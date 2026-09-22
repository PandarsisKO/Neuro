"""P11 EA-7 — a small OAuth 2.1 authorization server for external AI clients (plan §4, §8; mission §40, §55, §62).

Why it exists (re-verified against OpenAI's documentation on 2026-09-22): ChatGPT authenticates a custom MCP server
only through OAuth 2.1 (Client ID Metadata Documents or Dynamic Client Registration, PKCE) or with no auth at all —
a static bearer credential cannot be configured. No-auth would erase who is speaking, so Neuro issues OAuth tokens
itself, and every token resolves to one ordinary external credential (access.py): revoking that credential in the
Access card ends the connection, and everything downstream (ACL, disclosure, attribution, audit) is unchanged.

The PERSON is bound by an owner-issued, single-use connection invite that they type on the consent page — Neuro has
no user accounts to log into, and the invite is exactly "Kyle decided Gio may connect". Nothing here is vendor-specific.

Standards: RFC 9728 protected-resource metadata · RFC 8414 authorization-server metadata · RFC 7591 dynamic
registration · OAuth Client ID Metadata Documents · RFC 7636 PKCE (S256 only) · refresh-token rotation.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from . import access, db
from .access import AccessError

ACCESS_PREFIX, REFRESH_PREFIX, INVITE_PREFIX = "nsa_", "nsr_", "nsi_"
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 86400
CODE_TTL_S = 600
INVITE_TTL_S = 7 * 86400
CIMD_TTL_S = 86400
SCOPE = "neuro"
MCP_PATH = "/ext/mcp"


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def base_url(request_base: str | None = None) -> str:
    from .config import settings
    return (settings.public_url or request_base or "http://localhost:8000").rstrip("/")


def protected_resource_metadata(base: str) -> dict[str, Any]:
    return {"resource": f"{base}{MCP_PATH}", "authorization_servers": [base], "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"], "resource_name": "Neuro"}


def authorization_server_metadata(base: str) -> dict[str, Any]:
    return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register", "revocation_endpoint": f"{base}/oauth/revoke",
            "scopes_supported": [SCOPE], "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"], "client_id_metadata_document_supported": True}


# ------------------------------------------------------------------ clients: DCR and CIMD

def _valid_redirect(u: str) -> bool:
    p = urlparse(u)
    return p.scheme == "https" or (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1"))


def register(meta: dict[str, Any]) -> dict[str, Any]:
    uris = meta.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) and _valid_redirect(u) for u in uris):
        raise AccessError("invalid", "redirect_uris must be a non-empty list of https URLs")
    cid, t = "nsc_" + secrets.token_urlsafe(18), time.time()
    name = str(meta.get("client_name") or "External AI client")[:120]
    with db.tx() as conn:
        conn.execute("INSERT INTO oauth_clients (client_id, client_name, redirect_uris, kind, metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (cid, name, json.dumps(uris), "dcr", json.dumps({k: meta.get(k) for k in ("client_name", "client_uri", "logo_uri")}), t, t))
    return {"client_id": cid, "client_name": name, "redirect_uris": uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "client_id_issued_at": int(t)}


def client(client_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
    now = time.time()
    if r and (r["kind"] == "dcr" or now - r["updated_at"] < CIMD_TTL_S):
        return {**dict(r), "redirect_uris": json.loads(r["redirect_uris"])}
    if client_id.startswith("https://"):
        return _cimd(client_id)
    return None


def _cimd(url: str) -> dict[str, Any] | None:
    """Client ID Metadata Document: the client_id IS an https URL whose JSON names the client. Fetched only through
    safe_fetch (SSRF boundary, §55); the document must name itself."""
    from . import safe_fetch
    try:
        res = safe_fetch.safe_fetch(url, content_class="html")
        doc = json.loads(res.body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    uris = doc.get("redirect_uris") or []
    if doc.get("client_id") != url or not uris or not all(isinstance(u, str) and _valid_redirect(u) for u in uris):
        return None
    t = time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO oauth_clients (client_id, client_name, redirect_uris, kind, metadata, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET client_name=excluded.client_name, "
                     "redirect_uris=excluded.redirect_uris, metadata=excluded.metadata, updated_at=excluded.updated_at",
                     (url, str(doc.get("client_name") or urlparse(url).hostname)[:120], json.dumps(uris), "cimd",
                      json.dumps({k: doc.get(k) for k in ("client_name", "client_uri", "logo_uri")}), t, t))
    return client(url)


# ------------------------------------------------------------------ invites (the owner's decision that a person may connect)

def create_invite(actor_id: str, *, label: str | None = None, by: str = "kyle", ttl_s: float = INVITE_TTL_S) -> tuple[dict[str, Any], str]:
    a = access.get_actor(actor_id)
    if not a or a["kind"] != "person" or a["disabled_at"] is not None:
        raise AccessError("invalid", "invites are for an active person")
    code = INVITE_PREFIX + secrets.token_urlsafe(12)
    iid, t = db.new_id(), time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_invites (id, actor_id, code_prefix, code_hash, label, created_by, created_at, expires_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (iid, actor_id, code[:12], _h(code), (label or "")[:120] or None, by, t, t + ttl_s))
    return get_invite(iid), code  # type: ignore[return-value]


def get_invite(invite_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT id, actor_id, code_prefix, label, created_by, created_at, expires_at, used_at, used_client_id, revoked_at "
                             "FROM external_invites WHERE id=?", (invite_id,)).fetchone()
    return dict(r) if r else None


def list_invites() -> list[dict[str, Any]]:
    return [get_invite(r["id"]) for r in db.connect().execute("SELECT id FROM external_invites ORDER BY created_at DESC").fetchall()]  # type: ignore[misc]


def revoke_invite(invite_id: str) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE external_invites SET revoked_at=COALESCE(revoked_at, ?) WHERE id=?", (time.time(), invite_id))


_attempts: dict[str, list[float]] = {}
_attempt_lock = threading.Lock()


def _throttle(key: str, limit: int = 10) -> None:
    t = time.monotonic()
    with _attempt_lock:
        w = [x for x in _attempts.get(key, []) if t - x < 60]
        if len(w) >= limit:
            raise AccessError("rate_limited", "too many attempts; wait a minute")
        w.append(t)
        _attempts[key] = w


# ------------------------------------------------------------------ authorize → code → token

def check_authorize(q: dict[str, str]) -> dict[str, Any]:
    if q.get("response_type") != "code":
        raise AccessError("invalid", "response_type must be code")
    c = client(q.get("client_id") or "")
    if not c:
        raise AccessError("invalid", "unknown client_id")
    if q.get("redirect_uri") not in c["redirect_uris"]:
        raise AccessError("invalid", "redirect_uri is not registered for this client")
    if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        raise AccessError("invalid", "PKCE with S256 is required")
    return c


def consent_page(q: dict[str, str], c: dict[str, Any], error: str | None = None) -> str:
    hidden = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in q.items()
                     if k in ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope", "resource"))
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect to Neuro</title><style>
body{{font:16px/1.5 -apple-system,system-ui,sans-serif;background:#f6f6f4;color:#1d1d1f;margin:0;padding:48px 16px}}
main{{max-width:420px;margin:auto;background:#fff;border-radius:14px;padding:28px;box-shadow:0 1px 3px #0002}}
h1{{font-size:20px;margin:0 0 8px}} p{{margin:0 0 16px;color:#444}} input[type=text]{{width:100%;box-sizing:border-box;padding:10px;font:inherit;border:1px solid #ccc;border-radius:8px}}
button{{margin-top:14px;width:100%;padding:11px;border:0;border-radius:8px;background:#1d1d1f;color:#fff;font:inherit;cursor:pointer}}
.err{{color:#b00020}} @media (prefers-color-scheme:dark){{body{{background:#111;color:#eee}} main{{background:#1c1c1e}} p{{color:#bbb}} input[type=text]{{background:#111;color:#eee;border-color:#444}} button{{background:#eee;color:#111}}}}
</style></head><body><main><h1>Connect {html.escape(c['client_name'] or 'this AI client')} to Neuro</h1>
<p>Enter the connection code you were given. It connects this client as <em>you</em>, to the projects you were shared, and it works once.</p>
{err}<form method="post" action="/oauth/authorize">{hidden}<input type="text" name="invite_code" autocomplete="off" autofocus placeholder="nsi_…" required>
<button type="submit">Connect</button></form></main></body></html>"""


def approve(q: dict[str, str], invite_code: str) -> str:
    """Consume the invite, create this connection's client + credential, and return the redirect with a one-time code."""
    c = check_authorize(q)
    _throttle(f"invite:{q.get('client_id')}")
    code = (invite_code or "").strip()
    r = db.connect().execute("SELECT * FROM external_invites WHERE code_prefix=?", (code[:12],)).fetchone()
    t = time.time()
    if not r or not secrets.compare_digest(r["code_hash"], _h(code)) or r["revoked_at"] is not None or r["used_at"] is not None or r["expires_at"] <= t:
        raise AccessError("auth_invalid", "that connection code is not valid (wrong, expired, or already used)")
    actor = access.get_actor(r["actor_id"])
    if not actor or actor["disabled_at"] is not None:
        raise AccessError("auth_revoked", "this person's access is disabled")
    ext_client = access.create_client(f"{actor['name']}'s {c['client_name'] or 'AI client'}", transport="tunnel")
    cred, _secret_never_stored = access.issue_credential(actor["id"], ext_client["id"], created_by=f"invite:{r['id']}")
    raw = secrets.token_urlsafe(32)
    with db.tx() as conn:
        n = conn.execute("UPDATE external_invites SET used_at=?, used_client_id=? WHERE id=? AND used_at IS NULL", (t, ext_client["id"], r["id"])).rowcount
        if n != 1:
            raise AccessError("auth_invalid", "that connection code was just used")
        conn.execute("INSERT INTO oauth_codes (code_hash, oauth_client_id, credential_id, redirect_uri, code_challenge, scope, resource, expires_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (_h(raw), c["client_id"], cred["id"], q["redirect_uri"], q["code_challenge"],
                                                  q.get("scope") or SCOPE, q.get("resource"), t + CODE_TTL_S))
    sep = "&" if "?" in q["redirect_uri"] else "?"
    return q["redirect_uri"] + sep + urlencode({k: v for k, v in (("code", raw), ("state", q.get("state"))) if v})


def _issue(cred_id: str, oauth_client_id: str, scope: str | None) -> dict[str, Any]:
    t = time.time()
    access_tok, refresh_tok = ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)
    with db.tx() as conn:
        for tok, kind, ttl in ((access_tok, "access", ACCESS_TTL_S), (refresh_tok, "refresh", REFRESH_TTL_S)):
            conn.execute("INSERT INTO oauth_tokens (id, token_prefix, token_hash, kind, credential_id, oauth_client_id, scope, created_at, expires_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (db.new_id(), tok[:12], _h(tok), kind, cred_id, oauth_client_id, scope or SCOPE, t, t + ttl))
    return {"access_token": access_tok, "token_type": "Bearer", "expires_in": ACCESS_TTL_S, "refresh_token": refresh_tok, "scope": scope or SCOPE}


def token(form: dict[str, str]) -> dict[str, Any]:
    gt = form.get("grant_type")
    _throttle(f"token:{form.get('client_id')}", limit=30)
    t = time.time()
    if gt == "authorization_code":
        r = db.connect().execute("SELECT * FROM oauth_codes WHERE code_hash=?", (_h(form.get("code") or ""),)).fetchone()
        if not r or r["used_at"] is not None or r["expires_at"] <= t:
            raise AccessError("auth_invalid", "invalid_grant")
        if form.get("client_id") != r["oauth_client_id"] or form.get("redirect_uri") != r["redirect_uri"]:
            raise AccessError("auth_invalid", "invalid_grant")
        verifier = form.get("code_verifier") or ""
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if not verifier or not secrets.compare_digest(challenge, r["code_challenge"]):
            raise AccessError("auth_invalid", "invalid_grant")
        with db.tx() as conn:
            if conn.execute("UPDATE oauth_codes SET used_at=? WHERE code_hash=? AND used_at IS NULL", (t, r["code_hash"])).rowcount != 1:
                raise AccessError("auth_invalid", "invalid_grant")
        return _issue(r["credential_id"], r["oauth_client_id"], r["scope"])
    if gt == "refresh_token":
        tok = form.get("refresh_token") or ""
        r = db.connect().execute("SELECT * FROM oauth_tokens WHERE token_prefix=? AND kind='refresh'", (tok[:12],)).fetchone()
        if not r or not secrets.compare_digest(r["token_hash"], _h(tok)) or r["revoked_at"] is not None or r["expires_at"] <= t:
            raise AccessError("auth_invalid", "invalid_grant")
        if form.get("client_id") and form["client_id"] != r["oauth_client_id"]:
            raise AccessError("auth_invalid", "invalid_grant")
        cred = access.get_credential(r["credential_id"])
        if not cred or cred["revoked_at"] is not None:
            raise AccessError("auth_revoked", "this connection was revoked")
        with db.tx() as conn:                         # rotation: a refresh token works once
            if conn.execute("UPDATE oauth_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (t, r["id"])).rowcount != 1:
                raise AccessError("auth_invalid", "invalid_grant")
        return _issue(r["credential_id"], r["oauth_client_id"], r["scope"])
    raise AccessError("invalid", "unsupported_grant_type")


def revoke_token(tok: str) -> None:
    with db.tx() as conn:
        conn.execute("UPDATE oauth_tokens SET revoked_at=COALESCE(revoked_at, ?) WHERE token_prefix=? AND token_hash=?", (time.time(), tok[:12], _h(tok)))


def resolve_access(tok: str) -> str:
    """An OAuth access token → the credential it stands for (access.authenticate does the rest)."""
    r = db.connect().execute("SELECT * FROM oauth_tokens WHERE token_prefix=? AND kind='access'", (tok[:12],)).fetchone()
    if not r or not secrets.compare_digest(r["token_hash"], _h(tok)):
        raise AccessError("auth_invalid", "unknown token")
    if r["revoked_at"] is not None:
        raise AccessError("auth_revoked", "token revoked")
    if r["expires_at"] <= time.time():
        raise AccessError("auth_invalid", "token expired")
    return r["credential_id"]
