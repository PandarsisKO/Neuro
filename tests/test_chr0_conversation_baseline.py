"""CHR0 (docs/CHAT-REFRESH-PLAN.md §2, §14): every SUCCESSFUL assistant turn records what it could know —
messages.meta.evidence — from the FINAL excerpt list (initial retrieval + search_library additions + full-context
chunks), the scope it ran against, the retrieval query, and the real id of the user row it answered. Failed and
incomplete turns record no evidence, so the conversation's baseline never advances onto a turn that did not finish.
CHR0 changes nothing else: the answer, citations, tools and Claims path are untouched (the existing suites cover
that; this file only checks the bookkeeping)."""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, evals, fake_ai, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    for k in ("NEUROSEARCH_FAKE_CHAT_TOOL", "NEUROSEARCH_FAKE_CHAT_TRUNCATE", "NEUROSEARCH_FAKE_CHAT_TEXT_THEN_TOOL"):
        monkeypatch.delenv(k, raising=False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    yield
    db._local.conn = None


def _golden():
    return evals.load_golden()["project_id"]


def _rows(conv):
    return db.connect().execute("SELECT id, role, citations, meta FROM messages WHERE conversation_id=? ORDER BY id", (conv,)).fetchall()


def _last_assistant(conv):
    rows = [r for r in _rows(conv) if r["role"] == "assistant"]
    r = rows[-1]
    return r, json.loads(r["meta"] or "{}"), json.loads(r["citations"] or "[]")


def test_save_message_returns_the_row_id_and_get_messages_exposes_it():
    conv = db.create_conversation(None)["id"]
    a = db.save_message(conv, "user", "q1")
    b = db.save_message(conv, "assistant", "a1")
    assert isinstance(a, int) and isinstance(b, int) and b == a + 1
    assert [m["id"] for m in db.get_messages(conv)] == [a, b]


def test_successful_turn_records_shown_scope_query_and_question_id():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("What does the lender require for the seller note?", project_id=pid, conversation_id=conv)
    rows = _rows(conv)
    user_row = [r for r in rows if r["role"] == "user"][0]
    row, meta, cites = _last_assistant(conv)
    ev = meta["evidence"]
    assert ev["question_message_id"] == user_row["id"]                       # a real id, not a timestamp
    assert ev["retrieval_query"]                                               # the query the answer was built from
    assert set(ev["scope_source_ids"]) == set(db.get_project(pid)["source_ids"])
    shown = set(ev["shown_chunk_ids"])
    assert shown == {h["chunk_id"] for h in res["hits"]} and shown          # the initial retrieval, every excerpt
    # cited ⊆ shown: a citation [n] always points at an excerpt the model was shown
    cited_chunks = {res["hits"][c["n"] - 1]["chunk_id"] for c in cites}
    assert cited_chunks <= shown
    assert set(ev["shown_source_ids"]) == {h["source_id"] for h in res["hits"]}
    assert ev["research_revision"] == db.project_research_revision(pid)
    assert isinstance(ev["max_claim_evidence_id"], int)
    assert ev["full_context"] in (True, False) and ev["v"] == 4 and ev["complete"] is True
    assert set(ev["scope_source_revisions"]) <= set(ev["scope_source_ids"])
    assert db.conversation_baseline(conv)["message_id"] == row["id"]


def test_search_library_additions_are_part_of_the_snapshot(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TOOL", json.dumps({"name": "search_library", "input": {"query": "lender documents required", "limit": 4}}))
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("What documents does the lender need?", project_id=pid, conversation_id=conv)
    assert any(a["type"] == "searched" and a["added"] > 0 for a in res["actions"])   # the tool ran and added excerpts
    _, meta, _ = _last_assistant(conv)
    shown = set(meta["evidence"]["shown_chunk_ids"])
    assert shown == {h["chunk_id"] for h in res["hits"]}                    # FINAL ctx["hits"], tool additions included
    initial = {h["chunk_id"] for h in qa._hits_for(qa._retrieval_query("What documents does the lender need?", []), 14, db.get_project(pid)["source_ids"])[0]}
    added = sum(a["added"] for a in res["actions"] if a["type"] == "searched")
    assert initial <= shown and len(shown) == len(initial) + added          # initial retrieval + exactly the tool's additions


def test_full_context_turn_records_every_chunk_shown():
    pid = _golden()
    sid = db.get_project(pid)["source_ids"][0]
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("Summarise this.", project_id=pid, source_ids=[sid], conversation_id=conv)
    _, meta, _ = _last_assistant(conv)
    ev = meta["evidence"]
    assert ev["full_context"] is True
    assert set(ev["shown_chunk_ids"]) == {c["id"] for c in db.get_chunks(sid)}
    assert ev["scope_source_ids"] == [sid]
    assert ev["shown_source_ids"] == [sid]
    assert len(res["hits"]) == len(ev["shown_chunk_ids"])


def test_incomplete_and_failed_turns_do_not_advance_the_baseline(monkeypatch):
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("First, a good answer.", project_id=pid, conversation_id=conv)
    good = db.conversation_baseline(conv)
    assert good is not None
    # an answer that hits the output limit twice: saved, marked incomplete, no evidence
    from neurosearch import providers
    real = providers.invoke

    def always_truncated(task, **kw):
        if task != "answer.chat":
            return real(task, **kw)
        return fake_ai._Blk(stop_reason="max_tokens", model="fake-claude", content=[fake_ai._Blk(type="text", text="part of an answer that never", citations=None)],
                            usage=fake_ai._Blk(input_tokens=10, output_tokens=4000, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
    monkeypatch.setattr(providers, "invoke", always_truncated)
    qa.ask("Write everything.", project_id=pid, conversation_id=conv)
    _, meta, _ = _last_assistant(conv)
    assert meta.get("incomplete") is True and "evidence" not in meta
    # a turn that raised: save_failure keeps it visibly failed, no evidence
    qa.save_failure(conv, pid, "boom", partial="half")
    _, meta, _ = _last_assistant(conv)
    assert meta.get("incomplete") is True and "evidence" not in meta
    assert db.conversation_baseline(conv)["message_id"] == good["message_id"]   # still the last GOOD turn


def test_link_only_turn_records_a_zero_hit_baseline_on_purpose(monkeypatch):
    from neurosearch import ingest
    monkeypatch.setattr(qa, "queue_urls", lambda urls, pid: [{"url": u, "job_id": "j1", "detected": None} for u in urls])
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("https://www.youtube.com/watch?v=abc123xyz00", project_id=pid, conversation_id=conv)
    assert "Queued 1 link" in res["answer"]
    _, meta, _ = _last_assistant(conv)
    ev = meta["evidence"]
    assert ev["shown_chunk_ids"] == [] and ev["retrieval_query"] == ""
    assert set(ev["scope_source_ids"]) == set(db.get_project(pid)["source_ids"])   # the scope as of NOW: the link is not in it yet
    assert db.conversation_baseline(conv)["evidence"]["shown_chunk_ids"] == []


def test_incomplete_bookkeeping_marks_the_snapshot_not_complete(monkeypatch):
    """CHR0 hardening (Kyle, 2026-09-18): a snapshot that failed partway (research_revision or claim_state could
    not be read) must say so, not silently pass as an exact baseline — CHR1 downgrades on this flag."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    monkeypatch.setattr(db, "project_research_revision", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    _, meta, _ = _last_assistant(conv)
    ev = meta["evidence"]
    assert ev["complete"] is False
    assert ev["shown_chunk_ids"]            # what WAS gathered is still recorded — never discarded wholesale
    assert ev["research_revision"] is None


def test_legacy_chat_without_snapshots_has_no_baseline():
    conv = db.create_conversation(None)["id"]
    db.save_message(conv, "user", "old question")
    db.save_message(conv, "assistant", "old answer", citations=[], meta={"generation": {}})
    assert db.conversation_baseline(conv) is None
