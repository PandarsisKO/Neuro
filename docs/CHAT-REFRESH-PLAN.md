# Conversation Delta / Chat Refresh — plan

**Status (2026-09-18): CHR0 shipped. CHR1 implemented, pending push.** This is no longer a planning-only document.

Kyle: *"I might not want to retype out a chat, just see if the intelligence surfaces new information I should be
aware of based on new findings."* And, sharpening it: *"A refresh is valuable when it saves me from repeating an
old conversation and tells me only what Neuro has learned that could actually change my understanding or my
plan. More newly ingested material is not itself value. Changed understanding is value."*

Second revision. The first draft (fa2a66a/c912480) was written against a model of the code, not the code; §0
lists what it got wrong. Rungs are **CHR0 → CHR1 → CHR2 → CHR3** (Continuous Research already owns CR1…CR5:
`research_needs.py`, `research_refresh.py`, `tests/test_cr1_*`). Module and test names use *conversation delta* /
*chat refresh*; never "research refresh", which `research_refresh.py` already means.

## 0. Corrections to the first draft

| First draft said | The repository says | Consequence |
|---|---|---|
| rungs CR0–CR4 | CR1–CR5 are Continuous Research (`research_needs`, `research_refresh`, EXECUTION-LADDER Stage 10) | renamed CHR0–CHR3 |
| "the whole conversation is history, as today" | `qa.ask()` loads `db.get_messages(conversation_id, limit=12)` — a 12-message tail | Conversation Delta scans every real user question itself (§5); the paid refresh's history tail is unchanged and is *not* how the whole chat is covered |
| Tier 1 "FTS-only so it is literally $0" by calling `search()` | `search.search()` calls `embeddings.embed_query()` (an OpenAI call) whenever embeddings are enabled | a dedicated `search.search_fts()` seam (§4), gated by a zero-provider-call test |
| paid refresh retrieves from `new_in_scope` source ids only | a Finding can land on an old source; Claim evidence attaches to existing sources; `sources.revision` moves while the id stays | the refresh context is built from the delta's *evidence units* (§9) |
| "refresh answers are harvested into Claims like any answer" | an assistant answer is **not** Claim evidence today; the chain is answer → `save_finding` / Pin → `project_notes` (with citations) → `claims.harvest` | a refresh answer gets exactly that ability and nothing more (§8) |
| cache keyed on `project_view_revision` | that key carries global `sources`/`jobs` churn — SPEED-AUDIT §9 measured it invalidating faster than the value is useful | a narrow `conversation_delta_revision(project_id)` (§11) |
| "new" = `sources.updated_at > answered_at` | membership arrives through `project_sources`, collections and tags with no `added_at`; a source can be in scope while pending; a global source can be attached later with an old `created_at` | "new" = newly *available evidence*, decided by set difference against the stored scope + `sources.revision` + Findings/Claims/tensions timestamps (§3) |
| Findings overlap threshold 0.25 | nothing measured | measure on the live corpus copy first; record the chosen value and why (§6) |

## 1. What the feature is

**Conversation Delta** answers, deterministically and for $0:

1. What has Neuro learned since this conversation last had a *successful* answer?
2. Which of it touches topics this conversation discussed?
3. What changes or contradicts something the conversation previously relied on?
4. Does any of it affect the current Master Plan?

**Refresh this chat** is the optional, paid synthesis of that delta through the existing `answer.chat` contract.
The model call is not the feature; the delta is.

Layers, kept distinct:

- **A. Conversation baseline** — what each successful assistant turn could actually know (CHR0).
- **B. Conversation Delta** — deterministic diff of the project's evidence state against the baseline, classified
  by categorical importance, annotated with Plan Impact where the existing seam can resolve it (CHR1), shown in the
  open chat (CHR2).
- **C. Refresh** — a paid turn fed the delta's evidence units, saved as an ordinary answer with a fresh baseline
  (CHR3).

## 2. Layer A — the baseline (CHR0)

Every **successfully completed** assistant turn records what it could know, in `messages.meta.evidence` (the
`meta` column exists; no new table):

```
evidence:
  research_revision     db.project_research_revision(project_id) at answer time
  answered_at           message created_at (duplicated here so a reader never needs the row)
  retrieval_query       the `_retrieval_query(question, history)` string actually used
  scope_source_ids      project["source_ids"] (ready sources in scope) — or the explicit source_ids passed
  shown_chunk_ids       every excerpt the model was shown: FINAL ctx["hits"], i.e. initial hits + search_library
                        additions + full-context chunks
  shown_source_ids      distinct source_id over shown_chunk_ids
  full_context          bool — the whole scoped material was in the prompt
  question_message_id   the messages.id of the user turn this answers
```

Implementation facts that decide the shape:

- **Final hits, not initial.** `_run_tool("search_library")` does `ctx["hits"].extend(found)`; those excerpts
  were shown and cited as `[n]`. The snapshot is taken from `ctx["hits"]` after the tool loop ends, at the point
  citations are resolved. Full-context turns (`_hits_for` returning `is_full_context=True`) put every chunk of
  every scoped source into `hits`, so they are recorded the same way.
- **Scope before the turn.** `source_ids` is resolved at the top of `ask()` (`project["source_ids"] or
  ["__none__"]`); that list is what is stored, so a source attached later is found by set difference, with no
  `added_at` column.
- **Stable ids.** `db.save_message()` returns nothing and `db.get_messages()` does not expose `id`. The narrowest
  seam: `save_message` returns the new `messages.id` (`cursor.lastrowid` inside the existing `tx()`), and
  `get_messages` adds `id` to its SELECT. Nothing else changes; `question_message_id` and, later,
  `baseline_message_id` are real row ids, never inferred from timestamps.
- **Failure does not advance the baseline.** `save_failure()` writes `meta.incomplete=True` and no `evidence`
  key; an answer that hit the output limit twice (`generation["incomplete"]`) also records no `evidence`. The
  conversation's baseline is the newest assistant row *with* `meta.evidence`. A failed turn stays visibly failed.
- **URL-only / queue-confirmation turns** (the early return in `ask()` when a message is just links) record a
  zero-hit baseline: `shown_chunk_ids=[]`, scope as of that moment, `retrieval_query=""`. Intentional: the
  conversation *was* used, the links queued will become ready afterwards, and the next delta should surface them
  as newly available. Tested explicitly.
- **CHR0 changes nothing else** — not retrieval, prompting, ranking, Claims, or the answer text. It is a
  write-only addition of a few KB per answer.

## 3. "New" means newly available evidence (the exact-baseline path)

Given a baseline `B` (the newest assistant row with `meta.evidence`) and the project as it is now, the delta
detects — each from a real table, none from `sources.updated_at` alone:

| Change | Detected by |
|---|---|
| a source now in scope that was not | `set(project_source_ids(pid)) − set(B.scope_source_ids)` (covers direct attach, collection, tag, and a globally old source attached yesterday) |
| a source that was in scope but has since become usable / re-transcribed | in `B.scope_source_ids` **and** (`status='ready'` now with `replace_transcript` having set `revision` after `B.answered_at`, i.e. `updated_at > answered_at AND status='ready'`) — the timestamp is used only *inside* the already-scoped set, where it means "its transcript moved" |
| new Findings on old or new sources | `project_notes.created_at > B.answered_at` (status suggested/approved), regardless of `source_id` age |
| newly attached Claim evidence | `claim_evidence` rows whose `id` > max id at baseline — `claim_evidence.id` is AUTOINCREMENT; the baseline stores `max_claim_evidence_id` (added to the snapshot for exactly this) |
| Claim strength / freshness / status / application changes | `project_claims.updated_at > B.answered_at` **and** the claim's evidence touches a shown or cited source, or its `topic`/text overlaps a conversation question (§6) |
| new contradictions / tensions | `research_tensions.created_at > B.answered_at`, `status='open'`, `kind IN (CONTRADICTION, NOVEL, …)` whose `claim_id` is in the touched set |
| new evidence that resolves / materially improves an open research question | `project_evidence_targets` whose `status` moved from open after `B.answered_at`, or `research_needs.for_project()` entries that dropped since baseline (needs are a projection, so "dropped" is computed against the baseline's stored need keys — added to the snapshot as `open_need_keys` only if measurement shows it is cheap; otherwise omitted for CHR1 and recorded as a gap) |

No `added_at` schema column: the stored scope plus `sources.revision`/`status` answer every case above. If
measurement finds a case they do not, that is the moment to add schema, not before.

## 4. The $0 retrieval seam

`search.search()` embeds the query whenever `settings.embeddings_enabled`; it is not a $0 operation and global
settings are not toggled to make it one. CHR1 adds:

```
search.search_fts(query, limit, source_ids, per_source_cap) -> list[hit]
```

— the FTS5 leg of `search()` alone, same hit shape (`hit_from_chunk`), same scope semantics, no vector leg, no
rerank. Test gate: a delta computation under the fake provider asserts **zero** calls to `embeddings.embed_query`,
`providers.invoke`, and `usage.record_*`. Hybrid retrieval is used only by the paid refresh (CHR3).

## 5. Whole chat means the whole chat

Kyle chose all chat content. `qa.ask()`'s 12-message tail is the *model's* history and stays as it is; the
delta does its own pass:

- **Questions** = every `role='user'` row in the conversation with non-empty content **and** `meta.kind !=
  'refresh'`. Synthetic refresh turns are never topics, so a refresh cannot become the seed of the next refresh.
- Each question yields `_retrieval_query(question, history_before_it)` (the same function `ask()` uses, so the
  delta's query for a question is the query the answer was built from).
- Chats longer than 12 messages are handled because this reads `messages` directly (`ORDER BY id ASC`, no
  limit), not `get_messages`.
- **Budget:** per question, `search_fts(rq, limit=12, source_ids=newly_available)` — bounded, FTS only. The
  *paid* refresh gets one global excerpt budget equal to a normal chat's hard budget (`MAX_EXCERPTS`), never
  larger. Old questions are not given equal quota until it runs out: **all** questions are scanned, the resulting
  delta units are ranked by category (§6), and the budget is filled from the top of that ranking. A contradiction
  to question 1 beats a corroboration of question 9.

## 6. Classification, not a score

The $0 layer never says "novel" about a chunk merely because its id was not in `shown_chunk_ids`; that is
**new relevant evidence**. Stronger labels need stronger state. Panel order, from the repo's existing signals
(`decision_impact`'s two real signals, `claims.strength/freshness_status/status`, `research_tensions.kind`):

1. **Contradicts or reverses** something previously supported — open CONTRADICTION/NOVEL tension created after
   baseline on a Claim whose evidence touches a shown/cited source, or a Claim that went `accepted → rejected /
   superseded` in that set.
2. **Changes a Claim the Master Plan uses** — same Claim set filtered through `plan_impact.affected_items()`
   (`known=True`, non-empty items).
3. **Materially changes Claim strength / currentness / applicability** — `strength`, `freshness_status` or
   `application` transition on a touched Claim (transition, not just `updated_at`; the baseline stores the
   touched Claims' `(strength, freshness_status, status, application)` tuple as `claim_state` so a transition is
   a fact, not a guess).
4. **Resolves an open question or research gap** — an evidence target closed after baseline, or a need dropped.
5. **Adds a substantively new Finding relevant to the conversation** — new `project_notes` row whose text
   overlaps a question query.
6. **Adds a relevant excerpt from newly available material** — `search_fts` hit on a newly available source.
7. **Corroborates** — new evidence attached to a touched Claim whose state did not change.

One opaque relevance number is not built. For (5) and the "overlaps a question" tests in (1)/(3): token overlap
via `claims.overlap()` is the candidate mechanism; the threshold is **measured on Kyle's corpus copy** (the
session snapshot, `immutable=1`) against a hand-labelled sample of real chats before it is fixed, and the doc
records the value and the sample. 0.25 is not carried over from the first draft.

## 7. Master Plan connection — existing seams only

Hierarchy, unchanged:

```
new evidence
→ Findings / Claims / tensions through the existing research machinery
→ deterministic Conversation Delta
→ deterministic Plan Impact where resolvable      plan_impact.affected_items / plan_narrative.explain
→ optional pending plan update                    plan_narrative.propose_updates (origin='lp3', status pending)
→ user accepts / rejects                          POST /api/plan-updates/{id}, unchanged
→ plan rebuild through the existing path
```

For every changed Claim or new tension in the delta, CHR1 calls `plan_narrative.explain(pid, claim_id=… |
tension_id=…)`. `known=True` with items → the unit is annotated and the panel can say:

> **Could affect your Master Plan** — Seller-financing evidence changed. Used by: *First step: Structure the
> acquisition offer* · *Decision: Minimum seller note* · [Review plan impact]

`known=False` → the panel says exactly the reason `plan_impact` gives ("this plan's evidence citations cannot be
safely mapped… built before the plan-evidence seam existed") — never a guess. **Review plan impact** calls
`propose_updates` (pending rows, the existing accept/reject route promotes them). Nothing rewrites or rebuilds
the plan, and refresh prose is never an input to the plan.

## 8. The refresh answer is not evidence

An ordinary answer is not Claim evidence; it becomes one only through `save_finding` (tool) or Pin to findings
→ `project_notes` with citations → `claims.harvest`. A refreshed answer has **exactly** that ability: the
`save_finding` tool is offered as usual, Pin works as usual, and `claims.request_harvest` fires as usual *when a
note is created*. No path turns the refresh response itself into a Finding or Claim. If auto-materialising
individual delta units as Suggested Findings ever looks worth it, that is a separate product decision, written up
before it is built. Kyle's "yes, feed Claims like any answer" is satisfied by parity, not by a new evidence path.

## 9. The paid refresh context = the delta's evidence units (CHR3)

Not "chunks from new source ids". The context handed to the model is:

- relevant chunks from newly attached / newly ready / revised sources (delta category 6 hits);
- the excerpts cited by newly created Findings (`project_notes.citations` → chunks);
- evidence attached to changed Claims (`claim_evidence` → source/locator → chunk);
- evidence behind new tensions / contradictions (both claims' evidence);
- **plus** the previously cited passages needed for comparison — the chunks behind `B`'s and earlier
  answers' `citations`, marked `[previously cited]`.

Chunks in `shown_chunk_ids` are excluded unless they are one of those comparison passages. The model receives
evidence *selected by the delta*, ranked by §6, cut at `MAX_EXCERPTS`; it is not asked to rediscover the delta
from the corpus. Hybrid retrieval (`search()`) is allowed here for category-6 units because the user has approved
the spend.

Cross-project scope is a hard gate: every unit must resolve to a source in `project_source_ids(pid,
ready_only=False)`; anything else is dropped before the prompt is built (twin-project rule: compute reuse only).

## 10. Prompt behaviour

Synthetic user turn, saved with `meta.kind="refresh"` and rendered as a chip:

> Refresh: what's new since <date> in this chat?

Instruction appended to that user turn (not a new system block — the cached prefix is untouched):

> Review the newly available evidence against the conclusions and questions already discussed in this
> conversation. Report only material differences. Separate: what changes an earlier answer, what adds genuinely
> useful information, and what only confirms what was already known. Call out contradictions explicitly. If the
> new evidence does not materially change or add anything, say so briefly. Do not retell the conversation.

No giant "previous answer" block is pasted: the comparison baseline is the conversation history the turn already
carries plus the `[previously cited]` passages. The refresh result gets its own CHR0 snapshot with
`meta.refresh = {baseline_message_id, since, delta_summary}`, so the next refresh starts from this successful
state. Web search is off for refreshes unless the user turns it on.

## 11. Cache revision — narrow, measured

`db.conversation_delta_revision(project_id)` fingerprints **only** what the delta reads:

```
project source membership   COUNT + a cheap hash of project_source_ids(pid, ready_only=False)   (direct + collections + tags)
ready sources               COUNT(*) WHERE status='ready' in scope || MAX(revision-bearing updated_at) in scope
findings                    COUNT || MAX(created_at) || status counts       (project_notes has no updated_at — same trick project_view_revision uses)
claims                      COUNT || MAX(updated_at)
claim_evidence              MAX(id)
tensions                    COUNT || MAX(updated_at)
evidence targets            COUNT || MAX(updated_at)
plan identity               latest plans.id || plans.updated_at             (plan-impact annotations depend on it)
```

Not in it: `jobs` (heartbeats), global `sources`, usage, notes on other projects. It must move when the answer can
change and stay still while unrelated jobs heartbeat; both are test gates (a job heartbeat on an unrelated source
must not change it; attaching a ready source must). Cost is measured on the live DB copy the way
`project_research_revision` was (~5 ms target); the cache key is `(conversation_id, baseline_message_id,
conversation_delta_revision)`, stored in `cache.py`.

## 12. Old chats — Approximate mode

A chat with no `meta.evidence` on any assistant row:

- baseline = newest assistant row that is not `meta.incomplete`;
- the only known "seen evidence" is that row's (and earlier rows') `citations` source ids;
- post-baseline source / Findings / Claim / tension changes are inspected the same way;
- the panel **never** says "the model had not seen this" — it cannot be known.

Copy: *"Approximate refresh. This chat predates evidence snapshots, so Neuro can identify material added since the
answer but cannot know every excerpt the earlier model saw."* An approximate delta can still offer the paid refresh
when concrete post-date relevant evidence exists. If real use shows unacceptable noise, this one branch becomes
"establish a new baseline first"; the feature is not redesigned.

## 13. UX (CHR2)

No chat-list badge (Kyle: open chat only). No new research dashboard inside the chat. Progressive disclosure:

```
✨ What's new
3 meaningful changes since Sep 14
```

Opening it shows, in order and only the groups that exist:

- **Changes an earlier answer**
- **Adds useful information**
- **Could affect your Master Plan** — only when `plan_impact` returned `known=True` with items
- **More supporting evidence** — collapsed by default

Empty-but-busy: *"Nothing important changed. 15 sources were added to the project, but none matched what this
conversation covered."* No project change at all: no persistent UI. Legacy chat: the Approximate line. Primary
paid action: **Refresh this chat · estimated $X.XX**, with a one-line "what you'll get" above it.

Foreground rules apply: the request is made once on chat open (not on the 3 s poll), single-flight per chat
(`POLL.enter/leave`), never while `document.hidden`.

## 14. Rungs and gates

**CHR0 — exact evidence snapshots on every successful assistant turn.** Gate: initial hits recorded;
`search_library` hits recorded; full-context chunks recorded; cited ⊆ shown; scope recorded; `question_message_id`
is the real user row id; `save_failure` and incomplete turns do not carry `evidence`; URL-only turns record a
zero-hit baseline; the answer text, citations, tools and Claims path are byte-for-byte unchanged (existing test
suites pass untouched).

**CHR1 — `conversation_delta.py`, `search_fts`, `conversation_delta_revision`, `GET
/api/conversations/{id}/delta`, plan-impact annotations.** Gate: scans every real user question including chats >
12 messages; ignores `meta.kind='refresh'` turns; a newly attached already-ready source surfaces; pending → ready
surfaces; a new Finding on an old source surfaces; a changed Claim surfaces; a contradiction sorts above a
corroboration; an irrelevant new source is counted but not "meaningful"; second read is a cache hit; unrelated job
churn does not invalidate; empty delta makes zero provider and zero embedding calls; `known=False` plan impact is
reported with `plan_impact`'s own reason.

**CHR2 — open-chat What's New UI.** Gate: no list badge; no poll work; single-flight; hidden document does not
launch the request; compact state first; Approximate copy for legacy chats; plan-impact section only when known.

**CHR3 — paid refresh through `answer.chat`.** Gate: refused (409) when the delta has nothing relevant; synthetic
user turn has `meta.kind='refresh'`; refresh turns are excluded from later topic extraction; the model receives
delta evidence + comparison passages, never arbitrary old corpus chunks; source/Claim changes on old sources are
eligible; no cross-project evidence; the resulting assistant turn gets a fresh exact snapshot; save/pin works; no
raw-answer-to-Claim path; no automatic plan mutation.

## 15. Decisions on record

- Kyle, 2026-09-18: refresh targets the **whole open chat**; refresh answers feed Claims **through the existing
  Finding path only** (§8); surface **inside the open chat only**; old chats get **Approximate** mode (§12).
- Out of scope, on purpose: auto-refresh without a click; nightly "refresh everything" (that is `delta.py` /
  the envelope mission); cross-project notification; retrieval ranking changes.

## 16. Execution record

### CHR0 — shipped, pushed (`11dcaf0`, `76eab50`)

`db.save_message` returns the new `messages.id`; `db.get_messages` exposes `id`; `db.conversation_baseline()` =
newest assistant row with `meta.evidence` and no `meta.incomplete`. `conversation_delta.evidence_snapshot()` builds
the block from the FINAL `ctx["hits"]` (initial retrieval + `search_library` additions + full-context chunks), the
resolved scope, the retrieval query, and the user row id; it also records `max_claim_evidence_id` and `claim_state`
(strength/freshness/status/application of every Claim whose evidence touches a shown source). Incomplete turns
write `meta.incomplete` and no `evidence`; `save_failure` unchanged; link-only turns write a zero-hit baseline.
Nothing about retrieval, prompting, ranking, Claims or the answer changed. Gate: `tests/test_chr0_conversation_baseline.py`.

**Hardening (2026-09-18, before CHR1 began, Kyle's correction):** `evidence_snapshot()` deliberately swallows a
failure while gathering `research_revision` or `claim_state` (a chat answer must never be lost over delta
bookkeeping) — but until this fix, a snapshot that failed partway still looked identical to a fully-gathered one.
Bumped to `SNAPSHOT_VERSION = 2`: the block now carries `complete: bool`, set to `False` the moment either gather
step raises. A pre-existing `v1` snapshot (no `complete` key — what `76eab50` actually shipped) is treated as
complete for backward compatibility; only an *explicit* `complete: False` downgrades a question to approximate
mode in CHR1 (§14's `_questions()`). What DID succeed (the shown chunks/sources, the scope, the query) is still
recorded and still used — only the claims that depend on the fields that failed (exact temporal/epistemic
"never seen"/"transitioned" statements) are withheld. Gate:
`test_incomplete_bookkeeping_marks_the_snapshot_not_complete`.

### CHR1 — implemented, NOT yet pushed (working tree only as of this record)

`search.search_fts()` — the FTS5-only leg of `search()`, factored out of a shared `_hits_from_ranked()` tail
(book-weighting, priority reservation, per-source cap, final sort) so the two entry points cannot drift; never
calls `embeddings.embed_query`, regardless of `settings.embeddings_enabled` or `settings.retrieval_rerank`.

`db.conversation_delta_revision(project_id)` — the narrow fingerprint (§11): real source membership (a hash of
`project_source_ids(pid, ready_only=False)`, not a count/timestamp approximation, because an old source attached
from the global library keeps its own old `created_at`), scoped sources' status/revision, `project_notes_revision`
(reused, not reinvented), Claims count+`MAX(updated_at)`, `MAX(claim_evidence.id)`, tensions, evidence targets, and
the current plan's identity. Does not read `jobs` or another project.

`conversation_delta.py` (CHR1 section) — **the per-question baseline fix Kyle required before CHR1 began**: the
delta is built from `_questions()`, which pairs every real user question (excluding `meta.kind="refresh"` turns)
with the assistant answer whose `evidence.question_message_id` points back to it (exact) or the next good assistant
row positionally (legacy/approximate) — never diffed solely against `conversation_baseline()`, so an early question
going stale is not hidden behind a later, unrelated turn that happens to postdate the new evidence.
`conversation_seen_chunk_ids()` unions `shown_chunk_ids` across every successful snapshot in the conversation
(epistemic newness); `conversation_last_known_claim_state()` folds `claim_state` chronologically. `delta_for_question()`
discovers candidates independently per category (newly-available sources → `search_fts`; new Findings →
`claims.overlap` routed at `OVERLAP_THRESHOLD=0.35`, measured on Kyle's corpus snapshot, §6 below; Claims touched by
source or by overlap, transitions judged against last-known state; new open tensions on a touched Claim; resolved
evidence targets) — never starting from "new source ids" alone. `_merge()` dedupes into one unit per
source/Finding/Claim/tension with `touches_questions`; `_attach_plan_impact()` calls `plan_narrative.explain()`
**read-only** (never `propose_updates()`, which writes pending rows) for contradiction/claim-transition units only.
`for_conversation()` returns `mode` (`exact`/`approximate`/`mixed`), `nothing_new`, `material_changes`,
`supporting_changes`, `irrelevant_new_source_count`, `plan_impacts`. `get_delta()` caches on
`(conversation_id, conversation_delta_revision(project_id))`. `GET /api/conversations/{id}/delta` — read-only.

**Overlap threshold, measured (not carried over from the first draft):** 10 real questions × 17,990 short Findings
(<500 chars) from Kyle's corpus snapshot (immutable copy, never the live db), bucketed by `claims.overlap`:
0.10–0.19: 14,318 · 0.20–0.29: 8,583 · 0.30–0.39: 1,501 · 0.40–0.49: 248 · 0.50+: 566. Manual read of samples: below
0.30 is dominated by shared domain vocabulary with no real topical link; at ≥0.40 a short, well-formed question
matches only genuinely on-topic Findings. A long, multi-clause recap-style question (common in Kyle's real chats)
biases overlap upward regardless of topic, because `overlap()` takes the share of the *shorter* passage's tokens —
a long question's huge vocabulary likely contains most of a short Finding's distinctive words by chance. Chosen:
`0.35`, the lowest value where the mixed 0.30–0.39 band is still mostly relevant, bounded by two things regardless
of threshold noise: Findings-overlap only routes the lowest-but-one panel category (never contradiction/plan-impact/
claim-transition, which are anchored to actual source/Claim touch), and `FINDINGS_PER_QUESTION_CAP=5` bounds
exposure per question. If real use floods "more supporting evidence", raise the threshold or normalize by question
length — not a redesign.

Gate: `tests/test_chr1_conversation_delta.py` (15 tests) — whole chat scanned beyond 12 messages with refresh
turns excluded; the per-question semantic fix itself (an early question's source surfaces through a later,
unrelated answer that alone wouldn't detect it); conversation-wide seen chunks never re-flagged as new; new Claim
evidence on an old source reports a transition from last-known state; contradiction ranks above corroboration;
`known=False` plan impact stays unknown (no plan exists); an irrelevant new source is counted, not material;
`nothing_new` makes zero provider/embedding calls; `search_fts` never calls `embed_query` even with embeddings
enabled; a second identical request is a cache hit; unrelated job churn does not move the revision; another
project's Claims/Findings cannot appear; a legacy conversation is approximate; a mixed old/new conversation reports
`mixed`; the delta endpoint smoke test (200 + expected shape, 404 for an unknown conversation).

Full suite: green (`test_chr0_conversation_baseline.py` 8/8, `test_chr1_conversation_delta.py` 15/15, `test_core.py`
and all `tchunk*` groups) apart from three pre-existing failures belonging to a concurrent lane's uncommitted
0.63.94 work in the tree (`test_p1b_tonight_ui`'s ui-version meta, `test_s68` ×2 reading `created_at` for
"added N ago") — unrelated to CHR0/CHR1.

**Not yet done:** `git commit` + push of CHR1. This document was corrected and re-verified on the device before
that commit, specifically so the pushed commit and this document agree from the start (the prior push, `11dcaf0`,
silently reverted to the first draft's content despite the commit message — see git history for the actual diff;
never trust a commit message here without re-reading the file after push).
