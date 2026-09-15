"""AD4A — Adaptive Discovery outcome measurement (2026-09-15). $0, read-only, deterministic, no model call, no new
schema, no new telemetry, project-scoped, following `cost_value.py`'s own reporting discipline (reconciling
counts, an honest denominator, "zero is a valid result," never a stand-in for evidence that was not observed).

Kept in its OWN module rather than folded into `cost_value.py`: `cost_value` answers "did the money buy anything"
-- its counts are spend-attributed and every unit divides a dollar figure. This report has no dollar dimension at
all; it answers "is the Candidate Index / Adaptive Discovery loop actually producing useful research," purely from
`candidate_projects` / `candidates` / `project_notes` / `project_claims` / `candidate_links` state. Forcing it into
`cost_value` would mean either inventing a cost for it or breaking that module's own "cost / count" contract for
one section -- a second small file with the same discipline is cleaner than bending the first one's shape.

THE ONE THING THIS REPORT DOES NOT AND CANNOT DO (AD4 decision, 2026-09-15): claim that static ranking would have
produced a different capture rate than Adaptive Discovery did. AD1/AD2/AD3 do not persist `base_potential`,
`exploratory`, batch membership, served rank, or the candidates a batch's diversity cap deferred past the top N --
so there is no durable record of what the user was ever SHOWN, only what they eventually DECIDED. A user cannot be
said to have rejected a candidate that a batch never surfaced, and re-running today's ranking algorithm against
today's pool is not evidence of what an earlier batch actually contained. This module measures how the system
that shipped is actually performing (AD4A); it never manufactures the static-ranking counterfactual (AD4B, and
explicitly Kyle-gated / future evidence -- see EXECUTION-LADDER.md and HANDOFF.md).

Similarly, AD3's `exploratory` flag is never persisted, by design (AD3: "not a DB column... no telemetry"), so
this report cannot isolate "did the exploration slot specifically help" -- only whether Adaptive Discovery as a
whole (rerank + exploration together) is producing useful research at an acceptable review cost. That is
consistent with AD3's own decision, not a gap this module should quietly work around.
"""
from __future__ import annotations

import time
from typing import Any

from . import candidates, db
from .cost_value import window_start  # reused, not rebuilt -- same window semantics `cost_value` already uses

# "Genuine candidate decisions" (Kyle's AD4 spec, §4A): only states that represent an actual keep/reject judgment
# on a specific candidate. This is the EXACT set AD2's own `creator_disposition` already treats as preference-
# bearing -- reused directly rather than redefined, so the two reports can never quietly disagree about what
# counts as a decision. `skipped_limit` / `skipped_cost` / `duplicate` are operational (a review cap, a budget
# ceiling, an identity collision) and must never be read as "the user didn't want this."
DECISION_STATES = candidates.DISPOSITION_STATES        # ("acquired", "user_dismissed", "skipped_low_relevance")
OPERATIONAL_SKIP_STATES = ("skipped_limit", "skipped_cost", "duplicate")

# Evidence-sufficiency guards -- NOT a statistical significance claim, just an honesty floor so a report built on
# 3 decisions cannot read as confident as one built on 300. Simple, documented, arbitrary-and-said-so, same spirit
# as `candidates.DISPOSITION_MIN_DECISIONS` (3 decided = the floor before ANY signal is trusted at all) and
# `candidates.CREATOR_MIN_SOURCES` (one data point proves nothing).
THIN_SAMPLE_MIN = 1     # fewer than this and there is nothing to describe at all
USABLE_SAMPLE_MIN = 15  # fewer than this and the report calls itself a thin sample, on purpose


def _candidate_decisions(project_id: str) -> dict[str, Any]:
    """Genuine decisions (`DECISION_STATES`) vs. operational skips vs. the still-undecided pool, kept in three
    separate buckets so a capture rate is never computed against a denominator an operational skip inflated."""
    conn = db.connect()
    rows = conn.execute("SELECT state, COUNT(*) n FROM candidate_projects WHERE project_id=? GROUP BY state",
                        (project_id,)).fetchall()
    by_state = {r["state"]: int(r["n"]) for r in rows}
    decided = {s: by_state.get(s, 0) for s in DECISION_STATES}
    decided_total = sum(decided.values())
    acquired = decided.get("acquired", 0)
    if decided_total > 0:
        capture_rate, capture_rate_unavailable = round(acquired / decided_total, 4), None
    else:
        capture_rate, capture_rate_unavailable = None, "no genuine candidate decisions yet"
    return {
        "by_state": decided, "decided_total": decided_total, "acquired": acquired,
        "capture_rate": capture_rate, "capture_rate_unavailable": capture_rate_unavailable,
        "operational_skips": {s: by_state.get(s, 0) for s in OPERATIONAL_SKIP_STATES},
        "unresolved_pool": by_state.get("available", 0),
    }


def _acquired_source_ids(project_id: str) -> dict[str, Any]:
    """Sources the Candidate Index actually resolved to, split by how far each has gotten -- acquiring a
    candidate enqueues an ingest job (`candidates.capture`); it does not mean the job finished, and a finished
    job does not mean any finding has been written yet. Assuming otherwise would count "acquired" as "evaluated,"
    which Kyle's spec explicitly forbids (§4B)."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT c.id cid, c.source_id sid, c.creator creator, cp.updated_at acquired_at
           FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id
           WHERE cp.project_id=? AND cp.state='acquired'""", (project_id,)).fetchall()
    not_resolved: list[str] = []      # acquired, but the candidate never got a source_id (job never finished / failed)
    ready: dict[str, dict[str, Any]] = {}       # source_id -> {creator, acquired_at}
    ingest_incomplete: list[str] = []
    for r in rows:
        if not r["sid"]:
            not_resolved.append(r["cid"])
            continue
        s = db.get_source(r["sid"])
        if not s or s.get("status") != "ready":
            ingest_incomplete.append(r["sid"])
            continue
        ready[r["sid"]] = {"creator": (r["creator"] or "").strip(), "acquired_at": r["acquired_at"]}
    return {"total_acquired": len(rows), "not_yet_resolved": len(not_resolved),
            "ingest_incomplete": len(ingest_incomplete), "ready": ready}


def _findings_for_sources(project_id: str, source_ids: list[str]) -> dict[str, Any]:
    """Finding status distribution for a specific, named set of sources -- never "everything in the project,"
    so provenance stays honest. `model IS NOT NULL` is `cost_value`'s own test for a machine-written finding
    (as opposed to a note pinned by hand), reused here for the same reason."""
    if not source_ids:
        return {"by_status": {}, "total": 0, "sources_with_findings": 0, "sources_with_no_findings_yet": 0}
    conn = db.connect()
    ph = ",".join("?" * len(source_ids))
    rows = conn.execute(
        f"SELECT source_id, status, COUNT(*) n FROM project_notes "
        f"WHERE project_id=? AND model IS NOT NULL AND source_id IN ({ph}) GROUP BY source_id, status",
        (project_id, *source_ids)).fetchall()
    by_status: dict[str, int] = {}
    with_findings: set[str] = set()
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + int(r["n"])
        with_findings.add(r["source_id"])
    return {"by_status": by_status, "total": sum(by_status.values()),
            "sources_with_findings": len(with_findings),
            "sources_with_no_findings_yet": len(source_ids) - len(with_findings)}


def _claims_for_sources(project_id: str, source_ids: list[str]) -> dict[str, Any]:
    """Claim status distribution traced through `project_claims.origin_note_id -> project_notes.source_id`, so a
    Claim only counts here when its own provenance actually runs through one of these sources -- never "every
    Claim in the project," and never "caused by" language the provenance doesn't support."""
    if not source_ids:
        return {"by_status": {}, "total": 0}
    conn = db.connect()
    ph = ",".join("?" * len(source_ids))
    rows = conn.execute(
        f"""SELECT pc.status st, COUNT(*) n FROM project_claims pc
           JOIN project_notes pn ON pn.id = pc.origin_note_id
           WHERE pc.project_id=? AND pn.source_id IN ({ph}) GROUP BY pc.status""",
        (project_id, *source_ids)).fetchall()
    by_status = {r["st"]: int(r["n"]) for r in rows}
    return {"by_status": by_status, "total": sum(by_status.values())}


def _evidence_targets(project_id: str, candidate_ids: list[str]) -> dict[str, Any]:
    """Reuses the exact `candidate_links` semantics SC0b's `targets_helped` and AD2's `_stale_linked_targets`
    already read (`kind='evidence_target'`, `state in open|satisfied|dismissed`) -- not a new join, not a new
    interpretation of what a link means. Two different counts on purpose: raw link ROWS (a candidate can carry
    more than one target link) vs. DISTINCT targets, so nothing is silently double-counted as "targets helped"
    when it is really "link rows," per Kyle's §4D instruction."""
    if not candidate_ids:
        return {"links": {"open": 0, "satisfied": 0, "dismissed": 0}, "distinct_targets_satisfied": 0}
    conn = db.connect()
    ph = ",".join("?" * len(candidate_ids))
    rows = conn.execute(
        f"SELECT state, ref_id FROM candidate_links WHERE project_id=? AND kind='evidence_target' "
        f"AND candidate_id IN ({ph})", (project_id, *candidate_ids)).fetchall()
    links = {"open": 0, "satisfied": 0, "dismissed": 0}
    satisfied_targets: set[str] = set()
    for r in rows:
        if r["state"] in links:
            links[r["state"]] += 1
        if r["state"] == "satisfied":
            satisfied_targets.add(r["ref_id"])
    return {"links": links, "distinct_targets_satisfied": len(satisfied_targets)}


def _novel_creators(project_id: str, start: float) -> dict[str, Any]:
    """Creators whose FIRST acquisition through the Candidate Index (by `candidate_projects.updated_at` at the
    moment `state` became `acquired`) falls inside this window -- project-scoped only, never a global novelty
    score (G4's own rule: nothing here is built from more than one project's data)."""
    conn = db.connect()
    rows = conn.execute(
        """SELECT c.creator creator, MIN(cp.updated_at) first_acquired
           FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id
           WHERE cp.project_id=? AND cp.state='acquired' AND c.creator IS NOT NULL AND TRIM(c.creator) != ''
           GROUP BY c.creator""", (project_id,)).fetchall()
    novel = sorted([r["creator"] for r in rows if r["first_acquired"] >= start])
    return {"count": len(novel), "creators": novel[:50]}


def _sufficiency(decided_total: int) -> dict[str, Any]:
    if decided_total < THIN_SAMPLE_MIN:
        category = "no_usage"
        note = "No genuine candidate decisions recorded yet -- Adaptive Discovery has not been used on this project."
    elif decided_total < USABLE_SAMPLE_MIN:
        category = "thin_sample"
        note = (f"Only {decided_total} genuine candidate decision(s) so far (usable sample starts at "
                f"{USABLE_SAMPLE_MIN}). The numbers below describe what happened, not a settled pattern.")
    else:
        category = "usable_sample"
        note = f"{decided_total} genuine candidate decisions -- enough to describe a real pattern of use."
    return {"category": category, "decided_total": decided_total, "thin_sample_min": THIN_SAMPLE_MIN,
            "usable_sample_min": USABLE_SAMPLE_MIN, "note": note}


def _verdict(sufficiency: dict[str, Any], decisions: dict[str, Any]) -> str:
    if sufficiency["category"] == "no_usage":
        return "Not enough real usage yet to judge Adaptive Discovery."
    if sufficiency["category"] == "thin_sample":
        return ("Too little usage yet for a real verdict -- descriptive numbers only. No static-vs-adaptive "
                "conclusion is possible from this report; see AD4B.")
    rate = decisions["capture_rate"]
    rate_txt = f"a {rate:.0%} capture rate" if rate is not None else "an undetermined capture rate"
    return (f"Adaptive Discovery has produced {rate_txt} over {decisions['decided_total']} genuine decisions. "
            "This describes the system as it actually performed -- it is NOT a comparison against static "
            "ranking, which was never shown to the user and cannot be reconstructed from current state. See "
            "AD4B for whether that comparison is ever built.")


def report(project_id: str, window: str = "all", days: int | None = None) -> dict[str, Any]:
    """AD4A. Everything here is read-only and reconciles against durable state: `decided_total` in `usage` is the
    same number `evidence_sufficiency` grades, `research_value`'s source counts are the same set `cohort_comparison`
    partitions the project's sources by. No write, no model call, no new table."""
    start = window_start(window, days)
    decisions = _candidate_decisions(project_id)

    acquired = _acquired_source_ids(project_id)
    ready_ids = list(acquired["ready"].keys())
    findings = _findings_for_sources(project_id, ready_ids)
    claims = _claims_for_sources(project_id, ready_ids)

    conn = db.connect()
    acquired_candidate_ids = [r["cid"] for r in conn.execute(
        "SELECT c.id cid FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state='acquired'", (project_id,)).fetchall()]
    targets = _evidence_targets(project_id, acquired_candidate_ids)
    novel = _novel_creators(project_id, start)

    all_project_sources = set(db.project_source_ids(project_id, ready_only=False))
    other_source_ids = sorted(all_project_sources - set(ready_ids))
    other_findings = _findings_for_sources(project_id, other_source_ids)
    other_claims = _claims_for_sources(project_id, other_source_ids)

    denom = decisions["decided_total"]
    acquired_n = decisions["acquired"]
    review_burden = {
        "decisions_per_acquisition": round(denom / acquired_n, 2) if acquired_n else None,
        "rejection_rate": round((denom - acquired_n) / denom, 4) if denom else None,
        "low_relevance_rate": (round(decisions["by_state"].get("skipped_low_relevance", 0) / denom, 4)
                               if denom else None),
        "unresolved_pool_size": decisions["unresolved_pool"],
    }

    sufficiency = _sufficiency(denom)

    return {
        "project_id": project_id, "generated_at": time.time(), "window": {"kind": window, "start": start},
        "usage": {
            "candidate_decisions": decisions["by_state"], "decided_total": denom,
            "capture_rate": decisions["capture_rate"], "capture_rate_unavailable": decisions["capture_rate_unavailable"],
            "operational_skips": decisions["operational_skips"], "unresolved_pool": decisions["unresolved_pool"],
        },
        "research_value": {
            "acquired_sources": {"total_acquired_candidates": acquired["total_acquired"],
                                 "not_yet_resolved": acquired["not_yet_resolved"],
                                 "ingest_incomplete": acquired["ingest_incomplete"], "ready": len(ready_ids)},
            "findings": findings, "claims": claims,
            "evidence_targets": {"source_target_links": targets["links"],
                                 "distinct_targets_satisfied": targets["distinct_targets_satisfied"]},
        },
        "breadth": {"novel_creators_in_window": novel["count"], "novel_creators": novel["creators"]},
        "review_burden": review_burden,
        "cohort_comparison": {
            "explain": ("Are sources acquired through the Candidate Index producing useful downstream research, "
                       "compared with sources this project acquired some other way? This is NOT a comparison "
                       "against a static-ranking counterfactual -- the other-path cohort was never ranked by "
                       "Adaptive Discovery at all, it is simply everything else in the project."),
            "candidate_index": {"source_count": len(ready_ids), "findings": findings, "claims": claims},
            "other_paths": {"source_count": len(other_source_ids), "findings": other_findings, "claims": other_claims},
        },
        "evidence_sufficiency": sufficiency,
        "verdict": _verdict(sufficiency, decisions),
        "notes": (
            "No static-ranking counterfactual is computed or implied anywhere in this report -- AD1/AD2/AD3 "
            "persist no record of what a batch showed or omitted, so 'would static ranking have done better' is "
            "not answerable from current state. See AD4B.",
            "'exploratory' candidates are not tracked separately (AD3 deliberately does not persist that flag), "
            "so this report cannot isolate the exploration slot's own contribution -- only Adaptive Discovery as "
            "a whole.",
            "'Ready' sources are findings-eligible; 'not yet resolved' / 'ingest incomplete' acquisitions are "
            "real acquisitions whose downstream value simply cannot be judged yet, and are reported as such "
            "rather than silently excluded or counted as zero-yield.",
        ),
    }
