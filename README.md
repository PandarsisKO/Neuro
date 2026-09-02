# Neuro Search

Turn videos, podcasts and audio into a queryable, citation-backed knowledge base.

Give it a YouTube video, playlist or **whole channel**, a podcast episode, an Instagram reel, an mp3, or a
transcript you already have. It extracts the transcript (captions when they exist, Whisper when they don't),
splits it into timestamped chunks, indexes it for keyword + semantic search, and lets you ask questions.
Every answer cites the exact video **and timestamp**, with a link that opens the video at that moment.

Sources can be grouped into **Projects** — topic groupings with a brief that guides the answers and their own
conversation history — and the whole thing is reachable from a phone via the web app or as an MCP connector
inside the Claude app.

```
┌──────────────┐   yt-dlp / Whisper   ┌───────────────┐   FTS5 + embeddings   ┌──────────────┐
│ URL / file   │ ───────────────────▶ │ timestamped   │ ────────────────────▶ │ search + ask │──▶ answer + [video @ 12:34] links
│ playlist     │                      │ segments      │                       │ (Claude)     │
│ channel      │                      │ + chunks      │                       └──────────────┘
└──────────────┘                      └───────────────┘        ▲ web app · CLI · MCP (Claude desktop/mobile/Code)
```

## Quick start (on your Mac)

```bash
cd "2026 - KO Neuro Search REPO"
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
brew install ffmpeg            # needed for audio transcription
cp .env.example .env           # add ANTHROPIC_API_KEY, OPENAI_API_KEY, NEUROSEARCH_APP_TOKEN

neurosearch ingest "https://www.youtube.com/watch?v=..."            # one video
neurosearch ingest "https://www.youtube.com/playlist?list=..."     # a playlist
neurosearch ingest "https://www.youtube.com/@somechannel" -t sales  # a whole channel, tagged
neurosearch ask "what do they say about pricing objections?"
neurosearch export --segments   # master sheet CSV with one row per timestamped chunk
neurosearch serve               # web app at http://localhost:8000
```

Ingestion runs in the background: playlists and channels fan out into one job per video, two at a time.
Already-ingested videos are skipped, so re-running a channel just picks up the new uploads.

### Projects

```bash
neurosearch project create "Pricing" --brief "How do top sales trainers handle price objections?" -t sales
neurosearch ingest -p Pricing "https://www.youtube.com/playlist?list=..."
neurosearch ask -p Pricing "compare how they anchor price"
```

A project's sources come from three places, combined: sources added directly, playlists/channels linked to
it, and any source carrying one of the project's auto-include tags. Questions asked inside a project are
answered from that project's sources only, and the brief is passed to Claude so answers stay on-topic.
Answers can be pinned as notes on the project. Use `--web` / the "also search the web" toggle to let Claude
supplement with live web search — web findings are labelled separately from what the transcripts say.

### Growing a project by talking to it

Inside a project's chat (web app or the Claude connector):

- **Paste links to add sources.** Drop a video, playlist or channel URL into the conversation and it's ingested
  into that project on the spot; the chat shows progress and the next answers use the new material.
- **Multiple chats per project.** Each chat is an isolated thread over the same sources — one per idea.
- **Refocus the brief.** "Actually, narrow this to how they handle discount requests" — the assistant rewrites
  the project brief and confirms. Every later answer follows the new focus.
- **Pin findings.** "Pin that" / "save this as a finding" stores the conclusion with its timestamp citations in
  the project's notes (or click *Pin to project notes* under any answer).
- **Gap detection.** When the sources only partly cover a question the answer ends with a `Gap:` line saying
  what's missing and the best next step (a kind of source to add, or a web search), and the gap is recorded on
  the project so it shows up in the findings document.

### Findings document and the masterplan package

From a project (Projects tab → Open) you can download:

- **Findings (.md)** — brief, every pinned finding and open gap with `[Title @ mm:ss](link)` citations, source list.
- **Masterplan (.md)** — a Claude-written synthesis: purpose, executive summary, key insights by theme with
  citations, recommended actions, open questions, how to continue.
- **Masterplan package (.zip)** — everything another AI tool or collaborator needs to pick the project up:
  `README.md` (with a ready-made prompt), `masterplan.md`, `findings.md`, `conversations.md`, `sources.csv`,
  `transcripts/` (full timestamped transcripts, one file per source) and `context.json`. Upload the markdown files
  to ChatGPT, Claude, NotebookLM, etc. and continue there with full context and working citation links.

CLI: `neurosearch project findings "Pricing"` · `neurosearch project masterplan "Pricing"`.

## Web app — how it's organised

`neurosearch serve` runs everything on one port. Sign in with `NEUROSEARCH_APP_TOKEN`.

**Projects are the unit of work.** The home screen is a list of projects; open one and everything inside belongs
to it:

- **Chats** — as many independent chats as you like, each one scoped to *this project's sources only*. Keep the
  sources fixed and open a new chat for each idea or question you want to explore; they don't bleed into each
  other. Inside a chat you can paste links to add sources, say "refocus the brief on …", or "pin that".
- **Sources** — add by link (YouTube video / playlist / channel, podcast, Instagram, mp3/mp4 URL), by uploading a
  file (mp3, m4a, wav, mp4, mov … are transcribed; PDF, Word, text, markdown are read as documents with page-number
  citations; SRT/VTT are used as-is), by pasting text, or by pulling something already ingested in another project
  from the library. Progress for the project's ingest jobs shows at the top.
- **Findings** — pinned answers and recorded gaps, plus the exports (findings .md, masterplan .md, masterplan
  package .zip).
- **Settings** — name, brief (what the project is trying to find out; steers every answer), auto-include tags.

Sources are stored once in a shared library and can belong to many projects, so ingesting the same channel into
two projects doesn't download it twice. "Remove from project" unlinks; "Delete everywhere" removes the transcript.

## Deploy to the cloud (Fly.io)

```bash
brew install flyctl && fly auth signup
fly launch --no-deploy --copy-config --name <your-app-name>   # accept defaults; keep the Dockerfile
fly volumes create ns_data --size 3 --region sjc
fly secrets set ANTHROPIC_API_KEY=sk-ant-... OPENAI_API_KEY=sk-... NEUROSEARCH_APP_TOKEN=<random>
fly deploy
```

Then open `https://<your-app-name>.fly.dev` on your phone and sign in with the token. Railway/Render work
the same way with the Dockerfile — just mount a persistent volume at `/data` and set the same env vars.

### If YouTube blocks the cloud server

YouTube frequently refuses caption/audio downloads from datacenter IPs ("Sign in to confirm you're not a
bot"). Two fixes, use either or both:

1. **Cookies.** Export your YouTube cookies with a browser extension such as "Get cookies.txt LOCALLY",
   upload the file to the server's volume (`fly ssh sftp shell` → `put cookies.txt /data/cookies.txt`) and set
   `NEUROSEARCH_COOKIES_FILE=/data/cookies.txt`. Same file makes Instagram work.
2. **Extract on your Mac, store in the cloud.** Same CLI, one flag — extraction runs locally on your home IP
   and only the transcript is shipped to the server:
   ```bash
   export NEUROSEARCH_REMOTE_URL=https://<your-app-name>.fly.dev NEUROSEARCH_REMOTE_TOKEN=<token>
   neurosearch ingest --remote "$NEUROSEARCH_REMOTE_URL" "https://www.youtube.com/@somechannel" -p Pricing
   ```

## Use it from Claude (desktop, mobile, Claude Code)

The server exposes an MCP endpoint. In the Claude app go to **Settings → Connectors → Add custom connector**
and enter:

```
https://<your-app-name>.fly.dev/mcp/<NEUROSEARCH_APP_TOKEN>
```

(The token in the URL is the authentication — the connector UI has no field for headers. Keep the URL private.)
Claude then gets tools: `search_knowledge`, `ask`, `list_projects`, `create_project`, `add_to_project`,
`list_sources`, `list_collections`, `get_transcript`, `ingest`, `job_status`, `findings`, `masterplan`, `update_brief`, `save_note`. So from your phone
you can say "search my Pricing project for how they handle discount requests" or "ingest this playlist into
the Pricing project" and get timestamped links back.

For Claude Code: `claude mcp add --transport http neurosearch https://<app>.fly.dev/mcp --header "Authorization: Bearer <token>"`.

## How retrieval works

- **Segments** are the raw caption lines with start/end times, kept verbatim so transcripts can be viewed
  and exported.
- **Chunks** are ~60-second windows with 10 s of overlap for long-form content (never crossing a YouTube chapter
  boundary; chapter titles are prefixed), or the whole transcript for anything under 2.5 minutes. Each chunk
  keeps its start time — that's what the citations link to.
- **Search** is hybrid: SQLite FTS5 (BM25, porter stemming) plus OpenAI `text-embedding-3-small` cosine
  similarity, fused with reciprocal rank fusion, capped at 4 chunks per source so one long video can't crowd
  out the rest. Without an OpenAI key it falls back to keyword search only.
- **Answers** come from Claude (`claude-sonnet-4-6` by default) with the top 14 chunks as numbered excerpts;
  the `[n]` markers in its answer are mapped back to source + timestamp. With web search on, Claude's built-in
  web search tool is enabled and web sources are listed separately.

## Costs (rough)

YouTube captions are free. Whisper transcription is ~$0.006/min (~$0.36/hour of audio). Embeddings are
negligible (a 1-hour video ≈ $0.0003). Each question costs one Claude call, typically a fraction of a cent to a
couple of cents depending on the model. A Fly.io machine with 1 GB RAM that stays on runs about $6–8/month.

## Layout

```
neurosearch/
  config.py      settings from env / .env
  db.py          SQLite schema (sources, segments, chunks+FTS, collections, projects, jobs, conversations)
  media.py       yt-dlp: classify URLs, enumerate playlists/channels, captions, audio download
  documents.py   PDF / DOCX / text extraction with page numbers
  transcribe.py  Whisper API with ffmpeg splitting for long files
  chunking.py    segments → timestamped chunks
  embeddings.py  OpenAI embeddings
  ingest.py      extract_transcript / store_transcript / ingest_url orchestration
  jobs.py        background worker threads
  search.py      hybrid retrieval + deep links
  qa.py          Claude answers with citations, chat-ingest, project tools (+ optional web search)
  export.py      findings document and masterplan package
  remote.py      extract locally, store on a remote server
  api.py         FastAPI: REST, web UI, MCP mount, auth
  mcp_server.py  MCP tools
  cli.py         `neurosearch` command
  web/           single-page web app
tests/           offline tests (pytest)
```

## Roadmap ideas

- Speaker diarization for interviews (Deepgram/AssemblyAI) so citations can say who said it
- Per-source auto-summaries and topic tags on ingest
- Scheduled re-scan of channels for new uploads
- Google Sheets sync of the master sheet
- Instagram profile-level ingest (all reels from an account)
