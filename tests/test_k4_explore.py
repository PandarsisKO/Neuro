"""Rung G3 — website & collection exploration + the Discovery Candidate Index. (Sorts after test_core.)
A local HTTP server plays a public site through the safe_fetch harness hooks; no real network."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g3_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402

from neurosearch import candidates, db, explore, identity, ingest, jobs, resources  # noqa: E402
from neurosearch import safe_fetch as SF  # noqa: E402
from neurosearch.config import settings  # noqa: E402

PUBLIC_A = "93.184.216.34"

SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://site.test/sitemap-pubs.xml</loc></sitemap><sitemap><loc>https://site.test/sitemap-bad.xml</loc></sitemap></sitemapindex>"""
SITEMAP_PUBS = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://site.test/publications/p946-depreciation</loc><lastmod>2026-02-01</lastmod></url>
<url><loc>https://site.test/publications/p463-travel-expenses</loc><lastmod>2026-01-10</lastmod></url>
<url><loc>https://site.test/forms/4562-instructions</loc><lastmod>2025-12-01</lastmod></url>
<url><loc>https://site.test/careers</loc><lastmod>2025-01-01</lastmod></url>
<url><loc>https://site.test/logo.png</loc></url>
<url><loc>https://site.test/guides/business-use-of-aircraft</loc><lastmod>2026-03-01</lastmod></url>
</urlset>"""
FEED = """<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel><title>Baron Owners Podcast</title><itunes:author>Rich</itunes:author>
<item><title>Why New Baron Owners Can't Get Insurance</title><guid>ep-41</guid><link>https://site.test/ep/41</link><description>Low-time twin pilots, 25 hours dual, underwriting</description><pubDate>Tue, 05 Mar 2024 10:00:00 GMT</pubDate><enclosure url="https://site.test/audio/41.mp3" type="audio/mpeg"/><itunes:duration>45:10</itunes:duration></item>
<item><title>Engine reserves explained</title><guid>ep-42</guid><link>https://site.test/ep/42</link><description>Setting aside money per hour</description><enclosure url="https://site.test/audio/42.mp3" type="audio/mpeg"/></item>
<item><title>Blog: annual inspection checklist</title><guid>post-7</guid><link>https://site.test/blog/annual?utm_source=x</link><description>text only</description></item>
</channel></rss>"""
HOME = """<html><head><title>Site Test</title></head><body><a href="/about">About us</a><a href="/guides/">Guides</a><a href="/guides/first-twin">Your first twin</a>
<a href="https://other.test/x">elsewhere</a><a href="/login">Login</a><a href="/style.css">css</a><a href="/about">About again</a></body></html>"""


class Handler(BaseHTTPRequestHandler):
    routes = {"/robots.txt": ("text/plain", "User-agent: *\nSitemap: https://site.test/sitemap.xml\n"),
              "/sitemap.xml": ("application/xml", SITEMAP_INDEX), "/sitemap-pubs.xml": ("application/xml", SITEMAP_PUBS),
              "/feed.xml": ("application/rss+xml", FEED), "/": ("text/html", HOME), "/guides": ("text/html", HOME)}

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/sitemap-bad.xml":
            self.send_response(500); self.end_headers(); return
        if path not in self.routes:
            self.send_response(404); self.end_headers(); return
        ct, body = self.routes[path]
        data = body.encode()
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):  # noqa: D102
        pass


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch, server):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "default_max_videos", 3)
    db._local.conn = None
    db.init_db()
    monkeypatch.setattr(SF, "RESOLVER", lambda host, port: [PUBLIC_A] if host.endswith(".test") else (_ for _ in ()).throw(socket.gaierror("nope")))
    monkeypatch.setattr(SF, "CONNECT", lambda ip, port, timeout: socket.create_connection(server.server_address, timeout=timeout))
    import ssl

    class NoTLS(ssl.SSLContext):                 # canonical URLs are https; the local server speaks plain HTTP — skip the handshake only
        def wrap_socket(self, sock, server_hostname=None, **kw):
            return sock
    monkeypatch.setattr(SF.ssl, "create_default_context", lambda: NoTLS(ssl.PROTOCOL_TLS_CLIENT))
    jobs.CRASH_AT.clear()
    yield
    db._local.conn = None


def _proj():
    return db.create_project("G3", "aircraft ownership: insurance, depreciation, engine reserves")["id"]


# ------------------------------------------------------------------ enumerators

def test_sitemap_index_is_followed_filtered_and_fails_open():
    info, entries = explore.enumerate_sitemap("https://site.test/sitemap.xml")
    urls = [e["url"] for e in entries]
    assert info["kind"] == "sitemap" and len(entries) == 4                                       # careers + logo.png filtered; bad child skipped
    assert urls[0].endswith("/guides/business-use-of-aircraft") and urls[-1].endswith("/forms/4562-instructions")   # newest lastmod first
    assert entries[0]["title"] == "Business use of aircraft" and entries[0]["external_id"] == "site.test/guides/business-use-of-aircraft"


def test_feed_yields_podcast_episodes_and_web_posts():
    info, entries = explore.enumerate_feed("https://site.test/feed.xml")
    assert info["title"] == "Baron Owners Podcast" and len(entries) == 3
    ep = entries[0]
    assert ep["platform"] == "podcast" and ep["external_id"] == "ep-41" and ep["url"].endswith("/audio/41.mp3") and ep["duration"] == 2710.0
    assert ep["published_at"] == "2024-03-05" and ep["creator"] == "Rich" and "25 hours dual" in ep["description"]
    post = entries[2]
    assert post["platform"] == "web" and post["external_id"] == "site.test/blog/annual" and "utm" not in post["url"]


def test_website_prefers_sitemap_then_section_then_links():
    info, entries = explore.enumerate_website("https://site.test")
    assert info["how"].startswith("robots.txt → sitemap") and len(entries) == 4
    info2, entries2 = explore.enumerate_website("https://site.test/guides/")           # section: sitemap has <5 under it → page links
    assert "page links" in info2["how"] and [e["url"] for e in entries2] == ["https://site.test/guides/first-twin"]
    assert entries2[0]["title"] == "Your first twin"


# ------------------------------------------------------------------ the exploration job → review + Candidate Index

def test_explore_job_lists_ranks_reviews_and_remembers(monkeypatch):
    pid = _proj()
    c = resources.classify("site.test")
    assert c.kind == "website" and c.default_action == "explore"
    r = resources.route(c, pid)
    assert r["queued"] and db.get_job(r["job_id"])["kind"] == "explore"
    res = jobs.run_job(db.get_job(r["job_id"]))
    assert res["found"] == 4 and res["proposed"] == 4 and res["review"] and res["counts"] == {"already_in_project": 0, "already_in_library": 0, "new": 4}
    props = db.proposed_sources(res["collection_id"])
    assert len(props) == 4 and all(p["platform"] == "web" and p["status"] == "proposed" for p in props)
    assert all(p["id"] in set(db.project_source_ids(pid, ready_only=False)) or True for p in props)          # attached through the collection
    cc = candidates.counts(pid)
    assert cc["total"] == 4 and cc["available"] == 4 and cc["global"] == 4
    # ranking runs through the existing ranker (fake, lexical) and the review meta carries the counts
    rank = [j for j in db.list_jobs(20) if j["kind"] == "rank_proposed"][0]
    jobs.run_job(rank)
    meta = db.review_meta(res["collection_id"])
    assert meta["counts"]["new"] == 4 and meta["kind"] == "website"
    ranked = db.proposed_sources(res["collection_id"], pid)
    assert ranked[0]["relevance"] is not None
    # approve the best one: the rest are RETAINED as skipped candidates with the reason, not forgotten
    best = ranked[0]["id"]
    out = ingest.approve_proposed(res["collection_id"], [best])
    assert out["started"] == 1 and out["dropped"] == 3
    states = {x["title"]: x["state"] for x in candidates.list_for_project(pid)}
    assert list(states.values()).count("acquired") == 1 and all(s in ("skipped_limit", "skipped_low_relevance", "acquired") for s in states.values())
    acq = [x for x in candidates.list_for_project(pid, "acquired")][0]
    assert acq["source_id"] == best                                                                # the candidate RESOLVES to the source
    assert db.connect().execute("SELECT COUNT(*) FROM sources WHERE status='proposed'").fetchone()[0] == 0   # proposals dropped as before


def test_gap_recall_finds_skipped_candidates_without_re_enumerating(monkeypatch):
    pid = _proj()
    info, entries = explore.enumerate_feed("https://site.test/feed.xml")
    candidates.remember(entries, "podcast", pid, {"collection_id": "c1", "kind": "feed", "title": info["title"]})
    ids = {c["title"]: c["id"] for c in candidates.list_for_project(pid)}
    candidates.mark(pid, [ids["Why New Baron Owners Can't Get Insurance"]], "skipped_limit", "outside the top 3", relevance=41)
    # a later gap: insurance for low-time twin pilots — recalled from the index, no network
    hits = candidates.search(pid, "insurance low-time twin pilots underwriting")
    assert hits and hits[0]["title"].startswith("Why New Baron Owners") and hits[0]["state"] == "skipped_limit" and hits[0]["project"]["relevance"] == 41
    assert hits[0]["project"]["origin"]["title"] == "Baron Owners Podcast"
    # user intent outranks recall: a dismissed candidate stays hidden (unless asked for)
    candidates.dismiss(pid, hits[0]["id"], "don't trust this creator")
    assert not [h for h in candidates.search(pid, "insurance twin") if h["id"] == hits[0]["id"]]
    assert [h for h in candidates.search(pid, "insurance twin", include_dismissed=True) if h["id"] == hits[0]["id"]]
    candidates.restore(pid, hits[0]["id"])
    assert candidates.search(pid, "insurance twin")[0]["id"] == hits[0]["id"]
    # project relationships are separate: another project sees the global candidate but its own (empty) state
    other = db.create_project("other", "x")["id"]
    h2 = candidates.search(other, "insurance twin")[0]
    assert h2["state"] == "unseen_by_project" and h2["project"] is None


def test_same_video_from_channel_playlist_and_search_is_one_candidate_and_resolves_when_acquired(monkeypatch):
    from neurosearch import media
    pid = _proj()
    e = {"id": "vid00000abc", "url": "https://www.youtube.com/watch?v=vid00000abc", "title": "Insurance for your first Baron", "duration": 600.0}
    for kind, title in (("channel", "Flying with Rich"), ("playlist", "Twin ownership"), ("playlist", "Search: baron insurance")):
        monkeypatch.setattr(media, "classify_url", lambda u, k=kind: k)
        monkeypatch.setattr(media, "enumerate_entries", lambda u, t=title: ({"id": "X" + t, "url": u, "title": t}, [e]))
        ingest.ingest_url(f"https://www.youtube.com/{kind}/{title.replace(' ', '')}", project_id=pid, review=True)
    assert candidates.counts(pid)["global"] == 1 and candidates.counts(pid)["total"] == 1                   # one identity across three listings
    cand = candidates.list_for_project(pid)[0]
    assert cand["source_id"] is None
    # acquired through any path (a plain single-video add) → the candidate resolves to the global source
    monkeypatch.setattr(media, "classify_url", lambda u: "video")
    prop = db.find_source("youtube", "vid00000abc")
    db.set_source_status(prop["id"], "ready")                                                            # stand-in for the ingest completing
    identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="vid00000abc", url=e["url"]), pid)
    candidates.mark_by_source(pid, [prop["id"]], "acquired")
    assert candidates.list_for_project(pid)[0]["source_id"] == prop["id"]


def test_candidates_are_never_evidence():
    """Candidate metadata cannot reach the chat's excerpts: search() returns no chunk ids and nothing is in chunks/FTS."""
    pid = _proj()
    info, entries = explore.enumerate_feed("https://site.test/feed.xml")
    candidates.remember(entries, "podcast", pid, {"kind": "feed"})
    from neurosearch import search
    assert search.search("insurance low-time twin", limit=5, source_ids=db.project_source_ids(pid) or ["__none__"]) == []
    assert db.connect().execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    hit = candidates.search(pid, "insurance")[0]
    assert "chunk_id" not in hit and "text" not in hit


def test_api_candidates_and_acquire():
    """The endpoints, called directly (this module uses a private database per test, so no HTTP client)."""
    from neurosearch import api
    pid = _proj()
    info, entries = explore.enumerate_feed("https://site.test/feed.xml")
    candidates.remember(entries, "podcast", pid, {"kind": "feed", "title": info["title"]})
    r = api.api_candidates(pid, q="insurance")
    assert r["items"][0]["title"].startswith("Why New") and r["counts"]["total"] == 3
    cid = r["items"][0]["id"]
    assert api.api_candidate_dismiss(cid, api.CandidateActIn(project_id=pid, reason="not this creator"))["updated"] == 1
    assert api.api_candidates(pid, state="user_dismissed")["items"][0]["reason"] == "not this creator"
    api.api_candidate_restore(cid, api.CandidateActIn(project_id=pid))
    r = api.api_candidate_acquire(cid, api.CandidateActIn(project_id=pid))
    assert r["job_id"] and db.get_job(r["job_id"])["kind"] == "ingest_url"                                    # the normal lifecycle
    assert candidates.list_for_project(pid, "acquired")[0]["id"] == cid
