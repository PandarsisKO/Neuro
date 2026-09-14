"""G5 harvest() concurrency (2026-09-14): T4's batched executor (t4.execute) makes several suggest_findings jobs
finish within the same second, which makes _after_done()'s inline claims.harvest(pid) call fire concurrently for
the SAME project -- a real live run hit this (one extract_claims job failed outright on
project_claims.origin_note_id's UNIQUE constraint, another appeared stuck behind it). harvest() must survive being
called from multiple threads for the same project at the same time without losing notes, duplicating Claims, or
raising."""
import threading

import pytest

from neurosearch import claims, db


@pytest.fixture
def h_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    claims._harvest_locks.clear()
    yield
    db.close_thread_connection()


FACTS = [
    "The SBA guarantee fee on loans under $150,000 is 2 percent this fiscal year.",
    "Sellers financing part of the deal typically hold a note on full standby for the loan's life.",
    "Retaining an accounting firm's prior owner through two tax seasons protects client retention.",
    "A CIM's addback schedule should be checked against three years of tax returns, not just one.",
    "Working capital adjustments at close are the most commonly renegotiated term in an LOI.",
    "Lenders often want at least ten percent seller financing to show alignment of interest.",
    "Customer concentration above thirty percent from one client is a common diligence red flag.",
    "A DSCR below 1.25x on an SBA deal usually triggers additional lender scrutiny.",
    "Earnout structures shift risk to the seller but can slow down deal close timelines.",
    "Quality of earnings reports typically cost between five and fifteen thousand dollars.",
    "Non-competes for sellers commonly run two to five years depending on the industry.",
    "Asset deals limit successor liability compared to stock deals in most acquisitions.",
    "Landlord estoppel certificates are frequently overlooked until late in due diligence.",
    "Key employee retention bonuses are often structured to vest over the first year post-close.",
    "Inventory valuation disputes are a leading cause of post-closing purchase price adjustments.",
    "SBA loans cap at ten million dollars following the most recent program expansion.",
    "Environmental Phase I assessments are standard for any deal involving real property.",
    "Buyer-side legal fees for a typical small acquisition run ten to twenty-five thousand dollars.",
    "Transition services agreements typically run ninety days after closing for operational handoff.",
    "Escrow holdbacks of ten percent are common to cover post-closing indemnification claims.",
]


def _project_with_notes(n: int):
    project = db.create_project("harvest race", brief="find the durable facts")
    assert n <= len(FACTS)
    for i in range(n):
        db.add_project_note(project["id"], FACTS[i], citations=[], status="approved")
    return project


def test_concurrent_harvest_for_the_same_project_does_not_raise_or_duplicate(h_db):
    project = _project_with_notes(20)
    errors: list[BaseException] = []
    results: list[dict] = []
    lock = threading.Lock()

    def run():
        try:
            r = claims.harvest(project["id"])
            with lock:
                results.append(r)
        except BaseException as e:  # noqa: BLE001
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"harvest() raised under concurrency: {errors}"
    rows = db.connect().execute("SELECT origin_note_id, COUNT(*) c FROM project_claims WHERE project_id=? "
                                "GROUP BY origin_note_id HAVING c > 1", (project["id"],)).fetchall()
    assert rows == []                                          # no note was claimed twice
    total_created = sum(r["created"] for r in results)
    assert total_created == 20                                 # every note was claimed exactly once, by exactly one caller


def test_harvest_is_still_idempotent_called_serially_twice(h_db):
    project = _project_with_notes(5)
    first = claims.harvest(project["id"])
    second = claims.harvest(project["id"])
    assert first["created"] == 5
    assert second["created"] == 0 and second["merged"] == 0


def test_a_second_process_race_is_absorbed_not_fatal(h_db, monkeypatch):
    """The lock only closes the in-process race; a genuine cross-process collision (two OS processes) still hits
    the UNIQUE constraint at the database level -- that must be caught and skipped, not left to roll back the
    whole harvest."""
    import sqlite3

    project = _project_with_notes(3)
    real_add_claim = claims.add_claim
    calls = {"n": 0}

    def flaky_add_claim(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise sqlite3.IntegrityError("UNIQUE constraint failed: project_claims.project_id, project_claims.origin_note_id")
        return real_add_claim(*a, **k)

    monkeypatch.setattr(claims, "add_claim", flaky_add_claim)
    result = claims.harvest(project["id"])
    assert result["created"] == 2                              # the 3rd note's simulated collision was skipped, not fatal
