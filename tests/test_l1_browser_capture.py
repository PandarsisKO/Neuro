"""B1 — Browser Capture + Recovery (0.33.0): the Part-Q release gates that belong to B1, offline ($0).

A browser-solvable failure becomes `requires_browser` (a parked external job, provider "browser"), not a generic failure;
the source stays in its project; the extension's capture resolves the SAME job and the SAME source; the state survives a
restart (it is the durable job row); a failure the browser cannot solve stays a normal failure; Reddit falls JSON → HTML
→ browser; a reading that succeeds never asks for Chrome; identity is preserved; an owned global source bypasses the
browser; the queue/API state carries the recommendation; nothing in those responses carries cookies. (Sorts after test_k9b.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_b1_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import acquire, community, db, fake_ai, ingest, jobs, safe_fetch, webpage  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from neurosearch.safe_fetch import FetchResult  # noqa: E402

from tests.test_k9_community import THREAD_URL, _thread_json  # noqa: E402


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


def _reddit_blocked(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing — www.reddit.com: HTTP 403")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url, **kw: "<html><head><title>Welcome to Reddit</title></head><body>log in</body></html>")


def _run_next(kinds=("ingest_url",)):
    job = db.claim_job(kinds, worker_id="sim")
    assert job, "no claimable job"
    return job, jobs.execute(job, "sim")


def _capture_contract():
    listing, comments = _thread_json()
    link = listing["data"]["children"][0]["data"]
    out = []

    def walk(children, parent, depth):
        for ch in children:
            d = ch["data"]
            out.append({"reddit_id": d["id"], "parent_id": parent, "depth": depth, "author": d["author"], "text": d["body"], "score": d["score"],
                        "created_at": d["created_utc"], "edited": d.get("edited", False), "deleted": False, "permalink": "https://www.reddit.com" + d["permalink"]})
            if isinstance(d.get("replies"), dict):
                walk(d["replies"]["data"]["children"], d["id"], depth + 1)
    walk(comments["data"]["children"], link["id"], 1)
    return {"contract": "reddit_thread_capture/1", "method": "dom", "canonical_url": THREAD_URL,
            "thread": {"reddit_id": link["id"], "subreddit": "r/smallbusiness", "title": link["title"], "author": link["author"], "body": link["selftext"], "score": link["score"],
                       "created_at": link["created_utc"], "edited": False, "deleted": False, "permalink": "https://www.reddit.com" + link["permalink"], "expected_comments": 11},
            "comments": out, "capture": {"status": "complete", "captured": len(out), "expected": 11}}


# ---------------------------------------------------------------- gates 1, 2, 6, 11, 14: a blocked thread becomes a browser request

def test_reddit_blocked_becomes_requires_browser_not_failed(monkeypatch):
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B1", "buying an accounting practice")["id"]
    j = db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    job, st = _run_next()
    assert st == "external_pending"
    row = db.get_job(j["id"])
    assert row["status"] == "external_pending" and row["external_provider"] == "browser" and row["external_kind"] == "capture:reddit_thread"
    assert "browser needed" in (row["message"] or "").lower()
    # gate 6: the message shows that JSON and the server-rendered page were both tried before the browser was asked
    why = (row["payload"] or {}).get("capture", {}).get("why", "")
    assert "HTTP 403" in why and "Welcome to Reddit" in why
    # gate 2: the project keeps a visible source row, pending, classified
    src = db.get_source(row["payload"]["source_id"])
    assert src["status"] == "pending" and src["error_class"] == "browser_solvable:blocked" and src["platform"] == "community" and src["external_id"] == "reddit:abc123"
    assert "your browser can access it" in src["error"] and "403" not in src["error"]
    assert db.connect().execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=?", (pid, src["id"])).fetchone()
    # gate 11 + 14: the queue carries the recommendation and nothing secret
    q = acquire.pending_captures(project_id=pid)
    assert len(q) == 1 and q[0]["job_id"] == j["id"] and q[0]["adapter"] == "reddit_thread" and q[0]["capture_kind"] == "reddit_thread_capture" and q[0]["status"] == "pending"
    assert q[0]["canonical_url"].startswith("https://reddit.com/r/smallbusiness/comments/abc123") or q[0]["canonical_url"].startswith("https://www.reddit.com/r/smallbusiness/comments/abc123")
    assert "cookie" not in str(q).lower() and "token" not in str(q).lower()
    assert acquire.attention(pid)["browser_needed"] == 1 and acquire.extension_status()["state"] == "not_detected"


# ---------------------------------------------------------------- gates 3, 4, 9: the capture resolves the SAME job and source, across a restart

def test_capture_resolves_the_same_job_and_source_after_restart(monkeypatch):
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B1", "buying an accounting practice")["id"]
    j = db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    _run_next()
    sid = db.get_job(j["id"])["payload"]["source_id"]
    # "restart": a fresh connection and the recovery pass — the request is still there (it is the durable job row)
    db._local.conn = None
    jobs.recover_once() if hasattr(jobs, "recover_once") else None
    assert acquire.pending_capture(j["id"])["source_id"] == sid
    # the extension posts the capture contract
    r = acquire.resolve_capture(j["id"], _capture_contract())
    assert r["job_id"] == j["id"] and r["source_id"] == sid
    assert db.get_job(j["id"])["status"] == "queued"
    job, st = _run_next()
    assert job["id"] == j["id"] and st == "done"
    src = db.get_source(sid)
    assert src["status"] == "ready" and src["external_id"] == "reddit:abc123" and src["platform"] == "community"
    assert db.connect().execute("SELECT COUNT(*) FROM sources WHERE platform='community'").fetchone()[0] == 1, "one source, never a duplicate"
    posts = db.connect().execute("SELECT post_id, parent_id, corrected_by FROM community_posts WHERE source_id=?", (sid,)).fetchall()
    assert len(posts) == 12 and {p["post_id"]: p["corrected_by"] for p in posts}["c1"] == "c2", "the DOM contract yields the same tree and corrections"
    assert not acquire.pending_captures(project_id=pid)
    assert db.connect().execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=?", (pid, sid)).fetchone()
    # a second delivery for the same job is refused (nothing is waiting), never a second acquisition
    with pytest.raises(LookupError):
        acquire.resolve_capture(j["id"], _capture_contract())


def test_unsolicited_send_this_page_resolves_the_waiting_request(monkeypatch):
    """The user pressed the extension on the thread without going through Open & Capture: still the same job/source."""
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B1", "x")["id"]
    j = db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    _run_next()
    waiting = acquire.request_for(THREAD_URL, pid)
    assert waiting and waiting["job_id"] == j["id"]
    assert acquire.request_for("https://www.reddit.com/r/other/comments/zzz/x/", pid) is None
    import asyncio
    from neurosearch import api
    r = asyncio.run(api.api_ingest_thread(pid, api.ThreadIn(url=THREAD_URL, listing=_thread_json())))
    assert r.get("resolved_pending") and r["job_id"] == j["id"]
    job, st = _run_next()
    assert st == "done" and db.connect().execute("SELECT COUNT(*) FROM sources WHERE platform='community'").fetchone()[0] == 1


# ---------------------------------------------------------------- gate 5: a failure the browser cannot solve stays a failure

def test_non_browser_solvable_failure_stays_failed(monkeypatch):
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda url, **kw: FetchResult(url=url, status=404, content_type="text/html", body=b"<html><body>nope</body></html>"))
    pid = db.create_project("B1", "x")["id"]
    db.create_job("ingest_url", {"url": "https://www.example.com/missing-page", "project_id": pid, "tags": []})
    job, st = _run_next()
    assert st == "failed" and db.get_job(job["id"])["status"] == "failed"
    assert not acquire.pending_captures()
    src = [s for s in db.list_sources(limit=100) if "missing-page" in (s["url"] or "")]
    assert src and src[0]["status"] == "failed" and src[0]["error_class"] is None      # the page path sets error text; not a browser case
    # a document adapter never asks for the browser even on 403
    f = acquire.AcquisitionFailure("x", adapter="document", cls="blocked")
    assert f.browser_solvable is False and f.error_class == "blocked"


# ---------------------------------------------------------------- gate 7: a reading that succeeds never asks for Chrome

def test_successful_reading_never_asks_for_the_browser(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    pid = db.create_project("B1", "x")["id"]
    db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    job, st = _run_next()
    assert st == "done" and not acquire.pending_captures() and acquire.attention(pid)["browser_needed"] == 0
    assert db.get_source(db.connect().execute("SELECT id FROM sources WHERE platform='community'").fetchone()[0])["error_class"] is None


# ---------------------------------------------------------------- gate 10: an owned global source bypasses the browser entirely

def test_owned_global_source_bypasses_browser(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    p1 = db.create_project("A", "x")["id"]
    db.create_job("ingest_url", {"url": THREAD_URL, "project_id": p1, "tags": []})
    _run_next()
    # Reddit is now blocked, and a second project wants the same thread
    _reddit_blocked(monkeypatch)
    p2 = db.create_project("B", "y")["id"]
    db.create_job("ingest_url", {"url": THREAD_URL, "project_id": p2, "tags": []})
    job, st = _run_next()
    assert st == "done" and not acquire.pending_captures()
    sid = db.connect().execute("SELECT id FROM sources WHERE platform='community'").fetchone()[0]
    assert db.connect().execute("SELECT COUNT(*) FROM project_sources WHERE source_id=?", (sid,)).fetchone()[0] == 2


# ---------------------------------------------------------------- generic web pages: the same state, adapter-aware

def test_blocked_web_page_becomes_requires_browser_and_generic_capture_completes_it(monkeypatch):
    calls = {"n": 0}

    def fetch(url, **kw):
        calls["n"] += 1
        return FetchResult(url=url, status=403, content_type="text/html", body=b"<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>")
    monkeypatch.setattr(safe_fetch, "safe_fetch", fetch)
    pid = db.create_project("B1", "x")["id"]
    j = db.create_job("ingest_url", {"url": "https://publisher.example.com/article/valuation-multiples", "project_id": pid, "tags": []})
    job, st = _run_next()
    assert st == "external_pending"
    q = acquire.pending_captures(project_id=pid)
    assert q[0]["adapter"] == "web_page" and q[0]["capture_kind"] == "page_capture"
    src = db.get_source(q[0]["source_id"])
    assert src["error_class"] == "browser_solvable:challenge" and src["status"] == "pending" and "your browser can" in src["error"]
    html = "<html><head><title>Valuation multiples</title></head><body><main><h1>Valuation multiples</h1>" + "".join(
        f"<p>Paragraph {i}: small accounting practices trade at roughly one times annual gross revenue depending on client retention.</p>" for i in range(20)) + "</main></body></html>"
    acquire.resolve_capture(j["id"], {"contract": "page_capture/1", "method": "dom", "html": html, "title": "Valuation multiples"})
    job, st = _run_next()
    assert st == "done"
    src = db.get_source(q[0]["source_id"])
    assert src["status"] == "ready" and src["title"] == "Valuation multiples" and db.connect().execute("SELECT COUNT(*) FROM sources WHERE platform='web'").fetchone()[0] == 1


def test_login_wall_and_js_pages_classify_but_plain_404_does_not():
    assert acquire.classify_page(403, "<html>Access denied</html>") == "challenge"
    assert acquire.classify_page(403, "<html>forbidden</html>") == "blocked"
    assert acquire.classify_page(404, "") == "not_found" and acquire.classify_page(500, "") == "http_error" and acquire.classify_page(200, "<p>an article about CAPTCHA history</p>") in (None, "challenge")
    with pytest.raises(webpage.Blocked) as e:
        webpage.read_page("https://x.example.com/p", html_text="<html><body><p>Please log in to continue reading.</p></body></html>")
    assert e.value.cls == "login_wall" and e.value.browser_solvable
    with pytest.raises(acquire.AcquisitionFailure) as e:
        webpage.read_page("https://x.example.com/p", html_text="<html><body><div id=app></div></body></html>")
    assert e.value.cls == "js_required" and e.value.browser_solvable


# ---------------------------------------------------------------- extension presence + cancel

def test_heartbeat_and_cancel(monkeypatch):
    assert acquire.extension_status()["state"] == "not_detected"
    st = acquire.heartbeat("1.5")
    assert st["state"] == "ready" and st["version"] == "1.5"
    _reddit_blocked(monkeypatch)
    pid = db.create_project("B1", "x")["id"]
    j = db.create_job("ingest_url", {"url": THREAD_URL, "project_id": pid, "tags": []})
    _run_next()
    assert acquire.cancel_capture(j["id"]) is True and acquire.cancel_capture(j["id"]) is False
    assert db.get_job(j["id"])["status"] == "cancelled" and not acquire.pending_captures()
    assert db.get_source(db.get_job(j["id"])["payload"]["source_id"])["status"] == "failed"
