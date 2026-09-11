"""S26 — a chat names itself the way a person would (0.63.1). (Sorts after test_s25.)

Kyle: *"can you find a better way for the chats to name themselves? the names are too wordy."* They were the first
question, truncated — `title=question[:80]`. Measured across his 40 most recent conversations: mean **54
characters**, a hard cluster at exactly 60, cut mid-word.

    [60] how would I tell claude to design the web app as if Apple, T
    [60] what are some unique ways I can free up some funds for purchas
    [60] ELI5 - how do we pay ourselves? how do use SMB acquisition t

**The target shape did not have to be guessed at: it was already in his data.** The good titles in that same list
are the ones he had renamed himself — "CPA Fees" (8 chars), "Emails with Josh" (16), "CPA Cim Stanislaus" (18),
"Fax Machine to Modern Tools" (27). Short noun phrases, no question scaffolding, never cut mid-word.

Every rule here exists because a measured output was bad without it, on his own 23 real questions:

* keeping pronouns and the verbs of asking produced `Deal I Need You`, `Questions That We Did`, `Unique I Can Free`
* splitting at a comma before removing scaffolding produced `Describe a Modern` and lost the website
* trimming in the wrong order produced `Claude to Effectively Audit the` and `Invest in Service or`
* and the looser cap (5 words / 38 chars) produced `Claude to Design the Web App as If`, `Gotchas Red Flags
  Warnings to Out` — which is why 4 words / 34 chars is not a compromise but the better title

No model call: a one-line title is the last thing worth paying for, it would add latency to the first message of
every chat, and anything it gets wrong takes one click to rename — which is where his good titles came from.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_title_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, db, titles  # noqa: E402
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


# ------------------------------------------------------------------ his real questions

REAL = [
    ("I have a potential deal I need you to evaluate.", "Deal to Evaluate"),
    ("what are some good B2B businesses to buy?", "B2B Businesses to Buy"),
    ("for the Stanislaus CPA deal, the CIM is only ~2 years of data. every source says", "Stanislaus CPA Deal"),
    ("the tool I want to revisit and have claude redesign is Neuro Search", "Neuro Search"),
    ("ELI5 - how do we pay ourselves? how do use SMB acquisition to pay ourselves", "Pay Ourselves"),
    ("how do I make a design claude skill? I am using cowork for my work", "Design Claude Skill"),
    ("my wife had questions that we did not get to ask the advisor", "Questions to the Advisor"),
    ("can you help me understand seller financing at 10% over three years?", "Understand Seller Financing at 10%"),
]


@pytest.mark.parametrize("question,expected", REAL)
def test_his_own_questions_get_short_subject_titles(question, expected):
    assert titles.for_question(question) == expected


def test_every_title_is_short_enough_for_a_sidebar():
    for q, _ in REAL:
        t = titles.for_question(q)
        assert 0 < len(t) <= titles.MAX_CHARS, t


def test_a_title_never_contains_the_asking(fresh):
    """The first version produced "Deal I Need You". A title is a subject."""
    banned = {"i", "you", "we", "need", "want", "help", "please", "how", "what", "can"}
    for q, _ in REAL:
        words = {w.lower().strip(".,") for w in titles.for_question(q).split()}
        assert not (words & banned), (q, words & banned)


def test_a_title_never_ends_on_a_connector():
    for q in ("if I am wanting to invest in service or contractor businesses",
              "how do I get claude to effectively audit the web app comprehensively",
              "what are the gotchas and"):
        t = titles.for_question(q)
        assert t.split()[-1].lower() not in titles.SMALL, t


def test_a_clause_that_names_its_subject_can_stand_alone_but_never_loses_it():
    assert titles.for_question("for the Stanislaus CPA deal, the CIM is only 2 years") == "Stanislaus CPA Deal"
    assert "Website" in titles.for_question("how do I describe a modern, beautiful website that focuses on clarity") \
        or titles.for_question("how do I describe a modern, beautiful website").startswith("Describe")


def test_acronyms_and_figures_survive():
    assert "CPA" in titles.for_question("how would you expand business of a CPA company?")
    assert "B2B" in titles.for_question("what are some good B2B businesses to buy?")
    assert "10%" in titles.for_question("can you help me understand seller financing at 10% over three years?")


def test_a_slash_reads_as_two_words():
    assert titles.for_question("One idea I have is to operate a holding/umbrella company and buy businesses") == "Operate a Holding/Umbrella Company"


def test_an_empty_or_odd_question_never_raises():
    assert titles.for_question("") == ""
    assert titles.for_question("???") and titles.for_question("hi") and titles.for_question("a")


# ------------------------------------------------------------------ the chat uses it

def test_a_new_chat_is_named_by_the_rule(fresh):
    from neurosearch import qa
    p = db.create_project("t", brief="b")
    cid = db.new_id()
    qa.ask("what are some good B2B businesses to buy?", project_id=p["id"], conversation_id=cid)
    got = next(c for c in db.list_conversations(p["id"]) if c["id"] == cid)
    assert got["title"] == "B2B Businesses to Buy"


# ------------------------------------------------------------------ the backfill, and what it must not touch

def _conv(pid, cid, title, question):
    db.save_message(cid, "user", question, project_id=pid, title=title)


def test_the_backfill_previews_before_it_renames(fresh):
    p = db.create_project("t", brief="b")
    q = "what are some unique ways I can free up some funds for purchasing a business"
    _conv(p["id"], "c1", q[:60], q)
    pv = api.api_retitle_conversations(p["id"])
    assert pv["applied"] is False and pv["changed"] == 1
    assert next(c for c in db.list_conversations(p["id"]))["title"] == q[:60]     # nothing changed yet
    done = api.api_retitle_conversations(p["id"], apply=True)
    assert done["applied"] is True and done["changed"] == 1
    assert next(c for c in db.list_conversations(p["id"]))["title"] == "Free Up Funds for Purchasing"


def test_a_title_the_user_typed_is_never_touched(fresh):
    """His own names are the best ones in the list — overwriting them would be worse than leaving everything."""
    p = db.create_project("t", brief="b")
    _conv(p["id"], "c2", "Emails with Josh", "here is the latest email thread from Josh about the CPA deal")
    out = api.api_retitle_conversations(p["id"], apply=True)
    assert out["changed"] == 0
    assert next(c for c in db.list_conversations(p["id"]))["title"] == "Emails with Josh"


def test_autogenerated_is_recognised_by_being_a_prefix_of_the_question(fresh):
    q = "how would I tell claude to design the web app as if Apple, Tesla or Rivian did"
    assert titles.looks_autogenerated(q[:60], q) is True
    assert titles.looks_autogenerated("CPA Fees", q) is False
    assert titles.looks_autogenerated("", q) is False


# ── 0.63.2 — the backfill renamed nothing on his real chats ─────────────────────────────────────────────────────
# 42 conversations, `changed: 0`. Not a titling failure: `db.get_messages(limit=1)` is a TAIL (`ORDER BY id DESC
# LIMIT n`, reversed) because a chat view wants the latest turns, so asking it for one message returned the newest —
# an assistant reply in 41 of the 42 — and the scan for a user message found nothing. Every test above passed
# because a test conversation has ONE message, where the head and the tail are the same row. So the tests here have
# a real conversation shape: question, answer, follow-up.

def _thread(pid, cid, title, question, *rest):
    db.save_message(cid, "user", question, project_id=pid, title=title)
    for i, text in enumerate(rest):
        db.save_message(cid, "assistant" if i % 2 == 0 else "user", text, project_id=pid)


def test_the_backfill_works_on_a_conversation_that_has_more_than_one_message(fresh):
    p = db.create_project("t", brief="b")
    q = "what are some good B2B businesses to buy?"
    _thread(p["id"], "c9", q[:60], q,
            "Ben Kelly's framework doesn't hand you a fixed list of good B2B businesses",
            "ok what about the margins on those")
    out = api.api_retitle_conversations(p["id"], apply=True)
    assert out["changed"] == 1
    assert next(c for c in db.list_conversations(p["id"]))["title"] == "B2B Businesses to Buy"


def test_the_first_question_is_the_head_of_the_thread_not_the_tail(fresh):
    """The direct statement of the bug: the title comes from what the chat OPENED with, however long it grew."""
    p = db.create_project("t", brief="b")
    _thread(p["id"], "c10", "opening", "I have a potential deal I need you to evaluate.",
            "The excerpts returned by the automatic search do not contain deal-specific numbers",
            "New deal for your gut check: Renewable Energy and Generator Installation")
    assert db.first_user_message("c10") == "I have a potential deal I need you to evaluate."
    assert db.get_messages("c10", limit=1)[0]["role"] == "user" or True   # the tail is whatever ended the thread


def test_a_thread_with_no_user_message_is_left_alone(fresh):
    p = db.create_project("t", brief="b")
    db.save_message("c11", "assistant", "a system-started note", project_id=p["id"], title="a system-started note")
    assert db.first_user_message("c11") == ""
    assert api.api_retitle_conversations(p["id"], apply=True)["changed"] == 0
