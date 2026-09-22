"""P11 EA-7 — OAuth 2.1 for external AI clients, and file attachments by reference (plan §4, §8; mission §55, §62).

Re-verified 2026-09-22 against OpenAI's documentation: ChatGPT authenticates custom MCP servers only with OAuth 2.1
(CIMD or DCR, PKCE) or no auth, and passes uploaded files to tools as {download_url, file_id, mime_type, file_name}
via `_meta["openai/fileParams"]`. These tests hold Neuro's side of that contract without naming a vendor in the
domain: the person is bound by an owner-issued single-use invite; every token resolves to one revocable credential."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from urllib.parse import parse_qs, urlparse

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, db, oauth, safe_fetch
from neurosearch.config import settings

REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir(); (d / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    monkeypatch.setattr(settings, "public_url", "https://neuro.example.net")
    db._local.conn = None
    db.init_db()
    access._rate.clear(); oauth._attempts.clear()
    yield
    db._local.conn = None


def _pkce():
    v = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def _connect(client, invite_code, *, client_id=None, verifier=None, challenge=None):
    if client_id is None:
        client_id = client.post("/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT]}).json()["client_id"]
    if verifier is None:
        verifier, challenge = _pkce()
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "code_challenge": challenge,
         "code_challenge_method": "S256", "state": "st-123", "scope": "neuro", "resource": "https://neuro.example.net/ext/mcp"}
    page = client.get("/oauth/authorize", params=q)
    assert page.status_code == 200 and "to Neuro</h1>" in page.text and page.headers["x-frame-options"] == "DENY"
    r = client.post("/oauth/authorize", data={**q, "invite_code": invite_code}, follow_redirects=False)
    return client_id, verifier, q, r


def _gio_project():
    p = db.create_project("Business acquisition")["id"]
    access.create_actor("Gio", actor_id="gio")
    access.grant(p, "gio", "contribute")
    return p


def _mcp(client, token, method, params=None):
    r = client.post("/ext/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})},
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 200, r.text
    return json.loads(next(l for l in r.text.splitlines() if l.startswith("data: "))[6:])


def test_discovery_metadata_and_the_401_that_points_to_it(client):
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"] == "https://neuro.example.net/ext/mcp" and prm["authorization_servers"] == ["https://neuro.example.net"]
    assert client.get("/.well-known/oauth-protected-resource/ext/mcp").json() == prm
    asm = client.get("/.well-known/oauth-authorization-server").json()
    assert asm["code_challenge_methods_supported"] == ["S256"] and asm["client_id_metadata_document_supported"] is True
    assert asm["token_endpoint_auth_methods_supported"] == ["none"]
    r = client.post("/ext/mcp/", json={})
    assert r.status_code == 401
    assert 'resource_metadata="https://neuro.example.net/.well-known/oauth-protected-resource"' in r.headers["www-authenticate"]


def test_full_connection_flow_binds_the_person_and_works_over_mcp(client):
    p = _gio_project()
    inv, code = oauth.create_invite("gio", label="Gio's ChatGPT")
    cid, verifier, q, r = _connect(client, code)
    assert r.status_code == 303
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == REDIRECT
    qs = parse_qs(loc.query)
    assert qs["state"] == ["st-123"]
    bad = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": qs["code"][0], "redirect_uri": REDIRECT,
                                            "client_id": cid, "code_verifier": "wrong"})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": qs["code"][0], "redirect_uri": REDIRECT,
                                            "client_id": cid, "code_verifier": verifier}).json()
    assert tok["token_type"] == "Bearer" and tok["access_token"].startswith("nsa_") and tok["refresh_token"].startswith("nsr_")
    again = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": qs["code"][0], "redirect_uri": REDIRECT,
                                              "client_id": cid, "code_verifier": verifier})
    assert again.status_code == 400                                              # a code works once
    res = _mcp(client, tok["access_token"], "tools/call", {"name": "list_projects", "arguments": {}})
    env = json.loads(res["result"]["content"][0]["text"])
    assert [x["project_id"] for x in env["data"]] == [p]
    principal = access.authenticate(tok["access_token"])
    assert principal.actor_id == "gio" and principal.client_label == "Gio's ChatGPT"
    assert oauth.get_invite(inv["id"])["used_at"] is not None
    # the invite is single-use
    _, _, _, r2 = _connect(client, code)
    assert r2.status_code == 400 and "not valid" in r2.text


def test_refresh_rotates_and_revocation_ends_the_connection(client):
    _gio_project()
    _, code = oauth.create_invite("gio")
    cid, verifier, q, r = _connect(client, code)
    c = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    tok = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": c, "redirect_uri": REDIRECT, "client_id": cid, "code_verifier": verifier}).json()
    new = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid}).json()
    assert new["access_token"] != tok["access_token"]
    reuse = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid})
    assert reuse.status_code == 400
    cred = access.authenticate(new["access_token"]).credential_id
    access.revoke_credential(cred, reason="Gio left")
    with pytest.raises(access.AccessError) as e:
        access.authenticate(new["access_token"])
    assert e.value.code == "auth_revoked"
    dead = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": new["refresh_token"], "client_id": cid})
    assert dead.status_code == 400


def test_pkce_redirect_and_client_rules(client):
    _gio_project()
    cid = client.post("/oauth/register", json={"client_name": "ChatGPT", "redirect_uris": [REDIRECT]}).json()["client_id"]
    assert client.post("/oauth/register", json={"redirect_uris": ["http://evil.example.com/cb"]}).status_code == 400
    base = {"response_type": "code", "client_id": cid, "redirect_uri": REDIRECT, "code_challenge": "x", "code_challenge_method": "S256"}
    assert client.get("/oauth/authorize", params={**base, "code_challenge_method": "plain"}).status_code == 400
    assert client.get("/oauth/authorize", params={**base, "redirect_uri": "https://evil.example.com/cb"}).status_code == 400
    assert client.get("/oauth/authorize", params={**base, "client_id": "nope"}).status_code == 400
    oauth.create_invite("gio")
    for i in range(10):
        client.post("/oauth/authorize", data={**base, "invite_code": f"nsi_wrong{i:04d}"})
    r = client.post("/oauth/authorize", data={**base, "invite_code": "nsi_wrong9999"})
    assert r.status_code == 400 and "too many attempts" in r.text                 # guessing is throttled


def test_invites_are_owner_only_and_only_for_active_people(client):
    access.create_actor("Gio", actor_id="gio")
    assert client.post("/api/access/invites", json={"actor_id": "gio"}).status_code == 401
    r = client.post("/api/access/invites", json={"actor_id": "gio"}, headers={"Authorization": "Bearer t0k"}).json()
    assert r["code"].startswith("nsi_") and r["code"] not in json.dumps(client.get("/api/access/invites", headers={"Authorization": "Bearer t0k"}).json())
    with pytest.raises(access.AccessError):
        oauth.create_invite("system")
    access.set_actor_disabled("gio", True)
    with pytest.raises(access.AccessError):
        oauth.create_invite("gio")


def test_client_id_metadata_document_is_fetched_through_safe_fetch(client, monkeypatch):
    _gio_project()
    url = "https://client.example.org/oauth/client.json"
    doc = {"client_id": url, "client_name": "Some AI client", "redirect_uris": [REDIRECT]}
    seen = []
    def fake_fetch(u, content_class=None, **k):
        seen.append(u)
        return safe_fetch.FetchResult(url=u, status=200, content_type="application/json", body=json.dumps(doc).encode())
    monkeypatch.setattr(safe_fetch, "safe_fetch", fake_fetch)
    _, code = oauth.create_invite("gio")
    v, ch = _pkce()
    _, _, _, r = _connect(client, code, client_id=url, verifier=v, challenge=ch)
    assert r.status_code == 303 and seen == [url]
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda u, **k: safe_fetch.FetchResult(url=u, status=200, content_type="application/json",
                                                                                         body=json.dumps({**doc, "client_id": "https://other"}).encode()))
    assert oauth._cimd("https://client.example.org/other.json") is None            # a document must name itself


def test_uploaded_files_arrive_by_reference_and_processed_ones_are_not_reread(client, monkeypatch):
    p = _gio_project()
    c = access.create_client("Gio's ChatGPT")["id"]
    _, secret = access.issue_credential("gio", c)
    tools = {t["name"]: t for t in _mcp(client, secret, "tools/list")["result"]["tools"]}
    assert tools["attach_file"]["_meta"]["openai/fileParams"] == ["file"]
    fetched = []
    def fake_fetch(u, content_class=None, **k):
        fetched.append(u)
        return safe_fetch.FetchResult(url=u, status=200, content_type="image/png", body=b"\x89PNG bytes")
    monkeypatch.setattr(safe_fetch, "safe_fetch", fake_fetch)
    from neurosearch import ingest
    monkeypatch.setattr(ingest, "ingest_local_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-read a processed file")))
    iid = json.loads(_mcp(client, secret, "tools/call", {"name": "create_intake", "arguments": {"project_id": p, "client_request_id": "turn-file-1"}})
                     ["result"]["content"][0]["text"])["data"]["intake_id"]
    item = json.loads(_mcp(client, secret, "tools/call", {"name": "add_processed_material", "arguments": {"project_id": p, "intake_id": iid, "material": {
        "material_type": "image", "title": "Seller email", "producer": "Gio's ChatGPT", "extraction_method": "vision",
        "units": [{"text": "Another buyer is interested."}], "client_declared_class": "standard"}}})["result"]["content"][0]["text"])["data"]["item"]
    res = _mcp(client, secret, "tools/call", {"name": "attach_file", "arguments": {"project_id": p, "intake_id": iid, "item_id": item["item_id"],
               "file": {"download_url": "https://files.oaiusercontent.com/file-abc?sig=1", "file_id": "file-abc", "mime_type": "image/png", "file_name": "seller.png"}}})
    assert res["result"].get("isError") is not True, res
    from neurosearch import intake, jobs
    for r in db.connect().execute("SELECT ingest_job_id FROM intake_items WHERE intake_id=?", (iid,)).fetchall():
        j = db.get_job(r["ingest_job_id"])
        db.bump_job(j["id"]); claimed = db.claim_job((j["kind"],), worker_id="t"); jobs.execute(claimed, "t")
    st = intake.status(intake._row(iid))
    raw = next(i for i in st["items"] if i["kind"] == "raw_artifact")
    assert fetched == ["https://files.oaiusercontent.com/file-abc?sig=1"] and raw["status"] == "ready" and raw["sha256"]
