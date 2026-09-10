# The source-capability rung — remembering where to look

Filed 2026-09-10, from Kyle, immediately after FIELD-MAP-RUNG.md. Not built. The two are halves of the same
problem and should be read together.

> "when we scrape/partially ingest entire sources, knowing the type of information a source (master source) might
> provide us, is good data."

## The two halves

| | names | direction |
|---|---|---|
| FIELD-MAP-RUNG.md | **which questions exist** | outside-in, from literature the project does not own |
| this rung | **where to look for answers** | inside-out, from sources the project already partly owns |

Gap analysis today produces a question and then starts a search from nothing. What it never does is remember that a
place it has already been is the likely answer.

## What the app throws away

There is **no aggregation at the master-source level anywhere in the codebase.** `sources.channel` is set per
platform (YouTube channel, subreddit, book creators, page domain) and used for exactly three things: grouping the
Sources list, a CSV column, and a Bootstrap label. `collections` records that a channel was enumerated. Neither
carries a single fact about what that channel *turned out to be good for*.

The sharpest illustration is `candidates._potential`. It scores a known-but-uncaptured source out of 100 from the
words in its own title and 600 characters of description — and nothing else. So a video from a channel where
sixty siblings already produced hundreds of findings, closed three evidence targets and supplied the project's only
experiential pricing evidence scores exactly the same as a video from a channel that has never yielded anything.
The measurement exists. It is simply not consulted.

Kyle's partial-ingest pattern makes this worse than a missed optimisation. His live corpus has channels at 60 of
598, 107 unstarted, 93 unstarted, 398 unstarted. Those uningested remainders are not unknowns — they are
**reservoirs of known character**, and the app treats them as a flat list of strangers.

## The shape

A master-source **capability profile**, derived at $0 from artifacts that already exist, answering: what kind of
information has this source actually provided?

- **evidence classes it yields** — from `claim_evidence.evidence_class` on Claims whose evidence traces to its
  sources. This is the field that matters most, because an evidence target already declares
  `preferred_classes`, so the match is direct rather than semantic.
- **claim types and topics it yields** — from `project_claims.claim_type` / `topic` via the same trace.
- **density** — findings per hour of material, and what share survived to become Claims. Kyle's objective is
  volume that is not trash, and this is the per-source version of that same ratio.
- **targets it has closed before** — `candidate_links` already records kind + ref (`evidence_target`, `claim`,
  `tension`); resolving those to the master source is the "we found the answer here last time" signal.
- **coverage** — ingested versus known, so the size of the untapped remainder is a number.
- **cadence and freshness** — from `published_at` spread, which decides whether this source can answer a
  question whose `freshness_class` demands something current.

Then gap routing: an open target names its preferred evidence classes and its topic; the profiles say which master
sources have supplied that class on that topic before, and how much of each remains unread. The output is a
ranked *place to look*, each line traceable to the Claims that justify it — "Chase AI supplied 23 of your 31
experiential pricing findings, from 12 of 398 videos" — not a similarity score.

`candidates._potential` then gains a master-source term, which is the smallest useful first slice and probably
worth shipping alone before any of the rest.

## The architectural conflict to resolve first — do not skip this

G4's standing policy is explicit: **never build a global Source Profile from project findings, summaries or
relevance.** A capability profile derived from what a source yielded is, by construction, derived from project
findings. These two cannot both be satisfied naively, and the honest resolution is a split:

- **Global, metadata only** — topics, terms, cadence, authority signals. This is `library.baseline`, which already
  exists and must not learn from any project's interpretations.
- **Project-scoped yield** — evidence classes, claim types, density, targets closed. Real, valuable, and it stays
  inside the project that produced it, like `project_reuse` does for Bootstrap.

Gap routing combines the two at query time. Aggregating yield across projects is a *separate* decision with its own
justification; the reason for the G4 rule is that a finding is an interpretation written against one brief, and it
does not become a fact about a channel just because it is averaged. Whoever builds this should assume
project-scoped and argue their way out of it, not the reverse.

## What would be wrong to build

- **A trust or quality score.** `community.py` refuses one deliberately and this must too. A capability profile is
  multi-dimensional and says what a source is *for*, never how good it is. The moment it collapses to one number
  it starts overriding Kyle's judgement about his own sources.
- **A paid pass over the library.** G4's policy holds: every signal above already exists in the database. If this
  needs a model call per master source it has failed.
- **Anything that auto-ingests the remainder.** The output is a ranked place to look. Channels/playlists must be
  reviewed and approved before transcription — that rule predates all of this.
- **Treating absence as evidence.** A channel that has yielded no authoritative evidence may never have been asked
  for any. Zero yield on a class the project never pursued is not a finding about the channel, and reporting it as
  one would be the same error as claiming a skipped escalation step had been checked.
- **A new identity concept.** `channel` plus `collections` plus `works` already carry master-source identity per
  platform. Extend those. A fourth notion of "the thing a source belongs to" is how this gets unmaintainable.
