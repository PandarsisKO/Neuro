"""FastAPI app: REST API + web UI + MCP endpoint.

Auth: one shared secret (NEUROSEARCH_APP_TOKEN). Accepted as
  - Authorization: Bearer <token>
  - a `ns_token` cookie (set by the web login form)
  - a path prefix for MCP clients that can't send headers:  /mcp/<token>
If NEUROSEARCH_APP_TOKEN is unset, everything is open (local use only!).
"""
from __future__ import annotations

import asyncio
import contextlib
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

from . import bootstrap, cache, db, ingest, jobs, perf, qa
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


LIST_DESCRIPTION_CHARS = 200      # R2: the Sources list shows one ellipsised line; the full text stays on /api/sources/{id}


class PerfMiddleware:
    """Pure-ASGI (R0, SPEED-MISSION.md): time every /api request under its ROUTE TEMPLATE. Keying on the raw
    path would mint a new counter per project/source id and measure nothing; Starlette fills `scope["route"]`
    during routing, so it is read after the call rather than before."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/api"):
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            route = scope.get("route")
            key = getattr(route, "path", None) or str(scope.get("path", "?"))
            perf.record(f"{scope.get('method', 'GET')} {key}", time.perf_counter() - t0)


app = FastAPI(title="Neuro Search", lifespan=lifespan)
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
app.mount("/mcp", mcp_app)
app.add_middleware(PerfMiddleware)
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


class ScholarSearchIn(BaseModel):
    query: str
    limit: int = 10
    open_access_only: bool = False
    remember: bool = True


@app.get("/api/scholar/status", dependencies=[Depends(require_auth)])
def api_scholar_status() -> dict[str, Any]:
    """Which research catalogues are usable and why — config only, no network, no spend."""
    from . import scholar
    return {"providers": scholar.available(), "ready": scholar.ready_providers(),
            "note": "Crossref needs no account (an email in NEUROSEARCH_SCHOLAR_EMAIL earns the higher polite-pool "
                    "limits); OpenAlex has required a free key in OPENALEX_API_KEY since 2026-02-13."}


@app.post("/api/projects/{project_id}/scholar/search", dependencies=[Depends(require_auth)])
def api_scholar_search(project_id: str, body: ScholarSearchIn) -> dict[str, Any]:
    """Search Crossref/OpenAlex directly. $0 and no model call. Results are remembered as candidates (seen, not
    acquired) unless `remember` is false — nothing is attached to the project and nothing becomes evidence."""
    from . import scholar
    if not db.get_project(project_id):
        raise HTTPException(404)
    try:
        recs = scholar.search(body.query, limit=max(1, min(body.limit, scholar.MAX_ROWS)),
                              open_access_only=body.open_access_only)
    except scholar.ScholarUnavailable as e:
        raise HTTPException(503, f"{e.provider}: {e.reason}" + (f" — {e.detail}" if e.detail else "")) from e
    ids = scholar.to_candidates(recs, project_id, origin={"kind": "user_query", "query": body.query}) if body.remember else []
    return {"found": len(recs), "open_access": sum(1 for r in recs if r["oa_pdf_url"]), "candidate_ids": ids,
            "records": [{k: v for k, v in r.items()} for r in recs]}


@app.get("/api/projects/{project_id}/pool", dependencies=[Depends(require_auth)])
def api_pool(project_id: str, q: str | None = None, rank_by: str = "fit", limit: int = 100, kind: str = "all") -> dict[str, Any]:
    """S5: the known-but-uncaptured pool — skipped (pre-cutoff) sources + Candidate Index rows, ranked by a $0 potential scan."""
    from . import candidates
    if not db.get_project(project_id):
        raise HTTPException(404)
    return candidates.pool(project_id, q=q, rank_by=rank_by, limit=max(1, min(limit, 500)), kind=kind)


class PoolCaptureIn(BaseModel):
    kind: str = "all"          # all | skipped | candidates — same meaning as the pool's own `kind`
    rank_by: str = "fit"
    q: str | None = None
    min_potential: int = 40    # the pool's own "worth a look" line (candidates._potential ≥ 40)
    limit: int = 20


@app.post("/api/projects/{project_id}/pool/capture-many", dependencies=[Depends(require_auth)])
def api_pool_capture_many(project_id: str, body: PoolCaptureIn) -> dict[str, Any]:
    """S5: 'capture the N that fit' — every pool item at or above a potential threshold, up to `limit`, in ONE action.
    Exactly the per-item paths a single Capture click takes (retry for skipped, attach-or-acquire for a candidate) —
    never a parallel path — so a bulk capture behaves identically to clicking each row by hand."""
    from . import candidates, identity
    if not db.get_project(project_id):
        raise HTTPException(404)
    r = candidates.pool(project_id, q=body.q, rank_by=body.rank_by, limit=2000, kind=body.kind)
    chosen = [i for i in r["items"] if i["potential"] >= body.min_potential][:max(1, min(body.limit, 200))]
    captured: list[str] = []
    jobs_queued = attached = 0
    failed: list[str] = []
    for i in chosen:
        try:
            if i["kind"] == "skipped":
                src = db.get_source(i["id"])
                if not src:
                    failed.append(i["id"]); continue
                _retry_source(src)
                jobs_queued += 1
            else:
                cid = i["id"]
                c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone())
                if not c:
                    failed.append(cid); continue
                if c.get("source_id") and (db.get_source(c["source_id"]) or {}).get("status") == "ready":
                    identity.attach_existing(project_id, c["source_id"])       # already owned: attach, no acquisition
                    candidates.mark(project_id, [cid], "acquired", "attached from the library")
                    attached += 1
                else:
                    jobs.enqueue("ingest_url", {"url": c["url"], "tags": [], "project_id": project_id, "force": False, "review": False})
                    jobs_queued += 1
            captured.append(i["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("pool capture-many: %s failed: %s", i["id"], e)
            failed.append(i["id"])
    return {"captured": len(captured), "jobs_queued": jobs_queued, "attached": attached, "failed": len(failed),
            "considered": len(chosen), "available_above_threshold": sum(1 for i in r["items"] if i["potential"] >= body.min_potential),
            "min_potential": body.min_potential,
            "line": (f"{attached} attached from the library" + (" · " if attached and jobs_queued else "") + (f"{jobs_queued} capture{'s' if jobs_queued != 1 else ''} queued" if jobs_queued else "")
                    ) if captured else "nothing at or above that threshold"}


@app.post("/api/projects/{project_id}/sources/refresh-skipped-metadata", dependencies=[Depends(require_auth)])
def api_refresh_skipped_metadata(project_id: str, only_missing: bool = True) -> dict[str, Any]:
    """0.45.7 backfill: sources skipped before the ingest.ingest_source fix kept only the listing stage's bare title
    — no thumbnail. Queues one $0 refresh_skipped_metadata job per skipped source in this project (metadata only, no
    download, no status change) so an already-skipped row can catch up. `only_missing=true` (default) queues only
    rows with no thumbnail_url yet, so a repeat press doesn't re-fetch what already has real metadata.
    0.45.10: lane='low' — Kyle, live: transcribing a newly added source and ranking a review card are work he
    actually asked for or is watching; refreshing metadata for sources already skipped (content not yet known to
    be worth using) is speculative and must never make those wait, so it's claimed only once nothing else is."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    ids = set(db.project_source_ids(project_id, ready_only=False))
    rows = [s for s in db.list_sources(status="skipped", limit=100000) if s["id"] in ids and (not only_missing or not s.get("thumbnail_url"))]
    for s in rows:
        jobs.enqueue("refresh_skipped_metadata", {"source_id": s["id"], "project_id": project_id}, lane="low")
    return {"queued": len(rows)}


@app.get("/api/projects/{project_id}/sources/caption-recovery", dependencies=[Depends(require_auth)])
def api_caption_recovery_preview(project_id: str) -> dict[str, Any]:
    """$0 preview: which ready sources said nothing out loud but carry real text in their caption."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    rows = ingest.caption_recovery_candidates(project_id)
    return {"candidates": rows, "count": len(rows)}


@app.post("/api/projects/{project_id}/sources/caption-recovery", dependencies=[Depends(require_auth)])
def api_caption_recovery(project_id: str) -> dict[str, Any]:
    """Kyle, live: short-form video that is music plus on-screen text yields nothing today. New ingests recover the
    caption automatically (`ingest.recover_caption_text`); this backfills the ones already in the library. `low`
    lane — it is speculative repair of sources that are already sitting there, and must never displace the work the
    user is watching. No model call beyond re-embedding the new chunks."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    rows = ingest.caption_recovery_candidates(project_id)
    for r in rows:
        jobs.enqueue("recover_captions", {"source_id": r["id"], "project_id": project_id}, lane="low")
    return {"queued": len(rows)}


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
    cap = float(db.kv_get("providers:spend_cap_until") or 0)
    if cap and cap > time.time():
        t["account_limit_until"] = cap
        t["blocked"] = t["blocked"] or f"the Anthropic account's usage limit is reached — access returns {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(cap))}"
    bcap = float(db.kv_get("providers:billing_until") or 0)
    if bcap and bcap > time.time():
        t["billing_blocked_until"] = bcap
        t["blocked"] = t["blocked"] or "the Anthropic account's credit balance is too low — add credits in Plans & Billing to continue"
    from . import claude_code
    t["background_paused"] = db.background_paused()
    t["rate"] = usage.rate_gate()
    t["local_ai"] = {**claude_code.health(wait=False), "profile": settings.ai_profile, "line": claude_code.status_line(), "avoided_month": usage.avoided_this_month(),
                     "split": usage.local_split()}                       # L4: "N AI calls · % local · $ actual · $ avoided" (this month)
    return t


class JobPolicyIn(BaseModel):
    policy: str    # local_preferred | local_only | api_requested | api_only


@app.put("/api/jobs/{job_id}/policy", dependencies=[Depends(require_auth)])
def api_job_policy(job_id: str, body: JobPolicyIn) -> dict[str, Any]:
    """L1: the user's explicit choice of provider for a queued job (api_requested = 'answer now with the API' — never implied by slowness)."""
    if body.policy not in db.EXECUTION_POLICIES:
        raise HTTPException(400, f"policy must be one of {', '.join(db.EXECUTION_POLICIES)}")
    if not db.get_job(job_id):
        raise HTTPException(404)
    return db.set_job_policy(job_id, body.policy) or {}


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
    from . import acquire
    waiting = acquire.request_for(body.url, project_id)          # B1: the page a parked job is waiting for → that job, that source
    if waiting and waiting.get("adapter") == "web_page":
        return {**acquire.resolve_capture(waiting["job_id"], {"contract": "page_capture/1", "method": "dom", "html": body.html, "title": body.title}), "resolved_pending": True,
                "kind": "web", "title": body.title, "segments": 0}
    return ingest.ingest_webpage(body.url, tags=body.tags, project_id=project_id, title=body.title, html=body.html)


class ThreadIn(BaseModel):
    url: str
    listing: Any = None               # Reddit's [link listing, comment listing] JSON, fetched inside the user's browser (extension 1.4)
    capture: dict[str, Any] | None = None   # the reddit_thread_capture/1 contract (extension 1.5+)
    title: str | None = None
    tags: list[str] = []


@app.post("/api/projects/{project_id}/ingest/thread", dependencies=[Depends(require_auth)])
async def api_ingest_thread(project_id: str, body: ThreadIn) -> dict[str, Any]:
    """A community thread read inside the user's own browser (the extension's "Send this page" on a Reddit thread).
    Reddit refuses every non-browser client since 2026-06-30; the browser is the user's legitimate reader, and the
    thread goes through the very same acquisition path as a server-side read (`community.acquire_thread`)."""
    from . import acquire, community
    if not db.get_project(project_id):
        raise HTTPException(404)
    if not community.is_reddit_thread(body.url):
        raise HTTPException(400, "not a Reddit thread URL")
    if body.listing is None and body.capture is None:
        raise HTTPException(400, "no thread content (listing or capture)")
    if len(json.dumps(body.listing if body.capture is None else body.capture, default=str)) > 12_000_000:
        raise HTTPException(413, "thread too large")
    capture = body.capture if body.capture is not None else {"contract": "reddit_thread_capture/1", "method": "json", "listing": body.listing}
    # B1: if this thread is what a parked job is waiting for, the capture resolves THAT job (same source), never a parallel acquisition
    waiting = acquire.request_for(body.url, project_id)
    if waiting:
        return {**acquire.resolve_capture(waiting["job_id"], capture), "resolved_pending": True}
    try:
        return await anyio.to_thread.run_sync(lambda: community.acquire_thread(body.url, tags=body.tags, project_id=project_id, capture=capture))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


# --------------------------------------------------------------- B1: browser-assisted acquisition

class CaptureIn(BaseModel):
    contract: str | None = None          # reddit_thread_capture/1 | page_capture/1
    method: str | None = None            # json | dom
    url: str | None = None
    thread: dict[str, Any] | None = None
    comments: list[dict[str, Any]] | None = None
    listing: Any = None
    html: str | None = None
    title: str | None = None
    capture: dict[str, Any] | None = None   # completeness diagnostics (B2)


@app.get("/api/capture/pending", dependencies=[Depends(require_auth)])
def api_capture_pending(project_id: str | None = None, url: str | None = None) -> dict[str, Any]:
    """What the user's browser is being asked to capture (the Browser Capture queue). Content addresses only — never cookies."""
    from . import acquire
    return {"items": acquire.pending_captures(project_id=project_id, url=url), "extension": acquire.extension_status()}


@app.post("/api/capture/{job_id}", dependencies=[Depends(require_auth)])
def api_capture_resolve(job_id: str, body: CaptureIn) -> dict[str, Any]:
    """The extension delivers what the browser saw for a waiting request; the SAME job completes the SAME source."""
    from . import acquire
    payload = body.model_dump(exclude_none=True)
    if not (payload.get("thread") or payload.get("listing") is not None or payload.get("html")):
        raise HTTPException(400, "the capture carries no content (thread/listing or html)")
    try:
        return acquire.resolve_capture(job_id, payload)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(413, str(e))


@app.delete("/api/capture/{job_id}", dependencies=[Depends(require_auth)])
def api_capture_cancel(job_id: str) -> dict[str, Any]:
    from . import acquire
    if not acquire.cancel_capture(job_id):
        raise HTTPException(404, "no browser capture is waiting on that job")
    return {"ok": True}


class CaptureBestIn(BaseModel):
    n: int = 3


@app.get("/api/targets/{target_id}/known", dependencies=[Depends(require_auth)])
def api_target_known(target_id: str) -> dict[str, Any]:
    """B3: the promising sources already known for this open question but not captured (Candidate Index links)."""
    from . import knowledge
    tg = knowledge.get_target(target_id)
    if not tg:
        raise HTTPException(404)
    return knowledge.known_evidence(tg["project_id"], target_id, limit=5)


@app.post("/api/targets/{target_id}/capture-best", dependencies=[Depends(require_auth)])
def api_target_capture_best(target_id: str, body: CaptureBestIn) -> dict[str, Any]:
    """B3: acquire the best known sources for an open question through the normal path (attach → ingest job → browser when needed)."""
    from . import knowledge
    tg = knowledge.get_target(target_id)
    if not tg:
        raise HTTPException(404)
    return knowledge.capture_best(tg["project_id"], target_id, n=body.n)


class LinkDismissIn(BaseModel):
    project_id: str
    kind: str
    ref_id: str


@app.post("/api/candidates/{candidate_id}/dismiss-link", dependencies=[Depends(require_auth)])
def api_candidate_dismiss_link(candidate_id: str, body: LinkDismissIn) -> dict[str, Any]:
    """B3: 'not useful for this question' — the link is dismissed; the candidate itself stays known."""
    from . import candidates
    return {"ok": True, "updated": candidates.dismiss_link(body.project_id, candidate_id, body.kind, body.ref_id)}


class ShareIn(BaseModel):
    text: str
    citations: list[dict[str, Any]] = []
    length: str = "short"
    project_id: str | None = None


@app.post("/api/share", dependencies=[Depends(require_auth)])
def api_share(body: ShareIn) -> dict[str, Any]:
    """C0 Portable Answers: a shorter version of a finished answer for sharing (one model call; never a new research pass).
    The client re-attaches the sources and evidence warnings exactly as Copy ▾ does."""
    from . import qa, usage
    if not body.text.strip():
        raise HTTPException(400, "nothing to share")
    usage.guard()
    try:
        return qa.share_variant(body.text, body.citations, body.length, project_id=body.project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


class HeartbeatIn(BaseModel):
    version: str | None = None


@app.post("/api/extension/heartbeat", dependencies=[Depends(require_auth)])
def api_extension_heartbeat(body: HeartbeatIn) -> dict[str, Any]:
    """The extension checks in (every few minutes and when opened): presence for the UI, and the pending count for its badge."""
    from . import acquire
    st = acquire.heartbeat(body.version)
    return {"extension": st, "pending": len(acquire.pending_captures())}


@app.get("/api/projects/{project_id}/attention", dependencies=[Depends(require_auth)])
def api_attention(project_id: str) -> dict[str, Any]:
    """One line's worth of what needs the user in this project's acquisition (browser captures waiting, extension state)."""
    from . import acquire
    if not db.get_project(project_id):
        raise HTTPException(404)
    return acquire.attention(project_id)


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
                                          "want": body.want or meta.get("max_videos")}, lane="priority")
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


class ProjectRefIn(BaseModel):
    project_id: str


@app.post("/api/sources/clear-failed-in-project", dependencies=[Depends(require_auth)])
def api_clear_failed_in_project(body: ProjectRefIn) -> dict[str, Any]:
    """0.34.2 — force-clear the project's failed sources: cancel every job that could recreate them (queued / waiting /
    running / browser-parked jobs naming the source or its URL), exclude them from this project (a marker that survives
    collection links, tag matches and retries), and delete the source row outright when no other project holds it and
    it never produced content. Nothing cited elsewhere is touched."""
    pid = body.project_id
    if not db.get_project(pid):
        raise HTTPException(404)
    ids = set(db.project_source_ids(pid, ready_only=False))
    failed = [s for s in db.list_sources(status="failed", limit=10000) if s["id"] in ids]
    failed += [s for s in db.list_sources(status="pending", limit=10000) if s["id"] in ids and (s.get("error_class") or "").startswith("browser_solvable:")]
    conn = db.connect()
    urls = {s["url"] for s in failed}
    sids = {s["id"] for s in failed}
    cancelled = 0
    for j in conn.execute("SELECT id, status, payload FROM jobs WHERE status IN ('queued','running','external_pending')").fetchall():
        try:
            pl = json.loads(j["payload"] or "{}")
        except ValueError:
            continue
        if pl.get("source_id") in sids or (pl.get("url") and pl["url"] in urls) or any(x in sids for x in (pl.get("source_ids") or [])):
            db.request_cancel(j["id"])
            cancelled += 1
    excluded = deleted = 0
    for s in failed:
        others = [p for p in db.projects_for_source(s["id"]) if p != pid]
        has_content = conn.execute("SELECT 1 FROM chunks WHERE source_id=? LIMIT 1", (s["id"],)).fetchone() is not None
        cited = conn.execute("SELECT 1 FROM project_notes WHERE citations LIKE ? LIMIT 1", (f"%{s['id']}%",)).fetchone() is not None
        if not others and not has_content and not cited:
            db.delete_source(s["id"])
            deleted += 1
        else:
            db.remove_project_sources(pid, [s["id"]])
            excluded += 1
    return {"ok": True, "cleared": len(failed), "deleted": deleted, "excluded": excluded, "jobs_cancelled": cancelled}


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
    from . import claude_code
    from . import usage
    h["local_ai"] = {**claude_code.health(wait=False), "profile": settings.ai_profile, "line": claude_code.status_line(), "split": usage.local_split()}
    h["perf"] = {"slowest": perf.slowest(5), "caches": perf.snapshot()["caches"]}   # R0: in-memory, no query cost
    return h


class BackgroundPauseIn(BaseModel):
    paused: bool
    project_id: str | None = None


@app.post("/api/jobs/background-pause", dependencies=[Depends(require_auth)])
def api_background_pause(body: BackgroundPauseIn) -> dict[str, Any]:
    """Kyle: "I need it to get out of the way of 'real' work when I start adding new sources or do something on my
    own ... manual pause and resume would be good." The existing queue pause stops everything including the work he
    just started, so it was never the right control. This holds only the speculative lanes (`slow`/`low`: bulk claim
    passes, caption recovery, metadata backfill) while his own ingests, findings and ranking keep running.

    Resuming re-triggers the paused work rather than waiting for some later event to notice it should exist."""
    out = db.set_background_paused(body.paused)
    if not body.paused and body.project_id:
        from . import claims
        job = claims.maybe_extract(body.project_id, "resumed by you", force=True)
        out["requeued"] = bool(job)
    return out


@app.post("/api/usage/rate-resume", dependencies=[Depends(require_auth)])
def api_rate_resume() -> dict[str, Any]:
    """The user's explicit "carry on" after the spend-rate ceiling held paid background work. Like the account
    Re-check, this retires a belief the app formed on its own — it is not a fact, and only the user may clear it."""
    from . import usage
    usage.clear_rate_gate()
    return {"ok": True, **usage.rate_gate()}


@app.post("/api/usage/recheck", dependencies=[Depends(require_auth)])
def api_usage_recheck() -> dict[str, Any]:
    """Kyle, live: "I don't think that cap is real. I expanded the cap manually." He was right, and it was a bug —
    `providers:spend_cap_until` was set on SPEND_CAP and cleared nowhere, so raising the limit in the Anthropic
    Console could not unblock the app; the stored date gated everything and also parked every job, so no call was
    ever made that could discover the block had lifted. Successful calls now clear the gates on their own; this is
    the manual lever for the case where nothing is willing to make that first call. Clearing costs nothing: if the
    block is still real the next attempt re-sets it, and a usage-limit or credit refusal fails before generation."""
    from . import claude_code, usage
    cleared = db.clear_account_gates()
    unparked = db.release_budget_waits()
    # Kyle, live: "the probe from 5 minutes ago is not of any use to us now that I literally changed the cap 1
    # minute ago." Exactly right, and the same defect one layer over: `claude_code.health` caches its verdict for
    # HEALTH_TTL (10 min), so after the user fixes something the app keeps reporting the old answer and nothing in
    # the UI could ask for a new one. Re-check now forces a fresh probe too — `wait=False` so it runs in the
    # background instead of holding this request for up to PROBE_TIMEOUT.
    local = claude_code.health(force=True, wait=False)
    t = usage.totals()
    ok, reason, _ = usage.check()
    return {"cleared": cleared, "jobs_released": unparked, "blocked": None if ok else reason,
            "today": t["today"], "month": t["month"],
            "local_ai": {"state": local.get("state"), "rechecking": bool(local.get("checking"))}}


@app.get("/api/perf", dependencies=[Depends(require_auth)])
def api_perf(days: int = 7) -> dict[str, Any]:
    """R0 (SPEED-MISSION.md) — the measurement contract the whole speed ladder reports against. Joins this
    process's in-memory timings (endpoints, caches, time-to-first-token) with queue wait and model latency read
    from the durable tables, so §A's baseline regenerates itself from live data instead of being a one-off
    measurement session. Read on demand from the Health console, never polled."""
    since = time.time() - max(days, 1) * 86400
    return {**perf.snapshot(), "queue": db.job_timing(since), "models": db.model_timing(since), "window_days": days}


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
    # R2 (SPEED-MISSION.md): this endpoint measured 2.53 s p50 on Kyle's live server against <0.1 s for every
    # other polled endpoint, while the UI polls it every 3 s. The per-stage timings below are what say WHICH
    # part costs that, so the fix lands on the measured bottleneck instead of the assumed one. They stay after
    # the fix: the same breakdown is how the improvement gets verified, and how a regression would be noticed.
    with perf.timed("sources:list"):
        rows = db.list_sources(status=status, collection_id=collection_id, query=q,
                               limit=limit if not (project_id or not_in_project) else 10000, offset=offset)
    if project_id:
        with perf.timed("sources:membership"):
            ids = set(db.project_source_ids(project_id, ready_only=False))
            rows = [r for r in rows if r["id"] in ids and r["status"] != "proposed"][:limit]
        with perf.timed("sources:lookups"):
            counts = db.suggestion_counts(project_id)
            analysing = db.sources_being_analysed(project_id)
            live = db.live_job_by_source()
            ajobs = db.analysis_jobs_by_source(project_id)
            from . import acquire
            browser = acquire.pending_by_source()
            analysed_ids = db.analysed_sources(project_id)
            analyses = db.project_analyses(project_id)
            prio = db.priority_source_ids(project_id)
        prov_keys = ("model", "provider", "prompt_version", "input_hash", "source_revision", "brief_revision", "status", "updated_at", "depth")
        from . import sources_value, staleness
        with perf.timed("sources:value"):
            values = sources_value.compute(project_id)                                    # S2: what each source gave (one pass)
        with perf.timed("sources:staleness"):
            # 0.26 s and, after R2 part 1, 75% of what the endpoint still costs. `assess` reads the project row,
            # its analyses, every source revision AND live job state, so it is keyed on all three revisions rather
            # than the research one alone — job churn must invalidate it, or a source would keep reporting
            # "rebuilding" after its job finished. Cost estimates inside the result also depend on the observed
            # spend rate, which is NOT in the key: an estimate drifting by a few cents between recomputes is
            # cosmetic, where a wrong CURRENT/STALE verdict would not be.
            view_rev = db.project_view_revision(project_id)
            try:
                stale_by = cache.get_or_compute(
                    f"staleness:{project_id}", f"{view_rev['research']}|{view_rev['sources']}|{view_rev['jobs']}",
                    lambda: {x["source_id"]: x for x in staleness.assess(project_id)["sources"]},
                    label="staleness")
            except Exception:  # noqa: BLE001
                stale_by = {}
        # a skipped (pre-cutoff) source used to show up with no thumbnail and no hint of whether it's worth
        # ingesting anyway — the same $0 potential scan the pool already runs (candidates.pool) works row by row too.
        pot_qs = pot_vocab = None
        pot_rel: dict[str, Any] = {}
        research_rev = ""
        with perf.timed("sources:potential_setup"):
            if any(r.get("status") == "skipped" for r in rows):
                # 0.45.7 added this scan so a pre-cutoff source shows whether it is still worth ingesting, and it
                # ran `research_view.questions`/`areas` on EVERY request — measured at 1.52 s of the endpoint's
                # 2.58 s p50, on a 3 s poll (SPEED-MISSION.md R2). It depends only on project research state, so
                # it is now computed once per revision of that state and reused until the state actually changes.
                from . import candidates as candidates_mod
                research_rev = db.project_research_revision(project_id)
                pot_qs, pot_vocab, pot_rel = cache.get_or_compute(
                    f"gap_terms:{project_id}", research_rev,
                    lambda: (*candidates_mod._gap_terms(project_id), db.project_analysis(project_id, "relevance")),
                    label="gap_terms")
        _rows_t0 = time.perf_counter()
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
            r["reserve"] = c.get("reserve", 0)          # D1: extracted beyond the cap, lower importance — promotable, never exported
            r["depth"] = sm.get("depth")                # D2: 'deep' when Read deeper produced the current analysis
            from . import findings as findings_mod
            r["long"] = findings_mod.is_long(r)         # D2/D3: a book or ≥ 45 min — a candidate for Read deeper
            r["analysing"] = r["id"] in analysing
            if r["id"] in ajobs:
                r["analysis_job"] = ajobs[r["id"]]          # 0.42.1: "reading deeper · part 3/12 · 41 findings so far"
            r["analysed"] = r["id"] in counts or r["id"] in analysed_ids
            r["under_read"] = bool(r["long"] and r.get("depth") != "deep" and r["analysed"] and (r["approved"] + r["suggested"]) <= findings_mod.CAP_BASE)
            v = values.get(r["id"]) or sources_value.empty()
            st = stale_by.get(r["id"]) or {}
            r["value"] = {"score": v["value_score"], "label": v["label"], "matters": v["matters"], "never_used": v["never_used"], "used": v["used"],
                          "claims": v["claims"], "importance": v["importance"], "stale": st.get("status") in ("stale", "legacy_unverified"),
                          "stale_status": st.get("status"), "stale_reasons": st.get("reasons") or []}
            r["priority"] = r["id"] in prio
            if r.get("status") == "skipped" and pot_qs is not None:
                # 452 skipped rows on Kyle's project, each re-scored on every poll (0.68 s of the endpoint). The
                # score is a pure function of the source's own words and the project's research state, so it is
                # keyed on BOTH revisions: the source's `updated_at` (already on the row, so free) catches a
                # metadata refresh changing the title/description that the research revision would not.
                rr = pot_rel.get(r["id"]) or {}
                r["pool_potential"] = cache.get_or_compute(
                    f"potential:{project_id}:{r['id']}", f"{research_rev}@{r.get('updated_at')}",
                    lambda rr=rr, r=r: dict(zip(("score", "fits", "why"), candidates_mod._potential(
                        r.get("title") or "", r.get("description") or "", pot_qs, pot_vocab, rr.get("relevance"), []))),
                    label="potential")
            j = live.get(r["id"])
            if j:
                r["job"] = j          # {status, message, position, updated_at}
            if r.get("completeness"):
                try:
                    r["completeness"] = json.loads(r["completeness"])
                except ValueError:
                    r["completeness"] = None
            b = browser.get(r["id"])
            if b:
                r["acquisition"] = {"state": "requires_browser", "job_id": b["job_id"], "reason": b["reason"], "status": b["status"], "url": b["canonical_url"] or r["url"]}
            elif (r.get("error_class") or "").startswith("browser_solvable:"):
                r["acquisition"] = {"state": "requires_browser", "job_id": None, "reason": r.get("error"), "status": "needs_request", "url": r["url"]}
        # R2 part 3: `description` measured 2,135 KB of this response's 4,026 KB — 53%, for a field the list renders
        # as one ellipsised muted line and only when a source has no duration. The drawer and the reader fetch the
        # source again through /api/sources/{id}, so they still get it whole; only the LIST copy is clipped.
        for r in rows:
            d = r.get("description")
            if d and len(d) > LIST_DESCRIPTION_CHARS:
                r["description"] = d[:LIST_DESCRIPTION_CHARS] + "…"
        perf.record("sources:rows", time.perf_counter() - _rows_t0)
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
    if s.get("platform") == "book":            # G6P1: the publication's own structure, per segment
        s["sections"] = [dict(r) for r in db.connect().execute("SELECT ordinal, spine_index, href, fragment, chapter, chapter_no, section, role, depth, label, chars FROM book_sections WHERE source_id=? ORDER BY ordinal", (source_id,)).fetchall()]
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
    # R1: name + goal is the whole required form. `brief` remains the model-facing steering text every task reads;
    # when the user has not written one it is seeded from the goal, so nothing downstream has to learn a new field.
    brief = (body.brief or "").strip() or (body.goal or "").strip() or None
    p = db.create_project(body.name, brief, body.tags)
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
    # BOOTSTRAP R2: a project that knows what it is for starts searching what the user already owns, immediately.
    if (out.get("goal") or out.get("brief") or "").strip():
        try:
            out["bootstrap_job"] = jobs.enqueue("bootstrap_scan", {"project_id": p["id"]}, lane="priority")["id"]
        except Exception as e:  # noqa: BLE001 — a project must exist even if its scan cannot be queued
            log.warning("bootstrap could not be queued for %s: %s", p["id"][:8], e)
    return out


# ---------------------------------------------------------------- Mission BOOTSTRAP (R2/R3): starting research

class BootstrapDecideIn(BaseModel):
    source_ids: list[str]
    decision: str = "attach"          # attach | dismiss


@app.post("/api/projects/{project_id}/bootstrap", dependencies=[Depends(require_auth)])
def api_bootstrap_start(project_id: str) -> dict[str, Any]:
    """Search everything the user already owns for material this project could use. Retrieval only — one query
    embedding per search, never a generation call."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    job = jobs.enqueue("bootstrap_scan", {"project_id": project_id}, lane="priority")
    return {"job_id": job["id"], **bootstrap.state(project_id)}


@app.get("/api/projects/{project_id}/bootstrap", dependencies=[Depends(require_auth)])
def api_bootstrap_state(project_id: str) -> dict[str, Any]:
    if not db.get_project(project_id):
        raise HTTPException(404)
    return bootstrap.state(project_id)


@app.post("/api/projects/{project_id}/bootstrap/decide", dependencies=[Depends(require_auth)])
def api_bootstrap_decide(project_id: str, body: BootstrapDecideIn) -> dict[str, Any]:
    """Attach or dismiss suggested sources. Attaching adds a project membership row — the source is never copied,
    never re-acquired, and stays in every other project it belongs to."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    try:
        return bootstrap.decide(project_id, body.source_ids, body.decision)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


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


@app.get("/api/projects/{project_id}/tick", dependencies=[Depends(require_auth)])
def api_tick(project_id: str) -> dict[str, Any]:
    """R2 — "did anything change?", answered in ~6 ms so the 3 s poll stops rebuilding a 440 ms view to discover
    that nothing did. The client refetches a pane only when the revision that pane depends on has moved, and
    reconciles fully on a slow interval regardless, so a fingerprint that ever missed a change self-corrects
    within a minute rather than leaving a permanently stale screen."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    with perf.timed("tick"):
        rev = db.project_view_revision(project_id)
    return {"rev": rev, "active": db.count_active_jobs()}


@app.get("/api/projects/{project_id}/jobs", dependencies=[Depends(require_auth)])
def api_project_jobs(project_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """Jobs belonging to this project: URL/file ingests queued for it, plus per-video jobs of its sources.
    Kyle, live: with a big enough app-wide backlog, this used to scan only the most-recently-CREATED 400 jobs
    across every project before filtering to this one — a currently queued/running job could be crowded out of
    that window by newer jobs (in this project or any other) and simply vanish from the panel, even though it
    was genuinely active. Every ACTIVE job (queued/running/external_pending) for this project is now always
    included, however many there are; `limit` only bounds how many additional recent terminal (done/failed/
    cancelled) jobs ride along for history."""
    ids = set(db.project_source_ids(project_id, ready_only=False))

    def _mine(j: dict[str, Any]) -> bool:
        pl = j.get("payload") or {}
        return pl.get("project_id") == project_id or (j["kind"] == "ingest_source" and pl.get("source_id") in ids)

    out = [j for j in db.list_jobs(limit=5000, statuses=db.JOB_ACTIVE) if _mine(j)]
    have = {j["id"] for j in out}
    budget = len(out) + max(limit, 0)
    for j in db.list_jobs(limit=max(limit * 10, 400)):
        if len(out) >= budget:
            break
        if j["id"] in have:
            continue
        if _mine(j):
            out.append(j)
            have.add(j["id"])
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
    j["bumped"] = bool(j.get("bumped_at"))
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


@app.post("/api/jobs/{job_id}/bump", dependencies=[Depends(require_auth)])
def api_bump_job(job_id: str) -> dict[str, Any]:
    """Kyle: "can we get a manual start button in the progress queue to move it to the top/next in line?" Only a
    queued job can be bumped — it jumps ahead of every lane (priority/normal/slow/low) and any older bump, but is
    a one-shot request: the mark clears the moment a worker actually claims the job, never a standing pin."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    st = db.bump_job(job_id)
    if st != "queued":
        raise HTTPException(409, f"only a queued job can be bumped (this one is {st})")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/check-now", dependencies=[Depends(require_auth)])
def api_check_now(job_id: str) -> dict[str, Any]:
    """Kyle: "in our progress bar we have a message that states: account's usage limit is reached — access returns
    2026-10-01 00:00 UTC ... but I think thats an old message and is not true. how do we verify?" The date is real —
    parsed straight from Anthropic's own error text when the job was first parked — but nothing re-attempts the call
    before that date, so the banner can go stale if the real-world limit already lifted. This clears the wait and
    bumps the job to the front so the very next worker cycle makes a fresh call. A job with no active timer wait has
    nothing to check early — that's a no-op, not an error, since it just means the job is already eligible to run."""
    j = db.get_job(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    st = db.check_now(job_id)
    if st != "queued":
        raise HTTPException(409, f"only a queued job can be checked (this one is {st})")
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
    tier: str | None = None                # S1: rebuild_matters | rebuild_transcript | retry_failed | accept — the triage tier's sources


@app.get("/api/projects/{project_id}/ai-backlog", dependencies=[Depends(require_auth)])
def api_ai_backlog(project_id: str) -> dict[str, Any]:
    """L3: what is waiting on the local provider, the time it will take there, and what the same work costs on the API."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    return jobs.backlog(project_id)


class AccelerateIn(BaseModel):
    n: int = 10
    order: str = "queue"      # queue (oldest first) | value (the sources that matter most first)


@app.post("/api/projects/{project_id}/accelerate", dependencies=[Depends(require_auth)])
def api_accelerate(project_id: str, body: AccelerateIn) -> dict[str, Any]:
    """L3: buy speed on purpose — move the next N queued local jobs onto the API pool. Never implied by slowness."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    if body.order not in ("queue", "value"):
        raise HTTPException(400, "order must be queue or value")
    return jobs.accelerate(project_id, n=max(1, min(body.n, 500)), order=body.order)


@app.get("/api/projects/{project_id}/staleness/triage", dependencies=[Depends(require_auth)])
def api_staleness_triage(project_id: str) -> dict[str, Any]:
    """S1: the stale set as three answers — rebuild (matters / transcript changed), accept as still usable, retry failed — with
    the cost as time on Claude Code or dollars on the API. Pure computation."""
    from . import staleness
    if not db.get_project(project_id):
        raise HTTPException(404)
    return staleness.triage(project_id)


class AcceptIn(BaseModel):
    source_ids: list[str] | None = None
    tier: str | None = "accept"


@app.post("/api/projects/{project_id}/staleness/accept", dependencies=[Depends(require_auth)])
def api_staleness_accept(project_id: str, body: AcceptIn) -> dict[str, Any]:
    """S1: keep these findings and mark them accepted for the current inputs (refused when the transcript changed)."""
    from . import staleness
    if not db.get_project(project_id):
        raise HTTPException(404)
    return staleness.accept(project_id, body.source_ids, tier=None if body.source_ids else body.tier)


@app.post("/api/projects/{project_id}/rebuild-stale", dependencies=[Depends(require_auth)])
def api_rebuild_stale(project_id: str, body: RebuildIn) -> dict[str, Any]:
    """Queue stale artifacts for regeneration as ordinary jobs (each passes the budget valve on its own)."""
    from . import staleness
    if body.transport not in ("interactive", "batch"):
        raise HTTPException(400, "transport must be 'interactive' or 'batch'")
    source_ids = body.source_ids
    if body.tier:
        source_ids = [r["source_id"] for r in staleness.triage(project_id)["tiers"].get(body.tier, {}).get("sources", [])]
        if not source_ids:
            return {"queued": 0, "job_ids": [], "tier": body.tier}
    return {**staleness.rebuild(project_id, body.what, source_ids, transport=body.transport), "tier": body.tier}


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

# ---- G6 (0.31.0): Canonical Works & Source Resolver — global identity/versions/manifestations, project-relative relevance

class ResolveIn(BaseModel):
    text: str
    project_id: str | None = None
    external: bool = False


@app.post("/api/works/resolve", dependencies=[Depends(require_auth)])
def api_works_resolve(body: ResolveIn) -> dict[str, Any]:
    """Identity first, then access in the mandated order (project → global library → candidates → external on request). $0."""
    from . import works
    return works.find_copy(body.text, body.project_id, external=body.external)


@app.get("/api/works", dependencies=[Depends(require_auth)])
def api_works_list(project_id: str | None = None, q: str | None = None, limit: int = 100) -> dict[str, Any]:
    from . import works
    return {"works": works.list_works(project_id, q, limit), "stats": works.stats()}


@app.get("/api/works/{work_id}", dependencies=[Depends(require_auth)])
def api_work_get(work_id: str) -> dict[str, Any]:
    from . import works
    w = works.get(work_id)
    if not w:
        raise HTTPException(404)
    return w


class VersionIn(BaseModel):
    label: str
    edition: str | None = None
    year: str | None = None
    effective_date: str | None = None
    supersedes_id: str | None = None
    change_kind: str = "unknown"        # unknown | supersedes | material | rehost | formatting
    change_note: str | None = None


@app.post("/api/works/{work_id}/versions", dependencies=[Depends(require_auth)])
def api_work_version(work_id: str, body: VersionIn) -> dict[str, Any]:
    """Record a version/edition and how it relates to the one it replaces — this is what drives G6 freshness (needs_refresh
    vs stale vs nothing), so it is the user's explicit statement, never inferred from 'a newer file exists'."""
    from . import claims, works
    if not works.get(work_id):
        raise HTTPException(404)
    v = works.ensure_version(work_id, body.label, edition=body.edition, year=body.year, effective_date=body.effective_date, supersedes_id=body.supersedes_id,
                             change_kind=body.change_kind, change_note=body.change_note, status="current" if body.supersedes_id else "unknown")
    # re-assess the Claims whose evidence sits on this Work's older versions
    for m in works.manifestations_of(work_id):
        if m.get("source_id"):
            claims.stale_by_source(m["source_id"])
    return v


class LinkIn(BaseModel):
    source_id: str
    relation: str = "manifestation_of"
    version_id: str | None = None
    form: str | None = None


@app.post("/api/works/{work_id}/link", dependencies=[Depends(require_auth)])
def api_work_link(work_id: str, body: LinkIn) -> dict[str, Any]:
    from . import works
    if not works.get(work_id) or not db.get_source(body.source_id):
        raise HTTPException(404)
    try:
        return works.link_source(body.source_id, work_id, version_id=body.version_id, relation=body.relation, form=body.form, confidence="exact_metadata", basis={"from": "user"})
    except ValueError as e:
        raise HTTPException(400, str(e))


class MergeIn(BaseModel):
    into: str
    reason: str = "user"


@app.post("/api/works/{work_id}/merge", dependencies=[Depends(require_auth)])
def api_work_merge(work_id: str, body: MergeIn) -> dict[str, Any]:
    """The only way two Works become one (audit alias kept)."""
    from . import works
    try:
        return works.merge_work(work_id, body.into, reason=body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/works/reconcile", dependencies=[Depends(require_auth)])
def api_works_reconcile() -> dict[str, Any]:
    """Normalize identifier variants (Form 1120-S / 1120S) and merge identical canonical identifiers through merge_work."""
    from . import works
    return {"merges": works.reconcile_identifiers(), "stats": works.stats()}


class RelevanceIn(BaseModel):
    relevance: str      # attached | relevant | targeted | dismissed
    reason: str | None = None


@app.post("/api/projects/{project_id}/works/{work_id}/relevance", dependencies=[Depends(require_auth)])
def api_project_work_relevance(project_id: str, work_id: str, body: RelevanceIn) -> dict[str, Any]:
    from . import works
    if not db.get_project(project_id) or not works.get(work_id):
        raise HTTPException(404)
    try:
        works.set_project_relevance(project_id, work_id, body.relevance, body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return works.project_relevance(project_id, work_id) or {}


# ---- G7 (0.32.0): Deep & Community Source Discovery — threads as sources, missions from research state, synthesis

class ExploreCommunityIn(BaseModel):
    community: str                      # "r/smallbusiness"
    query: str | None = None            # manual query; otherwise the mission's
    mission: dict[str, Any] | None = None
    limit: int = 25


@app.get("/api/projects/{project_id}/community/missions", dependencies=[Depends(require_auth)])
def api_community_missions(project_id: str) -> dict[str, Any]:
    """Search missions derived from research STATE (missing perspectives, tensions, open targets, weak experiential Claims)."""
    from . import community
    if not db.get_project(project_id):
        raise HTTPException(404)
    return {"missions": community.missions(project_id)}


@app.post("/api/projects/{project_id}/community/explore", dependencies=[Depends(require_auth)])
async def api_community_explore(project_id: str, body: ExploreCommunityIn) -> dict[str, Any]:
    """Metadata only: candidate threads into the Candidate Index, ranked against the mission. Nothing acquired."""
    from . import community
    if not db.get_project(project_id):
        raise HTTPException(404)
    try:
        return await anyio.to_thread.run_sync(lambda: community.explore(body.community, project_id, body.mission, limit=min(body.limit, 100), query=body.query))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project_id}/community/synthesis", dependencies=[Depends(require_auth)])
def api_community_synthesis(project_id: str, refresh: bool = False) -> dict[str, Any]:
    from . import community
    if not db.get_project(project_id):
        raise HTTPException(404)
    rows = community.synthesize(project_id) if refresh else community.syntheses(project_id)
    return {"syntheses": rows, "stats": community.stats()}


@app.get("/api/sources/{source_id}/thread", dependencies=[Depends(require_auth)])
def api_source_thread(source_id: str) -> dict[str, Any]:
    """The preserved post tree of a community source (locators, corrections, claimed context, availability)."""
    from . import community
    src = db.get_source(source_id)
    if not src or src.get("platform") != community.PLATFORM:
        raise HTTPException(404)
    comp = json.loads(src["completeness"]) if src.get("completeness") else None
    return {"source": {k: src.get(k) for k in ("id", "title", "url", "channel", "published_at", "status", "revision")}, "completeness": comp, "posts": community.posts_of(source_id)}


class RecaptureIn(BaseModel):
    project_id: str | None = None


@app.post("/api/sources/{source_id}/recapture", dependencies=[Depends(require_auth)])
def api_source_recapture(source_id: str, body: RecaptureIn) -> dict[str, Any]:
    """B2 — 'Reopen and capture more': read the thread again (server first; the browser when the server cannot) and MERGE
    into the same source. A partial capture never deletes what an earlier reading saw."""
    src = db.get_source(source_id)
    if not src or not (src.get("url") or "").startswith("http"):
        raise HTTPException(404)
    from . import acquire
    if any(r.get("source_id") == source_id for r in acquire.pending_captures()):
        return {"ok": True, "already_waiting": True}
    job = jobs.enqueue("ingest_url", {"url": src["url"], "tags": [], "project_id": body.project_id, "force": True, "review": False, "reason": "reopen and capture more"})
    return {"ok": True, "job_id": job["id"]}


@app.post("/api/sources/{source_id}/accept-partial", dependencies=[Depends(require_auth)])
def api_source_accept_partial(source_id: str) -> dict[str, Any]:
    """B2 — the user accepts a partial capture as good enough for now; it stays visibly partial (the flag is 'accepted', never 'complete')."""
    src = db.get_source(source_id)
    if not src:
        raise HTTPException(404)
    comp = json.loads(src["completeness"]) if src.get("completeness") else {"status": "unknown"}
    comp["accepted"] = True
    with db.tx() as conn:
        conn.execute("UPDATE sources SET completeness=?, updated_at=? WHERE id=?", (json.dumps(comp), db.now(), source_id))
    return {"ok": True, "completeness": comp}


class ResearchRefreshIn(BaseModel):
    extract: bool = False        # allow ONE bounded normalization pass now (model call); default is the $0 path


@app.get("/api/projects/{project_id}/research", dependencies=[Depends(require_auth)])
def api_research(project_id: str) -> dict[str, Any]:
    from . import knowledge, research_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    st = knowledge.state(project_id)
    st["attention"] = research_view.attention(project_id)      # the sidebar number (R3): what needs Kyle, never the Claim count
    return st


@app.post("/api/projects/{project_id}/research/refresh", dependencies=[Depends(require_auth)])
async def api_research_refresh(project_id: str, body: ResearchRefreshIn) -> dict[str, Any]:
    """Harvest candidate Claims from findings ($0), assess, detect tensions, rebuild the map; with extract=true also run
    the lazy normalization contract inline (bounded) or queue it as a job when the backlog is large."""
    from . import claims, knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    from . import research_view
    res = await anyio.to_thread.run_sync(lambda: claims.ensure(project_id, allow_model=body.extract))
    res["state"] = knowledge.state(project_id)
    res["state"]["attention"] = research_view.attention(project_id)
    return res


@app.get("/api/projects/{project_id}/research/overview", dependencies=[Depends(require_auth)])
def api_research_overview(project_id: str, limit: int = 5, full: bool = False) -> dict[str, Any]:
    """R1/R3/R5/R6 ($0, deterministic): the decision-first view — summary, the ranked 'next' list (questions + watch-outs),
    recently improved, the sidebar attention count, and the Research Areas."""
    from . import research_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    return research_view.overview(project_id, limit=max(1, min(limit, 20)), full=full)


@app.get("/api/projects/{project_id}/research/questions", dependencies=[Depends(require_auth)])
def api_research_questions(project_id: str, status: str | None = None) -> dict[str, Any]:
    from . import research_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    qs = research_view.questions(project_id)
    if status:
        qs = [q for q in qs if q["status"] == status]
    return {"total": len(qs), "questions": qs}


@app.get("/api/projects/{project_id}/research/watchouts", dependencies=[Depends(require_auth)])
def api_research_watchouts(project_id: str) -> dict[str, Any]:
    from . import research_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    ws = research_view.watchouts(project_id)
    return {"total": len(ws), "watchouts": ws}


@app.get("/api/projects/{project_id}/research/areas", dependencies=[Depends(require_auth)])
def api_research_areas(project_id: str) -> dict[str, Any]:
    from . import research_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    return research_view.areas(project_id)


class EvalIn(BaseModel):
    budget: int = 150            # bounded by design: decision-relevant Claims + a stratified sample, never the corpus


@app.post("/api/projects/{project_id}/research/evaluate", dependencies=[Depends(require_auth)])
def api_research_evaluate(project_id: str, body: EvalIn) -> dict[str, Any]:
    """G5.1: one durable, bounded normalization evaluation (a job). Measures merges, qualifier/hedge preservation,
    topic grouping, tensions and cost so broader normalization has to earn adoption."""
    from . import claims
    if not db.get_project(project_id):
        raise HTTPException(404)
    # slow lane (see claims.py): a claims pass can hold an AI worker for up to two hours, and only local worker 0
    # takes that lane, so findings and ranking keep flowing while it runs.
    job = db.create_job("extract_claims", {"project_id": project_id, "evaluation": True, "budget": max(10, min(body.budget, 300)), "reason": "bounded normalization evaluation"}, lane="slow")
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


@app.get("/api/projects/{project_id}/claims", dependencies=[Depends(require_auth)])
def api_claims_query(project_id: str, q: str | None = None, status: str = "all", strength: str | None = None, freshness: str | None = None,
                     needs_decision: bool = False, topic: str | None = None, area: str | None = None, sort: str = "priority",
                     limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """R7: the Claims workbench — composable filters, facets, sort, paging, one plain-language line per Claim — over
    the FULL claim set, never the 300-cap `knowledge.state()` uses for its bootstrap page."""
    from . import claims_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    return claims_view.query(project_id, q=q, status=status, strength=strength, freshness=freshness, needs_decision=needs_decision,
                             topic=topic, area=area, sort=sort, limit=limit, offset=offset)


class ClaimsBulkIn(BaseModel):
    claim_ids: list[str]
    status: str                      # proposed | accepted | rejected
    application: str | None = None


@app.get("/api/projects/{project_id}/claims/for-source", dependencies=[Depends(require_auth)])
def api_claims_for_source(project_id: str, source_id: str, locator: str | None = None, limit: int = 5) -> dict[str, Any]:
    """RESEARCH-TAB.md §5's 'Why this answer': the Claims a chat citation's source feeds, closest locator first."""
    from . import claims_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    return claims_view.for_source(project_id, source_id, locator, limit=max(1, min(limit, 20)))


@app.post("/api/projects/{project_id}/claims/bulk-status", dependencies=[Depends(require_auth)])
def api_claims_bulk(project_id: str, body: ClaimsBulkIn) -> dict[str, Any]:
    """R7: batch accept/reject — one verdict on many Claims, project-scoped, then ONE refresh."""
    from . import claims_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    try:
        return claims_view.bulk_status(project_id, body.claim_ids, body.status, application=body.application)
    except ValueError as e:
        raise HTTPException(400, str(e))


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


class TensionsBulkIn(BaseModel):
    tension_ids: list[str]
    status: str    # resolved | dismissed | open


@app.post("/api/projects/{project_id}/tensions/bulk-status", dependencies=[Depends(require_auth)])
def api_tensions_bulk(project_id: str, body: TensionsBulkIn) -> dict[str, Any]:
    """R5's remaining half: one verdict on a whole watch-out ISSUE — "Not important to my project" / "Resolved" applies to
    every tension behind it, then ONE refresh. A dismissed tension is never reopened by a later refresh (`_upsert_tension`
    never resets status), so the verdict is durable."""
    from . import knowledge
    if not db.get_project(project_id):
        raise HTTPException(404)
    if body.status not in ("open", "resolved", "dismissed"):
        raise HTTPException(400, "status must be open, resolved or dismissed")
    mine = {r["id"] for r in db.connect().execute(
        f"SELECT id FROM research_tensions WHERE project_id=? AND id IN ({','.join('?' for _ in body.tension_ids) or 'NULL'})",
        (project_id, *body.tension_ids)).fetchall()} if body.tension_ids else set()
    for tid in mine:
        knowledge.set_tension_status(tid, body.status)
    if mine:
        knowledge.refresh(project_id)
    return {"changed": len(mine), "skipped": len(set(body.tension_ids)) - len(mine), "status": body.status}


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
    depth: str | None = None               # D2: "deep" = Read deeper (smaller windows + depth instruction; interactive only)


@app.post("/api/projects/{project_id}/findings/first-wave", dependencies=[Depends(require_auth)])
def api_findings_first_wave(project_id: str, limit: int = 6) -> dict[str, Any]:
    """Push this project's first few queued findings jobs to the front of the whole queue. Free — it changes queue
    ORDER only (same provider, same model, same $0); it exists because a new project's first finding should not sit
    behind another project's backlog."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    return db.promote_first_findings(project_id, limit=min(max(1, limit), jobs.FIRST_WAVE_CAP * 4))


@app.post("/api/projects/{project_id}/suggest", dependencies=[Depends(require_auth)])
def api_suggest(project_id: str, body: SuggestIn) -> dict[str, Any]:
    ids = body.source_ids or (db.project_source_ids(project_id) if body.force else db.sources_needing_suggestions(project_id))
    if not ids:
        return {"job": None, "sources": 0, "transport": body.transport}
    if body.transport not in ("interactive", "batch"):
        raise HTTPException(400, "transport must be 'interactive' or 'batch'")
    if body.depth == "deep" and body.transport == "batch":
        raise HTTPException(400, "Read deeper runs interactively (local provider or API), not in a background batch")
    if body.transport == "batch":
        job = jobs.enqueue("suggest_findings_batch", {"project_id": project_id, "source_ids": ids, "force": body.force})
    else:
        if body.depth == "deep":
            # one job PER source in the slow lane: each finishes and lands on its own, and only one local worker ever carries them
            made = [db.create_job("suggest_findings", {"project_id": project_id, "source_ids": [sid], "force": True, "depth": "deep", "reason": "read deeper"}, lane="slow") for sid in ids]
            return {"job": made[0]["id"] if made else None, "jobs": [j["id"] for j in made], "sources": len(ids), "transport": body.transport, "depth": body.depth, "lane": "slow"}
        job = db.create_job("suggest_findings", {"project_id": project_id, "source_ids": ids, "force": body.force, "depth": body.depth},
                            lane=jobs.first_wave_lane(project_id, ids[0] if len(ids) == 1 else None))
    return {"job": job["id"], "sources": len(ids), "transport": body.transport, "depth": body.depth}


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


@app.get("/api/projects/{project_id}/sources/{source_id}/digest", dependencies=[Depends(require_auth)])
def api_source_digest(project_id: str, source_id: str) -> dict[str, Any]:
    """S3: one source, everything it gave this project — value, findings by status with what used each, the Claims they
    became, where it shows up (plan steps, chat answers), and its staleness tier. $0."""
    from . import sources_value
    try:
        return sources_value.digest(project_id, source_id)
    except KeyError:
        raise HTTPException(404) from None


@app.get("/api/projects/{project_id}/findings", dependencies=[Depends(require_auth)])
def api_findings_query(project_id: str, q: str | None = None, status: str | None = "approved", min_importance: int | None = None, source_id: str | None = None,
                       used: str | None = None, stale: str | None = None, area: str | None = None, sort: str = "importance", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """S4: the Findings workbench — composable filters, facets, sort, paging; use badges (plan · chat · Claim); the low-value sweep."""
    from . import findings_view
    if not db.get_project(project_id):
        raise HTTPException(404)
    return findings_view.query(project_id, q=q, status=status, min_importance=min_importance, source_id=source_id, used=used, stale=stale, area=area, sort=sort, limit=limit, offset=offset)


@app.get("/api/projects/{project_id}/notes", dependencies=[Depends(require_auth)])
def api_list_notes(project_id: str, status: str = "reserve", source_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    """D1: the findings of one status (default `reserve` — extracted beyond the length-aware cap), optionally for one source,
    importance first. Promote with POST /api/notes/{id}/status {suggested|approved}."""
    if not db.get_project(project_id):
        raise HTTPException(404)
    rows = db.list_project_notes(project_id, status=status)
    if source_id:
        rows = [r for r in rows if r.get("source_id") == source_id]
    return {"total": len(rows), "notes": rows[:limit]}


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


SSE_HEARTBEAT = 10.0     # seconds of silence after which the stream sends a keep-alive comment (nothing is ever "frozen")


@app.post("/api/ask/stream", dependencies=[Depends(require_auth)])
async def api_ask_stream(body: AskIn) -> StreamingResponse:
    """The same answer as POST /api/ask, narrated as it happens (R1). Server-sent events:
      {"type":"phase","phase":...,"label":...}   what the turn is doing right now
      {"type":"delta","text":...}                answer text as the model writes it
      {"type":"done","result":{...}}             the identical payload /api/ask returns — the UI reconciles on this
      {"type":"error","message":...}
    The work runs in a worker thread exactly as the non-streaming route does; this endpoint only narrates it."""
    cid = body.conversation_id or db.new_id()
    loop = asyncio.get_running_loop()
    q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def push(ev: dict[str, Any] | None) -> None:
        loop.call_soon_threadsafe(q.put_nowait, ev)

    def run() -> None:
        try:
            res = qa.ask(body.question, project_id=body.project_id, conversation_id=cid, use_web=body.use_web,
                         attached_source_ids=body.attached_source_ids or None, on_event=push)
            push({"type": "done", "result": res})
        except Exception as e:  # noqa: BLE001 — the client must always learn why, not just lose the connection
            log.exception("ask stream failed")
            push({"type": "error", "message": str(e)})
        finally:
            push(None)

    async def gen() -> Any:
        task = asyncio.ensure_future(anyio.to_thread.run_sync(run))
        try:
            yield 'data: {"type":"open"}\n\n'
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT)
                except asyncio.TimeoutError:
                    yield ": still working\n\n"      # a comment frame: keeps proxies and the reader awake
                    continue
                if ev is None:
                    break
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            with contextlib.suppress(Exception):
                await task

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


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
