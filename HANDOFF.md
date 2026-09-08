# HANDOFF — start here in any new session (any model)

*Neuro Search, written 2026-09-08 at 0.34.2, current at 0.38.2. This file is the front door; it stays short and points at the documents that hold the substance.*

## 1. Read in this order (about 20 minutes)

1. `CLAUDE.md` — the architecture map and the **standing rules** (never write the DB from outside the app; additive schema; `providers.invoke` is the only model entry point; `safe_fetch` is the only fetch; frozen numbers are decisions; API keys only in `.env`; Tier 1 + pytest always; new test modules sort after `test_core.py`).
2. `EXPANSION.md` — the ladder (G1–G9, G6P1–P7, B1–B7), every LOCK Kyle wrote, every addendum, and the rung log with what each release built and its honest limits. The last sections say what is queued and how work moves between sessions.
3. The mission you were given (e.g. `RESEARCH-MISSION.md` + `RESEARCH-TAB.md`, or `LOCAL-AI-PROVIDER.md`, or the G6P section of EXPANSION.md, or `BROWSER-CAPTURE-AND-CATALOG.md`).
4. `HARDENING.md` — only the top table and the entries for the releases you will touch (why numbers are frozen).
5. The tests that gate your area (`tests/test_k6_claims.py`, `test_k8_works.py`, `test_k9_community.py`, `test_l1_browser_capture.py`, `test_l2_completeness.py`, `test_m1_epub.py`, `test_n1_research_view.py`, `test_n2_local_ai.py`, `test_k7_chat_truncation.py`, `test_core.py`) — read them as the executable form of the locks.

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
6. Release gate: in the sandbox `NEUROSEARCH_GIT_SHA=<mac short sha> .venv/bin/neurosearch release-check` → copy the two `evals/release/release-check-<ver>-<sha>-*.{txt,json}` to the conversation and to `<repo>/evals/release/`, commit separately ("release-check <ver> @ <sha>: PASS"), and `git tag -f <rung-tag>` (existing tags: `expansion-g5`, `expansion-g5-1`, `expansion-g6`, `expansion-g7`, `browser-b1`, `browser-b2`, `publication-g6p1`, `publication-g6p2`, `portable-answers-c0`, `browser-b3`, `research-r1`, `local-ai-l1`).
7. Live checks go through Kyle's Chrome (the Claude-in-Chrome tools) against `http://localhost:8000` — `fetch('/api/…')` from a tab on that origin; the sandbox and the Mac shell have no network to the app or to the web. Keep live probes to what a test cannot answer.

## 4. Where things stand (0.38.2)

Shipped and gated: G1–G7, G5.1, B1 (browser capture + `requires_browser`), B2 (completeness + capture queue), G6P1 (EPUB Core), G6P2 (EPUB structure: role weighting, reader, deep links), Share ▾ (0.35.1), B3 candidate links (0.36.0), Research view engine R1/R3/R5/R6 (0.37.2, `research_view.py` + endpoints; the tab's shell is NOT rebuilt yet), 0.32.2 (Reddit official API + browser reading), 0.34.x fixes. Suite 429, Tier 1 chat totals 34 / 196,951.

Queued, in Kyle's priority order and with rough cost in "points of a week" (a deterministic rung ≈ 4, a live-iteration rung ≈ 10): Research rebuild R2 shell + R4 + R7–R12 (`RESEARCH-MISSION.md`; the engine and its contract are done — start from `RESEARCH-TAB.md` §7 and render `GET …/research/overview`; UI-heavy, ~8–12 over several sessions); L1 live verification on the Mac + L2–L4 (`LOCAL-AI-PROVIDER.md`, ~8 over sessions); G6P3–P7; B4–B7; G8; G9. Kyle's own to-dos: Reddit script-app credentials in `.env` (enables Explore), reload the extension after each extension bump.

Known cosmetic debt: the live Work "Form 1099DIV" title (dehyphenated before the reconcile fix).

## 5. What "done" means for a rung

A rung is done when: the gate tests pass and are registered in `release.py`; the full suite and Tier 1 pass; the rung log entry in EXPANSION.md states what was built and its honest limits; HARDENING.md records any frozen-number change; CLAUDE.md's map is current; the release-check artifact is committed and the tag moved; and Kyle has been told, in plain language, what to try in the app.
