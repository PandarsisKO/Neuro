# Neuro Search — State of the App

Updated 2026-09-11 after the Phase 0 roadmap reconciliation. This is the current orientation document;
implementation and delivery evidence is in FOUNDATION-HANDOFF.md.

## Current status and priority

Live baseline: **0.63.38**, restart-verified at 15:28 PT. Version **0.63.39 is prepared, not delivered**. It closes
the Phase 1/2 gaps found during reconciliation: read-only surfaces no longer start hidden Claude CLI probes, tests
cannot inherit experimental flags from the developer `.env`, and the native killed-worker gate waits for the
provider invocation to be durably in flight before terminating it.

Kyle's DEVELOPMENT-OPERATING-SYSTEM.md governs priorities. NOW is Foundation stabilization: speed, QA, regression prevention, hardening, stability, recovery and predictable cost. Transcript Intelligence is the first major product program after Foundation closes. Other expansion is parked, including External AI Access and unrelated Findings redesign. PRODUCT-SCHEDULER.md is the single queue.

## What already exists

Neuro Search is a local, single-user research application: Python/FastAPI, SQLite FTS5 plus numpy vectors, one vanilla-JavaScript UI, and a browser extension. It ingests videos/audio, documents/spreadsheets/books, web content and images; produces findings with quote validation; maintains Claims and evidence; and answers with citations. It includes staged ingestion, a leased job queue, invocation and usage ledgers, provider policies, budgets and account gates, external batches, verified backups, revision-keyed derived state, and release/evidence gates.

Historical scale reported September 11: 1,863 sources, 17,923 findings, roughly 16,400 Claims and a 660 MB database. These figures were not remeasured by this session and are not current telemetry.

Speed R0–R3 are already shipped. Recent 0.63.32–0.63.34 changes supplied button acknowledgement, sustained busy state and wrapping action groups. 0.63.35 refreshed provider-health timestamps on real success, removed another wrong-model probe and raised the Claims timeout from 240 to 480 seconds. Its recorded 27% probe overhead was a BEFORE measurement; no fresh post-release performance claim is made here.

## Foundation remediation through 0.63.39

- Local-to-paid transport fallback defaults OFF, with an explicit configuration opt-in. Local failures park the same job visibly without consuming a retry attempt; explicit API/Accelerate choices are preserved. Model NO_FALLBACK and transport fallback are separate controls.
- Worker startup refuses a second live generation. Shutdown retains surviving threads, reports incomplete draining, and keeps heartbeats running until work drains. Worker connections bind to their starting database and close at thread exit.
- Endpoint tests no longer start uncontrolled background workers. The two tests that require queued execution drive their own exact job explicitly. A stale network mock now targets the actual safe_fetch boundary.
- Job/run context is established before task adapters, with full run IDs in logging context. This is attribution hardening, not a retrospective repair of ambiguous ledger rows.
- Every first-party request carries the UI version. A versioned stale client is rejected before endpoint side effects and told to reload. Visible tabs also check every 30 seconds and on focus/visibility change. Existing pre-0.63.36 tabs require one initial reload; API/extension clients without the version header remain supported.
- Dropdown/input change handlers and action links reuse acknowledgement state. New static gates check duplicate global declarations, duplicate literal DOM IDs, missing static handlers and fetch-boundary bypasses. They do not replace dynamic browser testing.
- Removed the unreachable `semantics.py` experiment and its unused DB helpers. Its fixed-quartile scoring and
  all-row backfill conflicted with current research policy. Existing embedding columns remain as harmless schema
  compatibility; no stored data is rewritten and active evidence/citation behavior is unchanged.
- The measured R8 portion adds four targeted indexes, a bounded 64 MB connection cache, a 1 GB mmap ceiling,
  memory temporary storage and weekly housekeeping-owned `ANALYZE`. Measurements came from a copied verified
  backup; the live database was never opened. Cost/execution ledgers are retained, and job-event retention remains
  pending a 30-day growth sample and consumer audit.
- 0.63.37 narrows findings-quality and usage cache revisions away from global job heartbeats; lexical cluster
  membership is cached separately from current keeper selection. Job list polling omits captured page bodies while
  detail remains complete. Claims checks cancellation after model responses and throughout backlog assessment.
  Five local screen recordings are preserved and ignored. They remain tracked because a pre-existing Git index lock
  prevented the index-only removal.
- 0.63.38 completes mutation replay/idempotency and native shutdown recovery evidence and isolates cloud-shaped API
  tests from the real local Claude CLI profile.
- 0.63.39 makes ordinary Health, Usage, backlog and staleness reads observe cached local-provider health without
  launching a probe. Explicit Re-check and actual provider routing remain the only probe initiators. It also pins
  every experimental flag to its safe default during test collection and removes a race from the native recovery gate.

Consult FOUNDATION-HANDOFF.md for actual test results and whether these changes are prepared or delivered.

## Known limits and unfinished work

1. Historical outcome_unknown attribution is NOT repaired or fully explained. HARDENING's 62 local unknown rows and lease-expiry hypothesis remain evidence to investigate. The available server log has no lost-lease/heartbeat-failure/recovery messages establishing that cause. Do not relabel unknown results as completed, widen sweeps, or repurchase work to hide the issue.
2. Terminal/orphan invocation cleanup and scheduled WAL checkpointing ALREADY exist. R8 indexes/pragmas/statistics are implemented from copied-backup measurements; live verification and an evidence-preserving job-event retention decision remain. No second reaper is needed.
3. General durable interactive work units (R4), their interruption/compatibility abuse gate, bounded per-unit concurrency (R5) and its gate are unfinished. Job deduplication is not proof that completed windows survive an incomplete parent. Stored partial external batch results are not a completed source.
4. R9 local-runtime/embedding measurements on the M3 Max have not been run. No new model, store, framework or embedding threshold was adopted.
5. The Phase 1/2 cross-cutting suite is now complete in the prepared 0.63.39 candidate; delivery and one bounded live
   verification remain before declaring the phases closed. Post-change R8 measurements and formal Foundation
   Performance + Stability closeout remain required.
6. Consolidated stale/risky-content review, phrase-aware retrieval ("quality of earnings"), and additional product ideas remain parked. Active evidence/citation behavior was not changed in this candidate.

## Safest next step

Deliver and live-verify the bounded 0.63.39 candidate, then mark Phases 1–2 closed. Complete R8's immediate live
statistics, memory/query-plan and cold/warm evidence and begin the 30-day job-event sample. The retention decision
waits for the sample; passive collection does not block R9. Continue R9 → R4 → recovery abuse gate → R5 → concurrency
gate → R6 → R7 → formal closeout → Transcript Intelligence.

## Document map

- DEVELOPMENT-OPERATING-SYSTEM.md — Kyle's governing instructions, preserved from his supplied document.
- CLAUDE.md — current architecture and standing invariants.
- HANDOFF.md — safe shared-session and delivery mechanics on this Mac.
- FOUNDATION-HANDOFF.md — precise changes, evidence, limits and restart point.
- HARDENING.md — measurements, regressions, rejected hypotheses and frozen decisions.
- PRODUCT-SCHEDULER.md — NOW / SUSPENDED / NEXT / PARKED / REJECTED / DONE.
- SPEED-MISSION.md — active technical rung requirements, subordinate to Foundation prerequisites.
- SCHEDULER.md — parked runtime scheduler design, not the product scheduler.
- docs/archive — prior states, historical missions and pre-Foundation CLAUDE/HANDOFF snapshots. Search as needed; do not read as an active queue or append new release history to EXPANSION.md.
