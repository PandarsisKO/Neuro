# Mission BOOTSTRAP — every project starts with what Neuro Search already knows

*Filed 2026-09-09 against 0.49.1. Brief by Kyle; investigation, corrections and ladder below. Nothing here is built.*

---

## 0. The headline finding

**About 70% of the architecture this mission asks for already exists, and the 30% that doesn't is mostly
orchestration and UI, not schema.** That is the single most important thing to know before reading the ladder,
because the brief is written as though Neuro Search stores knowledge per project and must be re-architected. It
doesn't. Sources, transcripts, chunks, embeddings and source profiles are already global; the relationship-row
pattern the brief proposes in §56 already exists three times over; the cross-project retrieval engine the brief
describes in §10–§11 already exists and even names "a new project" in its own docstring as a trigger it was built
to serve. **Nothing calls it at project creation.** That is the mission.

The corollary matters just as much: the parts that are genuinely missing are missing for good reasons, and two of
them should stay missing for now (§3).

---

## A. CURRENT STATE — what the repository actually does

Read: `db.py` schema + migrations, `library.py`, `knowledge.py`, `claims.py`, `findings.py`, `relevance.py`,
`candidates.py`, `api.py` project routes, the creation wizard in `web/index.html`, and the G1/G4 test gates.

### Already solved

| The brief asks for | Where it already lives |
|---|---|
| §12 one source serves many projects; never re-ingest | `sources` is global; `project_sources` is a pure membership row. Gated by the **G1 test: "global identity: one acquisition, N project relationships"**. Already true today. |
| §6 global evidence layer | `sources` → `segments` → `chunks` → embeddings are all global and project-neutral. |
| §36 a global relevance/search representation | **`source_profiles` (G4)** — *baseline* at $0 from stored metadata, top chunk terms, deterministic authority signals, a chunk centroid **and farthest-point "topic vectors"**; *enriched* is one lazy cached model call versioned by source revision, batched at ~50% off. Explicitly "strictly project-NEUTRAL … never built from project findings, summaries, relevance or steering". |
| §10–§11 cheap-recall-first cross-project scan | **`library.recall(project_id, query)`** — chunk-level FTS + vector retrieval over `library_scope` (ready sources *not* in the project), then profile term hits as ranking signal and explanation. Returns suggestions with provenance; attaches nothing. Works with **zero** enriched profiles. |
| §42 a 5-minute Claude passage inside a 3-hour finance podcast must be findable | Already the explicit design rationale for baseline topic vectors *and* for chunk-level (never source-averaged) recall. `recall` returns the matching chunks with timestamps and deep links. |
| §23 gap-first ordering | **`knowledge.py` already mandates the escalation `PROJECT EVIDENCE → GLOBAL LIBRARY → CANDIDATE INDEX → EXTERNAL`** for pursuing any Evidence Target, and records each run in `project_evidence_targets.last_escalation`. |
| §21/§70 strength ≠ applicability ≠ freshness | `project_claims` already carries **`strength` + `strength_why`**, **`application`** ("does it apply to THIS project?"), **`readiness` + `readiness_why`**, and **`freshness_status` + `freshness_why`** as four independent fields. Source **`substance`** is separate again, and global. |
| §48 don't double-count the same evidence | `claim_evidence.independent`, `derivative_of`, and `lineage_id` (one Work = one lineage). |
| §56 relationship rows carrying project-specific state | Exists **three times**: `project_source_analysis` (relevance, relevance_why, model provenance, `brief_revision`), `candidate_projects` (state, relevance, relevance_why, reason, origin), `project_works` (relevance, reason, target). The pattern is idiomatic here; a fourth is a small, familiar change. |
| §69 "relevance may be stored globally by mistake" | **Already found and fixed.** `sources.relevance` / `relevance_why` are legacy columns; `db.py` carries a migration that moves them into `project_source_analysis` keyed by (project, source) with `status='legacy_unverified'`. Project relevance is already contextual. |
| §27/§28/§29 chats, facts, plans stay project-scoped | `conversations`/`messages`, `project_facts`, `plans` are all project-scoped with FK cascade. Non-inheritance is the current default; the risk is only that bootstrap *breaks* it. |
| §30/§51 known-but-uncaptured material | `candidates` + `candidate_projects` + `candidate_links` (B3) — "an open question durably remembers the known-but-uncaptured sources that could fill it", already gated. |
| §31 works/versions/manifestations | `works`, `work_identifiers`, `work_versions`, `work_manifestations`, `project_works` all exist (G6). |
| Name + Goal | `projects.goal` **already exists as a column.** |

### Partially solved

- **`library.recall` takes one query string.** A project goal is not one query. Bootstrap needs a cheap
  query-expansion step and an aggregation across several recalls — no new retrieval engine, just a caller.
- **`findings.suggest_for_source(..., depth=)`** already re-reads one source against the current project brief.
  That *is* §14's targeted recontextualization; it lacks only the "what did we already capture" subtraction.
- **`project_source_analysis.brief_revision`** already records which brief a relevance judgement was made
  against — the machinery for §68's goal-change staleness exists, unused for this purpose.

### Genuinely missing

1. **No bootstrap.** Nothing runs `library.recall` from a new project's goal, aggregates it, or shows it.
2. **The creation form is a 14-field wizard.** Required today is `name` + `brief`; `goal` is buried inside a
   collapsed "Your situation" section as *"What does 'done' look like?"*.
3. **No cross-project identity for findings.** `project_notes` is project-owned text + citations.
4. **No cross-project identity for claims.** Same proposition in two projects = two rows and duplicated
   `claim_evidence`.
5. **No "related project, explained by its useful subset" view.** Nothing computes project-level overlap at all.
6. **No record of *why* an object was reused**, and no per-object reuse state.

---

## B. CORRECTIONS TO THE BRIEF

The brief invites disagreement (§90). Six places where I'd change it.

### B1. Do not make claims global. (against §6, §26)

The brief's instinct — "Claim X supported by A, B, C shouldn't be duplicated" — is right about *evidence* and
wrong about *claims*. Making claims global forces semantic claim identity (the brief's own §72) to be solved
**before anything ships**, and claim identity is the hardest unsolved problem in the product. Worse, it would be
wrong: `strength` is computed from the evidence a project has *accepted*, and two projects may legitimately accept
different evidence for the same sentence. A global strength would silently overwrite one project's judgement with
another's.

**Instead:** keep `project_claims` project-owned. Give it a **canonical proposition key** (the same `lineage_id`
idea already used for Works) plus a small equivalence table, so two projects' claims about the same proposition
can be *recognized* as the same without being *merged*. Bootstrap then says "another project already has evidence
for this proposition — here are its three sources" and lets the new project attach that **evidence**, recomputing
its own strength. Recognition now; merging only if the recognition proves reliable.

### B2. The portable unit is not the finding — it is the finding's evidence. (against §25)

A finding is an interpretation written against a brief, and the schema already knows it: `project_notes` carries
`brief_revision`, `source_revision` and `input_hash`. Copying a finding written for *Business Acquisition* into
*Portfolio Redesign* imports the old framing along with the fact — which is exactly the contamination §7 warns
against, arriving through the front door.

**Instead:** bootstrap surfaces a relevant existing finding as **a pointer to its source, locator and passage**,
labelled with where it came from. The new project re-derives its own finding from that passage if it wants one —
which is `findings.suggest_for_source` on an already-ingested source: cheap, and correct by construction. No
finding text is ever copied across a project boundary. This also disposes of §9's "reusable knowledge
designation": the promotion UX is unnecessary if the portable layer is evidence, because evidence is *already*
global.

### B3. Do not build a new relevance index. (against §36)

`source_profiles` + chunk embeddings + FTS already are it. Whether they are fast enough at Kyle's real scale
(**2,744 sources, 27,248 chunks, all embedded**) is a measurement, and R0's perf ledger exists precisely to make
it. Three times this month a measured reading overturned a confident prediction of mine here. **Measure first;
sqlite-vec only if the number says so**, and §H of SPEED-MISSION.md is where that trigger gets recorded.

### B4. No project lifecycle states. (against §39)

`seed → bootstrap_scanning → bootstrap_review → active` is a new column that can be wrong, can get stuck, and
must be reconciled after every crash — a new class of bug in a product that has spent months making job state
crash-safe. The job system already solves this. **The bootstrap is a job; its state is the job's state.** The
project is usable from the instant it exists, which is the actual product requirement.

### B5. Two job kinds, not five. (against §59)

`bootstrap_scan` (expand the goal into queries, recall, rank, persist candidates — cheap, resumable, `priority`
lane) and `bootstrap_deepen` (targeted recontextualization of specific chosen sources — `slow` lane). Enrichment
is the existing `library.enrich_wanted` / batch path. Gap analysis is the existing evidence-target escalation.

### B6. Explanations must be built from matched passages, not from a model summary. (sharpening §18)

`library.recall` already returns the *chunks* that matched, with timestamps and deep links. Building "why this
matched" from those passages is cheaper than a model call **and** more honest — it can be clicked and checked.
"Highly relevant to your goal" is exactly what you get if you ask a model to explain a retrieval it didn't do.
The related-project summary in §64 ("main overlap: Claude Code, AI automation") should likewise be computed from
the union of matched passage terms across that project's hits, not generated.

### One thing the brief under-weights

**The Finance→Website example is already half-solved and can be demonstrated today.** `library.recall` with a
query about Claude Code / local AI, scoped to sources outside the new project, will surface exactly the AI subset
of the Finance project with its matching passages, and will not surface SBA content, because nothing about it
matches. Rung 2 is largely wiring, and it is worth proving that on Kyle's real library **before** building
anything in rungs 6+.

---

## C. MISSION

> A new project begins with a name and a goal. Neuro Search immediately searches everything the user already owns
> — across every project and the unattached library — and shows what it found, at the level of individual sources
> and passages, with the reason visible. Evidence crosses project boundaries. Interpretation does not. Discovery
> runs last, and only against what is genuinely missing.

**Invariants** (any rung that breaks one is wrong):

1. **No source is ever re-acquired, re-transcribed, re-chunked or re-embedded to serve a second project.**
2. **Nothing is attached without the user's decision**, except within an explicit high-confidence band the user
   can see and undo.
3. **No finding text, chat message, project fact, decision, rejected option, plan or recommendation crosses a
   project boundary.** Ever. Automatically or otherwise.
4. **Every reused object carries a visible, checkable reason** — a passage, not an adjective.
5. **Reuse never inflates evidence strength.** One source is one source, and `independent` / `derivative_of` /
   `lineage_id` continue to govern.
6. **Inherited ≠ true here.** Strength may be global-ish; `application` and `readiness` start unknown.
7. **A project is usable the moment it exists**, and bootstrap failure degrades to an ordinary empty project.

---

## D. LADDER

Each rung ships alone, with tests, under the normal release ritual.

### R1 · Start a project with a name and a goal
Reduce the required form to two fields; everything else moves behind "Add more context" **inside** the project.
`goal` becomes the primary field and the retrieval seed. `brief` stays as the model-facing steering text and is
seeded from the goal until the user edits it (no schema change; both columns exist).
*Tests:* a project can be created from name + goal alone; every existing optional field still round-trips; an
existing project is unaffected. *Cost:* zero. *Risk:* the smallest rung on the ladder; ship it first.

### R2 · The bootstrap scan
New job `bootstrap_scan`: expand goal → a handful of queries ($0 term expansion first; **one** cheap model call
only if the goal is short), run `library.recall` per query, merge by source, rank, and persist candidates.
Persist to a **new relationship table** following the established pattern — `project_reuse (project_id,
object_kind, object_id, state, score, why, origin, brief_revision, created_at, updated_at)` — with `why` holding
the matched passages. Progress reported per stage so the card is honest from the first second (R1 of
SPEED-MISSION applies: partial results, real counts).
*Tests:* the Finance→Website fixture — a 150-source mostly-unrelated project yields the ~15 relevant sources and
none of the SBA content; no transcript is full-scanned; nothing is attached; a failed batch leaves usable partial
results. *Cost:* $0 in the common case.

### R3 · Starting Research review
The screen: counts that grow as stages complete; sources grouped by confidence with progressive disclosure (never
300 checkboxes); **related projects explained by their useful subset**, computed from matched passage terms;
"Review 17" opens the subset, never an import. Attach = `project_sources` insert. Nothing else.
*Tests:* removing an inherited source from the new project leaves the canonical source and the other projects
untouched; chat in the new project cites the attached source and never sees the old project's chats, facts or
plan. **This is the regression surface the brief calls §76 — gate it here, at the first rung that can break it.**

### R4 · Progressive context refinement
The optional questions, asked inside the project, each answer updating `brief`/`context`/`facts` and re-ranking
against the stored `brief_revision`. Explicit user decisions are never re-ranked away.
*Tests:* a new constraint changes the ranking; an accepted source stays accepted; `brief_revision` records which
brief each score was made against.

### R5 · Gap-first Discover
Discover's input becomes the project's open Evidence Targets and weak Knowledge Map areas rather than the brief
alone — reusing the escalation ladder that already exists. Deprioritise topics already covered by strong, fresh,
independent evidence.
*Tests:* a project whose questions are already answered proposes materially fewer acquisitions; a known
duplicate/repost is not proposed as new evidence.

### R6 · Evidence reuse for claims (recognition, not merging)
Canonical proposition key + equivalence table (B1). Bootstrap reports "another project has evidence for this
proposition"; attaching copies the **evidence rows** (pointing at the same global sources), never the verdicts.
`application` and `readiness` start `unknown` for the new project by construction.
*Tests:* strength is recomputed, not copied; the same source counted once; `derivative_of` still suppresses
reposts; a conflicting inherited pair opens a Tension rather than silently picking a winner (§49).

### R7 · Targeted recontextualization
"This source is relevant but its existing findings were written for another goal" → `findings.suggest_for_source`
against the new brief, restricted to the windows that matched, with already-captured passages subtracted.
*Tests:* a re-read reads fewer windows than a cold read of the same source and produces at least one finding the
old project's findings did not contain.

### R8 · Freshness on reuse, learning within the session, observability, evaluation
Freshness checks driven by `freshness_class` (§22 — a 2019 interview is not stale as *historical* evidence);
accept/reject within one bootstrap re-ranks the remaining batch; the diagnostics of §82; and the bounded
recall/precision/cost/latency evaluation of §80 on a deterministic fixture.

**Not built, deliberately:** global claims (B1), reusable-finding promotion UX (B2), a new vector index (B3),
project lifecycle states (B4), cross-project personal context, and any sharing/authorization model. §73's future
multi-user boundary is respected by *not* adding a global mutable knowledge layer — which is also the strongest
argument for B1.

---

## E. WHAT COULD BREAK

- **Chat/plan isolation** is the sharpest risk: attaching many sources widens retrieval scope. R3 gates it.
- **Evidence strength inflation** if R6 copies verdicts instead of evidence. R6 gates it.
- **Scale:** `library_scope` currently materialises every ready source id per call. At 873 ready sources that is
  nothing; at 10,000 it is a query to fix, not an architecture to replace. Measure in R2.
- **Migration:** additive only. One new table (R2), one new column + one small table (R6). The legacy
  `sources.relevance` columns stay untouched — they are already migrated and already marked
  `legacy_unverified`.
- **Cost:** the whole of R2 should be $0 in the common case; the one place a model call is justified is goal
  expansion on a very short goal, and it is one call, cached against the brief revision.
