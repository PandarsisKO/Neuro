# Evidence baseline manifest

Baseline commit `21bb117`. Eight canonical screenshots, all taken by Kyle directly on his own machine on
2026-09-12 (7:46–7:51 PM) against the audit instance (`http://localhost:8788`, `NEUROSEARCH_FAKE_AI=1`, $0
budgets) and saved as ordinary files — sidestepping the sandboxed-temp-path failure that lost the prior pass's
six screenshots (see git history on this file for that account). Each was cropped from Kyle's original capture
to remove browser chrome and, for the narrow set, his own desktop/iMessage window that sat alongside the
narrowed Chrome window in the original capture; no other edits were made.

## Desktop, dark theme (4)

Real project ("I want to start buying businesses…"), full window, browser chrome cropped out.

- `desktop-home-dark.png` — Home, project list + "Your research in numbers."
- `desktop-sources-dark.png` — Sources, project totals + live in-progress job queue.
- `desktop-findings-dark.png` — Findings, suggested-findings queue with approve/dismiss.
- `desktop-research-dark.png` — Research overview, "Do these next" ranked action cards.

These replace the six dark-theme desktop screenshots lost in the prior pass. They are not a clean
empty-state set (same real, populated project throughout, no login/failure/empty states) — see "still
missing" below.

## Narrow viewport (4)

Kyle's own machine, Chrome window narrowed to ~390pt CSS width (~498px at his display's pixel ratio) —
the resize-tool limitation noted in `raw.md`'s F0 addendum meant this had to be captured by hand. Cropped
to the app column only.

- `narrow-sources-numbers.png` — Sources, project-numbers panel at narrow width.
- `narrow-sources-list.png` — Sources, filter bar + source list at narrow width.
- `narrow-research-overview.png` — Research overview at narrow width.
- `narrow-chat-citations.png` — A chat answer with inline citation markers (`[1][6][12]`, etc.) at narrow
  width — closes the "chat with an answer + citations, narrow viewport" gap directly.

This is the first narrow-viewport evidence of any kind in this audit; `audit.md`'s completion table and the
narrow-viewport coverage note in `raw.md`'s F0 addendum are updated accordingly.

## Still missing / not claimed as closed

- No narrow-viewport Home screenshot.
- No login page, empty-project, or failure-state screenshot at either width in this set (the read-only pass's
  prose description in `raw.md` is the only record of those states; no image evidence backs them).
- The desktop set is single-theme (dark) and single-project (the real, populated one) — not the varied
  light/dark, empty/populated matrix a from-scratch baseline would ideally have.

## Retention

This replaces the empty baseline left by the previous pass in full — no historical images are being kept
alongside it, per the retention policy (`AUDIT.md` §... — one canonical `baseline/` set, replace rather than
accumulate). A future pass should replace individual images here as better ones become available, not add to
this set indefinitely.

## Incidental finding (unchanged from prior manifest)

Two screenshots taken during the *prior* (lost) pass captured Kyle's real Morgan Stanley account numbers and
balances, because the audit instance is an unredacted copy of the live backup. Those images were never
recoverable and are not part of this or any evidence set. See `raw.md`'s F0 addendum, "Incidental finding"
section, for the procedural note this leaves for future passes.
