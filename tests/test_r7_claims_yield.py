"""0.55.0 — a long job must give the worker back.

Kyle, live, for the third time in one day: *"extracting claims is STILL blocking transcription and findings."*

Measured on his running queue, and the ratio is the whole story:

    extract_claims     work_p50 237.55 s   work_p90 843.82 s
    suggest_findings   work_p50   0.95 s   wait_p50 4,781.99 s

One claims run occupies an AI worker for four to fourteen minutes. There are three. Behind it sat 1,128 findings
jobs, each under a second of actual work.

The two earlier attempts at this were both about ORDER — a priority lane (0.48.0) and a pause (0.48.2/0.51.0) —
and neither could have fixed it, because **a lane decides who is claimed next, not who is evicted.** Once a long
job is running, nothing short can get past it. The job has to yield voluntarily, which is free here: every group
is idempotent by `extraction_hash`, so stopping between groups costs nothing and resuming re-does nothing.
(Sorts after test_r6.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_yield_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claims, db, evals  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _many_candidates(n: int) -> str:
    """A project with more unnormalized candidates than one run is allowed to take."""
    g = evals.load_golden()
    pid = g["project_id"]
    for i in range(n):
        claims.add_claim(pid, f"Candidate proposition number {i} about financing and structure", origin="user")
    return pid


def test_the_bulk_pass_stops_after_its_quota_and_says_what_is_left():
    pid = _many_candidates(claims.GROUPS_PER_RUN * claims.EXTRACT_GROUP + 9)
    before = len(claims.unnormalized(pid))
    res = claims.run_job({"project_id": pid, "reason": "test"})
    assert res["calls"] == claims.GROUPS_PER_RUN, "a run must not exceed its quota of model calls"
    assert res["more"] is True and res["remaining"] > 0
    assert len(claims.unnormalized(pid)) < before, "it still made real progress before yielding"


def test_resuming_re_does_nothing_which_is_what_makes_yielding_free():
    pid = _many_candidates(claims.GROUPS_PER_RUN * claims.EXTRACT_GROUP + 9)
    first = claims.run_job({"project_id": pid, "reason": "one"})
    second = claims.run_job({"project_id": pid, "reason": "two"})
    assert second["calls"] <= claims.GROUPS_PER_RUN
    # the second run normalized DIFFERENT candidates — no group was paid for twice
    assert second["normalized"] > 0
    hashes = [r["extraction_hash"] for r in db.connect().execute(
        "SELECT extraction_hash FROM project_claims WHERE project_id=? AND extraction_hash IS NOT NULL", (pid,)).fetchall()]
    assert len(set(hashes)) >= 2, "each group carries its own extraction hash"
    # run until it stops asking for more: it must terminate, not loop forever
    for _ in range(20):
        r = claims.run_job({"project_id": pid, "reason": "again"})
        if not r.get("more"):
            break
    assert not claims.unnormalized(pid) or not r.get("more")


def test_the_fast_pass_is_never_interrupted():
    """The fast lane exists to be quick and is already bounded by FAST_GROUPS. Yielding it would defeat it."""
    pid = _many_candidates(claims.GROUPS_PER_RUN * claims.EXTRACT_GROUP + 9)
    ids = [c["id"] for c in claims.unnormalized(pid)][: (claims.GROUPS_PER_RUN + 2) * claims.EXTRACT_GROUP]
    res = claims.run_job({"project_id": pid, "reason": "important", "claim_ids": ids})
    assert res["calls"] > claims.GROUPS_PER_RUN, "an explicitly chosen set runs to the end"
    assert not res.get("more")


def test_a_lane_cannot_solve_this_which_is_why_the_job_yields():
    """Documents the reasoning as an executable check: a RUNNING job holds its worker whatever else arrives, so
    two earlier order-based attempts could not have fixed it."""
    pid = _many_candidates(4)
    long_job = db.create_job("extract_claims", {"project_id": pid}, lane="slow")["id"]
    db.claim_job(kinds=("extract_claims",), worker_id="ai-1")
    urgent = db.create_job("suggest_findings", {"project_id": pid, "source_ids": ["s"]}, lane="priority")["id"]
    assert db.get_job(long_job)["status"] == "running"
    # the priority job is claimable only by a DIFFERENT worker — nothing evicts the running one
    assert db.claim_job(worker_id="ai-1")["id"] == urgent
    assert db.get_job(long_job)["status"] == "running"
