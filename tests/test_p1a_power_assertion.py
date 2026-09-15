"""L-21 (EXECUTION-LADDER.md Stage 3, PRODUCT-INTELLIGENCE-MISSION.md idle-sleep section): the parts of
neurosearch/power_assertion.py that ARE testable without a real Mac -- start/stop wired to actual queue state,
and honest unavailability off macOS / without `caffeinate`. What is NOT and cannot be tested here (lid-closed
vs. lid-open+display-off reliability) is exactly the physical-hardware gate this rung's own docstring and
EXECUTION-LADDER.md entry say still needs Kyle's measurement -- these tests prove the software plumbing only,
never the power-management claim itself."""
from __future__ import annotations

import subprocess
import time

import pytest

from neurosearch import db, power_assertion


@pytest.fixture
def pa_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    power_assertion._watch_stop.set()
    if power_assertion._watch_thread is not None:
        power_assertion._watch_thread.join(timeout=5)
    power_assertion._proc = None
    power_assertion._watch_thread = None
    yield
    power_assertion.stop()
    db.close_thread_connection()


class _FakeProc:
    def __init__(self):
        self._alive = True
        self.pid = 4242
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self._alive = False


def test_unavailable_off_macos_never_claims_a_held_assertion(pa_db, monkeypatch):
    monkeypatch.setattr(power_assertion.sys, "platform", "linux")
    assert power_assertion.available() is False
    assert power_assertion.start() is False
    s = power_assertion.status()
    assert s["available"] is False and s["watching"] is False and s["held"] is False


def test_unavailable_without_caffeinate_on_path(pa_db, monkeypatch):
    monkeypatch.setattr(power_assertion.sys, "platform", "darwin")
    monkeypatch.setattr(power_assertion.shutil, "which", lambda name: None)
    assert power_assertion.available() is False
    assert power_assertion.start() is False


def test_starts_when_work_exists_and_stops_when_idle(pa_db, monkeypatch):
    monkeypatch.setattr(power_assertion.sys, "platform", "darwin")
    monkeypatch.setattr(power_assertion.shutil, "which", lambda name: "/usr/bin/caffeinate")
    spawned: list[_FakeProc] = []

    def fake_popen(cmd, **kw):
        assert cmd == ["caffeinate", "-s"]
        fp = _FakeProc()
        spawned.append(fp)
        return fp

    monkeypatch.setattr(power_assertion.subprocess, "Popen", fake_popen)

    db.create_job("reembed", {})       # a queued, immediately-eligible job counts as "work exists"
    assert power_assertion._work_exists() is True

    power_assertion._ensure_started()
    assert len(spawned) == 1 and power_assertion.status()["held"] is True

    # calling it again while the same process is alive must not spawn a second one
    power_assertion._ensure_started()
    assert len(spawned) == 1

    db.connect().execute("UPDATE jobs SET status='done' WHERE kind='reembed'")
    db.connect().commit()
    assert power_assertion._work_exists() is False

    power_assertion._ensure_stopped()
    assert spawned[0].terminated is True
    assert power_assertion.status()["held"] is False


def test_far_future_scheduled_work_does_not_justify_holding_the_assertion_yet(pa_db):
    db.create_job("reembed", {}, not_before=time.time() + power_assertion.SCHEDULED_LOOKAHEAD + 3600)
    assert power_assertion._work_exists() is False, "a job scheduled more than a day out shouldn't hold the assertion now"


def test_near_future_scheduled_work_does_justify_holding_it(pa_db):
    db.create_job("reembed", {}, not_before=time.time() + 3600)
    assert power_assertion._work_exists() is True


def test_watch_loop_starts_and_stops_the_thread(pa_db, monkeypatch):
    monkeypatch.setattr(power_assertion.sys, "platform", "darwin")
    monkeypatch.setattr(power_assertion.shutil, "which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(power_assertion.subprocess, "Popen", lambda cmd, **kw: _FakeProc())

    assert power_assertion.start(poll=0.05) is True
    assert power_assertion.status()["watching"] is True
    power_assertion.stop()
    assert power_assertion.status()["watching"] is False
