# Transcript Intelligence T5 admission — the adjudication escalation trigger

**Status: ADMITTED, trigger only, no live adjudication call.** Per `TRANSCRIPT-INTELLIGENCE-MISSION.md` §D/T5, the
brief's "Supreme Court" framing is already the shape of `contracts.TIERS`; the missing piece was the escalation
trigger itself. This admission is that trigger, PROPOSING adjudication candidates from real recorded signals — it
does not execute one. Built alongside T4/T6 under Kyle's "do 4/5/6 now" authorization.

## A stated scoping decision

Kyle authorized "do 4/5/6 now" including T5, despite my earlier flag that T5 is the first rung with real
per-use provider spend and a judgment threshold decision. Building the capability and spending real money on it
are different asks, so this slice makes no live paid provider call anywhere: `neurosearch/t5.py` only proposes
adjudication candidates and a properly-formed contract for each; nothing invokes a provider. Validation is against
the existing fake-provider test harness only, matching this codebase's own `batch_smoke.py --live`-opt-in
convention (T5 doesn't even need the flag — it makes no call to opt out of). Whether and how to actually run one
of these proposals live is Kyle's decision once he has seen this slice.

## Problem and evidence

`contracts.py` already enforces "cheapest tier unless a stated, admissible reason" for every registered contract
(`decision()`, `policy_violations()`), and `cost_value.by_model` (added 0.59.3) already answers per-model cost
per finding/claim from real recorded spend. What was missing is a trigger that decides *when* an ad-hoc
adjudication task is worth proposing, and constructs the reason for it from a live measurement rather than an
opinion.

Reading the current codebase (not inventing a new signal) found a real, existing "sources materially disagree"
detector already running: `knowledge.py`'s deterministic tension pass writes `research_tensions` rows with
`kind` (`CONTRADICTION` | `NOVEL` | `WEAK_CONSENSUS` | `STALE` | `MISSING_PERSPECTIVE`) and an `impact`
(`high`/`medium`/`low`). `CONTRADICTION` is literally "sources materially disagree." `NOVEL` and `WEAK_CONSENSUS`
are literally "a Claim's evidence is thin or non-independent" — the mission doc's "ambiguous evidence."

## Scope of this admission

`neurosearch/t5.py`, pure and read-only:

1. `escalation_candidates(project_id, *, unit="claim", window="month")` reads open tensions
   (`knowledge.list_tensions`) and keeps only `impact == "high"` `CONTRADICTION` (-> `source_disagreement`
   trigger), `NOVEL`, or `WEAK_CONSENSUS` (-> `ambiguous_evidence` trigger) rows. `STALE` and
   `MISSING_PERSPECTIVE` never trigger — neither means "disagreement" or "ambiguous evidence" in this codebase's
   own vocabulary.
2. For each, it calls `cost_value.by_model(unit, window)` — a live measurement, never a stated number — and
   builds an `evidence:<detail>` `tier_reason` naming the cheapest currently-measured model and its per-unit
   cost (or plainly says no comparable data exists yet, rather than fabricating one).
3. It constructs a `contracts.InferenceContract` proposal (model = `contracts.TIERS[1]`, i.e. Sonnet, one tier
   above cheapest) and runs it through the real `contracts.decision()` function — the same function
   `neurosearch models` uses — to prove the reason is accepted, never `UNJUSTIFIED`.
4. Nothing is registered into `contracts.py`'s own `_base()` contract table, no provider is called, and no row
   is written anywhere.

## Explicit non-goals for this slice

- No live provider call, ever, in this pass — see the scoping decision above.
- No "cheaper systems disagreed" trigger — no signal for a same-task cross-tier comparison currently exists in
  this codebase; inventing one would be a separate, future rung with its own measurement design, not this one.
- No wiring of `escalation_candidates`' output into any actual workflow, job, or UI — these are proposals for a
  human (or a future rung) to act on, exactly as T4's selector output is not yet acted on either.
- No change to `contracts.py`, `cost_value.py`, or `knowledge.py` — T5 reads existing seams as they are.

## Gate

Per the mission doc: "the model decision table (`neurosearch models`) still refuses any tier above the cheapest
without a stated reason; the split is justified by a live comparison, not by this document." Verified directly:
`test_every_proposed_reason_is_admissible_to_the_real_ladder` asserts every candidate's `tier_reason` passes the
real `contracts.policy_reason_ok` and that `contracts.decision()` never returns `UNJUSTIFIED` for one; the reason
is always a live `cost_value.by_model` read, never a hardcoded string
(`test_comparison_detail_reflects_live_recorded_data_not_a_stated_opinion`).

## Validation

Focused: `tests/test_t5_escalation.py` (10 tests: `CONTRADICTION` triggers `source_disagreement`; `NOVEL`/
`WEAK_CONSENSUS` trigger `ambiguous_evidence`; medium/low-impact tensions never trigger; `STALE`/
`MISSING_PERSPECTIVE` never trigger even at high impact; a resolved tension is excluded; the comparison detail
reflects live data; an empty project returns no candidates; the function is read-only — job/tension/claim row
counts unchanged before and after; every proposed reason is admissible to the real ladder; two calls return an
identical, stably-ordered result) — 10 passed. Run together with the contract/cost_value/knowledge/claims suites
(70 total) to confirm no interaction with the seams T5 reads.

Full suite: 1,382 of 1,397 pass — the same 15 pre-existing failures as every checkpoint since the T3
gold-adjudication closure, none introduced by this change. `repo-check` shows the same one pre-existing warning.
Commit-bound `release-check --no-pytest` shows the same pre-existing FAIL causes; every deterministic gate this
change could affect passes.

## Result

T5's escalation trigger is admitted: a pure, deterministic module that proposes adjudication candidates from
real disagreement/ambiguity signals already computed by this codebase, each carrying a gate-admissible reason
built from a live cost measurement. No live adjudication call has been made. Whether and when to run one for
real is a decision for Kyle, not this rung.
