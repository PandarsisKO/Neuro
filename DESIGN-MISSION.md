# Neuro Search Design Mission

This mission governs the design-system work introduced alongside the product missions. It is subordinate to data
integrity, the active feature mission, and the pre-T1 admission gate in `DEVELOPMENT-OPERATING-SYSTEM.md`.

## Current status — 2026-09-12

**D0 — freeze the instruments: complete.** `DESIGN.md` is the visual source of truth, `AUDIT.md` is the inspection
contract, and `tests/test_s50_design_drift.py` is the non-regression ratchet. The token palette was measured for WCAG
2.1 AA and the initial drift ceilings were recorded in `HARDENING.md`. No product UI was changed as part of D0.

**D1 — evidence audit: read-only half complete** (`docs/design-audit/2026-09-13-b85c222/{raw,audit,ladder}.md`,
commit `c45b754`). The interaction half, the missing state coverage and the `evidence/` baseline are rung F0 of
`ladder.md` — a design preflight that changes no product code and exits only when `AUDIT.md` §12 is fully marked.
F0 cannot start while any UI diff is uncommitted. The original D1 scope, for reference: Inspect the rendered application at the required desktop
and narrow widths, and exercise real loading, stale, empty, failure, and long-content states. Record findings in
`AUDIT.md` with evidence and affected surfaces. Do not redesign during D1.

**D2 — systemic fixes: admitted only from D1 evidence.** The rungs are `ladder.md` F1–P1; this file does not
restate them. Select the highest-value root causes, implement one bounded
surface at a time, lower the S50 ceilings in the same change when a surface is cleaned, and run the frontend and
accessibility gates. Preserve feature-mission behavior and keep every change documented in `HARDENING.md` and
`HANDOFF.md`.

## Ordering and handoff

R9(c) is explicitly deferred with a numeric revisit trigger after its external pull stalled. D1 may be prepared while
T1's measurement cohort is assembled, but it must not displace the active T1 rung. Claude and Codex should read this
file, the newest `STATE-OF-THE-APP-*.md`,
`PRODUCT-SCHEDULER.md`, and `HANDOFF.md` before continuing.

## Acceptance evidence

- D0 files exist and agree on the same token set and drift baseline.
- D1 contains reproducible evidence rather than aesthetic assertions.
- D2 changes pass the relevant tests, preserve the protected paths, and leave a handoff note with the next incomplete
  rung.
