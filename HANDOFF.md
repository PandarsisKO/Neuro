# Neuro Search — engineering handoff

*Version 0.14.1 · September 2026 · owner: Kyle Owen*

This document is for a team picking up Neuro Search to extend it. It explains what the product is, how it is built, how every feature works under the hood, the rules we learned the hard way, and where the obvious next steps are. Read it alongside `README.md` (user-facing quick start) and `CLAUDE.md` (a terse map of the code kept for AI coding assistants).

---

## 1. What it is, in one paragraph

Neuro Search is a personal research engine. You point it at videos, podcasts, web pages, PDFs, spreadsheets, Instagram reels or whole YouTube channels; it pulls out the transcript or text, indexes it, and then lets you *ask questions* of the material and get answers with citations that link to the exact second of the video (or page of the document). Material is grouped into **Projects**, each with a brief describing what you are trying to find out. On top of the question-answering layer sit three higher-level features: **Suggested findings** (the AI reads every source against the brief and proposes the claims that matter), **Discover** (the AI proposes new sources to go and get), and the **Master Planner** (it turns the accumulated research into a situation analysis and an actionable plan). The entire thing runs on one machine as a single Python process with a SQLite file, and is also exposed as an MCP server so it can be used from inside Claude.

The pitch in numbers, from the owner's own library at the time of writing: roughly 210 sources, about 79 hours of audio and video, just over a million words of transcript, for around $17 of API spend. The app shows this to the user as the "in numbers" card ("3.7× all of Breaking Bad").

## 2. Architecture

```
 browser (index.html, vanilla JS)      Chrome extension (MV3)        Claude app / Claude Code
        │ REST /api/*                       │ REST                       │ MCP  /mcp/<token>
        ▼                                   ▼                            ▼
 ┌──────────────────────────────── FastAPI process (api.py) ─────────────────────────────────┐
 │  sync endpoints (threadpool)   │   background workers (jobs.py)   │   mcp_server.py (FastMCP) │
 │                                │   2 general + 1 analysis worker  │                           │
 │  ingest.py ── media.py (yt-dlp) ── transcribe.py (Whisper) ── chunking.py ── embeddings.py     │
 │           └─ documents.py / webpage.py / sheets.py / courses.py                                 │
 │  search.py (FTS5 + cosine)  qa.py (Claude + tools)  findings.py  relevance.py  discover.py      │
 │  planner.py  export.py  usage.py (spend + budget valve)                                         │
 │                                  db.py — all SQL, one SQLite file (WAL)                         │
 └─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                   data/  neurosearch.db · files/ · cookies/ · backups/ · tmp media
```

**Stack.** Python 3.11+, FastAPI + uvicorn, SQLite (FTS5 for keyword search, embeddings stored as numpy blobs and compared with cosine similarity in Python), `yt-dlp` for media, `httpx` for HTTP, `openpyxl` + `formulas` for spreadsheets, `pypdf`/`python-docx` for documents, Typer for the CLI, FastMCP for the MCP mount. The web UI is a single file, `neurosearch/web/index.html`, vanilla JavaScript with no build step (~2,000 lines). Tests are pytest with a fake Anthropic client (`tests/fake_claude.py`), 39 tests, run with `pytest`.

**External APIs.** Anthropic (Claude Sonnet 4.6 by default — answers, findings, ranking, discover, planner; the `web_search` server tool for Discover and optional web-augmented answers), OpenAI (`text-embedding-3-small` embeddings, `whisper-1` transcription when captions are missing). Both keys live only in `.env` on the owner's Mac. Everything degrades gracefully: with no OpenAI key you still get keyword search and caption-based ingestion; with no Anthropic key you get search but no answers.

**Process model.** One process. FastAPI endpoints are plain `def` (not `async`) so they run in the threadpool and SQLite work never blocks the event loop. Background work goes through a job table; `jobs.py` starts worker threads at startup (`NEUROSEARCH_WORKERS`, default 2) plus one dedicated *analysis* worker that only takes `suggest_findings`, `rank_proposed`, `discover` and `build_plan` jobs, so AI analysis is never starved by a long channel download. An hourly thread snapshots the DB into `data/backups/` (keeps 48).

**Running it.** `./start` (or `start.command` from Finder) creates/updates the venv, `pip install -e .`, and runs `neurosearch start`, which is uvicorn with `--reload` watching `*.py` and `*.html`. Code changes are picked up live; **new dependencies are not** — that needs Ctrl+C and `./start` again. The UI compares its baked-in `UI_VERSION` against `/api/version` and shows a banner when the server is stale. `neurosearch serve` is the plain no-reload server. There is a `Dockerfile` and `fly.toml` from an earlier cloud deployment; datacenter IPs get blocked by YouTube, so `remote.py` exists to extract on a laptop and push to a remote server (`neurosearch ingest --remote URL --token TOKEN`). Current usage is entirely local.

**Auth.** One shared secret, `NEUROSEARCH_APP_TOKEN`: it is the web login password, the API Bearer token, and part of the MCP URL (`/mcp/<token>`). `/api/whoami` also reports the LAN address so a phone on the same Wi-Fi can use the app.

## 3. Data model (`db.py`)

All SQL lives in `db.py`. The schema is `CREATE TABLE IF NOT EXISTS` plus an additive `MIGRATIONS` list of `ALTER TABLE ADD COLUMN` statements checked at startup; there is no migration tool, so **keep changes additive**. Connections are thread-local, WAL mode; `db.tx()` is a commit-per-call context manager and `db.batch()` groups many writes into one transaction (used for bulk listings so the write lock is held briefly).

| Table | What it holds |
|---|---|
| `sources` | One row per ingested thing: url, platform (`youtube`, `media`, `instagram`, `web`, `document`, `spreadsheet`, `file`, `manual`), title, channel, duration, published_at, status (`pending`/`proposed`/`ready`/`failed`/`skipped`), error, summary + substance score (0–100), relevance + relevance_why (from ranking), view_count, tags |
| `segments` | Timestamped transcript lines (`start`, `end`, `text`). For documents/web/spreadsheets `start` is the page/section/sheet number |
| `chunks` | ~60-second windows of segments with 10 s overlap, FTS5-indexed, with an embedding blob |
| `collections`, `source_collections` | A playlist/channel/course/search listing and its members |
| `projects`, `project_sources`, `project_collections` | Projects and what is in scope. Steering fields: brief, goal, audience, output_pref, source_prefs, questions, context, tags, mode (`research`/`plan`) |
| `project_notes` | Findings. `status` is `suggested` / `approved` / `dismissed`; carries citations JSON, importance, title, source_id |
| `project_facts` | User-stated decisions / constraints / requirements / rejected options (fed to the planner) |
| `plans`, `plan_items`, `plan_updates` | Master Plan versions (JSON), per-item status keyed like `first_steps.0`, and proposed updates from new research |
| `discoveries` | Discover suggestions with status (`new`/`added`/`dismissed`) and verification notes |
| `conversations`, `messages` | Chats, isolated per project, with citations |
| `jobs` | The queue: kind, payload JSON, status, progress, message, not_before, attempts, updated_at |
| `usage` | Every paid API call: kind, model, tokens, cache tokens, cost, saved, project_id, source_id |
| `kv` | Small state: budgets, queue pause, review metadata (`review:<collection>`), spreadsheet models (`sheet:<source_id>`) |

**Golden rule: never write to `data/neurosearch.db` from outside the running app.** Writing through a mounted filesystem from another OS/VM corrupted the WAL once and destroyed three chats. Use the API or CLI for everything; read-only inspection with `sqlite3` is fine. Hourly backups exist for exactly this reason (`neurosearch backup` makes one on demand).

## 4. How ingestion works (`ingest.py`, `media.py`, `jobs.py`)

A URL or file becomes an `ingest_url` / `ingest_file` job. `media.classify_url` decides what it is: `youtube`, `playlist`, `channel`, `youtube_search` (a `youtube.com/results?search_query=` link), `instagram`, `instagram_profile`, a direct media file, or `web` for any non-media host.

**Single videos and audio.** `media.fetch_info` (yt-dlp metadata) → captions if they exist in `NEUROSEARCH_CAPTION_LANGS` (free) → otherwise download audio and transcribe with Whisper (capped by `NEUROSEARCH_MAX_TRANSCRIBE_MINUTES`, disable with `NEUROSEARCH_ALLOW_TRANSCRIPTION=false`) → segments → chunks → embeddings → status `ready`. `noplaylist=True` is set so a video link that carries a `list=` parameter does not stall on the whole playlist.

**Channels, playlists, searches, Instagram profiles.** These are *listed, not downloaded*. Every entry becomes a `proposed` source in a collection, filtered by age (`min_date`, from the "last N years" control), and a `rank_proposed` job scores them. The UI shows a **Review card**: the best `max_videos` are pre-ticked, the user adjusts and presses Start, and `approve_proposed` turns the ticked ones into `ingest_source` jobs; the rest are discarded. Review metadata (min_date, newest_first, max_videos, ranked flag, rank note, cookies_file, referer) lives in kv under `review:<collection_id>`.

**Relevance ranking (`relevance.py`).** Titles, description snippets, length and view count of up to 400 proposed videos are sent to Claude in batches of 80 with the project brief; each gets a 0–100 score and an eight-word reason, stored on the source. The JSON parser is deliberately tolerant (regex fallback per item) because the model occasionally breaks a quote; a failed batch leaves items unscored rather than pretending they are zeros, and a "re-rank" button retries only those. Cost is a few cents per channel.

**Politeness and rate limits (`media.polite`).** Per-site locks and randomised delays (`NEUROSEARCH_YT_DELAY`, default 4 s) serialise YouTube and Instagram fetches. If yt-dlp reports a bot check ("Sign in to confirm you're not a bot") the site is paused for `NEUROSEARCH_YT_BACKOFF_MINUTES` (20) and the job is re-queued; the error text is classed as transient. YouTube started issuing these after roughly 200 videos in a day. We deliberately do **not** use the owner's YouTube account cookies for bulk downloads (risk to the account); `NEUROSEARCH_COOKIES_FILE` exists as an opt-in for people who accept that.

**Retries.** `jobs.TRANSIENT` is a regex of error texts that mean "try later" (timeouts, 429/503, bot checks, rate limits); such jobs re-queue with `RETRY_DELAYS = [600, 1800, 5400]` seconds up to `MAX_ATTEMPTS = 4`, tracked in `payload._attempts` and `not_before`. Anything else fails visibly with a friendly message (`media._friendly`) and can be retried per job, per source, or in bulk ("Retry all failed", "Retry skipped"). Sources whose job was cancelled go back to `proposed` so they reappear in the Review card. `_with_timeout` (240 s) guards every yt-dlp call so a hung fetch cannot wedge a worker.

**Web pages (`webpage.py`).** Fetched with browser-like headers, chrome stripped with a small HTML parser, split into numbered sections (~900–4500 chars, headings start new ones) that play the role pages play for PDFs; citations render as `§ 3`. PDF links are routed to `documents.extract_pages`. Sites that return 401/403/429/503 raise `Blocked` with a hint to use the extension.

**Documents and files (`documents.py`, `sheets.py`).** PDF, DOCX, TXT, MD, HTML, SRT/VTT, audio and video uploads. Uploaded files are kept in `data/files/<source_id><ext>` so retries re-read the file rather than a temp path. Spreadsheets (xlsx/xlsm/csv) are read twice: as text (each sheet is a "page" of `A1: value` lines so it is searchable and citable as `sheet N`) and as a live model via the `formulas` package, which evaluates the workbook's own formulas. Labelled numeric constants become *inputs*, labelled formula cells become *outputs*; both are stored in kv `sheet:<source_id>`. The chat gets a `calculate` tool whenever a project contains a spreadsheet, and the UI has a 🧮 Calculator dialog. The point is that the user's spreadsheet *is* the calculator; we never re-implement its maths.

**Chrome extension (`extension/`, MV3, v1.3).** Three jobs: (1) *Course import* — `scanner.js` runs in the page of a course platform, finds lesson video URLs, and `popup.js` posts them with the user's cookies to `/api/projects/{id}/course-import`; `courses.py` writes a Netscape cookie file to `data/cookies/<collection>.txt` and the resulting `ingest_url` jobs carry `cookies_file`/`referer`. (2) *Send this page* — posts the rendered HTML of the current tab to `/api/projects/{id}/ingest/html`, which is how paywalled/JS-rendered/blocked pages get in. (3) *Send with session* — for media hosts (Instagram in particular) posts the URL plus the user's cookies to `/ingest/with-session`. Instagram profiles are listed only this way (`media.enumerate_instagram`), capped at `IG_MAX = 40` and slow on purpose. Cookies never leave the server's `data/cookies/` folder. The extension is served zipped at `/extension.zip`.

**Auto-suggest.** When a source in a project becomes ready and `NEUROSEARCH_AUTO_SUGGEST` is true (default), a `suggest_findings` job is queued for it, so findings appear without the user asking.

## 5. Search and answers (`search.py`, `qa.py`)

Retrieval is hybrid: FTS5 keyword match plus cosine similarity over chunk embeddings, merged and scoped to the project's sources. `qa.ask` builds a numbered `<excerpts>` block and asks Claude to answer citing `[n]`; the numbers are mapped back to source, timestamp and a deep link (`youtube.com/watch?v=…&t=754s`, page anchors for PDFs, `§ N` for pages). If everything in scope is small (≤6 sources and under 90k characters), retrieval is skipped and the whole material is handed over — this makes "summarise this" questions work, which retrieval handles badly.

The chat is agentic: Claude has tools `update_brief`, `save_finding`, `note_gap`, `record_fact`, and `calculate` (when spreadsheets exist), plus the `web_search` server tool when "also search the web" is ticked (web facts must be marked as such in the answer). Up to six tool rounds per turn. The system prompt carries the project brief, the pinned findings, known facts and the steering fields rendered by `db.project_steering`. URLs pasted into a chat message are queued for ingestion into the project. Answers end with a "Gap:" line when the excerpts only partly cover the question, and that gap is recorded as a note.

## 6. Suggested findings (`findings.py`)

Each ready source is read in windows of 60k characters against the project brief. The prompt asks for 3–12 findings with a headline-style title (≤8 words, never "X says…"), one sentence of substance, a ≤20-word verbatim quote, the timestamp before it, and an importance rating 1–5; it also asks for a substance score (0–100) and a two-sentence summary of the source, which the Sources list shows for triage. Findings land as `suggested` notes; the Findings tab lets the user approve or dismiss singly or in bulk, and only approved notes feed the chat prompt and the planner. Timestamps parse `m:ss`, `h:mm:ss`, `p. N`, `§ N`, `sheet N`.

## 7. Discover (`discover.py`)

Two passes. Pass 1 (`QUICK_SYSTEM`, no tools) proposes a shortlist from the brief instantly and saves it so the user sees results within seconds. Pass 2 (`VERIFY_SYSTEM`, `web_search`) verifies each suggestion exists, corrects URLs, and tops up; `db.update_discovery` merges the results. Runs as a `discover` job; the UI pane polls while it runs. Each suggestion has an Add button that routes on URL type: a video ingests, a channel/playlist opens a Review card, a `youtube.com/results?…` link becomes a **🔍 Search YouTube** action (`media.enumerate_search`, `ytsearchN`), and a plain web page gets an **Add page** button. Suggestions can be dismissed, and a "refine" box re-runs with extra instructions.

## 8. Master Planner (`planner.py`)

Two streamed Claude passes over a "material" pack (`_material`: brief and steering, approved findings with evidence ids, facts, source summaries, recent conversation, capped at `MATERIAL_CHARS = 170,000`).

Pass 1, `ANALYSIS_SYSTEM`, produces a situation analysis as JSON: situation, SWOT, readiness, options with a recommendation, assumptions, failure patterns, verdict. Pass 2, `SYSTEM`, produces the plan JSON informed by that analysis and by the previous plan if one exists: objective, first steps, phases, a **This week** list, risks, open questions, and `refine_questions` — guided questions whose answers become project facts (`Q: … A: …`) and trigger a rebuild ("Make this plan yours" in the UI). The UI renders **Start here** and **This week** up top, with everything else behind tabs, because the first version was judged too cluttered to act on. Streaming plus `_repair_json` (closes truncated JSON) exist because 16k-token outputs used to get cut off or time out. Plan item statuses are keyed like `first_steps.0` and carried across rebuilds. `check-updates` compares new research against the current plan (`UPDATE_SYSTEM`) and proposes deltas the user can apply. Exports: `plan.md`, `plan.html`, and `masterplan.zip` (findings + plan + transcripts package from `export.py`).

## 9. Cost control (`usage.py`)

Every paid call records a row with an estimated cost (price table `PRICES`, override with `NEUROSEARCH_PRICES` JSON). `usage.guard(estimate)` is called before paid background work; when the daily or monthly budget (kv, defaults from env: $5/$50) would be exceeded it raises `BudgetPaused` and the job re-queues with `not_before` at the window rollover — nothing fails or is lost. A manual pause switch uses the same path. Changing a budget or pressing Resume clears `not_before` on parked jobs immediately. User-initiated chats and plan builds are allowed through.

Estimates shown on the Review card ("≈ $0.80 to analyse") come from `estimate_video`: a chars-per-minute model of transcripts through the findings prompt, replaced by the *observed* cost per minute once five or more sources have history (`observed_rate_per_minute`). Whisper is shown as a separate "if captions are missing" figure.

Prompt caching (added in 0.14.0): `usage.cached_block` and `usage.mark_last` put `cache_control` breakpoints on stable prefixes — chat rules + project block (+ the full-context excerpts when ≤6 sources) and the conversation tail, findings/ranking project framing, and the planner's research material as the first system block shared by both passes. Cache reads are priced at 0.1×, writes at 1.25×, and each usage row stores what it saved; the total shows in Settings and on the "in numbers" card. Prefixes under ~1024 tokens are not marked because the API ignores them. Where the money actually goes: transcript windows in findings analysis dominate and cannot be cached (never re-sent); chats with tool rounds and plan builds are where caching pays.

## 10. The web UI (`web/index.html`)

Single page, hash-routed. **Home** lists projects and the global "Your research in numbers" card. Inside a project the sidebar has Chats, Sources, Findings, Plan, Settings, a one-line numbers strip, and the spend meter.

Sources tab: the "in numbers" card; an add box with panes for Link (with "last N years" and "best N videos" controls), Upload, Paste text, From library (attach sources already ingested elsewhere), Discover, and Browser extension (with the LAN address for pairing); Review cards for pending listings (tick boxes, estimate, re-rank, Start, Discard); the jobs card (per-job cancel/retry/dismiss, elapsed and "quiet for N min" indicators, pause/resume, cancel all queued, reconnect banner if the server goes away); and the sources list with filter chips (working/queued/ready/failed/skipped), status colouring (blue only for actively running jobs, not queued ones), live progress line, summary + substance, tags, transcript download, Calculator, Ingest anyway, Retry.

Chats: many per project, isolated to the project's sources; citations render as timestamp links; tool actions (brief updated, finding pinned, fact recorded, calculation) are shown inline. Findings: suggested vs approved with bulk actions and importance. Plan: as described above. Settings: brief and steering fields, facts list, budgets, exports, the project's numbers card, danger zone.

A poller refreshes jobs and sources while work is running and survives server restarts (it reconnects instead of dying on the first failed fetch — this bug caused the "sources page not updating" complaint). Version banner, toasts, dark mode.

## 11. CLI and MCP

`neurosearch ingest <urls…> [-t tag] [--project] [--remote --token]`, `ingest-file`, `ingest-text`, `ask`, `search`, `sources`, `status`, `export [--segments]`, `reembed`, `serve`, `start`, `worker`, `backup`, `cancel --job`. The MCP server (`mcp_server.py`) mounts at `/mcp/<token>` and exposes: `search_knowledge`, `ask`, `list_projects`, `create_project`, `add_to_project`, `list_sources`, `list_collections`, `get_transcript`, `ingest`, `job_status`, `findings`, `masterplan`, `build_master_plan`, `get_master_plan`, `record_fact`, `update_brief`, `save_note`. Any Claude client can therefore drive the whole product.

## 12. Configuration

`.env` (never committed; `.env.example` documents everything). Required: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `NEUROSEARCH_APP_TOKEN`. Notable optional: `NEUROSEARCH_DATA_DIR`, `NEUROSEARCH_ANSWER_MODEL`, `NEUROSEARCH_EMBEDDING_MODEL`, `NEUROSEARCH_TRANSCRIBE_MODEL`, `NEUROSEARCH_CAPTION_LANGS`, `NEUROSEARCH_COOKIES_FILE`, `NEUROSEARCH_ALLOW_TRANSCRIPTION`, `NEUROSEARCH_MAX_TRANSCRIBE_MINUTES`, `NEUROSEARCH_WORKERS`, `NEUROSEARCH_YT_DELAY`, `NEUROSEARCH_YT_BACKOFF_MINUTES`, `NEUROSEARCH_SINCE_YEARS`, `NEUROSEARCH_MAX_VIDEOS`, `NEUROSEARCH_DAILY_BUDGET_USD`, `NEUROSEARCH_MONTHLY_BUDGET_USD`, `NEUROSEARCH_PRICES`, `NEUROSEARCH_AUTO_SUGGEST`, `NEUROSEARCH_CHUNK_SECONDS`, `NEUROSEARCH_CHUNK_OVERLAP`, `NEUROSEARCH_SHORT_FORM_SECONDS`.

## 13. Conventions and hard-won rules

- Keep the schema additive; add a line to `MIGRATIONS`, never rename or drop.
- Never touch the DB file from outside the process (see §3). Use the API.
- API endpoints are sync `def`. Anything that does many small writes wraps them in `db.batch()`.
- Every Claude call goes through `usage.guard` before and `usage.record_anthropic` after; new prompts should use `usage.cached_block` for their stable prefix.
- Parse model JSON defensively (`_repair_json`, `parse_scores`); one malformed item must not sink a batch.
- Errors shown to users go through `media._friendly`; transient ones must match `jobs.TRANSIENT` so they retry instead of failing.
- Per-site politeness lives in `media.polite`; do not add a new scraper without it.
- User cookies stay server-side in `data/cookies/`; never use account cookies for bulk YouTube downloads by default.
- Bump `__version__`, `pyproject.toml` and `UI_VERSION` together on every release so the stale-server banner works.
- Tests: extend `tests/fake_claude.py` handlers (keyed on a phrase in the system prompt) when you add a prompt; keep `pytest` green.

## 14. Known gaps and what to build next

**Untested in the wild.** The course importer has only been run against one platform; the Instagram profile listing has not been exercised end to end; `remote.py` and the Fly deployment predate most features.

**Scaling.** Everything is one SQLite file and cosine similarity in Python over every chunk in scope. Fine to a few thousand sources; beyond that, move embeddings to a vector index (sqlite-vec or similar) and paginate the sources list (the UI currently fetches up to 2,000 rows per poll).

**Single user.** One shared token, no accounts, `project_members` endpoints exist but are vestigial. Multi-user means real auth, per-user projects, per-user API keys and budgets.

**Ideas the owner has raised or that fall naturally out of the design:** speaker diarisation so findings can name who said what; support for more platforms (Vimeo/Loom/TikTok/podcast RSS feeds with automatic new-episode pickup — the polite/transient machinery is ready for it); scheduled channel re-scans; a shareable read-only view of a plan or findings; findings deduplication across sources; a "compare sources" view that shows where speakers disagree; smarter estimates for documents and web pages; exporting to Notion/Docs; a mobile-first layout for the chat; a proper test suite for the UI.

**Tech debt worth paying.** `index.html` should be split into modules (it is a single 2,000-line file by design for zero-build simplicity, but it is past the comfortable size). `db.list_sources(limit=100000)` is used in a couple of helpers where a targeted query would do. The `usage` price table is hand-maintained.

## 15. Where to look first

Read `CLAUDE.md`, then `db.py` (schema at the top), then follow one video through `ingest.ingest_url` → `ingest_source` → `chunking` → `embeddings`, then `qa.ask`. Run `pytest`, then `./start`, add a short YouTube video to a new project with a one-line brief, and watch the jobs card, the findings appear, and the chat cite a timestamp. That path touches most of the system in ten minutes.

*Git: the repo on the owner's Mac (`2026 - KO Neuro Search REPO`), latest tag 0.14.1. No remote yet — adding a GitHub remote is the first thing the new team should do.*
