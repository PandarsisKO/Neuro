# State of the App — 2026-09-16 15:11 PT

Current orientation source for the Neuro Search mission; `STATE-OF-THE-APP-2026-09-15-1400.md` and older are
archived evidence in `docs/archive/`. Written mid-overnight-mission after Phase A closed clean; Phases B–F
(Continuous Research intent, CR3/CR4, CR8 seam docs, LP5) continue below this snapshot's timestamp — see
HANDOFF.md's tail for what actually landed after this was written.

## Where main is

- Local `main` tip at the time of this snapshot: `0fc7e3f`. App/package version **0.63.91** (unchanged tonight —
  Phase A was cleanup, not a shipped feature). Still unpushed: the sandbox cannot reach GitHub; Kyle pushes from
  the Mac terminal when he chooses to.
- Full suite **1,766 passed, 0 failed**, confirmed clean across 11+ consecutive `pytest -n 4 --dist=loadscope`
  runs in a row (was flaky roughly 1-in-3 to 1-in-6 before tonight's fix — see below). `repo-check: PASS`.
  Commit-bound `release-check --no-pytest` **PASS** at `3ab63eb` (0.63.91) — genuine git_sha, no `nogit`.
- No paid provider call was made tonight. Every validation used fake providers or fixture databases; the test
  workspace (`git clone --local` of the real repo, no `.env`) never had a real API key available to it.

## What Phase A actually found and fixed (the mission's headline result)

Three HANDOFF entries written earlier this week (during the send-screenshot repair rounds) mischaracterized two
real defects as "pre-existing" / "unrelated" / "the openai:embeddings circuit breaker". Both were wrong, and
both are now fixed with proof, not assumption:

- **S50 design-drift ceiling**: the JS colour-literal count (4 against a ceiling of 3) was real, freshly
  introduced drift from the send-screenshot repair round's own change to `research.js:122` — a hardcoded
  `#f7f8fa` that also never adapted to dark mode. Fixed by swapping to the existing `--panel2` token (ceiling
  restored to green, dark-mode bug fixed as a side effect).
- **The two `test_k_retrieval_fixes.py` failures that only ever appeared under `-n 4`**: NOT the circuit
  breaker. Reproduced with a standalone script outside pytest, then bisected in the real suite (binary search
  over one xdist worker's exact test order, ~480 tests down to one) to the actual live mechanism: FastAPI's
  *synchronous* route handlers run on a pooled `anyio` worker thread, not the main test thread. A test file's
  `autouse` fixture that swaps `settings.data_dir` for the duration of one test (e.g.
  `tests/test_r2_bootstrap.py`'s `_fresh`) can only reset `db._local.conn` on the **main** thread at teardown —
  it has no way to reach whichever anyio worker thread actually served that test's `client.*()` calls and
  opened its own connection to the swapped directory. That worker thread is reused by a later, unrelated test
  (thread pools are shared across the whole xdist worker process) and kept returning the swapped-away database.
  Fixed at the root: `db.connect()` now tracks the db_path each thread's cached connection is actually bound to
  and transparently reopens if the currently configured path has moved on — self-healing on *whichever* thread
  notices, not just the one that performed the swap. In production `settings.data_dir` never changes after
  startup, so this is provably a no-op there. Two tests that separately called a blanket `monkeypatch.undo()`
  mid-test (undoing a swapped-fixture's `data_dir` along with the patch they actually meant to undo) were fixed
  to use a scoped `MonkeyPatch.context()` instead, matching the existing safe idiom already used elsewhere in
  the suite. Full proof, reproducer, and bisection trail are in HANDOFF.md's Phase A entry.
- **Repo hygiene**: `STATE-OF-THE-APP-2026-09-14-1217.md` and `-09-15-1400.md` archived to `docs/archive/` so
  `repo-check`'s newest-state exemption is honest again (this file is now the only live one).

## What is in flight tonight, past this snapshot

Continuous Research CR3 (known-reservoir rescan) and CR4 (change detection) with corrections Kyle required
before implementation — reservoir-scan state must be project-scoped (not a global per-collection key alone,
to avoid a real cross-project candidate-starvation bug), CR4's no-op gate must require both "remote unchanged"
and "this project already reconciled" — plus the Continuous Research product-intent write-up
(Monitor ≠ Acquire ≠ Retain), CR8 (selective-acquisition seam) documented but not admitted, and LP5 (plan-patch
provenance) if capacity remains, with its schema additions verified against what `plan_updates` already stores
rather than assumed. See HANDOFF.md for what actually landed by morning.

## Standing constraints unchanged

Never open `data/neurosearch.db` from the sandbox (enforced by `db.refuse_bridge_mount`); cost disclosure before
any spend; `claims.set_status` is the only promotion door; two commits per rung; no paid provider calls without
Kyle's explicit go-ahead.
