"""Reddit's server-rendered pages (old.reddit.com) as a second reading of a public thread (0.32.2).

Reddit's public JSON listing is the preferred representation (`community.read_reddit_thread`), but Reddit's edge refuses
JSON to clients it takes for scrapers even when the same thread is public in any browser. old.reddit.com still renders
the whole thread server-side — a plain browser navigation gets the complete comment tree as HTML — so this module reads
that HTML into the SAME thread shape the JSON adapter produces: post ids, parents, authors, scores, timestamps, edited
and deleted state, permalinks. Nothing here needs JavaScript or a login. The parser is a small tolerant tree over the
standard library's HTMLParser; no third-party HTML dependency.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Callable, Iterator
from urllib.parse import urljoin

from .htmltree import BLOCKS, Node, parse  # noqa: E402,F401  (the tolerant tree moved to htmltree.py in 0.34.0)


def looks_like_thread(html: str) -> bool:
    return 'data-fullname="t3_' in html and "commentarea" in html


def looks_like_search(html: str) -> bool:
    return "search-result-listing" in html or "search-result-link" in html or "no results" in html.lower()


def expect_page(html: str, what: str) -> None:
    """Raise a diagnosable error describing the page Reddit answered with instead of `what`."""
    root = parse(html)
    title = root.first(lambda n: n.tag == "title")
    body = root.first(lambda n: n.tag == "body")
    gist = re.sub(r"\s+", " ", body.text() if body is not None else "")[:240]
    raise RuntimeError(f"old.reddit.com answered with a page that is not {what}" + (f" ({title.text()[:80]})" if title is not None else "")
                       + (f" — it says: {gist}" if gist else ""))


def _has(cls: str) -> Callable[[Node], bool]:
    return lambda n: cls in n.classes


def _is_thing(n: Node) -> bool:
    return n.tag == "div" and "thing" in n.classes and bool(n.attrs.get("data-fullname"))


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(s: str | None) -> int | None:
    m = re.search(r"-?\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else None


def _score(thing: Node) -> int | None:
    n = thing.first(lambda x: "score" in x.classes and "unvoted" in x.classes, stop=_is_thing)
    return _int(n.attrs.get("title")) if n is not None else None


def _md(thing: Node) -> str:
    n = thing.first(_has("md"), stop=_is_thing)
    return n.text() if n is not None else ""


def _time(thing: Node) -> tuple[float | None, bool]:
    times = list(thing.find(lambda x: x.tag == "time", stop=_is_thing))
    created = next((t for t in times if "edited-timestamp" not in t.classes), None)
    edited = any("edited-timestamp" in t.classes for t in times)
    return _epoch(created.attrs.get("datetime") if created is not None else None), edited


def thread_from_html(html: str, url: str, *, max_posts: int = 800) -> dict[str, Any]:
    """old.reddit.com thread page → the thread dict `community.read_reddit_thread` returns (same keys, same post shape)."""
    root = parse(html)
    things = [n for n in root.walk() if _is_thing(n)]
    link = next((t for t in things if "link" in t.classes and t.attrs["data-fullname"].startswith("t3_")), None)
    if link is None:
        expect_page(html, "a thread")
    op_id = link.attrs["data-fullname"][3:]
    tnode = link.first(lambda n: n.tag == "a" and "title" in n.classes, stop=_is_thing)
    title = tnode.text() if tnode is not None else url
    selftext = _md(link)
    created, edited = _time(link)
    author = link.attrs.get("data-author") or None
    posts: list[dict[str, Any]] = [{"post_id": op_id, "parent_id": None, "depth": 0, "author": author, "score": _score(link), "created": created,
                                    "edited": edited, "deleted": author in (None, "[deleted]") and not selftext,
                                    "text": title + ("\n\n" + selftext if selftext else ""), "kind": "post",
                                    "permalink": urljoin("https://www.reddit.com", link.attrs.get("data-permalink") or "")}]
    by_node: dict[int, str] = {id(link): op_id}
    depth_of: dict[str, int] = {op_id: 0}
    for t in things:
        if t is link or not t.attrs["data-fullname"].startswith("t1_"):
            continue
        if len(posts) >= max_posts:
            break
        pid = t.attrs["data-fullname"][3:]
        # the parent is the nearest enclosing .thing (old reddit nests replies inside their parent's .child block)
        anc, parent_id = t.parent, op_id
        while anc is not None:
            if _is_thing(anc):
                parent_id = by_node.get(id(anc), op_id)
                break
            anc = anc.parent
        depth = depth_of.get(parent_id, 0) + 1
        by_node[id(t)], depth_of[pid] = pid, depth
        body = _md(t)
        a = t.attrs.get("data-author") or None
        deleted = "deleted" in t.classes or body in ("[deleted]", "[removed]") or a == "[deleted]"
        created, edited = _time(t)
        posts.append({"post_id": pid, "parent_id": parent_id, "depth": depth, "author": a, "score": _score(t), "created": created, "edited": edited,
                      "deleted": deleted, "text": "" if deleted else body, "kind": "comment",
                      "permalink": urljoin("https://www.reddit.com", t.attrs.get("data-permalink") or "")})
    sub = link.attrs.get("data-subreddit") or ""
    nc = root.first(_has("panestack-title"))
    return {"platform": "reddit", "thread_id": op_id, "title": title, "community": ("r/" + sub) if sub else "", "url": posts[0]["permalink"] or url,
            "created": posts[0]["created"], "score": posts[0]["score"], "num_comments": _int(nc.text()) if nc is not None else max(0, len(posts) - 1),
            "posts": posts, "retrieved_at": time.time(), "representation": "old.reddit.com html"}


def search_from_html(html: str, community: str) -> list[dict[str, Any]]:
    """old.reddit.com search page → the candidate rows `community.enumerate_reddit` returns (metadata only)."""
    root = parse(html)
    sub = community.replace("r/", "").strip("/")
    out: list[dict[str, Any]] = []
    for r in root.find(lambda n: "search-result-link" in n.classes and bool(n.attrs.get("data-fullname"))):
        fid = r.attrs["data-fullname"]
        if not fid.startswith("t3_"):
            continue
        tnode = r.first(lambda n: n.tag == "a" and "search-title" in n.classes)
        cnode = r.first(lambda n: n.tag == "a" and "search-comments" in n.classes)
        href = (cnode.attrs.get("href") if cnode is not None else "") or (tnode.attrs.get("href") if tnode is not None else "")
        if not href or "/comments/" not in href:
            continue
        perm = urljoin("https://www.reddit.com", href).replace("://old.reddit.com", "://www.reddit.com")
        tm = r.first(lambda n: n.tag == "time")
        created = _epoch(tm.attrs.get("datetime") if tm is not None else None)
        auth = r.first(lambda n: n.tag == "a" and "author" in n.classes)
        sc = r.first(_has("search-score"))
        body = r.first(_has("md"))
        score = _int(sc.text()) if sc is not None else None
        out.append({"external_id": f"reddit:{fid[3:]}", "url": perm, "title": tnode.text() if tnode is not None else perm,
                    "description": (body.text() if body is not None else "")[:600], "creator": auth.text() if auth is not None else None,
                    "published_at": time.strftime("%Y-%m-%d", time.gmtime(created)) if created else None,
                    "view_count": score, "content_type": "post", "score": score, "num_comments": _int(cnode.text()) if cnode is not None else None,
                    "community": "r/" + sub})
    return out
