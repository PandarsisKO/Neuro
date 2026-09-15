"""findings.suggest_for_source(substance_floor=...): the T4 substance probe. Off by default; when on, a low first
window stops the read, the probe is a normal durable work unit, and the verdict is recorded on the analysis row."""
import json

import pytest

from neurosearch import db, findings, jobs
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    jobs._current.job_id = jobs._current.run_id = None
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def _source_and_project():
    project = db.create_project("floor", brief="find the durable facts")
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("src-floor", "manual", "src-floor", "manual://src-floor", "Three parts", "ready", 1.0, 1.0))
        conn.execute("INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                     ("src-floor", 0, 0.0, 100.0, "source text"))
    return project, "src-floor"


def _install(monkeypatch, substances: list[int]):
    """Fake _call: window i reports substances[i]; records which windows were actually read."""
    windows = [f"window {i} text" for i in range(len(substances))]
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: windows)
    read: list[int] = []

    def invoke(system, user, *args, **kwargs):
        i = next(idx for idx, w in enumerate(windows) if w in user)
        read.append(i)
        findings._last_model["model"] = "test-model"
        return {"summary": f"part {i}", "substance": substances[i],
                "findings": [{"title": f"finding {i}", "finding": "", "ts": "0:01", "quote": "source text", "importance": 3}]}

    monkeypatch.setattr(findings, "_call", invoke)
    return read


def _analysis_prefilter(project_id, source_id):
    row = db.get_analysis(project_id, source_id, "summary")
    pf = row.get("prefilter")
    return json.loads(pf) if isinstance(pf, str) else pf


def test_floor_off_by_default_reads_every_window(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [5, 5, 5])
    findings.suggest_for_source(project["id"], sid, force=True)
    assert sorted(read) == [0, 1, 2]
    assert _analysis_prefilter(project["id"], sid) is None


def test_low_first_window_stops_the_read_and_records_the_probe(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [12, 90, 90])
    result = findings.suggest_for_source(project["id"], sid, force=True, substance_floor=30)
    assert read == [0]                                            # windows 1 and 2 were never paid for
    assert result["windows"] == 1 or result.get("windows") in (1, 3)
    probe = _analysis_prefilter(project["id"], sid)["substance_probe"]
    assert probe == {"substance_floor": 30, "window_substance": 12, "stopped": True, "windows_skipped": 2, "reused": False}
    assert db.connect().execute("SELECT COUNT(*) FROM work_units WHERE source_id=?", (sid,)).fetchone()[0] == 1


def test_high_first_window_reads_everything_and_never_pays_for_the_probe_twice(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [80, 40, 40])
    findings.suggest_for_source(project["id"], sid, force=True, substance_floor=30)
    assert sorted(read) == [0, 1, 2] and read.count(0) == 1      # window 0 read once: the main pass reused the probe's unit
    probe = _analysis_prefilter(project["id"], sid)["substance_probe"]
    assert probe["stopped"] is False and probe["windows_skipped"] == 0 and probe["window_substance"] == 80


def test_unreadable_substance_fails_open(fresh, monkeypatch):
    project, sid = _source_and_project()
    windows = ["window 0 text", "window 1 text"]
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: windows)
    read = []

    def invoke(system, user, *args, **kwargs):
        i = 0 if windows[0] in user else 1
        read.append(i)
        findings._last_model["model"] = "test-model"
        return {"summary": "x", "substance": "n/a", "findings": []}

    monkeypatch.setattr(findings, "_call", invoke)
    findings.suggest_for_source(project["id"], sid, force=True, substance_floor=30)
    assert sorted(read) == [0, 1]
    assert _analysis_prefilter(project["id"], sid)["substance_probe"]["stopped"] is False


def test_single_window_source_is_not_probed(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [1])
    findings.suggest_for_source(project["id"], sid, force=True, substance_floor=30)
    assert read == [0]
    assert _analysis_prefilter(project["id"], sid) is None      # nothing to skip, nothing recorded


def test_suggest_for_project_passes_the_floor_through(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [12, 90, 90])
    result = findings.suggest_for_project(project["id"], [sid], substance_floor=30)
    assert read == [0]
    assert result == {"sources": 1, "done": 1, "failed": 0, "skipped": 0}   # substance-floor stop is not "skipped": it read window 0 for real, floor just stopped the rest
    probe = _analysis_prefilter(project["id"], sid)["substance_probe"]
    assert probe["stopped"] is True and probe["windows_skipped"] == 2


def test_suggest_for_project_without_floor_is_the_old_path(fresh, monkeypatch):
    project, sid = _source_and_project()
    read = _install(monkeypatch, [12, 90, 90])
    findings.suggest_for_project(project["id"], [sid])
    assert sorted(read) == [0, 1, 2]
    assert _analysis_prefilter(project["id"], sid) is None


def test_suggest_findings_job_passes_the_floor_through(fresh, monkeypatch):
    from neurosearch import jobs

    project, sid = _source_and_project()
    read = _install(monkeypatch, [12, 90, 90])
    job = db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [sid], "substance_floor": 30})
    jobs.run_job(job)
    assert read == [0]
    probe = _analysis_prefilter(project["id"], sid)["substance_probe"]
    assert probe["stopped"] is True


def test_suggest_findings_job_without_floor_key_is_the_old_path(fresh, monkeypatch):
    from neurosearch import jobs

    project, sid = _source_and_project()
    read = _install(monkeypatch, [12, 90, 90])
    job = db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [sid]})
    jobs.run_job(job)
    assert sorted(read) == [0, 1, 2]
    assert _analysis_prefilter(project["id"], sid) is None
