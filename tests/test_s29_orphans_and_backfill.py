"""S29 — work nothing is doing, and state nothing ever built (0.63.11). (Sorts after test_s28.)

Two faults found by reading Kyle's live database rather than his screen, and both are the same shape: something the
app only ever does FORWARD, leaving anything from before it in silent limbo.

**Two sources `pending` since 2026-09-04 with no job anywhere.** Both are YouTube *search* URLs
(`youtube.com/results?search_query=mark+kohler+LLC+vs+S-Corp`), with no title, no `external_id` and no error. Every
current path handles a search link properly — `media.classify_url` → `youtube_search` → `enumerate_search` → a review
list — so these are orphans of an older version. The Sources view offered *"pending (no job — use Retry)"*, and
Retry had nothing to retry.

**A project with 605 findings and no research state at all.** *Real Estate Investment Strategy*: 0 Claims, 0
knowledge nodes, 0 evidence targets — the Research tab read as an empty project. Not the hook's fault:
`_after_done` harvests after every findings job and 72 completed for it. They completed 2026-09-03 → 2026-09-08
00:09, and the **earliest Claim anywhere in the database is 2026-09-08 01:07** — every one of its findings landed
before the machinery was live. Run by hand: **652 ms, 589 Claims, $0.**
"""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_orph_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, jobs, media  # noqa: E402
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


def _pending(ext: str, url: str, age_s: float) -> str:
    s = db.upsert_source(platform="youtube", external_id=ext, url=url, status="pending")
    with db.tx() as conn:
        conn.execute("UPDATE sources SET updated_at=? WHERE id=?", (time.time() - age_s, s["id"]))
    return s["id"]


# ------------------------------------------------------------------ the orphan sweep

def test_a_pending_source_with_no_job_is_told_so(fresh):
    sid = _pending("orph1", "https://www.youtube.com/results?search_query=mark+kohler+s-corp", 7 * 3600)
    assert db.sweep_orphaned_pending() == [sid]
    row = db.get_source(sid)
    assert row["status"] == "failed" and row["error_class"] == "orphaned"
    assert "Retry" in (row["error"] or "")


def test_the_class_is_retryable_because_the_url_is_still_good(fresh):
    """A search link is fully handled now, so a retry goes somewhere — this must never be a permanent class."""
    assert db.failure_is_permanent("orphaned") is False
    assert media.classify_url("https://www.youtube.com/results?search_query=mark+kohler+s-corp") == "youtube_search"


def test_a_source_a_job_is_actually_running_is_left_alone(fresh):
    sid = _pending("orph2", "https://www.youtube.com/watch?v=orph2", 7 * 3600)
    db.create_job("ingest_source", {"source_id": sid, "project_id": "p"})
    assert db.sweep_orphaned_pending() == []
    assert db.get_source(sid)["status"] == "pending"


def test_a_source_queued_a_minute_ago_is_left_alone(fresh):
    """Six hours, not six minutes: a real ingest of a long video takes a while and must never be swept mid-flight."""
    sid = _pending("orph3", "https://www.youtube.com/watch?v=orph3", 60)
    assert db.sweep_orphaned_pending() == []
    assert db.get_source(sid)["status"] == "pending"


def test_the_sweep_runs_at_startup_and_is_idempotent(fresh):
    sid = _pending("orph4", "https://www.youtube.com/results?search_query=taxgeek", 7 * 3600)
    db.init_db()                                     # the sweep is part of it
    assert db.get_source(sid)["status"] == "failed"
    assert db.sweep_orphaned_pending() == []         # nothing left pending, so nothing to sweep


# ------------------------------------------------------------------ the research backfill

def _project_with_findings(n: int = 3) -> str:
    p = db.create_project("has findings", brief="b")
    s = db.upsert_source(platform="youtube", external_id="bf1", url="https://www.youtube.com/watch?v=bf1",
                         title="a video", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    for i in range(n):
        db.add_project_note(p["id"], f"A specific finding about seller financing terms, number {i}.",
                            status="approved", source_id=s["id"])
    return p["id"]


def test_a_project_with_findings_and_no_claims_gets_its_harvest_queued(fresh):
    pid = _project_with_findings()
    assert jobs._backfill_research() == [pid]
    assert [j for j in db.list_jobs(limit=50) if j["kind"] == "refresh_research"]


def test_it_is_offered_once_and_never_again(fresh):
    """A project whose findings genuinely yield no Claims must not be re-queued for ever."""
    pid = _project_with_findings()
    assert jobs._backfill_research() == [pid]
    assert jobs._backfill_research() == []
    assert db.kv_get(f"claims:backfilled:{pid}")


def test_a_project_that_already_has_claims_is_not_touched(fresh):
    pid = _project_with_findings()
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, claim_type, status, strength, created_at, "
                     "updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("cbf1", pid, "a claim it already holds", "factual", "proposed", "weak", 1.0, 1.0))
    assert jobs._backfill_research() == []


def test_a_project_with_no_findings_is_not_touched(fresh):
    db.create_project("empty", brief="b")
    assert jobs._backfill_research() == []


def test_the_backfill_runs_at_startup_before_the_first_wait(fresh, monkeypatch):
    """Same lesson as 0.63.7: work that waits two minutes has not happened when the user opens the app."""
    seen: list[str] = []
    monkeypatch.setattr(jobs, "_warm_quality", lambda: seen.append("warm"))
    monkeypatch.setattr(jobs, "_backfill_research", lambda: seen.append("backfill") or [])
    monkeypatch.setattr(jobs.db, "checkpoint_wal", lambda: {})

    class OneShot:
        def __init__(self) -> None:
            self.n = 0

        def is_set(self) -> bool:
            self.n += 1
            return self.n > 1

        def wait(self, _s: float) -> None:
            pass

    monkeypatch.setattr(jobs, "_stop", OneShot())
    jobs._housekeeping_loop(every=0.0)
    assert seen == ["warm", "backfill"]
