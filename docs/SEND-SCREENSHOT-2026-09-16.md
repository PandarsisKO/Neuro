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

A single tile that was never cut short is labeled `visible_only` — the honest fallback tier the plan requires,
not a failure. A run that completes its full 2D tile grid (rows × columns, since the repair round's tiling
rewrite — see below) with no ceiling firing is labeled `full_page`. A run cut short by any ceiling is labeled
`partial_page` (with `capture_partial_reason` set to the ceiling that fired) — `full_page` is reserved
exclusively for a genuinely complete capture; this doc previously described ceiling-limited captures as
`full_page`, which stopped being true once `partial_page` was introduced (see "Repair round" below) and is
corrected here rather than left for a future session to puzzle out.

### Runtime ceilings (enforced per tile, against actual progress, not once up front)

| Ceiling | Value | Why per-tile |
|---|---|---|
| Total pixels (using the actual captured bitmap scale, across every tile) | 40,000,000 | A lazy/infinite feed keeps rendering while being scrolled; the only honest place to catch that is after each tile, using the page's CURRENT height, not its height when the capture started. The running total uses the real captured bitmap's scale (repair round 2, gap #4), not `devicePixelRatio` alone, so it agrees with what actually gets stitched. |
| Tiles | 60 | Same reasoning — a page can keep growing indefinitely in either dimension since 2D tiling replaced the original 1D fold loop. |
| Elapsed time | 60,000 ms | Bounds total wall-clock regardless of how fast the page grows. |

Whichever fires first stops the loop; everything captured so far is still stitched and sent, labeled honestly.
The final stitched canvas itself is also bounded — on a partial capture it spans only the bounding box of the
tiles actually captured, not the full measured page (repair round 3, gap #A), and `stitchShots()` preflights
its own canvas allocation against the same 40M-pixel ceiling as a hard backstop.

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

(Superseded — this was the pre-repair-round acceptance list for the original 1.8.0 spike. The current,
authoritative live-Chrome acceptance matrix is the one in "Repair round" below, expanded again in "Repair round
3"; that matrix is what Kyle actually needs to run, against the current extension version, before this feature
is trusted for daily use.)

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
of the 4 original BLOCKERS: load the unpacked extension in his own Chrome and run it against a few real
pages, including at least one wider-than-viewport page (to exercise the new horizontal tiling) and one
lazy/infinite-scroll page (to exercise the ceiling-on-actual-progress and grid-growth handling).

## Repair round 2 (2026-09-16, Kyle's independent re-review of shipped 1.9.0)

Kyle checked the actual GitHub head himself rather than trusting the repair round's own summary, confirmed the
work above is real and substantial, and would not call the mission complete: "Implementation: ~90-95% complete.
Release acceptance: not complete." He found 4 code gaps to fix before the still-outstanding live-Chrome
acceptance pass, plus 3 smaller hardening items folded into the same pass (not individually release-blocking).

Four gaps fixed:

1. **Grid-regrowth traversal could skip newly-inserted earlier tiles.** `nsPlanTileGrid` lays out tiles
   row-major. When the page's WIDTH grows mid-capture (a new column), every later row's tile index shifts in the
   rebuilt grid — continuing the walk from the old `idx` could walk straight past a tile that now sits *earlier*
   in the new grid than `idx` already is, and `seenTileKeys` doesn't help because that position was never seen.
   The result could then be labeled `full_page` while pixels were actually missing — the most important of the
   4 gaps for that reason. Fixed: any grid regrowth resets `idx = 0`; `seenTileKeys` makes re-visiting an
   already-captured landed position a cheap `nsScrollTo` + `continue`, and `CAPTURE_MAX_ELAPSED_MS` still bounds
   the total regardless of how many times regrowth triggers a restart.
2. **Worker-respawn reconciliation didn't verify the retryable blob actually exists.** The shipped
   `nsReconcileDecision` unconditionally mapped every persisted `uploading` record to `upload_failed`, offering
   a "Retry send" button even when IndexedDB had nothing left to retry — and the round-1 test explicitly encoded
   that weaker behavior. `nsReconcileDecision` now takes a third `blobExists` argument (checked via
   `NSBlobStore.get()` in `reconcileCapturesOnWorkerInit()`, keeping the decision function itself pure and
   jsdom-testable without a real IndexedDB): blob present → `upload_failed` (recoverable); blob absent →
   terminal `failed` with an honest "the captured image was not saved — please capture again" message.
3. **Blob TTL (2h / 5-max / 200MB) was not continuously enforced.** `pruneExpired()`'s policy was correct but
   only ever invoked at `onInstalled`/`onStartup` and after a successful upload's own cleanup — a screenshot
   that failed to upload and was never retried could sit in IndexedDB well past its promised 2 hours during a
   long-running Chrome session. The existing 5-minute heartbeat alarm now also calls `pruneCaptures()`.
4. **The 40M-pixel safety ceiling used `devicePixelRatio` rather than the actual captured bitmap scale.**
   `stitchShots()` was already correctly upgraded (round 1) to derive its placement scale from the first tile's
   real bitmap width via `nsStitchScale`, because Chrome's actual `captureVisibleTab` output can differ from
   `cssPixels × dpr` under zoom/rounding — but the ceiling's running pixel total still used `dpr` directly, so
   the safety limit and the actual stitched image could disagree under zoom/scaling edge cases. Fixed: the loop
   now derives `capturedScale` once, the same way, from the first captured tile's real bitmap (falling back to
   `dpr` only if bitmap decoding fails, so ceiling accounting can never block or break a capture), and uses it
   in place of `dpr` for the running total. `dpr` is untouched everywhere else — pure provenance metadata, per
   Kyle's explicit instruction.

Three smaller hardening items folded in (not individually release-blocking):

- `nsTileKey(x, y)` no longer rounds landed coordinates before keying on them — the design already settled on
  deduping by actual landed position, and rounding could theoretically collapse two genuinely distinct
  fractional scroll positions into the same key.
- `stitchShots()` now validates every captured bitmap shares the first one's dimensions and throws a clear
  `CaptureMechanismError` on a mismatch, instead of silently assuming uniform dimensions.
- `api_ingest_file`'s `capture_id` branch now wraps `db.create_or_get_capture_ingest_request(...)` in a
  try/except that deletes the already-written temp upload file and re-raises on any exception — previously an
  exception thrown after the temp file was written had no cleanup path at all.

Tests: `tests/test_s54_send_screenshot.py` grew from 31 to 43 (grid-regrowth traversal — including a
deliberately-reverted variant confirmed to fail, proving the harness catches the bug class — the 3-argument
`nsReconcileDecision` signature, the heartbeat-prune wiring, the pixel-ceiling scale derivation, unrounded
tile-key dedup, the stitch dimension-mismatch guard, and an injected-failure orphan-temp-file test against a
real `client.post`). All 43 pass; the touched-surface regression (`test_core.py`, `test_k_retrieval_fixes.py`,
`test_m1_epub.py`) is clean except the same pre-existing sandbox-only "OpenAI Embeddings is temporarily
unavailable" network failures noted elsewhere in this doc — confirmed unrelated by reproducing one in isolation
on a test that never touches this feature.

**The live-Chrome acceptance gate is still the mandatory closing step**, and Kyle specified the matrix it must
cover once the extension is reloaded unpacked (this matrix supersedes the original 1.8.0 spec's acceptance list above):

- ordinary short page; tall page with a sticky/fixed header
- a genuinely horizontally-scrolling page
- a page whose width/height grows DURING capture — specifically exercising gap #1's fix
- real Mac DPR/zoom output, with seam inspection
- canvas/WebGL content
- a cross-origin iframe
- switching tabs mid-capture must abort without capturing the wrong tab
- forced service-worker death while capturing
- forced service-worker death after blob persistence but before/during upload
- the same test with the IndexedDB blob deliberately ABSENT, confirming no bogus retry is offered — directly
  exercises gap #2's fix
- network loss after server acceptance, then Retry send, proving one capture-event/job/source association
  end to end
- partial-page ceiling behavior and honest UI labeling
- starting a course scan during a capture and vice versa, confirming mutual exclusion
- inspecting the resulting screenshot in the actual Neuro app: OCR, Suggested Findings, project-relative
  provenance, URL, timestamp, partial status, and the user note all correct
- close and reopen the extension popup DURING a capture — the operation must survive in the background
  (`capture:<tabId>` in `chrome.storage.local`, not popup-local state) and the reopened popup must pick up
  exactly where the running capture is
- verify the exact original scroll position is restored afterward in every outcome: a successful capture, a
  failed one, and one that fell back to the visible-area-only path — not just "restored to somewhere near the
  top"
- navigate to another path on the SAME origin mid-capture (e.g. `/calculator` → `/dashboard`) and confirm the
  capture aborts rather than silently continuing — directly exercises repair round 3's gap #B fix

Write the pass/fail results for each item into this doc (or a dated results file alongside it) and update
HANDOFF once the pass is complete — only then does this mission close.

## Repair round 3 (2026-09-16, Kyle's second independent re-review of shipped 1.9.1)

Kyle re-checked the GitHub head again after repair round 2 landed, confirmed all 4 gaps and 3 hardening items
from that round were genuinely fixed, and still would not close the mission. He found 3 more implementation
gaps, plus the same still-outstanding release/acceptance work (now with 3 more matrix items, folded into the
matrix above, and a fresh release-gate run against the final commit).

Three gaps fixed:

A. **The pixel ceiling never actually bounded the FINAL stitched image.** The 40M-pixel check (as fixed in
   round 2) correctly counts captured tiles using the real captured scale — but on a PARTIAL capture,
   `finalPageW`/`finalPageH` still fell back to the full MEASURED page dimensions (`pageW`/`pageH`) whenever
   those were larger than what was actually captured. `stitchShots()` then allocated an `OffscreenCanvas` at
   that full size — so a capture that correctly stopped early at ~40M captured pixels on an enormous or
   infinite-scroll page could still attempt to allocate a canvas hundreds of millions of pixels large. Fixed in
   two layers: (1) the stitch canvas size is now the bounding box of the tiles actually captured
   (`shotsMaxX`/`shotsMaxY`) whenever the capture is partial — the full measured page size is only trusted when
   the capture is `complete`; (2) `stitchShots()` itself now preflights `w * h` against
   `CAPTURE_MAX_TOTAL_PIXELS` and throws before calling `new OffscreenCanvas(w, h)`, a hard backstop independent
   of whatever its caller computed. The reported `page_width`/`page_height` provenance is kept separate and
   still reports the TRUE measured page size — `partial_page` + `partial_reason` already label the result
   honestly; shrinking the reported page size to match the captured area would make an incomplete capture look
   like a smaller, complete one.
B. **Same-origin navigation could silently corrupt provenance.** `verifyTabIdentity` compared tab ORIGIN only,
   so a navigation from `example.com/calculator` to `example.com/dashboard` mid-capture passed unnoticed, while
   the uploaded provenance (`rec.url`) kept naming the URL recorded when the capture started — an old-URL,
   new-image mismatch. Same-origin is not a strong enough identity for evidence. Fixed: a new pure helper
   `nsPageIdentity(urlStr)` (`extension/capture-lib.js`) pins `origin + pathname + search` (a hash-only change —
   an in-page anchor jump — is still the same document and stays allowed); `verifyTabIdentity` now compares
   this instead of origin alone, and fails closed (`TabIdentityError`) on any change.
C. **A narrow MV3 durability hole between saving the Blob and persisting the upload state.** The code saved the
   Blob to IndexedDB first, then flipped the record to `'uploading'` and persisted THAT. If the worker died in
   between those two steps, the persisted record still said `'capturing'` — and reconciliation treats every
   `'capturing'` record as an unconditional hard failure, discarding a Blob that may have safely reached
   IndexedDB. Fixed: a new durable intermediate state, `'captured'`. Metadata (status → `'captured'`,
   `pending_upload` set) now persists BEFORE the blob write; the blob write happens second; the transition to
   `'uploading'` happens third. `'captured'` is treated identically to `'uploading'` everywhere blob existence
   matters — `nsReconcileDecision`, `reconcileCapturesOnWorkerInit()`, AND the in-process catch block in
   `startCapture` (which cannot simply trust the `'captured'` status string either, since `NSBlobStore.put()`
   itself could be what threw — it re-checks IndexedDB the same way the worker-restart path does). On restart:
   `captured` + blob present → recoverable `upload_failed`; `captured` + no blob → hard `failed`. `'captured'`
   is also active for mutual exclusion (`CAPTURE_ACTIVE`, `CAPTURE_ACTIVE_UI`) exactly like `'capturing'`/
   `'uploading'`.

Tests: `tests/test_s54_send_screenshot.py` grew from 43 to 53 — new coverage for the bounded partial-capture
stitch, the `stitchShots` pixel-ceiling preflight, `nsPageIdentity` (same-document pinning, hash-only changes
staying allowed), `verifyTabIdentity`'s updated comparison, the `'captured'`-before-blob-write ordering, and
the durability catch block's blob-existence recheck (not just its status string) for the in-process failure
path. All 53 pass.

Extension bumped to 1.9.2. `page_width`/`page_height` remain the true measured page size on a partial capture
(unchanged contract); only the internal stitch canvas allocation and `verifyTabIdentity`'s comparison changed.
The live-Chrome acceptance matrix above now includes the 3 additional cases Kyle specified this round (popup
close/reopen mid-capture, exact scroll-position restoration in every outcome, and same-origin navigation
aborting a capture) and remains the mandatory closing step — still not run.

A fresh full release-gate pass (pytest, Tier 1, release-check, version agreement) was run against this round's
final commit (`7b77fdd`) in the isolated workspace, per HANDOFF's rule that a prior pass does not count for
edited code:

- **Full pytest** (`pytest -q -n 4`, 1759 tests collected): 1713 passed, 46 failed. Every failure was inspected
  and confirmed pre-existing/environmental, not caused by this repair round — none touch a file this mission
  has ever edited. Two categories: (1) local-Claude-Code-CLI and OpenAI-embeddings network dependencies
  unavailable in this sandbox (`test_r4_local_model.py`, `test_j3_fallback.py`, `test_n2_local_ai.py`,
  `test_s39_answering_model.py`, `test_s43_foundation.py`, `test_p1_perf.py`, `test_indestructible.py`, and the
  network-touching tests in `test_core.py`/`test_k_retrieval_fixes.py` — several reproduce in isolation on
  files this mission never touched); (2) two unrelated stale-value tests —
  `test_s33_page_videos.py::test_the_extension_version_moved_again` hard-codes a manifest version literal
  (`"1.7.0"`) from an earlier mission and has been stale since the extension first passed 1.7.0, long before
  this mission started, and `test_s50_design_drift.py::test_colour_literals_stay_in_the_token_blocks` is a
  web-UI CSS/JS colour-literal ceiling unrelated to the extension. `tests/test_s54_send_screenshot.py` itself:
  53/53 passed.
- **Tier 1 / release-check** (`neurosearch release-check --no-pytest`): PASS on every deterministic,
  no-live-calls gate — schema registry, contracts, web JS modules parse (`UI_VERSION 0.63.91`), Tier 1 frozen
  totals and structured-output events, retrieval regression baseline, cache layout, H1 prefilter quality/
  economic gates, backup/restore round trip. Two FAILs, both pre-existing and unrelated: `repository hygiene`
  flags `STATE-OF-THE-APP-2026-09-14-1217.md` as an unexpected root entry (committed `b07f2a1`, 2026-09-14,
  before this mission); `Foundation` fails on the same local-Claude-Code-CLI-unavailable
  `test_local_failure_never_opens_paid_transport` parametrization pytest already surfaced. Artifact:
  `evals/release/release-check-0.63.91-7b77fdd-20260916-035224.json`.
- **Version agreement**: `pyproject.toml`, `neurosearch/__init__.py`, and `web/js/state.js`'s `UI_VERSION` all
  read `0.63.91` — confirmed both directly and via release-check's own passing "web JavaScript modules parse"
  gate. (This is the app's own version; unrelated to the extension's independently-versioned `manifest.json`,
  now 1.9.2.)

Net: nothing in this release gate implicates the send-screenshot feature or this repair round's changes. The
live-Chrome acceptance matrix above remains the only work between here and closing this mission.
