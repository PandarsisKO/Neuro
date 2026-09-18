"""S66 — Claims harvesting is isolated from findings completion (P0.2, docs/SPEED-AUDIT-2026-09-17.md).

Measured on Kyle's live server, 2026-09-17: `_after_done()` ran `claims.harvest()` synchronously inside
`jobs.execute()` — after `finish_job`, before the `finally` that removes the job from `_running` — and on the
19k-note / 17k-Claim project one harvest took 5–6 minutes inside ONE write transaction. Consequences, both seen
in server.log: 157 false "lost the lease" warnings for jobs that had already logged "done" (the lease keeper
heartbeated a row that was no longer `running`), and `database is locked` on a findings write, a heartbeat and
— for Kyle — "New chat" (one INSERT) while the harvest held the writer.

What this module proves, each against the failure class it removes:
  1. a finished job has LEFT `_running` before its post-completion hook runs (no false lease loss possible);
  2. findings completion queues one coalesced $0 `harvest_claims` job instead of harvesting inline;
  3. a RUNNING harvest never absorbs a new request (the L-16 lost-note rule) — a queued one does;
  4. the harvest writes in bounded chunks, never one transaction around the whole pass;
  5. the harvest job re-checks for notes that landed mid-job and harvests them;
  6. the harvest kind is neither an AI-worker kind nor a pause-able background kind (it is $0 maintenance).
"""
from __future__ import annotations

import pytest

import time

from neurosearch import claims, db, jobs


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
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
    "Quality of earnings reports from a third party cost between eight and twenty thousand dollars.",
    "Landlord consent to assign a commercial lease can take six weeks and should start before the LOI.",
    "An earnout tied to gross revenue is easier to audit than one tied to adjusted EBITDA.",
    "Key employee retention bonuses are usually funded by the buyer and vest twelve months after close.",
]


def _project_with_notes(n: int) -> str:
    assert n <= len(FACTS)
    pid = db.create_project("s66", brief="durable facts")["id"]
    sid = db.upsert_source(platform="manual", external_id="s66-src", url="manual://s66", title="src")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    db.connect().commit()
    for i in range(n):
        db.add_project_note(pid, FACTS[i], citations=[{"source_id": sid, "timestamp": "0:00", "snippet": "x"}], status="approved")
    return pid


def test_hook_runs_only_after_the_job_has_left_running(isolated, monkeypatch):
    pid = _project_with_notes(2)
    job = db.create_job("suggest_findings", {"project_id": pid, "source_ids": []})
    seen: dict = {}
    monkeypatch.setattr(jobs, "run_job", lambda j: {"sources": 0})

    def spy(j):
        with jobs._running_lock:
            seen["running"] = dict(jobs._running)
        seen["row"] = db.get_job(j["id"])["status"]
    monkeypatch.setattr(jobs, "_after_done", spy)
    claimed = db.claim_job(("suggest_findings",))
    assert jobs.execute(claimed) == "done"
    assert seen, "the post-completion hook did not run"
    assert claimed["id"] not in seen["running"], "the job must have left _running before the hook runs (false lost-lease class)"
    assert seen["row"] == "done"
    # and the lease keeper's own check agrees: nothing to heartbeat, nothing to warn about
    assert db.heartbeat(claimed["id"], claimed["run_id"]) is False and claimed["id"] not in jobs._running


def test_hook_does_not_run_for_a_failed_job(isolated, monkeypatch):
    pid = _project_with_notes(1)
    db.create_job("suggest_findings", {"project_id": pid, "source_ids": []})

    def boom(j):
        raise RuntimeError("no")
    monkeypatch.setattr(jobs, "run_job", boom)
    called = []
    monkeypatch.setattr(jobs, "_after_done", lambda j: called.append(j))
    assert jobs.execute(db.claim_job(("suggest_findings",))) == "failed"
    assert not called


def test_findings_completion_queues_one_harvest_job_and_harvests_nothing_inline(isolated):
    pid = _project_with_notes(3)
    jobs._after_done({"kind": "suggest_findings", "payload": {"project_id": pid}})
    jobs._after_done({"kind": "suggest_findings_batch", "payload": {"project_id": pid}})
    rows = db.connect().execute("SELECT id, lane, status FROM jobs WHERE kind='harvest_claims'").fetchall()
    assert len(rows) == 1 and rows[0]["lane"] == "normal" and rows[0]["status"] == "queued"
    assert claims.list_for_project(pid) == []                      # the hook itself moved no Claims
    hj = db.claim_job((jobs.claims_harvest_kind(),))
    assert hj["id"] == rows[0]["id"] and jobs.execute(hj) == "done"
    assert len(claims.list_for_project(pid)) == 3
    assert db.get_job(hj["id"])["result"]["created"] == 3


def test_a_running_harvest_never_absorbs_a_new_request(isolated):
    pid = _project_with_notes(2)
    first = claims.request_harvest(pid, "a")
    assert claims.request_harvest(pid, "b")["id"] == first["id"], "a QUEUED harvest coalesces"
    running = db.claim_job((jobs.claims_harvest_kind(),))
    assert running["id"] == first["id"] and running["status"] == "running"
    third = claims.request_harvest(pid, "c")
    assert third["id"] != first["id"] and third["status"] == "queued", \
        "a request while a harvest is RUNNING must queue a new one -- its snapshot predates this request (L-16)"


def test_harvest_writes_in_bounded_chunks_not_one_transaction(isolated, monkeypatch):
    pid = _project_with_notes(12)
    monkeypatch.setattr(claims, "HARVEST_TX_NOTES", 5)
    opened = []
    real_batch = db.batch
    from contextlib import contextmanager

    @contextmanager
    def counting_batch():
        opened.append(1)
        with real_batch():
            yield
    monkeypatch.setattr(db, "batch", counting_batch)
    r = claims.harvest(pid)
    assert r["created"] == 12
    assert len(opened) >= 3, f"12 notes at 5 per transaction need at least 3 write transactions, saw {len(opened)}"
    assert len(claims.list_for_project(pid)) == 12
    assert claims.harvest(pid) == {"created": 0, "merged": 0}      # idempotent, as before


def test_harvest_job_picks_up_notes_that_land_mid_job(isolated, monkeypatch):
    pid = _project_with_notes(2)
    sid = db.connect().execute("SELECT source_id FROM project_sources WHERE project_id=?", (pid,)).fetchone()["source_id"]
    real = claims.harvest
    calls = []

    def harvest_then_add(p):
        r = real(p)
        calls.append(r)
        if len(calls) == 1:                                        # a findings job finishes while we run
            db.add_project_note(p, "late arrival: the DSCR floor on an SBA deal is one point two five.",
                                citations=[{"source_id": sid, "timestamp": "0:01"}], status="approved")
        return r
    monkeypatch.setattr(claims, "harvest", harvest_then_add)
    out = claims.run_harvest_job({"project_id": pid, "reason": "test"})
    assert out["passes"] == 2 and out["created"] == 3
    assert not claims.unharvested_note_ids(pid)


def test_harvest_kind_is_zero_dollar_maintenance_not_ai_or_background_work(isolated):
    k = jobs.claims_harvest_kind()
    assert k not in jobs.ANALYSIS_KINDS, "harvest must not occupy an AI worker slot"
    assert k not in db.BACKGROUND_KINDS, "Pause background holds paid speculative work; a $0 harvest keeps Claims current"
    assert k in jobs.RETRYABLE
    # and neither "Pause background" (holds the slow/low lanes) nor the queue pause (holds paid kinds via
    # usage.guard) may hold it -- before P0.2 the harvest ran inline whatever the pause state (found live: the first
    # cut queued it on the `low` lane, which Pause background silently held)
    pid = _project_with_notes(1)
    job = claims.request_harvest(pid, "paused")
    db.set_background_paused(True)
    db.kv_set("queue_paused", "1")
    claimed = db.claim_job(jobs.MAINTENANCE_KINDS, worker_id="maintenance")   # what the maintenance worker asks for
    assert claimed and claimed["id"] == job["id"]
    assert jobs.execute(claimed) == "done"


def test_harvest_never_occupies_an_ingestion_or_ai_worker(isolated):
    """Kyle, live 2026-09-18: three harvests filled the three general workers (one harvesting, two parked on the
    per-project lock) while the twenty transcripts of a channel he had just added sat queued. A harvest runs on
    the single maintenance worker and nowhere else; an ingestion worker offered only harvests claims nothing."""
    k = jobs.claims_harvest_kind()
    assert k in jobs.MAINTENANCE_KINDS and k not in jobs.ANALYSIS_KINDS
    pid = _project_with_notes(1)
    for _ in range(3):
        db.create_job(k, {"project_id": pid, "reason": "burst"}, lane="normal", dedupe_key=db.new_id())
    general = db.claim_job(exclude_kinds=jobs.ANALYSIS_KINDS + jobs.MAINTENANCE_KINDS, worker_id="general-0")
    assert general is None, "a general (ingestion) worker must not claim a harvest"
    ai = db.claim_job(jobs.ANALYSIS_KINDS, worker_id="local-0")
    assert ai is None, "an AI worker must not claim a harvest"
    sid = db.upsert_source(platform="manual", external_id="s66-ing", url="manual://s66-ing", title="t")["id"]
    ingest = db.create_job("ingest_source", {"source_id": sid})
    got = db.claim_job(exclude_kinds=jobs.ANALYSIS_KINDS + jobs.MAINTENANCE_KINDS, worker_id="general-0")
    assert got and got["id"] == ingest["id"], "with harvests queued, the ingestion worker still gets the transcript"
    assert db.claim_job(jobs.MAINTENANCE_KINDS, worker_id="maintenance")["kind"] == k


def test_a_review_the_person_approved_ingests_ahead_of_background_work(isolated):
    """Kyle: 'I requested the channel, so it should be prioritized first.' Approved transcripts take the priority
    lane; a background ingest queued earlier on the normal lane waits its turn."""
    from neurosearch import ingest
    bg = db.upsert_source(platform="manual", external_id="bg", url="manual://bg", title="background")["id"]
    earlier = db.create_job("ingest_source", {"source_id": bg})              # normal lane, created first
    coll = db.upsert_collection("channel", "chan", "https://www.youtube.com/@chan", "chan")
    mine = db.upsert_source(platform="youtube", external_id="v1", url="https://youtu.be/v1", title="mine", status="proposed")["id"]
    db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)", (mine, coll["id"])); db.connect().commit()
    ingest.approve_proposed(coll["id"], [mine])
    first = db.claim_job(exclude_kinds=jobs.ANALYSIS_KINDS + jobs.MAINTENANCE_KINDS, worker_id="general-0")
    assert first and first["payload"]["source_id"] == mine and first["lane"] == "priority"
    assert db.claim_job(exclude_kinds=jobs.ANALYSIS_KINDS + jobs.MAINTENANCE_KINDS, worker_id="general-1")["id"] == earlier["id"]
