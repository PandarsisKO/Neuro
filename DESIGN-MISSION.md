# Neuro Search Design Mission

This mission governs the design-system work introduced alongside the product missions. It is subordinate to data
integrity, the active feature mission, and the pre-T1 admission gate in `DEVELOPMENT-OPERATING-SYSTEM.md`.

## Current status — 2026-09-12

**D0 — freeze the instruments: complete.** `DESIGN.md` is the visual source of truth, `AUDIT.md` is the inspection
contract, and `tests/test_s50_design_drift.py` is the non-regression ratchet. The token palette was measured for WCAG
2.1 AA and the initial drift ceilings were recorded in `HARDENING.md`. No product UI was changed as part of D0.

**D1 — evidence audit: next after the active pre-T1 gate.** Inspect the rendered application at the required desktop
and narrow widths, and exercise real loading, stale, empty, failure, and long-content states. Record findings in
`AUDIT.md` with evidence and affected surfaces. Do not redesign during D1.

**D2 — systemic fixes: admitted only from D1 evidence.** Select the highest-value root causes, implement one bounded
surface at a time, lower the S50 ceilings in the same change when a surface is cleaned, and run the frontend and
accessibility gates. Preserve feature-mission behavior and keep every change documented in `HARDENING.md` and
`HANDOFF.md`.

## Ordering and handoff

R9(c) remains the only open pre-T1 measurement. D1 may be prepared while it runs, but it must not change the active
priority or start a T1 migration. Once R9(c) is closed or explicitly deferred with a numeric revisit trigger, the
product scheduler owns the next rung. Claude and Codex should read this file, the newest `STATE-OF-THE-APP-*.md`,
`PRODUCT-SCHEDULER.md`, and `HANDOFF.md` before continuing.

## Acceptance evidence

- D0 files exist and agree on the same token set and drift baseline.
- D1 contains reproducible evidence rather than aesthetic assertions.
- D2 changes pass the relevant tests, preserve the protected paths, and leave a handoff note with the next incomplete
  rung.
