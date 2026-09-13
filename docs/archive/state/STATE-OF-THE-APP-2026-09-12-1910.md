# State of the App — 2026-09-12 19:10 PT

This checkpoint supersedes `STATE-OF-THE-APP-2026-09-12-1851.md`.

The live project inventory remains clean at three projects. Both protected user projects and the Claude/chatGPT
design project remain present; the ten synthetic test fixtures remain absent.

T1's pre-backfill correctness gaps are closed in the working candidate:

- queued embedding jobs execute with the queued model and record that same model in usage and vector provenance;
- missing, stale, wrong-space, wrong-version, wrong-hash, wrong-dimension, and malformed-length derived vectors are
  included in preview/backfill eligibility;
- corpus attestation is bound to the canonical chunk-embedding revision and embedded-row count;
- attestation distinguishes mechanically verified dimensions/revision from declared legacy provider/model provenance;
- the test harness fixes its application token before module collection, eliminating the discovered order-dependent
  authentication failures.

The supported live API re-attested 37,629 chunk vectors at 1,536 dimensions with zero malformed rows. The current
zero-cost preview is 39,740 derived objects across three projects, or 416 project-bounded batches at 96 rows. No paid
embedding work was queued or run.

Validation: 14 focused T1 tests pass; the deliberately reordered T1/design/isolation/resource/bootstrap slice passes
97 tests; full pytest passes 1,353 tests with one existing Starlette deprecation warning in 160.69 seconds.

Foundation remains closed through R7. R8 remains deferred to its October observation trigger; R9(a)/(b) are complete
and R9(c) is deferred. T1's next gate is the explicit spend decision for the derived-vector backfill, followed by the
version-stamped semantic cohort. Claude owns the concurrent Audit/Design work and its pending UI/Bootstrap files;
Codex did not modify those surfaces in this candidate.
