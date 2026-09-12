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
./start   # or: neurosearch start (auto-restarts on updates) · neurosearch serve (plain)               # web app at http://localhost:8000
```

Prove it works before you trust it: `neurosearch eval` runs the frozen Golden Project through the whole pipeline
(no keys, no network — `NEUROSEARCH_FAKE_AI=1` fakes the models) and reports retrieval recall, citation and quote
validity, tokens and cost; `neurosearch eval --live --baseline` does the same against the real models. See HARDENING.md.

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

### Importing a course you're logged into (Loom / Vimeo / Wistia behind a paywall)

Sources → **Import a course**. Download the small browser extension (Chrome, Edge, Brave, Arc), load it via
`chrome://extensions` → Developer mode → Load unpacked, and point it at your app address + password once. Then log
into the course in that browser, open the page listing the lessons, click the extension → **Scan this course**. It
follows the lesson links inside your logged-in session, finds each embedded player (Loom, Vimeo, Wistia, YouTube,
mp4), shows the list, and sends the videos plus your session cookies to the app, which downloads and transcribes
them as "Module › Lesson" sources in a course collection. The app never sees a password; cookies live only on the
server in `data/cookies/`. Works from another computer on your network (the pane shows the address to use) or from
anywhere if the app is deployed.

### Discover sources (for when you don't know where to start)

Sources → **Discover** searches the web for the leading creators, channels and podcasts for the project's brief
and returns ~10 with who they are, why they matter for *your* brief, their angle or bias, a fit rating, depth
level, and a starting video. Add the starting video or the whole channel with one click, dismiss what you don't
want, and steer another run ("more practitioners, fewer gurus", "podcasts only"). Suggestions persist on the
project and later runs skip what's already been proposed or added.

### Suggested findings

Most long videos and podcasts are mostly fluff. When a source finishes ingesting into a project, the assistant
reads the whole transcript against the project's brief and proposes the 3–12 findings that matter — each a
self-contained claim with a timestamp, a short quote and an importance rating — and scores the source's
**substance** (0–100) with a two-line summary so the Sources list shows at a glance what is worth your time.
Suggestions wait in the Findings tab (grouped by source) until you approve or dismiss them; only approved findings
feed the exports and the Master Plan. "Analyse new sources" / "Re-analyse all" run it on demand; per-source
"Suggest findings" is on every source. Turn auto-analysis off with `NEUROSEARCH_AUTO_SUGGEST=false`.

### Starting a project well

"New project" is a four-step setup because the assistant and the planner are only as good as what they know at
the start: **Basics** (name, the goal — what "done" looks like, the brief — what you need to find out, and starting
questions that each become a ready-made chat), **Situation** (budget, deadline, your experience, tools and accounts
you already have, hard constraints, what's already decided or rejected — all recorded as requirements), **Sources**
(links to start with, and what kinds of sources you trust), and **Output** (who it's for and what you want at the
end). Everything is editable later in Settings, and every prompt — chat answers, suggested findings, the Master
Plan — is steered by it.

## Master Planner (Plan mode)

Research answers *what do we need to know?* — the **Master Plan** answers *given everything we know, how do we
accomplish this?* Every project has a **Research | Plan** switch. Building the plan reads the whole project —
sources, findings, chats, uploaded documents, recorded decisions/constraints, and the project context you give it
(budget, deadline, experience level, tools you already have) — and produces:

1. Goal · 2. Recommended approach (with alternatives and why not) · 3. First steps you can start today ·
4. Phases fitted to the project · 5. Dependencies (blocking vs non-blocking) · 6. Decisions (decide now vs later,
with a recommendation) · 7. Tools & services (required / recommended / optional, free vs premium, cost) ·
8. Costs (minimum / recommended / premium, estimates flagged) · 9. Risks with mitigations, prioritised ·
10. Beginner gotchas · 11. What we don't need to worry about yet · 12. Open questions (blocking / soon / nice) ·
plan confidence · Ready to start.

Every recommendation carries its **basis** (research-backed, user-provided, planner judgement, or estimate) and
links to the evidence it rests on, so nothing is a black box. Items have statuses (not started, ready, blocked, in
progress, complete, needs research, needs decision). **Research this** on an open question opens a new chat with
the question ready to run. When research changes after the plan was built, **Check for updates** shows the
previous vs. proposed recommendation and why — accept, keep, or research further; accepted changes rebuild the plan
(statuses carry over). **Start project** marks the first steps ready and moves the project into execution.

Share it: **Plan (.md)** or **Share page (.html)** — a clean standalone page for teammates; both are also included
in the masterplan package. Decisions and constraints you state in chat ("we're going with X", "budget is $500")
are recorded automatically and visible in Settings. CLI: `neurosearch project plan "Site move" --build`,
`--html --out plan.html`. MCP: `build_master_plan`, `get_master_plan`, `record_fact`.

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
- **Master Plan** — Plan mode (see above).
- **Settings** — name, brief (what the project is trying to find out; steers every answer), auto-include tags.

Sources are stored once in a shared library and can belong to many projects, so ingesting the same channel into
two projects doesn't download it twice. "Remove from project" unlinks; "Delete everywhere" removes the transcript.

## Supported operating model

Neuro Search is a single-user local application. Start it with `start.command` or `neurosearch start`, then use
`http://localhost:8000`. Keep the data directory on the same Mac as the server. `Dockerfile`, `fly.toml` and the
remote-ingest compatibility path are retained as historical evidence while cloud and multi-user architecture are
parked; they are not supported deployment directions. The exact former README is preserved at
`docs/archive/README-2026-09-11-pre-foundation.md`.

### The spending valve (and picking up where it left off)

Every paid call — answers, findings analysis, plans, discovery, embeddings, Whisper — is logged with an estimated
cost, shown as "$x today · $y this month" in the sidebar. Set a **daily** and **monthly budget** in Settings
(defaults $5 / $50, or `NEUROSEARCH_DAILY_BUDGET_USD` / `NEUROSEARCH_MONTHLY_BUDGET_USD`). When a budget is
reached the background queue **pauses** — nothing fails, nothing is lost, jobs keep their order — and resumes at
midnight / the 1st, or immediately when you raise the limit. **Pause queue / Resume** in Sources gives you the same
valve by hand. The queue lives in the database, survives restarts, and never re-does a finished video, so a
400-video channel can be spread over several days without babysitting. Things you start yourself (a chat
question, a plan build) are still allowed while the queue is paused. Prices are estimates; override with
`NEUROSEARCH_PRICES='{"claude-sonnet-4-6":[3,15]}'` if the models or rates change.

### Channels and playlists wait for approval

A single video starts ingesting the moment you paste it. A channel or playlist does not: it is listed first (a
cheap, free enumeration) and shows up in Sources as **Review before starting** — every video with its length, a
cost estimate, select all / none / filter — and nothing is downloaded, transcribed or analysed until you press
**Start ingesting selected**. Discard drops the list. This applies wherever a channel link comes in: the Link tab,
a chat message, Discover's "+ Channel", or the new-project form. (The CLI keeps the old immediate behaviour.)

### Only recent videos (whole channels)

Channels and playlists default to **videos from the last 2 years, at most 150** (`NEUROSEARCH_SINCE_YEARS`,
`NEUROSEARCH_MAX_VIDEOS`; both adjustable per pull in Sources → Link). Older videos are marked *skipped* rather
than transcribed, and because a channel's Videos tab is newest-first, the first too-old video cancels the rest of
that channel's queue so no time or money is spent finding out the remaining 400 are older still.

### Being polite to YouTube (whole channels)

Bulk pulls are the thing that gets a home IP temporarily rate-limited ("Sign in to confirm you're not a bot" —
clears in hours, not a ban). The app fetches from YouTube one video at a time with a randomised pause between
them (`NEUROSEARCH_YT_DELAY`, default 4 s), and if YouTube throws the bot-check it pauses all YouTube fetches for
`NEUROSEARCH_YT_BACKOFF_MINUTES` (default 20), re-queues the affected videos, and shows the pause in the Sources
tab. For a 300-video channel expect roughly half an hour of background work. Instagram is far stricter — treat it
as one reel at a time, and avoid bulk pulls with your own login cookies.

### If YouTube asks for sign-in

Use the app's local cookie directory and Health guidance. Account cookies stay server-side and bulk YouTube
downloads do not use them by default. Instagram acquisition uses the browser extension's logged-in session.

## MCP on the local machine

The server exposes MCP for local integrations. Keep it bound to the local operating model and protect it with
`NEUROSEARCH_APP_TOKEN`. Public/mobile connector access remains parked until project-scoped authorization exists.
Current tool contracts live in `neurosearch/mcp_server.py` and are covered by the release gates.

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
couple of cents depending on the model. The app records actual routing and estimated spend in its usage ledger.

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
  findings.py    suggested findings + substance scoring per source
  discover.py    find creators/channels/podcasts for the brief (web search)
  courses.py     course import: cookies file + per-lesson ingest jobs (fed by extension/)
extension/       Chromium extension: scans a logged-in course page and sends lessons + cookies to the app
  planner.py     Master Planner: plan generation, updates, statuses, markdown/HTML rendering
  remote.py      parked cloud-ingest compatibility path; investigate usage before archival
  api.py         FastAPI: REST, web UI, MCP mount, auth
  mcp_server.py  MCP tools
  cli.py         `neurosearch` command
  web/           single-page web app
tests/           offline tests (pytest)
```

## Product direction

`PRODUCT-SCHEDULER.md` is the only current queue. Historical roadmap lists and mission documents are evidence,
not assignments. Foundation stabilization is active; Transcript Intelligence follows its formal closeout.
