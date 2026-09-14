"""Transcript Intelligence T4: the selector half of the Batch Research Executor.

Deliberately separate from any executor, per the mission doc's own fifth correction: "what is worth spending on"
and "who executes it" are two different questions, and this module answers only the first one.

Pure and read-only, exactly like T1's ``coverage_view`` and T3's ``extract``: no write, no queue, no provider
call, no promotion of research state. It reads T1+T2 signals (via ``t1.coverage_view``) and open Evidence
Targets (via ``knowledge.list_targets``), scores deterministic Tier-0 cue density on genuinely unexplained
passages with T3's own pure extractor, and returns a ranked, reproducible work list. Every item carries an
``input_hash`` (T1's own ``input_hash`` helper) derived only from the item's own identifying fields, so a re-run
against unchanged data reproduces byte-identical ranking and provenance, and nothing here decides who acts on
the list or writes anything back — ``claims.set_status`` remains the only promotion door, as it always has.
"""
from __future__ import annotations

from typing import Any

from . import contracts, db, knowledge, providers, t1, t3

SELECTOR_VERSION = "t4-selector-v1"
PLAN_VERSION = "t4-plan-v1"
EXECUTOR_TASK = "t4.research"

# Tier-0 record kinds whose presence on an already-unexplained chunk raises its priority: these are the
# "numbers and procedure that nothing has ever read" the mission doc names as worth surfacing first.
_HIGH_VALUE_T3_KINDS = ("money", "percentage", "duration", "unit", "number", "procedure", "warning", "date")


def _unexplained_chunk_items(project_id: str, *, chunk_limit: int | None) -> list[dict[str, Any]]:
    coverage = t1.coverage_view(project_id, limit=chunk_limit)
    # T2's own coverage_view never asserts primary_state "unexplained" while extracted/redundant/irrelevant
    # remain unavailable (see docs/T2-ADMISSION-2026-09-13.md: "unexplained is never asserted while any
    # required signal is unavailable") — which today is always, since T3 is not wired into that view and
    # redundant/irrelevant have no chunk-level signal yet. T4 does not change T2's honesty rule; instead it
    # reads the same underlying fact T2 already exposes (an empty ``signals`` list: no Claim/Finding coverage
    # and no semantic representation) and applies its own read of T3's extractor on top, which is exactly the
    # gap the mission doc names this rung to close.
    unexplained = [row for row in coverage["chunks"] if not row["signals"]]
    if not unexplained:
        return []
    ids = [row["chunk_id"] for row in unexplained]
    placeholders = ",".join("?" for _ in ids)
    text_by_id = {int(r["id"]): r["text"] or "" for r in
                  db.connect().execute(f"SELECT id, text FROM chunks WHERE id IN ({placeholders})", ids).fetchall()}
    items: list[dict[str, Any]] = []
    for row in unexplained:
        text = text_by_id.get(row["chunk_id"], "")
        cue_kinds = sorted({rec["kind"] for rec in t3.extract(text)["records"] if rec["kind"] in _HIGH_VALUE_T3_KINDS})
        # Priority 1 (highest) when Tier-0 found something concrete worth reading; priority 2 otherwise —
        # still genuinely unexplained, just with no deterministic signal yet pointing at *why* it matters.
        priority = 1 if cue_kinds else 2
        items.append({
            "kind": "unexplained_chunk",
            "chunk_id": row["chunk_id"], "source_id": row["source_id"], "chunk_idx": row["chunk_idx"],
            "start": row["start"], "end": row["end"],
            "reason": ("Tier-0 extraction found " + ", ".join(cue_kinds) + " with no Claim/Finding coverage"
                       if cue_kinds else "no Claim/Finding coverage, no Tier-0 cue"),
            "cue_kinds": cue_kinds,
            "priority": priority,
            "input_hash": t1.input_hash(SELECTOR_VERSION, "unexplained_chunk", row["chunk_id"], row["start"], row["end"]),
        })
    return items


def _open_target_items(project_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for target in knowledge.list_targets(project_id, status="open"):
        # A governing target with no Claim at all yet is the most consequential unresolved question this
        # project has; a governing target that already has a Claim, or a merely corroborative one, ranks lower.
        governing = target.get("sufficiency") == "governing"
        priority = 1 if (governing and not target.get("claim_id")) else (2 if governing else 3)
        items.append({
            "kind": "open_evidence_target",
            "target_id": target["id"], "question": target["question"], "sufficiency": target.get("sufficiency"),
            "claim_id": target.get("claim_id"),
            "reason": ("open governing target with no supporting Claim" if governing and not target.get("claim_id")
                       else "open governing target" if governing else "open corroborative target"),
            "priority": priority,
            "input_hash": t1.input_hash(SELECTOR_VERSION, "open_evidence_target", target["id"], target.get("updated_at")),
        })
    return items


def select(project_id: str, *, limit: int | None = None, chunk_limit: int | None = None) -> dict[str, Any]:
    """Return a ranked, reproducible work list of candidate research items for ``project_id``.

    Read-only: this function makes no database write, queues no job, calls no provider, and does not change
    research state. ``chunk_limit`` bounds how many of the project's chunks ``t1.coverage_view`` inspects (for
    very large projects); ``limit`` bounds how many ranked items are returned. Items are ordered by
    ``(priority, input_hash)`` — priority is the product judgement, ``input_hash`` breaks ties deterministically
    so the same inputs always produce the same order, independent of database row order or dict iteration.
    """
    items = _unexplained_chunk_items(project_id, chunk_limit=chunk_limit) + _open_target_items(project_id)
    items.sort(key=lambda item: (item["priority"], item["input_hash"]))
    selected = items if limit is None else items[:limit]
    return {"selector_version": SELECTOR_VERSION, "project_id": project_id, "count": len(items),
            "by_kind": {kind: sum(1 for i in items if i["kind"] == kind)
                        for kind in ("unexplained_chunk", "open_evidence_target")},
            "items": selected}


def plan(project_id: str, *, limit: int | None = None, chunk_limit: int | None = None) -> dict[str, Any]:
    """The executor's dry run: route ``select()``'s ranked items through the SAME contract and execution-policy
    seam a real executor call would use, without making one.

    This deliberately stops short of calling ``providers.route`` -- that function's local branch can start a
    Claude Code health probe (a real, if small, subscription spend) whenever the cached verdict has expired, and
    this function's whole purpose is to prove the wiring at $0, not to guess whether now is a good moment to
    spend a few tokens on a health check. It reads only ``contracts.contract(EXECUTOR_TASK)`` (a pure lookup) and
    ``providers.current_policy()`` (a pure thread-local read) -- both zero-cost and side-effect-free -- and
    reports what routing WOULD be eligible. No provider is called, no health probe runs, no row is written, and
    ``claims.set_status`` -- the only promotion door -- is never approached.

    Wiring a live call is future work: the point of this slice is that it requires adding the call itself where
    ``executed`` is currently always ``False``, not inventing new routing machinery to carry it.
    """
    selection = select(project_id, limit=limit, chunk_limit=chunk_limit)
    c = contracts.contract(EXECUTOR_TASK)
    policy = providers.current_policy()
    eligible_for_local = bool(c.local_capable) and policy not in ("api_only", "api_requested")
    if policy in ("api_only", "api_requested"):
        routing_note = f"api only: execution policy is {policy!r}"
    elif not c.local_capable:
        routing_note = "api only: t4.research is not local-capable"
    else:
        routing_note = "eligible for the local (Claude Code) backend, pending providers.route()'s health check at call time"
    items = [{**item, "executor_task": EXECUTOR_TASK, "executor_model": c.model,
             "eligible_for_local": eligible_for_local, "executed": False} for item in selection["items"]]
    return {"plan_version": PLAN_VERSION, "project_id": project_id, "selector_version": selection["selector_version"],
            "executor_task": EXECUTOR_TASK, "executor_model": c.model, "policy": policy,
            "eligible_for_local": eligible_for_local, "routing_note": routing_note,
            "count": selection["count"], "by_kind": selection["by_kind"], "items": items,
            "note": "dry run only: no provider call was made; providers.route() decides real backend/health at call time (not yet wired)"}
