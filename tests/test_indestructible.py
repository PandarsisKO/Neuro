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



# ---------------------------------------------------------------- D closeout: ambiguous paid calls, cancel vs delete, cycles

def test_ambiguous_external_execution_is_detected_and_accounted(tmp_path):
    """Exactly-once holds for database effects only. A synchronous provider call whose response is lost is an
    OUTCOME_UNKNOWN invocation: recovery marks it, the ledger shows it, the retry is visible as a second call."""
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=0)      # transcription = a paid synchronous call
    p = _project_with(urls)
    sim = crashkit.Sim()
    jobs.CRASH_AT["provider_response_lost"] = 1                               # the provider finished (and charged); we die before recording it
    assert sim.step(("ingest_url",)) == "crashed"
    amb = db.ambiguous_invocations()
    assert len(amb) == 1 and amb[0]["task"] == "transcribe" and amb[0]["provider"] == "openai" and amb[0]["state"] == "outcome_unknown"
    job = db.list_jobs(5)[0]
    assert any(e["event_type"] == "ambiguous_external_execution" for e in db.job_events(job["id"]))
    assert db.health()["invocations"]["ambiguous"] == 1
    sim.run_until_idle()
    # the work completed on retry; the ledger shows two transcription invocations — one unknown, one completed — so the
    # possible double charge is accounted for rather than hidden
    inv = db.connect().execute("SELECT state, COUNT(*) n FROM invocations WHERE task='transcribe' GROUP BY state").fetchall()
    assert {r["state"]: r["n"] for r in inv} == {"outcome_unknown": 1, "completed": 1}
    assert db.list_sources(limit=5)[0]["status"] == "ready"
    # normal completed calls are accounted as completed with the provider's request id when it gives one
    done = db.connect().execute("SELECT COUNT(*) FROM invocations WHERE state='completed'").fetchone()[0]
    assert done >= 3 and db.connect().execute("SELECT COUNT(*) FROM invocations WHERE state='in_flight'").fetchone()[0] == 0


def test_cancel_preserves_completed_stages_delete_removes_them(tmp_path):
    """Cancel = stop further processing, keep durable checkpoints (a retry resumes, never re-transcribes).
    Delete source = actually remove the durable artifacts."""
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=0)
    p = _project_with(urls)
    sim = crashkit.Sim()
    jobs.CANCEL_AT["transcript_complete"] = 1                                 # user presses cancel right after transcription landed
    assert sim.step(("ingest_url",)) == "cancelled"
    s = db.list_sources(limit=5)[0]
    assert s["stage"] == "transcript" and db.get_segments(s["id"]) and not db.get_chunks(s["id"]) and s["status"] == "failed" and "Retry resumes" in s["error"]
    assert _counts()["whisper"] == 1
    job = db.list_jobs(5)[0]
    assert job["status"] == "cancelled"
    # retry: resumes from chunks — no download, no second transcription
    new = db.retry_job(job["id"]) if job["status"] == "failed" else db.create_job("ingest_url", {"url": urls[0], "project_id": p["id"]})
    sim.run_until_idle()
    s = db.get_source(s["id"])
    assert s["status"] == "ready" and s["stage"] == "ready" and _counts()["whisper"] == 1
    # delete really removes
    assert db.delete_source(s["id"]) is not None and db.get_source(s["id"]) is None and not db.get_segments(s["id"])


def test_dependency_cycles_are_rejected():
    a = db.create_job("reembed", {"limit": 1})
    b = db.create_job("reembed", {"limit": 2}, blocked_by=[a["id"]])
    c = db.create_job("reembed", {"limit": 3}, blocked_by=[b["id"]])
    with pytest.raises(db.DependencyCycle):
        db.set_dependencies(a["id"], [c["id"]])                               # A → B → C → A
    with pytest.raises(db.DependencyCycle):
        db.set_dependencies(a["id"], [a["id"]])                               # self
    with pytest.raises(db.DependencyCycle):
        db.set_dependencies(b["id"], [c["id"]])                               # direct cycle B ⇄ C
    assert db.get_job(a["id"])["blocked_by"] is None                          # nothing was rewired
    d = db.create_job("reembed", {"limit": 4}, blocked_by=[a["id"], a["id"], b["id"]])
    assert d["blocked_by"] == [a["id"], b["id"]]                              # duplicates collapse
    # retry rewiring keeps the old relationship in the history
    db.update_job(a["id"], status="failed", message="error: x")
    new = db.retry_job(a["id"])
    ev = [e for e in db.job_events(b["id"]) if e["event_type"] == "dependency_rewired"][0]
    assert ev["payload"]["previous"] == [a["id"]] and ev["payload"]["now"] == [new["id"]]


# ---------------------------------------------------------------- Rung G: batch findings (Message Batches through external_pending)

def _golden(monkeypatch):
    from neurosearch import evals
    monkeypatch.setattr(settings, "daily_budget", 1000)
    g = evals.load_golden()
    return g["project_id"], g["sources"]


def _batch_state():
    import json
    p = settings.data_dir / "fake_batches.json"
    return json.loads(p.read_text()) if p.exists() else {"batches": {}}


def _notes_semantic(pid):
    """The research artifact minus transport-only fields (transport, batch_id, timestamps, ids, model id)."""
    out = {}
    for n in db.list_project_notes(pid, status="suggested"):
        cites = [{k: c.get(k) for k in ("source_id", "timestamp", "start", "snippet", "link")} for c in (n.get("citations") or [])]
        out.setdefault(n["source_id"], []).append((n.get("title"), n["content"], n.get("importance"), tuple(sorted(str(c) for c in cites)), n.get("prompt_version"), n.get("input_hash")))
    return {k: sorted(v) for k, v in out.items()}


def _analyses_semantic(pid):
    return {sid: {k: a.get(k) for k in ("summary", "substance", "input_hash", "schema_version", "prompt_version", "status")} for sid, a in db.project_analysis(pid, "summary").items()}


def test_batch_findings_equivalent_to_interactive(monkeypatch):
    """Same logical research artifact through both transports: notes, citations, analyses, input/prompt/schema hashes and
    quote validation identical; only the transport-specific provenance differs — and it differs EXPLICITLY."""
    from neurosearch import batches, findings
    pid, ids = _golden(monkeypatch)
    work = list(ids.values())                                                     # all 9 golden sources = 10 findings windows
    for sid in work:
        findings.suggest_for_source(pid, sid)
    inter_notes, inter_an = _notes_semantic(pid), _analyses_semantic(pid)
    inter_prov = db.connect().execute("SELECT transport, batch_id FROM project_notes WHERE project_id=?", (pid,)).fetchall()
    assert all(r["transport"] == "interactive" and r["batch_id"] is None for r in inter_prov)
    inter_cost = db.connect().execute("SELECT SUM(cost) c, COUNT(*) n FROM usage WHERE kind='findings' AND transport='interactive'").fetchone()
    # batch, forced (the inputs are current), through the real queue machinery
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": work, "force": True})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    items = db.batch_items(j["id"])
    assert len(items) == 10 and all(it["status"] == "submitted" and it["batch_id"] and it["invocation_id"] for it in items)
    assert all(len(it["custom_id"]) <= 64 and it["custom_id"].startswith("fw-") for it in items)
    for it in items:                                                             # frozen params: no beta header, structured output, 1h shared-prefix cache
        p = it["params"]
        assert "extra_headers" not in p and p["output_config"]["format"]["type"] == "json_schema"
    # cache breakpoints: same placement rule as interactive (none under the provider's minimum cacheable prefix — the
    # fixtures are short), and when one is placed the batch asks for the 1h duration
    from neurosearch import usage
    assert not any("cache_control" in blk for it in items for blk in it["params"]["system"])
    real_min = usage.CACHE_MIN_CHARS
    monkeypatch.setattr(usage, "CACHE_MIN_CHARS", 0)
    long_items = findings.batch_requests(pid, work[0])
    assert [b.get("cache_control") for b in long_items[0]["params"]["system"]] == [None, {"type": "ephemeral", "ttl": "1h"}, {"type": "ephemeral", "ttl": "1h"}]
    assert [b.get("cache_control") for b in findings._system_blocks(findings.SYSTEM, "head")] == [None, {"type": "ephemeral"}]
    monkeypatch.setattr(usage, "CACHE_MIN_CHARS", real_min)
    sim.run_until_idle()
    jj = db.get_job(j["id"])
    assert jj["status"] == "done" and jj["result"]["done"] == 9 and jj["result"]["items"] == 10 and jj["result"]["failed"] == 0 and jj["result"]["cohorts"] == 1, jj["result"]
    assert _notes_semantic(pid) == inter_notes and _analyses_semantic(pid) == inter_an
    prov = db.connect().execute("SELECT DISTINCT transport, batch_id FROM project_notes WHERE project_id=?", (pid,)).fetchall()
    assert len(prov) == 1 and prov[0]["transport"] == "batch" and prov[0]["batch_id"].startswith("msgbatch_")
    an = db.get_analysis(pid, work[0], "summary")
    assert an["transport"] == "batch" and an["batch_id"] and an["status"] == "current"
    # ledger: one completed row per logical item on the batch provider; economics: half the model price, saved recorded
    rows = db.connect().execute("SELECT state, COUNT(*) n FROM invocations WHERE provider='anthropic_batch' GROUP BY state").fetchall()
    assert {r["state"]: r["n"] for r in rows} == {"completed": 10}
    b = jj["result"]["batch"]
    assert b["model_calls"] == 10 and abs(b["cost"] - inter_cost["c"] * 0.5) < 1e-6 and b["saved_vs_interactive_full_price"] > 0
    assert all(k in b for k in ("input_tokens", "output_tokens", "cache_read", "cache_write"))
    # every raw provider result was persisted locally before materialisation
    assert all(it["status"] == "materialized" and it["raw"] and it["raw"]["content"] for it in db.batch_items(j["id"]))
    ev = [e["event_type"] for e in db.job_events(j["id"])]
    assert ["batch_planned", "external_submitting", "external_submitted", "external_result", "batch_ended"] == [k for k in ev if k.startswith(("batch", "external"))]


def test_batch_partial_failure_retries_only_failed_items(monkeypatch):
    from neurosearch import batches
    pid, ids = _golden(monkeypatch)
    victim = ids["yt02"][:12]
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE", f"fw-{victim}")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    jobs.poll_external_once()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"          # cohort 2 parked: only the failed window
    c2 = db.batch_items(j["id"], 2)
    assert len(c2) == 1 and c2[0]["source_id"] == ids["yt02"] and c2[0]["custom_id"] == db.batch_items(j["id"], 1, status="errored")[0]["custom_id"]
    st = _batch_state()["batches"]
    assert len(st) == 2 and sorted(b["n"] for b in st.values()) == [1, 10]
    # the other 8 sources were materialised after cohort 1, before the retry was even submitted
    assert len(db.project_analysis(pid, "summary")) == 8 and not db.get_analysis(pid, ids["yt02"], "summary")
    sim.run_until_idle()
    jj = db.get_job(j["id"])
    assert jj["status"] == "done" and jj["result"]["done"] == 9 and jj["result"]["cohorts"] == 2
    assert db.get_analysis(pid, ids["yt02"], "summary")["status"] == "current"
    ev = [e for e in db.job_events(j["id"]) if e["event_type"] == "batch_retry_planned"]
    assert len(ev) == 1 and ev[0]["payload"]["items"] == 1
    inv = db.connect().execute("SELECT state, error_type, COUNT(*) n FROM invocations WHERE provider='anthropic_batch' GROUP BY state, error_type").fetchall()
    assert {(r["state"], r["error_type"]): r["n"] for r in inv} == {("completed", None): 10, ("failed", "BATCH_ERRORED"): 1}


def test_batch_gives_up_visibly_after_max_cohorts(monkeypatch):
    from neurosearch import batches
    pid, ids = _golden(monkeypatch)
    victim = ids["yt02"][:12]
    monkeypatch.setattr(batches, "MAX_COHORTS", 1)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE", f"fw-{victim}")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    sim.run_until_idle()
    jj = db.get_job(j["id"])
    assert jj["status"] == "failed" and "still failed after 1 batch cohorts" in (jj["message"] or "") and "window 1/1" in jj["message"]
    assert len(db.project_analysis(pid, "summary")) == 8                       # partial success is kept, the failure is named


def test_batch_crash_after_create_before_persist_reattaches(monkeypatch):
    """The provider accepted the batch, we died before persisting its id: recovery re-attaches — one provider batch, not two."""
    pid, ids = _golden(monkeypatch)
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    jobs.CRASH_AT["batch_after_create_before_persist"] = 1
    assert sim.step(("suggest_findings_batch",)) == "crashed"
    assert len(_batch_state()["batches"]) == 1 and db.get_job(j["id"])["status"] == "queued"
    assert all(it["status"] == "planned" for it in db.batch_items(j["id"]))          # the id was never persisted
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    assert len(_batch_state()["batches"]) == 1                                       # re-attached, not resubmitted
    assert any(e["event_type"] == "external_reattached" for e in db.job_events(j["id"]))
    items = db.batch_items(j["id"])
    assert all(it["status"] == "submitted" and it["batch_id"] == db.get_job(j["id"])["external_handle"] for it in items)
    sim.run_until_idle()
    assert db.get_job(j["id"])["status"] == "done" and len(db.project_analysis(pid, "summary")) == 9


def test_batch_crash_after_results_persisted_uses_local_copy(monkeypatch):
    """Results are persisted the moment the batch ends; a crash before materialisation re-runs from the local copy and
    never reads the provider's results again."""
    pid, ids = _golden(monkeypatch)
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    sim.step(("suggest_findings_batch",)); jobs.poll_external_once()
    assert all(it["status"] == "succeeded" and it["raw"] for it in db.batch_items(j["id"]))
    bid = db.get_job(j["id"])["payload"]["_external_result"]["batch_id"]
    assert _batch_state()["batches"][bid]["results_reads"] == 1
    jobs.CRASH_AT["batch_results_persisted_before_materialize"] = 1
    assert sim.step(("suggest_findings_batch",)) == "crashed"
    assert len(db.project_analysis(pid, "summary")) == 0
    sim.run_until_idle()
    assert db.get_job(j["id"])["status"] == "done" and len(db.project_analysis(pid, "summary")) == 9
    assert _batch_state()["batches"][bid]["results_reads"] == 1                     # local copy, no second provider read
    assert len(_batch_state()["batches"]) == 1


def test_batch_cancel_keeps_completed_results(monkeypatch):
    from neurosearch import batches
    pid, ids = _golden(monkeypatch)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_READY_AFTER", "5")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    assert jobs.poll_external_once() == 0                                            # still processing
    jj = db.get_job(j["id"])
    assert db.request_cancel(jj["id"]) == "cancelled"
    h = batches.cancel_job(jj)                                                       # what the API endpoint does after request_cancel
    assert h["materialized"] >= 1
    items = db.batch_items(j["id"])
    st = {it["status"] for it in items}
    assert "materialized" in st and "canceled" in st                                  # completed valid results kept, the rest explicitly canceled
    assert db.get_job(j["id"])["status"] == "cancelled" and len(db.project_analysis(pid, "summary")) == h["materialized"]
    assert any(e["event_type"] == "batch_cancelled" for e in db.job_events(j["id"]))


def test_batch_estimate_and_pricing_scope(monkeypatch):
    from neurosearch import batches, usage
    pid, ids = _golden(monkeypatch)
    est = batches.estimate(pid)
    assert est["items"] == 10 and est["sources"] == 9 and abs(est["background"] - est["now"] * 0.5) < 1e-4 and "model cost only" in est["note"] and "24 hours" in est["note"]
    assert abs(usage.estimate_findings(40000, batch=True) - usage.estimate_findings(40000) * 0.5) < 1e-9
    # the discount applies to model tokens only: a web search is never discounted
    c_int = usage.record("answer", "claude-sonnet-4-6", input_tokens=1000, output_tokens=100, searches=1)
    c_bat = usage.record("answer", "claude-sonnet-4-6", input_tokens=1000, output_tokens=100, searches=1, transport="batch")
    model_part = c_int - usage.WEB_SEARCH_PER_CALL
    assert abs(c_bat - (model_part * 0.5 + usage.WEB_SEARCH_PER_CALL)) < 1e-9
    # stable custom ids: the same inputs always map to the same ids; a brief change changes them
    from neurosearch import findings
    a = [it["custom_id"] for it in findings.batch_requests(pid, ids["yt01"])]
    assert a == [it["custom_id"] for it in findings.batch_requests(pid, ids["yt01"])]
    db.update_project(pid, brief="a different brief")
    assert a != [it["custom_id"] for it in findings.batch_requests(pid, ids["yt01"])]


def test_batch_recovery_never_claims_by_count_alone(monkeypatch):
    """The real API has no client reference. Creation time + request count NARROW candidates; they never prove identity:
    nothing is attached, no ledger row is started, and the job's state says so."""
    import json as _json
    from neurosearch import batches, providers
    pid, ids = _golden(monkeypatch)
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": [ids["yt01"]]})
    items, _ = batches.plan_items(pid, [ids["yt01"]])
    db.batch_items_add(j["id"], 1, items)
    monkeypatch.setattr(settings, "fake_ai", False)
    ref = f"{j['id']}#1"
    db.kv_set(f"batch:intent:{ref}", _json.dumps({"job_id": j["id"], "cohort_no": 1, "n": len(items), "ts": 1000.0, "attempted": True}))
    class Counts:
        def __init__(self, n): self.processing, self.succeeded, self.errored, self.canceled, self.expired = n, 0, 0, 0, 0
    class B:
        def __init__(self, id, ts, n): self.id, self.created_at, self.request_counts = id, ts, Counts(n)
    class Stub:
        class messages:
            class batches:
                @staticmethod
                def list(limit=20): return type("P", (), {"data": [B("old", 900.0, len(items)), B("other-size", 1001.0, len(items) + 3), B("twin-a", 1001.0, len(items)), B("twin-b", 1002.0, len(items))]})()
    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: Stub())
    h = batches.AnthropicBatch.find_by_ref(ref)
    assert h == f"tentative:{ref}"
    assert all(it["status"] == "planned" and it["batch_id"] is None for it in db.batch_items(j["id"]))
    assert db.connect().execute("SELECT COUNT(*) FROM invocations WHERE provider='anthropic_batch'").fetchone()[0] == 0
    ev = {e["event_type"]: e["payload"] for e in db.job_events(j["id"])}
    assert "external_reattached" not in ev and ev["external_candidates"]["candidates"] == ["twin-a", "twin-b"]
    db.park_external(j["id"], None, batches.PROVIDER, "findings", h, None)
    assert db.derived_status(db.get_job(j["id"])) == "external_handle_ambiguous"
    db.kv_set(f"batch:candidates:{ref}", _json.dumps(["twin-a"]))
    assert db.derived_status(db.get_job(j["id"])) == "external_tentative"
    # cancelling an ambiguous job never touches the candidates (they may be someone else's)
    assert db.request_cancel(j["id"]) == "cancelled"
    assert batches.cancel_job(db.get_job(j["id"]))["materialized"] == 0
    assert any(e["event_type"] == "batch_cancelled" and "untouched" in e["payload"]["detail"] for e in db.job_events(j["id"]))


def _decoy_batch(n: int, tag: str = "decoy") -> str:
    """Another process in the same workspace submits a same-sized batch inside our recovery window."""
    from neurosearch import providers
    client = providers.anthropic_client()
    reqs = [{"custom_id": f"{tag}-{i}", "params": {"model": "claude-x", "max_tokens": 50, "system": "You are terse.", "messages": [{"role": "user", "content": f"say {i}"}]}} for i in range(n)]
    return client.messages.batches.create(requests=reqs).id


def test_batch_recovery_two_same_sized_batches_adopts_only_the_verified_one(monkeypatch):
    """Crash after the provider accepted our batch, before its id was persisted, with a same-sized foreign batch created
    right after ours: recovery observes BOTH, attaches NEITHER until results exist, rejects the foreign one by custom_id
    set, adopts ours — one provider batch of ours, the foreign one untouched."""
    from neurosearch import batches
    pid, ids = _golden(monkeypatch)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_NO_CLIENT_REF", "1")           # behave like the real API: no client reference
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_READY_AFTER", "2")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    jobs.CRASH_AT["batch_after_create_before_persist"] = 1
    assert sim.step(("suggest_findings_batch",)) == "crashed"
    ours = list(_batch_state()["batches"])[0]
    decoy = _decoy_batch(10)
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    jj = db.get_job(j["id"])
    assert jj["external_handle"] == f"tentative:{j['id']}#1" and db.derived_status(jj) == "external_handle_ambiguous"
    assert all(it["status"] == "planned" and it["batch_id"] is None for it in db.batch_items(j["id"]))
    assert len(_batch_state()["batches"]) == 2                                   # nothing resubmitted
    assert jobs.poll_external_once() == 0                                        # both still processing: observe, do nothing
    assert db.derived_status(db.get_job(j["id"])) == "external_handle_ambiguous"
    assert jobs.poll_external_once() == 1                                        # both ended: decoy rejected, ours verified + adopted
    ev = [e for e in db.job_events(j["id"]) if e["event_type"] in ("external_candidates", "external_candidate_rejected", "external_reattached")]
    assert [e["event_type"] for e in ev] == ["external_candidates", "external_candidate_rejected", "external_reattached"]
    assert sorted(ev[0]["payload"]["candidates"]) == sorted([ours, decoy])
    assert ev[1]["payload"]["handle"] == decoy and ev[1]["payload"]["overlap"] == 0 and ev[1]["payload"]["returned"] == 10
    assert ev[2]["payload"]["handle"] == ours and ev[2]["payload"]["where"] == "verified_custom_ids"
    assert all(it["status"] == "succeeded" and it["batch_id"] == ours for it in db.batch_items(j["id"]))
    sim.run_until_idle()
    assert db.get_job(j["id"])["status"] == "done" and len(db.project_analysis(pid, "summary")) == 9
    st = _batch_state()["batches"]
    assert len(st) == 2 and not st[decoy]["cancelled"] and st[ours]["results_reads"] == 1 and st[decoy]["results_reads"] == 1
    assert db.connect().execute("SELECT COUNT(*) FROM invocations WHERE provider='anthropic_batch' AND state='completed'").fetchone()[0] == 10


def test_batch_recovery_resubmits_only_after_every_candidate_is_rejected(monkeypatch):
    """Our submission never reached the provider (crash), but a same-sized foreign batch exists in the window: it is
    observed, rejected by custom_id set, and ONLY then does the job submit afresh — the foreign batch untouched."""
    import json as _json
    pid, ids = _golden(monkeypatch)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_NO_CLIENT_REF", "1")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    sim = crashkit.Sim()
    jobs.CRASH_AT["batch_after_create_before_persist"] = 1
    assert sim.step(("suggest_findings_batch",)) == "crashed"
    path = settings.data_dir / "fake_batches.json"
    d = _json.loads(path.read_text()); d["batches"].clear(); path.write_text(_json.dumps(d))    # the provider never had ours
    decoy = _decoy_batch(10)
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    assert db.derived_status(db.get_job(j["id"])) == "external_tentative"
    assert jobs.poll_external_once() == 0                                        # decoy ended → rejected → job handed back to the queue
    jj = db.get_job(j["id"])
    assert jj["status"] == "queued" and jj["external_handle"] is None
    kinds = [e["event_type"] for e in db.job_events(j["id"])]
    assert "external_candidate_rejected" in kinds and "external_recovery_resubmit" in kinds and "external_reattached" not in kinds
    assert sim.step(("suggest_findings_batch",)) == "external_pending"           # resubmitted: the rejected decoy is never a candidate again
    assert "external_recovery_no_candidate" in [e["event_type"] for e in db.job_events(j["id"])]
    ours = db.get_job(j["id"])["external_handle"]
    assert ours != decoy and not ours.startswith("tentative:") and all(it["batch_id"] == ours for it in db.batch_items(j["id"]))
    sim.run_until_idle()
    assert db.get_job(j["id"])["status"] == "done" and len(db.project_analysis(pid, "summary")) == 9
    st = _batch_state()["batches"]
    assert set(st) == {decoy, ours} and not st[decoy]["cancelled"]


# ---------------------------------------------------------------- Rung G2/G3: now vs background, stale rebuilds through the batch transport

def test_batch_estimate_uses_token_counts_with_cache_and_fallback(monkeypatch):
    """Both quotes come from the provider's token counter when available (cached per input, bounded calls per
    estimate), from the character estimate otherwise — and the UI never depends on counting succeeding."""
    from neurosearch import batches, providers
    pid, ids = _golden(monkeypatch)
    calls = {"n": 0}
    real = providers.anthropic_client
    class Counting:
        def __init__(self, inner): self._inner = inner; self.messages = self
        def count_tokens(self, **kw): calls["n"] += 1; return self._inner.messages.count_tokens(**kw)
    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: Counting(real(**kw)))
    e1 = batches.estimate(pid, force=True)
    assert e1["items"] == 10 and e1["basis"] == "token count" and e1["input_tokens"] > 0 and calls["n"] == 10
    assert abs(e1["background"] - e1["now"] * 0.5) < 1e-4 and e1["recommended"] == "background" and e1["bulk_threshold_items"] == batches.BULK_THRESHOLD_ITEMS
    assert e1["choices"]["now"]["label"] == "Analyze now" and "24 hours" in e1["choices"]["background"]["detail"] and "50%" in e1["choices"]["background"]["detail"]
    e2 = batches.estimate(pid, force=True)                                        # cached: no further counting calls
    assert calls["n"] == 10 and e2["now"] == e1["now"] and e2["basis"] == "token count"
    one = batches.estimate(pid, [ids["yt01"]], force=True)                          # one small source → analyze now
    assert one["items"] == 1 and one["recommended"] == "now"
    # counting unavailable → character estimate, same shape, still both quotes
    class Broken:
        def __init__(self): self.messages = self
        def count_tokens(self, **kw): raise RuntimeError("counting endpoint down")
    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: Broken())
    db.connect().execute("DELETE FROM kv WHERE key LIKE 'tokcount:%'"); db.connect().commit()
    e3 = batches.estimate(pid, force=True)
    assert e3["basis"] == "estimate" and e3["input_tokens"] is None and e3["now"] > 0 and abs(e3["background"] - e3["now"] * 0.5) < 1e-4
    # bounded: with a low call cap the rest fall back → 'mixed'
    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: Counting(real(**kw)))
    monkeypatch.setattr(batches, "MAX_COUNT_CALLS", 3)
    calls["n"] = 0
    e4 = batches.estimate(pid, force=True)
    assert calls["n"] == 3 and e4["basis"] == "mixed"


def test_suggest_api_keeps_transport_explicit(monkeypatch):
    """/suggest and /suggest/estimate: the transport is the caller's explicit choice, recorded on the durable job;
    nothing converts an ordinary findings job into a batch job. (Endpoint functions called directly: the app's MCP
    lifespan can only be started once per process.)"""
    from fastapi import HTTPException
    from neurosearch import api
    pid, ids = _golden(monkeypatch)
    monkeypatch.setattr(jobs.db, "claim_job", lambda *a, **k: None)
    est = api.api_suggest_estimate(pid, api.EstimateIn(force=True))
    assert est["items"] == 10 and est["now"] > est["background"] > 0 and est["recommended"] == "background"
    r_now = api.api_suggest(pid, api.SuggestIn(source_ids=[ids["yt01"]], transport="interactive"))
    r_bg = api.api_suggest(pid, api.SuggestIn(source_ids=[ids["yt02"]], transport="batch"))
    assert db.get_job(r_now["job"])["kind"] == "suggest_findings" and db.get_job(r_bg["job"])["kind"] == "suggest_findings_batch"
    with pytest.raises(HTTPException):
        api.api_suggest(pid, api.SuggestIn(transport="carrier-pigeon"))
    j = api.api_job(r_bg["job"])
    assert j["batch"]["phase"] == "queued" and "background" in j["batch"]["label"]
    # default transport is interactive: an unadorned request never becomes a batch job
    r_def = api.api_suggest(pid, api.SuggestIn(source_ids=[ids["yt03"]]))
    assert db.get_job(r_def["job"])["kind"] == "suggest_findings" and r_def["transport"] == "interactive"
    # the stale-rebuild endpoint carries the same explicit choice
    with pytest.raises(HTTPException):
        api.api_rebuild_stale(pid, api.RebuildIn(what=["findings"], transport="nope"))


def test_stale_rebuild_in_background_plan_waits_and_sources_land_one_by_one(monkeypatch):
    """G3: brief changes → findings stale; the user chooses background for the re-analysis → ONE batch job for the
    stale sources, the plan job blocked on it exactly as on synchronous jobs; sources become current as their
    results materialise; the plan builds only after the batch job is done."""
    from neurosearch import findings, planner, staleness
    pid, ids = _golden(monkeypatch)
    for gid, sid in ids.items():
        if gid != "calc":
            findings.suggest_for_source(pid, sid)
    planner.build_plan(pid)
    db.update_project(pid, brief="Now the project is about SELLING a small business, not buying one")
    s1 = staleness.assess(pid)
    assert s1["stale_sources"] == 8 and s1["plan"]["status"] == "stale"
    assert abs(s1["estimate"]["findings_background"] - s1["estimate"]["findings"] * 0.5) < 1e-6 and s1["estimate"]["total_background"] < s1["estimate"]["total"]
    r = staleness.rebuild(pid, ["findings", "plan"], transport="batch")
    assert r["queued"] == 2 and r["transport"] == "batch"
    bj, pj = (db.get_job(i) for i in r["job_ids"])
    assert bj["kind"] == "suggest_findings_batch" and sorted(bj["payload"]["source_ids"]) == sorted(x["source_id"] for x in s1["sources"] if x["status"] == "stale")
    assert bj["payload"]["force"] is True and bj["payload"]["reason"] == "stale" and pj["kind"] == "build_plan" and pj["blocked_by"] == [bj["id"]]
    s2 = staleness.assess(pid)
    assert s2["rebuilding"] == 9 and s2["stale_sources"] == 0 and s2["plan"]["status"] == "rebuilding" and "waiting for research" in s2["plan"]["note"]
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    assert sim.step(("build_plan",)) is None                                        # the plan is blocked on the batch, not claimable
    assert db.derived_status(db.get_job(pj["id"])) == "blocked"
    st = staleness.assess(pid)
    assert st["rebuilding"] == 9 and all("in background" in (x["note"] or "") for x in st["sources"] if x["status"] == "rebuilding")
    # results arrive: the batch job materialises each source; the moment one has landed it is current + usable
    jobs.poll_external_once()
    assert sim.step(("suggest_findings_batch",)) == "done"
    s3 = staleness.assess(pid)
    assert s3["stale_sources"] == 0 and sum(1 for x in s3["sources"] if x["status"] == "current") == 8 and s3["plan"]["status"] == "rebuilding"
    assert db.get_analysis(pid, ids["yt01"], "summary")["transport"] == "batch"
    assert db.sources_being_analysed(pid) == set()
    assert sim.step(("build_plan",)) == "done"
    s4 = staleness.assess(pid)
    assert not s4["anything_stale"] and s4["plan"]["status"] == "current" and s4["plan"]["version"] == 2


def test_batch_partial_failure_completed_sources_usable_while_retrying(monkeypatch):
    """While one window retries in a second round, the other sources' findings are already written, current, and no
    longer reported as being analysed; the job's UI state names the retry."""
    from neurosearch import batches, staleness
    pid, ids = _golden(monkeypatch)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE", f"fw-{ids['yt02'][:12]}")
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": list(ids.values())})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"
    assert batches.ui_state(db.get_job(j["id"]))["phase"] == "processing"
    assert db.sources_being_analysed(pid) == set(ids.values())
    jobs.poll_external_once()
    assert sim.step(("suggest_findings_batch",)) == "external_pending"              # round 2: the failed window only
    ui = batches.ui_state(db.get_job(j["id"]))
    assert ui["phase"] == "processing" and ui["done"] == 8 and ui["retrying"] == 1 and "retrying 1 item (round 2)" in ui["label"]
    assert db.sources_being_analysed(pid) == {ids["yt02"]}                          # the eight completed sources are usable now
    assert len(db.list_project_notes(pid, status="suggested")) > 0 and len(db.project_analysis(pid, "summary")) == 8
    assert {x["status"] for x in staleness.assess(pid)["sources"] if x["source_id"] != ids["yt02"]} == {"current"}
    sim.run_until_idle()
    ui = batches.ui_state(db.get_job(j["id"]))
    assert ui["phase"] == "complete" and ui["done"] == 9


def test_batch_ui_state_names_failure_and_cancel(monkeypatch):
    from neurosearch import batches
    pid, ids = _golden(monkeypatch)
    monkeypatch.setattr(batches, "MAX_COHORTS", 1)
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE", f"fw-{ids['yt02'][:12]}")
    j = db.create_job("suggest_findings_batch", {"project_id": pid})
    crashkit.Sim().run_until_idle()
    ui = batches.ui_state(db.get_job(j["id"]))
    assert ui["phase"] == "partial_failure" and ui["done"] == 8 and "1 errored" in ui["label"]
    monkeypatch.delenv("NEUROSEARCH_FAKE_BATCH_FAIL_ONCE")
    monkeypatch.setenv("NEUROSEARCH_FAKE_BATCH_READY_AFTER", "5")
    j2 = db.create_job("suggest_findings_batch", {"project_id": pid, "force": True})
    sim = crashkit.Sim(); assert sim.step(("suggest_findings_batch",)) == "external_pending"
    db.request_cancel(j2["id"]); batches.cancel_job(db.get_job(j2["id"]))
    ui = batches.ui_state(db.get_job(j2["id"]))
    assert ui["phase"] == "canceled" and "kept" in ui["label"] and ui["done"] >= 1


def test_batch_smoke_fake_passes_and_leaves_nothing_behind(monkeypatch, tmp_path):
    """`neurosearch batch-smoke` (fake tier): the exact flow the single live run takes — eval-only database, one frozen
    single-window item, real adapter code path, every check — ends PASS, writes its report, restores settings and
    deletes its database."""
    from pathlib import Path
    from neurosearch import batch_smoke
    was_dir, was_fake = settings.data_dir, settings.fake_ai
    rep = batch_smoke.run(live=False, progress=lambda m: None, out_dir=tmp_path)
    assert rep["verdict"] == "PASS" and not rep["fails"] and len(rep["checks"]) >= 18 and all(c["pass"] for c in rep["checks"])
    assert rep["tier"] == "fake" and rep["batch_id"].startswith("msgbatch_") and rep["expected_custom_id"].startswith("fw-")
    p = rep["pricing"]
    assert abs(p["actual_batch_cost"] - p["standard_model_cost"] * 0.5) < 1e-6 and p["input_tokens"] > 0 and p["output_tokens"] > 0
    assert rep["structured_outputs"]["mismatches"] == 0 and rep["notes"] >= 1 and rep["analysis"]["transport"] == "batch"
    assert Path(rep["artifact"]).exists() and Path(rep["artifact"]).with_suffix(".txt").read_text().endswith("Batch smoke PASS")
    assert settings.data_dir == was_dir and settings.fake_ai == was_fake and not Path(rep["database"]).exists()


# ---------------------------------------------------------------- Rung G (second portion): prompt-cache layout

LEGACY_PROJECT_BLOCK = """
Project: {name}
Project brief (what the user is trying to find out — let this shape what you emphasise):
{brief}

You can shape the project as you talk:
- update_brief: when the user asks to change, widen, narrow or refocus what the project is about. Rewrite the
  whole brief (keep what still applies, fold in the change) and confirm the change in one sentence.
- save_finding: when the user says to pin, save, remember or note something, or asks you to record a
  conclusion. Save a self-contained finding in plain prose with the same [n] citations you used.
- note_gap: record a coverage gap you identified (see Gap detection).
- record_fact: when the user states a decision ("we're going with X"), a constraint (budget, deadline, must/must-not),
  a requirement, or rejects an option, record it so the Master Planner can use it. Kinds: decision | constraint |
  requirement | rejected. Do not record things you merely inferred.
Pinned findings so far (do not repeat them unless asked; build on them):
{findings}
Known project facts (decisions, constraints, requirements):
{facts}
What the user told us when setting up the project (treat as requirements, not suggestions):
{steering}
"""


def _legacy_chat_system(project, use_web, full_context):
    """The 0.20.0+g3 chat system prompt, verbatim (one block; findings/facts inside the project block)."""
    from neurosearch import qa, usage
    notes = db.list_project_notes(project["id"])[:15]
    findings = "\n".join(f"- {n['content'][:400]}" for n in notes) or "(none yet)"
    facts = "\n".join(f"- [{f['kind']}] {f['content']}" for f in db.list_facts(project["id"])) or "(none yet)"
    block = LEGACY_PROJECT_BLOCK.format(name=project["name"], brief=project.get("brief") or "(none)", findings=findings, facts=facts, steering=db.project_steering(project))
    system = qa.SYSTEM.format(web_rule=qa.WEB_RULE_ON if use_web else qa.WEB_RULE_OFF, project_block=block)
    blocks = [usage.cached_block(system)]
    if full_context is not None:
        blocks.append(usage.cached_block(f"The user's material (cite it as [n]):\n<excerpts>\n{full_context}\n</excerpts>", min_chars=len(system)))
    return blocks


def test_cache_layout_preserves_request_content_exactly(monkeypatch):
    """Deterministic equivalence gate: the reordered chat and findings prompts carry exactly the same lines as the
    previous layout (multiset of non-empty lines over tools + system + messages) — nothing added, nothing lost —
    and the volatile project state sits AFTER the cached prefix."""
    from neurosearch import cache_layout, findings, qa
    pid, ids = _golden(monkeypatch)
    project = db.get_project(pid)
    db.add_project_note(pid, "Pinned: ten percent down is typical.", citations=[], status="approved")
    db.add_fact(pid, "constraint", "Budget under one million.")
    project = db.get_project(pid)
    tools = qa._project_tools()
    for use_web in (False, True):
        for full in (None, "[1] Excerpt one\nsome text\n[2] Excerpt two\nmore text"):
            new, _ = qa.chat_system_blocks(project, use_web, tools, full)
            old = _legacy_chat_system(project, use_web, full)
            a, b = cache_layout.request_content(tools, old, []), cache_layout.request_content(tools, new, [])
            assert a == b, cache_layout.content_diff(a, b)
            assert "Pinned: ten percent down" in new[-1]["text"] and "Budget under one million" in new[-1]["text"] and "cache_control" not in new[-1]
            assert "Pinned findings" not in new[0]["text"] and "Known project facts" not in new[0]["text"]
            assert "Project brief" in new[0]["text"] and "What the user told us" in new[0]["text"]
    # findings: [rules][project][source] carries the same lines as [rules][project+source]
    for sid in ids.values():
        src = db.get_source(sid)
        head = findings._head(project, src)
        new_blocks = findings._system_blocks(findings.SYSTEM, head)
        old_blocks = [{"type": "text", "text": findings.SYSTEM}, {"type": "text", "text": head}]
        a, b = cache_layout.request_content(None, old_blocks, []), cache_layout.request_content(None, new_blocks, [])
        assert a == b and len(new_blocks) == 3 and new_blocks[1]["text"].startswith("PROJECT:") and new_blocks[2]["text"].startswith("SOURCE:")
    # the project block is byte-identical across sources (that is what makes the shared prefix cacheable)
    heads = {findings._system_blocks(findings.SYSTEM, findings._head(project, db.get_source(s)))[1]["text"] for s in ids.values()}
    assert len(heads) == 1


def test_cache_layout_measurement_and_savings(monkeypatch):
    """The fake cache simulation follows the provider's rules (read + write + plain == total per request; ≥1024-token
    prefixes only; exact-prefix hits) and the layout delivers: the stable chat prefix is read on every later turn —
    including after a finding is pinned and a fact recorded mid-conversation — and in a new conversation."""
    from neurosearch import cache_layout, fake_ai
    monkeypatch.setattr(settings, "daily_budget", 1000)
    rep = cache_layout.run(progress=lambda m: None)
    for sc in rep["scenarios"].values():
        for e in sc["requests_detail"]:
            assert e["read"] + e["write"] + e["plain"] == e["total"] and e["read"] >= 0 and e["write"] >= 0
    chat = rep["chat_layout"]
    assert chat[0]["read"] == 0 and all(t["read"] > 0 and t["read"] == chat[1]["read"] for t in chat[1:])          # stable prefix read on turns 2-4
    assert chat[2]["system_blocks"][-1][0] > chat[1]["system_blocks"][-1][0]                                      # the state block grew after the pin/fact…
    assert chat[2]["read"] == chat[1]["read"]                                                                     # …and the prefix hit survived it
    assert chat[1]["read"] >= fake_ai.CACHE_MIN_TOKENS
    new_conv = rep["scenarios"]["project chat (new conversation, 3 turns)"]
    assert new_conv["cache_read"] == 3 * chat[1]["read"]                                                          # every turn of a later conversation reads the prefix
    assert rep["scenarios"]["planner (analysis + build)"]["cache_read"] > 0
    assert rep["input_cost_index"] < 1.0
    # default (tail breakpoint OFF): nothing volatile is written; the override (ON) writes the tail every turn at 1.25×
    tail_on = rep["scenarios"]["project chat (new conv, tail breakpoint ON)"]
    assert new_conv["cache_write"] == 0 and tail_on["cache_write"] > 0 and tail_on["cache_read"] == new_conv["cache_read"]
    assert new_conv["input_cost_index"] < tail_on["input_cost_index"] and new_conv["total_input_tokens"] == tail_on["total_input_tokens"]   # content identical either way
    assert all(t["write"] == 0 for t in chat[1:]) and chat[0]["write"] > 0                                     # only the stable prefix is ever written


# ---------------------------------------------------------------- Rung H1: findings window pre-filter

def test_prefilter_off_by_default_changes_nothing(monkeypatch):
    from neurosearch import findings, prefilter
    pid, ids = _golden(monkeypatch)
    assert not prefilter.enabled()
    project, src = db.get_project(pid), db.get_source(ids["yt03"])
    windows = findings._windows(db.get_segments(src["id"]), src["platform"])
    kept, summary = findings.window_plan(project, src, windows)
    assert kept == {0, 1} and summary is None and db.window_decisions(pid) == []
    r = findings.suggest_for_source(pid, ids["yt03"])
    assert r["prefilter"] is None and db.get_analysis(pid, ids["yt03"], "summary").get("prefilter") is None


def test_prefilter_eval_gates_and_economics(monkeypatch):
    """The labeled fixture: whole-window mode must pass every hard gate and actually save money; the sampled mode is
    reported as an experiment and the gates must CATCH its buried-nugget miss (that is what the gates are for)."""
    from neurosearch import prefilter_eval
    monkeypatch.setattr(settings, "daily_budget", 1000)
    rep = prefilter_eval.run(progress=lambda m: None)
    assert rep["fixture"]["windows"] == 16 and rep["fixture"]["relevant_windows"] == 10 and rep["fixture"]["nuggets"] == 12
    whole = rep["modes"]["whole window"]
    assert whole["quality_pass"] and whole["recall"] == 1.0 and not whole["false_negatives"] and not whole["unreachable_nuggets"] and not whole["lost_relevant_sources"]
    assert whole["decisions"]["drop"] >= 5 and whole["windows_dropped_share"] >= 0.3 and whole["tokens_dropped_share"] >= 0.4
    assert whole["net_saved"] > 0 and whole["leverage"] > 1.0 and whole["filter_cost"] > 0 and whole["fail_open"] == 0
    assert whole["filtered_evidence_recall"] >= rep["unfiltered_evidence_recall"]
    # economics at current list prices (Haiku $1/$5, Sonnet 5 $2/$10, batches ×0.5), against the transport the product would use:
    sc = whole["scenarios"]
    assert 0.15 < sc["interactive"]["net_saved_share"] < 0.20 and sc["interactive"]["leverage"] >= 1.5                      # interactive bulk: pays
    assert sc["background"]["net_saved_share"] < 0 and sc["background"]["leverage"] < 1.0                                    # background bulk: the filter costs MORE than plain batching
    assert sc["background"]["break_even_irrelevant_token_share"] > 0.6                                                      # …unless ~2/3 of the corpus is waste
    assert sc["background_batched_filter"]["net_saved_share"] > 0.15 and sc["background_batched_filter"]["batch_stages"] == 2   # only a two-stage batch pays, at 2×24 h latency
    assert not whole["economics_pass"] and not whole["pass"]                                                                # the background gate (≥10% net, ≥1.25×) FAILS
    assert whole["per_source"]["tangent"]["decisions"] == ["uncertain"]                        # the buried nugget: not dropped
    assert whole["per_source"]["mixed"]["decisions"][1] == "keep" and whole["per_source"]["beekeeping"]["decisions"] == ["drop", "drop"]
    prov = whole["provenance_example"]
    assert prov and prov["drop"] == 2 and prov["configured_model"] == "claude-haiku-4-5" and prov["prompt_version"].startswith("prefilter-") and prov["schema_version"] == "prefilter-v1"
    sampled = rep["modes"]["sampled 8,000 chars"]
    assert not sampled["quality_pass"] and not sampled["pass"] and sampled["false_negatives"] == [{"source": "tangent", "window": 0}] and sampled["leverage"] > whole["leverage"]
    assert sampled["economics_pass"]                                                                                        # cheap AND unsafe: exactly the trade the gates refuse
    assert not rep["pass"] and rep["production_mode"] == "whole window"


def test_prefilter_fails_open_on_every_failure_kind(monkeypatch):
    from neurosearch import findings, prefilter
    pid, ids = _golden(monkeypatch)
    monkeypatch.setattr(settings, "findings_prefilter", True)
    project, src = db.get_project(pid), db.get_source(ids["sourdough"])
    windows = findings._windows(db.get_segments(src["id"]), src["platform"])
    for mode, expect in (("error", "outage"), ("bad_json", "conform"), ("refuse", "REFUSED")):
        monkeypatch.setenv("NEUROSEARCH_FAKE_PREFILTER", mode)
        db.connect().execute("DELETE FROM window_decisions"); db.connect().commit()
        rows = prefilter.decide_windows(project, src, windows)
        assert rows[0]["decision"] == "uncertain" and rows[0]["fail_open"] and expect in rows[0]["fail_open"], (mode, rows[0]["fail_open"])
        kept, summary = findings.window_plan(project, src, windows)
        assert kept == {0} and summary["fail_open"] == 1 and summary["drop"] == 0
    monkeypatch.delenv("NEUROSEARCH_FAKE_PREFILTER")
    h = db.health()["prefilter"]
    assert h["fail_open"] >= 3 and h["enabled"] is True
    assert db.connect().execute("SELECT COUNT(*) FROM validation_events WHERE kind='prefilter_fail_open'").fetchone()[0] >= 3


def test_prefilter_aggressive_source_is_flagged_not_overridden(monkeypatch):
    from neurosearch import findings, prefilter
    pid, ids = _golden(monkeypatch)
    monkeypatch.setattr(settings, "findings_prefilter", True)
    monkeypatch.setattr(prefilter, "ANOMALY_MIN_WINDOWS", 2)
    monkeypatch.setenv("NEUROSEARCH_FAKE_PREFILTER", "drop_all")
    project, src = db.get_project(pid), db.get_source(ids["yt03"])
    windows = findings._windows(db.get_segments(src["id"]), src["platform"])
    kept, summary = findings.window_plan(project, src, windows)
    assert kept == set() and summary["drop"] == 2                                            # the decision stands (no hidden quota)…
    ev = db.connect().execute("SELECT detail FROM validation_events WHERE kind='prefilter_aggressive'").fetchall()
    assert len(ev) == 1 and db.health()["prefilter"]["aggressive_sources_flagged"] == 1       # …but it is flagged where a person will see it


def test_prefilter_decisions_are_durable_and_invalidated_by_filter_changes(monkeypatch):
    from neurosearch import fake_ai, findings, prefilter
    pid, ids = _golden(monkeypatch)
    project, src = db.get_project(pid), db.get_source(ids["yt01"])
    windows = findings._windows(db.get_segments(src["id"]), src["platform"])
    n0 = len(fake_ai.CACHE_LOG)
    a = prefilter.decide(project, src, 0, 1, windows[0])
    b = prefilter.decide(project, src, 0, 1, windows[0])
    assert a["decision"] == "keep" and not a["cached"] and b["cached"] and len(fake_ai.CACHE_LOG) == n0 + 1      # same inputs: stored row, no second call
    monkeypatch.setattr(prefilter, "SYSTEM", prefilter.SYSTEM + "\n(revised)")
    c = prefilter.decide(project, src, 0, 1, windows[0])
    assert not c["cached"] and c["input_hash"] != a["input_hash"] and c["prompt_version"] != a["prompt_version"]        # prompt change → re-evaluated
    monkeypatch.setenv("NEUROSEARCH_TASK_MODEL_FINDINGS_PREFILTER", "claude-haiku-4-6")
    d = prefilter.decide(project, src, 0, 1, windows[0])
    assert not d["cached"] and d["configured_model"] == "claude-haiku-4-6" and d["input_hash"] != c["input_hash"]     # model change → re-evaluated
    monkeypatch.delenv("NEUROSEARCH_TASK_MODEL_FINDINGS_PREFILTER")
    db.update_project(pid, brief="A completely different brief about beekeeping")
    e = prefilter.decide(db.get_project(pid), src, 0, 1, windows[0])
    assert not e["cached"] and e["input_hash"] not in (a["input_hash"], c["input_hash"])                              # brief change → re-evaluated
    assert len(db.window_decisions(pid, src["id"])) == 4


def test_prefilter_batch_path_skips_dropped_windows_and_keeps_provenance(monkeypatch):
    """Batch transport with the filter on: dropped windows are never submitted; a source whose windows are
    non-contiguous after filtering still materialises; provenance carries the filter summary."""
    from neurosearch import findings, prefilter_eval
    pid, gids = _golden(monkeypatch)
    lab = prefilter_eval.load_labeled(pid, gids)
    ids = lab["ids"]
    monkeypatch.setattr(settings, "findings_prefilter", True)
    items = findings.batch_requests(pid, ids["mixed"])
    assert [it["window_index"] for it in items] == [1] and items[0]["windows"] == 1 and items[0]["prefilter"]["drop"] == 1 and items[0]["prefilter"]["keep"] == 1
    assert findings.batch_requests(pid, ids["beekeeping"]) == []                            # everything dropped: nothing to submit
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": [ids["mixed"], ids["tangent"], ids["beekeeping"]]})
    sim = crashkit.Sim(); sim.run_until_idle()
    jj = db.get_job(j["id"])
    assert jj["status"] == "done" and jj["result"]["items"] == 2 and jj["result"]["done"] == 2
    an = db.get_analysis(pid, ids["mixed"], "summary")
    pf = __import__("json").loads(an["prefilter"])
    assert an["transport"] == "batch" and pf["windows"] == 2 and pf["drop"] == 1 and pf["keep"] == 1
    assert db.get_analysis(pid, ids["beekeeping"], "summary") is None                       # never analysed, never claimed current
    notes = db.list_project_notes(pid, status="suggested")
    assert any(n["source_id"] == ids["mixed"] for n in notes)


def test_prefilter_fixture_is_frozen():
    """The generated labeled-window fixture still produces exactly the labeled windows (regenerate labels if not)."""
    import json as _json
    from pathlib import Path
    from neurosearch import prefilter_eval
    labels = _json.loads((prefilter_eval.PREFILTER_DIR / "labels.json").read_text())
    assert [s["id"] for s in labels["sources"]] == ["beekeeping", "marathon", "mixed", "tangent"] and labels["version"] == 1
    assert sum(len(s["relevant"]) for s in labels["sources"]) == 6 and sum(len(v) for v in labels["golden"].values()) == 10
    for s in labels["sources"]:
        assert (prefilter_eval.PREFILTER_DIR / s["file"]).exists()
