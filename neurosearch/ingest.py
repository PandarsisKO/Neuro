"""Ingest orchestration: URL -> source rows -> transcript -> chunks -> embeddings."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Callable

from . import db, media, relevance
from .chunking import build_chunks, normalize_segments
from .config import settings
from .embeddings import embed_pending
from .transcribe import transcribe_file

log = logging.getLogger(__name__)

Progress = Callable[[float, str], None]


def _noop(_p: float, _m: str) -> None:
    pass


def ingest_url(
    url: str,
    tags: list[str] | None = None,
    project_id: str | None = None,
    progress: Progress = _noop,
    force: bool = False,
    cookies_file: str | None = None,
    referer: str | None = None,
    title: str | None = None,
    collection_id: str | None = None,
    since_years: float | None = None,
    max_videos: int | None = None,
    review: bool = True,
) -> dict[str, Any]:
    """Entry point for any URL. Single videos ingest immediately. Playlists/channels are listed first and,
    with review=True (the default), wait as 'proposed' sources until the user approves them
    (see approve_proposed); with review=False they fan out into one job per video straight away.

    `since_years` / `max_videos` limit bulk pulls (default from settings; 0 = no limit).
    """
    url = url.strip()
    kind = media.classify_url(url)
    tags = tags or []

    if kind in ("playlist", "channel"):
        progress(0.02, f"listing {kind}…")
        info, entries = media.enumerate_entries(url)
        if not entries:
            raise RuntimeError(f"no videos found for {kind}: {url}")
        coll = db.upsert_collection(kind, info.get("id"), info.get("url") or url, info.get("title"))
        if project_id:
            db.add_project_collections(project_id, [coll["id"]])
        sy = settings.default_since_years if since_years is None else since_years
        mx = settings.default_max_videos if max_videos is None else max_videos
        min_date = _cutoff_date(sy)
        total_found = len(entries)
        if mx and mx > 0 and not review:
            entries = entries[:mx]
        elif review:
            # keep a bigger pool so the relevance ranker can pick the best `mx`, not just the newest
            entries = entries[:max(relevance.POOL, mx or 0)]
        queued, skipped, proposed = 0, 0, 0

        def _list_one(i: int, e: dict[str, Any]) -> None:
            nonlocal queued, skipped, proposed
            existing = db.find_source("youtube", e["id"])
            already = bool(existing and existing["status"] == "ready" and not force)
            src = db.upsert_source(
                platform="youtube", external_id=e["id"], url=e["url"], title=e.get("title"),
                duration=e.get("duration"), tags=_merge_tags(existing, tags) if existing else tags,
                status=("ready" if already else ("proposed" if review else "pending")),
                **({"description": e["description"]} if e.get("description") else {}),
                **({"view_count": e["view_count"]} if e.get("view_count") else {}),
            )
            db.link_source_collection(src["id"], coll["id"])
            if already:
                skipped += 1
            elif review:
                proposed += 1
            else:
                db.create_job("ingest_source", {"source_id": src["id"], "min_date": min_date,
                                                "collection_id": coll["id"], "newest_first": kind == "channel"})
                queued += 1

        for start in range(0, len(entries), 50):
            with db.batch():   # one transaction per 50 videos instead of ~3 per video (keeps the API responsive)
                for i, e in enumerate(entries[start:start + 50], start=start):
                    _list_one(i, e)
            progress(0.05 + 0.9 * min(start + 50, len(entries)) / len(entries), f"listed {min(start + 50, len(entries))}/{len(entries)}")
        if review and proposed:
            db.kv_set(f"review:{coll['id']}", json.dumps({"min_date": min_date, "newest_first": kind == "channel",
                                                          "project_id": project_id, "max_videos": mx, "ranked": False}))
            db.create_job("rank_proposed", {"collection_id": coll["id"], "project_id": project_id, "want": mx})
        return {"kind": kind, "collection_id": coll["id"], "title": coll.get("title"),
                "found": total_found, "queued": queued, "proposed": proposed, "already_ingested": skipped,
                "limits": {"since": min_date, "max_videos": mx}, "review": review and proposed > 0}

    if kind == "web":
        return ingest_webpage(url, tags=tags, project_id=project_id, title=title, progress=progress, html=None)
    if kind == "instagram_profile":
        if not cookies_file:
            raise RuntimeError("Instagram profiles can't be listed without logging in. Open the profile in Chrome and use the "
                               "extension → Send this page (it lends your session; the newest posts are listed for review, "
                               "max 40, fetched slowly) — or paste individual reel links (instagram.com/reel/…).")
        progress(0.02, "listing profile with your session…")
        mx = min(max_videos or settings.default_max_videos or media.IG_MAX, media.IG_MAX)
        info, entries = media.enumerate_instagram(url, cookies_file, limit=media.IG_MAX)
        if not entries:
            raise RuntimeError("Instagram listed no posts for that profile with your session (private account you don't "
                               "follow, or Instagram is rate-limiting — wait a few minutes and send it again).")
        coll = db.upsert_collection("instagram", info["id"], info["url"], info["title"])
        if project_id:
            db.add_project_collections(project_id, [coll["id"]])
        min_date = _cutoff_date(settings.default_since_years if since_years is None else since_years)
        proposed, skipped = 0, 0
        with db.batch():
            for e in entries:
                existing = db.find_source("instagram", e["id"])
                already = bool(existing and existing["status"] == "ready" and not force)
                src = db.upsert_source(platform="instagram", external_id=e["id"], url=e["url"], title=e.get("title"),
                                       duration=e.get("duration"), description=e.get("description"), view_count=e.get("view_count"),
                                       tags=_merge_tags(existing, tags) if existing else tags,
                                       status="ready" if already else "proposed")
                db.link_source_collection(src["id"], coll["id"])
                skipped += already
                proposed += not already
        db.kv_set(f"review:{coll['id']}", json.dumps({"min_date": min_date, "newest_first": True, "project_id": project_id,
                                                      "max_videos": mx, "ranked": False, "cookies_file": cookies_file,
                                                      "referer": info["url"]}))
        db.create_job("rank_proposed", {"collection_id": coll["id"], "project_id": project_id, "want": mx})
        return {"kind": "instagram_profile", "collection_id": coll["id"], "title": coll.get("title"), "found": len(entries),
                "proposed": proposed, "already_ingested": skipped, "review": proposed > 0}
    platform = "youtube" if kind == "video" else ("instagram" if kind == "instagram" else "media")
    ext_id = _external_id_from_url(url, platform)
    existing = db.find_source(platform, ext_id) if ext_id else None
    if existing and existing["status"] == "ready" and not force:
        if project_id:
            db.add_project_sources(project_id, [existing["id"]])
            _after_ready(existing["id"], project_id)
        if tags:
            db.upsert_source(platform=platform, external_id=ext_id, tags=_merge_tags(existing, tags))
        return {"kind": kind, "source_id": existing["id"], "already_ingested": True, "title": existing["title"]}
    src = db.upsert_source(platform=platform, external_id=ext_id, url=url, status="pending",
                           tags=_merge_tags(existing, tags) if existing else tags, title=title)
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    if collection_id:
        db.link_source_collection(src["id"], collection_id)
    result = ingest_source(src["id"], progress=progress, cookies_file=cookies_file, referer=referer, keep_title=title)
    return {"kind": kind, **result}


def approve_proposed(collection_id: str, source_ids: list[str] | None = None) -> dict[str, Any]:
    """Start ingesting the chosen proposed sources of a collection; drop the rest of the proposals."""
    import json as _json
    meta = {}
    try:
        meta = _json.loads(db.kv_get(f"review:{collection_id}") or "{}")
    except ValueError:
        pass
    rows = db.proposed_sources(collection_id)
    chosen = set(source_ids) if source_ids is not None else {r["id"] for r in rows}
    started, dropped = 0, 0
    for r in rows:
        if r["id"] in chosen:
            db.set_source_status(r["id"], "pending")
            db.create_job("ingest_source", {"source_id": r["id"], "min_date": meta.get("min_date"),
                                            "collection_id": collection_id, "newest_first": bool(meta.get("newest_first")),
                                            "cookies_file": meta.get("cookies_file"), "referer": meta.get("referer")})
            started += 1
        else:
            db.delete_source(r["id"])
            dropped += 1
    db.kv_set(f"review:{collection_id}", None)
    return {"collection_id": collection_id, "started": started, "dropped": dropped}


def _cutoff_date(years: float | None) -> str | None:
    if not years or years <= 0:
        return None
    from datetime import date, timedelta
    return (date.today() - timedelta(days=int(years * 365.25))).isoformat()


class TooOld(RuntimeError):
    pass


def extract_transcript(url: str, platform: str, progress: Progress = _noop,
                       cookies_file: str | None = None, referer: str | None = None,
                       min_date: str | None = None) -> dict[str, Any]:
    """Fetch metadata + transcript for one URL WITHOUT touching the database.

    Returns a portable payload: source fields + segments + chapters. This is what the CLI ships
    to a remote server with `neurosearch ingest --remote`, and what ingest_source stores locally.
    """
    progress(0.05, "fetching metadata…")
    info = media.fetch_info(url, cookies_file=cookies_file, referer=referer)
    if not info:
        if platform == "instagram" and not cookies_file:
            raise RuntimeError("Instagram wants a login for this reel. Open it in Chrome and use the Neuro Search extension → "
                               "'Send this page' (it lends your Instagram session for this one video), or paste the reel's "
                               "text into Sources → Paste text.")
        raise RuntimeError("could not fetch metadata (private, removed, or blocked?)")
    fields = media.info_to_source_fields(info, platform)
    if min_date and fields.get("published_at") and fields["published_at"] < min_date:
        raise TooOld(f"published {fields['published_at']}, before cutoff {min_date}")

    segments: list[dict[str, Any]] = []
    kind, lang = None, None
    progress(0.15, "looking for captions…")
    caps = media.fetch_captions(info, cookies_file=cookies_file)
    if caps:
        segments, lang = caps
        kind = "captions"
    elif settings.allow_transcription and settings.openai_api_key:
        dur = (info.get("duration") or 0) / 60
        if dur > settings.max_transcribe_minutes:
            raise RuntimeError(f"no captions and duration {dur:.0f} min exceeds transcription limit")
        from . import usage
        usage.guard(usage.estimate_transcription(info.get("duration")))
        progress(0.2, "no captions; downloading audio…")
        audio = media.download_audio(url, cookies_file=cookies_file, referer=referer)
        try:
            segments, lang = transcribe_file(audio, progress=lambda p, m: progress(0.3 + 0.5 * p, m))
        finally:
            try:
                audio.unlink()
            except OSError:
                pass
        kind = "transcribed"
    else:
        raise RuntimeError("no captions available and audio transcription is disabled (set OPENAI_API_KEY)")

    segments = normalize_segments(segments)
    if not segments:
        raise RuntimeError("transcript came back empty")
    fields.update(transcript_kind=kind, language=lang or fields.get("language"))
    return {**fields, "segments": segments, "chapters": info.get("chapters") or []}


def store_transcript(payload: dict[str, Any], tags: list[str] | None = None, project_id: str | None = None,
                     collection: dict[str, Any] | None = None, progress: Progress = _noop) -> dict[str, Any]:
    """Store an extracted payload (from extract_transcript, locally or shipped from another machine)."""
    segments = normalize_segments(payload["segments"])
    if not segments:
        raise RuntimeError("transcript is empty")
    fields = {k: payload.get(k) for k in (
        "platform", "external_id", "url", "title", "channel", "channel_url", "published_at", "duration",
        "description", "thumbnail_url", "language", "transcript_kind")}
    existing = db.find_source(fields["platform"], fields["external_id"]) if fields.get("external_id") else None
    fields["tags"] = _merge_tags(existing, tags or [])
    src = db.upsert_source(**fields)
    progress(0.85, "chunking…")
    chunks = build_chunks(segments, duration=fields.get("duration"), chapters=payload.get("chapters"))
    db.replace_transcript(src["id"], segments, chunks)
    db.upsert_source(platform=src["platform"], external_id=src["external_id"], status="ready", error=None)
    if collection and collection.get("kind"):
        coll = db.upsert_collection(collection["kind"], collection.get("external_id"), collection.get("url"), collection.get("title"))
        db.link_source_collection(src["id"], coll["id"])
        if project_id:
            db.add_project_collections(project_id, [coll["id"]])
    elif project_id:
        db.add_project_sources(project_id, [src["id"]])
    progress(0.9, "embedding…")
    n_emb = embed_pending()
    progress(1.0, "done")
    _after_ready(src["id"], project_id)
    return {"source_id": src["id"], "title": src["title"], "segments": len(segments), "chunks": len(chunks),
            "transcript": fields.get("transcript_kind"), "embedded": n_emb}


def _after_ready(source_id: str, project_id: str | None = None) -> None:
    try:
        from .jobs import enqueue_suggestions
        enqueue_suggestions(source_id, project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("could not queue suggestions: %s", e)


def ingest_source(source_id: str, progress: Progress = _noop, cookies_file: str | None = None,
                  referer: str | None = None, keep_title: str | None = None, min_date: str | None = None,
                  collection_id: str | None = None, newest_first: bool = False) -> dict[str, Any]:
    src = db.get_source(source_id)
    if not src:
        raise RuntimeError(f"source {source_id} not found")
    try:
        try:
            payload = extract_transcript(src["url"], src["platform"], progress=progress, cookies_file=cookies_file,
                                         referer=referer, min_date=min_date)
        except TooOld as e:
            db.set_source_status(source_id, "skipped", str(e))
            n = 0
            if newest_first and collection_id:
                # a channel's Videos tab is newest-first: everything still queued behind this one is older too
                n = db.skip_queued_siblings(collection_id, reason=f"older than cutoff {min_date}")
            return {"source_id": source_id, "skipped": True, "reason": str(e), "also_skipped": n}
        payload["external_id"] = payload.get("external_id") or src["external_id"]
        if keep_title:
            payload["title"] = keep_title
        return store_transcript(payload, progress=progress)
    except Exception as e:  # noqa: BLE001
        from .media import RateLimited
        from .usage import BudgetPaused
        if isinstance(e, (RateLimited, BudgetPaused)):
            raise
        log.exception("ingest failed for %s", source_id)
        db.set_source_status(source_id, "failed", str(e)[:1000])
        raise


def ingest_local_file(path: Path, title: str | None = None, tags: list[str] | None = None,
                      project_id: str | None = None, progress: Progress = _noop,
                      original_name: str | None = None) -> dict[str, Any]:
    """Ingest an uploaded file: audio/video is transcribed; PDF/DOCX/TXT are read as documents;
    .srt/.vtt are parsed as ready-made transcripts."""
    from .documents import is_document, is_media

    name = original_name or path.name
    kind_path = Path(name)
    if kind_path.suffix.lower() in (".srt", ".vtt"):
        return ingest_subtitle_file(path, title or kind_path.stem, tags, project_id, name)
    if is_document(kind_path):
        return ingest_document(path, title or name, tags, project_id, name)
    if not is_media(kind_path):
        raise RuntimeError(f"unsupported file type: {kind_path.suffix or 'no extension'}")
    return _ingest_media_file(path, title or kind_path.stem, tags, project_id, name, progress)


def ingest_document(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str) -> dict[str, Any]:
    from .chunking import build_doc_chunks
    from .documents import extract_pages

    ext_id = f"doc:{name}:{path.stat().st_size}"
    src = db.upsert_source(platform="document", external_id=ext_id, url=f"file://{name}", title=title,
                           status="pending", tags=tags or [])
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    try:
        pages = extract_pages(path)
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = build_doc_chunks(pages)
        db.replace_transcript(src["id"], segments, chunks)
        db.upsert_source(platform="document", external_id=ext_id, duration=None, transcript_kind="document",
                         description=f"{len(pages)} pages", status="ready", error=None)
        n = embed_pending()
        _after_ready(src["id"], project_id)
        return {"source_id": src["id"], "title": title, "segments": len(segments), "chunks": len(chunks),
                "transcript": "document", "embedded": n}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_webpage(url: str, tags: list[str] | None = None, project_id: str | None = None,
                   title: str | None = None, progress: Progress = _noop, html: str | None = None) -> dict[str, Any]:
    """An article / web page (or a PDF link) as a source; sections are cited as '§ N'."""
    from .chunking import build_doc_chunks
    from .webpage import read_page

    ext_id = re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/")
    src = db.upsert_source(platform="web", external_id=ext_id, url=url, title=title, status="pending", tags=tags or [])
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    try:
        progress(0.1, "fetching page…")
        page = read_page(url, html_text=html)
        pages = page["pages"]
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = build_doc_chunks(pages)
        db.replace_transcript(src["id"], segments, chunks)
        db.upsert_source(platform="web", external_id=ext_id, title=title or page["title"], url=page["url"],
                         transcript_kind=page["kind"], description=f"{len(pages)} sections",
                         channel=urlparse(page["url"]).netloc.replace("www.", ""), status="ready", error=None)
        progress(0.7, "embedding…")
        n = embed_pending()
        _after_ready(src["id"], project_id)
        return {"kind": "web", "source_id": src["id"], "title": title or page["title"], "segments": len(segments),
                "chunks": len(chunks), "transcript": page["kind"], "embedded": n}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_subtitle_file(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str) -> dict[str, Any]:
    raw = path.read_text(errors="replace")
    if not raw.lstrip().startswith("WEBVTT"):  # srt -> vtt-ish: timestamps use commas
        raw = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d{3})", r"\1.\2", raw)
    segments = media.parse_vtt(raw)
    payload = {"platform": "file", "external_id": f"sub:{name}:{path.stat().st_size}", "url": f"file://{name}",
               "title": title, "duration": segments[-1]["end"] if segments else None, "transcript_kind": "captions",
               "segments": segments, "chapters": []}
    return store_transcript(payload, tags=tags, project_id=project_id)


def _ingest_media_file(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str,
                       progress: Progress) -> dict[str, Any]:
    """Transcribe an uploaded audio/video file."""
    ext_id = f"file:{name}:{path.stat().st_size}"
    src = db.upsert_source(platform="file", external_id=ext_id, url=f"file://{name}", title=title,
                           status="pending", tags=tags or [])
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    try:
        segments, lang = transcribe_file(path, progress=lambda p, m: progress(0.1 + 0.7 * p, m))
        segments = normalize_segments(segments)
        if not segments:
            raise RuntimeError("transcript came back empty")
        duration = segments[-1]["end"]
        chunks = build_chunks(segments, duration=duration)
        db.replace_transcript(src["id"], segments, chunks)
        db.upsert_source(platform="file", external_id=ext_id, duration=duration, transcript_kind="transcribed",
                         language=lang, status="ready", error=None)
        n = embed_pending()
        _after_ready(src["id"], project_id)
        return {"source_id": src["id"], "title": src["title"], "segments": len(segments), "chunks": len(chunks), "embedded": n}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_text(title: str, text: str, url: str | None = None, tags: list[str] | None = None,
                project_id: str | None = None) -> dict[str, Any]:
    """Store a transcript you already have. Lines starting with a timestamp like `12:34 ` or `[1:02:03]` are honoured."""
    segments = _parse_timestamped_text(text)
    ext_id = f"text:{abs(hash((title, text[:200], len(text))))}"
    src = db.upsert_source(platform="manual", external_id=ext_id, url=url or f"manual://{ext_id}", title=title,
                           status="pending", tags=tags or [])
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    duration = segments[-1]["end"] if segments and segments[-1]["end"] > 0 else None
    chunks = build_chunks(segments, duration=duration or 10 ** 6)  # force long-form windowing by chars if untimed
    db.replace_transcript(src["id"], segments, chunks)
    db.upsert_source(platform="manual", external_id=ext_id, duration=duration, transcript_kind="manual", status="ready")
    n = embed_pending()
    _after_ready(src["id"], project_id)
    return {"source_id": src["id"], "title": title, "segments": len(segments), "chunks": len(chunks), "embedded": n}


_TS_LINE = re.compile(r"^\s*\[?((?:\d{1,2}:)?\d{1,2}:\d{2})\]?\s*[-–—:]?\s*(.*)$")


def _parse_timestamped_text(text: str) -> list[dict[str, Any]]:
    segs: list[dict[str, Any]] = []
    untimed: list[str] = []
    for line in text.splitlines():
        m = _TS_LINE.match(line)
        if m and m.group(2).strip():
            parts = [int(p) for p in m.group(1).split(":")]
            t = parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]
            if segs:
                segs[-1]["end"] = max(segs[-1]["end"], float(t))
            segs.append({"start": float(t), "end": float(t), "text": m.group(2).strip()})
        elif line.strip():
            if segs:
                segs[-1]["text"] += " " + line.strip()
            else:
                untimed.append(line.strip())
    if not segs:
        # no timestamps at all: split into paragraphs at time 0 so chunking works by characters
        for para in re.split(r"\n\s*\n", "\n".join(untimed)) or [""]:
            if para.strip():
                segs.append({"start": 0.0, "end": 0.0, "text": " ".join(para.split())})
    return segs


def _merge_tags(existing: dict[str, Any] | None, tags: list[str]) -> list[str]:
    cur = list(existing.get("tags") or []) if existing else []
    for t in tags:
        if t not in cur:
            cur.append(t)
    return cur


def _external_id_from_url(url: str, platform: str) -> str | None:
    if platform == "youtube":
        m = re.search(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([A-Za-z0-9_-]{11})", url)
        return m.group(1) if m else None
    if platform == "instagram":
        m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)", url)
        return m.group(1) if m else url
    return url.split("#")[0]
