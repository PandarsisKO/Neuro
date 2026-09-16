"""S56 — LP5 (EXECUTION-LADDER.md, Kyle's overnight-mission correction 6): plan-patch acceptance provenance.
`plan_updates` gained five columns (claim_id, tension_id, decided_at, decided_by, applied_plan_id), verified
genuinely missing before adding them (see db.py's MIGRATIONS comment). These gates prove a single `plan_updates`
row can reconstruct, on its own, the full story of a plan-patch decision: what was proposed and why, which Claim
or tension it traces to, when and by whom it was decided, and -- if accepted -- which regenerated plan actually
folded it in. $0 throughout: no provider/model call is exercised here (planner.build_plan is faked in the one
test that calls apply_accepted_updates, since LP5 is about provenance bookkeeping, not plan generation)."""
from __future__ import annotations

import pytest

from neurosearch import db, plan_narrative, planner


@pytest.fixture
def s56_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(project_id, cid, *, status="accepted", strength="developing", freshness_status="current",
          freshness_class="age_insensitive", topic="topic", text=None):
    db.connect().execute(
        "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, freshness_status, "
        "freshness_class, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid, project_id, text or f"claim {cid}", "factual", topic, status, strength, freshness_status,
         freshness_class, db.now(), db.now()))
    db.connect().commit()


def _tension(project_id, tid, claim_id, kind="CONTRADICTION", status="open"):
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, impact, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, project_id, kind, claim_id, "d", status, "medium", db.now(), db.now()))
    db.connect().commit()


def _fold(claim_id, note_id):
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (claim_id, note_id))
    db.connect().commit()


def _lp3_row(s56_db_unused=None):
    """Build one project with a stale claim cited by a plan's only step, and one pending lp3 propose_updates
    row on it -- the shared setup every test below starts from."""
    p = db.create_project("LP5 provenance", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim behind step one")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    saved = db.save_plan(pid, plan, db.project_snapshot(pid))
    updates = plan_narrative.propose_updates(pid, claim_id="c1")
    assert len(updates) == 1
    return pid, saved["id"], updates[0]["id"]


def test_claim_linkage_is_persisted_on_the_row(s56_db):
    pid, plan_id, update_id = _lp3_row()
    row = db.connect().execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone()
    assert row["claim_id"] == "c1"
    assert row["tension_id"] is None   # this row was proposed via claim_id, not tension_id
    assert row["status"] == "pending"
    assert row["decided_at"] is None and row["decided_by"] is None and row["applied_plan_id"] is None


def test_tension_linkage_resolves_the_claim_id_too(s56_db):
    p = db.create_project("LP5 tension", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim")
    _fold("c1", n["id"])
    _tension(pid, "t1", "c1")
    plan = {"costs": {"evidence": ["F1"]}, "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    updates = plan_narrative.propose_updates(pid, tension_id="t1")
    assert len(updates) == 1
    row = db.connect().execute("SELECT * FROM plan_updates WHERE id=?", (updates[0]["id"],)).fetchone()
    assert row["tension_id"] == "t1"
    assert row["claim_id"] == "c1", "propose_updates resolves and persists the claim behind the tension too"


def test_accept_stamps_decided_at_and_decided_by_immediately(s56_db):
    pid, plan_id, update_id = _lp3_row()
    before = db.now()
    row = db.set_update_status(update_id, "accepted")
    assert row["status"] == "accepted"
    assert row["decided_by"] == "user"
    assert row["decided_at"] is not None and row["decided_at"] >= before
    assert row["applied_plan_id"] is None, "accepted but not yet applied -- no plan folded it in yet"


def test_reject_stamps_decided_fields_but_never_gets_an_applied_plan_id(s56_db):
    pid, plan_id, update_id = _lp3_row()
    row = db.set_update_status(update_id, "rejected")
    assert row["status"] == "rejected"
    assert row["decided_by"] == "user" and row["decided_at"] is not None
    assert row["applied_plan_id"] is None

    # apply_accepted_updates must never touch a rejected row's applied_plan_id, even when it runs afterward
    monkey_plan = {"id": "fake-plan-after-reject", "plan": {}, "updates": []}
    import neurosearch.planner as planner_mod
    orig_build_plan = planner_mod.build_plan
    planner_mod.build_plan = lambda *a, **k: monkey_plan
    try:
        planner.apply_accepted_updates(pid)
    finally:
        planner_mod.build_plan = orig_build_plan
    after = db.connect().execute("SELECT applied_plan_id FROM plan_updates WHERE id=?", (update_id,)).fetchone()
    assert after["applied_plan_id"] is None


def test_apply_accepted_updates_stamps_applied_plan_id_on_every_accepted_row(s56_db):
    pid, plan_id, update_id = _lp3_row()
    db.set_update_status(update_id, "accepted")

    fake_new_plan = {"id": "fake-plan-xyz", "plan": {"first_steps": []}, "updates": []}
    import neurosearch.planner as planner_mod
    orig_build_plan = planner_mod.build_plan
    planner_mod.build_plan = lambda *a, **k: fake_new_plan
    try:
        result = planner.apply_accepted_updates(pid)
    finally:
        planner_mod.build_plan = orig_build_plan

    assert result["id"] == "fake-plan-xyz"
    row = db.connect().execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone()
    assert row["applied_plan_id"] == "fake-plan-xyz"
    # the row still carries everything else from its original proposal -- a single row is now the whole story
    assert row["claim_id"] == "c1" and row["origin"] == "lp3" and row["status"] == "accepted"
    assert row["decided_by"] == "user" and row["decided_at"] is not None
    assert row["proposed"] and row["reason"]


def test_full_provenance_reconstructs_from_the_single_row_alone(s56_db):
    """The spec's own bar: previous, proposed/resulting, reason, claim linkage, origin, decided_by, decided_at,
    applied_plan_id must all be readable off one row with no other query."""
    pid, plan_id, update_id = _lp3_row()
    db.set_update_status(update_id, "accepted")
    fake_new_plan = {"id": "fake-plan-full", "plan": {}, "updates": []}
    import neurosearch.planner as planner_mod
    orig_build_plan = planner_mod.build_plan
    planner_mod.build_plan = lambda *a, **k: fake_new_plan
    try:
        planner.apply_accepted_updates(pid)
    finally:
        planner_mod.build_plan = orig_build_plan

    row = dict(db.connect().execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone())
    for field in ("previous", "proposed", "reason", "claim_id", "origin", "decided_by", "decided_at", "applied_plan_id"):
        assert row.get(field) not in (None, ""), f"{field} missing from the single-row reconstruction"
    assert row["origin"] == "lp3"
    assert row["applied_plan_id"] == "fake-plan-full"


def test_older_rows_with_null_provenance_columns_still_render(s56_db):
    """A pre-LP5 row (written before these columns existed / by the LLM-based path that never sets them) must
    still be readable -- the columns are additive and NULL-safe, never required."""
    p = db.create_project("LP5 legacy", "brief")
    pid = p["id"]
    plan = {"first_steps": [{"action": "x", "evidence": []}]}
    saved = db.save_plan(pid, plan, db.project_snapshot(pid))
    db.add_plan_updates(saved["id"], [{"section": "goal", "proposed": "planner says X", "reason": "llm"}])   # origin=None, no claim_id
    row = db.connect().execute("SELECT * FROM plan_updates WHERE plan_id=?", (saved["id"],)).fetchone()
    assert row["claim_id"] is None and row["tension_id"] is None
    assert row["decided_at"] is None and row["decided_by"] is None and row["applied_plan_id"] is None
    assert row["proposed"] == "planner says X" and row["status"] == "pending"


def test_accepted_via_the_existing_api_route_carries_full_provenance(s56_db, monkeypatch):
    from fastapi.testclient import TestClient
    from neurosearch import api
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "app_token", "")
    pid, plan_id, update_id = _lp3_row()
    client = TestClient(api.app)

    r = client.post(f"/api/plan-updates/{update_id}", json={"status": "accepted"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted" and body["decided_by"] == "user" and body["decided_at"] is not None
    assert body["claim_id"] == "c1" and body["origin"] == "lp3"
    assert body["applied_plan_id"] is None   # the route only decides status -- apply is a separate step

    assert client.post("/api/plan-updates/999999", json={"status": "accepted"}).status_code == 404
