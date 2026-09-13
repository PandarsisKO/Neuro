"""Transcript Intelligence T1: resumable, low-lane derived-object embedding backfill."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import numpy as np

from . import db
from .config import settings

VECTOR_VERSION = "t1-derived-v1"
CORPUS_ATTESTATION_KEY = "t1:corpus-space-attestation"
DERIVED_PROVIDER = "openai"

_DERIVED_SPECS = (
    ("project_notes", ("approved", "suggested"), "content", "citations", ("source_revision", "brief_revision")),
    ("project_claims", ("proposed", "accepted"), "text", "qualifiers", ("extraction_hash", "updated_at")),
)


def input_hash(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def enqueue_backfill(project_id: str, limit: int = 5000, offset: int = 0) -> list[dict[str, Any]]:
    """Queue canonical rows whose vector is missing, stale, corrupt, or in another space."""
    if limit <= 0 or offset < 0:
        return []
    conn = db.connect()
    out = []
    model = settings.embedding_model
    expected_dimensions = _attested_dimensions(DERIVED_PROVIDER, model)
    skipped = 0
    for table, statuses, text_col, meta_col, revision_cols in _DERIVED_SPECS:
        qs = ",".join("?" for _ in statuses)
        rows = conn.execute(f"""SELECT id, {text_col} AS text, {meta_col} AS metadata, {revision_cols[0]} AS rev_a,
            {revision_cols[1]} AS rev_b, embedding IS NULL AS embedding_missing,
            LENGTH(embedding) AS embedding_bytes, embedding_provider, embedding_model,
            embedding_dimensions, embedding_input_hash, embedding_version
            FROM {table} WHERE project_id=? AND status IN ({qs}) ORDER BY id""",
                          (project_id, *statuses)).fetchall()
        for row in rows:
            ih = input_hash(row["text"] or "", row["metadata"] or "", row["rev_a"], row["rev_b"])
            if not _needs_backfill(row, input_hash_=ih, provider=DERIVED_PROVIDER, model=model,
                                   expected_dimensions=expected_dimensions):
                continue
            if skipped < offset:
                skipped += 1
                continue
            payload = {
                "project_id": project_id, "table": table, "object_id": row["id"], "text": row["text"] or "",
                "input_hash": ih, "provider": DERIVED_PROVIDER, "model": model,
                "revision_a": row["rev_a"], "revision_b": row["rev_b"],
                "version": VECTOR_VERSION,
            }
            out.append(db.create_job("t1_embed_derived", payload,
                                     dedupe_key=f"t1-embed:{table}:{row['id']}:{ih}:{DERIVED_PROVIDER}:{model}:{VECTOR_VERSION}", lane="low"))
            if len(out) >= limit:
                return out
    return out


def backfill_preview(project_id: str) -> dict[str, Any]:
    """Return the billable T1 scope without queuing or running anything."""
    conn = db.connect()
    counts = {}
    model = settings.embedding_model
    expected_dimensions = _attested_dimensions(DERIVED_PROVIDER, model)
    for table, statuses, text_col, meta_col, revision_cols in _DERIVED_SPECS:
        qs = ",".join("?" for _ in statuses)
        rows = conn.execute(f"""SELECT id, {text_col} AS text, {meta_col} AS metadata,
            {revision_cols[0]} AS rev_a, {revision_cols[1]} AS rev_b,
            embedding IS NULL AS embedding_missing, LENGTH(embedding) AS embedding_bytes,
            embedding_provider, embedding_model, embedding_dimensions, embedding_input_hash, embedding_version
            FROM {table} WHERE project_id=? AND status IN ({qs})""", (project_id, *statuses)).fetchall()
        counts[table] = sum(_needs_backfill(
            row,
            input_hash_=input_hash(row["text"] or "", row["metadata"] or "", row["rev_a"], row["rev_b"]),
            provider=DERIVED_PROVIDER,
            model=model,
            expected_dimensions=expected_dimensions,
        ) for row in rows)
    total = sum(counts.values())
    return {"project_id": project_id, "rows": counts, "total_rows": total,
            "embedding_batches_at_96": (total + 95) // 96, "queued": 0, "executed": 0,
            "provider": DERIVED_PROVIDER, "model": model, "version": VECTOR_VERSION,
            "expected_dimensions": expected_dimensions}


def _attested_dimensions(provider: str, model: str) -> int | None:
    attestation = get_chunk_space_attestation()
    if not attestation or (attestation.get("provider"), attestation.get("model")) != (provider, model):
        return None
    return int(attestation["dimensions"])


def _needs_backfill(row: Any, *, input_hash_: str, provider: str, model: str,
                    expected_dimensions: int | None) -> bool:
    if row["embedding_missing"]:
        return True
    if (row["embedding_provider"], row["embedding_model"], row["embedding_version"], row["embedding_input_hash"]) != (
            provider, model, VECTOR_VERSION, input_hash_):
        return True
    dimensions = int(row["embedding_dimensions"] or 0)
    if dimensions <= 0 or int(row["embedding_bytes"] or 0) != dimensions * np.dtype(np.float32).itemsize:
        return True
    return expected_dimensions is not None and dimensions != expected_dimensions


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
    """Measure and persist a dimension/revision attestation for the declared legacy vector space."""
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    if provider != DERIVED_PROVIDER:
        raise ValueError("unsupported T1 embedding provider")
    if not model.strip() or not preparation_tag.strip():
        raise ValueError("model and preparation_tag are required")
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
                   "embedding_revision": db.chunk_embedding_revision(), "verified_at": time.time(),
                   "verification_scope": "dimensions_and_canonical_write_revision",
                   "provenance_basis": "declared_preparation_metadata",
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
    if not isinstance(value, dict) or not value.get("verified"):
        return None
    if value.get("verification_scope") != "dimensions_and_canonical_write_revision":
        return None
    if int(value.get("embedding_revision", -1)) != db.chunk_embedding_revision():
        return None
    current_count = db.connect().execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
    if int(value.get("count", -1)) != int(current_count):
        return None
    return value
