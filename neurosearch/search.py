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


def _community_locator(c: dict[str, Any]) -> tuple[str, str] | None:
    """G7: a community chunk cites the POST — 'comment 12 by author' with the comment's own permalink."""
    from . import db as _db
    r = _db.connect().execute("SELECT kind, author, permalink, corrected_by, availability FROM community_posts WHERE source_id=? AND ordinal=?", (c["source_id"], int(c["start"]))).fetchone()
    if not r:
        return None
    label = ("post" if r["kind"] == "post" else f"comment {int(c['start'])}") + (f" by {r['author']}" if r["author"] else "") + (" (corrected in thread)" if r["corrected_by"] else "") + (" (now unavailable)" if r["availability"] == "unavailable" else "")
    return label, (r["permalink"] or c["url"])


def _book_locator(c: dict[str, Any]) -> tuple[str, str] | None:
    """G6P1: a book chunk cites the publication's own structure — 'Ch. 3 → Title · Section' — with the anchor as the deep link."""
    from . import db as _db
    r = _db.connect().execute("SELECT label, href, fragment FROM book_sections WHERE source_id=? AND ordinal=?", (c["source_id"], int(c["start"]))).fetchone()
    if not r:
        return None
    return r["label"], f"#book/{c['source_id']}/{int(c['start'])}"      # an in-app deep link: the UI opens the book at that section (G6P2)


def locator_for(source_id: str, url: str, platform: str, start: float) -> tuple[str, str | None]:
    """(human label, deep link) for a position in a source — the publication's own structure where it has one."""
    c = {"source_id": source_id, "url": url, "start": start}
    if platform == "book":
        loc = _book_locator(c)
        if loc:
            return loc
    if platform == "community":
        loc = _community_locator(c)
        if loc:
            return loc
    return fmt_locator(platform, start), deep_link(url, platform, start)


def hit_from_chunk(c: dict[str, Any], score: float) -> dict[str, Any]:
    if (c.get("platform") or "") == "book":
        loc = _book_locator(c)
        if loc:
            return {"chunk_id": c["id"], "source_id": c["source_id"], "title": c.get("title") or c.get("url"), "channel": c.get("channel"), "platform": "book",
                    "published_at": c.get("published_at"), "url": c.get("url"), "start": c["start"], "end": c["end"], "timestamp": loc[0], "link": loc[1],
                    "text": c["text"], "score": round(float(score), 4)}
    if (c.get("platform") or "") == "community":
        loc = _community_locator(c)
        if loc:
            return {"chunk_id": c["id"], "source_id": c["source_id"], "title": c.get("title") or c.get("url"), "channel": c.get("channel"), "platform": "community",
                    "published_at": c.get("published_at"), "url": c.get("url"), "start": c["start"], "end": c["end"], "timestamp": loc[0], "link": loc[1],
                    "text": c["text"], "score": round(float(score), 4)}
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


class RetrievalUnavailable(RuntimeError):
    """Vector search could not run (embedding endpoint down, etc.). Raised only in strict mode; the default path
    degrades to FTS-only and records evidence:retrieval_degraded so the degradation is visible in Health."""


PRIORITY_RESERVE = 5     # of the excerpt slots, at most this many are reserved for priority sources' best matches (0.24.1)


def search(query: str, limit: int = 12, source_ids: list[str] | None = None,
           per_source_cap: int | None = 4, strict: bool = False, rerank: bool | None = None,
           priority_ids: set[str] | None = None, reserve: int = PRIORITY_RESERVE) -> list[dict[str, Any]]:
    """Return ranked chunk hits with source metadata and deep links. strict=True: a vector-search failure is an error,
    never a silent FTS-only result (frozen research for evals must not depend on a flaky endpoint).
    rerank: the I2 candidate-only reranker stage (None = settings.retrieval_rerank, off by default); it reorders the first
    rerank.RERANK_DEPTH hits and fails closed to this function's own ordering.
    priority_ids: the project's priority sources (0.24.1). Up to `reserve` of the `limit` slots go to their best-matching
    chunks first (only chunks that matched the query at all — a priority source with nothing relevant contributes
    nothing); the remaining slots are filled in plain score order and the final list is re-sorted by score, so the
    numbering stays meaningful. Hits from priority sources carry priority=True."""
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
            if strict:
                raise RetrievalUnavailable(f"vector search unavailable: {e}") from e
            log.warning("vector search unavailable: %s", e)
            try:
                db.kv_bump("evidence:retrieval_degraded")           # visible: Health counts FTS-only fallbacks
            except Exception:  # noqa: BLE001
                pass

    if not ranked:
        return []
    order = sorted(ranked.items(), key=lambda kv: -kv[1])
    chunks = db.get_chunks_by_ids([cid for cid, _ in order[: k * 2]])
    # G6P2: a book passage is weighed by its structural role (an index entry never outranks the chapter it points to)
    book_ids = {c["source_id"] for c in chunks.values() if (c.get("platform") or "") == "book"}
    if book_ids:
        from .epub import role_weight, section_roles
        roles = {sid: section_roles(sid) for sid in book_ids}
        order = sorted(((cid, sc * role_weight(roles[chunks[cid]["source_id"]].get(int(chunks[cid]["start"]))) if cid in chunks and chunks[cid]["source_id"] in roles else sc)
                        for cid, sc in order), key=lambda kv: -kv[1])
    hits: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    taken: set[int] = set()
    if priority_ids and reserve > 0:
        for cid, score in order:
            c = chunks.get(cid)
            if not c or c["source_id"] not in priority_ids:
                continue
            if per_source_cap and per_source.get(c["source_id"], 0) >= per_source_cap:
                continue
            per_source[c["source_id"]] = per_source.get(c["source_id"], 0) + 1
            hits.append({**hit_from_chunk(c, score), "priority": True})
            taken.add(cid)
            if len(hits) >= min(reserve, limit):
                break
    for cid, score in order:
        if cid in taken:
            continue
        c = chunks.get(cid)
        if not c:
            continue
        if per_source_cap and per_source.get(c["source_id"], 0) >= per_source_cap:
            continue
        per_source[c["source_id"]] = per_source.get(c["source_id"], 0) + 1
        h = hit_from_chunk(c, score)
        if priority_ids and c["source_id"] in priority_ids:
            h["priority"] = True
        hits.append(h)
        if len(hits) >= limit:
            break
    hits.sort(key=lambda h: -h["score"])
    use_rerank = settings.retrieval_rerank if rerank is None else rerank
    from . import rerank as R
    if use_rerank and hits:
        hits = R.rerank(query, hits)
    else:
        R.clear_last()
    return hits


def source_transcript(source_id: str, with_timestamps: bool = True) -> str:
    segs = db.get_segments(source_id)
    src = db.get_source(source_id) or {}
    if with_timestamps:
        if src.get("platform") == "book":
            labels = {r["ordinal"]: r["label"] for r in db.connect().execute("SELECT ordinal, label FROM book_sections WHERE source_id=?", (source_id,)).fetchall()}
            return "\n".join(f"[{labels.get(int(s['start'])) or fmt_locator('book', s['start'])}] {s['text']}" for s in segs)
        return "\n".join(f"[{fmt_locator(src.get('platform') or '', s['start'])}] {s['text']}" for s in segs)
    return " ".join(s["text"] for s in segs)
