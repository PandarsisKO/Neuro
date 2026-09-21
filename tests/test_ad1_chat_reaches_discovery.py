"""Mission A (2026-09-20, Kyle: "that's where I will be giving feedback to the app") — chat feedback can reach a
Discovery verdict.

Before this, the six chat tools could shape briefs, claims and priorities but nothing in chat could touch a
`skipped_low_relevance` candidate: saying "I want more from X" in chat moved nothing. `reconsider_creator` closes
that, on the same rule `ingest.approve_proposed` now uses — a creator this project has actually kept work from
(`pos > 0`) is worth DISPOSITION_MAX_ADJUST on a borderline score — so chat and review cannot disagree.

The cases that matter are the honest-failure ones: a creator with nothing kept, and a creator nobody has heard of,
must each say so rather than return an empty success (Kyle bulk-approves; a tool that silently no-ops would be
indistinguishable from one that worked).
"""
from __future__ import annotations

import pytest

from neurosearch import candidates as cand
from neurosearch import db
from neurosearch.config import settings


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _seed(pid: str, creator: str, rows: list[tuple[str, int, str]]) -> dict[str, str]:
    """rows: (external_id, relevance, state). Returns external_id -> candidate id."""
    out = {}
    for ext, rel, state in rows:
        cid = cand.remember([{"external_id": ext, "url": f"https://youtu.be/{ext}", "title": f"{creator} — {ext}",
                              "creator": creator}], "youtube", pid, {"kind": "channel", "title": creator})[0]
        cand.mark(pid, [cid], state, reason="seeded", relevance=rel)
        out[ext] = cid
    return out


def _project() -> str:
    return db.create_project("mission-a", brief="how to buy a small business")["id"]


def _state(pid: str, cid: str) -> str:
    return db.connect().execute(
        "SELECT state FROM candidate_projects WHERE project_id=? AND candidate_id=?", (pid, cid)).fetchone()["state"]


def test_trusted_creator_gets_borderline_items_back(fresh):
    pid = _project()
    # 3 kept (so `decided` clears DISPOSITION_MIN_DECISIONS and pos > 0), plus skips on both sides of the line
    ids = _seed(pid, "Acquiring Minds", [
        ("keep1", 80, "acquired"), ("keep2", 75, "acquired"), ("keep3", 70, "acquired"),
        ("near1", 48, "skipped_low_relevance"),      # within 12 of the 50 cutoff -> back
        ("near2", 38, "skipped_low_relevance"),      # exactly at the threshold    -> back
        ("far1", 37, "skipped_low_relevance"),       # one point under it          -> stays
        ("far2", 5, "skipped_low_relevance"),        # clearly off-topic           -> stays
    ])
    res = cand.reconsider_creator(pid, "Acquiring Minds")
    assert res["status"] == "moved"
    assert res["moved"] == 2, res
    assert {c["relevance"] for c in res["candidates"]} == {48, 38}
    assert _state(pid, ids["near1"]) == "available"
    assert _state(pid, ids["near2"]) == "available"
    assert _state(pid, ids["far1"]) == "skipped_low_relevance"    # ADD-ONLY: the cutoff still means something
    assert _state(pid, ids["far2"]) == "skipped_low_relevance"
    assert _state(pid, ids["keep1"]) == "acquired"                # nothing already decided is disturbed


def test_creator_name_matches_case_insensitively_and_partially(fresh):
    pid = _project()
    _seed(pid, "Acquisitions Anonymous Podcast", [
        ("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired"), ("s1", 45, "skipped_low_relevance")])
    res = cand.reconsider_creator(pid, "acquisitions anonymous")     # how a person actually types it in chat
    assert res["status"] == "moved" and res["moved"] == 1
    assert res["matched_creator"] == "Acquisitions Anonymous Podcast"


def test_second_run_is_idempotent(fresh):
    pid = _project()
    _seed(pid, "Walker Deibel", [("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired"),
                                 ("s1", 44, "skipped_low_relevance")])
    assert cand.reconsider_creator(pid, "Walker Deibel")["moved"] == 1
    again = cand.reconsider_creator(pid, "Walker Deibel")
    assert again["status"] == "nothing_left" and again["moved"] == 0   # not an error, and not a second move


def test_creator_with_nothing_kept_is_refused_out_loud(fresh):
    pid = _project()
    _seed(pid, "Random Channel", [("s1", 45, "skipped_low_relevance"), ("s2", 44, "skipped_low_relevance"),
                                  ("s3", 43, "skipped_low_relevance")])
    res = cand.reconsider_creator(pid, "Random Channel")
    assert res["status"] == "untrusted"          # seen, but never kept: no history to override the score with
    assert res["moved"] == 0
    assert res["known_creator"] == "Random Channel"


def test_unknown_creator_says_so_and_offers_the_real_ones(fresh):
    pid = _project()
    _seed(pid, "Acquiring Minds", [("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired")])
    res = cand.reconsider_creator(pid, "Some Channel That Was Never Seen")
    assert res["status"] == "unknown" and res["moved"] == 0
    assert "Acquiring Minds" in res["trusted_creators"]


def test_empty_creator_never_touches_anything(fresh):
    pid = _project()
    _seed(pid, "Acquiring Minds", [("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired"),
                                   ("s1", 45, "skipped_low_relevance")])
    assert cand.reconsider_creator(pid, "  ")["status"] == "no_creator"
    assert db.connect().execute(
        "SELECT COUNT(*) n FROM candidate_projects WHERE project_id=? AND state='skipped_low_relevance'",
        (pid,)).fetchone()["n"] == 1


def test_other_skip_states_are_never_resurfaced(fresh):
    """skipped_limit is "you picked 20 and this was 21st" and needs_membership is "YouTube will not allow it" —
    neither is a relevance judgment this can overturn, so neither moves."""
    pid = _project()
    ids = _seed(pid, "Acquiring Minds", [
        ("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired"),
        ("lim", 45, "skipped_limit"), ("gate", 95, "needs_membership"), ("dis", 46, "user_dismissed")])
    res = cand.reconsider_creator(pid, "Acquiring Minds")
    assert res["status"] == "nothing_left" and res["moved"] == 0
    assert _state(pid, ids["lim"]) == "skipped_limit"
    assert _state(pid, ids["gate"]) == "needs_membership"
    assert _state(pid, ids["dis"]) == "user_dismissed"   # an explicit human rejection is never undone by this


def test_the_chat_tool_reports_the_count_and_never_a_silent_success(fresh):
    """The qa.py handler is the half Kyle actually sees: every branch must produce text that says what happened."""
    from neurosearch import qa
    pid = _project()
    _seed(pid, "Acquiring Minds", [("k1", 90, "acquired"), ("k2", 85, "acquired"), ("k3", 80, "acquired"),
                                   ("s1", 45, "skipped_low_relevance")])
    project = db.get_project(pid)
    actions: list[dict] = []
    out = qa._run_tool("reconsider_creator", {"creator": "Acquiring Minds"}, project, [], actions)
    assert "1" in out and "Acquiring Minds" in out
    assert "not added" in out.lower()                 # it must not read as "added to your project"
    assert actions and actions[-1]["type"] == "creator_reconsidered" and actions[-1]["moved"] == 1

    out2 = qa._run_tool("reconsider_creator", {"creator": "Nobody At All"}, project, [], actions)
    assert "nothing was changed" in out2.lower()
    out3 = qa._run_tool("reconsider_creator", {"creator": ""}, project, [], actions)
    assert "no creator name" in out3.lower()


def test_the_tool_is_actually_offered_to_the_model(fresh):
    from neurosearch import qa
    assert any(t["name"] == "reconsider_creator" for t in qa._library_tools())
    assert "reconsider_creator" in qa.TOOL_LABELS
