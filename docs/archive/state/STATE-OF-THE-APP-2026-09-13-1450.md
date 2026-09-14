# State of the App — 2026-09-13 14:50 PT

This is the current orientation source for the Neuro Search mission. Older state files remain archived evidence.

## Current release and custody

- `main` is `46f0a5e`; application/package version is `0.63.65`.
- Commit-bound `release-check --no-pytest` passes every deterministic proof; artifact:
  `evals/release/release-check-0.63.65-46f0a5e-20260913-145001.json`.
- Full pytest passes **1,376 tests** with one existing Starlette deprecation warning. T1/T2/T3 focused checks pass
  28 tests.
- Claude owns the open design/audit/browser work, including `neurosearch/web/**` and `docs/design-audit/**`.
  Codex owns backend/reliability/T1–T3. Shared `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` are
  append-only and have been updated with this checkpoint.

## Mission boundary

Foundation Phases 0–10, T1, and T2 are complete. T3's pure deterministic Tier-0 extractor is implemented and
release-checked, but its output is not persisted and cannot drive T4 or user-facing state. Claims remains paused;
the historical collected-but-unwritten items remain untouched. R8 retention remains observational until
2026-10-11 17:28 PT. R9 triggers remain unchanged.

## T3 evidence and next gate

`neurosearch/t3.py` emits versioned exact `[start,end)` spans for numeric values, money, percentages, units, dates,
durations, URLs, canonical identifiers, cue sentences, and cue-gated entities. It has no DB, provider, queue, UI,
or write path. Regression tests cover phone-shaped ISBN rejection, punctuation-safe entities, comma-safe durations,
normalization, ordering, overlap, malformed input, and version isolation.

The provisional read-only sample is `evals/t3/tier0-sample-20260913-144650.json`: 15 project-balanced chunks,
positive and empty rows, every emitted kind, and 64 Codex-reviewed exact spans. Provisional precision and recall are
1.00 overall and per represented kind. The sample was generated from a copied verified backup opened in SQLite
`mode=ro`; its SHA-256 is recorded in the artifact. The sample is purposive and too small for production promotion.

The next Codex action is a larger seeded hand-label evaluation (including adversarial negatives and boundary cases),
then a release decision against the per-kind floors in `docs/T3-ADMISSION-2026-09-13.md`. Until that passes, do not
persist extraction, add a selector, invoke a provider, or begin T4. Claude's design ladder remains independent and
continues from its own documented browser/human gates.
