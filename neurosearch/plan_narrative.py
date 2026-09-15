"""LP2 (mission §12, EXECUTION-LADDER.md Stage 11): plain-language WHY, templated over LP1's deterministic WHERE.
No model call, no new table -- this only turns plan_impact.affected_items's structured result into one sentence
per affected item, naming the step, how directly it depends on the Claim (indicated vs. possible, unchanged from
LP1), and what actually changed about the evidence behind it. Kept as its own module rather than folded into
plan_impact.py: LP1 is the deterministic citation walker, this is a templating layer over it -- mission §12's
"thin shared seams" rule argues against merging a templating concern into the module that owns the walk."""
from __future__ import annotations

from typing import Any

from . import claims, db, plan_impact


def _claim_summary(claim_id: str) -> dict[str, Any] | None:
    c = claims.get(claim_id)
    if not c:
        return None
    return {"text": c.get("text"), "freshness_status": c.get("freshness_status"), "strength": c.get("strength")}


def _condition(claim: dict[str, Any] | None) -> str:
    if not claim:
        return "this claim is under review"
    if claim.get("freshness_status") in ("stale", "needs_refresh"):
        return f"evidence is {claim['freshness_status'].replace('_', ' ')}"
    if claim.get("strength") in ("weak", "unsupported"):
        return f"evidence strength is {claim['strength']}"
    return "the evidence behind it has changed"


def _why(label: str | None, strength: str, claim: dict[str, Any] | None) -> str:
    what = (claim or {}).get("text") or "a claim"
    what = what if len(what) <= 100 else what[:99] + "…"
    relation = "directly relies on it" if strength == "indicated" else "relies on a claim it absorbed via merge"
    return f'"{label or "this step"}" cites {what}, and {_condition(claim)} — {relation}.'


def explain(project_id: str, claim_id: str | None = None, tension_id: str | None = None) -> dict[str, Any]:
    """{"known": bool, "items": [...LP1's shape, plus "why": str], "reason"?: str} -- a strict superset of LP1's
    result, so a caller that only wants the deterministic WHERE can ignore the extra key."""
    r = plan_impact.affected_items(project_id, claim_id=claim_id, tension_id=tension_id)
    if not r["known"]:
        return r
    resolved = claim_id
    if not resolved and tension_id:
        row = db.connect().execute("SELECT claim_id FROM research_tensions WHERE id=?", (tension_id,)).fetchone()
        resolved = row["claim_id"] if row else None
    claim = _claim_summary(resolved) if resolved else None
    items = [{**it, "why": _why(it.get("label"), it["strength"], claim)} for it in r["items"]]
    return {"known": True, "items": items}



def _instruction(strength: str, condition: str) -> str:
    if "stale" in condition or "needs refresh" in condition:
        return "re-verify against current evidence before relying on this" if strength == "indicated" else \
               "review — evidence for this step was merged from a claim whose freshness is now in question"
    if "weak" in condition or "unsupported" in condition:
        return "strengthen the evidence before relying on this" if strength == "indicated" else \
               "review — evidence for this step was merged from a claim that no longer stands alone"
    return "review — the evidence behind this step has changed"


def propose_updates(project_id: str, claim_id: str | None = None, tension_id: str | None = None) -> list[dict[str, Any]]:
    """LP3: write one pending `plan_updates` row per plan item LP2 finds affected, `origin='lp3'` so this never
    collides with the existing LLM-based suggest_updates() queue on the same plan (db.add_plan_updates scopes its
    clear-before-insert by origin). $0, deterministic, templated -- never a model call, never auto-accepted: the
    existing accept/reject route (`POST /api/plan-updates/{id}`) is the only thing that promotes a row, unchanged.
    Returns [] (writing nothing) when LP1/LP2 cannot resolve the citation -- never a guessed patch."""
    r = explain(project_id, claim_id=claim_id, tension_id=tension_id)
    if not r.get("known") or not r.get("items"):
        return []
    plan = db.latest_plan(project_id)
    updates = [{"section": it["path"], "previous": it.get("label"),
               "proposed": _instruction(it["strength"], it["why"]), "reason": it["why"]} for it in r["items"]]
    db.add_plan_updates(plan["id"], updates, origin="lp3")
    return [u for u in db.get_plan(plan["id"])["updates"] if u.get("origin") == "lp3" and u.get("status") == "pending"]
