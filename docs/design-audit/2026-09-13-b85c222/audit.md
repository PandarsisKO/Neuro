# Design Audit

Neuro Search, FULL AUDIT (read-only half). Version `0.63.43`, HEAD `b85c222`, audited 2026-09-13. Synthesized from
`docs/design-audit/2026-09-13-b85c222/raw.md`. No product code was changed producing this file.

## Executive summary

**What the product does well.** Research is the strongest surface in the app: it states purpose, ranks work by
consequence of leaving it alone, and prices every action at $0 or names the cost — and it is the only surface with
an attention model at all. Findings and Sources carry real evidentiary density (importance dots, meaning-before-state
row text, source grouping) that should survive any redesign. Every paid rebuild across Findings and Plan already
states its dollar amount, which is the product's most important trust behavior and the one most worth protecting.

**The 3–7 biggest experience problems**, in order of leverage:

1. **No attention model outside Research.** Home, Sources, Findings and Plan all lead with totals (13 projects,
   1348 sources, 16,437 findings, four stale-rebuild prices) rather than "what needs you." Research proves the
   product already knows how to do this; it simply isn't applied anywhere else.
2. **"Stale" has four unrelated presentations.** The same underlying state — content that changed since it was last
   analyzed — surfaces as a Findings banner, a Plan banner, a per-row badge, and a Sources filter chip, each with its
   own wording. A user cannot learn what "stale" means once and reuse that knowledge.
3. **No shared vocabulary or visual weight for reprocessing actions.** Rebuild, Re-analyse, Re-rank, Suggest,
   Re-check, "in the background" vs "on the API" are priced inconsistently and styled inconsistently, so cost and
   consequence have to be re-learned per surface.
4. **Loading is indistinguishable from empty.** Findings — the app's largest, most consequential list — renders a
   blank content area for 5–8 seconds with no skeleton, spinner or label. `DESIGN.md` §11 forbids exactly this, and
   it forbids it because a user cannot tell "nothing here" from "still loading."
5. **Row-action overload on the two workbenches.** Sources exposes six actions per row, including a red destructive
   action, across 1,348 rows; Findings rows carry four to five badges against a two-badge design target. Both are
   symptoms of exposing every capability at every row instead of surfacing what the current task needs.
6. **Visual system drift is measured, not assumed.** 430 inline `style=` attributes, 16 distinct font sizes and 11
   distinct radii against `DESIGN.md`'s six and four, plus two status colors (`--ok`, `--warn`) that fail WCAG AA
   contrast today. This is the structural reason the same concept (a stale badge, a primary button, a status pill)
   looks different on every surface.
7. **Status is a log line.** Provider health, today's spend, this month's spend, and an instruction ("use Re-check
   or start local work") are concatenated into one ~10px sentence in two places (Home, Chat sidebar footer) — the
   only place the app says whether local AI is healthy, rendered so it cannot be scanned.

**The major systemic pattern behind them:** the product has one good attention/consequence pattern (Research) and
has not propagated it. Everywhere else, the UI surfaces raw system state — counts, banners, badges, log-line
sentences — and leaves the user to infer what matters, what it costs, and whether it's safe to ignore. The visual
drift (item 6) is a second, independent pattern: styling was authored locally per surface instead of through shared
tokens and primitives, which is why fixing the vocabulary problem and the visual drift problem separately will not
converge to consistency — they need the same shared components.

## Audit scope and limitations

- **Mode:** FULL AUDIT, read-only half only. Kyle's 2026-09-13 decision deferred the interaction-walk half (Phase 3
  exercised, not merely observed) to a second pass on a dedicated audit instance; nothing here was clicked that
  queues work, spends money, changes status, or deletes.
- **Admission path:** this audit and this document are always permitted. Any ladder rung that changes a surface's
  job requires Foundation §34 UI scope, or a `DEVELOPMENT-OPERATING-SYSTEM.md` §13 override with collision
  analysis, before implementation — this document does not itself admit anything.
- **Instance used:** live instance only, via Claude in Chrome at 1440×900, against the largest real project (876
  sources, 16,437 findings, 34 chats) and the 13-project home screen.
- **Not covered in this pass:** narrow-viewport rendering (a resize attempt did not take — the capture frame stayed
  at desktop width), Health/Jobs surfaces, dark theme (not screenshotted), polling/refresh behavior over time, and
  every Phase 3 workflow walk (link/upload/paste acquisition, findings triage, chat, discover, plan rebuild, job
  monitoring) — all filed as **observed, not exercised**.
- **Incident found and already remediated during this audit, not carried forward as a finding:** Phase 0 surfaced
  ten junk projects created by a test-isolation defect (`tests/test_k3_resources.py` and 77 other modules losing to
  `.env` on `os.environ.setdefault(...)`), which caused two focused test runs to queue real, paid jobs against the
  live database. This was fixed in commit `e29b830` (`tests/conftest.py` hard-set + `tests/test_s51_test_isolation.py`
  regression gate) before this document was written. It is recorded here only because Home finding H2 below assumes
  test-junk-in-production can recur by other means; the ten existing junk projects still need manual deletion by
  Kyle via the UI, which this audit does not do.

## Product map

| Surface | User intent | Primary question | Scale observed | Attention model |
|---|---|---|---|---|
| Home | pick up a project / see the library | which project, how big is my library | 13 projects (10 test junk) | none — uniform cards |
| Chats | ask the corpus | what did the research say about X | 34 chats/project | none |
| Sources | manage what's owned; add more | what do I have, what did it give me | 1,348 rows | none — filter chips only |
| Findings | review/curate evidence | what's worth keeping, what's stale | 16,437 findings | banners only, three stacked and competing |
| Research | decide what to do next | what needs my attention | 1,710 open questions, ranked cards | **yes — the only surface with one** |
| Master Plan | act this week | what do I do next | stale banner + weekly checklist | partial — "Start here" precedes analysis |
| Settings | steer the brief | is the brief right | 25-line brief, ~3 shown | none |

Full per-surface intent/action/risk table: `raw.md` Phase 1.

### Five-second scorecard (structured human evaluation, not a measurement)

Scored 2026-09-13 from the interface alone, live instance, 1440×900, light theme. Yes / Partly / No are a
reviewer's judgments; they are recorded so a RE-AUDIT can re-score the same cells and show before → after, not
because they are objective. Deciding observations are in `raw.md` Phase 2.

| Surface | Where am I | Current state | What matters | What to do next | What that will do |
|---|---|---|---|---|---|
| Home | Partly | No | No | Partly | Partly |
| Chats | Yes | Partly | Yes | Yes | Partly |
| Sources | Yes | Partly | No | No | Partly |
| Findings | Yes | Partly | Partly | Partly | Yes (Rebuild) / No (Dismiss) |
| Research | Yes | Yes | Yes | Yes | Yes |
| Master Plan | Yes | Partly | Yes | Yes | Partly |
| Settings | Yes | n/a | Partly | Yes | Partly |

Scored on the F0 audit-instance pass, 2026-09-13, same reviewer:

| Surface | Where am I | Current state | What matters | What to do next | What that will do |
|---|---|---|---|---|---|
| Settings → Health | Partly (no nav entry; reached only by scrolling Settings) | Yes — once found, the panel itself is clear and well-labeled | Partly — no ranking of which warning matters most | n/a (read-only panel) | n/a |
| New/empty project (any surface) | Yes | Yes — explicit "nothing yet, do X" copy on every surface | Yes | Yes | Yes |
| Login | Yes | n/a | n/a | Yes | Yes |

Not yet scored: a failed job, a failed poll.

**Narrow viewport — image evidence only, not an interactive scorecard pass (F0 evidence-recovery addendum, 2026-09-13).**
Kyle captured Sources, Research and a chat-with-citations at ~390pt width by hand (the browser-automation resize
tool still does not work). Judged from the static images alone, not an interactive walk, so scored conservatively:

| Surface (narrow) | Where am I | Current state | What matters | What to do next | What that will do |
|---|---|---|---|---|---|
| Sources (numbers + list) | Yes | Yes — no visible overflow or clipped text | Partly — same dense numbers grid as desktop, unranked | n/a (static capture) | n/a |
| Research overview | Yes | Yes | Yes — "Do these next" cards already rank by consequence | Yes | Yes |
| Chat with citations | Yes | Yes | Yes — citation markers render inline, unclipped | n/a (static capture) | n/a |

No layout break, clipped text, or horizontal scroll is visible in any of the three; this is a positive signal, not
a substitute for an actual interaction pass (scrolling, tapping a citation, opening the nav) at this width.

## Critical findings

None found in this pass. Nothing observed rises to AUDIT.md §7's bar (a core workflow that cannot be completed, a
UI that communicates materially false state, dangerously unclear destructive/costly behavior, a severe accessibility
blocker on a core path, or failure indistinguishable from success). The nearest candidate — Findings' blank loading
period — is filed as High below because it is time-bounded and does not assert false state, only withholds true
state.

## High-priority findings

### `[H-1] The system-health/spend status is a single unscannable log line`

**Severity:** High **Scope:** Cross-surface (Home, Chat sidebar) **Confidence:** High
**Evidence:** Visual **Affected surfaces:** Home, Chats

**What I observed:** Home and the Chat sidebar footer each render one muted sentence mixing today's spend, this
month's spend, provider health, an instruction, a call count and a percentage — e.g. "$0.43 today · $147.58 this
month · Claude Code: not checked · use Re-check or start local work · 8,229 AI calls · 24% local · $144.98 actual ·
$522.74 avoided" — the Chat sidebar renders this at roughly 10px in a ~110px column.

**Why this matters:** this is the only place the app states whether local AI is healthy, and whether the user is
spending money at an unexpected rate. Encoding it as prose in one font size and weight makes it something a user
reads once, not something they can scan on every visit — which defeats the purpose of a status line.

**Root cause:** part of RC-F (status rendered as a log line) and RC-A (no attention model — this is exactly the kind
of information an attention model should surface first, not last).

**Improvement direction:** a status component with independently legible parts (health indicator, today's spend,
period spend), ordered by what a user needs to notice first, not by narration order.

**Acceptance test:** a user can state whether local AI is healthy and roughly what they've spent this session by
glancing at Home for under a second, without reading a full sentence.

**Propagation:** any shared status/attention component (ladder L1, L7) must also serve Chat's sidebar footer.

### `[H-2] Findings' loading state is indistinguishable from its empty state`

**Severity:** High **Scope:** Local (Findings), pattern is systemic **Confidence:** High
**Evidence:** Runtime **Affected surfaces:** Findings; likely Sources and Chats at large scale (unmeasured)

**What I observed:** navigating to Findings on the 16,437-finding project leaves the content area blank for roughly
5–8 seconds with no skeleton, spinner, or "loading" label before rows appear.

**Why this matters:** `DESIGN.md` §11 explicitly forbids this pattern. A first-time or impatient user has no way to
distinguish "still loading" from "you have no findings," which is the worst possible ambiguity on the app's largest
evidence surface — it could plausibly cause someone to believe curation work was lost.

**Root cause:** RC-E, no shared loading-state primitive; each list surface renders its own way (or no way) between
navigation and data arrival.

**Improvement direction:** a shared loading/empty/failure state primitive (skeleton rows or a labeled spinner) used
by every list surface, so "loading," "empty," and "failed" are three visually distinct, consistently-styled states
everywhere.

**Acceptance test:** on a fresh navigation to a large project's Findings, a loading indicator appears within one
frame and remains until real content or a real empty state replaces it — never a blank content area.

**Propagation:** check Sources (1,348 rows) and any Chat history load for the same gap; not measured this pass.

### `[H-3] Findings stacks three competing warning banners above the work`

**Severity:** High **Scope:** Local (Findings) **Confidence:** High
**Evidence:** Visual, Documentation **Affected surfaces:** Findings

**What I observed:** a stale-sources banner (822 sources, two sub-sections, four priced Rebuild options plus an
"Accept 399 as still usable" link), a "SUGGESTED — nothing waiting" banner, and a "4,805 approved findings at
importance ≤2 were never used" banner render stacked above every finding, on every visit.

**Why this matters:** `DESIGN.md` §8 for Findings explicitly says to avoid stacked warning banners above the work.
Three banners competing for the same attention, each pricing multiple actions, forces the user to triage
system-generated housekeeping before they can do the review they came for.

**Root cause:** RC-A (no attention model — three separate detectors each claim top-of-page real estate) and RC-C
(stale, low-value, and unused-finding cleanup are three faces of "things the system thinks need review" with no
shared design).

**Improvement direction:** the "better recommendation" pattern AUDIT.md §9 itself gives — consolidate stale-source
review, low-value-finding review, and unused-finding review into one Review entry point that explains why each item
needs attention and exposes no bulk destructive action until the affected set is understood.

**Acceptance test:** a returning user sees at most one system-prompted review entry point above the finding list,
not three independently-worded banners.

**Propagation:** the same consolidation should absorb Plan's stale banner (`[H-6]`) if the underlying state is the
same "stale" concept — verify before merging the two banners into one component.

### `[H-4] Sources rows expose six actions each, including an unshielded destructive one, at 1,348 rows`

**Severity:** High **Scope:** Local (Sources) **Confidence:** High
**Evidence:** Visual, Code, Runtime **Affected surfaces:** Sources

**What I observed:** every source row carries six actions — What this gave · Transcript · Suggest findings · ☆ Make
priority · Remove from project · **Delete everywhere** (red text) — rendered identically at 889-1,348 rows
(≈5,300-8,000 buttons on one page, depending on project). "Remove from project" and "Delete everywhere" sit
adjacent, distinguished only by color.

**Runtime-verified (F0 addendum 4, 2026-09-14, `raw.md`):** exercising the row actions directly on the audit
instance surfaced a sharper version of the same root cause — row height and button-row width are not uniform
(long-form sources add a "Read deeper" button, sources with embedded videos add another, some rows carry an extra
tag/count line), so a fixed vertical click offset does not reliably land on the same button across rows of
different heights during a fast, repeated bulk pass. A real misclick (a title link opened instead of the intended
row action) occurred during an 11-row timed sample. This does not change the finding's severity or confidence
(both already High) — it sharpens the acceptance test below and gives Rung W4 a concrete regression to check
against, not just a theoretical adjacency risk.

**Why this matters:** at review scale, a destructive, irreversible, cross-project action ("Delete everywhere") is
one misclick away from a merely-per-project one ("Remove from project"), repeated on every one of 1,348 rows. Row
weight equal to Findings' single per-row "Dismiss" would make the page far calmer for the common case (browsing,
not deleting).

**Root cause:** RC-D, row action overload — every capability is exposed at every row instead of behind progressive
disclosure or an overflow control.

**Improvement direction:** surface one primary action per row by task context (reviewing vs. curating), move the
rest — destructive actions especially — behind an overflow affordance with a confirmation appropriate to
irreversibility.

**Acceptance test:** a source row exposes one primary action by default; secondary/destructive actions require one
additional, deliberate step; "Delete everywhere" is never adjacent to a same-styled, lower-consequence action.

**Propagation:** Findings' per-row badge density (`[M-4]`) is the same class of problem at lower severity — check
for a shared solution.

### `[H-5] No shared vocabulary, pricing disclosure, or visual weight for reprocessing actions`

**Severity:** High **Scope:** Systemic **Confidence:** High
**Evidence:** Visual, Documentation **Affected surfaces:** Findings, Master Plan, Sources, Chats

**What I observed:** Rebuild, Re-analyse (now / in background), Re-rank, Suggest findings, Re-check, and "on the
API" vs "in the background" appear across Findings, Plan, Sources and Chat, each priced or unpriced independently,
and each styled with locally-authored button treatments (raw.md counts at least four distinct "primary button"
treatments in this pass alone).

**Why this matters:** a user who learns that Findings' "Rebuild" costs money and needs confirmation has no reason to
expect Sources' "Suggest findings" (unpriced) or Chat's "also search the web" (unpriced, no consequence text) behave
differently — until they don't. Every surface has to be re-learned separately.

**Root cause:** RC-B, no shared action/state contract for reprocessing.

**Improvement direction:** one action/state contract — a fixed vocabulary, a fixed rule for when cost must be shown
inline, and one shared button-treatment set for primary/secondary/destructive/paid actions — applied to every
affected surface in the same rung, per AUDIT.md §9's own worked example.

**Acceptance test:** given any reprocessing action's label, a user can predict whether it costs money and roughly
what happens, without having seen that specific surface before.

**Propagation:** Sources "Suggest findings" and Chat "also search the web" currently disclose no cost or consequence
at all — both must move to the same disclosure rule as Findings/Plan, not just the same visual style.

### `[H-6] Master Plan's stale banner forces four choices before the plan is visible`

**Severity:** High **Scope:** Local (Master Plan) **Confidence:** Medium
**Evidence:** Visual **Affected surfaces:** Master Plan

**What I observed:** "Rebuild plan," "Re-analyse now + rebuild · $48.49," "Re-analyse in background + rebuild ·
$24.46," and "Raise budget" render as four options in one banner above the plan itself.

**Why this matters:** cost is stated for each option (a genuine strength, per AUDIT.md's own trust criteria), but a
new or returning user has to parse and choose among four priced/unpriced options — a decision — before seeing the
plan they came for, on the surface `raw.md` also credits with the best "start here / this week" ordering in the app.

**Root cause:** RC-C (stale, presented differently than Findings' version) combined with RC-A (no ranking of which
stale-remediation option is actually recommended for this case).

**Improvement direction:** default to a single recommended action with the others available on request, matching
Research's "one primary, others plain" hierarchy (`[R-2]` in raw.md, a strength worth reusing here).

**Acceptance test:** the plan itself is visible above the fold with at most one prominent stale-remediation action;
the remaining options are reachable but not co-equal.

**Propagation:** should share a component with the Findings stale banner (`[H-3]`) if merged.

### `[H-7] Two status colors fail WCAG AA contrast; the visual system is measurably drifted from `DESIGN.md``

**Severity:** High **Scope:** Systemic **Confidence:** High
**Evidence:** Measurement, Code **Affected surfaces:** every surface using `--ok`/`--warn`, and any surface with inline styling

**What I observed:** `--ok` (3.47:1) and `--warn` (3.64:1) both fail the 4.5:1 AA floor for normal text on `--panel`,
and have since before this audit (`HARDENING.md`, D0). Separately, `index.html` measures 430 inline `style=`
attributes, 28+3 color literals outside the token blocks, 16 distinct font sizes and 11 distinct radii against
`DESIGN.md`'s six and four.

**Why this matters:** `--ok` and `--warn` are the colors that carry "healthy" and "needs attention" across the
product — the two states the attention-model findings above depend on being legible. Separately, the measured
inline-style/token drift is the structural reason a corrected token and an inconsistent screen can coexist: fixing
the palette in `DESIGN.md` does nothing to the rendered UI until the tokens are actually adopted at each of these
430 sites.

**Root cause:** RC-G, styling authored locally per surface instead of through shared tokens/primitives; the
`--ok`/`--warn` failure is a specific, pre-existing instance of the same absence of a single source of truth.

**Improvement direction:** land the frozen, AA-validated token set from `HARDENING.md`/`DESIGN.md` (D2), and retire
inline styling surface-by-surface, lowering the `tests/test_s50_design_drift.py` ceilings in the same commit per its
own ratchet rule.

**Acceptance test:** `--ok`/`--warn` measure ≥4.5:1 on `--panel` in both themes (already computed: 5.29 / 5.24); the
S50 ratchet's counts decrease, never increase, rung over rung.

**Propagation:** every finding above that references inconsistent button/badge/banner styling (`H-3`, `H-5`, `H-6`)
depends on this rung landing first or alongside — see ladder ordering.

## Medium findings

- **`[M-1]`** Home's project cards are visually uniform with no last-activity, attention, or provenance signal — a
  0-source test project is indistinguishable from an 876-source real one. `[Visual]` Ties to `H-1`/RC-A.
- **`[M-2]`** Home's "Your research in numbers" stat block (7 tiles) uses larger type than any project title on the
  page and answers "how much," not "what now" — it competes with, rather than supports, the page's actual job of
  picking a project. `[Visual]`
- **`[M-3]`** Card-body clicks on Home give a focus ring but do not navigate; only the title text does — an
  acknowledgement gap between what looks clickable and what is. `[Runtime]`
- **`[M-4]`** Findings rows carry four to five badges (plan, 2×, weak, ⚠ stale source, topic) against `DESIGN.md`'s
  two-badge target; individually clear, cumulatively dense. `[Visual]`
- **`[M-5]`** Findings' filter row has six selects plus a search box with no visible active-filter summary, making
  it hard to tell why the current list looks the way it does. `[Visual]`
- **`[M-6]`** The Findings sidebar badge (16,437, styled in red) reads as an alert but is only the total count, not
  an attention signal — the opposite of `H-1`'s problem (state hidden) applied to a badge that overclaims urgency.
  `[Visual]`
- **`[M-7]`** Sources' add-source panel (tab strip + textarea + options) occupies the top ~180px of the page on
  every visit, even though reviewing 1,348 existing sources is the more common intent than adding new ones.
  `[Visual]`
- **`[M-8]`** Research's "1,710 important open questions" renders as a stat tile — a number with no action attached
  — while the real answer (the ranked list below it) is the surface's own best pattern. `[Visual]` Self-inconsistency
  worth fixing even on the app's strongest surface.
- **`[M-9]`** The sidebar's Research/Plan toggle changes the project's mode, not the current view, but is styled as
  a segmented view switch — a mismatch between control affordance and actual effect. `[Runtime/Visual]`
- **`[M-10]`** Settings' brief textarea shows roughly 3 of ~25 lines of the single most consequential text in the
  project, and Save carries no statement that editing the brief invalidates Findings/Plan (it does — `brief_revision`
  in code). `[Visual/Code]`
- **`[M-11]`** The Chat sidebar's chat list is unbounded (20+ visible) with no grouping by recency. `[Visual]`

## Medium findings (F0 addendum)

- **`[F0-3]`** The project's Goal/Brief text renders unlabeled in the sidebar directly above the spend/status
  footer, with no heading distinguishing it from system state — on a long brief it wraps and crowds the already
  dense status line. Additive to `H-1`/`RC-F`, not a new root cause: `W5`'s status component must label or
  relocate this line, not just reflow around it. `[Visual]` — audit instance, 2026-09-13.
- **`[F0-4]`** Discover's per-job progress badge froze at "18s · alive 17s ago" for roughly 35-50+ seconds
  while the page's top progress summary line kept advancing correctly (18s -> 35s -> 53s -> 73s+), and the whole
  operation ultimately took ~9x its own stated "~10s" ETA before completing successfully -- naturally occurring,
  not manufactured. A user watching only the small badge would reasonably conclude the job had died. Folds into
  `RC-C` (stale-state has four independent presentations) as a fifth instance, not a new root cause. Same widget
  class appears in Sources' "queued" panel (addendum 1); not separately confirmed there this pass -- see Residual
  Coverage. `[Runtime]` -- RUNTIME VERIFIED, audit instance, 2026-09-13 (F0 addendum 3).

## Low / polish findings

- **`[F0-1]`** A new chat's placeholder guidance rendered blank on first visit, then showed full guidance copy on
  a later visit to what appeared to be the same view — not reproduced a second time, low confidence, possibly the
  same class of defect as `H-2` (a brief loading gap read as permanently empty). Flagged for the interaction-pass
  audit to confirm or rule out, not yet a confirmed finding. `[Runtime]`
- **`[F0-2]`** A failed source's error text is a raw internal exception string (`Cannot parse data retryable ·
  other`) surfaced verbatim, not translated into something a user can act on — inconsistent with the plain-language
  standard the Health panel otherwise holds to. `[Visual/Copy]`
- **`[L-1]`** Every source-row thumbnail observed was an empty grey rectangle with no fallback glyph. `[Visual]`
- **`[L-2]`** "Master sheet CSV" and "Segments CSV" exports are placed among Sources' filter controls rather than
  with other export/utility actions. `[Visual]`
- **`[L-3]`** In the chat header menu, "Delete" renders as plain text at the same weight as "Rename" and "Share
  this chat." `[Visual]`
- **`[L-4]`** Master Plan's footer tab strip (Where you stand · Do this · Decide · Money & tools · Watch out ·
  Evidence) sits at the bottom of a long page rather than functioning as persistent navigation. `[Visual]`
- **`[L-5]`** The version tag (`v0.63.43`) renders at ~10px in the sidebar footer. `[Visual]`

## Design-system drift

Measured 2026-09-12/13 against `neurosearch/web/index.html`, held as a ratchet in `tests/test_s50_design_drift.py`
(counts may fall, never rise without a recorded `HARDENING.md` decision):

| Measure | Value | `DESIGN.md` target |
|---|---:|---|
| inline `style="` attributes | 430 | none in new UI |
| colour literals outside token blocks | 28 CSS / 3 JS | 0 |
| distinct `font-size` values | 16 | 6 |
| distinct `border-radius` values | 11 | 4 (+50% for circles) |
| controls whose only glyph is an emoji | 8 | 0 |
| colour tokens missing a dark value | 0 | 0 |
| `--ok` / `--warn` contrast on `--panel` | 3.47 / 3.64 (fail) | ≥4.5 (frozen fix: 5.29 / 5.24) |

### Where the inline styles are (measured 2026-09-13, working tree at `b85c222` + Codex's uncommitted diff)

`AUDIT.md` Phase 5 asks for the worst offending surfaces, not the global number. Each `style="` was attributed to
the static view container or the JS render function that contains it; surfaces below aggregate those owners
(function names in parentheses). The global count is a ratchet, not a target — what matters is that the drift is
concentrated in a few surfaces and a few repeated declaration families, which is what makes it tokenizable.

| Surface / component | Inline `style=` | Repeated, tokenizable patterns | Likely intentional one-offs |
|---|---:|---|---|
| **Sources** — static `#view-sources` markup (51), `srcRowHtml` (13), `sourceDrawer` (9), `renderBook` (7), `transportChoiceHtml` (7), capture queue / library suggestions / seen (25), quality & promotable drawers, value report (20), `browserBlock`, `classifyInput` (9) | **~141** | spacing stack, flex-row utilities, `font-size:12/12.5px` overrides, `width:auto` on checkboxes/buttons, `display:none` toggles | `max-height:40vh;overflow:auto` scroll regions (4); a handful of drawer alignments |
| **Research** — static markup (27), `renderOverview` (9), `claimCard` (5), `woCard`, `renderQuestionsPane`, `whereToLook` (12) | **~53** | flex-row utilities, spacing stack, status colours on cards | none obvious |
| **Jobs / Health / boot** — `loadJobs` (14), `renderBoot` (8), `bootRow` (8), `loadPool` (6), `loadWorkbench` (5), `loadBacklog`, `perfReport`, `loadNotes` (12) | **~53** | spacing stack, `color:var(--warn)` / `var(--bad)` status text, `font-size:11px` | none obvious; this surface was not visually audited (F0) |
| **Master Plan** — `renderPlan` (18), `renderTriageCard` (8), `renderStaleCard` (8), `renderNoPlan` (4) | **~38** | banner spacing, `border-color:var(--warn)` on stale cards, `display:flex;gap` rows | none obvious |
| **Settings** — static markup | **30** | `margin-top` stack between form rows, `width:auto` on inputs | none — this is a form that should be a form component |
| **Findings** — static markup (12), `loadReviews` (14) | **~26** | banner spacing and status colours | none |
| **Chats** — static (7), `addMsg`, `whyThisAnswer` (8) | **~15** | spacing | — |
| Home / wizard, shell, remainder | ~74 | scattered | — |

**The six declaration families** that account for most of the 430, counted across all owners:

| Family | Declarations | What it says about the system |
|---|---:|---|
| vertical spacing (`margin-top:` 2/3/4/6/8/10/12/14px, `margin-bottom`, `margin:4px 0`) | ~135 | no spacing stack utility or component spacing; every gap is hand-set |
| flex rows (`display:flex`, `flex:1`, `gap:6/8px`, `align-items`, `flex-wrap`, `min-width:0`, `justify-content`, `margin-left:auto`) | ~150 | no `.row` / `.grow` / `.push-right` utilities — the same five-declaration row is retyped |
| type overrides (`font-size:` 11/12/12.5/13px) | ~66 | the type scale exists in `DESIGN.md` §4 but not as classes, so every secondary line overrides inline |
| `width:auto` | 27 | the base input rule sets `width:100%`; every checkbox and button must undo it — a defect in one rule, not twenty-seven |
| status colour (`color:var(--warn)`/`var(--bad)`, `border-color:var(--warn)`) | ~23 | no status modifier class; tokens are used, roles are not |
| visibility (`display:none` / `display:block`) | ~28 | state toggled by style instead of the `hidden` attribute |

Everything else is long-tail. Reading: the drift is not 430 independent decisions; it is roughly six missing
shared rules plus one wrong base rule, concentrated in Sources and the three renderers that draw Jobs/boot, Plan
and Research. That is what F1 in `ladder.md` retires, ranked in that order. Codex's uncommitted diff to
`renderBoot` is net-neutral on this count (it removes lines and adds one `width:auto`).

Unmeasured but observed: at least four distinct "primary button" treatments (Research cards, Chat composer, Plan
banner, Sources "Add"); red used both for destructive actions and for a plain count badge; pill styling reused
across statuses, filters, chip-inputs, and the version tag with no visual distinction between the four roles. See
`H-7` for the finding this drives and `raw.md` Phase 5 for the full measurement notes.

## Workflow findings

Phase 3 (interaction walks) was deferred to a second, audit-instance pass per Kyle's 2026-09-13 decision; nothing
below was exercised, only observed as entry points, and none is reported at higher than Medium confidence, **except
Sources' row actions, which were exercised on the audit instance in F0 addendum 4 (2026-09-14, `raw.md`) — see
`[H-4]`'s runtime-verified note above**:

- The Sources link-acquisition textarea is pre-populated with three example YouTube URLs as grey placeholder text;
  a first-time user could plausibly mistake them for real, submittable content. `[Visual]` — Medium, unverified
  without an interaction pass.
- Findings' only reviewed row-level negative action is "Dismiss," with no visible statement of whether it is
  reversible. `[Visual]` — folds into `H-5`'s consequence-disclosure rule once written.
- Research's card actions ("Resolved" / "Not important to my project") are outcome-labeled rather than
  implementation-labeled — a strength (`DESIGN.md` §1.6) worth confirming holds once exercised.

Full entry-point notes: `raw.md` Phase 3.

## Accessibility / responsive findings

- **`--ok`/`--warn` AA contrast failure** — see `H-7`. This is the only accessibility finding with hard measurement
  behind it in this pass.
- **Narrow-viewport evidence is now partial, not absent.** The browser-automation resize tool still does not work
  (a 400×800 attempt did not take), but Kyle captured four states by hand at ~390pt width on 2026-09-13
  (Sources ×2, Research overview, a chat with citations) — see `evidence/baseline/`. None show a layout break,
  clipped text, or horizontal scroll. Home, login, empty-project, and failure states remain uncaptured at narrow
  width, so the layout/responsive question is answered for some surfaces, not all. Per `AUDIT.md` §4.3's mobile
  severity cap, any future narrow-viewport finding is still capped at Medium unless it also breaks a desktop
  workflow or the layout is unusable rather than cramped.
- No first-party console errors were observed in the sampled window (one Chrome-extension exception, not
  first-party). `[Runtime]` — recorded as a clean result, not a finding.

## Performance-as-experience findings

- **`H-2`** (Findings' blank load period) is the only measured perceived-performance defect this pass, but it is
  the highest-traffic instance of a pattern (RC-E) likely present anywhere a large list loads — Sources (1,348 rows)
  was not timed and should be in the interaction pass.
- Research's "1,710 open questions" and Findings' "16,437" sidebar badge are both raw counts presented as if they
  were performance/status indicators; neither tells the user how long anything will take or whether the system is
  working. Folded into `M-6`/`M-8` above rather than filed separately, since the underlying defect is attention
  modeling, not perceived latency.
- Sources renders all 1,348 rows as one grouped list; no virtualization or pagination signal was observed. Filed as
  a scale risk (`raw.md` Phase 1) rather than a confirmed defect, since no jank was actually measured this pass.

## Root-cause map

| ID | Root cause | Drives findings |
|---|---|---|
| RC-A | No attention model outside Research — every other surface answers "how much" before "what needs me" | H-1, H-3, H-6, M-1, M-2 |
| RC-B | No shared action/state vocabulary or visual weight for reprocessing actions | H-5 |
| RC-C | "Stale" has five independent presentations and vocabularies (Findings banner, Plan banner, row badge, Sources filter, Discover job-progress badge) | H-3, H-6, F0-4 |
| RC-D | Row action overload on the workbenches — every capability exposed at every row | H-4, M-4 |
| RC-E | Loading is indistinguishable from empty on large lists | H-2 |
| RC-F | Status (health, spend) rendered as an unscannable log-line sentence | H-1 |
| RC-G | Styling lives in 430 inline attributes rather than shared tokens/primitives | H-7, and the styling inconsistency inside H-3/H-5/H-6 |
| RC-H | Test isolation gap (incident, not a design defect) — already remediated in `e29b830`, listed here only for completeness | none open |

Closure-pass note (AUDIT.md Phase 9): RC-B (vocabulary) and RC-G (visual tokens) are separate root causes that
converge on the same surfaces — a rung that fixes one without the other will still look inconsistent even if it's
now correctly worded, or correctly styled but unpredictably priced. The ladder sequences RC-G (system foundation)
before RC-B/RC-C's cross-surface rollout for this reason. No contradictions between recommendations were found; no
recommendation here reintroduces a previously measured failure; no stale references to since-changed behavior were
found (the one behavior change during the audit period — the test-isolation fix — is a code path, not a UI surface,
and does not affect any finding above).

## Strengths worth preserving

- **Research's "DO THESE NEXT"** — ranked cards, one primary $0-stated action, consequence-of-inaction text. The
  model every other surface should adopt, not replace.
- **Explicit dollar amounts on every paid rebuild** (Findings, Plan) — the product's core trust behavior; no rung
  in the ladder should make a priced action's cost less visible than it is today.
- **Findings' row density and per-source grouping** — importance dots, meaning-before-state row text, grouped
  headers with counts; reduce badge count (`M-4`) without losing this structure.
- **Plan's "Start here" / "This week" ordering before analysis** — matches `DESIGN.md` §8; must survive the stale-
  banner simplification in `H-6`.
- **"What this gave" meaning-line on Sources rows**, decisions/constraints table on Settings, light-default with a
  working dark theme, inline chat citations, and Research's chip-style "Make this plan yours" answers — all named
  explicitly so implementation does not erase them incidentally.

## Completion criteria status (`AUDIT.md` §12)

F0 in `ladder.md` exits only when every row here reads *met* or *unsupported / n/a* with a reason.

| # | Criterion | Status |
|---|---|---|
| 1 | Product and version identified | met — 0.63.43; **baseline pinned at `21bb117`** (2026-09-13, F0 step 2): Codex's standalone `index.html` commit, drift counts re-measured there and identical (430 / 28 / 3 / 16 / 11 / 8) |
| 2 | Live product inspected read-only **and** interactions exercised on an audit instance | met — audit instance built (`tools/audit-instance.command`), a new project created and driven through every surface, a Master Plan build triggered, dark theme and login exercised (F0, 2026-09-13) |
| 3 | Surfaces inventoried by intent | met |
| 4 | Load-bearing workflows walked end to end | met — project creation, empty-state review, acquisition (add source), findings triage, chat, discover, and a Master Plan rebuild were all exercised on the audit instance (F0 addendum 3, six-flow runtime verification matrix, 2026-09-13); scale is separately tracked under criterion 6 |
| 5 | Important states incl. failure and empty inspected | met — every surface's empty state, one real failure state (a failed source), and the Health panel inspected (F0 addendum, `raw.md`) |
| 6 | Real-content / large-project behaviour tested | partly — observed at 876 / 16,437 / 1,348; not timed |
| 7 | Major findings carry reproducible evidence | partly — reproduction steps written for every finding; the original six screenshots from the audit-instance pass were lost to a sandboxed temp path (see `evidence/baseline/manifest.md` history), but eight canonical images taken directly by Kyle now cover Home/Sources/Findings/Research (desktop, dark) and Sources/Research/chat-with-citations (narrow) — not every individual finding has a matching image, so this stays partly, not met |
| 8 | Drift audited separately | met — measured, ratcheted, per-surface table above |
| 9 | Cross-surface interactions reviewed | met (as observed) |
| 10 | Raw observations preserved | met — `raw.md` |
| 11 | Symptoms consolidated into root causes | met |
| 12 | Materiality filter applied | met |
| 13 | Closure pass found no new unpropagated consequence | met — F0's four new findings (`F0-1` low-confidence, `F0-2`, `F0-3`, `F0-4`) fold into existing root causes (RC-E, RC-F, RC-C) with no contradiction; see F0 close-out |
| 14 | Ladder turns the biggest problems into coherent rungs | met — `ladder.md` |
| 15 | No product code changed | met |

Closed by the F0 audit-instance pass (2026-09-13): Jobs/Health, dark theme, empty project states, one failed
source. Narrow viewport went from **unsupported / not applicable** to **partly evidenced** after addendum 2's
static images, then to **interactively verified for two surfaces** (Master Plan, Sources) after addendum 3, once
`resize_window` was retried and worked — Home, login, empty-project, and failure states remain uncaptured
interactively (Residual Coverage, below). **Failed/recoverable job-state and interrupted/stale-poll inspection are
now both closed** (F0 addendum 3, 2026-09-13): a deterministic DNS-failure source exercised the queued -> failed ->
retried -> failed-again cycle end to end at $0 cost (see `[F0]` failure-state note in `raw.md`), and a naturally
occurring stale per-job progress badge during a live Discover run produced `[F0-4]` above. **Sources' interaction
walk is now closed too** (F0 addendum 4, 2026-09-14): row actions were exercised directly (not just read) with a
timed 11-row bulk-review sample, satisfying `ladder.md` Rung W4's stated precondition and sharpening `H-4` with a
runtime-observed misclick (see `raw.md` addendum 4).

## Residual Coverage

Per `AUDIT.md`'s Bounded stopping rule (Phase 9): the items below are known-uninspected surfaces that F0 is
closing without chasing further, because none is judged capable of changing a Critical/High finding, a root-cause
diagnosis, a material acceptance criterion, or `ladder.md`'s ordering. A future pass (interaction-pass audit, or
RE-AUDIT after any W-rung) should treat this list as its starting point rather than F0 reopening to cover it now.

- Narrow-viewport **interactive** verification on Home, login, empty-project, and failure states (Master Plan and
  Sources are now interactively verified; four other narrow states have static images only, from addendum 2; the
  rest have no narrow-width evidence of any kind).
- The six-flow runtime verification matrix (F0 addendum 3) was exercised on a small, single-project disposable
  dataset (2 sources, 1 chat, 1 plan), not at the 1,348-row / 16,437-badge scale observed on the real project
  (addendum 1) — this is why completion criterion 6 stays "partly," not the matrix itself.
- `[F0-4]`'s stale-badge pattern was observed once, on Discover; whether the same widget class staled identically
  on Sources' "2 queued" panel (addendum 1) is plausible but not separately confirmed.
- Timing baseline figures (`AUDIT.md` §4.6) are wall-clock, single-sample, and qualitative — not instrumented
  client-side timers — sufficient to rule out inventing a threshold from nothing, not to set one.
- The original six audit-instance screenshots lost to a sandboxed temp path (addendum 1/2 history) were never
  recovered; Kyle's own 8 replacement images (addendum 2) cover different states than the lost set, not a like-for-
  like replacement.
- Dark theme has computed-contrast verification only, no visual screenshot evidence (unchanged from before this
  addendum).

## Assumptions / cannot verify

Narrow-viewport interaction beyond Master Plan and Sources (resize-tool now works; Home, login, empty-project,
and failure states remain uninspected interactively — see Residual Coverage); whether Findings' blank period
(`H-2`) is network-bound or render-bound (needs client-side timing instrumentation, not just wall-clock
observation); dark theme was not screenshotted, so no visual (only computed-contrast) verification exists for it.
