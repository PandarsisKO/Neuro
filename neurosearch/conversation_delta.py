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
from typing import Any

from . import db

log = logging.getLogger(__name__)

SNAPSHOT_VERSION = 2   # v2 (hardening, 2026-09-18): adds "complete" — see below. A v1 snapshot (no key at all,
                       # already shipped and live) is treated as complete for backward compatibility; CHR1 only
                       # downgrades a snapshot that EXPLICITLY says complete=False.


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
        "shown_chunk_ids": shown_chunk_ids,
        "shown_source_ids": shown_source_ids,
        "full_context": bool(full_context),
        "question_message_id": question_message_id,
        "research_revision": None,
        "max_claim_evidence_id": None,
        "claim_state": {},
    }
    if not project_id:
        return snap   # no project: nothing further to gather, and nothing failed — still complete
    try:
        snap["research_revision"] = db.project_research_revision(project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("evidence snapshot: research revision unavailable: %s", e)
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
        out.append({
            "question_message_id": u["id"], "question": u["content"], "answer_message_id": answer["id"],
            "answered_at": answer["created_at"],
            "mode": "exact" if exact else "approximate",
            "scope_source_ids": set(ev["scope_source_ids"]) if exact and ev else None,
            "shown_chunk_ids": set(ev["shown_chunk_ids"]) if exact and ev else None,
            "shown_source_ids": set(ev["shown_source_ids"]) if ev else {c.get("source_id") for c in answer["citations"] if c.get("source_id")},
            "claim_state": ev.get("claim_state", {}) if exact and ev else {},
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


def conversation_last_known_claim_state(conversation_id: str) -> dict[str, list]:
    """The last state this conversation actually knew for each touched Claim — folded chronologically across every
    successful snapshot (later overwrites earlier), so a transition is judged against what the conversation was
    told, not against the Claim's state at only the newest turn."""
    known: dict[str, list] = {}
    for r in _rows(conversation_id):
        if r["role"] != "assistant":
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
        # Approximate baseline (plan §12): only temporal signals are honest here — no shown_chunk_ids exist to
        # diff against, so "unseen" is never claimed, only "added since".
        newly_available = current_scope - (q.get("shown_source_ids") or set())
    else:
        newly_available = (current_scope - (q["scope_source_ids"] or set()))
        # a source that WAS in scope but became ready / re-transcribed since this answer
        if q["scope_source_ids"]:
            marks = ",".join("?" * len(q["scope_source_ids"]))
            revised = {r["id"] for r in conn.execute(
                f"SELECT id FROM sources WHERE id IN ({marks}) AND status='ready' AND updated_at>?",
                (*q["scope_source_ids"], since)).fetchall()}
            newly_available |= revised

    # category: new relevant excerpt (6) — FTS-only, $0, from newly-available sources, minus what this
    # conversation has already been shown anywhere (epistemic newness)
    if newly_available and q["question"].strip():
        from .search import search_fts
        for h in search_fts(q["question"], limit=FTS_PER_QUESTION_LIMIT, source_ids=sorted(newly_available)):
            if h["chunk_id"] in conversation_seen:
                continue
            units.append({"kind": "new_excerpt", "category": "new_excerpt", "question_message_id": q["question_message_id"],
                         "question": q["question"], "source_id": h["source_id"], "chunk_ids": [h["chunk_id"]],
                         "why_relevant": "matches this question against newly available material", "locator": h.get("timestamp"),
                         "title": h.get("title"), "text": h["text"][:300]})

    # category: new Finding (5), overlap-routed — old OR new sources, both allowed (plan §3)
    findings = conn.execute(
        "SELECT id, content, source_id FROM project_notes WHERE project_id=? AND created_at>? AND status IN ('approved','suggested')",
        (project_id, since)).fetchall()
    scored = []
    for f in findings:
        ov = _claims.overlap(q["question"], f["content"])
        if ov >= OVERLAP_THRESHOLD:
            scored.append((ov, f))
    scored.sort(key=lambda t: -t[0])
    for ov, f in scored[:FINDINGS_PER_QUESTION_CAP]:
        units.append({"kind": "new_finding", "category": "new_finding", "question_message_id": q["question_message_id"],
                     "question": q["question"], "finding_id": f["id"], "source_id": f["source_id"],
                     "why_relevant": f"overlap={round(ov, 2)} with this question", "text": f["content"][:400]})

    # candidate Claim set: touched by shown/newly-available sources OR overlaps the question text
    touch_sources = (q.get("shown_source_ids") or set()) | newly_available
    touched = dict(_touched_claims_for_sources(project_id, touch_sources))
    for r in conn.execute("SELECT * FROM project_claims WHERE project_id=? AND updated_at>?", (project_id, since)).fetchall():
        if r["id"] in touched:
            continue
        if _claims.overlap(q["question"], r["text"]) >= OVERLAP_THRESHOLD:
            touched[r["id"]] = dict(r)

    for cid, c in touched.items():
        if c["updated_at"] <= since:
            continue
        prev = last_known_claim_state.get(cid) or q["claim_state"].get(cid)
        cur = [c["strength"], c["freshness_status"], c["status"], c["application"]]
        # new evidence attached to this Claim since the baseline?
        ce_rows = conn.execute("SELECT id FROM claim_evidence WHERE claim_id=? AND id>?",
                               (cid, _max_claim_evidence_id_at(project_id, since))).fetchall()
        # Epistemic newness for a Claim: prev is None when the conversation's baseline predates the Claim's own
        # creation, which is exactly "the conversation has never seen this Claim" — treated as a transition (from
        # nothing known to something known), not mere corroboration of an already-known state.
        transitioned = prev != cur
        if not transitioned and not ce_rows:
            continue
        relation = "changes" if transitioned else "corroborates"
        category = "claim_transition" if transitioned else "corroborates"
        units.append({"kind": "claim", "category": category, "question_message_id": q["question_message_id"],
                     "question": q["question"], "claim_id": cid, "previous_state": prev, "current_state": cur,
                     "relation": relation, "why_relevant": f'Claim "{c["text"][:100]}" ' + (
                         f"changed: {prev} → {cur}" if transitioned else "gained new evidence")})

    # category: contradiction / reversal — open tensions on a touched Claim, created after the baseline
    if touched:
        marks = ",".join("?" * len(touched))
        for t in conn.execute(
            f"SELECT * FROM research_tensions WHERE project_id=? AND claim_id IN ({marks}) AND status='open' AND created_at>?",
            (project_id, *touched.keys(), since)).fetchall():
            units.append({"kind": "tension", "category": "contradicts", "question_message_id": q["question_message_id"],
                         "question": q["question"], "claim_id": t["claim_id"], "tension_id": t["id"], "relation": "contradicts",
                         "why_relevant": f"a new open {t['kind'].lower()} tension appeared on a Claim this answer relied on"})

    # category: resolved evidence target / gap
    for tgt in conn.execute(
        "SELECT * FROM project_evidence_targets WHERE project_id=? AND status<>'open' AND updated_at>?",
        (project_id, since)).fetchall():
        if tgt["claim_id"] and tgt["claim_id"] not in touched and _claims.overlap(q["question"], tgt["question"] or "") < OVERLAP_THRESHOLD:
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
    """Read-only (plan §7): plan_narrative.explain() only, never propose_updates() (which WRITES pending
    plan_updates rows) — that happens only on an explicit 'Review plan impact' user action."""
    for u in units:
        if u["category"] not in ("contradicts", "claim_transition"):
            continue
        r = plan_narrative.explain(project_id, claim_id=u.get("claim_id"), tension_id=u.get("tension_id"))
        u["plan_impact"] = r
        if r.get("known") and r.get("items"):
            u["category"] = "plan_impact"


def for_conversation(conversation_id: str, project_id: str | None = None) -> dict[str, Any]:
    """CHR1's entry point: the full Conversation Delta for one chat, $0, deterministic. Returns a structure CHR2/
    CHR3 can render or feed without recomputing intelligence (plan §14)."""
    pid = project_id or db.conversation_project(conversation_id)
    if not pid:
        return {"mode": "none", "nothing_new": True, "questions_checked": 0, "material_changes": [],
               "supporting_changes": [], "irrelevant_new_source_count": 0, "plan_impacts": []}
    questions = _questions(conversation_id)
    if not questions:
        baseline = db.conversation_baseline(conversation_id)
        return {"mode": "approximate" if baseline is None else "exact", "nothing_new": True, "questions_checked": 0,
               "material_changes": [], "supporting_changes": [], "irrelevant_new_source_count": 0, "plan_impacts": []}

    current_scope = set(db.project_source_ids(pid, ready_only=True))
    seen = conversation_seen_chunk_ids(conversation_id)
    last_known = conversation_last_known_claim_state(conversation_id)

    all_units: list[dict[str, Any]] = []
    for q in questions:
        all_units.extend(delta_for_question(pid, q, current_scope=current_scope, conversation_seen=seen,
                                            last_known_claim_state=last_known))
    merged = _merge(all_units)
    _attach_plan_impact(pid, [u for u in merged if u["category"] in ("contradicts", "claim_transition")])
    # re-sort: plan_impact category may have been promoted by _attach_plan_impact
    merged.sort(key=lambda u: (CATEGORY_ORDER[u["category"]], -max(t["question_message_id"] for t in u["touches_questions"])))

    modes = {q["mode"] for q in questions}
    mode = "exact" if modes == {"exact"} else "approximate" if modes == {"approximate"} else "mixed"
    material = [u for u in merged if u["category"] in ("contradicts", "plan_impact", "claim_transition", "resolves_gap", "new_finding")]
    supporting = [u for u in merged if u["category"] in ("new_excerpt", "corroborates")]

    # count new sources that never surfaced any unit — the "15 sources added, none matched" message
    surfaced_sources = {u.get("source_id") for u in merged if u.get("source_id")}
    all_newly_available: set[str] = set()
    for q in questions:
        if q["mode"] == "exact" and q["scope_source_ids"] is not None:
            all_newly_available |= (current_scope - q["scope_source_ids"])
    irrelevant = len(all_newly_available - surfaced_sources)

    return {
        "mode": mode,
        "nothing_new": not material and not supporting,
        "questions_checked": len(questions),
        "latest_activity_at": max(q["answered_at"] for q in questions),
        "material_changes": material,
        "supporting_changes": supporting,
        "irrelevant_new_source_count": irrelevant,
        "plan_impacts": [u for u in merged if u.get("plan_impact", {}).get("known") and u["plan_impact"].get("items")],
    }


def get_delta(conversation_id: str, project_id: str | None = None) -> dict[str, Any]:
    """Cached entry point (plan §11): keyed on (conversation_id, conversation_delta_revision(project_id)) — NOT
    project_view_revision, and not time. A second identical call within the same revision is a cache hit."""
    from . import cache
    pid = project_id or db.conversation_project(conversation_id)
    if not pid:
        return for_conversation(conversation_id, project_id)
    rev = db.conversation_delta_revision(pid)
    key = f"conversation_delta:{conversation_id}"
    return cache.get_or_compute(key, rev, lambda: for_conversation(conversation_id, pid), label="conversation_delta")
