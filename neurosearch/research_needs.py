"""CR1 (mission §12, EXECUTION-LADDER.md Stage 10): what in this project could use fresh or better evidence right
now -- read-only, $0, no provider call. One adapter over signals that already exist: claims.freshness_status +
FRESHNESS_RULES (G5.1), knowledge.list_tensions (disagreement), knowledge.list_targets (open evidence gaps), and
decision_impact.decision_impact (plan_impact) -- so Continuous Research (this module), Source Capability routing
(SC3, folded in here via candidates.where_to_look) and the Morning Report / review-queue all read the SAME list
instead of three of them growing their own. No new table: a Research Need is a projection, recomputed on demand.

Kind, in priority order (mission §12's shared loop puts what would move the plan first):
  plan_impact_stale  -- a Claim the current plan cites (LP0/LP1) whose freshness verdict is stale/needs_refresh.
  disagreement        -- an open CONTRADICTION/NOVEL tension on a Claim (knowledge.list_tensions, not recomputed).
  open_target         -- an evidence target (project_evidence_targets) still open.
  weak_plan_cited      -- a Claim the plan cites whose evidence strength is weak/unsupported (not yet a tension).

A Claim in an age-insensitive freshness class (experiential, historical, static -- FRESHNESS_RULES with both
thresholds None) never becomes a need by age alone: claims.freshness_status already reports those as
"age_insensitive", never "stale"/"needs_refresh", so they simply do not match plan_impact_stale here. They can
still surface via disagreement or open_target, same as any other Claim.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import candidates, claims, db, decision_impact, knowledge, usage

KIND_ORDER = {"plan_impact_stale": 0, "disagreement": 1, "open_target": 2, "weak_plan_cited": 3}
STALE_FRESHNESS = {"stale", "needs_refresh"}
WEAK_STRENGTH = {"weak", "unsupported"}
INACTIVE_CLAIM_STATUS = {"rejected", "superseded"}
DUE_ORDER = {"critical": 0, "worth_checking": 1, "low": 2}
CHECK_TTL_S = 12 * 3600  # CR2: don't resurface the same need within one nightly window, even if budget remains
UNTAPPED_STATES = ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost")


def _route(project_id: str, question: str, preferred_classes: list[str] | None) -> list[dict[str, Any]]:
    """SC3: the existing $0 "where to look" router, unchanged -- folded in here rather than built twice."""
    try:
        target = {"question": question, "preferred_classes": preferred_classes or []}
        return candidates.where_to_look(project_id, target=target, limit=3)["rows"]
    except Exception:  # noqa: BLE001 -- routing is an annotation; a need is still real without a suggested place to look
        return []


def for_project(project_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Ranked Research Needs, one per (Claim or open target), each naming a real reason. Never a score, never an
    LLM call -- callers sort further or filter as they see fit; this only reports what is actually true."""
    active = [c for c in claims.list_for_project(project_id, with_evidence=False) if c.get("status") not in INACTIVE_CLAIM_STATUS]
    by_id = {c["id"]: c for c in active}
    impact = decision_impact.decision_impact(project_id, [c["id"] for c in active]) if active else {}
    tensions = {t["claim_id"]: t for t in knowledge.list_tensions(project_id, status="open") if t.get("claim_id")}

    seen: set[str] = set()
    needs: list[dict[str, Any]] = []

    for c in active:
        cid = c["id"]
        if impact.get(cid, {}).get("plan_impact") is True and c.get("freshness_status") in STALE_FRESHNESS:
            needs.append({"kind": "plan_impact_stale", "claim_id": cid, "topic": c.get("topic"), "text": c.get("text"),
                         "reason": f"cited in the current plan; freshness is {c.get('freshness_status')}"
                                   + (f" — {c['freshness_why']}" if c.get("freshness_why") else ""),
                         "preferred_classes": [], "question": c.get("text")})
            seen.add(cid)

    for cid, t in tensions.items():
        c = by_id.get(cid)
        if not c or cid in seen:
            continue
        needs.append({"kind": "disagreement", "claim_id": cid, "topic": c.get("topic"), "text": c.get("text"),
                     "reason": f"open {(t.get('kind') or 'tension').lower()}" + (f": {t['description']}" if t.get("description") else ""),
                     "preferred_classes": [], "question": c.get("text"), "impact": t.get("impact")})
        seen.add(cid)

    for tg in knowledge.list_targets(project_id, status="open"):
        needs.append({"kind": "open_target", "target_id": tg["id"], "claim_id": tg.get("claim_id"), "topic": tg.get("topic"),
                     "text": tg.get("question"), "reason": "evidence target still open" + (f" — {tg['gap']}" if tg.get("gap") else ""),
                     "preferred_classes": tg.get("preferred_classes") or [], "question": tg.get("question"),
                     "sufficiency": tg.get("sufficiency")})

    for c in active:
        cid = c["id"]
        if cid in seen:
            continue
        if impact.get(cid, {}).get("plan_impact") is True and c.get("strength") in WEAK_STRENGTH:
            needs.append({"kind": "weak_plan_cited", "claim_id": cid, "topic": c.get("topic"), "text": c.get("text"),
                         "reason": f"cited in the current plan; evidence strength is {c.get('strength')}"
                                   + (f" — {c['strength_why']}" if c.get("strength_why") else ""),
                         "preferred_classes": [], "question": c.get("text")})
            seen.add(cid)

    needs.sort(key=lambda n: KIND_ORDER.get(n["kind"], 9))
    needs = needs[:max(1, limit)]
    for n in needs:
        n["where_to_look"] = _route(project_id, n.get("question") or n.get("text") or "", n.get("preferred_classes"))
    return needs


# ------------------------------------------------------------- CR2: due policy


def _category(n: dict[str, Any]) -> str:
    """Categories, not a fake score (mission §12 ruling). freshness_status x consequence, read straight off the
    need's own recorded fields -- never re-parsed from its human-readable `reason` string."""
    kind = n["kind"]
    if kind == "plan_impact_stale":
        return "critical"
    if kind == "disagreement":
        return "critical" if n.get("impact") == "high" else "worth_checking"
    if kind == "weak_plan_cited":
        return "worth_checking"
    if kind == "open_target":
        return "worth_checking" if n.get("sufficiency") == "governing" else "low"
    return "low"


def _cost_estimate_for_creator(project_id: str, creator: str) -> tuple[float, str]:
    """Best $0 cost estimate for the next unread item from this creator. A real untapped candidate's own duration
    (when one is known) is exact enough to price with usage.estimate_video directly -- candidates are pre-ingest,
    so there is no source_id yet for usage.estimate_source_findings to key off. Falls back to this project's own
    average findings cost, then a generic estimate, always naming which basis was used -- never false precision,
    and never an actual spend: CR5 re-estimates against the real chosen source before spending anything."""
    for state in UNTAPPED_STATES:
        rows = [c for c in candidates.list_for_project(project_id, state=state, limit=200)
               if (c.get("creator") or "").strip() == creator and c.get("duration")]
        if rows:
            mins = int((rows[0]["duration"] or 0) / 60)
            return usage.estimate_video(rows[0]["duration"])["analyse"], f"a specific untapped item from {creator} (~{mins} min)"
    row = db.connect().execute("SELECT AVG(cost) c FROM usage WHERE project_id=? AND kind='findings'", (project_id,)).fetchone()
    avg = float(row["c"]) if row and row["c"] else None
    if avg:
        return avg, "this project's own average findings cost (no specific untapped item resolved)"
    return usage.estimate_findings(4000), "a generic ~4000-char findings pass (no untapped item and no cost history yet)"


def due_tonight(project_id: str, needs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """CR2: which of CR1's Research Needs are worth checking tonight, in ranked categories with an estimated
    (never spent) cost. A need already surfaced within CHECK_TTL_S is skipped even if budget remains -- recorded
    in the existing kv store, no new table."""
    needs = for_project(project_id) if needs is None else needs
    out: list[dict[str, Any]] = []
    for n in needs:
        key = f"{n['kind']}:{n.get('claim_id') or n.get('target_id')}"
        raw = db.kv_get(f"research:checked:{key}")
        if raw:
            try:
                checked = json.loads(raw)
            except ValueError:
                checked = {}
            if time.time() - float(checked.get("ts") or 0) < CHECK_TTL_S:
                continue
        category = _category(n)
        creator = ((n.get("where_to_look") or [{}])[0] or {}).get("creator")
        if creator:
            cost, basis = _cost_estimate_for_creator(project_id, creator)
        else:
            cost, basis = usage.estimate_findings(4000), "no untapped creator resolved for this need"
        out.append({**n, "due_category": category, "estimated_cost_usd": round(cost, 4), "cost_basis": basis})
        db.kv_set(f"research:checked:{key}", json.dumps({"ts": time.time(), "category": category}))
    out.sort(key=lambda x: DUE_ORDER.get(x["due_category"], 9))
    return out
