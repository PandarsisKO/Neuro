"""Pause and resume the speculative lanes only (Kyle, live 2026-09-09).

"I need it to get out of the way of 'real' work when I start adding new sources or do something on my own ... it
needs to be non blocking or allow interruption. manual pause and resume would be good."

The app already had a queue pause, but it stopped EVERYTHING including the ingest he had just started, which is
exactly why it was never the control he wanted. This one holds `slow`/`low` — bulk claim passes, caption recovery,
metadata backfill — and nothing else. (Sorts after test_p4.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_bg_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, db  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    db.kv_set("background_paused", "0")
    yield
    db.kv_set("background_paused", "0")
    db._local.conn = None


def test_pausing_background_never_touches_the_users_own_work():
    """The whole point. His ingest and his findings must keep flowing while the bulk work is held."""
    bulk = db.create_job("extract_claims", {"project_id": "p"}, lane="slow")
    backfill = db.create_job("refresh_skipped_metadata", {"source_id": "s"}, lane="low")
    mine = db.create_job("suggest_findings", {"source_ids": ["s1"]}, lane="normal")
    urgent = db.create_job("rank_proposed", {"collection_id": "c"}, lane="priority")

    db.set_background_paused(True)
    claimed = []
    while True:
        j = db.claim_job()
        if not j:
            break
        claimed.append(j["id"])
    assert set(claimed) == {mine["id"], urgent["id"]}                  # his work ran
    assert db.get_job(bulk["id"])["status"] == "queued"                # the bulk work waited
    assert db.get_job(backfill["id"])["status"] == "queued"


def test_resuming_lets_the_held_work_through_again():
    bulk = db.create_job("extract_claims", {"project_id": "p"}, lane="slow")
    db.set_background_paused(True)
    assert db.claim_job() is None
    out = db.set_background_paused(False)
    assert out["paused"] is False
    assert db.claim_job()["id"] == bulk["id"]                          # picked up where it left off


def test_metadata_backfill_replay_is_one_active_job():
    payload = {"project_id": "p", "source_id": "s"}
    first = db.create_job("refresh_skipped_metadata", payload, lane="low")
    replay = db.create_job("refresh_skipped_metadata", payload, lane="low")
    assert replay["id"] == first["id"]
    assert len([j for j in db.list_jobs(limit=20) if j["kind"] == "refresh_skipped_metadata"]) == 1
    assert any(e["event_type"] == "deduplicated" for e in db.job_events(first["id"]))


def test_pausing_asks_a_running_background_job_to_stop_but_leaves_real_work_alone():
    """'allow interruption' — and it is safe because background work is idempotent: a claims group whose
    extraction_hash is stamped is skipped without spend, so resuming re-does no paid work."""
    bulk = db.create_job("extract_claims", {"project_id": "p"}, lane="slow")
    mine = db.create_job("suggest_findings", {"source_ids": ["s1"]}, lane="normal")
    db.claim_job(("extract_claims",)); db.claim_job(("suggest_findings",))
    assert db.get_job(bulk["id"])["status"] == "running" and db.get_job(mine["id"])["status"] == "running"

    out = db.set_background_paused(True)
    assert out["stopped"] == 1
    assert db.cancel_requested(bulk["id"]) is True                     # asked to stop at its next safe point
    assert db.cancel_requested(mine["id"]) is False                    # his own running job untouched


def test_the_endpoint_reports_what_it_held_and_resume_requeues():
    p = db.create_project("BG", "brief")
    db.create_job("extract_claims", {"project_id": p["id"]}, lane="slow")
    out = api.api_background_pause(api.BackgroundPauseIn(paused=True, project_id=p["id"]))
    assert out["paused"] is True and out["waiting"] >= 1
    assert db.background_paused() is True

    back = api.api_background_pause(api.BackgroundPauseIn(paused=False, project_id=p["id"]))
    assert back["paused"] is False and db.background_paused() is False
    assert "requeued" in back                                          # resume re-triggers rather than waiting
