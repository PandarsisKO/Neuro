# HANDOFF — start here in any new session (any model)

*Neuro Search, written 2026-09-08 at 0.34.2, current at 0.43.0. This file is the front door; it stays short and points at the documents that hold the substance.*

## 1. Read in this order (about 20 minutes)

1. `CLAUDE.md` — the architecture map and the **standing rules** (never write the DB from outside the app; additive schema; `providers.invoke` is the only model entry point; `safe_fetch` is the only fetch; frozen numbers are decisions; API keys only in `.env`; Tier 1 + pytest always; new test modules sort after `test_core.py`).
2. `EXPANSION.md` — the ladder (G1–G9, G6P1–P7, B1–B7), every LOCK Kyle wrote, every addendum, and the rung log with what each release built and its honest limits. The last sections say what is queued and how work moves between sessions.
3. The mission you were given (e.g. `SOURCES-FINDINGS-MISSION.md` (S1–S5 queued: stale triage, source value, source drawer, findings workbench, known-but-uncaptured pool), `RESEARCH-MISSION.md` + `RESEARCH-TAB.md`, or `LOCAL-AI-PROVIDER.md`, or the G6P section of EXPANSION.md, or `BROWSER-CAPTURE-AND-CATALOG.md`).
4. `HARDENING.md` — only the top table and the entries for the releases you will touch (why numbers are frozen).
5. The tests that gate your area (`tests/test_k6_claims.py`, `test_k8_works.py`, `test_k9_community.py`, `test_l1_browser_capture.py`, `test_l2_completeness.py`, `test_m1_epub.py`, `test_n1_research_view.py`, `test_n2_local_ai.py`, `test_n3_deep_findings.py`, `test_n4_stale_triage.py`, `test_n5_source_value.py`, `test_n6_findings_workbench.py`, `test_n7_pool.py`, `test_k7_chat_truncation.py`, `test_core.py`) — read them as the executable form of the locks.

Chat transcripts are not required. Decisions live in the documents; invariants live in the tests.

## 2. How Kyle works with a session (the rules that are not in code)

- Kyle does **no terminal work**. The session delivers; Kyle tests in the app and reports.
- The app runs on Kyle's Mac from `./start` (uvicorn `--reload` watching `.py`). **Any delivery that touches a `.py` file restarts the server; ask Kyle before delivering one.** Docs-only and `index.html`/extension-only deliveries do not restart.
- Kyle approves each restart through a short question with the delivery summary; he answers "Deliver and restart now" or gives a correction — read his answer, it often contains a decision.
- He tracks the weekly model allowance; when asked, give honest cost estimates in "points of the week" and prioritise by wins per point.
- He locks designs in long messages ("I would make X…", numbered gates). File them into `EXPANSION.md` verbatim-in-substance before building; build to the gate; record honest limits in the rung log.
- Reddit, YouTube and any live site: **the user's browser is the legitimate reader**; never build anti-bot evasion. Credentials only in `.env`.

## 3. The delivery ritual (sandbox → Kyle's Mac)

The session has a full copy of the repo in its own workspace and a `.venv` (Python 3.11); Kyle's Mac repo is `/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO` (git, no remote; Python 3.14). Neither side has network to the other; files move through the device bridge.

1. Bump the version in **three** places: `neurosearch/__init__.py`, `pyproject.toml`, `UI_VERSION` in `neurosearch/web/index.html` (a test checks they agree); `uv pip install -e . -q --python .venv/bin/python`.
2. `rm -f data/neurosearch.db` before any pytest / eval / doctor (the sandbox DB is scratch; never ship it).
3. Full suite: `timeout 590 .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`. Tier 1: `NEUROSEARCH_FAKE_AI=1 .venv/bin/neurosearch eval` (frozen totals must match HARDENING.md).
4. Bundle: from the workspace root, `tar czf <scratch>/_update.tgz --exclude=.venv --exclude=data --exclude='__pycache__' --exclude='.git' --exclude='*.egg-info' --exclude=.env --exclude=.pytest_cache --exclude=evals neurosearch`; verify it contains `neurosearch/neurosearch/closeout.py` and nothing outside `neurosearch/`.
5. Send the bundle to the conversation (SendUserFile) → commit it to the Mac at `<repo>/_update.tgz` (device_commit_files, force) → on the Mac (device_bash): `cd "$HOME/mnt/2026 - KO Neuro Search REPO" && tar xzf _update.tgz --strip-components=1 --overwrite && rm -f _update.tgz && git add -A && git commit -qm "<message>"; rm -f .git/HEAD.lock .git/index.lock .git/objects/maintenance.lock; find .git/objects -name 'tmp_obj_*' -delete`. Commit messages end with the Co-Authored-By and Claude-Session lines the session is given.
6. Release gate: in the sandbox `NEUROSEARCH_GIT_SHA=<mac short sha> .venv/bin/neurosearch release-check` → copy the two `evals/release/release-check-<ver>-<sha>-*.{txt,json}` to the conversation and to `<repo>/evals/release/`, commit separately ("release-check <ver> @ <sha>: PASS"), and `git tag -f <rung-tag>` (existing tags: `expansion-g5`, `expansion-g5-1`, `expansion-g6`, `expansion-g7`, `browser-b1`, `browser-b2`, `publication-g6p1`, `publication-g6p2`, `portable-answers-c0`, `browser-b3`, `research-r1`, `local-ai-l1`, `local-ai-l4`, `deep-d1`, `stale-s1`, `value-s2`, `findings-s4`, `pool-s5`).
7. Live checks go through Kyle's Chrome (the Claude-in-Chrome tools) against `http://localhost:8000` — `fetch('/api/…')` from a tab on that origin; the sandbox and the Mac shell have no network to the app or to the web. Keep live probes to what a test cannot answer.

## 4. Where things stand (0.43.0)

Shipped and gated: G1–G7, G5.1, B1 (browser capture + `requires_browser`), B2 (completeness + capture queue), G6P1 (EPUB Core), G6P2 (EPUB structure: role weighting, reader, deep links), Share ▾ (0.35.1), B3 candidate links (0.36.0), Research view engine R1/R3/R5/R6 (0.37.2, `research_view.py` + endpoints; the tab's shell is NOT rebuilt yet), 0.32.2 (Reddit official API + browser reading), 0.34.x fixes. Suite 448, Tier 1 chat totals 34 / 196,951.

Queued, in Kyle's priority order and with rough cost in "points of a week" (a deterministic rung ≈ 4, a live-iteration rung ≈ 10): Mission S — S2 source value (S1 stale triage shipped 0.43.0), S3 source drawer, S4 findings workbench, S5 known-but-uncaptured pool (`SOURCES-FINDINGS-MISSION.md`; S1/S2/S5 are engine-heavy, S3/S4 UI-heavy); Research rebuild R2 shell + R4 + R7–R12 (`RESEARCH-MISSION.md`; the engine and its contract are done — start from `RESEARCH-TAB.md` §7 and render `GET …/research/overview`; UI-heavy, ~8–12 over several sessions); L2 local-first chat + L3 acceleration dialog (`LOCAL-AI-PROVIDER.md`; L1 verified live 2026-09-08, L4 shipped 0.38.3; ~6 over sessions); G6P3–P7; B4–B7; G8; G9. Kyle's own to-dos: Reddit script-app credentials in `.env` (enables Explore), reload the extension after each extension bump.

Known cosmetic debt: the live Work "Form 1099DIV" title (dehyphenated before the reconcile fix).

## 4a. Handoff from the Fable session (2026-09-08, 0.43.0) — start here if you are the Opus session

**State of the app.** Everything through 0.43.0 is committed, release-checked and tagged on Kyle's Mac (last tags: `research-r1`, `local-ai-l1`, `local-ai-l4`, `deep-d1`, `stale-s1`, `value-s2`, `findings-s4`, `pool-s5`). The local AI provider is ON in Kyle's `.env` (`NEUROSEARCH_AI_PROFILE=local`, `NEUROSEARCH_LOCAL_AI_WORKERS=2`, `NEUROSEARCH_CLAUDE_CODE_MODEL=sonnet`); Claude Code 2.1.257 runs findings/ranking/profiles/claims/discovery/plan-updates at $0; deep reads ride the slow lane on one local worker.

**Built this session (rung logs in EXPANSION.md, gates in `tests/test_n1…n7`):** Research view engine (R1/R3/R5/R6 — no shell yet); L1 Claude Code provider + L4 usage split; Deep content D1–D3 (length-aware cap, reserve findings, Read deeper with per-part progress + slow lane); S1 stale triage; S2 source value + the Sources filter row; S4 findings workbench; S5 known-but-uncaptured pool with the pre-cutoff scan.

**What Kyle asked for that is NOT built yet, in his priority order:**
1. **R2 — the Research tab shell** (Kyle: "still a mess, I have no clue how to utilize it"). Render `GET /api/projects/{id}/research/overview` (summary · next · recently improved · areas) as the tab's front page, with Questions / Watch-outs / Areas / Claims as drill-downs; contract and live numbers in `RESEARCH-TAB.md` §7; wireframe intent in `RESEARCH-MISSION.md`. Keep the old lists reachable under "Research tools".
2. **S3 — the source drawer** (`SOURCES-FINDINGS-MISSION.md` §3.4): one place per source — value line, findings by status with use badges, the Claims they became, where used, staleness tier with one-source actions, "Ask about this source" (pin via `attached_source_ids`). Most of the data already exists on `/api/sources` rows + `/api/projects/{id}/findings?source_id=` + `/api/projects/{id}/notes?status=reserve&source_id=`.
3. **L2/L3** — local-first chat and the "answer now with API ≈ $" acceleration dialog (`LOCAL-AI-PROVIDER.md`); the job policy endpoint `PUT /api/jobs/{id}/policy` is the hook.
4. Small follow-ups Kyle will notice: the Research questions' "N promising sources known" link should land on the 🔎 pool filtered to that question; a "capture the N that fit" bulk action on the pool; the first live measurement of how many findings a deep read yields on a 3-hour source (record in EXPANSION.md).

**Working rules that bit this session (beyond CLAUDE.md):** raw-JSON tabs in Kyle's Chrome freeze — run `fetch()` from a tab on `http://localhost:8000/` instead; `tar --overwrite` of unchanged `.py` files still restarts the server (docs-only deliveries go through `device_commit_files` per file); `tests/fake_claude.py` is an import shim — never overwrite it (the CLI stub is `tests/fake_claude_cli.py`); the Mac's Cowork VM cannot run `claude`, so live provider checks go through the app's `/api/health.local_ai`; every findings "used" signal must exclude weak harvested Claims (nearly every finding has one).

## 5. What "done" means for a rung

A rung is done when: the gate tests pass and are registered in `release.py`; the full suite and Tier 1 pass; the rung log entry in EXPANSION.md states what was built and its honest limits; HARDENING.md records any frozen-number change; CLAUDE.md's map is current; the release-check artifact is committed and the tag moved; and Kyle has been told, in plain language, what to try in the app.
