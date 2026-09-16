# State of the App — 2026-09-15 14:00 PT

Current orientation source for the Neuro Search mission; `STATE-OF-THE-APP-2026-09-14-1217.md` and older remain
archived evidence. Written by Claude after a day of solo execution (Codex is out until the weekend reset; every
Codex lane was reassigned to Claude on 2026-09-15). Live per-item state is `EXECUTION-LADDER.md`; the one page
Kyle needs is `docs/KYLE-GATES-2026-09-15.md`.

## Where main is

- Local `main` tip: `d7d37ce`. App/package version **0.63.91** (bumped at L-40, `ed87c06`). **Nothing is pushed**:
  main is ~75 commits ahead of `origin/main` (github.com/PandarsisKO/Neuro); the sandbox cannot push (no GitHub
  credential, no SSH egress) — Kyle runs `git push origin main` from a Mac terminal.
- Full suite **1,580 passed, 0 failed** (`-rf`, run in the `~/ns-verify` copy on the Mac, never against the live
  DB). `repo-check: PASS`. Commit-bound `release-check --no-pytest` **PASS** at 0.63.91 (artifact name carries
  `nogit` because it ran from the copy). One unidentified intermittent: two full runs earlier today showed one
  failure before `-rf` capture was on; ten clean runs since. Not dismissed — recorded in HANDOFF.
- No paid provider call was made today by Claude. Every validation used fake providers or fixture databases.

## What shipped today (all code-complete, tested, committed; gates below)

- **P0 audit (Stage 1, L-10..L-17) — CLOSED.** Four real defects fixed: integrity_check's own pass/fail, stale-input
  retry, un-gated duplicate job racing a budget pause, harvest coalescing losing notes under concurrency.
  `docs/P0-AUDIT-2026-09-15.md`.
- **P1A scheduled backend (L-20) — CLOSED.** `not_before` productized: caller-scheduled jobs, missed-window
  policy, budget sweep no longer wakes schedules early, `neurosearch project rebuild-stale --at HH:MM`.
- **L-21 power assertion** — `caffeinate -s` held only while real/near-future work exists; honest off-macOS.
- **E7 / P2 nightly envelope (L-30)** — `nightly.py`: preflight → per-project `t4.execute` under one SHARED
  nightly cap; T5 adjudication under its own separate cap (L-60); idempotent per day; `neurosearch nightly
  status|run|report`.
- **Project Delta v0 (L-31)** — `delta.for_envelope()`: what changed / why / what Neuro did / spend, every number
  reconciled to a table; real before-snapshot captured at run time.
- **Morning Report v1 (L-41)** — `report.py`: the P3 hierarchy, "nothing important changed" first-class, never
  "the N things you need to review" (tested). v2's "What needs me?" exists behind a flag that stays OFF (L-52 prep).
- **Decision Impact v1 (L-50, earlier) + exception queue (L-51)** — `review_queue.build()`: disagreement never
  capped, hidden counts reported, structurally cannot approve. API route + CLI.
- **T5/T6 operationalization (L-60/L-61)** — decision-aware adjudication triggers + budgeted nightly pass;
  T6 surfaces a number only when the night's output provably leaned on it and it is unmeasured/broken/stale.
- **P1B "Tonight" UI (L-40)** — Now / Tonight / Overnight batch on the stale-rebuild action; scheduled state
  visible, cancel, run-now, "since you were away"; host-honest copy; a scheduled job is its own state (fixed an
  L-20 gap where it read as "retry wait").
- Upstream prep for Kyle-gated rungs: `tools/decide_kept_rate.py` (L-07 is one command once L-06 is filled in),
  `tools/p7_estimate.py` (L-70's dollar decision stated as a $0 read).

## Control-plane corrections made today

- `PRODUCT-SCHEDULER.md` still named the frontend split as the NOW blocker two days after it landed
  (2026-09-13, `7480352`); that stale line caused L-40 to be recorded as blocked. Fixed at `5bf451d`.
- L-04/L-05 `pending-sha` placeholders replaced with the real commits (`477113c`, `aa53a9c`).

## What is open, and exactly why (verified against the repo, not inferred)

Kyle — real-world measurements, each reduced to commands in `docs/KYLE-GATES-2026-09-15.md`:
L-00 (his overnight rebuild — now one click: When… → tonight), L-01 (`.zshrc`), L-06 (20-min blind review),
L-07 (one command after L-06), L-08 (Mac run with OpenAI key, ~$0.03), L-21 (lid/display test), L-30 (one $2
night — also closes L-31/L-41/L-60/L-61's data side), L-40 (schedule one real rebuild for tonight), L-51 (judge the
queue on his project), L-52 (flip the flag after L-51), L-70 (needs L-07 + a yes on the P7 estimate).
Codex — nothing: every Codex lane was reassigned and is code-complete.
Not admitted — Stages 10–13 (P8–P11), by the ladder's own text.

## Standing constraints unchanged

Never open `data/neurosearch.db` from the sandbox (enforced by `db.refuse_bridge_mount`); cost disclosure before
any spend; `claims.set_status` is the only promotion door; two commits per rung; a `[x]` means the gate passed,
`[~]` means code-complete and the gate is a measurement someone still has to take.

## Addendum 15:00 — acceleration directive absorbed

Mission §12, ladder Stages 10–15 (dependency graph + admission classes), scheduler NOW = CR1 + LP0/LP1 (planned,
not started; plan-then-pause handoff in HANDOFF). Verified: Source Capability mostly shipped at 0.58.3; refresh
policy exists in `claims.FRESHNESS_RULES`; plan patches already persist in `plan_updates`; finding embeddings are
unpopulated (H1 parked). P11 Neuro Everywhere = future/nice-to-have. No code changed since 0.63.91.
