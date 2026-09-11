# Product organization — the philosophy behind every mission (locked 2026-09-09)

*Kyle's own synthesis, filed verbatim-in-substance per the HANDOFF rule ("he locks designs in long messages; file them
before building"). This is not a rung — it is the reading of intent that G1–G9, B1–B7, S1–S5, R1–R7, D1–D3 and L1–L4
have all, independently, been converging on. Read this before proposing new work in any mission; it is the test a new
idea should pass ("does this add organization, or does it add another pile?").*

## The one-sentence version

Neuro Search should not become a pile of Sources, Findings, chats and AI buttons. Its job is to **progressively
organize messy information into something the user can understand and act on** — and to **remember the state of an
investigation over time**, so the user never has to re-decide something they already decided.

## The architecture underneath every mission

```text
THE WORLD
   │
   ▼
Candidates / Catalog          "We know these things exist."
   │  acquire only when worthwhile
   ▼
Global Source Library         "We paid to capture these once."
   │  deliberately attach
   ▼
Project Evidence              "These sources matter to THIS question."
   │
   ▼
Findings                      "Interesting things extracted from evidence."
   │
   ▼
Claims                        "Things Neuro Search believes may be true."
   ├── Strength · Readiness · Freshness
   ▼
Knowledge Map                 "What do we actually know?"
   ├── Tensions (contradictions, missing perspectives, stale, weak/missing evidence)
   ▼
Evidence Targets              "What do we need to settle next?"
   │
   ▼
Discover (library-first)      existing evidence → external candidates → loops back into acquisition
   │
   ▼
MASTER PLANNER                "Given everything we know, what should I actually do?"
```

Three organizational layers recur across nearly every change Kyle has asked for:

1. **Acquisition organization** — what exists, what do we own, what should we capture, how. Candidate Catalog → Global
   Library → Collections → Browser handoff → ingestion.
2. **Knowledge organization** — what have we learned, how reliable, where do sources disagree, what don't we know.
   Findings → Claims → Strength/Readiness/Freshness → Knowledge Map → Tensions → Evidence Targets.
3. **Action organization** — given all of that, what should I do next. Facts/context → Chat → Master Planner → steps,
   dependencies, risks, costs, priorities.

And the implicit principle under all three: **Neuro Search should remember work so the user doesn't have to** — a
skipped video, a subreddit that might hold value, what was rejected and why, what's already owned globally, why a
source mattered, that a site needs the browser, where evidence came from, which Claims need refreshing, a gap noticed
sessions ago, the user's own decisions and circumstances, what a plan was based on.

## Status against every item Kyle raised (checked 2026-09-09, 0.45.5)

| # | Area | Status | Where |
|---|---|---|---|
| 1 | Source organization (channel → videos, subreddit → threads, hierarchy) | **NOT BUILT** | Sources tab is still one flat filtered/sorted list; no grouping by origin. |
| 2 | Global Library — acquire once, attach to many projects | SHIPPED | `library.py`, `identity.attach_existing`; a source is one global row, `project_sources` links it in. |
| 3 | Library-first discovery | SHIPPED | G4 `discover(mode=)` checks the library before the web; `knowledge.pursue` escalates project → library → candidates → external in that order. |
| 4 | Project boundaries (global material doesn't contaminate every project) | SHIPPED | `project_sources.excluded`; project-relative relevance/priority; library profiles are built project-NEUTRAL, never from project findings. |
| 5 | Candidate vs. Source (cheap metadata before ingestion) | SHIPPED | G3 `candidates.py` — a candidate is never evidence, never chunked/embedded, until acquired. |
| 6 | Remember rejected/skipped material | SHIPPED | Candidate states persist (`skipped_low_relevance`, `user_dismissed`, durable); S5 `candidates.pool` resurfaces them against current gaps. |
| 7 | Collection/catalog layer (catalog a whole channel/subreddit without ingesting every item) | SHIPPED (video/web); PARTIAL (Reddit) | G3 `explore.enumerate_*`; G7 `community.explore` catalogs a subreddit's threads as candidates before any thread is ingested. |
| 8 | Rescanning a specific channel/subreddit/category | **NOT BUILT** | No "rescan collection X" action exists — `explore()` runs once per enumeration; there's no durable handle to a channel/subreddit that a later session can re-run against. |
| 9 | Research tab simplification | SHIPPED | R2 shell (0.44.0) + R7 Claims workbench (0.45.5, this session). |
| 10 | Knowledge hierarchy (Findings mature into Claims into a larger model) | SHIPPED | G5 `claims.py` + `knowledge.py`. |
| 11 | Evidence quality: Strength / Readiness / Freshness as separate judgments | SHIPPED | G5 / G5.1 — three distinct fields, never merged into one score. |
| 12 | Knowledge Map (Claims organized by topic) | SHIPPED | G5 `knowledge.refresh` → `project_knowledge_nodes`. |
| 13 | Tensions (contradictions, outliers, weak consensus, stale, missing perspectives) | SHIPPED | G5 `research_tensions`, kinds NOVEL/CONTRADICTION/WEAK_CONSENSUS/STALE/MISSING_PERSPECTIVE. |
| 14 | Evidence Targets (prioritized queue of what to settle, with "enough" defined) | SHIPPED | G5 `project_evidence_targets`, governing/corroborative sufficiency. |
| 15 | Novelty / edge cases preserved, not organized around consensus alone | SHIPPED | NOVEL tension type exists specifically so an outlier is flagged, not discarded or averaged away. |
| 16 | False-consensus protection (copies of one thing ≠ independent corroboration) | SHIPPED | G6 lineage (`claim_evidence.lineage_id`, `derivative_of`) + G7 (six Reddit posts of one link = one lineage). |
| 17 | Claim-level freshness (not just source-level) | SHIPPED | G5.1 `freshness_class`/`freshness_status` live on the Claim, not the source. |
| 18 | Discovery driven by gaps, not generic search | PARTIAL | `knowledge.pursue(target)` is gap-driven and library-first; Discover's *default*, un-prompted mode is still general-purpose, not "search for what the Knowledge Map is missing" as its own standing mode. |
| 19 | Ranking as triage — small batches (top 5), learn from choices, suggest the next 5 | **NOT BUILT** | Discovery ranking (`rank_proposed`) is a static one-shot score; nothing adapts to what the user actually approved/dismissed, and review is not batched incrementally. |
| 20 | Bulk mode still available alongside triage | SHIPPED (the bulk half) | "Ingest all N anyway" / retry-skipped exist; it's the adaptive-triage half (#19) that's missing. |
| 21 | Research learns from user selections (approvals/dismissals shape future ranking) | **NOT BUILT** | Same gap as #19 — no feedback loop from decisions back into scoring, anywhere in the app. |
| 22 | Browser fallback as an explicit workflow state, not a mystery stuck job | SHIPPED | B1 `requires_browser` / `external_pending`, plain-language `error`. |
| 23 | "Needs Browser" state with a direct "Open & Capture" | SHIPPED | B1 — the pending source's card offers the capture path directly. |
| 24 | Extension guidance (the app reminds you the extension is needed) | SHIPPED | Extension badge/heartbeat + popup "wants this page." |
| 25 | Resume the SAME acquisition (no duplicate objects) | SHIPPED | B1 — a browser capture re-runs the SAME job and completes the SAME source. |
| 26 | Large-community handling (catalog subreddit, ingest threads later) | SHIPPED | G7 `community.explore` — same pattern as #7. |
| 27 | Chat as orchestration layer (steer research, flag gaps, initiate Discover, record decisions) | PARTIAL | `qa.py` tools cover research_state, propose_claim, record_fact, note_gap (→ **Settle this**, shipped 0.45.5), native web_search — but there is no chat tool that queues a durable Discover/explore job the way "Settle this" queues a target; a chat-initiated search is still ephemeral, not catalogued. |
| 28 | Master Planner as a distinct mode ("what do we know" vs "what should I do") | SHIPPED (by design) | `planner.py` is its own module/contract, deliberately separate from chat and Research — this is the shipped form of what Kyle asked for, not a gap. |
| 29 | Context weighting (user-supplied context like "I'm taking this class") changes priorities | PARTIAL | The project brief already re-stales and re-weighs relevance (S1/S2) on edit; there is no distinct "context object" (a syllabus, a deadline) that carries its own weighting separate from the brief text. |
| 30 | Local Claude Code as the default engine, API as fallback/explicit acceleration | SHIPPED | L1 (routing) + L3 (0.45.0/0.45.3 acceleration, three-price triage card). |
| 31 | Queue visibility + explicit paid acceleration | SHIPPED | L3, extended this session (0.45.3's background-batch middle option). |
| 32 | Cloud-safe acquisition tiering (a future cloud deployment) | **NOT APPLICABLE YET** | Neuro Search runs local-only today; this is a real design question for if/when a cloud version exists, not a gap in the current product. |
| 33 | Durable state (jobs, dependencies, browser handoffs, provenance survive restarts) | SHIPPED | `jobs.py` — durable SQLite queue, leases, `blocked_by`, `external_pending`. |
| 34 | Clear, distinct status semantics | SHIPPED | `jobs.py` derived statuses; `staleness.py` CURRENT/STALE/current_accepted/REBUILDING; the drawer/triage cards. |

### Related feature-like items (support the model above but are more concrete asks)

| Item | Status |
|---|---|
| Findings deduplication (near-duplicate findings across sources) | **NOT BUILT** — no explicit dedup pass exists; harvest folds a *repeated proposition* into one Claim (G5), but the raw Findings list can still show the same fact from three sources as three rows. |
| Source-comparison / disagreement view | **NOT BUILT** — Tensions surface disagreement at the Claim level; there's no side-by-side "what does source A say vs source B" view. |
| Scheduled channel/collection rescans | **NOT BUILT** — same underlying gap as #8; no scheduling exists at all today (a future session could use the platform's own scheduled-task mechanism once #8 gives it something durable to point at). |
| Speaker identification (diarization) | **NOT BUILT** — transcription has no speaker-separation step. |
| Podcasts / RSS / books / ePub / magazines / interviews | Mostly SHIPPED as content types (EPUB G6P1/P2, RSS via `explore.enumerate_feed`, podcasts/interviews as ordinary media sources); "magazine" has no distinct handling beyond generic document/media ingestion. |
| Shareable plans / findings lists | PARTIAL — chat answers have Share ▾ (C0, 0.35.1); the Master Plan and a findings list do not have their own share flow yet. |
| Mobile chat | **OUT OF SCOPE today** — Neuro Search is a local desktop app; revisit only if/when there's a reason to run it anywhere else. |
| Better export options | PARTIAL — `export.py` covers findings/conversations/transcript Markdown, sources CSV, the Master Plan zip; no format beyond Markdown/CSV/zip exists. |

## What this changes about how the next rung gets picked

Nothing here is queued as a rung yet — this is the map, not the ladder. But it reframes the "small follow-ups" habit:
a good next rung is one that removes a pile, not one that adds a feature. Reading the **NOT BUILT** rows above as
candidates, the ones that look highest-leverage against Kyle's own framing:

- **#1 + #8 (source hierarchy + rescanning)** are the same underlying gap: Sources has no notion of "this group of 40
  videos came from channel X" as a first-class, re-scannable object. Solving the grouping (a `collections` table
  already exists from G3 exploration — check whether it can be promoted into a durable, rescannable handle before
  inventing a second one) would likely unlock rescanning almost for free.
- **#19 + #21 (adaptive triage)** are one feature: batch review that gets smarter from what the user does with it.
  This is the one item on the whole list that changes the *shape* of a workflow (ranking) rather than adding a new
  surface, so it is worth scoping carefully before starting.
- **Findings deduplication** is probably the cheapest win here — the harvest logic already detects a repeated
  proposition for Claims (G5); the same signal could de-duplicate the raw Findings list without a new algorithm.

This document does not decide the order — that's Kyle's call, same as every other mission.
