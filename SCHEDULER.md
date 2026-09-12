> PARKED RUNTIME DESIGN — not the product scheduler. Priorities: DEVELOPMENT-OPERATING-SYSTEM.md and PRODUCT-SCHEDULER.md. Historical unfinished items are not a work queue.

# The Bidirectional Scheduler — a design exploration

**Status: design, not built.** Nothing in this document is implemented. It exists to be argued with before any
code is written. Where it says "measure first", that is not politeness — three times this month a measured
reading overturned a confident prediction of mine (the embedding matrix, `staleness.assess`, the Sources payload),
and the ideas below are exactly the kind that feel obviously right and can be quietly worthless.

## 0. The question

> Low-latency paid compute immediately claims high-user-value work while inexpensive local compute simultaneously
> claims complementary long-running/bulk work from the other end of the work set.

Two pools, claiming from two ends, meeting in the middle. The objective is stated as two things at once:

```
minimise    ∫ (mass of the user's unanswered questions) dt        ← time-to-useful-knowledge
    +  λ ·  (total money spent to finish the whole set)           ← total batch completion cost
```

These are not the same objective and they are not opposed either. The first is served by spending *fast money on
small things at the front*. The second is served by spending *no money on big things whenever there is time*. The
whole design is the coupling rules that stop either term from eating the other.

## 1. What the two pools actually are

| | **Paid (Anthropic API)** | **Cheap (local)** |
|---|---|---|
| marginal cost | real dollars per token | ~$0 (Claude Code subscription; true-local models on the M3 Max) |
| latency | seconds | seconds-to-minutes, and it queues behind itself |
| concurrency | high (dozens) | low (a couple of CLI sessions; one GPU) |
| quality | full | full for the CLI path; lower for small local models |
| the third pool | **Batch API**: ~50% off, up to 24 h, holds no worker | — |

The Batch API is not a footnote. It is a *third* pool with the cost profile of local compute and the quality of
paid compute, and its only price is patience. Several rules below exist purely to convert patience into money.

## 2. Why "two ends of one ordered list" is the wrong mental model

The tempting reading of "outside-in" is: score every item, paid takes the head, local takes the tail. That is
wrong, and worth being precise about why.

The tail of a value ordering is *the least valuable work*. Handing it to the free pool sounds thrifty, but the
free pool is not free in the only currency that is actually scarce here — **wall-clock on a machine with two CLI
slots**. Spending the scarce local pool on the provably least useful items is how you arrive, four hours later,
with a fully-processed pile of things nobody wanted and the interesting middle untouched.

The two ends are not two ends of one axis. They are **two different orderings over the same set**:

- the paid pool orders by *marginal knowledge per second of user waiting*,
- the cheap pool orders by *money avoided per unit of local time*.

An item can be near the top of both (a big, novel, mechanical source the user just added) or near the bottom of
both (a stale metadata backfill on a source that answered nothing). "Outside-in" means each pool walks its own
ordering from its own top; the "middle" is where the two orderings disagree least, and meeting there is a real
termination signal rather than an arithmetic coincidence.

**This is the justification for not using a single numeric priority.** One scalar makes the two objectives
commensurable at the margin, where they are not, and — worse for this application — it is unreadable. Kyle's own
principle from this week is that clarity *is* speed: the user must be able to look at the queue and understand why
this is running before that. "Score 0.71" explains nothing. "You're looking at it" explains everything.

## 3. Ordering dimensions

Six properties per work item. All cheap, all cacheable on a revision key, none requiring a model call.

| | dimension | how it is obtained | why it earns its place |
|---|---|---|---|
| **A** | **attention proximity** | open project, visible source, the thing just added, the source referenced by the live chat turn | the only dimension that changes the *felt* speed of the app |
| **Q** | **question pull** | overlap with open Evidence Targets / Research Tensions (`claims.triage` already computes this at $0) | work that closes a question is worth more than work that adds a fact |
| **N** | **novelty potential** | embedding distance from the item's centroid to the project's existing knowledge centroids | the biodiversity guarantee, made mechanical |
| **C** | **cost mass** | estimated tokens (already computed for batch planning) | the whole second half of the objective |
| **T** | **latency tolerance** | per-kind constant: chat = seconds, findings on a new source = minutes, corpus hygiene = days | what makes an item *eligible* to be patient |
| **D** | **determinism** | per-kind constant: embeddings/prefilter/dedupe/caption recovery = high; nuanced claim extraction = low | what makes an item safe to run on weaker compute |

**N deserves a note.** Novelty must be measured against what the store *already knows*, not against ingestion
order, or the fiftieth video from a favourite channel outranks the first video from a new one purely by arriving
later. Distance-to-existing-centroid is order-free by construction. It is also the dimension most likely to be
worthless in practice, which is why §8 says to validate it before building anything on top of it.

## 4. Tiers, not scores

Five tiers, defined by predicates a human can read. Within a tier, a cheap scalar tie-breaks — that is the one
place numeric ordering is honestly justified, because inside a tier the items really are comparable.

| tier | predicate (readable) | tie-break | who claims it |
|---|---|---|---|
| **T0 — asked for** | the user is waiting on it right now | none (FIFO) | paid, interactive |
| **T1 — in view** | A high: open project, visible source, just added | N desc | paid, interactive |
| **T2 — answers something** | Q above threshold | Q desc | paid, interactive → batch if C is large |
| **T3 — new ground** | N above threshold, no Q | N desc | batch, or local |
| **T4 — bulk** | everything else the user fed the machine | C desc (biggest first: most money avoided) | local, then batch |

Two rules keep this honest:

- **No item is ever deleted or marked done by the scheduler.** Kyle's workflow is "feed it everything as I find
  it, not knowing if it will benefit me later." A scheduler that garbage-collects the tail destroys exactly the
  asset he is accumulating. Demotion is the only downward move; T4 is a waiting room, not a bin.
- **Tier membership is recomputed, not assigned.** An item's tier is a function of current state, so opening a
  project re-tiers its work without any queue surgery.

## 5. The claiming mechanism

Not one `ORDER BY`. Each pool claims with **its own admission predicate plus its own within-pool ordering**,
against the same table, under the leases that already exist.

```
paid  claims:  tier IN (T0,T1,T2)  AND  paid_bucket.has_room()   ORDER BY tier, tie_break
local claims:  tier IN (T4,T3)     AND  D >= local_quality_floor  ORDER BY tier DESC, C DESC
batch claims:  tier IN (T2,T3,T4)  AND  T > 1 hour               ORDER BY C DESC   (cost-avoided first)
```

The important structural change is the **bucket, not the lane**. Lanes are a static partition of work, and Kyle
has already hit their failure mode twice this week — bulk claim extraction sitting in front of real work, and
background jobs he had to add a pause button for. A lane says *what kind of work this is*; it cannot say *how
much of the shared resource it may consume*. Replace the lane's role in admission with:

- **paid bucket**: rolling dollars/window **and** concurrent in-flight requests,
- **local bucket**: real CLI concurrency (2 today) plus a health probe,
- **batch bucket**: submitted-but-unfinished request count.

A pool claims only while its own bucket has room. Bulk work then cannot clog the API *structurally*, rather than
because the user pressed pause. (The pause button stays; it is now a user override rather than the only defence.)

## 6. Promotion, demotion, and hysteresis

An item moves when **the reason it was placed stops holding** — not on a timer.

1. **Attention promotion.** The user opens the project, or asks a question that touches the item → straight to
   T1/T0. If a local worker holds it, the worker yields at its next safe boundary (`check_cancel()` already marks
   these) and the paid pool re-claims it. Nothing is thrown away; the item resumes from its last completed unit.
2. **Aging promotion → *batch*, not interactive.** An item that has waited past its latency tolerance is
   promoted — but an item that has demonstrated nothing except patience should be cashed in for the *discount*,
   not for speed. This single rule is where most of the cost saving lives.
3. **Yield promotion (the bandit).** When an item completes, compare realised yield (findings kept, claims
   written, novelty residual) against what its tier predicted. Large positive surprise → promote its siblings
   (same source, same channel, same cluster). This is the only mechanism here that *learns where the value is*
   instead of guessing once at enqueue time, and it is what actually minimises time-to-useful-knowledge over a
   long session.
4. **Yield demotion.** Siblings of items that yielded nothing fall to T4. Still not deleted.
5. **Hysteresis.** A promotion count cap per item and a minimum dwell time per tier. Without these, rules 3 and 4
   oscillate and the queue thrashes — which the user experiences, correctly, as the machine being confused.

## 7. Stopping conditions

Most schedulers stop when the queue is empty. Kyle's queue is unbounded by design, so "empty" never arrives and
"stop" has to mean something else: **stop spending the expensive pool on this cohort.**

- **Marginal-yield floor.** Rolling novelty-per-item over the last *k* completions falls below a floor → the
  expensive pass over this cohort ends; the remainder is demoted to T4.
- **Question saturation.** Every open Evidence Target in the project is closed or has no remaining candidate
  above the overlap threshold → the paid pool has nothing left to earn here.
- **Cluster redundancy.** The last *k* items all landed inside an existing knowledge centroid's radius → stop
  this cluster and rotate to another. This is the biodiversity guarantee restated as a stopping rule: the
  scheduler is required to go somewhere else rather than mine one seam until it is exhausted.
- **Budget.** The rolling spend bucket (exists today).

And the hard rule again, because it is the one that protects the asset: **a stopping condition changes an item's
pool. It never marks it done, and it never deletes it.**

## 8. Work stealing

Classic random-victim stealing assumes homogeneous workers. These workers are not interchangeable, so stealing
has to be **directional and typed**.

- **Local steals up** when the paid pool is blocked (spend cap, rate limit, open breaker). It takes head items in
  descending D — the mechanical ones it can do at full quality — and *explicitly declines* low-D items rather than
  doing them badly. What it declined must be visible: "3 items are waiting for API-quality analysis" is honest and
  actionable; silently downgrading quality to look busy is the one failure mode that would violate the mission's
  north star.
- **Paid steals down** when the head is empty, the user is idle, and the spend bucket has room — and it routes
  what it steals to the **Batch API**, never to the interactive endpoint. Idle interactive capacity is thereby
  converted into cheap patient capacity instead of being wasted or, worse, spent at full price on bulk. This is
  the highest-leverage rule in the document for the second half of the objective.
- **Neither pool steals a leased item.** Leases and `bumped_at` already enforce this.
- **The meeting condition.** When the head cursor and the tail cursor would claim the same item, the cohort's
  expensive pass is complete. That is a real, explainable state and it should be shown: *"the two ends met — 41
  sources analysed at full depth, 380 held for background."*

## 9. What must be measured before any of this is built

R0's perf ledger already answers the first and third.

1. **Per-pool throughput and idle time.** How much interactive capacity is genuinely idle? If the answer is
   "almost none", §8's steal-down rule is worthless and should not be built.
2. **Does N predict realised yield?** Correlate novelty distance at enqueue against findings-kept at completion,
   over a few hundred existing items. If the correlation is weak, tier T3 is decoration and the tiering collapses
   to four tiers — which is fine, but should be known before the code is written, not after.
3. **What fraction of items are high-D?** The steal-up rule only matters if a meaningful share of blocked work is
   safe for weaker compute.
4. **Actual local concurrency and per-call latency on the M3 Max**, including true-local embeddings (R9). "Local
   is free" is a cost statement, not a throughput statement, and the throughput number is what decides how much
   of the tail the local pool can realistically absorb.

## 10. A staged ladder (each rung shippable alone)

| rung | what lands | why it is first |
|---|---|---|
| **S1** | pool buckets replace lanes in *admission* (lanes stay as labels) | fixes the clog structurally; smallest change |
| **S2** | tiers as readable admission predicates; the two claim queries | the outside-in shape itself |
| **S3** | attention promotion (extends today's `bumped_at`) | the biggest felt-speed win |
| **S4** | realised-yield recording, then the bandit | needs S2's tiers to have something to update |
| **S5** | steal-down-to-batch | the cost win; needs measurement 1 to justify it |
| **S6** | stopping conditions + "the two ends met" in the UI | needs S4's yield signal to be trustworthy |

## 11. Risks

- **Thrash.** Rules 3/4 oscillating. Mitigated by hysteresis (§6.5); must be observable in the perf ledger.
- **Tail starvation.** Mitigated by aging (§6.2) — and aging promotes to the *cheap* pool, so it is safe to be
  generous with it.
- **Double work.** Two pools racing the same item. Already prevented by leases plus the idempotency keys that
  exist (`extraction_hash`, the per-window custom ids, `dedupe_key`).
- **Quality drift.** The steal-up rule is the only place quality can silently degrade. The D floor plus the
  visible "waiting for API-quality analysis" count are the whole defence, and they are not optional.
- **Explainability decay.** Every rule added is a rule the user must be able to read off the queue. If a tier
  cannot be named in five words, it does not belong.
