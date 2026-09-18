"""Conversation Delta (docs/CHAT-REFRESH-PLAN.md). CHR0 (this file's first rung): the BASELINE — what a
successfully completed assistant turn could actually know, recorded in messages.meta.evidence so a later delta
can be a set difference against facts instead of a guess against timestamps.

Kyle's north star for the whole mission: *"More newly ingested material is not itself value. Changed understanding
is value."* — which is only decidable if we know what the earlier answer was shown. CHR0 records that; it changes
nothing about retrieval, prompting, ranking, Claims or the answer text (plan §2, last bullet).

The snapshot is taken from the FINAL ctx["hits"] — the initial retrieval plus every search_library addition plus
every chunk of a full-context turn — because all of those were in the prompt and could be cited as [n]. Cited
excerpts are therefore always a subset of shown ones, which the CHR0 gate asserts.
"""
from __future__ import annotations

import logging
from typing import Any

from . import db

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def evidence_snapshot(*, project_id: str | None, scope_source_ids: list[str] | None, retrieval_query: str,
                      hits: list[dict[str, Any]], full_context: bool, question_message_id: int | None) -> dict[str, Any]:
    """Build the meta.evidence block for an assistant turn that FINISHED. Never raises for the caller's sake: a
    snapshot that cannot be completed degrades to what could be read, and the answer is saved either way."""
    shown_chunk_ids = sorted({int(h["chunk_id"]) for h in hits if h.get("chunk_id") is not None})
    shown_source_ids = sorted({str(h["source_id"]) for h in hits if h.get("source_id")})
    scope = [s for s in (scope_source_ids or []) if s and s != "__none__"]
    snap: dict[str, Any] = {
        "v": SNAPSHOT_VERSION,
        "answered_at": db.now(),
        "retrieval_query": retrieval_query or "",
        "scope_source_ids": scope,
        "shown_chunk_ids": shown_chunk_ids,
        "shown_source_ids": shown_source_ids,
        "full_context": bool(full_context),
        "question_message_id": question_message_id,
        "research_revision": None,
        "max_claim_evidence_id": None,
        "claim_state": {},
    }
    if not project_id:
        return snap
    try:
        snap["research_revision"] = db.project_research_revision(project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: research revision unavailable: %s", e)
    try:
        conn = db.connect()
        r = conn.execute("SELECT COALESCE(MAX(ce.id), 0) m FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id "
                         "WHERE c.project_id=?", (project_id,)).fetchone()
        snap["max_claim_evidence_id"] = int(r["m"] or 0)
        # The state of every Claim whose evidence touches a source the model was shown: a later strength/freshness/
        # status/application change is then a TRANSITION the delta can name (plan §6 category 3), not an updated_at.
        if shown_source_ids:
            rows = conn.execute(
                "SELECT DISTINCT c.id, c.strength, c.freshness_status, c.status, c.application FROM project_claims c "
                "JOIN claim_evidence ce ON ce.claim_id=c.id WHERE c.project_id=? AND ce.source_id IN (%s)"
                % ",".join("?" * len(shown_source_ids)), (project_id, *shown_source_ids)).fetchall()
            snap["claim_state"] = {r["id"]: [r["strength"], r["freshness_status"], r["status"], r["application"]] for r in rows}
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: claim state unavailable: %s", e)
    return snap
