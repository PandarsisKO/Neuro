"""AD9 -- one long-running tool at a time.

WHAT WENT WRONG. Three `rescore_candidates.py` runs were started against the same project in separate Terminal
tabs. Each enforced `--budget 5` correctly; the user had in fact authorised $15 and did not know it. The same
shape applies to `backfill_descriptions.py` against the shared 10,000-unit daily YouTube quota.

These tests pin the two properties that make the lock trustworthy rather than merely present: a second holder is
REFUSED (not queued, not silently allowed), and the lock is released by process death alone, so there is no
stale-lock state a user could get stuck in and no cleanup step to remember.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import _runlock  # noqa: E402


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(type(settings), "data_dir", property(lambda self: tmp_path), raising=False)
    return tmp_path


def test_second_acquire_is_refused(data_dir):
    first = _runlock.acquire("t", note="the first run")
    with pytest.raises(_runlock.Busy) as ei:
        _runlock.acquire("t")
    assert "the first run" in ei.value.holder, "the refusal must say who is holding it, not just that it is held"
    assert str(os.getpid()) in ei.value.holder
    first.close()


def test_closing_releases_it(data_dir):
    _runlock.acquire("t").close()
    _runlock.acquire("t").close()          # would raise if the first lock outlived its file object


def test_different_names_do_not_collide(data_dir):
    a, b = _runlock.acquire("rescore"), _runlock.acquire("backfill")
    a.close(); b.close()


def test_a_failed_attempt_does_not_erase_the_holder(data_dir):
    """`a+` not `w`: a second run must never blank the record of the run that actually holds the lock."""
    first = _runlock.acquire("t", note="real holder")
    for _ in range(3):
        with pytest.raises(_runlock.Busy):
            _runlock.acquire("t")
    assert "real holder" in (data_dir / ".t.lock").read_text()
    first.close()


def test_the_lock_dies_with_the_process(data_dir, tmp_path):
    """No stale-lock class of bug: a run killed outright leaves nothing behind to clean up."""
    code = ("import fcntl, time\n"
            f"fh = open({str(tmp_path / '.t.lock')!r}, 'a+')\n"
            "fcntl.flock(fh.fileno(), fcntl.LOCK_EX)\n"
            "fh.write('pid ? -- the run we are about to kill\\n'); fh.flush()\n"
            "print('held', flush=True)\n"
            "time.sleep(30)\n")
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        with pytest.raises(_runlock.Busy):
            _runlock.acquire("t")
    finally:
        proc.kill()
        proc.wait(timeout=10)
    _runlock.acquire("t").close()           # free the moment the holder died -- nothing to clean up


def test_guard_exits_rather_than_raising(data_dir, capsys):
    first = _runlock.acquire("t")
    with pytest.raises(SystemExit) as ei:
        _runlock.guard("t")
    assert ei.value.code == 2
    assert "REFUSING" in capsys.readouterr().err
    first.close()


def test_ignore_lock_says_out_loud_what_it_costs(data_dir, capsys):
    first = _runlock.acquire("t")
    assert _runlock.guard("t", ignore=True) is None
    out = capsys.readouterr().out
    assert "PER RUN" in out, "the escape hatch must state that the budget ceiling no longer means what it says"
    first.close()
