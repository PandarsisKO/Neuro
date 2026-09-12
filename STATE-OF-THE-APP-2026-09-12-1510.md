# Neuro Search — State of the App

Updated 2026-09-12 after the authenticated Foundation closeout and the R9 local-runtime scorecard. This is the
current orientation document; `DEVELOPMENT-OPERATING-SYSTEM.md` governs the workflow and the linked admission/audit
documents contain the detailed evidence.

## Current status and priority

Runtime baseline: **0.63.43**, release-checked at `bf8d595`. Foundation Phases 0–10 are complete through R7 and the
formal closeout. Transcript Intelligence is the active product program, but T1 implementation has not started because
the final pre-T1 measurement arm, R9(c), remains open.

The immediate R9 decisions are complete where measured:

- **R9(a) embeddings:** local Ollama `bge-m3` (1024 dimensions) passed the isolated latency, recall@10 and MRR gates;
  `nomic-embed-text` was rejected on MRR. This is a candidate for a later full-space migration. It is not mixed with
  the existing 1536-dimensional production vectors.
- **R9(b) short classification:** Llama 3.1 8B passed the fair 256-token-cap validity/speed gate and is the routing
  candidate; Qwen3 8B, Qwen3 14B and gpt-oss-20b Q4 were rejected on the measured gates. No production routing change
  is admitted by this scorecard alone.
- **R9(c) long-window extraction:** one real approximately 15k-token window remains to be measured for the declared
  70B Q4 and `gpt-oss-120b` candidates, with prefill and generation reported separately against the 10.9-second gate.

R8 storage hygiene, statistics, WAL policy and indexes are shipped. The `job_events` retention decision is deliberately
deferred to a non-destructive observation trigger after **2026-10-11 17:28 PT**; no rollup, archive or deletion is
admitted before then and this does not block T1.

T1's design is admitted and reconciled: its first measurement uses the existing production `text-embedding-3-small`
space for versioned derived vectors so they can be compared with already embedded transcript chunks. A local `bge-m3`
space is a separate future migration rung. No live database re-embed, T1 migration, backfill or UI work has started.

## Pre-T1 completion matrix

| Roadmap work before T1 | Status |
|---|---|
| Phase 0 documentation/repository hygiene | Complete |
| Phase 1 measurement environment | Complete |
| Phase 2 systemic regression gates | Complete |
| Phase 3 R8 immediate storage gate | Complete; retention observation deliberately deferred |
| Phase 4 R9 local runtime | R9(a)/(b) complete; R9(c) open |
| Phase 5 R4 durable work units | Complete in 0.63.40 |
| Phase 6 R4 recovery/abuse gate | Complete |
| Phase 7 R5 bounded concurrency | Complete in 0.63.41 |
| Phase 8 R5 concurrency regression gate | Complete |
| Phase 9 R6 then R7 | Complete in 0.63.42/0.63.43 |
| Phase 10 Foundation hardening closeout | Complete |

Therefore the foundation work is complete, but the pre-T1 admission gate is not yet fully closed: R9(c) is the only
open measurement. See `docs/PRE-T1-GATE-AUDIT-2026-09-12.md` for the evidence and exact consequence.

## Known limits and coordination state

- R9(c) is running as a detached launchd chain so the large model pull and measurements survive a terminal/session end.
  Outputs are expected at `/tmp/neuro-r9-long-70b.json` and `/tmp/neuro-r9-long-120b.json`; this external cache is not
  committed.
- The live `data/neurosearch.db` remains protected and was not opened by the R9 probes. Tests and measurements use
  private temporary data or frozen fixtures.
- The worktree contains preserved uncommitted Claude-side runtime/UI/test changes and untracked design material in
  `AUDIT.md`, `design.md`, `Claude outputs/`, and `INSPIRATION/`. Review those as one coherent set before touching
  overlapping surfaces.
- A zero-byte `.git/index.lock` held by the macOS Virtualization VM process released at 16:08 PT, with no Git process
  associated. The real index was then reconciled to `HEAD`; no lock is present now. The latest documentation commits
  were published through a temporary alternate index and the GitHub tree is verified equal to the committed local tree.

## Safest next step

Monitor the R9(c) chain. When both outputs exist, record the actual token counts, prefill, generation and total times in
`docs/R9-ADMISSION-2026-09-11.md` and `evals/r9/scorecard-2026-09-12.json`, then update the pre-T1 audit and handoff. If
the arm is deliberately deferred, record a numeric revisit trigger. Only after that decision may T1's first measured
implementation slice begin.

## Document map

- `DEVELOPMENT-OPERATING-SYSTEM.md` — governing workflow and phase definitions.
- `PRODUCT-SCHEDULER.md` — the single active queue and admission state.
- `FOUNDATION-HANDOFF.md` — Foundation implementation, evidence and closeout.
- `docs/PRE-T1-GATE-AUDIT-2026-09-12.md` — current pre-T1 verdict and phase matrix.
- `docs/R9-ADMISSION-2026-09-11.md` — R9(a)/(b) decisions and R9(c) protocol.
- `docs/T1-ADMISSION-2026-09-12.md` — T1 design, gates and first implementation slice.
- `HANDOFF.md` — shared Codex/Claude custody, protected paths and resume mechanics.
