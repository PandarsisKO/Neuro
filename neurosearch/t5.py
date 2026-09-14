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


def escalation_candidates(project_id: str, *, unit: str = "claim", window: str = "month") -> dict[str, Any]:
    """Return proposed adjudication candidates for ``project_id``: open tensions that meet T5's escalation bar,
    each paired with a properly-formed, gate-admissible ``evidence:`` tier_reason.

    Read-only: queries ``knowledge.list_tensions`` and ``cost_value.by_model``, both existing read paths; writes
    no row, calls no provider, and registers nothing in ``contracts.py``'s contract table. The returned
    ``proposed_model`` is never executed here — a future rung decides whether and how to actually run one.
    """
    detail, comparison = _comparison_detail(unit=unit, window=window)
    tier_reason = f"evidence:{detail}"
    # Sanity gate: T5 must never propose a reason the ladder itself would reject.
    assert contracts.policy_reason_ok(tier_reason), f"T5 produced an inadmissible tier_reason: {tier_reason!r}"

    adjudicator_model = contracts.TIERS[1]  # one tier above cheapest — Sonnet, not Haiku, per the brief's framing
    candidates: list[dict[str, Any]] = []
    for tension in knowledge.list_tensions(project_id, status="open"):
        trigger = _TRIGGER_KIND_BY_TENSION_KIND.get(tension["kind"])
        if trigger is None or tension.get("impact") != "high":
            continue
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


def adjudicate(project_id: str, tension_id: str, *, write: bool = True) -> dict[str, Any]:
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
    candidates = {c["tension_id"]: c for c in escalation_candidates(project_id)["candidates"]}
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
    return result
