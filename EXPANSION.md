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

