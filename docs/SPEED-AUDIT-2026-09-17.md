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

---

## 8. P0 loaded validation — 0.63.92 + `2e386b7` + `0668899` (2026-09-17, 16:35–17:25 PT)

**Load.** Kyle ruled out spending API money to manufacture load, and the queue was empty and paused. The $0
workload that reproduces the contention class is `POST /api/projects/{id}/research/refresh` with
`extract=false`: `claims.ensure` — `harvest` + `assess_project` over 17k Claims + `knowledge.refresh`
(tension detection, target dedupe, community synthesis, node rebuild). It is the same pass `extract_claims`
runs at the end of every 2-group yield and `refresh_research` runs on the low lane, so it stands in for
"Claims extraction is running" without a model call. Run back-to-back from a second tab (each pass 300–520 s),
three runs of 8–12 min. Foreground: a probe in the app tab every ~10 s — New Chat (POST + list + open +
delete), `/api/version`, `/api/stats`, a view switch Sources → Findings → Research → Chat — plus, in run 3, the
page's own poll loop live on a visible Sources tab. The live database was never opened.

**Run 1 caught the failure class again.** The new `db:write_hold` ledger logged
`write lock held 12.1s by knowledge.py:416 dedupe_targets` on the first pass, and on the next:
`12.2s dedupe_targets` immediately followed by `10.0s api_create_conversation` — New Chat's one-row INSERT
waiting behind a pairwise-Jaccard loop that ran inside `db.tx()`. Fixed (`2e386b7`: decide outside, write in
one short `executemany`). Run 2 then surfaced the next-longest hold, `3.5s community.synthesize` (the
evidence walk over every Claim inside the transaction) with `assess_target` queued 3.6 s behind it. Fixed
(`0668899`). Both have gates (S66, K9). Neither would have been visible without the ledger.

| gate (Kyle's list) | run 1 (before fixes) | run 3 (after both fixes, visible tab, live poll) | verdict |
|---|---|---|---|
| New Chat while background processing is active | p50 129 ms · p90 891 ms · **max 10.5 s** (3 rounds > 1 s, each on a `dedupe_targets` hold) | **p50 80 ms · p90 626 ms · max 2.2 s** (1 of 43 rounds > 1 s; server-side POST max 0.64 s, writer peak 0.19 s) | pass |
| trivial endpoint (`/api/version`, `/api/stats`) | 4 ms / 146 ms p50 | 4 ms / 151 ms p50, max 191 / 360 ms | pass |
| view switching Sources → Findings → Research → Chat | requests complete; slowest per switch ≤ 2.3 s | requests complete; no switch's requests exceeded the probe's 1.5 s window in run 3 | pass |
| `/api/sources` under load (server) | p50 5.4 s · p90 19.4 s · max 25.7 s | **p50 5.6 s · p90 11.7 s · max 27.6 s** (page-observed 5–27 s over 20 refreshes) | **not met — see below** |
| `caption-recovery` under load (server) | p50 298 ms · max 10.4 s | p50 216 ms · p90 482 ms · max 12.1 s | p50 pass (15 ms idle → 216 ms is GIL sharing); one 12 s outlier unexplained |
| max simultaneous quiet requests | — | `/api/sources` in flight: **1** (20 refreshes); poll-path requests: 5 at a click fan-out (loud, uncapped by design), quiet cap 2 held | pass |
| longest `db:write_hold` | **12.4 s** (`dedupe_targets`), 10.0 s (victim) | **0.19 s** peak over the whole run | pass |
| `database is locked` | 0 | 0 | pass |
| false lost-lease warnings | 0 | 0 | pass |
| `harvest_claims` completes and catches mid-run notes | not observed live — the queue was paused and no findings job ran; gate S66 proves both deterministically | owed live, first time a findings job completes with the queue running | open (deterministic gate green) |
| foreground actions < ~1 s, no multi-second tail from Neuro itself | New Chat tail 10.5 s ← Neuro (writer hold) | one 2.2 s New Chat round (not a writer hold; threadpool/GIL under a CPU-bound pass); everything else sub-second | pass, with the Sources caveat |
| two visible Neuro tabs | — | not run: the extension cannot open a second window; one visible + one hidden tab: the hidden tab made 0 poll requests in 50 s | owed (Kyle opens a second window) |

Run 2 (dedupe fixed, synthesize not yet, app tab hidden so its poll loop was off): New Chat p50 113 ms,
p90 1.1 s, max 50 s — the 50 s was the first round after the `.py` reload that delivered the fix, while uvicorn
waited for the previous pass's 300 s request to drain ("Waiting for connections to close"); a delivery
artefact, not load. Excluding it, max 1.5 s. Writer peak 3.56 s (synthesize).

**Verdict: P0 closed for what it was scoped to.** Lightweight actions — New Chat, trivial endpoints, view
switching — stay sub-second at p50 and p90 with the heaviest $0 research pass running continuously, the writer
is never held past 0.2 s, and the browser cannot stack refreshes. Poll timeout 20 s, quiet cap 2, harvest chunk
25, hidden-tab pause: unchanged, per Kyle — measured boundaries, not tunables.

**What the loaded run says is next, with numbers (not started, per Kyle):**
1. **The Sources list under a running research pass is 5–27 s, not because of locks.** Every `knowledge.refresh`
   rewrites the knowledge nodes, so `db.project_research_revision` moves on every pass and every revision-keyed
   research cache misses every time: `staleness` 0/22 hits, `potential` **0/11,132**, `gap_terms_core` 0. Each
   `/api/sources` then recomputes the 452 skipped rows' potential plus gap terms plus staleness from cold, while
   sharing the GIL with the pass. Idle the same request is 270 ms. This is the cache-key churn the audit filed as
   P1.2 and belongs in Kyle's ladder step 2 (request-path diet): key the source-side caches on what they read,
   not on the whole research fingerprint.
2. **GIL sharing is the floor under everything.** `caption-recovery` — one indexed query, 15 ms idle — is 216 ms
   p50 with a CPU-bound pass in the same process, and `/api/version` p90 goes 5 → 76 ms. No lock is involved.
   That ceiling only moves when background work leaves the API process (audit P2.1) — a later, larger decision.
3. **Research refresh itself is 300–520 s of single-threaded CPU per pass**, dominated by `assess_project`
   over 17k Claims, `assess_target`, and the node rebuild. It runs on the `low` lane today; it is the load.

---

## 9. After P0: release hygiene, R8 (narrow), and the `/api/sources` cache-churn rung (2026-09-17, 17:40–19:20 PT)

Kyle's sequence: release hygiene → R8 → find out why `/api/sources` was 5–27 s when research state changed with
the writer idle → R4 → R5 → R9. Constraint for the Sources work: no caching by time; identify the dependency
that actually changed; cache each derived component against the narrowest durable revision that can change its
answer.

**Release hygiene.** `release-check` PASS on `0bfd6ce` (artifact `evals/release/release-check-0.63.92-0bfd6ce-
20260918-004814`); the whole suite on the same tree 2,512 passed, 0 failed, in six chunks (the VM cannot keep one
process alive for the full run). Push is pending from a Mac-side session (no GitHub credential here).

**R8, narrow (`0080d1f`).** `jobs.project_id` / `jobs.source_id` as VIRTUAL generated columns over the payload
(cannot drift; legal to add to the live database; no backfill) + two indexes; `api_project_jobs` runs two
index-ordered queries merged in Python — one `OR` query measured 205 ms on a copy of the 79k-row table because
SQLite unions both scans and re-sorts; split, 26 ms. Live: **209–226 ms → 30–33 ms.** The rest of R8 verified on
the 14:22 backup copy and left alone: `sqlite_stat1` present (79 rows), weekly `ANALYZE` recorded, no `in_flight`
invocations, 0 freelist pages, WAL checkpointing at ~100 MB; retention stays under its observation until
2026-10-11. Not a performance investigation.

**Why `/api/sources` was 5–27 s: the research fingerprint moved when nothing changed.** Every research-derived
cache the endpoint reads (`staleness`, `potential`, `gap_terms_core`, `rel_analysis`) keys on
`db.project_research_revision` — COUNT‖MAX(updated_at) over Claims, nodes, tensions, analyses, targets, project.
Watching `/tick`'s revision every 4 s during a live pass, and reading the code for each writer, found FIVE places
the fingerprint moved with no change in the answer, fixed in order of discovery, each proven live before the next:

| # | writer | what it did every pass | fix (commit) |
|---|---|---|---|
| 1 | `claims.assess()` | wrote all six verdict columns + `updated_at` on every Claim (17k) | write only when the verdict differs (`3199711`) |
| 2 | `knowledge.refresh()` | DELETE + re-INSERT every node with a fresh timestamp | rewrite only when the node set differs (`3199711`) |
| 3 | `knowledge.upsert_tension()` | UPDATE with a fresh timestamp for identical text | no-op when identical (`3199711`) |
| 4 | `knowledge.assess_target()` | stamped every target (6,774) | write only on change (`c3374fd`) |
| 5 | `detect()` ↔ `dedupe_targets()` | three tension targets re-opened by reconcile, folded back as near-duplicates, then their "duplicate of" reason overwritten by `assess_target` — one write per pass at a fixed point | dedupe records the reason in `gap`; detect honours it; assess_target leaves a dropped target alone (`fbdd4d5`, `42268c6`) |
| 6 | `cache.MAX_ENTRIES=512`, FIFO trim | not invalidation — eviction: one `/api/sources` stores 506 per-row `potential:` entries, so the singletons every request reads were evicted on schedule (10 of 43 misses with the revision stable) | 16,384, least-recently-used (`9980697`) |

No cache key was widened, nothing is cached by time, and every fix is "do not write what did not change" — the
same answers, minus the no-op writes (fewer writer holds too). Gate `tests/test_s72_research_revision_stability.py`:
each writer leaves unchanged rows alone; the full refresh sequence run twice leaves the revision byte-identical;
a real change (accepting a Claim) still moves it and then settles; the cache keeps a regularly read key.

**Measured, same load as §8 (continuous `research/refresh`, ~10 s foreground probe), five runs:**

| run | state | `/api/sources` p50 / p90 / max | revision changes | cache hits | New Chat p50 |
|---|---|---|---|---|---|
| A | after R8, before any churn fix | 5.2 s / 13.0 s / 23.3 s | every pass | 0 % | 20 ms |
| B | writers 1–3 fixed | 0.78 s / 7.2 s / 34.5 s | ~1–2 per pass (targets) | 58–76 % | 12 ms |
| C | + writer 4 | 0.75 s / 15.2 s / 21.4 s | 7 in 650 s (targets: the reopen/fold loop) | 49–64 % | 13 ms |
| D | + writer 5 | 0.80 s / 11.0 s / 19.1 s | **1 in 662 s** (first pass settling) | 59–77 % — eviction | 12 ms |
| **E** | + LRU cache | **0.70 s / 0.86 s / 8.1 s** | **0 in 667 s** (two full passes) | **95–98 %** | 12 ms |

Idle, the same request is 266 ms. What remains in run E: two spikes (5.1 s, 8.1 s) with the revision unchanged and
98 % hits — the first request of a new pass while `assess_project` re-reads 17k Claims: GIL sharing, not
recomputation, and caption-recovery's p50 of 24 ms under load versus 15 ms idle is the same effect. That is the
"remainder after fixing invalidation" Kyle asked to isolate before any process-separation decision; it is small.

**Side effects worth knowing.** A research pass is now ~283 s instead of ~340–470 s (fewer writes). The evidence
targets whose `gap` reads "duplicate of target <id>" are the ones dedupe folded; the survivor carries the
question. A dropped target is no longer re-assessed until something re-opens it.

**Next, per Kyle's ladder:** R4 (durable partial work), then R5 — with the P0 invariant as the gate concurrency
must pass. Owed, unchanged: push from the Mac; two visible windows; first live `harvest_claims` with the queue
running.

---

## 10. Corrections (2026-09-17, 19:40 PT): R8 reconciled against its full contract; R4/R5 were already shipped

### R8 — every written requirement, with evidence

I wrote "R8, narrow" and "three rungs done" while only the job indexes had changed. Kyle asked for the whole
written contract (SPEED-MISSION.md R8, HARDENING.md "R8 measured storage hygiene" and "R8 reversal") reconciled
item by item. Evidence is the 14:22 PT verified backup copied into the session workspace (never the live file),
the code, and today's `server.log`:

| requirement | state | evidence |
|---|---|---|
| `cache_size` pragma | **satisfied (0.63.36)** | `db.SQLITE_CACHE_KIB = 64*1024`, set on every connection |
| `mmap_size` pragma | **deliberately reverted to 0 (0.63.37)** | HARDENING "R8 reversal": three `fts5: corruption` reads after a sleep/wake with mmap on; observational test still open — "if corruption recurs across a sleep with mmap at 0, this hypothesis is wrong" |
| `temp_store=MEMORY` | **satisfied** | set on every connection |
| scheduled `ANALYZE` | **satisfied** | `db.ANALYZE_INTERVAL_S` = 7 days, housekeeping-owned; `kv storage:last_analyze` = 2026-09-11 18:54 UTC, 6.2 days old at the snapshot — due today; `sqlite_stat1` present, 79 rows |
| WAL checkpoint policy | **satisfied** | `_housekeeping_loop` every 120 s, `checkpoint_wal` TRUNCATE past `WAL_CHECKPOINT_AT`, `journal_size_limit` 64 MB; seven checkpoints today (33–104 MB → 0) |
| the four measured indexes | **present** | `ix_project_notes_project_status_source`, `ix_messages_conversation`, `ix_usage_kind_source`, `ix_jobs_kind_status`; `EXPLAIN QUERY PLAN` on the copy shows each production predicate SEARCHing its index |
| query plans unchanged or better | **verified** | the four above, plus the new `ix_jobs_project_created` / `ix_jobs_kind_source_created` (§9); no plan regressed |
| stuck `in_flight` invocation reaper | **satisfied (existing, not duplicated)** | `_resolve_job_inflight` at job finish + `_resolve_orphan_invocations` at startup; the copy has **0** `in_flight` rows and 148 `outcome_unknown` (the reaper's own marks); the 432 from 09-09 are gone |
| expired-lease recovery | **satisfied** | `recover_expired_leases` at startup and every 60 s; the copy's 5 stale `running` rows are the five jobs interrupted by the 14:22 reload, re-queued at 14:22:12 ("re-queued 4 interrupted jobs"); live Health at 16:09: `stale_running 0, expired_leases 0` |
| retention (`job_events`, `usage`, `invocations`) | **deliberately deferred, by the standing R8 decision** | `usage`/`invocations` are billing and execution evidence and are not deleted; `job_events` (344,696 rows, 10.1 days, 60 MB + 17 MB index) stays under non-destructive observation until 2026-10-11 17:28 PT, then a consumer inventory before any rollup |
| connection memory / plan observation | non-blocking monitoring, as the contract says | unchanged |

Nothing in R8 is silently outstanding. Two items are open by decision, each with its trigger written down: mmap
(sleep/wake observation) and retention (2026-10-11).

### R4 and R5 — already shipped; the ladder I wrote carried them as future work

CLAUDE.md and HARDENING.md record R4 (durable work units, 0.63.40, 57 focused + 66-case recovery gate) and R5
(bounded in-job concurrency, 0.63.41, 54 focused). §3's plan and §9's "next: R4 then R5" — and the re-ordered
ladder I put at the top of SPEED-MISSION.md — repeated the 09-09 mission text without checking the 0.63.40/41
entries two screens below it. Corrected here and in that note.

**Kyle's second lock, audited against the shipped R4.** The mission's sketch `(window text, prompt version, task)`
was never what shipped. `findings.work_unit_key` hashes the exact request: the system blocks (project name, brief,
steering facts, source framing), the user message (window, part index/count, depth instruction), the full model
contract (provider, model, local model, thinking, effort, max tokens, schema), execution policy/profile, source
revision, brief revision, facts revision and depth. `claims.extraction_unit_key` hashes the system prompt, the
group's user message (which embeds the project's brief/goal/questions), the contract, execution and the brief and
facts revisions. The existing gate `tests/test_s46_r4_durable_units.py` already proved: crash after 1 and after 9
of 10 → retry pays only the missing units; a changed brief cannot reuse or materialize old units; a source
revision or model contract change invalidates; provider failure retries only the missing unit; concurrent exact
duplicates compute once.

Four gates added today to state the rule in Kyle's words (`test_s46`, 16 → 20 tests):
- *same window, different project brief → different unit* (10 + 10 calls, disjoint keys);
- *every steering input changes the key* — window, index, depth, brief (and restoring it restores the key), source
  revision;
- *9-of-10 retry produces the same artifact as an uninterrupted run* — summary, substance, status, input hash,
  prompt version, model, depth and the notes compared field for field against a never-interrupted control;
- *identity is the request, not the project row* — recorded as a **design fact for Kyle to confirm**: two projects
  whose framing is identical word for word (same name, brief, facts) send the identical request and share units;
  a one-character difference in the brief does not. That is literally "same hash ⇒ the same artifact would be
  produced again", and it is not "same passage ⇒ already analyzed". If Kyle wants project identity itself in the
  key (no sharing even between verbatim twins), it is one line in `work_unit_key` and a version bump of
  `"work-unit-v1"`; I did not make that call.

R5 is likewise shipped and gated (`test_s47_r5_concurrency.py`, 14 tests: attribution, cancellation, policy
preservation, spend reservations, 7/12 crash with five-unit retry, ordering). The P0 invariant now stands beside
it in CLAUDE.md; nothing about R5's bounds (2 local / 3 API / cap 4) was touched.

**So the ladder after this rung is R9 (local-model benchmarking, R9(c) still open with its numeric revisit
trigger) — and, per Kyle, below everything above it.** The higher-value open item from today's measurements
remains the GIL floor (§9), which is a process-separation decision, not a rung on this ladder.

---

## 11. Closing decisions (Kyle, 2026-09-17 evening) — the speed mission enters observation mode

1. **Twin-project reuse stays exactly as shipped.** Two projects that generate the same effective request share
   the completed work unit; adding `project_id` to force recomputation would violate the stronger rule now in
   force: *same key ⇒ the same artifact would be produced again*. If a future defect shows an input that changes
   the output but is not in the key, add that input — never an arbitrary project id. **Guardrail:** this is
   compute reuse, not project-state reuse. The shared unit materializes into each project's own analysis rows,
   findings, Claims and state with that project's provenance and lifecycle; no verdict, applicability, approval,
   readiness or other project-owned state is shared because the computation was. Gated in `test_s46`
   (`test_identity_is_the_request_not_the_project_row`: separate analysis rows per project; an acceptance recorded
   in one project does not appear in its twin).
2. **R9(c) stays deferred.** Its question — can a 70B Q4 or MoE local model beat the 10.9 s API baseline for
   findings/Claims — is not the question today's measurements left open, and the mission expects it to fail at
   45–90 s. Its numeric revisit trigger stands as written in R9.
3. **Process separation has a revisit trigger, so it cannot become a vague temptation.** Reopen background-process
   isolation only if normal real-world use — not synthetic stress alone — repeatedly produces foreground p90 > 1 s
   while write holds remain < 250 ms, the relevant caches are > 95 % hit, and perf traces attribute the delay to
   concurrent CPU-bound background work. Read those off `/api/perf` (`db:write_hold` peak, cache rates, the
   endpoint timings) and `server.log`; the §8/§9 loads are the reference for what "synthetic" looked like.

**Status locked:** P0 closed · R4 shipped (0.63.40) · R5 shipped (0.63.41) · R8 satisfied with two documented
exceptions and their triggers (mmap after sleep/wake; retention 2026-10-11) · R9(c) deferred · `/api/sources`
cache churn closed · speed mission in observation mode. Product work resumes (Send Screenshot matrix, then the
Course Scanner live wiring, then the Kyle-gated judgments in the State of the App).
