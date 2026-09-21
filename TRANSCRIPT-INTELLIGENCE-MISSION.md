> PARKED UNTIL FOUNDATION CLOSEOUT — first major product mission afterward. Priorities: DEVELOPMENT-OPERATING-SYSTEM.md and PRODUCT-SCHEDULER.md. Historical unfinished items are not a work queue.

> **2026-09-21:** T1 is COMPLETE (0.63.56, `docs/T1-ADMISSION-2026-09-12.md`); T2–T6 were admitted separately through `docs/T*-ADMISSION-*.md`; the T2 `bge-m3` embedding-space migration is PARKED (no versioned migration gate). This is NOT the active program — `PRODUCT-INTELLIGENCE-MISSION.md` is (since 2026-09-14). The banner below is historical.

# Transcript Intelligence & Research State — evaluation and ladder

*Filed 2026-09-10 against Kyle's brief on two connected goals: better organisation of research state, and cheaper
cumulative understanding of source material. Written after measuring his live corpus, not from the brief alone.*


> **Sibling mission (filed 2026-09-10, not started):** `EXTERNAL-AI-ACCESS-MISSION.md` — letting ChatGPT/Claude use
> Neuro Search as a shared project intelligence layer, with per-identity project ACLs, a Project Inbox for material
> sent in from outside, and a hard boundary between external evidence, user decisions and AI-generated material.
> It shares this mission's cost rule ("never pay twice to rediscover something Neuro Search already learned") and
> depends on project state being cheap to assemble, which is what 0.62.2 and 0.61.4/0.62.0 made true.


**Revision 2 (same day), after Kyle's review.** He found five errors and three misjudgements in revision 1, and
they are corrected in place rather than quietly overwritten, because two of them were the same class of mistake
this project keeps making — reading a measurement as if it answered a question it never asked.

1. **"No claim evidence" is not "unexplained".** Revision 1 called 26,083 chunks unexplained on the strength of a
   locator test. A chunk with no `claim_evidence` inside it may be an introduction, a tangent, repetition, or a
   finding that never became a Claim. Coverage is now a **multi-signal state**, below, and "genuinely unexplained"
   is one of seven values rather than the complement of one test.
2. **The 74% and "far from every Claim" were two different measurements, presented as one.** The 74% came from
   locators; semantic distance had not been computed at all, because nothing was embedded yet. T1 now has to
   *produce* the semantic measure before anything is labelled a blind spot, and the two numbers are reported
   separately and compared.
3. **Evidence Atoms were dismissed too hard.** `claim_evidence` is evidence that has already been promoted to a
   Claim. The point of cheap mining is the material *before* that — warnings, procedures, costs, exceptions, tool
   mentions, questions. That intermediate layer genuinely has no home. The storage *pattern* exists; the layer does
   not.
4. **A JSON blob on every chunk is a trap.** It is the right prototype and the wrong destination: extractions will
   need filtering, querying, provenance and selective recomputation per extractor version. A narrow normalised
   table stays explicitly open.
5. **The refinery must not be Claude Code.** Claude Code is today's cheapest backend, not the architecture. The
   subsystem is a **Batch Research Executor** with interchangeable backends.
6. **T1 must not embed everything.** Dismissed findings, near-duplicates and superseded Claims would pollute
   similarity and clustering. Embed canonical/active knowledge by default; keep dismissed material deliberately and
   for a stated purpose (stopping it resurfacing).
7. **Embeddings need a version.** A bare BLOB with no record of which model produced it leaves a mixed vector space
   the first time the embedding model changes. Store the model and version beside the vector.
8. **T6 is not a prerequisite.** The assumption ledger is parallel housekeeping and was crowding the feature.

The assignment was to decide how much of the brief can be built without premature infrastructure. The short answer:
**most of the organisational model already exists and is not visible; most of the cheap-analysis ladder does not
exist but is nearly free to add; and the new data model the brief proposes (Evidence Atoms) should be prototyped on
the storage that already exists before it becomes a table of its own.**

---

## A. The measured picture (his own database, backup 2026-09-10 05:58)

Every number below is from his corpus, and several of them change what is worth building.

| | |
|---|---|
| sources | 1,792 (1,229 with retrievable chunks) |
| chunks | 35,029 · **100% already have embeddings** · avg 961 chars · 33.7 M chars total |
| findings | 12,301 (11,779 kept) — **no embeddings** |
| Claims | 13,371 (7,673 normalized) — **no embeddings** |
| claim evidence | 14,780 rows, **every one with an exact start offset**, across 974 sources |
| chunks containing a piece of claim evidence | **8,946 of 35,029 — 25.5%** |
| median source: share of its chunks with evidence | 34.8% (mean 39.4%) |
| sources with **zero** explained chunks | 300 |
| sources over half explained | 418 |
| month to date | $367.20 charged · findings $205.34 · claims $114.25 |

**What the 25.5% does and does not say.** It is a *locator* measurement: the share of chunks that contain the start
offset of a piece of evidence attached to a Claim. It says nothing about whether the rest was understood. Revision 1
called the remaining 26,083 chunks "unexplained" and that was wrong — they may be introductions, repetition,
tangents, material represented by a finding that never became a Claim, or genuinely untouched. **No semantic
measurement existed when that number was taken, because nothing derived was embedded.**

So the honest form of the claim is narrow: *74.5% of chunks have never had a piece of Claim evidence located inside
them, and we do not yet know what share of that is worth reading again.* Finding out is T1's job, and it is
measurable: the locator signal and the semantic signal can be compared directly once both exist, and the difference
between them is itself the interesting result.

**Coverage is a state, not a flag.** Seven values, each from a different signal, all cheap:

| state | signal |
|---|---|
| `extracted` | Tier-0 deterministic extraction has run at this extractor version |
| `represented` | close to a Claim or finding vector (semantic — needs T1) |
| `finding_covered` | a finding cites this chunk's window |
| `claim_covered` | a piece of claim evidence is located inside it |
| `redundant` | near-duplicate of another chunk (the `findings_quality` machinery, applied to chunks) |
| `irrelevant` | far from the project's goal and every Claim: owned, and not about this |
| `unexplained` | extracted, not redundant, not irrelevant, and represented by nothing |
Only the last is refinery fuel. The brief's illustrative morning report is right in shape; the numbers in it will
come out of this table rather than from the complement of one test.

**The embeddings are already paid for.** Every chunk has one. Nothing in the brief's Tier 1 needs a new model call over
transcripts — only over the *derived* objects, which have no vectors yet. T1's first measurement embeds those derived
objects in the same current production space as the chunks, so the comparison is mathematically defined. A local model
that uses a different dimension is a later full-space migration experiment, not a silent second space for T1.

---

## B. What already exists (and mostly is not visible)

The organisational model in the brief is, layer for layer, the architecture that is already here. This matters
because the gap is largely **surfacing and connecting**, not building.

| Brief concept | Already in Neuro Search | State |
|---|---|---|
| Candidate / Catalog | `candidates.py` — global Candidate Index, per-project state/reason/origin, `pool()` with a $0 potential scan | built, surfaced as "🔎 Known, not captured" |
| Catalog a channel without ingesting | `explore.py` (feed/sitemap/website), `rank_proposed`, Review card | built |
| Global Source Library, acquire once | `library.py` + `project_sources` membership (no copy, no re-transcribe) | built |
| Attach only relevant portions | `bootstrap.py` `project_reuse` (suggest → attach/dismiss) | built |
| Preserve skipped / dismissed / blocked | `project_sources.excluded`, `sources.status='skipped'`, `candidates` state, `sources.error_class='browser_solvable:*'` | built |
| Needs browser capture | `acquire.py` + `external_pending` + extension queue + `completeness` | built |
| Project Evidence → Findings → Claims | `findings.py`, `claims.py` (harvest $0, normalize lazily) | built |
| Knowledge Map, Tensions, Evidence Targets as first-class objects | `knowledge.py`, `research_tensions`, `evidence_targets`, `research_view.py` panes | built |
| Strength / Readiness / Freshness kept separate | `claims.assess` — three independent fields with `*_why` | built |
| Discovery driven by gaps | `knowledge.pursue` escalation, `candidates.where_to_look`, scholar `for_target` | built |
| "What do we know" vs "what should we do" | `knowledge.state` vs `planner.py` | built |
| Stale | `staleness.py` (CURRENT / STALE / REBUILDING / accepted) | built |
| Never re-acquire a source | global identity + `works.py` + `resolve_acquired` | built |
| Evidence Atom (promoted) | **`claim_evidence`** — source, locator, exact start, excerpt, class, independence, lineage, revision | built, but only for spans already attached to a Claim |
| Evidence Atom (**pre-Claim**: warning, procedure, cost, exception, tool, question) | nothing | **the genuine gap** — see C.3 |
| Cheap first, expensive last | `contracts.TIERS` + the four reason kinds + `release-check` refusing an unjustified tier | built (for model choice) |
| Resumable, incremental | `jobs.py` leases/heartbeats/dedupe/`Yield`, staged ingestion, `input_hash` idempotence | built |
| Provenance and timestamps | provenance columns on every AI artifact, `source_revision` frozen on evidence | built |

**Two things follow.** First, the brief's organisational half is largely a *visibility* problem: the objects exist,
the user cannot see the state they encode. Second — corrected from revision 1 — `claim_evidence` and `chunks`
between them provide the *storage pattern* an Evidence Atom needs (a span with provenance, a revision, a vector,
a cascade), but not the layer: `claim_evidence` only ever describes a span that has already become part of a
Claim's case. The interesting material for cheap mining is the span that has not: a warning, a procedure, a cost, an
exception, a tool mention, a question. **That layer does not exist**, and saying it did was the strongest claim in
revision 1 that the architecture would not support.

---

## C. What is genuinely missing

Four things, in order of how much they unlock per unit of work.

1. **Derived objects have no vectors.** Chunks do; findings and Claims do not. Every item on the brief's Tier 1
   list — similarity to Claims, claim coverage, novelty, unexplained clusters, cross-source similarity, duplicate
   detection beyond lexical — needs the *derived* side embedded. 13,371 Claims + 12,301 findings ≈ 25,700 short
   texts ≈ 1.3 M tokens ≈ **$0.03 once** at `text-embedding-3-small`, and it is the enabling step for at least six
   features. This is the highest-value low-complexity addition in the whole brief.
2. **Nothing records what analysis a passage has received.** Coverage is *derivable today* for the strongest signal
   (does any claim evidence land in this chunk — the 25.5% above) and not recorded at all for the rest.
3. **No pre-Claim layer, and no deterministic extraction to fill it.** Tier 0 of the brief (numbers, money, dates,
   URLs, citations, named products, questions, procedural language, warnings, exceptions) is genuinely absent,
   genuinely free, and genuinely reusable — and `findings_quality.NUMBER_WORDS` shows the machinery is already
   partly written. This is also the answer to the Evidence Atom question: the atoms worth having are the ones
   cheap extraction can produce *before* anything becomes a Claim.
4. **Overnight work is not gap-driven.** The overnight run of 2026-09-09/10 was a *release* pipeline (ten releases,
   $0). There is no refinery that takes the unexplained 74% and works it down.

---

## D. The ladder

Each rung is independently shippable, gated, and useful on its own. Cost is *incremental* API spend.

### T1 — Embed the derived objects, then MEASURE semantic coverage ($0.03, low complexity) — **do first**
`embeddings.py` already batches and prices; `chunks.embedding` shows the storage pattern (a BLOB on the row, not a
new table). Add a vector to `project_claims` and `project_notes`, embed lazily on write in the current production
`text-embedding-3-small` space, backfill in a `low`-lane job, and compute over the vectors already in memory (the 165 MB
matrix loads in 0.10 s warm — SPEED-MISSION §A). R9's selected `bge-m3` remains a separately gated candidate for a
future full-space chunk and derived-object migration.

Three constraints from Kyle's review, all of which change the design:

- **Scope.** Not "embed both tables". Canonical, active knowledge by default: Claims that are not `rejected` or
  `superseded`, findings that are `approved` or `suggested`. Dismissed findings and rejected Claims are embedded
  only when a feature needs them for a stated purpose — the obvious one being *stopping dismissed material
  resurfacing*, which needs their vectors precisely so it can exclude them. Anything else pollutes clustering with
  material the user already threw away.
- **Version.** Store the embedding model and a version tag beside every derived vector, and never mix them in one
  comparison. A bare BLOB is how a vector space quietly becomes two vector spaces the first time the embedding
  model changes; the same lesson as `usage.price_model` (0.59.3), where the missing basis made a per-model verdict
  wrong. A vector whose version does not match the current one is treated as absent and re-embedded, not compared.
- **Corpus baseline.** Existing chunk vectors are legacy bare blobs. Before they become T1's comparison side, record a
  versioned corpus-space attestation from the configured production model and a measured dimension/count check. If
  that exact identity cannot be verified, exclude the affected chunks from similarity and report the gap; do not
  infer compatibility from vector length alone.
- **The first output is a measurement, not a feature.** Semantic coverage has never been computed here, so before
  anything is called a blind spot: compute each chunk's similarity to the nearest Claim and finding, publish the
  distribution, and compare it against the locator signal (25.5%). How much of the 74.5% is semantically close to
  something we already hold is the number that decides whether the refinery has a large backlog or a small one.
  Thresholds are **percentiles of the project's own distribution**, never absolute cosines — the shape that fixed
  `CREATOR_PROVEN_QUANTILE` — and every answer returns the distribution it was cut from.

Then unlocks, all $0 after the one-off: **claim coverage** (Claims with passages nobody attached), **the coverage
states** in §A, **blind-spot clusters**, **semantic duplicate findings** (the open PARAPHRASE-RUNG decision, whose
only blocker was this cost), and better `library.recall` reranking (0.60.2's own comment points here).
*Gate:* the backfill is resumable and idempotent; a missing or stale-versioned vector never fails a read; the
paraphrase floor published in 0.58.8 is re-measured against the semantic pass and the difference recorded; and the
locator-vs-semantic comparison is written down before any UI calls anything unexplained.

### T2 — Coverage as the seven-state view, derived before it is stored ($0, low)
Start with the view, not the schema: the states in §A computed from what exists — chunk ranges vs
`claim_evidence.start`, `project_notes` per window, `project_source_analysis` per (project, source, kind, depth),
plus T1's semantic signal and the redundancy measure `findings_quality` already implements. That answers "how much
of this source has produced anything" (median 34.8%), "which sources produced nothing" (300 of them) and — new with
T1 — "how much of what produced nothing is nonetheless already represented".
Only once the view is in use, and only for passes that cannot be derived, add a narrow `chunk_pass` table
(chunk_id, pass, extractor_version, revision, ts) — one row per pass actually run, never a matrix of "not done".
*Gate:* every number in the view reconciles against the underlying rows; no pass is recorded that did not run; and
`unexplained` is never the complement of a single test.

### T3 — Tier 0 deterministic extraction, and the pre-Claim layer ($0, medium)
One module, one pass per (chunk revision, extractor version), no model: numbers with units, money, percentages,
dates and durations, URLs and DOIs/ISBNs, book/paper/person/company/tool mentions, questions,
imperative/procedural sentences, warnings and exceptions, comparatives, hedges. This is also where the **pre-Claim
Evidence Atom** lives — the span that is interesting before anything promotes it.

**Storage: prototype on the chunk, keep the normalised table explicitly open.** A JSON column is the right first
move (additive, inherits chunk identity, source revision and the deletion cascade) and the wrong destination, for
the reason Kyle gave: these will need filtering, querying by type, provenance, extractor-version tracking and
selective recomputation, and a blob answers none of that. So the prototype carries `extractor_version` from day
one, and the moment a real query wants "every cost mentioned in this project" or "recompute only the warnings
extractor", it becomes a narrow `chunk_extractions` table (chunk_id, kind, value, span, extractor_version) with the
blob as the cache. The trigger is a query requirement, not a feeling — and it is written here so the decision is
not made by accident.
Immediately useful for: `evidence.py` quote validation, `findings_quality.NUMBER_WORDS` (already needs this),
claim qualifier extraction, `works.extract_identifiers` (exists — extend, do not duplicate), and as the cheap
filter that decides which passages are worth a model at all.
*Gate:* deterministic and idempotent per (chunk revision, extractor version); measured precision on a hand-labelled
sample of his own transcripts before any downstream feature trusts it; and a version bump recomputes only its own
extractor.

### T4 — The Batch Research Executor, gap-driven ($0 API on the local backend) — **the brief's centrepiece**
Two separable halves, and keeping them separate is Kyle's fifth correction:

**The selector** ($0, deterministic): what is worth spending on, from T1+T2 — genuinely unexplained passages, novel
clusters with no Claim, weak or stale Claims, open Evidence Targets, and passages whose Tier-0 extraction says
"numbers and procedure" that nothing has ever read. It produces a ranked, reproducible work list and knows nothing
about who executes it.

**The executor**: a backend interface with interchangeable implementations —

    Batch Research Executor
      ├── Claude Code            (today's default: slow, $0 when the CLI is on a subscription)
      ├── local model            (when T7 earns its place)
      ├── Haiku API              (when speed matters)
      └── future cloud worker    (the app may run entirely in the cloud)

This is not new machinery: `providers.route` + `execution_policy` + the worker pools already choose between local
and API per job, and `contracts.py` already forbids a model choice without a stated reason. The rung is to make the
refinery *use* that seam rather than call Claude Code directly, so a core subsystem never depends on one developer
tool's invocation mechanics.

Output is **structured deltas** (candidate findings, candidate Claims, additional evidence, qualifications,
contradictions, new targets) written as *proposed* state — `claims.set_status` remains the only door, exactly as G5
requires. The morning report says **what changed**, leading with the coverage states from §A rather than a count of
what was skipped.
*Gate:* every delta carries provenance and the input hash it was derived from; a re-run with no new material
produces no deltas and costs nothing; the selection is reproducible and identical across backends; and swapping the
backend changes cost and latency, never what was selected.

### T5 — Sonnet as adjudicator, not reader (net saving, medium)
The brief's "Supreme Court" framing is already the shape of `contracts.TIERS`; what is missing is the *escalation
trigger*. Add explicit adjudication tasks — sources materially disagree, a high-importance Claim has ambiguous
evidence, cheaper systems disagreed — each with a contract, a reason kind (`evidence:` or `capability:`) and a
measured comparison. This is where `cost_value.by_model` starts paying: after 0.59.3 the per-model cost per finding
becomes answerable, so "Haiku reads, Sonnet adjudicates" can be *decided* rather than assumed.
*Gate:* the model decision table (`neurosearch models`) still refuses any tier above the cheapest without a stated
reason; the split is justified by a live comparison, not by this document.

### T6 — The assumption ledger ($0, low) — **parallel, not a prerequisite**
The brief's "never pay twice" has a twin: never keep a number nobody has re-checked. An inventory of this codebase
found roughly **145 constants that encode a judgement about the data, of which 19 are measured** — and the measured
ones cluster in four files. Four separate times in two days a plausible constant was contradicted by his own data
(`CLUSTER_MAX`, `NEAR_JACCARD`, `CREATOR_STRONG_PER_SOURCE`, the per-model finding cost — and in 0.60.2 the
three-character token rule and IDF weighting). A registry where each assumption declares what was assumed, when,
why, and *how to test it against live data now*, with a `neurosearch assumptions` command and a Health section, is
the mechanism that stops the next one lasting two days.
*Gate:* drift **warns**, never fails a release — a moved number is a fact about data, and a gate that fails for
that reason teaches people to ignore gates.

### T7 — Local NLP, only if T1–T4 leave a measured gap (unknown cost, high complexity) — **not now**
NER, keyphrases, topic segmentation, stance and NLI triage are the most attractive-sounding and least justified
part of the brief. They add a dependency (model weights, a runtime, a version to pin), they need their own
evaluation to be trusted, and T1's embeddings plus T3's extraction cover most of what they would be used for.
SPEED-MISSION §D already says local runtimes are TEST-only and never for findings or claims quality. Revisit with
a number: if the refinery's escalation rate stays above some measured share of passages after T4, an NLI triage
step has a case. Until then it is infrastructure ahead of need.

---

## E. Deliberately not building, and why

- **Evidence Atoms as a new table *first*.** Not "never" — revision 1 said that and it was too strong. The
  pre-Claim layer is real and has no home. But `chunks` already gives a span identity, a revision, a vector and a
  deletion cascade, so T3 prototypes the atom *attributes* there, carrying `extractor_version`, and the normalised
  `chunk_extractions` table lands the moment a real query needs it (filtering by type, recomputing one extractor,
  provenance per value). A genuinely separate object — spans that cross chunks, atoms with no source — is a further
  step again, and gets its own argument.
- **A per-chunk × per-pass coverage matrix as step one.** 35,029 chunks × six passes is 210,000 rows recording
  mostly "not done". Derive first (T2), store only what cannot be derived.
- **Blanket re-analysis of anything.** Both the brief and this file agree; the reason it needs saying is that the
  cheapest way to build a refinery is a loop over every transcript, and that is the thing being replaced.
- **A new UI surface per concept.** The Research tab shell (R2) and the Findings workbench (S4) are the two places
  this belongs. Coverage is a column and a filter, not a tab. Kyle's tenth requirement is the one most easily lost.

---

## F. How this folds into work already in flight

- **0.59.3 `cost_value`** is the measuring instrument for the whole ladder: cost per finding, per kept finding, per
  Claim and per corroborated finding, by model and by day. Every rung above should move one of those rows, and if
  it does not, that is the result.
- **0.58.0 `findings_quality`** published its own floor and said the honest fix needed embeddings at ~$0.013. T1
  pays that, so F-series can finally answer the paraphrase question — and its redundancy machinery is what supplies
  the `redundant` coverage state.
- **0.58.2 `candidates.creator_yield` / `where_to_look`** is gap-driven discovery already; T1 makes "where to look"
  semantic instead of lexical.
- **0.60.2 `library.query_anchor`** fixed recall precision lexically and its own comment says a measured semantic
  comparison is where this lands next — T1 again.
- **`jobs.py` lanes** already give the refinery its home: `low` lane, local pool, `Yield` for cooperative
  progress, `dedupe_key` so a nightly run cannot pile up.

## G. Order, and the one thing to do first

    T1 → T2 → T3 → T4 → T5          the feature
    T6                              in parallel, whenever there is a gap
    T7                              only if T4 leaves a measured one

T1 first because it costs three cents, takes one release, and is the precondition for four of the others — and
because its first output is the measurement that tells us how big the backlog actually is. T4 after T1–T3 because a
refinery with no coverage signal is a rescan with a nicer name. T6 alongside rather than in front: it is
housekeeping, it was crowding the feature, and Kyle was right to move it.
