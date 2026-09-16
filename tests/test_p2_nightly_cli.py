"""CLI surface for L-30 / L-41: `neurosearch nightly status|run|report`. Exercised through typer's CliRunner
against a fixture database. `run` is real paid work, so the cost-disclosure-then-confirm path is what these
tests pin hardest: the authorized amount is printed BEFORE anything runs, and a declined confirmation runs
nothing."""
from __future__ import annotations

import time

import pytest
from typer.testing import CliRunner

from neurosearch import db, nightly, t4
from neurosearch.cli import app

runner = CliRunner()


@pytest.fixture
def cli_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project_with_source(name="solo"):
    p = db.create_project(name, brief="find the durable facts")
    sid = db.upsert_source(platform="manual", external_id=f"{name}-s0", url=f"manual://{name}", title=name, status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, 30, "We paid $100 for item last quarter."))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, "We paid $100 for item last quarter."))
    db.connect().commit()
    return p, sid


def test_status_when_off_says_off_and_how_to_turn_on(cli_db):
    r = runner.invoke(app, ["nightly", "status"])
    assert r.exit_code == 0, r.output
    assert "OFF" in r.output
    assert "NEUROSEARCH_T4_NIGHTLY_BUDGET_USD" in r.output


def test_run_refuses_when_off_and_no_budget_given(cli_db):
    _project_with_source()
    r = runner.invoke(app, ["nightly", "run", "--yes"])
    assert r.exit_code == 1
    assert nightly.last_run() is None, "nothing may run with the budget at 0"


def test_run_discloses_the_authorized_amount_and_a_declined_confirm_runs_nothing(cli_db):
    _project_with_source()
    r = runner.invoke(app, ["nightly", "run", "--budget", "2"], input="n\n")
    assert r.exit_code == 0, r.output
    assert "authorizing up to $2.00 TOTAL" in r.output
    assert "shared cap" in r.output
    assert nightly.last_run() is None, "declining the confirmation must enqueue nothing"
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == 0


def test_run_with_yes_runs_once_and_a_second_run_needs_force(cli_db):
    _project_with_source()
    r = runner.invoke(app, ["nightly", "run", "--budget", "2", "--yes"])
    assert r.exit_code == 0, r.output
    assert nightly.last_run() is not None and nightly.last_run()["ok"] is True
    jobs_after_first = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    assert jobs_after_first == 1

    r2 = runner.invoke(app, ["nightly", "run", "--budget", "2", "--yes"])
    assert r2.exit_code == 0
    assert "already ran" in r2.output
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == jobs_after_first


def test_report_renders_the_morning_report_for_today(cli_db):
    p, sid = _project_with_source()
    runner.invoke(app, ["nightly", "run", "--budget", "2", "--yes"])
    r = runner.invoke(app, ["nightly", "report"])
    assert r.exit_code == 0, r.output
    assert "Morning Report — nightly-" in r.output
    assert "Nothing important changed overnight." in r.output

    # a material change shows up in the same command, no flags needed
    window_ts = (nightly.last_run()["ts"] + time.time()) / 2
    db.connect().execute("INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
                         (p["id"], "a suggested finding", "[]", window_ts, "suggested"))
    db.connect().commit()
    r = runner.invoke(app, ["nightly", "report"])
    assert "What changed: 1 new finding(s) suggested" in r.output
    assert "need to review" not in r.output.lower()


def test_report_for_a_night_that_never_ran_exits_nonzero_with_a_plain_message(cli_db):
    r = runner.invoke(app, ["nightly", "report", "--date", "1999-01-01"])
    assert r.exit_code == 1
    assert "No overnight report for nightly-1999-01-01" in r.output


def test_report_json_returns_the_underlying_data(cli_db):
    import json
    _project_with_source()
    runner.invoke(app, ["nightly", "run", "--budget", "2", "--yes"])
    r = runner.invoke(app, ["nightly", "report", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["found"] is True and data["budget"]["authorized_usd"] == 2.0


def test_run_discloses_the_separate_t5_cap(cli_db):
    _project_with_source()
    r = runner.invoke(app, ["nightly", "run", "--budget", "2", "--t5-budget", "1"], input="n\n")
    assert r.exit_code == 0, r.output
    assert "authorizing up to $2.00 TOTAL" in r.output and "plus up to $1.00 for T5 adjudication" in r.output
    assert nightly.last_run() is None
    # --t5-budget is scoped to THIS invocation only (config.override, CR8b hardening 2026-09-16) -- no manual
    # reset needed here any more; a second invocation with no --t5-budget just sees the real default again.
    r = runner.invoke(app, ["nightly", "run", "--budget", "2"], input="n\n")
    assert "T5 adjudication: off" in r.output
