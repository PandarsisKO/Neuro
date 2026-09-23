"""S84: a conversation saved from an outside AI lands in the project's Chats (Kyle, 2026-09-22).

"chats from ChatGPT should just land in chats... naturally." Each successful sync_conversation_to_project also writes
one readable message into a Neuro chat: one chat per outside conversation (same conversation_ref → same chat), what was
decided with the person's own words, what waits for review, the material read, the outside AI's reading labelled as
not evidence. The mirror is a courtesy on a committed save: its failure never fails the save.
"""
from __future__ import annotations

import pytest

from neurosearch import access, chat_mirror, db, jobs
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
    acq = db.create_project("Business Acquisition", "buy an HVAC business; seller note, SBA loan, transition")["id"]
    c = access.create_client("Kyle's ChatGPT", transport="tunnel")["id"]
    _, s = access.issue_credential("kyle", c)
    access.grant(acq, "kyle", "contribute")
    return {"s": s, "acq": acq}


def sync(client, s, sel="named", **args):
    if sel == "named" and "project_id" in args and "project_selection" not in args:
        args["project_selection"] = {"basis": "user_named", "user_text": "save it to the acquisition project"}
    r = client.post("/api/ext/v1/sync_conversation_to_project", json=args, headers={"Authorization": f"Bearer {s}"})
    return r.status_code, r.json()


FREEFLOW_STATE = [
    {"op": "record", "kind": "decision", "content": "Offer a 10% seller note", "user_text": "OK, let's offer a 10% seller note."},
    {"op": "record", "kind": "open_question", "content": "Will the SBA lender accept a standby seller note?",
     "user_text": "I don't know if the SBA lender will take a standby note."},
    {"op": "propose", "kind": "concern", "content": "Seller may walk if pushed on transition length"},
    {"op": "record", "kind": "context", "content": "Make it shorter"},
]


def _chat(pid):
    convs = [c for c in db.list_conversations(pid) if c["id"].startswith("ext-")]
    return convs


def test_a_save_lands_in_the_projects_chats_readably(client, kyle):
    _, env = sync(client, kyle["s"], client_request_id="chat-0001", project_id=kyle["acq"], conversation_ref="gpt-conv-A",
                  state=FREEFLOW_STATE,
                  materials=[{"material_type": "text", "title": "Seller P&L summary", "producer": "ChatGPT", "extraction_method": "manual",
                              "units": [{"locator": "p. 1", "text": "Revenue 1.2M"}]}],
                  analysis=[{"text": "The seller note looks negotiable."}])
    d = env["data"]
    assert d["saved"] and d["neuro_chat_id"].startswith("ext-")
    convs = _chat(kyle["acq"])
    assert len(convs) == 1 and convs[0]["title"].startswith("ChatGPT · ")
    [m] = db.get_messages(convs[0]["id"])
    assert m["role"] == "assistant" and m["meta"]["kind"] == "external_sync" and m["meta"]["client"] == "ChatGPT"
    t = m["content"]
    assert t.startswith("**Saved from ChatGPT**")
    assert "**Decided**" in t and "Offer a 10% seller note" in t and "you said: “OK, let's offer a 10% seller note.”" in t
    assert "**Still open**" in t and "**Waiting for your review**" in t and "(suggested by ChatGPT)" in t
    assert "**Material ChatGPT read**" in t and "Seller P&L summary (1 part)" in t
    assert "own reading** (kept apart, not evidence)" in t and "negotiable" in t
    assert "Make it shorter" not in t                                  # presentation chatter never reaches the chat


def test_a_second_save_from_the_same_conversation_appends_to_the_same_chat(client, kyle):
    sync(client, kyle["s"], client_request_id="chat-0002", project_id=kyle["acq"], conversation_ref="gpt-conv-B",
         state=[{"op": "record", "kind": "decision", "content": "Offer 10%", "user_text": "Offer 10%."}])
    sync(client, kyle["s"], client_request_id="chat-0003", project_id=kyle["acq"], conversation_ref="gpt-conv-B",
         project_selection={"basis": "previously_confirmed"},
         state=[{"op": "record", "kind": "deadline", "content": "LOI due Friday", "user_text": "LOI is due Friday."}])
    convs = _chat(kyle["acq"])
    assert len(convs) == 1 and len(db.get_messages(convs[0]["id"])) == 2
    sync(client, kyle["s"], client_request_id="chat-0004", project_id=kyle["acq"], conversation_ref="gpt-conv-C",
         state=[{"op": "record", "kind": "context", "content": "Broker is Sunbelt", "user_text": "The broker is Sunbelt."}])
    assert len(_chat(kyle["acq"])) == 2


def test_a_replayed_save_does_not_duplicate_the_chat_message(client, kyle):
    args = dict(client_request_id="chat-0005", project_id=kyle["acq"], conversation_ref="gpt-conv-D",
                state=[{"op": "record", "kind": "decision", "content": "Offer 12%", "user_text": "Offer 12%."}])
    sync(client, kyle["s"], **args)
    _, env = sync(client, kyle["s"], **args)
    assert env["data"].get("idempotent_replay")
    [c] = _chat(kyle["acq"])
    assert len(db.get_messages(c["id"])) == 1


def test_nothing_is_mirrored_when_the_project_was_not_chosen(client, kyle):
    _, env = sync(client, kyle["s"], sel=None, client_request_id="chat-0006", project_hint="Business Acquisition",
                  state=[{"op": "record", "kind": "decision", "content": "Offer 10%", "user_text": "Offer 10%."}])
    assert env["data"]["status"] in ("confirm_project", "needs_project")
    assert not _chat(kyle["acq"])


def test_a_mirror_failure_never_fails_the_save(client, kyle, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(db, "save_message", boom)
    _, env = sync(client, kyle["s"], client_request_id="chat-0007", project_id=kyle["acq"],
                  state=[{"op": "record", "kind": "decision", "content": "Offer 11%", "user_text": "Offer 11%."}])
    assert env["data"]["saved"] and "neuro_chat_id" not in env["data"]


def test_app_names():
    assert chat_mirror.app_name("Kyle's ChatGPT") == "ChatGPT" and chat_mirror.app_name("Claude") == "Claude"
    assert chat_mirror.app_name("") == "an AI app"


def test_backfill_gives_past_saves_their_chat_once(client, kyle):
    sync(client, kyle["s"], client_request_id="chat-0010", project_id=kyle["acq"], conversation_ref="gpt-conv-E",
         state=[{"op": "record", "kind": "context", "content": "Lender said 90% of SBA loans get denied",
                 "user_text": "The lender told me 90% of SBA loans get denied."}],
         materials=[{"material_type": "text", "title": "Lender call notes", "producer": "ChatGPT", "extraction_method": "manual",
                     "units": [{"locator": "msg:1", "text": "90% denied"}]}],
         analysis=[{"text": "Worth checking against SBA data."}])
    for c in _chat(kyle["acq"]):                       # simulate a save made before chat mirroring existed
        db.delete_conversation(c["id"])
    assert not _chat(kyle["acq"])
    assert chat_mirror.backfill() == 1
    [c] = _chat(kyle["acq"])
    [m] = db.get_messages(c["id"])
    assert "Lender said 90% of SBA loans get denied" in m["content"] and "Lender call notes" in m["content"]
    assert "Worth checking against SBA data." in m["content"]
    assert chat_mirror.backfill() == 0                 # idempotent


CONVO_1 = "User: What does an SBA 7(a) loan cost?\nChatGPT: Roughly prime plus 2.75%, with a 10% equity injection.\nUser: And private credit?\nChatGPT: Faster, but usually 10–14%."
CONVO_2 = CONVO_1 + "\nUser: OK, we'll go SBA first.\nChatGPT: Sensible — start the lender list this week."


def _roles(cid):
    return [(m["role"], (m["meta"] or {}).get("kind")) for m in db.get_messages(cid, limit=100)]


def test_the_conversation_itself_shows_as_real_turns_then_the_summary(client, kyle):
    _, env = sync(client, kyle["s"], client_request_id="chat-0020", project_id=kyle["acq"], conversation_ref="gpt-conv-T",
                  state=[{"op": "record", "kind": "decision", "content": "Pursue SBA first", "user_text": "OK, we'll go SBA first."}],
                  archive_transcript={"text": CONVO_1, "explicit_user_request": True})
    cid = env["data"]["neuro_chat_id"]
    assert _roles(cid) == [("user", "external_transcript"), ("assistant", "external_transcript"),
                           ("user", "external_transcript"), ("assistant", "external_transcript"), ("assistant", "external_sync")]
    ms = db.get_messages(cid, limit=100)
    assert ms[0]["content"] == "What does an SBA 7(a) loan cost?" and ms[3]["content"] == "Faster, but usually 10–14%."
    assert "Full conversation** shown above" in ms[-1]["content"] and "Conversation archive" not in ms[-1]["content"]
    assert db.list_conversations(kyle["acq"])[0]["title"] == "ChatGPT · What does an SBA 7(a) loan cost?"


def test_a_later_archive_of_the_same_conversation_adds_only_the_new_turns(client, kyle):
    sync(client, kyle["s"], client_request_id="chat-0021", project_id=kyle["acq"], conversation_ref="gpt-conv-U",
         archive_transcript={"text": CONVO_1, "explicit_user_request": True})
    _, env = sync(client, kyle["s"], client_request_id="chat-0022", project_id=kyle["acq"], conversation_ref="gpt-conv-U",
                  project_selection={"basis": "previously_confirmed"}, archive_transcript={"text": CONVO_2, "explicit_user_request": True})
    turns = [m for m in db.get_messages(env["data"]["neuro_chat_id"], limit=100) if (m["meta"] or {}).get("kind") == "external_transcript"]
    assert len(turns) == 6 and turns[-2]["content"] == "OK, we'll go SBA first."


def test_an_unlabelled_transcript_is_shown_once_whole(client, kyle):
    for n in ("chat-0023", "chat-0024"):
        _, env = sync(client, kyle["s"], client_request_id=n, project_id=kyle["acq"], conversation_ref="gpt-conv-V",
                      project_selection={"basis": "user_named", "user_text": "save it to the acquisition project"},
                      archive_transcript={"text": "notes without any speaker labels at all", "explicit_user_request": True})
    whole = [m for m in db.get_messages(env["data"]["neuro_chat_id"], limit=100) if (m["meta"] or {}).get("kind") == "external_transcript"]
    assert len(whole) == 1 and whole[0]["content"].startswith("**Full conversation from ChatGPT**")


def test_parse_turns_handles_common_labels():
    t = chat_mirror.parse_turns("You said:\nhi there\n\nChatGPT said:\nhello\n**You:** next\n**ChatGPT:** ok")
    assert t == [("user", "hi there"), ("assistant", "hello"), ("user", "next"), ("assistant", "ok")]
    assert chat_mirror.parse_turns("just one block of text") is None


def test_backfill_rebuilds_an_earlier_mirror_so_the_conversation_appears(client, kyle):
    _, env = sync(client, kyle["s"], client_request_id="chat-0025", project_id=kyle["acq"], conversation_ref="gpt-conv-W",
                  archive_transcript={"text": CONVO_1, "explicit_user_request": True})
    cid = env["data"]["neuro_chat_id"]
    with db.tx() as conn:                              # simulate the pre-transcript mirror: summary only
        conn.execute("DELETE FROM messages WHERE conversation_id=? AND meta LIKE '%external_transcript%'", (cid,))
    assert [k for _, k in _roles(cid)] == ["external_sync"]
    chat_mirror.backfill()
    [c] = [x for x in db.list_conversations(kyle["acq"]) if x["id"].startswith("ext-")]
    assert [k for _, k in _roles(c["id"])].count("external_transcript") == 4
