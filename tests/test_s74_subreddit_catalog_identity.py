"""SUB2 — subreddit catalog identity and membership.

These fixtures never read Reddit. They prove the boundary that later pagination relies on: a catalog remembers
candidate threads without becoming a Source collection, and Reddit listing candidates resolve to the existing
Community Source identity only when that thread has actually been captured.
"""
from __future__ import annotations

import os

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


def test_unknown_project_cannot_create_an_orphan_catalog():
    before = db.connect().execute("SELECT COUNT(*) FROM collections").fetchone()[0]
    with pytest.raises(LookupError):
        community.attach_subreddit_catalog("missing-project", "https://www.reddit.com/r/smallbusiness/")
    assert db.connect().execute("SELECT COUNT(*) FROM collections").fetchone()[0] == before


def test_page_link_reconciles_only_the_candidates_just_received():
    project = _project("page bounded")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    first, second = candidates.remember([_listing("first"), _listing("second")], "reddit", None, {"kind": "fixture"})
    db.link_collection_candidates(catalog["id"], [first])
    # Simulate a legacy missing project relationship.  A later page must not
    # use a broad catalog query to repair it; attachment owns that repair.
    db.connect().execute("DELETE FROM candidate_projects WHERE candidate_id=? AND project_id=?", (first, project))
    db.link_collection_candidates(catalog["id"], [second])
    rows = db.connect().execute("SELECT candidate_id FROM candidate_projects WHERE project_id=? ORDER BY candidate_id", (project,)).fetchall()
    assert [row["candidate_id"] for row in rows] == [second]


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


def test_attaching_catalog_reconciles_an_old_unresolved_reddit_pointer_once():
    owner, later = _project("legacy owner"), _project("legacy attach")
    catalog = community.attach_subreddit_catalog(owner, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post(owner)
    db.link_collection_candidates(catalog["id"], [candidate_id])
    source = identity.resolve_or_create_source(
        identity.Candidate(platform="community", external_id="reddit:abc123",
                           url="https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/"),
        owner, initial_status="ready",
    ).source
    # Simulate a pre-bridge candidate row: its capture was already known globally but the old row lacked source_id.
    db.connect().execute("UPDATE candidates SET source_id=NULL WHERE id=?", (candidate_id,))

    community.attach_subreddit_catalog(later, "https://www.reddit.com/r/smallbusiness/")
    row = db.connect().execute("SELECT source_id FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    assert row["source_id"] == source["id"]
    assert db.project_source_ids(later, ready_only=False) == []


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


def test_catalog_jobs_are_bound_to_their_run_and_refresh_replaces_a_blocked_run(monkeypatch):
    project = _project("run binding")
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    job = db.get_job(queued["job_id"])
    state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{queued['collection_id']}") or "{}")
    assert job["payload"]["catalog_run_id"] == state["run_id"]
    assert job["payload"]["catalog_generation"] == state["generation"]

    blocked = reservoir.scan_subreddit_page(project, queued["collection_id"], expected_run_id=state["run_id"],
                                             fetch_page=lambda _sub, _after: (_ for _ in ()).throw(RuntimeError("Reddit API: HTTP 403")))
    assert blocked["status"] == "blocked"
    refreshed = reservoir.begin_subreddit_refresh(project, queued["collection_id"])
    assert refreshed["run_id"] != state["run_id"] and refreshed["cursor"] is None and refreshed["mode"] == "refresh"

    called = []
    stale = reservoir.scan_subreddit_page(project, queued["collection_id"], expected_run_id=state["run_id"],
                                           fetch_page=lambda *_: called.append(True))
    assert stale["status"] == "stale" and called == []


def test_refresh_gets_its_own_job_when_an_old_retrying_run_is_still_active():
    project = _project("refresh admission")
    first = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    first_state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{first['collection_id']}") or "{}")
    assert first_state["job_id"] == first["job_id"]

    # A failed page reports blocked state while its original explore job is
    # still active/retryable.  A head refresh must not dedupe to that old job.
    blocked = reservoir.scan_subreddit_page(
        project, first["collection_id"], expected_run_id=first_state["run_id"],
        fetch_page=lambda _sub, _after: (_ for _ in ()).throw(RuntimeError("Reddit API: rate limited (429)")),
    )
    assert blocked["status"] == "blocked"
    refreshed = reservoir.admit_subreddit_scan(project, first["collection_id"], refresh=True)
    assert refreshed["state"]["run_id"] != first_state["run_id"]
    assert refreshed["job"]["id"] != first["job_id"]
    assert refreshed["state"]["job_id"] == refreshed["job"]["id"]
    assert refreshed["job"]["payload"]["catalog_run_id"] == refreshed["state"]["run_id"]
    assert db.get_job(first["job_id"])["status"] == "queued"


def test_catalog_admission_rolls_back_state_when_job_creation_fails(monkeypatch):
    project = _project("atomic admission")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    monkeypatch.setattr(jobs, "enqueue", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("queue unavailable")))
    with pytest.raises(RuntimeError, match="queue unavailable"):
        reservoir.admit_subreddit_scan(project, catalog["id"])
    assert db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") is None
    assert db.list_jobs(20) == []


def test_repeated_paste_reuses_an_active_run_but_not_a_completed_catalog():
    project = _project("route transitions")
    first = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    again = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    assert again["job_id"] == first["job_id"]
    reservoir.scan_subreddit_page(project, first["collection_id"], fetch_page=lambda _sub, _after: ([_listing("one")], None))
    completed = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    assert completed["queued"] is False and completed["job_id"] is None


def test_reclaimed_worker_cannot_commit_after_a_new_claim_fences_it():
    project = _project("lease fence")
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    first = db.claim_job(("explore",), worker_id="first")
    assert first and first["id"] == queued["job_id"]

    def reclaims_then_scans(_subreddit, _cursor):
        db.requeue_job(first["id"], message="fixture reclaim")
        second = db.claim_job(("explore",), worker_id="second")
        assert second and second["id"] == first["id"] and second["run_id"] != first["run_id"]
        newer = reservoir.scan_subreddit_page(
            project, queued["collection_id"],
            expected_run_id=second["payload"]["catalog_run_id"],
            expected_generation=second["payload"]["catalog_generation"],
            expected_job_id=second["id"], expected_job_run_id=second["run_id"],
            fetch_page=lambda _s, _a: ([_listing("new")], None),
        )
        assert newer["status"] == "complete"
        return [_listing("old")], None

    stale = reservoir.scan_subreddit_page(
        project, queued["collection_id"],
        expected_run_id=first["payload"]["catalog_run_id"],
        expected_generation=first["payload"]["catalog_generation"],
        expected_job_id=first["id"], expected_job_run_id=first["run_id"],
        fetch_page=reclaims_then_scans,
    )
    assert stale["status"] == "stale"
    rows = db.connect().execute("SELECT external_id FROM candidates ORDER BY external_id").fetchall()
    assert [row["external_id"] for row in rows] == ["reddit:new"]


def test_successful_retry_clears_a_blocked_scan_error_and_keeps_its_pinned_limits():
    project = _project("retry state")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    state = reservoir.begin_subreddit_refresh(project, catalog["id"])
    state.update({"page_limit": 1, "observation_limit": 3})
    db.kv_set(f"reservoir:scan:{project}:{catalog['id']}", __import__("json").dumps(state, sort_keys=True))
    blocked = reservoir.scan_subreddit_page(
        project, catalog["id"], fetch_page=lambda _s, _a: (_ for _ in ()).throw(RuntimeError("temporary 503")),
    )
    assert blocked["status"] == "blocked"
    retried = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _s, _a: ([_listing("one")], "t3_next"))
    current = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") or "{}")
    assert retried["status"] == "complete" and current["reason"] == "application limit reached"
    assert current["error"] is None and current["page_limit"] == 1 and current["observation_limit"] == 3


def test_catalog_cancel_uses_the_job_ledger_and_catalog_card_is_truthful():
    project = _project("catalog cancel")
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    cancelled = reservoir.cancel_subreddit_scan(project, queued["collection_id"])
    assert cancelled["status"] == "cancelled" and db.get_job(queued["job_id"])["status"] == "cancelled"
    card = reservoir.subreddit_catalogs(project)[0]
    assert card["scan"]["status"] == "cancelled"
    # Re-pasting resumes the same interrupted run from its durable cursor.
    resumed = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    assert resumed["job_id"] != queued["job_id"]
    assert resumed["scan"]["run_id"] == queued["scan"]["run_id"]


def test_catalog_rate_limit_uses_typed_retry_after_and_truthful_card_state(monkeypatch):
    project = _project("typed rate limit")
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: (_ for _ in ()).throw(
        community.RedditApiError(429, "Reddit API: rate limited (429)", retry_after=37)
    ))
    claimed = db.claim_job(("explore",), worker_id="test")
    assert claimed and jobs.execute(claimed, "test") == "queued"
    job = db.get_job(queued["job_id"])
    assert job["status"] == "queued" and job["wait_reason"] == "rate_limit"
    card = reservoir.subreddit_catalogs(project)[0]
    assert card["scan"]["status"] == "rate_limited"
    assert card["scan"]["job"]["status"] == "rate_limit_wait"
    assert card["scan"]["retry_at"] == job["not_before"]


def test_subreddit_catalog_is_never_sent_through_generic_monitored_rescan():
    project = _project("manual catalog only")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    db.set_collection_policy(project, catalog["id"], source_role="primary", monitor_policy="on")
    calls = []
    assert reservoir.rescan_project(project, enumerate=lambda url: calls.append(url) or ({}, [])) == []
    assert calls == []


def test_catalog_stops_a_cursor_cycle_with_an_honest_reason():
    project = _project("cursor cycle")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    pages = [([_listing("a")], "t3_a"), ([_listing("b")], "t3_b"), ([_listing("c")], "t3_a")]
    for expected in ("partial", "partial", "complete"):
        result = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _s, _a: pages.pop(0))
        assert result["status"] == expected
    state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") or "{}")
    assert state["reason"] == "cursor cycle" and state["cursor"] is None
    assert state["cursor_history"] == ["t3_a", "t3_b"]


def test_catalog_fails_an_advancing_empty_listing_instead_of_looping_to_the_cap():
    project = _project("empty page")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    result = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _s, _a: ([], "t3_next"))
    assert result["status"] == "blocked"
    assert result["error"] == "listing returned no usable posts with an advancing cursor"
    state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") or "{}")
    assert state["status"] == "blocked" and state["cursor"] is None


def test_concurrent_project_scans_assign_first_discovery_to_one_commit_only():
    first, second = _project("count first"), _project("count second")
    catalog = community.attach_subreddit_catalog(first, "https://www.reddit.com/r/smallbusiness/")
    community.attach_subreddit_catalog(second, "https://www.reddit.com/r/smallbusiness/")

    def second_commits_before_first(_subreddit, _cursor):
        winner = reservoir.scan_subreddit_page(second, catalog["id"], fetch_page=lambda _s, _a: ([_listing("shared")], None))
        assert winner["initial_known"] == 1
        return [_listing("shared")], None

    loser = reservoir.scan_subreddit_page(first, catalog["id"], fetch_page=second_commits_before_first)
    assert loser["initial_known"] == 0 and loser["total"] == 1
    first_state = __import__("json").loads(db.kv_get(f"reservoir:scan:{first}:{catalog['id']}") or "{}")
    second_state = __import__("json").loads(db.kv_get(f"reservoir:scan:{second}:{catalog['id']}") or "{}")
    assert first_state["initial_known"] + second_state["initial_known"] == 1


def test_catalog_blocked_worker_never_finishes_successfully(monkeypatch):
    project = _project("blocked worker")
    queued = resources.route(resources.classify("https://www.reddit.com/r/smallbusiness/"), project)
    monkeypatch.setattr(reservoir, "scan_subreddit_page", lambda *_a, **_kw: {"status": "blocked", "error": "Reddit API: HTTP 403"})
    claimed = db.claim_job(("explore",), worker_id="test")
    assert claimed and claimed["id"] == queued["job_id"]
    assert jobs.execute(claimed, "test") == "failed"
    assert db.get_job(queued["job_id"])["status"] == "failed"


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


def test_listing_omitted_author_is_not_a_deletion_signal(monkeypatch):
    monkeypatch.setattr(community, "reddit_api_configured", lambda: True)
    monkeypatch.setattr(community, "_api_get", lambda _url: {"data": {"after": None, "children": [
        {"data": {"id": "one", "permalink": "/r/smallbusiness/comments/one/title/", "title": "A", "author": None}},
        {"data": {"id": "two", "permalink": "/r/smallbusiness/comments/two/title/", "title": "B", "author": "[deleted]"}},
        {"data": {"id": "three", "permalink": "/r/smallbusiness/comments/three/title/", "title": "C", "removed_by_category": "moderator"}},
    ]}})
    rows, _ = community.enumerate_subreddit_page("smallbusiness")
    assert [r["metadata"]["availability"] for r in rows] == ["available", "deleted", "removed"]


def test_listing_parser_bounds_rows_and_ignores_malformed_numeric_metadata(monkeypatch):
    monkeypatch.setattr(community, "reddit_api_configured", lambda: True)
    children = [{"data": {"id": f"p{i}", "permalink": f"/r/smallbusiness/comments/p{i}/title/", "title": "A",
                          "score": "many", "num_comments": -1, "created_utc": "later"}} for i in range(101)]
    monkeypatch.setattr(community, "_api_get", lambda _url: {"data": {"after": None, "children": children}})
    rows, _ = community.enumerate_subreddit_page("smallbusiness")
    assert len(rows) == 100
    assert rows[0]["metadata"]["score"] is None and rows[0]["metadata"]["comment_count"] is None
    assert rows[0]["metadata"]["created_utc"] is None and rows[0]["published_at"] is None


def test_observed_metadata_can_explicitly_clear_text_and_flair_without_treating_omission_as_clear():
    project = _project("metadata clear")
    candidate_id = candidates.remember([_listing("clear") | {"description": "old text", "observed_metadata": True,
                                         "metadata": {"flair": "Old", "score": 1}}], "reddit", project, {"kind": "fixture"})[0]
    initial = db.connect().execute("SELECT description FROM candidates WHERE id=?", (candidate_id,)).fetchone()["description"]
    omitted = {key: value for key, value in _listing("clear").items() if key != "description"}
    candidates.remember([omitted | {"observed_metadata": True, "metadata": {"score": 1}}], "reddit", project, {"kind": "fixture"})
    preserved = db.connect().execute("SELECT description, metadata_json FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    assert preserved["description"] == initial and __import__("json").loads(preserved["metadata_json"])["flair"] == "Old"
    candidates.remember([_listing("clear") | {"observed_metadata": True, "observed_clear_fields": ["description"],
                                         "metadata_clears": ["flair"], "metadata": {"flair": None, "score": 1}}],
                        "reddit", project, {"kind": "fixture"})
    cleared = db.connect().execute("SELECT description, metadata_json FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    assert cleared["description"] is None and __import__("json").loads(cleared["metadata_json"])["flair"] is None


def test_scan_counts_unique_posts_but_records_duplicate_listing_observations():
    project = _project("duplicate page")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    first = _listing("same") | {"published_at": "2026-09-18"}
    duplicate = first | {"title": "newer listing observation"}
    result = reservoir.scan_subreddit_page(project, catalog["id"], fetch_page=lambda _sub, _after: ([first, duplicate], None))
    state = __import__("json").loads(db.kv_get(f"reservoir:scan:{project}:{catalog['id']}") or "{}")
    assert result["total"] == 1 and len(result["candidate_ids"]) == 1
    assert state["known_posts"] == 1 and state["observed"] == 2
    assert state["observed_oldest"] == state["observed_newest"] == "2026-09-18"


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


def test_catalog_actions_reject_detached_or_foreign_ids_before_any_write(client):
    owner, outsider = _project("catalog owner"), _project("catalog outsider")
    catalog = community.attach_subreddit_catalog(owner, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post(owner)
    db.link_collection_candidates(catalog["id"], [candidate_id])
    playlist = db.upsert_collection("playlist", "PL-boundary", "https://example.test/playlist", "Not a subreddit")
    db.add_project_collections(owner, [playlist["id"]])
    h = {"Authorization": "Bearer t0k"}

    before = {
        "jobs": db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
        "sources": db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "outsider_state": db.connect().execute("SELECT COUNT(*) FROM candidate_projects WHERE project_id=?", (outsider,)).fetchone()[0],
    }
    base = f"/api/projects/{outsider}/subreddit-catalogs/{catalog['id']}"
    assert client.get(base, headers=h).status_code == 404
    assert client.post(base + "/refresh", headers=h).status_code == 404
    assert client.get(base + "/yield", headers=h).status_code == 404
    assert client.post(base + f"/candidates/{candidate_id}/capture", headers=h, json={}).status_code == 404
    assert client.post(base + f"/candidates/{candidate_id}/dismiss", headers=h, json={}).status_code == 404
    assert client.get(f"/api/projects/{owner}/subreddit-catalogs/{playlist['id']}", headers=h).status_code == 404
    assert client.post(f"/api/projects/{owner}/subreddit-catalogs/{playlist['id']}/refresh", headers=h).status_code == 404

    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before["jobs"]
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before["sources"]
    assert db.connect().execute("SELECT COUNT(*) FROM candidate_projects WHERE project_id=?", (outsider,)).fetchone()[0] == before["outsider_state"]
    assert candidates.list_for_project(owner)[0]["state"] == "available"


def test_catalog_capture_endpoint_uses_the_catalog_scoped_action(client):
    project = _project("catalog scoped capture")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post(project)
    db.link_collection_candidates(catalog["id"], [candidate_id])
    h = {"Authorization": "Bearer t0k"}
    view = client.get(f"/api/projects/{project}/subreddit-catalogs/{catalog['id']}", headers=h).json()
    assert view["items"][0]["actions"]["capture"]["endpoint"].endswith(f"/{candidate_id}/capture")
    response = client.post(f"/api/projects/{project}/subreddit-catalogs/{catalog['id']}/candidates/{candidate_id}/capture", headers=h, json={})
    assert response.status_code == 200 and response.json()["job_id"]
    assert candidates.list_for_project(project)[0]["state"] == "acquired"


def test_catalog_yield_excludes_rejected_claims_and_nonready_sources():
    from neurosearch import claims
    project = _project("yield eligibility")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    candidate_id = _remember_post(project)
    db.link_collection_candidates(catalog["id"], [candidate_id])
    source = identity.resolve_or_create_source(
        identity.Candidate(platform="community", external_id="reddit:abc123",
                           url="https://www.reddit.com/r/smallbusiness/comments/abc123/owner_lessons/"),
        project, initial_status="ready",
    ).source
    claim = claims.add_claim(project, "A test claim")
    claims.add_evidence(claim["id"], source["id"])
    claims.set_status(claim["id"], "rejected")
    assert sources_value.subreddit_catalog_yield(project, catalog["id"])["distinct_claims_supported"] == 0
    claims.set_status(claim["id"], "accepted")
    assert sources_value.subreddit_catalog_yield(project, catalog["id"])["distinct_claims_supported"] == 1
    db.set_source_status(source["id"], "failed", "fixture")
    assert sources_value.subreddit_catalog_yield(project, catalog["id"])["distinct_claims_supported"] == 0


def test_catalog_query_pages_a_5000_post_fixture():
    project = _project("catalog scale")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    entries = [_listing(f"p{i:04d}") | {"title": f"Owner report {i:04d}"} for i in range(5_000)]
    ids = candidates.remember(entries, "reddit", project, {"kind": "fixture"})
    db.link_collection_candidates(catalog["id"], ids)
    first = candidates.catalog(project, catalog["id"], limit=100)
    last = candidates.catalog(project, catalog["id"], page=49, limit=100)
    assert first["total"] == 5_000 and len(first["items"]) == 100 and first["next_page"] == 1
    assert len(last["items"]) == 100 and last["next_page"] is None


def test_catalog_warm_reads_reuse_project_scoring(monkeypatch):
    from neurosearch import cache
    project = _project("catalog cache")
    catalog = community.attach_subreddit_catalog(project, "https://www.reddit.com/r/smallbusiness/")
    ids = candidates.remember([_listing("one"), _listing("two")], "reddit", project, {"kind": "fixture"})
    db.link_collection_candidates(catalog["id"], ids)
    cache.invalidate("subreddit-catalog-score:")
    original, calls = candidates._potential, []
    monkeypatch.setattr(candidates, "_potential", lambda *a, **kw: calls.append(a[0]) or original(*a, **kw))
    candidates.catalog(project, catalog["id"])
    candidates.catalog(project, catalog["id"], page=0, limit=1)
    assert len(calls) == 2
