# MISSION: SPEED, RESPONSIVENESS, AND EFFICIENT INTELLIGENCE

*Kyle's mission, filed 2026-09-09 at 0.45.14. Read with `CLAUDE.md` (architecture map), `LOCAL-AI-PROVIDER.md` (L1 routing), `RESEARCH-MISSION.md` (the research quality contract this must not violate) and `EXPANSION.md` (rung log). Every number below was measured against Kyle's live 461.7 MB database and running server on 2026-09-09, not estimated.*

## NORTH STAR

The more Neuro Search has already researched, the less work it should need to repeat. Fast answers come from accumulated understanding; deep research continues behind them. **Make Neuro Search faster by remembering and scheduling more intelligently, never by looking at less.**

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

1. *The embedding matrix reload.* All 26,958 vectors (165.6 MB) load in **0.10 s warm / 0.78 s cold**, and the actual similarity matmul is **0.002 s**. Worth a process-level cache (it happens up to ~7× per answer), but it is not a crisis and it does **not** justify sqlite-vec, FAISS, or a vector database. Brute force is fine to roughly 250k chunks.
2. *Cross-project analysis reuse.* Only **2 sources of 823** belong to more than one project. Building a cross-project cache today would be near-worthless. Design the seam; do not build the layer.
3. *The missing `project_notes` index.* The table has 10,503 rows and zero indexes, yet the hot filtered scan runs in **0.004 s**. Add the index as cheap insurance at 10× scale, not as a priority.

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
9. **Measure before and after every rung.** A rung that cannot show its own improvement did not earn its complexity.
10. **The research contract in `RESEARCH-MISSION.md` §B outranks every performance goal here.** If a speedup weakens evidence, lineage, novelty detection or recoverability, the speedup loses.

---

## C. PERFORMANCE MODEL

**Perceived latency** — the dominant felt cost. No answer streaming; no optimistic UI (every button waits a round trip *plus* the next 3 s poll); `#srcList` and `#jobs` rebuilt wholesale via `innerHTML` on every tick, destroying expanded panels, focus and selection; serial `await` chains on load (`/api/stats` then `/api/usage`; project then a 2.34 MB source list).

**Queue latency** — the dominant real cost. 479 s median wait on findings. Workers claim on a 1.5 s poll (acceptable), but a cold `claude_code.health()` probe can run up to 90 s *inline on the worker thread* before any work begins, and there is no reserved capacity for interactive work.

**Compute latency (in-job)** — every loop is serial: findings windows, findings across sources, claims groups of 8, ranking batches. `extract_claims` at 1,233 s median is N serial 122 s local calls. Concurrency is blocked only by `providers._tl`, `_policy_tl` and `jobs._current` being thread-locals written on the worker thread — a contained fix (pass context explicitly), not an inherent limit.

**Model latency** — 11–40 s per API call, 39–122 s local. Real, largely irreducible, and the *smallest* of the top three levers.

**Retrieval latency** — one OpenAI embedding round trip per search (0.5 s median), plus 0.10 s warm matrix load, plus 0.002 s of actual search. Healthy; cache the matrix and the query embedding and it is finished.

**Database/storage latency** — fine at current scale in isolation (`list_sources` 0.083 s; `project_notes` scan 0.004 s), but pathological in aggregate because `staleness.assess` runs ~2,000 queries per `/api/sources`, on a 3 s poll, while background writers hold the single SQLite write lock.

**Frontend latency** — 2.34 MB JSON every 3 s, full re-render, no ETag/delta/cursor anywhere, plus a second independent 5 s capture loop that interleaves with the 3 s loop.

**Repeated work** — good hashing already exists (`findings.input_hash`, `claims.extraction_hash`, `relevance.input_hash`, `db.dedupe_key_for`, batch `custom_id`). Gaps: interactive findings hold results in memory and only persist at `materialize`, so a retry at window 9 of 10 redoes all 10; `research_block` recomputes `knowledge.state()` every chat turn; excerpts sit outside the cached prompt prefix and are re-sent at full price on every tool round; `_load()` runs twice per Research/Claims request.

---

## D. PROPOSED ARCHITECTURE

Four ideas, in dependency order. Note what is *absent*: no Redis, no vector database, no service split. Measurement does not justify them, and Principle 8 forbids them until it does.

**1. Partial results are first class.** The backbone is not lanes — it is that a unit of analysis (a findings *window*, a claims *group*) is durably persisted the moment it completes, addressed by a content hash of `(window text, prompt version, task)` rather than by `(project, source, kind)`. This single change delivers resume-on-retry, progressive UI ("3 of 20 usable"), safe concurrency, and — for free, when it eventually matters — cross-project reuse. The batch path already does this in `batch_items`; the interactive path must too.

**2. Admission control with reserved interactive capacity.** A small, explicit split: interactive requests (chat, explicit clicks) get guaranteed capacity that background jobs cannot consume; background work yields. Paired with a poll diet — one consolidated tick, delta/ETag responses, counts instead of payloads — this removes the measured congestion that currently makes every endpoint queue past 45 s.

**3. Bounded concurrency inside a job, with context passed explicitly.** Fan out the window loop under a small semaphore, passing `(job_id, run_id, policy)` into workers instead of relying on thread-locals, and making `findings._last_model`/`_last_call` per-call. This is where the N× lives.

**4. Lanes as a thin scheduling policy on top — not the foundation.** Fast/Warm/Deep is real and worth building, but it is rung 6, not rung 1, because it is worth 3× where the layers beneath it are worth 50× and N×. Triage stays deterministic and LLM-free: existing metadata, embeddings, Knowledge Map topics, Evidence Targets, source role, and a diversity score. Routing gains a *latency* input alongside cost and availability — the mechanism already exists end to end (`lane` ordering in `db.claim_job`, the dedicated API worker in `jobs.start_workers`, value ordering in `jobs.accelerate`); only the automatic decision is missing.

**Novelty under speed pressure — the mechanism that protects Principle 2.** Chunk embeddings already exist, so redundancy is computable for free: a source's similarity profile against the analyzed corpus is a *deterministic, order-independent* score. Use it two ways. Across sources, high redundancy lowers scheduling priority and never eligibility. Within a source, the chunks *least* similar to everything already known are exactly the candidate novel insights — so a mostly-repetitive source gets a cheap targeted read of its residual rather than a full deep read or an exclusion. That is "compress repeated information, not entire sources" implemented literally, and it is what lets Source #11's single critical insight survive.

---

## E. THE LADDER

Ordered by measured value ÷ risk, respecting dependencies. Each rung must ship with its own before/after number.

**R0 · Permanent instrumentation.** *Changes:* a timing ledger on the hot paths (endpoint duration, queue wait, per-window model latency, cache hit/miss), surfaced on the Health console. *Why:* every rung below claims a number; without this we are guessing again. *Benefit:* none directly — it is the measurement contract. *Depends:* nothing. *Risk:* trivial. *Verify:* the table in §A regenerates itself from live data.

**R1 · Stream the answer.** *Changes:* `/api/ask` → SSE; tokens render as they arrive; real phase states ("searching · reading 6 sources · writing"). *Why:* the longest blank wait in the product (p90 51 s, max 78 s) becomes motion in under a second. *Benefit:* time-to-first-token from ~5–78 s to <1 s. *Depends:* R0. *Risk:* the citation-repair pass runs after generation — stream the draft, then reconcile citations visibly rather than silently. *Verify:* measured time-to-first-byte; existing chat regression gates unchanged.

**R2 · Poll diet and interactive reservation.** *Changes:* one consolidated tick; `/api/sources` stops returning `description` and stops `limit=10000`; a `changes?since=` (or ETag) delta endpoint for the poller; the duplicate 5 s capture loop folded in; `Promise.all` on independent loads; optimistic UI on every queue action; client-side source filtering; reserved interactive capacity so background jobs cannot starve chat. *Why:* directly fixes the measured >45 s congestion. *Benefit:* poll payload from ~2.34 MB to a few KB; interactive endpoints stay sub-second under load. *Depends:* R0. *Risk:* delta logic drifting from full-list truth — keep a periodic full reconcile. *Verify:* re-run the two-tab congestion test; every endpoint stays responsive.

**R3 · Cache derived state on revision keys.** *Changes:* memoize `staleness.assess` per `(project, revision)`; cache `knowledge.state()` per turn and never refresh inline in a chat request; process-level embedding matrix cache invalidated on write; cache query embeddings; single `_load()` per Research/Claims request; move excerpts and project state inside the cached prompt prefix. *Why:* kills ~2,000 queries per poll and up to 7× matrix loads per answer, and lifts the 37.6% prompt-cache rate. *Benefit:* `/api/sources` server time down an order of magnitude; measurably higher cache-read rate and lower per-answer cost. *Depends:* R0, R2. *Risk:* stale derived state — every cache keyed on an existing revision/hash, never on time alone. *Verify:* cache hit rate on the Health console; Tier 1 frozen totals unchanged.

**R4 · Durable, content-addressed windows.** *Changes:* persist each completed window/group immediately, keyed by a hash of `(window text, prompt version, task)`; interactive path uses the same store as `batch_items`. *Why:* retry stops redoing 9 completed windows; partial results become displayable; cross-project reuse becomes free later. *Benefit:* retry cost → only the failed unit; enables R5 and R6. *Depends:* R0. *Risk:* schema growth — additive only, with retention from R8. *Verify:* kill a job at window 9 of 10; the retry performs exactly one window.

**R5 · Bounded concurrency inside a job.** *Changes:* fan out windows/groups under a small semaphore; pass `(job_id, run_id, policy)` explicitly; per-call `_last_model`/`_last_call`. *Why:* the N× lever — `extract_claims` at 1,233 s median is serial 122 s calls. *Benefit:* long-source findings and claims fall by roughly the fan-out factor. *Depends:* R4 (safe partials), R0. *Risk:* **highest on the ladder** — losing ledger attribution, breaker keys, cancel checks or policy routing in child threads. Explicit context passing is mandatory; thread-locals must not be relied upon. *Verify:* every invocation row still carries `job_id`/`run_id`; cancel still lands mid-job; local-only jobs never touch the API.

**R6 · Fast first wave, then depth (Fast/Warm/Deep).** *Changes:* on a batch, deterministically select a small diverse high-value portfolio (metadata + embeddings + Evidence Targets + Blind Spots + diversity — no LLM triage), enqueue it `lane=priority, policy=api_requested`; the rest run warm/local; anything discovered to matter is promoted without restarting; the UI states plainly how many are usable versus deepening. *Why:* usable results in ~11 s instead of ~40 s per item, for cents, while the bulk stays free. *Benefit:* time-to-first-useful-result on a 20-source batch from ~13 min to under a minute. *Depends:* R4, R5, R2. *Risk:* fast results being treated as final — Principle 4 must be visible in the UI, not just the code. *Verify:* the regression suite in §F; the fast wave is genuinely diverse, not just the first N.

**R7 · Novelty-residual reading.** *Changes:* deterministic redundancy scoring against the analyzed corpus; high-redundancy sources drop in priority but stay eligible; within such a source, target the least-similar chunks for reading. *Why:* the mechanism that lets speed and research depth coexist. *Benefit:* less spend on genuinely repeated material, with novel insights still found. *Depends:* R4, R6. *Risk:* the scorer becoming a de facto filter — enforce by test. *Verify:* §F cases 1–3 in particular.

**R8 · Storage hygiene and retention.** *Changes:* `cache_size`, `mmap_size`, `temp_store=MEMORY`; scheduled `ANALYZE`; WAL checkpoint policy; indexes on `project_notes(project_id, status, source_id)`, `messages(conversation_id)`, `usage(kind, source_id)`, `jobs(kind, status)`; retention for `job_events`/`invocations`/`usage`; reaper for the 432 stuck `in_flight` rows. *Why:* cheap insurance that keeps the numbers above true at 10× scale; the `in_flight` leak is a correctness defect today. *Benefit:* small now, decisive later. *Depends:* nothing (may land any time; the reaper should land early). *Risk:* low — additive, no destructive migration. *Verify:* `sqlite_stat1` present; no `in_flight` row older than its lease; query plans unchanged or better.

---

## F. QUALITY REGRESSION GATES (these protect the mission from the ladder)

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

## G. EXPLICITLY NOT DOING (and why)

No vector database, sqlite-vec or FAISS — measured 0.002 s matmul over 26,958 vectors; revisit past ~250k chunks. No Redis/Valkey — there is one process; a process-level cache plus SQLite derived tables is strictly simpler and sufficient. No cross-project reuse layer — 2 of 823 sources qualify today; R4's content addressing leaves the seam open for when that changes. No service split or distributed queue — the local-first product does not need it, and R2–R5 leave clean boundaries for a future cloud deployment. No LLM-based triage stage — triage must be free and instant, or it becomes the latency it was meant to remove.
