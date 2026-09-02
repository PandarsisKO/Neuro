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
