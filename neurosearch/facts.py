"""P11 EA-2 — durable user state that evolves (EXTERNAL-AI-ACCESS-MISSION.md §47, §49–§51; plan §7).

`project_facts` stays the one table of user-authored project state; this module is the one door for changing it in a
way that keeps history: who said it, through which client, how explicitly, whether it is still the project's
position, and what it replaced. Nothing here calls a model.

    explicit, project scope     → active   (Read + Contribute may commit it directly, §50)
    accepted_recommendation     → active   only with ONE referent: the proposal the user accepted, verbatim
    inferred                    → proposed (reviewable; never the project's position until accepted)
    personal scope              → stored as that person's preference, never returned as the project position

    10% → reaffirm 10% → 7.5%:  fact A active · event decision_reaffirmed (A unchanged) · fact B active, A superseded.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import db, ledger

KINDS = ("decision", "constraint", "requirement", "rejected", "context", "preference", "commitment",
         "deadline", "counterpart_position", "concern", "open_question")          # the last four: P11 conversation sync (a counterpart's stated position is the USER's report of it)
EXPLICITNESS = ("explicit", "accepted_recommendation", "inferred")
_RECORDED = {"decision": "decision_recorded", "constraint": "constraint_recorded", "requirement": "requirement_recorded",
             "rejected": "rejected_option_recorded", "commitment": "commitment_recorded", "preference": "preference_recorded",
             "context": "fact_recorded", "deadline": "deadline_recorded", "counterpart_position": "counterpart_position_recorded",
             "concern": "concern_recorded", "open_question": "open_question_recorded"}


class Conflict(Exception):
    """§51: the state the client reasoned against has moved. Carries current and proposed so the client can ask."""

    def __init__(self, fact_id: int, current: dict[str, Any] | None, proposed: dict[str, Any], reason: str):
        super().__init__(reason)
        self.fact_id, self.current, self.proposed, self.reason = fact_id, current, proposed, reason

    def as_dict(self) -> dict[str, Any]:
        return {"fact_id": self.fact_id, "reason": self.reason, "current": self.current, "proposed": self.proposed}


def get(fact_id: int) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM project_facts WHERE id=?", (int(fact_id),)).fetchone()
    return dict(r) if r else None


def _by_request(client_id: str | None, request_id: str | None) -> dict[str, Any] | None:
    if not request_id:
        return None
    r = db.connect().execute("SELECT * FROM project_facts WHERE external_client_id IS ? AND client_request_id=?",
                             (client_id, request_id)).fetchone()
    return dict(r) if r else None


def _check_base(conn: Any, fact: dict[str, Any], base_cursor: int | None, proposed: dict[str, Any]) -> None:
    if fact["status"] != "active":
        raise Conflict(fact["id"], fact, proposed, f"this {fact['kind']} is no longer current ({fact['status']})")
    if base_cursor is None:
        return
    later = conn.execute("SELECT id FROM project_change_events WHERE project_id=? AND object_type='fact' AND object_id=? AND id>? "
                         "ORDER BY id DESC LIMIT 1", (fact["project_id"], str(fact["id"]), int(base_cursor))).fetchone()
    if later:
        raise Conflict(fact["id"], fact, proposed, "someone changed this after the state you were shown")


def _event_for(kind: str, status: str, scope: str) -> str:
    if status == "proposed":
        return "fact_proposed"
    if scope == "personal":
        return "preference_recorded"
    return _RECORDED.get(kind, "fact_recorded")


def record(project_id: str, kind: str, content: str, *, explicitness: str = "explicit", scope: str = "project",
           rationale: str | None = None, referent: str | None = None, disclosure_class: str | None = None,
           client_request_id: str | None = None, effective_at: float | None = None, origin: str = "user") -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if explicitness not in EXPLICITNESS:
        raise ValueError("bad explicitness")
    if scope not in ("project", "personal"):
        raise ValueError("bad scope")
    if explicitness == "accepted_recommendation" and not (referent and referent.strip()):
        raise ValueError("an accepted recommendation must name the ONE proposal the user accepted (referent)")
    content = content.strip()
    if not content:
        raise ValueError("empty content")
    who = ledger.current()
    existing = _by_request(who.get("client_id"), client_request_id)
    if existing:
        return {**existing, "idempotent_replay": True}
    status = "proposed" if explicitness == "inferred" else "active"
    t = time.time()
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO project_facts (project_id, kind, content, origin, created_at, actor_id, external_client_id, explicitness, status, "
            "scope, rationale, effective_at, client_request_id, disclosure_class, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, kind, content, origin, t, who.get("actor_id"), who.get("client_id"), explicitness, status, scope,
             rationale, effective_at or t, client_request_id, disclosure_class, t))
        fid = cur.lastrowid
        after = {"kind": kind, "content": content[:1000], "status": status, "scope": scope, "explicitness": explicitness}
        if referent:
            after["referent"] = referent[:500]
        if rationale:
            after["rationale"] = rationale[:500]
        ledger.record(conn, project_id, event_type=_event_for(kind, status, scope), object_type="fact", object_id=fid,
                      before=None, after=after, floor={disclosure_class or "restricted"})
    return get(fid)  # type: ignore[return-value]


def reaffirm(fact_id: int, *, rationale: str | None = None, base_cursor: int | None = None,
             client_request_id: str | None = None) -> dict[str, Any]:
    """§47: an explicit re-statement is chronology even though the position is unchanged. The fact row is untouched."""
    f = get(fact_id)
    if not f:
        raise LookupError("no such fact")
    with db.tx() as conn:
        if client_request_id and conn.execute("SELECT 1 FROM project_change_events WHERE object_type='fact' AND object_id=? "
                                              "AND request_id=? AND event_type='decision_reaffirmed'", (str(fact_id), client_request_id)).fetchone():
            return {**f, "idempotent_replay": True}
        _check_base(conn, f, base_cursor, {"op": "reaffirm", "fact_id": fact_id})
        with ledger.acting(**{**_ctx(), "request_id": client_request_id or ledger.current().get("request_id")}):
            ledger.record(conn, f["project_id"], event_type="decision_reaffirmed", object_type="fact", object_id=fact_id,
                          before={"content": f["content"][:1000]}, after={"content": f["content"][:1000], "rationale": (rationale or "")[:500]},
                          floor={f.get("disclosure_class") or "restricted"}, force=True)
    return get(fact_id)  # type: ignore[return-value]


def supersede(fact_id: int, content: str, *, rationale: str | None = None, base_cursor: int | None = None,
              explicitness: str = "explicit", disclosure_class: str | None = None,
              client_request_id: str | None = None) -> dict[str, Any]:
    """A changed position replaces the old one; history keeps both, and only one is current."""
    old = get(fact_id)
    if not old:
        raise LookupError("no such fact")
    who = ledger.current()
    existing = _by_request(who.get("client_id"), client_request_id)
    if existing:
        return {**existing, "idempotent_replay": True}
    content = content.strip()
    if not content:
        raise ValueError("empty content")
    cls = disclosure_class or old.get("disclosure_class")
    t = time.time()
    with db.tx() as conn:
        _check_base(conn, old, base_cursor, {"op": "supersede", "fact_id": fact_id, "content": content})
        cur = conn.execute(
            "INSERT INTO project_facts (project_id, kind, content, origin, created_at, actor_id, external_client_id, explicitness, status, "
            "scope, rationale, effective_at, supersedes_fact_id, client_request_id, disclosure_class, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?)",
            (old["project_id"], old["kind"], content, "user", t, who.get("actor_id"), who.get("client_id"), explicitness,
             old.get("scope") or "project", rationale, t, fact_id, client_request_id, cls, t))
        new_id = cur.lastrowid
        conn.execute("UPDATE project_facts SET status='superseded', updated_at=? WHERE id=?", (t, fact_id))
        floor = {old.get("disclosure_class") or "restricted", cls or "restricted"}
        ledger.record(conn, old["project_id"], event_type="decision_changed" if old["kind"] == "decision" else "fact_changed",
                      object_type="fact", object_id=fact_id,
                      before={"content": old["content"][:1000], "status": "active"},
                      after={"content": content[:1000], "status": "superseded", "superseded_by": new_id, "rationale": (rationale or "")[:500]},
                      floor=floor)
    return get(new_id)  # type: ignore[return-value]


def withdraw(fact_id: int, *, rationale: str | None = None, base_cursor: int | None = None) -> dict[str, Any]:
    f = get(fact_id)
    if not f:
        raise LookupError("no such fact")
    with db.tx() as conn:
        _check_base(conn, f, base_cursor, {"op": "withdraw", "fact_id": fact_id})
        conn.execute("UPDATE project_facts SET status='withdrawn', updated_at=? WHERE id=?", (time.time(), fact_id))
        ledger.record(conn, f["project_id"], event_type="decision_withdrawn" if f["kind"] == "decision" else "fact_withdrawn",
                      object_type="fact", object_id=fact_id, before={"status": "active", "content": f["content"][:1000]},
                      after={"status": "withdrawn", "rationale": (rationale or "")[:500]}, floor={f.get("disclosure_class") or "restricted"})
    return get(fact_id)  # type: ignore[return-value]


def set_proposal(fact_id: int, accept: bool) -> dict[str, Any]:
    """A person reviews an inferred proposal. Accepting makes it the project's position; rejecting keeps it as history."""
    f = get(fact_id)
    if not f:
        raise LookupError("no such fact")
    if f["status"] != "proposed":
        return f
    new = "active" if accept else "rejected"
    with db.tx() as conn:
        conn.execute("UPDATE project_facts SET status=?, explicitness=CASE WHEN ?='active' THEN 'accepted_recommendation' ELSE explicitness END, "
                     "updated_at=? WHERE id=?", (new, new, time.time(), fact_id))
        ledger.record(conn, f["project_id"], event_type=_RECORDED.get(f["kind"], "fact_recorded") if accept else "fact_proposal_rejected",
                      object_type="fact", object_id=fact_id, before={"status": "proposed"}, after={"status": new, "content": f["content"][:1000]},
                      floor={f.get("disclosure_class") or "restricted"})
    return get(fact_id)  # type: ignore[return-value]


def _ctx() -> dict[str, Any]:
    c = ledger.current()
    return {"actor_id": c.get("actor_id", "system"), "surface": c.get("surface"), "client_id": c.get("client_id"),
            "intake_id": c.get("intake_id"), "originating_actor_id": c.get("originating_actor_id"),
            "originating_request_id": c.get("originating_request_id")}


def current_position(project_id: str, *, scope: str = "project") -> list[dict[str, Any]]:
    return [dict(r) for r in db.connect().execute(
        "SELECT * FROM project_facts WHERE project_id=? AND status='active' AND scope=? ORDER BY created_at", (project_id, scope)).fetchall()]


def history(fact_id: int) -> list[dict[str, Any]]:
    """The chain a fact belongs to, oldest first (follows supersedes_fact_id both ways)."""
    conn = db.connect()
    root = get(fact_id)
    if not root:
        return []
    while root.get("supersedes_fact_id"):
        prev = get(root["supersedes_fact_id"])
        if not prev:
            break
        root = prev
    chain = [root]
    while True:
        nxt = conn.execute("SELECT * FROM project_facts WHERE supersedes_fact_id=? ORDER BY id LIMIT 1", (chain[-1]["id"],)).fetchone()
        if not nxt:
            break
        chain.append(dict(nxt))
    return chain


def as_public(row: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "kind", "content", "status", "scope", "explicitness", "rationale", "actor_id", "external_client_id",
            "effective_at", "supersedes_fact_id", "created_at", "updated_at")
    return {k: row.get(k) for k in keep}


_ = json  # (kept for callers that serialise facts through this module)
