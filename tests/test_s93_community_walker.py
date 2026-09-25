"""S93 (2026-09-24) — "Scan this community": every conversation of a logged-in community, not one post at a time.

Kyle: "using the SMB Market community example, how can I just capture every single one? I dont want to manually open
each one at a time." smbmarket.com is its own Next.js app with a cookie-authenticated JSON API
(community-api.smbmarket.com: feed?kind=latest&cursor=…, posts/{id}/comments?cursor=…). The extension walks it in
the person's tab with their session, builds `community_thread_capture/1` per thread, and posts batches to
POST /api/community/threads; each becomes a ready community source through the SAME `store_thread` path a Reddit
thread takes. The contract is platform-neutral; the walker's platform adapter is the only smbmarket-specific code."""
from __future__ import annotations

import json
import pathlib

import pytest

from neurosearch import community, db, ingest, safe_fetch
from neurosearch.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    monkeypatch.setattr(ingest, "_embed_ready", lambda sid: 0)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _capture(tid="d42c6b49", n_comments=3, expected=None, space="deal-talk"):
    comments = [{"id": f"c{i}", "parent_id": None if i == 0 else "c0", "author": f"Member {i}", "text": f"I bought a laundromat in 2024 and comment {i} says the SDE was $180k after add-backs.",
                 "score": i, "created_at": "2026-09-24T00:46:57.558Z", "edited": i == 1, "deleted": False, "permalink": f"https://smbmarket.com/dashboard/community/post/{tid}/#c{i}"}
                for i in range(n_comments)]
    return {"contract": "community_thread_capture/1", "platform": "smbmarket", "community": f"SMB Market · {space}",
            "thread": {"id": tid, "title": "Owning from Afar", "author": "Michael Herston", "body": "I am looking to own my first business in a city where I don't live.",
                       "created_at": "2026-09-23T18:00:00.000Z", "score": 4, "url": f"https://smbmarket.com/dashboard/community/post/{tid}/",
                       "expected_comments": expected if expected is not None else n_comments, "edited": False, "deleted": False},
            "comments": comments, "capture": {"status": "complete", "captured": n_comments, "expected": expected if expected is not None else n_comments, "method": "community api"}}


def test_the_generic_contract_becomes_the_same_thread_shape_reddit_produces():
    t = community.thread_from_generic_capture(_capture())
    assert t["platform"] == "smbmarket" and t["thread_id"] == "d42c6b49" and t["community"] == "SMB Market · deal-talk"
    assert t["url"].startswith("https://smbmarket.com/dashboard/community/post/")
    assert abs(t["created"] - 1790186400.0) < 1, "ISO-8601 → epoch (UTC)"
    kinds = [p["kind"] for p in t["posts"]]
    assert kinds == ["post", "comment", "comment", "comment"]
    assert [p["depth"] for p in t["posts"]] == [0, 1, 2, 2], "depth from the parent chain, the platform never said it"
    assert t["posts"][0]["text"].startswith("Owning from Afar\n\n")


def test_a_reply_to_something_not_in_the_thread_hangs_off_the_root():
    cap = _capture(n_comments=2)
    cap["comments"][1]["parent_id"] = "gone"
    t = community.thread_from_generic_capture(cap)
    assert t["posts"][2]["parent_id"] == "d42c6b49" and t["posts"][2]["depth"] == 1


def test_the_walker_batch_endpoint_stores_ready_community_sources(client):
    p = db.create_project("Business acquisition", "buy a laundromat")
    caps = [_capture("aaaa0001"), _capture("aaaa0002", n_comments=0), {"contract": "community_thread_capture/1", "platform": "smbmarket", "thread": {}}]
    r = client.post("/api/community/threads", json={"project_id": p["id"], "threads": caps}, headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] == 2 and body["failed"] == 1
    bad = [x for x in body["results"] if not x["ok"]][0]
    assert "no thread id" in bad["error"]
    src = db.get_source(body["results"][0]["source_id"])
    assert src["status"] == "ready" and src["platform"] == "community" and src["external_id"] == "smbmarket:aaaa0001"
    assert src["channel"] == "SMB Market · deal-talk" and json.loads(src["completeness"])["status"] == "complete"
    rows = db.connect().execute("SELECT COUNT(*) FROM community_posts WHERE source_id=?", (src["id"],)).fetchone()[0]
    assert rows == 4
    # attached to the project, and the same thread again is the same source (identity), not a second one
    assert db.connect().execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=?", (p["id"], src["id"])).fetchone()
    r2 = client.post("/api/community/threads", json={"project_id": p["id"], "threads": [_capture("aaaa0001", n_comments=4)]}, headers=H).json()
    assert r2["results"][0]["source_id"] == src["id"]
    assert client.post("/api/community/threads", json={"project_id": "nope", "threads": []}, headers=H).status_code == 404
    assert client.post("/api/community/threads", json={"project_id": p["id"], "threads": [_capture(f"b{i}") for i in range(51)]}, headers=H).status_code == 413


def test_a_partial_walk_is_recorded_as_partial():
    t = community.thread_from_generic_capture(_capture(n_comments=2, expected=40))
    c = community.completeness(t)
    assert c["status"] == "partial" and c["captured"] == 2 and c["expected"] == 40


def test_the_extension_ships_the_walker_and_the_adapter():
    ext = ROOT / "extension"
    bg = (ext / "background.js").read_text(); pop = (ext / "popup.js").read_text(); html = (ext / "popup.html").read_text()
    ad = (ext / "community-adapters.js").read_text()
    assert "importScripts('community-adapters.js');" in bg and "async function runCommunityScan(rec)" in bg
    assert "msg.type === 'cscan-start'" in bg and "msg.type === 'cscan-cancel'" in bg and "msg.type === 'cscan-get'" in bg
    assert "api('/api/community/threads'" in bg, "batches go through the app's endpoint"
    assert "credentials: 'include'" in bg.split("async function pageJson")[1].split("}, args: [url]")[0], "reads happen in the tab with the person's session"
    assert "self.NSCommunityAdapters = {" in ad and "contract: 'community_thread_capture/1'" in ad
    assert "smbmarket.com/dashboard/community" in ad
    assert ad.rstrip().endswith("})();"), "scoped, like thread-capture.js (S92's global-collision lesson)"
    assert 'id="communityScan"' in html and '<option value="365" selected>1 year</option>' in html, "1 year is the default walk-back (Kyle)"
    assert '<script src="community-adapters.js"></script>' in html and html.index("community-adapters.js") < html.index('src="popup.js"')
    assert "type: 'cscan-start', tabId: TAB.id, projectId: pid, maxAgeDays: age ? +age : null" in pop
    assert json.loads((ext / "manifest.json").read_text())["version"] in ("1.10.0", "1.11.0", "1.11.1", "1.11.2")
