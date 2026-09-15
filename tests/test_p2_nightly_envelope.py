"""L-30 (EXECUTION-LADDER.md Stage 4, P2 E7 Nightly Refinery backend): one bounded, preflighted envelope per
calendar day, off by default, budget shared (not repeated) across active projects."""
from __future__ import annotations

import pytest

from neurosearch import db, nightly, t4


@pytest.fixture
def p2_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)          # always "past the hour" in a test
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str, text: str) -> str:
    # status="ready" is required: db.list_projects()'s n_sources count (nightly.run()'s active-project filter)
    # goes through project_source_ids(ready_only=True), which only counts sources with status='ready' — the
    # sources table defaults new rows to 'pending' otherwise, and a 'pending' source never counts as active.
    sid = db.upsert_source(platform="manual", external_id=external_id, url=f"manual://{external_id}", title=external_id, status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    return sid


def _project(name: str, n: int):
    project = db.create_project(name, brief="find the durable facts")
    sids = [_source(project["id"], f"{name}-s{i}", f"We paid ${100 + i} for item {i} last quarter.") for i in range(n)]
    db.connect().commit()
    return project, sids


def test_off_by_default_never_runs(p2_db):
    _project("p1", 1)
    assert nightly.due() is False
    r = nightly.run(force=True)
    assert r == {"ran": False, "reason": "t4_nightly_budget is 0 (off)"}


def test_due_requires_budget_hour_and_not_already_run_today(p2_db, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    assert nightly.due() is True                          # hour is 0, always past

    monkeypatch.setattr(settings, "t4_nightly_hour", 23)
    import time
    if time.localtime().tm_hour < 23:
        assert nightly.due() is False
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)

    r = nightly.run()
    assert r["ran"] is True
    assert nightly.due() is False, "must not run twice for the same calendar day"


def test_one_project_within_budget_no_duplicate_source_work(p2_db, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    project, sids = _project("solo", 2)

    r = nightly.run()
    assert r["ran"] is True
    assert r["ok"] is True
    assert len(r["projects"]) == 1
    assert r["projects"][0]["project_id"] == project["id"]
    assert r["projects"][0]["executed"] is True
    assert r["spent_estimate"] <= 2.0

    jobs_before = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='suggest_findings_batch'").fetchone()["n"]
    assert jobs_before == 1                                # ONE batch job for the whole project, not one per source

    # a second run today is a pure no-op: no new jobs, ledger unchanged
    r2 = nightly.run()
    assert r2 == {"ran": False, "reason": f"already ran for {nightly._today_key()}"}
    jobs_after = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='suggest_findings_batch'").fetchone()["n"]
    assert jobs_after == 1


def test_budget_is_shared_across_projects_not_repeated_per_project(p2_db, monkeypatch):
    """The invariant nightly.run() actually owns is the budget_usd it HANDS to each t4.execute call: the
    second project must see whatever the first project's spend left over, never the full nightly budget again
    (that would silently multiply an amount Kyle authorized once as a single ceiling). It is NOT a promise that
    total spend can never exceed the nightly budget by a single source's cost -- t4.execute() itself always
    includes at least one eligible source even when that source's own estimate exceeds the budget_usd it was
    given (see t4.py's E2 docstring / commit 08e3dcf: "always includes at least one eligible source, then stops
    at budget_usd") -- a pre-existing, deliberate per-project contract this rung does not change or need to."""
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 0.05)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.03)
    p1, _ = _project("first", 1)
    p2, _ = _project("second", 1)

    real_execute = t4.execute
    seen_budgets: list[float] = []

    def spy(project_id, *, budget_usd, **kw):
        seen_budgets.append(budget_usd)
        return real_execute(project_id, budget_usd=budget_usd, **kw)

    monkeypatch.setattr(t4, "execute", spy)
    r = nightly.run()
    assert r["ran"] is True
    assert len(seen_budgets) == 2, "both active projects must be walked (not stopped early)"
    assert seen_budgets[0] == pytest.approx(0.05), "the first project sees the full nightly budget"
    assert seen_budgets[1] < seen_budgets[0], (
        "the second project must see only what the first left over, never the full $0.05 again -- "
        "that is the multiplication this rung exists to prevent"
    )
    assert seen_budgets[1] == pytest.approx(0.02), "0.05 - 0.03 spent by the first project"


def test_preflight_refusal_stops_the_whole_night_and_is_recorded(p2_db, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 5.0)
    _project("p1", 1)

    def refuse(envelope_id):
        raise RuntimeError(f"preflight refused for envelope {envelope_id!r}: live database integrity_check reported 'corrupt'")

    monkeypatch.setattr(db, "preflight_autonomous", refuse)
    r = nightly.run()
    assert r["ran"] is False
    assert r["ok"] is False
    assert "preflight refused" in r["reason"]
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == 0, "nothing may be enqueued when preflight refuses"

    rec = nightly.last_run()
    assert rec["ok"] is False and "preflight refused" in rec["reason"]


def test_one_projects_failure_does_not_abort_the_rest_of_the_night(p2_db, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 5.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    bad, _ = _project("bad", 1)
    good, _ = _project("good", 1)

    real_execute = t4.execute

    def flaky(project_id, **kw):
        if project_id == bad["id"]:
            raise RuntimeError("boom")
        return real_execute(project_id, **kw)

    monkeypatch.setattr(t4, "execute", flaky)
    r = nightly.run()
    assert r["ran"] is True
    by_pid = {p["project_id"]: p for p in r["projects"]}
    assert "error" in by_pid[bad["id"]]
    assert by_pid[good["id"]].get("executed") is True
