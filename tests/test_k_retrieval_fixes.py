"""0.24.1 — the chat can see and search the library; priority sources; follow-up grounding; in-chat upload; PDF reflow.
(Sorts after test_core, which builds the shared settings/DB at import.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_k_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurosearch import db, documents, evals, fake_ai, qa, search  # noqa: E402
from neurosearch.api import app  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True, scope="module")
def fresh():
    """This module uses the process-wide test database (the one the shared API client was started on): the app's
    threadpool and workers keep thread-local connections to it, so tests that go through HTTP must not move the data
    directory. Each test loads its own golden project, so nothing here depends on prior state."""
    mp = pytest.MonkeyPatch()
    (settings.data_dir / "media").mkdir(parents=True, exist_ok=True)
    mp.setattr(settings, "fake_ai", True)
    mp.setattr(settings, "daily_budget", 1000)
    mp.delenv("NEUROSEARCH_FAKE_CHAT_TOOL", raising=False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    yield
    mp.undo()
    db._local.conn = None


def _golden():
    g = evals.load_golden()
    return g["project_id"], g["sources"]




# ---------------------------------------------------------------- inventory + list_sources

def test_inventory_block_names_documents_not_videos():
    pid, ids = _golden()
    inv = qa.inventory_block(pid)
    assert "Project library:" in inv and "video" in inv
    assert "SBA 7(a) acquisition lending summary" in inv                 # the golden PDF is listed by title
    assert "[document]" in inv
    for sid in ids.values():
        s = db.get_source(sid)
        if s["platform"] == "youtube":
            assert s["title"] not in inv                                 # videos are counted, never listed
    # it lives in the volatile state block, after the cached prefix
    project = db.get_project(pid)
    blocks, _ = qa.chat_system_blocks(project, False, qa._project_tools() + qa._library_tools(), None)
    assert "Project library:" in blocks[-1]["text"] and "cache_control" not in blocks[-1]
    assert "Project library:" not in blocks[0]["text"]


def test_list_sources_tool_is_the_real_inventory():
    pid, ids = _golden()
    project = db.get_project(pid)
    actions: list = []
    out = qa._run_tool("list_sources", {"filter": "document"}, project, [], actions)
    assert "SBA 7(a) acquisition lending summary" in out and "video" not in out.split("\n", 1)[1]
    out_all = qa._run_tool("list_sources", {}, project, [], actions)
    assert out_all.startswith(f"{len(db.project_source_inventory(pid))} source(s)")
    assert qa._run_tool("list_sources", {"filter": "zzz-nothing"}, project, [], actions) == "no sources match"


# ---------------------------------------------------------------- priority sources

def test_priority_sources_get_reserved_slots_and_labels():
    pid, ids = _golden()
    doc = ids["report"]
    q = "what does the lender ask for"
    base = search.search(q, limit=6, source_ids=db.project_source_ids(pid))
    db.set_source_priority(pid, [doc], True)
    assert db.priority_source_ids(pid) == {doc}
    prio = search.search(q, limit=6, source_ids=db.project_source_ids(pid), priority_ids={doc})
    assert any(h["source_id"] == doc and h.get("priority") for h in prio)
    assert len(prio) == len(base) and prio == sorted(prio, key=lambda h: -h["score"])       # numbering still by score
    # a priority source with NO match contributes nothing (no forced junk)
    none = search.search("sourdough starter hydration", limit=4, source_ids=db.project_source_ids(pid), priority_ids={doc})
    assert all(h["source_id"] != doc for h in none) or any("lender" in h["text"].lower() for h in none)
    # label reaches the model
    ctx = qa.build_context(prio)
    assert "[priority source]" in ctx
    # unflag
    db.set_source_priority(pid, [doc], False)
    assert db.priority_source_ids(pid) == set()


def test_priority_flag_is_project_relative_and_survives_membership_paths():
    pid, ids = _golden()
    other = db.create_project("other", "brief")
    db.set_source_priority(pid, [ids["report"]], True)
    assert ids["report"] not in db.priority_source_ids(other["id"])
    inv = {r["id"]: r for r in db.project_source_inventory(pid)}
    assert inv[ids["report"]]["priority"] is True


def test_set_source_priority_tool_records_user_authority_as_state():
    pid, ids = _golden()
    project = db.get_project(pid)
    actions: list = []
    out = qa._run_tool("set_source_priority", {"filter": "lending summary"}, project, [], actions)
    assert out.startswith("flagged 1 source(s)") and actions[-1]["type"] == "priority_set" and actions[-1]["count"] == 1
    assert db.priority_source_ids(pid) == {ids["report"]}
    assert "no sources match" in qa._run_tool("set_source_priority", {"filter": "no-such-thing"}, project, [], actions)
    out = qa._run_tool("set_source_priority", {"filter": "lending summary", "priority": False}, project, [], actions)
    assert out.startswith("unflagged") and db.priority_source_ids(pid) == set()


def test_priority_api_and_listing(client):
    pid, ids = _golden()
    c = client
    if True:
        r = c.put(f"/api/projects/{pid}/priority", json={"source_ids": [ids["report"]], "priority": True}, headers=H)
        assert r.status_code == 200 and r.json()["priority_source_ids"] == [ids["report"]]
        rows = c.get(f"/api/sources?project_id={pid}", headers=H).json()
        assert {r["id"]: r["priority"] for r in rows}[ids["report"]] is True


# ---------------------------------------------------------------- search_library tool + the chat loop

def test_search_library_tool_extends_excerpts_with_continuing_numbers():
    pid, ids = _golden()
    project = db.get_project(pid)
    hits = search.search("seller note standby", limit=3, source_ids=db.project_source_ids(pid))
    ctx = {"hits": list(hits), "source_ids": db.project_source_ids(pid), "priority_ids": set(), "seen": {h["chunk_id"] for h in hits}}
    actions: list = []
    out = qa._run_tool("search_library", {"query": "what documents does the lender require", "source_filter": "document", "limit": 4}, project, [], actions, ctx)
    assert out.startswith("<excerpts>") and f"[{len(hits) + 1}]" in out and "(cite these as" in out
    assert len(ctx["hits"]) > len(hits) and all(h["source_id"] == ids["report"] for h in ctx["hits"][len(hits):])
    assert len({h["chunk_id"] for h in ctx["hits"]}) == len(ctx["hits"])                      # no duplicates across calls
    assert actions[-1]["type"] == "searched"
    assert "no sources match" in qa._run_tool("search_library", {"query": "x", "source_filter": "nope-nope"}, project, [], actions, ctx)
    ctx["hits"].extend([{"chunk_id": -i} for i in range(qa.MAX_EXCERPTS)])
    assert "excerpt limit" in qa._run_tool("search_library", {"query": "more"}, project, [], actions, ctx)


def test_chat_uses_search_library_and_citations_stay_valid(monkeypatch):
    pid, ids = _golden()
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TOOL", json.dumps({"name": "search_library", "input": {"query": "documents the lender asks for", "source_filter": "document"}}))
    res = qa.ask("Can you check the PDFs for anything about lender paperwork?", project_id=pid, conversation_id=db.new_id())
    assert any(a["type"] == "searched" for a in res["actions"])
    assert any(h["source_id"] == ids["report"] for h in res["hits"])                          # the PDF is now in the excerpts
    assert not res["invalid_citations"] and res["citations"]
    # every tool the model can call is offered
    names = {t["name"] for t in qa._project_tools() + qa._library_tools()}
    assert {"search_library", "list_sources", "set_source_priority", "save_finding", "record_fact"} <= names


def test_chat_can_flag_priority_from_a_user_statement(monkeypatch):
    pid, ids = _golden()
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TOOL", json.dumps({"name": "set_source_priority", "input": {"filter": "lending summary"}}))
    res = qa.ask("Anything from the SBA lending summary should be considered top tier", project_id=pid, conversation_id=db.new_id())
    assert any(a["type"] == "priority_set" for a in res["actions"]) and db.priority_source_ids(pid) == {ids["report"]}
    assert "priority source" in qa.render_markdown(res)


# ---------------------------------------------------------------- follow-up grounding

def test_follow_up_query_is_grounded_in_the_previous_question():
    hist = [{"role": "user", "content": "How much equity injection does an SBA 7(a) acquisition loan need?"},
            {"role": "assistant", "content": "Ten percent [1]."}]
    assert qa._retrieval_query("can you check the PDFs for that?", hist).startswith("How much equity injection")
    assert qa._retrieval_query("and those two?", hist).endswith("and those two?")
    long_q = "Tell me, in detail, how a seller note interacts with the SBA equity injection rules and what standby means for the first two years of the loan"
    assert qa._retrieval_query(long_q, hist) == long_q                                        # a full question stands alone
    assert qa._retrieval_query("what about it?", []) == "what about it?"                      # nothing to ground on


# ---------------------------------------------------------------- PDF reflow

def test_word_per_line_pdf_pages_are_reflowed_and_prose_is_untouched():
    col = "\n".join("Below is organized so you can paste it directly into a Google Doc and keep the notes".split()) + "\n\nSecond\npara\nhere\nnow\ntoo\nok\nyes\nend"
    out = documents._reflow(col)
    assert out.startswith("Below is organized so you can paste") and "\n\nSecond para here" in out
    prose = "\n".join(["This is an ordinary line of extracted prose with many words in it."] * 10)
    assert documents._reflow(prose) == prose
    assert documents._reflow("short") == "short"


# ---------------------------------------------------------------- in-chat upload, same-turn availability

def test_immediate_upload_is_ready_in_the_same_request_and_used_on_the_same_turn(tmp_path, client):
    pid, ids = _golden()
    c = client
    body = ("Insurance underwriting note. Low-time twin pilots typically need 25 hours of dual instruction in type "
            "before an insurer will bind coverage on a Baron. Premiums fall after the first 100 hours in type.\n") * 3
    f = tmp_path / "insurance_note.txt"; f.write_text(body)
    if True:
        with open(f, "rb") as fh:
            r = c.post("/api/ingest/file", files={"file": ("insurance_note.txt", fh, "text/plain")},
                       data={"project_id": pid, "immediate": "true"}, headers=H)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["immediate"] is True and j["ready"] is True and j["source_id"]
        sid = j["source_id"]
        assert sid in db.project_source_ids(pid) and db.get_chunks(sid)
        # the same file again is the same global source (no second row, no re-parse) — dedupe as today
        with open(f, "rb") as fh:
            r2 = c.post("/api/ingest/file", files={"file": ("insurance_note.txt", fh, "text/plain")}, data={"project_id": pid, "immediate": "true"}, headers=H)
        assert r2.json()["source_id"] == sid
        # media is NOT parsed inline: it is queued like before, and the response says so
        m = tmp_path / "clip.mp3"; m.write_bytes(b"\x00" * 100)
        with open(m, "rb") as fh:
            r3 = c.post("/api/ingest/file", files={"file": ("clip.mp3", fh, "audio/mpeg")}, data={"project_id": pid, "immediate": "true"}, headers=H)
        assert r3.json()["immediate"] is False and r3.json()["job"] and "transcribed" in r3.json()["note"]
        # the chat turn that carries the attachment sees it first, labelled, and cites it
        r4 = c.post("/api/ask", json={"question": "What does my attached note say about dual instruction?", "project_id": pid,
                                      "attached_source_ids": [sid]}, headers=H)
        assert r4.status_code == 200, r4.text
        res = r4.json()
        assert res["hits"][0]["source_id"] == sid and res["hits"][0]["attached"] is True
        assert any(h["source_id"] != sid for h in res["hits"])                                 # plus ordinary retrieval
        assert res["citations"] and res["citations"][0]["source_id"] == sid and not res["invalid_citations"]
    # the excerpt label the model sees
    assert "[attached by the user in this message]" in qa.build_context(res["hits"][:1])


def test_embedding_failure_does_not_fail_a_readable_document(tmp_path, monkeypatch):
    from neurosearch import ingest
    pid, _ = _golden()
    def boom(*a, **k):
        raise RuntimeError("embeddings provider down")
    monkeypatch.setattr(ingest, "embed_pending", boom)
    f = tmp_path / "note.txt"; f.write_text("A readable note about hangar rent at Modesto airport. " * 20)
    res = ingest.ingest_local_file(f, "note", [], pid, original_name="note.txt")
    src = db.get_source(res["source_id"])
    assert src["status"] == "ready" and res["embedded"] == 0
    assert db.fts_search("hangar rent Modesto", limit=5, source_ids=[src["id"]])           # full-text works immediately
    ev = db.connect().execute("SELECT COUNT(*) c FROM validation_events WHERE kind='embeddings_deferred'").fetchone()["c"]
    assert ev == 1
