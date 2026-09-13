# Neuro Search Design Guide

> Read before changing user-facing UI. Feature missions define feature behavior and information architecture. This file defines the shared visual language, interaction rules, and anti-slop constraints for Claude, Codex, and other coding agents. Audit mechanics live in `AUDIT.md`.

## 1. North star

Neuro Search should feel like a well-made research instrument: calm, precise, trustworthy, and dense when density helps.

**Calm at first glance, powerful on demand.** The interface must never dump its entire internal state onto the
screen at once, and it must never make the user excavate a simple answer through menus, tabs, drawers, and modals.
Every layer of disclosure must earn the click it adds. See section 3's "Progressive disclosure without interaction
tax" for the governing rule and interaction-depth heuristic this implies.

The interface should make complex research feel smaller. Within about five seconds, a reasonable first-time user should understand:

1. where they are
2. the current state
3. what matters
4. what to do next
5. what that action will do

Beauty comes from hierarchy, restraint, typography, spacing, coherent states, and purposeful interaction. Decoration is not a substitute for clarity.

Neuro Search is not a generic AI chatbot, marketing site, or dashboard template. The user's project, evidence, decisions, and next actions are the focus. AI stays visually secondary.

## 2. Precedence and audit boundary

When instructions conflict:

1. correctness, safety, data integrity, architectural invariants
2. feature mission and acceptance criteria
3. user task clarity and information architecture
4. this design guide
5. audit findings and cosmetic polish

Do not restructure a feature whose mission explicitly locks its behavior or layout.

`DESIGN.md` is the design source of truth. `AUDIT.md` checks whether the implementation follows it. The audit does not invent a new design language or override feature semantics. This file is `DESIGN.md` — capitalised, matching `CLAUDE.md`, `HANDOFF.md`, `AUDIT.md`. Do not create a second lowercase copy; the working disk is case-insensitive and Git will eventually track two names for one file.

`APPLE-DESIGN-REFERENCES.md` contains first-party Apple design sources and Neuro-specific interpretation for
progressive disclosure, simplicity, interaction depth, interface writing, familiarity, craft, and onboarding. It is
supporting reference material, not a second design system. `DESIGN.md` remains authoritative for Neuro; where the
two conflict, `DESIGN.md` wins until the conflict is deliberately reviewed.

**What "Apple-like" means here, and what it does not.** It means principles: intention, agency, familiarity,
simplicity that is not emptiness, concise contextual language, craft, restrained motion, predictable consequences,
and delight through competence. It does **not** mean copying Apple's visual chrome, recreating macOS/iOS, adding
glass effects or Apple-style marketing language, blindly adopting platform components, making every screen sparse,
hiding functionality, increasing click depth, or replacing Neuro's own tokens. Neuro keeps its own identity and
research-tool density.

## 3. Product UX rules

1. **Meaning before metadata.** Show outcomes and user meaning before engine detail. Internal terminology belongs in advanced inspectors when plain language is available.
2. **Recommended action before advanced controls.** Default order: current state -> what matters -> recommended next action -> alternatives -> supporting detail -> provenance/diagnostics.
3. **Aggregate machine complexity.** Aggregate first, filter second, drill down third. A large corpus must not become a larger to-do list.
4. **Ask only for judgment.** If Neuro can determine a state automatically, it should. Ask the user for real decisions, preferences, applicability, approval, rejection, or risk tolerance.
5. **Outcome labels beat operation labels.** Prefer `Search my existing research`, `Find new sources online`, `Use in project`, `Check for research changes`, `Read deeper`. The rule is semantic, not lexical: avoid a bare operation verb when the user cannot predict its outcome or consequence. `Resolved` can be a perfectly clear state; `Accept 399 as still usable` states an outcome and is valid; bare `Accept`, `Resolve`, `Refresh` or `Run` are inadequate only where their consequence is unclear. This is not a forbidden-word list, and no rung applies it by search-and-replace.
6. **Show consequences before important actions.** Surface what changes, reversibility, Chat/Planner impact, web use, and relevant cost before consequential actions. Confirm only destructive or high-impact actions.
7. **Cost is interface state.** Paid work must not look identical to a free state change. Show `$0`, local time, API estimate, or web-search budget when it affects the decision.
8. **Preserve uncertainty.** Weak, stale, partial, conflicting, or incomplete evidence must not look settled.
9. **Real progress only.** A click acknowledges immediately. Show real counts, stages, queue state, or honest indeterminate progress. Never invent a percentage.
10. **Default views are curated.** Surface no more than 3 to 5 priority items before the user asks for more.

### Progressive disclosure without interaction tax

Neuro currently tends to lay information, controls, metadata, warnings, and secondary detail directly onto the
page all at once. The redesign must reveal information more intentionally — but the opposite failure is equally
bad: hiding useful information behind layers of buttons, menus, tabs, drawers, and modals until a simple task
requires five clicks.

**Governing rule: surface conclusions and actions; collapse explanation and machinery; never collapse the result
itself.**

1. **The primary result should usually require zero clicks.** When Neuro already knows the thing the user came to
   the surface to understand — what matters, current status, recommended next action, an important warning, a
   plan recommendation, a research conclusion, whether something needs attention, whether a job succeeded or
   failed — show it immediately. Do not make the user open a card or drawer merely to discover a result's primary
   meaning.
2. **Supporting explanation should usually be one reveal away.** Why this matters, why Neuro thinks this,
   supporting evidence, what changed, secondary statistics, freshness reasoning, related Claims, source details,
   and consequences of an action belong behind inline expansion, an accordion, a drawer, a popover, or a
   contextual "See why" / "Details" control — chosen by the amount and importance of the information, never
   defaulted to a modal.
3. **Deep machinery may live another level down.** Provenance, evidence lineage, model/debug information, raw
   Claim internals, job diagnostics, research diagnostics, historical state, and large filter/control sets can sit
   two levels deep. A normal user should not have to traverse this layer to complete a normal workflow.
4. **Common actions stay close to the result.** Do not hide a frequently used action inside an overflow menu
   merely to make the page look cleaner. If an action is the likely next step from a result, it stays directly
   available on that result; secondary or rare actions move behind an overflow control, a drawer, or an expanded
   state.
5. **Interaction-depth heuristic.** For ordinary workflows, design toward 0 clicks to understand the result, 1
   click to understand it deeply, and ≤ 2 clicks to perform the normal next action. This is a heuristic, not a
   mechanical test — complexity, safety, expense, or irreversibility can genuinely require more steps — but any
   workflow requiring 3+ sequential interactions should be examined for unnecessary interaction depth. Avoid
   `result -> menu -> modal -> tab -> detail -> action`; prefer `result -> action` or
   `result -> See why -> supporting detail`.
6. **Hide complexity, not usefulness.** Progressive disclosure should hide what is secondary, advanced,
   contextual, diagnostic, infrequently needed, or only relevant after another decision. It must never hide the
   answer, the recommended action, meaningful status, an important warning or cost, a failure state, or whatever
   needs the user's attention.
7. **Reveal mechanisms have different jobs.** Inline disclosure/accordion for supporting content that belongs to
   the current context. A drawer for inspecting an object while preserving where the user was (source, Claim,
   finding, question, watch-out, plan item). A popover for a small contextual explanation (a definition, "why?",
   a freshness or cost explanation). A modal only when the user is making a contained decision that deserves
   interruption — a destructive action, significant spend, permissions, an irreversible or high-impact
   configuration. Do not use a modal as ordinary navigation.
8. **Animation explains state changes; it does not decorate them.** Motion should help the user understand what
   expanded, what collapsed, where new information came from, where an object moved, that an action completed, or
   that state changed — kept short and functional. It must never delay access to information, become required to
   understand state, make a repetitive workflow slower, or exist only to look modern. Respect reduced-motion
   preferences.
9. **Do not solve density solely with cards.** Not every object deserves its own large rounded card. Prefer
   hierarchy, grouping, rows, compact summaries, nested disclosure, drawers, whitespace, typography, dividers, and
   contextual controls before turning every piece of information into another card.
10. **Applying this while implementing an existing audit rung** (not re-auditing): for each surface, ask what must
    be visible immediately; what is useful but secondary and can be revealed; what is advanced machinery that can
    move deeper; what the normal next action is and whether it is directly accessible; whether reducing visual
    density accidentally increased click depth; whether the user can understand the result without interacting;
    whether the explanation is one reveal away; and whether the normal action completes within roughly two
    interactions. If improving one dimension harms the other, prioritize the user's workflow over visual
    cleanliness — a visually sparse interface that makes the user hunt is not an improvement, and a visually dense
    interface that exposes every internal detail at once is not an improvement either. The target is calm at
    first glance, powerful on demand.
11. **Simplicity is not minimalism.** An interface can look visually empty while still making the user hunt
    through layers of controls — that is not simple, only sparse. Neuro may stay dense where density genuinely
    helps understanding, comparison, or work (rule 9 above already says not to solve this with cards). Simplicity
    means removing friction and cognitive burden, never removing useful capability.
12. **Complexity appears just in time, not just in case.** Do not expose configuration, advanced controls,
    internal research machinery, or an additional decision before it is actually useful to the task at hand.
13. **Context should reduce copy, not the other way around.** Layout, state, hierarchy, and surrounding content
    should do most of the explaining, so a label can stay short (`Review`, `Retry`, `Continue`) without becoming
    vague — this is the same semantic test as rule 5 above, applied to brevity: a short label is good only when
    context makes its consequence predictable, not because shorter is inherently better.

## 4. Shell and page hierarchy

**The current shell is the standard.** A fixed left sidebar (`--side`, 250px) carrying project context and the six views — Chats, Sources, Findings, Research, Plan, Settings — plus a main column. Research carries its own sub-panes (Overview, Questions, Areas, Watch-outs, Claims, Tools). Do not restructure the shell, move navigation, or introduce a second navigation model as part of a styling change. A shell change is an information-architecture decision: it requires a mission or an approved audit rung, never a design pass.

Within a page, when applicable:

1. **Context**: project/location and page title
2. **Purpose**: one short sentence explaining the screen's job
3. **Status**: compact orientation summary
4. **Next**: highest-value action or 3 to 5 prioritized items
5. **Workbench**: searchable/filterable operational content
6. **Detail**: drawers, inspectors, provenance, advanced tools

Do not wrap every layer in a card. Use cards for genuinely bounded objects or decisions. Use sections, lists, and tables for continuous work. One level of card nesting is the normal maximum.

## 5. Visual system

These values are frozen. They were validated against WCAG 2.1 AA in both themes on 2026-09-12; the measurement is recorded in HARDENING.md. Do not change a token value without re-running that validation and recording the result.

### Color

Token names extend the set already in `index.html`; no existing name is renamed. Every token has a value in both themes. **No component may hard-code a colour that exists as a token, and no component may define a light-only colour.**

```css
:root{
  --bg:#F6F7F9; --panel:#FFFFFF; --panel2:#F1F3F6; --panel-strong:#E9EDF2;
  --text:#18212B; --muted:#515B66; --text-faint:#65707D;
  --line:#DDE3EA; --line-strong:#7A8EA5;
  --accent:#3156D3; --accent-hover:#2747B8; --accent-soft:#EEF2FF; --accent-text:#FFFFFF;
  --ok:#187A5A; --ok-soft:#EAF7F1;
  --warn:#946200; --warn-soft:#FFF6D8;
  --bad:#B42318; --bad-soft:#FEF0EE;
  --focus:#6184FF;
}
[data-theme=dark]{
  --bg:#0F1115; --panel:#171A21; --panel2:#1D212B; --panel-strong:#232834;
  --text:#E8E8EA; --muted:#9AA3B2; --text-faint:#828B9A;
  --line:#262B36; --line-strong:#5E6B86;
  --accent:#5F88FF; --accent-hover:#7D9DFF; --accent-soft:#141C34; --accent-text:#0F1115;
  --ok:#3ECF8E; --ok-soft:#143425;
  --warn:#F5B642; --warn-soft:#342814;
  --bad:#FF6B6B; --bad-soft:#341414;
  --focus:#6E8EFF;
}
```

Rules that come with those values:

- **Three text tiers, all readable.** `--text` for content, `--muted` for supporting information, `--text-faint` for de-emphasised but still legible detail (timestamps, ids). All three meet AA on `--bg`, `--panel` and `--panel2`. There is no fourth, lighter tier: if text is not worth reading it should not be rendered.
- **Two border roles.** `--line` separates and bounds (card edges, dividers, table rules); it is deliberately faint and carries no contrast requirement because content, not the line, identifies the region. `--line-strong` is the boundary of an interactive control — input, select, textarea, outlined button, checkbox — and meets 3:1, because there the border is the only thing identifying the control.
- **Fill labels flip by theme.** In light, filled accent and danger buttons carry white (`--accent-text`). In dark, the accent is bright, so `--accent-text` is near-black. Never hard-code `#fff` on a fill.
- **Focus is a two-part ring**, so it stays visible on a surface *and* on a coloured fill: `box-shadow:0 0 0 2px var(--panel),0 0 0 4px var(--focus)`. A single-colour ring fails on a primary button.
- Status colour is text-first: `--ok/--warn/--bad` as the text or glyph colour on `--panel`, or as text on the matching `-soft` background. Never a saturated fill with white text for status.
- No decorative gradients. Do not tint every card. Colour is never the only carrier of meaning.

### Typography

Native system typography; no font dependency for personality.

```css
:root{
  --font-sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,sans-serif;
  --font-mono:"SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;
  --text-xs:12px; --text-sm:13px; --text-base:15px; --text-lg:17px; --text-xl:20px; --text-2xl:26px;
}
```

- page title: 26px / 1.2 / 650
- section title: 20px / 1.25 / 650
- object title: 15 to 17px / 1.35 / 600
- body: 15px / 1.5 / 400
- controls: 14px / 1 / 550 to 600
- metadata: 13px / 1.4
- compact technical labels: 12px minimum

Six sizes, and 12px is the floor. Roboto appears in the stack only as the Android fallback; do not select it deliberately, and do not add Inter or Arial. Sentence case by default. Monospace only for genuinely technical content. Explanatory copy around 65 to 75 characters per line.

### Spacing, radius, elevation, motion

```css
:root{
  --space-1:4px; --space-2:8px; --space-3:12px; --space-4:16px;
  --space-6:24px; --space-8:32px; --space-12:48px; --space-16:64px;
  --radius-sm:6px; --radius-md:10px; --radius-lg:14px; --radius-pill:999px;
  --shadow-popover:0 10px 28px rgba(24,33,43,.12),0 2px 8px rgba(24,33,43,.08);
  --motion-fast:100ms; --motion-normal:160ms; --motion-slow:220ms;
  --ease-standard:cubic-bezier(.2,.8,.2,1);
}
```

Four radii, and circles (`50%`) only for avatars and dots. Prefer whitespace before another border. Card padding 16 to 20px; major sections 24 to 32px apart. Default surfaces use a 1px border, not a shadow; shadows are for floating layers only. Pills are for actual tags, filters, or compact statuses.

Motion communicates state and continuity only. No decorative bounce, spring, or long entrance animation. Respect `prefers-reduced-motion`.

### The inline-style rule

Most of this UI's styling does not live in the stylesheet. At the 2026-09-12 baseline `index.html` carried **432 inline `style="…"` attributes against 259 lines of CSS**, plus 16 distinct font sizes and 11 distinct radii — which is why a token can be correct and the screen still inconsistent. The rule is a ratchet, not a rewrite:

1. New or rewritten UI adds **no** inline `style` attribute and no literal colour, size, radius or duration that a token already names.
2. When you touch a surface, retire the inline styles on the part you touched into a class. Do not open a separate cleanup pass.
3. `tests/test_s50_design_drift.py` holds the measured ceiling. It fails if any count rises. It is never a target to hit, only a line not to cross.
4. One-off geometry that no token can express (a specific grid width, an aspect ratio) may stay inline; it must not carry colour, font size, radius or duration.

## 6. Component rules

- **Buttons:** primary, secondary, tertiary, danger. One dominant primary action per decision region. Desktop height 36px; touch target at least 44px. Icons support labels, not replace ambiguous labels. Actions acknowledge immediately and show truthful pending state.
- **Inputs/filters:** 36px desktop height; `--line-strong` border; persistent label when meaning is not obvious; placeholder is not a label; visible `:focus-visible` using the two-part ring; keep filters near the workbench they affect.
- **Statuses/badges:** text first, colour second. Do not pill every field. No more than two visible badges on a normal row.
- **Stat tile.** The unit for a number that orients rather than a number that decorates. Label (13px, `--muted`), value (20 to 26px, 650, `--text`), and at most one trailing qualifier — a delta, a unit, or four words of context. Optional sparkline, never a chart with axes. No icon unless it distinguishes tiles in a row. A tile whose number answers no question the user asked does not belong on the page.
- **Workbench row.** The unit for Sources, Findings, Claims and any list that reaches thousands. One line: object title (15px, 600, truncating), one line of meaning underneath (13px, `--muted`) — what this gave the project, not its pipeline stage — at most two badges, and trailing actions grouped at the right. Fixed row height; the row does not grow to fit its content. Depth goes in a drawer, never by expanding the row into a card.
- **Lists/tables:** align comparable data, keep rows compact, group trailing actions, and paginate/window/progressively reveal large sets.
- **Drawers:** depth without losing workbench position. Order: identity -> why it matters -> current state -> primary action -> evidence/detail -> provenance/history. Normally 520 to 640px wide on desktop, max 90vw.
- **Empty states:** explain what is absent, whether that is good/neutral/unfinished, and the next useful action if one exists.

### Icons

The rule is consistent, recognisable, accessible iconography — not an icon system. Use the smallest zero-dependency approach the single-file app allows: an inline SVG `<symbol>` block holding only the glyphs controls actually need, one stroke weight, `stroke:currentColor`, referenced as `<svg class="ic"><use href="#ic-refresh"></use></svg>`. Add a glyph when a control needs one, never a library in advance. No icon font, no icon package, no remote asset: the single-file constraint and the frontend gates both still apply. Every icon-only control carries an `aria-label` and a `title`.

Emoji are content, not iconography. They are fine inside project names, briefs, chat text and anything the user typed. They are not control glyphs: eight buttons still use one at the baseline; ladder rung F1 gives each a named glyph and an accessible name, and nothing more.

## 7. Responsive behaviour and accessibility

Desktop-first, usable at a narrow width. Stack controls before shrinking labels into ambiguity. Preserve state and primary action before secondary metadata. Test material changes around 390px, 768px, and wide desktop. Mobile parity is not a goal; mobile *legibility* is.

Meet WCAG AA contrast — the token values above already do, so achieving it means using them. All normal actions keyboard reachable with a visible two-part focus ring. Never encode status only by colour or icon. Icon-only controls require accessible names. Errors explain both the problem and the fix. Dialogs trap and restore focus and close on Escape.

### Refresh, polling and live state

The app polls. Polling must not make the page flicker or lose the user's place:

- A poll never replaces rendered content with a spinner or a skeleton. Skeletons appear on first paint only.
- A re-render preserves scroll position, open drawers, expanded rows, selections, and unsent input.
- Prefer a quiet freshness line (`updated 8s ago`) to a blink, a flash, or a moving spinner.
- If a poll fails, say the view is stale; do not silently show old numbers as current, and do not blank them.
- A read that renders a status must not start work: no job, no model call, no provider probe.

## 8. App-specific direction

### Research

A control center, not an evidence database console. Mental model: **Overview -> Questions -> Knowledge -> Advanced**.

- Overview: what should I pay attention to next?
- Questions: what do we still need to figure out?
- Knowledge: what do we understand by meaningful area?
- Advanced: Claims, provenance, diagnostics, engine detail

Claims power the product. Claims are not the product.

### Sources

Lead with what a source gave the project, not only ingestion state. Prefer value, use, freshness, and project relevance. Drawer for the source's full story.

### Findings

A workbench, not a feed. Large sets require search, filters, sorting, paging, use badges, and clear review semantics. Avoid stacked warning banners above the work.

### Chat

Conversational, not a research-report template. Citations and evidence available but visually secondary until needed. No decorative AI chrome.

### Master Plan

Action before analysis. `Start here` and `This week` stay above deeper analysis, options, evidence, and history.

### Health, Jobs, Settings, diagnostics

Operational tools may be denser and more technical. Factual state, tables, filters, and clear controls over decorative cards.

### Project creation — the canonical progressive-disclosure exemplar

This flow is the clearest test of section 3's progressive-disclosure rules and the reference other surfaces should
be judged against, not a one-off exception.

Ask for the minimum needed to begin — conceptually close to project name, goal, create — and start useful work
immediately. This is a direction, not a frozen copy/layout spec; a rung that ships this still owns its own exact
wording and field set.

Behind that simple surface Neuro may do substantial work: checking the existing library, finding reusable research,
finding related projects or sources, ranking material, identifying gaps, preparing the project. None of that
orchestration needs to be exposed merely because it exists — show human-readable progress and results as they
become useful, in the product's own language, never internal job names.

The desired feeling: **the product prepared the room before the user walked into it.** That is a behavioral
standard for what the flow accomplishes, not a request for decorative animation.

## 9. Content and microcopy

Voice: plain, concise, specific, non-performative.

Prefer `3 sources still need review`, `This may change your financing plan`, `Search my existing research`, `No major evidence problems need your attention`.

Avoid `Unlock powerful insights`, `AI-powered intelligence`, `Supercharge your research`, `Magic`, generic praise such as `Great question`, and engineering labels when a user outcome can be named.

Project creation *feeling* surprisingly capable — because real, substantial work happens smoothly with
little burden on the user — is a legitimate experience goal (see section 8's Project creation direction); it is
never license to literally label a feature "magic," "magical," or "AI magic" in the interface.

Use real product content while designing and testing. No lorem ipsum, generic fake analytics, or decorative AI-generated imagery in functional UI.

## 10. Anti-vibe-coded rules

Do not introduce:

- purple-blue gradients
- decorative beige-on-beige card stacks
- glassmorphism, frosted panels, glow, or neon borders
- excessive rounded rectangles or pill-shaped everything
- cards inside cards inside cards
- oversized hero typography inside functional screens
- giant whitespace that destroys useful density
- generic 3-column feature-card layouts when a list/workbench fits
- emoji as permanent primary iconography
- mixed icon styles
- generated abstract AI art or stock decoration
- fake charts/sparklines that answer no real question
- excessive status chips or a different accent color for every feature
- one-off CSS values that bypass tokens
- gratuitous animation
- center-aligned body copy in normal app screens
- ambiguous icon-only actions
- tooltips as the only explanation for a primary control
- anthropomorphic `Neuro is thinking` copy when a real system state exists

Do not make the interface interesting by making it less predictable. Distinctiveness should come from disciplined density, coherent typography, strong hierarchy, precise language, useful state design, and Neuro Search's real research model.

## 11. State and scale

Design explicit states when applicable: empty, loading, partial/in progress, current, stale, uncertain, failed but recoverable, blocked on user action, unavailable, and large-data.

`Nothing exists`, `nothing matched`, `still calculating`, `failed`, and `not available` must never look like the same blank box.

Evaluate against real shapes: new project, 1 source, 20 sources, hundreds/thousands of sources, thousands of Findings, thousands of Claims, simultaneous background jobs.

Summaries should come from compact API state, not giant payloads. Default views show priority rather than chronology unless chronology is the job. Counts support navigation, not guilt.

## 12. Agent rules and completion check

When changing UI:

1. Read the feature mission and current implementation first.
2. Reuse tokens and existing patterns before creating new ones.
3. Make new primitives reusable and token-based.
4. Keep behavioral semantics testable in application logic, not only frontend JavaScript.
5. Evaluate with real content and realistic large-data states.
6. Preserve architecture, data meaning, cost controls, and hardened behavior unless the mission explicitly changes them.
7. Do not rename or merge backend concepts solely for visual consistency.
8. Do not add dependencies only to make the UI feel more designed.
9. Treat a global token change as a product-wide design decision: re-run the contrast validation and record it.
10. Every change to `index.html` ships with a `UI_VERSION` bump in all three version sites, or open tabs cannot tell they are stale.

Before the audit runs, verify:

- a first-time user understands the screen's purpose within about five seconds
- the most important thing is visually obvious
- each decision region has at most one dominant primary action
- visible actions communicate their outcomes
- cost, web access, destructive consequences, and reversibility are visible where they matter
- clicks acknowledge immediately
- realistic large-data states remain usable
- advanced detail is reachable without overwhelming the default view
- **both themes render correctly** — light and dark, every state
- the anti-vibe-coded list is respected
- styling comes from the shared system, not local invention
- `test_s44_frontend_integrity.py`, `test_s5_ui_syntax.py` and `test_s50_design_drift.py` pass

## 13. Maintenance

This file should earn every line. Do not add speculative rules for mistakes that have never occurred.

Change it when a design mistake repeats, a reusable primitive is intentionally introduced, the audit repeatedly finds the same systemic drift, or real product usage proves an existing rule wrong. Prefer replacing an obsolete rule over stacking exceptions on top of it.

---

## Appendix — the INSPIRATION folder, adopt and reject

Twenty-five references collected 2026-09-12: nine marketing pages, fifteen product screens, one carousel. They settle the visual language. They do not settle the state language — none of them handle thousands of objects, stale versus current evidence, paid versus free actions, or partial and failed background work. Those come from Neuro's own model and from §11 above.

**Adopt.** Off-white canvas with white surfaces and hairline borders, shadow only on floating layers. One accent, used for selection and a single primary action. Soft-tinted status pills with dark text rather than saturated fills — the Healthy/Degraded/Critical row in the OrchestrateIQ references is the model for Findings and Claims status. Stat tiles: small label, large number, one qualifier. Dense aligned tables with a filter-chip row and a search box directly above them. A compact left rail, a contextual column, a wide workbench, and a right-hand inspector for the selected object. Two-tone headline emphasis (dark phrase, grey phrase) for page purpose lines only. A calm chat surface with suggested actions as small cards and the composer anchored at the bottom.

The strongest single reference is the meeting-analysis screen (Salach.ai): transcript on the left with time codes, extracted items on the right, each tagged and marked handled or not, with the AI analysis block clearly secondary. That is the closest existing analogue to a Neuro source drawer showing findings and Claims.

**Reject, deliberately — these appear in the references and violate §10.** Purple-blue gradients and glowing AI orbs. Glassmorphism over photography. Decorative illustration and hero photography inside functional screens. Emoji-forward greetings (`Hi, there 👋`) and `we'll handle the rest` copy. A different tinted colour per category. An implementer who opens the folder without this note will see the gradients first; they are not the part to copy.
