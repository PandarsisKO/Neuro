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
