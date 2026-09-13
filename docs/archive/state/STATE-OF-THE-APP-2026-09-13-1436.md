# State of the App — 2026-09-13 14:36 PT

This is the newest orientation source. Earlier state snapshots are archived evidence.

## Current release and custody

- `main` contains Claude's W1 step 4 landing and Codex's T2 implementation at `280146a`; the application/package is `0.63.65`.
- W1 step 4 discloses model-budget use on the legacy Sources “Re-analyse all” action. Claude owns the remaining F2/W1 browser and human re-score.
- T2 adds a bounded `detail=chunks` page to the authenticated existing transcript coverage route. It is derived and read-only: no new table, provider call, UI, or live-data mutation.
- T2 focused tests pass 31; full pytest passes 1,368 with one existing Starlette deprecation warning. Commit-bound release-check passes at `evals/release/release-check-0.63.65-280146a-20260913-143316.{json,txt}`.
- Real-corpus T2 measurement is `evals/t2/cohort-20260913-1435.json`, produced from a copied verified backup with no live-database access. All 38,038 retained-project chunk vectors were valid; timings and project-relative thresholds are recorded there.
- `repo-check` passes. The history-free GitHub safety snapshot remains `backup/2026-09-13-clean`; protected `VIDEOS/`, `data/`, and `_to_delete/` paths are absent from that tracked snapshot.

## Mission boundary

Foundation Phases 0–10 and Transcript Intelligence T1 and T2 are complete. R8 retention remains observational until 2026-10-11 17:28 PT. R9(c) remains behind its numeric trigger. Claims remains paused; historical unsettled batch results remain untouched.

Claude owns Design/Audit and the sequence `F0 → F1 → F2 → W1 → W2 → W3 → W4 → W5 → RE-AUDIT → C1 → P1`; F2/W1 browser evidence remains open. Codex owns backend, reliability, measurement, recovery, and Transcript Intelligence infrastructure.

## Next work

The next Codex-owned action is to prepare the T3 deterministic Tier-0 extraction admission and precision-gate proposal. T3 must remain model-free, versioned, idempotent, and measured on a hand-labeled sample before downstream work trusts it. Do not add a persisted extraction matrix or a new UI yet. Shared control-plane documents remain append-only.
