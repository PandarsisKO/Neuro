"""L-16 (EXECUTION-LADDER.md P0.F, CTO rulings §1.F): "several suggest_findings jobs now routinely finish within
the same second" (claims.py's own 2026-09-14 concurrency note, describing a real live incident: one
extract_claims job failed outright on project_claims' (project_id, origin_note_id) UNIQUE index, another
appeared stuck behind it). tests/test_claims_harvest_race.py already proves claims.harvest() itself is safe
under 8 concurrent in-process callers -- this test drives the layer ABOVE that, the one the real incident
actually hit: 8 real suggest_findings JOB completions (db.create_job -> db.claim_job -> jobs.execute(), the same
path a real worker takes) racing across 4 worker threads against ONE project, so _after_done()'s inline
claims.harvest(pid) call is what's firing concurrently, not a direct harvest() call. Asserts: no thread raised
(in particular no uncaught IntegrityError), no duplicate (project_id, origin_note_id) pair in project_claims,
and no lost harvest -- every note any of the 8 jobs produced ends up referenced by exactly one Claim."""
from __future__ import annotations

import threading

import pytest

from neurosearch import db, jobs


@pytest.fixture
def p16_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    from neurosearch import claims
    claims._harvest_locks.clear()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
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
]


def _project_with_sources(n: int):
    project = db.create_project("p16", brief="find the durable facts")
    sids = []
    for i in range(n):
        sid = db.upsert_source(platform="manual", external_id=f"p16-{i}", url=f"manual://p16-{i}", title=f"src{i}")["id"]
        db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project["id"], sid))
        text = FACTS[i]
        db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, len(text), text))
        db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, text))
        sids.append(sid)
    db.connect().commit()
    return project, sids


def test_eight_suggest_findings_completions_across_four_threads_do_not_race_harvest(p16_db):
    project, sids = _project_with_sources(8)
    for sid in sids:
        db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [sid]})

    errors: list[BaseException] = []
    completed: list[str] = []
    lock = threading.Lock()

    def worker():
        while True:
            job = db.claim_job(("suggest_findings",), worker_id=threading.current_thread().name)
            if not job:
                return
            try:
                outcome = jobs.execute(job, threading.current_thread().name)
                with lock:
                    completed.append(outcome)
            except BaseException as e:  # noqa: BLE001
                with lock:
                    errors.append(e)

    threads = [threading.Thread(name=f"w{i}", target=worker) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"a worker thread raised while completing a suggest_findings job: {errors}"
    assert completed.count("done") == 8, completed
    # P0.2: completion queues harvest_claims jobs instead of harvesting inline; the workers above claimed only
    # suggest_findings, so drain those now -- across the same four threads, so the harvest itself is still raced.
    def harvester():
        while True:
            job = db.claim_job((jobs.claims_harvest_kind(),), worker_id=threading.current_thread().name)
            if not job:
                return
            try:
                jobs.execute(job, threading.current_thread().name)
            except BaseException as e:  # noqa: BLE001
                with lock:
                    errors.append(e)
    hthreads = [threading.Thread(name=f"h{i}", target=harvester) for i in range(4)]
    for t in hthreads:
        t.start()
    for t in hthreads:
        t.join(timeout=60)
    assert not errors, f"a harvest job raised: {errors}"

    dup = db.connect().execute(
        "SELECT origin_note_id, COUNT(*) c FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL "
        "GROUP BY origin_note_id HAVING c > 1", (project["id"],)
    ).fetchall()
    assert dup == [], f"duplicate (project_id, origin_note_id): {[dict(r) for r in dup]}"

    notes = db.connect().execute(
        "SELECT id FROM project_notes WHERE project_id=? AND status IN ('approved','suggested')", (project["id"],)
    ).fetchall()
    harvested = {r["origin_note_id"] for r in db.connect().execute(
        "SELECT origin_note_id FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL", (project["id"],)
    )}
    missing = [n["id"] for n in notes if n["id"] not in harvested]
    assert not missing, f"note(s) never harvested into a Claim after all 8 jobs completed: {missing}"
