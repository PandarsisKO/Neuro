"""Transcript Intelligence T4: the selector half of the Batch Research Executor.

Deliberately separate from any executor, per the mission doc's own fifth correction: "what is worth spending on"
and "who executes it" are two different questions, and this module answers only the first one.

Pure and read-only, exactly like T1's ``coverage_view`` and T3's ``extract``: no write, no queue, no provider
call, no promotion of research state. It reads T1+T2 signals (via ``t1.coverage_view``) and open Evidence
Targets (via ``knowledge.list_targets``), scores deterministic Tier-0 cue density on genuinely unexplained
passages with T3's own pure extractor, and returns a ranked, reproducible work list. Every item carries an
``input_hash`` (T1's own ``input_hash`` helper) derived only from the item's own identifying fields, so a re-run
against unchanged data reproduces byte-identical ranking and provenance, and nothing here decides who acts on
the list or writes anything back — ``claims.set_status`` remains the only promotion door, as it always has.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from . import contracts, db, knowledge, providers, t1, t3

SELECTOR_VERSION = "t4-selector-v2"   # v2: source relevance (T1 Claim-centroid proximity) ranks chunks within a priority
PLAN_VERSION = "t4-plan-v1"
EXECUTOR_TASK = "t4.research"

# Tier-0 record kinds whose presence on an already-unexplained chunk raises its priority: these are the
# "numbers and procedure that nothing has ever read" the mission doc names as worth surfacing first.
_HIGH_VALUE_T3_KINDS = ("money", "percentage", "duration", "unit", "number", "procedure", "warning", "date")


def source_relevance(project_id: str) -> dict[str, Any]:
    """Per-source semantic proximity to what this project already holds: the mean cosine of a source's chunk
    vectors to the centroid of the project's canonical Claim vectors (T1's derived space, same attestation and
    version rules as ``t1.coverage_view``). Read-only, $0, no network: every vector it reads is already stored.

    Why this signal, and its known limit. Measured on the 13 sources read for real on 2026-09-14 (see
    docs/T4-ADMISSION-2026-09-14.md, "Relevance-aware selection"): Spearman 0.62 against the substance score
    ``findings.extract`` gave each source; all three high-substance sources landed in the top half, the bottom
    half averaged substance 9. The one miss was a spreadsheet source (substance 68, ranked 7th of 13): prose
    Claim vectors sit far from tabular text, so this is a RANKING signal combined with Tier-0 cue density, never
    a filter on its own. A brief-text embedding is the better long-term basis and belongs here once the
    embedding provider is reachable from the executing process; the centroid needs no new vector at all.

    Follows T1/T2's honesty rule: when the vector space is unattested, Claim vectors are missing, or a source has
    no valid chunk vector, the score is reported as unavailable (``None``) with a reason -- never as a low score.
    """
    unavailable = {"status": "unavailable", "scores": {}, "claim_vectors": 0}
    att = t1.get_chunk_space_attestation()
    if not att:
        return {**unavailable, "reason": "chunk_space_unattested"}
    provider, model, dims = att.get("provider"), att.get("model"), int(att.get("dimensions") or 0)
    if dims <= 0:
        return {**unavailable, "reason": "chunk_space_unattested"}
    claims = db.load_versioned_derived_embeddings("project_claims", project_id, provider=provider, model=model,
                                                  version=t1.VECTOR_VERSION, dimensions=dims)
    if not claims:
        return {**unavailable, "reason": "claim_vectors_unavailable"}
    centroid = np.vstack([np.asarray(v["embedding"], dtype=np.float32) for v in claims]).mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if not np.isfinite(norm) or norm == 0.0:
        return {**unavailable, "reason": "claim_centroid_degenerate", "claim_vectors": len(claims)}
    centroid = centroid / norm
    conn = db.connect()
    rows = conn.execute("""SELECT c.source_id, c.embedding FROM chunks c
                           JOIN project_sources ps ON ps.source_id = c.source_id
                           WHERE ps.project_id=? AND c.embedding IS NOT NULL""", (project_id,)).fetchall()
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    invalid: dict[str, int] = {}
    for r in rows:
        sid = r["source_id"]
        try:
            vec = db._unpack(r["embedding"])
            if vec.size != dims or not np.isfinite(vec).all():
                raise ValueError
        except (TypeError, ValueError):
            invalid[sid] = invalid.get(sid, 0) + 1
            continue
        sums[sid] = sums.get(sid, 0.0) + float(vec @ centroid)
        counts[sid] = counts.get(sid, 0) + 1
    scores = {sid: sums[sid] / counts[sid] for sid in counts}
    return {"status": "measured", "scores": scores, "claim_vectors": len(claims),
            "basis": "mean cosine of a source's chunk vectors to the centroid of project_claims vectors",
            "sources_scored": len(scores), "sources_with_invalid_chunks": len(invalid)}


def _unexplained_chunk_items(project_id: str, *, chunk_limit: int | None,
                             relevance: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    relevance = relevance if relevance is not None else source_relevance(project_id)
    scores = relevance.get("scores") or {}
    coverage = t1.coverage_view(project_id, limit=chunk_limit)
    # T2's own coverage_view never asserts primary_state "unexplained" while extracted/redundant/irrelevant
    # remain unavailable (see docs/T2-ADMISSION-2026-09-13.md: "unexplained is never asserted while any
    # required signal is unavailable") — which today is always, since T3 is not wired into that view and
    # redundant/irrelevant have no chunk-level signal yet. T4 does not change T2's honesty rule; instead it
    # reads the same underlying fact T2 already exposes (an empty ``signals`` list: no Claim/Finding coverage
    # and no semantic representation) and applies its own read of T3's extractor on top, which is exactly the
    # gap the mission doc names this rung to close.
    unexplained = [row for row in coverage["chunks"] if not row["signals"]]
    if not unexplained:
        return []
    ids = [row["chunk_id"] for row in unexplained]
    placeholders = ",".join("?" for _ in ids)
    text_by_id = {int(r["id"]): r["text"] or "" for r in
                  db.connect().execute(f"SELECT id, text FROM chunks WHERE id IN ({placeholders})", ids).fetchall()}
    items: list[dict[str, Any]] = []
    for row in unexplained:
        text = text_by_id.get(row["chunk_id"], "")
        cue_kinds = sorted({rec["kind"] for rec in t3.extract(text)["records"] if rec["kind"] in _HIGH_VALUE_T3_KINDS})
        # Priority 1 (highest) when Tier-0 found something concrete worth reading; priority 2 otherwise —
        # still genuinely unexplained, just with no deterministic signal yet pointing at *why* it matters.
        priority = 1 if cue_kinds else 2
        items.append({
            "kind": "unexplained_chunk",
            "chunk_id": row["chunk_id"], "source_id": row["source_id"], "chunk_idx": row["chunk_idx"],
            "start": row["start"], "end": row["end"],
            "reason": ("Tier-0 extraction found " + ", ".join(cue_kinds) + " with no Claim/Finding coverage"
                       if cue_kinds else "no Claim/Finding coverage, no Tier-0 cue"),
            "cue_kinds": cue_kinds,
            "priority": priority,
            "relevance": scores.get(row["source_id"]),   # None = unavailable, never "low"
            "input_hash": t1.input_hash(SELECTOR_VERSION, "unexplained_chunk", row["chunk_id"], row["start"], row["end"]),
        })
    return items


def _open_target_items(project_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for target in knowledge.list_targets(project_id, status="open"):
        # A governing target with no Claim at all yet is the most consequential unresolved question this
        # project has; a governing target that already has a Claim, or a merely corroborative one, ranks lower.
        governing = target.get("sufficiency") == "governing"
        priority = 1 if (governing and not target.get("claim_id")) else (2 if governing else 3)
        items.append({
            "kind": "open_evidence_target",
            "target_id": target["id"], "question": target["question"], "sufficiency": target.get("sufficiency"),
            "claim_id": target.get("claim_id"),
            "reason": ("open governing target with no supporting Claim" if governing and not target.get("claim_id")
                       else "open governing target" if governing else "open corroborative target"),
            "priority": priority,
            "input_hash": t1.input_hash(SELECTOR_VERSION, "open_evidence_target", target["id"], target.get("updated_at")),
        })
    return items


def select(project_id: str, *, limit: int | None = None, chunk_limit: int | None = None) -> dict[str, Any]:
    """Return a ranked, reproducible work list of candidate research items for ``project_id``.

    Read-only: this function makes no database write, queues no job, calls no provider, and does not change
    research state. ``chunk_limit`` bounds how many of the project's chunks ``t1.coverage_view`` inspects (for
    very large projects); ``limit`` bounds how many ranked items are returned. Items are ordered by
    ``(priority, input_hash)`` — priority is the product judgement, ``input_hash`` breaks ties deterministically
    so the same inputs always produce the same order, independent of database row order or dict iteration.
    """
    relevance = source_relevance(project_id)
    items = _unexplained_chunk_items(project_id, chunk_limit=chunk_limit, relevance=relevance) + _open_target_items(project_id)
    # v2 order within a priority: open Evidence Targets first (a governing question the project has already asked
    # outranks any passage nobody has asked about), then unexplained chunks by source relevance DESCENDING, then
    # input_hash so ties -- and the whole list when relevance is unavailable -- stay byte-for-byte reproducible.
    items.sort(key=lambda item: (item["priority"], 0 if item["kind"] == "open_evidence_target" else 1,
                                 -(item.get("relevance") if item.get("relevance") is not None else 0.0), item["input_hash"]))
    selected = items if limit is None else items[:limit]
    by_source: dict[str, dict[str, Any]] = {}
    for item in items:
        if item["kind"] != "unexplained_chunk":
            continue
        row = by_source.setdefault(item["source_id"], {"source_id": item["source_id"], "relevance": item.get("relevance"),
                                                       "unexplained_chunks": 0, "priority1_chunks": 0})
        row["unexplained_chunks"] += 1
        if item["priority"] == 1:
            row["priority1_chunks"] += 1
    sources = sorted(by_source.values(), key=lambda s: (-(s["relevance"] if s["relevance"] is not None else 0.0),
                                                        -s["priority1_chunks"], s["source_id"]))
    return {"selector_version": SELECTOR_VERSION, "project_id": project_id, "count": len(items),
            "by_kind": {kind: sum(1 for i in items if i["kind"] == kind)
                        for kind in ("unexplained_chunk", "open_evidence_target")},
            "relevance": {k: v for k, v in relevance.items() if k != "scores"},
            "by_source": sources,
            "items": selected}


def plan(project_id: str, *, limit: int | None = None, chunk_limit: int | None = None) -> dict[str, Any]:
    """The executor's dry run: route ``select()``'s ranked items through the SAME contract and execution-policy
    seam a real executor call would use, without making one.

    This deliberately stops short of calling ``providers.route`` -- that function's local branch can start a
    Claude Code health probe (a real, if small, subscription spend) whenever the cached verdict has expired, and
    this function's whole purpose is to prove the wiring at $0, not to guess whether now is a good moment to
    spend a few tokens on a health check. It reads only ``contracts.contract(EXECUTOR_TASK)`` (a pure lookup) and
    ``providers.current_policy()`` (a pure thread-local read) -- both zero-cost and side-effect-free -- and
    reports what routing WOULD be eligible. No provider is called, no health probe runs, no row is written, and
    ``claims.set_status`` -- the only promotion door -- is never approached.

    Wiring a live call is future work: the point of this slice is that it requires adding the call itself where
    ``executed`` is currently always ``False``, not inventing new routing machinery to carry it.
    """
    selection = select(project_id, limit=limit, chunk_limit=chunk_limit)
    c = contracts.contract(EXECUTOR_TASK)
    policy = providers.current_policy()
    eligible_for_local = bool(c.local_capable) and policy not in ("api_only", "api_requested")
    if policy in ("api_only", "api_requested"):
        routing_note = f"api only: execution policy is {policy!r}"
    elif not c.local_capable:
        routing_note = "api only: t4.research is not local-capable"
    else:
        routing_note = "eligible for the local (Claude Code) backend, pending providers.route()'s health check at call time"
    items = [{**item, "executor_task": EXECUTOR_TASK, "executor_model": c.model,
             "eligible_for_local": eligible_for_local, "executed": False} for item in selection["items"]]
    return {"plan_version": PLAN_VERSION, "project_id": project_id, "selector_version": selection["selector_version"],
            "executor_task": EXECUTOR_TASK, "executor_model": c.model, "policy": policy,
            "eligible_for_local": eligible_for_local, "routing_note": routing_note,
            "count": selection["count"], "by_kind": selection["by_kind"], "items": items,
            "note": "dry run only: no provider call was made; providers.route() decides real backend/health at call time (not yet wired)"}
