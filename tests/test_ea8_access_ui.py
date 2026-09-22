"""P11 EA-8 — the owner's Access / Inbox / Health surface (mission §8, §64; plan §9, §11).

External AI Health must never be one "connected / not connected" bit: each client reports its own state from the
audit log's outcome codes. The settings card is wired to real endpoints and declared handlers (the S44 static gates
cover the handler/ID rules; this checks the P11 card is actually present and loaded)."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, db
from neurosearch.config import settings

WEB = Path(__file__).resolve().parent.parent / "neurosearch" / "web"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    yield
    db._local.conn = None


def test_health_distinguishes_failure_kinds(client):
    H = {"Authorization": "Bearer t0k"}
    p = db.create_project("Shared")["id"]
    other = db.create_project("Private")["id"]
    access.create_actor("Gio", actor_id="gio")
    c1 = access.create_client("Gio's ChatGPT", transport="tunnel")["id"]
    c2 = access.create_client("Unused client")["id"]
    _, s = access.issue_credential("gio", c1)
    access.issue_credential("gio", c2)
    access.grant(p, "gio", "read")
    ext = lambda op, **a: client.post(f"/api/ext/v1/{op}", json=a, headers={"Authorization": f"Bearer {s}"})
    assert ext("open_project", project_id=p).status_code == 200
    assert ext("open_project", project_id=other).status_code == 404
    assert ext("sync_project_state", project_id=p, changes=[{"op": "record", "kind": "decision", "content": "x", "client_request_id": "h-000001"}]).status_code == 403
    by = {c["label"]: c for c in client.get("/api/access/client-health", headers=H).json()["clients"]}
    g = by["Gio's ChatGPT"]
    assert g["state"] == "forbidden" and g["last_success_at"] and g["requests_24h"] == 3 and g["refusals_24h"] == 2
    assert g["last_refusal"]["outcome"] == "forbidden" and g["transport"] == "tunnel" and g["people"] == ["gio"]
    assert by["Unused client"]["state"] == "never_used"
    for cred in access.list_credentials():
        if cred["client_id"] == c1:
            access.revoke_credential(cred["id"])
    assert {c["label"]: c for c in access.health()}["Gio's ChatGPT"]["state"] == "revoked"
    assert s not in str(client.get("/api/access/client-health", headers=H).json())


def test_settings_card_is_present_and_loaded():
    html = (WEB / "index.html").read_text()
    for el in ("p11People", "p11Name", "p11Role", "p11Msg", "p11Inbox"):
        assert f'id="{el}"' in html
    js = (WEB / "js" / "research.js").read_text()
    for fn in ("p11Load", "p11AddPerson", "p11SetRole", "p11SetClass", "p11Invite", "p11Remove", "p11Disconnect", "p11ShareFact"):
        assert f"globalThis.{fn} = " in js
    assert "p11Load()" in (WEB / "js" / "home.js").read_text()
    assert "/api/access/client-health" in js and "/inbox" in js
    assert "not evidence" in js                         # the assistant's reading is labelled, never presented as a source


def test_public_origin_serves_only_the_external_surface(client, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://neuro.example.net")
    pub = {"Host": "neuro.example.net"}
    for path in ("/", "/api/projects", "/api/access", "/mcp/", "/health", "/styles.css"):
        r = client.get(path, headers={**pub, "Authorization": "Bearer t0k"})
        assert r.status_code == 404, path                       # even the owner's token opens nothing here
    assert client.get("/.well-known/oauth-protected-resource", headers=pub).status_code == 200
    assert client.get("/.well-known/oauth-authorization-server", headers=pub).status_code == 200
    assert client.post("/ext/mcp/", json={}, headers=pub).status_code == 401
    assert client.post("/api/ext/v1/list_projects", json={}, headers=pub).status_code == 401
    via_proxy = client.get("/api/projects", headers={"Host": "127.0.0.1:8000", "X-Forwarded-Host": "neuro.example.net", "Authorization": "Bearer t0k"})
    assert via_proxy.status_code == 404
    assert client.get("/api/projects", headers={"Authorization": "Bearer t0k"}).status_code == 200     # local use unchanged
