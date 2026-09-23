"""P11 EA-3 — the structured external read service (EXTERNAL-AI-ACCESS-MISSION.md §39, §41–§42, §56–§58;
docs/P11-EXECUTION-PLAN-2026-09-22.md §3 and §10 rows 2 and 5).

The gate: no model call on any read; one bounded orientation call; every envelope field; cursor paging;
restricted material cannot leak through a Claim, finding, watch-out, plan implication, event or consult packet;
guessed ids are indistinguishable from nonexistent ones; REST and MCP are the same service."""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, chunking, claims, db, external, external_schemas, facts, knowledge, ledger
from neurosearch.config import settings

SECRET_WORDS = ("tax return", "instagram-only", "SECRET")


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    yield
    db._local.conn = None


@pytest.fixture
def world(client):
    """Kyle (owner, all classes) and Gio (contribute, standard) on one shared project; a private project of Kyle's."""
    p = db.create_project("Business acquisition", "buy an HVAC business")["id"]
    private = db.create_project("Kyle private")["id"]

    def source(platform, ext, text, **kw):
        sid = db.upsert_source(platform=platform, external_id=ext, url=f"https://www.youtube.com/watch?v={ext:0>11}"[:43],
                               title=f"{ext} title", channel=ext, status="ready", **kw)["id"]
        segs = [{"start": float(i * 30), "end": float(i * 30 + 30), "text": t} for i, t in enumerate(text)]
        db.replace_transcript(sid, segs, chunking.build_chunks(segs, duration=len(text) * 30))
        db.add_project_sources(p, [sid])
        return sid

    pub = source("youtube", "pub", ["Seller notes of ten percent are common in HVAC deals.",
                                    "Buyers negotiate transition periods of six to twelve months."])
    ig = source("instagram", "ig", ["instagram-only whisper: the seller note SECRET is really fifteen percent."])
    tax = source("youtube", "tax", ["tax return shows SECRET add-backs of 200k in HVAC seller note deals."])
    access.set_source_class(tax, "tax")
    c_pub = claims.add_claim(p, "Seller notes of ten percent are common in HVAC deals", origin="user", status="accepted")["id"]
    claims.add_evidence(c_pub, pub, locator="0:00", excerpt="Seller notes of ten percent are common")
    c_ig = claims.add_claim(p, "The seller note SECRET is really fifteen percent", origin="user", status="accepted")["id"]
    claims.add_evidence(c_ig, ig, excerpt="instagram-only whisper")
    knowledge._upsert_tension(p, "CONTRADICTION", c_ig, "SECRET contradiction from instagram-only material", {}, "high")
    knowledge.add_target(p, "What seller note do HVAC SECRET sellers accept?", claim_id=c_ig)
    facts.record(p, "decision", "Seller note stays at 10%", disclosure_class="standard")
    facts.record(p, "constraint", "tax return figures SECRET stay private", disclosure_class="tax")
    access.create_actor("Gio", actor_id="gio")
    c_gio, c_kyle = access.create_client("Gio's ChatGPT")["id"], access.create_client("Kyle's ChatGPT")["id"]
    _, s_gio = access.issue_credential("gio", c_gio)
    _, s_kyle = access.issue_credential("kyle", c_kyle)
    access.grant(p, "gio", "contribute")
    access.grant(p, "kyle", "owner", classes=list(external_schemas.DISCLOSURE_CLASSES))
    access.grant(private, "kyle", "owner")
    access._rate.clear()
    return {"p": p, "private": private, "gio": s_gio, "kyle": s_kyle, "pub": pub, "ig": ig, "tax": tax, "c_pub": c_pub, "c_ig": c_ig}


def ext(client, secret, op, **args):
    return client.post(f"/api/ext/v1/{op}", json=args, headers={"Authorization": f"Bearer {secret}"})


def _no_secrets(obj):
    s = json.dumps(obj)
    for w in SECRET_WORDS:
        assert w not in s, w


@pytest.fixture
def no_models(monkeypatch):
    from neurosearch import embeddings, providers, qa
    def boom(*a, **k):
        raise AssertionError("an external read called a model")
    for mod, name in ((providers, "invoke"), (providers, "invoke_structured"), (embeddings, "embed_query"), (qa, "ask")):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, boom)


def test_envelope_contract_and_orientation_in_one_call(client, world, no_models):
    r = ext(client, world["gio"], "open_project", project_id=world["p"],
            client_capabilities={"vision": True, "pdf_text": True, "ocr": True, "write_tools": True, "file_transport": ["none"]})
    assert r.status_code == 200, r.text
    env = r.json()
    external_schemas.check("external.envelope.v1", env)
    d = env["data"]
    assert d["project"]["name"] == "Business acquisition" and d["project"]["role"] == "contribute"
    assert [f["content"] for f in d["orientation"]["current_position"]] == ["Seller note stays at 10%"]
    assert d["orientation"]["counts"]["sources"] == 1 and d["orientation"]["counts"]["claims"] == {"accepted": 1}
    w = d["disclosure"]["withheld"]
    assert d["disclosure"]["classes"] == ["standard"] and w["sources"] == 2 and w["claims"] == 1 and w["facts"] == 1 and w["watchouts"] == 1
    assert d["capabilities"]["negotiated"]["pdf"] == "processed" and d["capabilities"]["negotiated"]["image"] == "processed"
    assert d["capabilities"]["server"]["models_called_on_read"] is False
    assert env["ledger_cursor"] > 0 and env["project_revision"]
    _no_secrets(env)
    assert access.get_client(access.authenticate(world["gio"]).client_id)["capabilities"]["vision"] is True


def test_owner_with_every_class_sees_everything(client, world, no_models):
    d = ext(client, world["kyle"], "open_project", project_id=world["p"]).json()["data"]
    assert d["orientation"]["counts"]["sources"] == 3 and all(v == 0 for v in d["disclosure"]["withheld"].values())
    assert {f["content"] for f in d["orientation"]["current_position"]} >= {"Seller note stays at 10%"}


def test_search_never_retrieves_restricted_text(client, world, no_models):
    d = ext(client, world["gio"], "search_project", project_id=world["p"], query="seller note HVAC SECRET percent").json()["data"]
    types = {h["hit_type"] for h in d["hits"]}
    assert "chunk" in types and "claim" in types
    assert all(h["source_id"] == world["pub"] for h in d["hits"] if h["hit_type"] == "chunk")
    assert all(h["claim_id"] == world["c_pub"] for h in d["hits"] if h["hit_type"] == "claim")
    _no_secrets(d["hits"])
    k = ext(client, world["kyle"], "search_project", project_id=world["p"], query="seller note SECRET").json()["data"]
    assert any(h.get("source_id") in (world["ig"], world["tax"]) for h in k["hits"] if h["hit_type"] == "chunk")


def test_evidence_drill_down_is_progressive_and_withheld_objects_do_not_exist(client, world, no_models):
    s = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref={"claim_id": world["c_pub"]}, depth="summary").json()["data"]
    assert "excerpt" not in s["evidence"][0] and "locator" not in s["evidence"][0]
    x = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref={"claim_id": world["c_pub"]}, depth="exact").json()["data"]
    assert x["evidence"][0]["locator"] == "0:00" and x["evidence"][0]["excerpt"]
    for ref in ({"claim_id": world["c_ig"]}, {"source_id": world["ig"]}, {"source_id": world["tax"]}, {"claim_id": "guessed"}):
        r = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref=ref, depth="exact")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", ref
    src = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref={"source_id": world["pub"], "start": 30}, depth="exact").json()["data"]
    assert src["passage"][0]["text"].startswith("Buyers negotiate")


def test_consult_packet_is_stored_state_and_leak_free(client, world, no_models):
    r = ext(client, world["gio"], "consult_project", project_id=world["p"], question="Should we stay at a 10% seller note?", since_cursor=0)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert [f["content"] for f in d["position"]] == ["Seller note stays at 10%"]
    assert [c["claim_id"] for c in d["research_state"]["claims"]] == [world["c_pub"]]
    assert d["research_state"]["watchouts"] == [] and d["withheld"]["claims"] == 1
    assert all(e["source_id"] == world["pub"] for e in d["evidence_available"])
    assert d["changed_since"]["summary"]["withheld"] >= 1
    _no_secrets(r.json())


def test_change_stream_through_the_service(client, world, no_models):
    first = ext(client, world["gio"], "get_project_changes", project_id=world["p"], since_cursor=0, limit=3).json()
    assert first["truncated"] is True and len(first["data"]["events"]) == 3
    seen, cur = [], 0
    while True:
        env = ext(client, world["gio"], "get_project_changes", project_id=world["p"], since_cursor=cur, limit=3).json()
        seen += [e["id"] for e in env["data"]["events"]]
        cur = env["next_cursor"]
        if not env["truncated"]:
            break
    assert len(seen) == len(set(seen))
    _no_secrets([ext(client, world["gio"], "get_project_changes", project_id=world["p"], since_cursor=0, limit=100).json()])
    assert cur == env["ledger_cursor"] or cur >= env["ledger_cursor"]


def test_plan_implications_are_withheld_when_the_plan_cites_restricted_findings(client, world, no_models):
    note = db.add_project_note(world["p"], "SECRET finding from instagram", [], source_id=world["ig"])["id"]
    db.save_plan(world["p"], {"goal": {"outcome": "buy"}, "approach": {"recommended": "SECRET approach", "evidence": ["F1"]},
                              "_evidence": {"F1": {"note_id": note}}}, {"notes": 1})
    g = ext(client, world["gio"], "open_project", project_id=world["p"]).json()["data"]
    assert g["orientation"]["plan"] is None and g["disclosure"]["withheld"]["plan"] == 1
    k = ext(client, world["kyle"], "open_project", project_id=world["p"]).json()["data"]
    assert k["orientation"]["plan"]["basis"] == "stored_plan_recommendation" and k["orientation"]["plan"]["version"] == 1


def test_isolation_idor_and_auth_codes(client, world):
    for pid in (world["private"], "does-not-exist"):
        r = ext(client, world["gio"], "open_project", project_id=pid)
        assert r.status_code == 404 and r.json()["error"]["code"] == "project_unauthorized"
    assert ext(client, "t0k", "list_projects").status_code == 401                          # the local token is not a credential here
    r = ext(client, None, "list_projects")
    assert r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer"
    names = [x["name"] for x in ext(client, world["gio"], "list_projects").json()["data"]]
    assert names == ["Business acquisition"]
    assert ext(client, world["gio"], "drop_tables", project_id=world["p"]).status_code == 422
    cred = access.authenticate(world["gio"]).credential_id
    access.revoke_credential(cred, reason="lost laptop")
    r = ext(client, world["gio"], "list_projects")
    assert r.status_code == 401 and r.json()["error"]["code"] == "auth_revoked"
    outcomes = {row["outcome"] for row in db.connect().execute("SELECT outcome FROM external_requests").fetchall()}
    assert {"ok", "project_unauthorized", "auth_invalid", "auth_revoked", "invalid"} <= outcomes
    assert world["gio"] not in json.dumps([dict(r) for r in db.connect().execute("SELECT * FROM external_requests").fetchall()])


def _mcp(client, secret, method, params=None, id_=1):
    r = client.post("/ext/mcp/", json={"jsonrpc": "2.0", "id": id_, "method": method, **({"params": params} if params else {})},
                    headers={"Authorization": f"Bearer {secret}", "Accept": "application/json, text/event-stream",
                             "MCP-Protocol-Version": "2025-06-18"})
    assert r.status_code == 200, r.text
    line = next(l for l in r.text.splitlines() if l.startswith("data: "))
    return json.loads(line[6:])


def test_mcp_adapter_is_the_same_service(client, world, no_models):
    assert client.post("/ext/mcp/", json={}).status_code == 401
    assert client.post("/ext/mcp/", json={}, headers={"Authorization": "Bearer t0k"}).status_code == 401
    init = _mcp(client, world["gio"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert "Reading is useful for orientation" in init["result"]["instructions"]   # descriptive wording since S83
    tools = {t["name"]: t for t in _mcp(client, world["gio"], "tools/list")["result"]["tools"]}
    assert {"list_projects", "open_project", "get_project_changes", "search_project", "get_evidence", "consult_project"} <= set(tools)
    assert tools["consult_project"]["annotations"]["readOnlyHint"] is True
    res = _mcp(client, world["gio"], "tools/call", {"name": "consult_project", "arguments": {"project_id": world["p"], "question": "seller note"}})
    env = json.loads(res["result"]["content"][0]["text"])
    external_schemas.check("external.envelope.v1", env)
    assert [f["content"] for f in env["data"]["position"]] == ["Seller note stays at 10%"]
    _no_secrets(env)
    bad = _mcp(client, world["gio"], "tools/call", {"name": "open_project", "arguments": {"project_id": world["private"]}})
    assert bad["result"]["isError"] is True and "project_unauthorized" in bad["result"]["content"][0]["text"]


def test_read_ops_do_not_write_project_state(client, world, no_models):
    before = ledger.cursor(world["p"])
    for op, a in (("open_project", {}), ("search_project", {"query": "seller"}), ("consult_project", {"question": "seller note"}),
                  ("get_project_changes", {"since_cursor": 0})):
        assert ext(client, world["gio"], op, project_id=world["p"], **a).status_code == 200
    assert ledger.cursor(world["p"]) == before
