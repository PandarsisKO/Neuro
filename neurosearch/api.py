"""FastAPI app: REST API + web UI + MCP endpoint.

Auth: one shared secret (NEUROSEARCH_APP_TOKEN). Accepted as
  - Authorization: Bearer <token>
  - a `ns_token` cookie (set by the web login form)
  - a path prefix for MCP clients that can't send headers:  /mcp/<token>
If NEUROSEARCH_APP_TOKEN is unset, everything is open (local use only!).
"""
from __future__ import annotations

import json
import csv
import io
import logging
import re
import time
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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
    from .logctx import configure
    configure(logging.INFO)
    __import__("neurosearch.schemas", fromlist=["check_installation"]).check_installation()
    db.init_db()
    if settings.fake_ai:
        logging.getLogger(__name__).warning("NEUROSEARCH_FAKE_AI=1 — every model call is served by the deterministic fakes")
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
# the browser extension calls the API from an extension origin; auth is the Bearer token, so open CORS is fine
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
EXT_DIR = Path(__file__).parent.parent / "extension"


@app.exception_handler(RuntimeError)
def _runtime_error(_r: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


# ---------------------------------------------------------------- web ui

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Any:
    if not _token_ok(_request_token(request)):
        return HTMLResponse((WEB_DIR / "login.html").read_text())
    return HTMLResponse((WEB_DIR / "index.html").read_text())


@app.post("/login")
def login(token: str = Form(...)) -> Any:
    if not _token_ok(token):
        return HTMLResponse((WEB_DIR / "login.html").read_text().replace("<!--ERR-->", "<p class=err>Wrong token.</p>"), status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("ns_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return resp


@app.get("/logout")
def logout() -> Any:
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("ns_token")
    return resp


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, **db.source_stats()}


# --------------------------------------------------------------- ingest

class IngestIn(BaseModel):
    url: str
    tags: list[str] = []
    project_id: str | None = None
    force: bool = False
    since_years: float | None = None   # channels/playlists: only videos newer than this (0 = all); default from settings
    max_videos: int | None = None      # channels/playlists: cap (0 = no cap); default from settings


@app.post("/api/ingest", dependencies=[Depends(require_auth)])
def api_ingest(body: IngestIn) -> dict[str, Any]:
    urls = [u.strip() for u in body.url.replace(",", "\n").splitlines() if u.strip()]
    if not urls:
        raise HTTPException(400, "no url")
    from .media import canonical_url
    # G1: the job's dedupe key is the CANONICAL url, so youtu.be/X and watch?v=X&si=… are one unit of work
    created = [jobs.enqueue("ingest_url", {"url": canonical_url(u), "tags": body.tags, "project_id": body.project_id, "force": body.force,
                                           "since_years": body.since_years, "max_videos": body.max_videos}) for u in urls]
    return {"jobs": [j["id"] for j in created]}


class CandidateActIn(BaseModel):
    project_id: str
    reason: str | None = None


@app.get("/api/projects/{project_id}/candidates", dependencies=[Depends(require_auth)])
def api_candidates(project_id: str, q: str | None = None, state: str | None = None, limit: int = 50) -> dict[str, Any]:
    """G3: the Discovery Candidate Index for a project — seen, not acquired. `q` = gap recall over cheap metadata."""
    from . import candidates
    if not db.get_project(project_id):
        raise HTTPException(404)
    items = candidates.search(project_id, q, limit=limit) if q else candidates.list_for_project(project_id, state=state, limit=limit)
    return {"items": items, "counts": candidates.counts(project_id)}


@app.post("/api/candidates/{candidate_id}/dismiss", dependencies=[Depends(require_auth)])
def api_candidate_dismiss(candidate_id: str, body: CandidateActIn) -> dict[str, Any]:
    from . import candidates
    return {"ok": True, "updated": candidates.dismiss(body.project_id, candidate_id, body.reason)}


@app.post("/api/candidates/{candidate_id}/restore", dependencies=[Depends(require_auth)])
def api_candidate_restore(candidate_id: str, body: CandidateActIn) -> dict[str, Any]:
    from . import candidates
    return {"ok": True, "updated": candidates.restore(body.project_id, candidate_id)}


@app.post("/api/candidates/{candidate_id}/acquire", dependencies=[Depends(require_auth)])
def api_candidate_acquire(candidate_id: str, body: CandidateActIn) -> dict[str, Any]:
    """Acquire a seen candidate through the NORMAL lifecycle (ingest_url → G1 identity): never a parallel path."""
    from . import candidates
    c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone())
    if not c:
        raise HTTPException(404)
    if c.get("source_id") and (db.get_source(c["source_id"]) or {}).get("status") == "ready":
        from . import identity
        r = identity.attach_existing(body.project_id, c["source_id"])                    # already owned: attach, no acquisition
        candidates.mark(body.project_id, [candidate_id], "acquired", "attached from the library")
        return {"ok": True, "job_id": None, "source_id": c["source_id"], "identity": r.state}
    job = jobs.enqueue("ingest_url", {"url": c["url"], "tags": [], "project_id": body.project_id, "force": False, "review": False})
    candidates.mark(body.project_id, [candidate_id], "acquired", body.reason or "acquired from the Candidate Index")
    return {"ok": True, "job_id": job["id"], "url": c["url"]}


class ClassifyIn(BaseModel):
    input: str


@app.post("/api/classify", dependencies=[Depends(require_auth)])
def api_classify(body: ClassifyIn) -> dict[str, Any]:
    """G2: what did the user paste? One classification per line (kind, label, detail, available actions). No network."""
    from . import resources
    return {"items": [c.as_dict() for c in resources.classify_many(body.input)]}


class AddIn(BaseModel):
    input: str
    action: str | None = None          # per-line override; None = each line's default action
    tags: list[str] = []
    force: bool = False
    since_years: float | None = None
    max_videos: int | None = None


@app.post("/api/projects/{project_id}/add", dependencies=[Depends(require_auth)])
def api_add(project_id: str, body: AddIn) -> dict[str, Any]:
    """G2: "Add something to research". Classifies every line and routes it to the standard lifecycle. A container
    (website, repository, community, feed, sitemap) is never fetched as a page unless action='page' is chosen."""
    from . import resources
    if not db.get_project(project_id):
        raise HTTPException(404)
    out = []
    for c in resources.classify_many(body.input):
        try:
            r = resources.route(c, project_id, body.action if body.action in {a["action"] for a in c.actions} else None,
                                tags=body.tags, since_years=body.since_years, max_videos=body.max_videos, force=body.force)
        except ValueError as e:
            r = {"kind": c.kind, "action": body.action, "queued": False, "note": str(e)}
        out.append({**c.as_dict(), "result": r})
    return {"items": out, "jobs": [i["result"]["job_id"] for i in out if i["result"].get("job_id")]}


@app.get("/api/usage", dependencies=[Depends(require_auth)])
def api_usage() -> dict[str, Any]:
    from . import usage
    t = usage.totals()
    ok, reason, _ = usage.check()
    t["blocked"] = None if ok else reason
    return t


class BudgetIn(BaseModel):
    daily: float | None = None
    monthly: float | None = None
    paused: bool | None = None


@app.post("/api/usage/budget", dependencies=[Depends(require_auth)])
def api_budget(body: BudgetIn) -> dict[str, Any]:
    from . import usage
    if body.daily is not None:
        db.kv_set("daily_budget", str(body.daily))
    if body.monthly is not None:
        db.kv_set("monthly_budget", str(body.monthly))
    if body.paused is not None:
        db.kv_set("queue_paused", "1" if body.paused else None)
    if body.paused is False or body.daily is not None or body.monthly is not None:
        # wake anything waiting on the valve — a raised budget or a Resume should take effect now, not at midnight
        with db.tx() as conn:
            conn.execute("UPDATE jobs SET not_before=NULL, message=NULL WHERE status='queued' AND (message LIKE 'paused:%' OR not_before IS NOT NULL)")
    return usage.totals()


class CancelIn(BaseModel):
    project_id: str | None = None


@app.post("/api/jobs/cancel-queued", dependencies=[Depends(require_auth)])
def api_cancel_queued(body: CancelIn) -> dict[str, Any]:
    """Stop everything that hasn't started. Queued videos go back to the Review card for later approval."""
    return {"cancelled": db.cancel_queued_jobs(project_id=body.project_id)}


@app.get("/api/projects/{project_id}/reviews", dependencies=[Depends(require_auth)])
def api_reviews(project_id: str) -> list[dict[str, Any]]:
    return db.pending_reviews(project_id)


class ApproveIn(BaseModel):
    source_ids: list[str] | None = None   # None = all proposed


class HtmlIn(BaseModel):
    url: str
    html: str
    title: str | None = None
    tags: list[str] = []


@app.post("/api/projects/{project_id}/ingest/html", dependencies=[Depends(require_auth)])
def api_ingest_html(project_id: str, body: HtmlIn) -> dict[str, Any]:
    """A page captured by the browser extension (for sites that block automated readers or need a login)."""
    if len(body.html) > 8_000_000:
        raise HTTPException(413, "page too large")
    return ingest.ingest_webpage(body.url, tags=body.tags, project_id=project_id, title=body.title, html=body.html)


class SessionIngestIn(BaseModel):
    url: str
    title: str | None = None
    cookies: list[dict[str, Any]] = []
    tags: list[str] = []


@app.post("/api/projects/{project_id}/ingest/with-session", dependencies=[Depends(require_auth)])
def api_ingest_with_session(project_id: str, body: SessionIngestIn) -> dict[str, Any]:
    """One video/post from a site that needs a login (Instagram reel, private Vimeo…): the extension lends the
    browser's cookies for that host; they are kept server-side only, one file per request."""
    import hashlib
    from .courses import write_cookie_file
    name = "session-" + hashlib.sha1(f"{body.url}{time.time()}".encode()).hexdigest()[:12]
    cookies_file = write_cookie_file(body.cookies, name) if body.cookies else None
    job = jobs.enqueue("ingest_url", {"url": body.url, "tags": body.tags, "project_id": project_id, "title": body.title,
                                      "cookies_file": cookies_file, "referer": body.url, "review": False})
    return {"job_id": job["id"], "cookies": bool(cookies_file)}


class RankIn(BaseModel):
    project_id: str | None = None
    want: int | None = None


@app.post("/api/collections/{collection_id}/rank", dependencies=[Depends(require_auth)])
def api_rank(collection_id: str, body: RankIn) -> dict[str, Any]:
    """(Re-)rank a pending review's videos by relevance to the project brief. Runs in the background."""
    meta = db.review_meta(collection_id)
    meta["ranked"] = False; meta.pop("rank_note", None)
    if body.want:
        meta["max_videos"] = body.want
    db.kv_set(f"review:{collection_id}", json.dumps(meta))
    job = db.create_job("rank_proposed", {"collection_id": collection_id, "project_id": body.project_id or meta.get("project_id"),
                                          "want": body.want or meta.get("max_videos")})
    return {"job_id": job["id"]}


@app.post("/api/collections/{collection_id}/approve", dependencies=[Depends(require_auth)])
def api_approve(collection_id: str, body: ApproveIn) -> dict[str, Any]:
    return ingest.approve_proposed(collection_id, body.source_ids)


@app.get("/api/defaults", dependencies=[Depends(require_auth)])
def api_defaults() -> dict[str, Any]:
    return {"since_years": settings.default_since_years, "max_videos": settings.default_max_videos}


@app.post("/api/ingest/file", dependencies=[Depends(require_auth)])
async def api_ingest_file(file: UploadFile = File(...), title: str | None = Form(None),
                          project_id: str | None = Form(None), tags: str = Form(""), immediate: bool = Form(False)) -> dict[str, Any]:
    """Upload audio/video (transcribed), PDF/DOCX/TXT (read as documents) or SRT/VTT. Runs as a background job.
    immediate=true (0.24.1, the chat's attach button): documents, spreadsheets, text and subtitle files are read,
    chunked and embedded inside this request through the very same `ingest_local_file` path (same global source
    row, same dedupe, same provenance) and the response carries the ready source; media still needs transcription
    and is queued exactly as before (the response says so)."""
    name = Path(file.filename or "upload").name
    dest = settings.media_dir / f"upload_{secrets.token_hex(4)}_{name}"
    with open(dest, "wb") as fh:
        while chunk := await file.read(1 << 20):
            fh.write(chunk)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    from .documents import is_media
    if immediate and not is_media(Path(name)):
        from . import ingest as _ingest
        try:
            res = await anyio.to_thread.run_sync(lambda: _ingest.ingest_local_file(dest, title or None, tag_list, project_id or None, original_name=name))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"could not read {name}: {e}") from e
        src = db.get_source(res["source_id"]) or {}
        return {"source_id": res["source_id"], "name": name, "title": src.get("title") or name, "ready": src.get("status") == "ready",
                "chunks": res.get("chunks"), "embedded": res.get("embedded"), "immediate": True}
    job = jobs.enqueue("ingest_file", {"path": str(dest), "name": name, "title": title or None,
                                       "tags": tag_list, "project_id": project_id or None})
    return {"job": job["id"], "name": name, "immediate": False,
            "note": "audio/video is transcribed in the background; it joins the project when ready" if immediate else None}


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
def api_jobs(limit: int = 50) -> list[dict[str, Any]]:
    out = db.list_jobs(limit)
    for j in out:
        _decorate_job(j)
    return out


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
def api_job(job_id: str) -> dict[str, Any]:
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404)
    _decorate_job(j)
    return j


class CalcIn(BaseModel):
    inputs: dict[str, Any] = {}
    outputs: list[str] | None = None


@app.get("/api/sources/{source_id}/calculator", dependencies=[Depends(require_auth)])
def api_calculator(source_id: str) -> dict[str, Any]:
    from .sheets import load_model
    try:
        return load_model(source_id)
    except RuntimeError as e:
        raise HTTPException(404, str(e))


@app.post("/api/sources/{source_id}/calculate", dependencies=[Depends(require_auth)])
def api_calculate(source_id: str, body: CalcIn) -> dict[str, Any]:
    from .sheets import calculate
    try:
        return calculate(source_id, body.inputs, body.outputs)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/sources/{source_id}/retry", dependencies=[Depends(require_auth)])
def api_retry(source_id: str) -> dict[str, Any]:
    src = db.get_source(source_id)
    if not src:
        raise HTTPException(404)
    return _retry_source(src)


def _retry_source(src: dict[str, Any]) -> dict[str, Any]:
    source_id = src["id"]
    if src["platform"] in ("spreadsheet", "document", "file"):
        # uploaded files: re-read the kept copy (spreadsheets keep theirs in data/files); otherwise ask for a re-upload
        from .sheets import files_dir
        name = src["url"].replace("file://", "")
        kept = next(iter(files_dir().glob(f"{source_id}.*")), None)
        if not kept:
            raise HTTPException(400, f"'{name}' isn't on disk any more — upload it again (drag it into Upload file) and it will replace this entry")
        import shutil, tempfile
        tmp = Path(tempfile.gettempdir()) / f"retry-{source_id}{kept.suffix}"
        shutil.copyfile(kept, tmp)
        db.set_source_status(source_id, "pending")
        return {"job": jobs.enqueue("ingest_file", {"path": str(tmp), "name": name, "title": src.get("title"), "tags": src.get("tags") or [],
                                                    "project_id": None})["id"]}
    db.set_source_status(source_id, "pending")
    if src["platform"] == "web" or (src["platform"] == "media" and not src.get("transcript_kind")):
        # links that never produced a transcript go back through the URL router (web page vs media detection)
        return {"job": jobs.enqueue("ingest_url", {"url": src["url"], "tags": src.get("tags") or [], "force": True, "review": False})["id"]}
    return {"job": jobs.enqueue("ingest_source", {"source_id": source_id})["id"]}


class ProjectIn(BaseModel):
    project_id: str


def _requeue_sources(project_id: str, status: str) -> dict[str, Any]:
    ids = set(db.project_source_ids(project_id, ready_only=False))
    n = 0
    for s in db.list_sources(status=status, limit=10000):
        if s["id"] not in ids:
            continue
        db.set_source_status(s["id"], "pending")
        if s["platform"] == "web" or (s["platform"] == "media" and not s.get("transcript_kind")):
            jobs.enqueue("ingest_url", {"url": s["url"], "tags": s.get("tags") or [], "force": True, "review": False, "project_id": project_id})
        else:
            jobs.enqueue("ingest_source", {"source_id": s["id"]})   # no min_date → the cutoff is deliberately ignored
        n += 1
    return {"queued": n}


@app.post("/api/sources/retry-skipped", dependencies=[Depends(require_auth)])
def api_retry_skipped(body: ProjectIn) -> dict[str, Any]:
    """Queue every skipped (older-than-cutoff) source of a project anyway."""
    return _requeue_sources(body.project_id, "skipped")


@app.post("/api/sources/retry-failed-in-project", dependencies=[Depends(require_auth)])
def api_retry_failed_in_project(body: ProjectIn) -> dict[str, Any]:
    return _requeue_sources(body.project_id, "failed")


@app.post("/api/retry-failed", dependencies=[Depends(require_auth)])
def api_retry_failed() -> dict[str, Any]:
    failed = db.list_sources(status="failed", limit=10000)
    for s in failed:
        db.set_source_status(s["id"], "pending")
        jobs.enqueue("ingest_source", {"source_id": s["id"]})
    return {"requeued": len(failed)}


# -------------------------------------------------------------- sources

@app.get("/api/version")
def api_version() -> dict[str, Any]:
    from . import __version__
    return {"version": __version__, "fake_ai": settings.fake_ai}


@app.get("/api/stats/fun", dependencies=[Depends(require_auth)])
def api_fun_stats(project_id: str | None = None) -> dict[str, Any]:
    return db.fun_stats(project_id)


@app.get("/api/health", dependencies=[Depends(require_auth)])
def api_health() -> dict[str, Any]:
    """Can I trust Neuro Search right now? Database integrity, verified backups, queue, validators, disk."""
    from .media import rate_limit_status
    h = db.health()
    h["sites"] = rate_limit_status()
    h["version"] = __import__("neurosearch").__version__
    return h


@app.post("/api/backup", dependencies=[Depends(require_auth)])
def api_backup() -> dict[str, Any]:
    chk = db.integrity_check()
    p = db.backup()
    return {"path": str(p), "integrity": chk, "verified": db.verify_database(p)}


@app.get("/api/validation-events", dependencies=[Depends(require_auth)])
def api_validation_events(kind: str | None = None, source_id: str | None = None, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Diagnostics: what the evidence validators rejected or repaired (never shown as findings, never lost)."""
    return db.validation_events(kind=kind, source_id=source_id, project_id=project_id, limit=limit)


@app.get("/api/stats", dependencies=[Depends(require_auth)])
def api_stats() -> dict[str, Any]:
    from .media import rate_limit_status
    return {**db.source_stats(), "youtube": rate_limit_status()}


@app.get("/api/sources", dependencies=[Depends(require_auth)])
def api_sources(status: str | None = None, collection_id: str | None = None, q: str | None = None,
                      project_id: str | None = None, not_in_project: str | None = None,
                      limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    rows = db.list_sources(status=status, collection_id=collection_id, query=q,
                           limit=limit if not (project_id or not_in_project) else 10000, offset=offset)
    if project_id:
        ids = set(db.project_source_ids(project_id, ready_only=False))
        rows = [r for r in rows if r["id"] in ids and r["status"] != "proposed"][:limit]
        counts = db.suggestion_counts(project_id)
        analysing = db.sources_being_analysed(project_id)
        live = db.live_job_by_source()
        analysed_ids = db.analysed_sources(project_id)
        analyses = db.project_analyses(project_id)
        prio = db.priority_source_ids(project_id)
        prov_keys = ("model", "provider", "prompt_version", "input_hash", "source_revision", "brief_revision", "status", "updated_at")
        for r in rows:
            kinds = analyses.get(r["id"]) or {}
            sm, rv = kinds.get("summary") or {}, kinds.get("relevance") or {}
            r["summary"], r["substance"] = sm.get("summary"), sm.get("substance")            # project-relative: what THIS brief made of the source
            r["relevance"], r["relevance_why"] = rv.get("relevance"), rv.get("relevance_why")
            r["analysis"] = {k: {pk: v.get(pk) for pk in prov_keys} for k, v in kinds.items()} or None   # per task, each with its own provenance
            r["legacy_analysis"] = any(v.get("status") == "legacy_unverified" for v in kinds.values())
            c = counts.get(r["id"], {})
            r["suggested"] = c.get("suggested", 0)
            r["approved"] = c.get("approved", 0)
            r["analysing"] = r["id"] in analysing
            r["analysed"] = r["id"] in counts or r["id"] in analysed_ids
            r["priority"] = r["id"] in prio
            j = live.get(r["id"])
            if j:
                r["job"] = j          # {status, message, position, updated_at}
    elif not_in_project:
        ids = set(db.project_source_ids(not_in_project, ready_only=False))
        rows = [r for r in rows if r["id"] not in ids][:limit]
    return rows


@app.get("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
def api_source(source_id: str) -> dict[str, Any]:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    s["segments"] = db.get_segments(source_id)
    s["analyses"] = [dict(r) for r in db.connect().execute("SELECT * FROM project_source_analysis WHERE source_id=?", (source_id,)).fetchall()]
    s["revision"] = s.get("revision") or db.source_revision(source_id)
    return s


@app.delete("/api/sources/{source_id}", dependencies=[Depends(require_auth)])
def api_delete_source(source_id: str) -> dict[str, Any]:
    touched = db.delete_source(source_id)
    return {"ok": True, "marked_removed": touched}


class TagsIn(BaseModel):
    tags: list[str]


@app.put("/api/sources/{source_id}/tags", dependencies=[Depends(require_auth)])
def api_set_tags(source_id: str, body: TagsIn) -> dict[str, Any]:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    return db.upsert_source(platform=s["platform"], external_id=s["external_id"], tags=body.tags)


@app.get("/api/sources/{source_id}/transcript.txt", dependencies=[Depends(require_auth)])
def api_transcript(source_id: str, timestamps: bool = True) -> Any:
    s = db.get_source(source_id)
    if not s:
        raise HTTPException(404)
    text = f"{s['title']}\n{s['url']}\n\n" + source_transcript(source_id, with_timestamps=timestamps)
    return StreamingResponse(io.StringIO(text), media_type="text/plain")


@app.get("/api/collections", dependencies=[Depends(require_auth)])
def api_collections() -> list[dict[str, Any]]:
    return db.list_collections()


# --------------------------------------------------------------- export

@app.get("/api/export/sources.csv", dependencies=[Depends(require_auth)])
def export_sources(project_id: str | None = None, collection_id: str | None = None) -> Any:
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
def export_segments(project_id: str | None = None, collection_id: str | None = None) -> Any:
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
    context: str | None = None
    goal: str | None = None
    audience: str | None = None
    output_pref: str | None = None
    source_prefs: str | None = None
    questions: list[str] | None = None
    # create-only extras
    facts: list[dict[str, str]] | None = None     # [{kind, content}]
    urls: list[str] | None = None                 # initial sources to ingest
    start_chats: bool = True                      # one chat per starting question


@app.get("/api/projects", dependencies=[Depends(require_auth)])
def api_projects() -> list[dict[str, Any]]:
    return db.list_projects()


@app.post("/api/projects", dependencies=[Depends(require_auth)])
def api_create_project(body: ProjectIn) -> dict[str, Any]:
    p = db.create_project(body.name, body.brief, body.tags)
    db.update_project(p["id"], context=body.context, goal=body.goal, audience=body.audience, output_pref=body.output_pref,
                      source_prefs=body.source_prefs, questions=body.questions or [])
    for f in body.facts or []:
        if f.get("content"):
            db.add_fact(p["id"], f.get("kind") or "constraint", f["content"])
    if body.start_chats:
        for q in body.questions or []:
            db.create_conversation(p["id"], q[:80])
    job_ids = []
    for u in body.urls or []:
        u = u.strip()
        if u:
            job_ids.append(jobs.enqueue("ingest_url", {"url": u, "tags": [], "project_id": p["id"]})["id"])
    out = db.get_project(p["id"]) or p
    out["jobs"] = job_ids
    return out


@app.get("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
def api_project(project_id: str) -> dict[str, Any]:
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(404)
    p["notes"] = db.list_project_notes(project_id)
    p["suggested"] = db.list_project_notes(project_id, status="suggested")
    p["conversations"] = db.list_conversations(project_id)
    p["facts"] = db.list_facts(project_id)
    p["has_plan"] = db.latest_plan(project_id) is not None
    return p


@app.put("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
def api_update_project(project_id: str, body: ProjectIn) -> dict[str, Any]:
    p = db.update_project(project_id, name=body.name, brief=body.brief, tags=body.tags, context=body.context, goal=body.goal,
                          audience=body.audience, output_pref=body.output_pref, source_prefs=body.source_prefs, questions=body.questions)
    if not p:
        raise HTTPException(404)
    return p


@app.delete("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
def api_delete_project(project_id: str) -> dict[str, Any]:
    db.delete_project(project_id)
    return {"ok": True}


class MembersIn(BaseModel):
    source_ids: list[str] = []
    collection_ids: list[str] = []


class PriorityIn(BaseModel):
    source_ids: list[str]
    priority: bool = True


@app.put("/api/projects/{project_id}/priority", dependencies=[Depends(require_auth)])
def api_set_priority(project_id: str, body: PriorityIn) -> dict[str, Any]:
    """Flag/unflag priority sources for THIS project (0.24.1): retrieval reserves excerpt slots for them."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    n = db.set_source_priority(project_id, body.source_ids, body.priority)
    return {"ok": True, "updated": n, "priority_source_ids": sorted(db.priority_source_ids(project_id))}


@app.post("/api/projects/{project_id}/members", dependencies=[Depends(require_auth)])
def api_add_members(project_id: str, body: MembersIn) -> dict[str, Any]:
    """Library → project. G1: the same resolver as every other entrance (attach, reuse, project-relative analysis)."""
    from . import identity
    states: dict[str, str] = {}
    for sid in body.source_ids:
        try:
            states[sid] = identity.attach_existing(project_id, sid).state
        except KeyError:
            raise HTTPException(404, f"unknown source {sid}") from None
    db.add_project_collections(project_id, body.collection_ids)
    if body.collection_ids:
        for sid in db.sources_needing_suggestions(project_id):
            jobs.enqueue_suggestions(sid, project_id)
    return {**(db.get_project(project_id) or {}), "identity": states}


@app.delete("/api/projects/{project_id}/members", dependencies=[Depends(require_auth)])
def api_remove_members(project_id: str, body: MembersIn) -> dict[str, Any]:
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
def api_project_jobs(project_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """Jobs belonging to this project: URL/file ingests queued for it, plus per-video jobs of its sources."""
    ids = set(db.project_source_ids(project_id, ready_only=False))
    out = []
    for j in db.list_jobs(limit=400):
        pl = j.get("payload") or {}
        if pl.get("project_id") == project_id or (j["kind"] == "ingest_source" and pl.get("source_id") in ids):
            out.append(j)
        if len(out) >= limit:
            break
    titles = db.source_titles({sid for j in out for sid in ((j.get("payload") or {}).get("source_ids") or [(j.get("payload") or {}).get("source_id")]) if sid})
    for j in out:
        pl = j.get("payload") or {}
        sids = pl.get("source_ids") or ([pl["source_id"]] if pl.get("source_id") else [])
        if sids:
            j["label"] = titles.get(sids[0], sids[0]) + (f" +{len(sids) - 1} more" if len(sids) > 1 else "")
        _decorate_job(j, titles)
    return out


def _decorate_job(j: dict[str, Any], titles: dict[str, str] | None = None) -> None:
    j["state"] = db.derived_status(j)
    if j["state"] == "provider_wait":
        from . import breakers
        j["provider_wait"] = {"operation": j.get("wait_operation"), "label": breakers.LABELS.get(j.get("wait_operation") or "", j.get("wait_operation")),
                              "until": j.get("not_before"), "message": breakers.wait_message(j.get("wait_operation") or "", j.get("not_before"))}
    if j.get("kind") == "suggest_findings_batch":
        from . import batches
        j["batch"] = batches.ui_state(j)
    if j.get("blocked_by"):
        rep = db.dependency_report(j)
        for x in rep["failed"] + rep["cancelled"]:
            if titles and x.get("label") in titles:
                x["label"] = titles[x["label"]]
        j["dependencies"] = rep


@app.get("/api/jobs/{job_id}/events", dependencies=[Depends(require_auth)])
def api_job_events(job_id: str) -> list[dict[str, Any]]:
    """The job's history: queued, claimed (worker, run), stages, waits, lease expiry/recovery, external handles, outcome."""
    return db.job_events(job_id)


@app.post("/api/jobs/{job_id}/retry", dependencies=[Depends(require_auth)])
def api_retry_job(job_id: str) -> dict[str, Any]:
    """Try a failed job again (fresh attempt, same input)."""
    j = db.get_job(job_id)
    if j and j["status"] == "failed" and j["kind"] == "ingest_source":
        src = db.get_source((j.get("payload") or {}).get("source_id") or "")
        if src and src["platform"] in ("spreadsheet", "document", "file", "web", "media"):
            # uploaded files / pages must go through their own reader, never the video downloader
            db.update_job(job_id, status="done", message=f"retried via source — {j.get('message') or ''}"[:500])
            return {"job_id": _retry_source(src)["job"]}
    new = db.retry_job(job_id)
    if not new:
        raise HTTPException(409, "only failed jobs can be retried")
    return {"job_id": new["id"]}


class RetryAllIn(BaseModel):
    project_id: str | None = None


@app.post("/api/jobs/retry-failed", dependencies=[Depends(require_auth)])
def api_retry_failed(body: RetryAllIn) -> dict[str, Any]:
    """Re-queue every failed job of the last 48 h (optionally one project)."""
    n = 0
    for j in db.failed_jobs(body.project_id):
        if db.retry_job(j["id"]):
            n += 1
    return {"retried": n}


@app.post("/api/jobs/{job_id}/dismiss", dependencies=[Depends(require_auth)])
def api_dismiss_job(job_id: str) -> dict[str, Any]:
    """Hide a failed job from the In-progress card (keeps the error in the history)."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] != "failed":
        raise HTTPException(409, "only failed jobs can be dismissed")
    db.update_job(job_id, status="done", message=f"dismissed — {j.get('message') or 'failed'}"[:500])
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_auth)])
def api_cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel one queued job. A queued video goes back to the Review card; running jobs can't be interrupted."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j["status"] in db.JOB_TERMINAL:
        raise HTTPException(409, f"job is already {j['status']}")
    was = j["status"]
    st = db.request_cancel(job_id)
    note = "will stop at its next safe point; nothing is written after that" if st == "running" else None
    if j["kind"] == "suggest_findings_batch" and was == "external_pending":
        from . import batches
        h = batches.cancel_job(j)                       # tell the provider, keep what already completed
        note = f"batch cancelled at the provider; {h.get('materialized', 0)} source(s) with complete results were kept"
    return {"cancelled": 1 if st == "cancelled" else 0, "status": st, "note": note}


class ConvIn(BaseModel):
    project_id: str | None = None
    title: str | None = None


@app.post("/api/conversations", dependencies=[Depends(require_auth)])
def api_create_conversation(body: ConvIn) -> dict[str, Any]:
    return db.create_conversation(body.project_id, body.title)


@app.put("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
def api_rename_conversation(conversation_id: str, body: ConvIn) -> dict[str, Any]:
    db.rename_conversation(conversation_id, body.title or "Untitled")
    return {"ok": True}


# ------------------------------------------------------------ planner

class FactIn(BaseModel):
    kind: str = "decision"
    content: str


@app.get("/api/projects/{project_id}/facts", dependencies=[Depends(require_auth)])
def api_facts(project_id: str) -> list[dict[str, Any]]:
    return db.list_facts(project_id)


@app.post("/api/projects/{project_id}/facts", dependencies=[Depends(require_auth)])
def api_add_fact(project_id: str, body: FactIn) -> dict[str, Any]:
    return db.add_fact(project_id, body.kind, body.content)


@app.delete("/api/facts/{fact_id}", dependencies=[Depends(require_auth)])
def api_delete_fact(fact_id: int) -> dict[str, Any]:
    db.delete_fact(fact_id)
    return {"ok": True}


class BuildIn(BaseModel):
    instructions: str | None = None
    background: bool = False   # True → {"job_id"}; poll /api/jobs/{id}


@app.get("/api/projects/{project_id}/plan", dependencies=[Depends(require_auth)])
def api_plan(project_id: str) -> dict[str, Any]:
    from . import planner
    plan = db.latest_plan(project_id)
    versions = db.list_plans(project_id)
    for v in versions:                                  # older versions are superseded, never "current"
        v["label"] = "current" if plan and v["id"] == plan["id"] else "superseded"
    return {"plan": plan, "research_changed": planner.research_changed(project_id) if plan else False, "versions": versions}


@app.get("/api/projects/{project_id}/staleness", dependencies=[Depends(require_auth)])
def api_staleness(project_id: str) -> dict[str, Any]:
    """Which artifacts no longer reflect the project (brief/facts/sources changed) and what a rebuild would cost.
    Pure computation — never launches analysis."""
    from . import staleness
    return staleness.assess(project_id)


class RebuildIn(BaseModel):
    what: list[str] | None = None          # findings | plan
    source_ids: list[str] | None = None
    transport: str = "interactive"         # findings rebuild: interactive (now) | batch (background); the plan is never batched


@app.post("/api/projects/{project_id}/rebuild-stale", dependencies=[Depends(require_auth)])
def api_rebuild_stale(project_id: str, body: RebuildIn) -> dict[str, Any]:
    """Queue stale artifacts for regeneration as ordinary jobs (each passes the budget valve on its own)."""
    from . import staleness
    if body.transport not in ("interactive", "batch"):
        raise HTTPException(400, "transport must be 'interactive' or 'batch'")
    return staleness.rebuild(project_id, body.what, body.source_ids, transport=body.transport)


@app.post("/api/projects/{project_id}/plan/build", dependencies=[Depends(require_auth)])
async def api_plan_build(project_id: str, body: BuildIn) -> dict[str, Any]:
    from . import planner
    if body.background:
        return {"job_id": jobs.enqueue("build_plan", {"project_id": project_id, "instructions": body.instructions})["id"]}
    return await anyio.to_thread.run_sync(lambda: planner.build_plan(project_id, body.instructions))


@app.post("/api/projects/{project_id}/plan/check-updates", dependencies=[Depends(require_auth)])
async def api_plan_check(project_id: str) -> dict[str, Any]:
    from . import planner, providers
    try:
        ups = await anyio.to_thread.run_sync(lambda: planner.suggest_updates(project_id))
    except providers.OutputError as e:          # typed: the model's output could not be used — say so, never "no updates"
        raise HTTPException(status_code=502, detail=f"Master Planner could not check for updates: {e}") from e
    return {"updates": ups, "plan": db.latest_plan(project_id)}


class UpdateStatusIn(BaseModel):
    status: str  # accepted | rejected


@app.post("/api/plan-updates/{update_id}", dependencies=[Depends(require_auth)])
def api_plan_update_status(update_id: int, body: UpdateStatusIn) -> dict[str, Any]:
    row = db.set_update_status(update_id, body.status)
    if not row:
        raise HTTPException(404)
    return row


@app.post("/api/projects/{project_id}/plan/apply", dependencies=[Depends(require_auth)])
async def api_plan_apply(project_id: str) -> dict[str, Any]:
    from . import planner
    return await anyio.to_thread.run_sync(lambda: planner.apply_accepted_updates(project_id))


class ItemIn(BaseModel):
    status: str
    note: str | None = None


@app.put("/api/plans/{plan_id}/items/{key}", dependencies=[Depends(require_auth)])
def api_plan_item(plan_id: str, key: str, body: ItemIn) -> dict[str, Any]:
    db.set_item_status(plan_id, key, body.status, body.note)
    return {"ok": True}


@app.post("/api/plans/{plan_id}/start", dependencies=[Depends(require_auth)])
def api_plan_start(plan_id: str) -> dict[str, Any]:
    plan = db.get_plan(plan_id)
    if not plan:
        raise HTTPException(404)
    db.set_plan_status(plan_id, "started")
    for i, _ in enumerate(plan["plan"].get("first_steps") or []):
        if plan["items"].get(f"first_steps.{i}", {}).get("status", "not_started") == "not_started":
            db.set_item_status(plan_id, f"first_steps.{i}", "ready")
    db.update_project(plan["project_id"], mode="execute")
    return db.get_plan(plan_id) or {}


@app.get("/api/projects/{project_id}/plan.md", dependencies=[Depends(require_auth)])
def api_plan_md(project_id: str) -> Any:
    from .planner import plan_markdown
    plan, p = db.latest_plan(project_id), db.get_project(project_id)
    if not plan or not p:
        raise HTTPException(404, "no plan yet")
    return StreamingResponse(iter([plan_markdown(plan, p)]), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=master_plan.md"})


@app.get("/api/projects/{project_id}/plan.html", dependencies=[Depends(require_auth)])
def api_plan_html(project_id: str) -> Any:
    from .planner import plan_html
    plan, p = db.latest_plan(project_id), db.get_project(project_id)
    if not plan or not p:
        raise HTTPException(404, "no plan yet")
    return HTMLResponse(plan_html(plan, p))


class DiscoverIn(BaseModel):
    refine: str | None = None
    background: bool = False   # True → returns {"job_id"}; poll /api/jobs/{id}
    mode: str = "library_first"   # G4: library_first | library_only | web_first | web_only


@app.get("/api/projects/{project_id}/discoveries", dependencies=[Depends(require_auth)])
def api_discoveries(project_id: str) -> list[dict[str, Any]]:
    return db.list_discoveries(project_id)


@app.post("/api/projects/{project_id}/discover", dependencies=[Depends(require_auth)])
async def api_discover(project_id: str, body: DiscoverIn) -> dict[str, Any]:
    if body.background:
        job = jobs.enqueue("discover", {"project_id": project_id, "refine": body.refine, "mode": body.mode})
        return {"job_id": job["id"]}
    from .discover import discover
    return await anyio.to_thread.run_sync(lambda: discover(project_id, body.refine, mode=body.mode))


@app.get("/api/projects/{project_id}/library/recall", dependencies=[Depends(require_auth)])
async def api_library_recall(project_id: str, q: str, limit: int = 8) -> dict[str, Any]:
    """G4: what the user already owns (outside this project) that could answer q — suggestions with provenance, never attached."""
    from . import library
    if not db.get_project(project_id):
        raise HTTPException(404)
    return await anyio.to_thread.run_sync(lambda: library.recall(project_id, q, limit=limit))


# ---- G5 (0.29.0): Knowledge Map, Claims, Evidence Targets, Research Tensions — project research STATE, suggestion-first

class ResearchRefreshIn(BaseModel):
    extract: bool = False        # allow ONE bounded normalization pass now (model call); default is the $0 path


@app.get("/api/projects/{project_id}/research", dependencies=[Depends(require_auth)])
def api_research(project_id: str) -> dict[str, Any]:
    from . import knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    return knowledge.state(project_id)


@app.post("/api/projects/{project_id}/research/refresh", dependencies=[Depends(require_auth)])
async def api_research_refresh(project_id: str, body: ResearchRefreshIn) -> dict[str, Any]:
    """Harvest candidate Claims from findings ($0), assess, detect tensions, rebuild the map; with extract=true also run
    the lazy normalization contract inline (bounded) or queue it as a job when the backlog is large."""
    from . import claims, knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    res = await anyio.to_thread.run_sync(lambda: claims.ensure(project_id, allow_model=body.extract))
    res["state"] = knowledge.state(project_id)
    return res


class EvalIn(BaseModel):
    budget: int = 150            # bounded by design: decision-relevant Claims + a stratified sample, never the corpus


@app.post("/api/projects/{project_id}/research/evaluate", dependencies=[Depends(require_auth)])
def api_research_evaluate(project_id: str, body: EvalIn) -> dict[str, Any]:
    """G5.1: one durable, bounded normalization evaluation (a job). Measures merges, qualifier/hedge preservation,
    topic grouping, tensions and cost so broader normalization has to earn adoption."""
    from . import claims
    if not db.get_project(project_id):
        raise HTTPException(404)
    job = db.create_job("extract_claims", {"project_id": project_id, "evaluation": True, "budget": max(10, min(body.budget, 300)), "reason": "bounded normalization evaluation"})
    return {"job_id": job["id"], "cohort_preview": claims.select_cohort(project_id, max(10, min(body.budget, 300)))["by_reason"]}


@app.get("/api/projects/{project_id}/research/evaluation", dependencies=[Depends(require_auth)])
def api_research_evaluation(project_id: str) -> dict[str, Any]:
    from . import claims
    return claims.evaluation_report(project_id) or {"none": True}


class ClaimIn(BaseModel):
    text: str
    claim_type: str = "other"
    topic: str | None = None
    qualifiers: dict[str, Any] | None = None
    needs_evidence: bool = True   # external factual Claim → also opens an Evidence Target; False = record only


@app.post("/api/projects/{project_id}/claims", dependencies=[Depends(require_auth)])
def api_claim_add(project_id: str, body: ClaimIn) -> dict[str, Any]:
    from . import claims, knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    c = claims.add_claim(project_id, body.text, claim_type=body.claim_type, topic=body.topic, qualifiers=body.qualifiers, origin="user", status="proposed", normalized=True)
    tgt = None
    if body.needs_evidence:
        suff = "governing" if body.claim_type in claims.GOVERNING_TYPES else "corroborative"
        tgt = knowledge.add_target(project_id, f"Establish: {body.text[:160]}", topic=c["topic"], claim_id=c["id"], sufficiency=suff, origin="user")
    knowledge.refresh(project_id)
    return {"claim": claims.get(c["id"]), "target": tgt}


class ClaimStatusIn(BaseModel):
    status: str                      # proposed | accepted | rejected
    application: str | None = None   # established | developing | unknown


@app.post("/api/claims/{claim_id}/status", dependencies=[Depends(require_auth)])
def api_claim_status(claim_id: str, body: ClaimStatusIn) -> dict[str, Any]:
    from . import claims, knowledge
    c = claims.get(claim_id)
    if not c:
        raise HTTPException(404)
    try:
        out = claims.set_status(claim_id, body.status, application=body.application)
    except ValueError as e:
        raise HTTPException(400, str(e))
    knowledge.refresh(c["project_id"])
    return out or {}


class ClaimRelateIn(BaseModel):
    related_claim_id: str
    relation: str = "CONTRADICTS"


@app.post("/api/claims/{claim_id}/relate", dependencies=[Depends(require_auth)])
def api_claim_relate(claim_id: str, body: ClaimRelateIn) -> dict[str, Any]:
    """Scope is checked first: a CONTRADICTS across different jurisdiction/product/timeframe/conditions becomes QUALIFIES."""
    from . import claims, knowledge
    c = claims.get(claim_id)
    if not c:
        raise HTTPException(404)
    try:
        res = claims.relate(claim_id, body.related_claim_id, body.relation)
    except ValueError as e:
        raise HTTPException(400, str(e))
    knowledge.refresh(c["project_id"])
    return res


class TargetIn(BaseModel):
    question: str
    sufficiency: str = "corroborative"
    topic: str | None = None
    preferred_classes: list[str] | None = None
    closure: str | None = None


@app.post("/api/projects/{project_id}/targets", dependencies=[Depends(require_auth)])
def api_target_add(project_id: str, body: TargetIn) -> dict[str, Any]:
    from . import knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    tg = knowledge.add_target(project_id, body.question, topic=body.topic, sufficiency=body.sufficiency, preferred_classes=body.preferred_classes, closure=body.closure, origin="user")
    if not tg:
        raise HTTPException(400, "question too short")
    knowledge.refresh(project_id)
    return tg


@app.get("/api/projects/{project_id}/targets", dependencies=[Depends(require_auth)])
def api_targets_list(project_id: str, status: str | None = None, origin: str | None = None, q: str | None = None, limit: int = 100) -> dict[str, Any]:
    from . import knowledge
    rows = knowledge.list_targets(project_id, status=status)
    if origin:
        rows = [t for t in rows if t.get("origin") == origin]
    if q:
        ql = q.lower()
        rows = [t for t in rows if ql in (t.get("question") or "").lower()]
    return {"total": len(rows), "targets": rows[:limit]}


class PursueIn(BaseModel):
    external: bool = False       # step 4 (a web Discover job) only when asked


@app.post("/api/targets/{target_id}/pursue", dependencies=[Depends(require_auth)])
async def api_target_pursue(target_id: str, body: PursueIn) -> dict[str, Any]:
    """Project evidence → global library → candidate index (reranked against THIS target, skipped ones resurfaced) → external."""
    from . import knowledge
    if not knowledge.get_target(target_id):
        raise HTTPException(404)
    return await anyio.to_thread.run_sync(lambda: knowledge.pursue(target_id, external=body.external))


class TargetStatusIn(BaseModel):
    status: str   # open | satisfied | closed_by_user


@app.post("/api/targets/{target_id}/status", dependencies=[Depends(require_auth)])
def api_target_status(target_id: str, body: TargetStatusIn) -> dict[str, Any]:
    from . import knowledge
    tg = knowledge.get_target(target_id)
    if not tg:
        raise HTTPException(404)
    try:
        out = knowledge.set_target_status(target_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    knowledge.refresh(tg["project_id"])
    return out or {}


class TensionStatusIn(BaseModel):
    status: str   # open | resolved | dismissed


@app.post("/api/tensions/{tension_id}/status", dependencies=[Depends(require_auth)])
def api_tension_status(tension_id: str, body: TensionStatusIn) -> dict[str, Any]:
    from . import knowledge
    row = db.connect().execute("SELECT project_id FROM research_tensions WHERE id=?", (tension_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    try:
        knowledge.set_tension_status(tension_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    knowledge.refresh(row["project_id"])
    return {"ok": True}


@app.get("/api/sources/{source_id}/profile", dependencies=[Depends(require_auth)])
def api_source_profile(source_id: str) -> dict[str, Any]:
    """The project-neutral Source Profile (baseline + enriched if present)."""
    from . import library
    p = library.profile(source_id)
    if p is None:
        raise HTTPException(404, "no profile (source not ready)")
    return p


class EnrichIn(BaseModel):
    source_ids: list[str] | None = None     # None = the wanted queue
    limit: int = 3
    batch: bool = False                     # queue the wanted profiles as ONE batch job instead (50%)


@app.post("/api/library/enrich", dependencies=[Depends(require_auth)])
async def api_library_enrich(body: EnrichIn) -> dict[str, Any]:
    """Enrich profiles on request: a few inline, or the whole wanted queue as an opportunistic batch. Never automatic
    across the library."""
    from . import library
    if body.batch:
        return library.maybe_queue_batch(force=True) or {"job_id": None, "note": "nothing wanted"}
    return await anyio.to_thread.run_sync(lambda: library.enrich_wanted(limit=min(body.limit, 10), source_ids=body.source_ids))


@app.get("/api/library/stats", dependencies=[Depends(require_auth)])
def api_library_stats() -> dict[str, Any]:
    from . import library
    return library.stats()


class DiscStatusIn(BaseModel):
    status: str   # added | dismissed | new


@app.post("/api/discoveries/{disc_id}/status", dependencies=[Depends(require_auth)])
def api_discovery_status(disc_id: int, body: DiscStatusIn) -> dict[str, Any]:
    row = db.set_discovery_status(disc_id, body.status)
    if not row:
        raise HTTPException(404)
    return row


# --------------------------------------------------------- course import

class CourseImportIn(BaseModel):
    course: dict[str, Any]
    lessons: list[dict[str, Any]]
    cookies: list[dict[str, Any]] | None = None


@app.post("/api/projects/{project_id}/course-import", dependencies=[Depends(require_auth)])
def api_course_import(project_id: str, body: CourseImportIn) -> dict[str, Any]:
    from .courses import import_course
    return import_course(project_id, body.course, body.lessons, body.cookies)


@app.get("/extension.zip")
def extension_zip(request: Request) -> Any:
    """The course-importer browser extension, zipped for download (sign-in required)."""
    if not _token_ok(_request_token(request)):
        raise HTTPException(401)
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXT_DIR.glob("*")):
            if f.is_file():
                z.write(f, f"neurosearch-course-importer/{f.name}")
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=neurosearch-course-importer.zip"})


@app.get("/api/whoami")
def api_whoami(request: Request) -> dict[str, Any]:
    """Addresses this server is reachable at (for the extension setup)."""
    import socket
    host = request.headers.get("host", "")
    lan = None
    try:
        s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s_.connect(("8.8.8.8", 80)); lan = s_.getsockname()[0]; s_.close()
    except OSError:
        pass
    port = host.split(":")[1] if ":" in host else "80"
    return {"host": host, "lan_url": f"http://{lan}:{port}" if lan else None, "hostname": socket.gethostname()}


class SuggestIn(BaseModel):
    source_ids: list[str] | None = None   # default: every ready source not yet analysed for this project
    force: bool = False                    # re-analyse even if already done
    transport: str = "interactive"         # interactive (analyze now) | batch (analyze in background) — explicit, per request


@app.post("/api/projects/{project_id}/suggest", dependencies=[Depends(require_auth)])
def api_suggest(project_id: str, body: SuggestIn) -> dict[str, Any]:
    ids = body.source_ids or (db.project_source_ids(project_id) if body.force else db.sources_needing_suggestions(project_id))
    if not ids:
        return {"job": None, "sources": 0, "transport": body.transport}
    if body.transport not in ("interactive", "batch"):
        raise HTTPException(400, "transport must be 'interactive' or 'batch'")
    if body.transport == "batch":
        job = jobs.enqueue("suggest_findings_batch", {"project_id": project_id, "source_ids": ids, "force": body.force})
    else:
        job = jobs.enqueue("suggest_findings", {"project_id": project_id, "source_ids": ids, "force": body.force})
    return {"job": job["id"], "sources": len(ids), "transport": body.transport}


class EstimateIn(BaseModel):
    source_ids: list[str] | None = None
    force: bool = False
    exact: bool = True                     # count tokens with the provider (cached per input) — falls back to the character estimate


@app.post("/api/projects/{project_id}/suggest/estimate", dependencies=[Depends(require_auth)])
def api_suggest_estimate(project_id: str, body: EstimateIn) -> dict[str, Any]:
    """Both quotes for the analyze-now / analyze-in-background choice (model cost only), the recommendation and its basis."""
    from . import batches
    ids = body.source_ids or (db.project_source_ids(project_id) if body.force else db.sources_needing_suggestions(project_id))
    if not ids:
        return {"items": 0, "sources": 0, "now": 0.0, "background": 0.0, "recommended": "now", "basis": "estimate", "choices": batches.CHOICES, "note": ""}
    return batches.estimate(project_id, ids, force=body.force, exact=body.exact)


class NoteStatusIn(BaseModel):
    status: str  # approved | dismissed | suggested


@app.post("/api/notes/{note_id}/status", dependencies=[Depends(require_auth)])
def api_note_status(note_id: int, body: NoteStatusIn) -> dict[str, Any]:
    row = db.set_note_status(note_id, body.status)
    if not row:
        raise HTTPException(404)
    return row


class BulkNotesIn(BaseModel):
    note_ids: list[int]
    status: str


@app.post("/api/notes/bulk-status", dependencies=[Depends(require_auth)])
def api_notes_bulk(body: BulkNotesIn) -> dict[str, Any]:
    for nid in body.note_ids:
        db.set_note_status(nid, body.status)
    return {"ok": True, "n": len(body.note_ids)}


class NoteIn(BaseModel):
    content: str
    citations: list[dict[str, Any]] = []


@app.post("/api/projects/{project_id}/notes", dependencies=[Depends(require_auth)])
def api_add_note(project_id: str, body: NoteIn) -> dict[str, Any]:
    return db.add_project_note(project_id, body.content, body.citations)


@app.delete("/api/notes/{note_id}", dependencies=[Depends(require_auth)])
def api_delete_note(note_id: int) -> dict[str, Any]:
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
    attached_source_ids: list[str] | None = None      # sources uploaded with this message (0.24.1)


@app.post("/api/ask", dependencies=[Depends(require_auth)])
async def api_ask(body: AskIn) -> dict[str, Any]:
    cid = body.conversation_id or db.new_id()
    return await anyio.to_thread.run_sync(
        lambda: qa.ask(body.question, project_id=body.project_id, conversation_id=cid, use_web=body.use_web,
                       attached_source_ids=body.attached_source_ids or None))


@app.get("/api/conversations", dependencies=[Depends(require_auth)])
def api_conversations(project_id: str | None = None) -> list[dict[str, Any]]:
    return db.list_conversations(project_id)


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
def api_conversation(conversation_id: str) -> list[dict[str, Any]]:
    return db.get_messages(conversation_id, limit=200)


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
def api_delete_conversation(conversation_id: str) -> dict[str, Any]:
    db.delete_conversation(conversation_id)
    return {"ok": True}
