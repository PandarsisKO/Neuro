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

Deliver:

- `design-audit-raw.md`
- `design-audit.md`
- `design-audit-ladder.md`

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

Use current docs and tests to identify intended behavior, locked invariants, known limitations, historical rationale, and expected states. Current implementation and rendered behavior outrank stale documentation.

## 4.4 Real project/data scale

Where safe and supported, inspect representative large-project states and real content scale. Do not infer usability at 5,000 findings from an empty fixture alone.

## 4.5 Minimum runtime verification matrix

Static reading does not satisfy a full audit for load-bearing workflows. Before F0/full inspection closes, use a disposable audit instance/project and exercise at least these flows end to end where the current environment safely permits it:

1. **Add/acquire research**: submit one safe source or file and observe admission/acknowledgement, queued state, active/progress state, and usable completion or controlled failure.
2. **Findings**: approve or dismiss one disposable finding and verify immediate feedback plus durable resulting state.
3. **Chat**: send one real project question and observe acknowledgement/progress/answer plus one evidence or research-gap path.
4. **Discover**: run one bounded Discover operation, observe its states/results, and safely add or dismiss one candidate.
5. **Master Planner**: exercise the real Planner workflow far enough to verify progress/state behavior and resulting UI. Use an existing local/fake path if a real rebuild would incur unnecessary spend.
6. **Jobs/background work**: observe one job from admission through active work to completion or recovery.

Also verify, using existing safe test/fake/failure mechanisms where possible:

- one failed or recoverable background job;
- one interrupted, stale, failed, or non-updating poll/refresh condition.

Do not sabotage valuable user state or spend paid API budget merely to create audit evidence.

For every important workflow/finding, classify the evidence as:

- **RUNTIME VERIFIED**
- **SIMULATED RUNTIME**
- **STATIC ONLY**
- **BLOCKED / CANNOT VERIFY**

Critical/High findings that remain STATIC ONLY must have reduced confidence and explicitly state the missing verification.

## 4.6 Timing baseline

Any proposed rung that changes perceived response time, row-action feedback, polling, queue acknowledgement, or progress disclosure must begin from measured current behavior rather than an invented threshold.

Record where possible:

- `T_ack`: user action → visible acknowledgement;
- `T_state`: action → truthful queued/running/progress state;
- `T_result`: action → first usable result or completion;
- relevant poll cadence.

Prefer three repetitions when the operation is cheap and reversible. For long or expensive operations, one representative runtime sample plus existing timing evidence is sufficient if labeled honestly.

## 4.7 Narrow viewport verification

For a full audit, exercise at least one realistic narrow viewport interactively when tooling permits. Screenshots alone do not count.

Verify:

- scrolling;
- navigation;
- primary actions;
- tap/click reachability;
- drawers/dialogs;
- blocking horizontal overflow.

Do not automatically elevate mobile/narrow work above higher-impact desktop workflow problems unless a material defect appears.

---

# 5. Audit dimensions

Evaluate major surfaces across these dimensions, but do not mechanically generate findings for every category when no material problem exists.

## 5.1 Intent and hierarchy

Can a first-time user tell what the page is for, what matters now, what to do next, and what can wait?

## 5.2 Information density and progressive disclosure

Does the default view show decisions and meaning first, with diagnostics/details available on demand? Watch for giant cards, excessive metadata, repeated explanations, long unprioritized lists, action overload, and shrinking typography as a substitute for hierarchy.

## 5.3 Actions and consequences

For each meaningful control, can the user predict outcome, cost class, reversibility, state change, and downstream consequence? Internal endpoint/payload identity is a debugging note, not the user-facing contract.

## 5.4 State and trust

Inspect loading, queued, working, partial, stale, failed, empty, disabled, recovery, and success. Verify the UI never converts unknown into zero or queued into complete.

## 5.5 Cross-surface continuity

Trace how Sources, Findings, Claims/Research, Discover, Chat, Planner, and Jobs affect one another. A screen may be locally coherent and globally confusing.

## 5.6 Performance as experience

Audit acknowledgement latency, progress visibility, blocking work, polling behavior, stale UI, and first usable result. Measure before prescribing thresholds.

## 5.7 Accessibility and responsiveness

Inspect semantic controls, keyboard/focus behavior where possible, labels, contrast, hierarchy, motion, narrow widths, and reachable interactions. Do not reduce accessibility to contrast alone.

## 5.8 Design-system drift

Separately inventory semantic roles and their implementations: action hierarchy, badges/statuses, cards, banners, drawers, tables/rows, typography roles, spacing, color tokens, empty states, loading/progress, error treatment, paid/cost-bearing actions, destructive actions, and responsive behavior. Flag local exceptions that create inconsistent meaning, not merely visual difference.

---

# 6. Workflow-first audit

Do not only inspect screens vertically. Walk load-bearing workflows horizontally, end to end.

Examples:

```text
Create project → bootstrap/reuse → research review → source attachment → findings → claims/research state → plan
Add source → admission → queue → processing → completion/failure → source value → downstream use
Finding action → immediate feedback → durable state → claims/research impact → planner impact
Discover → candidate → review → acquisition/reuse → evidence → research gap update
Chat → question → retrieval → answer → citation/evidence drilldown → user decision/context update
```

For each workflow record:

- entry point;
- user expectation;
- states encountered;
- costs or consent points;
- failure/recovery behavior;
- timing baseline where material;
- downstream state changes;
- evidence classification (runtime/simulated/static/blocked);
- places where the user must understand internal machinery to proceed.

---

# 7. Root-cause consolidation and closure

## 7.1 Consolidate symptoms

If multiple findings share a cause, create one root-cause finding with affected surfaces beneath it. Do not create twenty independent tickets for one missing status/action/hierarchy primitive.

## 7.2 Propagate consequences

When a root cause is identified, search every materially affected surface and component. A fix recommendation is incomplete until its propagation boundary is known.

## 7.3 Materiality threshold

Prioritize findings that materially affect comprehension, trust, task completion, cost understanding, evidence use, decision quality, error recovery, perceived speed, accessibility, or repeated consistency. Cosmetic preference without a user consequence belongs in polish or is omitted.

## 7.4 Fixed-point closure pass

After synthesis, re-read the major findings and proposed ladder as a system. Ask:

- Does one recommendation contradict another?
- Does a shared primitive change require propagation elsewhere?
- Did the proposed fix create a new state or accessibility obligation?
- Is a supposedly local issue actually systemic?
- Did runtime verification disprove or weaken a static diagnosis?
- Would any remaining uninspected surface plausibly change a Critical/High root cause or reorder the first implementation rung?

Repeat only when a new material consequence is discovered. Do not keep auditing for comfort.

## 7.5 Bounded stopping rule

F0/full inspection closes when:

- the minimum runtime matrix is satisfied or honestly marked blocked;
- required failure states are inspected or safely unreproducible and documented;
- timing-sensitive first-rung recommendations have a baseline;
- narrow-width interaction is verified where tooling permits;
- the closure pass produces no new material root cause or ladder reorder.

Remaining low-risk gaps go into **Residual Coverage**. They do not keep F0 open merely because more inspection is possible.

---

# 8. Required artifacts

## 8.1 `design-audit-raw.md`

Intentionally messy, exhaustive evidence capture. Include screenshots/references, interaction notes, runtime evidence labels, code references, state inventories, duplicates, questions, possible causes, measurements, assumptions, and disproven suspicions. Do not clean away evidence.

## 8.2 `design-audit.md`

Reviewed evidence-backed audit with executive summary, scope/limitations, product map, severity-ranked findings, design-system drift, workflow/accessibility/performance findings, root-cause map, strengths worth preserving, assumptions/cannot verify, and Residual Coverage.

## 8.3 `design-audit-ladder.md`

Convert the audit into a small number of coherent implementation rungs. Each rung includes problem, affected surfaces, system-level change, ordering rationale, non-goals, likely implementation seam, acceptance test, regression risks, runtime/test requirements, visual re-audit requirement, effort S/M/L, and risk Low/Medium/High. Foundations and workflow/IA changes precede component consistency and polish.

---

# 9. What substantial improvement means

A recommendation is substantial when it produces an observable user improvement and has a clear acceptance condition.

Weak: "Make the Findings page cleaner."

Better: consolidate stale-source review, low-value finding review, and duplicate review into one Review workflow that explains why each item needs attention, separates system-detectable cleanup from user judgment, and exposes no bulk destructive action until the user understands the affected set.

Weak: "Improve button styles."

Better: define one shared action hierarchy for primary, secondary, destructive, state-toggle, and paid actions, then replace local button styling and labels across Research, Sources, Findings, Discover, and Jobs. A first-time user should predict consequence and cost from label plus nearby microcopy.

Weak: "Add more spacing."

Better: move diagnostic metadata behind progressive disclosure and reserve the default card body for the user decision, reducing vertical height while improving scanability at 100+ items.

---

# 10. Things not to do

Do not ask the model to simply make the UI better; redesign from taste before workflows; change the product during audit; invent analytics/user complaints; treat intentional local/single-user behavior as a defect without context; apply irrelevant SEO checks; reduce accessibility to contrast; claim visual quality from code alone; treat stale Figma as authoritative; recommend framework churn for local mess; propose infrastructure before measured bottlenecks; solve density by shrinking all type; force all components identical regardless of semantics; expose engine terminology for architectural purity; add confirmations everywhere; automate unsafe user judgment; call one audit final/perfect; or create a hundred-item backlog without root-cause grouping.

---

# 11. Strengths must be recorded too

For every major surface, record strengths and constraints worth preserving: progressive evidence disclosure, explicit cost consent, honest uncertainty, precise provenance, useful compact density, cross-surface continuity, effective grouping, fast perceived feedback, clear empty states, or an existing pattern that should become the standard. The ladder must name what each rung must not regress.

---

# 12. Completion criteria for the audit

The audit is complete when all of the following are true:

1. Current product/version identified.
2. Live rendered product inspected where tooling allowed.
3. Major surfaces inventoried by user intent.
4. Load-bearing workflows walked end to end and evidence-tagged.
5. Important states include at least one failed/recoverable background job and one interrupted/stale/non-updating refresh condition where safely reproducible.
6. Timing-sensitive proposed rungs have measured baselines rather than invented thresholds.
7. At least one realistic narrow viewport was exercised interactively when tooling allowed.
8. Real-content/large-project behavior tested where available.
9. Major findings contain reproducible evidence; Critical/High STATIC ONLY findings are lower-confidence.
10. Design-system drift audited separately from general UX judgment.
11. Cross-surface interactions reviewed.
12. Raw observations preserved in `design-audit-raw.md`.
13. Symptoms consolidated into root causes in `design-audit.md`.
14. Recommendations filtered for materiality.
15. Fixed-point closure pass finds no new material unpropagated consequence.
16. Residual unverified surfaces listed without keeping F0 open unless they could plausibly change Critical/High findings or reorder the first rung.
17. `design-audit-ladder.md` turns major problems into coherent implementation rungs.
18. No product code changed unless separately authorized.

---

# 13. Invocation prompts

## Full audit

> Follow `AUDIT.md` in FULL AUDIT mode. Audit the current Neuro Search product as it exists now, using the live rendered application plus the current repository and tests. Do not change the product. Use a disposable audit instance/project for state-changing verification. Complete the minimum runtime matrix in §4.5, inspect the required failure states, capture a real timing baseline before proposing timing thresholds, and interactively exercise at least one narrow viewport when tooling permits. Do not spend paid API budget merely to create audit evidence unless explicitly authorized. Produce `design-audit-raw.md`, `design-audit.md`, and `design-audit-ladder.md`. Prioritize substantial, system-level improvements over cosmetic churn. Do not stop at generic UI/UX feedback. Reproduce important findings, connect them to their mechanics when useful, consolidate symptoms into root causes, and complete the bounded closure pass required by `AUDIT.md`. Once the runtime matrix and closure criteria are satisfied, close the audit rather than asking whether to continue inspecting low-risk surfaces.

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
