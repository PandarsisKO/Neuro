"""S98 — a subreddit walk ranks every post, not the newest 400 (Kyle, 2026-09-24).

"we seem to be having issues ranking posts from an entire subreddit": three subreddit cards (999 / 990 / 989 posts,
walked back a year on purpose) each had ~600 posts scored 0 with "beyond ranking pool (older)". `relevance.POOL` caps
a channel's back-catalogue at its newest 400 videos, which is right for an unbounded YouTube channel and wrong for a
window the person chose in the popup. Community listings are uncapped; a "finish the ranking" mode scores only what
no run ever scored, so the 400 real scores already paid for stand.
"""
from __future__ import annotations

import pytest

from neurosearch import db, relevance
from neurosearch.config import settings


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _listing(kind: str, platform: str, n: int, name: str = "one"):
    coll = db.upsert_collection(kind, f"{platform}:{kind}:{name}", "https://example.test/", kind)
    pid = db.create_project("s98", brief="how to build a lazy portfolio")["id"]
    db.kv_set(f"review:{coll['id']}", '{"project_id": "%s"}' % pid)
    for i in range(n):
        s = db.upsert_source(platform=platform, external_id=f"{platform}:{name}:{i}", url=f"https://example.test/{i}", title=f"post {i}", status="proposed")
        db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)", (s["id"], coll["id"]))
    db.connect().commit()
    return coll["id"], pid


def test_a_channel_is_still_capped_but_a_subreddit_is_not(fresh, monkeypatch):
    monkeypatch.setattr(relevance, "POOL", 5)
    chan, pid = _listing("channel", "youtube", 8)
    sub, pid2 = _listing("subreddit", "community", 8)
    assert relevance.pool_cap(chan) == 5 and relevance.pool_cap(sub) is None
    pool, rest = relevance._pool(db.proposed_sources(chan, pid), relevance.pool_cap(chan))
    assert (len(pool), len(rest)) == (5, 3)
    pool, rest = relevance._pool(db.proposed_sources(sub, pid2), relevance.pool_cap(sub))
    assert (len(pool), len(rest)) == (8, 0), "every post the person walked back to get is ranked"


def test_finish_the_ranking_scores_only_what_the_old_cap_left_at_zero(fresh, monkeypatch):
    sub, pid = _listing("subreddit", "community", 6)
    rows = db.proposed_sources(sub, pid)
    for r in rows[:3]:
        db.upsert_analysis(pid, r["id"], "relevance", relevance=70, relevance_why="real score", prompt_version="t", input_hash="h")
    for r in rows[3:5]:
        db.upsert_analysis(pid, r["id"], "relevance", relevance=0, relevance_why=relevance.BEYOND_POOL, prompt_version="t", input_hash="h")
    db.connect().commit()
    rows = db.proposed_sources(sub, pid)
    pool, _ = relevance._pool(rows, None, only_unscored=True)
    assert {r["relevance_why"] for r in pool} == {relevance.BEYOND_POOL, None}, "placeholders and never-scored rows only"
    assert len(pool) == 3
    # the plain path (a re-rank the person pressed: a job created after those scores) still re-scores everything
    import time
    monkeypatch.setattr(relevance, "_job_started", lambda: time.time() + 1)
    pool, _ = relevance._pool(db.proposed_sources(sub, pid), None)
    assert len(pool) == 6


def test_the_rank_endpoint_and_the_job_carry_the_mode(fresh):
    from neurosearch import api
    sub, pid = _listing("subreddit", "community", 2)
    out = api.api_rank(sub, api.RankIn(project_id=pid, only_unscored=True))
    assert db.get_job(out["job_id"])["payload"]["only_unscored"] is True
    sub2, pid2 = _listing("subreddit", "community", 2, name="two")
    out = api.api_rank(sub2, api.RankIn(project_id=pid2))
    assert db.get_job(out["job_id"])["payload"]["only_unscored"] is False


def test_review_can_rerank_after_success_or_failure_until_ingestion(fresh):
    from fastapi import HTTPException
    from neurosearch import api, jobs

    cid, pid = _listing("channel", "youtube", 2)
    db.add_project_collections(pid, [cid])
    request = api.RankIn(project_id=pid)

    def ranking():
        return api.api_reviews(pid)[0]["meta"]["ranking"]

    first = api.api_rank(cid, request)["job_id"]
    assert ranking()
    assert api.api_rank(cid, request)["job_id"] == first
    assert jobs.execute(db.claim_job(("rank_proposed",))) == "done"
    assert not ranking()

    second = api.api_rank(cid, request)["job_id"]
    assert second != first and ranking()
    claimed = db.claim_job(("rank_proposed",))
    assert db.finish_job(second, claimed["run_id"], "failed")
    assert not ranking()

    third = api.api_rank(cid, request)["job_id"]
    assert third != second and ranking()
    sid = db.proposed_sources(cid, pid)[0]["id"]
    assert api.api_approve(cid, api.ApproveIn(source_ids=[sid]))["started"] == 1
    assert api.api_reviews(pid) == []
    with pytest.raises(HTTPException) as rejected:
        api.api_rank(cid, request)
    assert rejected.value.status_code == 409
