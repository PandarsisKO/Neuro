# Local model substitution — audit of the live database (0.56.4)

**Method.** Read-only (`mode=ro&immutable=1`) over the app's own hourly verified backup
`data/backups/neurosearch-20260909-1939.db`. The live database was never opened; nothing was written anywhere.
Provenance comes from `project_source_analysis.routing` and `project_notes.routing`, which have carried
`requested_model` / `actual_model` since L1.

## 1. How much was substituted

2,792 analyses, 2,377 with routing recorded (415 predate the field).

| analysis_kind | executed_by | requested | actual | n |
|---|---|---|---|---|
| relevance | (older) | claude-sonnet-5 | claude-sonnet-5 | 781 |
| relevance | local | claude-sonnet-5 | claude-sonnet-5 | 448 |
| **summary** | **local** | **claude-sonnet-5** | **claude-haiku-4-5-20251001** | **372** |
| summary | api | claude-sonnet-5 | claude-sonnet-5 | 363 |
| summary | (older) | claude-sonnet-5 | claude-sonnet-5 | 230 |
| **relevance** | **local** | **claude-sonnet-5** | **claude-haiku-4-5-20251001** | **128** |
| summary | local | claude-sonnet-5 | claude-sonnet-5 | 55 |

**500 of 2,377 artifacts (21%) ran on a model the app did not request** — 372 findings passes and 128 relevance
rankings. Every one of them went through the local Claude Code path. The API path never substituted.

## 2. It is not configuration, and it is not fixed by removing the .env line

The `NEUROSEARCH_CLAUDE_CODE_MODEL` line was the obvious suspect and was commented out on 09-10. But the
substitution is **per call, not per period**: within the 22:00 ten-minute bucket on 09-09 there are 71 calls that
returned Sonnet 5 and 40 that returned Haiku. `local` runs that honoured the pin (448 + 55 = 503) and local runs
that did not (500) are almost exactly balanced and fully interleaved.

```
09-09, 10-minute buckets        sonnet5   haiku
  21:50                              81       0
  22:00                              71      40   <- same bucket, both models
  22:10                               0      33
  22:50                               1      29
  23:20                              18       0
```

A per-call split that config cannot explain points at the provider: the local CLI serves a different model when it
chooses to (a usage ceiling on the pinned model is the likeliest reason — `claude_code.health()` reports `ready`
throughout, so the app cannot see it). **Conclusion: the local transport cannot guarantee a model.** Any task whose
model was chosen by measurement cannot be `local_capable` without a returned-model check.

## 3. What the 500 substituted artifacts actually tell us about Haiku

This is an accidental natural experiment on Kyle's real corpus — far larger than any eval arm — and it points the
opposite way to the assumption that pins `findings.extract` to Sonnet 5.

All findings, by the model that actually wrote them (n = 11,172 with routing):

| model | findings | sources | per source | reserve % | mean importance | median chars | became a Claim |
|---|---|---|---|---|---|---|---|
| sonnet-5 | 7,101 | 656 | 10.8 | 1.4% | 3.02 | 184 | 89.6% |
| haiku-4-5 | 4,071 | 336 | 12.1 | 11.5% | 3.20 | 200 | 83.2% |

**The raw reserve gap is a confound, not a result.** Haiku's sources are longer (median 14.9 min vs 10.8), and the
findings cap is length-aware. Restricting to sources of 10–40 minutes:

| model | sources | findings/source | reserve/source | reserve % |
|---|---|---|---|---|
| sonnet-5 | 255 | 11.3 | 0.06 | 0.6% |
| haiku-4-5 | 180 | **15.6** | 0.17 | 1.1% |

Length-matched, Haiku writes **38% more findings per source** and the 8× reserve gap collapses to 0.6% → 1.1%.
Combining with the Claim-conversion rate: Haiku yields ~13.0 claim-worthy findings per source against Sonnet 5's
~10.1. On the two things this database can measure — volume and downstream survival — **Haiku is not worse.**

**What this does NOT establish.** Assignment was not random (substitution came in bursts, which correlate with heavy
batch periods and therefore with source type). No source was processed by both models, so nothing here is a paired
comparison. Claim conversion was itself mostly performed by `claude-sonnet-4-6`, so the downstream measure carries
its own routing. And neither count nor survival measures whether a finding is *right* — quote validity is enforced
at write time, so every stored finding passes it and the field carries no signal. Nothing here justifies changing
`findings.extract`; it justifies stopping treating Sonnet 5 as obviously necessary, and it raises the value of the
paired comparison.

## 4. Open item

`claims.extract` normalization is recorded as `claude-sonnet-4-6` for 5,746 claims and `sonnet-5` for 1,752, with 8
on Haiku. The 4.6 rows predate the decision engine. No substitution to investigate there, but the split is worth
knowing before reading any Claim-quality number.
