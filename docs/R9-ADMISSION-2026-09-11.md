# R9 local-runtime scorecard — 2026-09-12

## State: embedding decision complete; integration not yet started

R9 is the admitted speed rung after the R8 immediate evidence checkpoint. The benchmark uses an isolated temporary database and the frozen retrieval fixture. It never opens, queries, changes, or re-embeds the live database.

On 2026-09-12, Homebrew installed Ollama 0.33.3 and a local Ollama service was started on loopback. Its model cache is user-local (`~/.ollama/models`) and is not repository content. This supersedes the 2026-09-11 preflight statement that a runtime and weights were unavailable.

The acceptance criteria remain those frozen in `SPEED-MISSION.md` §R9. An embedding model is eligible only when p50 query latency is below 50 ms, recall@10 is at least 0.9000, and MRR is at least 0.863835 (within 5% of the 0.9093 reference). Passing a latency probe alone never authorizes an application change or corpus re-embed. `bge-m3` clears the full isolated fixture gate and is the selected embedding system for the next integration slice; the production corpus remains unchanged until its versioned migration and backfill exist.

## (a) Embeddings

| Candidate | Runtime / dimensions | Latency p50 / p90 | Recall@10 | MRR | Decision |
|---|---|---:|---:|---:|---|
| `nomic-embed-text` | Ollama 0.33.3 / 768 | 13.94 ms / 15.22 ms | 1.0000 | 0.8087 | **REJECT** — speed and recall pass; MRR misses the 0.863835 floor. |
| `bge-m3` | Ollama 0.33.3 / 1024 | 34.48 ms / 35.91 ms | 1.0000 | 0.8898 | **SELECT** — clears all frozen embedding gates. |
| `mxbai-embed-large` | not downloaded | — | — | — | Not run: `bge-m3` already clears every gate, so the declared conditional candidate is unnecessary. |

`nomic-embed-text` was warmed three times, then sampled 15 times through `POST /api/embed` with a short realistic query. The retrieval run rebuilt the entire frozen fixture using the same local embedding endpoint and production hybrid FTS-plus-vector RRF path; it recorded 30 queries, 2.60 seconds total, 14.2 ms average search time, recall@10 1.0000, MRR 0.8087, and exact-first-locator 0.8462. Its measured dimension is 768. The rejection preserves OpenAI embeddings and the existing query cache.

`bge-m3` was measured with the identical three-warmup, 15-sample loop and has 1024 dimensions: p50 34.48 ms and p90 35.91 ms. The isolated fixture was fully re-embedded through the local Ollama endpoint, then searched through the production hybrid FTS-plus-vector RRF path. It produced 30 queries in 4.7 seconds (36.1 ms/query), recall@10 1.0000, MRR 0.8898, one hard-negative false positive, zero Anthropic calls, and zero OpenAI embedding ledger calls. Both recall and MRR clear the frozen adoption floors. This selects `bge-m3` for T1's versioned derived-knowledge vectors; it does **not** silently mix 1024-dimensional vectors with existing 1536-dimensional production chunk vectors or authorize a live re-embed.

## (b) Short classification and triage

Not started. Candidates remain Llama 3.1 8B, Qwen3 8B/14B, and gpt-oss-20b at Q4. Adopt only if end-to-end routing/classification p50 is below one second.

## (c) Findings and claims extraction

Not started. Candidates remain a 70B Q4 model and gpt-oss-120b. Record prompt prefill and generation separately; adopt only if total wall clock beats the 10.9-second API reference. No findings or claims routing changes are allowed before that evidence exists.

## Remaining R9 arms

Short classification/triage and long-window findings/claims measurements remain open and must be recorded here and in `HARDENING.md`. They are separate decisions; they do not block T1, because R9(a) has selected and recorded its embedding system. No findings or claims routing changes are authorized until their own measurements pass. A negative result remains a valid closeout: retain the present provider path rather than compromising the frozen quality or latency gates.
