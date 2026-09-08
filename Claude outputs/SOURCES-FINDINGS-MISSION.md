# Sources, Findings and the Known-but-Uncaptured pool — a redesign (mission S, 2026-09-08)

*Claude's recommendation after reading the live project (1,086 sources · 5,222 approved findings · 396 stale sources · 3,954 candidates). Kyle asked for "better ways to organize and surface actions that will be useful to me", "a better way to deal with stale findings", and "a better way to surface and utilize transcripts or findings from the sources or non-ingested sources". Rung ladder D1–D3 (deep content) + S1–S5 at the end; each is a deliverable on its own.*

## 1. What the live project says (the diagnosis)

**Findings are a pile, not a workbench.** 5,222 approved findings, 1,725 of them at importance 1–2, grouped by source title on one page. "Approve all" made approval meaningless: approved ≠ curated. Nothing shows which findings the Master Plan, a chat answer or a Claim ever used, so the page cannot answer "what has this research actually given me?" — the one question that decides what to keep.

**"Stale" is a bill, not a triage.** All 396 stale sources are stale for one reason — *brief changed* — and 182 of them already failed a rebuild. Staleness is exact-input (transcript + brief + prompt), which is correct for provenance and wrong as a to-do list: editing one sentence of the brief stales every source equally, whether it holds the plan's key evidence or three importance-1 findings nobody cited. The only offer is "re-analyse all · $27". With Claude Code now the local provider the trade-off has changed — a rebuild costs $0 and minutes, not dollars — and the surface does not know it.

**Sources say what happened to them, not what they gave.** Filters are pipeline states (working / failed / ready / skipped). A source card shows a findings count and a transcript button; it cannot answer "which sources matter most", "which ready sources produced nothing", "which stale ones matter", or "show me everything this source gave me" without jumping to the 5,222-row page.

**The uncaptured pool is invisible.** 402 sources skipped by the date cutoff (each with a relevance score and a reason) plus 3,638 candidates marked skipped-low-relevance and 26 available: 4,000 known items that could fill today's open questions, reachable only through the Research tab's Evidence Target cards (B3) or a "Ingest all 402 anyway" button.

## 2. Principles

1. **Value is measured, not declared.** A source's value = what its findings became: importance, Claims (strong or not), plan evidence, chat citations, priority. $0, deterministic, from tables that exist. Every list in Sources and Findings can sort and filter by it.
2. **Stale is a triage with three answers** — *rebuild* (it matters, or the transcript changed), *accept as still usable* (brief-only staleness on low-value sources; recorded, never re-run until inputs change again), *retry* (the rebuild failed; show why) — and it names the cost honestly: "$0 · ~N min on Claude Code" or "$X on the API".
3. **A source has one home.** Everything a source gave — transcript with timestamps, findings (all three statuses), the Claims they became, where they were used, staleness — opens from the source card in a drawer. The Findings tab is the cross-source workbench; the drawer is the per-source one.
4. **Known ≠ acquired, but known is searchable.** Skipped sources and candidates are ONE pool, ranked against the project's current gaps (open questions, weak areas), with the reason each is known and one-click capture through the normal path (server → browser when needed). Never web search from here; never evidence until ingested.
5. **Nothing here spends without a click.** All of S1–S5 are $0 surfaces; the only paid actions are the existing rebuild/analyse jobs, now with the local provider named.

## 3. The design

### 3.1 Source Value ($0) — the spine of Sources and Findings

`sources_value.py`: per (project, source) → `findings {approved, suggested, dismissed}`, `importance {max, sum, n4plus}`, `claims {evidence_rows, strong, accepted}`, `used {plan_evidence, chat_citations, last_used_at}`, `priority`, `staleness {status, reasons, accepted}`, `value_score` (documented weights: plan evidence and priority dominate, then strong-claim evidence, then importance ≥ 4 counts, then chat citations; a source with only importance-1 findings scores near zero), `label` (one line: "12 findings · 3 strong Claims · in the plan · cited 7×"). Chat citations come from `messages.citations` (source_id); plan evidence from the latest plan's `_evidence`; claims from `claim_evidence`; all indexed lookups, one pass, cached per project revision.

Sources tab: new sort (Most valuable · Least used · Newest) and filters (**Matters** = priority or plan evidence or strong-claim evidence · **Gave nothing** = ready but 0 approved findings · **Stale, matters** · **Never used**), and each card carries the value line instead of the bare count.

### 3.2 Stale triage — `staleness.triage(pid)`

Partition the stale set by *why* and *whether it matters*:

| Tier | Rule | Offer |
|---|---|---|
| **Rebuild — matters** | stale AND (priority OR plan evidence OR strong-claim evidence OR any finding importance ≥ 4 cited in chat) | "Rebuild these N · $0 ~M min on Claude Code / $X on the API" |
| **Rebuild — transcript changed** | reason contains "transcript changed" | same offer; never acceptable as-is (the evidence text moved) |
| **Accept as still usable** | brief-only (or prompt/schema-only) staleness AND value_score below the tier line | "Accept N — keeps their findings, marks them acknowledged for this brief revision" |
| **Retry failed** | last rebuild failed | the failure reason, "Retry these N" (goes through the normal job path; a browser-solvable failure parks as usual) |

`project_source_analysis.accepted_brief_revision` (additive): `assess()` reports `current (accepted)` while the brief revision matches and nothing else changed; a later transcript change or brief edit stales it again. The Findings-tab banner becomes the triage card (four rows, four buttons) and says the provider and the time, not just the dollars: cost lines come from `usage.observed_rate_per_minute()` + the local split. The Master Plan's stale card gets the same "matters" logic: rebuild the plan after the *matters* tier, not after all 396.

### 3.3 Findings workbench — `GET /api/projects/{id}/findings`

Server-side query with `q` (words over title + content), `min_importance`, `status`, `source_id`, `area` (finding → Claim via `origin_note_id` → `research_view.area_of_claim`), `used` (plan | chat | claim | never), `stale` (source stale / current), `sort` (importance · newest · source · most used), `limit/offset`, plus `facets` (counts per importance, status, used, area, top sources). The tab gets a filter bar and paging; groups stay collapsible per source; each card shows its use badges (📋 plan · 💬 cited 3× · 🧠 Claim strong) and its source's staleness dot. One sweep action: **Low-value sweep** — "412 approved findings at importance ≤ 2 were never used by the plan, a chat or a Claim" → review list → bulk dismiss (never automatic).

### 3.4 Source drawer — `GET /api/projects/{id}/sources/{sid}/digest`

Everything the source gave: value line; findings by status with their use badges and the transcript locator each came from (click → the transcript at that timestamp / the book section / the post); the Claims its findings became (strength, status); where it was used (plan steps, chat answers by title, date); staleness with the tier and the one-source actions (Rebuild · Accept · Retry); **Ask about this source** (opens a chat turn pinned to this source via the existing `attached_source_ids` path); ★ priority; the transcript button. Opens from the card's findings line and from any finding's source chip.

### 3.5 Known-but-uncaptured pool — `candidates.pool(pid, q, rank_by)`

One list over skipped sources (status `skipped`, with the recorded relevance and reason) and Candidate Index rows (available + skipped_low_relevance + links), each with: title · creator · date · why known ("channel review, ranked 35/100, older than the cutoff", "found for question X", "seen in exploration of Y") · **fits** (the open question or weak area it best matches, by the same term overlap `research_view` uses; candidates already linked to a question via B3 rank first) · actions Ingest (server; browser when needed) · Not for this project (dismiss; durable). Search box = `candidates.search` + skipped-source title search. Ranking modes: *Fits an open question* (default), *Relevance score*, *Newest*, *Same creator as a priority source*. Sources tab gets the chip **🔎 Known, not captured (N)** opening this view; the Research questions' "N promising sources known" link lands here filtered to that question. "Ingest all 402 anyway" stays, but the default becomes "capture the 10 that fit".

### 3.6 Deep content — books, podcasts, long interviews, courses (Kyle: "surface more findings from these deep content treasures")

**The loss, measured.** `findings.materialize` keeps the top **12 findings per source whatever its length** (`max_findings=12`) and discards the rest of the validated findings the model already produced per window. The live project has **102 sources over 45 minutes or books — 131 hours of content — and 175 sources sitting exactly at the cap**: a 194-minute course yielded 12 findings, a 166-minute interview 9, a 3-hour automation course 12. Deep content is read at the same depth as a 10-minute clip.

**D1 — keep what was read (no model change).** The cap becomes length-aware: `cap = min(CAP_MAX, BASE + PER_WINDOW × (windows − 1))` (12 + 8 per extra window, max 120) with a **coverage floor** — every window keeps its top 3 before the global importance sort fills the rest, so the last hour of a podcast is never crowded out by the first. Findings beyond the cap are no longer discarded: they land as notes with the new status **`reserve`** ("extracted, lower importance"), invisible to Suggested/exports/planner, visible in the source drawer ("+23 more from this source · Show") and promotable to suggested/approved in one click. Additive (a status value), deterministic, $0; Tier 1 unaffected (call/token totals do not change).

**D2 — Read deeper (explicit, paid or local).** For a long source the card offers **Read deeper**: a second extraction pass with smaller windows (`DEEP_WINDOW_CHARS` = 20k, ≈ 3× the attention per minute) and a depth instruction in the *user* message ("this is a long-form source; extract every distinct, specific finding — aim for 10–20 per part; keep numbers, steps, conditions, named examples"), stored with `depth="deep"` in provenance and in the input hash (so a deep analysis is *current*, not stale). Runs through the normal findings job; with the local provider it costs $0 and the card says the time; on the API it names the estimate. Books use sections as windows (already), so deep = more findings per section, not re-windowing.

**D3 — Under-read detection.** `sources_value` computes `findings_per_hour` (books: per 10k words) and flags **under-read**: long source AND at the cap (or below 4 findings/hour) AND not deep-read. Sources tab chip **📚 Deep content (N)** = books, sources > 45 min, documents > 40 pages; sorted by "most under-read"; bulk action "Read deeper on all N under-read · $0 ~M h on Claude Code / $X on the API". The Research questions' "search my existing research" step gets deep-read findings like any other.

**D4 — Chapter/segment digests (later).** Per section (book) or per 30-minute segment (podcast) a one-line "what this part covers", built from the window summaries the extraction already returns (stored, not shown today), so a 3-hour source reads as a table of contents in the drawer with findings under each part.

## 4. Ladder and honest costs (points of a week: deterministic ≈ 3–4, with UI ≈ +2)

- **D1 Length-aware cap + reserve findings** — `findings.cap_for`, coverage floor, `reserve` status, `POST /api/notes/{id}/status` accepts reserve→suggested, source card "+N more", counts on `/api/sources`. Gate: a 4-window source keeps ≥ 12 + 3×8 candidates when the model offers them; every window contributes; reserve rows never reach exports/planner/claims; promotion works; a 1-window source is byte-identical to today. (**Kyle's newest ask; build first — it recovers value already paid for**)
- **D2 Read deeper** — depth pass with smaller windows, `depth` in provenance + input hash, the card action + bulk action, cost/time line with the provider. Gate: deep analysis is current; windows ≤ 20k chars; the depth instruction lives in the user message (the frozen system prompt is untouched); estimates name the provider.
- **D3 Under-read detection** — `findings_per_hour`, the Deep content chip and sort (rides on S2's value spine).
- **S1 Stale triage** — `staleness.triage`, `accepted_brief_revision`, cost/time lines with the provider, `POST …/staleness/accept`, `rebuild-stale {tier}`, the triage card in Findings and the plan card. Gate: tiers partition exactly; accept survives assess; transcript change re-stales; retry only failed; estimates name the provider. (**Kyle's #1**)
- **S2 Source Value + Sources tab** — `sources_value.py`, `/api/sources` rows carry `value`, sort + four filters, value line on cards. Gate: weights documented and deterministic; plan/chat/claim usage counted from real rows; a source with only importance-1 findings scores below one plan-evidence source.
- **S3 Source drawer** — digest endpoint + drawer UI + "Ask about this source". (**Kyle's #2**)
- **S4 Findings workbench** — the query endpoint with facets, filter bar, paging, use badges, low-value sweep. (**Kyle's #2**)
- **S5 Known-but-uncaptured pool** — `candidates.pool`, the chip and view, ranking modes, capture through the normal path. (**Kyle's #3**)

Everything reuses existing tables and paths: no new model calls, no new fetch path, no schema beyond two additive columns (`accepted_brief_revision`; a `value_cache` kv per project revision). Research-tab work (R2 shell) is untouched by this mission and consumes S2's value data when it lands.
