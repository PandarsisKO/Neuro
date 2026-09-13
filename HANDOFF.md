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

The worktree contains a preserved, uncommitted Claude-side Bootstrap, resources, UI and test set
(`neurosearch/bootstrap.py`, `neurosearch/resources.py`, `neurosearch/web/index.html`, `tests/test_k3_resources.py`,
`tests/test_s14_fix_pass.py`); its focused suite is 73 passed. Do not stage or overwrite that set while continuing
R9/T1. `AUDIT.md` and `DESIGN.md` are no longer untracked oddities: they are the canonical, tracked design
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
