"""L-14 (EXECUTION-LADDER.md P0.D, CTO rulings §1.D): a daily-budget (or provider-availability) wall hit
mid-project must leave exactly one durable, correctly-gated job behind -- not silently drop the remaining
sources, and not race a second, un-gated job ahead of the very wait that caused the pause.

Real bug found and fixed here (not just an audit): findings.suggest_for_project()'s per-source loop already had
special handling for BudgetPaused/ProviderUnavailable -- it created a SEPARATE fresh 'suggest_findings' job
carrying only the still-unprocessed source_ids, then re-raised so jobs.execute() would ALSO requeue the
original job (with its full, original source_ids list, via db.requeue_job's wait_reason='budget'/not_before for
BudgetPaused, or db.park_provider_wait for ProviderUnavailable). The result was two jobs covering the same
remaining source(s): the original (correctly gated behind the budget/provider wait) and the fresh one
(db.create_job with no wait fields at all, immediately claimable) -- which would race straight past the pause
that was supposed to stop new spend. Fixed by removing the manual fresh-job creation: jobs.execute() already
requeues the SAME job correctly for Yield, BudgetPaused, and ProviderUnavailable alike, and any source that
happened to complete before the pause is skipped on resume via the pre-existing is_current/input_hash check --
nothing is lost by simply re-raising, same fix shape as L-12's Yield handling."""
from __future__ import annotations

import pytest

from neurosearch import db, findings, jobs, usage


@pytest.fixture
def p14_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project_with_two_sources():
    project = db.create_project("p14", brief="find the durable facts")
    sids = []
    for ext in ("s1", "s2"):
        sid = db.upsert_source(platform="manual", external_id=ext, url=f"manual://{ext}", title=ext)["id"]
        db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project["id"], sid))
        text = "We paid $500 for the widget last quarter."
        db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
        db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
        sids.append(sid)
    db.connect().commit()
    return project, sids


def _suggest_findings_jobs():
    return [j for j in db.list_jobs(50) if j["kind"] == "suggest_findings"]


def test_budget_paused_mid_project_requeues_one_job_not_two(p14_db, monkeypatch):
    project, (s1, s2) = _project_with_two_sources()
    job = db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [s1, s2]})

    real = findings.suggest_for_source
    calls = []

    def fake(project_id, source_id, **kw):
        calls.append(source_id)
        if source_id == s2:
            raise usage.BudgetPaused("daily budget reached", 60)
        return real(project_id, source_id, **kw)

    monkeypatch.setattr(findings, "suggest_for_source", fake)

    claimed = db.claim_job(("suggest_findings",), worker_id="test-driver")
    assert claimed and claimed["id"] == job["id"]
    outcome = jobs.execute(claimed, "test-driver")
    monkeypatch.undo()

    assert outcome == "queued"
    assert calls == [s1, s2], "s1 completes, s2 is where the budget wall is hit"

    rows = _suggest_findings_jobs()
    assert len(rows) == 1, "exactly one job must remain -- not a second, un-gated duplicate for the remaining source(s)"
    row = rows[0]
    assert row["id"] == job["id"]
    assert row["status"] == "queued"
    assert row["wait_reason"] == "budget"
    assert row["not_before"] is not None and row["not_before"] > db.now(), \
        "the requeued job must be gated behind the budget wait, not immediately claimable"
    assert row["payload"]["source_ids"] == [s1, s2], "the full original source list is preserved for resume"

    # accepted/committed work for s1 (the source that finished before the pause) must be untouched: nothing
    # half-written, and a resumed run does not re-pay for it.
    assert db.get_analysis(project["id"], s1, "summary")["status"] == "current"
    assert db.get_analysis(project["id"], s2, "summary") is None, "nothing half-written for the paused source"
