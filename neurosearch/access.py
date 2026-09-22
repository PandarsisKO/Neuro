"""P11 EA-1 — external principals, project ACL and disclosure-at-assembly.

EXTERNAL-AI-ACCESS-MISSION.md §40–§43 and §61, executed per docs/P11-EXECUTION-PLAN-2026-09-22.md §4.

Three independent questions, answered in this order and never collapsed:
  1. WHO is calling?        `authenticate(secret)` → Principal (credential → actor + client). No credential, no call.
  2. MAY they do this here? `authorize(principal, project_id, operation)` → Authorization (role × operation).
  3. WHAT may they SEE?     `Authorization.classes` — an INPUT to every read assembly (`allowed_source_ids`,
                            `*_floors`), never a filter applied to a finished answer (§41).

The legacy shared app token (api.py `require_auth`) is untouched and never accepted here; an external credential is
never accepted there. Local administration (issuing credentials, grants, classification) is a local-owner act behind
the legacy token and lives in the functions at the bottom of this module.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import db
from .external_schemas import DISCLOSURE_CLASSES

TOKEN_PREFIX = "nsx_"
PREFIX_LEN = 12                          # "nsx_" + 8: the lookup key; the only part of a secret ever logged or shown again
ROLES = ("read", "contribute", "owner")
DEFAULT_GRANT_CLASSES = ("standard",)    # Kyle, 2026-09-22: a new grant is standard-only; the rest is explicit opt-in
READ_OPS = frozenset({"list_projects", "open_project", "get_project_changes", "search_project", "get_evidence",
                      "consult_project", "get_intake_status", "get_project_timeline"})
WRITE_OPS = frozenset({"create_intake", "add_processed_material", "attach_artifact", "finalize_intake",
                       "sync_project_state"})
OPS_BY_ROLE = {"read": READ_OPS, "contribute": READ_OPS | WRITE_OPS, "owner": READ_OPS | WRITE_OPS}
# Class rank for the raise-only rule (§41): a client may make material MORE restrictive, never less. Two different
# sensitive classes are not comparable; a conflict between them resolves to `restricted` (uncertainty defaults closed).
RANK = {"standard": 0, "correspondence": 1, "financial": 1, "tax": 1, "identity": 1, "restricted": 2}
RATE_PER_MIN = 60
LAST_USED_WRITE_S = 60.0
EXTERNAL_REQUEST_RETENTION_S = 30 * 86400
UNCLASSIFIED = "restricted"              # what NULL means for external disclosure (§41, §43)

# §43, as ONE expression used by the backfill AND by every read path, so a source is judged identically before and
# after the backfill materialises it (and a YouTube video added after the backfill is still judged). Public means the
# CONTENT is public and nothing private touched its acquisition: a public (ungated) YouTube video or a podcast episode
# with no browser capture, or a page the server itself fetched anonymously (`acquisition_provenance='anonymous'`,
# written by ingest.ingest_webpage). Everything else -- uploads, manual text, Instagram (extension session only),
# browser/DOM captures, legacy web pages whose origin was never recorded -- is restricted until an owner says otherwise.
PUBLIC_PLATFORMS = ("youtube", "podcast")


def effective_class_sql(alias: str = "s") -> str:
    a = alias
    return (f"(CASE WHEN {a}.disclosure_class IS NOT NULL THEN {a}.disclosure_class "
            f"WHEN {a}.access_gate IS NULL AND {a}.acquisition_provenance = 'anonymous' THEN 'standard' "
            f"WHEN {a}.access_gate IS NULL AND {a}.acquisition_provenance IS NULL AND {a}.platform IN ('youtube','podcast') "
            f"AND NOT EXISTS (SELECT 1 FROM source_captures sc WHERE sc.source_id = {a}.id) THEN 'standard' "
            f"ELSE 'restricted' END)")


class AccessError(Exception):
    """A refused external request. `code` is the Health taxonomy (§64); `status` its HTTP mapping."""
    STATUS = {"auth_invalid": 401, "auth_revoked": 401, "project_unauthorized": 404, "forbidden": 403,
              "rate_limited": 429, "invalid": 422, "capability_missing": 422, "conflict": 409, "not_found": 404}

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code, self.message = code, message or code
        self.status = self.STATUS.get(code, 400)


@dataclass(frozen=True)
class Principal:
    credential_id: str
    actor_id: str
    client_id: str
    actor_name: str = ""
    client_label: str = ""


@dataclass(frozen=True)
class Authorization:
    principal: Principal
    project_id: str
    role: str
    classes: frozenset[str]
    extra: frozenset[str] = field(default_factory=frozenset)

    def may_see(self, floor: Iterable[str]) -> bool:
        """A derived object is disclosable only when EVERY class it depends on is granted (§42)."""
        return set(floor) <= self.classes


# ------------------------------------------------------------------ authentication

def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


_rate: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _check_rate(credential_id: str) -> None:
    t = time.monotonic()
    with _rate_lock:
        window = [x for x in _rate.get(credential_id, []) if t - x < 60.0]
        if len(window) >= RATE_PER_MIN:
            _rate[credential_id] = window
            raise AccessError("rate_limited", f"more than {RATE_PER_MIN} requests in a minute")
        window.append(t)
        _rate[credential_id] = window


_CRED_SQL = ("SELECT c.*, a.name AS actor_name, a.disabled_at AS actor_disabled, k.label AS client_label "
             "FROM external_credentials c JOIN external_actors a ON a.id=c.actor_id JOIN external_clients k ON k.id=c.client_id ")


def authenticate(secret: str | None) -> Principal:
    """A static credential (`nsx_…`), or an OAuth access token (`nsa_…`, oauth.py) that stands for one. Either way
    every check below — revoked, disabled, expired, rate — is made against the credential."""
    if secret and secret.startswith("nsa_"):
        from . import oauth
        row = db.connect().execute(_CRED_SQL + "WHERE c.id=?", (oauth.resolve_access(secret),)).fetchone()
        if row is None:
            raise AccessError("auth_invalid", "unknown credential")
    else:
        if not secret or not secret.startswith(TOKEN_PREFIX) or len(secret) < PREFIX_LEN + 16:
            raise AccessError("auth_invalid", "missing or malformed credential")
        row = db.connect().execute(_CRED_SQL + "WHERE c.token_prefix=?", (secret[:PREFIX_LEN],)).fetchone()
        if row is None or not secrets.compare_digest(row["token_hash"], _hash(secret)):
            raise AccessError("auth_invalid", "unknown credential")
    t = time.time()
    if row["revoked_at"] is not None and row["revoked_at"] <= t:
        raise AccessError("auth_revoked", row["revoke_reason"] or "credential revoked")
    if row["actor_disabled"] is not None:
        raise AccessError("auth_revoked", "this person's access is disabled")
    if row["expires_at"] is not None and row["expires_at"] <= t:
        raise AccessError("auth_invalid", "credential expired")
    _check_rate(row["id"])
    if row["last_used_at"] is None or t - row["last_used_at"] > LAST_USED_WRITE_S:
        with db.tx() as conn:
            conn.execute("UPDATE external_credentials SET last_used_at=? WHERE id=?", (t, row["id"]))
    return Principal(row["id"], row["actor_id"], row["client_id"], row["actor_name"], row["client_label"])


def _grant(project_id: str, actor_id: str) -> dict[str, Any] | None:
    r = db.connect().execute(
        "SELECT g.* FROM external_project_grants g JOIN projects p ON p.id=g.project_id "
        "WHERE g.project_id=? AND g.actor_id=? AND g.revoked_at IS NULL", (project_id, actor_id)).fetchone()
    return dict(r) if r else None


def authorize(principal: Principal, project_id: str | None, operation: str) -> Authorization:
    """Role × operation for ONE project. An ungranted project and a nonexistent one are the same answer (404): an
    external caller learns nothing about projects it was not given (IDOR, plan §4)."""
    if not project_id:
        raise AccessError("project_unauthorized", "no such project")
    g = _grant(project_id, principal.actor_id)
    if g is None:
        raise AccessError("project_unauthorized", "no such project")
    if operation not in OPS_BY_ROLE.get(g["role"], frozenset()):
        raise AccessError("forbidden", f"your access to this project is {g['role']}; {operation} needs contribute")
    classes = frozenset(c for c in json.loads(g["disclosure_classes"] or "[]") if c in DISCLOSURE_CLASSES)
    return Authorization(principal, project_id, g["role"], classes, frozenset(json.loads(g["extra_permissions"] or "[]")))


def granted_projects(principal: Principal) -> list[dict[str, Any]]:
    rows = db.connect().execute(
        "SELECT p.id, p.name, p.updated_at, g.role, g.disclosure_classes FROM external_project_grants g "
        "JOIN projects p ON p.id=g.project_id WHERE g.actor_id=? AND g.revoked_at IS NULL ORDER BY p.name",
        (principal.actor_id,)).fetchall()
    return [{**dict(r), "disclosure_classes": json.loads(r["disclosure_classes"] or "[]")} for r in rows]


def record_request(principal: Principal | None, operation: str, project_id: str | None, outcome: str,
                   detail: str | None = None, duration_ms: int | None = None, credential_prefix: str | None = None) -> None:
    """The audit boundary (§61, §64): who asked for what, and the outcome code. Never a payload, never a secret."""
    t = time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_requests (credential_id, actor_id, client_id, operation, project_id, outcome, detail, duration_ms, created_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (principal.credential_id if principal else credential_prefix, principal.actor_id if principal else None,
                      principal.client_id if principal else None, operation[:80], project_id, outcome, (detail or "")[:300] or None,
                      duration_ms, t))
        if int(t) % 97 == 0:
            conn.execute("DELETE FROM external_requests WHERE created_at < ?", (t - EXTERNAL_REQUEST_RETENTION_S,))


# ------------------------------------------------------------------ disclosure at assembly (§41–§42)

def _chunks(xs: list[Any], n: int = 800) -> Iterable[list[Any]]:
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def source_classes(source_ids: Iterable[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(source_ids))
    out: dict[str, str] = {}
    conn = db.connect()
    for part in _chunks(ids):
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT s.id, {effective_class_sql('s')} AS cls FROM sources s WHERE s.id IN ({q})", part).fetchall():
            out[r["id"]] = r["cls"]
    for sid in ids:                       # a source id that no longer resolves has no provable class
        out.setdefault(sid, UNCLASSIFIED)
    return out


def allowed_source_ids(project_id: str, classes: Iterable[str], *, ready_only: bool = True) -> list[str]:
    """The project's sources this grant may receive, decided BEFORE retrieval so restricted text never enters a
    candidate set (§41: an input to assembly, not an egress filter)."""
    allowed = set(classes)
    ids = db.project_source_ids(project_id, ready_only=ready_only)
    if not ids or not allowed:
        return []
    cls = source_classes(ids)
    return [i for i in ids if cls.get(i) in allowed]


def note_floors(note_ids: Iterable[int]) -> dict[int, frozenset[str]]:
    ids = list(dict.fromkeys(int(i) for i in note_ids))
    conn = db.connect()
    src: dict[int, str | None] = {}
    for part in _chunks(ids):
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT id, source_id FROM project_notes WHERE id IN ({q})", part).fetchall():
            src[r["id"]] = r["source_id"]
    cls = source_classes([s for s in src.values() if s])
    # a finding with no source row has no provable provenance: closed
    return {i: frozenset({cls[src[i]]}) if src.get(i) else frozenset({UNCLASSIFIED}) for i in ids}


def claim_floors(claim_ids: Iterable[str]) -> dict[str, frozenset[str]]:
    """Most restrictive class set over everything a Claim rests on: its cited evidence and the finding it came from."""
    ids = list(dict.fromkeys(claim_ids))
    conn = db.connect()
    deps: dict[str, set[str]] = {i: set() for i in ids}
    notes: dict[str, set[int]] = {i: set() for i in ids}
    for part in _chunks(ids):
        q = ",".join("?" * len(part))
        for r in conn.execute(f"SELECT claim_id, source_id FROM claim_evidence WHERE claim_id IN ({q})", part).fetchall():
            deps[r["claim_id"]].add(r["source_id"])
        for r in conn.execute(f"SELECT id, origin_note_id FROM project_claims WHERE id IN ({q})", part).fetchall():
            if r["origin_note_id"] is not None:
                notes[r["id"]].add(int(r["origin_note_id"]))
        for r in conn.execute(f"SELECT claim_id, note_id FROM claim_evidence_notes WHERE claim_id IN ({q})", part).fetchall():
            notes[r["claim_id"]].add(int(r["note_id"]))
    cls = source_classes({s for d in deps.values() for s in d})
    nf = note_floors({n for ns in notes.values() for n in ns})
    out: dict[str, frozenset[str]] = {}
    for cid in ids:
        f = {cls[s] for s in deps[cid]}
        for n in notes[cid]:
            f |= nf.get(n, frozenset({UNCLASSIFIED}))
        out[cid] = frozenset(f or {UNCLASSIFIED})
    return out


def tension_floors(rows: Iterable[dict[str, Any]]) -> dict[str, frozenset[str]]:
    rows = list(rows)
    cids = {c for r in rows for c in (r.get("claim_id"), r.get("related_claim_id")) if c}
    cf = claim_floors(cids) if cids else {}
    out = {}
    for r in rows:
        deps = [cf[c] for c in (r.get("claim_id"), r.get("related_claim_id")) if c and c in cf]
        out[r["id"]] = frozenset().union(*deps) if deps else frozenset({UNCLASSIFIED})
    return out


def fact_class(row: dict[str, Any]) -> str:
    """User state is classified directly; a legacy fact written before classification existed is user-private
    input (§43) and stays closed until the owner classifies it."""
    return row.get("disclosure_class") or UNCLASSIFIED


def merge_declared(existing: str | None, declared: str | None) -> str | None:
    """Raise-only (§41). None + declared → declared; a lower declaration never lowers; two different sensitive
    classes are incomparable and resolve closed."""
    if declared is None:
        return existing
    if existing is None or existing == declared:
        return declared
    if RANK[declared] > RANK[existing]:
        return declared
    if RANK[declared] == RANK[existing]:
        return "restricted"
    return existing


# ------------------------------------------------------------------ local owner administration

def _check_class_list(classes: Iterable[str]) -> list[str]:
    out = list(dict.fromkeys(classes))
    bad = [c for c in out if c not in DISCLOSURE_CLASSES]
    if bad:
        raise AccessError("invalid", f"unknown disclosure class: {', '.join(bad)}")
    return out


def create_actor(name: str, *, actor_id: str | None = None, kind: str = "person") -> dict[str, Any]:
    if kind not in ("person", "system"):
        raise AccessError("invalid", "kind must be person or system")
    aid = actor_id or db.new_id()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_actors (id, name, kind, created_at) VALUES (?,?,?,?)", (aid, name.strip()[:200], kind, time.time()))
    return get_actor(aid)  # type: ignore[return-value]


def get_actor(actor_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM external_actors WHERE id=?", (actor_id,)).fetchone()
    return dict(r) if r else None


def list_actors() -> list[dict[str, Any]]:
    return [dict(r) for r in db.connect().execute("SELECT * FROM external_actors ORDER BY kind, name").fetchall()]


def set_actor_disabled(actor_id: str, disabled: bool) -> dict[str, Any] | None:
    if actor_id in ("kyle", "system"):
        raise AccessError("invalid", "the local owner and the system actor cannot be disabled")
    with db.tx() as conn:
        conn.execute("UPDATE external_actors SET disabled_at=? WHERE id=?", (time.time() if disabled else None, actor_id))
    return get_actor(actor_id)


def create_client(label: str, *, transport: str = "local", client_id: str | None = None) -> dict[str, Any]:
    if transport not in ("local", "lan", "tunnel"):
        raise AccessError("invalid", "transport must be local, lan or tunnel")
    cid = client_id or db.new_id()
    t = time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_clients (id, label, transport, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (cid, label.strip()[:200], transport, t, t))
    return get_client(cid)  # type: ignore[return-value]


def get_client(client_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM external_clients WHERE id=?", (client_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["capabilities"] = json.loads(d["capabilities"] or "{}")
    return d


def list_clients() -> list[dict[str, Any]]:
    return [get_client(r["id"]) for r in db.connect().execute("SELECT id FROM external_clients ORDER BY label").fetchall()]  # type: ignore[misc]


def set_client_capabilities(client_id: str, capabilities: dict[str, Any]) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE external_clients SET capabilities=?, updated_at=? WHERE id=?",
                     (json.dumps(capabilities, sort_keys=True), time.time(), client_id))


def issue_credential(actor_id: str, client_id: str, *, created_by: str = "kyle", expires_at: float | None = None,
                     rotated_from: str | None = None) -> tuple[dict[str, Any], str]:
    """Returns (row, secret). The secret exists only in this return value: it is shown once and never stored."""
    if not get_actor(actor_id):
        raise AccessError("invalid", "unknown actor")
    if not get_client(client_id):
        raise AccessError("invalid", "unknown client")
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    cid = db.new_id()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_credentials (id, actor_id, client_id, token_prefix, token_hash, created_at, created_by, expires_at, rotated_from) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (cid, actor_id, client_id, secret[:PREFIX_LEN], _hash(secret), time.time(), created_by, expires_at, rotated_from))
    return get_credential(cid), secret  # type: ignore[return-value]


def get_credential(credential_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT id, actor_id, client_id, token_prefix, created_at, created_by, expires_at, last_used_at, "
                             "revoked_at, revoked_by, revoke_reason, rotated_from FROM external_credentials WHERE id=?", (credential_id,)).fetchone()
    return dict(r) if r else None


def list_credentials() -> list[dict[str, Any]]:
    return [get_credential(r["id"]) for r in db.connect().execute(  # type: ignore[misc]
        "SELECT id FROM external_credentials ORDER BY created_at DESC").fetchall()]


def revoke_credential(credential_id: str, *, by: str = "kyle", reason: str | None = None, at: float | None = None) -> dict[str, Any] | None:
    """§61: stops new requests from this credential. Material it already delivered stays in the project with its
    attribution; nothing is deleted."""
    with db.tx() as conn:
        conn.execute("UPDATE external_credentials SET revoked_at=COALESCE(revoked_at, ?), revoked_by=COALESCE(revoked_by, ?), "
                     "revoke_reason=COALESCE(revoke_reason, ?) WHERE id=?", (at or time.time(), by, reason or "revoked by owner", credential_id))
    return get_credential(credential_id)


def rotate_credential(credential_id: str, *, by: str = "kyle", overlap_s: float = 0.0) -> tuple[dict[str, Any], str]:
    old = get_credential(credential_id)
    if not old:
        raise AccessError("not_found", "no such credential")
    new, secret = issue_credential(old["actor_id"], old["client_id"], created_by=by, rotated_from=credential_id)
    revoke_credential(credential_id, by=by, reason="rotated", at=time.time() + max(0.0, overlap_s))
    return new, secret


def grant(project_id: str, actor_id: str, role: str, *, classes: Iterable[str] | None = None, by: str = "kyle") -> dict[str, Any]:
    """Create or re-activate a grant. A NEW grant is standard-only unless the owner names more classes here."""
    if role not in ROLES:
        raise AccessError("invalid", f"role must be one of {', '.join(ROLES)}")
    if not db.get_project(project_id):
        raise AccessError("not_found", "no such project")
    if not get_actor(actor_id) or actor_id == "system":
        raise AccessError("invalid", "unknown actor")
    cls = _check_class_list(classes if classes is not None else DEFAULT_GRANT_CLASSES)
    t = time.time()
    before = get_grant(project_id, actor_id)
    with db.tx() as conn:
        _ledger_access(conn, project_id, actor_id, before, {"role": role, "classes": cls, "active": True})
        conn.execute("INSERT INTO external_project_grants (project_id, actor_id, role, disclosure_classes, granted_by, granted_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id, actor_id) DO UPDATE SET role=excluded.role, "
                     "disclosure_classes=excluded.disclosure_classes, granted_by=excluded.granted_by, updated_at=excluded.updated_at, "
                     "revoked_at=NULL, revoked_by=NULL", (project_id, actor_id, role, json.dumps(cls), by, t, t))
    return get_grant(project_id, actor_id)  # type: ignore[return-value]


def set_grant_classes(project_id: str, actor_id: str, classes: Iterable[str], *, by: str = "kyle") -> dict[str, Any]:
    cls = _check_class_list(classes)
    before = get_grant(project_id, actor_id)
    with db.tx() as conn:
        if before and before["revoked_at"] is None:
            _ledger_access(conn, project_id, actor_id, before, {"role": before["role"], "classes": cls, "active": True})
        n = conn.execute("UPDATE external_project_grants SET disclosure_classes=?, updated_at=?, granted_by=? "
                         "WHERE project_id=? AND actor_id=? AND revoked_at IS NULL", (json.dumps(cls), time.time(), by, project_id, actor_id)).rowcount
    if not n:
        raise AccessError("not_found", "no active grant")
    return get_grant(project_id, actor_id)  # type: ignore[return-value]


def revoke_grant(project_id: str, actor_id: str, *, by: str = "kyle") -> dict[str, Any] | None:
    before = get_grant(project_id, actor_id)
    with db.tx() as conn:
        if before and before["revoked_at"] is None:
            _ledger_access(conn, project_id, actor_id, before, {"role": before["role"], "classes": before["disclosure_classes"], "active": False})
        conn.execute("UPDATE external_project_grants SET revoked_at=?, revoked_by=? WHERE project_id=? AND actor_id=? AND revoked_at IS NULL",
                     (time.time(), by, project_id, actor_id))
    return get_grant(project_id, actor_id)


def _ledger_access(conn: Any, project_id: str, actor_id: str, before: dict[str, Any] | None, after: dict[str, Any]) -> None:
    """§61: the access boundary is audited in the project's own chronology. Floor `restricted`: who may see what is
    the owner's business, not something a collaborator's client is sent."""
    from . import ledger
    b = None if not before else {"role": before["role"], "classes": before["disclosure_classes"], "active": before["revoked_at"] is None}
    et = "access_granted" if not b or not b["active"] else ("access_revoked" if not after["active"] else "access_changed")
    ledger.record(conn, project_id, event_type=et, object_type="access", object_id=actor_id, before=b,
                  after={**after, "actor_id": actor_id}, floor={"restricted"})


def get_grant(project_id: str, actor_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM external_project_grants WHERE project_id=? AND actor_id=?", (project_id, actor_id)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["disclosure_classes"] = json.loads(d["disclosure_classes"] or "[]")
    d["extra_permissions"] = json.loads(d["extra_permissions"] or "[]")
    return d


def list_grants(project_id: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT project_id, actor_id FROM external_project_grants" + (" WHERE project_id=?" if project_id else "") + " ORDER BY granted_at"
    return [get_grant(r["project_id"], r["actor_id"]) for r in db.connect().execute(q, (project_id,) if project_id else ()).fetchall()]  # type: ignore[misc]


def set_source_class(source_id: str, cls: str, *, by: str = "kyle", reason: str | None = None) -> dict[str, Any]:
    """Owner-only, audited (§41). The only path that may LOWER a source's class."""
    _check_class_list([cls])
    conn = db.connect()
    r = conn.execute(f"SELECT s.disclosure_class, {effective_class_sql('s')} AS eff FROM sources s WHERE s.id=?", (source_id,)).fetchone()
    if not r:
        raise AccessError("not_found", "no such source")
    with db.tx() as c:
        c.execute("UPDATE sources SET disclosure_class=?, disclosure_origin='owner_set' WHERE id=?", (cls, source_id))
        c.execute("INSERT INTO disclosure_audit (object_type, object_id, from_class, to_class, actor_id, reason, created_at) VALUES ('source',?,?,?,?,?,?)",
                  (source_id, r["disclosure_class"] or f"unclassified:{r['eff']}", cls, by, reason, time.time()))
    return {"source_id": source_id, "from": r["disclosure_class"], "to": cls}


def set_fact_class(fact_id: int, cls: str, *, by: str = "kyle", reason: str | None = None) -> dict[str, Any]:
    _check_class_list([cls])
    r = db.connect().execute("SELECT disclosure_class FROM project_facts WHERE id=?", (fact_id,)).fetchone()
    if not r:
        raise AccessError("not_found", "no such fact")
    with db.tx() as c:
        c.execute("UPDATE project_facts SET disclosure_class=? WHERE id=?", (cls, fact_id))
        c.execute("INSERT INTO disclosure_audit (object_type, object_id, from_class, to_class, actor_id, reason, created_at) VALUES ('fact',?,?,?,?,?,?)",
                  (str(fact_id), r["disclosure_class"], cls, by, reason, time.time()))
    return {"fact_id": fact_id, "from": r["disclosure_class"], "to": cls}


def raise_source_class(source_id: str, declared: str) -> str | None:
    """Apply a client's declared class to a source under the raise-only rule. Returns the resulting stored class."""
    _check_class_list([declared])
    conn = db.connect()
    r = conn.execute("SELECT disclosure_class FROM sources WHERE id=?", (source_id,)).fetchone()
    if not r:
        return None
    new = merge_declared(r["disclosure_class"], declared)
    if new != r["disclosure_class"]:
        with db.tx() as c:
            c.execute("UPDATE sources SET disclosure_class=?, disclosure_origin=COALESCE(disclosure_origin, 'client_declared') WHERE id=?", (new, source_id))
    return new


# ------------------------------------------------------------------ §43 legacy backfill

_PRIVATE_PLATFORMS = ("instagram", "file", "document", "spreadsheet", "image", "manual", "book")


def backfill_classes(*, apply: bool = False) -> dict[str, Any]:
    """Materialise §43 for every source whose class is still NULL. Deterministic and idempotent:
      provably public (effective_class_sql says 'standard')      → standard   / backfill_public
      provably private (session/upload/capture/gated/manual)       → restricted / backfill_private
      provenance undecidable (legacy web pages, community threads) → left NULL (= restricted for disclosure)
    `apply=False` is the dry run and writes nothing."""
    conn = db.connect()
    eff = effective_class_sql("s")
    plat = ",".join(f"'{p}'" for p in _PRIVATE_PLATFORMS)
    private_pred = (f"(s.platform IN ({plat}) OR s.access_gate IS NOT NULL "
                    f"OR COALESCE(s.acquisition_provenance, '') IN ('browser_private','user_private') "
                    f"OR EXISTS (SELECT 1 FROM source_captures sc WHERE sc.source_id = s.id))")
    public = conn.execute(f"SELECT COUNT(*) FROM sources s WHERE s.disclosure_class IS NULL AND {eff}='standard'").fetchone()[0]
    private = conn.execute(f"SELECT COUNT(*) FROM sources s WHERE s.disclosure_class IS NULL AND {eff}!='standard' AND {private_pred}").fetchone()[0]
    undecided = conn.execute(f"SELECT COUNT(*) FROM sources s WHERE s.disclosure_class IS NULL AND {eff}!='standard' AND NOT {private_pred}").fetchone()[0]
    by_platform = {r[0]: r[1] for r in conn.execute(
        f"SELECT s.platform || ':' || {eff}, COUNT(*) FROM sources s WHERE s.disclosure_class IS NULL GROUP BY 1").fetchall()}
    out = {"apply": apply, "public": public, "private": private, "undecided": undecided, "by_platform_effective": by_platform}
    if apply:
        with db.tx() as c:
            c.execute(f"UPDATE sources SET disclosure_class='standard', disclosure_origin='backfill_public' WHERE disclosure_class IS NULL AND id IN "
                      f"(SELECT s.id FROM sources s WHERE s.disclosure_class IS NULL AND {eff}='standard')")
            c.execute(f"UPDATE sources SET disclosure_class='restricted', disclosure_origin='backfill_private' WHERE disclosure_class IS NULL AND id IN "
                      f"(SELECT s.id FROM sources s WHERE s.disclosure_class IS NULL AND {eff}!='standard' AND {private_pred})")
    return out


# ------------------------------------------------------------------ §64 External AI Health (diagnostic, never payloads)

def health(since_s: float = 86400) -> list[dict[str, Any]]:
    """Per client: which person, transport, last request / success / refusal and the refusal's CODE — so "not
    connected" is never one undifferentiated state (transport vs credential vs project vs disclosure vs capability)."""
    conn = db.connect()
    t = time.time()
    out = []
    for c in conn.execute("SELECT * FROM external_clients ORDER BY label").fetchall():
        creds = [dict(r) for r in conn.execute("SELECT id, actor_id, last_used_at, revoked_at, expires_at FROM external_credentials WHERE client_id=?", (c["id"],)).fetchall()]
        people = sorted({r["actor_id"] for r in creds})
        last = conn.execute("SELECT operation, outcome, created_at FROM external_requests WHERE client_id=? ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
        ok = conn.execute("SELECT MAX(created_at) FROM external_requests WHERE client_id=? AND outcome='ok'", (c["id"],)).fetchone()[0]
        deny = conn.execute("SELECT operation, outcome, detail, created_at FROM external_requests WHERE client_id=? AND outcome!='ok' "
                            "ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
        n = conn.execute("SELECT COUNT(*), SUM(outcome!='ok') FROM external_requests WHERE client_id=? AND created_at>?", (c["id"], t - since_s)).fetchone()
        active = [r for r in creds if r["revoked_at"] is None or r["revoked_at"] > t]
        state = ("revoked" if creds and not active else "never_used" if not last else
                 ("ok" if last["outcome"] == "ok" else last["outcome"]))
        out.append({"client_id": c["id"], "label": c["label"], "transport": c["transport"], "people": people,
                    "capabilities": json.loads(c["capabilities"] or "{}"), "state": state,
                    "credentials": {"active": len(active), "revoked": len(creds) - len(active)},
                    "last_request": dict(last) if last else None, "last_success_at": ok,
                    "last_refusal": dict(deny) if deny else None,
                    "requests_24h": int(n[0] or 0), "refusals_24h": int(n[1] or 0)})
    return out
