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
    assert "Cloudflare Pages: free static hosting" in md and "MX records" not in md
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


def test_discover_sources(client, monkeypatch):
    import anthropic
    from tests.fake_claude import Anthropic
    from neurosearch import discover
    monkeypatch.setattr(anthropic, "Anthropic", Anthropic)
    monkeypatch.setattr(discover.settings, "anthropic_api_key", "fake")
    p = client.post("/api/projects", headers=H, json={"name": "Money", "brief": "get out of debt and start investing"}).json()
    r = client.post(f"/api/projects/{p['id']}/discover", headers=H, json={}).json()
    assert r["added"] == 3 and r["verified"] == 1 and r["extra"] == 1 and r["items"][0]["name"] == "Dave Ramsey"
    ds = client.get(f"/api/projects/{p['id']}/discoveries", headers=H).json()
    ramsey = [d for d in ds if d["name"] == "Dave Ramsey"][0]
    assert ramsey["start_with"][0]["title"] == "Baby Steps"        # verification pass patched the starting video
    # second run doesn't duplicate
    r2 = client.post(f"/api/projects/{p['id']}/discover", headers=H, json={"refine": "more contrarian"}).json()
    assert r2["added"] == 0
    ds = client.get(f"/api/projects/{p['id']}/discoveries", headers=H).json()
    assert len(ds) == 3 and ds[0]["fit"] == 5
    client.post(f"/api/discoveries/{ds[1]['id']}/status", headers=H, json={"status": "dismissed"})
    sts = [d["status"] for d in client.get(f"/api/projects/{p['id']}/discoveries", headers=H).json()]
    assert sts.count("dismissed") == 1 and sts.count("new") == 2


def test_course_import(client):
    from neurosearch.courses import normalise_embed, write_cookie_file
    assert normalise_embed("https://www.loom.com/embed/abc123DEF?sid=1") == "https://www.loom.com/share/abc123DEF"
    assert normalise_embed("https://player.vimeo.com/video/12345?h=zz9") == "https://vimeo.com/12345/zz9"
    assert normalise_embed("https://www.youtube-nocookie.com/embed/abc123def45?rel=0") == "https://www.youtube.com/watch?v=abc123def45"
    p = client.post("/api/projects", headers=H, json={"name": "Course", "brief": "the course"}).json()
    r = client.post(f"/api/projects/{p['id']}/course-import", headers=H, json={
        "course": {"title": "Sales Mastery", "url": "https://school.example.com/courses/sales"},
        "lessons": [
            {"title": "Welcome", "module": "Module 1", "page_url": "https://school.example.com/lessons/1", "video_urls": ["https://www.loom.com/embed/xyz789"]},
            {"title": "Text only", "module": "Module 1", "page_url": "https://school.example.com/lessons/2", "video_urls": []},
        ],
        "cookies": [{"domain": ".example.com", "name": "session", "value": "s3cr3t", "path": "/", "secure": True, "expirationDate": 1900000000}]}).json()
    assert r["queued"] == 1 and r["no_video"] == ["Text only"] and r["cookies"] is True
    jobs_ = client.get(f"/api/projects/{p['id']}/jobs", headers=H).json()
    j = next(x for x in jobs_ if x["kind"] == "ingest_url")
    assert j["payload"]["title"] == "Module 1 › Welcome" and j["payload"]["referer"].endswith("/lessons/1")
    assert open(j["payload"]["cookies_file"]).read().count("s3cr3t") == 1
    cs = client.get("/api/collections", headers=H).json()
    assert any(c["kind"] == "course" and c["title"] == "Sales Mastery" for c in cs)
    assert client.get("/extension.zip", headers=H).status_code == 200


def test_rate_limit_backoff(monkeypatch):
    from neurosearch import media
    monkeypatch.setattr(media.settings, "yt_delay", 0.0)
    monkeypatch.setattr(media.settings, "yt_backoff_minutes", 1)
    media._yt_paused_until = 0.0
    db.init_db()
    # a bot-check error inside a polite() block converts to RateLimited and starts the pause
    with pytest.raises(media.RateLimited):
        with media.polite("https://www.youtube.com/watch?v=abc123def45"):
            raise Exception("ERROR: Sign in to confirm you’re not a bot")
    assert media.rate_limit_status()["paused"] is True
    # while paused, further youtube fetches are refused immediately; non-youtube is unaffected
    with pytest.raises(media.RateLimited):
        with media.polite("https://www.youtube.com/watch?v=zzz"):
            pass
    with media.polite("https://www.loom.com/share/x"):
        pass
    media._yt_paused_until = 0.0
    # job requeue with not_before is skipped by claim_job until due
    j = db.create_job("reembed", {})
    db.requeue_job(j["id"], delay=3600, message="paused")
    row = db.get_job(j["id"])
    assert row["status"] == "queued" and row["not_before"] > db.now() + 3000 and row["message"] == "paused"
    claimed = set()
    while (c := db.claim_job()):
        claimed.add(c["id"]); db.update_job(c["id"], status="done")
    assert j["id"] not in claimed
    db.requeue_job(j["id"], delay=0)
    assert db.claim_job()["id"] == j["id"]


def test_age_cutoff(client, monkeypatch):
    from neurosearch import ingest, media
    # fake a channel with 3 videos newest-first; metadata says the 2nd is old
    monkeypatch.setattr(media, "enumerate_entries", lambda url: ({"id": "UC1", "title": "Chan", "url": url},
        [{"id": f"vid{i}0000000", "url": f"https://www.youtube.com/watch?v=vid{i}0000000", "title": f"V{i}"} for i in range(3)]))
    dates = {"vid00000000": "2026-06-01", "vid10000000": "2019-01-01", "vid20000000": "2018-01-01"}
    def fake_extract(url, platform, progress=None, cookies_file=None, referer=None, min_date=None):
        vid = url.split("v=")[1]
        if min_date and dates[vid] < min_date:
            raise ingest.TooOld(f"published {dates[vid]}, before cutoff {min_date}")
        return {"platform": "youtube", "external_id": vid, "url": url, "title": vid, "published_at": dates[vid], "duration": 60,
                "transcript_kind": "captions", "segments": [{"start": 0, "end": 5, "text": "hello content"}], "chapters": []}
    monkeypatch.setattr(ingest, "extract_transcript", fake_extract)
    p = client.post("/api/projects", headers=H, json={"name": "Cutoff", "brief": "x"}).json()
    # default: channel is listed and waits for approval
    r = ingest.ingest_url("https://www.youtube.com/@chan", project_id=p["id"], since_years=2, max_videos=10)
    assert r["proposed"] == 3 and r["queued"] == 0 and r["review"] is True and r["limits"]["since"] is not None
    reviews = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()
    assert len(reviews) == 1 and len(reviews[0]["proposed"]) == 3
    # proposed sources are hidden from the project's source list
    assert all(x["status"] != "proposed" for x in client.get("/api/sources", headers=H, params={"project_id": p["id"]}).json())
    # approve all -> jobs created
    a = client.post(f"/api/collections/{reviews[0]['id']}/approve", headers=H, json={}).json()
    assert a["started"] == 3 and a["dropped"] == 0
    # run the queued jobs synchronously
    from neurosearch import jobs
    while (j := db.claim_job()):
        try:
            res = jobs.run_job(j); db.update_job(j["id"], status="done", result=res)
        except Exception as e:  # noqa: BLE001
            db.update_job(j["id"], status="failed", message=str(e))
    statuses = {s["external_id"]: s["status"] for s in db.list_sources(limit=1000) if s["external_id"] in dates}
    assert statuses["vid00000000"] == "ready" and statuses["vid10000000"] == "skipped" and statuses["vid20000000"] == "skipped"


def test_budget_valve(client, monkeypatch):
    from neurosearch import usage, jobs
    # record spend then set a tiny daily budget -> paid jobs wait, queue keeps order, resume when raised
    usage.record("findings", "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)   # $3
    u = client.get("/api/usage", headers=H).json()
    assert u["today"] >= 3.0 and u["blocked"] is None
    client.post("/api/usage/budget", headers=H, json={"daily": 2})
    u = client.get("/api/usage", headers=H).json()
    assert "daily budget reached" in (u["blocked"] or "")
    ok, reason, wait = usage.check()
    assert not ok and wait >= 60
    j = db.create_job("reembed", {})
    # run the worker loop body once: the job must be re-queued, not failed
    job = db.claim_job()
    try:
        jobs.run_job(job)
    except usage.BudgetPaused as e:
        db.requeue_job(job["id"], delay=min(e.wait, 3600), message=f"paused: {e}")
    row = db.get_job(j["id"])
    assert row["status"] == "queued" and "paused" in row["message"]
    # manual pause/resume clears the wait
    client.post("/api/usage/budget", headers=H, json={"daily": 100, "paused": True})
    assert "paused by you" in client.get("/api/usage", headers=H).json()["blocked"]
    client.post("/api/usage/budget", headers=H, json={"paused": False})
    assert client.get("/api/usage", headers=H).json()["blocked"] is None
    assert db.get_job(j["id"])["not_before"] is None
    db.update_job(j["id"], status="done")


def test_review_partial_approve(client, monkeypatch):
    from neurosearch import ingest, media
    monkeypatch.setattr(media, "enumerate_entries", lambda url: ({"id": "PLx", "title": "List", "url": url},
        [{"id": f"pl{i}000000000"[:11], "url": f"https://www.youtube.com/watch?v=pl{i}0000000", "title": f"P{i}"} for i in range(4)]))
    p = client.post("/api/projects", headers=H, json={"name": "Review", "brief": "x"}).json()
    r = ingest.ingest_url("https://www.youtube.com/playlist?list=PLx", project_id=p["id"])
    assert r["proposed"] == 4
    rv = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]
    keep = [s["id"] for s in rv["proposed"][:2]]
    a = client.post(f"/api/collections/{rv['id']}/approve", headers=H, json={"source_ids": keep}).json()
    assert a["started"] == 2 and a["dropped"] == 2
    assert client.get(f"/api/projects/{p['id']}/reviews", headers=H).json() == []
    jobs_ = [j for j in client.get(f"/api/projects/{p['id']}/jobs", headers=H).json() if j["kind"] == "ingest_source"]
    assert {j["payload"]["source_id"] for j in jobs_} >= set(keep)


def test_cancel_queued(client):
    p = client.post("/api/projects", headers=H, json={"name": "Cancel", "brief": "x"}).json()
    src = db.upsert_source(platform="youtube", external_id="cancelme001", url="https://www.youtube.com/watch?v=cancelme001", status="pending")
    coll = db.upsert_collection("channel", "UCc", "u", "Chan"); db.link_source_collection(src["id"], coll["id"]); db.add_project_collections(p["id"], [coll["id"]])
    j = db.create_job("ingest_source", {"source_id": src["id"], "collection_id": coll["id"], "min_date": "2024-01-01"})
    r = client.post("/api/jobs/cancel-queued", headers=H, json={}).json()
    assert r["cancelled"] >= 1 and db.get_job(j["id"])["status"] == "done" and db.get_job(j["id"])["message"] == "cancelled"
    assert db.get_source(src["id"])["status"] == "proposed"
    assert client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]["proposed"][0]["id"] == src["id"]


def test_relevance_ranking(client, monkeypatch):
    from neurosearch import ingest, media, relevance
    import anthropic
    from tests.fake_claude import Anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Anthropic)
    monkeypatch.setattr(relevance.settings, "anthropic_api_key", "fake")
    monkeypatch.setattr(media, "enumerate_entries", lambda url: ({"id": "UCr", "title": "Chan", "url": url},
        [{"id": f"rk{i}000000000"[:11], "url": f"https://www.youtube.com/watch?v=rk{i}00000000", "title": f"V{i}",
          "description": "about money" if i % 2 else "vlog", "view_count": 1000 * i, "duration": 600} for i in range(6)]))
    p = client.post("/api/projects", headers=H, json={"name": "Rank", "brief": "getting out of debt"}).json()
    r = ingest.ingest_url("https://www.youtube.com/@chan", project_id=p["id"], max_videos=2)
    assert r["proposed"] == 6                      # whole pool is listed, not just the first 2
    rv = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]
    assert rv["meta"]["ranked"] is False and rv["meta"]["max_videos"] == 2
    job = [j for j in client.get(f"/api/projects/{p['id']}/jobs", headers=H).json() if j["kind"] == "rank_proposed"][0]
    res = relevance.rank_collection(rv["id"], p["id"], want=2)
    assert res["ranked"] == 6
    rv = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]
    assert rv["meta"]["ranked"] is True
    scores = [s["relevance"] for s in rv["proposed"]]
    assert scores == sorted(scores, reverse=True) and scores[0] == 90 and scores[-1] == 20
    assert rv["proposed"][0]["relevance_why"] == "on topic" and rv["proposed"][0]["description"] == "about money"
    # re-rank endpoint queues a job and resets the flag
    assert "job_id" in client.post(f"/api/collections/{rv['id']}/rank", headers=H, json={"want": 3}).json()
    assert db.review_meta(rv["id"])["ranked"] is False and db.review_meta(rv["id"])["max_videos"] == 3


def test_cancel_single_job(client):
    p = client.post("/api/projects", headers=H, json={"name": "Cancel1", "brief": "x"}).json()
    ids = []
    for k in ("a", "b"):
        src = db.upsert_source(platform="youtube", external_id=f"one{k}0000000", url=f"https://www.youtube.com/watch?v=one{k}0000000", status="pending", title=f"Video {k}")
        db.add_project_sources(p["id"], [src["id"]])
        ids.append(db.create_job("ingest_source", {"source_id": src["id"]})["id"])
    js = client.get(f"/api/projects/{p['id']}/jobs", headers=H).json()
    assert any(j.get("label") == "Video a" for j in js)
    assert client.post(f"/api/jobs/{ids[0]}/cancel", headers=H).json()["cancelled"] == 1
    assert db.get_job(ids[0])["message"] == "cancelled" and db.get_job(ids[1])["status"] == "queued"
    assert client.post(f"/api/jobs/{ids[0]}/cancel", headers=H).status_code == 409


def test_discover_background_and_pause_turn(client, monkeypatch):
    import anthropic
    from tests.fake_claude import Anthropic, _Msgs
    from neurosearch import discover, jobs
    calls = {"n": 0}
    orig = _Msgs.create
    def create(self, **kw):   # first call returns a paused turn with no text, second the real answer
        calls["n"] += 1
        r = orig(self, **kw)
        if calls["n"] == 2:   # the web-search (verify) pass hands back a paused turn first
            r.stop_reason = "pause_turn"; r.content = []
        return r
    monkeypatch.setattr(_Msgs, "create", create)
    monkeypatch.setattr(anthropic, "Anthropic", Anthropic)
    monkeypatch.setattr(discover.settings, "anthropic_api_key", "fake")
    p = client.post("/api/projects", headers=H, json={"name": "BG", "brief": "get out of debt"}).json()
    r = client.post(f"/api/projects/{p['id']}/discover", headers=H, json={"background": True}).json()
    job = db.get_job(r["job_id"]); assert job["kind"] == "discover"
    res = jobs.run_job(job)
    assert calls["n"] == 3 and res["added"] == 3 and res["verified"] == 1
    assert len(client.get(f"/api/projects/{p['id']}/discoveries", headers=H).json()) == 3


def test_review_discard_last(client, monkeypatch):
    from neurosearch import ingest, media
    monkeypatch.setattr(media, "enumerate_entries", lambda url: ({"id": "PLd", "title": "L", "url": url},
        [{"id": "dl00000000a", "url": "https://www.youtube.com/watch?v=dl00000000a", "title": "only one"}]))
    p = client.post("/api/projects", headers=H, json={"name": "Last", "brief": "x"}).json()
    ingest.ingest_url("https://www.youtube.com/playlist?list=PLd", project_id=p["id"])
    rv = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]
    assert client.post(f"/api/collections/{rv['id']}/approve", headers=H, json={"source_ids": []}).json()["dropped"] == 1
    assert client.get(f"/api/projects/{p['id']}/reviews", headers=H).json() == []


def test_webpage_source(client, monkeypatch):
    from neurosearch import webpage, media
    html = ("<html><head><title>Buying a boring business</title></head><body><nav><a>Home</a></nav><article><h1>Buying a boring business</h1>"
            + "".join(f"<p>Paragraph {i}: SBA lenders want a debt service coverage ratio above 1.25 and a seller note for part of the price.</p>" for i in range(40))
            + "</article><footer>x</footer></body></html>")
    monkeypatch.setattr(webpage, "fetch", lambda url, timeout=40.0: (url, "text/html; charset=utf-8", html.encode()))
    assert media.classify_url("https://example.com/blog/boring-business") == "web"
    assert media.classify_url("https://vimeo.com/12345") == "media"
    assert media.classify_url("https://cdn.example.com/ep1.mp3") == "media"
    p = client.post("/api/projects", headers=H, json={"name": "Web", "brief": "buying businesses"}).json()
    from neurosearch import ingest
    r = ingest.ingest_url("https://example.com/blog/boring-business", project_id=p["id"])
    assert r["kind"] == "web" and r["segments"] >= 1 and r["title"] == "Buying a boring business"
    src = client.get(f"/api/sources/{r['source_id']}", headers=H).json()
    assert src["platform"] == "web" and src["status"] == "ready" and src["channel"] == "example.com"
    hits = client.get("/api/search?q=debt+service+coverage&project_id=" + p["id"], headers=H).json()
    assert hits and hits[0]["timestamp"].startswith("§ ")


def test_rank_parse_tolerates_bad_json():
    from neurosearch.relevance import parse_scores
    good = '{"scores":[{"i":0,"score":90,"why":"on topic"},{"i":1,"score":10,"why":"filler"}]}'
    assert [x["score"] for x in parse_scores(good)["scores"]] == [90, 10]
    bad = '```json\n{"scores":[{"i":0,"score":90,"why":"buying "boring" businesses"},{"i":1,"score":10,"why":"filler"},{"i":2,"score":55,"why":"cut off'
    res = parse_scores(bad)
    assert res.get("repaired") and [(x["i"], x["score"]) for x in res["scores"]] == [(0, 90), (1, 10)]
    assert res["scores"][0]["why"] == 'buying "boring" businesses'


def test_ingest_html_from_extension(client):
    p = client.post("/api/projects", headers=H, json={"name": "Ext", "brief": "buying businesses"}).json()
    html = "<html><head><title>Learning Center</title></head><body><main><h1>Due diligence checklist</h1>" + "".join(
        f"<p>Item {i}: verify three years of tax returns and reconcile them against the P&amp;L before making an offer.</p>" for i in range(30)) + "</main></body></html>"
    r = client.post(f"/api/projects/{p['id']}/ingest/html", headers=H, json={"url": "https://www.bizbuysell.com/learning-center/", "html": html}).json()
    assert r["kind"] == "web" and r["title"] == "Learning Center" and r["segments"] >= 1
    assert client.get(f"/api/sources/{r['source_id']}", headers=H).json()["status"] == "ready"


def test_blocked_site_message(monkeypatch):
    import httpx
    from neurosearch import webpage
    class R:  # minimal httpx-like response
        status_code = 403; headers = {}; content = b""; url = "https://x.com/a"
    class C:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url): return R()
    monkeypatch.setattr(httpx, "Client", C)
    import pytest
    with pytest.raises(webpage.Blocked, match="blocks automated readers"):
        webpage.fetch("https://x.com/a")


def test_instagram_urls(client):
    from neurosearch import media, ingest
    assert media.classify_url("https://www.instagram.com/sbaloanguy1/") == "instagram_profile"
    assert media.classify_url("https://www.instagram.com/reel/Cabc123/") == "instagram"
    import pytest
    with pytest.raises(RuntimeError, match="lends your session"):
        ingest.ingest_url("https://www.instagram.com/sbaloanguy1/")
    p = client.post("/api/projects", headers=H, json={"name": "IG", "brief": "x"}).json()
    r = client.post(f"/api/projects/{p['id']}/ingest/with-session", headers=H, json={"url": "https://www.instagram.com/reel/Cabc123/",
        "cookies": [{"domain": ".instagram.com", "name": "sessionid", "value": "abc", "path": "/", "secure": True}]}).json()
    j = db.get_job(r["job_id"]); assert r["cookies"] and j["payload"]["cookies_file"].endswith(".txt") and j["payload"]["review"] is False


def test_instagram_profile_with_session(client, monkeypatch, tmp_path):
    from neurosearch import ingest, media
    ck = tmp_path / "ig.txt"; ck.write_text("# cookies")
    monkeypatch.setattr(media, "enumerate_instagram", lambda url, cookies_file, limit=40: (
        {"id": "ig:sbaloanguy1", "title": "@sbaloanguy1 (Instagram)", "url": "https://www.instagram.com/sbaloanguy1/"},
        [{"id": f"ig{i}", "url": f"https://www.instagram.com/reel/ig{i}/", "title": f"SBA tip {i}", "duration": 45} for i in range(5)]))
    p = client.post("/api/projects", headers=H, json={"name": "IGP", "brief": "sba loans"}).json()
    r = ingest.ingest_url("https://www.instagram.com/sbaloanguy1/", project_id=p["id"], cookies_file=str(ck), review=False)
    assert r["kind"] == "instagram_profile" and r["proposed"] == 5 and r["review"]
    rv = client.get(f"/api/projects/{p['id']}/reviews", headers=H).json()[0]
    assert rv["kind"] == "instagram" and rv["meta"]["cookies_file"] == str(ck)
    a = client.post(f"/api/collections/{rv['id']}/approve", headers=H, json={"source_ids": [rv["proposed"][0]["id"]]}).json()
    assert a["started"] == 1
    job = [j for j in db.list_jobs(50) if j["kind"] == "ingest_source"][0]
    assert job["payload"]["cookies_file"] == str(ck) and job["payload"]["referer"].startswith("https://www.instagram.com/")


def test_transient_failures_retry_then_fail(client, monkeypatch):
    from neurosearch import jobs, ingest
    calls = {"n": 0}
    def boom(url, **kw):
        calls["n"] += 1
        raise RuntimeError("Instagram wants a login for this (or rate-limited the session)")
    monkeypatch.setattr(ingest, "ingest_url", boom)
    j = db.create_job("ingest_url", {"url": "https://www.instagram.com/reel/x/", "project_id": None})
    jobs.run_job  # noqa
    # drive the worker loop by hand: run + handle like _worker does
    def step():
        job = db.get_job(j["id"])
        try:
            db.update_job(job["id"], status="done", result=jobs.run_job(job))
        except Exception as e:  # noqa: BLE001
            payload = job.get("payload") or {}
            attempts = int(payload.get("_attempts") or 0) + 1
            if jobs.TRANSIENT.search(str(e)) and attempts < jobs.MAX_ATTEMPTS:
                db.set_job_payload(job["id"], {**payload, "_attempts": attempts}); db.requeue_job(job["id"], delay=0, message="retry")
            else:
                db.update_job(job["id"], status="failed", message=f"error: {e}")
    for _ in range(jobs.MAX_ATTEMPTS):
        step()
    assert calls["n"] == jobs.MAX_ATTEMPTS and db.get_job(j["id"])["status"] == "failed"
    assert jobs.TRANSIENT.search("HTTP Error 429: Too Many Requests") and not jobs.TRANSIENT.search("This Instagram post has no video")
    # manual retry endpoint creates a fresh job and retires the failed one
    r = client.post(f"/api/jobs/{j['id']}/retry", headers=H).json()
    assert db.get_job(r["job_id"])["status"] == "queued" and db.get_job(j["id"])["message"].startswith("retried")
    assert client.post("/api/jobs/retry-failed", headers=H, json={}).json()["retried"] == 0


def test_ingest_skipped_anyway(client):
    p = client.post("/api/projects", headers=H, json={"name": "Skip", "brief": "x"}).json()
    src = db.upsert_source(platform="youtube", external_id="oldvid00001", url="https://www.youtube.com/watch?v=oldvid00001", status="skipped", error="published 2019-01-01, before cutoff 2024-09-03")
    db.add_project_sources(p["id"], [src["id"]])
    r = client.post("/api/sources/retry-skipped", headers=H, json={"project_id": p["id"]}).json()
    assert r["queued"] == 1 and db.get_source(src["id"])["status"] == "pending"
    j = [j for j in db.list_jobs(20) if j["kind"] == "ingest_source" and j["payload"]["source_id"] == src["id"]][0]
    assert "min_date" not in j["payload"]
