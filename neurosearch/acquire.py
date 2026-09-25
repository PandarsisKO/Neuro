"""B1 — Browser-assisted acquisition: a classified failure, a generic `requires_browser` state, and the hand-off.

    SERVER ACQUISITION ──success──▶ Source
          │
          └─ access / auth / browser-only failure (classified, adapter-aware)
                          │
                          ▼
                   REQUIRES_BROWSER  = the ingest job parked `external_pending` with provider "browser"
                          │            (durable: survives restart like any external job; the source row stays
                          │             `pending` with `error_class` so the project keeps it)
                          ▼
                   the user's Chrome + the extension capture what the user can legitimately see
                          │
                          ▼
                   POST /api/capture/{job_id}  →  db.resume_external  →  the SAME job completes the SAME source

Rules (Browser Acquisition Track LOCK, EXPANSION.md): `requires_browser` is a capability state derived from a classified
failure, never a Reddit state; not every 403 is browser-solvable — the adapter says which classes are; browser work
uses the existing durable external-job system; the capture payload is content only (never cookies); the server is the
only normalizer. Adapters declare their acquisition methods here so blocked-source handling is one table, not scattered
conditionals.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

from . import db

# ---------------------------------------------------------------- the capability table

ADAPTERS: dict[str, dict[str, Any]] = {
    # methods in the order they are tried; browser_solvable = failure classes the user's browser is expected to recover
    "reddit_thread": {"methods": ["structured_api", "public_json", "server_html", "browser_rendered"],
                      "browser_solvable": {"blocked", "login_wall", "challenge", "not_found_blocked"}, "capture_kind": "reddit_thread_capture"},
    "web_page":      {"methods": ["http", "browser_rendered"],
                      "browser_solvable": {"blocked", "login_wall", "challenge", "js_required", "empty_render"}, "capture_kind": "page_capture"},
    "document":      {"methods": ["http", "manual_upload"], "browser_solvable": set(), "capture_kind": None},
    "youtube":       {"methods": ["http"], "browser_solvable": set(), "capture_kind": None},
}
CAPTURE_TTL_S = 14 * 24 * 3600          # a browser request waits two weeks before it is called expired (still re-openable)
PROVIDER = "browser"
CHALLENGE = re.compile(r"(just a moment|checking your browser|verify you are human|access denied|attention required|are you a robot|"
                       r"enable javascript and cookies|cf-challenge|captcha|whoa there, pardner|welcome to reddit)", re.I)
LOGIN_WALL = re.compile(r"(log in to continue|sign in to continue|please log in|you must be logged in|login required|members only|"
                        r"subscribe to (read|continue)|create an account to)", re.I)


class AcquisitionFailure(RuntimeError):
    """A server-side acquisition that did not produce content, with a typed class the product can act on.
    `browser_solvable` is decided by the adapter's table — never by the status code alone."""

    def __init__(self, message: str, *, adapter: str, cls: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.adapter, self.cls, self.detail = adapter, cls, detail

    @property
    def browser_solvable(self) -> bool:
        return self.cls in ADAPTERS.get(self.adapter, {}).get("browser_solvable", set())

    @property
    def error_class(self) -> str:
        return f"browser_solvable:{self.cls}" if self.browser_solvable else self.cls


def classify_page(status: int, body_text: str, adapter: str = "web_page") -> str | None:
    """The failure class of an HTTP answer (None = it is content). Adapter-aware callers turn it into an AcquisitionFailure."""
    head = body_text[:4000]
    if status in (401, 403, 429, 503):
        return "challenge" if CHALLENGE.search(head) else "blocked"
    if status == 404:
        return "not_found"
    if status >= 400:
        return "http_error"
    if LOGIN_WALL.search(head) or CHALLENGE.search(head):
        return "login_wall" if LOGIN_WALL.search(head) else "challenge"
    return None


def user_message(f: AcquisitionFailure, host: str | None = None) -> str:
    """What the user reads on the card — no status codes, no architecture."""
    site = host or "This site"
    if f.adapter == "reddit_thread":
        return "Reddit is blocking Neuro Search from reading this thread directly, but your browser can access it."
    if f.cls in ("login_wall",):
        return f"{site} shows this page only to a signed-in browser. Neuro Search cannot read it directly, but your browser can."
    if f.cls in ("js_required", "empty_render"):
        return f"{site} builds this page in the browser; nothing readable reaches Neuro Search directly, but your browser renders it."
    return f"{site} refuses automated readers. Neuro Search cannot read this page directly, but your browser can."


# ---------------------------------------------------------------- the external "provider": the user's browser

class BrowserCapture:
    """External handler for jobs parked on the user's browser. There is nothing to poll — the extension posts the
    capture (`resolve_capture`) — so `check` only answers 'pending'; the deadline makes an abandoned request visible."""
    name = PROVIDER

    @classmethod
    def find_by_ref(cls, ref: str) -> str | None:
        return None

    @classmethod
    def check(cls, handle: str) -> tuple[str, Any]:
        return "pending", None

    @classmethod
    def cancel(cls, handle: str) -> bool:
        return True


def park_for_browser(job: dict[str, Any], run_id: str | None, failure: AcquisitionFailure, url: str) -> dict[str, Any]:
    """Turn a browser-solvable failure into a durable browser-capture request on the SAME job, and make sure the
    project keeps a visible source row for it. Returns the pending capture request."""
    from . import community, identity, media
    payload = dict(job.get("payload") or {})
    project_id = payload.get("project_id")
    canonical = media.canonical_url(url)
    host = urlparse(canonical).netloc.replace("www.", "")
    # the placeholder source: the same identity the capture will resolve to, so nothing is ever created twice
    if failure.adapter == "reddit_thread":
        tid = community.reddit_thread_id(canonical) or canonical
        cand = identity.Candidate(platform=community.PLATFORM, external_id=f"reddit:{tid}", url=canonical, title=payload.get("title") or canonical,
                                  canonical_url=canonical, tags=list(payload.get("tags") or []), fields={"channel": _subreddit_of(canonical), "transcript_kind": "community"})
    else:
        ext_id = re.sub(r"^https?://(www\.)?", "", canonical).rstrip("/")
        cand = identity.Candidate(platform="web", external_id=ext_id, url=canonical, title=payload.get("title") or canonical, canonical_url=canonical,
                                  tags=list(payload.get("tags") or []), fields={"channel": host})
    res = identity.resolve_or_create_source(cand, project_id, initial_status="pending", retry=True)
    src = res.source
    msg = user_message(failure, host)
    with db.tx() as conn:
        conn.execute("UPDATE sources SET status='pending', error=?, error_class=?, updated_at=? WHERE id=?", (msg, failure.error_class, db.now(), src["id"]))
    payload.update({"source_id": src["id"], "capture": {"adapter": failure.adapter, "kind": ADAPTERS[failure.adapter]["capture_kind"], "reason": payload.get("reason"),
                                                        "why": str(failure)[:600], "classified_at": time.time()}})
    db.set_job_payload(job["id"], payload)
    db.park_external(job["id"], run_id, PROVIDER, f"capture:{failure.adapter}", canonical, time.time() + CAPTURE_TTL_S)
    db.update_job(job["id"], message=f"browser needed — {msg}")
    return pending_capture(job["id"]) or {"job_id": job["id"]}


def _subreddit_of(url: str) -> str | None:
    m = re.search(r"/(r/[^/]+)/", urlparse(url).path)
    return m.group(1) if m else None


# ---------------------------------------------------------------- the queue

def _row(j: dict[str, Any]) -> dict[str, Any]:
    pl = j.get("payload") or {}
    cap = pl.get("capture") or {}
    proj = db.get_project(pl["project_id"]) if pl.get("project_id") else None
    src = db.get_source(pl["source_id"]) if pl.get("source_id") else None
    expired = bool(j.get("external_deadline") and time.time() > j["external_deadline"])
    return {"job_id": j["id"], "project_id": pl.get("project_id"), "project_name": (proj or {}).get("name"), "source_id": pl.get("source_id"),
            "candidate_id": pl.get("candidate_id"), "canonical_url": j.get("external_handle"), "url": pl.get("url"), "title": (src or {}).get("title") or pl.get("title"),
            "adapter": cap.get("adapter"), "capture_kind": cap.get("kind"), "reason": cap.get("reason") or (src or {}).get("error"),
            "why": cap.get("why"), "status": "expired" if expired else "pending", "created_at": j.get("external_submitted_at") or j.get("created_at"),
            "expires_at": j.get("external_deadline")}


def pending_captures(project_id: str | None = None, url: str | None = None) -> list[dict[str, Any]]:
    """Everything the user's browser is being asked for (oldest first). Content only — never cookies or tokens."""
    from . import media
    want = media.canonical_url(url) if url else None
    out = []
    for j in db.external_pending_jobs():
        if j.get("external_provider") != PROVIDER:
            continue
        pl = j.get("payload") or {}
        if project_id and pl.get("project_id") != project_id:
            continue
        if want and j.get("external_handle") != want and media.canonical_url(pl.get("url") or "") != want:
            continue
        out.append(_row(j))
    return out


def pending_capture(job_id: str) -> dict[str, Any] | None:
    j = db.get_job(job_id)
    if not j or j.get("status") != "external_pending" or j.get("external_provider") != PROVIDER:
        return None
    return _row(j)


def pending_by_source() -> dict[str, dict[str, Any]]:
    """source_id → the browser request waiting for it (for the Sources list)."""
    out: dict[str, dict[str, Any]] = {}
    for r in pending_captures():
        if r.get("source_id"):
            out[r["source_id"]] = r
    return out


def resolve_capture(job_id: str, capture: dict[str, Any]) -> dict[str, Any]:
    """The extension delivered what the browser saw: hand it to the SAME parked job. The job re-runs through the normal
    ingest path with `_external_result` and completes the same source row — never a second one."""
    req = pending_capture(job_id)
    if not req:
        # The extension may retry after the first response was lost. Once the
        # capture is durably attached, return the original identity instead of
        # turning a successful delivery into a misleading 404.
        job = db.get_job(job_id)
        payload = (job or {}).get("payload") or {}
        ext = payload.get("_external_result") or {}
        if isinstance(ext, dict) and ext.get("capture") is not None:
            return {"ok": True, "job_id": job_id, "source_id": payload.get("source_id"),
                    "project_id": payload.get("project_id"), "replayed": True}
        raise LookupError("no browser capture is waiting on that job (already captured, cancelled, or never requested)")
    if len(json.dumps(capture, default=str)) > 12_000_000:
        raise ValueError("capture too large")
    db.resume_external(job_id, {"capture": capture, "captured_at": time.time(), "via": "browser extension"})
    db.job_event(job_id, "browser_captured", method=capture.get("method"), contract=capture.get("contract"))
    return {"ok": True, "job_id": job_id, "source_id": req.get("source_id"), "project_id": req.get("project_id"), "replayed": False}


def request_for(url: str, project_id: str | None) -> dict[str, Any] | None:
    """An unsolicited capture (the user pressed the extension on a page) may belong to a waiting request: find it so the
    result resolves that request instead of creating a parallel acquisition."""
    rows = pending_captures(project_id=project_id, url=url) or pending_captures(url=url)
    return rows[0] if rows else None


def cancel_capture(job_id: str) -> bool:
    req = pending_capture(job_id)
    if not req:
        return False
    db.update_job(job_id, status="cancelled", message="browser capture cancelled")
    db.job_event(job_id, "cancelled", reason="browser_capture_cancelled")
    if req.get("source_id"):
        db.set_source_status(req["source_id"], "failed", "browser capture cancelled — Retry asks again")
    return True


# ---------------------------------------------------------------- extension presence + attention

def heartbeat(version: str | None, seen_url: str | None = None, extension_id: str | None = None) -> dict[str, Any]:
    db.kv_set("extension:last_seen", str(time.time()))
    if version:
        db.kv_set("extension:version", version)
    if extension_id:
        db.kv_set("extension:id", extension_id)          # S97: lets the app page nudge the extension the moment captures appear
    return extension_status()


def extension_status() -> dict[str, Any]:
    ts = float(db.kv_get("extension:last_seen") or 0)
    age = time.time() - ts if ts else None
    state = "not_detected" if not ts else ("ready" if age < 600 else "stale")
    return {"state": state, "last_seen": ts or None, "age_s": round(age) if age is not None else None, "version": db.kv_get("extension:version"),
            "id": db.kv_get("extension:id")}


def attention(project_id: str) -> dict[str, Any]:
    """What the user should know about acquisition in this project, in one line's worth of numbers."""
    rows = pending_captures(project_id=project_id)
    return {"browser_needed": len(rows), "expired": sum(1 for r in rows if r["status"] == "expired"), "extension": extension_status(),
            "items": rows[:20]}
