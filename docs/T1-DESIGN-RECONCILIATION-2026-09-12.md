# T1 design reconciliation — 2026-09-12

## Why this record exists

The first T1 design selected local `bge-m3` (1024 dimensions) for derived vectors while also preserving the existing
1536-dimensional chunk vectors and forbidding mixed-space comparisons. Claude's read-only audit identified the resulting
contradiction: T1's first deliverable is a chunk-to-Claim/Finding similarity measurement, so both sides must occupy one
embedding space. A 1024-dimensional derived vector cannot be compared with a 1536-dimensional chunk vector.

## Decision resolved from the governing mission

T1 uses the existing production `text-embedding-3-small` space for its first measurement. Every chunk already has a vector
in that space, and `TRANSCRIPT-INTELLIGENCE-MISSION.md` §A says the one-off T1 embedding work is on derived objects only.
Claims and Findings receive versioned vectors from the same provider/model space as the chunks. This preserves the
mission's low-cost first slice, produces a defined semantic coverage measure, and does not alter retrieval or re-embed the
live corpus before the T1 gates pass.

R9(a)'s `bge-m3` result remains valid, but its scope is narrower than the earlier T1 wording implied: it is a selected
candidate for a later, separately gated full-space local migration. That migration must version chunk vectors, re-embed a
copied corpus, and pass the frozen retrieval gate before it can replace the current OpenAI space. It is not part of T1's
first measurement and must not be introduced by a silent provider switch.

## Consequences for implementation

- T1 derived-vector metadata records provider, model, dimension, preparation/version tag, content hash and timestamp.
- A vector is comparable only when its complete space identity matches the chunk space used by the report. Because legacy
  chunk blobs have no per-row model field, a T1 corpus-space attestation must verify the configured production model and
  observed dimensions before those chunks form that baseline.
- Missing, stale, corrupt or wrong-space vectors are excluded from similarity, counted in a visible report bucket, and never
  make a source or chunk unreachable.
- The first report measures semantic similarity and locator coverage separately, with project-relative distributions. It
  cannot label material `unexplained` while required vectors or locator data are missing.
- The existing production chunk vectors remain untouched. The local `bge-m3` cache and R9 benchmark artifacts are not
  application state.

## Evidence and handoff

The issue was independently recorded in the untracked Claude handoff at
`Claude outputs/T1-DESIGN-AUDIT-2026-09-12.md`. This tracked record resolves its option-A/option-B question using the
original mission's explicit “embeddings are already paid for” and “derived objects only” constraints. The active queue and
remaining gate are in `PRODUCT-SCHEDULER.md` and `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.
