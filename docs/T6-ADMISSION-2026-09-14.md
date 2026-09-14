# Transcript Intelligence T6 admission — the assumption ledger

**Status: ADMITTED.** T6 is explicitly "parallel, not a prerequisite" per `TRANSCRIPT-INTELLIGENCE-MISSION.md` §D/T6
— it does not gate T4 or T5, and per Kyle's own "do 4/5/6 now" authorization all three rungs were built together in
this pass. This doc is intentionally lighter than the T1/T2/T3 admission proposals: T6 is scoped by the mission doc
itself as $0, low-complexity, and structurally incapable of touching the database, a provider, or the UI.

## Problem and evidence

The mission doc's own inventory: roughly 145 constants in this codebase encode a judgement about the data, of
which 19 are measured, and the measured ones cluster in four files. Four separate times a plausible constant was
later contradicted by Kyle's own live data (`CLUSTER_MAX`, `NEAR_JACCARD`, `CREATOR_STRONG_PER_SOURCE`, the
per-model finding cost). Reading current code (not the mission doc's stale examples) confirmed `CLUSTER_MAX` and
`CREATOR_STRONG_PER_SOURCE` no longer exist as named — they were retired or replaced during earlier hardening — so
this first slice registers assumptions that are actually live in `main` today rather than reproducing a stale list.

## Scope of this admission (first slice)

1. `neurosearch/assumptions.py` (new): a read-only `Assumption` registry. Each entry names a module + attribute,
   resolves the CURRENT live value via `getattr` at call time (never a copied/duplicated number, so it can never
   silently drift from the code it describes), and states whether it has ever been measured against live data,
   with a pointer to the evidence and a concrete `how_to_verify` re-check.
2. Nine entries seeded: five `findings_quality.py` constants already measured against live corpora during earlier
   hardening (`NEAR_JACCARD`, `CONTAIN_RATIO`, `SET_JACCARD`, `SET_MIN_SHARED`, `PAIR_BUDGET`) with their
   evidence pointers; two `findings_quality.py` constants never measured (`TITLE_ECHO`, `SHORT_CONTENT_TOKENS`);
   and two new `concurrency.py` constants extracted as named module-level defaults during this same pass
   (`_LOCAL_UNIT_CONCURRENCY_DEFAULT`, `_API_UNIT_CONCURRENCY_DEFAULT` — a pure refactor of the existing inline
   `2`/`3` literals in `limit_for()`, no behavior change) and registered as unmeasured.
3. `neurosearch assumptions [--json]` CLI command (`cli.py`), mirroring the existing `repo-check` command's shape.
4. One new informational check in `release.doctor()`: `assumption ledger (informational)`, always `warn=True`,
   never contributing to `verdict`. This is the mission doc's own gate, verbatim: "drift warns, never fails a
   release."

## Explicit non-goals for this slice

- No automatic re-measurement of any assumption — `how_to_verify` documents the manual check; automating any one
  of them is its own future, separately-admitted rung.
- No UI/Health-page surface beyond the `doctor()` line and the CLI command — a dedicated Health section is future
  work if the CLI/doctor surface proves insufficient.
- No attempt to enumerate all ~145 candidate constants — nine real, currently-live ones, chosen because their
  measurement evidence (or absence of it) could be verified by reading the current owning module.
- No database, provider, queue, or network access anywhere in the module (enforced by the module itself being pure
  `getattr` resolution — there is nothing else it could reach).

## Gate

Per the mission doc: drift warns, never fails a release. Verified directly — `list_assumptions()` never raises even
when an entry cannot resolve (reports `"ERROR: ..."` as that entry's value instead), and no output shape anywhere
in the module carries a pass/fail verdict field (`test_gate_is_informational_only_never_a_pass_fail_verdict`
asserts this explicitly).

## Validation

Focused: `tests/test_t6_assumptions.py` (8 tests: every registered assumption resolves live; a broken registry
entry is reported, not raised; summary counts are consistent and non-overlapping; text/JSON rendering round-trip
and match the summary; the informational-only gate; the two new concurrency constants are registered and match the
live values; `doctor()` reports the ledger check) — 8 passed. `tests/test_s47_r5_concurrency.py` (the pure-refactor
target) — 19 passed together with T6's own suite, no change in behavior.

Full suite: 1,382 of 1,397 pass — the same 15 pre-existing failures as the last recorded baseline (13 in
`test_core.py`/`test_j3_fallback.py` from fake-provider breaker-state leaking across test order, 1
`test_s12_recall_precision.py` test-order flake, 1 `test_s43_foundation.py` native-worker-restart timing race),
none introduced by this change.

`repo-check`: the same one pre-existing warning (`KEEP AWAKE - overnight.command`, Kyle's own operational file,
outside the documented root allowlist). Commit-bound `release-check` records the same pre-existing FAIL causes as
the last baseline; every deterministic gate this change could affect (schema registry, contracts, Tier 1 frozen
totals, backup/restore round trip, the new assumption-ledger check itself) passes.

## Result

T6 is admitted as a first, real slice: nine live assumptions registered, five with cited measurement evidence and
four flagged for future verification, surfaced via CLI and an informational `doctor()` line, with the ledger
structurally unable to touch the database, a provider, or the UI.
