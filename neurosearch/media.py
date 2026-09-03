"""Everything that talks to yt-dlp: URL classification, playlist/channel enumeration,
metadata, caption download, audio download. Works for YouTube, Instagram, podcast feeds,
direct media URLs and ~1000 other sites yt-dlp supports.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .config import settings

log = logging.getLogger(__name__)

# --- politeness / rate-limit handling -------------------------------------------------------------
import random
import threading
import time as _time

_yt_lock = threading.Lock()          # one YouTube fetch at a time, app-wide
_yt_last = 0.0
_yt_paused_until = 0.0
BOT_CHECK = re.compile(r"confirm you.re not a bot|sign in to confirm|HTTP Error 429|too many requests|rate.?limit", re.I)


class RateLimited(RuntimeError):
    """YouTube asked us to slow down; the job runner re-queues instead of failing."""


def _is_youtube(url: str) -> bool:
    return any(h in url for h in ("youtube.com", "youtu.be"))


def polite(url: str):
    """Context manager: serialise YouTube requests and space them out; honour a global pause after a bot-check."""
    class _Ctx:
        def __enter__(self):
            if not _is_youtube(url):
                return self
            _yt_lock.acquire()
            global _yt_last
            wait = max(0.0, _yt_paused_until - _time.time())
            if wait > 0:
                _yt_lock.release()
                raise RateLimited(f"YouTube rate limit — paused for another {int(wait // 60) + 1} min")
            gap = settings.yt_delay * random.uniform(0.5, 1.5) - (_time.time() - _yt_last)
            if gap > 0:
                _time.sleep(gap)
            return self
        def __exit__(self, et, ev, tb):
            if not _is_youtube(url):
                return False
            global _yt_last, _yt_paused_until
            _yt_last = _time.time()
            _yt_lock.release()
            if ev is not None and BOT_CHECK.search(str(ev)):
                _yt_paused_until = _time.time() + settings.yt_backoff_minutes * 60
                log.warning("YouTube bot-check/rate limit hit; pausing YouTube fetches for %d min", settings.yt_backoff_minutes)
                raise RateLimited(f"YouTube asked us to slow down; pausing {settings.yt_backoff_minutes} min then retrying") from ev
            return False
    return _Ctx()


def rate_limit_status() -> dict[str, Any]:
    left = max(0.0, _yt_paused_until - _time.time())
    return {"paused": left > 0, "seconds_left": int(left)}


YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}


def classify_url(url: str) -> str:
    """video | playlist | channel | instagram | media  (media = anything else yt-dlp/ffmpeg can handle)."""
    u = urlparse(url.strip())
    host = u.netloc.lower()
    if host in YT_HOSTS:
        qs = parse_qs(u.query)
        if "list" in qs and "v" not in qs:
            return "playlist"
        if u.path.startswith("/playlist"):
            return "playlist"
        if host == "youtu.be" or u.path in ("/watch",) or u.path.startswith(("/shorts/", "/live/", "/embed/")):
            return "video"
        if u.path.startswith(("/@", "/channel/", "/c/", "/user/")):
            return "channel"
        return "video"
    if "instagram.com" in host:
        return "instagram"
    if "loom.com" in host:
        return "media"
    from .webpage import looks_like_media
    if not looks_like_media(url):
        return "web"
    return "media"


def _base_opts(cookies_file: str | None = None, referer: str | None = None, **extra: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    cf = cookies_file or settings.cookies_file
    if cf and Path(cf).exists():
        opts["cookiefile"] = cf
    if referer:
        opts["http_headers"] = {"Referer": referer, "Origin": referer.split("/", 3)[0] + "//" + referer.split("/", 3)[2]}
    opts.update(extra)
    return opts


# ------------------------------------------------------------ enumeration

def enumerate_entries(url: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """List videos in a playlist or channel without downloading anything.

    Returns (collection_info, entries) where each entry has id, url, title.
    For channels, both the Videos and Shorts tabs are scanned.
    """
    kind = classify_url(url)
    urls = [url]
    if kind == "channel":
        base = url.rstrip("/")
        if not re.search(r"/(videos|shorts|streams|live|playlists)$", base):
            urls = [base + "/videos", base + "/shorts"]
    info: dict[str, Any] = {}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    with yt_dlp.YoutubeDL(_base_opts(extract_flat="in_playlist", skip_download=True)) as ydl:
        for u in urls:
            try:
                res = ydl.extract_info(u, download=False)
            except Exception as e:  # noqa: BLE001
                log.warning("enumerate failed for %s: %s", u, e)
                continue
            if not res:
                continue
            if not info:
                info = {
                    "id": res.get("channel_id") if kind == "channel" else res.get("id"),
                    "title": res.get("channel") or res.get("uploader") if kind == "channel" else res.get("title"),
                    "url": res.get("channel_url") or res.get("webpage_url") or url if kind == "channel" else res.get("webpage_url") or url,
                }
            for e in _flatten(res):
                vid = e.get("id")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                entries.append({
                    "id": vid,
                    "url": e.get("url") if str(e.get("url", "")).startswith("http") else f"https://www.youtube.com/watch?v={vid}",
                    "title": e.get("title"),
                    "duration": e.get("duration"),
                    "description": (e.get("description") or None),
                    "view_count": e.get("view_count"),
                })
    return info, entries


def _flatten(res: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for e in res.get("entries") or []:
        if not e:
            continue
        if e.get("_type") == "playlist" and e.get("entries"):
            out.extend(_flatten(e))
        else:
            out.append(e)
    return out


# ------------------------------------------------------ metadata/captions

def fetch_info(url: str, cookies_file: str | None = None, referer: str | None = None) -> dict[str, Any] | None:
    """Full metadata for one item (no download)."""
    with polite(url), yt_dlp.YoutubeDL(_base_opts(cookies_file, referer, skip_download=True)) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:  # noqa: BLE001
            if BOT_CHECK.search(str(e)):
                raise
            raise RuntimeError(f"metadata fetch failed: {e}") from e
    if info and info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), None)
    return info


def info_to_source_fields(info: dict[str, Any], platform: str) -> dict[str, Any]:
    published = info.get("upload_date") or info.get("release_date")
    if published and len(published) == 8:
        published = f"{published[:4]}-{published[4:6]}-{published[6:]}"
    return {
        "platform": platform,
        "external_id": info.get("id"),
        "url": info.get("webpage_url") or info.get("original_url"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "published_at": published,
        "duration": info.get("duration"),
        "description": (info.get("description") or "")[:5000],
        "thumbnail_url": info.get("thumbnail"),
        "language": info.get("language"),
    }


def fetch_captions(info: dict[str, Any], cookies_file: str | None = None) -> tuple[list[dict[str, Any]], str] | None:
    """Return (segments, lang) using uploaded subtitles if present, else auto captions. None if neither."""
    langs = settings.caption_langs
    for pool_name in ("subtitles", "automatic_captions"):
        pool = info.get(pool_name) or {}
        for lang in _lang_candidates(pool, langs):
            fmts = pool.get(lang) or []
            fmt = next((f for f in fmts if f.get("ext") == "json3"), None) or next(
                (f for f in fmts if f.get("ext") in ("srv3", "vtt")), None)
            if not fmt or not fmt.get("url"):
                continue
            try:
                raw = _download_text(fmt["url"], cookies_file)
                segs = parse_json3(raw) if fmt["ext"] == "json3" else parse_vtt(raw)
            except Exception as e:  # noqa: BLE001
                log.warning("caption download failed (%s/%s): %s", pool_name, lang, e)
                continue
            if segs:
                return segs, lang
    return None


def _lang_candidates(pool: dict[str, Any], preferred: list[str]) -> list[str]:
    cands = [l for l in preferred if l in pool]
    # also accept any variant like en-orig, en-x-autogen
    cands += [l for l in pool if l.split("-")[0] in {p.split("-")[0] for p in preferred} and l not in cands]
    return cands


def _download_text(url: str, cookies_file: str | None = None) -> str:
    with yt_dlp.YoutubeDL(_base_opts(cookies_file)) as ydl:
        with ydl.urlopen(url) as resp:  # honours cookies/proxy settings
            return resp.read().decode("utf-8", errors="replace")


def parse_json3(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    segs: list[dict[str, Any]] = []
    for ev in data.get("events", []):
        if ev.get("aAppend") or "segs" not in ev:
            continue
        text = "".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000.0
        dur = ev.get("dDurationMs", 0) / 1000.0
        segs.append({"start": start, "end": start + dur, "text": text})
    return segs


_VTT_TS = re.compile(r"(\d+):(\d\d):(\d\d)\.(\d{3})|(\d\d):(\d\d)\.(\d{3})")


def _vtt_seconds(ts: str) -> float:
    m = _VTT_TS.match(ts.strip())
    if not m:
        return 0.0
    if m.group(1) is not None:
        h, mi, s, ms = (int(m.group(i)) for i in (1, 2, 3, 4))
    else:
        h, mi, s, ms = 0, int(m.group(5)), int(m.group(6)), int(m.group(7))
    return h * 3600 + mi * 60 + s + ms / 1000


def parse_vtt(raw: str) -> list[dict[str, Any]]:
    segs: list[dict[str, Any]] = []
    block: list[str] = []
    for line in raw.splitlines() + [""]:
        if line.strip() == "":
            if block:
                tl = next((l for l in block if "-->" in l), None)
                if tl:
                    a, b = tl.split("-->")[:2]
                    text = " ".join(l for l in block[block.index(tl) + 1:]).strip()
                    text = re.sub(r"<[^>]+>", "", text)
                    if text:
                        segs.append({"start": _vtt_seconds(a), "end": _vtt_seconds(b.split()[0]), "text": text})
                block = []
        else:
            block.append(line)
    # de-dupe rolling duplicates common in auto-generated vtt
    out: list[dict[str, Any]] = []
    for s in segs:
        if out and s["text"] == out[-1]["text"]:
            out[-1]["end"] = s["end"]
        else:
            out.append(s)
    return out


# ------------------------------------------------------------- audio

def download_audio(url: str, dest_dir: Path | None = None, cookies_file: str | None = None,
                   referer: str | None = None) -> Path:
    """Download best audio as m4a/mp3 for transcription. Returns the file path."""
    dest_dir = dest_dir or settings.media_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = _base_opts(
        cookies_file, referer,
        format="bestaudio/best",
        outtmpl=str(dest_dir / "%(id)s.%(ext)s"),
        postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}],
        ignoreerrors=False,
    )
    with polite(url), yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info and info.get("_type") == "playlist" and info.get("entries"):
            info = next((e for e in info["entries"] if e), None)
    if not info:
        raise RuntimeError("audio download produced no result")
    path = dest_dir / f"{info['id']}.mp3"
    if not path.exists():
        cands = list(dest_dir.glob(f"{info['id']}.*"))
        if not cands:
            raise RuntimeError("audio file not found after download")
        path = cands[0]
    return path
