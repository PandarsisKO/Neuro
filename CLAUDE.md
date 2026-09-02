# Neuro Search — notes for Claude Code

Python 3.11+ / FastAPI / SQLite (FTS5 + numpy vectors). Package lives in `neurosearch/`.

- `config.py` settings from env/.env · `db.py` schema + all SQL · `media.py` yt-dlp (enumerate, captions, audio)
- `transcribe.py` Whisper API · `chunking.py` segments→chunks · `embeddings.py` OpenAI embeddings
- `ingest.py` orchestration · `jobs.py` background workers · `search.py` hybrid retrieval · `qa.py` Claude answers w/ citations
- `api.py` REST + web UI + MCP mount · `mcp_server.py` MCP tools · `cli.py` typer CLI · `web/` single-page UI

Run locally: `pip install -e . && cp .env.example .env && neurosearch serve`. Tests: `pytest`.
YouTube may block datacenter IPs — ingestion can be run from a laptop with the same CLI against the same DB
(`NEUROSEARCH_DATA_DIR`) or with `NEUROSEARCH_COOKIES_FILE`.
Keep the DB schema additive (CREATE IF NOT EXISTS) — there is no migration tool.
