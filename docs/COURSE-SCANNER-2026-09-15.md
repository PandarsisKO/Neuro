# Course Scanner — "Scan this course" hardening (mission CS)

Date opened: 2026-09-15. Owner: Claude lane. Live acceptance case: SMB Market classroom
(`smbmarket.com/dashboard/educational-hub/classroom/`), using Kyle's already-signed-in Chrome. This note is the
mission's single design artifact: measurements first, then the architecture those measurements earned, then the
outcome contract, persistence model, safety boundaries, limits and live results. It is appended per rung
(CS0–CS6); nothing here is a diary.

Standing product rule this mission reopens: extension 1.6.0 concluded "app-rendered course → cannot list it →
open each lesson and press Send this page". That was a correct statement about a `fetch()` crawler and a wrong
statement about the browser. The browser is already rendering every lesson for the logged-in user; the question
is whether Neuro can operate the course's own navigation, safely, and read what renders.

## CS0 — SMB Market measured in the real browser (2026-09-15)

Method: Claude in Chrome against Kyle's logged-in tab; `javascript_tool` reading the live DOM, resource timing and
mutation counts; programmatic `.click()` on course-navigation controls only. Recorded: URLs (host + path),
counts, timings, attribute NAMES and class tokens. Not recorded, by rule: request/response headers, cookies,
tokens, bodies, query values, lesson text. The Loom embed ids below are truncated on purpose.

**Page shape.** Next.js app; one address for the whole classroom (`…/classroom/`), never changes, `history.length`
never moves (so `history.back()` would LEAVE the course — never use it for restoration). Course home shows six
"path" cards; the lesson view replaces the same `main` region.

| What | Measured |
|---|---|
| Modules ("paths") | 6 × `<button class="group block w-full text-left">` in a `div.grid` under `main`; text = `<title><N> lessons`; 6·5·7·7·11·7 = **43 lessons** visible on the home page. No collapse, no lazy render, no scrolling needed. |
| Module activation | `.click()` on a card swaps `main` to that module's **lesson 1** view (heading `Lesson 1 · <title>`), renders the module's full lesson list, and fires `GET api.smbmarket.com/api/v1/classroom/courses/<uuid>` + `/lessons/<uuid>`. |
| Lessons | Sibling `<button type=button data-slot=item data-variant=outline data-size=sm>` inside one `[data-slot=item-group]`; text = `<ordinal>. <title>[<duration>m]` (duration absent on some). All 11 rows of the largest module render at once: `overflow: visible`, not virtualised, no scroll required. |
| Lesson activation | `.click()` → heading changes, the Loom `<iframe>` is REPLACED (new 32-hex embed id), `GET …/classroom/lessons/<uuid>` fires. Programmatic click ≡ human click (identical transitions to the screenshot). |
| Selected state | No `aria-selected`/`aria-current`/`data-state`. The active row differs only by class tokens (`border-foreground/25!`, `bg-muted/50`) and its leading icon (play-circle vs circle). Selection must therefore be verified by CONTENT change (heading / iframe set / API fetch), not by an ARIA attribute. |
| Settle timing | Last `main` mutation **≈130 ms** after the click; heading + iframe present at the first 100 ms sample; `iframe` count transiently 3 then 1 within ≈1.4 s (player scaffolding). No further mutations for the following 10 s. |
| Player / media | Every lesson opened (mod 1: 1–4, mod 2: 1–3, mod 5: 1) rendered `www.loom.com/embed/<32-hex>` as an `<iframe src>` with `hide_owner/hideEmbedTopBar/hide_share` query flags — a **stable Loom identity**, readable from the DOM without Play. Zero `<video>` elements; no `.m3u8`/`.mp4` in resource timing (Loom keeps delivery inside its own frame). Resource timing ALSO lists the embed URL — corroborating evidence, not needed. |
| Stable ids | Lesson uuid appears only in the API URL the page fetches (`/lessons/<uuid>`), not on the control; the Loom embed id is the stable media identity; `(module title, ordinal)` is the stable lesson identity within the page. |
| Getting back | Breadcrumb `<button data-slot=breadcrumb-link>` "Learning" (inside `ol[data-slot=breadcrumb-list]`) returns to the module grid. Restoration = breadcrumb → (original module) → (original lesson). |
| Dangerous controls present in `main` | "Start course", "Prev", "Complete & next", quiz answers "A./B./C./D.", "Submit quiz", "Add to Calendar", "Deal Coach", "View calendar" (link). None is a sibling of the lesson rows' `item-group`; none has an ordinal-title(-duration) text shape. |
| Throttling (measurement caveat that is also a product limit) | With the tab hidden, Chrome throttled the page's timers to ~1 s, and after ~5 min hidden to Chrome's "intensive" tier — one loop iteration hung a 45 s CDP evaluate. DOM updates and MutationObserver callbacks still fired promptly. A long scan in a background tab therefore SLOWS (each bounded wait becomes ≥1 s / ≥1 min) but does not corrupt. |

**Conclusions the architecture is built on**
1. Strategy B is viable without any adapter: positive identification = ≥3 sibling controls in one container whose
   text matches `^\d+[.)]\s+\S` (optionally `\d+m$`), plus a module tier of ≥2 siblings matching `\b\d+\s+lessons?\b`.
   Nothing SMB-specific (no class tokens) is needed to find or drive them.
2. "Changed" must be a multi-signal verdict: `main` heading text, the set of player identities in the DOM, and new
   resource-timing entries since activation. Class-token diffs are a weak fourth signal, never sufficient alone.
3. Settle policy (CS0 output): wait for a **quiet window of 500 ms** with no `main` childList/attribute
   mutations AND a stable iframe set across two consecutive samples, after a minimum of 250 ms; hard cap **6 s**
   wall-clock. Under throttling the waits stretch; the cap is wall-clock, so throttling delays but never
   misclassifies.
4. Media identity comes from the rendered player element (Loom embed id). Resource timing is fallback evidence
   only; signed delivery URLs (`.m3u8`, CDN) are never treated as identity.
5. Restoration uses the page's own navigation (breadcrumb → module → lesson), never `history.back()`.
6. Coverage check: sum of the module cards' "N lessons" labels (43) vs lessons actually reached.

## CS1 — the scanner as a strategy pipeline (extension/scan-lib.js, 1.7.0)

`extension/scan-lib.js` is the one library the content script (`scanner.js`), the background service worker
(`background.js`), and the jsdom test harness (`tests/js/run.mjs`) all load unmodified — no second implementation.

- **Strategy A** (linked lesson pages) is 1.6.0's `fetch()`-per-lesson-page behaviour, unchanged, still the path for
  a course whose lessons are separate URLs.
- **Strategy B** (interactive SPA traversal) is what SMB Market needs: sequential `.click()` through modules then
  lessons, `allLessonRows()` diffed before/after each module activation to tell an accordion (rows inserted
  in-place, module card still findable) from a whole-view replace (SMB's shape — breadcrumb `findBackControl()` is
  used to return), `settle()` (the CS0-measured 500 ms quiet / 6 s cap policy, never a fixed sleep) after every
  click, and a bounded 1.5 s grace wait for a lazy-mounted player only when zero players were found on the first
  pass.
- **Strategy C** (rendered-content inspection) is folded into player detection rather than a separate pass:
  `findPlayers(doc, base, {rendered: true})` / `renderedPlayers()` scope the DOM scan to the active lesson's
  rendered markup — iframes, `<video>`, data attributes, links — and deliberately skip the whole-document
  inline-script regex scan Strategy A uses, because an SPA's serialized state blob (every lesson's Loom id, in one
  `<script>` tag) would otherwise get credited to whichever lesson happens to be open. `adapters = []` stays
  empty — no SMB-specific selector exists anywhere in the generic path (`test_no_platform_selectors_in_the_generic_scanner`
  greps for it).

Every lesson ends in one of `video_found / multiple_videos / no_video / needs_user_play / blocked / scan_failed /
not_scanned` — never silently dropped. Control classification (`siblingGroups`) is positive-identification-first:
a bounded ancestor climb finds the lowest container holding ≥3 (lessons) or ≥2 (modules) structurally-matching
rows; a denylist (`isDangerous`) is a second barrier, not the primary signal — proven against a fixture that
interleaves real lesson rows with Purchase/Complete lesson/Take quiz/Download certificate/Logout/Delete my
account/Submit quiz/Pay now, none of which are ever clicked. `changed()` is multi-signal (heading, rendered-player
set, resource count, URL), per CS0 conclusion 2. Media identity is stable-provider-only (Loom/Vimeo/YouTube/
Wistia/Vidyard via `IDENTITY`); a direct/CDN/`.m3u8`/`.mp4` url is marked `ephemeral: true` and never used for
dedup or identity. `duplicates()` returns `{mediaKey: [lessonIndexes]}` so a video referenced by more than one
lesson is reported against every lesson that uses it.

**Durable scan state** lives in `background.js`, keyed `scan:<tabId>` (never a singleton record) — a second
`scan-start` on a tab with an active scan is refused. Every message carries the run's `scan_id`; the background
ignores anything from a superseded runner. An interruption is only ever tab close, origin change, or an unanswered
liveness ping (`scan-ping`) to the content script — never a bare `tabs.onUpdated` URL change, since an SPA
legitimately rewrites its path/hash while switching lessons. `scanner.js` is a thin bridge with an isolated-world
marker (`globalThis.__nsScanActive`) so a double click or a popup reopen can never start two simultaneous
traversals. `popup.js` is a pure view of that state via `chrome.storage.onChanged` — closing and reopening the
popup mid-scan shows whatever is currently true — and speaks only in the user's words (lessons, videos, "needs
attention"); no DOM/selector/strategy/cookie/scrape language reaches it (`test_the_popup_speaks_in_lessons_and_videos_not_mechanics`).
Cookies are collected only at the explicit "Send" press, scoped to the course host and the hosts of the picked
lessons' videos — never earlier, never broader.

**Testing.** `tests/js/run.mjs` runs the shipped `scan-lib.js` inside jsdom against 8 synthetic course fixtures
(`tests/fixtures/courses/courses/*.html`: an SMB-shaped SPA, a collapsed accordion, a lazy/delayed player, a
no-video/locked lesson, a shared-video pair, a broken lesson that must not cost the others, a "current page
counts" single-lesson page, and the danger-button safety fixture) plus the original linked-course fixture.
`test_s32_course_scanner.py` (21 tests) proves classification, traversal, settling, outcomes, dedupe, cancellation
at a lesson boundary, and the safety rule against the shipped file — not a reimplementation. This proves
classification/DOM traversal/MutationObserver settling/outcomes/dedupe/partial-failure/safety; it does NOT prove
real React event semantics, real Chrome resource timing, the MV3 service-worker lifecycle, or SMB Market itself —
those stay live-browser gates (CS5, below).

## CS3 — course-import hardening (neurosearch/courses.py)

`import_course` now groups lessons by their normalised video url *before* enqueueing anything: a video shared by
two lessons (a repeated intro, a recap) produces one `ingest_url` job, and the response's `shared` list still
names every url more than one lesson referenced — a duplicate acquisition is never reported as a duplicate
membership. `db.sources_for_urls` (the same derived-truth check `add_page_videos` already used — no second "added"
flag) reports an already-downloaded video via `already_present` instead of requeueing it. `normalise_embed` is
untouched: only the providers `scan-lib.js`'s `IDENTITY` table treats as stable are canonicalised; anything else
groups on its literal string, which can only under-dedupe, never wrongly merge two different videos.
`needs_attention` was confirmed to never have been part of this endpoint — the only occurrence in `api.py` is the
unrelated `/scheduled` summary — so attention counts stay purely client-side, in the extension's own scan state.

## CS4 — the scanner gate installs its own dependency

A session-scoped autouse pytest fixture in `test_s32_course_scanner.py` runs `npm ci --prefix tests/js` (against
the committed lockfile) the first time a test needs jsdom and it isn't installed yet, and fails the whole module —
not a skip — if npm is missing or the install itself fails. `python -m pytest tests`, already the release-check
gate (`neurosearch/release.py::release_check`), now exercises the scanner's full jsdom coverage on any machine
with npm, without a separate manual step to remember.

## CS5 — live SMB Market acceptance gate (scan + enumerate only)

Not yet run. Scope, per the mission: press "Scan this course" against Kyle's real, logged-in SMB Market classroom
tab and confirm the scanner finds the lessons and their videos honestly — comparing the scanned count against the
module cards' "N lessons" labels (43, per CS0) — plus popup close/reopen mid-scan, cancellation, and partial-
coverage reporting. Explicitly NOT a bulk import/download test.

## Known limitations

- Strategy B's control classification is proven against the shapes CS0 measured and the safety fixture's decoy
  buttons; a platform with a materially different sibling-group structure (e.g. lesson rows nested inside their
  own module's DOM subtree rather than a flat list) has not been measured and may need real-browser tuning before
  it traverses correctly.
- `ephemeral: true` media (direct/CDN urls) is intentionally never deduped against the library by `import_course`
  — a course that only exposes signed/short-lived delivery urls will queue a fresh job per lesson even if two
  lessons happen to share the same underlying file, until a provider's identity is measured stable enough to add
  to `IDENTITY`.
- `adapters = []` is still empty. No platform has earned an adapter yet.
