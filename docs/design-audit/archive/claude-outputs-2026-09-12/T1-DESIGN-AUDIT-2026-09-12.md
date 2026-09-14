# T1 design audit — 2026-09-12 (Claude, read-only)

Scope: `docs/T1-ADMISSION-2026-09-12.md` and `docs/PRE-T1-GATE-AUDIT-2026-09-12.md` checked against
`DEVELOPMENT-OPERATING-SYSTEM.md` §35–39, `TRANSCRIPT-INTELLIGENCE-MISSION.md` revision 2 (Kyle's eight
corrections), `docs/R9-ADMISSION-2026-09-11.md`, and the code seams the admission document names
(`db.py`, `embeddings.py`, `novelty.py`, `findings_quality.py`, `claims.py`). Nothing in the checkout was changed.
Codex's uncommitted work was not read beyond `git diff` headers.

Verdict: the design is faithful to seven of Kyle's eight corrections. One decision in it makes T1's own first
deliverable impossible as written, and one piece of the evidence it rests on is not reproducible from the repo.
Both need an owner decision before the first implementation slice; neither needs new architecture.

---

## 1. BLOCKER — the measurement needs one vector space, and the design mandates two

T1's first deliverable (§35, T1-ADMISSION gate 4) is: for every transcript chunk, similarity to the nearest active
Claim and nearest applicable Finding, published as a project-relative distribution and compared against locator
coverage. That is a chunk-to-derived-object comparison. It is only defined when chunks and derived objects are
embedded in the same space.

The admission document selects `bge-m3` (1024-d) for derived vectors and — correctly, per Kyle's correction 7 —
forbids mixing it with the existing 1536-d `text-embedding-3-small` chunk vectors, and forbids re-embedding the
corpus. Taken together those three statements leave nothing to compare. The document's own seam table shows the
tension: "Chunk vectors: preserve the validated model space" and "Coverage: compute over chunk embeddings … and
R7's project-relative comparison patterns" — `novelty.py` compares chunk-to-chunk in OpenAI space and returns an
empty matrix when widths differ.

Root cause is a drift in what R9 was for. §28/§35 say T1 uses "the embedding system validated by R9", written when
R9 meant "can a local model replace the retrieval embeddings". R9(a) measured exactly that (chunk retrieval on the
frozen fixture: recall/MRR). It did not evaluate bge-m3 as an embedder of Claims and Findings, and selecting it for
derived vectors only is not something R9(a) tested.

Two coherent options, both honest to the rules:

| | A. Derived objects in the existing OpenAI space | B. Full bge-m3 space |
|---|---|---|
| What T1 does | Embed canonical Claims/Findings with `text-embedding-3-small`, versioned; compare to chunk vectors already stored | Add a versioned second chunk-vector column, backfill 35k chunks locally, embed derived objects, compare only within version |
| Cost / time | ≈$0.03 once (mission §D estimate); one low-lane job | $0; ≈20 min of local embedding at 34 ms/chunk plus a chunk migration/backfill gate |
| New code | Metadata columns, typed helpers, backfill adapter, report — the admitted first slice, unchanged | All of A plus an embedding-provider abstraction (§2 below), a chunk-vector version column, search-path awareness of which column is current, and a production retrieval gate before search may use it |
| Contradicts an existing rule? | No. It is the mission's original T1 design | Contradicts T1-ADMISSION's "does not re-embed the live corpus" and "existing chunks unchanged", so it needs an explicit rewrite of that admission |
| Where bge-m3 lands | A later, separately gated rung: "versioned local re-embed of retrieval + derived vectors", with R9(a) as its pre-evidence and a production-data retrieval gate | Now |

Recommendation: A for T1's measurement slice. It is what §D of the mission already specified, it reuses every seam
the admission document lists without adding one, and it produces the number T1 exists to produce. Record B as the
follow-on rung with its trigger (for example: local re-embed is admitted when the production-data retrieval gate
passes on a copied backup, or when OpenAI embedding spend crosses a stated monthly figure). This is Kyle's call
because it changes what "T1 uses the embedding system validated by R9" means; it should be decided in the
scheduler, not implied by code.

## 2. HIGH — no application path exists for bge-m3; the admission's "existing seam" is OpenAI-only

`embeddings.embed_texts` calls `providers.openai_client().embeddings.create(model=settings.embedding_model, …)`.
`settings.embedding_model` is a single string with no provider, dimension or runtime attached. There is no
Ollama client, contract, breaker (`ollama:embeddings`), health snapshot, usage price entry, or `providers`
route for embeddings anywhere in the package. R9(a)'s fixture rebuild "through the local Ollama endpoint" was
necessarily done by a script outside the app (see §3).

If option B — or any bge-m3 use — is chosen, T1's first slice grows by an embedding-provider boundary that the
admission document does not list: routed behind `providers` (CLAUDE.md: the only model entry points), $0 ledger
rows with a provider label so `cost_value` stays honest, a cached health snapshot rather than a per-read probe
(the 0.63.39 lesson: Ollama is a second external runtime exactly like the Claude CLI), and a breaker so a stopped
Ollama service parks the backfill instead of failing it. That is reasonable work, but under §42 "reuse map before
building" it must be declared as new, not assumed to exist.

Under option A none of this is needed for T1.

## 3. HIGH — the R9(a) selection is recorded as prose only

HANDOFF.md requires "the actual command, result, environment, candidate source hash, and artifact paths."
`docs/R9-ADMISSION`, `HARDENING.md` and `SPEED-MISSION.md` carry the numbers (bge-m3 p50 34.48 ms, recall@10
1.0000, MRR 0.8898; nomic rejected on MRR 0.8087) but the repo contains no benchmark script, no result JSON under
`evals/retrieval/`, no command line, and no note of how the production RRF path was pointed at Ollama (a
monkeypatched `embed_texts`, presumably). The same is true of the R9(b) rows now being written.

Before T1 or the bge-m3 rung cites R9(a), commit the script and its JSON output beside the existing
`baseline-retrieval-*.json` artifacts, with the fixture hash and Ollama/model versions. Otherwise the SELECT cannot
be re-run when the model or Ollama changes, which is the "RETEST AT <trigger>" mechanism §28 depends on.

One observation for the record, not a finding: 30 fixture queries is a small sample, and bge-m3's MRR (0.8898) is
below the OpenAI reference (0.9093) while clearing the frozen 5% floor. That is a legitimate pass. It is also a
reason not to move production retrieval to bge-m3 on fixture evidence alone — the production-data gate in option B
is doing real work.

## 4. MEDIUM — canonical scope leaves `status='reserve'` findings undecided

T1-ADMISSION says canonical Findings are `approved`/`suggested`. `project_notes.status` also has `reserve`
(D1: "extracted beyond the cap, lower importance — promotable, never exported"; `findings.py:452`). Reserve rows
are real derived knowledge that Neuro Search paid for. Excluding them makes `represented` undercount; including
them lets low-importance material into clustering. Kyle's correction 6 is "canonical/active by default" and reserve
is neither clearly active nor clearly discarded.

Recommendation: embed them, tag them, and publish the T1 distribution both with and without reserve so the effect
is measured rather than assumed. Dismissed findings and `rejected`/`superseded` Claims stay out, as designed.

## 5. MEDIUM — locator reconciliation needs four rules the design does not state

The locator-vs-semantic comparison is the heart of T1. Four things in the schema will silently distort it unless
decided up front:

- `claim_evidence.stale = 1` and `source_revision` mismatches. Stale evidence should not count as current locator
  coverage; report it as its own bucket.
- Finding locators live in `project_notes.citations` as JSON. The shape must be pinned (source id, start) and a
  finding with no parsable locator counted as "cited without locator", not as covering nothing.
- `chunks.start`/`end` are seconds for media, page numbers for documents (`documents.py` pages), and group
  indexes for sheets. "Evidence start falls inside the chunk window" is a per-source-type test; a single numeric
  comparison will produce false negatives on documents.
- 1,792 sources but 1,229 with retrievable chunks (mission §A). Sources with no chunks cannot be represented at
  all; the report needs a "no chunks" bucket so they never inflate `unexplained`. Kyle's correction 1 applies here.

## 6. MEDIUM — "fail open" needs a definition for a report

Gate 2 says a missing/stale/wrong-dimension vector "fails open; it never makes a finding, Claim, or transcript
chunk unreachable." That is the right rule for T2 views and search. For T1's report it is not enough: an object
with no usable vector is simply absent from the semantic signal, and if that absence is not counted the
distribution is wrong in a way nobody can see. Define fail-open for T1 as: excluded from similarity, counted in a
published "vector missing / stale version" bucket per project, and the report refuses to label anything
`unexplained` while that bucket is above a stated share. This is Kyle's correction 2 restated for the failure case.

## 7. LOW — version the vector by more than model name

Store beside each derived vector: `embedding_model`, `embedding_dim`, an `embedding_version` string that also
covers the text-preparation template and normalization, `content_hash` of the text actually embedded, and
`embedded_at`. Compare only when (model, dim, version) match exactly. `content_hash` is what makes gate 3 (change
detection on content edit) cheap: no hash, no re-embed. `chunks.embedding` has none of this today; that is fine
for T1 under option A, and it is the first thing option B would have to add.

## 8. LOW — ledger and retention side-effects

`usage.record("embed", model, tokens)` prices by model name. A $0 local embed must still write a row with the
model and a provider label, or `cost_value.by_model` loses the basis (the 0.59.3 lesson). Separately, a derived
backfill of ~25k objects will add job/job_event rows during the R8 30-day retention sample; note the job id so the
sample is not misread as organic growth.

## 9. PROCESS — two documents disagree about whether R9(b)/(c) block T1

`docs/T1-ADMISSION` and `docs/R9-ADMISSION` both say R9(b)/(c) "do not block T1" because R9(a) resolved the
embedding decision. `docs/PRE-T1-GATE-AUDIT` says T1 must not begin until R9(b)/(c) are complete or deferred with
numeric triggers, and `PRODUCT-SCHEDULER.md` NOW follows the audit. R9(b) (sub-second triage model) and R9(c)
(15k-token extraction model) have no dependency on T1 — T1 is embeddings and arithmetic. Under §12 admission
checkpoints this is exactly the "owner-approved deferral with a revisit trigger" case. Recommend Kyle records
one line in the scheduler: R9(b)/(c) continue as their own measurements; T1 is admitted on R9(a) plus the §1
decision. Then the three documents agree.

---

## What is right and should not be reopened

- Measurement before feature; no `unexplained` label before the semantic signal exists (corrections 1, 2).
- Project-relative percentiles, no universal cosine (§35).
- Canonical/active scope by default, dismissed material only for a stated purpose (correction 6).
- Model/version beside every derived vector, stale versions treated as absent (correction 7).
- Resumable, idempotent, low-lane backfill on the existing `jobs` seam; no new store (§42).
- `semantics.py` stays removed; its all-row fixed-quantile policy is the wrong shape (T1-ADMISSION is explicit).
- T2 persists nothing until a query proves the need; T3's pre-Claim layer prototypes on the chunk (corrections 3, 4).
- Executor is backend-agnostic; Claude Code is a backend (correction 5). T4 reuses R4/R5.
- T6 stays parallel (correction 8).

## Decisions needed from Kyle before the first slice

1. §1: option A (OpenAI space now, bge-m3 as a later gated rung) or option B (full local space now, admission rewritten).
2. §4: reserve findings in or out of canonical scope for T1 (recommend in, reported separately).
3. §9: record the R9(b)/(c) deferral so T1 is not waiting on unrelated benchmarks.

Everything else above is implementation guidance Codex or I can carry into the first slice without a decision.
