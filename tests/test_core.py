"""Offline tests: parsing, chunking, storage, search, projects, import API, MCP auth.
Run: pytest -q
"""
from __future__ import annotations

import os
import tempfile

os.environ["NEUROSEARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="ns_test_")
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurosearch import chunking, db, ingest, media  # noqa: E402
from neurosearch.api import app  # noqa: E402

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_parse_json3_skips_append_events():
    raw = '{"events":[{"tStartMs":0,"dDurationMs":2000,"segs":[{"utf8":"hello "},{"utf8":"world"}]},' \
          '{"tStartMs":1000,"aAppend":1,"segs":[{"utf8":"\\n"}]},{"tStartMs":2000,"dDurationMs":3000,"segs":[{"utf8":"second"}]}]}'
    segs = media.parse_json3(raw)
    assert segs == [{"start": 0.0, "end": 2.0, "text": "hello world"}, {"start": 2.0, "end": 5.0, "text": "second"}]


def test_parse_vtt():
    raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHi <c>there</c>\n\n00:00:03.500 --> 00:00:05.000\nHi there\n\n00:01:00.000 --> 00:01:02.000\nnext\n"
    segs = media.parse_vtt(raw)
    assert segs[0]["text"] == "Hi there" and segs[0]["end"] == 5.0 and segs[1]["start"] == 60.0


def test_classify_url():
    assert media.classify_url("https://youtu.be/abc123def45") == "video"
    assert media.classify_url("https://www.youtube.com/watch?v=abc&list=PL1") == "video"
    assert media.classify_url("https://www.youtube.com/playlist?list=PL1") == "playlist"
    assert media.classify_url("https://www.youtube.com/@somebody") == "channel"
    assert media.classify_url("https://www.instagram.com/reel/XYZ/") == "instagram"
    assert media.classify_url("https://example.com/ep1.mp3") == "media"


def test_chunking_long_and_short():
    segs = [{"start": i * 3, "end": i * 3 + 3, "text": f"segment {i}"} for i in range(200)]
    chunks = chunking.build_chunks(segs, duration=600)
    assert 8 <= len(chunks) <= 14
    assert chunks[0]["start"] == 0 and chunks[1]["start"] < chunks[0]["end"]  # overlap
    assert len(chunking.build_chunks(segs[:20], duration=60)) == 1
    chap = chunking.build_chunks(segs, duration=600, chapters=[{"start_time": 0, "title": "Intro"}, {"start_time": 300, "title": "Main"}])
    assert chap[0]["text"].startswith("[Intro]") and any(c["text"].startswith("[Main]") for c in chap)
    assert chunking.fmt_ts(3723) == "1:02:03" and chunking.fmt_ts(65) == "1:05"


def test_manual_ingest_search_and_projects():
    db.init_db()
    r = ingest.ingest_text("Manual", "0:05 hello there\n0:40 talking about pricing objections\n[1:02:03] later on", tags=["sales"])
    assert r["segments"] == 3
    hits = db.fts_search("pricing objections")
    assert hits and db.get_chunks_by_ids([hits[0][0]])[hits[0][0]]["start"] == 40.0
    p = db.create_project("Sales", "objections", tags=["sales"])
    assert db.project_source_ids(p["id"]) == [r["source_id"]]
    assert db.find_project("sales")["id"] == p["id"]


def test_api_auth_and_import(client):
    assert client.get("/api/stats").status_code == 401
    assert client.get("/api/stats", headers=H).status_code == 200
    payload = {
        "platform": "youtube", "external_id": "abc123def45", "url": "https://www.youtube.com/watch?v=abc123def45",
        "title": "Imported video", "channel": "Chan", "duration": 120, "transcript_kind": "captions",
        "segments": [{"start": 0, "end": 4, "text": "we talk about churn"}, {"start": 4, "end": 9, "text": "and retention tactics"}],
        "chapters": [],
    }
    r = client.post("/api/import", headers=H, json={"payload": payload, "tags": ["x"],
                    "collection": {"kind": "playlist", "external_id": "PL1", "url": "u", "title": "My list"}})
    assert r.status_code == 200, r.text
    hits = client.get("/api/search", headers=H, params={"q": "retention"}).json()
    assert hits and hits[0]["link"].endswith("t=0s") and hits[0]["title"] == "Imported video"
    colls = client.get("/api/collections", headers=H).json()
    assert colls[0]["title"] == "My list" and colls[0]["n_sources"] == 1
    csv_text = client.get("/api/export/segments.csv", headers=H).text
    assert "Imported video" in csv_text and "churn" in csv_text
    # re-import is idempotent (same external id -> same source)
    client.post("/api/import", headers=H, json={"payload": payload})
    assert client.get("/api/stats", headers=H).json()["sources"] == 2


def test_mcp_path_token(client):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    assert client.post("/mcp/wrong", json=init, headers=hdr).status_code == 401
    assert client.post("/mcp/", json=init, headers=hdr).status_code == 401
    ok = client.post("/mcp/t0k", json=init, headers=hdr)
    assert ok.status_code == 200 and "Neuro Search" in ok.text
    ok2 = client.post("/mcp", json=init, headers={**hdr, **H})
    assert ok2.status_code == 200


def test_chat_url_ingest_and_exports(client, monkeypatch):
    p = client.post("/api/projects", headers=H, json={"name": "Chat proj", "brief": "test brief"}).json()
    # a message that is only links -> queued into the project, no Claude call needed
    r = client.post("/api/ask", headers=H, json={"question": "https://www.youtube.com/watch?v=zzzzzzzzzzz add this",
                                                 "project_id": p["id"]}).json()
    assert r["ingest_jobs"] and "Queued 1 link" in r["answer"]
    job = client.get("/api/jobs/" + r["ingest_jobs"][0]["job_id"], headers=H).json()
    assert job["payload"]["project_id"] == p["id"]
    # findings + masterplan package without synthesis
    client.post(f"/api/projects/{p['id']}/notes", headers=H, json={"content": "Finding one [1]", "citations": [
        {"n": 1, "title": "Imported video", "timestamp": "0:00", "link": "https://www.youtube.com/watch?v=abc123def45&t=0s"}]})
    md = client.get(f"/api/projects/{p['id']}/findings.md", headers=H).text
    assert "Finding one" in md and "watch?v=abc123def45&t=0s" in md
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/projects/{p['id']}/masterplan.zip?synthesize=false", headers=H).content))
    names = z.namelist()
    assert {"README.md", "masterplan.md", "findings.md", "sources.csv", "context.json", "conversations.md"} <= set(names)


def test_ask_tool_loop(monkeypatch):
    """Claude calls save_finding + update_brief, then answers; citations resolve and notes are stored."""
    import anthropic
    from neurosearch import qa
    monkeypatch.setattr(qa.settings, "anthropic_api_key", "fake")
    p = db.create_project("Loop", "old brief")
    src = db.find_source("youtube", "abc123def45")
    db.add_project_sources(p["id"], [src["id"]])

    class Blk:
        def __init__(self, **kw): self.__dict__.update(kw)
    calls = []

    class Msgs:
        def create(self, **kw):
            calls.append(kw)
            if len(calls) == 1:
                return Blk(stop_reason="tool_use", content=[
                    Blk(type="tool_use", id="t1", name="update_brief", input={"brief": "new brief about retention"}),
                    Blk(type="tool_use", id="t2", name="save_finding", input={"content": "They discuss retention tactics [1]."}),
                ])
            assert kw["messages"][-1]["role"] == "user" and kw["messages"][-1]["content"][0]["type"] == "tool_result"
            return Blk(stop_reason="end_turn", content=[Blk(type="text", text="Retention comes up early [1].", citations=None)])

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: Blk(messages=Msgs()))
    res = qa.ask("refocus on retention and pin what they say", project_id=p["id"], conversation_id="conv1")
    assert res["citations"] and res["citations"][0]["title"] == "Imported video"
    assert {a["type"] for a in res["actions"]} == {"brief_updated", "finding_saved"}
    assert db.get_project(p["id"])["brief"] == "new brief about retention"
    notes = db.list_project_notes(p["id"])
    assert notes and notes[0]["citations"][0]["link"].endswith("t=0s")
    assert "Pinned findings so far" in calls[0]["system"] and "update_brief" in [t["name"] for t in calls[0]["tools"]]


def test_document_upload_job(client):
    import time
    p = client.post("/api/projects", headers=H, json={"name": "Docs", "brief": None}).json()
    text = "Retention playbook.\n\nChurn drops when onboarding is personal.\n\n" + ("Filler paragraph about pricing anchors. " * 40 + "\n\n") * 6
    r = client.post("/api/ingest/file", headers=H, data={"project_id": p["id"]},
                    files={"file": ("playbook.txt", text.encode(), "text/plain")}).json()
    assert r["job"]
    for _ in range(50):
        j = client.get("/api/jobs/" + r["job"], headers=H).json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert j["status"] == "done", j
    srcs = client.get("/api/sources", headers=H, params={"project_id": p["id"]}).json()
    assert srcs and srcs[0]["platform"] == "document" and srcs[0]["title"] == "playbook.txt"
    hits = client.get("/api/search", headers=H, params={"q": "onboarding personal", "project_id": p["id"]}).json()
    assert hits and hits[0]["timestamp"].startswith("p. ")
    jobs_ = client.get(f"/api/projects/{p['id']}/jobs", headers=H).json()
    assert any(x["id"] == r["job"] for x in jobs_)
    # chats are isolated per project
    c = client.post("/api/conversations", headers=H, json={"project_id": p["id"], "title": "Idea A"}).json()
    client.put("/api/conversations/" + c["id"], headers=H, json={"title": "Idea A2"})
    convs = client.get("/api/conversations", headers=H, params={"project_id": p["id"]}).json()
    assert [x["title"] for x in convs] == ["Idea A2"]


def test_master_planner(client, monkeypatch):
    import anthropic
    from tests.fake_claude import Anthropic
    from neurosearch import planner
    monkeypatch.setattr(anthropic, "Anthropic", Anthropic)
    monkeypatch.setattr(planner.settings, "anthropic_api_key", "fake")
    p = client.post("/api/projects", headers=H, json={"name": "Site move", "brief": "Move site off Squarespace", "context": "Budget $500"}).json()
    client.post(f"/api/projects/{p['id']}/facts", headers=H, json={"kind": "constraint", "content": "budget under $500"})
    src = db.find_source("youtube", "abc123def45"); db.add_project_sources(p["id"], [src["id"]])
    client.post(f"/api/projects/{p['id']}/notes", headers=H, json={"content": "Cloudflare Pages is free [1]", "citations": [
        {"n": 1, "title": "Imported video", "timestamp": "0:00", "link": "https://www.youtube.com/watch?v=abc123def45&t=0s"}]})
    assert client.get(f"/api/projects/{p['id']}/plan", headers=H).json()["plan"] is None
    row = client.post(f"/api/projects/{p['id']}/plan/build", headers=H, json={}).json()
    assert row["version"] == 1 and row["plan"]["approach"]["recommended"].startswith("Static export")
    assert "U1" in row["plan"]["_evidence"] and row["plan"]["_evidence"]["U1"]["kind"] == "user"
    assert db.get_project(p["id"])["mode"] == "plan"
    # statuses + markdown/html
    client.put(f"/api/plans/{row['id']}/items/first_steps.0", headers=H, json={"status": "in_progress"})
    md = client.get(f"/api/projects/{p['id']}/plan.md", headers=H).text
    assert "## 3. First steps" in md and "`in progress`" in md and "watch?v=abc123def45" in md and "Beginner gotchas" in md
    html = client.get(f"/api/projects/{p['id']}/plan.html", headers=H).text
    assert "<table>" in html and "Ready to start" in html and "<script" not in html
    # research changed -> suggested updates -> accept -> apply (new version keeps statuses)
    client.post(f"/api/projects/{p['id']}/notes", headers=H, json={"content": "Cloudflare forms are limited", "citations": []})
    assert client.get(f"/api/projects/{p['id']}/plan", headers=H).json()["research_changed"] is True
    r = client.post(f"/api/projects/{p['id']}/plan/check-updates", headers=H).json()
    assert r["updates"] and r["plan"]["updates"][0]["status"] == "pending"
    uid = r["plan"]["updates"][0]["id"]
    client.post(f"/api/plan-updates/{uid}", headers=H, json={"status": "accepted"})
    row2 = client.post(f"/api/projects/{p['id']}/plan/apply", headers=H).json()
    assert row2["version"] == 2 and row2["items"]["first_steps.0"]["status"] == "in_progress"
    # start project
    started = client.post(f"/api/plans/{row2['id']}/start", headers=H).json()
    assert started["status"] == "started" and started["items"]["first_steps.1"]["status"] == "ready"
    assert db.get_project(p["id"])["mode"] == "execute"
    # masterplan zip now carries the plan
    import io, zipfile
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/api/projects/{p['id']}/masterplan.zip?synthesize=false", headers=H).content))
    assert "master_plan.md" in z.namelist() and "master_plan.html" in z.namelist()


def test_suggested_findings(client, monkeypatch):
    import anthropic, time
    from tests.fake_claude import Anthropic
    from neurosearch import findings, jobs
    monkeypatch.setattr(anthropic, "Anthropic", Anthropic)
    monkeypatch.setattr(findings.settings, "anthropic_api_key", "fake")
    monkeypatch.setattr(jobs.settings, "anthropic_api_key", "fake")
    p = client.post("/api/projects", headers=H, json={"name": "Suggest", "brief": "hosting"}).json()
    r = ingest.ingest_text("Hosting talk", "0:05 cloudflare pages is free for static sites\n3:40 never touch MX records", project_id=p["id"])
    # auto-queued suggestion job runs in the background worker
    for _ in range(60):
        pj = client.get(f"/api/projects/{p['id']}", headers=H).json()
        if pj["suggested"]:
            break
        time.sleep(0.2)
    assert len(pj["suggested"]) == 2 and pj["notes"] == []
    top = pj["suggested"][0]
    assert top["importance"] == 5 and top["citations"][0]["timestamp"] == "0:05" and top["status"] == "suggested"
    src = client.get(f"/api/sources/{r['source_id']}", headers=H).json()
    assert src["substance"] == 72 and "DNS" in src["summary"]
    # approve one, dismiss one -> only approved counts for exports/planner
    client.post(f"/api/notes/{top['id']}/status", headers=H, json={"status": "approved"})
    client.post(f"/api/notes/{pj['suggested'][1]['id']}/status", headers=H, json={"status": "dismissed"})
    pj = client.get(f"/api/projects/{p['id']}", headers=H).json()
    assert len(pj["notes"]) == 1 and pj["suggested"] == []
    md = client.get(f"/api/projects/{p['id']}/findings.md", headers=H).text
    assert "Cloudflare Pages is free" in md and "MX records" not in md
    # nothing left to analyse; force re-analyses
    assert client.post(f"/api/projects/{p['id']}/suggest", headers=H, json={}).json()["job"] is None
    assert client.post(f"/api/projects/{p['id']}/suggest", headers=H, json={"force": True}).json()["sources"] == 1


def test_project_onboarding(client):
    body = {"name": "Onboard", "goal": "site live on cheaper host", "brief": "which host", "context": "Budget: $500",
            "questions": ["Which hosts do practitioners recommend?", "What breaks during DNS moves?"],
            "facts": [{"kind": "constraint", "content": "Budget: $500"}, {"kind": "rejected", "content": "Wix"}],
            "urls": ["https://www.youtube.com/watch?v=aaaaaaaaaaa"], "audience": "me", "output_pref": "a recommendation",
            "source_prefs": "practitioners over marketers"}
    p = client.post("/api/projects", headers=H, json=body).json()
    assert p["goal"] == "site live on cheaper host" and p["questions"] == body["questions"] and len(p["jobs"]) == 1
    full = client.get(f"/api/projects/{p['id']}", headers=H).json()
    assert [c["title"] for c in full["conversations"]] == body["questions"][::-1] or len(full["conversations"]) == 2
    assert {f["kind"] for f in full["facts"]} == {"constraint", "rejected"}
    steering = db.project_steering(full)
    assert "Goal (what done looks like): site live" in steering and "practitioners" in steering and "Starting questions" in steering
    # settings round-trip keeps the new fields
    upd = client.put(f"/api/projects/{p['id']}", headers=H, json={"name": "Onboard", "goal": "g2", "questions": ["q3"]}).json()
    assert upd["goal"] == "g2" and upd["questions"] == ["q3"] and upd["audience"] == "me"
