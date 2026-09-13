# Neuro Search Design Mission

This mission governs the design-system work introduced alongside the product missions. It is subordinate to data
integrity, the active feature mission, and the pre-T1 admission gate in `DEVELOPMENT-OPERATING-SYSTEM.md`.

## Current status — 2026-09-13

**D0 — freeze the instruments: complete.** `DESIGN.md` is the visual source of truth, `AUDIT.md` is the inspection
contract, and `tests/test_s50_design_drift.py` is the non-regression ratchet. The token palette was measured for WCAG
2.1 AA and the initial drift ceilings were recorded in `HARDENING.md`. No product UI was changed as part of D0.

**D1 — evidence audit: complete** (`docs/design-audit/2026-09-13-b85c222/{raw,audit,ladder}.md`, merged to `main`
at `79c4446`). Rung F0 of `ladder.md` closed on 2026-09-13 (addendum 3, commit `0520d07` on the now-merged
`design/f0` history): the six-flow runtime verification matrix, a failed/recoverable job-state check, a naturally
occurring stale-poll finding (`F0-4`), narrow-viewport interactive verification (Master Plan, Sources), and a
qualitative timing baseline are all recorded with evidence classification (RUNTIME VERIFIED / SIMULATED RUNTIME /
STATIC ONLY / BLOCKED, `AUDIT.md` §4.5–§4.7). `AUDIT.md` §12's completion criteria are met or explicitly
"partly"/residual with a stated reason — see `audit.md`'s completion table and its Residual Coverage section, which
lists what is deliberately not chased further under the bounded stopping rule. No open F0 work remains; do not
reopen it to chase Residual Coverage items unless one turns out to change a Critical/High finding, a root cause, an
acceptance criterion, or the ladder's order.

Separately, `DESIGN.md` gained a durable "progressive disclosure without interaction tax" principle and a small set
of Apple-derived rules (simplicity is not minimalism, complexity just in time, context reduces copy, the Project
Creation exemplar) sourced from the new `APPLE-DESIGN-REFERENCES.md`. These are decision filters for choosing
between two functionally equivalent implementations, not additional checklist items — do not add disclosure
layers, animation, or controls merely to demonstrate compliance with them. `DESIGN.md`/`AUDIT.md`/
`APPLE-DESIGN-REFERENCES.md` are now frozen; do not expand them further unless implementation surfaces a genuine
contradiction or repeated failure.

**D2 — systemic fixes: eligible now.** The rungs are `ladder.md` F1–P1; this file does not restate them. F1 and F2
may run in parallel per `ladder.md`'s own sequencing note. Select the highest-value root causes, implement one
bounded surface at a time, lower the S50 ceilings in the same change when a surface is cleaned, and run the frontend
and accessibility gates. Preserve feature-mission behavior and keep every change documented in `HARDENING.md` and
`HANDOFF.md`. Coordinate through repo state (this file, `PRODUCT-SCHEDULER.md`, `HANDOFF.md`, commits) rather than
through either agent's chat context — see `HANDOFF.md`'s "Operating model" section.

## Ordering and handoff

R9(c) is explicitly deferred with a numeric revisit trigger after its external pull stalled. D1 is complete and does
not displace the active T1 rung; D2/F1 work should still avoid touching T1's active surfaces
(`neurosearch/t1.py`, T1 backfill code) and Codex's `neurosearch/web/index.html` ownership where a mission locks it
— reconcile from `ladder.md`'s named seams and current git state, not assumption. Claude and Codex should read this
file, the newest `STATE-OF-THE-APP-*.md`,
`PRODUCT-SCHEDULER.md`, and `HANDOFF.md` before continuing.

## Acceptance evidence

- D0 files exist and agree on the same token set and drift baseline.
- D1 contains reproducible evidence rather than aesthetic assertions.
- D2 changes pass the relevant tests, preserve the protected paths, and leave a handoff note with the next incomplete
  rung.
