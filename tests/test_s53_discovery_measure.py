"""S53 — AD4A: Adaptive Discovery outcome measurement (2026-09-15).

Kyle's AD4 decision was explicit that Option A (this report) must never manufacture a static-ranking
counterfactual: AD1/AD2/AD3 persist no record of what a batch showed or omitted, so nothing here may claim
"static ranking would have produced X." These tests instead prove the narrower, honest thing the report actually
does: reconcile real `candidate_projects`/`candidates`/`project_notes`/`project_claims`/`candidate_links` state
into a project-scoped, provenance-correct description of how Adaptive Discovery has actually performed, with an
explicit evidence-sufficiency guard so a three-decision project cannot read as a verdict.
"""
from __future__ import annotations

import time

import pytest

from neurosearch import candidates, db, discovery_measure


@pytest.fixture()
def two_projects(monkeypatch):
    db.init_db()
    a = db.create_project("AD4A project A", brief="buy an accounting practice with an SBA loan")["id"]
    b = db.create_project("AD4A project B", brief="unrelated second project")["id"]
    yield a, b


def _source(ext, *, status="ready"):
    s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://example.org/{ext}",
                         title=f"source {ext}", status=status)
    return s["id"]


def _candidate(pid, ext, creator, *, title=None):
    return candidates.remember(
        [{"external_id": ext, "url": f"https://example.org/{ext}", "title": title or f"item {ext}", "creator": creator}],
        platform="youtube", project_id=pid, origin={"kind": "exploration"})[0]


def _acquire(pid, ext, creator, *, source_id=None, reason=None):
    """A candidate acquired through the normal Candidate Index path -- optionally resolved to a real source."""
    cid = _candidate(pid, ext, creator)
    if source_id:
        with db.tx() as conn:
            conn.execute("UPDATE candidates SET source_id=? WHERE id=?", (source_id, cid))
    candidates.mark(pid, [cid], "acquired", reason or "acquired from the Candidate Index")
    return cid


def _note(pid, source_id, *, status="approved"):
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO project_notes (project_id, content, created_at, status, model, source_id) "
                           "VALUES (?,?,?,?,?,?)",
                           (pid, "a specific finding", time.time(), status, "claude-sonnet-5", source_id))
        return int(cur.lastrowid)


def _claim(pid, origin_note_id, *, status="proposed"):
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, status, origin_note_id, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (f"claim{time.time_ns()}", pid, "a specific proposition", status, origin_note_id,
                      time.time(), time.time()))


def _target_link(pid, candidate_id, ref_id, *, state="satisfied"):
    with db.tx() as conn:
        conn.execute("INSERT OR REPLACE INTO candidate_links (candidate_id, project_id, kind, ref_id, state, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)", (candidate_id, pid, "evidence_target", ref_id, state, time.time(), time.time()))


# ------------------------------------------------------------------ 1. project isolation

def test_decisions_are_project_scoped(two_projects):
    a, b = two_projects
    _acquire(a, "iso1", "Creator A")
    r_a = discovery_measure.report(a)
    r_b = discovery_measure.report(b)
    assert r_a["usage"]["decided_total"] == 1
    assert r_b["usage"]["decided_total"] == 0


# ------------------------------------------------------------------ 2. operational skips excluded from decisions

def test_operational_skips_never_become_preference_decisions(two_projects):
    a, _ = two_projects
    _acquire(a, "op1", "Creator A")
    for ext, state in (("op2", "skipped_limit"), ("op3", "skipped_cost"), ("op4", "duplicate")):
        cid = _candidate(a, ext, "Creator A")
        candidates.mark(a, [cid], state)
    r = discovery_measure.report(a)
    assert r["usage"]["decided_total"] == 1          # only the acquisition counts as a genuine decision
    assert r["usage"]["operational_skips"] == {"skipped_limit": 1, "skipped_cost": 1, "duplicate": 1}


# ------------------------------------------------------------------ 3. capture-rate denominator is honest

def test_capture_rate_denominator_is_genuine_decisions_only(two_projects):
    a, _ = two_projects
    _acquire(a, "cr1", "Creator A")
    _acquire(a, "cr2", "Creator A")
    cid = _candidate(a, "cr3", "Creator A")
    candidates.mark(a, [cid], "user_dismissed")
    cid2 = _candidate(a, "cr4", "Creator A")
    candidates.mark(a, [cid2], "skipped_low_relevance")
    cid3 = _candidate(a, "cr5", "Creator A")
    candidates.mark(a, [cid3], "skipped_limit")       # must not inflate the denominator
    r = discovery_measure.report(a)
    assert r["usage"]["decided_total"] == 4           # 2 acquired + 1 dismissed + 1 low-relevance
    assert r["usage"]["capture_rate"] == 0.5


# ------------------------------------------------------------------ 4. unresolved / incomplete ingests are not yield

def test_unresolved_and_incomplete_acquisitions_are_not_counted_as_yield(two_projects):
    a, _ = two_projects
    _acquire(a, "un1", "Creator A")                                    # never got a source_id
    pending_source = _source("un2src", status="pending")
    _acquire(a, "un2", "Creator A", source_id=pending_source)          # resolved, but ingest not finished
    ready_source = _source("un3src", status="ready")
    _acquire(a, "un3", "Creator A", source_id=ready_source)
    _note(a, ready_source, status="approved")
    r = discovery_measure.report(a)
    rv = r["research_value"]["acquired_sources"]
    assert rv["total_acquired_candidates"] == 3
    assert rv["not_yet_resolved"] == 1
    assert rv["ingest_incomplete"] == 1
    assert rv["ready"] == 1
    assert r["research_value"]["findings"]["total"] == 1               # only the ready source's finding counts


# ------------------------------------------------------------------ 5. findings trace only through valid provenance

def test_findings_trace_only_through_candidate_index_provenance(two_projects):
    a, _ = two_projects
    acquired_source = _source("prov1", status="ready")
    _acquire(a, "prov1c", "Creator A", source_id=acquired_source)
    _note(a, acquired_source, status="approved")
    other_source = _source("prov2", status="ready")                    # acquired some OTHER way, never via candidates
    db.add_project_sources(a, [other_source])
    _note(a, other_source, status="approved")
    r = discovery_measure.report(a)
    assert r["cohort_comparison"]["candidate_index"]["findings"]["total"] == 1
    assert r["cohort_comparison"]["other_paths"]["findings"]["total"] == 1


# ------------------------------------------------------------------ 6. claim metrics trace through valid provenance

def test_claims_trace_through_valid_note_provenance(two_projects):
    a, _ = two_projects
    acquired_source = _source("cprov1", status="ready")
    _acquire(a, "cprov1c", "Creator A", source_id=acquired_source)
    note_id = _note(a, acquired_source, status="approved")
    _claim(a, note_id, status="accepted")
    _claim(a, None, status="proposed")                                 # no provenance at all -- must not be counted
    r = discovery_measure.report(a)
    assert r["research_value"]["claims"]["total"] == 1
    assert r["research_value"]["claims"]["by_status"] == {"accepted": 1}


# ------------------------------------------------------------------ 7. target counts: links vs distinct targets

def test_target_links_do_not_silently_become_target_count(two_projects):
    a, _ = two_projects
    c1 = _acquire(a, "tgt1", "Creator A")
    c2 = _acquire(a, "tgt2", "Creator A")
    _target_link(a, c1, "target-x", state="satisfied")
    _target_link(a, c2, "target-x", state="satisfied")                 # same target, two different candidates
    r = discovery_measure.report(a)
    et = r["research_value"]["evidence_targets"]
    assert et["source_target_links"]["satisfied"] == 2
    assert et["distinct_targets_satisfied"] == 1


# ------------------------------------------------------------------ 8. novel creator count is project-scoped

def test_novel_creator_count_is_project_scoped(two_projects):
    a, b = two_projects
    _acquire(a, "nc1", "Only In A")
    r_a = discovery_measure.report(a)
    r_b = discovery_measure.report(b)
    assert "Only In A" in r_a["breadth"]["novel_creators"]
    assert "Only In A" not in r_b["breadth"]["novel_creators"]
    assert r_b["breadth"]["novel_creators_in_window"] == 0


# ------------------------------------------------------------------ 9. zero-usage project

def test_zero_usage_project_returns_a_useful_thin_report(two_projects):
    _, b = two_projects
    r = discovery_measure.report(b)
    assert r["usage"]["decided_total"] == 0
    assert r["usage"]["capture_rate"] is None
    assert r["evidence_sufficiency"]["category"] == "no_usage"
    assert "not enough real usage" in r["verdict"].lower()


# ------------------------------------------------------------------ 10. thin usage never emits a strong verdict

def test_thin_usage_does_not_emit_a_confident_verdict(two_projects):
    a, _ = two_projects
    _acquire(a, "thin1", "Creator A")
    cid = _candidate(a, "thin2", "Creator A")
    candidates.mark(a, [cid], "user_dismissed")
    r = discovery_measure.report(a)
    assert r["usage"]["decided_total"] == 2
    assert r["evidence_sufficiency"]["category"] == "thin_sample"
    assert "too little usage" in r["verdict"].lower()
    assert "static" not in r["verdict"].lower() or "no static-vs-adaptive" in r["verdict"].lower()


# ------------------------------------------------------------------ 11. the report reconciles

def test_report_reconciles_its_major_totals(two_projects):
    a, _ = two_projects
    for i in range(20):
        _acquire(a, f"rec{i}", "Creator A")
    for i in range(5):
        cid = _candidate(a, f"recd{i}", "Creator A")
        candidates.mark(a, [cid], "user_dismissed")
    r = discovery_measure.report(a)
    dec = r["usage"]["candidate_decisions"]
    assert sum(dec.get(s, 0) for s in candidates.DISPOSITION_STATES) == r["usage"]["decided_total"]
    assert r["usage"]["decided_total"] == 25
    assert r["evidence_sufficiency"]["category"] == "usable_sample"


# ------------------------------------------------------------------ 12. no write occurs

def test_report_never_writes(two_projects):
    a, _ = two_projects
    _acquire(a, "nw1", "Creator A")
    conn = db.connect()
    before = {t: conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
             for t in ("candidates", "candidate_projects", "project_notes", "project_claims", "candidate_links", "sources")}
    discovery_measure.report(a)
    after = {t: conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            for t in ("candidates", "candidate_projects", "project_notes", "project_claims", "candidate_links", "sources")}
    assert before == after
