"""S15 — why the app locked up, and what stops it (0.61.2). (Sorts after test_s14.)

Kyle: *"the app is locked up or failing to load for me. very slow right now."* Measured on his machine while it
was unresponsive, rather than guessed:

* `/api/projects/{id}/findings/quality?summary=1` — **11.5 s** over 12,805 findings. It was 3.8 s at 10,000, so
  the pass grows faster than the corpus. It is cached on the project's view revision, and that revision moves
  every time a finding lands, which during a findings run is constantly. **A cache whose key changes faster than
  its value can be computed is not a cache.**
* `/findings` 2.0 s, so opening the Findings tab asked for ~13.5 s of CPU in a single-process server — and until
  0.61.0 the tab re-asked every four seconds.
* Every concurrent miss on the same key ran its own copy of the 11.5 s pass. Nothing serialised them.
* `data/neurosearch.db` 627 MB beside a **111.8 MB write-ahead log**, static: not growing, not shrinking. SQLite
  auto-checkpoints at ~4 MB but only when no reader holds an older snapshot, and this app keeps a long-lived
  connection per thread while several threads run multi-second passes, so the checkpoint had been starved for
  days. `journal_size_limit` was -1, so even a successful checkpoint never gave the file back.

The app answered a trivial request in 230 ms immediately after a restart, which is what ruled the database out as
the cause and pointed at the passes.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_lock_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import cache, db  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    cache.invalidate()
    yield
    db._local.conn = None


# ------------------------------------------------------------------ one computation, not N

def test_concurrent_misses_compute_once():
    """Eleven seconds, once, is survivable. Eleven seconds N times is the lock-up."""
    runs = []
    started = threading.Event()

    def slow():
        runs.append(1)
        started.set()
        time.sleep(0.3)
        return "value"

    out: list[str] = []
    threads = [threading.Thread(target=lambda: out.append(cache.get_or_compute("k", "r1", slow))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert out == ["value"] * 6
    assert len(runs) == 1


def test_a_new_revision_computes_again():
    n = []
    cache.get_or_compute("k", "r1", lambda: n.append(1) or "a")
    cache.get_or_compute("k", "r1", lambda: n.append(1) or "a")
    cache.get_or_compute("k", "r2", lambda: n.append(1) or "b")
    assert len(n) == 2


# ------------------------------------------------------------------ never block on a cold recompute

def test_a_stale_value_is_returned_at_once_and_refreshed_behind():
    cache.get_or_compute("q", "r1", lambda: "old")
    slow_done = threading.Event()

    def slow():
        time.sleep(0.2)
        slow_done.set()
        return "new"

    t0 = time.time()
    got = cache.get_stale_ok("q", "r2", slow)
    assert time.time() - t0 < 0.15                 # it did not wait for the recompute
    assert got["value"] == "old" and got["current"] is False and got["pending"] is True
    assert slow_done.wait(2)
    for _ in range(50):
        if cache.peek("q") == ("r2", "new"):
            break
        time.sleep(0.05)
    assert cache.peek("q") == ("r2", "new")
    assert cache.get_stale_ok("q", "r2", slow)["current"] is True


def test_only_one_background_refresh_per_key():
    cache.get_or_compute("q", "r1", lambda: "old")
    runs = []

    def slow():
        runs.append(1)
        time.sleep(0.25)
        return "new"

    for _ in range(5):
        cache.get_stale_ok("q", "r2", slow)
    time.sleep(0.5)
    assert len(runs) == 1


def test_a_cold_key_with_nothing_to_show_still_computes():
    """Stale-tolerance is not an excuse to return nothing on a first visit."""
    got = cache.get_stale_ok("cold", "r1", lambda: "computed")
    assert got["value"] == "computed" and got["current"] is True and got["pending"] is False


def test_a_cold_key_can_refuse_to_compute_when_asked_to():
    got = cache.get_stale_ok("cold2", "r1", lambda: "computed", warm=False)
    assert got["value"] is None and got["pending"] is True


def test_a_background_refresh_that_raises_is_swallowed():
    cache.get_or_compute("boom", "r1", lambda: "old")

    def bad():
        raise RuntimeError("nope")

    got = cache.get_stale_ok("boom", "r2", bad)
    assert got["value"] == "old"
    time.sleep(0.3)
    assert cache.peek("boom") == ("r1", "old")      # the old value survives; nothing is poisoned
    assert cache.refreshing() == []


# ------------------------------------------------------------------ the quality summary must not block a screen

def _notes(project_id, n, status="approved"):
    with db.tx() as conn:
        for i in range(n):
            conn.execute("INSERT INTO project_notes (project_id, content, citations, created_at, status, model, "
                         "importance, title, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
                         (project_id, f"a specific point number {i} about the ten percent injection", "[]",
                          1000.0 + i, status, "claude-sonnet-5", 3, f"Finding {i}", "s1"))


def test_the_summary_never_computes_inside_a_request():
    """0.61.2 made every visit but the FIRST cheap; the first still cost 9.8 s after a restart and dragged
    everything with it. So the request never computes the pass at all — the housekeeping loop does — and an
    uncomputed project says so instead of blocking."""
    from neurosearch import findings_quality
    p = db.create_project("cold", brief="b")
    _notes(p["id"], 4)
    s = findings_quality.summary(p["id"])                 # default: warm=False
    assert s.get("pending") is True and "has not run" in s["note"]
    warm = findings_quality.summary(p["id"], warm=True)   # what the background loop does
    assert warm["as_of_current"] is True and "findings" in warm
    assert findings_quality.summary(p["id"])["as_of_current"] is True   # now the request finds it ready


def test_the_background_loop_is_what_warms_it():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "jobs.py"), encoding="utf-8").read()
    assert "_warm_quality" in src and "warm=True" in src


def test_the_usage_map_is_computed_once_per_revision():
    """It walks every note, plan entry, chat citation and Claim, and three different screens ask for it."""
    from neurosearch import findings_view
    p = db.create_project("um", brief="b")
    _notes(p["id"], 5)
    runs = []
    orig = findings_view._usage_map

    def counted(pid):
        runs.append(1)
        return orig(pid)

    findings_view._usage_map = counted
    try:
        findings_view.usage_map(p["id"]); findings_view.usage_map(p["id"]); findings_view.usage_map(p["id"])
    finally:
        findings_view._usage_map = orig
    assert len(runs) == 1


def test_the_summary_takes_the_previous_answer_when_something_is_stored():
    from neurosearch import findings_quality
    p = db.create_project("q", brief="b")
    _notes(p["id"], 6)
    first = findings_quality.summary(p["id"], warm=True)
    assert first["as_of_current"] is True
    _notes(p["id"], 1)                              # a finding lands: the revision moves
    calls = []
    orig = findings_quality._review

    def counted(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    findings_quality._review = counted
    try:
        again = findings_quality.summary(p["id"])
        assert again["as_of_current"] is False and again["recomputing"] is True
        time.sleep(0.6)
    finally:
        findings_quality._review = orig
    assert len(calls) == 1                          # once, behind the request, not in it


def test_the_full_review_still_waits_for_a_current_answer():
    from neurosearch import findings_quality
    p = db.create_project("q2", brief="b")
    _notes(p["id"], 4)
    r = findings_quality.review(p["id"])
    assert "findings" in r and "as_of_current" not in r      # the deliberate path is unchanged


# ------------------------------------------------------------------ the write-ahead log

def test_the_log_is_truncated_when_it_grows():
    p = db.create_project("wal", brief="b")
    _notes(p["id"], 400)
    before = db.wal_bytes()
    r = db.checkpoint_wal(force=True)
    assert r["checkpointed"] is True
    assert db.wal_bytes() <= before
    assert r["wal_bytes"] == db.wal_bytes()


def test_a_small_log_is_left_alone():
    r = db.checkpoint_wal()
    assert r["checkpointed"] is False and "threshold" in r["why"]


def test_the_size_limit_is_set_on_every_connection():
    lim = db.connect().execute("PRAGMA journal_size_limit").fetchone()[0]
    assert int(lim) == db.WAL_LIMIT_BYTES


def test_health_reports_the_log_and_says_when_it_is_too_big():
    h = db.health()["storage"]
    assert "wal_mb" in h and "db_mb" in h and h["wal_over_threshold"] is False
    assert "checkpointed normally" in h["note"]


def test_a_checkpoint_failure_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("a reader holds an older snapshot")
    monkeypatch.setattr(db, "connect", boom)
    r = db.checkpoint_wal(force=True)
    assert r["checkpointed"] is False and "older snapshot" in r["why"]


def test_housekeeping_runs_on_its_own_loop():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "jobs.py"), encoding="utf-8").read()
    assert "_housekeeping_loop" in src and '"ns-housekeeping"' in src
    assert "db.checkpoint_wal()" in src


# ------------------------------------------------------------------ the workbench assembles its rows once (0.61.4)

def test_the_workbench_assembles_its_rows_once_per_revision():
    """`/findings` measured 23.2 s cold and 4.3 s warm on the 16,962-note project, and every request repeated the
    same assembly: every row loaded with its full text, every citations blob parsed, every derived field rebuilt.
    Filtering and sorting the dicts is milliseconds; assembling them is the bill."""
    from neurosearch import findings_view
    p = db.create_project("rows", brief="b")
    _notes(p["id"], 30)
    calls: list[str] = []
    real = findings_view._rows_only

    def counted(pid):
        calls.append(pid)
        return real(pid)

    findings_view._rows_only = counted
    try:
        first = findings_view.query(p["id"], status="approved")
        second = findings_view.query(p["id"], status="approved", q="specific")
        third = findings_view.query(p["id"], status="approved", sort="oldest")
    finally:
        findings_view._rows_only = real
    assert len(calls) == 1                                  # three different queries, one assembly
    assert first["total"] == 30 and third["total"] == 30
    assert second["total"] >= 1


def test_a_new_finding_retires_the_assembly():
    """Deliberately not stale-tolerant: a page of findings must never show a status the user just changed."""
    from neurosearch import findings_view
    p = db.create_project("rows2", brief="b")
    _notes(p["id"], 5)
    assert findings_view.query(p["id"], status="approved")["total"] == 5
    _notes(p["id"], 3)
    assert findings_view.query(p["id"], status="approved")["total"] == 8


def test_the_background_loop_warms_the_workbench_too():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "jobs.py"), encoding="utf-8").read()
    assert "findings_view.decorated" in src and "research_view.areas" in src
