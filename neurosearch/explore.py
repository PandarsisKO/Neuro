"""Rung G3 — website & collection exploration: turn a container into a ranked candidate set.

    RESOURCE → ENUMERATOR → CANDIDATES → canonical identity → Global Library check → CANDIDATE INDEX → project ranking → REVIEW → acquire | skip (retain)

Deterministic and cheap (Invariant G): sitemaps, sitemap indexes, RSS/Atom feeds, robots.txt, then (last) the home
page's own links — never a crawl of the domain. Everything is fetched through `safe_fetch` (J1 boundary). Nothing here
transcribes, reads or embeds a page; the output is metadata that becomes proposed sources (the existing review flow)
and Candidate Index entries (retained even when not selected). Bounds are explicit constants.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from . import candidates, db, identity, media
from .safe_fetch import FetchBlocked, safe_fetch

log = logging.getLogger(__name__)

MAX_ITEMS = 300               # candidates per exploration (the review pool); sitemaps beyond this are truncated, newest lastmod first
MAX_SITEMAPS = 25             # child sitemaps followed from a sitemap index
MAX_FEED_ITEMS = 500
HOME_LINKS_MAX = 200
FETCH_DEADLINE_S = 25.0
SKIP_PATH = re.compile(r"/(tag|tags|category|categories|author|page|wp-json|feed|login|signup|cart|checkout|search|privacy|terms|cookie|careers|jobs)(/|$)", re.I)
ASSET_EXT = (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".zip", ".mp4", ".mp3")


def _get(url: str, content_class: str = "html") -> bytes:
    r = safe_fetch(url, content_class=content_class, deadline_s=FETCH_DEADLINE_S)
    body = r.body
    if url.endswith(".gz") or r.content_type.startswith("application/gzip") or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body


def _text(el: ET.Element | None) -> str | None:
    return (el.text or "").strip() if el is not None and el.text else None


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _web_external_id(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", media.canonical_url(url)).rstrip("/")


def _humanize(url: str) -> str:
    seg = [s for s in urlparse(url).path.split("/") if s]
    last = seg[-1] if seg else urlparse(url).netloc
    last = re.sub(r"\.(html?|php|aspx?)$", "", last)
    return re.sub(r"[-_]+", " ", last).strip().capitalize() or url


# ------------------------------------------------------------------ enumerators

def enumerate_feed(url: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """RSS 2.0 / Atom. Podcast episodes (audio enclosures) become platform 'podcast' candidates keyed by GUID; blog
    entries become 'web' pages keyed by canonical URL."""
    root = ET.fromstring(_get(url))
    rt = _strip_ns(root.tag)
    entries: list[dict[str, Any]] = []
    if rt == "rss" or root.find("channel") is not None:
        ch = root.find("channel")
        title = _text(ch.find("title")) if ch is not None else None
        author = _text(ch.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}author")) if ch is not None else None
        for it in (ch.findall("item") if ch is not None else [])[:MAX_FEED_ITEMS]:
            enc = it.find("enclosure")
            link = _text(it.find("link"))
            guid = _text(it.find("guid")) or link or (enc.get("url") if enc is not None else None)
            media_url = enc.get("url") if enc is not None and (enc.get("type") or "").startswith(("audio/", "video/")) else None
            dur = _text(it.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}duration"))
            entries.append({"external_id": guid, "url": media_url or link, "page_url": link, "title": _text(it.find("title")),
                            "description": re.sub(r"<[^>]+>", " ", _text(it.find("description")) or "")[:2000] or None,
                            "published_at": _date(_text(it.find("pubDate"))), "duration": _duration(dur), "creator": author,
                            "platform": "podcast" if media_url else "web"})
    else:   # Atom
        title = _text(root.find("{http://www.w3.org/2005/Atom}title"))
        for it in root.findall("{http://www.w3.org/2005/Atom}entry")[:MAX_FEED_ITEMS]:
            links = it.findall("{http://www.w3.org/2005/Atom}link")
            alt = next((l.get("href") for l in links if l.get("rel") in (None, "alternate")), None)
            enc = next((l for l in links if l.get("rel") == "enclosure" and (l.get("type") or "").startswith(("audio/", "video/"))), None)
            entries.append({"external_id": _text(it.find("{http://www.w3.org/2005/Atom}id")) or alt, "url": (enc.get("href") if enc is not None else None) or alt, "page_url": alt,
                            "title": _text(it.find("{http://www.w3.org/2005/Atom}title")), "description": re.sub(r"<[^>]+>", " ", _text(it.find("{http://www.w3.org/2005/Atom}summary")) or "")[:2000] or None,
                            "published_at": _date(_text(it.find("{http://www.w3.org/2005/Atom}updated"))), "duration": None, "creator": None,
                            "platform": "podcast" if enc is not None else "web"})
    entries = [e for e in entries if e.get("external_id") and e.get("url")]
    for e in entries:
        if e["platform"] == "web":
            e["url"] = media.canonical_url(e["url"]); e["external_id"] = _web_external_id(e["url"])
    return {"id": url, "url": url, "title": title or url, "kind": "feed"}, entries


def enumerate_sitemap(url: str, limit: int = MAX_ITEMS, _depth: int = 0, _seen: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """urlset → pages; sitemapindex → follow up to MAX_SITEMAPS children. Newest lastmod first, capped at `limit`."""
    seen = _seen if _seen is not None else set()
    root = ET.fromstring(_get(url))
    rt = _strip_ns(root.tag)
    out: list[dict[str, Any]] = []
    if rt == "sitemapindex":
        children = [_text(sm.find("{*}loc")) or _text(sm.find("loc")) for sm in root.findall("{*}sitemap") + root.findall("sitemap")]
        for child in [c for c in children if c][:MAX_SITEMAPS]:
            if child in seen or _depth >= 2:
                continue
            seen.add(child)
            try:
                _, part = enumerate_sitemap(child, limit, _depth + 1, seen)
                out.extend(part)
            except (FetchBlocked, ET.ParseError, RuntimeError, OSError) as e:      # fail OPEN for discovery: one bad child never sinks the pass
                log.info("sitemap child skipped %s: %s", child, e)
            if len(out) >= limit * 3:
                break
    else:
        for u in root.findall("{*}url") + root.findall("url"):
            loc = _text(u.find("{*}loc")) or _text(u.find("loc"))
            if not loc or loc.lower().endswith(ASSET_EXT) or SKIP_PATH.search(urlparse(loc).path):
                continue
            out.append({"external_id": _web_external_id(loc), "url": media.canonical_url(loc), "title": _humanize(loc), "description": None,
                        "published_at": _date(_text(u.find("{*}lastmod")) or _text(u.find("lastmod"))), "duration": None, "creator": urlparse(loc).netloc, "platform": "web"})
    out.sort(key=lambda e: e.get("published_at") or "", reverse=True)
    dedup: dict[str, dict[str, Any]] = {}
    for e in out:
        dedup.setdefault(e["external_id"], e)
    return {"id": url, "url": url, "title": urlparse(url).netloc, "kind": "sitemap"}, list(dedup.values())[:limit]


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._cur: str | None = None
        self._buf: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._cur, self._buf = href, []
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data):
        if self._cur is not None:
            self._buf.append(data)
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "a" and self._cur is not None:
            self.links.append((self._cur, " ".join("".join(self._buf).split())[:200]))
            self._cur = None
        elif tag == "title":
            self._in_title = False


def enumerate_website(url: str, limit: int = MAX_ITEMS) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """robots.txt Sitemap: → sitemap(s); else /sitemap.xml; else the home page's own same-host links (bounded). The
    section a user pointed at (irs.gov/forms-instructions/) narrows sitemap entries to that path prefix when it yields
    enough, otherwise the section page's links are used."""
    base = media.canonical_url(url)
    u = urlparse(base)
    origin = f"{u.scheme}://{u.netloc}"
    prefix = u.path.rstrip("/")
    how = []
    sitemaps: list[str] = []
    try:
        robots = _get(origin + "/robots.txt").decode("utf-8", "replace")
        sitemaps = [ln.split(":", 1)[1].strip() for ln in robots.splitlines() if ln.lower().startswith("sitemap:")][:MAX_SITEMAPS]
        if sitemaps:
            how.append("robots.txt")
    except (FetchBlocked, RuntimeError, OSError):
        pass
    if not sitemaps:
        sitemaps = [origin + "/sitemap.xml"]
    entries: list[dict[str, Any]] = []
    for sm in sitemaps:
        try:
            _, part = enumerate_sitemap(sm, limit * 4)
            entries.extend(part)
            how.append("sitemap")
        except (FetchBlocked, ET.ParseError, RuntimeError, OSError) as e:
            log.info("no usable sitemap at %s: %s", sm, e)
        if len(entries) >= limit * 4:
            break
    if prefix:
        narrowed = [e for e in entries if urlparse(e["url"]).path.startswith(prefix)]
        if len(narrowed) >= 5:
            entries = narrowed
            how.append(f"section {prefix}")
        else:
            entries = []                                             # the sitemap does not cover the section: use the section page's links
    if not entries:
        try:
            html = _get(base).decode("utf-8", "replace")
        except (FetchBlocked, RuntimeError, OSError) as e:
            raise RuntimeError(f"could not read {base}: {e}") from e
        p = _Links(); p.feed(html)
        seen: set[str] = set()
        for href, text in p.links:
            full = urljoin(base, href.split("#")[0])
            v = urlparse(full)
            if v.scheme not in ("http", "https") or v.netloc.lower().replace("www.", "") != u.netloc.lower().replace("www.", ""):
                continue
            if v.path.lower().endswith(ASSET_EXT) or SKIP_PATH.search(v.path) or (prefix and not v.path.startswith(prefix)):
                continue
            ext = _web_external_id(full)
            if ext in seen or ext == _web_external_id(base):
                continue
            seen.add(ext)
            entries.append({"external_id": ext, "url": media.canonical_url(full), "title": text or _humanize(full), "description": None,
                            "published_at": None, "duration": None, "creator": u.netloc, "platform": "web"})
            if len(entries) >= HOME_LINKS_MAX:
                break
        how.append("page links")
    dedup: dict[str, dict[str, Any]] = {}
    for e in entries:
        dedup.setdefault(e["external_id"], e)
    return {"id": base, "url": base, "title": u.netloc + (prefix or ""), "kind": "website", "how": " → ".join(how) or "none"}, list(dedup.values())[:limit]


def _date(s: str | None) -> str | None:
    if not s:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        return m.group(1) if m else None


def _duration(s: str | None) -> float | None:
    if not s:
        return None
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        return None
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


# ------------------------------------------------------------------ the exploration job

ENUMERATORS = {"feed": enumerate_feed, "sitemap": enumerate_sitemap, "website": enumerate_website, "website_section": enumerate_website}


def explore(url: str, kind: str, project_id: str | None, *, tags: list[str] | None = None, max_items: int | None = None,
            progress: Any = None) -> dict[str, Any]:
    """Enumerate a container into proposed sources (review flow) + Candidate Index entries. Runs as the `explore` job."""
    progress = progress or (lambda p, m: None)
    fn = ENUMERATORS.get(kind)
    if not fn:
        raise RuntimeError(f"no explorer for {kind}")
    progress(0.05, f"exploring {kind}…")
    info, entries = fn(url) if kind != "sitemap" else fn(url, max_items or MAX_ITEMS)
    if max_items:
        entries = entries[:max_items]
    if not entries:
        raise RuntimeError(f"nothing to list at {url} (no sitemap, feed or links found)")
    coll = db.upsert_collection(info["kind"], info["id"], info["url"], info.get("title"))
    if project_id:
        db.add_project_collections(project_id, [coll["id"]])
    want = max_items or (db.get_project(project_id) or {}).get("default_max_videos") if project_id else None
    from .config import settings
    want = want or settings.default_max_videos
    counts = {"already_in_project": 0, "already_in_library": 0, "new": 0}
    member_ids = set(db.project_source_ids(project_id, ready_only=False)) if project_id else set()
    proposed = skipped = 0
    origin = {"collection_id": coll["id"], "kind": info["kind"], "title": info.get("title"), "how": info.get("how")}
    with db.batch():
        for i, e in enumerate(entries):
            platform = e.get("platform") or "web"
            cand = identity.Candidate(platform=platform, external_id=e["external_id"], url=e["url"], title=e.get("title"),
                                      canonical_url=e["url"] if platform == "web" else None, tags=list(tags or []),
                                      fields={"description": e.get("description"), "published_at": e.get("published_at"), "duration": e.get("duration"), "channel": e.get("creator")})
            res = identity.resolve_or_create_source(cand, None, initial_status="proposed", resume_skipped=False)
            src = res.source
            db.link_source_collection(src["id"], coll["id"])
            if src["id"] in member_ids:
                counts["already_in_project"] += 1
            elif res.state == identity.NEW:
                counts["new"] += 1
            else:
                counts["already_in_library"] += 1
            if src["status"] == "proposed":
                proposed += 1
            else:
                skipped += 1
            e["source_id"] = src["id"] if src["status"] == "ready" else None
            if i % 50 == 49:
                progress(0.1 + 0.8 * i / len(entries), f"listed {i + 1}/{len(entries)}")
    # the Candidate Index remembers every entry (cheaply), whatever the review decides later
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_platform.setdefault(e.get("platform") or "web", []).append({**e, "canonical_url": e["url"] if (e.get("platform") or "web") == "web" else None})
    for platform, items in by_platform.items():
        candidates.remember(items, platform, project_id, origin)
    meta = {"min_date": None, "newest_first": True, "project_id": project_id, "max_videos": want, "ranked": False, "counts": counts,
            "kind": info["kind"], "how": info.get("how")}
    if proposed:
        db.kv_set(f"review:{coll['id']}", json.dumps(meta))
        db.create_job("rank_proposed", {"collection_id": coll["id"], "project_id": project_id, "want": want})
    return {"kind": info["kind"], "collection_id": coll["id"], "title": info.get("title"), "found": len(entries), "proposed": proposed,
            "already_ingested": skipped, "counts": counts, "how": info.get("how"), "review": proposed > 0}
