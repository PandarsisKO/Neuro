"""S76 -- topic/basis claim synthesis (item 1, Kyle's decision session, 2026-09-20): a synthesized summary line
above a group of related weak claims, e.g. "9 sources give ranges of 1x-7x depending on business type... most
cluster around 2-4x SDE." Real trigger: Kyle's own words on the 25-item review queue -- "items 1-9 are not really
that big of a disagreement, but making an average/overlap of that data is probably most helpful." Explicitly NOT
claim merging: different valuation bases (SDE vs. revenue vs. profit vs. cash flow) must never be blended into one
number, since they measure genuinely different things. (Sorts after test_s75.)"""
from __future__ import annotations

import pytest

from neurosearch import claim_synthesis as cs
from neurosearch import db, review_queue


def _claim(claim_id: str, topic: str, text: str, reasons=("evidence_weak",), **extra) -> dict:
    row = {
        "claim_id": claim_id, "text": text, "claim_type": "valuation", "topic": topic,
        "strength": "weak", "strength_why": "single source", "reasons": list(reasons),
        "disagreement": False, "plan_impact": "unknown", "tensions": [],
        "members": {"note_ids": [], "merged_claim_ids": []}, "independent_sources": 1,
        "created_at": 0.0,
    }
    row.update(extra)
    return row


def test_extract_range_handles_single_and_range_multiples():
    assert cs.extract_range("multiples run 2-4x SDE") == (2.0, 4.0)
    assert cs.extract_range("about 3x cash flow") == (3.0, 3.0)
    assert cs.extract_range("range of 1x to 7x depending on size") == (1.0, 7.0)
    assert cs.extract_range("no number here") is None


def test_detect_basis_prefers_more_specific_terms():
    assert cs.detect_basis("2-4x SDE for owner-run shops") == "sde"
    assert cs.detect_basis("EBITDA multiples of 4-6x") == "ebitda"
    assert cs.detect_basis("priced on cash flow, 3x") == "cash_flow"
    assert cs.detect_basis("revenue multiple of 1x") == "revenue"
    assert cs.detect_basis("net profit multiple of 5x") == "profit"
    assert cs.detect_basis("just a 3x number") == "unspecified"


def test_group_of_similar_basis_claims_gets_a_summary_line():
    items = [
        _claim("c1", "business valuation multiples", "Small owner-run businesses sell for 1x-3x SDE"),
        _claim("c2", "business valuation multiples", "Typical range is 2x-4x SDE for this size"),
        _claim("c3", "business valuation multiples", "Some go as high as 6x-7x SDE for strong recurring revenue"),
        _claim("c4", "business valuation multiples", "Larger deals commonly land around 3x SDE"),
    ]
    summaries = cs.synthesize_topic_summaries(items)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["topic"] == "business valuation multiples"
    assert s["basis"] == "sde"
    assert s["n"] == 4
    assert s["overall_range"] == {"low": 1.0, "high": 7.0}
    assert "SDE" in s["summary_text"]
    assert set(s["claim_ids"]) == {"c1", "c2", "c3", "c4"}


def test_different_valuation_bases_are_never_blended_into_one_summary():
    items = [
        _claim("c1", "business valuation multiples", "Accounting firms trade at 1x-2x revenue"),
        _claim("c2", "business valuation multiples", "Accounting firm sales run 1.5x-2.5x revenue"),
        _claim("c3", "business valuation multiples", "CPA practices go for roughly 1x annual revenue"),
        _claim("c4", "business valuation multiples", "Owner-run trade businesses sell for 2x-4x SDE"),
        _claim("c5", "business valuation multiples", "Home service shops commonly go for 3x SDE"),
        _claim("c6", "business valuation multiples", "HVAC companies land around 2x-3x SDE"),
    ]
    summaries = cs.synthesize_topic_summaries(items)
    assert len(summaries) == 2
    by_basis = {s["basis"]: s for s in summaries}
    assert set(by_basis) == {"revenue", "sde"}
    assert by_basis["revenue"]["n"] == 3
    assert by_basis["sde"]["n"] == 3
    # no claim id crosses into the other basis's group
    assert set(by_basis["revenue"]["claim_ids"]).isdisjoint(by_basis["sde"]["claim_ids"])


def test_group_smaller_than_minimum_produces_no_summary():
    items = [
        _claim("c1", "business valuation multiples", "1x-2x SDE"),
        _claim("c2", "business valuation multiples", "2x-3x SDE"),
    ]
    assert cs.synthesize_topic_summaries(items) == []


def test_claims_without_topic_or_without_a_number_are_excluded_but_not_dropped_from_input():
    items = [
        _claim("c1", None, "1x-2x SDE"),
        _claim("c2", "business valuation multiples", "no number in this one"),
        _claim("c3", "business valuation multiples", "1x-2x SDE"),
        _claim("c4", "business valuation multiples", "2x-3x SDE"),
        _claim("c5", "business valuation multiples", "3x-4x SDE"),
    ]
    summaries = cs.synthesize_topic_summaries(items)
    assert len(summaries) == 1
    assert set(summaries[0]["claim_ids"]) == {"c3", "c4", "c5"}


def test_implausible_multiples_are_rejected_rather_than_dragged_into_a_range():
    # "400x" here is not a valuation multiple (e.g. it's describing some other kind of growth) -- it must not
    # widen the group's overall range or get counted as a member.
    assert cs.extract_range("grew 400x since launch") is None
    assert cs.extract_range("a 40x return for early investors") is None
    assert cs.extract_range("sells for 1x-400x depending on hype") is None  # the high end alone disqualifies it
    assert cs.extract_range("typical multiple is 2x-4x SDE") == (2.0, 4.0)  # ordinary claims are unaffected


def test_outlier_claim_is_excluded_from_its_group_not_blended_in():
    items = [
        _claim("c1", "business valuation multiples", "Small owner-run businesses sell for 1x-3x SDE"),
        _claim("c2", "business valuation multiples", "Typical range is 2x-4x SDE for this size"),
        _claim("c3", "business valuation multiples", "Larger deals commonly land around 3x SDE"),
        _claim("c4", "business valuation multiples", "This one grew 400x since the owner took over, unrelated to SDE"),
    ]
    summaries = cs.synthesize_topic_summaries(items)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["n"] == 3
    assert "c4" not in s["claim_ids"]
    assert s["overall_range"]["high"] == 4.0


def test_densest_interval_finds_the_sub_range_most_sources_agree_on():
    # 1-3, 2-4, 2-5, 6-7: three ranges overlap on [2,3], the fourth (6-7) is an outlier.
    ranges = [(1.0, 3.0), (2.0, 4.0), (2.0, 5.0), (6.0, 7.0)]
    interval, count = cs._densest_interval(ranges)
    assert interval == (2.0, 3.0)
    assert count == 3


# --- integration: review_queue.build() carries topic_summaries above the individual claims ------------------

@pytest.fixture
def rq_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _weak_claim(pid: str, cid: str, topic: str, text: str, created_at: float | None = None) -> None:
    t = created_at if created_at is not None else db.now()
    db.connect().execute(
        "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, freshness_class, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, pid, text, "valuation", topic, "proposed", "weak", "slow_changing", t, t))


def test_review_queue_build_includes_topic_summaries_above_the_individual_claims(rq_db):
    p = db.create_project("buying businesses", "acquire a business")
    pid = p["id"]
    _weak_claim(pid, "c1", "business valuation multiples", "Small owner-run businesses sell for 1x-2x SDE")
    _weak_claim(pid, "c2", "business valuation multiples", "Mid-size shops commonly go for 2x-4x SDE")
    _weak_claim(pid, "c3", "business valuation multiples", "Strong recurring-revenue shops fetch 4x-6x SDE")
    db.connect().commit()

    q = review_queue.build(pid)
    assert "topic_summaries" in q
    assert len(q["topic_summaries"]) == 1
    s = q["topic_summaries"][0]
    assert s["topic"] == "business valuation multiples"
    assert s["basis"] == "sde"
    assert s["n"] == 3
    assert set(s["claim_ids"]) == {"c1", "c2", "c3"}
    # the individual claims are still there underneath, untouched -- this is a summary, not a merge
    assert {x["claim_id"] for x in q["queue"]} == {"c1", "c2", "c3"}


def test_review_queue_build_has_no_topic_summaries_when_nothing_groups(rq_db):
    p = db.create_project("empty-ish", "brief")
    pid = p["id"]
    _weak_claim(pid, "c1", "solo topic", "no number in this claim at all")
    db.connect().commit()

    q = review_queue.build(pid)
    assert q["topic_summaries"] == []


def test_topic_summaries_only_draw_from_claims_actually_shown_not_the_whole_backlog(rq_db):
    p = db.create_project("buying businesses", "acquire a business")
    pid = p["id"]
    # 4 same-topic/basis weak claims, oldest first; with limit=3 only the 3 oldest are "shown" (evidence_weak
    # items are the ones the cap applies to -- see review_queue's ordering) and the newest is capped out.
    _weak_claim(pid, "c1", "business valuation multiples", "Small owner-run businesses sell for 1x-2x SDE", created_at=1.0)
    _weak_claim(pid, "c2", "business valuation multiples", "Mid-size shops commonly go for 2x-4x SDE", created_at=2.0)
    _weak_claim(pid, "c3", "business valuation multiples", "Strong recurring-revenue shops fetch 4x-6x SDE", created_at=3.0)
    _weak_claim(pid, "c4", "business valuation multiples", "Premium listings go for 6x-8x SDE", created_at=4.0)
    db.connect().commit()

    q = review_queue.build(pid, limit=3)
    assert q["counts"]["shown"] == 3
    assert q["counts"]["hidden_total"] == 1
    assert len(q["topic_summaries"]) == 1
    s = q["topic_summaries"][0]
    assert s["n"] == 3
    assert "c4" not in s["claim_ids"]  # capped out of the view -- must not be pulled into the summary anyway
