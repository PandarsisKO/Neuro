# State of the App — 2026-09-12 17:15 PT

This is the current orientation source and supersedes the 17:05 state file.

Foundation R4–R7 is complete. R8 retention remains a non-destructive deferral until after 2026-10-11 17:28 PT.
R9(a)/(b) are complete; R9(c) is explicitly deferred after its 70B pull stalled. The exact revisit trigger remains:
the same approximately 15k-token fixture, valid `findings` and `claims` arrays, total latency below 10.9 seconds.

T1 measurement work is active. The current implementation includes versioned derived-vector metadata, canonical
fail-open helpers, revision-aware low-lane deduplicated backfill jobs, measured corpus-space attestation, a
project-relative similarity distribution engine, and the read-only coverage endpoint. The latest T1 tests pass **9/9**.

Validation at this checkpoint: full pytest **1,345 passed, one existing Starlette warning, 171.90s**; full deterministic
release-check **PASS in 231.5s** (artifact `evals/release/release-check-0.63.43-7f631c6-20260912-171335.json`).
No live database was opened, queried, changed, or re-embedded. Claude’s uncommitted runtime/UI/design batch remains
preserved separately.

A fresh read-only cohort across all 13 visible projects is recorded at
`evals/t1/cohort-20260912-1718.json`; all reports correctly remain `measurement_pending` until attestation is admitted.
Remaining T1 acceptance work is the explicit attestation measurement, a version-stamped semantic cohort, and evidence
review on real project data through the supported app path. T2 persisted coverage states and UI work remain out of scope
until that cohort passes.

Read this file, `DEVELOPMENT-OPERATING-SYSTEM.md`, `PRODUCT-SCHEDULER.md`, `docs/T1-ADMISSION-2026-09-12.md`, and
`HANDOFF.md` before resuming. Protected paths remain `data/`, `VIDEOS/`, and `_to_delete/`.
