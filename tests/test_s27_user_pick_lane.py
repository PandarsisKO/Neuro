"""S27 — the thing the user just clicked runs next (0.63.5). (Sorts after test_s26.)

Measured on Kyle's live project before writing a line: of **2,507** completed `suggest_findings` jobs, **2,504 ran
in lane `normal`**, waiting a median of **2.6 hours** and up to **17 hours** for **25 seconds** of work. And
`bumped_at` was NULL on all 2,511 jobs ever created — the priority mechanism built in 0.45.12 had never once been
used, by anything.

The cause was a rule that is right for the case it was written for. `jobs.first_wave_lane` returns `normal` as soon
as a project has any findings, because there is nothing left to *bootstrap*:

    if db.connect().execute("SELECT COUNT(*) FROM project_notes WHERE project_id=? LIMIT 1", …):
        return "normal"          # already has findings: nothing to bootstrap

His project has 20,000 findings, so every source he clicked "Suggest findings" on himself joined the back of a
1,900-job background queue. Bootstrapping is not the only reason work should go first: **a source the user names in
a request is the strongest statement of intent the app ever receives** — they are sitting there waiting on that one
source — and it was the single case with no priority at all.

A sweep is not a pick, which is the whole distinction: "analyse everything" names no sources (the endpoint fills
them in from the project), and a request naming more than `USER_PICK_MAX` is a bulk action whose value does not
depend on any one item landing first. Ordering only — same provider, same model, same cost.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pick_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, db, jobs  # noqa: E402
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


@pytest.fixture(autouse=True)
def _no_jobs_left_behind(fresh):
    yield
    for j in db.list_jobs(limit=200):
        if j["status"] in ("queued", "running"):
            db.update_job(j["id"], status="cancelled")


def _project_with_findings(n_sources: int = 3) -> tuple[str, list[str]]:
    """A project past bootstrap — which is every project of Kyle's, and the case that had no priority."""
    p = db.create_project("big", brief="buying businesses")
    ids = []
    for i in range(n_sources):
        s = db.upsert_source(platform="youtube", external_id=f"vpick{i}", url=f"https://www.youtube.com/watch?v=vpick{i}",
                             title=f"video {i}", status="ready")
        db.add_project_sources(p["id"], [s["id"]])
        ids.append(s["id"])
    db.add_project_note(p["id"], "a finding that means this project is not bootstrapping", status="approved",
                        source_id=ids[0])
    assert jobs.first_wave_lane(p["id"], ids[1]) == "normal"        # the rule this release works around
    return p["id"], ids


# ------------------------------------------------------------------ the rule itself

def test_a_named_source_is_a_pick():
    assert jobs.user_pick_lane(True, 1) == "priority"
    assert jobs.user_pick_lane(True, jobs.USER_PICK_MAX) == "priority"


def test_a_sweep_is_not_a_pick():
    assert jobs.user_pick_lane(False, 1) is None                    # names nothing: the endpoint chose the sources
    assert jobs.user_pick_lane(False, 900) is None
    assert jobs.user_pick_lane(True, jobs.USER_PICK_MAX + 1) is None
    assert jobs.user_pick_lane(True, 0) is None


# ------------------------------------------------------------------ through the endpoint, on a project past bootstrap

def test_clicking_suggest_findings_on_one_source_goes_first(fresh):
    pid, ids = _project_with_findings()
    out = api.api_suggest(pid, api.SuggestIn(source_ids=[ids[1]]))
    assert out["lane"] == "priority"
    assert db.get_job(out["job"])["lane"] == "priority"


def test_analysing_the_whole_project_does_not(fresh):
    """Every source at once is a bulk purchase; making all of it priority would mean none of it is."""
    pid, _ = _project_with_findings()
    out = api.api_suggest(pid, api.SuggestIn(force=True))
    assert out["lane"] == "normal"


def test_a_priority_pick_is_claimed_before_an_older_normal_job(fresh):
    """The point of the lane, stated as the queue behaviour rather than as a column value."""
    pid, ids = _project_with_findings()
    bulk = db.create_job("suggest_findings", {"project_id": pid, "source_ids": ids, "force": True}, lane="normal")
    pick = api.api_suggest(pid, api.SuggestIn(source_ids=[ids[2]]))["job"]
    claimed = db.claim_job(kinds=("suggest_findings",), worker_id="w1")
    assert claimed and claimed["id"] == pick, "the source the user named must be claimed before the older sweep"
    db.update_job(claimed["id"], status="cancelled")
    db.update_job(bulk["id"], status="cancelled")


def test_read_deeper_stays_in_the_slow_lane(fresh):
    """A deep read is minutes of work carried by one local worker; jumping the queue with it would block the queue."""
    pid, ids = _project_with_findings()
    out = api.api_suggest(pid, api.SuggestIn(source_ids=[ids[1]], depth="deep"))
    assert out["lane"] == "slow"


def test_a_bootstrapping_project_still_gets_the_first_wave_rule(fresh):
    """This release adds a reason to go first; it removes none. A brand-new project has no findings and the
    first-wave rule is what makes it usable while the rest of it ingests."""
    p = db.create_project("new", brief="b")
    s = db.upsert_source(platform="youtube", external_id="npick1", url="https://www.youtube.com/watch?v=npick1",
                         title="only video", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    out = api.api_suggest(p["id"], api.SuggestIn(force=True))       # a sweep, so no user-pick lane
    assert out["lane"] == "priority"                               # but first_wave_lane still promotes it
