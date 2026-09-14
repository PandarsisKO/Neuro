# State of the App — 2026-09-13 15:07 PT

This is the current orientation source for the Neuro Search mission. Older state files remain archived evidence.

## Current release and custody

- `main` is `452804e`; application/package version remains `0.63.65`.
- `repo-check` passes. `release-check --no-pytest` passes every deterministic proof; artifact:
  `evals/release/release-check-0.63.65-452804e-20260913-150713.json`.
- Full pytest passes **1,383 tests** with one existing Starlette deprecation warning. Focused T3 coverage is 15 passed.
- Claude owns design/audit/browser work (`neurosearch/web/**`, `docs/design-audit/**`); Codex owns backend/reliability/T1–T3.

## Mission boundary

Foundation Phases 0–10, T1, and T2 are complete. T3 is implemented as a pure, versioned, read-only extractor. Claims
remains paused; historical collected-but-unwritten items remain untouched. R8 retention remains observational until
2026-10-11 17:28 PT; R9 triggers are unchanged.

## T3 current gate

Seeded corpus review found and fixed heading-label, harmless-narration, and bare-fragment cue false positives. T3 now
requires terminal punctuation for cue sentences, suppresses heading-prefixed segments, removes bare-`to` procedures,
and restricts negative warning cues to explicit imperative verbs. Adversarial regressions cover these paths.

`evals/t3/tier0-sample-20260913-144650.json` contains 15 project-balanced chunks and 63 manually reviewed spans.
`evals/t3/seeded-review-manifest-20260913-150111.json` contains 60 rows, 20 per retained project, seed `20260913`,
all 15 kinds, `gold: null`, and review-priority flags. Both came from a copied verified backup in SQLite `mode=ro`.

Manual exact-span adjudication of the seeded queue is the next gate. Until per-kind precision floors are established,
do not persist extraction, add a selector, invoke a provider, or begin T4. Claude's design ladder remains independent.

## Safety snapshot

`origin/backup/2026-09-13-clean` is a history-free snapshot branch maintained separately from `main`; protected paths
`VIDEOS/`, `data/`, and `_to_delete/` are absent. Refresh it after the next `main` commit.
