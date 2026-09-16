# The open gates — exactly what to run, nothing more

Every rung below is code-complete and tested; each gate is a real-world measurement only you can take (or a
short live-browser pass for the two extension missions at the bottom). Everything is copy-paste. Nothing here
spends money except the lines that say so.

**Readiness-pass update, 2026-09-16**: reconciled against current code and HANDOFF/EXECUTION-LADDER as of
today. All commands below were re-verified against the live CLI (`--help` on each, via a fresh import — not
just trusted from when this doc was written). One real usability gap was found and is called out in L-30/CR7
below: `nightly run` gained a third budget flag since this doc was first written, and omitting it makes CR7
silently not run, with the morning report staying completely quiet either way — nothing in the plain-text
report distinguishes "ran, nothing to do" from "the flag was never passed." No code was changed for this --
`nightly report --json` already disambiguates it (see CR7 below); this was a documentation gap, not a code one.
Five more gates that came into existence after 2026-09-15 (CR7, CR8b-gate, LP6, AD4B, FM1-gate) are added below,
plus the two live-extension acceptance gates (Send Screenshot, Course Scanner).

## L-30 — one real night at $2 (also closes L-31 and L-41's data side)

Spends up to $2 total across your projects. It runs preflight first (full integrity check + verified backup)
and refuses on a dirty database.

```
neurosearch nightly run --budget 2
```

**If you also want to exercise CR7 (Continuous Research's nightly refresh) the same night**, add its own
separate budget -- plain `--budget` alone does NOT touch CR6/CR7 at all:

```
neurosearch nightly run --budget 2 --research-refresh-budget 1
```

See "CR7" below for why this matters and how to confirm it actually ran.

It prints the authorized amount and asks before enqueuing. The worker then does the actual work, so leave it
running (`neurosearch worker`). Next morning:

```
neurosearch nightly report
```

That report IS L-41's gate: can you explain what changed overnight from it, without opening Findings? Yes/no
is the whole answer. If you want the numbers behind it:

```
neurosearch nightly report --json
```

L-31's gate ("every number reconciles to the tables it came from") closes on the same night — the `--json`
output is `delta.for_envelope()`'s data, and its tests already pin each number to its table.

To leave it on every night instead of running it by hand, set `NEUROSEARCH_T4_NIGHTLY_BUDGET_USD=2` in the
environment the worker runs in (and optionally `NEUROSEARCH_T4_NIGHTLY_HOUR`, default 2 = 2am local). Check
with:

```
neurosearch nightly status
```

## L-21 — does the worker keep going with the lid open and the display asleep?

Two ten-minute waits, no spend. Full detail in `docs/L21-POWER-ASSERTION.md`; the short version:

```
neurosearch worker
```

1. Lid **open**, let the display sleep, wait ~10 min. Did jobs keep getting claimed? (`neurosearch doctor`
   shows the power-assertion line.)
2. Lid **closed**, wait ~10 min, reopen. Did it stop? (Expected: yes — that confirms the documented limit.)

Two yes/no answers, recorded in `EXECUTION-LADDER.md` under L-21, closes it.

## Still separately blocked on you (earlier stage, unchanged)

- L-06: the ~20-minute blind review of the kept-rate sample (L-05 built it). L-07 and Stage 9 wait on this.
- L-08: the brief-text relevance backtest needs a Mac run with your OpenAI key (~$0.03 in embeddings).

## L-51 — the exception queue, against your real project

No spend, reads only, approves nothing:

```
neurosearch project review-queue "<your project name>"
```

The gate is three questions: is it short? does every line say why it's there? is the disagreement you already
know about in it (it can never be hidden by the cap)? Add `--json` for the data behind each line.

## L-60 — T5 adjudication on a real night (optional add-on to the L-30 run)

Same command as L-30 with one more flag. It's a second, separate cap (Sonnet-tier calls), disclosed separately
before it asks:

```
neurosearch nightly run --budget 2 --t5-budget 1
```

Next morning the Morning Report has an "Adjudicated N disagreement(s)" line and each verdict is a suggested
finding in the ordinary review. The gate is: were those verdicts worth their line — did they change what you
know or would do? Nothing was decided for you; no Claim or tension status moved.

## L-61 — T6 in the report (nothing extra to run)

When a night's output leaned on a number nobody has measured against your data, the last lines of
`neurosearch nightly report` say so, capped at three. On a quiet night there is no such line. The gate is the
same as L-60's: was it worth its line — did it change what you'd check?

## L-40 — the "Tonight" UI, once for real

In Findings, on a stale tier's row, press **When…** and pick **tonight** (free on Claude Code) or **overnight as a
batch** (half price). Leave the Mac the way you normally would. In the morning the same card says what happened.
The gate: was the outcome clear from that card alone, without opening the jobs console? If you closed the lid and
nothing ran, that is L-21's known limit and the card should have said "eligible from", not promised a time.

## L-06 → L-07 — the kept-rate review, then one command

Produce the sample (on the Mac; reads your real project, writes one JSON, changes nothing):

```
.venv/bin/python tools/sample_findings.py --out evals/p53-sample-2026-09-15.json
```

Fill in every `review` block (~20 minutes, blind to model). Then the decision is:

```
.venv/bin/python tools/decide_kept_rate.py --sample evals/p53-sample-2026-09-15.json
```

It prints the E5 rule's verdict and the numbers behind it, and refuses to decide on a partial review.

## L-08 — brief-text relevance backtest (~$0.03 in embeddings, needs your OpenAI key)

```
.venv/bin/python tools/relevance_backtest.py --project <your project id>
```

## L-70 — the P7 estimate you decide on ($0 to produce; the experiment itself waits on L-07)

```
.venv/bin/python tools/p7_estimate.py --project "<your project name>" --out evals/p7-estimate-2026-09-15.json
```

Arm A is priced the way the app prices any findings pass; Arm B is labelled as an assumption (no Arm B exists yet).

## L-52 — after you've judged L-51 on your real project

If the queue was short, defensible and showed the disagreement you know about, set
`NEUROSEARCH_MORNING_REPORT_NEEDS_ME=1` where the worker runs. That is the whole of v2.

## Push

Everything above is committed locally and not on GitHub (the sandbox can't push):

```
git -C "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO" push origin main
```

## CR7 — did the nightly worker actually do research overnight, for real

This is the SAME `nightly run` as L-30 above, but you must add `--research-refresh-budget` or CR6/CR7 never
runs at all:

```
neurosearch nightly run --budget 2 --research-refresh-budget 1
```

Next morning, the plain report may say nothing about it either way (a quiet CR6 section and an "off" CR6
section currently look identical in the plain-text report — a real gap, but the JSON already tells you which):

```
neurosearch nightly report --json
```

Look at the `research_refresh` key: `null` means the flag was never passed that night (CR7 did not run --
try again with the flag); a dict with `"ran": true` and a `"count"` means it fired -- that count is how many
research refreshes it requested (CR6's own async harvest; not yet confirmed changes, just started).

**What "pass" looks like**: `research_refresh` is non-null, `"ran": true`, and either a real count > 0 (it had
something due) or an honest 0 (nothing was due that night -- both count as CR7 happening for real, per the
gate's own rule). **What "fail" looks like**: it errors (`"ran": false, "error": ...`) instead of completing.
Tell Claude what the JSON showed -- this is CR7's whole gate ("did it happen for real," never faked or
simulated).

**Unlocks**: CR8c widening only reads CR8b-gate's evidence below, not CR7's -- CR7 mainly confirms the
nightly research pipeline itself is trustworthy day to day. No cost beyond the `--research-refresh-budget`
amount you set; reads/writes only your real project data through the existing CR5 refresh path (same one
`project refresh-need` uses by hand).

## CR8b-gate — selective acquisition, on a real Evidence Target

No new command -- CR8b either runs on its own during a nightly pass (if `cr8b_enabled`) or you can trigger it
directly against a project with an open Evidence Target:

```
neurosearch project acquire-evaluate <project>
```

$0 beyond whatever capture_best()'s existing budget machinery already authorizes (same shared mechanism CR5
uses); mutates real project data (queues an ingest job like any normal acquisition).

Read the result, then answer these against what actually happened (not a fixture) -- full text and the "do not
manufacture a verdict" caution live in `EXECUTION-LADDER.md` under `CR8b-gate`:

A. Did a real project have an open Evidence Target? B. Was the candidate genuinely justified for that target?
C. Did it stay within the intended bound (one per target per pass)? D. Was the provenance (why THIS source,
for THIS target) understandable? E. Did it avoid pulling in anything unrelated? F. Did the source actually help?
G. Was cost behavior correct and visible before it happened? H. Did the Morning Report / Project Delta surface
it appropriately?

**Unlocks**: CR8c (an admission rule, not more implementation) only after this evidence exists. Do not build
CR8c from a synthetic pass.

## LP6 — a real plan change reconstructed from provenance alone

No lookup command to remember: the existing Plan tab already surfaces this without you hunting for it. LP3
only ever writes a pending plan-update row when a Claim's evidence change genuinely affects a plan step -- so
if CR5/CR6/CR7's nightly refresh changes a Claim's status on a real project (strengthened / weakened /
contradicted), a pending update already appears in the Plan tab, naming the Claim and the reason, the same
place LP5's Accept/Reject with full provenance already lives.

**What you do**: use Neuro normally; when you notice a pending plan update, either accept/reject it yourself
(LP5 already records why), or just tell Claude the Claim id from that update. **What Claude does**: verifies
the resulting `plan_updates` row alone reconstructs "your plan changed in one place" (previous state, resulting
state, reason, claim linkage, system vs user provenance) with no other lookup needed. **Pass**: it does, with
nothing missing. **Fail**: something is missing or requires a second lookup to explain -- report that as its
own small gap, not a redesign.

**Unlocks**: nothing further is planned behind LP6; it is the mission's own closing measurement for P10.

## AD4B — is the adaptive-discovery sample big enough to compare against static

Keep using Discover normally (capture/reject through `project discover` or the UI), then:

```
neurosearch project discover-report <project>
```

$0, reads only. **Pass** looks like: the report says `usable_sample` (rather than `thin_sample`/`no_usage`)
AND its own capture-rate / yield / review-burden numbers leave you clearly satisfied either way. **Only if**
that report's numbers leave real ambiguity is AD4B (a controlled interleaving or occasional static-control
batch, the smallest design that answers the exact unresolved question) worth building -- never speculatively,
never a general analytics platform. Nothing changed here this pass -- the command already does exactly what
this gate needs.

## FM1-gate — one real Field Map run

```
neurosearch project field-map <a real project with 1+ scholarly/review sources with a DOI>
```

$0, Crossref-only, read-only (writes nothing to candidates/sources/claims/targets/the Planner). Verified this
session that the CLI's plain-text output already carries everything needed for the six A-F judgment questions
(seeds + provenance, per-seed fetch detail, all six completeness counters, an explicit
`sufficient_for_underrepresented_conclusion` line, and per-field-area representative references) -- see
`EXECUTION-LADDER.md`'s `FM1-gate` entry for the exact six questions. Nothing changed here this pass; the
one-command output was already sufficient.

**Unlocks**: FM2 only if your answer to question F is genuinely yes -- and even then FM2 is never auto-built
from that alone.

## Send Screenshot — the live-Chrome acceptance pass (still the only thing blocking this mission's close)

Full engineering history is in `docs/SEND-SCREENSHOT-2026-09-16.md` (four independent repair rounds); you do
not need to read it to run the gate. Load the unpacked extension (dev mode, `chrome://extensions`) at its
current version and, on a few real pages, walk this list:

1. **Ordinary page** -- one click on "Send screenshot," no intermediate chat; a Suggested Finding appears
   automatically once ingestion completes.
2. **A page wider than your viewport** -- exercises the new horizontal tiling; check the stitched image for
   seams or a duplicated sticky header.
3. **A lazy-load / infinite-scroll page** -- exercises the per-fold pixel/time ceilings and grid growth; a
   capture that hits a ceiling should land as `partial_page` with an honest reason, not silently truncate.
4. **Close and reopen the popup mid-capture** -- the capture should still complete or recover cleanly, not
   vanish or duplicate.
5. **Check scroll position is restored exactly afterward** -- in a success, a partial, and a forced-failure
   case if you can trigger one (e.g. going offline mid-upload should show "Retry send").
6. **Navigate away (same-origin) mid-capture** -- it should abort cleanly, never send a mismatched or
   half-captured image.
7. **Open the resulting source in the drawer** -- confirm provenance reads correctly: full_page vs
   visible_only, the partial reason when relevant, and your own note kept visibly separate from the evidence.

**Pass**: every case above behaves as described, on real pages, in your real Chrome. **Fail**: record exactly
which case and what happened -- that becomes a new, scoped repair round, not a rewrite. **Unlocks**: closes the
"send screenshot" mission outright; nothing else is queued behind it.

## Course Scanner — the one piece never exercised live

The scan/enumerate ALGORITHM itself is already live-validated for real: CS5's live pass against your actual,
logged-in SMB Market classroom got 43/43 lessons across all 6 modules, zero failures (`docs/COURSE-SCANNER-
2026-09-15.md`, "CS5"). What has never been exercised live is the actual extension UI wiring around it --
that pass drove the scan library directly, bypassing the popup/background chrome entirely (Claude in Chrome
cannot reach `chrome://extensions`).

Load the unpacked extension for real and, on a course page (SMB Market or any similar platform):

1. Press **Scan this course** from the popup itself (not the library directly) and confirm it enumerates the
   same lesson count you'd expect.
2. **Cancel a scan in progress** through the real popup control -- confirm it actually stops, not just visually.
3. **Close and reopen the popup mid-scan** -- confirm `background.js`'s durable per-tab state picks the scan
   back up or reports it correctly, rather than losing it.

**Pass**: all three behave as expected against the already-proven 43/43 scan logic. **Fail**: record exactly
which of the three broke -- the underlying scan/enumerate logic is proven and should not need reopening; a
failure here is almost certainly in the popup/background wiring, not the crawler. **Do not** re-run or reopen
CS0/CS5's already-proven scan logic to chase this -- it stays closed.
