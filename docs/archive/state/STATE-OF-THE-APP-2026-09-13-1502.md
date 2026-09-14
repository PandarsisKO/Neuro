# State of the App — 2026-09-13 15:02 PT

This is the current orientation source for the Neuro Search mission. Older state files remain archived evidence.

## Current release and custody

- `main` is `2b460ae`; application/package version remains `0.63.65`.
- `repo-check` passes. Commit-bound `release-check --no-pytest` passes every deterministic proof; artifact:
  `evals/release/release-check-0.63.65-2b460ae-20260913-150223.json`.
- The corrected full regression suite passed **1,383 tests** with one existing Starlette deprecation warning. The
  focused T3 suite is 15 passed.
- Claude owns the open design/audit/browser work, including `neurosearch/web/**` and `docs/design-audit/**`.
  Codex owns backend/reliability/T1–T3. Shared `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` are
  append-only.

## Mission boundary

Foundation Phases 0–10, T1, and T2 are complete. T3's pure deterministic Tier-0 extractor is implemented,
adversarial-hardened, and release-checked, but its output is not persisted and cannot drive T4 or user-facing state.
Claims remains paused; historical collected-but-unwritten items remain untouched. R8 retention remains observational
until 2026-10-11 17:28 PT. R9 triggers remain unchanged.

## T3 evidence and next gate

The extractor emits versioned exact `[start,end)` spans for numeric values, money, percentages, units, dates, durations,
URLs, canonical identifiers, cue sentences, and cue-gated entities. The provisional sample is
`evals/t3/tier0-sample-20260913-144650.json` (15 project-balanced chunks, 64 reviewed spans, provisional 1.00
precision/recall). The larger pending queue is `evals/t3/seeded-review-manifest-20260913-150111.json` (60 rows,
20 per retained project, seed `20260913`, all 15 kinds, `gold: null`) and now has review-only triage flags.

Both artifacts came from a copied verified backup in SQLite `mode=ro`; live data was untouched. The next Codex action
is manual adjudication of the seeded queue, including exact boundaries and adversarial negatives, followed by a release
decision against the per-kind floors in `docs/T3-ADMISSION-2026-09-13.md`. Until that passes, do not persist
extraction, add a selector, invoke a provider, or begin T4. Claude's design ladder remains independent.

## Safety snapshot

`origin/backup/2026-09-13-clean` is maintained as a history-free snapshot branch. Protected paths `VIDEOS/`, `data/`,
and `_to_delete/` are absent from the snapshot; refresh it after the next `main` commit.
