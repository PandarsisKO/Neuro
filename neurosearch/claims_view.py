"""R7 — the Claims workbench ($0): filter, facet, sort, page and batch-decide the project's Claims.

RESEARCH-TAB.md §5 asked for this when the R2 shell was designed — "Claims as a workbench, not a list: filters
(needs decision · accepted · weak · stale · by topic), batch accept/reject, one plain-language line per Claim... the
internals behind an expander" — and §5 also asked to rename the internal vocabulary in the UI. R2 (0.44.0) moved the
Claims list under its own pane but never rebuilt it: it stayed the same capped, unfiltered, jargon-carrying list
(`knowledge.state()`'s `claims` field, 300 of however many). This module is that rebuild.

Every filter composes (AND) over the FULL claim set (never the 300-cap `knowledge.state` uses for its bootstrap page —
that cap exists to keep the map/tensions/targets bundle small; a workbench that is ABOUT Claims must see all of them).
`plain()` turns strength/freshness_status/claim_type/status into one sentence a first-time reader can act on without a
glossary; the raw fields stay in the payload underneath for anyone who wants them (chat tools, exports, the drawer).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from . import claims as claims_mod
from . import db

PAGE_MAX = 300

STRENGTH_LABEL = {"strong": "well evidenced", "developing": "building evidence", "weak": "thin evidence", "unsupported": "no evidence yet"}
FRESHNESS_LABEL = {"needs_refresh": "may need a refresh", "stale": "likely outdated", "uncertain": "unclear if still current"}
TYPE_LABEL = {"governing": "a rule", "historical": "history", "expert_interpretation": "an expert's interpretation", "practice": "common practice",
              "experiential": "someone's experience", "market": "a market condition", "causal": "cause and effect", "novel_tactic": "a specific tactic", "other": "a claim"}
STATUS_LABEL = {"proposed": "not yet decided", "accepted": "accepted", "rejected": "rejected", "superseded": "superseded"}
NEEDS_DECISION_STRENGTHS = ("strong", "developing")   # weak/unsupported Claims are not yet worth a yes/no


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9'-]+", (s or "").lower()) if len(w) > 2}


def plain(c: dict[str, Any]) -> str:
    """One sentence, no glossary required. e.g. 'Well evidenced, may need a refresh — applies to you' or
    'Thin evidence — not yet decided'."""
    bits = [STRENGTH_LABEL.get(c.get("strength"), c.get("strength") or "")]
    fr = c.get("freshness_status")
    if fr in FRESHNESS_LABEL:
        bits.append(FRESHNESS_LABEL[fr])
    head = ", ".join(b for b in bits if b)
    status = c.get("status")
    if status == "accepted":
        tail = "applies to you" if c.get("application") == "established" else "accepted — not yet said if it applies to you"
    elif status == "rejected":
        tail = "rejected"
    else:
        tail = "not yet decided" if c.get("strength") in NEEDS_DECISION_STRENGTHS else "not yet decided (needs more evidence first)"
    return f"{head} — {tail}" if head else tail


def query(project_id: str, *, q: str | None = None, status: str = "all", strength: str | None = None, freshness: str | None = None,
          needs_decision: bool = False, topic: str | None = None, area: str | None = None, sort: str = "priority",
          limit: int = 100, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, PAGE_MAX))
    rows = claims_mod.list_for_project(project_id)
    if status != "superseded":
        rows = [c for c in rows if c["status"] != "superseded"]
    area_of: dict[str, str] = {}
    if area:
        try:
            from . import research_view
            area_of = research_view.areas(project_id)["area_of_claim"]
        except Exception:  # noqa: BLE001
            pass
    for c in rows:
        c["plain"] = plain(c)
        c["type_label"] = TYPE_LABEL.get(c.get("claim_type"), c.get("claim_type") or "")
        c["status_label"] = STATUS_LABEL.get(c.get("status"), c.get("status") or "")
        c["area"] = area_of.get(c["id"])
    qtoks = _tokens(q or "")

    def passes(c: dict[str, Any], skip: str | None = None) -> bool:
        if skip != "status" and status not in ("all", "superseded") and c["status"] != status:
            return False
        if skip != "strength" and strength and c["strength"] != strength:
            return False
        if skip != "freshness" and freshness and c.get("freshness_status") != freshness:
            return False
        if skip != "needs_decision" and needs_decision and not (c["status"] == "proposed" and c["strength"] in NEEDS_DECISION_STRENGTHS):
            return False
        if skip != "topic" and topic and (c.get("topic") or "") != topic:
            return False
        if skip != "area" and area and (c.get("area") or "") != area:
            return False
        if qtoks and not qtoks <= _tokens(c.get("text", "")):
            return False
        return True
    matched = [c for c in rows if passes(c)]
    facets = {
        "status": Counter(c["status"] for c in rows if passes(c, "status")),
        "strength": Counter(c["strength"] for c in rows if passes(c, "strength")),
        "freshness": Counter(c.get("freshness_status") or "uncertain" for c in rows if passes(c, "freshness")),
        "topic": Counter(c.get("topic") or "" for c in rows if passes(c, "topic") and c.get("topic")),
        "needs_decision": sum(1 for c in rows if passes(c, "needs_decision") and c["status"] == "proposed" and c["strength"] in NEEDS_DECISION_STRENGTHS),
    }
    order = {"strong": 0, "developing": 1, "weak": 2, "unsupported": 3}
    keyf = {"priority": lambda c: (0 if c["status"] == "proposed" and c["strength"] in NEEDS_DECISION_STRENGTHS else 1,
                                   order.get(c["strength"], 9), -(c.get("updated_at") or 0)),
            "newest": lambda c: -(c.get("updated_at") or 0),
            "topic": lambda c: ((c.get("topic") or "").lower(), order.get(c["strength"], 9)),
            "strength": lambda c: (order.get(c["strength"], 9), -(c.get("updated_at") or 0))}.get(sort) or (lambda c: (-(c.get("updated_at") or 0),))
    matched.sort(key=keyf)
    for c in matched:
        c["evidence_total"] = len(c.get("evidence") or [])
        c["evidence"] = (c.get("evidence") or [])[:8]
    page = matched[offset:offset + limit]
    return {"total": len(matched), "offset": offset, "limit": limit, "claims": page,
            "facets": {"status": dict(facets["status"]), "strength": dict(facets["strength"]), "freshness": dict(facets["freshness"]),
                       "topic": [{"topic": k, "n": v} for k, v in facets["topic"].most_common(30)], "needs_decision": facets["needs_decision"]}}


def for_source(project_id: str, source_id: str, locator: str | None = None, limit: int = 5) -> dict[str, Any]:
    """RESEARCH-TAB.md §5's 'Why this answer' — the Claims a chat citation's source feeds, closest locator first. $0:
    one indexed join, never a re-derivation of `claims.evidence_map`'s full-project pass."""
    rows = db.connect().execute(
        """SELECT c.*, e.locator AS ev_locator, e.relation, e.independent, e.stale AS ev_stale
           FROM claim_evidence e JOIN project_claims c ON c.id = e.claim_id
           WHERE c.project_id = ? AND e.source_id = ? AND c.status != 'superseded'
           ORDER BY e.created_at""", (project_id, source_id)).fetchall()
    by_claim: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        c = by_claim.setdefault(d["id"], claims_mod._claim(d))
        c.setdefault("_matches", []).append({"locator": d["ev_locator"], "relation": d["relation"], "independent": bool(d["independent"]), "stale": bool(d["ev_stale"])})
    out = list(by_claim.values())
    for c in out:
        c["plain"] = plain(c)
        c["type_label"] = TYPE_LABEL.get(c.get("claim_type"), c.get("claim_type") or "")
        c["matched_here"] = any((m["locator"] or "") == (locator or "") for m in c["_matches"]) if locator else False
        c.pop("_matches", None)
    order = {"strong": 0, "developing": 1, "weak": 2, "unsupported": 3}
    out.sort(key=lambda c: (0 if c["matched_here"] else 1, order.get(c["strength"], 9)))
    return {"source_id": source_id, "locator": locator, "claims": out[:limit], "total": len(out)}


def bulk_status(project_id: str, claim_ids: list[str], status: str, *, application: str | None = None) -> dict[str, Any]:
    """One verdict on many Claims, then ONE refresh — the batch accept/reject §5 asked for. Only Claims that belong to
    this project are touched; ids that don't (or don't exist) are reported, never silently dropped or raised."""
    from . import knowledge
    if status not in ("proposed", "accepted", "rejected", "superseded"):
        raise ValueError("bad status")
    mine = {r["id"] for r in db.connect().execute(
        f"SELECT id FROM project_claims WHERE project_id=? AND id IN ({','.join('?' for _ in claim_ids) or 'NULL'})",
        (project_id, *claim_ids)).fetchall()} if claim_ids else set()
    for cid in mine:
        claims_mod.set_status(cid, status, application=application)
    if mine:
        knowledge.refresh(project_id)
    return {"changed": len(mine), "skipped": len(set(claim_ids)) - len(mine), "status": status}
