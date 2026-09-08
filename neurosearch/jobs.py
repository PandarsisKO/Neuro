"""Durable SQLite job runner (hardening ladder, Mission D).

State machine (stored status → derived view in db.derived_status):

    queued ──claim (lease)──▶ running ──▶ done | failed | cancelled
      ▲                          │
      │ retry_wait / budget_wait / rate_limit_wait (not_before + wait_reason)
      │ lease expired → recovered (resumes from the source's last completed stage)
      │                          └──▶ external_pending (no lease; another system owns the work) ──result──▶ queued
    blocked = queued with unsatisfied blocked_by (derived)

Invariants: a job has exactly one execution owner (a worker holding the lease, an external provider, or nobody while
waiting); every terminal transition is guarded by the run_id of the worker that claimed it; budget and rate-limit
waits are not attempts; recovery re-attaches to external handles and never resubmits.
"""
from __future__ import annotations

import logging
import os
import re
import socket
import threading
import time
from typing import Any

from . import db, ingest, logctx, providers
from .config import settings
from .embeddings import embed_pending

log = logging.getLogger(__name__)

_stop = threading.Event()
_threads: list[threading.Thread] = []
_running: dict[str, str] = {}          # job_id -> run_id owned by this process (lease keeper extends these)
_running_lock = threading.Lock()

# Errors worth retrying on their own: rate limits, login walls that come and go, network hiccups, 5xx.
TRANSIENT = re.compile(r"rate.?limit|too many requests|429|5\d\d|timed? ?out|temporar|connection|reset by peer|unavailable|"
                       r"try again|slow down|login for this|please wait|overloaded|not a bot|sign in to confirm|bot-check", re.I)
RETRYABLE = ("ingest_url", "ingest_source", "suggest_findings", "suggest_findings_batch", "rank_proposed", "discover", "build_plan", "external_demo")
MAX_ATTEMPTS = 4
RETRY_DELAYS = [10 * 60, 30 * 60, 90 * 60]     # seconds between attempts
ANALYSIS_KINDS = ("suggest_findings", "suggest_findings_batch", "rank_proposed", "discover", "reembed", "build_plan", "enrich_profiles_batch", "extract_claims")


class Cancelled(RuntimeError):
    """Raised inside a job at a safe boundary after cancellation was requested. Nothing is written after it."""


class SimulatedCrash(BaseException):
    """Test hook: the process 'dies' here. Not an Exception on purpose — no handler in the job may swallow it."""


class ExternalPending(Exception):
    """A job hands its work to an external system and parks: (provider, kind, handle, deadline)."""

    def __init__(self, provider: str, kind: str, handle: str, deadline: float | None = None) -> None:
        super().__init__(f"parked on {provider}:{kind} {handle}")
        self.provider, self.kind, self.handle, self.deadline = provider, kind, handle, deadline


# ------------------------------------------------------------------ hooks used by job code

_current = threading.local()
CRASH_AT: dict[str, int] = {}          # crash point name -> remaining crashes (tests); env NEUROSEARCH_CRASH_AT=name is one-shot


CANCEL_AT: dict[str, int] = {}         # tests: request cancellation of the current job when execution reaches this point


def crash_point(name: str) -> None:
    """Deterministic destructive testing: die here if asked to (see D12). Never triggers unless configured."""
    if CANCEL_AT.get(name, 0) > 0:
        CANCEL_AT[name] -= 1
        jid = getattr(_current, "job_id", None)
        if jid:
            db.request_cancel(jid)
    n = CRASH_AT.get(name, 0)
    if n > 0:
        CRASH_AT[name] = n - 1
        raise SimulatedCrash(name)
    if os.environ.get("NEUROSEARCH_CRASH_AT") == name:
        os.environ.pop("NEUROSEARCH_CRASH_AT", None)
        raise SimulatedCrash(name)


def check_cancel() -> None:
    """Call between safe boundaries inside a job: raises Cancelled when the user asked to stop this job."""
    jid = getattr(_current, "job_id", None)
    if jid and db.cancel_requested(jid):
        raise Cancelled("cancelled by the user")


def stage_event(stage: str, state: str = "complete", **payload: Any) -> None:
    jid = getattr(_current, "job_id", None)
    if jid:
        db.job_event(jid, "stage", run_id=getattr(_current, "run_id", None), stage=f"{stage}:{state}", **payload)


def current_job() -> tuple[str | None, str | None]:
    return getattr(_current, "job_id", None), getattr(_current, "run_id", None)


# ------------------------------------------------------------------ external providers (Rung G plugs Anthropic Batch in here)

class FakeExternal:
    """Reference external system for tests: submissions are durable (a JSON file in the data dir), results appear
    after `ready_after` checks, submissions are findable by client reference (so a crash between the provider
    accepting and us persisting the handle is recoverable), and cancellation is supported."""
    name = "fake"

    @classmethod
    def _path(cls):
        return settings.data_dir / "fake_external.json"

    @classmethod
    def _load(cls) -> dict[str, Any]:
        import json
        p = cls._path()
        return json.loads(p.read_text()) if p.exists() else {"submissions": {}}

    @classmethod
    def _save(cls, d: dict[str, Any]) -> None:
        import json
        cls._path().write_text(json.dumps(d))

    @classmethod
    def submit(cls, kind: str, client_ref: str, request: dict[str, Any], ready_after: int = 2) -> str:
        d = cls._load()
        handle = f"fakebatch_{len(d['submissions']) + 1:04d}"
        d["submissions"][handle] = {"kind": kind, "client_ref": client_ref, "request": request, "checks": 0, "ready_after": ready_after, "cancelled": False}
        cls._save(d)
        return handle

    @classmethod
    def find_by_ref(cls, client_ref: str) -> str | None:
        for h, s in cls._load()["submissions"].items():
            if s["client_ref"] == client_ref and not s["cancelled"]:
                return h
        return None

    @classmethod
    def check(cls, handle: str) -> tuple[str, Any]:
        """('pending'|'done'|'failed', result)"""
        d = cls._load()
        s = d["submissions"].get(handle)
        if not s:
            return "failed", "unknown handle"
        if s["cancelled"]:
            return "failed", "cancelled"
        s["checks"] += 1
        cls._save(d)
        if s["checks"] >= s["ready_after"]:
            return "done", {"echo": s["request"], "handle": handle}
        return "pending", None

    @classmethod
    def cancel(cls, handle: str) -> bool:
        d = cls._load()
        if handle in d["submissions"]:
            d["submissions"][handle]["cancelled"] = True
            cls._save(d)
            return True
        return False

    @classmethod
    def submissions(cls) -> int:
        return len(cls._load()["submissions"])


from .batches import AnthropicBatch  # noqa: E402

from .acquire import AcquisitionFailure, BrowserCapture, park_for_browser  # noqa: E402

EXTERNAL = {"fake": FakeExternal, AnthropicBatch.name: AnthropicBatch, BrowserCapture.name: BrowserCapture}


def submit_external(provider: str, kind: str, request: dict[str, Any], deadline: float | None = None, client_ref: str | None = None, **submit_kw: Any) -> None:
    """Park the current job on an external system. Order matters: record the intent, submit, then raise
    ExternalPending so the worker persists the handle. If we die between submit and persist, recovery asks the
    provider for our reference and re-attaches instead of submitting again. `client_ref` defaults to the job id; a
    job that submits several rounds (batch cohorts) passes a per-round reference."""
    jid, run_id = current_job()
    if not jid:
        raise RuntimeError("submit_external needs a job context")
    handler = EXTERNAL[provider]
    ref = client_ref or jid
    db.note_external_intent(jid, run_id, provider, kind)
    existing = handler.find_by_ref(ref)
    if existing and existing.startswith("tentative:"):                # provider work that MAY be ours: observe, verify, then adopt — never resubmit meanwhile
        db.job_event(jid, "external_observing", run_id=run_id, provider=provider, handle=existing, where="before_submit")
        raise ExternalPending(provider, kind, existing, deadline)
    if existing:                                                       # a previous run already submitted this job's work
        db.job_event(jid, "external_reattached", run_id=run_id, provider=provider, handle=existing, where="before_submit")
        raise ExternalPending(provider, kind, existing, deadline)
    handle = handler.submit(kind, ref, request, **submit_kw)
    crash_point("external_before_ack")
    raise ExternalPending(provider, kind, handle, deadline)


def poll_external_once() -> int:
    """Check every externally parked job; resume the finished ones. Returns how many changed state."""
    n = 0
    for j in db.external_pending_jobs():
        handler = EXTERNAL.get(j.get("external_provider") or "")
        if not handler:
            continue
        try:
            state, result = handler.check(j["external_handle"])
        except Exception as e:  # noqa: BLE001
            log.warning("external check failed for %s: %s", j["id"][:8], e)
            continue
        db.external_checked(j["id"])
        if state == "pending":
            if j.get("external_deadline") and time.time() > j["external_deadline"]:
                if j.get("external_provider") == BrowserCapture.name:
                    continue                                     # a browser request never fails on its own: it is listed as expired until the user acts
                db.update_job(j["id"], status="failed", message="error: external work missed its deadline")
                db.job_event(j["id"], "failed", reason="external_deadline")
                n += 1
            continue
        if state == "done":
            db.resume_external(j["id"], result)
        else:
            db.update_job(j["id"], status="failed", message=f"error: external work failed — {result}")
            db.job_event(j["id"], "failed", reason="external", detail=str(result)[:200])
        n += 1
    return n


# ------------------------------------------------------------------ running a job

def enqueue(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return db.create_job(kind, payload)


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    jid = job["id"]
    payload = job["payload"] or {}
    _current.job_id, _current.run_id = jid, job.get("run_id")
    logctx.set_fields(job_id=jid, run_id=(job.get("run_id") or "")[:8] or None, project_id=payload.get("project_id"),
                      source_id=payload.get("source_id"), task=job["kind"])

    def progress(p: float | None, m: str) -> None:
        db.update_job(jid, progress=p, message=m)          # also a heartbeat

    from . import media
    media.set_progress_hook(progress)
    kind = job["kind"]
    from . import usage
    if kind in ("ingest_source", "ingest_file", "suggest_findings", "reembed", "rank_proposed", "discover"):
        usage.guard()   # cheap check first; transcription/findings re-check with a size-based estimate
    if kind == "ingest_url":
        ext = payload.get("_external_result") or {}
        return ingest.ingest_url(payload["url"], tags=payload.get("tags"), project_id=payload.get("project_id"),
                                 progress=progress, force=bool(payload.get("force")),
                                 cookies_file=payload.get("cookies_file"), referer=payload.get("referer"),
                                 title=payload.get("title"), collection_id=payload.get("collection_id"),
                                 since_years=payload.get("since_years"), max_videos=payload.get("max_videos"),
                                 review=payload.get("review", True), capture=ext.get("capture") if isinstance(ext, dict) else None)
    if kind == "ingest_source":
        return ingest.ingest_source(payload["source_id"], progress=progress, min_date=payload.get("min_date"),
                                    collection_id=payload.get("collection_id"), newest_first=bool(payload.get("newest_first")),
                                    cookies_file=payload.get("cookies_file"), referer=payload.get("referer"))
    if kind == "enrich_profiles_batch":
        from . import library
        return library.run_batch_job(jid, payload, progress)
    if kind == "extract_claims":
        from . import claims
        return claims.run_job(payload, progress)
    if kind == "explore":
        from . import explore
        return explore.explore(payload["url"], payload["kind"], payload.get("project_id"), tags=payload.get("tags"),
                               max_items=payload.get("max_items"), progress=progress)
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
        return suggest_for_project(payload["project_id"], payload.get("source_ids"), progress=progress, force=bool(payload.get("force")), depth=payload.get("depth"))
    if kind == "suggest_findings_batch":
        from .batches import run as run_batch
        return run_batch(jid, payload, progress=progress)
    if kind == "build_plan":
        from .planner import build_plan
        row = build_plan(payload["project_id"], payload.get("instructions"), progress=progress)
        return {"plan_id": row["id"], "version": row["version"]}
    if kind == "discover":
        from .discover import discover
        return discover(payload["project_id"], payload.get("refine"), progress=progress, mode=payload.get("mode") or "library_first")
    if kind == "rank_proposed":
        from .relevance import rank_collection
        return rank_collection(payload["collection_id"], payload.get("project_id"), want=payload.get("want"), progress=progress)
    if kind == "reembed":
        return {"embedded": embed_pending(limit=payload.get("limit", 100000))}
    if kind == "external_demo":
        # reference external job: first run submits and parks; the run after the result arrives completes.
        if "_external_result" in payload:
            crash_point("external_result_before_done")
            return {"completed_with": payload["_external_result"]}
        submit_external("fake", "demo", {"x": payload.get("x")}, deadline=time.time() + 3600, ready_after=int(payload.get("ready_after", 2)))
    raise RuntimeError(f"unknown job kind {kind}")


def execute(job: dict[str, Any], worker_id: str = "worker") -> str:
    """Run one claimed job to its next state and record it. Returns the stored status afterwards.
    Used by the worker threads and, directly, by the crash-matrix tests (a SimulatedCrash propagates out untouched —
    exactly like a dead process: the row stays 'running' with a lease that will expire)."""
    jid, run_id = job["id"], job.get("run_id")
    with _running_lock:
        _running[jid] = run_id or ""
    t0 = time.time()
    providers.set_policy(job.get("execution_policy") or "local_preferred")
    providers.reset_job_route()
    try:
        result = run_job(job)
        _record_execution(jid)
        db.finish_job(jid, run_id, "done", message="done", result=result)
        log.info("job done in %.1fs", time.time() - t0)
        _after_done(job)
        return "done"
    except ExternalPending as e:
        db.park_external(jid, run_id, e.provider, e.kind, e.handle, e.deadline)
        return "external_pending"
    except Cancelled:
        db.finish_job(jid, run_id, "cancelled", message="cancelled")
        pl = job.get("payload") or {}
        sid = pl.get("source_id")
        if sid and job["kind"] == "ingest_source":
            db.set_source_status(sid, "proposed")          # back to the review card; completed stages are kept for a retry
        elif job["kind"] == "ingest_url" and pl.get("url"):
            with db.tx() as conn:                          # a single link: visible + retryable; stages are kept, Retry resumes
                conn.execute("UPDATE sources SET status='failed', error=?, updated_at=? WHERE url=? AND status='pending'",
                             ("cancelled — Retry resumes from the last completed stage", db.now(), pl["url"]))
        return "cancelled"
    except Exception as e:  # noqa: BLE001
        from .media import RateLimited, rate_limit_status
        from .usage import BudgetPaused
        sid = (job.get("payload") or {}).get("source_id")
        if isinstance(e, BudgetPaused):
            db.requeue_job(jid, delay=min(e.wait, 3600), message=f"paused: {e}", wait_reason="budget")
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        from .breakers import ProviderUnavailable, get as breaker_get, wait_message
        from .providers import ProviderError as _PE
        pu = e if isinstance(e, ProviderUnavailable) else (e.__cause__ if isinstance(getattr(e, "__cause__", None), ProviderUnavailable) else None)
        if pu is None and isinstance(e, _PE) and e.operation and breaker_get(e.operation)["state"] != "closed":
            b = breaker_get(e.operation)                      # this job's own attempts tripped the circuit: it waits like everyone else
            pu = ProviderUnavailable(e.operation, b.get("next_probe_at"), b["state"])
        if pu is not None:
            until = pu.next_probe_at or (time.time() + 60)
            db.park_provider_wait(jid, pu.operation, until, wait_message(pu.operation, until))     # J2: 0 attempts, 0 invocations, $0
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        af = e if isinstance(e, AcquisitionFailure) else (e.__cause__ if isinstance(getattr(e, "__cause__", None), AcquisitionFailure) else None)
        if af is not None and af.browser_solvable and job["kind"] == "ingest_url" and (job.get("payload") or {}).get("url") \
                and not (job.get("payload") or {}).get("_external_result"):
            # B1: the user's browser can read what the server cannot — the SAME job waits for the capture (durable, restart-safe)
            park_for_browser(job, run_id, af, job["payload"]["url"])
            db.job_event(jid, "requires_browser", run_id=run_id, adapter=af.adapter, cls=af.cls)
            log.info("job %s requires the browser (%s/%s)", jid[:8], af.adapter, af.cls)
            return "external_pending"
        pe = e if isinstance(e, _PE) else (e.__cause__ if isinstance(getattr(e, "__cause__", None), _PE) else None)
        if pe is not None and pe.error_type == "SPEND_CAP":
            # the ACCOUNT's usage limit (Anthropic Console), not Neuro Search's budget: nothing retries until the date it names.
            # The job waits (0 attempts, $0) like a budget pause, and the whole app can show one banner instead of N failures.
            from .providers import spend_cap_until
            until = spend_cap_until(pe.cause) or (time.time() + 6 * 3600)
            when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(until))
            db.kv_set("providers:spend_cap_until", str(until))
            db.requeue_job(jid, delay=max(60, min(until - time.time(), 30 * 24 * 3600)), wait_reason="budget",
                           message=f"paused: the Anthropic account's usage limit is reached — access returns {when}. Raise the limit in the Anthropic Console to continue sooner.")
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        if isinstance(e, RateLimited) or isinstance(getattr(e, "__cause__", None), RateLimited):
            db.requeue_job(jid, delay=rate_limit_status()["seconds_left"] + 5, message=f"paused: {e}", wait_reason="rate_limit")
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        attempts = int(job.get("attempts") or 0) + 1
        from .providers import TRANSIENT_TYPES, ProviderError
        typed_transient = isinstance(e, ProviderError) and e.error_type in TRANSIENT_TYPES
        if (typed_transient or TRANSIENT.search(str(e))) and attempts < MAX_ATTEMPTS and job["kind"] in RETRYABLE:
            delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
            db.requeue_job(jid, delay=delay, message=f"retry {attempts + 1}/{MAX_ATTEMPTS} in {delay // 60} min — {str(e)[:200]}",
                           wait_reason="retry", count_attempt=True)
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        log.warning("job %s failed: %s", jid, e)
        db.finish_job(jid, run_id, "failed", message=f"error: {e}")
        return "failed"
    finally:
        with _running_lock:
            _running.pop(jid, None)
        _current.job_id = _current.run_id = None


# ------------------------------------------------------------------ workers, lease keeper, recovery, external poller

def _worker_id(n: int | str) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{n}"


def _record_execution(jid: str) -> None:
    """L1: which provider actually ran the job's model calls (local · api · mixed) and the first fallback reason, if any."""
    by, fb = providers.job_route()
    if by or fb:
        try:
            db.set_job_execution(jid, by, fb)
        except Exception as e:  # noqa: BLE001
            log.debug("execution record failed: %s", e)


LOCAL_POLICIES = ("local_preferred", "local_only")
API_POLICIES = ("api_requested", "api_only")


def _worker(n: int, kinds: tuple[str, ...] | None = None, exclude_kinds: tuple[str, ...] | None = None, policies: tuple[str, ...] | None = None,
            lanes: tuple[str, ...] | None = None) -> None:
    wid = _worker_id(n)
    log.info("worker %s started%s%s%s", n, f" ({', '.join(kinds)})" if kinds else "", f" [{'/'.join(policies)}]" if policies else "", f" lanes {'/'.join(lanes)}" if lanes else "")
    while not _stop.is_set():
        job = db.claim_job(kinds, worker_id=wid, exclude_kinds=exclude_kinds, policies=policies, lanes=lanes)
        if not job:
            _stop.wait(1.5)
            continue
        logctx.clear()
        st = execute(job, wid)
        if st == "queued":
            _stop.wait(2)


def _lease_loop(every: float = 30.0) -> None:
    while not _stop.is_set():
        with _running_lock:
            items = list(_running.items())
        for jid, run_id in items:
            try:
                if not db.heartbeat(jid, run_id or None):
                    log.warning("lost the lease on job %s — another worker owns it now", jid[:8])
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat failed: %s", e)
        _stop.wait(every)


def _recovery_loop(every: float = 60.0) -> None:
    while not _stop.is_set():
        try:
            rec = db.recover_expired_leases()
            if rec:
                log.warning("recovered %d job(s) whose worker stopped heartbeating", len(rec))
        except Exception as e:  # noqa: BLE001
            log.warning("recovery failed: %s", e)
        _stop.wait(every)


def _external_loop(every: float = 20.0) -> None:
    while not _stop.is_set():
        try:
            poll_external_once()
        except Exception as e:  # noqa: BLE001
            log.warning("external poll failed: %s", e)
        _stop.wait(every)


def start_workers(n: int | None = None) -> None:
    n = n or settings.workers
    db.init_db()
    requeued = db.requeue_stale_running_jobs()
    if requeued:
        log.info("re-queued %d interrupted jobs (they resume from their last completed stage)", requeued)
    _stop.clear()
    local = settings.ai_profile == "local"
    for i in range(n):
        # local profile: general workers keep ingestion and leave the AI kinds to the two AI pools
        t = threading.Thread(target=_worker, args=(i,), kwargs={"exclude_kinds": ANALYSIS_KINDS} if local else {}, daemon=True, name=f"ns-worker-{i}")
        t.start()
        _threads.append(t)
    if local:
        # L1: the local pool (busy = the job waits, never spends) and one API pool for api_requested / api_only jobs
        # 0.42.1: only the FIRST local worker takes the slow lane (Read deeper); the rest keep serving ordinary findings/ranking
        for i in range(max(1, settings.local_ai_workers)):
            t = threading.Thread(target=_worker, args=(f"local-{i}", ANALYSIS_KINDS), kwargs={"policies": LOCAL_POLICIES, "lanes": None if i == 0 else ("normal",)},
                                 daemon=True, name=f"ns-worker-local-ai-{i}")
            t.start()
            _threads.append(t)
        t = threading.Thread(target=_worker, args=("api", ANALYSIS_KINDS), kwargs={"policies": API_POLICIES}, daemon=True, name="ns-worker-api-ai")
        t.start()
        _threads.append(t)
    else:
        # one extra worker that only does the cheap Claude jobs, so findings/ranking never wait behind slow downloads
        t = threading.Thread(target=_worker, args=(n, ANALYSIS_KINDS), daemon=True, name="ns-worker-analysis")
        t.start()
        _threads.append(t)
    for target, name in ((_backup_loop, "ns-backup"), (_lease_loop, "ns-lease"), (_recovery_loop, "ns-recovery"), (_external_loop, "ns-external")):
        t = threading.Thread(target=target, daemon=True, name=name)
        t.start()
        _threads.append(t)


def _backup_loop(every: float = 3600.0) -> None:
    """Snapshot the database on startup and every hour, so nothing (chats, findings, plans) is more than an
    hour from recoverable. Snapshots: <data>/backups/."""
    while not _stop.is_set():
        try:
            chk = db.integrity_check()
            if not chk["ok"]:
                log.error("DATABASE INTEGRITY CHECK FAILED: %s", chk)
            p = db.backup()
            log.info("database snapshot verified: %s", p.name)
        except Exception as e:  # noqa: BLE001
            log.warning("backup failed: %s", e)
        _stop.wait(every)


def stop_workers() -> None:
    _stop.set()
    for t in _threads:
        t.join(timeout=2)
    _threads.clear()


def _after_done(job: dict[str, Any]) -> None:
    """G5: when findings land, Claims stay current for $0 (harvest) and extraction is queued only when debounced
    thresholds say so — event-driven, never a paid call per finding. Failures here never fail the job."""
    try:
        if job["kind"] in ("suggest_findings", "suggest_findings_batch"):
            pid = (job.get("payload") or {}).get("project_id")
            if pid:
                from . import claims
                claims.harvest(pid)
                claims.maybe_extract(pid, f"after {job['kind']}")
    except Exception as e:  # noqa: BLE001
        log.warning("post-job claims hook skipped: %s", e)


def wait_for_idle(poll: float = 1.0) -> None:
    """Block until there are no queued or running jobs (CLI use)."""
    while True:
        row = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running','external_pending')").fetchone()
        if row["n"] == 0:
            return
        time.sleep(poll)


def enqueue_suggestions(source_id: str, project_id: str | None = None) -> None:
    """After a source becomes ready: queue finding suggestions for each project it belongs to (if enabled)."""
    from . import providers
    if not settings.auto_suggest or not providers.anthropic_available():
        return
    pids = [project_id] if project_id else db.projects_for_source(source_id)
    for pid in pids:
        db.create_job("suggest_findings", {"project_id": pid, "source_ids": [source_id]})
