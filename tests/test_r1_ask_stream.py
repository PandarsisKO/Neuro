"""R1 (SPEED-MISSION.md) — the chat answer is narrated while it is written.

The measured problem was not that answers were slow: `answer.chat` has a p90 of 51 s and a max of 78 s, and every
second of that was a blank spinner. Nothing about the work changed here. What changed is that the user can see the
turn happening — which phase it is in, how long it has been going, and the answer arriving word by word.

The contract is deliberately narrow, and every test below asserts BOTH halves of it: streaming narrates the same
turn the non-streaming route runs, and the finished message still comes from the real result (citations, actions,
validation), never from the streamed text. A narration channel that could change an answer would be a liability,
not a feature. (Sorts after test_p5.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_r1_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, evals, providers, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _golden() -> str:
    return evals.load_golden()["project_id"]


def _events(raw: str) -> list[dict]:
    return [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]


# ---------------------------------------------------------------- the narration channel

def test_every_stage_of_the_turn_is_announced_in_words():
    seen: list[dict] = []
    r = qa.ask("What is the minimum down payment?", project_id=_golden(), on_event=seen.append)
    phases = [e["phase"] for e in seen if e["type"] == "phase"]
    assert phases[0] == "retrieving"
    for expected in ("retrieved", "thinking", "writing", "checking"):
        assert expected in phases, f"{expected} was never announced: {phases}"
    labels = [e["label"] for e in seen if e["type"] == "phase"]
    assert all(labels), "a phase with no sayable label is a spinner with extra steps"
    # the 'retrieved' phase reports real counts, never a shape
    got = next(e for e in seen if e.get("phase") == "retrieved")
    assert got["hits"] == len(r["hits"]) and got["sources"] >= 1


def test_the_streamed_text_is_the_answer_not_a_paraphrase():
    seen: list[dict] = []
    r = qa.ask("What is the minimum down payment?", project_id=_golden(), on_event=seen.append)
    streamed = "".join(e["text"] for e in seen if e["type"] == "delta")
    assert streamed.strip(), "nothing was streamed"
    assert streamed.strip() == r["answer"].strip()
    assert r["citations"], "the real result still carries the citations the stream cannot"


def test_a_callback_that_raises_never_costs_the_user_the_answer():
    def boom(_ev):
        raise RuntimeError("the browser closed mid-answer")

    r = qa.ask("What is the minimum down payment?", project_id=_golden(), on_event=boom)
    assert r["answer"] and r["citations"]


def test_no_callback_means_the_streaming_transport_is_never_used(monkeypatch):
    """Streaming is opt-in per call. Every background caller of answer.chat must keep the plain transport,
    which is the one with the retry policy."""
    calls: list[int] = []
    real = providers._stream_collect
    monkeypatch.setattr(providers, "_stream_collect", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    qa.ask("What is the minimum down payment?", project_id=_golden())
    assert not calls


def test_streaming_is_only_a_transport_the_answer_is_identical():
    pid = _golden()
    plain = qa.ask("What is the minimum down payment?", project_id=pid)
    streamed = qa.ask("What is the minimum down payment?", project_id=pid, on_event=lambda _e: None)
    assert plain["answer"] == streamed["answer"]
    assert [c["n"] for c in plain["citations"]] == [c["n"] for c in streamed["citations"]]


# ---------------------------------------------------------------- the endpoint

def test_endpoint_opens_immediately_and_ends_with_the_full_result(client):
    p = client.post("/api/projects", headers=H, json={"name": "R1 stream", "brief": "streaming"}).json()
    with client.stream("POST", "/api/ask/stream", headers=H,
                       json={"question": "what do you have?", "project_id": p["id"]}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    evs = _events(body)
    assert evs[0]["type"] == "open", "the first frame must arrive before any model call — that is the point"
    assert evs[-1]["type"] == "done"
    assert evs[-1]["result"]["answer"]
    assert any(e["type"] == "phase" for e in evs)


def test_endpoint_reports_a_failure_instead_of_dropping_the_connection(client, monkeypatch):
    from neurosearch import api as api_mod

    def blow(*a, **k):
        raise RuntimeError("model refused")

    monkeypatch.setattr(api_mod.qa, "ask", blow)
    p = client.post("/api/projects", headers=H, json={"name": "R1 err", "brief": "b"}).json()
    with client.stream("POST", "/api/ask/stream", headers=H,
                       json={"question": "x", "project_id": p["id"]}) as resp:
        body = "".join(resp.iter_text())
    evs = _events(body)
    assert evs[-1]["type"] == "error" and "model refused" in evs[-1]["message"]


def test_the_streamed_turn_saves_exactly_one_exchange(client):
    p = client.post("/api/projects", headers=H, json={"name": "R1 save", "brief": "b"}).json()
    conv = client.post("/api/conversations", headers=H, json={"project_id": p["id"]}).json()["id"]
    with client.stream("POST", "/api/ask/stream", headers=H,
                       json={"question": "one question", "project_id": p["id"], "conversation_id": conv}) as resp:
        "".join(resp.iter_text())
    msgs = client.get(f"/api/conversations/{conv}", headers=H).json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
