"""Rung G2 — universal resource input: understand what the user supplied BEFORE deciding what pipeline to run.

    INPUT  →  classify()  →  Classification(kind, actions)  →  route(choice)  →  the standard source / collection lifecycle

Kinds (Invariant F — containers and items behave differently):

    item        page · document · spreadsheet · image · video · media · instagram_post
    collection  channel · playlist · feed · sitemap · folder
    container   website · website_section · repository · community · instagram_profile
    request     search_query (free text) · work_identity (ISBN / DOI)

Deterministic: host and path shapes only, no network, no model. A container never falls through to the naive
"fetch this URL as a page" path: the user (or the caller) chooses `page` (add this address as one page) or
`explore` (enumerate it — Rung G3; until it ships the action is reported as unavailable, never faked).
Every route ends in an existing entrance (`ingest_url`, Discover), so every resulting source passes G1 identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import media

ITEM_KINDS = ("page", "document", "spreadsheet", "image", "video", "media", "instagram_post")
COLLECTION_KINDS = ("channel", "playlist", "feed", "sitemap", "folder", "subreddit")
CONTAINER_KINDS = ("website", "website_section", "repository", "community", "instagram_profile")
REQUEST_KINDS = ("search_query", "work_identity")
KINDS = ITEM_KINDS + COLLECTION_KINDS + CONTAINER_KINDS + REQUEST_KINDS

EXPLORABLE_NOW: tuple[str, ...] = ("channel", "playlist", "instagram_profile", "website", "website_section", "sitemap", "feed", "subreddit")
EXPLORE_LATER: tuple[str, ...] = ("repository", "community", "folder")   # repository: G3 follow-up · community: G7

DOC_EXT = (".pdf", ".docx", ".doc", ".pptx", ".txt", ".md", ".rtf", ".epub")
SHEET_EXT = (".xlsx", ".xlsm", ".csv", ".tsv")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff", ".bmp", ".heic")
COMMUNITY_HOSTS = ("reddit.com", "old.reddit.com", "news.ycombinator.com", "lemmy.world", "discourse.org", "stackexchange.com", "stackoverflow.com", "quora.com")
REPO_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")
SECTION_PATHS = {"blog", "news", "articles", "posts", "resources", "publications", "topics",
                 "categories", "archive", "archives", "docs", "documentation", "forms-instructions"}
URL_RE = re.compile(r"^(https?://)?([a-z0-9-]+\.)+[a-z]{2,}(/[^\s]*)?$", re.I)
ISBN_RE = re.compile(r"^(?:isbn[:\s-]*)?((?:97[89][- ]?)?(?:\d[- ]?){9}[\dXx])$", re.I)
DOI_RE = re.compile(r"^(?:doi[:\s]*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)$", re.I)


@dataclass
class Classification:
    kind: str
    input: str
    url: str | None = None
    identifier: str | None = None                 # ISBN / DOI / search text
    label: str = ""                               # "Website detected", "Book detected"…
    detail: str = ""                              # plain-language explanation for the UI / chat
    actions: list[dict[str, Any]] = field(default_factory=list)    # [{action, label, available, note?}]
    default_action: str | None = None
    host: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "input": self.input, "url": self.url, "identifier": self.identifier, "label": self.label,
                "detail": self.detail, "actions": self.actions, "default_action": self.default_action, "host": self.host,
                "is_container": self.kind in CONTAINER_KINDS or self.kind in COLLECTION_KINDS}


def _act(action: str, label: str, available: bool = True, note: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"action": action, "label": label, "available": available}
    if note:
        d["note"] = note
    return d


def _isbn_ok(digits: str) -> bool:
    d = digits.upper()
    if len(d) == 10:
        if not (d[:9].isdigit() and (d[9].isdigit() or d[9] == "X")):
            return False
        s = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d))
        return s % 11 == 0
    if len(d) == 13 and d.isdigit():
        s = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d))
        return s % 10 == 0
    return False


def classify(text: str) -> Classification:
    raw = (text or "").strip()
    if not raw:
        return Classification("search_query", raw, label="Nothing to add", detail="Paste a link, upload a file, or describe what you're looking for.", actions=[])
    # --- identifiers before URLs (a DOI may arrive as a doi.org URL). G6: any canonical identifier — ISBN, DOI, SOP number,
    # IRS publication, statute / CFR citation, form number — is a Work identity and goes to the Source Resolver ($0).
    from . import works as _works
    if not raw.lower().startswith(("http://", "https://")) or "doi.org" in raw.lower():
        ids = _works.extract_identifiers(raw)
        if ids and len(raw) <= 120:
            i = ids[0]
            kind_label = {"sop": "SBA SOP", "publication": "IRS publication", "statute": "Statute", "regulation": "Regulation", "form": "Form", "paper": "Paper", "book": "Book"}.get(i["kind"], "Work")
            return Classification("work_identity", raw, url=i.get("url"), identifier=f"{i['scheme']}:{i['value']}", label=f"{kind_label} detected ({i['family']}{' ' + i['version'] if i.get('version') else ''})",
                                  detail=f"{i['title']} is a Work, not a URL. The resolver checks what you already own (this project, then the global library), then anything seen but not acquired, before any acquisition.",
                                  actions=[_act("resolve", "Find an available copy")] + ([_act("acquire", "Acquire the official document")] if i.get("url") and i["kind"] in _works.REGULATORY_KINDS else [])
                                  + ([_act("page", "Add the landing page")] if i.get("url") and i["kind"] not in _works.REGULATORY_KINDS else []) + [_act("upload", "Upload a copy")],
                                  default_action="resolve")
    # --- not a URL: a research request
    is_url = raw.lower().startswith(("http://", "https://")) or (" " not in raw and bool(URL_RE.match(raw)))
    if not is_url:
        return Classification("search_query", raw, identifier=raw, label="Research request",
                              detail="Not a link — Discover will look for sources that answer it (your library first, then the web).",
                              actions=[_act("discover", "Discover sources for this")], default_action="discover")
    url = raw if raw.lower().startswith(("http://", "https://")) else "https://" + raw
    url = media.canonical_url(url)
    u = urlparse(url)
    host = u.netloc.lower()
    path = u.path or "/"
    low = path.lower()
    segs = [s for s in path.split("/") if s]
    # --- platforms the media layer already understands
    mk = media.classify_url(url)
    if mk == "video":
        return Classification("video", raw, url=url, label="Video detected", detail="A single video: captions or transcription, then findings.", actions=[_act("ingest", "Add video")], default_action="ingest", host=host)
    if mk == "playlist":
        return Classification("playlist", raw, url=url, label="Playlist detected", detail="Listed first; you approve which videos to ingest.", actions=[_act("explore", "List for review")], default_action="explore", host=host)
    if mk == "channel":
        return Classification("channel", raw, url=url, label="Channel detected", detail="Listed first; you approve which videos to ingest.", actions=[_act("explore", "List for review")], default_action="explore", host=host)
    if mk == "youtube_search":
        return Classification("search_query", raw, url=url, identifier=media.search_query_of(url), label="YouTube search detected",
                              detail="The top results are listed for review, like a playlist.", actions=[_act("explore", "List results for review")], default_action="explore", host=host)
    if mk == "instagram":
        return Classification("instagram_post", raw, url=url, label="Instagram post detected", detail="A single reel/post.", actions=[_act("ingest", "Add post")], default_action="ingest", host=host)
    if mk == "instagram_profile":
        return Classification("instagram_profile", raw, url=url, label="Instagram profile detected",
                              detail="Profiles are listed with your own session via the extension (Send this page), max 40 posts.",
                              actions=[_act("explore", "List with the extension", False, "open the profile in Chrome and use the extension → Send this page")], default_action=None, host=host)
    if mk == "fixture":
        return Classification("video", raw, url=url, label="Fixture", actions=[_act("ingest", "Add")], default_action="ingest", host=host)
    # --- repositories
    if any(host == h or host.endswith("." + h) for h in REPO_HOSTS):
        if len(segs) >= 2 and (len(segs) == 2 or segs[2] in ("tree", "")):
            return Classification("repository", raw, url=url, label="Repository detected", detail="A code repository is a collection: relevant files are explored, not fetched as one page.",
                                  actions=[_act("explore", "Explore relevant files", False, "Repository exploration ships in Rung G3"), _act("page", "Add the repository page only")], default_action="page", host=host)
        return Classification("page", raw, url=url, label="Repository file/page detected", detail="One page from a repository.", actions=[_act("page", "Add page")], default_action="page", host=host)
    # --- communities
    # A subreddit is a reusable catalog, distinct from both an individual Reddit thread and the broad
    # cross-platform "community" container. Canonicalizing here makes pasted URL variants converge before
    # any database write or future scan.
    if host in ("reddit.com", "www.reddit.com", "old.reddit.com"):
        from . import community
        subreddit = community.subreddit_name(url)
        if subreddit:
            canonical = community.subreddit_url(subreddit)
            return Classification("subreddit", raw, url=canonical, identifier=subreddit, label="Subreddit detected",
                                  detail="A subreddit is a reusable catalog. Posts are remembered for review; no discussion is read until you capture it.",
                                  actions=[_act("explore", "Set up catalog")], default_action="explore", host=host)
    if any(host == h or host.endswith("." + h) for h in COMMUNITY_HOSTS):
        is_thread = "/comments/" in low or "item?id=" in (u.query or "") or "/questions/" in low or "/t/" in low
        if not is_thread:
            return Classification("community", raw, url=url, label="Community detected", detail="A community is explored for high-signal threads, never ingested as a homepage.",
                                  actions=[_act("explore", "Explore discussions", False, "Community exploration ships in Rung G7")], default_action=None, host=host)
        return Classification("page", raw, url=url, label="Discussion thread detected", detail="One thread, read as a page (experiential evidence, not authority).",
                              actions=[_act("page", "Add thread")], default_action="page", host=host)
    # --- files by extension
    if low.endswith(DOC_EXT):
        return Classification("document", raw, url=url, label="Document detected", detail="Read as a document (citations point at page numbers).", actions=[_act("ingest", "Add document")], default_action="ingest", host=host)
    if low.endswith(SHEET_EXT):
        return Classification("spreadsheet", raw, url=url, label="Spreadsheet detected", detail="Download it and upload the file to get sheets as pages and a calculator.",
                              actions=[_act("ingest", "Add as a page", True, "the link is fetched as a page; upload the file for a calculator"), _act("upload", "Upload the file")], default_action="upload", host=host)
    if low.endswith(IMAGE_EXT):
        return Classification("image", raw, url=url, label="Image detected", detail="Visual evidence (charts, scans, screenshots) becomes citable in a later rung (Multimodal Evidence).",
                              actions=[_act("ingest", "Add", False, "images are not evidence yet — Rung 8")], default_action=None, host=host)
    # --- feeds and sitemaps
    if "sitemap" in low and (low.endswith(".xml") or low.endswith(".xml.gz")):
        return Classification("sitemap", raw, url=url, label="Sitemap detected", detail="A list of the site's pages: listed (newest first), ranked against your brief, and reviewed before anything is read.",
                              actions=[_act("explore", "List pages for review")], default_action="explore", host=host)
    if low.endswith((".rss", ".atom", "/feed", "/feed/", "/rss", "/rss/", "feed.xml", "rss.xml", "atom.xml")) or parse_qs(u.query).get("format", [""])[0] in ("rss", "atom"):
        return Classification("feed", raw, url=url, label="Feed detected", detail="An RSS/Atom feed (podcast or blog): episodes/posts are listed for review, nothing is downloaded until you approve.",
                              actions=[_act("explore", "List episodes for review")], default_action="explore", host=host)
    # --- generic media hosts
    if mk == "media":
        return Classification("media", raw, url=url, label="Media detected", detail="Audio/video from a supported host: transcribed.", actions=[_act("ingest", "Add media")], default_action="ingest", host=host)
    # --- websites vs pages
    if not segs and not u.query:
        return Classification("website", raw, url=url, label="Website detected",
                              detail=f"{host} is a whole site. Explore lists its pages (sitemap first, never a crawl), ranks them against your brief and lets you pick; or add just the home page.",
                              actions=[_act("explore", "Explore website"), _act("page", "Add home page only")], default_action="explore", host=host)
    # A shallow path (even with a trailing slash) can be a complete article.
    # Only recognizable section names justify enumerating instead of reading it.
    if len(segs) == 1 and segs[0].lower() in SECTION_PATHS and not u.query:
        return Classification("website_section", raw, url=url, label="Website section detected",
                              detail=f"A section of {host}. Explore lists the pages under it for review, or add just this page.",
                              actions=[_act("explore", "Explore section"), _act("page", "Add this page only")], default_action="explore", host=host)
    return Classification("page", raw, url=url, label="Web page detected", detail="Fetched and read as an article; sections are cited as § N.",
                          actions=[_act("page", "Add page")], default_action="page", host=host)


def classify_many(text: str) -> list[Classification]:
    """A pasted block: one classification per line/comma-separated entry (a multi-word line is one research request)."""
    parts = [p.strip() for p in re.split(r"[\n,]+", text or "") if p.strip()]
    if len(parts) > 1 and all(" " in p and not URL_RE.match(p) for p in parts):
        parts = [text.strip()]
    return [classify(p) for p in parts]


def route(c: Classification, project_id: str | None, action: str | None = None, *, tags: list[str] | None = None,
          since_years: float | None = None, max_videos: int | None = None, force: bool = False) -> dict[str, Any]:
    """Turn a classification + chosen action into work on the STANDARD paths. Returns {action, kind, job_id? | note}.
    Never enqueues a naive page fetch for a container unless the caller chose `page` explicitly."""
    from . import jobs
    action = action or c.default_action
    if not action:
        return {"kind": c.kind, "action": None, "queued": False, "note": c.detail}
    avail = {a["action"]: a for a in c.actions}
    if action not in avail:
        raise ValueError(f"{action} is not an action for a {c.kind}")
    if not avail[action]["available"]:
        return {"kind": c.kind, "action": action, "queued": False, "unavailable": True, "note": avail[action].get("note") or c.detail}
    if action in ("ingest", "page"):
        assert c.url
        job = jobs.enqueue("ingest_url", {"url": c.url, "tags": tags or [], "project_id": project_id, "force": force, "review": False})
        return {"kind": c.kind, "action": action, "queued": True, "job_id": job["id"], "url": c.url}
    if action == "explore":
        assert c.url and (c.kind in EXPLORABLE_NOW or c.kind == "search_query")
        if c.kind == "subreddit":
            # SUB3: attach the durable container first, then scan one resumable metadata page per job turn.
            from . import community
            catalog = community.attach_subreddit_catalog(project_id, c.url)
            job = jobs.enqueue("explore", {"url": catalog["url"], "kind": "subreddit", "project_id": project_id,
                                            "collection_id": catalog["id"]}, lane="low")
            return {"kind": c.kind, "action": action, "queued": True, "catalog": True,
                    "collection_id": catalog["id"], "url": catalog["url"], "job_id": job["id"],
                    "note": "Subreddit catalog scan queued. It remembers post metadata only; no threads are read."}
        if c.kind in ("website", "website_section", "sitemap", "feed"):
            job = jobs.enqueue("explore", {"url": c.url, "kind": c.kind, "tags": tags or [], "project_id": project_id, "max_items": max_videos or None})
            return {"kind": c.kind, "action": action, "queued": True, "job_id": job["id"], "url": c.url, "review": True}
        job = jobs.enqueue("ingest_url", {"url": c.url, "tags": tags or [], "project_id": project_id, "force": force, "review": True,
                                          "since_years": since_years, "max_videos": max_videos})
        return {"kind": c.kind, "action": action, "queued": True, "job_id": job["id"], "url": c.url, "review": True}
    if action == "discover":
        if not project_id:
            return {"kind": c.kind, "action": action, "queued": False, "note": "Discover needs a project"}
        job = jobs.enqueue("discover", {"project_id": project_id, "refine": c.identifier or c.input})
        return {"kind": c.kind, "action": action, "queued": True, "job_id": job["id"]}
    if action == "resolve":
        # identity + access only; acquisition is always a separate, explicit step (owned copies are never re-acquired)
        from . import works as _works
        res = _works.find_copy(c.identifier or c.input, project_id)
        kind = (res.get("work") or {}).get("kind")
        if res.get("access") == "unavailable":
            note = ("no copy owned or seen — acquire the official document (Acquire), or upload a copy you own" if kind in _works.REGULATORY_KINDS and res.get("url")
                    else "no copy owned or seen — upload a copy you own (a book/paper is a Work, not a URL)" + (f"; landing page: {res.get('url')}" if res.get("url") else ""))
        else:
            note = {"none": "already in this project", "attach": "you already own a copy — attach it (no re-acquisition)", "acquire": "seen but not acquired — acquire from the candidate",
                    "discover": "identity unresolved — Discover can look for it"}.get(res.get("next") or "", "")
        return {"kind": c.kind, "action": action, "queued": False, "resolver": res, "note": note}
    if action == "acquire":
        from . import works as _works
        res = _works.find_copy(c.identifier or c.input, project_id)
        if res.get("access") == "owned":
            return {"kind": c.kind, "action": action, "queued": False, "resolver": res, "note": "you already own a copy — attach it instead of acquiring again"}
        if not res.get("url"):
            return {"kind": c.kind, "action": action, "queued": False, "resolver": res, "note": "no official location known for this Work"}
        job = jobs.enqueue("ingest_url", {"url": res["url"], "tags": tags or [], "project_id": project_id, "force": force, "review": False})
        return {"kind": c.kind, "action": action, "queued": True, "job_id": job["id"], "url": res["url"], "resolver": res}
    if action == "upload":
        return {"kind": c.kind, "action": action, "queued": False, "note": "use Upload (or the chat attach button) to add the file"}
    return {"kind": c.kind, "action": action, "queued": False, "note": c.detail}
