# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-12. This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

Pre-T1 gate completion: R9(a) selected local Ollama `bge-m3` (1024 dimensions) and R9(b) has a complete candidate scorecard. R9(c)'s long-window findings/claims benchmark is explicitly deferred after an external 70B pull stalled; its exact revisit trigger is in `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`. R8 retention is deliberately deferred to the non-destructive observation trigger after 2026-10-11 17:28 PT and is non-blocking. See `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.

The design-system work is currently at D0 (instruments frozen) and is subordinate to T1. Its next rung is a read-only
rendered evidence audit (D1), documented in `DESIGN-MISSION.md`; it must not displace the T1 measurement cohort.

## SUSPENDED — RESUME FIRST

The current worktree contains an uncommitted Codex Bootstrap/resources/UI fix set and its tests (begun the afternoon of 2026-09-12; Claude did not touch these files):
`neurosearch/bootstrap.py`, `neurosearch/resources.py`, `neurosearch/web/index.html`,
`tests/test_k3_resources.py`, and `tests/test_s14_fix_pass.py`. The focused suite is **73 passed** (2026-09-12).
These files are intentionally preserved and are not included in the R9/T1 documentation commits. Review, commit, or
discard them as one coherent set before changing the same surfaces. Claude's uncommitted work is separate: the mmap
reversal in `neurosearch/db.py` plus two `HARDENING.md` entries (D0 tokens/drift baseline; FTS5 mmap), `DESIGN.md`,
`AUDIT.md`, `tests/test_s50_design_drift.py`, `docs/FTS5-CORRUPTION-2026-09-12.md`. The `INSPIRATION/` assets and
`Claude outputs/` are untracked handoff material;
do not silently delete them.

## NEXT — admitted priorities (maximum three)

1. Begin T1's versioned-vector measurement slice while preserving R9(c)'s numeric revisit trigger; see
   `docs/R9-ADMISSION-2026-09-11.md` and `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.
2. Continue the deliberately deferred, non-blocking R8 retention observation; revisit after 2026-10-11 17:28 PT and admit no retention cutoff before then.
3. Continue D1's read-only rendered evidence audit after the T1 slice is bounded; `bge-m3` remains reserved for a
   later full-space migration gate. See `docs/T1-DESIGN-RECONCILIATION-2026-09-12.md`.

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
