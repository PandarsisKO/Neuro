# NEURO PRODUCT INTELLIGENCE MISSION

> Adopted 2026-09-14. Two parts: the mission as written by Kyle, verbatim, then the CTO rulings and admission
> amendments of the same day, verbatim. **Where the rulings conflict with the mission text, the rulings win.**
> Claude's ten adoption challenges (E5 staleness, P0 as audit-not-build, P0.5 → P4, P1 collision with the
> frontend split, host sleep, Decision Impact signals, Morning Report v1 honesty, CLAUDE.md in the pre-read,
> DB preflight, T4 ownership) are each answered in the rulings; they are not reproduced separately.
> Pre-read order for any rung is rulings §8. Admission into the work queue is recorded in PRODUCT-SCHEDULER.md.

---

## Part 1 — The mission (Kyle, 2026-09-14)

Status

Product direction and execution ladder.

This document defines the next product phase for Neuro Search.

It is not blanket authorization to implement every idea listed here.

Current code, the newest STATE-OF-THE-APP-*, HANDOFF.md, PRODUCT-SCHEDULER.md, DEVELOPMENT-OPERATING-SYSTEM.md, and active mission admission gates outrank stale planning documents.

Before starting any rung:

1. Read the newest State of the App.
2. Read the tail of HANDOFF.md.
3. Read PRODUCT-SCHEDULER.md.
4. Check recent commits and active ownership.
5. Verify the capability is actually missing.
6. Do not duplicate a capability merely because an older planning document says it is missing.

### 1. Mission

Neuro should become a persistent research and planning partner, not a database full of AI-generated research artifacts.

The intended user loop is:

Tell Neuro what I am trying to accomplish
→ Neuro remembers what matters
→ understands what is known, uncertain, stale, contradictory, or missing
→ decides what research is worth doing
→ performs bounded work using the appropriate cost/latency path
→ reconciles new evidence against existing knowledge
→ identifies what materially changed
→ updates proposed research state
→ improves the plan
→ asks the user only for judgments that actually require a human.

The user should not need to understand T1, T2, T3, T4, Claims extraction, stale-state machinery, provider routing, work units, assumption registries, batch APIs, embeddings, or schedulers.

Those are internal mechanisms.

The product should expose:

* what changed,
* why it matters,
* what Neuro recommends,
* what needs the user's judgment,
* and what Neuro can safely handle itself.

### 2. Product North Star

A successful Neuro session should increasingly feel like:

Neuro already understood the project, did the obvious research, noticed what changed, and brought me the three things I actually needed to think about.

Not:

Neuro generated 900 findings and gave me another queue to process.

The scarce resource is no longer information.

The scarce resource is human attention.

Neuro must therefore optimize for:

decision-relevant understanding per unit of user attention.

### 3. Core Product Principles

#### 3.1 Evidence is not truth

Maintain hard boundaries between:

1. source evidence,
2. extracted observations/findings,
3. proposed interpretations,
4. accepted Claims,
5. user decisions and constraints,
6. Planner conclusions,
7. actions.

Autonomous research may create evidence and proposed state.

It must not silently turn controversial interpretation into accepted truth.

claims.set_status or its governed successor remains the promotion boundary unless a separately admitted mission changes that rule.

#### 3.2 Consequence matters more than volume

Do not prioritize work because it creates many findings.

Prioritize based on whether new information could change:

* a decision,
* an assumption,
* a risk,
* an Evidence Target,
* a dependency,
* a plan step,
* a deadline,
* or the user's understanding of the problem.

#### 3.3 Hide machinery, not control

The UI should progressively disclose complexity.

Users should not see instrumentation merely because it exists.

But progressive disclosure must not create five-click workflows for ordinary outcomes.

Default surface:

What changed → Why it matters → Recommended action

Operational details belong one level deeper.

#### 3.4 Autonomy must be bounded

Every autonomous system must have:

* explicit scope,
* budget,
* provenance,
* idempotency,
* cancellation behavior,
* project/brief revision awareness,
* failure visibility,
* and a clear promotion boundary.

Cheap autonomous work can create expensive knowledge pollution.

Cost safety alone is insufficient.

#### 3.5 "Nothing changed" is valuable

Continuous research must not invent novelty to justify its existence.

A successful overnight result can be:

Nothing important changed.

That outcome should increase user trust.

### 4. Current Product Reality

Treat these as orientation only and verify them against main before acting.

T4

The native T4 executor exists and has completed a real local run.

E3 demonstrated real execution against five sources using the local free path and produced findings.

E4

The intended kept-rate quality experiment remains strategically important.

Bulk approval is not equivalent to measuring whether generated findings are actually useful enough to retain.

Do not use bulk approval as evidence that the E4 quality question has been answered.

E5

Infrastructure exists for a paid Sonnet/Haiku comparison.

Do not run the experiment unless its decision would still affect a real product choice.

E6

The prefilter exists and remains off by default.

The evaluation was attempted and exposed an evaluation/environment routing problem rather than proving or disproving the filter.

The filter earns admission only through measured recall and savings.

E7

The Nightly Refinery and Morning Report remain the most important unbuilt bridge between Neuro's internal intelligence machinery and everyday user value.

T5

The real adjudication path exists and has completed a real Sonnet adjudication.

The missing question is no longer "can T5 run?"

It is:

When should Neuro invoke T5, and how should the result reach the user or research state?

T6

The assumption ledger exists.

It is primarily an internal/CLI capability.

Do not create an Assumptions dashboard merely because the data exists.

Surface assumption drift where it changes a user decision or plan.

Structured T4 deltas

The richer T4 output envisioned in the Transcript Intelligence mission remains deferred:

* candidate Claims,
* qualifications,
* contradictions,
* additional evidence,
* Evidence Targets,
* and related proposed state.

Do not implement this solely because the mission originally envisioned it.

Run the experiment defined later in this ladder.

### 5. Shared Product Concept: Decision Impact

Introduce Decision Impact as an internal product concept.

This does not initially require a new database object or visible UI.

The question is:

If this information is wrong, stale, contradicted, or changed, could something the user cares about materially change?

Decision Impact should eventually influence:

* T4 research priority,
* T5 adjudication,
* review priority,
* freshness urgency,
* monitoring frequency,
* morning-report prominence,
* Evidence Target priority,
* Discover behavior,
* and Planner warnings.

A low-confidence trivia Claim may have negligible Decision Impact.

A highly consequential financing assumption may deserve immediate attention even when model confidence is high.

Do not reduce Decision Impact to one opaque LLM confidence score.

Initial signals may include:

decision impact × disagreement × novelty × evidence weakness × irreversibility × freshness sensitivity

Start deterministic wherever possible.

### 6. The Main Product Interface: Project Delta

Create a conceptual contract called Project Delta.

Do not rush into a schema migration until the required data is understood.

A Project Delta answers:

What changed?

New evidence, changed Claim support, contradiction, resolved gap, stale assumption, changed source, new important unknown, completed research.

Why does it matter?

Which Claim, Decision, Evidence Target, risk, dependency, or plan step could be affected?

What did Neuro do?

Research performed, evidence reconciled, proposal created, source stopped, cost incurred.

What needs the user?

Ideally zero items.

Otherwise a small, prioritized judgment queue.

What should happen next?

No action, investigate, accept/reject proposal, refresh source, change decision, or update plan.

Project Delta should eventually serve:

* Morning Report,
* Research Overview,
* Chat,
* Planner,
* notifications,
* external ChatGPT/Claude access,
* and future monitoring.

Do not allow every subsystem to invent its own incompatible version of "what changed."

### 7. Execution Ladder

#### P0. Trustworthy Autonomy Foundation

Goal

Make autonomous research safe enough that Neuro can work unattended without creating invisible corruption, duplication, stale writes, runaway review burden, or false certainty.

Required work

P0.1 Revision-aware work

Every scheduled/autonomous research job must know the project and relevant brief/research-state revision it was created against.

If the governing input changes before completion:

* do not silently write as though nothing changed,
* reconcile safely,
* mark the result as based on an older revision,
* or re-evaluate before admission.

P0.2 Idempotency

Re-running identical autonomous work must not:

* duplicate spend,
* duplicate findings,
* duplicate jobs,
* duplicate evidence,
* or repeatedly change state.

Use stable work identity and input hashes.

P0.3 Hard budget envelope

Nightly/autonomous research must obey explicit user-configured limits.

Budget failure should stop or defer work cleanly.

It must never silently convert a bounded nightly task into unlimited work.

P0.4 Promotion boundary

Autonomous research may produce:

* evidence,
* findings,
* proposed state,
* tensions,
* targets,
* suggested plan changes.

It must not silently promote controversial interpretation into accepted canonical state.

P0.5 Review-at-scale design

Define how Neuro behaves when there are hundreds or thousands of proposals.

Do not treat "Approve 100" as the long-term solution.

Create a strategy based on significance and exception handling.

Gate

P0 closes when a repeated autonomous run against unchanged inputs:

* does not duplicate work or spend,
* preserves provenance,
* respects budget,
* detects changed governing inputs,
* and leaves accepted research state protected.

#### P1. "Do It Tonight"

Mission

Create the first user-facing scheduling primitive.

Do not build the full Bidirectional Scheduler.

Reuse the durable queue primitives already present.

Initial UX

Where appropriate:

Run now
Tonight
Overnight batch

Do not expose scheduler mechanics.

First candidate

Use a real operation already valuable to the user, such as:

* stale rebuild,
* expensive research,
* or another bounded operation.

Requirements

A scheduled operation must:

* run exactly once,
* survive the browser being closed,
* show pending state clearly,
* be cancellable before execution where safe,
* respect budget,
* preserve provenance,
* report success/failure,
* and avoid duplicate execution after restart/retry.

Gate

A user schedules legitimate work from the UI, leaves, returns later, and the work has completed exactly once with correct state and cost attribution.

#### P2. E7 Nightly Refinery

Mission

Turn Transcript Intelligence into a persistent product behavior.

Neuro should perform bounded useful research without the user initiating every run.

Initial behavior

For each eligible active project:

1. determine whether valuable T4 work exists,
2. respect nightly project budget,
3. select the appropriate transport,
4. execute bounded work,
5. reconcile output,
6. create a Project Delta,
7. prepare a Morning Report.

Default should favor off-hours economics when latency is irrelevant.

Do not

* research endlessly because work exists,
* automatically exhaust the nightly budget,
* reopen already-current sources without reason,
* silently promote Claims,
* or generate a morning report dominated by operational statistics.

Gate

One real project completes autonomous overnight research with:

* no duplicate source work,
* spend within budget,
* traceable provenance,
* and a concise Project Delta.

#### P3. Morning Report

Mission

Make overnight intelligence understandable in less than one minute.

Primary hierarchy

1. What changed?

Maximum emphasis.

2. Why it matters

Connect changes to the project.

3. What needs me?

Only consequential human judgments.

4. What Neuro handled

Secondary.

5. Operational details

Collapsed.

Example shape

3 things changed overnight

Evidence supporting seller financing strengthened.

One source conflicts with the working-capital assumption used in your current plan.

No meaningful new support was found for the broker-fee assumption.

Your plan is still usable. One area may need review.

Review 2 items

Behind Details:

* sources examined,
* findings generated,
* sources stopped,
* coverage changes,
* spend,
* provider path,
* duration.

Gate

A user can correctly explain the meaningful overnight change without inspecting Findings or internal instrumentation.

#### P4. Research Review at Scale

Mission

Make the user's attention requirement grow much more slowly than the evidence corpus.

The product should answer:

Which few things actually require human judgment?

Build toward

raw findings → clusters/propositions → Claims → tensions/gaps → decisions affected → actions

Candidate triage signals

Prioritize review based on:

* Decision Impact,
* disagreement,
* novelty,
* evidence weakness,
* provenance quality,
* source independence,
* irreversibility,
* freshness sensitivity,
* and downstream plan impact.

Important rule

Do not auto-approve merely because confidence is high.

Confidence and consequence are different.

Representative review

Investigate whether large groups of substantively equivalent findings can be reviewed through representative propositions or clusters while preserving inspectability.

Gate

A project with thousands of proposed findings presents a small, defensible exception queue without hiding consequential disagreement.

#### P5. Finish the T4 Intelligence Loop

This rung is several small experiments, not one monolith.

P5.1 Brief-text relevance

Test project-brief embedding against the current Claim-centroid relevance basis.

Pay special attention to tabular/spreadsheet sources.

Do not switch the ranking basis without a backtest.

P5.2 E6 prefilter

Fix only the evaluation-isolation issue necessary to measure the existing filter.

Measure:

* relevant-window recall,
* drop rate,
* tokens avoided,
* filter cost,
* net savings.

Enable only if the predetermined gate is met.

P5.3 E4 quality measurement

Recover the real product question:

Are T4-produced Findings useful enough to retain, and what characteristics predict usefulness?

Use a small manually reviewed sample.

Do not treat bulk approval as quality evidence.

P5.4 E5 only if still decision-relevant

Run the Sonnet/Haiku comparison only if choosing between those execution paths still affects real economics.

Do not spend money to complete an obsolete experiment.

Gate

T4 ranking, filtering, model tier and economics are driven by evidence rather than unfinished planning assumptions.

#### P6. T5 and T6 Operationalization

T5

The question is no longer whether adjudication works.

Define triggers for when expensive adjudication is justified.

Candidate triggers:

* high-impact contradiction,
* weak consensus affecting a decision,
* consequential minority viewpoint,
* strong sources disagree,
* plan-critical uncertainty.

T5 should create proposed resolution/adjudication, never silently resolve the canonical state.

T6

Do not create a generic assumptions dashboard.

Instead surface T6 when:

* an assumption has expired,
* a measured constant no longer matches reality,
* a plan depends on an unmeasured assumption,
* or an assumption materially affects a recommendation.

Gate

T5/T6 output appears in the user's workflow because it changes what the user should know or do, not because the subsystem has data to display.

#### P7. Structured Delta Experiment

Mission

Determine whether Findings alone lose important research structure.

Do not build structured-delta persistence first.

Experiment

Select approximately 20 strong, varied long-form sources.

Process them through:

Arm A

Current Findings path.

Arm B

Prototype structured analysis capable of identifying:

* candidate Claims,
* contradictions,
* qualifications,
* additional evidence,
* Evidence Targets,
* meaningful unresolved questions.

Then evaluate:

What consequential information can Arm B identify that cannot be reconstructed reliably from Findings?

Decision

If the difference is small, keep the simpler Findings model.

If structured output consistently identifies material Claim changes, contradictions or unanswered questions that Findings misses, admit a dedicated structured-delta rung.

Gate

A written measured decision exists before production implementation.

#### P8. Continuous Research

Mission

Transform projects from static research collections into living knowledge systems.

Capabilities

* durable source collections,
* rescan known channel/site/subreddit,
* scheduled rescans,
* freshness policies,
* Claim monitoring,
* stale evidence refresh,
* change detection,
* significance filtering.

Important distinction

Do not refresh because something is old.

Refresh because:

the probability it changed × the consequence if wrong justifies checking.

A historical fact may remain useful for decades.

A financing rate may deserve frequent refresh.

Gate

Neuro can answer:

What in this project could have changed, what is worth rechecking now, and what actually changed?

without rescanning the entire corpus.

#### P9. Research Beyond the Existing Corpus

Mission

Prevent Neuro from becoming increasingly confident inside an incomplete worldview.

Three complementary systems are required.

P9.1 Source Capability Intelligence

Learn which source reservoirs historically provide particular evidence classes and topics.

Use this for gap routing.

Do not confuse source capability with source authority.

P9.2 Adaptive Discovery

The product should learn from user selections.

Initial shape:

* rank a small set,
* user keeps/rejects,
* next set adapts.

Do not create a static top-5 feature and call it adaptive.

P9.3 Exploration protection

Adaptive systems must preserve deliberate exploration.

Otherwise they produce preference tunnel vision.

Start with a bounded exploration quota rather than trying to optimize it immediately.

P9.4 Field Map

Use external field structure, surveys, review works, catalogs, reference maps, or other broad sources to identify questions and areas the project has not considered.

Field Map suggestions remain proposed exploration.

They do not automatically become research truth.

Gate

Neuro can identify a valuable question the existing project corpus never asked.

#### P10. Living Master Plan

Mission

Move from "generate a plan from research" to "maintain a plan whose reasoning remains connected to changing evidence."

Every important plan element should eventually distinguish:

* Known
* Assumed
* Chosen
* Uncertain
* Blocked
* Monitored

Required capability

Plan changes should be explainable.

Not:

Your plan is stale. Rebuild?

Prefer:

One part of your plan may need to change.

New evidence affects the assumption supporting Step 8.

Neuro recommends moving lender prequalification before seller-note negotiation.

Review change

Plan stability

Do not rebuild the plan because every new source arrives.

Use material-change thresholds.

Preserve plan versions and the reasoning behind changes.

Gate

New evidence can produce a specific proposed plan change with a traceable path:

evidence → research-state change → decision/dependency impact → proposed plan change

#### P11. Neuro Everywhere

Do not admit this rung until the internal intelligence loop is trustworthy.

Project Inbox

External material can be handed to Neuro without forcing the user through native ingestion flows.

Support:

* URL,
* PDF,
* screenshot/image,
* document,
* correspondence,
* structured extraction supplied by an external AI.

External AI access

ChatGPT/Claude should be able to:

* discover projects,
* obtain compact project intelligence,
* ask Neuro for research substrate,
* send user-approved material/context back,
* and propose project-state changes.

The external AI remains a conversational reasoning layer.

Neuro remains the durable research substrate.

Multi-user

Implement identity and project-scoped permissions before broad sharing.

User facts, decisions and interpretations must remain attributable.

Do not allow one user's AI conversation to silently modify another user's canonical project state.

Gate

An external AI can reason over a permitted Neuro project and return useful context without gaining unrestricted project/database access or becoming a second hidden source of truth.

#### P12. Bidirectional Scheduler

Keep parked until measured need exists.

Do not implement it because the design is elegant.

Potential future design:

* urgent paid/small work from one side,
* cheap/free bulk work from the other,
* Batch transport between them.

Admit only when the simpler scheduling system shows measurable problems involving:

* starvation,
* latency,
* provider contention,
* cost inefficiency,
* or workload fairness.

### 8. Major Failure Modes to Protect Against

Autonomous knowledge contamination

AI-generated interpretation gradually becomes accepted fact.

Protection: proposed-state boundary and explicit provenance.

Feedback-loop tunnel vision

Adaptive discovery repeatedly shows what the user already prefers.

Protection: exploration quota and diversity tests.

Activity mistaken for value

The system optimizes findings count, source count or tokens saved.

Protection: measure useful changes, gaps closed, kept quality, decisions improved and user attention consumed.

Alert fatigue

Continuous research becomes another inbox.

Protection: significance thresholds and valid "nothing important changed" reports.

Plan thrashing

Minor evidence repeatedly changes the Master Plan.

Protection: material-change thresholds and plan versioning.

Stale-job mutation

A background job writes results after the project goal changed.

Protection: governing-revision identity and reconciliation.

Duplicate paid work

Concurrent schedulers or retries process the same material.

Protection: stable work units, hashes and idempotent enqueue/execution.

False consensus

Ten derivative sources appear to be ten independent confirmations.

Protection: evidence lineage and source-independence modeling.

Bad freshness semantics

Old automatically means stale.

Protection: Claim-specific volatility/freshness.

Absence becomes evidence

Neuro fails to find support and treats that as proof of falsehood.

Protection: explicit unknown, searched, unsupported and contradicted states.

Instrumentation UI creep

Every subsystem gets a page/card/dashboard.

Protection: subsystem information appears only when it changes user action.

Cost optimization destroys quality

Cheap models generate cheap noise.

Protection: optimize cost per useful/kept/decision-relevant output.

Multi-user contamination

One collaborator's interpretation becomes another person's accepted truth.

Protection: identity, attribution, ACLs and proposed-state transitions.

External-AI self-citation

An AI interpretation enters Neuro, then later appears to independently support itself.

Protection: hard provenance classes separating external evidence, user statements and AI interpretations.

Evaluation overfitting

Golden fixtures become the product.

Protection: holdouts, varied domains and periodic real-project sampling.

### 9. Claude and Codex Ownership

Maintain narrow ownership to avoid collision.

Codex lane

Primarily backend/reliability:

* scheduling primitive,
* not_before productization,
* durable nightly semantics,
* project/brief revision pinning,
* idempotency,
* dedupe,
* budget enforcement,
* cancellation/retry safety,
* E6 eval isolation,
* T4 experiments,
* Project Delta backend contract,
* overnight recovery,
* integrity gates.

Claude lane

Primarily experience/product behavior:

* Run Now / Tonight UX,
* Morning Report,
* Project Delta presentation,
* review-at-scale interaction,
* significance hierarchy,
* progressive disclosure,
* plan-change explanations,
* minimizing visible subsystem mechanics.

Neither agent should independently expand the mission into adjacent parked features.

Shared surfaces require coordination through HANDOFF.md.

### 10. Three Near-Term Demonstrations

These are the product milestones that matter most.

Milestone A: "Do it tonight"

The user chooses Tonight for a real bounded operation.

They leave.

The work executes exactly once.

When they return, Neuro clearly explains what happened.

Success means

The scheduler is invisible.

The outcome is dependable.

Milestone B: "Neuro worked while I slept"

E7 runs against a real active project.

The user wakes up to no more than a handful of important changes.

They do not need to inspect hundreds of Findings to understand the result.

Success means

Neuro created more understanding than attention cost.

Milestone C: "Neuro changed my plan for a reason"

New research materially affects a belief, dependency or assumption.

Neuro detects the consequence.

It proposes a specific Master Plan change and explains the causal chain.

It does not silently rewrite the user's plan.

Success means

The user sees:

This new evidence changes this belief, which affects this decision, which is why Neuro recommends changing this step.

That is the target product experience.

### 11. Execution Order

Unless a new reliability emergency overrides it:

P0 Trustworthy Autonomy
→ P1 Do It Tonight
→ P2 E7 Nightly Refinery
→ P3 Morning Report
→ P4 Review at Scale
→ P5 Finish T4 experiments
→ P6 Operationalize T5/T6
→ P7 Structured Delta experiment
→ P8 Continuous Research
→ P9 Beyond-Corpus Intelligence
→ P10 Living Master Plan
→ P11 Neuro Everywhere

P12 Bidirectional Scheduler remains parked until justified by measurements.

Some bounded experiments may run in parallel when they do not block or collide with the current rung.

### 12. Admission Rule

Before implementing any new capability, answer:

1. What user problem becomes meaningfully better?
2. Does an existing mechanism already solve most of it?
3. What is the smallest rung that proves the value?
4. What evidence will decide whether the next rung deserves to exist?
5. What can this corrupt, duplicate, confuse, or make expensive?
6. How does the user experience improve if this succeeds?

If the answer to #6 is primarily:

"There will be more data, metrics, controls, dashboards or generated findings"

the rung is probably not ready.

### 13. Definition of Magical

"Magical" does not mean hiding uncertainty or making more autonomous AI calls.

It means the system has enough context and discipline that the obvious next step appears to happen naturally.

Neuro feels magical when:

* it remembers so the user does not have to,
* researches before the user realizes research is needed,
* notices meaningful change without inventing noise,
* knows when not to spend money,
* understands when evidence affects a decision,
* asks fewer but better questions,
* protects the user from its own uncertainty,
* and keeps the plan synchronized with reality.

The product should progressively move from:

research tool

to:

research system

to:

persistent decision intelligence

to:

trusted planning partner.

That is the mission.

---

## Part 2 — CTO rulings and admission amendments (Kyle, 2026-09-14)

These rulings amend PRODUCT-INTELLIGENCE-MISSION.md.

Where this amendment conflicts with the original mission text, this amendment wins.

The strategic direction of the mission remains approved.

### 1. P0 IS AN AUDIT RUNG, NOT A BUILD RUNG

Approved.

The repository already contains substantial trustworthy-autonomy machinery.

Do not rebuild capabilities simply because the mission describes them as requirements.

P0 becomes:

**P0. Autonomous Execution Admission Audit**

Goal

Prove that the existing safety mechanisms work together under unattended execution and identify only the missing protections.

Existing mechanisms to verify before building anything

Verify current main, but expected mechanisms include:

* source_revision
* brief_revision
* facts_revision
* input_hash
* job dedupe_key
* findings is_current
* work-unit accounting
* budget ceilings
* provider/rate controls
* proposed-state Findings
* claims.set_status promotion boundary
* research tensions
* retry/recovery behavior
* full database integrity checking
* verified backups

Do not replace these with parallel abstractions unless the audit proves they cannot satisfy the autonomous-run requirement.

**P0 audit scenarios**

At minimum prove:

A. Repeated execution

Run the same autonomous work twice.

Expected:

* no duplicate paid work,
* no duplicate Findings,
* no duplicate Claims,
* no duplicate jobs,
* no double materialization.

B. Governing input changes mid-flight

Queue work against revision A.

Change the relevant project/brief/facts state before completion.

Verify the eventual result cannot silently masquerade as current revision-B research.

If current provenance already provides sufficient warning/reconciliation, document it.

If not, fix the narrow gap.

C. Restart/retry

Interrupt work during execution and recover it.

Expected:

* no duplicated provider spend where preventable,
* durable state remains coherent,
* completed work is not repeated unnecessarily,
* retry ownership is clear.

D. Budget exhaustion

Hit the autonomous-run budget boundary.

Expected:

* work stops or defers cleanly,
* accepted state remains valid,
* no hidden continuation occurs.

E. Promotion boundary

Verify autonomous Findings/research cannot silently become accepted canonical Claims merely because the run was unattended.

F. Concurrent completion

Exercise multiple autonomous source completions together.

The T4 E3 run already exposed one real concurrent claims.harvest() race.

The audit must assume concurrency will reveal additional bugs that serial tests never see.

G. Database safety preflight

Before an autonomous execution envelope that may mutate durable research state:

1. run full SQLite integrity_check, not quick_check;
2. require success;
3. create a verified backup before mutation begins.

Do this once per autonomous execution envelope, not once per individual source/job.

Several jobs belonging to the same nightly refinery run should share the same preflight rather than generating N backups.

If backup frequency becomes materially expensive in time or disk, measure first and design a safe recent-backup reuse policy rather than silently weakening this gate.

**P0 gate**

P0 closes when the existing machinery passes these scenarios or only measured failures have been fixed.

P0 must not become an open-ended reliability rewrite.

### 2. REVIEW AT SCALE MOVES OUT OF P0

Approved.

Remove review-at-scale design from P0's admission gate.

Scheduling existing operations does not inherently create a new Findings-review problem.

Review scaling belongs in P4, before large autonomous research volume makes that problem substantially worse.

Therefore:

P0 does not block P1 on P4 research.

### 3. P1 SPLITS INTO TWO GATES

Approved.

Codex's active frontend split should not be collided with unnecessarily.

**P1A. Scheduled Execution Backend**

Owner: backend/reliability lane.

Goal:

Prove Neuro can schedule a bounded operation for future execution without relying on a browser session.

Initial supported interface may be CLI/internal API.

Requirements:

* durable requested execution time,
* correct not_before semantics or equivalent existing primitive,
* exact-once logical execution,
* dedupe,
* cancellation where safe,
* restart recovery,
* budget protection,
* preflight integrity/backup,
* clear success/failure state.

P1A gate

A legitimate operation is scheduled from CLI/API, the initiating process can exit, and Neuro later performs the operation exactly once with correct provenance and state.

Passing P1A permits backend work on E7 to proceed.

It does not mean the user-facing "Do it tonight" product experience is finished.

**P1B. "Tonight" Product Experience**

Owner: Claude/design lane after the frontend split is safe to modify.

Appropriate actions may expose:

Now
Tonight
Overnight batch

Do not expose queue internals.

P1B gate

The user can schedule legitimate work from the product UI, leave, return later, and clearly understand:

* what was scheduled,
* whether it ran,
* what happened,
* what it cost where relevant,
* and whether anything needs attention.

Only P1B closes the complete user-facing P1 milestone.

### 4. EXECUTION-HOST AVAILABILITY IS A HARD PRODUCT CONSTRAINT

Add this explicitly.

Neuro currently runs on hardware that may sleep.

Browser independence does not imply machine independence.

A job scheduled for 2 AM cannot execute if the machine running Neuro is asleep and cannot be awakened.

Near-term requirements

Host state must be honest

Neuro must not promise:

Runs tonight at 2 AM

if it has no credible mechanism to execute at 2 AM.

The UI may instead communicate something equivalent to:

Ready tonight. Runs while Neuro is available.

or provide a stronger promise only when the host configuration supports it.

Idle sleep

Investigate whether Neuro can hold an appropriate macOS power assertion while scheduled/active autonomous work requires the machine to remain awake.

Do not assume this solves lid-close sleep.

Lid closure

Closing a Mac laptop lid is a separate constraint.

Do not claim that an application-level keep-awake mechanism guarantees execution with the lid closed unless proven on the actual deployment configuration.

Missed schedule

Scheduled work must have an explicit missed-window policy.

Default candidate:

If the host was unavailable at the requested time, run at the next eligible wake/start unless:

* the work is no longer current,
* its deadline has passed,
* the user cancelled it,
* or executing late would violate the task's semantics.

Record:

* scheduled time,
* actual start time,
* reason for delay.

Longer term

A persistent host, desktop machine, server or cloud worker may eventually remove this limitation.

Do not make cloud migration a prerequisite for proving P1/E7 locally.

Gate

The product never silently represents sleeping-host limitations as successful scheduling.

### 5. E5 STATUS CORRECTION

Update §4 and P5.

E5 has now run and selected Haiku as the Findings default.

Treat that decision as:

SHIPPED, PROVISIONAL PENDING P5.3 QUALITY EVIDENCE

Do not undo it merely because the original ladder expected E4 first.

Reasons to retain provisionally:

* reversible,
* cheaper,
* measured enough to justify a bounded default,
* limited downside if monitored.

But do not misrepresent the evidence.

The model choice was informed by a small quality spot-check, not the intended kept-rate dataset.

P5.3 therefore still matters.

Its purpose is no longer:

Should we permit E5?

Its purpose is:

Does larger human quality evidence support keeping Haiku as the default?

If P5.3 materially contradicts E5, revisit the model decision.

### 6. DECISION IMPACT V1 MUST USE REAL SIGNALS

Accepted challenge.

Do not implement the six-factor conceptual formula as an LLM-generated score.

For v1, use only signals that exist reliably in product state.

Start with:

Signal 1: disagreement

Existing research tensions / contradiction state.

Signal 2: plan impact

Whether the affected Claim, Evidence Target, assumption or research object participates in or materially supports an existing plan item.

If a deterministic relationship cannot be proven, report Decision Impact as unknown rather than inventing precision.

Novelty, irreversibility and freshness sensitivity remain future candidate signals.

They require their own representation/evidence before being admitted.

The conceptual formula remains product direction, not a production scoring specification.

### 7. MORNING REPORT V1 MUST NOT PRETEND P4 EXISTS

Accepted.

P3 may precede P4.

Therefore the first Morning Report must not promise an intelligently minimized judgment queue that Neuro cannot yet rank honestly.

V1 may show

* what changed,
* coverage delta,
* what Neuro researched,
* important existing tensions,
* stale/risky state using already-supported triage signals,
* spend/budget,
* operational details behind disclosure.

V1 must not claim

These are the exact 2 things you need to review

unless the ranking has a real defensible basis.

Existing staleness/triage tiers may be used as an explicitly provisional prioritization aid if appropriate.

After P4:

Morning Report can graduate to:

What needs me?

with consequence-aware review prioritization.

### 8. PRE-READ ORDER CORRECTION

Approved.

Before any rung begins:

1. CLAUDE.md
2. newest STATE-OF-THE-APP-*
3. tail of HANDOFF.md
4. PRODUCT-SCHEDULER.md
5. DEVELOPMENT-OPERATING-SYSTEM.md
6. relevant active mission/admission documents
7. recent commits / active ownership

CLAUDE.md belongs first because its standing operating rules govern execution.

Historical documents remain evidence/context, not assignments.

### 9. T4 OWNERSHIP

Decision:

Claude retains T4 implementation and experiment ownership through the current T4 experimental ladder.

Reason:

Claude already holds the working context for E1 through E5.

Transferring ownership now creates unnecessary handoff cost and raises regression risk.

Claude owns

* remaining T4-specific experiments,
* P5.1 brief-text relevance,
* P5.2 E6 prefilter evaluation,
* P5.3 kept-rate quality evidence,
* reconciliation of provisional E5,
* T4-specific structured-delta experiment support if later admitted.

Codex owns

* scheduled execution infrastructure,
* durable timing,
* queue/retry semantics,
* preflight integrity/backup,
* execution-host safety,
* idempotency/reliability audits,
* E7 orchestration around T4,
* generic Project Delta infrastructure where it does not require altering T4 semantics.

Integration boundary

Prefer:

t4.execute(...)

as the boundary.

E7 should orchestrate T4, not duplicate T4's ranking/research logic.

If Codex discovers a required change inside T4, record the requirement in HANDOFF.md for Claude rather than casually editing the subsystem in parallel.

Likewise Claude should not redesign generic scheduler semantics inside T4.

### 10. UPDATED NEAR-TERM ORDER

The admitted sequence becomes:

P0 Autonomous Execution Audit
↓
P1A Scheduled Execution Backend / CLI
↓
P1B Tonight UI when frontend ownership clears

After P1A passes, backend work may proceed in parallel toward:

P2 E7 Nightly Refinery backend

while Claude handles the safe UI lane and remaining T4 experiments.

Then:

P3 Morning Report V1
↓
P4 Review at Scale
↓
Morning Report V2 with "What needs me?"
↓
P5 remaining T4 evidence loop
↓
P6+ subsequent mission ladder

This is a dependency graph, not a requirement that every item execute serially.

Non-colliding evidence work may proceed in parallel.

### 11. GOVERNING PRODUCT RULE

Do not make Neuro rebuild infrastructure it already has.

Do not let infrastructure existence substitute for proving product behavior.

The sequence is:

verify existing mechanism → expose the real gap → fix only that gap → prove the user outcome

The purpose of this mission is not to create more architecture.

It is to make the architecture Neuro already has finally behave like a trustworthy research partner.

### 12. ACCELERATION STRATEGY — CURRENT EXECUTION INTERPRETATION (2026-09-15)

Accepted (Kyle's Product Intelligence Acceleration Directive, 2026-09-15). Verified against `main` before
writing; where the repo already had something, the repo wins and the ladder was adapted rather than the code.

**Objective.** Maximise meaningful product capability per development cycle while preserving the trust, evidence,
cost and promotion boundaries above. The product target: Neuro knows what deserves attention.

**Priority change.** P11 Neuro Everywhere (external ChatGPT/Claude access, Project Inbox, multi-user/ACLs,
external write-back) is FUTURE / NICE TO HAVE / NOT ON THE CRITICAL PATH. `EXTERNAL-AI-ACCESS-MISSION.md` is
preserved unchanged and its security/provenance requirements stand; the only present obligation is that P8–P10
interfaces stay coherent and provenance-preserving so a future external consumer is not designed out. P12
(bidirectional scheduler) stays trigger-only. Cloud hosting is not a prerequisite for anything below.

**The five capabilities, and the one loop they share.** Continuous Research (A) and Living Master Plan (B) are the
primary product goals; Source Capability (C), Adaptive Discovery (D) and Field Map (E) are the research-expansion
goals. They are NOT five systems. They share one loop over objects that already exist:

    PROJECT STATE (Claims + freshness_status · tensions · Evidence Targets · plan evidence links · assumptions)
      → RESEARCH NEED (read-only projection — see below)
      → RESEARCH PRIORITY (Decision Impact · freshness class · known reservoirs via candidates.where_to_look)
      → BOUNDED RESEARCH (existing nightly envelope; t4.execute; knowledge.pursue; candidates/collections)
      → PROJECT DELTA (delta.for_envelope — the change contract)
      → Morning Report · review queue · Decision Impact · plan impact
      → PROPOSED action / plan patch (plan_updates; claims.set_status remains the only promotion door)

**Thin shared seams, verified to exist (reuse, do not duplicate):** `claims.FRESHNESS_RULES` +
`freshness_status()` (the refresh policy: class × age, "uncertain" never invents confidence); `knowledge.pursue`
(project → library → candidates → external escalation, recorded in `last_escalation`); `candidates.creator_yield`
/ `untapped_by_creator` / `where_to_look` / `_creator_term` (the project-scoped source-capability view and its
ranking term — SOURCE-CAPABILITY-RUNG.md's "not built" is stale: 0.58.3 shipped most of it);
`decision_impact.decision_impact` (disagreement, plan_impact); `plans._evidence` + `plan_items` keys +
`plan_updates` (previous/proposed/reason/pending|accepted|rejected — the patch substrate already exists);
`delta.for_envelope`; `nightly.run`; `candidates` index (`first_seen_at`/`last_seen_at`/`metadata_revision`) +
`collections`/`source_collections` (known reservoirs); `sources.revision`; `work_units`.

**Research Need is an adapter, not a table.** A read-only projection over: accepted Claims whose
`freshness_status` is `stale`/`needs_refresh`; open high-impact tensions; open Evidence Targets; plan-cited Claims
that are weak; assumptions the night exercised. It carries the underlying object type/id, why, consequence (from
Decision Impact), freshness requirement, and where to look (from `where_to_look`). It is admitted only because it
has three immediate consumers: continuous-research candidate selection (CR1), source routing for refresh (SC3),
and the Morning Report / review queue. No schema until a vertical slice proves persistence is needed.

**Project Delta remains the change contract.** Extended only when a consumer proves it must be. The distinction
observed evidence → AI interpretation → accepted Claim → user decision → plan proposal is preserved at every step.

**Ladder rule.** `EXECUTION-LADDER.md` Stages 10–15 now encode REAL dependencies and mark parallel eligibility;
P8/P9/P10 are not serial. Admission is per small slice (SC0-sized), never per feature family. UI: contextual
progressive disclosure on existing surfaces, one-click defaults with inspectable detail — no new dashboards.
Cost order: deterministic data → existing derived objects → Global Library → local → off-hours batch →
interactive paid only when decision value justifies it. Success is measured in consequential changes surfaced,
stale Claims usefully refreshed, unnecessary refreshes avoided, targets closed, plan steps correctly identified,
attention avoided, cost per useful result — never raw counts.

**Closed-loop scenarios (to be built as the pieces land):** A (stale plan-supporting Claim → due → reservoir →
contradiction → delta → plan impact → one report item, nothing auto-accepted); B (Field Map proposal → accepted
target → exploration → capture → target gains evidence); C (monitored Claim checked, nothing changed, report says
nothing important changed).
