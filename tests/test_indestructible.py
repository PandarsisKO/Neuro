"""Mission D — make work indestructible. Crash matrix, external parking, cancellation, leases, dedupe, and the
exit gate: a 40-source project processed under randomised crashes ends in exactly the state an uninterrupted run
produces (crash-recovery equivalence)."""
from __future__ import annotations

import os
import random
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_d_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402

from neurosearch import db, jobs, media  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests import crashkit  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    """Every test gets its own database and media dir, fake AI on, no background workers."""
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", True)
    (data / "media").mkdir()
    db._local.conn = None
    db.init_db()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    try:
        db.connect().close()
    except Exception:  # noqa: BLE001
        pass
    db._local.conn = None


def _project_with(urls, brief="buying a small business with an SBA loan"):
    p = db.create_project("Crash project", brief)
    for u in urls:
        db.create_job("ingest_url", {"url": u, "tags": [], "project_id": p["id"]})
    return p


def _counts():
    c = db.connect()
    return {"whisper": c.execute("SELECT COUNT(*) FROM usage WHERE kind='whisper'").fetchone()[0],
            "findings_calls": c.execute("SELECT COUNT(*) FROM usage WHERE kind='findings'").fetchone()[0],
            "sources": c.execute("SELECT COUNT(*) FROM sources").fetchone()[0]}


# ---------------------------------------------------------------- crash matrix

@pytest.mark.parametrize("point", ["before_metadata", "metadata_complete", "audio_downloaded", "transcription_before_response",
                                   "transcript_complete", "chunks_complete", "embeddings_half"])
def test_crash_matrix_ingestion(tmp_path, monkeypatch, point):
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=0)      # no captions: must be transcribed (paid)
    downloads = {"n": 0}
    real_dl = media.download_audio
    def counting_dl(url, **kw):
        downloads["n"] += 1
        return real_dl(url, **kw)
    monkeypatch.setattr(media, "download_audio", counting_dl)
    p = _project_with(urls)
    sim = crashkit.Sim()
    jobs.CRASH_AT[point] = 1
    assert sim.step(("ingest_url",)) == "crashed"
    job = db.list_jobs(5)[0]
    assert job["status"] == "queued" and "recovered" in (job["message"] or "")           # restart recovered the lease
    src = db.list_sources(limit=5)
    if point in ("metadata_complete", "audio_downloaded", "transcription_before_response"):
        assert src and src[0]["stage"] == "metadata"
    if point == "audio_downloaded":
        assert src[0]["audio_path"] and os.path.exists(src[0]["audio_path"])
    if point in ("transcript_complete",):
        assert src[0]["stage"] == "transcript" and db.get_segments(src[0]["id"]) and not db.get_chunks(src[0]["id"])
    if point == "chunks_complete":
        assert src[0]["stage"] == "chunks" and db.get_chunks(src[0]["id"])
    if point == "embeddings_half":
        c = db.connect()
        assert 0 < c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL AND source_id=?", (src[0]["id"],)).fetchone()[0]
    before = _counts()
    sim.run_until_idle()
    s = db.list_sources(limit=5)[0]
    assert s["status"] == "ready" and s["stage"] == "ready" and s["transcript_kind"] == "transcribed"
    c = db.connect()
    assert c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NULL AND source_id=?", (s["id"],)).fetchone()[0] == 0
    after = _counts()
    # the expensive step is paid exactly once whatever happened; the download happened at most once
    assert after["whisper"] == 1 and after["sources"] == 1 and downloads["n"] == 1
    if point in ("transcript_complete", "chunks_complete", "embeddings_half"):
        assert before["whisper"] == 1                                                     # nothing re-transcribed after the crash
    assert s["audio_path"] is None and not list((settings.data_dir / "media").glob("*.mp3"))   # cleaned up
    # findings ran once for the source (auto-suggest) and the plan of events tells the story
    ev = [e["event_type"] + ":" + (e["stage"] or "") for e in db.job_events(job["id"])]
    assert "lease_expired:" in ev and "recovered:" in ev and "done:" in ev
    assert db.connect().execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] == 0


@pytest.mark.parametrize("point", ["findings_before_response", "findings_persisted_before_done"])
def test_crash_matrix_findings(tmp_path, point):
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    p = _project_with(urls)
    sim = crashkit.Sim()
    sim.run_until_idle(kinds=("ingest_url",))                    # ingest only; the auto-queued findings job waits
    fj = [j for j in db.list_jobs(10) if j["kind"] == "suggest_findings"][0]
    jobs.CRASH_AT[point] = 1
    assert sim.step(("suggest_findings",)) == "crashed"
    sid = db.project_source_ids(p["id"])[0]
    notes_after_crash = len([n for n in db.list_project_notes(p["id"], status="suggested") if n["source_id"] == sid])
    calls_after_crash = _counts()["findings_calls"]
    sim.run_until_idle()
    j = db.get_job(fj["id"])
    assert j["status"] == "done"
    notes = [n for n in db.list_project_notes(p["id"], status="suggested") if n["source_id"] == sid]
    assert len({n["content"] for n in notes}) == len(notes) and notes                     # no duplicate findings
    if point == "findings_persisted_before_done":
        # the analysis was already durable: the rerun recognised the input hash and paid nothing more
        assert notes_after_crash == len(notes) and _counts()["findings_calls"] == calls_after_crash
        assert j["result"].get("done") == 1
    assert db.get_analysis(p["id"], sid, "summary")["status"] == "current"


# ---------------------------------------------------------------- external parking

def test_external_parking_reattaches_never_resubmits():
    j = db.create_job("external_demo", {"x": 1, "ready_after": 2})
    sim = crashkit.Sim()
    assert sim.step(("external_demo",)) == "external_pending"
    j = db.get_job(j["id"])
    assert j["status"] == "external_pending" and j["external_handle"] and j["run_id"] is None and j["lease_until"] is None   # no worker lease
    assert db.derived_status(j) == "external_pending"
    assert jobs.FakeExternal.submissions() == 1
    # a restart must not touch it (another system owns the work) and must not resubmit
    sim.restart()
    assert db.get_job(j["id"])["status"] == "external_pending" and jobs.FakeExternal.submissions() == 1
    assert jobs.poll_external_once() == 0                     # first check: still pending
    assert jobs.poll_external_once() == 1                     # second check: result in → back to the queue
    j2 = db.get_job(j["id"])
    assert j2["status"] == "queued" and j2["payload"]["_external_result"]["handle"] == j["external_handle"]
    assert sim.step(("external_demo",)) == "done"
    assert db.get_job(j["id"])["result"]["completed_with"]["echo"] == {"x": 1}
    kinds = [e["event_type"] for e in db.job_events(j["id"])]
    assert ["external_submitting", "external_submitted", "external_result"] == [k for k in kinds if k.startswith("external")]


def test_external_crash_before_ack_recovers_handle():
    """The provider accepted the work but we died before persisting the handle: recovery asks the provider for our
    reference and re-attaches — one submission, not two."""
    j = db.create_job("external_demo", {"x": 2, "ready_after": 1})
    sim = crashkit.Sim()
    jobs.CRASH_AT["external_before_ack"] = 1
    assert sim.step(("external_demo",)) == "crashed"
    assert jobs.FakeExternal.submissions() == 1 and db.get_job(j["id"])["status"] == "queued"
    assert sim.step(("external_demo",)) == "external_pending"
    assert jobs.FakeExternal.submissions() == 1                                           # re-attached, not resubmitted
    assert any(e["event_type"] == "external_reattached" for e in db.job_events(j["id"]))
    sim.run_until_idle()
    assert db.get_job(j["id"])["status"] == "done"
    # and a crash after the result came back but before DONE just re-runs the completion step
    k = db.create_job("external_demo", {"x": 3, "ready_after": 1})
    sim.step(("external_demo",)); jobs.poll_external_once()
    jobs.CRASH_AT["external_result_before_done"] = 1
    assert sim.step(("external_demo",)) == "crashed"
    sim.run_until_idle()
    assert db.get_job(k["id"])["status"] == "done" and jobs.FakeExternal.submissions() == 2


def test_external_cancel_discards_result():
    j = db.create_job("external_demo", {"x": 4, "ready_after": 1})
    sim = crashkit.Sim()
    sim.step(("external_demo",))
    assert db.request_cancel(j["id"]) == "cancelled"
    jobs.poll_external_once(); jobs.poll_external_once()
    assert db.get_job(j["id"])["status"] == "cancelled" and sim.step(("external_demo",)) is None


# ---------------------------------------------------------------- cancellation, waits, leases, dedupe

def test_cancel_running_job_stops_at_safe_point_and_writes_nothing(tmp_path):
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    p = _project_with(urls)
    job = db.claim_job(("ingest_url",), worker_id="sim")
    assert db.request_cancel(job["id"]) == "running" and db.derived_status(db.get_job(job["id"])) == "cancelling"
    assert jobs.execute(job, "sim") == "cancelled"
    j = db.get_job(job["id"])
    assert j["status"] == "cancelled" and j["lease_until"] is None
    assert not db.list_sources(limit=5) or db.list_sources(limit=5)[0]["stage"] in (None, "listed")   # nothing durable was written
    assert not any(jb["kind"] == "suggest_findings" for jb in db.list_jobs(10))                       # no downstream work spawned
    # queued jobs cancel immediately; terminal jobs cannot be cancelled
    q = db.create_job("reembed", {})
    assert db.request_cancel(q["id"]) == "cancelled" and db.request_cancel(q["id"]) == "cancelled"


def test_budget_wait_is_not_an_attempt(monkeypatch):
    from neurosearch import usage
    j = db.create_job("reembed", {})
    monkeypatch.setattr(settings, "daily_budget", 0.000001)
    usage.record("findings", "claude-sonnet-4-6", input_tokens=10_000)
    job = db.claim_job(("reembed",), worker_id="sim")
    assert jobs.execute(job, "sim") == "queued"
    j = db.get_job(j["id"])
    assert j["attempts"] == 0 and j["wait_reason"] == "budget" and db.derived_status(j) == "budget_wait" and j["lease_until"] is None
    # a transient error IS an attempt and is a retry wait
    monkeypatch.setattr(settings, "daily_budget", 100.0)
    monkeypatch.setattr(jobs.ingest, "ingest_url", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP Error 429: Too Many Requests")))
    k = db.create_job("ingest_url", {"url": "https://example.com/x.mp3"})
    job = db.claim_job(("ingest_url",), worker_id="sim")
    assert jobs.execute(job, "sim") == "queued"
    k = db.get_job(k["id"])
    assert k["attempts"] == 1 and k["wait_reason"] == "retry" and db.derived_status(k) == "retry_wait"


def test_lease_expiry_recovery_and_single_owner():
    j = db.create_job("reembed", {})
    a = db.claim_job(("reembed",), worker_id="w1", lease_seconds=0.05)
    assert a and db.claim_job(("reembed",), worker_id="w2") is None                   # exactly one owner
    import time; time.sleep(0.1)
    assert db.recover_expired_leases() == [j["id"]]                                    # heartbeat stopped → recovered
    b = db.claim_job(("reembed",), worker_id="w2")
    assert b and b["run_id"] != a["run_id"]
    # the old run cannot finish the job it lost
    assert db.finish_job(j["id"], a["run_id"], "done", message="stale") is False
    assert db.heartbeat(j["id"], a["run_id"]) is False and db.heartbeat(j["id"], b["run_id"]) is True
    assert db.finish_job(j["id"], b["run_id"], "done", message="ok") is True
    kinds = [e["event_type"] for e in db.job_events(j["id"])]
    assert kinds == ["queued", "claimed", "lease_expired", "recovered", "claimed", "done"]


def test_dedupe_keys_and_idempotent_findings(tmp_path):
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    p = db.create_project("Dedupe", "brief")
    a = db.create_job("ingest_url", {"url": urls[0], "project_id": p["id"]})
    b = db.create_job("ingest_url", {"url": urls[0], "project_id": p["id"]})
    assert a["id"] == b["id"] and any(e["event_type"] == "deduplicated" for e in db.job_events(a["id"]))
    crashkit.Sim().run_until_idle()
    sid = db.project_source_ids(p["id"])[0]
    calls = _counts()["findings_calls"]
    from neurosearch import findings
    r = findings.suggest_for_source(p["id"], sid)
    assert r.get("skipped") and _counts()["findings_calls"] == calls                   # same inputs → no second payment
    db.update_project(p["id"], brief="a different brief")
    r = findings.suggest_for_source(p["id"], sid)
    assert not r.get("skipped") and _counts()["findings_calls"] == calls + 1            # changed inputs → real work


def test_dependency_policies_and_retry_rewiring():
    up1, up2 = db.create_job("reembed", {"limit": 1}), db.create_job("reembed", {"limit": 2})
    plan = db.create_job("build_plan", {"project_id": "none"}, blocked_by=[up1["id"], up2["id"]])
    anyok = db.create_job("reembed", {"limit": 3}, blocked_by=[up1["id"], up2["id"]], dependency_policy="ANY_SUCCESS")
    term = db.create_job("reembed", {"limit": 4}, blocked_by=[up1["id"], up2["id"]], dependency_policy="ALL_TERMINAL")
    assert db.derived_status(db.get_job(plan["id"])) == "blocked"
    db.update_job(up1["id"], status="done"); db.update_job(up2["id"], status="failed", message="error: x")
    assert db.claim_job(("build_plan",), worker_id="sim") is None
    rep = db.dependency_report(db.get_job(plan["id"]))
    assert rep["done"] == 1 and len(rep["failed"]) == 1 and rep["state"] == "failed"
    assert db.get_job(plan["id"])["status"] == "failed" and "1/2 upstream jobs succeeded" in db.get_job(plan["id"])["message"]
    assert db.claim_job(("reembed",), worker_id="sim")["id"] in (anyok["id"], term["id"])          # ANY_SUCCESS / ALL_TERMINAL run
    # retrying the failed upstream rewires and un-fails the dependent
    new = db.retry_job(up2["id"])
    pj = db.get_job(plan["id"])
    assert pj["status"] == "queued" and new["id"] in pj["blocked_by"] and up2["id"] not in pj["blocked_by"]
    db.update_job(new["id"], status="done")
    assert db.claim_job(("build_plan",), worker_id="sim")["id"] == plan["id"]


# ---------------------------------------------------------------- the exit gate

@pytest.mark.parametrize("seed", [20260906, 1, 42])
def test_crash_recovery_equivalence_40_sources(tmp_path, seed):
    """A 40-source project is processed while the worker is killed at random points; after every restart processing
    continues. The final state must equal an uninterrupted run's, and the ledger must show no duplicated paid work."""
    urls = crashkit.write_fixtures(tmp_path / "fx", 40, captions_every=2)

    def run(seed: int | None) -> tuple[dict, dict, crashkit.Sim, str]:
        p = _project_with(urls)
        sim = crashkit.Sim(random.Random(seed), crash_prob=0.35 if seed is not None else 0.0)
        sim.run_until_idle(kinds=("ingest_url",))
        sim.run_until_idle(kinds=("suggest_findings",))
        fj = [j["id"] for j in db.list_jobs(500) if j["kind"] == "suggest_findings"]
        plan = db.create_job("build_plan", {"project_id": p["id"]}, blocked_by=fj)
        sim.run_until_idle()
        return crashkit.project_state(p["id"]), _counts(), sim, plan["id"]

    # uninterrupted reference run in its own database
    ref_state, ref_counts, _, _ = run(None)
    ref_db = db._local.conn; db._local.conn = None
    data2 = tmp_path / "data2"; data2.mkdir(); (data2 / "media").mkdir()
    settings.data_dir = data2
    db.init_db()
    state, counts, sim, plan_id = run(seed=seed)

    assert sim.crashes and sim.restarts == len(sim.crashes) and len(sim.crashes) >= 10, sim.crashes
    # exit gate
    c = db.connect()
    assert counts["sources"] == 40 == len(state["sources"])                                   # 0 duplicate sources
    assert c.execute("SELECT COUNT(*) FROM (SELECT source_id, idx, COUNT(*) n FROM chunks GROUP BY source_id, idx HAVING n>1)").fetchone()[0] == 0   # 0 duplicate chunks
    assert c.execute("SELECT COUNT(*) FROM (SELECT project_id, source_id, content, citations, COUNT(*) n FROM project_notes GROUP BY 1,2,3,4 HAVING n>1)").fetchone()[0] == 0   # 0 duplicate findings (same claim at the same timestamp)
    assert c.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0] == 0    # 0 dangling leases / stuck RUNNING
    assert counts["whisper"] == 20 == ref_counts["whisper"]                                    # 0 unnecessary retranscriptions
    assert all(s["status"] == "ready" and s["stage"] == "ready" and s["embedded"] == s["chunks"] for s in state["sources"].values())
    assert all(s["analysis_status"] == "current" and s["findings"] for s in state["sources"].values())   # every expected analysis complete
    pj = db.get_job(plan_id)
    deps_done = max(e["finished_at"] or 0 for e in [db.get_job(d) for d in pj["blocked_by"]])
    assert pj["status"] == "done" and pj["started_at"] >= deps_done                            # plan built only after dependencies
    assert c.execute("SELECT COUNT(*) FROM jobs WHERE status='failed'").fetchone()[0] == 0     # 0 dependency violations / failures
    # crash-recovery equivalence: the interrupted run produced exactly the uninterrupted run's project state
    assert state == ref_state
    # usage ledger: no double payment (fake findings calls are deterministic: one per window)
    assert counts["findings_calls"] == ref_counts["findings_calls"]
    ref_db.close()

