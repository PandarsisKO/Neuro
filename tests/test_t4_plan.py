"""T4 executor dry run (t4.plan): proves routing wiring at $0 -- no provider call, no health probe, no write."""

import pytest

from neurosearch import contracts, db, providers, t4


@pytest.fixture
def t4_plan_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id,
                           url=f"manual://{external_id}", title=external_id)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    return sid


def _chunk(sid: str, idx: int, start: int, end: int, text: str) -> None:
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)",
                         (sid, idx, start, end, text))


def test_t4_research_contract_is_registered_and_gate_clean(t4_plan_db):
    c = contracts.contract(t4.EXECUTOR_TASK)
    assert c.local_capable is True
    assert c.reversible is True
    decision = contracts.decision(c)
    assert decision["verdict"] == "cheapest"  # runs at the cheapest tier, no tier_reason needed
    assert c.task not in [v.split(":")[0] for v in contracts.policy_violations()]


def test_plan_wraps_every_selected_item_with_routing_metadata(t4_plan_db):
    project_id = db.create_project("T4 plan wrap", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "We paid $500 for the service last quarter.")
    db.connect().commit()

    result = t4.plan(project_id)

    assert result["count"] == 1
    item = result["items"][0]
    assert item["executor_task"] == t4.EXECUTOR_TASK
    assert item["executor_model"] == contracts.contract(t4.EXECUTOR_TASK).model
    assert item["executed"] is False
    assert "eligible_for_local" in item


def test_plan_reports_local_preferred_policy_as_eligible(t4_plan_db):
    project_id = db.create_project("T4 local eligible", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 10, "A passage with $5 in it.")
    db.connect().commit()

    result = t4.plan(project_id)

    assert providers.current_policy() == "local_preferred"
    assert result["eligible_for_local"] is True
    assert "local" in result["routing_note"]


def test_plan_reports_api_only_under_api_only_policy(t4_plan_db):
    project_id = db.create_project("T4 api only", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 10, "A passage with $5 in it.")
    db.connect().commit()

    with providers.policy_context("api_only"):
        result = t4.plan(project_id)

    assert result["eligible_for_local"] is False
    assert result["policy"] == "api_only"
    assert "api only" in result["routing_note"]


def test_plan_makes_no_provider_call_or_write(t4_plan_db, monkeypatch):
    project_id = db.create_project("T4 plan readonly", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 10, "A passage with $5 in it.")
    db.connect().commit()
    jobs_before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    notes_before = db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0]
    claims_before = db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0]

    def _boom(*a, **kw):
        raise AssertionError("t4.plan must never call providers.route")

    monkeypatch.setattr(providers, "route", _boom)

    result = t4.plan(project_id)

    assert all(item["executed"] is False for item in result["items"])
    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before
    assert db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0] == notes_before
    assert db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0] == claims_before


def test_plan_respects_selector_limit(t4_plan_db):
    project_id = db.create_project("T4 plan limit", "test")["id"]
    sid = _source(project_id, "s1")
    for i in range(4):
        _chunk(sid, i, i * 10, i * 10 + 5, f"Passage {i} with no coverage.")
    db.connect().commit()

    result = t4.plan(project_id, limit=2)

    assert result["count"] == 4  # count reflects the full ranked list, same convention as select()
    assert len(result["items"]) == 2


def test_plan_is_deterministic(t4_plan_db):
    project_id = db.create_project("T4 plan repro", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "The warranty lasts 90 days.")
    db.connect().commit()

    first = t4.plan(project_id)
    second = t4.plan(project_id)

    assert first == second
