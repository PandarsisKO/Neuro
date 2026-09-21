# Mission: close the two open threads from the Discovery relevance-cliff work (2026-09-20)

Two things are still open from the "am I missing genuinely valuable content" investigation. Neither is started —
this doc is the plan for both, so you can greenlight one, both, or neither.

---

## Mission A: let CHAT feedback actually reach a Discovery verdict

**Why this matters (your words):** "that's where I will be giving feedback to the app and help refine plans."
Right now your chat tools (`update_brief`, `record_fact`, `propose_claim`, `set_source_priority`, `note_gap`,
`save_finding`) can shape briefs, claims, and priorities -- but none of them can touch a `skipped_low_relevance`
verdict. If you tell the app in chat "I want more from X" or "that topic matters more than the score suggests,"
nothing currently moves. The only lever that reaches skipped candidates today is the one-time script I just ran
for you by hand.

**Target outcome:** you say something like "pull back more from Acquiring Minds" or "I care more about
valuation-multiple content than the score suggests" in chat, and the app actually resurfaces matching skipped
candidates -- live, not via a script I run for you later.

**Design decision needed up front, narrowing to the smallest real version:** start with creator-level, not
topic-level. Topic-level (re-scoring skipped items against a stated interest) is a much bigger, fuzzier build
(needs a second relevance pass, a way to define "topic," and a way to avoid it becoming a second silent filter).
Creator-level reuses the exact mechanism already shipped and proven today (405 real candidates recovered) --
it's the same math, just triggered from chat instead of from a script.

**Steps:**
1. Add `candidates.py::reconsider_creator(project_id, creator, note)` -- same threshold logic as
   `tools/resurface_creator_trusted_candidates.py` (creator has >=1 kept source, relevance >= cutoff - trust
   boost), but scoped to one named creator and callable live instead of batch-run. Returns the count and ids
   rescued, same non-destructive move to `available`.
2. Add a new chat tool in `qa.py`, e.g. `reconsider_creator(creator: str, note: str)`, exposed to the model
   like the existing six chat tools. It calls step 1's function and returns a plain-language count back into
   the chat reply ("moved 12 candidates from X back into review") so you always see what it did -- never a
   silent action.
3. Guardrail: if the named creator doesn't match anything with `pos > 0` (i.e. you've never actually kept
   anything from them), the tool says so explicitly rather than silently doing nothing -- so it never feels
   broken.
4. Tests: one new test file mirroring the existing candidate-state tests, covering the same cases already
   covered for the batch script (creator with disposition, creator with none, empty result, idempotent re-run).
5. Add a gate entry to `docs/KYLE-GATES-2026-09-15.md` (or a new dated gates doc) with the acceptance
   questions: does it feel natural to ask for in chat? does the count it reports match what you expected? does
   re-running it harmlessly find nothing left?
6. You run it live in a real chat session against your business-acquisition project and judge it.

**Explicitly NOT in this first version** (would need its own separate mission if you want it later):
topic/interest-level resurfacing (re-scoring skipped items against something you describe in chat, rather than
a creator you've already proven you trust). That needs a second model-scoring pass and real design work on how
"topic" gets matched, and risks becoming a second silent filter if done carelessly.

---

## Mission B: AD4B -- does the current filter actually cost you anything, in real numbers

**CORRECTED 2026-09-20, after reading the review code.** The first version of this section assumed low-scoring
candidates were HIDDEN from Kyle, and proposed an "unfiltered review lane" sampled over future batches. That
premise was wrong, and the design built on it has been replaced. What the code actually does
(`web/js/sources.js` line 32, `db.proposed_sources`): the review card shows EVERY proposed item, sorted by
relevance. The score does not hide anything -- it decides which rows arrive PRE-TICKED (the top `want`, the
"pick top N" box). Bulk-approving accepts the pre-tick. So the 9,691 `skipped_low_relevance` candidates were on
screen, unticked, and never scrolled to.

**Why this is still open:** the discover-report gate's own text says plainly: "NOT a comparison against static
ranking, which was never shown to the user and cannot be reconstructed from current state." Kyle's answer
("fine as long as I am not missing out on potentially novel or insightful findings") was conditional, not a
close -- the answer is not known yet, he is just currently comfortable with the unknown.

**Target outcome:** a real number: of what the filter rejected, what fraction would Kyle actually have kept?

**The design, given what the code really does:** a blind spot-check, not a sampled lane. Draw a stratified
sample of already-rejected candidates, strip the score and the model's verdict out of the reviewable part, and
have Kyle judge keep/skip cold from exactly what the ranker saw (title, creator, description, length, date).
Then compare his blind calls against the algorithm's. Same number, except it runs against the existing 9,691
backlog instead of waiting weeks, costs nothing in model spend, and is a real measurement rather than a
rubber-stamp. Same shape as `tools/sample_findings.py` (L-05).

Blind matters here for one specific reason: Kyle bulk-approves. Shown the score, he would agree with the score,
and the measurement would report his deference back to him as agreement. `tests/test_ad4b_blind_sample.py`
holds that invariant -- the reviewable half of the file must leak no score, band, verdict, url or id.

**Built:**
- `tools/ad4b_blind_sample.py` -- stratified across the four rejection bands (0-19, 20-34, 35-44, 45-49; the
  45-49 band is the "one point under the cutoff" cliff and is the one that matters most), bands interleaved so
  position leaks nothing, fixed seed so the file is reproducible, verdicts held in `_scoring_key` at the bottom.
- `tools/ad4b_score.py` -- reads the filled rubric back against the key: headline rate, cut by band and by
  creator, the list of what Kyle would have kept with what the model said about each, and a verdict.
- Thresholds are set in the source BEFORE the run, not argued afterwards: under 10% kept -> AD4B closes, the
  filter is fine. 10-25% -> real but not alarming; the band table says whether widening the creator-trust nudge
  is enough or the score itself is the problem. Over 25% -> the cutoff or the ranking prompt should change.

**Steps:**
1. Kyle runs `tools/ad4b_blind_sample.py` to generate a 40-item rubric (~20 minutes of his time to fill in).
2. Kyle fills in `review.keep` / `review.why` per item, without scrolling to `_scoring_key`.
3. Kyle runs `tools/ad4b_score.py` on the filled file; it prints the number and the verdict.
4. AD4B closes or turns into a specific, evidence-backed change. Either way it stops being an open unknown.

## Status: both built (2026-09-20)

Both missions are implemented and compile clean. Nothing here has been live-tested against the real database --
the bridge shell has no project .venv, so every change was verified by `py_compile` plus offline tests against
synthetic data. Kyle runs the real suite.

**Mission A (shipped):** `candidates.reconsider_creator()` + a `reconsider_creator` chat tool in `qa.py`
(schema, label, system-prompt guidance, handler). Tests in `tests/test_ad1_chat_reaches_discovery.py`.
**Mission B (shipped):** `tools/ad4b_blind_sample.py` + `tools/ad4b_score.py`. Tests in
`tests/test_ad4b_blind_sample.py`, including the blindness invariant.

### Run these (on the Mac, real Terminal)

1. The new tests plus everything the change could have disturbed:

```
.venv/bin/pytest tests/test_ad1_chat_reaches_discovery.py tests/test_ad4b_blind_sample.py tests/test_n7_pool.py tests/test_s75_discovery_excludes.py tests/test_s66_harvest_isolation.py tests/test_s73_members_only_never_outrank.py tests/test_k4_explore.py -q
```

2. Mission A is then live in chat -- no command. Open the project chat and say something like "I want more from
   Acquiring Minds" or "Jonathan Jay got filtered out too aggressively." It should report a count and say the
   items are back in review, not added.

3. Mission B, generate the blind rubric:

```
.venv/bin/python tools/ad4b_blind_sample.py --project c752ed152ec942dd97b9a94c3f1b3b96 --out evals/ad4b-sample-2026-09-20.json
```

4. Fill in `review.keep` (true/false) and `review.why` for each item under `review_these`. Do not scroll to
   `_scoring_key` until done. Then:

```
.venv/bin/python tools/ad4b_score.py --in evals/ad4b-sample-2026-09-20.json
```

### Kyle-gates

- **Mission A:** does asking in chat feel natural? does the count match what you expected? does asking twice
  correctly report nothing left rather than pretending to work? does an unknown creator say so plainly?
- **Mission B:** the headline rate is the answer to the question you left conditional at AD4B. Under 10%, AD4B
  closes. Over 25%, the cutoff changes. In between, the band table decides.

## What I need from you to start either one

Nothing blocking -- both are ready to build as soon as you say go. If you want just one to start, say which.
If you want both, I'd build Mission A first (it's the smaller, more directly requested one -- "that's where I
will be giving feedback"), then B.
