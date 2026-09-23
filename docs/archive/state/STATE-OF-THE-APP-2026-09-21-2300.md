# State of the App — 2026-09-21 23:00 UTC (16:00 PT)

Written by the repo audit (`docs/REPO-AUDIT-2026-09-21.md`) from `HANDOFF.md`'s 2026-09-20/21 entries and a check
of the live working tree. `STATE-OF-THE-APP-2026-09-17-1130.md` and older are archived under `docs/archive/state/`.
**No runtime claim here was measured against the live server or database tonight**; runtime figures are quoted
from the dated HANDOFF entries that made them.

## Where main is

- `main` tip at the time of writing: `a3d8fdd` and moving — Claude Code was committing the `evidence_dismissed`
  work (S80) while this was written. **`origin/main` is `44bd125` (2026-09-19 22:10 PT): 26+ commits are
  unpushed.** Pushing needs Kyle's own Terminal (the sandbox has no GitHub credentials).
- App/package version **0.63.94** (`pyproject.toml`, `neurosearch/__init__.py`, `web/js/state.js`) — unchanged
  since 2026-09-19 even though everything below shipped since. Extension `manifest.json` **1.9.6**
  (2026-09-18). Which build Chrome has actually loaded is unverified (CE4).
- **Full suite: 2,367 passed, 0 failed** (Cowork VM, temp DBs, HANDOFF "Suggested-findings pass"), before S80.
  The earlier "≈40 environmental failures" allowance is gone: the two survivors were real bugs and were fixed
  (`release.py` frozen total; `E5_COHORT` dated Haiku id).
- Codex is offline for the week. Its uncommitted tree (S75, S76, scholar catalogue fix, E5 cohort fix) was
  adopted into `main` on 09-21 (`f99ab95`…`8fb5e7c`). Kyle has the Mac and runs Claude Code; the Cowork session
  runs tests in a Linux VM and never opens the live DB.

## What shipped 2026-09-20 → 21 (all pytest-green, none release-checked or version-bumped yet)

- Discovery relevance: ranker prompt rewritten to judge what a video *teaches* (`754d424`); `LOW_RELEVANCE`
  50 → 45 on the C1 band table (`db851c2`); a Lose now weighs what a Keep weighs; dismissed findings no longer
  count as creator yield; creator-trust cliff fix in `approve_proposed()`.
- YouTube Data API v3 client (`youtube_api.py`) + listing enrichment (`media._enrich_youtube`, first 600 entries,
  empty fields only); description backfill and re-score tools with a shared `flock` (`tools/_runlock.py`).
- Chat reaches Discovery: `reconsider_creator` tool (+341 input tokens/call, ~5.8 %, re-frozen totals 211,650 /
  277,869 / 224,716).
- S75 Discovery exclude list (`project_excludes`, Project-settings card); S76 synthesized topic summaries;
  L-51 Claims review queue as a Research tab; S80 `evidence_dismissed` reason (in flight).
- Findings review: `project_notes.reviewed_at` (additive live-schema migration); focus review one-at-a-time
  (S78); second look at bulk approvals and "Review suggested", 100 at a time (S79); "from an unreviewed finding"
  badge on Claims.
- E2 `wayback.py` + `GET /api/sources/{id}/archived` + "What it said then"; E1 `fred.py` (inert, parked).

## Measurements that matter

- AD4B blind review: **77 % → 55 % kept** after the fix (40 judged; bar 25 %). Band table: 45–49 10/10, 35–44
  3/10, 20–34 6/10, 0–19 3/10. Weighted: ~38 % of what the filter rejects is still material Kyle would keep.
- Findings model: Haiku confirmed as default (L-06/L-07: 100 %/100 % kept, $0.0006 vs $0.0014 per kept). The
  choice lives in `.env`, not in `contracts.py` — see `CLAUDE.md` top.
- Kyle's real nightly (09-20 15:02, `--budget 2 --research-refresh-budget 1`): L-30/L-31/CR7 PASS; 56
  refreshes requested; queue afterwards 29 queued / 14 running.
- Live enrichment check: `@AcquiringMinds` → 457 entries, 457 with descriptions.

## Open — decisions (Kyle)

AD4B close-or-third-round · the 35–44 band · C2 (exclude Nate Herk only?) · delete `planner_v3.py` /
`rerank.py` · CHR3 paid acceptance (spend) · CR8b-gate run + 8 answers · L-41 read one Morning Report · L-70 $
estimate. Detail and evidence: `docs/REPO-AUDIT-2026-09-21.md` §1.

## Open — live-DB / Mac work (Claude Code)

Confirm the $2.12 post-brief re-score ran (only the corrected dry run is recorded) · D3 description backfill
(`skipped_limit` 574, `acquired` 841) · check `plan_updates` for LP6 · `attest_chunk_space` never runs
automatically (HANDOFF 09-20) · one `neurosearch release-check`, bump to 0.63.95, push · CS7 first document
import · CE2 / CE4 extension checks.

## Parked by Kyle (2026-09-21)

Subreddit/Reddit API track · FRED · L-21 / L-40 / L-60 / L-61 overnight observations · Field Map FM1-gate→FM3.
Full list with re-open triggers: `PRODUCT-SCHEDULER.md` PARKED.

## Standing constraints unchanged

Never open `data/neurosearch.db` from outside the app; cost disclosure before any spend; `claims.set_status` is
the only promotion door; two commits per rung; stage by change, not by filename; HANDOFF is append-only.
