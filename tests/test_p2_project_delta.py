"""L-31 (EXECUTION-LADDER.md Stage 4, PRODUCT-INTELLIGENCE-MISSION.md section 6): Project Delta v0, data only.
Every assertion below checks that a number `delta.for_envelope()` reports reconciles to the actual table row(s)
it claims to summarize -- the gate this rung asks for -- not just that the function runs without raising."""
from __future__ import annotations

import json
import time

import pytest

from neurosearch import db, delta, nightly, t4


@pytest.fixture
def p2d_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)          # always "past the hour" in a test
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str, text: str) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id, url=f"manual://{external_id}", title=external_id, status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
    return sid


def _project(name: str, n: int):
    project = db.create_project(name, brief="find the durable facts")
    sids = [_source(project["id"], f"{name}-s{i}", f"We paid ${100 + i} for item {i} last quarter.") for i in range(n)]
    db.connect().commit()
    return project, sids


def test_unknown_envelope_id_returns_found_false(p2d_db):
    d = delta.for_envelope("nightly-1999-01-01")
    assert d == {"envelope_id": "nightly-1999-01-01", "found": False,
                 "reason": "no envelope record in kv for this id (unrecognised producer, or it hasn't run yet)"}


def test_unrecognised_producer_returns_found_false(p2d_db):
    d = delta.for_envelope("some-other-producer-42")
    assert d["found"] is False


def test_delta_sources_read_and_budget_reconcile_to_the_run_record(p2d_db):
    project, sids = _project("solo", 2)
    r = nightly.run()
    assert r["ran"] is True

    d = delta.for_envelope(r["envelope_id"])
    assert d["found"] is True
    assert d["budget"]["authorized_usd"] == 2.0
    assert d["budget"]["estimated_usd"] == r["spent_estimate"]
    assert len(d["projects"]) == 1
    pd = d["projects"][0]
    assert pd["project_id"] == project["id"]
    assert pd["what_neuro_did"]["sources_read"] == r["projects"][0]["count"]
    assert pd["what_neuro_did"]["job_ids"] == r["projects"][0]["job_ids"]


def test_delta_spend_reconciles_to_the_usage_table(p2d_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2   # comfortably inside [start, "now"]
    db.connect().execute(
        "INSERT INTO usage (ts, kind, cost, project_id) VALUES (?, 'findings', 0.0137, ?)",
        (window_ts, project["id"]))
    # a spend row OUTSIDE the window (well before the envelope started) must never be counted
    db.connect().execute(
        "INSERT INTO usage (ts, kind, cost, project_id) VALUES (?, 'findings', 9.99, ?)",
        (r["ts"] - 3600, project["id"]))
    db.connect().commit()

    d = delta.for_envelope(r["envelope_id"])
    pd = d["projects"][0]
    assert pd["what_neuro_did"]["spend_usd"] == pytest.approx(0.0137)
    assert d["budget"]["actual_usd"] == pytest.approx(0.0137)


def test_delta_counts_findings_suggested_only_inside_the_envelope_window(p2d_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "a suggested finding", "[]", window_ts, "suggested"))
    # a note from before the envelope started must not be counted as this run's work
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "an old finding", "[]", r["ts"] - 3600, "suggested"))
    # an approved (not suggested) note in-window must not be double counted as newly-suggested work either
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "an approved finding", "[]", window_ts, "approved"))
    db.connect().commit()

    d = delta.for_envelope(r["envelope_id"])
    pd = d["projects"][0]
    assert pd["what_neuro_did"]["findings_suggested"] == 1
    assert "1 new finding(s) suggested" in pd["why_it_matters"]
    assert pd["what_should_happen_next"] == "review suggested findings"


def test_delta_counts_sources_stopped_by_the_substance_probe(p2d_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    prefilter = json.dumps({"substance_probe": {"substance_floor": 30, "window_substance": 5, "stopped": True, "windows_skipped": 2}})
    db.connect().execute(
        "INSERT INTO project_source_analysis (project_id, source_id, analysis_kind, created_at, updated_at, prefilter) "
        "VALUES (?,?,?,?,?,?)",
        (project["id"], sids[0], "summary", window_ts, window_ts, prefilter))
    db.connect().commit()

    d = delta.for_envelope(r["envelope_id"])
    pd = d["projects"][0]
    assert pd["what_neuro_did"]["sources_stopped_by_probe"] == 1
    assert sids[0] in pd["what_neuro_did"]["revision_at_run"]
    assert "stopped early by the substance probe" in pd["why_it_matters"]


def test_delta_counts_new_tensions_only_inside_the_window(p2d_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("t1", project["id"], "CONTRADICTION", "two sources disagree", window_ts, window_ts))
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, description, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("t2-old", project["id"], "STALE", "an old one", r["ts"] - 3600, r["ts"] - 3600))
    db.connect().commit()

    d = delta.for_envelope(r["envelope_id"])
    assert d["new_tensions_total"] == 1
    pd = d["projects"][0]
    assert pd["what_changed"]["new_tensions"] == {"CONTRADICTION": 1}
    assert pd["what_should_happen_next"] == "review new tension(s)"


def test_delta_computes_a_real_coverage_delta_from_the_before_snapshot(p2d_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    snapshot_before = r["projects"][0]["snapshot_before"]
    assert snapshot_before is not None and snapshot_before["status"] == "measured"
    assert snapshot_before["canonical_findings"] == 0            # nothing suggested yet when the snapshot was taken

    # simulate the batch job's own completion adding a new suggested finding after the snapshot was taken
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "a suggested finding", "[]", window_ts, "suggested"))
    db.connect().commit()

    d = delta.for_envelope(r["envelope_id"])
    cov = d["projects"][0]["what_changed"]["coverage"]
    assert cov["available"] is True
    assert cov["canonical_findings"] == {"before": 0, "after": 1, "delta": 1}


def test_delta_reports_a_failed_project_and_asks_the_user_without_crashing(p2d_db):
    bad, _ = _project("bad", 1)
    good, _ = _project("good", 1)

    real_execute = t4.execute

    def flaky(project_id, **kw):
        if project_id == bad["id"]:
            raise RuntimeError("provider outage during selection")
        return real_execute(project_id, **kw)

    import unittest.mock
    with unittest.mock.patch.object(t4, "execute", flaky):
        r = nightly.run()
    assert r["ran"] is True

    d = delta.for_envelope(r["envelope_id"])
    by_pid = {pd["project_id"]: pd for pd in d["projects"]}
    assert "provider outage during selection" in by_pid[bad["id"]]["error"]
    assert by_pid[bad["id"]]["what_should_happen_next"].startswith("investigate")
    assert any(item["project_id"] == bad["id"] for item in d["needs_user"])
    # the good project's own delta must still be computed normally despite the other project's failure
    assert by_pid[good["id"]]["what_neuro_did"]["sources_read"] >= 0
    assert "error" not in by_pid[good["id"]]
