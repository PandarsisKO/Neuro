# T1 design audit — 2026-09-12

This tracked handoff preserves the actionable findings from Claude's read-only audit. The original working copy is also
at `Claude outputs/T1-DESIGN-AUDIT-2026-09-12.md`; the tracked file is the source of truth for future checkouts.

## Resolved before implementation

### Shared vector space was undefined

The earlier admission selected 1024-dimensional `bge-m3` vectors for Claims and Findings while preserving existing
1536-dimensional chunk vectors and forbidding mixed-space comparisons. That made the required chunk-to-derived-object
measurement impossible. `docs/T1-DESIGN-RECONCILIATION-2026-09-12.md` resolves it: T1's first measurement embeds derived
objects in the existing production `text-embedding-3-small` space. `bge-m3` is a later, separately gated full-space
migration candidate and must not be silently introduced into T1.

### R9 evidence was not reproducible

The repository now contains `evals/r9/embedding_probe.py`, `evals/r9/retrieval_probe.py`,
`evals/r9/classification_probe.py`, and `evals/r9/scorecard-2026-09-12.json`. They document the loopback runtime,
frozen fixture, sample protocol, and fair 256-token classification rerun. They use temporary databases and never open the
live database. The narrative decisions remain in `docs/R9-ADMISSION-2026-09-11.md` and `HARDENING.md`.

## Requirements carried into the first T1 slice

- Canonical scope is explicit. Include approved/suggested Findings and proposed/accepted Claims by default. Decide and
  report `reserve` Findings separately rather than silently counting or discarding them.
- Locator reconciliation is typed by source kind. Media uses time ranges, documents use pages, and spreadsheets use group
  indexes. Stale `claim_evidence` and source-revision mismatches are reported separately from current coverage.
- Finding citations in `project_notes.citations` must be parsed into a pinned locator shape. A finding with no parsable
  locator is “cited without locator,” not silently treated as no coverage.
- Sources with no retrievable chunks have a separate “no chunks” bucket. They must not inflate `unexplained`.
- Missing, stale, corrupt, wrong-dimension, or wrong-space vectors are excluded from similarity and counted in a visible
  per-project bucket. The report must refuse to label anything `unexplained` while required vector coverage is incomplete.
- Vector metadata includes provider, model, dimension, preparation/version tag, content hash and timestamp. Comparisons
  require an exact space identity match.
- Local zero-cost embedding work still records provider/model provenance in the usage ledger if that later migration is
  admitted. A T1 backfill job id must be recorded so R8's retention sample is not misread as organic growth.

## Remaining gate

R9(c) still needs one real 15k-token findings/claims window for a 70B Q4 candidate and `gpt-oss-120b`, with prefill and
generation reported separately and total wall clock compared with the 10.9-second API reference. R8's 30-day retention
observation is deliberately deferred to the dated trigger after 2026-10-11 17:28 PT; it remains non-destructive and
non-blocking. T1 implementation starts only after the pre-T1 audit records R9(c) as complete or deliberately deferred
with its numeric revisit trigger. The active R9(c) continuation state is recorded in
`docs/R9-ADMISSION-2026-09-11.md`; do not substitute a smaller model merely to bypass this gate.
