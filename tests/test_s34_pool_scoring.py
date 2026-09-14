"""S34 — 23 million set intersections, one item at a time (0.63.19). (Sorts after test_s33.)

`/api/projects/{id}/pool` measured **7.2–8.5 s on an idle server** — the only surface in the app that was genuinely
slow once the post-restart warm-up was out of the way. The cost was not the 10,319 candidates: `_potential` scores
each item against **every open question**, and Kyle's project has **2,689** of them. 8,499 items × 2,689 questions
is 23 million set intersections per request.

**`question_index` is exact, not an approximation.** A question sharing no token with the item scores 0 in the
original loop too, so skipping it cannot change an answer. Measured on his live rows: **identical scores on all
8,499 items, 3.67 s → 1.11 s.**

**And the first benchmark lied.** A synthetic corpus at his scale — 10,319 candidates, 2,689 questions — said the
index was barely worth having, because the synthetic questions shared only **67** distinct tokens, so every item
overlapped nearly every question. His real questions carry **6,683**. The shape of the data was the whole variable;
inventing it gave the wrong answer and his own rows gave the right one.

`gap_terms_cached` then removes the rest: `_gap_terms` builds a token set per open question and both `pool` and
`seen_for_query` were calling it fresh every request, while `api_sources` had cached it since 0.46.1. One place now
serves every caller, and the index is cached with the terms it belongs to.
"""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pool_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import candidates, db  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _questions(n: int, words: list[str]) -> list[tuple[str, str, set[str]]]:
    import random
    random.seed(11)
    return [(f"q{i}", f"question {i}", {*random.sample(words, 6)}) for i in range(n)]


WORDS = [f"w{i:04d}" for i in range(900)]          # a realistic spread, not 67 tokens shared by everything


# ------------------------------------------------------------------ the index is exact

def test_the_index_gives_the_same_answer_as_the_full_scan():
    """The property that makes this safe to ship: it is an index, not a heuristic."""
    import random
    random.seed(5)
    qs = _questions(400, WORDS)
    idx = candidates.question_index(qs)
    for _ in range(300):
        t = {*random.sample(WORDS, 8)}
        assert candidates._best_fit(t, qs, idx) == candidates._best_fit(t, qs, None)


def test_it_matches_on_the_questions_that_share_a_word():
    qs = [("q1", "seller financing terms", {"seller", "financing", "terms"}),
          ("q2", "lease assignment", {"lease", "assignment"})]
    idx = candidates.question_index(qs)
    label, share = candidates._best_fit({"seller", "financing", "terms"}, qs, idx)
    assert label == "seller financing terms" and share == 1.0


def test_an_item_sharing_nothing_fits_nothing():
    qs = [("q1", "seller financing", {"seller", "financing"})]
    idx = candidates.question_index(qs)
    assert candidates._best_fit({"laundromat", "vending"}, qs, idx) == (None, 0.0)


def test_no_questions_at_all_is_not_an_error():
    idx = candidates.question_index([])
    assert candidates._best_fit({"anything"}, [], idx) == (None, 0.0)
    assert candidates._potential("a title", "a description", [], set(), None, [], qindex=idx)[1] is None


def test_potential_is_unchanged_by_passing_an_index():
    """The score, the fit and the reasons must all be identical — the index is a speed-up, nothing else."""
    qs = _questions(120, WORDS)
    idx = candidates.question_index(qs)
    vocab = {*WORDS[:40]}
    for title in ("w0001 w0002 w0003 how to buy", "nothing in common here", "w0500 w0501 due diligence"):
        assert (candidates._potential(title, "w0004 w0005", qs, vocab, 60, [], qindex=idx)
                == candidates._potential(title, "w0004 w0005", qs, vocab, 60, []))


def test_the_index_is_actually_faster_on_a_realistic_spread():
    """Not a benchmark with a floor — a guard that the index has not silently become the slow path."""
    import random
    random.seed(9)
    qs = _questions(1200, WORDS)
    idx = candidates.question_index(qs)
    items = [{*random.sample(WORDS, 8)} for _ in range(400)]
    a = time.perf_counter()
    for t in items:
        candidates._best_fit(t, qs, None)
    plain = time.perf_counter() - a
    a = time.perf_counter()
    for t in items:
        candidates._best_fit(t, qs, idx)
    indexed = time.perf_counter() - a
    assert indexed < plain, f"indexed {indexed:.3f}s vs plain {plain:.3f}s"


# ------------------------------------------------------------------ the terms are computed once per revision

def test_the_gap_terms_and_index_are_cached_on_the_research_revision(fresh, monkeypatch):
    p = db.create_project("pool", brief="buying accounting firms")
    calls = {"n": 0}
    real = candidates._gap_terms

    def counted(pid):
        calls["n"] += 1
        return real(pid)

    monkeypatch.setattr(candidates, "_gap_terms", counted)
    a = candidates.gap_terms_cached(p["id"])
    b = candidates.gap_terms_cached(p["id"])
    assert calls["n"] == 1, "the second call must be served from the cache"
    assert a[2] is b[2]                                  # the same index object, not a rebuilt one


def test_a_change_in_research_state_recomputes_them(fresh, monkeypatch):
    p = db.create_project("pool", brief="b")
    calls = {"n": 0}
    real = candidates._gap_terms
    monkeypatch.setattr(candidates, "_gap_terms", lambda pid: (calls.__setitem__("n", calls["n"] + 1), real(pid))[1])
    candidates.gap_terms_cached(p["id"])
    with db.tx() as conn:                                # a new open question is a new research revision
        conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", ("tq1", p["id"], "what do lenders require?", "open", 1.0, 1.0))
    candidates.gap_terms_cached(p["id"])
    assert calls["n"] == 2


def test_the_pool_still_answers_with_the_same_shape(fresh):
    p = db.create_project("pool", brief="buying businesses")
    s = db.upsert_source(platform="youtube", external_id="sk1", url="https://youtu.be/sk1",
                         title="how to read a CIM", description="due diligence basics", status="skipped")
    db.add_project_sources(p["id"], [s["id"]])
    out = candidates.pool(p["id"])
    assert out["total"] >= 1 and out["items"][0]["kind"] == "skipped"
    assert "potential" in out["items"][0] and "why" in out["items"][0]
