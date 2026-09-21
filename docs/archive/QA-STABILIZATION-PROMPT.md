# Launch Prompt - QA / Stabilization Mission

> **Historical (2026-09-21):** the mission this prompt launches was closed and archived on 2026-09-13. Kept for the record only.

Use this same prompt with Claude Code or Codex.

---

You are taking ownership of the Neuro Search QA, stabilization, and repository-control mission.

Your objective is **not** to do a giant cleanup and not to maximize the number of issues you can report. Your objective is to make the repository progressively harder to regress and harder to clutter while preserving current product behavior and the hard-won architecture.

## Read first, in this order

1. `HANDOFF.md`
2. `CLAUDE.md`
3. `QUALITY-CONTRACT.md`
4. the newest `STATE-OF-THE-APP-*.md`
5. `docs/archive/missions/QA-STABILIZATION-MISSION-2026-09-13.md`
6. the relevant portions of `HARDENING.md`
7. current release/check tooling and the tests that gate the areas you will inspect
8. `DESIGN.md` and `AUDIT.md` only for design/UI QA responsibilities, if those files exist

The current repository is the source of truth. Older mission documents may describe behavior that has already shipped or changed. Search the implementation before assuming a requested system is missing.

## Hard constraints

- Follow every standing safety rule in `CLAUDE.md` and `HANDOFF.md`.
- Never open the live SQLite database from an external session. Use the supported API/CLI or a safe copied backup exactly as current repo rules specify.
- Do not make paid model calls for this mission unless Kyle explicitly authorizes a specific live evaluation.
- Do not create parallel infrastructure for jobs, ingestion, storage, providers, fetches, provenance, research state, release gating, or design QA.
- Do not add dependencies without a measured need and license/maintenance/removal review.
- Do not delete code based only on a linter/static-analysis warning.
- Do not weaken tests to make the suite green.
- Do not solve flakiness by automatic retries unless the product contract itself permits retries.
- Do not turn every existing warning into a blocker immediately. Baseline first, prevent new debt, then ratchet old debt down.
- Do not create another giant process document. Durable rules go in `QUALITY-CONTRACT.md`; evidence belongs in existing evidence/history docs; this mission file carries only the active ladder/status.

## Start with R0 only

Before changing production code, establish the current truth:

1. Run the required deterministic baseline from `HANDOFF.md`.
2. Inventory root docs/files, modules/subsystems, routes, jobs, tables/migrations, provider/fetch boundaries, config keys, tests, experiments, and archives.
3. Search for duplicate definitions, duplicate routes, parallel implementations, orphan/dead code candidates, suspicious `v2/new/old/copy` files, and duplicate live documentation.
4. Reconcile the inventory against the newest State of the App and architecture map.
5. Classify findings P0/P1/P2/P3.
6. Separate confirmed defects from false positives and intentional alternatives.
7. Add a concise R0 baseline to `docs/archive/missions/QA-STABILIZATION-MISSION-2026-09-13.md`.

**Do not begin broad cleanup during R0.** The only code changes permitted in R0 are test/instrumentation changes strictly necessary to measure the baseline, and even those should be avoided if current tooling can answer the question.

## Then propose the next rung

After R0, choose the smallest highest-value rung from the mission, biased toward:

1. correctness/safety,
2. flaky/regression behavior,
3. documentation/root confusion that affects every future agent,
4. architecture-drift prevention,
5. task-based regression coverage,
6. maintainability cleanup.

Before implementing the rung, state:

- the exact problem,
- evidence it exists,
- the invariant being protected,
- files/subsystems expected to change,
- regression surface,
- gate that will prove the fix,
- why this is not duplicating an existing mechanism.

Then implement in a bounded change and follow the repository's complete delivery/release ritual.

## Special instruction: repository mess

Treat repository structure as a product surface for future agents.

A completed mission should not remain in the active root reading path. A historical snapshot should not look current. A second copy of an instruction file is a bug even if its prose is correct. A new code path that duplicates an old responsibility is a bug even if both pass tests.

Prefer **one canonical home + executable gates + git history** over keeping multiple copies "just in case."

## Special instruction: QA layers

Do not conflate these:

- code/static QA,
- unit/contract tests,
- integration tests,
- task-based workflow regression tests,
- design-system/visual QA,
- first-time-user workflow/usability QA,
- operational/recovery QA,
- human final visual review.

A release can pass one layer and fail another. Report them separately.

## Completion behavior

At the end of each rung, report only:

1. what was proven before the change,
2. what changed,
3. which gates passed,
4. what risk/debt remains,
5. what the next best rung is.

Do not claim the repository is "clean" or "fully stable." Use measured statements.
