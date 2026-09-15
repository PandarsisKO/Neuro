"""LP4 (mission §12, EXECUTION-LADDER.md Stage 11): a plan item's evidence-CONFIDENCE state, derived on read from
what already exists -- LP1's citation resolution, Claim strength/freshness, decision_impact's disagreement
signal, and the plan's own `dependencies`/`basis` fields. This is a DIFFERENT axis from `plan_items.status` (the
existing user-facing execution progress: not_started/ready/done) and never reads or writes it -- persists
nothing, by the rung's own gate, unless a real project proves the derive-on-read cost matters.

States, in the precedence order used when more than one would apply (most actionable first):
  blocked   -- the plan's own dependencies name this item as blocking (token overlap with a `blocking: true` entry).
  monitored -- the item's cited Claim has an open disagreement (decision_impact.disagreement).
  uncertain -- the item's cited Claim is stale/needs_refresh or weak/unsupported (the same condition CR1 calls a
               Research Need -- reused, not re-derived).
  known     -- the item's cited Claim is current and strong/developing.
  chosen    -- a decision/tool item whose own `basis` is "research" or "user" (a deliberate, grounded choice).
  assumed   -- a decision/tool item whose own `basis` is "planner" or "estimate".
An item with no resolvable evidence and no usable `basis` is left unclassified -- never guessed.
"""
from __future__ import annotations

from typing import Any

from . import claims, db, decision_impact, plan_impact

STATES = ("blocked", "monitored", "uncertain", "known", "chosen", "assumed")
STALE_FRESHNESS = {"stale", "needs_refresh"}
WEAK_STRENGTH = {"weak", "unsupported"}
GROUNDED_BASIS = {"research", "user"}
ASSUMED_BASIS = {"planner", "estimate"}
LIST_SECTIONS = ("first_steps", "decisions", "tools")


def _blocked_terms(plan: dict[str, Any]) -> frozenset[str]:
    terms: set[str] = set()
    for d in plan.get("dependencies") or []:
        if d.get("blocking"):
            terms |= claims._tokens(d.get("item") or "")
    return frozenset(terms)


def _item_label(item: dict[str, Any]) -> str | None:
    return item.get("action") or item.get("decision") or item.get("need") or item.get("tool")


def _claim_state(claim_id: str, disagreeing: set[str]) -> str | None:
    c = claims.get(claim_id)
    if not c:
        return None
    if claim_id in disagreeing:
        return "monitored"
    if c.get("freshness_status") in STALE_FRESHNESS or c.get("strength") in WEAK_STRENGTH:
        return "uncertain"
    if c.get("strength") in ("strong", "developing"):
        return "known"
    return None


def derive(project_id: str) -> dict[str, dict[str, Any]]:
    """{key: {"state": str, "why": str}} for every keyed plan item LP1/basis can resolve. Read-only, $0, no
    provider call, nothing persisted."""
    plan = db.latest_plan(project_id)
    if not plan:
        return {}
    p = plan.get("plan") or {}
    blocked_terms = _blocked_terms(p)

    # every Claim any cited Finding could belong to, resolved once via LP1's own citation walk over the whole
    # plan (loop per distinct claim rather than a new batch primitive -- there is no per-plan Claim list to walk
    # without one, and this keeps LP4 a pure consumer of LP1 rather than a second citation-resolution path)
    all_claims = [c["id"] for c in claims.list_for_project(project_id, with_evidence=False) if c.get("status") not in ("rejected", "superseded")]
    disagreeing = {cid for cid, sig in decision_impact.decision_impact(project_id, all_claims).items() if sig.get("disagreement")}

    claim_to_paths: dict[str, list[str]] = {}
    for cid in all_claims:
        r = plan_impact.affected_items(project_id, claim_id=cid)
        if r.get("known"):
            for it in r["items"]:
                claim_to_paths.setdefault(cid, []).append(it["path"])

    path_to_claim: dict[str, str] = {}
    for cid, paths in claim_to_paths.items():
        for path in paths:
            path_to_claim.setdefault(path, cid)   # first claim to claim a path wins; ties are rare and informational only

    out: dict[str, dict[str, Any]] = {}

    def classify(key: str, item: dict[str, Any]) -> None:
        label = _item_label(item) if isinstance(item, dict) else None
        if label and claims._tokens(label) & blocked_terms:
            out[key] = {"state": "blocked", "why": "named as a blocking dependency in the plan"}
            return
        claim_id = path_to_claim.get(key)
        if claim_id:
            state = _claim_state(claim_id, disagreeing)
            if state:
                out[key] = {"state": state, "why": f"cites claim {claim_id}", "claim_id": claim_id}
                return
        basis = (item or {}).get("basis") if isinstance(item, dict) else None
        if basis in GROUNDED_BASIS:
            out[key] = {"state": "chosen", "why": f"basis: {basis}"}
        elif basis in ASSUMED_BASIS:
            out[key] = {"state": "assumed", "why": f"basis: {basis}"}

    for section in LIST_SECTIONS:
        for i, item in enumerate(p.get(section) or []):
            classify(f"{section}.{i}", item)
    if p.get("costs"):
        classify("costs", p["costs"])
    return out
