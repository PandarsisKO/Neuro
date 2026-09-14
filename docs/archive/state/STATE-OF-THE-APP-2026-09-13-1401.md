# State of the App — 2026-09-13 14:01 PT

This checkpoint is the current orientation source. It supersedes earlier State-of-the-App files for current status;
historical files remain evidence only.

## Mission and execution boundary

The governing mission is to make Neuro Search reliable, fast, economical, recoverable, and easier to extend before
expanding product scope. Foundation Phases 0–10 are complete. Transcript Intelligence follows Foundation, with T1
complete and T2 awaiting its design/state-model admission gate.

Claude owns Audit/Design and frontend surfaces. Codex owns backend, reliability, measurement, recovery, and
Transcript Intelligence infrastructure. Shared `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` remain
append-only: read the latest checkpoint, append evidence, and commit immediately. Concurrent work must use disjoint
branches/worktrees and must never overwrite another agent's changes.

## Current repository and runtime

- `main` is at `ed52a59`; the application is version `0.63.63`.
- W1 steps 1 and 2 are released. The latest changes add cost disclosure/restore parity and make Plan's rebuild
  label match Findings.
- Full pytest passed 1,364 tests; the commit-bound release gate passed with the existing Starlette deprecation
  warning only.
- Authenticated runtime verification reports `fake_ai=false`, zero queued/running/stale/leased/external-pending
  jobs, full backup `integrity: ok`, and 38,038 chunks.
- Claims remains paused. Two historical unsettled batches contain 36 collected-but-unwritten results and remain
  deliberately untouched.
- The compact GitHub safety snapshot is maintained on `backup/2026-09-13-clean`; normal `main` push remains blocked
  by retired historical `VIDEOS/` blobs. `VIDEOS/`, `data/`, and `_to_delete/` are not tracked.

## Active and next work

There is no admitted Codex-owned implementation rung at this checkpoint. The next evidence boundary is Claude's
human/browser re-score for F2 and W1. F2's deterministic implementation is released, but its first-paint loading,
clear-on-data, clear-on-error, and explicit failed-state browser evidence remains open. W1's remaining scope is the
Sources/Chats/Findings/Plan human scorecard and any label changes justified by that pass. W2 follows only after W1's
gate closes.

The design sequence is:

`F0 → F1 → F2 → W1 → W2 → W3 → W4 → W5 → RE-AUDIT → C1 → P1`.

F0, F1, and the F2 implementation are complete; W1 code steps 1–2 are complete. W2–P1 remain queued behind the
named gates in `docs/design-audit/2026-09-13-b85c222/ladder.md`.

Codex must not start T2 until its design/state-model gate exists and ownership is clear. R8 retention remains
observational until 2026-10-11 17:28 PT. R9(c) long-window local extraction remains behind its documented numeric
trigger. No rejected experiment or parked product expansion is reopened without its trigger.

## Completed Foundation and Transcript Intelligence evidence

R4 durable work units, the R4 abuse gate, R5 bounded concurrency, the R5 concurrency gate, R6 fast-first-wave,
R7 novelty/residual reading, the Foundation closeout, full-backup SQLite integrity checks, the FTS5 recovery seam,
test-isolation cleanup, and the findings-quality 12M ceiling are released and documented in `HARDENING.md` and
`HANDOFF.md`.

T1's derived-vector metadata, fail-open helpers, low-lane backfill, corpus attestation, 73,037-attempt cohort, and
semantic coverage measurement are complete in the existing production embedding space. R9(a)'s `bge-m3` result is
reserved for a separately gated future full-space migration; R9(b)'s Llama 3.1 8B short-classification decision is
complete.

## Safe continuation

The next agent should read this file, then `DEVELOPMENT-OPERATING-SYSTEM.md`, `CLAUDE.md`, the latest entries in
`HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md`. If Claude's browser evidence has landed, inspect the exact
commit and run the affected gates. If no new evidence exists, do not invent a Codex rung: preserve the ownership
boundary and wait for the T2 admission gate or a measured backend/reliability trigger.

## Operational verification addendum — 2026-09-13 14:08 PT

The editable virtualenv was refreshed from the repository metadata; `neurosearch doctor` now passes the installed
package/version check at `0.63.63`. `neurosearch repo-check` passes with no findings. Doctor still reports historical
structured-output, ambiguous-execution, model-substitution, network, and optional-Reddit-credential warnings; those
are retained as provenance and do not represent a newly admitted implementation rung.
