# Apple Design References for Neuro Search

*External reference sourcebook · added 2026-09-12*

## Purpose

This file gives `DESIGN.md`, `AUDIT.md`, design missions, Claude, Codex, and future reviewers a stable set of first-party Apple design references.

It is **reference material, not a replacement design system**. `DESIGN.md` remains Neuro Search's design source of truth. `AUDIT.md` remains the inspection protocol. Feature missions remain authoritative for feature behavior and information architecture.

Use Apple for principles, interaction judgment, writing discipline, hierarchy, familiarity, restraint, and craft. **Do not cargo-cult Apple aesthetics, copy platform chrome, or make Neuro Search imitate macOS/iOS.** Neuro is a dense research application with its own product model.

The goal is to learn from why Apple interfaces often make complicated systems feel simple while preserving access to power.

---

## 1. Human Interface Guidelines — Design principles

**Official source:**
https://developer.apple.com/design/human-interface-guidelines/design-principles

**Companion WWDC26 transcript:**
https://developer.apple.com/videos/play/wwdc2026/250/

Apple's current design-principles framework is:

- Purpose
- Agency
- Responsibility
- Familiarity
- Flexibility
- Simplicity
- Craft
- Delight

### Neuro-relevant interpretation

**Purpose** — every visible feature asks for time, attention, and trust. The interface should emphasize what actually helps the user accomplish the project's purpose. Choosing what *not* to expose is design work.

**Agency** — keep the user in control. Do not force unnecessary paths. Let people explore at their own pace. Make mistakes recoverable where possible. Confirm destructive actions rather than making every routine action defensive.

**Responsibility** — respect privacy, safety, data integrity, and the consequences of AI-assisted decisions. Neuro's evidence, provenance, cost, and uncertainty rules remain stronger and more specific than this general principle.

**Familiarity** — use recognizable conventions for ordinary actions. Things that look the same should behave the same. Distinctiveness should not make basic controls unpredictable.

**Flexibility** — support different contexts, content volumes, project states, viewport sizes, themes, and user needs without requiring one rigid flow to fit every situation.

**Simplicity** — Apple explicitly distinguishes simplicity from minimalism. Hiding everything in one place can make an interface visually minimal while making it harder to use. Simplicity means removing friction, using concise language, creating clear hierarchy, and reducing unnecessary steps.

**Craft** — details matter: typography, responsive feedback, performance, animation, consistency, and the quality of edge states all contribute to trust.

**Delight** — delight is not decorative flourish added afterward. It is the cumulative result of an experience feeling considered, human, understandable, responsive, and competent.

### Questions for Neuro

- Does this element earn the user's time and attention?
- Is the primary purpose obvious before secondary machinery?
- Did we make the interface simpler, or merely more minimal?
- Can the user predict what an action will do?
- Are common actions familiar and consistent?
- Does polish reinforce usefulness rather than decorate it?

---

## 2. WWDC26 — Principles of great design

**Official source:**
https://developer.apple.com/videos/play/wwdc2026/250/

This is the most concise first-party explanation of Apple's current design philosophy and should be the first external reference an agent reads when making a large Neuro UI judgment.

Particularly relevant ideas from the session:

- design is making something with intention, not merely making it look good;
- every feature consumes some combination of time, attention, and trust;
- deciding what not to include is part of design;
- agency means people should not be unnecessarily forced down predetermined paths;
- familiarity lets people reuse what they already know;
- simplicity is **not** the same as minimalism;
- concise interfaces use plain language and avoid redundancy;
- simplicity also means reducing the number of steps needed to get something done;
- clarity comes from hierarchy, order, spacing, and contrast;
- craft includes performance and responsive motion, not only visual styling;
- delight should emerge from the whole experience, not from confetti, decoration, or superficial animation.

### Neuro connection

This source directly supports the design balance Neuro needs:

> **Calm at first glance, powerful on demand.**

Progressive disclosure should hide secondary complexity without hiding the result or adding an interaction tax. A visually sparse interface that requires hunting is not simple. A dense interface that exposes every internal mechanism is not simple either.

---

## 3. WWDC22 — Writing for interfaces

**Official source:**
https://developer.apple.com/videos/play/wwdc2022/10037/

Apple presents a writing framework called **PACE**:

- Purpose
- Anticipation
- Context
- Empathy

### Purpose

Define the most important thing someone needs to know at that moment. Use information hierarchy to make it obvious. Decide what should remain, what can be removed, and what can move elsewhere. Give each screen and each multi-step flow a purpose.

### Anticipation

Think of the interface as a conversation. Anticipate the next action or question instead of explaining everything up front. Good design and good writing work together so the interface can say less.

### Context

Write for the moment in which information appears. Context can remove the need for explanatory copy. Alerts should be reserved for situations that genuinely deserve interruption. Destructive choices should name the exact action. Button labels should be understandable without relying on `Yes` / `No` or vague verbs.

Empty states should explain what is absent and what, if anything, the user can do next.

### Empathy

Use simple, plain language. Design copy and labels for accessibility, adaptable text, and people who may experience the interface differently. Avoid unnecessary idioms, jargon, or performative personality.

### Neuro microcopy rule

Context should do most of the explaining. UI copy should not repeat what layout, state, and surrounding content already communicate.

Prefer:

- `18 sources found` → `Review`
- `Failed` → `Retry`
- `4 questions open` → `Continue`

over explanatory paragraphs that repeat the visible state.

Shorter is not automatically better. A short label is good only when the surrounding context makes its consequence predictable.

---

## 4. WWDC17 — Essential Design Principles

**Official source:**
https://developer.apple.com/videos/play/wwdc2017/802/

This older session remains useful because it explains the human needs beneath interface technique.

Apple frames well-designed experiences around practical and emotional needs including safety/predictability, meaning/understanding, achievement, and beauty/joy.

Particularly relevant to Neuro:

- people should be able to predict the consequences of actions;
- interfaces should feel stable, solid, and trustworthy;
- information should help people make informed choices;
- workflows should be streamlined so people can accomplish tasks efficiently;
- internal consistency makes a product feel deliberate and whole;
- consistent glyphs, typography, sizing, color, and behavior create a sense of integrity;
- design exists to serve the human being, not to demonstrate design technique.

### Neuro connection

This reinforces why Neuro's evidence state, cost state, stale/current state, loading state, failures, and action semantics are design concerns rather than backend details. Trustworthiness is part of the interface.

---

## 5. Apple Design Resources

**Official source:**
https://developer.apple.com/design/resources/

**Apple Design index:**
https://developer.apple.com/design/

**Get Started:**
https://developer.apple.com/design/get-started/

Apple provides official platform UI kits, icon-production resources, fonts, templates, color guidance, and SF Symbols resources.

Use these for studying:

- proportion;
- hierarchy;
- control density;
- spacing discipline;
- typography;
- icon consistency;
- interaction/state treatment;
- platform conventions.

Do **not** treat these assets as a mandate to make Neuro look like a native Apple application. Neuro is browser-based and has its own visual system and information density.

---

## 6. Neuro's Apple-derived product principles

These are **Neuro's synthesis**, not quotations or official Apple rules. They translate the references above into the product's own needs.

1. **Purpose before interface.** Show what matters to the user's task, not everything the system happens to know.
2. **Hide orchestration, expose progress and outcomes.** The cogs can stay hidden; the user should still know what is happening.
3. **Progressive disclosure without interaction tax.** Hide secondary complexity, never the result or normal next action.
4. **Zero clicks to understand; one to understand deeply; roughly two to act.** A heuristic, not a mechanical test. Three-plus sequential interactions require justification.
5. **Context should reduce copy.** Layout, state, hierarchy, and timing should let labels stay short without becoming vague.
6. **Complexity appears just in time, not just in case.** Do not ask for configuration before it is useful.
7. **Common actions stay close to the result.** Do not bury routine work in overflow menus for visual cleanliness.
8. **Motion explains continuity and state.** Animation should reveal, connect, acknowledge, or orient; it should not delay work or decorate inactivity.
9. **Simplicity is not emptiness.** Neuro may remain dense where density helps compare and operate. Remove friction, not capability.
10. **Delight through competence.** Fast acknowledgment, clear state, thoughtful transitions, accurate language, recoverability, and trustworthy behavior create the desired feeling more than visual effects do.
11. **Every layer of disclosure must earn the click it adds.** Hiding something is a cost, not automatically an improvement.
12. **Make complicated things feel simple, not simplistic.** Preserve power and evidence while reducing the amount a user must hold in their head at one time.

### Canonical example: project creation

Project creation should be the clearest demonstration of these principles.

The visible beginning should ask for only what is required to start useful work, ideally something close to:

- Project name
- Goal
- Create

The system may then perform substantial work — existing-library scan, source reuse, related-project matching, gap detection, ranking — without making the user operate those mechanisms.

Show human-readable progress and results as they become useful. Do not expose internal job names merely because they exist.

Additional context should appear when it becomes valuable, not as an up-front wall of configuration.

The desired feeling is:

> **The product prepared the room before the user walked into it.**

That is a product-behavior goal, not an animation or styling requirement.

---

## 7. How `DESIGN.md` should use this file

`DESIGN.md` may cite this file when making judgment calls about:

- progressive disclosure;
- interaction depth;
- screen purpose;
- information hierarchy;
- concise UI writing;
- familiarity and consistency;
- motion;
- craft;
- simplicity versus minimalism;
- project onboarding and creation flows.

Do not duplicate this entire sourcebook into `DESIGN.md`. Keep the durable Neuro-specific rule there and point here for external rationale and deeper reading.

If this file conflicts with `DESIGN.md`, **`DESIGN.md` wins** until the conflict is deliberately reviewed and resolved.

---

## 8. How `AUDIT.md` should use this file

The audit may use these references as a lens when asking:

- What is the purpose of this screen?
- What must be understood with no interaction?
- What can be disclosed later?
- Did hiding complexity introduce unnecessary steps?
- Does the user know what comes next?
- Can context eliminate explanatory copy?
- Can button labels be understood in context and, for consequential choices, on their own?
- Are routine actions unnecessarily buried?
- Does motion communicate state or merely decorate it?
- Does the interface feel consistent enough that learned behavior transfers across surfaces?
- Is the interface simple, or only visually minimal?

These questions supplement Neuro's own audit criteria. They do not replace evidence collection, workflow testing, accessibility checks, performance measurement, or product-specific semantics.

---

## 9. Source hygiene

- Prefer first-party Apple Developer sources over summaries, social posts, or third-party interpretations.
- When Apple updates a live HIG page, treat the live version as current guidance and note any material change before altering Neuro's rules.
- Older WWDC sessions remain useful for durable principles but should not override current HIG guidance on platform-specific behavior.
- Keep Apple-derived claims distinct from **Neuro synthesis**. This file labels the synthesis explicitly.
- Do not turn every Apple recommendation into a hard gate. Neuro is not an Apple-platform clone.
