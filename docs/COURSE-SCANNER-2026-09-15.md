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

Run against Kyle's real, logged-in SMB Market classroom tab, scan+enumerate only (no import, no cookies, no
download) — the scanner library injected directly into the live page and driven with a bridge whose `fetch` throws
(so Strategy A can never reach the network) and whose `cancelled()` always returns false, exercising the exact
shipped `extension/scan-lib.js` end to end against real, authenticated markup.

The first live pass surfaced four bugs, none of them SMB-specific — a text-adjacency bug that hid a whole module
behind a glued-together badge, a page-root layout wrapper that shadowed every control on the page as site-chrome,
a module title rejected over ordinary business vocabulary ("Your Buy Box and Buyer Profile", over "buy"), and a
split ordinal/period text node that broke LESSON_TEXT's anchor. Each was root-caused live, fixed generally, and
locked down with a new jsdom fixture; three of the four modules were then found correctly, 43 lessons expected,
matching CS0's measured total exactly, but 3 of 43 lessons were still missing.

The missing 3 were a fifth bug of the same shape: `isDangerous` had a second, LESSON_TEXT-specific re-check for
`quiz|certificate|purchase|checkout` that fired even on rows already positively matching the numbered-lesson
shape, rejecting three genuine M&A lesson titles ("How to Determine Your Purchase Price", "The Purchase Agreement
Explained", "How to Quantify the Purchase Price of a Business") over the word "purchase". This one needed more
care than the others: the safety fixture (`tests/fixtures/courses/courses/safety.html`) deliberately includes two
disguised numbered rows — "2. Purchase the full course" and "3. Take quiz" — that must stay refused, so a blanket
exemption (mirroring the module-vocabulary fix) broke an existing safety test. The fix distinguishes a title that
merely *mentions* the topic from a row that *is* the action: the danger word must either open the title, or be
the entire content of a two-word row, to still count as dangerous. That resolves both real cases with a general,
non-SMB-specific signal (word position, not wording), verified against jsdom (all 26 tests, including the safety
fixture) and spot-checked live via `NSScan.isDangerous()` against synthetic elements built from the exact real and
decoy titles before re-running the full scan.

Final result, all five fixes applied, one full live pass: **43/43 lessons across all 6 modules, every one
`video_found`, zero `scan_failed`, zero `count_mismatch`** — matching the module cards' own "N lessons" labels and
CS0's originally measured count exactly. `diagnosis.expanded_modules === 6`, `diagnosis.activated === 43`,
`diagnosis.unchanged === 0`, `diagnosis.back_control === true` (SMB replaces the whole list per module, so every
transition after the first needed the breadcrumb "Learning" control, and it was found and used correctly each
time).

Not yet separately exercised on this pass: popup close/reopen mid-scan, cancellation via the real extension UI,
and partial-coverage reporting through `background.js`'s durable per-tab state (this pass drove `NSScan.run`
directly, bypassing the extension's popup/background wiring entirely, since Claude in Chrome cannot reach
`chrome://extensions` to reload the unpacked build — CS2's live-browser verification remains open for the same
reason). Explicitly NOT a bulk import/download test: `bridge.fetch` was wired to throw, so Strategy A (and any
accidental use of it) could not have reached the network even if triggered.

## CS6 — Acquisition Ace: lesson CARDS, not lesson controls (extension 1.9.4, 2026-09-18)

Kyle, logged in to Ben Kelly's Acquisition Ace (courses.benkelly.co, three course tracks), pressed "Scan this
course" on a track's lesson page and got "No lessons found on this page" although every chapter and lesson was
plainly on screen. Measured in his Chrome: the page is a React SPA whose lesson rows are bare `<div>`s with a
framework click handler and `cursor: pointer` — no `button`, no `role`, no `tabindex`, no `<a>` — each holding
one `<h3>` (the title), a blurb and a "Duration 5:00" badge, grouped under `Chapter NN · Title  NN Lessons
Total` headers; 31 rows across 5 chapters, the last chapter's 9 bonus rows carrying no duration (documents).
Opening a row moves the URL to a per-lesson route, REPLACES the `<main>` element, and renders one Loom
`<iframe>`; the breadcrumb (`nav[aria-label=Breadcrumb]`, buttons "All Courses" › "<course>" › current span)
brings the list back. Fetching a lesson URL directly returns the SPA shell with no content.

Why every strategy missed it: Strategy A saw no lesson links (there are none); Strategy B's control shape needs
`CONTROL_SEL` (never a bare div) AND `LESSON_TEXT`'s "<ordinal>. <title>" (the site has no ordinals); Strategy C
saw no player on the list page. The result was honest ("none" with zero links/controls/modules) and wrong.

The fix is a second Strategy B shape, `cardRows()`, on the same principle of positive identification: a CARD is
the ancestor of a heading whose parent holds >= 2 siblings that each hold exactly one heading (repeated
structure), and a card GROUP is a lesson list only when at least half its rows carry a duration ("m:ss" or
"N min") or the group sits under a header that SAYS it is a module ("<title> N lessons" or "Chapter/Module/
Section/Unit/Week/Part/Day NN"). A card containing a link or a control belongs to the other shapes; a card is
judged for danger by its TITLE alone (a blurb saying "complete", "share" or "next" is prose). Ordinals are page
order; the module is the chapter header. No selector names the site (`test_no_platform_selectors_in_the_generic_scanner`).

Three more general repairs the same page forced: `settle()` observes `document.body`, not `<main>` (an observer
bound to a `<main>` the router replaces goes deaf, and "quiet" is declared at `min_ms`); `findBackControl()`
returns the crumb NEAREST the current view, never the first (the first is "All Courses" — the site root, which
would leave the course); and the flat-lesson loop, on failing to find a row, uses the back control and looks
again (the module loop already did this; a per-lesson-route list needed it per lesson). Lesson records now carry
the address each lesson rendered at (`page_url` = the per-lesson route, the start address when the URL does not
move), which is a better referer for `import_course`.

Gate: `tests/fixtures/courses/courses/cards.html` (that shape without the site's classes: 7 cards, a bonus
chapter without durations, a bare-CTA card among the lessons, a two-card "recommended" grid that is NOT a lesson
list) and `test_a_course_of_plain_card_rows_with_no_ordinal_and_no_button_is_traversed`; 28/28 in
`test_s32_course_scanner.py`. Live, the patched library driven directly in Kyle's tab
(`NSScan.run` with a recording bridge, `fetch` unwired): all 31 cards identified with the right chapters and
durations, and the traversal reported every video lesson `video_found` with a stable Loom identity — see the
HANDOFF entry for the final counts. That pass ran in a HIDDEN tab, where Chrome throttles timers to ~1 Hz, so it
took ~20 s per lesson; the extension runs on the active tab, where CS0's settle numbers apply.

## CS7 — a course's DOCUMENTS come in with its videos (extension 1.9.6, 2026-09-18)

Kyle, after CS6: "there are bonus lessons without video content, I still want the information, spreadsheets,
pdfs etc that are in them." Measured live on Acquisition Ace: the nine bonus lessons are each one Google Drive
share link (`drive.google.com/file/d/<id>/view`) to a PDF — Fast Track Checklist, Perfect Deal Finder, Goal
Setting Worksheet, Deal Calculator, Hands-Off Playbook, Recession-Proof Portfolio Builder, 7-Figure Letter
Generator, No-Money-Down Secrets, Student Success Stories — behind a "Download Resource" button, with no
player and a paragraph of sales copy. The scanner called them `no_video`; the importer dropped them.

Scanner: `findAttachments()` records each lesson's document links as stable identities (`documentIdentity`:
Drive/Docs/Sheets/Slides ids, Dropbox paths, direct addresses with a document extension) on
`record.attachments`; a lesson with no player and at least one document is `document_found`, a READY outcome
(`background.summarize`, popup). A video lesson keeps its worksheet on the same record. Nothing is fetched by
the scanner. A link's text names the file only when short and specific; a button's text ("download Download
Resource Included with your membership north_east…", live) does not, and the importer names the document after
its lesson.

Importer: `courses.import_course` queues each distinct attachment once through `ingest_url` (a document two
lessons link is fetched once and titled for both, exactly like a shared video), with NO cookies file — a
document host is not a video host and Kyle's Google session is never sent to the app. Response gains
`documents` (queued) and `nothing` (lessons with neither video nor document); `no_video` keeps its meaning.

App: `webpage.document_download_url()` turns a share link into the address that returns the FILE (Drive
`uc?export=download`, Docs/Slides `export?format=pdf`, Sheets `export?format=xlsx`, Dropbox `dl=1`, a direct
document address as itself); `ingest.ingest_url` routes such links to the new `ingest_document_url`, which
fetches through the J1 boundary (`webpage.fetch_with_headers`, document limits) and hands the bytes to
`ingest_local_file` — the existing upload path: PDF/DOCX/TXT → `ingest_document`, XLSX/CSV →
`ingest_spreadsheet` (pages AND a calculator), EPUB/images to theirs; identity is the file's content
fingerprint. The link is written back onto the file source's `url`, so `sources_for_urls` answers a re-import.
A share link that answers with HTML (Google's sign-in page for a file not shared "anyone with the link") is
`Blocked` with the instruction to download it in the browser and add it with Sources → Upload — never read as
the document.

Gates: `tests/test_s55_course_documents.py` (link → download address; a Drive PDF becomes a document named after
its lesson and is found by search; a Sheets link becomes a spreadsheet with a calculator; a sign-in wall is
blocked, not read; the same bytes behind two links are one source; the importer queues each document once and
sends no cookies for it), `cards.html` extended with Drive links (one shared by two bonus lessons) and a
worksheet on a video lesson. Live: `findAttachments` run in Kyle's tab on Bonus #4 found the Drive identity.
NOT yet exercised live: the actual fetch of these nine files by the app (whether Ben Kelly's Drive files are
shared publicly decides between nine ready documents and nine honest "sign-in" failures) — that is the first
import on the Mac.

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
