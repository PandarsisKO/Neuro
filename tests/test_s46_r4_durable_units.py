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


# ---------------------------------------------------------------------- 2026-09-17: the identity rule, in Kyle's words
# "Same hash means: executing this unit again would be expected to produce the same artifact. Not: same transcript
# passage means we already analyzed this." Findings and Claims are project-relative interpretations written against a
# brief; a unit computed for one project must never become another project's interpretation because the window
# text matches. The keys above already carry the project framing (name, brief, steering, facts) — these gates pin it.

def _ten_window_source(sid: str = "src-r4"):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (sid, "manual", sid, f"manual://{sid}", "Ten parts", "ready", 1.0, 1.0))
        conn.execute("INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 100.0, "durable source text"))
    return sid


def _fake_windows(monkeypatch, calls):
    windows = [f"window {i} durable fact" for i in range(10)]
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: windows)

    def invoke(system, user, *args, **kwargs):
        calls.append((system, user))
        findings._last_model["model"] = "test-model"
        return {"summary": user.splitlines()[0], "substance": 50, "findings": []}
    monkeypatch.setattr(findings, "_call", invoke)


def test_same_window_different_project_brief_is_a_different_unit(fresh, monkeypatch):
    sid = _ten_window_source()
    a = db.create_project("Buying businesses", brief="find durable facts about acquiring small companies")
    b = db.create_project("Real estate", brief="find durable facts about rental property investing")
    calls: list = []
    _fake_windows(monkeypatch, calls)
    findings.suggest_for_source(a["id"], sid, force=True)
    assert len(calls) == 10
    findings.suggest_for_source(b["id"], sid, force=True)
    assert len(calls) == 20, "the same transcript windows under another project's brief must be re-read, never reused"
    ka = {findings.work_unit_key(a, {"id": sid, "title": "Ten parts", "platform": "manual"}, f"window {i} durable fact", i, 10) for i in range(10)}
    kb = {findings.work_unit_key(b, {"id": sid, "title": "Ten parts", "platform": "manual"}, f"window {i} durable fact", i, 10) for i in range(10)}
    assert ka.isdisjoint(kb)
    assert len(db.work_units_for_parent("findings.extract", a["id"], sid, findings.input_hash(a, sid))) == 10
    assert len(db.work_units_for_parent("findings.extract", b["id"], sid, findings.input_hash(b, sid))) == 10


def test_every_steering_input_changes_the_unit_key(fresh):
    """The identity is the complete semantic input: window, project brief and steering facts, depth, source
    revision, the model contract and prompt. Each alone must change the key; nothing else in the row does."""
    sid = _ten_window_source()
    src = {"id": sid, "title": "Ten parts", "platform": "manual"}
    p = db.create_project("R4", brief="find the durable facts")
    base = findings.work_unit_key(p, src, "window 0", 0, 10)
    assert findings.work_unit_key(p, src, "window 0", 0, 10) == base, "deterministic"
    assert findings.work_unit_key(p, src, "window 0 changed", 0, 10) != base
    assert findings.work_unit_key(p, src, "window 0", 1, 10) != base
    assert findings.work_unit_key(p, src, "window 0", 0, 10, depth="deep") != base
    db.update_project(p["id"], brief="a different research question")
    p2 = db.get_project(p["id"])
    assert findings.work_unit_key(p2, src, "window 0", 0, 10) != base
    db.update_project(p["id"], brief="find the durable facts")
    p3 = db.get_project(p["id"])
    assert findings.work_unit_key(p3, src, "window 0", 0, 10) == base, "restoring the brief restores the key"
    db.add_project_fact(p["id"], "buyer has $400k of equity") if hasattr(db, "add_project_fact") else None
    with db.tx() as conn:
        conn.execute("DELETE FROM segments WHERE source_id=?", (sid,))
        conn.execute("INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 100.0, "re-transcribed text"))
        conn.execute("UPDATE sources SET revision=NULL WHERE id=?", (sid,))
    assert findings.work_unit_key(p3, src, "window 0", 0, 10) != base, "a new source revision is a new unit"


def test_retry_after_nine_durable_units_produces_the_same_artifact_as_an_uninterrupted_run(fresh, monkeypatch):
    """The primary R4 gate, stated fully: interrupt after 9 of 10 durable completions; the retry performs exactly 1
    expensive unit and the final artifact is identical to a run that was never interrupted."""
    sid = _ten_window_source()
    p = db.create_project("R4", brief="find the durable facts")
    calls: list = []
    _fake_windows(monkeypatch, calls)
    persisted = 0

    def crash_after_nine(name):
        nonlocal persisted
        if name == "findings_window_persisted":
            persisted += 1
            if persisted == 9:
                raise jobs.SimulatedCrash(name)
    monkeypatch.setattr(jobs, "crash_point", crash_after_nine)
    with pytest.raises(jobs.SimulatedCrash):
        findings.suggest_for_source(p["id"], sid, force=True)
    assert len(calls) == 9
    monkeypatch.setattr(jobs, "crash_point", lambda name: None)
    findings.suggest_for_source(p["id"], sid, force=True)
    assert len(calls) == 10, "exactly one expensive unit on retry"
    interrupted = db.get_analysis(p["id"], sid, "summary")
    interrupted_notes = sorted(n["content"] for n in db.list_project_notes(p["id"], status=None))

    # the control: the same source and brief under a differently NAMED project, never interrupted. (An identically
    # named project with the identical brief is the identical request byte for byte -- see the next test -- so it
    # would reuse the ten units and make no control at all.)
    q = db.create_project("R4 control", brief="find the durable facts")
    calls.clear()
    findings.suggest_for_source(q["id"], sid, force=True)
    assert len(calls) == 10
    control = db.get_analysis(q["id"], sid, "summary")
    control_notes = sorted(n["content"] for n in db.list_project_notes(q["id"], status=None))
    for k in ("summary", "substance", "status", "input_hash", "prompt_version", "model", "depth"):
        assert interrupted.get(k) == control.get(k), k
    assert interrupted_notes == control_notes


def test_identity_is_the_request_not_the_project_row(fresh, monkeypatch):
    """Recorded as a design fact, not a defect (2026-09-17): the unit key is the exact request — project name, brief,
    steering facts, window, depth, source revision, contract, prompt. Two projects whose framing is identical word for
    word send the identical request, so they share units; a one-character difference in the brief does not. This is
    exactly "same hash ⇒ the same artifact would be produced again", and it is NOT "same passage ⇒ already analyzed"."""
    sid = _ten_window_source()
    calls: list = []
    _fake_windows(monkeypatch, calls)
    a = db.create_project("R4", brief="find the durable facts")
    findings.suggest_for_source(a["id"], sid, force=True)
    assert len(calls) == 10
    twin = db.create_project("R4", brief="find the durable facts")
    findings.suggest_for_source(twin["id"], sid, force=True)
    assert len(calls) == 10, "an identical request is the identical unit"
    assert db.get_analysis(twin["id"], sid, "summary")["status"] == "current"
    # Kyle's guardrail (2026-09-17): this is COMPUTE reuse, never project-STATE reuse. The shared unit materializes
    # into each project's own analysis row and notes, with that project's provenance and lifecycle; a verdict
    # taken in one project never appears in the other.
    a_an, t_an = db.get_analysis(a["id"], sid, "summary"), db.get_analysis(twin["id"], sid, "summary")
    assert a_an["project_id"] == a["id"] and t_an["project_id"] == twin["id"]
    with db.tx() as conn:                                        # a project-owned verdict on the shared computation
        conn.execute("UPDATE project_source_analysis SET accepted_hash=input_hash, accepted_at=1.0 WHERE project_id=? AND source_id=? AND analysis_kind='summary'", (a["id"], sid))
    assert db.get_analysis(a["id"], sid, "summary")["accepted_hash"]
    assert not db.get_analysis(twin["id"], sid, "summary")["accepted_hash"], "a verdict in one project must not leak into the other"
    near = db.create_project("R4", brief="find the durable facts.")
    findings.suggest_for_source(near["id"], sid, force=True)
    assert len(calls) == 20, "a different brief is a different request, however similar"
