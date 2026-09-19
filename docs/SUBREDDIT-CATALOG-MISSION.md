# Subreddit catalog, ranking, selected capture, and refresh

Status: ACTIVE — partial implementation landed; SUB-R0 baseline passed, SUB-R1–SUB-R9 acceptance remains open. NOT FEATURE-COMPLETE OR LIVE-RELEASE-VERIFIED.
Revised: 2026-09-19. Planner and executor: Codex. Claude is no longer executing this mission.
Current review baseline: `66f4d4d` on `main`, package version `0.63.94`. Original planning/execution baselines and worktrees are historical; resume from then-current `main` in isolation.

## 1. Hard planning gate and executor

Kyle requested review and revision of the supplied whole-subreddit brief, with execution by Codex instead of Claude/Fable. This document supersedes that brief's provisional ladder and agent/model assignments. Its product intent remains: a reusable subreddit catalog, project-relative recommendations, selected thread acquisition, local Research reuse, manual refresh, and honest coverage.

The original Phase A permitted inspection, safe source-only checks, and planning-document edits; it is complete. The original plan-only restriction ended with Kyle's subsequent execution instruction. The current request, “I need you to update the plan for the work that remains,” is documentation only: reconcile the remaining work against current code without starting runtime implementation in this turn.

Phase B began when Kyle explicitly instructed Codex to execute on 2026-09-19. Changing a model setting alone remains insufficient authorization. The executor must not switch models, invoke another coding model, create tasks, or delegate on the basis of this document. Kyle controls the execution configuration.

After authorization, Codex executes eligible work through this ladder without seeking routine engineering direction. No Claude handoff, Claude session, or waiting for Claude is part of this mission. This does not alter Neuro's internal model/provider contracts or remove its existing local Claude Code adapter.

This is the single canonical mission, under `docs/` because `neurosearch/repo_check.py::ROOT_FILES` does not allow a new root `SUBREDDIT-CATALOG-MISSION.md`. Changing runtime Python merely to admit a planning document would violate Phase A. HANDOFF points here; do not create a second copy.

## 2. Resume Delta and evidence limits — 2026-09-19

Review base is **`66f4d4d` on `main`**, tracked tree clean before these documentation edits. The original implementation and subsequent bounded corrections are already present. Preserve `.chr2_livetest/`, reference directories and untracked release artifacts; do not stage or clean them. CHR2 is closed at `7b43dc8`; other missions remain at their recorded checkpoints. The newest State snapshot (2026-09-17-1130) predates this code and does not establish today's running version.

Read: repository front door, HANDOFF, CLAUDE, QUALITY-CONTRACT, newest State, this mission, relevant implementation and subsystem tests. This review opened no live database or credentials and ran no app server, provider request, capture or runtime test.

Evidence carried forward:

- Frozen original baseline `c10f0b0`: **2,063 passed, two failed** (core tool loop and S12 discovery row). S68 passed the independent frozen runs; the earlier three-failure/order diagnosis was not established on an immutable tree.
- R0 isolation/worker repair produced **2,065 passing tests**. A session fixture restores runtime defaults after collection, and the Foundation worker uses the isolated interpreter. Remaining fixture hygiene is listed in R0; baseline diagnosis need not be repeated as unfinished work.
- Pre-rebase candidate **`064d86c`**: **2,074 passed**, normal isolated release-check **PASS**, Foundation 27 and frozen Tier 1 unchanged. Artifact: `evals/release/release-check-0.63.94-064d86c-20260919-105954.json` (and `.txt`).
- Corrections were rebased onto `078ccf0`, including the independent S55 test repair, and delivered through **`66f4d4d`**. Post-rebase S74/S43/S55 focused gate: **55 passed**. The full-suite/release artifact belongs to the pre-rebase candidate; it is not exact-tree release evidence for current `main`.
- The catalog module now has **22 tests**. Its 5,000-row fixture tests direct insertion and paging, not 50-page worker enumeration or measured performance. No real Reddit access, completed browser acceptance, bounded real capture, restart verification or new release version is established.

On runtime resumption, inspect intervening changes and record a new Resume Delta. Prepare an isolated checkout of then-current `main`, private data directory and usable interpreter/CLI; disable dotenv without editing Kyle's configuration. Do not copy live data, `.env`, cookies or unrelated work. Run the relevant regression baseline, preserve existing fixes and proceed to R1. An absent credential in a sanitized test process does **not** establish the live configuration or account's access status; check those through supported presence/status surfaces at R8b without exposing secrets.

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

**R0's baseline gate passed; R1 is the next implementation rung.** R1–R6 contain useful corrections, but
none has passed its full acceptance gate. R7 has a basic first-pass UI, not the complete workflow. R8 and R9
remain unaccepted. The remaining work includes backend correctness, not only UI and live testing. Section 2
records exactly which source revisions were tested; a deterministic release-check pass does not close these
product gates. This revision updates the plan only.

| Rung | Outcome | Depends on | Exit gate |
|---|---|---|---|
| SUB-R0 | Baseline passed; bounded fixture hygiene follow-up | Current source reconciliation | Retain passing baseline; remove remaining module-level setting leakage before the next full gate |
| SUB-R1 | Correct identity and project boundaries | R0 | Catalog attachment adds zero evidence; invalid project/catalog actions make zero writes |
| SUB-R2 | Durable scan, cancellation, resume and refresh | R1 | Real job/worker lifecycle passes interruption, retry, dedupe and stale-generation tests |
| SUB-R3 | Accurate metadata, counts and coverage | R2 | Duplicate/replay/concurrent pages preserve exact counts, decisions and bounded summaries |
| SUB-R4 | Useful, fast project ranking and queries | R3 | Two projects rank differently; stable paging/search; unchanged reads do no rescoring |
| SUB-R5 | Selected capture and truthful acquisition state | R4 | Select 10 of 4,000; replay adds no duplicate work; failures and exclusions remain honest |
| SUB-R6 | Local Research reuse and correct yield | R5 | A new question finds an old post offline; only eligible captured evidence contributes |
| SUB-R7 | Complete user workflow | R6 | Browser journey passes search, selection, capture, refresh, recovery and project switching |
| SUB-R8 | Offline operational gate (R8a), then live gate (R8b) | R7 | 5,000-post lifecycle/load proof; separately, supported Reddit access, visual acceptance and bounded real capture |
| SUB-R9 | Verified release and delivery | R8 | Full tests, Tier 1, release-check, version agreement and running-app verification all pass |

### SUB-R0 — baseline retained; fixture hygiene checkpoint implemented

Owners: existing conftest/configuration fixtures, Foundation tests and release tooling. **Implemented:** runtime defaults restored after test collection and worker subprocess tied to the isolated interpreter; full baseline and release harness have passed (Section 2). Do not reopen the unsupported three-failure diagnosis.

**Implemented in the R1 preparation slice:** S74 no longer sets fake-AI, app-token or data-directory environment values at import time, and `PYTHON_DOTENV_DISABLED=true` now prevents `config.py` from loading a nearby developer `.env`; an isolated subprocess regression proves that behavior. The session-scoped default reset is still not per-test isolation. Keep any later cleanup bounded to demonstrated leakage; no unrelated suite rewrite. Start every deterministic command with private data and dotenv disabled. Use the installed console entry or an import-complete `cli.app()` runner: the module's early `__main__` invocation precedes later command registrations, so `python -m neurosearch.cli release-check` is not a substitute for the console command.

Gate: relevant isolation and Foundation tests, then the next full deterministic gate on an immutable candidate. Record any new failure with its source and reproduction; retain protected baselines. This cleanup accompanies the next isolated implementation slice; it does not require replaying finished feature work.

### SUB-R1 — identity and project boundary repair

Owners: `db.py`, `identity.py`, `candidates.py`, `community.py`, `resources.py`, catalog routes in `api.py`. **Implemented:** catalog context/candidate guards, scoped capture/dismiss/restore, Reddit-to-Community identity bridge, and repair of null legacy Source pointers.

**Implemented in the first R1 slice:** validate the project before `attach_subreddit_catalog` upserts a global collection; an unknown project now leaves no orphan write. Page membership reconciliation now handles only the committed page, while initial attachment repairs unresolved pointers and reconciles existing catalog rows in 250-item batches. Existing project dispositions remain untouched.

**Remaining:** keep authorization and mutation consistent under detach races. Add old-database/conflicting-pointer and direct/browser/search identity fixtures; inspect conflicting non-null identities rather than merging destructively. Preserve the generic Candidate Index's intentional cross-project add behavior.

Exit: canonical variants and direct/browser/search capture converge; cross-post IDs stay distinct; second-project catalog attachment reconciles candidates locally and creates zero Sources/chunks/evidence. Foreign IDs, detached catalogs and non-subreddit collections are rejected before writes/jobs; exclusions and dispositions survive. Upgrade fixtures include existing catalogs/candidates/Sources, not only an empty DB. Reconciliation must not scan and rewrite every catalog member on every page.

### SUB-R2 — durable scan lifecycle

Owners: `community.py`, `reservoir.py`, `jobs.py`, existing queue/dedupe and API routes. **Implemented:** payload run/generation binding, page/checkpoint compare-and-set, blocked-worker failure and retryable explore jobs.

**Remaining, highest correctness priority:** refresh state is created separately from enqueue. A blocked run's old retrying job can win URL dedupe after a new run is created, leaving the new run stranded. Atomically admit or reuse the run and its intended job through the existing transaction/queue owner; record their association and test failure between the current two operations. Define initial, repeated attach, resume, cancel and refresh transitions explicitly: active clicks reuse the run; resume retains cursor/limits; explicit refresh starts at the head; attaching an already-complete catalog does not silently refresh; cancelled/failed jobs cannot leave an apparently active run forever.

Fence commits by the actual worker claim as well as catalog generation; a reclaimed worker in the same generation must not commit. Handle legacy payloads lacking run fields explicitly. Derive scan state and retry/cancel controls from the associated job, clearing obsolete error details after recovery. Honor limits pinned to the run, not subsequently changed defaults.

Preserve typed credential/access refusal, HTTP status and Retry-After through the existing API adapter and durable retries; generic exception-string matching is insufficient. Narrow retry changes to the subreddit branch or prove unchanged generic explore behavior. Stop multi-step cursor cycles and advancing-but-empty/malformed listings without falsely reporting success. Audit generic project rescan dispatch so a subreddit cannot fall into YouTube enumeration or acquire unintended scheduled monitoring. Keep one bounded page per turn, official access only, and no network while holding the writer.

Exit: actual `enqueue → claim → execute → yield/retry/cancel → restart/resume` fixtures, including crash before/after commit, delayed/stale workers, double-clicks and 401/403/429/5xx. Assert cursor/rows commit together, bounded attempts/turns, respected retry deadlines, and zero acquisition/model/comment-tree calls. A monkeypatched adapter returning `partial` alone does not close this rung.

### SUB-R3 — metadata, counting and coverage

Owners: the same scan owners and canonical candidate writer. **Implemented:** same-page ID dedupe, raw observation counts, completed reads using `known_posts`, basic date bounds, bounded completed-summary fields and missing-author handling.

**Remaining:** the known-ID snapshot/new-count calculation is outside the writer and can race between project scans. Define new-member attribution precisely against the fixed run baseline, and calculate distinct committed additions atomically; prevent two runs claiming the same first discovery. Replayed pages count nothing twice. Initial attachment must display all locally known members without labeling reconciliation as newly found Reddit posts. Keep a bounded run ledger, and normalize legacy nested summaries, including failed-refresh paths.

Validate malformed numbers/strings, outbound/permalink URLs, hostnames and post-ID consistency before commit; bound parsed page size and excerpt length. Explicit empty descriptions/flair currently collapse into omission, while missing availability fields can overwrite a prior observation as available. Preserve presence/clear/unknown distinctions through the writer. Store precise UTC observation bounds in current and previous completed summaries, and invalidate semantic revisions only when relevant values change. Observed dates do not imply continuous or exhaustive coverage.

Exit: 5,000 rows through 50 actual page commits, with overlap, same-page duplicates, concurrent projects, replay, cap, malformed optional metadata and repeated refreshes. Counts remain exact; run storage stays bounded; user decisions and existing Source identity remain unchanged. Malformed metadata cannot turn into a phantom successfully empty catalog.

### SUB-R4 — ranking, cache and query contract

Owners: `candidates.py`, existing community signals/gap-term index/cache, DB revision helpers and API. **Implemented:** per-candidate score caching and joined Source state; the warm regression proves `_potential` reuse. It does not prove cheap queries/sorts or semantic invalidation.

**Remaining:** the key uses broad `project_pool_revision`, including observation/disposition timestamps and unrelated Source changes; full rows still load and sort on each read, and thousands of individual cache entries compete for capacity. Cache catalog-scoped ranked results in the existing cache, keyed by database identity, rank version and all semantic inputs (framing/questions/targets/tensions, membership/metadata, dispositions and creator-yield signals actually used). Keep fresh acquisition status separate. Obtain a consistent revision/data snapshot or retry a changed revision. No new cache service or parallel revision infrastructure.

Finish the six modes: current Firsthand ordering can put irrelevant matches ahead of fit, and Fits an Open Question must require a question match, not merely an area match. Return stored excerpts and grounded reasons. Search all stored titles/excerpts; recommendations default ≤25 (currently 50), browsing 50/max 100; stable ties, valid dates, correct filters and honest revision conflicts. Avoid per-row Source/job queries across the catalog.

Exit: realistic contrasting briefs/questions produce different rankings; irrelevant popular/firsthand material does not outrank strong topical matches. Warm reads do no rescoring/full resort; identical observations and unrelated jobs do not invalidate ranking, while a new question invalidates the right project. Measure query counts and work, not only scorer calls. Search/paging find later rows without duplicates/omissions; stale revisions restart consistently.

### SUB-R5 — selected capture and acquisition state

Owners: catalog API actions, `candidates.capture`, existing identity/ingestion/jobs. **Implemented:** scoped single-candidate capture through the shared path. **Remaining:** explicit-ID bulk action, 1–100 unique IDs, validating the whole selection before writes and reporting per-item execution failures. Reuse ready Sources first; explicit re-add must clear an existing project exclusion through the supported membership owner. A globally deduped pending ingest job must still attach the Source to each selecting project; test the second project's completion, not just shared job IDs.

Derive Not captured, Queued/Capturing, Waiting for browser, Failed, Cancelled, Removed and Captured from actual job/Source/project membership. Current `acquired` rows can show Capturing forever after failure or exclusion. Preserve existing retry/dedupe and budget controls; no alternate ingest path.

Exit: selecting 10 of 4,000 schedules or attaches only those 10 and leaves 3,990 uncaptured; retries/concurrent selection do not duplicate acquisition. Test mixed ready/pending/failed/cancelled cases, source reuse, second projects, explicit re-add after exclusion, partial bulk failure reporting, and unchanged paid budget/transport controls. The UI must disclose capture/downstream processing consequences before selection is submitted.

### SUB-R6 — local Research proof and yield correctness

Owners: `knowledge.pursue(external=False)`, candidate links, `sources_value.compute` and existing project membership. **Implemented:** distinct-Claim counts now require ready Sources and non-rejected Claims. **Remaining:** catalog yield still relies on direct project membership rather than all supported membership paths. Derive one eligible captured-member set through the existing membership semantics, including tags/collections and exclusions, for every metric; never add subreddit `source_collections` membership.

Exercise actual local pursuit for a newly created question against an older catalog entry, with external/provider calls poisoned. Ranking/discovery must not capture, promote Claims or close targets. Verify candidate-link/source readiness through explicit capture using the existing lifecycle, and label only evidence relationships the metrics actually substantiate.

Exit: zero-source catalog yields zero evidence; multiple candidates/evidence joins do not inflate counts; rejected Claims, excluded/non-ready Sources and other projects contribute nothing. The new-question fixture finds the previously remembered post without a provider call and preserves the normal evidence lifecycle after explicit capture.

### SUB-R7 — complete the user workflow

Owners: existing Sources UI modules, API helpers, shared controls/tokens; consult `DESIGN.md` and `AUDIT.md`. **Implemented:** basic catalog card, per-row capture, refresh, mode/state selector and forward paging. **Remaining:** full-catalog search, excerpts/reasons, dismiss/restore, explicit selection count and bounded bulk capture, previous/next controls, truthful capture filters, observed coverage and distinct refresh/resume/cancel actions. Use normal row controls and action helpers; no independent component or polling framework.

Fix late responses painting the wrong project/catalog, shared selection state crossing projects, stale revision recovery retaining an invalid page offset, and list refreshes destroying the open review. Preserve focus/selection appropriately, disable in-flight actions, show progress/error recovery and follow existing hidden-tab/poll limits.

Exit: browser journey from pasted URL to scan → review/search → selection → capture/failure/retry → refresh → local reuse/yield. Exercise empty/blocked/partial/complete, rapid project switches and repeat clicks; assert escaped untrusted text and safe links. Automated interaction gates plus real light/dark/narrow/keyboard inspection are required; existing YouTube/course review and community search remain usable. Record the required human visual acceptance separately.

### SUB-R8 — separate offline operational acceptance from live acceptance

**R8a, offline gate:** use existing fixtures and perf/write-hold instrumentation. Enumerate 5,000 posts through 50 actual worker page commits, not direct candidate insertion. Measure cold/warm review with realistic question vocabulary, foreground interactions during scan, query counts, bounded DOM/payload and write holds against existing thresholds. Run interruption/reclaim/restart, refresh, exclusion and two-project lifecycles, poisoning model/acquisition calls during metadata work. Record baseline/candidate timings; do not invent a passing threshold after measuring.

**R8b, live gate:** check access/configuration through supported status surfaces, then verify approved working Reddit API access with a bounded official listing request. Run the same catalog/review/refresh flow on real metadata and minimal selected real capture; verify readiness/provenance. Honor existing cost authorization and obtain any still-required metered-cost decision only on a concrete prepared operation. No secrets in chat, live `.env` edits, scraping fallback or new credential service. If access is unavailable, finish eligible offline work and mark R8b BLOCKED with the exact reason; the feature is not release-ready. Record real browser and required human visual acceptance separately.

Exit: recorded lifecycle/performance evidence, real API behavior and coverage limits, correct captured content/provenance, and resolved browser findings/visual acceptance. Do not touch the live SQLite DB directly.

### SUB-R9 — release, delivery and truth reconciliation

Owners: existing release tooling, version markers, HANDOFF/HARDENING/current State and this mission. Choose the release version under the current ritual and update every checked marker, including `web/js/state.js` and the HTML version meta tag. Freeze the final integrated candidate and run full pytest, fake Tier 1, repo-check and normal release-check on that exact tree with safe entry flags. Record start/end source hashes; reports stamped only with a finishing SHA cannot prove unchanged source during execution. Reconcile intervening changes before this gate, or rerun affected gates after them. No skips, protected-baseline relaxation or inherited-failure waiver.

Exit: all required gates pass with source/base hashes, environment and artifacts recorded; merge/reconcile only that tested candidate into current `main`, perform the authorized restart/delivery mechanics, and verify served version, schema/startup health and the catalog workflow through supported app surfaces. Record prepared, committed, delivered and live-verified separately. Preserve unrelated files and reconcile intervening commits before landing. Update State/HANDOFF/HARDENING and archive the mission only after complete acceptance. The existing early merge does not waive any gate.

Execution discipline: retain R0, close its bounded fixture follow-up with the next slice, then R1 → R2 → R3 → R4 → R5 → R6 → R7 → R8a → R8b → R9. Tests land with their owning rung; capture/research semantics pass before dependent controls. Do not jump to UI because a partial regression checkpoint is green. Prepare gated changes in isolation; do not repeat the early shared-main landing as a substitute for acceptance. Use the existing two-commit implementation/checkpoint ritual, recording evidence and next action. Preserve Kyle's model/effort; no automatic switches, Claude handoff, delegation or routine per-rung permission requests.

Planning validation (2026-09-19): documentation only, limited to this mission and its HANDOFF/scheduler pointers. `.venv/bin/python` calling source-only `repo_check.check_repo()` returned PASS; `git diff --check` and rung/test-path/pointer consistency checks passed. No runtime tests or app/provider operations were performed for this revision. These checks validate hygiene, not feature readiness; runtime validation remains source-bound to the checkpoints in Section 2.

## Execution log

### Corrective checkpoint through `66f4d4d` — 2026-09-19

Retain `63f93a5` (runtime default/worker isolation), `5268aef` (catalog project boundaries), `7231017` (run-bound workers), `a27f47b` (listing observations), `4fa8ae2` (eligible evidence predicates), and `6597062` (score caching). These are bounded corrections, not closure of R1–R6. `66f4d4d` records their validation checkpoint. Section 2 distinguishes the 2,074-test/pre-rebase release pass from the 55-test/post-rebase focused pass. The feature module now has 22 tests. This remaining-work review corrected stale R0-next pointers and converted each rung into retained behavior, concrete residual work and an exit gate; no runtime implementation occurred during the review.

### R0/R1 preparation checkpoint — pending commit, 2026-09-19

The isolated R1 branch adds the deterministic dotenv opt-out and removes S74's import-time environment mutations. It validates the project before catalog upsert, limits page reconciliation to supplied candidate IDs, and reconciles an already-attached catalog in 250-item batches. Focused gate: `PYTHON_DOTENV_DISABLED=true NEUROSEARCH_FAKE_AI=0 … python -m pytest tests/test_s74_subreddit_catalog_identity.py tests/test_s51_test_isolation.py tests/test_s43_foundation.py tests/test_s55_reservoir_rescan.py -q` — **64 passed**. This is an R0/R1 checkpoint, not R1 closure or an integrated release result. Next: atomic catalog-run/job admission and refresh lifecycle in R2.

### Original pass — historical evidence and limits

**Correction, 2026-09-19:** entries below record code and checks from the first pass, not completed acceptance of SUB2–SUB8. The 281-test total includes existing subsystem regressions; the feature module then contained 13 tests. Its 5,000-row fixture inserts rows directly and checks paging, so it does not prove 50-page enumeration, performance, restart recovery or real access. The stale-worker test exercises an in-process callback, not concurrent workers. Section 5's corrective exit gates supersede broader completion claims in these historical checkpoints.

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

Retain the established R0 baseline and run a fresh isolated regression baseline on resumption to detect intervening changes. Do not repeat solved diagnosis or import historical failure allowances. Preserve protected baselines; unexplained release failures are not waived. Use fresh private `NEUROSEARCH_DATA_DIR`, `PYTHON_DOTENV_DISABLED=true`, no live `.env`, and existing deterministic fake/provider isolation fixtures. New test modules must sort after `test_core.py`.

Existing gates to read/run at the relevant intersection:

- Catalog: `tests/test_s74_subreddit_catalog_identity.py`; extend its 22 current tests with actual job admission/retry/reclaim, concurrent page attribution, legacy upgrade, semantic cache invalidation, bulk outcomes and offline Research lifecycle fixtures. Add UI interaction coverage through the existing frontend test conventions.
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

## 7. Execution configuration and cost boundary

Kyle controls the execution model and effort. Preserve his setting until he changes it; this plan neither switches models nor launches execution or agents. No model change or subagent was used for this review. The old per-rung model recommendations are retired with the original ladder; no model-selection decision is required to make this remaining-work plan concrete.

Neuro application cost is separate: cataloging, baseline ranking, local search, refresh and yield use zero generation/embedding calls. Reddit access eligibility/pricing is unverified. Selected capture may incur embeddings and Findings/Claims costs under existing contracts; expose that before spend and keep paid fallback off unless explicitly authorized. No model-based ranking enhancement is in this mission.

## 8. Autonomous execution, stop conditions and restart point

For corrective execution, follow Section 5 rather than restarting the original SUB2 implementation:

1. Reconcile current Git/working-tree state against `66f4d4d` and record the Resume Delta. Preserve unrelated work and completed CHR2; do not reopen other missions.
2. Prepare an isolated snapshot and private environment, verify interpreter/CLI provenance, and run the relevant baseline. Finish the bounded R0 fixture follow-up; diagnose only newly demonstrated failures.
3. **Start SUB-R1:** invalid-project attachment must make zero writes; page reconciliation must be bounded to changed candidates. Close legacy identity and project-boundary fixtures, then address R2's atomic run/job admission and retry-dedupe defect. Preserve existing implementations; no second feature path.
4. Continue the dependency chain, recording rung status, touched paths, actual checks, unresolved issues and next safe action. Preserve a recoverable checkpoint through context/session changes. No separate agent-specific plan or duplicate TODO system.
5. Prepare/test concrete changes before any required live-delivery approval. Follow current HANDOFF restart rules and Kyle's existing authorization; never ask him to run terminal commands. Commit/stage only mission changes and verify the delivered candidate separately from the prepared one.
6. Stop dependent work for a true product/architecture choice, unavailable required access, destructive action, collision that cannot be reconciled safely, systemic unexplained release failure, explicit user pause, or completion. Continue eligible independent work when an operational gate is blocked. Fix ordinary failed tests and continue. Do not use “Claude owns this” as a blocker.

No new product or architecture decision is required to execute the corrective ladder. Kyle's earlier execution authorization remains part of the record; this turn fulfills his narrower request to update the remaining-work plan. Account approval/credentials and any still-required metered-capture decision may block R8b; do not assume access or ask for secrets in chat. Routine engineering choices and per-rung progress do not require new approval.

Non-goals: unrestricted crawling, bypasses, new archives, automatic whole-catalog acquisition, a second parser/evidence/research/provider/queue system, universal quality scores, scheduled monitoring, speculative model ranking, fixing all unrelated pending work, or a claim to exhaustive subreddit history.

Current completion state: **REMAINING-WORK PLAN UPDATED — R0 BASELINE PASSED — R1 NEXT, R1–R9 ACCEPTANCE OPEN; FEATURE NOT READY**.
