# State of the App — 2026-09-13 15:13 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- `main` is `763c8eb`; app/package version `0.63.65`.
- `repo-check` and commit-bound `release-check --no-pytest` pass; artifact:
  `evals/release/release-check-0.63.65-763c8eb-20260913-151330.json`.
- Full pytest passes **1,386 tests**, one existing Starlette warning. Focused T3 is 18 passed.
- Claude owns design/audit/browser surfaces; Codex owns backend/reliability/T1–T3. Claims remains paused; R8/R9
  triggers unchanged.

T3 is a pure, versioned, read-only extractor with exact `[start,end)` spans. Corpus-driven hardening now handles
heading labels, harmless narration, bare fragments, phone-shaped ISBNs, malformed comma numbers, decimal components,
and decimal-period sentence boundaries. The provisional sample has 63 reviewed spans. The 60-row seeded manifest has
20 rows per retained project, all 15 kinds, `gold: null`, and review-priority flags; both were generated from a copied
verified backup in SQLite `mode=ro`.

Next gate: manual exact-span gold adjudication of the seeded queue, including adversarial negatives and boundaries.
Until per-kind floors close, do not persist extraction, add a selector, invoke a provider, or begin T4.

`origin/backup/2026-09-13-clean` is a separate history-free snapshot; protected `VIDEOS/`, `data/`, and `_to_delete/`
paths are absent.
