"""L-12 (EXECUTION-LADDER.md P0.B, CTO rulings §1.B): the project's brief changes WHILE a suggest_findings job
is running (started reading under brief A, the user edits the brief to B before the job finishes writing).

Real gap found and fixed here (not just an audit): findings.suggest_for_source() already re-checks
`_inputs_current()` at every safe boundary and raised to refuse writing a stale-tagged result -- correct -- but
it raised a bare RuntimeError, and jobs.execute()'s retry classification only recognizes typed/regex-matched
transient errors (see TRANSIENT in jobs.py) or a job kind in RETRYABLE *matching that regex* -- a plain
RuntimeError whose text doesn't match falls through to a terminal "failed" job, silently NOT retried, despite
its own message promising "kept for retry". Now raises `jobs.Yield` instead, the SAME mechanism long jobs
already use to give a worker back at a safe boundary with durable progress kept: immediate, uncounted requeue,
not a failure."""
from __future__ import annotations

import pytest

from neurosearch import db, findings, jobs


@pytest.fixture
def p0b_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project_with_source(brief: str):
    project = db.create_project("p0b", brief=brief)
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project["id"], sid))
    text = "We paid $500 for the widget last quarter."
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    db.connect().commit()
    return project, sid


def test_a_job_that_races_a_mid_flight_brief_edit_yields_and_retries_instead_of_failing(p0b_db, monkeypatch):
    project, sid = _project_with_source("brief A: find the durable facts")
    pid = project["id"]
    rev_a = db.brief_revision(pid)

    job = db.create_job("suggest_findings", {"project_id": pid, "source_ids": [sid]})
    real_get_project = db.get_project
    fired = []

    def get_project_then_edit(pid_):
        snapshot = real_get_project(pid_)
        if pid_ == pid and not fired:
            fired.append(1)
            db.update_project(pid, brief="brief B: an entirely different question")
        return snapshot

    # Patched by hand (not monkeypatch.setattr) and restored by hand: this test shares its `monkeypatch` fixture
    # instance with the `p0b_db` fixture above (function-scoped, injected into both), so calling
    # monkeypatch.undo() here would also roll back p0b_db's own fake_ai/data_dir patches, not just this one.
    db.get_project = get_project_then_edit
    claimed = db.claim_job(("suggest_findings",), worker_id="test-driver")
    assert claimed and claimed["id"] == job["id"]
    outcome = jobs.execute(claimed, "test-driver")
    db.get_project = real_get_project

    assert outcome == "queued", "a mid-flight input change must requeue the job, not fail it"
    row = db.get_job(job["id"])
    assert row["status"] == "queued"
    assert (row["attempts"] or 0) == 0, "Yield is not a failed attempt — it must not count against MAX_ATTEMPTS"
    assert row["not_before"] is None or row["not_before"] <= db.now() + 1, "Yield requeues immediately, no real delay"
    assert db.connect().execute("SELECT COUNT(*) n FROM project_notes WHERE project_id=?", (pid,)).fetchone()["n"] == 0, (
        "nothing should have been written under the stale brief"
    )

    rev_b = db.brief_revision(pid)
    assert rev_a != rev_b

    # The retry: claim and run it again, this time with no concurrent edit — it must complete cleanly under B.
    claimed2 = db.claim_job(("suggest_findings",), worker_id="test-driver")
    assert claimed2 and claimed2["id"] == job["id"]
    assert jobs.execute(claimed2, "test-driver") == "done"
    note = db.connect().execute("SELECT * FROM project_notes WHERE project_id=? AND source_id=?", (pid, sid)).fetchone()
    assert note is not None and note["brief_revision"] == rev_b, "the retry must write under the CURRENT (post-edit) brief"
