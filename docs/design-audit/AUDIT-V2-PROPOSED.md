# AUDIT V2 — proposed runtime-verification additions

**Status: PROPOSAL FOR MERGE, NOT CANONICAL.**

This file was produced in ChatGPT on 2026-09-12 after Claude identified a real gap in the current design audit: several important findings had been diagnosed from static code/markup inspection and passive display-state inspection, but the corresponding live workflows had not actually been exercised end to end.

`AUDIT.md` remains canonical. The current repository copy of `AUDIT.md` has evolved beyond the earlier base used to draft this proposal, including Neuro-specific safety, audit-instance, design-source-of-truth, evidence-location, and frontend-contract rules. **Do not replace `AUDIT.md` wholesale with this file.** Instead, compare the two and merge only the additions below where they strengthen the canonical audit without regressing newer rules.

The intended change is narrow: make runtime verification a bounded, explicit completion requirement so an auditor cannot stop after static inspection, but also cannot keep F0 open indefinitely because another low-risk screen remains uninspected.

---

# Proposed addition: controlled runtime verification protocol

A FULL AUDIT is not complete from static code/markup inspection plus passive screen viewing. Core workflows must be exercised on a safe audit instance.

## Use an audit instance, not valuable project state

For actions that mutate durable state, queue work, dismiss/approve content, trigger analysis, or could spend money:

- use the existing dedicated audit instance/project mechanism defined by canonical `AUDIT.md`;
- use disposable or reversible content;
- do not alter the user's real projects merely to create audit evidence;
- do not intentionally spend paid API budget merely to prove a UI state unless the user explicitly authorizes that spend;
- prefer existing fake/local/test provider paths when they preserve the user-visible workflow being inspected;
- do not add production code, hidden audit endpoints, or a second job system merely to make auditing easier.

If a cost-bearing workflow cannot be completed without real spend, audit the preflight/cost disclosure on the real UI and exercise the remaining state transition through the closest existing deterministic fake/test path. Label that evidence **SIMULATED RUNTIME**, not live production behavior.

## Minimum runtime matrix for a FULL AUDIT

Exercise each currently available workflow below at least once on the audit instance:

| Workflow | Minimum evidence |
|---|---|
| Add/acquire research | Submit one safe source/file → observe queued/working/progress → usable result or controlled failure |
| Findings | Approve or dismiss one disposable finding → verify immediate feedback + durable consequence |
| Chat | Send one real project question → observe acknowledgement/progress/answer → inspect one evidence or gap path |
| Discover | Run one bounded discovery operation → observe progress/results → add or dismiss one candidate where safe |
| Planner | Open and, where safely possible, rebuild/update a plan on audit evidence → observe progress and resulting state |
| Jobs/work | Start one background job → observe queue admission, active state, progress, completion/recovery |

Project creation should also be exercised at least once unless the audit scope explicitly excludes onboarding.

For every load-bearing workflow, tag the evidence level:

- **RUNTIME VERIFIED** — performed in the rendered app and observed end to end;
- **SIMULATED RUNTIME** — exercised through an existing fake/test/failure path with the rendered or executable workflow observed;
- **STATIC ONLY** — inferred from code/markup/docs without executing the behavior;
- **NOT APPLICABLE / BLOCKED** — explain why.

A Critical or High finding should normally have RUNTIME VERIFIED or SIMULATED RUNTIME evidence. If it remains STATIC ONLY, keep the finding but lower confidence and explicitly state the missing verification.

---

# Proposed addition: failure-state verification

A FULL AUDIT must inspect, not merely infer, at least:

1. one failed or recoverable background job; and
2. one interrupted, stale, failed, or non-updating polling/refresh condition where the environment safely permits it.

Use existing deterministic failure knobs, fixtures, fake providers, offline/network controls, or already-supported test paths. Do not corrupt state, sabotage the live database, or make a paid provider fail intentionally.

For each failure confirm whether the user can tell:

- that work failed or stopped;
- what failed;
- whether anything was charged or may still be running;
- whether partial work is usable;
- what action is available next;
- whether retry/recovery actually returns to a truthful state.

If safe runtime reproduction is impossible, mark the state **CANNOT VERIFY** and cite the closest executable test/code evidence. Do not silently count static inspection as equivalent.

---

# Proposed addition: timing baseline before performance thresholds

Do not invent a UX timing threshold before measuring the current behavior.

For any audit rung that proposes a timing/perceived-performance improvement, capture a baseline first. Prefer three repetitions of the same operation in the same environment when the operation is cheap and reversible. For expensive or very long operations, one representative runtime sample plus existing timing-ledger evidence is acceptable if clearly labelled.

Record separately where possible:

- **T_ack** — user action → visible acknowledgement;
- **T_state** — action → truthful queued/running/progress state;
- **T_result** — action → first usable result or completion;
- poll/refresh cadence if polling materially affects the experience;
- whether the UI looked dead, stale, or misleading during the wait.

Use these numbers as the baseline for the later acceptance test. The audit does not need statistically rigorous benchmarking; it does need a real number before proposing one.

---

# Proposed addition: narrow viewport must be interactive, not screenshot-only

For a FULL AUDIT, test at least one realistic narrow viewport when tooling permits. At minimum verify:

- primary navigation remains reachable;
- the page can scroll normally;
- primary actions remain reachable;
- controls can be activated without hidden overlap;
- dialogs/drawers can be opened and dismissed;
- no critical horizontal overflow blocks the task.

Static screenshots may support this evidence but do not replace interaction. If narrow-screen use is low priority for the product, record lower severity rather than skipping verification entirely.

---

# Proposed addition: bounded stopping rule

Runtime verification is a closure requirement, not an invitation to audit forever.

Once the minimum runtime matrix, required failure states, timing baseline for any timing-sensitive rung, and one interactive narrow-width pass are complete, perform the fixed-point closure pass.

If that pass produces **no new material root cause and no ladder reorder, close F0 and proceed.**

Do not ask the user whether to keep inspecting merely because additional low-confidence surfaces remain. Record them under **Residual coverage / cannot verify** and continue unless they could plausibly:

- change a Critical/High finding;
- invalidate a root cause; or
- reorder the first implementation rung.

This is specifically intended to prevent the audit from becoming an unbounded comfort-seeking exercise.

---

# Proposed completion-criteria additions

The canonical completion criteria should make the following explicit if they are not already covered strongly enough:

1. Load-bearing workflows were walked end to end and tagged RUNTIME VERIFIED, SIMULATED RUNTIME, STATIC ONLY, or BLOCKED.
2. Important states include at least one failed/recoverable background job and one interrupted/stale/non-updating refresh condition where safely reproducible.
3. Any timing-sensitive proposed rung has a measured baseline, preferably three repetitions when cheap/reversible, rather than an invented threshold.
4. At least one realistic narrow viewport was exercised interactively when tooling allowed; screenshots alone do not count as responsive verification.
5. Critical/High findings that remain STATIC ONLY are explicitly marked lower-confidence.
6. Residual unverified surfaces are listed without keeping F0 open unless they could plausibly change a Critical/High finding or reorder the first implementation rung.
7. A fixed-point closure pass found no new material unpropagated consequence.

---

# Proposed FULL AUDIT invocation delta

The canonical FULL AUDIT invocation should preserve all of its current Neuro-specific safety and artifact-location rules, while also requiring the following behavior:

> Use the dedicated audit instance/project for state-changing verification. Complete the minimum runtime matrix, inspect the required failure states, capture a real timing baseline before proposing timing thresholds, and interactively exercise at least one narrow viewport when tooling permits. Do not spend paid API budget merely to create audit evidence unless explicitly authorized. For every load-bearing workflow classify evidence as RUNTIME VERIFIED, SIMULATED RUNTIME, STATIC ONLY, or BLOCKED. Critical/High findings that remain STATIC ONLY must be marked lower-confidence. Once the runtime matrix and closure criteria are satisfied, close the audit rather than asking whether to continue inspecting low-risk surfaces.

---

# Merge intent

When reviewing this proposal against `AUDIT.md`:

1. **Canonical `AUDIT.md` wins on conflicts.** Preserve its newer Neuro-specific rules.
2. Do not duplicate rules that canonical `AUDIT.md` already expresses more strongly.
3. Merge the runtime-verification concepts only where they close a genuine gap.
4. Preserve the existing audit-instance safety boundary. Never use live valuable project state for state-changing audit exercises.
5. Preserve existing frontend integrity, version-handshake, cost, provider, design-source-of-truth, and evidence-location requirements.
6. Do not change the implementation ladder merely because this proposal exists. Re-run/reconcile F0 evidence first; change F1/W1 ordering only if runtime evidence materially changes the diagnosis.
7. After merging, remove or archive this proposal so there is one canonical audit contract, not two competing instructions.
