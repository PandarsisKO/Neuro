> PARKED IDEA. Priorities: DEVELOPMENT-OPERATING-SYSTEM.md and PRODUCT-SCHEDULER.md. Historical unfinished items are not a work queue.

> **2026-09-21:** this idea record is partly SHIPPED — FM0 (`0da834b`) and FM1 (`87ba57b`, `neurosearch project field-map`) exist. FM1-gate/FM2/FM3 are PARKED: no project has a DOI-bearing Work to seed the map. The "Not built" text below is historical.

# The field-map rung — "I don't know what I don't know"

Filed 2026-09-10, from Kyle, right after 0.57.0 shipped. Not built. This is the note that says why it is worth
building and what would be wrong to build.

## The distinction 0.57.0 missed

What shipped queries a catalogue with **a question the project has already formulated**. `scholar.for_target` takes
an open evidence target and looks for literature that could close it. That is answering a *known* question faster and
for nothing.

Kyle's point runs the other way: a single review article, survey or book does not answer your question — it tells
you **which questions exist**. It hands you the shape of a field, including the parts you had no vocabulary for and
therefore could never have asked about. Every gap mechanism in the app today is downstream of something the project
already noticed:

| mechanism | where the gap comes from |
|---|---|
| `knowledge.pursue` | a target somebody already wrote |
| `research_view.questions` | Claims and tensions already harvested |
| `candidates.pool` / `_potential` | fit to open questions and weak areas already known |
| `discover` | the brief, plus channels already in the project |
| `claims.assess` MISSING_PERSPECTIVE | a perspective absent from evidence already collected |

All five are *reflections of the corpus*. None can produce a question whose vocabulary is not already somewhere in
the project. That is the actual hole, and it is structural, not a tuning problem.

## Why a catalogue can close it and the corpus cannot

Three properties that nothing already in the app has:

1. **A review article is a curated map of a subfield**, written by someone who read it all. Its reference list is a
   reading list; its section headings are the field's own taxonomy, in the field's own words.
2. **Catalogue metadata carries structure the app never sees** — `referenced_works`, citation counts, and OpenAlex's
   `topics`/`concepts`. A cluster of highly-cited works the project has never touched is a measurable blind spot: not
   inferred from the project's own vocabulary, which is exactly the point.
3. **`type:review` is a filterable fact**, not a guess. OpenAlex can be asked for *only* the field maps.

## The shape it should take

Not "search for papers." Something closer to: given a project's brief, fetch the handful of review/survey works
covering it, and report the **taxonomy** — the recurring section topics and the reference clusters — as
*candidate areas the project has no coverage of*, in the source's own words, each traceable to the work that named
it. Output is a proposal for the user to accept or reject, not new research state. The natural landing place is a
tension kind (MISSING_PERSPECTIVE already exists and means almost this) or a new band in the Areas pane reading
"named by the literature, absent from your sources."

## What would be wrong to build

- **Do not let a catalogue write research state.** A topic named by an outside taxonomy is a *suggestion*, and
  `claims.set_status` remains the only door into the project's own claims. G5's boundary is not negotiable because
  an outside vocabulary is persuasive precisely when it is unfamiliar.
- **Do not run it for every project.** The 0.57.0 gate (`scholar_wanted`, expert/authoritative targets or an
  explicit ask) exists because a corpus of YouTube channels about editing workflow has no literature behind it.
  A field map of a field that does not exist is noise wearing a lab coat, and Kyle's stated objective is more
  findings *that are not trash*.
- **Do not confuse an academic taxonomy with the project's real gaps.** A literature's own divisions reflect how
  research is funded and published, not what Kyle needs to decide. Present it as "this is how the literature
  divides this", never as "you are missing X".
- **Do not make it a paid pass.** The whole appeal is that a review article's structure is free metadata. The
  moment this needs a model call per candidate topic it stops being cheaper than the model pass it supplements,
  which was 0.57.0's entire argument.
- **Do not build a second classifier or a second fetch path.** Extend `resources.classify`; go through
  `safe_fetch`. Same rules as everything else.

## Open question worth settling first

Whether the *reference list* of two or three reviews is a better field map than the reviews' own headings. The
reference list is measurable (clusters, counts, overlap with the corpus) where headings need interpretation — which
means the reference-list version might be doable at $0 and the heading version might not. Measure before choosing;
do not assume the richer-sounding one wins. That is the same discipline that killed the reranker and deferred the
prefilter.
