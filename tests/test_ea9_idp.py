"""P11 EA-9 correction — Neuro as a private OAuth resource server for a hosted identity provider (idp.py).

Kyle, 2026-09-22: do not make Neuro public to solve OAuth. With NEUROSEARCH_OAUTH_ISSUER set, Neuro serves only its
protected-resource metadata (through the tunnel), verifies the provider's JWTs, and exposes NO authorization
endpoints. A provider sign-in grants nothing until the person redeems an owner-issued invite (link_account)."""
from __future__ import annotations

import json
import os
import time

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from neurosearch import access, db, idp, oauth
from neurosearch.config import settings

ISS = "https://neuro-idp.example.com"
RES = "https://tunnel.example/ext/mcp"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    monkeypatch.setattr(settings, "oauth_issuer", ISS)
    monkeypatch.setattr(settings, "oauth_resource", RES)
    monkeypatch.setattr(settings, "oauth_required_scope", None)
    db._local.conn = None
    db.init_db()
    access._rate.clear(); oauth._attempts.clear()
    idp._cache.update(jwks_url=None, keys=None, fetched_at=0.0)
    yield
    db._local.conn = None


@pytest.fixture
def keys(monkeypatch):
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(k.public_key()))
    jwk.update(kid="k1", alg="RS256", use="sig")
    fetched = []

    def get_json(url):
        fetched.append(url)
        if url.endswith("/.well-known/oauth-authorization-server"):
            return {"issuer": ISS, "jwks_uri": ISS + "/jwks.json"}
        if url == ISS + "/jwks.json":
            return {"keys": [jwk]}
        raise RuntimeError("unexpected fetch " + url)
    monkeypatch.setattr(idp, "_get_json", get_json)
    return k, fetched


def tok(key, sub="auth0|gio", **over):
    now = int(time.time())
    claims = {"iss": ISS, "aud": RES, "sub": sub, "iat": now, "exp": now + 600, "scope": "openid neuro", **over}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": over.pop("_kid", "k1")})


def _mcp(client, token, name, args=None, method="tools/call"):
    params = {"name": name, "arguments": args or {}} if method == "tools/call" else None
    r = client.post("/ext/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})},
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
    return r, (json.loads(next(l for l in r.text.splitlines() if l.startswith("data: "))[6:]) if r.status_code == 200 else None)


def test_neuro_serves_no_authorization_endpoints_only_resource_metadata(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["authorization_servers"] == [ISS] and prm["resource"] == RES
    for method, path in (("get", "/.well-known/oauth-authorization-server"), ("get", "/oauth/authorize"),
                         ("post", "/oauth/token"), ("post", "/oauth/register"), ("post", "/oauth/revoke")):
        assert getattr(client, method)(path).status_code == 404, path


def test_signing_in_grants_nothing_until_an_invite_is_redeemed(client, keys):
    key, fetched = keys
    p = db.create_project("Business acquisition")["id"]
    access.create_actor("Gio", actor_id="gio")
    access.grant(p, "gio", "contribute")
    t = tok(key)
    r, body = _mcp(client, t, "list_projects")
    assert r.status_code == 200 and body["result"]["isError"] is True and "account_unlinked" in body["result"]["content"][0]["text"]
    # 2026-09-22: the message points at owner approval, NOT at a code. ChatGPT's credential-safety layer blocks an
    # nsi_ code in chat before link_account is sent, so telling the user to paste one is advice they cannot follow
    # (S82). link_account itself is unchanged and still works for clients that can carry a code — proved below.
    assert "approve this sign-in" in body["result"]["content"][0]["text"]
    assert "nsi_" not in body["result"]["content"][0]["text"]
    _, bad = _mcp(client, t, "link_account", {"code": "nsi_notarealcode"})
    assert bad["result"]["isError"] is True
    inv, code = oauth.create_invite("gio")
    _, ok = _mcp(client, t, "link_account", {"code": code, "client_name": "ChatGPT"})
    out = json.loads(ok["result"]["content"][0]["text"])["data"]
    assert out["linked"] and out["person"] == "Gio" and out["client"] == "Gio's ChatGPT"
    _, again = _mcp(client, t, "link_account", {"code": code})
    assert json.loads(again["result"]["content"][0]["text"])["data"]["already_linked"] is True
    _, lp = _mcp(client, t, "list_projects")
    assert [x["project_id"] for x in json.loads(lp["result"]["content"][0]["text"])["data"]] == [p]
    pr = access.authenticate(t)
    assert pr.actor_id == "gio" and access.get_client(pr.client_id)["transport"] == "tunnel"
    # a different person signing in at the same provider cannot ride Gio's code
    _, other = _mcp(client, tok(key, sub="auth0|stranger"), "link_account", {"code": code})
    assert other["result"]["isError"] is True
    # keys fetched once, discovered from the issuer's own metadata, through the one fetch path
    assert fetched == [ISS + "/.well-known/oauth-authorization-server", ISS + "/jwks.json"]


def test_resource_server_checks(client, keys, monkeypatch):
    key, _ = keys
    access.create_actor("Gio", actor_id="gio")
    _, code = oauth.create_invite("gio")
    idp.link(tok(key), code)
    assert access.authenticate(tok(key)).actor_id == "gio"
    bad = {
        "wrong audience": tok(key, aud="https://someone-else/mcp"),
        "wrong issuer": tok(key, iss="https://evil.example.com"),
        "expired": tok(key, exp=int(time.time()) - 3600),
        "no subject": jwt.encode({"iss": ISS, "aud": RES, "exp": int(time.time()) + 600}, key, algorithm="RS256", headers={"kid": "k1"}),
        "symmetric alg": jwt.encode({"iss": ISS, "aud": RES, "sub": "auth0|gio", "exp": int(time.time()) + 600}, "shared-secret-" * 4, algorithm="HS256", headers={"kid": "k1"}),
        "unknown key": jwt.encode({"iss": ISS, "aud": RES, "sub": "auth0|gio", "exp": int(time.time()) + 600},
                                  rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256", headers={"kid": "k2"}),
        "forged with another key under the same kid": tok(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    }
    for why, t in bad.items():
        with pytest.raises(access.AccessError) as e:
            access.authenticate(t)
        assert e.value.code == "auth_invalid", why
    monkeypatch.setattr(settings, "oauth_required_scope", "neuro:read")
    with pytest.raises(access.AccessError):
        access.authenticate(tok(key))
    assert access.authenticate(tok(key, scope="openid neuro:read")).actor_id == "gio"


def test_revocation_and_builtin_tokens_in_resource_server_mode(client, keys):
    key, _ = keys
    access.create_actor("Gio", actor_id="gio")
    _, code = oauth.create_invite("gio")
    idp.link(tok(key), code)
    cred = access.authenticate(tok(key)).credential_id
    access.revoke_credential(cred, reason="Gio left the deal")
    with pytest.raises(access.AccessError) as e:
        access.authenticate(tok(key))
    assert e.value.code == "auth_revoked"
    with pytest.raises(access.AccessError):
        access.authenticate("nsa_" + "x" * 40)            # the built-in server's tokens are not accepted in this mode


def test_jwts_are_refused_at_the_gate_when_no_provider_is_configured(client, keys, monkeypatch):
    key, _ = keys
    monkeypatch.setattr(settings, "oauth_issuer", None)
    r, _ = _mcp(client, tok(key), "list_projects")
    assert r.status_code == 401


def test_two_tunnels_two_audiences_accepted_anything_else_refused(keys, monkeypatch):
    """2026-09-23: OpenAI refused to associate Kyle's tunnel with Gio's personal account without a manual review, so
    Gio's ChatGPT reaches Neuro through her own tunnel. Each tunnel's tokens carry that tunnel's URL as `aud`; a
    comma-separated NEUROSEARCH_OAUTH_AUDIENCE accepts exactly those."""
    k, _ = keys
    kyle_t, gio_t = "https://tunnel-service.example/v1/mcp/tunnel_kyle", "https://tunnel-service.example/v1/mcp/tunnel_gio"
    monkeypatch.setattr(settings, "oauth_audience", f"{kyle_t}, {gio_t}")
    assert idp.audience() == [kyle_t, gio_t]
    assert idp.verify(tok(k, aud=kyle_t))["sub"] == "auth0|gio"
    assert idp.verify(tok(k, aud=gio_t))["sub"] == "auth0|gio"
    with pytest.raises(Exception):
        idp.verify(tok(k, aud="https://tunnel-service.example/v1/mcp/tunnel_someone_else"))
    monkeypatch.setattr(settings, "oauth_audience", kyle_t)
    assert idp.audience() == kyle_t
