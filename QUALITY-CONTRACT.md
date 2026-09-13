# Neuro Search Quality Contract

**Purpose:** Permanent quality, stabilization, regression, and repository-hygiene rules for every coding agent and every feature mission.

This file is intentionally stable. It is not a mission log, changelog, architecture map, or design guide. `CLAUDE.md` remains the architecture authority, `HANDOFF.md` remains the working/delivery authority, `HARDENING.md` remains the evidence and experiment record, `STATE-OF-THE-APP-*` remains the current product snapshot, and `DESIGN.md` / `AUDIT.md` govern design quality when present.

The job of this file is narrower: prevent a fast-moving AI-built application from becoming structurally messy, difficult to verify, or easy to regress.

## 1. Quality hierarchy

A change is not good because it compiles, passes its new unit test, or looks correct in one screenshot. A shippable change must preserve five layers of quality:

1. **Behavioral correctness** - the intended user task works and failure states are honest.
2. **Regression safety** - existing critical workflows still work, including workflows the change did not intend to touch.
3. **Architectural integrity** - the change extends existing systems instead of creating a parallel path for the same responsibility.
4. **Product and design integrity** - the interface still follows the established information architecture, design system, interaction semantics, responsiveness, and accessibility rules.
5. **Repository integrity** - the change leaves the codebase and documentation easier to understand, not harder.

Passing only one or two layers is not sufficient.

## 2. One responsibility, one canonical home

Before adding any module, table, endpoint family, job type, cache, provider adapter, fetch path, ingestion path, source identity mechanism, queue, auth mechanism, research representation, UI component pattern, configuration key, or documentation file:

1. Search the repository for the responsibility, not only the proposed name.
2. Identify the current canonical implementation.
3. Extend or reuse it when possible.
4. If a new abstraction is still necessary, document why the existing one cannot safely carry the responsibility.
5. Add a gate that would fail if the old and new paths diverge in a dangerous way.

**Parallel infrastructure is a defect unless explicitly justified.**

Examples already governed elsewhere remain binding: model calls use the existing provider/contracts path; user-supplied network fetches use the established safe fetch boundary; background work uses the durable job system; database access follows the running-app safety rules; ingestion, provenance, source identity, cost accounting, and research state are not reimplemented per feature.

## 3. Repository hygiene rules

### 3.1 Root stays intentional

The repository root is a navigation surface, not a storage bin.

Every root-level document must be one of:

- a permanent front door or contract,
- the current state document,
- an active or queued mission,
- a standard repository file required by tooling.

Finished missions, historical investigations, old state snapshots, one-off measurements, superseded plans, generated reports, and previous handoffs belong under an appropriate archive/reference directory, not beside active work.

A release gate should maintain an explicit root-document allowlist or equivalent rule and report unexpected root clutter.

### 3.2 One live document per responsibility

Do not maintain two live copies of the same mission, architecture description, or instruction set in different folders. Snapshots may exist only when clearly marked archival and must never be part of the normal reading path.

When a document is superseded:

- update the canonical pointer,
- archive or delete the superseded copy,
- do not leave two apparently-current versions.

### 3.3 Active versus historical must be machine-readable enough to check

Every mission document should have an obvious status near the top, such as `ACTIVE`, `QUEUED`, `BLOCKED`, or `COMPLETE/ARCHIVED`, plus the last meaningful revision date or release.

The root should contain only active/queued mission documents. Completed mission documents are moved to archive during closeout, not weeks later.

### 3.4 No junk drawers

Avoid generic modules such as `utils.py`, `helpers.py`, `misc.py`, `common2.py`, or `new_*.py` when the code has a clear domain owner. Shared code belongs with the subsystem that owns the invariant.

Do not create `foo_v2.py` as a permanent coexistence strategy. Experimental alternatives must have an explicit evaluation, adoption/rejection decision, and removal plan.

### 3.5 Dependencies must earn their place

Before adding a dependency, record:

- what measured problem it solves,
- why the standard library or current stack is insufficient,
- license,
- maintenance health,
- data portability or lock-in risk where relevant,
- removal difficulty.

A dependency added for convenience alone should be rejected when a small existing-path change is sufficient.

## 4. Change discipline

### Before editing

For every non-trivial change:

1. Read `HANDOFF.md`, `CLAUDE.md`, this contract, the current state document, the assigned mission, and the tests that gate the touched area.
2. Inspect the current implementation before accepting an older mission's description as truth.
3. Run the current baseline required by `HANDOFF.md`.
4. Search for existing implementations, duplicate concepts, routes, job kinds, tables, configuration keys, and UI controls that overlap the requested work.
5. State the regression surface: what could break even if the new feature itself works.

### While editing

- Make the smallest coherent change that proves the rung.
- Prefer modification over duplication.
- Keep refactors separate from behavior changes when practical.
- Do not opportunistically rewrite neighboring systems without evidence and a gate.
- Preserve compatibility unless the mission explicitly authorizes a breaking change.
- Add tests at the level where the regression can actually occur, not only at the helper-function level.
- If an unexpected architectural problem is discovered, record it as debt or amend the mission. Do not silently broaden scope.

### Before calling the change done

The existing release ritual still applies. In addition, the agent must answer:

- Did this create a second implementation of an existing responsibility?
- Did it create a new root document that now needs lifecycle ownership?
- Did it leave dead code, an obsolete path, stale flags, temporary compatibility code, or an abandoned experiment?
- Did it add a route/job/table/config key without documenting its owner and tests?
- Did it change a workflow without a task-level regression test?
- Did it change visible UI without running the relevant design/audit checks and a human visual pass?
- Is the current-state documentation now inaccurate?

If any answer is yes, the rung is not closed until the debt is explicitly resolved or recorded with a reason and owner.

## 5. Required QA layers

### Layer A - Static and structural QA

Automate checks where practical for:

- duplicate route registrations,
- duplicate or shadowed function/class definitions in the same module,
- obvious dead/unreachable code,
- unused imports and variables,
- import cycles or newly introduced dependency cycles,
- orphan modules with no imports/entry points/tests,
- duplicate configuration keys or conflicting defaults,
- multiple code paths performing the same protected responsibility,
- accidental root-level files and stale generated artifacts,
- test files that are not discoverable,
- oversized modules that cross a documented review threshold.

These are signals, not blind auto-delete instructions. A finding must be classified before destructive cleanup.

### Layer B - Unit and contract QA

Every subsystem keeps deterministic tests for its local invariants. New bug fixes receive a regression test whenever the failure is reproducible.

### Layer C - Integration QA

Test boundaries between systems: API to DB, jobs to providers, ingestion to source state, retrieval to citations, Research to project state, planner to evidence, UI actions to endpoints, external adapters to canonical ingestion.

### Layer D - Task-based workflow regression QA

Maintain a small set of critical user journeys that cross multiple modules. These are not exhaustive end-to-end tests. They are high-value product contracts.

At minimum evaluate the current equivalents of:

1. Create a project and refine its goal/context.
2. Add an already-known source and verify global reuse rather than duplicate acquisition.
3. Ingest a new source through the ordinary path and reach usable searchable state.
4. Ask a cross-source question and verify citations resolve to real evidence.
5. Generate/review findings and ensure status changes affect downstream state correctly.
6. Open Research and verify important questions/watch-outs/knowledge state remain coherent.
7. Build or update a plan and preserve evidence linkage.
8. Exercise a failed/retryable background job and verify recovery, dedupe, and cost behavior.
9. Restart/reload with work in flight and verify durable state remains honest.
10. Verify a stale or incompatible UI/server state is detected rather than silently misbehaving.

When a mission changes information architecture or workflow semantics, add a task-based regression for the user's mental model: can a first-time user still predict what to do, what an action changes, and how to recover?

### Layer E - Visual and interaction QA

Visual QA is separate from code QA.

When `DESIGN.md` and `AUDIT.md` exist, compare the changed surface against those stored rules rather than asking an AI for unconstrained aesthetic opinion.

Check at minimum:

- design-token and component drift,
- typography hierarchy,
- spacing, alignment, density, and readable line length,
- responsive layout at defined breakpoints,
- loading, disabled, success, empty, error, and partial states,
- focus/keyboard behavior for touched controls,
- destructive-action clarity,
- outcome-named buttons and consequence previews where required,
- first-time-user comprehension of the changed workflow.

Automated visual checks may flag drift. A human visual pass remains a release requirement for meaningful UI changes.

### Layer F - Operational QA

For changes touching runtime, storage, jobs, providers, networking, or recovery, verify the relevant operational contracts: startup, shutdown, restart, logs, stuck-work recovery, backups, integrity checks, budget/rate gates, retry semantics, idempotency, and truthful health reporting.

## 6. The repo-health gate

Create one deterministic command, preferably integrated with the existing CLI and `release-check`, that reports repository health without making paid calls or touching the live database from outside the running app.

Suggested shape: `neurosearch repo-check` or a similarly native name chosen after inspecting current CLI conventions.

It should initially report, then gradually enforce, checks such as:

- unexpected root documents/files,
- multiple active state snapshots,
- completed mission files still in the active root,
- duplicate same-module definitions,
- duplicate API route method/path pairs,
- orphaned test modules or undiscoverable tests,
- stale version mismatches already covered elsewhere,
- forbidden direct provider/fetch/database patterns already governed by architecture rules,
- references to missing or archived documents from active front-door docs,
- obviously abandoned experimental modules that remain reachable nowhere.

**Important:** establish a baseline before making this blocking. Existing debt is not an excuse to make the gate useless, and a new gate is not an excuse to demand a giant cleanup in one release. Freeze the known baseline, prevent regressions first, then pay down debt in measured rungs.

## 7. Regression budgets

A release must not make any protected baseline worse without an explicit recorded decision.

Protected baselines include whatever the repository already freezes, plus the stabilization mission's measured repository-health baseline. Examples:

- tests passing/failing/flaking,
- critical workflow results,
- duplicate routes/definitions,
- root-document clutter,
- direct-boundary violations,
- dead/orphan module count,
- startup/recovery checks,
- UI/design audit violations for protected surfaces.

The objective is not a magical score of 100. The objective is monotonic health: new work cannot casually make structural debt worse.

## 8. Cleanup safety

Do not perform a giant beautification/refactor pass.

Classify cleanup findings:

- **P0 Correctness/Safety:** can corrupt data, spend unexpectedly, expose secrets, lose work, lie to the user, or break recovery.
- **P1 Regression/Architecture:** duplicate pathways, conflicting state owners, broken tests, flakiness, job/routing inconsistencies.
- **P2 Maintainability:** dead code, obsolete compatibility paths, duplicated helpers, oversized modules, confusing naming.
- **P3 Cosmetic:** formatting, comments, low-value churn.

Work P0 and P1 first. P2 is done in bounded rungs with tests. P3 never justifies destabilizing working code.

Deletion requires evidence: repository search, call/import/route references, tests, and runtime/entry-point awareness. Git history is the recovery mechanism; do not preserve dead code indefinitely merely because deletion feels risky.

## 9. Documentation lifecycle

At mission start:

- active mission is visible from the current state/handoff path,
- status is explicit,
- acceptance gates are defined before implementation.

At each shipped rung:

- update the mission's status/rung log,
- update architecture docs only when architecture changed,
- update HARDENING only for evidence/frozen-number decisions,
- update current state when the product truth changed materially.

At mission completion:

- move the mission to archive,
- remove it from the active reading path,
- keep only durable rules in permanent docs,
- do not copy the mission's full history into CLAUDE/HANDOFF/STATE.

A completed mission should stop consuming the attention of every future coding agent.

## 10. Definition of stable

A subsystem is stable when:

- its owner/path is clear,
- its invariants are executable where practical,
- its critical workflow has a regression gate,
- its failures are observable and distinguishable,
- retries/restarts are safe where applicable,
- there is no competing implementation for the same responsibility,
- documentation points to one current truth,
- the next agent can change it without reconstructing months of chat history.
