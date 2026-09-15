# EXECUTION LADDER — Product Intelligence Mission

Machine-executable work queue for `PRODUCT-INTELLIGENCE-MISSION.md` (rulings win). Any session -- Sonnet, Haiku,
Codex -- picks up here without conversation context. Admission authority stays with `PRODUCT-SCHEDULER.md`;
this file is the ordered runbook for what is admitted, plus the parked tail so nobody re-plans it.

## How to execute this file

1. Pre-read, in this order, every time: `CLAUDE.md` → newest `STATE-OF-THE-APP-*` → tail of `HANDOFF.md` →
   `PRODUCT-SCHEDULER.md` → `DEVELOPMENT-OPERATING-SYSTEM.md` → the mission → `git log --oneline -15`.
2. Take the FIRST item whose status is `[ ]`, whose `lane` matches you, and whose `needs` are all `[x]`.
   Skip items whose lane is `kyle` -- report them, never do them.
3. Mark it `[~] <lane> <date>` before starting; `[x] <sha>` when the gate passes; `[!] <why>` if blocked.
   Never skip the gate. Never mark `[x]` on intent.
4. Validate before every commit: focused tests → the wider set the item names → `python -m pytest tests -q` in
   chunks with `NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=` blanked (until L-03 lands) → `repo-check`.
   Known-failure baseline is 14 (2026-09-14); zero NEW failures is the bar. Compare names, not counts.
5. Two commits per item minimum: code, then the docs/checkpoint. Append a dated checkpoint to `HANDOFF.md`
   (what, evidence, sha, next). Commit messages end with the session attribution.
6. Cost: state the dollar estimate before any metered call; `--paid`/`api_requested` is never a default; local
   Claude Code is free here (`claude_code.local_is_free()` is true) but has usage limits that make work WAIT.
7. Never open `data/neurosearch.db` from a sandbox (CLAUDE.md rule #1; `db.refuse_bridge_mount` enforces it).
   Anything that must read the live database is a `tools/*.py` script Kyle runs on the Mac, or a copy of a
   `data/backups/` snapshot in the session's own workspace.
8. Live-patching `neurosearch/*.py` while Kyle's `serve --reload` runs restarts his server. Say so first.
9. `tier: haiku` = mechanical, fully specified, safe for a smaller model. `tier: sonnet` = judgment, design,
   ambiguity, anything touching product behavior or reliability semantics. When unsure, sonnet.
10. Stop and ask Kyle only for: money above the stated estimate, a product decision the item marks `kyle-decides`,
    or a gate you cannot honestly pass. Otherwise keep going to the next item.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked · `[k]` waiting on Kyle

---

## Stage 0 — Tonight and standing prerequisites

### L-00 `[k]` Rebuild the 409 stale carrying-weight sources overnight, $0 — lane: kyle
No scheduler exists yet (that is L-20). Rulings §4: never promise "2 AM". Tonight's honest path:
- Findings → review panel → "Accept 389 as still usable" (instant, free).
- Restart the worker awake: `caffeinate -i .venv/bin/neurosearch worker` (lid open, plugged in).
- Click "Rebuild · $0 · Claude Code (4 at a time)" for the 409. ~2h17m local, waits (never pays) on usage limits.
Gate: morning Findings panel shows the 409 current; `usage` shows $0 for them.

### L-01 `[k]` `.zshrc` dead `deno/env` line — lane: kyle · 5 seconds
`sed -i '' '/Aerop-Ops-Pro.*deno\/env/s/^/# /' ~/.zshrc`

---

## Stage 1 — P0 Autonomous Execution Admission Audit (lane: claude 2026-09-15 through the weekend reset -- Codex is off until then, Kyle reassigned this stage so it isn't idle for 5 days; tier: sonnet)

AUDIT, not build (rulings §1). Each scenario: write the test that exercises EXISTING machinery, run it, record
pass/fail in `docs/P0-AUDIT-<date>.md`, fix only a measured failure, re-run. Boundary is `t4.execute(...)`.
`needs`: nothing. May run in parallel with Stage 2.

### L-10 `[x] c086341` P0.G database safety preflight — needs: —
Add `db.preflight_autonomous(envelope_id)` : full `PRAGMA integrity_check` (NOT quick_check) → require `ok` →
`db.backup()` (already verifies) → record `{envelope_id, ts, backup_path}` in `kv`. Once per envelope, shared by
every job in it (rulings §1.G). Also: `db.integrity_check()`'s `ok` must include `dangling_origin_note_id == 0`
(baseline is 0 since `tools/db_cleanup_legacy.py`, 2026-09-14). Tests: preflight refuses a malformed copy;
one backup per envelope across N jobs. Gate: tests green; `doctor` reports last preflight.

### L-11 `[x] 957e31c` P0.A repeated execution — needs: —
Test: `t4.execute(pid, budget, dry_run=False)` twice on a fake-AI temp DB with the same inputs → second run
enqueues 0 jobs (dedupe_key `findings:{pid}:{sid}` + `is_current`), 0 new `project_notes`, 0 new `project_claims`,
0 new `usage` rows. Then with the `suggest_findings` jobs actually run by a fake worker. Gate: all four zeros.

### L-12 `[x] 57f3fc7` P0.B governing input changes mid-flight — needs: L-11
Found a real, narrow gap (not just an audit): `findings.suggest_for_source()`'s pre-existing `_inputs_current()`
mid-flight guard already refused to write stale-tagged results, but raised a bare `RuntimeError` that
`jobs.execute()`'s retry classification (`TRANSIENT` regex) doesn't match -- so the job was marked terminally
"failed", never retried, despite its own message promising "kept for retry". `suggest_for_project()`'s per-source
try/except then swallowed it as an ordinary per-source failure on top of that. Fixed by raising `jobs.Yield`
(the existing safe-boundary requeue mechanism -- immediate, uncounted) at all 3 check sites, and letting it
propagate through `suggest_for_project()` (re-raised before the generic except, alongside the existing
`BudgetPaused`/`ProviderUnavailable` re-raise) instead of being counted as a source failure. New end-to-end test
(`tests/test_p0_governing_input_change.py`) drives the real `create_job` -> `claim_job` -> `jobs.execute()` path:
asserts `"queued"`, zero attempt penalty, immediate `not_before`, nothing written under the stale brief, then a
clean retry completes under the post-edit brief revision. Full suite 1494 passed; `repo-check: PASS`.

### L-13 `[ ]` P0.C restart/retry — needs: L-11
Kill a fake worker mid-`suggest_findings` (after the provider call, before `replace_suggestions` commits); restart;
confirm crash-recovery re-queues, the second attempt does not double-record `usage` where the first call's
result was lost, `work_units` count equals windows read. Gate: test green; if double-spend is unavoidable, the
audit doc says so and why.

### L-14 `[ ]` P0.D budget exhaustion — needs: L-11
`usage.guard` / daily budget hit mid-run: remaining jobs `wait_reason='budget'` with `not_before`, nothing
half-written, accepted claims untouched. Gate: test green.

### L-15 `[ ]` P0.E promotion boundary — needs: —
Prove by test that no autonomous path (`suggest_findings`, `extract_claims`, harvest, `_after_done`) calls
`claims.set_status` or writes `status='accepted'`; only user-driven API routes do. `grep` + a test that runs the
whole T4 path and asserts every new claim is `proposed`. Gate: test green.

### L-16 `[ ]` P0.F concurrent completion — needs: L-11
Run 8 `suggest_findings` completions across 4 threads against one project (pattern:
`tests/test_claims_harvest_race.py`). Assert no IntegrityError, no duplicate `(project_id, origin_note_id)`, no
lost harvest. Gate: 20 consecutive green runs.

### L-17 `[ ]` P0 closeout — needs: L-10…L-16
`docs/P0-AUDIT-<date>.md` with a scenario table (pass / fixed-at-sha / documented-limitation). Scheduler + HANDOFF
checkpoint. Gate: every scenario is one of those three; no open-ended rewrite proposed.

---

## Stage 2 — P5 T4 evidence loop (Claude lane) — parallel with Stage 1

### L-02 `[x] 01fa165` P5.2a eval isolation — lane: claude · tier: sonnet · needs: — · $0
`neurosearch eval --prefilter` (and any Tier-1 eval of a `local_capable` task) routes to the real `claude` CLI
when `NEUROSEARCH_AI_PROFILE=local`, because `providers.route()` ignores `settings.fake_ai`. Fix ONLY the
isolation: in `cli.eval_cmd`, when `not live`, call `evals.pin_api_transport()` (exists, `evals.py:1091`) and
restore on exit, so the fake `anthropic_client` serves every call. Test: with `ai_profile="local"` and
`fake_ai=True`, `route("findings.extract") == ("api", ...)` inside the eval. Gate: `neurosearch eval --prefilter`
completes on Kyle's Mac with `tier: fake` and $0. Wider set: `tests/test_r4_local_model.py`, `tests/test_p1_perf.py`.

### L-03 `[x] 01fa165` `.env` task overrides leak into pytest — lane: claude · tier: haiku · needs: — · $0
`tests/conftest.py` already pins profile/flags (lines 13–23). Add: delete every `NEUROSEARCH_TASK_*` from
`os.environ` at import, so a developer's `.env` model override never changes what a routing test asserts.
Gate: `python -m pytest tests/test_r4_local_model.py tests/test_p1_perf.py -q` passes WITHOUT blanking the
variable on the shell; step 4 above drops its blanking clause.

### L-04 `[x] pending-sha` P5.2b measure the prefilter — lane: kyle runs, claude decides · tier: sonnet · needs: L-02 · $0
On the Mac: `.venv/bin/neurosearch eval --prefilter --out evals/prefilter-<date>.json`. Claude reads the artifact
(it is a file, not the DB). Decision rule (T4 plan E6, unchanged): enable `NEUROSEARCH_FINDINGS_PREFILTER=1`
only if net savings > 0 AND relevant-window recall ≥ 0.98. Record the decision in `HARDENING.md` (frozen-number
rule). Gate: committed artifact + written decision, either way.

### L-05 `[x] pending-sha` P5.3 kept-rate sample design — lane: claude · tier: sonnet · needs: — · $0
Haiku default is SHIPPED-PROVISIONAL (rulings §5). Design the smallest review that can contradict it: from the 8
E5 sources (4 Sonnet / 4 Haiku, ids in docs/T4-ADMISSION-2026-09-14.md), a stratified sample of ~40 findings
(5 per source, importance-stratified), blind to model, exported by a `tools/sample_findings.py` Kyle runs on the
Mac to `evals/p53-sample-<date>.json`. Review rubric: accurate to source (y/n), worth keeping (y/n), one-line
why-not. Gate: script + rubric committed; Kyle can complete it in ≤ 20 minutes.

### L-06 `[k]` P5.3 Kyle reviews the sample — lane: kyle · ~20 min · needs: L-05
Real judgments, not batch. Writes answers into the JSON the script produced.

### L-07 `[ ]` P5.3 decision — lane: claude · tier: sonnet · needs: L-06 · $0
Compute kept-rate per model, cost per KEPT finding (cost data already in the admission doc). Rule (T4 plan E5):
Haiku stays only if cost-per-kept is lower AND kept-rate within 10 points of Sonnet. Otherwise revert the `.env`
line and say so. Gate: written decision in the admission doc + HANDOFF; `.env` matches the decision.

### L-08 `[~] claude 2026-09-15` P5.1 brief-text relevance backtest -- tooling ready, needs a Mac run + decision — lane: claude · tier: sonnet · needs: — · ~$0.03 (embeddings)
`embeddings.embed_query(project["brief"])` cached in `kv` by brief revision; `t4.source_relevance()` candidate =
max(centroid-sim, brief-sim). Re-run the 20-source backtest from docs/T4-ADMISSION-2026-09-14.md (needs the
embedding provider → a `tools/` script Kyle runs, or a backup copy in the session workspace). Switch the ranking
basis ONLY if the backtest improves on spreadsheets without regressing transcripts. Gate: backtest table
committed; decision recorded; if switched, `t4-selector-v3` and tests.

---

## Stage 3 — P1A Scheduled Execution Backend (lane: claude, reassigned 2026-09-15 -- see Stage 1 header; tier: sonnet) — needs: L-17

### L-20 `[ ]` `not_before` productized for one operation
`staleness.rebuild(..., not_before=ts)` → `jobs.enqueue(..., not_before, wait_reason="scheduled")`; the resume
sweeps (`api.py:645`, `db.py:1817`) must skip `wait_reason='scheduled'`; missed-window policy from rulings §4
(run at next eligible start unless not-current / cancelled / deadline passed; record scheduled, actual, reason);
cancel-before-start; exact-once via existing dedupe. CLI: `neurosearch project rebuild-stale <pid> --tier
rebuild_matters --at 02:00`. Preflight from L-10 wraps the envelope. Host honesty: the CLI prints "runs when the
worker is next available", never "at 02:00". Gate (rulings §3 P1A): schedule from CLI, exit the shell, worker
runs it exactly once later with provenance; restart in between does not duplicate it.

### L-21 `[ ]` macOS power assertion, measured not assumed — needs: L-20
Investigate `caffeinate`-equivalent from the worker (IOPMAssertion via `caffeinate -w <pid>` or a subprocess)
while scheduled/active autonomous work exists. Test on the real MacBook: lid open + display off → runs? lid
closed → runs? Record both answers in the audit doc. Gate: the product's host-state message matches measured
reality; no claim about lid-closed unless proven.

---

## Stage 4 — P2 E7 Nightly Refinery backend (lane: claude, reassigned 2026-09-15 -- see Stage 1 header; tier: sonnet) — needs: L-20

### L-30 `[ ]` nightly envelope
`settings.t4_nightly_budget` (default 0 = off) + `settings.t4_nightly_hour`; a housekeeping entry (pattern:
`jobs._housekeeping_loop` / `_backfill_research`) that, per active project, runs preflight (L-10) then
`t4.execute(pid, budget_usd=..., dry_run=False, transport="batch")` inside one envelope id. Never reopens current
sources (t4 already skips them). Gate (rulings P2): one real night on Kyle's project at $2: no duplicate source
work, spend ≤ budget, provenance traceable, ledger matches.

### L-31 `[ ]` Project Delta v0 (data only) — needs: L-30
One function `delta.for_envelope(envelope_id) -> dict`: sources read, findings suggested, sources stopped by the
probe, coverage-state deltas from `t1.coverage_view`, new tensions, spend vs budget, revision at run. No UI, no
schema migration -- a computed view over existing tables, stored in `kv` per envelope. Gate: JSON for a real
envelope; every number reconciles to the tables it came from.

---

## Stage 5 — P1B "Tonight" UI (Claude lane, tier: sonnet) — needs: L-20 AND Codex's frontend split landed

### L-40 `[ ]` Now / Tonight / Overnight batch on the stale-rebuild action
Progressive disclosure; pending state visible; cancellable; the host-honesty copy from L-20; on return the
panel says what was scheduled, whether it ran, what happened, cost, attention needed. Gate (rulings §3 P1B).

---

## Stage 6 — P3 Morning Report v1 (Claude lane, tier: sonnet) — needs: L-31

### L-41 `[ ]` report v1, honest about P4 not existing (rulings §7)
Surface: what changed (coverage delta, new tensions) → what Neuro researched → stale/risky via existing
`staleness.triage` tiers marked provisional → spend → operational details collapsed. "Nothing important
changed" is a first-class outcome. NO "the 2 things you need to review". Gate (rulings P3): Kyle explains the
overnight change without opening Findings.

---

## Stage 7 — P4 Review at Scale (Claude lane + Codex signals, tier: sonnet) — needs: L-41

### L-50 `[x] bc998d4` Decision Impact v1 = two real signals (rulings §6) — pulled forward, non-colliding, unblocked
`impact.for_claim(claim_id) -> {disagreement: from research_tensions, plan_impact: claim cited by plan_items,
value: high|some|unknown}`. Unknown when neither is provable. No LLM score. Gate: deterministic tests.

### L-51 `[ ]` exception queue — needs: L-50
Findings/claims grouped by twin/cluster; queue = high Decision Impact ∪ disagreement ∪ evidence-weak, capped;
representative review with inspectability; never auto-approve on confidence. Gate (rulings P4): Kyle's
project with thousands of proposals yields a short defensible queue that still shows consequential disagreement.

### L-52 `[ ]` Morning Report v2: "What needs me?" — needs: L-51

---

## Stage 8 — P6 T5/T6 operationalization (tier: sonnet) — needs: L-50
### L-60 `[ ]` T5 triggers: high-impact contradiction / weak consensus on a decision / strong sources disagree /
plan-critical uncertainty → `t5.adjudicate` produces a PROPOSED resolution (never canonical). Budgeted per night.
### L-61 `[ ]` T6 surfacing only where it changes a decision: expired assumption, constant drifted, plan depends
on unmeasured assumption. No dashboard.

## Stage 9 — P7 Structured Delta experiment (Claude lane, T4 owner) — needs: L-07
### L-70 `[ ]` ~20 varied long-form sources; Arm A findings vs Arm B structured prototype; written measured
decision BEFORE any persistence. `kyle-decides` on the $ estimate (state it first).

## Stage 10 — P8 Continuous Research — needs: L-30, L-50 · not admitted; do not start without scheduler entry
## Stage 11 — P9 Beyond-corpus (capability intel, adaptive discovery + exploration quota, field map) — not admitted
## Stage 12 — P10 Living Master Plan (Known/Assumed/Chosen/Uncertain/Blocked/Monitored; explainable changes;
material-change thresholds; versions) — needs: L-52 · not admitted
## Stage 13 — P11 Neuro Everywhere (inbox, external AI access, multi-user with identity/ACL) — not admitted
## Parked — P12 Bidirectional Scheduler: only on measured starvation/latency/contention/cost/fairness.

---

## Standing evidence rules (apply to every item)
- A gate is a measurement, a written decision, or a passing test -- never "implemented".
- Frozen numbers (Tier-1 totals, prefilter/rerank gates, PROBE_DISCOUNT, estimator constants) change only with a
  `HARDENING.md` entry.
- Bulk approval is not quality evidence (rulings §5).
- Activity is not value: report findings kept / decisions affected / attention consumed, not counts.
