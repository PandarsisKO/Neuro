"""L-13 (EXECUTION-LADDER.md P0.C, CTO rulings §1.C): crash a fake worker mid-suggest_findings -- after one
window's provider call and durable persistence (crash_point 'findings_window_persisted') but before the
source's overall analysis is complete. Restart (crashkit.Sim's real lease-recovery path, the same mechanism a
real process restart uses) and confirm: the job requeues rather than failing, the completed window's `usage`
row is never recorded twice, the missing window is paid for exactly once on retry, and `work_units` count
equals windows read once the source is fully analysed.

Audit note -- why this test exists on top of what was already there: the two halves of this claim were already
independently proven elsewhere. tests/test_s46_r4_durable_units.py::
test_completed_windows_survive_parent_crash_and_retry_runs_only_missing proves windows/work_units durability and
"the retry pays only for missing windows" at the suggest_for_source() level -- but with `findings._call` replaced
by a test double, so it never touches the real `usage` table. tests/test_indestructible.py::
test_crash_matrix_findings[findings_persisted_before_done] proves the real `usage` table is not double-recorded
across a genuine job-level crash+restart (crashkit.Sim, real fake-AI `_call`) -- but only for a whole-source
crash AFTER every window already completed, never a true partial-completion. Neither test combines real usage
recording, a real job-level restart, and a genuine partial (some windows done, one not) crash. This test closes
that specific, narrow gap; it does not re-prove what the other two already prove.

Windows are forced to run strictly sequentially (concurrency.limit_for patched to 1): findings.extract normally
fans multi-window sources out across a small thread pool (neurosearch/concurrency.py), so with the default
limit and only two windows both providers calls (and both usage rows) land before either thread reaches the
crash point -- there is no real "mid-flight" moment to crash at under concurrent execution with this few
windows. Sequential execution is what makes "one window done, one not yet started" a reachable, deterministic
state to crash in."""
from __future__ import annotations

import pytest

from neurosearch import concurrency, db, findings, jobs
from tests import crashkit


@pytest.fixture
def p13_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _usage_count() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM usage WHERE kind='findings'").fetchone()[0]


def test_partial_crash_mid_windows_does_not_double_pay_the_completed_window(p13_db, monkeypatch):
    project = db.create_project("p13", brief="find the durable facts")
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project["id"], sid))
    text = "We paid $500 for the widget last quarter."
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    db.connect().commit()

    # Force exactly two windows so the crash point can land strictly between them -- the real _windows() cutter
    # only splits on WINDOW_CHARS (60k chars), which this tiny fixture text never approaches.
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: ["window 0 fact", "window 1 fact"])
    monkeypatch.setattr(concurrency, "limit_for", lambda task: 1)

    job = db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [sid]})
    jobs.CRASH_AT["findings_window_persisted"] = 1
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings",)) == "crashed"

    assert _usage_count() == 1, "the completed window's provider call is durably recorded exactly once"
    parent_hash = findings.input_hash(project, sid)
    assert len(db.work_units_for_parent("findings.extract", project["id"], sid, parent_hash)) == 1

    # Restart: crashkit.Sim already cleared CRASH_AT and recovered the expired lease. The remaining window --
    # and only the remaining window -- runs.
    assert sim.step(("suggest_findings",)) == "done"
    row = db.get_job(job["id"])
    assert row["status"] == "done"
    assert _usage_count() == 2, "restart must pay for the missing window once, and never re-pay for the completed one"
    assert len(db.work_units_for_parent("findings.extract", project["id"], sid, parent_hash)) == 2
