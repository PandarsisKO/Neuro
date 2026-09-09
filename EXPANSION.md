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
**Feature Gate:** a root website, repository, community, or Work identity no longer falls through to naive webpage ingestion. **A standalone screenshot can enter Neuro Search as a first-class Source, proceed through the standard source lifecycle, and become searchable project evidence** (see the Image addendum).
**Platform Integration Gate:** every resulting source still enters the canonical lifecycle; no type bypasses global dedupe, durable jobs, provenance, revisions/staleness, cost, validation — for images explicitly: image source identity, global reuse, provenance, durable processing, revision compatibility, cost accounting, evidence validation, project boundary.

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

## RUNG 8 — Image, Screenshot & Multimodal Evidence

**Mission:** make all visually encoded research information readable, structured, retrievable, comparable, and citable, whether it originates as a standalone screenshot, photograph, scan, chart, diagram, slide, webpage image, or figure embedded inside another document. Images and screenshots are first-class research sources, not attachments that merely receive OCR or descriptions. Visual evidence object preserves original asset, source revision, visual regions, visible text, structured fields, tables, chart interpretation, visual observations, entities, temporal information, citation locator ("Screenshot 4 · Financial summary" / `source_id, revision_id, image_id, region_id, bounding_box`). The derived description is not the citation; the original revision and region are. Cheap heuristics first; analyze only substantive visuals.
**Must explicitly support:** standalone image ingestion · screenshot ingestion · visual text extraction · structured field extraction · table reconstruction · chart understanding (exact vs estimated values, never silently conflated) · visual region citations · image collections · visual deduplication · image comparison · temporal extraction · visual-to-project-state promotion · visual references feeding Discover · visual evidence feeding Claims · visual evidence feeding Novel Insights. Field-specific confidence; never hallucinate illegible values. Layers stay separate: original image → extracted observation → normalized data → claim/interpretation, each with provenance to the layer above.
**Feature Gate (all must pass):** screenshot text retrievable from another Chat · business-listing screenshot yields asking price / revenue / cash flow fields · table screenshot yields usable row/column data · chart explained with exact-vs-estimated distinguished · a fact answerable only by the screenshot is cited to screenshot/region · information persists outside the original conversation · two dashboard versions → meaningful changes identified · an expiration date becomes structured temporal information · a screenshot referencing a document not in the project proposes finding the Work.
**Platform Integration Gate:** Universal Resource Input, Global Source Identity, Global Library reuse, standard Source lifecycle, durable jobs, provenance, revisions, staleness, structured outputs, validation, retrieval, Claims/Evidence, Knowledge Map, Novel Insights/Research Tensions, Gap Engine, Discover, Planner, Temporal Intelligence, cost accounting, Health/release gates. **No standalone vision silo** — no separate "image memory", no Chat-only vision path that loses provenance.

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
| **C0 Portable Answers & Evidence** (baseline, ships before/alongside any Chat track) | one-click Copy · Share on every assistant message: Copy response / + sources / plain text / Markdown / shareable version; human-readable citations with original URLs and deep locators (`&t=` timestamps, PDF pages, web sections, sheet refs); evidence-status warnings (outlier, weak evidence, freshness, conflicts, gaps, current-vs-historical) survive copying; share-length variants (concise, text-message, email, executive summary) generated from the completed answer + its evidence, never a new research pass; "Copied with 6 sources" confirmation | a pasted answer in iMessage/email/Slack/another AI carries every source with a working deep link and no caution stripped |
| **C9 UX power features** | branches, selective merge, source-specific Chat, scope selector, research emphasis, citation drawer, one-click promotion, status, Novel Insight inspection | UX exposes existing intelligence without alternative state models |

## 35a. Portable Answers and Evidence (Kyle, 2026-09-08)

> **Portable Answers and Evidence:** Every Chat response must be exportable outside Neuro Search with one click. Users must be able to copy the complete response together with human-readable source citations, original URLs, timestamps, document pages/sections, and relevant evidence-status warnings. Chat should additionally support share-optimized plain-text versions suitable for text messages and email without requiring a new research pass or losing provenance.

Every assistant message: `Copy · Share · 👍 · 👎 · ⋯`, no text selection. **Copy response + sources** is the most important option: in-app `[n]` citations become a numbered *Sources* list with deep links — `Mike Smith Interview, 24:17 — https://youtube.com/watch?v=…&t=1457`, `SBA SOP 50 10 8, p. 112`, `IRS Small Business Guidance, §6` — never a bare title. **Copy shareable version** rewrites internal UI language ("Based on Source [3] and Finding #17…" → "Based on the SBA guidance and two acquisition-industry sources…") and keeps the detailed list at the bottom. **Share ▾** (full / concise / text-message / email / executive summary) is generated from the completed answer and its evidence, not a new research pass; the text-message version keeps `Sources: SBA SOP p. 112; Smith interview 24:17; XYZ Lending guide §4`. Special research states (potential outlier + evidence status, freshness warnings, conflicting sources, weak evidence, novel insights, unresolved gaps, current-vs-historical) must survive every copy variant — copying must never turn a hypothesis into a fact. Copy confirms briefly: "Copied with 6 sources".

## 36. Additional evaluation criteria
Novelty recall (known high-value information present in only one or two sources), novelty precision (no trivial rarities), outlier safety (one-source ideas stay distinguishable), corroboration neutrality (for and against), false-consensus detection, domain freshness, Claim-level freshness, impact prioritisation, candidate reactivation, noise rate. Novelty earns adoption through measured usefulness like every other experiment.

## 37. Recurring platform rules (added to the Platform Integration Gate)
> **Chat must orchestrate the existing hardened source, retrieval, Discover, Candidate Index, Claim/Evidence, project-state, provenance, revision/staleness, durable-job, cost, temporal and planning systems. Novelty detection and Research Tensions extend those systems rather than create a parallel evidence model.**

> **Neuro Search must not optimise exclusively for consensus. Retrieval and research synthesis must preserve the ability to surface high-impact credible novelty, outliers, contradictions, edge cases and emerging ideas, while maintaining explicit evidentiary separation between an interesting hypothesis and a validated conclusion.**

**Conceptual model:** CHAT (conversational command layer) → PROJECT STATE (decisions, constraints, preferences, deadlines, authority rules) · RESEARCH STATE (Claims, Evidence, Gaps, Tensions, Novel Insights, Freshness, Readiness) · ACTION (search, acquire, Discover, compare, verify, plan, monitor) → USER RESPONSE. Chat is the interface through which the user interrogates, steers and operates the research intelligence — and that intelligence answers not only "what does most of my evidence say?" but **"what important thing might I otherwise miss, how trustworthy is it, and is it worth investigating before I act?"**

**Already in place (0.24.1):** `search_library` / `list_sources` / `set_source_priority` tools, library inventory in the state block, project-relative priority sources with reserved excerpt slots, follow-up grounding, in-chat attachments — the first pieces of C1/C2 and the tool surface C5–C7 build on.

# ADDENDUM — First-Class Image, Screenshot & Visual Data Ingestion

*Kyle's addendum (2026-09-08). A strengthening of Rung 2 and a major expansion of Rung 8 — not a new rung. It also feeds the Chat addendum, the Candidate Index, the Gap Engine, Novel Insights, Temporal Intelligence, and eventually the mobile workflow.*

## Critical clarification

Images and screenshots are first-class research sources, not attachments that merely receive OCR or descriptions. A user must be able to drag, paste, upload, or capture screenshots, photographs, charts, tables, dashboards, social-media posts, receipts, invoices, schedules, maps, diagrams, product specifications, forms, scanned documents, whiteboards, slides, app interfaces, and websites captured as images — and have Neuro Search extract the useful information into the same evidence system used for text, webpages, PDFs, transcripts, and documents. The core user expectation: **if I can see useful information in an image, Neuro Search should be able to read it, understand it, retrieve it later, and cite where it came from.**

## 1. Image is an explicit Universal Resource type

`IMAGE / SCREENSHOT → STANDARD SOURCE LIFECYCLE → VISUAL EXTRACTION → STRUCTURED EVIDENCE → RETRIEVAL / CLAIMS / CHAT / PLANNER`. Formats where practical: PNG, JPEG/JPG, HEIC, WEBP, TIFF, GIF (static frame). Entry points: upload, drag into Sources, paste from clipboard, paste directly into Chat, send through the browser/mobile workflow. A screenshot pasted into Chat should optionally become a real project Source rather than existing only inside one conversation turn.

## 2. Visual extraction is not OCR alone

Identify visible text, tables, numbers, labels, structured fields, charts, diagrams, UI elements, relationships, layout, objects, visual context. A business-listing screenshot must not be saved as "image showing a business listing"; it yields `asking_price = 2,000,000 USD`, `cash_flow = 325,000 USD`, `revenue = 1,100,000 USD`, `employees = 7`, `location = California` while the screenshot stays the original evidence.

## 3. "Extract data from image" as an explicit capability

Intents: read this screenshot · pull all the numbers out · turn this table into structured data · what does this chart show · add these specifications to the project · compare this with the other listing · save the deadlines shown · extract the prices · what changed between these two screenshots. Chat determines whether the user wants text extraction, structured data, visual interpretation, comparison, project ingestion, fact/claim extraction, or temporal event extraction.

## 4. Visual Evidence Object

Each meaningful image preserves: original image, visual regions, visible text, structured fields, tables, chart interpretation, visual observations, entities, temporal information, evidence locators. E.g. `Screenshot 12 / Region 1 type=header text="Accounting Practice for Sale" / Region 2 type=financial table fields={Asking Price, Revenue, Cash Flow} / Region 3 descriptive text / Region 4 chart`. Content is independently retrievable without losing the original visual context.

## 5. Region-level provenance

Locators more precise than "Screenshot 4": "Screenshot 4, upper-right table"; internally `source_id, revision_id, image_id, region_id, bounding_box (x1,y1,x2,y2)`. The user need not see coordinates; the UI highlights the cited region. Long-term citation: **$325,000 owner cash flow** — Screenshot 4 · Financial summary; clicking opens the screenshot and highlights the region containing `$325,000`.

## 6. Structured tables from screenshots

A table screenshot produces a structured table (row, column, header, value, unit, source region), not flattened OCR text — enabling comparison, calculations, export, spreadsheet conversion, filtering, trend analysis, Chat queries ("Compare the financials from the five businesses I screenshotted").

## 7. Chart understanding

Extract chart type, title, axis labels, units, legend, series, visible values, trend direction, major changes, outliers, annotations. Distinguish **directly readable data** (values visibly present) from **estimated visual data** (inferred from geometry). Never silently treat estimated values as exact: "Revenue appears to rise from approximately $1.2M to $1.7M" stays explicitly approximate.

## 8. Time-sensitive screenshots

Deadlines, promotions, dates, expiration notices, schedules, prices, appointment times, course assignments, flight information, application windows feed Temporal Intelligence. `Promotion: 5x points on groceries, ends December 31, 2026` → `type: promotion, benefit: 5x points, category: groceries, effective_until: 2026-12-31, source: screenshot, refresh_required: true`; Chat may propose "This screenshot contains an expiration date. Add it to the project's tracked deadlines?"

## 9. Screenshot → structured project state

Extractions are eligible for promotion into Fact, Claim, Constraint, Decision, Requirement, Deadline, Price, Metric, Finding, Research Gap, Entity, Plan input — under the existing control rule: **extraction does not automatically equal accepted project truth.** "Asking price: $2,000,000" may safely become extracted evidence; "this business is undervalued" is a derived Claim requiring reasoning and support.

## 10. Field-specific confidence

No single confidence for a whole screenshot: `Asking Price $2,000,000 high · Cash Flow $325,000 high · Employee Count 7? uncertain`. If text is illegible, cropped, obstructed, or ambiguous, say so. Do not hallucinate missing values.

## 11. Original and derived layers stay separate

`ORIGINAL IMAGE → EXTRACTED OBSERVATION → NORMALIZED DATA → CLAIM / INTERPRETATION` (pixels "$325,000" → visible text "$325,000" → `cash_flow_usd = 325000` → "cash flow is ~16.25% of asking price"); each layer retains provenance to the one above.

## 12. Image collections

Several screenshots often form one logical source (6 of a listing, 12 from a carousel, 8 of a report, 20 photographed pages). Allow grouping into a collection/logical document ("Business Listing — Smith CPA Practice: Screenshot 1…4"); detect sequential, overlapping, duplicate screenshots, pages of one document, carousel order where possible.

## 13. Screenshot deduplication

Cheap image identity where practical: exact file hash, perceptual hash, visual similarity, metadata similarity. Visually identical recompressed screenshots should not become independent evidence; a cropped screenshot may relate to a full one without being identical — preserve source relationships.

## 14. Comparative visual analysis

"What's different between these pricing screenshots?", "Compare these three listings", "What changed in this dashboard since last week?", "Which specifications differ?", "Has the promotion changed?" — structured extraction of revision A and B → differences. Screenshots of the same changing object may participate in revision/change tracking rather than being unrelated sources.

## 15. Global Library reuse

An image is a standard global Source: global identity, deduplication, project relationships, provenance, revisions, staleness, retrieval, Claims, cost accounting, durable jobs. **Do not create a separate "image memory" system.**

## 16. Screenshots in Chat

On paste, Chat asks (lightweight UX) or infers: use only in this conversation vs add to project research; where unambiguous, offer **Add screenshot to project**. Once added, its evidence is available to future Chats, Findings, Claims, Knowledge Map, Planner, Gap Engine, Discover — it does not disappear when the conversation ages.

## 17. Screenshot-focused Chat actions

Equivalents of `extract_image_text`, `extract_image_data`, `extract_table`, `analyze_chart`, `compare_images`, `save_image_to_project`, `create_fact_from_visual`, `create_deadline_from_visual`, `create_claim_from_visual`, `find_related_sources` (names follow the hardened architecture). Chat orchestrates the standard visual-source pipeline; no separate Chat-only vision implementation that loses provenance.

## 18. Image search within the project

"Find the screenshot where the business had $325k cash flow", "Which screenshot showed the expiration date?", "Find the chart with the 2027 projection", "Which image mentioned 90% SBA financing?" — retrieval through extracted text, structured fields, entities, captions, and visual descriptions.

## 19. Novelty and Gap Analysis include visual evidence

A screenshot stating "Seller will remain for 24 months" with no other source mentioning a two-year transition → Novel Insight (evidence: Screenshot 7; corroboration: none; impact: high) for the Gap Engine to investigate. Visual evidence must not sit outside the project's intelligence system.

## 20. Image-derived leads feed the Candidate Index

A screenshot may reveal a book, author, company, URL, product, regulation, person, citation, podcast, paper, document number ("See IRS Publication 946"): `VISUAL EVIDENCE → extract reference → resolve entity/work → check Global Library → Candidate Index → propose acquisition`. A screenshot triggers the same recursive research behaviour as text.

## 21. Mobile importance

See something useful → screenshot → send to Neuro Search → extract → save to project → continue researching. Minimize friction between camera/screenshot and durable project evidence; likely one of the highest-frequency ingestion workflows.

## 22. Privacy and image metadata

Do not depend on EXIF for evidence; avoid exposing unnecessary device/location metadata; preserve only metadata useful for research/provenance; treat uploaded screenshots as user-controlled source material. If EXIF is used for date/time provenance, distinguish it from visible evidence.

## 23–26. Gate changes

Recorded directly in Rung 2 (Feature Gate + Platform Integration Gate) and Rung 8 (renamed, updated mission, nine-part Feature Gate, Platform Integration Gate) above.

## 27. Image-specific evaluation criteria

Text extraction accuracy · numeric accuracy · structured-field accuracy (label/value pairing) · table reconstruction · chart fidelity (no invented exact values from unlabeled charts) · citation localization · visual hallucination rate · multi-image grouping · duplicate detection · temporal extraction · persistence (retrievable long after the original Chat) · recursive utility (visible references become leads).

## Updated product rules

> **If useful information is visible to the user, Neuro Search should treat it as potentially ingestible evidence regardless of whether the information is encoded as selectable text.**

> **Visual understanding must produce provenance-backed evidence, not merely an AI description of an image.**

`I SEE SOMETHING USEFUL → SCREENSHOT → NEURO SEARCH → READ IT · STRUCTURE IT · REMEMBER IT · CITE IT · COMPARE IT · RESEARCH FROM IT → PROJECT KNOWLEDGE`. A core ingestion capability, not an optional enhancement to PDFs.

# G5 LOCK — decisions and guardrails (Kyle, 2026-09-08)

**Decision 1 — Claim Intelligence is automatic but event-driven, debounced, batchable and lazy.** Zero-cost candidate Claims are created immediately from approved findings, recorded user facts/decisions and already-structured project analysis; they stay `PROPOSED` and cannot affect readiness merely because they were generated. Normalization/extraction (`claims.extract`) runs lazily and batched at boundaries: after a source-analysis batch completes, when Discover/Chat needs Claims, when enough unprocessed candidates accumulate, or before a Knowledge Map refresh — never one model call per new finding. Suggested/unapproved findings may yield candidate Claims for investigation but never accepted beliefs until evidence/state permits. Re-running the same source revision + extraction contract is idempotent with no duplicate spend. **G5 must remain useful with zero new Claim-extraction calls when existing structured data is sufficient.**

**Decision 2 — a single primary source can make a Claim Strong; independence does not always dominate.** Two sufficiency concepts: **Governing sufficiency** (does the evidence directly establish what the controlling source says?) and **Corroborative sufficiency** (do enough independent sources establish that a pattern, interpretation, experience, market condition or disputed conclusion is reliable?). Strength follows the evidence requirement of the Claim type, not source count:

| Claim type | One source can be Strong? |
|---|---|
| Current statute/regulation/SOP says X | Yes — if current, authentic, directly applicable, unambiguous |
| Contract/syllabus/manual says X | Yes — when that document is the governing authority |
| Historical person said X | Yes — with a reliable primary record |
| Expert interpretation is correct | Usually no |
| Industry practice is X | Usually no |
| Owners commonly experience X | No — independent experiential evidence |
| Market price/cost is X | Usually no — unless narrowly one specific quote/listing |
| Causal claim | Generally no — stronger corroboration |
| Novel/outlier tactic works | No — until corroborated |

**Strong is not Decision Ready.** Evidence strength, application to the project, and decision readiness are separate fields with a reason (e.g. SOP permits X under Y — STRONG; application to our transaction — DEVELOPING; NOT READY: we have not established that our structure satisfies Y).

**Guardrails.** (a) Claims carry qualifiers — jurisdiction, product/model, population, conditions, timeframe, source language — never normalize "some lenders may allow X when Y" into "lenders allow X"; similar Claims may legitimately stay separate. (b) User statements ≠ external Claims: "my maximum budget is $2M" is a project fact/constraint that needs no corroboration; "SBA lets me borrow $2M" is an external Claim needing evidence — the Project Context Model is not a pile of Claims. (c) Claim evidence freezes `source_id, revision_id, locator, relation, evidence excerpt/reference, task/model provenance, created_at` so a revision can stale exactly the affected Claims. (d) Before `CONTRADICTS`, test scope: different date, jurisdiction, product/version, factual conditions, primary rule vs practical experience, general rule vs exception. (e) Knowledge Map coverage ≠ source volume; it reflects the Claims/Evidence Targets that matter. (f) Every Evidence Target states explicit closure criteria ("one current directly applicable primary source, ambiguity resolved" vs "several independent experiences, disagreement characterized, outliers captured") — the foundation of G9 Research Sufficiency. (g) Candidate Recall reranks against the Evidence Target, not the whole project — a hard G5 gate. (h) Novelty/Research Tensions begin in G5 in the backend: `NOVEL · CONTRADICTION · WEAK_CONSENSUS · STALE · MISSING_PERSPECTIVE`, so the map is never consensus-only. (i) Suggestion-first: model-generated Claims, gaps, authority interpretations and map changes are proposed research state; deterministic evidence may compute status automatically, but explicit user decisions and accepted facts are never silently rewritten.

**Acceptance gate (frozen end-to-end test).** A vague project with a current primary source, several derivative secondaries, one credible outlier, one stale source and one relevant previously skipped Candidate. G5 must determine that: (1) the governing Claim is Strong from one primary source; (2) repeated derivative sources are not independent corroboration; (3) the outlier becomes a Research Tension / Corroboration Gap, not consensus; (4) the stale Claim is flagged by its domain-sensitive freshness requirement; (5) an Evidence Target searches Project → Global Library → Candidate Index → external; (6) the skipped Candidate is reranked against the new gap and resurfaced without network enumeration; (7) no library/candidate evidence enters the project until the boundary is crossed; (8) every Claim traces to exact source revision + locator; (9) the Knowledge Map explains *why* an area is Strong/Weak rather than counting sources; (10) all of it passes the hardened provenance, jobs, staleness, cost, validation, Health and release gates.

# G6 LOCK — Canonical Works & Source Resolver (Kyle, 2026-09-08)

**Model.** Work = intellectual/legal identity (global). Version/edition = a first-class part of identity whenever it changes what is authoritative (global). Manifestation = a particular obtainable representation of a version (global). Project association = relevance/use, never ownership of the Work, and never stored on the Work row (`project_works`). Hierarchy: work family (SBA SOP 50 10) → version (SOP 50 10 8, effective June 2026) → manifestation (official PDF, mirror, HTML copy, excerpt, OCR copy) → derivative (article/video explaining it) → project relevance (attached / relevant / targeted / dismissed).

**Relations** (source ↔ version, typed — `derivative` alone is too broad for independence): manifestation_of · reprint_of · translation_of · revision_of · excerpt_of · summary_of · quotes · derivative_of · cites · implements/interprets (guidance that applies a governing document).

**Resolver is conservative.** False negatives are cheaper than false canonicalization: ambiguous identity → an unresolved *possible* relationship, never a forced merge. Identity signals, ranked and frozen: (1) DOI / ISBN / ISSN / official document number / statute citation / SOP number; (2) exact normalized title + creator + edition/year; (3) publisher + title + date; (4) model-assisted semantic match; (5) **never auto-merge on title similarity alone for legal/regulatory/high-stakes material.** Outcomes: resolved & owned · resolved & candidate · **resolved identity, unresolved access** (we know exactly which SOP/book/paper it is but hold no usable manifestation) · unresolved identity — the last two are different states and both are represented. The resolver prefers owned / global-library manifestations before external acquisition.

**Independence by lineage (frozen).** Multiple manifestations of one Work are ONE evidentiary lineage unless they contain independently generated substantive analysis: official PDF + mirrored PDF = 1; podcast quoting the SOP + article quoting the same SOP = still one governing lineage; SOP + lender underwriting manual + practitioner dataset = potentially three. Claim independence is computed by lineage, not raw source count. **Stricter governing sufficiency:** a governing Claim is not fully verified merely because a derivative accurately quotes the rule when an obtainable primary manifestation exists — Chat can say "supported by three secondary sources, but the governing primary source has not yet been resolved."

**Freshness by version relationship** (never merely "a newer manifestation exists"): newer version discovered, differences unknown → needs_refresh · newer version explicitly supersedes → needs_refresh · newer version changes the relevant provision → stale · formatting/rehost only → no penalty · a historical Claim explicitly about the old version → age-insensitive in that context.

**Citations become obtainable targets.** A finding cites a Work not in the project → Work stub → Candidate → Evidence Target that names the *manifestation* needed ("Obtain the authoritative/current manifestation of IRS Publication 946 for tax year 2026"), tying canonical identity to freshness.

**Frozen gate (12).** (1) ISBN/DOI/document number resolves to an existing global Work and reuses an owned manifestation at $0; (2) equivalent copies of one authoritative document are one lineage; (3) a derivative source does not independently corroborate the Work it derives from; (4) a finding citing an unavailable Work creates a Work stub, a Candidate and a specific Evidence Target; (5) a newer governing edition makes old-version evidence `needs_refresh`, not blindly `stale`; (6) a materially changed provision makes old supporting evidence `stale`; (7) a mirrored/rehosted identical manifestation triggers no freshness degradation; (8) **ambiguous title matching never auto-merges two Works**; (9) one Work is relevant to many projects without duplication; (10) project dismissal/relevance never mutates the global Work; (11) the resolver prefers owned/global-library manifestations before external acquisition; (12) **Claim independence is computed by lineage, not raw source count.**

# G7 LOCK — Deep & Community Source Discovery (Kyle, 2026-09-08)

**Principle.** Community evidence is valuable because it reveals lived experience, failure modes, edge cases and practitioner knowledge. It must never inflate factual consensus or quietly outrank governing evidence.

**Constraints.** (1) Community is an EVIDENCE CLASS (community/experiential), not a platform type: adapters (Reddit first; forums, owner communities, professional boards, discussion threads, imported Slack/Discord exports, comments beneath other media later). (2) Thread structure is preserved — original post, comments, replies, corrections attached to the statement they correct; a corrected statement is never surfaced later as unqualified consensus. (3) The THREAD is the acquired Source; posts/comments are evidence locators (`r/flying · thread title · comment by <author if retained> · locator · retrieved <date>`), never hundreds of global source rows. (4) Metadata discovery is separate from acquisition: community → search/enumerate → Candidate Threads (cheap metadata) → rank against the Evidence Target → Review → acquire selected; unselected stay candidates; never ingest whole communities. (5) Queries are Evidence-Target-aware: Claims, targets, tensions, missing perspectives and Planner dependencies generate community search missions ("unexpected first-year Baron maintenance costs", not "Baron 58"). (6) Discovery preferentially surfaces experience language ("I own…", "after X years…", "I wish I knew…", "my annual cost…", "biggest mistake…", "wouldn't do it again…", "unexpected…", "A&P here…", "CPA here…", "we see this frequently…"). (7) Signals stay multi-dimensional — relevance, substance, firsthand, specificity, quantitative detail, corroboration, community support, evidence links, professional context, disagreement — never one trust score; **upvotes are evidence of community reaction, not truth.** (8) Community consensus = independent experiential recurrence: REPEATED INFORMATION (six posts repeating one creator/article — G6 lineage) ≠ INDEPENDENT EXPERIENCE (six unrelated owners describing the same failure). (9) Cross-thread synthesis yields structured states — FREQUENTLY_REPORTED · MIXED_EXPERIENCE · STRONG_DISAGREEMENT · RARE_BUT_SERIOUS · FIRSTHAND_EXAMPLES — each retaining evidence links; synthesis is derived, never primary evidence. (10) Claim type decides what community evidence can establish: "The SBA requires X" from community posts is governing with experiential evidence → *insufficient authority* → find the governing primary source; "many first-time twin owners report difficult underwriting" can strengthen from independent firsthand reports. (11) Community references to Works resolve through G6: the post INTERPRETS / QUOTES / DISCUSSES the Work — never a second lineage for what the SOP says. (12) Self-asserted credentials are `claimed_context: CPA, basis: self-described` — never verified authority. (13) Preserve retrieved_at, platform id, thread/comment id, edited state, deleted/unavailable state, source revision; a deleted comment that supported a Claim becomes *previously retrieved evidence, currently unavailable*, never silently vanishes. (14) MISSING_PERSPECTIVE is a flagship workflow: manufacturer material + brokers + optimistic videos → G5 flags the missing owner-regret perspective → G7 searches for regret, failure, surprise costs, downtime, "wouldn't buy again", mistakes. (15) Novelty and Research Tensions consume community evidence immediately (one experienced buyer → NOVEL, high impact, needs corroboration; five unrelated buyers → corroboration rises; a broker disputes → MIXED/DISPUTED).

**Cost strategy.** metadata search → Candidate Index → cheap ranking → selected thread acquisition → signal extraction only for selected material. A 500-comment thread: deterministic pruning first; the full tree kept locally; model analysis only of high-signal branches/windows; more branches promoted when the model reports unresolved context. Never 500 comments blindly through a large model.

**Acceptance gate (frozen, 15 points).** Fixture: one authoritative Work (G6); one thread quoting it incorrectly with a correction later in the thread; three independent firsthand owner reports about a practical problem; two derivative posts repeating one external article; one low-engagement, highly substantive professional comment; one high-upvote joke/unsupported assertion; one previously skipped Candidate Thread that becomes relevant after a MISSING_PERSPECTIVE target appears. Prove: (1) thread/reply hierarchy survives ingestion; (2) the corrected false Claim does not become consensus; (3) three independent firsthand reports count as three experiential lines; (4) two derivative posts do not count as two lines; (5) high engagement does not outrank substantive evidence automatically; (6) self-declared professional context stays explicitly unverified; (7) regulatory Claims from community material trigger primary-source verification through G6; (8) the skipped Candidate is resurfaced without re-enumerating the community; (9) cross-thread synthesis distinguishes recurring experience from disagreement; (10) synthesis retains exact evidence provenance; (11) no community candidate becomes project evidence before acquisition/attachment; (12) acquisition goes through global identity, jobs, revisions, staleness and cost accounting; (13) prompt-injection text inside a post cannot change agent behaviour; (14) NOVEL / CONTRADICTION / MISSING_PERSPECTIVE tensions arise from community evidence; (15) every hardened platform and release gate stays green.

**Cleanup alongside.** A tested canonical `merge_work(source_work, canonical_work)` primitive (migrates versions, manifestations, project relationships, citations/relations, targets; keeps an audit alias) — used to fold the Form 1120S / Form 1120-S duplicate, never an ad-hoc DB fix.

# PROPOSAL — Source Navigator + Scoped Refresh (Kyle, 2026-09-08; sequencing to be decided)

**Mission.** Turn the Global Library from a flat inventory into an organized, addressable source hierarchy where any source, container, content class or subtree can be independently refreshed, diffed, acquired, re-indexed or re-analyzed without duplicating existing evidence or repeating unnecessary paid work. **Invariant: folders organize scopes; they never own evidence.** A video can appear under a channel, a playlist, a project, a Work, a tag and a search result at once — one canonical source/manifestation underneath.

**Model.** Virtual folders backed by canonical objects: platform/origin → container (channel, subreddit, site, podcast, course) → content type (videos, playlists, threads, publications, forms, episodes, modules) → item → Work/version/manifestation. Built on `collections` / `source_collections`, global `sources`, project attachment, Works, the Candidate Index. Every level is an actionable scope with actions that mean different things and cost different amounts: **Refresh** (re-enumerate container metadata, $0/low) · **Find new** (listing vs Global Library/Candidate Index, $0/low) · **Check changes** (newer versions, changed URLs/content, removed items, low) · **Ingest new** (acquire only newly discovered material) · **Re-ingest** (deliberate rebuild, potentially expensive) · **Re-index** (chunks/search/embeddings without reacquiring, embedding cost) · **Re-analyze** (Findings/Claims on existing content, model cost) · **Re-analyze for project** (reinterpret existing global evidence against one project's brief, model cost). "The source changed" and "my research question changed" are different events: a changed mission → *Re-analyze for: Business Acquisition* on `Reddit → r/smallbusiness` downloads nothing; six months later → *Refresh channel* on `YouTube → Mark J Kohler` enumerates cheaply and reports "247 known · 18 previously rejected · 12 new since last scan · 3 appear changed · 0 downloads — Review 15 changes"; money is spent only after review.

**Saved scan scopes.** Every container keeps its acquisition recipe (source, community/channel id, content kinds, lookback, sort modes, minimum score, selection rule, last enumerated / last acquisition / last project analysis, known / ingested / rejected / unreviewed counts) — a repeatable acquisition boundary, not just organization.

# Rung log

*(Each rung: version, what changed, invariants, states, schema, jobs, provenance, staleness, cost, tests, measured usefulness, limitations, experiments rejected, dependencies for the next rung.)*

## G1 — Global Source Identity & Deduplication — 0.25.0 (COMPLETE)

**What changed.** One resolution path, `identity.resolve_or_create_source(candidate, project_id)`, returns the five states (ALREADY_IN_PROJECT · EXISTING_READY · EXISTING_PENDING · EXISTING_FAILED · NEW) and is used by every entrance: single URL, channel/playlist/search listing, Instagram listing, pasted HTML, session ingest, file upload (media, document, spreadsheet, subtitle), pasted text, transcript import, course import (via `ingest_url`), library attach (`/members`, CLI `project add`, MCP `add_to_project`). Creation is transactional: two concurrent adds of the same source resolve to one row (unique index + IntegrityError re-select), tested with 8 threads.

**Identity (Invariant C).** platform-native id → canonical URL (`sources.canonical_url`) → content fingerprint (`sources.content_fingerprint`, sha256; uploads now keyed `file:<fp>`, pasted text `text:<fp>` — stable across restarts) → the legacy `name:size` upload key, trusted only while the legacy row's content is unknown or matches, and stamped with the fingerprint on first match. `db.upsert_source` refuses a row with no identity (the old blind insert on a missing external id is gone). The `ingest_url` job dedupe key is the canonical URL, so `youtu.be/X` and `watch?v=X&si=…` are one unit of work.

**States → behaviour.** Ready: attach + this project's own project-relative analysis, nothing re-downloaded (findings queued exactly once per project). Pending: attach to the same global work; status is never reset; a second project waits when another job owns the source (`identity.claim_job_for` stamps the running job with the source so `live_job_by_source` sees it), and a stale pending row with no live job is resumed once. Failed: attached and reported to a new project without spending; the project that already has it re-adding it is a retry request; `force` retries from anywhere. A channel listing never flips an in-flight source to `proposed`, and review meta carries `counts` (found / already in library / already in project / new) so the estimate covers new work only. A transcript import with a collection now attaches the source to the project (it used to attach only the collection).

**Schema (additive).** `sources.canonical_url`, `sources.content_fingerprint` (+ indexes), `source_relations` (lineage seam for derived-from / cites / same-work — empty until a later rung, so corroboration can tell repeats from independent evidence without retrofitting identity).

**Provenance / cost / Health.** Every reuse writes a `source_reused` validation event (state, project, source) and bumps `library:acquisitions_avoided` (ready/pending) or `library:failed_attached`; Health → `library` (sources, ready, shared_by_projects, acquisitions_avoided, duplicate_fingerprints); doctor warns on duplicate fingerprints; release-check gained the gate “global identity: one acquisition, N project relationships”. Revisions and staleness are untouched: attaching an existing source runs a new project-relative analysis under the existing source revision.

**UI.** Add-a-link chips say “already in your library, attached (nothing re-downloaded)”, “already being ingested for another project”, or “attached, but its last acquisition failed”; review cards show the four counts; Health has a Global Library row.

**Tests.** `tests/test_k2_identity.py` (12): the five states, concurrent create, identity order + legacy fallback + same-name-different-bytes, refusal of identity-less rows, the Feature Gate (three URL forms × two projects → 1 row, 2 links, 1 ingestion, 2 analyses), shared pending, failed attach/retry rules, content-based upload reuse with no re-extraction, stable pasted-text identity, import-with-collection attach, listing never resets in-flight sources, idempotent library attach, Health + migration. Suite 275.

**Measured usefulness.** Deterministic: a second project attaching the same sources performs zero acquisitions (`acquisitions_avoided` = number of sources, $0). No live run (paid evals are for model/architecture changes only).

**Known limitations.** Web pages are identified by canonical URL, not content (a page's content is a revision, not an identity). Cross-platform identity (the same episode on YouTube and as a podcast enclosure) is Rung 6 (Works). `source_relations` is a seam only. Proposed-but-unselected review items are still deleted on approve — the Candidate Index (Rung 3) replaces that.

**Experiments rejected.** None — G1 is infrastructure, not a heuristic.

**Next rung depends on.** `identity.Candidate` + `identity.resolve` (dry run) for G2 classification and G3 enumeration counts; `source_relations` for C6/G5.

## G2 — Universal Resource Input — 0.26.0 (COMPLETE; delivered together with G1)

**What changed.** `resources.classify(text)` recognises, deterministically (host/path shapes, checksums — no network, no model): page · document · spreadsheet · image · video · media · instagram_post · channel · playlist · feed · sitemap · folder · website · website_section · repository · community · instagram_profile · search_query (free text or a YouTube search link) · work_identity (ISBN-10/13 with checksum, DOI incl. doi.org links). Each classification carries a plain-language label/detail and its **actions** with availability: `ingest` / `page` (standard `ingest_url` → G1 identity), `explore` (available today for channel/playlist/search — the existing review flow; reported *unavailable, never faked* for website, section, sitemap, feed, repository, folder → G3, community → G7, instagram_profile → extension), `discover` (a research request → the existing `discover` job with the text as `refine`), `upload`, `resolve` (ISBN/DOI → Source Resolver, G6). `resources.route(classification, project_id, action)` turns a choice into work on the standard paths only.

**Feature Gate.** A root website, repository, community, feed, sitemap or Work identity no longer falls through to naive webpage ingestion: `route()` refuses an unavailable action and only fetches a container as one page when `page` is chosen explicitly; a community has no default action at all. Chat: a pasted container comes back as *detected* with the choices instead of being queued; items and reviewable collections queue as before.

**Surfaces.** `POST /api/classify` (one classification per line), `POST /api/projects/{id}/add` (classify + route, per-line default or an explicit action). Sources → Add shows "Website detected — irs.gov … [Explore website (coming)] [Add home page only]" as you type, one radio row per line; the Add button routes each line by its chosen action. Chat chips: "🔍 irs.gov — Website detected · choose in Sources → Add".

**Platform Integration Gate.** Every resulting source still enters `ingest_url` → `identity.resolve_or_create_source` (G1), the durable queue, provenance, revisions/staleness, cost and validation; nothing new stores sources. Release-check gained "universal input: containers never fall through" (`tests/test_k3_resources.py`, 29 tests: a 25-case classification matrix, bad-ISBN checksum, multi-line splitting, refusal/explicit-choice routing, API, chat).

**Known limitations.** Classification is shape-based: a one-segment path such as `/about-irs` is reported as a website *section* (its default action is still "add as page", so nothing is lost). Images are recognised but not ingested (Rung 8). `explore` for websites/feeds/sitemaps/repositories is a declared, unavailable action until G3 — visible to the user as "(coming)". Folders/archives are not yet reachable from a URL.

**Next rung depends on.** `Classification.kind` + `route(…, "explore")` is the seam G3 fills (enumerators per kind → candidates → identity dry-run counts → Candidate Index → review).

## G3 — Website & Collection Exploration + Discovery Candidate Index — 0.27.0 (COMPLETE; delivered together with G1/G2)

**What changed.** `explore.py` turns containers into ranked review sets, deterministically and bounded, through `safe_fetch` only: **feeds** (RSS 2.0 / Atom → podcast episodes keyed by GUID with enclosure, duration, author; blog posts keyed by canonical URL), **sitemaps** (urlset; sitemap indexes followed up to `MAX_SITEMAPS`, a failing child is skipped — fail open for discovery; assets and boilerplate paths filtered; newest `lastmod` first; capped at `MAX_ITEMS`), **websites** (robots.txt `Sitemap:` → sitemap(s) → the section's path prefix when the user pointed at one → the page's own same-host links as the last resort, `HOME_LINKS_MAX`; never a crawl). The `explore` job (durable, dedupe `explore:<project>:<url>`) creates a collection + proposed sources through G1 identity (a page already owned counts as "already in your library"), remembers every entry in the Candidate Index, and hands off to the existing `rank_proposed` → Review flow; review meta carries `counts` and `how` ("robots.txt → sitemap → section /forms-instructions"). `resources` now offers **Explore** for website / section / sitemap / feed as the default action (repository and community remain declared-unavailable: G3 follow-up and G7). Web pages proposed by an exploration are read by the page path (`ingest_source` → `ingest_webpage`).

**Discovery Candidate Index** (`candidates.py`, tables `candidates` + `candidate_projects` + FTS). What we have SEEN but not acquired: one global candidate per (platform, external_id) with cheap metadata (title, description, creator, date, duration, views, first/last seen, availability), a per-project relationship with state (`available · skipped_low_relevance · skipped_limit · skipped_cost · user_dismissed · duplicate · acquired`), relevance + reason + origin (which listing, when). Populated by every enumeration — YouTube channel/playlist/search, Instagram profile, feed, sitemap, website — at zero acquisition cost. **Skipped ≠ forgotten:** `approve_proposed` now records why each unselected proposal was skipped (below the relevance cutoff vs outside the number picked) before dropping the proposal row; the chosen ones resolve to their source (`candidates.source_id`), and any source created by any path resolves its candidate (`candidates.resolve_acquired`). **Gap recall:** `candidates.search(project, query)` (FTS over metadata) returns seen-but-unacquired items with their project state and whether the global library already owns them; `user_dismissed` is hidden unless asked for — user intent outranks recall. The chat has `search_seen_sources` (metadata only, explicitly "cannot be cited"), the API has `GET /api/projects/{id}/candidates?q=…`, dismiss / restore / **acquire** (through `ingest_url` → G1 — never a parallel path; an already-owned candidate is attached, not re-acquired). UI: Sources → Library → "Seen, not added" with search, states, origin, Add / Dismiss (with reason) / Restore; Health's Global Library row counts candidates.

**Feature Gates.** A large domain becomes a concise review set (sitemap-first, capped, filtered) rather than a crawl; after listing a collection and acquiring some of it, the rest remain searchable as candidates without transcripts or content embeddings; a later gap surfaces a previously skipped candidate without re-enumerating (test: the insurance episode skipped at relevance 41 is recalled by "insurance low-time twin pilots"). **Evidence isolation:** candidates never enter `chunks`/FTS/embeddings; `search.search` cannot return them; the chat tool result is labelled metadata-only.

**Platform Integration.** Identity via G1 (one candidate across channel + playlist + search), durable `explore` job, review as the cost boundary (estimate covers new work), `safe_fetch` for every request, cost: nothing paid to populate the index (ranking uses the existing `rank.relevance` contract on titles/descriptions as before). Release-check gate added (`tests/test_k4_explore.py`, 8 tests; suite 312). Tier 1 chat totals re-frozen once more for the new tool (170,091; `CHAT_ARM_INPUT_TOTAL` 183,154).

**Known limitations.** Sitemap/website candidates carry a humanised path as their title (no page fetch to read `<title>` — by design, to keep the index free); ranking therefore has less to work with for such pages than for videos. No candidate freshness re-verification yet (`last_verified_at` is only set on acquisition). No metadata embeddings (FTS only — adopt only if measured to help). Repository exploration is declared but not built. Podcast episodes acquire through yt-dlp's generic extractor on the enclosure URL.

**Next rung depends on.** `candidates.search` as tier 3 of the evidence escalation (G4/C5); `explore.ENUMERATORS` as the extension point for repositories (G3 follow-up) and communities (G7).

## G4 — Global Library Intelligence — 0.28.0 (COMPLETE, pending delivery)

**What changed.** `library.py`. Two layers of **project-neutral Source Profile** (table `source_profiles`, versioned by source revision): a **$0 baseline** built lazily from what is already stored — source metadata (title, creator, platform, dates, duration, kind, tags, host), the source's own top terms, deterministic **authority signals with their basis** (government/education/organisation domain, kind, official-style document titles, creator, publication date, how the text was obtained — facts, never a score), a chunk-vector centroid as a *coarse* signal only, and `TOPIC_VECTORS` representative chunk vectors chosen by farthest-point sampling (the outlier first) so a briefly-covered topic keeps its own vector; and an **enriched profile** (`library.profile` contract, schema `source-profile-v1`: summary, topics, entities, document type, evidence class, temporal character, useful_for, not_useful_for, authority_notes with basis, minority_topics), generated **only** for sources that became plausible candidates (`want`), cached globally with model/prompt/schema/input-hash/routing/transport provenance, marked `stale` when the source revision moves, and re-used when the inputs are unchanged (no second spend). **Never built from project findings, summaries, relevance or steering.**

**Library recall** (`library.recall(project, query)`): Library Candidates = ready sources *outside* the project; chunk-level FTS + vector retrieval over them (`search.search`, per-source cap, nothing averaged away), grouped by source, precision bias (`MIN_SCORE`), then baseline term/title hits and — when present — enriched topic/entity/useful_for hits as ranking bonus + explanation. Each suggestion carries the matching passages with locators, `why`, authority signals, evidence class/temporal character if enriched, source revision, and an explicit `attach` action. **Nothing is attached**; the project's own retrieval sees nothing until the user adds it (G1 `attach_existing`). Top unenriched hits are marked `wanted` with the reason (provenance of a future spend); recall never waits.

**Enrichment policy (Kyle's four corrections, all gated by tests):** no findings in global profiles (test asserts a planted finding never appears); centroid coarse only + per-chunk recall + topic vectors (farthest-point test keeps the lone minority chunk); authority = deterministic signals with basis + descriptive `authority_notes`, never a verdict; and **the acceptance gate: recall works with zero enriched profiles** — the test wipes every enrichment row, proves recall finds the right owned source through chunks + metadata, proves the project boundary, then proves enrichment improves ranking/explanation without moving the boundary. Enrichment is lazy (`want` → `enrich_wanted` for ≤ `INTERACTIVE_MAX` inline when a query needs them) and **opportunistically batched**: `maybe_queue_batch` creates one durable `enrich_profiles_batch` job only when ≥ `BATCH_MIN` wanted profiles have accumulated (one at a time; never on a timer; never for sources nobody asked about), reusing the Rung G batch machinery (`batch_items`, `AnthropicBatch`, `external_pending`, 50% usage rate, `usage.kind = profile`). No eager pass over the library exists anywhere in the code.

**Library-first Discover.** `discover(mode=library_first|library_only|web_first|web_only)`: the library is consulted first at $0; `library_only` never calls a model; `library_first` without a refinement skips the web pass only under a deliberately conservative rule — ≥ `LIBRARY_ENOUGH` (4) owned sources matching at ≥ `LIBRARY_STRONG` × `MIN_SCORE` with two or more passages each — and even then says the library *appears* to cover it and offers Web first (relevance is not evidence sufficiency; that model arrives with G5 Claims); with a refinement the web passes run with the owned sources listed as "do not propose again". UI: mode selector + an "In your library — no new acquisition needed" card with passages, signals and Add buttons. Chat: `search_global_library` tool (suggestions only, explicitly not citable; Add buttons on the action chip). API: `GET /api/projects/{id}/library/recall?q=`, `GET /api/sources/{id}/profile`, `POST /api/library/enrich` (a few inline, or the wanted queue as one batch), `GET /api/library/stats`; Health's Global Library row shows profile counts.

**Platform Integration.** Contract with NO_FALLBACK, structured output, batch_allowed; provenance on every enriched profile incl. routing; revision-aware staleness; durable job; usage accounting (`profile` kind, batch rate); project boundary intact (Invariant D); release-check gate added (`tests/test_k5_library.py`, 9 tests; suite 321). Tier 1 chat totals re-frozen for the new tool (175,395; `CHAT_ARM_INPUT_TOTAL` 188,458).

**0.28.1 — real-library verification fix.** On the 900-source library an off-topic question ("low-time pilots… twin-engine Baron insurance") still returned four suggestions at healthy-looking scores, because RRF scores are rank-based — the top hit of *any* query looks the same. Recall now also requires an absolute signal: the share of the query's content terms that actually appear in the matched passages/title (`MIN_COVERAGE` 0.4 to be suggested at all; `STRONG_COVERAGE` 0.6 plus ≥2 passages for Discover's conservative web-skip). Suggestions report `coverage` and `covered_terms`. Test: the off-topic question returns nothing.

**0.28.2 — first real opportunistic batch failed on a schema trap.** The first library-first Discover on the real library queued 28 wanted profiles, so `enrich_profiles_batch` ran 30 items at batch rate — and every one failed *local* validation: `authority_notes` exceeded a `maxLength: 300` that the provider never saw, because `provider_schema` strips client-only constraints. Cost: one batch of 30 profiles wasted (batch-rate, cents), zero data corruption — failed profiles stay `failed` and re-become `wanted` on the next recall, so nothing was lost except the money. Fix: `source-profile-v1` carries no string-length constraints at all (lists are bounded with `maxItems`, categories with enums); a regression test walks the schema for `maxLength`/`minLength` and validates a deliberately long profile. Lesson recorded for every structured-output schema: a constraint the provider strips is not a constraint, it is a way to fail after paying. (`prefilter-v1` still carries one; that feature is off.)

**Measured usefulness.** Deterministic on the Golden Project: a new empty project asking about SBA lender documents is pointed at the owned lending summary with the exact passage, at $0, before any web pass; `library_only` Discover makes zero model calls.

**Known limitations.** Recall is bounded by the existing chunk retrieval (RRF over FTS + vectors) — no cross-source profile embedding index yet (the centroid/topic vectors are stored for it; adopt only when measured). Enriched profiles are interactive or one batch at a time; there is no scheduler. Authority signals know government/education/organisation domains and a few official-title patterns; publisher identity and Work relationships arrive with G6.

**Next rung depends on.** `library.recall` as tier 2 of the evidence escalation (Chat C5, Gap Engine C4); `source_profiles.enriched.evidence_class/temporal_character` for freshness (C2) and Knowledge Map coverage (G5).

## G5 — Knowledge Map, Claim Graph & Evidence Planning — 0.29.0 (COMPLETE, pending delivery)

**Built on.** `project_notes` (approved/suggested findings with citations = the $0 source of candidate Claims), `library.recall` (tier 2), `candidates.search` (tier 3), `library.authority_signals` / `source_profiles.enriched.evidence_class` (evidence class of a source), `sources.revision` (exact-revision provenance), the Rung G job queue (`extract_claims`, dedupe `claims:{project}`), structured outputs (`claim-set-v1`, no string-length constraints — the 0.28.2 lesson), Discover, the chat tool loop.

**Modules.** `claims.py` — candidate harvest ($0; a finding whose proposition already exists becomes EVIDENCE for that Claim, never a second Claim), `add_evidence` (freezes `source_id, source_revision, locator, start, link, relation, excerpt, evidence_class, independent/derivative_of, task/model, created_at`; independence decided by passage overlap ≥ 0.6 or same creator), `assess` (governing vs corroborative sufficiency, domain-sensitive freshness → `stale`, contradiction downgrade, readiness separate from strength — every verdict carries `strength_why`), `relate` (CONTRADICTS is downgraded to QUALIFIES when jurisdiction/product/population/conditions/timeframe or primary-rule-vs-experience differ), `extract` (contract `claims.extract`, groups of 20, idempotent by `extraction_hash`), `maybe_extract` (event-driven: after a findings job; debounced: ≥ 6 unnormalized candidates or 30 min since the last pass; one job, deduped), `ensure` (what Chat/Discover call: $0 unless explicitly allowed to spend). `knowledge.py` — Evidence Targets with explicit closure (`closure` text + `closure_rule {min_independent, primary_required, characterize_disagreement}`), `pursue` = PROJECT EVIDENCE → GLOBAL LIBRARY → CANDIDATE INDEX (reranked against the target: term coverage × preferred-class fit; skipped candidates resurfaced to `available` with the reason) → EXTERNAL (a `discover` job only on request), tensions `NOVEL · CONTRADICTION · WEAK_CONSENSUS · STALE · MISSING_PERSPECTIVE` (NOVEL is project-relative: an idea echoed by another source is not an outlier; NOVEL/WEAK_CONSENSUS open a corroboration target), `refresh` (nodes with `why`, never a count), `state`, `summary_text`. Surfaces: `GET/POST /api/projects/{id}/research[/refresh]`, `/claims`, `/api/claims/{id}/{status,relate}`, `/targets`, `/api/targets/{id}/{pursue,status}`, `/api/tensions/{id}/status`; chat tools `research_state` ($0) and `propose_claim` (external assertion → proposed Claim + target; `record_fact` stays for the user's own constraints); a `Research state` line in the volatile state block; Discover leads with research state (open targets and tensions steer the web prompt; `research` in every result); UI **Research** view (map, tensions, targets with Look ($0) / + web, Claims with Accept / Applies to us / Reject) and a research header in the Discover pane. `db.replace_transcript` stales exactly the evidence rows frozen on the old revision.

**Decisions honoured.** Automatic but never a paid call per finding (jobs `_after_done` → harvest + debounced `maybe_extract`); useful with zero extraction calls (the acceptance gate runs entirely on the $0 path); one primary source makes a governing Claim Strong; independence decides corroborative strength; Strong ≠ Decision Ready; qualifiers preserved (the contract is instructed never to strip hedges; the fake keeps them); user facts are not Claims; contradiction scope check; map explains why; targets state closure; candidate rerank is against the target; tensions from day one; suggestion-first (`status` and `application` are only written by `set_status`, never by the model pass).

**Acceptance gate (frozen, tests/test_k6_claims.py::test_g5_acceptance_gate_end_to_end).** The vague accounting-practice project: SOP page on sba.gov (authoritative) + three channels repeating the passage + one podcast outlier (importance 5) + one 2023 fee-rate page + one candidate skipped as low relevance. All ten points hold with `safe_fetch` poisoned (no network) and zero `claims.extract` invocations. 8 tests; suite 330.

**Frozen numbers.** Tier 1 chat totals re-frozen for the two new tools and the research line: answer 34 calls / 175,395 → **186,010** tokens; `CHAT_ARM_INPUT_TOTAL` 188,458 → 199,070; sum 241,614 → 252,229. Findings/plan unchanged. Recorded in HARDENING.md.

**Honest limits.** Claim types and topics on the $0 path are heuristic (cue words + evidence class) until the extraction contract names them; the Message-Batches transport for `claims.extract` is deferred like G4's (contract is `batch_allowed`, jobs run inline groups) until a project shows a backlog large enough to matter; independence is passage-overlap + creator identity, not citation analysis (G6 Works will improve it); freshness uses `published_at` (ingest date as fallback), so undated sources are never flagged stale.

**Next rung depends on.** `project_claims.claim_type` + `claim_evidence.evidence_class` for G6 canonical Works (which manifestation is the primary?) and G7 community/experiential sourcing (MISSING_PERSPECTIVE targets name the class to acquire); `knowledge.pursue` as the Gap Engine's spine (C4/C5) and Research Missions (G9); `research_tensions` as the seed of Novel Insights (C3).

**0.29.1 — real-library scale.** The first `research/refresh` on the 449-source project (≈5,000 findings) did not return within the browser's timeout: the $0 harvest compared every finding against every Claim (O(n²) token overlap) and assessed a Claim after every merge; NOVEL detection did the same. Now: an inverted token index for twin/echo search, one write transaction per harvest, assessment once per touched Claim, one evidence query per project instead of N+1, source lookups memoized per assessment; the NOVEL budget is 12 per pass (highest importance first) so a thousand lone findings do not become a thousand tensions and targets; $0 topics use the project's own vocabulary (most-shared content word) so nodes aggregate instead of one node per finding; the state payload is paged (300 Claims, 12 evidence rows each, 100 targets/tensions, with totals). Synthetic 300-source / 3,000-finding project: harvest 170 s → 3 s, refresh 13 s → 0.6 s, payload 3 MB → 0.5 MB.

**0.29.2 / 0.29.3 — reconciliation after the first real pass.** 0.29.0's unbounded first pass had left the 449-source project with 3,480 open tensions and 1,545 targets (one per lone finding) and 1,354 orphan map nodes (targets kept their pre-vocabulary topics). Each deterministic pass now owns its NOVEL / WEAK_CONSENSUS / STALE / MISSING_PERSPECTIVE tensions: whatever it does not re-select is dismissed and the corroboration target it had opened is `dropped` (user-made targets are never touched; a re-selected tension re-opens its target); targets linked to a Claim follow that Claim's topic. The $0 freshness guess was over-eager ("market", "current" made 632 Claims `periodic` → stale): `periodic` now needs a dated figure (a rate/fee/price *and* a year or "fiscal"/"currently"); `fast_changing` needs promotion/offer/deadline/expiry words. 0.29.3 also re-derives the $0 freshness class of unnormalized Claims on every harvest (the 632 `stale` Claims came from the old guess), and reports open tensions by kind.
**0.29.4 — tension budgets.** On the real project the remaining open tensions were 340 STALE + 272 WEAK_CONSENSUS: true by the rules, useless as a list. A STALE tension now only for Claims that matter (importance ≥ 4 or accepted — every stale Claim still shows `stale` with its reason), WEAK_CONSENSUS capped at 40 per pass (highest importance first). The acceptance fixture's fee-rate finding is importance 4 so the gate still asserts the STALE tension.

## G5.1 — Claim-relative freshness + bounded normalization policy — 0.30.0 (Kyle's correction, 2026-09-08)

**Decision.** Freshness belongs to the Claim, not to the age of the source it came from. A 2021 interview carries a stale rate, a still-current transition insight, a timeless anecdote and a rule that needs re-verification at once. The verdict is a separate field (`freshness_status`: current · needs_refresh · stale · uncertain · age_insensitive, with `freshness_why`), never folded into evidence strength; readiness drops to not-ready on a stale Claim. Classes (`claims.FRESHNESS_RULES`, refresh/stale horizons): regulatory (365 d → needs refresh: verify the current version/effective date; never "stale" by age) · rates_pricing (180 / 540 d) · promotional (60 / 120 d) · underwriting_practice (365 / 730 d) · tactics (6 y → newer corroboration preferred; never stale) · operational (7 y) · experiential, historical, static (age-insensitive; applicability instead) · uncertain (3 y → `uncertain`, never stale). The $0 heuristic classifies from Claim semantics + temporal language + evidence class + governing domain and errs toward `uncertain`; the extraction contract names the class per Claim. Legacy 0.29.x values map (slow_changing → tactics, periodic → regulatory, fast_changing → rates_pricing). STALE tensions cover `stale` and `needs_refresh` for Claims that matter. Frozen test: one 2021 interview → stale rate / age-insensitive transition insight / age-insensitive anecdote / regulatory needs-refresh / static framework / uncertain observation; strength never carries a temporal verdict.

**Normalization policy.** Never the whole corpus. `claims.select_cohort` picks decision-relevant Claims first — strong/developing, NOVEL/CONTRADICTION/WEAK_CONSENSUS tensions, Claims behind open or pursued targets, important stale/needs-refresh Claims, Claims the current plan's evidence points at — then a stratified (by topic, importance-first) sample of weak Claims, capped by budget (default 150). `claims.run_evaluation` is a durable job (`extract_claims` with `evaluation`) that snapshots, normalizes, refreshes and measures: merges, qualifiers present, hedges kept (hedged text must keep a hedge or a `conditions` qualifier), over-generalizations (hedge lost + text shrunk ≥ 40 %), `imposed_by` distribution, type changes, topic count, tensions and open targets before/after, calls and USD from the usage ledger; report at `GET /api/projects/{id}/research/evaluation`, rows kept for review. Long term a Claim earns normalization when it becomes decision-relevant, gains evidence, meets a contradiction, opens a tension or target, is depended on by the Planner, or is asked about in Chat.

**Requirement provenance (the CPA-buyer test).** The contract keeps who imposes a requirement in `qualifiers.imposed_by` — seller_or_listing · legal_ownership · professional_licensing · service_performance · lender_policy · state_specific · unclear — and is told never to collapse "the seller wants a CPA buyer" into "only CPAs can buy CPA firms"; where the evidence is ambiguous it says so in `conditions` and proposes a target that decomposes the underlying question by those sources. Live result recorded below once the bounded evaluation has run.
**0.30.1 — first live reading of G5.1 on the 449-source project:** 2,036 age-insensitive · 797 current · 703 needs refresh (regulatory: "verify the current version") · 500 stale · 167 uncertain. The stale count was inflated by "%"/"$" alone making a Claim `rates_pricing` ("10% down" is a structure point, not a price): the cue now needs a money-over-time word too. STALE tensions get a per-pass budget (60, stale before needs-refresh, importance first) like NOVEL and WEAK_CONSENSUS; every Claim still carries its own freshness verdict.
**0.30.2 — the first live evaluation truncated.** Groups of 20 Claims produced more than the 4k-token output budget (each normalized Claim carries an 8-field qualifier object) and the sixth group failed after five had landed; the job failed and the before-snapshot with it. Now: groups of 8, budget 5k / ceiling 8k, and the evaluation is resumable — the cohort, before-snapshot and cost mark are stored as `claims:eval:{project}:pending` at the start, so a retry measures the same cohort and only spends on what is still unnormalized (frozen test).
**0.30.3 — two production findings.** (1) The live evaluation's first call failed local validation on `missing_areas` > maxItems 8 — the second time a paid response died on a bound the provider strips; `schemas.clamp` now truncates such lists/strings before validation for every structured task (frozen test), so this class of failure is gone by construction. (2) Kyle reported chat answers ending mid-sentence: `qa.ask` treated `stop_reason=max_tokens` like `end_turn`. Fixed with diagnostics, automatic continuation (≤ 2), a forced text round after the tool rounds, a 4k budget, a concise-answer rule and a release gate — details in HARDENING.md.

**0.30.4 — the bounded normalization evaluation, live (2026-09-08, business-acquisition project).** Cohort 150 of 4,203 candidates (27 strong/developing, 41 tension, 81 important stale/needs-refresh, 1 evidence target), 19 calls, **$1.21**, 144 normalized, 5 merged. Qualifier preservation: 144/144 carry qualifiers; 56/56 hedged texts kept their hedge or a `conditions` qualifier; 0 over-generalizations. `imposed_by` was populated on 48 requirement Claims (lender_policy 29, legal_ownership 9, seller_or_listing 5, state_specific 4, unclear 1). **The CPA-buyer test passed:** "Buyer must be a CPA who can prepare compilations — this professional licensing requirement disqualifies non-CPA buyers…" became "A listing for a Central Valley CPA Practice (CAN6535, profiled 2026-08-18) states the buyer must be a CPA who can prepare compilations — this is a seller/listing-imposed requirement…", `imposed_by = seller_or_listing`, jurisdiction "California (Central Valley)", population "prospective buyers without CPA licensure", conditions "as stated in the listing's Specific Requirements sheet; no independent verification…", source language kept verbatim — the listing preference was not collapsed into a licensing rule. Freshness classes moved sensibly (STALE tensions 42 → 19; the model reclassified many $0 guesses). Two things it did badly, fixed here: topics fragmented (28 → 138 for 150 Claims — one topic per Claim) and every call proposed up to 8 targets from the same brief (53 → 227 open targets, mostly rephrasings). Now the contract receives the project's existing topics and open targets, must reuse topics and propose at most three genuinely new targets per call; targets dedupe by meaning (Jaccard ≥ 0.5) at creation and on every refresh (user targets never folded); NOVEL echo detection is symmetric so a verbose normalized text cannot "echo" every short Claim it shares a few words with. **Verdict:** normalization materially improves qualifier fidelity, requirement provenance and freshness classification at ~$0.008 per Claim, and is worth running lazily for decision-relevant Claims; corpus-wide normalization stays off.
**0.30.5 — the decomposition target + map nodes.** The live pass decomposed the CPA requirement's qualifiers correctly but did not open the governing question; now a normalized requirement whose `imposed_by` is seller/listing or unclear opens a $0 governing target ("Is this a legal ownership, professional licensing or service-performance requirement in California (Central Valley), or only the seller's/listing's preference: …", closure = one current primary source that imposes it or shows it is not imposed). Map nodes need ≥ 3 Claims per topic; finer contract-named topics fold into the project-vocabulary topic for the map only (the Claim keeps its label), which removes the 114 one-Claim "missing" nodes the fragmentation had produced.

## G6 — Canonical Works & Source Resolver — 0.31.0 (COMPLETE, pending delivery)

**Built on.** G1 identity (sources stay the possessed objects), G2 `resources.classify` (`work_identity` now covers SOP numbers, IRS publications, statute/CFR citations, form numbers, ISBN, DOI; actions `resolve` → `acquire` → `page` / `upload`), G3 Candidate Index (a cited-but-unowned Work is a `work` candidate with its official location), G4 library recall (owned manifestations before anything external), G5 Claims (independence by lineage; stricter governing sufficiency; version-relationship freshness).

**Model (`works.py`, all global).** `works` (family: kind, title, identifiers, `resolution` stub|resolved) · `work_identifiers` (scheme+value → work, version) · `work_versions` (label, edition, year, effective_date, `supersedes_id`, `change_kind` unknown|supersedes|material|rehost|formatting, `change_note`, status) · `work_manifestations` (source or candidate, typed relation: manifestation_of · reprint_of · translation_of · revision_of · excerpt_of · summary_of · quotes · derivative_of · cites · implements · interprets · possible_manifestation_of; form official|mirror|…; access owned|candidate|unavailable|unknown; confidence + basis) · `project_works` (attached|relevant|targeted|dismissed + reason — never on the Work row). Lineage = `LINEAGE_RELATIONS` (manifestation … derivative); `cites`/`implements`/`interprets` keep their own lineage.

**Resolver ($0, conservative).** `extract_identifiers` (SOP, IRS Pub with tax-year version, U.S.C./IRC/C.F.R. citations, forms, DOI, ISBN with checksum) → `ensure_work` by the frozen signal order (identifier → exact normalized title + creator for non-regulatory kinds → new stub; regulatory kinds never merge on title) → `index_source` (a source whose own metadata/URL names a Work: government host = official manifestation, identifier in the URL path or an uploaded document = mirror, media = derivative_of, any other page that merely names it = quotes) → `cite` (a finding names a Work → stub → `cites` link → owned? relevant : candidate + target "Obtain the authoritative/current manifestation of … (version)" + relevance `targeted`) → `find_copy` (identity, then project → global library → candidates → external only on request; outcomes owned-in-project / owned-attach / candidate / resolved-identity-unresolved-access / unresolved). `version_freshness` reads the version graph: none · unknown · supersedes · material · rehost.

**Claims integration.** `claim_evidence.lineage_id`; `add_evidence` decides independence by lineage first (the first arrival of a Work is a new line; its best PRIMARY manifestation represents the line — official beats mirror beats derivative), wording/creator heuristics only for sources with no lineage; `_primary_gap` adds "the governing primary source (X) is owned but not the evidence here / has not yet been resolved into the project — this Claim rests on a quote" and demotes a governing Strong to Developing; version freshness: unknown/supersedes → needs_refresh, material → stale, rehost → nothing, historical Claims untouched; an unnormalized rule-shaped Claim becomes `governing` once an authoritative primary supports it.

**Surfaces.** `POST /api/works/resolve`, `GET /api/works[/id]`, `POST /api/works/{id}/versions` (the user's explicit statement of how an edition relates — re-assesses affected Claims), `POST /api/works/{id}/link`, `POST /api/projects/{id}/works/{wid}/relevance`; chat tool `resolve_work`; Sources → Library → **Works** (resolve box, versions, owned/seen counts, Add-it-here / Acquire); Health `library.works`. Tier 1 re-frozen 187,030 → 192,504 (HARDENING.md).

**Gate (frozen, tests/test_k8_works.py).** All twelve points of the lock, offline and $0, plus the quote-vs-primary sufficiency test. Suite 348.

**Honest limits.** Model-assisted identity matching (signal 4) is not built — nothing needed it yet, and false negatives are the cheap side; title-only inputs stay unresolved by design. Version graphs are recorded from source metadata (SOP numbers, tax years) and the user's explicit statements — Neuro Search does not diff two PDFs to decide `material` on its own. Books/papers resolve only through ISBN/DOI; a copy still has to be uploaded (no acquisition path for non-official Works).
**0.31.1 — first real-library reading of G6 (business-acquisition project, $0, 12 s to index 449 sources).** 13 Works resolved from source metadata alone: IRS forms (2553, 8832, 1120-S, 1065, 8995, 1041, 1099-DIV, Form 700), IRS Publication 334, 31 C.F.R. § 1031.320, two books by ISBN — 27 manifestation links, most of them `derivative_of` (videos that explain a form), which the first UI rendered as "27 owned" — fixed: Works now show copies *owned* (primary manifestations) separately from sources *discussing* them. "Form 1120S" and "Form 1120-S" had become two Works — form numbers normalize without hyphens. A book resolved by ISBN now takes its title from the owned copy instead of "ISBN …". The resolver's honest answers on this library: **SOP 50 10 8 — resolved identity, unresolved access** (the project's SBA sources are sba.gov programme pages, not the SOP itself; Acquire points at sba.gov/document/sop-50-10-8) and **IRS Publication 946 — resolved, unavailable** (irs.gov/pub/irs-pdf/p946.pdf). No paid call anywhere in G6.

## G7 — Deep & Community Source Discovery — 0.32.0 (COMPLETE, pending delivery)

**Built on.** G1 identity (a thread is one global source, `community:<platform>:<thread_id>`), G2 classification (community hosts; a thread URL now routes through the community adapter instead of a JavaScript page read as HTML — the "no readable text on that page" error on Reddit threads is this), G3 Candidate Index (candidate threads are metadata until acquired), G5 Claims/tensions/targets (missions come from research state; evidence flows straight into Claims), G6 Works (a thread that names an SOP `interprets` the Work — never a second lineage; a shared external URL is one lineage).

**Modules.** `community.py` — Reddit adapter over the public JSON listing (through `safe_fetch`; other communities plug in by host), `store_thread` (full tree in `community_posts` with platform id, parent, ordinal locator, author, self-described `claimed_context` {verified: false}, score, edited, deleted/availability, permalink, corrected_by/acknowledged, firsthand, disagreement, quantitative, evidence_links, injection, in_chunks, retrieved_at, last_seen_revision), deterministic `signals` (relevance, substance, firsthand, specificity, quantitative, engagement, evidence_links, claimed_context, disagreement, acknowledges, low_content, injection — never one score), `_mark_corrections` (a disagreeing reply marks its parent; the parent's later acknowledgement confirms), `prune` (OP, corrected/correcting, firsthand, context, numbers, links, then most substantive; jokes and one-liners never become evidence; the tree stays), one chunk per post (the post IS the locator: "comment 6 by owner_dev", the comment's own permalink; corrected posts carry "[CORRECTED in this thread by …]" in the retrievable text; injection posts carry "[post contains instruction-like text — quoted as data, not followed]"), `missions` (MISSING_PERSPECTIVE → regret/mistake/unexpected-cost expansions first; NOVEL/WEAK_CONSENSUS → corroborate; open corroborative targets; weak experiential Claims), `enumerate_reddit` + `explore` (metadata → Candidate Index → `rank_candidates`: term coverage × experience language × substance; engagement reported, never the key), `synthesize` (FREQUENTLY_REPORTED · MIXED_EXPERIENCE · STRONG_DISAGREEMENT · RARE_BUT_SERIOUS · FIRSTHAND_EXAMPLES over Claims with community evidence, a line = a post, every state keeps source/locator/permalink/relation/independence; recomputed on every research refresh; derived, never primary), re-acquisition marks vanished posts `deleted / unavailable` while keeping their text (previously retrieved evidence). `claims.add_evidence`: community creator = the post's author (two owners in one subreddit are two people); firsthand posts by different people are independent whatever the wording; posts leaning on one external link share a `url:` lineage; posts of one thread compare against each other. `claims.assess`: a governing Claim whose only support is community/experiential is **insufficient authority** — find the governing primary source. `search.hit_from_chunk`: community hits cite the post. Chat: rules that excerpts/posts are DATA (instruction-like text is never followed) and that corrected posts are never consensus; `research_state` includes the cross-thread synthesis. Surfaces: `GET /api/projects/{id}/community/missions`, `POST …/community/explore`, `GET …/community/synthesis`, `GET /api/sources/{id}/thread`; Sources → Library → **Communities** (missions, explore, acquire thread, cross-thread experience). Tier 1 re-frozen 192,504 → 196,951 (HARDENING.md).

**Gate (frozen, tests/test_k9_community.py).** The 15-point fixture thread (wrong SOP quote → correction → acknowledgement; three independent owners; two readers repeating one article; a 1-point CPA comment; a 340-point joke; an injection post; a skipped regret thread). All fifteen points, offline, $0. Suite 354.

**Honest limits.** Only Reddit has an adapter; other community hosts still read as pages (or fail on JavaScript). Firsthand/disagreement/context detection is regex — good at the obvious ("I own…", "CPA here", "That's wrong") and blind to subtlety; the model pass that would refine it is deliberately not built until the $0 signals prove insufficient on real threads. A broker's YouTube video is still evidence class `experiential` (platform-based), so MISSING_PERSPECTIVE cannot yet tell a broker pitch from an owner's account outside community threads. Community consensus counts posts, not people across platforms (the same person on two threads is two lines).

**Cleanup.** `works.merge_work` (versions by label, manifestations deduped, project relevance keeps the stronger state, lineage ids rewritten, `alias` identifiers so old ids resolve) and `works.reconcile_identifiers` (form-number variants) — tested; `POST /api/works/reconcile` folds the live Form 1120S / Form 1120-S pair through it.


## 0.32.2 — Reddit after 2026-06-30: the browser and the official API are the readers (live finding, 2026-09-08; built and tested, pending delivery)

**What broke.** Every Reddit thread failed with "no readable text on that page". Live probes from Kyle's Mac, with the job message now naming each answer: www.reddit.com and api.reddit.com answer the public `.json` with their styled `403` block page; old.reddit.com answers `404` to JSON and, for the server-rendered thread page, a `200` login wall titled "Welcome to Reddit". Web check confirmed the cause: **since June 30, 2026 Reddit requires a login on old.reddit.com and blocks all non-browser clients at the infrastructure level** (datacenter-IP reputation, TLS fingerprint at the handshake, JavaScript challenge) — no header, User-Agent or cookie handshake from a Python client reads a public thread anymore. Kyle's premise ("anyone can view full threads without logging in") holds only for a real browser.

**What changed.** Two legitimate readers, both through the existing G7 acquisition path (`thread_from_listing` → `store_thread`; corrections, locators, synthesis unchanged):
1. **The browser extension** (1.4): "Send this page" on a Reddit thread fetches the thread's `.json` *inside the user's own logged-in browser* (same-origin, real TLS — the reader Reddit serves) and posts it to `POST /api/projects/{id}/ingest/thread`; the app acquires it exactly as a thread it read itself (`representation: browser extension`). Same rule as the Instagram session path: the user's browser is the legitimate reader.
2. **Reddit's official API** (optional): `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `.env` (a Reddit "script" app) → app-only OAuth (`client_credentials`, read-only public data, cached token, one re-auth on 401, 429 surfaced) on `oauth.reddit.com` for both threads and subreddit search — the only way **Explore** works server-side now. Credentials never enter the database.
Order of readings in `read_reddit_thread` / `enumerate_reddit`: official API when configured → public `.json` with an honest `desktop:neurosearch` UA (refused today; free to try) → old.reddit page (`reddit_html.py`, login-walled today; kept with its cookie handshake for the day it is not, and it reads an extension-supplied page). When all fail the error names each and says what to do (extension / .env). Communities UI shows the same guidance when no API credentials exist (`stats.reddit_api`). `safe_fetch`: `body=` for the token POST, a `None` header value drops a default header, every `Set-Cookie` survives.

**Gate.** `tests/test_k9b_reddit_html.py` (9): HTML reading equals JSON reading post-for-post; deleted/edited state; fallback only on refusal; non-thread page reported with its gist; search rows; thread acquired through the page is a full community source; cookie handshake; **extension endpoint** (same global source on resend, 400 on non-thread/malformed); **server-side refusal names the way forward**; **official API** reads a thread and a search with one token and never touches the unauthenticated rungs. Release-check gate. Suite 363. Tier 1 untouched.

**Honest limits.** Explore needs the API credentials; the extension path is one thread at a time, from a tab the user opens. Reddit's API terms allow personal-use reading at 100 requests/minute; nothing here batches beyond one search or one thread per user action. Community hosts other than Reddit still read as pages.

---

# ADDENDUM — Publication Intelligence Track (G6P) — Kyle, 2026-09-08

**Placement.** Not a second Works/Resolver mission: book, EPUB, periodical, article and interview capabilities EXTEND the live G6 architecture. G1–G6 are shipped and frozen under their gate names, so the track is numbered G6P (an expansion of G6's acquisition and manifestation intelligence), sequenced between G6 and G7:

```text
G1 Global Source Identity → G2 Universal Resource Input → G3 Collection Exploration + Candidate Index → G4 Global Library Intelligence
→ G5 Knowledge Map + Claims + Evidence Planning → G6 Canonical Works + Source Resolver
   └── G6P PUBLICATION INTELLIGENCE TRACK: P1 EPUB Core · P2 EPUB Structure + Work Integration · P3 Book Resolution + Acquisition ·
       P4 Periodical / Article Intelligence · P5 Issue Slicer · P6 Interview Intelligence · P7 Work-first Discover + Better-Copy UX
→ G7 Deep + Community Source Discovery → G8 Multimodal Evidence → G9 Recursive Research + Temporal Intelligence + Decision Readiness
```

*(Sequencing note, recorded at filing: G7 0.32.x had already shipped when this addendum arrived; the addendum's "do not start G7 yet" therefore reads as "G6P1 is the NEXT release" — G7 is not reverted; community posts that name books/interviews/articles will resolve them through G6/G6P as §10 says.)*

## 1. What G6 already solved (do not rebuild)
Work family → Work Version/Edition → Manifestations → Global Source. Already established: Work identity; versions/editions; manifestation relationships; supersession/version lineage; evidence lineage; Global Library first; project-relative Work relevance; identifier-first deterministic resolution; ISBN/DOI/regulatory identifiers; owned vs seen vs unresolved states; attach without reacquisition; unresolved identity/access states; explicit acquisition after resolution; Work-aware Evidence Targets; manifestation/evidence independence; basic `resolve_work`; Works UI; Add → Resolve behavior.

## 2. What is genuinely new
A. Native EPUB ingestion (a first-class structured document format, not an opaque ZIP or converted PDF). B. Publication-aware document structure (spine order, chapters, sections, front/body/back matter, native anchors, human-readable citations, images/tables/figures). C. Book-specific acquisition intelligence (G6 identifies books; G6P locates and evaluates obtainable manifestations). D. Periodical hierarchy Publication → Issue → Article. E. Issue slicing (one issue satisfies many article needs without duplicate ingestion). F. Interview intelligence (who was interviewed, who asked, editorial framing, same interview across copies, articles that merely quote it). G. Preferred manifestation / acquisition upgrades (Partial preview → Complete EPUB now available; prefer the better manifestation, keep provenance/history).

## 3. G6P1 — EPUB Core (BUILD NEXT)
EPUB is independently useful; the larger resolver mission must not delay it. Mission: a user uploads an EPUB and Neuro Search treats it as a structured publication. Pipeline: .epub → recognize → validate package → extract publication metadata → read spine → extract structured XHTML → build segments/chunks → index → retrieve → cite chapter/section. Support at minimum: EPUB 2, EPUB 3, reflowable books, nested TOC, missing/weak TOC, non-English content, large books, malformed-but-recoverable packages, encrypted/protected detection. **No DRM circumvention.** Metadata where available: title, subtitle, creator(s), publisher, language, publication date, modified date, identifiers, ISBN, subjects, description, rights, edition/version hints, package identifier — no paid model call for what deterministic parsing recovers. **The spine defines reading order; never process ZIP contents alphabetically.**
**Gate P1.** A valid EPUB can: (1) upload through the ordinary source lifecycle; (2) extract in correct reading order; (3) become searchable; (4) produce findings; (5) answer questions; (6) produce deterministic structural citations; (7) survive retry/restart; (8) use normal provenance/jobs/cost/revision infrastructure.

## 4. G6P2 — EPUB Structure + Work Integration
Exploit EPUB's structure: Book → Front Matter (Preface, Introduction) → Part I → Chapter 1 → Section → Subsection … → Appendix, Notes, Bibliography, Index. Semantic roles where inferable: front_matter / body / back_matter; title_page, copyright, foreword, preface, introduction, part, chapter, section, appendix, notes, bibliography, glossary, index, acknowledgements — roles influence retrieval/findings weighting; low-priority sections are never discarded. Locator: kind epub, spine_index, href, fragment, chapter, section, structural_role (adapted to current locator conventions). Citation hierarchy: prefer "Book · Ch. 3 → Disruptive Technological Change" over synthetic page numbers; fallbacks chapter+section → chapter → content-document title → EPUB section number; citations deterministically map back to ingested content. Deep linking: click citation → chapter/anchor/passage context without re-ingestion. Work integration: Upload EPUB → ISBN/title/creator → resolve Work → resolve Version → create EPUB Manifestation → attach Source; never a second Work G6 already knows.
**Gate P2.** A real EPUB produces: existing Work matched; correct Version/Edition when determinable; EPUB Manifestation; structured chapters; human-readable citations; no duplicate Source acquisition.

## 5. G6P3 — Book Resolution + Acquisition
From "I know this book exists" to "I know which Work/version this is and what legitimate manifestations are available." Funnel: B0 current project → B1 Global Library → B2 existing Work/Version records → B3 structured bibliographic resolution → B4 authoritative legitimate full text → B5 publisher/author/institutional copy → B6 legitimate archive → B7 partial preview/excerpt → B8 user-provided copy → B9 metadata-only unresolved Work. Identity: ISBN-10/13, OCLC, LCCN, Open Library ID, Google Books ID, publisher identifiers — one ISBN identifies an edition/format, not the Work family; preserve that distinction. Providers to evaluate: Open Library, Google Books, Library of Congress, HathiTrust, publishers, author sites, institutional repositories — deterministic/structured/free lookup before web/model reasoning. Completeness states: ACQUIRED_FULL, ACQUIRED_PARTIAL, METADATA_ONLY, USER_FILE_REQUIRED, ACCESS_REQUIRED, NOT_FOUND, RECHECK_LATER — a preview never masquerades as the complete book. Related material (author interview, review, lecture, summary, excerpt) helps research but is not the book manifestation unless it actually is one.
**Gate P3.** exact ISBN → correct edition; another ISBN → same Work, different version; existing EPUB prevents reacquisition; preview remains partial; interview is not a book manifestation; complete EPUB can supersede preview as preferred manifestation.

## 6. G6P4 — Periodical and Article Intelligence
Publication → Issue → Article (Wired → May 1998 → Interview with Jane Doe). Identity: publication, ISSN, publisher, volume, issue, issue date, article title, author, page range, DOI, article type. Reuse G6 Works/versions/manifestations; no parallel magazine database unless a minimal additive helper abstraction is genuinely necessary. Global Library first: wanted Article X + full issue already owned ⇒ locate the article inside the owned issue, never reacquire externally.
**Gate P4.** An article Evidence Target recognizes that an existing issue already contains the needed material.

## 7. G6P5 — Issue Slicer
ONE ISSUE SOURCE → Article A, Article B, Interview C, Review D — article-level research units without duplicating the asset. Boundaries from TOC, headings, page ranges, bylines, known article metadata, layout/structure, title matching — deterministic and text/layout-based first; G8 improves scanned magazines later. **Critical evidence rule: parent issue + sliced article are not independent corroboration — shared lineage.**
**Gate P5.** issue identity; article identity; article range; parent/child relationship; article-granularity retrieval; no file duplication; no evidence double counting; the same article reprinted elsewhere retains correct lineage.

## 8. G6P6 — Interview Intelligence
Interviews are specialized first-person evidence. Identity: interviewee, interviewer, publication/show, date, headline, alternate headline, issue, page range, DOI, text fingerprints. Resolve the same interview across print issue, publisher HTML, transcript, archive scan, authorized reprint, excerpt, quoting article — with the G6 relation vocabulary (exact, reprint, excerpt, derived, related). Speaker structure where reliable: EDITORIAL INTRO / INTERVIEWER question / INTERVIEWEE answer; evidence retains speaker attribution — "CEO said X" never collapses into "journalist says CEO believes X". Claimed vs known speaker: never infer identity the structure does not establish.
**Gate P6.** interviewee attribution; interviewer attribution; editorial text separated; exact reprint recognized; excerpt recognized; derivative article recognized; a related later interview stays distinct; an alternate headline resolves the same interview.

## 9. G6P7 — Work-first Discover + Find a Better Copy
Discover surfaces WORK CANDIDATES (title, creator, why it matters, resolution: "Complete EPUB already in Global Library" / "Article located in full issue already owned, pp. 41–47") rather than bare URLs. Never block Discover: show immediately → resolver works asynchronously → availability fills in. Universal action "Find a better copy" for any Work/version with poor or missing access (metadata only → full copy; preview → complete; poor OCR → publisher HTML; excerpt → original interview). Manifestation upgrade keeps both manifestations and history; marks the better research manifestation; never deletes provenance.
**Gate P7.** Discover suggests a Work immediately, progressively resolves manifestations, reuses existing assets, and upgrades the preferred manifestation without corrupting lineage.

## 10. How G6P connects to the ladder
G2: recognition covers .epub, book catalog URL, periodical issue, article, interview — EPUB works everywhere documents work. G3: metadata preserved for unacquired books/editions/articles/interviews/issues. G4: Library Recall understands "article requested + issue owned = existing evidence candidate" and "book requested + different usable manifestation owned = reuse before acquisition". G5: partial book ≠ full-book coverage; issue + article never count twice; Claims distinguish interviewee statement / editorial statement / interviewer assertion; reprints, excerpts and derivatives never inflate corroboration. G7: community posts naming books/interviews/articles resolve them through G6/G6P rather than becoming independent evidence for what those Works say. G8: G6P preserves EPUB images, SVG, captions, tables, figure location, surrounding text now; G8 interprets later ("preserve now, interpret more deeply in G8"). G9: preserve footnotes, bibliographies, citations, references, named Works for the Reference Graph — no uncontrolled recursive acquisition during G6P.

## 11. Execution order
G1–G6 DONE → **G6P1 EPUB Core NEXT** → G6P2 → G6P3 → G6P4 → G6P5 → G6P6 → G6P7 → G7 (shipped 0.32.x) → G8 → G9.

## 12. Why here
G8 answers "can Neuro Search understand visual evidence?"; G6P answers "what publication am I looking at, what structure does it have, which copy/version do I possess?" — resolver and ingestion concerns, directly after G6. EPUB is a structured textual publication format with optional visual assets; its structure is used before multimodal analysis exists.

## 13. Source hierarchy extension
Books → Author → Work → Edition/Version → EPUB/PDF/Preview; Periodicals → Publication → Year → Issue → Article; Interviews → Interviewee → Publication/Program → Interview. Not hardcoded if the hierarchy abstraction expresses it generically; the capabilities that matter: filter, browse, re-resolve, re-ingest, inspect, attach, analyze, find better manifestation.

## 14. Recurring G6P platform gates (every sub-rung)
Global identity (reuses G1/G6) · Work identity (attaches to the existing Work/version) · Global Library first · Candidate memory · Completeness (partial vs complete) · Lineage (reprints, excerpts, issue children, derivatives never inflate corroboration) · Provenance (exact evidence location) · Citation quality (publication-native locator) · Durable ingestion (normal jobs) · Cost (deterministic before paid) · Rights (legitimate access, no DRM circumvention) · Evidence boundary (resolved/unacquired manifestations are non-evidence until acquired and attached).

## 15. Publication Intelligence acceptance project (one integrated fixture)
Book Work → 1997 Edition → EPUB manifestation; Periodical → Issue PDF → Interview article; authorized web reprint of the interview; later article quoting it; partial book preview; complete uploaded EPUB. Must prove: (1) EPUB enters normal ingestion; (2) spine order correct; (3) metadata resolves the existing Work; (4) book version separate from Work family; (5) chapter/section citation stable; (6) partial preview remains partial; (7) complete EPUB becomes preferred; (8) issue reused, not reacquired; (9) article addressable inside the issue; (10) issue + article not independent evidence; (11) authorized reprint resolves correctly; (12) derived article ≠ the interview; (13) editorial text not attributed to the interviewee; (14) interviewee statements keep speaker provenance; (15) Global Library checked before every acquisition; (16) all new work on normal jobs/provenance/cost/revision/release infrastructure.

## 16. Immediate direction
The next release is **G6P1 — EPUB Core**: independently useful, deterministic enough to build safely, needed for serious book acquisition, directly compatible with G6, independent of G7/G8/G9. After G6P1 is proven with a realistic EPUB, continue through the sub-ladder. The transition: G6 "Neuro Search knows what Work this is" → G6P "Neuro Search understands publications deeply enough to acquire, structure, cite, compare, and reuse the best manifestations of that Work."


---

# ADDENDUM — Browser-assisted acquisition + Community cataloging (Kyle's mission, Parts A–Q, 2026-09-08)

*Filed in condensed form; the architectural recommendation and phased ladder (B1–B7) are in `BROWSER-CAPTURE-AND-CATALOG.md`.*

**Premise.** Server-side Reddit access is unreliable (see 0.32.2). Keep both server paths (JSON/API-style fetch with an honest UA; server-rendered HTML parsed into the same normalized thread). Extend so Neuro Search can: use the user's real Chrome as an acquisition node when the backend fails; catalog large communities without ingesting every thread; remember useful threads globally before capture; associate uncaptured threads with Projects, Claims, Gaps, Discover results and future needs; rank cataloged threads so only the small useful percentage is captured; re-scan communities for new/newly relevant discussions; generalize to other blocked, authenticated, paywalled or JavaScript-rendered sources.

**A — Third acquisition path, browser capture.** JSON → server HTML → browser (Chrome extension → normalized payload → existing parser/indexing). Chrome is the acquisition *environment*, not a proxy for the same HTTP request: the content script inspects the rendered page and emits structured content (`reddit_thread_capture`: thread {reddit_id, canonical_url, subreddit, title, author, body, score, created_at, edited, deleted, permalink}; comments {reddit_id, parent_id, depth, author, text, score, created_at, edited, deleted, permalink}) feeding the SAME normalized tree; no separate search semantics.
**B — Capture completeness.** Rendered pages may lack comments (collapsed, "more replies", lazy branches). Never present partial as complete: `capture_status` complete/partial/unknown, visible/captured counts, unloaded/collapsed branches, reason, captured_at; keep the thread's reported comment count separate from captured; UI "184 captured, thread reports 213, 29 may not be loaded". No anti-bot automation.
**C — Cataloging ≠ acquisition.** Knowing a source exists vs possessing its contents. A Target = known location + thin metadata, capture_state uncaptured/queued/captured/unavailable, relevance + reason, nullable source_id (and work_id only if Works fit).
**D — Large subreddit cataloging.** Extension *Scan Subreddit*: thin metadata from listing/search cards (id, permalink, title, subreddit, author, date, score, comment count, flair, snippet, outbound link, surfacing listing, timestamp), batched, stable ids, UPSERT (score 621→784, comment_count 94→137, last_seen updated).
**E — Coverage, not exhaustiveness.** Coverage dimensions: recency (7/30/90 d, 1 y), popularity (top day/week/month/year/all), project-driven search terms; a subreddit is a dynamic container/catalog ("18,421 known · 137 captured · 42 attached · coverage table current/stale").
**F — Project-aware probes** from brief, questions, context, Claims + freshness, Gaps, Findings, planner questions, Facts, Discover history — a generalized mechanism, no hardcoded terms.
**G — Rank before capture.** Signals: semantic relevance, gap match, claim-needing-evidence match, novelty vs owned sources, comments, score, recency, title specificity, flair, disagreement potential, diversity; review like the YouTube workflow (Critical / High / Potential / Low; capture selected); learn from selections later if clean.
**H — Gap/Discovery memory.** Uncaptured Targets stay attached to Gaps ("92 — Bought a CPA practice… r/accounting · 438 comments · uncaptured") with a Capture action; relate Targets to gaps, claims, discoveries, projects, Works, source families, planner needs without duplicating across tables.
**I — Global Target library.** Same canonical Target across projects; capture in one project benefits others under global-library rules; do not force discussions into Works.
**J — Re-scanning.** Cursors/state, last_scan, coverage records, dedupe, update semantics, stale detection, project-search freshness; scheduling later.
**K — Generalize** (AcquisitionAdapter: Http / BrowserCapture{Reddit, GenericRenderedPage, Course, authenticated}; CatalogAdapter: RedditCommunity, YouTubeChannel, PodcastFeed, Website, Publication) without a plugin framework for elegance.
**L — Source model.** Containers → catalog → Targets (thin) → ranking → acquisition (HTTP | browser) → Source → chunks → evidence (Subreddit/thread; channel/video; podcast/episode; website/page; publication/article; book catalog/edition; course/lesson) — evaluate against what exists first.
**M — UX.** "Add Reddit Community" → Map this community (recent · top · project-relevant; metadata only; nothing downloaded automatically) → container view (known / captured / relevant / recommended / new since last scan; Review · Find gap evidence · Scan for updates) → review with Capture selected; a captured Target becomes a normal Source.
**N — Safety.** No CAPTCHA defeat, impersonation, identity rotation, protection bypass, or hidden mass tabs; the user's browser captures what the user can legitimately access; catalog and rank so few captures are needed.
**O — Cost.** Staged: metadata + deterministic filters ($0) → lexical/heuristic ($0) → embeddings/batch AI only for plausible candidates → browser acquisition only selected → extraction only acquired; global library first.
**P — Relationship to current work.** Thread ladder: already captured globally? attach → structured fetch → server HTML → requires_browser → capture queue → extension → normalize → Source. Community path: catalog listings → Targets → rank vs Project/Gaps/Claims → attach / server acquire / browser capture.
**Q — Browser-assisted recovery and guidance.** Never leave "403 / Failed" when the browser can solve it: acquisition outcomes ready / failed / retryable / requires_browser / requires_login / partial_browser_capture / unsupported; adapter-aware detection (401/403, challenge, login wall, JS-required, empty render, session content, Reddit failure, partial capture); user-facing "Browser needed — [Open & Capture]" with details behind a control; extension presence (ready / last seen / not detected) via a lightweight heartbeat if practical, with setup guidance; a persistent Browser Capture queue ("5 sources need your browser", 1 of N guidance, partial accept/reopen, auto-advance); guidance wherever the problem originates (source/job failure, Discover, Target review, Gaps/Claims, Chat when materially relevant, community view); proactive but suppressed reminders (first/last notified, dismissed_until, priority); one-click recovery with capture identity passed to the extension so the result resolves the original job/Target/Source; a pending `browser_capture_request` (request_id, project, target, source, canonical_url, adapter, capture_kind, reason, status pending/opened/capturing/captured/partial/cancelled/expired) — jobs if they fit; extension-side "Neuro Search wants this page — Project · Reason — [Capture]" on user action only; an acquisition resolver that records why a path was chosen; an adapter capability model (http / structured_api / server_html / browser_rendered / browser_session / manual_upload) only if it simplifies; browser-required work survives restart. Release gates (14): browser-solvable failure → requires_browser not failed; stays associated with its project; capture resolves the SAME pending Target/Source; survives restart; non-browser-solvable failure stays failed; JSON → HTML → browser fall-through; successful JSON/HTML never asks for Chrome; partial stays visibly partial; canonical identity preserved; already-acquired sources bypass browser; recommendations appear in API/UI state; multiple pending captures as a queue; Gap/Claim-linked Targets stay linked until acquired or dismissed; no cookies/session material in normal responses. UX acceptance: a nontechnical user recovers a blocked thread without knowing the architecture.

**Requested before implementation.** Inspect the code; deliver the architecture + revised ladder (20 questions, phased B-ladder with mission / behaviour / schema / backend / extension / UI / tests / gate / non-goals / dependencies) and identify pieces of the current Reddit work completable safely now. → `BROWSER-CAPTURE-AND-CATALOG.md`.

---

# BROWSER ACQUISITION TRACK — LOCK (Kyle, 2026-09-08)

**Framing.** Browser Capture is a **cross-cutting acquisition track (B)**, not a main research rung: when legitimate server-side acquisition fails but the user can access the material in their browser, Neuro Search hands acquisition to the user's authorized browser session and receives a structured capture back through the normal source lifecycle — foundational for Reddit, logged-in communities, courses, publisher pages, subscription content, JavaScript sites, and G6P book/article/interview resolution. The Reddit premise is validated (Reddit's 2026-06-30 login requirement for Old Reddit's logged-out experience, enforced server-side; developers pushed to authenticated API paths). The two server paths stay as best-effort alternatives, never dependable acquisition.

**Decision 1.** Deliver 0.32.2 now (restart approved).

**Decision 2 — sequence.** G6 → **B1 Browser Capture + Recovery → B2 Completeness + Capture Queue** → G6P1 EPUB Core → G6P2 → G6P3 → G6P4 → G6P5 → G6P6 → G6P7 → **B3 Candidate Links / Gap Recall → B4 Community Containers + Scan → B5 Staged Ranking + Review → B6 Re-scan / Freshness / Attention → B7 Second-platform generalization** → G7 (shipped) → G8 → G9. B1/B2 first because they are small platform primitives that remove a production blocker and benefit G6P; B3–B7 must not delay EPUB.

**Locked design rules.** (1) G3 Candidates are the single "known but not acquired" abstraction — no `targets` table; durable candidate relationships (project, Evidence Target, Claim, Research Tension, Discover mission, Planner dependency) instead. (2) `requires_browser` is a **generic capability state**, derived from classified acquisition failure (`sources.error_class`), never a Reddit state; browser work uses the existing durable `external_pending` job system (provider=browser) → extension capture → normal source lifecycle; later reused by publishers, courses, forums, archive viewers, authenticated documentation. (3) Same-origin structured capture is the preferred browser producer where legitimately available; rendered-DOM extraction is the fallback; **both emit one canonical capture contract (`reddit_thread_capture`) and only the server normalizes** — never two pipelines. (4) B2: a successful capture and a complete capture are different states; preserve expected/captured/missing counts, collapsed branches, load-more remaining, deleted count, capture method, timestamp, partial reason as first-class provenance, so G7 synthesis never says "most commenters agree" over 37 of 412 comments.

## B1 — Browser Capture + Recovery — 0.33.0 (COMPLETE, pending delivery)

**Built on.** 0.32.2 (`thread_from_listing`, `/ingest/thread`, the official-API and best-effort server readings), the durable job system's `external_pending` state (Mission D), G1 identity, G3/G7.

**Modules.** `acquire.py` — the capability table `ADAPTERS` (reddit_thread: structured_api → public_json → server_html → browser_rendered; web_page: http → browser_rendered; document/youtube: never the browser) with the failure classes each adapter calls browser-solvable; `AcquisitionFailure(adapter, cls)` with `browser_solvable` decided by that table, never by a status code; `classify_page` (401/403/429/503 → blocked/challenge; 404 not_found; 200 walls → login_wall/challenge; thin renders → js_required); `park_for_browser` (the SAME ingest job → `external_pending`, provider `browser`, kind `capture:<adapter>`, handle = canonical URL, 14-day deadline; a pending placeholder source with the identity the capture will resolve to, `error_class` = `browser_solvable:<cls>`, a plain-language `error`; `payload.capture` = adapter/kind/reason/why); `BrowserCapture` external handler (nothing to poll; expiry never fails the job — it is listed as expired until the user acts); `pending_captures` / `pending_by_source` / `request_for` / `resolve_capture` (→ `db.resume_external`: the job re-runs with `_external_result.capture` through `ingest.ingest_url(capture=)` and completes the same source) / `cancel_capture`; `heartbeat` + `extension_status` (ready < 10 min / stale / not_detected, kv only); `attention(project)`. `community.thread_from_capture` = the `reddit_thread_capture/1` contract (thread + comments + capture diagnostics; a raw `listing` still accepted) → the one thread dict; `acquire_thread(capture=)`; Global Library first: when the server cannot read a thread that is already owned, it is attached, never sent to the browser (a refresh still re-reads whenever the server can). `webpage.Blocked` is now an `AcquisitionFailure`; a 200 that is a sign-in/verification wall or an empty render is classified too. `jobs.execute`: a browser-solvable `AcquisitionFailure` on an `ingest_url` job parks it (event `requires_browser`) — before the transient-retry logic, never after a capture has already been delivered. API: `GET /api/capture/pending[?project_id&url]`, `POST /api/capture/{job_id}` (contract or listing or html), `DELETE /api/capture/{job_id}`, `POST /api/extension/heartbeat`, `GET /api/projects/{id}/attention`; `/api/sources` rows carry `acquisition {state: requires_browser, job_id, reason, status, url}`; `/ingest/thread` and `/ingest/html` resolve a waiting request for that URL instead of a parallel acquisition. **Extension 1.5:** `background.js` (heartbeat every 5 min; the pending list → badge: blue dot on a wanted tab, count elsewhere; nothing captured without a click), popup "Neuro Search wants this page — Project · reason — [Capture for Neuro Search]" with the project pre-selected, the queue's next item, and the contract producers (`redditCapture`: same-origin JSON first, rendered DOM — shreddit/old — as fallback with captured/expected/load_more counts; `pageCapture`: rendered HTML). UI: Sources → **Browser capture** card (N of M, Open & Capture, Cancel, extension state), the source card's *Browser needed* block (reason in plain language, Open & Capture / How this works / Cancel; status codes only in the job history), a 🌐 filter chip, jobs list label.

**Gate (tests/test_l1_browser_capture.py, 9).** Part-Q gates 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 14: blocked thread → `requires_browser` with the JSON/HTML attempts recorded; source stays in the project; the capture resolves the same job and source after a "restart"; the unsolicited extension send resolves the waiting request; a 404 and a document adapter stay ordinary failures; a successful reading never asks for Chrome; an owned thread bypasses the browser; a blocked publisher page becomes a page capture and completes through the generic path; login-wall / JS-only classification; heartbeat and cancel. Suite 372. Release-check gate added.

**Non-goals (B2).** Completeness as first-class provenance (`sources.completeness` column exists, unused), merge-on-recapture, the guided 1-of-N walk with auto-advance, "Accept partial / Reopen and capture more".

## B2 — Completeness + Capture Queue — 0.33.1 (COMPLETE, pending delivery)

**Principle (Kyle's lock).** A successful capture and a complete capture are different states. `community.completeness(thread)` is deterministic provenance recorded on the source (`sources.completeness` JSON): `status` complete / partial / unknown, `captured` vs `expected` (the platform's count — which includes removed comments, so a small shortfall ≤ max(5, 10 %) is `complete` with `missing` recorded, a large one is `partial`), `load_more_remaining` + `unloaded_count` (Reddit's `more` stubs in a JSON/API listing; the DOM producer's count of unexpanded branches), `collapsed`, `deleted`, `method` (json / dom / reddit api), `captured_at`, `partial_reason`, `accepted`. Never `complete` by default: no count reported → `unknown`. The source description carries "N of ~M comments captured"; `/api/sources`, `/api/sources/{id}` and `/api/sources/{id}/thread` carry the record; the UI shows *⚠ Partial capture: 184 comments captured, the thread reports ~213 · 29 may not be loaded* with **Accept partial** (`POST /api/sources/{id}/accept-partial` — sets `accepted`, never `complete`) and **Reopen and capture more** (`POST /api/sources/{id}/recapture` — a forced re-read: server first, the browser when the server cannot; the SAME source, one waiting request at a time). **Merge rule:** a partial capture never deletes what an earlier reading saw — previously known posts keep their rows and ordinal order (evidence locators stay valid), new posts append; only a complete reading marks vanished posts `unavailable` (G7 semantics kept); a merge that reaches the platform's count becomes complete. **Queue walk:** the Browser capture card shows *Next — 1 of N* with Open & Capture / Skip, polls every 5 s, reports each landed capture (✓ complete · partial with Accept/Reopen · error) and advances by itself; expired requests say "open and capture again". G7 synthesis therefore never speaks over a thread it only partly holds without the partial state being visible on the source.

**Gate (tests/test_l2_completeness.py, 6).** `more` stubs → partial with counts and reason; a small shortfall stays complete with the gap recorded; a partial browser capture stays visibly partial and Accept keeps it partial (Part-Q gate 8); a partial capture merges and never deletes what was known, then reaches complete; a complete reading after a partial marks a vanished post unavailable while keeping its text; three requests form an oldest-first queue that advances (gate 12), Reopen re-requests the same source, never a duplicate. Suite 378. Release-check gate added.

**Next.** G6P1 EPUB Core (the Browser Acquisition Track pauses here by decision; B3–B7 resume after G6P).

## G6P1 — EPUB Core — 0.34.0 (COMPLETE, pending delivery)

**Built on.** G1 identity (an upload's content fingerprint), the document pipeline (segments/chunks/embeddings, `build_doc_chunks`), G6 Works (`ensure_work` / `ensure_version` / `link_source`), the 0.32.2 tolerant HTML tree (now `htmltree.py`, shared with `reddit_html`).

**Modules.** `epub.py` — `is_epub`, `read_epub(path)` (stdlib only, $0): container.xml → OPF (falls back to scanning for an .opf when the container is missing or unreadable), `read_metadata` (title + subtitle by `title-type` refines, creators, publisher, language, date, `dcterms:modified`, identifiers with scheme incl. `urn:isbn:` / `opf:scheme` / `identifier-type`, ISBN, subjects, description, rights, package id, an edition hint, EPUB version), manifest + **spine** (reading order — never the ZIP's file order; non-linear items kept and marked), TOC from the EPUB 3 nav document or the EPUB 2 NCX (nested; a missing TOC names chapters from their headings with a warning), **protection detection** (`META-INF/encryption.xml` referencing a content document → `EpubProtected`, refused, no circumvention; encrypted fonts alone are fine), content documents → `_sections_of` (split at h1–h4 with the heading's or the nearest preceding `id` as the anchor; paragraphs, lists, block quotes, captions, table cells; scripts/styles/nav skipped; tiny heading-only fragments fold into the next section), semantic roles from `epub:type` or the title (title_page, copyright, foreword, preface, introduction, part, chapter, appendix, notes, bibliography, glossary, index, epilogue, prologue, acknowledgements), a large-book bound (`MAX_SECTIONS`). `locators(book)` → ordered sections with `label` = **"Ch. N → Chapter · Section"** (N = the TOC's top-level order; without a TOC the heading alone). `ingest.ingest_epub` (routed from `ingest_local_file` on `.epub`, so uploads, the chat's attach button and the ingest job all take it): platform `book`, transcript_kind `epub`, one segment per section, **chunks never cross a section** (the locator stays exact), `book_sections` table (ordinal ↔ spine index / href / fragment / chapter / chapter_no / section / role / depth / label), source metadata (title with subtitle, creators as channel, date, language, description "EPUB 3 · 5 chapters · 6 sections · publisher · ISBN · edition"), `completeness` complete. **Work integration ($0):** ISBN → `ensure_work("book", …)` on the existing Work (or exact title + creator when there is no ISBN), an edition/year version when determinable, `link_source(relation manifestation_of, form epub)` → access `owned`; never a second Work G6 already knows. `search._book_locator` / `locator_for`: hits, findings citations, the transcript view and `transcript.txt` all cite the structural label with the anchor as the deep link (`url#href#fragment`). `/api/sources/{id}` carries `sections`.

**Gate (tests/test_m1_epub.py, 6 — the P1 eight points).** Synthetic EPUB 3 and EPUB 2 packages whose ZIP names sort in the wrong order: (1) upload through the ordinary lifecycle, (2) spine order, (3) searchable (English and Spanish sections), (4) findings via the normal extraction with structural citations, (5) answers citing "Ch. …", (6) deterministic locators with anchors, (7) the same bytes are the same source with unchanged locators, (8) normal infrastructure; plus EPUB 2 NCX, missing TOC + broken markup recovered with warnings, protected book refused, ISBN → existing Work (one Work, one owned copy per source; title + creator without ISBN → the same Work), the immediate upload endpoint. Suite 385; Tier 1 untouched.

**Honest limits.** Images, SVG, tables and figures are preserved only as their text (captions and cells) — G8 interprets them; footnotes/bibliographies are sections (roles `notes` / `bibliography`), not yet a reference graph (G9); deep links point at the anchor inside the package, there is no in-app EPUB reader yet (P2). Fixed-layout and image-only EPUBs read as "no readable text".

## 0.34.1 — three live findings (2026-09-08)

1. **EPUB not selectable in the uploader** — the Sources file input's `accept` list lacked `.epub` (the ingest path was live since 0.34.0). Fixed; the chat attach button never filtered.
2. **Extension capture message in red** — the popup coloured the "Partial: 8 of ~16 comments" note as an error. A capture is a success; the shortfall against Reddit's count is usually deleted comments (still counted), so the note is now neutral ("Reddit counts 16; the difference is usually deleted comments") and only a large shortfall or unexpanded "more replies" branches show as an amber *Partial* with the way to add the rest. Extension 1.5.1.
3. **"You have reached your specified API usage limits. You will regain access on 2026-10-01"** — Anthropic Console's *account* usage limit (not Neuro Search's budget), now delivered as a 400 `invalid_request_error`, so it classified as INVALID_REQUEST and every AI job failed after one attempt. `providers.classify_error` maps it to SPEND_CAP and `spend_cap_until` reads the date; `jobs.execute` parks such jobs `budget_wait` until then (0 attempts, $0) with one message that says what to do (raise the limit in the Console); `/api/usage` carries `account_limit_until` and the header shows the pause. Until the limit is raised — or the local provider below exists — no AI work can run.

## 0.34.2 — "failed sources keep showing up" (2026-09-08)

**Cause.** *Remove from project* deleted the `project_sources` row, but membership is also derived from linked collections (playlists/channels/explored sites) and project tag matches, and a retried or queued ingest job recreates a deleted source row under the same identity — so the source reappeared as failed after every remove or delete. **Fix.** Removal is now a durable **exclusion** (`project_sources.excluded`, additive): `project_source_ids`, `projects_for_source`, identity's ALREADY_IN_PROJECT and the Candidate Index all honour it; an explicit add lifts it. **Force-clear:** Sources → Failed → *✕ Clear all failed* (`POST /api/sources/clear-failed-in-project`) cancels every job that could recreate them (queued / running / browser-parked, by source id or URL), excludes them from the project, and deletes the row outright when no other project holds it, it never produced content, and nothing cites it. Gate in `tests/test_l1_browser_capture.py`. **Also fixed:** findings extracted from a community thread had no citation (the "post N" locator was not parsed back), so the Findings view grouped them under "Untitled source"; they now cite the post with its permalink (`tests/test_l2_completeness.py`).

---

# ADDENDUM — Neuro Search Local-First AI Policy (Kyle, 2026-09-08)

**Policy (verbatim intent).** All eligible AI work on a local Neuro Search installation is processed through the local **Claude Code** provider by default. The Anthropic API remains fully supported as an automatic reliability fallback and as user-authorized burst capacity for workloads where faster completion is worth additional cost. Provider choice must not alter application behavior, persisted data, task semantics, or output schemas. The same provider abstraction must allow a future cloud deployment to use the Anthropic API as its primary AI runtime without rewriting the feature layer.

**Architecture.** `AIService` (task contracts) → `ProviderRouter` → `ClaudeCodeProvider` (local default) | `AnthropicAPIProvider` (secondary) → standardized result → jobs / chat / findings / planner. Rule: *if Neuro Search runs locally and Claude Code is healthy, Claude Code does the work* — chat, Discover, findings, ranking, Planner, gap analysis, summaries, claim analysis, refresh. The API takes work only on (1) **fallback** — Claude Code unavailable, erroring, at a usage limit, or unable to perform the operation; (2) **user-authorized acceleration** — a visible backlog with an offer ("37 items remaining · Claude Code is processing locally · [Speed up with API] ≈ $2.40" → keep local / next 10 ≈ $0.64 / next 25 / finish backlog; relevance can pick what accelerates). *Busy ≠ unavailable*: busy is the user's choice to buy time; unavailable falls back automatically. Chat is Claude-Code-first too ("Local AI is busy — [Wait] [Answer now with API ≈ $0.03]"). The worker is a **dedicated, isolated, non-interactive Claude Code session** with structured output and no repository access — an inference provider, never the developer. Features never know Anthropic exists (`ai.complete / complete_structured / agent`). Two independent AI worker pools (local AI workers; API burst workers normally idle) beside the general workers; jobs carry `execution_policy` (local_only | local_preferred | api_requested | api_only), fallback recorded separately from intent. Usage splits into Claude Code usage (tasks, capacity, subscription, estimated avoided $) and API usage (tokens, cache, actual $, budget valve — now the overflow control); the satisfying metric: "2,184 AI tasks · 93.0% local · $14.62 actual · $169.69 avoided". Deployment profiles: LOCAL (SQLite, local files, user's browser, Claude Code + API overflow) and CLOUD (managed DB, object storage, extension/client, API primary) share projects, sources, findings, claims, planner, jobs, prompts, schemas, UI and API — provider-independent, not a "Claude Code edition".

## Assessment (Claude, same day)

**What already holds.** The feature layer is already provider-blind: every model call goes through `providers.invoke` / `invoke_structured` against an `InferenceContract` (contracts.py, `NO_FALLBACK`), with the ledger, breakers, retries, schemas + clamp/repair, usage guard and the durable job queue around it. So this is a second provider plus a router and a policy — not a refactor of findings/planner/qa/discover. The `NO_FALLBACK` rule (no silent *model* substitution) stays: the router substitutes the *provider* under a stated policy and records it on the artifact's `routing_json`, which is what that rule was protecting.

**How Claude Code is driven.** Headless `claude -p` (non-interactive; JSON output; tool allow-list; max turns; an MCP config) run by a dedicated local AI worker pool with a scratch working directory, no repo, and only Neuro Search's own MCP server allowed — the isolation boundary Kyle asked for. Structured tasks (findings.extract, rank.relevance, planner.update, discover.quick, claims.extract, library.profile, summaries) map directly: the same prompt, the same schema, the same clamp/validate/repair path on the returned text. Chat maps in two steps: answer-only first (the retrieval and the state block are ours; the CLI generates), then the tool loop through the existing MCP server (`search_library`, `list_sources`, `record_fact`, …) so citations keep their numbering. Streaming via the CLI's stream-json output.

**Two honest caveats to decide with eyes open.** (1) Claude Code inference draws on the *same subscription allowance* as these development sessions (the weekly limit we are budgeting right now); the API avoided-spend metric is real, but the local capacity is not free — it is time-shared with building Neuro Search, and the models differ (the subscription's models vs. the contracts' pinned `claude-sonnet-5` / `sonnet-4-6`, so routing_json must say which actually ran and Tier 1 must be re-frozen per provider). (2) Anthropic's terms for Claude Code cover the user's own interactive/agentic use; running it as a background inference engine for an application is a use to check against the current terms before it becomes the default — the design keeps the API path fully intact so nothing depends on the answer.

**Phases (cheapest coherent cuts).** **L1 Provider + router + policy (≈6–8 points incl. live verification on the Mac):** `providers.ClaudeCodeProvider` (health probe, `-p` invocation, JSON/stream parsing, usage-limit detection → typed error), `ProviderRouter` with `execution_policy` on jobs (default `local_preferred`; fallback recorded as `executed_by` + reason), the local AI worker pool, Health/Jobs banner ("Claude Code: ready · 3 running · 26 waiting"), fake `claude` binary for tests, doctor check; structured tasks only, chat stays API until L2. **L2 Chat on Claude Code (≈4):** answer generation via the CLI with the MCP tool loop; streaming; "Answer now with API" offer. **L3 Speed up with API (≈4):** backlog detection, cost estimate from the ledger, the acceleration dialog, relevance-picked acceleration, `api_requested` jobs to the burst pool. **L4 Usage split + avoided-spend metric + cloud profile switch (≈3).**

**Sequencing given the week.** With the Console limit reached until 2026-10-01, no AI work runs today whichever rung we build next; raising the Console limit is the zero-cost unblock. L1 is the highest-leverage engineering left this week and fits the remaining budget only if nothing else is started; G6P2, Share ▾ and B3 move to next week in that case.

## Queued: Research tab redesign (Kyle, 2026-09-08)

The Research tab is confusing and overwhelming as built (0.29–0.34). A handoff document for a dedicated redesign session — intended use, the five objects and the loop, an honest diagnosis of why it overwhelms, a starting redesign position, and the architecture/invariants the redesign must keep — is `RESEARCH-TAB.md`; Kyle's full mission (north star, locked invariants, Overview/Questions/Knowledge hierarchy, prioritization engine, Open Questions, Watch-outs, Research Areas, Claims workbench, decision semantics, hidden instruments, sidebar count, cross-product entry points, ladder R1–R12, 22 acceptance criteria) is `RESEARCH-MISSION.md`. Placement in the ladder: a UX rung on G5's surface, independent of G6P/B tracks; no schema change expected.


## Handoff plan when Fable credits run out (Claude, 2026-09-08)

The repository is the handoff: `CLAUDE.md` (architecture + standing rules), `EXPANSION.md` (every lock, addendum and rung log), `HARDENING.md` (frozen numbers and why), `BROWSER-CAPTURE-AND-CATALOG.md` (B-track), `RESEARCH-TAB.md` + `RESEARCH-MISSION.md` (Research rebuild), the gates under `tests/`, and `evals/release/`. A new session on another model should start by reading CLAUDE.md, the mission it is assigned, the tests that gate that area, and running the suite — not by re-reading chat transcripts. **Best fits for a fresh Opus session** (fully specified, deterministic, gate-protected, little live iteration): the Research rebuild R1–R12; G6P2 EPUB Structure + Work Integration; Share ▾ portable-answer variants; B3 Candidate links / gap recall; G6P3 book resolver (needs live provider probing — expect iteration). **Keep on the session with continuity, or write a more detailed note first:** L1 Claude Code provider (judgement about the `claude` CLI on the Mac, subscription-sharing caveat, routing_json/Tier-1 implications); anything touching frozen Tier 1 prompts; B4 community scanning (extension + live Reddit). The delivery ritual, the reading order and Kyle's working rules are in `HANDOFF.md`; the Claude Code provider rung is specified in `LOCAL-AI-PROVIDER.md`.

## G6P2 — EPUB Structure + Work Integration — 0.35.0 (COMPLETE, pending delivery)

**What P1 already carried.** Chapter/section hierarchy with anchors, semantic roles from `epub:type` and titles, "Ch. N → Chapter · Section" citations with a fallback chain (chapter + section → chapter → content-document title → section number), Work resolution by ISBN or title + creator with an edition/year version and an `epub` manifestation on the existing Work, no duplicate acquisition.

**Built in P2.** (1) **Roles influence weighting, nothing is discarded:** `epub.ROLE_WEIGHT` (body/chapter/part/introduction 1.0 · preface 0.9 · epilogue 0.9 · foreword 0.8 · appendix 0.85 · notes/glossary 0.7 · bibliography 0.5 · index/acknowledgements 0.3 · copyright/title page 0.2); `search.search` multiplies a book chunk's fused score by its section's weight, so an index page that repeats a chapter's words never outranks the chapter but stays retrievable; `findings._windows` skips `SKIP_FOR_FINDINGS` (index, copyright, title page, acknowledgements — never worth a paid window) and orders body before back matter. (2) **Deep linking without re-ingestion:** book citations everywhere (search hits, findings, chat, research) link to `#book/<source_id>/<ordinal>`; one document-level handler opens the in-app reader at that section. (3) **The reader:** the source's 📖 Read dialog shows the Contents tree (chapters with numbers and roles, sections nested) beside the text, section labels inline, click-to-scroll with a highlight; `/api/sources/{id}` carries `sections` (ordinal, spine index, href, fragment, chapter, chapter_no, section, role, depth, label, chars) aligned with the segments by ordinal — the reader contract.

**Gate (tests/test_m1_epub.py, +2 → 8).** A book with an index and a copyright page that repeat the chapter's words: the chapter wins retrieval, the index remains retrievable, findings windows contain neither back-matter page and put the body first; the reader contract aligns sections with segments and carries roles/anchors; deep links are `#book/…`. P2 items (existing Work matched; version when determinable; EPUB manifestation; structured chapters; human-readable citations; no duplicate acquisition) are covered by the P1 tests. Suite 390; Tier 1 untouched; the frozen retrieval baseline (no books in the golden fixture) untouched.

**Honest limits.** Role detection is by `epub:type` and title words — an unlabeled "Chapter 12" whose title is "Notes on Method" is treated as notes (0.7), never dropped. The reader renders text only (images/tables as text until G8). No page-number mapping (EPUBs have none; publisher `page-list` navs are ignored for now).


## C0 Portable Answers, second half — Share ▾ — 0.35.1 (COMPLETE, pending delivery)

**Built.** Every assistant message has **↗ Share ▾** beside Copy ▾: *Short version + sources (2–3 sentences)*, *Medium version + sources (one paragraph)*, *Full answer + sources*. A variant is one call on the new contract `answer.share` (interactive, 1,200 output tokens, `NO_FALLBACK`) over the FINISHED answer and its numbered sources — never a new research pass, no tools, no retrieval. `qa.share_variant` enforces the evidence rule: the rewrite may use only the original's citation markers; a stray marker is removed and reported (`removed_markers`, `warning`). The client re-attaches the sources list and the evidence-status warnings exactly as Copy ▾ does (`exportMsg`), so a warning survives every variant; variants are cached per message in the session. `POST /api/share` is budget-guarded. Tier 1 untouched (the chat prompt is unchanged; `answer.share` is a separate task).

**Gate (tests/test_m2_share.py, 4).** Contract shape; short < original and medium > short with markers ⊆ original; exactly one invocation per variant; a stray marker removed and reported; the endpoint rejects empty text and guards the budget. Suite 394.

**Honest limits.** The fake provider truncates by sentence; the live rewrite's faithfulness is the model's — the marker check catches invented citations, not invented prose, which is why the system prompt forbids adding facts and the UI labels the result as a version of the answer, not the answer.


## B3 — Candidate links / gap recall — 0.36.0 (COMPLETE, pending delivery)

**Built.** `candidate_links` (additive: candidate ↔ project ↔ kind evidence_target | claim | tension | mission | discovery ↔ ref, relevance, why, state open / satisfied / dismissed) replaces the JSON trail as the durable relation "why a known-but-not-captured source matters". `knowledge.pursue` links the reranked Candidate Index results to the open question (idempotent; a dismissed link stays dismissed; a link on an already-acquired candidate is born satisfied); `candidates.resolve_acquired` — acquisition by ANY path, any project — satisfies every open link to that candidate (Global Library rules unchanged). `knowledge.state()` targets carry `known_uncaptured`; `known_evidence(target)` returns the best few with an `acquisition_hint` (`browser_likely` for Reddit/community; `server` otherwise); `capture_best(target, n)` acquires them through the NORMAL path only — attach when a ready copy is owned, else an `ingest_url` job carrying `candidate_id` (which B1 parks on the browser when the server cannot read) — never a web search. The chat's `research_state` tool names, per open question, "N promising sources known but not yet captured (the user can capture them from Research)" — tool output, so Tier 1 is untouched. API: `GET /api/targets/{id}/known`, `POST /api/targets/{id}/capture-best {n}`, `POST /api/candidates/{id}/dismiss-link`. UI (interim, pre-redesign): the Evidence Target card shows "N promising sources known, not captured — [Capture best 3] · see them"; the list dialog offers "Not for this" per source and marks browser-likely ones.

**Gate (tests/test_m3_links.py, 4).** Pursue links durably and refreshes without duplicates; the state and the chat tool show the count; acquisition satisfies, dismissal survives re-ranking; Capture best attaches an owned copy and queues ingest jobs with the candidate id, never a discover job; Reddit candidates are flagged browser-likely. Suite 398; Tier 1 34 / 196,951 unchanged.

**Honest limits.** Links are written by `pursue` (and by the mission/discovery paths only where those already call the Candidate Index); the B4 scanner will be the main producer. No learning from selections yet (B5). The Research-tab surface is interim: the redesign (`RESEARCH-MISSION.md` §F) renders these as "3 previously discovered sources may help — [Check those 3 sources]".

## Research rebuild R1 + R3 + R5 + R6 (engine only) — 0.37.0 (COMPLETE, pending delivery)

**Built.** `research_view.py` — the decision-first Research view's engine, $0 and deterministic, shipped ahead of its shell so the Opus session that builds R2 renders a finished contract instead of inventing one. `overview` (summary counts · the ranked "next" list across open questions and watch-outs · recently improved · the attention number · Research Areas · empty flag), `questions` (evidence targets in plain language: headline, what settles it, evidence so far, gap, what was already checked, known-but-uncaptured sources, why it is being asked, what happens if ignored, actions with cost), `watchouts` (tensions collapsed into issues by kind × area — one title, one detail line, one action, the underlying rows for drill-down), `areas` (stable clusters over the topic nodes; generic and tiny topics folded, never shown; names from finding titles — "Guarantee fee rates · Seller note standby rule", never "Full & Usual"), `attention` (important open questions + high/medium watch-outs + strong Claims awaiting a decision; never the Claim count). Priority scoring is documented in `RESEARCH-TAB.md` §7 with every constant named. API: `GET /api/projects/{id}/research/overview|questions|watchouts|areas`; the existing `GET …/research` and `POST …/research/refresh` carry `attention`, and the sidebar badge `#nResearch` now shows it (the only UI change). R1's baseline note (every control, what it mutates, cost, consequences, existing auto-resolution, sidebar semantics, live stress numbers) is `RESEARCH-TAB.md` §7.

**Gate (tests/test_n1_research_view.py, 9).** Same state → identical view, zero invocations; ranked by score with the stale high-impact issue first; importance and Master-Plan dependence raise priority by the documented bonuses; questions carry the escalation history and gain the capture-best action once sources are known; seven Claim-level STALE tensions become ONE issue (breadth-scored, capped); a missing-perspective issue names the absent voice; areas are never named by generic tokens and fold small topics; area cards summarise without source counts; attention falls when questions are settled and Claims accepted while the Claim count does not; an empty project is explicit; the API surfaces all of it. Suite 407; Tier 1 34 / 196,951 unchanged (no prompt text changed).

**Honest limits.** No shell: the Research tab still renders the old map/tensions/targets/claims lists — only the sidebar number changed. Areas cluster on the topic nodes' term bags (Jaccard), so a project whose nodes are all generic collapses into one area named from its two most common finding titles; R6's "human-level domains" exit is met on the fixture and must be checked live on the 449-source project (`GET /api/projects/{id}/research/areas`) when R2 lands. "Not important to my project" and automatic re-grouping on evidence change are R5's second half (the dismissal endpoint exists per tension; the grouped action is UI). Recently-improved is limited to settled questions and newly accepted strong Claims within 14 days. R2 (shell), R4 (questions UI), R7–R12 remain queued for the next session — `RESEARCH-MISSION.md` + `RESEARCH-TAB.md` §7 are the handoff.

## 0.37.1 — the engine meets the live project (2026-09-08)

The first live read of `GET …/research/overview` on the 449-source project (4,420 Claims, 414 ms) exposed three things the fixture could not: (1) 1,332 open questions of which 700 carry importance ≥ 4 — "important open questions" cannot be the sidebar number, so `attention` is now high-impact issues + planner-dependent questions + Claims awaiting a decision (things that are few by construction; the important-question count stays in the summary); (2) greedy clustering with an ever-growing term bag made one area a magnet (1,656 Claims, 18 topics) — cluster bags are re-trimmed to `AREA_TERMS` after each merge; (3) finding titles on that project are full propositions ("Deal structure matters more than headline price"), useless as area names, while the normalized topics are exactly the human-level domains R6 asks for ("acquisition due diligence framework", "franchise economics", "seller motivation seven ds") — areas are now named from their multi-word topic labels first (largest, plus a second when nearly as large), single-word topics ("cash", "deal", "buyer") never stand alone when any multi-word topic exists, and titles/terms are only fallbacks. Gate +1 (multi-word labels win, lone words fold). Suite 408.

## 0.37.2 — unlabelled bulk (2026-09-08)

0.37.1 live: badge 19 (was 99), 20 areas with human names ("Due diligence", "Tax strategy", "Business credit", "Seller financing", "S-corp taxation", "Franchise economics", "Holding company structure"…), overview 380 ms — but "Due diligence" still held 2,851 of 4,778 Claims, because the $0 harvest labels most Claims with a lone word ("business" ×1,243, "revenue" ×214, "seller" ×133, "deal" ×101…) and those blocks folded whole into whichever area's vocabulary was broadest. A lone-word topic with many Claims is not a subject, it is unlabelled bulk: 0.37.2 places each of its Claims by its own words (`BULK_MIN_OVERLAP` 0.15 of the Claim's tokens must be the area's) and sends the rest to an explicit **Everything else** area instead of inflating the largest one. `areas()` now returns `area_of_claim` alongside `area_of_topic`; questions and watch-outs are placed by Claim; tensions on superseded Claims are no longer issues (that was the "General evidence may be outdated" card). Gate +1. Suite 409.

## L1 — Claude Code as the local AI provider — 0.38.0 (COMPLETE, pending delivery; OFF until Kyle turns it on)

**Built.** `claude_code.py`: the headless CLI driver (`claude -p … --output-format json --max-turns 1 --system-prompt … --tools ""`, `--json-schema` when the installed CLI lists it; the flag table is verified against `claude --help` at runtime so a flag the CLI does not know is never sent), scratch cwd under `data/local_ai/`, contract timeout, output cap, no repo, no tools; `LocalResponse` duck-types the API message so the ledger, `structured()`, schema validation and provenance run unchanged. Health (`not_installed · not_signed_in · usage_limit (+reset hint) · error · ready · disabled`) cached 10 min, corrected at once by any real failure. `providers.route(task)` → local only when the task is `local_capable` (findings.extract, rank.relevance, library.profile, claims.extract, discover.quick, planner.update), the profile is `local`, the job's policy allows it and health is ready; `LOCAL_UNAVAILABLE` / `LOCAL_LIMIT` are typed, never retried, never trip a breaker, and fall back to the API with the reason in `routing_json` (`executed_by`, `route_reason`, `fallback_reason`) — `fallback_used` stays False because the MODEL is never substituted. `local_only` raises instead of spending; `api_only` / `api_requested` never touch local; `ai_profile=cloud` (the default) makes local absent. Jobs: additive `execution_policy` (intent) + `executed_by` / `fallback_reason` (outcome, sticky across a job's calls: local · api · mixed); `PUT /api/jobs/{id}/policy`; in the local profile general workers leave the AI kinds to a `local_ai` pool (`NEUROSEARCH_LOCAL_AI_WORKERS`, busy = wait) and one `api_ai` pool for API policies. Usage: local calls are `transport='local'`, `cost 0`, `saved` = the avoided API spend at the contract's model price; `/api/usage.local_ai` (+ `avoided_month`), `/api/health.local_ai`, doctor line, the Jobs-view spend line shows "Claude Code: … · $x avoided" when local. `.env.example` documents the four settings.

**Gate (tests/test_n2_local_ai.py, 20).** Ready → local, identical structured output to the cloud path, $0 + avoided spend in the ledger; five failure modes → API with the reason, health corrected, no breaker, no retry; local_only never touches the API; api_only/api_requested never touch local; non-local-capable tasks stay on the API; the policy column, the three pool claims, intent ≠ outcome on real jobs; the stub CLI (`tests/fake_claude_cli.py`) proves the flag table, the JSON contract, native structured output, the error mapping (limit with reset hint, auth, crash, garbage) and the timeout; missing binary and cloud profile. Suite 429; Tier 1 34 / 196,951 unchanged (the fake path answers local calls with fixture outputs, and the default profile is cloud).

**Honest limits / what Kyle must do before it is worth turning on.** (1) Not verified against a real Claude Code binary — the sandbox and the Mac's VM cannot run `claude`; the flag table matches the documented CLI and adapts to `--help`, but the first live run on the Mac is the real gate: set `NEUROSEARCH_AI_PROFILE=local` in `.env`, restart, run `neurosearch doctor` (the "Claude Code:" line), then approve one findings job and read its row (`executed_by`, `fallback_reason`) and `/api/usage.local_ai`. (2) The subscription's models differ from the pinned API models: quality on the Golden Project with the local provider is unmeasured — run `neurosearch eval` with the local profile (unfrozen, recorded) before trusting findings/ranking from it. (3) L2 chat (streaming, tool loop via the MCP server), L3 the "answer now with API ≈ $" acceleration dialog, L4 the usage split are not built; the policy column and `PUT /api/jobs/{id}/policy` are their hooks. (4) The health probe spends a few subscription tokens every 10 minutes while the profile is local. (5) Per the policy note: Claude Code inference shares the week's subscription allowance with development sessions, and Anthropic's terms for using Claude Code as an application's background engine should be checked before it becomes the default.

## 0.38.1 — EPUB hotfix (Kyle, live, 2026-09-08)

"epub failed: unsupported operand type(s) for |: 'tuple' and 'set'" — `epub._sections_of` tested a wrapper `<div>` against `("p", "div", …) | HEADINGS`, a tuple-or-set that raises the moment a chapter is wrapped in a div, which every real converter (Calibre, InDesign) does and the fixture did not. Fixed (`BLOCK_CONTAINERS` set); the m1 fixture's chapter 2 now carries the wrapper-div shape plus a leaf div, so the branch is gated for good. No other change.

## 0.38.2 — first live run of L1 (2026-09-08)

Kyle enabled the local profile (`.env`: `NEUROSEARCH_AI_PROFILE=local`, `NEUROSEARCH_LOCAL_AI_WORKERS=2`, `NEUROSEARCH_CLAUDE_CODE_MODEL=sonnet`). Claude Code 2.1.257 was installed and signed in; the probe answered — on **claude-haiku-4-5** (the CLI routes a trivial prompt to its cheapest model), hence the explicit `sonnet` pin: findings/ranking quality was frozen on Sonnet. Two fixes from the first minutes: (1) `/api/health` and `/api/usage` (polled by the Jobs view) blocked on the synchronous probe after every reload (up to 90 s; the UI tab froze) — `health(wait=False)` now returns the last verdict or `checking` at once and probes in a background thread; only the router and doctor wait; (2) the reported model is the one that did the most work in `modelUsage`, not the first key. Gate +1 (surfaces never block). Kyle's allowance note: Claude Code inference under the subscription counts against the all-models pool (54% this week), not the Fable pool (88%).

**Live record (0.38.2, 2026-09-08 21:50 UTC).** Claude Code 2.1.257, signed in, `--model sonnet`. `/api/health` 23 ms with the background probe. A `suggest_findings` job (one long transcript, many windows) ran on the local pool: the ledger's avoided spend climbed $3.69 → $3.91 → $4.51 over ~3 minutes while API spend for the day stayed flat at $25.76 — every window answered locally, none fell back. Speed: roughly one findings window per minute on the local provider versus a few seconds on the API — expected, and exactly the "busy ≠ unavailable" case: work waits, nothing spends; L3's acceleration offer is how the user buys speed. Not yet recorded: the CLI's own model string per task call (the probe reported haiku before the pin), and Golden-Project quality under the local profile.

## L4 — usage split + provider badges — 0.38.3 (COMPLETE, pending delivery)

`usage.local_split()` = "N AI calls · % local · $ actual · $ avoided" for the month (whisper excluded), on `/api/usage.local_ai.split` and `/api/health.local_ai.split`; the Jobs-view spend line shows it when the profile is local; every job row now carries 🖥 local · ☁ API · 🖥/☁ mixed (the hover text names the fallback reason when it meant local and ran on the API), and a queued/running job with a non-default policy shows it. Gate +1. The metric is informational and unfrozen (HARDENING 0.38.0 note). L2 (local-first chat with the MCP tool loop) and L3 (the acceleration dialog; `PUT /api/jobs/{id}/policy` is its hook) remain.

## Mission S — Sources, Findings, Deep content (filed 2026-09-08; `SOURCES-FINDINGS-MISSION.md`)

Kyle: "dig deep and think about our research tab and our sources tab and find better ways to organize and surface actions… a better way to deal with stale findings… a better way to surface and utilize transcripts or findings from the sources or non ingested sources… get more value out of longer form content and deeper knowledge content like books, podcasts, long interviews." The mission document holds the live diagnosis (5,222 findings as a pile; 396 stale for one reason, "brief changed"; 4,000 known-but-uncaptured items invisible; a 12-per-source cap starving 131 hours of long-form content) and the ladder D1–D3 + S1–S5.

## D1–D3 — Deep content — 0.39.0 (COMPLETE, pending delivery)

**Built.** `findings.cap_for(windows)` = 12 + 8 per extra window (max 120) with `COVERAGE_FLOOR` 3 per window (`select_findings`: per-window importance order, then global importance with window index as tie-break; a one-window source is exactly the old top-12); validated findings beyond the cap are stored as **`reserve`** notes — replaced with suggestions on re-analysis, never read by exports, the planner's new-notes scan, Claim harvest or the chat's research block; `GET /api/projects/{id}/notes?status=reserve&source_id=`; promotion through the existing note-status endpoints; `/api/sources` rows carry `reserve`, and the card shows "+N more extracted · Show" with ✓ / 📌 / ✕ per finding and send-all/dismiss-all. **D2 Read deeper:** `suggest_for_source(depth="deep")` re-windows at `DEEP_WINDOW_CHARS` 20k and adds `DEPTH_INSTRUCTION` to the USER message (the frozen system prompt and `prompt_version` are untouched); `input_hash(…, depth)` and the additive `project_source_analysis.depth` make a deep analysis current on its own terms — an ordinary request is satisfied by an ordinary or a deep analysis, a deep request only by a deep one; `staleness.assess` hashes with the stored depth; `POST …/suggest {depth:"deep"}` (interactive only; forces), job payload `depth`; the card shows 🔬 Read deeper on long sources and 🔬 deep-read afterwards. **D3:** `findings.is_long` (book or ≥ 45 min), `under_read` (long, read once, ≤ 12 findings, not deep); Sources chip **📚 Deep content (N)** sorted under-read first, the 📚 under-read tag, and "🔬 Read deeper on all N" (confirm → one job).

**Gate (tests/test_n3_deep_findings.py, 8).** Cap growth and bound; one-window = old top-12; the floor keeps a quiet window's finding; multi-window overflow → reserve with citations, invisible to approved/exports/Claims/project view, counted and listed, promotable, replaced on re-analysis; a short source unchanged; deep pass uses more windows and the depth instruction in every user message, is current for both request kinds, staleness agrees, a brief edit stales it; the API refuses deep-in-batch and forces; under-read flips off after a deep read. Suite 439; Tier 1 34 / 196,951 and findings 9 / 30,297 unchanged.

**Honest limits.** Existing analyses keep their 12: the reserve only exists for sources analysed after 0.39.0 (a Read deeper or re-analysis fills it). Deep reads run interactively (local pool or API), not in the batch path. `is_long` ignores page counts for documents (books and media only) until S2's value spine carries words. No measurement yet of how many more findings a deep read yields on a real 3-hour source — the first live run should be recorded here.

## S1 — Stale triage — 0.40.0 (COMPLETE, pending delivery)

**Built.** `staleness.triage(pid)` partitions the stale set by why and weight: **rebuild_matters** (priority source · evidence in the Master Plan · evidence of a strong Claim · an approved finding rated 4–5 — `_matters`, $0 from existing rows, each source carries its `why`), **rebuild_transcript** (the quoted evidence may have moved; never acceptable), **accept** (brief/prompt-only staleness carrying no weight), **retry_failed** (the last rebuild failed; the reason on the row). Each tier carries an API-dollar estimate and, when the local profile is on and Claude Code is ready, a time line ("$0 · about 1 h 20 min on Claude Code", `LOCAL_MINUTES_PER_WINDOW` 1.2 from the 2026-09-08 live run). `staleness.accept(pid, source_ids | tier)` writes the additive `project_source_analysis.accepted_hash/accepted_at` — the exact input hash accepted — and `assess()` reports such sources as `current_accepted` until the inputs change again (a transcript change is refused outright). `rebuild-stale {tier}` queues exactly that tier (the plan still waits behind it). API `GET …/staleness/triage`, `POST …/staleness/accept`. The Findings-tab banner is now the triage card: four rows, each with its explanation, the first three titles, the why, and one button; "Hide for now" instead of "Leave stale".

**Gate (tests/test_n4_stale_triage.py, 3).** Partition by why and weight with the why strings; a transcript change moves a source to its own tier; cost lines name the provider both ways; accept survives assess, queues nothing, touches no finding, lapses on the next brief change, refuses transcript changes, and a rebuild supersedes it; tier rebuilds and retries queue exactly their sources; empty tiers queue nothing. Suite 442; Tier 1 unchanged.

**Honest limits.** "Cited in chat" is not yet a weight signal (S2's value spine adds chat citations); importance ≥ 4 stands in. The plan card keeps its old "rebuild after re-analysing N" wording until S2. Legacy (0.15) analyses sit in the tiers like stale ones. On Kyle's project the expectation is: 396 stale → a few dozen "matters", a handful "failed", and the rest acceptable in one click.

## S2 — Source Value + the Sources filters — 0.41.0 (COMPLETE, pending delivery)

**Built.** `sources_value.py` — one pass over `project_notes`, `claim_evidence` (independent evidence only), the latest plan's `_evidence`, assistant `messages.citations` and `project_sources.priority` → per source: findings by status, importance (max/sum/rated 4–5), Claims (rows/strong/accepted), used (plan evidence, chat citations, last used), priority, `value_score` (+40 plan · +30 priority · +10/strong Claim cap 30 · +3/rated finding cap 30 · +2/citation cap 20 · +1/other finding cap 10), **`matters` as a rule** (priority · plan evidence · independent evidence of a strong Claim · ≥ 3 findings rated 4–5 — S1's triage now reads the same rule and words), `never_used`, a one-line `label` ("12 findings (4 rated 4–5) · 2 strong Claims · in the plan · cited 7× · ★ priority"). `/api/sources?project_id` rows carry `value` (+ `stale`/`stale_status`/`stale_reasons` from `staleness.assess`). Sources tab: a **Show:** row of composable filters — ★ Matters · ⚠ Stale · ★ Priority · 📚 Under-read · 🔬 Deep-read · ∅ Gave nothing · Never used — a length band (under 15 min · 15–45 · 45+ · books & documents) and a sort (activity · most valuable · least used · longest · newest · title); the card's findings line is the value label with a ⚠ stale tag (reasons on hover). Filters AND together with the status chips and the text box.

**Gate (tests/test_n5_source_value.py, 2).** Strong-Claim evidence and a rated finding make the primary source matter while its derivative repeats do not; plan evidence, chat citations and the star each make a source matter with the right words; determinism; only-low-importance findings score below one plan-evidence source; rows carry value and a boolean stale flag. Suite 444; Tier 1 unchanged.

**Honest limits.** `matters` via rated findings needs three of them (one 5/5 finding alone does not, deliberately — approve-all made single ratings cheap); on Kyle's project the S1 "matters" tier will shrink from 210 accordingly. Value is computed per request (one pass, ~100 ms on 1,000 sources); no cache yet. The findings-tab filters (S4) and the source drawer (S3) are next.

## S4 — Findings workbench — 0.42.0 (COMPLETE, pending delivery)

**Built.** `findings_view.py` — `usage_map` (finding → plan evidence at its locator, chat citations at its locator, the Claim it originated or evidences, from `plans._evidence`, `messages.citations`, `project_claims.origin_note_id`, `claim_evidence_notes`) and `query(pid, q, status, min_importance, source_id, used, stale, area, sort, limit, offset)` with facets (status · importance · used · stale · area · top sources), each facet counted over the filtered set minus its own dimension; area = the Research Area of the finding's Claim (`research_view.area_of_claim`); the **low-value sweep** (approved · importance ≤ 2 · never used) as a review list with the note ids. `GET /api/projects/{id}/findings`. UI: the 5,222-row page becomes a workbench — search box, status (approved / suggested / reserve / dismissed / all), importance, used-by (plan / chat / Claim / never), source state, area (populated from the facet), sort (importance / newest / by source / most used), a count line with the use split, paging by 100, per-source groups with a "filter" button, use badges on every card (📋 plan · 💬 N× · 🧠 strength · ⚠ stale source · area), the sweep banner with "Review them" and "Dismiss all N" (confirm).

**Gate (tests/test_n6_findings_workbench.py, 2).** Filters compose; facets describe the other dimensions; text search over title/content/source; badges from real plan/chat/Claim rows; the sweep counts and never dismisses; sorts and paging; area filter; status/source filters; the API mirrors the engine; source staleness follows the analysis state. Suite 446; Tier 1 unchanged.

**Honest limits.** Chat use matches a finding by source + locator string (a chat citation to the same source at a different timestamp does not count for the finding, only for the source's value); plan use without a locator counts for every finding of that source. The query loads the project's notes in memory (5,222 rows ≈ 100–200 ms); no FTS index for findings yet. "Gaps" pinned from chat now show as ordinary findings under "Pinned from chat".

## 0.42.1 — Read deeper: progress and the slow lane (Kyle, live, 2026-09-08)

"I can't tell if the deeper findings is actually working, there's no indication of how far it is in the progress, and it's holding back other work." Two fixes. (1) **Progress per part:** `suggest_for_source(progress=)` reports "reading deeper · part 3/12 · 41 findings so far" per window (nested inside the per-source progress of a multi-source job); the source card shows that line with a percentage while the job runs, and "queued for a deep read (slow lane — other work keeps running)" while it waits (`db.analysis_jobs_by_source` → `analysis_job` on the row). (2) **The slow lane:** additive `jobs.lane` (`normal` | `slow`), `claim_job(lanes=)`; Read deeper creates ONE job per source in the slow lane; in the local pool only the first worker takes the slow lane, every other local worker serves the normal lane — a deep read can never occupy more than one local worker, and ordinary findings/ranking keep flowing beside it (`NEUROSEARCH_LOCAL_AI_WORKERS=3` gives two normal workers). Also in this release: S4's "used" now means referenced by the plan body (not merely handed to the planner), cited in chat, or behind a strong/accepted Claim — the $0 harvest folds nearly every finding into a weak Claim and that is not use (live: 5,206 of 5,234 findings were "used by a Claim"); plan evidence is matched by source+locator or by the planner's "title @ locator" label. Gate +1 (progress + lane). Suite 447.

## S5 — Known, not captured + the pre-cutoff quick scan — 0.43.0 (COMPLETE, pending delivery)

**Built.** `candidates.pool(pid, q, rank_by, kind)` — the 402 sources skipped at the ingest cutoff (with the review's relevance score and reason) and the Candidate Index rows (available · skipped-low-relevance, with their B3 links to open questions) as ONE list. Each item: why known ("published 2021-03-01, before cutoff 2024-09-08" / "found for an open question" / "seen in exploration of X · ranked below the cut"), **potential 0–100** from a $0 scan of title + description — already linked to an open question (+45), fits an open question or weak Research Area by term overlap (+35), uses the project's own vocabulary (+20), the review score (+25%), reads as timeless (how-to / principles / checklist, +10) or dated (news / rates / a year, −10) — the best `fits`, the reasons, ★ same creator as a priority source. Rank by fit · review score · creator · newest; show all / skipped at cutoff / seen while exploring; text search. Capture = the existing `/retry` (skipped, lifts the cutoff for that one) or `/acquire` (candidate → `ingest_url`); dismissal = remove from project (durable `excluded`) or candidate dismiss. `GET /api/projects/{id}/pool`; Sources chip **🔎 Known, not captured (N)**. Skipped stays the default — the scan is a hint for review, never a verdict, and nothing is evidence until captured.

**Gate (tests/test_n7_pool.py, 1).** Skipped and candidate rows unify; the timeless pre-cutoff source outranks the dated one and fits the open question; the linked candidate carries "found for an open question"; search, kind filter, rank by review score; capture endpoints are the normal paths; dismissal is durable; no chunks exist for anything in the pool. Suite 448; Tier 1 unchanged.

**Honest limits.** The scan reads titles and descriptions only (no transcript exists for uncaptured items by definition); YouTube descriptions are often thin, so "worth a look" undercounts. Timeless/dated cues are a small word list. No "capture the 10 that fit" bulk action yet — one click per item. The Research questions' "N promising sources known" link does not yet land on this view filtered to that question.

## R2 — the Research shell — 0.44.0 (COMPLETE, pending delivery)

**Built.** The Research tab is no longer four raw lists. One request — `GET …/research/overview?full=1` (`research_view.overview(full=True)`: the same `questions`, `watchouts`, `areas`, `area_of_claim` and `area_of_topic` the separate endpoints return, computed in ONE `_load()` pass instead of four) — renders every pane, and the heavy `/research` state (300 Claims) is fetched lazily, only when the Claims or Research-tools pane is opened. Panes: **Overview** (four plain-language stats — important open questions · watch-outs worth acting on · Claims awaiting your decision · areas still weak — then "Do these next", the ranked mix of questions and watch-outs with what it costs to leave each alone, then recently improved, then the areas), **Open questions** (headline, evidence so far, what is still needed, what would settle it, why it is being asked, where it already looked, known-but-uncaptured sources, and the engine's own cost-labelled actions rendered as buttons + "Settle · not needed"), **Watch-outs** (one card per ISSUE: impact, detail, what happens if ignored, "Show the N Claims" drill-down, the $0 action when open questions cover it, **Resolved**, **Not important to my project**), **Areas** (state, understanding, what needs work, Focus → filters questions, watch-outs AND the Claims workbench by `area_of_claim`), **Claims** (the old workbench, area-filtered), **Research tools** (the old Knowledge Map, tension and target lists, Refresh / Normalise / Evaluate — everything reachable, nothing removed). The sidebar badge is set from the shell's own request. New endpoint `POST /api/projects/{id}/tensions/bulk-status {tension_ids, status}` — R5's remaining half: one verdict for every tension behind an issue, then ONE refresh; scoped to the project, validated, and durable because `_upsert_tension` never resets status.

**Gate (tests/test_n8_research_shell.py, 3).** `overview(full=True)` equals the separate endpoints and costs zero invocations, the light request stays light; one verdict clears a whole issue, survives `knowledge.refresh` + `claims.ensure`, is scoped to its project, refuses a bad status and a missing project, and the issue count falls by exactly one; and a UI rung still gets a gate — every pane id, element id, endpoint and question action the shell renders must exist on this build (routes checked against `api.app.routes`). Suite 451; Tier 1 34 / 196,951 unchanged.

**Honest limits.** The watch-out's primary action only appears when an open question already covers one of its Claims (that is the only honest $0 action the engine has for an issue); otherwise the card offers the drill-down and the two verdicts. Area focus is client-side over the maps the one request already carries. "Recently improved" still only counts questions settled and Claims accepted in the last 14 days. Not yet done from Kyle's list: the "N promising sources known" link opens the B3 dialog rather than landing on the 🔎 pool filtered to that question.

## 0.44.1 — the fourth overview stat (live, 2026-09-08)

The first live render of R2 on the 449-source project (overview in 622 ms for every pane; 4,800 Claims, attention 67, 50 watch-out issues, 29 areas, 1,856 open questions) showed the fourth stat reading "29/29 areas still weak" — an area is only `strong` when half its Claims are, which never happens on a harvested corpus, so the number could never move. Replaced with **"N/29 areas with a well-evidenced conclusion"** (areas holding at least one Strong Claim), which is a progress measure the open questions above it actually shift. UI only.

## S3 — the source drawer — 0.45.0 (SHIPPED 403223a; includes 0.44.1)

**Built.** `sources_value.digest(pid, sid)` + `GET /api/projects/{id}/sources/{sid}/digest` — one $0 request returns everything a source gave: its measured value (S2 score, label, why it matters, never-used), its findings **by status** (approved · waiting · reserve · dismissed) each with the use badges S4 computes and its transcript locator, the Claims resting on it (strength, independence, stale evidence, locator), **where it shows up** (`used_in`: Master Plan steps found by walking the plan BODY for the evidence ids of this source — the step's own title, never an entry the planner was merely handed; chat answers by conversation title, locators and a snippet), and its staleness with the S1 tier and estimate. UI: a **What this gave** button on every ready source card, the card's value line, and a `source ↗` button on each group in the Findings workbench all open one dialog — value and why, 💬 **Ask about this source** (pins it to the next chat question through the existing `attached_source_ids` path), Transcript / 📖 Read, 🔬 Read deeper when it is long and not yet deep-read, and the one-source staleness actions (Re-read it · Accept as still usable — the same durable acceptance the triage card writes), then where it shows up, the Claims, and every finding with ✓ / 📌 / ✕ (including promoting a `reserve` finding). Also folded in: **0.44.1** — the Overview's fourth stat was "29/29 areas still weak", a number that could never move, and is now "N/29 areas with a well-evidenced conclusion".

**Gate (tests/test_n9_source_drawer.py, 3).** The digest costs zero invocations; value, findings-with-uses, Claims, the plan step found by its own title and the chat answer by its conversation; a source the plan cites but never references is NOT reported as used; a source that gave nothing says so instead of inventing a use; the staleness tier appears and acceptance flips it to `current_accepted`; reserve findings sit in their own group, never mixed into approved; the drawer is reachable from three places and every action it renders points at a route that exists. Suite 454; Tier 1 34 / 196,951 unchanged.

**Honest limits.** Chat uses are matched by source id and reported with the citation's locator; the plan walk is depth-capped at 8 and reports at most 12 places. The drawer lists up to 60 findings per status. No "compare two sources" view; no per-source cost history.

## L3 — the acceleration dialog + a Read-deeper dedupe fix — 0.45.0 (SHIPPED 403223a)

**Built.** `jobs.backlog(project_id)` — what waits on the local provider (queued + running AI jobs, per job: sources, windows, the API estimate, the S2 value of its sources), the TIME it needs on Claude Code (`windows × staleness.LOCAL_MINUTES_PER_WINDOW`, deep reads counted at 3× because they re-window) and the DOLLARS the same work costs on the API — using `usage.estimate_source_findings`, the one estimator the stale triage now also calls, so the two surfaces can never disagree. `jobs.accelerate(pid, n, order)` moves exactly the chosen jobs to `api_requested` (order `queue` = oldest first, `value` = the sources that matter most first); the `api_ai` worker pool then claims them while the rest keep running locally at $0. `GET /api/projects/{id}/ai-backlog`, `POST /api/projects/{id}/accelerate`. UI: a banner above the Jobs list — "🖥 N jobs waiting on Claude Code · about 2 h 10 min · the same work on the API ≈ $1.20. Nothing is stuck…" with **next 10 / next 25 / all** and **most valuable first**, each confirming the estimate before it spends. The banner never appears on the cloud profile or when Claude Code is not the one doing the work.

**Fixed (0.39.0 bug, found by this rung's test).** `db.dedupe_key_for` keyed a findings job as `findings:{project}:{source}` with no depth — so pressing **Read deeper** on a source that already had an ordinary findings job queued silently returned that shallow job and the user got a normal read. The key now carries `:deep`; a second identical deep request is still one job. Regression test added to the D-gate.

**Gate (tests/test_o1_accelerate.py, 3).** Backlog counts, ETA arithmetic, the dollar figure equal to the triage's own estimator, per-project scoping, deep reads counted as more local work; acceleration moves exactly what was chosen (value order honoured), marks `api_requested`, leaves the rest local, returns the estimate for what actually moved, tolerates n > backlog, refuses a bad order and a missing project; a cloud profile reports `local_ready` false and the banner hides itself. Suite 458; Tier 1 34 / 196,951 unchanged.

**Honest limits.** The ETA uses one measured constant (1.2 min/window on Sonnet, 2026-09-08) — it is an estimate, not a promise, and does not model the two local workers running in parallel (so it reads pessimistic when `NEUROSEARCH_LOCAL_AI_WORKERS > 1`). Acceleration is per project. **L2 (local-first chat) is deliberately NOT built** — see the note below.

## L2 — local-first chat: a recommendation, not a rung (2026-09-09)

The Local-First AI policy asks for chat to run on Claude Code with the API as burst. Having measured the local provider (about a minute per findings window; a deep read of a 3-hour course takes ~7 minutes), the honest recommendation is **not to make chat local-first by default**: chat is the one surface where latency is felt directly by a person waiting, the answer needs a tool loop (`search_library`, `list_sources`, `set_source_priority`) which on the CLI means `--mcp-config` plus a permission surface, and Tier 1's chat totals are frozen against the API models. What the policy actually wants — "don't silently turn slow into spend" — is already delivered by L1 (background work runs local at $0), L3 (the user buys speed on purpose) and L4 (the split is visible). If Kyle wants local chat anyway, the shape to build is a per-project toggle ("answer with Claude Code, slower and $0"), never a default, with the API answer one click away. Left as a decision for him, not a silent default.

## S1 fix — an accepted legacy source stayed stale forever — 0.45.1 (COMPLETE, pending delivery)

**Found live, not in a test.** Kyle's project reads 64 stale sources behind 513 of 519 approved findings, and every one of them
is `legacy_unverified` — the whole library was migrated from Neuro Search 0.15. Running the S1 accept tier against it returned
`accepted: 14, refused: 0` and **changed nothing**: `stale_total` stayed 64, `accepted` stayed 0, the tier stayed full.

**The bug.** `staleness.assess` handles the legacy row in its own branch, which appended the "preserved from 0.15" reason and
fell straight through to the estimate — it never read `accepted_hash`. `accept()` had always written that hash for legacy
sources (they are exactly what lands in the accept tier), so the write was real and the read never happened. Consequence: on a
migrated library the accept tier could never empty, and the stale pile looked permanent no matter what the user pressed —
which is precisely the complaint that "things marked stale never go away". The stale branch had the same check and worked, so
the S1 gate passed throughout: **every test built its sources with `findings.suggest_for_source`, so not one of them was ever
`legacy_unverified`.** The tier that only ever appears on real, migrated data was the tier that was never tested.

**Fixed.** The legacy branch now honours an acceptance the same way the stale branch does, and clears the reasons and the
estimate with it. Because `findings.input_hash` covers the transcript revision, the brief revision and the prompt, an accepted
legacy source un-accepts itself the moment any of those change — accepting is never "never ask again", and a re-accept is one
action. Nothing else moves: the findings are untouched, nothing is queued, and an accepted source is no longer quoted as work
to buy. Downstream, `findings_view`'s stale facet and `sources_value` stop calling those findings stale, because they read the
status this function returns.

**Gate (tests/test_n4_stale_triage.py, +2 → 5).** A migrated library (`status='legacy_unverified'`, `input_hash` NULL, provider
`migrated` — what `db._migrate` writes) is accepted and the tier actually empties: assess reports `current_accepted` with its
note, `stale_sources` 0, `triage.accepted` 4, every estimate 0, nothing queued, the findings still there, and the workbench's
stale facet down to 0. Then: a transcript change puts that source back to `legacy_unverified` with an estimate again, a brief
change puts all four back, and one re-accept clears them for the new brief. Suite 460; Tier 1 34 / 196,951 unchanged.

**Honest limits.** This makes the acceptance *visible*; it does not judge whether those findings are still right — that is what
the rebuild tiers are for. A legacy row still carries no input baseline, so its only "why" is the migration itself.

## S1 fixes from Kyle's real library — 0.45.2 (COMPLETE, pending delivery)

Two things his screenshot showed that no test could have: 182 of 570 sources sitting in **"whose last rebuild failed"**, and a
triage card offering **one price** — "$0 · about 4 h 24 min on Claude Code" — with no way to see or choose anything faster.

**1. `importance: 0` killed the whole source.** The extraction schema demanded `importance` ≥ 1 while the prompt asks for 1–5.
When the model answered 0 for a single finding it thought worthless, that one number failed the entire window's validation —
twice, because `invoke_structured` retries once — and the source's whole read was discarded with
`findings/1/importance: 0 is less than the minimum of 1`. **182 sources died of one integer.** Every consumer already treats
importance as 0-capable (`int(f.get("importance") or 0)`), so the schema was stricter than the product it validated. Now
`minimum: 0`: a 0 is a finding the model rated worthless, it sorts last, and it falls inside the low-value sweep — which is
precisely what it means. The schema NAME (`findings-v2`) is unchanged, so no `input_hash` moves and **nothing re-stales**;
Tier 1 totals are unchanged (34 / 196,951 · 9 / 30,297).

**2. The card quoted one currency.** `cost_line` was a ternary — the local time if Claude Code was configured, the API dollars
otherwise — so on a local setup the API price was computed, sent, and never rendered, and no button could reach it. A four-hour
tier looked like the only thing on offer. Each tier now carries `local_line` AND `api_line`, and every rebuild/retry row gets a
second button: **⏩ Rebuild on the API · $X**, which queues the tier and immediately moves it onto the API pool in value order,
confirming the dollar figure and the hours it saves first. It appears only when there is a real choice (local active and a
non-zero API price), so the cloud profile still shows one price and an empty tier shows none.

**Gate (test_n3 +1 → 11, test_n4 +1 → 6).** A window carrying one `importance: 0` validates while −1 and 6 still fail; the
schema name and `findings.schema_version()` are unchanged (the no-re-stale guarantee); a 0 ranks below a 1 in
`select_findings`. Both currencies appear on a populated tier, `cost_line` still defaults to the free one, an empty tier quotes
nothing, the cloud profile offers no second currency, and the fast button's fields and route both exist. Suite 462.

**Honest limits.** The API price is still an estimate from the same shared estimator, not a quote. Nothing retroactively
re-reads the 182 failed sources — the fix stops the next read failing; pressing **Retry** is what recovers them.

## S1 — the odd gap: a wrong ETA and a missing third option — 0.45.3 (COMPLETE, pending delivery)

Kyle: *"the API version is pretty expensive, while the Claude Code version is very slow. multiple hours. that feels odd."*
He was right, and both halves of the gap were our doing.

**The ETA quoted work, not wall clock.** `local_minutes` was `windows × LOCAL_MINUTES_PER_WINDOW` — never divided by
`settings.local_ai_workers`, which is 2 on his machine and spawns two independent local workers in `jobs._start_pools`. So the
free option was advertised at exactly twice its real duration: 200 sources read "about 4 h 24 min" for work two workers finish
in about 2 h 12 min. The line now divides by the pool and says so ("2 at a time"), and `local_workers` is in the payload.
Parallelism changes time and never money, so `api_cost` is untouched by it — the gate asserts that.

**There was a third option all along.** `findings.extract` is `batch_allowed=True`, `usage.BATCH_MULT` is 0.5, and
`/rebuild-stale` has always accepted `transport: "batch"` — one background batch job for the whole tier, results landing source
by source, at half the model-token price. Nothing offered it. The card presented the two extremes (free but slow / now but full
price) and hid the middle. Each tier now carries `batch_cost` and `batch_line`, and every rebuild/retry row shows three
answers. On Kyle's 200-source tier that is: **$0 · about 2 h 12 min · 2 at a time** — **📦 $4.98 in the background** —
**⏩ $9.96 now**. Both paid buttons confirm the figure and name the alternative before spending.

**Not wrong, and left alone: the API price itself.** 220 windows at $9.96 is $0.045/window, which is what a 60k-char window
(≈15k tokens in, ~600 out) costs on Sonnet 5. The estimator is honest; the presentation was not.

**Gate (test_n4 +1 → 7).** One worker vs two: same money, half the time, the label says "2 at a time" only when it is true;
the batch price is the API price at the documented multiplier and is named separately; `findings.extract` really is batchable;
`transport="batch"` really produces ONE `suggest_findings_batch` job for the whole tier rather than one per source; an empty
tier still quotes nothing; the UI reads exactly these fields. Suite 463; Tier 1 unchanged.

**Honest limits.** The 1.2 min/window constant is still one measurement from one evening on one machine, and dividing it by the
worker count assumes the workers do not contend — on a laptop under load the real figure will drift. It is an estimate the card
now labels as "about", not a promise. Batch results land when Anthropic returns them; there is no ETA for a batch.


## S5 — "capture the N that fit" bulk action — 0.45.4 (COMPLETE, pending delivery)

The last item on HANDOFF §4a's small-follow-ups list. The pool (S5, 0.43.0) always scored every item against the project's
open questions and weak areas and could tell you which ones were "worth a look" (potential ≥ 40), but capturing them meant
clicking each row. On Kyle's larger project that number can be dozens.

**Built.** `POST /api/projects/{id}/pool/capture-many` — takes the pool's own filter (`kind`, `rank_by`, `q`) plus a
threshold (`min_potential`, default 40 — the pool's own "worth a look" line) and a cap (`limit`, default 20), and captures
every item at or above the threshold through **exactly** the per-item path a single Capture click takes: a skipped source
goes through `_retry_source` (the same function `POST /sources/{id}/retry` calls), a candidate already owned as a source is
attached (`identity.attach_existing` + `candidates.mark(..., "acquired")`), and any other candidate is queued the normal way
(`jobs.enqueue("ingest_url", …)`) — never a parallel or abbreviated path, so a bulk capture cannot diverge from what clicking
each row by hand would have done. Reports what happened in the terms a person asks the question in: attached vs queued,
how many were considered, and whether more exist above the threshold than the limit captured (so pressing it again finishes
the rest rather than silently stopping at 20). UI: a **Capture the N that fit** button next to the pool's count line,
appearing only when something clears the bar, confirming the current rank/show filter before it runs.

**Gate (tests/test_n7_pool.py, +1 → 3).** A mixed pool (a linked candidate, a topically-relevant skipped source, a dated
low-relevance one) captures exactly the items at or above the threshold and none below it; the skipped source's status and
job mirror the single-retry path exactly; the candidate is attached or queued, never silently dropped; an empty result
(threshold nothing clears) is reported as "nothing at or above that threshold", not "0 captured" dressed as success; the
route and the UI's button both exist. Suite 464; Tier 1 unchanged.

**Honest limits.** `limit` caps a single call at 200 to keep it synchronous and cheap; a pool larger than that needs a second
press (the response says how many are left). Ingest jobs still go through the normal ingest pipeline and its own costs
(transcription, embeddings) — capturing is not $0 the way scoring the pool is.

## R7 — the Claims workbench (the piece R2 never rebuilt) — 0.45.5 (COMPLETE, pending delivery)

Kyle: *"we must be missing some work that I was hoping to accomplish, either in the expansion.md or in the docs in the
sub folder 'Claude outputs'."* He was right. Reading `RESEARCH-TAB.md` §5 (the original redesign brief) against what
R2 (0.44.0) actually shipped: the shell built five new panes — Overview, Open questions, Watch-outs, Areas, Research
tools — and gave Claims its own tab, but the tab itself was never rebuilt. It stayed `knowledge.state()`'s original
300-of-however-many capped, unfiltered, raw-vocabulary list (`strength`/`readiness`/`freshness_class`/`claim_type` shown
verbatim), exactly the thing §4 of the same doc diagnosed as the reason the tab overwhelms. On Kyle's larger project
that's 300 of 6,377 with no way to search, filter, or act on more than one at a time — very likely the reason "I still
have no clue how to utilize it" outlived the R2 shell that was supposed to fix it.

**Built — the Claims workbench (`claims_view.py`).** A server-side query — `GET /api/projects/{id}/claims` — over the
**full** claim set (never the 300-cap; that cap exists to keep the map/tensions/targets bootstrap small, not to hide
the majority of a project's Claims from the one page that's about them): filters compose (status, evidence level,
still-current-or-not, **needs your decision** — proposed AND strong-or-developing, area, free text), facets, four
sorts, paging. Every Claim carries one **plain-language line** built server-side (`claims_view.plain`) — "well
evidenced, may need a refresh — applies to you" instead of `strength=strong, freshness_status=needs_refresh,
application=established` — so the internals never have to be read to use the page; the raw fields stay underneath for
anyone (the chat tools, exports) who wants them. **Batch accept/reject** — `POST …/claims/bulk-status` — one verdict
on many Claims, project-scoped (a claim id from another project is skipped, not silently touched, and reported), one
`knowledge.refresh` however many were changed. UI: a filter bar, a selection checkbox per card, a bulk-action bar that
appears the moment something is selected, a pager — the same shape as the S4 findings workbench and the S1 triage
card, so nothing new to learn.

**Built — "Why this answer" and "Settle this" (§5's "Connect to the work", also never built).** Every chat citation
with a `source_id` now carries a 🧠 **why** link; `GET …/claims/for-source` returns the Claims that source's evidence
feeds (closest-locator match first, `matched_here` flagged) so a chat answer's citations open straight into the
Claims that stand behind them — accept from the dialog, or jump to the full workbench. A chat **gap** (the model's
existing `gap_noted` action, already recorded as a note) now offers **Settle this**, which is not new machinery: it
calls the same `POST …/targets` endpoint the manual "Add a target" box has always used, so a gap noticed in
conversation becomes a real, normally-escalatable Open question with nothing new to keep in sync.

**Gate (tests/test_o2_claims_workbench.py, 5).** `query` filters over the full set (never the cap), facets are counts
minus their own dimension; `plain()` contains no raw internal token for either a well-evidenced or a stale Claim;
`bulk_status` is project-scoped (a foreign claim id is skipped, never touched), refreshes exactly once, an empty
selection calls refresh zero times, a bad status is refused; `for_source` ranks the matching-locator Claim first and
returns an honest empty list for a source nothing rests on; the API routes exist and the UI wires exactly these
endpoints and function names; "Settle this" is verified to be the pre-existing `/targets` path, not a parallel one.
Suite 469; Tier 1 unchanged (34 / 196,951).

**Honest limits.** `plain()` is a translation layer, not a rewrite of the underlying model — `strength_why` and
`freshness_why` (the actual reasoning) still render as a second line for anyone who wants it; this is deliberately
"jargon behind an expander" in spirit, expressed as "headline first, detail second" rather than a literal
click-to-expand, since the detail is one line, not a paragraph. The rename §5 asked for (Strength → Evidence,
Evidence Target → Open question, etc. as PERMANENT UI labels everywhere, not just here) is only done inside the
workbench and the "why" dialog — the Research tools pane (the old Knowledge Map / Tensions / Targets lists, kept for
completeness) still shows raw labels, since renaming a page nobody asked to keep felt lower value than shipping the
part that was actually missing.

## S6 + R8 — grouped views (Sources, Findings, Claims) — 0.45.6 (COMPLETE, pending delivery)

Kyle: *"I care most about getting organized around our structure and the content we already have. right now when I
look at sources, or findings or research, its one GIANT list I have to scroll endlessly through. filters are ok but
its just a big mess... we can strategize on rescanning and deduping later."* This is `PRODUCT-ORGANIZATION.md` item
#1, taken narrowly and on purpose: grouping, not rescanning, not dedup — those stay queued.

**Built.** All three surfaces now group instead of running as one flat list, and all three needed no new scanning or
schema — the grouping key already existed on every row, it was just never read by the view that lists them:

- **Sources** groups by *origin* — `s.channel`, the column `community.py` already sets to the subreddit name, YouTube
  already sets to the channel name, `epub.py` to the book's creators, and `webpage.py` to the domain. `srcGroupKey`
  falls back to a platform label only for the few rows with no channel at all. `<details class="fgroup">` per group,
  a header with the count, an "Expand all / Collapse all" pair, and `SRCG.collapsed` remembers which groups a person
  closed by hand across re-renders (a new source landing, a filter change). A search or an active chip/value filter
  forces every group open — grouping must never hide a match. Below 5 groups nothing is grouped at all (there is
  nothing to declutter).
- **Findings** already grouped by source (0.43.0) — the gap was that the groups could never collapse, so a project
  with many sources was still one long scroll of *open* groups. Same `<details>` treatment, same remembered-collapse
  behaviour (`FGRP`), same "never hide a match while searching" rule.
- **Claims** gets its first grouping: by *Area* — the same clusters the Overview and Areas panes already compute
  (`research_view.areas`). `claims_view.query` now computes `area_of_claim` unconditionally (previously only when
  filtering to one specific area, since nothing else needed it) so every returned Claim carries an `area` even when
  browsing all of them. A **Group by area** checkbox (default on, off automatically the moment an Area filter narrows
  the page to one area already) plus the same `<details>`/Expand-all/Collapse-all pattern (`CWG`).

**Honest limits.** This groups the *current page* of a paginated view (30–100 rows), not the underlying resultset —
consistent with how Findings already grouped before this rung. `channel` is a plain string, so two channels that
happen to share an exact name (rare) group together; a real Collection object (`collections`/`source_collections`,
already in the schema from G3) would disambiguate that, but reading a column already on every row shipped this
without it. Rescanning a channel/subreddit as a first-class object (#8) and adaptive/learning triage (#19/#21) and
findings deduplication remain **NOT BUILT**, exactly as `PRODUCT-ORGANIZATION.md` said — this rung is grouping only.

## S1 fix — an out-of-credit account failed jobs with a raw SDK error instead of pausing — 0.45.6

Kyle, live: an `extract_claims` job showed `error: BILLING after 1 attempt: Error code: 400 - {'type': 'error', ...
'message': 'Your credit balance is too low...'}` in the Sources progress card. `providers.classify_error` already
typed this correctly as `BILLING` (non-transient, never retried) — but unlike `SPEND_CAP` (the Anthropic Console's
*usage limit*, which names a resume date and gets a plain-language pause + banner), a `BILLING` error (the account's
*credit balance*, which names no date) fell through to the generic path and was marked `failed` with the exception
text verbatim as the job's message.

**Built.** `jobs.execute` now parks a `BILLING` error the same way it parks `SPEND_CAP` — `queued`, `wait_reason`
`budget`, 0 attempts, 0 cost — with a plain sentence ("the Anthropic account's credit balance is too low — add
credits in Plans & Billing to continue") instead of the raw exception, retried on a fixed 30-minute interval since
(unlike the usage limit) there is no date to wait for. `providers.py` clears the flag the moment any call actually
succeeds, so the banner disappears as soon as credits are back rather than waiting out the retry window. `/api/usage`
surfaces it exactly like the usage-limit banner (`billing_blocked_until`, folded into `blocked`).

**Gate (tests/test_l1_browser_capture.py, +1 → 13).** A `BILLING` exception parks the job (queued, `wait_reason`
`budget`, 0 attempts), the message names the real cause and never the raw SDK text, `/api/usage` reflects the pause,
and a subsequent successful call clears it. Suite 470; Tier 1 unchanged (34 / 196,951; findings 9/30,297; plan 2).

## S1 fix — a skipped source's fetched metadata was thrown away, and the pool's value scan never reached it — 0.45.7

Kyle, live, on the 0.45.6 grouping delivery: *"sources that were beyond the cutoff are not showing thumbnails, and
are not giving any indication on whether they still may be of value to ingest."* Not a grouping regression — both
were true before 0.45.6 too, just harder to notice as a flat list.

**Root cause 1.** `ingest.ingest_source`'s cutoff check runs AFTER `media.fetch_info` already succeeds — the
metadata (thumbnail, channel, published date, description) is real and in hand — but the skip branch called
`db.set_source_status(source_id, "skipped", reason)` and returned, discarding everything `media.info_to_source_fields`
had just fetched. A skipped row kept only what the LISTING stage saw (bare title, maybe duration), which is why it
never had a thumbnail: the metadata that would have supplied one was fetched and thrown away in the same breath.

**Root cause 2.** The $0 "is this worth ingesting anyway" scan (`candidates._potential`) has existed since S5
(0.43.0) — but only inside `candidates.pool()`, the separate "🔎 Known, not captured" view. The ordinary Sources
list a person actually scans (`GET /api/sources`) never called it, so a skipped row sitting right there in the
Skipped filter gave no hint either way without switching views.

**Built.** `ingest.ingest_source`'s skip branch now saves the fetched fields (title, channel, channel_url,
published_at, duration, description, thumbnail_url, language) via `db.upsert_source` before returning — same fields
the non-skip path saves, same source row, just with `status="skipped"` and the cutoff reason as `error` instead of
proceeding to transcript/chunks. `api_sources` now runs the same `candidates._potential` scan `pool()` does — same
`_gap_terms`, same relevance input — for every `skipped` row in a project response and attaches `pool_potential`
(`score`, `fits`, `why`); the Sources card shows it as a "🔎 worth a look — NN/100" or "🔎 low potential — NN/100"
tag with the reasons on hover, right next to the row that finally has its thumbnail back. A ready/non-skipped row
never carries the field — there's nothing to score.

**Gate.** `tests/test_core.py::test_age_cutoff` extended: a skipped source's `thumbnail_url`/`channel`/`published_at`/
`description` match what the fake `fetch_info` returned, and its `error` still names the cutoff. New
`tests/test_n7_pool.py::test_skipped_sources_carry_the_pool_potential_scan_on_the_plain_sources_list`: `/api/sources`'s
`pool_potential.score` for a skipped row equals what `candidates.pool()` computes for the same source (same scan,
never a second one that could drift), a higher-relevance/timeless/on-topic source outscores a dated one exactly as
the pool ranks them, and a non-skipped row never carries the field at all.

**Backfill for existing skipped sources.** The `ingest.ingest_source` fix only helps sources skipped from now on —
Kyle's existing skipped sources (saved before this release, often with no thumbnail) needed a separate path. Built
`ingest.refresh_skipped_metadata(source_id)`: refuses on anything not currently `status="skipped"` (this is a
display backfill, never a re-ingest route), otherwise re-runs `media.fetch_info`/`info_to_source_fields` and
re-upserts the fields while keeping `status="skipped"` and the original cutoff `error` untouched. `POST
/api/projects/{id}/sources/refresh-skipped-metadata` (`only_missing=True` by default) queues one
`refresh_skipped_metadata` job per matching skipped source; the Sources tab's "🔄 Refresh info" button (next to
"⏵ Ingest all N anyway", shown whenever a skipped row is missing a thumbnail) calls it. Job kind added to `RETRYABLE`.

**Gate.** `tests/test_core.py::test_age_cutoff` extended: a skipped source's `thumbnail_url`/`channel`/`published_at`/
`description` match what the fake `fetch_info` returned, and its `error` still names the cutoff. New
`tests/test_n7_pool.py::test_skipped_sources_carry_the_pool_potential_scan_on_the_plain_sources_list` and
`test_refresh_skipped_metadata_backfills_thumbnails_without_changing_status` (queues only rows missing a thumbnail,
running the job updates thumbnail/channel/description while status/error stay `skipped`, refuses on a non-skipped
source, a repeat call queues nothing). Suite 472; Tier 1 unchanged.

**Honest limits.** The backfill button re-fetches metadata only, one HTTP request per source, same network path as
first ingest (yt-dlp) — it does no transcript/chunk work and never changes a source's status, so it's safe to run
broadly but Kyle still has to click it (never auto-queued on his behalf).
