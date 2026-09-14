# State of the App — 2026-09-14 12:17 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Local `main` is at documentation tip `56fa21c`; the latest tested code checkpoint is `ceca6e5` (Claude's T5
  evidence correction is in ancestor `39f27f4`), and the latest product-code checkpoint remains `1e6b632`.
  App/package version is `0.63.90`.
- The post-cleanup full suite is **1,439 passed, 1 warning**. The sole pre-cleanup failure was the
  release-check test asserting PASS while `repo-check` saw Kyle's operational `KEEP AWAKE - overnight.command`
  root entry. That helper was moved intact to `/Users/kyleowen/KEEP AWAKE - overnight.command` without broadening
  the repository allowlist, and the failing test now passes in isolation; `repo-check` is now PASS and
  commit-bound `release-check --no-pytest` most recently passed at docs tip `59b9b49` (artifact
  `evals/release/release-check-0.63.90-59b9b49-20260914-130613.json`).
  No paid provider call was made by this cleanup.
- T3's exact-span gold gate is **closed**: 252 predicted records across the 60-row seeded queue were manually
  adjudicated with zero false positives; every per-kind and overall precision floor is 1.00. The two remaining
  T3 issues are recall-only structural gaps and are explicitly non-blocking.
- T4 is shipped as a deterministic selector plus a tested **$0 executor-routing dry run**. Claude then exercised
  the existing `findings.suggest_for_source()` pipeline through the documented bridge on nine sources: 57
  successfully recorded Sonnet calls, **$3.251579** recorded across T4, 358 suggested findings, and useful
  substance separation on the acquisition-specific sources. A first third-batch attempt also made 17 real calls
  before a five-minute timeout; those responses were not checkpointed and cost approximately **$0.79** outside the
  app ledger. The rerun now checkpoints after each source. The dry-run path itself still never calls
  `providers.route()` or starts a worker; a general live executor and structured-delta write path remain separately
  admitted future work. Combined actual T4 + T5 spend today is approximately **$4.04** ($3.255347 recorded in-app
  plus the disclosed lost spend). No further paid work is authorized under the current allowance.
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
- The latest verified history-free GitHub safety snapshot is remote commit
  `86e14a72e7688a737b66234b94211f088d59ff37`, refreshed from the current committed `main` tree. The snapshot branch
  excludes `VIDEOS/`, `data/`, and `_to_delete/`. `origin/main` remains at `67520c9` because its reachable local
  history contains retired multi-gigabyte video blobs that GitHub will reject; local `main` history is unchanged.

## Current low-cost cleanup gate

The active work is deterministic control-plane and reliability cleanup only:

1. Reconcile stale scheduler/state documentation against the T3/T4/T5/T6 facts above.
2. Isolate fake-OpenAI breaker state between tests without changing production behavior unless evidence requires it.
3. Add or strengthen pure no-provider/no-write tests for T4 dry-run and T5 proposal/blocked-credential paths.
4. Run focused tests, full regression, `repo-check`, and commit-bound `release-check`; record failures exactly.

No live T5 execution, paid inference, T4 provider routing, or structured-delta write path is authorized by this
checkpoint.

## Final optional-validation checkpoint — 2026-09-14 12:46 PT

The full current suite passes **1,439/1,439** with the existing Starlette deprecation warning. The known native
restart race remains green (18/18), and the two documented T3 recall-only gaps have explicit tests. Claude's T4
bridge scratch request/response files were preserved outside the repository at `/Users/kyleowen/neuro-t4-bridge/`;
the repository root remains clean under `repo-check`.

## Optional cleanup follow-through — 2026-09-14 12:44 PT

The stale detached F0 worktree metadata was verified and pruned; no `design/f0` branch or live worktree existed.
`tests/test_s43_foundation.py` passes **18/18**, and T3's bracket-label and unpunctuated-cue recall gaps now have
explicit regression coverage. No production extractor or scheduler behavior changed.

## Claude T4 second-batch checkpoint — 2026-09-14 12:47 PT

Claude ran the next six T4-selected sources through the unchanged findings pipeline: 33 real Sonnet calls cost
`$1.9937`, and 165 additional suggested findings were materialized. The two acquisition-specific sources scored
substance 68 and 83; the other four scored 5–26. Combined T4/T5 spend is `$2.346612`; no further paid calls are
authorized while allowance is constrained.

## Claude T4 third-batch checkpoint — 2026-09-14 12:50 PT

Claude ran six additional selected sources. The batch recorded `$0.908735` and 146 suggested findings; “Buy then
Build” scored substance 79. A prior attempt made 17 real calls before timing out without checkpoints, losing about
`$0.79` of billed spend and no usable output. The rerun added per-source checkpointing. Recorded T4/T5 spend is
`$3.255347`; estimated actual provider billing is roughly `$4.04`. No further paid calls are authorized.
