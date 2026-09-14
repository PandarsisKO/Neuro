# State of the App — 2026-09-14 12:17 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Local `main` is at documentation tip `0ac749c`; the latest tested product-code checkpoint is `1e6b632`.
  App/package version is `0.63.90`.
- The latest full-suite observation before this cleanup was **1,435 passed, 1 failed**; the sole failure was the
  release-check test asserting PASS while `repo-check` saw Kyle's operational `KEEP AWAKE - overnight.command`
  root entry. That helper was moved intact to `/Users/kyleowen/KEEP AWAKE - overnight.command` without broadening
  the repository allowlist, and the failing test now passes in isolation. No paid provider call was made.
- T3's exact-span gold gate is **closed**: 252 predicted records across the 60-row seeded queue were manually
  adjudicated with zero false positives; every per-kind and overall precision floor is 1.00. The two remaining
  T3 issues are recall-only structural gaps and are explicitly non-blocking.
- T4 is shipped as a deterministic selector plus a tested **$0 executor-routing dry run**. It does not call
  `providers.route()`, start a worker, invoke a provider, or write research state. A fully live executor remains a
  separately admitted future step requiring provider routing and structured-delta persistence.
- T5 is shipped as a deterministic escalation proposal and a real adjudication-call path. The real call is forced
  onto `api_only` and is blocked by the invalid Anthropic API key (`401 Unauthorized`); no cost was recorded and
  no note was written. Do not retry until the credential is refreshed.
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
