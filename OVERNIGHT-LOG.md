# Overnight log — 2026-09-10

Read this first in the morning. Newest entry at the bottom. Every line is a fact, not a plan.

Start: `1896030`, `v0.57.0`, tree clean, release-check PASS, app running.
Plan: `OVERNIGHT-MISSION.md`. Spend so far: **$0.00** (no paid call is possible from either environment).

| time PDT | rung | outcome |
|---|---|---|
| 21:15 | — | mission and ladder locked, starting F1 |
| 21:45 | **F1+F2+F3** | shipped **0.58.0** `0d8a2a8`, tag `v0.58.0`. `findings_quality.py` + review dialog. 653 tests, Tier 1 PASS, release-check PASS. Read-only: nothing changes a finding but your own sweep. |
| 21:55 | **F4** | shipped **0.58.1** `3df0976`, tag `v0.58.1`. Cap 12/8/120 → **20/12/200**, env-reversible; 3 D1 tests re-framed to the shape, recorded in HARDENING.md. 658 tests, Tier 1 PASS (frozen totals unchanged), release-check PASS. |
| 22:02 | **C1** | shipped **0.58.2** `568c31c`, tag `v0.58.2`. `creator_yield` + a master-source term in `candidates._potential`, project-scoped per the G4 split. 670 tests, Tier 1 PASS, release-check PASS. |
| 22:13 | **C2** | shipped **0.58.3** `72397ef`, tag `v0.58.3`. `where_to_look` + `untapped_by_creator`, on `pursue`'s result rather than its ladder. 676 tests, Tier 1 PASS, release-check PASS. |
| 22:23 | **C3** | shipped **0.58.4** `49ed50a`, tag `v0.58.4`. "Where to look" button in Research; `release-check` now runs `node --check` over the UI's 247 KB of inline JS and asserts UI_VERSION. 684 tests, Tier 1 PASS, release-check PASS. |
| 22:30 | **S0 + D1** | written up, **not shipped** — `SCHEDULER-ADMISSION.md` (restructures `claim_job`, your queue is live) and `FINDINGS-YIELD-DEBT.md` (needs your call: staging table vs the batch path). |
| 22:33 | **F5** | shipped **0.58.5** `603f998`, tag `v0.58.5`. `reserve` findings worth promoting — not vacuous and not repeats of what you approved. 690 tests, Tier 1 PASS, release-check PASS. |
| 22:45 | **calibration** | shipped **0.58.6** `4af7e4f`, tag `v0.58.6`. Measured the filter against your real 12,614 findings (read-only, from the hourly backup) and it found **two bugs in my own guesses**: the 400-note cap made duplicate detection report zero on a project with hundreds, and the 0.62 threshold was far too strict. Now **192 real duplicates in 169 groups (1.8%)**, cached on the view revision. Vacuity is 0.03% and that is correct — your findings are specific. 693 tests, Tier 1 PASS, release-check PASS. |
