"""B2 — Completeness + Capture Queue (0.33.1): a successful capture and a COMPLETE capture are different states, offline ($0).

Completeness is first-class provenance on the source: what was captured vs what the platform reports, the branches the
reading admits it left out, the method, the time. A partial capture is visibly partial (Part-Q gate 8) and never deletes
what an earlier reading saw; only a complete reading can say a post vanished; several waiting requests form a queue
(gate 12). (Sorts after test_l1.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_b2_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import acquire, community, db, fake_ai, jobs, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k9_community import THREAD_URL, _thread_json  # noqa: E402
from tests.test_l1_browser_capture import _capture_contract, _reddit_blocked, _run_next  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "reddit_client_id", None)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _comp(sid):
    return json.loads(db.get_source(sid)["completeness"])


def test_listing_with_more_stubs_is_partial_and_says_so(monkeypatch):
    listing, comments = _thread_json()
    comments["data"]["children"].append({"kind": "more", "data": {"count": 37, "children": ["x1", "x2"]}})
    listing["data"]["children"][0]["data"]["num_comments"] = 48
    monkeypatch.setattr(community, "_json_get", lambda url: [listing, comments])
    pid = db.create_project("B2", "x")["id"]
    r = community.acquire_thread(THREAD_URL, project_id=pid)
    c = _comp(r["source_id"])
    assert c["status"] == "partial" and c["captured"] == 11 and c["expected"] == 48 and c["missing"] == 37 and c["load_more_remaining"] == 1 and c["unloaded_count"] == 37
    assert "not loaded" in c["partial_reason"] and c["method"] == "json" and c["accepted"] is False
    assert "11 of ~48 comments captured" in db.get_source(r["source_id"])["description"]


def test_small_shortfall_is_complete_with_the_gap_recorded(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())          # 11 comments, num_comments 11
    r = community.acquire_thread(THREAD_URL, project_id=db.create_project("B2", "x")["id"])
    c = _comp(r["source_id"])
    assert c["status"] == "complete" and c["missing"] == 0
    listing, comments = _thread_json()
    listing["data"]["children"][0]["data"]["num_comments"] = 12                         # one removed comment still counted by the platform
    monkeypatch.setattr(community, "_json_get", lambda url: [listing, comments])
    r = community.acquire_thread(THREAD_URL, project_id=db.create_project("B2b", "x")["id"])
    c = _comp(r["source_id"])
    assert c["status"] == "complete" and c["missing"] == 1


def test_partial_browser_capture_stays_visibly_partial_and_accept_keeps_it_partial(monkeypatch):
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B2", "x")["id"]
    j = db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    _run_next()
    cap = _capture_contract()
    cap["comments"] = cap["comments"][:4]                                               # the page had 4 of 11 loaded
    cap["capture"] = {"status": "partial", "captured": 4, "expected": 11, "load_more_remaining": 2, "method": "dom"}
    acquire.resolve_capture(j["id"], cap)
    job, st = _run_next()
    assert st == "done"
    sid = db.get_job(j["id"])["payload"]["source_id"]
    c = _comp(sid)
    assert c["status"] == "partial" and c["captured"] == 4 and c["expected"] == 11 and c["missing"] == 7 and c["load_more_remaining"] == 2 and c["method"] == "dom"
    src = db.get_source(sid)
    assert src["status"] == "ready" and "4 of ~11 comments captured" in src["description"] and src["error_class"] is None and not src["error"]
    # gate 8: accepting it records acceptance — it never becomes "complete"
    from neurosearch import api
    out = api.api_source_accept_partial(sid)
    assert out["completeness"]["accepted"] is True and out["completeness"]["status"] == "partial"
    assert api.api_source_thread(sid)["completeness"]["status"] == "partial"


def test_partial_capture_merges_and_never_deletes_what_was_known(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    pid = db.create_project("B2", "x")["id"]
    sid = community.acquire_thread(THREAD_URL, project_id=pid)["source_id"]
    assert _comp(sid)["status"] == "complete"
    # later, a partial browser capture with only 4 comments arrives (e.g. Reopen and capture more on a slow page)
    cap = _capture_contract()
    cap["comments"] = cap["comments"][:4]
    cap["capture"] = {"status": "partial", "captured": 4, "expected": 11, "method": "dom"}
    r = community.acquire_thread(THREAD_URL, project_id=pid, capture=cap)
    conn = db.connect()
    rows = conn.execute("SELECT post_id, availability, deleted, ordinal FROM community_posts WHERE source_id=? ORDER BY ordinal", (sid,)).fetchall()
    assert len(rows) == 12 and all(x["availability"] == "available" and x["deleted"] == 0 for x in rows), "the 7 unseen comments are still available — a partial read says nothing about them"
    c = _comp(sid)
    assert c["status"] == "complete" and c["captured"] == 11, "merged with the earlier reading, the thread reaches the platform's count"
    assert r["posts"] == 12
    # a partial capture that adds a NEW comment grows the thread and keeps the earlier locators' order
    cap2 = _capture_contract()
    cap2["comments"] = [{"reddit_id": "c99", "parent_id": "abc123", "depth": 1, "author": "late_owner", "text": "We bought a practice in 2024 and the first-year software migration cost far more than projected.", "score": 2, "created_at": 1780001000, "edited": False, "deleted": False, "permalink": "https://www.reddit.com/r/smallbusiness/comments/abc123/x/c99/"}]
    cap2["capture"] = {"status": "partial", "captured": 1, "expected": 12, "method": "dom"}
    community.acquire_thread(THREAD_URL, project_id=pid, capture=cap2)
    rows2 = conn.execute("SELECT post_id, ordinal FROM community_posts WHERE source_id=? ORDER BY ordinal", (sid,)).fetchall()
    assert len(rows2) == 13 and rows2[-1]["post_id"] == "c99" and [x["post_id"] for x in rows2[:12]] == [x["post_id"] for x in rows]


def test_complete_reading_after_partial_marks_vanished_posts_unavailable(monkeypatch):
    pid = db.create_project("B2", "x")["id"]
    cap = _capture_contract()
    cap["capture"] = {"status": "partial", "captured": 11, "expected": 30, "load_more_remaining": 3, "method": "dom"}
    sid = community.acquire_thread(THREAD_URL, project_id=pid, capture=cap)["source_id"]
    assert _comp(sid)["status"] == "partial"
    listing, comments = _thread_json()
    comments["data"]["children"] = [c for c in comments["data"]["children"] if c["data"]["id"] != "c4"]   # a complete reading: c4 is gone
    monkeypatch.setattr(community, "_json_get", lambda url: [listing, comments])
    community.acquire_thread(THREAD_URL, project_id=pid)
    c = _comp(sid)
    assert c["status"] == "complete" and c["method"] == "json"
    row = db.connect().execute("SELECT availability, deleted, text FROM community_posts WHERE source_id=? AND post_id='c4'", (sid,)).fetchone()
    assert row["availability"] == "unavailable" and row["deleted"] == 1 and "software" in row["text"]


def test_queue_of_several_requests_and_reopen(monkeypatch):
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B2", "x")["id"]
    urls = [THREAD_URL, "https://www.reddit.com/r/accounting/comments/def456/client_retention/", "https://www.reddit.com/r/taxpros/comments/ghi789/seller_financing/"]
    for u in urls:
        db.create_job("ingest_url", {"url": u, "project_id": pid, "tags": []})
        _run_next()
    q = acquire.pending_captures(project_id=pid)
    assert [r["canonical_url"].split("/comments/")[1].split("/")[0] for r in q] == ["abc123", "def456", "ghi789"], "oldest first, one per thread"
    assert acquire.attention(pid)["browser_needed"] == 3
    # one lands; the queue advances
    acquire.resolve_capture(q[0]["job_id"], _capture_contract())
    _run_next()
    assert [r["canonical_url"].split("/comments/")[1].split("/")[0] for r in acquire.pending_captures(project_id=pid)] == ["def456", "ghi789"]
    # Reopen and capture more on the captured (complete) thread: the server cannot read → a new request for the SAME source, no duplicate
    from neurosearch import api
    sid = q[0]["source_id"]
    r = api.api_source_recapture(sid, api.RecaptureIn(project_id=pid))
    assert r.get("job_id")
    _run_next()
    again = [x for x in acquire.pending_captures(project_id=pid) if x["source_id"] == sid]
    assert len(again) == 1 and api.api_source_recapture(sid, api.RecaptureIn(project_id=pid)).get("already_waiting")
    assert db.connect().execute("SELECT COUNT(*) FROM sources WHERE platform='community'").fetchone()[0] == 3


def test_synthesis_over_a_partial_thread_says_so(monkeypatch):
    """G7 synthesis never speaks as full-thread consensus over a thread the app only partly holds."""
    from neurosearch import claims
    from tests.test_k9_community import _note
    pid = db.create_project("B2", "Buying a small accounting practice with an SBA loan: what owners actually experience")["id"]
    cap = _capture_contract()
    cap["capture"] = {"status": "partial", "captured": 11, "expected": 412, "load_more_remaining": 9, "method": "dom"}
    sid = community.acquire_thread(THREAD_URL, project_id=pid, capture=cap)["source_id"]
    posts = {p["post_id"]: p for p in community.posts_of(sid)}
    for pidx in ("c4", "c5", "c6"):
        _note(pid, sid, posts[pidx]["text"][:300], f"post {posts[pidx]['ordinal']}", importance=4)
    claims.ensure(pid)
    syn = community.synthesize(pid)
    fy = next(s for s in syn if "first-year maintenance" in s["statement"])
    assert fy["kind"] == "FREQUENTLY_REPORTED" and fy["coverage"] and fy["coverage"]["partial_threads"][0]["source_id"] == sid
    assert "11 of ~412 comments" in fy["coverage"]["note"] and "not full-thread consensus" in fy["coverage"]["note"]
    assert community.syntheses(pid)[0]["coverage"]["note"]
    # the chat's research_state carries the same qualifier
    from neurosearch import qa
    txt = qa._run_tool("research_state", {}, db.get_project(pid), [], [])
    assert "PARTIAL:" in txt and "11 of ~412" in txt
    # a complete reading of the same thread clears the qualifier
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    community.acquire_thread(THREAD_URL, project_id=pid, force=True)
    assert _comp(sid)["status"] == "complete"
    syn2 = community.synthesize(pid)
    assert next(s for s in syn2 if "first-year maintenance" in s["statement"])["coverage"] is None


def test_findings_on_a_community_thread_cite_the_post(monkeypatch):
    """0.34.2: findings extracted from a thread carry a citation (post locator + permalink) — never 'Untitled source'."""
    from neurosearch import findings
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    pid = db.create_project("cite", "buying an accounting practice: first-year costs")["id"]
    sid = community.acquire_thread(THREAD_URL, project_id=pid)["source_id"]
    r = findings.suggest_for_source(pid, sid)
    notes = db.list_project_notes(pid, status="suggested")
    assert r.get("suggested", 0) >= 1 and notes
    for n in notes:
        assert n["citations"] and n["citations"][0]["source_id"] == sid and n["citations"][0]["title"]
        assert n["citations"][0]["timestamp"].startswith(("post", "comment")) and "reddit.com" in (n["citations"][0]["link"] or "")
