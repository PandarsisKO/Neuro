# F1 remaining scope — ready-to-execute specs

Written 2026-09-13, against `main` at `30ee4f4`. Not yet applied to `neurosearch/web/index.html` — held back
deliberately while Codex is restructuring that same file for the frontend-split initiative. This document exists
so the three items below can be executed immediately once that's safe, without re-deriving the scope.

## Correction to the record

The `HANDOFF.md` entry for "F1 step 2m" (the inline-style-retirement pass, steps 2c–2m) said that work "closes
out the entire `audit.md` offender ranking table" and treated F1 as finished. That's true only for one part of
what `docs/design-audit/2026-09-13-b85c222/ladder.md` actually scopes as **Rung F1**. The ladder defines F1 as
four things:

1. Land the frozen AA-validated color tokens — **done**, verified below.
2. Retire the tokenizable inline-style patterns on the ranked offender surfaces — **done**, steps 2c–2m (373 → 301
   inline `style=` attributes).
3. Fix the base-input rule that forces `width:auto` onto every filter `<select>` — **not done**.
4. Convert `style="display:none"` state toggles to the `hidden` attribute — **not done**.
5. Name the eight emoji-only controls via an inline SVG `<symbol>` sprite — **not done**.

So Rung F1 is roughly two-thirds done, not complete, and per the ladder's own sequencing (`F1 → F2 → W1 → …`),
Rung F2 (the loading/empty/failure state primitive, which fixes `H-2`) can't start until F1 fully closes. This
doc scopes the three remaining pieces precisely enough to execute in one sitting each, whenever `index.html` is
safe to touch again.

## 1. Token verification (already landed — confirmed, not a to-do)

Computed directly from the current `:root` / `[data-theme=dark]` blocks:

| pair | ratio | AA (4.5:1) |
|---|---|---|
| light `--ok` on `--panel` | 5.29:1 | pass |
| light `--warn` on `--panel` | 5.24:1 | pass |
| light `--bad` on `--panel` | 6.57:1 | pass |
| dark `--ok` on `--panel` | 8.72:1 | pass |
| dark `--warn` on `--panel` | 9.66:1 | pass |
| dark `--bad` on `--panel` | 6.27:1 | pass |

Matches `audit.md`'s own precomputed values (5.29 / 5.24) exactly — this half of `H-7` is closed. `test_s50`'s
`test_status_text_colours_meet_aa_on_panel` already covers this as a permanent gate.

## 2. `width:auto` — 14 sites, all `<select>` elements, all one mechanical class swap

**Root cause:** the base rule `input,textarea,select{width:100%}` (line 14) forces every form control full-width;
14 filter/inline `<select>` elements override it individually with `style="width:auto"` instead of a shared class.
(Checkboxes and Plan's inline selects already have this solved via existing CSS class rules — `.rv .li
input{width:auto}`, `.wk input{width:auto}`, `.plan .item select{width:auto}` — so this is narrower than
`ladder.md`'s "27 checkboxes and buttons" estimate; some of that gap has apparently already been closed by
whoever landed those three rules.)

**Fix:** add one utility class alongside the others already in the shared-rules block —

```css
.w-auto{width:auto}
```

— then mechanically replace all 14 occurrences of `style="width:auto"` with `class="w-auto"` (each select is
currently bare, no existing `class` attribute to merge into, so this is a straight attribute swap, not a merge).
Sites, by function: `loadCandidates`'s `#candState` filter (Sources), the discovery-mode `#discMode` select
(Research), six Findings filter-bar selects (`#fbStatus`, `#fbImp`, `#fbUsed`, `#fbStale`, `#fbArea`, `#fbSort`),
four Claims-workbench selects (`#cwStatus`, `#cwStrength`, `#cwFresh`, `#cwSort`), the Evidence Target
sufficiency select (`#resTargetS`), and Settings' `#factKind` select.

**Risk:** low — this is the same class of exact-match mechanical swap done throughout steps 2c–2m, just onto a
new utility class instead of an existing one. No JS reads `.style.width` on any of these elements (spot-checked;
re-verify at execution time). `MAX_INLINE_STYLE_ATTRS` drops from 301 to 287 once landed.

## 3. `display:none` → `hidden` attribute — scoped, needs JS coordination, medium risk

This one is not a pure markup swap like the rest of the F1 pass — an element toggled with
`el.style.display = 'none' / ''` in JS needs its toggle code changed to `el.hidden = true / false` at the same
time its markup changes, or the two will fight each other. Full breakdown at current count:

- **11 static `style="display:none"` exact-attribute sites** (candidates for the `hidden` attribute): the file
  attach `<input type="file">` (Chats askbar), `#jobsCard`, four Research pane containers (`#paneQuestions`,
  `#paneWatchouts`, `#paneAreas`, `#paneClaims`), `#cwBulk`, `#paneTools`, `#settleBtn`, and the per-source
  `#reserve-${s.id}` div (Sources). Each needs its paired toggle site found and converted alongside it.
- **26 `.style.display = ...` assignments in JS** — this is the larger number and the real work: every one of
  these needs to become a `.hidden = (boolean)` assignment instead. `renderShell`'s pane-switcher
  (`el.style.display = RES.pane === k ? '' : 'none'`) is the one that drives four of the eleven static sites above
  in one place, so it's a good first target — fixing it alongness its four panes closes a third of this item in
  one change.
- **2 dynamic ternary cases embedded in template strings** — the per-row filter-visibility toggle in `loadReviews`
  (`rvFilterText[c.id] && !... ? ' style="display:none"' : ''`) and a similar pattern elsewhere — these build the
  attribute string inline per-row rather than toggling a fixed element, so they need `?'hidden':''` substituted
  directly rather than a separate JS toggle function change.
- Several more `display:none` occurrences are **combined declarations** (e.g. `#fbGroupCtl`'s
  `style="display:none;gap:8px;margin:-2px 0 6px;font-size:12.5px"`) — these need the non-display parts either
  moved to a class first or left inline per the existing "one-off geometry may stay inline" rule in `DESIGN.md`
  §5; only the `display:none` half converts to `hidden`.

**Fix approach:** work element by element, not as one mechanical find/replace — for each of the 11 static sites,
locate every place that element's visibility is toggled (`grep` for its `id` near `.style.display`), convert both
the initial markup (`hidden` attribute, dropping `style="display:none"`) and every toggle site
(`el.hidden = true/false` instead of `el.style.display = 'none'/''`) together, then verify by reading the toggle
logic rather than assuming a 1:1 id-to-toggle mapping (some, like `renderShell`'s loop, drive several elements
from one piece of code).

**Risk:** medium — this is real behavior-adjacent code, not pure styling, so it needs the same care as the
dynamic-class cases deferred throughout steps 2c–2m, plus a JS read/write pass alongside the markup change. Test
with the panel actually switching visibility in both themes before landing, not just a green test suite.

## 4. Name the eight emoji-only controls — glyph inventory complete, sprite not built

`test_emoji_are_content_not_control_glyphs`'s own detector finds exactly 8 buttons whose only content is an
emoji, confirming `MAX_EMOJI_ONLY_CONTROLS = 8` is still the untouched baseline. All 8 collapse to **3 distinct
glyphs**, simpler than `ladder.md`'s "likely five distinct shapes" estimate:

| glyph | meaning | sites | source function |
|---|---|---|---|
| ✕ | dismiss / remove / cancel | 6 | `discStatus` dismiss (Research candidates), `sourceDrawer`'s `group()` helper (2x, approved/suggested/reserve finding actions), job cancel button, job dismiss-error button |
| ✓ | approve | 2 | `sourceDrawer`'s `group()` helper (reserve → approved, suggested → approved) |
| 📌 | send to Suggested | 1 | `sourceDrawer`'s `group()` helper (reserve → suggested) |

None currently carry a `title` or `aria-label` — confirmed gap.

**Fix, per `DESIGN.md` §6:** one inline `<svg>` block near the top of `<body>` holding three `<symbol>`
definitions (`ic-dismiss`/`ic-approve`/`ic-flag` or similar names — final naming is a small judgment call, not
mechanical), `stroke:currentColor`, one stroke weight. Each of the 8 buttons gets
`<svg class="ic"><use href="#ic-dismiss"></use></svg>` in place of the bare emoji, plus a `title` and
`aria-label` matching what the button actually does (e.g. "Dismiss", "Approve", "Send to Suggested" — vary by
context where the same glyph means slightly different things, e.g. job-cancel's ✕ should read "Cancel job", not
generic "Dismiss").

**New test to add** (per `ladder.md`'s F1 gate list): `test_s50` needs a new assertion that every icon-only
control (an element whose only child is an `<svg class="ic">`) has both `aria-label` and `title` — this becomes
a permanent gate alongside `MAX_EMOJI_ONLY_CONTROLS`, which drops from 8 toward 0 as each is converted.

**Risk:** low — additive (new sprite block, no existing markup removed except the bare emoji character), narrow
blast radius (8 known call sites), but needs real design judgment on exact glyph shapes and label wording, so
it's a "sit down and do it deliberately" task rather than a scripted mechanical pass.

## Sequencing note

Per `ladder.md`, none of `F2`/`W1`–`W5`/`C1` should start until all of Rung F1 (items 2–4 above) is closed —
"every workflow rung restyles buttons, banners and badges; doing that against drifted tokens means doing it
twice" is the stated reason, and it applies just as much to the `width:auto`/`display:none`/icon items as it did
to the inline-style retirement. Recommend landing items 2–4 above, in that order (lowest to highest risk), as
three more `f1-step2n`/`2o`/`2p`-style sub-units once it's safe to touch `index.html` again — then Rung F1 is
genuinely closed and F2 (the `H-2` loading-state fix) can begin.
