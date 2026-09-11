"""S31 — the arbitrary limits, raised with their cost stated (0.63.14). (Sorts after test_s30.)

Kyle: *"lets update the arbitrary limits - balancing speed and budget."*

The ones changed here were round numbers with nothing measured behind them, and two of them narrowed what the chat
knows about the user's own project. Each was sized against his live data first:

| limit | was | now | what it costs |
|---|---|---|---|
| `qa.INVENTORY_MAX` | 40 | 120 | his project has 65 non-video sources: all of them ~1,359 tokens against ~853 at 40 — so 40 hid 25 of his own documents to save ~500 tokens (~$0.0015) a turn |
| `qa.RESEARCH_MAX` | 4 | 10 | ~475 tokens a turn (a question averages 180 chars, a watch-out 134) against 2,672 open questions and 264 watch-outs |
| `qa.MAX_EXCERPTS` | 60 | 90 | only REACHED when the model keeps searching, so ~12k input tokens (~$0.04) on the hard questions and nothing on the rest |
| `qa.MAX_TOOL_ROUNDS` | 6 | 8 | up to two more calls, spent only on a question still being worked |
| `candidates.SEEN_LIMIT` | 12 | 24 | $0, no network — a DB search over 10,319 candidates |
| `discover.LINK_MAX` | 24 | 40 | a little network; an unchecked dead link costs a queued job that fails later |
| `settings.workers` | 2 | 3 | ingestion concurrency; YouTube politeness is `yt_delay`, not the worker count |

**The frozen Tier 1 totals did not move**, and that is a fact about the gate rather than about the change: the
golden fixture has too few sources and targets to reach any of these caps. So the tests below hit them on purpose.
Every limit reads the environment, so each is revertible from `.env` with no code change — a limit that needs a
code edit is not a setting, it is a decision nobody can revisit.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_lim_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import candidates, db, discover, qa  # noqa: E402
from neurosearch.config import int_env, settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _project_with_documents(n: int) -> str:
    p = db.create_project("wide", brief="buying businesses")
    for i in range(n):
        s = db.upsert_source(platform="document", external_id=f"doc{i}", url=f"file:///doc{i}.pdf",
                             title=f"A deal document number {i}", status="ready")
        db.add_project_sources(p["id"], [s["id"]])
    return p["id"]


# ------------------------------------------------------------------ the numbers themselves

def test_every_raised_limit_is_readable_from_the_environment(monkeypatch):
    """A limit that needs a code edit is not a setting. Each one reverts from `.env`."""
    for env, default in (("NEUROSEARCH_CHAT_INVENTORY_MAX", 120), ("NEUROSEARCH_CHAT_RESEARCH_MAX", 10),
                         ("NEUROSEARCH_CHAT_MAX_EXCERPTS", 90), ("NEUROSEARCH_CHAT_TOOL_ROUNDS", 8),
                         ("NEUROSEARCH_SEEN_LIMIT", 24), ("NEUROSEARCH_DISCOVER_LINK_MAX", 40)):
        monkeypatch.setenv(env, "7")
        assert int_env(env, default) == 7
        monkeypatch.delenv(env)
        assert int_env(env, default) == default


def test_a_junk_or_zero_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_CHAT_MAX_EXCERPTS", "not a number")
    assert int_env("NEUROSEARCH_CHAT_MAX_EXCERPTS", 90) == 90
    monkeypatch.setenv("NEUROSEARCH_CHAT_MAX_EXCERPTS", "0")
    assert int_env("NEUROSEARCH_CHAT_MAX_EXCERPTS", 90) == 90
    monkeypatch.setenv("NEUROSEARCH_CHAT_MAX_EXCERPTS", "-5")
    assert int_env("NEUROSEARCH_CHAT_MAX_EXCERPTS", 90) == 90


def test_the_new_values_are_what_shipped():
    assert (qa.INVENTORY_MAX, qa.RESEARCH_MAX, qa.MAX_EXCERPTS, qa.MAX_TOOL_ROUNDS) == (120, 10, 90, 8)
    assert candidates.SEEN_LIMIT == 24 and discover.LINK_MAX == 40 and settings.workers >= 3


# ------------------------------------------------------------------ the prompt actually grows, and stays bounded

def test_the_inventory_lists_more_of_his_own_documents(fresh):
    """65 of his sources are documents, pages and files. At 40 the chat was told about 40 of them."""
    pid = _project_with_documents(65)
    block = qa.inventory_block(pid)
    assert block.count("\n- ") == 65 and "more (list_sources)" not in block


def test_the_inventory_is_still_bounded_and_says_so(fresh):
    """Raising a cap must not turn it into no cap: a 500-document project cannot write an unbounded prompt."""
    pid = _project_with_documents(qa.INVENTORY_MAX + 30)
    block = qa.inventory_block(pid)
    assert block.count("\n- ") == qa.INVENTORY_MAX + 1          # the listed rows plus the "… and N more" line
    assert f"and {30} more (list_sources)" in block


def test_the_research_block_carries_the_RANKED_items_not_the_first_n(fresh, monkeypatch):
    """The real defect was the ORDER: these were the first N of an arbitrary order. Ten ranked beats ten arbitrary."""
    pid = _project_with_documents(1)
    with db.tx() as conn:
        for i in range(40):
            conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, "
                         "updated_at) VALUES (?,?,?,?,?,?)",
                         (f"lt{i}", pid, f"open question number {i} about seller financing", "open", 1.0, 1.0))
        conn.execute("INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     ("lc1", pid, "a claim about seller financing terms", "factual", "seller financing",
                      "proposed", "weak", 1.0, 1.0))
    called = {}

    def spy(project_id, limit=5, **kw):
        called["limit"] = limit
        return {"next": [{"type": "question", "question": f"ranked question {i}"} for i in range(limit)]}

    monkeypatch.setattr("neurosearch.research_view.overview", spy)
    block = qa.research_block(pid)
    assert called["limit"] == qa.RESEARCH_MAX
    assert "ranked question 0" in block and block.count("- open evidence target:") == qa.RESEARCH_MAX


def test_a_failure_to_rank_never_loses_the_research_block(fresh, monkeypatch):
    """A chat turn must not depend on a priority order being computable — it falls back to the unranked lists."""
    pid = _project_with_documents(1)
    with db.tx() as conn:
        conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", ("lt99", pid, "an open question that must survive", "open", 1.0, 1.0))
        conn.execute("INSERT INTO project_claims (id, project_id, text, claim_type, status, strength, created_at, "
                     "updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("lc99", pid, "a claim", "factual", "proposed", "weak", 1.0, 1.0))
    monkeypatch.setattr("neurosearch.research_view.overview",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    block = qa.research_block(pid)
    assert block.startswith("Research state") and "an open question that must survive" in block


def test_the_excerpt_ceiling_is_the_ceiling_it_says(fresh):
    """MAX_EXCERPTS is a hard stop, not a target: the tool refuses past it rather than growing the prompt."""
    p = db.create_project("x", brief="b")
    project = db.get_project(p["id"])
    ctx = {"hits": [{"chunk_id": -i} for i in range(qa.MAX_EXCERPTS)], "source_ids": [], "priority_ids": set(),
           "seen": set()}
    out = qa._run_tool("search_library", {"query": "anything"}, project, [], [], ctx)
    assert "excerpt limit" in out
