"""FastAPI app: REST API + web UI + MCP endpoint.

Auth: one shared secret (NEUROSEARCH_APP_TOKEN). Accepted as
  - Authorization: Bearer <token>
  - a `ns_token` cookie (set by the web login form)
  - a path prefix for MCP clients that can't send headers:  /mcp/<token>
If NEUROSEARCH_APP_TOKEN is unset, everything is open (local use only!).
"""
from __future__ import annotations

import csv
import io
import logging
import re
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from . import db, ingest, jobs, qa
from .chunking import fmt_ts
from .config import settings
from .mcp_server import mcp
from .search import search, source_transcript

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


# ------------------------------------------------------------------ auth

def _token_ok(token: str | None) -> bool:
    if not settings.app_token:
        return True
    return bool(token) and secrets.compare_digest(token, settings.app_token)


def _request_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("ns_token")


def require_auth(request: Request) -> None:
    if not _token_ok(_request_token(request)):
        raise HTTPException(401, "unauthorized")


class TokenPathMiddleware:
    """Pure-ASGI: authenticate /mcp requests via `/mcp/<token>` path or Bearer header."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            path: str = scope["path"]
            parts = path.split("/", 3)  # ['', 'mcp', maybe-token, rest]
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            bearer = headers.get("authorization", "")
            bearer = bearer[7:].strip() if bearer.lower().startswith("bearer ") else None
            ok = _token_ok(bearer)
            rest = ""
            if not ok and len(parts) >= 3 and _token_ok(parts[2]):
                ok = True
                rest = parts[3] if len(parts) > 3 else ""
            elif len(parts) > 3:
                rest = parts[3]
            # normalise to /mcp/<rest> so the mounted app never has to redirect (a redirect drops the POST body)
            scope["path"] = "/mcp/" + rest
            scope["raw_path"] = scope["path"].encode()
            if not ok:
                resp = JSONResponse({"error": "unauthorized"}, status_code=401)
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ------------------------------------------------------------------- app

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init_db()
    jobs.start_workers()
    async with mcp.session_manager.run():
        yield
    jobs.stop_workers()


app = FastAPI(title="Neuro Search", lifespan=lifespan)
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
app.mount("/mcp", mcp_app)
app.add_middleware(TokenPathMiddleware)


@app.exception_handler(RuntimeError)
async def _runtime_error(_r: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


# ---------------------------------------------------------------- web ui

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    if not _token_ok(_request_token(request)):
        return HTMLResponse((WEB_DIR / "login.html").read_text())
    return HTMLResponse((WEB_DIR / "index.html").read_text())


@app.post("/login")
async def login(token: str = Form(...)) -> Any:
    if not _token_ok(token):
        return HTMLResponse((WEB_DIR / "login.html").read_text().replace("<!--ERR-->", "<p class=err>Wrong token.</p>"), status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("ns_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return resp


@app.get("/logout")
async def logout() -> Any:
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("ns_token")
    return resp


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, **db.source_stats()}


# --------------------------------------------------------------- ingest

class IngestIn(BaseModel):
    url: str
    tags: list[str] = []
    project_id: str | None = None
    force: bool = False


@app.post("/api/ingest", dependencies=[Depends(require_auth)])
async def api_ingest(body: IngestIn) -> dict[str, Any]:
    urls = [u.strip() for u in body.url.replace(",", "\n").splitlines() if u.strip()]
    if not urls:
        raise HTTPException(400, "no url")
    created = [jobs.enqueue("ingest_url", {"url": u, "tags": body.tags, "project_id": body.project_id, "force": body.force}) for u in urls]
    return {"jobs": [j["id"] for j in created]}


@app.post("/api/ingest/file", dependencies=[Depends(require_auth)])
async def api_ingest_file(file: UploadFile = File(...), title: str | None = Form(None),
                          project_id: str | None = Form(None), tags: str = Form("")) -> dict[str, Any]:
    """Upload audio/video (transcribed), PDF/DOCX/TXT (read as documents) or SRT/VTT. Runs as a background job."""
    name = Path(file.filename or "upload").name
    dest = settings.media_dir / f"upload_{secrets.token_hex(4)}_{name}"
    with open(dest, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    job = jobs.enqueue("ingest_file", {"path": str(dest), "name": name, "title": title or None,
                                       "tags": tag_list, "project_id": project_id or None})
    return {"job": job["id"], "name": name}


class TextIn(BaseModel):
    title: str
    text: str
    url: str | None = None
    tags: list[str] = []
    project_id: str | None = None


@app.post("/api/ingest/text", dependencies=[Depends(require_auth)])
async def api_ingest_text(body: TextIn) -> dict[str, Any]:
    return await anyio.to_thread.run_sync(
        lambda: ingest.ingest_text(body.title, body.text, url=body.url, tags=body.tags, project_id=body.project_id))


class ImportIn(BaseModel):
    payload: dict[str, Any]          # from ingest.extract_transcript (fields + segments + chapters)
    tags: list[str] = []
    project_id: str | None = None
    collection: dict[str, Any] | None = None


@app.post("/api/import", dependencies=[Depends(require_auth)])
async def api_import(body: ImportIn) -> dict[str, Any]:
    """Store a transcript extracted elsewhere (see `neurosearch ingest --remote`)."""
    return await anyio.to_thread.run_sync(
        lambda: ingest.store_transcript(body.payload, tags=body.tags, project_id=body.project_id, collection=body.collection))


@app.get("/api/jobs", dependencies=[Depends(require_auth)])
async def api_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return db.list_jobs(limit)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
async def api_job(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404)
    return j


@app.post("/api/sources/{source_id}/retry", dependencies=[Depends(require_auth)])
async def api_retry(source_id: str) -> dict[str, Any]:
    if not db.get_source(source_id):
        raise HTTPException(404)
    db.set_source_status(source_id, "pending")
    return {"job": jobs.enqueue("ingest_source", {"source_id": source_id})["id"]}


@app.post("/api/retry-failed", dependencies=[Depends(require_auth)])
async def api_retry_failed() -> dict[str, Any]:
    failed = db.list_sources(status="failed", limit=10000)
    for s in failed:
        db.set_source_status(s["id"], "pending")
        jobs.enqueue("ingest_source", {"source_id": s["id"]})
    return {"requeued": len(failed)}


# -------------------------------------------------------------- sources

@app.get("/api/stats", dependencies=[Depends(require_auth)])
async def api_stats() -> dict[str, Any]:
    return db.source_stats()


@app.get("/api/sources", dependencies=[Depends(require_auth)])
async def api_sources(status: str | None = None, collection_id: str | None = None, q: str | None = None,
                      project_id: str | None = None, not_in_project: str | None = None,
                      limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    rows = db.list_sources(status=status, collection_id=collection_id, query=q,
                           limit=limit if not (project_id or not_in_project) else 10000, offset=offset)
    if project_id:
        ids = set(db.project_source_ids(project_id, ready_only=False))
        rows = [r for r in rows if r["id"] in ids][:limit]
    elif not_in_project:
        ids = set(db.project_source_ids(not_in_project, ready_only=False))
        rows = [r for r in rows if r["id"] not in ids][:limit]
    return rows


@app.get("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
async def api_source(source_id: str) -> dict[str, Any]:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    s["segments"] = db.get_segments(source_id)
    return s


@app.delete("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
async def api_delete_source(source_id: str) -> dict[str, Any]:
    db.delete_source(source_id)
    return {"ok": True}


class TagsIn(BaseModel):
    tags: list[str]


@app.put("/api/sources/{source_id}/tags", dependencies=[Depends(require_auth)])
async def api_set_tags(source_id: str, body: TagsIn) -> dict[str, Any]:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    return db.upsert_source(platform=s["platform"], external_id=s["external_id"], tags=body.tags)


@app.get("/api/sources/{source_id}/transcript.txt", dependencies=[Depends(require_auth)])
async def api_transcript(source_id: str, timestamps: bool = True) -> Any:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    text = f"{s['title']}\n{s['url']}\n\n" + source_transcript(source_id, with_timestamps=timestamps)
    return StreamingResponse(io.StringIO(text), media_type="text/plain")


@app.get("/api/collections", dependencies=[Depends(require_auth)])
async def api_collections() -> list[dict[str, Any]]:
    return db.list_collections()


# --------------------------------------------------------------- export

@app.get("/api/export/sources.csv", dependencies=[Depends(require_auth)])
async def export_sources(project_id: str | None = None, collection_id: str | None = None) -> Any:
    """Master sheet: one row per source."""
    rows = db.list_sources(collection_id=collection_id, limit=100000)
    if project_id:
        ids = set(db.project_source_ids(project_id))
        rows = [r for r in rows if r["id"] in ids]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "title", "channel", "platform", "published", "duration", "url", "status", "transcript_kind", "tags", "transcript"])
    for r in rows:
        w.writerow([r["id"], r["title"], r["channel"], r["platform"], r["published_at"], fmt_ts(r["duration"] or 0),
                    r["url"], r["status"], r["transcript_kind"], ",".join(r.get("tags") or []),
                    source_transcript(r["id"], with_timestamps=False) if r["status"] == "ready" else ""])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=neurosearch_sources.csv"})


@app.get("/api/export/segments.csv", dependencies=[Depends(require_auth)])
async def export_segments(project_id: str | None = None, collection_id: str | None = None) -> Any:
    """Granular sheet: one row per timestamped chunk with a deep link."""
    from .search import deep_link
    rows = db.list_sources(collection_id=collection_id, status="ready", limit=100000)
    if project_id:
        ids = set(db.project_source_ids(project_id))
        rows = [r for r in rows if r["id"] in ids]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["source_id", "title", "channel", "published", "start", "end", "timestamp", "link", "text"])
    for r in rows:
        for c in db.get_chunks(r["id"]):
            w.writerow([r["id"], r["title"], r["channel"], r["published_at"], round(c["start"], 1), round(c["end"], 1),
                        fmt_ts(c["start"]), deep_link(r["url"], r["platform"], c["start"]), c["text"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=neurosearch_segments.csv"})


# ------------------------------------------------------------- projects

class ProjectIn(BaseModel):
    name: str
    brief: str | None = None
    tags: list[str] = []


@app.get("/api/projects", dependencies=[Depends(require_auth)])
async def api_projects() -> list[dict[str, Any]]:
    return db.list_projects()


@app.post("/api/projects", dependencies=[Depends(require_auth)])
async def api_create_project(body: ProjectIn) -> dict[str, Any]:
    return db.create_project(body.name, body.brief, body.tags)


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
async def api_project(project_id: str) -> dict[str, Any]:
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    p["notes"] = db.list_project_notes(project_id)
    p["conversations"] = db.list_conversations(project_id)
    return p


@app.put("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
async def api_update_project(project_id: str, body: ProjectIn) -> dict[str, Any]:
    p = db.update_project(project_id, name=body.name, brief=body.brief, tags=body.tags)
    if not p:
        raise HTTPException(404)
    return p


@app.delete("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
async def api_delete_project(project_id: str) -> dict[str, Any]:
    db.delete_project(project_id)
    return {"ok": True}


class MembersIn(BaseModel):
    source_ids: list[str] = []
    collection_ids: list[str] = []


@app.post("/api/projects/{project_id}/members", dependencies=[Depends(require_auth)])
async def api_add_members(project_id: str, body: MembersIn) -> dict[str, Any]:
    db.add_project_sources(project_id, body.source_ids)
    db.add_project_collections(project_id, body.collection_ids)
    return db.get_project(project_id) or {}


@app.delete("/api/projects/{project_id}/members", dependencies=[Depends(require_auth)])
async def api_remove_members(project_id: str, body: MembersIn) -> dict[str, Any]:
    db.remove_project_sources(project_id, body.source_ids)
    db.remove_project_collections(project_id, body.collection_ids)
    return db.get_project(project_id) or {}


@app.get("/api/projects/{project_id}/findings.md", dependencies=[Depends(require_auth)])
async def api_findings(project_id: str) -> Any:
    from .export import findings_markdown
    text = await anyio.to_thread.run_sync(lambda: findings_markdown(project_id))
    return StreamingResponse(iter([text]), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=findings.md"})


@app.get("/api/projects/{project_id}/masterplan.md", dependencies=[Depends(require_auth)])
async def api_masterplan_md(project_id: str) -> Any:
    from .export import synthesize_masterplan
    text = await anyio.to_thread.run_sync(lambda: synthesize_masterplan(project_id))
    return StreamingResponse(iter([text]), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=masterplan.md"})


@app.get("/api/projects/{project_id}/masterplan.zip", dependencies=[Depends(require_auth)])
async def api_masterplan_zip(project_id: str, synthesize: bool = True) -> Any:
    from .export import build_masterplan_zip
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    data = await anyio.to_thread.run_sync(lambda: build_masterplan_zip(project_id, synthesize=synthesize))
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", p["name"])[:40] or "project"
    return StreamingResponse(iter([data]), media_type="application/zip",
                             headers={"Content-Disposition": f"attachment; filename={fname}_masterplan.zip"})


@app.get("/api/projects/{project_id}/jobs", dependencies=[Depends(require_auth)])
async def api_project_jobs(project_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """Jobs belonging to this project: URL/file ingests queued for it, plus per-video jobs of its sources."""
    ids = set(db.project_source_ids(project_id, ready_only=False))
    out = []
    for j in db.list_jobs(limit=400):
        pl = j.get("payload") or {}
        if pl.get("project_id") == project_id or (j["kind"] == "ingest_source" and pl.get("source_id") in ids):
            out.append(j)
        if len(out) >= limit:
            break
    return out


class ConvIn(BaseModel):
    project_id: str | None = None
    title: str | None = None


@app.post("/api/conversations", dependencies=[Depends(require_auth)])
async def api_create_conversation(body: ConvIn) -> dict[str, Any]:
    return db.create_conversation(body.project_id, body.title)


@app.put("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
async def api_rename_conversation(conversation_id: str, body: ConvIn) -> dict[str, Any]:
    db.rename_conversation(conversation_id, body.title or "Untitled")
    return {"ok": True}


class NoteIn(BaseModel):
    content: str
    citations: list[dict[str, Any]] = []


@app.post("/api/projects/{project_id}/notes", dependencies=[Depends(require_auth)])
async def api_add_note(project_id: str, body: NoteIn) -> dict[str, Any]:
    return db.add_project_note(project_id, body.content, body.citations)


@app.delete("/api/notes/{note_id}", dependencies=[Depends(require_auth)])
async def api_delete_note(note_id: int) -> dict[str, Any]:
    db.delete_project_note(note_id)
    return {"ok": True}


# ----------------------------------------------------------- search / ask

@app.get("/api/search", dependencies=[Depends(require_auth)])
async def api_search(q: str, project_id: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    sids = None
    if project_id:
        sids = db.project_source_ids(project_id) or ["__none__"]
    return await anyio.to_thread.run_sync(lambda: search(q, limit=limit, source_ids=sids))


class AskIn(BaseModel):
    question: str
    project_id: str | None = None
    conversation_id: str | None = None
    use_web: bool = False


@app.post("/api/ask", dependencies=[Depends(require_auth)])
async def api_ask(body: AskIn) -> dict[str, Any]:
    cid = body.conversation_id or db.new_id()
    return await anyio.to_thread.run_sync(
        lambda: qa.ask(body.question, project_id=body.project_id, conversation_id=cid, use_web=body.use_web))


@app.get("/api/conversations", dependencies=[Depends(require_auth)])
async def api_conversations(project_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_conversations(project_id)


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
async def api_conversation(conversation_id: str) -> list[dict[str, Any]]:
    return db.get_messages(conversation_id, limit=200)


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
async def api_delete_conversation(conversation_id: str) -> dict[str, Any]:
    db.delete_conversation(conversation_id)
    return {"ok": True}
