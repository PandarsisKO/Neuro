"""S4 — the Findings workbench query ($0): filter, facet, sort and page the project's findings server-side.

Filters compose (AND): q (words over title + content), status (approved · suggested · reserve · dismissed), min_importance, importance (exact levels, "1,2"),
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


def rows_only(project_id: str) -> list[dict[str, Any]]:
    """Every note in the project with its citations parsed, cached on the NOTES revision alone (0.61.5).

    Measured through Kyle's browser on the 16,962-note project: `/findings` 23.2 s cold, 4.3 s warm at 0.61.3,
    and 9.3 s / 19.9 s at 0.61.4 while six ingest jobs were running. 0.61.4 cached the whole assembly on
    `db.project_view_revision`, which is the Sources fingerprint: it includes a GLOBAL jobs component, so during a
    run it moves whenever any job anywhere does, and an assembly that costs seconds was being retired before it
    could be reused. The same failure as the quality pass, one layer along — a cache whose key changes faster than
    its value can be computed is not a cache.

    So the assembly is split by what it actually depends on. The rows themselves depend on `project_notes` and
    nothing else, and that revision moves only when a finding lands or a status changes — which is exactly when
    the list must change. The derived badges live in `decorations()` below.

    Never mutated by a caller: `query` merges into copies, because this list is shared by every request that hits
    the same revision."""
    from . import cache
    rev = db.project_notes_revision(project_id)
    return cache.get_or_compute(f"findings_plain:{project_id}", rev, lambda: _rows_only(project_id),
                                label="findings_plain")


def _rows_only(project_id: str) -> list[dict[str, Any]]:
    rows = [dict(r) for r in db.connect().execute(
        "SELECT * FROM project_notes WHERE project_id=? ORDER BY importance DESC, created_at DESC",
        (project_id,)).fetchall()]
    for r in rows:
        r.pop("embedding", None)  # 0.63.67: T1 backfill populates this BLOB on real projects now; a raw
        # embedding vector is not valid UTF-8 and crashes the JSON response (PydanticSerializationError:
        # invalid utf-8 sequence...) the moment any note in a project has one. db.row_to_dict() already
        # strips it for every other reader of project_notes; this was the one path still doing a bare
        # dict(row) instead. Metadata columns (embedding_model/_provider/_dimensions/...) are plain
        # strings/ints and stay — only the BLOB itself is unserializable.
        try:
            r["citations"] = json.loads(r["citations"] or "[]")
        except ValueError:
            r["citations"] = []
        c0 = (r["citations"] or [{}])[0] if r["citations"] else {}
        r["source_title"] = c0.get("title") or "Pinned from chat"
    return rows


def decorations(project_id: str, *, block: bool = False) -> dict[str, Any]:
    """The three derived maps the workbench decorates rows with — plan/chat/Claim use, source staleness, and the
    research area a finding sits in — cached on the full view revision because that is what they genuinely depend on.

    `block=False` (the default for an ordinary page of findings) returns the previous maps at once with
    `current: False`, or nothing at all on a cold project, and never computes in the request. That is safe in a way
    the rows are not: a badge saying a finding has not been used yet may be a moment out of date, whereas a finding
    whose status the user just changed may not be. `block=True` is used when the user filters or sorts ON one of
    these dimensions — then they have asked for it and it is worth waiting for."""
    from . import cache
    rev = json.dumps(db.project_view_revision(project_id), sort_keys=True)
    key = f"findings_decor:{project_id}"
    if block:
        maps = cache.get_or_compute(key, rev, lambda: _decorations(project_id), label="findings_decor")
        return {"maps": maps, "current": True, "pending": False}
    # warm=True deliberately: with NOTHING cached there is no badge to show and an empty map would read as "this
    # finding has never been used", which is a false statement rather than a slow one. So a cold project pays for
    # the pass once; every later request takes the previous maps immediately and refreshes behind the screen. The
    # failure this avoids is not the cold cost, it is recomputing on every request because the view revision keeps
    # moving while sources are being read.
    got = cache.get_stale_ok(key, rev, lambda: _decorations(project_id), label="findings_decor", warm=True)
    return {"maps": got["value"], "current": bool(got["current"]), "pending": got["value"] is None}


def _decorations(project_id: str) -> dict[str, Any]:
    from . import staleness
    um = usage_map(project_id)
    try:
        st = {x["source_id"]: x["status"] for x in staleness.assess(project_id)["sources"]}
    except Exception:  # noqa: BLE001
        st = {}
    area_of: dict[int, str] = {}
    try:
        from . import research_view
        claim_area = research_view.areas(project_id)["area_of_claim"]
        for r in db.connect().execute("SELECT id, origin_note_id FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL", (project_id,)).fetchall():
            if r["id"] in claim_area:
                area_of[r["origin_note_id"]] = claim_area[r["id"]]
    except Exception:  # noqa: BLE001
        pass
    return {"used": um, "stale": st, "area": area_of}


def _merge(rows: list[dict[str, Any]], maps: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Copies, never the cached rows. An unknown badge is `None`, never a confident zero — `used.known` says which."""
    um = (maps or {}).get("used") or {}
    st = (maps or {}).get("stale") or {}
    ar = (maps or {}).get("area") or {}
    known = maps is not None
    out = []
    for r in rows:
        u = um.get(r["id"]) or {"plan": 0, "chat": 0, "claim": None}
        out.append({**r,
                    "used": {"plan": u["plan"], "chat": u["chat"], "claim": u["claim"],
                             "claim_counts": bool(u.get("claim_counts")),
                             "never": known and not (u["plan"] or u["chat"] or u.get("claim_counts")),
                             "known": known},
                    "source_stale": st.get(r.get("source_id") or "") in ("stale", "legacy_unverified"),
                    "area": ar.get(r["id"])})
    return out


def decorated(project_id: str) -> list[dict[str, Any]]:
    """Rows with every badge resolved, computing whatever is missing. The background warmer and any caller that
    needs the full picture uses this; a page of findings does not."""
    return _merge(rows_only(project_id), decorations(project_id, block=True)["maps"])


def _decorate(project_id: str) -> list[dict[str, Any]]:
    return _merge(_rows_only(project_id), _decorations(project_id))


def usage_map(project_id: str) -> dict[int, dict[str, Any]]:
    """note id → {plan: n, chat: n, claim: strength|None}. Plan use = a plan evidence entry citing the note's source at the
    note's locator (or, lacking a locator match, the same source); chat use = an assistant citation of the same source and
    locator; Claim = the note is a Claim's origin or evidence (claim_evidence.note_id / project_claims.origin_note_id).

    Cached on the usage inputs alone. Before 0.63.37 this used the Sources view revision, including the GLOBAL jobs
    heartbeat. Every queue update therefore retired a walk over every note, plan entry, chat citation and Claim even
    when none of those facts changed. Three screens ask for this map, so that unrelated invalidation multiplied."""
    from . import cache
    rev = db.project_usage_revision(project_id)
    return cache.get_or_compute(f"usage_map:{project_id}", rev, lambda: _usage_map(project_id), label="usage_map")


def _usage_map(project_id: str) -> dict[int, dict[str, Any]]:
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


def parse_levels(importance: str | None) -> set[int] | None:
    """S99: `importance="1,2"` -> {1, 2}; blank/None -> None (no filter). Unknown tokens are ignored rather than
    rejected, so a stale chip value can never turn the list into an error page. 0 means "unrated"."""
    if importance is None or not str(importance).strip():
        return None
    out: set[int] = set()
    for tok in str(importance).split(","):
        tok = tok.strip()
        if tok.isdigit() and 0 <= int(tok) <= 5:
            out.add(int(tok))
    return out or None


def query(project_id: str, *, q: str | None = None, status: str | None = "approved", min_importance: int | None = None, source_id: str | None = None,
          used: str | None = None, stale: str | None = None, area: str | None = None, sort: str = "importance",
          reviewed: str | None = None, importance: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """`importance` (S99, Kyle 2026-09-25: "filter by strength so I can review findings and bulk select and remove")
    is an exact SET of levels — "1,2" is the weak end, "5" the strongest — where `min_importance` was only ever a
    floor. Both compose (AND) when given; the workbench sends `importance`, older callers keep `min_importance`."""
    limit = max(1, min(limit, PAGE_MAX))
    levels = parse_levels(importance)
    needs_decorations = bool(used or stale or area) or sort == "used"
    dec = decorations(project_id, block=needs_decorations)
    rows = _merge(rows_only(project_id), dec["maps"])
    qtoks = set(_tokens(q or ""))

    def passes(r: dict[str, Any], skip: str | None = None) -> bool:
        if skip != "status" and status and status != "all" and r["status"] != status:
            return False
        if skip != "importance" and min_importance and int(r.get("importance") or 0) < min_importance:
            return False
        if skip != "importance" and levels is not None and int(r.get("importance") or 0) not in levels:
            return False
        # `reviewed_at` is NULL for every row that predates the column and for anything auto-approved, which is
        # precisely the set a second look wants. Not faceted: it is a scope, not a dimension to browse by.
        if reviewed == "no" and r.get("reviewed_at") is not None:
            return False
        if reviewed == "yes" and r.get("reviewed_at") is None:
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
            # weakest first -- what a second look wants, and the exact reverse of the default. Ties break
            # oldest-first so a long pass moves steadily through the backlog rather than re-treading new rows.
            "weakest": lambda r: (int(r.get("importance") or 0), (r.get("created_at") or 0)),
            "newest": lambda r: -(r.get("created_at") or 0),
            "source": lambda r: (r["source_title"].lower(), -int(r.get("importance") or 0)),
            "used": lambda r: (-(r["used"]["plan"] * 3 + r["used"]["chat"] + (2 if r["used"]["claim_counts"] else 0)), -int(r.get("importance") or 0))}.get(sort) or (lambda r: (-int(r.get("importance") or 0),))
    matched.sort(key=keyf)
    page = matched[offset:offset + limit]
    low = [r for r in rows if r["status"] == "approved" and int(r.get("importance") or 0) <= LOW_IMPORTANCE and r["used"]["never"]]
    return {"total": len(matched), "offset": offset, "limit": limit, "findings": page,
            "badges": {"known": dec["maps"] is not None, "current": dec["current"], "pending": dec["pending"],
                       "note": "" if dec["current"] else ("use, staleness and area are still being counted"
                                                          if dec["pending"] else "use, staleness and area are from a moment ago")},
            "facets": {"status": dict(facets["status"]), "importance": {str(k): v for k, v in sorted(facets["importance"].items(), reverse=True)},
                       "used": dict(facets["used"]), "stale": dict(facets["stale"]), "area": dict(facets["area"].most_common(30)),
                       "source": [{"source_id": k[0], "title": k[1], "n": v} for k, v in facets["source"].most_common(40)]},
            "low_value_sweep": {"count": len(low), "note_ids": [r["id"] for r in low][:2000], "pending": dec["pending"],
                                "line": "" if dec["pending"] or not low else
                                        f"{len(low)} approved findings at importance ≤ {LOW_IMPORTANCE} were never used by the plan, a chat or a Claim"}}
