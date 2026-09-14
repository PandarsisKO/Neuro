"""Transcript Intelligence T1: resumable, low-lane derived-object embedding backfill."""
from __future__ import annotations

import hashlib
import json
import math
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


# T2: coverage is a derived view over the T1 seam.  These values are deliberately
# not persisted: a pass that did not run must never be represented by a row.
_T2_PRIMARY_PRECEDENCE = (
    "irrelevant", "redundant", "claim_covered", "finding_covered",
    "represented", "extracted", "unexplained",
)
_T2_UNAVAILABLE = {
    "extracted": "T3 deterministic extraction has not run",
    "redundant": "the existing duplicate pass is finding-level, not chunk-level",
    "irrelevant": "no validated chunk-level project-relevance signal exists",
}


def _t2_number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _t2_matches(chunks_by_source: dict[str, list[dict[str, Any]]], source_id: Any,
                start: Any, end: Any = None, *, membership: dict[str, int] | None = None) -> tuple[set[int], str | None]:
    """Return chunks covered by a point/window and a typed reason when none match."""
    sid = str(source_id) if source_id is not None else ""
    if membership is not None:
        if sid not in membership:
            return set(), "source_not_member"
        if int(membership[sid]):
            return set(), "excluded_source"
    lo = _t2_number(start)
    if lo is None:
        return set(), "invalid_locator"
    hi = _t2_number(end) if end is not None else lo
    if hi is None or hi < lo:
        return set(), "invalid_window"
    rows = chunks_by_source.get(sid, [])
    if not rows:
        return set(), "source_has_no_chunks"
    if hi == lo:
        matches = {int(r["id"]) for r in rows if float(r["start"]) <= lo < float(r["end"])}
    else:
        matches = {int(r["id"]) for r in rows if float(r["start"]) < hi and lo < float(r["end"])}
    if matches:
        return matches, None
    if lo < float(rows[0]["start"]):
        return set(), "before_first_chunk"
    if abs(lo - float(rows[-1]["end"])) < 1e-9:
        return set(), "at_chunk_end"
    if lo > float(rows[-1]["end"]):
        return set(), "at_or_after_last_chunk"
    return set(), "internal_chunk_gap"


def _t2_semantic_scores(conn: Any, project_id: str, chunk_rows: list[Any],
                        *, attestation: dict[str, Any] | None) -> tuple[dict[int, bool], dict[str, Any]]:
    """Compute project-relative representation without allocating a chunk×vector matrix."""
    unavailable = {"status": "unavailable", "reason": "missing_or_unattested_vector_space"}
    if not attestation or not chunk_rows:
        return {}, unavailable
    provider, model = attestation.get("provider"), attestation.get("model")
    dimensions = int(attestation.get("dimensions") or 0)
    if dimensions <= 0:
        return {}, unavailable
    vectors_by_kind: dict[str, list[np.ndarray]] = {}
    expected = {"claims": ("project_claims", ("proposed", "accepted")),
                "findings": ("project_notes", ("approved", "suggested"))}
    for kind, (table, statuses) in expected.items():
        vectors = db.load_versioned_derived_embeddings(table, project_id, provider=provider, model=model,
                                                       version=VECTOR_VERSION, dimensions=dimensions)
        qs = ",".join("?" for _ in statuses)
        canonical = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=? AND status IN ({qs})",
                                 (project_id, *statuses)).fetchone()[0]
        if not int(canonical):
            return {}, {**unavailable, "reason": f"{kind}_vectors_unavailable", "valid": 0, "expected": 0}
        if len(vectors) != int(canonical):
            return {}, {**unavailable, "reason": f"{kind}_vectors_incomplete", "valid": len(vectors), "expected": int(canonical)}
        vectors_by_kind[kind] = [np.asarray(v["embedding"], dtype=np.float32) for v in vectors]
    valid_chunks: list[tuple[int, np.ndarray]] = []
    invalid_chunks = 0
    for row in chunk_rows:
        blob = row["embedding"]
        try:
            vec = db._unpack(blob)
            if vec.size != dimensions or not np.isfinite(vec).all():
                raise ValueError
        except (TypeError, ValueError):
            invalid_chunks += 1
            continue
        valid_chunks.append((int(row["id"]), vec))
    if invalid_chunks or len(valid_chunks) != len(chunk_rows):
        return {}, {**unavailable, "reason": "chunk_vectors_incomplete", "valid": len(valid_chunks), "expected": len(chunk_rows)}
    matrix = np.vstack([v for _, v in valid_chunks])
    scores: dict[str, np.ndarray] = {}
    distributions: dict[str, dict[str, float | None]] = {}
    for kind, vectors in vectors_by_kind.items():
        if not vectors:
            scores[kind] = np.full(len(valid_chunks), -np.inf, dtype=np.float32)
            distributions[kind] = {"p50": None, "p90": None, "min": None, "max": None}
            continue
        best = np.full(len(valid_chunks), -np.inf, dtype=np.float32)
        for vector in vectors:
            best = np.maximum(best, matrix @ vector)
        scores[kind] = best
        distributions[kind] = {"min": float(np.min(best)), "p50": float(np.percentile(best, 50)),
                               "p90": float(np.percentile(best, 90)), "max": float(np.max(best))}
    represented: dict[int, bool] = {}
    thresholds = {k: distributions[k]["p90"] for k in distributions}
    for i, (chunk_id, _) in enumerate(valid_chunks):
        represented[chunk_id] = any(thresholds[k] is not None and float(scores[k][i]) >= float(thresholds[k])
                                    for k in scores)
    return represented, {"status": "measured", "thresholds": thresholds,
                         "distributions": distributions, "chunk_count": len(chunk_rows),
                         "invalid_chunks": 0}


def coverage_view(project_id: str, *, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
    """T2's derived seven-signal view; reads only and never queues or writes work."""
    if offset < 0 or (limit is not None and limit < 0):
        raise ValueError("offset and limit must be non-negative")
    conn = db.connect()
    chunk_rows = conn.execute("""SELECT c.id,c.source_id,c.idx,c.start,c.end,c.text,c.embedding
        FROM chunks c JOIN project_sources ps ON ps.source_id=c.source_id
        WHERE ps.project_id=? AND ps.excluded=0 ORDER BY c.source_id,c.idx,c.id""", (project_id,)).fetchall()
    by_source: dict[str, list[dict[str, Any]]] = {}
    membership = {str(r["source_id"]): int(r["excluded"])
                  for r in conn.execute("SELECT source_id,excluded FROM project_sources WHERE project_id=?", (project_id,)).fetchall()}
    for row in chunk_rows:
        by_source.setdefault(str(row["source_id"]), []).append(dict(row))
    claim_chunks: set[int] = set(); claim_reasons: dict[str, int] = {}; claim_locator_rows = 0
    for row in conn.execute("""SELECT ce.source_id,ce.start FROM claim_evidence ce
                              JOIN project_claims pc ON pc.id=ce.claim_id
                              WHERE pc.project_id=? AND pc.status IN ('proposed','accepted')""", (project_id,)).fetchall():
        claim_locator_rows += 1
        matches, reason = _t2_matches(by_source, row["source_id"], row["start"], membership=membership)
        claim_chunks.update(matches)
        if reason: claim_reasons[reason] = claim_reasons.get(reason, 0) + 1
    finding_chunks: set[int] = set(); finding_reasons: dict[str, int] = {}; malformed = 0; finding_rows = 0; finding_items = 0
    for row in conn.execute("SELECT citations FROM project_notes WHERE project_id=? AND status IN ('approved','suggested')", (project_id,)).fetchall():
        raw = row["citations"]
        if not raw or raw == "[]":
            continue
        finding_rows += 1
        try:
            citations = json.loads(raw)
        except (TypeError, ValueError):
            malformed += 1; continue
        if not isinstance(citations, list):
            malformed += 1; continue
        for citation in citations:
            finding_items += 1
            if not isinstance(citation, dict):
                malformed += 1; continue
            matches, reason = _t2_matches(by_source, citation.get("source_id"), citation.get("start"), citation.get("end"), membership=membership)
            finding_chunks.update(matches)
            if reason: finding_reasons[reason] = finding_reasons.get(reason, 0) + 1
    attestation = get_chunk_space_attestation()
    represented, semantic = _t2_semantic_scores(conn, project_id, chunk_rows, attestation=attestation)
    rows: list[dict[str, Any]] = []
    signal_counts = {name: 0 for name in ("extracted", "represented", "finding_covered", "claim_covered", "redundant", "irrelevant", "unexplained")}
    primary_counts: dict[str, int] = {}
    for row in chunk_rows:
        cid = int(row["id"]); signals: list[str] = []
        if cid in claim_chunks: signals.append("claim_covered")
        if cid in finding_chunks: signals.append("finding_covered")
        if represented.get(cid): signals.append("represented")
        for signal in signals: signal_counts[signal] += 1
        unknown = list(_T2_UNAVAILABLE)
        if semantic.get("status") != "measured": unknown.append("represented")
        primary = next((name for name in _T2_PRIMARY_PRECEDENCE if name in signals), "unknown")
        if not signals and not unknown: primary = "unexplained"
        primary_counts[primary] = primary_counts.get(primary, 0) + 1
        rows.append({"chunk_id": cid, "source_id": row["source_id"], "chunk_idx": row["idx"],
                     "start": row["start"], "end": row["end"], "signals": signals,
                     "unknown_signals": sorted(set(unknown)), "primary_state": primary})
    selected = rows[offset:] if limit is None else rows[offset:offset + limit]
    return {"project_id": project_id, "status": "measured", "denominator": len(rows),
            "canonical_claims": len(conn.execute("SELECT id FROM project_claims WHERE project_id=? AND status IN ('proposed','accepted')", (project_id,)).fetchall()),
            "canonical_findings": len(conn.execute("SELECT id FROM project_notes WHERE project_id=? AND status IN ('approved','suggested')", (project_id,)).fetchall()),
            "signals": signal_counts, "primary_states": primary_counts,
            "unknown_reasons": dict(_T2_UNAVAILABLE), "semantic": semantic,
            "reconciliation": {"claim_locator_rows": claim_locator_rows,
                                "claim_locator_rows_without_match": sum(claim_reasons.values()),
                                "claim_locator_reasons": claim_reasons,
                                "finding_citation_items": finding_items,
                                "finding_rows_with_citations": finding_rows,
                                "finding_citations_malformed": malformed,
                                "finding_citation_reasons": finding_reasons},
            "offset": offset, "limit": limit, "chunks": selected}


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
