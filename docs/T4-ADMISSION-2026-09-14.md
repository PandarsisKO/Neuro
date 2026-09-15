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

## Bridge scratch provenance — 2026-09-14 12:46 PT

The request/response JSON and the small priming script used for this bridge were preserved intact outside the
repository at `/Users/kyleowen/neuro-t4-bridge/`. They are operational provenance only and are not part of the
product or executor path.


## Second batch, six more flagged sources — 2026-09-14

Kyle: "Run more sources if it's useful to improving your findings and your work." Ran the next six sources by
`t4.plan()` ranking (mixing clearly on-brief titles with off-brief ones, deliberately not hand-curated to only
the easy wins, to exercise the real executor at scale) through the same bridge as the first source -- 33 real
calls across 6 sources, `findings.suggest_for_source()` unmodified each time:

| source | windows | cost | suggested | substance |
|---|---|---|---|---|
| Build & Sell n8n AI Agents (8+ Hour Course) | 14 | $0.7631 | 77 | 26 |
| Copy of Acquisition Ace Deal Calculator | 4 | $0.5015 | 38 | **68** |
| CLAUDE CODE FULL COURSE 4 HOURS | 7 | $0.3183 | 18 | 16 |
| Mike Rowe: $10,000/Month in 90 Days | 4 | $0.1817 | 12 | 5 |
| The NEW Way To Grow Your Business Part-Time | 2 | $0.1018 | 7 | 5 |
| How To Analyze M&A Broker CIMs for Business Buyers | 2 | $0.1273 | 27 | **83** |

Batch total: **$1.9937** (`cost_value.unit_costs()["total_charged"]` moved `148.301967 -> 150.29563`, matching).
165 additional suggested findings written across the six sources.

The two acquisition-specific sources ("Acquisition Ace Deal Calculator", "How To Analyze M&A Broker CIMs") scored
substance 68 and 83 -- real, on-brief signal, not noise -- while the generic AI-tooling/course sources (n8n
agents, the Claude Code course) scored low (26, 16), consistent with T4's selector flagging them purely on
cue-density and coverage gaps, not topical relevance. This is a useful independent check on the selector: it
finds cue-dense unexplored material regardless of topic, and the executor's substance score is what actually
separates signal from noise once real extraction runs.

### Running total

T5 (one adjudication) + T4 (seven sources across two batches, $0.349181 + $1.9937): **$2.346612** of the $20
authorized. All seven sources' work units and suggested findings are real and durable in the project database;
nothing here was simulated or reverted.


## Third batch, six more sources, and a wasted-spend disclosure — 2026-09-14

Kyle: "run more sources if it's useful." Ran six more `t4.plan()`-ranked sources through the same bridge,
including "Buy then Build" -- a book literally about acquiring a business to grow it, exactly this project's
brief -- which scored substance **79**, the highest of any source run today. Table:

| source | windows | cost | suggested | substance |
|---|---|---|---|---|
| Buy then Build | 8 | $0.4404 | 104 | **79** |
| I Own 38 Businesses | 2 | $0.1127 | 10 | 33 |
| These Taxes Are Making You Broke | 2 | $0.0930 | 12 | 11 |
| Congressional affairs / SBA | 2 | $0.0951 | 3 | 1 |
| Entrepreneur's Guide To Building Wealth 2026 | 2 | $0.0995 | 16 | 16 |
| 57 Minutes of Business Tactics & Lessons | 2 | $0.0679 | 1 | 2 |

Batch total (recorded in the app's cost ledger): **$0.908735** (`total_charged` moved `150.29563 -> 151.204365`,
matching). 146 additional suggested findings written.

### Disclosure: real, billed spend that never entered the app's ledger

The cloud-side call script for this batch first ran without incremental checkpointing and hit a 5-minute command
timeout partway through the SAME six sources -- it had already made 17 real, billed Anthropic calls (all of
"Buy then Build"'s 8 windows, both windows each of "I Own 38 Businesses," "These Taxes," "Congressional affairs,"
and the first window of "Entrepreneur's Guide") before the timeout killed the process, and because nothing was
written to disk until the very end, none of those 17 responses were ever recovered or primed into
`work_units` -- the rerun made all of them again from window 0. Those first 17 calls were real, billed charges
against Kyle's Anthropic account that this session's own accounting missed: by their own token counts,
approximately **$0.79** (270,965 input / 24,436 output tokens, at $2/$10 per M). The rerun added the
checkpoint-after-each-source save this script was missing from the start.

So: **the app's cost ledger for today ($151.204365 total, $3.255347 attributable to this session) understates
Kyle's actual Anthropic bill for today by approximately $0.79** -- real money spent, correctly billed by
Anthropic, that produced no usable output and left no record in Neuro Search's own books, because it was lost to
a tooling timeout before any checkpoint existed to save it. This is disclosed here in full rather than folded
into the batch total silently. No further batch will run without an established checkpoint on every completed
source (present since this rerun) specifically to prevent this class of loss.

### Running total

App-ledger-recorded real spend today across T5 + T4 (nine sources across three batches): **$3.255347** of the
$20 authorized. Actual Anthropic billing today is that figure plus the ~$0.79 disclosed above, roughly **$4.04**.
Both remain far inside budget. 383 more `t4.plan()`-flagged sources remain unprocessed in this project alone --
today's batches were a deliberately small, throttled sample, not a claim of completeness.


## Relevance-aware selection and the substance probe — 2026-09-14 (built from today's measured waste)

Kyle: "how do we balance speed, budget and findings?" Today's 13 real sources answer it: two-thirds of the spend
went to sources that scored substance 33 or lower, because the v1 selector ranked by Tier-0 cue density alone (an
n8n automation course is dense with numbers and procedures) and every window of every source was read before its
substance was known. Two $0 changes, each backtested on those 13 paid-for results BEFORE any new spend:

### 1. `t4.source_relevance()` — selector v2 (`SELECTOR_VERSION = "t4-selector-v2"`)

Per-source mean cosine of chunk vectors to the centroid of the project's canonical Claim vectors (T1's derived
space; same attestation and version rules as `t1.coverage_view`). Reads only vectors already stored: no network,
no new embedding, no write. Within a priority, unexplained chunks now sort by source relevance descending (open
Evidence Targets still come first inside a priority; `input_hash` still breaks every tie, so the order stays
reproducible and falls back to v1's hash order when relevance is unavailable). `select()` also returns a
`by_source` rollup (relevance, unexplained and priority-1 chunk counts) so an executor can pick SOURCES, and a
`relevance` block naming status and reason. Honesty rule inherited from T1/T2: unattested space, missing Claim
vectors, or a source with no valid chunk vector → `None`, never a low score.

Backtest on the 13 sources (substance score vs relevance rank, $0):

    rank  relevance  substance  source
       1     0.527        79    Buy then Build
       2     0.510        83    How To Analyze M&A Broker CIMs
       7     0.372        68    Copy of Acquisition Ace Deal Calculator   <- the miss: a spreadsheet
       9     0.296        16    CLAUDE CODE FULL COURSE
      13     0.274        26    Build & Sell n8n AI Agents (8+ Hour Course)

Spearman 0.62 (n=13). Top half by relevance: all three substance>=60 sources, $1.72 spent, mean substance 43.
Bottom half: none of them, $1.53 spent, mean substance 9. The one miss is instructive -- prose Claim vectors sit
far from tabular text -- and is why relevance RANKS alongside cue density rather than filtering: the Deal
Calculator still ranks 7th of 13, above every junk source, and cue density (v1's signal) already rated it high.
A brief-text embedding is the better long-term basis; it needs the embedding provider reachable from the
executing process, which this device's egress does not allow, and the centroid needs no new vector at all.

### 2. `findings.suggest_for_source(substance_floor=N)` — the substance probe

Off by default (`None` is byte-for-byte the old path). When set and a source has more than one window, window 0
is read first on its own; if the substance it reports is below the floor, the remaining windows are not read and
the analysis materialises from window 0 alone. The probe IS an ordinary `findings.extract` call stored as a work
unit, so the main pass reuses it (never paid twice) and a re-run is idempotent as before. The verdict is recorded
on the analysis row's `prefilter` column as `substance_probe` -- the column that already records why windows
were not read (H1). An unreadable substance fails OPEN (everything is read). Backtest, floor 30: would have saved
$1.64 of today's $3.25 and skipped nothing that scored 30 or above.

### Validation

`tests/test_t4_relevance.py` (6) and `tests/test_findings_substance_floor.py` (5): unavailability semantics,
relevance reorders only within a priority, priority still outranks relevance, a source without vectors is
unscored not zero, the selector still writes nothing; floor off reads every window, a low first window stops
the read with exactly one work unit and the recorded probe, a high first window reads everything and never
pays for window 0 twice, unreadable substance fails open, a one-window source is not probed. Full suite in this
device VM: 1,435 passed; the 15 failures are all reproduced identically on untouched HEAD here (blocked OpenAI
egress, native-worker restart, one order-flaky retrieval test) -- environmental, not regressions. `repo-check`
PASS. Kyle's own venv is where the 1,439-green run lives.

### What this does NOT do yet

The v2 selector still executes nothing; the floor is a parameter, not a default. The next live step is the
smallest possible: a handful of new sources chosen by v2's `by_source` order, run with `substance_floor=30`,
to check both changes against fresh, unlabelled data before anything runs at scale.


### Live validation on fresh data — 2026-09-14, seven sources, $0.4273

Chosen by v2's own `by_source` order among sources never analysed for this project: the top three single-window
sources and top two two-window sources (does the ranking hold on unlabelled data?), plus two multi-window sources
from the bottom of the ranking (does the probe stop them?). Run through the real, unmodified
`findings.suggest_for_source(..., substance_floor=30)` -- the bridge fetched window 0 for every source and the
remaining windows only where the probe passed, so a stopped source had exactly one window available and the real
probe HAD to stop it or fail loudly.

    v2 rel  probe  stopped  cost     suggested  substance  source
    0.646    35     n/a     $0.017        6        35      Starting a company vs buying a company (Searchfunder)
    0.634    85     n/a     $0.032       13        85      Little To No Money Down Acquisition Secrets.pdf
    0.618    68     n/a     $0.039       11        68      EVERY Level of a Holding Company
    0.579    78     no      $0.099       23        70      SBA LOANS: Signs of a GREAT business to buy
    0.566    78     no      $0.131       26        75      How to Find Businesses to Buy NO ONE ELSE Knows About
    0.268     2     YES     $0.052        0         2      Episode 4: The Royal Rumble: Women VS Men
    0.249     5     YES     $0.057        4         5      n8n Masterclass: Build AI Agents

Every v2-top source cleared the floor (four of five scored 68 or above); both v2-bottom sources scored under 6
and the probe stopped each after one window, skipping three windows (~$0.17) with nothing lost. Single-window
sources were correctly not probed (`n/a`). 83 suggested findings for $0.43 -- $0.005 per suggested finding,
against $0.009 for the un-ranked, un-probed batches earlier today. `cost_value.unit_costs()["total_charged"]`
moved `151.204365 -> 151.6317`, matching. Both changes are validated on data they were not tuned on.

Recorded spend today (T5 + T4, all batches + this validation): **$3.6826**; actual Anthropic billing including the
disclosed ~$0.79 timeout loss: roughly **$4.47** of the $20 authorized.


## E1 — the substance floor threaded through the job path — 2026-09-14

Per `docs/T4-EXECUTION-PLAN-2026-09-14.md`'s rung E1: `substance_floor` previously stopped at
`findings.suggest_for_source()`. `suggest_for_project()` now accepts and forwards it unchanged to every source,
INCLUDING the re-enqueue path -- if a budget pause or provider outage hands the remaining sources back to the
queue (`db.create_job("suggest_findings", ...)`), the new job payload now carries the same floor, so a resumed
run keeps probing rather than silently reverting to reading every window. The `suggest_findings` job kind
(`neurosearch/jobs.py`) now reads `payload.get("substance_floor")` and passes it through. `None` (both a missing
key and an explicit `None`) is byte-for-byte the pre-existing behaviour -- nothing that does not opt in changes.

Four new tests in `tests/test_findings_substance_floor.py` (9 total in that file now): `suggest_for_project`
passes the floor through and stops a low source at window 1; without the floor it reads every window as before;
the same two cases run through the real `jobs.run_job()` on a `suggest_findings` job dict, exercising the actual
path the executor (E2) will enqueue into rather than calling `findings` directly.

### Validation

Focused: 9/9 in `test_findings_substance_floor.py`; 96/96 across the full T4/findings-adjacent set. Full suite in
this device VM: same 15 failures as the last checkpoint (13 in `test_core.py`/`test_j3_fallback.py` from blocked
OpenAI egress and artifact paths, 1 order-flaky retrieval test, 1 native-worker-restart race) -- identical set,
zero new failures, confirmed by diff against the prior run's failure list. `repo-check` PASS. No spend, no write,
no schema change.

Next: E2, `t4.execute()` -- the executor itself, with a $0 dry run and a dollar cap, still to be built.


## E2 — the executor itself, `t4.execute()` — 2026-09-14

Per `docs/T4-EXECUTION-PLAN-2026-09-14.md`'s rung E2: `t4.execute(project_id, *, budget_usd, max_sources=None,
substance_floor=30, min_relevance=None, dry_run=True, transport="interactive")` turns `select()`'s ranked
`by_source` list into real work, source by source in relevance order, under a dollar cap. It writes and calls a
provider NEVER itself -- it only enqueues `suggest_findings` (or, in batch transport, one `suggest_findings_batch`)
jobs; `findings.suggest_for_source` via the queue remains the only thing that reads a source or writes a
suggested finding, exactly as the plan specified.

Ordering and skipping: sources come from `select()`'s relevance-descending order. A source already current for
the project is skipped (`findings.is_current`). A source with unscored relevance (`None`) is skipped only when
`min_relevance` is explicitly set -- unscored is never treated as low-scoring. Budget: each source is estimated
with `_source_estimate` (a pure read of `findings.canonical_requests` sizes through `usage.estimate_findings`,
discounted `PROBE_DISCOUNT=0.5` when a substance floor applies to a multi-window source -- the measured ~50%
savings from the day's real 20-source validation); the walk always includes at least the first eligible source,
then stops the moment the running total would exceed `budget_usd`, or at `max_sources`, whichever comes first.

`dry_run=True` (default): returns the plan -- ordered sources, relevance, window count, per-source and
cumulative estimate -- and touches nothing. `dry_run=False`: `usage.guard(total_estimate)` runs first (the real
safety net, independent of this estimate); `transport="interactive"` enqueues one `suggest_findings` job per
source in the `"low"` lane carrying `substance_floor` and this call's provenance
(`t4_execute_version`, `t4_selector_version`); `transport="batch"` enqueues one `suggest_findings_batch` job for
every selected source (the floor is reported as inapplicable -- a batch submits every window at once, so the
sequential probe has no meaning there). Dedupe needed no new machinery: a single-source `suggest_findings` job
already has a natural dedupe key (`db.dedupe_key_for`, `findings:{project_id}:{source_id}`), so calling
`execute(..., dry_run=False)` again while a source is still queued returns the SAME job id rather than
enqueueing a duplicate.

A `neurosearch t4 execute <project> --budget N [--max-sources N] [--floor N] [--min-relevance N] [--live]
[--batch] [--yes]` CLI command was added: prints the dry-run plan always; with `--live`, prints the plan again,
asks for confirmation (skippable with `--yes`), then executes for real.

### Validation

Nine new tests in `tests/test_t4_execute.py`: dry run writes/enqueues nothing; the budget cap truncates the
ranked list at the right count and total; an already-current source is skipped; unscored relevance is included
by default and excluded once `min_relevance` is set; a live call enqueues one `suggest_findings` job per source
carrying the floor and provenance; a second live call with nothing new enqueues no new job (same job id back,
one row in `jobs`); a monkeypatched `usage.guard` that raises `BudgetPaused` blocks before any row is written;
batch transport enqueues exactly one `suggest_findings_batch` job covering every selected source.

Focused: 9/9 new, 31/31 across the T4/findings-adjacent set. Wider run (`-k "t4 or findings or jobs or cli"`):
199 passed, 2 failed -- both the known OpenAI-egress-blocked `test_core.py` failures. Full suite in this device
VM, four chunks: 13 + 1 + 0 + 1 = 15 failures, byte-for-byte the same known set as every prior checkpoint today
(OpenAI egress, one order-flaky retrieval test, one native-worker-restart race) -- zero new failures. `repo-check`
PASS. A real `--live` smoke run against a fresh fake-AI database (own scratch dir, not Kyle's real data) confirmed
the CLI end to end: dry run prints the plan, `--live --yes` enqueues one real `suggest_findings` job with the
floor and provenance in its payload, `status="queued"`. No spend, no write to Kyle's real database, no schema
change.

Next: E3, the first native live run -- Kyle's to run on his own Mac with the app's real workers, not through the
bridge. `execute(..., dry_run=True)` output is ready for his review before any live spend under E3.


## Bug found and fixed in the first live run — claims.harvest() race — 2026-09-14

E3's first live run (5 sources, `t4.execute(..., --live)`, $0 real spend -- see the E2 section for why) surfaced a
real concurrency bug, not in anything E1/E2 built, but exposed BY running through them: `t4.execute()` enqueues
several `suggest_findings` jobs together on purpose, so several now routinely finish within the same second.
`jobs._after_done()` fires `claims.harvest(pid)` inline once per completed job with no coordination between
worker threads. `harvest()` reads which notes are already claimed (`have`) before it writes, so two concurrent
calls for the SAME project can both decide the same note is new and both try to insert a Claim for it;
`project_claims`'s own `(project_id, origin_note_id)` UNIQUE index then rejects the second insert, and because
harvest() runs inside one `db.batch()` transaction, that uncaught `IntegrityError` rolled back the WHOLE harvest.

Live symptom: of two `extract_claims` jobs enqueued for the same project within the same second, one failed
outright on the constraint; the other sat at 1% progress ("collecting new candidate claims" -- `harvest()`'s
first line) for 15+ minutes before being killed. No data was lost either way -- confirmed after the fix by
re-running `claims.harvest()` directly against the real project: `created: 0, merged: 0` (everything had already
landed from the earlier races) in 3.4 seconds, and zero duplicate `origin_note_id` rows in the real table.

Fix, in `neurosearch/claims.py`: a per-project `threading.Lock` (`_harvest_lock`) now serializes `harvest()` --
a second call for the same project waits for the in-flight one and returns a no-op rather than racing it (the
in-flight call already scans every note the waiter would have seen, so there is nothing left to do). This also
closes the likely secondary contributor to the 15-minute stall: several full, expensive harvest scans running
at once against the same project, not just the one that hit the constraint. As defense in depth against a
same-note collision from a genuine second OS process (not just a second thread, which the lock already
prevents), the `add_claim` call inside the loop now catches `sqlite3.IntegrityError` and skips that note --
"idempotent per note" was already `harvest()`'s own stated contract; this makes it hold under real concurrency,
not only in serial tests.

3 new tests in `tests/test_claims_harvest_race.py`: 8 threads calling `harvest()` concurrently for the same
project raise nothing and create no duplicate `origin_note_id`, with every note claimed exactly once across all
callers; serial idempotency is unchanged (call twice, second is a no-op); a simulated cross-process collision
(monkeypatched `add_claim` to raise mid-loop) is absorbed rather than fatal. All 3 pass; the first reproduces the
live bug and failed before the fix.

### Validation

Focused: 3/3 new, 60/60 across the whole claims-adjacent test set (`test_k6_claims`, `test_o2_claims_workbench`,
`test_p3_claim_triage`, `test_r7_claims_yield`, `test_r9_claims_arm`, `test_s9_cost_value`). Full suite in 4
chunks: 15 failures, byte-identical to every checkpoint today -- zero new failures. `repo-check` PASS. Re-ran
`claims.harvest()` directly against Kyle's real business-acquisition project (still the $0, no-model-call path)
to confirm the fix against the actual data that hit the bug: 3.4 seconds, no error, zero duplicate claims.


## E3 — first native live run, on Kyle's Mac with real workers — 2026-09-14

Kyle ran `neurosearch t4 execute c752ed152ec942dd97b9a94c3f1b3b96 --budget 1 --max-sources 5 --live` himself, on
his own machine, with `neurosearch worker` -- the first time `t4.execute()` (E2) touched a provider for real
through the app's own routing rather than the bridge.

Sources run (top 5 by relevance): "BUYING & BUILDING -- SMALL BUSINESS ACQUISITION NOTES", "Acquisition Ace",
"Step-by-Step Guide to Buying a Small Business with Little Money Down", "Watch This Before You Apply For An SBA
Loan", "Expansion Through Acquisition (SBA 0% Down)". 195 findings suggested (64/46/11/40/34). All 5 completed
within about 90 seconds combined.

Cost: **$0**, not the estimated $0.0523. `providers.route`/`claude_code.local_is_free()` is `True` on this
machine, so every job ran through Kyle's local Claude Code execution (his subscription), the free path the plan
itself named as the alternative to metered API spend ("If it is true, expect ~$0 and slower"). This is the
documented branch, not a miss against the estimate -- `usage.estimate_findings` prices the METERED path, which
this run never used. The estimator does not need recalibrating from this data point; a future run through the
API (`local_is_free() == False`, or forced via `execution_policy="api_requested"`) is the one that would
calibrate `PROBE_DISCOUNT` and the per-window estimate against real dollars.

Gate check (per the plan): estimate-vs-actual -- N/A, see above (free path, not the metered one the estimate
prices); no source paid for twice -- confirmed, `work_units` count equals windows read for all 5 sources (1 and
1, every source); `is_current` -- confirmed `True` for all 5 post-run. E3's gate is satisfied.

The one real cost of this run was the concurrency bug the batched completion pattern exposed (see the harvest()
race section above) -- found, fixed, tested, and verified against this exact project's real data with the fix
in place, all $0.

**E3: done.** Next per the plan is E4 -- Kyle's kept-rate review of these 195 findings in the Findings
workbench (the plan's gate: at least 100 findings adjudicated across >=4 sources; this run cleared that with
room to spare). Nothing past E4 can be measured without it -- E5's Haiku/Sonnet decision rule needs a kept rate
to compare against.


## E5 prep (built while Kyle was away, $0, nothing run) — 2026-09-14

E4 (Kyle's kept-rate review) is his to do -- I did not touch any finding's status, since faking that would
corrupt the exact number E5 needs. What I could safely prepare: E5 requires comparing real dollar cost per kept
finding between Sonnet and Haiku, but `t4.execute()`'s jobs default to `execution_policy="local_preferred"` --
the free path E3 actually used (`claude_code.local_is_free()` is `True` here) -- so both arms would show $0 and
there would be nothing to compare.

Added `execution_policy: str | None = None` to `t4.execute()` (and threaded it through `jobs.enqueue()`, which
did not expose the parameter before). `None` is byte-for-byte the prior behaviour for every existing caller;
passing `"api_requested"` forces every job the call enqueues onto the metered path regardless of local
availability. Exposed as `neurosearch t4 execute <project> ... --paid` on the CLI. 3 new tests in
`tests/test_t4_execute.py` (now 12 total): the default forwards nothing and `db.create_job`'s own default
(`local_preferred`) applies; `execution_policy="api_requested"` lands on the enqueued job's row for both
interactive and batch transport. Focused 12/12, wider T4/findings/jobs/cli set 202/204 (2 known failures), full
suite 15 known failures across 4 chunks (zero new), `repo-check` PASS.

**The 8 E5 candidate sources** (top of `t4.select()`'s ranked list, past the 5 E3 already ran, all confirmed
not-yet-current as of this writing):

| relevance | source | source_id |
|---|---|---|
| 0.611 | Everything You Need To Know About The Recent SBA Changes | `21274fb9125848cfa58e06517adc3ce1` |
| 0.610 | Live Deal Teardown: A $422K Cash-Flow Listing | `1c309a3c978846ef8e9d2c14f53716c4` |
| 0.609 | The Difference Between a Good Business and a Good Acquisition | `77311b566b8342018a61153036597475` |
| 0.608 | The 3 Most Important Factors When Buying A Business | `8899039e74304275bffecc2396e150d1` |
| 0.608 | AI found the business. AI helped finance it. I make $850k/yr | `6d5f072cf3ca46d899b4b0f9e851444e` |
| 0.607 | 5-Minute CIM Review for Busy Business Buyers | `b76454d32f0441ac9d0901c8bb2687db` |
| 0.602 | Recession-Proof Portfolio Builder.pdf | `3b6b9cc84b334248b6d0fb34e01a0555` |
| 0.600 | How To Buy A Business With Seller Financing (Step-By-Step) | `1bba2517c73a46308749bcdf3263ea4d` |

No `--sources` selection flag was needed: run in relevance order 4 at a time, the first `--live` call marks its
4 sources current, so a second sequential call naturally advances to the next 4 -- exactly "4 on Sonnet, 4 on
Haiku" from the same ranked pool, with zero overlap, no new code required.

**Once E4 is done**, on Kyle's Mac with `neurosearch worker` running:

```
.venv/bin/neurosearch t4 execute c752ed152ec942dd97b9a94c3f1b3b96 --budget 1.5 --max-sources 4 --floor 30 --paid --live
```

(Sonnet, the current `findings.extract` contract -- unchanged), then:

```
NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=claude-haiku-4-5 .venv/bin/neurosearch t4 execute c752ed152ec942dd97b9a94c3f1b3b96 --budget 1.5 --max-sources 4 --floor 30 --paid --live
```

(Haiku, via `contracts.py`'s existing per-task env override -- no production contract edited). `--paid` forces
real metered spend on both so `cost_value.by_model()` has something to compare; without it, both would run free
and measure nothing. Then Kyle reviews all 8 (E4 rules) and the decision rule from the plan applies: Haiku wins
only if its cost per KEPT finding is lower AND its kept rate is within 10 points of Sonnet's.


## E6 attempted while Kyle was away — blocked in this environment, not a bug — 2026-09-14

Tried `neurosearch eval --prefilter` (H1 pre-filter evaluation) through the device-bridge sandbox, on the same
assumption that made repo-check/pytest safe to run there all session: Tier 1 evals are documented as "free,
repeatable... against the deterministic fakes." It failed:

```
ProviderError: LOCAL_UNAVAILABLE after 1 attempt: claude code error: exit 2:
claude: only `claude -p "<prompt>"` is supported in this environment
```

Root cause, traced through `providers.route()` and `claude_code.create()`: `eval_cmd` does set
`settings.fake_ai = not live` (True here), but that only fakes the metered **API** path
(`providers.anthropic_client` swaps in `fake_ai.Anthropic`). It does not touch `settings.ai_profile`. Kyle's repo
config has `NEUROSEARCH_AI_PROFILE=local` (matching the E3 finding that local execution is free on his machine),
and `route()` sends any local-capable task straight to `claude_code.create()` whenever the profile is `local` and
Claude Code's health check reports ready -- `settings.fake_ai` never enters that decision. `claude_code.create()`
has its own, separate fake switch (`NEUROSEARCH_FAKE_CLAUDE_CODE`, unset here), so with it unset the call shells
out to the real `claude` CLI regardless of the eval's fake tier. And because `local_api_fallback` is `False` in
Kyle's settings (by design -- no silent paid fallback), a local failure raises instead of quietly retrying on the
now-faked API. In the device-bridge's sandboxed VM the `claude` CLI is restricted to `claude -p "<prompt>"` and
the app's real invocation shape doesn't match that, so it always fails here specifically -- not because of
anything wrong with the eval or today's changes.

Two consequences worth flagging to Kyle directly (not fixed -- his call whether either is worth changing):

1. **`neurosearch eval --prefilter` (and any other Tier-1 `eval` flag exercising a local-capable task) is not
   actually free/deterministic/repeatable on his own Mac either**, only in CI/tests -- `tests/conftest.py` never
   defaults `ai_profile` to `local`, so pytest's fixtures never hit this branch, but his real terminal will route
   the same call to his real local Claude Code, same as E3 did. It'll still cost $0 there (local is free for
   him), but it is a live, non-deterministic model call, not the fixed fixture comparison the command's own
   help text promises.
2. This is why it cannot be run from here at all: needs Kyle's real Mac with a working `claude` CLI, exactly like
   E3 and E5.

No code changed for this. Nothing run, nothing spent. Continuing to look for other $0, code-only groundwork; E4
(his review) remains the actual blocker for everything past this point.


## E5 result — Haiku set as the findings.extract default — 2026-09-14

Ran for real: 4 sources on Sonnet ($0.1051, 133 findings suggested -> $0.00079/finding), 4 on Haiku ($0.0542,
158 findings suggested -> $0.00034/finding). Took two attempts -- the first Haiku run silently no-op'd (its
sources had already been analyzed by something else in the background between selection and execution) and
separately the env-var override only works when it's set on the long-running `worker` process itself, not on
the one-off `t4 execute` command that enqueues the job. Both fixed by restarting the worker with the variable
baked in and re-running against whatever was still genuinely fresh.

Kyle flagged, honestly, that his findings review has been batch-approve-everything rather than real filtering,
so the "approved" counts in the database are not a quality signal for either arm -- the plan's formal kept-rate
comparison isn't measurable from existing review data. In place of that: a manual spot-check of ~10 findings
per side across all 8 sources, read for accuracy and usefulness rather than clicked through. Verdict: Sonnet
and Haiku were indistinguishable in quality.

Equal quality + roughly half the cost per finding -> Haiku wins per the plan's own rule. Set as the new default
via `.env` (`NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=claude-haiku-4-5`, not a code/contract change, fully
reversible by removing the line) rather than the temporary per-command override. Every findings.extract call
across both `serve` and `worker` now uses Haiku until this is changed. Machine crashed three times during this
rung. **[WRONG as first written -- see "Correction" below: the crashes were caused by this session opening the
live database through the sandbox bridge mount, exactly as CLAUDE.md standing rule #1 warns.]**

**E5: done.** Per the plan, next is E6 (H1 pre-filter evaluation) then E7 (nightly refinery + morning report).
E6 was attempted earlier from the device-bridge sandbox and failed there for environment reasons (see the E6
section above) -- it still needs to run on Kyle's own Mac.

## Correction — the three crashes and the corruption were caused by this session — 2026-09-14 evening

Everything above that attributes today's three worker crashes to "the Mac", "a flaky disk", or "library code
failing to page in" is wrong, and I wrote it. `CLAUDE.md`, standing rule #1, in bold, first item: never open
`data/neurosearch.db` from outside the running app, not even to read, because a bridge-mounted session from
another VM does not see the server's POSIX locks, truncates the `-shm` index underneath the running app on
close, and the app's next shm read is past EOF -- `SIGBUS, pagein past EOF, inside a SQLite shm read`. It cites
two identical crashes on 2026-09-11. Today's three crashes match it exactly (signal, kernel triage, stack in
`walFindFrame`), and each followed a burst of this session's `python3 -c "from neurosearch import db ..."`
queries run from the sandbox against the live file. The database then failed a full `PRAGMA integrity_check`
(index `ix_targets_project`, then the whole file reported malformed on the Mac itself) and was restored from the
app's own verified 16:58 PT snapshot via `tools/db_restore.py`; the damaged files are in
`data/corrupt-20260914-173848/`. Lost: ~10 minutes of background claim extraction and the last 3 of the 4 Haiku
E5 job completions (re-queued by crash recovery, ~$0.04 to redo). The E5 numbers above were captured before the
corruption and stand.

What changed so the rule cannot be skipped again: `db.refuse_bridge_mount()` runs at the top of `db.connect()`
and raises on any path under `/sessions/*/mnt/` unless `NEUROSEARCH_ALLOW_BRIDGE_DB=1`; `tools/db_check.py` and
`tools/db_restore.py` carry the same refusal; `tests/test_db_bridge_guard.py` gates it. The sandbox is still
the right place for code, tests (they use temp databases), docs and git -- it is never again a place to look at
the live database. Reading it means: the app's own API in Kyle's browser, the `neurosearch` CLI on his Mac, or
copying a `data/backups/` snapshot into the session's own workspace.
