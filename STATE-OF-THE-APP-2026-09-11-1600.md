# Neuro Search — State of the App

**Version 0.63.34 · 2026-09-11 16:00 UTC · 1,246 automated tests green · release gate PASS**

*This is the one document to read. It is written for someone who has never seen the codebase: a
collaborator evaluating features, giving feedback, or deciding what to build next. It supersedes the
need to read the other twenty documents in this repo — §9 says what each of those is for, and which
ones are archive.*

*Maintained by Claude. Each revision gets a new dated filename and the previous one moves to
`docs/archive/`. If the date above is more than a few days old, ask for a refresh — the app moves
fast enough that a stale version of this file is worse than none.*

---

## 1. What it is, in plain words

Neuro Search turns hours of video, podcasts, documents, spreadsheets, books and web pages into
**research you can cite**. You give it a project brief — "I want to start buying businesses" — and it
ingests sources, transcribes them, pulls out specific findings with verified quotes, tracks which
claims those findings support, notices where the evidence is thin or contradictory, and answers
questions with citations that link back to the exact timestamp or page.

The distinction that shapes every design decision: it is not a chatbot with a document store. It is a
**research state machine** that happens to have a chat window. The durable thing is the evidence and
what it supports; the conversation is a view onto that.

It runs locally on one person's Mac — a single Python process, a SQLite database, one HTML file for the
interface. No cloud service, no accounts, no other users. That is a deliberate constraint, not a stage
it is trying to grow out of.

**Who it is for right now:** one person (Kyle) doing deep research on business acquisition, real estate
and web app design. Everything below is measured against his real corpus, not a demo.

### Current scale (live, today)

| | |
|---|---|
| Sources in the library | **1,863** (1,273 fully processed) |
| Hours of audio/video read | **324** |
| Findings extracted | **17,923** — 16,437 approved |
| Claims tracked | **~16,400** across 3 projects |
| Database | 660 MB |
| AI calls to date | 7,710 — 20% on a local subscription, $144 actual, $433 avoided |
| Spend this month | $147 |

---

## 2. Status at a glance

| Area | State | Notes |
|---|---|---|
| Ingestion (video, audio, docs, sheets, books, web, images) | **Complete** | 10 source types, staged and resumable |
| Search & retrieval | **Complete** | Keyword + semantic, measured baseline |
| Findings extraction | **Complete** | Every finding carries a verified quote |
| Chat with citations | **Complete** | Streaming, citations resolve to timestamps |
| Research state (Claims, evidence, gaps) | **Complete** | The deepest and least-explained part |
| Cost control | **Complete** | Budgets, rate ceiling, per-unit value reporting |
| Speed | **Partial** | Big wins shipped; three rungs left |
| Interface polish | **In progress** | Active work as of today |
| Reviewing stale / low-value content | **Scattered** | Known problem, unstarted — see §6 |
| External AI access (ChatGPT/Claude reading the project) | **Designed, not built** | Largest queued mission |

---

## 3. What it does today — feature by feature

Everything in this section is **built, tested and in daily use**. Percentages and counts are measured
on the live corpus.

### 3.1 Getting material in

- **YouTube, podcasts, audio** — downloads, transcribes (Whisper), chunks, embeds. Handles playlists
  and whole channels, with a review step so you approve what gets ingested rather than dumping 600
  videos into a project.
- **Documents, spreadsheets, PDFs, EPUB books** — page and sheet-level citation. Books are split by
  real chapter structure, so a citation says "Ch. 4 → Section 2", not "byte 91,000".
- **Web pages** — via a Chrome extension ("Send this page"), which also catches videos embedded in the
  page (Loom, Wistia, Vimeo) and offers to fetch them.
- **Images and screenshots** — OCR, cheapest-engine-first: Apple Vision (free, local), then tesseract,
  then a paid model call only if the free ones found nothing readable.
- **Reddit and forum threads** — one thread is one source, individual posts are citable locators.
- **Academic papers** — Crossref and OpenAlex lookup; open-access PDFs can be ingested directly.
- **Courses** — a scanner that walks a course site's lessons and imports the videos, using your own
  logged-in browser session.

### 3.2 Making sense of it

- **Findings.** Each source is read in windows and produces specific, checkable statements. **Every
  finding's quote is verified against the actual transcript before it is stored** — 98.8% of 25,769
  passed; the rest were rejected rather than kept. A finding that cannot be cited is recorded as such
  instead of silently stored (98.3% of recent findings are citable).
- **Claims.** Findings that assert the same thing are merged into one Claim with multiple pieces of
  evidence. Claim strength is computed deterministically — one authoritative source can settle a rule,
  while several independent people agreeing is what settles a pattern. Two sources that share a
  lineage (a quote of a quote) count once.
- **Research gaps.** The app tracks open questions, contradictions between sources, weak consensus and
  missing perspectives, and can go looking for evidence on a specific gap: project → your library →
  sources it has seen but never read → the open web, in that order, stopping as soon as it finds
  something.
- **Chat.** Ask a question, get an answer with numbered citations that link to the exact timestamp.
  Answers stream. It can search the global library mid-answer, list what it actually has, and be told
  "this source is top tier". Every answer can be copied or shared, including a **plain version** with
  the research scaffolding stripped out for sending to someone who does not care about sources — with a
  check that stripping it did not quietly remove the uncertainty.
- **Master Plan** — a synthesised plan built from approved findings, rebuilt when its underlying
  sources change.

### 3.3 Keeping it honest

This is the part that makes the rest trustworthy, and it is unusual enough to call out.

- **Nothing is claimed that was not measured.** Health reports quote validity, citation validity,
  citation rate, model routing, cache hit rates, and whether the last release gate passed.
- **Every cost is explicit before you spend it.** Buttons show both currencies — hours on the local
  subscription, or dollars on the paid API — and nothing spends money without being pressed.
- **Spend is bounded four ways**: daily budget, weekly budget, a dollars-per-hour runaway ceiling, and
  account-level gates that stop the queue rather than letting it retry into a wall.
- **Cost per unit of value.** Not just what was spent, but what it bought: $0.0045 per kept finding
  this month. Spend that no unit claims is named rather than spread.
- **Work is never paid for twice.** If a source's analysis is already bought and in flight, a second
  request is refused with the reason given.
- **The database is integrity-checked and snapshotted hourly**, and every snapshot is reopened and
  verified before it counts.

### 3.4 Things that are deliberately off

Built, measured, and switched off with the reasoning recorded — listed here so nobody rebuilds them:

- **Retrieval reranking** — killed on live measurement; it made results worse.
- **Findings prefilter** — works, but the economics do not (it costs more than it saves on the batch
  path).
- **Planner v3** — not better than v1.
- **Semantic duplicate detection** — the current duplicate finder is lexical and **publishes its own
  floor**: it reports "at least this many duplicates", never "this many". Catching paraphrases needs
  embeddings, which is a costed decision nobody has taken.

---

## 4. In progress right now

**Interface responsiveness (0.63.32 → 0.63.34, today).** The complaint was "I click a button and
nothing happens for 1–5 seconds and I think it's broken". Measured: 228 controls had click handlers and
**12 of them acknowledged the click**. Now every button acknowledges in about 2 milliseconds, greys out
for the whole wait, and bulk actions say what they did. Three bugs surfaced in the process, including
two labelled verdict buttons that had been silently dead because of a duplicate function name.

**Still open in this area:** dropdowns, checkboxes and links get a window-level progress bar but no
per-control state.

---

## 5. What is next — the ladder

Ordered by measured value ÷ risk. This is the honest priority list, not a wish list.

### 5.1 Speed (`SPEED-MISSION.md`)

Rungs R0–R3 are **done** and the wins were large: the slowest screens went from 8–75 seconds to under
half a second, a 5.9 MB request became 228 KB, and a request that ran the entire research pass twice
now runs it never. What is left:

| Rung | What | Why it matters | Risk |
|---|---|---|---|
| **R8** | Database indexes, retention, and a reaper for stuck rows | Includes a real correctness bug today | Low — **do this first** |
| **R9** | Benchmark local models on the M3 Max | Either unlocks free embeddings or closes the question with a number | Low, parallel |
| **R4** | Save completed work units so a retry does not redo them | A retry currently redoes nine finished units | Medium |
| **R5** | Run work units concurrently inside one job | The big one: a 20-minute job is 122-second calls in series | **Highest on the ladder** |
| **R7** | Read only what is genuinely new in a source | Where speed and research depth stop fighting | Medium |

### 5.2 The two big queued missions

- **External AI access** (`EXTERNAL-AI-ACCESS-MISSION.md`) — let ChatGPT and Claude use Neuro Search as
  a private, persistent project memory: a cheap orientation call, project-scoped search, evidence
  drill-down, and writing decisions back in. Its hard rule: **AI interpretation can never become
  evidence.** Blocked on a real problem — there is currently one shared access token and no per-project
  permissions, so every existing tool would be exposed the moment a second identity exists.
- **Transcript intelligence** (`TRANSCRIPT-INTELLIGENCE-MISSION.md`) — cheaper cumulative understanding
  of source material instead of re-reading.

Neither is scheduled. **Kyle decides the order.**

---

## 6. Known problems, stated plainly

Nothing here is hidden in a subsection of another document.

1. **Reviewing stale and risky content is scattered.** The Findings page currently stacks three
   separate review mechanisms — stale sources, findings nothing ever used, and findings that repeat each
   other — with no explanation of how they differ. Two of them offer bulk-dismiss buttons for
   thousands of items. **This is the top UX problem and the fix is probably one consolidated review
   surface rather than three banners.** Not started.
2. **The Findings page is cluttered and dense.** Related to the above.
3. **A long-open browser tab can silently run a months-old interface** against a current server. The
   app says nothing about the mismatch.
4. **3.8% of local AI calls are recorded as "we don't know whether we were charged."** Precisely
   diagnosed, not fixed.
5. **Searching for a term of art fails** when no single word in it names the subject — "quality of
   earnings" anchors on "quality". Two attempted fixes were measured and abandoned; the real fix is
   phrase handling, which nobody has built.
6. **36 paid batch results were collected and never written**, because the other windows of their
   source were cancelled at the provider. Half a source is not a reading of it, so the app correctly
   refuses to write a partial — but the money is spent.
7. **One test flakes** about once in nine full runs. A leaked background worker is the suspicion.
8. **Local AI is currently erroring into the paid API** — the status line reads "Claude Code: error —
   no answer within 240s · API fallback active". Worth investigating; it costs real money when it
   happens.

### Recently fixed, worth knowing because they shaped the rules

- **A Claude session reading the live database crashed the server, twice** (2026-09-11). SQLite in
  WAL mode shares a memory-mapped index between connections and decides it is alone from file locks; a
  session reaching the folder over a bridge mount cannot see the server's locks, so it truncated that
  index under a running server. Read-only mode is **not** protection. The rule is now "never open the
  database from outside the app" and measurement goes through the app's own API.
- **The app kept no log**, so a crash, a deadlock and a startup failure were indistinguishable. It now
  writes `data/server.log`.
- **A crash leaves the port held**, so the next launch failed with an error that scrolled past and
  looked like slow loading. There is now a `restart.command` and a plain-language refusal.

---

## 7. How to evaluate it — for a reviewer

If you have been handed this to give feedback, these are the things worth pressing on.

**Try these, in this order:**
1. Ask the chat a question that needs evidence from several sources. Check that every citation actually
   lands where it says it does.
2. Open the Research tab and look at the open questions. Ask whether they are the questions *you* would
   want answered.
3. Open Findings and try to work out what you are supposed to do on that screen. (This is problem #1
   in §6 — we know, and we want to know how it reads to a fresh pair of eyes.)
4. Look at the Health console. Ask whether any number on it is one you would not trust.
5. Ask it to find something it does not have, and see whether it says so or invents a path.

**Questions we actually want answered:**
- Is the Claims/evidence layer worth its complexity, or is it machinery the user never needs to see?
- Where does the interface explain itself, and where does it assume you already know?
- What would you expect this to do that it does not?

**Two things that are not bugs:** it is single-user and local on purpose, and it deliberately asks
before spending money rather than being fast by default.

---

## 8. Why the code looks the way it does

Six rules explain most decisions, and they were each learned by getting it wrong first.

1. **A failure that is indistinguishable from an answer is worse than no feature at all.** This one has
   been the fix seven times: an OCR step that reported a missing dependency as "no text in this image",
   a course importer that blamed the login for three different problems, a finding stored with no
   citation, a header claiming 8,917 items matched when 345 did, an app that hung with nothing to read,
   a held port reported as slow loading, and a button that had been dead for four releases.
2. **A number nobody reads is worse than a missing number, because the system looks instrumented.**
   Model substitutions were detected and counted correctly for four releases and rendered on no screen.
3. **An expensive pass is not worth having inside a request.** Five separate times, the fix was moving
   work out of the request path and caching it against a revision — never against a clock.
4. **A cache whose key changes faster than its value can be computed is not a cache.**
5. **A ranking change is not verified by its unit test.** It is verified by running the user's own query
   against the user's own library. One change shipped without that and made results worse; it was
   reverted the next release.
6. **Measure before you fix, and record the hypotheses that died.** Roughly a third of the
   investigations in this repo ended in "the obvious fix was measured and abandoned", and those entries
   are kept deliberately so the same idea is not tried a third time.

---

## 9. The other documents — what to read, what to ignore

There are twenty other markdown files here, totalling about a megabyte. **You do not need them.** This
is what they are, so you can ignore them with confidence.

### Live and worth reading

| File | What it is |
|---|---|
| `CLAUDE.md` | The architecture map and standing rules. The single most important file **for a developer**; 2,000 lines. |
| `HANDOFF.md` | How to work on this repo: reading order, the delivery ritual, what "done" means. |
| `HARDENING.md` | The evidence log — every measurement, every fix, every hypothesis that died. Read when you want to know *why*, not *what*. |
| `SPEED-MISSION.md` | The performance ladder (§5.1 above). Still active. |
| `README.md` | Setup and usage. |

### Queued missions — not started

| File | Status |
|---|---|
| `EXTERNAL-AI-ACCESS-MISSION.md` | Designed in detail, amended once, **not built**. The big one. |
| `TRANSCRIPT-INTELLIGENCE-MISSION.md` | Designed, **not built**. |
| `SCHEDULER.md` | A design exploration. **Nothing in it is built**, and it says four things must be measured first. |

### Finished — historical record only

`RESEARCH-MISSION.md`, `RESEARCH-TAB.md`, `SOURCES-FINDINGS-MISSION.md`, `BOOTSTRAP-MISSION.md`,
`PRODUCT-ORGANIZATION.md`, `LOCAL-AI-PROVIDER.md`, `BROWSER-CAPTURE-AND-CATALOG.md`,
`SCHEDULER-ADMISSION.md`, `OVERNIGHT-MISSION.md`, `OVERNIGHT-LOG.md`, `PARAPHRASE-RUNG.md`,
`FINDINGS-YIELD-DEBT.md`, `EXPANSION.md`.

These describe work that is **done and shipped**, or a single measurement kept for reference. They are
the source of the "which mission do I look at?" confusion, because a finished mission document reads
exactly like a live one. **Recommended:** move all thirteen into `docs/archive/` so that the only
`*-MISSION.md` files left at the top level are the two that are actually queued.

---

## 10. One-line summary for anyone who asks

> Neuro Search reads hundreds of hours of video, documents and books, extracts findings with verified
> quotes, tracks what those findings collectively support, and answers questions with citations that
> land on the exact timestamp — locally, on one machine, for a few dollars a week.
