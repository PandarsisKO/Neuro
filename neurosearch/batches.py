"""Rung G — Message Batches for background findings extraction.

    logical work items (one per transcript window, stable custom_id)
          ↓ cohort (the queue groups compatible items; sizing is a transport choice, not a findings semantic)
    provider batch  ── external_pending ──  poll  ──  ended
          ↓
    persist every item's raw result locally (Neuro Search's database is authoritative; provider retention is not part of durability)
          ↓
    validate exactly like the interactive path (structured() → full schema; quote validator in findings.materialize)
          ↓
    materialize per source once ALL its windows succeeded; failed/expired/canceled items → next cohort (only those), up to MAX_COHORTS

Durability invariants kept from Mission D: intent persisted before submission, handle persisted, `external_pending`
while the provider owns the work, crash recovery re-attaches and never blindly resubmits, every request mapped by
custom_id, each item outcome handled explicitly, partial failure retries only the failed logical work, cancellation
never destroys completed valid results. Batch provenance is explicit: transport='batch', batch_id, custom_id, per-item
ledger rows, batch pricing (50% off model tokens — nothing else).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

PROVIDER = "anthropic_batch"
JOB_KIND = "suggest_findings_batch"
MAX_COHORTS = 3                       # a logical item is submitted at most this many times
DEADLINE_S = 26 * 3600                # the provider allows up to 24 h; a little slack, then the job is failed visibly
TENTATIVE = "tentative:"              # external handle prefix while recovery observes candidate batches whose identity is unproven


# ------------------------------------------------------------------ the external handler (jobs.EXTERNAL[PROVIDER])

class AnthropicBatch:
    """External-system adapter for the Message Batches API, shaped like jobs.FakeExternal: submit / find_by_ref / check / cancel."""
    name = PROVIDER

    @staticmethod
    def _client() -> Any:
        from . import providers
        return providers.anthropic_client()

    @classmethod
    def submit(cls, kind: str, client_ref: str, request: dict[str, Any]) -> str:
        """request = {"job_id", "cohort_no"}: the items are read from batch_items (frozen params), one ledger row each,
        then ONE provider batch. The handle is the provider batch id."""
        from . import jobs
        job_id, cohort_no = request["job_id"], int(request["cohort_no"])
        items = db.batch_items(job_id, cohort_no, status="planned")
        if not items:
            raise RuntimeError("nothing to submit: no planned items in this cohort")
        jid, run_id = jobs.current_job()
        invs: dict[str, str] = {}
        for it in items:
            invs[it["custom_id"]] = db.invocation_start(PROVIDER, it["task"], str(it["params"].get("model") or ""), it["custom_id"], jid, run_id)
        requests = [{"custom_id": it["custom_id"], "params": it["params"]} for it in items]
        client = cls._client()
        extra = {"_client_ref": client_ref} if settings.fake_ai else {}
        intent = json.loads(db.kv_get(f"batch:intent:{client_ref}") or "{}")
        db.kv_set(f"batch:intent:{client_ref}", json.dumps({**intent, "attempted": True, "ts": min(intent.get("ts") or time.time(), time.time())}))
        batch = client.messages.batches.create(requests=requests, **extra)
        jobs.crash_point("batch_after_create_before_persist")
        db.batch_items_submitted(job_id, cohort_no, batch.id, invs)
        db.kv_set(f"batch:intent:{client_ref}", None)
        log.info("batch %s submitted: %d items (cohort %d of job %s)", batch.id, len(items), cohort_no, job_id[:8])
        return batch.id

    @classmethod
    def find_by_ref(cls, client_ref: str) -> str | None:
        """Recovery after a crash between the provider accepting the batch and us persisting its id.
        The fake keeps our reference exactly. The real API has no client reference, so identity can only be PROVEN by
        the returned custom_id set — which exists once a batch has ended. Until then a plausible batch (unknown to our
        table, created after our recorded intent, same request count) is a tentative CANDIDATE: observed, never
        cancelled, mutated or attributed. `check()` on the tentative handle verifies each ended candidate's custom_id
        set, adopts an exact match, rejects the rest; when none is left the job resubmits."""
        client = cls._client()
        intent = db.kv_get(f"batch:intent:{client_ref}")
        if not intent:
            return None
        meta = json.loads(intent)
        if not meta.get("attempted"):                                  # we never reached the provider: nothing to find
            return None
        if settings.fake_ai and not os.environ.get("NEUROSEARCH_FAKE_BATCH_NO_CLIENT_REF"):
            found = client.messages.batches.find_by_ref(client_ref)
            if found:
                cls._attach(meta, found, where="client_ref")
            return found
        known = {r["batch_id"] for r in db.connect().execute("SELECT DISTINCT batch_id FROM batch_items WHERE batch_id IS NOT NULL").fetchall()}
        rejected = set(json.loads(db.kv_get(f"batch:rejected:{client_ref}") or "[]"))
        try:
            page = client.messages.batches.list(limit=20)
        except Exception as e:  # noqa: BLE001
            log.warning("batch list failed during recovery: %s", e)
            return None
        candidates = []
        for b in getattr(page, "data", []) or []:
            created = getattr(b, "created_at", None)
            ts = created.timestamp() if hasattr(created, "timestamp") else float(created or 0)
            counts = getattr(b, "request_counts", None)
            total = sum(int(getattr(counts, k, 0) or 0) for k in ("processing", "succeeded", "errored", "canceled", "expired")) if counts else None
            if b.id not in known and b.id not in rejected and ts >= meta["ts"] - 5 and total == meta["n"]:
                candidates.append(b.id)
        job_id = meta["job_id"]
        if not candidates:
            db.job_event(job_id, "external_recovery_no_candidate", provider=PROVIDER, client_ref=client_ref, rejected=sorted(rejected))
            return None
        db.kv_set(f"batch:candidates:{client_ref}", json.dumps(candidates))
        db.job_event(job_id, "external_candidates", provider=PROVIDER, client_ref=client_ref, candidates=candidates, n=len(candidates),
                     detail="created after our intent with our request count — tentative until the returned custom_id set is verified")
        return TENTATIVE + client_ref

    @classmethod
    def _check_tentative(cls, client_ref: str) -> tuple[str, Any]:
        """Observe the candidates; adopt the one whose ended results carry EXACTLY our custom_id set; reject the others."""
        client = cls._client()
        meta = json.loads(db.kv_get(f"batch:intent:{client_ref}") or "{}")
        candidates = json.loads(db.kv_get(f"batch:candidates:{client_ref}") or "[]")
        rejected = json.loads(db.kv_get(f"batch:rejected:{client_ref}") or "[]")
        job_id, cohort_no = meta.get("job_id"), int(meta.get("cohort_no") or 0)
        expected = {it["custom_id"] for it in db.batch_items(job_id, cohort_no, status="planned")}
        for bid in list(candidates):
            b = client.messages.batches.retrieve(bid)
            if getattr(b, "processing_status", None) != "ended":
                continue
            got = list(client.messages.batches.results(bid))        # read-only; the provider keeps the results either way
            ids = {r.custom_id for r in got}
            if ids == expected and expected:
                cls._attach(meta, bid, where="verified_custom_ids")
                counts = cls.persist_results(bid, results=got)
                db.kv_set(f"batch:candidates:{client_ref}", None)
                return "done", {"batch_id": bid, "counts": counts, "cancelled": bool(getattr(b, "cancel_initiated_at", None))}
            rejected.append(bid)
            candidates.remove(bid)
            db.kv_set(f"batch:rejected:{client_ref}", json.dumps(rejected))
            db.kv_set(f"batch:candidates:{client_ref}", json.dumps(candidates))
            db.job_event(job_id, "external_candidate_rejected", provider=PROVIDER, handle=bid, expected=len(expected), returned=len(ids),
                         overlap=len(ids & expected), detail="returned custom_id set differs from ours — not our batch")
        if candidates:
            return "pending", None
        db.kv_set(f"batch:candidates:{client_ref}", None)
        db.unpark_external(job_id, "every tentative candidate was rejected by custom_id verification")
        return "pending", None

    @classmethod
    def _attach(cls, meta: dict[str, Any], batch_id: str, *, where: str) -> None:
        """Bind a provider batch to the cohort whose id was never persisted: ledger rows for the planned items, batch id
        on every item, intent cleared. Only called with a proven identity (fake client_ref, or verified custom_id set)."""
        job_id, cohort_no = meta["job_id"], int(meta["cohort_no"])
        planned = db.batch_items(job_id, cohort_no, status="planned")
        if not planned:
            return
        invs = {it["custom_id"]: it.get("invocation_id") or db.invocation_start(PROVIDER, it["task"], str(it["params"].get("model") or ""), it["custom_id"], job_id, None)
                for it in planned}
        db.batch_items_submitted(job_id, cohort_no, batch_id, invs)
        db.kv_set(f"batch:intent:{job_id}#{cohort_no}", None)
        db.job_event(job_id, "external_reattached", provider=PROVIDER, handle=batch_id, where=where,
                     detail="returned custom_id set matched ours exactly" if where == "verified_custom_ids" else "provider kept our client reference")

    @classmethod
    def check(cls, handle: str) -> tuple[str, Any]:
        """('pending'|'done'|'failed', result). On 'ended' every item result is persisted locally BEFORE we report done."""
        if handle.startswith(TENTATIVE):
            return cls._check_tentative(handle[len(TENTATIVE):])
        client = cls._client()
        b = client.messages.batches.retrieve(handle)
        status = getattr(b, "processing_status", None)
        if status != "ended":
            # Kyle, live: "the background processes says they will take several hours but I never know if something
            # is actually happening." The provider reports live per-request counts on every one of these polls and
            # we were discarding them, so the panel showed a static "up to 24 hours; 0/N ready" for hours. Record
            # them for ui_state: real progress from the provider, never an invented bar.
            c = getattr(b, "request_counts", None)
            if c is not None:
                got = {k: int(getattr(c, k, 0) or 0) for k in ("processing", "succeeded", "errored", "canceled", "expired")}
                db.kv_set(f"batch:progress:{handle}", json.dumps({**got, "ts": time.time()}))
            return "pending", None
        counts = cls.persist_results(handle)
        return "done", {"batch_id": handle, "counts": counts, "cancelled": bool(getattr(b, "cancel_initiated_at", None))}

    @classmethod
    def persist_results(cls, batch_id: str, results: list[Any] | None = None) -> dict[str, int]:
        """Read the provider's results once (or use `results` already read) and write each item's raw result + outcome
        to batch_items. Idempotent."""
        client = cls._client()
        items = {it["custom_id"]: it for it in db.batch_items_for_batch(batch_id)}
        counts = {"succeeded": 0, "errored": 0, "expired": 0, "canceled": 0, "unknown_custom_id": 0}
        seen: set[str] = set()
        for r in (results if results is not None else client.messages.batches.results(batch_id)):
            cid = r.custom_id
            it = items.get(cid)
            if not it:
                counts["unknown_custom_id"] += 1          # a heuristically re-attached batch that was not ours
                continue
            seen.add(cid)
            rtype = getattr(r.result, "type", None)
            if rtype == "succeeded":
                msg = r.result.message
                raw = _message_to_dict(msg)
                db.batch_item_result(batch_id, cid, "succeeded", raw=raw)
                if it.get("invocation_id"):
                    db.invocation_finish(it["invocation_id"], "completed", provider_request_id=batch_id, returned_model=str(getattr(msg, "model", "") or "") or None)
                counts["succeeded"] += 1
            else:
                err = getattr(getattr(r.result, "error", None), "message", None) or rtype
                st = rtype if rtype in ("errored", "expired", "canceled") else "errored"
                db.batch_item_result(batch_id, cid, st, error=str(err)[:300])
                if it.get("invocation_id"):
                    db.invocation_finish(it["invocation_id"], "failed", error=str(err)[:300], error_type="BATCH_" + st.upper())
                counts[st] += 1
        for cid, it in items.items():                    # an item the provider never reported: treat as errored, visibly
            if cid not in seen and it["status"] == "submitted":
                db.batch_item_result(batch_id, cid, "errored", error="no result returned for this custom_id")
                counts["errored"] += 1
        if counts["unknown_custom_id"]:
            log.error("batch %s returned %d results with custom_ids we never submitted — re-attachment was wrong", batch_id, counts["unknown_custom_id"])
        return counts

    @classmethod
    def cancel(cls, handle: str) -> bool:
        client = cls._client()
        try:
            client.messages.batches.cancel(handle)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("batch cancel failed for %s: %s", handle, e)
            return False


def _message_to_dict(msg: Any) -> dict[str, Any]:
    def conv(x: Any) -> Any:
        if hasattr(x, "model_dump"):
            return x.model_dump()
        if hasattr(x, "__dict__") and not isinstance(x, type):
            return {k: conv(v) for k, v in vars(x).items() if not k.startswith("_")}
        if isinstance(x, list):
            return [conv(i) for i in x]
        if isinstance(x, dict):
            return {k: conv(v) for k, v in x.items()}
        return x
    return conv(msg)


class _Msg:
    """A persisted batch result re-hydrated into the interactive response shape (content blocks with .type/.text, .usage, .stop_reason, .model)."""

    def __init__(self, d: dict[str, Any]) -> None:
        self.stop_reason = d.get("stop_reason")
        self.model = d.get("model")
        self.id = d.get("id")
        self.content = [type("B", (), b)() for b in (d.get("content") or [])]
        u = d.get("usage") or {}
        self.usage = type("U", (), u)() if u else None


# ------------------------------------------------------------------ planning a cohort

def plan_items(project_id: str, source_ids: list[str] | None = None, force: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    """Logical work items for the sources that need findings (or all given ones with force). Returns (items, skipped_source_ids)."""
    from . import findings
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    ids = source_ids or db.sources_needing_suggestions(project_id)
    items: list[dict[str, Any]] = []
    skipped: list[str] = []
    for sid in ids:
        if not force and findings.is_current(project, sid):
            skipped.append(sid)
            continue
        reqs = findings.batch_requests(project_id, sid)
        if not reqs:
            skipped.append(sid)
            continue
        items += reqs
    return items, skipped


BULK_THRESHOLD_ITEMS = int(os.environ.get("NEUROSEARCH_BATCH_BULK_THRESHOLD", "6"))   # ≥ this many findings windows: background is recommended
MAX_COUNT_CALLS = int(os.environ.get("NEUROSEARCH_BATCH_MAX_COUNT_CALLS", "12"))       # token-count calls per estimate before falling back to chars
OUT_TOKENS_PER_WINDOW = 600                                                             # same assumption as usage.estimate_findings

CHOICES = {
    "now": {"label": "Analyze now", "detail": "Faster · standard model cost"},
    "background": {"label": "Analyze in background", "detail": "Up to 24 hours · ~50% lower model cost"},
}


def _count_input_tokens(items: list[dict[str, Any]]) -> tuple[dict[str, int], str]:
    """Exact input tokens per item from the provider's token-counting endpoint, cached by custom_id (which embeds the
    input hash, so a cached count is exact until the inputs change). At most MAX_COUNT_CALLS uncached calls per
    estimate so a modal never waits on dozens of round-trips; the rest fall back to the character estimate.
    Returns ({custom_id: tokens}, basis) with basis 'token count' | 'mixed' | 'estimate'."""
    from . import providers
    counts: dict[str, int] = {}
    todo = []
    for it in items:
        cached = db.kv_get("tokcount:" + it["custom_id"])
        if cached is not None:
            counts[it["custom_id"]] = int(cached)
        else:
            todo.append(it)
    calls = 0
    if todo and providers.anthropic_available():
        try:
            client = providers.anthropic_client()
            for it in todo[:MAX_COUNT_CALLS]:
                p = it["params"]
                strip = [{k: v for k, v in b.items() if k != "cache_control"} for b in p["system"]] if isinstance(p["system"], list) else p["system"]
                fmt = {"output_config": p["output_config"]} if p.get("output_config") else {}
                n = int(client.messages.count_tokens(model=p["model"], system=strip, messages=p["messages"], **fmt).input_tokens)
                db.kv_set("tokcount:" + it["custom_id"], str(n))
                counts[it["custom_id"]] = n
                calls += 1
        except Exception as e:  # noqa: BLE001
            log.info("token counting unavailable for the estimate (%s); using the character estimate", e)
    basis = "token count" if len(counts) == len(items) and items else ("mixed" if counts else "estimate")
    return counts, basis


def estimate(project_id: str, source_ids: list[str] | None = None, force: bool = False, exact: bool = True) -> dict[str, Any]:
    """Cost quote for the choice 'analyze now' vs 'analyze in background'. Model cost only; background = BATCH_MULT.
    Input tokens come from the provider's token counter when practical (exact=True, cached), else ~4 chars/token."""
    from . import usage
    from .contracts import contract
    items, skipped = plan_items(project_id, source_ids, force=force)
    chars = sum(len(it["params"]["messages"][0]["content"]) for it in items)
    counts, basis = _count_input_tokens(items) if exact and items else ({}, "estimate")
    pin, pout = usage._price(contract("findings.extract").model)
    now_cost = 0.0
    for it in items:
        cid = it["custom_id"]
        if cid in counts:
            now_cost += counts[cid] / 1e6 * pin + OUT_TOKENS_PER_WINDOW / 1e6 * pout
        else:
            now_cost += usage.estimate_findings(len(it["params"]["messages"][0]["content"]))
    bg = now_cost * usage.BATCH_MULT
    recommended = "background" if len(items) >= BULK_THRESHOLD_ITEMS else "now"
    return {"items": len(items), "sources": len({it["source_id"] for it in items}), "skipped_current": len(skipped), "chars": chars,
            "input_tokens": sum(counts.values()) if basis == "token count" else None, "basis": basis,
            "now": round(now_cost, 4), "background": round(bg, 4), "discount": usage.BATCH_MULT,
            "recommended": recommended, "bulk_threshold_items": BULK_THRESHOLD_ITEMS, "choices": CHOICES,
            "note": "model cost only (the batch discount applies to model tokens, not to transcription, embeddings or web search); batches may take up to 24 hours"}


def ui_state(job: dict[str, Any]) -> dict[str, Any]:
    """What the user sees for a background analysis job: phase + a plain sentence. queued/submitting → processing →
    materializing → complete, with partial failure / canceled / expired named explicitly. No provider jargon."""
    st, handle = job.get("status"), str(job.get("external_handle") or "")
    items = db.batch_items(job["id"])
    by = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
    sources = {it["source_id"] for it in items}
    done = {it["source_id"] for it in items if it["status"] == "materialized"}
    cohort = max((it["cohort_no"] for it in items), default=0)
    retrying = sum(1 for it in items if it["cohort_no"] == cohort and it["status"] in ("planned", "submitted")) if cohort > 1 else 0
    n_src = len(sources) or len((job.get("payload") or {}).get("source_ids") or [])
    if st == "queued" and (job.get("payload") or {}).get("_external_result"):
        phase, label = "materializing", f"results received — writing findings ({len(done)}/{n_src} sources ready)"
    elif st == "queued":
        phase, label = "queued", f"queued for background analysis ({n_src} source{'s' if n_src != 1 else ''})"
    elif st == "running" and not by.get("submitted") and not (job.get("payload") or {}).get("_external_result"):
        phase, label = "submitting", "submitting to the background queue"
    elif st == "running":
        phase, label = "materializing", f"writing findings ({len(done)}/{n_src} sources ready)"
    elif st == "external_pending" and handle.startswith(TENTATIVE):
        phase, label = "verifying", "verifying which provider batch is ours before adopting any results"
    elif st == "external_pending":
        phase = "processing"
        prog = {}
        try:
            prog = json.loads(db.kv_get(f"batch:progress:{handle}") or "{}")
        except ValueError:
            prog = {}
        finished = sum(int(prog.get(k, 0)) for k in ("succeeded", "errored", "canceled", "expired"))
        total = finished + int(prog.get("processing", 0))
        if total:
            mins = max(0, int((time.time() - float(prog.get("ts") or 0)) // 60))
            checked = "just now" if mins < 1 else f"{mins} min ago"
            return {"phase": phase, "label": f"{finished} of {total} request{'' if total == 1 else 's'} done at the provider "
                                             f"· checked {checked} · {len(done)}/{n_src} source{'' if n_src == 1 else 's'} written",
                    "done": len(done), "sources": n_src, "counts": by, "provider_done": finished, "provider_total": total}
        label = f"processing in background — up to 24 hours; {len(done)}/{n_src} sources ready" + (f" · retrying {retrying} item{'s' if retrying != 1 else ''} (round {cohort})" if retrying else "")
    elif st == "done":
        phase, label = "complete", f"complete — {len(done)}/{n_src} sources analysed"
    elif st == "failed":
        phase = "partial_failure" if done else "failed"
        bad = {k: v for k, v in by.items() if k in ("errored", "expired", "canceled")}
        label = (f"{len(done)}/{n_src} sources analysed; " if done else "") + (", ".join(f"{v} {k}" for k, v in bad.items()) or "failed")
    elif st == "cancelled":
        phase, label = "canceled", f"canceled — {len(done)} source{'s' if len(done) != 1 else ''} with complete results kept"
    else:
        phase, label = st or "unknown", st or ""
    return {"phase": phase, "label": label, "sources": n_src, "done": len(done), "by_status": by, "cohort": cohort, "retrying": retrying}


# ------------------------------------------------------------------ the job

def run(job_id: str, payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    """Job body for suggest_findings_batch. First run: plan + submit cohort 1 (parks). Each later run: the batch ended —
    materialize what succeeded, resubmit only what failed (parks again) or finish."""
    from . import jobs
    pid = payload["project_id"]
    result = payload.get("_external_result")
    cohort_no = int(payload.get("_cohort_no") or 1)
    if not result:
        existing = db.batch_items(job_id, cohort_no)
        if not existing:                                                    # first run: plan (idempotent on retry: items are keyed)
            items, skipped = plan_items(pid, payload.get("source_ids"), force=bool(payload.get("force")))
            if not items:
                return {"sources": 0, "items": 0, "skipped_current": len(skipped), "note": "nothing to analyse"}
            db.batch_items_add(job_id, 1, items)
            db.job_event(job_id, "batch_planned", cohort_no=1, items=len(items), sources=len({i["source_id"] for i in items}), skipped_current=len(skipped))
        _submit_cohort(job_id, cohort_no)                                    # raises ExternalPending
    # ---- a cohort ended: its results are already persisted locally (AnthropicBatch.check did that before reporting done)
    batch_id = result["batch_id"]
    jobs.crash_point("batch_results_persisted_before_materialize")
    out = materialize_ready(job_id, pid)
    failed = [it for it in db.batch_items(job_id, cohort_no) if it["status"] in ("errored", "expired", "canceled")]
    db.job_event(job_id, "batch_ended", cohort_no=cohort_no, batch_id=batch_id, counts=result.get("counts"), materialized_sources=out["materialized"], failed_items=len(failed))
    if failed and not result.get("cancelled"):
        if cohort_no >= MAX_COHORTS:
            raise RuntimeError(f"{len(failed)} findings window(s) still failed after {cohort_no} batch cohorts: "
                               + "; ".join(f"{it['source_id'][:8]} window {it['window_index'] + 1}/{it['windows']}: {it['error']}" for it in failed[:6]))
        # next cohort: ONLY the failed logical items, same custom_ids, same frozen params
        db.batch_items_add(job_id, cohort_no + 1, [{"custom_id": it["custom_id"], "task": it["task"], "project_id": it["project_id"], "source_id": it["source_id"],
                                                    "window_index": it["window_index"], "windows": it["windows"], "params": it["params"]} for it in failed])
        db.job_event(job_id, "batch_retry_planned", cohort_no=cohort_no + 1, items=len(failed), custom_ids=[it["custom_id"] for it in failed])
        _set_cohort(job_id, cohort_no + 1)
        _submit_cohort(job_id, cohort_no + 1)                                # parks again
    summary = cohort_summary(job_id)
    if failed and result.get("cancelled"):
        summary["note"] = f"cancelled at the provider; {out['materialized']} source(s) with complete results were kept, {len(failed)} window(s) not completed"
    return summary


def _set_cohort(job_id: str, cohort_no: int) -> None:
    with db.tx() as conn:
        r = conn.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        pl = json.loads(r["payload"] or "{}") if r else {}
        pl["_cohort_no"] = cohort_no
        pl.pop("_external_result", None)
        conn.execute("UPDATE jobs SET payload=?, updated_at=? WHERE id=?", (json.dumps(pl), db.now(), job_id))


def _submit_cohort(job_id: str, cohort_no: int) -> None:
    from . import jobs, usage
    items = db.batch_items(job_id, cohort_no, status="planned")
    chars = sum(len(it["params"]["messages"][0]["content"]) for it in items)
    usage.guard(usage.estimate_findings(chars, batch=True))
    client_ref = f"{job_id}#{cohort_no}"
    if not db.kv_get(f"batch:intent:{client_ref}"):                  # a surviving intent (with its 'attempted' mark) is the recovery evidence — keep it
        db.kv_set(f"batch:intent:{client_ref}", json.dumps({"job_id": job_id, "cohort_no": cohort_no, "n": len(items), "ts": time.time()}))
    jobs.submit_external(PROVIDER, "findings", {"job_id": job_id, "cohort_no": cohort_no}, deadline=time.time() + DEADLINE_S, client_ref=client_ref)


def _prefilter_summary(project_id: str, source_id: str) -> dict[str, Any] | None:
    """The pre-filter's provenance for a source materialised from a batch: the latest decision per window."""
    from . import prefilter
    rows = db.window_decisions(project_id, source_id)
    latest: dict[int, dict[str, Any]] = {}
    for r in rows:
        latest[r["window_index"]] = r
    return prefilter.summary([latest[i] for i in sorted(latest)]) if latest else None


def materialize_ready(job_id: str, project_id: str) -> dict[str, Any]:
    """For every source whose windows ALL succeeded (across cohorts): validate each persisted result exactly like the
    interactive path (structured → full schema; quote validator inside materialize) and store the artifact once."""
    from . import findings, providers, usage
    by_source: dict[str, dict[int, dict[str, Any]]] = {}
    for it in db.batch_items(job_id):
        if it["status"] in ("succeeded", "materialized"):
            by_source.setdefault(it["source_id"], {})[it["window_index"]] = it
    materialized = 0
    details = []
    for sid, wins in by_source.items():
        n = next(iter(wins.values()))["windows"]
        if len(wins) < n or all(it["status"] == "materialized" for it in wins.values()):
            continue
        results: list[tuple[str, dict[str, Any]]] = []
        model = None
        batch_ids: set[str] = set()
        for i in sorted(wins):                            # window indexes are the source's own (a pre-filter may have dropped some)
            it = wins[i]
            msg = _Msg(it["raw"])
            # 0.62.3: dated when the provider's result arrived, not when we got round to materialising it. Kyle's
            # recovery of 410 stranded batches booked $23.18 of Sep-9 spend into a 23-minute window on Sep 10 and
            # tripped the spend-rate ceiling on money that was already gone.
            usage.record_anthropic(msg, "findings", project_id=project_id, source_id=sid, transport="batch",
                                   ts=it.get("result_at") or None)
            parsed = providers.structured("findings.extract", msg)                     # same strict path: typed on truncation/refusal/mismatch
            results.append((window_text(it["params"]), parsed))
            model = getattr(msg, "model", None) or model
            batch_ids.add(it["batch_id"])
        pf = _prefilter_summary(project_id, sid)
        r = findings.materialize(project_id, sid, results, model=model, transport="batch", batch_id=",".join(sorted(batch_ids)), prefilter=pf)
        db.batch_items_materialized(job_id, sid)
        materialized += 1
        details.append({"source_id": sid, "suggested": r["suggested"], "rejected_quotes": r["rejected_quotes"], "windows": n})
    return {"materialized": materialized, "details": details}


def window_text(params: dict[str, Any]) -> str:
    """The transcript window back out of the frozen request (findings._user wraps it in a fixed frame)."""
    content = params["messages"][0]["content"]
    return content.split("\n", 1)[1].rsplit("\n\nExtract the findings now.", 1)[0]


def cohort_summary(job_id: str) -> dict[str, Any]:
    items = db.batch_items(job_id)
    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    sources = {it["source_id"] for it in items}
    done_sources = {it["source_id"] for it in items if it["status"] == "materialized"}
    usage_rows = db.connect().execute("SELECT SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read) cr, SUM(cache_write) cw, SUM(cost) c, SUM(saved) s, COUNT(*) n "
                                      "FROM usage WHERE transport='batch' AND kind='findings' AND source_id IN (%s)" % ",".join("?" * max(1, len(sources))),
                                      tuple(sources) or ("",)).fetchone()
    return {"sources": len(sources), "done": len(done_sources), "failed": len(sources - done_sources), "items": len(items), "by_status": by_status,
            "cohorts": max((it["cohort_no"] for it in items), default=0),
            "batch": {"input_tokens": int(usage_rows["i"] or 0), "output_tokens": int(usage_rows["o"] or 0), "cache_read": int(usage_rows["cr"] or 0),
                      "cache_write": int(usage_rows["cw"] or 0), "cost": round(float(usage_rows["c"] or 0), 6), "saved_vs_interactive_full_price": round(float(usage_rows["s"] or 0), 6),
                      "model_calls": int(usage_rows["n"] or 0)}}


# ------------------------------------------------------------------ the path back from a cancelled batch (0.60.3)
#
# Measured on Kyle's own data while auditing the 432 `outcome_unknown` invocations: ONE job
# (`suggest_findings_batch`, handle msgbatch_01F8ZLA…, 2026-09-08) accounts for 426 of them. It was submitted, then
# cancelled locally 11.7 hours later, and its 426 `batch_items` are STILL at status `submitted` two days on.
#
# `cancel_job` does the right things in the right order — cancel at the provider, wait, persist, materialise — but
# it waits one second for the batch to end and then gives up inside a try/except. An eleven-hour-old batch does not
# end within a second of a cancel, so the harvest failed, the warning went to the log, and there was no way back.
# Anthropic bills the requests that completed before the cancellation landed, so this is both a money leak and a
# LOST-WORK leak: findings that were paid for and never written.
#
# The rule this restores is one the codebase already states about account gates: never leave a state with no path
# back. `unsettled()` finds these durably (derived, so it cannot go stale), and `settle()` is the path — retrieve,
# persist whatever succeeded, materialise it into the project it was always for, and mark the rest with a reason so
# nothing sits at "submitted" for ever. It is idempotent and free: retrieving a batch costs nothing.
def unsettled() -> list[dict[str, Any]]:
    """Finished jobs whose provider batch has work that was paid for and never written.

    TWO states, not one (0.61.1). `submitted` means nobody has collected the result yet. `succeeded` means the
    result was collected and the finding was still never written — which happens when a source's OTHER windows were
    cancelled, because `materialize_ready` only writes a source whose every window came back. Kyle's abandoned
    batch settled into exactly that shape: of 426 requests, 410 succeeded, 331 were written, **79 are still sitting
    there collected and unwritten**, and 15 were cancelled at the provider. Counting only `submitted` declared that
    batch finished while 79 paid-for results had gone nowhere."""
    rows = db.connect().execute(
        "SELECT j.id, j.kind, j.status, j.external_handle, j.payload, j.finished_at, "
        "       SUM(CASE WHEN b.status='submitted' THEN 1 ELSE 0 END) awaiting_collection, "
        "       SUM(CASE WHEN b.status='succeeded' THEN 1 ELSE 0 END) collected_not_written, "
        "       COUNT(b.id) items "
        "FROM jobs j JOIN batch_items b ON b.job_id = j.id "
        "WHERE j.status IN ('cancelled','failed','done') AND b.status IN ('submitted','succeeded') "
        "AND j.external_handle IS NOT NULL GROUP BY j.id ORDER BY j.finished_at DESC").fetchall()
    out = []
    for r in rows:
        handle = str(r["external_handle"] or "")
        if handle.startswith(TENTATIVE):
            continue                       # identity unproven: never touch candidates that may not be ours
        try:
            pl = json.loads(r["payload"] or "{}")
        except ValueError:
            pl = {}
        prog = db.kv_get(f"batch:progress:{handle}")
        out.append({"job_id": r["id"], "kind": r["kind"], "status": r["status"], "handle": handle,
                    "project_id": pl.get("project_id"), "items": int(r["items"]),
                    "awaiting_collection": int(r["awaiting_collection"] or 0),
                    "collected_not_written": int(r["collected_not_written"] or 0),
                    "finished_at": r["finished_at"],
                    "last_seen_counts": json.loads(prog) if prog else None})
    return out


def stuck_sources(job_id: str) -> list[dict[str, Any]]:
    """Sources in this batch whose results cannot be assembled: some window succeeded and another did not.

    `materialize_ready` is right to refuse them — half a source's windows is not a reading of the source — but the
    refusal was silent, so the paid-for half simply vanished from view. Naming them is what lets someone decide:
    re-read the source (it costs again) or accept the partial (a separate decision, not this function's)."""
    rows = db.connect().execute(
        "SELECT source_id, "
        "       SUM(status='succeeded') ok, SUM(status='materialized') done, "
        "       SUM(status IN ('canceled','errored','expired')) lost, COUNT(*) windows "
        "FROM batch_items WHERE job_id=? GROUP BY source_id", (job_id,)).fetchall()
    out = []
    for r in rows:
        if int(r["ok"] or 0) and int(r["lost"] or 0):
            out.append({"source_id": r["source_id"], "collected": int(r["ok"]), "lost": int(r["lost"]),
                        "windows": int(r["windows"]),
                        "why": (f"{r['ok']} of {r['windows']} windows came back and {r['lost']} did not, so the "
                                "source cannot be assembled from this batch")})
    return out


def settle(job_id: str) -> dict[str, Any]:
    """Collect what a cancelled or failed batch actually produced. Free, idempotent, and safe to run at any time.

    Materialising into a cancelled job's project is deliberate: the requests were paid for and the findings belong
    to the source, whatever happened to the job that asked for them. Cancelling the job stopped the *spending*, not
    the ownership of work already done."""
    job = db.get_job(job_id)
    if not job:
        return {"settled": False, "why": "no such job"}
    handle = str(job.get("external_handle") or "")
    if not handle or handle.startswith(TENTATIVE):
        return {"settled": False, "why": "this job has no proven provider batch"}
    project_id = (job.get("payload") or {}).get("project_id")
    try:
        b = AnthropicBatch._client().messages.batches.retrieve(handle)
    except Exception as e:  # noqa: BLE001
        # the handle is gone (batches expire): stop the items pretending to be in flight, with the reason on each
        n = db.batch_items_mark_unsettled(handle, f"the provider no longer has this batch: {str(e)[:120]}")
        db.job_event(job_id, "batch_settled", handle=handle, gone=True, items=n)
        return {"settled": True, "gone": True, "items": n,
                "note": "the provider no longer has this batch, so nothing can be recovered from it"}
    counts = getattr(b, "request_counts", None)
    seen = {k: int(getattr(counts, k, 0) or 0) for k in ("processing", "succeeded", "errored", "canceled", "expired")} if counts else {}
    if getattr(b, "processing_status", None) != "ended":
        db.kv_set(f"batch:progress:{handle}", json.dumps({**seen, "ts": time.time()}))
        return {"settled": False, "still_processing": True, "counts": seen,
                "note": "the provider is still working through this batch — come back and settle it later"}
    got = AnthropicBatch.persist_results(handle)
    # The event is written BEFORE materialising (0.61.1). The first live settle collected 410 results and wrote 331
    # sources' findings, then something raised inside materialisation — so the whole outcome went into an exception
    # handler and `job_events` recorded nothing at all. Collecting is the irreversible half; it gets its own line
    # in the log whatever happens next.
    db.job_event(job_id, "batch_settled", handle=handle, counts=got, provider_counts=seen)
    harvested: dict[str, Any] = {"materialized": 0}
    error = None
    try:
        if project_id:
            harvested = materialize_ready(job_id, project_id)
    except Exception as e:  # noqa: BLE001 — the results are already saved; writing them is a separate step
        error = str(e)[:200]
        log.warning("settle %s: results collected but materialisation failed: %s", handle, e)
    stuck = stuck_sources(job_id)
    db.job_event(job_id, "batch_materialised", handle=handle, materialized=harvested.get("materialized", 0),
                 stuck=len(stuck), error=error)
    note = (f"{got.get('succeeded', 0)} request(s) had completed and were collected; "
            f"{harvested.get('materialized', 0)} source(s) gained their findings")
    if stuck:
        note += (f"; {len(stuck)} source(s) cannot be assembled because some of their windows were cancelled at "
                 "the provider — re-read those sources if you want them")
    if error:
        note += f"; writing them raised: {error}"
    return {"settled": True, "counts": got, "provider_counts": seen,
            "materialized": harvested.get("materialized", 0), "stuck": stuck, "error": error, "note": note}


def settle_all(limit: int = 10) -> dict[str, Any]:
    out = []
    for u in unsettled()[:limit]:
        try:
            out.append({"job_id": u["job_id"], **settle(u["job_id"])})
        except Exception as e:  # noqa: BLE001
            out.append({"job_id": u["job_id"], "settled": False, "why": str(e)[:160]})
    return {"attempted": len(out), "results": out,
            "materialized": sum(int(r.get("materialized") or 0) for r in out)}


def cancel_job(job: dict[str, Any]) -> dict[str, Any]:
    """Cancel a parked batch job: tell the provider, then harvest whatever already completed (persist + materialize the
    sources whose windows all succeeded) before the job is marked cancelled. Completed valid results are never destroyed."""
    handle = job.get("external_handle")
    harvested: dict[str, Any] = {"materialized": 0}
    if handle and handle.startswith(TENTATIVE):
        # identity unproven: the candidates may belong to someone else — observe only, never cancel or mutate them
        db.job_event(job["id"], "batch_cancelled", handle=handle, materialized_after_cancel=0, detail="tentative candidates left untouched (identity unproven)")
        return harvested
    if handle:
        AnthropicBatch.cancel(handle)
        try:
            for _ in range(5):                       # the provider needs a moment to end the batch after a cancel
                b = AnthropicBatch._client().messages.batches.retrieve(handle)
                if getattr(b, "processing_status", None) == "ended":
                    break
                time.sleep(0.2)
            AnthropicBatch.persist_results(handle)
            harvested = materialize_ready(job["id"], (job.get("payload") or {}).get("project_id"))
        except Exception as e:  # noqa: BLE001
            # 0.60.3: this is where 426 items were abandoned. The failure is expected — a batch does not end within
            # a second of being cancelled — so it is no longer the end of the story: `unsettled()` will list this
            # job until someone settles it, and Health says so.
            log.warning("harvest after cancel failed for %s (left for settling): %s", handle, e)
            harvested["unsettled"] = True
    db.job_event(job["id"], "batch_cancelled", handle=handle, materialized_after_cancel=harvested.get("materialized", 0))
    return harvested
