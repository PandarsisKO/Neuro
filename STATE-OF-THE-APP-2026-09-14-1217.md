# State of the App — 2026-09-14 12:17 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Local `main` is at documentation tip `69a2ec9`; the latest tested code checkpoint is `ceca6e5` (Claude's T5
  evidence correction is in ancestor `39f27f4`), and the latest product-code checkpoint remains `1e6b632`.
  App/package version is `0.63.90`.
- The post-cleanup full suite is **1,438 passed, 1 warning**. The sole pre-cleanup failure was the
  release-check test asserting PASS while `repo-check` saw Kyle's operational `KEEP AWAKE - overnight.command`
  root entry. That helper was moved intact to `/Users/kyleowen/KEEP AWAKE - overnight.command` without broadening
  the repository allowlist, and the failing test now passes in isolation; `repo-check` is now PASS and
  commit-bound `release-check --no-pytest` is PASS at the current docs tip `8d15a2e` (artifact
  `evals/release/release-check-0.63.90-8d15a2e-20260914-123747.json`).
  No paid provider call was made by this cleanup.
- T3's exact-span gold gate is **closed**: 252 predicted records across the 60-row seeded queue were manually
  adjudicated with zero false positives; every per-kind and overall precision floor is 1.00. The two remaining
  T3 issues are recall-only structural gaps and are explicitly non-blocking.
- T4 is shipped as a deterministic selector plus a tested **$0 executor-routing dry run**. It does not call
  `providers.route()`, start a worker, invoke a provider, or write research state. A fully live executor remains a
  separately admitted future step requiring provider routing and structured-delta persistence.
- T5 is shipped as a deterministic escalation proposal and a real adjudication-call path. One real adjudication
  was executed through a documented egress bridge because this device's MITM egress returns a false `401` for
  `api.anthropic.com`; the key was valid. It cost **$0.003768** (474 input / 282 output tokens), recorded in the
  real cost ledger, and produced suggested note `29360`; Claim and tension status stayed unchanged. Do not retry
  or spend further with T5 while the weekly allowance is constrained; any future native call must first have a
  verified egress path.
- T6's assumption ledger is shipped and informational only; drift warns and never fails a release.
- Claude's design/audit work is complete through all 22 declutter findings. D0/D1/F0 remain frozen; any future
  design work starts from fresh evidence.
- Claims work remains paused. R8 retention is observational until after 2026-10-11 17:28 PT. R9(c) remains
  deferred behind its numeric trigger; `bge-m3` remains reserved for a separately gated full-space migration.
- The last verified history-free GitHub safety snapshot is remote commit `de9866dd8054aaa1602064606f2a2157fc7ebe4b`.
  The snapshot branch excludes `VIDEOS/`, `data/`, and `_to_delete/`; local commits after that snapshot still need
  a credentialed refresh.

## Current low-cost cleanup gate

The active work is deterministic control-plane and reliability cleanup only:

1. Reconcile stale scheduler/state documentation against the T3/T4/T5/T6 facts above.
2. Isolate fake-OpenAI breaker state between tests without changing production behavior unless evidence requires it.
3. Add or strengthen pure no-provider/no-write tests for T4 dry-run and T5 proposal/blocked-credential paths.
4. Run focused tests, full regression, `repo-check`, and commit-bound `release-check`; record failures exactly.

No live T5 execution, paid inference, T4 provider routing, or structured-delta write path is authorized by this
checkpoint.
