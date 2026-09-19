# Subreddit catalog, ranking, selected capture, and refresh

Status: ACTIVE — partial implementation landed; corrective ladder SUB-R0–SUB-R9 is open. NOT FEATURE-COMPLETE OR RELEASE-VERIFIED.
Revised: 2026-09-19. Planner and executor: Codex. Claude is no longer executing this mission.
Planning baseline: `2231049e7fb388e7e000d186bfb1fec304b8e720`. Execution baseline: `09be5579ee85c333182beffea437ef9566187e8b` in isolated worktree `/private/tmp/neuro-subreddit-catalog` on `codex/subreddit-catalog`.

## 1. Hard planning gate and executor

Kyle requested review and revision of the supplied whole-subreddit brief, with execution by Codex instead of Claude/Fable. This document supersedes that brief's provisional ladder and agent/model assignments. Its product intent remains: a reusable subreddit catalog, project-relative recommendations, selected thread acquisition, local Research reuse, manual refresh, and honest coverage.

The original Phase A permitted inspection, safe source-only checks, and planning-document edits; it is complete. The original plan-only restriction ended with Kyle's subsequent execution instruction. The current request, “Make the ladder,” is a documentation task: reconcile the remaining work here without starting corrective runtime implementation in this turn.

Phase B began when Kyle explicitly instructed Codex to execute on 2026-09-19. Changing a model setting alone remains insufficient authorization. The executor must not switch models, invoke another coding model, create tasks, or delegate on the basis of this document. Recommendations below are advisory; Kyle controls the execution configuration.

After authorization, Codex executes eligible work through this ladder without seeking routine engineering direction. No Claude handoff, Claude session, or waiting for Claude is part of this mission. This does not alter Neuro's internal model/provider contracts or remove its existing local Claude Code adapter.

This is the single canonical mission, under `docs/` because `neurosearch/repo_check.py::ROOT_FILES` does not allow a new root `SUBREDDIT-CATALOG-MISSION.md`. Changing runtime Python merely to admit a planning document would violate Phase A. HANDOFF points here; do not create a second copy.

## 2. Repository reconciliation and limits of this review

**Current correction baseline: `7b43dc884e0da08e961506348b6152d6afe79ae2` on `main`, tracked tree clean before this documentation edit.** The partial implementation was already fast-forwarded into the shared checkout through `7fdcd2a`; that is delivery of code, not acceptance of the feature. HANDOFF's later CHR2 closure supersedes the earlier unfinished-CHR2 note. Preserve unrelated untracked work. The records below describe the original planning baseline, not today's working tree. For correction work, isolate from the then-current `main` and record any newer changes; do not blindly reuse the older worktree snapshot.

Read: AGENTS, HANDOFF's standing mechanics and recent checkpoints, CLAUDE, QUALITY-CONTRACT, latest State (2026-09-17-1130), operating-system priorities, Foundation's historical status, scheduler and execution-ladder orientation, relevant source and tests. No live database or credentials were opened. No live catalog, source acquisition, model invocation, or test server was started.

The newest State snapshot is older than current code. HEAD is `2231049`, not the State's `d1b6a67`; the working-tree package marker is `0.63.94`. This does not establish the running app version or a passing release for this dirty tree. Old test counts and old statements that a lane belongs to Claude are not current evidence.

Preserve all pre-existing work. At initial inspection, modified tracked paths were HANDOFF, `docs/COURSE-SCANNER-2026-09-15.md`, `extension/{manifest.json,popup.html,scan-lib.js}`, `neurosearch/{__init__.py,courses.py,ingest.py,webpage.py}`, `neurosearch/web/js/{sources.js,state.js,utils.js}`, `pyproject.toml`, and `tests/test_s32_course_scanner.py`. Untracked work includes `tests/test_s55_course_documents.py`, `tests/test_s64_sources_listing_order.py`, `tests/fixtures/courses/courses/cards.html`, `.chr2_livetest/`, reference directories and release artifacts. Do not stage, discard, normalize, or delete these as part of this mission.

The latest HANDOFF also records unfinished CHR2 acceptance and fixes inside `.chr2_livetest/worktree/`, including `db.py` and `web/js/chats.js`. Preserve that directory and its work. CHR3 remains outside this mission. Execution authorization for this mission should be recorded as its admission in PRODUCT-SCHEDULER, with other work suspended at its actual checkpoint; it must not silently close CHR2 or reopen another ladder.

Before implementation: re-read diffs and recent checkpoints, record a Resume Delta, and construct an isolated source snapshot containing the intended current code and necessary pending changes. A clean HEAD-only worktree would omit relevant course/Sources changes. Do not copy `.env`, live data, cookies, media, or `.chr2_livetest` into the execution workspace. Record baseline, included patches, source hash, and isolation path. Never broadly stage the shared checkout.

Phase A validation: the pure source-only `repo_check.check_repo` runner returned PASS before and after planning edits; `git diff --check` passed, and the planning-gate/rung/test-filename checks passed. Only this mission and the short HANDOFF pointer were edited for this task. Full pytest, Tier 1, and release-check were not run in this planning phase; no runtime correctness or release claim is made. A fresh isolated baseline is the first Phase B requirement.

## 3. Original pre-implementation inventory (historical)

This inventory explains the original architectural choices. Section 5 is the current gap inventory and execution order; this table must not be read as a claim that no implementation exists today.

| Responsibility | Existing owner and evidence | Mission delta |
|---|---|---|
| Classify and route pasted input | `resources.classify/route`, `api_add`; `tests/test_k3_resources.py` | Subreddit URLs currently get generic Community detected with an unavailable Explore action. Recognize exact subreddit containers and enable catalog routing; keep thread routing intact. |
| Reddit metadata discovery | `community.enumerate_reddit/explore`; G7 in `tests/test_k9_community.py` | Existing search is one bounded page (up to 100), query-driven, with no durable cursor or listing coverage. Add listing pagination through the existing API owner. |
| Reddit access | `community._oauth_token/_api_get`, `safe_fetch`; existing JSON/HTML and extension thread paths | Reuse OAuth and safe-fetch. Preserve response rate-limit details for durable retry. Do not scale the public JSON/HTML fallback chain into a bulk crawler. |
| Collections | `db.upsert_collection`, `project_collections`, `source_collections` | Add `kind=subreddit` using the existing unique `(kind, external_id)` identity. Candidate membership is missing; origin JSON is not that relation. |
| Metadata-only rescans | `reservoir.rescan/rescan_project`, tests S55/S57 | Already preserves decisions and project-scoped scan fingerprints, but hardcodes YouTube and materializes the whole listing. Extend this owner for Reddit; preserve existing YouTube contracts. |
| Candidate identity/state | `candidates.remember/mark`, `candidate_projects`; K4/M3 | Global `(platform, external_id)` uniqueness exists. Reddit discovery uses `reddit / reddit:<post-id>`, while thread Sources use `community / reddit:<post-id>`. Reconcile this boundary explicitly. |
| Candidate metadata | `candidates.remember` and FTS | Existing updates only fill empty fields. Comment count, flair, precise creation time, outbound URL and durable subreddit metadata are missing; current Reddit search drops most of them before storage. |
| Ranking and review | `community.rank_candidates`, `candidates.pool`, `_potential`, `gap_terms_cached`, revision cache; N7/S30/S34/S35 | Ranking already exists. Add collection scope, persistent metadata signals, explanations and bounded paging. Current pool returns a limited prefix, not general paged catalog browsing. |
| Capture | `candidates.capture` → `jobs.enqueue('ingest_url')` → `community.acquire_thread` → identity/ingestion | Reuse. Fix Source lookup across the Reddit/community boundary so already-owned threads attach before network work. Distinguish capture-requested from ready evidence in the new UI. |
| Research reuse | `knowledge.pursue(external=False)`, `known_evidence`, `capture_best`, candidate links; K9/M3/S58 | Already implemented locally. Prove catalog rows participate when a new question is created; no second Research subsystem. |
| Yield | `sources_value.compute`, candidate/source relations and project evidence | Aggregate distinct captured member Sources with existing project metrics. Do not rank a subreddit universally or infer evidence from metadata. |
| UI | `web/index.html`, `web/styles.css`, modular `web/js/sources.js`, `state.js`, `research.js` | Source/review behavior is no longer all in index.html. Reuse current Sources review patterns and API helpers. Preserve current uncommitted row-control/sort improvements. |

Two dangerous shortcuts are specifically rejected:

1. `explore.explore()` currently creates proposed Source rows and links them to a collection. Calling it unchanged would violate catalog-only behavior.
2. `db.project_source_ids()` and `projects_for_source()` infer project membership through `project_collections JOIN source_collections`. Linking captured subreddit threads into that ordinary collection relation would let another attached project gain Sources without selecting them.

## 4. Product and architecture contract

### Identity and membership

- A subreddit is a container; a Reddit thread is one global Source; posts/comments remain the existing evidence locators.
- Canonical catalog identity: `collections.kind='subreddit'`, external ID = validated lower-case subreddit name, canonical URL = `https://www.reddit.com/r/<name>/`. Normalize supported host/case/trailing-slash/query variants. Reject lookalike hosts, multi-subreddit paths, user profiles and malformed names as subreddit containers. `/comments/` URLs retain thread classification.
- Keep the existing Reddit candidate key `('reddit', 'reddit:<post-id>')` and existing Source key `('community', 'reddit:<post-id>')`. Add an explicit mapping at the current identity/candidate resolution boundary; do not rename all Source platforms or create a second registry. Cover discovery-before-capture and capture-before-discovery, search and browser capture, repeated requests, and two projects. Reconcile existing unresolved candidate pointers through this same mapping, bounded and idempotent. Unexpected conflicting rows require inspection, not destructive merging.
- Add `collection_candidates(collection_id, candidate_id, first_seen_at, last_seen_at)` in `db.py`, composite primary key, foreign keys and reverse lookup index. This owns catalog membership; origin JSON remains provenance only. Cross-posts with different Reddit post IDs remain distinct candidates.
- Do not populate `source_collections` for subreddit catalogs. Derive captured members via `collection_candidates → candidates.source_id`, intersected with actual project membership. Explicit selected capture uses `identity.attach_existing`/normal ingest and project membership. Existing tag-based membership remains independent; a catalog attachment alone must never add evidence.
- Attaching a second project reconciles all already-known catalog candidates into its own `candidate_projects`, in bounded batches and without a Reddit request. Never copy another project's relevance, dismissals, monitoring policy or capture decisions. Honor `project_sources.excluded` everywhere.

### Metadata and scan state

- Extend candidate metadata additively with a versioned `metadata_json` payload owned by the existing candidate writer. It contains Reddit score (including zero/negative), comment count, flair, UTC creation time, subreddit, outbound URL/domain and access/deletion observations. Keep title/description/author in existing FTS fields; store only a bounded self-text excerpt. No raw page payloads or comment trees in catalog storage.
- Add an explicit observed-metadata update mode to the canonical writer, defaulting to current behavior for existing callers. A changed Reddit observation updates allowed mutable fields and `metadata_revision`; identical observations do not change semantic revisions. Preserve first-seen, user state, relevance decisions and Source identity. Absent optional fields do not erase known values; explicit removal/deletion markers must be distinguishable from absence. Metadata evidence remains a dated observation, not proof of current availability.
- Extend the existing versioned `reservoir:scan:<project_id>:<collection_id>` KV record rather than inventing a second scan service/table. Store run ID/generation, initial/refresh mode, pinned endpoint/sort/access method, cursor, last committed page, observed/unique/new counts, observed oldest/newest timestamps, started/updated/finished times, status, terminal reason, limits and retry timing. Preserve the previous completed summary during an in-progress or failed refresh. Detailed execution history belongs to the existing job ledger.
- Define **Known posts** as distinct local catalog members. Define **Captured** as ready member Sources actually in this project; queued/failed acquisition is separate. **New in latest scan** means distinct catalog members first discovered by that scan, measured against the fixed baseline at scan start. Initial reconciliation of an existing catalog is labeled initial known posts, not new Reddit posts. A separate `new_to_project` count may describe reconciliation. Do not use mutable `candidate_projects.updated_at` as a new-post marker.
- Persist enough run-local ID bookkeeping in the existing job/scan record to keep new counts idempotent on page replay; never persist an unbounded entire catalog in KV. Membership first-seen timestamps plus fixed run boundaries identify additions; serialize page commits for a run and use generation checks so stale workers cannot move a newer cursor. Cross-project scans must converge via unique membership and not reset each other's project summaries.
- Fetch/parse/rank outside write transactions. Commit one bounded page's candidates, memberships, project reconciliation, counts and checkpoint atomically using existing `db.batch/tx` semantics. Crash before commit replays the page; crash after commit resumes from the recorded cursor. Do not hold a write lock across network work.

### Enumeration, refresh and access

- Use the existing `explore` durable job family, dispatched by `kind='subreddit'` to `reservoir` orchestration and the `community` page adapter before generic exploration can propose Sources. Update its retry/dedupe classification narrowly for this branch. One active catalog scan per project/catalog; repeated clicks return its existing job. No new worker pool or scheduler.
- First supported scan is `/r/<name>/new`, following the API's returned `after` cursor. Default page size 100, initial bounded run limit 50 pages/5,000 observations, and short worker turns (one committed page before yielding). These are application safety limits, not promised Reddit capacity. Measure foreground responsiveness before freezing or changing them.
- Manual refresh starts at the listing head. Resume continues an interrupted run's cursor. Do not stop at the first familiar post; page overlap, pinned posts and reordered listings can coexist with unseen posts. Continue to the provider end or the explicit application cap, deduping by ID. No timestamps-as-cursors or search-sharding to manufacture exhaustive history.
- Distinguish: never scanned, queued, scanning, partial/cancelled, rate-limited with retry time, credential/access denied, transient error, stopped at application cap, provider listing ended, and cursor did not advance. Stop repeated cursors/empty nonadvancing pages safely. Page errors never discard earlier pages. Missing posts in a later limited listing are not deletion proof.
- Surface observed date range and termination reason separately. Never imply continuous coverage between the oldest and newest observed dates. Example: “983 posts known; observed post dates Jan–Sep 2026. Reddit's listing ended; older posts may exist.” The brief's 4,812/5,000 figures are UX/load-test examples, not an API promise.
- Bulk enumeration uses approved official API access and honest identity. Missing credentials/access is a clear blocked scan with no fallback crawling. Existing user-browser thread capture remains available for individual threads; building browser subreddit enumeration is outside this mission. No credential changes during planning and no new paid Reddit service or archive dependency.
- External verification, 2026-09-19: [Reddit's API documentation](https://www.reddit.com/dev/api/#listings) describes `after` pagination over changing listings; [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) requires approved API access and respecting access limits. Account approval and working credentials were not verified in Phase A. Before real-data validation, confirm the permitted access and applicable data-handling requirements; fixtures can establish implementation independently. An access blocker cannot be reported as successful live delivery.

### Ranking, capture and Research

- Keep deterministic $0 ranking within `candidates` and `community`; reuse gap-term indexing and existing signal functions. Project fit is primary, firsthand/specificity/substance are secondary; engagement is display context or an explicitly selected sort, never evidence strength. Do not let firsthand language alone make irrelevant content a strong recommendation.
- Compute project fit from the existing brief/Open Question/target/tension machinery, without silently limiting fit to the first eight community missions. Reasons identify the matching question or project terms and metadata-only signals. A 0–100 display value is a review hint, not confidence or truth. Store model-free rank version and input revision when materializing scores; do not overwrite user dispositions while reranking.
- Modes: Recommended, Fits an Open Question, Firsthand, Newest, Most discussed, Highest community score. Search title and stored excerpt, not only currently rendered rows. Include explicit captured/dismissed filters. Default review shows at most 25 recommendations; catalog page default 50, hard maximum 100 with stable ID tie-breaks and revision-aware pagination.
- Reuse the existing cache with keys covering project research/brief revision, catalog membership/metadata revision and dispositions. Never rescore a full catalog on each poll. Verify same-revision reads are cheap and a new question invalidates the correct project view. A stale page revision should trigger an honest refresh, not duplicate/skip rows silently.
- Capture selected candidate IDs through `candidates.capture`, with bounded bulk handling and server-side validation of project/catalog membership. Ready Source lookup must precede remote acquisition. Preserve deduped work and retry behavior for pending/failed Sources. The existing `state='acquired'` can mean queued acquisition; the new UI must use source/job readiness to show Capturing, Failed, and Captured accurately.
- Attaching an owned Source can still schedule project-specific analysis under existing rules. Do not call every attach entirely cost-free. Metadata catalog/ranking/review/refresh/local gap lookup invoke no generation or embedding model; acquisition/downstream analysis retain existing budget and transport controls.
- `knowledge.pursue(..., external=False)` and candidate links must surface old catalog entries for new questions. Merely ranking, viewing, or refreshing must never call `capture_best`, enable CR8b, close an Evidence Target, or promote a Claim. Existing explicitly authorized acquisition policy is unchanged.
- Yield starts with distinct ready captured threads, Findings, high-importance Findings, distinct Claims receiving evidence, and evidence-row counts. Reuse `sources_value` inputs, dedupe joins, exclude removed project membership. “Open Questions improved” and “firsthand evidence supplied” appear only if existing evidence relationships substantiate them; a metadata match or satisfied candidate link alone does not prove improvement. No universal subreddit score.

## 5. Corrective execution ladder — current authority

The previous declaration that SUB2–SUB8 were implemented is withdrawn. Useful code exists, but several required behaviors are missing and the new tests prove only a subset of the acceptance contract. Original SUB numbers below remain historical provenance; **SUB-R0–SUB-R9** own all remaining work in this same mission. Section 4's architecture and product contract remains binding.

All corrective rungs are **OPEN**. SUB-R0 is the next execution unit. This planning revision does not mark any corrective code or live gate complete.

| Rung | Outcome | Depends on | Exit gate |
|---|---|---|---|
| SUB-R0 | Trustworthy baseline and release environment | Current source reconciliation | Isolation defects reproduced and fixed; full baseline failure inventory; runnable local release harness |
| SUB-R1 | Correct identity and project boundaries | R0 | Catalog attachment adds zero evidence; invalid project/catalog actions make zero writes |
| SUB-R2 | Durable scan, cancellation, resume and refresh | R1 | Real job/worker lifecycle passes interruption, retry, dedupe and stale-generation tests |
| SUB-R3 | Accurate metadata, counts and coverage | R2 | Duplicate/replay/concurrent pages preserve exact counts, decisions and bounded summaries |
| SUB-R4 | Useful, fast project ranking and queries | R3 | Two projects rank differently; stable paging/search; unchanged reads do no rescoring |
| SUB-R5 | Selected capture and truthful acquisition state | R4 | Select 10 of 4,000; replay adds no duplicate work; failures and exclusions remain honest |
| SUB-R6 | Local Research reuse and correct yield | R5 | A new question finds an old post offline; only eligible captured evidence contributes |
| SUB-R7 | Complete user workflow | R6 | Browser journey passes search, selection, capture, refresh, recovery and project switching |
| SUB-R8 | Operational and real-access acceptance | R7 | 5,000-post lifecycle/load proof, supported Reddit access, visual acceptance and bounded real capture |
| SUB-R9 | Verified release and delivery | R8 | Full tests, Tier 1, release-check, version agreement and running-app verification all pass |

### SUB-R0 — establish a trustworthy baseline

Owners: existing test fixtures/conftest, configuration isolation, Foundation worker tests and release tooling. Create or refresh an isolated checkout from current `main`, without `.env`, live data or browser credentials. Provide its own usable interpreter/CLI environment; verify imports and worker subprocesses resolve to that checkout. Disable dotenv loading for deterministic checks without editing Kyle's `.env`. Keep test-specific fake settings scoped to their fixtures, including the new S74 module's import-time environment writes.

Reproduce the full-suite failures, including HANDOFF's three reported order-dependent failures (core tool loop, S12 discovery row, S68 proposed-source inspection). Reduce each to its contaminating predecessor/fixture before changing code. A failing test that passes alone is an investigation target, not a waiver. Establish the complete failure set with a full run, not only `-x`. Correct the release invocation: production flags off at entry, with release-check's own fake fixtures used internally; fake Tier 1 remains a separate command.

Exit: isolation regressions pass alone and after their triggering predecessor; the full deterministic baseline and Foundation gates pass, with a source-bound report. Record any genuinely external blocker and continue only independent work; it cannot become a release pass. Also determine Reddit access prerequisites through configuration-presence/status checks without exposing secrets; actual external acceptance belongs to R8.

### SUB-R1 — identity and project boundary repair

Owners: `db.py`, `identity.py`, `candidates.py`, `resources.py`, catalog routes in `api.py`. Verify identity collisions and old unresolved Reddit candidate pointers, with bounded, idempotent reconciliation through the existing mapping. Validate catalog kind and explicit project attachment for catalog read/refresh/yield/selection actions. Retain the generic Candidate Index's deliberate cross-project library-add behavior; enforce catalog selection scope at its own action boundary.

Exit: canonical variants and direct/browser/search capture converge; cross-post IDs stay distinct; second-project catalog attachment reconciles candidates locally and creates zero Sources/chunks/evidence. Foreign IDs, detached catalogs and non-subreddit collections are rejected before writes/jobs; exclusions and dispositions survive. Upgrade fixtures include existing catalogs/candidates/Sources, not only an empty DB. Reconciliation must not scan and rewrite every catalog member on every page.

### SUB-R2 — durable scan lifecycle

Owners: `community.py`, `reservoir.py`, `jobs.py`, existing queue/dedupe and API routes. Define and implement distinct initial scan, resume-from-cursor and refresh-from-head transitions. Repeated clicks share one active run; refreshing cannot silently resume an old blocked scan. Bind queued work to its intended run/generation, and create admission state and job consistently so a crash cannot leave one without the other. Preserve prior committed pages and the last completed summary.

Carry credential/access refusal, 429 retry timing, transient errors, cancellation, provider end, application cap and cursor nonprogress through the existing durable job status/retry mechanisms. A blocked scan must not appear as a successfully completed job. Stop repeated/cyclic cursors and empty nonprogressing listings. Keep one bounded page per worker turn, official API access only, and no network while holding the writer.

Exit: actual `enqueue → claim → execute → yield/retry/cancel → restart/resume` fixtures, including crash before/after commit, delayed/stale workers, double-clicks and 401/403/429/5xx. Assert cursor/rows commit together, bounded attempts/turns, respected retry deadlines, and zero acquisition/model/comment-tree calls. A monkeypatched adapter returning `partial` alone does not close this rung.

### SUB-R3 — metadata, counting and coverage

Owners: the same scan owners and canonical candidate writer. Deduplicate within and across pages; serialize membership/count calculation with commit so simultaneous project scans cannot inflate or lose counts. Separate observations, unique known posts, initial reconciliation and distinct new members of a fixed refresh run. Fix completed-scan reads still looking for obsolete `total`. Preserve a single bounded previous-completed summary rather than nesting prior runs indefinitely.

Validate small metadata observations and URLs, retaining zero/negative engagement. Distinguish omitted fields, explicit cleared flair/text, deleted author and removed post; an absent author alone is not proof a post was deleted. Identical observations must not invalidate semantic rank revisions. Persist observed oldest/newest dates and honest stop reason; never claim exhaustive or continuous history.

Exit: 5,000 rows through 50 actual page commits, with overlap, same-page duplicates, concurrent projects, replay, cap, malformed optional metadata and repeated refreshes. Counts remain exact; run storage stays bounded; user decisions and existing Source identity remain unchanged. Malformed metadata cannot turn into a phantom successfully empty catalog.

### SUB-R4 — ranking, cache and query contract

Owners: `candidates.py`, existing community signals/gap-term index/cache, DB revision helpers and API. The current catalog function rescans/rescores every request; reuse the existing cache with a catalog-scoped semantic revision. Include project framing/questions/targets, membership, observed metadata and dispositions; do not churn on timestamps, unrelated jobs or identical observations. Separate reusable ranking from live acquisition status.

Implement the six Section 4 modes with project fit dominant in recommendations, grounded reasons, secondary firsthand/specificity/substance signals, and engagement confined to explicit sorts/context. Search the full stored title/excerpt set; default recommendations ≤25, browsing 50/max 100; stable tie-breaks, correct state filters and honest revision conflicts. Avoid per-row Source/job queries across the full catalog.

Exit: contrasting project briefs/questions produce different rankings; irrelevant popular/firsthand material does not outrank strong topical matches. Same-revision warm reads invoke zero scoring passes, while changed semantic inputs invalidate the correct project view. Paging/search find rows beyond the first page without duplicates/omissions; stale revisions force restart from a consistent page.

### SUB-R5 — selected capture and acquisition state

Owners: catalog API actions, `candidates.capture`, existing identity/ingestion/jobs. Add bounded explicit-ID bulk selection through the shared capture path, validating every selected ID against project/catalog membership before work begins. Reuse ready Sources before network work; handle pending/failed work with existing dedupe/retry rules. Derive Not captured, Queued/Capturing, Failed, Cancelled and Captured from actual job/Source/project membership, not `candidate_projects.state='acquired'` alone. Removed project evidence must not appear permanently Capturing.

Exit: selecting 10 of 4,000 schedules or attaches only those 10 and leaves 3,990 uncaptured; retries/concurrent selection do not duplicate acquisition. Test mixed ready/pending/failed/cancelled cases, source reuse, second projects, explicit re-add after exclusion, partial bulk failure reporting, and unchanged paid budget/transport controls. The UI must disclose capture/downstream processing consequences before selection is submitted.

### SUB-R6 — local Research proof and yield correctness

Owners: `knowledge.pursue(external=False)`, candidate links, `sources_value.compute` and existing project membership. Prove a newly created question finds an older catalog entry with external discovery disabled; discovery must not itself acquire it or promote Claims/close targets. Use one consistent eligible captured-member set for all yield metrics. The present distinct-Claim query lacks the ready-Source/rejected-Claim predicates used by the other counts; fix that discrepancy. Use actual project membership, including its supported paths and exclusions, without adding `source_collections` catalog membership.

Exit: zero-source catalog yields zero evidence; multiple candidates/evidence joins do not inflate counts; rejected Claims, excluded/non-ready Sources and other projects contribute nothing. The new-question fixture finds the previously remembered post without a provider call and preserves the normal evidence lifecycle after explicit capture.

### SUB-R7 — complete the user workflow

Owners: existing Sources UI modules, API helpers, shared controls/tokens; consult `DESIGN.md` and `AUDIT.md`. Provide an obvious paste-to-catalog review path, full-catalog search, explanations, dismiss/restore, selection count and bounded bulk capture, previous/next controls, distinct captured/failed filters, observed coverage, and clear refresh/resume/cancel actions. Reuse ordinary row controls; avoid an independent component or polling framework.

Fix late responses painting the wrong project/catalog, shared selection state crossing projects, stale revision recovery retaining an invalid page offset, and list refreshes destroying the open review. Preserve focus/selection appropriately, disable in-flight actions, show progress/error recovery and follow existing hidden-tab/poll limits.

Exit: browser journey from pasted URL to scan → review/search → selection → capture/failure/retry → refresh → local reuse/yield. Exercise empty/blocked/partial/complete, rapid project switches and repeat clicks; assert escaped untrusted text and safe links. Automated interaction gates plus real light/dark/narrow/keyboard inspection are required; existing YouTube/course review and community search remain usable. Record the required human visual acceptance separately.

### SUB-R8 — operational and real-access acceptance

Owners: existing fixtures, perf/write-hold instrumentation, supported API and isolated browser. Measure cold and warm review with 5,000 posts and realistic question vocabulary, foreground interactions during scan, query counts, bounded DOM/payload, and write holds. Record baseline/candidate timings and existing threshold compliance; do not invent a passing performance threshold after measuring. Run end-to-end restart, refresh, exclusion and two-project lifecycle cases, with zero model calls during metadata work.

Verify permitted working Reddit API access with a bounded official listing request, then run the same catalog/review/refresh flow on real metadata. Exercise a minimal selected real thread through existing capture and verify readiness/provenance; obtain any required explicit metered-cost decision on the concrete bounded operation first. No scraping fallback or new credential service. Fixtures allow other work to proceed if access is unavailable, but the real-access gate remains BLOCKED with the exact reason. Missing access must not be called a release success.

Exit: recorded lifecycle/performance evidence, real API behavior and coverage limits, correct captured content/provenance, and resolved browser findings/visual acceptance. Do not touch the live SQLite DB directly.

### SUB-R9 — release, delivery and truth reconciliation

Owners: existing release tooling, version markers, HANDOFF/HARDENING/current State and this mission. Choose the new release version using the current repository ritual and update every checked marker, including `web/js/state.js` and the HTML version meta tag. Run full pytest, fake Tier 1, repo-check and the normal release-check on the same isolated candidate with production flags at safe defaults. No skips, frozen-baseline relaxation, or blanket inherited-failure waiver.

Exit: all required gates pass with source/base hashes, environment and artifacts recorded; merge/reconcile only that tested candidate into current `main`, perform the authorized restart/delivery mechanics, and verify served version, schema/startup health and the catalog workflow through supported app surfaces. Record prepared, committed, delivered and live-verified separately. Preserve unrelated files and reconcile intervening commits before landing. Update State/HANDOFF/HARDENING and archive the mission only after complete acceptance. The existing early merge does not waive any gate.

Execution discipline: R0 → R1 → R2 → R3 → R4 → R5 → R6 → R7 → R8 → R9. Tests land with each owning rung; capture and research semantics must pass before adding controls that depend on them. Use the existing two-commit implementation/checkpoint ritual and record actual evidence and the next safe step. Retain Kyle's model/effort setting; no automatic switches, Claude handoff or delegation. A later instruction to execute this ladder should proceed through eligible work without per-rung permission requests.

Ladder-writing validation (2026-09-19): documentation only, limited to this mission and its HANDOFF/scheduler pointers. The source-only `repo_check.check_repo(Path.cwd())` runner returned PASS before and after the edit; `git diff --check` passed. No runtime tests, application edits, provider calls, live DB access or restart were performed for this planning revision. These checks validate document/repository hygiene, not feature readiness.

## Execution log

**Correction, 2026-09-19:** entries below record code and checks from the first pass, not completed acceptance of SUB2–SUB8. The 281-test total includes existing subsystem regressions; the feature module contains 13 tests. Its 5,000-row fixture inserts rows directly and checks paging, so it does not prove 50-page enumeration, performance, restart recovery or real access. The stale-worker test exercises an in-process callback, not concurrent workers. Section 5's corrective exit gates supersede broader completion claims in these historical checkpoints.

### SUB2 — identity and catalog membership — implementation checkpoint, 2026-09-19

Implemented in `2f1a31e` (`subreddit: add durable catalog identity and membership`) in the isolated execution worktree. A pasted supported subreddit URL now canonicalizes to a reusable `subreddit` catalog and creates/attaches only that catalog. `collection_candidates` owns candidate membership; it is explicitly separate from `source_collections`, so catalog attachment never grants project Source membership.

The canonical Candidate Index bridge maps listing identity `reddit:reddit:<post-id>` to captured Community Source identity `community:reddit:<post-id>`, including capture-before-discovery and discovery-before-capture. Existing generic collection behavior remains unchanged: its proposed rows do not resolve early simply because a non-ready Source exists.

Focused regression gate: 82 passed, covering SUB2 plus K2/K3/K4/K9/S55. Research/candidate/isolation/policy/repo gates: 56 passed. Core migration subset: 2 passed. `repo-check` and `git diff --check` passed. The isolated complete-suite prefix reaches the existing order-dependent `tests/test_core.py::test_ask_tool_loop` failure after 70 tests; the same `tests -x` command against untouched `main` at `09be557` fails at exactly that test, while `test_core.py` by itself passes 114/114. It is a baseline suite-order failure outside SUB2, not waived as a pass. No live database, provider call, server restart, or Reddit request occurred.

### SUB3–SUB8 — catalog lifecycle implementation checkpoints, 2026-09-19

`6778890` adds authenticated `/r/<name>/new` metadata pagination through the existing Reddit API owner. Each page is fetched outside the write transaction, committed atomically with its catalog membership and cursor checkpoint, then yields through the existing low-lane `explore` job. The catalog branch cannot use public JSON, HTML, browser, archive, search, Source, embedding, or generation fallbacks.

`5fc590f` adds bounded observed metadata, semantic `metadata_revision`, distinct known-post accounting, initial-versus-refresh labels, page/observation limits, and a generation compare-and-set. A stale page worker rolls back rather than replacing a newer refresh cursor; absent listing fields retain prior observations.

`93444df` adds the project-scoped catalog review and refresh API. It provides deterministic modes, states, bounded pages, revision-aware pagination, and capture status while reusing the existing Candidate Index and acquisition route.

`516f444` adds the Sources catalog card and thread-level capture/refresh controls, plus captured-member yield. Yield counts only distinct ready Sources actually included in the project; metadata membership never counts as evidence.

Validation reported after the first code pass and rebase: the consolidated gate passed **281 tests**; `test_core.py` passed 114/114 separately; JavaScript syntax, fake Tier 1 and repo-check passed. These are historical run results, not proof of all product gates. `pytest tests -x -q` stopped at `test_ask_tool_loop` after 70 passes. Release-check was invoked with the wrong fake-AI entry flag and lacked its expected local CLI path; both are correctable harness issues, not a requirement to use real paid providers. The implementation was subsequently fast-forwarded into shared `main` through `7fdcd2a`. Runtime reload/live behavior was not verified; no explicit restart or real Reddit test was performed. R0 diagnoses the full baseline; R9 must produce a passing deterministic release.

## 6. Validation contract

At SUB-R0, establish the actual isolated baseline and diagnose failures. Do not import historical failure allowances or assume VM failures reproduce on the Mac. Preserve protected baselines; unexplained release failures are not waived. Use fresh private `NEUROSEARCH_DATA_DIR`, `PYTHON_DOTENV_DISABLED=true`, no live `.env`, and the existing deterministic fake/provider isolation fixtures. New test modules must sort after `test_core.py`.

Existing gates to read/run at the relevant intersection:

- Classification/identity/exploration: `tests/test_k3_resources.py`, `test_k2_identity.py`, `test_k4_explore.py`.
- Community content/citations/browser paths: `test_k9_community.py`, `test_k9b_reddit_html.py`, `test_l1_browser_capture.py`, `test_l2_completeness.py`.
- Research/candidate reuse: `test_m3_links.py`, `test_n7_pool.py`, `test_n1_research_view.py`, `test_s55_reservoir_rescan.py`, `test_s57_monitor_policy.py`, `test_s58_selective_acquisition.py`.
- Performance/revisions: `test_s30_pool_sizes.py`, `test_s34_pool_scoring.py`, `test_s35_pool_cache.py`, `test_s65_poll_containment.py`, `test_s66_harvest_isolation.py`, `test_s68_sources_list_diet.py`, `test_s70_write_hold_ledger.py`, `test_s72_research_revision_stability.py`.
- UI/regression: `test_s41_click_feedback.py`, `test_s44_frontend_integrity.py`, `test_s50_design_drift.py`, current course tests, source-listing tests and `test_s73_members_only_never_outrank.py`.
- Operational/release: existing migration fixtures, `test_s43_foundation.py`, `test_s51_test_isolation.py`, `test_repo_check.py`, full current pytest, Tier 1 and release-check. Use current discovered test names; filenames above are repository-relative.

New fixtures must include 5,000 synthetic listing rows across pages, overlapping/repeated pages, missing optional fields, malicious titles/URLs, legitimate zero/negative engagement, removed/deleted markers, access-denied/rate-limit responses, interrupted scans, two attached projects and one excluded Source. Assert zero Sources, chunks, comment-tree reads and model invocations during cataloging. Do not mistake the permitted metadata-scan job for an acquisition job.

Performance: measure cold and warm 5,000-row review queries with realistic question vocabulary, not just a tiny toy fixture. Gate bounded API payload/DOM rows and no full rescore on same-revision polls. Preserve existing foreground rules: no network/CPU loops in write transactions, no ingestion-worker starvation by long scans, existing polling limits unchanged. Record actual timings and write holds against a contemporaneous baseline; do not invent a passing threshold from the mock UX.

At each meaningful release boundary run, from the isolated source snapshot:

```text
NEUROSEARCH_FAKE_AI=0 python -m pytest tests -q
NEUROSEARCH_FAKE_AI=1 neurosearch eval
NEUROSEARCH_FAKE_AI=0 neurosearch repo-check
NEUROSEARCH_FAKE_AI=0 neurosearch release-check
```

This is the corrected validation recipe, not a claim that this documentation turn ran runtime tests. Set the private environment and disabled-dotenv flag before every command; use the isolated interpreter/install so an editable install cannot silently resolve to the live checkout. Release-check validates safe production flags at entry, then enables its own deterministic fake proofs internally; setting fake AI off at entry does not authorize paid calls. Use normal complete release-check unless the current ritual explicitly permits separately recorded full-pytest evidence for the exact same candidate. Verify all actual version markers, including modular `web/js/state.js` and the HTML meta tag. Record command, environment, source/base hash, results and artifacts.

Meaningful UI changes also require DESIGN/AUDIT comparison, task-level browser exercise and the required human visual acceptance. Code tests alone cannot mark those gates complete. A live test must be bounded, on supported access, and separately authorized for any metered capture cost. Never restart or probe the live DB externally to manufacture evidence. Preserve existing two-commit rung mechanics where applicable: implementation then checkpoint evidence; no implementation commits in this planning phase.

## 7. Original model advice and continuing cost boundary

The advice below belongs to the original plan and does not assign models to the corrective ladder. Kyle controls the active setting; preserve it unless he changes it. Model recommendations are not execution or delegation instructions.

Kyle selects the execution model/effort after this planning turn. No model was switched and no subagent was used. Current app capability metadata advertises GPT-6 Astra, GPT-5.6 Sol/Terra/Luna and GPT-5.5 with supported reasoning levels; availability should be checked again when starting. The rung recommendations are engineering judgments, not benchmarked price guarantees.

If Kyle wants one setting for the entire autonomous mission, recommend **GPT-6 Astra / high** because identity, migrations, transaction/restart behavior and project isolation recur throughout. A more economical proposed split is Astra/high for SUB2–4 and SUB6, Sol/high for SUB5 and SUB8, Sol/medium for SUB7, and Astra/high for final hardening. The safe switching seam is a fully gated rung with a durable checkpoint. Do not pause every rung merely to request a model switch; retain Kyle's chosen setting unless he changes it.

No `max`/`ultra` effort is recommended by default. No LOW-only rung is invented for “test cleanup”: migration and lifecycle verification are substantive engineering. Actual Codex allowance/cost was not measured and no exact dollar estimate is claimed. [Official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model) supports Astra for complex multistep/software-engineering work; the specific per-rung allocation here is a recommendation based on the inspected risks.

Neuro application cost is separate: cataloging, baseline ranking, local search, refresh and yield use zero generation/embedding calls. Reddit access eligibility/pricing is unverified. Selected capture may incur embeddings and Findings/Claims costs under existing contracts; expose that before spend and keep paid fallback off unless explicitly authorized. No model-based ranking enhancement is in this mission.

## 8. Autonomous execution, stop conditions and restart point

For corrective execution, follow Section 5 rather than restarting the original SUB2 implementation:

1. Reconcile current Git/working-tree state, CHR2 and course/Sources custody, and this plan's Resume Delta. Record mission admission/suspension in existing coordination docs, without rewriting old history.
2. Build the isolated snapshot and run the baseline. Fix only prerequisite failures whose cause is established and whose scope is within authorization; otherwise record the blocker and continue independent work.
3. Start SUB-R0 by preparing the isolated local environment and reproducing the full test-isolation failure set. Preserve the existing catalog work and correct it incrementally; do not recreate the feature in a second path.
4. Continue the dependency chain, recording rung status, touched paths, actual checks, unresolved issues and next safe action. Preserve a recoverable checkpoint through context/session changes. No separate agent-specific plan or duplicate TODO system.
5. Prepare/test concrete changes before any required live-delivery approval. Follow current HANDOFF restart rules and Kyle's existing authorization; never ask him to run terminal commands. Commit/stage only mission changes and verify the delivered candidate separately from the prepared one.
6. Stop for a true product/architecture choice, unavailable required access, destructive action, collision that cannot be reconciled safely, systemic unexplained release failure, explicit user pause, or completion. Fix ordinary failed tests and continue. Do not use “Claude owns this” as a blocker.

No new product or architecture decision is required to execute the corrective ladder. Kyle's earlier execution authorization remains part of the record; this turn fulfills his narrower request to write the ladder. Account approval/credentials and an explicit decision for any metered real capture may be operational blockers for R8; do not assume access or ask for secrets in chat.

Non-goals: unrestricted crawling, bypasses, new archives, automatic whole-catalog acquisition, a second parser/evidence/research/provider/queue system, universal quality scores, scheduled monitoring, speculative model ranking, fixing all unrelated pending work, or a claim to exhaustive subreddit history.

Current completion state: **CORRECTIVE LADDER WRITTEN — PARTIAL IMPLEMENTATION ON MAIN — SUB-R0 NEXT; FEATURE NOT READY**.
