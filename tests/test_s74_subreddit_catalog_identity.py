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

from neurosearch import candidates, community, db, identity, jobs, reservoir, resources, sources_value  # noqa: E402
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
    assert catalog["queued"] is True

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
    assert sources_value.subreddit_catalog_yield(second, catalog["id"])["captured_threads"] == 1
    db.remove_project_sources(second, [created.source["id"]])
    assert sources_value.subreddit_catalog_yield(second, catalog["id"])["captured_threads"] == 0
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


def _listing(post_id: str) -> dict:
    return {"external_id": f"reddit:{post_id}", "url": f"https://www.reddit.com/r/smallbusiness/comments/{post_id}/x/",
            "title": f"Post {post_id}", "description": "owner detail", "content_type": "post"}


def test_resumable_pages_keep_partial_progress_and_never_create_sources():
    project = _project("scan")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    calls = []

    def pages(subreddit, after):
        calls.append((subreddit, after))
        return (([_listing("a"), _listing("b")], "t3_b") if after is None else ([_listing("b"), _listing("c")], None))

    first = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=pages)
    assert first["status"] == "partial" and first["new"] == 0 and first["initial_known"] == 2 and first["total"] == 2
    candidates.dismiss(project, first["candidate_ids"][0], "not useful")
    second = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=pages)
    assert second["status"] == "complete" and second["new"] == 0 and second["initial_known"] == 1 and second["total"] == 3
    assert calls == [("smallbusiness", None), ("smallbusiness", "t3_b")]
    assert len(db.collection_candidate_ids(catalog["id"])) == 3
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") or "{}")
    assert state["status"] == "complete" and state["reason"] == "listing ended"
    assert state["known_posts"] == 3 and state["observed"] == 4 and state["initial_known"] == 3
    assert db.connect().execute("SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                                (first["candidate_ids"][0], project)).fetchone()["state"] == "user_dismissed"


def test_scan_failure_keeps_already_committed_pages_and_reports_the_block():
    project = _project("blocked")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _sub, _after: ([_listing("a")], "t3_a"))
    blocked = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _sub, _after: (_ for _ in ()).throw(RuntimeError("Reddit API: rate limited (429)")))
    assert blocked["status"] == "blocked" and blocked["total"] == 1 and "429" in blocked["error"]
    assert len(db.collection_candidate_ids(catalog["id"])) == 1


def test_subreddit_explore_job_yields_after_a_committed_page(monkeypatch):
    project = _project("job")
    monkeypatch.setattr(reservoir, "scan_subreddit_page", lambda *_a, **_kw: {"status": "partial", "collection_id": "c"})
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    job = db.get_job(queued["job_id"])
    claimed = db.claim_job(("explore",), worker_id="test")
    assert claimed and claimed["id"] == job["id"]
    assert jobs.execute(claimed, "test") == "queued"
    assert db.get_job(job["id"])["message"] == "catalog page saved; continuing automatically"


def test_catalog_enumerator_requires_official_api_and_keeps_listing_metadata_small(monkeypatch):
    monkeypatch.setattr(community, "reddit_api_configured", lambda: False)
    with pytest.raises(RuntimeError, match="credentials are required"):
        community.enumerate_subreddit_page("smallbusiness")

    seen = []
    monkeypatch.setattr(community, "reddit_api_configured", lambda: True)
    monkeypatch.setattr(community, "_api_get", lambda path: seen.append(path) or {"data": {"after": "t3_next", "children": [
        {"data": {"id": "one", "permalink": "/r/smallbusiness/comments/one/title/", "title": "A", "selftext": "x" * 2500,
                  "author": "owner", "created_utc": 1, "score": 0, "num_comments": 12, "link_flair_text": "Question"}}
    ]}})
    rows, after = community.enumerate_subreddit_page("smallbusiness", "t3 before", limit=500)
    assert seen == ["/r/smallbusiness/new?raw_json=1&limit=100&after=t3%20before"]
    assert after == "t3_next" and rows[0]["external_id"] == "reddit:one"
    assert rows[0]["description"] == "x" * 2000 and rows[0]["view_count"] == 0
    assert rows[0]["metadata"] == {"version": 1, "subreddit": "smallbusiness", "score": 0, "comment_count": 12,
                                    "flair": "Question", "created_utc": 1, "outbound_url": None,
                                    "outbound_domain": None, "availability": "available"}


def test_refresh_tracks_distinct_new_posts_and_semantic_metadata_changes():
    project = _project("refresh")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    initial = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _sub, _after: ([_listing("a")], None))
    assert initial["initial_known"] == 1 and initial["new"] == 0
    started = reservoir.begin_subreddit_refresh(project, catalog["id"])
    assert started["mode"] == "refresh" and started["known_posts"] == 1
    assert reservoir.begin_subreddit_refresh(project, catalog["id"])["run_id"] == started["run_id"]
    changed = _listing("a") | {"title": "Post a revised", "observed_metadata": True,
                                "metadata": {"version": 1, "score": -2, "comment_count": 4, "subreddit": "smallbusiness"}}
    refreshed = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _sub, _after: ([changed, _listing("b")], None))
    assert refreshed["new"] == 1 and refreshed["total"] == 2 and refreshed["observed"] == 2
    row = db.connect().execute("SELECT title, metadata_json, metadata_revision FROM candidates WHERE external_id='reddit:a'").fetchone()
    assert row["title"] == "Post a revised" and __import__("json").loads(row["metadata_json"])["score"] == -2
    assert row["metadata_revision"] == 2


def test_stale_scan_cannot_commit_after_a_newer_refresh_starts():
    project = _project("stale")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")

    def replaced_mid_fetch(_sub, _after):
        reservoir.begin_subreddit_refresh(project, catalog["id"])
        return [_listing("lost")], None

    result = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=replaced_mid_fetch)
    assert result["status"] == "stale"
    assert db.collection_candidate_ids(catalog["id"]) == []


def test_catalog_query_is_project_scoped_paged_and_metadata_only():
    first, second = _project("catalog first"), _project("catalog second")
    catalog = community.attach_subreddit_catalog(first, "https://www.reddit.com/r/smallbusiness/")
    community.attach_subreddit_catalog(second, "https://www.reddit.com/r/smallbusiness/")
    ids = candidates.remember([
        _listing("fit") | {"title": "I bought a small business", "description": "owner lessons", "observed_metadata": True,
                           "metadata": {"score": 2, "comment_count": 4}},
        _listing("popular") | {"title": "Unrelated popular thread", "description": "memes", "observed_metadata": True,
                               "metadata": {"score": 999, "comment_count": 20}},
        _listing("new") | {"title": "Newest owner report", "description": "I run a business", "published_at": "2026-09-19",
                           "observed_metadata": True, "metadata": {"score": 1, "comment_count": 1}},
    ], "reddit", first, {"kind": "fixture"})
    db.link_collection_candidates(catalog["id"], ids)
    candidates.dismiss(first, ids[1], "not useful")
    highest = candidates.catalog(first, catalog["id"], mode="highest_score", state="all", limit=2)
    assert highest["total"] == 3 and [x["id"] for x in highest["items"]] == [ids[1], ids[0]]
    assert highest["next_page"] == 1 and highest["items"][0]["metadata"]["score"] == 999
    second_view = candidates.catalog(second, catalog["id"], state="available", mode="newest", limit=10)
    assert second_view["total"] == 3 and second_view["items"][0]["id"] == ids[2]
    with pytest.raises(RuntimeError, match="revision changed"):
        candidates.catalog(first, catalog["id"], revision="outdated")


def test_catalog_api_exposes_review_refresh_and_yield(client):
    project = _project("catalog api")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post(project)
    db.link_collection_candidates(catalog["id"], [candidate_id])
    h = {"Authorization": "Bearer t0k"}
    view = client.get(f"/api/projects/{project}/subreddit-catalogs/{catalog['id']}", headers=h)
    assert view.status_code == 200 and view.json()["total"] == 1
    refreshed = client.post(f"/api/projects/{project}/subreddit-catalogs/{catalog['id']}/refresh", headers=h)
    assert refreshed.status_code == 200 and refreshed.json()["job_id"]
    outcome = client.get(f"/api/projects/{project}/subreddit-catalogs/{catalog['id']}/yield", headers=h)
    assert outcome.status_code == 200 and outcome.json()["captured_threads"] == 0
