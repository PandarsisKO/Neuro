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


def _old_reddit_html(url: str) -> str:
    """The server-rendered page on old.reddit.com, requested exactly as a browser navigation (the one representation Reddit
    serves to a plain client without login). Raises with the status when even that is refused."""
    from .safe_fetch import safe_fetch
    u = url.replace("://www.reddit.com", "://old.reddit.com", 1).replace("://reddit.com", "://old.reddit.com", 1)
    res = safe_fetch(u, content_class="html", headers={"User-Agent": BROWSER_UA})
    if res.status != 200:
        raise RuntimeError(f"old.reddit.com: HTTP {res.status}")
    return res.body.decode("utf-8", errors="replace")


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


def read_reddit_thread(url: str) -> dict[str, Any]:
    """Reddit's public listing endpoint (no login): the post + the comment forest, with ids, parents, authors, scores,
    edited/deleted flags. When Reddit refuses the JSON to a non-browser client (it does, even for public threads), the
    same thread is read from old.reddit.com's server-rendered page (`reddit_html.thread_from_html`) — same shape."""
    try:
        data = _json_get(_reddit_json_url(url))
    except RuntimeError as e:
        from . import reddit_html
        try:
            html = _old_reddit_html(_reddit_html_url(url))
            return reddit_html.thread_from_html(html, url, max_posts=MAX_POSTS)
        except RuntimeError as e2:
            raise RuntimeError(f"{e}; server-rendered page: {e2}") from e
    if not isinstance(data, list) or len(data) < 1:
        raise RuntimeError("unexpected Reddit response")
    link = data[0]["data"]["children"][0]["data"]
    posts: list[dict[str, Any]] = []
    op_id = link["id"]
    posts.append({"post_id": op_id, "parent_id": None, "depth": 0, "author": link.get("author"), "score": link.get("score"),
                  "created": link.get("created_utc"), "edited": bool(link.get("edited")), "deleted": link.get("author") in ("[deleted]", None) and not link.get("selftext"),
                  "text": (link.get("title") or "") + ("\n\n" + link["selftext"] if link.get("selftext") else ""), "kind": "post",
                  "permalink": "https://www.reddit.com" + link.get("permalink", "")})

    def walk(children: list[dict[str, Any]], parent: str, depth: int) -> None:
        for ch in children:
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
            "created": link.get("created_utc"), "score": link.get("score"), "num_comments": link.get("num_comments"), "posts": posts, "retrieved_at": time.time()}


def enumerate_reddit(community: str, query: str, *, limit: int = 25, sort: str = "relevance", time_filter: str = "all") -> list[dict[str, Any]]:
    """Candidate threads for a mission: cheap metadata (title, excerpt, score, comments, date) — nothing acquired."""
    sub = community.replace("r/", "").strip("/")
    from urllib.parse import quote
    url = f"https://www.reddit.com/r/{quote(sub)}/search.json?q={quote(query)}&restrict_sr=1&sort={sort}&t={time_filter}&limit={min(limit, 100)}&raw_json=1"
    try:
        data = _json_get(url)
    except RuntimeError as e:
        from . import reddit_html
        try:
            html = _old_reddit_html(f"https://www.reddit.com/r/{quote(sub)}/search?q={quote(query)}&restrict_sr=on&sort={sort}&t={time_filter}")
            return reddit_html.search_from_html(html, sub)[:limit]
        except RuntimeError as e2:
            raise RuntimeError(f"{e}; server-rendered page: {e2}") from e
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


def store_thread(thread: dict[str, Any], *, tags: list[str] | None = None, project_id: str | None = None, query_terms: set[str] | None = None) -> dict[str, Any]:
    """Thread → ONE global source (platform 'community', external_id '<platform>:<thread_id>'), the full post tree in
    community_posts, and chunks for the pruned high-signal posts (locator = post ordinal; deep link = permalink)."""
    from . import identity, media
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
        for row in conn.execute("SELECT post_id FROM community_posts WHERE source_id=?", (src["id"],)).fetchall():
            if row["post_id"] not in seen_ids:                            # previously retrieved, now gone → unavailable, never silently dropped
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
        db.upsert_source(platform=PLATFORM, external_id=ext, title=thread["title"], url=url, transcript_kind="community", channel=thread.get("community"),
                         description=f"{thread.get('community') or thread['platform']} thread · {len(posts)} posts ({len(kept)} substantive) · {thread.get('score')} points",
                         status="ready", error=None)
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
            "firsthand": sum(1 for p in kept if p["signals"]["firsthand"]), "community": thread.get("community")}


def acquire_thread(url: str, *, tags: list[str] | None = None, project_id: str | None = None, progress: Any = None, query: str | None = None) -> dict[str, Any]:
    """Acquire one community thread as a Source through the standard identity/revision path. Reddit today; other adapters
    plug in here by host."""
    from . import ingest
    if progress:
        progress(0.1, "reading the thread…")
    if is_reddit_thread(url):
        thread = read_reddit_thread(url)
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
    with db.tx() as conn:
        conn.execute("DELETE FROM community_syntheses WHERE project_id=?", (project_id,))
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
            sid = db.new_id()
            conn.execute("INSERT INTO community_syntheses (id, project_id, kind, claim_id, statement, independent_lines, supporting, contradicting, evidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (sid, project_id, kind, c["id"], c["text"][:300], indep, len(sup), len(con), json.dumps(links), t))
            out.append({"id": sid, "kind": kind, "claim_id": c["id"], "statement": c["text"][:300], "independent_lines": indep, "supporting": len(sup), "contradicting": len(con), "evidence": links})
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
            "explorations": int(db.kv_get("community:explorations") or 0)}
