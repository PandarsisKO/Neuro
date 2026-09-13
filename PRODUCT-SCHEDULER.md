# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-13. This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

Pre-T1 gate completion: R9(a) selected local Ollama `bge-m3` (1024 dimensions) and R9(b) has a complete candidate scorecard. R9(c)'s long-window findings/claims benchmark is explicitly deferred after an external 70B pull stalled; its exact revisit trigger is in `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`. R8 retention is deliberately deferred to the non-destructive observation trigger after 2026-10-11 17:28 PT and is non-blocking. See `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.

The design-system work has completed D0 and D1 (`DESIGN-MISSION.md`, updated 2026-09-13): `ladder.md` rung F0
closed with a bounded runtime-verification pass, and `design/f0`'s full history (AUDIT.md/DESIGN.md upgrades, the
Apple design reference sourcebook, the evidence baseline) is merged to `main` at `79c4446`. D2 (`ladder.md` F1–P1)
is now eligible and subordinate to T1 in the same way D1 was: it must not displace the T1 measurement cohort or
touch T1's active surfaces.

## SUSPENDED — RESUME FIRST

This section is now historical. The previously uncommitted Codex
Bootstrap/resources/UI fix set is committed on `main` (`21bb117`, `5fc2ad6`,
`d95f4b3`) and its focused tests are part of the full release suite. Claude's
F0/D1 design work is likewise merged (`79c4446`); `DESIGN.md`, `AUDIT.md`,
`DESIGN-MISSION.md`, the Apple reference sourcebook, and the evidence baseline
are tracked. Local `INSPIRATION/`, `Claude outputs/`, `SCREENSHOT AUDIT/`, and
`.audit-compare-tmp/` material remains preserved as non-authoritative evidence;
do not silently delete it.

## NEXT — admitted priorities (maximum three)

1. Continue T1's versioned-vector measurement slice. The implementation and
   zero-cost preview are complete; the remaining derived-object backfill is
   explicitly authorization-gated. Preserve R9(c)'s numeric revisit trigger;
   see `docs/R9-ADMISSION-2026-09-11.md` and
   `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.
2. Continue the deliberately deferred, non-blocking R8 retention observation; revisit after 2026-10-11 17:28 PT and admit no retention cutoff before then.
3. D1 is complete. Begin D2 (`ladder.md` F1–P1) one bounded surface at a time, after the T1 slice is bounded on
   any surface F1/F2 would also touch; `bge-m3` remains reserved for a later full-space migration gate. See
   `docs/T1-DESIGN-RECONCILIATION-2026-09-12.md` and `DESIGN-MISSION.md`.

The governing downstream sequence is R4 → R4 abuse gate → R5 → concurrency gate → R6 → R7 → formal Foundation
closeout → Transcript Intelligence. R6 and R7 share Foundation Phase 9 but require separate implementation and evidence.

## PARKED

- Transcript Intelligence: active program after Foundation closeout. T1 implementation is in progress after the explicit R9(c) deferral; its admission design and shared-space decision are at `docs/T1-ADMISSION-2026-09-12.md` and `docs/T1-DESIGN-RECONCILIATION-2026-09-12.md`. T4 reuses R4/R5.
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
blocking the ladder. R8 retention is deliberately deferred until after 2026-10-11 17:28 PT with no deletion or cutoff admitted. R9(a) embedding decision is complete: `bge-m3` is selected from an isolated frozen-fixture scorecard. R9(b) is complete with Llama 3.1 8B adopted for short classification and all other candidates rejected. R9(c) is explicitly deferred with a numeric revisit trigger; T1 is the active rung.
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

The historical next-order note is superseded. The current execution order is the T1 measurement slice in the existing
production embedding space, with R9(c)'s deferred long-window benchmark retained behind its numeric trigger. The 30-day job-event sample continues in
parallel; no deletion or retention cutoff is admitted before its 2026-10-11 17:28 PT trigger. The cold derived-state
change remains trigger-only.

R9(a) admission: `bge-m3` is selected after passing frozen latency, recall and MRR gates; `nomic-embed-text` is rejected on MRR. R9(b) is complete: Llama 3.1 8B is adopted for short classification, while Qwen3 8B, Qwen3 14B and gpt-oss-20b are rejected on the measured gate. R9(c) is explicitly deferred; see docs/R9-ADMISSION-2026-09-11.md.
