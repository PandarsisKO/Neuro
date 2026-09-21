# State of the App — 2026-09-17 11:30 PT

**Continuation update — 2026-09-19:** the dated snapshot below is historical where superseded by HANDOFF.
Current execution follows [docs/CONTINUOUS-EXECUTION-MISSION.md](docs/CONTINUOUS-EXECUTION-MISSION.md): CE0's
focused baseline and CHR3 implementation plus deterministic release proof are complete; screenshot/auth/course
acceptance, CHR3 paid/browser acceptance, existing-feature acceptance and a conditional subreddit delivery track remain.
CHR2 is closed. The 401/403 handlers exist; real-Chrome acceptance is still open.
Course start/cancel/reopen-after-cancel were observed; active-scan reopening, completion and CS7 document-fetch
acceptance remain. CHR3's delta-only context, 409 no-evidence refusal, material-first bounded provenance and
explicit control have deterministic coverage and a commit-bound release PASS at `e99ccac`, but no real paid
synthesis is claimed. Screenshot case 7 remains unclosed; case 6 cosmetics stay deferred. Subreddit's integrated
candidate `abdefaa` / evidence `c842861` passed 2,169 tests and release-check but is not delivered; official API
configuration was last observed false. No new runtime or live-acceptance claim is made by this planning update.
The new mission supersedes stale queue directions below, while existing feature contracts retain their gates.

Current orientation source for the Neuro Search mission; `STATE-OF-THE-APP-2026-09-16-1540.md` and older are
archived evidence in `docs/archive/`. Written to reconcile stale control-plane documents against current
repository reality — see `PRODUCT-SCHEDULER.md`'s new top-of-NOW note and this file's own content for what
changed since 09-16.

## Where main is

- `main` tip: **`d1b6a67`**, and it matches `origin/main` on GitHub — pushed and current, unlike the prior
  snapshot's "still unpushed" note (that was true on 09-16, superseded since).
- App/package version **0.63.91**, unchanged since the overnight mission. Extension `manifest.json` version
  **1.9.3**, unchanged since repair round 4 (2026-09-16) — the case 2/case 3/setup-screen fixes landed after
  1.9.3 shipped without their own version bump; the pending 401/403 UX fix and the Send Screenshot release gate
  (see below) are expected to close with a bump to 1.9.4.
- **Latest fully green full-suite baseline: 1,870 passed, 0 failed at `f13ca97`** (2 consecutive clean
  `pytest -n 4 --dist=loadscope` runs, HANDOFF.md line ~5636/5659). Everything shipped after that point (Send
  Screenshot case 2 fix, case 3's two fixes, the setup-screen lockout fix) was validated with its own focused
  test additions (63→65→66 in `tests/test_s54_send_screenshot.py`, then +4 for the setup screen = 70) plus
  before/after **differential** full-suite runs comparing the failure *name set*, not a fresh from-zero full
  count — each of those differential runs held an identical pre-existing/environmental failure set (≈40) with
  zero new failures introduced. `repo-check: PASS` at every one of those commits.
- No paid provider call has been made from this session's own actions today.

## What's current since the last snapshot (09-16 → 09-17)

1. **Send Screenshot cases 1–3: PASS**, each confirmed by live-Chrome acceptance plus pixel-level inspection of
   the actual stitched image (not job metadata alone) — case 1 (`59ed11b`, a credential-state issue, not code),
   case 2 (`d1d1ed0`/`bff98fb`, baked-in scrollbar bug, fixed and re-verified), case 3 (`c59a6bd`/`06578cc`/
   `91890a9`, two distinct defects — a reCAPTCHA-badge timing gap and a descendant-visibility-inheritance gap —
   found across three live re-verification rounds and fixed). Full detail: `docs/KYLE-GATES-2026-09-15.md`
   under "Send Screenshot", `HANDOFF.md` parts 3–7 and 9.
2. **Extension setup-screen lockout fixed** (`1e5aa34`/`108271f`): a real defect independent of the acceptance
   matrix — no Cancel affordance and no fetch timeout could strand the user in the settings screen with no way
   back if the app was unreachable. Fixed with a Cancel button (storage untouched until a successful Save) and
   an 8s save timeout with an honest message.
3. **A likely root cause identified for today's two live server incidents** — see the dedicated note below.
   Not yet a certainty; treated as the leading explanation pending direct confirmation.
4. **D2/F1 is not suspended.** The `## SUSPENDED — RESUME FIRST` section still in `PRODUCT-SCHEDULER.md` was
   proven closed on 09-16 by `386891b` ("D2/F1 Resume Delta — design ladder already fully closed, nothing to
   resume"); the scheduler section itself was never updated to say so until today's reconciliation note.
5. **Repository storage cleanup** (`d1b6a67`, current tip): orphaned worktree and disposable `data-audit/`
   removed; live database, backups, and Git history untouched.

## Today's live incidents — a likely root cause, not yet a proven one

Two SQLite failures hit the real server today: a burst of "database disk image is malformed" / "file is not a
database" errors at 09:43–09:44 (self-resolved on its own restart), and a harder `SIGBUS`/`EXC_BAD_ACCESS`
crash (`FS pagein error`, inside SQLite's WAL commit path) that required `restart.command` to clear a stuck
port. `CLAUDE.md`'s standing rule #1 documents this exact failure signature: opening `data/neurosearch.db` from
a bridge-mounted session — even read-only — can truncate the WAL `-shm` file underneath a running server's own
memory-mapped view of it, and the server gets killed with a SIGBUS matching what Kyle's crash report showed.

This session queried the live database directly (read-only) several times today, bracketing both incidents in
time. That timing makes this session's own live-DB opens the **leading causal explanation** — the signature
matches rule #1's documented mechanism closely — but it has not been directly proven (no reproducer was run,
and no server-side log entry names the offending connection). Treated as likely, not certain, per Kyle's
correction to the version of this note first drafted.

**Going forward: this session will not open `data/neurosearch.db` (or its `-wal`/`-shm`) directly again.**
Permitted paths, in the order `CLAUDE.md` prescribes: the app's own API through Kyle's browser; the
`neurosearch` CLI on Kyle's Mac; or a verified backup snapshot copied into this session's own scratch space and
queried there (never a live file, and never paired with `-wal`/`-shm` sidecars unless the specific backup being
restored is known to need them for consistency — see `data/backups/` and its documented restore procedure).

## Send Screenshot acceptance matrix — current status

- Cases 1–3: **PASS** (see above).
- Cases 4–7: **open.** Case 4 (close/reopen popup mid-capture) has partial evidence already gathered today (one
  clean capture completed correctly after Kyle pressed Escape mid-capture — single capture event, clean image,
  no duplication — but the popup-side observation of what was actually seen on screen is still needed before
  this counts as a verified pass). Cases 5 (scroll restoration), 6 (same-origin navigate-away), 7 (drawer
  provenance) not started.
- Deferred: the silent-401/403 UX fix in `popup.js`'s and `background.js`'s `api()` (and `apiForm()`) — bounded,
  scoped, intentionally held until cases 4–7 pass, per Kyle's own instruction.

## Course Scanner — current status

The scan/enumerate algorithm itself is closed (CS5, 43/43 lessons, real SMB Market classroom). The only
remaining piece is the popup/background UI wiring around it, never exercised live: Scan this course from the
real popup, Cancel a scan in progress, close/reopen the popup mid-scan. Not started.

## Kyle-gated judgments ready to present, no further engineering needed

- **CR7** — real nightly research-refresh run, needs Kyle to run it with the right budget flags and check
  `nightly report --json`'s `research_refresh` key.
- **CR8b-gate** — real-world validation of selective acquisition against a genuine open Evidence Target (496
  candidates in "buying businesses", 230 in "web app design"); needs Kyle to run `project acquire-evaluate` (or
  wait for a `cr8b_enabled` nightly pass) and answer the gate's 8 questions.
- **CR8c** — blocked on CR8b-gate's evidence; not an implementation, an admission rule.
- **LP6** — waiting on a natural trigger (a real Claim status change); `plan_updates` was still empty as of the
  last check.
- **AD4B** — `usable_sample` reached for real on both active projects (buying businesses: 10,100 decisions, 8%
  capture rate; web app design: 3,650 decisions, 10% capture rate); waiting on Kyle's judgment whether that
  leaves genuine ambiguity worth a static-comparison build.
- **FM1-gate** — blocked on live Crossref/OpenAlex access this sandbox cannot reach; needs Kyle's machine.
- **L-51** — real 25-item review-queue result already produced against the "buying businesses" project; waiting
  on Kyle's answers to the gate's 3 questions.
- **L-21** — code+tests done, blocked on Kyle's physical macOS lid-closed power test.
- **L-06 → L-07** — L-06 needs Kyle's sample review; L-07 (a `$0` decision command) needs L-06 first.
- **L-08** — brief-text relevance backtest, tooling ready, needs a Mac run (~$0.03 in embeddings) + Kyle's
  decision.

## Standing constraints unchanged

Never open `data/neurosearch.db` from this session (see above — now enforced more strictly than before, not
just as a rule to recite); cost disclosure before any spend; `claims.set_status` is the only promotion door;
two commits per rung; no paid provider calls without Kyle's explicit go-ahead.
