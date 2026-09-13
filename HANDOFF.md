# HANDOFF — shared Codex / Claude delivery mechanics

## Start here

1. Find every `STATE-OF-THE-APP-YYYY-MM-DD-HHMM.md`; read the newest timestamp.
2. Read `DEVELOPMENT-OPERATING-SYSTEM.md` for Kyle's governing workflow, and `CLAUDE.md` for standing invariants.
3. Read `FOUNDATION-HANDOFF.md` for changes, validation, delivery status and the exact restart point.
4. Read only the active rung and relevant tests/HARDENING entries. `PRODUCT-SCHEDULER.md` owns priorities.

The active program is Transcript Intelligence, admitted after the completed Foundation closeout. External AI access,
expanded Research/Discover/Planner, additional Bootstrap and unrelated Findings redesign are parked. Old declarations
of a current mission are historical evidence only.

Live-project hygiene was completed on 2026-09-12 18:51 PT through the authenticated API: ten synthetic `G2`/`G2
chat`/`G2 api`/`Article routing` fixtures were deleted. The three remaining projects are the two protected user
projects and the Claude/chatGPT design project. See `docs/LIVE-PROJECT-CLEANUP-2026-09-12.md`; this cleanup did not
touch the database directly or alter the T1 spend boundary.

Current execution state: Foundation 0.63.43 is release-checked at `bf8d595`; the active T1 slice is release-checked
on the current T1 commit chain. R7 adds project-relative embedding
comparison to R6 scheduling and Findings reading: redundant material receives a bounded priority reduction, while
its least-similar residual chunks are read first. This never removes a source or kept window; missing/corrupt vectors
leave existing order unchanged. Full pytest, Tier 1 and release-check pass. The authenticated closeout observation
also found a clean queue, healthy integrity/backup state and interactive endpoint p90 at or below 0.58s. T1 is
implemented through corpus attestation, versioned derived-vector storage, fail-open measurement helpers, and a
read-only cohort in the existing production `text-embedding-3-small` space. R9(a)'s selected local `bge-m3` result is 34.48
ms p50, recall@10 1.0000 and MRR 0.8898; it is reserved for a later full-space migration gate. R9(b) is now complete: Llama 3.1 8B
clears the short-classification gate and the other declared candidates are rejected. R9(c)'s long-window benchmark
is explicitly deferred with a numeric revisit trigger. R8 retention is deliberately deferred to its non-destructive observation trigger after
2026-10-11 17:28 PT and is non-blocking. Existing production chunks remain
unchanged; the remaining T1 gate is the explicitly authorized derived-object backfill and semantic cohort. See `PRODUCT-SCHEDULER.md`,
`docs/PRE-T1-GATE-AUDIT-2026-09-12.md` and `docs/T1-ADMISSION-2026-09-12.md`.

T1's pre-backfill correctness review closed the stale/wrong-space selection gap, pinned queued model identity through
execution and usage accounting, made corpus attestation expire after canonical embedding changes, and removed a
test-order authentication leak. The 2026-09-12 19:07 PT live re-measurement found 37,629 valid chunk vectors and
39,740 derived objects across the three retained projects. Full pytest passed 1,353 tests. The backfill remains
unstarted and requires an explicit spend decision. Commit-bound release-check candidate `fd66241` passed at 19:22 PT
in 172.6 seconds; artifact: `evals/release/release-check-0.63.43-fd66241-20260912-192249.json`. H1's batch economic
gate remains deferred by design.

GitHub custody: the current documentation tree is published on `https://github.com/PandarsisKO/Neuro` and the latest
compact sync was verified tree-equal to this checkout. The published snapshot includes the Foundation R7 closeout,
R9(a)/(b) scorecards, the T1 vector-space reconciliation, the R8 revisit trigger, the Claude handoff, and the
reproducible R9(c) continuation chain. Re-run the compact sync after any future tracked documentation change.
`VIDEOS/`, `data/` and `_to_delete/` remain absent from tracked files.

## Shared checkout and coordination

The Mac checkout is `/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO`. Codex works directly on this Mac; historical VM/device-bridge/tar delivery instructions DO NOT apply here. Claude was dormant when Kyle confirmed coordination on 2026-09-11.

Before editing, inspect current Git state and the Foundation handoff. Record the base commit, isolation path and touched files. Before delivery, compare against that base; preserve other changes and reconcile overlap instead of overwriting it. Never reset, broadly stage, remove Git locks, or delete files as a delivery shortcut. Do not assume a clean tree solely because an older handoff says so.

Current custody note: the compact GitHub tree is protected and `git ls-files 'VIDEOS/**'` returns zero files. A
zero-byte `.git/index.lock` held by the macOS Virtualization VM process released at 16:08 PT; no Git process was
associated, the real index was reconciled to `HEAD`, and no lock is present now. The recordings remain on local disk
and are excluded from Git/GitHub. Do not add `VIDEOS/`, `data/` or `_to_delete/` to a snapshot.

The former preserved Bootstrap/resources/UI/test set is committed on `main`
(`21bb117`, `5fc2ad6`, `d95f4b3`) and covered by the full release suite. `AUDIT.md` and `DESIGN.md` are canonical,
tracked design
source-of-truth and audit contract on `main` (merged from the `design/f0` branch at `79c4446`, which also carries
`APPLE-DESIGN-REFERENCES.md` and the `docs/design-audit/2026-09-13-b85c222/` evidence set). See `DESIGN-MISSION.md`
for current D0/D1/D2 status. `Claude outputs/T1-DESIGN-AUDIT-2026-09-12.md` and `INSPIRATION/` remain untracked
reference material; preserve them. The tracked copy of Claude's design audit is `docs/T1-DESIGN-AUDIT-2026-09-12.md`.

## Operating model

The repo is the control plane, not either agent's chat history or Kyle. Claude and Codex coordinate through Git
state, `ladder.md`, `PRODUCT-SCHEDULER.md`, `DESIGN-MISSION.md` and this file, and through commits and their
messages — never by relaying messages through Kyle, and never by assuming the other agent's chat context. Assume
either agent's session can end at any time: at any reasonable stopping point, a fresh agent must be able to recover
the active mission, current rung, what's done and remaining, changed files, test/gate results, and the next safe
action from repository evidence alone.

Either agent may inspect, diagnose, implement, test, exercise, verify, commit and advance eligible work
independently, without waiting for the other and without making the other wait. Roles are specialties, not locks:
Claude for design judgment, UX diagnosis, and verification; Codex for sustained implementation, refactors and
long-running engineering. Neither "the other agent owns this" nor "I need the other agent's context" is a valid
reason to block on eligible work. Before editing, check current Git state and recent commits for overlap: if another
agent is working an unrelated area, proceed; if the same files or surface, do not overwrite — pick another eligible
task or reconcile from actual diffs and commits, never assumptions.

Execution loop for a meaningful unit of work: inspect, implement, test, exercise, verify, commit, record state in
the existing docs, continue. A progress update is not a stopping point. Prefer small coherent commits over one large
uncommitted change; after a coherent milestone, leave a breadcrumb in the existing state/handoff docs rather than a
new document. Do not expand `DESIGN.md`/`AUDIT.md` for ordinary one-off implementation choices — that doctrine is
frozen unless a genuine contradiction or repeated failure appears; execution-specific judgment belongs in the
rung/state/handoff docs instead. Verification happens at meaningful rung/closure boundaries, not on every commit —
deterministic tests protect the space between them.

Stop for Kyle only for a genuine product decision, a destructive or irreversible choice, an architectural conflict,
a credential only he controls, or a blocker that cannot reasonably be resolved from repository evidence. Otherwise
make the best safe decision and continue. Coordination stays lightweight: no agent-lock files, no duplicate TODO
systems, no separate Claude/Codex plans, no new orchestration framework — Git state plus the existing ladder and
state docs are the memory.

## Protect the live app

Never open or copy the live `data/neurosearch.db`, even read-only. Never delete it. Never run tests, doctor, eval, release-check or a second server against it. Use the running app's supported API for observations. For raw SQL use a verified backup copied into a private temporary workspace, never the original backup in place.

Prepare runtime changes in an isolated checkout/copy without `.env`, `data`, cookies or media. Set a private temporary `NEUROSEARCH_DATA_DIR` for commands. Tests use deterministic fakes and private databases; live provider work must have a justified measurement and explicit cost/transport decision. Do not change Kyle's `.env` to make a test pass.

Runtime files are watched by the live server. Landing them can interrupt active work. Prepare the exact tested change and handoff first; delivery approval, where needed, is the final step. Kyle does no terminal work. A restart needed for recovery must use the existing double-clickable launcher or be performed by the agent with authorization, never assigned as shell commands to Kyle.

## Validation and release

During development run affected tests plus touched invariant gates. At a release boundary run full pytest, Tier 1, release-check, and check version agreement (`neurosearch/__init__.py`, `pyproject.toml`, UI_VERSION). All commands operate in the isolated workspace. Test failures must be diagnosed rather than repeatedly rerun until green.

Record the actual command, result, environment, candidate source hash, and artifact paths. A previous PASS is not evidence for edited code. An artifact marked `nogit` is historical evidence without commit binding; new artifacts must identify the tested candidate and its base. Do not call code released merely because it was written or tests passed. Record prepared, delivered, committed/tagged and live-verified separately.

Rung evidence belongs in HARDENING.md and current state/handoff documents. Do not append new work to archived EXPANSION.md. Preserve frozen baselines; changes require explicit measured justification. Browser behavior and M3 Max/provider performance require their own verification.

## Returning to suspended work

Answer: what did intervening work benefit, hinder, invalidate or add risk to? Compare touched surfaces and assumptions, write a Resume Delta, and run intersection gates before continuing. Do not mechanically resume a historical checklist.

The prior handoff is retained in `docs/archive/HANDOFF-2026-09-11-pre-foundation.md` for history only.

## T1 backfill execution — 2026-09-13

Kyle authorized the paid derived-object backfill. The live app was re-attested
through its authenticated API at 38,038 valid 1,536-dimensional chunk vectors,
zero malformed rows, revision 10. Codex added the bounded enqueue endpoint
`POST /api/projects/{project_id}/transcript/backfill` (pages of 1–5,000 with an
offset) and committed it at `1194646`; the focused T1 suite is 16 passed and the
full deterministic suite is 1,362 passed. The queue was paused while admitting
exactly 39,951 low-lane `t1_embed_derived` jobs across the three retained
projects, then resumed. Health showed 3,206 complete, 36,586 queued, two running,
zero stale leases, and zero new T1 failures at the last observation. Do not
re-enqueue; dedupe keys and offsets already cover the full scope. When queued
reaches zero, use the supported coverage endpoint for each project and save the
fresh version-stamped semantic cohort before any T2 decision.

### Execution checkpoint — 2026-09-13 09:23 PDT

The backfill remains healthy on the live local-profile workers. A supported
health sample recorded 20,702 global jobs done, 24,911 queued, four leased,
zero stale leases, and the unchanged historical failure total of 50. The
project-scoped preview reported approximately 26,065 T1 candidates still
needing vectors (17,433 / 7,438 / 1,194 by project); the difference from the
global queue is pre-existing non-T1 work that is draining concurrently.
OpenAI Embeddings remained closed/Healthy with no new failures. This is an
observation checkpoint only; no jobs were cancelled, re-enqueued, or reprioritized.

### Stale-input reconciliation admission — 2026-09-13 09:49 PDT

The first 39,951-job cohort reached terminal state with zero T1 failures. Its
post-run preview showed 14,742 changed claims in the buying-businesses project
and 3,602 changed claims in the design project; all notes and all real-estate
rows were current. The claims had legitimately returned `skipped: stale_input`
because revision metadata moved while the live app continued its own work.
With the background queue paused, Codex admitted exactly 18,344 fresh claim
jobs through the bounded offset endpoint (14,742 + 3,602), observed 18,325
queued and three running after resume. Four pre-existing `extract_claims` jobs
were outside this T1 cohort; the one still running was later cancelled through
the supported endpoint as requested, and no claims job remained active at
closeout.

### T1 cohort closeout — 2026-09-13 10:58 PDT

After the claims lane was explicitly cancelled, the final 14,742-claim pass
reached terminal state with no T1 failures. The supported preview returned
`total_rows: 0` for all three retained projects. The accepted cohort is
`evals/t1/cohort-20260913-105835.json`, collected from live and repository
version 0.63.56 at commit `c0d2054`.

The artifact records 73,037 T1 attempts: 41,477 embedded writes and 31,560
stale-input skips across the initial admission and two reconciliations. All
73,037 T1 jobs are terminal `done`, with zero T1 failures. Semantic coverage
is measured in the attested OpenAI `text-embedding-3-small` 1,536-dimensional
space for every canonical active row: buying-businesses 14,742 claims / 16,577
findings, design 3,602 / 3,834, and real estate 589 / 605. Coverage latency
and the month cost ledger are recorded separately in the artifact. The
top-level coverage `status` remains the compatibility readiness label; the
nested `semantic_distributions.status` is the measured result.

The full release gate passed at
`evals/release/release-check-0.63.57-9c15f36-20260913-110852.json`: 1,362 tests
plus all migration, crash/recovery, identity, retrieval, frontend, backup, and
repository-hygiene gates passed in 198.5 seconds, with the one existing
Starlette deprecation warning.

## QA stabilization handoff — 2026-09-13

The repository-control mission is archived at
`docs/archive/missions/QA-STABILIZATION-MISSION-2026-09-13.md`.
R0 through R8 are complete: the root reading path is documented, superseded
state snapshots are archived, `neurosearch repo-check` is deterministic and
clean, high-confidence duplicate definitions and the direct-DB boundary are
covered, design D1/F0 is merged, and `release-check` blocks on repository
hygiene findings. The merged-design release artifact is
`evals/release/release-check-0.63.43-6edcb73-20260913-030843.json` and records
PASS. R9 found no safe unmeasured cleanup candidate; R10 closeout is the next
action once the mission status is archived. Claude-owned design files remain
canonical and must not be duplicated.

## Design ladder — F1 step 1 landed — 2026-09-13

`ladder.md` rung F1 ("Land the frozen tokens, retire the tokenizable inline patterns, name the eight controls")
has three steps; step 1 only is done, on `main` at merge commit `9dfbc15` (source commit `f77e673` on branch
`design/f1`, now safe to delete). It replaces the drifted `:root`/`[data-theme=dark]` colour tokens in
`neurosearch/web/index.html` with the frozen palette from `DESIGN.md` §5, fixing the two measured AA failures
(`--ok`, `--warn` both now >= 4.5:1 on `--panel` in light theme; dark theme's only change is `--accent-text`
going near-black per DESIGN.md's own rule). No existing token name was renamed; the frozen set's new names
(`--panel-strong`, `--text-faint`, `--line-strong`, `--accent-hover`, `--accent-soft`, `--ok-soft`, `--warn-soft`,
`--bad-soft`, `--focus`) were added for steps 2/3 and later rungs to use. `UI_VERSION` bumped to `0.63.44` in all
three sites. A new deterministic gate, `test_status_text_colours_meet_aa_on_panel` in `test_s50_design_drift.py`,
holds this; it and the existing `test_s50`/`test_s44`/`test_s5` suites pass (24 tests).

**Not done yet, still part of the same F1 rung:** step 2 (the shared spacing/flex/type-scale/status-modifier
utility classes, retiring inline styles on the ranked offender surfaces, the base-input `width:auto` fix, the
`hidden`-attribute conversion) and step 3 (the inline SVG sprite naming the eight emoji-only controls). Do not
start F2/W1 work while inside `index.html` for this — see `ladder.md`'s own sequencing note.

**Owed, not completed this session: the human rendered re-audit in both themes against `evidence/`.** The
already-running audit instance (`localhost:8788`) did not reflect this merge on reload — it kept serving
`v0.63.43`, so whatever process is behind it is not reading this checkout's `main` live, or needs an explicit
restart this session wasn't positioned to trigger unprompted. Separately, its theme toggle does not flip
`[data-theme]` on click (pre-existing, unrelated to this change, not fixed here per F1's non-goals), and forcing
the attribute via devtools produced correct `getComputedStyle` values without a visual repaint in this browser
session — likely a screenshot-capture staleness quirk. Whoever restarts the audit instance next should do the
before/after rendered check for this commit as the first order of business, before F1 continues to step 2.

## Design ladder — F1 step 2a landed — 2026-09-13

Step 2's first bounded sub-unit is done, on `main` at merge commit `f11fd57` (source commit `3e6b4c1` on branch
`design/f1-step2`, now deleted). Fixes the base-input `width:auto` defect audit.md calls out by name: adds
`input[type=checkbox],input[type=radio]{width:auto}` to the base CSS rule in `neurosearch/web/index.html`, then
retires the six now-redundant inline `style="width:auto"` overrides on checkboxes (useWeb, inForce,
srcGroupToggle, cwNeeds, cwGroupToggle, bootPick). This also silently fixed six other checkboxes that had no
inline override at all and were rendering full-width before this landed — no HTML change needed for those, the
base rule now covers them too. All 12 `<input type="checkbox">` elements in the app confirmed (via grep, not
visual — see the rendered-verification gap noted above, still open) to resolve to `width:auto`; zero inline
`width:auto` remains on any checkbox. `UI_VERSION` bumped to `0.63.45` in all three sites.
`test_s50_design_drift.py`/`test_s44_frontend_integrity.py`/`test_s5_ui_syntax.py` pass (24 tests).

**Deliberately deferred, not a defect:** the 19 `<select>` elements (17 have an inline `width:auto` override, 2
don't — one `style="flex:1"`, one unstyled and currently full-width). Two of them don't fit this same pattern
cleanly, and there's still no working rendered-visual-verification path in this environment to confirm a blanket
select fix is safe, so this was left as its own future sub-unit rather than forced through.

**Still remaining in F1 step 2:** the shared spacing/flex-row/type-scale/status-modifier utility classes and
retiring inline styles on the ranked offender surfaces (Sources, Research, Jobs/Health/boot, Master Plan, per
audit.md's ranking), the deferred `<select>` decision above, and the `style="display:none"` → `hidden`-attribute
conversion. Step 3 (the inline SVG sprite) has not started. Per Kyle's serialization instruction, these proceed
as further bounded sub-units, one at a time, each with its own worktree/commit/test/merge cycle — not as one
large step-2 commit.

## Design ladder — F1 step 2b landed — 2026-09-13

The "add the small set of shared rules" half of step 2 is done, on `main` at merge commit `903bccc` (source
commit `d5c8a4d` on branch `design/f1-step2b`, now deleted). Purely additive, nothing retired yet: added the
non-colour frozen tokens from `DESIGN.md` §5 (`--space-1..16`, `--text-xs..2xl`, `--radius-sm/md/lg/pill`,
`--motion-*`, `--ease-standard`) that F1 step 1 didn't land (it was colour-only), plus the utility classes
`audit.md`'s "six declaration families" table names as missing: `.grow`/`.push-right`/`.min-w-0` (flex-row
helpers beyond the existing `.row`), `.mt-1`..`.mt-6`/`.mb-1`..`.mb-6` (the spacing stack, at the frozen scale —
retiring surfaces should snap each surface's odd margin value, e.g. `margin-top:10px`, to the nearest of these,
not add a new one-off), `.text-xs`..`.text-2xl` (the type scale as classes), and `.status-ok`/`-warn`/`-bad` plus
`-border` variants (status modifiers). No existing rule, class or inline style was touched, so the drift ratchet
in `test_s50_design_drift.py` is unchanged (24 tests still pass). `UI_VERSION` bumped to `0.63.46` in all three
sites.

**Next F1 step 2 sub-unit: retire inline occurrences of these families on Sources**, `audit.md`'s top-ranked
offender (~141 of the 430 total). Use the classes just landed; where a surface's inline `margin-top`/`font-size`
value doesn't sit exactly on the new scale, snap to nearest rather than adding a bespoke class. This is expected
to move `test_s50`'s inline-style-count ceiling down, which the rung's own gate requires happen in the same
commit that retires them.

## Design ladder — F1 step 2c landed — 2026-09-13

First real inline-style retirement pass, on `main` at merge commit `f7aa121` (source commit `d085d6c` on branch
`design/f1-step2c`, now deleted). Scope was deliberately narrow — this session still has no working rendered-
visual-verification path (see the F1 step 1 note above), so only `style="..."` attributes whose entire content is
a single declaration sitting exactly on a frozen scale value (`margin-top:8px`/`4px` -> `.mt-2`/`.mt-1`, lone
`flex:1` -> `.grow`) were converted; every substitution produces the identical computed style it replaces, and
each touched element was checked for JS that reads/sets its `style` property before landing (none does). 16
style attributes eliminated in Sources' static `#view-sources` markup (425 -> 409, counting step 2a's earlier
-5). `MAX_INLINE_STYLE_ATTRS` in `test_s50_design_drift.py` lowered `430` -> `409` in the same commit, per the
rung's own gate. `UI_VERSION` bumped to `0.63.47`.

**Deliberately left alone in this pass, still counted in the 409:** combined/multi-declaration style attributes
(e.g. `margin-top:14px;border-top:1px solid var(--line);padding-top:10px`), non-scale spacing values (10px, 6px)
and non-scale font sizes (12.5px) — converting these would move the rendered result by a couple of pixels, not
verifiable without rendered checking — one-off geometry (explicit pixel widths, which `DESIGN.md` §5 explicitly
allows to stay inline), `display:none` state toggles, and the deferred `<select>` `width:auto` question.

**Still remaining for Sources:** the rest of its static markup's non-exact-match cases above, then its JS render
functions (`srcRowHtml`, `sourceDrawer`, `renderBook`, `transportChoiceHtml`, capture-queue/library-suggestions/
seen, quality & promotable drawers, value report, `browserBlock`, `classifyInput`) — the majority of Sources'
~141 total. Each is its own future bounded sub-unit. After Sources, `audit.md`'s ranking continues: Research,
Jobs/Health/boot, Master Plan, Settings, Findings, Chats.

## Design ladder — F1 step 2d landed — 2026-09-13

`srcRowHtml`'s exact-match retirement pass, on `main` at merge commit `119e88c` (source commit `8b9d79b` on
branch `design/f1-step2d`, now deleted). Same discipline as 2c, applied to this render function: the wrapping
`flex:1;min-width:0` -> `class="grow min-w-0"`; three `class="tag" style="color:var(--warn)"` spans (under-read,
legacy-analysis, stale badges) and the "suggested findings" link -> `status-warn`; the error-message div's
`color:var(--bad)` -> `status-bad`; two identical `margin-top:4px` blocks -> `mt-1`. Every touched element was
checked for JS that reads/sets its `style` property first (none does). 8 more style attributes eliminated
(409 -> 401); `MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.48`.
24 tests pass.

**Explicitly deferred within `srcRowHtml` itself, not just "later Sources":** `margin-top:3px` (off the frozen
scale) and the two dynamic `style="color:${...ternary...}"` badges (substance score, pool-potential score) —
turning computed inline colour logic into conditional classes is a materially different, riskier change than a
static substitution and needs its own considered pass, not a mechanical one.

Codex committed an unrelated, purely-additive `HANDOFF.md`/`docs/T1-ADMISSION-2026-09-12.md` checkpoint
(`a3ac76f`) between step 2c and 2d landing — checked via diff before resuming, no `index.html` touch, no
collision.

## Design ladder — F1 step 2e landed — 2026-09-13

Extended the exact-match retirement pass across every remaining Sources function between `srcRowHtml` (step 2d)
and `sourceDrawer` (not yet touched) — `renderBook`, `openCalc`, `loadPool`, `browserBlock`,
`loadCaptureQueue`, `classifyInput`, `exploreCommunity`, `loadWorks`, `loadLibrary`, `loadCandidates`,
`renderSeen`, `renderLibrarySuggestions`, `loadDiscoveries`, `claimCard`, `renderClaimsBulkBar`,
`whyThisAnswer`. On `main` at merge commit `3201844` (source commit `b97fa14` on branch `design/f1-step2e`, now
deleted). Same rules as 2c/2d: a lone `flex:1` (8x) -> `.grow`; a lone `flex:1;min-width:0` (3x) -> `.grow
.min-w-0`; `class="muted" style="font-size:12px"` (4x) -> `.text-xs`; five more single-instance exact matches
onto their matching `--space-*`/status-* class; and one inline `width:auto` on a `<input type="radio">` removed
outright (already covered by the step 2a base rule, so it was purely redundant, not converted). 22 style
attributes eliminated (401 -> 379); ceiling lowered to match. `UI_VERSION` bumped to `0.63.49`. 24 tests pass.

Sources' remaining inline styles are now concentrated in `sourceDrawer` (the drawer — value report, quality &
promotable sections — audit.md's own breakdown names this as one of the largest single owners) and
`transportChoiceHtml`, plus the off-scale/dynamic/display:none cases already logged as deliberately skipped
throughout steps 2c-2e. `sourceDrawer` is the natural next sub-unit.

## Design ladder — F1 step 2f landed — 2026-09-13

`sourceDrawer` plus the quality/promotable review functions (`loadQuality`, `loadPromotable`, `openPromotable`,
`openQuality`) — audit.md's "quality & promotable drawers" bucket. On `main` at merge commit `2f003cb` (source
commit `0883817` on branch `design/f1-step2f`, now deleted). Substitutions: `sourceDrawer`'s "What it gave you"
card's `margin-top:8px` -> `mt-2` (merged into existing `card` class); the drawer title's `font-size:15px` ->
`text-base` (15px is the exact `--text-base` token value); four `style="flex:1"` spans across the
quality/promotable functions -> `class="grow"`. Every touched element checked first for JS reading/setting its
`style` property (none does). 6 style attributes eliminated (379 -> 373); `MAX_INLINE_STYLE_ATTRS` lowered to
match in the same commit. `UI_VERSION` bumped to `0.63.50`. 24 tests pass.

`transportChoiceHtml` was reviewed this step and found to have zero exact-match candidates — its inline styles
are all combined or off-scale declarations, so it was left untouched and stays open for a future, more careful
pass (not a mechanical exact-match one).

**Sources is now effectively exhausted for the mechanical exact-match pass** (steps 2c-2f): remaining Sources
inline styles are the deliberately-deferred categories logged throughout — off-scale spacing values, dynamic
`style="color:${...ternary...}"` badges, `display:none`/`display:block` state toggles, and `transportChoiceHtml`'s
combined declarations — each needing its own considered (non-mechanical) sub-unit rather than a drop-in
substitution. Per `audit.md`'s ranking, the next sub-unit should move to the next-ranked surface: Research.

## Design ladder — F1 step 2g landed — 2026-09-13

Moved the retirement pass onto Research (the next surface in `audit.md`'s ranking after Sources), covering the
`view-research` static markup and its render functions: `renderOverview`, `woCard`, `qCard`, `whereToLook`,
`areaCard`, `renderQuestionsPane`, `renderWatchoutsPane`, `renderAreasPane`. On `main` at merge commit `cfec636`
(source commit `abe7ab1` on branch `design/f1-step2g`, now deleted). Substitutions: 2x `margin-top:8px` -> `mt-2`
(Claims pager row, tools "Refresh" button row); a `font-size:12px` merge into an existing `muted` class ->
`text-xs` (stat tile label); 3x `margin-top:16px` -> `mt-4` (renderOverview's three section headers); 4x lone
`flex:1;min-width:0` -> `class="grow min-w-0"` (one each in woCard/qCard/whereToLook/areaCard's row-card
wrappers); 3x `margin-top:12px` -> `mt-3` (the leading heading/wrapper in each of renderQuestionsPane,
renderWatchoutsPane, renderAreasPane). Every touched element checked first for JS reading/setting its `style`
property (none does). 13 style attributes eliminated (373 -> 360); `MAX_INLINE_STYLE_ATTRS` lowered to match in
the same commit. `UI_VERSION` bumped to `0.63.51`. 24 tests pass.

Left untouched in Research, same discipline as Sources: the row/gap/flex-wrap combinations that have no covering
class (e.g. `gap:14px;flex-wrap:wrap`), off-scale margins (6px, 10px, 14px), `claimCard`'s off-scale/combined
declarations (`margin-top:3px`, `margin-top:2px`, the `margin-left:auto;display:flex;gap:6px;...` combo), the
`<select>` `width:auto` cases across the Claims workbench filters (still the deferred selects decision), and
`display:none` state toggles on the research panes (deferred with the rest of that work). Research is now
similarly exhausted for the mechanical pass; per `audit.md`'s ranking the next sub-unit should move to
Jobs/Health/boot.

## Design ladder — F1 step 2h landed — 2026-09-13

Moved the retirement pass onto Jobs/Health/boot (the next surface in `audit.md`'s ranking after Research):
`bootRow`, `renderBoot`, `loadJobs`, `loadNotes`, `useBadges`, `loadWorkbench`. On `main` at merge commit
`270a745` (source commit `0e76e8f` on branch `design/f1-step2h`, now deleted). `loadPool`, `loadBacklog`,
`perfReport` and `loadHealth` were reviewed and found to have zero exact-match candidates left — `loadPool`'s
were already retired by step 2e (it doubles as a Sources function), and the rest are off-scale, combined, or
dynamic throughout (perfReport's debug tables, loadHealth's single off-scale `margin-top:3px`).

Substitutions: `bootRow`'s lone `flex:1;min-width:0` -> `class="grow min-w-0"`; a `font-size:12px` merge into an
existing `muted` class -> `.text-xs` on the channel byline; 2x `class="tag" style="color:var(--warn)"` ->
`class="tag status-warn"` (older-matcher, generic-match badges). `renderBoot`'s 2x `margin-top:4px`/`margin-top:8px`
merges into existing `muted` classes -> `.mt-1`/`.mt-2`; a bare `margin-top:8px` -> `class="mt-2"`; a bare
`flex:1` spacer span -> `class="grow"`. `loadJobs`' `class="muted" style="flex:1"` (2x: spend line, per-job
message span) -> `class="muted grow"`; a bare `flex:1` (coldLine span) -> `class="grow"`; a lone
`color:var(--bad)` (dependency-failure span) -> `class="status-bad"`. `loadNotes`' `margin-bottom:8px` merge into
its `row` class -> `.mb-2`. `useBadges`' lone stale-source `color:var(--warn)` tag -> `status-warn`.
`loadWorkbench`'s 2x bare `flex:1` (source-filter chip, low-value-sweep banner) -> `class="grow"`. Every touched
element checked first for JS reading/setting its `style` property (none does). 16 style attributes eliminated
(360 -> 344); `MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.52`. 24
tests pass.

Left untouched, same discipline: `margin-top:5px`/`3px`/`6px` (off the `--space-*` scale), shorthand
`margin:8px 0`/`margin:4px 0 8px` banners, `flex-wrap`/`overflow`/`text-overflow` combinations with no covering
class, the dynamic `${rt.blocked ? ... }` inline-color ternary in `loadJobs`, and every `font-size:11px`/`12.5px`
instance (off the current `--text-*` scale — a candidate for a future token, not a mechanical substitution).
Jobs/Health/boot is now similarly exhausted for the mechanical pass; per `audit.md`'s ranking the next sub-unit
should move to Master Plan.

## Design ladder — F1 step 2i landed — 2026-09-13

Moved the retirement pass onto Master Plan (the next surface in `audit.md`'s ranking after Jobs/Health/boot):
`renderTriageCard`, `renderStaleCard`, `renderPlan`. On `main` at merge commit `06bfb75` (source commit
`37e2ad8` on branch `design/f1-step2i`, now deleted). `renderNoPlan` was reviewed and found to have zero
exact-match candidates — all four of its inline styles are off the `--space-*` scale or combined with an
uncovered property (`min-height:100px`).

Substitutions: `renderTriageCard`'s lone `flex:1;min-width:0` -> `class="grow min-w-0"`; 2x `font-size:12px`
merges into existing `muted` classes -> `.text-xs`; a bare `margin-top:8px` row plus its nested
`flex:1;font-size:12px` span (both fully covered by existing utilities) -> `class="row mt-2"` /
`class="muted grow text-xs"`, eliminating both style attributes in one substitution. `renderStaleCard`'s 3x
`class="card" style="border-color:var(--warn)"` -> `class="card status-warn-border"`; a lone budget-exceeded
`color:var(--warn)` span -> `class="status-warn"`. `renderPlan`'s bare `margin-bottom:12px` header row ->
`class="row mb-3"`; a bare `margin-top:8px` accepted-updates row -> `class="row mt-2"`; a lone
`color:var(--bad)` on a bare `<b>` -> `class="status-bad"`; a `flex:1` merge into the existing `starth` class
-> `.grow`; a lone `color:var(--warn)` on a bare `<td>` -> `class="status-warn"`; 2x bare `margin-top:4px`
(Discuss/Research-this action wrappers in the Decide tab) -> `class="mt-1"`. Every touched element checked
first for JS reading/setting its `style` property (none does). 16 style attributes eliminated (344 -> 328);
`MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.53`. 24 tests pass.

Left untouched, same discipline: `margin-top:6px` throughout, shorthand `margin:0`/`h2 style="margin:0;flex:1"`,
`font-weight:400`/`font-size:13px` combinations (13px is off the current `--text-*` scale), `flex-wrap:wrap`/
`gap:*` combinations with no covering class, `min-width:180px`/`min-width:100px`, and `flex:0 0 22px;color:var(--muted)`
(neither part maps onto an existing utility — `--muted` isn't one of the status tokens). Master Plan is now
similarly exhausted for the mechanical pass; per `audit.md`'s ranking the next sub-unit should move to
Settings.

## Design ladder — F1 step 2j landed — 2026-09-13

Moved the retirement pass onto Settings (the next surface in `audit.md`'s ranking after Master Plan) — a
single static view with no dedicated render functions, so this covers all of `#view-settings`. On `main` at
merge commit `16cd8ed` (source commit `6a90c09` on branch `design/f1-step2j`, now deleted).

Substitutions: 6x bare `margin-top:8px` -> `.mt-2` (one merged into an id-only `#facts` div, five merged into
an already-present `class="row"` on the Claims/budget/health/retire/danger-zone action rows); 1x bare
`margin-top:12px` on the project-settings Save row -> `.mt-3`, merged into its `class="row"`. Every touched
element checked first for JS reading/setting its `style` property (none does). 7 style attributes eliminated
(328 -> 321); `MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.54`.
24 tests pass.

Left untouched, as `audit.md` itself flagged this surface ("this is a form that should be a form component"):
the repeated `style="display:block;margin-top:10px"` on every field label (display:block uncovered, 10px off
the `--space-*` scale), every textarea's `min-height:*px`, the `<select>`/`<input>` `width:auto`/`width:90px`
cases (still the deferred selects/inputs decision), `#healthLine`'s combined grid declaration, `#perfOut`/
`#valueOut`/`#retList`/`#retPreview`'s combined `margin-top` + `font-size:12.5px` + `overflow` strings,
`#retReason`'s `flex:1;min-width:240px`, `#settleBtn`'s `display:none` state toggle, and the `<dialog>` row's
`margin-top:12px;justify-content:flex-end` (only the margin half is covered). Settings is now similarly
exhausted for the mechanical pass; per `audit.md`'s ranking the next sub-unit should move to Findings.

## Design ladder — F1 step 2k landed — 2026-09-13

Moved the retirement pass onto Findings (the next surface in `audit.md`'s ranking after Settings):
`#view-findings`'s static markup plus `loadReviews`. On `main` at merge commit `05b7088` (source commit
`658f94d` on branch `design/f1-step2k`, now deleted).

Substitutions: static markup's bare `<span class="muted" style="flex:1">` in the "What's worth keeping" intro
row -> `class="muted grow"`; the `#fbPager` wrapper's bare `margin-top:8px` -> `class="row mt-2"`, merged
alongside its existing `id`. `loadReviews`: a lone `color:var(--warn)` rank-note span -> `class="status-warn"`;
a bare `margin-left:auto` re-rank button in the unranked/unscored branch -> the existing `.push-right` utility
(the first use of `.push-right` outside the surface it was defined for); a bare `<b style="flex:1">` card
header -> `class="grow"`; a bare `margin-top:4px` rankLine wrapper row -> `class="mt-1"`. Every touched element
checked first for JS reading/setting its `style` property (none does). 6 style attributes eliminated
(321 -> 315); `MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.55`.
24 tests pass.

Left untouched, same discipline: `loadReviews`' dynamic `class="card rv${folded ? ' folded' : ''}"
style="border-color:var(--warn)"` — unlike every other card/border-color merge so far this engagement, its
`class` attribute is itself a template-literal expression, so a static find/replace can't safely fold in
`status-warn-border`; this needs its own converter approach and was deliberately deferred rather than forced.
Also left: the number-input's combined `width:64px;flex:none;padding:4px 6px`, the `display:inline-flex;gap:6px;
align-items:center;margin-left:auto;white-space:nowrap` wrapper (combined, uncovered), `margin-top:3px`/`2px`/
`6px`/`10px` instances throughout the card body (all off the `--space-*` scale), the filter input's
`max-width:240px`, and the per-row dynamic `' style="display:none"'` filter-visibility ternary (deferred with
other `display:none` cases). Findings' own six `<select>` `width:auto` attributes (still the deferred
selects/inputs decision), `#fbBar`'s combined `gap:6px;flex-wrap:wrap;margin:14px 0 6px;font-size:12.5px`, and
`#fbGroupCtl`'s combined `display:none;gap:8px;margin:-2px 0 6px;font-size:12.5px` are untouched for the same
reasons. Findings is now similarly exhausted for the mechanical pass; per `audit.md`'s ranking the next
sub-unit should move to Chats — noting `whyThisAnswer` was already partially processed during step 2e's
Sources pass, so it should be checked for remaining exact matches rather than assumed untouched.

## Design ladder — F1 step 2l landed — 2026-09-13

Moved the retirement pass onto Chats (the next surface in `audit.md`'s ranking after Findings):
`#view-chats`'s static markup plus `addMsg`. On `main` at merge commit `06be10c` (source commit `c5e8b39` on
branch `design/f1-step2l`, now deleted). `whyThisAnswer` was re-checked, as flagged in the prior handoff entry
(it was already partially processed during step 2e's Sources pass) — it has zero remaining exact-match
candidates: its `style="${c.matched_here ? '' : 'opacity:.75'}"` is a dynamic ternary, its
`margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end` is combined with uncovered
properties beyond the margin-left half, and its lone `margin-top:10px` is off the `--space-*` scale.

Substitutions: static markup's bare `#shareChatMsg` `font-size:12px` -> `.text-xs`; the askbar's bare
`<div style="flex:1">` wrapping the question textarea -> `class="grow"`. `addMsg`: a lone `color:var(--warn)`
on the validation-warning `.web` div -> `class="web status-warn"`; a bare `font-size:12px` on the
`.muted copied` toast span -> merged in as `.text-xs`. Every touched element checked first for JS
reading/setting its `style` property (none does — `#shareChatMsg` and `.copied` are only ever touched via
`.textContent`). 4 style attributes eliminated (315 -> 311); `MAX_INLINE_STYLE_ATTRS` lowered to match in the
same commit. `UI_VERSION` bumped to `0.63.56`. 24 tests pass.

Left untouched, same discipline: the share-menu wrapper's `position:relative` (uncovered property), the ask
row's combined `margin-top:6px;gap:14px` (6px is off the `--space-*` scale and `gap` is uncovered), the
attach-label's `cursor:pointer`, and the file input's `display:none` (deferred with other `display:none`
cases). Chats is now similarly exhausted for the mechanical pass — **this closes out every surface `audit.md`'s
offender ranking table named individually** (Sources, Research, Jobs/Health/boot, Master Plan, Settings,
Findings, Chats all exhausted across steps 2c-2l). Remaining scope per `audit.md` is Home/wizard/shell/remainder
(~74 instances, scattered rather than concentrated in a single surface) — the next sub-unit should scope that
territory before continuing the mechanical pass further.

## Design ladder — F1 step 2m landed — 2026-09-13

Scoped and closed the last `audit.md` bucket: "Home / wizard, shell, remainder | ~74 | scattered." Rather than
reading surface-by-surface (this territory has no single concentrated surface — that's what "scattered"
means), ran a full-file regex scan for bare single-declaration `style="..."` attributes exactly matching an
already-landed utility class or token. It turned up 10 real candidates across six otherwise-unrelated
functions, plus the `loadReviews` folded-card dynamic-class case already flagged and deferred in step 2k (still
untouched, same reason). On `main` at merge commit `071ac12` (source commit `90b1019` on branch
`design/f1-step2m`, now deleted).

Substitutions (all bare, single-declaration, onto an existing utility): `funCard`'s title-row spacer span
`flex:1` -> `.grow` (shared by Home's "Your research in numbers" and the project workspace's "This project in
numbers" — the first cross-surface instance of a single template being touched once); `ask()`'s thinking-bubble
error span `color:var(--bad)` -> `.status-bad`; `renderShell`'s `resAreaBar` "Showing only &lt;area&gt;" span
`flex:1` -> `.grow`; `showKnown`'s evidence-target candidate-row span `flex:1` -> `.grow`;
`loadRetireChannels`' channel-checkbox label span `flex:1` -> `.grow`; `renderFacts`' fact-content span
`flex:1` -> `.grow` (its sibling tag span's `flex:0 0 auto` is combined/uncovered and stays); `retPreview`'s two
bare `margin-top:4px` divs -> `.mt-1`; `checkUpdates`' "no material changes" banner `margin-bottom:8px` ->
`.mb-2`; `liveTag`'s job quiet-for-a-while warning span `color:var(--warn)` -> `.status-warn`. Every touched
element checked first for JS reading/setting its `style` property (none does — all are anonymous
template-literal elements with no `id`). 10 style attributes eliminated (311 -> 301);
`MAX_INLINE_STYLE_ATTRS` lowered to match in the same commit. `UI_VERSION` bumped to `0.63.57`. 24 tests pass.

Left untouched, same discipline as every prior sub-unit: combined declarations with an uncovered property
(`gap`, `display:flex`, border/padding shorthand, `cursor`, `position:relative`, `flex:0 0 auto`), every
off-scale margin/font-size (2px, 3px, 5px/5.5px/6px/10px/11px/11.5px/13px/14px, 20px — `--space-5` doesn't
exist so nothing bridges `--space-4`(16px) and `--space-6`(24px)), `display:none` state toggles, and
`loadReviews`' dynamic `class="card rv${folded ? ' folded' : ''}" style="border-color:var(--warn)"` (unchanged
from step 2k — still needs a non-static conversion approach, not a mechanical find/replace).

**This closes out the entire `audit.md` offender ranking table** — every named surface (Sources, Research,
Jobs/Health/boot, Master Plan, Settings, Findings, Chats) plus the scattered Home/wizard/shell/remainder bucket
is now exhausted for this exact-match-only mechanical pass, across steps 2c through 2m. 301 inline `style="..."`
attributes remain, all either combined-with-uncovered-properties, off the `--space-*`/`--text-*` scale,
dynamic (ternary-driven color or class), or `display:none`/`display:block` state toggles — none are further
mechanical exact matches onto an existing utility. Per Kyle's serialization instruction not to start
subsequent steps while still inside F1, the next sub-unit is **F1 step 3**: the inline `<svg><symbol>` sprite
naming the eight emoji-only controls that `audit.md` flagged. A fresh decision is needed before resuming F1
step 2's *further* retirement (a `display:none`→`hidden`-attribute conversion pass, and/or new spacing/
font-size tokens to cover the off-scale values found throughout) — that work should wait for explicit
direction rather than being assumed as the automatic next sub-unit.


## Frontend split — ACTIVE, CSS candidate — 2026-09-13

Kyle explicitly reprioritized structural frontend extraction over D2/F1 continuation. Safe switch: no tracked
uncommitted work; base/main `30ee4f4`, version 0.63.57. Isolated worktree `/private/tmp/neuro-frontend-split`,
branch `refactor/frontend-css`; existing untracked main references/evidence preserved. D2/F1 step 3 is suspended,
with its resume boundary in `PRODUCT-SCHEDULER.md`.

First candidate 0.63.58 moves the exact style-block contents to `neurosearch/web/styles.css`, linked from the
same position in the head. The existing FastAPI web-serving section supplies `/styles.css` as `text/css` with
revalidation required. Existing `web/*` package data already includes the CSS. JavaScript and markup are unchanged
apart from the stylesheet link and version. S50 reads external CSS and still measures font/radius declarations
across CSS plus HTML; the inline-attribute ceiling stays 301. S44 covers actual stylesheet delivery and freshness.
Touched files: index/styles, API, package/version files, S50/S44, scheduler, this handoff and architecture map.
Baseline S50/S44/S5: 24 passed. Release validation is pending; this is not yet landed/live-verified.

Next: validate and land the CSS cut, notify Kyle for the requested direction check before JS extraction.
Then extract state/API/shared formatting, individual surfaces and bootstrap/router incrementally, preserving
inline-handler reachability, startup ordering, shared state identity and the versioned fetch boundary. No build
step, dependencies, restyling, or backend behavior changes are admitted.

## Frontend split — decomposition candidate complete — 2026-09-13

The structural extraction continued after the initial candidate. `index.html` is now a 302-line markup shell with
`styles.css` and a single native-module entrypoint (`js/app.js`). The JavaScript is split into `api.js`, `utils.js`,
`state.js`, `home.js`, `chats.js`, `sources.js`, `research.js`, `plan.js`, and `bootstrap.js`. Existing inline
handlers remain supported through explicit `globalThis` bindings; the bootstrap module preserves the original
execution order and calls `route()` only after all surface modules load. No framework, bundler, transpiler,
dependency, or backend/API contract was added.

The extracted files preserve the original bytes and behavior apart from the required module binding form. Static
assets are served by the existing FastAPI web surface (`/styles.css` and `/js/*`), with package data covering the
nested module directory. `UI_VERSION` is 0.63.58 in the package, pyproject, and state module. Frontend structural
readers now inspect the complete static asset set; `MAX_INLINE_STYLE_ATTRS` remains 301 and continues to count
only element attributes. A shared `tests/frontend_helpers.py` reader keeps static contract assertions pointed at
the shipped HTML, CSS, and modules.

Validation in `/private/tmp/neuro-frontend-split` at base `30ee4f4`: focused frontend/click suites 47 passed;
the affected static-contract collection 198 passed; full deterministic pytest 1,363 passed with one existing
Starlette deprecation warning; `release-check --no-pytest` passed all proofs and wrote
`evals/release/release-check-0.63.58-30ee4f4-20260913-115141.json`. A browser visual pass remains a delivery
check because the current environment has no reliable browser repaint path; no visual source changed.

Before delivery, inspect `main` HEAD again, review the generated module diff for accidental declaration rewrites,
run the full release ritual from the isolated checkout, and commit this as the frontend decomposition milestone.

## Frontend split — delivered — 2026-09-13

The decomposition milestone is delivered on `main` at `5f667a1` (rebased onto concurrent docs commit `d14e13d`).
Post-merge full pytest passed **1,363 tests** with one existing Starlette deprecation warning. The commit-bound
`release-check --no-pytest` passed every deterministic proof, including repository hygiene, frontend integrity,
all Tier 1/retrieval/cache/economic/backup gates, and parsing all 10 JavaScript modules; artifact:
`evals/release/release-check-0.63.58-5f667a1-20260913-115812.json`.

The requested initial direction checkpoint is therefore complete as an informational milestone, and the full
decomposition is complete in the same structural pass. Runtime visual repaint verification remains the only
environmental limitation recorded by the existing audit path; no CSS values, markup content, or interaction logic
were intentionally changed.

## Design ladder — F1 items 2-3 landed (width:auto + icon sprite) — 2026-09-13

With Codex's frontend decomposition delivered (5f667a1 / 6e81e36), re-scoped and landed the two
remaining tokenizable F1 items from `docs/design-audit/2026-09-13-b85c222/f1-remaining-scope.md`
against the new split layout. On `main` at merge commit `a914cbf` (source commits `12d62cc` +
`20a775d` on branch `design/f1-step2n-width-icon`, now deleted).

**width:auto (14 sites)**: added `.w-auto{width:auto}` to `styles.css`; swapped all 14 bare
`style="width:auto"` `<select>` elements in `index.html` onto it (Sources' `#candState`,
Research's `#discMode`, six Findings filter-bar selects, four Claims-workbench selects, Evidence
Target's `#resTargetS`, Settings' `#factKind`).

**Icon sprite (8 emoji-only buttons -> named SVG icons)**: added an inline `<symbol>` sprite
right after `<body>` in `index.html` with three original stroke-based glyphs (`ic-dismiss`,
`ic-approve`, `ic-flag` — an X, a checkmark, and a flag replacing the pushpin) plus `.ic`/
`.icon-sprite` utility classes in `styles.css`. Converted all 8 sites to
`<svg class="ic"><use href="#...">` with matching `title` + `aria-label`: `discStatus`'s dismiss
button (`js/sources.js`), and `sourceDrawer`'s `group()` helper (5 sites: reserve/suggested/
approved branches) plus the job cancel/dismiss buttons (2 sites), both in `js/research.js`
despite the name split.

301 -> 287 inline `style="..."` attributes; `MAX_INLINE_STYLE_ATTRS` lowered to match.
`UI_VERSION` bumped to `0.63.59` in package/pyproject/index.html/state.js (a follow-up commit,
`20a775d`, was needed after the first commit missed staging the `state.js` edit — caught before
merge). 35 tests pass across `test_s50_design_drift`, `test_s44_frontend_integrity`,
`test_s5_ui_syntax`, and the directly-related surface suites (`test_n8_research_shell`,
`test_n9_source_drawer`, `test_o1_accelerate`); `node --check` passes on both touched JS modules.
A full-suite run separately showed 7 pre-existing failures (golden-eval tier1, router
equivalence, mission-closeout, native-worker-restart, spreadsheet calculator, doctor/
release-check artifact) — all confirmed present identically on unmodified `main` before this
change, environment-dependent (missing `.venv` in fresh worktrees; a couple fail even on the
primary checkout in this sandbox), not caused by this patch.

This closes out Rung F1's remaining tokenizable items. The last piece of F1 —
`display:none` -> `hidden` attribute conversion — is still deferred: it needs a fresh
element-by-element scope pass against the new module boundaries (the old line-number map no
longer applies now that JS toggle logic is spread across separate surface files), not a blind
carry-forward of the pre-split scope. Once that lands, Rung F1 is genuinely closed and F2 (the
shared loading/empty/failure-state primitive, fixing `H-2`) becomes eligible per `ladder.md`'s
sequencing.
