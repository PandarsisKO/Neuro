"""S86 (2026-09-23) — per-job pause/resume. Kyle: "theres no pause button on the sources progress window. only cancel.
we need a pause/resume option".

A pause is a HOLD, not a wait and not a cancel: a queued job is simply never claimed until Resume; a running job
stops at its next safe boundary (the hook `check_cancel` already provides in ingest, findings, claims and — from S85 —
the ranker's batch loop), keeps everything it has written, and goes back to the queue held. Resume continues from the
last completed stage. The queue-wide Resume, budget releases and provider wake-ups never lift a person's own pause."""
from __future__ import annotations

import pytest

from neurosearch import db, jobs, relevance
from neurosearch.config import settings

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _collection(pid: str, n: int) -> str:
    coll = db.upsert_collection("channel", "UCpause0001", "https://www.youtube.com/@pause", "A finance channel")
    for i in range(n):
        src = db.upsert_source(platform="youtube", external_id=f"pz{i:08d}", url=f"https://www.youtube.com/watch?v=pz{i:08d}",
                               status="proposed", title=f"Video {i} about budgeting and index funds", description="finance", duration=900)
        db.link_source_collection(src["id"], coll["id"])
    return coll["id"]


def test_a_queued_job_is_held_and_never_claimed_until_resumed():
    jid = db.create_job("rank_proposed", {"collection_id": "c", "project_id": "p"})["id"]
    assert db.request_pause(jid) == "queued"
    j = db.get_job(jid)
    assert j["status"] == "queued" and db.derived_status(j) == "paused" and "press ▶" in j["message"]
    assert db.claim_job(kinds=("rank_proposed",), worker_id="w") is None, "held: no worker may take it"
    assert db.resume_job(jid) == "queued"
    j = db.get_job(jid)
    assert db.derived_status(j) == "queued" and j["not_before"] is None and j["wait_reason"] is None
    assert db.claim_job(kinds=("rank_proposed",), worker_id="w")["id"] == jid
    kinds = [e["event_type"] for e in db.job_events(jid)]
    assert "paused" in kinds and "resumed" in kinds


def test_a_running_job_pauses_at_its_next_safe_point_and_keeps_its_work(monkeypatch):
    """The ranker persists each batch before starting the next; a pause requested mid-run lands between batches."""
    p = db.create_project("Personal finance", "How to build a budget and invest the rest")
    coll = _collection(p["id"], relevance.BATCH * 2)
    jid = db.create_job("rank_proposed", {"collection_id": coll, "project_id": p["id"], "want": 20})["id"]
    claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    real_call = relevance._call
    calls = []
    def call_then_pause(*a, **k):
        calls.append(1)
        res = real_call(*a, **k)
        if len(calls) == 1:
            assert db.request_pause(jid) == "running"        # the person presses ⏸ while batch 1 is being scored
        return res
    monkeypatch.setattr(relevance, "_call", call_then_pause)
    assert jobs.execute(claimed, worker_id="w") == "queued"
    j = db.get_job(jid)
    assert db.derived_status(j) == "paused" and j["run_id"] is None and j["worker_id"] is None
    assert len(calls) == 1, "batch 2 was never started"
    scored = [r for r in db.proposed_sources(coll, p["id"]) if r.get("relevance") is not None]
    assert len(scored) == relevance.BATCH, "batch 1's scores were kept"
    assert db.claim_job(kinds=("rank_proposed",), worker_id="w") is None
    # resume: only the unscored batch is ranked, and the job finishes
    monkeypatch.setattr(relevance, "_call", real_call)
    assert db.resume_job(jid) == "queued"
    claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    assert claimed and claimed["id"] == jid
    assert jobs.execute(claimed, worker_id="w") == "done"
    assert all(r.get("relevance") is not None for r in db.proposed_sources(coll, p["id"]))


def test_pause_wins_over_a_resume_pressed_before_the_safe_point(monkeypatch):
    """Resume while still 'pausing' just withdraws the request — the job never stops."""
    p = db.create_project("Personal finance", "a brief")
    coll = _collection(p["id"], relevance.BATCH * 2)
    jid = db.create_job("rank_proposed", {"collection_id": coll, "project_id": p["id"], "want": 20})["id"]
    claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    real_call = relevance._call
    def call_pause_then_resume(*a, **k):
        res = real_call(*a, **k)
        assert db.request_pause(jid) == "running"
        assert db.derived_status(db.get_job(jid)) == "pausing"
        assert db.resume_job(jid) == "running"
        return res
    monkeypatch.setattr(relevance, "_call", call_pause_then_resume)
    assert jobs.execute(claimed, worker_id="w") == "done"


def test_the_queue_wide_resume_does_not_lift_a_persons_pause(client):
    jid = db.create_job("ingest_source", {"source_id": "s1", "project_id": "p"})["id"]
    other = db.create_job("ingest_source", {"source_id": "s2", "project_id": "p"})["id"]
    db.requeue_job(other, delay=600, message="paused: budget", wait_reason="budget")
    assert client.post(f"/api/jobs/{jid}/pause", headers=H).json()["state"] == "paused"
    assert client.post("/api/usage/budget", json={"paused": False}, headers=H).status_code == 200
    assert db.derived_status(db.get_job(jid)) == "paused", "Resume queue is not Resume THIS job"
    assert db.get_job(other)["not_before"] is None, "the budget-parked one was released as before"
    r = client.post(f"/api/jobs/{jid}/resume", headers=H).json()
    assert r["resumed"] and db.derived_status(db.get_job(jid)) == "queued"


def test_api_refuses_to_pause_finished_or_provider_side_work(client):
    jid = db.create_job("ingest_source", {"source_id": "s1", "project_id": "p"})["id"]
    db.request_cancel(jid)
    assert client.post(f"/api/jobs/{jid}/pause", headers=H).status_code == 409
    assert client.post("/api/jobs/nope/pause", headers=H).status_code == 404


def test_the_jobs_box_offers_pause_and_resume():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "research.js").read_text()
    assert "onclick=\"pauseJob('${j.id}')\"" in js and "onclick=\"resumeJob('${j.id}')\"" in js
    assert "paused: 'paused by you'" in js
    assert "j.state === 'paused' || j.bumped" in js, "a paused job stays in the collapsed view so it can be resumed"
