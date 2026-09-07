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
    assert [b.get("cache_control") for b in long_items[0]["params"]["system"]] == [None, {"type": "ephemeral", "ttl": "1h"}]
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
    assert est["items"] == 10 and est["sources"] == 9 and abs(est["background"] - est["now"] * 0.5) < 1e-6 and "model cost only" in est["note"] and "24 hours" in est["note"]
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


def test_batch_recovery_heuristic_for_the_real_api(monkeypatch):
    """Without a client reference on the real API, an orphaned batch is claimed only when it was created after our
    recorded intent with exactly our item count — and a claimed batch whose results carry foreign custom_ids is reported."""
    import json as _json
    from neurosearch import batches, providers
    pid, ids = _golden(monkeypatch)
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": [ids["yt01"]]})
    items, _ = batches.plan_items(pid, [ids["yt01"]])
    db.batch_items_add(j["id"], 1, items)
    monkeypatch.setattr(settings, "fake_ai", False)
    ref = f"{j['id']}#1"
    db.kv_set(f"batch:intent:{ref}", _json.dumps({"job_id": j["id"], "cohort_no": 1, "n": len(items), "ts": 1000.0}))
    class Counts:
        def __init__(self, n): self.processing, self.succeeded, self.errored, self.canceled, self.expired = n, 0, 0, 0, 0
    class B:
        def __init__(self, id, ts, n): self.id, self.created_at, self.request_counts = id, ts, Counts(n)
    class Stub:
        class messages:
            class batches:
                @staticmethod
                def list(limit=20): return type("P", (), {"data": [B("old", 900.0, len(items)), B("other-size", 1001.0, len(items) + 3), B("ours", 1001.0, len(items))]})()
    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: Stub())
    assert batches.AnthropicBatch.find_by_ref(ref) == "ours"
    assert all(it["status"] == "submitted" and it["batch_id"] == "ours" for it in db.batch_items(j["id"]))
    assert any(e["event_type"] == "external_reattached" and e["payload"]["where"] == "recovery_heuristic" for e in db.job_events(j["id"]))
