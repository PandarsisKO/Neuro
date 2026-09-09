"""R0 (SPEED-MISSION.md) — the timing ledger and the in-flight invocation leak it exposed.

Two things are gated here. (1) The instrument itself: bounded in-memory samples, percentiles, cache hit
rates, and an ASGI middleware that keys on the ROUTE TEMPLATE so a per-project path cannot mint a new
counter per id. It must add no table and no write, because an instrument that slows the path it measures
is worse than none. (2) The defect R0's first reading found: 432 invocations stuck 'in_flight' on Kyle's
live database, every one a batch findings call whose job had been cancelled — `mark_ambiguous_invocations`
only ever ran on lease expiry, so every other terminal path leaked. (Sorts after test_o2.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_perf_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, db, perf  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    perf.reset()
    yield
    perf.reset()
    db._local.conn = None


# ---------------------------------------------------------------- the instrument

def test_samples_are_bounded_and_percentiles_track_the_recent_window():
    """The ledger must never grow: it is deliberately not a table, so its whole safety argument is that
    memory is capped per key regardless of how long the process runs."""
    for i in range(perf.SAMPLES * 3):
        perf.record("k", i / 1000.0)
    s = perf.stats("k")
    assert s["n"] == perf.SAMPLES                     # capped, not cumulative
    assert s["max"] == round((perf.SAMPLES * 3 - 1) / 1000.0, 4)   # keeps the RECENT window, not the first
    assert s["p50"] < s["p90"] <= s["max"]
    assert perf.stats("never-recorded") is None


def test_cache_counters_and_slowest_ordering():
    perf.mark("embed_query", True); perf.mark("embed_query", True); perf.mark("embed_query", False)
    perf.record("fast", 0.01); perf.record("slow", 2.0)
    snap = perf.snapshot()
    assert snap["caches"]["embed_query"] == {"hit": 2, "miss": 1, "rate": round(2 / 3, 4)}
    assert list(snap["timings"]) == ["slow", "fast"]          # slowest first — the answer, not a sort exercise
    assert [x["key"] for x in perf.slowest(1)] == ["slow"]
    perf.reset()
    assert perf.snapshot()["timings"] == {} and perf.snapshot()["caches"] == {}


def test_middleware_keys_on_the_route_template_not_the_raw_path(client):
    """`/api/projects/<uuid>/jobs` must record ONE key, not one per project — otherwise the ledger measures
    nothing and grows without bound, which is the failure mode this design exists to avoid. (Uses the
    session-scoped client from conftest: the app's MCP mount can only start once per process.)"""
    p = db.create_project("Perf", "brief")
    perf.reset()
    h = {"Authorization": "Bearer t0k"}
    for _ in range(3):
        client.get(f"/api/projects/{p['id']}/jobs", headers=h)
    client.get("/api/stats", headers=h)
    keys = perf.snapshot()["timings"]
    assert "GET /api/projects/{project_id}/jobs" in keys
    assert keys["GET /api/projects/{project_id}/jobs"]["n"] == 3       # one key, three samples
    assert not any(p["id"] in k for k in keys)                          # no id ever becomes a key
    assert "GET /api/stats" in keys


def test_perf_endpoint_joins_memory_with_the_durable_tables():
    """§A's baseline must regenerate itself: endpoint timings come from memory, queue wait and model latency
    from the tables that are already written anyway."""
    j = db.create_job("reembed", {})
    db.claim_job(("reembed",))
    db.finish_job(j["id"], db.get_job(j["id"])["run_id"], "done", message="done")
    perf.record("GET /api/stats", 0.4)
    out = api.api_perf(days=7)
    assert out["timings"]["GET /api/stats"]["p50"] == 0.4
    assert any(q["kind"] == "reembed" for q in out["queue"])
    q = next(q for q in out["queue"] if q["kind"] == "reembed")
    assert q["n"] == 1 and 0.0 <= q["waiting_share"] <= 1.0
    assert isinstance(out["models"], list)                              # no completed invocations yet, but shaped


# ---------------------------------------------------------------- the leak R0 found

def _inflight(job_id: str) -> str:
    iid = db.invocation_start("anthropic_batch", "findings.extract", "m", None, job_id, None)
    assert db.get_invocation_state(iid) == "in_flight"
    return iid


def test_a_finished_job_never_leaves_a_call_in_flight():
    """432 rows on the live database said otherwise. A terminal job resolves its calls to outcome_unknown —
    never to 'completed', because whether the provider ran it is genuinely unknown once the run is gone."""
    j = db.create_job("suggest_findings", {})
    db.claim_job(("suggest_findings",))
    iid = _inflight(j["id"])
    db.finish_job(j["id"], db.get_job(j["id"])["run_id"], "failed", message="boom")
    assert db.get_invocation_state(iid) == "outcome_unknown"


def test_cancelling_external_work_resolves_its_in_flight_calls():
    """The exact path that produced all 432: a batch job cancelled while the provider may still be running it."""
    j = db.create_job("suggest_findings_batch", {})
    db.claim_job(("suggest_findings_batch",))
    iid = _inflight(j["id"])
    db.park_external(j["id"], db.get_job(j["id"])["run_id"], "anthropic", "batch", "batch_123")
    assert db.request_cancel(j["id"]) == "cancelled"
    assert db.get_invocation_state(iid) == "outcome_unknown"


def test_startup_resolves_orphans_but_never_touches_a_live_run():
    """Self-healing safety net (like _backfill_job_lanes) for any terminal path nobody thought of — and it must
    NOT resolve calls belonging to a job that is still running, or a healthy batch would be declared ambiguous."""
    dead = db.create_job("suggest_findings", {})
    db.claim_job(("suggest_findings",))
    dead_call = _inflight(dead["id"])
    db.connect().execute("UPDATE jobs SET status='cancelled' WHERE id=?", (dead["id"],))   # a path that forgot to resolve
    db.connect().commit()

    live = db.create_job("suggest_findings", {})
    db.claim_job(("suggest_findings",))
    live_call = _inflight(live["id"])

    assert db._resolve_orphan_invocations(db.connect()) == 1
    assert db.get_invocation_state(dead_call) == "outcome_unknown"
    assert db.get_invocation_state(live_call) == "in_flight"            # still running: untouched
    assert db._resolve_orphan_invocations(db.connect()) == 0            # idempotent
