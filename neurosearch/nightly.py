"""L-30 (EXECUTION-LADDER.md Stage 4, P2 E7 Nightly Refinery backend). One bounded, preflighted envelope per
calendar day (local time), off by default.

`settings.t4_nightly_budget` (default 0) is a TOTAL per-night dollar cap, not a per-project one: each active
project's `t4.execute(..., budget_usd=remaining, ...)` call is given whatever is left of the night's budget
after earlier projects' own estimates, walking it down exactly like `t4.execute`'s own per-source budget walk
does within one project. Applying the full nightly budget to every project would silently multiply an amount
Kyle explicitly authorized as a single ceiling -- the spend-discipline rule (never make a paid call without
current authorization) applies to the SUM across a night, not per project.

`settings.t4_nightly_hour` is a local hour (0-23); `due()` is true once local time has reached that hour AND
today's envelope hasn't already run -- never "at that hour exactly," matching L-20's host-honesty rule (this
product never claims a sleeping host will wake itself).

Never reopens current sources: `t4.execute`'s own selector already skips a source with a current analysis
(`findings.is_current`) before it ever reaches the budget walk -- nothing new needed here for that guarantee.

Each per-project record also carries a `snapshot_before` (L-31): a cheap `t1.coverage_view(pid, limit=0)` call
taken immediately before `t4.execute`, excluding the large per-chunk `chunks` list. This is the ONLY point in
the system where a real "before" state for the night's work exists to capture -- `delta.for_envelope()` (L-31)
reads it back to compute an honest coverage delta; without it, a delta computed only from tables mutated by the
run itself would not be a real before/after comparison, it would be a guess.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import db
from .config import settings

log = logging.getLogger("neurosearch.nightly")


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def due() -> bool:
    """False whenever t4_nightly_budget<=0 (off) or the local hour hasn't reached t4_nightly_hour yet, or
    today's envelope already ran (recorded in kv, checked here so callers never need their own idempotency)."""
    if settings.t4_nightly_budget <= 0:
        return False
    if time.localtime().tm_hour < settings.t4_nightly_hour:
        return False
    return db.kv_get(f"nightly:{_today_key()}") is None


def last_run() -> dict[str, Any] | None:
    raw = db.kv_get(f"nightly:{_today_key()}")
    return json.loads(raw) if raw else None


def run(force: bool = False) -> dict[str, Any]:
    """Run tonight's envelope once. `force=True` bypasses the due()/already-ran check (tests, or a manual
    "run it now" trigger) but NEVER the budget-off guard -- t4_nightly_budget<=0 always means "do nothing,"
    forced or not, since that is the explicit off switch."""
    from . import t4

    if settings.t4_nightly_budget <= 0:
        return {"ran": False, "reason": "t4_nightly_budget is 0 (off)"}
    key = _today_key()
    if not force and db.kv_get(f"nightly:{key}") is not None:
        return {"ran": False, "reason": f"already ran for {key}"}

    envelope_id = f"nightly-{key}"
    try:
        preflight = db.preflight_autonomous(envelope_id)
    except RuntimeError as e:
        record = {"ok": False, "reason": f"preflight refused: {e}", "ts": time.time(), "envelope_id": envelope_id}
        db.kv_set(f"nightly:{key}", json.dumps(record))
        log.warning("nightly envelope %s refused at preflight: %s", envelope_id, e)
        return {"ran": False, **record}

    budget = settings.t4_nightly_budget
    remaining = budget
    per_project: list[dict[str, Any]] = []
    # most-recently-active project first: with a shared nightly budget, whatever gets touched most recently
    # by the person using the product is the most likely to still matter tonight.
    projects = [p for p in db.list_projects() if p.get("n_sources")]
    for p in projects:
        if remaining <= 0:
            break
        # L-31: capture a real "before" coverage snapshot now, the only moment it can honestly be taken --
        # after t4.execute runs, "before" no longer exists to observe. A snapshot failure never blocks the
        # night's work; it just leaves delta.for_envelope() unable to compute a coverage delta for this project.
        try:
            from . import t1
            snapshot_before = t1.coverage_view(p["id"], limit=0)
        except Exception as e:  # noqa: BLE001
            log.warning("nightly envelope %s: before-snapshot failed for project %s: %s", envelope_id, p["id"], e)
            snapshot_before = None
        try:
            r = t4.execute(p["id"], budget_usd=remaining, dry_run=False, transport="batch")
        except Exception as e:  # noqa: BLE001 — one project's failure must never abort the rest of the night
            log.warning("nightly envelope %s: t4.execute failed for project %s: %s", envelope_id, p["id"], e)
            per_project.append({"project_id": p["id"], "error": str(e), "snapshot_before": snapshot_before})
            continue
        spent = float(r.get("total_estimate") or 0)
        remaining = max(0.0, remaining - spent)
        per_project.append({"project_id": p["id"], "executed": r.get("executed"), "estimate": spent,
                            "job_ids": r.get("job_ids"), "count": r.get("count"), "snapshot_before": snapshot_before})

    # L-60: T5 adjudication under its OWN per-night cap (settings.t5_nightly_budget, default 0 = off), after the
    # findings walk. Separate authorization on purpose: an adjudication is a Sonnet-tier call, and folding it into
    # the findings budget would let one silently eat the other. Same rule as above: a failure here never loses the
    # findings record.
    adjudication: dict[str, Any] | None = None
    if settings.t5_nightly_budget > 0:
        try:
            from . import t5
            adjudication = t5.run_nightly([p["id"] for p in projects], budget_usd=settings.t5_nightly_budget, envelope_id=envelope_id)
        except Exception as e:  # noqa: BLE001
            log.warning("nightly envelope %s: T5 adjudication pass failed: %s", envelope_id, e)
            adjudication = {"ran": False, "error": str(e), "budget": settings.t5_nightly_budget}

    record = {"ok": True, "envelope_id": envelope_id, "ts": time.time(), "budget": budget,
              "spent_estimate": round(budget - remaining, 4), "projects": per_project,
              "adjudication": adjudication,
              "preflight_backup": preflight.get("backup_path")}
    db.kv_set(f"nightly:{key}", json.dumps(record))
    log.info("nightly envelope %s: %d project(s) touched, ~$%.4f of $%.2f estimated",
            envelope_id, sum(1 for x in per_project if x.get("executed")), record["spent_estimate"], budget)
    return {"ran": True, **record}
