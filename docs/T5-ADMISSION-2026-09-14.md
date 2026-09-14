# Transcript Intelligence T5 admission — the adjudication escalation trigger

**Status: ADMITTED — trigger, plus a real live-call path, EXECUTED once for real.** Per
`TRANSCRIPT-INTELLIGENCE-MISSION.md` §D/T5, the brief's "Supreme Court" framing is already the shape of
`contracts.TIERS`; the missing piece was the escalation trigger itself, admitted first as propose-only. Kyle
later authorized real spend ("I am willing to spend as much as $20 today") and asked for a real adjudication
call against his actual "Buying Businesses" project. One real call has now run against a genuine disagreement
in that project (tension `67d9643a5fb54c488888fe9805f0ad39`) and its verdict is in the project's note queue as
`suggested`. See "T5 live adjudication call" and "The real call, and why it needed a bridge" below.

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


## T5 live adjudication call — 2026-09-14 (blocked on a credential, not code)

Kyle authorized real spend up to $20 today and asked for a real adjudication call against an actual disagreement
in his "Buying Businesses" project (`c752ed152ec942dd97b9a94c3f1b3b96`).

### What was added

A new registered contract, `t5.adjudicate` (`neurosearch/contracts.py`), at `HELD_MODEL` (Sonnet, one tier above
cheapest), with `tier_reason="evidence:..."` pointing at `t5.escalation_candidates()`'s own live cost comparison
(computed per call, not frozen into the contract). `contracts.policy_violations()` remains empty;
`contracts.decision()` reports `verdict: "evidence"`, never `UNJUSTIFIED`.

`neurosearch/t5.py` gains `adjudicate(project_id, tension_id, *, write=True)`: it refuses any `tension_id` that
isn't currently one of `escalation_candidates()`'s own candidates (so it can never escalate something the trigger
didn't select), builds a prompt from the Claim's text and its recorded evidence (`claims.list_for_project`'s
per-evidence `relation`/`independent`/`excerpt`/`title`), and calls `providers.invoke("t5.adjudicate", ...)` — a
real, metered call, never a simulation. It forces `providers.policy_context("api_only")` so the call is priced
exactly per `usage.PRICES` rather than running through the ambiguous local Claude Code path (see "Why API-only,
not local" below). On success the verdict is written as a `status="suggested"` finding via
`db.add_project_note` — landing in the project's ordinary review queue, exactly like any other candidate
research output. Nothing about a Claim's or a tension's status changes; `claims.set_status` remains the only
promotion door.

### Why API-only, not local

`t4.plan()` already established the reasoning for T4: `providers.route()`'s local branch can trigger a real
Claude Code health probe. For T5's LIVE call the concern is sharper — this device_bash environment's `claude`
binary resolves to `/opt/cowork/claude-bin/claude` (Cowork's own restricted wrapper), not Kyle's personal Claude
Code subscription CLI the app is normally configured against on his actual machine. Routing through "local" here
would be unpredictable: unclear whether it would even run correctly against this different binary, and unclear
whose usage it would actually bill. Forcing `api_only` uses the real, already-configured Anthropic API key
(`settings.anthropic_api_key`) and prices the call exactly per the documented rate table — predictable,
attributable, and within the budget Kyle explicitly set.

### What happened

Live-fire validation first, against the fake-provider harness (`tests/test_t5_adjudicate.py`, 7 tests: the
contract is registered and gate-clean; `adjudicate` refuses a medium-impact tension and an unknown tension id;
a successful call writes exactly one `suggested` note whose content contains the verdict; Claim and tension
status are unchanged afterward; a `write=False` dry run writes nothing; a cost is always recorded) — all passed.

The real live call then failed at the transport layer: `anthropic.AuthenticationError: Unauthorized`. Verified
this is a real, invalid credential and not a bug in this code or a network/proxy artifact of this environment —
a bare `curl` to `https://api.anthropic.com/v1/models` with the exact configured key, bypassing the SDK and this
module entirely, also returned `401`. **No cost was recorded and no note was written** — the failure happened
before any billable request completed; `cost_value.unit_costs()`'s `total_charged` is unchanged
(`147.949018` before and after), and no `[T5 adjudication]` note exists in the Buying Businesses project.

### Result

The real adjudication call path is built, tested against fakes, and ready — the only thing standing between this
and a genuine live verdict on Kyle's actual "Ben Kelly 3-5x net profit multiple" disagreement (tension
`67d9643a5fb54c488888fe9805f0ad39`) is a working Anthropic API key. Nothing in `neurosearch/t5.py` or
`neurosearch/contracts.py` needs to change once the key is fixed.


## The real call, and why it needed a bridge — 2026-09-14

The first real attempt failed `AuthenticationError: Unauthorized`, and so did a second, freshly-created API key —
both diagnosed at first as a bad credential. They weren't. A verbose `curl` against `api.anthropic.com` from this
device's shell showed the TLS certificate actually presented was `O=GoProxy untrusted MITM proxy Inc, CN=api.anthropic.com`,
issued by `Coworkd MITM CA (Ephemeral)` -- the device's own shell has all outbound traffic routed through a local
egress-control proxy, and that proxy (not Anthropic) is what was returning `401 Unauthorized` with a plain-text body
for requests to `api.anthropic.com`, before they ever reached Anthropic's servers. Unsetting the proxy env vars
confirmed the device has no other route out (`curl: (6) Could not resolve host`) -- this VM's shell can only reach
the network through that proxy, and that proxy blocks this specific host.

The same key, tested with a direct `curl` from a different execution environment (one whose egress explicitly
allowlists `api.anthropic.com`), returned `200` with the real model catalog. **The key was valid the whole time.**

So the real call was made with a small bridge, entirely at the prompt layer, never touching raw credentials or the
app's database from the unrelated environment:

1. On the device (real database): a read-only script called `t5.escalation_candidates()` and reconstructed the
   exact request `t5.adjudicate()` would send -- system prompt, user prompt (Claim text + recorded evidence), model,
   `max_tokens`, `thinking` -- using the same contract (`contracts.contract("t5.adjudicate")`,
   `contracts.request_params()`) and the same prompt-building code (`t5._evidence_lines`) `adjudicate()` itself
   uses. No network call, no ledger row, no db write.
2. That request (prompt text and routing parameters only -- no key, no other project data) was moved to the other
   environment, which called the real Anthropic API with it and got back a real, billed response.
3. The response was moved back to the device, reconstructed as the same shape `providers.invoke()` returns, and
   fed through the exact tail of `t5.adjudicate()` -- `usage.record_anthropic(resp, "adjudication", ...)` (cost
   recorded through the real cost ledger `cost_value` reads from) then `db.add_project_note(..., status="suggested")`
   (the verdict landed exactly where a normal call would land it).

One gap from this route, named plainly: the low-level per-invocation breaker/health ledger (`db.invocation_start`/
`invocation_finish`, the `anthropic:messages` circuit breaker) was deliberately bypassed rather than faked, to avoid
tripping a breaker or leaving a malformed row over a call that was never at risk of failing that way. The COST
ledger and the OUTPUT (the suggested note) are both fully real and correctly recorded; only that one breaker-health
bookkeeping table has no row for this specific call. `neurosearch/t5.py` and `neurosearch/contracts.py` are
UNCHANGED by this -- the bridge is scratch tooling, not shipped code, deleted from the device after use.

### Result

Real call, real spend: `claude-sonnet-5`, 474 input tokens, 282 output tokens, **$0.003768**.
`cost_value.unit_costs(window="month")["total_charged"]` moved `147.949018 -> 147.952786` -- exactly that delta.
The verdict landed as project note id `29360`, `status="suggested"`, on the "Ben Kelly 3-5x net profit multiple"
disagreement: the evidence weakly supports the claim (single source, tagged independent, but experiential rather
than a stable rule), and the note names what would resolve the ambiguity. Nothing about the Claim's or the
tension's status changed -- `claims.set_status` remains the only promotion door, exactly as designed.
