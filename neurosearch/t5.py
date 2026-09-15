"""Transcript Intelligence T5: the adjudication escalation trigger.

The brief's "Supreme Court" framing is already the shape of ``contracts.TIERS``; what was missing, per the
mission doc, is the *escalation trigger* itself. This module is that trigger and nothing more: it is pure and
read-only (no write, no provider call, no queue, no registration into ``contracts.py``'s own contract registry),
and it PROPOSES adjudication candidates — it does not run them. Wiring a real provider call onto one of these
proposals, and deciding when that is worth doing live, is deliberately left to a future rung: this slice was
built and validated only against the existing fake-provider test harness, matching this codebase's own
``batch_smoke.py --live``-opt-in convention (no live paid call is made anywhere in this module).

Trigger conditions, grounded in what this codebase already measures — not invented:

- **Sources materially disagree**: an open, high-impact ``CONTRADICTION`` tension (``knowledge.list_tensions``,
  ``research_tensions.kind``). This is not a new signal; T5 reads the same tension-detection pass D0-era code
  already runs, applying the mission doc's own escalation bar (impact) rather than surfacing every open tension.
- **A high-importance Claim has ambiguous evidence**: an open, high-impact ``NOVEL`` or ``WEAK_CONSENSUS``
  tension — a Claim resting on thin or non-independent corroboration, exactly what those two tension kinds mean.

Deliberately NOT a trigger in this slice: "cheaper systems disagreed" (the mission doc's third example). Nothing
in this codebase currently records a same-task comparison across model tiers to read — adding that measurement
is its own future, separately-admitted rung, not invented here.

Every proposed candidate carries a properly-formed ``evidence:`` ``tier_reason`` (see ``contracts.py``'s own
"three admissible reasons" rule) naming a LIVE ``cost_value.by_model`` comparison — never a stated opinion and
never this document — so the gate the mission doc names is met exactly: "the model decision table (`neurosearch
models`) still refuses any tier above the cheapest without a stated reason; the split is justified by a live
comparison, not by this document."
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import claims as claims_mod
from . import contracts, cost_value, db, knowledge, providers, usage

TRIGGER_VERSION = "t5-trigger-v1"
ADJUDICATE_TASK = "t5.adjudicate"

# research_tensions.kind -> what that disagreement means in the mission doc's own vocabulary.
_TRIGGER_KIND_BY_TENSION_KIND = {
    "CONTRADICTION": "source_disagreement",
    "NOVEL": "ambiguous_evidence",
    "WEAK_CONSENSUS": "ambiguous_evidence",
}


def _comparison_detail(*, unit: str, window: str) -> tuple[str, dict[str, Any]]:
    """A live ``cost_value.by_model`` comparison, and the one-line summary used as an ``evidence:`` reason's
    detail. Never fabricated: when there is not yet enough recorded spend to compare, the detail says so plainly
    rather than inventing a number."""
    report = cost_value.by_model(unit=unit, window=window)
    if not report.get("supported"):
        return f"cost_value.by_model({unit!r}) unsupported: {report.get('reason')}", report
    comparable = [r for r in report["rows"] if r["comparable"] and r["per_unit"] is not None]
    if not comparable:
        return f"no comparable {unit} cost-per-model data recorded yet this {window}", report
    cheapest_row = comparable[0]  # by_model already sorts comparable rows by ascending per_unit
    detail = (f"{unit} cost/model this {window}: cheapest measured is {cheapest_row['model']} at "
              f"${cheapest_row['per_unit']}/{unit} ({cheapest_row['count']} produced)")
    return detail, report


def escalation_candidates(project_id: str, *, unit: str = "claim", window: str = "month", decision_aware: bool = False) -> dict[str, Any]:
    """Return proposed adjudication candidates for ``project_id``: open tensions that meet T5's escalation bar,
    each paired with a properly-formed, gate-admissible ``evidence:`` tier_reason.

    Read-only: queries ``knowledge.list_tensions`` and ``cost_value.by_model``, both existing read paths; writes
    no row, calls no provider, and registers nothing in ``contracts.py``'s contract table. The returned
    ``proposed_model`` is never executed here — a future rung decides whether and how to actually run one.

    ``decision_aware=True`` (L-60, EXECUTION-LADDER.md Stage 8): adds the mission doc's two decision-shaped
    triggers, both grounded in L-50's real ``plan_impact`` signal rather than a guessed importance --
    ``weak_consensus_on_decision`` (an open WEAK_CONSENSUS tension, any impact, on a Claim the current plan
    cites) and ``plan_critical_uncertainty`` (an open CONTRADICTION/NOVEL tension, any impact, on such a Claim).
    When ``plan_impact`` is "unknown" (no plan, or notes changed since it was built) these add nothing -- unknown
    never escalates, same rule as decision_impact itself. Off by default so existing callers are unchanged.
    """
    detail, comparison = _comparison_detail(unit=unit, window=window)
    tier_reason = f"evidence:{detail}"
    # Sanity gate: T5 must never propose a reason the ladder itself would reject.
    assert contracts.policy_reason_ok(tier_reason), f"T5 produced an inadmissible tier_reason: {tier_reason!r}"

    adjudicator_model = contracts.TIERS[1]  # one tier above cheapest — Sonnet, not Haiku, per the brief's framing
    plan_cited: set[str] = set()
    if decision_aware:
        from . import decision_impact
        plan_cited = {cid for cid, v in decision_impact.decision_impact(project_id).items() if v.get("plan_impact") is True}
    candidates: list[dict[str, Any]] = []
    for tension in knowledge.list_tensions(project_id, status="open"):
        trigger = _TRIGGER_KIND_BY_TENSION_KIND.get(tension["kind"])
        if trigger is None:
            continue
        if tension.get("impact") != "high":
            if not (decision_aware and tension.get("claim_id") in plan_cited):
                continue
            trigger = "weak_consensus_on_decision" if tension["kind"] == "WEAK_CONSENSUS" else "plan_critical_uncertainty"
        proposed = contracts.InferenceContract(
            task=f"adjudication.{tension['id']}", provider="anthropic", model=adjudicator_model,
            tier_reason=tier_reason, reversible=True,
            gate="a human, or a future automated adjudication pass, reviews the tension before any Claim status changes",
        )
        decision = contracts.decision(proposed)
        candidates.append({
            "tension_id": tension["id"], "claim_id": tension.get("claim_id"), "trigger": trigger,
            "impact": tension.get("impact"), "description": tension.get("description"),
            "proposed_task": proposed.task, "proposed_model": proposed.model,
            "tier_reason": tier_reason, "decision_verdict": decision["verdict"],
        })
    candidates.sort(key=lambda c: c["tension_id"])
    return {"trigger_version": TRIGGER_VERSION, "project_id": project_id,
            "comparison_unit": unit, "comparison_window": window, "comparison_basis": detail,
            "comparison_supported": bool(comparison.get("supported")),
            "count": len(candidates), "candidates": candidates}


def _evidence_lines(evidence: list[dict[str, Any]]) -> str:
    lines = []
    for e in evidence:
        if e.get("stale"):
            continue
        indep = "independent" if e.get("independent") else "not independent"
        excerpt = (e.get("excerpt") or "").strip().replace("\n", " ")
        lines.append(f"- [{e.get('relation', '?')}, {indep}] {e.get('title') or e.get('source_id') or '?'}: {excerpt[:280]}")
    return "\n".join(lines) or "(no evidence recorded on this Claim)"


def adjudicate(project_id: str, tension_id: str, *, write: bool = True, decision_aware: bool = False) -> dict[str, Any]:
    """Run ONE live adjudication call for a specific open, high-impact tension this project's own deterministic
    tension detection already flagged (see ``escalation_candidates`` -- this function refuses any ``tension_id``
    that isn't currently one of its candidates, so it can never escalate something the trigger didn't select).

    This makes a real, metered call through ``providers.invoke`` under the ``t5.adjudicate`` contract -- genuine
    spend, never a simulation. It is forced onto the API backend (``providers.policy_context("api_only")``)
    rather than the local Claude Code path, so the cost is exactly what ``usage.PRICES`` says for Sonnet, not an
    ambiguous local-subscription call.

    On success the verdict is written as a SUGGESTED finding (``db.add_project_note(..., status="suggested")``)
    -- it lands in the project's ordinary review queue exactly like any other candidate research output.
    Nothing here changes a Claim's or a tension's status; ``claims.set_status`` remains the only promotion door.
    """
    candidates = {c["tension_id"]: c for c in escalation_candidates(project_id, decision_aware=decision_aware)["candidates"]}
    candidate = candidates.get(tension_id)
    if candidate is None:
        raise ValueError(f"{tension_id!r} is not an open, high-impact tension this project's escalation trigger currently flags")
    claim = next((c for c in claims_mod.list_for_project(project_id) if c["id"] == candidate["claim_id"]), None)
    if claim is None:
        raise ValueError(f"claim {candidate['claim_id']!r} for tension {tension_id!r} was not found")
    project = db.get_project(project_id)
    if project is None:
        raise ValueError(f"project {project_id!r} was not found")

    system = ("You are adjudicating one research disagreement for a private research project. Read the Claim "
              "and its recorded evidence, then give a short, direct verdict: which position the evidence "
              "actually supports (if either), how confident that is, and what -- if anything -- would resolve "
              "the ambiguity. Use only the evidence given to you; never invent a source or a number. Three to "
              "five sentences, not an essay.")
    user = (f"PROJECT: {project['name']}\nCLAIM: {claim['text']}\nTRIGGER: {candidate['trigger']}\n"
           f"TENSION: {candidate['description']}\n\nRECORDED EVIDENCE:\n{_evidence_lines(claim.get('evidence') or [])}\n\n"
           "Give your adjudication now.")

    with providers.policy_context("api_only"):
        resp = providers.invoke(ADJUDICATE_TASK, system=system, messages=[{"role": "user", "content": user}])
    cost = usage.record_anthropic(resp, "adjudication", project_id=project_id)
    verdict = providers.text_of(resp).strip()

    result = {"trigger_version": TRIGGER_VERSION, "project_id": project_id, "tension_id": tension_id,
             "claim_id": candidate["claim_id"], "trigger": candidate["trigger"], "tier_reason": candidate["tier_reason"],
             "model": str(getattr(resp, "model", None) or contracts.contract(ADJUDICATE_TASK).model),
             "cost": cost, "verdict": verdict, "written_note_id": None}
    if write and verdict:
        note = db.add_project_note(project_id,
            content=f"[T5 adjudication -- {candidate['trigger']}] {candidate['description']}\n\nVerdict: {verdict}",
            citations=[], status="suggested", importance=4)
        result["written_note_id"] = note["id"]
        db.kv_set(f"t5:adjudicated:{tension_id}", json.dumps({"note_id": note["id"], "ts": time.time(), "cost": cost}))
    return result


def already_adjudicated(tension_id: str) -> bool:
    return db.kv_get(f"t5:adjudicated:{tension_id}") is not None


def estimate_adjudication(project_id: str, claim_id: str | None) -> float:
    """What one adjudicate() call would cost, from the same prompt size it would actually send (usage.estimate_model_call
    on the t5.adjudicate contract), never a flat guess."""
    claim = next((c for c in claims_mod.list_for_project(project_id) if c["id"] == claim_id), None) if claim_id else None
    n_chars = 600 + (len(claim["text"]) + len(_evidence_lines(claim.get("evidence") or [])) if claim else 0)
    return usage.estimate_model_call(ADJUDICATE_TASK, n_chars)


def run_nightly(project_ids: list[str], *, budget_usd: float, envelope_id: str) -> dict[str, Any]:
    """L-60: budgeted per night. Walks the given projects' decision-aware candidates, most consequential first
    (high impact before decision-triggered, then oldest tension), skipping any tension already adjudicated on a
    previous night (kv ``t5:adjudicated:*`` -- the same disagreement is never paid for twice), estimating each
    call before making it and stopping at the first that would exceed ``budget_usd``. Every verdict lands as a
    SUGGESTED finding (adjudicate()'s only write); no Claim or tension status ever changes here.

    ``budget_usd <= 0`` means off: returns immediately having called nothing. One project's failure never aborts
    the others. Returns the per-call record the nightly envelope stores."""
    out: dict[str, Any] = {"envelope_id": envelope_id, "budget": budget_usd, "spent_estimate": 0.0, "spent": 0.0,
                           "adjudicated": [], "skipped_already": 0, "stopped_by_budget": None, "errors": []}
    if budget_usd <= 0:
        return {**out, "ran": False, "reason": "t5_nightly_budget is 0 (off)"}
    remaining = float(budget_usd)
    queue: list[tuple[tuple, str, dict[str, Any]]] = []
    for pid in project_ids:
        try:
            for c in escalation_candidates(pid, decision_aware=True)["candidates"]:
                if already_adjudicated(c["tension_id"]):
                    out["skipped_already"] += 1
                    continue
                rank = (0 if c["impact"] == "high" else 1, c["tension_id"])
                queue.append((rank, pid, c))
        except Exception as e:  # noqa: BLE001
            out["errors"].append({"project_id": pid, "error": str(e)})
    queue.sort(key=lambda x: x[0])
    for _, pid, c in queue:
        est = estimate_adjudication(pid, c.get("claim_id"))
        if est > remaining:
            out["stopped_by_budget"] = {"tension_id": c["tension_id"], "estimate": round(est, 4), "remaining": round(remaining, 4)}
            break
        try:
            r = adjudicate(pid, c["tension_id"], decision_aware=True)
        except Exception as e:  # noqa: BLE001 -- one failed call never aborts the night's other adjudications
            out["errors"].append({"project_id": pid, "tension_id": c["tension_id"], "error": str(e)})
            continue
        remaining -= est
        out["spent_estimate"] = round(out["spent_estimate"] + est, 4)
        out["spent"] = round(out["spent"] + float(r.get("cost") or 0), 4)
        out["adjudicated"].append({"project_id": pid, "tension_id": c["tension_id"], "claim_id": c.get("claim_id"),
                                   "trigger": c["trigger"], "note_id": r.get("written_note_id"), "cost": r.get("cost")})
    return {**out, "ran": True}
