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

## T3 adversarial boundary hardening — 2026-09-13 14:56 PT

Added `tests/test_t3_adversarial.py` (7 tests) for phone/ZIP/address false identifiers, bare cue words, numeric
subspan double counting, explicit-ISBN gating, punctuation-safe entity and URL spans, and markdown-label empties.
The focused T3 suite now passes 15 tests. These tests are regression protection only; the larger seeded hand-label gate
is still required before downstream trust.

## Release hygiene correction — 2026-09-13 14:57 PT

The first post-hardening full run reported 1,382 passed and one failure in the existing release-check test because the
superseded root state file `STATE-OF-THE-APP-2026-09-13-1436.md` was still present alongside the new authoritative
state. That file was archived under `docs/archive/state/`; the focused release test now passes and
`release-check --no-pytest` is green at `e4cf07f`, artifact `evals/release/release-check-0.63.65-e4cf07f-20260913-145704.json`.
This was a documentation hygiene fix; T3 code remains unchanged.

## T3 seeded review manifest prepared — 2026-09-13 15:01 PT

Prepared `evals/t3/seeded-review-manifest-20260913-150111.json` from a temporary copy of the verified 14:10
backup opened in SQLite `mode=ro` (same recorded SHA-256 as the provisional sample). The manifest contains 60 rows,
20 per retained project, selected by fixed kind-strata IDs plus seeded random fill (`seed=20260913`). Every targeted
kind is represented; each row includes the source text and predicted records but `gold: null` and
`review_status: pending_manual_label`. It is a review queue, not a pass/fail result. A reviewer must adjudicate exact
kind, normalized value, and `[start,end)` spans before T3 can feed any selector, persistence, or T4.

## T3 review triage — 2026-09-13 15:04 PT

The pending manifest now carries non-authoritative triage flags: 26 dense multi-span rows, 10 sentence-boundary
reviews, 5 empty-negative rows, 3 cue-entity reviews, and 2 canonical-identifier reviews. Flags only prioritize
human work; they do not alter predictions or create gold labels.

## T3 triage release checkpoint — 2026-09-13 15:02 PT

The triage-only manifest update is release-checked at `2b460ae`; `repo-check` passes and the deterministic release
artifact is `evals/release/release-check-0.63.65-2b460ae-20260913-150223.json`. The full regression baseline remains
1,383 passed with one existing Starlette warning. No extractor behavior changed. The next gate is manual gold
adjudication of the 60-row seeded queue; persistence and T4 remain prohibited until its per-kind floors are met.

## T3 precision narrowing after seeded corpus review — 2026-09-13 15:12 PT

Review of the seeded manifest exposed recurring false-positive paths in the original cue layer: markdown/topic labels
were treated as sentence content, `I don't know` became a warning, and bare `to ...` fragments became procedures.
The extractor now requires terminal punctuation for cue sentences, suppresses heading-prefixed segments, removes the
bare-`to` procedure cue, and admits `don't`/`never` only with explicit imperative warning verbs. Focused tests still
pass 15 and the full suite passes 1,383 with one existing Starlette warning.

Both evidence artifacts were regenerated from the same copied read-only backup. The provisional sample now contains
63 manually reviewed spans; the 60-row seeded manifest retains `gold: null` and pending status, with updated triage
counts. This narrows precision risk but does not close the larger hand-label gate or authorize downstream trust.

## T3 precision-fix release checkpoint — 2026-09-13 15:07 PT

The corpus-driven cue narrowing is committed at `452804e`. Full pytest passes 1,383 with one existing Starlette
warning; focused T3 is 15 passed; `repo-check` and commit-bound `release-check --no-pytest` pass. Release artifact:
`evals/release/release-check-0.63.65-452804e-20260913-150713.json`. The regenerated 15-row sample and 60-row pending
manifest are read-only evidence. Manual gold adjudication remains the next gate; no persistence, selector, provider,
queue, or T4 work is admitted.

## T3 decimal-boundary hardening — 2026-09-13 15:16 PT

The seeded review surfaced one remaining numeric boundary error: `_NUMBER` could emit the fractional component of a
larger decimal (`00` from `1.00`). Its left boundary now rejects a preceding period, with a regression test. Focused
T3 coverage is 16 passed. The sample and pending manifest were refreshed to match the committed extractor; downstream
trust remains gated.

## T3 decimal-boundary release checkpoint — 2026-09-13 15:08 PT

Decimal-boundary hardening is committed at `f1533c6`; focused T3 is 16 passed, full pytest is 1,383 passed, and
`repo-check` plus commit-bound release-check pass. Artifact: `evals/release/release-check-0.63.65-f1533c6-20260913-150847.json`.
The seeded queue remains pending manual gold adjudication; no downstream trust or persistence is admitted.

## T3 malformed-number and decimal-sentence hardening — 2026-09-13 15:24 PT

The pending corpus also exposed malformed comma fragments (`1,00`) and sentence splitting inside decimal values
(`1.00`). Numeric boundaries now reject comma/period subspans, and cue sentence termination treats a period after a
digit as decimal content. Focused T3 coverage is 18 passed; both read-only evidence artifacts were refreshed again.
The larger hand-label gate remains open.
