"""SUB-R2: real queue admission, checkpoint and worker ownership, without Reddit access."""
import json
import time

import pytest

from neurosearch import community, db, jobs, reservoir, resources
from neurosearch.config import settings

URL = "https://www.reddit.com/r/smallbusiness/"


def request(pid, cid, *, action):
    if action == "cancel":
        return reservoir.cancel_subreddit_scan(pid, cid)["state"]
    return reservoir.admit_subreddit_scan(pid, cid, refresh=action == "refresh")["state"]


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def setup():
    pid = db.create_project("catalog lifecycle")["id"]
    routed = resources.route(resources.classify(URL), pid)
    return pid, routed["collection_id"], routed["job_id"]


def state(pid, cid):
    return json.loads(db.kv_get(reservoir._scan_key(pid, cid)) or "{}")


def listing(post):
    return {"external_id": f"reddit:{post}", "url": URL + f"comments/{post}/title/", "title": post}


def turn():
    claimed = db.claim_job(("explore",), worker_id="fixture")
    assert claimed
    return jobs.execute(claimed, "fixture")


def test_run_and_job_admission_rollback_together(monkeypatch):
    pid = db.create_project("atomic")["id"]
    cid = community.attach_subreddit_catalog(pid, URL)["id"]
    enqueue = jobs.enqueue

    def interrupted(*args, **kwargs):
        enqueue(*args, **kwargs)
        raise RuntimeError("crash after enqueue")

    monkeypatch.setattr(jobs, "enqueue", interrupted)
    with pytest.raises(RuntimeError, match="crash after enqueue"):
        request(pid, cid, action="attach")
    assert state(pid, cid) == {}
    assert db.list_jobs(100) == []


def test_actual_two_page_worker_and_completed_attach_do_not_refresh(monkeypatch):
    pid, cid, jid = setup()
    calls = []

    def fetch(_sub, after, **_kw):
        assert not db.connect().in_transaction
        calls.append(after)
        return ([listing("a")], "t3_a") if after is None else ([listing("b")], None)

    monkeypatch.setattr(community, "enumerate_subreddit_page", fetch)
    assert state(pid, cid)["job_id"] == jid
    assert resources.route(resources.classify(URL), pid)["job_id"] == jid
    assert turn() == "queued"
    assert state(pid, cid)["cursor"] == "t3_a"
    assert turn() == "done"
    assert calls == [None, "t3_a"]
    before = state(pid, cid)
    assert resources.route(resources.classify(URL), pid)["queued"] is False
    assert state(pid, cid) == before
    assert len(db.list_jobs(100)) == 1
    assert len(db.collection_candidate_ids(cid)) == 2
    assert db.project_source_ids(pid, ready_only=False) == []


def test_refresh_of_blocked_retry_cannot_dedupe_to_the_old_job():
    pid, cid, jid = setup()
    before = state(pid, cid)
    db.kv_set(reservoir._scan_key(pid, cid), json.dumps({**before, "status": "blocked", "error": "429"}))
    db.requeue_job(jid, delay=600, wait_reason="retry")
    refreshed = request(pid, cid, action="refresh")
    assert refreshed["run_id"] != before["run_id"]
    assert refreshed["job_id"] != jid
    assert db.get_job(jid)["status"] == "cancelled"
    assert db.get_job(refreshed["job_id"])["payload"]["catalog_run_id"] == refreshed["run_id"]
    assert request(pid, cid, action="refresh") == refreshed


def test_cancel_resume_keeps_cursor_and_run_limits(monkeypatch):
    monkeypatch.setattr(reservoir, "SUBREDDIT_MAX_PAGES", 2)
    pid, cid, jid = setup()
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda _sub, after, **_kw: ([listing(str(after))], "next-" + str(after)))
    assert turn() == "queued"
    first = state(pid, cid)
    request(pid, cid, action="cancel")
    assert db.get_job(jid)["status"] == "cancelled"
    assert reservoir.subreddit_catalogs(pid)[0]["scan"]["status"] == "cancelled"
    monkeypatch.setattr(reservoir, "SUBREDDIT_MAX_PAGES", 50)
    resumed = request(pid, cid, action="resume")
    assert resumed["cursor"] == first["cursor"]
    assert resumed["run_id"] == first["run_id"] and resumed["page_limit"] == 2
    assert resumed["job_id"] != jid
    assert turn() == "done"
    assert state(pid, cid)["pages"] == 2
    assert state(pid, cid)["reason"] == "application limit reached"


@pytest.mark.parametrize("outcome", ["page", "error"])
def test_reclaimed_worker_cannot_commit_same_generation(monkeypatch, outcome):
    pid, cid, jid = setup()
    claimed = db.claim_job(("explore",), worker_id="old")
    before = state(pid, cid)
    replacement = []

    def fetch(*_args, **_kw):
        db.requeue_job(jid)
        replacement.append(db.claim_job(("explore",), worker_id="new"))
        if outcome == "error":
            raise RuntimeError("old worker failure")
        return [listing("stale")], "cursor"

    monkeypatch.setattr(community, "enumerate_subreddit_page", fetch)
    jobs.execute(claimed, "old")
    assert state(pid, cid) == before
    assert db.collection_candidate_ids(cid) == []
    actual = db.get_job(jid)
    assert actual["status"] == "running" and actual["run_id"] == replacement[0]["run_id"]


def test_cancel_during_fetch_commits_no_page(monkeypatch):
    pid, cid, jid = setup()

    def fetch(*_args, **_kw):
        db.request_cancel(jid)
        return [listing("cancelled")], None

    monkeypatch.setattr(community, "enumerate_subreddit_page", fetch)
    assert turn() == "cancelled"
    assert db.collection_candidate_ids(cid) == []
    assert reservoir.subreddit_catalogs(pid)[0]["scan"]["status"] == "cancelled"


def test_detach_during_fetch_commits_no_page(monkeypatch):
    pid, cid, _jid = setup()

    def fetch(*_args, **_kw):
        db.remove_project_collections(pid, [cid])
        return [listing("detached")], None

    monkeypatch.setattr(community, "enumerate_subreddit_page", fetch)
    turn()
    assert db.collection_candidate_ids(cid) == []


def test_legacy_worker_requires_explicit_recovery_without_fetch(monkeypatch):
    pid = db.create_project("legacy")["id"]
    cid = community.attach_subreddit_catalog(pid, URL)["id"]
    job = jobs.enqueue("explore", {"kind": "subreddit", "url": URL, "project_id": pid, "collection_id": cid})
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_k: pytest.fail("legacy worker fetched"))
    assert turn() == "failed"
    assert "resume" in db.get_job(job["id"])["message"].lower()


def test_generic_rescan_never_dispatches_subreddit_to_youtube():
    pid, cid, _jid = setup()
    db.set_collection_policy(pid, cid, source_role="primary", monitor_policy="on")
    forbidden = lambda *_a: pytest.fail("subreddit reached YouTube enumeration")
    assert reservoir.rescan_project(pid, enumerate=forbidden) == []
    with pytest.raises(ValueError, match="catalog"):
        reservoir.rescan(pid, cid, enumerate=forbidden)


def test_generic_explore_dedupe_is_unchanged():
    payload = {"project_id": "p", "url": "https://example.com", "kind": "website"}
    assert db.dedupe_key_for("explore", payload) == "explore:p:https://example.com"


def test_claim_guard_on_requeue_does_not_clear_replacement():
    _pid, _cid, jid = setup()
    old = db.claim_job(("explore",), worker_id="old")
    db.requeue_job(jid)
    new = db.claim_job(("explore",), worker_id="new")
    assert not db.requeue_job(jid, expected_run_id=old["run_id"])
    assert db.get_job(jid)["run_id"] == new["run_id"]


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_official_http_failure_survives_adapter_and_job(monkeypatch, status):
    from neurosearch import safe_fetch
    pid, cid, jid = setup()
    calls = []
    monkeypatch.setattr(community, "reddit_api_configured", lambda: True)
    monkeypatch.setattr(community, "_oauth_token", lambda: "fixture-token")

    def fetch(url, **_kw):
        assert not db.connect().in_transaction
        calls.append(url)
        return safe_fetch.FetchResult(url, status, "application/json", b"{}", {"Retry-After": "7200"})

    monkeypatch.setattr(safe_fetch, "safe_fetch", fetch)
    start = time.time()
    expected = "failed" if status in (401, 403) else "queued"
    assert turn() == expected
    saved, job = state(pid, cid), db.get_job(jid)
    assert saved["provider_status"] == status and saved["status"] == "blocked"
    assert len(calls) == (2 if status == 401 else 1)
    assert all(url.startswith("https://oauth.reddit.com/r/smallbusiness/new?") for url in calls)
    assert db.collection_candidate_ids(cid) == []
    if expected == "queued":
        assert job["not_before"] >= start + 7200
        assert db.claim_job(("explore",)) is None
        assert request(pid, cid, action="resume")["job_id"] == jid
        assert db.get_job(jid)["not_before"] == job["not_before"]
    else:
        assert not job.get("not_before") and job["attempts"] == 0


def test_retry_after_http_date_and_invalid_header():
    from email.utils import formatdate
    future = int(time.time()) + 3600
    before = time.time()
    assert future - before - 1 <= community._retry_after({"retry-after": formatdate(future, usegmt=True)}) <= future - before
    assert community._retry_after({"Retry-After": "nonsense"}) is None


def test_retry_attempts_are_bounded_and_success_clears_old_error(monkeypatch):
    pid, cid, jid = setup()

    def fail(*_a, **_kw):
        raise community.RedditApiError(503, "busy", kind="server", retryable=True)

    monkeypatch.setattr(community, "enumerate_subreddit_page", fail)
    for attempt in range(jobs.MAX_ATTEMPTS):
        assert turn() == ("failed" if attempt == jobs.MAX_ATTEMPTS - 1 else "queued")
        if attempt < jobs.MAX_ATTEMPTS - 1:
            assert db.claim_job(("explore",)) is None
            with db.tx() as conn:
                conn.execute("UPDATE jobs SET not_before=0 WHERE id=?", (jid,))
    assert db.get_job(jid)["attempts"] == jobs.MAX_ATTEMPTS - 1
    resumed = request(pid, cid, action="resume")
    assert resumed["job_id"] != jid
    assert "error" not in resumed
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: ([listing("recovered")], None))
    assert turn() == "done"
    assert not state(pid, cid).get("error") and "provider_status" not in state(pid, cid)


@pytest.mark.parametrize("bad_page", ["cycle", "empty"])
def test_cursor_cycle_and_advancing_empty_page_are_not_success(monkeypatch, bad_page):
    pid, cid, jid = setup()
    pages = iter([([listing("one")], "A"), ([listing("two")], "B"),
                  ([listing("repeated")], "A") if bad_page == "cycle" else ([], "C")])
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: next(pages))
    assert turn() == "queued"
    assert turn() == "queued"
    assert turn() == "failed"
    assert state(pid, cid)["status"] == "blocked" and state(pid, cid)["cursor"] == "B"
    assert state(pid, cid)["pages"] == 2
    assert len(db.collection_candidate_ids(cid)) == 2
    assert not db.get_job(jid).get("not_before")


@pytest.mark.parametrize("data", [{}, {"data": {}}, {"data": {"children": {}}},
                                  {"data": {"children": [None], "after": None}},
                                  {"data": {"children": [], "after": 7}}])
def test_malformed_listing_fails_without_phantom_empty_completion(monkeypatch, data):
    pid, cid, _jid = setup()
    monkeypatch.setattr(community, "reddit_api_configured", lambda: True)
    monkeypatch.setattr(community, "_api_get", lambda *_a: data)
    assert turn() == "failed"
    assert state(pid, cid)["status"] == "blocked"
    assert db.collection_candidate_ids(cid) == []


def test_missing_credentials_and_untyped_errors_do_not_retry_by_message(monkeypatch):
    pid, cid, _jid = setup()
    monkeypatch.setattr(community, "reddit_api_configured", lambda: False)
    assert turn() == "failed"
    assert state(pid, cid)["error_type"] == "credentials"
    request(pid, cid, action="resume")
    def fail(*_a, **_kw):
        raise RuntimeError("503 rate limit unavailable: an untyped bug, not a retry contract")
    monkeypatch.setattr(community, "enumerate_subreddit_page", fail)
    assert turn() == "failed"


def test_failure_between_rows_and_checkpoint_rolls_back_then_resume(monkeypatch):
    pid, cid, _jid = setup()
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: ([listing("atomic")], None))
    original = db.kv_compare_set
    def fail(*_a, **_kw):
        raise RuntimeError("page checkpoint failed")
    monkeypatch.setattr(db, "kv_compare_set", fail)
    assert turn() == "failed"
    assert state(pid, cid)["pages"] == 0
    assert db.collection_candidate_ids(cid) == []
    assert db.connect().execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
    monkeypatch.setattr(db, "kv_compare_set", original)
    request(pid, cid, action="resume")
    assert turn() == "done"
    assert len(db.collection_candidate_ids(cid)) == 1


def test_crash_after_commit_and_restart_does_not_replay_page(monkeypatch):
    pid, cid, jid = setup()
    original = reservoir.scan_subreddit_page
    calls = []
    def fetch(*_a, **_kw):
        calls.append(True)
        return [listing("committed")], None
    def crash(*a, **kw):
        original(*a, **kw)
        raise jobs.SimulatedCrash("after catalog commit")
    monkeypatch.setattr(community, "enumerate_subreddit_page", fetch)
    monkeypatch.setattr(reservoir, "scan_subreddit_page", crash)
    with pytest.raises(jobs.SimulatedCrash):
        turn()
    assert state(pid, cid)["status"] == "complete"
    db.close_thread_connection()
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (jid,))
    assert db.recover_expired_leases() == [jid]
    monkeypatch.setattr(reservoir, "scan_subreddit_page", original)
    assert turn() == "done" and calls == [True]
    assert state(pid, cid)["observed"] == 1 and len(db.collection_candidate_ids(cid)) == 1


def test_new_scan_actions_reject_foreign_projects_before_writes():
    pid, cid, _jid = setup()
    foreign = db.create_project("foreign")["id"]
    before = state(pid, cid)
    for action in ("attach", "refresh", "resume", "cancel"):
        changes = db.connect().total_changes
        with pytest.raises(ValueError):
            request(foreign, cid, action=action)
        assert db.connect().total_changes == changes
    assert state(pid, cid) == before


def test_resume_cancel_api_uses_same_project_scoped_admission(client):
    pid, cid, jid = setup()
    foreign = db.create_project("outsider")["id"]
    h = {"Authorization": "Bearer t0k"}
    for action in ("resume", "cancel", "refresh"):
        before = len(db.list_jobs(100))
        assert client.post(f"/api/projects/{foreign}/subreddit-catalogs/{cid}/{action}", headers=h).status_code == 404
        assert len(db.list_jobs(100)) == before
    assert client.post(f"/api/projects/{pid}/subreddit-catalogs/{cid}/cancel", headers=h).status_code == 200
    assert db.get_job(jid)["status"] == "cancelled"
    resumed = client.post(f"/api/projects/{pid}/subreddit-catalogs/{cid}/resume", headers=h)
    assert resumed.status_code == 200
    assert resumed.json()["job_id"] == state(pid, cid)["job_id"] != jid


def test_cancel_after_page_commit_before_yield_never_requeues(monkeypatch):
    pid, cid, jid = setup()
    original = reservoir.scan_subreddit_page
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: ([listing("saved")], "next"))
    def cancel_after_commit(*args, **kw):
        result = original(*args, **kw)
        db.request_cancel(jid)
        return result
    monkeypatch.setattr(reservoir, "scan_subreddit_page", cancel_after_commit)
    assert turn() == "cancelled"
    assert len(db.collection_candidate_ids(cid)) == 1
    assert state(pid, cid)["cursor"] == "next"
    assert db.claim_job(("explore",)) is None


def test_concurrent_double_click_admits_one_run_and_job():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    pid = db.create_project("double click")["id"]
    cid = community.attach_subreddit_catalog(pid, URL)["id"]
    gate = threading.Barrier(2)
    def admit():
        try:
            gate.wait(timeout=5)
            return request(pid, cid, action="refresh")
        finally:
            db.close_thread_connection()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [f.result(timeout=10) for f in [pool.submit(admit), pool.submit(admit)]]
    assert first["run_id"] == second["run_id"] and first["job_id"] == second["job_id"]
    assert len(db.list_jobs(100)) == 1


def test_expired_claim_leaves_work_for_recovery(monkeypatch):
    pid, cid, jid = setup()
    claimed = db.claim_job(("explore",), worker_id="expired", lease_seconds=-1)
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda *_a, **_kw: pytest.fail("expired claim fetched"))
    assert jobs.execute(claimed, "expired") == "running"
    assert db.recover_expired_leases() == [jid]
    assert state(pid, cid)["pages"] == 0


def test_legacy_checkpoint_resumes_with_new_job_binding(monkeypatch):
    pid = db.create_project("legacy checkpoint")["id"]
    cid = community.attach_subreddit_catalog(pid, URL)["id"]
    db.kv_set(reservoir._scan_key(pid, cid), json.dumps({"status": "partial", "cursor": "old-cursor", "pages": 1,
                                                     "observed": 3, "page_limit": 7, "observation_limit": 700}))
    assert reservoir.subreddit_catalogs(pid)[0]["scan"]["status"] == "blocked"
    saved = request(pid, cid, action="resume")
    assert saved["cursor"] == "old-cursor" and saved["page_limit"] == 7
    calls = []
    monkeypatch.setattr(community, "enumerate_subreddit_page", lambda _sub, after, **_kw: calls.append(after) or ([], None))
    assert turn() == "done" and calls == ["old-cursor"]
