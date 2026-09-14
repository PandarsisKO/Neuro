# Design Audit — declutter, redundancy and semantic-mismatch pass, 2026-09-14

**Mode:** `AUDIT.md` §3 TARGETED AUDIT, requested by Kyle after the substance-bar revert (commit `bd95e65`): "review our
audits and design docs for mismatched ideas like that finding. Our mission is to declutter, reduce redundancies and
simplify." **Baseline:** commit `bd95e65`, `v0.63.82`, audit instance with `NEUROSEARCH_FAKE_AI=1`, dark theme,
606×757 viewport (the only width the browser tool could produce this session — layout observations are made from
DOM and CSS, not from the narrow rendering; Kyle has explicitly deprioritised narrow-viewport work). **Scope:**
Home, project sidebar, Sources, Findings, Research, Master Plan, Settings, Chat; `DESIGN.md`, `AUDIT.md`,
`docs/design-audit/2026-09-13-b85c222/{audit,ladder,reaudit}.md`, `docs/design-audit/2026-09-14-d64cb62/*.md`.

**Status: findings only. Nothing here has been built.** Kyle gates execution per finding.

## Executive summary

The F0→P1 ladder fixed what it targeted, and every one of its findings still reads as resolved. What it never
had a lens for — and what the 2026-09-14 overnight FULL AUDIT therefore closed "nothing new" on — is a second
layer: the same number rendered in several places with drifting values, one glyph carrying several meanings,
stacked controls that all open the same thing, and a few places where the visual hierarchy contradicts the
product's own stated rule. None of it is a single broken screen; all of it is why the app reads as busier than
its parts. Twenty-two findings below, grouped into semantic mismatches (the substance-bar class), redundancies,
clutter/hierarchy, and doc-level fixes, with a suggested execution order at the end.

The lens that was missing, stated once so it can be added to `AUDIT.md` (see `DOC-1`): *for every number,
badge, glyph or control on a surface, is the same thing shown elsewhere on the same screen or the adjacent one,
and does its visual form match the kind of thing it is?*

---

## Severity key

`AUDIT.md` §7. **High** — blocks or actively misleads a normal workflow, or contradicts a rule the product itself
states. **Medium** — material noise or inconsistency on a load-bearing surface. **Low** — polish, or a doc line.

---

## A. Semantic mismatches — the visual says one thing, the data is another

### `SM-1` The sidebar has a "Research | Plan" mode toggle above a nav that already contains Research and Master Plan — High

**What I observed.** `index.html:29` renders `<div class="modes">` — an accent-filled segmented control reading
"Research | Plan" — directly above the six-item nav. The nav itself contains "🧠 Research" and "🧭 Master Plan".
"Research" therefore names two different things (a mode grouping five views, and one view) within ~60px, and
"Plan" appears twice. The toggle's only behaviour (`home.js:124`) is to mirror whether `state.view === 'plan'`.

**Why this matters.** `DESIGN.md` §4 defines the shell as "a fixed left sidebar … and the six views"; no mode
concept exists in the design. A first-time user's "where am I" reading (§1 item 1) is contradicted by the first
two controls they see. It is the app's own earlier two-mode information architecture surviving under the
six-view one — the definition of drift.

**Location.** `neurosearch/web/index.html:29`; `styles.css:275–277`; `home.js:124`.

**Likely root cause.** Two-mode IA replaced by six views without retiring the mode control.

**Improvement direction.** Remove `.modes` and its handler. Nothing else depends on it (`grep` shows the three
sites above only).

**Acceptance test.** No element with class `modes` in the DOM; the word "Research" appears exactly once in the
sidebar; `test_s44`/`test_s5` pass; `UI_VERSION` bumped.

---

### `SM-2` Sidebar count badges change encoding depending on which page last wrote them — Medium

**What I observed.** `#nPlan` shows "✓" after `home.js:89` runs and "v1" after `plan.js:5` runs; `#nFindings`
shows "16644" (`home.js:86`: approved + suggested) or "16450 +194" (`research.js:802`: approved, then suggested).
Navigating Chats → Findings → Plan changes both badges' *shape*, not just their value, with no change in the data.

**Why this matters.** A badge that re-encodes itself teaches the user it is unreliable. §11: counts support
navigation.

**Location.** `home.js:86,89`; `plan.js:5`; `research.js:802`; `chats.js:209,285` (increments the text directly).

**Improvement direction.** One renderer for each badge, fed by the project payload, called from every load path.
Pick one encoding per badge and keep it: Findings = approved count (suggested count belongs to the Findings page's
own REVIEW/SUGGESTED block, not the nav); Plan = "v1"/blank, or the stale dot alone — not both a checkmark and a
version.

**Acceptance test.** Navigating across all six views leaves every nav badge's text unchanged; a `test_s44`-style
check that only one function writes each `#n*` element.

---

### `SM-3` 🧠 carries four meanings — Medium

**What I observed.** 🧠 is: the Research nav item; the "became a Claim" use-badge on finding rows; the "why"
link on every Chat citation (fourteen per answer in the sample); and the prefix of the "🧠 weak / strong /
unsupported" evidence tag on finding rows. On a finding row, "🧠 weak" reads as "this finding is weak" — it
actually describes the corroboration state of the Claim the finding feeds.

**Why this matters.** §6 Icons: consistent, recognisable iconography; §10: emoji are not permanent iconography.
One glyph, four referents defeats recognition entirely.

**Location.** `index.html` nav; `findings.js` row template (use badges and evidence tag); `chats.js` citation
renderer.

**Improvement direction.** Reserve 🧠 (or its F1 SVG successor) for the Research nav only. Use-badges become
text ("in plan", "cited 2×", "Claim"); the evidence tag names its subject ("Claim: weak"); the citation "why"
link is text, or one text link per answer that opens the existing "why this answer" panel rather than one per
citation.

**Acceptance test.** 🧠 appears once per page; no badge on a finding row is an emoji-only glyph.

---

### `SM-4` Findings' REVIEW block styles the most expensive rebuild as the primary action, inverting the stated rule — High

**What I observed.** Under "816 sources analysed against older inputs", the three options render as: "Rebuild ·
$0 · about 4 h 54 min on Claude Code" (plain), "📦 Rebuild in the background · $15.09" (secondary), "⏩ Rebuild now
· $30.19 on the API" (filled accent primary). On Master Plan, the same three-way choice correctly makes the $0.43
option primary and folds the rest behind "Other ways to rebuild".

**Why this matters.** Rung W3's written rule: the recommended action is "the cheapest option that fully resolves
staleness … never an arbitrary pick", and its regression risk was "a default that steers toward a more expensive
choice". Findings does exactly that. §3 rule 7 (cost is interface state) is satisfied by the labels and undone by
the hierarchy.

**Location.** `findings.js` `loadReviews` (stale-group option buttons).

**Improvement direction.** Apply W3's treatment: the $0 option is the single primary; the two paid options sit
behind one disclosure, same as Plan. Consider whether Plan's banner component should simply be reused here (W3 left
that decision open).

**Acceptance test.** In each REVIEW stale group exactly one `.primary` button exists and it is the $0 option;
both paid options remain reachable within one click with the same labels and prices.

---

### `SM-5` Research shows "2000 important open questions" beside a tab reading "Open questions 200" — Medium

**What I observed.** The stat tile (`research.js:202`, server `important_questions`) reads 2000; the tab label
(`research.js:182`, `openQ.length`) reads 200, because the tab counts the paged client list.

**Why this matters.** Same screen, same concept, 10× apart. §1.7 honest states; §6 stat tile: "a number that
orients".

**Location.** `research.js:182,202`.

**Improvement direction.** Both from the same server count, or the tab drops its number (the tile already has
it).

**Acceptance test.** The two numbers are equal, or only one is shown.

---

### `SM-6` The job console lives inside Sources — Medium

**What I observed.** Between "Add sources" and the filter row, Sources renders an "In progress" panel: the global
spend line ("$0.00 of $50.00 today · $148.04 of $300.00 this month · $0.00/h"), four controls (Pause queue, Pause
background, Cancel queued, Budget…), and per-job rows with progress and a "⋯" menu.

**Why this matters.** §8 scopes dense operational tooling to "Health, Jobs, Settings, diagnostics". On Sources it
sits above the workbench the user came for, and its spend line duplicates the header/sidebar status bar (`RD-3`).

**Location.** `sources.js` `loadJobs` / `#view-sources` static markup.

**Improvement direction.** Collapse to one line on Sources ("2 jobs running · reading 6301 candidate claims") with
the console itself one reveal away or on Settings, where Health already lives. Keep Pause/Cancel reachable in that
reveal — §3 rule 4, common actions stay near the result — but the *budget* control and the spend line belong with
the other budget controls.

**Acceptance test.** Sources' default render above the filter row contains at most one job line and no spend
figure; all four controls reachable within one click.

---

## B. Redundancies — the same thing rendered more than once

### `RD-1` The "research in numbers" novelty block renders on four surfaces — High

**What I observed.** `funCard()` (`utils.js:75`) renders "📊 Your research in numbers / This project in numbers"
with a "🎲 another comparison" reroll on Home (`home.js:18`), in the project sidebar footer (one-line form: "📊
330.3 h read for you — 2.6× every match of a World Cup · $125.59"), on Sources (`home.js:104`), and on Settings.
Tiles include "1.6× Joe Rogan's longest 100 episodes", "4× the Encyclopaedia Britannica", "$639.21 saved by prompt
caching".

**Why this matters.** §6 stat tile: "A tile whose number answers no question the user asked does not belong on the
page." §10: "fake charts/sparklines that answer no real question." The Appendix's "adopt stat tiles" line is being
read as licence for this block; it is not — see `DOC-2`. Four copies of decorative content is the single largest
declutter available.

**Location.** `utils.js:74–93`; `home.js:18,104`; sidebar footer renderer; Settings.

**Improvement direction.** Keep at most one, on Home, reduced to the two or three numbers that orient (hours of
material, sources, findings) without the comparison reroll; remove from sidebar, Sources and Settings. If the
novelty comparisons are wanted, they are one click away on Home, not ambient.

**Acceptance test.** `funCard` is called from one site; no 🎲 control exists; Sources and Settings render no
stat-tile block.

---

### `RD-2` Five money totals in one Home viewport, and they disagree — High

**What I observed.** Home header: "$0.00 today", "$148.04 this month", "$145.44 actual", "$606.19 avoided". Home
fun block: "$148.04 spent", "$639.21 saved by prompt caching". Sources fun block: "$486.22 saved"; Settings fun
block a minute later: "$486.98 saved" (same project, no spend in between). "Avoided" and "saved" are two names for
overlapping things with different values.

**Why this matters.** §3 rule 7 says paid work must not look like free work — it does not say cost should be
wallpaper. Two different "saved" figures on adjacent screens undermine the one strength the earlier audit named
(explicit dollar amounts as the product's core trust behaviour).

**Location.** `statusBar()` (W5), `funCard()`, `/api/stats/fun`, `/api/usage`.

**Improvement direction.** One spend number per scope (global: today + month; project: month), one place each.
"Avoided/saved" is either one figure with one name, shown on Settings' cost section only, or not shown.

**Acceptance test.** Home renders at most three currency values; the same figure is never rendered with two
different values on any two surfaces of the same scope.

---

### `RD-3` The global status bar repeats in the Home header and every project sidebar — Medium

**What I observed.** "● Local AI ready · $0.00 today · $148.04 this month · 50,010 AI calls · 4% local · $145.44
actual · $606.19 avoided" renders in the Home header and again at the foot of every project sidebar, plus the
spend line inside Sources' job console (`SM-6`).

**Why this matters.** W5 made the status bar legible; it did not ask whether every screen needs it. "50,010 AI
calls · 4% local" answers no per-project question.

**Location.** `statusBar()` and its two mount points; `loadJobs`.

**Improvement direction.** Sidebar footer: health dot + today's spend only (the two things that change while you
work). The full breakdown lives on Home and Settings.

**Acceptance test.** Sidebar footer contains at most two status segments.

---

### `RD-4` Master Plan shows two stale warnings and two rebuild controls at once — Medium

**What I observed.** A warn-bordered card "⚠ Plan may be stale v1 — built before revisions were recorded" with
"Rebuild plan · $0.43" and the "Other ways to rebuild" disclosure; then, in the plan header directly below, a pill
"⚠ Research changed — check for updates" and a "Rebuild…" button.

**Why this matters.** §8 Findings: "avoid stacked warning banners above the work" — Plan has the same problem W2
removed from Findings. Two rebuild entry points with different labels for the same job.

**Location.** `plan.js` `renderStaleCard` and the plan-header toolbar.

**Improvement direction.** One stale banner (W3's), one rebuild control. The header keeps version/date and the
exports.

**Acceptance test.** The string "Rebuild" appears in one control on the Plan surface; one ⚠ element above the
plan body.

---

### `RD-5` Research "Do these next" cards print the area name twice — Low

**What I observed.** Card title: "Deal financing · Seller financing evidence may be outdated"; chip beneath: "Deal
financing · Seller financing".

**Location.** `research.js` `renderOverview` next-action card.

**Improvement direction.** Title says what is wrong ("Evidence may be outdated"); the chip says where.

**Acceptance test.** No card renders its area string more than once.

---

### `RD-6` Sources rows carry two controls that open the same drawer — Medium

**What I observed.** "📌 12 findings · evidence for 11 Claims · cited 2×" is a link to `sourceDrawer(id)`; "What
this gave" (`sources.js:162`, filled `.primary`) is a button to `sourceDrawer(id)`.

**Why this matters.** Two controls, one destination, on every one of 889 rows; and see `CL-1` for why the button
being primary is its own problem.

**Improvement direction.** The meaning line is the drawer link (it already says what the drawer will show); the
button goes.

**Acceptance test.** One drawer-opening control per source row.

---

### `RD-7` Findings REVIEW copy repeats and contradicts itself inside single lines — Medium

**What I observed.** "4779 low-value findings — 4779 approved findings at importance ≤ 2 were never used by the
plan, a chat or a Claim; nothing has used them." "(evidence of a strong Claim; 22 approved findings rated 4–5; 15
approved findings rated 4–5)." "1 finding need a quality check — 1776 the same source said twice · 1784 protected ·
320 independently confirmed and kept."

**Why this matters.** §9 voice: plain, concise, specific. The third line's headline count (1) contradicts its own
breakdown (1776/1784/320), and "1 finding need" is ungrammatical, so the line is not trusted.

**Location.** `findings.js` `loadReviews` category summaries; the server's review payload for the counts.

**Improvement direction.** One clause per fact; headline count equals the sum the user can see; singular/plural
handled.

**Acceptance test.** Each REVIEW category line states each count once; headline count matches the visible
breakdown for the quality-check group.

---

## C. Clutter and hierarchy

### `CL-1` A filled primary button on every row — High

**What I observed.** Sources: "What this gave" is `.primary` on every ready row (×889). Findings SUGGESTED:
"✓ Approve" is `.primary` on every card (×100 shown), beneath a `.primary` "Approve 100 shown" and per-source
"✓ Approve all".

**Why this matters.** §6: "One dominant primary action per decision region." A list is one region; 889 primaries
means none. Three tiers of Approve (all-shown / per-source / per-row) for one decision.

**Location.** `sources.js:162`; `findings.js` suggested-block renderer.

**Improvement direction.** Row actions are secondary/tertiary; the one primary on Sources is "Add sources" (or
nothing). On Findings, per-row Approve/Dismiss stay (they are the work) but as plain buttons; bulk approve is one
control at the top, behind the count it affects.

**Acceptance test.** At most one `.primary` visible per surface outside of drawers/dialogs.

---

### `CL-2` Findings renders 100 suggested-finding cards inline above the workbench — High

**What I observed.** After REVIEW, a "SUGGESTED (194)" block renders 100 full cards (dots, title, body, source,
quote, Approve, Dismiss), grouped by source with "Approve all / Dismiss all" per group, then "Showing the 100 most
important of 194. The workbench below pages through the rest — set Show to suggested." The workbench then follows,
with its own "suggested" filter.

**Why this matters.** §3 rule 3: "A large corpus must not become a larger to-do list"; §3 rule 10: "no more than 3
to 5 priority items before the user asks for more." The block duplicates a workbench filter that already exists.

**Location.** `findings.js` suggested block; `#view-findings` static markup.

**Improvement direction.** The SUGGESTED block becomes one REVIEW entry ("194 suggested findings waiting — Review")
that sets the workbench filter to suggested. Bulk approve/dismiss live on the filtered workbench, above the count.

**Acceptance test.** Findings' default render above the workbench contains no finding cards; the REVIEW block has
one suggested entry; the workbench's suggested filter shows the same 194.

---

### `CL-3` Finding rows are five-to-six-line cards, not workbench rows — High

**What I observed.** Each row: importance dots; title; 2–3 line body; badge line (e.g. "📋 plan 💬 2× 🧠 weak ⚠
stale source"); area chip; source line + "quote" link; Dismiss button. `DESIGN.md` §6 Workbench row: "One line:
object title … one line of meaning underneath … at most two badges, and trailing actions grouped at the right.
Fixed row height … Depth goes in a drawer."

**Why this matters.** The re-audit closed C1 on the badge count; the row shape was never changed, so Findings at
16,450 rows is a feed of cards — §8's "a workbench, not a feed" in reverse.

**Location.** `findings.js` row template; `styles.css` finding-row rules.

**Improvement direction.** Two-line row (title; body truncated to one line), ≤2 badges (stale wins, then one use
badge), source as the trailing muted text, quote/area/full body in the existing drawer or an inline expand.

**Acceptance test.** A rendered finding row's height is fixed and equals two text lines plus padding; ≤2 badges;
the body is one line, truncated.

---

### `CL-4` Guilt counts — Medium

**What I observed.** "16450 findings · plan 209 · chat 508 · Claims 542 · never used 15296"; Sources status chip
"🔎 Known, not captured 9360"; REVIEW "4779 low-value findings … nothing has used them".

**Why this matters.** §11 verbatim: "Counts support navigation, not guilt." None of these three is actionable
from where it is shown, and "never used 15296" reads as a failing grade.

**Location.** `findings.js` count line; `sources.js` status chips; `loadReviews`.

**Improvement direction.** Drop "never used" from the count line (the "used anywhere or not" filter already
covers it); "Known, not captured" moves inside the Discover/library reveal it belongs to; the low-value REVIEW
entry keeps its count but leads with the action ("Hide 4779 low-value findings from the workbench").

**Acceptance test.** No count on a default surface names a quantity the user cannot act on from that surface.

---

### `CL-5` Sources and Findings filter stacks — Medium

**What I observed.** Above the Sources workbench, in order: fun block (`RD-1`), Add sources, job console (`SM-6`),
six status chips, "1371 sources" + two CSV exports, seven "Show:" chips (★ Matters and ★ Priority share a glyph),
two unlabeled `<select>`s (length, sort), "Group by origin", Expand all / Collapse all. Findings: three export
buttons, REVIEW, SUGGESTED, search + six unlabeled `<select>`s (state, importance, use, source state, area — the
area select lists 30 areas — sort), count line, Expand/Collapse.

**Why this matters.** §6 inputs: "persistent label when meaning is not obvious"; §3 rule 12: complexity just in
time; §4: the workbench is item 5 of the page hierarchy, and here it starts well below the fold.

**Improvement direction.** Search + one chip row (the status/Show chips merged, one ★) visible; everything else —
length, sort, group, area, use, importance, exports — behind a single "Filters" disclosure with labels. Expand/
Collapse all become one toggle.

**Acceptance test.** Default render above each workbench contains one search input and one chip row; every
`<select>` has a visible label; the first workbench row is within ~400px of the page title at 1440×900.

---

### `CL-6` Emoji still serve as glyphs across the app — Medium

**What I observed.** Nav (💬📚📌🧠🧭⚙︎), theme toggle (☀️/🌙), status chips (✕ ✓ 📚 🔎), Show chips (★ ⚠ 📚 🔬 ∅),
buttons (📦 ⏩ ⬇ 🎲 📊 📎 ⧉ ↗ 📌), row badges (📋 💬 🧠 ⚠), REVIEW options, and 24 Health rows prefixed ✅ ⚠️ 🧪 📈 🧹.

**Why this matters.** §6: "Emoji are content, not iconography." F1 named the eight icon-only controls it was
scoped to and stopped; the rest of the glyph vocabulary is unchanged. `SM-3` is one consequence.

**Improvement direction.** One pass, one rule: an emoji beside a text label is removed unless it distinguishes
siblings in a row (nav qualifies; a button labelled "Rebuild in the background" does not). Status glyphs (✅/⚠️)
become the existing `.status-*` text colour plus a word.

**Acceptance test.** `test_s50` gains a ceiling on emoji-prefixed buttons and badges, lowered in the same commit.

---

## D. Doc-level

### `DOC-1` `AUDIT.md` has no cross-surface duplication check and no encoding-matches-data check — Medium

**What I observed.** Phase 4 §D lists "repeated metadata competing with the actual decision" and "too many
simultaneous calls to action" — both within one surface. Nothing asks whether a number, badge or control is
rendered elsewhere, and nothing asks whether a visual form (bar, dots, pill, checkmark) matches the kind of value
it carries. That is the gap the substance bar passed through and the reason the 2026-09-14 FULL AUDIT closed
"nothing new" over `RD-1`, `RD-2`, `CL-1`–`CL-3`.

**Improvement direction.** Two lines in Phase 4 §C/§D, and one line in Phase 6 (cross-surface): "For each
number, badge, glyph and control: is it shown elsewhere on this or the adjacent surface, and with the same value?
Does its visual form match what it encodes (a bar for a fill-toward-whole, dots for a rating, a pill for a state,
a checkmark for done — never a bar for a score, never a checkmark for a version)?"

---

### `DOC-2` `DESIGN.md`'s Appendix "adopt stat tiles" is read against §6/§10 — Low

**What I observed.** Appendix "Adopt": "Stat tiles: small label, large number, one qualifier." §6: "A tile whose
number answers no question the user asked does not belong on the page." §10: "fake charts/sparklines that answer
no real question." `RD-1` is the result of reading the first without the second.

**Improvement direction.** One clause in the Appendix line: "…for orientation numbers the user acts on — not for
novelty comparisons."

---

### `DOC-3` Two doc-vs-code contradictions — Low

`DESIGN.md` §4 describes the shell as six views; the `.modes` toggle (`SM-1`) is not in the doc, which is the
right outcome once `SM-1` lands. §12 item 10: "`UI_VERSION` bump in all three version sites" — there are four
(`__init__.py`, `pyproject.toml`, `index.html`, `state.js`).

---

## Strengths worth preserving (§11 of `AUDIT.md`)

- The REVIEW entry point's *structure* (reason visible before the action, every priced option reachable) is right;
  `SM-4` and `RD-7` are hierarchy and copy defects inside a sound frame.
- Plan's stale banner (W3) is the correct model for Findings' stale group — reuse it, don't redesign.
- Sources' one-primary-plus-overflow row (W4) is right in principle; `CL-1`/`RD-6` are about *which* control is
  primary and whether it is needed at all.
- Chat's "why this answer" panel and the plain-language Research tiers (09-14 research audit) are unchanged and
  still good.

## Assumptions / cannot verify

- Desktop-width rendering was inferred from CSS and DOM; the browser tool produced only a 606px viewport this
  session. No finding above depends on width.
- Light theme was not re-walked for this pass; every finding is structural (what is rendered), not tonal.

## Suggested execution order

Each line is one bounded rung under `DESIGN-MISSION.md`'s discipline; Kyle admits them by ID.

1. **`RD-1` + `RD-2`** — remove three of four fun blocks, reconcile money figures. Largest visible reduction,
   lowest risk, no behaviour change.
2. **`SM-1` + `SM-2` + `RD-3` + `RD-4`** — sidebar and Plan header: retire the mode toggle, one badge renderer, a
   two-segment sidebar footer, one stale banner on Plan.
3. **`SM-4`** — Findings' $0 option becomes primary, paid options behind W3's disclosure. One small change with
   real cost consequences.
4. **`CL-2` + `CL-3` + `CL-5` + `CL-4` + `RD-6` + `RD-7`** — the Findings-and-Sources workbench rung: suggested
   block becomes a REVIEW entry, two-line rows, one chip row + Filters disclosure, guilt counts and duplicate
   controls removed, REVIEW copy tightened. Largest rung; gated by the W4 bulk-review timing baseline.
5. **`CL-1` + `CL-6` + `SM-3` + `SM-5` + `SM-6` + `RD-5`** — the vocabulary pass: primary-button discipline,
   emoji-as-glyph, 🧠 disambiguation, the 200/2000 count, job console out of Sources, area-name duplication.
6. **`DOC-1` – `DOC-3`** folded into whichever rung first touches the relevant file.
