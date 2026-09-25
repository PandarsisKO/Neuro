"""S95 (2026-09-24) — "Scan this subreddit". Kyle's idea: walk a subreddit's listing, weigh titles and bodies against
the brief, and capture only the posts worth having — through the extension, since Reddit blocks the server. No OCR:
the extension reads the same structured listing Reddit serves the person's browser (/r/<sub>/new.json with their
session), so titles, bodies, dates, scores and permalinks arrive intact.

Server side: POST /api/community/proposals turns the listing into a review card exactly like a YouTube channel
(proposed sources, rank_proposed over title + body, best N pre-selected); Start (approve_proposed) ingests a
proposed thread through the URL path, so a Reddit block becomes the parked browser capture the extension already
fulfils, and identity lands the capture on the SAME proposed row."""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest

from neurosearch import acquire, community, db, ingest, jobs, safe_fetch
from neurosearch.config import settings

H = {"Authorization": "Bearer t0k"}
SUB = "https://www.reddit.com/r/smallbusiness/new/"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "reddit_client_id", None)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing — www.reddit.com: HTTP 403")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url, **kw: "<html><head><title>Welcome to Reddit</title></head><body>log in</body></html>")
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _items(n=6):
    return [{"id": f"p{i:06x}", "title": f"Bought a small accounting practice, question {i} about SDE and seller notes", "body": f"Body {i}: the seller wants 20% down and an SBA 7a loan for the rest.",
             "author": f"owner{i}", "created_at": 1790000000 - i * 86400, "score": 40 - i, "expected_comments": 3 + i,
             "url": f"https://www.reddit.com/r/smallbusiness/comments/p{i:06x}/bought_a_small_accounting_practice_{i}/"} for i in range(n)]


def test_a_walked_listing_becomes_a_ranked_review_card(client):
    p = db.create_project("Business acquisition", "buy an accounting practice with an SBA loan")
    r = client.post("/api/community/proposals", json={"project_id": p["id"], "platform": "reddit", "community": "r/smallbusiness", "url": SUB, "items": _items(), "max_videos": 3}, headers=H)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "subreddit" and out["title"] == "r/smallbusiness" and out["found"] == 6 and out["proposed"] == 6 and out["review"]
    cards = db.pending_reviews(p["id"])
    assert len(cards) == 1 and cards[0]["kind"] == "subreddit" and len(cards[0]["proposed"]) == 6
    src = cards[0]["proposed"][0]
    assert src["platform"] == "community" and src["external_id"].startswith("reddit:p") and src["channel"] == "r/smallbusiness" and src["status"] == "proposed"
    assert src["description"].startswith("Body "), "the ranker sees title + body"
    meta = db.review_meta(cards[0]["id"])
    assert meta["max_videos"] == 3 and meta["project_id"] == p["id"] and meta["ranked"] is False
    # the ranker was queued, like a channel
    rank = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    assert rank and rank["payload"]["collection_id"] == cards[0]["id"] and rank["payload"]["want"] == 3
    assert jobs.execute(rank, worker_id="w") == "done"
    assert all(s.get("relevance") is not None for s in db.pending_reviews(p["id"])[0]["proposed"])
    # a second walk of the same subreddit is the same card, and already-owned threads keep their status
    r2 = client.post("/api/community/proposals", json={"project_id": p["id"], "platform": "reddit", "community": "r/smallbusiness", "url": SUB, "items": _items(2)}, headers=H).json()
    assert r2["collection_id"] == out["collection_id"] and len(db.pending_reviews(p["id"])) == 1
    assert client.post("/api/community/proposals", json={"project_id": "nope", "platform": "reddit", "community": "r/x", "url": SUB, "items": []}, headers=H).status_code == 404
    assert client.post("/api/community/proposals", json={"project_id": p["id"], "platform": "skool", "community": "x", "url": SUB, "items": []}, headers=H).status_code == 400


def test_start_ingests_a_chosen_thread_through_the_browser_and_lands_on_the_same_row(client):
    p = db.create_project("Business acquisition", "buy an accounting practice")
    out = client.post("/api/community/proposals", json={"project_id": p["id"], "platform": "reddit", "community": "r/smallbusiness", "url": SUB, "items": _items(3)}, headers=H).json()
    rows = db.pending_reviews(p["id"])[0]["proposed"]
    chosen = rows[0]
    res = ingest.approve_proposed(out["collection_id"], [chosen["id"]])
    assert res["started"] == 1 and res["dropped"] == 2
    assert db.get_source(chosen["id"])["status"] == "pending"
    job = db.claim_job(kinds=("ingest_url",), worker_id="sim")
    assert job and job["payload"]["url"] == chosen["url"] and job["payload"]["project_id"] == p["id"]
    assert jobs.execute(job, "sim") == "external_pending", "Reddit blocks the server → the browser is asked"
    row = db.get_job(job["id"])
    assert row["external_provider"] == "browser" and row["payload"]["source_id"] == chosen["id"], "identity: the capture request is for the SAME proposed row, never a second source"
    q = acquire.pending_captures(project_id=p["id"])
    assert len(q) == 1 and q[0]["adapter"] == "reddit_thread" and q[0]["job_id"] == job["id"]
    src = db.get_source(chosen["id"])
    assert src["status"] == "pending" and src["error_class"] == "browser_solvable:blocked"


def test_the_extension_has_a_dedicated_scan_this_subreddit_button():
    import pathlib
    ext = pathlib.Path(__file__).resolve().parents[1] / "extension"
    html = (ext / "popup.html").read_text(); pop = (ext / "popup.js").read_text(); bg = (ext / "background.js").read_text(); ad = (ext / "community-adapters.js").read_text()
    assert 'id="subredditScan"' in html and ">Scan this subreddit</button>" in html, "Kyle: make a dedicated button so I know about it"
    assert "key: 'reddit'" in ad and "/new.json?" in ad and "mode: 'propose'" in ad
    assert "api('/api/community/proposals'" in bg
    assert "async function fulfilRedditCaptures" in bg and "url: 'https://www.reddit.com/*'" in bg, "pending Reddit captures are fulfilled from any open Reddit tab, no tab per post"
    assert "type: 'cscan-start', tabId: TAB.id, projectId: pid, maxAgeDays" in pop


def test_a_review_card_scanned_into_the_wrong_project_can_be_moved(client):
    """S96 — Kyle: "I think I just scanned them to the wrong project..." The card moves; the new project re-ranks."""
    wrong = db.create_project("Business acquisition", "buy a business"); right = db.create_project("Personal wealth", "index funds")
    out = client.post("/api/community/proposals", json={"project_id": wrong["id"], "platform": "reddit", "community": "r/Bogleheads", "url": SUB, "items": _items(4)}, headers=H).json()
    r = client.post(f"/api/collections/{out['collection_id']}/move", json={"project_id": right["id"]}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == 4 and r.json()["from"] == wrong["id"]
    assert [c["id"] for c in db.pending_reviews(right["id"])] == [out["collection_id"]]
    assert db.pending_reviews(wrong["id"]) == []
    assert db.review_meta(out["collection_id"])["project_id"] == right["id"]
    ranks = [j for j in (db.claim_job(kinds=("rank_proposed",), worker_id="w"),) if j]
    assert ranks and ranks[0]["payload"]["project_id"] in (wrong["id"], right["id"])
    assert client.post(f"/api/collections/{out['collection_id']}/move", json={"project_id": "nope"}, headers=H).status_code == 404
