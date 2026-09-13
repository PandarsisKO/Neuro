# State of the App — 2026-09-13 14:57 PT

This is the current orientation source for the Neuro Search mission. Older state files remain archived evidence.

## Current release and custody

- `main` is `e4cf07f`; application/package version is `0.63.65`.
- `release-check --no-pytest` passes every deterministic proof; artifact:
  `evals/release/release-check-0.63.65-e4cf07f-20260913-145704.json`.
- The full regression suite reached 1,382 passed and exposed one repository-hygiene failure: a superseded root state
  file. After archiving that file, the affected release test passes; the next full run is required after this docs-only
  checkpoint. The focused T3 suite is 15 passed.
- Claude owns the open design/audit/browser work, including `neurosearch/web/**` and `docs/design-audit/**`.
  Codex owns backend/reliability/T1–T3. Shared `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` are
  append-only.

## Mission boundary

Foundation Phases 0–10, T1, and T2 are complete. T3's pure deterministic Tier-0 extractor is implemented and
release-checked, but its output is not persisted and cannot drive T4 or user-facing state. Claims remains paused;
historical collected-but-unwritten items remain untouched. R8 retention remains observational until 2026-10-11
17:28 PT. R9 triggers remain unchanged.

## T3 evidence and next gate

`neurosearch/t3.py` emits versioned exact `[start,end)` spans for numeric values, money, percentages, units, dates,
durations, URLs, canonical identifiers, cue sentences, and cue-gated entities. It has no DB, provider, queue, UI,
or write path. Focused extraction and adversarial tests cover normalization, ordering, overlap, malformed input,
phone-shaped ISBN rejection, punctuation-safe entities/URLs, comma-safe durations, and markdown empties.

The provisional read-only sample is `evals/t3/tier0-sample-20260913-144650.json`: 15 project-balanced chunks,
positive and empty rows, every emitted kind, and 64 Codex-reviewed exact spans. The sample was generated from a copied
verified backup opened in SQLite `mode=ro`; its SHA-256 is recorded in the artifact. Provisional precision and recall
are 1.00 overall and per represented kind, but the sample is purposive and too small for production promotion.

The next Codex action is a larger seeded hand-label evaluation with adversarial negatives and boundary cases, then a
release decision against the per-kind floors in `docs/T3-ADMISSION-2026-09-13.md`. Until that passes, do not persist
extraction, add a selector, invoke a provider, or begin T4. Claude's design ladder remains independent.
