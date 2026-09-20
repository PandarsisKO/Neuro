# Continuous execution — finish acceptance, then Chat Refresh

Status: ACTIVE — the CHR3 evidence-boundary repair is delivered after a follow-up audit; continue with supported
live acceptance gates and Kyle decisions.
Updated: 2026-09-19. Owner: executing agent, currently Codex.
Planning base: shared `main` at `aea21ef369603308ef48d5b4eee85d608786ea6e`.

## 1. Mission and authority

Finish the outstanding screenshot, extension-authentication and course workflows; implement the optional
whole-chat refresh through the existing chat path; prepare the already-built research features for real
acceptance; finish subreddit delivery when approved official API access is available. Each completed feature
must have evidence for what a user actually does, a passing release gate for its exact source, and an honest
delivery state. A blocked dependency must not stop unrelated eligible work.

Kyle requested this mission and ladder on 2026-09-19 for continuous execution of the recommended plan. This
establishes the sequence, including CHR3 as the next feature after extension acceptance work, and supersedes
the earlier blanket stop-after-CHR2 instruction for that planned continuation. This planning turn does not
execute runtime changes, authorize a new dollar budget, or claim any live gate passed. Prior authorization
for autonomous in-scope engineering persists; routine rung transitions require no new permission.

This document owns cross-feature sequencing and execution status only. It does not duplicate feature designs:

- [Chat Refresh](CHAT-REFRESH-PLAN.md) owns CHR3 semantics and evidence boundaries.
- [Send Screenshot](SEND-SCREENSHOT-2026-09-16.md), [Course Scanner](COURSE-SCANNER-2026-09-15.md), and
  [live acceptance cases](KYLE-GATES-2026-09-15.md) own the extension behavior contracts.
- [Subreddit Catalog](SUBREDDIT-CATALOG-MISSION.md) owns SUB-R8b/R9; use the integrated checkout's newer
  evidence until it is reconciled into main.
- [Product Intelligence ladder](../EXECUTION-LADDER.md) owns the CR/LP/AD/FM/L acceptance criteria.
- [HANDOFF](../HANDOFF.md), [CLAUDE](../CLAUDE.md), [Quality Contract](../QUALITY-CONTRACT.md), and
  [Development Operating System](../DEVELOPMENT-OPERATING-SYSTEM.md) retain their standing responsibilities.

The new document is necessary because the work spans several existing feature contracts. Keep its ladder here,
not in a second task file or agent-specific queue. Scheduler, state and handoff point here. Archive it at full
closeout and update those pointers; preserve the feature-specific evidence in its existing home.

## 2. Starting truth — preserve completed work

| Area | Verified position at planning time | Remaining |
|---|---|---|
| Screenshot | Case 7's partial and bounded full-page provenance/image paths are live-accepted; case 6 cosmetic issue remains deliberately deferred | Broader historical matrix cases only; no unmeasured repair is admitted |
| Extension auth | Popup/background/form/pending-poll 401/403 handling exists; eight executable runtime checks pass against controlled responses | Real extension failure/recovery acceptance; repair only demonstrated defects |
| Course Scanner | Algorithm accepted; live popup scan completed all 3 lessons and its record survived popup closure | Exact active-state reopen snapshot and CS7 document ingestion live acceptance remain unproven |
| Chat | CHR0/CHR1 shipped; CHR2 closed; the delivered follow-up repair adds conservative citation resolution, capped-evidence disclosure and duplicate-admission boundaries | Supported live verification and paid real-evidence synthesis acceptance |
| Subreddit | Prepared delivery candidate `7191fdf` on `codex/subreddit-delivery`; offline implementation and release proof are complete | Approved access, bounded real listing/capture and visual acceptance, SUB-R9 delivery |
| Existing research features | CR1–CR6/CR8a/CR8b, LP0–LP5, AD0–AD4A and FM1 built | Real-use observations and the decisions listed in CE9; no wholesale rebuild |

Last supported Reddit configuration observation: `stats.reddit_api=false`. A true value proves configuration
presence only, not approved access or working listing/capture. The existing monitor
`resume-reddit-catalog-live-gate` watches this dependency; do not create a duplicate.

The catalog candidate is at `/private/tmp/neuro-subreddit-delivery`. It remains intentionally separate from main
until approved Reddit API access permits R8b. Do not repeat the stale R1-next checklist or land it to bypass that
live gate.

## 3. Execution loop and isolation

1. Inspect Git state and current pointers. Record the source/base, isolated checkout, touched surfaces and
   relevant intervening changes. Read the owning feature contract and its tests before implementation.
2. Take the earliest eligible rung in Section 4. Work one runtime change at a time. Investigate a failed gate,
   repair its demonstrated cause, validate, commit the coherent implementation, then record evidence in a
   checkpoint commit. Planning-only changes need no artificial implementation commit.
3. At a meaningful boundary, reconcile code, tests, visual evidence and runtime status. Update this ladder's
   state and the owning feature's evidence, then continue without a routine approval pause.
4. If a rung needs missing access, a physical action, a dollar authorization not already granted, or a genuine
   product judgment, finish its independent preparation, record the exact dependency, and continue to the next
   eligible rung. An open acceptance gate stays open. Do not label it complete to make the queue advance.
5. On resumption, read the latest checkpoint and compare actual diffs. Do not re-run completed gates without
   a change or unresolved risk that invalidates them. No model/effort switches or new task delegation by default.

Runtime work starts in an isolated checkout of then-current main with private data, disabled dotenv and no
copied secrets/cookies/media. Keep the blocked catalog candidate intact. Where main's known test-isolation
defects prevent a clean baseline, reuse the minimal reviewed corrections already proven on the integrated
branch, with their regression gates; do not import the whole catalog merely to obtain a green harness. Record
the selected changes and provenance. If a separable correction cannot be established, resolve the dependency
explicitly instead of disguising it as a pre-existing failure allowance.

When catalog work resumes, reconcile only the accepted changes from the other track into its candidate and
revalidate the changed source. Do not overwrite either branch's handoff or evidence with an older version.

Never open or copy the live SQLite database. Observe it through supported authenticated app surfaces; use a
verified backup copied into private storage when raw inspection is necessary. Do not run a CLI that opens the
live database merely because an older gate document tells Kyle to do so. The agent performs supported operations;
Kyle is not assigned terminal commands. Missing UI/API support is a recorded limitation, not permission to
invent another runtime command channel or storage path.

## 4. Execution ladder

States: READY, ACTIVE, BLOCKED, PREPARED, ACCEPTED, DELIVERED, COMPLETE. PREPARED means engineering evidence
exists; it never implies real acceptance or delivery. Mark COMPLETE only when that rung's exit gate is met.
Priority is table order among eligible work. CE10 may resume at the next safe boundary once its dependency clears.

| Rung | Initial state | Dependencies | Exit gate |
|---|---|---|---|
| CE0 — establish the execution baseline | ACCEPTED (focused) | None | Isolated source/harness identified, existing repairs reconciled, relevant baseline passing |
| CE1 — finish screenshot acceptance | ACCEPTED (2026-09-19) | Actual Chrome and a real capture | Provenance/partial/image checks pass; evidence tied to source and extension versions |
| CE2 — accept authentication failure and recovery | READY after CE0 | Actual extension; controlled failure target | Visible 401/403 feedback and successful recovery, with successful capture behavior preserved |
| CE3 — finish course acceptance | READY after CE0 | Signed-in course; separate cost/access boundary for document import | Active-scan reopen and completion verified; one successful bounded CS7 document import, with blocked-host behavior distinguished |
| CE4 — release accepted extension repairs | READY after relevant CE1–CE3 work | Concrete candidate; required visual acceptance | Full release ritual, version agreement, delivery and supported live verification |
| CE5 — CHR3 evidence-context preparation | ACCEPTED (release-checked candidate) | CHR0–CHR2 retained; owning design read | Scoped evidence builder, comparison passages, honest limits and meaningful deterministic tests |
| CE6 — CHR3 synthesis and persistence | ACCEPTED (release-checked candidate) | Existing chat/provider/storage paths | Correct refreshed turn, refusal/failure/retry behavior and fresh successful snapshot |
| CE7 — CHR3 interaction and visual acceptance | PREPARED (isolated) | Working isolated candidate | Real browser task exercise, clear spend consequence, correct state and required human visual review |
| CE8 — CHR3 release | PREPARED (deterministic gate passed) | Exact frozen candidate | Full release ritual, delivered source/version and supported live verification |
| CE9 — existing-feature acceptance package | READY after CE0; lower priority than eligible CE1–CE8 | Supported reads and existing real evidence | Fresh evidence gathered, eligible live gates run, remaining judgments made concrete |
| CE10 — subreddit live acceptance and delivery | BLOCKED | Approved official access/configuration; capture cost boundary | SUB-R8b then SUB-R9 pass on reconciled candidate |
| CE11 — mission closeout | BLOCKED | All in-scope gates resolved | Truthful delivered inventory, no unrecorded blockers; mission archived |

“Extension work attempted” means CE1–CE4 have either passed or reached a documented external dependency after
safe alternatives are exhausted. It does not mean skipping a repair that can be completed autonomously. Partial
release is allowed for an independently accepted slice; the unreleased or unaccepted slice remains open.

### CE0 — baseline and resume delta

Read the latest main and integrated branch status; preserve all unrelated tracked/untracked work. Baseline the
extension and chat intersections and any selected harness corrections in isolation. Establish a clean full suite
at the first runtime release boundary; never inherit main's historical failure allowance. Record which old
evidence still applies, which has been invalidated, and why. No live restart is part of baseline preparation.

### CE1 — screenshot provenance and image integrity

Inspect an actual captured source through the app drawer and supported capture metadata. Verify the page title,
capture timestamp (including displayed timezone), full-page/visible-only wording, source URL, separate user note,
and partial tag/reason when applicable. Use real complete and partial records; create a bounded new capture only
when existing records cannot prove the case and its provider-cost consequences are covered. Check the actual
image, including the later axis-ceiling/corruption fix recorded in HANDOFF parts 21–22, not only metadata.
Record identifiers, expected versus observed values and browser evidence without secrets. Repair only a measured
gap through the existing capture/provenance/drawer owners. Case 6's explicitly deferred cosmetic issue stays deferred.

**Checkpoint (2026-09-19):** supported live app inspection confirmed the partial fixture source
`f5eb0c54f23d41288cd18ff50b730ecd` shows its real title, capture time, `part of the page` wording, `partial` tag,
source URL and separately-labelled note; supported digest data confirms `mode=partial_page` and
`partial_reason=ceiling_axis`. Two normal captures showed `the visible area` and digest-confirmed
`mode=visible_only`. No existing safe full-page capture was available, so that mode and the actual image's
full integrity remain open rather than manufacturing a production capture without a covered cost boundary.

**Follow-up (2026-09-19, delivered and live-verified):** a direct Source Drawer view completed for the partial
fixture and confirmed the title, partial wording/tag and URL. Its unsuffixed local timestamp exposed an ambiguity
against this gate's timezone requirement. `6738674` adds the browser's short timezone label (for example, PDT),
has a regression gate and a full deterministic release PASS at
`evals/release/release-check-0.63.94-6738674-20260919-193846.json` (**2,100 passed, 1 warning**), and was
delivered at `9ad45a2`. After browser reload, the card visibly rendered `Sep 19, 2026, 6:59:22 PM PDT` alongside
the correct title, partial mode/tag and URL.

**Bounded complete-capture acceptance (2026-09-19):** the installed `1.9.3` extension captured the local synthetic
two-tile fixture added at `ee27ec0`, visibly reporting `Captured the full page — sent to Neuro Search`. Its ready
source `6dc4abaccd7147e19d6a8e9aa515b5db` opened through the supported drawer with the true title, `Sep 19, 2026,
7:51:17 PM PDT`, `the full page` wording, fixture URL, and the independently labelled synthetic note. The stored
image visibly included the bottom `END OF COMPLETE FIXTURE` marker and matched the direct browser full-page rendering
at `3840×2864`; it was not merely assumed complete from metadata. The S54 gate is **73 passed, 1 warning**. Together
with the partial and visible-only checks above, this closes CE1/Case 7; Case 6's explicitly deferred cosmetic issue
is unchanged.

### CE2 — extension 401/403 failure and recovery

Inspect and reuse the existing handlers. Exercise popup project loading, background/form upload and pending-poll
error surfacing with actual extension code against a controlled local endpoint or disposable extension profile.
The result must identify the connection problem and recovery action, preserve captured/retryable work, and not
claim a successful send. Restore valid connectivity and prove the error clears and normal behavior resumes.
Do not invalidate the user's working token or edit live credentials to manufacture a failure. Mocked JavaScript
checks are regression evidence; they are not a substitute for the Chrome interaction. Record test-profile versus
production evidence separately.

**Checkpoint (2026-09-19):** the shipped `popup.js` and `background.js` now run under the narrow
`tests/js/run-extension-auth.mjs` Chrome/HTTP harness, rather than only source-text assertions. It exercised
both popup 401/403 responses, background API 401, form-upload 403, and background polling's 401 persistence
versus quiet 500 behavior; `tests/test_s74_extension_auth.py` is **8 passed**. This closes the deterministic
regression gap only. No extension was installed or pointed at a controlled failure endpoint, and no user
credential was touched, so CE2's live failure-and-recovery acceptance remains open.

### CE3 — course completion, persistence and document outcome

Use the existing signed-in course, real popup and background worker. Start a scan, close and reopen while it is
still active, then let it finish; reconcile expected lessons, explicit failures and final counts. Preserve the
already-observed cancellation result unless touched code invalidates it. Do not confuse reopening a stopped scan
with reopening an active one or re-open the accepted algorithm without a demonstrated failure.

CS7 also records an untested real document fetch. Use at most one representative selected attachment through
the existing import path when access and processing cost are covered; inspect the resulting source/searchability
and duplicate handling. If the host requires sign-in, an honest blocked outcome validates that failure path but
does not prove successful document ingestion. Leave that success gate open until an accessible representative
is tested. Never transmit course/Google session cookies or import an entire course to prove this small gate.
If there is no safe bounded supported import, record the limitation and continue CE5.

**Checkpoint (2026-09-19):** on the signed-in Acquisition Ace course, the installed extension's real popup
started a new scan, visibly reported `3 lessons found` / `Reading the first lesson` / `0 videos found so far`,
then traversed the three lessons. The popup was closed from that confirmed active state; the course continued
to its normal completion and reopening the popup showed `3 of 3 lessons ready`, all three named lessons, and
the shared-video “downloaded once” disclosure. Neither course progress nor any Review & import action was
triggered. The three-lesson traversal completed before the reopen snapshot, so the distinct exact *active on
reopen* observation remains open; it is not silently counted as passed. CS7 remains open because no document
or browser session was sent to the app.

### CE4 — extension release boundary

Release only the accepted slice. Check actual package/UI/extension versions and bump the relevant component
when code changed; do not overwrite a newer version using the old planned 1.9.4 bump. Run the complete ritual
in Section 6, then deliver at a safe boundary consistent with existing authorization and active-job state.
Verify which extension build Chrome actually loaded and the running app's version/health. Record screenshot,
auth, scanner and document gates separately; a passing release-check cannot close missing browser evidence.

### CE5 — CHR3 evidence context

Follow Chat Refresh §§8–10, 12 and 14 plus its later correction records. The implemented CHR1 data shape wins
over obsolete prose. Extend the existing conversation-delta and chat seams; do not create a second research
refresh engine. Before building, trace the existing delta units, per-question baselines, citation resolution,
chat admission/tool loop and persistence so integration choices are concrete.

Resolve relevant new/revised excerpts, Finding citations, changed Claim evidence and both sides of tensions,
including changes on old sources. Include only the previously cited passages needed for comparison. Revalidate
current project membership, exclusion and ready-state before context assembly; deduplicate and rank under the
existing chat excerpt budget, preserving category priority and explicit truncation/unknown information. Use
the actual whole-chat delta rather than treating the model's 12-message history tail as whole-chat coverage.
Approximate/mixed chats keep their uncertainty labels. Unresolvable evidence is omitted honestly, never invented.

Gate: meaningful fixture coverage for old-source changes, >12-message conversations, exclusions/cross-project
isolation, missing evidence and bounded ordering; empty/context preparation makes no model or embedding call.

**Checkpoint (2026-09-19):** `conversation_delta.refresh_evidence()` is implemented in the isolated candidate.
It accepts only concrete delta units, resolves findings/Claim evidence plus earlier citations to real chunks, rejects
sources outside the current project and does no retrieval/provider work. Focused CHR0/CHR1 tests are green.

### CE6 — CHR3 existing chat execution path

Connect explicit refresh to the existing `answer.chat` contract, provider/cost controls, response/streaming,
citations and message persistence. Refuse an empty relevant delta with 409 before paid work or a successful
baseline is written. Save the synthetic user turn with `meta.kind='refresh'`; exclude it from future topic
extraction. Use the established prompt instructions and comparison evidence, retaining the cached system prefix;
web search stays off unless explicitly selected. Tool access must preserve the delta-selected evidence boundary
and existing save-finding behavior rather than silently retrieving arbitrary old corpus material.

On successful completion persist the normal exact evidence snapshot and refresh provenance. Failure, interruption
or truncation cannot advance the baseline. Repeated clicks/concurrent requests cannot launch accidental duplicate
paid turns; reuse established request/job semantics and specify retry behavior with tests. Membership changes
during preparation cannot leak evidence. Save/Pin still uses project notes and the normal harvest path; refresh
prose never directly promotes a Claim, mutates a plan, or becomes source evidence.

Gate: deterministic integration checks through the real chat seam cover success, empty-delta refusal, concurrent
admission, failure/retry, exact/approximate provenance, citation scope and unchanged ordinary chat behavior.

**Checkpoint (2026-09-19):** the isolated candidate has `POST /api/conversations/{id}/refresh`, explicit user/assistant
refresh provenance, a 409 no-evidence refusal, normal fresh evidence snapshots and no corpus-search tools. Focused
tests cover success, refusal, refresh-topic exclusion, cross-project exclusion and no direct Claim creation.

**CE7/CE8 checkpoint (2026-09-19):** an isolated fake-AI browser exercised the meaningful-delta control through
persisted chip and cited answer; the 500px layout had no horizontal overflow in light/dark states. The later
`e99ccac` repair makes selected evidence material-first under the hard excerpt cap, records overflow, and persists
an incomplete assistant failure after a post-admission provider error. Its exact candidate-bound release check
passed with **2,095 passed, 1 warning** and wrote
`evals/release/release-check-0.63.94-e99ccac-20260919-185514.json`. This does not
authorize or claim the remaining real paid synthesis, human production visual judgment, delivery or live verification.

**Follow-up deterministic repair (2026-09-19, prepared):** a private reproduction found that historic citations
could select the next chunk by nearest start, while locator-only evidence silently selected chunk zero. The isolated
candidate resolves only containing numeric/exact timestamp chunks and omits page-like/unresolvable locators. It also
keeps an unchanged capped selection from becoming a new paid refresh merely because additional omitted passages
arrive, limits affected-question prompt wording to selected evidence, and tells both provider and user when the cap
omitted lower-priority passages. Commit `91bd9e1` passed the ordinary deterministic release ritual — **2,099
passed, 1 warning**, Foundation, Tier 1, migrations, recovery and backup/restore — at
`evals/release/release-check-0.63.94-91bd9e1-20260919-192933.json`. It was delivered to shared `main` and GitHub
at `ab4bde8`; it is still not real-paid/live accepted, so retain those separate states.

### CE7 — CHR3 UI and browser acceptance

Add the working refresh action inside the open chat's existing What's New region. Clearly state its paid-call
consequence using the app's cost/transport conventions before invocation. Do not auto-refresh or add chat-list
badges, background polling or a new research dashboard. Preserve the CHR2 automatic Exact versus manual
Approximate checks and hidden-tab behavior.

Exercise meaningful/empty/approximate deltas, loading, duplicate click, failure/retry, switching conversations
mid-request, resulting citations and Save/Pin in a running isolated browser. Inspect light/dark, narrow/normal
width, keyboard/focus and readable language against DESIGN/AUDIT. A fixture browser pass proves wiring, not the
quality of real paid synthesis. Prepare a small representative real-evidence case and cost disclosure; run it
only within an already-authorized applicable budget, otherwise keep live synthesis acceptance explicitly blocked.
Obtain the required human visual judgment on the concrete result without stopping independent engineering.

### CE8 — CHR3 release boundary

Freeze the candidate and run Section 6. Resolve failures rather than lowering gates. Deliver/push scoped changes
using the existing handoff ritual and observe version, health, ordinary chat and refreshed-chat behavior through
supported app surfaces. Record prepared, committed, delivered and live-verified separately. If acceptance or
delivery is blocked, retain a reviewable candidate and continue eligible CE9/CE10 work.

### CE9 — acceptance of existing research features

This is bounded evidence gathering and real acceptance, not permission to rebuild the Product Intelligence
roadmap. Use supported reads and verified private backup copies, refresh stale measurements, and present Kyle
the result needed for judgment. Inspect existing successful runs before scheduling anything new. Group related
nightly checks into one bounded run when authorized; do not repeat production work just to generate evidence.

| Existing gate | Agent work | Remaining decision/dependency |
|---|---|---|
| L-30/L-31/L-40/L-41, CR7, L-60/L-61 | Reconcile a real scheduled/nightly result, Project Delta, report and research-refresh execution; distinguish disabled, no work due, queued and completed | Applicable separate budgets and actual overnight outcome; Kyle judges usefulness of the report/adjudication lines |
| L-51 → L-52 | Present the real short review queue, reasons and disagreement coverage | Kyle judges its usefulness; enable the already-built report section only after that gate passes |
| CR8b-gate | Demonstrate one justified acquisition for a genuine open target, provenance, costs and resulting evidence | Real access/budget and usefulness verdict; CR8c expansion stays unadmitted |
| LP6 | Inspect a naturally occurring evidence/Claim change and reconstruct the proposed plan patch through existing provenance | A genuine trigger and understandable real result; never manufacture a live Claim change |
| AD4B | Refresh the descriptive discovery report; identify the exact unresolved question if one exists | Kyle decides whether a prospective static comparison is warranted; no speculative experiment build |
| FM1-gate | Check current supported network availability and genuine scholarly seed readiness; run the existing prototype when eligible | Useful real references and A–F verdict; FM2/FM3 are not admitted by this mission |

Historical sandbox/network limitations must be rechecked safely in the current environment, not repeated as
permanent facts. Do not bypass an access restriction. Every judgment package contains the actual result,
its limitations, the exact acceptance question and the agent's recommendation. The agent handles operations;
only judgment, physical action, account access and uncovered spend require Kyle.

**Checkpoint (2026-09-19):** public, read-only availability probes returned HTTP 200 from both
`api.crossref.org` and `api.openalex.org`, replacing the prior sandbox-unreachable observation. FM1 is therefore
no longer infrastructure-blocked; it still needs an eligible real project with a scholarly/review DOI and Kyle's
six-part usefulness judgment. No project database, provider credential, candidate, source or claim was read or
changed for this probe.

### CE10 — subreddit conditional track

Use the existing supported authenticated community-status check. If configuration is absent/unavailable, remain
BLOCKED and continue other work. Once present, establish approved official access, reconcile the preserved
candidate, and execute the canonical SUB-R8b bounded listing, minimal selected capture and provenance/visual
acceptance, then SUB-R9 versioning/release/delivery. Configuration presence, synthetic 5,000-row timings and the
old passing artifact are not substitutes for those gates. No scraper, anonymous fallback, credential inspection,
unbounded acquisition or deletion-policy redesign. Update/remove the existing monitor when its purpose ends.

### CE11 — closeout and completion truth

Reconcile every rung with its owning feature record. The mission is COMPLETE only when the included release and
acceptance gates pass, or Kyle explicitly removes/defers a remaining gate from scope and that decision is recorded.
“All autonomous work finished; awaiting X” is a valid checkpoint, not full completion. Unavailable access does not
erase unfinished work. Record delivered versions/SHAs, release/browser evidence, remaining deliberate deferrals,
and the next trigger for each deferred item. Archive this mission after full closure and update all front doors.

## 5. Boundaries and interruption rules

- Continue ordinary fixes, tests, browser checks, source reconciliation and documentation autonomously within
  the admitted scope. Keep human-gated evidence concrete; do not request routine permission per rung.
- No new spend ceiling is granted by this plan. Inspect already-authorized limits and disclose the actual
  action/transport/estimate before metered execution. The old gate doc's example budgets are not approvals.
  Prepare with deterministic fakes when a real paid gate is blocked; never label fake output as live proof.
- A required restart/delivery decision comes after the candidate is tested and reviewable. Respect active jobs
  and existing authorization; no speculative live cancellation, configuration change or restart to get a gate green.
- A discovered P0 safety/cost/data-integrity regression interrupts the sequence for a bounded repair. Other
  unrelated ideas remain parked; do not use this mission as authorization for a general refactor.
- Still outside scope: case 6 cosmetic cleanup; physical sleep test L-21; L-06/L-07 sample review and L-08 paid
  relevance experiment; L-70 Structured Delta; CR8c expansion; FM2/FM3; H1/H2; Neuro Everywhere; retention before
  its existing 2026-10-11 trigger. Preserve their existing records and gates.
- Stop execution only for explicit pause, full completion, or when all remaining eligible work depends on
  unresolved external input. A single blocked gate never ends independent work. Do not silently create a new
  recurring execution automation; the existing Reddit monitor retains its narrow purpose.

## 6. Verification and evidence

Read and run the relevant current gates; discover renamed files rather than inventing test paths:

- Extension: `tests/test_s54_send_screenshot.py`, `tests/test_s32_course_scanner.py`,
  `tests/test_s55_course_documents.py`, their existing `tests/js/` harnesses, and affected ingestion/capture gates.
- Chat: `tests/test_chr0_conversation_baseline.py`, `tests/test_chr1_conversation_delta.py`,
  `tests/js/run-chat-delta.mjs`, ordinary chat/tool/citation checks in `tests/test_core.py`,
  `tests/test_k7_chat_truncation.py`, `tests/test_s24_lost_chat_and_fk.py`, plus provider/budget tests touched.
- UI: `tests/test_s44_frontend_integrity.py`, `tests/test_s50_design_drift.py`, DESIGN/AUDIT comparison,
  real-browser interaction and required human visual acceptance.
- Existing features: their named gates in EXECUTION-LADDER, including S53/S56/S58/S60 and nightly/report tests.
- Baseline/release: `tests/test_s43_foundation.py`, `tests/test_s51_test_isolation.py`,
  `tests/test_repo_check.py`; use the catalog mission's exact additional gates for CE10.

At each runtime release boundary: full pytest, fake Tier 1, source-only repo-check, normal complete release-check
and version agreement, in the isolated checkout with private `NEUROSEARCH_DATA_DIR`, dotenv disabled and no
provider credentials. Check interpreter/CLI provenance first. Release-check enters with production-safe flags
(`NEUROSEARCH_FAKE_AI=0`) and supplies its own fakes; the separate Tier 1 uses `NEUROSEARCH_FAKE_AI=1`.
Do not use a skip flag or a changing source tree to manufacture a pass. Package, pyproject, modular UI state and
HTML markers agree; extension changes also match the loaded manifest. Preserve frozen numbers and QA baselines.

For every gate record: base/candidate SHA, actual command and environment, result, artifact location, real versus
fixture evidence, inspected versions/identifiers, remaining limitation and next action. Browser actions must
verify the real outcome rather than stopping at a successful HTTP response. Runtime edits invalidate old release
evidence for the edited candidate; documentation-only changes require source hygiene/link checks, not a claim of
a new runtime release.

## 7. Current checkpoint

2026-09-19: plan created against main `634aa44`; no runtime, live jobs, settings or provider operations changed.
Baseline source-only `repo_check.check_repo()` PASS with no findings; `git diff --check` PASS. Planning validation
and final commit are recorded in the corresponding handoff checkpoint. CE0 is the next execution action; CE10
remains blocked on approved Reddit API access. No feature gate is closed by writing this mission.

2026-09-19: isolated candidate `8a347720f0ddd820431c18d9e41d850e42c56bd7` adds executable extension-auth
regression coverage only: the focused auth gate is 8 passed. Its adjacent Send Screenshot, Course Scanner and
course-document gates remain to be run before release. The HTTP 200 public catalogue probes above remove FM1's
historical network limitation but do not constitute a Field Map run or a live research-feature acceptance.
