# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-13. This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

Kyle's 2026-09-13 override: split `neurosearch/web/index.html` into static CSS and native ES modules,
without a build step or visual/behavior changes. ACTIVE: CSS extraction first, then state/API/shared formatting,
view modules and bootstrap/router in independently mergeable steps. Acceptance: affected frontend gates after
each step; full pytest, Tier 1 and commit-bound release-check at release boundaries. Initial CSS landing is
Kyle's direction-check checkpoint before the JavaScript split. Progress and isolation details: `HANDOFF.md`.

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

## NEXT — admitted priorities (maximum three)

1. Continue D2 (`ladder.md` F1–P1) one bounded design surface at a time, using
   Claude's ownership boundaries and append-only handoff rules. The completed
   T1 cohort is recorded in `docs/T1-ADMISSION-2026-09-12.md` and
   `evals/t1/cohort-20260913-105835.json`.
2. Continue the deliberately deferred, non-blocking R8 retention observation; revisit after 2026-10-11 17:28 PT and admit no retention cutoff before then.
3. Preserve R9(c)'s numeric revisit trigger and keep `bge-m3` reserved for a
   later full-space migration gate. See `docs/R9-ADMISSION-2026-09-11.md` and
   `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.

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
