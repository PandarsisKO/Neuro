"""The ranker must judge what a video TEACHES, not whether its subject business fits the buy-box (2026-09-20).

Measured, not assumed: a blind review of 30 candidates the filter had rejected found Kyle would have kept 23 --
77%, against a 25% bar fixed before the run. The loss was not concentrated near the cutoff (100% at 35-44, 90%
at 20-34, 40% at 0-19), which rules out "the threshold is too high" and points at the score measuring the wrong
thing. The model's own reasons named the mechanism: "not remote", "size mismatch", "physical not online",
"built it instead of buying it" -- all facts about a business, none about whether a video teaches anything.

The cause is structural, not a one-off: `db.project_steering` renders the brief as the person's own requirements
("must be operable remotely", "SDE at least $350k", "laundromats are rejected"), and the ranker was handed that
with no statement of what it is for. These tests hold the correction in place.
"""
from __future__ import annotations

import pytest

from neurosearch import db, relevance
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


def test_the_prompt_forbids_rejecting_on_buy_box_mismatch():
    sys_l = relevance.SYSTEM.lower()
    # the distinction itself
    assert "buy-box" in sys_l
    assert "teach" in sys_l
    # the exact excuses the model actually used on Kyle's data must be named as NON-reasons
    for excuse in ("not remote", "size mismatch", "wrong industry", "built it instead of buying it"):
        assert excuse in sys_l, f"the prompt no longer names {excuse!r} as a non-reason to reject"
    # constraints are a tiebreak, never a gate
    assert "tiebreak" in sys_l
    assert "never a veto" in sys_l


def test_a_constraint_mismatch_alone_cannot_score_below_60():
    """The floor is what stops the old behaviour coming back in a softer form: the model may still prefer
    closer matches, but it may not bury an instructive video for being about the wrong kind of business."""
    assert "never pushes an instructive video below 60" in relevance.SYSTEM


def test_a_missing_description_is_not_treated_as_a_reason_to_reject():
    """None of the 30 sampled candidates had a stored description, so the ranker was judging on titles alone —
    and a thin title must not read as 'nothing here'."""
    s = relevance.SYSTEM.lower()
    assert "description is often missing" in s
    assert "score\nin the middle" in s or "score in the middle" in s


def test_the_injected_brief_says_what_it_is_for(fresh):
    """The steering block is shared with every other prompt and cannot be reworded for this one, so the ranker
    is told at the point of injection how to read it."""
    pid = db.create_project("t", brief="Business must be operable remotely. SDE at least $350k.")["id"]
    head = relevance._head(db.get_project(pid), None)
    assert "Business must be operable remotely" in head          # the brief is still passed through verbatim
    assert "SITUATION and BUY-BOX" in head
    assert "TEACH" in head
    assert "not on whether the business it features fits those criteria" in head


def test_changing_the_prompt_invalidates_every_old_score(fresh):
    """`input_hash` folds in `prompt_version`, which hashes SYSTEM — so scores from the old prompt are
    automatically stale rather than silently kept. This is what makes a re-score meaningful."""
    pid = db.create_project("t", brief="b")["id"]
    project = db.get_project(pid)
    item = {"title": "Roofing roll-up", "description": "", "duration": 1800}
    before = relevance.input_hash(project, item)
    real = relevance.SYSTEM
    try:
        relevance.SYSTEM = real + "\n(changed)"
        assert relevance.prompt_version() != "rank-" + __import__("hashlib").sha1(real.encode()).hexdigest()[:8]
        assert relevance.input_hash(project, item) != before
    finally:
        relevance.SYSTEM = real
    assert relevance.input_hash(project, item) == before


def test_rescore_writes_scores_without_touching_state(fresh):
    """Scoring and deciding stay separate: a re-score must be readable before anything moves."""
    from neurosearch import candidates as cand
    pid = db.create_project("t", brief="b")["id"]
    cid = cand.remember([{"external_id": "x1", "url": "https://youtu.be/x1", "title": "Roofing roll-up",
                          "creator": "Acquiring Minds"}], "youtube", pid, {"kind": "channel", "title": "AM"})[0]
    cand.mark(pid, [cid], "skipped_low_relevance", reason="old prompt", relevance=22)

    assert cand.rescore(pid, [(cid, 78, "real deal structure, transferable")]) == 1
    row = db.connect().execute(
        "SELECT state, relevance, relevance_why FROM candidate_projects WHERE project_id=? AND candidate_id=?",
        (pid, cid)).fetchone()
    assert row["relevance"] == 78
    assert row["relevance_why"] == "real deal structure, transferable"
    assert row["state"] == "skipped_low_relevance"      # unchanged: promoting it is a separate, opt-in step


def test_rescore_ignores_candidates_from_other_projects(fresh):
    from neurosearch import candidates as cand
    a = db.create_project("a", brief="b")["id"]
    b = db.create_project("b", brief="b")["id"]
    cid = cand.remember([{"external_id": "x2", "url": "https://youtu.be/x2", "title": "t", "creator": "c"}],
                        "youtube", a, {"kind": "channel", "title": "c"})[0]
    cand.mark(a, [cid], "skipped_low_relevance", relevance=10)
    assert cand.rescore(b, [(cid, 90, "w")]) == 0
    assert db.connect().execute(
        "SELECT relevance FROM candidate_projects WHERE project_id=? AND candidate_id=?",
        (a, cid)).fetchone()["relevance"] == 10


# ---------------------------------------------------------------- description snippet (2026-09-20, later)
# Descriptions existed for the first time that afternoon. Measured immediately: median 1,883 chars, but the
# first 220 — all `_line` ever passed to the model — were promo for 25% of them. Backfilling descriptions and
# then feeding the ranker a funnel would have bought almost nothing.

def test_a_promo_header_does_not_eat_the_snippet():
    d = ("➡️ Learn How to Acquire Your First ''Boring'' Business: https://bit.ly/4q1JWxm\n"
         "➡️ Join My FREE Daily Newsletter: https://bit.ly/45oz0Sf\n\n"
         "In this video, I am sharing the best boring businesses to buy in 2026.")
    out = relevance.clean_description(d)
    assert out.startswith("In this video")
    assert "bit.ly" not in out and "Newsletter" not in out


def test_a_benefit_phrased_call_to_action_is_still_a_link_label():
    """No keyword list catches 'Learn How to Acquire Your First Boring Business:' — but a line that carried a
    URL and ends in a colon is a label for that URL whatever it says."""
    assert relevance.clean_description("Buy your first business in 6 months: https://x.co/a\nReal content here.") \
        == "Real content here."


def test_a_description_with_no_promo_is_left_alone():
    d = "We break down the financials of a $3.4M rodeo supply business, including add-backs and seller financing."
    assert relevance.clean_description(d) == d


def test_a_url_inside_a_real_sentence_loses_only_the_url():
    out = relevance.clean_description("The SBA published SOP 50 10 8 at https://sba.gov/doc which changes the rule.")
    assert "sba.gov" not in out
    assert "SOP 50 10 8" in out and "changes the rule" in out      # the sentence survives


def test_empty_and_missing_descriptions_are_safe():
    assert relevance.clean_description(None) == ""
    assert relevance.clean_description("") == ""
    assert relevance.clean_description("https://only-a-link.com") == ""


def test_the_snippet_window_is_wider_than_it_was():
    assert relevance.DESC_CHARS >= 400


def test_line_uses_the_cleaned_description(fresh):
    line = relevance._line(0, {"title": "T", "duration": 600,
                               "description": "Subscribe here: https://x.co/a\nActual substance about add-backs."})
    assert "x.co" not in line and "Subscribe" not in line
    assert "add-backs" in line


def test_changing_the_cleaning_invalidates_old_scores(fresh):
    """`input_hash` must fingerprint what is ACTUALLY judged. If it hashed the raw description, a cleaning
    change would leave every old score looking current."""
    pid = db.create_project("t", brief="b")["id"]
    project = db.get_project(pid)
    promo = {"title": "T", "description": "Join my newsletter: https://x.co/a\nReal content.", "duration": 600}
    plain = {"title": "T", "description": "Real content.", "duration": 600}
    # the two differ only in a funnel line the cleaner removes, so they must now judge — and hash — identically
    assert relevance.input_hash(project, promo) == relevance.input_hash(project, plain)
