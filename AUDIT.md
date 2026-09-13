# AUDIT.md

# Neuro Search Design Audit System

## Purpose

This file defines a repeatable design audit system for Claude Code, Codex, or another capable coding agent working inside the Neuro Search repository.

This is not a prompt asking an AI whether the UI is "good." It is an inspection protocol for understanding how the product actually behaves, how it communicates that behavior to a user, where the interface drifts from its own system, and which changes would create meaningful product improvement.

The audit has two distinct jobs:

1. **Product Experience Audit**: inspect the live application, real workflows, content, interaction states, information architecture, UX, accessibility, responsiveness, perceived performance, and the code/mechanics behind what the user experiences.
2. **Design-System Drift Audit**: inspect whether the same semantic roles are represented consistently across screens, whether tokens/components/patterns are applied consistently, and whether local exceptions have accumulated into an incoherent interface.

The first job asks whether the product works brilliantly for the user. The second asks whether the product consistently follows its own design language.

They are related, but they are not the same audit.

---

# 1. Core operating principles

## 1.1 Audit reality, not intentions

The current rendered product is the object being audited.

Documentation explains intent. Code explains implementation. Tests explain protected contracts. The live interface shows the truth the user actually experiences.

Do not declare a flow good because the code is elegant. Do not declare a control functional because a handler exists. Do not declare a state understandable because its internal model is sophisticated.

Whenever possible, inspect all four layers:

```text
PRODUCT INTENT
    ↓
IMPLEMENTATION
    ↓
RENDERED / INTERACTIVE EXPERIENCE
    ↓
USER CONSEQUENCE
```

When those layers disagree, the disagreement is itself an audit finding.

## 1.2 Evidence first, diagnosis second, redesign third

Do not begin by redesigning screens.

First collect evidence. Then diagnose. Then consolidate root causes. Only then propose improvement directions.

Aesthetic instinct is not sufficient evidence for a product change.

## 1.3 Capture everything before editorializing

The first audit artifact should be intentionally detailed and imperfect.

Do not prematurely compress the audit into ten attractive bullets. Preserve awkward details, local inconsistencies, unanswered questions, overlapping observations, screenshots, code references, interaction notes, and edge cases.

The synthesis pass happens later.

## 1.4 User intent comes before visual styling

For every major surface, first determine:

- Why did the user come here?
- What are they trying to understand or accomplish?
- What is the primary decision or action?
- What should they notice first?
- What can remain hidden until needed?
- What must never be hidden?

Do not start with colors, cards, icons, or animation.

## 1.5 Progressive disclosure over exposed machinery

Show meaning before metadata.

Show the problem before the diagnostic.

Show the recommended action before advanced controls.

Aggregate machine-generated complexity before presenting it.

A large corpus or advanced feature set should make the user feel more informed, not more burdened.

## 1.6 Outcome labels over implementation labels

A user-facing control should communicate:

- what will happen;
- why they might want it;
- whether it costs money;
- whether it is reversible;
- whether it changes project state;
- whether it changes what Chat, Research, Discover, Planner, or another surface may use later.

A control named after an internal operation is suspicious until proven understandable.

## 1.7 Honest states

Loading, queued, working, complete, stale, partial, failed, unavailable, unknown, and empty are different states.

Never allow the interface to imply success when work merely queued.

Never show zero when the real state is unknown.

Never let a silent delay look like a dead control.

Never let a failure look like a legitimate answer.

## 1.8 Real content is the test

Do not audit only pristine states.

The product must survive:

- long titles;
- large projects;
- thousands of findings or claims;
- missing metadata;
- failures;
- partial results;
- empty states;
- stale data;
- mixed states;
- long explanations;
- unusual source types;
- narrow screens;
- slow operations;
- disabled actions;
- conflicting evidence;
- old browser tabs or stale UI state where applicable.

## 1.9 Substantial improvement over cosmetic churn

The audit should prefer changes that remove a class of problems.

A systemic improvement is more valuable than twenty isolated style edits.

Examples:

- clarifying one global action pattern instead of renaming one button;
- defining one status system instead of restyling one badge;
- fixing information architecture instead of shrinking a crowded card;
- consolidating three review mechanisms into one understandable workflow instead of polishing all three separately;
- making a shared control component consistent instead of patching each screen independently.

## 1.10 Audit and implementation are separate phases

**Default behavior: do not modify the product during the audit.**

The audit should produce evidence and an improvement ladder.

Implementation begins only when explicitly instructed to implement the approved audit ladder or a selected subset of findings.

This prevents a diagnosis from mutating the object being diagnosed halfway through the review.

---

# 2. Neuro Search ground truth and safety

Before auditing Neuro Search, orient to the current repository rather than trusting an old mission document.

`DESIGN.md` states what good Neuro Search design is; this file checks whether the implementation follows it. Read
`DESIGN.md` before judging any surface - a finding that contradicts it is a finding about `DESIGN.md`, and belongs
in the audit as such rather than as a silent deviation.

Read the current front-door material first, especially:

- `STATE-OF-THE-APP-*.md` or its current replacement;
- `CLAUDE.md`;
- `HANDOFF.md`;
- `README.md` when useful;
- relevant current tests;
- current implementation of the surfaces under audit.

Use historical mission documents to understand design intent and hard-won reasoning, not as proof that the current product still behaves that way.

### Hard rule: do not open the live SQLite database from an external session

Use the running application's API, supported CLI paths, or a safe copied backup according to the repository's current rules.

Do not create a "design audit shortcut" that bypasses this.

### Hard rule: the audit does not spend money or change the user's research

Phase 3 walks workflows that add sources, queue work, accelerate jobs and recover from failures. On the live
instance those are real downloads, real transcription, real paid calls and durable changes to Kyle's projects.

- **Live instance: read-only.** Navigate, open, filter, expand, sort, resize, screenshot. Do not click any control
  that queues work, spends money, changes status, approves, dismisses, retires or deletes. The live instance is
  where scale, real content and real accumulated state are observed, and nowhere else.
- **Audit instance: interactions.** A second app with a private `NEUROSEARCH_DATA_DIR` restored from a copied
  verified backup, `NEUROSEARCH_FAKE_AI=1` (or a zero daily budget), on a different port. Never a second server
  against the live data directory. Every click-through in Phase 3 happens there. The procedure is tracked (a tiny
  generic launcher or a documented command — no framework); the copied database, private data directory, tokens,
  cookies and machine-private state are gitignored and never tracked, so a RE-AUDIT can recreate the instance
  from the repository alone.
- If the audit instance cannot be started, each affected workflow is reported as **observed, not exercised**. Do
  not silently downgrade a walk to a code reading and present it as a walk.

### Do not introduce parallel architecture during a design fix

If the audit later recommends implementation, fixes must extend existing product systems rather than inventing parallel ingestion, research, job, provenance, state, cost, or memory paths.

### Respect intentional product constraints

Do not file these as defects merely because another product might choose differently:

- local-first operation;
- single-user behavior when that remains the stated current product model;
- explicit confirmation before spending money;
- deep evidence/provenance under the hood;
- deliberate preference for correctness and auditability over superficial speed.

The design question is whether these constraints are communicated and usable, not whether they exist.

---

# 3. Audit modes

This file supports four modes.

## FULL AUDIT

Audit the complete current product.

Deliver, into `docs/design-audit/<YYYY-MM-DD>-<short-sha>/`:

- `raw.md`
- `audit.md`
- `ladder.md`
- `evidence/` for screenshots — one `baseline/` set of canonical before-states (roughly one image per surface and
  important state, both themes), at most one `current/` comparison set, and a short `manifest.md`. Accepted changes
  replace superseded baseline images; a historical image is retained only when a documented regression names it.

The repository root keeps only `AUDIT.md` and `DESIGN.md`; audit output never lands there.

Do not implement.

## TARGETED AUDIT

Audit one surface, workflow, or design-system dimension while still checking its dependencies and cross-product effects.

Examples:

- Research
- Findings review
- Sources
- Discover
- Chat
- Master Planner
- Jobs / progress / cost feedback
- Project creation
- Design-system consistency
- Mobile/narrow viewport behavior

Do not treat a targeted audit as permission to ignore affected upstream or downstream surfaces.

## DRIFT AUDIT

Audit design-system consistency only.

Use Figma if a reliable current file and system exist. Otherwise audit the implemented UI and code-side tokens/components/patterns.

A drift audit checks conformance. It does not replace the Product Experience Audit.

## RE-AUDIT

Revisit a previous audit after fixes.

Do not infer resolution from commits alone. Reproduce the original user-visible condition and mark each finding:

- RESOLVED
- PARTIALLY RESOLVED
- UNCHANGED
- REGRESSED
- NO LONGER APPLICABLE
- CANNOT VERIFY

Then inspect for new problems introduced by the fix.

---

# 4. Required evidence sources

Use every evidence source that is materially available.

## 4.1 Live visual inspection

Use the environment's browser or computer-control capability to inspect the rendered application.

For important screens and workflows:

- navigate the real app;
- click actual controls;
- observe feedback and state transitions;
- resize the viewport when possible;
- capture screenshots when useful;
- inspect dialogs, drawers, expanded states, errors, empty states, loading states, and disabled states;
- revisit screens after state changes.

If an accessibility-tree or DOM snapshot tool already exists in the environment, use it to complement screenshots and identify controls precisely.

Do not install a new audit stack solely for this review unless explicitly authorized.

If visual/browser access is unavailable, state that limitation clearly. Do not claim a complete visual audit from code inspection alone.

## 4.2 Code inspection

Inspect the code responsible for material findings.

The purpose is not to grade code style. It is to determine whether a visible symptom is:

- a local rendering defect;
- a repeated component/pattern defect;
- an information architecture problem;
- a state-model mismatch;
- a backend/API contract issue;
- a performance problem;
- a stale-state problem;
- duplicated logic;
- a missing shared primitive.

When useful, include file/function references in the audit.

## 4.3 Product documentation and tests

Use current docs and tests to identify:

- intended behavior;
- locked invariants;
- known limitations;
- deliberately rejected approaches;
- regressions the product already learned from;
- terminology that should or should not reach the user.

Do not suggest a "fix" that reintroduces a previously measured failure without new evidence.

### Protected contracts a UI change inherits

Any ladder rung that touches `neurosearch/web/index.html` inherits all of these. Name them in the rung and run
them before delivery:

- `tests/test_s44_frontend_integrity.py` - unique static DOM ids; every inline handler names a declared function;
  no duplicate column-zero global declarations; exactly one `fetch(` so every first-party request passes the
  version boundary.
- `tests/test_s5_ui_syntax.py` - UI syntax gate.
- `tests/test_s50_design_drift.py` - the design drift ratchet (inline styles, colour literals outside the token
  blocks, distinct font sizes, distinct radii, emoji-only controls). Counts may fall, never rise.
- The `UI_VERSION` handshake: a changed `index.html` ships with a version bump in all three version sites, or
  every open tab silently runs a stale UI against a newer server.
- Click acknowledgement and sustained busy state (0.63.32-0.63.34) must survive any restyle.
- Request-path purity: a read-only surface must not start a job, a model call or a provider health probe.

## 4.4 Existing measurements

Use current measurements when they exist.

Examples:

- endpoint timing;
- payload size;
- source/finding/claim counts;
- queue latency;
- click acknowledgement;
- cost;
- actual error frequency;
- known stress-case scale.

Do not invent analytics, user behavior, conversion data, or frequency numbers.

Clearly label assumptions.

---

# 5. Audit sequence

Follow this order unless a genuine environment constraint forces a change.

## Phase 0: Baseline and scope

Record:

- current version / commit if available;
- audit date;
- audit mode;
- **admission path** for any implementation the ladder will propose: Foundation UI scope (client/server
  compatibility, handler integrity, console errors, interaction acknowledgement) or a CEO override under
  `DEVELOPMENT-OPERATING-SYSTEM.md` SS13 with its collision analysis. The audit itself is always allowed; its
  treatment rungs are not automatically admitted, and a ladder nobody can admit is wasted work;
- **which instance was used for what**: the live instance (read-only observation) and the audit instance
  (interaction), with the audit instance's data-dir provenance and AI/budget settings;
- available visual/browser capability;
- viewport sizes used;
- projects / fixtures used as test cases;
- major limitations of the audit environment;
- relevant known product constraints.

Confirm the app is functional enough to audit before treating symptoms caused by a broken environment as product findings.

## Phase 1: Build the product map

Before judging screens, inventory the current product.

For every major surface, capture:

| Field | Question |
|---|---|
| Surface | What is it called? |
| User intent | Why would someone come here? |
| Primary question | What should this surface answer quickly? |
| Primary action | What is the most important thing a user may do here? |
| Secondary actions | What else can happen? |
| Entry points | How does a user get here? |
| Exit / next step | Where should the workflow naturally continue? |
| Main states | Empty, loading, working, success, partial, error, stale, etc. |
| Scale risk | What happens at 1, 20, 500, 5,000+ relevant objects? |
| Cost / consequence | Can actions spend money or change durable state? |
| Dependencies | What other surfaces consume or modify this state? |

Do not assume the navigation labels accurately describe the job each screen performs.

## Phase 2: Cold first-time-user walk

Pretend you did not build Neuro Search.

Do not use hidden architectural knowledge to excuse unclear UI.

From the interface alone, ask repeatedly:

1. Where am I?
2. What is this for?
3. What should I pay attention to?
4. What should I do next?
5. What happens if I do nothing?
6. What will this button do?
7. Will it cost anything?
8. Can I undo it?
9. Did my action work?
10. Where did the result go?
11. What does this status mean?
12. Is this a problem, information, or a decision I need to make?

Record every moment where the answer depends on builder knowledge.

### The five-second scorecard

`DESIGN.md` SS1 sets the five-second test. Score it per surface, in a table, so the result is comparable across
surfaces and re-measurable in a later RE-AUDIT:

| Surface | Where am I | Current state | What matters | What to do next | What that will do |
|---|---|---|---|---|---|

Each cell is **Yes / Partly / No** plus the one observation that decided it. This is a structured human UX
evaluation, not a measurement: it is re-scored by a person after a change and recorded before → after, alongside —
never instead of — the deterministic gates in §4.3. It belongs in both `raw.md` and `audit.md`.

## Phase 3: Walk load-bearing workflows end to end

Component correctness does not prove workflow quality.

Audit complete workflows, including the handoffs between surfaces.

At minimum, when currently available, walk:

### Project creation

```text
create project
→ understand starting state
→ add/refine context
→ see existing research or empty state
→ know next action
```

### Add / acquire research

```text
add URL/file/source
→ classify / review if needed
→ queue / process
→ observe progress
→ recover from a failure or browser-needed state
→ source becomes usable
→ understand what value was produced
```

### Findings review

```text
new findings exist
→ user notices attention state
→ enters review
→ understands why review is needed
→ distinguishes useful / duplicate / stale / low-value cases
→ acts safely
→ sees consequence
```

### Research

```text
open Research
→ understand current state
→ identify what needs attention
→ inspect an open question / watch-out / area
→ take the recommended action
→ understand free vs paid path
→ see state improve
```

### Chat

```text
ask evidence-based question
→ understand active progress
→ receive answer
→ inspect source/evidence when needed
→ identify uncertainty or gap
→ move into deeper research if desired
```

### Discover

```text
need more evidence
→ understand why new research is needed
→ see library / known / external candidates appropriately
→ understand why each candidate matters
→ add or dismiss
→ see acquisition state
```

### Planner

```text
open plan
→ understand current recommendation
→ distinguish plan state from research uncertainty
→ follow blocked/research-dependent items
→ see plan react to meaningful project changes
```

### Work / jobs / cost feedback

```text
start meaningful background work
→ understand it queued
→ understand what is active
→ understand local vs paid path where relevant
→ see progress
→ distinguish slow from stuck
→ understand failure
→ recover or accelerate intentionally
```

For each workflow inspect:

```text
entry
→ orientation
→ action
→ feedback
→ durable consequence
→ downstream effect
→ failure path
→ recovery
→ return / continuation
```

## Phase 4: Screen-by-screen product experience audit

For each major surface, audit only the dimensions that materially apply.

### A. Intent and mental model

- Is the purpose obvious?
- Does the surface correspond to one coherent job or several unrelated jobs?
- Are internal concepts exposed before a user needs them?
- Does the surface answer the user's likely question quickly?

### B. Information architecture

- Is primary information visually and structurally primary?
- Are secondary details progressively disclosed?
- Are actions near the information they affect?
- Are related tasks grouped?
- Are unrelated tasks separated?
- Is navigation based on user jobs rather than backend modules?

### C. Hierarchy and scanability

- Can the user tell what matters in roughly five seconds?
- Is the primary action obvious but not noisy?
- Are counts supporting information rather than the entire interface?
- Does typography express hierarchy consistently?
- Are cards/panels being used because they clarify structure or simply because they are available?

### D. Density and calmness

Target **calm density**: information-rich, compact, and understandable without becoming visually frantic.

Look for:

- giant cards containing little value;
- oversized headings that reduce usable space;
- excessive whitespace that pushes actions below the fold;
- dense walls of controls with no hierarchy;
- repeated metadata competing with the actual decision;
- long unbounded lists;
- too many simultaneous calls to action;
- detail that should live in an inspector, drawer, expander, or secondary view.

Do not solve density only by making fonts smaller.

### E. Action semantics and affordance

For every meaningful control ask:

- Can a first-time user predict the result?
- Is the label an outcome or an implementation term?
- Is the primary action visually distinct?
- Is destructive behavior visually and textually clear?
- Are disabled controls explained when necessary?
- Are irreversible or costly actions appropriately disclosed?
- Does the interface acknowledge the click immediately?

### F. State and feedback

Audit:

- loading;
- queued;
- running;
- partial;
- success;
- empty;
- disabled;
- stale;
- needs review;
- warning;
- recoverable failure;
- terminal failure;
- offline/unavailable if applicable.

For each, ask whether the user can tell what is happening and what they can do next.

### G. Terminology and copy

- Does the interface use human language rather than architecture language?
- Does the same term mean the same thing everywhere?
- Are two independent concepts accidentally collapsed into one label?
- Does helper text explain consequence, not restate the button?
- Are warnings actionable?
- Are technical details available without dominating the default experience?

### H. Navigation and continuity

- Do links land in the correct filtered/contextual state?
- Does the next screen preserve the reason the user went there?
- Does back navigation preserve useful state?
- Does a cross-product action feel like one workflow or a context reset?

### I. Accessibility

Inspect materially applicable concerns:

- semantic control roles;
- labels;
- keyboard reachability;
- visible focus;
- contrast;
- text readability;
- touch/click target size;
- color not being the only signal;
- motion/reduced-motion behavior where relevant;
- modal/dialog focus and dismissal;
- error association with inputs;
- screen-reader or accessibility-tree clarity when tooling allows.

Do not claim WCAG conformance unless it was actually measured against the relevant requirements.

### J. Responsive behavior

Test realistic widths when possible.

Do not merely shrink the desktop view.

**Severity cap.** Mobile is deliberately deprioritised for this product: UI and flow clarity come first. A
narrow-viewport finding is capped at Medium unless a desktop workflow is also broken, or the layout is unusable
rather than merely cramped.

Check:

- navigation;
- control wrapping;
- table/list behavior;
- long labels;
- dialogs/drawers;
- primary-action reachability;
- filters;
- horizontal overflow;
- readable line length;
- inspector behavior;
- whether density adapts appropriately.

### K. Perceived performance

Audit what the user experiences, not only backend timing.

Check:

- click acknowledgement;
- progress narration;
- skeleton/loading behavior;
- whether content disappears unnecessarily during refresh;
- layout shifts;
- whole-screen re-renders;
- polling-induced flicker;
- whether long work exposes meaningful progress;
- whether slow and stuck are distinguishable.

If performance is a significant UX finding, inspect current measurements before prescribing infrastructure.

### L. Trust and transparency

Neuro Search asks users to trust evidence, AI processing, background work, and cost decisions.

Check whether the UI makes material truth visible:

- where evidence came from when needed;
- whether evidence is current;
- whether something is uncertain;
- whether something is a user decision vs system inference;
- whether processing is complete;
- whether an action may spend money;
- whether local/free and paid paths are honestly represented;
- whether failures and substitutions are visible when consequential.

### M. Real-content resilience

Stress the design using real and ugly content.

Check:

- very long titles;
- missing thumbnails;
- missing descriptions;
- large counts;
- many groups;
- long summaries;
- many status badges;
- zero results;
- only one result;
- thousands of results;
- mixed successful/failed items;
- historical and current content together.

### N. Non-applicable checks

Do not mechanically audit irrelevant categories.

Example: SEO is not a meaningful quality dimension for a private local application unless a public web surface is actually in scope.

The objective is material completeness, not checklist inflation.

## Phase 5: Design-system drift audit

Run this as a separate lens after understanding user intent.

The question is not "does everything look identical?" The question is "does the interface use a coherent visual and interaction language?"

Inventory the system that actually exists.

### Record the numeric drift baseline

Prose cannot show movement. Measure these against `neurosearch/web/index.html` and put the table in `audit.md`;
`tests/test_s50_design_drift.py` holds the same counts as a ratchet:

| Measure | How |
|---|---|
| inline `style="` attributes | static markup and JS template strings |
| colour literals outside the token blocks | hex/rgba in CSS and in JS |
| distinct `font-size` values | against the six-step scale in `DESIGN.md` |
| distinct `border-radius` values | against the four-step scale |
| controls whose only glyph is an emoji | buttons and links |
| icon-only controls with no accessible name | missing `aria-label`/`title` |
| tokens defined in one theme only | a light-only value is a dark-theme defect |

Each is one grep. Report the number, the direction against the recorded baseline, and the worst three offending
surfaces - not a list of every occurrence.

### Check tokens and primitives

Where implemented, inspect consistency of:

- spacing;
- typography;
- color;
- radius;
- border;
- elevation/shadow;
- panel treatment;
- icon sizing/style;
- control heights;
- focus treatment;
- motion/transition timing;
- breakpoints;
- density rules.

### Check semantic components

Compare all instances of:

- primary buttons;
- secondary buttons;
- destructive buttons;
- icon buttons;
- links;
- tabs;
- segmented controls;
- search;
- filters/chips;
- text inputs;
- selects;
- checkboxes;
- menus;
- dialogs;
- drawers/inspectors;
- cards;
- tables/lists;
- badges/status pills;
- alerts;
- toasts;
- empty states;
- loading states;
- errors;
- pagination/load-more controls.

For each semantic role, ask:

- Is the same role represented consistently?
- Are different roles visually distinguishable?
- Have one-off local styles drifted from shared patterns?
- Are there duplicated patterns that should be one component or token?
- Is an intentional exception documented by context, or merely accidental?

### If Figma exists

There is no authoritative Figma system for Neuro Search today; the implemented UI is the design system. If a
current authoritative file ever exists, compare implementation against it and record uncertainty where the source
of truth is unclear. Do not treat a stale or partial file as truth, and do not file its absence as a defect.

## Phase 6: Cross-surface interaction audit

After screen-level review, inspect combinations.

Look for defects that emerge only when individually-correct parts interact.

Examples relevant to Neuro Search include:

- background work × progress UI;
- cost controls × acceleration UI;
- project state × Chat behavior;
- evidence status × Planner readiness;
- Findings status × Claims visibility;
- stale source state × review actions;
- global library reuse × project isolation;
- filtering × grouping × pagination;
- grouping × sort order;
- live polling × open drawers/forms;
- stale browser UI × current server;
- browser capture × original job state;
- empty/partial research state × Overview recommendations;
- local AI failure × paid fallback messaging;
- large resultsets × default rendering;
- terminology in Research × terminology in Chat/Discover/Planner.

Do not assume two correct components create a correct workflow.

## Phase 7: Root-cause consolidation

The raw audit may contain many symptoms.

Before prioritizing, group findings by likely root cause.

Example:

```text
SYMPTOMS
- three pages use different names for the same status
- one button says Refresh, another says Rebuild, another says Re-run
- cost consequence appears on only one surface

ROOT CAUSE
No shared user-facing action/state vocabulary for reprocessing.

SYSTEMIC DIRECTION
Define one action/state contract and apply it to every affected surface.
```

Prefer one consolidated correction package over a sequence of isolated patches when the dependency is already visible.

For each root cause, identify every affected surface before calling the proposed change complete.

## Phase 8: Materiality filter

Do not inflate the report with every subjective preference.

A finding is material when leaving it unchanged can reasonably cause one or more of:

- user cannot complete or discover a core workflow;
- user takes the wrong action;
- user misunderstands durable state;
- user cannot tell what needs attention;
- user cannot predict an action's consequence;
- user may spend money without sufficient clarity;
- system failure looks like success or inactivity;
- important uncertainty is hidden;
- consequential information is visually buried;
- repeated friction across normal use;
- major accessibility barrier;
- poor behavior at realistic product scale;
- substantial visual/system inconsistency;
- loss of trust;
- high implementation maintenance caused by duplicated UI logic;
- likely future regressions because a shared primitive is missing.

Aesthetic preference alone is usually a low-severity observation unless it harms hierarchy, consistency, readability, trust, or task completion.

## Phase 9: Fixed-point closure pass

After consolidating the audit and proposed directions, perform another pass over the audited product and the report.

Look for:

- contradictions between recommendations;
- one proposed fix that makes another workflow worse;
- duplicate findings that are actually the same root cause;
- a root cause whose consequences were not propagated to every affected surface;
- stale references to behavior that changed during the audit period;
- recommendations that conflict with current product invariants;
- recommendations that accidentally introduce parallel architecture;
- acceptance criteria that do not actually prove the proposed improvement.

Repeat the affected review until one closure pass produces no new material finding or unpropagated consequence.

This is a review-completion criterion, not a claim that future audits will never find more.

---

# 6. Finding format

Every material finding in the polished audit should use this structure.

## `[ID] Short problem statement`

**Severity:** Critical / High / Medium / Low  
**Scope:** Systemic / Cross-surface / Workflow / Local  
**Confidence:** High / Medium / Low  
**Evidence:** Runtime / Visual / Code / Test / Documentation / Measurement  
**Affected surfaces:** ...

### What I observed

Concrete behavior only.

### Why this matters

State the user consequence, not merely the design principle being violated.

### Reproduction / location

How to see it again. Include screen/control names and screenshot or code references when available.

### Likely root cause

Explain whether this appears local or systemic. Mark uncertainty honestly.

### Improvement direction

Describe the outcome to achieve. Do not jump straight to arbitrary pixels or a complete redesign unless evidence supports it.

### Acceptance test

Describe observable before/after behavior that would prove the issue improved.

### Propagation

List other screens/components/workflows that must be checked if this root cause is fixed.

---

# 7. Severity and prioritization

Severity and implementation priority are related but not identical.

## Critical

Use sparingly.

Examples:

- core workflow cannot be completed;
- UI communicates materially false state;
- destructive/costly behavior is dangerously unclear;
- severe accessibility blocker on a core path;
- failure is indistinguishable from success.

## High

Examples:

- repeated confusion in a core workflow;
- major information hierarchy failure;
- users cannot tell what to do next;
- important state/consequence is hidden;
- severe scale failure on real projects;
- systemic design drift affecting many screens.

## Medium

Examples:

- meaningful friction;
- inconsistent interaction pattern;
- weak hierarchy on a secondary task;
- non-blocking responsive/accessibility issue;
- avoidable duplication or local inconsistency.

## Low

Examples:

- polish;
- minor spacing/alignment inconsistency;
- isolated copy improvement;
- aesthetic refinement with limited workflow effect.

## Priority ladder

When creating `design-audit-ladder.md`, rank work using these factors:

1. **User impact**: how much the problem harms understanding, trust, or task completion.
2. **Reach**: one edge state vs many screens/core flows.
3. **Frequency**: likely every session vs rare edge case, only when evidence exists.
4. **Leverage**: whether one root fix eliminates many symptoms.
5. **Confidence**: strength of runtime/evidence support.
6. **Implementation risk**: probability of damaging hardened behavior.
7. **Effort**: rough relative effort, not fake precision.

Prefer high-impact, high-leverage, well-evidenced fixes.

Do not prioritize merely because something is visually easy to change.

---

# 8. Required audit deliverables

## 8.1 `design-audit-raw.md`

This is the exhaustive evidence notebook.

It should be intentionally messy and detailed.

Include:

- screen inventory;
- workflow notes;
- screenshots or screenshot references;
- accessibility-tree/DOM observations where available;
- code references;
- state inventories;
- duplicate or overlapping observations;
- questions;
- possible root causes;
- inconsistencies;
- edge cases;
- measurements;
- assumptions;
- things that looked suspicious but were later disproven.

Do not remove detail to make this file elegant.

Do not change the product while creating it.

## 8.2 `design-audit.md`

This is the reviewed, evidence-backed audit.

Recommended structure:

```text
# Design Audit

## Executive summary
- what the product does well
- the 3 to 7 biggest experience problems
- the major systemic pattern behind them

## Audit scope and limitations

## Product map

## Critical findings

## High-priority findings

## Medium findings

## Low / polish findings

## Design-system drift

## Workflow findings

## Accessibility / responsive findings

## Performance-as-experience findings

## Root-cause map

## Strengths worth preserving

## Assumptions / cannot verify
```

Do not turn the polished report into a vague executive summary. Preserve enough evidence for another engineer or model to reproduce the conclusions.

## 8.3 `design-audit-ladder.md`

Convert the audit into an implementation sequence, but do not implement it yet.

Each rung should include:

- problem being solved;
- affected surfaces;
- proposed system-level change;
- why this rung comes before the next;
- explicit non-goals;
- implementation seam / likely modules or components;
- acceptance test;
- regression risks;
- tests or runtime checks required;
- whether visual re-audit is required;
- rough effort: S / M / L;
- risk: Low / Medium / High.

Prefer a small number of coherent rungs over dozens of micro-fixes.

The ladder should clearly distinguish:

- **system foundations**;
- **workflow / information architecture changes**;
- **component consistency changes**;
- **polish**.

Do not begin with polish if a structural problem makes the screen confusing.

---

# 9. What substantial improvement means

A recommendation is substantial when it produces an observable user improvement and has a clear acceptance condition.

Weak recommendation:

> Make the Findings page cleaner.

Better:

> Consolidate stale-source review, low-value finding review, and duplicate review into one Review workflow that explains why each item needs attention, separates system-detectable cleanup from user judgment, and exposes no bulk destructive action until the user understands the affected set.

Weak recommendation:

> Improve button styles.

Better:

> Define one shared action hierarchy for primary, secondary, destructive, state-toggle, and paid actions, then replace local button styling and labels across Research, Sources, Findings, Discover, and Jobs. A first-time user should be able to predict consequence and cost from label plus nearby microcopy.

Weak recommendation:

> Add more spacing.

Better:

> Move diagnostic metadata behind progressive disclosure and reserve the default card body for the user decision, reducing vertical height while improving scanability at 100+ items.

---

# 10. Things not to do

Do not:

- ask the model to simply "make the UI better";
- redesign based on taste before inspecting workflows;
- change the product during the audit;
- invent analytics;
- invent user complaints;
- call intentional local/single-user behavior a defect without context;
- apply SEO checks to a private local app merely because a website checklist includes SEO;
- treat accessibility as a single contrast check;
- declare visual quality from source code without seeing the rendered UI;
- treat a Figma file as authoritative if it is stale or incomplete;
- recommend a new framework because one screen is messy;
- propose infrastructure before checking measured bottlenecks;
- solve density by shrinking every font;
- solve inconsistency by making every component identical regardless of function;
- expose internal engine terminology merely for architectural purity;
- add confirmation modals everywhere;
- automate user judgment the product cannot safely infer;
- make claims of "final" or "perfect" after one audit;
- create a hundred-item backlog with no root-cause grouping.

---

# 11. Strengths must be recorded too

An audit that only produces criticism is dangerous because implementation may erase good behavior.

For every major surface, record the important strengths and constraints worth preserving.

Examples:

- progressive evidence disclosure;
- explicit cost consent;
- honest uncertainty;
- precise citation/provenance;
- useful compact density;
- good cross-surface continuity;
- effective grouping;
- fast perceived feedback;
- clear empty states;
- a design pattern that is already consistent and should become the standard.

The improvement ladder should explicitly name which strengths each rung must not regress.

---

# 12. Completion criteria for the audit

The audit is complete when all of the following are true:

1. The current product and version were identified.
2. The auditor inspected the live rendered product read-only, and exercised interactions on an audit instance,
   exactly as Phase 0 recorded. A run without browser access cannot tick this.
3. Major surfaces were inventoried by user intent, not only navigation name.
4. Load-bearing workflows were walked end to end.
5. Important states, including failure and empty states, were inspected.
6. Real-content and large-project behavior was tested where available.
7. Major findings contain reproducible evidence.
8. Design-system drift was audited separately from general UX judgment.
9. Cross-surface interactions were reviewed.
10. Raw observations were preserved in `design-audit-raw.md`.
11. Symptoms were consolidated into root causes in `design-audit.md`.
12. Recommendations were filtered for materiality.
13. A fixed-point closure pass found no new material unpropagated consequence in the current audit.
14. `design-audit-ladder.md` turns the biggest problems into coherent implementation rungs.
15. No product code was changed unless the user separately authorized implementation.

---

# 13. Invocation prompts

## Full audit

Use this exact instruction:

> Follow `AUDIT.md` in FULL AUDIT mode. Audit the current Neuro Search product as it exists now, using the live rendered application plus the current repository and tests. Do not change the product. Produce `design-audit-raw.md`, `design-audit.md`, and `design-audit-ladder.md`. Prioritize substantial, system-level improvements over cosmetic churn. Do not stop at generic UI/UX feedback. Reproduce important findings, connect them to their mechanics when useful, consolidate symptoms into root causes, and complete the closure pass required by `AUDIT.md`.

## Targeted audit

> Follow `AUDIT.md` in TARGETED AUDIT mode for **[SURFACE OR WORKFLOW]**. Inspect the live experience, the code behind material findings, and every upstream/downstream surface materially affected by this workflow. Do not change the product. Produce the raw audit, polished targeted audit, and a short implementation ladder.

## Design-system drift audit

> Follow `AUDIT.md` in DRIFT AUDIT mode. Audit the implemented interface against the current design system and shared component/token patterns. If an authoritative current Figma system is available, include it; otherwise use the implemented system as evidence. Find inconsistent semantic components, one-off styles, token drift, state drift, and responsive inconsistencies. Do not redesign the product and do not change code. Produce a drift inventory grouped by root cause and affected surfaces.

## Re-audit after implementation

> Follow `AUDIT.md` in RE-AUDIT mode using the previous audit as the baseline. Verify each implemented finding in the live product, not only in code. Mark it RESOLVED, PARTIALLY RESOLVED, UNCHANGED, REGRESSED, NO LONGER APPLICABLE, or CANNOT VERIFY. Then inspect the changed surfaces for new regressions and update the audit ladder accordingly.

---

# 14. Separate implementation handoff

After the audit is reviewed and implementation is authorized, create or use a separate mission based on `design-audit-ladder.md`.

The implementation agent should:

1. read the current repository and current audit artifacts;
2. verify the finding is still present before changing it;
3. implement the smallest coherent system-level fix;
4. propagate the fix to every affected surface named by the audit;
5. preserve locked product invariants;
6. add or update tests where behavior is testable;
7. visually re-check the live result;
8. run the repository's normal release gates;
9. update the audit finding with proof of resolution;
10. continue rung by rung rather than performing a giant visual rewrite.

The audit is the diagnosis. The ladder is the treatment plan. Implementation is a separate controlled operation.

