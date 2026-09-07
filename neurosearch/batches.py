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
import time
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

PROVIDER = "anthropic_batch"
JOB_KIND = "suggest_findings_batch"
MAX_COHORTS = 3                       # a logical item is submitted at most this many times
DEADLINE_S = 26 * 3600                # the provider allows up to 24 h; a little slack, then the job is failed visibly


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
        batch = client.messages.batches.create(requests=requests, **extra)
        jobs.crash_point("batch_after_create_before_persist")
        db.batch_items_submitted(job_id, cohort_no, batch.id, invs)
        db.kv_set(f"batch:intent:{client_ref}", None)
        log.info("batch %s submitted: %d items (cohort %d of job %s)", batch.id, len(items), cohort_no, job_id[:8])
        return batch.id

    @classmethod
    def find_by_ref(cls, client_ref: str) -> str | None:
        """Recovery after a crash between the provider accepting the batch and us persisting its id. The fake keeps our
        reference exactly; the real API has no client reference, so: any batch our table already knows is not an
        orphan, and an unknown batch created after our recorded intent with exactly our item count is claimed
        (confirmed later by custom_id match when its results are read — a mismatch fails the job visibly)."""
        client = cls._client()
        intent = db.kv_get(f"batch:intent:{client_ref}")
        if not intent:
            return None
        meta = json.loads(intent)
        if settings.fake_ai:
            found = client.messages.batches.find_by_ref(client_ref)
            if found:
                cls._attach(meta, found, where="client_ref")
            return found
        known = {r["batch_id"] for r in db.connect().execute("SELECT DISTINCT batch_id FROM batch_items WHERE batch_id IS NOT NULL").fetchall()}
        try:
            page = client.messages.batches.list(limit=20)
        except Exception as e:  # noqa: BLE001
            log.warning("batch list failed during recovery: %s", e)
            return None
        for b in getattr(page, "data", []) or []:
            created = getattr(b, "created_at", None)
            ts = created.timestamp() if hasattr(created, "timestamp") else float(created or 0)
            counts = getattr(b, "request_counts", None)
            total = sum(int(getattr(counts, k, 0) or 0) for k in ("processing", "succeeded", "errored", "canceled", "expired")) if counts else None
            if b.id not in known and ts >= meta["ts"] - 5 and total == meta["n"]:
                cls._attach(meta, b.id, where="recovery_heuristic")
                return b.id
        return None

    @classmethod
    def _attach(cls, meta: dict[str, Any], batch_id: str, *, where: str) -> None:
        """Bind a provider batch found during recovery to the cohort whose id was never persisted: ledger rows for the
        planned items, batch id on every item, intent cleared. Idempotent for items already bound."""
        job_id, cohort_no = meta["job_id"], int(meta["cohort_no"])
        planned = db.batch_items(job_id, cohort_no, status="planned")
        if not planned:
            return
        invs = {it["custom_id"]: it.get("invocation_id") or db.invocation_start(PROVIDER, it["task"], str(it["params"].get("model") or ""), it["custom_id"], job_id, None)
                for it in planned}
        db.batch_items_submitted(job_id, cohort_no, batch_id, invs)
        db.kv_set(f"batch:intent:{job_id}#{cohort_no}", None)
        db.job_event(job_id, "external_reattached", provider=PROVIDER, handle=batch_id, where=where,
                     detail="created after intent, same item count; confirmed by custom_ids at result time" if where == "recovery_heuristic" else "provider kept our client reference")

    @classmethod
    def check(cls, handle: str) -> tuple[str, Any]:
        """('pending'|'done'|'failed', result). On 'ended' every item result is persisted locally BEFORE we report done."""
        client = cls._client()
        b = client.messages.batches.retrieve(handle)
        status = getattr(b, "processing_status", None)
        if status != "ended":
            return "pending", None
        counts = cls.persist_results(handle)
        return "done", {"batch_id": handle, "counts": counts, "cancelled": bool(getattr(b, "cancel_initiated_at", None))}

    @classmethod
    def persist_results(cls, batch_id: str) -> dict[str, int]:
        """Read the provider's results once and write each item's raw result + outcome to batch_items. Idempotent."""
        client = cls._client()
        items = {it["custom_id"]: it for it in db.batch_items_for_batch(batch_id)}
        counts = {"succeeded": 0, "errored": 0, "expired": 0, "canceled": 0, "unknown_custom_id": 0}
        seen: set[str] = set()
        for r in client.messages.batches.results(batch_id):
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


def estimate(project_id: str, source_ids: list[str] | None = None) -> dict[str, Any]:
    """Cost quote for the choice 'analyze now' vs 'analyze in background' — model cost only; batch = BATCH_MULT."""
    from . import usage
    items, skipped = plan_items(project_id, source_ids)
    chars = sum(len(it["params"]["messages"][0]["content"]) for it in items)
    now_cost = sum(usage.estimate_findings(len(it["params"]["messages"][0]["content"])) for it in items)
    return {"items": len(items), "sources": len({it["source_id"] for it in items}), "skipped_current": len(skipped), "chars": chars,
            "now": round(now_cost, 4), "background": round(now_cost * usage.BATCH_MULT, 4), "discount": usage.BATCH_MULT,
            "note": "model cost only (the batch discount applies to model tokens, not to transcription, embeddings or web search); batches may take up to 24 hours"}


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
    db.kv_set(f"batch:intent:{client_ref}", json.dumps({"job_id": job_id, "cohort_no": cohort_no, "n": len(items), "ts": time.time()}))
    jobs.submit_external(PROVIDER, "findings", {"job_id": job_id, "cohort_no": cohort_no}, deadline=time.time() + DEADLINE_S, client_ref=client_ref)


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
        for i in range(n):
            it = wins[i]
            msg = _Msg(it["raw"])
            usage.record_anthropic(msg, "findings", project_id=project_id, source_id=sid, transport="batch")
            parsed = providers.structured("findings.extract", msg)                     # same strict path: typed on truncation/refusal/mismatch
            results.append((window_text(it["params"]), parsed))
            model = getattr(msg, "model", None) or model
            batch_ids.add(it["batch_id"])
        r = findings.materialize(project_id, sid, results, model=model, transport="batch", batch_id=",".join(sorted(batch_ids)))
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


def cancel_job(job: dict[str, Any]) -> dict[str, Any]:
    """Cancel a parked batch job: tell the provider, then harvest whatever already completed (persist + materialize the
    sources whose windows all succeeded) before the job is marked cancelled. Completed valid results are never destroyed."""
    handle = job.get("external_handle")
    harvested: dict[str, Any] = {"materialized": 0}
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
            log.warning("harvest after cancel failed for %s: %s", handle, e)
    db.job_event(job["id"], "batch_cancelled", handle=handle, materialized_after_cancel=harvested.get("materialized", 0))
    return harvested
