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


# ---------------------------------------------------------------- estimator calibration (E5, 2026-09-14)
# 8 real metered windows: (user chars, system chars, actual list-price cost). Every one a single window, cold cache.
_MEASURED = {   # model -> (list price in/out per Mtok as _price() returned it that day, [(user chars, system chars, actual cost)])
    "claude-sonnet-5": ((2.0, 10.0), [(10360, 6222, 0.0298), (2461, 6222, 0.0194), (2295, 6222, 0.0179), (21031, 6222, 0.0380)]),
    "claude-haiku-4-5": ((1.0, 5.0), [(15566, 6222, 0.0133), (7785, 6222, 0.0121), (5296, 6222, 0.0089), (34253, 6222, 0.0199)]),
}


def test_estimate_reproduces_measured_spend(monkeypatch):
    """The calibration is frozen against real spend: every window within -15%/+40% of actual, each model's
    4-window total within -10%/+25%. Over is the safe side for a budget gate; far under is what E5 caught."""
    from neurosearch import usage as U
    for model, (price, points) in _MEASURED.items():
        monkeypatch.setattr(U, "_price", lambda m, _p=price: _p)
        est_total = act_total = 0.0
        for n_chars, sys_chars, actual in points:
            est = U.estimate_findings(n_chars, system_chars=sys_chars)
            assert 0.85 <= est / actual <= 1.40, (model, n_chars, est, actual)
            est_total += est
            act_total += actual
        assert 0.90 <= est_total / act_total <= 1.25, (model, est_total, act_total)


def test_old_formula_would_fail_the_same_points(monkeypatch):
    """Regression guard on the guard: the pre-calibration formula (chars/4, 600 out, no system prompt) is the
    thing that said $0.042 for a $0.105 batch. If someone quietly reverts the constants, this fails."""
    (pin, pout), points = _MEASURED["claude-sonnet-5"]
    for n_chars, _, actual in points:
        old = n_chars / 4 / 1e6 * pin + 0.0006 * pout
        assert old / actual < 0.6


def test_estimate_tracks_real_system_prompt(e2_db):
    """The system prompt = a FIXED instructions block + the project brief (grows with the project). Two guards:
    the fixed block stays in its measured band (a rewrite that doubles it shows up here), and the fallback
    constant is never BELOW what even a one-line-brief project actually sends (under is the unsafe side)."""
    from neurosearch import usage as U
    project, sids = _project_with_sources(1)
    ws = findings.canonical_requests(project["id"], sids[0])
    assert ws, "fixture produced no window"
    blocks = ws[0]["system"]
    assert isinstance(blocks, list) and blocks
    fixed = len(blocks[0]["text"])                      # measured 1,959 on 2026-09-14
    assert 1400 <= fixed <= 3000, fixed
    assert t4._system_chars(ws[0]) <= U.FINDINGS_SYSTEM_CHARS


def test_source_estimate_uses_the_windows_own_system_prompt(e2_db, monkeypatch):
    from neurosearch import usage as U
    project, sids = _project_with_sources(1)
    seen = {}
    real_fn = U.estimate_findings
    def spy(n_chars, batch=False, system_chars=None):
        seen["system_chars"] = system_chars
        return real_fn(n_chars, batch=batch, system_chars=system_chars)
    monkeypatch.setattr(U, "estimate_findings", spy)
    t4._source_estimate(project["id"], sids[0], substance_floor=None)
    assert seen["system_chars"] is not None and seen["system_chars"] > 0
