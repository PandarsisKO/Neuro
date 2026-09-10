"""S10 — the plain share (0.60.0). (Sorts after test_s9.)

Kyle: *"our chats are really good for depth and citing sources for ease of finding more information quickly. but
when I want to share with my wife or a friend, they will not care about the sources, the names of the people and
what they said. we need a cleaner more human feeling summary ability (without the feedback that chat currently
gives like 'thats a great question')."*

That is a different READER, not a shorter answer, and the distinction is what these tests hold. The cited variants
(C0, 0.35.1) are written for someone who might go and check: markers stay, and the client re-attaches the source
list. A plain one is written for someone who wants to know the thing: no markers, no creators' names, none of the
vocabulary that gives an answer its provenance.

The one thing it may not do is launder the uncertainty. Stripping the machinery makes a text message sound settled
for free, so if the original hedged and the retelling does not, that is reported rather than shipped quietly.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_plain_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, fake_ai, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402

ANSWER = ("The SBA requires at least a 10 percent equity injection on a change-of-ownership loan [1]. A seller note can "
          "count toward it only when it is on full standby for the life of the loan [2]. Several owners report that "
          "first-year software costs ran well over the seller's numbers [3]. One broker disputes this, calling the "
          "migration story overblown [4].")
CITES = [{"n": 1, "title": "SOP 50 10 8", "channel": "U.S. Small Business Administration", "timestamp": "p. 112"},
         {"n": 2, "title": "SOP 50 10 8", "channel": "U.S. Small Business Administration", "timestamp": "p. 114"},
         {"n": 3, "title": "How I bought a laundromat", "channel": "Codie Sanchez", "timestamp": "14:20"},
         {"n": 4, "title": "Broker blog", "channel": "Quiet Light Brokerage", "timestamp": "§ 1"}]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    for v in ("NEUROSEARCH_FAKE_PLAIN_LEAK", "NEUROSEARCH_FAKE_SHARE_STRAY"):
        monkeypatch.delenv(v, raising=False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    yield
    db._local.conn = None


def _calls() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task='answer.share'").fetchone()[0]


# ------------------------------------------------------------------ what plain mode removes

def test_a_plain_version_carries_no_citation_markers():
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    assert v["mode"] == "plain" and v["text"]
    assert "[1]" not in v["text"] and "[" not in v["text"]
    assert v["markers"] == [] and v["sources_attached"] is False


def test_a_plain_version_names_nobody():
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    for name in ("Codie Sanchez", "Quiet Light Brokerage", "SOP 50 10 8", "How I bought a laundromat"):
        assert name.lower() not in v["text"].lower()
    assert v["leaks"]["names"] == []


def test_the_forbidden_list_is_provenance_and_never_substance():
    """A creator is where the answer came from; an institution the answer is ABOUT has to survive, or the plain
    version stops being true. The list is built from the citations' own fields for exactly this reason."""
    forbidden = qa._plain_forbidden(CITES)
    assert "Codie Sanchez" in forbidden and "Quiet Light Brokerage" in forbidden
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    assert "sba" in v["text"].lower() or "small business administration" in v["text"].lower() or "10 percent" in v["text"]


def test_the_default_mode_is_unchanged():
    """C0's behaviour is the default and must not move: markers kept, sources re-attached by the client."""
    v = qa.share_variant(ANSWER, CITES, "short")
    assert v["mode"] == "cited" and v["sources_attached"] is True and v["markers"] == [1, 2]


def test_an_unknown_mode_is_refused_before_anything_is_spent():
    with pytest.raises(ValueError):
        qa.share_variant(ANSWER, CITES, "short", mode="friendly")
    assert _calls() == 0


def test_the_long_length_exists_for_both_modes():
    assert "long" in qa.SHARE_LENGTHS
    plain = qa.share_variant(ANSWER, CITES, "long", mode="plain")
    cited = qa.share_variant(ANSWER, CITES, "long")
    assert plain["length"] == cited["length"] == "long"


# ------------------------------------------------------------------ the checks, and the one retry

def test_a_leaked_name_triggers_exactly_one_corrective_retry(monkeypatch):
    """The two things this rewrite is FOR — losing the names and losing the markers — are the two a model drops
    back into by habit. One more cheap call is a better answer than a version Kyle has to hand-edit."""
    monkeypatch.setenv("NEUROSEARCH_FAKE_PLAIN_LEAK", "name")
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    assert v["retried"] is True
    assert v["leaks"]["names"] == [] and v["warning"] is None
    assert _calls() == 2


def test_research_vocabulary_is_checked_not_merely_requested(monkeypatch):
    """'According to the transcript' is the tell that gives a retelling away. A rule in a prompt is a hope."""
    monkeypatch.setenv("NEUROSEARCH_FAKE_PLAIN_LEAK", "tell")
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    assert v["retried"] is True and v["leaks"]["tells"] == []
    assert "according to" not in v["text"].lower()


def test_a_marker_is_stripped_even_if_the_retry_leaves_one(monkeypatch):
    """A marker can be cut out of a sentence without breaking it; a name cannot. So markers are removed outright
    and names are only ever reported."""
    monkeypatch.setenv("NEUROSEARCH_FAKE_PLAIN_LEAK", "marker")
    v = qa.share_variant(ANSWER, CITES, "short", mode="plain")
    assert "[3]" not in v["text"] and v["leaks"]["markers"] == []


def test_uncertainty_that_does_not_survive_is_reported():
    """The failure this guards against is silent and one-directional: lose the caveat and a text message reads as
    settled fact. It needs no simulating — the original's disagreement lives in its fourth sentence, so a 2–3
    sentence retelling drops it, and that is precisely when the user should be sent to the cited version."""
    v = qa.share_variant(ANSWER, CITES, "short", mode="plain")
    assert v["warning"] and "reads as settled" in v["warning"] and "cited version" in v["warning"]


def test_a_retelling_that_keeps_the_disagreement_is_not_warned_about():
    """The same original at a length that has room for the caveat: no warning. A warning that fires either way
    teaches people to ignore it."""
    v = qa.share_variant(ANSWER, CITES, "medium", mode="plain")
    assert v["warning"] is None and qa._hedged(v["text"]) is True


def test_a_condition_is_not_doubt():
    """"only when it is on full standby" is structure, not hedging. Counting it would fire the warning on
    retellings that lost nothing."""
    assert qa._hedged("it counts only when it is on full standby") is False
    assert qa._hedged("several owners report higher costs", research=True) is False


def test_an_original_with_nothing_to_hedge_is_not_warned_about():
    flat = "The equity injection is 10 percent."
    v = qa.share_variant(flat, [], "short", mode="plain")
    assert v["warning"] is None


def test_the_hedge_check_reads_ordinary_language_not_research_vocabulary():
    """The plain prompt asks for "this part isn't settled" rather than "one source", so the hedge detector has to
    recognise the words it asked for."""
    assert qa._hedged("this part isn't settled yet") is True
    assert qa._hedged("people disagree about how much it costs") is True
    assert qa._hedged("it is ten percent, full stop") is False


# ------------------------------------------------------------------ a whole conversation

def _chat_with(project_id, turns):
    c = db.create_conversation(project_id, "SBA questions")
    for role, text, cites in turns:
        db.save_message(c["id"], role, text, cites)
    return c["id"]


def test_a_whole_chat_is_retold_as_one_piece():
    p = db.create_project("share", brief="buying a business")
    cid = _chat_with(p["id"], [("user", "How much do I have to put in?", None),
                               ("assistant", ANSWER, CITES),
                               ("user", "And the seller note?", None),
                               ("assistant", "A seller note counts only on full standby [2].", CITES[1:2])])
    v = qa.share_conversation(cid, "long")
    assert v["mode"] == "plain" and v["text"] and "[" not in v["text"]
    assert v["covered"]["messages"] == 4 and v["covered"]["of_messages"] == 4
    assert v["covered"]["truncated"] is False
    assert _calls() == 1                        # one call over what was already written — never a research pass


def test_retelling_a_chat_can_also_keep_the_sources():
    p = db.create_project("share2", brief="buying a business")
    cid = _chat_with(p["id"], [("assistant", ANSWER, CITES)])
    v = qa.share_conversation(cid, "long", mode="cited")
    assert v["mode"] == "cited" and v["sources_attached"] is True


def test_an_empty_chat_is_refused_rather_than_summarised():
    p = db.create_project("share3", brief="x")
    cid = _chat_with(p["id"], [])
    with pytest.raises(ValueError):
        qa.share_conversation(cid)
    assert _calls() == 0


def test_a_long_chat_keeps_the_newest_turns_and_says_it_truncated(monkeypatch):
    """A retelling that quietly covers half a conversation is the kind of thing someone forwards, so the share of
    the chat it actually read is part of the result."""
    monkeypatch.setattr(qa, "SHARE_CONVERSATION_MAX_MESSAGES", 4)
    p = db.create_project("share4", brief="x")
    cid = _chat_with(p["id"], [("assistant", f"Point number {i} about the equity injection.", None) for i in range(12)])
    mat = qa.conversation_material(cid)
    assert mat["messages"] == 4 and mat["of_messages"] == 12 and mat["truncated"] is True
    assert "Point number 11" in mat["text"] and "Point number 0" not in mat["text"]
    v = qa.share_conversation(cid)
    assert "most recent 4 of 12" in v["warning"]


def test_a_chars_budget_also_bounds_the_material(monkeypatch):
    monkeypatch.setattr(qa, "SHARE_CONVERSATION_CHARS", 120)
    p = db.create_project("share5", brief="x")
    cid = _chat_with(p["id"], [("assistant", "y" * 100, None) for _ in range(5)])
    mat = qa.conversation_material(cid)
    assert mat["messages"] == 1 and mat["truncated"] is True and mat["chars"] <= 120


def test_the_conversation_material_is_only_what_was_already_written():
    """No retrieval, no tools, no new excerpts: a retelling can restate what the chat established and nothing else."""
    p = db.create_project("share6", brief="x")
    cid = _chat_with(p["id"], [("user", "q", None), ("assistant", "a", None)])
    mat = qa.conversation_material(cid)
    assert mat["text"] == "QUESTION: q\n\nANSWER: a"


# ------------------------------------------------------------------ the chat itself stops praising the question

def test_the_chat_prompt_forbids_opening_praise():
    """Kyle asked for this twice — once about me and once about the app. The plain rewrite drops a preamble after
    the fact; this stops it being written."""
    assert "great question" in qa.SYSTEM
    assert "Open with the answer" in qa.SYSTEM
    assert "never announce what you are about to do" in qa.SYSTEM
