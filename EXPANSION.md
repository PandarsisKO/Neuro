# Neuro Search — Master Feature Expansion Mission + Ladder

## Mission: Research Intelligence and Universal Evidence Acquisition

### Foundation constraint

**Feature Expansion begins from the hardened Neuro Search 0.24.0 platform** (tag `hardening-complete`; see HARDENING.md).

New capabilities must build on the hardened platform rather than creating parallel ingestion, AI, storage, retrieval, job, provenance, revision, staleness, validation, cost, provider, or release infrastructure. They must reuse, extend, or deliberately integrate with the platform's existing: global source identity, source lifecycle, Global Library, canonicalization and deduplication, durable jobs and dependencies, external-pending work, provenance, source revisions, staleness, project-relative analysis, retrieval, findings, structured model contracts, structured outputs, validation, provider resilience, cost accounting, budget controls, Health / Doctor diagnostics, release checks and gates.

**Expansion should add capabilities and intelligence, not weaken or duplicate existing guarantees.**

> **Feature expansion must build on the hardened 0.24.0 platform rather than creating parallel ingestion, AI, storage, retrieval, job, provenance, or cost paths.**

---

# 1. Mission statement

Make Neuro Search capable of starting from an incomplete research mission and progressively determining:

1. what the user actually needs to know
2. what the project already knows
3. what claims, assumptions, requirements, constraints, deadlines, and decisions it currently relies upon
4. what remains uncertain, weak, contradictory, stale, incomplete, or missing
5. which questions an expert would investigate that the user may not know to ask
6. what type of evidence would resolve each uncertainty
7. whether Neuro Search already owns useful evidence
8. what intellectual works, authorities, communities, datasets, manuals, books, or other source classes should exist
9. where those works can legitimately be acquired
10. which manifestation or copy is the best ingest target
11. whether that evidence has already been acquired globally
12. how the evidence relates to specific claims
13. whether the evidence is independent
14. whether the evidence is current
15. what new concepts, contradictions, citations, risks, requirements, or unknowns emerge from it
16. what additional research has the greatest expected value
17. whether further research would materially change a decision
18. when the project has enough trustworthy evidence to act
19. what needs to be monitored because reality may change later

Target progression:

```text
Understand the mission → Build structured project state → Map the subject → Identify knowns and unknowns
→ Identify claims and assumptions → Determine evidence requirements → Check current project evidence
→ Check Global Library → Discover missing evidence → Resolve intellectual works → Acquire the best available manifestation
→ Ingest once globally → Attach deliberately to projects → Interpret evidence locally → Validate claims and provenance
→ Update confidence / freshness / project state → Detect new concepts / gaps / contradictions → Prioritize further research
→ Determine research sufficiency → Feed trustworthy conclusions into planning → Monitor time-sensitive dependencies where needed
```

The user should not need to already know which IRS publication exists, what an applicable statute is called, which FAA manual governs a question, which textbook or syllabus matters most, which technical terminology an expert would search, which foundational book exists, what podcast episode or interview contains important tribal knowledge, what subreddit or specialist forum contains relevant firsthand experience, whether a Spotify episode has an RSS manifestation, whether a book has a legitimate digital copy, whether Neuro Search already ingested the same source six months ago, whether twelve articles are actually repeating one original source, whether the evidence is obsolete, or what important question they failed to ask. That is increasingly Neuro Search's job.

---

# 2. Product model

Two coordinated intelligence systems.

**A. Research Intelligence** determines: what should this project know? what does it currently know? what claims does it rely upon? what requirements, constraints, deadlines, or decisions exist? how strong is the evidence? what is missing, contradictory, stale? what perspectives are absent? what evidence would resolve the uncertainty? which research task matters most? when is the evidence strong enough to act? what may need to be refreshed or monitored later?

**B. Evidence Acquisition** determines: do we already possess useful evidence? what intellectual Work are we trying to obtain? what resource or collection contains it? what manifestations exist? which is best? can it be acquired legitimately? has it already been acquired globally? how should it enter the standard source lifecycle, be parsed, cited, participate in revisions and staleness, and relate to project Claims?

Discover sits at the intersection. Discover must no longer mean "find some URLs that appear relevant". It should mean:

> **Identify the strongest evidence available to improve this project, prioritizing information the user already owns, identifying evidence the user does not know to seek, and acquiring new material only where meaningful gaps remain.**

---

# 3. Ultimate research unit: the Claim

The current system is source-centric; the mature system becomes increasingly **claim-centric**. Sources are how knowledge enters. Claims are what the user believes, questions, compares, verifies, rejects, plans around, depends upon, and acts upon.

```text
SOURCE → EVIDENCE → CLAIM (supported / contradicted / qualified / interpreted / superseded by evidence) → KNOWLEDGE MAP → DECISION / PLAN
```

A research gap should increasingly mean "this important Claim or decision dependency does not yet have sufficient evidence", not merely "we do not have many sources on this topic".

---

# 4. Platform rules inherited from 0.24.0 (apply to every new capability)

**Rule 1 — Every source type enters through the same source lifecycle.** Reddit, forum, book, podcast, website, image, PDF, spreadsheet, syllabus, magazine, GitHub repository, future connector: all participate where applicable in classification, canonicalization, global identity, deduplication, acquisition, ingestion stages, provenance, revisions, staleness, project attachment, project-relative analysis, findings, claims, retrieval, durable jobs, cost accounting, validation. Platform-specific acquisition adapters are acceptable; parallel source universes are not.

**Rule 2 — Global Library first, external acquisition second.** Before downloading, scraping, transcribing, OCR, multimodal interpretation, embedding, paying a provider, or launching expensive AI analysis, check whether the source or Work already exists globally. Reuse expensive project-independent artifacts; keep project-specific interpretation local.

**Rule 3 — Discovery and authority are separate.** Preserve separate signals for at least relevance, authority/primacy, recency, user preference, project-specific importance; where applicable specificity, independence, accessibility, evidence class. `official syllabus > generic course advice` even when the generic advice is semantically closer to a query.

**Rule 4 — Every generated artifact remains explainable.** Where did this come from? Which source and revision? Which evidence supports it? Which model/task generated it, when? Is it current? Is any input stale? Was evidence removed or superseded? Did a newer revision change the result?

**Rule 5 — New asynchronous work uses the durable job system** (site exploration, enumeration, channel imports, community ingestion, OCR, multimodal, source resolution, recursive Discover, bibliography expansion, monitoring, scheduled refresh, profiling). No ad-hoc threads or parallel task systems.

**Rule 6 — Cost is part of the product experience.** Estimate when practical; surface new acquisition vs reuse; distinguish immediate vs background; support cheaper/slower alternatives; respect budgets; preserve usage attribution.

**Rule 7 — Fail open for discovery, fail closed for evidence.** Discovery may be exploratory, broad, incomplete, probabilistic, noisy, speculative; a failed candidate must not sink a pass. Evidence must be attributable, validated, auditable, provenance-backed, appropriately current, project-scoped, clear about uncertainty. Findings, Claims, citations, plans, deadlines and factual conclusions must not silently inherit speculative Discover state.

**Rule 8 — Recursive discovery is powerful but bounded** by budgets, stopping rules, deduplication, source-gap tracking, acquisition value, research priority, evidence sufficiency, user control. Not an autonomous general crawler.

**Rule 9 — Time-sensitive information is structured state** (`effective_from`, `effective_until`, `deadline`, `expiration`, `retrieved_at`, `confidence`, `source`, `refresh_required`, `refresh_after`, `monitoring_cadence`, `next_check`, `action`, `dependency`) for syllabus deadlines, exams, promotions, offers, prices, regulations, licensing, application windows, warranties, subscriptions, certifications, renewals. Feeds future Planner/Tracker.

**Rule 10 — Multimodal processing creates evidence**: locatable, retrievable, attributable, citable, revision-aware, claim-supporting — not merely an AI description.

**Rule 11 — User interaction refines structured project state.** "This is authoritative", "Ignore this source", "The deadline moved", "I chose option B", "I completed this" update facts, constraints, source preferences, authority rules, decisions, rejected options, tasks, deadlines, completion state, Knowledge Map, monitoring requirements. Conversation is an input surface for the project model.

**Rule 12 — Features earn production adoption** through measurable usefulness. An experiment that does not outperform the current system is removed or disabled. A failed experiment is acceptable; shipping a worse system because the roadmap expected the feature is not.

---

# 5. Core architectural invariants

- **A. Parse once globally. Interpret locally. Retrieve selectively.** Global: acquired files/media, transcript, extraction, page/timestamp structure, OCR, figures, tables, chunks, embeddings, canonical metadata, neutral Source Profile, provenance, revision history. Project-relative: relevance, source role, project summary, findings, Claim relationships, project authority, importance, planner implications, freshness requirements.
- **B. A source is acquired once globally.** Every entrance resolves global identity first: `ALREADY_IN_PROJECT → no-op · EXISTING_READY → attach · EXISTING_PENDING → attach to the same global work · EXISTING_FAILED → reference and retry if requested · NEW → create once, acquire once`.
- **C. Identity is stronger than URL equality.** Prefer platform-native ID → canonical Work identifier → canonical URL → content fingerprint → normalized URL. (YouTube video ID; podcast GUID/enclosure; paper DOI; book Work/ISBN; periodical ISSN + issue/article.)
- **D. Projects remain controlled evidence environments.** Project Evidence (attached, affects reasoning) · Library Candidates (owned, not attached, suggest only) · External Candidates (not owned; cannot become evidence until acquired and attached).
- **E. Resource, Work, Manifestation, Source, Revision, Evidence, Claim are distinct.**
- **F. Containers and items behave differently.** Page → ingest; website → explore; sitemap/channel/RSS/folder → enumerate; document/video → ingest; image → analyze; repository/subreddit → explore; query → discover; ISBN → resolve.
- **G. Deterministic discovery precedes expensive reasoning** (identity lookup, sitemaps, RSS, structured metadata, canonical links, repository trees, indexes, native IDs, citations, titles/descriptions first).
- **H. Evidence dimensions remain independent** (relevance, authority, primary-source status, specificity, recency, independence, project preference, project importance, accessibility); manifestations separately carry exactness, completeness, provenance, citation precision, fidelity, persistence, rights confidence.
- **I. Authority is contextual** (course: syllabus > professor > assigned material > external academic > supplemental; aircraft maintenance: AD > manufacturer > mechanic > owner; tax: law > IRS guidance > professional > article > community). No universal authority order.
- **J. Different evidence classes answer different questions**: authoritative, expert, experiential, market/current-state, historical.
- **K. Original evidence remains the citation target.**
- **L. Time is a first-class property** (`published_at`, `retrieved_at`, `effective_from/until`, `supersedes/superseded_by`, `freshness_class`, `refresh_requirement`).
- **M. Repetition is not corroboration.** Track lineage and common origin.
- **N. Source content is untrusted input.** Never overrides agent instructions, project policy, tool permissions, security boundaries, credential handling, acquisition rules.
- **O. Research is bounded by value** (decision impact, uncertainty, evidence weakness, information gain, freshness urgency, cost, dependency impact).

---

# 6. Cross-cutting intelligence systems (emerge across the ladder)

**A. Claim & Evidence Graph** — Source Revision → Evidence → Claim with SUPPORTS / CONTRADICTS / QUALIFIES / INTERPRETS / SUPERSEDES / EXPERIENTIAL. Target statement: "supported by two independent primary sources; three secondary sources repeat the same interpretation; one older source conflicts but has been superseded."
**B. Entity Resolution** — FAA ≡ Federal Aviation Administration; IRC §280F ≡ 26 USC 280F; Beechcraft Baron 58 ≡ BE58. Improves Knowledge Map, Discover, retrieval, dedupe, contradiction detection, citation resolution.
**C. Temporal Intelligence** — what is true now / previously / when it changed / what superseded it / is the planner stale. Freshness classes STATIC · SLOW_CHANGING · PERIODIC · FAST_CHANGING.
**D. Research Audit Trail** — what triggered this, which Claim/gap, what evidence existed, what was missing, what was searched, what was rejected, why selected, what changed.
**E. Feedback Learning** — not relevant / wrong jurisdiction / too old / duplicate / weak authority / already known / wrong product / do not use this domain / not useful for this project. Project-specific unless deliberately promoted.
**F. Research Sufficiency** — UNRESEARCHED · WEAK · DEVELOPING · STRONG · DECISION_READY (enough evidence to act responsibly, not every question answered).

---

# 7. The implementation ladder

Cumulative. Every rung preserves everything hardened before it. Every rung has a **Feature Gate** and a **Platform Integration Gate**; a rung is not complete unless both pass.

## RUNG 1 — Global Source Identity & Deduplication

**Mission:** protect the user's existing research investment; a source is acquired once globally and reused across projects.
**Build:** one shared resolution path `resolve_or_create_source(candidate)` returning ALREADY_IN_PROJECT / EXISTING_READY / EXISTING_PENDING / EXISTING_FAILED / NEW, using native identifiers, canonical URLs, fingerprints and other identity signals; prevent duplicate races transactionally. Existing → attach, reuse global artifact, run project-relative analysis. New → create global source, attach, durable ingestion lifecycle.
**Review UX:** `317 found · 84 already in Global Library · 12 already in this project · 221 new`; selected: `24 reuse existing assets · 51 require acquisition`; quote cost only for genuinely new work.
**Feature Gate:** the same source entering by multiple pathways results in 1 global acquisition and N project relationships; pending acquisition is shared.
**Platform Integration Gate:** Global Library reuse, canonical identity, durable jobs, provenance, revision compatibility, staleness compatibility, project-relative analysis, usage/cost accounting, validation, release checks.

## RUNG 2 — Universal Resource Input

**Mission:** understand what the user supplied before deciding what pipeline to run. `INPUT → RESOURCE CLASSIFICATION → STANDARD SOURCE / COLLECTION LIFECYCLE`.
**Recognize:** page, website, website_section, sitemap, document, image, video, channel, playlist, feed, repository, community, folder/archive, spreadsheet, search_query, work_identity.
**UX:** "Add something to research — paste a URL, upload a file, or describe what you're looking for." `irs.gov → Website detected → Explore website / Add page only`; `ISBN → Book detected → Find available copy`; `GitHub repository → Explore relevant files`.
**Feature Gate:** a root website, repository, community, or Work identity no longer falls through to naive webpage ingestion.
**Platform Integration Gate:** every resulting source still enters the canonical lifecycle; no type bypasses global dedupe, durable jobs, provenance, revisions/staleness, cost, validation.

## RUNG 3 — Website & Collection Exploration

**Mission:** turn containers into ranked candidate sources: `enumerate → rank → review → attach/acquire`. Pipeline: RESOURCE → ENUMERATOR → CANDIDATES → CANONICAL IDENTITY → GLOBAL LIBRARY CHECK → **CANDIDATE INDEX** → PROJECT RANKING → REVIEW → ACQUIRE | SKIP (retain metadata).
**Website exploration** prefers sitemap → sitemap indexes → robots → RSS → navigation → metadata → internal links → linked documents → constrained site search. Do not crawl the entire domain; project needs drive exploration. `irs.gov` might yield `97 Publication 946 · 95 Form 4562 Instructions · 93 Publication 463 · 88 Business-use guidance · 11 Careers`.
**Feature Gates:** a large domain yields a concise project-specific candidate set rather than thousands of crawled pages; **and** after enumerating a 300-item channel and acquiring 20, the 20 become global Sources while the other relevant items remain searchable as Candidates without transcripts or content embeddings. Non-selected credible candidates must not disappear (see Candidate Memory below).
**Platform Integration Gate:** enumeration, ranking, acquisition and retries use existing job infrastructure, source identity, Global Library dedupe, cost controls, provenance, validated Review state.

## RUNG 4 — Global Library Intelligence

**Mission:** use previously acquired evidence before spending money. Default `PROJECT → GLOBAL LIBRARY → EXTERNAL WORLD`.
**Global Source Profile:** neutral, reusable representation of what a source can answer (topics, entities, type, authority, temporal, useful-for).
**Retrieval funnel:** all global sources → cheap matching → candidate reduction → authority/freshness filtering → relevant chunk inspection → strong suggestions. Bias toward precision; "no relevant library evidence found" is acceptable.
**Discover modes:** Library first (default) · Library only · Web first · Web only.
**Feature Gate:** Neuro Search recognizes useful evidence already owned without letting it affect the project until deliberately attached.
**Platform Integration Gate:** profiles remain project-neutral; project evidence boundaries intact; provenance points to the reused global source/revision; reused sources never repeat expensive ingestion; project analysis still runs separately; cost reporting shows savings accurately.

## RUNG 5 — Knowledge Map, Claim Graph & Evidence Planning

**Mission:** determine what a competent researcher should investigate before searching for more URLs. Discover becomes Research Intelligence.
**Knowledge Map** tracks topic, coverage, confidence, evidence quality, freshness, contradictions, missing perspectives, research state (e.g. Financing Strong/High/none · Maintenance Moderate/Medium/better experiential · Tax Weak/Low/primary authority · Insurance Missing/None/current underwriting · Resale Missing/None/market).
**Claims:** normalize important propositions; connect evidence as SUPPORTS / CONTRADICTS / QUALIFIES / INTERPRETS.
**Evidence Target:** question → preferred evidence classes in order → current evidence → gap.
**Detect:** unsupported/weak Claims, missing primary sources, stale evidence, contradictions, repeated derived evidence, single-source dependency, missing source class/perspective, weak planner assumptions, unknown unknowns.
**User interaction:** chat statements update structured state ("This syllabus is authoritative", "The deadline changed to October 12", "Ignore advice from this forum", "I chose option B", "I completed this step").
**Whenever a new Evidence Target is created:** 1. check project sources · 2. check Global Library · 3. query the Discovery Candidate Index · 4. only then external discovery.
**Feature Gates:** a deliberately vague project produces meaningful missing research areas and Evidence Targets the user never named; the system identifies weak corroboration despite many repeated sources; **and** a new gap can rerank and surface a previously skipped candidate without re-enumerating the original platform.
**Platform Integration Gate:** Knowledge Map, Claims, relationships and user corrections preserve source/revision provenance, model/task provenance, freshness, project scope, validated structured output, staleness behaviour, auditability.

## RUNG 6 — Canonical Works & Source Resolver

**Mission:** stop treating URLs as the identity of knowledge. **Do not scrape a platform merely because it exposes a Work. Resolve the Work.** (Spotify, Apple Podcasts, Amazon, Audible, Google Books, academic indexes, magazine/news apps, library catalogs.)
**Model:** WORK → identifiers → manifestations → SOURCE. Manifestation relationships EXACT / AUTHORIZED_REPRINT / EXCERPT / DERIVED / RELATED.
**Acquisition ladder:** Tier 0 Global Library · 1 open structured source · 2 authoritative alternative manifestation · 3 trusted index/archive · 4 targeted web resolution · 5 user-authorized browser access · 6 user-supplied artifact · 7 metadata-only preservation. No DRM circumvention.
**Work states:** IDENTIFIED · RESOLVING · ACQUIRED_FULL · ACQUIRED_PARTIAL · USER_ACCESS_REQUIRED · USER_FILE_REQUIRED · METADATA_ONLY · NOT_FOUND · RECHECK_LATER.
**Podcasts:** episode identity → Global Library → RSS → official transcript → official media → official video → best manifestation. **Books:** Work, edition, author, publisher, ISBNs, legitimate availability; related material never substitutes for the requested book. **Periodicals:** PUBLICATION → ISSUE → ARTICLE; full-issue extraction without duplicating the asset. **Interviews:** resolve across titles, interviewer, interviewee, publication, date, episode/issue, known quotes; preserve speaker attribution.
**Feature Gate:** a closed catalog URL resolves to the best legitimate manifestation with full/partial/unavailable states represented honestly.
**Platform Integration Gate:** resolved manifestations pass global identity, use durable acquisition jobs, retain provenance, participate in revisions/staleness, respect rights/access status, use standard cost accounting, enter standard retrieval/evidence paths.

## RUNG 7 — Deep & Community Source Discovery

**Mission:** capture tribal knowledge, real-world experience, mistakes, hidden costs, workarounds, limitations, specialist disagreements, failure patterns. Communities are collections: explore, don't ingest the homepage. Preserve thread structure (post / comment / reply / correction). Favour relevance, firsthand experience, specificity, numbers, substantive explanation, corroboration, corrections, cited evidence, professional context; downweight jokes, spam, duplication, unsupported claims, tangents, trolling. **Popularity is not truth** — separate relevance, substance, engagement, corroboration, specificity, evidence support, experience, disagreement. Cross-thread synthesis: frequently reported / mixed / strong disagreement / rare but serious / firsthand examples, always cited. A community claim ("The IRS requires X") becomes lead + regulatory Claim + primary-source verification required.
**Feature Gate:** a large community yields a concise high-signal set of discussions and structured experiential findings without confusing popularity with authority.
**Platform Integration Gate:** standard identity, durable jobs, revisions/staleness, provenance, evidence validation, project-relative authority, cost accounting. No shadow corpus.

## RUNG 8 — Multimodal Evidence

**Mission:** evidence from images, screenshots, scans, charts, maps, diagrams, tables, figures, slides, PDF imagery, SVGs. Visual evidence object preserves original asset, source revision, location, visible text, caption, structured observations, visual interpretation, chart/table extraction, citation locator ("Maintenance Manual · Page 43 · Figure 7 · Region …"). The derived description is not the citation; the original revision and location are. Cheap heuristics first; analyze only substantive visuals.
**Feature Gate:** a question whose answer exists only inside a visual object is answered with a precise citation to source/page/figure/region.
**Platform Integration Gate:** same lifecycle, revision model, provenance, retrieval, Claim relationships, staleness, durable jobs, usage accounting, validation as text.

## RUNG 9 — Recursive Research, Temporal Intelligence & Decision Readiness

**Mission:** let evidence reveal what to research next while research stays bounded, explainable, current, cost-conscious, decision-focused.
**Recursive triggers:** new terminology, citation, bibliography, weak Claim, contradiction, missing perspective, planner dependency, temporal staleness, user change.
**Citation & Reference Graph:** SOURCE REVISION → REFERENCE EXTRACTION → WORK/ENTITY RESOLUTION → GLOBAL LIBRARY CHECK → PROJECT RELEVANCE → DISCOVERY CANDIDATE; backward and forward citation discovery.
**Temporal intelligence:** structured temporal fields; STATIC / SLOW_CHANGING / PERIODIC / FAST_CHANGING; a contradiction may be OLD RULE vs NEW RULE.
**Research Mission priority:** decision impact, uncertainty, evidence weakness, expected information gain, freshness urgency, dependency count, cost, effort. **Bounded Research Missions** with reason, target, scope, cost, and Research / Dismiss / Lower priority actions. **Sufficiency states** UNRESEARCHED → DECISION_READY. **Stop conditions:** target acquired, Claim established, primary authority obtained, corroboration adequate, contradictions explained, evidence current, additional sources redundant, low information gain, low decision impact, budget/value threshold, user dismissed. Recursive Discover treats the Candidate Index as a first-class tier before external research.
**Feature Gates:** one strong source can introduce an unknown concept, create a justified Research Mission, locate stronger evidence, update Claims, coverage and readiness, explain lineage, and stop when further research lacks value; **and** a gap discovered weeks after a scan can reactivate a skipped candidate, acquire it through the normal lifecycle, and use its validated evidence.
**Platform Integration Gate:** durable jobs/dependencies, Global Library first, duplicate prevention, budget controls, cost estimates, provenance, revisions/staleness, validated evidence state, audit trail, bounded stopping rules.

---

# 8. Finished Discover experience

Discover leads with **research state**, not URLs: Research Coverage (Strong 7 · Developing 4 · Weak 3 · Unresearched 5; weak Claims, missing areas, stale evidence, contradictions, missing perspectives/evidence classes); Recommended Research (Missions with "why"); Evidence Already in Global Library (relevance, authority, role, freshness, origin; Review / Add to project); New Evidence Found (primary/authoritative · expert · community/experiential · current market · historical); Works Being Resolved (exact Work identified, full text unavailable, preview available, related sources; Add preview / Upload copy / Add related / Find another copy); New Discoveries (potentially important concepts, each explained); Claims Requiring Attention (evidence class present vs missing; Verify); Time-sensitive state. Discover must be allowed to conclude that the library already suffices and recommend attaching existing sources; it should not invent work to appear productive.

# 9. Universal Add experience

"Add something to research — paste a URL, upload a file, or describe what you're looking for." The user never needs to understand ingestion modules, dedupe, collections, resolvers, crawling, enumeration, browser fallback, Work identity, media extraction, OCR. Review remains the cost/control boundary whenever one input expands into many candidates.

# 10. Data model direction

Additive migrations; implement the minimum per rung. Possible concepts: global identity (`identity_scheme`, `external_id`, `canonical_url`, `content_fingerprint`); Source Profiles; `works`, `work_identifiers`, `work_manifestations`, `source_relations`; `project_claims`, `claim_evidence`; `project_knowledge_nodes`, `project_evidence_targets`, `research_missions`; structured temporal fields. Do not create these names mechanically if hardened structures provide a cleaner extension point.

# 11. Default discovery and acquisition funnel

1. Current Project Evidence · 2. Global Library · 3. Discovery Candidate Index · 4. Existing citations/references · 5. Structured/open indexes · 6. Authoritative originals · 7. Trusted archives · 8. Targeted external discovery · 9. User-authorized browser access · 10. User-supplied artifact · 11. Metadata-only Work preservation. At every stage: **do we already know where sufficient evidence may exist?**

# 12. Future monitoring compatibility

DISCOVER → EVIDENCE → TEMPORAL STATE → MONITOR → CHANGE → CLAIM REASSESSMENT → PLANNER / TASK UPDATE. Not built here unless required, but all time-sensitive architecture supports it.

# 13. Safety, access, rights, provenance

No DRM circumvention (legitimate open copies, publisher/author copies, institutional repositories, libraries, authorized archives, user uploads, legitimate browser access; preserve metadata otherwise). Source prompt injection: all source material is untrusted evidence and cannot alter system instructions, project policy, tool permissions, security boundaries, credential handling, acquisition rules. Fail closed for evidence: an unvalidated/unlocated/unattributed source may remain a Discovery Candidate, never a trusted conclusion.

# 14. Research auditability

For important artifacts: what triggered this, which project state, which source/revision, which locator, which model/task, validated?, stale?, superseded?, what was searched, rejected, why selected, reused or newly acquired, cost, what changed after acquisition. Research Intelligence must not become an opaque agent.

# 15. Evaluation harness

Primary Golden Project: *"I am thinking about buying an airplane and using it partly for business. Help me understand whether this makes sense."* Start with almost no evidence; a mature system progressively discovers FAA requirements, tax, financing, insurance, documentation, maintenance, reserves, depreciation, recapture, business-use requirements, ownership structure, operational constraints, downtime, resale, market conditions, counterarguments, owner experience, manuals, books, expert material, and distinguishes which questions need primary authority / expert interpretation / experiential / market evidence.
**Measure:** discovery precision, critical-source recall, unknown-unknown recall, primary-source resolution, source identity accuracy, Global Library reuse, citation correctness, revision correctness, evidence independence, temporal correctness, community handling, research efficiency (cost to Decision Ready), mission noise, prompt-injection resilience, platform integration, plus Candidate Recall tests (preservation, gap recovery, gap-specific reranking, explicit dismissal, global candidate dedupe, candidate-to-source promotion, evidence isolation, cost improvement).

# 16. Feature experiments and adoption

For major heuristics, models, ranking strategies, extraction approaches, UX changes: define expected improvement and baseline, test on representative projects, measure usefulness, regressions, cost; remove or disable if it loses. Applies especially to rerankers, prefilters, autonomous recursion, community ranking, Source Profiles, Claim extraction, entity resolution, multimodal interpretation, research prioritization. Negative findings are evidence.

# 17. Engineering execution protocol

Before every rung: read CLAUDE.md; inspect architecture, schema, hardening/release docs; run Doctor/Health and release checks; identify existing primitives; define the smallest additive architecture; name the 0.24.0 invariants touched. Per rung: architecture → affected files → migrations → durable job behaviour → provenance → revision/staleness → Global Library → cost → validation → backend state first → UI after → test failure/retry/restart, dedupe, revision/staleness, provenance, budget → full tests → Doctor/Health → release-check → version bump → independent commit → document (what changed, invariants, states, schema, jobs, provenance, staleness, cost, tests, measured usefulness, limitations, experiments rejected, what the next rung depends on). No unrelated cleanup; never replace hardened infrastructure with a parallel implementation.

# 18. Recurring rung exit test

Feature value · Global Library reuse · source lifecycle · deduplication · provenance · revision integrity · staleness · durable work · cost · validation (speculative vs validated) · project boundary · safety (untrusted content) · evaluation (measured usefulness) · platform health (Doctor, Health, tests, release-check green). Any platform-critical "no" means the rung is not complete.

# 19. Gate matrix

| Gate | Primary acceptance test |
|---|---|
| G1 Global Identity | One underlying source → one global acquisition, many project relationships |
| G2 Universal Input | Arbitrary input classified and routed into the standard lifecycle |
| G3 Exploration | Large collections → concise ranked Review sets, not crawls; skipped candidates retained |
| G4 Library Intelligence | Previously acquired evidence reused without project contamination |
| G5 Research Intelligence | Vague projects reveal Claims, gaps, evidence needs, unknown unknowns; gaps recall skipped candidates |
| G6 Source Resolver | Works resolve independently of closed catalog URLs |
| G7 Community Intelligence | Tribal knowledge captured without being confused with authority |
| G8 Multimodal | Visual information becomes locatable, citable evidence |
| G9 Recursive Research | New evidence triggers bounded, prioritized follow-up and reaches Decision Ready |

Every gate also requires the recurring Platform Integration Gate.

# 20. Dependency order

`0.24.0 → G1 → G2 → G3 → G4 → G5 → G6 → G7 → G8 → G9 → Decision Readiness / future Tracker`. Do not skip to autonomous or recursive Discover: without the earlier layers recursion amplifies duplication, cost, weak evidence, stale assumptions, project contamination, provenance failures, unbounded work.

# 21. User-facing progression

1 Don't make me pay twice · 2 Understand what I gave you · 3 Find the useful material inside it · 4 Use what I already own first · 5 Tell me what I don't know · 6 Find the actual Work, not merely a URL · 7 Find what people learned in the real world · 8 Understand evidence even when it is visual · 9 Follow the evidence into the next important unknown · Final: know when we have enough evidence to act, and what needs to be watched afterward.

---

# ADDITION — Discovery Candidate Memory & Gap Recall

**Principle: Discover once, remember cheaply, acquire only when needed.** Neuro Search preserves lightweight knowledge about credible candidate sources it has encountered even when they were not ingested.

```text
PROJECT EVIDENCE → GLOBAL LIBRARY (fully acquired) → DISCOVERY CANDIDATE INDEX (seen / identified / not acquired) → EXTERNAL WORLD
```

The Candidate Index is **not evidence**: candidate metadata cannot support a Claim, be cited, influence factual answers, satisfy an Evidence Target, or make an area Decision Ready. It only says "we have previously encountered something that may contain useful evidence".

**Why:** enumeration (channels, playlists, YouTube search, websites, sitemaps, podcast feeds, communities, repositories, Discover, Work resolution, periodical issues) does valuable work before ingestion. Enumerate 400, select 25, and the other 375 must not vanish — a video scored 41 against the original brief may score 97 against a later Evidence Target ("Why New Baron Owners Can't Get Insurance").

**Lifecycle:** ENUMERATE → IDENTIFY/CANONICALIZE → GLOBAL LIBRARY CHECK → (acquired → GLOBAL SOURCE | not acquired → DISCOVERY CANDIDATE → metadata indexed → relevance ranking → selected → acquire | skipped → KEEP CANDIDATE). Skipped ≠ forgotten.

**Candidate states (intent matters):** AVAILABLE · SKIPPED_LOW_RELEVANCE · SKIPPED_LIMIT · SKIPPED_COST · USER_DISMISSED · DUPLICATE · UNAVAILABLE · STALE_METADATA · ACQUIRED. "Only the best 20" is a strong future candidate; "do not use this creator" should not resurface. **User intent outranks automated gap recall.**

**Candidate metadata (cheap):** platform, native ID, canonical URL, title, description/snippet, creator/channel, publication date, duration, engagement, collection/discovery origin, thumbnail ref, content type, language, first/last_seen_at, original project, original mission, original relevance score and reason, skip/dismiss reason, availability state; where economical: metadata search text, metadata embedding, topic/entity hints. Never transcribe or run source-level AI merely to populate the index.

**Global candidate identity:** one global candidate per native identity across channel / playlist / search / Discover / project; project-specific relevance, reasons and dismissals stay separate. One project's dismissal or score is never universal truth.

**Gap Recall hierarchy:** EVIDENCE TARGET → 1 current project evidence → 2 Global Library → 3 Discovery Candidate Index → 4 existing citations/references → 5 external discovery. **Gap-specific reranking:** never reuse the original project score; rerank likely candidates against the specific Claim / Evidence Target / gap / planner dependency / source-class / freshness requirement. Gap-driven batch retrieval uses the Review pattern ("17 possibly relevant · 3 in Library · 14 seen not acquired · Recommended 5 · [Review 5] [Acquire best 3] [Search externally too]").

**Searchable by** Knowledge Map topics, Claims, Evidence Targets, contradictions, missing perspectives, Planner assumptions, temporal refresh needs. Recursive research consumes known candidates before expanding the search universe.

**Candidate freshness:** `first_seen_at`, `last_seen_at`, `last_verified_at`, `availability_state`, `metadata_revision`; refresh only when highly relevant to an active gap, on acquisition request, when old enough to matter, or for fast-changing classes. Acquisition verifies identity/availability before expensive processing.

**Candidate provenance:** how encountered (channel enumeration + collection + date; Discover mission; referenced by source/bibliography entry) so the system can explain "we already encountered this video while scanning a channel for your project, but it was outside the original cutoff; it now appears highly relevant to the insurance gap".

**Economics:** enumeration metadata cheap → candidate index cheap → gap matching cheap → selective ingestion expensive. Start with FTS, metadata fields, title/description similarity, entity/topic overlap; adopt embeddings or model reranking only when measured to help.

**Platform Integration Gate for Candidate Memory:** identity (canonical/native), global reuse (no duplicate objects per encounter), project boundaries (metadata never becomes evidence automatically), provenance, user intent preserved, freshness revalidation when actionable, durable work for large indexing/reranking, cost (retention cheap, acquisition deferred), evidence validation (a Candidate never supports a Claim until acquired, processed and validated), revision compatibility (an acquired Candidate resolves to the canonical global Source, never parallel evidence state).

**Product principle:** WHAT WE OWN (Global Library) · WHAT WE HAVE SEEN (Discovery Candidate Index) · WHAT WE STILL NEED TO FIND (External Discovery). First ask whether we own the evidence, then whether we have seen where it might be, only then search the outside world again.

---

# FINAL PRODUCT PRINCIPLE

> **Neuro Search owns a reusable, revision-aware evidence library. Projects are controlled research environments. Claims represent what the project currently believes or needs to establish. Discover determines what the project should learn next and finds the strongest available evidence to learn it from. Planner turns sufficiently supported project state into action. Future Tracker functionality monitors the pieces of reality that may change afterward.**

The north star: **Can a reasonably intelligent user begin a difficult project with little domain knowledge and have Neuro Search progressively reveal the questions, terminology, authorities, Claims, evidence, books, manuals, data, communities, contradictions, historical changes, deadlines, risks, and blind spots that a competent expert would know to investigate, while reusing prior research, preserving provenance and temporal validity, controlling cost, resisting bad evidence, learning from the user, and knowing when the evidence is strong enough to act?** And throughout: **new intelligence must inherit the guarantees of the hardened platform rather than bypass them.**

---

---

# ADDENDUM — Chat as the Research Orchestration, Novelty & Gap Intelligence Layer

**Net change:** Chat becomes the primary conversational orchestration layer for research, optimising not only for correct consensus but for **useful surprise**. It operates the systems the mission already defines (Global Library, Candidate Index, authority, Claims/Evidence, Knowledge Map, Gap Analysis, temporal intelligence, provenance, recursive Discover, cost, Planner) — it must not duplicate any of them. New explicit behaviour: **Neuro Search actively seeks relevant novelty, minority viewpoints, contradictions, edge cases, emerging practices, hidden opportunities and uncommon ideas that could materially improve the user's understanding or plan — surfaced without being confused with truth.**

## 1–3. Chat as the research command layer
`USER TURN → INTENT (answer · investigate · change project state · make/revisit decision · change evidence scope · research a gap · investigate an outlier · update plan · create monitoring need) → PROJECT STATE → RESEARCH STATE (Claims, Evidence, Gaps, Research Tensions, Knowledge Map, Freshness) → EVIDENCE STRATEGY → ANSWER / ACTION / PROPOSAL`. Every turn is a potential project event: "This syllabus overrides YouTube advice", "Ignore the Aerostar", "The deadline moved to October 12", "I don't trust this creator for regulatory questions", "I completed Phase 1" are eligible to become structured state. Distinguish **temporary conversational instruction** (this turn) from **durable project state** (changes future behaviour). Infer answer intent ("What does my evidence say about seller financing?") vs research instruction ("I don't think we have enough evidence…" → assess the gap, propose the cheapest credible path) vs broad delegation ("Figure this out" → inspect evidence → Claims/Knowledge Map → weakness → Global Library → Candidate Index → references → external). No separate Research Mode unless UX testing shows it helps.

## 4. Mandatory evidence escalation order
`1 CURRENT PROJECT EVIDENCE → 2 GLOBAL LIBRARY → 3 DISCOVERY CANDIDATE INDEX → 4 EXISTING CITATIONS/REFERENCES → 5 EXTERNAL DISCOVERY`, for gaps from Chat, Claims, Planner, contradictions, stale evidence, Research Tensions, Knowledge Map, user requests. ("Three videos previously skipped from a Baron channel now appear directly relevant — evaluate those before searching YouTube again.")

## 5. Chat Gap Engine
Classify *why* something is weak: `MISSING_EVIDENCE · INSUFFICIENT_AUTHORITY · PRIMARY_SOURCE_MISSING · CONFLICTING_EVIDENCE · STALE_EVIDENCE · MISSING_QUANTITATIVE_DATA · MISSING_PERSPECTIVE · UNANSWERED_DEPENDENCY · USER_DECISION_REQUIRED · CORROBORATION_GAP`. A gap is Gap + Why + Need, and can trigger evidence recovery through the escalation order — not just a warning.

## 6–9. Useful surprise as a first-class objective
Every serious pass asks (1) what is the strongest supported understanding and (2) what credible information might we otherwise miss: outliers, edge cases, hidden opportunities, contradictions, emerging ideas, rare-but-material risks, beginner blind spots. **Novelty is project-relative** — meaningfully new relative to what this project knows (distance from existing Claims, rarity across project evidence, relevance to mission, impact if true): "appears only once in your 83-source corpus, but directly affects a stated constraint". A high-value outlier becomes a **Novel Insight** (why surfaced, evidence, authority, corroboration, freshness, impact if true, risk if wrong, status: needs corroboration; actions Investigate further / Save as hypothesis / Accept as Finding / Dismiss), not an ordinary Finding. Evaluate **independent dimensions** — relevance, novelty, evidence, authority, corroboration, freshness, impact, risk — never one opaque score.

## 10–13. Research Tensions, Corroboration Gaps, resolution, false consensus
**Research Tension** = something important that deserves investigation even if it does not look like an unanswered question; types `NOVEL · CONTRADICTION · WEAK_CONSENSUS · STALE · EDGE_CASE · EMERGING · HIGH_IMPACT_OUTLIER`, carrying the dimensions above and a recommended investigation. Tensions feed the Gap Engine. A high-impact Novel Insight with thin support becomes a **CORROBORATION_GAP** whose mission is never "find confirming evidence" but "determine whether this unusual Claim is supported, contradicted, outdated, situational, or useful — seek independent evidence for AND against" through the escalation order (a prime use of skipped-candidate metadata). Resolution states: `CORROBORATED · PLAUSIBLE_BUT_THIN · SITUATIONAL · DISPUTED · SUPERSEDED · UNSUPPORTED · PROBABLY_WRONG`; investigation history is preserved, failed hypotheses are not deleted. **False consensus:** 20 videos repeating one blog post are one lineage — account for independence, shared citations, repeated wording, syndication, upstream sources, creator relationships, evidence actually supplied, primary vs derivative; independence is Claim- and evidence-class-relative ("fifteen independent owner reports" can be real experiential corroboration).

## 14–16. Domain-sensitive, Claim-level freshness
No universal cutoff: credit-card promotions / tax / SBA rules extremely-very high; software, aviation regulation, pricing, market high; tactics, technique medium; case studies, interviews, theory low. Evaluate the freshness requirement of the **Claim**, not the age of the Source; separate idea freshness from fact freshness (a 2018 episode's modernisation idea survives; its tax rule needs verification). Freshness warnings are actionable ("relies on 2022 tax guidance… [Verify current rule]") and connect to the Gap Engine.

## 17–22. Surprise-oriented queries, Research-this-further, cost, scope controls
Support "What am I missing?", "Show me the non-obvious stuff", "What did only one or two sources mention?", "What would an expert notice that a beginner wouldn't?", "Strongest credible contrarian view?", "Where does conventional advice break down?", "What haven't we investigated because it seemed irrelevant earlier?" — these query Claims, rarity, Novel Insights, Tensions, contradictions, the Candidate Index, authority and impact, not plain semantic retrieval. **Research this further** after an uncertain answer: extract weak Claims → gaps/tensions → project → library → candidates → references → external → cost → proposed operation ("1 Global Library source may help · 3 skipped candidates relevant · external search probably unnecessary · est. $0.06"). Cost is a research constraint: lowest-cost credible path to sufficient evidence, exposing owned / previously discovered / new acquisition / estimated cost / cheaper alternative. Per-turn evidence controls ("only primary sources", "exclude Reddit", "only evidence newer than January 2026", "consensus first, then outliers") are temporary unless saved as steering; a later scope selector (this project · selected sources · current source · Global Library · project + library · project + web · primary only) and research emphasis (balanced · consensus · non-obvious · contrarian · current only) configure the same evidence system, never separate engines. **Open this source in Chat**: summarise, what the author believes, what evidence they supply, what to be sceptical about, which Claims are novel to the project, what it mentions that nobody else does, what Tensions it creates.

## 23–27. Speaker identity, evidence-explained confidence, decisions, recommendation provenance, citation inspection
Preserve speaker identity only where established (diarisation, structure, metadata, labels). Confidence is explained through evidence — `STRONG` (three independent authoritative sources agree) · `MODERATE` (two credible secondary, primary missing) · `WEAK` (one practitioner) · `NOVEL / UNVERIFIED` · `CONFLICTED` · `STALE` — never "82% confident". Decisions use durable criteria (mission fit, cost, risk, evidence, novel considerations); "Forget option B" becomes a recorded rejection future recommendations respect. Recommendations trace RECOMMENDATION → Claims (consensus, tensions, risks) → Evidence → Source revision → locator, and say when a Novel Insight materially affected them. Citation inspection shows quote, context, speaker, authority, evidence class, dates, freshness, Claim relationship, corroboration, contradiction, novelty status, revision, jump to original — a view of existing provenance.

## 28–34. Branches, promotion, proactive behaviour, Chat-aware Discover, status, Planner, monitoring
Conversation branches explore without contaminating accepted state (merge selected Claims/Findings/Insights/Tensions/decisions/facts/constraints/questions/sources/plan proposals; never raw assumptions). Promote outputs to durable objects (Finding, Fact, Decision, Constraint, Requirement, Novel Insight, Research Tension, Reject Option, Question, Gap, Investigate, Discover, Task, Watch, Plan) — Chat is an interface, never a second hidden source of truth. Controlled proactivity: notice contradictions of approved Claims, ideas no other source mentions, uncorroborated high-impact insights, stale evidence, plan-assumption impacts, closable gaps — **propose** the transition, never silently rewrite accepted state. Discover is reachable from conversation ("1 library source · 3 skipped candidates · 1 unresolved reference · 2 possible external sources"). Status questions ("Where are we? What's weak? What's stale? Biggest contradictions? Most important Tensions? Ready to act?") query structured research state. Chat ↔ Planner is two-way (plan changes stay proposals). Watches ("tell me if this SBA rule changes") go through the standard Tracker/monitoring architecture.

## 35. Chat integration track (interleaved with G1–G9; novelty enters early so the system never solidifies around consensus-first retrieval)

| Track | Adds | Exit test |
|---|---|---|
| **C1 Project Memory & Steering** | constraints, requirements, decisions, rejected options, authority preferences, deadlines, durable conversational state | material user statements change structured project behaviour |
| **C2 Source Authority + Temporal Relevance** | project-relative authority, per-turn scope, primary-source rules, domain-sensitive freshness, stale warnings, idea-vs-fact freshness | Chat treats evidence age differently for a tax Claim than for a strategic idea |
| **C3 Novelty, Outliers & Research Tensions** | Novel Insights, project-relative novelty, outlier/edge-case/emerging detection, false-consensus signals, Tension objects | a high-impact idea from one credible source is surfaced without being presented as established |
| **C4 Gap & Corroboration Engine** | structured Gap classes, Corroboration Gaps, for-and-against research, resolution states, contradiction handling | an outlier triggers balanced corroboration research and resolves to a state |
| **C5 Library-Aware Research Agent** | project → library → candidates → references → external | a skipped candidate is recovered because a new Claim/Gap/Tension makes it relevant |
| **C6 Claims & Evidence Graph** | normalised Claims, relationships, independence, confidence explanations, consensus vs derivative, provenance chains | Chat distinguishes repetition from independent corroboration |
| **C7 Chat Operations + Planner** | research actions, ingestion proposals, compare, primary-source search, Research This Further, state changes, Planner proposals, cost-aware strategy | the research engine is operated conversationally with no parallel backend |
| **C8 Monitoring & Temporal Intelligence** | deadlines, refresh requirements, change detection, watches, stale-Claim reassessment | a time-sensitive Claim triggers revalidation through standard monitoring |
| **C9 UX power features** | branches, selective merge, source-specific Chat, scope selector, research emphasis, citation drawer, one-click promotion, status, Novel Insight inspection | UX exposes existing intelligence without alternative state models |

## 36. Additional evaluation criteria
Novelty recall (known high-value information present in only one or two sources), novelty precision (no trivial rarities), outlier safety (one-source ideas stay distinguishable), corroboration neutrality (for and against), false-consensus detection, domain freshness, Claim-level freshness, impact prioritisation, candidate reactivation, noise rate. Novelty earns adoption through measured usefulness like every other experiment.

## 37. Recurring platform rules (added to the Platform Integration Gate)
> **Chat must orchestrate the existing hardened source, retrieval, Discover, Candidate Index, Claim/Evidence, project-state, provenance, revision/staleness, durable-job, cost, temporal and planning systems. Novelty detection and Research Tensions extend those systems rather than create a parallel evidence model.**

> **Neuro Search must not optimise exclusively for consensus. Retrieval and research synthesis must preserve the ability to surface high-impact credible novelty, outliers, contradictions, edge cases and emerging ideas, while maintaining explicit evidentiary separation between an interesting hypothesis and a validated conclusion.**

**Conceptual model:** CHAT (conversational command layer) → PROJECT STATE (decisions, constraints, preferences, deadlines, authority rules) · RESEARCH STATE (Claims, Evidence, Gaps, Tensions, Novel Insights, Freshness, Readiness) · ACTION (search, acquire, Discover, compare, verify, plan, monitor) → USER RESPONSE. Chat is the interface through which the user interrogates, steers and operates the research intelligence — and that intelligence answers not only "what does most of my evidence say?" but **"what important thing might I otherwise miss, how trustworthy is it, and is it worth investigating before I act?"**

**Already in place (0.24.1):** `search_library` / `list_sources` / `set_source_priority` tools, library inventory in the state block, project-relative priority sources with reserved excerpt slots, follow-up grounding, in-chat attachments — the first pieces of C1/C2 and the tool surface C5–C7 build on.

# Rung log

*(Filled in as each rung ships: version, commit, what changed, invariants, schema, jobs, provenance, staleness, cost, tests, measured usefulness, limitations, experiments rejected, dependencies for the next rung.)*
