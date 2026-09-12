> FOUNDATION COMPLETE: R4 and its 66-case recovery abuse gate are complete in 0.63.40; R5 and its concurrency gate are complete in 0.63.41; R6 and its Fast/Warm gate are complete in 0.63.42; R7 and its novelty/residual gate are complete in 0.63.43. The authenticated closeout observed an empty current queue, healthy integrity/backup state, and interactive endpoint p90 at or below 0.58s. Transcript Intelligence is now the active program and is governed by DEVELOPMENT-OPERATING-SYSTEM.md and PRODUCT-SCHEDULER.md. R8 immediate evidence is complete (30-day retention sampling continues); R9(a) selected `bge-m3` (Ollama 0.33.3, 1024d) after it cleared frozen latency, recall@10 and MRR gates in an isolated fixture; `nomic-embed-text` was rejected on MRR. R9(b) is complete with Llama 3.1 8B adopted for short classification and the other declared candidates rejected on the measured gate. R9(c) remains open. Existing production chunk embeddings are unchanged until a versioned migration/backfill exists. R6 and R7 share Foundation Phase 9 but remain separate measured releases. No parallel product missions.
>
> REUSE CORRECTION (2026-09-11): db._resolve_job_inflight and _resolve_orphan_invocations already handle terminal/orphan invocation cleanup, and jobs._housekeeping_loop/db.checkpoint_wal already implement periodic WAL cleanup. Original R8's "432 rows" is historical, not a newly measured backlog. Measure remaining gaps and run attribution before adding another reaper. R4's old three-field hash sketch is insufficient: version all model, prompt/schema, source, project/brief and other semantic inputs needed for compatibility. Completed units survive; incomplete sources must remain incomplete. Do not maintain EXPANSION.md as a release diary.

# MISSION: SPEED, RESPONSIVENESS, AND EFFICIENT INTELLIGENCE

*Kyle's mission, filed 2026-09-09 at 0.45.14, revised the same day with the stack-review requirement. Read with `CLAUDE.md` (architecture map), `docs/archive/LOCAL-AI-PROVIDER.md` (L1 routing), `docs/archive/RESEARCH-MISSION.md` (the research quality contract this must not violate) and `docs/archive/EXPANSION.md` (rung log). Every number below was measured against Kyle's live 461.7 MB database and running server on 2026-09-09, not estimated.*

## NORTH STAR

The more Neuro Search has already researched, the less work it should need to repeat. Fast answers come from accumulated understanding; deep research continues around them. Prefer open-source, locally executable, free infrastructure unless a paid or proprietary alternative demonstrates concrete value worth its cost and dependency. **Make Neuro Search faster by remembering and scheduling more intelligently, never by looking at less.**

---

## A. WHAT WE MEASURED (this section is the spine — do not plan against intuition)

The single most important finding: **Neuro Search's latency is overwhelmingly waiting and repeating, not thinking.** Model calls are not the problem. Everything around them is.

**Queue wait dominates real compute, by a factor of ~50.** Median completed-job figures from the `jobs` table:

| kind | n | median work | p90 work | median WAIT before starting |
|---|---|---|---|---|
| `suggest_findings` | 1,656 | **8.6 s** | 43 s | **479 s** |
| `ingest_source` | 1,305 | 11.4 s | 15 s | 169 s |
| `rank_proposed` | 86 | 81 s | 168 s | 0.7 s |
| `extract_claims` | 8 | **1,233 s** | **6,821 s** | 72 s |
| `discover` | 7 | 576 s | 696 s | 0.6 s |
| `refresh_skipped_metadata` | 428 | 13.6 s | 16 s | 1,467 s *(by design — low lane)* |

A findings job spends **98% of its elapsed life waiting for a worker**. No amount of model speed fixes that; only scheduling and concurrency do.

**Local is ~3× slower than the API for identical work** (`invocations`, completed calls, median seconds):

| task | claude_code (local, $0) | anthropic (API) | ratio |
|---|---|---|---|
| `findings.extract` | 39.2 s | 10.9 s | 3.6× |
| `claims.extract` | 122.1 s | 39.4 s | 3.1× |
| `rank.relevance` | 52.4 s | 18.2 s | 2.9× |

That ratio is the entire economic basis of a fast lane — and it is worth 3×, while concurrency inside a job is worth N× and fixing queue admission is worth ~50×. **Ranking the levers by measured value: admission ≫ concurrency ≫ model routing.** This challenges our earlier framing, in which Fast/Warm/Deep did most of the work.

**Cost of buying that 3×** (per-call, this month): findings $0.0328, claims $0.0473, answer $0.0552, rank $0.0295. Local ran 525 calls at $0 and avoided $115.61. A fast lane is cheap *because it is small*: promoting a 3-source first wave out of 20 costs cents, not dollars.

**Chat has no streaming and a brutal tail.** `answer.chat` median 4.6 s but p90 51.1 s, max 77.7 s — and the user sees a spinner with zero output for the entire duration, because `/api/ask` buffers the whole response (up to 6 tool rounds + 2 continuations + 1 citation repair, all serial, each re-sending the prompt).

**Interactive requests are starved by our own polling.** With two browser tabs open on a 3 s poll, *every* endpoint — including trivial `/api/stats` — queued past 45 s and never returned. The Sources tick fires 7 requests including `/api/sources`, which ships 2.34 MB of `description` text for 1,347 rows, calls `db.list_sources(limit=10000)` (whole global library, filtered in Python), and runs `staleness.assess`, which issues on the order of 1,500–2,000 queries per call. This is self-inflicted congestion, and it is the reason the app "feels slow" even when nothing is running.

**Three things we expected to be bottlenecks and measured as NOT bottlenecks — do not spend effort here:**

1. *The embedding matrix reload.* All 26,958 vectors (165.6 MB) load in **0.10 s warm / 0.78 s cold**, and the actual similarity matmul is **0.002 s**. Worth a process-level cache (it happens up to ~7× per answer), but it does **not** justify sqlite-vec, FAISS, or a vector database. Brute force is fine to roughly 250k chunks.
2. *Cross-project analysis reuse.* Only **2 sources of 823** belong to more than one project. Building a cross-project cache today would be near-worthless. Design the seam; do not build the layer.
3. *The missing `project_notes` index.* The table has 10,503 rows and zero indexes, yet the hot filtered scan runs in **0.004 s**. Add the index as cheap insurance at 10× scale, not as a priority.

**Retrieval's real cost is the network, not the math.** One OpenAI embedding round trip per search costs **0.5 s median** — roughly 5× everything else in retrieval combined (0.10 s matrix + 0.002 s matmul). That, not vector indexing, is the retrieval number worth attacking.

**The hardware.** Apple M3 Max, 128 GB unified memory (the 128 GB configuration is the top bin: 16-core CPU, 40-core GPU, ~400 GB/s memory bandwidth). Two consequences run through everything below. First, the entire 461.7 MB database fits in RAM many times over — which is why the "cold" embedding read measured at 0.07 s, and why R8's cache/mmap pragmas can be set generously at no risk. Second, and less obvious: **this machine's strength is memory bandwidth, and Neuro Search's model workload is prefill-bound, which is the axis Apple Silicon is weakest on.** A findings window is ~60k chars (~15k tokens) of input for a few hundred tokens of output. 128 GB means a 70B-class model *fits* comfortably; fitting was never the constraint. Prompt-processing throughput is, and it is what decides §D's local-model verdict.

**Hygiene defects found:** 432 `invocations` stuck in `in_flight` since 2026-09-08 (never reaped); `sqlite_stat1` absent (`ANALYZE` has never run); no `cache_size`/`mmap_size`/`temp_store` pragmas; 51.4 MB WAL with no checkpoint policy; no retention on `job_events`, `invocations`, `usage`.

---

## B. PRINCIPLES (non-negotiable)

1. **Reordering is allowed; discarding is not.** Lanes, triage and deferral may change *when* material is read. Nothing may make material unreadable, and every deferred item stays in a queue, never a filter.
2. **Compress repeated information, not sources.** Redundancy lowers a source's *priority*, never its *eligibility*. A source that is 95% repetitive is still read for the 5%.
3. **Novelty is measured against the corpus, never against arrival order.** Source #11 is not less valuable because #1–10 arrived first. Any priority score must be recomputable and order-independent.
4. **Fast results are provisional, never privileged.** Anything produced in a fast lane can be revised, qualified or overturned by later, deeper work, and is labelled as early.
5. **Promotion is always possible.** Work in a slow lane that turns out to matter must be promotable to a fast lane without restarting.
6. **Never fake progress.** Show real state ("3 of 20 sources usable, 17 deepening"), never a synthetic bar.
7. **Interactive work outranks background work, always.** Chat and explicit user actions must never queue behind bulk ingestion.
8. **Reuse → Cache → Index → Prioritize → Parallelize → Escalate — before adding a service.** No new infrastructure without a measured number justifying it.
9. **Open source and local-first is the default; the burden of proof is on the paid or proprietary alternative.** A paid or closed component must show that the free/open option materially fails on performance, reliability, capability, or development burden — measured, not asserted. Preference order: open-source and free → source-available/free for personal use → subscriptions already paid for *where officially supported* → paid API where the value is clear → proprietary infrastructure, which needs the strongest case. Paid services should accelerate the system, not become permanent load-bearing dependencies.
10. **License review is part of architecture review.** Every significant dependency is recorded with its license, self-hosting story, data portability, maintenance health, and how hard it would be to remove.
11. **No infrastructure collecting.** Each component must solve a measured problem that cannot be solved more simply. If SQLite + FTS5 works, no vector server. If the jobs table works, no broker. If in-process caching works, no Valkey. If SSE works, no WebSockets. If a small provider adapter works, no gateway.
12. **Measure before and after every rung.** A rung that cannot show its own improvement did not earn its complexity.
13. **The research contract in `docs/archive/RESEARCH-MISSION.md` §B outranks every performance goal here.** If a speedup weakens evidence, lineage, novelty detection or recoverability, the speedup loses.

---

14. **Clarity is a speed feature.** (Kyle, live 2026-09-09: *"better clarity does make things faster because then
    the user is not in the dark and they can strategize about what to do next."*) A user who can see what is
    happening makes better decisions about what to do next, and stops re-running work out of doubt. Honest,
    moving, specific progress therefore counts as a performance win and is measured as one — but only when it is
    real: a fabricated percentage is worse than a spinner, because it destroys the trust that makes every other
    signal useful.
15. **Every scheduling decision must be readable.** If the queue's order cannot be explained to the user in five
    words per rule, it is the wrong order — however good its score. (See `SCHEDULER.md`.)

## C. PERFORMANCE MODEL

**Perceived latency** — the dominant felt cost. No answer streaming; no optimistic UI (every button waits a round trip *plus* the next 3 s poll); `#srcList` and `#jobs` rebuilt wholesale via `innerHTML` on every tick, destroying expanded panels, focus and selection; serial `await` chains on load (`/api/stats` then `/api/usage`; project then a 2.34 MB source list).

**Queue latency** — the dominant real cost. 479 s median wait on findings. Workers claim on a 1.5 s poll (acceptable), but a cold `claude_code.health()` probe can run up to 90 s *inline on the worker thread* before any work begins, and there is no reserved capacity for interactive work.

**Compute latency (in-job)** — every loop is serial: findings windows, findings across sources, claims groups of 8, ranking batches. `extract_claims` at 1,233 s median is N serial 122 s local calls. Concurrency is blocked only by `providers._tl`, `_policy_tl` and `jobs._current` being thread-locals written on the worker thread — a contained fix (pass context explicitly), not an inherent limit.

**Model latency** — 11–40 s per API call, 39–122 s local. Real, largely irreducible, and the *smallest* of the top three levers.

**Retrieval latency** — 0.5 s embedding round trip + 0.10 s matrix load + 0.002 s search. The network dominates; the algorithm is not the problem.

**Database/storage latency** — fine at current scale in isolation (`list_sources` 0.083 s; `project_notes` scan 0.004 s), but pathological in aggregate because `staleness.assess` runs ~2,000 queries per `/api/sources`, on a 3 s poll, while background writers hold the single SQLite write lock.

**Frontend latency** — 2.34 MB JSON every 3 s, full re-render, no ETag/delta/cursor anywhere, plus a second independent 5 s capture loop that interleaves with the 3 s loop.

**Repeated work** — good hashing already exists (`findings.input_hash`, `claims.extraction_hash`, `relevance.input_hash`, `db.dedupe_key_for`, batch `custom_id`). Gaps: interactive findings hold results in memory and only persist at `materialize`, so a retry at window 9 of 10 redoes all 10; `research_block` recomputes `knowledge.state()` every chat turn; excerpts sit outside the cached prompt prefix and are re-sent at full price on every tool round; `_load()` runs twice per Research/Claims request.

---

## D. STACK REVIEW

Verdicts against the candidate stack. Licenses verified as stated; where a claim in the brief was slightly off it is corrected here.

| Layer | Candidate | Verdict | Why |
|---|---|---|---|
| App runtime | Python · FastAPI · Uvicorn, single process | **KEEP** | MIT. Nothing measured implicates the runtime. The 45 s congestion was expensive endpoints plus SQLite serialization, not ASGI. Fix the endpoints (R2/R3), not the server. |
| Durable store | SQLite · WAL · FTS5 · additive schema | **KEEP + MODIFY** | Public domain (not MIT — the brief's one licensing slip). 461.7 MB, 577,940 segments, 26,958 chunks, and the hot scans run in single-digit milliseconds. MODIFY = pragmas, `ANALYZE`, retention, targeted indexes (R8). |
| Vector retrieval | Python cosine → evaluate sqlite-vec | **KEEP + MODIFY; sqlite-vec REJECT (now)** | 0.002 s matmul over 26,958 vectors. sqlite-vec (Apache-2.0/MIT, healthy) would add a dependency to fix a 2 ms problem. MODIFY = cache the matrix in process. **Revisit trigger: >250k chunks, or p50 vector search >150 ms after caching.** |
| Separate vector DB | Qdrant/Chroma/etc. | **REJECT** | Fails Principle 11 outright at three orders of magnitude below where it would help. |
| Hot cache | In-process LRU · SQLite derived tables | **ADOPT** | The measured cache targets (`staleness.assess`, `knowledge.state`, embedding matrix, query embeddings) are all per-process derived state. A dict beats a server. |
| Valkey | Shared cache/queues/locks | **REJECT (now)** | BSD-3, Linux Foundation, genuinely open — and genuinely unnecessary in one process. **Revisit trigger: a second process that must share state.** Never as a home for durable research knowledge. |
| Realtime | SSE | **ADOPT** | Server→client only, which is exactly the shape of the need; the client already has POST for actions. No broker, no new dependency, works through the existing ASGI stack. |
| WebSockets / broker | — | **REJECT** | Bidirectional infrastructure for a unidirectional problem. |
| Job scheduling | Evolve the `jobs` table | **KEEP + MODIFY** | The table already has lanes, `blocked_by` dependencies, leases, heartbeats, retries, external parking, `bumped_at` promotion and dedupe keys — *more* than Celery would provide. MODIFY = reserved interactive capacity, durable partial results, automatic promotion. |
| Celery / RabbitMQ / Kafka | — | **REJECT** | Would replace a working, better-instrumented scheduler with a weaker one plus an operational burden. |
| Local model execution | Ollama · llama.cpp | **TEST (narrowly scoped)** | Both MIT, both healthy. **ADOPT-leaning for embeddings and short classification; REJECT-leaning for findings/claims — on hardware grounds, not just quality grounds.** The M3 Max will hold a 70B Q4 (~40 GB) or an MoE like gpt-oss-120b (~65 GB) with room to spare, but a 15k-token findings window is prefill-dominated, and prefill is compute-bound where this machine trades compute for bandwidth: expect roughly a minute of prompt processing per window against the 39 s the Claude Code path measures today and the API's 10.9 s. Capacity is not the constraint; tokens-of-input per second is. MoE architectures help generation far more than prefill, so they do not rescue this workload either. R9 measures it rather than assuming. |
| Current local provider | Claude Code CLI, headless | **KEEP + MODIFY (and de-risk)** | It delivers Sonnet quality at $0 and avoided $115.61 this month — real value. But it is automation over a subscription CLI, and it broke twice in one day: the health probe silently used the CLI's bare default model instead of the pinned `sonnet` (fixed in 0.45.14), and 598 `BILLING` failures parked work. Treat it as a *valuable but fragile* lane: pin the model, never probe inline, and keep a fallback that does not depend on it. |
| Embeddings | OpenAI `text-embedding-3-small` | **KEEP for current retrieval/T1; local migration measured** | R9(a) measured local `bge-m3` at 34.48 ms p50 with recall@10 1.0000 and MRR 0.8898, while `nomic-embed-text` missed the MRR floor. The local result is reserved for a later full-space migration because changing dimensions rewrites every stored blob; the frozen retrieval baseline must be re-validated on a copied corpus before any switch. T1 keeps the existing OpenAI space so derived vectors and existing chunks are comparable. Query-embedding caching remains the risk-free optimization whichever space is eventually admitted. |
| Provider abstraction | Thin native vs. AI gateway | **KEEP existing; gateway REJECT** | `providers.invoke`/`invoke_structured` already carries the ledger, typed errors, circuit breakers, schema validation, cost accounting and local/API fallback. A gateway would replace something better-instrumented than itself. This is the clearest "the existing implementation is already better" answer in the review. |
| Profiling | External observability stack | **ALTERNATIVE** | For a single-process local app, an in-app timing ledger written to SQLite and surfaced on the existing Health console (R0) beats OpenTelemetry plus a collector, and matches the `invocations`/`usage` pattern already in the codebase. |
| Cloud: Postgres + pgvector | — | **KEEP AS HYPOTHESIS — do not build** | Both permissively licensed (PostgreSQL License); pgvector keeping vectors inside Postgres is the right instinct. **The trigger is concurrency, not size:** SQLite's single-writer model, not its file size, is what will eventually force the move. R4's content-addressed storage is the seam that makes it a swap rather than a rewrite. |
| Object storage | — | **REJECT (now)** | Media already lives on disk outside the DB. Revisit only if blobs move off-machine. |

**Where I differ from the candidate stack:** three places. (1) sqlite-vec is listed as a near-term thing to *evaluate*; the measurement says defer it entirely with a numeric trigger, because evaluating it now would cost more than it saves. (2) Local model runtimes are proposed for a broad list including routine findings and candidate claim extraction; I would restrict them to embeddings and deterministic classification, because the 3× latency gain does not justify a quality drop in the two tasks that *are* the product. (3) The brief treats the Claude Code subscription lane as straightforwardly available; today's two incidents say it needs to be explicitly de-risked and never load-bearing on its own.

---

## E. PROPOSED ARCHITECTURE

Four ideas, in dependency order. Note what is absent: no Redis, no vector database, no service split, no broker. Measurement does not justify them, and Principles 8 and 11 forbid them until it does.

**1. Partial results are first class.** The backbone is not lanes — it is that a unit of analysis (a findings *window*, a claims *group*) is durably persisted the moment it completes, addressed by a content hash of `(window text, prompt version, task)` rather than by `(project, source, kind)`. This single change delivers resume-on-retry, progressive UI ("3 of 20 usable"), safe concurrency, and — for free, when it eventually matters — cross-project reuse and a clean storage seam for Postgres. The batch path already does this in `batch_items`; the interactive path must too.

**2. Admission control with reserved interactive capacity.** A small, explicit split: interactive requests (chat, explicit clicks) get guaranteed capacity that background jobs cannot consume; background work yields. Paired with a poll diet — one consolidated tick, delta/ETag responses, counts instead of payloads — this removes the measured congestion that currently makes every endpoint queue past 45 s.

**3. Bounded concurrency inside a job, with context passed explicitly.** Fan out the window loop under a small semaphore, passing `(job_id, run_id, policy)` into workers instead of relying on thread-locals, and making `findings._last_model`/`_last_call` per-call. This is where the N× lives. Note the asymmetry the hardware creates: fan-out multiplies throughput on the API and Claude Code paths (16 cores, 128 GB, work is remote and I/O-bound) but **not** on a local-model path, where a single GPU serializes requests regardless of how many threads ask. Concurrency and local inference are alternatives here, not complements.

**4. Lanes as a thin scheduling policy on top — not the foundation.** Fast/Warm/Deep is real and worth building, but it is rung 6, not rung 1, because it is worth 3× where the layers beneath it are worth 50× and N×. Triage stays deterministic and LLM-free: existing metadata, embeddings, Knowledge Map topics, Evidence Targets, source role, and a diversity score. Routing gains a *latency* input alongside cost and availability — the mechanism already exists end to end (`lane` ordering in `db.claim_job`, the dedicated API worker in `jobs.start_workers`, value ordering in `jobs.accelerate`); only the automatic decision is missing.

**Novelty under speed pressure — the mechanism that protects Principle 2.** Chunk embeddings already exist, so redundancy is computable for free: a source's similarity profile against the analyzed corpus is a *deterministic, order-independent* score. Use it two ways. Across sources, high redundancy lowers scheduling priority and never eligibility. Within a source, the chunks *least* similar to everything already known are exactly the candidate novel insights — so a mostly-repetitive source gets a cheap targeted read of its residual rather than a full deep read or an exclusion. That is "compress repeated information, not entire sources" implemented literally, and it is what lets Source #11's single critical insight survive.

---

## F. THE LADDER

Ordered by measured value ÷ risk, respecting dependencies. Each rung ships with its own before/after number.

**R0 · Permanent instrumentation.** *Changes:* a timing ledger on the hot paths (endpoint duration, queue wait, per-window model latency, cache hit/miss, first-token time), surfaced on the Health console. *Why:* every rung below claims a number; without this we are guessing again. *Benefit:* none directly — it is the measurement contract. *Depends:* nothing. *Risk:* trivial. *Verify:* the tables in §A regenerate themselves from live data.

**R1 · Stream the answer. — SHIPPED 0.49.0** (`POST /api/ask/stream`; `providers.invoke(on_text=…)` as a transport, not a second entry point; `done` carries the identical `/api/ask` payload so citations still come from the real result. Local route runs unstreamed.) *Changes:* `/api/ask` → SSE; tokens render as they arrive; real phase states ("searching · reading 6 sources · writing"). *Why:* the longest blank wait in the product (p90 51 s, max 78 s) becomes motion in under a second. *Benefit:* time-to-first-token from ~5–78 s to <1 s. *Depends:* R0. *Risk:* the citation-repair pass runs after generation — stream the draft, then reconcile citations visibly rather than silently. *Verify:* measured time-to-first-byte; existing chat regression gates unchanged.

**R2 · Poll diet and interactive reservation.** *Changes:* one consolidated tick; `/api/sources` stops returning `description` and stops `limit=10000`; a `changes?since=` (or ETag) delta endpoint; the duplicate 5 s capture loop folded in; `Promise.all` on independent loads; optimistic UI on every queue action; client-side source filtering; reserved interactive capacity. *Why:* directly fixes the measured >45 s congestion. *Benefit:* poll payload from ~2.34 MB to a few KB; interactive endpoints stay sub-second under load. *Depends:* R0. *Risk:* delta logic drifting from full-list truth — keep a periodic full reconcile. *Verify:* re-run the two-tab congestion test; every endpoint stays responsive.

**R3 · Cache derived state on revision keys.** *Changes:* memoize `staleness.assess` per `(project, revision)`; cache `knowledge.state()` and never refresh it inline in a chat request; process-level embedding-matrix cache invalidated on write; query-embedding cache; single `_load()` per Research/Claims request; move excerpts and project state inside the cached prompt prefix. *Why:* kills ~2,000 queries per poll, up to 7× matrix loads per answer, and a 0.5 s round trip on repeat queries; lifts the 37.6% prompt-cache rate. *Benefit:* `/api/sources` server time down an order of magnitude; measurably higher cache-read rate and lower per-answer cost. *Depends:* R0, R2. *Risk:* stale derived state — every cache keyed on an existing revision/hash, never on time alone. *Verify:* cache hit rate on the Health console; Tier 1 frozen totals unchanged.

**R4 · Durable, content-addressed windows.** *Changes:* persist each completed window/group immediately, keyed by a hash of `(window text, prompt version, task)`; the interactive path uses the same store as `batch_items`. *Why:* retry stops redoing 9 completed windows; partial results become displayable; cross-project reuse and a Postgres-shaped storage seam come free. *Benefit:* retry cost → only the failed unit; enables R5 and R6. *Depends:* R0. *Risk:* schema growth — additive only, with retention from R8. *Verify:* kill a job at window 9 of 10; the retry performs exactly one window.

**R5 · Bounded concurrency inside a job.** *Changes:* fan out windows/groups under a small semaphore; pass `(job_id, run_id, policy)` explicitly; per-call `_last_model`/`_last_call`. *Why:* the N× lever — `extract_claims` at 1,233 s median is serial 122 s calls. *Benefit:* long-source findings and claims fall by roughly the fan-out factor. *Depends:* R4 (safe partials), R0. *Risk:* **highest on the ladder** — losing ledger attribution, breaker keys, cancel checks or policy routing in child threads. Explicit context passing is mandatory; thread-locals must not be relied upon. *Verify:* every invocation row still carries `job_id`/`run_id`; cancel still lands mid-job; local-only jobs never touch the API.

**R6 · Fast first wave, then depth (Fast/Warm/Deep).** *Changes:* on a batch, deterministically select a small diverse high-value portfolio (metadata + embeddings + Evidence Targets + Blind Spots + diversity — no LLM triage), enqueue it `lane=priority, policy=api_requested`; the rest run warm/local; anything discovered to matter is promoted without restarting; the UI states plainly how many are usable versus deepening. *Why:* usable results in ~11 s instead of ~40 s per item, for cents, while the bulk stays free. *Benefit:* time-to-first-useful-result on a 20-source batch from ~13 min to under a minute. *Depends:* R4, R5, R2. *Risk:* fast results being treated as final — Principle 4 must be visible in the UI, not just the code. *Verify:* the regression suite in §G; the fast wave is genuinely diverse, not just the first N.

**R7 · Novelty-residual reading.** *Changes:* deterministic redundancy scoring against the analyzed corpus; high-redundancy sources drop in priority but stay eligible; within such a source, target the least-similar chunks for reading. *Why:* the mechanism that lets speed and research depth coexist. *Benefit:* less spend on genuinely repeated material, with novel insights still found. *Depends:* R4, R6. *Risk:* the scorer becoming a de facto filter — enforce by test. *Verify:* §G cases 1–3 in particular.

**R8 · Storage hygiene and retention — MEASURED PART IN CANDIDATE 0.63.36.** *Shipped candidate changes:* bounded per-connection `cache_size`, 1 GB `mmap_size`, `temp_store=MEMORY`; weekly housekeeping-owned `ANALYZE`; the four measured indexes below. Existing WAL checkpoint and terminal/orphan invocation cleanup remain the owners; no duplicate reaper was added. On a copied verified 630 MB backup, source-specific Findings changed from a 7.87 ms scan to a 0.43 ms indexed lookup; message and usage scans were removed; the broad Findings list correctly remained a scan. *Retention decision:* do not delete `usage` or `invocations`, which are authoritative cost/execution evidence. `job_events` is 17.18 MB but only 3.9 days old; measure 30 days and identify every consumer before admitting a rollup/archive cutoff. Exact evidence is in HARDENING.md. *Remaining verification:* first live housekeeping pass creates `sqlite_stat1`; observe connection memory and query plans under real load; design evidence-preserving job-event rollup only after the measurement trigger.

**R9 · Local runtime benchmark on the M3 Max (TEST rung; after Foundation prerequisites).** *Changes:* benchmark Ollama and llama.cpp on the actual machine across three separable questions, each with a pass/fail threshold set in advance so the result is a decision, not a discussion.

*(a) Embeddings — expected to pass.* Candidates `nomic-embed-text` (768d), `bge-m3`, `mxbai-embed-large`. **Adopt if** p50 query-embedding latency < 50 ms (against the measured 500 ms) **and** the retrieval baseline holds — recall@10 ≥ 0.9 and MRR within 5% of the 0.9093 live reference — on a full re-embed. Otherwise keep OpenAI plus the query cache from R3.

*(b) Short classification and triage — expected to pass.* Candidates Llama 3.1 8B, Qwen3 8B/14B, gpt-oss-20b at Q4. **Adopt if** an end-to-end routing/classification decision completes p50 < 1 s. If it does, R6's triage may optionally take a *local* model assist without violating the "no expensive LLM call before fast work" rule — a free, on-device, sub-second call is not the stage that rule was written against.

*(c) Findings/claims extraction — expected to fail, and worth failing on the record.* Run one real 15k-token window through a 70B Q4 and an MoE (gpt-oss-120b), and report prefill time separately from generation time. **Adopt only if** total wall-clock beats 10.9 s (current API parity); I predict 45–90 s, dominated by prefill. Either way the number gets written down and the question closes.

*Why:* (a) attacks retrieval's largest measured cost; (b) unlocks a free triage lane; (c) settles the "128 GB means run everything locally" intuition with evidence instead of argument. *Benefit:* unknown until measured — that is the rung. *Depends:* R0. *Risk:* scope creep from (b) into (c) — Principle 13 forbids trading findings/claims quality for latency, and (c) is expected to show the trade is not even favourable on speed. *Verify:* one written scorecard covering all three; each adopted only against its stated threshold; negative results recorded in HARDENING.md so the question is not silently reopened later.

---

## G. QUALITY REGRESSION GATES (these protect the mission from the ladder)

New test module, sorting after `tests/test_core.py`, exercising the optimized scheduler end to end:

1. Sources 1–10 assert the same idea; Source 11 repeats most of it and adds one critical novel insight — the insight is still extracted and surfaced.
2. A low-ranked, low-priority source contains the decisive exception — it is still reachable and still read before planning completes.
3. A book chapter resolves an open Tension — depth is not skipped because the book scored redundant on its first chunks.
4. Several sources share one underlying origin — lineage still collapses them for corroboration, and none is silently dropped.
5. A previously irrelevant source becomes important after the plan changes — it is promotable and re-analyzable, not permanently deferred.
6. A fast-lane result is later contradicted by deep analysis — the later evidence wins and the early result is visibly revised.
7. Deferral is never deletion: for any deferred item, a query proves it remains enumerable, promotable and analyzable.

Existing gates that must not move: Tier 1 frozen totals (chat 34/196,951; findings 9/30,297; plan 2/11,026), citation and evidence integrity at 1.0, retrieval recall@10 ≥ 0.9, and the full `release-check` suite.

---

## H. REVISIT TRIGGERS (so deferral is not amnesia)

Each rejected component gets a number that reopens the question, checked at each release: **sqlite-vec** at >250k chunks or p50 vector search >150 ms after caching; **Valkey** at a second process needing shared state; **Postgres/pgvector** at sustained SQLite write-lock contention or multi-user access, never at a file-size threshold; **object storage** when blobs must leave the machine; **WebSockets** when the client genuinely needs to push; **a broker** when the jobs table cannot express a required scheduling behaviour. Recording the trigger is what separates an engineering decision from a preference.
