# Design Implementation Ladder

Derived from `docs/design-audit/2026-09-13-b85c222/audit.md`. This is a sequence, not an authorization: per
`DESIGN-MISSION.md`, D2 rungs are admitted only from D1 evidence, one bounded surface at a time, and each still
needs Foundation §34 UI scope or a `DEVELOPMENT-OPERATING-SYSTEM.md` §13 override before implementation begins.
Nothing in this document has been built.

Four groups, in the order they should be attempted: system foundations, then workflow/IA changes, then component
consistency, then polish. Do not start a workflow/IA rung before its dependent foundation rung has landed — the
audit's closure pass found that vocabulary and token fixes converge on the same surfaces, so building the workflow
change first would mean redoing its styling and copy a second time.

---

## System foundations

### `Rung F1` — Land the frozen design tokens and reduce inline-style drift

**Problem being solved:** `H-7`. Two status colors (`--ok`, `--warn`) fail WCAG AA today; 430 inline `style=`
attributes, 28+3 stray color literals, 16 font sizes and 11 radii mean every other surface's styling was authored
locally rather than through a shared system.

**Affected surfaces:** `neurosearch/web/index.html` globally — this rung touches the token block and as many inline
sites as can be retired in one bounded pass, not necessarily all 430.

**Proposed system-level change:** replace the live `:root`/`[data-theme=dark]` token blocks with the frozen,
AA-validated set recorded in `HARDENING.md` (D0). Retire inline styling surface-by-surface in the same pass where
practical, lowering the `tests/test_s50_design_drift.py` ceilings in the same commit per its own ratchet rule.

**Why this rung precedes the next:** every workflow/IA and component rung below (banners, buttons, badges) depends
on a correct, complete token set existing first — building a consolidated banner component against the current
drifted styles would mean re-styling it again once the tokens land.

**Explicit non-goals:** this rung does not redesign any surface's layout, copy, or information architecture — token
and literal-style substitution only. It does not attempt to retire all 430 inline styles in one pass; partial
progress that lowers the ratchet is the expected outcome, not full elimination.

**Implementation seam / likely modules:** `neurosearch/web/index.html` `<style>` block (token definitions), then
the highest-inline-style surfaces identified in `raw.md` Phase 4/5 (Sources, Findings row markup).

**Acceptance test:** `--ok`/`--warn` measure ≥4.5:1 on `--panel` in both themes; `tests/test_s50_design_drift.py`
ceilings for inline styles and color literals decrease from their current values (430 / 28 / 3) in the same commit.

**Regression risks:** a token rename or value shift that isn't reflected everywhere it's read could produce a
visually broken surface that the drift ratchet wouldn't catch (it counts literals and sprawl, not correctness).
Visual spot-check in both themes is required, not just the automated gate.

**Tests / runtime checks required:** `tests/test_s50_design_drift.py`, `tests/test_s44_frontend_integrity.py`,
`tests/test_s5_ui_syntax.py`, `UI_VERSION` bump in all three version sites, click-acknowledgement and sustained-busy
state spot-check (`AUDIT.md` §4.3 protected contracts).

**Visual re-audit required:** yes — a rendered-UI check in both themes before this rung is considered done; computed
contrast alone (D0's method) is not sufficient once the values are actually live.

**Effort:** L **Risk:** Medium — touches every surface indirectly through the token block, but the mechanism
(substitution against a pre-validated table) is low-judgment.

---

### `Rung F2` — Shared loading / empty / failure list-state primitive

**Problem being solved:** `H-2` and RC-E. Findings renders a blank content area for 5–8 seconds with no loading
indicator; this is likely present on any large list, unmeasured elsewhere.

**Affected surfaces:** Findings first (highest severity, largest list); Sources and Chat history checked for the
same gap.

**Proposed system-level change:** one shared component (skeleton rows or a labeled spinner, consistently styled via
F1's tokens) used by every surface that renders a list from a fetch, replacing whatever ad hoc handling (or absence
of handling) each surface currently has between navigation and data arrival.

**Why this rung precedes the next:** the workflow/IA rungs below (Findings banner consolidation, Sources row
reduction) change what renders once data arrives; this rung fixes what renders before data arrives, and doing it
first means the workflow rungs don't have to separately solve "what does this look like while loading."

**Explicit non-goals:** does not address polling/refresh behavior after initial load (unmeasured, flagged in the
audit as needing timing instrumentation) — that is a separate, not-yet-scoped concern.

**Implementation seam / likely modules:** the fetch/render path for Findings, Sources and Chat history lists in
`neurosearch/web/index.html`'s JS.

**Acceptance test:** on a fresh navigation to a large project's Findings, a loading indicator is visible within one
frame and remains until real content or a real, visually distinct empty state replaces it.

**Regression risks:** a loading state that never clears (a fetch-completion signal that's wired wrong) would be
worse than the current blank period because it actively asserts "still working" — needs explicit timeout/error
handling, not just a happy-path skeleton.

**Tests / runtime checks required:** request-path purity check (a read-only surface must not start a job as a side
effect of showing a loading state), manual timing verification on the largest available project.

**Visual re-audit required:** yes, on Findings specifically, since `H-2`'s evidence was time-based (observed, not
timed precisely).

**Effort:** M **Risk:** Low — additive UI state, no change to existing successful-load rendering.

---

## Workflow / information-architecture changes

### `Rung W1` — One reprocessing action/state vocabulary and disclosure rule

**Problem being solved:** `H-5` (RC-B). Rebuild/Re-analyse/Re-rank/Suggest/Re-check are worded, priced, and styled
inconsistently across Findings, Plan, Sources and Chat.

**Affected surfaces:** Findings (Rebuild banner), Master Plan (Re-analyse banner), Sources ("Suggest findings"),
Chat ("also search the web").

**Proposed system-level change:** define one action/state contract — a fixed verb set, a fixed rule for when a cost
or consequence must be shown inline (any action that spends money or changes durable state discloses it, full stop),
and one shared button treatment per role (primary / secondary / destructive / paid) built on F1's tokens — then
apply it to all four surfaces in the same rung, per `AUDIT.md` §9's own worked example for this exact problem.

**Why this rung precedes the next:** `H-3` and `H-6` (banner consolidation on Findings and Plan) both depend on
having a settled vocabulary and disclosure rule to consolidate around — building the merged banner first would mean
choosing ad hoc wording that this rung would immediately have to revisit.

**Explicit non-goals:** does not change what any action actually does or what it costs — wording, disclosure and
styling only. Does not yet merge Findings' and Plan's banners into one component (that's `W2`).

**Implementation seam / likely modules:** the action-button markup on Findings/Plan/Sources/Chat, plus a shared
button/badge component in the CSS token layer landed by F1.

**Acceptance test:** given any reprocessing action's label alone, a person who has seen it on one surface can
predict whether it costs money and roughly what it does on another surface, without having used that surface
before. Sources' "Suggest findings" and Chat's "also search the web" both gain cost/consequence disclosure they
currently lack entirely.

**Regression risks:** relabeling an action a user already has muscle memory for (e.g., "Rebuild") risks momentary
confusion; mitigate by keeping the closest-matching existing term where it already fits the new contract rather than
renaming for its own sake.

**Tests / runtime checks required:** `tests/test_s44_frontend_integrity.py` (inline handlers still name declared
functions after any markup change), manual verification that every priced action still fires the correct
provider/cost path unchanged.

**Visual re-audit required:** yes, across all four affected surfaces together, since consistency is the acceptance
criterion.

**Effort:** M **Risk:** Medium — copy and disclosure changes across four surfaces at once; sequencing all four in
one rung is deliberate (per the audit's root-cause note) but raises the blast radius of a single rung.

---

### `Rung W2` — Consolidate Findings' three stacked banners into one Review entry point

**Problem being solved:** `H-3`. Stale-sources, "nothing waiting," and "4,805 never used" render as three
independently-worded banners stacked above every finding.

**Affected surfaces:** Findings.

**Proposed system-level change:** one Review entry point that explains why each item needs attention, separates
system-detectable cleanup (stale, unused) from user judgment (curation), and exposes no bulk destructive action
until the affected set is understood — using `W1`'s settled vocabulary and disclosure rule for every action inside
it.

**Why this rung precedes the next:** `H-6` (Plan's banner) is very likely the same underlying "stale" state
presented a second way; this rung should land and be validated on Findings first, then `W3` decides whether Plan's
banner merges into the same component or stays separate with shared styling only.

**Explicit non-goals:** does not change the underlying stale-detection logic, pricing, or what triggers a rebuild —
presentation and consolidation only. Does not touch the finding rows themselves (that's `C1`).

**Implementation seam / likely modules:** the Findings banner-rendering block in `neurosearch/web/index.html`.

**Acceptance test:** a returning user sees at most one system-prompted review entry point above the finding list;
the "822 stale sources," "nothing waiting," and "4,805 never used" states are reachable from within it rather than
each claiming independent top-of-page space.

**Regression risks:** merging three banners into one could bury a state a user currently notices immediately (e.g.,
the priced stale-rebuild options) — the acceptance test should specifically confirm pricing visibility is not
regressed, per the "strengths worth preserving" list in the audit.

**Tests / runtime checks required:** `tests/test_s50_design_drift.py`, manual check that all four previously-visible
priced options remain reachable and priced identically.

**Visual re-audit required:** yes.

**Effort:** M **Risk:** Medium — this is the rung most likely to accidentally hide a currently-visible priced
action; needs deliberate acceptance-test verification, not just a visual pass.

---

### `Rung W3` — Master Plan: default to one recommended stale-remediation action

**Problem being solved:** `H-6`. Four priced/unpriced options render as co-equal choices before the plan itself is
visible.

**Affected surfaces:** Master Plan.

**Proposed system-level change:** default to a single recommended action (matching Research's own "one primary,
others plain" hierarchy, a strength named in the audit), with the other three reachable but visually subordinate;
decide in this rung whether the underlying banner shares a component with Findings' (`W2`) or stays visually
separate.

**Why this rung precedes the next:** row/badge-level component consistency (`C1`, `C2`) is lower-leverage than
fixing the two banner surfaces first, since the banners are what a user sees before anything else on both pages.

**Explicit non-goals:** does not change which remediation options exist or their prices — ranking and default
presentation only.

**Implementation seam / likely modules:** the Master Plan stale-banner block in `neurosearch/web/index.html`.

**Acceptance test:** the plan is visible above the fold with at most one prominent stale-remediation action shown by
default; the remaining three are one interaction away, not hidden entirely.

**Regression risks:** picking the wrong default recommended action could push a user toward a more expensive choice
than they'd have picked themselves — the "recommended" logic needs an explicit, defensible rule (e.g., cheapest
option that fully resolves staleness), not an arbitrary pick.

**Tests / runtime checks required:** manual verification that all four options remain fully functional and priced
identically after the rung.

**Visual re-audit required:** yes.

**Effort:** S **Risk:** Low — smaller surface than `W2`, same pattern already validated there.

---

### `Rung W4` — Sources: progressive disclosure for row actions

**Problem being solved:** `H-4`. Six actions per row, including an unshielded destructive one, at 1,348 rows.

**Affected surfaces:** Sources.

**Proposed system-level change:** surface one primary action per row by task context; move secondary actions,
"Delete everywhere" especially, behind an overflow control with confirmation scaled to irreversibility (cross-
project delete gets a stronger confirmation than "Remove from project").

**Why this rung precedes the next:** this is the highest-severity remaining workflow rung after the two banner
surfaces; it should land before `C1` (badge/pill consistency) since it changes row structure, and a consistency pass
on soon-to-be-restructured rows would be wasted work.

**Explicit non-goals:** does not change what any action does, only its default visibility and confirmation weight.
Does not address the add-source panel's placement (`P1`, polish) in this rung.

**Implementation seam / likely modules:** the source-row action markup in `neurosearch/web/index.html`.

**Acceptance test:** a source row exposes one primary action by default; "Delete everywhere" requires one
additional deliberate step and is never adjacent, at equal visual weight, to "Remove from project."

**Regression risks:** hiding actions behind an overflow could slow down a power user's bulk-review workflow if not
given a shortcut; the interaction-pass audit (not yet run) should validate this before considering the rung closed.

**Tests / runtime checks required:** `tests/test_s44_frontend_integrity.py`, `tests/test_s50_design_drift.py`,
manual verification every action still functions once relocated.

**Visual re-audit required:** yes, plus an interaction-pass check once the audit-instance walk is available.

**Effort:** M **Risk:** Medium — destructive-action placement changes carry real consequence if done wrong; this
rung should not ship without the deferred interaction-pass validation.

---

### `Rung W5` — Home and status-line reorientation toward attention, not totals

**Problem being solved:** `H-1`, `M-1`, `M-2`, `M-3` (RC-A, RC-F). No attention signal on project cards; the stat
block outweighs project titles; status is an unscannable sentence; card-click affordance is inconsistent.

**Affected surfaces:** Home, Chat sidebar footer (shares the status-line component).

**Proposed system-level change:** a status component with independently legible parts (health indicator, spend),
ordered by what needs noticing first, replacing the single narrated sentence in both locations; project cards gain
a last-activity or attention signal and de-emphasized stat block relative to project titles; the whole card becomes
a consistent click target.

**Why this rung precedes the next:** this is the last of the high-severity findings and the most speculative in
scope (it touches Home's whole layout) — sequenced after the three more surgical rungs above so the token and
vocabulary systems are already in place to build it on.

**Explicit non-goals:** does not add cross-project search, sort or archive to Home (raised as a scale risk in
`raw.md` Phase 1 but not evidenced as a current problem at 13 projects) — that is a separate, larger IA question
outside this ladder's scope.

**Implementation seam / likely modules:** Home's project-card markup and the shared status-line component (also
used by Chat's sidebar footer).

**Acceptance test:** a user can state whether local AI is healthy and roughly what they've spent by glancing at
Home for under a second; a 0-source test project and an 876-source real project are visually distinguishable;
clicking anywhere on a card body navigates.

**Regression risks:** none identified beyond standard layout-change risk; lowest-dependency rung in this group since
it doesn't touch pricing or destructive actions.

**Tests / runtime checks required:** `tests/test_s44_frontend_integrity.py`, `tests/test_s50_design_drift.py`.

**Visual re-audit required:** yes.

**Effort:** M **Risk:** Low.

---

## Component-consistency changes

### `Rung C1` — Unified badge/pill and banner component

**Problem being solved:** the visual-drift portion of `H-3`/`H-5`/`H-6`/`M-4`/`M-6` — pills and banners currently
share styling across four unrelated roles (status, filter, chip-input, version tag) with no visual distinction, and
Findings rows carry 4–5 badges against a 2-badge target.

**Affected surfaces:** Findings (row badges, sidebar count badge), Sources (filter chips), Research/Plan (chip
answers), sidebar (version tag).

**Proposed system-level change:** one badge/pill primitive with distinct visual treatments per role (status vs.
filter vs. input vs. metadata), built on `F1`'s tokens; reduce Findings' per-row badge count toward the two-badge
target by folding lower-value badges into the row's existing meaning-line text.

**Why this rung precedes the next:** this is lower-severity than the workflow rungs above but higher-leverage than
pure polish, since it's referenced by multiple High findings as a contributing (not root) cause.

**Explicit non-goals:** does not change which information each badge conveys, only how many render and how visually
distinct the roles are.

**Implementation seam / likely modules:** shared badge/pill CSS classes, Findings row markup.

**Acceptance test:** the four badge roles (status, filter, input, metadata) are visually distinguishable from each
other; Findings rows render at most two badges by default with the rest available on expansion or in the meaning
line.

**Regression risks:** removing a badge a power user currently scans for (e.g., "weak") could reduce information
density that raw.md names as a strength — verify against the strengths list before removing any badge outright.

**Tests / runtime checks required:** `tests/test_s50_design_drift.py`.

**Visual re-audit required:** yes.

**Effort:** M **Risk:** Low.

---

## Polish

### `Rung P1` — Small, independent surface fixes

**Problem being solved:** `L-1` through `L-5`, `M-7`, `M-9`, `M-10`, `M-11` — a set of small, uncorrelated findings
that don't require a shared system change.

**Affected surfaces:** Sources (thumbnail fallback, export placement, add-panel real estate), Chat (menu-item
weight, sidebar grouping), Master Plan (footer tab placement), sidebar (version tag size), Settings (brief textarea
height, Save consequence text), sidebar mode toggle (Research/Plan affordance mismatch).

**Proposed system-level change:** none — each item is fixed independently, in whichever surface's other rung is
already touching that file, to avoid a standalone low-value commit.

**Why this rung comes last:** none of these findings block understanding of a core workflow; `AUDIT.md` §10
explicitly warns against starting with polish when a structural problem makes the screen confusing, and several
structural problems precede this list.

**Explicit non-goals:** no new shared component is introduced for this rung; if two items turn out to need the same
fix (e.g., Chat menu weight and any other destructive/non-destructive adjacency), fold that into `W1`'s button
treatment instead of solving it twice.

**Implementation seam / likely modules:** scattered — Sources row/panel markup, Chat header menu, Master Plan
footer, sidebar version tag, Settings textarea, sidebar mode toggle.

**Acceptance test:** each item's specific defect (missing fallback glyph, misplaced export, equal-weight delete,
buried footer nav, tiny version tag, truncated brief, missing consequence text, mismatched toggle affordance) is
independently verifiable as fixed; no shared acceptance test across the group.

**Regression risks:** low individually; the main risk is scope creep if "polish while I'm in the file" expands
beyond the specific items listed here.

**Tests / runtime checks required:** `tests/test_s44_frontend_integrity.py`, `tests/test_s50_design_drift.py` where
applicable per item.

**Visual re-audit required:** spot-check only, not a full pass.

**Effort:** S (aggregate; each item is trivial individually) **Risk:** Low.

---

## Sequencing summary

F1 → F2 → W1 → W2 → W3 → W4 → W5 → C1 → P1, with the note that F1 and F2 could run in parallel (both are additive,
non-conflicting foundation work) if two implementers are available, but W1 must not start until F1 has landed, and
W2/W3 must not start until W1 has landed, per the closure-pass finding that vocabulary and token fixes converge on
the same surfaces. Every rung requires a RE-AUDIT (`AUDIT.md` "RE-AUDIT" mode) of its affected surfaces before the
next rung in the same group begins; a cross-cutting RE-AUDIT across all affected surfaces is due after `W5`, before
`C1` starts, to confirm no unpropagated consequence was introduced across the five preceding workflow rungs.
