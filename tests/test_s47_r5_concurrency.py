"""Foundation R5: bounded child execution preserves job context and deterministic ordering."""
from __future__ import annotations

import os
import tempfile
import threading
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_r5_concurrency_"))
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest

from neurosearch import breakers, claims, concurrency, db, findings, jobs, logctx, providers, usage
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def test_bounded_map_carries_job_policy_log_context_and_order(fresh):
    seen = []
    active = peak = 0
    lock = threading.Lock()

    def work(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.01 * (4 - item))
            seen.append((jobs.current_job(), providers.current_policy(), logctx.get().get("project_id")))
            providers._tl.route = {"executed_by": "api", "reason": "test", "fallback_reason": None}
            providers._accumulate_route()
            return item * 10
        finally:
            with lock:
                active -= 1

    with jobs.bound_current("job-r5", "run-r5"), providers.policy_context("api_requested"), logctx.context(project_id="project-r5"):
        providers.reset_job_route()
        result = concurrency.bounded_map(work, [1, 2, 3], max_workers=2)
        route = providers.job_route()

    assert result == [10, 20, 30]
    assert peak == 2
    assert seen and all(row == (("job-r5", "run-r5"), "api_requested", "project-r5") for row in seen)
    assert route == ("api", None)


def test_bounded_map_stops_admission_after_first_failure(fresh):
    started = []
    release = threading.Event()

    def work(item):
        started.append(item)
        if item == 0:
            release.wait(1)
            raise RuntimeError("unit failed")
        release.set()
        time.sleep(0.02)
        return item

    with pytest.raises(RuntimeError, match="unit failed"):
        concurrency.bounded_map(work, range(8), max_workers=2)

    assert set(started).issubset({0, 1}), "no later unit may be admitted after the first failed wave"


def test_bounded_map_closes_each_child_database_connection(fresh, monkeypatch):
    closed = []
    original = db.close_thread_connection

    def close():
        closed.append(threading.get_ident())
        original()

    monkeypatch.setattr(db, "close_thread_connection", close)
    assert concurrency.bounded_map(lambda n: n, [1, 2, 3], max_workers=2) == [1, 2, 3]
    assert len(closed) == 3


def test_findings_job_fans_out_with_explicit_context_and_deterministic_materialization(fresh, monkeypatch):
    project = db.create_project("R5", brief="parallel facts")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("src-r5", "manual", "src-r5", "manual://src-r5", "Parallel", "ready", 1.0, 1.0),
        )
        conn.execute("INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                     ("src-r5", 0, 0.0, 10.0, "parallel source"))
    windows = [f"window {i}" for i in range(4)]
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: windows)
    active = peak = 0
    seen = []
    lock = threading.Lock()

    def call(system, user, *args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            seen.append((jobs.current_job(), providers.current_policy()))
            time.sleep(0.03 if "part 1/4" in user else 0.01)
            findings._last_model["model"] = "test-model"
            return {"summary": user.splitlines()[0], "substance": 50, "findings": []}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(findings, "_call", call)
    with jobs.bound_current("job-findings", "run-findings"), providers.policy_context("api_requested"):
        providers.reset_job_route()
        result = findings.suggest_for_source(project["id"], "src-r5", force=True)

    assert result["windows"] == 4
    assert peak == 3
    assert result["summary"].startswith("TRANSCRIPT (part 1/4): TRANSCRIPT (part 2/4):")
    assert all(row == (("job-findings", "run-findings"), "api_requested") for row in seen)
    units = db.work_units_for_parent("findings.extract", project["id"], "src-r5", findings.input_hash(project, "src-r5"))
    assert [u["unit_index"] for u in units] == [0, 1, 2, 3]


def test_concurrent_estimates_cannot_race_around_spend_ceiling(fresh, monkeypatch):
    calls = []
    monkeypatch.setattr(usage, "check", lambda estimate=0.0: (estimate <= 1.0, "ceiling", 60))

    def work(item):
        calls.append(item)
        time.sleep(0.03)
        return item

    with pytest.raises(usage.BudgetPaused, match="ceiling"):
        concurrency.bounded_map(work, [1, 2], max_workers=2, estimate=lambda item: 0.6)
    assert len(calls) == 1


def test_child_provider_invocations_keep_parent_job_and_run_ids(fresh):
    class Response:
        model = "claude-sonnet-5"
        id = "response"

    call = providers._Ledgered(lambda **kwargs: Response(), "anthropic", "findings.extract",
                               policy={"max_attempts": 1, "backoff": []})
    with jobs.bound_current("job-ledger", "run-ledger"), providers.policy_context("api_requested"):
        concurrency.bounded_map(lambda item: call(model="claude-sonnet-5", messages=[{"role": "user", "content": str(item)}]),
                                [1, 2, 3], max_workers=2)
    rows = db.connect().execute("SELECT job_id, run_id, state FROM invocations ORDER BY requested_at").fetchall()
    assert len(rows) == 3
    assert all((r["job_id"], r["run_id"], r["state"]) == ("job-ledger", "run-ledger", "completed") for r in rows)


def test_parallel_first_successes_initialize_one_breaker_row(fresh):
    assert concurrency.bounded_map(
        lambda n: breakers.record_success("anthropic:r5-test", f"worker-{n}"), range(4), max_workers=4
    ) == [False, False, False, False]
    assert db.connect().execute("SELECT COUNT(*) FROM circuit_breakers WHERE operation='anthropic:r5-test'").fetchone()[0] == 1


def test_claim_groups_fan_out_only_inside_a_job(fresh, monkeypatch):
    project = db.create_project("R5 Claims", brief="parallel normalization")
    for i in range(claims.EXTRACT_GROUP * 2):
        claims.add_claim(project["id"], text=f"Candidate claim {i} about financing.", normalized=False)
    active = peak = 0
    seen = []
    lock = threading.Lock()

    def invoke(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            seen.append((jobs.current_job(), providers.current_policy()))
            time.sleep(0.03)
            return {"claims": [], "targets": []}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(providers, "invoke_structured", invoke)
    monkeypatch.setattr(providers, "routing_json", lambda *args: "{}")
    with jobs.bound_current("job-claims", "run-claims"), providers.policy_context("api_requested"):
        result = claims.extract(project["id"], transport="job", max_groups=2)
    assert result["calls"] == 2
    assert peak == 2
    assert all(row == (("job-claims", "run-claims"), "api_requested") for row in seen)


def test_claim_input_change_keeps_parallel_units_but_materializes_nothing(fresh, monkeypatch):
    project = db.create_project("R5 Claims Mutation", brief="old brief")
    for i in range(claims.EXTRACT_GROUP * 2):
        claims.add_claim(project["id"], text=f"Mutable claim {i}.", normalized=False)
    changed = threading.Event()

    def invoke(*args, **kwargs):
        if not changed.is_set():
            db.update_project(project["id"], brief="new brief")
            changed.set()
        time.sleep(0.01)
        return {"claims": [], "targets": []}

    monkeypatch.setattr(providers, "invoke_structured", invoke)
    monkeypatch.setattr(providers, "routing_json", lambda *args: "{}")
    with jobs.bound_current("job-mutation", "run-mutation"), providers.policy_context("api_requested"):
        with pytest.raises(RuntimeError, match="inputs changed"):
            claims.extract(project["id"], transport="job", max_groups=2)
    assert db.connect().execute("SELECT COUNT(*) FROM work_units WHERE task='claims.extract'").fetchone()[0] == 2
    assert db.connect().execute("SELECT COUNT(*) FROM project_claims WHERE normalized=1").fetchone()[0] == 0


def test_parent_cancellation_stops_admission_and_keeps_running_unit_results(fresh, monkeypatch):
    started = []
    completed = []
    cancel_set = threading.Event()

    def work(item):
        started.append(item)
        if item == 0:
            completed.append(item)
            cancel_set.set()
            return item
        if item == 1:
            cancel_set.wait(1)
            time.sleep(0.03)
            completed.append(item)  # provider response was durable before cancellation was observed
            jobs.check_cancel()
        jobs.check_cancel()         # newly admitted work stops before provider execution
        completed.append(item)
        return item

    monkeypatch.setattr(db, "cancel_requested", lambda job_id: job_id == "job-cancel" and cancel_set.is_set())
    with jobs.bound_current("job-cancel", "run-cancel"):
        with pytest.raises(jobs.Cancelled):
            concurrency.bounded_map(work, range(8), max_workers=2)
    assert completed == [0, 1]
    assert set(started).issubset({0, 1, 2})
    assert not set(range(3, 8)).intersection(started)


def test_parallel_crash_with_seven_of_twelve_retries_only_five(fresh):
    durable = {}
    calls = []
    crash = {"enabled": True}
    blockers_started = threading.Barrier(3)
    release_blockers = threading.Event()

    def work(item):
        if item in durable:
            return durable[item]
        calls.append(item)
        if crash["enabled"] and item in (7, 8):
            blockers_started.wait(1)
            release_blockers.wait(1)
            raise jobs.SimulatedCrash("parallel_process_death")
        durable[item] = item
        if crash["enabled"] and item == 6:
            blockers_started.wait(1)
            release_blockers.set()
            raise jobs.SimulatedCrash("parallel_process_death")
        return item

    with pytest.raises(jobs.SimulatedCrash):
        concurrency.bounded_map(work, range(12), max_workers=3)
    assert sorted(durable) == list(range(7))
    crash["enabled"] = False
    before_retry = len(calls)
    assert concurrency.bounded_map(work, range(12), max_workers=3) == list(range(12))
    assert len(calls) - before_retry == 5
