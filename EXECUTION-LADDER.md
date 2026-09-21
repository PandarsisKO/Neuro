# EXECUTION LADDER — Product Intelligence Mission

**Status ticks — 2026-09-21 (repo audit):** every `[x]`/`[k-done]`/`[parked]` marker dated 2026-09-21 below was set from
evidence recorded in `HANDOFF.md` on 2026-09-20/21, not from intent. Items Kyle parked on 2026-09-21 (L-21, L-40,
L-60, L-61, FM1-gate→FM3, the subreddit track) are marked `[parked]` and listed in `PRODUCT-SCHEDULER.md` PARKED.

**Current execution routing — 2026-09-19:** the active cross-feature mission and ordered ladder are
[docs/CONTINUOUS-EXECUTION-MISSION.md](docs/CONTINUOUS-EXECUTION-MISSION.md), starting at CE0. This file retains
the canonical Product Intelligence gate definitions and history; it is not a competing NOW queue. Its historical
agent-lane restrictions, known-failure allowance and Kyle-runs-terminal directions below do not override the
current mission/HANDOFF: the executing agent performs eligible supported operations, release failures must be
resolved, and only actual judgment/access/spend/physical dependencies need Kyle. Existing CR/LP/AD/FM/L statuses
are not closed by the new plan. Record evidence in their owning entries when CE9 actually satisfies a gate.

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
4. Validate before every commit: focused tests → the wider set the item names → `python -m pytest tests -q`
   (L-03 landed 2026-09-15, so no `.env` blanking is needed) → `repo-check`.
   Known-failure baseline is **0** since 2026-09-21 (2,367 passed, 0 failed; HANDOFF 09-21). Any failure is new.
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

### L-00 `[k]` (no disposition recorded; the 2026-09-20 real nightly rebuilt 107+1 stale sources, so the count is unknown — re-derive from Health before acting) Rebuild the 409 stale carrying-weight sources overnight, $0 — lane: kyle
Updated 2026-09-15: the scheduler (L-20) and its UI (L-40) now exist, so this is one click. Rulings §4 still
apply: never promise "2 AM". Tonight's honest path:
- Findings → review panel → "Accept 389 as still usable" (instant, free).
- On the "stale AND carrying weight" row: **When… → Rebuild tonight · $0** (eligible from the nightly hour; the
  card says so). The worker holds a keep-awake assertion while work is pending (L-21) -- lid OPEN, plugged in;
  a closed lid is the known limit L-21's test measures.
- Morning: the same card says what happened. (Old path still works: `caffeinate -i .venv/bin/neurosearch worker`
  + "Rebuild · $0" now.)
Gate: morning Findings panel shows the 409 current; `usage` shows $0 for them.

### L-01 `[k]` (cosmetic; never recorded as done) `.zshrc` dead `deno/env` line — lane: kyle · 5 seconds
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

### L-05 `[x] 829eab1` P5.3 kept-rate sample design — lane: claude · tier: sonnet · needs: — · $0
Haiku default is SHIPPED-PROVISIONAL (rulings §5). Design the smallest review that can contradict it: from the fixed 8
E5 sources (4 Sonnet / 4 Haiku, ids in docs/T4-ADMISSION-2026-09-14.md), an exactly-40-finding sample
(5 per source, importance-stratified), blind to model, exported by a `tools/sample_findings.py` Kyle runs on the
Mac to `evals/p53-sample-<date>.json`. Review rubric: accurate to source (y/n), worth keeping (y/n), one-line
why-not. Gate: script + rubric committed; Kyle can complete it in ≤ 20 minutes.

### L-06 `[x] 2026-09-20 — Kyle judged 40/40 on `evals/p53-sample-2026-09-20.json` (HANDOFF "L-06/L-07 answered")` P5.3 Kyle reviews the sample — lane: kyle · ~20 min · needs: L-05
Real judgments, not batch. Writes answers into the JSON the script produced.

### L-07 `[x] 2026-09-20 — Haiku confirmed as findings default: 100 %/100 % kept, $0.0006 vs $0.0014 per kept finding (HANDOFF "L-06/L-07 answered")` P5.3 decision — lane: claude · tier: sonnet · needs: L-06 · $0 — prepped 19dc1a7: `tools/decide_kept_rate.py --sample evals/p53-sample-<date>.json` is the whole computation
Compute kept-rate per model, cost per KEPT finding (cost data already in the admission doc). Rule (T4 plan E5):
Haiku stays only if cost-per-kept is lower AND kept-rate within 10 points of Sonnet. Otherwise revert the `.env`
line and say so. Gate: written decision in the admission doc + HANDOFF; `.env` matches the decision.

### L-08 `[x] 2026-09-20 — run on the Mac; Spearman 0.999/1.0, no case to switch the ranking basis (HANDOFF "Item 4 closed")` P5.1 brief-text relevance backtest — lane: claude · tier: sonnet · needs: — · ~$0.03 (embeddings)
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

### L-21 `[parked] 2026-09-21 — Kyle: sleep/wake tests don't matter now; code+tests done at 7b5e5cc` macOS power
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

### L-30 `[x] 2026-09-20 — real night run by Kyle at 15:02 (`--budget 2 --research-refresh-budget 1`), HANDOFF "Real nightly run closes L-30/L-31/L-41 and CR7"` nightly envelope
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

### L-31 `[x] 2026-09-20 — passed on the same real night as L-30` Project Delta v0 (data only) — needs: L-30
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

### L-40 `[parked] 2026-09-21 — code+tests done at ed87c06 (0.63.91); Kyle's one-use observation parked with the other sleep/wake gates` Now / Tonight / Overnight batch on the stale-rebuild action
Progressive disclosure; pending state visible; cancellable; the host-honesty copy from L-20; on return the
panel says what was scheduled, whether it ran, what happened, cost, attention needed. Gate (rulings §3 P1B).
Shipped: each triage tier keeps one primary ("Rebuild · price" = now) plus a "When…" disclosure (now on the API /
tonight / overnight as a batch / in the background). The card shows what is scheduled (sources · eligible from
HH:MM tonight · how · cost) with Run now instead / Cancel, and on return "Since you were away: N re-read · failed ·
missed the window · $ · needs a look". Copy is host-honest and internals-free (pinned by test). Server owns
"tonight" (`staleness.next_tonight`, host clock, nightly hour); `GET .../scheduled`, `POST .../scheduled/cancel`,
`POST /jobs/{id}/run-now`; a scheduled job is its own visible state ("scheduled", was falling through to "retry
wait" -- a real L-20 gap). 6 tests; frontend gates 43/43; full suite 1572; repo-check PASS; release-check PASS at
0.63.91. Gate: Kyle schedules one real rebuild for tonight, leaves the Mac as he normally would, and reads the card
in the morning -- is the outcome clear without opening the jobs console? (`docs/KYLE-GATES-2026-09-15.md`)

---

## Stage 6 — P3 Morning Report v1 (Claude lane, tier: sonnet) — needs: L-31

### L-41 `[k] code+tests done at 16169e3; the 2026-09-20 night produced a real report — gate is Kyle reading it once (`neurosearch nightly report`) and saying whether it explained the night` report v1, honest about P4 not existing (rulings §7)
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

### L-51 `[x] 2026-09-20 — passed on real data, Kyle's verdict recorded (HANDOFF "L-51 closed on real data"); web surface built 09-21 as the Research tab (`19d672a`)` exception queue — needs: L-50 **2026-09-16 real run**: executed against the real "buying businesses" project (982 sources) via a same-day
backup snapshot (never the live DB directly -- CLAUDE.md rule #1): `25 to review out of 15589 proposed
(disagreement 6, plan impact 0, weak evidence 25; hidden by the cap: 14949)`. Real result, not a fixture --
awaiting Kyle's answer to the gate's 3 questions (short enough? does each line say why? is the disagreement he
already knows about represented?).
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

### L-52 `[x] 2026-09-20 — flag turned on after L-51 passed; the review-queue UI it was waiting for landed 09-21 (`19d672a`)` Morning Report v2: "What needs me?" — needs: L-51
`settings.morning_report_needs_me` (`NEUROSEARCH_MORNING_REPORT_NEEDS_ME`, default off) fills each project's
"Needs you" from `review_queue.build(pid, limit=5)`, each item with its reason; never the banned phrasing (tested).
Off = v1 byte-identical. Flip to 1 ONLY after L-51's gate passes on Kyle's real project (rulings §7).

---

## Stage 8 — P6 T5/T6 operationalization (tier: sonnet) — needs: L-50
### L-60 `[parked] 2026-09-21 — code+tests done at fee162c; the `--t5-budget` night is parked with the other overnight observations` T5 triggers: high-impact contradiction / weak consensus on a decision / strong sources disagree /
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
### L-61 `[parked] 2026-09-21 — code+tests done at a541e5a; parked with L-60` T6 surfacing only where it changes a decision: expired assumption, constant drifted, plan depends
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
### L-70 `[ ]` (UNBLOCKED 2026-09-20: L-07 closed; needs Kyle's $ yes on `tools/p7_estimate.py`) ~20 varied long-form sources; Arm A findings vs Arm B structured prototype; written measured
decision BEFORE any persistence. `kyle-decides` on the $ estimate (state it first) -- prepped d9468c0: `tools/p7_estimate.py --project <name>` states it ($0, Arm B labelled as an assumption).

## Stages 10–15 — the acceleration plan (mission §12, 2026-09-15). Dependencies are REAL, not feature-family order.

Admission classes: **ADMITTED NOW** · **READY AFTER GATE <x>** · **PARALLEL PREP** (may proceed, non-colliding) ·
**EXPERIMENT ONLY** · **PARKED**. Every rung is a vertical slice: existing state → tiny adapter → bounded
behavior → minimal surface → measurement → decision. No new table until a slice proves persistence is needed.

Dependency graph (arrows are real code dependencies; anything not connected may run in parallel):

    CR1 research needs ──┬──> CR2 due policy ──> CR5 one-Claim refresh ──> CR6 nightly ──> CR7 real gate
                         │                              ▲
    SC3 claim→reservoir ─┘ (feeds CR5's "where")        │
    CR3 reservoir rescan ──> CR4 change detection ──────┘
    LP0 seam (plan `_evidence` note ids) ──> LP1 affected steps ──> LP2 explainable impact ──> LP3 proposed patch ──> LP5 acceptance ──> LP6 demo
                                          (LP4 state semantics: derived, alongside LP2)
    AD0 feedback inventory ──> AD1 small batch ──> AD2 rerank (uses SC view) ──> AD3 exploration ──> AD4 measure
    FM0 $0 experiment ──> FM1 proposals ──> FM2 accept → existing object ──> FM3 route via pursue/where_to_look

Parallel-safe now: {CR1, LP0+LP1, FM0, AD0} touch disjoint files. CR1 and LP1 both READ decision_impact; neither
edits it beyond LP0's additive note-id seam. Do not run two agents on `report.py`/`delta.py` at once.

### Stage 10 — P8 Continuous Research (Claude lane: semantics; Codex lane: CR3/CR4 plumbing) — needs: L-30 code (exists), L-50
Audit (CR0, done 2026-09-15, recorded in HANDOFF): freshness policy EXISTS (`claims.FRESHNESS_RULES`,
`freshness_status`); stale-source logic EXISTS (`staleness`); targets + escalation EXIST (`knowledge.pursue`,
`last_escalation`); reservoirs EXIST (`collections`, `candidates` with first/last_seen, `where_to_look`);
scheduler + nightly EXIST. Missing: the selection step, rescan of a known reservoir, and the end-to-end refresh.

### CR1 `[x] 2cbc82f` research needs — DONE · lane: claude · needs: —
`research_needs.for_project(project_id) -> {needs:[...], counts}`: read-only projection over accepted Claims with
`freshness_status` in (stale, needs_refresh); open CONTRADICTION/NOVEL/WEAK_CONSENSUS tensions; open Evidence
Targets; plan-cited weak Claims (`decision_impact`). Each need: kind, ref id, question/proposition, why, consequence
(disagreement/plan_impact), freshness class + status, existing coverage (evidence count, newest age), last
escalation, and `where` = `candidates.where_to_look` adapted from the Claim's topic + evidence classes (this IS
SC3). Deterministic order: plan-impact+stale first, then disagreement, then open targets; no LLM score. Surfaces:
`GET /api/projects/{id}/research-needs`, `neurosearch project needs <project>`, one Morning-Report line ("N things
may need fresh evidence") only when non-empty. Gate: deterministic tests incl. "a static Claim never becomes a
need by age alone"; on Kyle's project the list reads as things worth checking (his judgment, recorded).

### CR2 `[x] c215849` due policy — DONE · lane: claude
When is a need DUE tonight: `freshness_status` (not raw age) × consequence (plan_impact/disagreement) × cost of the
check (`usage.estimate_source_findings` on the reservoir's next unread). Categories, not a fake score. Records
`kv research:checked:<need>` so nothing is rechecked because budget remains. Gate: tests for each freshness class.

### CR3 `[x] 638dd22` known-reservoir rescan — DONE · lane: claude
YouTube channel/playlist via `media.enumerate_entries`: "has this reservoir produced new candidate material
since the last scan?" New items flow into the existing Candidate Index via `candidates.remember` — no second
ingestion pipeline, nothing auto-ingested, never a sources row (MONITOR only, PRODUCT-INTELLIGENCE-MISSION.md
§13). `neurosearch/reservoir.py`. CLI-only: `neurosearch project rescan <project> [--collection <id>]`. Gate:
`tests/test_s55_reservoir_rescan.py` (13 tests) — rescan of a fixture channel adds only new candidates; a second
rescan adds none; a candidate already in the Library gets its source_id resolved; a dismissed candidate stays
dismissed across rescans.

### CR4 `[x] 638dd22` change detection before analysis — DONE · lane: claude
Merged into CR3's `rescan()` rather than a separate pass: a project-scoped fingerprint
(`reservoir:scan:<project_id>:<collection_id>`, order-insensitive, built from external id/title/duration) is
checked BEFORE any candidate diff work. Project-scoped, not merely per-collection, so the no-op gate means "same
remote revision AND this project is already reconciled to it" — a global, collection-only key would let a
second project attaching to an already-scanned, unchanged reservoir silently miss candidates the first project
already found (the cross-project starvation bug this correction exists to prevent). Gate (same test file):
unchanged reservoir costs $0 and enqueues nothing (zero `jobs`/`invocations` rows, `enumerate` called exactly
once); a second project sharing an unchanged reservoir with a first still reconciles fully into its own index,
no duplicates, no disposition leak.

### CR5 `[x] d72537b` one important Claim refreshed end-to-end — DONE · lane: claude
Due Claim → `where` → bounded research through existing paths (`knowledge.pursue` steps 1–3 free; the captured
source through the ordinary ingest+findings jobs) → `claims.assess` recomputes strength/freshness → delta reports
strengthened / weakened / contradicted / unchanged for that Claim → no status change → Morning Report line only if
consequential. Gate: fixture scenario A and C from mission §12 pass; no `set_status` call anywhere on the path.

### CR6 `[x] 690d3f2` nightly integration — DONE · lane: claude/codex interface first
A third bounded work source in `nightly.run()` under its own explicit cap (like T5's); "nothing changed" is a
successful outcome recorded on the envelope. Gate: envelope test; no need refreshed twice in a night.

### CR7 `[x] 2026-09-20 — passed on Kyle's real nightly run (56 refreshes requested; HANDOFF "Real nightly run closes … CR7")` real-project gate — needs: CR6. **Kyle action**: let the nightly worker run once, unattended, on a real project (same path L-00 already uses for the stale-source rebuild). Next morning, check the Morning Report / Findings panel for CR6's envelope line ("N Claim(s) refreshed" or an honest "nothing changed" — both count as a pass) and tell Claude what it showed. Never faked, never simulated with a fixture -- this gate is specifically "did it happen for real." **2026-09-16 readiness-pass correction**: `nightly run` requires its own separate `--research-refresh-budget` flag or CR6/CR7 never runs at all (`neurosearch nightly run --budget 2 --research-refresh-budget 1`), and the plain-text Morning Report stays silent about CR6 either way this run had it off or it had nothing due -- check `nightly report --json`'s `research_refresh` key instead: `null` means the flag was never passed, a dict means it ran. Full copy-paste steps in `docs/KYLE-GATES-2026-09-15.md` under "CR7".

### CR8a `[x] 4f14113` monitoring-classification storage — DONE (Kyle's product decision, 2026-09-16)
The missing piece between NEW CANDIDATE (a Candidate Index row CR3/CR4 can now produce) -> JUSTIFIED RESEARCH
NEED -> EXISTING ACQUISITION PATH. Not built tonight; not queued as ready work. This entry exists so the seam is
named and its shape is known, per PRODUCT-INTELLIGENCE-MISSION.md §13: "the seam between 'a candidate exists' and
'a candidate should be acquired' is CR8 -- documented, not built."

**The seam, concretely, in terms of what already exists:** a deterministic adapter -- no new model call, no new
provider call -- that would sit between a candidate CR3/CR4 just remembered and the acquisition paths
`candidates.py` already owns: `research_needs.for_project` (what does this project still need to close a gap),
`candidates.where_to_look` (per creator: does this creator have BOTH a yield history in this project AND
something left unread -- $0, no network, answers from what the project has already measured), `_best_fit` (which
of several possible sources best closes a specific need), and `candidates.link` (idempotent: record that a
known-but-not-yet-acquired candidate may serve a need -- relevance/why refresh on repeat, a dismissed link stays
dismissed, a link on an already-acquired candidate is born satisfied). The adapter's job would be narrow: when a
rescan's new candidates land, ask whether any of them are `where_to_look`-eligible for an unmet need this project
already has, and if so call `candidates.link` -- never `candidates.remember` (already done by CR3) and never
anything that creates a `sources` row or spends money. Gating: CR2's due policy (a need must actually be due, not
merely open) and CR6's nightly budget (this would be bounded work inside the same envelope CR6 already caps, not
a new unbounded pass).

**Why this stays documented-only tonight, not built:** the real blocking question is product, not technical --
*where does a reservoir's "primary for this project" monitoring classification get stored* (PRODUCT-
INTELLIGENCE-MISSION.md §13's open question). CR3/CR4 sidestepped it by making every `project_collections`-
attached reservoir eligible for an explicit, on-demand rescan regardless of tier. CR8 cannot sidestep it the same
way: linking a candidate to a research need on the strength of `where_to_look`'s creator-yield signal is exactly
the kind of "should Neuro pay attention to this automatically" decision that the MONITOR/ACQUIRE tier split exists
to gate, and building the adapter before that storage question is answered would quietly force an answer (every
attached reservoir treated as if it were primary) rather than let Kyle make the call. Building this without that
decision would also skip past ACQUIRE's own rule (PRODUCT-INTELLIGENCE-MISSION.md §13): acquisition stays a
separate, explicit decision, never a consequence of monitoring alone -- `candidates.link` recording a possible fit
is still short of acquiring anything, but it is one step closer to blurring that line than CR3/CR4's plain
`remember` was, so it deserves its own explicit go-ahead rather than riding in on CR3/CR4's approval.

**Resolved (2026-09-16).** Kyle's call: "primary for this project" lives on the project<->collection
RELATIONSHIP (`project_collections.source_role`/`monitor_policy`), never a universal flag on `collections` --
the same reservoir is primary for one project's question and merely secondary for another's. Built:
`db.get_collection_policy`/`set_collection_policy` (two additive columns, conservative unspecified/auto
defaults, pure bookkeeping -- never touches candidates/sources/jobs), `reservoir.effective_monitor_active`
(on/off always win; auto defaults active only for `primary`), `reservoir.rescan_project()` now skips any
attached-but-unmonitored collection with zero `enumerate()` calls, and `neurosearch project collection-policy`
(CLI) to show/set it. The single, explicit `reservoir.rescan(pid, cid)` path (`--collection`) stays ungated by
design -- an explicit, one-collection ask is a deliberate action, same override principle as user-explicit watch
in §13. Gate: `tests/test_s57_monitor_policy.py` (15 tests) -- the full truth table, per-project (not
per-collection) scoping with zero cross-project leakage, policy changes never ingesting anything, pre-existing
rows migrating to conservative defaults. Release-gate PASS at `6144a11` (`4f14113`).

**Follow-up (2026-09-16, `0df11d4`).** Kyle confirmed the design as shipped and asked for one explicit
regression: the explicit single-collection rescan is a one-time "check this now", never a "start watching this
forever" -- running it against a `secondary`/inactive collection must check it once, reconcile normally, and
leave `source_role`/`monitor_policy` completely untouched, with a later `rescan_project()` still skipping it.
Proven in `tests/test_s57_monitor_policy.py::test_explicit_single_collection_rescan_is_a_one_time_check_not_a_policy_change`
(the exact 10-step scenario). `reservoir.rescan()` never wrote to `project_collections` to begin with, so this
was already true by construction -- the test adds the missing direct proof. Release-gate PASS at `94b3699`
(`0df11d4`).

### CR8b `[x]` selective-acquisition adapter — DONE (`afa2acf`, `477f9e5`)
CR8a resolved the one blocking question; Kyle then commissioned the CR8b mission itself (plan-once/pause-once).
Execution-ready plan written into HANDOFF.md after a fresh pre-read of `candidates.py`, `knowledge.py`,
`research_refresh.py` (CR5) and `nightly.py` (CR6) -- NOT built yet, no code changed this pass.

**What the plan found, in short**: CR5's `research_refresh.request_refresh()` + `knowledge.pursue()`/
`capture_best()` already implement almost this exact pattern for Claim-linked needs, and explicitly REFUSE an
`open_target` need with no `claim_id` (`test_request_refresh_refuses_an_open_target_need_with_no_claim`) -- that
refusal is precisely Kyle's v1 case. The plan adds a sibling `research_refresh.request_acquisition()` for
`open_target` needs, reusing `pursue`/`candidates.links_for`/`candidates.capture()` (the canonical seam) with its
own eligibility gate (closes two real gaps inspection found: `links_for` never checks `candidate_projects.state`,
so a dismissed candidate's still-open link could otherwise be re-captured; neither `pursue` nor `capture_best`
budget-gates before spending), a re-check immediately before acquisition, bounded to one acquisition per target
per pass, gated by a new off-by-default nightly budget (`cr8b_acquisition_nightly_budget`, same pattern as
T4/T5/CR6's separate pools) plus an on-demand `project acquire-evaluate` CLI command for the explicit "check this
source now" case. One small, proven-necessary provenance addition: `candidates.capture()`'s job payload gains
`candidate_id`/`reason` (both already in scope as the function's own parameters; `capture_best()` already proves
the pattern safe) -- no new table, no schema migration. Full plan, exact function-by-function design, and the
original 15-item test matrix are in HANDOFF.md's "Planning checkpoint — CR8b" entry.

**Shipped, with Kyle's 9 corrections over that plan** (`afa2acf`): no new dollar budget -- a plain
`cr8b_enabled` feature flag instead, reusing `capture_best()`'s existing `usage.guard()`/`usage.check()` for its
one spend-bearing branch (correction #1). CR5's `request_refresh()` and the new
`research_refresh.request_acquisition()` both go through the SAME `knowledge.capture_best()` -- no second
selection/acquisition implementation (correction #2). `capture_best()` itself is where the fixes landed: it
re-reads live `candidate_projects.state` per candidate before acting (skips `user_dismissed`/`acquired`/
`duplicate` -- closes the dismissed-candidate leak both CR5 and CR8b would otherwise inherit), decouples its
candidate consideration pool (fixed at 10) from the acquisition cap `n`, attaches an already-ready Library source
UNCONDITIONALLY (a depleted budget must never block a $0 reuse -- correction #3), budget-gates only the
enqueue-a-real-ingest branch via `usage.guard()`, and returns a new `skipped` list with reasons. The dismissed
check lives at this shared boundary, deliberately NOT inside `candidates.capture()`, which stays the explicit
single-candidate "capture this anyway" override a user can still reach to reverse their own dismissal (correction
#4). `request_acquisition()` re-checks the target's own `status == "open"` immediately before acting --
`capture_best()` only checks candidate-level state, not target-level (correction #5) -- and still caps at one
acquisition per target per pass (correction #6). `nightly.py`'s CR8b block is thin: gated by
`settings.cr8b_enabled` (boolean, not a budget pool), per-project due `open_target` needs, same
try/except-log-and-continue shape CR6 uses (correction #7). `neurosearch project acquire-evaluate <project>
[--target ID] [--json]` is the on-demand CLI equivalent. `tests/test_s58_selective_acquisition.py` (23 tests)
covers the original matrix plus correction #9's six A-F assertions (library reuse ignores exhausted budget,
spend-bearing acquisition refused under budget with no partial acquisition, CR5+CR8b share `capture_best`,
autonomous CR8b never captures a dismissed candidate, the manual override path stays unaffected). A second commit
(`477f9e5`) fixed a real but unrelated pre-existing landmine the new nightly tests exposed: `cli.py`'s `nightly
run` command mutates `settings.research_refresh_nightly_budget` directly (not via monkeypatch), so an earlier
test exercising that CLI command left it nonzero for the rest of the process, causing CR6's block to silently
consume the same `due_tonight()` TTL-dedup key CR8b's own block needed -- fixed by pinning that setting to 0 in
`s58_db`'s own fixture, not in `cli.py` (out of this rung's scope). Full suite 1828/0 failed (2+ consecutive clean
`-n4 --dist=loadscope` runs), `repo-check` PASS, `release-check --no-pytest` PASS at `477f9e5` (0.63.91). Full
trail in HANDOFF.md's "Execution — CR8b shipped with Kyle's 9 corrections" entry.

**Hardening (`0289f17`, `dcabfbc`).** The `cli.py` global-state landmine the CR8b test fixture worked around at
`477f9e5` is now fixed at its source: `config.py` gained a scoped `override(**changes)` context manager (the
smallest reusable mechanism, not a second configuration system), and `nightly_run_cmd` now wraps its
budget-dependent body in it instead of assigning straight to the shared `settings` singleton. 10 new tests in
`tests/test_s59_cli_settings_lifecycle.py` prove the mechanism (visible during the block, restored on normal
exit/exception, multiple keys, rejects an unknown attribute), the CLI command actually using it (a spy proves
`nightly.run()` sees the override while executing), two sequential invocations not leaking into each other, an
exception mid-command still restoring settings, the exact original CR8b symptom reproduced end-to-end and proven
gone, and that existing CLI disclosure/confirmation/refusal behavior is unchanged. Full suite 1838/0 failed (2+
consecutive clean runs), `repo-check` PASS, `release-check --no-pytest` PASS at `0289f17` (0.63.91).

### CR8b-gate `[k]` real-world validation before widening — needs: CR8b (done), a real project with a real open
Evidence Target. **2026-09-16: precondition confirmed for real** (via a same-day backup snapshot, read-only
inspection): the "buying businesses" project has 496 open Evidence Targets with no Claim yet (origin=model);
the "web app design" project has 230. Genuine candidates exist -- e.g. "What fraction of small business
acquisitions in the $500K-$1M range actually include seller financing" (topic: seller financing market data).
Running `project acquire-evaluate` itself WRITES (queues a real ingest job for the live worker to pick up) and
cannot safely run from this session's bridge-mounted access to the live DB (CLAUDE.md rule #1) -- this is the
one remaining step and needs either Kyle running the one-line command himself, or this session getting
permitted browser access to the running app's own UI/API. **Kyle action**: let CR8b run against a real project — either wait for its own nightly pass
(`cr8b_enabled` must be on) or run `neurosearch project acquire-evaluate <project> [--target ID]` yourself — then
report back what happened so Claude can answer, against the actual result (not a fixture):
- **A.** Did an actual project have an open Evidence Target?
- **B.** Did CR8b identify a candidate you'd agree was genuinely justified for that target?
- **C.** Did it acquire no more than the intended bound (one per target per pass)?
- **D.** Was the provenance (why THIS source, for THIS target) understandable from what's shown?
- **E.** Did it avoid pulling in anything unrelated?
- **F.** Did the resulting source actually help the target / project?
- **G.** Was cost behavior correct (free reuse attached regardless of budget state; spend, if any, matched what
  was authorized; nothing acquired past budget)?
- **H.** Did the Morning Report / Project Delta surface the result appropriately (not silently, not oversold)?

This is deliberately an observation gate, not a build — do not manufacture a synthetic verdict from fixture data
in place of it, and do not expand CR8b's scope while this remains open. If G surfaces a real gap (e.g. cost
isn't disclosed anywhere the user would see it before it happens), record that as its own small, separately
admitted follow-up rather than folding it into this gate or into CR8c.

### CR8c `[ ]` admission rule (not implementation) — needs: CR8b-gate evidence. CR8b intentionally stays narrow:
OPEN EVIDENCE TARGET → deterministic candidate match → at most one justified acquisition → existing pipeline. Do
NOT widen automatic acquisition to stale Claims broadly, contradictions broadly, tensions broadly, plan
dependencies broadly, Source Capability recommendations, arbitrary semantic relevance, or exploration candidates
until CR8b-gate has real evidence. Once it does, the evidence — specifically where CR8b's narrow Evidence Target
model felt insufficient in practice, not a preference stated in the abstract — decides which single next trigger
earns expansion (candidates include: a stale consequential Claim, an unresolved high-impact tension, a
plan-critical unknown, or another explicit Research Need type). Do not preselect the winner now; this entry
records the admission RULE, not an implementation, and CR8c does not start until CR8b-gate closes.

### Stage 11 — P10 Living Master Plan (Claude lane) — needs: L-50 only (NOT P8)
Audit (LP0-audit, done 2026-09-15): plan JSON carries `evidence:[F<n>]` on first_steps/decisions/tools/costs;
`plan_items` keys mirror those paths; `plan["_evidence"]` (emap) stores label/link/kind/source_id per id but NOT
the note id, so `decision_impact` re-derives F<n>→note by re-numbering and must say "unknown" whenever notes
changed since the plan; `plan_updates` already holds previous/proposed/reason/status — the patch substrate exists.

### LP0 `[x] 2cbc82f` plan-evidence seam — DONE · lane: claude · needs: —
`planner._evidence` records `note_id` (and fact id) in the stored emap for every F/U entry; `decision_impact`
prefers the stored ids and falls back to re-derivation for older plans. Additive, no migration (plan JSON). Gate:
plan_impact stays known after notes change for a plan built after this seam; older plans unchanged.

### LP1 `[x] 2cbc82f` affected-step detector — DONE · lane: claude · needs: LP0 (same commit)
`plan_impact.affected_items(project_id, claim_id|tension_id) -> [{key, section, text, via: [note ids], strength:
possible|indicated}]` — deterministic over evidence links; `indicated` only when the link is a direct citation,
`possible` when via a merged/superseded Claim; unknown stays unknown. Surface: one Plan-tab line "1 step may need
revision" (progressive disclosure) + `GET .../plan/impact?claim_id=`. Gate: deterministic tests; the demo claim in
`test_decision_impact` maps to exactly its cited step.

### LP2 `[x] c215849` explainable impact — DONE · lane: claude
Given a delta (changed Claim/tension), produce affected Claim → decision/dependency → step → why → possible vs
indicated, by templating over LP1 (no model call). Feeds `delta.for_envelope` "what decision or plan element
could be affected". Gate: scenario A text reads correctly from fixtures.

### LP3 `[x] d72537b` proposed plan patch — DONE · lane: claude
Write a `plan_updates` row (pending) per affected step: move/insert prerequisite/flag blocked/mark dependency
unresolved/revisit decision, with reason + claim linkage. Never mutates the accepted plan. Gate: row shape; the
existing accept/reject route promotes it; nothing else does.

### LP4 `[x] 690d3f2` stable state semantics — DONE · lane: claude
Known/Assumed/Chosen/Uncertain/Blocked/Monitored as DERIVED state over plan_items + linked Claim strength/
freshness + assumptions; persist nothing unless the derivation proves insufficient. Gate: derivation tests.

### LP5 `[x] 0c14c01` patch acceptance provenance — DONE · lane: codex-shaped
Five columns added to `plan_updates` (`claim_id`, `tension_id`, `decided_at`, `decided_by`, `applied_plan_id`)
via the existing additive MIGRATIONS mechanism, verified genuinely missing by inspection before adding any
(Kyle's overnight-mission correction 6). `plan_narrative.propose_updates()` now persists the claim_id `explain()`
already resolves (direct or via tension_id) instead of discarding it; `db.set_update_status()` stamps
`decided_at`/`decided_by` at decision time; `planner.apply_accepted_updates()` stamps `applied_plan_id` on every
accepted row once the regenerated plan exists (rejected rows never get one). Gate:
`tests/test_s56_plan_patch_provenance.py` (8 tests) — "your plan changed in one place" reconstructs from a
single row alone (previous/proposed/reason/claim linkage/origin/decided_by/decided_at/applied_plan_id), rejected
rows stay `applied_plan_id: null` even after a later apply, older NULL-column rows still render, and the existing
`POST /api/plan-updates/{id}` route round-trips full provenance. `planner.build_plan` faked directly (not via
`monkeypatch.undo`) — $0, no provider/model call.

### LP6 `[k]` (2026-09-21: the 09-20 nightly requested 56 refreshes; nobody has re-checked `plan_updates` since — Claude Code, one query on the Mac) real evidence-change demo — needs: LP3. **2026-09-16 checked, no trigger yet**: `plan_updates` table is empty in the same-day backup snapshot across
all 3 real projects -- no plan-impacting Claim change has happened yet. Correctly left waiting for its real
trigger, per the mission's explicit instruction not to manufacture one. **Kyle action**: the next time CR5/CR6's nightly refresh actually changes a Claim's status on a real project (strengthened / weakened / contradicted -- CR7 is where this is first observed), tell Claude the Claim id. Claude verifies the resulting `plan_updates` row alone reconstructs "your plan changed in one place" (previous state, resulting state, reason, claim linkage, system vs user provenance) with no other lookup needed.

### Stage 12 — P9A Source Capability — mostly SHIPPED at 0.58.3 (`candidates.creator_yield` = SC0 view;
`where_to_look` = SC1 routing; `_creator_term` in `_potential` = SC2, capped so yield never dominates).
### SC0b `[x] 29952b0` capability view completeness — DONE · lane: claude · needs: —
Add to `creator_yield`: claim types/topics yielded, targets previously helped close (`candidate_links` state
satisfied), cadence (published_at spread). Read-only; project-scoped; never a single score. Gate: tests.
### SC3 `[x] 2cbc82f` — folded into CR1 (`where` per need) — DONE. CR1's own entry says it explicitly: "`where` = `candidates.where_to_look` adapted from the Claim's topic + evidence classes (this IS SC3)". Stale `[ ]` marker corrected 2026-09-16 -- no code changed, CR1 already satisfied this when it shipped.

### Stage 13 — P9B Adaptive Discovery (Claude lane) — needs: SC view (exists)
### AD0 `[x] 866edc8` feedback inventory — DONE · lane: claude · $0 · needs: —
Written matrix of durable signals that already exist: `candidates.mark` states (dismissed/acquired/skipped_*),
`candidate_links.state`, findings status, `claims.set_status`, target closure. Decide which feed AD2. No telemetry.
See `docs/AD0-FEEDBACK-INVENTORY.md`: AD2 reranks off candidate disposition (primary) + link outcome (secondary);
findings/claim status and target closure are reserved for AD4's retrospective measurement, not the rerank loop.
### AD1 `[x] 77e26bf` small-batch discovery — DONE · lane: claude
"5 best next" from `candidates.pool` (kind="candidates" only), capture/reject through the existing durable
`candidate_projects.state` vocabulary, "5 more" by calling again — no new shown/seen/cursor/session state; a
resolved item already drops out on its own (`project_pool_revision` already tracks `mark()`), an undecided one
is correctly shown again. `candidates.capture()` extracted as the one shared CAPTURE path (was duplicated
inline in two API handlers). CLI (`project discover` / `discover-decide`) + `GET .../discover/next`. No new
frontend — the ladder names no UI gate for AD1; the existing Sources-tab pool table is untouched.
### AD2 `[x] 528209c` deterministic rerank — DONE · lane: claude
Target fit / preferred class / SC view / freshness are `_potential()`'s existing terms, reused as-is (not
rebuilt). AD2's own additions, scoped to `next_batch`'s `rank_by="fit"` path only: `creator_disposition` (a
bounded RATE over decided `acquired`/`user_dismissed`/`skipped_low_relevance` outcomes -- never a raw count,
never `skipped_limit`/`skipped_cost`/`duplicate`), `_stale_linked_targets` (AD0's secondary link-outcome
signal -- demotes a candidate whose linked target closed through a different candidate), and a bounded-lookahead
diversity cap that defers, never drops. `rank_by` values other than `fit` are untouched. Gate: tests.
### AD3 `[x] b303562` exploration slot targets the unknown, not the badly ranked — DONE · lane: claude
Kyle's own 12-section product-decision spec resolved what "outside the pattern" means: EXPLORE reuses AD2's own
learned/neutral distinction (creator_disposition adjust==0, not negative) rather than any new classifier or
randomness. `apply_exploration` gates on both a non-neutral learned signal existing in the lookahead AND a
qualifying neutral candidate clearing the existing WORTH_A_LOOK ("worth a look") floor; at most one
`exploratory:true` slot per batch, deterministic, scoped to `next_batch`'s `rank_by=="fit"` path only -- every
other sort mode untouched. Displaced top-N items are never dropped, only deferred. `rerank` now also preserves
`base_potential` (pre-adjustment score) for AD4. Gate: tests.
### AD4A `[x] 364c1b9` adaptive-discovery outcome measurement — DONE · lane: claude
Kyle's own AD4 decision split "static vs adaptive measurement" into two gates once the plan surfaced a real
methodological problem: AD1/AD2/AD3 persist no record of what any batch showed or omitted (no `base_potential`,
no `exploratory`, no served rank, no batch membership), so a retrospective static-ranking counterfactual cannot
be honestly reconstructed -- the user never evaluated candidates a batch never surfaced. `discovery_measure.report`
answers the answerable half instead: how Adaptive Discovery has actually performed, from existing durable state
only (candidate decisions with an honest denominator, downstream finding/Claim/target yield traced through valid
provenance, review burden, project-scoped novel creators), with an evidence-sufficiency guard (no_usage /
thin_sample / usable_sample) that keeps the verdict descriptive and refuses confidence on a thin sample. No
schema, no persisted batch telemetry, no reversal of AD3's "exploratory is not persisted" decision. Gate: tests.
### AD4B `[k]` (2026-09-21: two blind rounds done — 77 % → 55 % kept vs a 25 % bar; cutoff moved 50→45 on the band table; Kyle 2026-09-21: "load up one more blind for me" — round 3 is Claude Code's to generate after the post-brief re-score) true static vs adaptive comparison — needs: real usage. **2026-09-16: usable_sample reached for real on both active projects** (via a same-day backup snapshot,
read-only): "buying businesses" project — 10,100 genuine decisions, 8% capture rate, 92.5% rejection rate;
"web app design" project — 3,650 genuine decisions, 10% capture rate, 89.9% rejection rate. Real estate project
still `no_usage`. Awaiting Kyle's judgment on the two usable_sample verdicts: do these numbers leave genuine
ambiguity about Adaptive Discovery's value, or is he satisfied without a static-comparison build? **Kyle action**: keep using Adaptive Discovery normally (capture/reject through `project discover` or the UI) for a while, then run `neurosearch project discover-report <project>` yourself, or ask Claude to run it, once the report says `usable_sample` rather than `thin_sample`/`no_usage`. Only if THAT report's numbers leave the adaptive system's value genuinely ambiguous is AD4B worth building -- the smallest prospective design for the exact unresolved question (controlled interleaving, occasional static control batches, or similar), chosen then, never built speculatively now, never a general analytics/event platform.

### Stage 14 — P9C Field Map — EXPERIMENT ONLY until FM0 decides
### FM0 `[x] 0da834b` $0 experiment — DONE · lane: claude · needs: existing `scholar`/`resources` tooling · gate `scholar_wanted`
Reference-list clusters vs headings of 2–3 review works, compared with the project's Claims/targets/sources
vocabulary. Written go/no-go. No paid pass unless the $0 method fails AND the paid one has clear decision value.
See `docs/FM0-EXPERIMENT.md`: GO on reference-list clustering (additive to scholar.py, no new capability); NO-GO
on heading clustering (needs a new extraction primitive, real acquisition cost). Live evidence on a real project
is Kyle-gated (sandbox has no route to Crossref/OpenAlex) -- FM1 stays gated on this decision, not built here.
### FM1 `[x] 87ba57b` reference-list clustering prototype — DONE · lane: claude · needs: `scholar`/`works`/`claims` tooling
`neurosearch project field-map <project> [--fetch-seeds Q] [--json]`: local-first seed discovery (project Works with
a DOI identity -> project sources via the Works manifestation relationship -> Candidate Index -> explicit
`--fetch-seeds` only as a last resort, deduplicated by DOI across all four with provenance recorded), up to 3
Crossref singleton reference fetches (`scholar.fetch_crossref_references`, a new FM1-only fetch path that does NOT
touch `CROSSREF_FIELDS` or ordinary Scholar discovery), deterministic greedy token-overlap clustering of the
collapsed bibliography into field areas with `reference_count`/`referenced_work_count`/`seed_count` kept distinct,
deterministic labels (never a model-generated category name), and coverage classified against the project's OWN
extracted evidence (`claims.project_vocab` + Claim text + open Evidence Target questions) -- never a claim about
the whole Library. Six completeness counters plus an `insufficient_reference_metadata` state when reference data is
too thin to support a conclusion (a missing/empty Crossref `reference` array is a limitation, never evidence of
absence). Read-only: writes nothing to candidates/sources/claims/targets/the Planner. `tests/test_s60_field_map.py`
(25 tests, all fixture-fed, no network). Full suite 1863 passed (2 consecutive clean runs); repo-check PASS;
release-check PASS at `87ba57b`.
**Follow-up hardening (`f13ca97`).** (1) DOI-less canonical identity now folds normalized-title + first-author
+ YEAR WHEN PRESENT into the key (was title+author alone): a missing year never forces a merge with a dated entry
(kept as a duplicate representation, not a false merge, per Kyle's "false merge is worse than duplicate
representation" principle); two undated entries with the same title+author still merge (no information says
otherwise). No fuzzy resolution, no model call. (2) The CLI's human-readable `project field-map` output now
surfaces everything needed to judge a real run WITHOUT `--json`: per-seed fetch detail, all six completeness
counters spelled out, an explicit `sufficient_for_underrepresented_conclusion` line, and each field area's full
metrics plus `representative_references` (title, DOI when it has one, mention count). 25 -> 32 tests. Full suite
1870 passed (2 consecutive clean runs); repo-check PASS; release-check PASS at `f13ca97`.
### FM1-gate `[parked] 2026-09-21 — network is no longer the blocker (Crossref/OpenAlex 200 since 09-19); no project has a DOI-bearing Work to seed it; parked until one exists` real-world validation — needs: a real project with a genuine review/scholarly seed AND live **2026-09-16 real attempt**: ran against all 3 of Kyle's real projects (via a same-day backup snapshot, read-
only). None has a naturally DOI-bearing seed work (expected -- his projects are video/podcast/practitioner
content, not academic literature). Tried `--fetch-seeds` to search Crossref explicitly: blocked at the DNS
level from this session's execution environment (`fetch blocked (dns) at hop 0 for api.crossref.org` --
captured exactly, not worked around, per the mission's explicit instruction not to route around network
policy). FM1-gate stays open on two independent grounds: no natural seed exists yet in real project data, and
this session cannot reach Crossref to search for one. If Kyle runs `neurosearch project field-map <project>
--fetch-seeds "<query>"` from his own Mac Terminal (outside any sandbox/bridge), Crossref may well resolve
fine there -- worth trying once from that context before concluding this is a standing policy block.
Crossref access, neither available from this sandbox (fresh `curl` check against `api.crossref.org` /
`api.openalex.org` from the connected device's shell still returns 403 from the org's own egress proxy, matching
FM0's original finding). **Kyle action**: on a machine with live Crossref access, run
`neurosearch project field-map <a real project with 1+ scholarly/review sources>` (plain text output already has
everything below; add `--json` only if you want the raw structure) and judge:
(A) did it surface at least one field area that was not obvious from Neuro's existing project structure;
(B) were the representative references inspectable enough to understand why that area appeared;
(C) did the output distinguish repeated mentions (`reference_count`) from distinct works (`referenced_work_count`)
and distinct seed bibliographies (`seed_count`);
(D) were areas already well represented in the project's own evidence correctly recognized as covered (`coverage`);
(E) did thin/incomplete bibliography metadata degrade to `insufficient_reference_metadata`/`unknown` rather than
manufacture an `underrepresented` claim -- check the "sufficient reference metadata..." line before trusting any
`underrepresented` result;
(F) was at least one `underrepresented` result genuinely useful enough that Kyle would want Neuro to investigate it.
Record the verdict here, especially (F): if F is NO, record why and FM2 stays stopped; if F is YES, FM2 may be
considered for admission, but is never implemented automatically from that alone. Do not expand clustering
sophistication or add a second data source (OpenAlex, headings) speculatively before this evidence exists.
### FM2 `[parked] 2026-09-21` accepted proposal → existing object (Evidence Target or MISSING_PERSPECTIVE tension) — READY AFTER FM1-gate.
### FM3 `[parked] 2026-09-21` routing through `knowledge.pursue` / `where_to_look` — READY AFTER FM2.

### Stage 9 (unchanged) — P7 Structured Delta: EXPERIMENT ONLY (L-70), needs L-07 + Kyle's $ yes. Must not block
Stages 10–14 unless a real dependency is found.

### Stage 15 — Opportunistic $0 unlocks (never displacing the loop)
### H1 `[ ]` semantic finding dedupe — PARKED: `project_notes.embedding`/`project_claims.embedding` columns exist
but NO writer populates them (verified 2026-09-15), so this still needs paid embeddings → measured cost/quality
gate first. ### H2 `[ ]` chapter/segment digests — PARKED pending a check that `work_units.result` per-window
`summary` fields are populated and readable without a new pass (per-source summaries exist in
`project_source_analysis`). ### H3 speaker structure — PARKED.

### P11 — Neuro Everywhere: FUTURE / NICE TO HAVE / no active rungs (mission §12). `EXTERNAL-AI-ACCESS-MISSION.md`
preserved. ### P12 — Bidirectional Scheduler: trigger-only; do not resurrect without measured contention.

---

## Standing evidence rules (apply to every item)
- A gate is a measurement, a written decision, or a passing test -- never "implemented".
- Frozen numbers (Tier-1 totals, prefilter/rerank gates, PROBE_DISCOUNT, estimator constants) change only with a
  `HARDENING.md` entry.
- Bulk approval is not quality evidence (rulings §5).
- Activity is not value: report findings kept / decisions affected / attention consumed, not counts.
