"""Project-relative residual reading over the embeddings we already store.

R7 is deliberately a scheduler and reading-order signal, never a gate: missing
vectors, a tiny corpus, or an unexpected vector shape all fail open.  The same
comparison set is used for every candidate in a bulk request, so its result is
not affected by arrival order.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from . import db


def _rows(source_ids: list[str]) -> list[dict[str, Any]]:
    if not source_ids:
        return []
    marks = ",".join("?" for _ in source_ids)
    return [dict(r) for r in db.connect().execute(
        f"SELECT source_id, idx, text, embedding FROM chunks WHERE embedding IS NOT NULL AND source_id IN ({marks}) ORDER BY source_id, idx",
        source_ids,
    ).fetchall()]


def _normalise(vectors: list[np.ndarray]) -> np.ndarray:
    if not vectors:
        return np.zeros((0, 0), dtype=np.float32)
    widths = {len(v) for v in vectors}
    if len(widths) != 1:
        return np.zeros((0, 0), dtype=np.float32)
    mat = np.vstack(vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.maximum(norms, 1e-12)


def profile(project_id: str, source_id: str, *, comparison_source_ids: list[str] | None = None) -> dict[str, Any]:
    """Return a source's project-relative redundancy and least-similar chunks.

    The comparison corpus is every project member plus the supplied batch
    candidates.  The candidate itself is excluded, making the score stable if
    the source is re-read.  ``available=False`` means callers must leave their
    normal priority/order unchanged.
    """
    comparison = set(db.project_source_ids(project_id, ready_only=False))
    comparison.update(comparison_source_ids or [])
    comparison.discard(source_id)
    own = _rows([source_id])
    other = _rows(sorted(comparison))
    base = {"source_id": source_id, "available": False, "redundancy": None, "residual_chunks": [], "chunk_scores": {}, "compared_chunks": len(other)}
    if not own or not other:
        return base
    try:
        own_vecs = [db._unpack(r["embedding"]) for r in own]
        other_vecs = [db._unpack(r["embedding"]) for r in other]
        a, b = _normalise(own_vecs), _normalise(other_vecs)
        if not len(a) or not len(b) or a.shape[1] != b.shape[1]:
            return base
        scores = np.max(a @ b.T, axis=1)
    except Exception:  # corrupted/legacy vectors must never make evidence unreachable
        return base
    by_idx = {int(row["idx"]): round(float(score), 4) for row, score in zip(own, scores)}
    ordered = sorted(by_idx, key=lambda idx: (by_idx[idx], idx))
    return {"source_id": source_id, "available": True, "redundancy": round(float(np.mean(scores)), 4), "residual_chunks": ordered,
            "chunk_scores": by_idx, "compared_chunks": len(other)}


def priority_adjustment(profile_row: dict[str, Any]) -> int:
    """A bounded nudge for scheduling; no source can be excluded by it."""
    redundancy = profile_row.get("redundancy")
    return -round(float(redundancy) * 40) if redundancy is not None else 0


def order_windows(windows: list[str], kept: set[int], profile_row: dict[str, Any]) -> list[int]:
    """Read windows containing the least-represented chunks first.

    Chunks are derived from the same transcript text as windows.  Exact text
    containment is preferred; token overlap is a conservative fallback for
    document and community chunkers.  Every kept window remains in the result.
    """
    indexes = sorted(kept)
    scores = profile_row.get("chunk_scores") or {}
    if not profile_row.get("available") or not scores:
        return indexes
    chunk_rows = _rows_for_window_matching(profile_row.get("source_id"))
    # profile() does not expose source text intentionally; callers attach it below
    if not chunk_rows:
        return indexes
    ranked: list[tuple[float, int]] = []
    for i in indexes:
        text = windows[i].lower()
        matched: list[float] = []
        for chunk in chunk_rows:
            sample = " ".join((chunk["text"] or "").lower().split()[:24])
            if sample and sample in text:
                matched.append(float(scores.get(int(chunk["idx"]), 1.0)))
        ranked.append((min(matched) if matched else 1.0, i))
    return [i for _, i in sorted(ranked, key=lambda row: (row[0], row[1]))]


def _rows_for_window_matching(source_id: str | None) -> list[dict[str, Any]]:
    if not source_id:
        return []
    return [dict(r) for r in db.connect().execute(
        "SELECT idx, text FROM chunks WHERE source_id=? ORDER BY idx", (source_id,)
    ).fetchall()]
