"""S35 — a fit is a claim on screen, and the pool was a pass in a request (0.63.20). (Sorts after test_s34.)

Two faults behind one slow surface, found by profiling the pool after 0.63.19's index had already taken it from
7–8 s to 2.8 s cold / 1.5 s warm on Kyle's machine.

**The screen was making a claim nothing had measured.** `_potential` has awarded points for a fit only at or above
0.34 since S5, but `_best_fit` returned the argmax whatever its share was, and `fits` is rendered on every pool row
and counted in the header chip. On his project that chip read **"8,917 fit an open question"** out of 8,970 items —
while **196** cleared the bar, and **49.6%** of items scored under 0.10, which is a single function word in common.
`and`, `what` and `the` are in ~80% of his 2,726 open questions. So the pool told him almost everything it knew
fitted something, which is the same defect as the 0.63.12 header that read 200 for 17,845 findings: a number that
is worse than absent because it looks like an answer.

Closing it made the index faster, because the bar is what licenses pruning. A question of `den` tokens needs
`_need_for(den)` of them shared; leaving its `need - 1` MOST COMMON tokens out of the postings cannot lose it, by
pigeonhole, and those are exactly the tokens that carried the cost. Verified on his 13,034 real rows: **zero
mismatches against the plain scan, 8.3× faster**, postings 83,380 → 56,454.

**And the pool had no cache and no background writer** — the last such screen. `_pool_items` is the assembly,
cached on `db.project_pool_revision`; `pool` filters, sorts and slices it. Measured: **2.30 s → 0.053 s warm.**
The revision deliberately omits the `jobs` component that `project_view_revision` carries, because a 2 s assembly
keyed on job churn is retired before it can be reused — the mistake 0.62.0 already paid for.
"""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pool2_"))
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


WORDS = [f"w{i:04d}" for i in range(600)]


def _questions(n: int, lengths=(3, 6, 12, 24), seed: int = 11):
    """Questions of MIXED length, because the prune depth is derived from each question's own length — a corpus of
    one length would exercise one `need` and prove nothing about the others."""
    import random
    random.seed(seed)
    out = []
    for i in range(n):
        k = lengths[i % len(lengths)]
        out.append((f"q{i}", f"question {i}", {*random.sample(WORDS, k)}))
    return out


def _add_question(pid: str, tid: str, question: str) -> None:
    with db.tx() as conn:
        conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", (tid, pid, question, "open", 1.0, 1.0))


# ------------------------------------------------------------------ the bar

def test_nothing_below_the_bar_is_reported_as_a_fit():
    """One shared word out of a twelve-word question is not a fit, and saying so was the whole bug."""
    qs = [("q1", "how do I structure the seller note on an accounting firm acquisition",
           {"how", "structure", "seller", "note", "accounting", "firm", "acquisition", "the", "and", "what", "for", "does"})]
    idx = candidates.question_index(qs)
    assert candidates._best_fit({"and"}, qs, idx) == (None, 0.0)
    assert candidates._best_fit({"the", "and", "what"}, qs, idx) == (None, 0.0)
    label, share = candidates._best_fit({"how", "structure", "seller", "note", "accounting"}, qs, idx)
    assert label and share >= candidates.FIT_MIN_SHARE


def test_the_bar_is_the_same_one_the_score_uses():
    """`_potential` awards fit points at `FIT_MIN_SHARE`; a label below it would be a reason with no points."""
    qs = [("q1", "seller financing terms", {"seller", "financing", "terms", "on", "the", "note"})]
    idx = candidates.question_index(qs)
    for t in ({"seller"}, {"the", "note"}, {"seller", "financing", "terms"}):
        _score, fit, why = candidates._potential(" ".join(t), "", qs, set(), None, [], qindex=idx)
        assert bool(fit) == any(w.startswith("fits an open question") for w in why)


def test_need_for_matches_the_comparison_the_verification_makes():
    """Derived by the predicate, never by `ceil(share * den)`: 0.34 * 50 is 17.000000000000004 in binary, so a
    ceiling would demand 18 shared tokens for a question that 17 genuinely clear — and would then prune it."""
    for den in range(1, 61):
        need = candidates._need_for(den)
        assert need / den >= candidates.FIT_MIN_SHARE, den
        assert need == 1 or (need - 1) / den < candidates.FIT_MIN_SHARE, den


# ------------------------------------------------------------------ the prune is exact

def test_the_pruned_index_gives_the_same_answer_as_the_full_scan():
    """The property that licenses it: dropping a question's commonest tokens cannot lose that question."""
    import random
    random.seed(5)
    qs = _questions(500)
    idx = candidates.question_index(qs)
    for _ in range(600):
        t = {*random.sample(WORDS, random.choice((4, 9, 18, 30)))}
        assert candidates._best_fit(t, qs, idx) == candidates._best_fit(t, qs, None)


def test_a_question_reachable_only_through_its_rare_words_is_still_found():
    """The pigeonhole claim, stated as a case: the item shares everything, so the commonest words being absent from
    the postings must not hide the question."""
    common = {"the", "and", "what", "for"}
    qs = [(f"q{i}", f"question {i}", common | {f"rare{i}", f"rarer{i}"}) for i in range(40)]
    idx = candidates.question_index(qs)
    label, share = candidates._best_fit(common | {"rare7", "rarer7"}, qs, idx)
    assert label == "question 7" and share == 1.0
    assert candidates._best_fit(common | {"rare7", "rarer7"}, qs, None) == (label, share)


def test_the_prune_removes_exactly_the_commonest_tokens_of_each_question():
    """A guard that the index has not quietly become the plain scan again, stated as the rule rather than a ratio:
    each question keeps `den - (need - 1)` of its tokens, and the ones it loses are its commonest."""
    common = ["and", "are", "business", "for", "the", "what"]      # df 200 each; ties break alphabetically
    qs = [(f"q{i}", f"q{i}", {*common} | {f"r{i}{c}" for c in "abcdef"}) for i in range(200)]
    idx = candidates.question_index(qs)
    den = 12
    drop = candidates._need_for(den) - 1
    assert drop > 0
    assert idx["postings"] == len(qs) * (den - drop) < sum(len(q[2]) for q in qs)
    for w in common[:drop]:                             # in every question, and unable to decide any of them
        assert w not in idx["post"]
    for i in range(200):                                # every question is still reachable by its own rare words
        assert all(i in idx["post"][f"r{i}{c}"] for c in "abcdef")


def test_the_index_is_still_the_fast_path():
    import random
    random.seed(9)
    qs = _questions(1200)
    idx = candidates.question_index(qs)
    items = [{*random.sample(WORDS, 10)} for _ in range(400)]
    a = time.perf_counter()
    for t in items:
        candidates._best_fit(t, qs, None)
    plain = time.perf_counter() - a
    a = time.perf_counter()
    for t in items:
        candidates._best_fit(t, qs, idx)
    indexed = time.perf_counter() - a
    assert indexed < plain, f"indexed {indexed:.3f}s vs plain {plain:.3f}s"


def test_the_index_is_deterministic():
    """Postings are ordered by df then by the word, so two builds of the same questions agree — otherwise a tie
    would resolve differently between two processes and the same row would name two questions."""
    qs = _questions(120)
    a, b = candidates.question_index(qs), candidates.question_index(qs)
    assert a["post"] == b["post"] and a["qlen"] == b["qlen"]


# ------------------------------------------------------------------ the header counts what it says it counts

def test_fits_a_question_counts_only_items_that_clear_the_bar(fresh):
    """The chip on his screen read 8,917 of 8,970. One item here genuinely answers the open question and eleven
    share only its function words, so the honest count is 1."""
    p = db.create_project("pool", brief="buying accounting firms")["id"]
    _add_question(p, "t1", "what are the seller note terms on an accounting firm acquisition")
    for i in range(11):
        s_ = db.upsert_source(platform="youtube", external_id=f"nf{i}", url=f"https://youtu.be/nf{i}",
                              title=f"what are the {i}", description="what are the", status="skipped")
        db.add_project_sources(p, [s_["id"]])
    hit = db.upsert_source(platform="youtube", external_id="yes", url="https://youtu.be/yes",
                           title="seller note terms on an accounting firm acquisition",
                           description="seller note terms", status="skipped")
    db.add_project_sources(p, [hit["id"]])
    r = candidates.pool(p, limit=50)
    rows_with_a_label = [i for i in r["items"] if i["fits"]]
    assert r["counts"]["fits_a_question"] == len(rows_with_a_label) == 1
    assert rows_with_a_label[0]["id"] == hit["id"]


# ------------------------------------------------------------------ the assembly is cached, and the cache is honest

def test_the_pool_is_assembled_once_and_then_filtered(fresh, monkeypatch):
    p = db.create_project("pool", brief="buying accounting firms")["id"]
    for i in range(30):
        candidates.remember([{"external_id": f"c{i}", "url": f"https://example.com/c{i}",
                              "title": f"how to value a firm {i}", "description": "valuation playbook"}], "youtube", p, {"kind": "test"})
    calls = {"n": 0}
    real = candidates._pool_items

    def counted(pid):
        calls["n"] += 1
        return real(pid)

    monkeypatch.setattr(candidates, "_pool_items", counted)
    a = candidates.pool(p, limit=5)
    b = candidates.pool(p, limit=5, rank_by="newest")
    c = candidates.pool(p, limit=5, kind="candidates")
    assert calls["n"] == 1, "the assembly must run once per revision, not once per request"
    assert a["total"] == b["total"] and c["total"] <= a["total"]


def test_sorting_and_filtering_never_mutate_the_cached_list(fresh):
    """The cached dicts are shared with every later caller, so a sort in place would reorder someone else's answer."""
    p = db.create_project("pool", brief="buying accounting firms")["id"]
    for i in range(20):
        candidates.remember([{"external_id": f"m{i}", "url": f"https://example.com/m{i}", "title": f"title {i}",
                              "description": "d"}], "youtube", p, {"kind": "test"})
    first = [i["id"] for i in candidates.pool(p, limit=100)["items"]]
    candidates.pool(p, limit=100, rank_by="newest")
    candidates.pool(p, limit=100, kind="skipped")
    assert [i["id"] for i in candidates.pool(p, limit=100)["items"]] == first


def test_a_new_candidate_moves_the_pool_revision(fresh):
    p = db.create_project("pool", brief="buying accounting firms")["id"]
    before = db.project_pool_revision(p)
    candidates.remember([{"external_id": "new1", "url": "https://example.com/new", "title": "a new one",
                          "description": "d"}], "youtube", p, {"kind": "test"})
    assert db.project_pool_revision(p) != before


def test_starring_a_source_moves_the_pool_revision(fresh):
    """`project_sources` has no `updated_at`, so without the priority count this change would be invisible — and
    every row's `same_creator_as_priority` depends on it."""
    p = db.create_project("pool", brief="b")["id"]
    src = db.upsert_source(platform="youtube", external_id="aaa", url="https://youtu.be/aaa", title="t",
                           channel="Chan", status="skipped")
    db.add_project_sources(p, [src["id"]])
    before = db.project_pool_revision(p)
    db.set_source_priority(p, [src["id"]], True)
    assert db.project_pool_revision(p) != before


def test_removing_a_source_from_the_project_moves_the_pool_revision(fresh):
    """Found by the frozen S5 gate rather than by this module. `remove_project_sources` sets `excluded=1` instead of
    deleting the row (0.34.2's durable marker), so neither the count nor `MAX(suggested_at)` nor the priority sum
    moved — and the pool went on offering a source the user had just removed. A cache that outlives the user's own
    decision is wrong, not stale (0.62.8)."""
    p = db.create_project("pool", brief="b")["id"]
    src = db.upsert_source(platform="youtube", external_id="bbb", url="https://youtu.be/bbb", title="t",
                           channel="Chan", status="skipped")
    db.add_project_sources(p, [src["id"]])
    assert src["id"] in {i["id"] for i in candidates.pool(p, limit=50)["items"]}
    before = db.project_pool_revision(p)
    db.remove_project_sources(p, [src["id"]])
    assert db.project_pool_revision(p) != before
    assert src["id"] not in {i["id"] for i in candidates.pool(p, limit=50)["items"]}


def test_a_job_heartbeat_does_not_move_the_pool_revision(fresh):
    """The whole reason this is not `project_view_revision`: a cache whose key changes faster than its value can be
    computed is not a cache (0.61.2, 0.62.0). During an ingest run the global `jobs` component moves constantly."""
    from neurosearch import jobs
    p = db.create_project("pool", brief="b")["id"]
    before = db.project_pool_revision(p)
    jobs.enqueue("external_demo", {"project_id": p})
    jobs.enqueue("external_demo", {"project_id": p, "n": 2})
    assert db.project_pool_revision(p) == before


def test_an_open_question_moves_the_pool_revision(fresh):
    """The fit term reads the open questions, so a question arriving must retire the scores — the 0.63.19 bug, one
    layer up."""
    p = db.create_project("pool", brief="b")["id"]
    before = db.project_pool_revision(p)
    _add_question(p, "t1", "how do I value an accounting firm")
    assert db.project_pool_revision(p) != before


def test_the_pool_is_in_the_background_warm_set():
    """A cached pass with no background writer is cold on every restart, which is a silent failure — nothing
    breaks, someone just waits (0.63.7). So the warm set is asserted by name."""
    import inspect

    from neurosearch import jobs
    src = inspect.getsource(jobs._warm_quality)
    assert 'candidates.pool' in src
