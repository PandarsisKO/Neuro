"""Conversation Delta (docs/CHAT-REFRESH-PLAN.md). CHR0 (this file's first rung): the BASELINE — what a
successfully completed assistant turn could actually know, recorded in messages.meta.evidence so a later delta
can be a set difference against facts instead of a guess against timestamps.

Kyle's north star for the whole mission: *"More newly ingested material is not itself value. Changed understanding
is value."* — which is only decidable if we know what the earlier answer was shown. CHR0 records that; it changes
nothing about retrieval, prompting, ranking, Claims or the answer text (plan §2, last bullet).

The snapshot is taken from the FINAL ctx["hits"] — the initial retrieval plus every search_library addition plus
every chunk of a full-context turn — because all of those were in the prompt and could be cited as [n]. Cited
excerpts are therefore always a subset of shown ones, which the CHR0 gate asserts.
"""
from __future__ import annotations

import logging
import json
from typing import Any

from . import db

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 4   # v4 (2026-09-18): adds "open_evidence_target_ids" — the id set of every
                       # project_evidence_target that was OPEN at answer time, on top of v3's "scope_source_revisions"
                       # and v2's "complete". Without this, CHR1 could not tell "this research target was open when
                       # the answer was given and is satisfied now" (a real resolution) from "this target was
                       # already satisfied and something else about it was touched later" (not a resolution at
                       # all) — see conversation_delta.delta_for_question's resolves_gap section. A v1-v3 snapshot
                       # (no key) falls back to a more conservative rule there (created-after-baseline only).
                       # A v1 snapshot (neither "complete" nor revision/target keys) is treated as complete for
                       # backward compatibility; CHR1 only downgrades a snapshot that EXPLICITLY says
                       # complete=False. A v1/v2 snapshot (no revision map) falls back to the old
                       # updated_at>answered_at heuristic for "did this source get re-transcribed" specifically —
                       # everything else about that question can still be exact.


def evidence_snapshot(*, project_id: str | None, scope_source_ids: list[str] | None, retrieval_query: str,
                      hits: list[dict[str, Any]], full_context: bool, question_message_id: int | None) -> dict[str, Any]:
    """Build the meta.evidence block for an assistant turn that FINISHED. Never raises for the caller's sake: a
    snapshot that cannot be completed degrades to what could be read, and the answer is saved either way — BUT it
    is marked complete=False when that happens, so a reader never mistakes a partially-gathered snapshot for an
    exact one. This matters starting with CHR1: "this conversation had never seen this" and "this Claim changed
    from X to Y" are exact claims, and they must not be made from a snapshot whose research_revision or claim_state
    could not actually be read (Kyle's correction, 2026-09-18)."""
    shown_chunk_ids = sorted({int(h["chunk_id"]) for h in hits if h.get("chunk_id") is not None})
    shown_source_ids = sorted({str(h["source_id"]) for h in hits if h.get("source_id")})
    scope = [s for s in (scope_source_ids or []) if s and s != "__none__"]
    snap: dict[str, Any] = {
        "v": SNAPSHOT_VERSION,
        "complete": True,
        "answered_at": db.now(),
        "retrieval_query": retrieval_query or "",
        "scope_source_ids": scope,
        "scope_source_revisions": {},
        "shown_chunk_ids": shown_chunk_ids,
        "shown_source_ids": shown_source_ids,
        "full_context": bool(full_context),
        "question_message_id": question_message_id,
        "research_revision": None,
        "max_claim_evidence_id": None,
        "claim_state": {},
        "open_evidence_target_ids": [],
    }
    if not project_id:
        return snap   # no project: nothing further to gather, and nothing failed — still complete
    try:
        snap["research_revision"] = db.project_research_revision(project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: research revision unavailable: %s", e)
        snap["complete"] = False
    try:
        # A "revised source" (re-transcribed, same id) must be detected by its ACTUAL revision, not updated_at —
        # any metadata write (a title fix, a status back-fill) also moves updated_at without touching the
        # transcript (Kyle's correction, 2026-09-18). Recording each scoped source's revision AT ANSWER TIME is
        # what lets CHR1 compare "then" vs "now" exactly instead of guessing from a timestamp. One batched SELECT,
        # not N calls to db.source_revision — replace_transcript() always sets sources.revision directly, so a
        # source with a transcript already has it; a source with none (not yet transcribed) has none to compare.
        if scope:
            rows = db.connect().execute(
                f"SELECT id, revision FROM sources WHERE id IN ({','.join('?' * len(scope))})", scope).fetchall()
            snap["scope_source_revisions"] = {r["id"]: r["revision"] for r in rows if r["revision"]}
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: source revisions unavailable: %s", e)
        snap["complete"] = False
    try:
        conn = db.connect()
        r = conn.execute("SELECT COALESCE(MAX(ce.id), 0) m FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id "
                         "WHERE c.project_id=?", (project_id,)).fetchone()
        snap["max_claim_evidence_id"] = int(r["m"] or 0)
        # The state of every Claim whose evidence touches a source the model was shown: a later strength/freshness/
        # status/application change is then a TRANSITION the delta can name (plan §6 category 3), not an updated_at.
        if shown_source_ids:
            rows = conn.execute(
                "SELECT DISTINCT c.id, c.strength, c.freshness_status, c.status, c.application FROM project_claims c "
                "JOIN claim_evidence ce ON ce.claim_id=c.id WHERE c.project_id=? AND ce.source_id IN (%s)"
                % ",".join("?" * len(shown_source_ids)), (project_id, *shown_source_ids)).fetchall()
            snap["claim_state"] = {r["id"]: [r["strength"], r["freshness_status"], r["status"], r["application"]] for r in rows}
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: claim state unavailable: %s", e)
        snap["complete"] = False
    try:
        # v4 (Kyle, 2026-09-18): which research targets were OPEN right now, at answer time — the historical
        # baseline that lets a later Exact-mode delta PROVE a target transitioned open→satisfied after this
        # answer, instead of guessing from updated_at (which a satisfied target's unrelated field edits also move).
        rows = db.connect().execute(
            "SELECT id FROM project_evidence_targets WHERE project_id=? AND status='open'", (project_id,)).fetchall()
        snap["open_evidence_target_ids"] = [r["id"] for r in rows]
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: open evidence targets unavailable: %s", e)
        snap["complete"] = False
    return snap


# =============================================================================================================
# CHR1 — Conversation Delta (docs/CHAT-REFRESH-PLAN.md §3, §5–§7, §11, §14).
#
# THE SEMANTIC FIX (Kyle, 2026-09-18, before CHR1 began): the delta is aggregated from PER-QUESTION answer
# baselines, never diffed solely against the newest assistant message. An early question can go stale while a
# later, unrelated question keeps the conversation's overall "last successful use" timestamp moving forward —
# conversation_baseline() alone would permanently hide that. CHR0's question_message_id exists to make the
# per-question walk possible: for every real user question, find the assistant row whose
# meta.evidence.question_message_id points back to it, and treat THAT answer's snapshot as the baseline for
# THAT question. conversation_baseline() remains useful for "last successful activity", legacy/coarse chats,
# and cache identity — it is not sufficient by itself for exact delta semantics.
#
# Two kinds of newness, both derived from the per-question baselines with no new schema:
#   temporal newness  — this evidence appeared after the answer it could affect (question-specific: created_at
#                        / updated_at > that question's own answered_at).
#   epistemic newness — this conversation has never actually been shown this evidence (conversation-wide:
#                        conversation_seen_chunk_ids, the union of shown_chunk_ids across every successful
#                        snapshot, so a chunk shown to answer Q3 is not re-flagged as "unseen" for Q1).
# =============================================================================================================

import json
import time
from typing import Any

from . import claims as _claims
from . import db, plan_narrative

OVERLAP_THRESHOLD = 0.35
# Measured 2026-09-18 on Kyle's live corpus (snapshot copy, immutable=1; never the live db — standing rule #1),
# project c752ed152ec942dd97b9a94c3f1b3b96 (19,485 findings; 99.7% under 400 chars, median 193). 10 real
# questions x 17,990 short findings (<500 chars), bucketed by claims.overlap(question, finding.content):
#   0.10-0.19: 14318   0.20-0.29: 8583   0.30-0.39: 1501   0.40-0.49: 248   0.50+: 566
# Manual inspection: below 0.30 is dominated by shared domain vocabulary with no real topical link (both short,
# well-formed questions like "can an SBA loan be used for renovations?" and long conversational recaps). At and
# above 0.40, short well-formed questions match ONLY genuinely on-topic findings. 0.30-0.39 is mixed. A long,
# multi-clause recap-style question (many of Kyle's real messages are these) biases overlap UPWARD regardless of
# topic, because overlap() takes the share of the SHORTER passage's (the finding's) tokens found in the other —
# a long question's huge vocabulary is likely to contain most of a short finding's distinctive words by chance.
# Chosen threshold: 0.35 — the lowest value where the 0.30-0.39 band's mixed-but-mostly-relevant character still
# keeps the panel useful, given two things that bound the noise this lets through: (1) Findings-overlap is ONLY
# the routing filter for category 5 ("adds a substantively new finding") — the lowest-but-one panel category,
# never the contradiction/plan-impact/claim-transition categories, which are anchored to actual source/claim
# touch, not overlap; (2) FINDINGS_PER_QUESTION_CAP below bounds exposure regardless of how noisy the threshold
# turns out to be on a given question's phrasing. If real use shows this still floods the "more supporting
# evidence" section, the fix is a higher threshold or a length-normalized variant — not a redesign.
FINDINGS_PER_QUESTION_CAP = 5     # top-N findings by overlap considered per question, so one long recap question cannot flood the delta

FTS_PER_QUESTION_LIMIT = 12       # excerpts search_fts may pull per question (mirrors qa.ask's initial retrieval size)

CATEGORY_ORDER = {                # plan §6 — lower sorts first; recency breaks ties WITHIN a category, never across
    "contradicts": 0,
    "plan_impact": 1,
    "claim_transition": 2,
    "resolves_gap": 3,
    "new_finding": 4,
    "new_excerpt": 5,
    "corroborates": 6,
    "new_claim": 7,   # Exact mode, Kyle's 2026-09-18 correction: a Claim newly relevant to THIS answer with no
                       # provable prior state in its own snapshot — never a fabricated "changed from None"
                       # transition, so it sorts as supporting evidence rather than a proven material change.
}


def _rows(conversation_id: str) -> list[dict[str, Any]]:
    """Every message in the conversation, oldest first, WITH id and parsed meta — a direct read (no limit), so a
    chat longer than qa.ask()'s 12-message history tail is still scanned in full (plan §5)."""
    rows = db.connect().execute(
        "SELECT id, role, content, citations, created_at, meta FROM messages WHERE conversation_id=? ORDER BY id",
        (conversation_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d["meta"]) if d["meta"] else {}
        except ValueError:
            d["meta"] = {}
        try:
            d["citations"] = json.loads(d["citations"]) if d["citations"] else []
        except ValueError:
            d["citations"] = []
        out.append(d)
    return out


def _reconstructed_retrieval_query(rows: list[dict[str, Any]], user_row: dict[str, Any]) -> str:
    """A legacy question carries no stored retrieval_query (pre-CHR0). Reconstruct it the same deterministic, $0
    way qa.ask() would have built it at the time: the same qa._retrieval_query(question, history), fed the prior
    user/assistant turns up to that point (capped at 12, matching qa.ask's own history window) — not a guess, the
    same pure function, replayed. This is what makes a bare follow-up like "What about taxes?" route on topic even
    without an exact snapshot (Kyle's correction, 2026-09-18)."""
    from .qa import _retrieval_query
    prior = [r for r in rows if r["id"] < user_row["id"] and r["role"] in ("user", "assistant") and r["content"].strip()][-12:]
    history = [{"role": r["role"], "content": r["content"]} for r in prior]
    return _retrieval_query(user_row["content"], history)


def _questions(conversation_id: str) -> list[dict[str, Any]]:
    """Every REAL user question paired with the successful assistant answer that responds to it — exact mode
    (linked by question_message_id, CHR0) when available, approximate mode (positional: the next non-incomplete
    assistant row) otherwise. Synthetic refresh turns (meta.kind == "refresh") are excluded from this set — they
    are never a topic and can never seed the next refresh (plan §5)."""
    rows = _rows(conversation_id)
    users = [r for r in rows if r["role"] == "user" and r["content"].strip() and r["meta"].get("kind") != "refresh"]
    assistants = [r for r in rows if r["role"] == "assistant"]
    by_question_id = {r["meta"]["evidence"]["question_message_id"]: r
                      for r in assistants if isinstance(r["meta"].get("evidence"), dict) and not r["meta"].get("incomplete")
                      and r["meta"]["evidence"].get("question_message_id") is not None}
    good_assistants = [r for r in assistants if not r["meta"].get("incomplete") and r["content"].strip()]

    out = []
    for u in users:
        answer = by_question_id.get(u["id"])
        if answer is None:
            # legacy positional fallback: the next good assistant row after this question, by id order
            answer = next((a for a in good_assistants if a["id"] > u["id"]), None)
        if answer is None:
            continue   # an unanswered question contributes nothing to the delta
        ev = answer["meta"].get("evidence") if isinstance(answer["meta"].get("evidence"), dict) else None
        # CHR0 hardening (Kyle, 2026-09-18): a snapshot that explicitly says complete=False had bookkeeping fail
        # partway (research_revision or claim_state could not be read) — it is real evidence of what was SHOWN,
        # but not a basis for exact claim-transition or plan-impact claims, so this question is downgraded to
        # approximate rather than trusted as exact. A v1 snapshot (no "complete" key, already shipped) defaults
        # to exact for backward compatibility — only an EXPLICIT False downgrades.
        exact = bool(ev) and ev.get("complete", True) is not False
        # Route on the SAME retrieval query the original answer used (Kyle's correction, 2026-09-18): a bare
        # follow-up ("What about taxes?") retrieves badly on its own words — qa._retrieval_query() is what grounded
        # it in the prior turn when the answer was generated, and CHR1 must use that exact string, not the raw
        # question, or a contextual follow-up silently loses its topic. Legacy questions get it reconstructed.
        retrieval_query = (ev.get("retrieval_query") or u["content"]) if exact and ev else _reconstructed_retrieval_query(rows, u)
        out.append({
            "question_message_id": u["id"], "question": u["content"], "retrieval_query": retrieval_query,
            "answer_message_id": answer["id"], "answered_at": answer["created_at"],
            "mode": "exact" if exact else "approximate",
            "scope_source_ids": set(ev["scope_source_ids"]) if exact and ev else None,
            "scope_source_revisions": ev.get("scope_source_revisions") or {} if exact and ev else {},
            "shown_chunk_ids": set(ev["shown_chunk_ids"]) if exact and ev else None,
            "shown_source_ids": set(ev["shown_source_ids"]) if ev else {c.get("source_id") for c in answer["citations"] if c.get("source_id")},
            "claim_state": ev.get("claim_state", {}) if exact and ev else {},
            # v4+ only (Kyle, 2026-09-18): None means "no historical open-target baseline available" (v1-v3 exact
            # snapshot, or Approximate mode) -- delta_for_question's resolves_gap section falls back to a more
            # conservative rule in that case. Deliberately keyed on the field's PRESENCE, not just "exact", since
            # an exact v1-v3 snapshot has no such record either.
            "open_evidence_target_ids": (set(ev["open_evidence_target_ids"])
                                         if exact and ev and "open_evidence_target_ids" in ev else None),
        })
    return out


def conversation_seen_chunk_ids(conversation_id: str) -> set[int]:
    """Epistemic newness (plan, Kyle's correction): the union of shown_chunk_ids across EVERY successful assistant
    snapshot in the conversation, including refresh answers (their excerpts were genuinely shown, even though a
    refresh turn is not itself a topic) — so a chunk shown to answer Q3 is never mislabelled 'unseen' for Q1."""
    seen: set[int] = set()
    for r in _rows(conversation_id):
        if r["role"] != "assistant":
            continue
        ev = r["meta"].get("evidence")
        if isinstance(ev, dict):
            seen.update(ev.get("shown_chunk_ids") or [])
    return seen


def conversation_last_known_claim_state(conversation_id: str, *, exclude_message_id: int | None = None) -> dict[str, list]:
    """The last state this conversation actually knew for each touched Claim — folded chronologically across every
    successful snapshot (later overwrites earlier), so a transition is judged against what the conversation was
    told, not against the Claim's state at only the newest turn.

    `exclude_message_id` (Kyle, 2026-09-18, fifth correction): when computing "did some OTHER answer in this chat
    already see this state" for a specific question, that question's OWN answer row must not count as "elsewhere"
    -- without this, a single-question conversation (or the question being evaluated itself) would trivially fold
    its own claim_state into `known` and then compare it against itself, always reporting
    already_seen_elsewhere_in_chat=True even though nothing else in the chat actually saw it. Callers computing a
    per-question "elsewhere" annotation pass that question's own `answer_message_id` here; the single
    whole-conversation call some other reader might want (none currently) would omit it."""
    known: dict[str, list] = {}
    for r in _rows(conversation_id):
        if r["role"] != "assistant" or r["id"] == exclude_message_id:
            continue
        ev = r["meta"].get("evidence")
        if isinstance(ev, dict):
            known.update(ev.get("claim_state") or {})
    return known


def _touched_claims_for_sources(project_id: str, source_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not source_ids:
        return {}
    conn = db.connect()
    marks = ",".join("?" * len(source_ids))
    rows = conn.execute(
        f"SELECT DISTINCT c.* FROM project_claims c JOIN claim_evidence ce ON ce.claim_id=c.id "
        f"WHERE c.project_id=? AND ce.source_id IN ({marks})", (project_id, *source_ids)).fetchall()
    return {r["id"]: dict(r) for r in rows}


def delta_for_question(project_id: str, q: dict[str, Any], *, current_scope: set[str],
                       conversation_seen: set[int], last_known_claim_state: dict[str, list]) -> list[dict[str, Any]]:
    """Evidence units relevant to ONE question, discovered independently of any other question (plan §7: "Do not
    start with 'new source IDs'" — every category below is its own SQL pass, never a source-id-only filter).
    Each unit is a plain dict, not UI prose: kind, ids, previous/current state, relation, why_relevant."""
    units: list[dict[str, Any]] = []
    since = q["answered_at"]
    conn = db.connect()

    if q["mode"] != "exact":
        # Approximate baseline (plan §12), CORRECTED (Kyle, 2026-09-18): the original formula --
        #   newly_available = current_scope - shown_source_ids
        # -- is not a valid inference. shown_source_ids tells us only what the OLD ANSWER cited/saw; a pre-CHR0
        # answer carries no scope snapshot, so it does NOT tell us what sources existed in the project at answer
        # time. "not shown by the old chat" != "added after the old chat" -- an old chat may have cited 5 of 1,072
        # sources that all already existed. Treating the other 1,067 as "new" is what made touch_sources swallow
        # ~93% of a real project's Claims and made a single delta computation take 90+ minutes (measured).
        # The only honest temporal signal for a legacy chat is: which of the CURRENT scope's sources can be PROVEN
        # to have moved (become ready, or been re-transcribed) after this question's answered_at, via their own
        # updated_at -- the same fallback heuristic exact mode already uses for a source with no recorded revision.
        # A source that already existed and never changed produces no signal here and is correctly never surfaced;
        # a source added to the project after this answer but never modified afterwards is a real, acknowledged
        # miss for approximate mode (no historical project-membership record exists to catch it) -- exact mode
        # (below) proves this case instead, via scope_source_ids.
        newly_available: set[str] = set()
        if current_scope:
            marks = ",".join("?" * len(current_scope))
            newly_available = {r["id"] for r in conn.execute(
                f"SELECT id FROM sources WHERE id IN ({marks}) AND status='ready' AND updated_at>?",
                (*current_scope, since)).fetchall()}
    else:
        newly_available = (current_scope - (q["scope_source_ids"] or set()))
        # a source that WAS in scope but became ready / re-transcribed since this answer
        if q["scope_source_ids"]:
            baseline_revisions = q.get("scope_source_revisions") or {}
            in_scope_with_baseline_rev = set(q["scope_source_ids"]) & set(baseline_revisions)
            if in_scope_with_baseline_rev:
                # v3+ snapshot: compare the ACTUAL revision, not a timestamp any metadata write could move
                # (Kyle's correction, 2026-09-18) — exact for every source this baseline recorded a revision for.
                marks = ",".join("?" * len(in_scope_with_baseline_rev))
                for r in conn.execute(f"SELECT id, revision FROM sources WHERE id IN ({marks}) AND status='ready'",
                                      tuple(in_scope_with_baseline_rev)).fetchall():
                    if r["revision"] and r["revision"] != baseline_revisions.get(r["id"]):
                        newly_available.add(r["id"])
            # sources this baseline predates entirely for revision purposes (v1/v2 snapshot, or a scoped source
            # that had no transcript yet at answer time): fall back to the old timestamp heuristic — approximate
            # compatibility, not pretended exactness (a metadata-only write can false-positive here).
            no_baseline_rev = set(q["scope_source_ids"]) - in_scope_with_baseline_rev
            if no_baseline_rev:
                marks = ",".join("?" * len(no_baseline_rev))
                revised = {r["id"] for r in conn.execute(
                    f"SELECT id FROM sources WHERE id IN ({marks}) AND status='ready' AND updated_at>?",
                    (*no_baseline_rev, since)).fetchall()}
                newly_available |= revised

    # category: new relevant excerpt (6) — FTS-only, $0, from newly-available sources. `fts_hit_source_ids` doubles
    # as a relevance signal below (Kyle, 2026-09-18, part C): a newly-available source that actually produced a
    # topical hit for THIS question is a stronger relevance proof than mere membership in `newly_available`.
    fts_hit_source_ids: set[str] = set()
    if newly_available and q["retrieval_query"].strip():
        from .search import search_fts
        for h in search_fts(q["retrieval_query"], limit=FTS_PER_QUESTION_LIMIT, source_ids=sorted(newly_available)):
            fts_hit_source_ids.add(h["source_id"])
            # Kyle's correction, 2026-09-18 (part D): this used to `continue` (drop the unit) whenever the chunk
            # was already in `conversation_seen` — the whole-chat union of every successful snapshot's shown
            # chunks. That repeats the whole-chat-baseline mistake CHR1 was built to avoid: a chunk absent from
            # THIS question's own snapshot is still a genuine post-baseline change relevant to THIS question, even
            # if a LATER question in the same chat happened to also surface it (e.g. new evidence that would have
            # changed Q1's answer, which Q2 — asked afterward — separately picked up). Annotate, never discard.
            already_seen_elsewhere = h["chunk_id"] in conversation_seen
            units.append({"kind": "new_excerpt", "category": "new_excerpt", "question_message_id": q["question_message_id"],
                         "question": q["question"], "source_id": h["source_id"], "chunk_ids": [h["chunk_id"]],
                         "why_relevant": "matches this question against newly available material", "locator": h.get("timestamp"),
                         "title": h.get("title"), "text": h["text"][:300],
                         "already_seen_elsewhere_in_chat": already_seen_elsewhere})

    # category: new Finding (5), overlap-routed — old OR new sources, both allowed (plan §3)
    findings = conn.execute(
        "SELECT id, content, source_id FROM project_notes WHERE project_id=? AND created_at>? AND status IN ('approved','suggested')",
        (project_id, since)).fetchall()
    scored = []
    for f in findings:
        ov = _claims.overlap(q["retrieval_query"], f["content"])
        if ov >= OVERLAP_THRESHOLD:
            scored.append((ov, f))
    scored.sort(key=lambda t: -t[0])
    for ov, f in scored[:FINDINGS_PER_QUESTION_CAP]:
        units.append({"kind": "new_finding", "category": "new_finding", "question_message_id": q["question_message_id"],
                     "question": q["question"], "finding_id": f["id"], "source_id": f["source_id"],
                     "why_relevant": f"overlap={round(ov, 2)} with this question", "text": f["content"][:400]})

    # `touched` = changed_claim_ids' row data: everything touched by shown/newly-available sources OR overlapping
    # the question text. This is the CHANGED set (Kyle's §5 separation) — deliberately broad, feeding the
    # Approximate rollup's aggregate counts and the Exact claim-transition scan below. It is NOT itself a relevance
    # signal (see relevant_claim_ids, next) — a Claim reached only via a brand-new, never-cited, topically-unrelated
    # source is "changed" but not necessarily "relevant to this conversation."
    touch_sources = (q.get("shown_source_ids") or set()) | newly_available
    touched = dict(_touched_claims_for_sources(project_id, touch_sources))
    for r in conn.execute("SELECT * FROM project_claims WHERE project_id=? AND updated_at>?", (project_id, since)).fetchall():
        if r["id"] in touched:
            continue
        if _claims.overlap(q["retrieval_query"], r["text"]) >= OVERLAP_THRESHOLD:
            touched[r["id"]] = dict(r)

    # Perf (Kyle, 2026-09-18 measurement): this loop used to call _max_claim_evidence_id_at(project_id, since) --
    # itself a SQL query -- ONCE PER TOUCHED CLAIM, and ran one "does this claim have new evidence" query per claim
    # too. On a mature project (measured on Kyle's real corpus: ~16k claims touched by one early question of a
    # legacy/approximate conversation) that is ~16k redundant recomputations of a loop-invariant value at ~25 ms
    # each -- >170 s for a single question, before CHR2 would trigger this path automatically on chat open. Hoisted
    # the invariant call out of the loop and batched the per-claim evidence check into chunked IN() queries.
    max_ce_id = _max_claim_evidence_id_at(project_id, since)
    claims_with_new_evidence: set[str] = set()
    ids_to_check = [cid for cid, c in touched.items() if c["updated_at"] > since]
    _CE_CHUNK = 500
    for i in range(0, len(ids_to_check), _CE_CHUNK):
        chunk = ids_to_check[i:i + _CE_CHUNK]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT DISTINCT claim_id FROM claim_evidence WHERE claim_id IN ({marks}) AND id>?",
                (*chunk, max_ce_id)).fetchall():
            claims_with_new_evidence.add(r["claim_id"])

    # relevant_claim_ids (Kyle, 2026-09-18, second AND third correction): "important to the project is not
    # automatically important to this conversation" — and this now applies to BOTH modes, not just Approximate.
    # `touched` (above) answers "what changed"; this answers "what's connectable to THIS question." Built from:
    #   1. the Claim's evidence touches a source THIS question's answer actually cited/saw (shown_source_ids —
    #      not the wider touch_sources, which also includes brand-new sources the answer could never have seen);
    #   2. (Exact mode only) the Claim was part of THIS answer's own recorded claim_state — a real historical fact,
    #      strictly stronger than mere source-touch, and the reason Exact mode does not need weak lexical overlap
    #      to trust a historically-known Claim (Kyle: "remains relevant even with weak lexical overlap");
    #   3. the Claim has its OWN evidence excerpt on a newly-available source that produced an ACTUAL FTS hit for
    #      this question's retrieval_query — judged at the EVIDENCE level, not the source level (Kyle's fourth
    #      correction, 2026-09-18): a source can cover many topics, so "this source is topically relevant" does
    #      NOT make every Claim that happens to have evidence on it relevant too (the bug the regression test
    #      caught: an unrelated microphone-brand Claim became "relevant" purely because it shared a source with
    #      genuinely on-topic seller-financing material). Mere membership in `newly_available` never counted either
    #      (a Claim on an unrelated brand-new source is not "relevant" just because the source happens to be new);
    #   4. the Claim's own text passes the same topical-overlap test used for retrieval-query routing elsewhere.
    # Plan impact is deliberately NOT a signal here — "Plan impact increases the importance of a relevant change.
    # It does not establish conversation relevance by itself" — so it is applied downstream, in for_conversation(),
    # as an intersection with this set, never as an alternate way into it.
    shown_touched = dict(_touched_claims_for_sources(project_id, q.get("shown_source_ids") or set()))
    relevant_claim_ids = set(shown_touched.keys())
    if q["mode"] == "exact":
        relevant_claim_ids |= set(q["claim_state"].keys())
    if fts_hit_source_ids:
        # Kyle's correction, 2026-09-18 (fourth pass): a source being topically relevant does NOT make every
        # Claim that happens to have evidence on it relevant -- a source can cover many topics (the regression
        # test that caught this: a seller-financing source whose FTS hit made an unrelated microphone-brand Claim
        # "relevant" purely by co-location). Relevance must be judged at the EVIDENCE level, not the source level:
        # a Claim reached only through fts_hit_source_ids is relevant only if it has its OWN evidence excerpt on
        # that hit source that itself overlaps this question's retrieval_query -- the narrowest existing seam
        # (claim_evidence.excerpt), not a fuzzy locator-to-chunk reconstruction (not attempted unless measurement
        # ever proves it necessary).
        marks = ",".join("?" * len(fts_hit_source_ids))
        for r in conn.execute(
                f"SELECT DISTINCT ce.claim_id, ce.excerpt FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id "
                f"WHERE c.project_id=? AND ce.source_id IN ({marks})",
                (project_id, *fts_hit_source_ids)).fetchall():
            if r["claim_id"] in relevant_claim_ids:
                continue
            if _claims.overlap(q["retrieval_query"], r["excerpt"] or "") >= OVERLAP_THRESHOLD:
                relevant_claim_ids.add(r["claim_id"])
    for cid, c in touched.items():
        if cid in relevant_claim_ids:
            continue
        if _claims.overlap(q["retrieval_query"], c["text"]) >= OVERLAP_THRESHOLD:
            relevant_claim_ids.add(cid)

    if q["mode"] == "exact":
        # Exact mode: the baseline's claim_state snapshot is real (CHR0 recorded it at answer time), so a
        # prev/cur comparison against THIS answer's own snapshot is a genuine epistemic signal.
        for cid in touched.keys() & relevant_claim_ids:
            c = touched[cid]
            if c["updated_at"] <= since:
                continue
            # Kyle's correction, 2026-09-18 (part B): previous state must come from THIS QUESTION's own
            # claim_state, never from last_known_claim_state (the latest state seen ANYWHERE in the conversation,
            # folded chronologically). The old code did `last_known_claim_state.get(cid) or q["claim_state"].get(cid)`
            # — if a LATER question (e.g. Q2) already recorded the Claim's current state, that later state would
            # silently stand in as "previous" for an EARLIER question's (Q1's) own comparison, making Q1's own
            # A→B transition compare B against B and disappear. `last_known_claim_state` is now used only as an
            # annotation (did some other turn in this chat already see this outcome?), never as a substitute for
            # what this specific answer actually knew.
            previous_for_this_answer = q["claim_state"].get(cid)
            latest_seen_elsewhere = last_known_claim_state.get(cid)
            cur = [c["strength"], c["freshness_status"], c["status"], c["application"]]
            has_new_evidence = cid in claims_with_new_evidence   # new evidence attached since the baseline?
            if previous_for_this_answer is None:
                # Kyle's correction, 2026-09-18: prev=None does NOT necessarily mean "the conversation's baseline
                # predates the Claim's own creation" — it may simply mean THIS answer's own snapshot never
                # captured this Claim (e.g. it becomes relevant only now, via a newly-available source's FTS hit or
                # topical overlap). That is real, but it is "new to this answer," not a proven A→B transition — a
                # transition needs two known states to compare, and fabricating "changed from None" overstates what
                # is actually known. A separate category keeps the API semantics honest.
                units.append({"kind": "claim", "category": "new_claim", "question_message_id": q["question_message_id"],
                             "question": q["question"], "claim_id": cid, "previous_state": None, "current_state": cur,
                             "relation": "new", "already_seen_elsewhere_in_chat": latest_seen_elsewhere is not None,
                             # ranking signal only (Kyle's second correction, part 2): how strongly this Claim's own
                             # text matches this question's retrieval_query, used downstream in for_conversation()
                             # to pick a small, deterministic explicit sample out of a potentially large new_claim
                             # population -- never a relevance gate here, relevance was already decided above.
                             "overlap_score": _claims.overlap(q["retrieval_query"], c["text"]),
                             "why_relevant": f'Claim "{c["text"][:100]}" is newly relevant to this answer'})
                continue
            transitioned = previous_for_this_answer != cur
            if not transitioned and not has_new_evidence:
                continue
            relation = "changes" if transitioned else "corroborates"
            category = "claim_transition" if transitioned else "corroborates"
            # annotation only (Kyle, part B): the SAME resulting state may already have been recorded by a later
            # question in this chat — worth telling the reader, but it must never suppress THIS question's own
            # transition unit.
            already_seen_elsewhere = latest_seen_elsewhere is not None and latest_seen_elsewhere == cur
            units.append({"kind": "claim", "category": category, "question_message_id": q["question_message_id"],
                         "question": q["question"], "claim_id": cid, "previous_state": previous_for_this_answer,
                         "current_state": cur, "relation": relation, "already_seen_elsewhere_in_chat": already_seen_elsewhere,
                         "why_relevant": f'Claim "{c["text"][:100]}" ' + (
                             f"changed: {previous_for_this_answer} → {cur}" if transitioned else "gained new evidence")})
    else:
        # Approximate mode, CORRECTED (Kyle, 2026-09-18): prev=None here does NOT mean "the conversation never
        # knew this Claim" — a legacy/pre-CHR0 answer carries no claim_state snapshot at all, so prev is simply
        # UNKNOWN, not "absent." The old code read `prev != cur` as a transition regardless of mode, which turned
        # nearly every touched Claim — often ~90% of a mature project's whole Claim table — into an explicit
        # "claim_transition" unit: 16,000+ of them for a single real legacy chat, each then feeding an expensive
        # plan-impact lookup (measured: 90+ minutes cold for one chat open).
        # Only deterministic, provable signals earn an explicit unit here: an open contradiction/tension (handled
        # separately, below) and a batch-verified Master Plan citation on a Claim that is ALSO independently
        # relevant (relevant_claim_ids, computed above) — everything else is real, but not something Approximate
        # mode can honestly attribute to "this changed what you were told." It is counted, not enumerated (one
        # cheap rollup unit below carries the id sets), so CHR2 never receives thousands of near-identical objects
        # to collapse, and this function never allocates a per-claim dict for the ones that get rolled up.
        # decision_impact() is deliberately NOT called here, per question -- Kyle's point 4: "use batch
        # decision_impact() once", and measurement showed why it matters beyond call count: decision_impact()'s
        # _plan_cited_note_ids() reloads and JSON-parses every one of the project's Findings on EVERY call (not
        # cached across calls), so calling it once per question was itself a real, measured cost (~330 ms/call on
        # Kyle's real corpus, ~17k Findings) on top of the plan-impact routing it was doing. candidate_ids here is
        # just the set this ONE question found active; for_conversation unions them across every question and
        # makes exactly one decision_impact() call for the whole delta.
        candidate_ids = {cid for cid, c in touched.items() if c["updated_at"] > since}   # changed_claim_ids
        rollup_ce_ids = claims_with_new_evidence
        if candidate_ids or rollup_ce_ids or newly_available:
            units.append({"kind": "rollup", "category": "rollup", "question_message_id": q["question_message_id"],
                         "question": q["question"], "rollup_source_ids": set(newly_available),
                         "rollup_claim_ids": candidate_ids, "rollup_claim_evidence_ids": rollup_ce_ids,
                         "candidate_claims": {cid: touched[cid] for cid in candidate_ids},
                         "relevant_claim_ids": relevant_claim_ids})

    # category: contradiction / reversal — open tensions on a RELEVANT Claim, created after the baseline.
    # relevant_claim_ids is now the gate for BOTH modes (Kyle, 2026-09-18, part C: "important to the project is
    # not automatically important to this conversation" applies to Exact mode too — a Claim reached only via an
    # unrelated newly-available source is not conversation-relevant merely because the source is new). Exact mode
    # is not weakened by this: its relevant_claim_ids includes every Claim this answer's own claim_state actually
    # recorded, unconditionally, which is a strictly stronger signal than Approximate mode has access to.
    if relevant_claim_ids:
        marks = ",".join("?" * len(relevant_claim_ids))
        for t in conn.execute(
            f"SELECT * FROM research_tensions WHERE project_id=? AND claim_id IN ({marks}) AND status='open' AND created_at>?",
            (project_id, *relevant_claim_ids, since)).fetchall():
            units.append({"kind": "tension", "category": "contradicts", "question_message_id": q["question_message_id"],
                         "question": q["question"], "claim_id": t["claim_id"], "tension_id": t["id"], "relation": "contradicts",
                         "why_relevant": f"a new open {t['kind'].lower()} tension appeared on a Claim this answer relied on"})

    # category: resolved evidence target / gap.
    # Kyle's correction, 2026-09-18 (part A): `status<>'open'` is NOT "resolved." project_evidence_targets has
    # four statuses -- open, satisfied, closed_by_user, dropped. `dropped` is used for dedup/tension cleanup, not
    # evidence Neuro produced; `closed_by_user` is a user action, not Neuro resolving a research question. Only
    # `status='satisfied'` represents the evidence machinery actually closing a gap, so resolves_gap must never be
    # emitted for the other two regardless of relevance.
    # A second issue: even `status='satisfied' AND updated_at>since` does not PROVE the target transitioned from
    # open to satisfied after this answer -- a previously-satisfied target's other fields (gap notes,
    # current_evidence) can be touched later without re-opening it. A v4 snapshot records `open_evidence_target_ids`
    # at answer time, so Exact mode with a v4+ baseline can prove the transition directly: the target was open at
    # answer time AND is satisfied now. A target created after the answer and satisfied since is provable without
    # any baseline at all (the whole gap-and-resolution event happened after the baseline). Without a v4 baseline
    # (v1-v3 Exact snapshots, or Approximate mode, which never had target-state bookkeeping) the only
    # non-fabricated signal remains "created after this answer, satisfied now" -- `updated_at` alone is never
    # trusted as proof of a transition there.
    has_target_baseline = q.get("open_evidence_target_ids") is not None
    open_baseline = q.get("open_evidence_target_ids") or set()
    for tgt in conn.execute(
        "SELECT * FROM project_evidence_targets WHERE project_id=? AND status='satisfied' AND updated_at>?",
        (project_id, since)).fetchall():
        if has_target_baseline:
            provably_resolved = tgt["id"] in open_baseline or tgt["created_at"] > since
        else:
            provably_resolved = tgt["created_at"] > since
        if not provably_resolved:
            continue
        if tgt["claim_id"]:
            # linked to a Claim: include even with weak target-text overlap IF that Claim is itself relevant
            # (relevant_claim_ids); otherwise fall back to requiring the target's own question to overlap.
            if tgt["claim_id"] not in relevant_claim_ids and _claims.overlap(q["retrieval_query"], tgt["question"] or "") < OVERLAP_THRESHOLD:
                continue
        else:
            # no linked Claim at all: the target text itself must pass the topical test — a claim-less target was
            # previously included unconditionally here, the same project-wide-activity-as-relevance bug fixed for
            # the linked-Claim case.
            if _claims.overlap(q["retrieval_query"], tgt["question"] or "") < OVERLAP_THRESHOLD:
                continue
        units.append({"kind": "evidence_target", "category": "resolves_gap", "question_message_id": q["question_message_id"],
                     "question": q["question"], "claim_id": tgt["claim_id"], "target_id": tgt["id"],
                     "why_relevant": f"an open research question this conversation touched on was resolved: {tgt['question'][:120]}"})

    return units


def _max_claim_evidence_id_at(project_id: str, before_ts: float) -> int:
    """The claim_evidence.id ceiling AS OF a given time — used to find evidence rows added strictly after a
    per-question baseline (ids are monotonic with insertion, created_at is stored per-row for this lookup)."""
    r = db.connect().execute(
        "SELECT COALESCE(MAX(ce.id),0) m FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id "
        "WHERE c.project_id=? AND ce.created_at<=?", (project_id, before_ts)).fetchone()
    return int(r["m"] or 0)


def _merge(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe the same source/Finding/Claim/tension appearing against multiple questions into one unit, keeping
    every question it touches (plan §7: touches_questions, "this new evidence affects 3 things you discussed")."""
    merged: dict[tuple, dict[str, Any]] = {}
    for u in units:
        key = (u["kind"], u.get("claim_id"), u.get("tension_id"), u.get("finding_id"), u.get("target_id"),
              tuple(sorted(u.get("chunk_ids", []))) if u.get("chunk_ids") else None)
        if key in merged:
            merged[key]["touches_questions"].append({"question_message_id": u["question_message_id"], "question": u["question"][:200]})
            # the most severe category any linked question earns wins
            if CATEGORY_ORDER[u["category"]] < CATEGORY_ORDER[merged[key]["category"]]:
                merged[key]["category"] = u["category"]
        else:
            m = dict(u)
            m["touches_questions"] = [{"question_message_id": u["question_message_id"], "question": u["question"][:200]}]
            merged[key] = m
    out = list(merged.values())
    out.sort(key=lambda u: (CATEGORY_ORDER[u["category"]], -max(t["question_message_id"] for t in u["touches_questions"])))
    return out


def _attach_plan_impact(project_id: str, units: list[dict[str, Any]]) -> None:
    """Read-only (plan §7): plan_narrative.explain() / plan_impact.affected_items(), never propose_updates()
    (which WRITES pending plan_updates rows) — that happens only on an explicit 'Review plan impact' user action.

    Batched (Kyle, 2026-09-18 measurement): calling plan_narrative.explain() once PER unit does not scale — that
    function resolves the plan's cited-note map on every call, measured at ~335 ms/call, and a legacy/approximate
    conversation on a mature project can touch thousands of Claims. decision_impact.decision_impact() already
    resolves that cited-note map ONCE and answers True/False/"unknown" for a whole batch of Claim ids in a couple
    of queries. explain() — the more expensive call that also produces the human-readable narrative — now runs
    only for the Claims decision_impact says actually have plan_impact=True, expected to be a small subset. A
    Claim with plan_impact=False gets an honest empty result with no explain() call at all (there is nothing to
    narrate). A project-wide "unknown" (no plan yet, or the plan predates the evidence-citation seam) is resolved
    ONCE for the whole batch via one affected_items() probe, instead of recomputing the identical project-level
    reason once per Claim."""
    from . import decision_impact as _di
    eligible = [u for u in units if u["category"] in ("contradicts", "claim_transition") and u.get("claim_id")]
    if not eligible:
        return
    claim_ids = sorted({u["claim_id"] for u in eligible})
    impact = _di.decision_impact(project_id, claim_ids)

    true_ids = [cid for cid in claim_ids if impact.get(cid, {}).get("plan_impact") is True]
    unknown_ids = {cid for cid in claim_ids if impact.get(cid, {}).get("plan_impact") == "unknown"}
    unknown_reason: str | None = None
    if unknown_ids:
        from . import plan_impact as _pi
        probe = _pi.affected_items(project_id, claim_id=next(iter(unknown_ids)))
        unknown_reason = probe.get("reason") or "plan impact could not be determined for this project"

    explained: dict[str, dict[str, Any]] = {
        cid: plan_narrative.explain(project_id, claim_id=cid) for cid in true_ids
    }

    for u in eligible:
        cid = u["claim_id"]
        state = impact.get(cid, {}).get("plan_impact")
        if state is True:
            r = explained.get(cid) or {"known": False, "items": [], "reason": "plan impact could not be resolved"}
        elif state is False:
            r = {"known": True, "items": []}
        else:
            r = {"known": False, "items": [], "reason": unknown_reason or "plan impact could not be determined for this project"}
        u["plan_impact"] = r
        if r.get("known") and r.get("items"):
            u["category"] = "plan_impact"


def for_conversation(conversation_id: str, project_id: str | None = None) -> dict[str, Any]:
    """CHR1's entry point: the full Conversation Delta for one chat, $0, deterministic. Returns a structure CHR2/
    CHR3 can render or feed without recomputing intelligence (plan §14)."""
    pid = project_id or db.conversation_project(conversation_id)
    if not pid:
        return {"mode": "none", "nothing_new": True, "questions_checked": 0, "material_changes": [],
               "supporting_changes": [], "irrelevant_new_source_count": 0, "plan_impacts": [],
               "rollups": None, "new_claims": None, "approximate_limitations": []}
    questions = _questions(conversation_id)
    if not questions:
        baseline = db.conversation_baseline(conversation_id)
        return {"mode": "approximate" if baseline is None else "exact", "nothing_new": True, "questions_checked": 0,
               "material_changes": [], "supporting_changes": [], "irrelevant_new_source_count": 0, "plan_impacts": [],
               "rollups": None, "new_claims": None, "approximate_limitations": []}

    current_scope = set(db.project_source_ids(pid, ready_only=True))
    seen = conversation_seen_chunk_ids(conversation_id)

    all_units: list[dict[str, Any]] = []
    for q in questions:
        # per-question "elsewhere" state (Kyle's fifth correction): excludes THIS question's own answer row, so
        # the already_seen_elsewhere_in_chat annotation means "another successful answer in this conversation
        # recorded this state," never "this same answer's own snapshot."
        last_known_elsewhere = conversation_last_known_claim_state(conversation_id, exclude_message_id=q["answer_message_id"])
        all_units.extend(delta_for_question(pid, q, current_scope=current_scope, conversation_seen=seen,
                                            last_known_claim_state=last_known_elsewhere))

    # Rollup units (approximate mode only — see delta_for_question) never go through _merge/plan-impact/sort as-is:
    # they carry aggregate id SETS, not per-claim narrative fields. One exception is resolved here, once, for the
    # WHOLE conversation rather than per question (Kyle's point 4 + the measured _plan_cited_note_ids cost of
    # calling decision_impact() repeatedly): a candidate Claim that decision_impact() proves affects the current
    # Master Plan is promoted OUT of the rollup into an explicit claim_transition unit before merging.
    rollup_units = [u for u in all_units if u["kind"] == "rollup"]
    real_units = [u for u in all_units if u["kind"] != "rollup"]

    if rollup_units:
        all_candidate_rows: dict[str, dict[str, Any]] = {}
        for ru in rollup_units:
            all_candidate_rows.update(ru.get("candidate_claims") or {})
        if all_candidate_rows:
            from . import decision_impact as _di
            impact = _di.decision_impact(pid, sorted(all_candidate_rows))
            plan_true_ids = {cid for cid in all_candidate_rows if impact.get(cid, {}).get("plan_impact") is True}
            # One unit PER question that had this Claim as a candidate — same pattern every other category uses
            # (_merge's own dedup-by-claim_id accumulates them into a single unit with a full touches_questions
            # list; a single pre-merged unit here would need _merge special-cased just for this one caller).
            # Regression gate (Kyle, 2026-09-18, second correction): plan impact alone must NOT promote a Claim --
            # "Master Plan-impacting Claim unrelated to the chat: does not become a chat delta unit solely because
            # it affects the Plan." Each rollup unit now also carries relevant_claim_ids (built in delta_for_question
            # from demonstrable citation + topical overlap only, never from plan impact), so promotion requires the
            # Claim to be BOTH plan-impacting AND independently relevant to that specific question.
            for ru in rollup_units:
                promote = (ru.get("candidate_claims") or {}).keys() & plan_true_ids & (ru.get("relevant_claim_ids") or set())
                for cid in promote:
                    c = ru["candidate_claims"][cid]
                    real_units.append({"kind": "claim", "category": "claim_transition",
                                       "question_message_id": ru["question_message_id"], "question": ru["question"],
                                       "claim_id": cid, "previous_state": None,
                                       "current_state": [c["strength"], c["freshness_status"], c["status"], c["application"]],
                                       "relation": "changes",
                                       "why_relevant": f'Claim "{c["text"][:100]}" changed since this conversation and is cited in the current plan'})

    merged = _merge(real_units)
    _attach_plan_impact(pid, [u for u in merged if u["category"] in ("contradicts", "claim_transition")])
    # re-sort: plan_impact category may have been promoted by _attach_plan_impact
    merged.sort(key=lambda u: (CATEGORY_ORDER[u["category"]], -max(t["question_message_id"] for t in u["touches_questions"])))

    # new_claims progressive disclosure (Kyle, 2026-09-18, second correction, part 2): "new_claim" means a Claim is
    # newly relevant to an earlier answer with no provable prior state -- real, but the lowest-priority category
    # (CATEGORY_ORDER's last slot, sorted alongside `corroborates`), never one of the "must stay individually
    # enumerated" categories (contradicts, plan_impact, claim_transition, resolves_gap, new_finding). A synthetic
    # worst-case benchmark produced ~3,000 of these for one Exact-mode conversation when every seeded Claim happened
    # to be topically on-point -- an automatically-opened Exact chat should never get a 3,000-object payload for the
    # category that matters least. `_merge()` has already deduped these to one unit per Claim (across every question
    # that found it, with `touches_questions` accumulated), so this step operates on the FINAL population, not a
    # per-question one. Rank deterministically -- (1) strongest Claim-text/retrieval_query overlap, (2) number of
    # questions touched, (3) claim_id as a stable tie-break -- keep a small explicit sample, and report the rest as
    # a count. This is not silent dropping: explicit examples + total = the complete population, same principle as
    # the Approximate rollup's aggregate counts (§16, first hardening round).
    NEW_CLAIM_EXPLICIT_CAP = 5
    new_claim_units = [u for u in merged if u["category"] == "new_claim"]
    new_claims: dict[str, int] | None = None
    if new_claim_units:
        ranked = sorted(new_claim_units,
                        key=lambda u: (-(u.get("overlap_score") or 0.0), -len(u["touches_questions"]), u["claim_id"]))
        kept_ids = {u["claim_id"] for u in ranked[:NEW_CLAIM_EXPLICIT_CAP]}
        merged = [u for u in merged if u["category"] != "new_claim" or u["claim_id"] in kept_ids]
        new_claims = {"total": len(new_claim_units), "shown": min(len(new_claim_units), NEW_CLAIM_EXPLICIT_CAP)}

    modes = {q["mode"] for q in questions}
    mode = "exact" if modes == {"exact"} else "approximate" if modes == {"approximate"} else "mixed"
    material = [u for u in merged if u["category"] in ("contradicts", "plan_impact", "claim_transition", "resolves_gap", "new_finding")]
    supporting = [u for u in merged if u["category"] in ("new_excerpt", "corroborates", "new_claim")]

    # count new sources that never surfaced any unit — the "15 sources added, none matched" message
    surfaced_sources = {u.get("source_id") for u in merged if u.get("source_id")}
    all_newly_available: set[str] = set()
    for q in questions:
        if q["mode"] == "exact" and q["scope_source_ids"] is not None:
            all_newly_available |= (current_scope - q["scope_source_ids"])

    # Rollup counts (Kyle, 2026-09-18): deterministic aggregate for what approximate mode found but cannot
    # honestly attribute to a specific Claim/source — "16,201 related Claim updates it cannot safely classify
    # against the original answers", never silently dropped, never individually enumerated. Anything that DID
    # earn an explicit unit above (a real Claim/source id already in `merged`) is subtracted so the same fact is
    # never both an explicit item and a rollup count.
    rollups: dict[str, int] | None = None
    if rollup_units:
        explicit_claim_ids = {u.get("claim_id") for u in merged if u.get("claim_id")}
        explicit_source_ids = {u.get("source_id") for u in merged if u.get("source_id")}
        rollup_source_ids: set[str] = set()
        rollup_claim_ids: set[str] = set()
        rollup_ce_ids: set[str] = set()
        for ru in rollup_units:
            rollup_source_ids |= ru.get("rollup_source_ids") or set()
            rollup_claim_ids |= ru.get("rollup_claim_ids") or set()
            rollup_ce_ids |= ru.get("rollup_claim_evidence_ids") or set()
        rollup_source_ids -= explicit_source_ids
        rollup_claim_ids -= explicit_claim_ids
        rollup_ce_ids -= explicit_claim_ids

        # Findings created after the earliest approximate baseline, minus ones that already earned an explicit
        # new_finding unit — one bulk COUNT-shaped query, not a re-run of the per-question overlap loop.
        approx_since = [q["answered_at"] for q in questions if q["mode"] != "exact"]
        findings_added = 0
        if approx_since:
            explicit_finding_ids = {u.get("finding_id") for u in merged if u.get("finding_id")}
            all_findings = {r["id"] for r in db.connect().execute(
                "SELECT id FROM project_notes WHERE project_id=? AND created_at>? AND status IN ('approved','suggested')",
                (pid, min(approx_since))).fetchall()}
            findings_added = len(all_findings - explicit_finding_ids)

        rollups = {
            "sources_changed": len(rollup_source_ids),
            "findings_added": findings_added,
            "claims_added_or_updated": len(rollup_claim_ids),
            "claim_evidence_added": len(rollup_ce_ids),
        }
    irrelevant = len(all_newly_available - surfaced_sources)

    approximate_limitations: list[str] = []
    if mode in ("approximate", "mixed"):
        approximate_limitations.append(
            "This chat predates evidence snapshots, so Neuro can identify research that changed after the answer, "
            "but cannot reconstruct every source or Claim state the original conversation had available.")

    rollup_has_activity = bool(rollups) and any(rollups.values())

    return {
        "mode": mode,
        "nothing_new": not material and not supporting and not rollup_has_activity,
        "questions_checked": len(questions),
        "latest_activity_at": max(q["answered_at"] for q in questions),
        "material_changes": material,
        "supporting_changes": supporting,
        "irrelevant_new_source_count": irrelevant,
        "plan_impacts": [u for u in merged if u.get("plan_impact", {}).get("known") and u["plan_impact"].get("items")],
        "rollups": rollups,
        "new_claims": new_claims,
        "approximate_limitations": approximate_limitations,
    }


def get_delta(conversation_id: str, project_id: str | None = None) -> dict[str, Any]:
    """Cached entry point (plan §11): keyed on (conversation_id, CONVERSATION identity + conversation_delta_revision
    (project_id)) — not project_view_revision, not time, and not the project revision alone. Kyle's correction
    (2026-09-18): conversation_delta_revision() tracks the PROJECT's evidence state, which does not move just
    because this conversation gained another successful question/answer with no project-level change — so caching
    on it alone would return a stale questions_checked/material_changes after a brand new turn. The conversation's
    own append-only message id (db.conversation_message_revision) is folded into the key for exactly that reason."""
    from . import cache
    pid = project_id or db.conversation_project(conversation_id)
    if not pid:
        return for_conversation(conversation_id, project_id)
    rev = f"{db.conversation_message_revision(conversation_id)}|{db.conversation_delta_revision(pid)}"
    key = f"conversation_delta:{conversation_id}"
    return cache.get_or_compute(key, rev, lambda: for_conversation(conversation_id, pid), label="conversation_delta")


# =============================================================================================================
# CHR3 — the paid synthesis is deliberately built from the delta's evidence, not from another broad retrieval.
# It lives here, beside the delta, so the source-scope gate cannot drift from the code that decides what changed.

def _citation_chunk_ids(citations: list[dict[str, Any]], allowed_sources: set[str]) -> list[int]:
    """Resolve persisted chat/Note citations to their closest real chunks.

    Historic citations predate stable chunk ids, but they do contain source_id and usually start/end offsets.  This
    is intentionally conservative: an unresolved citation contributes no invented passage, and every returned
    chunk remains within the current project's source membership.
    """
    out: list[int] = []
    for cite in citations:
        sid = cite.get("source_id")
        if not sid or sid not in allowed_sources:
            continue
        chunks = db.get_chunks(sid)
        if not chunks:
            continue
        start = cite.get("start")
        if start is None:
            out.append(int(chunks[0]["id"]))
            continue
        nearest = min(chunks, key=lambda c: abs(float(c.get("start") or 0) - float(start)))
        out.append(int(nearest["id"]))
    return out


def refresh_evidence(conversation_id: str, project_id: str | None = None,
                     delta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return CHR3's bounded, source-scoped evidence selection.

    ``new`` passages come only from concrete Conversation Delta units: new excerpts, Finding citations, and the
    source evidence behind changed Claims/tensions.  ``comparison`` passages come only from citations already
    present in this conversation.  No search call is made here, and no source outside this project's current
    membership can pass the gate.  The caller turns these chunks into normal chat hits.
    """
    pid = project_id or db.conversation_project(conversation_id)
    if not pid:
        return {"project_id": None, "new_chunk_ids": [], "comparison_chunk_ids": [], "baseline_message_id": None,
                "since": None, "delta_summary": {"material": 0, "supporting": 0}}
    result = delta if delta is not None else get_delta(conversation_id, pid)
    allowed_sources = set(db.project_source_ids(pid, ready_only=False))
    units = list(result.get("material_changes") or []) + list(result.get("supporting_changes") or [])
    new_ids: list[int] = []
    finding_ids: set[int] = set()
    claim_ids: set[str] = set()
    for unit in units:
        sid = unit.get("source_id")
        if sid and sid not in allowed_sources:
            continue
        new_ids.extend(int(cid) for cid in (unit.get("chunk_ids") or []) if cid is not None)
        if unit.get("finding_id") is not None:
            finding_ids.add(int(unit["finding_id"]))
        if unit.get("claim_id"):
            claim_ids.add(str(unit["claim_id"]))

    conn = db.connect()
    if finding_ids:
        marks = ",".join("?" * len(finding_ids))
        rows = conn.execute(f"SELECT citations FROM project_notes WHERE id IN ({marks})", tuple(sorted(finding_ids))).fetchall()
        for row in rows:
            try:
                citations = json.loads(row["citations"] or "[]")
            except ValueError:
                citations = []
            new_ids.extend(_citation_chunk_ids(citations, allowed_sources))
    if claim_ids:
        marks = ",".join("?" * len(claim_ids))
        rows = conn.execute(
            f"SELECT ce.source_id, ce.start FROM claim_evidence ce JOIN project_claims c ON c.id=ce.claim_id "
            f"WHERE c.project_id=? AND ce.claim_id IN ({marks})", (pid, *sorted(claim_ids))).fetchall()
        new_ids.extend(_citation_chunk_ids([{"source_id": r["source_id"], "start": r["start"]} for r in rows], allowed_sources))

    comparison_ids: list[int] = []
    for row in _rows(conversation_id):
        if row["role"] != "assistant":
            continue
        comparison_ids.extend(_citation_chunk_ids(row.get("citations") or [], allowed_sources))

    def ordered_unique(ids: list[int], *, exclude: set[int] | None = None) -> list[int]:
        seen = exclude or set()
        out = []
        for cid in ids:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
        return out

    new_chunk_ids = ordered_unique(new_ids)
    comparison_chunk_ids = ordered_unique(comparison_ids, exclude=set(new_chunk_ids))
    baseline = db.conversation_baseline(conversation_id)
    return {
        "project_id": pid,
        "new_chunk_ids": new_chunk_ids,
        "comparison_chunk_ids": comparison_chunk_ids,
        "baseline_message_id": baseline.get("message_id") if baseline else None,
        "since": baseline.get("answered_at") if baseline else result.get("latest_activity_at"),
        "delta_summary": {"material": len(result.get("material_changes") or []), "supporting": len(result.get("supporting_changes") or [])},
    }
