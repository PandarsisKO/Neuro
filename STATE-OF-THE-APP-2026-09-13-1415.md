# State of the App — 2026-09-13 14:15 PT

This is the newest orientation source and supersedes earlier State-of-the-App files for current status. Historical
snapshots remain archived evidence.

## Current release and custody

- `main` is `178d64d` (the W1 step-3 release plus documentation-only archive cleanup); the released application is
  UI/package version `0.63.64`.
- Claude's W1 step 3 is landed: both Sources re-rank controls disclose that they score titles/descriptions against
  the brief and use the model budget.
- The focused W1 step-3 suite passed 28 tests. Commit-bound `release-check --no-pytest` passed every deterministic
  proof; artifact: `evals/release/release-check-0.63.64-307b593-20260913-141519.{json,txt}`.
- The last full pytest baseline is 1,364 passed on the 0.63.63 tree; the step-3 diff is frontend-only and its
  affected focused suite is green.
- `repo-check` passes. The compact GitHub safety snapshot is maintained on `backup/2026-09-13-clean` with a tree
  identical to `main`; `VIDEOS/`, `data/`, and `_to_delete/` are absent from tracked files.

## Mission boundary

Foundation Phases 0–10 and Transcript Intelligence T1 are complete. R8 retention remains observational until
2026-10-11 17:28 PT. R9(c) remains behind its numeric trigger. Claims remains paused; historical unsettled batch
results remain untouched.

Claude owns the open F2/W1 browser and human re-score. W1 code steps 1–3 are complete; no further code-only W1
disclosure change is admitted without that visual pass. The design sequence remains:

`F0 → F1 → F2 → W1 → W2 → W3 → W4 → W5 → RE-AUDIT → C1 → P1`.

Codex has prepared, but not self-admitted, `docs/T2-ADMISSION-2026-09-13.md`. It defines the seven-state derived
coverage view, reconciliation invariants, project-relative thresholds, and release gates. T2 implementation waits
for review of those state semantics; it must not add a UI, new table, provider call, or live-data mutation first.

## Safe continuation

The next agent should read this file, `DEVELOPMENT-OPERATING-SYSTEM.md`, `CLAUDE.md`, `HANDOFF.md`,
`PRODUCT-SCHEDULER.md`, `HARDENING.md`, and the T2 admission proposal. If the T2 semantics are accepted, implement
only the existing T1 coverage seam and run its named gates. Otherwise preserve the proposal and ownership boundary;
do not invent a parallel Codex rung or reopen parked work.
