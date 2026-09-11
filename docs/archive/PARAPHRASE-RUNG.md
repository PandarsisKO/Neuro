# The paraphrase rung — the one limitation tonight measured but did not fix

Written 2026-09-10 overnight, immediately after 0.58.8 measured the problem. **Not built**, deliberately.

## The measurement

`findings_quality` catches near-verbatim repeats and rewordings. It cannot catch a paraphrase — the same fact in
different words. Three found by hand on the live corpus, with their scores on every lexical measure available:

| set-Jaccard | the pair |
|---|---|
| 0.33 | *"SBA loan repayment data shows acquired small businesses have a 95%+ five-year success rate…"* / *"SBA loan repayment data confirms acquired small businesses succeed at 95%+ over 5 years…"* |
| 0.20 | *"Cash investors buying into the acquisition LLC typically receive profit distributions alongside the operator…"* / *"Cash investors typically become equity partners sharing ongoing profit distributions alongside the operator…"* |
| 0.18 | *"Posting regular progress updates on LinkedIn/Facebook/Instagram/Twitter attracts investors organically…"* / *"Posting real-time updates on LinkedIn, Facebook, or Instagram about the buying process draws in investors organically…"* |

The blocking constraint is not the threshold, it is the *ordering*: 856 pairs sit in the 0.30–0.35 band and that band
is genuinely mixed — two **different** off-topic videos, each described as off-topic, score 0.33. No lexical rule
separates a paraphrase from two findings that merely share vocabulary, because lexically they are the same thing.

## What would fix it, and what it costs

Embeddings. `text-embedding-3-small` at ~50 tokens per finding: **~$0.013 for 13,000 findings**, then a few cents a
month as findings accrue. Cosine similarity over finding vectors separates "same proposition" from "same topic" in a
way word overlap cannot.

## Why it is not built

Three reasons, in order of weight:

1. **It would repeat tonight's mistake.** 0.58.6 and 0.58.7 exist because F1 and C1 shipped with guessed constants
   that real data demolished. A cosine threshold is another guessed constant, and the only way to set it honestly is
   to embed a real corpus and sample the bands — which costs money and therefore needs Kyle's consent.
2. **It is the app's first paid $0-tier feature.** Everything in `findings_quality` is free today, which is why it
   can run on every Findings load. An embedding-backed check has a per-finding cost, needs storage, needs a backfill
   job, and needs to decide what happens when a finding has no vector yet. That is a rung, not a tweak.
3. **The current filter is honest about it.** `review()["limits"]` says the duplicate count is a floor, and
   `promotable()` tells the user to skim before approving in bulk. A known, stated limitation is not an emergency.

## The shape, when it is built

- Reuse the existing embedding path (`embeddings.py`) rather than adding a second one; store finding vectors beside
  chunk vectors, keyed by note id and content hash so an edited finding re-embeds and nothing else does.
- A `low`-lane backfill job, resumable, bounded — the same shape as `refresh_skipped_metadata`.
- Keep the lexical pass as the first filter: it is free, it catches the verbatim cases, and it reduces the pairs a
  cosine check has to consider. Cosine is the second opinion, not the replacement.
- **Set the threshold the way 0.58.6 and 0.58.8 set theirs**: embed one project, score the candidate pairs, sample
  the bands by hand, and write the band table into HARDENING.md before choosing a number. Budget one paid run for
  calibration and say what it cost.
- Exit test: the three pairs above cluster, and the 0.30–0.35 lexical band's false positives (two unrelated
  off-topic findings) still do not.

## The decision for Kyle

One line: *is paraphrase-level duplicate detection worth $0.013 plus a calibration run?* If yes, this is a
half-day rung with a clear exit test. If no, the filter stays free and states its floor, which is a defensible
place to leave it.
