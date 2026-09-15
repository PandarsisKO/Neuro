"""L-61 (EXECUTION-LADDER.md Stage 8, P6 T6): surface an assumption only where it changes what the user should
know. Gate (P6): output appears because it changes what the user should know or do, not because the subsystem has
data to display -- so the tests pin the NEGATIVE cases as hard as the positive ones: a quiet night says nothing,
an operational default never surfaces, and a mechanism that did not fire surfaces nothing."""
from __future__ import annotations

from datetime import date

import pytest

from neurosearch import assumptions, t6
from neurosearch.assumptions import Assumption


def _delta(*, stopped=0, suggested=0, read=1, projects=1, adjudicated=0):
    return {
        "projects": [{"project_id": f"p{i}", "what_neuro_did": {"sources_stopped_by_probe": stopped, "findings_suggested": suggested,
                                                                "sources_read": read}} for i in range(projects)],
        "adjudication": {"count": adjudicated} if adjudicated else None,
    }


def _reg(monkeypatch, *entries):
    monkeypatch.setattr(assumptions, "REGISTRY", tuple(entries))


def _a(name, *, measured, kind="threshold", exercised=(), measured_on=None, module="neurosearch.t4", attr="PROBE_DISCOUNT"):
    return Assumption(name=name, module=module, attr=attr, why="w", measured=measured, evidence="e", how_to_verify="verify it",
                      kind=kind, measured_on=measured_on, exercised_by=tuple(exercised))


def test_mechanisms_fired_is_read_off_the_record_conservatively():
    assert t6.mechanisms_fired(_delta(read=0)) == set()
    assert t6.mechanisms_fired(_delta(read=1)) == {"findings_extract"}
    assert t6.mechanisms_fired(_delta(stopped=2)) >= {"substance_probe"}
    assert t6.mechanisms_fired(_delta(suggested=1)) >= {"findings_clusters", "findings_extract"}
    assert "nightly_budget_walk" in t6.mechanisms_fired(_delta(projects=2))
    assert "nightly_budget_walk" not in t6.mechanisms_fired(_delta(projects=1))
    assert "adjudication" in t6.mechanisms_fired(_delta(adjudicated=1))
    assert t6.mechanisms_fired({"projects": [{"project_id": "x", "error": "boom"}]}) == set()


def test_quiet_night_surfaces_nothing_even_with_unmeasured_thresholds_registered(monkeypatch):
    _reg(monkeypatch, _a("FLOOR", measured=False, exercised=("substance_probe",)))
    out = t6.surface(_delta(read=1))                 # the probe did not stop anything tonight
    assert out["items"] == [] and t6.render_lines(out) == []


def test_unmeasured_threshold_surfaces_only_when_its_mechanism_fired(monkeypatch):
    _reg(monkeypatch, _a("FLOOR", measured=False, exercised=("substance_probe",)))
    out = t6.surface(_delta(stopped=3))
    assert [x["name"] for x in out["items"]] == ["FLOOR"]
    assert out["items"][0]["kind"] == "unmeasured_exercised"
    assert "never been measured" in out["items"][0]["why_now"] and "substance_probe" in out["items"][0]["why_now"]
    lines = t6.render_lines(out)
    assert lines[0].strip().startswith("Numbers tonight leaned on") and "FLOOR" in lines[1]


def test_operational_defaults_never_surface_unless_broken(monkeypatch):
    _reg(monkeypatch, _a("CONC", measured=False, kind="default", exercised=("findings_extract",)))
    assert t6.surface(_delta(read=5))["items"] == []


def test_measured_but_stale_surfaces_as_a_recheck_not_a_verdict(monkeypatch):
    _reg(monkeypatch,
         _a("OLD", measured=True, measured_on="2026-01-01", exercised=("findings_clusters",)),
         _a("FRESH", measured=True, measured_on="2026-09-01", exercised=("findings_clusters",)))
    out = t6.surface(_delta(suggested=2), today=date(2026, 9, 15))
    assert [x["name"] for x in out["items"]] == ["OLD"]
    assert out["items"][0]["kind"] == "stale_exercised" and "days old" in out["items"][0]["why_now"]


def test_unresolvable_constant_always_surfaces_first_even_on_a_quiet_night(monkeypatch):
    _reg(monkeypatch,
         _a("GONE", measured=True, attr="THIS_DOES_NOT_EXIST", exercised=()),
         _a("FLOOR", measured=False, exercised=("substance_probe",)))
    out = t6.surface(_delta(stopped=1))
    assert [x["kind"] for x in out["items"]] == ["unresolvable", "unmeasured_exercised"]
    assert t6.surface(_delta(read=0))["items"][0]["name"] == "GONE"


def test_render_is_capped_and_points_at_the_json(monkeypatch):
    _reg(monkeypatch, *[_a(f"T{i}", measured=False, exercised=("substance_probe",)) for i in range(5)])
    lines = t6.render_lines(t6.surface(_delta(stopped=1)))
    assert len(lines) == 1 + t6.MAX_LINES + 1 and "and 2 more" in lines[-1]


def test_real_registry_resolves_and_the_night_numbers_are_registered():
    rows = {r["name"]: r for r in assumptions.list_assumptions()}
    assert not any(str(r["value"]).startswith("ERROR:") for r in rows.values())
    assert rows["DEFAULT_SUBSTANCE_FLOOR"]["measured"] is False and "substance_probe" in rows["DEFAULT_SUBSTANCE_FLOOR"]["exercised_by"]
    assert rows["PROBE_DISCOUNT"]["measured_on"] == "2026-09-14"
    from neurosearch import t4
    assert t4.DEFAULT_SUBSTANCE_FLOOR == rows["DEFAULT_SUBSTANCE_FLOOR"]["value"] == 30


def test_morning_report_carries_t6_last_and_a_broken_constant_breaks_the_quiet_path(tmp_path, monkeypatch):
    from neurosearch import db, nightly, report, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data"); settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True); monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0); monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "t5_nightly_budget", 0.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    db._local.conn = None; db.init_db()
    try:
        pid = db.create_project("t6", "b")["id"]
        sid = db.upsert_source(platform="manual", external_id="s", url="manual://s", title="s", status="ready")["id"]
        db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
        db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, 10, "some text."))
        db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, "some text."))
        db.connect().commit()
        r = nightly.run()
        text = report.render_text(report.for_envelope(r["envelope_id"]))
        assert "Nothing important changed overnight." in text and "Numbers tonight" not in text

        _reg(monkeypatch, _a("GONE", measured=True, attr="THIS_DOES_NOT_EXIST"))
        text = report.render_text(report.for_envelope(r["envelope_id"]))
        assert "one of the numbers the system runs on is broken" in text and "GONE" in text
    finally:
        db.close_thread_connection()
