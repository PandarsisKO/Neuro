"""S17 — a discovery pass paid seven minutes to read a few counts (0.62.2). (Sorts after test_s16.)

Kyle: *"the search took much longer than the ~10 seconds advertised."* It took **195 s** — and on the run right
after 3,314 findings were approved, **432 s** — for a library-only Discover: no model call, no web request, no
dollars. I had assumed the library pass, and so had he. Staged timing (0.62.1 added it) settled it:

    discover.research_state   431.6 s
    discover.library            0.9 s     ← the pass we both blamed, warm
    recall.search               6.9 s     p50, cold
    recall.mentions / anchor / profiles / scope   all milliseconds

The seven minutes were `claims.ensure` running BEFORE the discovery: `harvest` across 17,119 notes, then every one
of 4,331 Claims assessed, then the whole knowledge map, tension detection, community synthesis and every evidence
target — so that a discovery pass could read some counts and a list of open questions to steer itself.

Two fixes, and one of them is arithmetic: `ensure` called `assess_project` and then `knowledge.refresh`, which
opens by calling `assess_project` itself — so every Claim in the project was assessed **twice per call**, 8,662
times instead of 4,331, for identical results. And steering does not need a current map, only a recent one, so
`ensure_cheap` reads what exists and queues the refresh as a `refresh_research` job on the `low` lane.

**A pass worth having is not worth having in a request** — the third time that sentence has been the fix this week
(0.61.2 the quality pass, 0.61.4/0.62.0 the findings rows, this).
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_steer_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import claims, db, knowledge  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _project_with_a_node():
    p = db.create_project("steer", brief="buying businesses")
    with db.tx() as conn:
        conn.execute("INSERT INTO project_knowledge_nodes (project_id, topic, state, why, evidence_classes, "
                     "missing_perspectives, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (p["id"], "seller financing", "developing", "two sources", "[]", "[]", 1.0))
    return p


def test_no_claim_is_assessed_twice_per_ensure(fresh, monkeypatch):
    """The arithmetic half: 4,331 Claims were being assessed 8,662 times for identical results."""
    p = db.create_project("dbl", brief="b")
    calls = []
    real = claims.assess_project
    monkeypatch.setattr(claims, "assess_project", lambda pid: (calls.append(pid), real(pid))[1])
    monkeypatch.setattr(knowledge, "detect", lambda pid: 0)
    claims.ensure(p["id"])
    assert len(calls) == 1


def test_steering_never_recomputes_the_research_state(fresh, monkeypatch):
    """`ensure_cheap` is what Discover uses: it reads the map that exists and queues the refresh."""
    p = _project_with_a_node()
    monkeypatch.setattr(claims, "ensure", lambda *a, **k: pytest.fail("ensure ran inside a steering call"))
    out = claims.ensure_cheap(p["id"])
    assert out["computed"] is False
    assert out["map"]["counts"]["developing"] == 1
    assert out["queued"]


def test_the_refresh_is_queued_once_not_once_per_request(fresh):
    p = _project_with_a_node()
    a = claims.ensure_cheap(p["id"])["queued"]
    b = claims.ensure_cheap(p["id"])["queued"]
    assert a == b                                      # deduped per project while one is still waiting
    rows = [j for j in db.list_jobs(limit=50) if j["kind"] == "refresh_research"]
    assert len(rows) == 1 and rows[0]["lane"] == "low"


def test_a_project_with_no_map_at_all_still_gets_one(fresh, monkeypatch):
    """The first pass on a project pays once, because there is nothing to steer by — and it is small by definition."""
    p = db.create_project("empty", brief="b")
    monkeypatch.setattr(knowledge, "detect", lambda pid: 0)
    out = claims.ensure_cheap(p["id"])
    assert out["computed"] is True


def test_the_refresh_job_runs_the_full_pass(fresh, monkeypatch):
    p = _project_with_a_node()
    seen = {}
    def fake_ensure(pid, **k):
        seen["pid"] = pid
        return {"harvested": 3}
    monkeypatch.setattr(claims, "ensure", fake_ensure)
    out = claims.run_refresh_job({"project_id": p["id"]})
    assert seen["pid"] == p["id"] and out["harvested"] == 3


def test_discover_says_how_current_its_steering_is(fresh, monkeypatch):
    from neurosearch import discover
    p = _project_with_a_node()
    out = discover.discover(p["id"], refine=None, count=1, verify=False, mode="library_only")
    assert out["research"]["as_of"] == "a moment ago"


def test_the_job_is_retryable_and_named_in_plain_language(fresh):
    from neurosearch import jobs
    assert "refresh_research" in jobs.RETRYABLE
    ui = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "neurosearch", "web", "index.html"), encoding="utf-8").read()
    assert "bringing the research state up to date" in ui
