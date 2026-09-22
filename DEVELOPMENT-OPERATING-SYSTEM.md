# NEURO SEARCH DEVELOPMENT OPERATING SYSTEM

> **Override recorded 2026-09-21 (repo audit):** §1's program list (Speed/QA, then Transcript Intelligence; Research/Discover expansion parked) was superseded on 2026-09-14 when Kyle adopted `PRODUCT-INTELLIGENCE-MISSION.md` as the active program; the Continuous Research and Discovery-relevance work of 09-15→09-21 is that program, not a violation of §1. Everything else in this file stands.

This document governs how Neuro Search development is prioritized, interrupted, tested, resumed and delivered.

It exists to solve four connected problems:

1. Neuro Search is large enough that regressions increasingly cause the same engineering work to be repaired multiple times.
2. Performance work must improve actual throughput and responsiveness without weakening research quality.
3. New product ideas are valuable, but unrestricted context switching is reducing execution efficiency.
4. When priorities genuinely change, development must be able to stop and resume safely without architectural collisions, duplicate work or stale assumptions.

The objective is not to suppress ideas.

The objective is:

> CAPTURE IDEAS FREELY. ADMIT ENGINEERING WORK DELIBERATELY.

And:

> THE MORE WORK NEURO OR ITS DEVELOPMENT PROCESS HAS ALREADY COMPLETED SUCCESSFULLY, THE LESS OF THAT WORK SHOULD EVER NEED TO BE REPEATED.

---

# 1. CURRENT STRATEGIC PRIORITY

Until Kyle explicitly changes this priority, development is restricted to:

## FIRST

Speed

QA

Regression prevention

Hardening

Stability

Recoverability

Cost predictability

## THEN

Transcript Intelligence

## PARKED UNTIL AFTERWARD

External AI Access *(re-opened by Kyle 2026-09-22 — P11 — ACTIVE / FINAL READINESS — execution begins only after Kyle explicitly accepts the execution plan. See `PRODUCT-SCHEDULER.md` NOW.)*

Project Inbox

Multi-user / sharing

additional Bootstrap work

Research expansion

Discover expansion

Planner expansion

new source/acquisition classes

unrelated Findings redesign

cloud architecture

general infrastructure expansion

new product surfaces not required by the active program

Ideas in these areas may be discussed and recorded.

They are not automatically admitted into development.

---

# 2. SOURCE OF TRUTH

When beginning any session:

1. Find every current top-level file matching (ignore `docs/archive/**`, which is historical evidence unless a
   comparison is explicitly required):

`STATE-OF-THE-APP-YYYY-MM-DD-HHMM.md`

2. Select the newest timestamp.

3. That file governs current product status, currently known problems and current priorities.

4. The current repository code, tests and most recent passing release artifacts govern actual implementation if documentation conflicts.

5. `CLAUDE.md` governs architecture and standing engineering invariants.

6. `HANDOFF.md` governs delivery mechanics and how a development session interacts with Kyle's Mac.

7. Read only the active mission required for the work currently being performed.

8. Consult relevant HARDENING entries when touching an area with frozen measurements, rejected hypotheses or previous failures.

9. Historical missions and archived planning documents are evidence only.

Never treat an old mission document as an active work queue merely because it contains unfinished-looking checklist items.

---

# 3. CONTEXT BUDGET

Do not begin a session by reading every Markdown file.

Default context:

* newest State-of-the-App
* current CLAUDE.md
* current HANDOFF.md
* active mission or rung
* tests covering affected components
* relevant HARDENING entries found by search

Search before reading large historical documents.

Context size is an engineering resource.

Do not spend tens of thousands of tokens repeatedly reconstructing history that should already be summarized in current-state documents.

---

# 4. DOCUMENT CLEANUP

Perform one bounded cleanup before major engineering resumes.

The purpose is to eliminate contradictory planning instructions, not create a documentation project.

## Required outcome

State-of-the-App:
current status and active priorities

CLAUDE.md:
current architecture and standing rules

HANDOFF.md:
session and delivery mechanics

HARDENING.md:
measurements, regressions, failed hypotheses and reasons behind hard architectural decisions

Active mission:
requirements specific to the current active program

Archive:
finished missions and historical planning

Remove stale "current mission" declarations from old handoffs and historical documents.

Finished missions should not sit at the top level looking active.

Do not continue maintaining EXPANSION.md as a universal release diary if the current State-of-the-App considers it historical.

---

# 5. PRODUCT SCHEDULER

The product development scheduler has six states.

## NOW

Exactly one active implementation effort.

There may be multiple technical tasks required to complete it.

There may not be multiple competing active missions.

## SUSPENDED - RESUME FIRST

Work that was deliberately interrupted by a CEO override.

Normally there should be no more than one item here.

It is not ordinary backlog.

## NEXT

Maximum three admitted future priorities.

These have already passed prioritization but may not interrupt NOW.

## PARKED

Unlimited idea capture.

A parked idea is not rejected.

It has simply not earned engineering capacity yet.

## REJECTED / REVISIT ON TRIGGER

An idea or architecture that was investigated and found unjustified.

Every rejected item should have a concrete revisit trigger when practical.

Example:

"Do not revisit vector database until >250k chunks or measured vector search p50 exceeds 150 ms after caching."

## DONE

Released, tested and passed through the required gates.

---

# 6. IDEA CAPTURE IS NOT REPRIORITIZATION

When Kyle says:

"What if we..."

"I have an idea..."

"Could Neuro also..."

"Wouldn't it be cool if..."

"While we're here..."

Assume he is ideating unless he explicitly says he wants development priority changed.

Claude should:

1. engage with the idea seriously
2. understand the user problem
3. challenge unnecessary architecture
4. identify existing capabilities that already solve part of it
5. classify the idea
6. estimate its likely value
7. record it in the Product Scheduler
8. state whether it changes the active mission

Default:

ACTIVE MISSION CHANGED: NO

Do not interpret enthusiasm as authorization to abandon the active rung.

---

# 7. IDEA CLASSIFICATION

Every meaningful idea gets one primary classification.

## PAINKILLER

Fixes something causing real user pain now.

## MULTIPLIER

Makes several existing capabilities better.

## ENABLER

Unlocks strategically important future work.

## DELIGHT / COOL

Interesting, differentiated or impressive, but current utility is uncertain.

Delight ideas are not bad ideas.

They simply carry a higher burden before they displace Painkillers, Multipliers or Enablers.

---

# 8. PRIORITIZATION SCORECARD

Before moving PARKED → NEXT, evaluate:

## Benefits, 0-5 each

User value

Pain frequency

Pain severity

Foundation leverage

Mission alignment

Cost/time savings

Confidence that the problem is real

Unlock value

## Costs, 0-5 each

Engineering effort

Regression surface

Permanent complexity

Interruption cost

The score is not mathematical truth.

Its purpose is to expose the tradeoff.

A highly exciting idea that solves a rare problem, requires new infrastructure and interrupts a foundational mission should remain parked.

A boring improvement that eliminates repeated work across the entire app may belong in NOW.

---

# 9. USEFULNESS TEST

Before promoting an idea, answer:

What user problem does it solve?

What happens today without it?

How frequently does that happen?

How severe is it?

Can existing functionality solve most of it?

What measurable outcome should improve?

What is the cheapest experiment that could validate it?

What currently planned work would this delay?

If these questions cannot be answered, the idea is not ready for engineering admission.

---

# 10. INTERRUPT PRIORITIES

Only four categories may displace active work.

## P0 - INTEGRITY / SECURITY

Immediate interruption.

Examples:

data corruption

data loss

security vulnerability

credential exposure

evidence corruption

citation integrity failure

destructive behavior

## P1 - ACTIVE COST / RELIABILITY DAMAGE

Immediate or nearest safe checkpoint.

Examples:

runaway paid API spend

duplicate paid work

crash loops

local execution silently becoming paid execution

core feature unavailable

## P2 - BLOCKS ACTIVE MISSION

May enter NOW because active work cannot safely proceed without it.

Example:

R5 exposes an R4 recovery defect that makes safe concurrency impossible.

Fixing the defect is completing the mission, not scope creep.

## P3+ - EVERYTHING ELSE

Cannot interrupt an active rung without explicit CEO override.

Wait for the next admission checkpoint.

---

# 11. SAME-RUNG ABSORPTION RULE

A new request may be absorbed into the current rung without formal reprioritization only if ALL are true:

* it touches the same subsystem already being changed
* it directly improves the stated rung objective
* it does not expand architectural scope
* it does not create an independent user-facing feature
* regression surface is small
* it does not materially extend release duration

Otherwise:

PARK IT.

"Only 30 lines" is not enough justification.

---

# 12. ADMISSION CHECKPOINTS

Normal admission occurs at rung boundaries.

Flow:

NOW
→ finish rung
→ regression gates
→ release
→ priority checkpoint
→ evaluate NEXT and new parked ideas
→ choose highest-value eligible work
→ NOW

Do not continuously reprioritize development between checkpoints.

---

# 13. CEO OVERRIDE

Kyle retains explicit authority to override current priorities.

Claude must not block or argue with an override.

Claude must make the consequences visible and execute the change safely.

Before switching, report:

CURRENT
<mission/rung>

PROPOSED OVERRIDE <new work>

INTERRUPTION SAFETY
Safe / Stabilize First / Unsafe Right Now

COLLISION
Green / Yellow / Red

INTERRUPTION COST
Low / Medium / High

RECOMMENDED SWITCH POINT <nearest safe checkpoint>

Kyle may still choose to proceed.

---

# 14. SAFE INTERRUPTION LEVELS

## SAFE

Work is committed or isolated.

Current release remains functional.

Tests are meaningful.

No migration or interface replacement is halfway complete.

Override may proceed.

## STABILIZE FIRST

Current changes need a small amount of work to reach a coherent checkpoint.

Examples:

finish an atomic refactor

restore passing affected tests

commit incomplete work behind an unused path

finish defining an additive migration

save benchmark results

Reach that checkpoint, then switch.

## UNSAFE RIGHT NOW

Repository state cannot be meaningfully resumed.

Examples:

schema transition halfway complete

old interface removed but replacement incomplete

state ownership ambiguous

rollback/current behavior cannot be distinguished

Reach the nearest safe checkpoint unless the override itself is an emergency response to that condition.

---

# 15. SUSPENSION SNAPSHOT

Before an override becomes NOW, record a compact suspension snapshot.

## Identity

Active program

Mission

Rung

Version

Commit

Date

Reason for override

## Completed work

Implemented work

Released work

Measurements

Decisions

Passing gates

## Remaining work

Exact unfinished items

Next intended step

Required tests

Unresolved hypotheses

Known blockers

## Active assumptions

Explicitly record assumptions the incomplete work depends on.

Examples:

provider routing behavior

job ownership

endpoint contracts

table ownership

cancellation semantics

work-unit behavior

schema shape

## Touched surfaces

Modules

Functions

Tables

Endpoints

Jobs

Providers

Contracts

UI surfaces

Tests

## Fragile boundaries

Anything likely to collide with new work.

## Resume checkpoint

Exact safest next step if nothing relevant changes.

A fresh Claude session should be able to understand how to resume from this snapshot.

---

# 16. COLLISION ANALYSIS

Before implementing the override, compare it to suspended work.

## GREEN

Independent.

No meaningful shared architecture.

## YELLOW

Touches shared interfaces or primitives.

Reintegration tests required.

## RED

Changes assumptions or architecture suspended work depends on.

Examples:

schema ownership

provider routing

jobs

contracts

retrieval

API shapes

storage model

concurrency model

Do not blindly resume the old suspended plan after a RED collision.

For every Yellow/Red overlap record:

shared component

old assumption

override change

likely consequence

required reintegration test

---

# 17. OVERRIDE WORK STILL USES NORMAL ENGINEERING DISCIPLINE

CEO override does NOT bypass:

reuse mapping

regression tests

provider/cost controls

schema discipline

affected invariant gates

release gate

documentation

measurements where appropriate

A priority change is not authorization for a lower-quality release.

---

# 18. REINTEGRATION REVIEW

When override work completes, DO NOT immediately continue the old checklist.

Compare:

SUSPENSION SNAPSHOT

against:

CURRENT CODEBASE

For each relevant assumption or boundary classify the override's impact.

## BENEFITED

Override solved or simplified something suspended work needed.

Action:

reuse it

delete obsolete planned work

shorten remaining ladder

## NEUTRAL

No material interaction.

Action:

verify intersection and resume.

## HINDERED

Goal remains valid but implementation is harder.

Action:

adjust plan before continuing.

## INVALIDATED

Previous design assumption is no longer true.

Action:

re-plan that portion from the current architecture.

Do not mechanically continue the old checklist.

## CREATED NEW RISK

Override introduced a failure mode relevant to suspended work.

Action:

add regression protection before continuing into that surface.

---

# 19. MANDATORY RESUME QUESTION

Before resuming ANY suspended effort, explicitly answer:

"What did the interrupting work change that BENEFITS, HINDERS, INVALIDATES, or ADDS RISK to the work we are about to resume?"

If the answer appears to be "nothing," verify that against the recorded touched surfaces.

This question may not be skipped.

---

# 20. RESUME DELTA

Create a short Resume Delta:

What changed?

What old work is now unnecessary?

What became easier?

What became harder?

What assumptions became false?

What new tests are needed?

Did the rung objective itself change?

Where is the new safest restart point?

Rebase remaining work against current architecture.

Do not restart completed work.

---

# 21. INTERSECTION TESTS

Before resuming:

run suspended mission's affected gates

run override's affected gates

run tests covering shared components

run any newly required regression tests

If clean:

resume development.

Full suite still occurs at normal rung release boundary.

---

# 22. NESTED OVERRIDES

Avoid override chains.

Normal limit:

NOW

plus

SUSPENDED - RESUME FIRST

If another override occurs, Claude must show that interruption cost has increased.

Do not allow a stack of abandoned half-missions.

New feature ideas discovered during override work go to PARKED unless P0/P1/P2 or Kyle explicitly overrides again.

---

# 23. CURRENT FOUNDATION ROADMAP

The active strategic roadmap is:

PHASE 0
Context/document hygiene

PHASE 1
Stabilize measurement environment

PHASE 2
Systemic regression gates

PHASE 3
Speed R8

PHASE 4
Speed R9

PHASE 5
Speed R4

PHASE 6
R4 recovery gate

PHASE 7
Speed R5

PHASE 8
R5 concurrency regression gate

PHASE 9
Speed R6, then Speed R7

PHASE 10
Foundation Hardening Closeout

PHASE 11+
Transcript Intelligence

Everything else remains parked unless admitted under this scheduler.

---

# 24. PHASE 0 - CONTEXT / DOCUMENT HYGIENE

Perform once.

Archive finished mission files.

Make newest State-of-the-App authoritative for current status.

Reduce contradictory current-mission declarations.

Refactor CLAUDE.md toward current architecture and rules, not historical release narrative.

HANDOFF remains delivery mechanics.

HARDENING remains measurements and reasoning.

Do not turn documentation cleanup into prolonged work.

---

# 25. PHASE 1 - STABILIZE MEASUREMENT ENVIRONMENT

Before risky speed changes:

1. Diagnose and fix flaky test / suspected worker leak.

2. Diagnose Claude Code timeout behavior.

3. Diagnose unexpected paid API fallback.

4. Make execution transport and cost changes explicit.

5. Fix stale browser UI/server mismatch detection.

6. Complete bounded interaction-feedback gaps if directly related to current responsiveness work.

Record root causes.

Record disproven hypotheses.

---

# 26. PHASE 2 - SYSTEMIC REGRESSION GATES

Add compact cross-cutting gates.

## Worker lifecycle

No leaked workers.

Clean shutdown.

Correct DB ownership.

Predictable leases/heartbeats.

## Recovery

Expired leases.

Killed workers.

Abandoned invocations.

Unknown provider outcome.

Process restart.

All converge without duplicate work.

## Routing/cost

Requested model.

Actual model.

Transport.

Fallback legality.

Timeout.

Usage attribution.

No silent local → paid transition.

## Request-path purity

Cheap endpoints cannot accidentally:

call models

trigger corpus-wide analysis

run hidden refreshes

perform expensive rebuilds

## Frontend integrity

Detect:

duplicate functions

duplicate IDs

missing handlers

obsolete handler references

unacknowledged controls where acknowledgement is required

## Client/server version compatibility

Old UI against new server must refresh/refuse visibly.

---

# 27. PHASE 3 - SPEED R8

Execute current R8.

Includes current documented hygiene work such as:

stuck-row/invocation reaper

ANALYZE/statistics

WAL/checkpoint policy

retention

SQLite pragmas

targeted indexes

Do not replace SQLite.

Measure before and after.

Establish fresh baseline afterward.

---

# 28. PHASE 4 - SPEED R9

Benchmark local models on actual M3 Max.

Especially resolve embedding strategy before Transcript Intelligence T1.

Every candidate receives:

ADOPT

REJECT

or

RETEST AT <numeric trigger>

Negative conclusions are valid deliverables.

Do not repeatedly reopen rejected technology without the trigger.

---

# 29. PHASE 5 - SPEED R4

Implement durable, content-addressed work units.

Invariant:

COMPLETED WORK SURVIVES AN INCOMPLETE PARENT.

Example:

10 windows

9 complete

1 missing

Parent remains incomplete.

Retry executes only missing work.

Completed compatible results must not be:

lost

recomputed

repurchased

misrepresented as a fully completed source

This architecture should support Findings, Claims, batches and future Transcript Intelligence.

Hash/version all inputs needed to prevent incompatible units materializing as current.

---

# 30. PHASE 6 - R4 ABUSE GATE

Test:

1/10 completed then interrupt

9/10 completed then interrupt

duplicate request

cancel

provider timeout

local provider failure

partial external batch

process death

restart

source revision mid-run

brief/project revision mid-run

explicit user cancellation

Prove:

completed compatible work survives

stale work cannot become current

incomplete parent stays incomplete

no duplicate artifacts

no repeated paid units

no silently lost completed result

Do not start R5 until these pass.

---

# 31. PHASE 7 - SPEED R5

Implement bounded concurrency over durable work units.

Preserve:

job identity

unit identity

usage attribution

invocation attribution

provider policy

model identity

cancellation

leases

heartbeats

retries

circuit breakers

account gates

budget guards

spend-rate controls

deterministic materialization

Bound independently:

local execution

paid API

external batch

local deterministic compute where relevant

Never use uncontrolled fanout.

Never allow provider failure to produce a fallback stampede.

---

# 32. PHASE 8 - R5 CONCURRENCY GATE

Test:

## Duplicate request

Exactly one computation.

## Parent cancellation

Completed units survive.

Unstarted units remain unstarted.

Running units stop at documented safe boundaries.

## Provider failure during fanout

No uncontrolled paid fallback.

## Spend ceiling

Concurrency cannot race around cost controls.

## Crash

7 of 12 complete.

Restart executes exactly 5.

## Input mutation

Old results may remain historical.

They cannot materialize as current.

## Completion ordering

Parallel completion order cannot change deterministic final output.

---

# 33. PHASE 9 - SPEED R6, THEN SPEED R7

R6 is the fast-first-wave rung defined in SPEED-MISSION.md. It was omitted from an earlier Foundation summary even
though R7 depends on it. Execute it after R5 and its concurrency gate, as its own measured release:

- deterministically select a small, diverse, high-value first wave
- keep the remaining work eligible and visibly deepening
- permit promotion without restarting completed compatible work
- prove that early results are provisional and later contradictory evidence wins

Do not admit R7 until R6 passes its quality gates. Grouping both rungs in Foundation Phase 9 preserves the existing
phase numbering; it does not authorize combining their implementations or evidence.

Then execute R7:

Use accumulated knowledge to avoid repeatedly spending equal cognition on already represented material.

Rule:

REDUNDANCY MAY CHANGE PRIORITY.

REDUNDANCY MAY CHANGE DEPTH.

REDUNDANCY MAY NOT REMOVE ELIGIBILITY.

Identify:

represented

redundant

novel

uncertain

Concentrate expensive analysis on novel/uncertain residual material while preserving access to all source content.

Novelty must be corpus/project-relative.

Not arrival-order-relative.

Validate quality before declaring speed improvement successful.

---

# 34. PHASE 10 - FOUNDATION HARDENING CLOSEOUT

Before Transcript Intelligence, produce one formal Foundation Performance + Stability report.

## Correctness

full pytest

Tier 1

release-check

database integrity

frozen quote/citation/retrieval gates

no unexplained stuck jobs

no unexplained stuck invocations

## Recovery

leases

interruptions

partial batches

provider failure

restart

## Cost

duplicate-work rate

unknown-cost invocations

local → paid fallback count

completed work discarded

cost per useful unit where available

## Performance

API/page p50/p90

chat time-to-first-output

queue waits

findings processing

claims processing

retry recomputation

durable-unit reuse

parallel utilization

query embedding latency

large payloads/request counts

## UI

client/server compatibility

handler integrity

runtime/console errors

interaction acknowledgement

Closeout question:

DID NEURO BECOME FASTER WITHOUT BECOMING LESS TRUSTWORTHY?

If that cannot be demonstrated, foundation work is not complete.

---

# 35. TRANSCRIPT INTELLIGENCE T1

Transcript Intelligence is the first major product mission after Foundation closes.

T1 uses one embedding space for both existing transcript chunks and newly embedded derived objects. The first T1
measurement stays in the current production `text-embedding-3-small` space because every chunk is already embedded there
and T1 must compare chunks with Claims and Findings. R9's selected local `bge-m3` is evidence for a later, separately
gated full-space migration; it must not be mixed with the existing 1536-dimensional chunk vectors or silently substituted
inside T1.

Embed canonical active derived knowledge with embedding model/version metadata.

First deliverable:

MEASUREMENT.

Measure transcript representation against:

active Claims

applicable Findings

claim evidence locators

finding locators

redundancy

relevance where applicable

Publish distributions.

Compare semantic coverage with locator coverage.

Current checkpoint (2026-09-12): R9(c) is explicitly deferred with the numeric trigger in
`docs/PRE-T1-GATE-AUDIT-2026-09-12.md`. T1's first schema slice is implemented: derived-vector metadata, canonical
fail-open helpers, a low-lane durable backfill job, and a read-only coverage scaffold are present and covered by
`tests/test_t1_vector_metadata.py`. Corpus-space attestation is now verified on the supported app path; the scaffold
reports `ready_for_measurement`, while semantic output remains pending until versioned derived vectors exist.

Do not define "unexplained" as simply "has no claim evidence."

Do not choose universal cosine thresholds by intuition if project-relative distributions are available.

---

# 36. TRANSCRIPT INTELLIGENCE T2

Build the seven-state coverage model.

States:

extracted

represented

finding_covered

claim_covered

redundant

irrelevant

unexplained

Derived state first.

Persist only when demonstrated query/performance requirements justify storage.

Every stored pass marker must be versioned and idempotent.

---

# 37. TRANSCRIPT INTELLIGENCE T3

Implement deterministic Tier-0 extraction before spending model cognition.

Potential extraction:

numbers

units

currency

percentages

dates

durations

URLs

DOI / ISBN / identifiers

people

companies

products/tools

questions

procedural language

warnings

exceptions

comparatives

hedges

Create the missing pre-Claim intermediate layer.

Prototype storage conservatively.

Do not prematurely build a huge Evidence Atom architecture.

Normalize once real queries require it.

Version every extractor independently.

---

# 38. TRANSCRIPT INTELLIGENCE T4

Build the Batch Research Executor by reusing R4/R5.

Separate:

SELECTOR
what deserves cognition

from:

EXECUTOR
where cognition runs

Selector may prioritize:

genuinely unexplained passages

novel clusters

weak Claims

stale Claims

open research targets/questions

Tier-0 high-value passages

Executor may use:

Claude Code

validated local model

paid API

provider batch

future supported execution path

Claude Code is an execution backend, not architecture.

Outputs remain structured/proposed research state.

AI interpretation cannot self-promote into evidence.

---

# 39. LATER TRANSCRIPT INTELLIGENCE

Do not automatically implement every remaining mission rung.

Before each rung ask:

WHAT MEASURED PROBLEM DOES THIS SOLVE NOW?

If the previous rungs do not demonstrate the need:

stop

measure

report

do not add architecture.

---

# 40. TEST EXECUTION POLICY

Do not run the entire test suite after every edit.

## Development loop

affected module tests

cross-cutting invariant gates for touched systems

## Rung release gate

new regression tests

affected subsystem gates

full pytest

Tier 1

release-check

version agreement

current HANDOFF delivery ritual

## Live testing

Only where deterministic testing cannot establish:

provider behavior

M3 Max performance

real corpus performance

browser behavior

ranking/retrieval quality

Never open the live SQLite database externally, including read-only.

Use:

running app API

supported local CLI

copied verified backup in session workspace

---

# 41. REGRESSION PHILOSOPHY

Every bug must trigger this question:

WHAT SYSTEM INVARIANT WOULD HAVE PREVENTED THIS ENTIRE CLASS OF BUG?

Examples:

Duplicate function kills button
→ detect duplicate handler declarations.

Paid windows repeated after restart
→ durable work-unit invariant.

Unexpected API fallback
→ routing/cost invariant.

Expensive research computation appears inside simple GET
→ request-path purity invariant.

Worker leaks between tests
→ worker lifecycle invariant.

Concurrency duplicates cost
→ atomic work-unit ownership.

Prefer one systemic gate over many narrow regressions.

---

# 42. REUSE MAP BEFORE BUILDING

Before every rung create a compact reuse map:

Existing modules

Existing helpers/functions

Existing tables/columns

Existing jobs

Existing retries/dedupe

Existing providers/routing

Existing caches

Existing endpoints

Existing tests

What genuinely does not exist

Do not introduce:

new table

new queue

new provider abstraction

new fetch path

new ingestion architecture

new cache service

new retrieval engine

new concurrency framework

unless the reuse map proves current primitives cannot carry the requirement.

---

# 43. MEASURE BEFORE ARCHITECTURE

Performance, retrieval, ranking, model selection, scheduler and infrastructure changes require measurements.

Record:

before

after

corpus/fixture

latency

cost

quality

reliability

hypothesis

result

If a hypothesis fails, record that failure.

A disproven idea is useful project knowledge.

Do not spend future sessions rediscovering it.

---

# 44. RELEASE SIZE

Prefer one coherent behavioral change per rung/release.

Avoid combining:

unrelated refactor

schema migration unrelated to objective

new feature plus broad cleanup

performance change plus research-semantic change

A small well-gated release is preferable to a large release whose tests cannot identify which change caused a regression.

---

# 45. DOCUMENTATION RESPONSIBILITY

## State-of-the-App

Current product truth.

Current active priority.

Known current problems.

## CLAUDE.md

Architecture.

Standing invariants.

Current module ownership.

## HANDOFF.md

Safe session workflow.

Delivery mechanics.

## HARDENING.md

Measurements.

Failed hypotheses.

Frozen decisions.

Regression classes.

Why important architectural decisions exist.

## Product Scheduler

NOW

SUSPENDED

NEXT

PARKED

REJECTED / TRIGGER

DONE

## Active mission

Only the requirements and status needed while that mission is actually active.

Do not make every document a parallel roadmap.

---

# 46. PRODUCT SCHEDULER IDEA RECORD

Each meaningful parked idea may contain:

TITLE

DATE

PROBLEM

CLASSIFICATION
Painkiller / Multiplier / Enabler / Delight

EXPECTED VALUE

EVIDENCE

DEPENDENCIES

LIKELY COMPLEXITY

REGRESSION SURFACE

CURRENT SCORE

REVISIT TRIGGER

STATUS

Do not require exhaustive documentation for every passing thought.

Record enough that the idea does not need to be rediscovered later.

---

# 47. PRIORITY CHECKPOINT FORMAT

At each rung boundary report:

COMPLETED

MEASURED RESULT

REGRESSIONS / DEBT CREATED

CURRENT FOUNDATION STATUS

NEXT PLANNED RUNG

NEW HIGH-VALUE IDEAS SINCE LAST CHECKPOINT

DO ANY OF THEM OUTRANK THE PLANNED NEXT RUNG?

Recommendation:

CONTINUE PLAN

or

REPRIORITIZE

Kyle decides.

---

# 48. CORE DEVELOPMENT PRINCIPLES

1. One active implementation mission.

2. Ideas are cheap to capture and expensive to admit.

3. Completed work should survive interruption.

4. The current codebase, not an old plan, governs resumed work.

5. Overrides are allowed but must be safely suspended and reintegrated.

6. New work must reuse current architecture before adding parallel systems.

7. Speed does not justify lost evidence or weakened research quality.

8. Regression gates should prevent failure classes, not merely replay previous bugs.

9. Measurements can reject ideas.

10. Negative results are valuable.

11. Cool is not the same as useful.

12. User pain, foundational leverage and compounding value outrank novelty.

13. Rung boundaries are the normal product admission points.

14. P0/P1/P2 are legitimate interrupts.

15. CEO override always remains possible.

16. An override cannot permanently fracture architecture.

17. Resume means rebase remaining work against current reality.

18. The more Neuro already knows and the more engineering has already completed, the less cognition and labor should ever have to be repeated.

---

# 49. CURRENT DEFINITION OF SUCCESS

The Foundation program succeeds when Neuro Search is measurably:

FASTER

MORE RESPONSIVE

MORE RECOVERABLE

LESS LIKELY TO REPEAT WORK

LESS LIKELY TO SPEND MONEY UNEXPECTEDLY

HARDER TO REGRESS

EASIER TO DIAGNOSE

SAFE TO PARALLELIZE

AND NO LESS TRUSTWORTHY

Only then does Transcript Intelligence become the active major product program.

Transcript Intelligence succeeds when Neuro increasingly understands:

WHAT IT HAS ALREADY EXTRACTED

WHAT IS ALREADY REPRESENTED

WHAT IS ACTUALLY NOVEL

WHAT HAS NEVER BEEN MEANINGFULLY EXAMINED

AND WHERE ADDITIONAL COGNITION HAS THE HIGHEST EXPECTED VALUE

That combination is the strategic direction:

A research system that becomes faster and smarter because of everything it has already done.
