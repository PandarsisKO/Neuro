# Pre-T1 gate audit — 2026-09-12

## Verdict: do not begin T1 implementation yet

The governing roadmap in `DEVELOPMENT-OPERATING-SYSTEM.md` places R8 and R9 before Transcript Intelligence. Foundation R4–R7 and its formal authenticated closeout are complete. That does not make every earlier measurement requirement complete.

| Prerequisite | Status | Evidence / remaining work |
|---|---|---|
| Context, measurement environment and systemic regression gates | Complete | 0.63.36–0.63.39 evidence and release gates. |
| R8 storage hygiene, statistics, WAL policy and targeted indexes | Complete | 0.63.36; copied-backup measurement and first live confirmation recorded. |
| R8 retention decision | **Open, non-destructive observation** | 30-day `job_events` sample has not elapsed. No rollup, archive, or deletion is authorized before it does. This is intentionally non-blocking under the existing scheduler. |
| R9(a) embeddings | Complete | `bge-m3` selected after frozen latency, recall@10 and MRR gates; Nomic rejected. |
| R9(b) short classification/triage | Complete | Fair 256-token-cap reruns produced a complete verdict for every declared candidate: Llama 3.1 8B adopted (343 ms p50, 15/15 valid); Qwen3 8B, Qwen3 14B, and gpt-oss-20b rejected on the measured speed and/or validity gates. |
| R9(c) findings/claims extraction | **Open** | The declared 70B Q4 and MoE candidates still need one real 15k-token window, separately reporting prefill and generation, against the 10.9-second API gate. |
| Foundation R4, R4 recovery gate, R5, R5 concurrency gate, R6, R7, formal closeout | Complete | 0.63.40–0.63.43 and `docs/FOUNDATION-CLOSEOUT-2026-09-12.md`. |

## Consequence

T1 must remain at design/admission preparation until the owner explicitly accepts the R8 non-blocking observation and R9(c)'s remaining benchmark arm as either completed or deliberately deferred with a numeric revisit trigger. R9(a)'s embedding decision and R9(b)'s complete candidate scorecard are necessary for T1, but R9(c) still requires the declared long-window measurement before the pre-T1 gate is closed.

No T1 code, migration, backfill, local corpus re-embed, or UI work has started. The existing production chunk embeddings remain unchanged.
