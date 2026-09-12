# Pre-T1 gate audit — 2026-09-12

## Verdict: do not begin T1 implementation yet

The governing roadmap in `DEVELOPMENT-OPERATING-SYSTEM.md` places R8 and R9 before Transcript Intelligence. Foundation R4–R7 and its formal authenticated closeout are complete. That does not make every earlier measurement requirement complete.

| Prerequisite | Status | Evidence / remaining work |
|---|---|---|
| Context, measurement environment and systemic regression gates | Complete | 0.63.36–0.63.39 evidence and release gates. |
| R8 storage hygiene, statistics, WAL policy and targeted indexes | Complete | 0.63.36; copied-backup measurement and first live confirmation recorded. |
| R8 retention decision | Deliberately deferred, non-destructive observation | The 30-day `job_events` sample has not elapsed. Revisit after **2026-10-11 17:28 PT** with growth, consumers, and evidence-preserving options; no rollup, archive, or deletion is authorized before then. This is intentionally non-blocking under the existing scheduler. |
| R9(a) embeddings | Complete | `bge-m3` selected after frozen latency, recall@10 and MRR gates; Nomic rejected. |
| R9(b) short classification/triage | Complete | Fair 256-token-cap reruns produced a complete verdict for every declared candidate: Llama 3.1 8B adopted (343 ms p50, 15/15 valid); Qwen3 8B, Qwen3 14B, and gpt-oss-20b rejected on the measured speed and/or validity gates. |
| R9(c) findings/claims extraction | **Open** | The declared 70B Q4 and MoE candidates still need one real 15k-token window, separately reporting prefill and generation, against the 10.9-second API gate. |
| Foundation R4, R4 recovery gate, R5, R5 concurrency gate, R6, R7, formal closeout | Complete | 0.63.40–0.63.43 and `docs/FOUNDATION-CLOSEOUT-2026-09-12.md`. |

## Phase-by-phase confirmation

| Roadmap phase | Status | Checkpoint |
|---|---|---|
| Phase 0 — documentation and repository hygiene | Complete | Active mission, scheduler, handoff, protected-path policy, and this audit agree; GitHub snapshot excludes `VIDEOS/`, `data/`, and `_to_delete/`. |
| Phase 1 — measurement environment | Complete | R8 copied-backup measurement and the loopback Ollama R9 environment are recorded; live `data/neurosearch.db` was not opened. |
| Phase 2 — systemic regression gates | Complete | 0.63.39 request-path purity, test isolation, recovery and release checks. |
| Phase 3 — R8 storage hygiene | Immediate gate complete; retention deferred | Statistics, WAL policy and indexes are shipped. The 30-day `job_events` observation has a dated revisit trigger and no destructive cutoff. |
| Phase 4 — R9 local runtime | R9(a)/(b) complete; R9(c) open | `bge-m3` selected for a later full-space migration; Llama 3.1 8B adopted for short classification; long-window extraction is still measured. |
| Phase 5 — R4 durable work units | Complete | 0.63.40 and its 66-case recovery abuse gate. |
| Phase 6 — R4 recovery gate | Complete | Graceful shutdown and mutation replay/idempotency evidence in `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`. |
| Phase 7 — R5 bounded concurrency | Complete | 0.63.41 deterministic concurrency gate. |
| Phase 8 — R5 concurrency regression gate | Complete | Dedicated gate passed; no reopened scheduler implementation. |
| Phase 9 — R6 then R7 | Complete | 0.63.42 Fast/Warm admission, 0.63.43 novelty/residual gate, and authenticated live closeout. |
| Phase 10 — Foundation hardening closeout | Complete | `docs/FOUNDATION-CLOSEOUT-2026-09-12.md`; queue, integrity, backup, release check, and interactive p90 evidence recorded. |

## Consequence

T1 must remain at design/admission preparation until R9(c)'s remaining benchmark arm is complete or deliberately deferred
with its numeric revisit trigger. R8 is already deliberately deferred with the dated observation trigger above; it remains
non-blocking and no retention mutation is admitted. R9(a)'s embedding decision and R9(b)'s complete candidate scorecard
are necessary for T1, but R9(c) still requires the declared long-window measurement before the pre-T1 gate is closed.

No T1 code, migration, backfill, local corpus re-embed, or UI work has started. The existing production chunk embeddings remain unchanged.
