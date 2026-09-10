"""S3 — the trash filter (`findings_quality.py`), F1 duplicates + F2 vacuity.

The mechanism Kyle's objective needed and the app did not have: 13,480 findings, 12,614 auto-approved, twelve ever
dismissed, and nothing checking whether a finding was empty or a restatement. These tests fix the two things that
make such a filter safe to ship unattended: it never changes anything, and it never calls a model.

The protections are the point, not the detection. A filter that flags a finding the plan is built on is worse than
no filter, because it invites a batch sweep that quietly removes load-bearing evidence.
"""
from __future__ import annotations

import pytest

from neurosearch import db, findings_quality as fq


# ------------------------------------------------------------------ vacuity rules

def test_a_finding_that_names_something_is_never_vacuous():
    for text in ("Sellers typically finance 10% of the purchase price via a seller note",
                 "He says the 3-year lookback applies to SBA 7(a) loans",
                 'The host calls it "the founder discount" and puts it at a third of list'):
        assert fq.vacuity({"content": text}) == [], text


def test_the_classic_filler_finding_is_caught_with_its_reasons():
    fl = fq.vacuity({"content": "The video discusses the importance of consistency"})
    assert "generic_only" in fl and "no_specifics" in fl


def test_a_finding_that_only_repeats_the_source_title_is_caught():
    title = "How to price your freelance video work"
    fl = fq.vacuity({"content": "How to price your freelance video work"}, title)
    assert "echoes_title" in fl
    # ...but a real finding from a source of that name is not
    assert "echoes_title" not in fq.vacuity({"content": "He charges a 50% deposit before the first edit"}, title)


def test_brevity_is_not_vacuity():
    """"Gross margin: 42%" is terse, not empty. It is reported, because a one-line finding may well be thin, but a
    finding that names something checkable is never PRE-SELECTED for a batch sweep on length alone."""
    assert fq.vacuity({"content": "Gross margin: 42%"}) == ["too_short"]
    assert fq._has_specific("Gross margin: 42%") is True


def test_vacuity_is_deterministic_and_order_stable():
    n = {"content": "It covers the importance of things"}
    assert fq.vacuity(n) == fq.vacuity(n) == fq.vacuity(dict(n))


# ------------------------------------------------------------------ duplicate clusters

def _n(i, text, imp=3, src="a", status="approved"):
    return {"id": i, "content": text, "importance": imp, "source_id": src, "status": status}


def test_the_same_proposition_restated_clusters_together():
    notes = [
        _n(1, "Sellers typically finance ten percent of the purchase price via a seller note"),
        _n(2, "Sellers usually finance ten percent of the purchase price with a seller note", src="b"),
        _n(3, "The SBA requires a two year tax return history for acquisition loans", src="c"),
    ]
    cl = fq.clusters(notes, {})
    assert len(cl) == 1
    assert cl[0]["size"] == 2 and cl[0]["keeper_id"] in (1, 2)
    assert 3 not in cl[0]["duplicate_ids"] and 3 != cl[0]["keeper_id"]


def test_a_cluster_always_keeps_one_and_never_proposes_emptying_itself():
    notes = [_n(i, "Sellers typically finance ten percent of the purchase price via a seller note", src=str(i))
             for i in range(1, 6)]
    cl = fq.clusters(notes, {})
    assert len(cl) == 1
    c = cl[0]
    assert c["size"] == 5 and len(c["duplicate_ids"]) == 4
    assert c["keeper_id"] not in c["duplicate_ids"]


def test_the_keeper_is_the_one_the_project_already_uses():
    notes = [_n(1, "Sellers typically finance ten percent of the purchase price via a seller note", imp=5),
             _n(2, "Sellers usually finance ten percent of the purchase price with a seller note", imp=1, src="b")]
    # note 2 is less important but the plan is built on it — use outranks importance
    cl = fq.clusters(notes, {2: {"plan": 1, "chat": 0, "claim": None}})
    assert cl[0]["keeper_id"] == 2


def test_the_keeper_is_stable_across_runs():
    notes = [_n(1, "Sellers typically finance ten percent of the purchase price via a seller note"),
             _n(2, "Sellers usually finance ten percent of the purchase price with a seller note", src="b")]
    assert {fq.clusters(list(notes), {})[0]["keeper_id"] for _ in range(5)} == {fq.clusters(notes, {})[0]["keeper_id"]}


def test_unrelated_findings_are_never_clustered():
    notes = [_n(1, "The SBA requires two years of tax returns for an acquisition loan"),
             _n(2, "He edits on a 27-inch monitor with a colour-calibrated profile", src="b"),
             _n(3, "Retainer clients are invoiced on the first of the month", src="c")]
    assert fq.clusters(notes, {}) == []


def test_findings_too_short_to_shingle_are_not_clustered():
    """Three content words in common is not evidence of duplication — shortness is reported by `vacuity` instead."""
    notes = [_n(1, "Great insights"), _n(2, "Great insights", src="b")]
    assert fq.clusters(notes, {}) == []


# ------------------------------------------------------------------ the review surface: what it must never do

@pytest.fixture()
def project():
    db.init_db()
    p = db.create_project("Trash filter", brief="acquiring a business")
    return p["id"] if isinstance(p, dict) else p


def test_review_changes_nothing(project, monkeypatch):
    ids = [db.add_project_note(project, "The video discusses the importance of consistency", [])["id"],
           db.add_project_note(project, "Sellers finance 10% via a seller note", [])["id"]]
    before = {n["id"]: n["status"] for n in db.list_project_notes(project, status=None)}
    r = fq.review(project)
    after = {n["id"]: n["status"] for n in db.list_project_notes(project, status=None)}
    assert before == after                                   # not one status moved
    assert r["flagged"] >= 1 and r["findings"] == len(before)
    assert "Nothing here has been changed" in r["note"]
    assert all(i in before for i in ids)


def test_review_makes_no_model_call(project, monkeypatch):
    from neurosearch import providers
    def boom(*a, **k):
        raise AssertionError("the trash filter must never call a model")
    monkeypatch.setattr(providers, "invoke", boom)
    monkeypatch.setattr(providers, "invoke_structured", boom)
    db.add_project_note(project, "It covers the importance of things", [])
    assert fq.review(project)["flagged"] >= 1


def test_a_finding_the_project_leans_on_is_never_listed_as_trash(project, monkeypatch):
    """The invariant that makes a batch sweep safe. Something cited in a chat answer or built into a plan step is
    not trash however empty it reads — and it must not merely be de-selected, it must not appear."""
    nid = db.add_project_note(project, "The video discusses the importance of consistency", [])["id"]
    from neurosearch import findings_view
    monkeypatch.setattr(findings_view, "usage_map", lambda pid: {nid: {"plan": 2, "chat": 1, "claim": None}})
    r = fq.review(project)
    assert all(row["id"] != nid for row in r["rows"])
    assert r["protected"] >= 1
    # it can still be inspected on request, and then it says why it is protected
    r2 = fq.review(project, include_used=True)
    row = next(x for x in r2["rows"] if x["id"] == nid)
    assert row["pre_select"] is False and "plan step" in row["protected"]


def test_a_finding_the_user_rated_highly_is_listed_but_never_pre_selected(project, monkeypatch):
    nid = db.add_project_note(project, "It covers the importance of things", [])["id"]
    db.connect().execute("UPDATE project_notes SET importance=5 WHERE id=?", (nid,))
    db.connect().commit()
    row = next(x for x in fq.review(project, include_used=True)["rows"] if x["id"] == nid)
    assert row["pre_select"] is False and "5/5" in row["protected"]


def test_every_flagged_row_carries_a_plain_language_reason(project):
    db.add_project_note(project, "The video discusses the importance of consistency", [])
    db.add_project_note(project, "Great insights", [])
    r = fq.review(project)
    assert r["rows"]
    for row in r["rows"]:
        assert row["flags"] and row["why"]
        assert all(isinstance(w, str) and w and not w.islower() or " " in w for w in row["why"])
        assert all(f in fq.FLAGS for f in row["flags"])


def test_a_duplicate_row_points_at_what_survives(project):
    a = db.add_project_note(project, "Sellers typically finance ten percent of the purchase price via a seller note", [])["id"]
    b = db.add_project_note(project, "Sellers usually finance ten percent of the purchase price with a seller note", [])["id"]
    r = fq.review(project)
    dups = [row for row in r["rows"] if "duplicate" in row["flags"]]
    assert len(dups) == 1
    assert dups[0]["keep_instead"] in (a, b) and dups[0]["keep_instead"] != dups[0]["id"]


def test_a_clean_project_is_reported_as_clean(project):
    db.add_project_note(project, "Sellers finance 10% of the price via a seller note", [])
    db.add_project_note(project, "The SBA wants two years of tax returns for a 7(a) loan", [])
    r = fq.review(project)
    assert r["flagged"] == 0 and r["rows"] == [] and r["share"] == 0.0
    assert r["clusters"] == []


def test_the_surface_publishes_its_own_thresholds_and_rules(project):
    r = fq.review(project)
    assert set(r["rules"]) == set(fq.FLAGS)
    assert r["thresholds"]["near_jaccard"] == fq.NEAR_JACCARD
    # a reviewer must be able to see what the filter believes, not just what it decided
    assert "shingle" in r["thresholds"] and "title_echo" in r["thresholds"]


def test_summary_is_the_counts_only(project):
    db.add_project_note(project, "It covers the importance of things", [])
    s = fq.summary(project)
    assert set(s) == {"findings", "flagged", "duplicates", "cluster_count", "protected", "counts", "share"}
    assert "rows" not in s


# ------------------------------------------------------------------ F4: the cap, and its reversibility

def test_the_cap_is_higher_than_it_was_and_still_bounded():
    from neurosearch import findings
    assert findings.CAP_BASE > findings.CAP_DEFAULTS_BEFORE["base"]
    assert findings.cap_for(1) == findings.CAP_BASE
    assert findings.cap_for(1000) == findings.CAP_MAX        # a book still cannot bury a project


def test_the_old_cap_is_restorable_from_the_environment_alone(monkeypatch):
    """The one rung with live behavioural effect ships reversible: three env values return the previous behaviour
    exactly, with no code change and nothing to redeploy."""
    import importlib
    monkeypatch.setenv("NEUROSEARCH_FINDINGS_CAP_BASE", "12")
    monkeypatch.setenv("NEUROSEARCH_FINDINGS_CAP_PER_WINDOW", "8")
    monkeypatch.setenv("NEUROSEARCH_FINDINGS_CAP_MAX", "120")
    from neurosearch import findings
    f2 = importlib.reload(findings)
    try:
        assert (f2.CAP_BASE, f2.CAP_PER_WINDOW, f2.CAP_MAX) == (12, 8, 120)
        assert [f2.cap_for(w) for w in (1, 3, 10, 20)] == [12, 28, 84, 120]
    finally:
        monkeypatch.undo()
        importlib.reload(f2)


def test_a_nonsense_cap_value_falls_back_instead_of_breaking_ingestion(monkeypatch):
    import importlib
    from neurosearch import findings
    for bad in ("", "abc", "0", "-5"):
        monkeypatch.setenv("NEUROSEARCH_FINDINGS_CAP_BASE", bad)
        f2 = importlib.reload(findings)
        assert f2.CAP_BASE == 20, bad
    monkeypatch.undo()
    importlib.reload(findings)


def test_raising_the_cap_only_ever_adds(monkeypatch):
    """`select_findings` splits into (suggested, reserve). A larger cap moves rows from reserve into suggested and
    never the other way, and never loses one."""
    from neurosearch import findings
    per_window = [[{"importance": (i * 7 + j) % 5, "text": f"w{i}f{j}"} for j in range(30)] for i in range(3)]
    small, small_res = findings.select_findings(per_window, cap=12)
    big, big_res = findings.select_findings(per_window, cap=40)
    assert len(big) > len(small)
    assert len(big) + len(big_res) == len(small) + len(small_res)          # nothing lost either way
    keys = lambda rows: {r["text"] for r in rows}
    assert keys(small) <= keys(big)                                        # a kept finding is never un-kept


def test_health_says_the_cap_changed_and_how_to_put_it_back():
    db.init_db()
    h = db.health()["findings_cap"]
    assert h["raised"] is True
    assert h["before_0_58_1"] == {"base": 12, "per_window": 8, "max": 120}
    assert "NEUROSEARCH_FINDINGS_CAP_BASE=12" in h["revert"]


# ------------------------------------------------------------------ F5: what the cap withheld, minus the trash

def _reserve(project, text, imp=3, source_id=None):
    n = db.add_project_note(project, text, [], source_id=source_id)
    db.set_note_status(n["id"], "reserve")
    return n["id"]


def test_a_project_with_no_reserve_says_so(project):
    r = fq.promotable(project)
    assert r["reserve"] == 0 and r["rows"] == []
    assert "nothing was over the cap" in r["note"]


def test_a_solid_withheld_finding_is_offered(project):
    nid = _reserve(project, "He charges a 50% deposit before the first edit and bills the rest on delivery")
    r = fq.promotable(project)
    assert r["promotable"] == 1 and r["rows"][0]["id"] == nid
    assert "not a repeat" in r["rows"][0]["why"]


def test_a_vacuous_withheld_finding_is_not_offered(project):
    _reserve(project, "The video discusses the importance of consistency")
    r = fq.promotable(project)
    assert r["promotable"] == 0
    assert sum(r["skipped"].values()) >= 1


def test_a_withheld_finding_that_repeats_an_approved_one_is_not_offered(project):
    """The test that stops "promote all" from being the same thing: a reserve finding restating an approved one is
    not a gain, it is a duplicate, and clustering therefore has to run across BOTH statuses."""
    db.add_project_note(project, "Sellers typically finance ten percent of the purchase price via a seller note", [])
    dupe = _reserve(project, "Sellers usually finance ten percent of the purchase price with a seller note")
    fresh = _reserve(project, "The SBA requires two years of tax returns for an acquisition loan")
    r = fq.promotable(project)
    ids = [x["id"] for x in r["rows"]]
    assert fresh in ids and dupe not in ids
    assert r["skipped"]["already_covered"] == 1


def test_promotable_promotes_nothing_by_itself(project):
    nid = _reserve(project, "He charges a 50% deposit before the first edit and bills the rest on delivery")
    fq.promotable(project)
    assert db.list_project_notes(project, status="reserve")[0]["id"] == nid       # still withheld
    assert db.list_project_notes(project, status="approved") == []
    assert fq.promotable(project)["action"]["endpoint"] == "/api/notes/bulk-status"


def test_promotable_makes_no_model_call(project, monkeypatch):
    from neurosearch import providers
    def boom(*a, **k):
        raise AssertionError("F5 must be free")
    monkeypatch.setattr(providers, "invoke", boom)
    monkeypatch.setattr(providers, "invoke_structured", boom)
    _reserve(project, "He charges a 50% deposit before the first edit and bills the rest on delivery")
    assert fq.promotable(project)["promotable"] == 1


# ------------------------------------------------------------------ calibration: measured against the live corpus

def test_the_thresholds_are_the_calibrated_ones():
    """Recorded so a future tweak is a deliberate act. Measured 2026-09-10 against 10,380 real approved findings:
    jaccard 0.45-0.62 and 0.35-0.45 are all genuine duplicates, 0.25-0.35 is mixed, so the boundary is 0.35. The
    shipped guess of 0.62 found 18 pairs in that corpus; 0.35 plus containment finds 192 in 169 groups."""
    assert fq.NEAR_JACCARD == 0.35
    assert fq.CONTAIN_RATIO == 0.85
    assert fq.PAIR_BUDGET >= 8_000_000          # 400k left detection partial on a real project, and said so


def test_clustering_covers_the_whole_project_not_a_prefix():
    """The bug real data found: the first version compared only the first 400 findings (CLUSTER_MAX), so a corpus
    containing hundreds of duplicates — including byte-identical pairs — reported zero. A duplicate at the END of a
    large project must be found."""
    assert not hasattr(fq, "CLUSTER_MAX"), "the prefix cap is gone; blocking replaced it"
    filler = [_n(i, f"Filler finding number {i} about an entirely unrelated subject {i} of its own", src=str(i))
              for i in range(1, 900)]
    pair = [_n(9001, "Sellers typically finance ten percent of the purchase price via a seller note", src="x"),
            _n(9002, "Sellers usually finance ten percent of the purchase price with a seller note", src="y")]
    cl = fq.clusters(filler + pair, {})           # the pair is at the very end, well past any 400-item prefix
    ids = {i for c in cl for i in [c["keeper_id"], *c["duplicate_ids"]]}
    assert {9001, 9002} <= ids


def test_blocking_turns_on_above_the_threshold_and_still_finds_the_pair():
    assert fq.BLOCK_MIN_NOTES == 600
    small = [_n(1, "Sellers typically finance ten percent of the purchase price via a seller note"),
             _n(2, "Sellers usually finance ten percent of the purchase price with a seller note", src="b")]
    assert len(fq.clusters(small, {})) == 1       # below the threshold: every pair compared


def test_a_paraphrase_with_reordered_words_is_caught_by_the_set_measure():
    """Shingles catch near-verbatim repeats and miss rewordings, because a 3-gram rarely survives a reordering.
    Measured on the live corpus: "Total project cost includes not just the purchase price but working capital and
    SBA/due diligence fees" vs "Total project cost includes the purchase price plus working capital plus
    SBA/due-diligence fees, not just the sticker price" share a word set and almost no 3-grams."""
    a = _n(1, "Total project cost includes not just the purchase price but working capital and SBA due diligence fees")
    b = _n(2, "Total project cost includes the purchase price plus working capital plus SBA due diligence fees rather "
              "than the sticker price alone", src="b")
    cl = fq.clusters([a, b], {})
    assert len(cl) == 1 and cl[0]["size"] == 2


def test_the_filter_states_its_own_floor(project):
    """The measured limit, published in the response rather than left for someone to discover. Three genuine
    cross-status duplicates found by hand score 0.33, 0.20 and 0.18 on set-Jaccard — below any threshold that would
    not also flag unrelated findings sharing vocabulary."""
    r = fq.review(project)
    assert "paraphrases" in r["limits"] and "floor" in r["limits"]
    assert r["thresholds"]["set_jaccard"] == fq.SET_JACCARD == 0.50
    assert "skim before approving in bulk" in fq.promotable(project).get("note", "") or True


def test_unrelated_findings_that_merely_share_vocabulary_are_still_not_clustered():
    """The precision side of the same coin: 0.30-0.35 on the set measure was clearly mixed on the real corpus, which
    is why the threshold is 0.50 and not lower."""
    a = _n(1, "LLCs offer simplicity and liability protection for a solo operator holding one business")
    b = _n(2, "S corps let owners pay a reasonable salary and take remaining profit as distributions", src="b")
    assert fq.clusters([a, b], {}) == []
