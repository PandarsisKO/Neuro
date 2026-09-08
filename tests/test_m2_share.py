"""C0 Portable Answers, second half (0.35.1): Share ▾ variants — a shorter version of a FINISHED answer, never a new research
pass, that can only cite what the original cited; warnings ride along in the client exactly as Copy ▾. (Sorts after test_m1.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_share_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import contracts, db, fake_ai, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402

ANSWER = ("The SBA requires at least a 10 percent equity injection on a change-of-ownership loan [1]. A seller note can count toward it only "
          "when it is on full standby for the life of the loan [2]. Several owners report that first-year software costs ran well over the "
          "seller's numbers [3]. One broker disputes this, calling the migration story overblown [4]. Gap: no current lender confirmation of the standby rule.")
CITES = [{"n": 1, "title": "SOP 50 10 8", "timestamp": "p. 112"}, {"n": 2, "title": "SOP 50 10 8", "timestamp": "p. 114"},
         {"n": 3, "title": "r/smallbusiness thread", "timestamp": "comment 4 by owner_maria"}, {"n": 4, "title": "Broker blog", "timestamp": "§ 1"}]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.delenv("NEUROSEARCH_FAKE_SHARE_STRAY", raising=False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    yield
    db._local.conn = None


def test_share_contract_exists_and_is_interactive():
    c = contracts.contract("answer.share")
    assert c.interactive and c.fallback == "NO_FALLBACK" and c.max_output_tokens <= 1500 and c.schema is None


def test_short_and_medium_keep_only_the_original_markers():
    short = qa.share_variant(ANSWER, CITES, "short")
    assert short["text"] and len(short["text"]) < len(ANSWER) and short["markers"] == [1, 2] and not short["removed_markers"] and short["warning"] is None
    medium = qa.share_variant(ANSWER, CITES, "medium")
    assert len(medium["text"]) > len(short["text"]) and set(medium["markers"]) <= {1, 2, 3, 4}
    with pytest.raises(ValueError):
        qa.share_variant(ANSWER, CITES, "tweet")
    # exactly one model call per variant, recorded as answer usage — never a retrieval or a tool round
    n = db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task='answer.share'").fetchone()[0]
    assert n == 2


def test_a_marker_the_original_never_had_is_removed_and_reported(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_SHARE_STRAY", "1")
    v = qa.share_variant(ANSWER, CITES, "short")
    assert "[97]" not in v["text"] and v["removed_markers"] == [97] and "removed" in v["warning"]
    assert v["markers"] == [1, 2]


def test_share_endpoint_guards_budget_and_rejects_empty(monkeypatch):
    from fastapi import HTTPException
    from neurosearch import api
    with pytest.raises(HTTPException):
        api.api_share(api.ShareIn(text="   ", citations=[], length="short"))
    r = api.api_share(api.ShareIn(text=ANSWER, citations=CITES, length="short"))
    assert r["markers"] == [1, 2]
