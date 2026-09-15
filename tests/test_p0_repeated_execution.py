"""L-11 (EXECUTION-LADDER.md P0.A, CTO rulings §1.A): repeated execution against the same inputs must be a true
no-op the second time -- t4.execute()'s own dedupe (findings.is_current filtering at selection, plus
db.dedupe_key_for's "findings:{project_id}:{source_id}" on the enqueued job for the in-flight case) is EXISTING
machinery; this proves it rather than building anything new."""
from __future__ import annotations

import pytest

from neurosearch import db, findings, jobs, t4


@pytest.fixture
def p0a_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project_with_source():
    project = db.create_project("p0a", brief="find the durable facts")
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project["id"], sid))
    text = "We paid $500 for the widget last quarter. It broke in March."
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    db.connect().commit()
    return project, sid


def _counts(project_id):
    conn = db.connect()
    notes = conn.execute("SELECT COUNT(*) n FROM project_notes WHERE project_id=?", (project_id,)).fetchone()["n"]
    claims = conn.execute("SELECT COUNT(*) n FROM project_claims WHERE project_id=?", (project_id,)).fetchone()["n"]
    us = conn.execute("SELECT COUNT(*) n FROM usage WHERE project_id=?", (project_id,)).fetchone()["n"]
    return notes, claims, us


def test_second_execute_after_the_job_ran_enqueues_and_writes_nothing_new(p0a_db, run_queued_job):
    project, sid = _project_with_source()
    pid = project["id"]

    plan1 = t4.execute(pid, budget_usd=10.0, dry_run=False)
    assert plan1["executed"] is True and len(plan1["job_ids"]) == 1
    run_queued_job(plan1["job_ids"][0])   # the fake worker actually runs suggest_findings

    notes1, claims1, usage1 = _counts(pid)
    assert notes1 > 0, "the fake path should have written at least one finding to compare against"

    # Second call: the SAME inputs, nothing changed in between -- is_current now filters the source out entirely.
    plan2 = t4.execute(pid, budget_usd=10.0, dry_run=False)
    assert plan2["count"] == 0 and plan2["job_ids"] == [] and plan2["executed"] is False

    notes2, claims2, usage2 = _counts(pid)
    assert (notes2, claims2, usage2) == (notes1, claims1, usage1), "repeated execution must write nothing new"


def test_second_execute_while_the_first_job_is_still_queued_enqueues_nothing(p0a_db):
    project, sid = _project_with_source()
    pid = project["id"]

    plan1 = t4.execute(pid, budget_usd=10.0, dry_run=False)
    assert len(plan1["job_ids"]) == 1
    before = {r["id"] for r in db.connect().execute("SELECT id FROM jobs").fetchall()}

    # source is not YET current (nothing ran the job) -- selection still includes it, but the natural dedupe_key
    # on the enqueued job (findings:{project_id}:{source_id}) must return the SAME job, not a second one.
    plan2 = t4.execute(pid, budget_usd=10.0, dry_run=False)
    after = {r["id"] for r in db.connect().execute("SELECT id FROM jobs").fetchall()}
    assert after == before, "a source still queued must dedupe to the same job, not enqueue a second one"
    assert plan2["job_ids"] == plan1["job_ids"]
