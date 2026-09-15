"""Decision Impact v1 (PRODUCT-INTELLIGENCE-MISSION.md + CTO rulings §6): "which findings/claims matter enough
to interrupt Kyle." Ruling §6 is explicit: no six-factor LLM score, no novelty/irreversibility/freshness/
confidence guesswork. Exactly two REAL, deterministic signals for v1 -- everything else reports "unknown", never
a fabricated number.

  1. disagreement: an open CONTRADICTION/NOVEL tension in research_tensions touches this Claim (the exact query
     `knowledge.py`'s own evidence-target satisfaction check already uses -- not a new signal, a reused one).
  2. plan_impact: is this Claim cited (via its folded-in Findings) anywhere in the CURRENT plan's evidence.

Read-only, $0, no provider call -- same discipline as t4.source_relevance and t1.coverage_view.

**plan_impact's real limitation, worth stating plainly**: a plan's evidence citations (`"evidence": ["F3", ...]`
in plans.plan JSON, see planner.py's ANALYSIS_SCHEMA) are labels assigned by `planner._evidence()` at BUILD time
from the live ordering of `db.list_project_notes()` -- they are not stored against a stable note id anywhere.
Re-deriving the same labels later only reproduces the same mapping if the project's notes haven't changed since
the plan was built. This module checks that cheaply (plan snapshot's note count vs the current count) and
reports `plan_impact: "unknown"` for every claim rather than guess when they differ -- the mission's own honesty
rule (T1/T2/T4 all already do this: unavailable is reported as unavailable, never as a false negative).
"""
from __future__ import annotations

from typing import Any

from . import db


def _walk_evidence_ids(node: Any, out: set[str]) -> None:
    """Recursively collect every string under an "evidence" key anywhere in a plan JSON tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "evidence" and isinstance(v, list):
                out.update(x for x in v if isinstance(x, str))
            else:
                _walk_evidence_ids(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_evidence_ids(item, out)


def _plan_cited_note_ids(project_id: str) -> set[int] | None:
    """Note ids cited (as "F<n>") anywhere in the latest plan's evidence arrays, or None if there's no plan and
    nothing can be resolved at all.

    LP0 (mission §12): planner._evidence() now records each F<n>'s real note_id in the plan's own frozen `_evidence`
    map at build time (plan["plan"]["_evidence"][fid]["note_id"]) -- that mapping is stable forever, regardless of
    what happens to the project's notes afterwards. Prefer it. Only for an OLDER plan, built before this seam
    existed, do we fall back to re-deriving the mapping from the CURRENT note ordering -- and only when the note
    count still matches what the plan was built against, exactly as before."""
    plan = db.latest_plan(project_id)
    if not plan:
        return None
    cited: set[str] = set()
    _walk_evidence_ids(plan.get("plan"), cited)
    fids = {c for c in cited if c.startswith("F")}
    if not fids:
        return set()

    emap = (plan.get("plan") or {}).get("_evidence") or {}
    from_emap = {emap[f]["note_id"] for f in fids if isinstance(emap.get(f), dict) and emap[f].get("note_id") is not None}
    missing = {f for f in fids if not (isinstance(emap.get(f), dict) and emap[f].get("note_id") is not None)}
    if not missing:
        return from_emap  # every citation resolved from the plan's own frozen record -- no re-derivation needed

    current_notes = db.list_project_notes(project_id)
    if plan.get("snapshot", {}).get("notes") != len(current_notes):
        # can't safely re-derive the rest; report what the emap DOES know rather than discarding it
        return from_emap if from_emap else None

    # Reproduce planner._evidence()'s exact F<n> numbering: sequential over reversed(list_project_notes()).
    fid_to_note_id = {f"F{i + 1}": n["id"] for i, n in enumerate(reversed(current_notes))}
    return from_emap | {fid_to_note_id[f] for f in missing if f in fid_to_note_id}


def decision_impact(project_id: str, claim_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """{claim_id: {"disagreement": bool, "plan_impact": bool | "unknown"}} for every non-rejected Claim in the
    project (or just `claim_ids`, if given). Never a score, never a rank -- callers combine or sort as they see
    fit; this only reports what is actually known."""
    conn = db.connect()
    if claim_ids is None:
        claim_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM project_claims WHERE project_id=? AND status<>'rejected'", (project_id,)).fetchall()]
    if not claim_ids:
        return {}

    marks = ",".join("?" for _ in claim_ids)
    disagreeing = {r["claim_id"] for r in conn.execute(
        f"SELECT DISTINCT claim_id FROM research_tensions WHERE claim_id IN ({marks}) "
        f"AND status='open' AND kind IN ('CONTRADICTION','NOVEL')", claim_ids).fetchall()}

    cited_note_ids = _plan_cited_note_ids(project_id)
    if cited_note_ids is None:
        plan_impact = {cid: "unknown" for cid in claim_ids}
    else:
        claim_note_ids: dict[str, set[int]] = {}
        for r in conn.execute(f"SELECT claim_id, note_id FROM claim_evidence_notes WHERE claim_id IN ({marks})", claim_ids).fetchall():
            claim_note_ids.setdefault(r["claim_id"], set()).add(r["note_id"])
        plan_impact = {cid: bool(claim_note_ids.get(cid, set()) & cited_note_ids) for cid in claim_ids}

    return {cid: {"disagreement": cid in disagreeing, "plan_impact": plan_impact[cid]} for cid in claim_ids}
