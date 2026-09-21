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
# 2026-09-21: `evidence_dismissed` leads, because it is the only reason here that describes a Claim standing on
# grounds its OWNER has already rejected -- the others describe a Claim that is merely hard to judge.
#
# The gap it closes: `claim_evidence` is keyed by SOURCE, and `claims.assess` filters only on whether a source
# revision moved. Nothing anywhere consults a NOTE's status. So dismissing a finding removed it from chat, from
# exports and from future harvesting -- and left every Claim built on it standing at unchanged strength, with
# no indication its evidence had been rejected. `retire.py` models exactly this loss, but only for sources
# LEAVING the project; the ordinary Dismiss button never had an equivalent. A rejected finding whose conclusion
# quietly survives is the worst shape this can take, because the user believes they have acted.
REASON_ORDER = ("evidence_dismissed", "disagreement", "plan_impact", "evidence_weak")
SIGNALS_NOT_USED = ("novelty", "irreversibility", "provenance_quality", "source_independence", "freshness_sensitivity")


def build(project_id: str, limit: int = 25) -> dict[str, Any]:
    """$0, deterministic, read-only. Returns the queue plus the counts a UI needs to be honest about it."""
    from . import claims, decision_impact, knowledge

    conn = db.connect()
    proposed = [c for c in claims.list_for_project(project_id, status="proposed", with_evidence=False)]
    # 2026-09-21: ACCEPTED Claims are checked too, for the one reason that can apply to them. An accepted Claim
    # is one the user personally stood behind; if they have since dismissed every finding under it, that is a
    # direct contradiction between two of their own judgements, and `claims.assess` will never notice -- it
    # consults source revisions, not note status, so the Claim keeps its strength forever. That makes this the
    # clearest possible case of "needs a human", not a reason to leave it out of a queue built for exactly that.
    accepted = [c for c in claims.list_for_project(project_id, status="accepted", with_evidence=False)]
    ids = [c["id"] for c in proposed] + [c["id"] for c in accepted]
    impact = decision_impact.decision_impact(project_id, ids) if ids else {}

    tensions_by_claim: dict[str, list[dict[str, Any]]] = {}
    for t in knowledge.list_tensions(project_id, status="open"):
        if t.get("claim_id"):
            tensions_by_claim.setdefault(t["claim_id"], []).append(
                {"id": t["id"], "kind": t["kind"], "impact": t.get("impact"), "description": t.get("description")})

    # Which proposed Claims rest ONLY on findings the user has dismissed. "Only" is the defensible line and it
    # mirrors retire.py's own `HAVING SUM(...) = 0`: one dismissed finding among three leaves a Claim supported,
    # while all of them dismissed leaves it supported by nothing its owner still accepts. Both routes a note can
    # back a Claim are counted -- `origin_note_id` (the finding it was harvested from) and `claim_evidence_notes`
    # (findings later folded in as support) -- because either alone would miss real cases.
    evidence_dismissed: set[str] = set()
    if ids:
        marks = ",".join("?" for _ in ids)
        for r in conn.execute(
                f"""SELECT cid, SUM(CASE WHEN n.status='dismissed' THEN 0 ELSE 1 END) alive, COUNT(*) total FROM (
                        SELECT id AS cid, origin_note_id AS nid FROM project_claims
                         WHERE id IN ({marks}) AND origin_note_id IS NOT NULL
                        UNION
                        SELECT claim_id AS cid, note_id AS nid FROM claim_evidence_notes WHERE claim_id IN ({marks})
                    ) JOIN project_notes n ON n.id = nid GROUP BY cid""", [*ids, *ids]).fetchall():
            if int(r["total"]) and not int(r["alive"]):
                evidence_dismissed.add(r["cid"])

    note_ids_by_claim: dict[str, list[int]] = {}
    if ids:
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
    # every proposed Claim is a candidate; an accepted one only when its evidence is gone
    for c in proposed + [c for c in accepted if c["id"] in evidence_dismissed]:
        cid = c["id"]
        imp = impact.get(cid, {})
        reasons = []
        if cid in evidence_dismissed:
            reasons.append("evidence_dismissed")
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
            # 2026-09-21: `origin` has recorded 'finding_suggested' since claims.py:611 -- a Claim harvested
            # from a finding nobody ever reviewed -- and NOTHING has ever surfaced it. On Kyle's project that is
            # 2,352 unreviewed findings feeding proposed Claims invisibly. A Claim standing on evidence its
            # owner has not looked at is exactly the thing this queue exists to put in front of him.
            "origin": c.get("origin"),
            "status": c.get("status"),        # "accepted" here means: you stood behind this, then rejected what it stood on
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

    # Never capped, for the same reason disagreement is not: a Claim resting on rejected evidence is not a
    # "nice to get to" item, and hiding it behind a limit is how it stays invisible for another month.
    UNCAPPED = ("disagreement", "evidence_dismissed")
    must_show = [x for x in candidates if any(r in x["reasons"] for r in UNCAPPED)]
    capped_pool = [x for x in candidates if not any(r in x["reasons"] for r in UNCAPPED)]
    room = max(0, limit - len(must_show))
    shown = must_show + capped_pool[:room]
    hidden = capped_pool[room:]

    def _by_reason(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {r: sum(1 for x in rows if r in x["reasons"]) for r in REASON_ORDER}

    # S76 (item 1, Kyle's decision session, 2026-09-20): a synthesized summary line above a group of related
    # weak claims -- e.g. "9 sources give ranges of 1x-7x SDE ... most cluster around 2-4x SDE." Computed over
    # `shown` -- the same claims actually visible in this queue view -- not the full unbounded `candidates` list:
    # a project can carry thousands of proposed claims across its whole history, and summarizing all of them
    # would blend claims the caller never asked to see into one line above claims they did. Grouped by (topic,
    # basis) so claims measuring genuinely different things (SDE vs. revenue vs. profit vs. cash flow) are never
    # blended -- this is deliberately NOT claim merging (see claims.py's narrow `merge_into`); the individual
    # claims below are untouched.
    from . import claim_synthesis
    topic_summaries = claim_synthesis.synthesize_topic_summaries(shown)

    return {
        "project_id": project_id, "limit": limit,
        "topic_summaries": topic_summaries,
        "queue": shown,
        "counts": {"proposed_total": len(proposed), "candidates": len(candidates), "shown": len(shown),
                   "accepted_on_dismissed_evidence": sum(1 for x in candidates if x.get("status") == "accepted"),
                   "by_reason": _by_reason(shown), "not_shown": _by_reason(hidden), "hidden_total": len(hidden)},
        "basis": {"signals_used": list(REASON_ORDER), "signals_not_used": list(SIGNALS_NOT_USED),
                  "plan_impact_known": bool(ids) and all(v.get("plan_impact") != "unknown" for v in impact.values()),
                  "disagreement_never_capped": True, "auto_approve": "never"},
    }
