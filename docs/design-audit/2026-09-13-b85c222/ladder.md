# Design Implementation Ladder

Derived from `docs/design-audit/2026-09-13-b85c222/audit.md`. This is a sequence, not a blanket authorization: D1
(rung F0) is complete, and D2 rungs are admitted one bounded surface at a time (`DESIGN-MISSION.md`,
`PRODUCT-SCHEDULER.md`). The repo is the control plane (see `HANDOFF.md`'s "Operating model" section) — a rung may
execute when its own preconditions below are satisfied, `PRODUCT-SCHEDULER.md` considers it eligible, a collision
analysis against current Git state has been performed for any surface it shares with active work, the work stays
bounded to the rung, and its required deterministic, behavioral and visual gates can be run. User approval is not a
routine implementation gate; stop only for a genuine unresolved product decision, a destructive or costly action
needing consent, an architectural conflict, or a semantic collision that cannot be safely reconciled. (This replaces
an earlier reference to a "Foundation §34 UI scope" and "`DEVELOPMENT-OPERATING-SYSTEM.md` §13 override" — neither
document defines those sections; that was stale manual-admission language from before the repo-as-control-plane
model.) Shared files such as `neurosearch/web/index.html` are not permanently owned by either agent: inspect current
Git state and any active changes touching the same file, compare the exact regions/functions each unit intends to
modify, work from an isolated branch/worktree, preserve unrelated changes, and reconcile against current `main`
before landing — do not overwrite or reset another agent's work. Nothing in this document has been built.

The standard each rung is held to is `DESIGN.md`; the inspection procedure that verifies each rung is `AUDIT.md`
(RE-AUDIT mode). This file does not restate either — it names sections. The current shell is the starting point
(`DESIGN.md` §2); a rung may change information hierarchy and interaction where the audit shows the current
structure is accidental, and may not change feature semantics or hardened behavior.

Groups, in order: preflight, system foundations, workflow/IA, component consistency, polish. Do not start a rung
before the rung it names as a precondition has landed — the audit's closure pass found that vocabulary and token
fixes converge on the same surfaces, so building the workflow change first would mean restyling it a second time.

## How a rung is gated

Every W-rung carries three gate types, applied where they fit:

- **Deterministic / system gate** — a test or measurement that passes or fails without judgment: the frontend
  gates named in `AUDIT.md` §4.3 (`test_s44`, `test_s5`, `test_s50`, `UI_VERSION`), contrast, token use, state
  semantics, request-path purity.
- **Behavioral / workflow regression gate** — the affected workflow still does what it did: existing workflow tests,
  plus a walk on the audit instance confirming every action the rung touched keeps the same user-visible operation,
  state transition, authorization requirement, cost class and truthful disclosure, reversibility, and downstream
  consequence — unless the rung explicitly intends to change one of those. Endpoint and payload may be recorded
  during the walk for debugging; they are not a design gate, and "same price" means same cost class and honest
  estimate, not the same number.
- **Human UX re-score** — the five-second scorecard (`AUDIT.md` Phase 2) is a structured human evaluation,
  Yes / Partly / No, not a measurement. Each rung names the specific cells it intends to improve; after
  implementation those cells are re-scored and recorded before → after. A cell that the evidence does not move
  stays where it is; the rung is not failed for honesty.

Scorecard cells are written `Surface › column` using the columns in `raw.md` Phase 2: Where am I · Current state ·
What matters · What to do next · What that will do.

---

## Preflight

### `Rung F0` — Design preflight: a trustworthy baseline

**Problem being solved:** neither `audit.md` nor this ladder can be verified against the product as it is, because
(a) the UI file has an uncommitted diff from another session, (b) half of `AUDIT.md`'s coverage was never inspected,
and (c) `evidence/` is empty, so a RE-AUDIT has no before-state to compare with.

**Affected surfaces:** none changed. This rung changes no product design and no product code.

**What F0 does, in order:**

1. **No design implementation while any UI diff is uncommitted.** Codex's current T1 set (`bootstrap.py`,
   `resources.py`, `index.html`, `test_k3_resources.py`, `test_s14_fix_pass.py`) is finished and committed, or
   abandoned, by its owner. Not by this ladder.
2. **Pin the baseline.** Record the resulting commit SHA as the design/audit baseline in `audit.md` Phase 0 and in
   `HARDENING.md`'s drift entry. Re-run the `test_s50` measurement against that SHA; if the counts moved, the
   ceilings and the table in `audit.md` are corrected to the pinned SHA in the same commit.
3. **Build the minimum audit instance** per `AUDIT.md` §3 ("the audit does not spend money or change the user's
   research"): private `NEUROSEARCH_DATA_DIR` restored from a copied verified backup, `NEUROSEARCH_FAKE_AI=1` or a
   zero budget, a different port. The *procedure* is not disposable: a tiny generic launcher (a `.command` or a
   documented command in `AUDIT.md` §3 — one screen, no framework) is tracked; the copied database, the private
   data directory, tokens, cookies and any machine-private state are gitignored and never tracked. RE-AUDIT must
   be able to recreate the instance from the tracked procedure alone.
4. **Finish the missing coverage** on that instance, following `AUDIT.md` Phase 3–4 and appending to `raw.md`:
   normal/default states of every surface; the important failure and empty states (new project with nothing in
   it, a failed source, a failed job, a failed poll); Jobs / Health / cost feedback; narrow viewport (~390px,
   under the `AUDIT.md` §4.3 severity cap); dark theme — verified 2026-09-13 as an intentional product state since
   `v0.7` (persisted `🌙 Dark` / `☀️ Light` toggle in the header and sidebar), so it is inspected, not invented.
   Anything that cannot be reached is marked **unsupported / not applicable** explicitly, not skipped.
5. **Capture a small canonical screenshot baseline into `evidence/`.** One representative before-state per major
   surface and per important state — on the order of fifteen to twenty images, light and dark — named
   `<surface>-<state>-<theme>.png`. Not one per interaction. **Retention:** `evidence/` holds one `baseline/` set,
   at most one `current/` comparison set, and a short `manifest.md` (what each image shows, the SHA it was taken
   at). A RE-AUDIT that accepts a change replaces the superseded baseline images rather than adding a dated
   folder; a historical image is kept only when a documented regression names it. No screenshot history tree.
6. **Update `audit.md`** with any new material finding the coverage produces, and re-run the Phase 9 closure pass
   if one appears. Re-score the scorecard for any surface first seen in this step.

**Exit criterion:** `AUDIT.md` §12's completion criteria 1–15 are each marked *met*, or *unsupported / not
applicable* with a one-line reason, in `audit.md`. Until that table exists, no F1 work starts.

**F0 does not authorize F1.** Closing F0 ends with a report, not a commit to product code: does anything found in
step 4 change the ladder's ordering, scope, or root-cause diagnosis? If not, F1 may be admitted next. If it does,
the ladder is patched first and F1 waits for the patched version. F1 is never started in the same step that closes
F0.

**Non-goals:** no token change, no copy change, no layout change, no new component, no refactor "while in there."
If step 4 finds a defect in a state nobody has seen, it is filed, not fixed.

**Effort:** M (mostly inspection time) **Risk:** Low — nothing is changed.

---

## System foundations

### `Rung F1` — Land the frozen tokens, retire the tokenizable inline patterns, name the eight controls

**Problem being solved:** `H-7` (RC-G). `--ok`/`--warn` fail AA today; 430 inline `style=` attributes carry most of
the UI's visual language outside the stylesheet. The per-surface measurement in `audit.md` "Design-system drift"
shows the drift is concentrated, not diffuse: Sources markup and drawers, Research, the Jobs/Health/boot renderers,
and Plan account for roughly two-thirds of it, and six repeated declaration families account for most of those.

**Affected surfaces:** `index.html` token block; then the worst offenders in the order the table ranks them.

**Proposed change:**

1. Replace the `:root` / `[data-theme=dark]` token blocks with the frozen set in `DESIGN.md` §3 / `HARDENING.md`
   (D0). This alone fixes the two AA failures.
2. Add the small set of shared rules the offender table shows are missing — the spacing stack, the flex-row
   utilities, the type-scale classes, the status modifiers — and retire inline occurrences of those families on the
   ranked surfaces. Fix the base-input rule that forces `width:auto` onto twenty-seven checkboxes and buttons.
   Replace `style="display:none"` state toggles with the `hidden` attribute where the JS toggles them.
3. **Give the eight emoji-only controls a name.** The smallest maintainable approach that fits a single-file app:
   an inline `<svg><symbol>` block holding *only the glyphs those eight controls need* (likely five distinct
   shapes), `stroke:currentColor`, each control gaining an `aria-label` and `title`. Not an icon system, not a
   framework, not a twenty-glyph library — `DESIGN.md` §6 asks for consistent, accessible iconography, and eight
   controls need eight names. Emoji that sit beside a text label stay as they are.

**Why this precedes W1:** every workflow rung restyles buttons, banners and badges; doing that against drifted
tokens means doing it twice.

**Non-goals:** no layout, copy, or hierarchy change; no attempt to reach zero inline styles in one pass — the
intentional one-offs in the offender table (scroll-region heights, a few genuine single-use alignments) are left
alone and the ratchet is lowered to whatever was actually retired.

**Seam:** `<style>` block; Sources static markup (`#view-sources`), `srcRowHtml`, `sourceDrawer`, `renderBook`;
Research static markup and `renderOverview`; `loadJobs`, `renderBoot`, `bootRow`; `renderPlan`,
`renderStaleCard`, `renderTriageCard`; Settings static markup.

**Gates.** *Deterministic:* `--ok`/`--warn` ≥ 4.5:1 on `--panel` in both themes; `test_s50` ceilings for inline
styles, colour literals and emoji-only controls lowered in the same commit; `test_s44`, `test_s5`; `UI_VERSION`
bumped in all three sites; every icon-only control has an accessible name (add this check to `test_s50`).
*Behavioral:* click acknowledgement and sustained busy state intact on every surface touched; no handler renamed.
*Human:* rendered check of every touched surface in both themes against the `evidence/` baseline — the goal is
"nothing looks different except the two status colours and the eight glyphs."

**Regression risks:** a token value read somewhere the ratchet does not count; the base-input fix changing the
width of a text input that relied on the old rule. Both are caught only by looking, hence the rendered check.

**Visual re-audit:** yes, DRIFT AUDIT mode, both themes. **Effort:** L **Risk:** Medium.

---

### `Rung F2` — Shared loading / empty / failure list-state primitive

**Problem being solved:** `H-2` (RC-E). Findings renders blank for 5–8 s; `DESIGN.md` §11 forbids it and says
skeletons appear on first paint only, never on a poll.

**Affected surfaces:** Findings first; Sources and Chat history checked on the audit instance (F0 step 4 will
have timed them).

**Proposed change:** one shared three-state primitive — loading, empty, failed — used by every list that renders
from a fetch, styled from F1's tokens, with an explicit failure branch so a stuck fetch reads as "failed", never as
"still loading."

**Why this precedes W1:** the workflow rungs change what renders once data arrives; this fixes what renders before
it does, so they inherit it instead of each solving it.

**Non-goals:** polling behaviour after first paint (`DESIGN.md` §11 already specifies it; F0 measures whether it is
violated; a separate rung if so).

**Seam:** the fetch/render paths for Findings, Sources and Chat history lists.

**Gates.** *Deterministic:* request-path purity — showing a loading state starts no job; `test_s44`, `test_s5`,
`UI_VERSION`. *Behavioral:* on the audit instance, a fresh navigation to the large project's Findings shows the
loading state within one frame and clears on data or on error; a forced fetch failure shows the failed state.
*Human:* re-score `Findings › Current state` (Partly → expected Yes).

**Regression risks:** a loading state that never clears is worse than a blank; the failure branch is not optional.

**Visual re-audit:** Findings, plus whichever other lists gained the primitive. **Effort:** M **Risk:** Low.

---

## Workflow / information-architecture changes

### `Rung W1` — One reprocessing action vocabulary and one disclosure rule

**Problem being solved:** `H-5` (RC-B). Rebuild / Re-analyse / Re-rank / Suggest / Re-check / "in background"
vs "on the API" are worded, priced and styled independently on Findings, Plan, Sources and Chat.

**Affected surfaces:** Findings (Rebuild banner), Master Plan (Re-analyse banner), Sources ("Suggest findings"),
Chat ("also search the web").

**Proposed change:** one contract — labels that follow `DESIGN.md` §1 rule 5 (a bare operation verb is fine when
its outcome is predictable, inadequate when it is not; this is semantic clarity, not a forbidden-word list), one
rule for disclosure (any action capable of initiating non-free work exposes the applicable cost mode or estimate
before commitment, using the app's real cost semantics — `$0`, local/subscription time, an API estimate, or "may
use model/web-search budget" are all valid disclosures), and one button treatment per role from `DESIGN.md` §5
(primary / secondary / tertiary / danger). Applied to all four surfaces in one rung.

**Precondition:** F1 landed. **Why before W2/W3:** the banner consolidations need settled wording to consolidate
around.

**Non-goals:** what any action does or costs is unchanged; Findings' and Plan's banners are not yet merged (W2/W3).

**Seam:** action-button markup on the four surfaces; the shared button rules F1 added.

**Gates.** *Deterministic:* `test_s44`, `test_s5`, `test_s50`, `UI_VERSION`. *Cost-disclosure check (behavioral,
enumerated from the product, not from JavaScript):* list the actions that can initiate non-free work from the
app's own cost/job metadata — the job kinds and admission classes the server prices, the web-search and model
budgets — and on the audit instance confirm each such action shows its applicable cost mode or estimate before
commitment. Not bound to handler names, endpoint names, or a literal price element. *Behavioral:* each of the four
surfaces' reprocessing actions keeps the same user-visible operation, state transition, cost class and disclosure,
reversibility and downstream consequence (endpoint/payload recorded for debugging only); existing workflow tests
(`test_s14_fix_pass`, the Findings/Plan rebuild tests) pass. *Human:* re-score
`Sources › What that will do` (Partly), `Chats › What that will do` (Partly), `Findings › What that will do`
(Yes for Rebuild / No for Dismiss — record the Dismiss half), `Plan › What that will do` (Partly). Expected:
each moves toward Yes; Dismiss's reversibility must be stated or the cell stays No.

**Regression risks:** relabelling a control users have muscle memory for — keep the closest existing term where it
already fits the contract.

**Visual re-audit:** all four surfaces together. **Effort:** M **Risk:** Medium.

---

### `Rung W2` — Findings: three stacked banners become one Review entry point

**Problem being solved:** `H-3` (RC-A, RC-C). `DESIGN.md` §8 (Findings) forbids stacked warning banners above the
work; three are there.

**Affected surfaces:** Findings.

**Proposed change:** one Review entry point that explains why each item needs attention, separates
system-detectable cleanup (stale, never-used) from user judgment, and exposes no bulk destructive action until the
affected set is understood — `AUDIT.md` §9's own worked example. Every action inside it uses W1's contract.

**Precondition:** W1 landed. **Why before W3:** Plan's banner is most likely the same "stale" state; prove the
component here first, then decide in W3 whether Plan shares it.

**Non-goals:** stale detection, pricing, and rebuild triggers unchanged; finding rows untouched (C1).

**Seam:** the Findings banner-rendering block (`loadReviews` and the static `#view-findings` markup).

**Gates.** *Deterministic:* `test_s50` (banner markup is a common inline-style source); `test_s44`, `test_s5`,
`UI_VERSION`. *Behavioral:* every priced option previously visible (four Rebuild variants, "Accept N as still
usable", "Review them", "Dismiss all N") is reachable from the new entry point with the same operation, cost class
and truthful estimate, reversibility and consequence — checked on the audit instance; a bulk-dismiss cannot be
reached without the count of affected items on screen; per `DESIGN.md` §3's progressive-disclosure rule, why each
item needs attention is visible at the entry point itself (0 clicks), not behind a further expand, and each
previously-visible priced option stays reachable within ≤ 2 clicks of the entry point. *Human:* re-score `Findings › Current state` (Partly) and `Findings › What matters`
(Partly). Expected: both toward Yes.

**Regression risks:** this is the rung most likely to hide a priced action a user currently sees at once — the
behavioral gate exists for exactly that. The strengths list in `audit.md` names explicit dollar amounts as the
product's core trust behaviour; visibility of price may not regress.

**Visual re-audit:** yes. **Effort:** M **Risk:** Medium.

---

### `Rung W3` — Master Plan: one recommended stale action, the plan above the fold

**Problem being solved:** `H-6`. Four co-equal options before the plan is visible.

**Affected surfaces:** Master Plan.

**Proposed change:** one recommended action by default, the others one step away — the "one primary, others
plain" hierarchy Research already uses. The recommendation follows an explicit, stated rule (e.g. the cheapest
option that fully resolves staleness), never an arbitrary pick. Decide here whether the banner shares W2's
component or only its styling.

**Precondition:** W2 landed.

**Non-goals:** the four options and their prices are unchanged; "Start here / This week" ordering (a named
strength) is not moved.

**Seam:** `renderStaleCard`, `renderPlan` banner block.

**Gates.** *Deterministic:* `test_s44`, `test_s5`, `test_s50`, `UI_VERSION`. *Behavioral:* all four options still
reachable with the same cost class and disclosure behaviour (audit instance); the plan's first section is visible
without scrolling at 1440×900. *Human:* re-score `Plan › Current state` (Partly) and `Plan › What that will do` (Partly).

**Regression risks:** a default that steers toward a more expensive choice — the rule must be written down in the
rung's handoff note.

**Visual re-audit:** yes. **Effort:** S **Risk:** Low.

---

### `Rung W4` — Sources: one primary row action, the rest disclosed

**Problem being solved:** `H-4` (RC-D). Six actions per row, a red irreversible one adjacent to a reversible one,
× 1,348 rows.

**Affected surfaces:** Sources.

**Proposed change:** one primary action per row by task context; secondary actions behind an overflow control;
"Delete everywhere" behind a confirmation scaled to its irreversibility and never adjacent at equal weight to
"Remove from project". `DESIGN.md` §5 (danger role) governs the treatment. Per `DESIGN.md` §3's progressive-
disclosure rule (common actions stay close to the result), if the audit instance's twenty-row bulk-review baseline
shows a second action used on a large share of rows (e.g. Retry on the current `Failed` filter), that action is a
second visible control on the row, not folded into the overflow with the genuinely rare ones — collapsing to
exactly one visible action is not itself the goal.

**Precondition:** W1 landed, **and** F0's interaction walk of Sources exists — this rung does not ship on
observation alone.

**Non-goals:** what any action does is unchanged; the add-source panel's placement (`M-7`) is P1.

**Seam:** `srcRowHtml`, `renderBook`, the static `#view-sources` row template.

**Gates.** *Deterministic:* `test_s44` (handlers), `test_s50` (row markup is the single largest inline-style
source), `test_s5`, `UI_VERSION`. *Behavioral:* on the audit instance every one of the six actions still performs
the same operation with the same consequence and reversibility from its new position; a bulk-review pass of
twenty rows is timed **before** the rung — several runs if the numbers are noisy, recorded in the rung's handoff
note as the baseline — and again after. A material regression against that recorded baseline fails the rung; no
threshold is set before the baseline exists. *Human:* re-score `Sources › What matters` (No)
and `Sources › What to do next` (No). Expected: toward Partly or Yes; the Findings row density strength must be
matched, not traded away.

**Regression risks:** slowing a power user's bulk workflow — the timing gate exists for this.

**Visual re-audit:** yes, plus the interaction walk. **Effort:** M **Risk:** Medium.

---

### `Rung W5` — Home and the status line: attention before totals

**Problem being solved:** `H-1`, `M-1`, `M-2`, `M-3` (RC-A, RC-F).

**Affected surfaces:** Home; the Chat sidebar footer (shares the status component).

**Proposed change:** a status component with independently legible parts (health, today's spend, period spend)
ordered by what needs noticing first — `DESIGN.md` §5 stat-tile and §8 Home direction apply; project cards gain a
last-activity/attention signal; the stat block is subordinated to project titles; the whole card is the click
target.

**Precondition:** W1 landed (the status line contains an instruction — "use Re-check" — that W1's vocabulary
governs). Sequenced last among W-rungs because it has the widest layout scope and the least dependency on the
others.

**Non-goals:** no cross-project search, sort or archive (a scale question not evidenced at 13 projects).

**Seam:** Home card markup, `renderWizard`/`funCard`, the status-line renderer used by both Home and the Chat
sidebar footer.

**Gates.** *Deterministic:* `test_s44`, `test_s5`, `test_s50`, `UI_VERSION`; the status component renders the same
three numbers the current sentence does (a test comparing its DOM to the `/api/…` status payload). *Behavioral:*
card-body click navigates (a `test_s44`-style handler check plus an audit-instance click); Re-check performs the
same health probe with the same consequence. *Human:* re-score `Home › Where am I` (Partly), `Home › Current state` (No), `Home › What matters`
(No), `Chats › Current state` (Partly).

**Regression risks:** ordinary layout risk; nothing priced or destructive is touched.

**Visual re-audit:** yes, both themes (the status colours matter here). **Effort:** M **Risk:** Low.

---

## Component consistency

### `Rung C1` — One badge/pill primitive, roles distinguishable; Findings rows to two badges

**Problem being solved:** the styling half of `H-3`/`H-5`/`H-6`, and `M-4`/`M-6`. Pills serve four roles (status,
filter, chip-input, metadata) with one look; Findings rows carry four to five badges.

**Affected surfaces:** Findings rows and sidebar badge, Sources filter chips, Research/Plan chip answers, the
version tag.

**Proposed change:** one primitive with a distinct treatment per role (`DESIGN.md` §5 badges); Findings rows show
two badges by default, the rest folded into the meaning line or expansion.

**Precondition:** W1–W5 landed and a cross-cutting RE-AUDIT done (see sequencing).

**Non-goals:** what a badge conveys is unchanged.

**Seam:** shared badge rules; Findings row template; the sidebar `.n` count badge.

**Gates.** *Deterministic:* `test_s50`; `test_s44`, `test_s5`, `UI_VERSION`. *Behavioral:* filters still filter,
chip answers still submit. *Human:* re-score `Findings › What matters` (from W2's after-state) and check the
Findings density strength against the `evidence/` before-image.

**Visual re-audit:** yes. **Effort:** M **Risk:** Low.

---

## Polish

### `Rung P1` — Small independent fixes, folded into whichever rung is already in the file

`L-1` – `L-5`, `M-7`, `M-9`, `M-10`, `M-11`. No shared change; each is fixed inside the rung that already touches
that surface, never as a standalone commit. Gates are the touched rung's gates. If two items want the same fix,
that fix belongs in W1 or C1, not here. **Effort:** S aggregate **Risk:** Low.

---

## Sequencing

F0 → [F0 close-out report: does the new evidence change the ladder?] → F1 → F2 → W1 → W2 → W3 → W4 → W5 →
[cross-cutting RE-AUDIT] → C1 → P1.

F1 and F2 may run in parallel once F0's close-out report has been given and the ladder patched if it needed to be. W1 waits for F1. W2 and W3 wait for W1; W4 waits for W1 and for F0's
Sources walk. After W5, one RE-AUDIT across every touched surface, against the `evidence/` baseline, before C1 —
to catch a consequence that five workflow rungs propagated without anyone noticing. Each rung leaves a handoff note
naming the next incomplete rung (`DESIGN-MISSION.md`, acceptance evidence).

**Cross-cutting RE-AUDIT: done, 2026-09-14 (`reaudit.md`).** Every `H`/`M` finding tied to F1, F2, W1–W5 verified
RESOLVED live on the audit instance (dark theme; light theme covered per-rung at landing), except `M-3`, closed
NO LONGER APPLICABLE. No new regression found. `C1`'s precondition is satisfied — `C1` is next.
