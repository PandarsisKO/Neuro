# HANDOFF — start here in any new session (any model)

*Neuro Search, written 2026-09-08 at 0.34.2, current at 0.56.1. This file is the front door; it stays short and points at the documents that hold the substance.*

## 1. Read in this order (about 20 minutes)

1. `CLAUDE.md` — the architecture map and the **standing rules** (never write the DB from outside the app; additive schema; `providers.invoke` is the only model entry point; `safe_fetch` is the only fetch; frozen numbers are decisions; API keys only in `.env`; Tier 1 + pytest always; new test modules sort after `test_core.py`).
2. `PRODUCT-ORGANIZATION.md` — Kyle's own synthesis of the philosophy underneath every mission (locked 2026-09-09), with a status audit of every organizational item he's raised against the actual codebase. Read this before proposing new work in any mission; it's the test a new idea should pass.
3. `EXPANSION.md` — the ladder (G1–G9, G6P1–P7, B1–B7), every LOCK Kyle wrote, every addendum, and the rung log with what each release built and its honest limits. The last sections say what is queued and how work moves between sessions.
4. The mission you were given (e.g. `SOURCES-FINDINGS-MISSION.md` (S1–S5 queued: stale triage, source value, source drawer, findings workbench, known-but-uncaptured pool), `RESEARCH-MISSION.md` + `RESEARCH-TAB.md`, or `SPEED-MISSION.md` (R0–R9: performance, filed 2026-09-09 with measured baselines from Kyle's live DB — read §A before planning anything, it contradicts several intuitions; §D is a KEEP/MODIFY/ADOPT/TEST/REJECT verdict per stack layer and §H records the numeric trigger that reopens each rejection), or `BOOTSTRAP-MISSION.md` (Mission BOOTSTRAP — project bootstrap and cross-project research reuse; R1–R3 shipped 0.50.0, R4–R8 queued; §0 records that ~70% of the architecture already existed and §B the six corrections to the original brief), or `SCHEDULER.md` (a design exploration of the bidirectional outside-in scheduler — two pools claiming from two orderings; nothing in it is built, and §9 lists the four measurements that must come first), or `LOCAL-AI-PROVIDER.md`, or the G6P section of EXPANSION.md, or `BROWSER-CAPTURE-AND-CATALOG.md`).
5. `HARDENING.md` — only the top table and the entries for the releases you will touch (why numbers are frozen).
6. The tests that gate your area (`tests/test_k6_claims.py`, `test_k8_works.py`, `test_k9_community.py`, `test_l1_browser_capture.py`, `test_l2_completeness.py`, `test_m1_epub.py`, `test_n1_research_view.py`, `test_n2_local_ai.py`, `test_n3_deep_findings.py`, `test_n4_stale_triage.py`, `test_n5_source_value.py`, `test_n6_findings_workbench.py`, `test_n7_pool.py`, `test_n8_research_shell.py`, `test_n9_source_drawer.py`, `test_o1_accelerate.py`, `test_o2_claims_workbench.py`, `test_k7_chat_truncation.py`, `test_core.py`) — read them as the executable form of the locks.

Chat transcripts are not required. Decisions live in the documents; invariants live in the tests.

## 2. How Kyle works with a session (the rules that are not in code)

- Kyle does **no terminal work**. The session delivers; Kyle tests in the app and reports.
- The app runs on Kyle's Mac from `./start` (uvicorn `--reload` watching `.py`/`.html` in the package). **The server restarts ITSELF automatically the moment a changed file lands on disk — there is nothing for Kyle to run, ever.** A delivery that touches a `.py` file still briefly interrupts whatever the server is mid-doing (an in-flight request, a running job's connection), so ask Kyle before landing one — but the question is permission to interrupt, never an instruction to restart. **Never tell Kyle to run `./start` or "restart the server" — a live mistake in the 2026-09-09 session, corrected after he called it out.** Docs-only and pure asset deliveries don't even interrupt anything.
- Kyle approves each delivery through a short question naming what's changing and that it'll briefly restart the running server; he answers "Deliver [...] now" or gives a correction — read his answer, it often contains a decision. The confirmation message it lands in should never say "restart your server" or imply he needs to take an action.
- He tracks the weekly model allowance; when asked, give honest cost estimates in "points of the week" and prioritise by wins per point.
- He locks designs in long messages ("I would make X…", numbered gates). File them into `EXPANSION.md` verbatim-in-substance before building; build to the gate; record honest limits in the rung log.
- Reddit, YouTube and any live site: **the user's browser is the legitimate reader**; never build anti-bot evasion. Credentials only in `.env`.

## 3. The delivery ritual (sandbox → Kyle's Mac)

The session has a full copy of the repo in its own workspace and a `.venv` (Python 3.11); Kyle's Mac repo is `/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO` (git, no remote; Python 3.14). Neither side has network to the other; files move through the device bridge.

1. Bump the version in **three** places: `neurosearch/__init__.py`, `pyproject.toml`, `UI_VERSION` in `neurosearch/web/index.html` (a test checks they agree); `uv pip install -e . -q --python .venv/bin/python`.
2. `rm -f data/neurosearch.db` before any pytest / eval / doctor (the sandbox DB is scratch; never ship it).
3. Full suite: `timeout 590 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`. Tier 1: `NEUROSEARCH_FAKE_AI=1 .venv/bin/neurosearch eval` (frozen totals must match HARDENING.md).
4. Bundle: `cd` to the **workspace ROOT — the parent of the `neurosearch/` repo folder, e.g. `/home/claude`, NOT `/home/claude/neurosearch`** — then `tar czf <scratch>/_update.tgz --exclude=.venv --exclude=data --exclude='__pycache__' --exclude='.git' --exclude='*.egg-info' --exclude=.env --exclude=.pytest_cache --exclude=evals neurosearch`. **Verify the exact path** `tar tzf <scratch>/_update.tgz | grep closeout.py` prints `neurosearch/neurosearch/closeout.py` — TWO `neurosearch/` segments (the outer is the sandbox's repo-folder wrapper `--strip-components=1` removes below; the inner is the actual Python package). If it prints only ONE segment (`neurosearch/closeout.py`), the tar ran from inside the repo folder instead of its parent — the bundle is malformed and `--strip-components=1` will land every file one level too shallow (`<repo>/api.py` instead of `<repo>/neurosearch/api.py`) without any error at extract time. Rebuild it from the correct `cd` before sending.
5. Send the bundle to the conversation (SendUserFile) → commit it to the Mac at `<repo>/_update.tgz` (device_commit_files, force) → on the Mac (device_bash): `cd "$HOME/mnt/2026 - KO Neuro Search REPO" && tar xzf _update.tgz --strip-components=1 --overwrite && rm -f _update.tgz && git add -A && git status --short`. **Before committing**, read the status output: it must show only `M`/`A` on paths you actually meant to touch, every changed `.py`/`.html` under `neurosearch/`, and NOTHING new at the repo root (no bare `api.py`, `jobs.py`, `web/` — that shape means the bundle was malformed per step 4 and files landed at the wrong path while the real `neurosearch/` package stayed stale). Confirm with a direct grep for something the change actually added, e.g. `grep -n '<a distinctive new string>' neurosearch/<file>.py`, before trusting the diff. Only then `git commit -qm "<message>"; rm -f .git/HEAD.lock .git/index.lock .git/objects/maintenance.lock; find .git/objects -name 'tmp_obj_*' -delete`. If a bad extraction was already committed and `git status` is clean afterward, `git reset --hard HEAD~1` undoes it safely (nothing else was mixed into that commit) — then redo the bundle and extraction correctly and recommit. Commit messages end with the Co-Authored-By and Claude-Session lines the session is given.
6. Release gate: in the sandbox `NEUROSEARCH_GIT_SHA=<mac short sha> .venv/bin/neurosearch release-check` → copy the two `evals/release/release-check-<ver>-<sha>-*.{txt,json}` to the conversation and to `<repo>/evals/release/`, commit separately ("release-check <ver> @ <sha>: PASS"), and `git tag -f <rung-tag>` (existing tags: `expansion-g5`, `expansion-g5-1`, `expansion-g6`, `expansion-g7`, `browser-b1`, `browser-b2`, `publication-g6p1`, `publication-g6p2`, `portable-answers-c0`, `browser-b3`, `research-r1`, `local-ai-l1`, `local-ai-l4`, `deep-d1`, `stale-s1`, `value-s2`, `findings-s4`, `pool-s5`, `research-r2`, `drawer-s3`, `grouped-views-s6-r8`, `skipped-metadata-s7`, `claims-cancel-s1`, `priority-lane-s1`, `low-lane-s1`, `lane-backfill-s1`, `bump-job-s1`, `check-now-s1`, `probe-model-pin-s1`, `speed-r0`, `speed-r2a`, `speed-r2b`, `speed-r2c`, `account-gate-fix`, `claims-slow-lane`, `caption-recovery-s8`, `claim-triage-r6a`, `honest-progress-s9`, `background-pause-s10`).
7. Live checks go through Kyle's Chrome (the Claude-in-Chrome tools) against `http://localhost:8000` — `fetch('/api/…')` from a tab on that origin; the sandbox and the Mac shell have no network to the app or to the web. Keep live probes to what a test cannot answer.

## 4. Where things stand (0.45.0)

Shipped and gated: G1–G7, G5.1, B1 (browser capture + `requires_browser`), B2 (completeness + capture queue), G6P1 (EPUB Core), G6P2 (EPUB structure: role weighting, reader, deep links), Share ▾ (0.35.1), B3 candidate links (0.36.0), Research view engine R1/R3/R5/R6 (0.37.2, `research_view.py` + endpoints; the tab's shell is NOT rebuilt yet), 0.32.2 (Reddit official API + browser reading), 0.34.x fixes. Suite 458, Tier 1 chat totals 34 / 196,951.

## Where things stand after 2026-09-09 (0.45.13 → 0.55.0, ~20 releases in one session)

**The through-line of that session, and the thing to fix next.** Three separate fires — a paid claim pass
re-queuing itself every five minutes (32% of a month's spend), $5 leaving in ten minutes when parked work all
released at once, and a new project's findings starving behind another project's 1,128-job backlog — were **one
missing idea wearing three costumes: the app has no notion of ADMISSION.** Every fix so far has been about ORDER
(lanes, bumps, pauses) or about POLITENESS (a job yielding voluntarily, 0.55.0), and both fail the same way: a
lane cannot evict a running job, and politeness has to be remembered separately by every long job. `rank_proposed`
(`work_p90` 384 s) still has not remembered.

**Current mission: SCHEDULER S1–S2** (`SCHEDULER.md` §5, §10). Pool budgets replace lanes in *admission*: a pool
claims only while its own bucket has room — dollars per rolling window and concurrent requests for the paid pool,
real CLI concurrency for local, submitted-but-unfinished for batch. It is the smallest change that makes all
three of the above structurally impossible rather than individually patched, and §9 lists what to measure first
(R0's perf ledger already answers two of the four).

### Missions in flight

| mission | state | next |
|---|---|---|
| **SCHEDULER** (`SCHEDULER.md`) | design only, nothing built | **S1 buckets, S2 tiers — the current mission** |
| **SPEED** (`SPEED-MISSION.md`) | R0–R3 shipped (0.46.0–0.49.0) | R4 durable windows → R5 in-job concurrency (R5 is the highest-risk rung on the ladder); R8 cheap hygiene any time; R9 needs ~20 min of Kyle's machine |
| **BOOTSTRAP** (`BOOTSTRAP-MISSION.md`) | R1–R3 shipped (0.50.0) | R4 progressive refinement + re-ranking · R5 gap-first Discover — the product-value half Kyle asked for |
| Model policy (`contracts.py`, 0.54.0) | engine enforced | the **$5–8 live Haiku comparison**: it converts 11 of the engine's 13 justifications from "debt"/"opinion" into facts |
| Mission S (`SOURCES-FINDINGS-MISSION.md`) | S1 shipped 0.43.0 | S2 source value · S3 drawer · S4 findings workbench · S5 pool |
| Research rebuild (`RESEARCH-MISSION.md`) | engine + shell + workbench shipped | R4, R7–R12 (UI-heavy) |
| Local-first AI (`LOCAL-AI-PROVIDER.md`) | L1/L3/L4 shipped | L2 local-first chat (a recommendation, not a rung) |

### Open debts created on 2026-09-09 (each is small and each is real)

- **`rank_proposed` does not yield** — identical shape to the claims job 0.55.0 fixed (`work_p90` 384 s, same
  3-worker pool). Mechanically the same change. Likely why channel reviews feel like they freeze everything.
- **Kyle's `.env` still pins `NEUROSEARCH_CLAUDE_CODE_MODEL=claude-haiku-4-5`**, which overrides every contract's
  model on the local path. Visible since 0.52.0 (`doctor` names it) but still in force.
- **The Haiku comparison has not been run.** `eval --migration-compare --live --candidate-model claude-haiku-4-5`
  covers chat/repair/export/planner.update today; arms for `claims.extract`, `library.profile` and `answer.share`
  do not exist yet.
- **Idle-detection auto-yield** — Kyle asked for "if 15 minutes has passed it's fine for it to start doing active
  work"; only the manual pause was built (0.48.2).
- **Per-claim area assignment is not persisted** — the structural fix behind 0.47.1's caching workaround.
- **UI: three tall review cards hide the In-progress card** and their inner lists swallow the page scroll, so the
  queue controls become unreachable on a project mid-review.
- **OCR for caption-less shorts** — 18 candidates now, ~100 including cutoff-skipped ones (deferred, 0.47.0).
- **`SPEED-MISSION.md` §D still says ADD NOTHING** — no vector DB, no Valkey, no broker, no gateway; §H holds the
  number that reopens each rejection.

### Kyle's own to-dos

- Reddit script-app credentials in `.env` (enables Explore); reload the extension after each extension bump.
- **Three review cards are sitting un-started** on "Design beautiful and modern web apps" — Kyle Skelly (107),
  Matthew Encina (93), Chase AI (400). Those 600 candidates are not queued at all; they wait for "Start ingesting
  selected". A project can look starved when it is really unapproved.
- Decide whether to clear `NEUROSEARCH_CLAUDE_CODE_MODEL` from `.env` (see the debts above).

Known cosmetic debt: the live Work "Form 1099DIV" title (dehyphenated before the reconcile fix).

## 4a. Handoff from the Fable session (2026-09-08, 0.43.0) — start here if you are the Opus session

**State of the app.** Everything through 0.43.0 is committed, release-checked and tagged on Kyle's Mac (last tags: `research-r1`, `local-ai-l1`, `local-ai-l4`, `deep-d1`, `stale-s1`, `value-s2`, `findings-s4`, `pool-s5`, `research-r2`, `drawer-s3`). The local AI provider is ON in Kyle's `.env` (`NEUROSEARCH_AI_PROFILE=local`, `NEUROSEARCH_LOCAL_AI_WORKERS=2`, `NEUROSEARCH_CLAUDE_CODE_MODEL=sonnet`); Claude Code 2.1.257 runs findings/ranking/profiles/claims/discovery/plan-updates at $0; deep reads ride the slow lane on one local worker.

**Built this session (rung logs in EXPANSION.md, gates in `tests/test_n1…n7`):** Research view engine (R1/R3/R5/R6 — no shell yet); L1 Claude Code provider + L4 usage split; Deep content D1–D3 (length-aware cap, reserve findings, Read deeper with per-part progress + slow lane); S1 stale triage; S2 source value + the Sources filter row; S4 findings workbench; S5 known-but-uncaptured pool with the pre-cutoff scan.

**What Kyle asked for that is NOT built yet, in his priority order:**
1. ~~**R2 — the Research tab shell**~~ — SHIPPED 0.44.1 (`RESEARCH-TAB.md` §8). Kyle has not reviewed it live yet: the first thing to ask him is whether the Overview's "Do these next" is the list he would actually work through, and whether the area names read like his subject matter.
2. ~~**S3 — the source drawer**~~ — SHIPPED 0.45.0 (`GET …/sources/{sid}/digest`; opens from the source card, its value line, and each Findings group).
3. ~~**L3** — the acceleration dialog~~ — SHIPPED 0.45.0 (banner above the Jobs list). **L2 (local-first chat) is a decision for Kyle, not a queued rung** — the recommendation against making it the default, and the shape to build if he wants it, is in EXPANSION.md ("L2 — a recommendation, not a rung").
4. **The stale pile itself.** Kyle's live project is a MIGRATED library: all 64 stale sources are `legacy_unverified`, not `stale`, and 513 of 519 approved findings sit behind them. 0.45.1 fixed the reason accepting them did nothing (see EXPANSION.md). The lesson for the next rung: **build test fixtures that are legacy rows, not freshly analysed ones** — every S-mission gate so far constructed its sources with `findings.suggest_for_source`, so the code path Kyle actually runs on was the one path no test covered.
5. Small follow-ups Kyle will notice: ~~a "capture the N that fit" bulk action on the pool~~ — SHIPPED 0.45.4 (`POST …/pool/capture-many`). ~~the Claims workbench + "Why this answer" / "Settle this"~~ — SHIPPED 0.45.5, see item 6. Still open: the Research questions' "N promising sources known" already opens a per-question dialog (`showKnown`) with per-item capture/dismiss — decide whether that's sufficient or Kyle still wants a link into the pool view itself, filtered to that question, once he's tried the dialog; the first live measurement of how many findings a deep read yields on a 3-hour source (record in EXPANSION.md).
7. ~~Grouped views (Sources/Findings/Claims)~~ — SHIPPED 0.45.6, see EXPANSION.md "S6 + R8". `PRODUCT-ORGANIZATION.md` #1 taken narrowly (grouping, not rescanning/dedup). Its remaining NOT BUILT items (#8 rescanning, #19/#21 adaptive triage, findings dedup) are still queued, in that order of leverage per the doc's own closing section — Kyle has not yet said which to build next.
8. Live, same session: an `extract_claims` job failed with a raw `BILLING` (out-of-credit) SDK exception as its message. Fixed 0.45.6 — see EXPANSION.md "S1 fix — an out-of-credit account...". If Kyle reports another provider-error message that reads like a stack trace rather than a sentence, check `jobs.execute`'s error branches first — `SPEND_CAP` and now `BILLING` are handled; any OTHER non-transient type (`AUTH`, `INVALID_REQUEST`, `REFUSAL`) still falls through to the generic `failed` path with the raw exception text, which may be worth the same treatment if Kyle hits one.
9. Live, same session, on the 0.45.6 grouping delivery: "sources that were beyond the cutoff are not showing thumbnails, and are not giving any indication on whether they still may be of value to ingest." Fixed 0.45.7 — see EXPANSION.md "S1 fix — a skipped source's fetched metadata...". Two root causes: `ingest.ingest_source`'s skip branch discarded metadata `media.fetch_info` had already fetched (now saved); the pool's `_potential` scan never reached the plain Sources list (now surfaced there as `pool_potential` on every skipped row). Also built a one-click backfill (`refresh_skipped_metadata` job + "🔄 Refresh info" button) for sources that were already skipped before this fix landed — the ingest.py fix alone only helps future skips.
10. Live, same session, with a screenshot: an `extract_claims` job stuck at "cancelling... (stops at the next safe point)" for minutes, and its Jobs-panel label was the raw kind name. Fixed 0.45.8 — see EXPANSION.md "S1 fix — extract_claims couldn't actually be cancelled...". Root cause: `claims.extract()` never called `jobs.check_cancel()` anywhere (every other AI job kind does, at a safe boundary), so a cancel request could only take effect once the whole job finished on its own — on a big candidate backlog, never. Now checks between per-group model calls, joined `jobs.RETRYABLE`, and shows "finding claims to track" in the panel. Kyle hasn't confirmed whether his complaint was ONLY this (label + stuck cancel) or also volume/frequency of extract_claims runs against his large migrated project — worth asking directly once he's seen this land.
11. Live, same session: "our in progress queue gets cut off if theres too many items in queue. I cannot see whats active" and "ranking is far too slow. we need to improve that." Fixed 0.45.9 — see EXPANSION.md "S1 fixes — the Jobs panel could hide an active job, and ranking queued behind the whole AI backlog". `api_project_jobs` used to scan only the most-recently-created 400 jobs APP-WIDE before filtering to the project — a genuinely active job could fall out of that window on a busy app and vanish from the panel; every active job for the project is now always included. `rank_proposed` (the Review-card scoring job) now gets a new `lane="priority"` so it's claimed ahead of the `normal`-lane findings/claims backlog on the same $0 local pool — never a spending decision, purely queue order. Honest limit noted in EXPANSION.md: this doesn't speed up each ranking batch's own model-call latency, only its wait to start; if Kyle still finds it slow after this, the next lever is accelerating that specific job onto the API pool (L3), which he hasn't been offered directly yet.
12. Live, same session, immediately following item 11: "we need to be able to skip the line for items that are higher priority. obvously transcribing new sources, ranking things etc are higher priority over refreshing meta data from stale or skipped things that we dont even know if we will utilize." Fixed 0.45.10 — see EXPANSION.md "S1 fix — a fourth lane for speculative background work". `lane` gained `low`, claimed only once nothing `priority`/`normal`/`slow` is waiting; `refresh_skipped_metadata` (the skipped-source backfill button) is now tagged `low` so it never displaces an actively transcribing source or ranking job. Only `rank_proposed` and `refresh_skipped_metadata` are tagged so far — that matches what Kyle actually asked for; other kinds stay `normal` by default.
13. Live, same session, right after item 12: "the active queue needs to be re-prioritized." Confirmed with Kyle: he meant jobs already sitting in the queue from before the lane fix landed weren't touched by it. Fixed 0.45.11 — see EXPANSION.md "S1 fix — the lane fix didn't retroactively touch jobs already sitting in the queue". `db.init_db()` now backfills the correct lane onto any currently-queued `rank_proposed`/`refresh_skipped_metadata` job on every app start (idempotent, live-queue-only, never rewrites job history) — so a restart alone fixes the existing backlog, not just jobs created after the update.
14. Live, same session, right after item 13: "can we get a manual start button in the progress queue to move it to the top/next in line?" Built 0.45.12 — see EXPANSION.md "S1 feature — a manual 'run this next' button". A "⏫ Start next" button on any queued job in the Jobs panel jumps it ahead of every lane (even `priority`) and any older bump; one-shot, cleared the moment it's actually claimed. Per-job only — bumping one source in a batch doesn't bump the rest.
15. Live, same session: "in our progress bar we have a message that states: account's usage limit is reached — access returns 2026-10-01 00:00 UTC ... but I think thats an old message and is not true. how do we verify?" Confirmed the date itself is genuine — parsed straight out of Anthropic's own error text the moment the job first hit SPEND_CAP, not invented — but it's frozen: `not_before` blocks any re-attempt before that date, so the banner can go stale for weeks if the real-world limit already lifted. Built 0.45.13 — see EXPANSION.md "S1 feature — 'Check now' for a parked wait". `db.check_now(job_id)` clears the wait and bumps the job (reusing 0.45.12's mechanism) so the next worker cycle makes a genuinely fresh call; "🔄 Check now" button in the Jobs panel on timer-driven waits only (`budget_wait`/`rate_limit_wait`/`provider_wait`/`retry_wait`, never dependency-driven `blocked`). Told Kyle the Anthropic Console (console.anthropic.com → Billing/Limits) is the independent ground-truth check outside the app too.
16. Live, same session: "This is a serious issue. Our Claude code subscription is not saturated. Only fable work is. We should be able to do background (non api) still." Confirmed with Kyle: "fable" is the CLI's own bare default model, not the pinned `sonnet` from his `.env`. Found the real bug: `claude_code._probe()` hardcoded `model=None` for its health check while `create()` (real work) already honored `settings.claude_code_model`. The probe was asking a DIFFERENT, separately-metered model than every actual job runs on — that model's own exhaustion was reporting the entire local-AI path down, even though the pinned `sonnet` model (what findings/claims/ranking/plan jobs actually ask for) had headroom the whole time. Fixed 0.45.14 — see EXPANSION.md "S1 fix — the local-AI health probe used the CLI's bare default model, not the pinned one". Also live in this session, while investigating: queued 25 $0 `refresh_skipped_metadata` jobs (no AI/whisper call) for the Real Estate project's skipped sources, and separately retried 11 network-failed sources — realized mid-way that those retries could reach paid Whisper transcription (not $0, a different provider than the Anthropic-account block), tried to cancel them, and triggered a native `confirm()` dialog via a UI click that froze the Chrome tab (a repeat of the documented "never trigger a dialog via automation" hazard) — had to ask Kyle to dismiss it by hand. Worth remembering: `/api/retry-failed` → `ingest_source` is NOT a $0 action even when the failure itself was a free metadata-fetch timeout, because success continues on to paid transcription.
6. **Design-doc drift.** Kyle keeps a personal copy of the original mission docs under `Claude outputs/` at the repo root (outside `neurosearch/`, so it never travels in the delivery bundle) — it's a SNAPSHOT from before either mission's "what shipped" status sections existed, and it's what led him to ask "are we missing something?" on 2026-09-09: `RESEARCH-TAB.md` §5's "Claims as a workbench" and "Connect to the work" (Why this answer / Settle this) really had been skipped by R2, and are now R7 (0.45.5). The working copies at the repo ROOT (`RESEARCH-TAB.md`, `SOURCES-FINDINGS-MISSION.md`) now carry closing status sections; the `Claude outputs/` copies were hand-updated to match in the same session via `device_bash` (they live outside the bundle, so any future doc change there needs the same manual step, or ask Kyle whether that folder should just be deleted in favour of the root copies).

**Working rules that bit this session (beyond CLAUDE.md):** raw-JSON tabs in Kyle's Chrome freeze — run `fetch()` from a tab on `http://localhost:8000/` instead; `tar --overwrite` of unchanged `.py` files still restarts the server (docs-only deliveries go through `device_commit_files` per file); `tests/fake_claude.py` is an import shim — never overwrite it (the CLI stub is `tests/fake_claude_cli.py`); the Mac's Cowork VM cannot run `claude`, so live provider checks go through the app's `/api/health.local_ai`; every findings "used" signal must exclude weak harvested Claims (nearly every finding has one).

## 5. What "done" means for a rung

A rung is done when: the gate tests pass and are registered in `release.py`; the full suite and Tier 1 pass; the rung log entry in EXPANSION.md states what was built and its honest limits; HARDENING.md records any frozen-number change; CLAUDE.md's map is current; the release-check artifact is committed and the tag moved; and Kyle has been told, in plain language, what to try in the app.


## Open debt added 0.56.3 — local Haiku in normal use

The local Claude Code CLI returned `claude-haiku-4-5` for a call pinned to `claude-sonnet-4-6` during the migration
comparison. `NEUROSEARCH_AI_PROFILE=local` is set in Kyle's `.env`, and `findings.extract`, `claims.extract`,
`planner.update` and `rank.relevance` are all `local_capable`. So the findings and Claims already in his live
database may have been produced by Haiku while their provenance recorded Sonnet 5.

0.56.3 counts every mismatch from now on (`db.model_mismatches()`, Health → `model_routing`, a `release-check`
warning). It does NOT reclassify existing artifacts. Deciding that needs a query over
`project_source_analysis.routing` in the live database — through the API, never by opening the file — and Kyle's call
on whether to re-run anything. Do not assume the artifacts are wrong: `routing.actual_model` was always stored, so
the answer is already in there.


## Next rung, filed 2026-09-10 by Kyle — the field map (FIELD-MAP-RUNG.md)

0.57.0's catalogue work answers questions the project already formulated. Kyle's observation is that the harder gap
is the opposite direction: one review article or book tells you WHICH QUESTIONS EXIST — including the ones you had no
vocabulary for. Every gap mechanism in the app today (pursue, research_view.questions, candidates.pool, discover,
MISSING_PERSPECTIVE) is a reflection of the corpus, so none can produce a question whose words are not already
somewhere in the project. That is a structural hole, not a tuning problem, and a catalogue is the only thing here
that can see past it.

Read FIELD-MAP-RUNG.md before starting: it carries the shape, the $0 constraint, the four things that would be wrong
to build (letting a catalogue write research state; running it for projects with no literature behind them;
presenting an academic taxonomy as the project's real gaps; making it a paid pass), and the open question to settle
by measurement first — reference-list clusters versus the reviews' own headings.
