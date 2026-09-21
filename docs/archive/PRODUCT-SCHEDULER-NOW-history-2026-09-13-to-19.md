# PRODUCT-SCHEDULER.md — superseded NOW / SUSPENDED notes (2026-09-13 → 2026-09-19)

Moved out of `PRODUCT-SCHEDULER.md` on 2026-09-21 by the repo audit. Every note below was superseded by a later one; none is an assignment. The live queue is the top of `PRODUCT-SCHEDULER.md`.

---

# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-16 (NOW section reconciled against EXECUTION-LADDER.md's live per-item state; the rest of this file is an append-only history and reflects the date each entry was written). This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

**CONTINUOUS EXECUTION — 2026-09-19, current authority.** Kyle requested the recommended plan as a mission
and ladder. Follow [docs/CONTINUOUS-EXECUTION-MISSION.md](docs/CONTINUOUS-EXECUTION-MISSION.md): CE0's focused
baseline and CHR3 implementation plus its deterministic release proof are complete in the isolated candidate; next
finish screenshot/auth/course acceptance, the CHR3 paid/browser gate, and release eligible repairs.
Prepare existing research-feature acceptance when higher-priority work is blocked. One runtime rung at a time;
no routine per-rung pauses. The subreddit candidate is offline-complete on `codex/subreddit-integrated`
(`abdefaa`, checkpoint `c842861`, 2,169-test release PASS), blocked only for its real-access/acceptance and delivery
gates; resume it at a safe boundary when approved access exists. Preserve that branch and reconcile later.
This plan adds no dollar budget, does not reopen CHR2, and does not admit the parked roadmap. The older
subreddit-only active-effort/R1-next declarations below are historical and superseded. Feature-specific records
retain their own gates; the new mission is the sole cross-feature execution ladder.

**SUBREDDIT CORRECTION — 2026-09-19 (supersedes older active-effort orientation below).** Kyle requested
an updated remaining-work plan for the partial subreddit implementation already on `main`. Codex is the executor; Claude
is no longer executing this mission. Follow [the canonical mission, Section 5](docs/SUBREDDIT-CATALOG-MISSION.md#5-corrective-execution-ladder--current-authority),
SUB-R0–SUB-R9. At review base `66f4d4d`, R0's baseline passed; next is R1's remaining project/identity
boundaries with bounded fixture hygiene, then R2's atomic run/job admission and retry lifecycle. R1–R9
acceptance remains open despite partial corrections and a pre-rebase deterministic release-check pass.
The current request updates documentation only. R8 separates offline operational proof from live access,
browser and capture acceptance. CHR2 is closed at its verified visual checkpoint (`7b43dc8`). Other unfinished
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

