"""S24 — a question is the user's, not the answer's; and a source that left is not a failure (0.63.0).

Two live faults Kyle reported within minutes of each other.

**"chats are failing to save, I was chatting, it did not complete its response, and I lost the chat because I
looked at sources."** `qa.ask` wrote BOTH messages at the very end of the turn — after the model call, after
citations were resolved, after findings were written. A conversation row is created by the first `save_message`, so
a turn that raised or was abandoned saved nothing at all: not the answer, and **not the question he had typed**. The
whole chat vanished. The question is now saved the moment it arrives, before anything can fail, and
`qa.save_failure` records the assistant's side of a turn that did not finish — with whatever text had already been
written, clearly marked.

**"we seem to be getting 'error: FOREIGN KEY constraint failed' a lot today."** Measured in his job history: every
single occurrence is a `rank_proposed` job — 9 of them, the newest at 23:01 that evening, the oldest on Sep 8. That
job reads a collection's proposed sources, spends minutes ranking them (p50 384 s), then writes one relevance
artifact per source. If a source is deleted or replaced in between — exactly what approving a review, discarding
one, or retiring a direction does — the write lands on a dangling foreign key. And because those writes share one
`db.batch()`, **one vanished source voided the whole ranking**: minutes of paid work discarded, under an error
message that named neither the table nor the source.

A source that no longer exists has not failed, it has left. The artifact has nowhere to live, so it is skipped, the
rest of the ranking is kept, and the count is reported in the review note.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_lost_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _msgs(cid):
    return [(m["role"], m["content"]) for m in db.get_messages(cid, limit=100)]


# ------------------------------------------------------------------ the question survives a failed turn

def test_the_question_is_saved_before_anything_can_fail(fresh, monkeypatch):
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    boom = RuntimeError("the provider fell over mid-answer")
    monkeypatch.setattr(qa, "chat_system_blocks", lambda *a, **k: (_ for _ in ()).throw(boom))
    with pytest.raises(RuntimeError):
        qa.ask("what should worry me about customer concentration?", project_id=p["id"], conversation_id=cid)
    rows = _msgs(cid)
    assert rows and rows[0][0] == "user"
    assert "customer concentration" in rows[0][1]           # the chat exists, and his words are in it


def test_the_conversation_itself_exists_after_a_failed_turn(fresh, monkeypatch):
    """He did not lose an answer, he lost the CHAT — because the conversation row is created by its first message."""
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    monkeypatch.setattr(qa, "chat_system_blocks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    with pytest.raises(RuntimeError):
        qa.ask("a question I do not want to lose", project_id=p["id"], conversation_id=cid)
    assert any(c["id"] == cid for c in db.list_conversations(p["id"]))


def test_the_second_question_of_a_conversation_still_saves_when_history_fetch_and_provider_both_run(fresh, monkeypatch):
    """2026-09-18 (Kyle) — the history fetch was moved to before the save so _retrieval_query() sees the real prior
    turn instead of the question being answered. This is a durability gate on THAT reordering specifically: history
    must still be readable and the new question must still be saved, even when the turn then fails downstream."""
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    db.save_message(cid, "user", "how does seller financing work?", project_id=p["id"], title="q1")
    db.save_message(cid, "assistant", "It works like this [1].", project_id=p["id"])
    monkeypatch.setattr(qa, "chat_system_blocks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        qa.ask("what about taxes?", project_id=p["id"], conversation_id=cid)
    rows = _msgs(cid)
    assert rows[-1] == ("user", "what about taxes?")        # the new question survived the downstream failure


def test_a_failed_turn_can_record_the_assistant_side_too(fresh):
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    db.save_message(cid, "user", "why is this risky?", project_id=p["id"], title="why is this risky?")
    qa.save_failure(cid, p["id"], "connection reset", partial="The first risk is customer concentration,")
    rows = _msgs(cid)
    assert rows[-1][0] == "assistant"
    assert "customer concentration" in rows[-1][1]          # the half that was written is kept
    assert "did not finish" in rows[-1][1]                  # and it can never be mistaken for a finished answer


def test_a_failure_with_no_text_still_says_what_happened(fresh):
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    db.save_message(cid, "user", "q", project_id=p["id"], title="q")
    qa.save_failure(cid, p["id"], "budget paused")
    assert "budget paused" in _msgs(cid)[-1][1]


def test_the_question_is_never_saved_twice(fresh):
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    out = qa.ask("what do we know about seller financing?", project_id=p["id"], conversation_id=cid)
    assert out["answer"]
    roles = [r for r, _ in _msgs(cid)]
    assert roles.count("user") == 1 and roles.count("assistant") == 1


def test_a_link_only_message_also_saves_once(fresh):
    p = db.create_project("chat", brief="b")
    cid = db.new_id()
    qa.ask("https://example.com/x", project_id=p["id"], conversation_id=cid)
    assert [r for r, _ in _msgs(cid)].count("user") == 1


# ------------------------------------------------------------------ a source that left is not an error

def _source(sid):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (sid, "youtube", sid, f"https://y/{sid}", "t", "proposed", 1.0, 1.0))


def test_an_analysis_for_a_vanished_source_is_skipped_not_raised(fresh):
    p = db.create_project("rank", brief="b")
    _source("s1")
    db.set_relevance("s1", 4, "fits", project_id=p["id"])              # normal write
    assert db.project_analysis(p["id"], "relevance").get("s1")
    with db.tx() as conn:
        conn.execute("DELETE FROM sources WHERE id='s1'")
    db.set_relevance("s1", 5, "fits even better", project_id=p["id"])  # would have raised FOREIGN KEY


def test_an_analysis_for_a_vanished_project_is_skipped_too(fresh):
    p = db.create_project("gone", brief="b")
    _source("s2")
    with db.tx() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (p["id"],))
    db.set_relevance("s2", 3, "why", project_id=p["id"])


def test_one_vanished_source_no_longer_voids_the_batch(fresh):
    """The actual damage: the writes share one transaction, so a single dangling row discarded minutes of ranking."""
    p = db.create_project("rank", brief="b")
    for sid in ("a", "b", "c"):
        _source(sid)
    with db.tx() as conn:
        conn.execute("DELETE FROM sources WHERE id='b'")
    with db.batch():
        for sid in ("a", "b", "c"):
            db.set_relevance(sid, 4, "fits", project_id=p["id"])
    got = db.project_analysis(p["id"], "relevance")
    assert set(got) == {"a", "c"}                           # b left; a and c were still ranked


def test_writable_is_the_explicit_question(fresh):
    p = db.create_project("rank", brief="b")
    _source("s3")
    assert db.analysis_writable(p["id"], "s3") is True
    assert db.analysis_writable(p["id"], "nope") is False
    assert db.analysis_writable("nope", "s3") is False


def test_the_review_note_says_how_many_left(fresh, monkeypatch):
    from neurosearch import relevance
    p = db.create_project("rank", brief="buying businesses")
    coll = db.upsert_collection("youtube_channel", "c1", "https://y/c", "A channel")
    for sid in ("k1", "k2"):
        _source(sid)
        db.link_source_collection(sid, coll["id"])
    # the real sequence: the rows are READ, then a source is deleted while the ranking runs, then the writes land.
    # `_pool` is called after the read, so deleting there reproduces it exactly.
    def pool_then_delete(rows, *_a, **_k):
        with db.tx() as conn:
            conn.execute("DELETE FROM sources WHERE id='k2'")
        return rows, []
    monkeypatch.setattr(relevance, "_pool", pool_then_delete)
    relevance.rank_collection(coll["id"], p["id"])
    note = (db.review_meta(coll["id"]) or {}).get("rank_note") or ""
    assert "removed while this was ranking" in note
