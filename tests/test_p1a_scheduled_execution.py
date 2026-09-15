"""L-20 (EXECUTION-LADDER.md P1A, PRODUCT-INTELLIGENCE-MISSION.md §4 missed-window policy): not_before
productized as a caller-facing feature, not just internal retry/budget machinery. Covers:

1. db.create_job(..., not_before=ts) makes a job unclaimable before ts and claimable at/after it, tags it
   wait_reason='scheduled', and preserves the request in payload["_scheduled_for"] (claim_job() nulls the
   not_before column itself at claim time, so this is the only place the original request survives).
2. jobs.execute() records the missed-window provenance the ruling asks for -- scheduled time, actual start
   time, reason -- as a job_event, for every job that carries _scheduled_for.
3. A job whose deadline (payload["_deadline"]) has already passed by the time it's claimed is cancelled with a
   clear reason and never runs its actual work -- "executing late would violate the task's semantics."
4. The budget/pause resume sweep in api.py (POST /api/usage settings) must never wake a wait_reason='scheduled'
   job early -- only a wait_reason='budget' (or unlabeled) queued job's not_before is a budget-related wait.
5. staleness.rebuild(..., not_before=ts) threads the schedule into every job it creates (suggest_findings and,
   through its dependency barrier, build_plan)."""
from __future__ import annotations

import time

import pytest

from neurosearch import db, findings, ingest, jobs, staleness


@pytest.fixture
def p1a_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    db._local.conn = None
    db.init_db()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db.close_thread_connection()


def test_not_before_gates_claiming_and_survives_in_payload_for_provenance(p1a_db):
    future = db.now() + 3600
    job = db.create_job("reembed", {}, not_before=future)
    assert job["not_before"] == future
    assert job["wait_reason"] == "scheduled"
    assert job["payload"]["_scheduled_for"] == future

    assert db.claim_job(("reembed",), worker_id="w") is None, "must not be claimable before its scheduled time"

    # move the clock past the schedule by editing the row directly (no sleep in a test)
    db.connect().execute("UPDATE jobs SET not_before=? WHERE id=?", (db.now() - 1, job["id"]))
    db.connect().commit()
    claimed = db.claim_job(("reembed",), worker_id="w")
    assert claimed and claimed["id"] == job["id"]
    assert claimed["payload"]["_scheduled_for"] == future, "the original request survives claiming, which nulls the not_before column itself"


def test_execute_records_scheduled_vs_actual_start_provenance(p1a_db):
    scheduled = db.now() - 5           # already due, so it claims and runs immediately
    job = db.create_job("reembed", {}, not_before=scheduled)
    claimed = db.claim_job(("reembed",), worker_id="w")
    jobs.execute(claimed, "w")
    events = [e for e in db.job_events(job["id"]) if e["event_type"] == "scheduled_run_started"]
    assert len(events) == 1
    ev = events[0]["payload"]
    assert ev["scheduled"] == scheduled
    assert ev["actual"] >= scheduled
    assert ev["delay_seconds"] >= 0
    assert ev["reason"]


def test_a_job_whose_deadline_already_passed_is_cancelled_not_run(p1a_db):
    scheduled = db.now() - 100
    deadline = db.now() - 10          # the deadline already passed before this job was even claimed
    job = db.create_job("reembed", {"_deadline": deadline}, not_before=scheduled)
    claimed = db.claim_job(("reembed",), worker_id="w")
    outcome = jobs.execute(claimed, "w")
    assert outcome == "cancelled"
    row = db.get_job(job["id"])
    assert row["status"] == "cancelled"
    assert "deadline" in (row["message"] or "").lower()
    missed = [e for e in db.job_events(job["id"]) if e["event_type"] == "missed_window"]
    assert len(missed) == 1 and missed[0]["payload"]["reason"] == "deadline passed"


def test_budget_resume_sweep_never_wakes_a_scheduled_job_early(p1a_db):
    from neurosearch import api

    future = db.now() + 3600
    scheduled_job = db.create_job("reembed", {}, not_before=future)
    budget_job = db.create_job("reembed", {})
    db.requeue_job(budget_job["id"], delay=3600, message="paused: daily budget reached", wait_reason="budget")

    # The real endpoint function, called directly (no HTTP layer needed) -- exactly what a "raise the daily
    # budget" or "Resume" click in the UI triggers.
    api.api_budget(api.BudgetIn(daily=100.0))

    sched_row = db.get_job(scheduled_job["id"])
    budget_row = db.get_job(budget_job["id"])
    assert sched_row["not_before"] == future, "a caller-requested schedule must never be cleared by the budget/pause resume sweep"
    assert budget_row["not_before"] is None, "a genuine budget wait IS cleared by the same sweep"


def _stale_project():
    p = db.create_project("P1A", "hosting")
    text = "0:05 provider0 pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks"
    r = ingest.ingest_text("Hosting talk", text, project_id=p["id"])
    findings.suggest_for_source(p["id"], r["source_id"], force=True)
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (p["id"], r["source_id"]))
    db.connect().commit()
    db.update_project(p["id"], brief="hosting and email deliverability")     # inputs changed: the source is now stale
    return p, r["source_id"]


def test_staleness_rebuild_threads_not_before_into_every_job_it_creates(p1a_db):
    p, sid = _stale_project()
    t = staleness.triage(p["id"])
    assert sid in {r["source_id"] for r in t["tiers"]["rebuild_matters"]["sources"]}, "fixture must actually land in a rebuildable tier"

    future = db.now() + 3600
    res = staleness.rebuild(p["id"], ["findings"], [sid], not_before=future)
    assert res["queued"] == 1
    row = db.get_job(res["job_ids"][0])
    assert row["not_before"] == future
    assert row["wait_reason"] == "scheduled"
    assert row["payload"]["_scheduled_for"] == future
