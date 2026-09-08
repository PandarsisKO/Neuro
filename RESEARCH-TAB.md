# The Research tab — what it is for, how it works, and why it overwhelms (handoff for a redesign session)

*Written 2026-09-08 at 0.34.2, from the code. Everything in the tab is the G5 "Research Intelligence" rung (0.29.0 → 0.30.x), extended by G6 Works, G7 community evidence and B2 completeness. Nothing here costs money unless a button says "model".*

## 1. The one-sentence purpose

Chat answers questions; Findings are quotes you approved; the **Research tab is the project's memory of what it currently believes, how well each belief is evidenced, and what a competent researcher would establish next** — so that the chat, Discover and the Planner stop treating every question as new and stop presenting one source's opinion as settled.

Everything on the tab is *proposed research state* built for $0 from your approved findings. It does not decide anything for you; it keeps score.

## 2. The mental model (five objects, one loop)

```
approved Findings ──harvest ($0)──▶ CLAIMS ──assess ($0)──▶ strength · readiness · freshness
                                      │
                                      ├──▶ KNOWLEDGE MAP   (Claims grouped by topic: what the project knows per area)
                                      ├──▶ TENSIONS        (where the evidence disagrees, is thin, stale, or one-sided)
                                      └──▶ EVIDENCE TARGETS (questions that must be settled, with "enough" defined)
                                                 │
                                    pursue: project → global library → seen-not-added → web
                                                 │
                                    new sources → new findings → back to the top
```

**Claim** — one proposition the project has evidence for ("SBA 7(a) equity injection must be at least 10 % of total project cost"). Harvested from findings; two findings saying the same thing become one Claim with two evidence rows. Each Claim has a *type* (regulatory / rates / tactic / experiential / …), a *topic*, a *status* you control (proposed → accepted / rejected / superseded), an optional *application* note ("applies to my deal because…"), and three assessments the app computes:

- **Strength** — *how well evidenced*. Governing claims (a rule, a rate, a definition) need one current authoritative source to be Strong. Corroborative claims (experience, tactics, opinion) need several **independent** sources: copies, quotes and reprints of one document count once (G6 lineage), six Reddit posts repeating one article count once, six different owners describing the same failure count six (G7). `strength_why` is the sentence that explains it.
- **Readiness** — *can you act on it*: separate from strength on purpose. Strong ≠ decision-ready: a rule can be Strong and still not apply to your situation, which is your judgement (the `application` field).
- **Freshness** — *is it still current*: per Claim class (regulatory, rates, promotional, underwriting practice, tactics, experiential, static…), never a global age cutoff. `current / needs_refresh / stale / uncertain / age_insensitive`, with the reason. The $0 guess errs toward `uncertain`, never toward a false "stale".

**Knowledge Map node** — a topic with ≥ 3 Claims, summarised as a state (strong / developing / weak / missing) with a *why* that never just counts sources.

**Tension** — an automatically detected problem in the evidence: `CONTRADICTION` (two Claims disagree), `NOVEL` (one source says something nobody else does), `WEAK_CONSENSUS` (several sources, none independent), `STALE`, `MISSING_PERSPECTIVE` (only brokers, no owners — the G7 flagship). Each has an impact level and can be *Resolved* or *Dismissed* by you.

**Evidence Target** — a question that must be established before you decide, with a sufficiency rule: *governing* (one authoritative source closes it) or *corroborative* (needs N independent sources). It records what "enough" means, the current gap, and the trail of where the app already looked. **Pursue** runs the mandated escalation in order and at $0: this project's evidence → the global library (other projects' sources) → sources seen but never added (the Candidate Index, reranked against the target, including ones skipped earlier) → the web (only when you press the web variant; that one queues a Discover job).

**Community synthesis** (G7, shown under Sources → Communities, fed by this state) — cross-thread states (FREQUENTLY_REPORTED, MIXED_EXPERIENCE, STRONG_DISAGREEMENT, RARE_BUT_SERIOUS, FIRSTHAND_EXAMPLES), derived, and since B2 qualified when built on partially captured threads.

## 3. How it is meant to be used (the intended weekly loop)

1. Approve findings as usual (chat, Findings view). The Research state harvests them automatically after findings jobs (debounced) — or press **Refresh ($0)**.
2. Read the **Knowledge Map** first: which areas are strong, which are developing, which are missing. That is the honest map of the project.
3. Look at **Tensions**: each one is a place where the answer you would get in chat is less settled than it sounds. Resolve the ones you have thought through; leave the rest — the chat's system prompt reads open tensions and hedges accordingly.
4. Turn the things you actually need to settle into **Evidence Targets** (type the question, pick governing/corroborative). Press **Pursue** — the app looks in everything it already has before it ever searches the web, and shows the trail ("project 0 → library 2 → seen 3 (1 resurfaced)"). Attach what it found, or press the web variant.
5. Optionally, once per project, press **Normalise Claims (model)** — one bounded model pass that cleans candidate Claims (qualifiers, type, topic, freshness) and proposes targets you did not name. "Evaluate normalisation" is the measured, resumable version (~150 Claims) that proves whether normalisation earns wider use; it is an engineering instrument as much as a feature.
6. In **Claims**, accept the propositions you stand behind (Accept makes a Claim *yours*; the app never accepts on your behalf), reject the wrong ones, and write an application note on the ones that matter for your decision. Accepted, Strong, current, applicable = decision-ready.

The chat participates through two tools: `research_state` (it reads the map, tensions, targets and community synthesis when a question touches them) and `propose_claim` (an external assertion becomes a proposed Claim plus a target, never accepted truth).

## 4. Why it overwhelms (an honest diagnosis)

- **Everything is on one page, at the same visual weight.** Map, tensions, targets and Claims are four different jobs (orient, worry, plan, decide) rendered as four stacked lists with identical cards. On a 449-source project that is hundreds of rows with no hierarchy.
- **The most important question — "what should I do next?" — is nowhere.** Targets are the answer, but they sit third, below a map that mostly says "developing".
- **Engineering instruments are exposed as features.** "Normalise Claims (model)" and "Evaluate normalisation (≈150)" exist to prove the G5.1 policy; a user should see at most "Improve Claims (one model pass, ≈ $1)". The evaluation summary line ("merged 12 · qualifiers present 118/150 · hedges kept…") is a release-gate readout.
- **Vocabulary is internal.** strength / readiness / freshness / sufficiency / governing / corroborative / lineage / independent / normalised — every card shows five of them. They are the right concepts; they are the wrong labels for a first read.
- **Claims are a flat, paged list** (300 shown of 4,203) with no way to navigate by topic, status, or "needs my decision". The map nodes are not clickable into their Claims.
- **Actions are per-card and tiny** (Accept / Reject / Resolved / Dismiss / Pursue) with no batch operations and no explanation of consequences ("Accept" changes what the chat treats as settled — the page does not say so).
- **No entry point from the work.** You arrive from the sidebar, not from a question. The Discover header links to "the map", the chat mentions tensions, but nothing says "this answer rests on a Weak claim — open it".

## 5. What a redesign could look like (a starting position, not a decision)

- **Lead with "Next":** open evidence targets (with the pursue trail and one-click *Look* / *Search the web*), then tensions with impact — the two things that ask for an action. Map and Claims become drill-downs.
- **Make the map navigable:** a node click filters the Claims list to that topic; states become a small legend, not a tag per row.
- **Claims as a workbench, not a list:** filters (needs decision · accepted · weak · stale · by topic), batch accept/reject, one plain-language line per Claim ("Strong — one current SBA SOP; applies to your deal? not yet said") and the internals behind an expander.
- **Rename in the UI, keep the code:** Strength → *Evidence*, Readiness → *Ready to use?*, Freshness → *Still current?*, governing/corroborative → *one authoritative source is enough / needs independent sources*, Evidence Target → *Open question*, Tension → *Watch-out*.
- **Hide the instruments** behind a "Research tools" expander (Normalise, Evaluate, the evaluation readout) or move them to Settings → Advanced.
- **Connect to the work:** a "Why this answer" affordance on chat citations that opens the Claim; a "Settle this" button in chat gaps that creates a target.

## 6. Architecture (for the session that will change it)

**Modules.** `claims.py` (harvest, assess, extract/normalise contract `claims.extract` with schema `claim-set-v1`, `select_cohort` + `run_evaluation`, `relate`, `add_evidence`, independence by lineage/creator, `FRESHNESS_RULES`, `stale_by_source`), `knowledge.py` (`refresh` = harvest → assess → map nodes → tensions → targets → community synthesis; `pursue`, `add_target`, `list_tensions`, `state()` paged: 300 claims / 12 evidence / 100 lists), `works.py` (lineage for independence), `community.py` (`synthesize`, `missions`), `qa.py` (tools `research_state`, `propose_claim`; the research block in the system prompt; the truncation-aware chat), `db.py` tables `project_claims`, `claim_evidence` (with `lineage_id`, `source_revision`, `locator`, `independent`, `stale`), `project_evidence_targets`, `project_knowledge_nodes`, `research_tensions`, `claim_evidence_notes`, `community_syntheses`, kv `claims:eval:{pid}:pending`.

**Endpoints.** `GET /api/projects/{id}/research` (the paged state), `POST …/research/refresh {extract}`, `POST …/research/evaluate {budget}`, `GET …/research/evaluation`, `POST /api/claims/{id}/status {status, application}`, `POST /api/claims/{id}/relate`, `GET/POST /api/projects/{id}/targets`, `POST /api/targets/{id}/pursue {external}`, `POST /api/targets/{id}/status`, `POST /api/tensions/{id}/status`, community: `GET …/community/synthesis`, `GET …/community/missions`.

**UI.** One view `#view-research` in `web/index.html`: `renderResearch(state)` fills `#resMap`, `#resTensions`, `#resTargets`, `#resClaims`; `refreshResearch`, `evaluateNormalisation`, `loadEvaluation`, `claimStatus`, `tensionStatus`, `targetStatus`, `addTarget`, `pursueTarget`; `renderResearchHeader` on Discover; `stTag(state)` for the coloured pills. The sidebar count `#nResearch` = live Claims.

**Invariants the redesign must keep (locked decisions).** Claims are project state, never library state; everything works with zero model calls; normalisation is bounded and importance-driven, never corpus-wide; Strong ≠ decision-ready; freshness is Claim-relative and errs to uncertain; independence is by lineage (G6) and by person (G7); community evidence can never establish a governing rule; model output is proposed state — status changes only through `claims.set_status`; targets escalate project → library → seen → web with web only on request; a synthesis over a partial thread says so. Gates: `tests/test_k6_claims.py` (10-point fixture), `test_k8_works.py`, `test_k9_community.py`, `test_l2_completeness.py`; Tier 1 chat totals are frozen (34 / 196,951) — a change to the research block text in the chat prompt re-freezes them.

**Numbers from the live project** (accounting-practice acquisition, 449 sources): 4,203 Claims harvested, refresh 1.8 s, one bounded normalisation evaluation of 150 Claims in 19 calls for $1.21.

## 7. R1 baseline note + the engine that R2 renders (0.37.0)

**Baseline (before any redesign; suite 398, Tier 1 34 / 196,951, no behaviour change).** Every user-facing control on the tab, what it mutates, and what it costs:

| Control | Mutates | Cost | Chat / Planner consequence |
|---|---|---|---|
| Refresh | harvest → assess → map → tensions → targets (`claims.ensure` + `knowledge.refresh`) | $0 | the research block in the chat prompt and `research_state` change |
| Normalise (extract=true) | `project_claims.normalized`, merges | one bounded `claims.extract` call per 20 Claims | merged Claims cite the same evidence |
| Evaluate | a durable `extract_claims` evaluation job | paid, bounded (≤ 300) | none until reviewed |
| Claim: Accept / Reject / application | `claims.set_status` | $0 | accepted Claims lead the chat's research block; rejected ones leave it |
| Target: Look (pursue, external=false) | `last_escalation`, candidate links | $0 | `research_state` shows what is known but uncaptured |
| Target: Search the web (external=true) | a `discover` job | discovery budget | proposals appear in Discover |
| Target: settle / close | `project_evidence_targets.status` | $0 | the gap leaves the chat's research block |
| Tension: Resolved / Dismiss | `research_tensions.status` | $0 | the tension leaves the chat's research block |
| Capture best N | attach or `ingest_url` jobs (browser when needed) | $0 (+ ingest) | new evidence → next refresh |

Auto-resolution that already exists: every refresh re-selects NOVEL / WEAK_CONSENSUS / STALE / MISSING_PERSPECTIVE deterministically and resolves the ones it no longer selects; a target whose gap closes is `satisfied` by `assess`; a dismissed tension or closed target is never reopened by the machine. Sidebar count (old): live Claims. Live stress case (the 449-source project, read 2026-09-08 at 0.37.0): 4,420 Claims, 1,332 open questions (importance 5: 407; 4: 293), 57 watch-out issues, overview in 414 ms; at 0.37.2 (4,778 Claims, overview 435 ms, attention 19, 9 high-impact issues) the 20 areas are: Everything else 1,424 · Due diligence 710 · Tax strategy 652 · Seller financing 494 · Business credit 432 · S-corp taxation 206 · Source relevance screening 148 (the "not relevant to this project" findings — a candidate for hiding in the shell) · Asset protection 123 · Deal financing 92 · Franchise economics 91 · Business valuation 88 · LLC formation privacy 64 · Business growth tactics 57 · SBA collateral requirements 51 · Business formation costs 40 · Business acquisition 39 · Holding company structure 23 · Entity structure 19 · S-corp tax strategy 13 · Worker classification 12. Top of `next`: "Due diligence evidence may be outdated" (82), "Business valuation evidence may be outdated" (76), "Seller financing evidence may be outdated" (76), "S-corp taxation evidence may be outdated" (73), "Business credit: no authoritative or expert voice yet" (72). "Everything else" is 30% of the Claims: those carry a lone-word harvest topic and share no vocabulary with any area — the honest ceiling of $0 clustering; a bounded normalization pass (`claims.extract`) is what would label them.

**The engine (`research_view.py`, $0, deterministic — R3 + R5 + R6, shipped 0.37.0 without the shell).** `overview(pid)` → `summary`, `next` (top 5 across questions + watch-outs by `score`), `recently_improved`, `attention`, `areas`, `empty`. `questions(pid)` = evidence targets in plain language (`headline`, `label`, `what_settles_it`, `current`, `gap`, `already_checked`, `known_uncaptured`, `why_asking`, `if_ignored`, `actions` with cost). `watchouts(pid)` = tensions grouped into ISSUES by (kind, area): title by the single Claim's label or the area, `detail`, `impact`, `underlying` rows, one `action`. `areas(pid)` = greedy Jaccard clustering over the topic nodes' term bags (`AREA_MERGE` 0.22); topics that are generic words (`GENERIC_TOPICS`) or hold fewer than `AREA_MIN_CLAIMS` are folded into the nearest cluster, never shown; names come from the cluster's own multi-word topic labels (the largest, plus a second when nearly as large — "Acquisition due diligence framework"); single-word topics never stand alone when a multi-word topic exists; short finding titles, then distinctive terms, are fallbacks only (0.37.1). A lone-word topic holding many Claims (the harvest's "business", "revenue", "deal"…) is unlabelled bulk: each Claim is placed by its own words (`BULK_MIN_OVERLAP`), the unplaceable ones in an explicit **Everything else** area; `area_of_claim` is the authoritative placement, `area_of_topic` the topic-level approximation for filters (0.37.2). Priority = base by type (`BASE`) + 5 × importance (finding importance; user facts 5) + planner dependence (+15, Master Plan `_evidence` overlap ≥ 0.5) + impact (high +15 / low −10) + breadth (+3 per extra Claim, cap 12) + known uncaptured sources (+8) + recency (+5 within 7 days) + applicability unknown on a strong Claim (+8). Attention (the sidebar number, R3) = high-impact watch-outs (issues, already aggregated) + planner-dependent open questions + strong proposed Claims of importance ≥ 4 awaiting a decision; capped at 99; never the Claim count and never the important-question count (700+ on the live project — that stays in `summary.important_questions`). Endpoints: `GET /api/projects/{id}/research/overview|questions|watchouts|areas`; `GET …/research` now carries `attention`. Gate `tests/test_n1_research_view.py`.

**What R2 (the shell) renders from it.** Overview = `summary` + `next` + `recently_improved`; Questions = `questions` (open first); Watch-outs = `watchouts` (drill-down = `underlying`); Areas = `areas` (click → filter Claims/Questions/Watch-outs by `area`); Claims workbench and Research tools unchanged underneath. "Not important to my project" on a watch-out = `POST /api/tensions/{id}/status dismissed` for each underlying row (R5's remaining half); per-area drill-down filters are client-side over `area_of_topic`.
