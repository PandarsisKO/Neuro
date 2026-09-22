"""P11 EA-9 — Neuro brought in late: conversation catch-up sync and late project binding (Kyle, 2026-09-22).

Server halves of acceptance scenarios EA-9B…9F. The live halves (does a natural "save this to Neuro" invoke the app;
does ChatGPT build a clean handoff) are Kyle's ChatGPT acceptance; these hold what Neuro must do with the handoff."""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, convsync, db, facts, jobs, ledger, safe_fetch
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir(); (d / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    monkeypatch.setattr(jobs, "enqueue_suggestions", lambda *a, **k: None)
    yield
    db._local.conn = None


@pytest.fixture
def kyle(client):
    """Kyle's own ChatGPT is the first acceptance client (EA-9A): Kyle grants himself the projects he tests on."""
    acq = db.create_project("Business Acquisition", "buy an HVAC business; seller note, SBA loan, transition")["id"]
    acct = db.create_project("Accounting firm purchase", "buy a small CPA practice; client retention, seller note")["id"]
    secret_p = db.create_project("Personal taxes")["id"]
    c = access.create_client("Kyle's ChatGPT", transport="tunnel")["id"]
    _, s = access.issue_credential("kyle", c)
    access.grant(acq, "kyle", "contribute", classes=["standard", "correspondence", "financial"])
    access.grant(acct, "kyle", "contribute")
    return {"s": s, "acq": acq, "acct": acct, "private": secret_p, "client": c}


def sync(client, s, **args):
    r = client.post("/api/ext/v1/sync_conversation_to_project", json=args, headers={"Authorization": f"Bearer {s}"})
    return r.status_code, r.json()


FREEFLOW_STATE = [
    {"op": "record", "kind": "decision", "content": "Offer a 10% seller note", "rationale": "keeps the seller invested through transition"},
    {"op": "record", "kind": "constraint", "content": "Total debt service must stay under 1.25x DSCR"},
    {"op": "record", "kind": "counterpart_position", "content": "Seller wants a 5% note and a 6-month transition"},
    {"op": "record", "kind": "deadline", "content": "LOI response due Friday"},
    {"op": "record", "kind": "open_question", "content": "Will the SBA lender accept a standby seller note?"},
    {"op": "propose", "kind": "concern", "content": "Seller may walk if pushed on transition length"},
    {"op": "record", "kind": "context", "content": "Make it shorter"},
    {"op": "record", "kind": "context", "content": "use a warmer tone"},
]


def test_9b_late_binding_nothing_is_written_until_the_project_is_known(client, kyle):
    code, env = sync(client, kyle["s"], client_request_id="save-000001", state=FREEFLOW_STATE)
    assert code == 200 and env["data"]["status"] == "needs_project" and env["data"]["saved"] is False
    names = [c["name"] for c in env["data"]["candidates"]]
    assert set(names) == {"Business Acquisition", "Accounting firm purchase"} and "Personal taxes" not in names
    assert db.connect().execute("SELECT COUNT(*) FROM project_facts").fetchone()[0] == 0
    assert db.connect().execute("SELECT COUNT(*) FROM external_intakes").fetchone()[0] == 0
    # the user names the project → resolved and saved, no transcript, chatter dropped, inferred stays a suggestion
    code, env = sync(client, kyle["s"], client_request_id="save-000001", project_hint="the business acquisition project",
                     state=FREEFLOW_STATE)
    d = env["data"]
    assert code == 200 and d["saved"] and d["project"]["name"] == "Business Acquisition"
    assert d["summary"] == ("Saved to Business Acquisition: 1 decision, 1 constraint, 1 counterpart position, 1 deadline, "
                            "1 open question, 1 suggestion to review")
    assert d["skipped"] == {"presentation": 2, "already_known": 0} and d["needs_attention"] == []
    pos = {f["kind"]: f["content"] for f in facts.current_position(kyle["acq"])}
    assert pos["decision"] == "Offer a 10% seller note" and "concern" not in pos
    assert not any("shorter" in f["content"].lower() or "tone" in f["content"].lower()
                   for f in db.list_facts(kyle["acq"], include_history=True))
    ev = [e for e in ledger.events(kyle["acq"])["events"] if e["object_type"] == "fact"]
    assert {e["actor_id"] for e in ev} == {"kyle"} and {e["external_client_id"] for e in ev} == {kyle["client"]}


def test_9f_ambiguous_project_is_asked_never_guessed(client, kyle):
    code, env = sync(client, kyle["s"], client_request_id="save-000002", project_hint="the seller note deal",
                     state=[{"op": "record", "kind": "decision", "content": "Hold at 10%"}])
    d = env["data"]
    assert d["status"] == "needs_project" and {c["name"] for c in d["candidates"]} == {"Business Acquisition", "Accounting firm purchase"}
    assert db.connect().execute("SELECT COUNT(*) FROM project_facts").fetchone()[0] == 0
    ranked = client.post("/api/ext/v1/list_projects", json={"query": "HVAC"}, headers={"Authorization": f"Bearer {kyle['s']}"}).json()["data"]
    assert ranked[0]["name"] == "Business Acquisition" and "Personal taxes" not in [r["name"] for r in ranked]
    code, _ = sync(client, kyle["s"], client_request_id="save-000003", project_id=kyle["private"],
                   state=[{"op": "record", "kind": "decision", "content": "x"}])
    assert code == 404                                            # an unpermitted project does not exist here


def test_9d_decision_only_and_repeated_saves_do_not_duplicate(client, kyle):
    st = [{"op": "record", "kind": "decision", "content": "Stay at 10%", "rationale": "frame it around the transition"},
          {"op": "record", "kind": "context", "content": "Rewrite it"}, {"op": "record", "kind": "context", "content": "give me 3 versions"}]
    _, env = sync(client, kyle["s"], client_request_id="save-000004", project_id=kyle["acq"], state=st)
    assert env["data"]["summary"] == "Saved to Business Acquisition: 1 decision" and env["data"]["skipped"]["presentation"] == 2
    _, again = sync(client, kyle["s"], client_request_id="save-000004", project_id=kyle["acq"], state=st)
    assert again["data"]["idempotent_replay"] and again["data"]["summary"] == env["data"]["summary"]
    _, later = sync(client, kyle["s"], client_request_id="save-000005", project_id=kyle["acq"], state=[
        {"op": "record", "kind": "decision", "content": "stay at 10%."},
        {"op": "reaffirm", "fact_id": env["data"]["facts"][0]["fact_id"], "rationale": "seller pushed again"}])
    assert later["data"]["skipped"]["already_known"] == 1 and later["data"]["counts"]["decision"] == 1
    assert len([f for f in facts.current_position(kyle["acq"]) if f["kind"] == "decision"]) == 1
    types = [e["event_type"] for e in ledger.events(kyle["acq"])["events"]]
    assert types.count("decision_recorded") == 1 and types.count("decision_reaffirmed") == 1


def test_9e_prior_attachments_by_reference_or_as_extraction_only(client, kyle, monkeypatch):
    fetched = []
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda u, **k: (fetched.append(u), safe_fetch.FetchResult(
        url=u, status=200, content_type="application/pdf", body=b"%PDF fake"))[1])
    from neurosearch import ingest
    monkeypatch.setattr(ingest, "ingest_local_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-read a processed file")))
    pdf = {"material_type": "pdf", "title": "Seller P&L 2025", "producer": "Kyle's ChatGPT", "extraction_method": "pdf_text",
           "client_declared_class": "financial", "units": [{"locator": "p. 1", "text": "SDE $310k"}]}
    shot = {"material_type": "image", "title": "Broker text", "producer": "Kyle's ChatGPT", "extraction_method": "vision",
            "original_available": False, "units": [{"text": "Seller has another offer"}]}
    _, env = sync(client, kyle["s"], client_request_id="save-000006", project_id=kyle["acq"], materials=[pdf, shot],
                  files=[{"artifact_ref": {"kind": "signed_url", "url": "https://files.example/p&l.pdf?sig=1", "filename": "pl.pdf"},
                          "original_of_material": 0}],
                  analysis=[{"text": "The other offer is probably leverage."}])
    d = env["data"]
    assert d["counts"]["materials"] == 2 and d["counts"]["files"] == 1 and d["counts"]["analysis"] == 1
    iid = d["intake_id"]
    for r in db.connect().execute("SELECT ingest_job_id FROM intake_items WHERE intake_id=? AND ingest_job_id IS NOT NULL", (iid,)).fetchall():
        j = db.get_job(r["ingest_job_id"]); db.bump_job(j["id"]); jobs.execute(db.claim_job((j["kind"],), worker_id="t"), "t")
    from neurosearch import intake
    st = intake.status(intake._row(iid))
    assert st["status"] == "ready" and fetched == ["https://files.example/p&l.pdf?sig=1"]
    kinds = sorted(i["kind"] for i in st["items"])
    assert kinds == ["interpretation", "processed_material", "processed_material", "raw_artifact"]
    rows = {r["title"]: dict(r) for r in db.connect().execute("SELECT * FROM sources").fetchall()}
    assert rows["Seller P&L 2025"]["disclosure_class"] == "financial" and "Broker text" in rows
    assert not any("leverage" in t for t in rows)                      # analysis is never a source
    item = json.loads(db.connect().execute("SELECT payload FROM intake_items WHERE intake_id=? AND material_type='image'", (iid,)).fetchone()[0])
    assert item["material"]["original_available"] is False


def test_9c_catch_up_then_read(client, kyle):
    facts.record(kyle["acq"], "constraint", "SBA requires a 10% equity injection", disclosure_class="standard")
    _, env = sync(client, kyle["s"], client_request_id="save-000007", project_id=kyle["acq"], state=[
        {"op": "record", "kind": "counterpart_position", "content": "Seller now asks for a 5% seller note"}])
    assert "consult_project" in env["data"]["next"]
    c = client.post("/api/ext/v1/consult_project", json={"project_id": kyle["acq"], "question": "Should we accept a 5% seller note?",
                                                          "since_cursor": 0}, headers={"Authorization": f"Bearer {kyle['s']}"}).json()["data"]
    contents = [f["content"] for f in c["constraints"] + c["position"]]
    assert "SBA requires a 10% equity injection" in contents                               # what Neuro already knew
    assert any(e["after"] and "5% seller note" in json.dumps(e["after"]) for e in c["changed_since"]["events"])  # what was just caught up


def test_transcript_archive_only_on_explicit_request_and_read_only_cannot_sync(client, kyle):
    code, env = sync(client, kyle["s"], client_request_id="save-000008", project_id=kyle["acq"],
                     archive_transcript={"text": "the whole chat", "explicit_user_request": False})
    assert code == 422
    _, ok = sync(client, kyle["s"], client_request_id="save-000009", project_id=kyle["acq"],
                 archive_transcript={"text": "User: hi\nAssistant: hello", "explicit_user_request": True})
    assert ok["data"]["saved"]
    access.grant(kyle["acq"], "kyle", "read")
    code, env = sync(client, kyle["s"], client_request_id="save-000010", project_id=kyle["acq"], state=[{"op": "record", "kind": "decision", "content": "y"}])
    assert code == 403


def test_chatter_backstop_is_narrow():
    for t in ("Make it shorter", "try again", "use a warmer tone", "Give me 3 versions", "rephrase"):
        assert convsync.is_chatter(t), t
    for t in ("Make the transition shorter than six months", "We will try again with the SBA lender in March",
              "Offer a 10% seller note", "Rewrite the LOI to cap the earnout at 12 months and remove the non-compete carve-out"):
        assert not convsync.is_chatter(t), t


def test_mcp_tool_takes_files_by_reference_and_carries_the_freeflow_instructions(client, kyle):
    def mcp(method, params=None):
        r = client.post("/ext/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})},
                        headers={"Authorization": f"Bearer {kyle['s']}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"})
        return json.loads(next(l for l in r.text.splitlines() if l.startswith("data: "))[6:])
    init = mcp("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
    assert "does NOT need to be involved from the start" in init["result"]["instructions"]
    tools = {t["name"]: t for t in mcp("tools/list")["result"]["tools"]}
    assert tools["sync_conversation_to_project"]["_meta"]["openai/fileParams"] == ["files"]
    res = mcp("tools/call", {"name": "sync_conversation_to_project", "arguments": {"client_request_id": "mcp-save-01", "project_hint": "Business Acquisition",
              "state": [{"op": "record", "kind": "decision", "content": "Offer 10%"}]}})
    assert json.loads(res["result"]["content"][0]["text"])["data"]["summary"] == "Saved to Business Acquisition: 1 decision"
