"""Hybrid retrieval: BM25 keyword search + vector similarity, fused with reciprocal rank fusion."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import numpy as np

from . import db
from .chunking import fmt_locator, fmt_ts
from .config import settings

log = logging.getLogger(__name__)


def deep_link(url: str, platform: str, start: float) -> str:
    """URL that opens the source at the right moment where the platform supports it."""
    t = int(max(0, start))
    if platform == "youtube":
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}t={t}s"
    host = urlparse(url).netloc
    if "vimeo.com" in host:
        return f"{url}#t={t}s"
    if "loom.com" in host:
        base = url.split("?")[0]
        return f"{base}?t={t}"
    if url.startswith(("http://", "https://")) and platform == "media":
        return f"{url}#t={t}"
    return url


def hit_from_chunk(c: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "chunk_id": c["id"],
        "source_id": c["source_id"],
        "title": c.get("title") or c.get("url"),
        "channel": c.get("channel"),
        "platform": c.get("platform"),
        "published_at": c.get("published_at"),
        "url": c.get("url"),
        "start": c["start"],
        "end": c["end"],
        "timestamp": fmt_locator(c.get("platform") or "", c["start"]),
        "link": deep_link(c["url"], c.get("platform") or "", c["start"]),
        "text": c["text"],
        "score": round(float(score), 4),
    }


def search(query: str, limit: int = 12, source_ids: list[str] | None = None,
           per_source_cap: int | None = 4) -> list[dict[str, Any]]:
    """Return ranked chunk hits with source metadata and deep links."""
    query = query.strip()
    if not query:
        return []
    k = max(limit * 4, 40)
    ranked: dict[int, float] = {}

    fts = db.fts_search(query, limit=k, source_ids=source_ids)
    for rank, (cid, _score) in enumerate(fts):
        ranked[cid] = ranked.get(cid, 0.0) + 1.0 / (60 + rank)

    if settings.embeddings_enabled:
        try:
            from .embeddings import embed_query
            qv = embed_query(query)
            mat, ids = db.load_embedding_matrix(source_ids)
            if len(ids):
                sims = mat @ qv
                top = np.argsort(-sims)[:k]
                for rank, i in enumerate(top):
                    if sims[i] < 0.15:
                        break
                    cid = ids[int(i)]
                    ranked[cid] = ranked.get(cid, 0.0) + 1.0 / (60 + rank) * 1.1
        except Exception as e:  # noqa: BLE001
            log.warning("vector search unavailable: %s", e)

    if not ranked:
        return []
    order = sorted(ranked.items(), key=lambda kv: -kv[1])
    chunks = db.get_chunks_by_ids([cid for cid, _ in order[: k * 2]])
    hits: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    for cid, score in order:
        c = chunks.get(cid)
        if not c:
            continue
        if per_source_cap and per_source.get(c["source_id"], 0) >= per_source_cap:
            continue
        per_source[c["source_id"]] = per_source.get(c["source_id"], 0) + 1
        hits.append(hit_from_chunk(c, score))
        if len(hits) >= limit:
            break
    return hits


def source_transcript(source_id: str, with_timestamps: bool = True) -> str:
    segs = db.get_segments(source_id)
    src = db.get_source(source_id) or {}
    if with_timestamps:
        return "\n".join(f"[{fmt_locator(src.get('platform') or '', s['start'])}] {s['text']}" for s in segs)
    return " ".join(s["text"] for s in segs)
