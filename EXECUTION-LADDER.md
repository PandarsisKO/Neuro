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

### L-13 `[x] b0b406b` P0.C restart/retry — needs: L-11
Audit finding: this exact claim was already proven in two separate halves before this rung started --
`test_s46_r4_durable_units.py::test_completed_windows_survive_parent_crash_and_retry_runs_only_missing` (windows/
work_units durability + "retry pays only for missing windows", but with `_call` mocked -- never touches the real
`usage` table) and `test_indestructible.py::test_crash_matrix_findings[findings_persisted_before_done]` (real
`usage` table not double-recorded across a real job-level crash+restart via `crashkit.Sim`, but only for a
whole-source crash AFTER every window already completed). Neither combines real usage recording + a real
job-level restart + a genuine partial (some windows done, one not) crash, so a narrow gap in test coverage
remained. New test `tests/test_p0_restart_retry.py` closes it: forces windows sequential
(`concurrency.limit_for` patched to 1 -- otherwise both fake-AI calls complete before either thread reaches the
crash point, since findings.extract normally fans multi-window sources across a small thread pool), crashes at
`findings_window_persisted` after window 0, restarts via `crashkit.Sim` (the real lease-recovery path), and
asserts exactly 1 `usage` row + 1 `work_unit` after the crash, exactly 2 of each after the clean retry -- never
double-recorded, never dropped. No production bug found (unlike L-12) -- this closed a coverage gap, not a
defect. Full suite: 1495 passed; `repo-check: PASS`.

### L-14 `[x] 9c85f40` P0.D budget exhaustion — needs: L-11
Real bug found (not just an audit): `suggest_for_project()`'s BudgetPaused/ProviderUnavailable handling created
a SEPARATE fresh `suggest_findings` job for the remaining sources, then re-raised so `jobs.execute()` ALSO
requeued the original job (full source list, correctly `wait_reason='budget'` + `not_before` gated). The fresh
job had no wait fields at all (`not_before=None`) -- immediately claimable, racing straight past the very
budget/provider wait that caused the pause, and leaving two jobs covering the same remaining source(s). Fixed
by folding `BudgetPaused`/`ProviderUnavailable` into the same re-raise branch as `Yield` (L-12) -- `jobs.execute()`
already handles all three uniformly and correctly; any source completed before the pause skips on resume via the
existing `is_current`/`input_hash` check. New test (`tests/test_p0_budget_exhaustion.py`): two sources, second
hits `BudgetPaused` mid-project, asserts exactly one job remains, gated behind the budget wait, full source list
preserved, nothing half-written for the paused source, completed source's analysis stays current. Full suite:
1496 passed; `repo-check: PASS`.

### L-15 `[x] 22292fe` P0.E promotion boundary — needs: —
Two proofs, no violation found (this rung closes the gate, it doesn't fix a bug). Static: every `.py` under
`neurosearch/` grepped for a `claims.set_status(`/`set_status(` call site -- only `claims.py` (the definition),
`api.py` (direct route) and `claims_view.py` (`bulk_status`, called only from `require_auth`-gated POST routes)
match. Dynamic: the real harvest/assess/map pipeline (`claims.ensure()`, reusing `test_k6_claims.py`'s proven
multi-claim G5 acceptance fixture) run end-to-end under fake AI -- every resulting Claim's status is
`proposed` or `superseded` (the one legitimate autonomous transition: dedup/merge of a still-proposed duplicate,
gated `AND status='proposed'` in `claims.py` so it can never touch an already-accepted Claim), never `accepted`
or `rejected`. Full suite: 1498 passed; `repo-check: PASS`.

### L-16 `[x] aef8d4a` P0.F concurrent completion — needs: L-11
Real bug found (not just an audit) -- and found BECAUSE this rung drove the layer the existing
`tests/test_claims_harvest_race.py` doesn't (real job completions via `db.create_job` -> `db.claim_job` ->
`jobs.execute()`, 4 threads racing 8 jobs for one project, so `_after_done()`'s inline `claims.harvest(pid)`
fires concurrently, not a direct `harvest()` call). `harvest()`'s per-project lock used to coalesce: a caller
that found the lock held would wait for release and return a no-op, trusting "the in-flight call already scans
every currently approved/suggested note." That assumption breaks under real concurrency -- the in-flight call's
note scan is a snapshot from when IT acquired the lock, so a note the WAITER's own job wrote afterward but before
the waiter's own `harvest()` call was silently never scanned by anyone. ~1 run in 10 lost a note permanently
(silent: `_after_done()` swallows harvest's exceptions and nothing else retries). Fixed by removing the
coalesce -- every caller now does its own real scan once it holds the lock. New test
(`tests/test_p0_concurrent_completion.py`) reproduced the bug on its first run pre-fix; 30 consecutive green runs
post-fix (gate asked for 20). Full suite: 1499 passed; `repo-check: PASS`.

### L-17 `[x] 5a2573d` P0 closeout — needs: L-10…L-16
`docs/P0-AUDIT-2026-09-15.md`: scenario table for all 7 rungs (L-10..L-16). 4 real defects found and fixed
(L-10, L-12, L-14, L-16 -- see each rung's own entry above for commit shas), 3 scenarios where the system
already behaved correctly and the gap was in test coverage rather than behavior (L-11, L-13, L-15), 0 documented
limitations, 0 open-ended rewrites. **P0 (Stage 1) is now fully closed.**

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

### L-04 `[x] 477113c` P5.2b measure the prefilter — lane: kyle runs, claude decides · tier: sonnet · needs: L-02 · $0
On the Mac: `.venv/bin/neurosearch eval --prefilter --out evals/prefilter-<date>.json`. Claude reads the artifact
(it is a file, not the DB). Decision rule (T4 plan E6, unchanged): enable `NEUROSEARCH_FINDINGS_PREFILTER=1`
only if net savings > 0 AND relevant-window recall ≥ 0.98. Record the decision in `HARDENING.md` (frozen-number
rule). Gate: committed artifact + written decision, either way.

### L-05 `[x] aa53a9c` P5.3 kept-rate sample design — lane: claude · tier: sonnet · needs: — · $0
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

### L-20 `[x] f183ab5` `not_before` productized for one operation
Built exactly as scoped: `db.create_job(..., not_before=ts)` (sets the column, tags `wait_reason='scheduled'`,
preserves the request in `payload["_scheduled_for"]` since claiming nulls the column itself) →
`jobs.enqueue(..., not_before=ts)` → `staleness.rebuild(..., not_before=ts)` threading it into every job it
creates. `jobs.execute()` records missed-window provenance (`scheduled_run_started` job_event:
scheduled/actual/delay/reason) for every scheduled job, and cancels-not-runs one whose `payload["_deadline"]`
already passed. Real bug found: `api.py`'s budget/pause resume sweep (`POST /api/usage/budget`) unconditionally
cleared `not_before` for every queued job -- raising the budget or clicking Resume would wake a "run at 2am"
schedule immediately; fixed to skip `wait_reason='scheduled'` (the `db.py:1817` sweep, `release_budget_waits()`,
was already correctly scoped -- no change needed there, only `api.py`'s). CLI:
`neurosearch project rebuild-stale <project> --tier <tier> --at HH:MM`, host-honest by construction ("runs when
the worker is next available, no earlier than..."). Gate verified: two `staleness.rebuild()` calls for the same
still-in-flight source produce no duplicate job (`assess()` itself excludes sources with a live job, on top of
`create_job`'s existing dedupe); not_before gates claiming and survives a restart (manually verified beyond the
5-test suite). Full suite: 1504 passed; `repo-check: PASS`.

### L-21 `[~] claude 2026-09-15 -- code+tests done at 7b5e5cc, blocked on Kyle's physical test` macOS power
assertion, measured not assumed — needs: L-20
`neurosearch/power_assertion.py` built and tested: holds `caffeinate -s` for exactly as long as active/near-future
scheduled work exists, wired into `jobs.start_workers()`/`stop_workers()`, reported by `doctor`, honestly
unavailable off macOS. 6 tests prove the software plumbing (queue-state-driven start/stop, no double-spawn,
24h lookahead, honest unavailability) -- deliberately NOT a claim about lid-closed reliability, which is not
provable in software (documented Apple/developer behavior: a caffeinate assertion does not survive a closed lid
without an external display -- stated in the module's own docstring, not tested this session because it can't
be from here). The one thing genuinely still needed: Kyle running the two-minute test in
`docs/L21-POWER-ASSERTION.md` (lid open + display off vs. lid closed, ~10 min each) and recording both answers
here. Gate remains open until that measurement lands -- this is not a code-complete gate, it is explicitly a
measured-reality gate.

---

## Stage 4 — P2 E7 Nightly Refinery backend (lane: claude, reassigned 2026-09-15 -- see Stage 1 header; tier: sonnet) — needs: L-20

### L-30 `[~] claude 2026-09-15 -- code+tests done at 6f48da3, blocked on Kyle's real night` nightly envelope
`neurosearch/nightly.py` built and tested: `settings.t4_nightly_budget` (default 0 = off) + `settings.t4_nightly_hour`
gate `due()`; `run()` calls `db.preflight_autonomous()` first (L-10, refuses and records rather than proceeding on
a dirty DB), then per active project (most-recently-active first) `t4.execute(pid, budget_usd=remaining, dry_run=False,
transport="batch")`, walking `remaining` down by each project's own `total_estimate` so the budget is a SHARED TOTAL
across the night, never re-applied per project. One project's exception is caught/logged without aborting the rest
of the night. Idempotent per calendar date via `kv`. Wired into `jobs._housekeeping_loop`; `doctor()` reports today's
envelope status. 6 tests (off-by-default, due()'s three gates, single-project no-duplicate-work + same-day no-op,
budget-walk-down across projects, preflight-refusal-stops-the-night, one-project-failure-doesn't-abort-the-rest).
Full suite 1516 passed, `repo-check: PASS`. The gate itself (rulings P2) is explicitly a measured-reality gate like
L-21's: "one real night on Kyle's project at $2: no duplicate source work, spend ≤ budget, provenance traceable,
ledger matches" needs Kyle's real database, Kyle's spend authorization, and an actual overnight run -- none of
which this sandbox can produce or fake (never touches `data/neurosearch.db`, never manufactures paid evidence).
To run it: `neurosearch nightly run --budget 2` (prints the authorized amount and asks first; commit 4c6867e added
the CLI), leave the worker running, then `neurosearch nightly report` the next morning -- see
`docs/KYLE-GATES-2026-09-15.md`. Gate remains open until Kyle runs it and confirms the ledger reconciles -- code-complete, not gate-complete.

### L-31 `[~] claude 2026-09-15 -- code+tests done at 175e856, blocked on a real L-30 night` Project Delta v0 (data only) — needs: L-30
`neurosearch/delta.py` built and tested: `for_envelope(envelope_id) -> dict` reads the envelope's own kv record
(today, only `nightly.run()`'s `"nightly-{date}"` shape) and, per touched project, counts sources read, findings
suggested, sources stopped by the substance probe, revision-at-run per touched source, new tensions, and spend --
every one filtered to the envelope's real time window `[preflight ts, now]` and counted live from the tables that
actually recorded it (`project_notes`, `project_source_analysis.prefilter`, `research_tensions`, `usage`,
`sources.revision`) -- plus a real coverage-state delta from `t1.coverage_view`, made possible by a small
additive change to `nightly.py`: it now captures a per-project "before" `coverage_view` snapshot immediately
before calling `t4.execute` (the only moment a real "before" exists to observe) and stores it in the envelope
record. A failed project reports its error and a `needs_user` entry rather than raising; the rest of the
envelope's projects still get a normal delta. 9 tests, each checking a reported number against the real table
row(s) it claims to summarize, in-window vs. out-of-window rows both exercised. Full suite 1525 passed,
`repo-check: PASS`. Manually verified end to end against a real (fake-AI) run + real batch-job completion +
`for_envelope()` call, producing the exact JSON the gate asks for with every number reconciling.
The gate itself ("JSON for a real envelope; every number reconciles to the tables it came from") means a REAL
envelope -- i.e. depends on L-30's own gate (an actual overnight run on Kyle's project) having happened first;
nothing here can honestly satisfy "for a real envelope" before one exists. Once a real `nightly-{date}` envelope has run, `neurosearch nightly report --json` for that date IS this gate's
JSON -- no further code is needed (see `docs/KYLE-GATES-2026-09-15.md`).

---

## Stage 5 — P1B "Tonight" UI (Claude lane, tier: sonnet) — needs: L-20 (done) AND Codex's frontend split (landed 2026-09-13 at `7480352`; `neurosearch/web/js/*` + `styles.css`)

### L-40 `[ ]` Now / Tonight / Overnight batch on the stale-rebuild action
Progressive disclosure; pending state visible; cancellable; the host-honesty copy from L-20; on return the
panel says what was scheduled, whether it ran, what happened, cost, attention needed. Gate (rulings §3 P1B).

---

## Stage 6 — P3 Morning Report v1 (Claude lane, tier: sonnet) — needs: L-31

### L-41 `[~] claude 2026-09-15 -- code+tests done at 16169e3, blocked on Kyle reading a real one` report v1, honest about P4 not existing (rulings §7)
`neurosearch/report.py` built and tested: `for_envelope(envelope_id) -> dict` assembles `delta.for_envelope()`'s
data with `staleness.triage()`'s tiers (marked explicitly provisional); `render_text(report) -> str` renders the
mission doc's own primary hierarchy (what changed, max emphasis → why it matters → what needs me → what Neuro
handled, secondary → operational details, collapsed). "Nothing important changed" is a first-class short path,
never a fallback. Neither the rendered text nor the raw dict can ever contain any form of "the N things you need
to review" -- checked directly by test, not just by inspection -- since that claim needs Stage 7's Decision
Impact ranking (not yet built) to be defensible. A real bug was caught before it reached tests: `staleness.triage()`'s
tiers are per-tier SUMMARY dicts (each already carrying its own `"count"`), not bare row lists -- an early draft's
`len(tiers[k])` silently reported the dict's key count (11) as every tier's source count; caught by manually
rendering a report against a project with zero actual stale sources and seeing "11 rebuild matters", fixed, and
pinned with a regression test. 7 tests. Full suite 1532 passed, `repo-check: PASS`.
Gate (rulings P3): "Kyle explains the overnight change without opening Findings" -- a real human-comprehension
measurement, same shape as L-21/L-30/L-31's gates: needs Kyle to actually read a real rendered report from a
real night: `neurosearch nightly report` the morning after L-30's run (CLI added at 4c6867e; see
`docs/KYLE-GATES-2026-09-15.md`). Code-complete, not gate-complete.

---

## Stage 7 — P4 Review at Scale (Claude lane + Codex signals, tier: sonnet) — needs: L-41

### L-50 `[x] bc998d4` Decision Impact v1 = two real signals (rulings §6) — pulled forward, non-colliding, unblocked
`impact.for_claim(claim_id) -> {disagreement: from research_tensions, plan_impact: claim cited by plan_items,
value: high|some|unknown}`. Unknown when neither is provable. No LLM score. Gate: deterministic tests.

### L-51 `[~] claude 2026-09-15 -- code+tests done at 3ea00da, gate needs Kyle's real project` exception queue — needs: L-50
`neurosearch/review_queue.py`: `build(project_id, limit=25)`. Review unit = the proposed Claim (harvest already
folds twin findings into one Claim and merges duplicate Claims via `superseded_by`), so each item is one
representative proposition with inspectable members (findings folded in, Claims merged in). Inclusion =
disagreement ∪ plan_impact (both L-50's real signals) ∪ evidence_weak; novelty/irreversibility/provenance/
freshness NOT used and named as absent in `basis`. Cap applies only to plan_impact/evidence_weak -- disagreement
is never dropped, `counts.not_shown` reports exactly what was hidden by reason. Structurally cannot approve
(no writes, no `set_status`; pinned by an AST test). Surfaces: `GET /api/projects/{id}/claims/review-queue`,
`neurosearch project review-queue <project> [--limit N] [--json]`. 9 tests; the gate is tested literally with
2,000 proposed Claims (60 disagreeing, limit 25 → all 60 shown, 0 weak, hidden counted). Full suite 1548,
`repo-check: PASS`. Gate needs Kyle's real project: `neurosearch project review-queue <project>` -- is the list
short, does every line justify itself, and is the disagreement you know about in it? (`docs/KYLE-GATES-2026-09-15.md`)

### L-52 `[ ]` Morning Report v2: "What needs me?" — needs: L-51

---

## Stage 8 — P6 T5/T6 operationalization (tier: sonnet) — needs: L-50
### L-60 `[~] claude 2026-09-15 -- code+tests done at fee162c, gate needs a real night with --t5-budget` T5 triggers: high-impact contradiction / weak consensus on a decision / strong sources disagree /
plan-critical uncertainty → `t5.adjudicate` produces a PROPOSED resolution (never canonical). Budgeted per night.
`t5.escalation_candidates(decision_aware=True)` adds `weak_consensus_on_decision` and `plan_critical_uncertainty`
(any-impact WEAK_CONSENSUS / CONTRADICTION-NOVEL on a Claim the current plan cites -- L-50's real `plan_impact`,
unknown never escalates). `t5.run_nightly()`: high impact first, each call estimated from its real prompt, stops
at the cap, never adjudicates a tension twice across nights (kv `t5:adjudicated:*`), verdicts only ever land as
SUGGESTED findings. `settings.t5_nightly_budget` (`NEUROSEARCH_T5_NIGHTLY_BUDGET_USD`, default 0) is a SEPARATE
cap from the findings budget; `nightly.run()` runs it after the findings walk; delta + Morning Report surface it.
CLI: `neurosearch nightly run --budget 2 --t5-budget 1`. 8 tests + 1 CLI test; all 18 pre-existing T5 tests
unchanged. Full suite 1557, `repo-check: PASS`. Gate (P6: "appears because it changes what the user should know
or do"): one real night with `--t5-budget` on Kyle's project, then read the adjudication verdicts in the Morning
Report / Findings review and judge whether they were worth their line (`docs/KYLE-GATES-2026-09-15.md`).
### L-61 `[~] claude 2026-09-15 -- code+tests done at a541e5a, gate = Kyle judges the line on a real night` T6 surfacing only where it changes a decision: expired assumption, constant drifted, plan depends
on unmeasured assumption. No dashboard.
`neurosearch/t6.py` (read-only): reads which mechanisms the night's envelope record PROVES fired and intersects
with the ledger's new `exercised_by` tags. Surfaces only: unresolvable constants (code moved -- always, first),
never-measured thresholds/weights that shaped tonight's output, and measured ones >60 days old that fired
(a re-check, not a verdict). Operational defaults never surface unless broken. Ledger gained `measured_on` +
`exercised_by` and the four numbers the night itself leans on (`DEFAULT_SUBSTANCE_FLOOR` -- now a real t4
constant, honestly unmeasured for recall -- `PROBE_DISCOUNT`, `LOCAL_MINUTES_PER_WINDOW`, `SCHEDULED_LOOKAHEAD`).
Rendered LAST in the Morning Report, collapsed, only when non-empty; a quiet night says nothing. 9 tests, the
negatives pinned as hard as the positives. Not built and not pretended: automatic re-measurement. Full suite
1566 (-rf), `repo-check: PASS`. Gate (P6): on a real night's report, was the line worth reading -- did it change
what you'd check? Nothing extra to run: it appears at the bottom of `neurosearch nightly report` when earned.

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
