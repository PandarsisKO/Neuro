"""0.30.3 — Chat must never silently return a model response whose stop reason says the generation was incomplete
(a production symptom: answers ending mid-sentence). Frozen regressions: (1) stop_reason=max_tokens → automatic
continuation → one complete message with the final sentence and no duplicated transition text; (2) text + tool_use in
one response → the tool runs and the FINAL text is the answer, not the pre-tool fragment; (3) the loop can never end on
a dangling tool_use. (Sorts after test_core.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_k7_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

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


def test_max_tokens_triggers_a_continuation_and_one_complete_message(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TRUNCATE", "1")
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    seen = []
    monkeypatch.setattr(qa, "OBSERVER", lambda rec: seen.append(rec))
    res = qa.ask("Give me a long, multi-section explanation of the whole SBA acquisition process.", project_id=pid, conversation_id=conv)
    answer = res["answer"]
    assert answer.endswith("ends here, complete.")                         # the final sentence made it
    assert "[Answer cut short" not in answer
    assert answer.count("ends here, complete.") == 1
    # no duplicated transition text where the two halves were spliced
    words = answer.split()
    assert not any(words[i:i + 4] == words[i + 4:i + 8] for i in range(len(words) - 8))
    assert [r["stop_reason"] for r in seen] == ["max_tokens", "end_turn"]
    stored = [m for m in db.get_messages(conv) if m["role"] == "assistant"]
    assert len(stored) == 1 and stored[0]["content"] == answer                # persisted = returned, one message
    g = (stored[0].get("meta") or {}).get("generation") or {}
    assert g["continuations"] == 1 and g["incomplete"] is False and g["last_stop_reason"] == "end_turn" and g["output_tokens"] > 2000
    assert int(db.kv_get("chat:continuations") or 0) >= 1


def test_text_plus_tool_use_returns_the_final_answer_not_the_fragment(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TEXT_THEN_TOOL", "1")
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("What should I do about the seller note?", project_id=pid, conversation_id=conv)
    assert res["answer"].endswith("FINAL: the complete answer after the tool call.")
    assert any(a["type"] == "fact_recorded" for a in res["actions"])         # the tool ran
    assert "most important point is" in res["answer"]                       # the pre-tool text is kept, and followed by the final text
    stored = [m for m in db.get_messages(conv) if m["role"] == "assistant"][0]
    assert stored["content"] == res["answer"]


def test_continuation_limit_marks_the_answer_incomplete_instead_of_pretending(monkeypatch):
    """A response that keeps hitting max_tokens is capped after CONTINUATIONS_MAX rounds and SAYS it is incomplete —
    it is never returned as if it were whole."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    from neurosearch import providers
    calls = {"n": 0}
    real = providers.invoke

    def always_truncated(task, **kw):
        if task != "answer.chat":
            return real(task, **kw)
        calls["n"] += 1
        return fake_ai._Blk(stop_reason="max_tokens", model="fake-claude", content=[fake_ai._Blk(type="text", text=f"part {calls['n']} of a very long answer that never", citations=None)],
                            usage=fake_ai._Blk(input_tokens=10, output_tokens=4000, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
    monkeypatch.setattr(providers, "invoke", always_truncated)
    res = qa.ask("Write everything.", project_id=pid, conversation_id=conv)
    assert calls["n"] == 1 + qa.CONTINUATIONS_MAX
    assert "[Answer cut short" in res["answer"] and "part 3" in res["answer"]
    stored = [m for m in db.get_messages(conv) if m["role"] == "assistant"][0]
    assert (stored.get("meta") or {}).get("generation", {}).get("incomplete") is True
    assert "incomplete" in ((stored.get("meta") or {}).get("warning") or "")


def test_tool_loop_never_ends_on_a_dangling_tool_use(monkeypatch):
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    from neurosearch import providers
    calls = []
    real = providers.invoke

    def tool_hungry(task, **kw):
        if task != "answer.chat":
            return real(task, **kw)
        calls.append(bool(kw.get("tools")))
        if kw.get("tools"):
            return fake_ai._Blk(stop_reason="tool_use", model="fake-claude",
                                content=[fake_ai._Blk(type="tool_use", id=f"toolu_{len(calls)}", name="list_sources", input={})],
                                usage=fake_ai._Blk(input_tokens=10, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
        return fake_ai._Blk(stop_reason="end_turn", model="fake-claude", content=[fake_ai._Blk(type="text", text="Here is the answer in text.", citations=None)],
                            usage=fake_ai._Blk(input_tokens=10, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0, server_tool_use=None))
    monkeypatch.setattr(providers, "invoke", tool_hungry)
    res = qa.ask("List everything.", project_id=pid, conversation_id=conv)
    assert res["answer"] == "Here is the answer in text."
    assert calls == [True] * qa.MAX_TOOL_ROUNDS + [False]                    # six tool rounds, then one forced text round


def test_join_continuation_drops_repeated_overlap_and_keeps_mid_sentence_flow():
    assert qa._join_continuation("the seller note must be on full stand", "by for the life of the loan.") == "the seller note must be on full standby for the life of the loan."
    assert qa._join_continuation("Lenders usually require the note", "usually require the note to be subordinated.") == "Lenders usually require the note to be subordinated."
    assert qa._join_continuation("First point.", "Second point.") == "First point. Second point."
    assert qa._join_continuation("the note must be", " subordinated to the loan.") == "the note must be subordinated to the loan."
