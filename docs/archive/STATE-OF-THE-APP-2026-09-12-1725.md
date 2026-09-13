# State of the App — 2026-09-12 17:25 PT

This is the current orientation source and supersedes the 17:20 state file.

Foundation is closed through R7. R8 retention remains deferred until after 2026-10-11 17:28 PT. R9(a)/(b) are
complete; R9(c) is explicitly deferred after the stalled 70B pull with its exact numeric revisit trigger preserved.

T1's production corpus attestation is admitted: `openai/text-embedding-3-small`, 1,536 dimensions, 37,583 vectors,
zero malformed. The read-only attested cohort is `evals/t1/cohort-20260912-1719.json`; all 13 projects are ready for
measurement, but no derived vectors exist yet.

The zero-cost backfill preview is `evals/t1/backfill-preview-20260912-1724.json`: 39,715 canonical missing vectors,
about 418 existing 96-row embedding batches, zero queued, zero executed. The remaining T1 gate requires explicit
authorization for that billable backfill, then a version-stamped semantic cohort and locator/semantic evidence review.

Full pytest passed 1,345 tests with one existing Starlette warning; full release-check passed in 231.5s. Claude’s
uncommitted runtime/UI/design work remains separate and preserved. Protected paths are `data/`, `VIDEOS/`, and
`_to_delete/`.
