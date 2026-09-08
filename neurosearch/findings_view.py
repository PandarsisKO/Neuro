"""S4 — the Findings workbench query ($0): filter, facet, sort and page the project's findings server-side.

Filters compose (AND): q (words over title + content), status (approved · suggested · reserve · dismissed), min_importance,
source_id, used (plan · chat · claim · never), stale (source stale / current), area (the Research Area the finding's Claim
belongs to), sort (importance · newest · source · used). Facets are counts over the FILTERED set minus the facet's own
dimension (so a facet always shows what choosing it would give). Use badges: 📋 plan · 💬 cited N× · 🧠 Claim (strength).
"Used" means: referenced by the plan body, cited in a chat answer, or behind a STRONG or ACCEPTED Claim — the $0 harvest
folds nearly every finding into some weak Claim, and that is not use.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from . import db

PAGE_MAX = 500
LOW_IMPORTANCE = 2      # the "low-value sweep": approved, importance ≤ LOW_IMPORTANCE, never used


def _tokens(s: str) -> list[str]:
    import re
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'-]+", (s or "").lower()) if len(w) > 2]


def usage_map(project_id: str) -> dict[int, dict[str, Any]]:
    """note id → {plan: n, chat: n, claim: strength|None}. Plan use = a plan evidence entry citing the note's source at the
    note's locator (or, lacking a locator match, the same source); chat use = an assistant citation of the same source and
    locator; Claim = the note is a Claim's origin or evidence (claim_evidence.note_id / project_claims.origin_note_id)."""
    conn = db.connect()
    notes = [dict(r) for r in conn.execute("SELECT id, source_id, citations FROM project_notes WHERE project_id=?", (project_id,)).fetchall()]
    out: dict[int, dict[str, Any]] = {n["id"]: {"plan": 0, "chat": 0, "claim": None} for n in notes}
    loc_of: dict[int, tuple[str | None, str | None]] = {}
    by_src: dict[str, list[int]] = defaultdict(list)
    for n in notes:
        try:
            c = (json.loads(n["citations"] or "[]") or [{}])[0]
        except ValueError:
            c = {}
        loc_of[n["id"]] = (n["source_id"], str(c.get("timestamp") or ""))
        if n["source_id"]:
            by_src[n["source_id"]].append(n["id"])
    plan = db.latest_plan(project_id)
    if plan:
        # only evidence the plan body actually REFERENCES counts as use (the map lists everything the planner was handed);
        # match by source id + locator when the entry has them, else by the "title @ locator" label the planner writes
        from .evidence import plan_evidence_ids
        body = plan.get("plan") or {}
        emap = body.get("_evidence") or {}
        refs = set(plan_evidence_ids({k: v for k, v in body.items() if not k.startswith("_")}))
        by_title_loc: dict[tuple[str, str], list[int]] = defaultdict(list)
        for n in notes:
            try:
                c = (json.loads(n["citations"] or "[]") or [{}])[0]
            except ValueError:
                c = {}
            if c.get("title"):
                by_title_loc[(str(c["title"]), str(c.get("timestamp") or ""))].append(n["id"])
        for eid, v in emap.items():
            if eid not in refs:
                continue
            sid, loc = v.get("source_id"), str(v.get("timestamp") or v.get("locator") or "")
            label = str(v.get("label") or "")
            hit = []
            if sid:
                hit = [nid for nid in by_src.get(sid, []) if not loc or loc_of[nid][1] == loc]
            if not hit and " @ " in label:
                t, _, l = label.rpartition(" @ ")
                hit = by_title_loc.get((t, l), [])
            for nid in hit:
                out[nid]["plan"] += 1
    for r in conn.execute("""SELECT m.citations FROM messages m JOIN conversations c ON c.id=m.conversation_id
                             WHERE c.project_id=? AND m.role='assistant' AND m.citations IS NOT NULL AND m.citations<>'[]'""", (project_id,)).fetchall():
        try:
            cites = json.loads(r["citations"]) or []
        except ValueError:
            continue
        for c in cites:
            sid, loc = (c or {}).get("source_id"), str((c or {}).get("timestamp") or "")
            for nid in by_src.get(sid or "", []):
                if loc and loc_of[nid][1] == loc:
                    out[nid]["chat"] += 1
    rank = {"strong": 3, "developing": 2, "weak": 1, "unsupported": 0}
    for r in conn.execute("SELECT origin_note_id AS nid, strength, status FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL AND status<>'rejected' "
                          "UNION ALL SELECT e.note_id, c.strength, c.status FROM claim_evidence_notes e JOIN project_claims c ON c.id=e.claim_id WHERE c.project_id=? AND c.status<>'rejected'",
                          (project_id, project_id)).fetchall():
        nid = r["nid"]
        if nid in out:
            cur = out[nid]
            lab = ("accepted " if r["status"] == "accepted" else "") + str(r["strength"] or "")
            if cur["claim"] is None or rank.get(r["strength"], 0) + (10 if r["status"] == "accepted" else 0) > cur.get("_rank", -1):
                cur["claim"], cur["_rank"] = lab, rank.get(r["strength"], 0) + (10 if r["status"] == "accepted" else 0)
                cur["claim_counts"] = r["status"] == "accepted" or r["strength"] == "strong"      # harvest touches nearly every finding; only a strong/accepted Claim is USE
    return out


def query(project_id: str, *, q: str | None = None, status: str | None = "approved", min_importance: int | None = None, source_id: str | None = None,
          used: str | None = None, stale: str | None = None, area: str | None = None, sort: str = "importance", limit: int = 100, offset: int = 0) -> dict[str, Any]:
    from . import staleness
    limit = max(1, min(limit, PAGE_MAX))
    rows = [dict(r) for r in db.connect().execute("SELECT * FROM project_notes WHERE project_id=? ORDER BY importance DESC, created_at DESC", (project_id,)).fetchall()]
    for r in rows:
        try:
            r["citations"] = json.loads(r["citations"] or "[]")
        except ValueError:
            r["citations"] = []
    um = usage_map(project_id)
    try:
        st = {x["source_id"]: x["status"] for x in staleness.assess(project_id)["sources"]}
    except Exception:  # noqa: BLE001
        st = {}
    area_of: dict[int, str] = {}
    try:
        from . import research_view
        ar = research_view.areas(project_id)
        claim_area = ar["area_of_claim"]
        for r in db.connect().execute("SELECT id, origin_note_id FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL", (project_id,)).fetchall():
            if r["id"] in claim_area:
                area_of[r["origin_note_id"]] = claim_area[r["id"]]
    except Exception:  # noqa: BLE001
        pass
    titles = {}
    for r in rows:
        u = um.get(r["id"]) or {"plan": 0, "chat": 0, "claim": None}
        r["used"] = {"plan": u["plan"], "chat": u["chat"], "claim": u["claim"], "claim_counts": bool(u.get("claim_counts")),
                     "never": not (u["plan"] or u["chat"] or u.get("claim_counts"))}
        r["source_stale"] = st.get(r.get("source_id") or "") in ("stale", "legacy_unverified")
        r["area"] = area_of.get(r["id"])
        c0 = (r["citations"] or [{}])[0] if r["citations"] else {}
        r["source_title"] = c0.get("title") or "Pinned from chat"
        titles[r.get("source_id") or ""] = r["source_title"]
    qtoks = set(_tokens(q or ""))

    def passes(r: dict[str, Any], skip: str | None = None) -> bool:
        if skip != "status" and status and status != "all" and r["status"] != status:
            return False
        if skip != "importance" and min_importance and int(r.get("importance") or 0) < min_importance:
            return False
        if skip != "source" and source_id and r.get("source_id") != source_id:
            return False
        if skip != "used" and used:
            u = r["used"]
            if used == "never" and not u["never"]:
                return False
            if used in ("plan", "chat") and not u[used]:
                return False
            if used == "claim" and not u["claim_counts"]:
                return False
        if skip != "stale" and stale in ("stale", "current") and r["source_stale"] != (stale == "stale"):
            return False
        if skip != "area" and area and (r["area"] or "") != area:
            return False
        if qtoks:
            hay = set(_tokens((r.get("title") or "") + " " + (r.get("content") or "") + " " + r["source_title"]))
            if not qtoks <= hay:
                return False
        return True
    matched = [r for r in rows if passes(r)]
    facets = {
        "status": Counter(r["status"] for r in rows if passes(r, "status")),
        "importance": Counter(int(r.get("importance") or 0) for r in rows if passes(r, "importance")),
        "used": Counter(k for r in rows if passes(r, "used") for k in (["plan"] if r["used"]["plan"] else []) + (["chat"] if r["used"]["chat"] else []) + (["claim"] if r["used"]["claim_counts"] else []) + (["never"] if r["used"]["never"] else [])),
        "stale": Counter("stale" if r["source_stale"] else "current" for r in rows if passes(r, "stale")),
        "area": Counter(r["area"] for r in rows if passes(r, "area") and r["area"]),
        "source": Counter((r.get("source_id") or "", r["source_title"]) for r in rows if passes(r, "source")),
    }
    keyf = {"importance": lambda r: (-int(r.get("importance") or 0), -(r.get("created_at") or 0)),
            "newest": lambda r: -(r.get("created_at") or 0),
            "source": lambda r: (r["source_title"].lower(), -int(r.get("importance") or 0)),
            "used": lambda r: (-(r["used"]["plan"] * 3 + r["used"]["chat"] + (2 if r["used"]["claim_counts"] else 0)), -int(r.get("importance") or 0))}.get(sort) or (lambda r: (-int(r.get("importance") or 0),))
    matched.sort(key=keyf)
    page = matched[offset:offset + limit]
    low = [r for r in rows if r["status"] == "approved" and int(r.get("importance") or 0) <= LOW_IMPORTANCE and r["used"]["never"]]
    return {"total": len(matched), "offset": offset, "limit": limit, "findings": page,
            "facets": {"status": dict(facets["status"]), "importance": {str(k): v for k, v in sorted(facets["importance"].items(), reverse=True)},
                       "used": dict(facets["used"]), "stale": dict(facets["stale"]), "area": dict(facets["area"].most_common(30)),
                       "source": [{"source_id": k[0], "title": k[1], "n": v} for k, v in facets["source"].most_common(40)]},
            "low_value_sweep": {"count": len(low), "note_ids": [r["id"] for r in low][:2000],
                                "line": f"{len(low)} approved findings at importance ≤ {LOW_IMPORTANCE} were never used by the plan, a chat or a Claim" if low else ""}}
