"""Ingest orchestration: URL -> source rows -> transcript -> chunks -> embeddings."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from . import db, media
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
) -> dict[str, Any]:
    """Entry point for any URL. Playlists/channels fan out into one job per video.

    Returns a summary dict.
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
        queued, skipped = 0, 0
        for i, e in enumerate(entries):
            existing = db.find_source("youtube", e["id"])
            src = db.upsert_source(
                platform="youtube", external_id=e["id"], url=e["url"], title=e.get("title"),
                duration=e.get("duration"), tags=_merge_tags(existing, tags) if existing else tags,
                status=(existing["status"] if existing and existing["status"] == "ready" and not force else "pending"),
            )
            db.link_source_collection(src["id"], coll["id"])
            if existing and existing["status"] == "ready" and not force:
                skipped += 1
            else:
                db.create_job("ingest_source", {"source_id": src["id"]})
                queued += 1
            if i % 25 == 0:
                progress(0.05 + 0.9 * i / len(entries), f"queued {i + 1}/{len(entries)}")
        return {"kind": kind, "collection_id": coll["id"], "title": coll.get("title"),
                "found": len(entries), "queued": queued, "already_ingested": skipped}

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
                           tags=_merge_tags(existing, tags) if existing else tags)
    if project_id:
        db.add_project_sources(project_id, [src["id"]])
    result = ingest_source(src["id"], progress=progress)
    return {"kind": kind, **result}


def extract_transcript(url: str, platform: str, progress: Progress = _noop) -> dict[str, Any]:
    """Fetch metadata + transcript for one URL WITHOUT touching the database.

    Returns a portable payload: source fields + segments + chapters. This is what the CLI ships
    to a remote server with `neurosearch ingest --remote`, and what ingest_source stores locally.
    """
    progress(0.05, "fetching metadata…")
    info = media.fetch_info(url)
    if not info:
        raise RuntimeError("could not fetch metadata (private, removed, or blocked?)")
    fields = media.info_to_source_fields(info, platform)

    segments: list[dict[str, Any]] = []
    kind, lang = None, None
    progress(0.15, "looking for captions…")
    caps = media.fetch_captions(info)
    if caps:
        segments, lang = caps
        kind = "captions"
    elif settings.allow_transcription and settings.openai_api_key:
        dur = (info.get("duration") or 0) / 60
        if dur > settings.max_transcribe_minutes:
            raise RuntimeError(f"no captions and duration {dur:.0f} min exceeds transcription limit")
        progress(0.2, "no captions; downloading audio…")
        audio = media.download_audio(url)
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


def ingest_source(source_id: str, progress: Progress = _noop) -> dict[str, Any]:
    src = db.get_source(source_id)
    if not src:
        raise RuntimeError(f"source {source_id} not found")
    try:
        payload = extract_transcript(src["url"], src["platform"], progress=progress)
        payload["external_id"] = payload.get("external_id") or src["external_id"]
        return store_transcript(payload, progress=progress)
    except Exception as e:  # noqa: BLE001
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
