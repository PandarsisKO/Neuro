# Transcript Intelligence T1 admission — 2026-09-12

## State: T1 first schema slice in progress

Foundation closed through R7 with an authenticated live observation on 2026-09-12. Transcript Intelligence is now
the active product program. Its first rung, T1 has a defined shared-space design. R9(c) is explicitly deferred with the numeric revisit trigger in
`docs/PRE-T1-GATE-AUDIT-2026-09-12.md`. The design reconciliation is recorded in
`docs/T1-DESIGN-RECONCILIATION-2026-09-12.md`.

R9(a) is complete in an isolated fixture: Ollama 0.33.3 runs on loopback and `bge-m3` (1024 dimensions) clears
the frozen latency, recall@10, and MRR gates. `nomic-embed-text` was rejected on MRR. The live database was not opened, queried,
changed, or re-embedded. `bge-m3` is the selected local candidate for a later full-space migration; its recorded decision is
in `docs/R9-ADMISSION-2026-09-11.md`. T1's first derived-object vectors stay in the current production
`text-embedding-3-small` space so chunk-to-derived comparisons are defined.

R9(b) is also complete. The fair 256-token-cap classification probe adopted Llama 3.1 8B (343 ms p50, 15/15 valid)
and rejected Qwen3 8B, Qwen3 14B, and gpt-oss-20b Q4 on the measured speed and/or validity gates. R9(c)'s real
15k-token findings/claims benchmark is explicitly deferred after the external 70B pull stalled; its numeric revisit
trigger is recorded in the pre-T1 audit. R8 retention is deliberately deferred to its non-destructive
observation trigger after 2026-10-11 17:28 PT and does not block T1.
The first bounded schema slice is now underway: additive metadata columns, typed fail-open read/write/invalidation
helpers, a low-lane durable backfill adapter, and a read-only `/api/projects/{id}/transcript/coverage` scaffold have
been added to both derived-object tables, with focused coverage in `tests/test_t1_vector_metadata.py`. The endpoint
reports explicit `measurement_pending` until corpus-space attestation exists; it never invents semantic coverage.
No live database was opened or re-embedded.

The affected Foundation/storage gate and the deterministic release check were rerun after the slice; release-check
passed with experimental flags off (artifact generated 2026-09-12 16:54 PT). The full pytest gate remains a separate
release-boundary action; the prior attempt was interrupted after an unbounded multiprocessing stall and is not counted
as a pass.

This is a real admission boundary, rather than a reason to revive the removed semantic prototype. `semantics.py` was
removed in 0.63.36 because it had no product/API path and used an all-row, fixed-quantile policy incompatible with
T1's canonical-active and project-relative requirements.

## Existing implementation seam

| Need | Existing seam | T1 change after R9(a) selection |
|---|---|---|
| Chunk vectors | `chunks.embedding`, `embeddings.embed_texts`, `db.load_embedding_matrix` | Create a one-time corpus-space attestation from the configured production model and measured stored dimensions before comparison. Use the existing `text-embedding-3-small` space only when that attestation verifies it; otherwise fail open and report the chunks as unavailable for T1 similarity. Never silently mix dimensions or model versions. |
| Derived-vector storage | Additive `project_notes.embedding` and `project_claims.embedding` columns already exist for compatibility | Add explicit model and embedding-version metadata; existing bare blobs are treated as unavailable, never trusted. |
| Canonical scope | Findings have `approved`/`suggested` status; Claims have `proposed`/`accepted`/`rejected`/`superseded` status | Default to approved/suggested Findings and proposed/accepted Claims; dismissed/rejected/superseded objects require an explicit feature reason. |
| Resumable backfill | `embeddings.embed_pending` commits in 96-row batches; chunk embeddings are idempotent | Create a derived-object equivalent keyed by object id, content/revision and embedding model/version. A restart resumes only stale or missing rows. |
| Jobs and cost ledger | durable `jobs`, provider contracts and `usage.record("embed", ...)` | Submit a low-lane, durable, deduplicated backfill after R9 validates the model; retain provider and model provenance. |
| Coverage computation | Chunk embeddings, `claim_evidence` locators, `project_notes` citations, R7's project-relative comparison patterns | Compute a read-only project-relative distribution first. Do not create coverage state or UI labels until the measurement is published. |

`chunks.embedding` stores bare normalized float32 blobs and has no historical per-row provider/model field. The initial
T1 migration must therefore record a versioned corpus-space attestation (provider, model, dimension, preparation tag,
verification timestamp and a fixed count/dimension check) before derived vectors become comparable. `db.row_to_dict()`
intentionally strips raw `embedding` blobs, so T1 needs dedicated raw-vector helpers rather than exposing them through
existing list endpoints. `project_notes` has no `updated_at`; its derived-vector freshness key must include normalized
content, citations and source/revision inputs rather than a timestamp alone.

## T1 acceptance gates

1. R9 records the local candidate runtime/model, vector dimension, retrieval recall/MRR, and latency decision in
   `docs/R9-ADMISSION-2026-09-11.md` and `HARDENING.md`; this reconciliation records the shared-space choice for T1.
2. A derived vector stores its model and version. A missing, stale, corrupt, or wrong-dimension vector fails open;
   it never makes a finding, Claim, or transcript chunk unreachable.
3. Backfill is resumable and idempotent across interruption, re-run, content change, and embedding-version change.
4. The first output reports, per project, nearest active Claim similarity, nearest applicable Finding similarity,
   locator coverage, semantic coverage distributions, and their comparison. It does not call no-locator material
   “unexplained.”
5. Similarity cut points are project-relative percentiles published with their distribution. No universal cosine
   threshold is introduced.
6. The gate includes deterministic vectors proving canonical filtering, stale-version exclusion, no mixed-space
   comparison, locator reconciliation, and a fail-open read path. A fresh T1 cohort must report latency and cost
   separately from the historical Foundation queue/batch measurements.

## First implementation slice after pre-T1 gate completion

1. Add metadata columns and schema compatibility migrations for both derived tables, plus the corpus-space attestation
   required to compare them with legacy chunk vectors.
2. Add typed db helpers for selecting canonical rows, reading/writing versioned vectors, and invalidating only the
   changed object.
3. Add a low-lane durable backfill adapter using the existing embedding provider and an explicit execution contract.
4. Add a read-only coverage report/API with distributions and locator comparison, initially without a UI state model.
5. Add focused T1 tests, run affected gates, then use a fresh version-stamped evaluation cohort before admitting T2.

## Explicit non-goals

T1 does not create a seven-state persisted coverage model (T2), a pre-Claim extraction layer (T3), a batch research
executor (T4), local NLP, or a universal semantic threshold. It does not re-embed the live corpus. Its first measurement
uses the current production embedding space for versioned derived-knowledge vectors. A full local `bge-m3` space is a
separate future migration rung with its own copied-corpus retrieval gate.
