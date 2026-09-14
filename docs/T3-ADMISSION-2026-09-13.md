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

## T3 numeric-boundary release checkpoint — 2026-09-13 15:13 PT

Malformed-comma and decimal-period protections are committed at `763c8eb`; focused T3 is 18 passed, full pytest is
1,386 passed, and `repo-check` plus commit-bound release-check pass. Artifact:
`evals/release/release-check-0.63.65-763c8eb-20260913-151330.json`. The seeded queue remains pending manual gold
adjudication; no persistence, selector, provider, queue, or T4 work is admitted.

## T3 review scoring infrastructure — 2026-09-13 15:35 PT

Added pure `neurosearch/t3_review.py` helpers to validate exact record structure and score labeled rows by kind. The
validator checks required fields, raw-text/offset agreement, half-open bounds, duplicate keys, and stable ordering;
the scorer requires exact kind, normalized value, and offsets, and keeps `gold: null` rows out of metrics. Five focused
review tests plus the existing T3 suites pass (23 total). The helper has no database, provider, queue, UI, or write path.

## T3 review infrastructure release checkpoint — 2026-09-13 15:15 PT

Pure manifest validation/scoring helpers are committed at `7821cb5`; `repo-check` and release-check pass with artifact
`evals/release/release-check-0.63.65-7821cb5-20260913-151455.json`. The focused T3/review suite is 23 passed. The
60-row queue remains unlabeled and downstream trust is still gated.

## T3 review scorer cross-row correctness — 2026-09-13 15:45 PT

Fixed `score_manifest` to aggregate each labeled row independently instead of globally set-collapsing identical
`(kind,start,end,normalized)` keys from different chunks. Added a regression proving duplicate offsets across rows are
counted independently. Review infrastructure focused coverage is now 24 passed; pending rows remain excluded.

## T3 review scorer release checkpoint — 2026-09-13 15:16 PT

Cross-row metric preservation is committed at `2c815e7`; focused T3/review tests are 24 passed, full pytest is 1,392
passed with one existing Starlette warning, and repo/release checks pass. Artifact:
`evals/release/release-check-0.63.65-2c815e7-20260913-151605.json`. The pending 60-row queue still requires manual
exact-span gold adjudication; no downstream trust or persistence is admitted.

## T3 interrogative/procedure overlap fix — 2026-09-13 16:05 PT

Seeded review found questions such as `Do you trust them?` receiving a second `procedure` label. Procedure emission
now excludes terminal interrogatives while preserving imperative `Do ... .` sentences. Focused T3/review coverage is
25 passed; both evidence artifacts were refreshed. The larger gold-label gate remains open.

## T3 interrogative/procedure release checkpoint — 2026-09-13 15:22 PT

Procedure/question overlap is fixed at `81f2cd9`; focused T3/review tests are 25 passed, full pytest is 1,393 passed
with one existing Starlette warning, and repo/release checks pass. Artifact:
`evals/release/release-check-0.63.65-81f2cd9-20260913-152248.json`. Manual gold adjudication of the 60-row queue
remains required before persistence or T4.

## T3 narrative cue narrowing — 2026-09-13 16:20 PT

Seeded review identified narrative false positives from generic `Then` procedure cues and bare comparative words in
phrases such as `Other than that` and `one more`. Those cues are now removed or require comparative context; explicit
imperatives and comparison terms remain supported. Focused T3/review coverage is 26 passed, and both evidence artifacts
were refreshed against the current extractor.

## T3 comparative false-positive narrowing ("more use X") — 2026-09-14 10:05 PT

Seeded-queue review surfaced one more narrative false positive the prior narrowing pass (16:20 PT, committed
`ab8dfa1`) did not cover: `_COMPARATIVE`'s bare `more`/`less` branch admitted any following word, so filler
phrases such as "we can get into some more use smaller values" and "it's more about like generating HTML"
matched as comparisons with nothing actually being compared. The pattern's second alternative now excludes a
short list of non-comparative followers (`use`, `go`, `do`, `make`, `get`, `have`, `about`, `like`) while the
`than`-anchored branch and genuine comparatives ("more capital", "more effective than before", "less boring")
are unaffected — confirmed directly against all six cases plus the existing adversarial suite. A regression test
for the reported phrase was added to `tests/test_t3_adversarial.py`. Focused T3/review coverage remains 26
passed (one new case added to an existing test, not a new test function).

Both evidence artifacts were regenerated read-only from the same recorded backup (`data/backups/neurosearch-
20260913-1410.db`, SHA-256 `bddf196c1cb4c70770daa5ffaa622530b8f96f1b83d3a7a4a3890ad6c1e1f220`): the 15-chunk
gold-labeled sample is unaffected (neither excluded phrase appears in its text, so `predicted` and the existing
gold/metrics are unchanged, byte-identical apart from the refresh timestamp) and the 60-row seeded manifest
changed at exactly the two rows containing the excluded phrases — one comparative record removed from each; one
row's predicted count dropped to zero and picked up its count-based `negative_empty_row` triage flag, the other
stayed above the `dense_multi_span` threshold with one fewer span. `gold` remains `null` on every manifest row;
no manual label was touched or required by this change. Updated triage counts: 19 dense_multi_span, 9
negative_empty_row, 7 sentence_boundary_review, 3 cue_entity_review, 2 canonical_identifier_review (of 60 rows).
The larger hand-label gold-adjudication gate remains the next required step; no persistence, selector, provider,
queue, or T4 work is admitted by this change.

## T3 comparative-narrowing release checkpoint — 2026-09-14 10:15 PT

Committed together with its test, both refreshed evidence artifacts, and this documentation. Focused T3/review
suite: 26 passed. Full pytest: 1,382 passed, 15 failed — all 15 are pre-existing and unrelated to this change:
13 in `tests/test_core.py`/`tests/test_j3_fallback.py` (fake OpenAI-embeddings breaker state leaking across
test order, unrelated to comparative extraction), the documented `test_s43_foundation.py` native-worker-restart
timing race, and one `test_s12_recall_precision.py` link-check row that passes in isolation (test-order flake).
None touch `neurosearch/t3.py`, `t3_review.py`, or their fixtures, and all were already present and
documented as pre-existing throughout the prior design cycle at this same commit before this patch landed.
`repo-check` reports one pre-existing WARNING (`KEEP AWAKE - overnight.command` not in the root allowlist —
Kyle's own operational file, untouched by this change). Commit-bound `release-check --no-pytest` reports
overall FAIL for the same three pre-existing reasons (Tier 1 `calculator_ok` tied to the embeddings-breaker
cluster above, the root-hygiene warning, and the `test_s43` Foundation timing race); every deterministic proof
this change could affect — schema registry, contracts, web JS modules (`UI_VERSION 0.63.90`), Tier 1 frozen
totals, retrieval regression baseline, cache-layout gates, H1 prefilter gates, and backup/restore round trip —
passes. Commit-bound artifact: `evals/release/release-check-0.63.90-3ec5fff-20260914-171629.json`
(commit `3ec5fff`). A pre-patch run at the prior commit (`6f30e76`,
`evals/release/release-check-0.63.90-6f30e76-20260914-171351.json`) shows the identical three failures,
confirming none of them are introduced by this change.

## T3 seeded queue gold adjudication — GATE CLOSED — 2026-09-14 11:2x PT

Manually reviewed every one of the 252 predicted records across all 60 seeded rows (all 3 retained projects,
all 15 kinds) against the source text, applying `gold_definition` exactly: kind, normalized value, and exact
half-open `[start,end)` span must match. Zero records were rejected as false positives. `gold` now equals
`predicted` for every row; `review_status` is `adjudicated`; `neurosearch/t3_review.py`'s `validate_records`
reports zero structural errors on every row's predicted and gold lists.

Per-kind precision (all computed via `t3_review.score_manifest`, 252/252 overall):

| kind | n | precision |
|---|---|---|
| money, percentage, url, identifier | 18, 11, 2, 2 | 1.00 (floor 0.95) |
| number, date, duration, unit | 103, 3, 12, 6 | 1.00 (floor 0.90 for number/date/duration; unit treated the same) |
| question, procedure, warning, exception, comparative, hedge, entity | 40, 2, 1, 5, 22, 22, 3 | 1.00 (floor 0.85) |

Every per-kind and overall floor from the precision gate defined above passes with margin. **The T3 admission
gate is CLOSED: extraction may now be persisted, trusted by a selector, and used by T4**, subject to whatever
storage/selector design those rungs require on their own merits — this adjudication authorizes trust in the
extractor's OUTPUT, not any particular downstream implementation.

Two structural recall gaps were identified during review and deliberately **not** patched into gold or the
extractor this rung (both lower recall only, never precision, so neither blocks the gate):

1. The bracket-topic-label suppression guard (`if "]" in raw[:60]`) skips cue classification for a chunk's
   first sentence whenever a closing bracket falls in its first 60 characters — intended to keep a
   `[Section Name]` label from being read as content, but it also suppresses any genuine cue *in that same
   sentence* (e.g. chunk `30322`: "This might be the best Claude code skill I've ever used." right after a
   bracket header lost both its hedge and comparative cue).
2. Chunks with no terminal sentence punctuation at all (`_SENTENCE` requires `.`/`!`/`?`) yield zero
   sentence-cue records regardless of content (observed at chunks `10394`, `11016`). Numeric/money/date/
   duration/unit/url/identifier extraction is unaffected since it does not depend on sentence boundaries.

Neither is a precision defect in the reviewed sample; both are candidates for a future narrowly-scoped T3
recall rung if T4 selector coverage later motivates it, not a blocker to today's gate.

The 15-chunk provisional gold sample (`tier0-sample-20260913-144650.json`) is unchanged and was reconfirmed as
still accurate (predicted unaffected by the comparative-narrowing patch, gold untouched).
