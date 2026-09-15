"""LP1 (mission §12, EXECUTION-LADDER.md Stage 11): which plan items would be affected if a Claim (or the tension
on it) changes. Built entirely on LP0's plan-evidence note_id seam (planner._evidence's emap now records each
F<n>'s real note_id) plus decision_impact's existing citation resolver -- no new table, no LLM call, $0 and
read-only. When the seam can't resolve a citation (an older plan, built before this seam, whose note count has
since moved), this says so plainly: known: False, never a guess dressed up as an answer.

strength: "indicated" -- the plan item cites a Finding folded directly into this Claim.
          "possible"  -- the plan item cites a Finding folded into a Claim this Claim absorbed via merge
                         (superseded_by), so the citation is real but one hop removed.
"""
from __future__ import annotations

from typing import Any

from . import db
from .decision_impact import _plan_cited_note_ids, _walk_evidence_ids  # reuse the one citation walker/resolver

LIST_SECTIONS = ("first_steps", "decisions", "tools")  # list-shaped plan sections; costs is a single dict with its own evidence array


def _claim_note_ids(claim_id: str) -> set[int]:
    return {r["note_id"] for r in db.connect().execute(
        "SELECT note_id FROM claim_evidence_notes WHERE claim_id=?", (claim_id,)).fetchall()}


def _superseded_chain(claim_id: str) -> list[str]:
    """Claim ids merged INTO claim_id over time (superseded_by points from the old claim to the survivor, so walk
    backwards from claim_id to find everything that once pointed at it, transitively)."""
    conn = db.connect()
    out: list[str] = []
    seen = {claim_id}
    frontier = [claim_id]
    while frontier:
        cur = frontier.pop()
        for r in conn.execute("SELECT id FROM project_claims WHERE superseded_by=?", (cur,)).fetchall():
            if r["id"] not in seen:
                seen.add(r["id"])
                out.append(r["id"])
                frontier.append(r["id"])
    return out


def _label(item: dict[str, Any]) -> str | None:
    return item.get("action") or item.get("decision") or item.get("need") or item.get("tool")


def affected_items(project_id: str, claim_id: str | None = None, tension_id: str | None = None) -> dict[str, Any]:
    """{"known": bool, "items": [{"path", "label", "strength"}], "reason"?: str (only when known is False)}."""
    if tension_id and not claim_id:
        row = db.connect().execute("SELECT claim_id FROM research_tensions WHERE id=?", (tension_id,)).fetchone()
        claim_id = row["claim_id"] if row else None
    if not claim_id:
        return {"known": False, "items": [], "reason": "no claim to check impact for"}

    plan = db.latest_plan(project_id)
    if not plan:
        return {"known": False, "items": [], "reason": "no plan yet"}

    cited = _plan_cited_note_ids(project_id)
    if cited is None:
        return {"known": False, "items": [],
                "reason": "this plan's evidence citations cannot be safely mapped to notes (built before the "
                          "plan-evidence seam existed, and the project's notes have changed since)"}

    direct = _claim_note_ids(claim_id)
    possible: set[int] = set()
    for other in _superseded_chain(claim_id):
        possible |= _claim_note_ids(other)
    possible -= direct

    p = plan.get("plan") or {}
    emap = p.get("_evidence") or {}

    def note_for(fid: str) -> int | None:
        e = emap.get(fid)
        return e.get("note_id") if isinstance(e, dict) else None

    items: list[dict[str, Any]] = []

    def consider(path: str, label: str | None, fids: set[str]) -> None:
        note_ids = {n for n in (note_for(f) for f in fids) if n is not None}
        if not note_ids:
            return  # this citation predates the LP0 seam -- silently skip rather than fabricate a match
        if note_ids & direct:
            items.append({"path": path, "label": label, "strength": "indicated"})
        elif note_ids & possible:
            items.append({"path": path, "label": label, "strength": "possible"})

    for section in LIST_SECTIONS:
        for i, item in enumerate(p.get(section) or []):
            fids = {x for x in (item.get("evidence") or []) if isinstance(x, str) and x.startswith("F")}
            if fids:
                consider(f"{section}.{i}", _label(item), fids)

    costs_fids = {x for x in ((p.get("costs") or {}).get("evidence") or []) if isinstance(x, str) and x.startswith("F")}
    if costs_fids:
        consider("costs", "costs", costs_fids)

    return {"known": True, "items": items}
