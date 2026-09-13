# Evidence baseline manifest

**No image files are retained from the F0 pass.** Six canonical screenshots were captured 2026-09-13 against the
pinned design baseline `21bb117` (Home light/dark, Sources empty-light, Findings empty-light, Sources failed-dark,
login-dark), but they were saved by the browser-automation tool into a macOS app-sandboxed temp directory reported
as `/tmp/...` that is not the same `/tmp` a normal shell can see, and is not reachable from either this session's
device shell or Kyle's own Terminal (`find / -name "screenshot-1789266*.jpg"` returned nothing). The files are
presumed gone — sandboxed temp files are typically cleaned up shortly after the process that wrote them exits.
This is a tooling limitation of this pass, not a decision to skip evidence capture; see `raw.md`'s F0 addendum for
what each state looked like, described in prose, and the "Assumptions / cannot verify" note in `audit.md`.

A future F0 or RE-AUDIT pass should either save screenshots directly into this repo's `evidence/` path (rather
than through this browser tool's own disk cache), or use a screenshot mechanism whose output path is verified
reachable before relying on it for a canonical evidence set.

Two other screenshots taken during this pass (Settings → Decisions & constraints on the real "buying businesses"
project, light and dark) captured Kyle's real Morgan Stanley account numbers and balances, present because the
audit instance is an unredacted copy of the live backup. They were never recoverable outside the same sandbox and
are presumed gone along with the rest — recorded here so their absence isn't mistaken for oversight. See `raw.md`'s
F0 addendum, "Incidental finding" section, for the procedural note this leaves for future passes.
