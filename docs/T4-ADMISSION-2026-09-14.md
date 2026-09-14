# Transcript Intelligence T4 admission — the selector (first slice)

**Status: ADMITTED — selector, executor $0 routing dry run, and one throttled real extraction.** Per `TRANSCRIPT-INTELLIGENCE-MISSION.md`
§D/T4 and Kyle's fifth correction, the selector and the executor are two separable concerns. The selector
landed first, alone, under Kyle's "do 4/5/6 now" authorization. Kyle then asked to get T4 "fixed and shipped";
given the choice between a $0 routing dry run and a full live executor in one pass, he chose the $0 slice
(see "T4 executor — $0 dry run" below). A later, separately throttled bridge-assisted extraction exercised the
existing findings pipeline once; the executor routing seam and structured-delta path remain unimplemented.

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

- No LIVE executor call. `t4.plan()` (below) proves the routing wiring but never invokes a provider, a
  worker pool, or `providers.route` itself. The mission doc's executor interface (Claude Code default / local
  model / Haiku API / future cloud worker) actually reading an item and writing a structured delta remains
  future work.
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


## T4 executor — $0 dry run — 2026-09-14 13:1x PT

Kyle asked to get T4 "fixed and shipped." Given a choice between (a) a first $0 slice proving the executor's
routing wiring, matching how every other rung in this ladder was built, or (b) a full live executor making real
calls in one pass, he chose (a).

### What was added

A new registered contract, `t4.research` (`neurosearch/contracts.py`), at the cheapest tier (`CHEAP` /
`claude-haiku-4-5`), `local_capable=True`, `reversible=True`, with a `gate` stating explicitly that
`claims.set_status` remains the only promotion door and every output is proposed state. `contracts.policy_violations()`
remains empty and `contracts.decision()` reports `verdict: "cheapest"` for it — no `tier_reason` is needed at the
cheapest tier.

`neurosearch/t4.py` gains `plan(project_id, *, limit=None, chunk_limit=None)`: it calls `select()` for the ranked
work list, then attaches routing metadata to every item using `contracts.contract("t4.research")` (a pure lookup)
and `providers.current_policy()` (a pure thread-local read) — both zero-cost, side-effect-free reads. It
deliberately does **not** call `providers.route()`: that function's local branch can start a real Claude Code
health probe (a genuine, if small, subscription spend per `claude_code.health()`'s own docstring: "the probe is
one tiny prompt — it does spend a few subscription tokens") whenever the cached health verdict has expired. This
slice's whole purpose is to prove the wiring costs nothing, not to guess whether now is a good moment to spend a
few tokens on a health check — so it reports what routing *would be eligible* (`eligible_for_local`, a
`routing_note`) without ever confirming Claude Code's live health. Every item's `executed` field is `False`.

### Why this satisfies "reuses providers.route + execution_policy" without calling it

The mission doc's requirement is that T4 use the SAME seam every other task in this codebase uses rather than
inventing new machinery — not that this particular dry-run slice must trigger a live health probe. `t4.plan()`
proves the item -> contract -> policy path is wired correctly (verified by
`test_t4_research_contract_is_registered_and_gate_clean` and `test_plan_wraps_every_selected_item_with_routing_metadata`)
and that the *same* `contracts.contract()` and `providers.current_policy()` calls every real task depends on
return the expected values for T4's items. Wiring the actual `providers.route()` call — and the real
local/API dispatch it enables — is exactly the next, separate step; nothing about this slice's design would need
to change to add it, since `route()` is a drop-in replacement for the informational `eligible_for_local` logic
this dry run computes by hand.

### Explicit non-goals (this addition)

- No call to `providers.route()`, so no health probe and no possibility of even a small subscription spend.
- No structured-delta schema, no candidate finding/Claim writes, no worker-pool job type. These are the real
  executor's work and remain unbuilt.
- No change to `providers.py`, `execution_policy`, or the worker pools — T4 reads existing seams as they are, as
  before.

### Validation

Focused: `tests/test_t4_plan.py` (7 tests: the `t4.research` contract is registered and gate-clean at the
cheapest tier; every selected item is wrapped with routing metadata; `local_preferred` policy reports eligible
for local, `api_only` reports not eligible; `plan()` makes no provider call — a monkeypatched `providers.route`
that raises if called never fires, and job/finding/Claim row counts are unchanged before and after; `limit`
truncates items the same way `select()` does; two calls return an identical result) — 7 passed. Run together
with `test_t4_selector.py` and the contract/model-policy suites (27 total) to confirm no interaction.

Full suite: 1,382 of 1,397 pass — the same 15 pre-existing failures as every checkpoint since the T3
gold-adjudication closure, none introduced. `repo-check` shows the same one pre-existing warning; the new
`t4.research` contract does not appear in `contracts.policy_violations()`.

### Result

T4 now has both halves represented: a real, tested selector, and a real, tested executor routing seam proven at
$0. The only remaining step to a fully live T4 is wiring `providers.route()` plus the actual provider/local call
and a structured-delta write path — deliberately left for a future rung, per Kyle's choice.


## Real findings extraction, one flagged source — 2026-09-14

Kyle authorized real spend up to $20 today and asked to run real findings extraction on flagged sources in his
"Buying Businesses" project, throttled: one source first, check the real cost, then decide batch size.

### Which source, and why

`t4.plan()` ranked the project's unexplained chunks; source `559438c56dbb4be1b1116f8da76698b2`
("If I Wanted to Go From $0 to $100M, I'd Do This [FULL GUIDE]") had the most priority-1 items (6, each with a
Tier-0 cue and zero Claim/Finding coverage) of any single source, so it was the first real test.

### What ran, and why it needed the same bridge as T5

Same root cause as T5 (see `docs/T5-ADMISSION-2026-09-14.md`, "The real call, and why it needed a bridge"): this
device's shell can only reach the network through a local proxy that blocks `api.anthropic.com`. Rather than
build a T4-specific executor, this ran the EXISTING, already-shipped, already-tested production pipeline --
`findings.suggest_for_source()` -- completely unmodified, using the seam it already has for exactly this kind of
problem: the durable work-unit cache (`db.work_unit_get`/`work_unit_complete`, keyed by a content hash of every
input that can change the request). The comment on that cache reads "work in flight is still work" -- it exists
so a batch job whose results haven't been collected yet is never re-bought; the same mechanism makes a
pre-fetched real response indistinguishable from one `suggest_for_source` fetched itself:

1. On the device (real database): built the exact 6 per-window requests `suggest_for_source` would send for
   this source, via the pipeline's own `findings.canonical_requests()` plus the `findings.extract` contract's
   `request_params()` -- pure and read-only, no network, no ledger row.
2. Those 6 requests moved to a network-capable environment, which made the 6 real, billed calls.
3. The 6 real responses moved back. Each was parsed with `providers.structured()` (the exact function
   `invoke_structured()` itself calls), its cost recorded with `usage.record_anthropic()`, and the result written
   into `db.work_unit_complete()` under the SAME `work_unit_key()` the real pipeline would compute for that
   window (a pure hash of project/source/window/index/contract/revisions -- verified to match by construction,
   not by convention).
4. `findings.suggest_for_source(project_id, source_id, force=True)` then ran for real, completely unmodified.
   It found every window already "completed" in the work-unit cache, reused all 6 without any network call, and
   ran its real materialize pipeline (dedup, cap, prefilter bookkeeping, note-writing) on real model output.

`neurosearch/findings.py` is UNCHANGED. This is deliberately a heavier-weight bridge than T5's (which called
`providers.invoke` directly): T4's target was the production extraction pipeline itself, with its concurrency,
durable caching, and materialize logic all worth exercising for real rather than reimplementing.

### Result

6 real calls, `claude-sonnet-5`: 133,029 input tokens, 7,332 output tokens, **$0.3492** (matches
`usage.record_anthropic`'s own per-window recording exactly). `cost_value.unit_costs(window="month")["total_charged"]`
moved `147.952786 -> 148.301967`. `suggest_for_source` materialized **47 suggested findings** for this source
(cap 80, not hit) and recorded a substance score of 12/100 -- correctly low: the transcript is Dan Martell/Tony
Robbins content on personal finance, investing and business scaling, essentially unrelated to the project's
acquisition-research brief. This is itself a useful, honest result: T4's selector flagged this source as
unexplained and cue-dense, and a real extraction pass confirms there was genuinely little of substance here for
THIS project -- not a wasted selector pick, a correctly low-substance read.

Combined real spend today across T5 (one adjudication) and T4 (one source, six windows): **$0.352949** of the
$20 authorized -- both rungs have now executed for real, not just against the fake-provider harness.
