"""P11 EA-3 — the structured external service (EXTERNAL-AI-ACCESS-MISSION.md §39, §56–§59; plan §3).

One service below every adapter: REST (`/api/ext/v1/<op>`, api_external.py) and MCP (`mcp_external.py`) both call
`call(secret, op, args)`. Every response is the versioned envelope (§39); every read is assembled FROM the grant's
disclosure classes (§41) — sources are chosen before retrieval, derived objects are admitted only when their
provenance floor is inside the grant, and a count of what was withheld is returned instead of its content.

Nothing on these paths calls a model (§57, §58). `consult_project` is a packet of stored state and named $0
derivations, never an advisory answer: the external LLM does the reasoning (§27, §28).
"""
from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import time
from typing import Any, Callable

from . import access, claims, db, facts, ledger
from .access import AccessError, Authorization, Principal
from .external_schemas import SCHEMA_VERSION, CAPABILITIES, ContractError, check

MAX_LIST = 20
SERVER_CAPABILITIES = {"schema_version": SCHEMA_VERSION, "read": True, "write": True,
                       "intake_paths": ["processed", "raw"], "artifact_ref_kinds": ["multipart"],
                       "models_called_on_read": False}


# ------------------------------------------------------------------ envelope

def _revision(project_id: str) -> str:
    raw = db.conversation_delta_revision(project_id) + "|" + db.facts_revision(project_id)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]        # opaque: moves when intelligence moves, reveals nothing


def envelope(data: Any, *, auth: Authorization | None = None, truncated: bool = False, next_cursor: Any = None) -> dict[str, Any]:
    pid = auth.project_id if auth else None
    return {"schema_version": SCHEMA_VERSION, "project_id": pid,
            "project_revision": _revision(pid) if pid else None,
            "ledger_cursor": ledger.cursor(pid, auth.classes) if auth else None,
            "as_of": time.time(), "truncated": bool(truncated), "next_cursor": next_cursor, "data": data}


# ------------------------------------------------------------------ disclosure-aware selectors

def _visible_claims(auth: Authorization, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    if not rows:
        return [], 0
    floors = access.claim_floors([r["id"] for r in rows])
    ok = [r for r in rows if auth.may_see(floors[r["id"]])]
    return ok, len(rows) - len(ok)


def _visible_facts(auth: Authorization, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    ok = [r for r in rows if access.fact_class(r) in auth.classes]
    return ok, len(rows) - len(ok)


def _claim_out(c: dict[str, Any]) -> dict[str, Any]:
    return {"claim_id": c["id"], "text": c["text"], "status": c["status"], "strength": c.get("strength"),
            "readiness": c.get("readiness"), "freshness": c.get("freshness_status"), "topic": c.get("topic"),
            "type": c.get("claim_type")}


def _fact_out(f: dict[str, Any]) -> dict[str, Any]:
    return {"fact_id": f["id"], "kind": f["kind"], "content": f["content"], "status": f.get("status") or "active",
            "scope": f.get("scope") or "project", "explicitness": f.get("explicitness") or "explicit",
            "rationale": f.get("rationale"), "by": f.get("actor_id") or "kyle", "via_client": f.get("external_client_id"),
            "effective_at": f.get("effective_at") or f.get("created_at"), "supersedes_fact_id": f.get("supersedes_fact_id")}


def _open_questions(auth: Authorization, limit: int) -> tuple[list[dict[str, Any]], int]:
    rows = [dict(r) for r in db.connect().execute(
        "SELECT id, question, claim_id, status, gap, updated_at FROM project_evidence_targets WHERE project_id=? AND status='open' "
        "ORDER BY updated_at DESC LIMIT 200", (auth.project_id,)).fetchall()]
    cids = [r["claim_id"] for r in rows if r["claim_id"]]
    floors = access.claim_floors(cids) if cids else {}
    ok, hidden = [], 0
    for r in rows:
        f = floors.get(r["claim_id"]) if r["claim_id"] else frozenset({access.UNCLASSIFIED})
        if auth.may_see(f):
            ok.append({"question_id": r["id"], "question": r["question"], "gap": r["gap"], "claim_id": r["claim_id"]})
        else:
            hidden += 1
    return ok[:limit], hidden


def _watchouts(auth: Authorization, limit: int) -> tuple[list[dict[str, Any]], int]:
    rows = [dict(r) for r in db.connect().execute(
        "SELECT id, kind, claim_id, related_claim_id, description, impact, updated_at FROM research_tensions WHERE project_id=? AND status='open' "
        "ORDER BY (impact='high') DESC, updated_at DESC LIMIT 200", (auth.project_id,)).fetchall()]
    floors = access.tension_floors(rows)
    ok = [{"watchout_id": r["id"], "kind": r["kind"], "impact": r["impact"], "description": r["description"],
           "claim_id": r["claim_id"]} for r in rows if auth.may_see(floors[r["id"]])]
    return ok[:limit], len(rows) - len(ok)


def _plan(auth: Authorization) -> tuple[dict[str, Any] | None, int]:
    p = db.latest_plan(auth.project_id)
    if not p:
        return None, 0
    plan = p.get("plan") or {}
    floor = db._plan_floor(db.connect(), plan)
    if not auth.may_see(floor):
        return None, 1
    appr = plan.get("approach") or {}
    return {"basis": "stored_plan_recommendation", "plan_id": p["id"], "version": p["version"], "status": p.get("status"),
            "goal": (plan.get("goal") or {}).get("outcome"), "recommended": appr.get("recommended"), "why": appr.get("why"),
            "open_decisions": [{"decision": d.get("decision"), "recommended": d.get("recommended"), "when": d.get("when")}
                               for d in (plan.get("decisions") or [])[:8] if isinstance(d, dict)],
            "first_steps": [s.get("action") for s in (plan.get("first_steps") or [])[:5] if isinstance(s, dict)]}, 0


def _relevant(question: str, texts: list[tuple[Any, str]], k: int) -> list[Any]:
    scored = [(claims.overlap(question, t), key) for key, t in texts if t]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    return [key for _, key in scored[:k]]


# ------------------------------------------------------------------ read operations

def list_projects(principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    rows = access.granted_projects(principal)
    out = [{"project_id": r["id"], "name": r["name"], "role": r["role"], "disclosure_classes": r["disclosure_classes"],
            "last_change_cursor": ledger.cursor(r["id"], r["disclosure_classes"])} for r in rows]
    if args.get("query"):                               # late binding: best match first, permitted projects only
        from . import convsync
        rank = {c["project_id"]: (i, c["match"]) for i, c in enumerate(convsync.candidates(principal, str(args["query"])))}
        out.sort(key=lambda r: rank[r["project_id"]][0])
        for r in out:
            r["match"] = rank[r["project_id"]][1]
    return envelope(out)


def sync_conversation_to_project(principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    from . import convsync
    return convsync.sync(principal, args, apply_state, envelope)


def open_project(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    caps = args.get("client_capabilities")
    if caps is not None:
        check("external.capabilities.v1", caps)
        access.set_client_capabilities(auth.principal.client_id, caps)
    p = db.get_project(auth.project_id) or {}
    position, hid_f = _visible_facts(auth, facts.current_position(auth.project_id))
    questions, hid_q = _open_questions(auth, 5)
    watchouts, hid_w = _watchouts(auth, 5)
    plan, hid_p = _plan(auth)
    allowed = access.allowed_source_ids(auth.project_id, auth.classes)
    all_ready = db.project_source_ids(auth.project_id)
    claim_rows = [dict(r) for r in db.connect().execute(
        "SELECT id, status FROM project_claims WHERE project_id=? AND status IN ('accepted','proposed')", (auth.project_id,)).fetchall()]
    vis_claims, hid_c = _visible_claims(auth, claim_rows)
    by_status: dict[str, int] = {}
    for c in vis_claims:
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
    negotiated = _negotiate(caps or {})
    data = {
        "project": {"name": p.get("name"), "brief": p.get("brief"), "goal": p.get("goal"), "role": auth.role},
        "orientation": {"current_position": [_fact_out(f) for f in position][:MAX_LIST],
                        "open_questions": questions, "watchouts": watchouts, "plan": plan,
                        "counts": {"sources": len(allowed), "claims": by_status}},
        "capabilities": {"server": SERVER_CAPABILITIES, "client": caps or {}, "negotiated": negotiated},
        "disclosure": {"classes": sorted(auth.classes),
                       "withheld": {"sources": len(all_ready) - len(allowed), "claims": hid_c, "facts": hid_f,
                                    "questions": hid_q, "watchouts": hid_w, "plan": hid_p}},
        "guidance": {"read_when": "the turn needs durable project knowledge not already in this conversation",
                     "skip_read_for": ["drafting", "rewriting", "tone", "formatting", "translation"],
                     "write_when": "the user states a durable decision, constraint, requirement, rejected option, commitment or fact, "
                                   "or shares material the project should keep"},
    }
    return envelope(data, auth=auth)


def _negotiate(caps: dict[str, Any]) -> dict[str, Any]:
    """§63: which intake path this client should use per material type — from what it says it can do, never who it is."""
    t = set(caps.get("file_transport") or [])
    return {"pdf": "processed" if caps.get("pdf_text") else ("raw" if t - {"none"} else "unsupported"),
            "image": "processed" if (caps.get("vision") or caps.get("ocr")) else ("raw" if t - {"none"} else "unsupported"),
            "audio_video": "processed" if caps.get("transcription") else ("raw" if t - {"none"} else "unsupported"),
            "spreadsheet": "processed" if caps.get("table_extraction") else ("raw" if t - {"none"} else "unsupported"),
            "url": "processed" if caps.get("web_access") else "raw",
            "text": "processed", "correspondence": "processed",
            "writes": bool(caps.get("write_tools", True))}


def get_project_changes(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    page = ledger.events(auth.project_id, since=int(args.get("since_cursor") or 0), classes=auth.classes,
                         limit=int(args.get("limit") or 50), min_materiality=args.get("min_materiality"))
    out = [{"id": e["id"], "type": e["event_type"], "object_type": e["object_type"], "object_id": e["object_id"],
            "by": e["actor_id"], "via_client": e["external_client_id"], "caused_by": e["originating_actor_id"],
            "when": e["created_at"], "before": e["before"], "after": e["after"], "materiality": e["materiality"],
            "decision_impact": e["decision_impact"]} for e in page["events"]]
    return envelope({"summary": page["summary"], "events": out}, auth=auth, truncated=page["more"], next_cursor=page["next_cursor"])


def search_project(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from .search import search_fts
    q = str(args.get("query") or "").strip()
    if not q:
        raise AccessError("invalid", "query is required")
    limit = max(1, min(int(args.get("limit") or 10), MAX_LIST))
    kinds = set(args.get("kinds") or ["chunk", "claim", "fact"])
    out: list[dict[str, Any]] = []
    if "chunk" in kinds:
        allowed = access.allowed_source_ids(auth.project_id, auth.classes)
        for h in (search_fts(q, limit=limit, source_ids=allowed) if allowed else []):   # restricted text never enters the candidate set
            out.append({"hit_type": "chunk", "source_id": h["source_id"], "title": h.get("title"), "locator": h.get("timestamp"),
                        "link": h.get("link"), "excerpt": (h.get("text") or "")[:600], "score": h.get("score")})
    if "claim" in kinds:
        rows = [dict(r) for r in db.connect().execute(
            "SELECT * FROM project_claims WHERE project_id=? AND status IN ('accepted','proposed')", (auth.project_id,)).fetchall()]
        keys = _relevant(q, [(r["id"], r["text"]) for r in rows], limit * 3)
        cand = [r for r in rows if r["id"] in set(keys)]
        vis, _ = _visible_claims(auth, cand)
        order = {k: i for i, k in enumerate(keys)}
        out += [{"hit_type": "claim", **_claim_out(c)} for c in sorted(vis, key=lambda c: order[c["id"]])[:limit]]
    if "fact" in kinds:
        vis, _ = _visible_facts(auth, facts.current_position(auth.project_id))
        keys = _relevant(q, [(f["id"], f["content"]) for f in vis], limit)
        byid = {f["id"]: f for f in vis}
        out += [{"hit_type": "fact", **_fact_out(byid[k])} for k in keys]
    return envelope({"query": q, "hits": out}, auth=auth)


def get_evidence(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    """Progressive disclosure (plan §3): summary → excerpt → exact locator. Never more than the grant allows."""
    ref = args.get("ref") or {}
    depth = args.get("depth") or "summary"
    if depth not in ("summary", "excerpt", "exact"):
        raise AccessError("invalid", "depth must be summary, excerpt or exact")
    if ref.get("claim_id"):
        c = claims.get(ref["claim_id"])
        if not c or c["project_id"] != auth.project_id:
            raise AccessError("not_found", "no such claim in this project")
        if not auth.may_see(access.claim_floors([c["id"]])[c["id"]]):
            raise AccessError("not_found", "no such claim in this project")      # a withheld object does not exist here
        ev = claims.evidence_for(c["id"])
        srcs = {r["id"]: dict(r) for r in db.connect().execute(
            f"SELECT id, title, url, platform FROM sources WHERE id IN ({','.join('?' * len(ev)) or 'NULL'})", [e['source_id'] for e in ev]).fetchall()} if ev else {}
        items = []
        for e in ev:
            s = srcs.get(e["source_id"], {})
            item = {"source_id": e["source_id"], "title": s.get("title"), "relation": e.get("relation"),
                    "evidence_class": e.get("evidence_class"), "independent": bool(e.get("independent"))}
            if depth in ("excerpt", "exact"):
                item["excerpt"] = e.get("excerpt")
            if depth == "exact":
                item.update({"locator": e.get("locator"), "link": e.get("link") or s.get("url"), "source_revision": e.get("source_revision")})
            items.append(item)
        return envelope({"claim": _claim_out(c), "strength_why": c.get("strength_why"), "evidence": items}, auth=auth)
    if ref.get("source_id"):
        sid = ref["source_id"]
        if sid not in set(access.allowed_source_ids(auth.project_id, auth.classes, ready_only=False)):
            raise AccessError("not_found", "no such source in this project")
        s = dict(db.connect().execute("SELECT id, title, url, platform, channel, published_at, transcript_kind FROM sources WHERE id=?", (sid,)).fetchone())
        data: dict[str, Any] = {"source": s}
        if depth in ("excerpt", "exact"):
            at = ref.get("start")
            q = "SELECT start, end, text FROM segments WHERE source_id=?"
            params: list[Any] = [sid]
            if at is not None:
                q += " AND end>? ORDER BY start LIMIT 6"; params.append(float(at))
            else:
                q += " ORDER BY start LIMIT 6"
            segs = [dict(r) for r in db.connect().execute(q, params).fetchall()]
            from .chunking import fmt_locator
            data["passage"] = [{"locator": fmt_locator(s["platform"] or "", g["start"]), "text": g["text"]} for g in segs]
        return envelope(data, auth=auth)
    if ref.get("fact_id") is not None:
        f = facts.get(int(ref["fact_id"]))
        if not f or f["project_id"] != auth.project_id or access.fact_class(f) not in auth.classes:
            raise AccessError("not_found", "no such fact in this project")
        return envelope({"fact": _fact_out(f), "history": [_fact_out(x) for x in facts.history(f["id"])
                                                            if access.fact_class(x) in auth.classes]}, auth=auth)
    raise AccessError("invalid", "ref needs claim_id, source_id or fact_id")


def consult_project(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    """§58: the compact intelligence packet for ONE substantive question. Stored state + $0 derivations only."""
    from .search import search_fts
    q = str(args.get("question") or "").strip()
    if not q:
        raise AccessError("invalid", "question is required")
    position, _ = _visible_facts(auth, facts.current_position(auth.project_id))
    pos_keys = set(_relevant(q, [(f["id"], f["content"]) for f in position], 8))
    constraints = [f for f in position if f["kind"] in ("constraint", "requirement", "rejected")]
    rows = [dict(r) for r in db.connect().execute(
        "SELECT * FROM project_claims WHERE project_id=? AND status IN ('accepted','proposed')", (auth.project_id,)).fetchall()]
    focus = set((args.get("focus") or {}).get("claim_ids") or [])
    keys = list(focus) + _relevant(q, [(r["id"], r["text"]) for r in rows], 12)
    cand = [r for r in rows if r["id"] in set(keys)]
    vis_claims, hid_claims = _visible_claims(auth, cand)
    order = {k: i for i, k in enumerate(keys)}
    vis_claims.sort(key=lambda c: order.get(c["id"], 99))
    watch, _ = _watchouts(auth, 50)
    watch_rel = [w for w in watch if w["claim_id"] in {c["id"] for c in vis_claims}] or \
                [w for w in watch if w["impact"] == "high"][:3]
    questions, _ = _open_questions(auth, 50)
    qkeys = _relevant(q, [(x["question_id"], x["question"]) for x in questions], 5)
    qby = {x["question_id"]: x for x in questions}
    plan, _ = _plan(auth)
    since = args.get("since_cursor")
    changed = None
    if since is not None:
        pg = ledger.events(auth.project_id, since=int(since), classes=auth.classes, limit=20, min_materiality="supporting")
        changed = {"summary": pg["summary"], "events": [{"type": e["event_type"], "object_id": e["object_id"], "after": e["after"]}
                                                        for e in pg["events"][:10]]}
    allowed = access.allowed_source_ids(auth.project_id, auth.classes)
    hits = search_fts(q, limit=6, source_ids=allowed) if allowed else []
    data = {
        "question": q,
        "position": [_fact_out(f) for f in position if f["id"] in pos_keys or f["kind"] == "decision"][:12],
        "constraints": [_fact_out(f) for f in constraints][:8],
        "research_state": {"claims": [_claim_out(c) for c in vis_claims[:10]], "watchouts": watch_rel[:5]},
        "changed_since": changed,
        "plan_implications": plan,
        "unresolved": [qby[k] for k in qkeys],
        "evidence_available": [{"source_id": h["source_id"], "title": h.get("title"), "locator": h.get("timestamp"),
                                "excerpt": (h.get("text") or "")[:300]} for h in hits],
        "withheld": {"claims": hid_claims},
        "how_to_use": "Reason over this yourself. Cite evidence only if the user asks why; call get_evidence for exact passages.",
    }
    return envelope(data, auth=auth)


# ------------------------------------------------------------------ writes (EA-4..EA-6)

def _visible_fact(auth: Authorization, fact_id: Any) -> dict[str, Any]:
    f = facts.get(int(fact_id)) if fact_id is not None else None
    if not f or f["project_id"] != auth.project_id or access.fact_class(f) not in auth.classes:
        raise AccessError("not_found", "no such fact in this project")       # you cannot change what you cannot see
    return f


def _kind_changed_since(project_id: str, kind: str, base: int) -> bool:
    r = db.connect().execute(
        "SELECT 1 FROM project_change_events e JOIN project_facts f ON f.id = CAST(e.object_id AS INTEGER) "
        "WHERE e.project_id=? AND e.object_type='fact' AND f.kind=? AND e.id>? LIMIT 1", (project_id, kind, int(base))).fetchone()
    return r is not None


def apply_state(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    """§50/§51 (plan §7) with the integrity rules from Kyle's EA-9 review (2026-09-22). Every item arrives as a MODEL's
    structured reading of the conversation, so a client label is not proof:

      1. Committing needs the user's own words (`user_text`). 'explicit' or 'accepted_recommendation' without them is
         saved as a suggestion (proposed), never as project truth. reaffirm / supersede / withdraw — explicit acts by
         definition — are refused without them. The words are stored with the fact and on its ledger event.
      3. A retry (same request id) is a no-op and repeated information is not an event: a `record` whose content the
         project already holds is skipped, whatever the wording. A reaffirmation happens ONLY through an explicit
         `reaffirm` with the user's words — it is never inferred from a restatement.
      5. Nothing replaces project truth blind — decided by a READ, not by text similarity (Kyle's second review). A
         committed decision/constraint/requirement/rejected option/commitment/deadline is written only if the client
         has seen the project's current state of that kind: when active facts of that kind are visible to this grant
         and the client sent no base revision (a conversation that never read Neuro), or one of them changed after its
         base, nothing is written and `needs_current_state` returns the current facts plus the cursor to resend with.
         If facts of that kind exist that this grant cannot see, the item is kept as a suggestion for the owner to
         reconcile rather than becoming a second, unseen "current" truth. supersede / withdraw need a base revision.
         Word overlap only annotates `likely_same` candidates; it never decides.
    Each change stands alone: one conflict or refusal does not stop the others."""
    body = check("external.sync.v1", {k: v for k, v in args.items() if k in ("project_id", "base_revision", "intake_id", "changes")})
    base = body.get("base_revision")
    applied: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    needs_state: list[dict[str, Any]] = []

    def done(op: str, f: dict[str, Any], note: str | None = None) -> None:
        applied.append({"op": op, "fact_id": f["id"], "status": f["status"], "replay": bool(f.get("idempotent_replay")),
                        "fact": _fact_out(f), **({"note": note} if note else {})})

    for ch in body["changes"]:
        op, req = ch["op"], ch["client_request_id"]
        words = (ch.get("user_text") or "").strip() or None
        try:
            prior = facts._by_request(auth.principal.client_id, req)
            if prior is not None and op in ("record", "propose", "supersede"):
                done(op, {**prior, "idempotent_replay": True})
                continue
            if op in ("record", "propose"):
                if not ch.get("kind") or not ch.get("content"):
                    raise AccessError("invalid", f"{op} needs kind and content")
                expl = "inferred" if op == "propose" else ch.get("explicitness", "explicit")
                if expl == "accepted_recommendation" and not (ch.get("referent") or "").strip():
                    raise AccessError("invalid", "an accepted recommendation must name the ONE proposal the user accepted (referent)")
                note = None
                if expl != "inferred" and not words:
                    expl, note = "inferred", "saved as a suggestion: no user wording supports it"
                same = facts.identical_active(auth.project_id, ch["kind"], ch["content"])
                if same is not None and access.fact_class(same) in auth.classes:
                    skipped.append({"op": op, "reason": "already_recorded", "fact_id": same["id"], "content": ch["content"]})
                    continue
                if expl != "inferred" and ch["kind"] in facts.CANONICAL and ch.get("scope", "project") == "project":
                    current = facts.active_of_kind(auth.project_id, ch["kind"])
                    seen = [f for f in current if access.fact_class(f) in auth.classes]
                    if seen and (base is None or _kind_changed_since(auth.project_id, ch["kind"], base)):
                        needs_state.append({
                            "op": op, "client_request_id": req, "kind": ch["kind"],
                            "proposed": {"content": ch["content"], "user_text": words},
                            "current": [_fact_out(f) for f in seen][:20],
                            "likely_same": [f["id"] for f in seen if facts.same_topic(f["content"], ch["content"])],
                            "base_revision": ledger.cursor(auth.project_id, auth.classes),
                            "reason": f"the project already has a current {ch['kind']}; decide with the user whether this replaces "
                                      f"one of them (supersede with its fact_id) or stands beside them (record again), and resend "
                                      f"with this base_revision"})
                        continue
                    if len(seen) < len(current):
                        expl, note = "inferred", (f"saved for the owner to reconcile: this project has {ch['kind']}s you can't see")
                f = facts.record(auth.project_id, ch["kind"], ch["content"], explicitness=expl, scope=ch.get("scope", "project"),
                                 rationale=ch.get("rationale"), referent=ch.get("referent"), user_text=words,
                                 disclosure_class=ch.get("disclosure_class") or "standard", client_request_id=req)
                done(op, f, note)
                continue
            old = _visible_fact(auth, ch.get("fact_id"))              # a fact this grant cannot see does not exist here
            if not words:
                refused.append({"op": op, "fact_id": ch.get("fact_id"), "reason": f"{op} changes the project's position and needs "
                                "the user's own words (user_text)"})
                continue
            if op == "reaffirm":
                done(op, facts.reaffirm(int(ch["fact_id"]), rationale=ch.get("rationale"), base_cursor=base, client_request_id=req, user_text=words))
                continue
            if base is None:
                raise facts.Conflict(old["id"], old, {"op": op, "fact_id": old["id"], "content": ch.get("content")},
                                     "read the current state first (open_project or consult_project) and pass its ledger_cursor as base_revision")
            if op == "supersede":
                if not ch.get("content"):
                    raise AccessError("invalid", "supersede needs content")
                done(op, facts.supersede(int(ch["fact_id"]), ch["content"], rationale=ch.get("rationale"), base_cursor=base,
                                         explicitness=ch.get("explicitness", "explicit"), user_text=words,
                                         disclosure_class=access.merge_declared(old.get("disclosure_class"), ch.get("disclosure_class")),
                                         client_request_id=req))
            else:                                                              # withdraw
                done(op, facts.withdraw(int(ch["fact_id"]), rationale=ch.get("rationale"), base_cursor=base))
        except facts.Conflict as e:
            conflicts.append({"op": op, "client_request_id": req, **e.as_dict(),
                              "current": _fact_out(e.current) if e.current else None})
    return {"applied": applied, "conflicts": conflicts, "refused": refused, "skipped": skipped, "needs_state": needs_state}


def sync_project_state(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    return envelope(apply_state(auth, args), auth=auth)


def create_intake(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from . import intake
    return envelope(intake.create(auth, args), auth=auth)


def add_processed_material(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from . import intake
    return envelope(intake.add_processed(auth, args), auth=auth)


def attach_artifact(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from . import intake
    return envelope(intake.attach(auth, args, upload=args.pop("_upload", None)), auth=auth)


def finalize_intake(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from . import intake
    return envelope(intake.finalize(auth, args, apply_state=apply_state), auth=auth)


def get_intake_status(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    from . import intake
    return envelope(intake.get_status(auth, args), auth=auth)


# ------------------------------------------------------------------ dispatcher

READS: dict[str, Callable[[Authorization, dict[str, Any]], dict[str, Any]]] = {
    "open_project": open_project, "get_project_changes": get_project_changes, "search_project": search_project,
    "get_evidence": get_evidence, "consult_project": consult_project, "get_intake_status": get_intake_status,
}
WRITES: dict[str, Callable[[Authorization, dict[str, Any]], dict[str, Any]]] = {
    "create_intake": create_intake, "add_processed_material": add_processed_material, "attach_artifact": attach_artifact,
    "finalize_intake": finalize_intake, "sync_project_state": sync_project_state,
}
PROJECTLESS: dict[str, Callable[[Principal, dict[str, Any]], dict[str, Any]]] = {
    "list_projects": list_projects,
    "sync_conversation_to_project": sync_conversation_to_project,   # resolves (or asks for) its project itself; authorizes inside
}


class ExternalError(Exception):
    def __init__(self, code: str, status: int, message: str, detail: Any = None):
        super().__init__(message)
        self.code, self.status, self.message, self.detail = code, status, message, detail

    def body(self) -> dict[str, Any]:
        out = {"schema_version": SCHEMA_VERSION, "error": {"code": self.code, "message": self.message}}
        if self.detail is not None:
            out["error"]["detail"] = self.detail
        return out


def call(secret: str | None, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Authenticate → authorize → bind the actor → run → audit. Raises ExternalError with a Health code (§64)."""
    args = dict(args or {})
    t0 = time.perf_counter()
    principal: Principal | None = None
    project_id = args.get("project_id")
    try:
        principal = access.authenticate(secret)
        rid = str(args.get("client_request_id") or f"ext:{_secrets.token_hex(6)}")
        with ledger.acting(principal.actor_id, client_id=principal.client_id, request_id=rid, surface="external"):
            if op in PROJECTLESS:
                out = PROJECTLESS[op](principal, args)
            elif op in READS or op in WRITES:
                auth = access.authorize(principal, project_id, op)
                out = (READS.get(op) or WRITES[op])(auth, args)
            else:
                raise AccessError("invalid", f"unknown operation {op!r}")
        access.record_request(principal, op, project_id, "ok", duration_ms=int((time.perf_counter() - t0) * 1000))
        return out
    except AccessError as e:
        _audit(principal, op, project_id, e.code, e.message, t0, secret)
        raise ExternalError(e.code, e.status, e.message)
    except ContractError as e:
        _audit(principal, op, project_id, "invalid", str(e), t0, secret)
        raise ExternalError("invalid", 422, "request does not match its contract", detail=e.errors[:20])
    except facts.Conflict as e:
        _audit(principal, op, project_id, "conflict", e.reason, t0, secret)
        raise ExternalError("conflict", 409, e.reason, detail=e.as_dict())
    except (LookupError, ValueError) as e:
        _audit(principal, op, project_id, "invalid", str(e), t0, secret)
        raise ExternalError("invalid", 422, str(e)[:300])
    except ExternalError:
        raise
    except Exception as e:  # noqa: BLE001
        rid = _secrets.token_hex(6)
        _audit(principal, op, project_id, "error", f"{type(e).__name__} [{rid}]", t0, secret)
        import logging
        logging.getLogger(__name__).exception("external %s failed [%s]", op, rid)
        raise ExternalError("error", 500, f"Neuro could not complete this request (ref {rid})")


def link_account(secret: str | None, code: str, client_name: str | None = None) -> dict[str, Any]:
    """Resource-server mode (idp.py): bind the identity-provider sign-in behind `secret` to the Neuro person an
    owner-issued invite names. The only operation an unlinked sign-in may perform."""
    from . import idp
    t0 = time.perf_counter()
    try:
        if not idp.enabled() or not idp.looks_like_jwt(secret):
            raise AccessError("invalid", "linking is only used with a sign-in from this server's identity provider")
        out = idp.link(secret, code, client_name)
        access.record_request(None, "link_account", None, "ok", out.get("person"), int((time.perf_counter() - t0) * 1000))
        return envelope(out)
    except AccessError as e:
        _audit(None, "link_account", None, e.code, e.message, t0, None)
        raise ExternalError(e.code, e.status, e.message)


def _audit(principal: Principal | None, op: str, project_id: str | None, code: str, msg: str, t0: float, secret: str | None) -> None:
    try:
        access.record_request(principal, op, project_id if principal else None, code, msg[:200],
                              int((time.perf_counter() - t0) * 1000),
                              credential_prefix=(secret or "")[:access.PREFIX_LEN] if secret and not principal else None)
    except Exception:  # noqa: BLE001 — the audit must never replace the real answer
        pass


_ = (json, CAPABILITIES)
