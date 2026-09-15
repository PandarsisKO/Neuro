# AD0 — Feedback signal inventory (2026-09-15)

PARALLEL PREP for P9.2 Adaptive Discovery. Written matrix only — no code, no schema change, no new table, **no
telemetry**. Every signal below is a durable state column that already exists, already reflects a real user or
system decision, and is already read on demand from the table that owns it. AD0's job is to inventory these and
decide which feed AD2 (deterministic rerank); it does not build AD1/AD2/AD3/AD4 themselves.

## The five durable signals

| # | Signal | Table.column | Values | What it actually means |
|---|---|---|---|---|
| 1 | Candidate disposition | `candidate_projects.state` | `available · skipped_low_relevance · skipped_limit · skipped_cost · user_dismissed · duplicate · acquired` | The most direct verdict there is: did the project keep or reject THIS item when it was presented as a candidate. Set by `candidates.mark()` / `mark_by_source()`. |
| 2 | Link outcome | `candidate_links.state` | `open · satisfied · dismissed` | Whether a candidate linked to a specific research need (`evidence_target \| claim \| tension \| mission \| discovery`) turned out to close that need, or was explicitly told "not important" by the user. Narrower than #1 — scoped to one need, not the item's general appeal. |
| 3 | Finding status | `project_notes.status` | `approved · suggested · reserve · dismissed` | Once a candidate is acquired and read, whether the passages it produced were accepted, held back, or thrown out. First quality signal downstream of acquisition — arrives after ingest + findings extraction, not at selection time. |
| 4 | Claim status | `project_claims.status` (`claims.set_status`) | `proposed · accepted · rejected · superseded` | Whether a finding that survived to become a tracked proposition is something the project actually believes. One step further downstream than #3; the user's real verdict, never written by the model. |
| 5 | Target closure | `project_evidence_targets.status` | `open · satisfied · closed_by_user` | Whether the original research gap that justified acquiring a source got closed by evidence (`satisfied`) or by the user deciding they don't need it (`closed_by_user` — a rejection of the GAP, not of any one candidate). |

Read together, these five track one candidate's entire life: chosen or rejected (#1) → linked to what it was
for (#2) → what it yielded (#3) → whether that yield stuck as belief (#4) → whether the gap it was chosen for
is actually closed (#5). No two of them measure the same thing, and none of them requires a new column,
event log, or background job — each is written by an action the product already takes (`mark`, `link`,
harvest, `set_status`, target satisfaction) and read straight off its own table at decision time.

## Decision: which signals feed AD2

**AD2's rerank loop uses #1 (candidate disposition) as its primary input, and #2 (link outcome) as a secondary
routing weight — both already available at the moment AD1 needs to rank the next five.** Reasoning:

- AD1's loop is tight — rank, present, user keeps/rejects, rank again — so its feedback has to be available
  the instant the user acts. #1 is written synchronously by the same `mark` call the keep/reject UI already
  calls; nothing else on this list updates that fast. A creator whose items the project has been rejecting
  (`skipped_low_relevance`, `user_dismissed`) should rank lower next round; one whose items keep getting
  acquired should rank higher — the same "absence is never evidence, presence is" discipline SC0b's
  `creator_yield` already applies.
- #2 is already read by `where_to_look`/`creator_yield` this session (SC0b's `targets_helped`) as a per-need
  routing signal. It belongs in AD2 as a secondary term (an item linked to an already-`satisfied` need for this
  project is less useful to re-rank toward), not the primary keep/reject signal, since a link can be satisfied
  by any acquisition path, not only ones AD1 itself presented.
- #3 and #4 are real quality signals but arrive on the harvest pipeline's own schedule (minutes to a night
  later, after ingest + findings + claims), not at click time — feeding them into AD2 would make the rerank
  loop wait on async work it has no business waiting on. They are reserved for **AD4** (static vs. adaptive
  measurement: capture rate, yield, targets closed) where a slower, retrospective signal is exactly right.
- #5 changes slower still — a target closes once, not every round — and is likewise an AD4 measurement, not
  an AD2 input.

## What AD0 explicitly does not do

No new table, column, or event log. No signal here is invented — all five are read from state the product
already durably records for other reasons (review UI, harvest, user verdicts, gap tracking). AD1/AD2/AD3/AD4
are separate, later rungs; this document only decides which existing signal answers which later question.
