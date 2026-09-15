"""Foundation R4: completed interactive Findings windows survive an incomplete parent."""
from __future__ import annotations

import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_r4_units_"))
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest

from neurosearch import claims, db, findings, jobs, providers
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    # Module-level environment assignments are too late when another test has
    # already imported the cached settings object. Keep this suite deterministic
    # in every collection order and prevent accidental live-provider calls.
    monkeypatch.setattr(settings, "fake_ai", True)
    # Direct `jobs.run_job` tests leave the thread-local execution marker set;
    # clear it before this interactive path decides whether to fan out windows.
    jobs._current.job_id = jobs._current.run_id = None
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def _source_and_project():
    project = db.create_project("R4", brief="find the durable facts")
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("src-r4", "manual", "src-r4", "manual://src-r4", "Ten parts", "ready", 1.0, 1.0),
        )
        conn.execute(
            "INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
            ("src-r4", 0, 0.0, 100.0, "durable source text"),
        )
    return project, "src-r4"


@pytest.mark.parametrize("completed_count", [1, 9])
def test_completed_windows_survive_parent_crash_and_retry_runs_only_missing(fresh, monkeypatch, completed_count):
    project, source_id = _source_and_project()
    windows = [f"window {i} durable fact" for i in range(10)]
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: windows)
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        return {"summary": user.splitlines()[0], "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    persisted = 0

    def crash_after_checkpoint(name):
        nonlocal persisted
        if name == "findings_window_persisted":
            persisted += 1
            if persisted == completed_count:
                raise jobs.SimulatedCrash(name)

    monkeypatch.setattr(jobs, "crash_point", crash_after_checkpoint)
    with pytest.raises(jobs.SimulatedCrash):
        findings.suggest_for_source(project["id"], source_id, force=True)

    parent_hash = findings.input_hash(project, source_id)
    assert len(calls) == completed_count
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, parent_hash)) == completed_count
    assert db.get_analysis(project["id"], source_id, "summary") is None

    monkeypatch.setattr(jobs, "crash_point", lambda name: None)
    result = findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 10, "the retry must pay only for missing windows"
    assert result["windows"] == 10
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, parent_hash)) == 10
    assert db.get_analysis(project["id"], source_id, "summary")["status"] == "current"


def test_changed_brief_cannot_reuse_or_materialize_old_units(fresh, monkeypatch):
    project, source_id = _source_and_project()
    windows = ["first", "second"]
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: windows)
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    findings.suggest_for_source(project["id"], source_id, force=True)
    old_hash = findings.input_hash(project, source_id)

    db.update_project(project["id"], brief="a materially different research question")
    changed = db.get_project(project["id"])
    findings.suggest_for_source(project["id"], source_id, force=True)
    new_hash = findings.input_hash(changed, source_id)

    assert old_hash != new_hash
    assert len(calls) == 4
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, old_hash)) == 2
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, new_hash)) == 2
    assert db.get_analysis(project["id"], source_id, "summary")["input_hash"] == new_hash


def test_cancel_after_paid_response_keeps_unit_but_not_parent(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["first", "second"])
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    checks = 0

    def cancel_after_first_response():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise jobs.Cancelled("cancelled")

    monkeypatch.setattr(jobs, "check_cancel", cancel_after_first_response)
    with pytest.raises(jobs.Cancelled):
        findings.suggest_for_source(project["id"], source_id, force=True)

    parent_hash = findings.input_hash(project, source_id)
    assert len(calls) == 1
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, parent_hash)) == 1
    assert db.get_analysis(project["id"], source_id, "summary") is None

    monkeypatch.setattr(jobs, "check_cancel", lambda: None)
    findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 2


def test_brief_change_during_call_keeps_old_unit_but_cannot_finish_parent(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["first", "second"])
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        if len(calls) == 1:
            db.update_project(project["id"], brief="changed while the provider was running")
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    old_hash = findings.input_hash(project, source_id)
    with pytest.raises(jobs.Yield, match="inputs changed"):
        findings.suggest_for_source(project["id"], source_id, force=True)

    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, old_hash)) == 1
    assert db.get_analysis(project["id"], source_id, "summary") is None

    findings.suggest_for_source(project["id"], source_id, force=True)
    current = db.get_project(project["id"])
    assert len(calls) == 3
    assert db.get_analysis(project["id"], source_id, "summary")["input_hash"] == findings.input_hash(current, source_id)


def test_source_revision_change_during_call_cannot_materialize_mixed_units(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["first", "second"])
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        if len(calls) == 1:
            db.replace_transcript(source_id, [{"start": 0.0, "end": 1.0, "text": "replacement transcript"}], [])
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    old_hash = findings.input_hash(project, source_id)
    with pytest.raises(jobs.Yield, match="inputs changed"):
        findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, old_hash)) == 1
    assert db.get_analysis(project["id"], source_id, "summary") is None

    findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 3
    assert db.get_analysis(project["id"], source_id, "summary")["input_hash"] == findings.input_hash(project, source_id)


def test_model_contract_change_invalidates_parent_and_units(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["one window"])
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "returned-model"
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    findings.suggest_for_source(project["id"], source_id, force=True)
    old_parent = findings.input_hash(project, source_id)

    monkeypatch.setenv("NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT", "claude-haiku-4-5")
    new_parent = findings.input_hash(project, source_id)
    assert new_parent != old_parent
    assert not findings.is_current(project, source_id)

    findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 2
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, old_parent)) == 1
    assert len(db.work_units_for_parent("findings.extract", project["id"], source_id, new_parent)) == 1


def test_provider_failure_retries_only_the_missing_unit(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["first", "second"])
    calls = []
    fail_second = True

    def invoke(system, user, *args, **kwargs):
        nonlocal fail_second
        calls.append(user)
        if "part 2/2" in user and fail_second:
            fail_second = False
            raise RuntimeError("provider timeout")
        findings._last_model["model"] = "test-model"
        return {"summary": "ok", "substance": 50, "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    with pytest.raises(RuntimeError, match="provider timeout"):
        findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 2
    assert db.get_analysis(project["id"], source_id, "summary") is None

    findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 3
    assert db.get_analysis(project["id"], source_id, "summary")["status"] == "current"


def test_duplicate_exact_request_materializes_without_second_spend(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["durable source text"])
    calls = []

    def invoke(system, user, *args, **kwargs):
        calls.append(user)
        findings._last_model["model"] = "test-model"
        return {"summary": "ok", "substance": 50,
                "findings": [{"title": "Durable", "finding": "The source is durable.",
                              "quote": "durable source text", "ts": "0:00", "importance": 5}]}

    monkeypatch.setattr(findings, "_call", invoke)
    findings.suggest_for_source(project["id"], source_id, force=True)
    findings.suggest_for_source(project["id"], source_id, force=True)
    assert len(calls) == 1
    notes = [n for n in db.list_project_notes(project["id"], status="suggested") if n["source_id"] == source_id]
    assert len(notes) == 1


def test_claim_group_response_survives_crash_before_materialization(fresh, monkeypatch):
    project = db.create_project("Claims R4", brief="normalize acquisition claims")
    for i in range(3):
        claims.add_claim(project["id"], f"Seller financing claim {i}", origin="user")
    candidates = claims.unnormalized(project["id"])
    real_invoke = providers.invoke_structured
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_invoke(*args, **kwargs)

    monkeypatch.setattr(providers, "invoke_structured", counted)

    def crash_after_saved(name):
        if name == "claims_group_persisted":
            raise jobs.SimulatedCrash(name)

    monkeypatch.setattr(jobs, "crash_point", crash_after_saved)
    with pytest.raises(jobs.SimulatedCrash):
        claims.extract(project["id"], candidates)
    assert calls == 1
    assert all(not c["normalized"] for c in claims.list_for_project(project["id"]))

    monkeypatch.setattr(jobs, "crash_point", lambda name: None)
    result = claims.extract(project["id"], claims.unnormalized(project["id"]))
    assert calls == 1, "the paid group response must be reused after the parent crash"
    assert result["normalized"] > 0
    assert not claims.unnormalized(project["id"])


def test_concurrent_duplicate_requests_compute_unit_once(fresh, monkeypatch):
    project, source_id = _source_and_project()
    monkeypatch.setattr(findings, "_windows", lambda *args, **kwargs: ["durable source text"])
    calls = 0
    calls_lock = threading.Lock()

    def invoke(system, user, *args, **kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        findings._last_model["model"] = "test-model"
        return {"summary": "ok", "substance": 50,
                "findings": [{"title": "Durable", "finding": "The source is durable.",
                              "quote": "durable source text", "ts": "0:00", "importance": 5}]}

    monkeypatch.setattr(findings, "_call", invoke)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: findings.suggest_for_source(project["id"], source_id, force=True), range(2)))

    assert calls == 1
    assert [r["suggested"] for r in results] == [1, 1]
    notes = [n for n in db.list_project_notes(project["id"], status="suggested") if n["source_id"] == source_id]
    assert len(notes) == 1
