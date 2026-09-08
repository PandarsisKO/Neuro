"""Web pages / articles as sources: fetch, strip the chrome, split into numbered sections.

Sections play the role pages play for documents: segments and chunks carry start/end = section number,
and citations render as '§ 3'. A PDF URL is handed to the document extractor instead.
"""
from __future__ import annotations

import html
import logging
import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MEDIA_EXT = (".mp3", ".m4a", ".wav", ".mp4", ".mov", ".m4v", ".webm", ".ogg", ".aac", ".flac")
MEDIA_HOSTS = ("vimeo.com", "loom.com", "soundcloud.com", "spotify.com", "podcasts.apple.com", "anchor.fm",
               "buzzsprout.com", "libsyn.com", "twitch.tv", "tiktok.com", "rumble.com", "dailymotion.com",
               "wistia.com", "facebook.com", "fb.watch", "x.com", "twitter.com", "podbean.com", "simplecast.com",
               "transistor.fm", "megaphone.fm", "spreaker.com", "castos.com", "captivate.fm")
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe", "button", "template"}
BLOCK_TAGS = {"p", "div", "li", "br", "tr", "td", "th", "section", "article", "blockquote", "pre", "dd", "dt", "figcaption"}
HEAD_TAGS = {"h1", "h2", "h3", "h4"}
SECTION_MIN, SECTION_MAX = 900, 4500


def looks_like_media(url: str) -> bool:
    u = urlparse(url)
    host = u.netloc.lower()
    if u.path.lower().endswith(MEDIA_EXT):
        return True
    return any(host == h or host.endswith("." + h) for h in MEDIA_HOSTS)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []   # (kind, text)  kind = 'h' | 'p'
        self._skip = 0
        self._cur: list[str] = []
        self._kind = "p"
        self.title = ""
        self._in_title = False

    def _flush(self) -> None:
        t = " ".join("".join(self._cur).split())
        if t:
            self.blocks.append((self._kind, t))
        self._cur, self._kind = [], "p"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
        if tag in HEAD_TAGS:
            self._flush(); self._kind = "h"
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
        if not self._skip and (tag in HEAD_TAGS or tag in BLOCK_TAGS):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self._cur.append(data)


def extract_sections(html_text: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (title, [{page: n, text: str}]) — headings start new sections; tiny sections are merged."""
    ex = _Extractor()
    ex.feed(html_text)
    ex._flush()
    # main-content heuristic: drop very short blocks that look like menus, keep the rest
    blocks = [(k, t) for k, t in ex.blocks if k == "h" or len(t) > 40 or t.endswith((".", "?", "!", ":"))]
    sections: list[str] = []
    cur = ""
    for k, t in blocks:
        if k == "h" and len(cur) >= SECTION_MIN:
            sections.append(cur.strip()); cur = ""
        piece = (f"\n\n## {t}\n\n" if k == "h" else t + "\n\n")
        if len(cur) + len(piece) > SECTION_MAX and cur:
            sections.append(cur.strip()); cur = ""
        cur += piece
    if cur.strip():
        sections.append(cur.strip())
    # merge trailing tiny sections
    merged: list[str] = []
    for s in sections:
        if merged and len(merged[-1]) < SECTION_MIN:
            merged[-1] += "\n\n" + s
        else:
            merged.append(s)
    title = " ".join(ex.title.split())
    return title, [{"page": i + 1, "text": s} for i, s in enumerate(merged)]


HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
}


from .acquire import AcquisitionFailure, classify_page  # noqa: E402


class Blocked(AcquisitionFailure):
    """The site refused an automated reader (403/401/429/challenge page). A classified, browser-solvable failure (B1):
    the job that hit it becomes a browser-capture request instead of a dead end."""

    def __init__(self, message: str, *, cls: str = "blocked", detail: str | None = None) -> None:
        super().__init__(message, adapter="web_page", cls=cls, detail=detail)


def fetch(url: str, timeout: float = 60.0) -> tuple[str, str, bytes]:
    """GET the URL through the J1 network boundary (`safe_fetch`: public addresses only, pinned connection, manual
    revalidated redirects, streamed size/decoded limits, total deadline). Returns (final_url, content_type, body).
    A refused destination raises safe_fetch.FetchBlocked (typed reason, user-safe message)."""
    from .safe_fetch import safe_fetch
    r = safe_fetch(url, deadline_s=timeout)
    if r.status in (401, 403, 429, 503):
        cls = classify_page(r.status, r.body[:4000].decode("utf-8", errors="replace")) or "blocked"
        raise Blocked(f"{urlparse(url).netloc} blocks automated readers (HTTP {r.status}). "
                      "Open the page in Chrome and use the Neuro Search extension → 'Send this page', "
                      "or copy the text into Sources → Paste text.", cls=cls, detail=f"HTTP {r.status}")
    if r.status == 404:
        raise AcquisitionFailure(f"HTTP 404 — nothing at that address on {urlparse(r.url).netloc}", adapter="web_page", cls="not_found")
    if r.status >= 400:
        raise AcquisitionFailure(f"HTTP {r.status} fetching {urlparse(r.url).netloc}", adapter="web_page", cls="http_error", detail=f"HTTP {r.status}")
    return r.url, r.content_type, r.body


def LOGIN_OR_CHALLENGE(head: str) -> str | None:
    """A 200 that is really a wall: 'login_wall' | 'challenge' | None."""
    from .acquire import CHALLENGE, LOGIN_WALL
    if LOGIN_WALL.search(head):
        return "login_wall"
    if CHALLENGE.search(head):
        return "challenge"
    return None


def read_page(url: str, html_text: str | None = None) -> dict[str, Any]:
    """Fetch (or use the supplied HTML) and section a page.
    Returns {title, url, pages, kind} where kind is 'webpage' or 'document' (PDF)."""
    if html_text is not None:
        title, pages = extract_sections(html_text)
        if not pages or sum(len(p["text"]) for p in pages) < 200:
            wall = LOGIN_OR_CHALLENGE(html_text[:6000] + " " + " ".join(p["text"] for p in pages))
            if wall:
                raise Blocked(f"{urlparse(url).netloc} answered with a sign-in or verification page instead of the content.", cls=wall)
            raise AcquisitionFailure("no readable text on that page (it may need JavaScript or a login)", adapter="web_page", cls="js_required")
        return {"title": html.unescape(title) or url, "url": url, "pages": pages, "kind": "webpage"}
    final, ctype, body = fetch(url)
    if "pdf" in ctype or final.lower().split("?")[0].endswith(".pdf"):
        from .documents import extract_pages
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(body)
            p = Path(fh.name)
        try:
            pages = extract_pages(p)
        finally:
            p.unlink(missing_ok=True)
        name = urlparse(final).path.rsplit("/", 1)[-1] or "document.pdf"
        return {"title": name, "url": final, "pages": pages, "kind": "document"}
    text = body.decode("utf-8", errors="replace")
    title, pages = extract_sections(text)
    if not pages or sum(len(p["text"]) for p in pages) < 200:
        wall = LOGIN_OR_CHALLENGE(text[:6000] + " " + " ".join(p["text"] for p in pages))     # a thin page that is really a wall
        if wall:
            raise Blocked(f"{urlparse(final).netloc} answered with a sign-in or verification page instead of the content.", cls=wall)
        raise AcquisitionFailure("no readable text on that page (it may need JavaScript or a login)", adapter="web_page", cls="js_required")
    return {"title": html.unescape(title) or final, "url": final, "pages": pages, "kind": "webpage"}
