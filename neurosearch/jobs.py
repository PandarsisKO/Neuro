"""Tiny background job runner: a few worker threads pulling from the jobs table.

Good enough for one user and hundreds of videos; survives restarts (running jobs are re-queued).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from . import db, ingest
from .config import settings
from .embeddings import embed_pending

log = logging.getLogger(__name__)

_stop = threading.Event()
_threads: list[threading.Thread] = []


def enqueue(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return db.create_job(kind, payload)


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    jid = job["id"]
    payload = job["payload"] or {}

    def progress(p: float, m: str) -> None:
        db.update_job(jid, progress=p, message=m)

    kind = job["kind"]
    from . import usage
    if kind in ("ingest_source", "ingest_file", "suggest_findings", "reembed"):
        usage.guard()   # cheap check first; transcription/findings re-check with a size-based estimate
    if kind == "ingest_url":
        return ingest.ingest_url(payload["url"], tags=payload.get("tags"), project_id=payload.get("project_id"),
                                 progress=progress, force=bool(payload.get("force")),
                                 cookies_file=payload.get("cookies_file"), referer=payload.get("referer"),
                                 title=payload.get("title"), collection_id=payload.get("collection_id"),
                                 since_years=payload.get("since_years"), max_videos=payload.get("max_videos"))
    if kind == "ingest_source":
        return ingest.ingest_source(payload["source_id"], progress=progress, min_date=payload.get("min_date"),
                                    collection_id=payload.get("collection_id"), newest_first=bool(payload.get("newest_first")))
    if kind == "ingest_file":
        from pathlib import Path
        path = Path(payload["path"])
        try:
            return ingest.ingest_local_file(path, title=payload.get("title"), tags=payload.get("tags"),
                                            project_id=payload.get("project_id"), progress=progress,
                                            original_name=payload.get("name"))
        finally:
            path.unlink(missing_ok=True)
    if kind == "suggest_findings":
        from .findings import suggest_for_project
        return suggest_for_project(payload["project_id"], payload.get("source_ids"), progress=progress)
    if kind == "reembed":
        return {"embedded": embed_pending(limit=payload.get("limit", 100000))}
    raise RuntimeError(f"unknown job kind {kind}")


def _worker(n: int) -> None:
    log.info("worker %d started", n)
    while not _stop.is_set():
        job = db.claim_job()
        if not job:
            _stop.wait(1.5)
            continue
        try:
            result = run_job(job)
            db.update_job(job["id"], status="done", progress=1.0, message="done", result=result)
        except Exception as e:  # noqa: BLE001
            from .media import RateLimited, rate_limit_status
            from .usage import BudgetPaused
            if isinstance(e, BudgetPaused):
                db.requeue_job(job["id"], delay=min(e.wait, 3600), message=f"paused: {e}")
                sid = (job.get("payload") or {}).get("source_id")
                if sid:
                    db.set_source_status(sid, "pending")
                _stop.wait(5)
                continue
            if isinstance(e, RateLimited) or isinstance(getattr(e, "__cause__", None), RateLimited):
                db.requeue_job(job["id"], delay=rate_limit_status()["seconds_left"] + 5, message=f"paused: {e}")
                # keep the source from showing as failed
                sid = (job.get("payload") or {}).get("source_id")
                if sid:
                    db.set_source_status(sid, "pending")
                _stop.wait(5)
                continue
            log.warning("job %s failed: %s", job["id"], e)
            db.update_job(job["id"], status="failed", message=f"error: {e}")


def start_workers(n: int | None = None) -> None:
    n = n or settings.workers
    db.init_db()
    requeued = db.requeue_stale_running_jobs()
    if requeued:
        log.info("re-queued %d interrupted jobs", requeued)
    _stop.clear()
    for i in range(n):
        t = threading.Thread(target=_worker, args=(i,), daemon=True, name=f"ns-worker-{i}")
        t.start()
        _threads.append(t)


def stop_workers() -> None:
    _stop.set()
    for t in _threads:
        t.join(timeout=2)
    _threads.clear()


def wait_for_idle(poll: float = 1.0) -> None:
    """Block until there are no queued or running jobs (CLI use)."""
    while True:
        row = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running')").fetchone()
        if row["n"] == 0:
            return
        time.sleep(poll)


def enqueue_suggestions(source_id: str, project_id: str | None = None) -> None:
    """After a source becomes ready: queue finding suggestions for each project it belongs to (if enabled)."""
    if not settings.auto_suggest or not settings.anthropic_api_key:
        return
    pids = [project_id] if project_id else db.projects_for_source(source_id)
    for pid in pids:
        db.create_job("suggest_findings", {"project_id": pid, "source_ids": [source_id]})
