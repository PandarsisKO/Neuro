# Design audit — raw evidence notebook

Mode: FULL AUDIT, **read-only half only** (interaction walks deferred to a second pass on an audit instance — Kyle's
decision 2026-09-13). Nothing was clicked that queues work, spends, changes status or deletes. Per `AUDIT.md`
this notebook is deliberately detailed and unpolished; `audit.md` and `ladder.md` are the synthesis.

## Phase 0 — baseline and scope

| | |
|---|---|
| Version / commit | 0.63.43, HEAD `b85c222`; working tree carries Codex's uncommitted bootstrap/resources/index.html set and Claude's mmap reversal |
| Date | 2026-09-13 (session started ~17:40 PT 2026-09-12) |
| Admission path | Foundation §34 UI scope for D0–D2; any D3 rung that changes a surface's job is a §13 override (see DESIGN-MISSION.md §0) |
| Instances | **Live instance only, read-only**, via Claude in Chrome at 1440×900. Audit instance not built; every Phase 3 walk is *observed, not exercised* |
| Viewport | 1440×900. A 400×800 resize was attempted; the capture frame stayed 1436×840, so **no narrow-viewport evidence exists in this pass** |
| Projects used | "I want to start buying businesses…" (876 sources, 16,437 findings, 34 chats, plan mode) — the largest real project; home screen across all 13 |
| Tooling limits | Screenshots not saved to `evidence/` this pass (viewed inline); console read only for errors |
| Known constraints respected | local-first, single-user, explicit cost consent, deep provenance |

### Incident found during Phase 0 (not a design finding — filed separately, must be fixed first)

The home screen listed **10 projects named `G2`, `G2 api`, `G2 chat`, `Article routing`** with brief "brief", 0–1
sources, created **16:40:44 and 16:49:48 PT 2026-09-12** — the two runs of Codex's "focused suite, 73 passed" on
`tests/test_k3_resources.py`. Cause: that module (and **78 others**) sets the data dir with
`os.environ.setdefault("NEUROSEARCH_DATA_DIR", tmp)`; Kyle's `.env` sets `NEUROSEARCH_DATA_DIR`, so `setdefault`
loses and a *focused* run hits production. `test_core.py` hard-sets it, which is why the full suite is safe and a
single module is not. The server then **executed the test-queued jobs with real providers**: OpenAI embeddings,
Claude Code (`claude code claude-sonnet-5 answered`), a YouTube fetch of `@BenKelly`, and one `discover` job
requested as sonnet-4-6 and answered by haiku-4-5 (a model mismatch). The test process had `FAKE_AI=1`; the server
that ran its jobs did not. Systemic fix: hard-set `NEUROSEARCH_DATA_DIR` in `tests/conftest.py` (runs before every
module), and add a gate that fails if any test module still uses `setdefault` for it. Ten modules set no data dir
at all and rely on `fresh`/`tmp_path` fixtures — verify each. Filed to Kyle 2026-09-13; nothing deleted.

## Phase 1 — product map (from the live UI, not the nav labels)

| Surface | User intent | Primary question | Primary action | Main states seen | Scale risk | Cost/consequence | Feeds |
|---|---|---|---|---|---|---|---|
| Home (all projects) | pick up a project / see the library | which project, how big is my library | open a project; "+ New project" | 13 projects incl. 10 test junk; "Your research in numbers" stat block | grid only; no sort/search/archive at 13; would fail at 50 | none | everything |
| Project › Chats | ask the corpus | what did the research say about X | Ask (composer) | 34 chats in sidebar; answer with [n] citations; "also search the web" toggle | chat list unbounded in sidebar | web search = spend; not stated inline | Findings (pin), Plan |
| Project › Sources | manage what's owned; add more | what do I have and what did it give me | add (6 tabs) / filter / per-row actions | 1348 rows grouped by origin; tiles; filter chips; each row has 6 actions | 1348 rows rendered as one list (grouped), ~80 px each; 8,970 "known, not captured" | "Delete everywhere" red on every row; "Suggest findings" spends | Findings, Chat, Research |
| Project › Findings | review/curate evidence | what's worth keeping, what's stale | Rebuild / Accept stale banners; per-row Dismiss | 16,437 findings; stale banner (822 sources) with 3 priced actions; "4805 never used" banner; grouped by source | renders after ~5–8 s with **empty area meanwhile**; list unbounded | Rebuild $29.72 / $18.33 / $14.86 / $9.17 stated ✓ | Claims, Plan, Chat |
| Project › Research | what to do next | what needs my attention | "DO THESE NEXT" ranked cards, $0 actions | Overview tiles (1710 / 15 / 101 / 36/52); panes Questions 200 · Watch-outs 72 · Areas 52 · Claims 16123 · tools | 1710 open questions is a number, not a queue | "$0" stated on each action ✓ | Plan, Chat, Discover |
| Project › Master Plan | act | what do I do this week | "Start project"; This-week checklist | stale banner w/ 4 priced options; Start here; This week; "Make this plan yours" Q&A chips; footer tabs | fine | $48.49 / $24.46 stated ✓ | — |
| Project › Settings | steer | is the brief right | Save | long form + decisions/constraints table | fine | none | everything (brief revision) |
| Health / Jobs | trust | can I trust it right now | Re-check | not opened this pass | — | — | — |

## Phase 2 — cold first-time-user walk + five-second scorecard

Scored from the interface alone, no builder knowledge.

| Surface | Where am I | Current state | What matters | What to do next | What that will do |
|---|---|---|---|---|---|
| Home | **Partly** — "Neuro Search" + a grid; no page purpose | **No** — one dense grey line: "$0.43 today · $147.58 this month · Claude Code: not checked · use Re-check or start local work · 8,229 AI calls · 24% local…" reads as a log line, not a status | **No** — 13 equal cards; test junk indistinguishable from real projects | **Partly** — cards are the only affordance; "+ New project" is a small card | **Partly** — card click opened Chats view, not stated |
| Chats | **Yes** — sidebar + chat title | **Partly** — spend/local status only in a 10 px sidebar footer | **Yes** — the answer | **Yes** — composer | **Partly** — "also search the web" checkbox: no cost/consequence text; "attach a document or screenshot" fine |
| Sources | **Yes** | **Partly** — 7 stat tiles in ~11 px type, then a counts sentence; the *state* (Failed 1 · Skipped 471 · Known-not-captured 8970) is in filter chips, not a status line | **No** — every row is equal weight; "Matters/Stale/Priority/Under-read/Deep-read/Gave nothing/Never used" are toggles with no default emphasis | **No** — six buttons per row × 1348; the add-source panel (textarea + 6 tabs) dominates the top even when you came to review | **Partly** — "What this gave" / "Transcript" clear; "Suggest findings" silent on cost; "Remove from project" vs "Delete everywhere" adjacent and only colour-separated |
| Findings | **Yes** | **Partly** — for ~5–8 s the list area is blank with no indicator (looked empty); then two stacked amber banners | **Partly** — banners say what's stale and what it costs; but "4805 approved findings at importance ≤2 were never used" is a third banner competing with the first two | **Partly** — Rebuild/Accept are clear and priced; row "Dismiss" is the only row action; no "use in plan" | **Yes** for Rebuild ($ stated); **No** for Dismiss (reversible?) |
| Research | **Yes** — "Research", a purpose line, four tiles | **Yes** — tiles read as orientation | **Yes** — "DO THESE NEXT, ranked by what it costs you to leave it alone" | **Yes** — one primary per card, $0 stated | **Yes** — "If you leave it: Chat and the Master Plan keep treating these as needing re-verification" |
| Master Plan | **Yes** | **Partly** — stale banner first, plan second; version/date tiny | **Yes** — "Start here" / "This week" | **Yes** — "Start project", checklist | **Partly** — four priced re-analyse options in one banner is a decision the user has to parse |
| Settings | **Yes** | n/a | **Partly** — brief textarea shows 3 lines of a 25-line brief | **Yes** — Save | **Partly** — no statement that changing the brief invalidates findings/plan (it does: brief_revision) |

Moments that depended on builder knowledge: what "Known, not captured 8970" means; what "substance 38/100" is; what "cited 2×" counts; why a source is "stale" (transcript changed? brief changed?); what "Rebuild in the background" vs "on the API" changes besides price; that the card click lands on Chats; that "Deep content 141" is a mode; the meaning of the sidebar badge "16437" on Findings (count of all, not of attention items).

## Phase 3 — workflows: observed, not exercised

Not exercised in this pass (no audit instance). Observed entry points only:
- **Add/acquire**: Sources › Link/Upload/Paste/From library/Discover/Browser extension. The link textarea is
  pre-populated with example URLs in grey (placeholder) — three lines of YouTube URLs; a first-time user may believe
  they are real. "Channels/playlists: only the last 2 years, best 20 videos" appears as a control row without a label.
- **Findings review**: two amber banners each with 2–3 priced actions; "Hide for now" link; row-level "Dismiss" only.
- **Research**: cards with $0 primary + "Resolved" / "Not important to my project" secondaries — outcome labels ✓.
- **Chat**: composer + web toggle + attach.
- **Plan**: stale banner with "Rebuild plan / Re-analyse now + rebuild · $48.49 / Re-analyse in background + rebuild · $24.46 / Raise budget".
- **Jobs / cost feedback**: not opened.

## Phase 4 — screen-by-screen observations (evidence only)

### Home
- H1: The global status line is a single muted sentence mixing money, provider health, an instruction ("use Re-check or start local work"), call counts and a percentage. It is the only place the app says whether local AI is healthy. `[Visual]`
- H2: Project cards are uniform; no last-activity, no attention signal, no distinction between a 876-source project and a 0-source test project. `[Visual]`
- H3: "Your research in numbers" block has 7 stat tiles with mixed emphasis (476.6 / 19 days 20 h 37 min / 5875k / 1.6× / 19138 / $147.58 / $555.74) — the number typography is the largest type on the page, larger than any project title; the block answers "how much" not "what now". A "Another comparison" link suggests it is a fun-stats widget. `[Visual]`
- H4: Card click on the card body gave a focus ring but did not navigate; clicking the title did. `[Runtime]` — acknowledgement gap.
- H5: `🌙 Dark` button is emoji-glyph + label (fine per DESIGN.md), positioned in the header at 12 px. `[Visual]`

### Chats
- C1: Sidebar footer packs `$0.43 today · $147.58 this month · Claude Code: not checked · use Re-check or start local work · 8,229 AI calls · 24% local · $144.98 actual · $522.74 avoided` into a ~110 px wide column at ~10 px — unreadable at a glance. `[Visual]`
- C2: Citations `[n]` inline in prose; the citation panel is not visible without interaction. Answer body is full-width prose at ~15 px, ~140 chars/line — over DESIGN.md's 65–75. `[Visual]`
- C3: "Rename · Share this chat · Delete" top-right: Delete is plain text, same weight as Rename. `[Visual]`

### Sources (1348 rows)
- S1: Every row carries six actions: What this gave · Transcript · Suggest findings · ☆ Make priority · Remove from project · **Delete everywhere** (red text). 1348 × 6 = 8,088 buttons on one page. `[Visual/Code]`
- S2: Thumbnail column is an empty grey rectangle on every row observed — missing thumbnails universal, no fallback glyph. `[Visual]`
- S3: Row meaning line is good ("substance 38/100 · This transcript is a general how-to…") — value before pipeline state ✓ — but the "ready · captions" pill sits before it. `[Visual]`
- S4: Filter chip row mixes counts (`All 1348 · Failed 1 · Ready 876 · Deep content 141 · Skipped 471 · Known, not captured 8970`) with a right-aligned search box; then a *second* row of "Show:" toggles; then Expand all / Collapse all. Three control rows above the first source. `[Visual]`
- S5: The add-source panel (tab strip + textarea + options) occupies the top ~180 px of the page on every visit, even for a project with 1348 sources where reviewing is the more common intent. `[Visual]`
- S6: "Master sheet CSV" and "Segments CSV" are exports placed among filters. `[Visual]`
- S7: Stat tiles: 7 tiles, label under number, number ~20 px, label ~11 px, each with a ~2-line muted explanation — tiles are dense but every one is a "how much". `[Visual]`

### Findings (16,437)
- F1: **Blank-while-loading**: for ~5–8 s after navigation the area below the filters was empty with no skeleton, no spinner, no "loading" — indistinguishable from "no findings". `[Runtime]` (DESIGN.md §11 explicitly forbids this.)
- F2: Three stacked banners above the work: stale (822 sources; two sub-sections each with two priced Rebuild options + "Accept 399 as still usable"), "SUGGESTED — Nothing waiting", and "4805 approved findings at importance ≤2 were never used" with "Review them" / "Dismiss all 4805". `[Visual]` (DESIGN.md §8 Findings: "avoid stacked warning banners above the work".)
- F3: Rows are dense and good: importance dots, title, one-line meaning, badges (`plan`, `2×`, `weak`, `⚠ stale source`, topic), source link, `quote`. **Four to five badges per row** vs DESIGN.md's two. `[Visual]`
- F4: Grouping by source with per-group `filter` and `source ↗`; group header shows count. Good structure. `[Visual]`
- F5: The filter row has six selects (approved / any importance / used anywhere or not / any source state / any area / sort) and a search — no visible active-filter summary. `[Visual]`
- F6: Sidebar badge `16437` in red on Findings reads as an alert; it is the total. `[Visual]`

### Research
- R1: Best surface in the app. Purpose line, four orientation tiles, "DO THESE NEXT" ranked with the consequence of inaction stated, $0 on every primary. `[Visual]` — **strength to preserve**.
- R2: Card actions are text buttons of equal weight: "Find current evidence · $0" (filled) vs "Show the 20 Claims" / "Resolved" / "Not important to my project" (plain) — hierarchy present. ✓
- R3: Pane strip "Overview · Open questions 200 · Watch-outs 72 · Areas 52 · Claims 16123 · Research tools" — counts as nav; "Claims 16123" invites opening a 16k list. `[Visual]`
- R4: "1710 important open questions" as a stat tile is a number nobody can act on; the ranked list below is the real answer. `[Visual]`
- R5: "Recently improved" list uses a `settled` pill per row — one badge, consistent. ✓

### Master Plan
- P1: Stale banner at top with **four** priced/unpriced options in one row: "Rebuild plan", "Re-analyse now + rebuild · $48.49", "Re-analyse in background + rebuild · $24.46", "Raise budget". Cost stated ✓; four choices before the plan is visible ✗. `[Visual]`
- P2: "Start here" card and "This week" checklist above analysis — matches DESIGN.md §8. ✓
- P3: "Make this plan yours — 0 of 4 answered" with chip answers per question — good pattern; chips are pill-styled inputs (consistent). ✓
- P4: Footer tab strip (Where you stand · Do this · Decide · Money & tools · Watch out · Evidence) sits at the *bottom* of a long page. `[Visual]`

### Settings
- T1: Brief textarea shows ~3 visible lines of a ~25-line brief; the most important text in the project is mostly hidden. `[Visual]`
- T2: No consequence statement near Save ("changing the brief marks findings/plan as needing re-verification"). `[Visual/Code: brief_revision]`
- T3: Decisions/constraints table: kind pill + text + "remove" — clean. ✓

### Global
- G1: Sidebar chat list is unbounded (20+ entries visible); no grouping by recency. `[Visual]`
- G2: Every view's title is 15–17 px bold; no page-purpose line except Research and Findings ("What's worth keeping…"). `[Visual]`
- G3: Mode toggle "Research | Plan" at the top of the sidebar changes the *project's* mode, not the view — looks like a segmented view switch. `[Visual]`
- G4: Console: no first-party errors in the sampled window (one Chrome-extension exception, not ours). `[Runtime]`
- G5: Version tag `v0.63.43` in the sidebar footer at ~10 px. `[Visual]`

## Phase 5 — design-system drift (measured 2026-09-12/13, ratchet in `tests/test_s50_design_drift.py`)

| Measure | Value | DESIGN.md asks |
|---|---:|---|
| inline `style="` attributes | **430** (static + JS templates) vs 259 lines of CSS | none in new UI; ratchet |
| colour literals outside token blocks | 28 CSS / 3 JS | 0 |
| distinct `font-size` | **16** (9, 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15, 16, 17, 18, 20, 22, 24) | 6 |
| distinct `border-radius` | **11** (2, 3, 6, 7, 8, 9, 10, 12, 14 px, 50%, 999px) | 4 (+50%) |
| controls whose only glyph is an emoji | 8 (✕ ✓ 📌 …) | 0 |
| colour tokens with no dark value | 0 | 0 |
| `--ok` / `--warn` contrast on `--panel` | 3.47 / 3.64 (**fail AA**) | ≥ 4.5 (frozen values fix: 5.29 / 5.24) |

Observed drift, not counted: three different "primary" button treatments (filled accent on Research cards, filled
accent "Ask" in the chat composer, filled blue "Rebuild plan" in the plan banner, plain-text "Add" in Sources); red
used both for destructive ("Delete everywhere") and for a count badge (Findings 16437); pills used for statuses,
filters, chips-as-inputs, and version tag alike.

## Phase 6 — cross-surface observations (candidates, unverified)

- Stale × everything: the same 822 stale sources produce a banner on Findings, a banner on Plan, a "⚠ stale source" badge on every finding row, and a "Stale" filter on Sources — four presentations, four vocabularies ("stale source", "analysed against older inputs", "plan may be stale", "needs re-verification").
- Cost × surfaces: Findings and Plan state $; Sources "Suggest findings" and Chat "also search the web" do not.
- Counts × navigation: sidebar badges (34 / 876 / 16437 / 99+) are totals; Research's badge is the only one that means "needs you".
- Polling × Findings: not measured (would need a longer observation) — flagged for the interaction pass.
- Home × test data: junk projects are indistinguishable from real ones — a symptom of the incident above, but also of H2.

## Phase 7 — root-cause candidates (to be consolidated in audit.md)

RC-A **No attention model.** Every count is a total; "what needs me" exists only on Research. Home, Sources,
Findings, Plan each answer "how much" first.
RC-B **No shared action hierarchy or vocabulary for reprocessing.** Rebuild / Re-analyse / Re-rank / Suggest /
Re-check / Rebuild in background vs on the API — priced inconsistently, styled inconsistently.
RC-C **Stale has four faces.** One state, four presentations, four names.
RC-D **Row action overload on the workbenches.** Sources: six per row incl. destructive; Findings: badges ≥4.
RC-E **Loading is indistinguishable from empty** on the large lists.
RC-F **Status is a log line.** Spend/health/local-AI state rendered as one muted sentence in two places.
RC-G **Styling lives inline.** 430 inline styles / 16 sizes / 11 radii — the measured cause of the visual drift.
RC-H **Test isolation gap** (incident, not design) — must precede any implementation rung.

## Strengths worth preserving (must not regress)

Research overview's "DO THESE NEXT" with consequence-of-inaction and $0 stated; explicit dollar amounts on every
paid rebuild; Findings row density and per-source grouping; Plan's "Start here / This week" before analysis;
"What this gave" meaning line on sources; decisions/constraints table; light-default with a working dark theme;
citations inline in chat; "Make this plan yours" chip answers.

## Assumptions / cannot verify in this pass

Narrow viewport (resize did not take); polling flicker; Health/Jobs surfaces; every Phase 3 walk; whether the
Findings blank period is network or render (needs timing); dark theme not screenshotted this pass.
