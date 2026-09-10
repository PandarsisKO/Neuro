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
                 "classes": {"experiential": 30, "expert": 25}, "per_source": 26.0, "proven": True,
                 "project_bar": 19.0},
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
    assert "top quartile" in joined                                   # and says what "proven" means
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


# ------------------------------------------------------------------ C2: where to look

def _src(proj, title, text, channel):
    from neurosearch import ingest
    r = ingest.ingest_text(title, text, project_id=proj)
    db.connect().execute("UPDATE sources SET channel=? WHERE id=?", (channel, r["source_id"]))
    db.connect().commit()
    return r["source_id"]


def test_where_to_look_needs_both_a_history_and_something_unread(proj):
    """A proven channel with nothing left is not a place to look, and an untapped channel with no history is just a
    list. Only the intersection is a recommendation."""
    sid = _src(proj, "Read already", "0:01 sellers finance ten percent of the price", "Proven But Exhausted")
    for i in range(12):
        db.add_project_note(proj, f"A real finding number {i} about seller financing terms", [], source_id=sid)
    out = candidates.where_to_look(proj)
    assert out["rows"] == []                       # history, but nothing untapped
    assert out["considered"] >= 1


def test_where_to_look_recommends_a_proven_creator_with_unread_material(proj):
    # enough READ sources to clear CREATOR_MIN_SOURCES — one rich video no longer proves a creator (0.58.7)
    for k in range(candidates.CREATOR_MIN_SOURCES):
        sid = _src(proj, f"Deal structure {k}", "0:01 sellers finance ten percent of the price", "Chase AI")
        for i in range(12):
            db.add_project_note(proj, f"A real finding {k}-{i} about seller financing terms", [], source_id=sid)
    # something known but unread from the same channel
    candidates.remember([{"external_id": f"vid{i}", "url": f"https://example.org/{i}",
                          "title": f"Deal structure part {i}", "creator": "Chase AI"} for i in range(14)],
                        platform="youtube", project_id=proj, origin={"kind": "exploration"})
    out = candidates.where_to_look(proj)
    assert out["rows"], out
    top = out["rows"][0]
    assert top["creator"] == "Chase AI"
    assert top["untapped"] == 14 and top["read"] == candidates.CREATOR_MIN_SOURCES
    assert any("14 known but unread" in w for w in top["why"])
    assert any("findings from" in w for w in top["why"])          # the reason cites the measurement
    assert top["expected_findings"] > 0
    assert top["action"]["query"]["q"] == "Chase AI"              # and it points at the pool, filtered


def test_a_creator_with_no_history_is_not_recommended_and_not_penalised(proj):
    candidates.remember([{"external_id": "u1", "url": "https://example.org/u1", "title": "Unknown channel video",
                          "creator": "Never Yielded"}], platform="youtube", project_id=proj,
                        origin={"kind": "exploration"})
    out = candidates.where_to_look(proj)
    assert all(r["creator"] != "Never Yielded" for r in out["rows"])
    assert "not evidence that it cannot" in out["note"]           # the reason is stated, not implied


def test_the_wanted_evidence_class_changes_the_ranking(proj):
    a = _src(proj, "Experiential source", "0:01 owners report a hard first year", "Experience Channel")
    b = _src(proj, "Expert source", "0:01 the statute imposes a two year lookback", "Expert Channel")
    for i in range(12):
        db.add_project_note(proj, f"A real finding number {i} from the experiential channel", [], source_id=a)
        db.add_project_note(proj, f"A real finding number {i} from the expert channel", [], source_id=b)
    for name in ("Experience Channel", "Expert Channel"):
        candidates.remember([{"external_id": f"{name}-{i}", "url": f"https://example.org/{name}{i}",
                              "title": f"{name} video {i}", "creator": name} for i in range(12)],
                            platform="youtube", project_id=proj, origin={"kind": "exploration"})
    # give the experiential channel a Claim with an experiential evidence class
    from neurosearch import claims as claims_mod
    claim = claims_mod.add_claim(proj, "Owners report a hard first year", claim_type="experiential")
    cid = claim["id"] if isinstance(claim, dict) else claim
    db.connect().execute("INSERT INTO claim_evidence (claim_id, source_id, evidence_class, created_at) VALUES (?,?,?,?)",
                         (cid, a, "experiential", 1.0))
    db.connect().commit()
    out = candidates.where_to_look(proj, {"question": "How do owners describe year one?",
                                          "preferred_classes": ["experiential"]})
    assert out["wanted_classes"] == ["experiential"]
    assert out["rows"][0]["creator"] == "Experience Channel"
    assert any("experiential evidence before" in w for w in out["rows"][0]["why"])


def test_where_to_look_makes_no_model_call_and_no_network(proj, monkeypatch):
    from neurosearch import providers, safe_fetch
    def boom(*a, **k):
        raise AssertionError("where_to_look must be free and offline")
    monkeypatch.setattr(providers, "invoke", boom)
    monkeypatch.setattr(providers, "invoke_structured", boom)
    monkeypatch.setattr(safe_fetch, "safe_fetch", boom)
    candidates.where_to_look(proj)


def test_pursue_carries_the_recommendation_without_touching_the_escalation_ladder(proj):
    """`steps` is the escalation LADDER and every entry is somewhere the app actually looked — the Research tab
    renders `already_checked` straight from it, and the G5 acceptance gate freezes its sequence. `where_to_look`
    searched nothing; it recommends where the USER should look. So it rides alongside the ladder, never in it.
    The first version of this put it in `steps` and broke both gates, which were right."""
    from neurosearch import knowledge
    tg = knowledge.add_target(proj, "How do owners describe year one?", preferred_classes=["experiential"],
                              origin="user")
    r = knowledge.pursue(tg["id"], external=False)
    esc = r["escalation"]
    steps = [s["step"] for s in esc["steps"]]
    assert [s for s in steps if s.startswith("where")] == []      # not a rung of the ladder
    assert "catalogue" not in steps                               # and still no outside request on this path
    assert steps == ["project_evidence", "global_library", "candidate_index", "external"]
    assert "where_to_look" in esc and isinstance(esc["where_to_look"], list)


# ------------------------------------------------------------------ calibration: "proven" is relative, not absolute

def test_proven_is_the_projects_own_top_quartile_not_a_fixed_number(proj):
    """CALIBRATED 2026-09-10 against the live corpus. An absolute bar does not survive contact with real projects:
    per-source findings is a property of the domain and of source length, not of a creator's merit. Measured
    per-source medians — "buying businesses" 12.0 (112 creators, max 48.2), "web app design" 6.1, "real estate"
    9.4 — so a fixed 8.0 marked nearly everyone in one project and almost nobody in another."""
    from neurosearch import ingest
    assert not hasattr(candidates, "CREATOR_STRONG_PER_SOURCE"), "the absolute bar is gone"
    assert candidates.CREATOR_PROVEN_QUANTILE == 0.75
    # three creators at clearly different rates, each with enough read sources to count
    plan = {"Prolific": 10, "Middling": 5, "Sparse": 2}
    for name, per in plan.items():
        for k in range(candidates.CREATOR_MIN_SOURCES):
            r = ingest.ingest_text(f"{name} {k}", f"0:01 a transcript for {name} number {k}", project_id=proj)
            db.connect().execute("UPDATE sources SET channel=? WHERE id=?", (name, r["source_id"]))
            db.connect().commit()
            for i in range(per):
                db.add_project_note(proj, f"{name} finding {k}-{i} naming something specific like {i} percent", [],
                                    source_id=r["source_id"])
    y = candidates.creator_yield(proj)
    assert y["Prolific"]["proven"] is True
    assert y["Sparse"]["proven"] is False
    assert y["Prolific"]["project_bar"] == y["Sparse"]["project_bar"]      # one bar, set by the project


def test_one_lucky_source_does_not_make_a_creator_proven(proj):
    from neurosearch import ingest
    r = ingest.ingest_text("A single very rich source", "0:01 one transcript", project_id=proj)
    db.connect().execute("UPDATE sources SET channel=? WHERE id=?", ("One Hit", r["source_id"]))
    db.connect().commit()
    for i in range(40):
        db.add_project_note(proj, f"A specific finding {i} with {i} percent in it", [], source_id=r["source_id"])
    y = candidates.creator_yield(proj)
    assert y["One Hit"]["sources"] == 1 < candidates.CREATOR_MIN_SOURCES
    assert y["One Hit"]["proven"] is False


def test_no_rate_is_projected_from_one_or_two_read_sources(proj):
    """Measured on the live corpus: "Acquiring Minds — 1 video read, 24 findings" produced a projection of ~240
    findings from the next ten. One source is not a rate. Below CREATOR_MIN_SOURCES the row offers no number and
    says why, which is the difference between an estimate and a guess wearing an estimate's clothes."""
    sid = _src(proj, "One rich video", "0:01 a single transcript", "One Hit Wonder")
    for i in range(24):
        db.add_project_note(proj, f"A specific finding {i} naming {i} percent of something", [], source_id=sid)
    candidates.remember([{"external_id": f"oh{i}", "url": f"https://example.org/oh{i}",
                          "title": f"One Hit Wonder video {i}", "creator": "One Hit Wonder"} for i in range(40)],
                        platform="youtube", project_id=proj, origin={"kind": "exploration"})
    out = candidates.where_to_look(proj)
    row = next(r for r in out["rows"] if r["creator"] == "One Hit Wonder")
    assert row["expected_findings"] is None and row["rate_is_reliable"] is False
    assert any("no reliable rate" in w for w in row["why"])
    assert "Null when fewer than" in out["expected_findings_note"]


def test_a_big_unread_pile_cannot_outrank_measured_yield(proj):
    """The untapped count is a tie-break, not a reason — a large remainder is not evidence it is worth reading."""
    for k in range(candidates.CREATOR_MIN_SOURCES):
        good = _src(proj, f"Good {k}", "0:01 transcript", "High Yield")
        for i in range(15):
            db.add_project_note(proj, f"High yield finding {k}-{i} naming {i} percent", [], source_id=good)
        meh = _src(proj, f"Meh {k}", "0:01 transcript", "Low Yield")
        for i in range(3):
            db.add_project_note(proj, f"Low yield finding {k}-{i} naming {i} percent", [], source_id=meh)
    candidates.remember([{"external_id": f"hy{i}", "url": f"https://e.org/hy{i}", "title": f"HY {i}",
                          "creator": "High Yield"} for i in range(10)], platform="youtube", project_id=proj,
                        origin={"kind": "exploration"})
    candidates.remember([{"external_id": f"ly{i}", "url": f"https://e.org/ly{i}", "title": f"LY {i}",
                          "creator": "Low Yield"} for i in range(400)], platform="youtube", project_id=proj,
                        origin={"kind": "exploration"})
    out = candidates.where_to_look(proj)
    order = [r["creator"] for r in out["rows"]]
    assert order.index("High Yield") < order.index("Low Yield"), order
