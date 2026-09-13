# Transcript Intelligence T2 admission proposal — seven-state coverage view

**Status: PROPOSED — implementation is not admitted until the state semantics below are reviewed and accepted.**

This is the next Transcript Intelligence rung after the completed T1 derived-vector measurement. It is Codex-owned
backend/measurement work and deliberately has no frontend or Audit/Design surface. The source requirements are
`TRANSCRIPT-INTELLIGENCE-MISSION.md` §D/T2 and `DEVELOPMENT-OPERATING-SYSTEM.md` §36.

## Problem and evidence

T1 now provides versioned vectors for every canonical active Claim and Finding in the attested production
`text-embedding-3-small` space. The accepted cohort (`evals/t1/cohort-20260913-105835.json`) covers three retained
projects: 38,038 attested 1,536-dimensional chunk vectors, 18,933 canonical derived objects, and measured
project-relative similarity distributions. The existing `/api/projects/{project_id}/transcript/coverage` endpoint
is read-only and already reconciles locator counts with the T1 semantic measurement.

The missing product capability is a trustworthy view of what each chunk has received. A locator miss is not the same
as an unexplained passage, so the view must preserve independent signals and must never define `unexplained` as the
complement of one test.

## Scope of the admission

1. Extend the existing read-only T1 coverage seam with a deterministic per-chunk/per-source coverage view. Do not
   create a new route or UI surface before the response shape is proven.
2. Derive these seven states/signals from existing rows and T1 output:
   `extracted`, `represented`, `finding_covered`, `claim_covered`, `redundant`, `irrelevant`, and `unexplained`.
3. Preserve the independent signals in the response. If a consumer needs one primary label, expose it as a
   deterministic projection with the precedence documented in the implementation and keep the signal list intact.
4. Use project-relative percentile cut points from the measured T1 distributions. Do not add a universal cosine
   threshold or silently substitute a missing/stale vector.
5. Start with a derived view. Add a narrow `chunk_pass` table only if a later pass cannot be derived and query or
   performance evidence demonstrates that persistence is needed.

## State semantics and proposed projection

The response should carry `signals` (possibly more than one) and a `primary_state` for simple consumers. The proposed
projection is ordered only to make the result deterministic; it must not discard the underlying signals:

1. `irrelevant`: project-relative evidence says the chunk is far from the project's goal and every canonical Claim,
   and no stronger coverage signal applies.
2. `redundant`: the existing project-relative duplicate machinery identifies the chunk as a near-duplicate, and no
   stronger coverage signal applies.
3. `claim_covered`: a canonical Claim evidence locator falls inside the chunk's `[start, end)` range.
4. `finding_covered`: an applicable canonical Finding citation/window covers the chunk.
5. `represented`: a valid T1 vector is within the project's measured representation cut point, without a locator.
6. `extracted`: a versioned deterministic Tier-0 extraction pass has run for the chunk (T3 may provide this later).
7. `unexplained`: the chunk is eligible, not irrelevant or redundant, has no Claim/Finding locator, is not
   represented by valid T1 vectors, and has an extraction/pass result where the definition requires one.

Until T3 exists, `extracted` must be reported as `unknown`/unavailable rather than asserted. Until a measured
project-relative irrelevance or redundancy signal is available for a chunk, those signals remain absent. The view
must say which inputs were unavailable so a missing signal cannot be mistaken for a negative result.

## Reconciliation and safety invariants

- Every chunk in the denominator belongs to a non-excluded project membership and has a stable source revision.
- Claim locator counts reconcile with `claim_evidence` rows for canonical `proposed`/`accepted` Claims.
- Finding coverage reconciles with canonical Finding citations/windows; malformed citations are reported as unavailable,
  never silently counted as covered.
- T1 similarity is used only when provider, model, version, dimensions, input hash, and corpus attestation match.
  Missing, stale, corrupt, or wrong-space vectors fail open.
- `unexplained` is never computed as `total - covered` and never includes a chunk whose required signal is unavailable.
- Excluded project membership subtracts the chunk from that project's denominator; global source identity is unchanged.
- The read path performs no writes, queues no jobs, starts no provider/model call, and does not mutate caches whose
  invalidation would change durable state.
- Stable ordering is `(source_id, chunk_idx, chunk_id)`; repeated reads with unchanged inputs are byte-equivalent.

## Acceptance gates

**Deterministic:** focused T2 tests prove state precedence, signal preservation, locator range boundaries, excluded
membership, malformed/missing citation handling, stale/missing T1 vectors, project-relative cut points, stable
ordering, and read-only request-path purity. Existing T1, S44, S5, and repository-hygiene gates remain green.

**Measurement:** run the view against the version-stamped T1 cohort and publish per-project counts for every signal,
denominator, unavailable inputs, and latency. Compare locator versus semantic distributions without inventing an
absolute quality threshold. Record memory and p50/p90 before deciding whether any persistence or index is needed.

**Behavioral:** the authenticated endpoint remains read-only, does not enqueue work, and returns the same underlying
counts as direct application-owned query helpers. No frontend change is part of T2 admission.

**Release:** focused tests, full pytest, Tier 1 where affected, and the commit-bound `release-check` must pass. The
admission artifact and results are appended to `HANDOFF.md`, `PRODUCT-SCHEDULER.md`, and `HARDENING.md` before the
rung is closed.

## Explicit non-goals

- No seven-state UI, new Research tab, or frontend markup change.
- No Tier-0 extraction (T3), batch executor (T4), adjudicator (T5), local NLP (T7), or universal threshold.
- No new table unless the derived view's measured query/performance evidence requires one.
- No live database access outside the authenticated app API; copied verified backups are the only offline measurement
  source.

## Review and next action

This proposal is ready for state-model review. If accepted, implement the derived response in the existing T1 seam,
run the gates above, and record a Resume Delta naming the exact files and test evidence. If the review changes state
precedence or the meaning of unavailable signals, patch this proposal before writing code.
