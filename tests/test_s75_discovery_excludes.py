"""S75 — Discovery exclude list (item 2, Kyle's decision session, 2026-09-20): a short, explicit "not interested
in" list per project that `pool()`/`next_batch()` check on every candidate BEFORE it is ever shown, separate from
the free-text brief (which nothing parses for a hard rule). Real trigger: Kyle's brief already said "laundromats
are rejected as primary target" and `project_facts` already carried two explicit `rejected` rows naming
laundromats and accounting/bookkeeping firms — none of it was ever read by Discovery, so 9 more laundromat videos
from 4 different creators were captured anyway. Per-creator dismissal learning (`creator_disposition`) cannot fix
this: each new creator starts neutral. (Sorts after test_s74.)"""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, candidates, db, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _project():
    return db.create_project("buying businesses", "acquire a business")["id"]


def test_keyword_exclude_hides_matching_candidates_from_the_pool():
    pid = _project()
    candidates.remember([
        {"external_id": "laund-1", "url": "https://example.org/laund-1",
         "title": "This Laundromat Makes $3 Million?", "creator": "Codie Sanchez"},
        {"external_id": "laund-2", "url": "https://example.org/laund-2",
         "title": "Building a 10-Laundromat Empire", "creator": "UpFlip"},
        {"external_id": "ok-1", "url": "https://example.org/ok-1",
         "title": "How to buy an HVAC company with seller financing", "creator": "Acquiring Minds"},
    ], platform="youtube", project_id=pid, origin={"kind": "exploration"})

    before = candidates.pool(pid, kind="candidates", limit=100)
    assert before["counts"]["candidates"] == 3

    db.add_exclude(pid, "keyword", "laundromat", reason="Kyle: rejected as primary target")
    after = candidates.pool(pid, kind="candidates", limit=100)
    titles = {i["title"] for i in after["items"]}
    assert after["counts"]["candidates"] == 1
    assert "How to buy an HVAC company with seller financing" in titles
    assert not any("Laundromat" in t for t in titles)


def test_creator_exclude_hides_every_candidate_from_that_creator_regardless_of_title():
    pid = _project()
    candidates.remember([
        {"external_id": "acct-1", "url": "https://example.org/acct-1",
         "title": "Why we sold our CPA firm", "creator": "Anders Virtual CFO"},
        {"external_id": "acct-2", "url": "https://example.org/acct-2",
         "title": "Tax season tips for owners", "creator": "Anders Virtual CFO"},
        {"external_id": "ok-1", "url": "https://example.org/ok-1",
         "title": "SBA loans explained", "creator": "Acquiring Minds"},
    ], platform="youtube", project_id=pid, origin={"kind": "exploration"})

    db.add_exclude(pid, "creator", "Anders Virtual CFO", reason="Kyle: no longer pursuing accounting firms")
    r = candidates.pool(pid, kind="candidates", limit=100)
    creators = {i["creator"] for i in r["items"]}
    assert r["counts"]["candidates"] == 1
    assert creators == {"Acquiring Minds"}


def test_exclude_is_case_insensitive_and_a_duplicate_add_is_a_no_op():
    pid = _project()
    row1 = db.add_exclude(pid, "keyword", "Laundromat")
    row2 = db.add_exclude(pid, "keyword", "laundromat")
    assert row1["id"] == row2["id"]
    assert len(db.list_excludes(pid)) == 1

    candidates.remember([{"external_id": "laund-3", "url": "https://example.org/laund-3",
                          "title": "laundromat cash flow deep dive", "creator": "Some Channel"}],
                        platform="youtube", project_id=pid, origin={"kind": "exploration"})
    r = candidates.pool(pid, kind="candidates", limit=100)
    assert r["counts"]["candidates"] == 0


def test_removing_an_exclude_lets_matching_candidates_reappear():
    pid = _project()
    row = db.add_exclude(pid, "keyword", "laundromat")
    candidates.remember([{"external_id": "laund-4", "url": "https://example.org/laund-4",
                          "title": "Laundromat profit margins", "creator": "Some Channel"}],
                        platform="youtube", project_id=pid, origin={"kind": "exploration"})
    assert candidates.pool(pid, kind="candidates", limit=100)["counts"]["candidates"] == 0
    db.delete_exclude(row["id"])
    assert candidates.pool(pid, kind="candidates", limit=100)["counts"]["candidates"] == 1


def test_excludes_are_scoped_per_project_never_global():
    pid_a = _project()
    pid_b = db.create_project("web app design", "design apps")["id"]
    db.add_exclude(pid_a, "keyword", "laundromat")
    candidates.remember([{"external_id": "laund-5", "url": "https://example.org/laund-5",
                          "title": "Laundromat empire", "creator": "Some Channel"}],
                        platform="youtube", project_id=pid_b, origin={"kind": "exploration"})
    assert candidates.pool(pid_b, kind="candidates", limit=100)["counts"]["candidates"] == 1


def test_api_add_list_delete_exclude_roundtrip():
    pid = _project()
    added = api.api_add_exclude(pid, api.ExcludeIn(kind="keyword", term="laundromat", reason="rejected"))
    assert added["kind"] == "keyword" and added["term"] == "laundromat"
    listed = api.api_excludes(pid)
    assert len(listed) == 1 and listed[0]["id"] == added["id"]
    api.api_delete_exclude(added["id"])
    assert api.api_excludes(pid) == []


def test_api_rejects_bad_kind_and_empty_term():
    from fastapi import HTTPException
    pid = _project()
    with pytest.raises(HTTPException):
        api.api_add_exclude(pid, api.ExcludeIn(kind="topic", term="laundromat"))
    with pytest.raises(HTTPException):
        api.api_add_exclude(pid, api.ExcludeIn(kind="keyword", term="   "))


def test_excluded_candidate_never_offered_by_next_batch_either():
    pid = _project()
    db.add_exclude(pid, "keyword", "laundromat")
    candidates.remember([{"external_id": "laund-6", "url": "https://example.org/laund-6",
                          "title": "Laundromat empire part 2", "creator": "Some Channel"},
                         {"external_id": "ok-2", "url": "https://example.org/ok-2",
                          "title": "Buying a plumbing business", "creator": "Acquiring Minds"}],
                        platform="youtube", project_id=pid, origin={"kind": "exploration"})
    batch = candidates.next_batch(pid, n=50)
    titles = {i["title"] for i in batch["items"]}
    assert "Buying a plumbing business" in titles
    assert not any("Laundromat" in t for t in titles)
