# State of the App — 2026-09-12 16:45 PT

This is the current orientation source. It supersedes `STATE-OF-THE-APP-2026-09-12-1510.md`.

Foundation R4–R7 and the formal closeout are complete. R8 retention remains a deliberate, non-destructive deferral
until after 2026-10-11 17:28 PT. R9(a) and R9(b) are complete. R9(c) was explicitly deferred at 16:38 PT because the
external 70B pull stalled beyond a 99-hour ETA; revisit only with the same approximately 15k-token fixture, valid
`findings` and `claims` arrays, and total latency below 10.9 seconds.

T1 is now the active implementation mission. The first slice is in commits `8acbb9d`, `23a7f64`, and `0c3d8e0`:

- versioned embedding metadata and additive migrations for `project_notes` and `project_claims`;
- canonical, dimension-checked, fail-open vector read/write/invalidation helpers;
- a low-lane durable `t1_embed_derived` job and resumable enqueue adapter;
- a read-only `/api/projects/{id}/transcript/coverage` endpoint that reports `measurement_pending` until corpus-space
  attestation exists;
- six focused tests in `tests/test_t1_vector_metadata.py`.

No live database was opened, queried, changed, or re-embedded. Claude’s uncommitted Bootstrap/resources/UI work and
design audit assets remain preserved and separate; do not overwrite or stage them without reviewing the coherent set.

Next T1 work is corpus-space attestation, content/revision freshness keys, locator reconciliation, project-relative
distribution measurement, and a fresh version-stamped cohort. T2’s persisted coverage states and any UI state model
remain out of scope until that measurement gate passes.

Read this file, `DEVELOPMENT-OPERATING-SYSTEM.md`, `PRODUCT-SCHEDULER.md`, `docs/T1-ADMISSION-2026-09-12.md`, and
`HANDOFF.md` before the next session. Protected local paths remain `data/`, `VIDEOS/`, and `_to_delete/`.
