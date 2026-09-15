# Morning batch — everything that needs Kyle, in order

Generated overnight, 2026-09-15. Assume a fresh terminal for every command below (each one has its own `cd`).
Nothing here touches money beyond what's labeled. Total estimated time: ~30 minutes of your attention, spread
across waiting for a few commands to finish. Do these in order — later ones depend on earlier ones passing.

---

## 1. Validate last night's two code fixes (L-02, L-03) — 1 min, $0

```
cd "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO"
```

```
.venv/bin/python -m pytest tests/test_r4_local_model.py tests/test_p1_perf.py -q
```

If it's all green: tell me "L-02/L-03 green" and I'll flip them to `[x]` in the ladder with the commit sha.
If anything is red that wasn't red before last night, tell me and I'll fix it before anything else runs.

---

## 2. Run the (now-fixed) prefilter eval — L-04 — ~1 min, $0

```
cd "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO"
```

```
.venv/bin/neurosearch eval --prefilter --out evals/prefilter-2026-09-15.json
```

Paste me the output (or just say "done, committed" once you `git add`/`git commit` the artifact) — I'll read the
JSON and apply the frozen decision rule from the T4 plan myself (enable `NEUROSEARCH_FINDINGS_PREFILTER=1` only
if net savings > 0 AND relevant-window recall ≥ 0.98), then record it in `HARDENING.md`. Nothing for you to
decide here — just run it.

---

## 3. Generate the kept-rate review sample — L-05 output — ~10 sec, $0

```
cd "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO"
```

```
.venv/bin/python tools/sample_findings.py --out evals/p53-sample-2026-09-15.json
```

---

## 4. Review the sample — L-06 — the only genuinely judgment-based item, ~20 min

Open `evals/p53-sample-2026-09-15.json` in any editor. For each of the ~40 items under `review_these`, read the
finding and fill in:
- `review.accurate`: `true`/`false` — does it faithfully represent its source?
- `review.keep`: `true`/`false` — would you actually keep this finding?
- `review.why_not`: one short line, only when `keep` is `false`.

**Don't scroll down to `_scoring_key` until you're completely done** — that's what tells the review which
finding came from which model, and looking early un-blinds you. Save the file when finished, then tell me
"L-06 done" and I'll compute the kept-rate/cost-per-kept decision (L-07) myself — that one's mechanical once
your judgments are in the file.

---

## 5. Brief-text relevance backtest — L-08 — ~30 sec, a few cents (OpenAI embeddings)

Only run this if `OPENAI_API_KEY` is set in your environment — it makes exactly one real embedding call per
project (cached after that, so re-runs are free).

```
cd "/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO"
```

```
.venv/bin/python tools/relevance_backtest.py --project c752ed152ec942dd97b9a94c3f1b3b96 --out evals/relevance-backtest-2026-09-15.json
```

Paste me the output or the file — I'll read the verdict and decide whether switching the T4 ranking basis is
warranted (per L-08's own rule: only if it improves without regressing). No decision needed from you, just run
it and hand me the result.

---

## 6. Housekeeping — L-01 — 5 seconds, whenever

The dead `deno/env` line in your `.zshrc` I flagged earlier. Only if it's still bothering you; it's cosmetic.

---

## 7. Kick off Codex on P0, whenever you're ready

Codex's lane (P0 audit, `EXECUTION-LADDER.md` L-10 through L-17) is fully unclaimed and doesn't collide with
anything I touched overnight (different files: `db.py` preflight helpers, not `t4.py`). Point Codex at
`HANDOFF.md`'s "Codex, your lane" section whenever you start that session — it has the three concrete inputs
from Wednesday's incident already written down.

---

## What I did overnight without you (for reference, no action needed)

- **L-02** — fixed `neurosearch eval --prefilter`'s eval-isolation bug (commit `01fa165`)
- **L-03** — fixed the `.env` task-model leak into pytest (commit `01fa165`)
- **L-05** — built the kept-rate sample script (commit `aa53a9c`)
- **L-08** — built the relevance backtest script (commit `15e489d`)
- Full detail in `HANDOFF.md`'s "Autonomous execution pass" section.

Everything past this point in `EXECUTION-LADDER.md` (Stage 3 onward) needs either Codex's P0 to land first, or
a decision only you can make (L-07, L-08's verdict) — nothing else was safely runnable without you or real
money changing hands, so I stopped there rather than guess.
