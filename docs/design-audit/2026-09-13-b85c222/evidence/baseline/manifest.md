# Evidence baseline manifest

Canonical before-state screenshots, captured F0 2026-09-13 against the pinned design baseline `21bb117`, on the
audit instance (`tools/audit-instance.command`, fake AI, $0 budgets). Per `ladder.md`'s retention policy: one
`baseline/` set, replaced on acceptance of a future change, not accumulated. Six images — a small canonical set,
not a screenshot-per-interaction log.

| File | Surface / state | Theme | Notes |
|---|---|---|---|
| `home-default-light.jpg` | Home, populated (3 real projects + empty probe) | Light | matches `H-1`, `M-1`, `M-2` |
| `home-default-dark.jpg` | Home, same state | Dark | `--ok`/`--warn` not visibly exercised here (no status pills on Home) |
| `sources-empty-light.jpg` | Sources, new empty project, incl. the library-scan "no matches" card | Light | new evidence, F0 addendum |
| `findings-empty-light.jpg` | Findings, new empty project | Light | strength: explicit, actionable empty-state copy |
| `sources-failed-dark.jpg` | Sources, `Failed 1` filter, real project, one failed row | Dark | supports `F0-2`; real project's other content out of frame |
| `login-dark.jpg` | Login page, unauthenticated | Dark | theme persists pre-login via `localStorage` |

Two additional screenshots taken during this pass (Settings → Decisions & constraints on the real "buying
businesses" project, light and dark) were **deleted, not retained** — they captured Kyle's real Morgan Stanley
account numbers and balances, present because the audit instance is an unredacted copy of the live backup. See
`raw.md`'s F0 addendum, "Incidental finding" section, for the procedural note this leaves for future passes.
