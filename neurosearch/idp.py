"""P11 EA-9 correction — Neuro as an OAuth RESOURCE SERVER for an external, hosted identity provider.

Kyle's ruling (2026-09-22): do not make Neuro public to solve OAuth. Re-verified in OpenAI's documentation the same
day: in the ChatGPT flow the person's BROWSER performs the authorize/consent step and ChatGPT's BACKEND exchanges the
code for a token, so the authorization server must be reachable from the internet; Secure MCP Tunnel carries the MCP
connection and OAuth discovery but "the authorization server itself is not automatically tunneled"; and OpenAI
"strongly recommend[s] that you use an existing established identity provider rather than implementing authentication
from scratch". So the default shape is:

    ChatGPT ──(Secure MCP Tunnel)──▶ Neuro /ext/mcp          private; the Mac opens only an OUTBOUND connection
    browser + ChatGPT ─────────────▶ hosted identity provider  public, not the Mac; issues JWTs for Neuro's resource
    Neuro ──(outbound, safe_fetch)─▶ provider JWKS             to verify those JWTs

Neuro serves only the protected-resource metadata (through the tunnel) and verifies tokens: signature (asymmetric
only), issuer, audience = this resource, expiry, optional scope. WHO the token is decides nothing on its own: an
(issuer, subject) is mapped to a Neuro person only after that person redeems an owner-issued single-use invite
(`link_account`), so signing up at the provider grants nothing. Each linked identity is one ordinary credential —
revocation, ACL, disclosure, attribution and audit are unchanged. Nothing here names a vendor.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from . import access, db
from .access import AccessError
from .config import settings

JWKS_TTL_S = 3600
ALLOWED_ALGS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
LEEWAY_S = 30

_lock = threading.Lock()
_cache: dict[str, Any] = {"jwks_url": None, "keys": None, "fetched_at": 0.0}


def enabled() -> bool:
    return bool(settings.oauth_issuer)


def issuer() -> str:
    return (settings.oauth_issuer or "").rstrip("/")


def resource() -> str:
    from .oauth import MCP_PATH, base_url
    return settings.oauth_resource or (base_url() + MCP_PATH)


def audience() -> str:
    return settings.oauth_audience or resource()


def looks_like_jwt(tok: str | None) -> bool:
    return bool(tok) and tok.count(".") == 2 and not tok.startswith(("nsx_", "nsa_", "nsr_", "nsi_"))


def _get_json(url: str) -> dict[str, Any]:
    from . import safe_fetch
    res = safe_fetch.safe_fetch(url, content_class="html")
    return json.loads(res.body.decode("utf-8"))


def _jwks_url() -> str:
    if settings.oauth_jwks_url:
        return settings.oauth_jwks_url
    if _cache["jwks_url"]:
        return _cache["jwks_url"]
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
        try:
            meta = _get_json(issuer() + path)
        except Exception:  # noqa: BLE001
            continue
        if meta.get("jwks_uri") and meta.get("issuer", "").rstrip("/") == issuer():
            _cache["jwks_url"] = meta["jwks_uri"]
            return meta["jwks_uri"]
    raise AccessError("auth_invalid", "the identity provider's signing keys could not be discovered")


def _keys(force: bool = False) -> dict[str, Any]:
    with _lock:
        if not force and _cache["keys"] is not None and time.time() - _cache["fetched_at"] < JWKS_TTL_S:
            return _cache["keys"]
        if force and time.time() - _cache["fetched_at"] < 30:          # an unknown kid cannot make us hammer the provider
            return _cache["keys"] or {}
        import jwt
        doc = _get_json(_jwks_url())
        keys = {}
        for k in doc.get("keys") or []:
            try:
                keys[k.get("kid") or "_"] = jwt.PyJWK(k)
            except Exception:  # noqa: BLE001 — an unusable key is skipped, never trusted
                continue
        _cache.update(keys=keys, fetched_at=time.time())
        return keys


def verify(token: str) -> dict[str, Any]:
    """Resource-server checks on a provider-issued JWT. Raises AccessError('auth_invalid')."""
    import jwt
    if not enabled():
        raise AccessError("auth_invalid", "external identity provider not configured")
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise AccessError("auth_invalid", "malformed token")
    if header.get("alg") not in ALLOWED_ALGS:
        raise AccessError("auth_invalid", "token algorithm not accepted")
    kid = header.get("kid") or "_"
    keys = _keys()
    if kid not in keys:
        keys = _keys(force=True)
    key = keys.get(kid)
    if key is None:
        raise AccessError("auth_invalid", "token signed with an unknown key")
    try:
        claims = jwt.decode(token, key.key, algorithms=[header["alg"]], audience=audience(), issuer=issuer(),
                            leeway=LEEWAY_S, options={"require": ["exp", "iss", "aud", "sub"]})
    except jwt.ExpiredSignatureError:
        raise AccessError("auth_invalid", "token expired")
    except jwt.PyJWTError as e:
        raise AccessError("auth_invalid", f"token rejected: {type(e).__name__}")
    need = settings.oauth_required_scope
    if need:
        granted = set(str(claims.get("scope") or "").split()) | set(claims.get("scp") or [])
        if need not in granted:
            raise AccessError("auth_invalid", "token lacks the required scope")
    return claims


def credential_for(token: str) -> str:
    """A verified token → the credential its (issuer, subject) was linked to."""
    c = verify(token)
    r = db.connect().execute("SELECT credential_id FROM external_identities WHERE issuer=? AND subject=?", (issuer(), str(c["sub"]))).fetchone()
    if not r:
        raise AccessError("account_unlinked", "this sign-in is not linked to a Neuro person yet: ask the user for their Neuro "
                                              "connection code (nsi_…) and call link_account with it")
    return r["credential_id"]


def link(token: str, invite_code: str, client_name: str | None = None) -> dict[str, Any]:
    """Redeem an owner-issued invite for the (issuer, subject) this token proves. Single-use; idempotent for the same
    identity (a second call returns the existing link and does not spend another invite)."""
    from . import oauth
    c = verify(token)
    sub = str(c["sub"])
    existing = db.connect().execute("SELECT credential_id FROM external_identities WHERE issuer=? AND subject=?", (issuer(), sub)).fetchone()
    if existing:
        p = access.authenticate_credential_id(existing["credential_id"])
        return {"linked": True, "person": p.actor_name, "already_linked": True}
    oauth._throttle(f"link:{sub}")
    code = (invite_code or "").strip()
    r = db.connect().execute("SELECT * FROM external_invites WHERE code_prefix=?", (code[:12],)).fetchone()
    t = time.time()
    import secrets as _s
    if not r or not _s.compare_digest(r["code_hash"], oauth._h(code)) or r["revoked_at"] is not None or r["used_at"] is not None or r["expires_at"] <= t:
        raise AccessError("auth_invalid", "that connection code is not valid (wrong, expired, or already used)")
    actor = access.get_actor(r["actor_id"])
    if not actor or actor["disabled_at"] is not None:
        raise AccessError("auth_revoked", "this person's access is disabled")
    ext_client = access.create_client(f"{actor['name']}'s {client_name or 'AI client'}", transport="tunnel")
    cred, _never_stored = access.issue_credential(actor["id"], ext_client["id"], created_by=f"invite:{r['id']}")
    with db.tx() as conn:
        if conn.execute("UPDATE external_invites SET used_at=?, used_client_id=? WHERE id=? AND used_at IS NULL", (t, ext_client["id"], r["id"])).rowcount != 1:
            raise AccessError("auth_invalid", "that connection code was just used")
        conn.execute("INSERT INTO external_identities (issuer, subject, credential_id, invite_id, linked_at) VALUES (?,?,?,?,?)",
                     (issuer(), sub, cred["id"], r["id"], t))
    return {"linked": True, "person": actor["name"], "client": ext_client["label"]}


def protected_resource_metadata() -> dict[str, Any]:
    from .oauth import SCOPE
    return {"resource": resource(), "authorization_servers": [issuer()],
            "scopes_supported": [settings.oauth_required_scope or SCOPE] if settings.oauth_required_scope else [],
            "bearer_methods_supported": ["header"], "resource_name": "Neuro"}
