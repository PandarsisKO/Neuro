"""Rung G2 — universal resource input: arbitrary input is classified and routed into the standard lifecycle; a root
website / repository / community / Work identity never falls through to naive page ingestion. (Sorts after test_core.)"""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, qa, resources  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True, scope="module")
def _shared_db():
    mp = pytest.MonkeyPatch()
    (settings.data_dir / "media").mkdir(parents=True, exist_ok=True)
    mp.setattr(settings, "fake_ai", True)
    mp.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    mp.undo()
    db._local.conn = None


CASES = {
    "irs.gov": ("website", "explore"),
    "https://www.irs.gov": ("website", "explore"),
    "https://www.irs.gov/forms-instructions/": ("website_section", "explore"),
    "https://www.irs.gov/publications/p946": ("page", "page"),
    "https://example.com/report.pdf": ("document", "ingest"),
    "https://example.com/budget.xlsx": ("spreadsheet", "upload"),
    "https://example.com/chart.png": ("image", None),
    "https://youtu.be/dQw4w9WgXcQ": ("video", "ingest"),
    "https://www.youtube.com/@BenKelly": ("channel", "explore"),
    "https://www.youtube.com/playlist?list=PL123": ("playlist", "explore"),
    "https://www.youtube.com/results?search_query=baron+insurance": ("search_query", "explore"),
    "https://feeds.megaphone.fm/xyz/rss": ("feed", "explore"),
    "https://example.com/sitemap.xml": ("sitemap", "explore"),
    "https://github.com/anthropics/claude-code": ("repository", "page"),
    "https://github.com/anthropics/claude-code/blob/main/README.md": ("page", "page"),
    "https://www.reddit.com/r/smallbusiness/": ("subreddit", "explore"),
    "https://www.reddit.com/r/smallbusiness/comments/abc/how_i_bought/": ("page", "page"),
    "https://www.instagram.com/benkellyone/": ("instagram_profile", None),
    "https://www.instagram.com/reel/Cxyz123/": ("instagram_post", "ingest"),
    "978-0-13-468599-1": ("work_identity", "resolve"),        # G6: identifiers go to the Source Resolver first
    "ISBN 0-306-40615-2": ("work_identity", "resolve"),
    "10.1038/nature12373": ("work_identity", "resolve"),
    "https://doi.org/10.1038/nature12373": ("work_identity", "resolve"),
    "how do low-time pilots get baron insurance": ("search_query", "discover"),
    "https://www.loom.com/share/abc": ("media", "ingest"),
}


@pytest.mark.parametrize("text,expected", list(CASES.items()))
def test_classification_matrix(text, expected):
    c = resources.classify(text)
    assert (c.kind, c.default_action) == expected, c.as_dict()
    assert c.kind in resources.KINDS and c.label
    if c.default_action:
        assert any(a["action"] == c.default_action and a["available"] for a in c.actions)


def test_bad_isbn_is_not_a_book_and_multiline_splits():
    assert resources.classify("978-0-13-468599-2").kind == "search_query"          # checksum fails → plain text
    items = resources.classify_many("irs.gov\nhttps://youtu.be/dQw4w9WgXcQ, https://example.com/a.pdf")
    assert [i.kind for i in items] == ["website", "video", "document"]
    assert [i.kind for i in resources.classify_many("what are the sba equity injection rules\nand seller note standby")] == ["search_query"]


def test_containers_are_never_fetched_as_pages_unless_chosen():
    pid = db.create_project("G2", "brief")["id"]
    mine = lambda: [j for j in db.list_jobs(200) if j["kind"] == "ingest_url" and j["payload"].get("project_id") == pid]  # noqa: E731
    site = resources.classify("irs.gov")
    repo = resources.classify("https://github.com/anthropics/claude-code")
    r = resources.route(repo, pid, "explore")
    assert not r["queued"] and r["unavailable"] and "G3" in r["note"]                                       # repository exploration: declared, not faked
    assert not mine()                                                                                       # nothing queued
    r0 = resources.route(site, pid)                                                                         # default for a website = explore (G3), never a page fetch
    assert r0["queued"] and r0["review"] and db.get_job(r0["job_id"])["kind"] == "explore" and not mine()
    r2 = resources.route(site, pid, "page")                                                                 # explicit choice
    assert r2["queued"] and r2["url"].rstrip("/") == "https://irs.gov"
    assert db.get_job(r2["job_id"])["payload"]["review"] is False
    comm = resources.classify("https://www.reddit.com/r/smallbusiness/")
    catalog = resources.route(comm, pid)
    assert catalog["queued"] is True and catalog["catalog"] is True
    assert db.get_collection(catalog["collection_id"])["kind"] == "subreddit"
    assert db.get_job(catalog["job_id"])["kind"] == "explore"
    assert not db.connect().execute("SELECT 1 FROM sources WHERE platform='community'").fetchone()
    with pytest.raises(ValueError):
        resources.route(comm, pid, "ingest")                                                                 # not an action for a community
    ch = resources.route(resources.classify("https://www.youtube.com/@BenKelly"), pid, since_years=1, max_videos=5)
    assert ch["queued"] and ch["review"] and db.get_job(ch["job_id"])["payload"]["max_videos"] == 5
    q = resources.route(resources.classify("what does the sba require for seller notes"), pid)
    assert q["queued"] and db.get_job(q["job_id"])["kind"] == "discover" and db.get_job(q["job_id"])["payload"]["refine"].startswith("what does")
    isbn = resources.route(resources.classify("978-0-13-468599-1"), pid)
    assert not isbn["queued"] and "upload" in isbn["note"].lower() and isbn["resolver"]["identity"] == "resolved"


def test_api_classify_and_add(client):
    pid = db.create_project("G2 api", "brief")["id"]
    r = client.post("/api/classify", json={"input": "irs.gov\nhttps://youtu.be/dQw4w9WgXcQ"}, headers=H)
    assert r.status_code == 200 and [i["kind"] for i in r.json()["items"]] == ["website", "video"]
    assert r.json()["items"][0]["is_container"] and not r.json()["items"][1]["is_container"]
    r = client.post(f"/api/projects/{pid}/add", json={"input": "irs.gov", "action": "page"}, headers=H)   # explicit page-only choice
    assert r.status_code == 200 and r.json()["items"][0]["result"]["action"] == "page" and r.json()["jobs"]
    r = client.post(f"/api/projects/{pid}/add", json={"input": "irs.gov"}, headers=H)                    # default = explore (G3)
    assert r.json()["items"][0]["result"]["action"] == "explore" and db.get_job(r.json()["jobs"][0])["kind"] == "explore"
    r = client.post(f"/api/projects/{pid}/add", json={"input": "https://www.reddit.com/r/smallbusiness/"}, headers=H)
    assert r.json()["items"][0]["result"]["catalog"] is True and r.json()["jobs"]
    r = client.post(f"/api/projects/{pid}/add", json={"input": "https://github.com/anthropics/claude-code", "action": "explore"}, headers=H)
    assert r.json()["items"][0]["result"]["unavailable"] is True


def test_chat_pasted_container_is_detected_not_ingested():
    pid = db.create_project("G2 chat", "brief")["id"]
    before = len(db.list_jobs(200))
    res = qa.ask("https://www.reddit.com/r/smallbusiness/", project_id=pid, conversation_id=db.new_id())
    queued = db.list_jobs(200)
    assert len(queued) == before + 1 and queued[0]["kind"] == "explore" and queued[0]["payload"]["kind"] == "subreddit"
    assert res["ingest_jobs"][0]["kind"] == "subreddit"
    assert res["ingest_jobs"][0]["job_id"]
    assert "Queued 1 link" in res["answer"]
    res2 = qa.ask("https://youtu.be/dQw4w9WgXcQ", project_id=pid, conversation_id=db.new_id())
    assert res2["ingest_jobs"][0]["job_id"] and "Queued 1 link" in res2["answer"]
    res3 = qa.ask("https://www.youtube.com/@BenKelly", project_id=pid, conversation_id=db.new_id())
    assert res3["ingest_jobs"][0]["review"] and "approval" in res3["answer"]


@pytest.mark.parametrize("url", [
    "https://medium.muz.li/why-every-ai-built-app-looks-the-same-and-how-to-escape-ai-slop-919bf2dc6fc0",
    "https://example.com/a-single-article",
    "https://example.com/a-single-article/",
    "https://example.com/about",
])
def test_shallow_pages_queue_ingestion_not_exploration(client, url):
    detected = client.post("/api/classify", json={"input": url}, headers=H).json()["items"][0]
    assert detected["kind"] == "page" and detected["default_action"] == "page"
    pid = db.create_project("Article routing", "brief")["id"]
    result = client.post(f"/api/projects/{pid}/add", json={"input": url}, headers=H)
    assert result.status_code == 200
    job = db.get_job(result.json()["jobs"][0])
    assert job["kind"] == "ingest_url"
    assert job["payload"]["url"].rstrip("/") == url.rstrip("/")
    assert job["payload"]["review"] is False


@pytest.mark.parametrize("path", ["blog", "news/", "articles", "resources/", "forms-instructions/"])
def test_known_sections_still_offer_exploration(path):
    c = resources.classify("https://example.com/" + path)
    assert c.kind == "website_section" and c.default_action == "explore"
    assert any(a["action"] == "page" for a in c.actions)
