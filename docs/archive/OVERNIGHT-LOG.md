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
