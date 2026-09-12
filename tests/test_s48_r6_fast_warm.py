"""Foundation R6: deterministic Fast/Warm/Deep admission over existing durable jobs."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_r6_fast_warm_"))
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest

from neurosearch import api, db, jobs
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def _project_and_sources():
    project = db.create_project("R6", brief="find acquisition financing and operating evidence")
    rows = [("a", "Alpha", 99), ("b", "Alpha", 98), ("c", "Beta", 70),
            ("d", "Gamma", 69), ("e", "Delta", 40), ("f", "Epsilon", 20)]
    ids = []
    for key, channel, score in rows:
        src = db.upsert_source(platform="youtube", external_id=f"r6-{key}", url=f"https://example.test/{key}",
                               title=f"{key} financing evidence", description="acquisition financing", channel=channel, status="ready")
        db.add_project_sources(project["id"], [src["id"]])
        db.upsert_analysis(project["id"], src["id"], "relevance", relevance=score, relevance_why="review")
        ids.append(src["id"])
    return project, ids


def test_fast_wave_is_diverse_deterministic_and_keeps_every_source_eligible(fresh):
    project, ids = _project_and_sources()
    first = jobs.fast_wave_plan(project["id"], ids)
    second = jobs.fast_wave_plan(project["id"], list(reversed(ids)))
    assert [x["source_id"] for x in first] == [x["source_id"] for x in second]
    assert [x["source_id"] for x in first] == [ids[0], ids[2], ids[3]]
    assert len({x["creator"] for x in first}) == 3

    scheduled = jobs.enqueue_fast_warm(project["id"], ids)
    assert scheduled["fast"] == [ids[0], ids[2], ids[3]]
    assert scheduled["warm"] == [ids[1], ids[4], ids[5]]
    by_source = {(j["payload"]["source_ids"][0]): j for j in scheduled["jobs"]}
    assert all(by_source[sid]["lane"] == "priority" and by_source[sid]["execution_policy"] == "api_requested"
               and by_source[sid]["payload"]["r6_provisional"] for sid in scheduled["fast"])
    assert all(by_source[sid]["lane"] == "normal" and by_source[sid]["execution_policy"] == "local_preferred"
               and not by_source[sid]["payload"]["r6_provisional"] for sid in scheduled["warm"])


def test_warm_promotion_reuses_the_same_job(fresh):
    project, ids = _project_and_sources()
    scheduled = jobs.enqueue_fast_warm(project["id"], ids)
    warm_id = next(j["id"] for j in scheduled["jobs"] if j["payload"]["source_ids"] == [ids[1]])
    promoted = jobs.promote_warm_sources(project["id"], [ids[1]])
    assert promoted["job_ids"] == [warm_id]
    job = db.get_job(warm_id)
    assert job["lane"] == "priority" and job["execution_policy"] == "api_requested"
    assert len([j for j in db.list_jobs(limit=50) if j["payload"].get("source_ids") == [ids[1]]]) == 1


def test_bulk_interactive_endpoint_returns_provisional_fast_and_warm_contract(fresh):
    project, ids = _project_and_sources()
    out = api.api_suggest(project["id"], api.SuggestIn(source_ids=ids))
    assert out["provisional"] is True
    assert len(out["fast"]) == jobs.FAST_WAVE_SIZE and len(out["warm"]) == len(ids) - jobs.FAST_WAVE_SIZE
    assert len(out["jobs"]) == len(ids)


def test_fast_provenance_is_visible_and_later_analysis_revises_it(fresh):
    project, ids = _project_and_sources()
    db.upsert_analysis(project["id"], ids[0], "summary", summary="early result", r6_wave="fast", r6_provisional=1)
    row = next(r for r in api.api_sources(project_id=project["id"], limit=20) if r["id"] == ids[0])
    assert row["r6_wave"] == "fast" and row["r6_provisional"] is True
    # A later warm/deep materialization is a normal current artifact; it replaces the provisional marker.
    db.upsert_analysis(project["id"], ids[0], "summary", summary="later contradictory evidence", r6_wave="warm", r6_provisional=0)
    revised = next(r for r in api.api_sources(project_id=project["id"], limit=20) if r["id"] == ids[0])
    assert revised["summary"] == "later contradictory evidence"
    assert revised["r6_wave"] == "warm" and revised["r6_provisional"] is False
