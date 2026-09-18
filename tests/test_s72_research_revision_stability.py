"""S72 — a research pass over unchanged inputs does not move the research revision (Sources cache-churn,
docs/SPEED-AUDIT-2026-09-17.md §8, 2026-09-17).

Under a continuous $0 research pass, `/api/sources` took 5–27 s while the writer was idle (0.19 s peak): every
research-derived cache it reads (`staleness`, `potential`, `gap_terms_core`, `rel_analysis`) keys on
`db.project_research_revision`, and that fingerprint moved on every pass — 0 hits of 11,132 — because
`claims.assess()` stamped `updated_at` on every Claim whether or not its verdict changed, and `knowledge.refresh()`
deleted and re-inserted identical nodes with a fresh timestamp. "A cache whose key changes faster than its value can
be computed is not a cache" (SPEED-MISSION.md). The revision must move when the answer changes, never because it
was re-derived. This proves both writers, then the fingerprint end to end, and that a real change still moves it.
"""
from __future__ import annotations

import time

import pytest

from neurosearch import claims, db, knowledge
from neurosearch.config import settings


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    claims._harvest_locks.clear()
    yield
    db._local.conn = None


FACTS = [
    "The SBA guarantee fee on loans under $150,000 is 2 percent this fiscal year.",
    "Sellers financing part of the deal typically hold a note on full standby for the loan's life.",
    "Retaining an accounting firm's prior owner through two tax seasons protects client retention.",
    "A CIM's addback schedule should be checked against three years of tax returns, not just one.",
]


def _project() -> str:
    pid = db.create_project("s72", brief="durable facts about buying businesses")["id"]
    sid = db.upsert_source(platform="manual", external_id="s72", url="manual://s72", title="src", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid)); db.connect().commit()
    for f in FACTS:
        db.add_project_note(pid, f, citations=[{"source_id": sid, "timestamp": "0:00", "snippet": "x"}], status="approved")
    claims.ensure(pid)                                                  # harvest + assess + map: the steady state
    # every fingerprint component must be populated, or a churning writer hides behind an empty table
    knowledge.add_target(pid, "Obtain the current SBA guarantee fee schedule from the SBA itself", origin="user", sufficiency="governing")
    db.upsert_analysis(pid, sid, "summary", summary="one source, four durable facts", prompt_version="findings-test", input_hash="h1")
    claims.ensure(pid)
    parts = db.project_research_revision(pid).split("|")
    assert all(not p_.startswith("0:") for p_ in parts[:5]), f"fixture leaves a fingerprint component empty: {parts}"
    return pid


def test_assess_writes_only_when_the_verdict_changes(fresh):
    pid = _project()
    cid = claims.list_for_project(pid)[0]["id"]
    before = db.connect().execute("SELECT updated_at FROM project_claims WHERE id=?", (cid,)).fetchone()[0]
    claims.assess(cid)
    after = db.connect().execute("SELECT updated_at FROM project_claims WHERE id=?", (cid,)).fetchone()[0]
    assert after == before, "an unchanged verdict must not touch updated_at"


def test_refresh_leaves_identical_nodes_alone(fresh):
    pid = _project()
    stamps = lambda: sorted(r[0] for r in db.connect().execute("SELECT updated_at FROM project_knowledge_nodes WHERE project_id=?", (pid,)))
    before = stamps()
    assert before, "the fixture must produce at least one node"
    knowledge.refresh(pid)
    assert stamps() == before, "an identical node set must not be rewritten"


def test_research_revision_is_stable_across_a_full_pass_and_moves_on_a_real_change(fresh):
    pid = _project()
    rev0 = db.project_research_revision(pid)
    claims.ensure(pid)                                                  # the whole $0 research pass, again
    claims.ensure(pid)
    assert db.project_research_revision(pid) == rev0, "re-deriving unchanged research state must not move the revision"
    # a real change: accept a Claim (readiness changes) — the revision must move, and the pass after it settle again
    c = claims.list_for_project(pid)[0]
    claims.set_status(c["id"], "accepted", application="established")
    rev1 = db.project_research_revision(pid)
    assert rev1 != rev0
    claims.ensure(pid)
    rev2 = db.project_research_revision(pid)
    claims.ensure(pid)
    assert db.project_research_revision(pid) == rev2


def test_a_target_folded_as_a_duplicate_is_not_reopened_by_the_next_pass(fresh):
    """Measured live: detect() re-opened three tension targets every pass and dedupe_targets folded them again —
    one write per pass, the last churning writer. A duplicate stays folded into its open survivor."""
    import json as _json
    pid = _project()
    c = claims.list_for_project(pid)[0]
    now = time.time()
    with db.tx() as conn:
        for i, q in enumerate(["Corroborate or refute: the seller note stands on full standby for the loan's life",
                               "Independently corroborate: the seller note stands on full standby for the loan's life"]):
            conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, topic, claim_id, sufficiency, preferred_classes, closure, "
                         "closure_rule, status, origin, gap, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (db.new_id(), pid, q, "seller", c["id"], "corroborative", _json.dumps(["practice"]), "x", _json.dumps({}), "open", "tension", None, now + i, now + i))
    # make the WEAK_CONSENSUS condition real for this Claim (2 supporting rows, 1 independent source) so detect()
    # selects its tension and would, before the fix, re-open the folded target
    sid = db.connect().execute("SELECT source_id FROM project_sources WHERE project_id=?", (pid,)).fetchone()["source_id"]
    claims.add_evidence(c["id"], sid, locator="0:30", relation="SUPPORTS", excerpt="a second passage from the same source")
    assert knowledge.dedupe_targets(pid) == 1
    folded = [t for t in knowledge.list_targets(pid, status="dropped") if t["claim_id"] == c["id"]]
    assert len(folded) == 1 and folded[0]["gap"].startswith(knowledge.DUPLICATE_GAP_PREFIX)
    knowledge.detect(pid)                                               # the reconcile that used to re-open it
    open_ids = [t["id"] for t in knowledge.list_targets(pid, status="open") if t["claim_id"] == c["id"]]
    assert folded[0]["id"] not in open_ids and open_ids, "the folded duplicate stays folded; its survivor stays open"
    assert knowledge.dedupe_targets(pid) == 0
    for tg in knowledge.list_targets(pid):                              # the refresh() step that erased the reason
        knowledge.assess_target(tg["id"])
    assert knowledge.get_target(folded[0]["id"])["gap"].startswith(knowledge.DUPLICATE_GAP_PREFIX)
    rev = db.project_research_revision(pid)
    knowledge.detect(pid); knowledge.dedupe_targets(pid)                 # a second pass is a no-op end to end
    for tg in knowledge.list_targets(pid):
        knowledge.assess_target(tg["id"])
    assert db.project_research_revision(pid) == rev
