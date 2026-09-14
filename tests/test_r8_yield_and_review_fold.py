"""0.55.1 — the shared yield, and the review stack that hid the queue controls.

Two things, both from the same live session and both about a screen you cannot get past.

**jobs.Yield.** 0.55.0 made `extract_claims` hand its worker back, but it leaned on a re-trigger that happened to
exist for claims and does not exist for anything else. `rank_proposed` has the same shape — measured `work_p90`
384 s against three AI workers, and a 398-video channel is five batches — and had no way to yield at all. The
mechanism is now shared: a job raises `jobs.Yield` at a safe boundary with its progress already persisted, and
`jobs.execute` requeues it immediately, no delay, no attempt counted, because this is neither a failure nor a
wait.

**The review stack.** Three review cards (107 + 93 + 398 videos) each carrying a 320px scrolling list made a page
whose In-progress card could not be reached: the inner lists swallow the wheel, so "scroll further down" never
arrives. The queue controls — including the pause button — were unreachable exactly when the queue was busiest.
(Sorts after test_r7.)"""
from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_y8_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, jobs, relevance  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests.frontend_helpers import ui_source  # noqa: E402

UI = pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "index.html"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _collection(pid: str, n: int) -> str:
    coll = db.upsert_collection("channel", "UCyield0001", "https://www.youtube.com/@yield", "A big channel")
    db.link_project_collection(pid, coll["id"]) if hasattr(db, "link_project_collection") else None
    for i in range(n):
        src = db.upsert_source(platform="youtube", external_id=f"yld{i:08d}", url=f"https://www.youtube.com/watch?v=yld{i:08d}",
                               status="proposed", title=f"Video {i} about design systems and interface work",
                               description="A talk about product design, navigation and information architecture.", duration=900)
        db.link_source_collection(src["id"], coll["id"])
    return coll["id"]


# ---------------------------------------------------------------- the shared yield

def test_a_yield_is_requeued_immediately_and_costs_no_attempt(monkeypatch):
    """A yield is neither a failure nor a wait: straight back to queued, no delay, no attempt burned."""
    jid = db.create_job("rank_proposed", {"collection_id": "c", "project_id": "p"})["id"]
    claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    monkeypatch.setattr(jobs, "run_job", lambda job: (_ for _ in ()).throw(jobs.Yield("paused after 2 batches")))
    assert jobs.execute(claimed, worker_id="w") == "queued"
    row = db.get_job(jid)
    assert row["status"] == "queued" and row["attempts"] == 0
    assert (row["not_before"] or 0) <= db.now() + 1, "no delay: another worker may take it, this one moves on"
    assert "paused" in (row["message"] or "")
    assert any(e["event_type"] == "yielded" for e in db.job_events(jid))


def test_ranking_stops_after_its_quota_persists_what_it_scored_and_resumes():
    p = db.create_project("Design", "How complex web apps stay simple")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))
    with pytest.raises(jobs.Yield) as e:
        relevance.rank_collection(coll, p["id"], want=20)
    assert "paused" in str(e.value)
    scored = [r for r in db.proposed_sources(coll, p["id"]) if r.get("relevance") is not None]
    assert len(scored) == relevance.BATCH * relevance.BATCHES_PER_RUN, "every completed batch is persisted before leaving"
    # resuming ranks only what is still unscored — no paid call is made twice, and with one batch left it finishes
    res = relevance.rank_collection(coll, p["id"], want=20)
    scored2 = [r for r in db.proposed_sources(coll, p["id"]) if r.get("relevance") is not None]
    assert len(scored2) > len(scored) and res.get("ranked")
    assert all(r.get("relevance") is not None for r in db.proposed_sources(coll, p["id"])[:relevance.POOL])


def test_a_short_collection_never_yields():
    p = db.create_project("Small", "a brief")
    coll = _collection(p["id"], 10)
    res = relevance.rank_collection(coll, p["id"], want=5)      # must not raise
    assert res["ranked"] >= 1


# ---------------------------------------------------------------- the review stack

def test_the_queue_controls_sit_above_the_review_stack():
    """Ordering in the DOM is the fix: In-progress is what you reach for WHILE reviewing, not after."""
    html = ui_source(UI.parent)
    assert html.index('id="jobsCard"') < html.index('id="reviewWrap"'), "the queue card must come before the review cards"
    assert html.index('id="bootCard"') < html.index('id="reviewWrap"')


def test_review_cards_after_the_first_start_folded():
    html = ui_source(UI.parent)
    assert "RVFOLD" in html and ".rv.folded .list" in html and ".rv.folded .rvfoot" in html
    assert "RVFOLD[c.id] !== undefined ? RVFOLD[c.id] : idx > 0" in html, "default folded for every card after the first"
    assert 'class="row rvfoot"' in html, "the ingest buttons fold away with their list"
