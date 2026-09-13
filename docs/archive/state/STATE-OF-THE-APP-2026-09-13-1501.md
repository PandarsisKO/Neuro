# State of the App — 2026-09-13 15:01 PT

This is the current orientation source for the Neuro Search mission. Older state files remain archived evidence.

## Current release and custody

- `main` is `473d1ec`; application/package version remains `0.63.65`.
- The last commit-bound deterministic release gate passed at `e4cf07f` (code unchanged since); artifact:
  `evals/release/release-check-0.63.65-e4cf07f-20260913-145704.json`.
- The corrected full regression suite passed **1,383 tests** with one existing Starlette deprecation warning. T3
  focused coverage is 15 passed.
- Claude owns the open design/audit/browser work, including `neurosearch/web/**` and `docs/design-audit/**`.
  Codex owns backend/reliability/T1–T3. Shared `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` are
  append-only.

## Mission boundary

Foundation Phases 0–10, T1, and T2 are complete. T3's pure deterministic Tier-0 extractor is implemented and
release-checked, but its output is not persisted and cannot drive T4 or user-facing state. Claims remains paused;
historical collected-but-unwritten items remain untouched. R8 retention remains observational until 2026-10-11
17:28 PT. R9 triggers remain unchanged.

## T3 evidence and next gate

The extractor emits versioned exact `[start,end)` spans for numeric values, money, percentages, units, dates, durations,
URLs, canonical identifiers, cue sentences, and cue-gated entities. Adversarial tests cover phone/ZIP/address false
identifiers, bare cues, numeric subspan double counting, ISBN gating, punctuation-safe entities/URLs, comma-safe
durations, and markdown empties.

The provisional sample is `evals/t3/tier0-sample-20260913-144650.json` (15 project-balanced chunks, every emitted kind,
64 reviewed spans, provisional 1.00 precision/recall). The larger pending review queue is
`evals/t3/seeded-review-manifest-20260913-150111.json` (60 rows, 20 per retained project, seed `20260913`, all 15
kinds, `gold: null`). Both were generated from a copied verified backup in SQLite `mode=ro`; live data was untouched.

The next Codex action is manual adjudication of the seeded queue, including exact boundaries and adversarial negatives,
then a release decision against the floors in `docs/T3-ADMISSION-2026-09-13.md`. Until that passes, do not persist
extraction, add a selector, invoke a provider, or begin T4. Claude's design ladder remains independent.

## Safety snapshot

`origin/backup/2026-09-13-clean` is maintained as a history-free snapshot branch with a tree equal to the tested
release tree at the last refresh. Protected paths `VIDEOS/`, `data/`, and `_to_delete/` are absent from the snapshot.
