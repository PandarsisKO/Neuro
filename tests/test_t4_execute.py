"""T4 E2: t4.execute() -- the budgeted executor. Ranks sources by t4.select()'s relevance order and walks them
under a dollar cap. dry_run=True (the default) only describes the plan; dry_run=False enqueues real
suggest_findings jobs, relying on findings.py's own dedupe and findings.is_current -- execute() itself never
calls a provider or writes a finding."""
import json

import pytest

from neurosearch import db, findings, t4, usage


@pytest.fixture
def e2_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str, text: str) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id, url=f"manual://{external_id}", title=external_id)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    return sid


def _project_with_sources(n: int):
    project = db.create_project("t4 exec", brief="find the durable facts")
    sids = [_source(project["id"], f"s{i}", f"We paid ${100 + i} for item {i} last quarter.") for i in range(n)]
    db.connect().commit()
    return project, sids


def _jobs():
    return db.connect().execute("SELECT kind, payload FROM jobs").fetchall()


def test_dry_run_writes_and_enqueues_nothing(e2_db):
    project, sids = _project_with_sources(2)
    plan = t4.execute(project["id"], budget_usd=10.0)
    assert plan["executed"] is False and plan["job_ids"] == []
    assert plan["count"] == 2
    assert len(_jobs()) == 0


def test_budget_cap_truncates_the_list(e2_db, monkeypatch):
    project, sids = _project_with_sources(3)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 1.0)
    plan = t4.execute(project["id"], budget_usd=2.5)
    assert plan["count"] == 2
    assert plan["total_estimate"] == 2.0


def test_already_current_source_is_skipped(e2_db, monkeypatch):
    project, sids = _project_with_sources(2)
    monkeypatch.setattr(findings, "is_current", lambda proj, sid, depth=None: sid == sids[0])
    plan = t4.execute(project["id"], budget_usd=10.0)
    assert [s["source_id"] for s in plan["sources"]] == [sids[1]]


def test_unscored_relevance_is_not_skipped_by_default(e2_db):
    project, sids = _project_with_sources(1)
    plan = t4.execute(project["id"], budget_usd=10.0)
    assert plan["sources"][0]["relevance"] is None
    assert plan["count"] == 1


def test_unscored_relevance_is_skipped_once_min_relevance_is_set(e2_db):
    project, sids = _project_with_sources(1)
    plan = t4.execute(project["id"], budget_usd=10.0, min_relevance=0.1)
    assert plan["count"] == 0


def test_live_enqueues_one_suggest_findings_job_per_source_with_the_floor(e2_db, monkeypatch):
    project, sids = _project_with_sources(2)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    result = t4.execute(project["id"], budget_usd=10.0, substance_floor=30, dry_run=False)
    assert result["executed"] is True and len(result["job_ids"]) == 2
    rows = _jobs()
    assert len(rows) == 2
    for row in rows:
        assert row["kind"] == "suggest_findings"
        payload = json.loads(row["payload"])
        assert payload["substance_floor"] == 30
        assert payload["t4_execute_version"] == t4.EXECUTE_VERSION
        assert payload["t4_selector_version"] == t4.SELECTOR_VERSION


def test_second_live_call_with_nothing_new_enqueues_nothing_new(e2_db, monkeypatch):
    project, sids = _project_with_sources(1)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    first = t4.execute(project["id"], budget_usd=10.0, dry_run=False)
    second = t4.execute(project["id"], budget_usd=10.0, dry_run=False)
    assert first["job_ids"] == second["job_ids"]
    assert len(_jobs()) == 1        # the second call's enqueue deduplicated against the first, still-queued job


def test_usage_guard_blocks_before_any_enqueue(e2_db, monkeypatch):
    project, sids = _project_with_sources(1)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)

    def blow_up(estimate):
        raise usage.BudgetPaused("daily budget reached", 60)

    monkeypatch.setattr(usage, "guard", blow_up)
    with pytest.raises(usage.BudgetPaused):
        t4.execute(project["id"], budget_usd=10.0, dry_run=False)
    assert len(_jobs()) == 0


def test_batch_transport_enqueues_one_suggest_findings_batch_job(e2_db, monkeypatch):
    project, sids = _project_with_sources(2)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    result = t4.execute(project["id"], budget_usd=10.0, dry_run=False, transport="batch")
    assert result["executed"] is True and len(result["job_ids"]) == 1
    rows = _jobs()
    assert len(rows) == 1 and rows[0]["kind"] == "suggest_findings_batch"
    payload = json.loads(rows[0]["payload"])
    assert sorted(payload["source_ids"]) == sorted(sids)


def test_execution_policy_none_is_the_prior_default(e2_db, monkeypatch):
    project, sids = _project_with_sources(1)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    t4.execute(project["id"], budget_usd=10.0, dry_run=False)
    row = db.connect().execute("SELECT execution_policy FROM jobs").fetchone()
    assert row["execution_policy"] == "local_preferred"          # db.create_job's own default, unchanged


def test_execution_policy_api_requested_is_forced_through(e2_db, monkeypatch):
    project, sids = _project_with_sources(1)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    result = t4.execute(project["id"], budget_usd=10.0, dry_run=False, execution_policy="api_requested")
    assert result["execution_policy"] == "api_requested"
    row = db.connect().execute("SELECT execution_policy FROM jobs").fetchone()
    assert row["execution_policy"] == "api_requested"


def test_execution_policy_api_requested_on_batch_transport(e2_db, monkeypatch):
    project, sids = _project_with_sources(2)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    t4.execute(project["id"], budget_usd=10.0, dry_run=False, transport="batch", execution_policy="api_requested")
    row = db.connect().execute("SELECT execution_policy FROM jobs WHERE kind='suggest_findings_batch'").fetchone()
    assert row["execution_policy"] == "api_requested"
