"""Transcript Intelligence T1: resumable, low-lane derived-object embedding backfill."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from . import db
from .config import settings

VECTOR_VERSION = "t1-derived-v1"
CORPUS_ATTESTATION_KEY = "t1:corpus-space-attestation"


def input_hash(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enqueue_backfill(project_id: str, limit: int = 5000) -> list[dict[str, Any]]:
    """Queue only canonical rows without a current vector; low lane makes this work yield to user tasks."""
    conn = db.connect()
    out = []
    for table, statuses, text_col, meta_col, revision_cols in (("project_notes", ("approved", "suggested"), "content", "citations", ("source_revision", "brief_revision")),
                                                               ("project_claims", ("proposed", "accepted"), "text", "qualifiers", ("extraction_hash", "updated_at"))):
        qs = ",".join("?" for _ in statuses)
        rows = conn.execute(f"""SELECT id, {text_col} AS text, {meta_col} AS metadata, {revision_cols[0]} AS rev_a,
            {revision_cols[1]} AS rev_b FROM {table}
            WHERE project_id=? AND status IN ({qs}) AND embedding IS NULL LIMIT ?""",
                          (project_id, *statuses, max(0, limit - len(out)))).fetchall()
        for row in rows:
            ih = input_hash(row["text"] or "", row["metadata"] or "", row["rev_a"], row["rev_b"])
            payload = {
                "project_id": project_id, "table": table, "object_id": row["id"], "text": row["text"] or "",
                "input_hash": ih, "provider": "openai", "model": settings.embedding_model,
                "revision_a": row["rev_a"], "revision_b": row["rev_b"],
                "version": VECTOR_VERSION,
            }
            out.append(db.create_job("t1_embed_derived", payload,
                                     dedupe_key=f"t1-embed:{table}:{row['id']}:{ih}:{VECTOR_VERSION}", lane="low"))
    return out


def backfill_preview(project_id: str) -> dict[str, Any]:
    """Return the billable T1 scope without queuing or running anything."""
    conn = db.connect()
    counts = {}
    for table, statuses in (("project_notes", ("approved", "suggested")), ("project_claims", ("proposed", "accepted"))):
        qs = ",".join("?" for _ in statuses)
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND status IN ({qs}) AND embedding IS NULL",
                         (project_id, *statuses)).fetchone()[0]
        counts[table] = int(n)
    total = sum(counts.values())
    return {"project_id": project_id, "rows": counts, "total_rows": total,
            "embedding_batches_at_96": (total + 95) // 96, "queued": 0, "executed": 0,
            "model": settings.embedding_model, "version": VECTOR_VERSION}


def coverage_report(project_id: str) -> dict[str, Any]:
    """Read-only T1 measurement scaffold; semantic coverage stays unavailable until chunk-space attestation exists."""
    conn = db.connect()
    claims = conn.execute("SELECT COUNT(*) FROM project_claims WHERE project_id=? AND status IN ('proposed','accepted')", (project_id,)).fetchone()[0]
    findings = conn.execute("SELECT COUNT(*) FROM project_notes WHERE project_id=? AND status IN ('approved','suggested')", (project_id,)).fetchone()[0]
    claim_locators = conn.execute("SELECT COUNT(*) FROM claim_evidence ce JOIN project_claims pc ON pc.id=ce.claim_id WHERE pc.project_id=? AND pc.status IN ('proposed','accepted')", (project_id,)).fetchone()[0]
    finding_locators = conn.execute("SELECT COUNT(*) FROM project_notes WHERE project_id=? AND status IN ('approved','suggested') AND citations IS NOT NULL AND citations NOT IN ('', '[]')", (project_id,)).fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks c JOIN project_sources ps ON ps.source_id=c.source_id WHERE ps.project_id=? AND ps.excluded=0", (project_id,)).fetchone()[0]
    attestation = get_chunk_space_attestation()
    report = {"project_id": project_id, "status": "ready_for_measurement" if attestation else "measurement_pending", "chunks": chunk_count,
            "canonical_claims": claims, "canonical_findings": findings,
            "claim_locator_rows": claim_locators, "finding_locator_rows": finding_locators, "semantic_distributions": None,
            "corpus_space": attestation,
            "reason": None if attestation else "corpus-space attestation required before similarity comparisons"}
    if attestation:
        report["semantic_distributions"] = measure_project(project_id, provider=attestation["provider"],
                                                             model=attestation["model"], dimensions=int(attestation["dimensions"]))
    return report


def measure_project(project_id: str, *, provider: str, model: str, dimensions: int,
                    version: str = VECTOR_VERSION) -> dict[str, Any]:
    """Compare canonical derived vectors with attested chunks and publish project-relative percentile distributions."""
    att = get_chunk_space_attestation()
    if not att or (att.get("provider"), att.get("model"), int(att.get("dimensions", 0))) != (provider, model, dimensions):
        return {"status": "unavailable", "reason": "corpus-space attestation does not match requested space"}
    chunk_mat, _ = db.load_embedding_matrix(db.project_source_ids(project_id))
    if not len(chunk_mat):
        return {"status": "measured", "chunk_count": 0, "claims": {}, "findings": {}}
    out: dict[str, Any] = {"status": "measured", "chunk_count": int(len(chunk_mat)), "claims": {}, "findings": {}}
    for table, key in (("project_claims", "claims"), ("project_notes", "findings")):
        vectors = db.load_versioned_derived_embeddings(table, project_id, provider=provider, model=model,
                                                       version=version, dimensions=dimensions)
        scores = [float(np.max(chunk_mat @ row["embedding"])) for row in vectors]
        out[key] = {"vector_count": len(scores), "distribution": {
            "min": float(np.min(scores)) if scores else None,
            "p50": float(np.percentile(scores, 50)) if scores else None,
            "p90": float(np.percentile(scores, 90)) if scores else None,
            "max": float(np.max(scores)) if scores else None,
        }}
    return out


def attest_chunk_space(*, provider: str, model: str, dimensions: int, preparation_tag: str) -> dict[str, Any]:
    """Measure and persist the legacy chunk-vector space; mixed or malformed blobs fail closed."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    rows = db.connect().execute("SELECT embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
    bad = 0
    for row in rows:
        try:
            if db._unpack(row["embedding"]).size != dimensions:
                bad += 1
        except (TypeError, ValueError):
            bad += 1
    attestation = {"provider": provider, "model": model, "dimensions": dimensions,
                   "count": len(rows), "bad_dimensions": bad, "preparation_tag": preparation_tag,
                   "verified": bool(rows) and bad == 0}
    db.kv_set(CORPUS_ATTESTATION_KEY, json.dumps(attestation, sort_keys=True))
    return attestation


def get_chunk_space_attestation() -> dict[str, Any] | None:
    raw = db.kv_get(CORPUS_ATTESTATION_KEY)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("verified") else None
