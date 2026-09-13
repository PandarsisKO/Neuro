# State of the App — 2026-09-12 17:20 PT

This is the current orientation source and supersedes the 17:15 state file.

Foundation R4–R7 is complete. R8 retention remains a non-destructive deferral until after 2026-10-11 17:28 PT.
R9(a)/(b) are complete; R9(c) is explicitly deferred after the stalled 70B pull, with the exact 15k-token,
valid-shape, `<10.9s` revisit trigger preserved in the pre-T1 audit.

T1 now has an admitted production corpus-space attestation through the authenticated app route: provider `openai`,
model `text-embedding-3-small`, 1,536 dimensions, 37,583 vectors, zero malformed rows, preparation tag
`t1-production-space-20260912`. The read-only cohort is `evals/t1/cohort-20260912-1719.json`; all 13 projects are
`ready_for_measurement`, but derived-vector counts are zero because no paid backfill has been queued or run.

The T1 engine and its nine focused tests are complete. The remaining acceptance item is an explicitly authorized,
low-lane derived-object backfill followed by a version-stamped semantic cohort and locator/semantic evidence review.
No T2 persisted coverage state or UI work is admitted yet. No live re-embedding has occurred.

Full pytest passes 1,345 tests with one existing Starlette warning; full release-check passes in 231.5s. Claude’s
uncommitted runtime/UI/design batch remains preserved separately. Read this file, the mission, scheduler, T1 admission,
and handoff before resuming. Protected paths remain `data/`, `VIDEOS/`, and `_to_delete/`.
