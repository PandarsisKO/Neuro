# State of the App — 2026-09-12 19:23 PT

This checkpoint supersedes `STATE-OF-THE-APP-2026-09-12-1910.md`.

The ownership split is now operational. Codex's backend/T1 chain is on `main`; Claude's Audit/Design work is to run
from a separate `design/f0` worktree pinned after the self-consistent baseline. Codex will not modify the design-owned
surfaces until F0 closes: `AUDIT.md`, `DESIGN.md`, `DESIGN-MISSION.md`, `docs/design-audit/**`, `test_s50`, or
`neurosearch/web/index.html`.

The self-consistent baseline is commit `d95f4b3` (UI `index.html` at `21bb117`, followed by Bootstrap relevance and
resource-routing fixes). T1 correctness and test isolation are committed after it at `fd66241`. The complete
commit-bound release check for `fd66241` passed in 172.6 seconds; artifact:
`evals/release/release-check-0.63.43-fd66241-20260912-192249.json`. The only failing economic behavior remains the
pre-existing, intentionally deferred H1 batch gate.

The live corpus was re-attested at 19:07 PT: 37,629 valid 1,536-dimensional chunk vectors, zero malformed. The
current zero-cost preview is 39,740 derived objects across the three retained projects, 416 project-bounded batches.
No paid embedding work was queued or run. The next T1 gate is explicit spend authorization, followed by the
version-stamped semantic cohort.

The working tree still contains Claude's uncommitted Bootstrap/resource/UI/test changes plus untracked QA/design
documents and inspiration assets. They remain preserved and are outside Codex's committed T1 chain.
