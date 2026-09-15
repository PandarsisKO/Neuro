"""L-70 prep: the P7 dollar estimate Kyle must decide on is a $0 read. Pins: varied selection (per-platform cap,
longest first, excluded/unready never chosen), Arm A priced by the app's own estimator, Arm B labelled as an
assumption, no provider call, nothing written."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("p7_estimate", Path(__file__).resolve().parents[1] / "tools" / "p7_estimate.py")
p7 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(p7)  # type: ignore[union-attr]

from neurosearch import db, usage  # noqa: E402


@pytest.fixture
def p7_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data"); settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None; db.init_db()
    yield
    db.close_thread_connection()


def _src(pid, ext, platform, duration=None, chars=0, status="ready", excluded=0):
    sid = db.upsert_source(platform=platform, external_id=ext, url=f"{platform}://{ext}", title=ext, status=status, duration=duration)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,?)", (pid, sid, excluded))
    if chars:
        db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 1.0, "x" * chars))
    db.connect().commit()
    return sid


def test_selection_is_long_first_varied_and_skips_excluded_or_unready(p7_db):
    pid = db.create_project("p7", "b")["id"]
    for i in range(6):
        _src(pid, f"yt{i}", "youtube", duration=3600 * (6 - i))
    _src(pid, "pod", "podcast", duration=100)
    _src(pid, "file", "file", chars=50000)
    _src(pid, "gone", "youtube", duration=99999, excluded=1)
    _src(pid, "pending", "youtube", duration=99999, status="pending")
    picked = p7.select_sources(pid, n=20, per_platform=4)
    plats = [s["platform"] for s in picked]
    assert plats.count("youtube") == 4 and "podcast" in plats and "file" in plats
    assert all(s["title"] not in ("gone", "pending") for s in picked)
    assert picked[0]["title"] == "yt0", "longest first"


def test_arm_a_is_the_apps_own_estimate_and_arm_b_is_a_labelled_assumption(p7_db, monkeypatch):
    pid = db.create_project("p7", "b")["id"]
    a = _src(pid, "a", "youtube", duration=3600); b = _src(pid, "b", "file", chars=40000)
    called = []
    monkeypatch.setattr(p7, "select_sources", lambda *args, **kw: [{"source_id": a, "title": "a", "platform": "youtube", "duration": 3600, "chars": 0},
                                                                    {"source_id": b, "title": "b", "platform": "file", "duration": None, "chars": 40000}])
    r = p7.estimate(pid, n=2)
    expected_a = usage.estimate_source_findings(a) + usage.estimate_source_findings(b)
    assert r["arm_a_usd"] == pytest.approx(round(expected_a, 2), abs=0.01)
    assert r["arm_b_usd_assumed"] > r["arm_a_usd"] and "ASSUMPTION" in r["arm_b_basis"]
    assert r["total_usd_assumed"] == pytest.approx(round(r["arm_a_usd"] + r["arm_b_usd_assumed"], 2), abs=0.02)
    assert db.connect().execute("SELECT COUNT(*) n FROM usage").fetchone()["n"] == 0, "an estimate spends nothing"
