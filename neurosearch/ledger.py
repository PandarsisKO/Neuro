"""P11 EA-2 — the project change ledger (EXTERNAL-AI-ACCESS-MISSION.md §44–§48, §60; plan §5).

One narrow, append-only table (`project_change_events`) that records what CHANGED in a project's intelligence, who
changed it, and on whose behalf. The domain tables stay the authoritative current state; this is never read back to
reconstruct state (not event sourcing, §44). It exists for the external sync cursor, chronology, attribution and
conflict context.

Rules this module enforces:
  * `record()` is called INSIDE the writer's own `db.tx()`, reads only the small tracked fields, and appends nothing
    when they did not change (§46) — a reassessment of 56 Claims that moves 2 writes 2 rows.
  * The only exception is an explicit user act that re-states a value (`decision_reaffirmed`, §47): `force=True`.
  * Nothing expensive happens under the write lock (§45). Materiality and Decision Impact are classified by an
    after-commit hook (`db.after_commit`), in their own short write.
  * Attribution is never guessed (Kyle's ruling 2, 2026-09-22). `acting()` binds WHO is acting for the current
    request/job. Unbound work is `system` — a background pass is never written as a person's act; when a person's
    request caused it, `originating_actor_id` / `originating_request_id` say so.
  * Operational churn (jobs, heartbeats, usage, caches, work units, invocations) is never ledgered: `record()` is
    called only from the modules listed in `WRITERS` (a grep gate in tests/test_ea2_ledger.py keeps that true).
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import time
from typing import Any, Iterable, Iterator

from . import db

log = logging.getLogger(__name__)

MATERIALITY_VERSION = "m1"
MAX_PAYLOAD_BYTES = 4096
WRITERS = ("db.py", "claims.py", "knowledge.py", "retire.py", "access.py", "facts.py", "intake.py", "ledger.py", "identity.py")

# Explicit-chronology events: written even when the tracked value is unchanged, only ever from an explicit user act.
FORCED = frozenset({"decision_reaffirmed"})

_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("neurosearch_actor", default=None)
_SYSTEM = {"actor_id": "system", "surface": "job"}


def current() -> dict[str, Any]:
    return dict(_ctx.get() or _SYSTEM)


@contextlib.contextmanager
def acting(actor_id: str, *, surface: str | None = None, client_id: str | None = None, request_id: str | None = None,
           intake_id: str | None = None, originating_actor_id: str | None = None,
           originating_request_id: str | None = None) -> Iterator[dict[str, Any]]:
    """Bind who is acting for everything written in this block (contextvars: safe across threads and async)."""
    ctx = {"actor_id": actor_id, "surface": surface, "client_id": client_id, "request_id": request_id,
           "intake_id": intake_id, "originating_actor_id": originating_actor_id,
           "originating_request_id": originating_request_id}
    token = _ctx.set({k: v for k, v in ctx.items() if v is not None})
    try:
        yield current()
    finally:
        _ctx.reset(token)


def bind(**ctx: Any) -> contextvars.Token:
    """Non-scoped bind, for an ASGI middleware that resets it itself."""
    return _ctx.set({k: v for k, v in ctx.items() if v is not None})


def reset(token: contextvars.Token) -> None:
    _ctx.reset(token)


def origin_for_job() -> tuple[str | None, str | None]:
    """What a job enqueued now should remember as its cause: the acting person (never 'system') and their request."""
    c = current()
    if c.get("actor_id") and c["actor_id"] != "system":
        return c["actor_id"], c.get("request_id")
    return c.get("originating_actor_id"), c.get("originating_request_id")


# ------------------------------------------------------------------ the choke point

def _bounded(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = {k: (x[:1000] + "…" if isinstance(x, str) and len(x) > 1000 else x) for k, x in v.items()}
    s = json.dumps(v, sort_keys=True, default=str)
    if len(s.encode()) > MAX_PAYLOAD_BYTES:
        s = json.dumps({"truncated": True, "keys": sorted(v)[:40] if isinstance(v, dict) else None})
    return s


def record(conn: Any, project_id: str | None, *, event_type: str, object_type: str, object_id: Any,
           before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
           floor: Iterable[str] | None = None, force: bool = False) -> int | None:
    """Append one event inside the caller's transaction when the tracked fields changed (or `force` for an explicit
    re-statement). `floor` is the disclosure class set of what before/after expose; omitted = computed from the
    object's provenance (access.py) — cheap, bounded lookups, never a scan."""
    if not project_id:
        return None
    if not force and event_type not in FORCED and before == after:
        return None
    if floor is None:
        floor = _floor_of(object_type, object_id)
    c = current()
    cur = conn.execute(
        "INSERT INTO project_change_events (project_id, event_type, object_type, object_id, actor_id, external_client_id, "
        "local_surface, intake_id, request_id, originating_actor_id, originating_request_id, before, after, disclosure_floor, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, event_type, object_type, str(object_id), c.get("actor_id") or "system", c.get("client_id"),
         None if c.get("client_id") else c.get("surface"), c.get("intake_id"), c.get("request_id"),
         c.get("originating_actor_id"), c.get("originating_request_id"), _bounded(before), _bounded(after),
         json.dumps(sorted(set(floor))), time.time()))
    db.after_commit(_classify_soon)
    return int(cur.lastrowid)


def _floor_of(object_type: str, object_id: Any) -> set[str]:
    from . import access
    try:
        if object_type == "claim":
            return set(access.claim_floors([str(object_id)])[str(object_id)])
        if object_type == "claim_evidence":
            return set(access.source_classes([str(object_id).split(":", 1)[1]]).values())
        if object_type == "finding":
            return set(access.note_floors([int(object_id)])[int(object_id)])
        if object_type in ("source", "source_membership"):
            return set(access.source_classes([str(object_id)]).values())
        if object_type == "tension":
            r = db.connect().execute("SELECT id, claim_id, related_claim_id FROM research_tensions WHERE id=?", (object_id,)).fetchone()
            return set(access.tension_floors([dict(r)])[r["id"]]) if r else {access.UNCLASSIFIED}
        if object_type == "question":
            r = db.connect().execute("SELECT claim_id FROM project_evidence_targets WHERE id=?", (object_id,)).fetchone()
            if r and r["claim_id"]:
                return set(access.claim_floors([r["claim_id"]])[r["claim_id"]])
            return {access.UNCLASSIFIED}
        if object_type == "fact":
            r = db.connect().execute("SELECT disclosure_class FROM project_facts WHERE id=?", (int(object_id),)).fetchone()
            return {access.fact_class(dict(r))} if r else {access.UNCLASSIFIED}
    except Exception:  # noqa: BLE001 — an unknowable floor is a closed floor, never a failed write
        log.debug("floor lookup failed for %s %s", object_type, object_id, exc_info=True)
    return {access.UNCLASSIFIED}


# ------------------------------------------------------------------ post-commit classification (§45, §48)

PASS_EVENTS = frozenset({"claims_reassessed"})     # maintenance summaries: counted in `summary`, never listed as changes
MATERIAL_EVENTS = frozenset({"claim_created", "claim_status_changed", "claim_statement_changed", "decision_recorded",
                             "decision_changed", "decision_reaffirmed", "decision_withdrawn", "constraint_recorded",
                             "requirement_recorded", "rejected_option_recorded", "commitment_recorded", "plan_version_created",
                             "fact_changed", "deadline_recorded"})
SUPPORTING_EVENTS = frozenset({"claim_assessment_changed", "claim_evidence_added", "source_attached", "source_removed",
                               "source_ready", "finding_status_changed", "question_opened", "question_status_changed",
                               "plan_item_status_changed", "brief_changed", "fact_proposed", "fact_recorded",
                               "preference_recorded", "intake_finalized", "intake_needs_review", "tension_status_changed",
                               "counterpart_position_recorded", "concern_recorded", "open_question_recorded"})
DECISION_EVENTS = frozenset({"decision_recorded", "decision_changed", "decision_reaffirmed", "decision_withdrawn",
                             "constraint_recorded", "requirement_recorded", "plan_version_created"})


def _classify_soon() -> None:
    try:
        classify_pending()
    except Exception:  # noqa: BLE001 — classification is derived; it is retried on the next read
        log.warning("ledger classification deferred", exc_info=True)


def classify_pending(limit: int = 500) -> int:
    """Fill materiality / decision_impact for unclassified events. Runs after commit, never under another writer's
    transaction; reads first, then one short write."""
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, project_id, event_type, object_type, object_id, after FROM project_change_events WHERE materiality IS NULL "
        "ORDER BY id LIMIT ?", (limit,)).fetchall()]
    if not rows:
        return 0
    from .decision_impact import decision_impact
    by_project: dict[str, list[str]] = {}
    for r in rows:
        if r["object_type"] == "claim":
            by_project.setdefault(r["project_id"], []).append(r["object_id"])
    impact: dict[str, dict[str, Any]] = {}
    for pid, cids in by_project.items():
        try:
            impact.update(decision_impact(pid, list(dict.fromkeys(cids))))
        except Exception:  # noqa: BLE001
            log.debug("decision impact unavailable for %s", pid, exc_info=True)
    updates = []
    for r in rows:
        et = r["event_type"]
        di = None
        if et in DECISION_EVENTS:
            di = {"kind": "decision", "basis": "user_state" if et != "plan_version_created" else "plan"}
        elif r["object_type"] == "claim" and impact.get(r["object_id"], {}).get("plan_impact") is True:
            di = {"kind": "plan", "basis": "plan_cites_claim_evidence"}
        after = json.loads(r["after"] or "{}") if r["after"] else {}
        if et == "tension_opened":
            m = "material" if after.get("impact") == "high" else "supporting"
        elif et == "claim_created":
            m = "material" if after.get("status") == "accepted" or di else "supporting"
        elif et == "claim_assessment_changed":
            m = "material" if di else "supporting"
        elif et in MATERIAL_EVENTS:
            m = "material"
        elif et in SUPPORTING_EVENTS:
            m = "supporting"
        else:
            m = "none"
        updates.append((m, json.dumps(di) if di else None, r["id"]))
    with db.tx() as c:
        c.executemany("UPDATE project_change_events SET materiality=?, decision_impact=? WHERE id=? AND materiality IS NULL", updates)
    return len(updates)


# ------------------------------------------------------------------ reads (disclosure is an input, §41)

def _floor_sql(classes: Iterable[str]) -> tuple[str, list[str]]:
    cl = sorted(set(classes))
    if not cl:
        return "0", []
    marks = ",".join("?" * len(cl))
    return f"NOT EXISTS (SELECT 1 FROM json_each(e.disclosure_floor) j WHERE j.value NOT IN ({marks}))", cl


def cursor(project_id: str, classes: Iterable[str] | None = None) -> int:
    if classes is None:
        r = db.connect().execute("SELECT COALESCE(MAX(id), 0) FROM project_change_events WHERE project_id=?", (project_id,)).fetchone()
    else:
        pred, args = _floor_sql(classes)
        r = db.connect().execute(f"SELECT COALESCE(MAX(e.id), 0) FROM project_change_events e WHERE e.project_id=? AND {pred}",
                                 (project_id, *args)).fetchone()
    return int(r[0])


def events(project_id: str, *, since: int = 0, classes: Iterable[str] | None = None, limit: int = 100,
           object_type: str | None = None, object_id: str | None = None,
           min_materiality: str | None = None) -> dict[str, Any]:
    """A cursor page of the change stream, floor-filtered IN the query. Impact-ordered inside the page; the cursor
    is always the page's max id so nothing is skipped or repeated."""
    classify_pending()
    limit = max(1, min(int(limit), 100))
    base = ["e.project_id=?", "e.id>?"]
    base_args: list[Any] = [project_id, int(since)]
    if object_type:
        base.append("e.object_type=?"); base_args.append(object_type)
    if object_id is not None:
        base.append("e.object_id=?"); base_args.append(str(object_id))
    if min_materiality == "material":
        base.append("e.materiality='material'")
    elif min_materiality == "supporting":
        base.append("e.materiality IN ('material','supporting')")
    fpred, fargs = _floor_sql(classes) if classes is not None else ("1", [])
    conn = db.connect()
    # the window's upper edge, read once: the cursor may pass events this grant cannot see, never ones not yet read
    top = int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM project_change_events WHERE project_id=?", (project_id,)).fetchone()[0])
    base.append("e.id<=?"); base_args.append(top)
    rows = [dict(r) for r in conn.execute(
        f"SELECT e.* FROM project_change_events e WHERE {' AND '.join(base)} AND {fpred} ORDER BY e.id LIMIT ?",
        (*base_args, *fargs, limit + 1)).fetchall()]
    more = len(rows) > limit
    rows = rows[:limit]
    withheld = 0
    if classes is not None:
        # how many events in the same window this grant was NOT shown — a count, never their content (§64)
        hi = rows[-1]["id"] if (rows and more) else None
        cond = " AND ".join(base) + (" AND e.id<=?" if hi is not None else "")
        tail = [hi] if hi is not None else []
        total = conn.execute(f"SELECT COUNT(*) FROM project_change_events e WHERE {cond}", (*base_args, *tail)).fetchone()[0]
        visible = conn.execute(f"SELECT COUNT(*) FROM project_change_events e WHERE {cond} AND {fpred}", (*base_args, *tail, *fargs)).fetchone()[0]
        withheld = int(total - visible)
    for r in rows:
        r["before"] = json.loads(r["before"]) if r["before"] else None
        r["after"] = json.loads(r["after"]) if r["after"] else None
        r["decision_impact"] = json.loads(r["decision_impact"]) if r["decision_impact"] else None
        r["disclosure_floor"] = json.loads(r["disclosure_floor"])
    passes = [r for r in rows if r["event_type"] in PASS_EVENTS]
    changes = [r for r in rows if r["event_type"] not in PASS_EVENTS]
    summary = {"reassessed": sum(int((r["after"] or {}).get("reassessed") or 0) for r in passes),
               "changed": len(changes),
               "material": sum(1 for r in changes if r["materiality"] == "material"),
               "decision_affecting": sum(1 for r in changes if r["decision_impact"]),
               "withheld": withheld}
    rank = {"material": 0, "supporting": 1, "none": 2}
    ordered = sorted(changes, key=lambda r: (0 if r["decision_impact"] else 1, rank.get(r["materiality"] or "none", 2), r["id"]))
    return {"summary": summary, "events": ordered, "next_cursor": rows[-1]["id"] if more else max(int(since), top), "more": more}
