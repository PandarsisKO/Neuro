"""OpenAI embeddings for chunks. Optional: without OPENAI_API_KEY the system falls back to keyword search only."""
from __future__ import annotations

import logging

import numpy as np

from . import db
from .config import settings

log = logging.getLogger(__name__)
BATCH = 96


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    out: list[np.ndarray] = []
    for i in range(0, len(texts), BATCH):
        batch = [t[:8000] for t in texts[i:i + BATCH]]
        res = client.embeddings.create(model=settings.embedding_model, input=batch)
        try:
            from . import usage
            usage.record("embed", settings.embedding_model, input_tokens=int(getattr(getattr(res, "usage", None), "total_tokens", 0) or 0))
        except Exception:  # noqa: BLE001
            pass
        for d in sorted(res.data, key=lambda d: d.index):
            v = np.asarray(d.embedding, dtype=np.float32)
            out.append(v / (np.linalg.norm(v) or 1.0))
    return out


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]


def embed_pending(limit: int = 5000) -> int:
    """Embed every chunk that doesn't have a vector yet. Returns count embedded."""
    if not settings.embeddings_enabled:
        return 0
    done = 0
    while done < limit:
        rows = db.chunks_missing_embeddings(limit=min(BATCH * 4, limit - done))
        if not rows:
            break
        vecs = embed_texts([r["text"] for r in rows])
        db.set_embeddings(list(zip([r["id"] for r in rows], vecs)))
        done += len(rows)
    return done
