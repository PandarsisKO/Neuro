# State of the App — 2026-09-13 15:08 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- `main` is `f1533c6`; app/package version `0.63.65`.
- `repo-check` and commit-bound `release-check --no-pytest` pass; artifact:
  `evals/release/release-check-0.63.65-f1533c6-20260913-150847.json`.
- Full pytest baseline: **1,383 passed**, one existing Starlette deprecation warning. Focused T3: 16 passed.
- Claude owns design/audit/browser surfaces; Codex owns backend/reliability/T1–T3. Claims remains paused; R8/R9
  triggers unchanged.

T3 is a pure, versioned, read-only extractor with exact `[start,end)` spans. Corpus-driven hardening now suppresses
heading labels, harmless narration, bare-`to` procedures, generic negative cues, and decimal fraction subspans.
The 15-row provisional sample has 63 reviewed spans. The 60-row seeded manifest has 20 rows per retained project,
all 15 kinds, `gold: null`, and review-priority flags. Both came from copied verified backup data in SQLite `mode=ro`.

Next gate: manual exact-span gold adjudication of the seeded queue, including adversarial negatives and boundaries.
Until per-kind floors close, do not persist extraction, add a selector, invoke a provider, or begin T4.

`origin/backup/2026-09-13-clean` is maintained as a separate history-free snapshot; protected `VIDEOS/`, `data/`, and
`_to_delete/` paths are absent. Refresh it after the next `main` commit.
