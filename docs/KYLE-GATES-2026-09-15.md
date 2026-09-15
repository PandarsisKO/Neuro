# The four open gates — exactly what to run, nothing more

Four rungs are code-complete and tested but their gates are real-world measurements only you can take.
Everything below is copy-paste. Nothing here spends money except the one line that says so.

## L-30 — one real night at $2 (also closes L-31 and L-41's data side)

Spends up to $2 total across your projects. It runs preflight first (full integrity check + verified backup)
and refuses on a dirty database.

```
neurosearch nightly run --budget 2
```

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
