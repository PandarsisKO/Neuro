"""S16 — "Modern CPA" returned house-flipping videos (0.62.0). (Sorts after test_s15.)

Kyle: *"discover feature still isnt working ... NONE of the results are valuable to the search at all."* He searched
**Modern CPA** in the business-acquisition project and got eight sources back: house flipping, clinic website
design, Mike Rowe, "Design with Claude Code". Every one matched the word **modern**, and the app said so in its own
explanation line.

Measured on his live library (1,229 sources with chunks, 2026-09-10):

* **"modern" is in 128 sources, "cpa" in 130.** The anchor rule picks the rarest word, so a two-source margin
  decided which word the search was about, and it picked the one that names nothing.
* Scored against a target set (sources mentioning CPA 3+ times or in the title — 45 of them): the shipped rule
  returned 128 sources of which **3** were on target — **2% precision, 7% recall**.
* **Requiring every query term** — the obvious fix, and the one that would have looked best in a demo — gives 27%
  precision and leaves recall at 7%: it throws away 93% of the right answers. Rejected on the measurement.
* **The correct anchor plus a mention floor** gives **62% precision at 100% recall** (73 sources): "cpa, mentioned
  at least twice". 66% of the "modern" sources say it exactly once in a whole transcript, against 44% for "cpa".

The anchor choice itself is NOT a statistics problem, and this module records why. Nothing countable separates the
two words: equal rarity, equally often in titles (2 each), and mentions-per-source prefers "cpa" (2.35 v 1.66) but
prefers "designing" (6.54, in 41% of the library) over both — so that measure is a coincidence here, not a rule.
The difference is that "modern" is a modifier: it attaches to any topic in any field and denotes none. So it is a
written list a human can read and correct, used for anchor CHOICE only, and it is an assumption rather than a
measurement — which is the honest label for it.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_anchor_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, library  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


@pytest.fixture(autouse=True)
def _no_jobs_left_behind():
    """Tests here queue real jobs (`refresh_research` from a steering call). A worker pool started by ANOTHER module
    can claim one afterwards and run it against whatever database is current by then, which is how a queued job from
    this module made an unrelated embedding test fail. So nothing queued survives a test in this file."""
    yield
    try:
        with db.tx() as conn:
            conn.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('queued','running')")
    except Exception:  # noqa: BLE001
        pass

def _source(sid, title, chunks, channel="ch"):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, channel, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (sid, "youtube", sid, f"https://x/{sid}", title, channel, "ready", 1.0, 1.0))
        for i, c in enumerate(chunks):
            conn.execute("INSERT INTO chunks (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                         (sid, i, i * 60.0, i * 60.0 + 60.0, c))


def _filler(n=5, word="marketing"):
    """Enough unrelated sources that a share of the library is under ANCHOR_TOO_COMMON_SHARE. Two sources out of
    three IS most of a library, and the rule is right to say so — these fixtures are standing in for a real one."""
    for i in range(n):
        _source(f"f{i}", f"Unrelated {i}", [f"{word} talk {i}", f"more {word}", f"{word} again"])


# ------------------------------------------------------------------ the modifier list

def test_a_modifier_never_becomes_the_anchor(lib):
    """The whole complaint in one assertion: 'modern' may be rarer, and it still does not name the subject."""
    _source("cpa1", "Working with your CPA", ["your cpa should model the deal", "ask the cpa for the addbacks", "cpa fees"])
    _source("cpa2", "CPA basics", ["a cpa reviews the books", "the cpa signs off", "cpa letters"])
    # 'modern' deliberately made RARER than 'cpa' — this is Kyle's situation, inverted even further
    _source("m1", "Flip houses fast", ["a modern kitchen sells", "granite counters", "paint the trim"])
    _filler()
    a = library.query_anchor({"modern", "cpa"})
    assert a["term"] == "cpa"
    assert a["skipped_generic"] == ["modern"]
    assert "generic" in a["reason"]


def test_a_search_made_only_of_modifiers_is_called_vague(lib):
    _source("x", "Best modern things", ["the best modern approach", "simply the best", "a modern take"])
    a = library.query_anchor({"modern", "best"})
    assert a["term"] is None and a["all_generic"] is True
    assert sorted(a["skipped"]) == ["best", "modern"]
    assert "names a subject" in a["reason"]


def test_a_modifier_still_matches_and_still_counts_towards_coverage(lib):
    """Excluded from CHOOSING the anchor, never from matching — otherwise the rule would hide real answers."""
    _source("s1", "Modern CPA practice", ["the modern cpa firm runs on software", "a modern cpa bills monthly",
                                          "cpa staffing", "modern tooling for the cpa"])
    r = library.recall(None, "modern cpa")
    assert [s["source_id"] for s in r["suggestions"]] == ["s1"]
    assert "modern" in r["suggestions"][0]["covered_terms"]


# ------------------------------------------------------------------ aboutness, not presence

def test_one_mention_in_a_long_source_is_not_aboutness(lib):
    """66% of the sources containing 'modern' contain it exactly once in an entire transcript."""
    long_passing = ["the cpa reviews every deal"] + ["unrelated talk about marketing"] * 6 + ["ask your cpa again"]
    long_failing = ["one throwaway line about a cpa"] + ["unrelated talk about marketing"] * 7
    _source("keep", "Deal diligence", long_passing)
    _source("drop", "Marketing show", long_failing)
    _source("other", "CPA hour", ["cpa cpa", "cpa fees explained", "the cpa engagement letter"])
    _filler()
    r = library.recall(None, "cpa diligence")
    ids = {s["source_id"] for s in r["suggestions"]}
    assert "drop" not in ids
    assert r["rejected"]["anchor_mentioned_once"] >= 1


def test_a_short_source_is_not_punished_for_saying_it_once(lib):
    """The floor is a statement about a long transcript. A two-chunk note that says it once has said it in half of
    everything it contains, so the rule waits (ANCHOR_MENTION_MIN_CHUNKS)."""
    _source("short", "A note on CPAs", ["a cpa handles the quality of earnings", "that is all"])
    _source("other", "CPA hour", ["cpa cpa", "cpa fees explained", "the cpa engagement letter"])
    _filler()
    r = library.recall(None, "cpa earnings")
    assert "short" in {s["source_id"] for s in r["suggestions"]}


def test_the_reason_says_how_many_times(lib):
    _source("s1", "CPA deep dive", ["the cpa models addbacks", "cpa fees", "your cpa and the bank", "cpa letters"])
    _source("s2", "Addbacks explained", ["addbacks and the cpa", "more addbacks", "addbacks again", "cpa notes"])
    _filler()
    r = library.recall(None, "cpa addbacks")
    why = " · ".join(r["suggestions"][0]["why"])
    assert "×" in why and "cpa" in why


# ------------------------------------------------------------------ the share bar

def test_a_word_in_most_of_the_library_cannot_anchor():
    """ANCHOR_MAX_DF_SHARE was 0.5, which would anchor on 'accountant' — in 49.6% of Kyle's library. The measured
    distribution puts every topic word at or below a quarter."""
    assert library.ANCHOR_MAX_DF_SHARE == 0.25


def test_the_share_bar_does_not_apply_to_a_tiny_library(lib):
    """A proportion of four sources is not a proportion. This guard turns the tightening OFF, so it can never
    invent a false negative — the same shape as ANCHOR_MAX_TERMS and ANCHOR_MIN_SOURCES in 0.60.2."""
    _source("a", "UX work", ["ux for complex workflows", "more ux", "ux again"])
    _source("b", "UX too", ["ux patterns", "ux tables", "ux forms"])
    _source("c", "Business", ["complex workflows for growth"] * 3)
    _source("d", "More business", ["complex workflows everywhere"] * 3)
    a = library.query_anchor({"ux", "complex", "workflows"})
    assert a["term"] == "ux"                       # 2 of 4 sources = 50%, far above 0.25, and correctly ignored
    assert db.sources_with_chunks() < library.ANCHOR_SHARE_MIN_LIBRARY


# ------------------------------------------------------------------ Discover says so out loud

def test_discover_calls_a_vague_search_vague_and_still_shows_the_hits(lib, monkeypatch):
    """The weak-query judgement existed in the bootstrap scan since 0.61.0 and Discover never got it, which is why
    eight rows were presented as answers. Nothing is hidden — they are tagged and they stop counting as strong."""
    from neurosearch import discover
    _source("s1", "Best modern kitchens", ["the best modern kitchen", "a modern remodel", "best practices"])
    p = db.create_project("proj", brief="b")
    monkeypatch.setattr(discover, "_library_query", lambda *a, **k: "best modern")
    out = discover.discover(p["id"], refine=None, count=1, verify=False, mode="library_only")
    vq = out["library"].get("vague_query")
    assert vq and "generic modifier" in vq["why"]
    assert all(s.get("generic_match") for s in out["library"]["suggestions"])


# ------------------------------------------------------------------ saturation (0.62.4)

def test_a_project_that_owns_the_subject_is_told_so(lib):
    """Kyle, after the anchor fix: *"discover search still is useless."* Measured on his project, and it was not a
    ranking failure — the pool was leftovers:

        term                 in library   already in this project   outside
        cpa                        130          115  (88%)              15
        sba                        212          191  (90%)              21
        quality of earnings         27           25  (93%)               2
        addbacks                     7            7 (100%)               0

    Library recall can only offer what the project does not have, so on its own subject this project has almost
    nothing left — 8 sources with two or more mentions of "cpa", seven about short-term rentals. Meanwhile the card
    said "no new acquisition needed", which is a false claim about the dregs."""
    p = db.create_project("owns", brief="buying businesses")
    owned = ["o1", "o2", "o3", "o4"]
    for sid in owned:
        _source(sid, f"CPA talk {sid}", ["the cpa models the deal", "cpa fees", "your cpa and the bank"])
        db.add_project_sources(p["id"], [sid])
    _source("left", "One left over", ["a cpa for rentals", "cpa again", "rental tax"])
    _filler()
    cov = library.coverage_of(p["id"], "cpa")
    assert cov["in_library"] == 5 and cov["in_project"] == 4 and cov["outside"] == 1
    assert cov["saturated"] is True
    assert "web search" in cov["note"] and "search inside the project" in cov["note"]


def test_a_thin_project_is_not_called_saturated(lib):
    p = db.create_project("thin", brief="b")
    for sid in ("a", "b", "c", "d"):
        _source(sid, f"CPA {sid}", ["cpa one", "cpa two", "cpa three"])
    db.add_project_sources(p["id"], ["a"])
    _filler()
    cov = library.coverage_of(p["id"], "cpa")
    assert cov["saturated"] is False and cov["in_project"] == 1 and cov["outside"] == 3


def test_recall_reports_coverage_beside_its_suggestions(lib):
    _source("s1", "CPA deep dive", ["the cpa models addbacks", "cpa fees", "your cpa and the bank", "cpa letters"])
    _source("s2", "Addbacks", ["addbacks and the cpa", "more addbacks", "cpa notes"])
    _filler()
    r = library.recall(None, "cpa addbacks")
    assert r["owned"]["term"] == r["anchor"]["term"]        # coverage is reported for the term that decided the match
    assert r["owned"]["in_library"] == 2 and r["owned"]["saturated"] is False


def test_saturation_never_suppresses_the_web_search(lib):
    """Saturation is the REASON to search the web, so it must not count as the library covering the request."""
    from neurosearch import discover
    p = db.create_project("sat", brief="b")
    for sid in ("o1", "o2", "o3"):
        _source(sid, f"CPA {sid}", ["cpa one", "cpa two", "cpa three"])
        db.add_project_sources(p["id"], [sid])
    _source("left", "Leftover", ["a cpa mention", "cpa twice", "unrelated"])
    _filler()
    out = discover.discover(p["id"], refine="cpa fees", count=1, verify=False, mode="library_only")
    assert out["library"]["saturated"]["saturated"] is True
    assert out["web_skipped"] is True and "Library only" in out["note"]      # mode said library_only, not saturation
