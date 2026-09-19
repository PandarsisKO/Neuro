"""SUB-R1: bounded catalog membership, atomic authority and legacy identity repair."""
import pytest

from neurosearch import candidates, community, db, identity
from neurosearch.config import settings


@pytest.mark.parametrize("first_capture", ["direct", "browser"])
def test_search_catalog_direct_and_browser_capture_share_identity(monkeypatch, first_capture):
    from neurosearch import ingest, safe_fetch
    owner = db.create_project("capture owner")["id"]
    later = db.create_project("catalog only")["id"]
    col = community.attach_subreddit_catalog(owner, URL)["id"]
    post = {"id": "abc123", "permalink": "/r/smallbusiness/comments/abc123/title/", "title": "Business owner lessons",
            "selftext": "I bought a small business and learned to budget for repairs before closing. " * 8,
            "author": "fixture-owner", "subreddit": "smallbusiness", "num_comments": 0, "score": 1}
    listing = [{"data": {"children": [{"kind": "t3", "data": post}]}}, {"data": {"children": []}}]
    url = "https://www.reddit.com" + post["permalink"]
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *_a, **_kw: pytest.fail("real network used"))
    monkeypatch.setattr(community, "read_reddit_thread", lambda u: community.thread_from_listing(listing, u))
    monkeypatch.setattr(community, "enumerate_reddit", lambda *_a, **_kw: [
        {"external_id": "reddit:abc123", "url": url, "title": post["title"], "description": post["selftext"]}])
    found = community.explore("r/smallbusiness", owner, query="business owner")
    candidate = found["candidates"][0]["candidate_id"]
    db.link_collection_candidates(col, [candidate])
    assert db.project_source_ids(owner, ready_only=False) == []
    first = (ingest.ingest_url(url, project_id=owner) if first_capture == "direct"
             else community.acquire_thread(url, project_id=owner, listing=listing))
    second = (community.acquire_thread(url, project_id=owner, listing=listing) if first_capture == "direct"
              else ingest.ingest_url(url, project_id=owner))
    assert first["source_id"] == second["source_id"]
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    # Reopen a populated pre-bridge row, not an empty database, then repair its missing pointer.
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=NULL WHERE id=?", (candidate,))
    db.close_thread_connection()
    db.init_db()
    community.attach_subreddit_catalog(later, URL)
    assert db.project_source_ids(later, ready_only=False) == []
    assert db.connect().execute("SELECT COUNT(*) FROM source_collections").fetchone()[0] == 0
    captured = candidates.catalog_capture(later, col, candidate)
    assert captured["source_id"] == first["source_id"] and captured["job_id"] is None
    crosspost = remember("different123")
    db.link_collection_candidates(col, [crosspost])
    assert crosspost != candidate
    assert db.connect().execute("SELECT source_id FROM candidates WHERE id=?", (crosspost,)).fetchone()[0] is None


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


URL = "https://www.reddit.com/r/smallbusiness/"


def remember(post):
    return candidates.remember([{"external_id": f"reddit:{post}",
                                "url": URL + f"comments/{post}/title/", "title": post}], "reddit", None, {})[0]


@pytest.mark.parametrize("project_id", [None, "", "does-not-exist"])
def test_unknown_project_cannot_leave_an_orphan_catalog(project_id):
    before = db.connect().total_changes
    with pytest.raises((ValueError, LookupError)):
        community.attach_subreddit_catalog(project_id, URL)
    assert db.connect().total_changes == before
    assert db.list_collections() == []


def test_next_page_reconciles_only_its_ids_not_the_entire_catalog():
    first = db.create_project("first")["id"]
    second = db.create_project("second")["id"]
    col = community.attach_subreddit_catalog(first, URL)["id"]
    old = remember("old")
    db.link_collection_candidates(col, [old])
    community.attach_subreddit_catalog(second, URL)
    candidates.dismiss(first, old, "keep dismissed")
    new = remember("new")
    # INSERT OR IGNORE still visits old rows and runs BEFORE INSERT triggers.
    # A page must not attempt reconciliation of any previous page's members.
    db.connect().execute(f"""CREATE TEMP TRIGGER no_previous_page BEFORE INSERT ON candidate_projects
        WHEN NEW.candidate_id='{old}' BEGIN SELECT RAISE(ABORT, 'revisited previous page'); END""")
    db.link_collection_candidates(col, [new])
    for pid in (first, second):
        assert db.connect().execute("SELECT state FROM candidate_projects WHERE project_id=? AND candidate_id=?",
                                    (pid, new)).fetchone()[0] == "available"
        assert db.project_source_ids(pid, ready_only=False) == []
    assert candidates.list_for_project(first, state="user_dismissed")[0]["id"] == old


@pytest.mark.parametrize("action", ["catalog_capture", "catalog_dismiss", "catalog_restore"])
def test_catalog_authority_and_mutation_share_a_writer_transaction(monkeypatch, action):
    pid = db.create_project("owner")["id"]
    col = community.attach_subreddit_catalog(pid, URL)["id"]
    cid = remember("one")
    db.link_collection_candidates(col, [cid])
    validate = candidates.catalog_candidate

    def guard(*args):
        assert db.connect().in_transaction, "detach can win between check and mutation"
        validate(*args)

    monkeypatch.setattr(candidates, "catalog_candidate", guard)
    getattr(candidates, action)(pid, col, cid)


def test_attachment_repairs_legacy_pointers_in_bounded_batches_without_replacing_conflicts():
    owner = db.create_project("old catalog owner")["id"]
    later = db.create_project("new catalog reader")["id"]
    col = community.attach_subreddit_catalog(owner, URL)["id"]
    ids = [remember(f"p{i}") for i in range(205)]
    db.link_collection_candidates(col, ids)
    source = identity.resolve_or_create_source(identity.Candidate(
        platform="community", external_id="reddit:p0", url=URL + "comments/p0/title/"),
        owner, initial_status="ready").source
    wrong = db.upsert_source(platform="youtube", external_id="unrelated", url="https://example.test/unrelated")
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=NULL WHERE id=?", (ids[0],))
        conn.execute("UPDATE candidates SET source_id=? WHERE id=?", (wrong["id"], ids[1]))
    statements = []
    db.connect().set_trace_callback(statements.append)
    try:
        community.attach_subreddit_catalog(later, URL)
    finally:
        db.connect().set_trace_callback(None)
    assert db.connect().execute("SELECT source_id FROM candidates WHERE id=?", (ids[0],)).fetchone()[0] == source["id"]
    assert db.connect().execute("SELECT source_id FROM candidates WHERE id=?", (ids[1],)).fetchone()[0] == wrong["id"]
    assert len(candidates.list_for_project(later, limit=500)) == 205
    assert db.project_source_ids(later, ready_only=False) == []
    assert sum(s == "COMMIT" for s in statements) >= 3, "all membership repair held in one unbounded writer"
    community.attach_subreddit_catalog(later, URL)
    assert len(candidates.list_for_project(later, limit=500)) == 205
    assert len(db.list_sources()) == 2


def test_conflicting_source_pointer_is_refused_without_merging_or_attaching():
    pid = db.create_project("conflicting legacy row")["id"]
    col = community.attach_subreddit_catalog(pid, URL)["id"]
    cid = remember("one")
    db.link_collection_candidates(col, [cid])
    wrong = db.upsert_source(platform="community", external_id="reddit:other", url=URL + "comments/other/", status="ready")
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=? WHERE id=?", (wrong["id"], cid))
    before = db.connect().total_changes
    with pytest.raises(LookupError, match="identity conflict"):
        candidates.catalog_capture(pid, col, cid)
    assert db.connect().total_changes == before
    assert db.project_source_ids(pid, ready_only=False) == []
    assert db.list_jobs(10) == []


def test_detach_wins_before_action_without_partial_decisions_or_jobs():
    pid = db.create_project("detached")["id"]
    col = community.attach_subreddit_catalog(pid, URL)["id"]
    cid = remember("one")
    db.link_collection_candidates(col, [cid])
    db.remove_project_collections(pid, [col])
    before = db.connect().total_changes
    for act in (candidates.catalog_capture, candidates.catalog_dismiss, candidates.catalog_restore):
        with pytest.raises(LookupError):
            act(pid, col, cid)
    assert db.connect().total_changes == before
    assert db.list_jobs(10) == []
    assert candidates.list_for_project(pid)[0]["state"] == "available"


def test_detach_cannot_interleave_with_a_validated_capture(monkeypatch):
    import threading

    pid = db.create_project("concurrent detach")["id"]
    col = community.attach_subreddit_catalog(pid, URL)["id"]
    cid = remember("one")
    db.link_collection_candidates(col, [cid])
    started = threading.Event()
    outcomes, errors = [], []

    def detach():
        try:
            started.set()
            db.remove_project_collections(pid, [col])
            outcomes.append("detached")
        except Exception as exc:
            errors.append(exc)
        finally:
            db.close_thread_connection()

    thread = threading.Thread(target=detach)
    validate = candidates.catalog_candidate
    mark = candidates.mark

    def guard(*args):
        validate(*args)
        thread.start()
        assert started.wait(5)

    def marking(*args, **kwargs):
        assert outcomes == [], "detach committed while the authorized action was in flight"
        outcomes.append("captured")
        return mark(*args, **kwargs)

    monkeypatch.setattr(candidates, "catalog_candidate", guard)
    monkeypatch.setattr(candidates, "mark", marking)
    try:
        result = candidates.catalog_capture(pid, col, cid)
    finally:
        thread.join(5)
    assert not thread.is_alive() and errors == []
    assert outcomes == ["captured", "detached"]
    assert result["job_id"] and not db.project_has_collection(pid, col)
