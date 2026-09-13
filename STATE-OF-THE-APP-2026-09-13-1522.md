# State of the App — 2026-09-13 15:22 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Tested code baseline is `81f2cd9`; the current `main` tip may advance with documentation-only checkpoints. App/package
  version is `0.63.65`.
- `repo-check` and commit-bound `release-check --no-pytest` pass; artifact:
  `evals/release/release-check-0.63.65-81f2cd9-20260913-152248.json`.
- Full pytest passes **1,393 tests**, one existing Starlette warning. Focused T3/review coverage is 25 passed.
- Claude owns design/audit/browser surfaces; Codex owns backend/reliability/T1–T3. Claims remains paused; R8/R9
  triggers unchanged.

T3 remains pure, versioned, and read-only with exact `[start,end)` spans. Corpus-driven hardening covers heading
labels, harmless narration, bare fragments, phone-shaped ISBNs, malformed comma numbers, decimal components,
decimal-period sentence boundaries, and interrogative/procedure overlap. `neurosearch/t3_review.py` validates record
structure and scores labeled rows independently across chunks.

The provisional sample contains 15 project-balanced chunks and 63 reviewed spans. The seeded review manifest contains
60 rows, 20 per retained project, all 15 kinds, `gold: null`, and review-priority flags. Both were generated from a
copied verified backup in SQLite `mode=ro`.

Next gate: manual exact-span gold adjudication of the seeded queue, including adversarial negatives and boundaries.
Until per-kind floors close, do not persist extraction, add a selector, invoke a provider, or begin T4.

`origin/backup/2026-09-13-clean` is a separate history-free snapshot; protected `VIDEOS/`, `data/`, and `_to_delete/`
paths are absent.
