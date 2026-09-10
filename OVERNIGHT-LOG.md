# Overnight log — 2026-09-10

Read this first in the morning. Newest entry at the bottom. Every line is a fact, not a plan.

Start: `1896030`, `v0.57.0`, tree clean, release-check PASS, app running.
Plan: `OVERNIGHT-MISSION.md`. Spend so far: **$0.00** (no paid call is possible from either environment).

| time PDT | rung | outcome |
|---|---|---|
| 21:15 | — | mission and ladder locked, starting F1 |
| 23:20 | **verification attempt** | tried to open your app in the built-in browser to see the new banners actually render — the desktop app is asleep, so **no UI change tonight was visually verified**. Shipped **0.58.10**: the new banner is now explicitly unable to break the findings list if it fails, and the dialogs tolerate unexpected shapes. |

---

## When you wake up

**Nothing is broken and nothing needs doing.** Tree clean, `v0.58.10`, release-check PASS, spend **$0.00**.

### The one thing to check first
Open a project → **Findings**. Tonight added a 🧽 banner there (and a 📥 one under the `reserve` filter). It was
verified by parsing the JavaScript, **not** by looking at it — your desktop app was asleep, so I could not open the
page. If a banner is missing or the list looks wrong, that is where it will be, and 0.58.10 made the banner unable
to take the list down with it. `git checkout v0.57.0` reverts the whole night if you want a clean baseline.

### What is waiting for you, in the order I would do it
1. **Findings → the 🧽 banner.** ~441 duplicates across your projects (4.2% of the big one), each with the finding
   it would keep instead. Nothing is dismissed until you press the button.
2. **Findings → status `reserve` → the 📥 banner.** 540 findings you already paid for and never saw, of which 1
   duplicates something approved. Close to free value. Skim before Approve-all — the check catches rewordings, not
   paraphrases.
3. **Research → any open question → "Where to look · $0".** Ranked master sources with what each has already given
   you and how much is unread.
4. **Two decisions I could not make for you:** `FINDINGS-YIELD-DEBT.md` (books hold an AI worker — staging table or
   the batch path?) and `SCHEDULER-ADMISSION.md` (the root cause of yesterday's three fires; it restructures the
   queue's claim path, so it wants you awake).
5. **Optional, still unrun:** `run-findings-haiku-test.command` ($0.45) and the two free catalogue keys in `.env`.

### What I would not trust yet
The findings cap went from 12 to 20 per source (env-reversible). Sources ingested from now on keep more. Watch the
duplicate share in Health → `findings_quality` as that takes effect — that number is the honest signal for whether
the higher cap is buying you findings or noise.

---

## 04:36–05:00 — the money question, answered properly

Kyle said Anthropic was charging him far more than the app admitted. My first read of his ledger said $112 for the
week and I implied his ~$300 figure was wrong. **He was right and I was wrong.** His Console: **$312.40** month to
date.

| | |
|---|---|
| app ledger, month to date | $111.96 |
| local Claude Code path, booked as `saved` | $210.55 |
| **sum** | **$322.51** |
| Anthropic Console | **$312.40** |

Within 3%. L1 booked every local call at `cost=0` because it assumed the CLI runs on a subscription, and nothing
ever checked. His CLI is on an API key, so those were real charges — invisible to the daily budget, the monthly
budget, the rate ceiling and Health simultaneously, because all four read `cost`.

**Shipped 0.59.0** `868765c`, tag `v0.59.0`, release-check PASS, 733 tests:
- local calls priced as spend unless provably free (`unknown` counts as billed);
- `usage.reconcile()` — recorded vs likely charged, by day/week/month, without rewriting history;
- a **weekly** budget and a **settable** rate ceiling ($6/hr default ≈ $1,000/week);
- account walls now stop the queue instead of being rediscovered job by job (624 + 48 refusals measured);
- duplicates split: one source repeating itself is redundancy; several sources agreeing is **corroboration**, and
  it is protected, never swept, and sorts first in the promote list.

**Two things for Kyle:** check `echo $ANTHROPIC_API_KEY` in the shell that starts Neuro Search — if it is set, run
`claude login` to move the local path onto the subscription and it becomes genuinely free. Or set
`NEUROSEARCH_AI_PROFILE=cloud` to turn local off and make all spend visible.
