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

import json
import logging
import os
import re
import socket
import threading
import contextlib
import time
from typing import Any

from . import db, ingest, logctx, providers
from .config import settings
from .embeddings import embed_pending

log = logging.getLogger(__name__)

_stop = threading.Event()
_lease_stop = threading.Event()
_lifecycle_lock = threading.RLock()
_threads: list[threading.Thread] = []
_running: dict[str, str] = {}          # job_id -> run_id owned by this process (lease keeper extends these)
_running_lock = threading.Lock()

# Errors worth retrying on their own: rate limits, login walls that come and go, network hiccups, 5xx.
TRANSIENT = re.compile(r"rate.?limit|too many requests|429|5\d\d|timed? ?out|temporar|connection|reset by peer|unavailable|"
                       r"try again|slow down|login for this|please wait|overloaded|not a bot|sign in to confirm|bot-check", re.I)
RETRYABLE = ("harvest_claims", "ingest_url", "ingest_source", "suggest_findings", "suggest_findings_batch", "rank_proposed", "discover", "build_plan", "external_demo", "refresh_skipped_metadata", "extract_claims", "recover_captions", "bootstrap_scan", "refresh_research", "settle_batches", "explore")
MAX_ATTEMPTS = 4
RETRY_DELAYS = [10 * 60, 30 * 60, 90 * 60]     # seconds between attempts
BILLING_RETRY_SECONDS = 30 * 60   # BILLING (credit balance too low) names no resume date, unlike SPEND_CAP — retry on
                                   # a fixed interval until a call succeeds again (providers.py clears the flag then)
ANALYSIS_KINDS = ("suggest_findings", "suggest_findings_batch", "rank_proposed", "discover", "reembed", "build_plan", "enrich_profiles_batch", "extract_claims")
MAINTENANCE_KINDS = ("harvest_claims",)     # $0 bookkeeping: its own single worker, never an ingestion or AI slot


class Cancelled(RuntimeError):
    """Raised inside a job at a safe boundary after cancellation was requested. Nothing is written after it."""


class Paused(RuntimeError):
    """S86: raised at the same safe boundary after the person pressed pause. Everything written so far is kept; the
    job goes back to the queue held until Resume, and re-running continues from its last completed stage."""


class Yield(Exception):
    """A long job voluntarily gives its worker back at a safe boundary, with durable progress already written.

    0.55.1. The AI pool is three workers and some jobs work for minutes: `extract_claims` measured p90 843 s and
    `rank_proposed` 384 s, while `suggest_findings` — 0.95 s of actual work — waited 4,782 s behind them. Lanes
    cannot fix that, because a lane decides who is claimed NEXT, not who is EVICTED; a running job holds its
    worker whatever arrives. So a long job has to stand up and leave, and this is the shared way to do it rather
    than each one inventing its own (0.55.0's claims fix leaned on a re-trigger that happened to exist).

    The contract for a job that raises this: everything done so far is already persisted, and re-running must skip
    it. Requeued immediately, no delay, no attempt counted — this is not a failure and not a wait."""

    def __init__(self, message: str = "paused so other work can run — continues automatically") -> None:
        super().__init__(message)
        self.message = message


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
    if jid and db.pause_requested(jid):
        raise Paused("paused by the user")


def stage_event(stage: str, state: str = "complete", **payload: Any) -> None:
    jid = getattr(_current, "job_id", None)
    if jid:
        db.job_event(jid, "stage", run_id=getattr(_current, "run_id", None), stage=f"{stage}:{state}", **payload)


def current_job() -> tuple[str | None, str | None]:
    return getattr(_current, "job_id", None), getattr(_current, "run_id", None)


@contextlib.contextmanager
def bound_current(job_id: str | None, run_id: str | None):
    """Bind explicit parent-job identity in a child execution thread."""
    before = current_job()
    _current.job_id, _current.run_id = job_id, run_id
    try:
        yield
    finally:
        _current.job_id, _current.run_id = before


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

def claims_harvest_kind() -> str:
    return "harvest_claims"


def enqueue(kind: str, payload: dict[str, Any], lane: str = "normal", execution_policy: str = "local_preferred",
           not_before: float | None = None) -> dict[str, Any]:
    return db.create_job(kind, payload, lane=lane, execution_policy=execution_policy, not_before=not_before)


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    jid = job["id"]
    payload = job["payload"] or {}
    _current.job_id, _current.run_id = jid, job.get("run_id")
    logctx.set_fields(job_id=jid, run_id=job.get("run_id"), project_id=payload.get("project_id"),
                      source_id=payload.get("source_id"), task=job["kind"])

    def progress(p: float | None, m: str) -> None:
        db.update_job(jid, progress=p, message=m)          # also a heartbeat

    from . import media
    media.set_progress_hook(progress)
    kind = job["kind"]
    from . import usage
    if kind in ("ingest_source", "ingest_file", "suggest_findings", "reembed", "rank_proposed", "discover", "t1_embed_derived"):
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
    if kind == claims_harvest_kind():
        from . import claims
        return claims.run_harvest_job(payload, progress)
    if kind == "settle_batches":
        from . import batches
        return batches.run_settle_job(payload, progress)
    if kind == "refresh_research":
        from . import claims
        return claims.run_refresh_job(payload, progress)
    if kind == "explore":
        if payload.get("kind") == "subreddit":
            from . import reservoir
            result = reservoir.scan_subreddit_page(payload["project_id"], payload["collection_id"],
                                                    expected_run_id=payload.get("catalog_run_id"),
                                                    expected_generation=payload.get("catalog_generation"))
            if result["status"] == "partial":
                raise Yield("catalog page saved; continuing automatically")
            if result["status"] == "blocked":
                raise RuntimeError(result.get("error") or "subreddit catalog scan blocked")
            return result
        from . import explore
        return explore.explore(payload["url"], payload["kind"], payload.get("project_id"), tags=payload.get("tags"),
                               max_items=payload.get("max_items"), progress=progress)
    if kind == "intake_item":
        from . import intake          # P11 EA-4/5: an external intake item, on the ordinary queue
        return intake.process_item(payload["item_id"], progress)
    if kind == "ingest_file":
        from pathlib import Path
        path = Path(payload["path"])
        try:
            return ingest.ingest_local_file(path, title=payload.get("title"), tags=payload.get("tags"),
                                            project_id=payload.get("project_id"), progress=progress,
                                            original_name=payload.get("name"),
                                            capture_event_id=payload.get("capture_event_id"))
        finally:
            path.unlink(missing_ok=True)
    if kind == "suggest_findings":
        from .findings import suggest_for_project
        return suggest_for_project(payload["project_id"], payload.get("source_ids"), progress=progress, force=bool(payload.get("force")), depth=payload.get("depth"),
                                   r6_wave=payload.get("r6_wave"), r6_provisional=bool(payload.get("r6_provisional")),
                                   substance_floor=payload.get("substance_floor"))
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
        return rank_collection(payload["collection_id"], payload.get("project_id"), want=payload.get("want"), progress=progress,
                               only_unscored=bool(payload.get("only_unscored")))
    if kind == "reembed":
        return {"embedded": embed_pending(limit=payload.get("limit", 100000))}
    if kind == "refresh_skipped_metadata":
        return ingest.refresh_skipped_metadata(payload["source_id"])
    if kind == "recover_captions":
        return ingest.recover_caption_text(payload["source_id"])
    if kind == "bootstrap_scan":
        from . import bootstrap
        return bootstrap.run_job(jid, payload, progress=progress)
    if kind == "external_demo":
        # reference external job: first run submits and parks; the run after the result arrives completes.
        if "_external_result" in payload:
            crash_point("external_result_before_done")
            return {"completed_with": payload["_external_result"]}
        submit_external("fake", "demo", {"x": payload.get("x")}, deadline=time.time() + 3600, ready_after=int(payload.get("ready_after", 2)))
    if kind == "t1_embed_derived":
        from . import embeddings
        from . import t1
        table = payload.get("table")
        if table not in ("project_notes", "project_claims"):
            raise ValueError("unsupported T1 derived-vector table")
        if payload.get("provider") != t1.DERIVED_PROVIDER:
            raise ValueError("unsupported T1 embedding provider")
        row = db.connect().execute(f"SELECT * FROM {table} WHERE id=?", (payload["object_id"],)).fetchone()
        if row is None or t1.input_hash(row["content"] if payload["table"] == "project_notes" else row["text"],
                                       row["citations"] if payload["table"] == "project_notes" else row["qualifiers"],
                                       row["source_revision"] if payload["table"] == "project_notes" else row["extraction_hash"],
                                       row["brief_revision"] if payload["table"] == "project_notes" else row["updated_at"]) != payload["input_hash"]:
            return {"skipped": "stale_input"}
        vec = embeddings.embed_texts([payload.get("text") or ""], model=payload["model"])[0]
        db.set_derived_embedding(table, payload["object_id"], vec,
                                 provider=payload["provider"], model=payload["model"],
                                 version=payload["version"], input_hash=payload["input_hash"])
        return {"embedded": payload["object_id"], "dimensions": int(vec.size), "version": payload["version"]}
    raise RuntimeError(f"unknown job kind {kind}")


def execute(job: dict[str, Any], worker_id: str = "worker") -> str:
    """Run one claimed job to its next state and record it. Returns the stored status afterwards.
    Used by the worker threads and, directly, by the crash-matrix tests (a SimulatedCrash propagates out untouched —
    exactly like a dead process: the row stays 'running' with a lease that will expire)."""
    jid, run_id = job["id"], job.get("run_id")
    _current.job_id, _current.run_id = jid, run_id
    with _running_lock:
        _running[jid] = run_id or ""
    t0 = time.time()

    # L-20 (EXECUTION-LADDER.md P1A, missed-window policy, PRODUCT-INTELLIGENCE-MISSION.md §4): "record scheduled
    # time, actual start time, reason for delay" for a job a caller asked to run no earlier than a future time
    # (create_job's not_before -> here as payload["_scheduled_for"], since claim_job() already nulled the
    # not_before column itself at claim time). A deadline (payload["_deadline"], not yet exposed by any caller --
    # ready for the first one that needs "don't run this if it's now too late to matter") is honored here too:
    # "executing late would violate the task's semantics" / "the deadline has passed" from the same ruling.
    scheduled_for = (job.get("payload") or {}).get("_scheduled_for")
    if scheduled_for is not None:
        deadline = (job.get("payload") or {}).get("_deadline")
        delay = t0 - scheduled_for
        if deadline is not None and t0 > deadline:
            db.job_event(jid, "missed_window", run_id=run_id, scheduled=scheduled_for, actual=t0, delay_seconds=delay,
                        reason="deadline passed")
            db.finish_job(jid, run_id, "cancelled",
                          message=f"missed its deadline (scheduled for {time.strftime('%H:%M', time.localtime(scheduled_for))}, "
                                  f"deadline {time.strftime('%H:%M', time.localtime(deadline))}, host unavailable until now)")
            with _running_lock:
                _running.pop(jid, None)
            return "cancelled"
        db.job_event(jid, "scheduled_run_started", run_id=run_id, scheduled=scheduled_for, actual=t0, delay_seconds=delay,
                    reason="on time" if delay < 60 else "host unavailable at the scheduled time; ran at next eligible start")

    providers.set_policy(job.get("execution_policy") or "local_preferred")
    providers.reset_job_route()
    after_done = False
    try:
        from . import ledger
        # P11 (Kyle's ruling 2): a job's writes are Neuro's own work; the person/request that queued it is its cause
        with ledger.acting("system", surface="job", request_id=f"job:{jid}", originating_actor_id=job.get("origin_actor_id"),
                           originating_request_id=job.get("origin_request_id")):
            result = run_job(job)
        _record_execution(jid)
        # 2026-09-15 -- `message` used to be the literal string "done" no matter what happened, so a real
        # no-op (every source already current, or an in-flight batch -- findings.py's `_skipped()`) was
        # indistinguishable from genuine work without opening `result`'s JSON or querying invocations/work_units
        # by hand (the exact diagnosis this cost during E5, docs/T4-ADMISSION-2026-09-14.md). Two known result
        # shapes carry a skip signal: a single-item `_skipped()`-style dict (top-level "skipped" key, a short
        # reason string), and suggest_for_project's per-project summary ("sources"/"done"/"failed"/"skipped"
        # counts). Surface it as the headline message when every source in the job was skipped; leave the
        # ordinary "done" alone when only some were (that's real work, just not all of it).
        done_message = "done"
        if isinstance(result, dict):
            reason = result.get("skipped")
            if isinstance(reason, str) and reason:
                done_message = f"skipped: {reason}"
            elif isinstance(reason, int) and reason and reason == result.get("sources"):
                done_message = f"skipped: all {reason} source(s) already current or in flight"
        db.finish_job(jid, run_id, "done", message=done_message, result=result)
        log.info("job done in %.1fs", time.time() - t0)
        after_done = True
        return "done"
    except ExternalPending as e:
        db.park_external(jid, run_id, e.provider, e.kind, e.handle, e.deadline)
        return "external_pending"
    except Paused:
        db.hold_paused(jid, run_id)
        return "queued"
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
        if isinstance(e, Yield):
            db.requeue_job(jid, delay=0, message=e.message)
            db.job_event(jid, "yielded", run_id=job.get("run_id"), message=e.message)
            return "queued"
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
        if pe is not None and pe.error_type in providers.LOCAL_TYPES:
            _record_execution(jid)
            db.requeue_job(jid, delay=60, wait_reason="provider",
                           message="paused: local AI unavailable — waiting locally; no paid API fallback. Use Accelerate to choose paid execution.")
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
        if pe is not None and pe.error_type == "BILLING":
            # the account's credit balance, not a rate/usage cap — this will not clear itself on a schedule the way
            # SPEND_CAP's stated date does, so this parks (0 attempts, $0) and retries on a fixed interval; a plain
            # banner beats a raw SDK exception as the job's message, and one banner beats N sources failing alike.
            until = time.time() + BILLING_RETRY_SECONDS
            db.kv_set("providers:billing_until", str(until))
            db.requeue_job(jid, delay=BILLING_RETRY_SECONDS, wait_reason="budget",
                           message="paused: the Anthropic account's credit balance is too low — add credits in Plans & Billing to continue. Nothing is lost; this resumes automatically once credits are added.")
            if sid:
                db.set_source_status(sid, "pending")
            return "queued"
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
        # 0.61.0: and the hook itself is cleared, so work this job abandoned (a yt-dlp download that outlived a
        # timed-out metadata fetch) has nowhere left to report to.
        try:
            media.set_progress_hook(None)
        except Exception:  # noqa: BLE001
            pass
        with _running_lock:
            _running.pop(jid, None)
        _current.job_id = _current.run_id = None
        # P0.2 (docs/SPEED-AUDIT-2026-09-17.md): the post-completion hook runs ONLY after the job has left
        # `_running`. It used to run before this `finally`, so a job whose row was already `done` stayed on the
        # lease keeper's list for as long as the hook took — 5–6 minutes of harvest on the live project — and
        # every 30 s heartbeat on it logged a takeover that never happened. Whatever the hook costs now, the
        # job's truthful terminal state and its lease bookkeeping are settled first.
        if after_done:
            _after_done(job)


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
    while not _lease_stop.is_set():
        with _running_lock:
            items = list(_running.items())
        for jid, run_id in items:
            try:
                if not db.heartbeat(jid, run_id or None):
                    log.warning("lost the lease on job %s — another worker owns it now", jid[:8])
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat failed: %s", e)
        _lease_stop.wait(every)


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


def _thread_main(target: Any, db_path: Any, args: tuple = (), kwargs: dict | None = None) -> None:
    """A worker generation owns its original database, even if a test changes global settings."""
    db._local.db_path = db_path
    try:
        target(*args, **(kwargs or {}))
    finally:
        db.close_thread_connection()
        db._local.__dict__.pop("db_path", None)
        logctx.clear()


def start_workers(n: int | None = None) -> None:
    with _lifecycle_lock:
        if any(t.is_alive() for t in _threads):
            raise RuntimeError("Workers are already running or still shutting down; refusing a second generation")
        _threads.clear()
        _start_workers(n)


def _start_workers(n: int | None = None) -> None:
    n = n or settings.workers
    db.init_db()
    requeued = db.requeue_stale_running_jobs()
    if requeued:
        log.info("re-queued %d interrupted jobs (they resume from their last completed stage)", requeued)
    _stop.clear()
    _lease_stop.clear()
    # L-21 (EXECUTION-LADDER.md): no-op off macOS / without `caffeinate` -- power_assertion.start() reports that
    # honestly rather than pretending to hold an assertion it can't.
    from . import power_assertion
    power_assertion.start()
    local = settings.ai_profile == "local"
    for i in range(n):
        # local profile: general workers keep ingestion and leave the AI kinds to the two AI pools.
        # 2026-09-18 (Kyle, live): they also leave the $0 MAINTENANCE kinds to the maintenance worker below. The
        # first cut of P0.2 put `harvest_claims` on the normal lane for these general workers, and the moment a
        # findings burst queued three harvests the three general workers were all inside them — one harvesting,
        # two parked on `_harvest_lock` — while the twenty transcripts of a channel Kyle had just added sat queued
        # with nobody to run them. Ingestion is what the person is waiting on; a harvest is never that.
        t = threading.Thread(target=_thread_main, args=(_worker, settings.db_path, (i,),
                             {"exclude_kinds": ANALYSIS_KINDS + MAINTENANCE_KINDS} if local else {"exclude_kinds": MAINTENANCE_KINDS}),
                             daemon=True, name=f"ns-worker-{i}")
        t.start()
        _threads.append(t)
    # ONE maintenance worker: $0 bookkeeping kinds run here, serialized, so they can neither occupy an ingestion
    # worker nor an AI worker, and two harvests for one project can never park a second thread on the lock.
    t = threading.Thread(target=_thread_main, args=(_worker, settings.db_path, ("maintenance", MAINTENANCE_KINDS)),
                         daemon=True, name="ns-worker-maintenance")
    t.start()
    _threads.append(t)
    if local:
        # L1: the local pool (busy = the job waits, never spends) and one API pool for api_requested / api_only jobs
        # 0.42.1: only the FIRST local worker takes the slow lane (Read deeper); the rest keep serving ordinary findings/ranking
        for i in range(max(1, settings.local_ai_workers)):
            t = threading.Thread(target=_thread_main, args=(_worker, settings.db_path, (f"local-{i}", ANALYSIS_KINDS), {"policies": LOCAL_POLICIES, "lanes": None if i == 0 else ("normal", "priority", "low")}),
                                 daemon=True, name=f"ns-worker-local-ai-{i}")
            t.start()
            _threads.append(t)
        # 0.63.13 — `settings.api_ai_workers` (3), not a hard-coded 1. Accelerating moves jobs to `api_requested`
        # precisely because the user asked to buy speed, and one thread served them one at a time: 385 of Kyle's
        # findings jobs ran this pool. Nothing about spend changes — the rate ceiling, budgets and account gates
        # are what bound cost, and a thread count was never the right instrument for it.
        for i in range(max(1, settings.api_ai_workers)):
            t = threading.Thread(target=_thread_main, args=(_worker, settings.db_path, (f"api-{i}", ANALYSIS_KINDS), {"policies": API_POLICIES}),
                                 daemon=True, name=f"ns-worker-api-ai-{i}")
            t.start()
            _threads.append(t)
    else:
        # one extra worker that only does the cheap Claude jobs, so findings/ranking never wait behind slow downloads
        t = threading.Thread(target=_thread_main, args=(_worker, settings.db_path, (n, ANALYSIS_KINDS)), daemon=True, name="ns-worker-analysis")
        t.start()
        _threads.append(t)
    for target, name in ((_backup_loop, "ns-backup"), (_lease_loop, "ns-lease"), (_recovery_loop, "ns-recovery"),
                         (_external_loop, "ns-external"), (_housekeeping_loop, "ns-housekeeping")):
        t = threading.Thread(target=_thread_main, args=(target, settings.db_path), daemon=True, name=name)
        t.start()
        _threads.append(t)


def _housekeeping_loop(every: float = 120.0) -> None:
    """0.61.2: keep the write-ahead log from becoming the slowest thing in the app.

    Measured on Kyle's machine while it was unresponsive: a 111.8 MB WAL beside a 627 MB database, static —
    SQLite's own auto-checkpoint had been starved for days because this app keeps a long-lived connection per
    thread and several of those threads run multi-second derived-state passes, so there was always an older
    snapshot in the way. A checkpoint that cannot run is not an error; it is a thing to try again shortly, which
    is exactly what a loop is for."""
    # 0.63.6: warm BEFORE the first wait. The loop waited 120 s before doing anything, so the two minutes right
    # after a relaunch — exactly when he opens the app, because relaunching is what he had just been told to do —
    # were the cold ones. Measured cold on his project: staleness/triage 8.1 s, Claims 7.7 s, Research 8.0 s,
    # against 50–170 ms warm.
    _warm_quality()
    _backfill_research()
    while not _stop.is_set():
        _stop.wait(every)
        if _stop.is_set():
            break
        try:
            # L-30 (EXECUTION-LADDER.md Stage 4): checked on the same cadence as WAL checkpointing -- off by
            # default (settings.t4_nightly_budget == 0), and due() itself is the idempotency guard (kv-recorded
            # per calendar date), so a missed or repeated check here can never double-run the night.
            from . import nightly
            if nightly.due():
                nightly.run()
        except Exception as e:  # noqa: BLE001
            log.warning("nightly envelope check skipped: %s", e)
        try:
            r = db.checkpoint_wal()
            if r.get("checkpointed"):
                log.info("housekeeping: WAL %.1f MB -> %.1f MB", (r.get("was") or 0) / 1e6, r["wal_bytes"] / 1e6)
            stats = db.analyze_if_due()
            if stats.get("analyzed"):
                log.info("housekeeping: planner statistics refreshed (%d rows, %.3f s)",
                         stats["stat_rows"], stats["seconds"])
        except Exception as e:  # noqa: BLE001
            log.warning("housekeeping skipped: %s", e)
        _warm_quality()


def _backfill_research() -> list[str]:
    """A project with findings and NO research state gets its harvest queued, once.

    Found on Kyle's database (0.63.11): *Real Estate Investment Strategy* — **605 findings, 0 Claims, 0 knowledge
    nodes, 0 evidence targets**, so its whole Research tab read as an empty project. The cause is not the hook:
    `_after_done` harvests after every findings job, and 72 of them completed for that project. They completed
    between 2026-09-03 and 2026-09-08 00:09, and **the earliest Claim anywhere in the database is 2026-09-08
    01:07** — its findings all landed before the machinery was live in his app, and nothing ever went back.

    Run by hand afterwards it took **652 ms and produced 589 Claims for $0.** So the defect is that research state
    was only ever built FORWARD: a project whose findings predate the feature, or whose hook failed once, stays
    empty for ever and looks like a project with nothing in it.

    `refresh_research` is the existing job, on the `low` lane, deduped per project; the marker means a project is
    offered this at most once, so a project whose findings genuinely yield no Claims is not retried for ever."""
    queued: list[str] = []
    try:
        from . import claims
        rows = db.connect().execute(
            "SELECT p.id FROM projects p WHERE EXISTS (SELECT 1 FROM project_notes n WHERE n.project_id=p.id) "
            "AND NOT EXISTS (SELECT 1 FROM project_claims c WHERE c.project_id=p.id)").fetchall()
        for r in rows:
            pid = r["id"]
            if db.kv_get(f"claims:backfilled:{pid}"):
                continue
            db.kv_set(f"claims:backfilled:{pid}", str(time.time()))
            if claims.maybe_refresh(pid):
                queued.append(pid)
                log.info("queued the first research harvest for project %s", pid[:8])
    except Exception as e:  # noqa: BLE001 — a backfill is a nicety and never stops the loop
        log.warning("research backfill skipped: %s", e)
    return queued


def _warm_quality() -> None:
    """Compute the expensive derived state for each project HERE, in the background, so no screen waits for it.

    0.61.2 made the duplicate summary serve the previous answer, which fixed every visit except the first after a
    restart — and that one still cost 9.8 s and dragged everything else with it. Re-measured after it: `/findings`
    was **23.2 s cold** on the 17,000-note project, because a cold request was also building the research areas
    from 13,000 Claims. All three passes are worth having and none is worth having in a request."""
    try:
        from . import candidates, claims_view, findings_quality, findings_view, research_view, staleness
        for row in db.connect().execute("SELECT id FROM projects ORDER BY updated_at DESC LIMIT 8").fetchall():
            pid = row["id"]
            for what, fn in (("areas", lambda: research_view.areas(pid)),
                             ("rows", lambda: findings_view.decorated(pid)),
                             ("quality", lambda: findings_quality.summary(pid, warm=True)),
                             # 0.63.6 — the two remaining cold screens, measured through his browser. Both are
                             # already cached on a revision; nothing was computing them before a person did.
                             ("triage", lambda: staleness.triage(pid)),
                             ("claims", lambda: claims_view.query(pid)),
                             # 0.63.20 — the pool was the last screen with no background writer: 8,970 items
                             # scored per request, measured at 2.8 s cold / 1.5 s warm on his machine.
                             ("pool", lambda: candidates.pool(pid, limit=1))):
                try:
                    fn()                          # each is cached under the project's current revision
                except Exception as e:  # noqa: BLE001
                    log.debug("warm %s skipped for %s: %s", what, pid[:8], e)
    except Exception as e:  # noqa: BLE001
        log.warning("warm-up skipped: %s", e)


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


def stop_workers(timeout: float = 10.0) -> None:
    """Stop admission, drain work, then stop heartbeats. Never forget a surviving thread."""
    from . import power_assertion
    power_assertion.stop()
    with _lifecycle_lock:
        _stop.set()
        deadline = time.monotonic() + timeout
        for t in _threads:
            if t.name != "ns-lease":
                t.join(timeout=max(0.0, deadline - time.monotonic()))
        survivors = [t.name for t in _threads if t.name != "ns-lease" and t.is_alive()]
        if survivors:
            # Keep the lease keeper alive until draining finishes. A caller may retry shutdown;
            # restarting in this process is refused while this generation still exists.
            raise RuntimeError("Worker shutdown incomplete: " + ", ".join(survivors))
        _lease_stop.set()
        for t in _threads:
            if t.name == "ns-lease":
                t.join(timeout=max(0.0, deadline - time.monotonic()))
        survivors = [t.name for t in _threads if t.is_alive()]
        if survivors:
            raise RuntimeError("Worker shutdown incomplete: " + ", ".join(survivors))
        _threads.clear()


def _after_done(job: dict[str, Any]) -> None:
    """G5: when findings land, Claims stay current for $0 (harvest) and extraction is queued only when debounced
    thresholds say so — event-driven, never a paid call per finding. Failures here never fail the job."""
    try:
        if job["kind"] in ("suggest_findings", "suggest_findings_batch"):
            pid = (job.get("payload") or {}).get("project_id")
            if pid:
                # P0.2: queue the $0 harvest instead of running it here (see claims.request_harvest). This hook now
                # costs one small INSERT, and execute() runs it only after the job has left `_running`.
                from . import claims
                claims.request_harvest(pid, f"after {job['kind']}")
    except Exception as e:  # noqa: BLE001
        log.warning("post-job claims hook skipped: %s", e)


def wait_for_idle(poll: float = 1.0) -> None:
    """Block until there are no queued or running jobs (CLI use)."""
    while True:
        row = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running','external_pending')").fetchone()
        if row["n"] == 0:
            return
        time.sleep(poll)


FIRST_WAVE_RANKED = 3     # of a whole channel/playlist, the top N by the ranking the user already reviewed
FIRST_WAVE_CAP = 12       # a hard ceiling per project, whatever the rules below decide
FAST_WAVE_SIZE = 3        # R6: a small paid first wave; the remaining sources stay eligible on the warm/local path
FAST_WAVE_MIN_BATCH = 6   # a hand-picked few keeps existing user-pick semantics; a real bulk request gets Fast/Warm


USER_PICK_MAX = 5         # named sources in one request that still reads as "I clicked this", not a sweep


def user_pick_lane(named: bool, count: int) -> str | None:
    """The lane for work a person picked by hand just now, or None if this is not that.

    Measured on Kyle's project (0.63.5): of 2,507 completed `suggest_findings` jobs, **2,504 ran in lane `normal`**,
    waiting a median of **2.6 hours** and up to 17 hours for 25 seconds of work — including every source he clicked
    "Suggest findings" on himself. `bumped_at` was NULL on all 2,511 jobs ever created, so the priority mechanism
    built in 0.45.12 had never once been used.

    The cause was a rule that was right for the case it was written for: `first_wave_lane` returns `normal` as soon
    as a project has any findings, because there is nothing left to *bootstrap*. But bootstrapping is not the only
    reason a job should go first. **A source the user names in a request is the strongest statement of intent the
    app ever receives** — they are sitting there waiting on that one source — and it was the single case with no
    priority at all.

    A sweep is not a pick: "analyse everything" names no sources (the endpoint fills them in from the project), and
    a request naming more than `USER_PICK_MAX` is a bulk action whose value does not depend on any one item landing
    first. Ordering only — same provider, same model, same cost."""
    return "priority" if named and 0 < count <= USER_PICK_MAX else None


def first_wave_lane(project_id: str, source_id: str | None = None) -> str:
    """Which sources jump the global queue so a project is usable while the rest of it ingests.

    Kyle set the rule, and it is better than the arrival-order one it replaces: *"fast batch of findings needs to
    be like top 3 videos by ranking when ingesting a whole channel, and start findings right away when videos are
    added individually."* Both halves are really the same signal — how deliberately did the user choose this
    source? — and both are free to compute from data that already exists:

      added on its own   →  always first. You added one video; you are waiting on that video.
      from a collection  →  only the top FIRST_WAVE_RANKED by the relevance ranking `rank_proposed` already
                            produced at review time. That ranking exists before anything is downloaded, so "the
                            top 3 of this channel" is decidable the moment each one becomes ready, without
                            waiting for its siblings.

    Free either way: this changes queue ORDER only — same local provider, same model, same $0. And it cannot
    re-trigger itself (0.48.0's lesson): a project that already has findings is not bootstrapping any more, and
    FIRST_WAVE_CAP bounds the whole thing regardless of what the rules say."""
    try:
        if db.connect().execute("SELECT COUNT(*) FROM project_notes WHERE project_id=? LIMIT 1", (project_id,)).fetchone()[0]:
            return "normal"                                   # already has findings: nothing to bootstrap
        used = int(db.kv_get(f"firstwave:{project_id}") or 0)
        if used >= FIRST_WAVE_CAP:
            return "normal"
        rank, size = (db.rank_within_collections(project_id, source_id) if source_id else (None, 0))
        deliberate = rank is None                              # in no collection = added on its own
        if not deliberate and (rank or 99) > FIRST_WAVE_RANKED:
            return "normal"                                    # a channel's 4th-best video can wait its turn
        db.kv_set(f"firstwave:{project_id}", str(used + 1))
        return "priority"
    except Exception:  # noqa: BLE001 — a promotion is a nicety; never let it stop a job being queued
        return "normal"


def enqueue_suggestions(source_id: str, project_id: str | None = None) -> None:
    """After a source becomes ready: queue finding suggestions for each project it belongs to (if enabled)."""
    from . import providers
    if not settings.auto_suggest or not providers.anthropic_available():
        return
    pids = [project_id] if project_id else db.projects_for_source(source_id)
    for pid in pids:
        db.create_job("suggest_findings", {"project_id": pid, "source_ids": [source_id]}, lane=first_wave_lane(pid, source_id))


def _wave_tokens(text: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if w not in {"with", "from", "that", "this", "what", "when", "where"}}


def fast_wave_plan(project_id: str, source_ids: list[str], limit: int = FAST_WAVE_SIZE) -> list[dict[str, Any]]:
    """Deterministically choose a small high-value, diverse portfolio without a model call.

    This ranks only sources supplied by the bulk request. A high score changes scheduling order, never eligibility;
    every unselected source remains a warm job. Diversity is greedy but deterministic: source id breaks every tie.
    """
    from . import knowledge, novelty, sources_value
    ids = list(dict.fromkeys(source_ids))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = {r["id"]: dict(r) for r in db.connect().execute(
        f"SELECT id, title, description, channel, platform FROM sources WHERE id IN ({marks})", ids).fetchall()}
    values = sources_value.compute(project_id)
    relevance = {r["source_id"]: int(r["relevance"] or 0) for r in db.connect().execute(
        f"SELECT source_id, relevance FROM project_source_analysis WHERE project_id=? AND analysis_kind='relevance' AND source_id IN ({marks})",
        (project_id, *ids)).fetchall()}
    target_words = set().union(*(_wave_tokens(t.get("question") or "") for t in knowledge.list_targets(project_id, status="open")))
    residuals = novelty.profiles(project_id, ids, comparison_source_ids=ids)
    candidates = []
    for sid in ids:
        source = rows.get(sid)
        if not source:
            continue
        words = _wave_tokens(f"{source.get('title') or ''} {source.get('description') or ''}")
        target_hits = len(words & target_words)
        value = int((values.get(sid) or {}).get("value_score") or 0)
        priority = bool((values.get(sid) or {}).get("priority"))
        residual = residuals[sid]
        novelty_adjustment = novelty.priority_adjustment(residual)
        base = (1000 if priority else 0) + value * 10 + relevance.get(sid, 0) + min(40, target_hits * 8) + novelty_adjustment
        why = ([] if not priority else ["priority source"])
        if value:
            why.append(f"existing project value {value}")
        if relevance.get(sid):
            why.append(f"review score {relevance[sid]}")
        if target_hits:
            why.append(f"matches {target_hits} open-target term{'s' if target_hits != 1 else ''}")
        if residual["available"]:
            why.append(f"project-relative redundancy {int(float(residual['redundancy']) * 100)}%; residual chunks read first")
        candidates.append({"source_id": sid, "base": base, "creator": (source.get("channel") or "").strip().lower(),
                           "platform": source.get("platform") or "", "why": why or ["available source"]})
    selected, creators, platforms = [], set(), set()
    while candidates and len(selected) < max(1, min(int(limit), FAST_WAVE_SIZE)):
        def key(item: dict[str, Any]) -> tuple[int, int, int, str]:
            creator_bonus = 30 if item["creator"] and item["creator"] not in creators else 0
            platform_bonus = 5 if item["platform"] and item["platform"] not in platforms else 0
            return (item["base"] + creator_bonus + platform_bonus, creator_bonus, platform_bonus, item["source_id"])
        picked = max(candidates, key=key)
        picked["diversity"] = ("new creator" if picked["creator"] and picked["creator"] not in creators else
                                "new source type" if picked["platform"] and picked["platform"] not in platforms else "best remaining score")
        selected.append(picked)
        candidates.remove(picked)
        if picked["creator"]:
            creators.add(picked["creator"])
        if picked["platform"]:
            platforms.add(picked["platform"])
    return selected


def enqueue_fast_warm(project_id: str, source_ids: list[str], *, force: bool = False) -> dict[str, Any]:
    """R6 bulk admission: fast sources get explicit paid priority; all others remain warm/local and eligible."""
    ids = list(dict.fromkeys(source_ids))
    plan = fast_wave_plan(project_id, ids)
    fast = {row["source_id"]: row for row in plan}
    jobs_ = []
    for sid in ids:
        wave = "fast" if sid in fast else "warm"
        payload = {"project_id": project_id, "source_ids": [sid], "force": force, "r6_wave": wave,
                   "r6_provisional": wave == "fast", "r6_reason": (fast[sid]["why"] + [fast[sid]["diversity"]]) if sid in fast else ["continues after the fast wave"]}
        jobs_.append(db.create_job("suggest_findings", payload, lane="priority" if wave == "fast" else "normal",
                                   execution_policy="api_requested" if wave == "fast" else "local_preferred"))
    return {"fast": [row["source_id"] for row in plan], "warm": [sid for sid in ids if sid not in fast],
            "jobs": jobs_, "reasons": {row["source_id"]: row["why"] + [row["diversity"]] for row in plan}}


def promote_warm_sources(project_id: str, source_ids: list[str], limit: int = FAST_WAVE_SIZE) -> dict[str, Any]:
    """Promote existing compatible warm jobs; never recreates a job or discards R4 completed units."""
    wanted = set(source_ids)
    rows = [j for j in db.list_jobs(limit=10000, statuses=("queued",)) if j.get("kind") == "suggest_findings"]
    eligible = []
    for job in rows:
        payload = job.get("payload") or {}
        sid = (payload.get("source_ids") or [None])[0]
        if payload.get("project_id") == project_id and payload.get("r6_wave") == "warm" and sid in wanted:
            eligible.append((str(sid), job))
    plan_order = {r["source_id"]: i for i, r in enumerate(fast_wave_plan(project_id, [sid for sid, _ in eligible], limit=limit))}
    eligible.sort(key=lambda pair: (plan_order.get(pair[0], 9999), pair[0], pair[1]["id"]))
    moved = []
    for sid, job in eligible[:max(1, min(int(limit), FAST_WAVE_SIZE))]:
        db.set_job_policy(job["id"], "api_requested")
        db.set_job_lane(job["id"], "priority")
        moved.append(job["id"])
    return {"promoted": len(moved), "job_ids": moved, "remaining_warm": max(0, len(eligible) - len(moved))}


# ------------------------------------------------------------------ L3: the acceleration dialog — "the local provider is slow, buy speed on purpose"

WINDOW_CHARS_PER_WINDOW = 60000     # findings._windows; used only to estimate how many model calls a queued source needs


def _windows_for(source_id: str) -> int:
    row = db.connect().execute("SELECT COALESCE(SUM(LENGTH(text)),0) c, COALESCE(MAX(0),0) FROM segments WHERE source_id=?", (source_id,)).fetchone()
    return max(1, int((int(row["c"] or 0) + WINDOW_CHARS_PER_WINDOW - 1) // WINDOW_CHARS_PER_WINDOW))


def backlog(project_id: str | None = None) -> dict[str, Any]:
    """What is waiting on the local provider, what it will cost in TIME there, and what the same work would cost in
    DOLLARS on the API. Pure computation — reads the queue, never changes it."""
    from . import claude_code, sources_value, staleness, usage
    rate = usage.observed_rate_per_minute()
    rows = [dict(r) for r in db.connect().execute(
        "SELECT id, kind, payload, status, execution_policy, lane, created_at FROM jobs WHERE kind IN "
        f"({','.join('?' for _ in ANALYSIS_KINDS)}) AND status IN ('queued','running') ORDER BY created_at", ANALYSIS_KINDS).fetchall()]
    value = sources_value.compute(project_id) if project_id else {}
    items, running = [], []
    for r in rows:
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        if project_id and pl.get("project_id") != project_id:
            continue
        sids = pl.get("source_ids") or []
        cost = round(sum(usage.estimate_source_findings(s, rate) for s in sids), 4)
        windows = sum(_windows_for(s) for s in sids) or 1
        if pl.get("depth") == "deep":
            windows *= 3                                   # deep reads re-window at DEEP_WINDOW_CHARS
        title = (db.get_source(sids[0]) or {}).get("title") if sids else None
        item = {"id": r["id"], "kind": r["kind"], "status": r["status"], "lane": r["lane"], "policy": r["execution_policy"], "depth": pl.get("depth"),
                "source_ids": sids, "title": title, "sources": len(sids), "windows": windows, "api_cost": cost,
                "value": max((value.get(s, {}).get("value_score", 0) for s in sids), default=0)}
        (running if r["status"] == "running" else items).append(item)
    local = [i for i in items if i["policy"] in LOCAL_POLICIES]
    api_side = [i for i in items if i["policy"] in API_POLICIES]
    minutes = sum(i["windows"] for i in local) * staleness.LOCAL_MINUTES_PER_WINDOW
    ready = claude_code.health_snapshot(model=claude_code.local_model_for(claude_code.DOMINANT_LOCAL_TASK)).get("state") == "ready" and settings.ai_profile == "local"
    return {"local_queued": len(local), "api_queued": len(api_side), "running": running, "jobs": local,
            "windows": sum(i["windows"] for i in local), "local_minutes": round(minutes) if ready else None,
            "local_eta": staleness._hm(minutes) if ready and local else None,
            "api_cost": round(sum(i["api_cost"] for i in local), 2), "profile": settings.ai_profile, "local_ready": ready,
            "options": accelerate_options(project_id, local),
            "pools": _pool_shape(len(local), len(api_side)),
            "choices": [n for n in (10, 25) if n < len(local)] + ([len(local)] if local else []),
            "line": (f"{len(local)} job{'s' if len(local) != 1 else ''} waiting on Claude Code · about {staleness._hm(minutes)} · the same work on the API ≈ ${sum(i['api_cost'] for i in local):.2f}"
                     if local and ready else f"{len(local)} AI job{'s' if len(local) != 1 else ''} queued" if local else "nothing waiting")}


def _pool_shape(n_local: int, n_api: int) -> dict[str, Any]:
    """Why a long queue can feel serialised (0.59.2). Kyle: "it feels like we are not doing the api and background
    at the same time." He is right, and it is structural rather than a stall: `start_workers` partitions the AI
    workers by execution policy — the local pool claims `LOCAL_POLICIES`, the api pool claims `API_POLICIES` — and
    ordinary findings work is created `local_preferred`. So the API worker is idle BY CONSTRUCTION whenever the
    backlog is ordinary work, however long that backlog is. Accelerating is the only thing that gives it anything to
    do, which is a defensible design (it never spends without being asked) but it was never SAID anywhere.

    0.63.13: the sizes are reported from the settings rather than hard-coded, because `api_workers` used to be
    literally `1` in this dict AND in `start_workers` — so the panel was truthfully reporting a limit nobody had
    chosen."""
    local_workers = max(1, settings.local_ai_workers) if settings.ai_profile == "local" else 0
    return {"local_workers": local_workers,
            "api_workers": max(1, settings.api_ai_workers) if settings.ai_profile == "local" else 0,
            "local_queued": n_local, "api_queued": n_api,
            "api_idle_by_construction": bool(local_workers and n_local and not n_api),
            "why": ("Ordinary AI work is created `local_preferred`, and the API worker only claims `api_requested` / "
                    "`api_only`. So it cannot help with this backlog until you move some of it across — that is what "
                    "accelerating does, and it is the only thing that spends money here.")}


# --- accelerate options: each a DIFFERENT set, each with its own reason and price (0.59.2) ------------------------
#
# Kyle: "two of the spend options are identical and worthless ... the 'most valuable first' option and the 'do all'
# option are the same, making 'most valuable' pointless."  He was exactly right and for two compounding reasons:
#   1. `order="value"` SORTS the set it is given, so with n = every queued job the sort changes nothing at all;
#   2. the value came from `sources_value.compute(project_id)`, which is empty when no project is in scope — so on a
#      subset the ordering was frequently a no-op too, and two buttons quietly did identical work.
# An option is now a SET with a stated criterion and its own cost, and identical sets are collapsed so the dialog can
# never again offer the same purchase twice under two names.

ACCEL_SUBSET_MAX = 25


def accelerate_options(project_id: str | None, local: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The genuinely distinct purchases available, cheapest first. Never two names for one set."""
    if local is None:
        local = [i for i in backlog(project_id)["jobs"]]
    if not local:
        return []
    opts: list[dict[str, Any]] = []

    def add(key: str, label: str, why: str, picked: list[dict[str, Any]]) -> None:
        if not picked:
            return
        ids = sorted(j["id"] for j in picked)
        for o in opts:
            if o["job_ids"] == ids:          # same set, different name — the exact bug being fixed
                return
        opts.append({"key": key, "label": label, "why": why, "n": len(ids), "job_ids": ids,
                     "api_cost": round(sum(j["api_cost"] for j in picked), 2)})

    # 1. answers something you are waiting on — the same two signals Kyle chose for claim triage
    targeted = [j for j in local if j.get("value", 0) > 0 or j.get("lane") == "priority"]
    add("waiting_on", f"The {len(targeted)} tied to work you are waiting on",
        "Jobs on a priority source, or whose source already earned a value score in this project.", targeted[:ACCEL_SUBSET_MAX])
    # 2. the most valuable, as a bounded subset — meaningful only because it is a subset
    if len(local) > 5:
        by_value = sorted(local, key=lambda j: (-j.get("value", 0), j["id"]))[:min(ACCEL_SUBSET_MAX, max(5, len(local) // 4))]
        add("most_valuable", f"The {len(by_value)} most valuable",
            "Highest value score first — what these sources have already given this project.", by_value)
    # 3. the quickest wins: fewest windows, so the most jobs cleared per dollar
    if len(local) > 5:
        cheap = sorted(local, key=lambda j: (j["windows"], j["id"]))[:min(ACCEL_SUBSET_MAX, max(5, len(local) // 4))]
        add("cheapest", f"The {len(cheap)} cheapest to finish",
            "Fewest windows to read, so the most jobs cleared per dollar.", cheap)
    # 4. everything
    add("all", f"All {len(local)}", "The whole backlog moves to the API.", local)
    opts.sort(key=lambda o: (o["api_cost"], o["n"]))
    return opts


def accelerate(project_id: str | None, n: int = 10, order: str = "queue", option: str | None = None) -> dict[str, Any]:
    """Move the next N queued local jobs onto the API pool — the user's explicit purchase of speed, never implied by
    slowness. Marks them `api_requested`; the api_ai worker claims them. Returns what it moved and the estimate."""
    b = backlog(project_id)
    jobs_ = b["jobs"]
    if option:
        # 0.59.2: an option names a SET, computed and priced by `accelerate_options`, so what is bought is exactly
        # what the button said it would be — no re-derivation, no drift between the estimate and the purchase.
        chosen = next((o for o in b.get("options") or [] if o["key"] == option), None)
        if chosen is None:
            raise ValueError(f"unknown accelerate option {option!r}")
        ids = set(chosen["job_ids"])
        picked = [j for j in jobs_ if j["id"] in ids]
        for j in picked:
            db.set_job_policy(j["id"], "api_requested")
        return {"moved": len(picked), "job_ids": [j["id"] for j in picked],
                "api_cost": round(sum(j["api_cost"] for j in picked), 2),
                "option": option, "label": chosen["label"], "remaining": len(jobs_) - len(picked)}
    if order == "value":
        jobs_ = sorted(jobs_, key=lambda j: (-j["value"], j["id"]))
    picked = jobs_[:max(0, n)]
    for j in picked:
        db.set_job_policy(j["id"], "api_requested")
    return {"moved": len(picked), "job_ids": [j["id"] for j in picked], "api_cost": round(sum(j["api_cost"] for j in picked), 2),
            "order": order, "remaining": len(jobs_) - len(picked)}
