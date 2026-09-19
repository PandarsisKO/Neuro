"""G7 — Deep & Community Source Discovery (0.32.0).

Community is an EVIDENCE CLASS (community / experiential), not a platform type. Reddit is the first adapter; the shapes
here (thread tree, post locators, signals, missions, synthesis) are platform-neutral.

The THREAD is the acquired Source (platform 'community'); posts/comments are evidence LOCATORS (`community_posts`), never
global source rows. The full tree is kept locally with retrieved_at / platform ids / edited / deleted state; a correction
stays attached to the statement it corrects and that statement is never surfaced as unqualified consensus (its chunk is
prefixed with the correction). Chunks — what retrieval, findings and Claims see — are built only for posts that pass
deterministic pruning, so a 500-comment thread never goes blindly through a model.

Signals are multi-dimensional and deterministic ($0): relevance, substance, firsthand, specificity, quantitative,
engagement, evidence_links, claimed_context (self-described, never verified), disagreement, corrected. Upvotes are
community reaction, not truth. Independence is by lineage (G6) and by author: six posts repeating one article are one
line; six unrelated owners describing the same failure are six.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from . import db

log = logging.getLogger("neurosearch.community")

PLATFORM = "community"
SUBREDDIT_HOSTS = ("reddit.com", "www.reddit.com", "old.reddit.com")
SUBREDDIT_NAME = re.compile(r"^[a-z0-9_]{3,21}$", re.I)
# Reddit's edge refuses clients that announce a bot token in the UA (the app's normal UA ends with "NeuroSearch/1.0") — the
# listing endpoint is public, but it is served to browsers; we identify as the browser the user would use.
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HONEST_UA = "desktop:neurosearch:0.32 (personal research tool; single user; reads public threads on request)"
MAX_POSTS = 800                 # tree kept locally
MAX_CHUNK_POSTS = 120           # posts that become evidence chunks after pruning
MIN_POST_CHARS = 40

EXPERIENCE = re.compile(r"\b(i own(ed)?|we own(ed)?|i bought|we bought|i sold|after \w+ years?|in my experience|i wish i (had )?kn[eo]w|my (annual|yearly|monthly) cost|"
                        r"biggest mistake|wouldn'?t (do|buy) (it|that|one) again|unexpected(ly)?|lesson(s)? learned|i learned|what nobody tells you|i regret|cost me|"
                        r"we see this (frequently|a lot|often)|from experience|first[- ]hand|i'?ve (been|done|had)|when (i|we) (bought|sold|started|acquired))\b", re.I)
CONTEXT = re.compile(r"\b(cpa|a&p|a&p/ia|ia|attorney|lawyer|lender|underwriter|banker|broker|sba lender|enrolled agent|ea|mechanic|cfi|pilot|physician|md|"
                     r"bookkeeper|accountant|tax pro|loan officer)\b\s*(here|speaking|for \d+ years|of \d+ years)|\b(as an? (cpa|attorney|lender|broker|a&p|underwriter|mechanic|accountant))\b", re.I)
DISAGREE = re.compile(r"\b(this is (wrong|incorrect|not (true|right|accurate))|that'?s (wrong|incorrect|not (true|right))|actually,|not quite|correction:|to be clear,|"
                      r"you'?re (wrong|mistaken|confusing)|misinformation|that is false|the sop (actually|says))\b", re.I)
ACKNOWLEDGE = re.compile(r"\b(you'?re right|you are right|good catch|my mistake|i stand corrected|thanks for the correction|fair point|i was wrong|corrected)\b", re.I)
JOKE = re.compile(r"(\blol\b|\blmao\b|\bhaha|😂|🤣|\bthis\.\s*$|^\s*(same|this|underrated comment)\s*[.!]*\s*$)", re.I)
NUMBERS = re.compile(r"(\$\s?[\d,]+(\.\d+)?k?|\b\d+(\.\d+)?\s?(%|percent|hours?|hrs|years?|months?|weeks?|days?|k\b|x\b|bps)|\b\d{2,}\b)", re.I)
URL = re.compile(r"https?://[^\s)\]>]+?(?=[.,;:!?]*(?:\s|$|[)\]>]))")
INJECTION = re.compile(r"(ignore (all |the )?(previous|prior|above) instructions|you are (now )?(an?|the) (assistant|ai|model)|system prompt|call the tool|record_fact\(|"
                       r"disregard (your|the) (rules|instructions)|as an ai language model)", re.I)


# ---------------------------------------------------------------- durable subreddit catalog identity

def subreddit_name(url: str) -> str | None:
    """Return the canonical subreddit identity only for a subreddit container URL.

    A thread, multi-subreddit, profile, lookalike host, or malformed path is not a catalog. Thread URLs keep
    their existing Community Source route; this helper deliberately does no network work.
    """
    u = urlparse(url)
    host = (u.hostname or "").lower().rstrip(".")
    segs = [s for s in u.path.split("/") if s]
    if host not in SUBREDDIT_HOSTS or len(segs) != 2 or segs[0].lower() != "r":
        return None
    name = segs[1].lower()
    return name if SUBREDDIT_NAME.fullmatch(name) else None


def subreddit_url(name: str) -> str:
    """The one persisted URL form for a subreddit catalog."""
    if not SUBREDDIT_NAME.fullmatch(name):
        raise ValueError("invalid subreddit name")
    return f"https://www.reddit.com/r/{name.lower()}/"


def attach_subreddit_catalog(project_id: str | None, url: str) -> dict[str, Any]:
    """Create or attach a durable catalog without reading Reddit or creating a Source."""
    name = subreddit_name(url)
    if not name:
        raise ValueError("not a subreddit container URL")
    # Validate the owning project before creating the global catalog.  The
    # resource route already requires a project, but this owner is also used
    # directly by API/tests and must not leave an orphan collection when an
    # unknown id arrives there.
    if not project_id or not db.get_project(project_id):
        raise LookupError(project_id)
    catalog = db.upsert_collection("subreddit", name, subreddit_url(name), f"r/{name}")
    db.add_project_collections(project_id, [catalog["id"]])
    return catalog


# ---------------------------------------------------------------- adapters (metadata-cheap, all through safe_fetch)

def _reddit_attempts(url: str) -> list[tuple[str, dict[str, str | None]]]:
    """The ways Reddit's public JSON may answer a client that is not a browser. Reddit's own rule is a unique, descriptive
    User-Agent (a spoofed browser UA from a non-browser TLS stack is exactly what its filter refuses), so every rung
    identifies as NeuroSearch; the hosts differ. When all three refuse, the caller reads old.reddit.com's page instead."""
    honest = {"User-Agent": HONEST_UA, "Accept": "application/json", "Upgrade-Insecure-Requests": None,
              "Sec-Fetch-Dest": None, "Sec-Fetch-Mode": None, "Sec-Fetch-Site": None, "Sec-Fetch-User": None}
    old = url.replace("://www.reddit.com", "://old.reddit.com", 1)
    api = url.replace("://www.reddit.com", "://api.reddit.com", 1).replace(".json?", "?").replace(".json", "")
    return [(url, honest), (old, honest), (api, honest)]      # a spoofed browser UA was refused on every host (0.32.2 probe)


def _json_get(url: str) -> Any:
    """Reddit's public listing endpoints answer without login, but refuse clients they take for scrapers. We walk a short
    ladder of honest requests (see `_reddit_attempts`) and, when every rung is refused, say exactly what each one got,
    so a refusal is diagnosable from the job message alone."""
    from .safe_fetch import safe_fetch
    tried: list[str] = []
    for u, hdrs in _reddit_attempts(url):
        res = safe_fetch(u, content_class="html", headers=hdrs)
        if res.status == 200:
            try:
                return json.loads(res.body.decode("utf-8", errors="replace"))
            except ValueError:
                tried.append(f"{urlparse(u).netloc}: 200 but not JSON")
                continue
        snippet = re.sub(r"<[^>]+>|\s+", " ", res.body[:600].decode("utf-8", errors="replace")).strip()[:60]
        tried.append(f"{urlparse(u).netloc}: HTTP {res.status}" + (f" ({snippet})" if snippet else ""))
        if res.status not in (403, 404, 429, 503):
            break
    raise RuntimeError("Reddit refused the listing — " + "; ".join(tried))


def _old_reddit_html(url: str, *, expect: Any = None) -> str:
    """The server-rendered page on old.reddit.com, requested exactly as a browser navigation (the one representation Reddit
    serves to a plain client without login). Reddit sometimes answers a cookie-less first visit with a welcome/consent
    page and only the second visit — carrying the cookies it just set — with the content; `expect(html)` says whether
    the page is the one we asked for, and when it is not we make that second visit once. Raises with the status (or the
    page's gist) when even that is refused."""
    from .safe_fetch import safe_fetch
    u = url.replace("://www.reddit.com", "://old.reddit.com", 1).replace("://reddit.com", "://old.reddit.com", 1)
    hdrs: dict[str, str | None] = {"User-Agent": BROWSER_UA}
    for visit in (1, 2):
        res = safe_fetch(u, content_class="html", headers=hdrs)
        if res.status != 200:
            raise RuntimeError(f"old.reddit.com: HTTP {res.status}")
        if urlparse(res.url).netloc.lower() != "old.reddit.com":
            raise RuntimeError(f"old.reddit.com redirected to {res.url[:120]}")
        html = res.body.decode("utf-8", errors="replace")
        if expect is None or expect(html):
            return html
        cookies = [line.split(";", 1)[0].strip() for line in (res.headers.get("set-cookie") or "").split("\n") if "=" in line]
        if visit == 2 or not cookies:
            break
        hdrs["Cookie"] = "; ".join(cookies)
    return html


def is_reddit_thread(url: str) -> bool:
    u = urlparse(url)
    return u.netloc.lower().replace("www.", "").replace("old.", "") == "reddit.com" and "/comments/" in u.path


def reddit_thread_id(url: str) -> str | None:
    m = re.search(r"/comments/([a-z0-9]+)", urlparse(url).path)
    return m.group(1) if m else None


def _reddit_json_url(url: str) -> str:
    u = urlparse(url)
    path = u.path.rstrip("/")
    if not path.endswith(".json"):
        path += ".json"
    return f"https://www.reddit.com{path}?raw_json=1&limit=500&depth=12"


def _reddit_html_url(url: str) -> str:
    u = urlparse(url)
    return f"https://www.reddit.com{u.path.rstrip('/')}/?limit=500&depth=12"


# ---------------------------------------------------------------- Reddit's official API (app-only OAuth; read-only public data)

_OAUTH: dict[str, Any] = {"token": None, "expires": 0.0}
OAUTH_HOST = "https://oauth.reddit.com"


class RedditApiError(RuntimeError):
    """Typed official-API outcome preserved through the durable scan job."""

    def __init__(self, status: int, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _retry_after(headers: dict[str, str]) -> float | None:
    raw = next((value for key, value in headers.items() if key.lower() == "retry-after"), None)
    try:
        seconds = float(raw) if raw is not None else None
    except ValueError:
        return None
    return max(1.0, min(seconds, 24 * 3600.0)) if seconds is not None else None


def reddit_api_configured() -> bool:
    from .config import settings
    return bool(settings.reddit_client_id and settings.reddit_client_secret)


def _oauth_token() -> str:
    """Application-only OAuth (client_credentials): Reddit's sanctioned way for a script to read public data. Cached until
    it expires. Credentials live only in .env (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET); never in the database."""
    import base64
    from .config import settings
    from .safe_fetch import safe_fetch
    if _OAUTH["token"] and time.time() < _OAUTH["expires"] - 60:
        return _OAUTH["token"]
    basic = base64.b64encode(f"{settings.reddit_client_id}:{settings.reddit_client_secret}".encode()).decode()
    res = safe_fetch("https://www.reddit.com/api/v1/access_token", method="POST", body=b"grant_type=client_credentials", content_class="html",
                     headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded", "User-Agent": HONEST_UA,
                              "Accept": "application/json", "Upgrade-Insecure-Requests": None, "Sec-Fetch-Dest": None, "Sec-Fetch-Mode": None,
                              "Sec-Fetch-Site": None, "Sec-Fetch-User": None})
    if res.status != 200:
        raise RedditApiError(res.status, f"Reddit API: token request refused (HTTP {res.status}) — check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env",
                             retry_after=_retry_after(res.headers))
    try:
        tok = json.loads(res.body.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise RuntimeError("Reddit API: token response was not JSON") from e
    if not tok.get("access_token"):
        raise RuntimeError(f"Reddit API: {tok.get('error') or 'no access token in the response'}")
    _OAUTH["token"], _OAUTH["expires"] = tok["access_token"], time.time() + float(tok.get("expires_in") or 3600)
    return _OAUTH["token"]


def _api_get(path_and_query: str) -> Any:
    """GET oauth.reddit.com/<path> with the app-only bearer token; one re-auth on 401."""
    from .safe_fetch import safe_fetch
    for attempt in (1, 2):
        tok = _oauth_token()
        res = safe_fetch(OAUTH_HOST + path_and_query, content_class="html",
                         headers={"Authorization": "bearer " + tok, "User-Agent": HONEST_UA, "Accept": "application/json", "Upgrade-Insecure-Requests": None,
                                  "Sec-Fetch-Dest": None, "Sec-Fetch-Mode": None, "Sec-Fetch-Site": None, "Sec-Fetch-User": None})
        if res.status == 401 and attempt == 1:
            _OAUTH["token"] = None
            continue
        if res.status == 429:
            raise RedditApiError(429, "Reddit API: rate limited (429)", retry_after=_retry_after(res.headers))
        if res.status != 200:
            raise RedditApiError(res.status, f"Reddit API: HTTP {res.status}", retry_after=_retry_after(res.headers))
        try:
            return json.loads(res.body.decode("utf-8", errors="replace"))
        except ValueError as e:
            raise RuntimeError("Reddit API: response was not JSON") from e
    raise RedditApiError(401, "Reddit API: unauthorized")


def enumerate_subreddit_page(subreddit: str, after: str | None = None, *, limit: int = 100) -> tuple[list[dict[str, Any]], str | None]:
    """Read one official `/new` listing page as metadata only.

    Whole-catalog scans deliberately have no public-JSON, HTML, browser, archive, or search fallback. Those
    paths remain valid for individual thread capture and the older query-based Explore feature, but a durable
    catalog must fail honestly when approved API access is unavailable.
    """
    if not reddit_api_configured():
        raise RuntimeError("Reddit API credentials are required to catalog a subreddit (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)")
    if not SUBREDDIT_NAME.fullmatch(subreddit):
        raise ValueError("invalid subreddit name")
    from urllib.parse import quote
    query = f"raw_json=1&limit={max(1, min(limit, 100))}"
    if after:
        query += "&after=" + quote(after, safe="")
    data = _api_get(f"/r/{quote(subreddit)}/new?{query}")
    listing = data.get("data") if isinstance(data, dict) else None
    if not isinstance(listing, dict):
        raise RuntimeError("Reddit API: malformed subreddit listing")
    rows: list[dict[str, Any]] = []
    for child in listing.get("children") or []:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict) or not post.get("id") or not post.get("permalink"):
            continue
        outbound = post.get("url_overridden_by_dest") or post.get("url")
        from urllib.parse import urlparse
        outbound_domain = urlparse(outbound).hostname.lower() if isinstance(outbound, str) and outbound else None
        availability = "removed" if post.get("removed_by_category") else ("deleted" if post.get("author") == "[deleted]" else "available")
        rows.append({"external_id": f"reddit:{post['id']}", "url": "https://www.reddit.com" + post["permalink"],
                     "title": post.get("title"), "description": (post.get("selftext") or "")[:2000] or None,
                     "creator": post.get("author"),
                     "published_at": time.strftime("%Y-%m-%d", time.gmtime(post.get("created_utc") or 0)) if post.get("created_utc") else None,
                     "view_count": post.get("score"), "content_type": "post", "observed_metadata": True,
                     "metadata": {"version": 1, "subreddit": subreddit.lower(), "score": post.get("score"),
                                  "comment_count": post.get("num_comments"), "flair": post.get("link_flair_text"),
                                  "created_utc": post.get("created_utc"), "outbound_url": outbound,
                                  "outbound_domain": outbound_domain,
                                  "availability": availability}})
    next_cursor = listing.get("after")
    return rows, str(next_cursor) if next_cursor else None


def thread_from_listing(data: Any, url: str, *, retrieved_via: str = "reddit json") -> dict[str, Any]:
    """A Reddit comments listing (the two-element [link listing, comment listing] JSON — from the API, the public .json
    endpoint, or the browser extension) → the thread dict every other part of G7 consumes."""
    if not isinstance(data, list) or len(data) < 1:
        raise RuntimeError("unexpected Reddit response")
    try:
        link = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("unexpected Reddit response (no link in the listing)") from e
    posts: list[dict[str, Any]] = []
    op_id = link["id"]
    posts.append({"post_id": op_id, "parent_id": None, "depth": 0, "author": link.get("author"), "score": link.get("score"),
                  "created": link.get("created_utc"), "edited": bool(link.get("edited")), "deleted": link.get("author") in ("[deleted]", None) and not link.get("selftext"),
                  "text": (link.get("title") or "") + ("\n\n" + link["selftext"] if link.get("selftext") else ""), "kind": "post",
                  "permalink": "https://www.reddit.com" + link.get("permalink", "")})

    unloaded = {"stubs": 0, "count": 0}                                   # B2: what the listing itself says it left out

    def walk(children: list[dict[str, Any]], parent: str, depth: int) -> None:
        for ch in children:
            if ch.get("kind") == "more":
                unloaded["stubs"] += 1
                unloaded["count"] += int((ch.get("data") or {}).get("count") or 0)
                continue
            if ch.get("kind") != "t1" or len(posts) >= MAX_POSTS:
                continue
            d = ch["data"]
            body = d.get("body") or ""
            deleted = body in ("[deleted]", "[removed]") or d.get("author") in ("[deleted]",)
            posts.append({"post_id": d["id"], "parent_id": parent, "depth": depth, "author": d.get("author"), "score": d.get("score"),
                          "created": d.get("created_utc"), "edited": bool(d.get("edited")), "deleted": deleted, "text": "" if deleted else body, "kind": "comment",
                          "permalink": "https://www.reddit.com" + d.get("permalink", "")})
            replies = d.get("replies")
            if isinstance(replies, dict):
                walk(replies.get("data", {}).get("children", []), d["id"], depth + 1)
    if len(data) > 1:
        walk(data[1]["data"]["children"], op_id, 1)
    community = link.get("subreddit_name_prefixed") or ("r/" + link["subreddit"] if link.get("subreddit") else "")
    return {"platform": "reddit", "thread_id": op_id, "title": link.get("title") or url, "community": community, "url": "https://www.reddit.com" + link.get("permalink", ""),
            "created": link.get("created_utc"), "score": link.get("score"), "num_comments": link.get("num_comments"), "posts": posts, "retrieved_at": time.time(),
            "representation": retrieved_via, "capture": {"method": "json", "load_more_remaining": unloaded["stubs"], "unloaded_count": unloaded["count"]}}


def thread_from_capture(capture: dict[str, Any], url: str) -> dict[str, Any]:
    """The extension's `reddit_thread_capture/1` contract (thread + comments + capture diagnostics, produced in the
    user's browser from the same-origin JSON or from the rendered DOM) → the thread dict. Same shape as every other
    reading; `capture` diagnostics ride along so B2 can record completeness. A raw Reddit listing is accepted too."""
    if isinstance(capture, dict) and capture.get("listing") is not None and not capture.get("thread"):
        t = thread_from_listing(capture["listing"], url, retrieved_via="browser extension")
        t["capture"] = capture.get("capture") or {"status": "unknown", "method": "json"}
        return t
    if not isinstance(capture, dict) or not isinstance(capture.get("thread"), dict):
        raise RuntimeError("unexpected capture payload (no thread)")
    th, comments = capture["thread"], capture.get("comments") or []
    tid = th.get("reddit_id") or reddit_thread_id(th.get("permalink") or url) or ""
    tid = tid[3:] if tid.startswith("t3_") else tid
    if not tid:
        raise RuntimeError("capture has no thread id")
    perm = th.get("permalink") or th.get("canonical_url") or url
    posts: list[dict[str, Any]] = [{"post_id": tid, "parent_id": None, "depth": 0, "author": th.get("author"), "score": th.get("score"), "created": th.get("created_at"),
                                    "edited": bool(th.get("edited")), "deleted": bool(th.get("deleted")) or (th.get("author") in (None, "[deleted]") and not th.get("body")),
                                    "text": (th.get("title") or "") + ("\n\n" + th["body"] if th.get("body") else ""), "kind": "post", "permalink": perm}]
    known = {tid}
    for c in comments:
        if len(posts) >= MAX_POSTS or not isinstance(c, dict):
            break
        cid = str(c.get("reddit_id") or "")
        cid = cid[3:] if cid.startswith("t1_") else cid
        if not cid or cid in known:
            continue
        pid = str(c.get("parent_id") or tid)
        pid = pid[3:] if pid[:3] in ("t1_", "t3_") else pid
        text = c.get("text") or ""
        deleted = bool(c.get("deleted")) or text in ("[deleted]", "[removed]") or c.get("author") == "[deleted]"
        posts.append({"post_id": cid, "parent_id": pid if pid in known else tid, "depth": int(c.get("depth") or 1), "author": c.get("author"), "score": c.get("score"),
                      "created": c.get("created_at"), "edited": bool(c.get("edited")), "deleted": deleted, "text": "" if deleted else text, "kind": "comment",
                      "permalink": c.get("permalink") or perm})
        known.add(cid)
    sub = th.get("subreddit") or _subreddit_from(perm) or ""
    community = sub if sub.startswith("r/") else (f"r/{sub}" if sub else "")
    return {"platform": "reddit", "thread_id": tid, "title": th.get("title") or url, "community": community, "url": perm if perm.startswith("http") else "https://www.reddit.com" + perm,
            "created": th.get("created_at"), "score": th.get("score"), "num_comments": th.get("expected_comments") if th.get("expected_comments") is not None else len(posts) - 1,
            "posts": posts, "retrieved_at": time.time(), "representation": f"browser extension ({capture.get('method') or 'capture'})", "capture": capture.get("capture") or {}}


def _subreddit_from(url: str) -> str | None:
    m = re.search(r"/(r/[^/]+)/", urlparse(url).path)
    return m.group(1) if m else None


def read_reddit_thread(url: str) -> dict[str, Any]:
    """The post + the comment forest (ids, parents, authors, scores, edited/deleted flags). Order of readings:
    (1) Reddit's official API when credentials are configured; (2) the public .json endpoint with an honest UA (refused to
    every non-browser client since 2026-06-30, kept because it is free to try); (3) old.reddit.com's server-rendered page
    (login-walled since the same date; kept for the day it is not). When all fail, the error names each — and the browser
    extension's "Send this page" reads the thread inside the user's own browser (`api_ingest_thread`)."""
    from urllib.parse import quote
    errors: list[str] = []
    if reddit_api_configured():
        tid = reddit_thread_id(url)
        try:
            return thread_from_listing(_api_get(f"/comments/{quote(tid or '')}?raw_json=1&limit=500&depth=12"), url, retrieved_via="reddit api")
        except RuntimeError as e:
            errors.append(str(e))
    try:
        return thread_from_listing(_json_get(_reddit_json_url(url)), url)
    except RuntimeError as e:
        errors.append(str(e))
    from . import reddit_html
    try:
        html = _old_reddit_html(_reddit_html_url(url), expect=reddit_html.looks_like_thread)
        return reddit_html.thread_from_html(html, url, max_posts=MAX_POSTS)
    except RuntimeError as e:
        errors.append(f"server-rendered page: {e}")
    from .acquire import AcquisitionFailure
    hint = "" if reddit_api_configured() else " · Reddit refuses non-browser clients: use the extension's “Send this page” on the thread, or add REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET to .env"
    raise AcquisitionFailure("; ".join(errors) + hint, adapter="reddit_thread", cls="blocked")


def enumerate_reddit(community: str, query: str, *, limit: int = 25, sort: str = "relevance", time_filter: str = "all") -> list[dict[str, Any]]:
    """Candidate threads for a mission: cheap metadata (title, excerpt, score, comments, date) — nothing acquired."""
    sub = community.replace("r/", "").strip("/")
    from urllib.parse import quote
    q = f"q={quote(query)}&restrict_sr=1&sort={sort}&t={time_filter}&limit={min(limit, 100)}&raw_json=1"
    errors: list[str] = []
    data = None
    if reddit_api_configured():
        try:
            data = _api_get(f"/r/{quote(sub)}/search?{q}")
        except RuntimeError as e:
            errors.append(str(e))
    if data is None:
        try:
            data = _json_get(f"https://www.reddit.com/r/{quote(sub)}/search.json?{q}")
        except RuntimeError as e:
            errors.append(str(e))
    if data is None:
        from . import reddit_html
        try:
            html = _old_reddit_html(f"https://www.reddit.com/r/{quote(sub)}/search?q={quote(query)}&restrict_sr=on&sort={sort}&t={time_filter}",
                                    expect=reddit_html.looks_like_search)
            rows = reddit_html.search_from_html(html, sub)[:limit]
            if not rows:
                reddit_html.expect_page(html, "a search listing")   # raises with the page's gist when it is not one
            return rows
        except RuntimeError as e:
            errors.append(f"server-rendered page: {e}")
        hint = "" if reddit_api_configured() else " · subreddit search needs Reddit API credentials (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env); threads can still be sent from the extension"
        raise RuntimeError("; ".join(errors) + hint)
    out = []
    for ch in data.get("data", {}).get("children", []):
        d = ch.get("data", {})
        if not d.get("permalink"):
            continue
        out.append({"external_id": f"reddit:{d['id']}", "url": "https://www.reddit.com" + d["permalink"], "title": d.get("title"),
                    "description": (d.get("selftext") or "")[:600], "creator": d.get("author"), "published_at": time.strftime("%Y-%m-%d", time.gmtime(d.get("created_utc") or 0)) if d.get("created_utc") else None,
                    "view_count": d.get("score"), "content_type": "post", "score": d.get("score"), "num_comments": d.get("num_comments"), "community": "r/" + sub})
    return out


# ---------------------------------------------------------------- signals ($0, multi-dimensional — never one score)

def signals(post: dict[str, Any], query_terms: set[str] | None = None) -> dict[str, Any]:
    text = post.get("text") or ""
    low = text.lower()
    toks = set(re.findall(r"[a-z][a-z0-9\-']{3,}", low))
    rel = round(len(toks & query_terms) / max(1, len(query_terms)), 2) if query_terms else None
    nums = NUMBERS.findall(text)
    ctx = CONTEXT.search(text)
    return {
        "relevance": rel,
        "substance": round(min(1.0, len(text) / 900), 2),
        "firsthand": bool(EXPERIENCE.search(text)),
        "specificity": round(min(1.0, (len(nums) + len(re.findall(r"\b[A-Z][a-z]+ [A-Z0-9][A-Za-z0-9-]+\b", text))) / 6), 2),
        "quantitative": len(nums),
        "engagement": post.get("score"),                                    # community reaction — not truth
        "evidence_links": URL.findall(text)[:5],
        "claimed_context": ({"context": ctx.group(0).strip(), "basis": "self-described in the post", "verified": False} if ctx else None),
        "disagreement": bool(DISAGREE.search(text)),
        "acknowledges": bool(ACKNOWLEDGE.search(text)),
        "low_content": bool(JOKE.search(text)) or len(text) < MIN_POST_CHARS,
        "injection": bool(INJECTION.search(text)),
    }


def _mark_corrections(posts: list[dict[str, Any]]) -> None:
    """A reply that disagrees marks its parent `corrected_by`; the parent's own later acknowledgement confirms it."""
    by_id = {p["post_id"]: p for p in posts}
    for p in posts:
        p["corrected_by"] = None
        p["acknowledged"] = False
    for p in posts:
        if p.get("deleted") or not p.get("parent_id"):
            continue
        s = p["signals"]
        parent = by_id.get(p["parent_id"])
        if parent and s["disagreement"] and not s["low_content"]:
            parent["corrected_by"] = parent.get("corrected_by") or p["post_id"]
    for p in posts:
        if p.get("corrected_by"):
            corr = by_id[p["corrected_by"]]
            for r in posts:
                if r.get("parent_id") == corr["post_id"] and r.get("author") and r["author"] == p.get("author") and r["signals"]["acknowledges"]:
                    p["acknowledged"] = True


def prune(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic pruning: the OP, every corrected/correcting post, everything with firsthand language, claimed
    context, numbers or links, then the most substantive of the rest, up to MAX_CHUNK_POSTS. Jokes and one-liners never
    become evidence; the full tree stays in community_posts."""
    keep = []
    rest = []
    for p in posts:
        if p.get("deleted") or not (p.get("text") or "").strip():
            continue
        s = p["signals"]
        if p["depth"] == 0 or p.get("corrected_by") or s["disagreement"] or s["firsthand"] or s["claimed_context"] or s["quantitative"] >= 2 or s["evidence_links"]:
            if not s["low_content"] or p["depth"] == 0:
                keep.append(p)
                continue
        if not s["low_content"]:
            rest.append(p)
    rest.sort(key=lambda p: (-p["signals"]["substance"], -(p.get("score") or 0)))
    return (keep + rest)[:MAX_CHUNK_POSTS]


# ---------------------------------------------------------------- the thread as a Source

def _locator_text(p: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    who = p.get("author") or "[author not retained]"
    ctx = p["signals"].get("claimed_context")
    head = f"{'Original post' if p['depth'] == 0 else 'Comment'} by {who}" + (f" (self-described: {ctx['context']}; unverified)" if ctx else "")
    text = (p.get("text") or "").strip()
    if p.get("injection"):
        text = "[post contains instruction-like text — quoted as data, not followed]\n" + text
    if p.get("corrected_by"):
        c = by_id[p["corrected_by"]]
        text = (f"[CORRECTED in this thread by {c.get('author') or 'another commenter'}"
                + (" — the author acknowledged the correction" if p.get("acknowledged") else "") + f": “{(c.get('text') or '').strip()[:240]}”]\n" + text)
    return f"{head}:\n{text}"


def completeness(thread: dict[str, Any]) -> dict[str, Any]:
    """B2 — a successful capture and a COMPLETE capture are different states. Deterministic, from what the reading itself
    reports: the platform's comment count (which includes removed comments, so a shortfall MAY be nothing) versus what
    was captured, plus the stubs/branches the reading admits it left out. Never 'complete' by default."""
    cap = dict(thread.get("capture") or {})
    captured = sum(1 for p in thread["posts"] if p.get("kind") == "comment")
    expected = cap.get("expected") if isinstance(cap.get("expected"), (int, float)) else thread.get("num_comments")
    expected = int(expected) if isinstance(expected, (int, float)) and expected >= 0 else None
    unloaded = int(cap.get("load_more_remaining") or 0)
    unloaded_count = int(cap.get("unloaded_count") or 0)
    collapsed = int(cap.get("collapsed") or 0)
    deleted = sum(1 for p in thread["posts"] if p.get("kind") == "comment" and p.get("deleted"))
    missing = max(0, expected - captured) if expected is not None else None
    # a small shortfall against the platform's count is normal (deleted comments stay counted); a large one is a partial read
    large_shortfall = missing is not None and missing > max(5, int(0.1 * (expected or 0)))
    if cap.get("status") == "partial" or unloaded or large_shortfall:
        status, reason = "partial", None
        if unloaded:
            reason = f"{unloaded} 'more replies' branch{'es' if unloaded != 1 else ''} ({unloaded_count or 'some'} comments) not loaded"
        elif missing:
            reason = f"{missing} comment{'s' if missing != 1 else ''} may not be loaded (the platform's count includes removed comments)"
        else:
            reason = cap.get("partial_reason") or "the reader reported a partial capture"
    elif expected is None and cap.get("status") != "complete":
        status, reason = "unknown", "the platform did not report a comment count"
    else:
        status, reason = "complete", None
    return {"status": status, "captured": captured, "expected": expected, "missing": missing, "load_more_remaining": unloaded, "unloaded_count": unloaded_count or None,
            "collapsed": collapsed or None, "deleted": deleted, "method": cap.get("method") or thread.get("representation") or "reddit json",
            "captured_at": thread.get("retrieved_at"), "partial_reason": reason, "accepted": False}


def _merge_partial(source_id: str, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A PARTIAL capture never deletes what an earlier reading saw: previously known posts absent from this capture keep
    their rows (their stored ordinal order first, so evidence locators stay valid); the new posts follow."""
    seen = {p["post_id"] for p in posts}
    conn = db.connect()
    kept_prior: list[dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM community_posts WHERE source_id=? ORDER BY ordinal", (source_id,)).fetchall():
        if r["post_id"] in seen:
            continue
        kept_prior.append({"post_id": r["post_id"], "parent_id": r["parent_id"], "depth": r["depth"], "author": r["author"], "score": r["score"], "created": r["created"],
                           "edited": bool(r["edited"]), "deleted": bool(r["deleted"]), "text": r["text"] or "", "kind": r["kind"], "permalink": r["permalink"], "_prior": True})
    if not kept_prior:
        return posts
    by_id = {p["post_id"]: p for p in posts}
    op = next((p for p in posts if p["kind"] == "post"), None)
    merged = [op] if op else []
    prior_ids = {p["post_id"] for p in kept_prior}
    # previously known comments in their stored order, then everything new from this capture (its own order)
    merged += [p for p in kept_prior if p["kind"] == "comment"]
    merged += [p for p in posts if p["kind"] == "comment"]
    for p in merged:
        if p.get("parent_id") and p["parent_id"] not in by_id and p["parent_id"] not in prior_ids and op:
            p["parent_id"] = op["post_id"]
    return merged


def store_thread(thread: dict[str, Any], *, tags: list[str] | None = None, project_id: str | None = None, query_terms: set[str] | None = None) -> dict[str, Any]:
    """Thread → ONE global source (platform 'community', external_id '<platform>:<thread_id>'), the full post tree in
    community_posts, and chunks for the pruned high-signal posts (locator = post ordinal; deep link = permalink).
    B2: `completeness` is recorded on the source; a partial capture merges into what was already known instead of
    marking the unseen posts unavailable — only a complete reading can say a post vanished."""
    from . import identity, media
    comp = completeness(thread)
    posts = thread["posts"]
    for p in posts:
        p["signals"] = signals(p, query_terms)
        p["injection"] = p["signals"]["injection"]
    _mark_corrections(posts)
    by_id = {p["post_id"]: p for p in posts}
    kept = prune(posts)
    order = {p["post_id"]: i + 1 for i, p in enumerate(posts)}            # locator = position in the tree (stable per revision)
    ext = f"{thread['platform']}:{thread['thread_id']}"
    url = media.canonical_url(thread["url"]) if thread["url"].startswith("http") else thread["url"]
    cand = identity.Candidate(platform=PLATFORM, external_id=ext, url=url, title=thread["title"], canonical_url=url, tags=list(tags or []),
                              fields={"channel": thread.get("community"), "published_at": time.strftime("%Y-%m-%d", time.gmtime(thread["created"])) if thread.get("created") else None,
                                      "transcript_kind": "community", "description": f"{thread.get('community') or thread['platform']} thread · {len(posts)} posts · {thread.get('score')} points"})
    res = identity.resolve_or_create_source(cand, project_id, retry=True)
    src = res.source
    if comp["status"] != "complete":
        merged = _merge_partial(src["id"], posts)
        if merged is not posts:
            posts = merged
            for p in posts:
                if "signals" not in p:
                    p["signals"] = signals(p, query_terms)
                    p["injection"] = p["signals"]["injection"]
            _mark_corrections(posts)
            by_id = {p["post_id"]: p for p in posts}
            kept = prune(posts)
            order = {p["post_id"]: i + 1 for i, p in enumerate(posts)}
            comp["captured"] = sum(1 for p in posts if p.get("kind") == "comment")
            comp["missing"] = max(0, comp["expected"] - comp["captured"]) if comp["expected"] is not None else None
            if comp["status"] == "partial" and not comp["load_more_remaining"] and comp["expected"] is not None and comp["captured"] >= comp["expected"]:
                comp["status"], comp["partial_reason"] = "complete", None       # the merge reached the platform's count: complete now
            elif comp["status"] == "partial" and comp["missing"] is not None:
                comp["partial_reason"] = f"{comp['missing']} comment{'s' if comp['missing'] != 1 else ''} may not be loaded (merged with the earlier reading)"
    pages = [{"page": order[p["post_id"]], "text": _locator_text(p, by_id)} for p in kept]
    segments = [{"start": float(pg["page"]), "end": float(pg["page"]), "text": " ".join(pg["text"].split())} for pg in pages]
    # one chunk per post (the post IS the locator); a very long post is split into pieces that keep its ordinal
    chunks = []
    for pg in pages:
        text = pg["text"].strip()
        pieces = [text[i:i + 1800] for i in range(0, len(text), 1800)] or [text]
        for piece in pieces:
            chunks.append({"start": float(pg["page"]), "end": float(pg["page"]), "text": piece})
    with db.batch():
        db.replace_transcript(src["id"], segments, chunks)
        rev = db.source_revision(src["id"])
        conn = db.connect()
        seen_ids = {p["post_id"] for p in posts}
        if comp["status"] == "complete":                                  # only a complete reading can say a post vanished
            for row in conn.execute("SELECT post_id FROM community_posts WHERE source_id=?", (src["id"],)).fetchall():
                if row["post_id"] not in seen_ids:                        # previously retrieved, now gone → unavailable, never silently dropped
                    conn.execute("UPDATE community_posts SET deleted=1, availability='unavailable', last_seen_revision=last_seen_revision WHERE source_id=? AND post_id=?", (src["id"], row["post_id"]))
        for p in posts:
            s = p["signals"]
            conn.execute("INSERT INTO community_posts (source_id, post_id, parent_id, ordinal, depth, kind, author, claimed_context, score, created, edited, deleted, availability, "
                         "text, permalink, corrected_by, acknowledged, firsthand, disagreement, quantitative, evidence_links, injection, in_chunks, retrieved_at, last_seen_revision) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id, post_id) DO UPDATE SET parent_id=excluded.parent_id, ordinal=excluded.ordinal, "
                         "depth=excluded.depth, author=COALESCE(excluded.author, community_posts.author), claimed_context=excluded.claimed_context, score=excluded.score, edited=excluded.edited, "
                         "deleted=excluded.deleted, availability=excluded.availability, text=CASE WHEN excluded.deleted=1 THEN community_posts.text ELSE excluded.text END, permalink=excluded.permalink, "
                         "corrected_by=excluded.corrected_by, acknowledged=excluded.acknowledged, firsthand=excluded.firsthand, disagreement=excluded.disagreement, quantitative=excluded.quantitative, "
                         "evidence_links=excluded.evidence_links, injection=excluded.injection, in_chunks=excluded.in_chunks, retrieved_at=excluded.retrieved_at, last_seen_revision=excluded.last_seen_revision",
                         (src["id"], p["post_id"], p.get("parent_id"), order[p["post_id"]], p["depth"], p["kind"], p.get("author"), json.dumps(s["claimed_context"]) if s["claimed_context"] else None,
                          p.get("score"), p.get("created"), 1 if p.get("edited") else 0, 1 if p.get("deleted") else 0, "unavailable" if p.get("deleted") else "available",
                          p.get("text") or "", p.get("permalink"), p.get("corrected_by"), 1 if p.get("acknowledged") else 0, 1 if s["firsthand"] else 0, 1 if s["disagreement"] else 0,
                          s["quantitative"], json.dumps(s["evidence_links"]), 1 if s["injection"] else 0, 1 if p in kept else 0, thread["retrieved_at"], rev))
        comp_line = "" if comp["status"] == "complete" else (f" · {comp['captured']} of ~{comp['expected']} comments captured" if comp["expected"] is not None else " · comment count unknown")
        db.upsert_source(platform=PLATFORM, external_id=ext, title=thread["title"], url=url, transcript_kind="community", channel=thread.get("community"),
                         description=f"{thread.get('community') or thread['platform']} thread · {len(posts)} posts ({len(kept)} substantive) · {thread.get('score')} points{comp_line}",
                         status="ready", error=None, error_class=None, completeness=json.dumps(comp))
    # G6: what the thread quotes / discusses resolves to Works — the thread interprets the Work, never a second lineage
    try:
        from . import works
        for p in kept:
            for i in works.extract_identifiers(p.get("text") or ""):
                w, _ = works.ensure_work(i["kind"], i["family"], identifiers=[{"scheme": i["scheme"], "value": i["value"]}], publisher=i.get("publisher"))
                vid = works.ensure_version(w["id"], i["version"])["id"] if i.get("version") else None
                works.link_source(src["id"], w["id"], version_id=vid, relation="interprets", form="derivative", confidence="identifier", basis={"post": p["post_id"], "identifier": f"{i['scheme']}:{i['value']}"})
    except Exception as e:  # noqa: BLE001
        log.warning("community work links skipped: %s", e)
    return {"source_id": src["id"], "title": thread["title"], "posts": len(posts), "substantive": len(kept), "chunks": len(chunks), "identity": res.state,
            "corrections": sum(1 for p in posts if p.get("corrected_by")), "claimed_contexts": sum(1 for p in posts if p["signals"]["claimed_context"]),
            "firsthand": sum(1 for p in kept if p["signals"]["firsthand"]), "community": thread.get("community"), "completeness": comp}


def acquire_thread(url: str, *, tags: list[str] | None = None, project_id: str | None = None, progress: Any = None, query: str | None = None,
                   listing: Any = None, capture: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    """Acquire one community thread as a Source through the standard identity/revision path. Reddit today; other adapters
    plug in here by host. `listing` = the thread's JSON already read inside the user's browser (the extension's
    "Send this page"): the same shape, the same path, one fewer network step."""
    from . import identity, ingest, media
    if progress:
        progress(0.1, "reading the thread…")
    if capture is not None and is_reddit_thread(url):
        thread = thread_from_capture(capture, url)
    elif listing is not None and is_reddit_thread(url):
        thread = thread_from_listing(listing, url, retrieved_via="browser extension")
    elif is_reddit_thread(url):
        try:
            thread = read_reddit_thread(url)
        except Exception as e:  # noqa: BLE001
            from .acquire import AcquisitionFailure
            if not isinstance(e, AcquisitionFailure):
                raise
            # Global Library first (B1 gate 10): a thread already owned is attached, never sent to the browser; a fresh
            # re-read (refresh) still happens whenever the server CAN read
            tid = reddit_thread_id(url)
            state, existing = identity.resolve(identity.Candidate(platform=PLATFORM, external_id=f"reddit:{tid}", url=media.canonical_url(url)), project_id)
            if existing and existing.get("status") == "ready" and not force:          # force = an explicit re-read (Reopen and capture more)
                if project_id:
                    identity.attach_existing(project_id, existing["id"])
                conn = db.connect()
                return {"source_id": existing["id"], "title": existing["title"], "identity": state, "already_ingested": True, "community": existing.get("channel"), "chunks": 0,
                        "posts": conn.execute("SELECT COUNT(*) FROM community_posts WHERE source_id=?", (existing["id"],)).fetchone()[0],
                        "substantive": conn.execute("SELECT COUNT(*) FROM community_posts WHERE source_id=? AND in_chunks=1", (existing["id"],)).fetchone()[0]}
            raise
    else:
        raise RuntimeError("no community adapter for this host yet (Reddit threads are supported; other communities can be added as pages)")
    terms = set(re.findall(r"[a-z][a-z0-9\-']{3,}", (query or "").lower())) or None
    out = store_thread(thread, tags=tags, project_id=project_id, query_terms=terms)
    if progress:
        progress(0.7, "embedding…")
    out["embedded"] = ingest._embed_ready(out["source_id"])
    ingest._after_ready(out["source_id"], project_id)
    try:
        from . import claims
        for cid in {r["claim_id"] for r in db.connect().execute("SELECT claim_id FROM claim_evidence WHERE source_id=?", (out["source_id"],))}:
            claims.assess(cid)
    except Exception:  # noqa: BLE001
        pass
    return out


def posts_of(source_id: str) -> list[dict[str, Any]]:
    rows = db.connect().execute("SELECT * FROM community_posts WHERE source_id=? ORDER BY ordinal", (source_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("claimed_context", "evidence_links"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    pass
        out.append(d)
    return out


def post_for_locator(source_id: str, ordinal: int) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM community_posts WHERE source_id=? AND ordinal=?", (source_id, int(ordinal))).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- missions (Evidence-Target-aware) and candidate discovery

REGRET_TERMS = ["regret", "wouldn't buy again", "biggest mistake", "unexpected cost", "downtime", "wish I knew", "went wrong", "lesson learned"]
PERSPECTIVE_TERMS = {"experiential": ["I own", "my experience", "after years", "lesson learned", "wouldn't do again"],
                     "expert": ["CPA here", "attorney here", "lender here", "professional opinion"],
                     "market": ["asking price", "sold for", "quoted", "my annual cost"],
                     "authoritative": ["SOP", "publication", "regulation", "statute"]}


def missions(project_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Community search missions from research STATE, not topics: open targets, MISSING_PERSPECTIVE / NOVEL / WEAK_CONSENSUS
    tensions, weak experiential Claims. Each mission carries the gap it serves and experience-language expansions."""
    from . import claims, knowledge
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, query: str, why: str, ref: dict[str, Any], terms: list[str]) -> None:
        q = " ".join(query.split())[:160]
        key = q.lower()
        if key in seen or len(out) >= limit:
            return
        seen.add(key)
        out.append({"kind": kind, "query": q, "why": why, "expansions": terms[:4], **ref})
    for t in knowledge.list_tensions(project_id, status="open"):
        if t["kind"] == "MISSING_PERSPECTIVE":
            ev = t.get("evidence") or {}
            missing = ev.get("missing") or []
            topic = ev.get("topic") or ""
            terms = (REGRET_TERMS if "experiential" in missing else []) + [x for m in missing for x in PERSPECTIVE_TERMS.get(m, [])] or REGRET_TERMS
            add("missing_perspective", f"{topic} {' '.join(terms[:2])}", t["description"][:160], {"tension_id": t["id"], "topic": topic, "missing": missing}, terms + REGRET_TERMS)
        elif t["kind"] in ("NOVEL", "WEAK_CONSENSUS") and t.get("claim_text"):
            add("corroborate", t["claim_text"][:120], f"{t['kind']}: needs independent firsthand reports", {"tension_id": t["id"], "claim_id": t.get("claim_id")}, ["I own", "my experience", "after years", "anyone else"])
    for tg in knowledge.list_targets(project_id, status="open"):
        if tg.get("sufficiency") == "corroborative":
            add("target", tg["question"][:140], f"open evidence target ({tg.get('closure') or ''})"[:160], {"target_id": tg["id"], "claim_id": tg.get("claim_id")}, ["experience", "lesson learned", "unexpected", "in practice"])
    for c in claims.list_for_project(project_id, with_evidence=False):
        if c["status"] != "rejected" and c["claim_type"] in ("experiential", "practice") and c["strength"] in ("weak", "developing"):
            add("strengthen", c["text"].split(" — ", 1)[-1][:120], f"{c['strength']} {c['claim_type']} Claim: independent firsthand reports can strengthen it", {"claim_id": c["id"]}, ["I own", "my experience", "unexpected", "biggest mistake"])
    return out


def _mission_terms(m: dict[str, Any]) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9\-']{3,}", (m["query"] + " " + " ".join(m.get("expansions") or [])).lower()))


def rank_candidates(rows: list[dict[str, Any]], mission: dict[str, Any]) -> list[dict[str, Any]]:
    """Cheap ranking of candidate threads against the MISSION: term coverage × experience language × substance; engagement
    is reported, never the ranking key."""
    terms = _mission_terms(mission)
    out = []
    for r in rows:
        meta = f"{r.get('title') or ''} {r.get('description') or ''}"
        toks = set(re.findall(r"[a-z][a-z0-9\-']{3,}", meta.lower()))
        cov = len(toks & terms) / max(1, len(terms))
        exp = 1.0 if EXPERIENCE.search(meta) else 0.0
        subst = min(1.0, len(meta) / 500)
        score = round(0.55 * cov + 0.3 * exp + 0.15 * subst, 3)
        out.append({**r, "mission_score": score, "coverage": round(cov, 2), "experience_language": bool(exp), "engagement": r.get("score") or r.get("view_count")})
    out.sort(key=lambda x: x["mission_score"], reverse=True)
    return out


def explore(community: str, project_id: str, mission: dict[str, Any] | None = None, *, limit: int = 25, query: str | None = None) -> dict[str, Any]:
    """Community → search → Candidate Threads (metadata only, into the Candidate Index) → ranked against the mission →
    Review. Nothing acquired here. Reddit today."""
    from . import candidates
    m = mission or {"kind": "manual", "query": query or "", "expansions": [], "why": "manual exploration"}
    q = query or m["query"]
    if community.startswith("r/") or "reddit.com" in community:
        sub = community.split("reddit.com/r/")[-1] if "reddit.com" in community else community
        rows = enumerate_reddit(sub, q, limit=limit)
        platform = "reddit"
    else:
        raise RuntimeError("no community adapter for that community yet")
    ids = candidates.remember([{k: v for k, v in r.items() if k in ("external_id", "url", "title", "description", "creator", "published_at", "view_count", "content_type")} for r in rows],
                              platform, project_id, {"kind": "community_search", "title": community, "query": q, "mission": m.get("kind")})
    ranked = rank_candidates(rows, m)
    for r, cid in zip(rows, ids):
        r["candidate_id"] = cid
    by_ext = {r["external_id"]: r for r in rows}
    for r in ranked:
        r["candidate_id"] = by_ext[r["external_id"]]["candidate_id"]
    db.kv_bump("community:explorations")
    return {"community": community, "query": q, "mission": m, "found": len(rows), "candidates": ranked, "note": "metadata only — nothing acquired; review and acquire the threads worth reading"}


# ---------------------------------------------------------------- cross-thread synthesis (derived, never primary evidence)

SEVERE = re.compile(r"\b(lawsuit|sued|bankrupt|lost (my|the|our) (business|deal|money|licen)|fraud|penalt(y|ies)|audit(ed)?|fine[ds]?\b|shut down|closed down|catastroph|"
                    r"crash|totaled|failed inspection|denied|revoked|foreclos)\b", re.I)


def synthesize(project_id: str) -> list[dict[str, Any]]:
    """Structured states over the project's experiential Claims that carry community evidence:
    FREQUENTLY_REPORTED (≥3 independent lines) · MIXED_EXPERIENCE (support and contradiction) · STRONG_DISAGREEMENT
    (contradictions ≥ support) · RARE_BUT_SERIOUS (one line, severe language) · FIRSTHAND_EXAMPLES (the rest). Every
    state keeps its evidence rows (source, locator, author, permalink). Stored in community_syntheses; recomputed each refresh."""
    from . import claims
    out = []
    t = time.time()
    comp_cache: dict[str, dict[str, Any] | None] = {}

    def comp_of(source_id: str) -> dict[str, Any] | None:
        if source_id not in comp_cache:
            src = db.get_source(source_id) or {}
            try:
                comp_cache[source_id] = json.loads(src["completeness"]) if src.get("completeness") else None
            except ValueError:
                comp_cache[source_id] = None
        return comp_cache[source_id]

    # P0 (docs/SPEED-AUDIT-2026-09-17.md §7): the walk over every Claim's evidence is reading and CPU, and it used to
    # run INSIDE the write transaction (3.5 s hold on Kyle's project, other writers queued behind it). The rows are
    # decided first; the DELETE + INSERTs are one short transaction at the end. Same rows, same order.
    rows: list[tuple] = []
    if True:                                                          # (indentation kept so the diff stays reviewable)
        for c in claims.list_for_project(project_id):
            if c["status"] in ("rejected", "superseded"):
                continue
            ev = c["evidence"]
            if not any(e.get("platform") == PLATFORM for e in ev):
                continue                                                   # only Claims that carry community evidence
            sup = [e for e in ev if e["relation"] in ("SUPPORTS", "EXPERIENTIAL") and not e.get("stale")]
            con = [e for e in ev if e["relation"] == "CONTRADICTS"]
            indep = len({(e["source_id"], e.get("locator")) for e in sup if e.get("independent")})     # a line = a post, not a thread
            severe = bool(SEVERE.search(c["text"]))
            if con and len(con) >= len(sup):
                kind = "STRONG_DISAGREEMENT"
            elif con:
                kind = "MIXED_EXPERIENCE"
            elif indep >= 3:
                kind = "FREQUENTLY_REPORTED"
            elif indep == 1 and severe:
                kind = "RARE_BUT_SERIOUS"
            else:
                kind = "FIRSTHAND_EXAMPLES"
            links = [{"source_id": e["source_id"], "locator": e.get("locator"), "link": e.get("link"), "relation": e["relation"], "independent": e.get("independent"), "title": e.get("title")} for e in ev]
            # B2: a state over threads the app only partly holds says so — unseen comments may hold the disagreement
            partial = []
            for src_id in {e["source_id"] for e in ev if e.get("platform") == PLATFORM}:
                cp = comp_of(src_id)
                if cp and cp.get("status") in ("partial", "unknown"):
                    partial.append({"source_id": src_id, "status": cp["status"], "captured": cp.get("captured"), "expected": cp.get("expected"), "title": next((e.get("title") for e in ev if e["source_id"] == src_id), None)})
            coverage = {"partial_threads": partial,
                        "note": ("based in part on partially captured threads (" + "; ".join(f"{p['captured']} of ~{p['expected']} comments" if p["expected"] else "comment count unknown" for p in partial)
                                 + ") — unseen comments may hold disagreement; this is not full-thread consensus") if partial else None}
            sid = db.new_id()
            rows.append((sid, project_id, kind, c["id"], c["text"][:300], indep, len(sup), len(con), json.dumps(links), t, json.dumps(coverage) if partial else None))
            out.append({"id": sid, "kind": kind, "claim_id": c["id"], "statement": c["text"][:300], "independent_lines": indep, "supporting": len(sup), "contradicting": len(con), "evidence": links,
                        "coverage": coverage if partial else None})
    with db.tx() as conn:
        conn.execute("DELETE FROM community_syntheses WHERE project_id=?", (project_id,))
        conn.executemany("INSERT INTO community_syntheses (id, project_id, kind, claim_id, statement, independent_lines, supporting, contradicting, evidence, created_at, coverage) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    order = {"RARE_BUT_SERIOUS": 0, "STRONG_DISAGREEMENT": 1, "MIXED_EXPERIENCE": 2, "FREQUENTLY_REPORTED": 3, "FIRSTHAND_EXAMPLES": 4}
    out.sort(key=lambda x: (order[x["kind"]], -x["independent_lines"]))
    return out


def syntheses(project_id: str) -> list[dict[str, Any]]:
    rows = db.connect().execute("SELECT * FROM community_syntheses WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["evidence"] = json.loads(d["evidence"] or "[]")
            d["coverage"] = json.loads(d["coverage"]) if d.get("coverage") else None
        except ValueError:
            pass
        out.append(d)
    return out


def stats() -> dict[str, Any]:
    conn = db.connect()
    return {"threads": conn.execute("SELECT COUNT(*) FROM sources WHERE platform=?", (PLATFORM,)).fetchone()[0],
            "posts": conn.execute("SELECT COUNT(*) FROM community_posts").fetchone()[0],
            "substantive": conn.execute("SELECT COUNT(*) FROM community_posts WHERE in_chunks=1").fetchone()[0],
            "corrections": conn.execute("SELECT COUNT(*) FROM community_posts WHERE corrected_by IS NOT NULL").fetchone()[0],
            "unavailable": conn.execute("SELECT COUNT(*) FROM community_posts WHERE availability='unavailable'").fetchone()[0],
            "explorations": int(db.kv_get("community:explorations") or 0),
            "reddit_api": reddit_api_configured()}
