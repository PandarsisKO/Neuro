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
