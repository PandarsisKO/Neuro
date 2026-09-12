# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-11. This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

R9 local-runtime scorecard: Ollama 0.33.3 is running on loopback against an isolated frozen fixture. `nomic-embed-text` passed the latency and recall gates but failed the MRR floor, so it is rejected; complete the remaining declared candidates before changing production embeddings or admitting T1 code.

## SUSPENDED — RESUME FIRST

None recorded. No evidence of uncommitted Claude work at base f345726. Do not invent a suspended R4 or scheduler implementation from an old checklist.

## NEXT — admitted priorities (maximum three)

1. Complete R9's active local-runtime scorecard before writing T1 code; see
   `docs/R9-ADMISSION-2026-09-11.md` and `docs/T1-ADMISSION-2026-09-12.md`.
2. On an R9 pass, begin T1 with a fresh, version-stamped semantic-coverage cohort and keep its quality, latency and
   cost separate from historical provider-batch and queue wait.
3. Continue the non-blocking R8 retention observation; no retention cutoff is admitted yet.

The governing downstream sequence is R4 → R4 abuse gate → R5 → concurrency gate → R6 → R7 → formal Foundation
closeout → Transcript Intelligence. R6 and R7 share Foundation Phase 9 but require separate implementation and evidence.

## PARKED

- Transcript Intelligence: active program after Foundation closeout. T1 implementation is blocked on R9's embedding decision; its admission design is at `docs/T1-ADMISSION-2026-09-12.md`. T4 reuses R4/R5.
- External AI access and multi-user/sharing: permissions boundary unresolved; no implementation admission.
- Project Inbox, cloud/infrastructure expansion, new acquisition classes, additional Bootstrap, Research/Discover/Planner expansion.
- Consolidated stale/risky Findings review and unrelated Findings redesign: real usability pain; revisit at Foundation admission checkpoint unless it blocks current work.
- Phrase-aware retrieval: measured failure of "quality of earnings"; two word-list fixes rejected. Revisit with a real-query quality experiment after current foundation effort.
- FIELD-MAP-RUNG and remaining SOURCE-CAPABILITY-RUNG scope: idea records, not active queues.

## REJECTED / REVISIT ON TRIGGER

Retrieval reranker, batch-path findings prefilter and Planner v3 remain off. Use HARDENING.md's measured decisions. Additional stores/services and infrastructure retain SPEED-MISSION.md §H's numeric triggers. Do not reopen an experiment simply because another session proposes it.

## DONE

- Existing speed R0–R3 and shipped product features: preserved; no restart.
- 0.63.35 local probe/model/timeout fixes: released historical baseline.
- Historical mission archival at f345726: completed.

0.63.36–0.63.39 are DONE. R8 immediate evidence is complete; its 30-day retention sample continues without
blocking the ladder. R9 preflight is superseded: the local runtime is installed and the scorecard is actively measuring candidates in an isolated fixture.
R4 and its 66-case abuse gate are complete in 0.63.40. R5 and its deterministic concurrency gate are complete in
0.63.41. R6 and its Fast/Warm admission gate are complete in 0.63.42. R7 and its novelty/residual gate are complete
in 0.63.43. The authenticated Foundation closeout observation is complete: current queue was empty, integrity and
backup were healthy, release check passed, and interactive endpoint p90 was at most 0.58s in the observed sample.

## AUDIT ADDITIONS — 2026-09-11

These are bounded gaps found during the post-0.63.37 review. They are admitted as Foundation follow-ons; they do not reopen parked product missions.

1. **Graceful shutdown gate — complete 2026-09-11.** Clean live restart and native SIGTERM-during-provider recovery are covered. The worker fence remains intact; interrupted invocation uncertainty is recorded as `outcome_unknown`; durable output is not duplicated. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
2. **Mutation replay/idempotency gate — complete 2026-09-11.** Queue, capture, session-ingest, collection, and candidate transitions were inventoried and covered; missing caption/metadata natural keys, capture replay, and session cookie-file reuse were fixed. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
3. **Request-path purity and test isolation — complete in 0.63.39.** Read-only status/polling paths use a cached
   health snapshot and never start a Claude CLI probe. Explicit Re-check and actual local work remain the only probe
   initiators. Tests pin every experimental feature to its production-safe default before imports. The native
   restart gate kills only after an invocation is durably in flight. Combined Phase 1/2 suite: **115 passed**.
4. **Cold derived-state budget.** The first findings-quality scan can still hit the eight-million comparison budget and emit a partial-review warning. Keep the narrowed invalidation cache; measure cold-start cost and admit an indexed/blocking or persisted derived graph only if the agreed latency and memory trigger is crossed.
5. **Evidence and repository hygiene.** `.git/index.lock` is absent. The recordings remain on local disk but no
   `VIDEOS/**` path is tracked. Clean GitHub snapshots exclude `VIDEOS/`, `data/` and `_to_delete/`.
6. **R8 evidence checkpoint — observed 2026-09-11 17:28 PT.** Copied verified backups at 16:28 and 17:28 both pass
   integrity, contain `sqlite_stat1`, and are byte-identical in size (662,859,776 bytes) with 105,048 job-event rows
   and 4,394 distinct jobs. No growth was measurable across that hour. The 30-day sample remains open.

The next execution order is Transcript Intelligence baseline → bounded admission experiment.
The 30-day job-event sample continues alongside those stages; no deletion or retention cutoff is admitted before it
finishes. The cold derived-state change remains trigger-only.

R9 admission: local Ollama is installed and the benchmark is active. `nomic-embed-text` is rejected on frozen MRR despite passing latency; see docs/R9-ADMISSION-2026-09-11.md.
