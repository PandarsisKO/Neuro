# Cross-cutting RE-AUDIT — F1, F2, W1–W5 against the `evidence/` baseline

**Mode:** `AUDIT.md` §3 RE-AUDIT. **Baseline:** `audit.md` findings + `evidence/baseline/` (commit `21bb117`).
**Current:** audit instance rebuilt at commit `2462b81` (Rung W5 landed), then re-verified at `bc64e8a` (relTime
plural fix) with no further product change. **Date:** 2026-09-14. **Scope, per `ladder.md`'s sequencing note**
("one RE-AUDIT across every touched surface, against the `evidence/` baseline, before C1"): every surface named
in F1/F2/W1–W5's "Affected surfaces" fields — Home, the Chat sidebar footer, Sources, Findings, Master Plan,
Chat, and the global token block. Research was not touched by any landed rung and is out of scope here.

Every finding below was reproduced live on the audit instance (not inferred from commits), per `AUDIT.md` §3's
RE-AUDIT instruction. Screenshots referenced as "current" were taken this pass at 1440×757/900, dark and light
theme as noted.

## Findings verified

| ID | Rung | Verdict | Evidence |
|---|---|---|---|
| `H-1` | W5 | **RESOLVED** | Home and the Chat sidebar footer both now render `statusBar()`'s separated segments (health dot + label, today, month, de-emphasized split detail) instead of one run-on sentence. Live, dark theme: Home reads as four visually distinct chunks with dividers; the narrower sidebar stacks the same chunks vertically. Matches the acceptance test — health and rough spend are readable in well under a second. |
| `H-2` | F2 | **RESOLVED** | Findings, Sources and Chat history all render through the shared `listState()` primitive; deterministic gate (`request-path purity — showing a loading state starts no job`) passes. Live: no surface rendered a blank, ambiguous period — content or an explicit empty/failed state appeared promptly on every navigation this pass. (The sandbox's fake-AI/local data doesn't reproduce the original 5–8s slow-network condition that motivated this finding; the deterministic + code-path evidence is what's load-bearing here, matching `H-2`'s own regression risk note.) |
| `H-3` | W2 | **RESOLVED** | Findings' three stacked banners are now one "REVIEW" entry point. Live, dark theme: "816 sources analysed against older inputs" expands to show why each sub-group needs attention (419 stale-and-carrying-weight vs. 397 stale-only) with every previously-visible priced option (Rebuild $0/background/API, Accept-as-usable, Hide for now) still reachable, plus two more collapsed categories (low-value findings, quality-check) below it. No stacked warnings above the work. |
| `H-4` | W4 | **RESOLVED** | Sources rows show exactly one primary action + a "⋯" overflow menu (Suggest findings / Transcript / Make priority / Remove from project / divider / Delete everywhere). Live, dark theme: confirmed across a scrolled sample of rows in different states (ready+analysed, ready+unanalysed); menu opens/closes correctly, dark-theme contrast intact. |
| `H-5` | W1 | **RESOLVED** | One vocabulary across Findings/Plan/Sources/Chat: "Rebuild · $0 · ~4h46m on Claude Code", "Rebuild in the background · $14.57", "Rebuild now · $29.14 on the API" — same three-cost-mode pattern appears on both Findings' review entry point and Plan's stale banner, live, dark theme. |
| `H-6` | W3 | **RESOLVED** | Master Plan shows one primary "Rebuild plan · $0.43" button with budget inline; the two costlier re-analyse variants sit behind a collapsed "Other ways to rebuild" disclosure. Live, dark theme: expanded and confirmed both priced alternates render correctly and collapse cleanly. "Start here" / "This week" still render above the fold, matching `DESIGN.md` §8's "action before analysis" direction — the strength this rung was required not to break. |
| `H-7` | F1 | **RESOLVED** | `--ok`/`--warn` on `--panel`: light 5.29:1 / 5.24:1, dark 8.72:1 / 9.66:1 — both themes ≥ 4.5:1 (computed from the live token block this pass, not re-typed from the original audit). `test_s50`'s eight gates (inline-style ceiling, colour-literal ceiling, type-scale, radius-scale, emoji-only-control naming, both-theme token completeness, AA contrast, ratchet-catches-a-regression) all pass. Inline `style=` attributes are down from the F0 baseline of 430 to at or under the current ceiling of 287 — a real, ratcheted reduction, not just a frozen ceiling. |
| `M-1` | W5 | **RESOLVED** | Live, dark theme: the three real seeded projects (all with sources) show `relTime()`'s relative dates ("updated 1 day ago", "updated 6 days ago"); the 0-source case (not present among the three real projects, verified by code path instead) renders a "Needs sources" tag per `home.js`. |
| `M-2` | W5 | **RESOLVED** | Live zoomed-screenshot comparison: "Your research in numbers" tile values (15px, `fun-sub`) now render visibly smaller than the project card titles above them (16px) — previously 22px vs. 16px, the inverted relationship the finding named. |
| `M-3` | W5 | **NO LONGER APPLICABLE** | Re-checked against current `home.js` before any W5 code was written: the whole `.pcard` div already carries the navigation `onclick`, not the title alone. Not reproducing against this baseline. No code change was needed; recorded in `audit.md` as a closed re-check rather than silently dropped. |
| `F0-3` | W5 | **RESOLVED** | The sidebar's brief/goal text now carries an explicit "BRIEF" label above the status footer instead of sitting unlabeled directly above it. Live, dark theme, confirmed via zoomed screenshot. |
| `L-5` | W5 (P1 fold-in) | **RESOLVED** | Version tag's ad hoc 11.5px inline override replaced with a 12px CSS rule, folded in because W5 already rewrote that exact footer block. |

## New problems introduced by these fixes

None found. Specifically checked for the two risks the rungs themselves flagged:

- **W2/W1's regression risk** ("hiding a priced action a user currently sees at once") — every previously-visible priced option on Findings' review entry point and Plan's stale banner is still visible, with the same $ amounts, live.
- **F1's regression risk** ("a token value read somewhere the ratchet doesn't count; the base-input fix changing an input's width") — `test_s50`'s "ratchet would catch a regression" test and "every colour token exists in both themes" test both pass; no visibly broken input width observed on Settings, Sources' add-source form, or the chat composer this pass.
- **W4's regression risk** ("row action overload just moves into the menu confusingly") — menu contents live-checked, ordered predictably (view/read actions, then priority/removal, then a divider before the one destructive action), matches the design intent, not a dumping ground.

One earlier false alarm during this pass, not a real regression: a mid-scroll screenshot on Sources briefly
showed a white-background row list against an otherwise dark-themed page. A second screenshot after the scroll
settled showed the correct dark background throughout — a stale/partial JPEG capture from the screenshot tool
mid-repaint, not a rendering defect. Noted here rather than silently discarded, per this audit's own evidence
discipline.

## Theme coverage note

This pass concentrated on **dark theme**, since F1 (token contrast) and W5 (status colours) are the two rungs
most sensitive to theme, and dark theme has historically had the weaker evidence trail (`audit.md`'s own
Assumptions section: "dark theme was not screenshotted, so no visual — only computed-contrast — verification").
Light theme was live-verified per-rung at landing time for W3/W4/W5 (see each rung's own `HANDOFF.md` entry) and
was spot-checked again here for Home. This is a residual-coverage note, not a gap in the RE-AUDIT's conclusions:
no theme-specific regression is plausible from CSS-only, token-based changes that `test_s50`'s both-theme gate
already covers.

## Deterministic gates (this pass)

`test_s44_frontend_integrity.py`, `test_s50_design_drift.py`, `test_s5_ui_syntax.py`: 26 passed. `test_core.py`,
`test_indestructible.py`: the same 12 `test_core` failures confirmed pre-existing/sandbox-environment-specific
across every rung since W3 (golden-eval/real-API-tier paths this sandbox cannot run) — unchanged by this RE-AUDIT
since no product code changed during it.

## Conclusion

Every High/Medium finding tied to F1, F2, W1–W5 is RESOLVED or, for `M-3`, correctly closed as no longer
applicable. No new regression was found on any touched surface. `C1`'s precondition ("W1–W5 landed and a
cross-cutting RE-AUDIT done") is satisfied — `C1` may start next.
