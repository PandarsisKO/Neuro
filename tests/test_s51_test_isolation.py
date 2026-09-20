"""S51 — no test may reach the live database. (Sorts after test_s50.)

On 2026-09-12 a focused run of one module wrote ten projects into Kyle's production database and queued jobs the
live server executed with real providers. `tests/conftest.py` now hard-sets `NEUROSEARCH_DATA_DIR` before any
module imports; this file makes sure nothing weakens that and that the resolved data dir is never the repo's own.
"""
from pathlib import Path
import os, re, tempfile

TESTS = Path(__file__).resolve().parent
REPO_DATA = (TESTS.parent / "data").resolve()


def test_bootstrap_blocks_dotenv_from_restoring_stripped_overrides(tmp_path):
    """Exercise the real bootstrap/config import against an adversarial, synthetic dotenv file."""
    import subprocess
    import sys

    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=unwanted-model\n"
                           "NEUROSEARCH_AI_PROFILE=local\nNEUROSEARCH_FAKE_AI=1\n"
                           "NEUROSEARCH_DATA_DIR=/not-a-test-database\n")
    code = """
import os, runpy, sys, dotenv.main
from pathlib import Path
os.environ.pop('PYTHON_DOTENV_DISABLED', None)
dotenv.main.find_dotenv = lambda *a, **kw: sys.argv[1]
runpy.run_path('tests/conftest.py')
from neurosearch.config import settings
assert settings.ai_profile == 'cloud' and settings.fake_ai is False
assert 'NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT' not in os.environ
assert Path(settings.data_dir).name.startswith('ns_pytest_')
"""
    result = subprocess.run([sys.executable, "-c", code, str(dotenv_file)], cwd=TESTS.parent,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_chat_collection_does_not_enable_fake_ai():
    import subprocess
    import sys

    code = """
import os, runpy
runpy.run_path('tests/conftest.py')
for path in ('tests/test_chr0_conversation_baseline.py', 'tests/test_chr1_conversation_delta.py'):
    runpy.run_path(path)
from neurosearch.config import settings
assert settings.fake_ai is False
assert os.environ['NEUROSEARCH_FAKE_AI'] == '0'
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=TESTS.parent,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_conftest_hard_sets_the_data_dir_before_any_module():
    src = (TESTS / "conftest.py").read_text(encoding="utf-8")
    assert re.search(r'^os\.environ\["NEUROSEARCH_DATA_DIR"\]\s*=\s*tempfile\.mkdtemp', src, re.M), \
        "conftest.py must hard-set NEUROSEARCH_DATA_DIR (not setdefault) — a developer .env otherwise wins"


def test_no_module_relies_on_setdefault_for_the_data_dir():
    # setdefault is harmless now that conftest wins, but a future removal of the conftest line would silently
    # re-open the hole; keep the ratchet visible so it only ever goes down from the current 71-module baseline.
    offenders = sorted(p.name for p in TESTS.glob("test_*.py")
                       if p.name != Path(__file__).name and 'setdefault("NEUROSEARCH_DATA_DIR"' in p.read_text(encoding="utf-8"))
    assert len(offenders) <= 71, f"new module uses setdefault for the data dir: {offenders}"


def test_resolved_data_dir_is_a_private_temp_dir_not_the_repo():
    d = Path(os.environ["NEUROSEARCH_DATA_DIR"]).resolve()
    assert d != REPO_DATA and REPO_DATA not in d.parents, f"tests resolved to the live data dir: {d}"
    assert Path(tempfile.gettempdir()).resolve() in d.parents or "ns_" in d.name, f"unexpected data dir: {d}"
    from neurosearch.config import settings
    assert Path(settings.data_dir).resolve() == d, "settings.data_dir disagrees with the environment"


def test_fresh_database_does_not_inherit_an_open_provider_breaker(tmp_path, monkeypatch):
    """A provider outage in one isolated test database cannot poison the next database."""
    from neurosearch import breakers, db
    from neurosearch.config import settings

    # S51-b (2026-09-16): this test swaps settings.data_dir twice and re-binds db._local.conn to throwaway dirs.
    # monkeypatch restores settings.data_dir on teardown, but it never touches db._local.conn -- left bound to
    # 'second' (below), the NEXT test to call db.connect() on this same xdist worker/thread would silently keep
    # querying 'second's now-out-of-scope database instead of the real per-worker session database, because
    # db.connect() only re-resolves the path when _local.conn is None (see db.connect()'s own docstring/comment).
    # Proven with a standalone reproducer outside pytest before this fix landed (see HANDOFF.md, 2026-09-16).
    # db.close_thread_connection() is the existing, already-safe teardown primitive ("never opens a DB during
    # cleanup") -- the same one tests/test_core.py's `isolated_db` fixture already uses on its own teardown path.
    try:
        first = tmp_path / "first"
        first.mkdir()
        monkeypatch.setattr(settings, "data_dir", first)
        db._local.conn = None
        db.init_db()
        for _ in range(breakers.FAILURE_THRESHOLD):
            breakers.record_failure("openai:embeddings", "OVERLOADED", "isolation-test")
        assert breakers.get("openai:embeddings")["state"] == breakers.OPEN

        second = tmp_path / "second"
        second.mkdir()
        db._local.conn = None
        monkeypatch.setattr(settings, "data_dir", second)
        db.init_db()
        state = breakers.get("openai:embeddings")
        assert state["state"] == breakers.CLOSED
        assert state["failures"] == 0
    finally:
        db.close_thread_connection()


def test_a_test_that_swaps_data_dir_does_not_leak_its_connection_to_the_next_one(tmp_path, monkeypatch):
    """Regression for the exact leak fixed above: a test that rebinds db._local.conn to a throwaway data_dir must
    not leave the NEXT connect() call (simulating the next test on the same worker thread) bound to it, even
    after settings.data_dir itself has been restored (e.g. by monkeypatch's own teardown)."""
    from neurosearch import db
    from neurosearch.config import settings

    session_dir = settings.data_dir  # the real per-worker session dir conftest.py already set up

    throwaway = tmp_path / "throwaway"
    throwaway.mkdir()
    monkeypatch.setattr(settings, "data_dir", throwaway)
    db._local.conn = None
    db.init_db()
    db.close_thread_connection()   # what the fixed test above now does in its own `finally`
    # monkeypatch's fixture teardown restores settings.data_dir to session_dir here in real usage; emulate it
    # explicitly since this test controls its own monkeypatch scope directly.
    monkeypatch.setattr(settings, "data_dir", session_dir)

    conn = db.connect()
    row = conn.execute("PRAGMA database_list").fetchone()
    actual_path = row["file"] if hasattr(row, "keys") else row[2]
    assert str(throwaway) not in actual_path, f"connect() is still bound to the throwaway dir: {actual_path}"
    assert str(session_dir) in actual_path, f"connect() did not resolve back to the session dir: {actual_path}"


def test_a_connection_opened_by_one_thread_self_heals_when_data_dir_moves_on_without_it(tmp_path, monkeypatch):
    """The actual mechanism proven live in HANDOFF.md (2026-09-16): a FastAPI sync route handler runs on a
    pooled anyio worker thread, not the main test thread. A test file's autouse fixture that swaps
    settings.data_dir for one test resets db._local.conn on the MAIN thread only on teardown -- it cannot reach
    whichever anyio worker thread served that test's client.*() calls and opened ITS OWN connection to the
    swapped dir. That SAME pooled thread is reused later by an unrelated test and, before this fix, kept
    returning the swapped-away database. db.connect() must self-heal on ANY thread whose cached connection no
    longer matches the current settings.data_dir -- not only the thread that performed the swap.
    A threading.Event hands the SAME worker thread two jobs in sequence (exactly how a real thread pool reuses
    an idle thread across two unrelated requests), so this proves self-healing on reuse, not just a fresh
    thread's ordinary first connect()."""
    import threading
    from neurosearch import db
    from neurosearch.config import settings

    session_dir = settings.data_dir
    first = tmp_path / "first"; first.mkdir()
    result: dict = {}
    job1_done, job2_ready, job2_done = threading.Event(), threading.Event(), threading.Event()

    def pooled_worker():
        # job 1: connect while settings.data_dir points at the swapped-away 'first' dir
        conn = db.connect()
        row = conn.execute("PRAGMA database_list").fetchone()
        result["path_during_swap"] = row["file"] if hasattr(row, "keys") else row[2]
        job1_done.set()
        job2_ready.wait(timeout=5)
        # job 2: the SAME thread is handed a new job after settings.data_dir has moved back
        conn2 = db.connect()
        row2 = conn2.execute("PRAGMA database_list").fetchone()
        result["path_after_swap"] = row2["file"] if hasattr(row2, "keys") else row2[2]
        job2_done.set()

    monkeypatch.setattr(settings, "data_dir", first)
    db.init_db()   # so the worker thread's first connect() has a schema to open against
    t = threading.Thread(target=pooled_worker)
    t.start()
    assert job1_done.wait(timeout=5)
    assert str(first) in result["path_during_swap"]

    # the swap ends, as if the test that caused it finished and its own fixture restored settings.data_dir --
    # the main thread never touches the worker thread's thread-local state, matching the real anyio pool
    monkeypatch.setattr(settings, "data_dir", session_dir)
    job2_ready.set()
    assert job2_done.wait(timeout=5)
    t.join(timeout=5)

    assert str(first) not in result["path_after_swap"], \
        f"a reused thread must not still be bound to the swapped-away dir: {result['path_after_swap']}"
    assert str(session_dir) in result["path_after_swap"], \
        f"a reused thread must self-heal to the current data_dir: {result['path_after_swap']}"
