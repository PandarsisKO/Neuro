# State of the App — 2026-09-12 17:05 PT

This supersedes `STATE-OF-THE-APP-2026-09-12-1645.md`.

Foundation R4–R7 is closed. R8 retention remains a non-destructive deferral until after 2026-10-11 17:28 PT. R9(a)
and R9(b) are complete. R9(c) is explicitly deferred after its 70B pull stalled; revisit only with the same
approximately 15k-token fixture, valid `findings`/`claims` arrays, and total latency below 10.9 seconds.

T1 first-slice implementation is in commits `8acbb9d`, `23a7f64`, `0c3d8e0`, `aab00b9`, and `eec5de0`:

- versioned metadata plus canonical fail-open vector read/write/invalidation;
- low-lane durable, deduplicated backfill jobs;
- measured corpus-space attestation for legacy chunk vectors;
- project-relative Claim/Finding-to-chunk similarity distributions with separate locator counts;
- read-only coverage endpoint with an explicit pending state;
- seven focused T1 tests.

The full pytest suite passed **1,342 tests, one existing Starlette warning, 157.74s**. The full deterministic
release-check passed **228.1s** with experimental flags off. No live database was opened, queried, changed, or
re-embedded. Claude’s uncommitted Bootstrap/resources/UI and design audit material remains preserved separately.

Next incomplete T1 work is content/revision freshness keys and a fresh version-stamped measurement cohort with evidence
review. T2 persisted coverage states and UI work remain out of scope until that gate.

Read this file, `DEVELOPMENT-OPERATING-SYSTEM.md`, `PRODUCT-SCHEDULER.md`, `docs/T1-ADMISSION-2026-09-12.md`, and
`HANDOFF.md` before resuming. Protected paths remain `data/`, `VIDEOS/`, and `_to_delete/`.
