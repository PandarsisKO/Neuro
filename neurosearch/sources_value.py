"""S2 — Source Value: what a source GAVE the project, measured from rows that exist ($0, deterministic, one pass).

A source's value is what its findings became — importance the user assigned, Claims (strong or not), Master Plan evidence,
chat citations — plus the user's own priority star. It is never declared by a model. Every list in Sources and Findings can
sort and filter by it; the stale triage (S1) and the under-read signal (D3) read the same numbers.

value_score (documented weights; a source with only importance-1 findings scores near zero):
    +40 evidence in the Master Plan · +30 priority star · +10 per Strong Claim it evidences (cap 30)
    +3 per approved finding rated 4–5 (cap 30) · +2 per chat citation (cap 20) · +1 per other approved finding (cap 10)
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from . import db

W_PLAN, W_PRIORITY, W_STRONG, W_STRONG_CAP, W_IMPORTANT, W_IMPORTANT_CAP, W_CITE, W_CITE_CAP, W_OTHER, W_OTHER_CAP = 40, 30, 10, 30, 3, 30, 2, 20, 1, 10
MATTERS_RATED = 3     # "matters" is a RULE, not a score threshold: plan evidence · priority star · evidence of a strong Claim · ≥ 3 approved findings rated 4–5


def compute(project_id: str) -> dict[str, dict[str, Any]]:
    """{source_id: value} for every source that has any trace in the project (findings, Claims, plan, chat, priority)."""
    conn = db.connect()
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"findings": {"approved": 0, "suggested": 0, "reserve": 0, "dismissed": 0},
                                                          "importance": {"max": 0, "sum": 0, "n4plus": 0},
                                                          "claims": {"evidence_rows": 0, "strong": 0, "accepted": 0},
                                                          "used": {"plan_evidence": 0, "chat_citations": 0, "last_used_at": None},
                                                          "priority": False})
    for r in conn.execute("SELECT source_id, status, COUNT(*) n, MAX(importance) mx, SUM(COALESCE(importance,0)) sm, "
                          "SUM(CASE WHEN importance>=4 AND status='approved' THEN 1 ELSE 0 END) n4 FROM project_notes "
                          "WHERE project_id=? AND source_id IS NOT NULL GROUP BY source_id, status", (project_id,)).fetchall():
        v = out[r["source_id"]]
        v["findings"][r["status"]] = int(r["n"])
        if r["status"] == "approved":
            v["importance"]["max"] = int(r["mx"] or 0)
            v["importance"]["sum"] = int(r["sm"] or 0)
            v["importance"]["n4plus"] = int(r["n4"] or 0)
    # a strong Claim counts for the source only when its evidence there is INDEPENDENT (a derivative repeat of the primary is not the source that matters)
    for r in conn.execute("""SELECT e.source_id, COUNT(*) n, SUM(CASE WHEN c.strength='strong' AND COALESCE(e.independent,0)=1 THEN 1 ELSE 0 END) strong,
                                    SUM(CASE WHEN c.status='accepted' THEN 1 ELSE 0 END) acc
                             FROM claim_evidence e JOIN project_claims c ON c.id=e.claim_id
                             WHERE c.project_id=? AND c.status<>'rejected' GROUP BY e.source_id""", (project_id,)).fetchall():
        if r["source_id"]:
            out[r["source_id"]]["claims"] = {"evidence_rows": int(r["n"]), "strong": int(r["strong"] or 0), "accepted": int(r["acc"] or 0)}
    plan = db.latest_plan(project_id)
    if plan:
        for v in ((plan.get("plan") or {}).get("_evidence") or {}).values():
            if v.get("source_id"):
                out[v["source_id"]]["used"]["plan_evidence"] += 1
                out[v["source_id"]]["used"]["last_used_at"] = max(out[v["source_id"]]["used"]["last_used_at"] or 0, plan.get("created_at") or 0)
    for r in conn.execute("""SELECT m.citations, m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id
                             WHERE c.project_id=? AND m.role='assistant' AND m.citations IS NOT NULL AND m.citations<>'[]'""", (project_id,)).fetchall():
        try:
            cites = json.loads(r["citations"]) or []
        except ValueError:
            continue
        seen = set()
        for c in cites:
            sid = (c or {}).get("source_id")
            if sid and sid not in seen:
                seen.add(sid)
                out[sid]["used"]["chat_citations"] += 1
                out[sid]["used"]["last_used_at"] = max(out[sid]["used"]["last_used_at"] or 0, r["created_at"] or 0)
    for r in conn.execute("SELECT source_id FROM project_sources WHERE project_id=? AND priority=1", (project_id,)).fetchall():
        out[r["source_id"]]["priority"] = True
    for sid, v in out.items():
        v["value_score"] = score(v)
        v["why"] = why(v)
        v["matters"] = bool(v["why"])
        v["never_used"] = not (v["used"]["plan_evidence"] or v["used"]["chat_citations"] or v["claims"]["evidence_rows"])
        v["label"] = label(v)
    return dict(out)


def subreddit_catalog_yield(project_id: str, collection_id: str) -> dict[str, Any]:
    """Evidence yield for explicitly captured members of one subreddit catalog.

    Candidate membership itself is metadata, never evidence. A member contributes only when its resolved Source is
    ready and is an included member of this project; the DISTINCT query prevents cross-post/candidate joins from
    inflating source, finding, or Claim counts.
    """
    conn = db.connect()
    source_ids = [r["source_id"] for r in conn.execute("""SELECT DISTINCT c.source_id
        FROM collection_candidates cc JOIN candidates c ON c.id=cc.candidate_id
        JOIN sources s ON s.id=c.source_id AND s.status='ready'
        JOIN project_sources ps ON ps.source_id=s.id AND ps.project_id=? AND ps.excluded=0
        WHERE cc.collection_id=? AND c.source_id IS NOT NULL""", (project_id, collection_id)).fetchall()]
    values = compute(project_id)
    selected = [values.get(sid, empty()) for sid in source_ids]
    return {"captured_threads": len(source_ids),
            "findings": sum(v["findings"].get("approved", 0) for v in selected),
            "high_importance_findings": sum(v["importance"].get("n4plus", 0) for v in selected),
            "claim_evidence_rows": sum(v["claims"].get("evidence_rows", 0) for v in selected),
            "distinct_claims_supported": conn.execute("""SELECT COUNT(DISTINCT e.claim_id) FROM claim_evidence e
                JOIN project_claims pc ON pc.id=e.claim_id AND pc.project_id=?
                WHERE e.source_id IN (SELECT DISTINCT c.source_id FROM collection_candidates cc
                    JOIN candidates c ON c.id=cc.candidate_id JOIN project_sources ps ON ps.source_id=c.source_id
                    WHERE cc.collection_id=? AND ps.project_id=? AND ps.excluded=0)""",
                (project_id, collection_id, project_id)).fetchone()[0],
            "source_ids": source_ids}


def score(v: dict[str, Any]) -> int:
    f, imp, cl, u = v["findings"], v["importance"], v["claims"], v["used"]
    other = max(0, f.get("approved", 0) - imp["n4plus"])
    return int((W_PLAN if u["plan_evidence"] else 0) + (W_PRIORITY if v["priority"] else 0) + min(W_STRONG_CAP, W_STRONG * cl["strong"])
               + min(W_IMPORTANT_CAP, W_IMPORTANT * imp["n4plus"]) + min(W_CITE_CAP, W_CITE * u["chat_citations"]) + min(W_OTHER_CAP, W_OTHER * other))


def why(v: dict[str, Any]) -> list[str]:
    """Why a source matters, in the words the triage card and the drawer show."""
    out = []
    if v["priority"]:
        out.append("priority source")
    if v["used"]["plan_evidence"]:
        out.append("evidence in the Master Plan")
    if v["claims"]["strong"]:
        out.append("evidence of a strong Claim")
    if v["importance"]["n4plus"] >= MATTERS_RATED:
        out.append(f"{v['importance']['n4plus']} approved findings rated 4–5")
    return out


def label(v: dict[str, Any]) -> str:
    """One line: '12 findings · 3 strong Claims · in the plan · cited 7×'."""
    f, cl, u = v["findings"], v["claims"], v["used"]
    parts = []
    a = f.get("approved", 0)
    if a:
        parts.append(f"{a} finding{'s' if a != 1 else ''}" + (f" ({v['importance']['n4plus']} rated 4–5)" if v["importance"]["n4plus"] else ""))
    elif f.get("suggested", 0):
        parts.append(f"{f['suggested']} suggested")
    if cl["strong"]:
        parts.append(f"{cl['strong']} strong Claim{'s' if cl['strong'] != 1 else ''}")
    elif cl["evidence_rows"]:
        parts.append(f"evidence for {cl['evidence_rows']} Claim{'s' if cl['evidence_rows'] != 1 else ''}")
    if u["plan_evidence"]:
        parts.append("in the plan")
    if u["chat_citations"]:
        parts.append(f"cited {u['chat_citations']}×")
    if v["priority"]:
        parts.append("★ priority")
    return " · ".join(parts) or "nothing yet"


def empty() -> dict[str, Any]:
    v = {"findings": {"approved": 0, "suggested": 0, "reserve": 0, "dismissed": 0}, "importance": {"max": 0, "sum": 0, "n4plus": 0},
         "claims": {"evidence_rows": 0, "strong": 0, "accepted": 0}, "used": {"plan_evidence": 0, "chat_citations": 0, "last_used_at": None}, "priority": False}
    v.update({"value_score": 0, "why": [], "matters": False, "never_used": True, "label": "nothing yet"})
    return v


# ------------------------------------------------------------------ S3: the source drawer — everything one source gave, in one place ($0)

def _walk_plan_uses(node: Any, eids: set[str], label: str | None, out: list[dict[str, Any]], depth: int = 0) -> None:
    """Every place in the plan BODY that cites one of this source's evidence ids, with the nearest enclosing title."""
    if depth > 8:
        return
    if isinstance(node, dict):
        here = str(node.get("title") or node.get("name") or node.get("step") or "") or label
        ev = node.get("evidence")
        if isinstance(ev, list) and any(isinstance(e, str) and e in eids for e in ev):
            out.append({"where": here or "the plan", "text": str(node.get("text") or node.get("detail") or node.get("description") or "")[:220]})
        for k, v in node.items():
            if not str(k).startswith("_"):
                _walk_plan_uses(v, eids, here if k not in ("phases", "tasks", "steps") else here, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_plan_uses(v, eids, label, out, depth + 1)


def used_in(project_id: str, source_id: str) -> dict[str, Any]:
    """Where this source actually shows up: Master Plan steps that cite it, and chat answers that cited it."""
    conn = db.connect()
    plan_uses: list[dict[str, Any]] = []
    plan = db.latest_plan(project_id)
    version = None
    if plan:
        body = plan.get("plan") or {}
        eids = {eid for eid, v in (body.get("_evidence") or {}).items() if v.get("source_id") == source_id}
        if eids:
            _walk_plan_uses({k: v for k, v in body.items() if not str(k).startswith("_")}, eids, None, plan_uses)
        version = plan.get("version")
    seen, chat_uses = set(), []
    for r in conn.execute("""SELECT m.id, m.content, m.created_at, c.id AS conv_id, c.title FROM messages m JOIN conversations c ON c.id=m.conversation_id
                             WHERE c.project_id=? AND m.role='assistant' AND m.citations LIKE ? ORDER BY m.created_at DESC LIMIT 40""",
                          (project_id, f"%{source_id}%")).fetchall():
        try:
            cites = json.loads(conn.execute("SELECT citations FROM messages WHERE id=?", (r["id"],)).fetchone()["citations"] or "[]")
        except (ValueError, TypeError):
            cites = []
        locs = [str(c.get("timestamp") or "") for c in cites if (c or {}).get("source_id") == source_id]
        if not locs or r["id"] in seen:
            continue
        seen.add(r["id"])
        chat_uses.append({"conversation_id": r["conv_id"], "conversation": r["title"] or "untitled chat", "at": r["created_at"],
                          "locators": sorted({l for l in locs if l})[:4], "snippet": " ".join((r["content"] or "").split())[:200]})
    return {"plan": {"version": version, "uses": plan_uses[:12]}, "chat": chat_uses[:12]}


def digest(project_id: str, source_id: str) -> dict[str, Any]:
    """One source, everything it gave this project: value, its findings by status (with what used each), the Claims they
    became, where it shows up, and its staleness tier with the one-source actions. $0, no model call."""
    from . import findings as findings_mod
    from . import findings_view, staleness
    src = db.get_source(source_id)
    if not src or not db.get_project(project_id):
        raise KeyError("source or project not found")
    v = compute(project_id).get(source_id) or empty()
    fq = findings_view.query(project_id, status="all", source_id=source_id, sort="importance", limit=findings_view.PAGE_MAX)
    by_status: dict[str, list[dict[str, Any]]] = {}
    for f in fq["findings"]:
        by_status.setdefault(f["status"], []).append({"id": f["id"], "title": f.get("title"), "content": f.get("content"), "importance": f.get("importance"),
                                                      "locator": ((f.get("citations") or [{}])[0] or {}).get("timestamp"),
                                                      "link": ((f.get("citations") or [{}])[0] or {}).get("link"), "used": f["used"], "area": f.get("area")})
    claims_rows = [dict(r) for r in db.connect().execute(
        """SELECT c.id, c.text, c.strength, c.status, c.claim_type, c.freshness_status, e.independent, e.locator, e.stale
           FROM claim_evidence e JOIN project_claims c ON c.id=e.claim_id
           WHERE c.project_id=? AND e.source_id=? AND c.status<>'rejected'
           ORDER BY CASE c.strength WHEN 'strong' THEN 0 WHEN 'developing' THEN 1 ELSE 2 END, c.created_at LIMIT 40""", (project_id, source_id)).fetchall()]
    st = next((x for x in staleness.assess(project_id)["sources"] if x["source_id"] == source_id), {})
    tier = None
    if st.get("status") in ("stale", "legacy_unverified"):
        tiers = staleness.triage(project_id)["tiers"]
        tier = next((k for k, t in tiers.items() if any(r["source_id"] == source_id for r in t["sources"])), None)
    # send-screenshot provenance (repair round, item 9: "stored but not surfaced"): PROJECT-scoped only, never a
    # cross-project or global-most-recent fallback -- a capture taken while working in a different project must
    # never surface as evidence on this project's copy of the same (dedup-shared) source. Newest-first, one shown.
    captures = db.get_capture_events_for_source(source_id, project_id=project_id)
    latest_capture = captures[0] if captures else None
    return {"source": {"id": source_id, "title": src.get("title") or src["url"], "url": src["url"], "platform": src["platform"], "channel": src.get("channel"),
                       "published_at": src.get("published_at"), "duration": src.get("duration"), "status": src["status"],
                       "long": findings_mod.is_long(src), "depth": (db.get_analysis(project_id, source_id, "summary") or {}).get("depth"),
                       "summary": (db.get_analysis(project_id, source_id, "summary") or {}).get("summary")},
            "value": {"score": v["value_score"], "label": v["label"], "why": v["why"], "matters": v["matters"], "never_used": v["never_used"],
                      "priority": v["priority"], "findings": v["findings"], "importance": v["importance"], "claims": v["claims"], "used": v["used"]},
            "findings": by_status, "findings_total": fq["total"], "claims": claims_rows,
            "used_in": used_in(project_id, source_id),
            "staleness": {"status": st.get("status"), "reasons": st.get("reasons") or [], "tier": tier, "estimate": st.get("estimate"),
                          "analysed_at": st.get("analysed_at"), "model": st.get("model")},
            "capture": ({"url": latest_capture["capture_url"], "page_title": latest_capture["capture_page_title"],
                        "captured_at": latest_capture["captured_at"], "mode": latest_capture["capture_mode"],
                        "partial_reason": latest_capture["capture_partial_reason"], "note": latest_capture["capture_note"]}
                       if latest_capture else None)}
