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
