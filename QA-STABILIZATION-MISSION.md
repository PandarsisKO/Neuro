# MISSION: QA, STABILIZATION, AND REPOSITORY CONTROL

**Status:** ACTIVE WHEN EXPLICITLY ASSIGNED

## Mission

Make Neuro Search harder to break and easier to continue building without slowing feature development into bureaucracy.

The target is not "clean code" as an aesthetic exercise. The target is a repository in which Claude, Codex, or a human can rapidly answer:

- What is the canonical implementation of this responsibility?
- What must not regress?
- What tests prove that?
- Which documents are current?
- Which missions are actually active?
- Is this proposed module/path/table/job genuinely new, or are we duplicating something?
- If a release breaks, can we tell what failed and recover safely?

The repository itself must increasingly enforce those answers.

## Starting context to verify, not blindly trust

The latest supplied State of the App snapshot reports a healthy release baseline with 1,246 automated tests green and release gate PASS, while also naming a flaky test, a current correctness/hygiene rung, and documentation clutter from completed mission files. The current repository is always the source of truth. Re-measure before changing anything.

This mission must preserve all standing rules in `CLAUDE.md`, `HANDOFF.md`, `HARDENING.md`, active missions, and the permanent `QUALITY-CONTRACT.md`.

It must also consume, not duplicate, the separate design system work. If `design.md` and `audit.md` exist, use them as the visual/design QA references.

## Non-goals

Do not:

- rewrite the whole application,
- convert the stack because another architecture is fashionable,
- introduce a new test framework when pytest/current release tooling is sufficient,
- create a second job system, DB abstraction, fetch path, provider path, ingestion architecture, design system, or documentation hierarchy,
- "fix" frozen measurements without re-measurement,
- mass-delete code from static-analysis output,
- reformat the entire repository,
- turn every warning into a release blocker on day one,
- create a giant QA dashboard before the underlying checks exist,
- perform paid model calls merely to validate code quality.

## Core strategy

**Inventory -> Baseline -> Prevent new debt -> Fix high-risk debt -> Add workflow regressions -> Integrate into release gate -> Archive the mission.**

The order matters. A cleanup that is not protected by a regression gate simply creates a new opportunity to regress later.

## R0 baseline — 2026-09-12

Measured from the current checkout at `053145c` (documentation-only changes after the
release candidate `fd66241`). The deterministic release ritual for `fd66241` passed:
1,353 tests and all required release gates; the evidence is recorded under
`evals/release/release-check-0.63.43-fd66241-20260912-192249.*`.

- Repository shape: 38 root files, 77 top-level Python modules in `neurosearch/`,
  96 test modules, and 30 archived files.
- Runtime inventory: 197 unique API method/path pairs (0 duplicate pairs), 38
  job-level definitions in `neurosearch/jobs.py`, 37 schema table declarations,
  106 fetch-related references, and 792 provider/model references.
- Tests: the full deterministic suite is green (1,353 passed, one existing warning).
  A focused T1/storage/adversarial set and repeated crash-recovery checks are also
  green; no paid model work was run.
- Confirmed structural debt: the QA mission and quality contract were present only
  as untracked working-tree files; several root state snapshots and historical
  mission artifacts still compete with the current reading path; a naive AST scan
  reports repeated nested method names, but a top-level definition scan and route
  pair scan found no confirmed duplicate implementation.
- False positives: repeated `__init__`, `connect`, and similar names in nested
  classes are intentional; README export names are not automatically broken
  references; Claude's design-owned documents and evidence remain outside this
  mission's edit boundary.
- Do not touch: live `data/`, `VIDEOS/`, `_to_delete/`, Claude's design worktree
  and design-owned files, or `neurosearch/web/index.html` while F0 is open. Do not
  make paid provider calls.

This baseline is the R0 record. The next rung is R1 navigation/root hygiene,
followed immediately by the report-only R2 `repo-check` implementation.

### R0/R1/R2 completion record — 2026-09-12

R0 passed without a behavior change. Three superseded root state snapshots were
moved to `docs/archive/state/`; the newest snapshot remains the single root
checkpoint. R2 is implemented as `neurosearch repo-check` and covered by
`tests/test_repo_check.py`. It is report-only, deterministic, JSON-capable, and
does not initialize the app or open a database. Its current real-repository output
is `PASS (no findings)`. The check treats the explicitly documented, disabled
`planner_v3.py` experiment as an allowlisted exception and catches future
experimental filenames, duplicate top-level definitions, duplicate API routes,
broken front-door links, and root-entry drift. Focused verification: 117 passed;
the full suite was rerun after the changes and produced no observed failure.

The next active rung is R3: re-measure correctness/flakiness debt and select the
highest-value confirmed issue before adding any broader release gate. After the
six repository-check fixtures were added, the full suite collected and passed
1,359 tests with one pre-existing Starlette deprecation warning (138.41s).

The front door is now durable: `AGENTS.md`, `QUALITY-CONTRACT.md`, and
`QA-STABILIZATION-PROMPT.md` are tracked. Their design references use the
repository's canonical uppercase filenames, so a new session will not be sent to
nonexistent `design.md`/`audit.md` files.

### R3/R5/R8 transition record — 2026-09-12

R3 re-measurement found no unresolved P0/P1 correctness or flakiness defect in
the current checkout. The named local-provider fallback concern is already
covered by the explicit no-fallback contract and `tests/test_j3_fallback.py`;
that gate passes (14 tests). Existing task-level gates cover project creation,
global source reuse, ingestion/retrieval, citation-backed chat, findings and
research state, planner provenance, retry/recovery, restart durability, and
stale-client/version behavior across the K/L/N/O/S test families. This is an
evidence-based acceptance of the current R5 coverage, with no duplicate browser
test layer introduced.

R8 is now active: `neurosearch release-check` invokes the same deterministic
`repo-check` and blocks when it reports any finding. A `skip_pytest` release
probe passed on commit `1ecb8e1`, including the new repository-hygiene gate.
The full suite had already passed 1,359 tests after the preceding changes; the
release integration's focused gate passes 14 tests. Remaining work is R6 design
integration (Claude-owned), then R7 operational proof and a final full
release-check before R9/R10 closeout.

### R7 operational evidence — 2026-09-12

`neurosearch doctor --no-smoke` passed in the isolated
`/tmp/neuro-doctor-20260912b` data directory with all experimental flags off,
contracts valid, provider/model routing coherent, and no substitutions. The
only warnings were expected: a new private directory has no database until the
first app run, and optional Reddit credentials are unset. No live database was
opened and no paid model evaluation was run. Existing crash/recovery, breaker,
retry, backup, and stale-client gates remain part of the release ritual.

### Release verification — 2026-09-12

The complete release ritual passed at commit `5476a03` in 172.6 seconds. The
current evidence is `evals/release/release-check-0.63.43-5476a03-20260912-194737`
(`.json` and `.txt`). It includes the blocking repository-hygiene gate,
1,359-test pytest run, migration and crash/recovery matrices, workflow gates,
Tier 1 frozen totals, retrieval/cache/prefilter checks, and backup/restore
integrity. The H1 batch economic gate remains intentionally deferred as a
pre-existing decision; no paid work was initiated by this mission.

R6 remains a coordination boundary: Claude owns `DESIGN.md`, `AUDIT.md`,
`DESIGN-MISSION.md`, `docs/design-audit/**`, and the design drift tests in its
separate F0 worktree. Codex has not modified those paths. Once Claude closes F0,
the design evidence can be attached to this release result without merging
product-code changes.

The local `SCREENSHOT AUDIT/` folder is preserved as non-authoritative evidence:
the canonical design audit explicitly cites those user-captured images. It is
allowlisted by `repo-check` so evidence retention does not create a false root
hygiene failure.

# R0 - Establish the truth

Before editing production code:

1. Read `HANDOFF.md`, `CLAUDE.md`, `QUALITY-CONTRACT.md`, the current State of the App, `HARDENING.md` sections relevant to current failures, active missions, `release.py`, CLI/release-check implementation, test configuration, and dependency metadata.
2. Run the normal deterministic baseline required by the current handoff.
3. Inventory the repository:
   - root files and docs,
   - Python modules by subsystem,
   - API route method/path pairs,
   - job kinds and handlers,
   - DB tables/migrations and their owning modules,
   - provider/model entry points,
   - network fetch entry points,
   - config/env keys,
   - test modules and collection count,
   - generated/eval artifacts,
   - archived versus active docs,
   - experimental or disabled modules.
4. Search for likely duplication:
   - same-module duplicate function/class names,
   - near-identical route handlers,
   - duplicated helpers implementing protected responsibilities,
   - `*_v2`, `new_*`, `old_*`, `backup_*`, `copy_*` code files,
   - multiple live docs for one mission/responsibility.
5. Record current structural debt without changing it yet.

### R0 deliverable

A short baseline section added to this mission containing counts, confirmed problems, false positives, and a "do not touch" list.

### R0 gate

Full deterministic baseline is green or every pre-existing failure is reproduced and explicitly classified. No behavior change.

# R1 - Documentation and root hygiene

The latest supplied state document already identifies completed mission documents as a source of confusion. Fix the navigation problem first because every future agent depends on it.

1. Determine the canonical active reading path.
2. Move completed/historical mission docs and old state snapshots into `docs/archive/` or the repository's existing archival location after a reference sweep.
3. Resolve duplicate personal/snapshot doc copies such as any `Claude outputs/` mirror. Prefer one canonical copy plus history in git. If the folder serves a real user workflow, mark it clearly as non-authoritative and prevent agents from reading it as current truth.
4. Ensure active root mission docs have explicit status.
5. Add a deterministic root-doc/reference check.
6. Fix active-doc links that point at moved files.
7. Do not rewrite historical content just to make it pretty.

### R1 gate

A new session can identify the current state, architecture rules, delivery rules, active mission, and quality contract without reading archived missions. No active document points at a missing file. Root clutter cannot silently grow again.

# R2 - Build `repo-check` in report-only mode

Implement the native repository-health command described in `QUALITY-CONTRACT.md` using the current CLI conventions.

Initial checks should be deterministic and cheap. Prefer Python AST/route/test metadata and repository filesystem inspection over model judgment.

At minimum report:

- duplicate same-module definitions,
- duplicate API method/path pairs,
- unexpected root docs/files,
- archived/completed missions still presented as active,
- broken references from front-door docs,
- suspicious duplicate/experimental filenames,
- test discovery anomalies,
- known forbidden-boundary patterns that can be detected reliably without excessive false positives.

Every finding must include file/location, rule, severity, and why it matters.

### R2 rule

**Do not block release yet.** First prove signal quality on the real repo.

### R2 gate

The command is deterministic, $0, does not open the live DB externally, produces stable output on two consecutive runs, and has fixture tests for each rule.

# R3 - Close correctness and flakiness debt first

Use the baseline to prioritize P0/P1 problems. The supplied state snapshot specifically names a flaky test roughly once in nine full runs and current local-provider fallback behavior as known issues. Re-verify current truth before acting.

For each confirmed correctness/flakiness issue:

1. Reproduce it.
2. Identify the invariant it violates.
3. Add or strengthen a regression test that fails for the actual mechanism.
4. Apply the smallest fix.
5. Stress/repeat the relevant test enough to make the old intermittent failure meaningful.
6. Record the mechanism and honest limits.

Do not "solve" a flaky test by retrying it automatically or weakening assertions unless the asserted behavior itself is invalid.

### R3 gate

Confirmed P0/P1 issues selected for the rung are fixed with regression coverage; full suite/Tier 1/release ritual passes.

# R4 - Architecture-drift guardrails

Turn the most important standing architecture rules into executable checks where reliable.

Candidates, after inspecting current code:

- model calls bypassing the provider/contracts entry points,
- user-controlled HTTP fetches bypassing the safe fetch path except documented exceptions,
- background threads/queues created outside approved infrastructure,
- direct SQL outside the DB ownership pattern if the codebase intends all SQL to live centrally,
- duplicate source-ingestion pipelines,
- duplicate project/source identity logic,
- API writes that bypass canonical service/domain operations,
- new config keys without registration/documentation,
- schema changes violating additive migration rules.

Do not write crude grep rules that punish valid code. Prefer AST, import, registration, or explicit allowlist checks with tests.

### R4 gate

At least the highest-value drift rules are machine-enforced, with explicit exceptions for legitimate architecture and no known noisy false-positive flood.

# R5 - Critical workflow regression suite

Build a compact task-based regression layer for workflows whose failures unit tests can miss.

Do not create a browser-test empire. Start with the smallest deterministic representation that crosses real subsystem boundaries and can run in the existing release environment.

Required workflow contracts should cover current equivalents of:

1. Project creation and context refinement.
2. Existing global source reused in another project without duplicate acquisition.
3. New source progresses through canonical ingestion to retrievable state.
4. Cross-source chat answer returns valid citations.
5. Findings approval/dismissal changes downstream behavior correctly.
6. Research state remains coherent after evidence/status changes.
7. Planner uses current project evidence and preserves provenance.
8. Retry/recovery of a transient job is idempotent and does not double-spend/double-create.
9. Restart/recovery does not lose durable queued work.
10. UI/server version mismatch or stale-client condition is surfaced honestly.

For information-architecture changes, add explicit workflow assertions for action semantics and state consequences, not just DOM presence.

### R5 gate

The suite catches at least one deliberately introduced representative regression per workflow family during test development, then passes on current production behavior.

# R6 - Design and interaction drift integration

Do not invent another design critique system.

If `design.md` defines the visual system and `audit.md` defines the design audit, wire release QA to those artifacts:

- identify which changed surfaces require visual/design review,
- run deterministic design-system checks where possible,
- preserve screenshot/reference comparisons only where they are stable and useful,
- test responsive/interaction states for touched components,
- require a human visual gate for meaningful UI changes.

Add task-based checks after major IA/workflow changes: can a new user identify the next action, predict the consequence, and recover from a mistake?

### R6 gate

The quality system can distinguish code correctness from design conformance and from workflow usability. It does not claim a UI is "good" merely because a visual linter passes.

# R7 - Operational stabilization

Use current Health/Doctor/log/release infrastructure. Do not create a parallel observability stack.

Exercise and gate the relevant current behaviors:

- startup refusal/failure is clear,
- restart after crash is recoverable,
- logs distinguish crash/deadlock/startup/provider failure,
- stuck invocations/jobs are reaped according to current rules,
- backup/integrity mechanisms remain valid,
- budget/rate/provider gates recover through supported paths,
- retries and external pending work remain idempotent,
- paid fallback cannot happen invisibly.

### R7 gate

Operational failures selected for coverage are observable, classifiable, and recoverable without direct live-DB surgery.

# R8 - Turn `repo-check` from observer into regression gate

Once R2-R7 establish a clean enough measured baseline:

1. Freeze the accepted baseline in a small machine-readable artifact or tests.
2. Make new violations blocking while grandfathered debt remains visible.
3. Ratchet debt downward as cleanup rungs land.
4. Integrate the check into the existing release-check rather than creating a competing release system.

### R8 gate

A change that adds a duplicate route, shadowed function, forbidden architecture path, or new root-doc clutter fails before release.

# R9 - Bounded maintainability cleanup

Only now pay down P2 maintainability debt.

Work in subsystem-sized rungs. Candidates may include:

- dead modules/functions proven unused,
- abandoned experimental alternatives already rejected by measurement,
- duplicated helper logic,
- stale compatibility shims,
- confusing names,
- modules that have become too broad and cross multiple responsibilities,
- giant UI-file sections that can be separated without introducing a heavy build system, if evidence supports it.

For every cleanup rung:

- preserve behavior,
- add characterization tests first when behavior is poorly specified,
- remove the old path in the same rung when safe,
- avoid temporary coexistence that becomes permanent,
- measure whether complexity actually decreased.

### R9 gate

No user-visible behavior change unless explicitly specified; all protected baselines are equal or better; `repo-check` debt count moves downward or remains flat with a documented reason.

# R10 - Closeout and make the system self-maintaining

At completion:

1. Integrate durable rules into `QUALITY-CONTRACT.md` and executable gates.
2. Remove temporary stabilization-only scripts that are no longer needed.
3. Update the current State of the App with the resulting QA/repo-health capabilities and remaining known debt.
4. Archive this mission.
5. Confirm `HANDOFF.md` and `CLAUDE.md` link to the permanent quality contract but do not copy its full contents.
6. Confirm `AGENTS.md`, if present for Codex, remains a thin pointer rather than a second architecture manual.

## Severity model

- **P0:** data loss/corruption, security, uncontrolled spend, false evidence, unrecoverable work, serious user deception.
- **P1:** regression, flakiness, duplicate architecture, broken recovery, conflicting state ownership.
- **P2:** maintainability debt, dead code, duplicate helpers, confusing structure, stale compatibility.
- **P3:** cosmetic cleanup.

Priority is P0 -> P1 -> P2. P3 is opportunistic only.

## Rules for Claude and Codex working concurrently

1. One agent owns a subsystem/rung at a time.
2. No two agents independently "solve" the same debt.
3. Before starting, inspect git status and the current mission log.
4. Keep commits/rungs narrow enough to attribute regressions.
5. Rebase/reconcile against current repository truth before delivery; never overwrite newer work from an older sandbox copy.
6. Share durable decisions through repository docs/tests, not private chat context.
7. Tests and gates arbitrate disagreements about behavior; `CLAUDE.md` arbitrates architecture; the current mission arbitrates scope; Kyle arbitrates product intent.

## Definition of mission success

This mission succeeds when adding features becomes safer without requiring every future agent to perform another giant stabilization pass.

The durable outcome is:

- fewer active documents,
- one clear reading path,
- deterministic repo-health checks,
- architectural drift gates,
- critical workflow regressions,
- design QA attached to the existing design system,
- operational recovery checks,
- a release gate that prevents structural debt from growing,
- and a repository where historical work is available without being mistaken for current instruction.
