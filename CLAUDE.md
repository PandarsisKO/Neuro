# Neuro Search — notes for Claude Code

Python 3.11+ / FastAPI / SQLite (FTS5 + numpy vectors). Package lives in `neurosearch/`.

- `config.py` settings from env/.env · `db.py` schema + all SQL · `media.py` yt-dlp (enumerate, captions, audio) · `documents.py` PDF/DOCX/text → pages
- `transcribe.py` Whisper API · `chunking.py` segments→chunks · `embeddings.py` OpenAI embeddings
- `ingest.py` orchestration · `jobs.py` background workers · `search.py` hybrid retrieval · `qa.py` Claude answers w/ citations + project tools · `export.py` findings & masterplan package
- `api.py` REST + web UI + MCP mount · `mcp_server.py` MCP tools · `cli.py` typer CLI · `web/` single-page UI

Run locally: `pip install -e . && cp .env.example .env && neurosearch serve`. Tests: `pytest`.
YouTube may block datacenter IPs — ingestion can be run from a laptop with the same CLI against the same DB
(`NEUROSEARCH_DATA_DIR`) or with `NEUROSEARCH_COOKIES_FILE`.
Keep the DB schema additive (CREATE IF NOT EXISTS) — there is no migration tool.

UI model: projects are the unit; inside a project: chats (many, isolated to project sources), sources, findings, settings.
Documents use page numbers as start/end in segments/chunks; `fmt_locator` renders 'p. N' vs mm:ss.
Master Planner lives in `planner.py`: two streamed passes (ANALYSIS_SYSTEM → plan.analysis with SWOT/readiness/options/assumptions/failure_patterns; then SYSTEM → plan), material capped (MATERIAL_CHARS), `_repair_json` for cut-off output, runs as `build_plan` job (API `background: true`); `plan_markdown`/`plan_html`; statuses in plan_items keyed like `first_steps.0`.
Tests use `tests/fake_claude.py` in place of the Anthropic client.
Suggested findings: `findings.py`; notes have status suggested|approved|dismissed (list_project_notes defaults to approved).
Project steering fields (goal, audience, output_pref, source_prefs, questions, context) are rendered by `db.project_steering` into every prompt.
Discover sources: `discover.py` — pass 1 no-tools shortlist (instant, saved immediately), pass 2 web_search verify/top-up (`db.update_discovery`); `discoveries` table; UI pane in Sources polls during the job.
Course import: `extension/` (MV3; scanner.js runs in the page, popup.js posts to /api/projects/{id}/course-import) → `courses.py` writes data/cookies/<collection>.txt; ingest_url jobs carry cookies_file/referer/title/collection_id.
Spend/budget: `usage.py` (usage table, `guard()` raises BudgetPaused → jobs re-queue with not_before; kv table holds budgets + queue_paused).
Relevance ranking: `relevance.py` scores proposed channel/playlist videos (titles+descriptions, `rank_proposed` job) → sources.relevance/relevance_why; review meta in kv `review:<collection>` carries max_videos/ranked; the UI pre-ticks the best `max_videos`.
Web pages: `webpage.py` (fetch + section HTML; PDF links go through documents.extract_pages) → platform 'web', sections cited as '§ N'; `media.classify_url` returns 'web' for non-media hosts. API endpoints are plain `def` (threadpool) so SQLite work never blocks the event loop; `db.batch()` groups bulk-listing writes.
Sites that block fetches (403) raise `webpage.Blocked` with a hint; the extension's 'Send this page' posts the rendered HTML to /api/projects/{id}/ingest/html.
Instagram: profiles only with the user's own session via the extension (`media.enumerate_instagram`, cap IG_MAX=40, review card, per-site politeness in `media.polite`); review meta carries cookies_file/referer into ingest_source jobs.
Retries: transient errors (jobs.TRANSIENT) re-queue with backoff up to MAX_ATTEMPTS (payload._attempts); failed jobs can be retried (/api/jobs/{id}/retry, /api/jobs/retry-failed) or dismissed.
NEVER write to data/neurosearch.db from outside the running app (another OS/VM through a mount corrupts the WAL and loses recent transactions) — use the API/CLI. Hourly snapshots: db.backup() → data/backups/.
Spreadsheets: `sheets.py` — xlsx/csv → platform 'spreadsheet' (sheets as pages, locator 'sheet N'), file kept in data/files/, labelled inputs/outputs in kv `sheet:<source_id>`; `formulas` package recomputes the workbook (calculate(source_id, inputs, outputs)); chat gets a `calculate` tool when the project has spreadsheets; UI: 🧮 Calculator dialog, /api/sources/{id}/calculator + /calculate.
YouTube search links (youtube.com/results?search_query=…) → `media.enumerate_search` (ytsearchN) → review card like a playlist; Discover renders a 🔍 Search YouTube button for them.
Prompt caching: `usage.cached_block`/`usage.mark_last` put cache breakpoints on the stable prefixes — chat rules+project block (+ full-context excerpts when ≤6 sources) and the conversation tail (tool rounds/turns), findings/relevance project head, planner research material (first system block, shared by both passes). `usage.record` prices cache_read (0.1x) / cache_write (1.25x) and stores `saved`; shown in Settings and the fun stats card. Prefixes under ~1024 tokens are not marked (the API ignores them).
Hardening (see HARDENING.md): `providers.py` is the only place clients are made (`NEUROSEARCH_FAKE_AI=1` → `fake_ai.py`, content-aware fakes; every call declares its task in extra_headers x-neurosearch-task — the router hook). `evals.py` + `neurosearch eval` run the frozen Golden Project (tests/fixtures/golden) end to end with Tier-1 gates; `evidence.py` validators run at runtime (finding quotes must be in the transcript window, answer citations must exist, plan evidence ids must resolve) and count into kv `evidence:*` → `/api/health`. `db.backup()` verifies every snapshot (`verify_database`), `db.integrity_check()` hourly; migration fixtures in tests/fixtures/db (built by build.py from old db.py copies). `media.canonical_url` before any dedupe. `logctx.py` correlates log lines (job/run/project/source/task/model).
Data trust (0.16): project-relative analysis lives in `project_source_analysis` (`db.upsert_analysis/project_analysis/get_analysis`; `set_source_summary`/`set_relevance` require project_id) — never write summary/substance/relevance on `sources`. Revisions: `db.segments_revision` → sources.revision; `db.brief_revision/facts_revision/source_set_revision/project_revisions`; notes/plans/discoveries carry them + model/prompt_version. `staleness.assess/rebuild` (+ /api/projects/{id}/staleness, /rebuild-stale): informational, cost-quoted, jobs go through usage.guard; chats never stale. `db.delete_source` marks citations/evidence `removed` (planner emap entries carry source_id).
