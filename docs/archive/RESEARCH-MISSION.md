# MISSION: REBUILD THE NEURO SEARCH RESEARCH EXPERIENCE

*Kyle's mission, filed 2026-09-08 for a dedicated session. Read together with `RESEARCH-TAB.md` (how the current tab works and why it overwhelms) and `CLAUDE.md` (architecture map, standing rules). Sequenced in EXPANSION.md as a UX rung on G5's surface; phases R1–R12 below.*

This is not a cosmetic cleanup of the existing Research page. The current Research tab exposes a sophisticated research engine as though the user is supposed to operate the engine manually. The evidence model is valuable, but the UX is confusing, overwhelming, and unclear about: what the user should do next; why anything matters; what each button actually does; what happens if the user does nothing; which operations cost money; which operations change Chat / Planner behavior; which states are informational versus actionable; what "finished" or "good enough" research looks like.

Your mission is to rebuild Research into a human-facing research control center while preserving the hardened evidence architecture underneath it.

## NORTH STAR

Research should make a large project feel smaller. When I open Research, I should be able to understand within approximately five seconds: (1) What does Neuro Search currently understand? (2) What important things are still unresolved? (3) What could materially change my decisions or plan? (4) What should I work on next? (5) What can Neuro Search do for me to improve the evidence?

The normal user must NOT need to understand the internal research architecture in order to use it. The product should expose outcomes and decisions. The backend may continue to use Claims, Strength, Readiness, Freshness, Tensions, Evidence Targets, governing/corroborative sufficiency, lineage, normalisation, etc. The normal UX should not require the user to learn those terms.

## A. FIRST: STUDY THE EXISTING SYSTEM

Before changing code: read RESEARCH-TAB.md completely; read CLAUDE.md; read the relevant current implementations (claims.py, knowledge.py, works.py, community.py, qa.py, db.py, api.py, web/index.html); inspect the current Research API contract and endpoints; inspect the existing tests covering Claims, works/lineage, communities, completeness, chat research state, and release gates; run the existing test suite before making changes; inspect the current live Research UI implementation (renderResearch, resMap, resTensions, resTargets, resClaims, refreshResearch, evaluateNormalisation, loadEvaluation, claimStatus, tensionStatus, targetStatus, addTarget, pursueTarget, renderResearchHeader, sidebar Research count); use the current live accounting-practice acquisition project as a stress case — it has thousands of Claims and demonstrates why a raw list cannot be the primary interface.

Do not begin by rewriting the evidence engine. This mission is primarily information architecture, UX semantics, prioritization, aggregation, and navigation around the existing research state.

## B. LOCKED ARCHITECTURAL INVARIANTS (do not break)

1. Claims are PROJECT state, never global-library state.
2. The Research system must remain useful with ZERO model calls.
3. Model-generated state is proposed state only. User-owned Claim status changes still go through the existing explicit status mechanism.
4. Strong evidence does NOT mean decision-ready. Keep orthogonal: how well supported is this? · is it current? · does it apply to the user's situation? · has the user chosen to rely on it?
5. Freshness remains Claim-relative and errs toward uncertain rather than pretending something is current.
6. Evidence independence remains lineage-aware.
7. Person/creator independence remains relevant where appropriate.
8. Community evidence must never establish a governing rule by itself.
9. Partial community/thread synthesis must remain explicitly qualified as partial.
10. Evidence pursuit preserves the escalation order PROJECT → GLOBAL LIBRARY → SEEN / CANDIDATE INDEX → WEB; the web is used only when explicitly requested.
11. Normalisation remains bounded and importance-driven, never a corpus-wide uncontrolled model operation.
12. Do not create a parallel research, ingestion, discovery, provenance, or memory architecture. Use the existing hardened systems.
13. Preserve database safety rules: additive schema changes only; no destructive migrations; no direct external DB writes; normal API/job/usage patterns; cost accounting for model calls.
14. Preserve existing chat regression gates unless a change is genuinely required. Do not casually rewrite the research block in the Chat system prompt and trigger unnecessary frozen-total churn.

## C. THE CORE UX CHANGE

The Research page is no longer Knowledge Map → Tensions → Evidence Targets → Claims as giant lists on one page. Those are four different jobs — orient, identify risk, plan research, inspect individual beliefs — and must not have equal visual weight. Create a hierarchy. Primary: **[ Overview ] [ Questions ] [ Knowledge ]**. Advanced/secondary: Claims; Research history if useful; Research diagnostics / tools. CLAIMS MUST NO LONGER BE THE DEFAULT EXPERIENCE: a normal user can use Research effectively without ever opening the raw Claims workbench.

## D. OVERVIEW: THE NEW DEFAULT VIEW

Research opens to OVERVIEW, whose purpose is "WHAT SHOULD I PAY ATTENTION TO NEXT?". Plain-language orientation ("See what Neuro Search understands, what still needs checking, and what would most improve your project."), then a compact project status — e.g. "8 of 12 important questions settled · 3 issues could materially affect your plan · 2 important areas should be refreshed · 1 major area needs better coverage" — never raw Claim counts. Then WHAT TO WORK ON NEXT: at most 3–5 recommended items by default, never a dump of every tension or target. Each recommended action must explain: WHAT is unresolved; WHY it matters; WHAT we currently know; WHAT is missing or questionable; WHAT happens if the user does nothing; WHAT action Neuro Search recommends; WHAT the button will accomplish.

Example: *Confirm how seller financing affects your SBA structure — High impact · Acquisition Financing. Why this matters: your current financing plan depends on this assumption. Current state: useful practitioner evidence but no current authoritative confirmation. If left unresolved: Chat and the Master Plan should continue treating this as uncertain. Recommended action: check existing research for authoritative evidence. [Search my existing research] [Why?]* Actions describe outcomes, not implementation verbs.

## E. PRIORITIZATION ENGINE

Research must not sort by creation date. Create a deterministic priority/ranking layer for actionable Research items that works without a model call, using state such as: importance; links to project goals / facts / plan; governing vs corroborative need; evidence weakness; contradictions; stale/currentness concern; missing perspective; unresolved user applicability; open evidence target; blocking vs non-blocking relevance where available; magnitude of downstream impact; whether the item affects multiple Claims; whether the issue already has promising Candidate Index sources; recency of changes. The formula is implementation-specific but must be deterministic, testable, inspectable, stable and documented. Do not use an LLM to decide what appears first; a model may optionally improve labels or grouping additively, but the core must function at $0.

## F. QUESTIONS: REPLACE "EVIDENCE TARGETS"

User-facing term: Evidence Target → **Open Question**. The Questions page answers "What do we still need to figure out?". Each Open Question shows: human-readable question; why it matters; current understanding; missing evidence; what would be enough to settle it; where Neuro Search has already looked; promising existing candidates; recommended next action; status. Do NOT expose governing/corroborative as the primary vocabulary — translate: governing → "One current authoritative source can settle this."; corroborative → "This needs independent confirmation." Preserve the exact internal escalation project → library → Candidate Index → web, exposed conversationally ("Already checked: ✓ This project ✓ Your library · 3 previously discovered sources may help [Check those 3 sources] [Find new evidence online]").

## G. ACTION SEMANTICS: FIX THE BUTTON PROBLEM

Current buttons (Refresh · Normalise Claims · Evaluate normalisation · Resolved · Dismiss · Look (60) · + web · Close · Accept · Applies to us · Reject) are ambiguous. PRODUCT RULE: **no button may appear in Research unless a reasonable first-time user can predict both what will happen and why they would want that outcome.** Replace operation labels with outcome labels: Refresh → "Check for research changes"; Pursue/Look → "Search my existing research" or "Check 3 promising sources"; + web → "Find new sources online"; Close → split into "This question is settled" / "Not important to my project". *Resolved* should generally NOT be a manual button for automatically detectable evidence conditions: **the user resolves decisions; the system resolves evidence conditions** — if a stale Claim becomes current because a new governing source arrives, the system clears/updates the stale Watch-out automatically. Dismiss becomes a meaningful user decision ("Not important to my project") with explanatory copy.

## H. ACTION CONSEQUENCE PREVIEWS

Important actions get lightweight explanations (concise subtext, tooltips, inline disclosure; confirmation only for destructive/high-impact cases — no modal hell). Examples: *Search my existing research* — "Checks this project, your global library, and previously seen sources. No web search." · *Find new sources online* — "Looks outside your library and proposes sources for review before ingestion." · *Use in project* — "Tells Neuro Search you are willing to rely on this Claim as a project belief. Chat and planning may use it accordingly." · *Doesn't apply to me* — "Keeps the Claim in the research record but prevents it from being treated as applicable to your situation." · *Not important to my project* — "Removes this issue from your attention queue. It does not delete the underlying evidence." · *Reject Claim* — "Marks this Claim as rejected and prevents it from being treated as established project knowledge."

## I. WATCH-OUTS: REPLACE RAW "TENSIONS"

User-facing term: Tension → **Watch-out**. Do NOT expose an unbounded raw feed (STALE STALE STALE NOVEL WEAK CONSENSUS …). Aggregate related tensions into human-meaningful ISSUES — e.g. *Your valuation assumptions may be outdated — High impact · Business Valuation. 11 related Claims rely on older market evidence. This could materially change which asking prices look attractive. Recommended: find current valuation evidence. [Update this research] [See why]*. One Watch-out may represent 17 underlying stale Claim-level tensions; the user solves the ISSUE, not 17 rows. Other examples: not enough independent evidence for this tax strategy; sources disagree about seller-note standby requirements; we are hearing mostly from buyers and not sellers; a potentially important minority viewpoint has little corroboration; a governing source may have been superseded. Retain the detailed tensions in the advanced inspector.

## J. KNOWLEDGE: TURN THE MAP INTO NAVIGATION

The current map is an index of token-like rows (account, annual, asset, both, buyer, build, capital, year) — not a human Knowledge Map; do not display internal topic tokens as primary navigation. Create a user-facing **Research Area** layer: stable, human-readable clusters over lower-level topics (for the acquisition project, the desired level is things like Acquisition Financing, SBA Rules, Seller Financing, Business Valuation, Deal Structure, Due Diligence, Cash Flow & Debt Service, Taxes & Entity Structure, Owner Transition, Employees & Benefits, Search Strategy, Post-Acquisition Operations — examples of the semantic level, NOT hardcoded categories; the implementation must support arbitrary projects). Must function without a model call: derive from normalised topics, project brief/steering, Claim type/topic metadata, targets, tensions, source/category information; an optional bounded model pass may improve naming/grouping but no critical UX depends on it. Suppress garbage/non-navigational topics aggressively. A Research Area card summarises state ("Business Valuation — Developing. What we understand: … Needs attention: 3 important questions remain; most market multiple evidence is aging. [Explore]") and drills into current understanding, confident conclusions, unresolved questions, watch-outs, key evidence, relevant Claims, related sources. The map becomes navigation, not telemetry.

## K. CLAIMS: ADVANCED WORKBENCH

Claims remain important as a filterable workbench and inspector under Advanced → Claims (search; topic / Research Area filter; needs my decision; accepted / used in project; rejected; weak evidence; needs updating; applicability undecided; evidence class; freshness; pagination; sorting; safe batch actions). Never render thousands of Claims as a raw list. Collapsed row: statement · Evidence: Strong · Still current?: Needs checking · Applies to my situation?: Not decided · [Review]. The inspector exposes the internals (text, qualifiers, type/topic, strength, supporting/contradicting evidence, provenance, lineage, source revision, freshness reasoning, independence, related Claims, application note, history) — internal jargon belongs here.

## L. FIX CLAIM DECISION SEMANTICS

"Accept | Applies to us | Reject" mixes dimensions. Separate: QUESTION 1 — *Do I want Neuro Search to rely on this as an established project belief?* Use in project / Leave undecided / Reject. QUESTION 2 — *Does this apply to my situation?* Yes / No / Not sure, with an optional note. Preserve the backend distinctions: strongly evidenced + current + not applicable is valid; strongly evidenced + applicable + not adopted is valid. Do not collapse these states.

## M. HIDE ENGINEERING INSTRUMENTS

Remove from the ordinary Research UI: Normalise Claims (model), Evaluate normalisation, evaluation cohort controls, evaluation statistics/readout, developer diagnostics. Move to Settings → Advanced → Research diagnostics (or a clearly advanced Research tools area). If normalisation deserves a user-facing operation, expose the OUTCOME ("Improve research organization — we found likely duplicate or poorly classified Claims… [Improve organization]") and show cost before any paid action.

## N. RESEARCH SIDEBAR COUNT

The badge must represent USER-ACTIONABLE ATTENTION (important unresolved Open Questions; high/medium Watch-outs requiring the user; Claims genuinely awaiting an explicit decision), not total Claims. Choose a clear definition, document it, test it; cap at 99+ if appropriate. The raw Claim count belongs in the advanced workbench.

## O. RESEARCH PROGRESS

Give a sense of progress without fake certainty: count/state summaries ("8 of 12 important questions settled · 3 issues need attention · 2 areas need fresh evidence · 1 area has weak coverage"), never a universal "87 % researched" unless its semantics are defensible. Show positive change too ("Recently improved — ✓ Seller transition question strengthened: new evidence from 3 independent sources · ✓ SBA eligibility updated: current governing evidence found"). Research should not feel like a permanent warning dashboard.

## P. CONNECT RESEARCH TO THE REST OF THE PRODUCT

Research is a SYSTEM capability; the tab is where the full state is inspected. CHAT: a weak/qualified answer can expose "Research gap — … [Research this]"; a citation/answer inspector can show Evidence / Current? / other evidence counts / [Open in Research]; a "Research this answer" workflow identifies unresolved Claims/questions → inspects project evidence → global library → Candidate Index → proposes external research only if needed → estimates cost → presents an operation for approval — orchestrating existing systems, never a new retrieval mechanism. MASTER PLANNER: research-blocked plan items link to the Open Question; research resolution can affect planner readiness through existing state. DISCOVER: explain why a proposed source matters ("may answer an open question about …"); Research calls Discover, never duplicates it.

## Q. COST AND SAFETY AFFORDANCES

Make $0 vs paid visible where useful ("Search my existing research — $0"; "Find new sources online — may use model/web-search budget"; "Improve research organization — estimated cost $X.XX"). Not every button needs a price tag, but no paid action may look indistinguishable from a free state update. Use the existing usage.guard and usage recording.

## R. EMPTY STATES AND SMALL PROJECTS

Design for a brand-new project, 1 source, 20 sources, and the 449-source / 4,203-Claim stress case. No Claims: "Approve Findings and Neuro Search will begin building your project's research state." No Open Questions: "No important unanswered questions are currently tracked." No Watch-outs: "No major evidence problems need your attention right now." No Research Areas: a useful onboarding state, not empty boxes.

## S. RESPONSIVE DENSITY

Fix information density with card hierarchy, progressive disclosure, readable line length, whitespace, clear primary/secondary actions, collapsible detail, counts as supporting information — not by enlarging fonts. The information architecture must change.

## T. IMPLEMENTATION APPROACH

Prefer adapting the existing API/state; add narrow derived fields/endpoints/helpers for overview summary, priority ranking, grouped Watch-outs, Research Areas, actionable sidebar count, question summaries, consequence metadata — deterministic derived state where possible. Avoid materialising derived data into new tables without strong reason; if persistence is required: additive migration, documented ownership/lifecycle, explicit refresh/idempotency. Do not let front-end JavaScript be the only place important semantics are computed; keep ranking/grouping rules testable in Python.

## U. USER-FACING VOCABULARY

Strength → Evidence · Readiness → Ready to use? · Freshness → Still current? · Evidence Target → Open Question · Tension → Watch-out · governing sufficiency → One authoritative source can settle this · corroborative sufficiency → Needs independent confirmation · application → Applies to my situation · Accept → Use in project · Pursue → Search my existing research · external pursue → Find new sources online · Normalise → hidden / Improve research organization · Evaluate normalisation → hidden entirely. Do not rename backend concepts for cosmetic consistency; keep internal terminology where changing it adds migration risk.

## V. THE PRODUCT LOOP

The user only needs: (1) add and approve useful research; (2) Neuro Search organises what it learns automatically; (3) open Research to see what needs attention; (4) resolve important Open Questions; (5) review individual Claims only when judgment is needed; (6) new evidence automatically improves the state. Underneath: Findings → Claims → evidence + applicability + currentness → Knowledge / Watch-outs / Open Questions → Project → Library → Seen → Web → new evidence ↺.

## W. LADDER (disciplined rungs; no giant rewrite)

- **R1 Baseline + contract** — run the suite; document current state/API; record live stress-case metrics; list every user-facing control, what each mutates, what costs money, Chat/Planner consequences, existing auto-resolution behaviour, sidebar-count semantics. Deliverable: a short implementation note. Exit: suite green, no behaviour change.
- **R2 Research shell + navigation** — Overview / Questions / Knowledge / Advanced → Claims / Advanced → diagnostics; move/hide Normalise, Evaluate, raw Claim list, raw tension list. Exit: Research opens to Overview; thousands of Claims no longer render on first load; underlying actions remain reachable.
- **R3 Overview + actionable priority** — deterministic summary, priority scoring, top 3–5 next actions, attention count, empty states, recently-improved summary if feasible; every card carries why / current state / gap / recommended action. Exit: the 449-source project opens with ≤ 5 recommended items.
- **R4 Open Questions** — the view, plain-language sufficiency, pursue trail, $0 path, external path, status semantics, promising-candidate count/actions; outcome-named controls. Exit: a user unfamiliar with Evidence Targets understands why, what "enough" means, where it looked, what each action does.
- **R5 Watch-out aggregation** — grouped Watch-outs, impact/priority, drill-down, automatic resolution/update on evidence change, "Not important to my project". Exit: many Claim-level tensions collapse into a few meaningful issues.
- **R6 Knowledge / Research Areas** — areas, garbage-topic suppression, stable grouping, summaries, state, drill-down filtering Claims/Questions/Watch-outs by area; no model call for baseline. Exit: the live project shows human-level domains, not "both", "year", "asset".
- **R7 Claims workbench** — filtering, search, pagination, sorting, area drill-down, needs-decision/weak/stale/accepted/rejected/applicability-undecided, safe batch actions, inspector; Use-in-project separate from Applies-to-me. Exit: the 20 Claims that matter are findable without reading 4,203 rows.
- **R8 Button / consequence system** — audit every button: outcome label, microcopy, paid/free, state consequence, Chat/Planner consequence, reversibility. Exit: no unexplained Resolved / Dismiss / Look (60) / + web / Close / Accept / Applies to us / Normalise / Evaluate in the normal UI.
- **R9 Cross-product entry points** — Chat gap → Open Question; Chat evidence inspector → Claim; "Research this"; Planner blocked item → Open Question; Discover suggestion → related question reason. Existing orchestration only. Exit: users benefit from Research without visiting the tab.
- **R10 Scale + responsive UX** — rendering, payload sizes, pagination, filters, grouping, load time, narrow widths, 1-source and 4,000-Claim projects; summaries from the API instead of thousands of rows. Exit: responsive on the real large project.
- **R11 Tests + regression gates** — priority ordering; attention count; Watch-out aggregation; Research Area grouping/fallback; escalation order; web never without explicit request; status and applicability independent; strong ≠ decision-ready; stale/currentness; lineage independence; community governing restriction; zero-model path; sidebar count; API pagination; existing status semantics; auto-resolution; cost accounting. Keep test_k6_claims, test_k8_works, test_k9_community, test_l2_completeness and the chat gates green; do not weaken tests to pass.
- **R12 Documentation + release** — update RESEARCH-TAB.md (final product), CLAUDE.md, README if appropriate, new contracts; run pytest, release-check, doctor, a live smoke test on the large project; test the manual flow (open Research → know the next action without scrolling Claims → open a Question → search existing research → see Candidate Index results → understand when web search would occur → drill into a Knowledge area → inspect one Claim → set Use in project → separately set Applies to my situation → return to Overview and see progress update → verify Chat still hedges unresolved evidence); bump the version by existing conventions. Not complete merely because the page looks nicer.

## X. ACCEPTANCE CRITERIA (all must hold)

1. A first-time user opens Research and knows what to do next. 2. The normal experience does not expose thousands of Claim rows. 3. Nor engineering evaluation tooling. 4. Raw topic tokens no longer serve as the primary map. 5. Evidence Targets read as understandable Open Questions. 6. Raw tension rows aggregate into meaningful Watch-outs. 7. The user is not expected to manually resolve evidence conditions the system can detect. 8. Every normal button communicates its outcome. 9. Paid vs free is distinguishable. 10. "Use in project" and "Applies to my situation" are separate decisions. 11. Claims are navigable/filterable. 12. Evidence, applicability, freshness and acceptance stay separate states. 13. Independence/lineage behaviour unchanged. 14. Community evidence still cannot establish governing claims. 15. Pursuit still escalates project → library → seen → web. 16. Web search still requires explicit intent. 17. Core Research works with zero model calls. 18. The sidebar no longer equates raw Claim count with homework. 19. Chat/Planner can direct users into Research. 20. The live large project feels materially simpler. 21. Existing regression and release gates stay green. 22. No parallel architecture was introduced.

## Y. DESIGN PRINCIPLES FOR JUDGMENT CALLS

Show meaning before metadata; the problem before the diagnostic; the recommended action before advanced controls. Aggregate machine-generated complexity before presenting it. Progressive disclosure beats giant lists; outcome labels beat implementation labels. The system does automatically what it can determine automatically; ask the user only for genuine judgment. Preserve uncertainty rather than fake confidence. Never let UI tasks scale linearly with Claims. A large corpus should make the user feel more informed, not more burdened. Research is decision support, not an evidence database console. Claims power the product; Claims are not the product. Research is a system capability; the tab is its control center. The primary question is always "What should I pay attention to next?"

## Z. EXECUTION INSTRUCTION

Proceed autonomously through the ladder unless a genuine architectural decision conflicts with a locked invariant. Do not stop after mockups — implement. Do not discard working evidence logic because its UI is poor. Small, reviewable changes; keep the app runnable; targeted tests after each rung; the full release gate before completion. At checkpoints report what changed, why, what remains, tests run, migration/API implications, concise UI descriptions, the next rung. The final deliverable is a Research experience that converts the evidence graph into clear understanding, prioritized uncertainty and obvious next actions without sacrificing the epistemic safeguards that make the system trustworthy.
