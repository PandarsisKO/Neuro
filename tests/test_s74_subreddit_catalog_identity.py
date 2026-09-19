"""SUB2 — subreddit catalog identity and membership.

These fixtures never read Reddit. They prove the boundary that later pagination relies on: a catalog remembers
candidate threads without becoming a Source collection, and Reddit listing candidates resolve to the existing
Community Source identity only when that thread has actually been captured.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_subreddit_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import candidates, community, db, identity, resources  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _project(name: str) -> str:
    return db.create_project(name, brief="buying a small business") ["id"]


def _remember_post(project_id: str | None = None) -> str:
    return candidates.remember(
        [{"external_id": "reddit:abc123", "url": "https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/",
          "title": "Owner lessons", "description": "I bought a business and learned the hard way.", "content_type": "post"}],
        "reddit", project_id, {"kind": "fixture"},
    )[0]


def test_subreddit_container_variants_converge_and_threads_do_not():
    variants = (
        "reddit.com/r/SmallBusiness",
        "https://www.reddit.com/r/smallbusiness/?sort=new",
        "https://old.reddit.com/r/SMALLBUSINESS/",
    )
    for url in variants:
        found = resources.classify(url)
        assert found.kind == "subreddit"
        assert found.identifier == "smallbusiness"
        assert found.url == "https://www.reddit.com/r/smallbusiness/"
        assert found.default_action == "explore"

    for url in (
        "https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/",
        "https://www.reddit.com/r/smallbusiness+entrepreneur/",
        "https://www.reddit.com/user/smallbusiness/",
        "https://reddit.example/r/smallbusiness/",
    ):
        assert resources.classify(url).kind != "subreddit"


def test_catalog_membership_is_idempotent_project_scoped_and_never_source_membership():
    first, second = _project("first"), _project("second")
    catalog = resources.route(resources.classify("https://old.reddit.com/r/SmallBusiness/?sort=new"), first)
    replay = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), first)
    assert catalog["catalog"] and replay["catalog"]
    assert catalog["collection_id"] == replay["collection_id"]
    assert catalog["queued"] is False

    candidate_id = _remember_post()
    assert db.link_collection_candidates(catalog["collection_id"], [candidate_id, candidate_id]) == 1
    assert db.collection_candidate_ids(catalog["collection_id"]) == [candidate_id]
    assert candidates.list_for_project(first)[0]["id"] == candidate_id

    second_catalog = resources.route(resources.classify("https://reddit.com/r/smallbusiness"), second)
    assert second_catalog["collection_id"] == catalog["collection_id"]
    assert candidates.list_for_project(second)[0]["id"] == candidate_id
    assert db.project_source_ids(first, ready_only=False) == []
    assert db.project_source_ids(second, ready_only=False) == []
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    assert db.connect().execute("SELECT COUNT(*) FROM source_collections").fetchone()[0] == 0


def test_reddit_candidate_and_community_source_resolve_without_recapture_or_cross_project_leak():
    first, second = _project("first"), _project("second")
    catalog = community.attach_subreddit_catalog(first, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post()
    db.link_collection_candidates(catalog["id"], [candidate_id])

    created = identity.resolve_or_create_source(
        identity.Candidate(platform="community", external_id="reddit:abc123",
                           url="https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/"),
        first, initial_status="ready",
    )
    candidate = candidates.list_for_project(first)[0]
    assert candidate["source_id"] == created.source["id"]

    # A second project can attach the catalog and see the possible thread, but it receives no evidence until
    # the explicit Capture action. The capture uses the ready Source instead of scheduling a reread.
    community.attach_subreddit_catalog(second, "https://www.reddit.com/r/smallbusiness/")
    assert db.project_source_ids(second, ready_only=False) == []
    captured = candidates.capture(candidate_id, second)
    assert captured["job_id"] is None and captured["source_id"] == created.source["id"]
    assert db.project_source_ids(second, ready_only=False) == [created.source["id"]]
    assert db.list_jobs(20) == []


def test_discovery_after_direct_thread_capture_resolves_the_same_candidate_identity():
    project = _project("direct capture")
    source = identity.resolve_or_create_source(
        identity.Candidate(platform="community", external_id="reddit:abc123",
                           url="https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/"),
        project, initial_status="ready",
    ).source
    candidate_id = _remember_post(project)
    candidate = candidates.list_for_project(project)[0]
    assert candidate["id"] == candidate_id and candidate["source_id"] == source["id"]
    assert candidates.capture(candidate_id, project)["job_id"] is None
