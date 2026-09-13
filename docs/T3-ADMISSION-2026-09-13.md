# Transcript Intelligence T3 admission — deterministic Tier-0 extraction

## Status

**ADMITTED FOR IMPLEMENTATION DESIGN; extraction output is not yet persisted or trusted downstream.** T2's derived
coverage view is complete and deliberately reports `extracted` as unavailable. T3 is the next Codex-owned rung in
`TRANSCRIPT-INTELLIGENCE-MISSION.md` and `DEVELOPMENT-OPERATING-SYSTEM.md` §37.

## Problem and boundary

T2 can identify locator and semantic coverage but cannot distinguish a passage that contains a concrete number,
procedure, warning, exception, identifier, question, or comparison before spending model cognition. T3 supplies that
cheap signal. It is deterministic, local, versioned, and fail-open. It must not decide whether a passage is true, promote
a Claim, dismiss a Finding, or call a provider.

The first slice is a pure extractor and read-only evaluation path. It does not add a table, JSON column, endpoint, UI,
provider call, queue job, or live-data mutation. A later storage decision requires a real query or selective-recompute
need; the default remains no persistence.

## Extractor contract

Input identity is `(chunk_id, source_revision, extractor_version, text)`. Output is a stable list of span records:
`{kind, raw, normalized, start, end, attributes}`. Text offsets are character offsets using the half-open interval
`[start,end)`. Records are sorted by `(start, end, kind, normalized)` and deduplicated by that tuple. Every record
preserves the exact raw span and enough attributes to explain normalization. Same input identity must produce byte-
identical JSON; a version change may add or remove records without rewriting another version's result.

The first version reuses `works.extract_identifiers` for DOI, ISBN, SOP, statute, regulation, publication, and form
identifiers, and `qa.URL_RE` for URLs. New conservative patterns cover:

- numeric values, money, percentages, units, dates, and durations;
- questions and procedural/imperative sentences;
- warnings, exceptions, comparisons, and hedges;
- named organizations, products, tools, and people only when a high-precision deterministic cue is present.

Cues are evidence to route a passage for review, not a semantic verdict. Ambiguous text remains unextracted. No generic
capitalization heuristic or broad named-entity guess is admitted without a measured precision result.

## Precision gate and sample

Before any selector, T4 executor, or user-facing state trusts T3, evaluate a stratified hand-labeled sample from the
three retained projects: equal project representation, random chunks plus cue-dense chunks, and all candidate kinds
represented. Gold labels mark exact spans and kind; overlaps are allowed when one span legitimately has multiple kinds.
The artifact records the sampling seed, backup hash, labels, extractor version, and per-kind precision, recall, and span
boundary accuracy. The minimum gates are precision ≥0.95 for money, percentages, URLs, and canonical identifiers;
precision ≥0.90 for numeric/date/duration; and precision ≥0.85 for cue sentence classes. Any kind below its floor is
removed or narrowed before release. Recall is reported and may motivate later expansion, but false positives cannot be
traded away silently.

## Idempotence and release gates

Focused tests prove regex normalization, exact offsets, overlap handling, URL/identifier reuse, malformed input, stable
ordering, version isolation, and no provider/queue/write side effects. The evaluation proves all sample labels are
reproducible from the copied backup. Full pytest, Tier 1 where affected, and commit-bound `release-check` must pass.
No extractor output is written to the live database during this rung.

## Explicit non-goals

No Evidence Atom table, per-chunk extraction matrix, model-assisted entity recognition, language expansion, Claim
promotion, Finding mutation, batch executor, UI, or universal relevance/quality score. Those require a separate measured
admission.

## T3 implementation and provisional sample — 2026-09-13 14:47 PT

The pure extractor is implemented in `neurosearch/t3.py` at version `t3-tier0-v1`, with focused coverage in
`tests/test_t3_extraction.py` (8 tests). It emits deterministic, sorted, exact half-open spans for numeric values,
money, percentages, units, dates, durations, URLs, canonical identifiers, sentence cues, and cue-gated entities;
output is read-only and has no database, queue, provider, UI, or persistence path.

The admission review found and fixed two precision hazards before any downstream use: T3 now requires an explicit ISBN
label or unambiguous 978/979 prefix before passing text to the existing canonical ISBN normalizer, preventing
phone-shaped ten-digit strings from becoming identifiers; and cue-entity names no longer absorb periods or the next
sentence. Duration matching also rejects comma-separated address fragments such as `2, Second`. Regression tests cover
these cases.

A provisional, project-balanced corpus sample is recorded at
`evals/t3/tier0-sample-20260913-144650.json`. It was produced from a temporary copy of verified backup
`data/backups/neurosearch-20260913-1410.db` (SHA-256
`bddf196c1cb4c70770daa5ffaa622530b8f96f1b83d3a7a4a3890ad6c1e1f220`) opened with SQLite `mode=ro`; the live database
was not opened. The sample contains 15 chunks across all three retained projects, includes positive and empty rows,
and represents every emitted kind. Codex manually reviewed exact kind, normalized value, and `[start,end)` span for
64 candidates: provisional precision/recall are 1.00 overall and for each represented kind. This is a purposive,
small sample, so it does **not** authorize T4 or persisted extraction; a larger seeded sample and release gate remain
required before downstream trust.

## T3 implementation release checkpoint — 2026-09-13 14:50 PT

Implementation and provisional evidence are committed at `46f0a5e` (`feat: add T3 deterministic extraction`). The
full suite passes 1,376 tests (one existing Starlette deprecation warning); T1/T2/T3 focused checks pass 28 tests.
Commit-bound `release-check --no-pytest` passes every deterministic proof at UI/package `0.63.65`; artifact:
`evals/release/release-check-0.63.65-46f0a5e-20260913-145001.json`.

The provisional sample remains evidence only. A larger seeded hand-label set with adversarial negatives and boundary
cases is the next gate. No T3 output is persisted or trusted by T4, a selector, or user-facing state until that gate is
closed.
