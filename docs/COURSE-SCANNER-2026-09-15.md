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
