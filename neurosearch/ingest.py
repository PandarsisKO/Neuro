"""Ingest orchestration: URL -> source rows -> transcript -> chunks -> embeddings."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Callable

from . import db, identity, media, providers, relevance
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
    capture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Entry point for any URL. Single videos ingest immediately. Playlists/channels are listed first and,
    with review=True (the default), wait as 'proposed' sources until the user approves them
    (see approve_proposed); with review=False they fan out into one job per video straight away.

    `since_years` / `max_videos` limit bulk pulls (default from settings; 0 = no limit).
    """
    url = media.canonical_url(url)
    kind = media.classify_url(url)
    tags = tags or []

    from . import community
    if community.is_reddit_thread(url):
        # G7: a discussion thread is a community Source (thread + post tree), never a JavaScript page read as HTML;
        # B1: `capture` = what the user's browser saw (the parked job's external result) — same path, same source
        return community.acquire_thread(url, tags=tags, project_id=project_id, progress=progress, capture=capture, force=force)
    if capture is not None:
        # B1: a page the browser rendered for us (generic capture): the standard page path with the supplied HTML
        html = capture.get("html") if isinstance(capture, dict) else None
        if not html:
            raise RuntimeError("the browser capture carried no page content")
        return ingest_webpage(url, tags=tags, project_id=project_id, title=title or (capture.get("title") if isinstance(capture, dict) else None), progress=progress, html=html)
    if kind == "youtube_search":
        # a YouTube search link (Discover hands these out when it isn't sure of a channel): list the top results
        # for review + relevance ranking, exactly like a playlist — never blindly download a search page
        query = media.search_query_of(url)
        if not query:
            raise RuntimeError("that YouTube search link has no query in it")
        progress(0.02, f"searching YouTube for “{query}”…")
        info, entries = media.enumerate_search(query, limit=30)
        if not entries:
            raise RuntimeError(f"YouTube returned no results for “{query}”")
        kind = "playlist"       # from here on it is handled like a playlist review (below)
        review = True
    else:
        info = entries = None
    if kind in ("playlist", "channel"):
        progress(0.02, f"listing {kind}…")
        if entries is None:
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
        counts = {"already_in_project": 0, "already_in_library": 0, "new": 0}

        def _list_one(i: int, e: dict[str, Any]) -> None:
            nonlocal queued, skipped, proposed
            # G1: identity first. An existing row is never reset by a listing (a video being ingested for another
            # project keeps its status); only NEW rows start as proposed/pending.
            cand = identity.Candidate(platform="youtube", external_id=e["id"], url=e["url"], title=e.get("title"), tags=tags,
                                      fields={"duration": e.get("duration"), "description": e.get("description") or None,
                                              "view_count": e.get("view_count") or None})
            res = identity.resolve_or_create_source(cand, None, initial_status="proposed" if review else "pending", resume_skipped=False)
            src = res.source
            db.link_source_collection(src["id"], coll["id"])
            in_project = bool(project_id) and src["id"] in project_member_ids
            if in_project:
                counts["already_in_project"] += 1
            elif res.state == identity.NEW:
                counts["new"] += 1
            else:
                counts["already_in_library"] += 1
            already = (src["status"] == "ready" and not force) or (in_project and src["status"] != "proposed")
            if already:
                skipped += 1
            elif src["status"] == "proposed" or (res.created and review):
                proposed += 1
            elif res.created:
                db.create_job("ingest_source", {"source_id": src["id"], "min_date": min_date,
                                                "collection_id": coll["id"], "newest_first": kind == "channel"})
                queued += 1
            else:
                skipped += 1                                       # pending/failed elsewhere: shared work, not a new job

        project_member_ids = set(db.project_source_ids(project_id, ready_only=False)) if project_id else set()
        for start in range(0, len(entries), 50):
            with db.batch():   # one transaction per 50 videos instead of ~3 per video (keeps the API responsive)
                for i, e in enumerate(entries[start:start + 50], start=start):
                    _list_one(i, e)
            progress(0.05 + 0.9 * min(start + 50, len(entries)) / len(entries), f"listed {min(start + 50, len(entries))}/{len(entries)}")
        from . import candidates as _cand      # G3: every listed video is remembered cheaply, selected or not
        _cand.remember([{"external_id": e["id"], "url": e["url"], "title": e.get("title"), "description": e.get("description"), "duration": e.get("duration"),
                         "view_count": e.get("view_count"), "creator": info.get("title") if kind == "channel" else e.get("channel"), "published_at": e.get("published_at")}
                        for e in entries], "youtube", project_id, {"collection_id": coll["id"], "kind": kind, "title": coll.get("title")})
        if review and proposed:
            db.kv_set(f"review:{coll['id']}", json.dumps({"min_date": min_date, "newest_first": kind == "channel",
                                                          "project_id": project_id, "max_videos": mx, "ranked": False, "counts": counts}))
            db.create_job("rank_proposed", {"collection_id": coll["id"], "project_id": project_id, "want": mx})
        return {"kind": kind, "collection_id": coll["id"], "title": coll.get("title"),
                "found": total_found, "queued": queued, "proposed": proposed, "already_ingested": skipped, "counts": counts,
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
        counts = {"already_in_project": 0, "already_in_library": 0, "new": 0}
        member_ids = set(db.project_source_ids(project_id, ready_only=False)) if project_id else set()
        with db.batch():
            for e in entries:
                cand = identity.Candidate(platform="instagram", external_id=e["id"], url=e["url"], title=e.get("title"), tags=tags,
                                          fields={"duration": e.get("duration"), "description": e.get("description"), "view_count": e.get("view_count")})
                res = identity.resolve_or_create_source(cand, None, initial_status="proposed", resume_skipped=False)
                src = res.source
                db.link_source_collection(src["id"], coll["id"])
                if src["id"] in member_ids:
                    counts["already_in_project"] += 1
                elif res.state == identity.NEW:
                    counts["new"] += 1
                else:
                    counts["already_in_library"] += 1
                already = src["status"] != "proposed" and not force
                skipped += already
                proposed += not already
        from . import candidates as _cand
        _cand.remember([{"external_id": e["id"], "url": e["url"], "title": e.get("title"), "description": e.get("description"), "duration": e.get("duration"),
                         "view_count": e.get("view_count"), "creator": info.get("title")} for e in entries], "instagram", project_id,
                       {"collection_id": coll["id"], "kind": "instagram", "title": info.get("title")})
        db.kv_set(f"review:{coll['id']}", json.dumps({"min_date": min_date, "newest_first": True, "project_id": project_id,
                                                      "max_videos": mx, "ranked": False, "cookies_file": cookies_file,
                                                      "referer": info["url"], "counts": counts}))
        db.create_job("rank_proposed", {"collection_id": coll["id"], "project_id": project_id, "want": mx})
        return {"kind": "instagram_profile", "collection_id": coll["id"], "title": coll.get("title"), "found": len(entries),
                "proposed": proposed, "already_ingested": skipped, "counts": counts, "review": proposed > 0}
    platform = {"video": "youtube", "instagram": "instagram", "fixture": "fixture"}.get(kind, "media")
    ext_id = _external_id_from_url(url, platform)
    # G1: one resolution path for every entrance — identity first, then the five states
    res = identity.resolve_or_create_source(
        identity.Candidate(platform=platform, external_id=ext_id, url=url, title=title, canonical_url=url, tags=tags),
        project_id, retry=force)
    src = res.source
    identity.claim_job_for(src["id"])
    if collection_id:
        db.link_source_collection(src["id"], collection_id)
    if not force:
        if src["status"] == "ready":                                  # EXISTING_READY or ALREADY_IN_PROJECT: nothing to acquire
            return {"kind": kind, "source_id": src["id"], "title": src["title"], "identity": res.state, "already_ingested": True}
        if src["status"] == "failed" and res.state != identity.ALREADY_IN_PROJECT:
            # attached to the new project, acquisition NOT retried (that spends money): the failure is reported instead
            return {"kind": kind, "source_id": src["id"], "title": src["title"], "identity": res.state, "failed": True,
                    "error": src.get("error"), "note": "this source failed before; use Retry to try the acquisition again"}
        if src["status"] == "failed":                                 # re-added by the project that already has it = a retry request
            with db.tx() as conn:
                conn.execute("UPDATE sources SET status='pending', error=NULL, updated_at=? WHERE id=?", (db.now(), src["id"]))
        if identity.has_live_ingest_job(src["id"]):                   # another job owns it: shared work, this project waits
            return {"kind": kind, "source_id": src["id"], "title": src["title"], "identity": res.state, "already_pending": True,
                    "note": "already being ingested for another project; this project gets it when it finishes"}
    if force and not res.created:
        with db.tx() as conn:                                        # a forced re-ingest starts the stages over
            conn.execute("UPDATE sources SET stage=NULL, audio_path=NULL, status='pending', error=NULL WHERE id=?", (src["id"],))
    result = ingest_source(src["id"], progress=progress, cookies_file=cookies_file, referer=referer, keep_title=title)
    return {"kind": kind, "identity": res.state, **result}


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
    pid = meta.get("project_id") or db.collection_project(collection_id)
    if pid:
        # G3: skipped ≠ forgotten. The Candidate Index keeps every proposal with WHY it was not selected; chosen ones resolve to their source.
        from . import candidates as _cand
        rel = {r["id"]: (r.get("relevance"), r.get("relevance_why")) for r in rows}
        _cand.mark_by_source(pid, [r["id"] for r in rows if r["id"] in chosen], "acquired", "selected in review", rel)
        low = [r["id"] for r in rows if r["id"] not in chosen and r.get("relevance") is not None and r["relevance"] < _cand.LOW_RELEVANCE]
        rest = [r["id"] for r in rows if r["id"] not in chosen and r["id"] not in low]
        _cand.mark_by_source(pid, low, "skipped_low_relevance", "ranked below the relevance cutoff in review", rel)
        _cand.mark_by_source(pid, rest, "skipped_limit", "outside the number selected in review", rel)
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
    elif settings.allow_transcription and providers.openai_available():
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
    meta = {k: v for k, v in fields.items() if k not in ("platform", "external_id", "url", "title") and v is not None}
    cand = identity.Candidate(platform=fields["platform"], external_id=fields.get("external_id"), url=fields.get("url") or "",
                              title=fields.get("title"), canonical_url=media.canonical_url(fields["url"]) if fields.get("url", "").startswith("http") else None,
                              fingerprint=payload.get("fingerprint"), legacy_external_id=payload.get("legacy_external_id"),
                              tags=list(tags or []), fields=meta)
    res = identity.resolve_or_create_source(cand, project_id, retry=True)     # an explicit import always (re)stores the transcript
    src = res.source
    if src["status"] == "ready" and not payload.get("replace"):
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "transcript": src.get("transcript_kind"),
                "embedded": 0, "already_ingested": True, "identity": res.state}
    if meta:
        db.upsert_source(platform=src["platform"], external_id=src["external_id"], **meta)
    progress(0.85, "chunking…")
    chunks = build_chunks(segments, duration=fields.get("duration"), chapters=payload.get("chapters"))
    db.replace_transcript(src["id"], segments, chunks)
    db.upsert_source(platform=src["platform"], external_id=src["external_id"], status="ready", error=None)
    if collection and collection.get("kind"):
        coll = db.upsert_collection(collection["kind"], collection.get("external_id"), collection.get("url"), collection.get("title"))
        db.link_source_collection(src["id"], coll["id"])
        if project_id:
            db.add_project_collections(project_id, [coll["id"]])
    progress(0.9, "embedding…")
    n_emb = embed_pending(source_id=src["id"])
    progress(1.0, "done")
    _after_ready(src["id"], project_id)
    return {"source_id": src["id"], "title": src["title"], "segments": len(segments), "chunks": len(chunks),
            "transcript": fields.get("transcript_kind"), "embedded": n_emb, "identity": res.state}


def _after_ready(source_id: str, project_id: str | None = None) -> None:
    try:
        from .jobs import enqueue_suggestions
        enqueue_suggestions(source_id, project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("could not queue suggestions: %s", e)


def ingest_source(source_id: str, progress: Progress = _noop, cookies_file: str | None = None,
                  referer: str | None = None, keep_title: str | None = None, min_date: str | None = None,
                  collection_id: str | None = None, newest_first: bool = False) -> dict[str, Any]:
    """Staged, resumable ingestion of one linked source (Mission D3/D4):

        listed → metadata → transcript → chunks → embeddings → ready

    Each stage's durable data is committed together with the stage marker, so after a crash the job resumes at the
    first incomplete stage: a fetched transcript is never re-fetched, paid transcription is never paid twice,
    embeddings resume with only the missing chunks. Cancellation is honoured between stages."""
    from .jobs import check_cancel, crash_point, stage_event
    from .transcribe import transcribe_file

    src = db.get_source(source_id)
    if not src:
        raise RuntimeError(f"source {source_id} not found")
    if src["platform"] in ("spreadsheet", "document", "file", "manual"):
        db.set_source_status(source_id, "failed", "this is an uploaded file, not a link — use Retry on its row in Sources, or upload it again")
        raise RuntimeError("uploaded files can't be fetched like a link — use Retry on the source row, or upload the file again")
    if src["platform"] == "web":                                      # G3: pages proposed by an exploration are read by the page path
        if src["status"] == "proposed":
            db.set_source_status(source_id, "pending")
        return ingest_webpage(src["url"], tags=None, project_id=None, title=None, progress=progress, html=None)
    platform, url = src["platform"], src["url"]
    stage = db.stage_index(src.get("stage"))
    try:
        crash_point("before_metadata")
        # ---- metadata (atomic)
        if stage < db.stage_index("metadata"):
            check_cancel()
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
                db.set_source_status(source_id, "skipped", f"published {fields['published_at']}, before cutoff {min_date}")
                return {"source_id": source_id, "skipped": True, "reason": f"published {fields['published_at']}, before cutoff {min_date}"}
            fields["external_id"] = fields.get("external_id") or src["external_id"]
            if keep_title:
                fields["title"] = keep_title
            fields.pop("url", None)                                   # keep the url the user gave us
            with db.batch():
                db.upsert_source(**{**fields, "platform": platform, "external_id": src["external_id"]})
                db.set_stage(source_id, "metadata")
            db.kv_set(f"ingest_info:{source_id}", json.dumps({"chapters": info.get("chapters") or [], "language": info.get("language")}))
            stage_event("metadata")
            crash_point("metadata_complete")
            src = db.get_source(source_id) or src
        else:
            info = None
        # ---- transcript (atomic; the expensive step — captions or download + transcription)
        if stage < db.stage_index("transcript"):
            check_cancel()
            info = info or media.fetch_info(url, cookies_file=cookies_file, referer=referer) or {}
            progress(0.15, "looking for captions…")
            caps = media.fetch_captions(info, cookies_file=cookies_file)
            kind, lang = None, None
            audio = None
            if caps:
                segments, lang = caps
                kind = "captions"
            elif settings.allow_transcription and providers.openai_available():
                dur = (src.get("duration") or info.get("duration") or 0) / 60
                if dur > settings.max_transcribe_minutes:
                    raise RuntimeError(f"no captions and duration {dur:.0f} min exceeds transcription limit")
                from . import usage
                usage.guard(usage.estimate_transcription(src.get("duration") or info.get("duration")))
                audio = Path(src["audio_path"]) if src.get("audio_path") else None
                if not (audio and audio.exists()):
                    progress(0.2, "no captions; downloading audio…")
                    audio = media.download_audio(url, cookies_file=cookies_file, referer=referer)
                    db.set_audio_path(source_id, str(audio))            # durable: a retry reuses the download
                    stage_event("audio", "downloaded", path=str(audio))
                    crash_point("audio_downloaded")
                else:
                    progress(0.2, "reusing downloaded audio…")
                check_cancel()
                crash_point("transcription_before_response")
                segments, lang = transcribe_file(audio, progress=lambda p, m: progress(0.3 + 0.5 * p, m))
                kind = "transcribed"
            else:
                raise RuntimeError("no captions available and audio transcription is disabled (set OPENAI_API_KEY)")
            segments = normalize_segments(segments)
            if not segments:
                raise RuntimeError("transcript came back empty")
            with db.batch():
                db.replace_transcript(source_id, segments, [])                 # segments only; chunks are the next stage
                db.upsert_source(platform=platform, external_id=src["external_id"], transcript_kind=kind, language=lang or src.get("language"))
                db.set_stage(source_id, "transcript")
            stage_event("transcript", segments=len(segments), kind=kind)
            if audio is not None:                                          # the download served its purpose
                for p in (audio, audio.with_suffix(".segments.json")):
                    try:
                        p.unlink(missing_ok=True)
                    except OSError:
                        pass
                db.set_audio_path(source_id, None)
            crash_point("transcript_complete")
        # ---- chunks (atomic, derived deterministically from the stored segments)
        if stage < db.stage_index("chunks") or db.stage_index((db.get_source(source_id) or {}).get("stage")) < db.stage_index("chunks"):
            check_cancel()
            progress(0.85, "chunking…")
            segments = db.get_segments(source_id)
            meta = json.loads(db.kv_get(f"ingest_info:{source_id}") or "{}")
            chunks = build_chunks(segments, duration=(db.get_source(source_id) or {}).get("duration"), chapters=meta.get("chapters"))
            with db.batch():
                db.replace_chunks(source_id, chunks)
                db.set_stage(source_id, "chunks")
            stage_event("chunks", chunks=len(chunks))
            crash_point("chunks_complete")
        # ---- embeddings (granular: one chunk at a time is the checkpoint)
        progress(0.9, "embedding…")
        n_emb = embed_pending(source_id=source_id)
        with db.batch():
            db.set_stage(source_id, "embeddings")
            db.upsert_source(platform=platform, external_id=src["external_id"], status="ready", error=None)
            db.set_stage(source_id, "ready")
        db.kv_set(f"ingest_info:{source_id}", None)
        stage_event("ready", embedded=n_emb)
        progress(1.0, "done")
        _after_ready(source_id)
        final = db.get_source(source_id) or {}
        return {"source_id": source_id, "title": final.get("title"), "segments": len(db.get_segments(source_id)),
                "chunks": len(db.get_chunks(source_id)), "transcript": final.get("transcript_kind"), "embedded": n_emb}
    except Exception as e:  # noqa: BLE001
        from .jobs import Cancelled
        from .media import RateLimited
        from .breakers import ProviderUnavailable
        from .usage import BudgetPaused
        if isinstance(e, (RateLimited, BudgetPaused, Cancelled, ProviderUnavailable)):
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
    from .sheets import is_spreadsheet
    if is_spreadsheet(kind_path):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise RuntimeError("spreadsheet support needs a dependency that isn't installed yet — stop the server (Ctrl+C) "
                               "and run ./start once; it installs it, then Retry this file") from None
        return ingest_spreadsheet(path, title or kind_path.stem, tags, project_id, name)
    if kind_path.suffix.lower() == ".epub":
        return ingest_epub(path, title, tags, project_id, name, progress)
    if is_document(kind_path):
        return ingest_document(path, title or name, tags, project_id, name)
    if not is_media(kind_path):
        raise RuntimeError(f"unsupported file type: {kind_path.suffix or 'no extension'}")
    return _ingest_media_file(path, title or kind_path.stem, tags, project_id, name, progress)


def _embed_ready(source_id: str) -> int:
    """Embed a document/spreadsheet that is already READY (its text is stored and full-text searchable). An embedding
    failure — provider down, circuit open, budget paused — must not turn a readable document into a failed source:
    it is logged as a visible event and the chunks stay pending for the next `embed_pending` pass (0.24.1)."""
    try:
        return embed_pending(source_id=source_id)
    except Exception as e:  # noqa: BLE001
        log.warning("embeddings deferred for %s: %s", source_id, e)
        try:
            db.validation_event("embeddings_deferred", {"source_id": source_id, "error": str(e)[:200]})
            db.kv_bump("evidence:retrieval_degraded")
        except Exception:  # noqa: BLE001
            pass
        return 0


def ingest_spreadsheet(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str) -> dict[str, Any]:
    """A workbook: each sheet becomes a searchable page, and its formulas become a calculator the chat can run."""
    from .chunking import build_doc_chunks
    from .sheets import files_dir, read_workbook, save_model, store_file

    res = identity.resolve_or_create_source(identity.upload_candidate("spreadsheet", path, name, title, tags, "sheet"), project_id, retry=True)
    src, ext_id = res.source, res.source["external_id"]
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready":
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "transcript": "spreadsheet", "embedded": 0,
                "already_ingested": True, "identity": res.state}
    try:
        if path.parent != files_dir():
            path = store_file(path, src["id"], Path(name).suffix)      # keep the original so Retry works
        model = read_workbook(path)
        pages = [{"page": i + 1, "text": s["text"]} for i, s in enumerate(model["sheets"])]
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = build_doc_chunks(pages)
        db.replace_transcript(src["id"], segments, chunks)
        save_model(src["id"], path.name, model)
        db.upsert_source(platform="spreadsheet", external_id=ext_id, duration=None, transcript_kind="spreadsheet",
                         description=f"{len(pages)} sheet{'s' if len(pages) != 1 else ''} · {len(model['inputs'])} inputs · {len(model['outputs'])} calculated outputs",
                         status="ready", error=None)
        n = _embed_ready(src["id"])
        _after_ready(src["id"], project_id)
        return {"source_id": src["id"], "title": title, "segments": len(segments), "chunks": len(chunks),
                "transcript": "spreadsheet", "embedded": n, "inputs": len(model["inputs"]), "outputs": len(model["outputs"])}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_epub(path: Path, title: str | None, tags: list[str] | None, project_id: str | None, name: str, progress: Progress = _noop) -> dict[str, Any]:
    """G6P1 — an EPUB as a structured publication: spine order, chapters/sections with anchors as locators, publication
    metadata on the source, and ($0) the Work it manifests when the package names an ISBN or a title + creator. Same
    identity/revision lifecycle as every other upload (content fingerprint); same chunking; embeddings deferred on failure."""
    from . import epub, works
    from .chunking import build_doc_chunks
    res = identity.resolve_or_create_source(identity.upload_candidate("book", path, name, title, tags, "epub"), project_id, retry=True)
    src, ext_id = res.source, res.source["external_id"]
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready":
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "transcript": "epub", "embedded": 0, "already_ingested": True, "identity": res.state}
    try:
        progress(0.1, "reading the package…")
        book = epub.read_epub(path)
        md = book["metadata"]
        locs = epub.locators(book)
        pages = [{"page": lo["ordinal"], "text": lo["text"]} for lo in locs if lo["text"]]
        if not pages or sum(len(p["text"]) for p in pages) < 200:
            raise RuntimeError("the EPUB has no readable text (image-only pages, or an empty package)")
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = [c for p in pages for c in build_doc_chunks([p])]          # a chunk never crosses a section: the locator stays exact
        book_title = title or md.get("title") or Path(name).stem
        if md.get("subtitle") and not title:
            book_title = f"{book_title}: {md['subtitle']}"
        creators = ", ".join(md.get("creators") or [])
        with db.batch():
            db.replace_transcript(src["id"], segments, chunks)
            conn = db.connect()
            conn.execute("DELETE FROM book_sections WHERE source_id=?", (src["id"],))
            conn.executemany("INSERT INTO book_sections (source_id, ordinal, spine_index, href, fragment, chapter, chapter_no, section, role, depth, label, chars) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             [(src["id"], lo["ordinal"], lo["spine_index"], lo["href"], lo["fragment"], lo["chapter"], lo["chapter_no"], lo["section"], lo["role"], lo["depth"], lo["label"], len(lo["text"])) for lo in locs])
            desc = f"EPUB {md.get('version') or ''}".strip() + f" · {book['chapters']} chapter{'s' if book['chapters'] != 1 else ''} · {book['sections']} sections" \
                   + (f" · {md['publisher']}" if md.get("publisher") else "") + (f" · ISBN {md['isbn']}" if md.get("isbn") else "") + (f" · {md['edition']}" if md.get("edition") else "")
            db.upsert_source(platform="book", external_id=ext_id, title=book_title, channel=creators or None, published_at=(md.get("date") or "")[:10] or None,
                             language=md.get("language"), transcript_kind="epub", description=desc, status="ready", error=None, error_class=None,
                             completeness=json.dumps({"status": "complete", "captured": book["sections"], "expected": book["sections"], "method": "epub", "warnings": book["warnings"][:10]}))
        progress(0.6, "linking the Work…")
        work = None
        try:
            idents = [{"scheme": "isbn", "value": md["isbn"]}] if md.get("isbn") else None
            if idents or (md.get("title") and md.get("creators")):
                w, _created = works.ensure_work("book", md.get("title") or book_title, identifiers=idents, creators=md.get("creators") or None,
                                                publisher=md.get("publisher"), year=(md.get("date") or "")[:4] or None)
                vid = None
                label = md.get("edition") or ((md.get("date") or "")[:4] + " edition" if md.get("date") else None)
                if label:
                    vid = works.ensure_version(w["id"], label, edition=md.get("edition"), year=(md.get("date") or "")[:4] or None)["id"]
                works.link_source(src["id"], w["id"], version_id=vid, relation="manifestation_of", form="epub", confidence="identifier" if idents else "title_creator",
                                  basis={"isbn": md.get("isbn"), "package_id": md.get("package_id"), "publisher": md.get("publisher")})
                work = {"id": w["id"], "title": w.get("title"), "version": label, "by": "isbn" if idents else "title+creator"}
        except Exception as e:  # noqa: BLE001
            log.warning("epub work link skipped: %s", e)
        progress(0.7, "embedding…")
        n = _embed_ready(src["id"])
        _after_ready(src["id"], project_id)
        return {"source_id": src["id"], "title": book_title, "segments": len(segments), "chunks": len(chunks), "transcript": "epub", "embedded": n,
                "chapters": book["chapters"], "sections": book["sections"], "toc_depth": book["toc_depth"], "metadata": md, "warnings": book["warnings"], "work": work, "identity": res.state}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_document(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str) -> dict[str, Any]:
    from .chunking import build_doc_chunks
    from .documents import extract_pages

    res = identity.resolve_or_create_source(identity.upload_candidate("document", path, name, title, tags, "doc"), project_id, retry=True)
    src, ext_id = res.source, res.source["external_id"]
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready":
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "transcript": "document", "embedded": 0,
                "already_ingested": True, "identity": res.state}
    try:
        pages = extract_pages(path)
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = build_doc_chunks(pages)
        db.replace_transcript(src["id"], segments, chunks)
        db.upsert_source(platform="document", external_id=ext_id, duration=None, transcript_kind="document",
                         description=f"{len(pages)} pages", status="ready", error=None)
        n = _embed_ready(src["id"])
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

    url = media.canonical_url(url)
    ext_id = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    res = identity.resolve_or_create_source(identity.Candidate(platform="web", external_id=ext_id, url=url, title=title, canonical_url=url, tags=tags or []),
                                            project_id, retry=html is not None)      # a page the user SENT is always re-read (new revision)
    src = res.source
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready" and html is None:
        return {"kind": "web", "source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "transcript": src.get("transcript_kind"),
                "embedded": 0, "already_ingested": True, "identity": res.state}
    if res.state == identity.EXISTING_PENDING and not res.resumed and identity.has_live_ingest_job(src["id"]):
        return {"kind": "web", "source_id": src["id"], "title": src["title"], "already_pending": True, "identity": res.state}
    try:
        progress(0.1, "fetching page…")
        page = read_page(url, html_text=html)
        pages = page["pages"]
        segments = [{"start": float(p["page"]), "end": float(p["page"]), "text": " ".join(p["text"].split())} for p in pages]
        chunks = build_doc_chunks(pages)
        db.replace_transcript(src["id"], segments, chunks)
        db.upsert_source(platform="web", external_id=ext_id, title=title or page["title"], url=page["url"],
                         transcript_kind=page["kind"], description=f"{len(pages)} sections",
                         channel=urlparse(page["url"]).netloc.replace("www.", ""), status="ready", error=None, error_class=None)
        progress(0.7, "embedding…")
        n = _embed_ready(src["id"])
        _after_ready(src["id"], project_id)
        return {"kind": "web", "source_id": src["id"], "title": title or page["title"], "segments": len(segments),
                "chunks": len(chunks), "transcript": page["kind"], "embedded": n, "identity": res.state}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_subtitle_file(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str) -> dict[str, Any]:
    raw = path.read_text(errors="replace")
    if not raw.lstrip().startswith("WEBVTT"):  # srt -> vtt-ish: timestamps use commas
        raw = "WEBVTT\n\n" + re.sub(r"(\d\d:\d\d:\d\d),(\d{3})", r"\1.\2", raw)
    segments = media.parse_vtt(raw)
    cand = identity.upload_candidate("file", path, name, title, tags, "sub")
    payload = {"platform": "file", "external_id": cand.external_id, "url": f"file://{name}", "fingerprint": cand.fingerprint,
               "legacy_external_id": cand.legacy_external_id,
               "title": title, "duration": segments[-1]["end"] if segments else None, "transcript_kind": "captions",
               "segments": segments, "chapters": []}
    return store_transcript(payload, tags=tags, project_id=project_id)


def _ingest_media_file(path: Path, title: str, tags: list[str] | None, project_id: str | None, name: str,
                       progress: Progress) -> dict[str, Any]:
    """Transcribe an uploaded audio/video file."""
    res = identity.resolve_or_create_source(identity.upload_candidate("file", path, name, title, tags, "file"), project_id, retry=True)
    src, ext_id = res.source, res.source["external_id"]
    identity.claim_job_for(src["id"])
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready":
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "embedded": 0, "already_ingested": True,
                "identity": res.state, "note": "this file was transcribed before — nothing was paid for again"}
    if res.state in (identity.EXISTING_PENDING, identity.ALREADY_IN_PROJECT) and not res.resumed and identity.has_live_ingest_job(src["id"]):
        return {"source_id": src["id"], "title": src["title"], "already_pending": True, "identity": res.state,
                "note": "this file is already being transcribed; it joins the project when it finishes"}
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
        n = _embed_ready(src["id"])
        _after_ready(src["id"], project_id)
        return {"source_id": src["id"], "title": src["title"], "segments": len(segments), "chunks": len(chunks), "embedded": n, "identity": res.state}
    except Exception as e:  # noqa: BLE001
        db.set_source_status(src["id"], "failed", str(e)[:1000])
        raise


def ingest_text(title: str, text: str, url: str | None = None, tags: list[str] | None = None,
                project_id: str | None = None) -> dict[str, Any]:
    """Store a transcript you already have. Lines starting with a timestamp like `12:34 ` or `[1:02:03]` are honoured."""
    segments = _parse_timestamped_text(text)
    fp = identity.fingerprint_text(title or "", text)
    ext_id = f"text:{fp[7:23]}"                                       # stable across restarts (the old key was process-salted)
    res = identity.resolve_or_create_source(identity.Candidate(platform="manual", external_id=ext_id, url=url or f"manual://{ext_id}", title=title,
                                                               fingerprint=fp, tags=list(tags or [])), project_id, retry=True)
    src = res.source
    if res.state in (identity.EXISTING_READY, identity.ALREADY_IN_PROJECT) and src["status"] == "ready":
        return {"source_id": src["id"], "title": src["title"], "segments": 0, "chunks": 0, "embedded": 0, "already_ingested": True, "identity": res.state}
    duration = segments[-1]["end"] if segments and segments[-1]["end"] > 0 else None
    chunks = build_chunks(segments, duration=duration or 10 ** 6)  # force long-form windowing by chars if untimed
    db.replace_transcript(src["id"], segments, chunks)
    db.upsert_source(platform="manual", external_id=ext_id, duration=duration, transcript_kind="manual", status="ready")
    n = _embed_ready(src["id"])
    _after_ready(src["id"], project_id)
    return {"source_id": src["id"], "title": title, "segments": len(segments), "chunks": len(chunks), "embedded": n, "identity": res.state}


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
    if platform == "fixture":
        return url
    return media.canonical_url(url)
