# Foundation recovery gates

Status: Gates 1–3 immediate work, R4 recovery and R5 concurrency gates complete. Version 0.63.41 is release-checked;
R6 is active.

## Gate 1 — graceful shutdown during provider work — COMPLETE 2026-09-11

Current evidence: `jobs.stop_workers()` sets the stop event and preserves a surviving worker generation, but a live restart during an in-flight local provider call logged `Worker shutdown incomplete`. Startup then recovered the interrupted job. The existing unit contract deliberately raises on a survivor; do not weaken that safety property without a replacement test.

Progress: the ASGI lifespan converts a bounded survivor into a recovery warning while preserving the worker fence. A controlled live 0.63.38 restart completed without a lifespan traceback. The native subprocess gate starts a real worker against a disposable database, kills it during a delayed fake-provider call, starts a replacement, and proves the same durable job completes without duplicate discovery rows. The ledger records one interrupted invocation as `outcome_unknown` and exactly two completed invocations for the restarted two-stage discovery. Foundation lifecycle validation: **17 passed**. Gate 1 is complete.

Completed work:

1. Add a native lifecycle test that starts the app, holds a provider call, sends the shutdown signal, and records the HTTP/application exit result.
2. Define the contract for a bounded drain: which jobs may finish, which jobs are recovered on the next startup, what is logged, and whether the lifespan exits cleanly when a daemon worker outlives the timeout.
3. Prove that the recovered job cannot create a second paid invocation or duplicate durable output.
4. Update `FOUNDATION-HANDOFF.md` with the measured timeout, survivor behavior, and the final decision (fixed or explicitly accepted).

Acceptance:

- No duplicate invocation or duplicate finding after restart.
- No worker generation is started while the previous generation is alive.
- Shutdown behavior is deterministic at the configured timeout and visible in logs.
- The native test runs without external providers.

## Gate 2 — mutation replay protection — COMPLETE 2026-09-11

Inventory every authenticated mutating route in `neurosearch/api.py`. Domain idempotency already covers many source and claims paths, but a transport retry is not uniformly represented at the HTTP boundary.

Completed inventory: the main queue-producing routes already used natural job keys. Two low-lane kinds did not: `recover_captions` and `refresh_skipped_metadata`; both now key active work by project and source. Browser capture replay returns the original durable identity. Session-assisted ingest canonicalizes its URL and reuses one private cookie path per project/resource. Collection ranking returns the same active job; repeated approval creates no second ingest; repeated candidate dismiss, restore, and acquire preserve one final state and one active acquisition job.

Validation: replay/background/capture/session coverage passes **12 tests**; collection and candidate replay coverage passes **3 tests**; the full native suite after the first replay slice is **1,285 passed**. Gate 2 is complete.

Completed work:

1. Identify routes where a repeated request can queue work or apply a state transition twice.
2. Add an idempotency key only to those routes, with a durable response record and bounded retention.
3. Test a timeout/retry sequence and concurrent duplicate requests.
4. Document routes intentionally left domain-idempotent without a request key.

Acceptance:

- A retried request returns the original result and does not enqueue a second equivalent job.
- Different request keys remain independent.
- Existing UI clients continue to work without a key.

## Gate 3 — R8 evidence and cold derived-state budget

Collect live job-event growth and memory statistics before choosing retention. Measure the first findings-quality scan separately from warm-cache scans. Keep the 0.63.37 revision-scoped cache unless a numeric latency or memory trigger is crossed; only then evaluate an indexed or persisted duplicate graph.

The immediate R8 evidence record—live planner statistics, memory/query-plan observations and cold-versus-warm
findings-quality cost—must be complete before R9. Start the 30-day job-event growth sample at the same time. The
retention decision waits for the complete sample, but passive collection does not block R9 or R4 because neither
changes or deletes job-event evidence. No retention cutoff is admitted early. The cold quality optimization is
measurement-triggered, not a parallel project.

Evidence checkpoint 2026-09-11 17:28 PT: copied backups `neurosearch-20260911-1628.db` and
`neurosearch-20260911-1728.db` both passed `PRAGMA integrity_check`; both contained `sqlite_stat1`, 161,831 pages
at 4,096 bytes, and 662,859,776 bytes on disk. Both contained 105,048 `job_events` rows spanning the same recorded
range and 4,394 distinct jobs. No event growth or file growth was measurable across that hourly pair. This is an
initial observation, not the 30-day retention decision.

## Phase 1/2 closeout candidate — 0.63.39

- Read-only Health, Usage, backlog and staleness paths now call `claude_code.health_snapshot()`. A cold or stale
  cache is reported honestly without starting a hidden CLI subprocess. Only explicit Re-check and actual provider
  routing initiate a probe.
- The request-purity gate patches model entry points, job creation and active health refresh to fail, then exercises
  the ordinary version, Usage, Health, tick, project, staleness, backlog and Sources reads.
- The native killed-worker gate waits until the provider invocation is durably `in_flight` before terminating the
  process, removing a race between job claim and invocation creation.
- `tests/conftest.py` pins every experimental/rollback feature to its production-safe default before imports, so a
  developer `.env` cannot silently activate the reranker, prefilter, Planner V3 or other release-disabled paths.
- Reranker diagnostics are cleared when search does not execute the reranker, preventing a previous experiment from
  appearing to describe a later baseline request.

Validation: Foundation lifecycle, local transport, frontend integrity, fallback/release and crash/recovery suites:
**115 passed in 37.59 seconds**. Full native suite: **1,287 passed, 1 existing Starlette deprecation warning in
140.53 seconds**. Deterministic release-check: **PASS in 5.7 seconds**, artifact
`evals/release/release-check-0.63.39-f345726-20260911-162905.json`. Version is observed live; authenticated behavioral verification remains bounded.

## Validation note — 2026-09-11

The test-isolation defect is resolved. The developer machine's `.env` selected the local Claude Code profile before test collection, so tests that monkeypatched the API-shaped Anthropic client instead launched the real CLI. This made six deterministic tests slow and variable. `tests/conftest.py` now selects the cloud-shaped adapter before application imports; tests of the local provider opt into local mode explicitly. The chat tool-loop test is also self-contained instead of depending on an earlier test to initialize its database and source fixture.

Validation after the original fix: the six original failures pass together in 1.46 seconds, the isolated chat
tool-loop passes, and the full native suite at that checkpoint was **1,284 passed, 1 Starlette dependency
deprecation warning in 141.16 seconds**. The later replay checkpoint was **1,285 passed**. The 0.63.39 full-suite
result is **1,287 passed** as recorded above.
