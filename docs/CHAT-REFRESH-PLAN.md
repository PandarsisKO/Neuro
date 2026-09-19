# Conversation Delta / Chat Refresh — plan

**Status (2026-09-18): CHR0 shipped. CHR1 shipped and closed at `308f9d3`. CHR2 in progress.** This is no longer a planning-only document.

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

**Relevance is a separate test from "did this change" (2026-09-18, Kyle's second correction, Approximate mode
only).** "Important to the project" is not automatically "important to this conversation." A Claim, contradiction,
or resolved evidence target can be judged **changed** (its own `updated_at`, an open tension, a closed target — all
provable, project-wide facts) without being judged **relevant to this chat** (connectable to what this conversation
actually discussed). Categories 1 and 4 above (`contradicts`, `resolves_gap`) and the rollup's own Claim-transition
promotion path (category 3, in Approximate mode) all gate on relevance before becoming an explicit unit — see §12
and §16's "Relevance gating" entry for the exact rule and why plan impact (category 2) does not by itself satisfy
it.

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

A chat with no `meta.evidence` on any assistant row (or one where CHR0's gather partially failed, `complete: False`):

- baseline = newest assistant row that is not `meta.incomplete`;
- the only known "seen evidence" is that row's (and earlier rows') `citations` source ids;
- post-baseline source / Findings / Claim / tension changes are inspected the same way;
- the panel **never** says "the model had not seen this" — it cannot be known.

Copy: *"Approximate refresh. This chat predates evidence snapshots, so Neuro can identify research that changed
after the answer, but cannot reconstruct every source or Claim state the original conversation had available."*
An approximate delta can still offer the paid refresh when concrete post-date relevant evidence exists. If real use
shows unacceptable noise, this one branch becomes "establish a new baseline first"; the feature is not redesigned.

**The Exact vs. Approximate honesty boundary, in one sentence (2026-09-18):** Exact mode has a real historical
`claim_state`/scope snapshot, so a fact like "this Claim's state was X when the answer was given, and is Y now" is
provable and used directly (§3's revision-diff, §6 category 3's `prev != cur` transition test), and its relevance
test may rest on that same historical record (a Claim touched by a source the snapshot proves was in scope).
Approximate mode has no such record — a legacy answer's `prev` state is **unknown**, not **absent** — so it never
manufactures a transition from `prev=None`, never infers "newly available" from mere absence in `shown_source_ids`
(a source not cited by an old answer may simply be one it had no reason to cite, not one that did not exist yet —
§3's `newly_available` computation uses `status='ready' AND updated_at>since` on the *current* scope instead), and
never treats broad same-project fan-out (any Claim whose evidence touches a scope-adjacent source) as proof that
*this conversation* cares about it. This is not a feature deficiency to be engineered away — it is the honest limit
of what a legacy chat's own message history can prove, and CHR2's copy should say so plainly rather than imply a
transition or a project-wide research total is something this specific chat learned.

## 13. UX (CHR2)

No chat-list badge (Kyle: open chat only). No new research dashboard inside the chat. One region between
`#chatHead` and `#chat` (`#chatDelta`), attached to the conversation header, never inserted as a fake assistant
message. Progressive disclosure:

```
✨ What's new
3 meaningful changes since Sep 14
```

**The request is NOT made once on every chat open — that was the pre-CHR2 placeholder rule, and it is wrong for
a large legacy conversation whose reconstruction measures ~12 s (§16.C).** The actual rule, decided during CHR2:

- **Exact chat** (every real successful assistant answer in the conversation has a complete `meta.evidence`
  snapshot, checked cheaply from the message rows `selectChat()` already loaded — no extra request just to find
  out): `GET .../delta` fires automatically, once, on open — `ack:false`, single-flight per conversation via
  `POLL.enter/leave('conversation-delta:<id>', ...)`, never while `document.hidden`, never part of `pollTick()`.
- **Approximate or mixed chat** (any real successful answer missing `meta.evidence`, or explicitly
  `complete: false`) and any legacy pre-CHR0 chat: **no automatic request.** A compact "✨ Check what's new ·
  Older chat · approximate check" affordance is shown instead; the expensive reconstruction runs only when the
  user clicks it, through the normal acknowledged `api()` call (not `ack:false`).
- An empty/new chat (no real assistant answers yet) gets no What's New UI at all.

Opening the compact card shows, in order and only the groups that exist:

- **Changes an earlier answer**
- **Could affect your Master Plan** — only when `plan_impact` returned `known=True` with items
- **Adds useful information**
- **More supporting evidence** — collapsed by default, includes rollups/`new_claims` aggregate counts and, for
  Approximate/mixed results, the `approximate_limitations` text (shown here, once, not as persistent pre-check
  clutter)

Empty-but-busy: *"Nothing important changed. 15 sources were added to the project, but none matched what this
conversation covered."* No project change at all: for an automatic Exact check, the temporary checking state
simply disappears — no persistent card. Legacy chat: the Approximate line, only after the user asks for it.

CHR3 (the paid "Refresh this chat" synthesis call) is out of scope for CHR2: Plan Impact is read-only display
here, and no dead "Refresh this chat" button is shipped ahead of it.

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

### CHR0 — shipped, pushed (`11dcaf0`, `76eab50`, folded into `da0b2d7` with CHR1's first cut)

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

### CHR1 — first cut shipped/pushed at `da0b2d7`; two hardening rounds (below) shipped/pushed at `7016f14` and `719f2f7`

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

`git show da0b2d7` is CHR0+CHR1's first cut as pushed. Everything below happened after that push, in review of the
first cut, and is implemented in the working tree only as of this record.

### CHR1 hardening pass, first round — shipped, pushed (`7016f14`)

**1. `qa.py` history-ordering fix.** `qa.ask()` fetched `history = db.get_messages(conversation_id, limit=12)`
*after* the current question was already saved, so `_retrieval_query()`'s "previous user message" lookup found the
question being answered instead of the true prior turn — a self-duplicated `retrieval_query` (`"What about
taxes?\nWhat about taxes?"`) and the current question appearing twice in the provider's messages (once via
`history`, once via the explicit question turn appended further down). Fixed by moving the `history` fetch to
before the save block; the later duplicate fetch was removed. This is a production correctness bug independent of
Conversation Delta — it affected every follow-up question's grounding and every provider call's message list — and
CHR1's own retrieval-query routing (§3, §6) depends on `retrieval_query` being correct, so it had to be fixed before
CHR1's own hardening could be trusted. Gates: `tests/test_k_retrieval_fixes.py` (first-question `retrieval_query`
not duplicated; a contextual follow-up grounded by the true prior turn, not itself; the provider sees the current
question exactly once; a link-only early return still records the real question and a zero-hit snapshot),
`tests/test_s24_lost_chat_and_fk.py` (an exception between history-fetch and provider call still leaves the
question saved).

**2. Two measured performance fixes** (`for_conversation`/`delta_for_question`, real-corpus cold-path measurement —
see below): (a) `_max_claim_evidence_id_at()` was being recomputed once per touched Claim (a loop-invariant SQL
query re-run ~16k times for one early question on Kyle's real corpus, >170s alone) — hoisted out of the loop, with
the per-claim "has new evidence" check batched into chunked `IN()` queries (`_CE_CHUNK=500`). (b)
`_attach_plan_impact()`'s `plan_narrative.explain()` was called once per candidate unit (~335ms/call, because
`decision_impact()`'s `_plan_cited_note_ids()` reloads and JSON-parses every one of the project's Findings on every
call, uncached) — restructured so `decision_impact()` runs **once per conversation** (not once per question) on the
union of every question's candidate Claim ids, `explain()` is called only for the `plan_impact=True` subset, and an
"unknown" plan-impact reason is resolved once for the whole batch via a single `plan_impact.affected_items()` probe.
Together these took one real legacy chat from 90+ minutes cold to single-digit seconds.

**3. Approximate mode's `newly_available` formula corrected.** The original `current_scope - shown_source_ids` is
not a valid inference — "not shown by the old answer" is not "added after the old answer"; a legacy chat may have
cited 5 of 1,072 already-existing sources. Fixed to the only honest legacy signal: which of the *current* scope's
sources can be proven to have moved (`status='ready' AND updated_at>since`) after this question's `answered_at` —
the same fallback exact mode already uses for an in-scope source with no recorded revision (§3). A source added to
the project after the answer but never modified afterwards remains a real, acknowledged miss for Approximate mode
(§12's honesty boundary); Exact mode does not have this gap, because `scope_source_ids` proves project membership
at answer time directly.

**4. `prev=None` semantic fix + the rollup unit (Approximate mode).** The original code read `prev != cur` as a
Claim transition in *both* modes. In Exact mode this is correct — the baseline's `claim_state` snapshot is real, so
`prev=None` means "the conversation's baseline predates this Claim's own creation," a genuine transition. In
Approximate mode a legacy answer carries no `claim_state` snapshot at all, so `prev=None` means **unknown**, not
"absent" — treating it as a transition turned ordinary post-baseline project activity (on Kyle's real corpus,
often ~90% of a mature project's whole Claim table) into thousands of individual `claim_transition` units per
question. Approximate mode no longer compares `prev`/`cur` at all. Instead: every Claim touched-or-overlapping a
question (`touched`) that changed since the baseline (`candidate_ids`, i.e. `changed_claim_ids` for that question)
goes into a `rollup` unit — a `kind="rollup"` object carrying id *sets* (`rollup_source_ids`, `rollup_claim_ids`,
`rollup_claim_evidence_ids`, plus the full candidate row dicts and, since the relevance-gating fix below,
`relevant_claim_ids`) instead of a per-claim narrative. Rollup units are filtered out of `all_units` before
`_merge`/`_attach_plan_impact`/sort and aggregated separately in `for_conversation()`, via **set union across every
question** (so a Claim touched by three questions counts once), into the response's `rollups` block:
`{sources_changed, findings_added, claims_added_or_updated, claim_evidence_added}` (`findings_added` computed by a
single bulk query over `project_notes` for the earliest Approximate `answered_at`, minus ids already explicit). The
counts are **never silently discarded**: `nothing_new` is `False` whenever any rollup count is non-zero even if
`material_changes`/`supporting_changes` are both empty. Only one Claim-level signal is strong enough to survive
Approximate mode's honesty limit and get promoted out of the rollup into an explicit `claim_transition` unit
directly: `decision_impact()`-proven Master Plan citation — called once per conversation on the union of every
rollup's candidates (not once per question, for the same reason as fix 2). As of the relevance-gating fix below,
that promotion additionally requires the Claim to be independently relevant to that specific question (plan impact
alone is not conversation relevance — see next entry). Gates:
`test_approximate_mode_rolls_up_unproven_claim_churn_instead_of_flooding_material_changes`,
`test_approximate_mode_plan_impacting_claim_still_surfaces_explicitly` (`tests/test_chr1_conversation_delta.py`).

**5. Relevance gating for `contradicts` and `resolves_gap` (Approximate mode) (2026-09-18, Kyle's second
correction).** Fix 4 stopped ordinary Claim churn from flooding `material_changes`, but `contradicts` and
`resolves_gap` still used the full `touched` set (built from `touch_sources = shown_source_ids | newly_available`,
i.e. source-touch fan-out, unioned with topical-overlap matches) as their relevance proxy — "never aggregate a
contradiction or resolved gap" had been read as "never filter one by relevance either," which let a real but
project-wide contradiction or resolved research question (reached only via a brand-new, never-cited source) get
reported as if this specific legacy conversation had learned it. Kyle's correction: *"important to the project is
not automatically important to this conversation... A contradiction can be extremely important to the project and
still have nothing to do with the conversation I opened."* `touched` (source-touch-or-overlap union, used for
*what changed*) is now split from a narrower `relevant_claim_ids` (used for *what's connectable to this question*,
Approximate mode only) built from exactly two deterministic signals: (1) the Claim's evidence touches a source
`shown_source_ids` — i.e. a source **this old answer demonstrably cited/saw** (not the wider `touch_sources`, which
also includes brand-new sources the old answer could never have seen); (2) the Claim's own text passes
`claims.overlap(retrieval_query, claim.text) >= OVERLAP_THRESHOLD` against the same grounded `retrieval_query`
`§3`/`§6` already use elsewhere (never the raw follow-up text — a short "What about taxes?" is grounded through the
prior turn before this test runs). Plan impact is deliberately **not** a third signal into `relevant_claim_ids` —
*"Plan impact increases the importance of a relevant change. It does not establish conversation relevance by
itself"* — so fix 4's promotion path now intersects `plan_true_ids` with the *same question's* `relevant_claim_ids`
before promoting a rollup candidate to an explicit `claim_transition`. `resolves_gap`'s existing gate
(`tgt["claim_id"] not in <relevant set> and overlap(retrieval_query, tgt["question"]) < THRESHOLD → skip`) needed
one further correction while implementing this: a target with **no** `claim_id` at all was previously included
unconditionally (the `and`-chain short-circuited on the falsy `claim_id`), which is the identical bug in miniature
— fixed so a claim-less target must independently pass the topical test on its own question text. Exact mode is
untouched by any of this — its `touched_for_tensions` stays the full `touched` set, because a real historical
scope/claim_state snapshot is already a stronger relevance signal than either of Approximate mode's two proxies,
and narrowing it further would weaken a mode that does not have Approximate mode's honesty gap. Gates (all in
`tests/test_chr1_conversation_delta.py`, prefixed `test_gate<N>_...`): (1) an unrelated contradiction is not
material; (2) a contradiction on a Claim whose text matches the retrieval query is material even from an
uncited source; (3) a contradiction on the cited source is material despite weak text overlap; (4) an unrelated
resolved target (no claim, no text overlap) is not material; (5) a resolved target whose question matches the
retrieval query is material; (6) a resolved target linked to an independently-relevant Claim is material despite
weak target-text overlap; (7) a plan-impacting-but-unrelated Claim does not become explicit solely because it
affects the Plan; (8) Exact mode's contradiction/resolved-gap behaviour is unchanged (still ungated by relevance).

**Real-corpus measurements, after all of the above** (Kyle's project `c752ed152ec942dd97b9a94c3f1b3b96` — 1,072
sources, ~17.6k Claims, ~19.5k Findings; snapshot via the immutable copy discipline, never the live db):

| conversation (real, Approximate mode) | cold `for_conversation` | material_changes | supporting_changes | `contradicts` | `resolves_gap` | `new_finding` | explicit unique Claims | `decision_impact`/`affected_items`/`explain` calls | response JSON |
|---|---|---|---|---|---|---|---|---|---|
| 3 questions  | 3.74 s  | 32  | 29  | 2  | 27  | 3 | 26  | 2 / 1 / 0 | 49.8 KB |
| 10 questions | 5.33 s  | 328 | 99  | 48 | 255 | 25 | 267 | 2 / 1 / 0 | 1.30 MB |
| 14 questions (largest real) | 12.78 s | 401 | 128 | 25 | 370 | 6 | 328 | 2 / 1 / 0 | 495 KB |

Before fix 5 (relevance gating), the same three conversations reported `material_changes` of 1,585 / 612 / 1,744 —
this pass's relevance gate is what drives the material_changes columns above down to 32 / 328 / 401 (`resolves_gap`
is the majority of what remains and is now genuinely gated by relevance, not source-fan-out membership; a
follow-up count without the doc's manual spot-check of that specific bucket has not been done and is a candidate
for the next review, not assumed clean). `rollups` (not shown in the table — aggregate, not enumerated) stayed in
the thousands-to-tens-of-thousands range across all three (e.g. 14q: `sources_changed=830, findings_added=16992,
claims_added_or_updated=14265, claim_evidence_added=14264`) — an honest reflection of a project that has grown
roughly 300x in scope since these chats' answers, reported as a count, never enumerated as individual units.

**Cold time did not improve materially from fix 5** (12.78s for 14q vs. ~13.0s before it — expected, since fix 5 is
a correctness/relevance change, not a performance one, per Kyle's "do not add another semantic shortcut simply to
hit a latency number"). Profiling the 14q cold path (`cProfile`, `tests`/measurement script against the immutable
snapshot) shows the dominant cost has moved: `_touched_claims_for_sources()` — now called **twice** per question
(once for the broad `touch_sources` set, once for the narrower `shown_source_ids` set that fix 5's
`relevant_claim_ids` needs) — accounts for ~7.1s of the 13.1s total (~54%), almost entirely `fetchall()` time on
large `IN (...)` joins against `claim_evidence`/`project_claims` when `touch_sources` is large. `decision_impact()`
(already batched to 2 calls/conversation) and `search_fts` (14 calls, one per question) are both well under 1s each
and are not the next hotspot. **Not yet acted on** — this is a measurement to hand back for a decision, not an
optimization made unilaterally: the second `_touched_claims_for_sources()` call (for `shown_source_ids`) could
likely be satisfied by filtering the *existing* `touched` dict in memory for claims whose evidence touches
`shown_source_ids` (avoiding a second DB round-trip) since `shown_source_ids ⊆ touch_sources` always holds, but
that changes the meaning of the check subtly enough (a claim can be *in* `touched` via `newly_available`-sourced
evidence for one row and via `shown_source_ids` evidence for another — an in-memory filter over `_touched_claims_for_sources`'s
returned rows does not distinguish which source id matched) that it needs sign-off rather than a silent swap.

Full suite (`tests/test_chr0_conversation_baseline.py` 8/8, `tests/test_chr1_conversation_delta.py` 32/32 including
the 8 new relevance gates, `tests/test_k_retrieval_fixes.py` + `tests/test_s24_lost_chat_and_fk.py`, `test_core.py`
+ all `tchunk*` groups): green, apart from the same three pre-existing failures already on record above as
belonging to a concurrent lane's uncommitted 0.63.94 UI work (`test_p1b_tonight_ui`'s hardcoded `ui-version` meta
value, `test_s68` ×2) — confirmed unrelated: none of those three tests touch `conversation_delta.py`, `qa.py`, or
any file this pass changed.

### CHR1 hardening pass, second round — shipped, pushed (`719f2f7`)

Kyle's review of `7016f14` found three further correctness problems, all in `conversation_delta.py`'s Exact-mode
and target-resolution logic, none of which the first round's relevance gate had touched.

**A. `resolves_gap`'s target-status query was factually wrong.** `status<>'open'` treated `dropped` (used for
dedup/tension cleanup — not evidence Neuro produced) and `closed_by_user` (a user action) as "resolved," alongside
the one status that actually means it: `satisfied`. `resolves_gap` now queries `status='satisfied'` only. A second,
subtler issue: even `status='satisfied' AND updated_at>since` does not PROVE a target transitioned open→satisfied
after the answer — a target satisfied long ago can have unrelated fields (gap notes, `current_evidence`) touched
later without ever re-opening, which would keep bumping `updated_at`. Bumped the evidence snapshot to **v4**: it
now records `open_evidence_target_ids` (every target that was `status='open'` at answer time, one batched query) so
Exact mode can PROVE a resolution — target open in this question's own baseline AND satisfied now — instead of
inferring one from a timestamp. A target created after the answer and satisfied since is provable without any
baseline at all (the whole gap-and-resolution event happened after the baseline), so that path works even for a
v1-v3 Exact snapshot or Approximate mode, which have no target-state bookkeeping at all; anything else in those
older/Approximate cases is conservatively omitted rather than guessed from `updated_at`. On the real corpus this
was a material contributor: `resolves_gap` for the 14-question legacy chat dropped from 370 to 69 (3q: 27→14, 10q:
255→26) — a meaningful share of what remained after the first relevance-gate round was `dropped`/`closed_by_user`
targets being reported as "resolved research questions." Gates (`tests/test_chr1_conversation_delta.py`,
`test_gateA1`-`test_gateA6`): a `dropped` target after baseline is not `resolves_gap`; `closed_by_user` is not
`resolves_gap`; a target open in a v4 baseline and satisfied afterward IS `resolves_gap`; a target already
satisfied before the baseline but touched afterward is NOT newly resolved; a target created and satisfied after an
Exact baseline IS `resolves_gap`; an Approximate/pre-v4 baseline never fabricates a resolution from `updated_at`
alone.

**B. Exact-mode Claim transitions could be silently erased by a later question's own snapshot.** The comparison was
`prev = last_known_claim_state.get(cid) or q["claim_state"].get(cid)` — `last_known_claim_state` is the LATEST
state seen anywhere in the whole conversation, folded chronologically across every question's snapshot. If Q1 knew
state A, the Claim changed to B, and a LATER question Q2 happened to also see (and snapshot) state B, then Q1's own
delta computation would compare B against B and the real A→B transition Q1 should report would silently vanish —
exactly the whole-chat-baseline mistake CHR1's per-question design exists to prevent, reintroduced one level down.
Fixed: the comparison now uses ONLY `q["claim_state"].get(cid)` — THIS question's own recorded prior state — never
`last_known_claim_state`, which is now used solely as an annotation (`already_seen_elsewhere_in_chat`: did some
other turn in this chat already record this same resulting state?) that can never suppress the unit itself. A
related correction: `prev=None` does not necessarily mean "the conversation's baseline predates the Claim's own
creation" — it may simply mean THIS answer's own snapshot never captured the Claim (e.g. it becomes relevant only
now, via a newly-available source's FTS hit or topical overlap). A transition needs two known states to compare;
fabricating "changed from None" overstated what's actually known. `prev=None` now produces a `new_claim` unit
("newly relevant to this answer," `previous_state: null`) instead of a fabricated `claim_transition`. `new_claim`
sorts as supporting evidence (`CATEGORY_ORDER` position 7, alongside `corroborates`), never material — it is not a
proven change, just a real new connection. Gate: `test_gateB_earlier_questions_claim_transition_is_not_erased_by_a_later_questions_snapshot`
(A recorded for Q1, Claim changes to B, Q2 later re-snapshots B, whole-chat delta still reports Q1's A→B
transition with `previous_state==A`); `test_new_claim_created_after_baseline_reports_new_claim_not_a_fabricated_transition`
(existing test renamed and re-asserted for the new category).

**C. Exact mode had the identical over-broad relevance problem Approximate mode had, one round earlier.** The first
relevance-gating round (Kyle's second correction) deliberately left Exact mode's `touched_for_tensions` as the
full, unfiltered `touched` set — reasoned at the time as "a real historical snapshot is already a stronger
signal." Kyle's review corrected this: `touched` in Exact mode was still built from
`touch_sources = shown_source_ids | newly_available`, so *every* Claim attached to *every* newly-available source
became eligible for contradictions/transitions/resolved gaps, whether or not that source (or Claim) had anything
to do with the question — "important to the project is not automatically important to this conversation" applies
to Exact mode too. `relevant_claim_ids` is now computed uniformly for BOTH modes (the mode-specific duplication
from round one is gone) from: (1) evidence touching `shown_source_ids` (both modes); (2) **Exact mode only** —
membership in this answer's own recorded `claim_state`, a real historical fact and the reason a historically-known
Claim remains relevant even with weak lexical overlap; (3) evidence touching a newly-available source that
produced an ACTUAL FTS hit for this question's `retrieval_query` (both modes — mere membership in `newly_available`
does not count, only a source that is provably topically relevant to this exact question); (4) the Claim's own
text passing the topical-overlap test (both modes). `touched` (the broader, "changed" set) is now used only where
Kyle's §5 separation intends it — the Approximate rollup's aggregate counts and the Exact claim-transition scan's
candidate pool — never as the relevance test itself, in either mode. Exact mode is not weakened by this: signal
(2) is unconditional (no overlap test needed) and strictly stronger than anything Approximate mode has. Gates:
`test_gateC1` (an unrelated newly-attached source's unrelated Claim's contradiction does NOT surface),
`test_gateC2` (the same shape, but the new source produces an actual FTS hit for this question — the contradiction
DOES surface), `test_gateC3` (a Claim whose text matches the retrieval query surfaces even via an unrelated new
source), plus the existing `test_gate3`/`test_gate8`-family tests (a historically-cited-source Claim surfaces
despite weak text overlap) confirming the historical signal still holds.

**D. `new_excerpt` silently discarded evidence that a LATER question in the same chat had also shown.** The
`if h["chunk_id"] in conversation_seen: continue` line used `conversation_seen_chunk_ids()` — the whole-chat union
of every successful snapshot's shown chunks — as an exclusion filter. That is the same whole-chat-baseline mistake
again: a chunk absent from THIS question's own snapshot is a genuine post-baseline change relevant to THIS
question, even if a later question in the same chat happened to also surface it (e.g. evidence that would have
changed Q1's answer, which Q2 — asked afterward — separately picked up). Fixed to annotate
(`already_seen_elsewhere_in_chat: bool`) instead of dropping. Gate:
`test_gateD_new_excerpt_seen_later_in_chat_still_associates_with_earlier_question` (a chunk absent from Q1,
introduced after Q1, shown again in a fabricated Q2 snapshot — the whole-chat delta still reports it against Q1,
annotated as seen elsewhere, never silently removed).

**Real-corpus re-measurement, after A-D** (same three real legacy conversations, immutable snapshot):

| conversation (real, Approximate mode) | cold `for_conversation` | material_changes | supporting_changes | `contradicts` | `resolves_gap` | `new_finding` | explicit unique Claims | response JSON |
|---|---|---|---|---|---|---|---|---|
| 3 questions  | 3.77 s  | 33  | 29  | 16 | 14 | 3  | 19 | 55.1 KB |
| 10 questions | 5.33 s  | 110 | 99  | 59 | 26 | 25 | 66 | 589 KB |
| 14 questions (largest real) | 12.75 s | 160 | 128 | 85 | 69 | 6  | 94 | 318 KB |

`resolves_gap` fell sharply as predicted (14q: 370→69, 10q: 255→26, 3q: 27→14) — fix A's status filter was indeed
the dominant contributor Kyle suspected. `contradicts` rose somewhat (14q: 25→85) for a legitimate reason, not a
regression: `relevant_claim_ids` gained a real new signal in this round (the FTS-hit-source route, C.3 above) that
applies to Approximate mode too, surfacing genuinely relevant contradictions the previous round's narrower signal
set missed. Cold time is essentially unchanged (12.75s vs 12.78s for 14q) — expected, this round was correctness,
not performance; the profiled hotspot is unchanged too, `_touched_claims_for_sources()` still ~55% of cold time
(now called up to 3x per question instead of 2x, since C added a third call for `fts_hit_source_ids` when
newly-available sources produced hits — a small, News-driven addition, not the dominant driver).

**Synthetic Exact-mode benchmark, re-run after A-D** (throwaway `tempfile.mkdtemp()` data dir, 300 sources + 3,000
Claims seeded, then another 300+3,000 after each conversation to simulate growth — never the live db or the
snapshot):

| conversation | cold `for_conversation` | material_changes | supporting_changes |
|---|---|---|---|
| 3 questions  | 118 ms | 0 | 3,012 |
| 10 questions | 316 ms | 0 | 3,012 |
| 14 questions (largest real shape) | 539 ms | 0 | 3,046 |

**A new finding from this benchmark, reported rather than acted on:** all ~3,000 `supporting_changes` in each row
are individual `new_claim` units, not an aggregate. This is a synthetic worst case by construction (every seeded
Claim's text is built to topically match the seeded question, so all ~3,000 post-growth Claims pass the topical-
overlap signal and are legitimately "new to this answer" per fix B), and there are currently zero real Exact-mode
conversations in Kyle's corpus to check this against (all 47 real conversations predate CHR0). But the underlying
gap is real: Exact mode's `new_claim` category has no rollup/aggregation analog to Approximate mode's — every
`new_claim` becomes its own explicit unit, unbounded, unlike `claim_transition`/`contradicts`/`resolves_gap`, which
stay individually enumerated by design because they are each a proven, specific signal. Whether a mature Exact-mode
project could produce thousands of legitimately-topical `new_claim` units the same way a legacy Approximate chat
produced thousands of ordinary Claim churn is untested against real data and not fixed here — flagged for CHR2
review rather than addressed now, per "do not add another semantic shortcut simply to hit a latency number" (this
is a volume/response-size question, not a latency one, and Exact mode has no real-corpus traffic yet to measure it
against).

**CHR2 latency recommendation (Kyle's part E — a product decision, not implemented here):** cold time for the
largest real (Approximate) legacy chat remains ~12.75s after two full correctness passes; the dominant cost
(`_touched_claims_for_sources()`, ~55%) is a measured, reported, NOT-yet-acted-on finding (see the first hardening
round's profiling entry above) that needs sign-off, not a latency target to chase blindly. Recommendation: Exact
chats (small, cache-friendly, no historical reconstruction needed) can run Conversation Delta automatically on
chat open; legacy Approximate chats — cold, multi-second, and reconstructing history that was never recorded —
should probably get a lazy "Check what's new" action instead of an automatic foreground computation on open. This
is offered as input to a CHR2 design decision, not implemented in CHR1: CHR2 owns the question of when the delta
computation actually runs.

Full suite re-run after A-D: `tests/test_chr0_conversation_baseline.py` 8/8, `tests/test_chr1_conversation_delta.py`
43/43 (32 from the first round + 11 new gates: A1-A6, B, C1-C3, D), `tests/test_k_retrieval_fixes.py` +
`tests/test_s24_lost_chat_and_fk.py`, `test_core.py` + all `tchunk*` groups — green, apart from the same three
pre-existing, unrelated failures on record above. Pushed as `719f2f7`.

### CHR1 hardening pass, third round — final correction pass before CHR2 (2026-09-18, review of `719f2f7`)

Kyle's review of `719f2f7` found two remaining correctness problems (both caught by his own reading of the C2 test
and the synthetic benchmark's raw numbers), plus a documentation-currency fix. Explicitly scoped as the LAST CHR1
correction pass — CHR2 review follows this, not another hardening round.

**1. Relevance signal 3 (the FTS-hit-source route) leaked from source-level to Claim-level.** The rule was "a
newly-available source produced an FTS hit for this question → every Claim with evidence on that source is
relevant." That is one level too coarse: a source can cover many topics, so a genuinely on-topic source hitting FTS
does not make an unrelated Claim on that same source relevant — caught directly by `test_gateC2`'s own fixture (a
seller-financing source's FTS hit made an unrelated microphone-brand Claim's contradiction surface). Fixed:
relevance via this route now requires the Claim to have its OWN `claim_evidence.excerpt` on the hit source that
itself overlaps the question's `retrieval_query` (`claims.overlap(retrieval_query, excerpt) >= OVERLAP_THRESHOLD`)
— the narrowest existing seam, no fuzzy locator-to-chunk reconstruction attempted (not needed; can revisit only if
measurement ever proves this insufficient). Historical relevance (signals 1 and 2 — `shown_source_ids` touch and
Exact mode's `claim_state` membership) is unchanged. `test_gateC2` was split into two gates matching Kyle's
instruction: `test_gateC2a` (FTS-relevant source + an unrelated Claim whose own evidence excerpt does not overlap
the query → does NOT surface) and `test_gateC2b` (same source-discovery shape, but the Claim's own evidence excerpt
IS on-topic even though the Claim's own text wording is weak/generic → DOES surface) — making source-level
discovery and Claim-level relevance two independently-tested things instead of one conflated gate.

**2. `already_seen_elsewhere_in_chat` could be trivially true against a question's own snapshot.**
`conversation_last_known_claim_state()` folds `claim_state` across every assistant row in the WHOLE conversation,
including the very row being evaluated — so a single-question conversation's own transition would fold its own
post-change state into "known," then compare it against itself and always report `already_seen_elsewhere_in_chat:
true`, even though nothing else in the chat actually saw it. `already_seen_elsewhere_in_chat` is annotation-only
(never gates whether the transition surfaces — that principle from the second round is unchanged), but an
annotation that lies is still a bug. Fixed: `conversation_last_known_claim_state()` now takes an optional
`exclude_message_id`, and `for_conversation()` calls it once PER question, excluding that question's own
`answer_message_id`, so "elsewhere" means what it says — another successful answer in this conversation, never this
one. Gates: `test_gateE1` (a single-question conversation's own transition is never flagged seen-elsewhere) and
`test_gateE2` (the existing two-question scenario, now explicitly asserting the flag IS true when a later question
independently re-records the same state).

**3. Exact mode's `new_claim` category had no bound — the output-contract half of Kyle's second-round finding.**
The synthetic benchmark had already surfaced ~3,000 individual `new_claim` objects in a worst-case scenario; the
semantic category was correct (a Claim newly relevant to an earlier answer with no provable prior state IS real,
low-priority information) but the output contract was not — an automatically-opened Exact chat should never receive
a 3,000-object payload for the category that matters least. Applied the same progressive-disclosure principle
already used for the Approximate rollup: after `_merge()` produces the final, deduped `new_claim` population (one
unit per Claim across every question that found it, `touches_questions` already accumulated), rank deterministically
— (1) strongest overlap between `retrieval_query` and the Claim's own text (a new `overlap_score` field, computed
once at unit-creation time, purely a ranking signal — relevance itself was already decided before this unit was
created), (2) number of questions touched, (3) `claim_id` as a stable tie-break — keep the top `NEW_CLAIM_EXPLICIT_CAP
= 5` as explicit units, and report a new top-level `new_claims: {"total": N, "shown": min(N, 5)}` field (`None` when
no `new_claim` units exist). The strong categories (`contradicts`, `plan_impact`, `claim_transition`, `resolves_gap`,
`new_finding`) are completely untouched by this mechanism — it filters `merged` by `category == "new_claim"`
specifically, nothing else. Gates: `test_gateF1` (a 20-candidate population caps at 5 explicit units, `new_claims`
reports the exact total of 20); `test_gateF4` (two independent calls produce the identical explicit sample in the
identical order — deterministic, not insertion-order-dependent); `test_gateF5` (`nothing_new` stays `False` when
the only new information is a handful of rolled-up `new_claim`s, none of which happen to be individually visible
beyond the cap); `test_gateF6` (8 independently-relevant contradictions all surface — none capped, proving the
mechanism is scoped to `new_claim` alone); `test_gateF7` (`new_claims.total` exceeds `new_claims.shown` once the
population exceeds the cap, so CHR3 can always tell there's more than what it's holding).

**Re-measurement.** Real corpus (same three legacy conversations; item 1's tighter relevance signal reduced
`contradicts`/`resolves_gap` further on top of the second round's numbers):

| conversation | cold | material_changes | supporting_changes | `contradicts` | `resolves_gap` | `new_finding` |
|---|---|---|---|---|---|---|
| 3 questions  | 3.69 s  | 7  | 29  | 2  | 2  | 3 |
| 10 questions | 5.28 s  | 91 | 99  | 49 | 17 | 25 |
| 14 questions (largest real) | 12.60 s | 84 | 128 | 25 | 53 | 6 |

Synthetic Exact-mode benchmark, re-run with all three fixes (same 300-source/3,000-Claim seed-and-grow methodology,
throwaway `tempfile.mkdtemp()` — never the live db or the snapshot):

| conversation | cold | material_changes | supporting_changes | `new_claims.total` | `new_claims.shown` | response JSON |
|---|---|---|---|---|---|---|
| 3 questions  | 113 ms | 0 | 17 | 3,000 | 5 | 12.1 KB |
| 10 questions | 401 ms | 0 | 17 | 3,000 | 5 | 22.1 KB |
| 14 questions | 629 ms | 0 | 51 | 3,000 | 5 | 43.3 KB |

Before this round's fix 3, the same synthetic conversations returned `supporting_changes` of 3,012/3,012/3,046 and
a proportionally sized JSON body (megabytes at true worst-case scale); now the response body is bounded regardless
of how many Claims are legitimately newly-relevant — a mature Exact-mode project cannot flood an automatically-run
chat-open request. Cold latency for the synthetic benchmark is unaffected by this round (unchanged from the second
round's numbers within noise) — as expected, this was a response-size fix, not a latency one.

**4. Legacy Approximate latency — recorded, deliberately not touched this round.** Largest real legacy chat cold
time remains ~12.6s; the dominant cost (`_touched_claims_for_sources()`, still the majority of cold time across all
three hardening rounds) remains a measured, reported finding awaiting sign-off, not something optimized speculatively
here. Kyle's product recommendation for CHR2 is recorded rather than implemented in CHR1: Exact chats run
Conversation Delta automatically on chat open; Approximate legacy chats get a lazy, user-triggered "Check what's
new" affordance instead of an automatic multi-second foreground computation — no chat-list badge, no polling. CHR2
owns implementing this split.

Full suite after this round: `tests/test_chr0_conversation_baseline.py` 8/8, `tests/test_chr1_conversation_delta.py`
51/51 (43 from the second round, net +8: `test_gateC2a`/`test_gateC2b` replacing the old `test_gateC2`,
`test_gateE1`/`test_gateE2`, `test_gateF1`/`test_gateF4`/`test_gateF5`/`test_gateF6`/`test_gateF7`),
`tests/test_k_retrieval_fixes.py` + `tests/test_s24_lost_chat_and_fk.py`, `test_core.py` + all `tchunk*` groups —
green, apart from the same three pre-existing, unrelated failures on record throughout this document.

**CHR1 is closed as of this round**, per Kyle's exit criteria: targeted and full suites green; Exact-mode synthetic
response size is bounded; `new_claims.total` remains exact even when capped; Claim relevance no longer leaks from
an FTS-relevant source to an unrelated Claim; this document's status lines agree with what's actually on GitHub.
CHR2 begins from the product rules recorded in this round's item 4, plus §13's existing UX sketch: compact summary
first, progressive disclosure, supporting/new-Claim rollups collapsed, no chat-list badge, no polling, Plan Impact
read-only until an explicit user action.
### CHR2 — open-chat What's New UI (this round, not yet pushed)

Implements §13 exactly as revised in item 0 above: `#chatDelta` between `#chatHead` and `#chat`
(`neurosearch/web/index.html`); the Exact-vs-legacy preflight, both loaders, and all rendering in
`neurosearch/web/js/chats.js`; a handful of new CSS rules reusing existing tokens/classes in
`neurosearch/web/styles.css`. No new frontend framework, state manager, or polling system — `state`, `api`, `POLL`,
`NSACK`, `listState` and the existing `<details>`/`.chip`/`.card` disclosure conventions are all reused as-is.

**Preflight (item 2).** `chatDeltaMode(ms)` classifies the conversation from the message rows `selectChat()` already
loaded, no extra request: every real successful assistant answer (non-empty content, not `meta.incomplete`) must
carry a `meta.evidence` object with `complete !== false`, or the chat is `'legacy'`; no real assistant answers at
all is `null` (no What's New UI). This mirrors `conversation_delta._questions()`'s own exact/approximate test
exactly, so the UI's guess about mode always agrees with what `/delta` would actually compute.

**Automatic Exact check (item 3) / lazy Approximate affordance (item 4).** One loader, `loadChatDelta(id, quiet)`,
serves both: `quiet=true` is the automatic path (`api(path, {ack:false})`, no `NSACK` acknowledgement, exactly
`loadJobs`/`loadSources`'s existing convention); `quiet=false` is the user's own click on the "✨ Check what's new"
affordance (a normal acknowledged `api()` call). Both are single-flight via the SAME `POLL.enter('conversation-delta:
<id>', quiet)` / `POLL.leave(...)` primitive every other background refresh in this app already uses — no second
coalescing mechanism. A loading state only appears after a short delay for the (already-launched) automatic check,
so a normal few-hundred-ms response never flashes one.

**Hidden-document guard (item 12).** `document.hidden` is checked once, at schedule time; a hidden Exact chat sets
one `CHATDELTA.pendingAuto`, fired once by a single `visibilitychange` listener when the tab becomes visible again
— no periodic watcher, and only if that pending chat is still the open one.

**Stale-UI prevention (item 11).** `selectChat()` calls `clearChatDelta()` on every entry, before doing anything
else, and re-checks `state.conv === id` both after the (possibly slow) message fetch and again when a `/delta`
response lands, so a response for a chat the user has since left is never painted. `ask()` calls `clearChatDelta()`
immediately after a new answer renders — no automatic recompute; the next `selectChat()` of that conversation
computes fresh.

**Rendering (items 5-10).** One compact card first (`renderChatDelta`): a one-line summary, a quiet "· Approximate"
tag when the mode isn't exact, nothing else — click (or Enter, it's a `role="button"`) to expand. Expanded content
groups `material_changes` into the three named priority groups in order — "Changes an earlier answer", "Could
affect your Master Plan" (only when `plan_impacts` actually has known items with content — never an empty warning),
"Adds useful information" — then a separate `<details>` (collapsed by default) for supporting evidence: explicit
`new_excerpt`/`corroborates`/`new_claim` rows, `new_claims.total - shown` as one sentence, `rollups` as one
aggregate sentence (never expanded into per-item rows), and `approximate_limitations` text once, only here. Every
row uses only user-readable fields (`why_relevant`, Finding/excerpt text, Plan Impact `why`/`label`) — no
`overlap=`, `claim_id=`, or raw `previous_state` ever reaches the DOM. `already_seen_elsewhere_in_chat` renders as a
quiet inline annotation, never a suppression. A group over 8 items shows the first 8 with a "Show N more" control
that reveals the rest in one click (the remainder sits in a `hidden` sibling, not truncated/dropped).

**Empty states (item 10).** Truly nothing (`nothing_new` and no `irrelevant_new_source_count`): the automatic
Exact check's temporary "Checking…" state clears to nothing, no persistent card; the lazy Approximate click still
gets one quiet acknowledging line. Busy-but-irrelevant (`nothing_new` true but sources changed): the compact card
renders the existing "Nothing important changed. N sources were added or changed, but none matched what this
conversation covered" copy.

**CHR3 stayed out (item 13/18).** No synthesis call, no Refresh endpoint, no Claim/plan mutation path — Plan Impact
is read-only display sourced straight from CHR1's already-computed `plan_impacts`; no product surface today has an
explicit "review this plan impact" action to link to, so none is added.

**Gates (item 15, all 18).** A new harness, `tests/js/run-chat-delta.mjs`, runs the SHIPPED `api.js`+`chats.js` in
jsdom against a scripted `uiFetch` — same technique as `run-poll-containment.mjs` — and proves all 18 numbered
gates (14 behavioral, 4 as static source scans for the ones behavior alone can't observe: gate 6 pollTick
isolation, gate 7 no chat-list badge/fetch, gate 9's static confirmation that `ask()` calls `clearChatDelta()`,
gate 18 no CHR3 reference). One correction made while writing the harness: gate 5's "single-flight" does not mean
"call it 3 times, fetch once ever" — `POLL`'s actual, already-shipped contract is one run + at most one coalesced
rerun for callers that arrive while it's in flight (identical to `loadJobs`/`loadSources`) — the gate was rewritten
to assert that real contract (2 requests for 3 back-to-back opens, never 3) rather than a stricter one nothing in
this codebase implements. `21/21` pass. Also re-ran targeted (`test_chr0_conversation_baseline.py`,
`test_chr1_conversation_delta.py`, `test_p2_project_delta.py`, `test_k7_chat_truncation.py`,
`test_s24_lost_chat_and_fk.py`, `test_s26_chat_titles.py`) and the full `test_core.py` + all `tchunk*` groups:
green, apart from the same three pre-existing, unrelated failures on record throughout this document — plus one
new, self-inflicted failure caught and fixed in this round: `test_s50_design_drift.py`'s CL-6 check
(`test_emoji_beside_a_label_the_button_already_states_is_removed`) flagged the "✨ Check what's new" `<button>`
label; the emoji now sits outside the `<button>` element, in the surrounding text, matching every other delta
state's existing pattern.

**Manual usability pass (item 16) — partially completed.** No live `neurosearch` server was reachable from this
session's sandboxed shell (the working copy has no running instance, and this environment cannot start one against
the real corpus), so states A/B/C could not be clicked through in a live browser this round. Compensated with the
jsdom behavioral harness above, which exercises the real shipped DOM-manipulation code (not a reimplementation) for
all three states' underlying logic: an Exact chat with changes rendering a useful compact-then-expanded card
(state A), an Exact chat with `nothing_new` leaving no persistent card (state B), and a legacy/Approximate chat
never auto-firing `/delta` with the lazy affordance working correctly (the mechanics of state C — gates 2-4). The
one thing genuinely unverified is subjective UI feel against the real large legacy conversation
(`6320f26515a143edb964175ed109f143`, ~12.6s cold) in an actual browser session — recorded here as an open item for
Kyle to check once this is on a machine with the live app running, rather than claimed as done.

Not yet pushed — `git push` requires a GitHub credential only present on Kyle's Mac, never in this session.

### CHR2 live-gate update (Codex, 2026-09-19)

The isolated Mac pass was resumed against `.chr2_livetest/` with `NEUROSEARCH_FAKE_AI=1` and a copied project
database; the normal checkout, live database, and paid providers were not used. The two CHR2 fixes from the
isolated worktree were ported to the real checkout: the conversation-message revision cache key in `db.py`, and
the display-only jargon/dedup helpers in `chats.js`. The live meaningful-change pass also exposed a third
presentation leak in claim-transition rows: raw state arrays and the backend word `Claim` were reaching the DOM.
The renderer now turns that row into a plain-language evidence-assessment sentence while preserving the
deterministic delta category and payload.

Live Test A now passes on the exact chat `9cf17d525d9847658656e8027aa631a7` in the copied project. After a
relevant source/evidence addition and a deterministic strength transition, the real page showed:

- `✨ What's new` with `1 meaningful change since 9/18/2026`;
- `Changes an earlier answer` with the evidence-assessment sentence;
- collapsed `More supporting evidence` containing the new source excerpt;
- no raw `previous_state`, `current_state`, `claim_id`, `overlap=`, or `Claim` backend label in the rendered
  delta DOM.

The direct deterministic response matched the live card (`mode=exact`, one material change, one supporting
excerpt), and the card remained non-blocking. The exact `nothing_new` state had already been observed cleanly;
the legacy Approximate pass had already been observed end-to-end on the real large conversation, including
loading feedback, progressive disclosure, rollups, and limitations. The exact auto-check was observed in the
isolated server log and the hidden-document guard remains intentional. Light-theme and narrow-viewport visual
checks remain genuinely unverified in this automation environment, so CHR2 is not marked fully closed until
those are either checked on a foreground browser or explicitly accepted as a gap.

Gates after the port and final renderer correction: `node tests/js/run-chat-delta.mjs` = 21/21 and
`tests/test_s50_design_drift.py` = 9/9. The ported code and this record still need the normal commit/release
ritual; no GitHub push is claimed without verified credentials.

### Delivery update (Codex, 2026-09-19)

The scoped changes were committed as `09be557` and pushed to `origin/main`; remote verification returned the
same SHA. The release artifact is `evals/release/release-check-0.63.94-09be557-20260919-100142.json`.
The full ritual completed with 2,019 passed and 33 failures: the known 8 S43 foundation failures plus the
existing local-model/configuration, S12, S39, and S46 failures. No CHR2-specific failure was introduced.
