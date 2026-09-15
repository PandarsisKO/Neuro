# FM0 — Field Map $0 experiment (2026-09-15)

PARALLEL PREP for P9.4 Field Map, gated `scholar_wanted` (the same signal that already gates `scholar_pass` —
literature is only ever fetched when the user asked for it or an open target names expert/authoritative
evidence as missing). This is EXPERIMENT ONLY: a written go/no-go between two candidate $0 methods, using only
existing tooling. It does not build FM1 (blind-spot proposals) — that stays gated on this decision, per the
ladder's own ordering.

## The question

Field Map's job is to find questions the project's own corpus never asked, by comparing the project's Claims/
targets/sources vocabulary against the STRUCTURE of a small number (2–3) of external review works on the same
subject — not their content, their shape: what topics they group together, what a field considers worth a
section of its own. Two candidate shapes for that structure, per the ladder: reference-list clusters, or the
headings of the review works themselves.

## What the existing tooling actually gives each method, for $0

**Reference-list clustering.** `neurosearch/scholar.py` already fetches Crossref/OpenAlex catalogue records
(`search()`, `CROSSREF_FIELDS`/`OPENALEX_FIELDS`) but does not currently request either catalogue's reference
list — Crossref's `reference` field and OpenAlex's `referenced_works` are both returned in the SAME request
these fields already make, at no extra network cost. Adding them is a one-line field addition plus a small
parse step (`_from_crossref`/`_from_openalex` already turn raw catalogue JSON into `_record()`s the same
shape). Clustering the cited works' own titles by token overlap against `claims.project_vocab` (already built
and reused by LP4/SC0b this arc) is deterministic, no model call, and directly comparable to how `_creator_term`
already scores overlap. **This is additive to code that exists — no new capability, no new abstraction.**

**Heading clustering.** Requires the review work's full text, which requires it to be open-access AND already
acquired (`scholar.acquire()` → the normal ingest pipeline) — a real, if occasional, cost beyond $0 when a
paper isn't open. Once ingested, there is no existing heading detector: `book_sections` (G6P1) gives real
structure only for EPUBs; a PDF or HTML review article ingests as plain segments/chunks with no heading
signal preserved. Getting from that to "this field groups these topics under this heading" would mean
building a NEW heuristic extractor (line-length / capitalization / numbering heuristics over plain text,
since font-size metadata is not retained past PDF extraction) with no existing primitive to lean on, and no
way to validate its accuracy against real papers without a live catalogue fetch.

## Constraint hit while running this experiment

This environment (the cloud sandbox this rung is being executed in) has no outbound network route to
`api.crossref.org` / `api.openalex.org` — confirmed directly (`curl` to Crossref timed out / connection
reset). `scholar.py`'s real network calls only ever run on Kyle's own machine, inside the actual app — the
same reason CR7 (the real-project gate) needs Kyle's own night rather than anything runnable here. So this
document reasons from what each method requires and what the code already has, not from a live comparison run
against real catalogue results, and says so plainly rather than fabricating a verdict from data that was never
fetched.

## Go / no-go

**GO on reference-list clustering as the one method worth prototyping toward FM1.** It needs only a small,
additive extension to fields `scholar.py` already requests (no new network cost, no new table), reuses
`claims.project_vocab` and the same token-overlap discipline `_creator_term`/SC0b already apply, and is fully
unit-testable with fixture catalogue responses — nothing about validating it requires a live fetch, since the
comparison is deterministic token overlap over data the fixture already supplies.

**NO-GO, for now, on heading clustering.** It requires a real new extraction capability (no existing
primitive), a non-zero acquisition cost (full-text ingest, not just catalogue metadata), and — per FM0's own
gate ("no paid pass unless the $0 method fails AND the paid one has clear decision value") — the more
expensive method should not be attempted before the cheaper one has been tried and found insufficient. Revisit
only if reference-list clustering, once built and run by Kyle on a real project, turns out not to surface
anything a plain vocabulary diff wouldn't have shown anyway.

## What this does not do

Does not implement reference-list clustering — that is FM1, explicitly gated on this decision, not built here.
Does not run a live catalogue query — the sandbox has no route to Crossref/OpenAlex; the actual go/no-go
EVIDENCE (does this method surface a real blind spot on one of Kyle's real projects) is Kyle-gated the same
way CR7 is, and belongs to FM1's own gate once built, not to this document. This document only decides which
of the two candidate methods is worth building toward that test.
