"""S4 — C1: a known-but-uncaptured source is scored by what its master source has already given the project.

Before this, `candidates._potential` judged an item out of 100 on the words in its own title and 600 characters of
description, and nothing else. A video from a channel whose sixty siblings had produced hundreds of findings and
closed evidence targets scored exactly the same as one from a channel that had never yielded anything — the
measurement was in the database and nothing read it. With a partial-ingest pattern (60 of 598, 107, 93, 398
unstarted) those remainders are reservoirs of known character, so this is the difference between a ranked pool and
a flat list of strangers.

The two rules that keep it honest: **absence is never evidence** (a creator with no yield is never penalised, it may
never have been asked), and the profile is **project-scoped** (G4 forbids a global source profile built from project
findings — a finding is an interpretation written against one brief).
"""
from __future__ import annotations

import pytest

from neurosearch import candidates, db


@pytest.fixture()
def proj():
    db.init_db()
    p = db.create_project("Capability", brief="acquiring a small business")
    return p["id"] if isinstance(p, dict) else p


STATS = {
    "Chase AI": {"sources": 12, "findings": 312, "claims": 40, "evidence": 55,
                 "classes": {"experiential": 30, "expert": 25}, "per_source": 26.0, "proven": True},
    "Thin Channel": {"sources": 4, "findings": 2, "claims": 0, "evidence": 0, "classes": {},
                     "per_source": 0.5, "proven": False},
    "Middling": {"sources": 5, "findings": 20, "claims": 0, "evidence": 0, "classes": {},
                 "per_source": 4.0, "proven": False},
}


# ------------------------------------------------------------------ the creator term

def test_a_proven_creator_earns_a_measured_bonus_with_its_numbers():
    score, why = candidates._creator_term("Chase AI", STATS, {"experiential"})
    assert score == candidates.CREATOR_MAX_BONUS
    joined = " ".join(why)
    assert "312 findings" in joined and "12 source(s)" in joined      # the reason cites the measurement
    assert "became tracked Claims" in joined
    assert "experiential evidence before" in joined


def test_a_creator_with_no_yield_is_never_penalised():
    """Absence is not evidence: a channel that has supplied no authoritative evidence may never have been asked for
    any. Reporting that as a negative would be the same error as claiming a skipped step had been checked."""
    for name in ("Thin Channel", "Never Seen Before", None, ""):
        score, why = candidates._creator_term(name, STATS, {"authoritative"})
        assert score == 0 and why == [], name


def test_the_bonus_is_bounded_and_cannot_dominate_the_word_signals():
    score, _ = candidates._creator_term("Chase AI", STATS, {"experiential", "expert"})
    assert score <= candidates.CREATOR_MAX_BONUS <= 30


def test_a_middling_creator_earns_less_than_a_proven_one():
    mid, _ = candidates._creator_term("Middling", STATS, set())
    strong, _ = candidates._creator_term("Chase AI", STATS, set())
    assert 0 < mid < strong


def test_the_class_bonus_only_applies_to_a_class_the_project_actually_wants():
    with_want, _ = candidates._creator_term("Chase AI", STATS, {"experiential"})
    without, _ = candidates._creator_term("Chase AI", STATS, {"market"})
    assert with_want > without


# ------------------------------------------------------------------ _potential composes, it does not replace

def test_potential_still_works_with_no_creator_information():
    """The creator term is a bonus, never a prerequisite — a project with no yield history behaves exactly as before."""
    a = candidates._potential("SBA loan requirements explained", "", [], set(), 80, [])
    b = candidates._potential("SBA loan requirements explained", "", [], set(), 80, [], creator="X", creator_stats={})
    assert a == b


def test_the_same_item_scores_higher_from_a_proven_creator():
    base, _, why_a = candidates._potential("Seller financing walkthrough", "", [], set(), None, [])
    boosted, _, why_b = candidates._potential("Seller financing walkthrough", "", [], set(), None, [],
                                              creator="Chase AI", creator_stats=STATS, want_classes={"experiential"})
    assert boosted > base
    assert len(why_b) > len(why_a)
    assert any("312 findings" in w for w in why_b)


def test_a_score_stays_within_bounds():
    s, _, _ = candidates._potential("Seller financing walkthrough with real numbers", "sba 7a loan seller note",
                                    [("t1", "financing", {"seller", "financing", "note"})], {"seller", "note"}, 100,
                                    ["an open question"], creator="Chase AI", creator_stats=STATS,
                                    want_classes={"experiential"})
    assert 0 <= s <= 100


# ------------------------------------------------------------------ creator_yield: derived, project-scoped, $0

def test_creator_yield_is_empty_for_an_empty_project(proj):
    assert candidates.creator_yield(proj) == {}


def test_creator_yield_makes_no_model_call(proj, monkeypatch):
    from neurosearch import providers
    def boom(*a, **k):
        raise AssertionError("the capability profile must never call a model")
    monkeypatch.setattr(providers, "invoke", boom)
    monkeypatch.setattr(providers, "invoke_structured", boom)
    candidates.creator_yield(proj)


def test_creator_yield_counts_findings_per_master_source(proj):
    from neurosearch import ingest
    a = ingest.ingest_text("Deal structure part one", "0:01 sellers finance ten percent of the price",
                           project_id=proj)
    b = ingest.ingest_text("Deal structure part two", "0:01 the sba wants two years of returns", project_id=proj)
    for sid, chan in ((a["source_id"], "Chase AI"), (b["source_id"], "Chase AI")):
        db.connect().execute("UPDATE sources SET channel=? WHERE id=?", (chan, sid))
    db.connect().commit()
    db.add_project_note(proj, "Sellers finance 10% of the price", [], source_id=a["source_id"])
    db.add_project_note(proj, "The SBA wants two years of returns", [], source_id=b["source_id"])
    db.add_project_note(proj, "A third finding from the same channel", [], source_id=a["source_id"])
    y = candidates.creator_yield(proj)
    assert "Chase AI" in y
    assert y["Chase AI"]["sources"] == 2 and y["Chase AI"]["findings"] == 3
    assert y["Chase AI"]["per_source"] == 1.5
    assert y["Chase AI"]["proven"] is False                 # 1.5 per source is not proven, and says so


def test_yield_does_not_leak_across_projects(proj):
    """G4's boundary in the one place it could be broken: a finding is an interpretation written against ONE brief,
    so another project's findings must never appear in this project's capability profile."""
    from neurosearch import ingest
    other = db.create_project("Other project", brief="something else")
    oid = other["id"] if isinstance(other, dict) else other
    r = ingest.ingest_text("Shared source", "0:01 a shared video both projects hold", project_id=proj)
    db.connect().execute("UPDATE sources SET channel=? WHERE id=?", ("Shared Channel", r["source_id"]))
    db.connect().commit()
    db.add_project_note(oid, "A finding that belongs to the OTHER project", [], source_id=r["source_id"])
    y = candidates.creator_yield(proj)
    assert y.get("Shared Channel", {}).get("findings", 0) == 0
