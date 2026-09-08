"""0.32.2 — Reddit's server-rendered page (old.reddit.com) as the second reading of a public thread, offline ($0).

Reddit refuses its JSON listing to non-browser clients even for public threads. The gate here: the HTML reading yields the
SAME thread (ids, parents, depth, authors, text, deleted/edited state, permalinks) as the JSON reading, the search page
yields the same candidate rows, and the fallback engages only when the JSON is refused. (Sorts after test_k9.)"""
from __future__ import annotations

import os
import tempfile
from html import escape

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g7b_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import community, db, fake_ai, jobs, reddit_html, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k9_community import THREAD_URL, _thread_json  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


# ---------------------------------------------------------------- an old.reddit page rendered from the frozen JSON fixture

def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def _md(text):
    return "".join(f"<p>{escape(p)}</p>" for p in text.split("\n\n")) if text else ""


def _comment_html(node):
    d = node["data"]
    deleted = d["author"] == "[deleted]"
    body = "[deleted]" if deleted else d["body"]
    cls = " thing id-t1_%s noncollapsed comment %s" % (d["id"], "deleted" if deleted else "")
    kids = "".join(_comment_html(c) for c in d.get("replies", {}).get("data", {}).get("children", [])) if isinstance(d.get("replies"), dict) else ""
    edited = f'<time class="edited-timestamp" datetime="{_iso(d["created_utc"] + 60)}">*</time>' if d.get("edited") else ""
    return (f'<div class="{cls}" id="thing_t1_{d["id"]}" data-fullname="t1_{d["id"]}" data-subreddit="smallbusiness" data-author="{d["author"]}" data-permalink="{d["permalink"]}">'
            f'<p class="parent"><a name="{d["id"]}"></a></p><div class="midcol unvoted"><div class="arrow up"></div></div>'
            f'<div class="entry unvoted"><p class="tagline"><a class="author may-blank" href="https://old.reddit.com/user/{d["author"]}">{d["author"]}</a>'
            f'<span class="score dislikes" title="{d["score"] - 1}">{d["score"] - 1} points</span><span class="score unvoted" title="{d["score"]}">{d["score"]} points</span>'
            f'<span class="score likes" title="{d["score"] + 1}">{d["score"] + 1} points</span><time datetime="{_iso(d["created_utc"])}" title="x">3 hours ago</time>{edited}</p>'
            f'<form class="usertext warn-on-unload"><input type="hidden"><div class="usertext-body may-blank-within md-container"><div class="md">{_md(body)}</div></div></form>'
            f'<ul class="flat-list buttons"><li><a href="{d["permalink"]}">permalink</a></li></ul></div>'
            f'<div class="child"><div class="sitetable listing">{kids}</div></div><div class="clearleft"></div></div>')


def _thread_html(thread=None):
    listing, comments = thread or _thread_json()
    link = listing["data"]["children"][0]["data"]
    return (f'<!DOCTYPE html><html><head><title>{escape(link["title"])} : smallbusiness</title><script>var x = "<div class=thing>";</script></head><body class="comments-page">'
            f'<div id="siteTable" class="sitetable linklisting"><div class="thing id-t3_{link["id"]} odd link self" id="thing_t3_{link["id"]}" data-fullname="t3_{link["id"]}" '
            f'data-subreddit="{link["subreddit"]}" data-author="{link["author"]}" data-permalink="{link["permalink"]}">'
            f'<div class="midcol unvoted"><div class="arrow up"></div><div class="score dislikes">87</div><div class="score unvoted" title="{link["score"]}">{link["score"]}</div><div class="score likes">89</div></div>'
            f'<div class="entry unvoted"><div class="top-matter"><p class="title"><a class="title may-blank" href="{link["permalink"]}">{escape(link["title"])}</a><span class="domain">(self.smallbusiness)</span></p>'
            f'<p class="tagline"><time datetime="{_iso(link["created_utc"])}">a day ago</time> by <a class="author may-blank">{link["author"]}</a></p></div>'
            f'<div class="expando"><form class="usertext"><div class="usertext-body may-blank-within md-container"><div class="md">{_md(link["selftext"])}</div></div></form></div></div></div></div>'
            f'<div class="commentarea"><div class="panestack-title"><span class="title">all {link["num_comments"]} comments</span></div>'
            f'<div class="sitetable nestedlisting">{"".join(_comment_html(c) for c in comments["data"]["children"])}</div></div>'
            f'<div class="footer-parent"><p>unclosed paragraph <b>bold</div></body></html>')


def _search_html(rows):
    items = "".join(
        f'<div class="search-result search-result-link has-linkflair" data-fullname="t3_{r["id"]}"><a class="may-blank thumbnail self"></a><div>'
        f'<header class="search-result-header"><a class="search-title may-blank" href="https://old.reddit.com{r["permalink"]}">{escape(r["title"])}</a></header>'
        f'<div class="search-result-meta"><span class="search-score">{r["score"]} points</span><a class="search-comments may-blank" href="https://old.reddit.com{r["permalink"]}">{r["num_comments"]} comments</a>'
        f'<span class="search-time"><time datetime="{_iso(r["created_utc"])}">a year ago</time></span><span class="search-author"><a class="author may-blank">{r["author"]}</a></span>'
        f'<span><a class="search-subreddit-link may-blank">r/smallbusiness</a></span></div>'
        f'<div class="search-expando collapsed"><div class="search-result-body"><div class="md">{_md(r["selftext"])}</div></div></div></div></div>' for r in rows)
    return f'<html><head><title>smallbusiness: search results</title></head><body><div class="search-result-listing"><div class="search-result-group">{items}</div></div></body></html>'


SEARCH_ROWS = [
    {"id": "s1", "title": "Bought a practice — year one surprises", "selftext": "I bought a practice and the software migration cost me.", "author": "own1", "score": 53, "num_comments": 150, "created_utc": 1716300000,
     "permalink": "/r/smallbusiness/comments/s1/bought_a_practice/"},
    {"id": "s2", "title": "Seeking business owners' advice", "selftext": "", "author": "own2", "score": 2, "num_comments": 14, "created_utc": 1780000000, "permalink": "/r/smallbusiness/comments/s2/seeking/"},
]


# ---------------------------------------------------------------- the gate

def _shape(p):
    return {k: p[k] for k in ("post_id", "parent_id", "depth", "author", "deleted", "kind", "permalink")} | {"text": p["text"].strip(), "edited": bool(p["edited"])}


def test_html_reading_matches_the_json_reading(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    via_json = community.read_reddit_thread(THREAD_URL)
    via_html = reddit_html.thread_from_html(_thread_html(), THREAD_URL)
    assert via_html["thread_id"] == via_json["thread_id"] == "abc123"
    assert via_html["title"] == via_json["title"] and via_html["community"] == "r/smallbusiness"
    assert via_html["url"] == via_json["url"] and via_html["score"] == 88 and via_html["num_comments"] == 11
    assert [_shape(p) for p in via_html["posts"]] == [_shape(p) for p in via_json["posts"]]
    assert [p["score"] for p in via_html["posts"]] == [p["score"] for p in via_json["posts"]]
    assert all(abs(a["created"] - b["created"]) < 1 for a, b in zip(via_html["posts"], via_json["posts"]))
    assert via_html["representation"] == "old.reddit.com html"
    # tree: the correction is a reply to the wrong quote; the acknowledgement a reply to the correction
    by = {p["post_id"]: p for p in via_html["posts"]}
    assert by["c2"]["parent_id"] == "c1" and by["c3"]["parent_id"] == "c2" and by["c3"]["depth"] == 3 and by["c4"]["parent_id"] == "abc123"


def test_html_reading_keeps_deleted_and_edited_state():
    listing, comments = _thread_json()
    comments["data"]["children"][0]["data"]["replies"]["data"]["children"][0]["data"]["edited"] = True
    comments["data"]["children"][-1]["data"].update({"author": "[deleted]", "body": "[deleted]"})
    t = reddit_html.thread_from_html(_thread_html((listing, comments)), THREAD_URL)
    by = {p["post_id"]: p for p in t["posts"]}
    assert by["c2"]["edited"] is True and by["c1"]["edited"] is False
    assert by["c11"]["deleted"] is True and by["c11"]["text"] == ""


def test_fallback_engages_only_when_the_json_is_refused(monkeypatch):
    calls = []
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing — www.reddit.com: HTTP 403")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url: calls.append(url) or _thread_html())
    t = community.read_reddit_thread(THREAD_URL)
    assert len(t["posts"]) == 12 and calls and calls[0].startswith("https://www.reddit.com/r/smallbusiness/comments/abc123/")
    # and when the JSON answers, the page is never requested
    calls.clear()
    monkeypatch.setattr(community, "_json_get", lambda url: _thread_json())
    community.read_reddit_thread(THREAD_URL)
    assert calls == []
    # both refused → one message that names both readings
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing — www.reddit.com: HTTP 403")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url: (_ for _ in ()).throw(RuntimeError("old.reddit.com: HTTP 429")))
    with pytest.raises(RuntimeError, match="HTTP 403.*server-rendered page: old.reddit.com: HTTP 429"):
        community.read_reddit_thread(THREAD_URL)
    # a page that is not a thread (a block page, a login wall) is reported as such, not parsed into an empty thread
    monkeypatch.setattr(community, "_old_reddit_html", lambda url: "<html><head><title>Blocked</title></head><body>whoa there</body></html>")
    with pytest.raises(RuntimeError, match="not a thread \\(Blocked\\)"):
        community.read_reddit_thread(THREAD_URL)


def test_search_page_yields_the_same_candidate_rows(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url: _search_html(SEARCH_ROWS) if "/search?q=" in url else "")
    rows = community.enumerate_reddit("r/smallbusiness", "bought an accounting practice", limit=10)
    assert [r["external_id"] for r in rows] == ["reddit:s1", "reddit:s2"]
    r = rows[0]
    assert r["url"] == "https://www.reddit.com/r/smallbusiness/comments/s1/bought_a_practice/" and r["title"].startswith("Bought a practice")
    assert r["score"] == 53 and r["num_comments"] == 150 and r["published_at"] == "2024-05-21" and r["creator"] == "own1" and "software migration" in r["description"]
    assert r["community"] == "r/smallbusiness" and r["content_type"] == "post"


def test_thread_acquired_through_the_page_is_a_full_community_source(monkeypatch):
    monkeypatch.setattr(community, "_json_get", lambda url: (_ for _ in ()).throw(RuntimeError("Reddit refused the listing")))
    monkeypatch.setattr(community, "_old_reddit_html", lambda url: _thread_html())
    pid = db.create_project("G7b", "Buying a small accounting practice with an SBA loan")["id"]
    r = community.acquire_thread(THREAD_URL, project_id=pid)
    assert r["posts"] == 12 and r["substantive"] >= 8
    conn = db.connect()
    posts = conn.execute("SELECT post_id, parent_id, corrected_by FROM community_posts WHERE source_id=? ORDER BY rowid", (r["source_id"],)).fetchall()
    assert len(posts) == 12
    corrected = {p["post_id"]: p["corrected_by"] for p in posts if p["corrected_by"]}
    assert corrected.get("c1") == "c2", "the wrong SOP quote is marked corrected by its reply, from the HTML tree too"
    src = db.get_source(r["source_id"])
    assert src["platform"] == "community" and src["external_id"] == "reddit:abc123"
