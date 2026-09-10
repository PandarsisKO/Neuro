# S0 — admission: the idea three fires on 2026-09-09 were all missing

Design only. No code. Written for a session Kyle is awake for, because it touches `db.claim_job` — the hottest
surface in the app and the one processing his sources while he sleeps.

## The through-line

Three separate emergencies that day turned out to be one missing idea:

1. a paid claims pass re-queued itself every ~5 minutes, all day (32% of a month's spend);
2. $5 of credit gone in ten minutes, with no rate limit anywhere;
3. a brand-new project starved behind an old project's backlog.

Every fix was either about **order** (lanes, `bumped_at`, pause flags) or about **politeness** (`jobs.Yield`). Both
keep failing for structural reasons:

- **A lane decides who is claimed NEXT, not who is EVICTED.** Once a job holds a worker, no lane can take it back.
  That is why `extract_claims` blocked findings three separate times and I got the layer wrong twice before Kyle
  said it a third time.
- **Politeness must be remembered per job.** `Yield` works, but it is voluntary and stateless: each job has to be
  taught to be polite, and a job that forgets — `suggest_findings` on a book, still — silently reintroduces the
  problem.
- **A pause that exempts the biggest spender is worse than no pause.** "Pause background" skipped `slow`/`low` while
  the expensive fast claims pass ran on `priority`. Two controls shipped the same day, never checked against each
  other.

The word for what is absent is **admission**: a decision, taken before a job is claimed, about whether the system
can afford to run it *right now* — in money, in worker slots, and in fairness to other projects.

## What admission would be

Not another lane. Lanes are a priority ORDER; admission is a *budget of concurrency*, checked at claim time:

- **Buckets, not lanes.** Each bucket has a maximum number of simultaneously running jobs. `ai_paid`, `ai_local`,
  `ingest`, `cheap`. A bucket at its ceiling admits nothing, whatever its lane says. This is what stops one kind of
  work from consuming all three AI workers, which is the eviction problem restated as an admission problem —
  solvable, where eviction is not.
- **Per-project fairness inside a bucket.** A share, not a queue position: no project may hold more than N of a
  bucket's slots while another project has queued work of the same kind. That is the new-project-starvation fire,
  fixed structurally instead of by Kyle pressing "Start next".
- **Money as an admission test, not a post-hoc alarm.** `usage.SPEND_RATE_CEILING` already exists but is checked
  *after* spend lands. As an admission rule it becomes: this bucket may not admit paid work if the projected
  hourly rate would exceed the ceiling. Same number, moved one step earlier, and it removes the need for a rate
  gate to be released by hand.
- **Politeness becomes structural.** With bucket ceilings, a long job holding a slot is bounded by definition;
  `Yield` stays as an optimisation rather than the only defence.

## Why this is not tonight's work

`claim_job` is the single query every worker runs, and its current shape already carries two admission filters
bolted on (background pause, rate gate) as SQL fragments. Getting this right means restructuring that query and its
tests, with Kyle's live queue running. A bug there does not degrade gracefully: it either stops all work or admits
everything. The rule for tonight was "no changes to the claim path", and this is the reason the rule exists.

## Suggested first slice, when there is a person watching

`S1`: buckets with ceilings only — no fairness, no money test. `db.BUCKETS = {kind: (bucket, ceiling)}`, one extra
`AND` in `claim_job` counting running jobs per bucket, and the existing `BACKGROUND_LANES`/`RATE_HELD_POLICIES`
fragments rewritten as bucket rules so there is one mechanism instead of three. Exit test: `extract_claims` cannot
occupy more than one of three AI slots, proven with a fixture rather than argued.

`S2`: per-project share inside a bucket. `S3`: the projected-rate admission test replacing the post-hoc gate.

## One honest caveat

Admission ceilings will make the queue *look* slower on a single-project day, because work that used to grab all
three slots now takes one. That is the intended behaviour and it will still feel wrong the first time. Whoever
ships S1 should show Kyle the before/after on a two-project workload, not a one-project one, or the rung will look
like a regression.
