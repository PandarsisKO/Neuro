# L-21 — macOS power assertion: what's measured, what's assumed, what's left

## What this code does

`neurosearch/power_assertion.py` holds a `caffeinate -s` system-sleep assertion for exactly as long as there is
active or near-future (within 24h) scheduled autonomous work — started alongside `jobs.start_workers()`, released
when the queue goes idle, checked every 30s by a background thread. It is a no-op (and says so honestly via
`power_assertion.available()`/`status()`) off macOS or without `caffeinate` on PATH.

`neurosearch doctor` now reports whether an assertion is currently held (L-21's line, alongside L-10's preflight
line), and the check is explicitly labeled "display-sleep only, NOT proven to survive a closed lid" so the
product never overclaims what it hasn't measured.

## What's known from documentation, not from testing this session

A `caffeinate -s` (or any `IOPMAssertionCreate`-based) system-sleep assertion does **not** keep a MacBook awake
once the **lid is closed**, unless an external display is attached and macOS's clamshell-mode conditions are
met. This is a hardware/firmware-level (SMC) sleep trigger, not something any user-space power assertion can
override — well-documented Apple and third-party developer behavior, not something this session needed a real
Mac to establish.

## What genuinely needs Kyle's real MacBook — the one open question

With the worker running and the assertion held:

1. **Lid open, display allowed to sleep (display off, system still "awake")** — does the worker keep polling
   and executing jobs? This is the case the assertion is actually designed for and the one this rung's gate
   needs measured, not assumed.
2. **Lid closed** — does the worker stop, as documented above? (Expected: yes, it stops — this confirms rather
   than contradicts the known limitation, but should still be observed once rather than only inferred.)

### The two-minute test

```
neurosearch worker
```

1. Leave it running, let the display sleep (or manually trigger display sleep) with the lid **open**. Wait ~10
   minutes. Check `neurosearch doctor` or the job list for continued activity — did any job run or get claimed
   during that window?
2. Separately, close the lid for ~10 minutes with the worker running. Reopen and check the same thing.

Record both answers (yes/no, and roughly how the queue looked before/after) as a short note back to Claude or
directly in `EXECUTION-LADDER.md`'s L-21 entry — that closes this rung. Until then it stays open even though
the software side is built and tested, because the gate is explicitly a measured-reality gate, not a
code-complete gate.
