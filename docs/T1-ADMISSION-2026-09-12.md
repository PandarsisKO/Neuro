# Transcript Intelligence T1 admission — 2026-09-12

## State: design complete; T1 first measurement slice admitted

Foundation closed through R7 with an authenticated live observation on 2026-09-12. Transcript Intelligence is now
the active product program. Its first rung, T1, now has its governing embedding prerequisite resolved:
`DEVELOPMENT-OPERATING-SYSTEM.md` §35 requires T1 to use the embedding system validated by R9, and
`PRODUCT-SCHEDULER.md` records the same dependency.

R9(a) is complete in an isolated fixture: Ollama 0.33.3 runs on loopback and `bge-m3` (1024 dimensions) clears
the frozen latency, recall@10, and MRR gates. `nomic-embed-text` was rejected on MRR. The live database was not opened, queried,
changed, or re-embedded. `bge-m3` is the validated T1 embedding system; its recorded decision is in `docs/R9-ADMISSION-2026-09-11.md`.

This is a real admission boundary, rather than a reason to revive the removed semantic prototype. `semantics.py` was
removed in 0.63.36 because it had no product/API path and used an all-row, fixed-quantile policy incompatible with
T1's canonical-active and project-relative requirements.

## Existing implementation seam

| Need | Existing seam | T1 change after R9(a) selection |
|---|---|---|
| Chunk vectors | `chunks.embedding`, `embeddings.embed_texts`, `db.load_embedding_matrix` | Preserve the validated model space; never silently mix dimensions or model versions. |
| Derived-vector storage | Additive `project_notes.embedding` and `project_claims.embedding` columns already exist for compatibility | Add explicit model and embedding-version metadata; existing bare blobs are treated as unavailable, never trusted. |
| Canonical scope | Findings have `approved`/`suggested` status; Claims have `proposed`/`accepted`/`rejected`/`superseded` status | Default to approved/suggested Findings and proposed/accepted Claims; dismissed/rejected/superseded objects require an explicit feature reason. |
| Resumable backfill | `embeddings.embed_pending` commits in 96-row batches; chunk embeddings are idempotent | Create a derived-object equivalent keyed by object id, content/revision and embedding model/version. A restart resumes only stale or missing rows. |
| Jobs and cost ledger | durable `jobs`, provider contracts and `usage.record("embed", ...)` | Submit a low-lane, durable, deduplicated backfill after R9 validates the model; retain provider and model provenance. |
| Coverage computation | Chunk embeddings, `claim_evidence` locators, `project_notes` citations, R7's project-relative comparison patterns | Compute a read-only project-relative distribution first. Do not create coverage state or UI labels until the measurement is published. |

## T1 acceptance gates

1. R9 records the chosen embedding runtime/model, vector dimension, retrieval recall/MRR, and latency decision in
   `docs/R9-ADMISSION-2026-09-11.md` and `HARDENING.md`.
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

## Admitted first implementation slice

1. Add metadata columns and schema compatibility migrations for both derived tables.
2. Add typed db helpers for selecting canonical rows, reading/writing versioned vectors, and invalidating only the
   changed object.
3. Add a low-lane durable backfill adapter using the existing embedding provider and an explicit execution contract.
4. Add a read-only coverage report/API with distributions and locator comparison, initially without a UI state model.
5. Add focused T1 tests, run affected gates, then use a fresh version-stamped evaluation cohort before admitting T2.

## Explicit non-goals

T1 does not create a seven-state persisted coverage model (T2), a pre-Claim extraction layer (T3), a batch research
executor (T4), local NLP, or a universal semantic threshold. It does not re-embed the live corpus. It uses the selected local `bge-m3` system only for versioned derived-knowledge vectors, without mixing them with existing chunk-vector space.
