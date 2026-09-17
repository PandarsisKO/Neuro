# State of the App — 2026-09-16 15:40 PT

Current orientation source for the Neuro Search mission; `STATE-OF-THE-APP-2026-09-16-1511.md` and older are
archived evidence in `docs/archive/`. Written at the close of the overnight mission Kyle approved with six
corrections — see HANDOFF.md's tail for the full execution trail (Phase A's root-cause investigation, Phase B's
product-intent write-up, CR3/CR4's design, CR8's seam documentation, LP5's provenance wiring).

## Where main is

- Local `main` tip: `7c356ad`. App/package version **0.63.91** (unchanged all night — this mission treats the
  whole overnight train as one release, not a per-rung bump).
- Full suite **1,787 passed, 0 failed**, confirmed clean across 4+ consecutive `pytest -n 4 --dist=loadscope`
  runs (this is Phase A's 1,766 + CR3/CR4's 13 new tests + LP5's 8 new tests). `repo-check: PASS`. Commit-bound
  `release-check --no-pytest` **PASS** at `0c14c01` (0.63.91) — genuine git_sha, no `nogit`.
- No paid provider call was made at any point tonight. Every validation used fake providers or fixture
  databases; the test workspace (`ns-verify-git/src2`, a `git clone --local` of the real repo, no `.env`) never
  had a real API key available to it.
- Still unpushed — the sandbox cannot reach GitHub; Kyle pushes from the Mac terminal when he chooses to.

## What shipped tonight, in order

1. **Phase A** — S50 design-drift ceiling fix (real drift, not pre-existing as earlier entries wrongly claimed)
   and the actual root cause of the `-n 4`-only flaky tests: a pooled `anyio` worker thread outliving a test
   fixture's `settings.data_dir` swap. Fixed at the root in `db.connect()` (self-healing per-thread reconnect,
   provably a no-op in production). Full reproducer + bisection trail in HANDOFF.md.
2. **Phase B** — Continuous Research product intent written into `PRODUCT-INTELLIGENCE-MISSION.md` §13:
   MONITOR ≠ ACQUIRE ≠ RETAIN, three separate decisions with separate defaults, never collapsed.
3. **CR3 + CR4** (`neurosearch/reservoir.py`) — known-reservoir rescan and metadata-first change detection,
   project-scoped scan state (`reservoir:scan:<project_id>:<collection_id>`) to prevent a real cross-project
   candidate-starvation bug a global per-collection key would have caused. CLI-only (`project rescan`), never
   scheduled, never touches `sources`/ingestion.
4. **CR8** — the seam between a new Candidate Index row and an existing acquisition path
   (`research_needs.for_project`/`candidates.where_to_look`/`_best_fit`/`candidates.link`) documented in
   `EXECUTION-LADDER.md`. Explicitly NOT built — the real blocker is a product decision (where per-collection
   "primary for this project" monitoring classification is stored), not implementation effort.
5. **LP5** (`plan_updates` provenance) — `claim_id`, `tension_id`, `decided_at`, `decided_by`, `applied_plan_id`
   added via the existing additive migrations mechanism, verified genuinely missing before adding any. A single
   `plan_updates` row now reconstructs the full story of a plan-patch decision on its own.

## Standing constraints unchanged

Never open `data/neurosearch.db` from the sandbox (enforced by `db.refuse_bridge_mount`); cost disclosure before
any spend; `claims.set_status` is the only promotion door; two commits per rung; no paid provider calls without
Kyle's explicit go-ahead.

## What's next (unresolved, by design)

- The per-collection "primary for this project" monitoring-classification storage question (§13, CR8) — a real
  product decision, not guessed at tonight.
- CR7, LP6, AD4B, FM1 live — each needs a specific Kyle action, named in `EXECUTION-LADDER.md`. Not touched.
- Nothing else is queued as ready, Kyle-free work in the Claude lane right now.
