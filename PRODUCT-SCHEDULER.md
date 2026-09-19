# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-16 (NOW section reconciled against EXECUTION-LADDER.md's live per-item state; the rest of this file is an append-only history and reflects the date each entry was written). This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

**SUBREDDIT CORRECTION — 2026-09-19 (supersedes older active-effort orientation below).** Kyle requested
the ladder to finish the partial subreddit implementation already on `main`. Codex is the executor; Claude
is no longer executing this mission. Follow [the canonical mission, Section 5](docs/SUBREDDIT-CATALOG-MISSION.md#5-corrective-execution-ladder--current-authority),
SUB-R0–SUB-R9. All corrective rungs are open; next is R0's isolated baseline/test-harness repair, not another
feature-complete declaration. This admission records priority and the plan; the ladder-writing turn makes
documentation changes only. CHR2 is closed at its verified visual checkpoint (`7b43dc8`). Other unfinished
missions remain at their actual recorded checkpoints and are not closed or restarted by this admission.
The older NOW entries below remain history, not competing assignments.

**SPEED — observation mode (Kyle, 2026-09-17).** P0 closed · R4/R5 shipped (0.63.40/41) · R8 satisfied with two
documented triggers (mmap, retention 2026-10-11) · `/api/sources` cache churn closed · R9(c) deferred · twin-project
unit reuse kept as shipped with the compute-not-state guardrail gated. Process separation reopens only on the
real-use trigger in `docs/SPEED-AUDIT-2026-09-17.md` §11. Do not tune the P0 boundaries without a new measurement.
The one active effort is product work again, in the order below. Still owed from Kyle when convenient: two visible
windows; the first live `harvest_claims` completion with the queue running.
The Send Screenshot matrix below stays the other open effort; it was not touched.

**CURRENT-STATE RECONCILIATION — 2026-09-17 (read this first, supersedes the FM1 RECONCILIATION note directly
below it for orientation purposes — FM1's own DONE status is unchanged, just no longer the freshest note here).**
See `STATE-OF-THE-APP-2026-09-17-1130.md` for the full current snapshot. In short: `main` is `d1b6a67` and
matches `origin/main` on GitHub (pushed and current — the "Nothing pushed to GitHub" line further down this
file is dated history from 09-16, not current). The one active effort right now is the Send Screenshot
live-Chrome acceptance matrix: cases 1-3 are PASS (see `docs/KYLE-GATES-2026-09-15.md`), cases 4-7 are open,
and a deferred silent-401/403 UX fix is scoped and waiting behind them. After that: the Course Scanner
popup/background live-wiring gate (algorithm itself already closed at CS5), then presenting Kyle the judgments
that are already evidence-ready (L-51, AD4B, CR8b-gate, CR7) with no further engineering needed.

The `## SUSPENDED — RESUME FIRST` section below (D2/F1) is **stale and superseded** — `386891b` ("D2/F1 Resume
Delta — design ladder already fully closed, nothing to resume") already closed it on 2026-09-16; the section's
own text was just never updated to say so. Do not resume it; do not treat it as live.

**FM1 RECONCILIATION — 2026-09-16 (later same day, read this first, supersedes the CONTROL-PLANE
RECONCILIATION note directly below it).** FM1 (reference-list clustering) shipped at `87ba57b`: it is **DONE**,
not "the one genuinely agent-ready, not-yet-started Claude-lane rung" as the note below still says. `neurosearch
project field-map <project>` is real, tested (25 tests), full-suite-clean, repo-check/release-check PASS. Only
**FM1-gate** remains -- Kyle-gated real-world validation on a machine with live Crossref access (this sandbox's
egress proxy still returns 403 for `api.crossref.org`/`api.openalex.org`, same as FM0 found). FM2/FM3 stay
unbuilt until FM1-gate has real evidence -- do not start them speculatively. See EXECUTION-LADDER.md's FM1/FM1-gate
entries for the exact required Kyle action.

**CONTROL-PLANE RECONCILIATION — 2026-09-16, current reality (read this first).** EXECUTION-LADDER.md is the
live per-item source of truth; this note exists because the rest of this NOW section (and the whole NEXT
section below) accumulated stale claims that could misdirect a fresh agent. As of this commit:

- **CR1-CR8b are ALL DONE** (CR1/CR2/CR3/CR4/CR5/CR6/CR8a/CR8b all `[x]` in EXECUTION-LADDER.md). CR3 is NOT
  "Codex-shaped" or open -- it shipped alongside CR4 on 2026-09-15/16. CR8b is NOT un-admitted -- it shipped with
  Kyle's 9 corrections and was then hardened (config.override fix for cli.py's nightly-settings mutation). Only
  **CR7** remains, and it is Kyle-gated (a real-project nightly run + report-back, not more code).
- **LP0-LP5 are ALL DONE.** LP5 is NOT "codex-shaped, READY AFTER LP3" or open -- it shipped 2026-09-16. Only
  **LP6** remains, Kyle-gated (report a real Claim-status-change id).
- **SC0b/AD0-AD4A are ALL DONE.** Only **AD4B** remains, Kyle-gated (real usage first, then a `discover-report`
  read).
- **FM0 is DONE. FM1 is now also DONE** (see the FM1 RECONCILIATION note above this one -- this line predates
  FM1 shipping and is kept as history, not current guidance). Only **FM1-gate** remains, Kyle-gated (live
  Crossref/OpenAlex access this sandbox does not have).
- The "Next eligible in the Claude lane: nothing is READY..." paragraph and the "## NEXT — admitted priorities"
  section below are both **superseded** by the above -- they predate CR3/CR4/CR8a/CR8b/LP5 shipping and describe
  an earlier state. Left in place as history per this file's append-only convention, not deleted; do not act on
  their "nothing ready" / "CR3 (Codex-shaped)" / "LP5 (codex-shaped)" claims. See EXECUTION-LADDER.md directly
  for anything not covered here.

**Updated 2026-09-16 15:35 (overnight mission — Phase A + Phase B + CR3/CR4 + CR8-docs all closed; assessing
LP5).** Phase A: full suite 1766/0 clean across 11 consecutive `-n 4` runs (was flaky ~1-in-3..6 under a wrong
diagnosis — the real cause was a pooled anyio worker thread outliving a test's `settings.data_dir` swap, fixed
in `db.connect()`; see HANDOFF.md), repo-check PASS, release-check PASS at `3ab63eb` (0.63.91). Phase B
(`8d60313`): Monitor ≠ Acquire ≠ Retain written into PRODUCT-INTELLIGENCE-MISSION §13, per-collection "primary
for this project" classification storage left explicitly open. CR3+CR4 (`638dd22`, one module —
`neurosearch/reservoir.py`): known-reservoir rescan + metadata-first change detection, project-scoped scan-state
key (`reservoir:scan:<project_id>:<collection_id>`, not per-collection alone — required to avoid a real
cross-project candidate-starvation bug, proven with a dedicated regression test), 13-test gate
(`test_s55_reservoir_rescan.py`), zero provider/model calls verified directly against job/invocation counts,
CLI-only surface (`project rescan`), never scheduled. Release-gate PASS at `ea73bee`. CR8 (`aed34b9`): seam
documented in EXECUTION-LADDER.md — NOT built, NOT admitted — pending the same open classification-storage
decision Phase B flagged. See HANDOFF.md's Phase B/CR3/CR4/CR8 entry for full detail.

**LP5 (`0c14c01`) also closed** — re-verified by inspection that all five columns
(`claim_id`/`tension_id`/`decided_at`/`decided_by`/`applied_plan_id`) were genuinely missing before adding them,
wired `plan_narrative.propose_updates`/`db.set_update_status`/`planner.apply_accepted_updates`, 8-test gate
(`test_s56_plan_patch_provenance.py`). Release-gate PASS at `7c356ad` (`0c14c01`, 0.63.91).

**Overnight mission closed, then CR8a resolved on Kyle's own follow-up.** Kyle resolved CR8's open product
question directly: "primary for this project" monitoring classification lives on `project_collections`
(`source_role`/`monitor_policy`), per-relationship not per-collection. Built and gated (`4f14113`,
`tests/test_s57_monitor_policy.py`, 15 tests) — `reservoir.rescan_project()` now respects it (skips
attached-but-unmonitored collections, zero enumerate calls), new `project collection-policy` CLI command. The
explicit single-collection rescan path stays ungated by design (see HANDOFF.md for that judgment call). CR8b
(the acquisition adapter this was blocking) remains explicitly un-admitted per Kyle's own instruction not to
jump straight to it. Release-gate PASS at `6144a11` (`4f14113`, 0.63.91, unchanged all night).

Final: full suite 1804/0 failed across 3+ consecutive `-n 4` runs, repo-check PASS. No paid call all night.
Live/manual gates (send-screenshot Chrome matrix, course-scanner live extension, CR7, LP6, AD4B, FM1 live) not
touched — each still needs the specific Kyle action EXECUTION-LADDER.md names. Nothing pushed to GitHub; sandbox
has no route there.

**CR8b shipped (2026-09-16, executing model), with Kyle's 9 corrections over the plan-then-pause checkpoint.**
No new dollar budget — a plain `cr8b_enabled` feature flag, reusing `capture_best()`'s existing `usage.guard()`
for its one spend-bearing branch. CR5's `request_refresh()` and the new `research_refresh.request_acquisition()`
now both go through the SAME `knowledge.capture_best()` — the fixes (dismissed-candidate protection, $0-vs-spend
sequencing, a bounded candidate pool decoupled from the acquisition cap) landed there, not in a second
implementation. Thin `nightly.py` wiring gated by the boolean flag, plus an on-demand `project acquire-evaluate`
CLI command. `tests/test_s58_selective_acquisition.py` (23 tests) covers the original matrix plus 6 additional
assertions Kyle required. Full trail, including a real pre-existing `cli.py` global-state landmine found and
isolated against (not fixed at its source — out of scope), in HANDOFF.md's "Execution — CR8b shipped with
Kyle's 9 corrections" entry and EXECUTION-LADDER.md's CR8b entry. Full suite 1828/0 failed, repo-check PASS,
release-check PASS at `477f9e5` (0.63.91). No paid provider call made.

**Hardening + control-plane reconciliation (2026-09-16).** The `cli.py` global-settings-mutation landmine CR8b's
own test fixture worked around is now fixed at its source: `config.override()` (scoped context manager) +
`nightly_run_cmd` using it, 10 new tests, release-check PASS at `0289f17`. This NOW section and the NEXT section
below were reconciled against current EXECUTION-LADDER.md state (see the note at the very top of NOW).
`CR8b-gate` (Kyle-gated real-world validation, 8 questions) and `CR8c` (the admission RULE for widening CR8b,
not an implementation) are recorded in EXECUTION-LADDER.md, right after CR8b's entry — no CR8c code exists.

Updated 2026-09-15 (CR6 + LP4 landed, `690d3f2`). Every rung in the CR/LP chain (CR1→CR6, LP0→LP4) is
code-complete. Per the "ONE PLAN PAUSE, THEN CONTINUOUS EXECUTION" handoff rule, the plan/pause checkpoint that
authorized CR6/LP4 also covers continuing straight into the remaining PARALLEL PREP rungs in the same mission §12
dependency chain, no new pause required. Active now, in the Claude lane:

**SC0b, AD0, FM0 all landed** (`29952b0`, `866edc8`, `0da834b`) — every PARALLEL PREP rung in
Stages 12–14 that was eligible with no further Kyle input is now code-complete or decided. SC0b extended
`creator_yield` (claim types/topics, targets helped close, cadence). AD0 decided AD2 reranks off candidate
disposition + link outcome, reserving findings/claim status and target closure for AD4. FM0 decided FM1 should
prototype reference-list clustering, not heading clustering, and flagged that the real go/no-go evidence run
needs Kyle's machine (no catalogue network route from this sandbox).

**AD1 + AD2 landed** (`77e26bf`, `528209c`): small-batch discovery over the existing pool, then a
deterministic rerank on top -- disposition rate (not raw count), stale link-outcome correction, and a
bounded-lookahead diversity cap that defers rather than drops. No new UI, no schema, no model call in either.

**AD3 landed** (`b303562`): a single, quality-floor-gated, deterministic exploration slot on the fit-ranked
batch, per Kyle's own 12-section product-decision spec. Reuses AD2's learned/neutral disposition split and the
existing WORTH_A_LOOK floor rather than any new classifier, randomness, or persistent state; every other sort
mode is untouched; displaced items are deferred, never dropped; `base_potential` is preserved for AD4.

**AD4A landed** (`364c1b9`): Kyle's AD4 plan review found a real methodological gap -- AD1/AD2/AD3 persist no
record of what any batch showed or omitted, so a retrospective static-ranking counterfactual can't be honestly
built from current state. AD4 split into AD4A (build the $0 measurement capability now, from existing durable
state, descriptive only) and AD4B (the actual static-vs-adaptive verdict, deferred to real usage). AD4A's report
(`discovery_measure.report`) covers candidate decisions with an honest denominator, downstream finding/Claim/
target yield through valid provenance, review burden, and an evidence-sufficiency guard that refuses a confident
read on a thin sample.

**[SUPERSEDED — 2026-09-16, see the reconciliation note at the top of NOW. CR3 and LP5 shipped; they were not
left as "Codex-shaped" parallel prep. Kept verbatim below only as a historical record of what was open at the
time this paragraph was written.]**

Next eligible in the Claude lane (as of 2026-09-15, now historical): nothing is READY with no further Kyle input
right now. Three small, concrete things are waiting on Kyle -- exact wording and gate in EXECUTION-LADDER.md:
- **CR7**: let the nightly worker run once on a real project, then say what the next morning's report showed.
- **LP6**: next time a real Claim's status actually changes overnight, hand Claude the Claim id.
- **AD4B**: keep using Adaptive Discovery normally; revisit only once `project discover-report` says
  `usable_sample` and its numbers leave the adaptive system's value genuinely ambiguous.
FM1's live validation against Crossref/OpenAlex is likewise Kyle-machine-gated (sandbox has no route there), but
FM1's own code is Claude-lane and not yet started. Parallel prep still open for a second agent: LP5 (codex-shaped,
READY AFTER LP3), CR3 (Codex-shaped). **[Both LP5 and CR3 are DONE as of 2026-09-16 -- see the reconciliation
note at the top of NOW for current status.]**

## SUSPENDED — RESUME FIRST

D2/F1 is suspended at a safe committed boundary (0.63.57, base `30ee4f4`): mechanical inline-style
retirement is complete; F1 step 3's eight-control SVG sprite remains next. Collision is Yellow: both efforts
share frontend source and design gates. Resume by finding CSS in `styles.css` and JavaScript in its then-current
modules, re-running S50/S44/S5 plus affected gates, and recording a Resume Delta. No backend/T1 work is in flight;
the T1 cohort and release closeout are complete. Interruption cost is low.

The following earlier suspension is historical. The previously uncommitted Codex
Bootstrap/resources/UI fix set is committed on `main` (`21bb117`, `5fc2ad6`,
`d95f4b3`) and its focused tests are part of the full release suite. Claude's
F0/D1 design work is likewise merged (`79c4446`); `DESIGN.md`, `AUDIT.md`,
`DESIGN-MISSION.md`, the Apple reference sourcebook, and the evidence baseline
are tracked. Local `INSPIRATION/`, `Claude outputs/`, `SCREENSHOT AUDIT/`, and
`.audit-compare-tmp/` material remains preserved as non-authoritative evidence;
do not silently delete it.

## NEXT — admitted priorities

**[SUPERSEDED — 2026-09-16.]** This section named P0/P1A/P5 as the admitted priorities on 2026-09-14/15. All
three are long since resolved: P0 (Stage 1, L-10..L-17) is entirely DONE; P1A (Stage 3, L-20/L-21) is DONE at
L-20 with L-21 Kyle-gated (a real macOS power test); P5 (Stage 2, L-02..L-08) is DONE except L-07 (needs Kyle's
L-06 sample review first) and L-08 (Claude-prepped, needs a Mac run). CR2→CR5 and LP2→LP3, also named below, are
likewise DONE (see EXECUTION-LADDER.md Stage 10-11: CR1-CR8b and LP0-LP5 all `[x]`). Kept verbatim below as a
historical record; EXECUTION-LADDER.md is the live source of truth for current NEXT.

**Current (2026-09-16), read from EXECUTION-LADDER.md directly:**
- **[SUPERSEDED -- 2026-09-16, FM1 shipped at `87ba57b`.]** ~~Agent-ready, no Kyle gate, not yet started:~~ FM1
  (Stage 14, reference-list clustering) — FM0's $0 experiment
  chose this direction; FM1's own code is Claude-lane and buildable now. (Its live Crossref/OpenAlex validation
  separately needs Kyle's machine, but that doesn't block starting the code.)
- **Explicitly parked, not ready:** H1 (Stage 15, semantic finding dedupe). P11 Neuro Everywhere remains
  FUTURE / NICE TO HAVE.
- **Kyle-gated (code already done or the whole rung is a real-world observation, not implementation):** CR7,
  LP6, AD4B, L-06/L-07/L-08, L-21, L-30/L-31, L-40, L-41, L-51/L-52, L-60/L-61 — each names its exact required
  Kyle action directly in EXECUTION-LADDER.md. Do not build more code against these; they need Kyle's action,
  not another implementation pass.
- Do NOT restart CR1-CR8b, LP0-LP5, SC0b, AD0-AD4A, or FM0 — all DONE.

(2026-09-15, historical) After CR1 + LP1: **CR2 → CR5** (one Claim refreshed end-to-end, the P8 vertical slice) and **LP2 → LP3**
(explainable impact → proposed patch) — both READY AFTER their gate, both Claude lane. P11 Neuro Everywhere is
FUTURE / NICE TO HAVE and not in this queue. The three items below are the 2026-09-14 admissions, all now
code-complete and Kyle-gated; kept for history.


Governing document: `PRODUCT-INTELLIGENCE-MISSION.md` (mission + CTO rulings, 2026-09-14; rulings win on conflict).
Pre-read order before any rung is rulings §8, CLAUDE.md first.
The ordered, agent-executable runbook for everything admitted here is `EXECUTION-LADDER.md` (item ids L-xx).

1. **P0 — Autonomous Execution Admission Audit** (Codex lane). An AUDIT, not a build: prove the existing
   machinery (revision pinning, input_hash/is_current, dedupe_key, budgets, rate ceiling, set_status boundary,
   tensions, recovery, full integrity_check + verified backup) passes scenarios A–G under unattended execution;
   fix only measured gaps. Integration boundary `t4.execute(...)`. Closes on the scenarios passing.
2. **P1A — Scheduled Execution Backend / CLI** (Codex lane, after P0). `not_before` productized: durable
   requested time, exact-once, dedupe, cancel, restart recovery, budget, preflight, missed-window policy
   (rulings §4), honest host-availability state. First candidate: the stale-source rebuild.
   P1B (the "Tonight" UI, Claude lane): frontend split landed 2026-09-13 -- P1B is L-40, active (see NOW).
3. **P5 — remaining T4 evidence loop** (Claude lane, parallel, non-colliding): P5.2 E6 eval isolation +
   measurement; P5.3 kept-rate quality sample (Haiku default is SHIPPED, PROVISIONAL pending this);
   P5.1 brief-text relevance backtest.

Carried forward, not displacing the three above: the deliberately deferred R8 retention observation (revisit after
2026-10-11 17:28 PT); R9(c)'s numeric revisit trigger with `bge-m3` reserved (docs/R9-ADMISSION-2026-09-11.md);
D2 (`ladder.md` F1–P1) resumes as the Claude design lane once P1B/P3 need those surfaces.

The governing downstream sequence is R4 → R4 abuse gate → R5 → concurrency gate → R6 → R7 → formal Foundation
closeout → Transcript Intelligence. R6 and R7 share Foundation Phase 9 but require separate implementation and evidence.

## PARKED

- Transcript Intelligence: T1 is complete after the explicit R9(c) deferral. T2 remains the next product rung and is not admitted until its own design and state-model gate are reviewed. T4 reuses R4/R5.
- External AI access and multi-user/sharing: permissions boundary unresolved; no implementation admission.
- Project Inbox, cloud/infrastructure expansion, new acquisition classes, additional Bootstrap, Research/Discover/Planner expansion.
- Consolidated stale/risky Findings review and unrelated Findings redesign: real usability pain; revisit at Foundation admission checkpoint unless it blocks current work.
- Phrase-aware retrieval: measured failure of "quality of earnings"; two word-list fixes rejected. Revisit with a real-query quality experiment after current foundation effort.
- FIELD-MAP-RUNG and remaining SOURCE-CAPABILITY-RUNG scope: idea records, not active queues.

## REJECTED / REVISIT ON TRIGGER

Retrieval reranker, batch-path findings prefilter and Planner v3 remain off. Use HARDENING.md's measured decisions. Additional stores/services and infrastructure retain SPEED-MISSION.md §H's numeric triggers. Do not reopen an experiment simply because another session proposes it.

## DONE

- Existing speed R0–R3 and shipped product features: preserved; no restart.
- 0.63.35 local probe/model/timeout fixes: released historical baseline.
- Historical mission archival at f345726: completed.

0.63.36–0.63.39 are DONE. R8 immediate evidence is complete; its 30-day retention sample continues without
blocking the ladder. R8 retention is deliberately deferred until after 2026-10-11 17:28 PT with no deletion or cutoff admitted. R9(a) embedding decision is complete: `bge-m3` is selected from an isolated frozen-fixture scorecard. R9(b) is complete with Llama 3.1 8B adopted for short classification and all other candidates rejected. R9(c) is explicitly deferred with a numeric revisit trigger; T1 is the active rung.
R4 and its 66-case abuse gate are complete in 0.63.40. R5 and its deterministic concurrency gate are complete in
0.63.41. R6 and its Fast/Warm admission gate are complete in 0.63.42. R7 and its novelty/residual gate are complete
in 0.63.43. The authenticated Foundation closeout observation is complete: current queue was empty, integrity and
backup were healthy, release check passed, and interactive endpoint p90 was at most 0.58s in the observed sample.
T1's implementation, three-pass 73,037-attempt derived-vector backfill, zero-candidate preview, semantic cohort, and
full release gate are complete in 0.63.56; see `docs/T1-ADMISSION-2026-09-12.md`.

## AUDIT ADDITIONS — 2026-09-11

These are bounded gaps found during the post-0.63.37 review. They are admitted as Foundation follow-ons; they do not reopen parked product missions.

1. **Graceful shutdown gate — complete 2026-09-11.** Clean live restart and native SIGTERM-during-provider recovery are covered. The worker fence remains intact; interrupted invocation uncertainty is recorded as `outcome_unknown`; durable output is not duplicated. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
2. **Mutation replay/idempotency gate — complete 2026-09-11.** Queue, capture, session-ingest, collection, and candidate transitions were inventoried and covered; missing caption/metadata natural keys, capture replay, and session cookie-file reuse were fixed. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
3. **Request-path purity and test isolation — complete in 0.63.39.** Read-only status/polling paths use a cached
   health snapshot and never start a Claude CLI probe. Explicit Re-check and actual local work remain the only probe
   initiators. Tests pin every experimental feature to its production-safe default before imports. The native
   restart gate kills only after an invocation is durably in flight. Combined Phase 1/2 suite: **115 passed**.
4. **Cold derived-state budget.** The first findings-quality scan can still hit the eight-million comparison budget and emit a partial-review warning. Keep the narrowed invalidation cache; measure cold-start cost and admit an indexed/blocking or persisted derived graph only if the agreed latency and memory trigger is crossed.
5. **Evidence and repository hygiene.** `.git/index.lock` is absent. The recordings remain on local disk but no
   `VIDEOS/**` path is tracked. Clean GitHub snapshots exclude `VIDEOS/`, `data/` and `_to_delete/`.
6. **R8 evidence checkpoint — observed 2026-09-11 17:28 PT.** Copied verified backups at 16:28 and 17:28 both pass
   integrity, contain `sqlite_stat1`, and are byte-identical in size (662,859,776 bytes) with 105,048 job-event rows
   and 4,394 distinct jobs. No growth was measurable across that hour. The 30-day sample remains open.

The historical next-order note is superseded. The current execution order is the T1 measurement slice in the existing
production embedding space, with R9(c)'s deferred long-window benchmark retained behind its numeric trigger. The 30-day job-event sample continues in
parallel; no deletion or retention cutoff is admitted before its 2026-10-11 17:28 PT trigger. The cold derived-state
change remains trigger-only.

R9(a) admission: `bge-m3` is selected after passing frozen latency, recall and MRR gates; `nomic-embed-text` is rejected on MRR. R9(b) is complete: Llama 3.1 8B is adopted for short classification, while Qwen3 8B, Qwen3 14B and gpt-oss-20b are rejected on the measured gate. R9(c) is explicitly deferred; see docs/R9-ADMISSION-2026-09-11.md.

## HANDOFF UPDATE — 2026-09-13 12:31 PT

Claude remains the owner of D2/F1 Audit and Design work. The frontend lane has since landed F1 items 2–3 (the
`width:auto` utility and named SVG icon sprite) on `main` through `a914cbf`/`b30420f`; the remaining `display:none`
scope still needs Claude's element-by-element design pass. Codex's backend reliability follow-up is committed at
`c513a46` with the explicit authenticated FTS5 recovery endpoint and health history, and its deterministic release
gate is recorded at `evals/release/release-check-0.63.59-c513a46-20260913-123106.json`. Keep the ownership split:
Claude advances frontend/design surfaces; Codex takes backend/reliability work and appends shared handoff notes.

## CURRENT CHECKPOINT — 2026-09-13

Claude's F1 final item (`display:none` → native `hidden`, including the CSS specificity guard) is now landed on
`main` at `696a0c6`/`509dad2`. UI version is `0.63.60`, and Rung F1 is closed. The next eligible design rung is
**F2**, the shared loading/empty/failed-state primitive for Findings first, then Sources and Chat history. Its
deterministic gates are `test_s44`, `test_s5`, and UI version checks; its behavioral gate requires first-paint
loading, clear-on-data, clear-on-error, and an explicit failed state on the audit instance. Claude owns this lane.
Codex's FTS5 recovery and test-isolation work remains complete and does not block F2.
The dead root-level `main/` worktree copy was moved intact out of the checkout in `45428d2`; `repo-check` and the
release-check for the cleaned tree are green at `82765db` (details in `HANDOFF.md`).
The follow-up isolation cleanup is validated at `d9e2914`: full pytest 1,364 passed, and the commit-bound release
gate is green. No Codex-owned rung is admitted while Claude's F2 design work is pending its boundary.

## CURRENT CHECKPOINT OVERRIDE — 2026-09-13

The historical checkpoint above is superseded by Claude's merged F2 boundary at `49e2b62` (source `bc1aba1`). The
shared loading/empty/failed list-state primitive is implemented across Findings, Sources, and Chat history, with the
UI/package marker at `0.63.61`. Focused frontend/design gates pass, and a clean full-suite run passes **1,364 tests**
with the existing Starlette deprecation warning. F2's remaining acceptance evidence is the audit-instance behavioral
check for first-paint loading, clear-on-data, clear-on-error, and an explicit failed state under forced fetch failure;
Claude owns that verification. W1 is eligible after that gate, but has not started.

Codex remains confined to backend/reliability and measurement surfaces. T2 is still parked behind its own design and
state-model gate. R8 retention remains observational until 2026-10-11 17:28 PT, and R9(c) remains behind its recorded
numeric trigger. Preserve the ownership boundary and do not edit Claude-owned frontend or design-audit files while F2
behavioral evidence is open. The earlier mixed full-suite result was order-dependent noise; the clean rerun and focused
checks are green.

## Codex measurement checkpoint — 2026-09-13 13:09 PT

The previously trigger-only cold `findings_quality` observation has new evidence: on a temporary copy of the verified
backup, the largest retained project takes 11.871 s cold and hits the 8,000,000 pair budget, while the two smaller
projects take 0.319 s and 0.152 s. Warm-cache times are below 0.055 s for all three. This qualifies a bounded Codex
optimization investigation after the current design boundary: compare an exact indexed/blocking or persisted
derived-graph candidate against frozen duplicate counts. No implementation is admitted yet, and no blind budget
increase or new service is allowed. Claude's F2 behavioral gate remains the current design ownership boundary.

The exact-budget experiment then tested 8M, 12M, and 16M pairs on the same backup. Twelve million and sixteen
million produced identical 1,503-cluster signatures; eight million differed by two missing and one extra cluster.
Measured runtimes were 10.066 s, 11.862 s, and 11.937 s. A 12M ceiling is therefore the smallest measured complete
candidate for the current corpus, pending a deterministic regression fixture and memory check after the active design
boundary. The constant remains unchanged.

The Codex backend checkpoint now implements the measured 12M findings-quality ceiling. This remains disjoint from
Claude's F2 browser/W1 design work: only `neurosearch/findings_quality.py`, its calibration test, and shared handoff
documentation are touched. The full suite and commit-bound release gate are required before this bounded fix closes;
no new service or unmeasured threshold change is admitted.

The 12M findings-quality ceiling is now released at `fd476f5`. Full pytest passed 1,364 tests (one existing Starlette
warning), and the deterministic release gate passed at app `0.63.61`; artifact:
`evals/release/release-check-0.63.61-fd476f5-20260913-133816.json`. This bounded Codex rung is closed. Reassess the
admitted queue at the next safe checkpoint; do not change the ceiling again without a new measured corpus trigger.

Live authenticated verification confirms the running app serves the 12M result: 1,776 duplicate findings and 60
clusters for the large project in 0.625 s from the warmed cache, with no partial warning and no work queued. The rung
is therefore released in code and runtime, not only in tests.

The validated current tree is also backed up remotely on `backup/2026-09-13-clean` (snapshot commit
`aff2e407b5faae5ee8d193168bfc094f9dfabf7f`). A normal `main` push is blocked by retired historical `VIDEOS/` blobs and
was not retried destructively; local history remains intact pending an explicit history-rewrite decision.

The backup branch is refreshed after each documentation checkpoint; its current tip is discoverable with
`git ls-remote origin refs/heads/backup/2026-09-13-clean`.

The stale, already-merged `design/f0` worktree metadata was pruned and its local branch removed after verifying it was
an ancestor of `main`; only the active main checkout remains. This reconciles the scheduler's stated worktree cleanup
with the actual repository state.

The later audit-instance restart note in `HANDOFF.md` is historical and does not reopen the removed `.worktrees/f0`
checkout. The merged `design/f0` branch and stale metadata were pruned after verifying ancestry; `36ad3ae` is only a
historical baseline reference. F2's behavioral browser gate remains open and W1 remains investigation-only.

The later `design/w1-step1-vocab-disclosure` worktree was likewise a dead session pointer with no unique commits. It
was pruned and its merged local branch removed after verifying ancestry; only `main` remains as an active checkout.

## CODEX RELIABILITY CHECKPOINT — 2026-09-13 13:45 PT

With F2's browser evidence still owned by Claude and no T2 admission gate, Codex admitted one bounded backend
reliability fix: make verified backups use full SQLite `integrity_check` so FTS5 virtual-table corruption cannot be
missed by `quick_check`. A copied current backup measured `integrity_check: ok` in 1.479 s; all migration fixtures
passed. The implementation is committed with a focused 5-test pass; full pytest and the commit-bound release gate
must pass before the rung is closed. No live database was opened and no unsettled batch was mutated.

## CURRENT CHECKPOINT — 2026-09-13, W1 step 1 supersedes the prune note above

The `design/w1-step1-vocab-disclosure` prune note above was premature: that worktree was mid-edit (patch applied,
not yet committed) when it was pruned as a "dead session pointer with no unique commits" — at that instant true,
but the worktree was actively in use, not abandoned. Kyle had explicitly authorized starting Rung W1 ahead of F2's
still-open browser-verification gate. The worktree was recreated, the patch re-verified against `main`'s
then-current content, and landed cleanly: commit `b7c2422`, merged to `main` at `f0ca4b5` (86 targeted tests pass,
before and after). Details in `HANDOFF.md`'s "Rung W1 step 1 landed" entry, including a note asking that future
worktree pruning confirm a worktree is not actively in use before removing it, not only that its branch is merged
or commit-less.

F2's behavioral browser gate remains open and separately tracked. W1 is no longer investigation-only — step 1 has
landed; remaining W1 scope (Findings/Plan button-role and label consistency) is still open.

## CODEX RELIABILITY CHECKPOINT — closeout — 2026-09-13 13:51 PT

The bounded backup-integrity rung is complete. `verify_database()` now requires full SQLite `integrity_check`,
including FTS5 virtual-table validation. Focused tests passed, full pytest passed **1,364**, and the deterministic
release gate passed on the current `0.63.62 @ ec6b5e7` tree with artifact
`evals/release/release-check-0.63.62-ec6b5e7-20260913-134844.json`. No additional Codex implementation is admitted
until a new backend/reliability trigger appears; Claude's W1 step 1 is landed and its remaining design/browser gates
remain the active shared boundary.

## RUNTIME RECONCILIATION — 2026-09-13 13:52 PT

The running app is now verified at `0.63.62` (`fake_ai=false`). Authenticated Health shows no queued, running, stale,
leased, or external-pending jobs; the newest verified backup has full `integrity: ok` and 38,038 chunks. The two
historical unsettled batches (36 collected-but-unwritten items) remain deliberately untouched while Claims is paused.
The current clean GitHub snapshot is `backup/2026-09-13-clean @ 3bf21f05403c4f7c50781e6ec1ee2107c0b49b8d`.

## W1 STEP 2 RELEASE CHECKPOINT — 2026-09-13 13:54 PT

W1 step 2 is released at `1a7ff71`: Master Plan's primary `Rebuild plan` action now carries the same inline cost
label as Findings. Focused checks (86), full pytest (1,364), and the commit-bound release gate all pass at
`0.63.63`; artifact `evals/release/release-check-0.63.63-1a7ff71-20260913-135410.json`. W1's remaining work is
human re-scoring and any evidence-backed label sweep; F2 browser evidence remains open. Codex has no new independent
rung to admit while T2's state-model gate and the recorded R8/R9(c) triggers remain unmet.

## W1 STEP 2 RUNTIME CHECKPOINT — 2026-09-13 13:53 PT

Post-release authenticated verification reports `0.63.63`, `fake_ai=false`, no active or stale jobs, and a newest
verified backup with full `integrity: ok`. The 36 historical unsettled batch results remain untouched while Claims is
paused. W1 step 2 is therefore validated in code, tests, release gate, and runtime; the next evidence requirement is
Claude's human/browser re-score before additional W1 label changes.

## CONTROL-PLANE RECONCILIATION — 2026-09-13 14:01 PT

The older `NOW` block at the top of this file describes the frontend CSS/module extraction as active. That effort is
already delivered and is followed by Claude's F1/F2 and W1 work on `main`; it is no longer an active implementation
queue. The latest authoritative checkpoint is `STATE-OF-THE-APP-2026-09-13-1401.md` and the W1 step-2 release entry
above: `main` is `ed52a59`, UI `0.63.63`, W1 code steps 1–2 are released, and the remaining W1 work is human/browser
re-scoring plus any evidence-backed label sweep.

There is currently no admitted Codex-owned implementation rung. T2 remains behind its design/state-model admission
gate; R8 retention and R9(c) remain trigger-gated. Claude owns the open F2/W1 browser evidence. Do not reopen the
superseded frontend-split queue or start parked product work. A new Codex rung requires a measured backend,
reliability, recovery, or Transcript Intelligence trigger and the normal tests, documentation, and release gate.

## T2 ADMISSION PROPOSAL — 2026-09-13 14:18 PT

Codex prepared `docs/T2-ADMISSION-2026-09-13.md` from the completed T1 cohort. It defines a read-only, derived
seven-state coverage view, preserves independent signals plus a deterministic projection, requires project-relative
cut points, and postpones `chunk_pass` persistence until measured need. This is a proposal, not an implementation
admission: state semantics must be reviewed before Codex touches T2 code. It does not touch Claude-owned frontend or
design surfaces. If accepted, T2 becomes the single active Codex effort and must pass its focused tests, measurement,
full suite/Tier 1 where affected, and commit-bound release gate.

## W1 STEP 3 RELEASE CHECKPOINT — 2026-09-13 14:15 PT

Claude's W1 step 3 is released at `6a17b9e` (source `a086fb5`): both Sources re-rank controls now disclose that
ranking titles/descriptions against the project brief uses the model budget. The focused suite passed 28 tests and
commit-bound `release-check --no-pytest` passed every deterministic proof at UI `0.63.64`; artifact
`evals/release/release-check-0.63.64-307b593-20260913-141519.{json,txt}`. W1's remaining acceptance is the human/
browser re-score for F2 and W1. The T2 admission proposal is prepared but remains pending state-model review.

## T2 pre-admission baseline — 2026-09-13 14:19 PT

Codex produced `evals/t2/pre-admission-baseline-20260913-141959.json` from a copied verified backup, with no live-database access. Full `integrity_check` and `quick_check` passed; FTS5 contains 38,038 rows. The artifact publishes per-project chunk, canonical Claim/Finding, Claim-locator, Finding-citation, union-locator, and unavailable-signal counts. Unmatched locator rows (1,091 Buying Businesses; 37 Design) are recorded for T2 reconciliation and are not treated as failures or repaired. This strengthens the pending T2 state-model gate; it does not admit implementation or create a new active rung.

## T2 locator reconciliation follow-up — 2026-09-13 14:23 PT

The baseline artifact `evals/t2/pre-admission-baseline-20260913-141959.json` distinguishes exact half-open-boundary misses from internal gaps and membership problems. Buying Businesses contains 293 locators exactly at chunk ends, 615 internal gaps, and 12 excluded/non-member rows; Design contains 12 internal gaps and 25 edge misses; Real Estate matches all 603. T2 must preserve `[start, end)` semantics and report unavailable/reconciliation reasons rather than silently broadening coverage.

## T2 state-model admission — 2026-09-13 14:26 PT

The internal state-model gate is closed. T2 is now the single active Codex rung, implemented only through the existing T1 read-only coverage seam. The fixed rules are finite locators with `[start, end)` chunk boundaries, typed boundary/membership gaps, project-relative attested T1 representation, and explicit unknowns for source-level relevance, findings-only redundancy, and pre-T3 extraction. `unexplained` remains unavailable whenever a required input is unavailable. Artifact `evals/t2/pre-admission-baseline-20260913-141959.json` is the baseline; no UI, table, provider call, or live-data mutation is admitted.

## T2 implementation closeout — 2026-09-13 14:35 PT

T2 is release-checked at `280146a`; the existing authenticated coverage route now pages the derived seven-signal view. Cohort `evals/t2/cohort-20260913-1435.json` measured all 38,038 retained-project chunk vectors read-only, with project-relative p90 thresholds and typed boundary/member/gap reconciliation. The full 1,368-test suite and deterministic release artifact `evals/release/release-check-0.63.65-280146a-20260913-143316.json` are green. Unknown states are explicit where T3 extraction, chunk-level redundancy, or validated chunk-level relevance does not yet exist; `unexplained` is never inferred. T2 is closed. The next Codex-owned work is to prepare T3's deterministic extraction admission and precision gate; Claude retains the open W1/F2 browser/human gate.

## Claude W1 step 4 landing — 2026-09-13

Claude's W1 step 4 (`f143266`) discloses model-budget use on the legacy Sources “Re-analyse all” control and synchronizes UI/package version `0.63.65`. This frontend change remains Claude-owned; Codex's T2 work stayed in backend/tests/docs.

## T3 admission — 2026-09-13 14:40 PT

T2 is closed. The next single Codex-owned rung is deterministic Tier-0 extraction under `docs/T3-ADMISSION-2026-09-13.md`: pure versioned spans, exact offsets, reuse of existing identifier/URL extractors, and a copied-backup precision gate. No persistence, UI, provider call, or live mutation is admitted before the sample and release gates pass.

## T3 extractor checkpoint — 2026-09-13 14:47 PT

The next Codex rung is implemented as a pure `t3-tier0-v1` extractor with exact spans and no scheduler, provider,
queue, persistence, or UI effect. Focused tests cover deterministic ordering, overlap, malformed input, URL and
identifier normalization, phone-shaped ISBN rejection, punctuation-safe entities, and comma-safe durations. The
read-only provisional sample `evals/t3/tier0-sample-20260913-144650.json` covers 15 chunks across all retained projects
and 64 manually reviewed candidates (1.00 provisional precision/recall). This is not a downstream admission: T4 and
stored extraction remain blocked until a larger seeded sample and commit-bound release gate pass.

## T3 release checkpoint — 2026-09-13 14:50 PT

T3 is implemented and release-checked at `46f0a5e`; full pytest 1,376 passed and the deterministic release artifact
is `evals/release/release-check-0.63.65-46f0a5e-20260913-145001.json`. The extractor remains outside scheduling,
queues, providers, persistence, and UI. Do not schedule extraction or downstream selector work until the larger
seeded/adversarial hand-label gate closes.

## T3 adversarial tests — 2026-09-13 14:56 PT

Seven new deterministic negative/boundary tests protect T3 from phone/ZIP/address identifiers, bare cues, numeric
subspan double counts, and punctuation leaks. Focused T3 coverage is 15 passed; no scheduling or downstream trust is
admitted.

## State-file hygiene repair — 2026-09-13 15:00 PT

Moved superseded `STATE-OF-THE-APP-2026-09-13-1436.md` into `docs/archive/state/` so the release hygiene gate sees
one authoritative root state file. No scheduler behavior changed.

## Release hygiene correction — 2026-09-13 14:57 PT

Archived the superseded root state file that caused the release hygiene test to fail. The affected test now passes and
`release-check --no-pytest` is green at `e4cf07f`; no scheduler behavior changed. Current root state:
`STATE-OF-THE-APP-2026-09-13-1457.md`.

## T3 seeded review manifest — 2026-09-13 15:01 PT

Prepared a 60-row, project-balanced T3 hand-label queue with deterministic seed and all targeted kinds. Rows remain
pending manual gold labels; no scheduler or downstream extraction work is admitted from this manifest.

## T3 review triage — 2026-09-13 15:04 PT

Pending T3 rows carry review-priority flags only; scheduling and downstream selector work remain gated on manual gold
labels and precision floors.

## T3 triage release checkpoint — 2026-09-13 15:02 PT

The pending review triage metadata is green under `repo-check` and release-check at `2b460ae`; no scheduler or queue
behavior changed. Manual gold adjudication remains the next gate.

## T3 precision narrowing — 2026-09-13 15:12 PT

Corpus review narrowed cue matching to avoid heading, narration, and bare-fragment false positives. Full pytest remains
1,383 passed; no scheduler or downstream extraction path changed. Manual gold review is still required.

## T3 precision-fix release checkpoint — 2026-09-13 15:07 PT

Cue precision narrowing is release-checked at `452804e`; scheduler and downstream behavior are unchanged. Manual gold
adjudication of the pending 60-row queue remains required.

## T3 decimal-boundary hardening — 2026-09-13 15:16 PT

Numeric decimal boundaries are hardened and covered by focused tests; scheduler behavior is unchanged and downstream
trust remains gated.

## T3 decimal-boundary release checkpoint — 2026-09-13 15:08 PT

T3 numeric boundary hardening is green at `f1533c6`; no scheduler behavior changed. Manual gold review remains the
next gate.

## T3 malformed-number and decimal-sentence hardening — 2026-09-13 15:24 PT

Numeric and sentence decimal boundaries are hardened under focused tests; scheduler behavior is unchanged and manual
gold review remains required.

## T3 numeric-boundary release checkpoint — 2026-09-13 15:13 PT

Numeric and decimal sentence boundaries are release-checked at `763c8eb`; scheduler behavior is unchanged. Manual gold
review remains the next gate.

## T3 review scoring infrastructure — 2026-09-13 15:35 PT

Pure review validation/scoring helpers are available for the pending queue; scheduler behavior and downstream trust are
unchanged.

## T3 review infrastructure release checkpoint — 2026-09-13 15:15 PT

Pure T3 manifest validation/scoring is release-checked at `7821cb5`; scheduler behavior is unchanged. Manual gold
adjudication remains the next gate.

## T3 review scorer cross-row correctness — 2026-09-13 15:45 PT

The pure scorer now preserves cross-row duplicate spans; scheduler behavior is unchanged and manual gold review remains
the gate.

## T3 review scorer release checkpoint — 2026-09-13 15:16 PT

Cross-row review metrics are corrected and release-checked at `2c815e7`; scheduler behavior is unchanged. Manual gold
review remains the next gate.

## T3 interrogative/procedure overlap fix — 2026-09-13 16:05 PT

Procedure/question overlap is corrected under focused tests; scheduler and downstream behavior remain unchanged.

## T3 interrogative/procedure release checkpoint — 2026-09-13 15:22 PT

Procedure/question overlap is corrected and release-checked at `81f2cd9`; scheduler behavior is unchanged. Manual gold
review remains the next gate.

## T3 narrative cue narrowing — 2026-09-13 16:20 PT

Narrative procedure/comparative false positives are narrowed under focused tests; scheduler behavior is unchanged.

## Audit runtime allowlist repair — 2026-09-13

The hygiene checker now recognizes the documented `data-audit/` audit runtime; scheduler behavior is unchanged.

## Reconciliation: NOW section is stale — 2026-09-14 10:16 PT

This file's "NOW" header still names the `index.html` CSS/module split as the active effort. That split, and
Claude's full 22-finding design/audit declutter pass built on top of it, are both already committed on `main`
(declutter closed through commit `ee52d1a`/`6f30e76`; see `HANDOFF.md`). Not rewriting that section's history —
appending instead, per this file's own append-only rule.

The actual active technical gate is T3 manual gold adjudication: the 60-row seeded review queue
(`evals/t3/seeded-review-manifest-20260913-150111.json`) needs exact-span, per-kind gold labels, including
adversarial negatives and boundaries, before extraction can be persisted, trusted by a selector, used by T4, or
exposed as user-facing state. The comparative false-positive narrowing landed today (`3ec5fff`) is extractor
hardening discovered *during* that review, not a substitute for it. Design/audit ownership remains available for
fresh evidence-driven work but has no queued findings; do not reopen closed F0/F1 findings without new evidence.

## T3 comparative-narrowing checkpoint — 2026-09-14 10:16 PT

Narrative-fragment false positives on bare more/less comparatives are narrowed and release-checked at `3ec5fff`;
scheduler behavior is unchanged. Manual gold review of the 60-row queue remains the next gate.

## T3 gold-adjudication gate closed — 2026-09-14 11:35 PT

The 60-row seeded gold-adjudication queue is fully labeled with 0 false positives found; every per-kind
precision floor passes. T3's admission gate is closed at commit `3ca18be`. The next admitted rung is T4
(Batch Research Executor) per `TRANSCRIPT-INTELLIGENCE-MISSION.md`, but T4 requires its own design/storage
review before implementation — it is not auto-admitted by this closure. Scheduler NEXT/PARKED sections are
unchanged pending that review.

## T6 admitted — assumption ledger — 2026-09-14

T6's first slice (registry + CLI + informational doctor check) is admitted at `e0e99f5`, built alongside T4/T5
under Kyle's "do 4/5/6 now" authorization. Per the mission doc T6 is parallel, not a prerequisite — it does not
change NEXT/PARKED sequencing for T4/T5.

## T4 admitted, selector only — 2026-09-14

T4's selector (ranked work list, no executor) is admitted at `86ddab9`, built alongside T5/T6 under Kyle's
"do 4/5/6 now" authorization. The executor interface (Claude Code / local model / Haiku API / future cloud
worker) remains future, separately-admitted work — nothing currently calls `t4.select`'s output or acts on it.

## T5 admitted, propose only, no live spend — 2026-09-14

T5's escalation trigger is admitted at `ed37393`, built alongside T4/T6 under Kyle's "do 4/5/6 now"
authorization. No live adjudication call has been made anywhere -- `escalation_candidates()` output is not
wired into any workflow yet. This is now the "do 4/5/6" set's last item; all three are admitted.

## T4 shipped — selector + $0 executor routing — 2026-09-14

T4 now has both halves represented at `c127978`: a tested selector (`86ddab9`) and a tested, $0 executor
routing dry run (`c127978`). Kyle chose the $0 scope explicitly over a full live executor. The remaining work --
wiring `providers.route()`, a real provider/local call, and a structured-delta write path -- is not started and
has no target date; it's the next step whenever Kyle wants T4 fully live.

## T5 real call ready, waiting on a working API key — 2026-09-14

The real adjudication call path (`t5.adjudicate`) is built, tested, and committed at `1e6b632`. It cannot run
for real until Kyle refreshes the Anthropic API key in his `.env` -- the current one returns 401 Unauthorized.
Once fixed, `t5.adjudicate('c752ed152ec942dd97b9a94c3f1b3b96', '67d9643a5fb54c488888fe9805f0ad39')` is ready to
run against his real "Buying Businesses" project with no further code changes.

## Control-plane reconciliation — 2026-09-14 12:17 PT

The historical `NOW` header still names the frontend CSS/module split. That work and Claude's complete 22-finding
declutter pass are already committed. The current active technical state is instead the low-cost reliability and
control-plane cleanup recorded in `STATE-OF-THE-APP-2026-09-14-1217.md`.

T3's 60-row exact-span gold gate is closed at `3ca18be`; T4 is shipped through the selector and the $0 executor
routing dry run (`86ddab9`, `c127978`); T5's proposal and real-call paths are shipped at `ed37393` and `1e6b632`
but live execution is blocked by the invalid Anthropic credential; T6 is shipped at `e0e99f5`. Do not retry T5,
wire live T4 provider execution, or add structured-delta persistence without the required credential and explicit
admission. The immediate safe work is deterministic test-isolation, pure side-effect coverage, and release/document
reconciliation.

## Control-plane reconciliation — 2026-09-14 12:31 PT

Claude's later T5 evidence supersedes the historical “invalid key” wording above: the device egress proxy, not
the credential, returned the synthetic `401`. One adjudication ran through a documented bridge at `$0.003768`
and wrote suggested note `29360`; no Claim or tension status changed. Do not retry T5 or make other paid calls
while the weekly allowance is constrained.

The low-cost cleanup has now removed the root keep-awake warning without broadening `repo-check`: full pytest is
**1,436 passed, 1 warning**, `repo-check` passes, and commit-bound `release-check --no-pytest` passes at `296d20f`.
The next Codex-owned items are explicit test regressions for fresh-database breaker isolation and blocked-T5
no-mutation, followed by the ordinary full release ritual. Claude retains ownership of audit/design documents.

## Cleanup gates closed — 2026-09-14 12:37 PT

Codex's local-only cleanup is complete at `ceca6e5`: the auth/egress failure path is proven no-mutation and
fresh-database provider-breaker isolation is covered. Full pytest is **1,438 passed, 1 warning**; `repo-check`
and commit-bound `release-check --no-pytest` pass. The release artifact is
`evals/release/release-check-0.63.90-ceca6e5-20260914-123650.json`. Keep T5 retries, live T4 execution, claims,
and structured-delta writes behind their existing admissions and spend controls.

The current documentation tip is `8d15a2e`; a docs-only commit-bound release check passes there as well, with
artifact `evals/release/release-check-0.63.90-8d15a2e-20260914-123747.json`.

## T4 real extraction reconciliation — 2026-09-14 12:39 PT

Claude subsequently exercised the existing `findings.suggest_for_source()` pipeline on the highest-priority
T4-selected source through the documented egress bridge: six real Sonnet calls cost `$0.3492` and materialized
47 suggested findings, with substance 12/100. Combined real spend today across T4 and T5 is `$0.352949`.
This does not change the admission boundary: the general T4 executor, provider routing, and structured-delta
write path remain future work; only this one throttled extraction was run.

## T4 second-batch checkpoint — 2026-09-14 12:47 PT

Claude ran six additional T4-selected sources through the unchanged findings pipeline: 33 real Sonnet calls cost
`$1.9937` and materialized 165 more suggested findings. The acquisition-specific sources scored substance 68 and
83, while generic sources scored 5–26. Combined T4/T5 spend is `$2.346612`; no further paid calls are authorized
under the current allowance. The general T4 executor and structured-delta path remain future admissions.

## T4 third-batch checkpoint — 2026-09-14 12:50 PT

Claude ran six more T4-selected sources through the unchanged findings pipeline: 18 successful real calls recorded
`$0.908735` and materialized 146 suggested findings. “Buy then Build” scored substance 79. The first attempt made
17 billed calls before a five-minute timeout without incremental checkpoints; approximately `$0.79` was spent with
no usable output and no app-ledger row. The rerun now checkpoints after each source. Recorded T4/T5 spend is
`$3.255347`; estimated actual billing is roughly `$4.04`. No further paid calls are authorized.

## Optional cleanup follow-through — 2026-09-14 12:44 PT

The stale F0 worktree registration was pruned after verifying its path was gone and no `design/f0` branch existed.
The native worker-restart foundation suite is green (**18 passed**), and T3's bracket-label and unpunctuated-cue
recall gaps are now pinned by explicit regression tests. No scheduler or production behavior changed.

## Final optional-validation checkpoint — 2026-09-14 12:46 PT

The current full suite is **1,439 passed, 1 warning**, with `repo-check` PASS. The stale F0 registration and
Claude's root-level T4 bridge scratch entries were cleaned up safely: the former was pruned after branch/worktree
verification, and the latter were moved intact to `/Users/kyleowen/neuro-t4-bridge/`. No scheduler behavior changed.

## Product Intelligence Mission admitted — 2026-09-14 evening

`PRODUCT-INTELLIGENCE-MISSION.md` adopted with Kyle's CTO rulings (P0 is an audit rung; P1 splits into P1A backend
/ P1B UI; host sleep is a hard product constraint with a missed-window policy; E5 is SHIPPED-PROVISIONAL pending
P5.3; Decision Impact v1 = disagreement + plan impact only; Morning Report v1 must not fake a ranked "what needs
me"; CLAUDE.md heads the pre-read; Claude keeps T4 experiments, Codex owns scheduling/preflight/E7 orchestration
around `t4.execute`). NEXT above rewritten to P0 → P1A → (P5 in parallel). The NOW item (Codex's frontend split)
is unchanged and P1B waits behind it. Today's earlier entries under "T4 shipped / T5 real call ready" are
superseded on two facts: T4 E3–E5 ran for real (docs/T4-ADMISSION-2026-09-14.md) and T5's real adjudication did
run once via the bridge (HANDOFF.md).
