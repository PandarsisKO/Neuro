# Chat Refresh — plan (2026-09-18)

Kyle: *"I might not want to retype out a chat, just see if the intelligence surfaces new information I should be
aware of based on new findings."*

Planning only. Nothing here is implemented. Written against the code as of `f7b1818` (0.63.92).

## 1. What the feature is, in one sentence

An existing chat can be asked **"what's new since I got this answer?"** — and the app answers that in two tiers:
a **$0 deterministic delta** (what changed in the project that touches this chat), and, only when the user
clicks for it, a **paid refresh turn** that reads the new material and reports *only* what adds to, changes, or
contradicts the earlier answer.

## 2. What the code already gives us

| Need | Exists today | Gap |
|---|---|---|
| The chat's questions and answers | `messages` (role, content, citations JSON, created_at, meta JSON) | fine |
| What an answer was *based on* | `citations` (source_id, start/end, snippet) — only the excerpts the model cited | the excerpts it was *shown* but didn't cite are not stored; the retrieval query and scope aren't stored |
| "Has anything changed?" cheaply | `db.project_research_revision`, `db.project_view_revision` (S72: move only when answers change) | no per-conversation baseline to compare against |
| New sources in scope | `sources.updated_at` (set by `replace_transcript` when a transcript lands), `project_sources`, collections/tags | membership rows carry no `added_at` |
| New / changed Claims | `project_claims.created_at/updated_at`, `status`, `strength`, `freshness_status`, `claim_evidence.source_id` | none |
| Claims a citation's source feeds | `claims_view` "Why this answer" ($0) | none — reuse as-is |
| New findings | `project_notes.created_at` | none |
| Retrieval | `qa._retrieval_query(question, history)`, `search()` (FTS + vector) | query embedding is an OpenAI call — tiny but not $0 |
| The paid turn | `qa.ask()` with full history, tools, citation validation, continuation, save-on-failure | needs a "refresh" mode that scopes excerpts to *new* material and tells the model to diff, not re-answer |
| Cost disclosure / contracts | `contracts.contract("answer.chat")`, `usage.record_anthropic` | a refresh should use the same contract (no model-policy change) |

## 3. Design

### 3.1 Baseline: what a chat "knows"

Every assistant message written from now on records, in `meta.evidence` (no schema change — `messages.meta` is
already JSON):

```
{"research_revision": "...", "scope_source_ids": [...],          # what was in scope (project sources at answer time)
 "retrieval_query": "...", "shown_chunk_ids": [...],             # every excerpt the model saw, cited or not
 "shown_source_ids": [...], "answered_at": <ts>}
```

This is the only change to the normal ask path and it is write-only (a few KB per answer). Chats answered before
this ships have no snapshot; for them the baseline is `messages.created_at` of the last assistant turn and the
cited sources — the delta is coarser (time-based) but still honest, and the UI says so ("baseline: answered
2026-09-14, excerpts not recorded").

**Why store the shown chunks, not just the cited ones:** "new relevant excerpt" must mean *the model has not seen
it*, not *the model didn't cite it*. Otherwise a refresh re-surfaces material the model already read and chose
not to use, which is exactly the noise Kyle doesn't want.

### 3.2 Tier 0 — the badge ($0, SQL only, poll-safe)

For the chat list: *"anything happened in this project since this chat's last answer?"* Pure counts, no corpus
walk, no retrieval:

- sources in scope with `status='ready'` and `updated_at > answered_at`
- `project_claims` with `updated_at > answered_at` whose evidence touches a cited source, or whose `status`
  changed to accepted/rejected/superseded
- `project_notes` created after `answered_at`
- `research_tensions` opened after `answered_at`

Cached in `cache.py` keyed on `(conversation_id, last_message_id, project_view_revision)` — same discipline as
S72: the value only recomputes when a revision moves. Delivered as extra fields on `GET /api/conversations`
(the list already loads once per project open), never on the 3 s poll. A zero here means the "What's new" panel
never runs anything heavier, and the chat shows nothing at all — no badge, no "0 changes".

### 3.3 Tier 1 — the delta panel ($0 by policy, opened on demand)

`GET /api/conversations/{id}/delta`. Computed when the user opens the chat or clicks the badge, cached on the same
key as Tier 0. It answers **four questions**, each with provenance links:

1. **New sources with something to say.** For the last N user questions (cap N=5; the last one weighted first),
   rebuild `_retrieval_query(question, history)` and run `search(rq, source_ids=new_in_scope, per_source_cap=2)`.
   FTS-only for this tier so it is literally $0 (no query embedding); the paid tier uses full retrieval. Report the
   hits the baseline didn't contain (`chunk_id ∉ shown_chunk_ids`), grouped by source, with the question they
   answer.
2. **Claims that moved.** "Why this answer" for every cited source (existing `claims_view`), filtered to claims whose
   `updated_at > answered_at`; show the transition (proposed→accepted, strong→weak, current→stale, superseded_by).
   A claim that *contradicts* something the answer cited is the highest-value item and is listed first.
3. **New findings** in the project since `answered_at` that overlap the questions (`claims.overlap` on tokens,
   threshold to be set from the live corpus — start at 0.25 and measure).
4. **New tensions** whose sources intersect the cited sources.

Empty across all four → the panel says *"Nothing new since <date>. <n> sources were added but none of them
match what this chat asked."* No model call is made for an empty delta, ever.

Hard bounds so this stays inside the foreground rule: ≤5 questions × ≤12 FTS hits, one Claims lookup per cited
source (≤ the citation count), all reads; measured target < 300 ms warm on Kyle's DB, cache hit ≥ 95 % after the
first open (revision-keyed).

### 3.4 Tier 2 — the paid refresh turn (one click, cost shown first)

Button in the delta panel: **"Refresh answer (~$x)"** — the estimate comes from the contract's input size
(new excerpts + history + prior answer), same as any chat turn; nothing new in cost policy.

Mechanics, all inside `qa.ask()` via a new `mode="refresh"` (no second answer path — same tools, citation
check, continuation, save-on-failure):

- **Synthetic user turn.** Saved as a user message with `meta.kind="refresh"` and content
  `"Refresh: what's new since <date> on: <last question>"`. The UI renders it as a chip, not as typed text, so
  Kyle never has to retype and the transcript stays honest about what was asked.
- **Excerpts = the delta.** `_hits_for` runs on `new_in_scope` sources only (full retrieval this time, priority
  reserve honoured), *plus* the excerpts the prior answer cited so the model can compare against the exact
  passages it used. Anything the model already saw and didn't cite is excluded.
- **Instruction, appended to the user turn (not a new system prompt — keeps the cached prefix):**
  *"Below is your previous answer and only the material that is new since then. Report ONLY what is new: facts
  that add to the answer, change it, or contradict it, with [n] citations. If nothing here changes the answer,
  say so in one sentence. Do not restate the previous answer."*
- **Saved** as an assistant message with `meta.refresh = {baseline_message_id, since, delta_summary}` and its own
  `meta.evidence` (so the *next* refresh diffs against this one). Pin-to-findings, Claims harvest and "Why this
  answer" work unchanged — a refresh answer is an ordinary answer with a known baseline.
- **Scope.** The whole conversation is history, as today; the refresh targets the *last* question by default with
  a picker for an earlier one. Web search is off for refreshes unless the user turns it on.

### 3.5 What it must never do

- Spend money without a click (Tier 0/1 are $0; Tier 1 uses FTS, not embeddings, for that reason).
- Run on the poll path or walk the corpus per poll (Tier 0 is counts on indexed timestamps, cached on revision).
- Re-answer the question. A refresh that ignores the "only what's new" instruction is a regression, and the test
  suite should assert it with the fake provider (answer must not repeat > X % of prior answer's sentences).
- Share project state across projects. Delta is per conversation, inside its project; the twin-project rule
  (compute reuse only) is untouched.
- Change model policy or contracts. Refresh uses `answer.chat` as-is.

## 4. Rungs (small, reversible, each with a test)

| Rung | Ships | Test |
|---|---|---|
| CR0 | `meta.evidence` snapshot on every assistant message | snapshot present, shown ⊇ cited, revision matches `project_research_revision` at answer time |
| CR1 | `GET /api/conversations/{id}/delta` + Tier 0 counts on the list; cache keyed on revision | adding a ready source in scope moves the delta; adding one out of scope doesn't; a claim status change on a cited source appears; empty delta returns `nothing_new=true` and makes **no** provider call; second call is a cache hit |
| CR2 | Chat UI: badge on the chat list, "What's new" panel on the chat, "nothing new" state | JS test in `tests/js/` (same harness as poll containment): panel never fetches while `document.hidden`, one in-flight per chat |
| CR3 | Tier 2 refresh mode in `qa.ask` + button with cost estimate | fake-provider test: excerpts handed to the model contain only new + previously-cited chunks; synthetic user turn saved with `meta.kind`; refresh answer records `meta.refresh` and its own `meta.evidence`; a chat with no delta cannot trigger a refresh (409) |
| CR4 (later, on trigger) | Tier 0 recomputed by the maintenance worker after ingest/harvest completes, so badges are warm before Kyle opens the project | only if opening a project with many chats measures > 300 ms on Tier 0 |

Order is deliberate: CR0 first so every chat Kyle has from tomorrow on has an exact baseline by the time CR1–3
land; CR1 without CR2 is already usable through the API for measurement.

## 5. Decisions I need from Kyle before CR0

1. **Which question does a refresh target by default** — the last one (my recommendation), or the whole chat
   as one "what changed anywhere in this conversation" turn? The latter is more expensive and diffuses the
   answer; the picker covers the earlier-question case.
2. **Should a refresh answer be harvested into Claims like any answer?** I recommend yes (it *is* evidence), but
   it doubles the surface where a bad refresh could seed a claim.
3. **Badge on the chat list, or only inside the chat?** List badges are the "I should be aware" moment Kyle
   described; they are Tier 0 and cheap, but they are one more thing on the screen.
4. **Old chats (no snapshot):** show the coarse time-based delta with a caveat (recommendation), or hide the
   feature until the chat has had one post-CR0 answer?

## 6. Out of scope, on purpose

Auto-refreshing chats without a click; a nightly "refresh everything" (that is the Project Delta / envelope
mission in `delta.py`, a different surface); notifying across projects; changing retrieval ranking.

## 16. Execution record

- **CHR0 shipped (2026-09-18).** `db.save_message` returns the new `messages.id`; `db.get_messages` exposes `id`;
  `db.conversation_baseline(conversation_id)` = newest assistant row with `meta.evidence` and no `meta.incomplete`.
  `conversation_delta.evidence_snapshot()` builds the block from the FINAL `ctx["hits"]` (initial retrieval +
  `search_library` additions + full-context chunks), the resolved scope, the retrieval query, and the user row id;
  it also records `max_claim_evidence_id` and `claim_state` (strength/freshness/status/application of every Claim
  whose evidence touches a shown source) so CHR1 can name transitions. Incomplete turns write `meta.incomplete`
  and no `evidence`; `save_failure` unchanged (no `evidence`); link-only turns write a zero-hit baseline. Gate:
  `tests/test_chr0_conversation_baseline.py` (7 tests). Full suite green apart from `test_p1b_tonight_ui`'s
  ui-version assertion, which belongs to the concurrent 0.63.94 work in the tree, not to CHR0.
