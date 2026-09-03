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
Master Planner lives in `planner.py` (structured plan JSON + evidence map; `plan_markdown`/`plan_html`); statuses in plan_items keyed like `first_steps.0`.
Tests use `tests/fake_claude.py` in place of the Anthropic client.
Suggested findings: `findings.py`; notes have status suggested|approved|dismissed (list_project_notes defaults to approved).
Project steering fields (goal, audience, output_pref, source_prefs, questions, context) are rendered by `db.project_steering` into every prompt.
Discover sources: `discover.py` (Claude + web_search) → `discoveries` table; UI pane in Sources.
Course import: `extension/` (MV3; scanner.js runs in the page, popup.js posts to /api/projects/{id}/course-import) → `courses.py` writes data/cookies/<collection>.txt; ingest_url jobs carry cookies_file/referer/title/collection_id.
Spend/budget: `usage.py` (usage table, `guard()` raises BudgetPaused → jobs re-queue with not_before; kv table holds budgets + queue_paused).
Relevance ranking: `relevance.py` scores proposed channel/playlist videos (titles+descriptions, `rank_proposed` job) → sources.relevance/relevance_why; review meta in kv `review:<collection>` carries max_videos/ranked; the UI pre-ticks the best `max_videos`.
Web pages: `webpage.py` (fetch + section HTML; PDF links go through documents.extract_pages) → platform 'web', sections cited as '§ N'; `media.classify_url` returns 'web' for non-media hosts. API endpoints are plain `def` (threadpool) so SQLite work never blocks the event loop; `db.batch()` groups bulk-listing writes.
Sites that block fetches (403) raise `webpage.Blocked` with a hint; the extension's 'Send this page' posts the rendered HTML to /api/projects/{id}/ingest/html.
Instagram: profiles only with the user's own session via the extension (`media.enumerate_instagram`, cap IG_MAX=40, review card, per-site politeness in `media.polite`); review meta carries cookies_file/referer into ingest_source jobs.
