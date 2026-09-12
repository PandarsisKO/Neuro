"""Transcript Intelligence T1: resumable, low-lane derived-object embedding backfill."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import db, jobs
from .config import settings

VECTOR_VERSION = "t1-derived-v1"


def input_hash(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enqueue_backfill(project_id: str, limit: int = 5000) -> list[dict[str, Any]]:
    """Queue only canonical rows without a current vector; low lane makes this work yield to user tasks."""
    conn = db.connect()
    out = []
    for table, statuses, text_col, meta_col in (("project_notes", ("approved", "suggested"), "content", "citations"),
                                                 ("project_claims", ("proposed", "accepted"), "text", "qualifiers")):
        qs = ",".join("?" for _ in statuses)
        rows = conn.execute(f"""SELECT id, {text_col} AS text, {meta_col} AS metadata FROM {table}
            WHERE project_id=? AND status IN ({qs}) AND embedding IS NULL LIMIT ?""",
                          (project_id, *statuses, max(0, limit - len(out)))).fetchall()
        for row in rows:
            ih = input_hash(row["text"] or "", row["metadata"] or "")
            out.append(jobs.enqueue("t1_embed_derived", {
                "project_id": project_id, "table": table, "object_id": row["id"], "text": row["text"] or "",
                "input_hash": ih, "provider": "openai", "model": settings.embedding_model,
                "version": VECTOR_VERSION,
            }, lane="low"))
    return out
