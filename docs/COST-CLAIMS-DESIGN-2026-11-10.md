# Cost mission: Claims experiment design and Claims dating fix (2026-11-10)

Status: Claims reporting repair and library disclosure prepared and fully validated on an isolated branch; activation held.
The paid experiment remains design only and has not run. No production routing has changed. Authority: the Cost Reduction mission
checkpoints (owner approval required before any paid run or app-interrupting delivery).

## 1. Evidence behind it (read-only, from the live API and the owner's invoices)

- Last 30 days, Neuro's estimate: $298.65, of which Claims $228.73 (77%). This is API-equivalent, not billed: the
  owner's invoices show **no extra-usage charge between Oct 1 and Nov 1** (the sweep ran inside the Max plan). Real
  charges since moving to Pro: $62.61 of auto-recharges on Nov 2-3. Console API spend in the same 30 days: $1.41,
  equal to Neuro's recorded chat spend, so Neuro's API-side accounting is exact.
- The Oct 11-19 sweep was 673 `claims.extract` calls, all on `claude-sonnet-5`, priced at that model's own rates
  (about $0.34 per call). At EXTRACT_GROUP=8 that is at most about 5,400 claims, so roughly $0.04 per claim, matching
  the lifetime figure ($865 on 21,295 Sonnet 5 claims). The $0.259 per claim shown for the window is **not real**: see 2.
- `claims.extract` is the contract model `HELD_MODEL` (`claude-sonnet-5`, $2/$10 per M tokens), `local_capable`,
  `batch_allowed`, thinking disabled, groups of 8. Findings were moved to Haiku 4.5 through `.env`; Claims has no
  override. Haiku 4.5 is $1/$5, exactly half the price per token.

## 2. Plan: date Claims by when they were normalized (replaces "record the model")

The model is **already recorded**: `project_claims` has `model`, `prompt_version`, `routing`, `transport`. The 883 claims
with no model in the window are `$0` harvested candidates (`normalized=0`) waiting for the paid step.

The real defect: `claims.extract` normalizes rows **in place** (`claims.py` around lines 1121/1130), so `created_at` stays
the harvest time. `cost_value` counts claims by `created_at`, so spend lands in one window and its claims in another.

- Add an additive column `project_claims.normalized_at REAL` (same ALTER-if-missing pattern as other additive columns).
  Set it when a row becomes `normalized=1`. Legacy rows stay NULL.
- `cost_value._claims_counts`, `by_model` and `trend` for the claim units count by `COALESCE(normalized_at, updated_at)`
  and report how many rows used the `updated_at` fallback, because `updated_at` is also touched by status changes and
  evidence (approximate, never presented as exact).
- Tests: a new normalization stamps the column; a windowed count follows normalization time, not harvest time; the
  fallback is flagged; per-claim cost for a window equals window spend divided by claims normalized in it.
- Risk: low (additive column, read-side reporting only). Delivery restarts the app, so it needs owner approval.

## 3. Experiment: claims.extract on Haiku 4.5 versus Sonnet 5 (needs separate paid-experiment approval)

Reuse the existing claims arm (`migration.py`, "claims arm"): cohort `CLAIMS_EVAL_BUDGET` = 40 candidates (5 calls per
arm), judged by the product's own `claims.run_evaluation` (qualifiers preserved, hedges kept, over-generalizations,
merges, type changes); runs in a temporary database; the cohort is reset between arms (`_reset_normalization`).

- Baseline: `claude-sonnet-5` (current production). Candidate: `claude-haiku-4-5`. The harness's default pair is
  Sonnet 4.6 versus Sonnet 5, so passing these two models is a small harness change to confirm before any run.
- Transport: forced to API (`_force_api_transport`, cloud + api_only), verified per arm by `_assert_arm_model`. It
  bills the Console balance ($23.12, visible on the Console Cost page), not Pro credits or the Pro usage limit.
- Expected spend from the harness's own model: about $0.16 (Sonnet 5 arm) + $0.08 (Haiku arm) = about $0.23;
  maximum with its 1.5x safety about $0.35. Proposed hard cap: **$1.00**. A whole-migration run costs more and is not proposed.
- Pass rule (frozen before running): adopt Haiku only if qualifier preservation is within `CLAIMS_QUALIFIER_TOLERANCE`
  (10 points) of Sonnet 5, no more over-generalizations or lost hedges, and no failed schema. Otherwise keep Sonnet 5.
- Limits: 40 candidates is a gate, not proof. If it passes, deliver the override the same way findings did
  (`NEUROSEARCH_TASK_MODEL_CLAIMS_EXTRACT`, to be confirmed), watch `by-model` for the first real batches, and keep
  Sonnet 5 as the one-line rollback.
- Expected benefit: about 50% on Claims per token. A repeat of the October sweep would drop from about $228 to about
  $114 (estimate, token counts for Haiku may be higher: the harness assumes +30%, which is already in its $0.08).
- Cheaper alternative: none that measures quality; the fake-AI tier does not.

## 4. Not in scope here

Batch API for Claims (50% off, applies only on the API transport), re-using extraction results, and the ranking task
(about $34 estimated over 30 days on Sonnet 5): later rungs of the cost ladder, each to be baselined first.


## 5. Codex takeover: reporting repair and checkpoint limits (2026-11-10)

Owner approval: "Approved. Continue with instruction-enforced checkpoints in Codex and repair the Claims report.
Treat hard runtime enforcement as unresolved. No paid experiments or app restarts yet."

Base: `687b81d`; isolated branch `codex/claims-report-repair` at `/private/tmp/neuro-claims-report-20261110`.
The shared checkout, live application and live database remain untouched. No paid experiment is authorized in this interval.

S114's `updated_at` fallback can count later reviews as paid normalization. Merely flagging approximate counts still
publishes a misleading ratio. The repair retains costs and approximate counts but withholds the affected normalized
unit ratio, affected model ratios/comparability, and all ratios in an affected Claims trend window. Trend suppression
covers all days because the last edit cannot locate the original normalization day. Scope is the requested project
and window; unrelated projects and legacy rows last updated before the window do not suppress exact results.
Tracked-Claims totals still describe creation, including free harvest, as before. No data, prices or routing change.

Do not substitute a claimed exact cost or a call-count ceiling: the currently configured group size is not a proven
historical output count. The earlier ~$0.04 estimate is not a measured per-claim result. Affected historical ratios
remain unavailable; this repair does not reconstruct missing normalization timestamps.

Checkpoint investigation: local Claude Code is 2.1.306; no hooks or agent definitions were present in the inspected
project/user settings. Official hooks documentation supports SessionStart, PreToolUse, PreModelSwitch and
PostModelSwitch; `onFailure: "block"` requires >=2.1.295. Those Claude hooks do not enforce this Codex chat.
No hooks were installed and no runtime enforcement claim is made. Agent-writable approval files cannot establish
owner authorization. Installation must also account for Neuro's existing Claude subprocesses rather than blocking
production processing accidentally. Owner explicitly accepted instruction-based checkpoints here; hard runtime
enforcement and its seven acceptance tests remain unresolved, not completed.
Reference: https://code.claude.com/docs/en/hooks

Baseline focused tests: 39 passed, 1 existing Starlette/anyio warning. Candidate focused billing/report/isolation tests:
61 passed, 1 existing warning. Regression cases cover mixed exact/legacy output, withheld model verdicts, separate
spend/output days, and project/window isolation. Full pytest, Tier 1 and release-check results are recorded in HANDOFF.
Paid Claims experiment, harness task filter/cap, production model changes and app activation remain pending approval.


## 6. Final combined candidate validation (activation held)

Candidate `c2cf414`: full suite **2,636 passed** (447.08 s, one existing deprecation warning), Tier 1 **PASS**,
release-check **PASS**. Final source hashes unchanged. Canonical evidence and exact commands are in the newest
HANDOFF entry and `evals/release/claims-library-candidate-20261110.json`. Evidence is published on the repair
branch only. Main, the live app and production settings are unchanged. No paid experiment or restart occurred.
