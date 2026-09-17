# Speed audit — why the app feels sluggish (2026-09-17, planning only)

*Discovery and planning, no code changed. Written by Claude at Kyle's request ("Neuro Search is feeling really
sluggish even just clicking around. Trying to start a new chat took so long I gave up.") Evidence sources, in the
order CLAUDE.md prescribes: the running app's own API through Kyle's browser (`/api/perf`, direct fetch timings),
`data/server.log`, and a copy of the verified 14:22 PT backup queried in the session's own workspace. The live
database was never opened. Numbers are from today, on the live server, unless marked otherwise.*

## TL;DR

The app is not slow because the machine or the model is slow. It is slow because **background work and the
Sources-page poll hold the one SQLite write lock and the Chrome connection pool for minutes at a time**, and
everything interactive — including a one-row `INSERT` for "New chat" — queues behind them. Five concrete causes,
ranked by measured impact:

| # | Cause | Measured today | Fix size |
|---|---|---|---|
| 1 | `claims.harvest()` runs synchronously after **every** findings job, holds one write transaction for the whole pass, and scales with the project's 17k Claims / 19k notes, not with the new notes | jobs log "done" then sit in `_running` for **5–6 min**; `database is locked` on a worker, a heartbeat and a findings write at 14:40; 157 "lost the lease" warnings today, every one a false alarm | small–medium |
| 2 | `/api/projects/{id}/sources/caption-recovery` loads the **full transcript of ~770 sources (601k segment rows, 22 MB)** on every Sources poll, from every open tab, uncached | **p50 186 s** since 13:48 restart (n=50); 0.6–1.9 s even on an idle server | small |
| 3 | `/api/sources?limit=2000` — 1,515 rows, **2.5 MB**, and its derived-state caches miss almost always while jobs run (staleness 4 % hit, potential 15 %, gap_terms 6 %, rel_analysis 8 %) | **p50 92 s** since restart; `sources:potential_setup` p50 70 s; 1.3–16 s on an idle server | medium |
| 4 | The Sources poll fires ~7 requests per tick, `loadSources()` is not awaited, there is no client-side timeout or de-duplication — so a hung poll overlaps the next one until Chrome's 6-connections-per-host limit is full, and **every click in that tab (New chat included) waits for a poll that takes minutes** | 30 distinct client sockets in a 20-minute window; concurrent `/api/sources` requests visible in the log | small |
| 5 | uvicorn `--reload` watches `*.html` too: every edit to `web/index.html` (Codex made two today) restarts the server — 10 s drain timeout, in-flight local model calls killed and re-run ("re-queued 4 interrupted jobs"), every in-process cache and the perf ledger wiped cold | reloads at 13:59 and 14:22 today; each followed by a burst of cold `/api/sources` passes | trivial |

The SPEED-MISSION.md ladder already named most of this (R2 poll diet, R3 revision-keyed caches, "interactive work
outranks background work"). R2/R3 landed and then **regressed by scale and by new endpoints**: the project is now
19,098 notes / 17,254 Claims / 947 ready sources (vs. 605 findings when harvest was measured at 652 ms), the
database is 1.22 GB (vs. 461.7 MB on 09-09), and caption-recovery was added after the poll diet and never
measured.

## 1. Evidence

### 1a. What Kyle's browser sees (direct `fetch` timings, 4 samples each, ~15:10 PT, queue paused by Kyle)

| endpoint | ms (4 runs) | payload |
|---|---|---|
| `/api/version` | 8 · 5 · 6 · 10 | — |
| `/api/conversations?project_id=` | 6 · 3 · 5 · 2 | 7 KB |
| `/api/projects/{id}` | 12 · 11 · 12 · 12 | 67 KB |
| `/api/projects/{id}/tick` | 91 · 101 · 92 · 94 | — |
| `/api/projects/{id}/jobs?limit=30` | 233 · 498 · 372 · 586 | 38 KB |
| `/api/projects/{id}/sources/caption-recovery` | **1901 · 803 · 630 · 620** | 0 KB (0 candidates) |
| `/api/sources?project_id=&limit=2000` | **16462 · 2176 · 1321 · 4189** | **2,511 KB**, 1,515 rows |
| `/api/health` | 178 · 151 · 156 · 159 | 14 KB |

So on an *idle* server, one Sources poll tick is already ~2–20 s of server time and 2.5 MB. The chat endpoints
themselves are trivially fast. "New chat" is `POST /api/conversations` (one INSERT) → `GET /api/conversations` →
`GET /api/conversations/{id}` — four serial round trips of a few ms each. It cannot be slow on its own; it is slow
only when the write lock is held (cause 1) or the tab's connection pool is full (cause 4).

### 1b. What the server's own R0 ledger says (`/api/perf?days=1`, in-process since the 13:48 restart, seconds)

| key | n | p50 | p90 | max |
|---|---|---|---|---|
| `GET …/sources/caption-recovery` | 50 | **185.8** | 290.8 | 302.8 |
| `GET /api/sources` | 50 | **92.2** | 193.8 | 251.6 |
| `sources:potential_setup` | 50 | 70.6 | 165.4 | 228.2 |
| `rv.load.claims` | 127 | 19.9 | 43.2 | 73.6 |
| `sources:staleness` | 50 | 12.6 | 27.0 | 37.4 |
| `pool.gap_terms` | 21 | 9.7 | 47.4 | 194.6 |
| `GET …/jobs` | 26 | 1.7 | 2.1 | 2.8 |
| `GET …/tick` | — | ~0.09 | | |

Cache hit rates over the same window: `staleness` 2/50 (4 %), `potential` 3,854/25,300 (15 %), `gap_terms_core`
4/71 (6 %), `rel_analysis` 4/50 (8 %), `findings_clusters` 0/20. These caches are keyed on
`research|sources|jobs` revisions; while the queue is active the `jobs` revision moves every few seconds, so the
cache is correct and useless at the same time.

Queue (`db.job_timing`, 24 h): `suggest_findings` n=26 work p50 55 s, **wait p50 395 s (88 % of life waiting)**;
`extract_claims` n=7 work p50 145 s / p90 12,880 s, wait p50 500 s; `ingest_url` wait 793 s. Model p50s:
`claims.extract` local 120 s / API 32 s; `findings.extract` local 35 s; `embed` 0.83 s.

### 1c. What `server.log` shows

- **13:25, 14:11–14:44:** 157 × `lost the lease on job … — another worker owns it now`, every 30 s per job,
  for jobs that had already logged `job done` minutes earlier. Example: `4d9f885a` done 14:14:29, lease warnings
  until 14:20:09 (5 m 40 s). Cause: `jobs.execute()` calls `_after_done()` → `claims.harvest()` **after**
  `finish_job` and **before** the `finally` that pops the job from `_running`; `db.heartbeat` then finds no
  `running` row and the lease keeper reports a takeover that never happened. (L-18 already diagnosed this exact
  symptom and added an ID-only short-circuit; it fires for the *followers* — `6cfaa709` and `572ada75` cleared in
  ~1 min and ~30 s — but not for the first harvest after new notes land, which is every findings job.)
- **14:40:07** `suggest failed for beba938a…: database is locked`; **14:40:14** `heartbeat failed: database is
  locked`. The write lock was held > 30 s (the connection's `timeout=30`). `harvest()` wraps its whole note loop
  in one `db.batch()` — one implicit write transaction from the first INSERT to the end of the pass — so every
  other writer (API POSTs, `finish_job`, heartbeats, ingest stages) blocks for its duration.
- **13:59 and 14:22:** `WatchFiles detected changes in 'neurosearch/web/index.html'. Reloading...` → `worker
  drain exceeded shutdown timeout … Worker shutdown incomplete: ns-worker-local-ai-0..3, ns-worker-api-ai-1,
  ns-housekeeping` → `re-queued 4 interrupted jobs`. `cli.serve(reload=True)` passes
  `reload_includes=["*.py", "*.html"]`.
- **Model substitution, ongoing:** every `suggest_findings` today logs `claude code claude-haiku-4-5-20251001
  answered` under `model=claude-sonnet-4-6`. Not a speed issue, but it is the silent substitution CLAUDE.md
  says `release-check`/`doctor` warn on; worth confirming `db.model_mismatches()` is counting it.
- **09:43–09:44** `file is not a database` / `database disk image is malformed` on `api_reviews`,
  `api_caption_recovery_preview`, `api_sources`, `api_project_jobs`, `api_tick` — the incident the 09-17 State of
  the App attributes to a bridge-mounted read. Recorded here only because those five endpoints are exactly the
  Sources-poll fan-out: the poll is what turns any server hiccup into a frozen UI.
- **Housekeeping:** WAL checkpoints at 14:05 (69 MB), 14:11 (49.5 MB), 14:42 (104 MB), 14:54 (89 MB) — ~100 MB
  of WAL growth per half hour while findings/claims run. `DATABASE INTEGRITY CHECK FAILED` at 14:00 and 14:22
  with `duplicate_claim_evidence: 1` (a data-hygiene flag, not corruption; `result: ok`).

### 1d. Scale (copied 14:22 backup, `immutable=1`, session workspace)

| | rows | on-disk |
|---|---|---|
| `segments` | 892,583 | 87 MB (+43 MB index) |
| `chunks` | 41,740 | 327 MB |
| `job_events` | 344,696 | 60 MB (+17 MB index) |
| `jobs` | 79,508 (79,427 done) | **90 MB** — `payload` 46.7 MB |
| `invocations` / `usage` | 55,996 / 50,778 | 18.5 MB / — |
| `project_notes` | 23,537 (main project 19,098; 17,185 approved) | **168 MB**, of which ~129 MB is `embedding` |
| `project_claims` | 21,457 (main project 17,254; 4,686 proposed & un-normalized) | **152 MB**, ~116 MB `embedding` |
| `candidates` / `candidate_projects` | 15,574 / 15,268 | — |

Raw SELECT cost on the copy (fully in RAM, so a floor not a live number): all main-project claims `SELECT *`
0.29 s (0.17 s without `embedding`); all approved notes `SELECT *` 0.22 s (0.12 s without); the caption-recovery
segment walk 601,423 rows / 21.7 MB in 0.21 s. `list_project_notes` and `claims.list_for_project` are both
`SELECT *`, so each harvest and each vocabulary pass moves ~250 MB of embedding blobs through Python it never
uses (`row_to_dict` pops the column after fetching it).

`jobs` payloads: 46.7 MB across 79k rows — `api_project_jobs` reads `list_jobs(limit=5000, statuses=ACTIVE)` plus
`list_jobs(limit=400)` (payload JSON decoded per row) and filters in Python; that is the 233–586 ms seen above for a 30-row answer.

## 2. Mechanism — how the pieces compound into "everything is sluggish"

1. A local findings job finishes (35–80 s of model time) and, still inside `execute()`, runs `harvest()` for a
   17k-Claim project: read every claim and every approved note (with embeddings), build the token index, then
   one multi-minute write transaction (`add_claim`/`add_evidence`/`works.cite` per new note, then `_topic_of` over
   all ~4.7k un-normalized Claims, then `assess()` per touched Claim), then `maybe_extract()` (`unnormalized()`
   + `triage()` over the same set). The next findings job to finish waits on `_harvest_lock` and repeats the
   read side. With 4 local + 3 API workers this is near-continuous while the queue is active.
2. Meanwhile the Sources page (per open tab) polls: `tick` (fast) → because the `jobs` revision moved, `loadJobs`
   (`jobs` + `stats` + `usage` + `ai-backlog`) **and** `loadSources` (`sources` 2.5 MB + `reviews` +
   `caption-recovery` + `capture/pending` + `bootstrap`). `caption-recovery` walks 22 MB of transcript;
   `sources` recomputes staleness/potential/gap-terms because the revision key changed; both compete for the
   GIL with the harvest thread's Python loops and for the page cache with the harvest's blob reads.
3. Any endpoint that needs the write lock (`POST /api/conversations`, `finish_job`, heartbeats, ingest stages,
   `staleness.accept`, `kv_set`) waits up to 30 s and then fails with `database is locked`.
4. `loadSources()` is fire-and-forget inside `pollTick`; the next tick (3 s later) starts another one. `api()`
   has no `AbortController`/timeout and no in-flight de-duplication, so the tab accumulates hung requests until
   Chrome's per-host connection limit (6 for HTTP/1.1) is exhausted. From then on **every** request the tab
   makes — including the three tiny ones behind "New chat" — sits in the browser's queue behind requests the
   server is taking minutes to answer. That is the "gave up" experience: the server was probably fine for the
   chat call; the tab could not send it. Two or more open tabs multiply steps 2 and 4.
5. A `web/index.html` edit restarts the server: 10 s of refused connections, interrupted model calls redone at
   full cost, caches cold — and step 2 restarts from a cold cache on every open tab at once.

## 3. Plan — ordered by measured value ÷ risk, respecting the ladder's principles

Every item carries its own before/after number. Nothing below removes, filters or defers research (Principle 1);
these are reorderings, caches keyed on real revisions, and payload diets.

### P0 — stop the bleeding (a day; no schema change; all reversible)

**P0.1 Take `harvest()` out of the job's critical section, and out of one giant transaction.**
Move `_after_done()` to run after `_running.pop()` (or better, make harvest its own `$0` job kind on the `low`
lane, coalesced per project with a `dedupe_key`, so "N findings landed" → one harvest, never N). Inside
`_harvest_locked`, commit per note (or per 25 notes) instead of one `db.batch()` around the whole loop, and move
the un-normalized-Claim `_topic_of` sweep and `assess()` calls to only the Claims this harvest actually
touched/created (the sweep over all 4.7k un-normalized Claims is the same work every time). Gate: a findings job's
`_running` entry is cleared within 1 s of `job done`; no `lost the lease` line for a finished job in a 2-hour
active run; longest write-lock hold (P0.4 ledger) < 2 s.

**P0.2 Cache or index `caption_recovery_candidates`.**
Store `spoken_chars` on `sources` at ingest/recovery time (additive column, backfilled once), so the endpoint is
one indexed query; until then, `cache.get_or_compute` keyed on the project's `sources` revision. Gate: endpoint
p50 < 20 ms; zero `segments` reads on the poll path.

**P0.3 Poll hygiene in the client.**
(a) `pollTick` awaits or skips: if a `loadSources` is in flight, do not start another. (b) `api()` gets an
`AbortController` with a per-call budget (say 20 s for polls, longer for explicit actions) so a stalled poll can
never pin a connection for minutes. (c) Only the visible tab polls (`document.hidden` already gates
`checkVersion`; apply it to `pollTick`, or use `BroadcastChannel` to elect one poller across tabs). (d)
`caption-recovery` and `reviews` should not ride every `loadSources`; fetch them on the `sources` revision only.
Gate: with two tabs open and the queue active, `POST /api/conversations` measured from the browser stays
< 300 ms; at most one `/api/sources` in flight per tab.

**P0.4 Instrument the two things this audit could not measure directly**: write-lock hold time (wrap `tx()` /
`batch()` commit with a `perf` sample and log any hold > 2 s with the caller) and `_after_done` duration per
stage. Both feed the existing `/api/perf`. This is R0's contract applied to the writer side, which it never
covered.

**P0.5 Stop reloading on `*.html`.** `reload_includes=["*.py"]` only; static files are served from disk and need
no restart. Gate: editing `index.html` produces no `Reloading...` line.

### P1 — make the Sources poll cheap again (2–3 days)

**P1.1 `/api/sources` payload diet, part 2.** 1,515 rows × 1.7 KB. Options, cheapest first: drop `summary`,
`relevance_why`, `pool_potential` and `channel_url` from the list (fetch on expand — `/api/sources/{id}` already
carries the full record); paginate the list the UI actually renders (it filters client-side over `SRCG.all`, so a
server cursor is a real change but the R2 `changes?since=` idea was already designed for this); or an ETag so an
unchanged list costs 0 bytes. Gate: poll payload < 300 KB, or 0 bytes when unchanged.

**P1.2 Fix the cache keys that churn.** `staleness`, `potential`, `gap_terms`, `rel_analysis` are keyed on the
`jobs` revision because job churn *can* change a verdict. Split the key: derive from `sources`+`research`
revisions plus only the set of *active job ids for this project* (a small sorted list), not every job event.
Then a heartbeat or a job in another project no longer retires the cache. Gate: hit rate > 80 % during an active
queue (today 4–15 %).

**P1.3 `api_project_jobs` stops scanning hundreds of rows to answer 30.** Today it reads every active job app-wide plus the 400 most recent (payload JSON decoded for each) and filters in Python. Add `project_id` as a real column on `jobs` (additive,
backfilled from `payload.project_id`, indexed with `status`) so the endpoint is one indexed query. Gate: p50
< 20 ms (today 233–586 ms, and it is called on every tick that sees a change).

**P1.4 `SELECT *` on tables that carry embeddings.** `list_project_notes`, `claims.list_for_project`,
`project_vocab` and friends should select the columns they use; ~250 MB of blobs per harvest is pure waste and
evicts the page cache the API needs. Gate: harvest read phase < 0.5 s on the live project.

### P2 — structural, when P0/P1 numbers prove it is still needed

**P2.1 Interactive reservation at the process level.** The mission's Principle 7 ("interactive work outranks
background work, always") is implemented as lanes inside one process, but the GIL and the single SQLite writer
do not honour lanes. The cheapest honest version: move the AI worker threads into a second process
(`neurosearch workers`) sharing the same database, so API threads never compete with harvest/tokenizing loops
for the GIL, and a reload of the web process never kills a model call. SQLite handles two processes on one file
correctly (this is the normal case; the bridge-mount incident is a different mechanism). This is the "Valkey /
Postgres revisit trigger" moment SPEED-MISSION.md §H described — but a second *process* on SQLite is the step
before either of those, and needs no new infrastructure.

**P2.2 SSE for the Sources/Jobs panes** (already ADOPTed in §D, shipped only for chat): the server pushes
`rev` changes; the client fetches only what moved. Kills the 3 s poll entirely.

**P2.3 Retention on `jobs.payload`/`job_events`** (the R8 observation window ends 2026-10-11): 90 MB of job
rows, 46 MB of it payload, most of it terminal — the active-jobs query pays for all of it today. Nothing to
decide before the window closes; noting it so P1.3's index is designed with the rollup in mind.

## 4. What this audit did NOT establish (measure before believing)

- Exactly which lines inside `_harvest_locked` cost the 5 minutes. The reads are ≤ 0.5 s on a copy; the
  suspects are the per-note `works.cite` → `candidates.remember` / `knowledge.add_target` path, `assess()` per
  touched Claim, and lock waits on other writers. P0.4's stage timings answer this in one active hour.
- How many tabs Kyle had open when "New chat" hung. The log shows 30 distinct client sockets in 20 minutes,
  which is consistent with 2–4 tabs plus the extension. If it was one tab, cause 4 still applies (overlapping
  polls alone fill six connections in ~20 s of a hung `/api/sources`).
- Whether the 09:43 corruption burst had a second cause. Out of scope here; the 09-17 State of the App owns it.

## 5. Verification plan (the numbers each rung must reproduce)

1. **Before:** one active hour with the queue running, two Sources tabs open. Record from `/api/perf`: p50/p90 of
   `GET /api/sources`, `caption-recovery`, `jobs`; cache hit rates; count of `lost the lease` and
   `database is locked` lines; and from the browser, `POST /api/conversations` latency sampled every 30 s.
2. **After P0:** same hour, same tabs. Pass = no `lost the lease` for finished jobs, no `database is locked`,
   `POST /api/conversations` p90 < 300 ms, `caption-recovery` p50 < 20 ms.
3. **After P1:** poll payload and hit rates as gated above; `/api/sources` p50 < 300 ms on an active queue.
4. **Standing gates unchanged:** full pytest, Tier 1 frozen totals, `release-check`; the harvest race test from
   L-16 (8 jobs / 4 threads) must still find every note — moving harvest to a coalesced job must not reopen the
   lost-note bug it fixed.

## 6. Interim, today, without code

- Keep "Pause background" on while working in the app (Kyle did this at ~15:00; the idle-server numbers in §1a
  are what the app feels like when it is not fighting itself).
- One Sources tab at a time; leave the app on a chat view when not watching sources (only the Sources view
  polls).
- Codex: avoid editing `web/index.html` while Kyle is using the app until P0.5 lands; `.js`/`.css` edits do not
  reload.

---

## 7. P0 execution record — 0.63.92 (2026-09-17, 15:45–16:20 PT)

Kyle narrowed the SPEED mission to this P0 ("foreground user actions must remain responsive regardless of
background research, maintenance, polling, queue size, or number of open Neuro tabs"). Five commits on `main`,
each with the regression gate for the failure class it removes: `3d69fd4` P0.1 · `9835bfa` P0.2 · `f3ade92`
P0.3 · `7f3de01` P0.4 (+ `db:write_hold` ledger, `spoken_chars` column) · `c42930e` P0.5 · `aa43fb4` 0.63.92.
New gates: `test_s65_poll_containment` (node vm over the shipped `api.js`), `test_s66_harvest_isolation`,
`test_s67_caption_recovery_incremental`, `test_s68_sources_list_diet`, `test_s69_html_edits_do_not_restart`,
`test_s70_write_hold_ledger`. Suite (Linux VM, Python 3.12, fake AI, private data dir; 150 modules in six
`-n 4` chunks): 2,507 passed, 2 failed — both pre-existing on the base checkout in this environment
(`test_j3_fallback::test_doctor_is_fast_and_release_check_writes_an_artifact`,
`test_s43_foundation::test_native_worker_restart_recovers_inflight_fake_provider_job`); `test_core::
test_ask_tool_loop` flaked once on the base checkout and passed on every run of the changed tree. A from-zero
run on Kyle's Mac (`pytest -n 4 --dist=loadscope`) is still owed before this is called released.

### BEFORE → AFTER (Neuro's own API, measured from Kyle's browser; live database never opened)

| gate | BEFORE (§1, 0.63.91) | AFTER (0.63.92, idle queue, 5 samples) | target |
|---|---|---|---|
| New Chat (POST + list + open, end-to-end) | "took so long I gave up" (writer held for minutes; tab's connections full) | **8 · 11 · 11 ms** | < 300 ms p90 under load |
| trivial interactive (`/api/version`, `/api/conversations`) | 5–10 ms / 2–6 ms idle; queued behind polls under load | 5–9 ms / 3–5 ms | sub-second p50, no minute tails |
| `/api/sources` (1,515 rows) | 2,511 KB · 1.3–16 s idle · **p50 92 s** loaded | **1,688 KB** · 266–272 ms warm (1.8 / 2.7 s on the two cold requests after restart) | < 300 KB or 0 bytes unchanged (P1), p50 < 300 ms loaded |
| `caption-recovery` | 620–1,900 ms idle · **p50 186 s** loaded · 601k segment rows per call | **12–16 ms**, zero segment reads | p50 < 20 ms ✓ |
| `/api/projects/{id}/jobs` | 233–586 ms | 209–226 ms (unchanged — P1.3) | < 20 ms (P1) |
| overlapping `/api/sources` from one tab | unbounded (fire-and-forget every 3 s) | **1** in flight max; hidden tab: 0 polls in 50 s | ≤ 1 ✓ |
| quiet requests on the wire at once | up to the browser's 6 | ≤ 2 (4 connections always free for clicks) | ✓ |
| longest SQLite write-lock hold | unmeasured (> 30 s inferred from `database is locked`) | `db:write_hold` on `/api/perf`; harvest chunks of 25 notes | < 2 s (warning threshold) — to be read off after one active hour |
| `database is locked` incidence | 3 lines in one afternoon (14:40) | 0 since 16:09 restart (queue idle) | 0 in an active hour |
| false "lost the lease" for finished jobs | 157 lines, 13:25–14:44 | structurally impossible (hook runs after `_running.pop`) — 0 since restart | 0 in an active hour |
| findings job reaches truthful terminal state | "done" then 5–6 min still `running` to the lease keeper | `done` row + `_running` cleared before any post-processing (gate S66) | ✓ |
| server restarts from HTML-only edits | 2 today (13:59, 14:22), each killing in-flight model calls | watch is `*.py` only (gate S69) | 0 ✓ |

**Not yet measured — needs the queue running.** Every "loaded" cell above still carries the BEFORE number.
Background was paused by Kyle at ~15:00 and the queue drained before 0.63.92 went live, so the "while
background findings/Claims work is active" half of the gate has no AFTER yet. To close it: unpause background
(a paid `extract_claims` fast pass may follow — Kyle's call), open one Sources tab, and after ~an hour read
`/api/perf?days=1` (`GET /api/sources`, `caption-recovery`, `db:write_hold` p50/p90/max, cache hit rates) and
`server.log` (`database is locked`, `lost the lease`, `write lock held`), and time New Chat from the browser.
The exit condition is met on those numbers, not on the idle ones.

### What was NOT done (deliberately, per the P0 scope)

- No SQLite timeout change, no new infrastructure, no model or cache-key work (P1.2 cache churn, P1.3 jobs
  index, P1.4 `SELECT *` on embedding tables, P2 worker process / SSE are unchanged — see §3).
- One poller across tabs: not built. Hidden tabs no longer poll at all, which covers the measured case (one
  visible tab per window). Revisit only if two visible Sources tabs are common.
- `/api/sources` is still 1.7 MB: the remaining bytes are fields the row template genuinely renders (`value`
  336 KB, `summary` 207 KB, thumbnails/titles/urls). Going lower means pagination or ETag/delta (P1.1), which
  the instruction sequences after the basic endpoint is bounded — it now is.
- The initial project open still fires ~8 loud requests at once (2 over the browser's limit for a moment);
  that is `openProject`'s fan-out, not the poll, and was out of scope.
- The live server's `claude-haiku-4-5` substitution under `model=claude-sonnet-4-6` on every `suggest_findings`
  today (§1c) is untouched and unrelated to speed.

### Process note

The dev server watches `neurosearch/*.py`, so the first four rungs' edits — made directly in the repo before
this was caught — restarted the live server five times between 15:49 and 15:56 PT (background was paused;
no job was interrupted; the `spoken_chars` backfill ran once, 1,462 rows). From P0.4 on, work happened in an
isolated copy and was copied in once per rung: one restart at 16:09 for 0.63.92. `.git/index.lock` and
`.git/HEAD.lock` were zero-byte leftovers stamped 21:53:08 UTC — one second after commit `22b6b5b` — with no
git process behind them; removed with Kyle's delete approval. Older zero-byte `refs/tags/v0.6x.lock` files
and `objects/maintenance.lock` (2026-09-10/11) remain; they block only tag updates and `git maintenance`.
