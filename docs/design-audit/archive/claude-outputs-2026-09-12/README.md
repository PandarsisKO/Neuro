# Archived — root `Claude outputs/` folder, 2026-09-14

These four files were the untracked working copies in the root-level `Claude outputs/` folder, flagged by
`VESTIGIAL-INVENTORY.md` as needing "explicit comparison" before archival. That comparison, done tonight:

- **`T1-DESIGN-AUDIT-2026-09-12.md`** — superseded. The tracked `docs/T1-DESIGN-AUDIT-2026-09-12.md` says so
  explicitly in its own header ("the tracked file is the source of truth for future checkouts") and its content
  confirms every finding from this draft was carried forward and resolved (shared vector space, R9
  reproducibility) before implementation.
- **`f1-remaining-scope.md`** — superseded. `docs/design-audit/2026-09-13-b85c222/f1-remaining-scope.md` is a
  strict superset: same 140 lines plus a 2026-09-13 addendum recording the frontend-split re-verification.
- **`f1_step2n_width_auto.py`**, **`f1_step2o_icon_sprite.py`** — one-time landing scripts for F1's remaining
  `width:auto` and icon-sprite items, referenced by the scope doc above. F1 is confirmed RESOLVED (the
  cross-cutting RE-AUDIT's `H-7` entry, landed and RE-AUDIT-verified clean); these scripts already did their job.

No unique, unresolved content was found in any of the four — moved here rather than deleted, so the history
stays recoverable.
