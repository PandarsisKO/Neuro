# R9 local-runtime scorecard — 2026-09-12

## State: R9(a) and R9(b) decisions complete; R9(c) remains open

R9 is the admitted speed rung after the R8 immediate evidence checkpoint. The benchmark uses an isolated temporary database and the frozen retrieval fixture. It never opens, queries, changes, or re-embeds the live database.

On 2026-09-12, Homebrew installed Ollama 0.33.3 and a local Ollama service was started on loopback. Its model cache is user-local (`~/.ollama/models`) and is not repository content. This supersedes the 2026-09-11 preflight statement that a runtime and weights were unavailable. Re-runnable probes and the compact JSON scorecard are in `evals/r9/`; the frozen retrieval fixture remains under `tests/fixtures/golden/retrieval/`.

At the current checkpoint, the declared 70B candidate is downloading as the detached launchd job
`com.neuro.r9pull70` (`ollama pull llama3.1:70b`), with output in `/tmp/neuro-r9-pull-70b.err`. The chained job
`com.neuro.r9chain` waits for that model, runs the long-window probe, pulls `gpt-oss:120b`, and runs the second probe;
outputs will be `/tmp/neuro-r9-long-70b.json` and `/tmp/neuro-r9-long-120b.json`. The pull process is external
model-cache state and must never be committed.

The acceptance criteria remain those frozen in `SPEED-MISSION.md` §R9. An embedding model is eligible only when p50 query latency is below 50 ms, recall@10 is at least 0.9000, and MRR is at least 0.863835 (within 5% of the 0.9093 reference). Passing a latency probe alone never authorizes an application change or corpus re-embed. `bge-m3` clears the full isolated fixture gate and is selected as a candidate for a later full-space local migration; the production corpus remains unchanged until its versioned migration and backfill exist.

## (a) Embeddings

| Candidate | Runtime / dimensions | Latency p50 / p90 | Recall@10 | MRR | Decision |
|---|---|---:|---:|---:|---|
| `nomic-embed-text` | Ollama 0.33.3 / 768 | 13.94 ms / 15.22 ms | 1.0000 | 0.8087 | **REJECT** — speed and recall pass; MRR misses the 0.863835 floor. |
| `bge-m3` | Ollama 0.33.3 / 1024 | 34.48 ms / 35.91 ms | 1.0000 | 0.8898 | **SELECT** — clears all frozen embedding gates. |
| `mxbai-embed-large` | not downloaded | — | — | — | Not run: `bge-m3` already clears every gate, so the declared conditional candidate is unnecessary. |

`nomic-embed-text` was warmed three times, then sampled 15 times through `POST /api/embed` with a short realistic query. The retrieval run rebuilt the entire frozen fixture using the same local embedding endpoint and production hybrid FTS-plus-vector RRF path; it recorded 30 queries, 2.60 seconds total, 14.2 ms average search time, recall@10 1.0000, MRR 0.8087, and exact-first-locator 0.8462. Its measured dimension is 768. The rejection preserves OpenAI embeddings and the existing query cache.

`bge-m3` was measured with the identical three-warmup, 15-sample loop and has 1024 dimensions: p50 34.48 ms and p90 35.91 ms. The isolated fixture was fully re-embedded through the local Ollama endpoint, then searched through the production hybrid FTS-plus-vector RRF path. It produced 30 queries in 4.7 seconds (36.1 ms/query), recall@10 1.0000, MRR 0.8898, one hard-negative false positive, zero Anthropic calls, and zero OpenAI embedding ledger calls. Both recall and MRR clear the frozen adoption floors. This selects `bge-m3` for a later full-space local migration; it does **not** silently mix 1024-dimensional vectors with existing 1536-dimensional production chunk vectors or authorize a live re-embed. T1's first measurement uses the existing production space for derived objects so its chunk-to-derived comparison is defined.

## (b) Short classification and triage

The probe sends the same fixed scheduler-shaped item to Ollama's chat endpoint with temperature 0 and a 256-token
output cap. Three warmups and fifteen samples are used for each model. A response is valid when the model returns the
two requested fields with values from the declared enums; fenced JSON is accepted, matching the app's structured-output
normalization. Adoption requires valid structured output and p50 below one second. The 64-token first pass was
discarded for the reasoning models because the cap could truncate their answer before the JSON object; the table below
uses the fair 256-token rerun for every candidate.

| Candidate | Latency p50 / p90 | Valid structured outputs | Decision |
|---|---:|---:|---|
| Llama 3.1 8B | 343.368 ms / 371.299 ms | 15/15 | **ADOPT** — clears the measured speed and validity gates; integration remains separately gated by product-quality tests. |
| Qwen3 8B | 7.207 s / 9.198 s | 0/15 | **REJECT** — exceeds the one-second p50 gate and did not produce a valid bounded response. |
| Qwen3 14B | 10.974 s / 11.727 s | 0/15 | **REJECT** — exceeds the one-second p50 gate and did not produce a valid bounded response. |
| gpt-oss-20b Q4 | 3.154 s / 3.307 s | 15/15 | **REJECT** — structured output is valid, but p50 exceeds the one-second gate. |

Raw fair-run artifacts are disposable local files under `/tmp/neuro-r9-*-classification-256.json`; the compact result is
also recorded in `evals/r9/scorecard-2026-09-12.json`. No model weights or live database content are repository content.
The adopted model is a routing candidate only; no production classifier or provider path has changed.

## (c) Findings and claims extraction

**Running as of 2026-09-12 16:12 PT.** Candidates remain a 70B Q4 model and gpt-oss-120b. Record prompt prefill and
generation separately; adopt only if total wall clock beats the 10.9-second API reference and the response is valid
JSON with `findings` and `claims` arrays. No findings or claims routing changes are allowed before that evidence
exists. The first pull attempt hit inconsistent Ollama partial-cache
metadata; the missing reversible segment markers were reconstructed without deleting the downloaded blob, and the
detached pull resumed from a fresh 42 GB layer download.

## Remaining R9 arms

Long-window findings/claims measurement remains open and must be recorded here and in `HARDENING.md`. The short
classification decision is closed: Llama 3.1 8B is the only local candidate that clears the speed and validity gates;
the other three are rejected. No findings or claims routing changes are authorized until R9(c) is measured. A negative
result remains a valid closeout: retain the present provider path rather than compromising the frozen quality or latency
gates.
