"""L-51 (EXECUTION-LADDER.md Stage 7, PRODUCT-INTELLIGENCE-MISSION.md P4 "Research Review at Scale"): the
exception queue. "Which few things actually require human judgment?" -- answered with a SHORT list whose every
entry can say why it is there, built only from signals the system can actually prove, and which never hides a
consequential disagreement behind the cap.

Review unit = the proposed Claim, not the raw finding. `claims.harvest()` already folds twin findings (approved
and suggested alike) into one Claim via `claim_evidence_notes`, and merges duplicate proposed Claims via
`superseded_by`; so one queue item is one representative proposition, and its inspectable members are the
findings folded into it plus any Claims merged into it. That is P4's "representative review while preserving
inspectability" using the grouping the product already has, not a second clustering.

Inclusion (P4's candidate signals, restricted -- like L-50 -- to the ones that are real today):
  disagreement   an open CONTRADICTION/NOVEL tension touches the Claim   (decision_impact, L-50)
  plan_impact    the Claim's findings are cited in the current plan       (decision_impact, L-50)
  evidence_weak  strength is weak/unsupported                             (claims.py, deterministic)
Novelty, irreversibility, provenance quality, freshness sensitivity: NOT used -- no defensible basis yet, and a
made-up score here would be exactly the "intelligently minimized queue Neuro cannot rank honestly" that rulings
section 7 forbids. They are named in `basis` as absent so the UI can say so.

Cap: `limit` applies to plan_impact and evidence_weak items only. Disagreement items are NEVER dropped by the cap
(the gate: "without hiding consequential disagreement"); when there are more than the cap of them the queue is
simply longer, and `counts.not_shown` reports exactly what the cap did hide, by reason.

Never auto-approves: this module writes nothing. It has no path to `claims.set_status` (L-15's promotion boundary)
and no INSERT/UPDATE at all; a static test pins that. "Do not auto-approve merely because confidence is high" is
satisfied structurally -- there is no approve here, at any confidence.
"""
from __future__ import annotations

from typing import Any

from . import db

WEAK = ("weak", "unsupported")
REASON_ORDER = ("disagreement", "plan_impact", "evidence_weak")
SIGNALS_NOT_USED = ("novelty", "irreversibility", "provenance_quality", "source_independence", "freshness_sensitivity")


def build(project_id: str, limit: int = 25) -> dict[str, Any]:
    """$0, deterministic, read-only. Returns the queue plus the counts a UI needs to be honest about it."""
    from . import claims, decision_impact, knowledge

    conn = db.connect()
    proposed = [c for c in claims.list_for_project(project_id, status="proposed", with_evidence=False)]
    ids = [c["id"] for c in proposed]
    impact = decision_impact.decision_impact(project_id, ids) if ids else {}

    tensions_by_claim: dict[str, list[dict[str, Any]]] = {}
    for t in knowledge.list_tensions(project_id, status="open"):
        if t.get("claim_id"):
            tensions_by_claim.setdefault(t["claim_id"], []).append(
                {"id": t["id"], "kind": t["kind"], "impact": t.get("impact"), "description": t.get("description")})

    note_ids_by_claim: dict[str, list[int]] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for r in conn.execute(f"SELECT claim_id, note_id FROM claim_evidence_notes WHERE claim_id IN ({marks}) ORDER BY note_id", ids).fetchall():
            note_ids_by_claim.setdefault(r["claim_id"], []).append(int(r["note_id"]))
        merged_into: dict[str, list[str]] = {}
        for r in conn.execute(f"SELECT id, superseded_by FROM project_claims WHERE project_id=? AND status='superseded' AND superseded_by IN ({marks})",
                              (project_id, *ids)).fetchall():
            merged_into.setdefault(r["superseded_by"], []).append(r["id"])
    else:
        merged_into = {}
    source_ids_by_claim = claims.evidence_source_ids(project_id) if ids else {}

    candidates: list[dict[str, Any]] = []
    for c in proposed:
        cid = c["id"]
        imp = impact.get(cid, {})
        reasons = []
        if imp.get("disagreement"):
            reasons.append("disagreement")
        if imp.get("plan_impact") is True:
            reasons.append("plan_impact")
        if c.get("strength") in WEAK:
            reasons.append("evidence_weak")
        if not reasons:
            continue
        candidates.append({
            "claim_id": cid, "text": c["text"], "claim_type": c.get("claim_type"), "topic": c.get("topic"),
            "strength": c.get("strength"), "strength_why": c.get("strength_why"),
            "reasons": reasons,
            "disagreement": bool(imp.get("disagreement")), "plan_impact": imp.get("plan_impact", "unknown"),
            "tensions": tensions_by_claim.get(cid, []),
            "members": {"note_ids": note_ids_by_claim.get(cid, []), "merged_claim_ids": merged_into.get(cid, [])},
            "independent_sources": len(source_ids_by_claim.get(cid, ())),
            "created_at": c.get("created_at"),
        })

    # Order inside the queue: disagreement first (then by tension impact), plan_impact next, evidence_weak last;
    # within a tier, more folded findings first (more evidence pressure behind one proposition), then oldest.
    def _key(x: dict[str, Any]) -> tuple:
        tier = min(REASON_ORDER.index(r) for r in x["reasons"])
        high = any(t.get("impact") == "high" for t in x["tensions"])
        return (tier, 0 if high else 1, -len(x["members"]["note_ids"]), x["created_at"] or 0)
    candidates.sort(key=_key)

    must_show = [x for x in candidates if "disagreement" in x["reasons"]]
    capped_pool = [x for x in candidates if "disagreement" not in x["reasons"]]
    room = max(0, limit - len(must_show))
    shown = must_show + capped_pool[:room]
    hidden = capped_pool[room:]

    def _by_reason(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {r: sum(1 for x in rows if r in x["reasons"]) for r in REASON_ORDER}

    return {
        "project_id": project_id, "limit": limit,
        "queue": shown,
        "counts": {"proposed_total": len(proposed), "candidates": len(candidates), "shown": len(shown),
                   "by_reason": _by_reason(shown), "not_shown": _by_reason(hidden), "hidden_total": len(hidden)},
        "basis": {"signals_used": list(REASON_ORDER), "signals_not_used": list(SIGNALS_NOT_USED),
                  "plan_impact_known": bool(ids) and all(v.get("plan_impact") != "unknown" for v in impact.values()),
                  "disagreement_never_capped": True, "auto_approve": "never"},
    }
