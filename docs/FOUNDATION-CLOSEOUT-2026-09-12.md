# Foundation Performance + Stability closeout — 2026-09-12

## Verdict: Foundation closeout passes; live performance observation recorded

Foundation code through R7 is release-ready at `bf8d595` and is documented by the later coordination commit
`2efea59`. The live version endpoint returned `0.63.43` with `fake_ai=false`. The final release check passed in
213.0 seconds and includes the whole test suite, Tier 1, migration, crash/recovery, retrieval, browser, UI,
storage, backup and restore gates. Its artifact is
`evals/release/release-check-0.63.43-bf8d595-20260912-032952.json`.

The authenticated Health console was refreshed and observed at the same running version. It supplied the required
operational snapshot without opening, copying or querying the live database. The results support a stable Foundation
closeout and admission of Transcript Intelligence. They do **not** establish that R7 reduced all historical job or
provider latency: those measurements include work executed before R7 and batch-provider turnaround that R7 does not
control.

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
| Queue wait and work p50/p90 | Authenticated Health console, 7-day history | OBSERVED; historical queue wait is the next optimization target |
| Model-call p50/p90 and local/API split | Authenticated Health console, 7-day history | OBSERVED; batch turnaround is historical/provider-bound |
| Endpoint p50/p90 and time-to-first-output | Authenticated Health console process samples | OBSERVED; interactive endpoints remain sub-second at p90 |
| Parallel utilisation and work-unit reuse rate | Durable job/work-unit records and R4/R5 invariant gates | PASS by durable-unit and concurrency gates |
| R7 semantic benefit and latency reduction | deterministic ordering/eligibility proof only | NOT CLAIMED |

## Authenticated live observation — 2026-09-12

The local authenticated console was refreshed to `v0.63.43`; its Health panel reported the last release check as
**PASS · 0.63.43 @ bf8d595 · 2026-09-12T03:29:52 · 42 gates**. The database integrity check was OK and the verified
backup was 22 minutes old (662.9 MB; 1,863 sources; 234 messages). The queue reported **0 queued, 0 running**, so
there was no stale running job at observation time. The console also reported 100.0% valid answer citations (996),
98.8% verified finding quotes (25,769 checked; 323 rejected), and live model-provider health for Anthropic Batches,
OpenAI Embeddings, and OpenAI Transcription.

The `/api/perf` report shown by **Measure speed** contained these process samples:

| Surface | p50 | p90 | Sample / interpretation |
|---|---:|---:|---|
| `/api/health` | 0.09s | 0.09s | 2 requests |
| `/api/projects/{project_id}/jobs` | 0.08s | 0.14s | 17 requests |
| `/api/projects/{project_id}/bootstrap` | 0.03s | 0.04s | 17 requests |
| `/api/sources` | 0.27s | 0.57s | 17 requests |
| `sources:list` | 0.13s | 0.24s | 17 requests |
| slowest observed endpoint: caption recovery | 0.34s | 0.58s | 17 requests; maximum 0.89s |

The 7-day job report separates service work from queue wait. The large waits are historical admission/backlog
measurements, not a current stuck queue: `suggest_findings` had 14.41s work p50 and 3,075.60s wait p50 (2,204 jobs);
`ingest_source` had 11.77s work p50 and 254.23s wait p50 (1,438 jobs). The report also retains old provider-batch
turnaround: `findings.extract` through `anthropic_batch` showed 208,600.85s p50 / 238,123.87s p90 (1,188 calls).
This should be treated as provider/batch-history evidence, not an R7 regression or a reason to reopen a clean live
queue.

Two pre-existing operational disclosures remain visible and are preserved rather than papered over: 36 already
collected batch results were intentionally not written after their sibling windows were cancelled, and structured
output shows three schema mismatches with one unrecovered historical event. Neither produced a current running job,
integrity failure, citation failure, or unexplained invocation in the observed Health state. Future work must keep
those records auditable; it must not relabel them as successful work.

## UI and operational state

The release gate proves first-party client/server version handling, static handler integrity, acknowledgement behavior,
and web syntax. The live version endpoint confirms the current server version. Detailed operational state remains behind
authentication as intended: `/api/health` reports database integrity, verified backup state, stale leases, invocation
ambiguity, structured-output failures, providers and release state; `/api/perf` reports endpoint, queue and model
latency. A direct unauthenticated `/api/health` request returned HTTP 401, which confirms the boundary rather than a
runtime defect.

## Closeout decision

Foundation is complete through R7. The observed release has a clean current queue, valid integrity/backup state,
and responsive interactive endpoints; the full release gate also passed. Transcript Intelligence is admitted next.
Its first performance experiments must use fresh, version-stamped cohorts so historical batch wait cannot be
misattributed to new changes. R8's 30-day retention observation and R9's local-runtime prerequisite remain
independent, non-blocking tracks.
