"""YouTube Data API v3 as a $0 metadata backend — batched, keyed, and strictly optional.

WHY THIS EXISTS. `media.enumerate_entries` lists a channel with yt-dlp's `extract_flat="in_playlist"`, which
returns id/title/duration and nothing else, then reads `e.get("description")` — a field flat extraction never
populates. Measured 2026-09-20 on Kyle's project: ~48 of 11,774 candidates carry a description and none carry a
publish date, so every relevance score the app has ever computed was made from a title and a runtime. The
alternative yt-dlp offers is a full per-video fetch at `settings.yt_delay` (~4.4 s each, serialised by
`media.polite`), which is ~14 hours for that backlog and holds the lock ingestion needs.

The Data API answers the same question in batches: `videos.list` takes up to 50 ids for ONE quota unit against a
10,000 unit/day free allowance, so the whole backlog is ~236 units and a few minutes. `playlistItems.list` is
likewise 1 unit per 50 and carries `snippet.description`, which means a channel can be ENUMERATED with
descriptions already attached — removing the flat-vs-slow tradeoff rather than paying it later.

WHAT IT DOES NOT DO. Captions. `captions.download` requires OAuth as the video's OWNER, so third-party
transcripts remain yt-dlp's job permanently; `contentDetails.caption` only reports whether captions EXIST, which
is still worth having because `usage.estimate_video` currently cannot tell and quotes a range. `search.list`
costs 100 units per call — a hundred searches would exhaust the day — so it is deliberately not implemented here.

BOUNDARIES, mirroring `scholar.py`: every request goes through `safe_fetch` (the one fetch path), no client
library, no second boundary. No model call anywhere. Nothing here writes to the database or attaches anything to
a project — callers decide. Without a key `available()` reports off and every caller falls back to yt-dlp, so
this module is additive: the app behaves exactly as it does today until a key is configured.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from .config import settings

API = "https://www.googleapis.com/youtube/v3"
DEADLINE_S = 20.0
BATCH = 50                 # the API's own ceiling for an `id` list, and for `maxResults`
COST = {"videos": 1, "playlistItems": 1, "channels": 1, "search": 100}


class YouTubeApiUnavailable(RuntimeError):
    """One exception for every failure mode, so a caller never has to tell 'no results' from 'it is down'."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


def available() -> dict[str, Any]:
    """Is the API usable, and the plain reason when not. Reads config, touches no network."""
    key = settings.youtube_api_key
    return {"ready": bool(key),
            "why": "keyed — 10,000 quota units/day, 50 videos per unit" if key else
                   "no NEUROSEARCH_YOUTUBE_API_KEY set — falling back to yt-dlp (one paced request per video)"}


_spent = {"units": 0, "calls": 0}


def quota_spent() -> dict[str, int]:
    """Units used by THIS process. The API exposes no remaining-quota endpoint, so this is a local tally only —
    accurate for what we did, silent about what anything else did with the same key."""
    return dict(_spent)


def _get(endpoint: str, params: dict[str, Any]) -> Any:
    from . import safe_fetch as SF
    key = settings.youtube_api_key
    if not key:
        raise YouTubeApiUnavailable("no_key", "NEUROSEARCH_YOUTUBE_API_KEY is not set")
    q = {k: v for k, v in params.items() if v not in (None, "")}
    q["key"] = key
    url = f"{API}/{endpoint}?" + urllib.parse.urlencode(q)
    try:
        res = SF.safe_fetch(url, content_class="html", headers={"Accept": "application/json"}, deadline_s=DEADLINE_S)
    except SF.FetchBlocked as e:
        raise YouTubeApiUnavailable("fetch_blocked", getattr(e, "reason", "") or str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise YouTubeApiUnavailable("unreachable", str(e)[:200]) from e
    _spent["units"] += COST.get(endpoint, 1)
    _spent["calls"] += 1
    body = (res.body or b"").decode("utf-8", "replace")
    if res.status == 403 and "quotaExceeded" in body:
        raise YouTubeApiUnavailable("quota_exceeded", "the key's 10,000 daily units are gone; it resets at midnight Pacific")
    if res.status == 403:
        raise YouTubeApiUnavailable("forbidden", "key rejected — check it is enabled for YouTube Data API v3 and unrestricted for this use")
    if res.status == 400:
        raise YouTubeApiUnavailable("bad_request", body[:200])
    if res.status >= 400:
        raise YouTubeApiUnavailable("http_error", f"HTTP {res.status}")
    try:
        return json.loads(body)
    except ValueError as e:
        raise YouTubeApiUnavailable("bad_json", body[:200]) from e


# ------------------------------------------------------------------ parsing (pure; tested without a key)

_ISO = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_duration(iso: str | None) -> float | None:
    """ISO-8601 duration -> seconds. The API's own format; `PT1H2M3S`, `P1DT2H`, `PT45S`."""
    if not iso:
        return None
    m = _ISO.match(iso.strip())
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    total = d * 86400 + h * 3600 + mi * 60 + s
    return float(total) or None


def video_fields(item: dict[str, Any]) -> dict[str, Any]:
    """One `videos.list` item -> the field names the Candidate Index already uses, so callers can hand the result
    straight to `candidates.remember` without a second mapping layer."""
    sn = item.get("snippet") or {}
    cd = item.get("contentDetails") or {}
    st = item.get("statistics") or {}
    published = (sn.get("publishedAt") or "")[:10] or None          # YYYY-MM-DD, as the schema stores it
    return {
        "external_id": item.get("id"),
        "title": sn.get("title"),
        "description": (sn.get("description") or "")[:5000] or None,
        "creator": sn.get("channelTitle"),
        "channel_id": sn.get("channelId"),
        "published_at": published,
        "duration": parse_duration(cd.get("duration")),
        "view_count": int(st["viewCount"]) if str(st.get("viewCount", "")).isdigit() else None,
        # `usage.estimate_video` quotes "+$X if captions turn out to be missing" because nothing could tell it.
        # This can: "true"/"false" as a string in the API's own JSON.
        "has_captions": {"true": True, "false": False}.get(str(cd.get("caption")).lower()),
        "tags": sn.get("tags") or [],
        "category_id": sn.get("categoryId"),
        "live": (sn.get("liveBroadcastContent") or "none") != "none",
    }


def playlist_item_fields(item: dict[str, Any]) -> dict[str, Any] | None:
    """One `playlistItems.list` item -> the same shape, for enumeration. Deleted/private entries have no id and
    are dropped rather than becoming a candidate with no way to fetch it."""
    sn = item.get("snippet") or {}
    vid = ((sn.get("resourceId") or {}).get("videoId")) or None
    if not vid:
        return None
    title = sn.get("title") or ""
    if title in ("Private video", "Deleted video"):
        return None
    return {
        "external_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": title,
        "description": (sn.get("description") or "")[:5000] or None,
        "creator": sn.get("videoOwnerChannelTitle") or sn.get("channelTitle"),
        "published_at": (sn.get("publishedAt") or "")[:10] or None,
    }


# ------------------------------------------------------------------ batched reads

def videos(ids: list[str], *, parts: str = "snippet,contentDetails,statistics") -> dict[str, dict[str, Any]]:
    """Full metadata for many video ids, 50 per quota unit. Returns {id: fields}; ids the API does not return
    (deleted, private, region-blocked) are simply absent — never an error, so a caller can tell what it got."""
    out: dict[str, dict[str, Any]] = {}
    clean = [i for i in dict.fromkeys(ids) if i]
    for b in range(0, len(clean), BATCH):
        chunk = clean[b:b + BATCH]
        data = _get("videos", {"part": parts, "id": ",".join(chunk), "maxResults": BATCH})
        for item in data.get("items") or []:
            f = video_fields(item)
            if f["external_id"]:
                out[f["external_id"]] = f
    return out


def uploads_playlist_id(channel_id: str) -> str | None:
    """A channel's uploads playlist — the cheap way to enumerate everything it has published."""
    data = _get("channels", {"part": "contentDetails", "id": channel_id})
    for item in data.get("items") or []:
        rel = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {})
        if rel.get("uploads"):
            return rel["uploads"]
    return None


def playlist_items(playlist_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Enumerate a playlist WITH descriptions, 50 per quota unit. `limit` bounds the paging so a 5,000-video
    channel cannot quietly spend 100 units."""
    out: list[dict[str, Any]] = []
    token = None
    while len(out) < limit:
        data = _get("playlistItems", {"part": "snippet", "playlistId": playlist_id,
                                      "maxResults": min(BATCH, limit - len(out)), "pageToken": token})
        for item in data.get("items") or []:
            f = playlist_item_fields(item)
            if f:
                out.append(f)
        token = data.get("nextPageToken")
        if not token:
            break
    return out[:limit]


# ------------------------------------------------------------------ enumeration by URL

_RE_CHANNEL_ID = re.compile(r"/channel/(UC[A-Za-z0-9_-]{20,})")
_RE_HANDLE = re.compile(r"/@([A-Za-z0-9._\-]+)")
_RE_LEGACY = re.compile(r"/(?:c|user)/([A-Za-z0-9._\-]+)")


def channel_ref(url: str) -> tuple[str, str] | None:
    """Which `channels.list` selector a channel URL gives us. `/channel/UC…` is the id itself (free); `/@handle`
    is `forHandle`; the legacy `/c/` and `/user/` forms are only resolvable as `forUsername`, and for a `/c/`
    vanity name that often fails -- callers fall back to yt-dlp rather than guessing."""
    m = _RE_CHANNEL_ID.search(url)
    if m:
        return ("id", m.group(1))
    m = _RE_HANDLE.search(url)
    if m:
        return ("forHandle", "@" + m.group(1))
    m = _RE_LEGACY.search(url)
    if m:
        return ("forUsername", m.group(1))
    return None


def playlist_id_of(url: str) -> str | None:
    """The `list=` id of a playlist URL. A watch URL carrying `list=` is a VIDEO with a playlist attached, so
    `media.classify_url` already calls that a video and this is never reached for one."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    v = (q.get("list") or [None])[0]
    return v or None


def resolve_channel(url: str) -> dict[str, Any] | None:
    """Channel URL -> {channel_id, title, url, uploads}. One quota unit. None when the URL carries no selector
    we can use; raises YouTubeApiUnavailable when the API itself is the problem, so a caller can tell a URL it
    should handle another way from an outage it should retry."""
    ref = channel_ref(url)
    if not ref:
        return None
    sel, val = ref
    data = _get("channels", {"part": "snippet,contentDetails", sel: val})
    for item in data.get("items") or []:
        sn = item.get("snippet") or {}
        rel = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {})
        cid = item.get("id")
        return {"channel_id": cid, "title": sn.get("title"),
                "url": f"https://www.youtube.com/channel/{cid}" if cid else url,
                "uploads": rel.get("uploads")}
    return None


def enrich(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill duration / view_count / has_captions onto `playlistItems` rows, which carry none of the three. One
    extra unit per 50, so a 500-video channel costs 10 units here on top of 10 to list it -- against a 10,000
    unit day. Anything the videos endpoint does not return keeps its listing fields rather than vanishing."""
    ids = [e.get("external_id") for e in entries if e.get("external_id")]
    if not ids:
        return entries
    full = videos(ids)
    for e in entries:
        f = full.get(e.get("external_id") or "")
        if not f:
            continue
        for k in ("duration", "view_count", "has_captions", "creator", "channel_id", "tags", "category_id", "live"):
            if f.get(k) is not None:
                e[k] = f[k]
        # videos.list gives the untruncated description and the real title; listing rows can lag both
        if f.get("description"):
            e["description"] = f["description"]
        if f.get("title"):
            e["title"] = f["title"]
    return entries


def enumerate_url(url: str, *, limit: int = 500, with_details: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """A channel or playlist URL -> (collection_info, entries) with descriptions and publish dates ATTACHED,
    which is the whole point: `media.enumerate_entries`'s flat yt-dlp path cannot carry either, so every
    candidate it created had to be scored from a title alone (see this module's header).

    Returns (info, []) for a URL this cannot address -- a `/c/` vanity name the API will not resolve, say -- so
    the caller falls back rather than treating an unaddressable URL as an empty channel."""
    pid = playlist_id_of(url)
    info: dict[str, Any] = {}
    if pid:
        info = {"id": pid, "title": None, "url": url}
    else:
        ch = resolve_channel(url)
        if not ch or not ch.get("uploads"):
            return {}, []
        pid = ch["uploads"]
        info = {"id": ch.get("channel_id"), "title": ch.get("title"), "url": ch.get("url") or url}
    entries = playlist_items(pid, limit=limit)
    if entries and with_details:
        entries = enrich(entries)
    if not info.get("title") and entries:
        info["title"] = entries[0].get("creator")
    return info, entries
