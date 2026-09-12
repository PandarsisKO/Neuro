# Foundation coordination — Codex and Claude

Status: **0.63.43 R7 COMPLETE; FOUNDATION CLOSEOUT ACTIVE**, 2026-09-12.

Current restart point: commit `bf8d595` implements R7 project-relative novelty/residual reading over R6's durable
Fast/Warm jobs. The 0.63.43 full suite, Tier 1 and release-check pass. R7 is closed; formal Foundation closeout is
the next active work.

Codex prepared candidate 0.63.36 in `/private/tmp/neuro-foundation-review` from base
`f345726e790b27ce32fadaf8d9003426364d99dc`. Kyle confirmed Claude was dormant. Before delivery, the live checkout
still had that base and only the two coordination documents Codex created; no overlapping Claude edits appeared.
The 0.63.36 runtime was subsequently delivered and verified. Candidate 0.63.37 adds measured cache, polling and
Claims-cancellation fixes; Kyle authorized interruption of the active Claims job and background pause.

The release artifact identifies validated source snapshot `f345726-deb83f63`:
`evals/release/release-check-0.63.36-f345726-deb83f63-20260911-114435.json`.

## What the candidate fixes

1. **Cost boundary.** Local-provider failure waits locally by default. Paid API fallback requires
   `NEUROSEARCH_LOCAL_API_FALLBACK=true`; explicit API/Accelerate choices still work. A local failure parks the
   same job visibly without consuming a job attempt. Model `NO_FALLBACK` and transport fallback are separate.
2. **Worker ownership.** A second live worker generation is refused. Shutdown stops admission, drains workers
   while the lease keeper continues, retains and reports survivors, and closes per-thread database connections.
   Each thread binds the database path it started with. Job/run context exists before the task adapter runs.
3. **Test ownership.** API tests do not start a session-wide background pool. Tests that require queued work claim
   and execute the exact job. Stale mocks now patch the actual network boundary; OCR/model tests are deterministic.
4. **Client compatibility.** First-party browser requests carry UI version 0.63.36. The server rejects a versioned
   stale client with 409 before endpoint side effects; visible tabs recheck every 30 seconds and on focus. Existing
   unversioned API/extension clients remain compatible. Tabs from before 0.63.36 need one reload to gain the guard.
5. **Frontend integrity.** Shared request routing and acknowledgement behavior cover buttons, action links,
   selects and inputs. Static gates detect duplicate top-level functions, duplicate literal IDs, missing inline
   handlers and raw first-party fetch bypasses.
6. **Measured R8 portion.** On a copied verified 630 MB backup, source-specific Findings changed from a 7.87 ms
   scan to a 0.43 ms indexed lookup. Four targeted indexes, a bounded 64 MB connection cache, a 1 GB mmap ceiling,
   memory temp storage and weekly housekeeping-owned `ANALYZE` are included. The live database was never opened.
7. **Vestigial removal.** Unreachable `semantics.py` and its unused DB helpers were removed; its additive columns
   remain for existing-database/downgrade compatibility. Its fixed-quartile/all-row policy conflicted with current
   active-only, multi-signal research policy. The current README no longer publishes unsafe cloud directions;
   exact prior README/Claude-output snapshots are archived. Cloud packaging and remote ingest are clearly labeled
   historical/compatibility pending a usage check.
8. **Derived-state cache scope.** Findings quality and usage no longer key expensive work on the global jobs
   heartbeat. Lexical duplicate membership keys only on findings; current usage reselects the keeper.
9. **Job-poll payload size.** List endpoints omit browser-captured `_external_result` page bodies; the individual
   job endpoint retains the complete durable payload.
10. **Claims cancellation.** `extract_claims` checks after a model response and during backlog assessment.
11. **Repository hygiene.** Five unreferenced screen recordings (~3 GB) remain locally and are ignored. No
   `VIDEOS/**` path is tracked, `.git/index.lock` is absent, and clean GitHub snapshots exclude `VIDEOS/`, `data/`
   and `_to_delete/`. No recording was deleted.
12. **Queued cancellation cleanup.** A cancellation requested before a paused worker can claim a job is finalized as
    terminal `cancelled`; it cannot remain indefinitely in user-facing `cancelling` state.

## Deliberate non-changes

- Historical `outcome_unknown` rows are not relabeled. Attribution is hardened, but current logs do not prove the
  prior lease-expiry hypothesis.
- `usage` and `invocations` are retained as cost/execution ledgers. `job_events` is 17.18 MB across only 3.9 days;
  collect 30 days and audit consumers before admitting an evidence-preserving rollup/archive.
- `_to_delete/` remains untouched. It is 432 MB and includes database journals that must never be opened. Move it
  as a recoverable unit only after a separate cleanup decision. The empty `_scratch/` can be removed on delivery.
- No live provider evaluation, product semantics rewrite, R9 model adoption or R5 concurrency implementation has
  occurred. R4 is committed and deterministically validated; its abuse-gate closeout is still active.

## Validation evidence

- 0.63.43 R7 candidate: `novelty.py` compares a source's stored chunk embeddings against the complete project
  corpus plus its submitted cohort, excluding itself. This makes comparison project-relative and independent of
  arrival order. Redundancy subtracts at most 40 scheduling points; it never changes eligibility, so every
  non-fast source remains a durable warm job. Findings reads least-similar chunk windows first but materializes in
  original source order and retains the same durable work-unit keys. Missing, malformed or shape-incompatible
  vectors fail open to existing priority/order. Final focused R7/R6/R4/R5 tests: **30 passed in 29.19 seconds**. The
  commit-bound release-check passed in **229.7 seconds** with full pytest, Tier 1 and all Foundation gates:
  `evals/release/release-check-0.63.43-bf8d595-20260912-032952.json`.

- 0.63.42 R6 candidate: a bulk interactive request of six or more sources deterministically picks at most three
  high-value, diverse sources using project priority, existing value, reviewed relevance, open-target lexical fit,
  creator and source-type diversity. Fast jobs are `priority` + `api_requested`; all other sources become durable
  `warm` + `local_preferred` jobs. Fast provenance remains visible as a provisional marker on the analysis until a
  later warm/deep analysis replaces it. Warm promotion changes the existing job's policy/lane and never restarts
  compatible R4 work. Focused R6/R4/R5 tests: **26 passed**; full pytest: **1,313 passed, one existing Starlette
  warning in 147.38 seconds**. Tier 1 passes unchanged. Commit-bound release-check artifact:
  `evals/release/release-check-0.63.42-3fd0a2c-20260912-030848.json`.

- 0.63.41 R5 candidate: a bounded executor carries explicit job/run, policy and logging context into every child;
  child routes merge back into the parent job summary and each child closes its own database connection. Findings uses
  at most two local or three API units (hard cap four); Claims uses the same bound only for job execution. It preserves
  input-order materialization, stops admitting units after failure/cancellation, and reserves estimated spend so
  parallel guards cannot race around a ceiling. Concurrent first successes exposed a circuit-breaker row-creation
  race; `INSERT OR IGNORE` makes healthy-row initialization idempotent. R5 gate suite: **54 passed**; adjacent
  recovery/local-policy suite: **113 passed**; full pytest: **1,309 passed, one existing Starlette warning in
  159.20 seconds**. Tier 1 passes unchanged. Commit-bound release-check artifact:
  `evals/release/release-check-0.63.41-9f46c79-20260912-025822.json`.

- 0.63.40 R4 candidate: `work_units` stores each exact Findings window or Claims group before parent
  materialization. Keys cover request text, model contract, prompt/schema/source/brief/facts revisions, depth and
  execution policy. Exact concurrent duplicates serialize by key; incompatible revisions cannot materialize as
  current. Focused R4/Findings/Claims validation reached **57 passed**; the affected broad subset reached
  **227 passed**. Full pytest: **1,298 passed, 1 existing Starlette deprecation warning in 165.06 seconds**. Tier 1
  passed with frozen totals. Commit-bound release-check passed in **6.4 seconds** with artifact
  `evals/release/release-check-0.63.40-3af9c37-20260911-191914.json`.

- 0.63.38 test-isolation milestone: the harness selects the cloud-shaped adapter before imports, so the live `.env` cannot launch the real Claude CLI from API-mocked tests. The final full native suite is **1,284 passed, 1 dependency deprecation warning in 141.16 seconds**. `test_ask_tool_loop` is self-contained and passes in isolation.
- 0.63.38 replay gate: caption/metadata jobs, browser capture, session ingest, collection review, and candidate actions are covered against repeated delivery. The post-change full suite is **1,285 passed**; the combined Foundation/replay subset is **46 passed in 3.88 seconds**. Python, package, and UI versions all report 0.63.38; `git diff --check` is clean.
- Gate 1 native recovery is complete: a disposable-database subprocess test kills a real worker during a delayed fake-provider call, starts a replacement, and verifies the same job completes with one `outcome_unknown` interrupted invocation, exactly two completed discovery-stage invocations, and no duplicate durable discovery rows. Foundation lifecycle suite: **17 passed**.
- Live restart verification at 15:28 PT: the active queue was empty; `restart.command` stopped the watched server cleanly (`Application shutdown complete`), started 0.63.38 with all worker pools, served `/api/version` with `fake_ai=false`, and verified snapshot `neurosearch-20260911-1529.db`. No shutdown warning, traceback, queued job, running job, or recovery replay was observed. The disposable native in-flight-provider kill/recovery case supplies the destructive boundary proof; Gate 1 is complete.

- 0.63.39 Phase 1/2 closeout candidate: read-only Health, Usage, backlog and staleness calls no longer start a hidden
  Claude CLI health probe; explicit Re-check and real local work retain probe ownership. Test collection pins all
  experimental features to production-safe defaults before imports. The native recovery gate now waits for a durable
  `in_flight` invocation before killing the worker. A request-purity test covers the ordinary read surfaces. The
  combined Foundation/local-provider/frontend/fallback/crash suite is **115 passed in 37.59 seconds**. The full
  native suite is **1,287 passed with one existing Starlette deprecation warning in 140.53 seconds**. Deterministic
  release-check passes in **5.7 seconds** with artifact
  `evals/release/release-check-0.63.39-f345726-20260911-162905.json`. This candidate is not delivered or live-verified
  yet.

- Foundation/storage gate: `23 passed in 1.71s`.
- Full native isolated suite: `1278 passed, 1 warning in 110.94s`. The warning is Starlette's existing
  `BlockingPortal` deprecation. A sandbox-only attempt failed because loopback binds and macOS Vision were denied;
  the approved native run passed those same tests.
- Tier 1 fake eval: PASS; retrieval 32/32 at recall@5 and recall@10, 100% citation and finding-quote validity,
  90% planted-evidence recall, zero schema mismatch/fallback/truncation/refusal events.
- Deterministic release-check: **PASS in 172.3s**, including full pytest, migration fixtures, crash/recovery matrix,
  40-source equivalence, browser/network boundaries, Tier 1 frozen totals, retrieval/cache/economic gates and a
  verified backup/restore round trip.
- Version agreement: package, pyproject and UI all report 0.63.36.
- Full native isolated suite after the 0.63.37 fixes: `1281 passed, 1 warning in 119.94s`.
- Deterministic release-check 0.63.37 (pytest run separately): **PASS in 5.2s**; final artifact
  `evals/release/release-check-0.63.37-nogit-20260911-123448.json` (and matching `.txt`).
- Candidate package, pyproject and UI all report 0.63.37.

## Delivery hold and exact restart point

At 11:43 local time the live 0.63.35 server was actively normalizing Claims in job `20f418c7`; it yielded after
two groups with 7,763 candidates still queued and then continued. Landing watched Python/HTML files would reload
the old server while that work is active. Codex therefore did not overwrite runtime files merely because tests
passed.

Kyle authorized the interruption and background pause. The old process is being stopped so startup recovery can mark
`20f418c7` cancelled from its durable request. Copy only the documented 0.63.37 paths (never `.env`, `data`, temporary
helpers or reports), let the launcher reload, then verify `/api/version`, stale-client refusal, housekeeping `ANALYZE`,
worker startup, `background_paused=true`, and the cancelled job through the supported app/API. Record the exact live
facts below. Commit/tag only after that proof.

## 0.63.37 live verification record

- Source validation: 1,281 native tests passed; deterministic release-check passed.
- Live delivery: verified after authorized restart and post-restart API/UI check.
- Claims control: job `20f418c7`, cancellation requested through the live API; old worker stopped for recovery.
- Background control: `background_paused=true` confirmed before restart.
- Live version: `/api/version` returned `0.63.37`, `fake_ai=false`.
- Live Claims state: `20f418c7` is terminal `cancelled` with its original cancellation timestamp retained.
- Live background state: `/api/usage` returned `background_paused=true`, `paused=false`.
- Live startup: workers started, one interrupted job was recovered, and the recovered cancellation was finalized
  without launching another Claims call.
- Git hygiene follow-up: `.git/index.lock` already existed (timestamp 09:49) when the index-only `VIDEOS/` cleanup
  was attempted. No lock was removed and no index mutation was forced. Before staging the five recording deletions,
  inspect whether an owning Git process still exists; if none does, use the repository's approved stale-lock recovery
  procedure, then verify the recordings remain on disk and `git status` sees `VIDEOS/` only through `.gitignore`.

The formal closeout report is at `docs/FOUNDATION-CLOSEOUT-2026-09-12.md`. Its authenticated Health/Performance
observation is complete: the refreshed console ran `0.63.43`, the 42-gate release check passed, integrity and backup
were healthy, and the live queue was `0 queued · 0 running`. Interactive endpoint p90 was at most 0.58s in the
captured sample. Historical provider-batch and queue waits remain explicitly recorded as old/provider-bound evidence,
not as an R7 regression. Transcript Intelligence is now admitted, but its T1 implementation remains correctly
blocked until R9 validates a supported local runtime and weights; the complete handoff is
`docs/T1-ADMISSION-2026-09-12.md`. R8's 30-day retention sample continues without blocking this ladder.
`PRODUCT-SCHEDULER.md` is authoritative.

R8 evidence checkpoint: copied verified backups from 16:28 and 17:28 PT both passed integrity; both were 662,859,776
bytes with `sqlite_stat1`, 161,831 pages, 105,048 job-event rows and 4,394 distinct jobs. No growth was measurable
across that hour. The 30-day retention sample and live memory/query-plan observations remain open.
