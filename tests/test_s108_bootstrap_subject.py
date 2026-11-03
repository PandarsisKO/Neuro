"""S108 — "Research in your library that may help this project" must be about the PROJECT, not one phrase of it.

Kyle, 2026-11-03, new project about AI tools for his aircraft-cleaning business: the card was "wildly unhelpful and
inaccurate". Measured: 6 of 7 "strong" rows came from the clause "we have quickbooks online" (what he already uses,
not what he is researching) — M&A and bookkeeping videos that name QuickBooks once. Two fixes, gated here:
  * a short clause (fewer than 3 content words) cannot make a match "strong" on its own;
  * every match is checked against the WHOLE brief by meaning, with bars set by rank within this library (the
    closest 10% to stay, the closest 1% to be strong or to be added when no facet search found it). A source found
    by meaning alone is offered as "possible", never pre-ticked: "strong" needs a facet search AND meaning to agree."""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import bootstrap, db, ingest  # noqa: E402
from neurosearch.config import settings  # noqa: E402

BRIEF = ("I am looking for an unbiased opinion on what ai tools would be useful to my aviation cleaning business. "
         "I use google workspace and am hiring my first employee. I want something like a virtual assistant, "
         "we have quickbooks online, and I want customers to book their own appointments.")

QB = [(f"Deal interview {i}", f"0:05 the seller ran the books in quickbooks online\n2:00 debt service coverage and sde multiple {i}")
      for i in range(4)]
AI = [("AI assistant for a small service business", "0:05 an ai virtual assistant answers customers and books appointments for a small service business\n1:00 tools that integrate with google workspace"),
      ("AI tool stack for owner operators", "0:10 the ai tools a one person business actually needs: scheduling, an assistant, invoicing\n3:00 measure roi before you automate")]
FILLER = [(f"Filler {i}", f"0:05 real estate cap rates and duplex financing number {i}\n1:00 tenant screening {i}") for i in range(30)]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _library():
    other = db.create_project("Buying businesses", "acquisitions")
    ids = {}
    for group, items in (("qb", QB), ("ai", AI), ("filler", FILLER)):
        ids[group] = [ingest.ingest_text(t, b, project_id=other["id"])["source_id"] for t, b in items]
    p = db.create_project("AI powered Aviation Detailing Company", BRIEF)
    db.update_project(p["id"], goal=BRIEF)
    return p["id"], ids


# ---------------------------------------------------------------- band rules

def test_a_two_word_clause_cannot_make_a_match_strong_on_its_own():
    hit = {"queries": ["we have quickbooks online"], "distinctive_queries": ["we have quickbooks online"],
           "coverage": 1.0, "passage_coverage": 1.0}
    assert bootstrap._band(hit) == "possible", "naming the product once fully 'covers' a two-word clause"
    hit3 = {**hit, "queries": ["virtual assistant appointment booking"], "distinctive_queries": ["virtual assistant appointment booking"]}
    assert bootstrap._band(hit3) == "strong"
    two = {**hit, "queries": ["we have quickbooks online", "my aviation cleaning business"],
           "distinctive_queries": ["we have quickbooks online", "my aviation cleaning business"]}
    assert bootstrap._band(two) == "strong", "two independent facets still make a strong match"


def test_a_loose_subject_score_caps_the_band_and_a_close_one_carries_a_semantic_find():
    two = {"queries": ["a b c", "d e f"], "distinctive_queries": ["a b c", "d e f"], "coverage": 1.0, "passage_coverage": 1.0}
    assert bootstrap._band({**two, "subject": 0.50, "subject_strong": 0.60}) == "possible"
    assert bootstrap._band({**two, "subject": 0.65, "subject_strong": 0.60}) == "strong"
    sem = {"queries": [], "distinctive_queries": [], "coverage": 0.0, "passage_coverage": None, "semantic_only": True}
    assert bootstrap._band({**sem, "subject": 0.65, "subject_strong": 0.60}) == "possible", "meaning alone is offered, never pre-ticked"
    assert bootstrap._band({**sem, "subject": 0.55, "subject_strong": 0.60}) == "possible"
    assert bootstrap._band({**two, "subject": None}) == "strong", "no embeddings: the check is skipped"


# ---------------------------------------------------------------- the scan, with the subject check

def _fake_subject(ids, qb=0.2, ai=0.9):
    def f(project_id, project):
        out = {}
        for sid in ids["ai"]:
            out[sid] = (ai, [])
        for i, sid in enumerate(ids["filler"]):
            out[sid] = (round(0.1 + 0.01 * i, 3), [])
        for sid in ids["qb"]:
            out[sid] = (qb, [])
        return dict(sorted(out.items(), key=lambda kv: -kv[1][0]))
    return f


def test_off_subject_matches_are_dropped_and_on_subject_ones_found(monkeypatch):
    pid, ids = _library()
    monkeypatch.setattr(bootstrap, "_subject_scores", _fake_subject(ids))
    monkeypatch.setattr(bootstrap, "_semantic_hit", lambda sid, sim, best: {
        "source_id": sid, "title": (db.get_source(sid) or {}).get("title"), "channel": None, "platform": None,
        "url": None, "published_at": None, "score": sim, "coverage": 0.0, "passage_coverage": None, "queries": [],
        "distinctive_queries": [], "passages": [], "terms": [], "subject": sim, "semantic_only": True})
    r = bootstrap.scan(pid)
    got = {h["source_id"]: h for h in r["sources"]}
    assert not set(ids["qb"]) & set(got), "a passing mention of QuickBooks in an M&A interview is not about this project"
    assert set(ids["ai"]) <= set(got), "the sources that are about the brief are on the card"
    assert all(got[s]["band"] in ("strong", "possible") for s in ids["ai"])
    assert not any(h["band"] == "strong" and h.get("semantic_only") for h in r["sources"])
    sub = db.last_bootstrap_run(pid)["subject"]
    assert sub["dropped"] >= 1 and sub["of"] == len(ids["ai"]) + len(ids["filler"]) + len(ids["qb"])
    assert sub["min"] >= sub["p90"] - 1e-6, "the bar is a rank within this library, not a fixed number"


def test_without_embeddings_the_scan_still_runs_and_no_short_clause_is_strong(monkeypatch):
    pid, ids = _library()
    monkeypatch.setattr(bootstrap, "_subject_scores", lambda *a: None)
    r = bootstrap.scan(pid)
    for h in r["sources"]:
        if set(h["queries"]) == {"we have quickbooks online"}:
            assert h["band"] == "possible"
    assert db.last_bootstrap_run(pid)["subject"] is None


def test_the_real_subject_check_runs_on_stored_vectors():
    pid, ids = _library()
    s = bootstrap._subject_scores(pid, db.get_project(pid))
    assert s is not None and set(ids["ai"]) <= set(s)
    sims = [v[0] for v in s.values()]
    assert sims == sorted(sims, reverse=True), "closest first, so additions take the best"
    best_ai = max(s[x][0] for x in ids["ai"])
    assert best_ai > max(s[x][0] for x in ids["filler"]), "the brief's own subject is closer than unrelated sources"


def test_old_suggestions_are_reported_stale():
    assert bootstrap.SCAN_VERSION == "recall-4"
