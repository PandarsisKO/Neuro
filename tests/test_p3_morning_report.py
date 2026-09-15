"""L-41 (EXECUTION-LADDER.md Stage 6, PRODUCT-INTELLIGENCE-MISSION.md P3 Morning Report v1, rulings section 7):
"MORNING REPORT V1 MUST NOT PRETEND P4 EXISTS" -- V1 may show what changed / why it matters / what Neuro did /
provisional stale-risk tiers / spend, but must never claim a defensibly-ranked "these are the N things you need
to review". These tests check the honesty constraints directly, not just that rendering doesn't crash."""
from __future__ import annotations

import time

import pytest

from neurosearch import db, nightly, report, t4


@pytest.fixture
def p3_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
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


def test_unknown_envelope_returns_found_false_like_delta_does(p3_db):
    rep = report.for_envelope("nightly-1999-01-01")
    assert rep["found"] is False
    text = report.render_text(rep)
    assert "No overnight report" in text


def test_nothing_changed_is_a_first_class_short_outcome(p3_db):
    _project("solo", 1)
    r = nightly.run()
    rep = report.for_envelope(r["envelope_id"])
    assert rep["material_change"] is False
    text = report.render_text(rep)
    assert "Nothing important changed overnight." in text
    assert "What changed:" not in text          # the short path never falls through to the per-project detail


def test_material_change_renders_what_changed_and_why_it_matters(p3_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "a suggested finding", "[]", window_ts, "suggested"))
    db.connect().commit()

    rep = report.for_envelope(r["envelope_id"])
    assert rep["material_change"] is True
    text = report.render_text(rep)
    assert "What changed: 1 new finding(s) suggested" in text
    assert "Why it matters:" in text
    assert "Needs you: nothing" in text
    assert "What Neuro did: read 1 source(s)" in text


def test_never_claims_a_ranked_judgment_queue(p3_db):
    """Rulings section 7's hard constraint: no form of "these are the N things you need to review" until a
    defensible ranking exists (Stage 7, not yet built). Checked against both a material-change night and a
    quiet one, and against the raw dict (not just the rendered text) since a future UI could read the dict
    directly."""
    project, sids = _project("solo", 1)
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (project["id"], "a suggested finding", "[]", window_ts, "suggested"))
    db.connect().commit()

    rep = report.for_envelope(r["envelope_id"])
    text = report.render_text(rep)
    for banned in ("things you need to review", "you need to review", "top priorit"):
        assert banned not in text.lower()
    import json
    assert "need to review" not in json.dumps(rep).lower()


def test_stale_risk_tiers_are_pulled_from_triages_own_summary_counts_not_miscounted(p3_db):
    """Regression for a real bug caught before this test existed: staleness.triage()'s tiers are ALREADY
    per-tier summary dicts (each carrying its own "count" key, plus cost/line fields) -- not bare lists of
    rows. An earlier draft of report.py did len(tiers[k]) and silently reported the dict's KEY COUNT (11) as
    the tier's source count for every project, every time. This asserts the real semantics directly against a
    project with zero stale sources (freshly created, nothing to rebuild) -- the true count is 0, and 11 would
    be a very loud, very wrong number for a project this small."""
    project, sids = _project("solo", 1)
    r = nightly.run()
    rep = report.for_envelope(r["envelope_id"])
    pd = rep["projects"][0]
    assert pd["staleness_tiers"]["rebuild_matters"]["count"] == 0
    assert pd["staleness_tiers"]["retry_failed"]["count"] == 0


def test_failed_project_is_visible_in_the_rendered_report(p3_db):
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

    rep = report.for_envelope(r["envelope_id"])
    text = report.render_text(rep)
    assert "Did not run: provider outage during selection" in text
    assert "Needs you: investigate why this project's nightly run failed." in text


def test_spend_and_budget_lines_reconcile_to_the_envelope_record(p3_db):
    project, sids = _project("solo", 1)
    r = nightly.run()
    rep = report.for_envelope(r["envelope_id"])
    text = report.render_text(rep)
    assert f"of $2.00 authorized" in text
    assert rep["budget"]["authorized_usd"] == 2.0
    assert rep["budget"]["estimated_usd"] == r["spent_estimate"]
