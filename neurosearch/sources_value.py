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
