# Send screenshot — capture-and-send extension feature (mission "send screenshot")

Date opened: 2026-09-16. Owner: Claude lane. This note is the mission's design artifact: Kyle's original spec,
the three rounds of revision he required before approval, the architecture those revisions produced, the runtime
contract, limits, test coverage and what still needs Kyle's own hands (loading the unpacked extension — Claude in
Chrome cannot reach `chrome://extensions`).

## Purpose

Some of what Neuro needs to research can't be reconstructed from a URL or from HTML alone: a loan calculator's
result for a specific input, a configurator's current build, a dashboard's numbers right now. "Send screenshot"
captures the page AS RENDERED, right now, in the user's own browser, and sends it into Neuro's existing image
pipeline as evidence — the same pipeline an uploaded photo of a whiteboard already goes through (OCR → chunks →
findings → claims). No new ingestion system was built for this; the extension side is new, the server side is a
narrow, explicit extension of one existing endpoint.

## What Kyle approved, and why (revision history)

The plan went through three rounds of explicit revision before "Approved, execute the mission." Each item below
names the concern and where it landed in the shipped code — kept here so a later reader does not have to
reconstruct WHY the code looks the way it does.

**Round 1**
1. Start with `chrome.tabs.captureVisibleTab` + scroll/stitch only; do not add the `debugger` permission unless
   scroll/stitch proves materially inadequate. → `debugger` is not in `manifest.json`; not used anywhere.
   Deliberately excluded pending Kyle's own manual verification of real pixel output (see "What still needs
   Kyle" below) — if that verification finds scroll/stitch materially broken, `debugger` needs its OWN approval
   round before it is even proposed, not silently added.
2. Structured, capture-specific provenance (not a generic metadata bucket): url, page title, captured_at,
   full_page vs visible_only, page/viewport dimensions, DPR, optional note. → the `source_captures` table
   (below) carries exactly this set, nothing more.
3. Never `immediate=true` for the production flow; accepted/queued, then the normal async pipeline and automatic
   Suggested Findings. → `background.js`'s upload always sends `immediate: 'false'`.
4. A FormData-aware `apiForm()` (the existing `api()` hardcodes JSON content-type). → added in `background.js`,
   alongside the unchanged `api()`.
5. Extend `/api/ingest/file`'s server contract with the smallest set of capture fields needed. → 10 new optional
   `Form(...)` params on `api_ingest_file` (11 counting the later-added `capture_partial_reason`, see Round 3).
6. The user's note is user-authored context, never the source title, never merged into OCR evidence. →
   `capture_note` is its own column, its own form field, never touches `title`; a page's OWN title
   (`capture_page_title`) becomes the source title instead of the uploaded filename.
7. An explicit max page height/pixel budget from the measurement spike; infinite/lazy feeds must not become
   unbounded jobs. → three ceilings, enforced per fold (see "Runtime ceilings" below).

**Round 2**
1. Capture metadata does NOT live as columns on `sources` — global image-byte dedupe means identical screenshot
   bytes can resolve to one existing `sources` row while representing a genuinely new capture event (different
   timestamp/URL/project/note). Nine columns on the global source would overwrite the first capture or lose a
   later one. → a separate `source_captures` table, keyed to `source_id` (nullable until resolved). Proven by
   `test_two_captures_of_identical_bytes_both_get_their_own_capture_event` (`tests/test_s54_send_screenshot.py`):
   two presses with identical pixel bytes dedupe to one `sources` row but keep two distinct
   `source_captures` rows.
2. The async contract must never claim "source created" when the upload merely returns — "accepted, job queued"
   is the honest claim. → `api_ingest_file`'s queued-path response carries `job`/`status: "queued"`/`immediate:
   False` and never a `source_id`; proven by `test_screenshot_upload_is_accepted_and_queued_not_immediate`.
3. Capture metadata must survive the queued-job boundary — persist BEFORE enqueueing, or it vanishes with the
   job's own argument list. → `api_ingest_file` calls `db.create_pending_capture_event(...)` before
   `jobs.enqueue(...)`; only the resulting `capture_event_id` (never the raw fields) travels in the job payload;
   `ingest_image` calls `db.materialize_capture_event(capture_event_id, source_id)` once a source_id exists,
   covering both the dedup-early-return path and the full-ingest path.
4. Three runtime ceilings (pixels / folds / elapsed time), re-checked PER FOLD, not once up front, because a
   lazy/infinite page can grow WHILE it is being scrolled. → `runCapture()`'s loop re-measures
   `document.documentElement.scrollHeight` after every fold; whichever ceiling trips first stops the loop and the
   result is still stitched from what was captured, labeled `full_page` with a `capture_partial_reason`
   (`ceiling_pixels` / `ceiling_folds` / `ceiling_time`) rather than being thrown away.
5. `try/finally` restoration of every mutated style and the exact scroll position, PLUS a content-script
   watchdog independent of the background operation. → `runCapture()`'s `restore()` runs in a `try { … } finally
   { await restore(); }`-shaped flow (both the success path and the `catch` re-throw call it); separately,
   `capture-lib.js`'s `nsHideAndArm()` arms an in-page `setTimeout` that self-restores on its own timer if
   nothing ever calls `nsRestore()` — proven by `test_watchdog_self_heals_if_nothing_calls_restore`, which never
   calls restore at all and confirms the page heals itself.
6. The measurement spike must not leave permissions, code paths or instrumentation in the shipping extension. →
   the Phase 1 spike ran entirely as a standalone page outside `extension/`, using `document.write()` against a
   real top-level document (worked around several sandbox limitations — see the session's own notes); nothing
   from it was copied into the extension package. `manifest.json`'s permission list is unchanged from before this
   mission (`activeTab`, `scripting`, `cookies`, `storage`, `alarms`, `tabs` — no `debugger`).

**Round 3**: a verbatim repeat of Round 2's six points — every one was already addressed by the revision that
produced the list above; nothing further changed.

## Architecture

### Server: `source_captures` (neurosearch/db.py)

A capture event is NOT a source — it is a record of one press of "Send screenshot": which URL, what the page was
called, when, at what size/DPR, with what optional note, and (once resolved) which global `sources` row its
bytes landed on. `source_id` starts `NULL`; `db.create_pending_capture_event(...)` writes the row before the
ingest job is even enqueued, and `db.materialize_capture_event(capture_event_id, source_id)` fills `source_id`
in once ingestion resolves one — first write wins (idempotent against a retried or duplicate-triggered job).
`db.get_capture_events_for_source(source_id)` lists every capture event that ever landed on a given source
(useful later for "this evidence was captured N times, most recently on X").

### Server: `/api/ingest/file` contract extension (neurosearch/api.py)

11 new optional `Form(...)` params, all present together only for a screenshot capture: `capture_url`,
`capture_page_title`, `captured_at`, `capture_mode` (`full_page` | `visible_only`), `capture_partial_reason`
(`ceiling_pixels` | `ceiling_folds` | `ceiling_time` | unset), `capture_page_width/height`,
`capture_viewport_width/height`, `capture_dpr`, `capture_note`. When `capture_url` is present and no explicit
`title` was given, the source's title becomes the captured PAGE's title (`capture_page_title`), never the
uploaded filename — proven by `test_screenshot_job_materializes_capture_event_and_uses_page_title`. The async
(`immediate=false`) response is unchanged in shape from the existing contract (`job`, `status: "queued"`) — no
new response fields, because the honest thing to say is exactly what every other queued upload already says.

### Extension: capture engine (`extension/background.js` + `extension/capture-lib.js`)

`chrome.tabs.captureVisibleTab` is a background-only API, so the whole capture loop is orchestrated from
`background.js` (unlike the course scanner, which runs its traversal as a content-script driven by messages).
Durable per-tab state mirrors the scanner's pattern exactly, for exactly the same reason — MV3 may evict the
worker, and the popup may close, mid-operation:

- `capture:<tabId>` in `chrome.storage.local`, `{ capture_id, tab_id, url, title, project_id, note, status
  (capturing → uploading → done|failed), fold, started_at, updated_at, finished_at, error, result }`.
- The same per-tab promise-chain lock the scanner uses (`withScan`, reused here as `withCapture`) guards the
  synchronous "is one already running / create the record" step — a capture and a scan on the same tab would
  otherwise race over scroll position and DOM mutation.
- The popup (`popup.js`) is a pure VIEW: `chrome.storage.onChanged` on `capture:<tabId>` re-renders status;
  closing and reopening the popup mid-capture shows whatever is currently true.

The loop itself, per fold: scroll to the fold's Y (`window.scrollTo({behavior:'instant'})` + a bounded
`setTimeout` settle — NOT a `requestAnimationFrame` wait; Chrome throttles rAF to ~1fps in a backgrounded tab,
measured directly in the Phase 1 spike, so the scanner's own proven `setTimeout`-poll pattern is what this reuses
instead); for every fold after the first, hide sticky/fixed elements (`nsHideAndArm`, `visibility:hidden` so
layout — and `scrollHeight` — does not shift) so they do not "stamp" themselves into every subsequent fold;
`chrome.tabs.captureVisibleTab(...)`; restore (`nsRestore`); re-measure `scrollHeight` (the page may have grown);
check the three ceilings; continue or stop. Folds are stitched into one tall PNG with `OffscreenCanvas`
(available in MV3 service workers), DPR-aware (`Math.round(cssPixels * dpr)`).

A single fold that was never cut short is labeled `visible_only` — the honest fallback tier the plan requires,
not a failure. Two or more folds, or a run that was cut short by a ceiling, is labeled `full_page` (with
`capture_partial_reason` set when a ceiling fired).

### Runtime ceilings (enforced per fold, not once up front)

| Ceiling | Value | Why per-fold |
|---|---|---|
| Total pixels (post-DPR, across every fold) | 40,000,000 | A lazy/infinite feed keeps rendering while being scrolled; the only honest place to catch that is after each fold, using the page's CURRENT height, not its height when the capture started. |
| Folds | 30 | Same reasoning — a page can keep growing indefinitely. |
| Elapsed time | 60,000 ms | Bounds total wall-clock regardless of how fast the page grows. |

Whichever fires first stops the loop; everything captured so far is still stitched and sent, labeled honestly.

### Content-script watchdog

`nsHideAndArm(watchdogMs)` arms an in-page `setTimeout` (20s) that self-restores every hidden sticky/fixed
element on its own, independent of `background.js` staying alive, the message channel staying open, or any
`try/finally` on the background side ever running. `test_watchdog_self_heals_if_nothing_calls_restore`
(`tests/test_s54_send_screenshot.py` → `tests/js/run-capture.mjs`) proves this directly: it hides, waits past the
watchdog's timer, and never calls restore at all.

### Why `capture-lib.js` is a separate file

`nsMeasure`, `nsScrollTo`, `nsHideAndArm` and `nsRestore` are plain, closure-free functions (required anyway,
since `chrome.scripting.executeScript({ func })` serializes a function by its source text and runs it in the
target page's isolated world — a closure over outer state would serialize as broken source). Because they are
closure-free, they can be loaded two ways from the exact same file: `background.js` via `importScripts()` (a
classic, non-module MV3 service worker), and `tests/js/run-capture.mjs` via `window.eval()` against a jsdom
window — the identical technique `tests/js/run.mjs` already uses for `extension/scan-lib.js`. This is what lets
the sticky/fixed hide-and-restore mechanics be gated in CI rather than only verified once, by hand, in a spike.

## Test coverage (`tests/test_s54_send_screenshot.py`)

jsdom side (`tests/js/run-capture.mjs` against `tests/fixtures/capture/sticky-fixed.html`): measurement reports
viewport/DPR/title; hide touches only non-zero-area sticky/fixed elements (a zero-size sticky element and
ordinary static content are both left alone); restore undoes a hide completely; the watchdog self-heals
unassisted; a guard test asserts the primitives are NOT duplicated inline in `background.js` (so this file can
never quietly start testing dead code again if someone re-inlines them).

Server side (`client`/`run_queued_job` fixtures, mirroring `test_document_upload_job` in `tests/test_core.py`):
the queued response never implies a source exists; the job materializes the capture event and the page's title
(not the filename) becomes the source title; the note is preserved separately and never becomes the title;
`capture_partial_reason` round-trips; two captures of byte-identical screenshots dedupe to one `sources` row but
keep two distinct `source_captures` rows.

jsdom does no real layout — `getBoundingClientRect()` is zero for every element by default — so the fixture
stubs three elements' rects explicitly (see the fixture's own comment) rather than letting that limitation turn
the hide/skip test into a false negative.

## What jsdom does NOT prove — still needs Kyle's own hands

Same boundary the course scanner drew (`docs/COURSE-SCANNER-2026-09-15.md`): jsdom proves DOM mechanics, not a
real browser's rendering pipeline. Not yet verified live, because Claude in Chrome cannot reach
`chrome://extensions` to load an unpacked extension:

- **Real `captureVisibleTab` pixel output** — does the sticky header actually appear exactly once per stitched
  image, or does hiding it cause a visible layout jump anyway on some site's CSS.
- **DPR crop correctness** against a real HiDPI screen (the math is `Math.round(cssPixels * dpr)`; unverified
  against an actual 2x/3x display).
- **Canvas/WebGL survival** through `captureVisibleTab` (the spike's synthetic canvas test suggested this is
  fine, but was never checked against a captured PNG, only against the DOM before capture).
- **Cross-origin iframe content** — expected to appear as whatever the browser has already composited (same as
  any screenshot), never separately fetched; unverified against a real cross-origin embed.
- **A real infinite-scroll page** hitting the pixel/fold/time ceilings in practice, not just in the spike's
  synthetic `IntersectionObserver` fixture.

Kyle needs to load the unpacked extension (1.8.0) in his own Chrome and run the 12-item test list from the
original spec against a few real pages — a tall marketing page, a calculator, a dashboard with a sticky nav —
before this feature is trusted for daily use.

## Product gate

Ships when: one click sends a screenshot with no intermediate chat; the result is provenance-labeled honestly
(full_page vs visible_only, partial reason when relevant); the note stays separate from the evidence; Suggested
Findings appear automatically after ingestion; nothing is captured or sent except by explicit button press; and
Kyle's own manual pass against real pages (above) confirms the visual output is trustworthy.

## Repair round (2026-09-16, post-ship review)

The feature above shipped (`55a0291`, `013f906`) and Kyle then reviewed the SHIPPED code against this design,
finding 12 real gaps — 4 of them BLOCKERS (no `captureVisibleTab` rate limiter; wrong-tab capture risk; missing
horizontal-overflow handling; no real-browser acceptance gate) plus 8 more (mode mislabeling; missing visible-
area fallback; missing upload retry; a suspected — and disproven — cross-project Suggested-Findings gap;
provenance stored-but-not-surfaced; missing worker-restart reconciliation; scan/capture not actually mutually
exclusive; and this doc's own approval-history record not naming the repair round itself, which this paragraph
now fixes). Four further rounds of PLAN_ONLY revision followed (worker-init races, end-to-end upload
idempotency, whole-capture tile identity, and finally server-side capture/job creation atomicity) before Kyle's
explicit **"Approved to execute. Behind now."** authorized the repair implemented here.

What changed, by file:

- **`neurosearch/db.py`** — `source_captures` gained `client_capture_id` (partial-unique index, NULL-safe) and
  `ingest_job_id`, both written in the SAME insert (never a later UPDATE). New
  `create_or_get_capture_ingest_request()`: the extension's own `capture_id` (generated once per "Send
  screenshot" press, resent verbatim on every retry) is now the end-to-end idempotency key — a capture-event row
  and its ingest job are created atomically (`db.batch()`, insert-first/catch-`IntegrityError`/re-select, the
  same idiom `identity.py` already uses for source creation), so no concurrent-duplicate-job race and no
  crash-between-two-writes race can leave an orphan row or a duplicate job. `create_job()` gained an optional
  `job_id` param (backward compatible) so both writes can share one transaction. `get_capture_events_for_source`
  gained an optional `project_id` filter (see `sources_value.py` below).
- **`neurosearch/api.py`** — `api_ingest_file` gained a `capture_id` form field; when present, the atomic DB
  function above replaces the old create-then-enqueue sequence. A losing retry deletes its own just-uploaded temp
  file (the winner's job already references the winner's own file) rather than leaking it. The response reports
  the job's CURRENT status honestly, not a hardcoded `"queued"` — a retry landing after the job already finished
  is allowed to say so.
- **`extension/capture-lib.js`** — gained pure (non-DOM) helpers: 2D tile-grid planning (`nsPlanTileGrid`),
  whole-capture tile-identity dedup (`nsIsDuplicateTile`, a `Set` of every landed coordinate seen this run, not
  just the previous tile), ceiling checks against actual progress (`nsCheckCeilings`), stitch scale from the
  real captured bitmap rather than DPR alone (`nsStitchScale`), the global rate-limit wait calculation
  (`nsRateLimitWaitMs`), fallback eligibility by tagged error kind (`nsIsFallbackEligible`), and worker-restart
  reconciliation decisions (`nsReconcileDecision`). All exercised directly under jsdom
  (`tests/js/run-capture.mjs`), no real Chrome needed.
- **`extension/capture-blob-store.js`** (new) — durable IndexedDB blob storage keyed by `capture_id`,
  service-worker-only (never page-injected, unlike `capture-lib.js`). Retention is bounded and oldest-evicted:
  2 hour TTL, max 5 blobs, max 200MB combined — the pure policy function `nsBlobRetentionPlan` is testable
  without a real IndexedDB.
- **`extension/background.js`** — full capture-engine rewrite. A global `captureVisibleTab` rate limiter
  (`chrome.storage.session`, survives worker respawn, resets on browser restart, serialized by an in-process
  async lock) fixes the missing-throttle BLOCKER. Every single `captureVisibleTab` call (each tile, plus the
  fallback) re-verifies the target tab is still Chrome's ACTIVE tab and passes its real `windowId` explicitly,
  fixing the wrong-tab-capture BLOCKER. 2D tiling (rows × columns) replaces the old 1D fold loop, fixing the
  missing-horizontal-overflow BLOCKER; capture stitches at each tile's ACTUAL landed coordinate (not the
  requested scroll target). A `firstTileCaptured` flag (not a fold-index check) generalizes the sticky/fixed
  hide-for-all-but-the-first-tile rule to 2D. Two tagged error classes (`TabIdentityError`,
  `CaptureMechanismError`) gate a 5-step ordered visible-area fallback that runs ONLY on a genuine capture-
  mechanism failure, never when the target tab's identity became uncertain. Durability ordering: pixels →
  durable blob (`NSCaptureBlobStore.put`) → THEN `status='uploading'` → POST — a worker eviction between any two
  of those steps can never strand a record claiming to have sent something that was never saved. A new
  `capture-retry` message resubmits the same durable bytes under the same `capture_id`, recoverable from
  `upload_failed`. `reconcileCapturesOnWorkerInit()` runs unawaited on every worker initialization (MV3 may
  evict/respawn this worker at any point, not just at `onInstalled`/`onStartup`); `capture-start`,
  `capture-retry`, `capture-get` and `startScan`'s capture-active check all `await captureInit` first, so no
  message ever acts on a stale pre-reconciliation record. `startScan` and `startCapture` now check each other's
  active status — scan and capture are finally actually mutually exclusive per tab, not just each internally
  serialized.
- **`extension/popup.js` / `popup.html`** — a "Retry send" button appears exactly when a capture is
  `upload_failed`; new copy for `partial_page` mode and the tagged failure reasons
  (`tab_not_active`/`origin_changed`/`fallback_after_error`/`upload_failed`) in the user's own words, never DOM
  or mechanism jargon.
- **`neurosearch/sources_value.py` / `web/js/research.js`** — `digest()` now surfaces the newest capture THIS
  PROJECT made of a source (project-scoped only — a capture from a different project sharing the same
  dedup-merged source never appears here); the source drawer renders "Captured from *title* · date/time", the
  captured URL as a link, a "partial" chip when applicable, and the user's own note explicitly labeled as
  context, never merged into the evidence itself.
- **Suspected item 8 (cross-project Suggested Findings gap)** — investigated, not fixed: `identity.py`'s
  `resolve_or_create_source()` already calls `after_ready()` (which enqueues Suggested Findings) whenever a
  source is `EXISTING_READY` and gets newly attached to a project, before `ingest_image()`'s early return is
  even reached. The "fix" would have reintroduced the uncontrolled-duplicate-suggestion-jobs problem the
  original design explicitly avoided. A regression test proves the existing invariant instead of changing code.

Server-side gates for all of the above (concurrent-duplicate real-thread race, response-loss retry, atomicity
under an injected mid-batch failure, orphan-temp-file cleanup, project-relative provenance isolation) and
client-side pure-function gates (tile-grid planning, whole-capture dedup, ceilings-on-actual-progress, stitch
scale, rate-limit math, fallback eligibility, worker-restart reconciliation) live in
`tests/test_s54_send_screenshot.py` (31 tests) and `tests/js/run-capture.mjs`. The worker-init race, durability
ordering, capture_id-on-every-upload and firstTileCaptured-not-fold-index properties are gated as source-shape
assertions in the same file (the same technique the pre-existing "loaded by reference, not inlined" test uses) —
a jsdom harness cannot otherwise exercise MV3 worker-respawn timing or a real `chrome.storage.session` without a
full `chrome.*` mock.

**Still needs Kyle's own hands** — nothing above replaces the live-browser acceptance gate that was itself one
of the 4 original BLOCKERS: load the unpacked extension (1.9.0) in his own Chrome and run it against a few real
pages, including at least one wider-than-viewport page (to exercise the new horizontal tiling) and one
lazy/infinite-scroll page (to exercise the ceiling-on-actual-progress and grid-growth handling).
