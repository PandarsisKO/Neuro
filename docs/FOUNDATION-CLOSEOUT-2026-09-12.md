# Foundation Performance + Stability closeout — 2026-09-12

## Verdict: release integrity passes; live performance snapshot remains required

Foundation code through R7 is release-ready at `bf8d595` and is documented by the later coordination commit
`2efea59`. The live version endpoint returned `0.63.43` with `fake_ai=false`. The final release check passed in
213.0 seconds and includes the whole test suite, Tier 1, migration, crash/recovery, retrieval, browser, UI,
storage, backup and restore gates. Its artifact is
`evals/release/release-check-0.63.43-bf8d595-20260912-032952.json`.

This is not yet permission to declare that the live system became faster overall. The authenticated `/api/perf` and
`/api/health` endpoints hold the required live measures, but this closeout run did not have authenticated API access.
The live database was not opened, copied or queried to work around that boundary.

## Correctness and recovery: PASS

| Requirement | Evidence | Result |
|---|---|---|
| Full regression, Tier 1, release integrity | Final release-check artifact | PASS |
| Durable compatible work reuse | R4 66-case recovery gate; exact window/group keys | PASS |
| Bounded parallel execution and spend reservation | R5 concurrency gate | PASS |
| Early results without loss of deepening work | R6 Fast/Warm gate | PASS |
| Redundancy without evidence loss | R7 gate: residual-first, fail-open, eligibility retained | PASS |
| Restart, lease, provider and partial-batch recovery | Final release-check recovery gates | PASS |
| Database integrity and restore | Final release-check backup/restore gate | PASS |

## Cost and performance: mixed evidence

| Question | Available evidence | Closeout status |
|---|---|---|
| Duplicate work avoided | R4 durable units prevent rerunning compatible completed windows/groups | PASS by invariant gate |
| Paid work admitted deliberately | R5 reservation and R6 explicit API policy gates | PASS by invariant gate |
| Queue wait and work p50/p90 | `/api/perf` derives them from durable job history | LIVE SNAPSHOT REQUIRED |
| Model-call p50/p90 and local/API split | `/api/perf` derives them from invocation history | LIVE SNAPSHOT REQUIRED |
| Endpoint p50/p90 and time-to-first-output | bounded process-memory samples in `/api/perf` | LIVE SNAPSHOT REQUIRED |
| Parallel utilisation and work-unit reuse rate | durable job/work-unit records exist; no aggregate report was captured | LIVE SNAPSHOT REQUIRED |
| R7 semantic benefit and latency reduction | deterministic ordering/eligibility proof only | NOT CLAIMED |

## UI and operational state

The release gate proves first-party client/server version handling, static handler integrity, acknowledgement behavior,
and web syntax. The live version endpoint confirms the current server version. Detailed operational state remains behind
authentication as intended: `/api/health` reports database integrity, verified backup state, stale leases, invocation
ambiguity, structured-output failures, providers and release state; `/api/perf` reports endpoint, queue and model
latency. A direct unauthenticated `/api/health` request returned HTTP 401, which confirms the boundary rather than a
runtime defect.

## Required final observation

Use the authenticated Health console’s **Measure speed** action or authenticated `GET /api/perf?days=7` and
`GET /api/health`. Record the returned endpoint p50/p90, queue wait/work p50/p90, model p50/p90, stale-running
jobs, outcome-unknown invocations, backup/integrity state and release verdict in this report. If any field indicates a
new unexplained stuck job, stale lease, unresolved invocation, failed integrity/backup check, or material regression,
open the corresponding Foundation fix before admitting Transcript Intelligence.

Until that observation is recorded, the evidence supports **stable and release-checked Foundation**, not a completed
claim that Neuro is faster in live operation.
