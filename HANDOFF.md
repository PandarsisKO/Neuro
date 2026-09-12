# HANDOFF — shared Codex / Claude delivery mechanics

## Start here

1. Find every `STATE-OF-THE-APP-YYYY-MM-DD-HHMM.md`; read the newest timestamp.
2. Read `DEVELOPMENT-OPERATING-SYSTEM.md` for Kyle's governing workflow, and `CLAUDE.md` for standing invariants.
3. Read `FOUNDATION-HANDOFF.md` for changes, validation, delivery status and the exact restart point.
4. Read only the active rung and relevant tests/HARDENING entries. `PRODUCT-SCHEDULER.md` owns priorities.

The active program is Foundation. Transcript Intelligence follows its formal closeout. External AI access, expanded Research/Discover/Planner, additional Bootstrap and unrelated Findings redesign are parked. Old declarations of a current mission are historical evidence only.

Current execution state: 0.63.40 is observed through `/api/version` with `fake_ai=false`. Commit `3af9c37` implements
R4 durable Findings windows and Claims groups; its full suite, Tier 1, bound release-check and consolidated 66-case
abuse gate pass. R4 is closed and R5 bounded concurrency is active.

## Shared checkout and coordination

The Mac checkout is `/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO`. Codex works directly on this Mac; historical VM/device-bridge/tar delivery instructions DO NOT apply here. Claude was dormant when Kyle confirmed coordination on 2026-09-11.

Before editing, inspect current Git state and the Foundation handoff. Record the base commit, isolation path and touched files. Before delivery, compare against that base; preserve other changes and reconcile overlap instead of overwriting it. Never reset, broadly stage, remove Git locks, or delete files as a delivery shortcut. Do not assume a clean tree solely because an older handoff says so.

Current custody note: `.git/index.lock` is absent and `git ls-files 'VIDEOS/**'` returns zero files. The recordings
remain on local disk and are excluded from Git/GitHub. Do not add `VIDEOS/`, `data/` or `_to_delete/` to a snapshot.

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
