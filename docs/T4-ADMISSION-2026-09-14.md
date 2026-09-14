# Transcript Intelligence T4 admission — the selector (first slice)

**Status: ADMITTED, selector only.** Per `TRANSCRIPT-INTELLIGENCE-MISSION.md` §D/T4 and Kyle's fifth correction,
the selector and the executor are two separable concerns; this admission is the selector alone. No executor is
wired in this pass — it "knows nothing about who executes it," exactly as the mission doc specifies. Built
alongside T5 and T6 under Kyle's explicit "do 4/5/6 now" authorization, following T3's gold-adjudication gate
closing (`3ca18be`), which is what cleared T3's extraction output for use by a selector.

## Problem and evidence

T3's admission gate closed on 2026-09-14 (`docs/T3-ADMISSION-2026-09-13.md`): all 252 predicted records across
the 60-row seeded gold queue are correct, every per-kind precision floor passes at 1.00. That closure explicitly
authorized "trusting T3's output" for a selector. T2's `coverage_view` (in `neurosearch/t1.py`) already exposes,
per chunk, whether it is claim-covered, finding-covered, or semantically represented — but by T2's own documented
honesty rule (`docs/T2-ADMISSION-2026-09-13.md`), it never asserts the `unexplained` primary state while
`extracted`/`redundant`/`irrelevant` remain unavailable, which today is always (T3 is not wired into that view,
and chunk-level redundant/irrelevant signals do not exist). Reading `t1.coverage_view`'s actual code (not the
mission doc's prose) confirmed this: `_T2_UNAVAILABLE` unconditionally names those three signals, so `unexplained`
is currently unreachable as a `primary_state` value.

T4 does not change T2's honesty rule or touch `t1.py`. Instead it reads the same fact T2 already exposes — an
empty `signals` list on a chunk, meaning no Claim/Finding coverage and no semantic representation — and applies
its own read of T3's pure extractor on top. That is exactly the gap the mission doc names T4 to close: "passages
whose Tier-0 extraction says 'numbers and procedure' that nothing has ever read."

## Scope of this admission (selector only)

`neurosearch/t4.py`, pure and read-only (no write, no queue, no provider call, no promotion of research state):

1. `_unexplained_chunk_items`: calls `t1.coverage_view(project_id)`, keeps chunks with an empty `signals` list,
   fetches their raw text with one read-only query, and runs `t3.extract` on each (T3's own pure function — no
   new extraction logic). A chunk where Tier-0 found `money`/`percentage`/`duration`/`unit`/`number`/`procedure`/
   `warning`/`date` gets priority 1; one with no cue gets priority 2 — still worth a look, but with no
   deterministic signal yet pointing at *why*.
2. `_open_target_items`: calls `knowledge.list_targets(project_id, status="open")`. A governing target with no
   supporting Claim yet is priority 1 (the most consequential unresolved question this project has); a governing
   target that already has a Claim is priority 2; a corroborative target is priority 3.
3. `select(project_id, *, limit=None, chunk_limit=None)` merges both lists, sorts by `(priority, input_hash)` —
   `input_hash` is T1's own `input_hash` helper, keyed only on each item's identifying fields, so ties break
   deterministically and the whole list is byte-identical on a re-run against unchanged data — and returns
   `{selector_version, project_id, count, by_kind, items}`.

## Explicit non-goals for this slice

- No executor. Nothing in this module invokes a provider, `providers.route`, a worker pool, or writes a
  structured delta anywhere. The mission doc's executor interface (Claude Code default / local model / Haiku API
  / future cloud worker) is future work built on top of this selector's output, not part of this admission.
- No novel-cluster-with-no-Claim signal — the mission doc names this as a candidate selector input, but no
  chunk-level clustering signal currently exists in this codebase to read (T2's duplicate detection is
  finding-level, not chunk-level, per its own admission doc). Adding one is its own future, separately-admitted
  rung, not invented here.
- No weak/stale-Claim signal — same reasoning; nothing in the current schema marks a Claim's evidence as stale
  in a way this selector could read without inventing new state.
- No change to `t1.coverage_view`, `t3.extract`, or the `project_evidence_targets` schema. T4 reads existing
  seams as they are.

## Gate

Per the mission doc: "every delta carries provenance and the input hash it was derived from; a re-run with no
new material produces no deltas and costs nothing; the selection is reproducible and identical across backends."
No deltas are produced by this slice (no executor exists yet to produce one), so the applicable half of the gate
is: every item carries `input_hash`; a re-run against unchanged data produces an identical ranked list; the
selection has no dependency on any backend (there is none to vary). Verified directly —
`test_selection_is_deterministic_and_reproducible` asserts two successive calls return the exact same dict, and
that every item's `input_hash` within one call is unique.

## Validation

Focused: `tests/test_t4_selector.py` (7 tests: a cue-bearing unexplained chunk outranks a cue-free one;
claim-covered chunks are excluded entirely; governing-without-claim outranks governing-with-claim outranks
corroborative, and closed targets never appear; determinism/reproducibility across two calls with unique
per-item hashes; `limit` truncates `items` while `count` still reports the full ranked list; the selector makes
no database write anywhere — job/claim/finding row counts are unchanged before and after; an empty project
returns an empty, fully-typed result) — 7 passed. Run together with `test_t2_coverage.py`, `test_t1_vector_metadata.py`,
`test_t3_extraction.py`, `test_t3_adversarial.py` (47 total) to confirm no interaction with the seams T4 reads.

Full suite: 1,382 of 1,397 pass — the same 15 pre-existing failures as the T6 baseline (13 in
`test_core.py`/`test_j3_fallback.py`, 1 `test_s12_recall_precision.py` order flake, 1 `test_s43_foundation.py`
timing race), none introduced by this change. `repo-check` shows the same one pre-existing warning. Commit-bound
`release-check --no-pytest` shows the same pre-existing FAIL causes as every prior checkpoint; every deterministic
gate this change could affect passes.

## Result

T4's selector half is admitted: a pure, deterministic, $0 module producing a ranked, reproducible, provenance-
carrying work list from existing T1/T2/T3/Evidence-Target seams, with no executor wired and no new database
state. The executor interface, the novel-cluster signal, and the weak/stale-Claim signal remain explicitly
future, separately-admitted work.
