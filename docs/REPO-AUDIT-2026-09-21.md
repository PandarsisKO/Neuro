# Repo audit — 2026-09-21 (evening PT)

Full read of the control-plane docs, an import/route/DOM graph over the code, and a check of the live working
tree on the Mac. Snapshot audited at `main` = `6e262df` (0.63.94, extension 1.9.6). Everything below was
verified against file contents, not taken from summaries; `file:line` cites the repo as it stood tonight.
Nothing in the repo was modified by this audit, and `data/neurosearch.db` was not touched.

---

## 0. The one thing that matters most tonight

**26 commits on `main` are not on GitHub.** `origin/main` is still `44bd125` (2026-09-19 22:10 PT). Everything
since — the Codex tree adoption, S75/S76, the cutoff move to 45, the YouTube Data API client and enrichment,
`reviewed_at`, focus review, "Review suggested", `wayback.py`, `fred.py`, the `evidence_dismissed` queue reason
— exists only on this Mac. That is two days of three agents' work with no off-machine copy, in a repo that had
171 stale `.git` lock files two days ago. One command, from Kyle's own Terminal (not through a bridge mount):

```
cd "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO" && git push origin main
```

Wait for the in-flight change below to be committed first if an agent is still working (files under
`neurosearch/` were being written at 22:12 PT while this audit ran).

---

## 1. Decisions waiting on Kyle

Ranked by how much is sitting behind each. Items that older docs list as open but HANDOFF later closed are
in §5, not here.

| # | Decision | What is behind it | Where |
|---|---|---|---|
| 1 | **AD4B: is 55 % kept "good enough", or do you want the third measurement?** The bar was 25 %; the fix moved 77 → 55. Weighted by the real population, ~38 % of everything the filter rejects is still material you would keep. The post-brief re-score ($2.12, 106 calls) is recorded as a corrected *dry run* only — nothing records that the real run completed. | Whether the Discovery relevance thread closes or gets one more cycle. | HANDOFF.md:8307-8353, 8431-8460 |
| 2 | **The 35–44 band.** 570 candidates at ~30 % keep (n=10, ±15 pts). Lowering `LOW_RELEVANCE` from 45 to 35 would surface them; leaving it is defensible. Nobody can call this but you. | 570 candidates. | HANDOFF.md:8351-8358 |
| 3 | **C2 — the AI-automation creators.** Evidence: Nate Herk 0/3, Nick Puru 0/1, Liam Ottley 1/2 (the keep was his Zapier episode at 48). Recommendation on file: exclude Nate Herk only, via the new Project-settings exclude card; let the other two ride. | Three creators' output in the pool. | HANDOFF.md:8344-8347; docs/COMPLETION-CHECKLIST-2026-09-21.md:89-93 |
| 4 | **CR8b-gate → CR8c.** Selective acquisition is shipped behind `cr8b_enabled` (off). It needs one real run (`neurosearch project acquire-evaluate <project>`, writes a real ingest job) and your answers to questions A–H. CR8c (the admission rule) cannot start until then. Nothing has mentioned it since 09-16. | The whole "continuous research acquires on its own" ladder. | EXECUTION-LADDER.md:559-593; docs/KYLE-GATES-2026-09-15.md:193-215 |
| 5 | **Field Map FM1 → park or seed?** Network is no longer the blocker (Crossref/OpenAlex return 200 since 09-19). The blocker is that no project has a single DOI-bearing Work; the library is video/podcast/web. Either park FM1–FM3 explicitly or give it a project with a scholarly seed. | `field_map.py` + 32 tests with nothing to run on. | HANDOFF.md:7143-7150; EXECUTION-LADDER.md:725-752 |
| 6 | **Subreddit catalog: keep funding it?** Needs official Reddit API access (`stats.reddit_api=false`). The executor (Codex) is offline for the week. Two docs name two different delivery candidates (`abdefaa` on `codex/subreddit-integrated` vs `7191fdf` on `codex/subreddit-delivery`), both living in worktrees under `/private/tmp` on the Mac — a reboot can erase them. Both branches do exist in `.git`, so the commits are safe; the worktree state is not. | SUB-R1–R9, a whole track. | docs/SUBREDDIT-CATALOG-MISSION.md:3-10; docs/CONTINUOUS-EXECUTION-MISSION.md:45-54 |
| 7 | **CHR3 chat refresh: authorize a bounded paid acceptance?** Delivered to `main` with a deterministic release PASS; no real paid synthesis and no human look at the What's New card. Mission grants no budget, so this is a spend decision. | Whether CHR3 counts as accepted. | docs/CHAT-REFRESH-PLAN.md:1-8, 982-1009 |
| 8 | **L-70 / P7 structured-delta $ estimate.** Was gated on L-07; L-07 closed 09-20, so this is unblocked and dormant. `tools/p7_estimate.py` exists. | The T4 structured-delta write path (the genuinely unbuilt part of T4). | EXECUTION-LADDER.md:366-368; docs/KYLE-GATES:138-144 |
| 9 | **Small deferred calls you made and never revisited:** the `reconsider_creator` chat tool costs +341 input tokens (~5.8 %) on every chat call, recorded but never judged acceptable; Send Screenshot case 6's stray scroll-jump ("let's keep moving"); case 5.2's "looks different despite matching scroll number". | Nothing large; listed so they are not silently permanent. | HANDOFF.md:8003-8004, 6534-6541, 6459-6463 |

## 2. Actions only you can do (physical, keys, a real night)

| Action | Detail | Where |
|---|---|---|
| **L-21 lid test** | `neurosearch worker`; ~10 min with lid open/display asleep, then ~10 min lid closed; record yes/no for each under L-21. Code and tests have been done since 09-15. | docs/L21-POWER-ASSERTION.md:22-46 |
| **L-41: read one real Morning Report** | The 09-20 nightly produced the data. The gate is: can you explain the overnight change from `neurosearch nightly report` alone? Still open pending that one read. | EXECUTION-LADDER.md:291-306 |
| **L-40: use "When… → tonight" once** | Schedule one stale rebuild for tonight, leave the Mac normally, read the card in the morning. | EXECUTION-LADDER.md:274-285 |
| **L-60/L-61: one night with `--t5-budget`** | The only real nightly run was `--budget 2 --research-refresh-budget 1`; T5 adjudication has never fired for real. | EXECUTION-LADDER.md:341-364 |
| **CS7: first real document import** | Reload extension 1.9.6, re-scan Acquisition Ace, tick the 9 bonus Drive PDFs, import. Whether the Drive files are public decides "nine documents vs nine honest sign-in failures". Never exercised. | docs/COURSE-SCANNER-2026-09-15.md:244-247 |
| **CE2: live 401/403 extension recovery** | Only the jsdom harness exists. Point the extension at a failing endpoint in real Chrome, see the message, restore. | docs/CONTINUOUS-EXECUTION-MISSION.md:153-168 |
| **CE4: which extension build is Chrome actually running?** | Manifest is 1.9.6; a 09-19 entry says the installed one was 1.9.3; a 09-18 entry says you ran 1.9.4. Verify in `chrome://extensions` and do the release ritual once. | docs/CONTINUOUS-EXECUTION-MISSION.md:144, 195-201 |
| **FRED key** | You said it's unavailable for now. `fred.py` is inert. Note for when you do: **nothing consumes it yet** — adding the key changes nothing user-visible until a caller is built (§3). | docs/COMPLETION-CHECKLIST-2026-09-21.md:120-146 |
| **LP6: hand over a Claim id** | The 09-20 nightly requested 56 refreshes; nobody has re-checked whether `plan_updates` now has a row. If it does, LP6 closes with one id. | docs/KYLE-GATES:217-232 |
| **Speed observation owed** | The "two visible windows" measurement and first live `harvest_claims` completion off `/api/perf`. Low urgency; never recorded. | PRODUCT-SCHEDULER.md:34-35 |
| Not yours, but unrun: **D3** description backfill for `skipped_limit` (574) and `acquired` (841), ~28 quota units — Claude Code, live DB. | | docs/COMPLETION-CHECKLIST:112-114 |

## 3. Orphaned, parked or half-wired features

**Built, never accepted or never reachable**

- **`fred.py`** (19 tests) — imported by nothing but its test. With or without a key, no route, no Claim, no
  Health check calls `fred.prime()`/`rates()`. The checklist says "nothing calls it without the key"; it is
  also true with the key. E1 is a client, not a feature yet.
- **`t3_review.py`** — scoring infrastructure with no CLI/API entry point; waiting on the 60-row hand-label
  queue that was never labelled (docs/T3-ADMISSION-2026-09-13.md:181-200).
- **Subreddit catalog dismiss/restore** — routes exist (`api.py:355, 365`), `sources.js` never calls them; the
  only test is a 404 guard. Listed as "Remaining" in the mission doc.
- **T4** — PRODUCT-SCHEDULER.md:649-654 still says the executor is "not started, no target date". It is built
  and ran for real on 09-20 (`nightly.run()` → `t4.execute(...)`). The genuinely unbuilt remainder is the
  structured-delta persistence path (P7/L-70, decision #8). `t4.py:213`'s "(not yet wired)" note is stale
  wording about the dry-run only.
- **`attest_chunk_space` is never called automatically** — only `POST /api/transcript/corpus-attestation`
  (`api.py:3414`). After any chunk change every T1/T4 relevance surface reports "unavailable" until someone
  POSTs an undocumented endpoint. Flagged 09-20 (HANDOFF.md:7160-7180), not scheduled.
- **The 09-21 batch is unreleased by the repo's own ritual.** Cutoff 50→45, `project_excludes`,
  `project_notes.reviewed_at` (a live-schema migration), Research tab, focus reviewers, Review suggested, S76,
  `wayback.py`, YouTube enrichment, `_runlock.py`, `evidence_dismissed` — all pytest-green (2,367 passed, 0
  failed) but no release-check, version bump, or State file records them. `pyproject`/`state.js` are still
  0.63.94 from 09-19.
- **49 of 221 API routes have no UI or extension caller.** Most are documented CLI/API-only by design
  (`discover/next`, transcript coverage/backfill, `research-needs`, `plan/impact`, usage reconcile/trend,
  CSV exports). The ones worth a yes/no on whether a surface was ever intended: `/api/scholar/*`,
  `/source-yield`, `/attention`, `PUT /api/jobs/{id}/policy`, `PUT /api/sources/{id}/tags`,
  `/library/recall`, the whole `/works/*` version/link/merge/reconcile group (G6), `/sources/{id}/thread`,
  `POST /claims/{id}/relate`, `/sources/{id}/profile`, `/library/enrich|stats`, `findings/fast-wave/promote`,
  `GET /api/search`, and `GET /logout` (there is no sign-out link anywhere).
  `/api/usage/spend-settings` is the only way to set the weekly budget and rate ceiling — no UI control.

**Parked by decision, with elapsed triggers**

- **`planner_v3.py`** — HARDENING.md:36 marks it a deletion candidate "if not revisited within two product
  releases". Many releases have passed. Delete or re-admit.
- **`rerank.py`** — "killed (measured live)", HARDENING.md:38 says it can go. Still present.
- **`NEUROSEARCH_CHAT_TAIL_BREAKPOINT`** — HARDENING.md:39: delete if still off after the next cost review.
- **H1 semantic finding dedupe** — `project_notes.embedding` / `project_claims.embedding` columns exist with
  no writer (consistent with the `semantics.py` removal). H2/H3 parked.
- **T2 embedding-space migration to `bge-m3`** — selected 09-11, no versioned migration/backfill gate
  exists. **R8 retention** revisit is dated 2026-10-11.
- **P11 Neuro Everywhere** (EXTERNAL-AI-ACCESS-MISSION.md, 63 KB) and **P12 bidirectional scheduler**
  (SCHEDULER.md) — filed, not started; sequencing is yours.
- **Podcast Index** — explicitly rejected (0 podcast-platform sources; 1,471/1,616 are YouTube). Fine.
- **Findings prefilter** — measured, not enabling (economics). Fine.

**Referenced but missing**

- HANDOFF.md:7083 and :7158 cite a **"17-item decision doc"** — "items 5-10, 13-17 status unchanged from the
  decision doc". That document is not in the repo. Items 5–10, 13, 14 and 16 have no traceable status
  anywhere in repository evidence, which breaks HANDOFF's own operating model (everything durable lives in the
  repo). If it was a chat message, paste it into `docs/` or the items are lost.

## 4. Code loose ends (small, concrete)

1. **In flight right now:** `review_queue.py`, `web/js/research.js`, `test_s77_*`, `test_s80_*` were being
   edited at 22:12 PT (the `evidence_dismissed` follow-up after `6e262df`). Whoever is driving should commit
   it; do not stage by filename (the lesson at HANDOFF.md:8272-8306).
2. **`start` vs `start.command` diverged.** `start.command` has the 0.63.92 stuck-port self-heal
   (`free_stuck_port`, gated by `test_s62`); root `start` still tells you to "double-click restart.command
   instead" (`start:28`). `README.md:36` tells people to run `./start` — the launcher without the fix.
3. **`RUN THIS - Audit Instance.command` (root) and `tools/audit-instance.command`** both `cd` into
   `.worktrees/f0` (`:18`), pruned as orphaned on 09-14. Both fail on a fresh checkout. Delete or repoint.
4. **`run-haiku-comparison.command` / `run-findings-haiku-test.command`** — both 09-09 runs were invalidated
   (HARDENING.md:845, :867); no valid third run recorded; VESTIGIAL says "compare before archiving". Decide.
5. **`neurosearch project review-queue` (CLI) omits the new `evidence_dismissed` reason** from its summary
   line (`cli.py:915-918`); it is only visible with `--json`. The UI empty-state copy at `research.js:285`
   also doesn't mention it. Backend and UI render it; the CLI text lags.
6. **`.env.example` documents ~25 of ~40 `NEUROSEARCH_*` names `config.py` reads** (and ~90 across the
   package). Missing user-facing ones: `NEUROSEARCH_YOUTUBE_API_KEY` (the new B1 path), `NEUROSEARCH_FRED_API_KEY`,
   `NEUROSEARCH_CR8B_ENABLED`, `NEUROSEARCH_MORNING_REPORT_NEEDS_ME`, the T4/T5/research-refresh nightly
   budgets, `NEUROSEARCH_API_AI_WORKERS`, `NEUROSEARCH_TASK_MODEL_<TASK>`, `NEUROSEARCH_FAKE_AI`, the three
   feature flags, `NEUROSEARCH_PRICES`, `NEUROSEARCH_AUTO_SUGGEST`. A clean checkout cannot discover the
   YouTube Data API path exists. `.env.example:29` `NEUROSEARCH_MAX_VIDEOS=150` vs code default 20
   (`config.py:112`); README.md:232 repeats 150.
7. **Chat model documentation is wrong.** README.md:290 and `.env.example:17` say chat runs
   `claude-sonnet-4-6` by default. `answer.chat`/`answer.repair` are pinned to `HELD_MODEL = "claude-sonnet-5"`
   (`contracts.py:111, 142, 145`); `settings.answer_model` feeds no contract, only fallback labels.
   `release.py:220` still reports `settings.answer_model` as the "production model" for `answer`, and the
   comment at `contracts.py:115` ("every other task still follows settings.answer_model") is false.
8. **Findings model documentation is wrong the other way.** CLAUDE.md:27 and HARDENING.md:23 say
   `findings.extract` is pinned to Sonnet 5; production is Haiku via `.env`
   (`NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=claude-haiku-4-5`, decided 09-14, confirmed 09-20). A fresh
   checkout without that `.env` line runs Sonnet 5 at 2.3× the cost with nothing saying so.
9. **`source_relations` table** (`db.py:387-394`, "populated by later rungs") — never written or read; lineage
   was built on `work_manifestations` instead. Harmless; note it as superseded.
10. Dead JS: `globalThis.FUN` (`utils.js:68`) never read; `globalThis.QUAL` (`research.js:1171`) written never
    read; `<span id="askStatus">` (`index.html:62`) never written. Extension banners still say "extension
    1.9.3"/"1.7.0" in `capture-lib.js:1`, `capture-blob-store.js:1`, `scan-lib.js:1`.
11. Verified clean, for the record: no TODO/FIXME/NotImplementedError anywhere; every UI→API path resolves;
    every extension message type is both sent and handled; extension icons are present (the snapshot dropped
    them, the repo has them); all `tools/` imports resolve; no test imports a missing module; the jsdom gate
    fails (not skips) on `npm ci` failure but still *skips* on a machine with no `node` at all.

## 5. Doc rot that will mislead the next agent

The three agents coordinate through these files, so this is not cosmetic. Grouped by what a fresh agent would
get wrong.

**Wrong version / wrong baseline**

- `CLAUDE.md:7` "0.63.63 is the current released application… zero queued/running jobs" (real: 0.63.94; the
  jobs clause is a 09-13 snapshot inside a standing-rules file). `CLAUDE.md:98` extension 1.9.3 (real 1.9.6).
  `CLAUDE.md:72` says `UI_VERSION` lives in `web/index.html`; since the 09-13 split it is
  `web/js/state.js:13` and the UI is 11 JS modules.
- `EXECUTION-LADDER.md:23-24` "Known-failure baseline is 14… until L-03 lands". Baseline is 0 failures; L-03
  landed 09-15. An agent reading the ladder will tolerate 14–40 failures.
- `STATE-OF-THE-APP-2026-09-17-1130.md` — the file CLAUDE.md says to read *first* — is four days and ~1,600
  HANDOFF lines behind: 0.63.91/1.9.3; "1,870 passed + ≈40 environmental failures" (real 2,367/0, and the
  "environmental" failures were real bugs, HANDOFF.md:8228); Send Screenshot cases 4–7 "open" (all passed
  09-17/18, case 7 closed 09-19); Course Scanner popup wiring "not started" (done 09-19); its Kyle-gated list
  still carries L-06/07/08, L-51, CR7 (all closed 09-20) and FM1 "sandbox cannot reach" (superseded).
  Nothing from 09-20/21 exists in it.
- `FOUNDATION-HANDOFF.md:5-6` "current released app is 0.63.63" — the file declares itself historical, yet
  `CLAUDE.md:5` and `HANDOFF.md:143` still send agents to it as "the active Foundation handoff".

**Which program is active — four docs disagree**

- `DEVELOPMENT-OPERATING-SYSTEM.md:24-50` (named by CLAUDE.md as your governing priorities) restricts work to
  Speed/QA then Transcript Intelligence, with Research/Discover expansion **parked**. `HANDOFF.md:146` "Start
  here" says the active program is Transcript Intelligence and the T1 backfill is unstarted (it completed in
  0.63.56). `README.md:355-357` same. `TRANSCRIPT-INTELLIGENCE-MISSION.md:1` says it is parked until Foundation
  closeout (09-12). Actual work since 09-14 is Product Intelligence / Continuous Research / Discovery relevance
  — the thing DOS §1 says is parked. You overrode DOS by adopting PRODUCT-INTELLIGENCE-MISSION.md; DOS §1 was
  never amended.
- `PRODUCT-SCHEDULER.md:5-25` NOW is four stacked, mutually superseding notes (09-19, 09-19, 09-17, 09-17) with
  **zero** mention of 09-20/21. The real active thread (Discovery relevance, Mission A/B, AD4B C1, cutoff 45,
  YouTube API, focus review) exists only in HANDOFF, `docs/MISSION-2026-09-20-*.md` and
  `docs/COMPLETION-CHECKLIST-2026-09-21.md`, and none of PRODUCT-SCHEDULER, EXECUTION-LADDER, CLAUDE.md or
  CONTINUOUS-EXECUTION-MISSION references those two docs.
- `PRODUCT-SCHEDULER.md:178-185` "## SUSPENDED — RESUME FIRST: D2/F1" — proven closed 09-16 (`386891b`); the
  file admits it at :36-38 but the section text was never changed.
- `docs/CONTINUOUS-EXECUTION-MISSION.md:5` and `PRODUCT-SCHEDULER.md:19` say Codex is the executor; Codex is
  offline for the week and its tree was adopted into `main` (HANDOFF.md:8274). A fresh Codex would restart
  SUB-R1 from a branch that has already been adopted.

**Closed items still shown open** (all closed 09-20/21 per HANDOFF, never ticked): EXECUTION-LADDER L-06 `[k]`,
L-07 `[ ]`, L-08 `[~]`, L-30/L-31 `[~]`, L-51 `[~]`, L-52 `[~]`, CR7 `[k]`; KYLE-GATES L-30/CR7, L-06/07/08,
L-51, Send Screenshot 5–7, Course Scanner three tests; COMPLETION-CHECKLIST A1/A2/A3, B1's "still owed" live
check (done, 457/457 with descriptions, HANDOFF.md:8206), C1; CONTINUOUS-EXECUTION §2 L-51→L-52 and CR7;
MORNING-BATCH.md (every item done — obsolete at root). L-00/L-01 (`[k]`, Stage 0) have no disposition anywhere.

**Frozen values not recorded where CLAUDE.md says they must be.** CLAUDE.md:44: "changing a frozen value is
recorded in HARDENING.md". HARDENING's last chat total is 165,365 (`:19, :143`); current is 211,650 / 277,869
(`test_core.py:1506-1508`, `release.py:452`) and `CHAT_ARM_INPUT_TOTAL` 224,716, re-baselined 09-20/21 for
`reconsider_creator` — reasoning lives only in code comments and HANDOFF. `LOW_RELEVANCE` 50→45 (`db851c2`)
is not in HARDENING either. HARDENING.md:30/:63 "UI stays a single file without a build" is stale since 09-13.

**Broken pointers.** `HANDOFF.md:214`, `DESIGN-MISSION.md:13-43`, `PRODUCT-SCHEDULER.md:241` cite a bare
`ladder.md` that only exists at `docs/design-audit/2026-09-13-b85c222/ladder.md` (fully closed).
`QA-STABILIZATION-PROMPT.md:17` tells the agent to read a root `QA-STABILIZATION-MISSION.md` that was archived
(`repo_check.py:28` still allow-lists the root name). `FIELD-MAP-RUNG.md:1` and `SOURCE-CAPABILITY-RUNG.md:1`
say "Not built" — FM0/FM1 and `where_to_look`/`creator_yield` shipped. `VESTIGIAL-INVENTORY.md:13` describes a
`Claude outputs/` that was removed 09-14; the folder is back with two screenshots nobody inventoried.

**HANDOFF.md itself (697 KB, 8,581 lines).** No index. "Start here" is at :139, *after* four 09-19 Codex
sections that were **prepended** (:3-138), while Claude **appends** (09-20/21 at the end). Two agents, two
conventions, so the newest entry is at both ends and the "current continuation pointer" (:95) is stale.
"Start here" (:139-183) is 09-12 content. There is no standing "Codex, your lane" section — the phrase appears
once inside a done 09-14 entry (:3211). Lines 264–6415 (09-13 → 09-17) are 504 KB of history that tests cite
only in docstrings.

### Recommended cleanup pass (one agent, one sitting, no product code)

1. Write `STATE-OF-THE-APP-2026-09-21-*.md` from HANDOFF :7000-end; archive the 09-17 one (pick one archive
   convention — `docs/archive/` and `docs/archive/state/` both exist with 14 and 18 files).
2. Fix CLAUDE.md :5, :7, :27, :72, :98; add the Haiku findings default and the `.env` line that carries it.
3. Cut HANDOFF.md at :6415 into `docs/archive/HANDOFF-2026-09-13-to-2026-09-17.md`; rebuild the head as a
   15-line index (version, active thread → COMPLETION-CHECKLIST, who is on/off, last green suite, open Kyle
   gates); move the 09-19 prepends into chronological order; declare **append-only** as the one convention.
4. Collapse PRODUCT-SCHEDULER NOW to a single current note pointing at the 09-20/21 docs; delete the SUSPENDED
   section; amend DOS §1 with the 09-14 override.
5. Tick the closed ladder/gate items listed above; add the missing HARDENING records (chat totals, cutoff 45,
   Haiku default); add a heading index to HARDENING.
6. Archive: FOUNDATION-HANDOFF, MORNING-BATCH, QA-STABILIZATION-PROMPT, DESIGN-MISSION, SPEED-MISSION,
   TRANSCRIPT-INTELLIGENCE-MISSION, EXTERNAL-AI-ACCESS-MISSION, FIELD-MAP-RUNG, SOURCE-CAPABILITY-RUNG,
   docs/PLAN_FOUNDATION_RECOVERY_GATES — each with a one-line banner; update `repo_check.py` ROOT_FILES to
   match. Keep DESIGN/AUDIT/APPLE-DESIGN-REFERENCES/QUALITY-CONTRACT/DOS/PRODUCT-INTELLIGENCE.
7. Fix README :36 (`./start` → `start.command`), :232, :290, :318-357; `.env.example` :14, :17, :29 plus the
   missing variable names.

## 6. Working tree hygiene (Mac, checked tonight)

| Item | State | Recommendation |
|---|---|---|
| Unpushed commits | 26 ahead of `origin/main`, 0 behind | **Push** (§0). |
| Uncommitted edits | `review_queue.py`, `research.js`, `test_s77`, `test_s80` — active at 22:12 PT | Let the driving agent commit by change, not filename. |
| `evals/release/` | 370 files, 336 tracked, 34 untracked | Policy is "cited artifact per version gets committed, iteration runs don't" (HANDOFF.md:1941-1949). Commit the cited 0.63.9x ones, delete the rest; make `repo-check` warn on uncited artifacts. |
| `evals/p53-sample-2026-09-20.json` | untracked | **Commit** — the L-06/L-07 Haiku decision rests on it, like the already-tracked `ad4b-sample-*.json`. |
| `.chr2_livetest/` | untracked scratch worktree with an edited `test_core.py`, `data/`, `server.log` | Delete; add to `.gitignore`. |
| `Claude outputs/` | two screenshots (09-20, 09-21), untracked | Inventory or delete; add to `.gitignore` so a broad stage can't publish drafts. |
| `INSPIRATION/` (5.9 MB), `SCREENSHOT AUDIT/` (44 MB) | untracked reference images | Add to `.gitignore`; never commit. `repo_check.py:87` silently tolerates them so nothing will ever flag it. |
| `_to_delete/` | empty (0 bytes) | Remove the folder. (This audit's own 3.6 MB snapshot tarball was moved there — it is the only thing in it now; delete it.) |
| `data_backup_2026-09-03/` | 81 MB raw DB copy with `-wal`/`-shm` sidecars inside the repo folder, gitignored | Move outside the repo folder. Never open in place (standing rule #1). |
| `.git` lock litter | 0 stale locks, `git worktree list` clean | Good; the 09-21 repair held. |
| `codex/*` branches | 10 local branches, none merged by ref | After the subreddit decision (#6), delete the ones whose work was adopted (`chat-refresh-*`, `capture-*`, `release-isolation-repair`, `continuous-execution`). |
