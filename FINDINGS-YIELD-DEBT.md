# D1 — why `suggest_findings` still does not yield, and what it would actually take

Investigated 2026-09-10 overnight. **Deliberately not shipped.** This is the write-up the throttle rule asks for
when a rung does not fit safely.

## The debt

`claims.extract` and `relevance.rank_collection` both learned to hand their worker back mid-job (`jobs.Yield`) on
2026-09-09. `findings.suggest_for_source` did not, so a book-length source holds one of three AI worker slots for
every one of its windows — up to 20+ sequential model calls — while findings for every other source wait.

## Why the same fix does not work here

`Yield` is only safe when durable progress is already written, which is exactly why ranking needed its persistence
moved *inside* the batch loop first. Findings cannot do that today:

- `suggest_for_source` accumulates `results` in memory and calls `materialize()` once at the end;
- `materialize` is all-or-nothing per source: one `project_source_analysis` row, plus the cap applied ACROSS all
  windows (`select_findings` needs every window's candidates to choose the top N and put the rest in `reserve`).

So yielding after window 8 of 20 would either discard eight paid model calls, or write a partial analysis with a cap
computed from a third of the evidence — silently wrong findings, which is worse than a slow queue.

## The three real options

1. **Stage raw window results, then yield.** Additive table (`finding_windows`: source, window index, input hash,
   raw JSON), resume by reloading completed windows. Correct, and the cap still sees everything. Cost: a new table
   on the findings hot path, and resume logic that must be idempotent against `input_hash` — the kind of change that
   wants a person watching it land.
2. **Send long sources down the batch path.** `findings.batch_requests` already exists and the whole `batches`
   machinery was built for background findings — a provider batch holds no worker at all and costs 50% less. This is
   arguably the *designed* answer and needs no new table. It changes latency for books from minutes to hours, so it
   is a product decision for Kyle, not an implementation choice for me.
3. **Cap windows per run and mark the source partially read.** Cheapest, and wrong: it makes "read" mean two
   different things and D3's `under_read` flag already occupies that concept.

## Recommendation

Ask Kyle option 1 vs option 2 before writing anything. If he wants books read overnight anyway, option 2 is free
speed for everyone else and costs him nothing he cares about. If he wants a book's findings while he waits, option 1
is the one, and it should ship with a person watching the first book go through.

Not urgent in the way it looks: 0.58.1 raised the cap, so a long source now *keeps* more of what it reads, which
makes each of those slot-hours more valuable rather than less. The queue cost is unchanged either way.
