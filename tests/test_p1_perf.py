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

from neurosearch import api, cache, db, perf  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    perf.reset()
    cache.invalidate()
    yield
    perf.reset()
    cache.invalidate()
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


# ---------------------------------------------------------------- R2: revision-keyed derived-state cache

def test_cache_reuses_only_while_the_revision_holds():
    """The whole safety argument for caching derived research state: entries retire because the revision moved,
    never because a timer expired. A cache that can be stale under any timing is not acceptable here."""
    calls = []
    def compute():
        calls.append(1)
        return {"v": len(calls)}

    assert cache.get_or_compute("k", "rev1", compute) == {"v": 1}
    assert cache.get_or_compute("k", "rev1", compute) == {"v": 1}      # same revision → reused, not recomputed
    assert len(calls) == 1
    assert cache.get_or_compute("k", "rev2", compute) == {"v": 2}      # revision moved → recomputed
    assert len(calls) == 2
    assert perf.snapshot()["caches"]["k"] == {"hit": 1, "miss": 2, "rate": round(1 / 3, 4)}
    assert cache.invalidate("k") == 1 and cache.size() == 0


def test_research_revision_moves_on_any_input_change_including_deletion():
    """If the revision does not move when research state changes, every cache keyed on it serves stale answers —
    so this is the single assertion the R2/R3 caches actually rest on. COUNT is in the fingerprint precisely so
    that a DELETE moves it, which a MAX(updated_at) alone would not."""
    p = db.create_project("Rev", "brief")
    r0 = db.project_research_revision(p["id"])
    assert db.project_research_revision(p["id"]) == r0                 # stable when nothing changes

    db.connect().execute("INSERT INTO research_tensions (id, project_id, kind, description, status, impact, created_at, updated_at) "
                         "VALUES ('t1',?,'CONTRADICTION','d','open','high',?,?)", (p["id"], db.now(), db.now()))
    db.connect().commit()
    r1 = db.project_research_revision(p["id"])
    assert r1 != r0

    db.connect().execute("DELETE FROM research_tensions WHERE id='t1'")
    db.connect().commit()
    assert db.project_research_revision(p["id"]) != r1                 # deletion moves it too


def test_sources_endpoint_caches_the_skipped_scan_without_changing_its_answer():
    """R2's measured hotspot: 0.45.7's skipped-source scan re-ran the whole $0 research derivation on every poll
    (1.52 s of a 2.58 s endpoint, polled every 3 s). Caching it must be invisible in the OUTPUT — identical
    pool_potential — and must recompute once the project's research state moves."""
    p = db.create_project("Pool", "buying a business with seller financing")
    s = db.upsert_source(platform="youtube", external_id="pool-x1", url="https://www.youtube.com/watch?v=pool-x1",
                         title="Seller financing explained",
                         description="how seller financing works when buying a business")
    db.add_project_sources(p["id"], [s["id"]])
    db.set_source_status(s["id"], "skipped")

    first = api.api_sources(project_id=p["id"], limit=50)
    assert first and first[0]["pool_potential"] is not None
    before = perf.snapshot()["caches"].get("gap_terms", {}).get("miss", 0)

    second = api.api_sources(project_id=p["id"], limit=50)
    assert [r["pool_potential"] for r in second] == [r["pool_potential"] for r in first]   # same answer
    assert perf.snapshot()["caches"]["gap_terms"]["hit"] >= 1                              # and it was reused
    assert perf.snapshot()["caches"]["gap_terms"]["miss"] == before                        # no recompute

    db.connect().execute("INSERT INTO research_tensions (id, project_id, kind, description, status, impact, created_at, updated_at) "
                         "VALUES ('t2',?,'CONTRADICTION','d','open','high',?,?)", (p["id"], db.now(), db.now()))
    db.connect().commit()
    api.api_sources(project_id=p["id"], limit=50)
    assert perf.snapshot()["caches"]["gap_terms"]["miss"] == before + 1                    # research moved → recomputed


def test_view_revision_moves_on_sources_jobs_and_findings_changes():
    """The tick is only safe if its fingerprint moves for everything the Sources view renders. Membership can
    arrive through collections and tags, so `sources` and `jobs` are global on purpose — over-invalidating costs a
    recompute, under-invalidating shows a wrong screen. `notes` carries status counts because approving a finding
    changes the badges on a source row without touching any timestamp."""
    p = db.create_project("View", "brief")
    r0 = db.project_view_revision(p["id"])
    assert set(r0) == {"sources", "jobs", "notes", "research"}
    assert db.project_view_revision(p["id"]) == r0                      # stable when nothing happens

    s = db.upsert_source(platform="youtube", external_id="view-1", url="https://www.youtube.com/watch?v=view-1", title="t")
    assert db.project_view_revision(p["id"])["sources"] != r0["sources"]

    r1 = db.project_view_revision(p["id"])
    db.create_job("reembed", {})
    assert db.project_view_revision(p["id"])["jobs"] != r1["jobs"]

    r2 = db.project_view_revision(p["id"])
    note = db.add_project_note(p["id"], "a finding", citations=[], status="suggested", source_id=s["id"])
    assert db.project_view_revision(p["id"])["notes"] != r2["notes"]

    r3 = db.project_view_revision(p["id"])
    db.set_note_status(note["id"] if isinstance(note, dict) else note, "approved")
    assert db.project_view_revision(p["id"])["notes"] != r3["notes"]    # status change, no timestamp change


def test_tick_answers_did_anything_change_without_building_the_view(client):
    """The whole point: the poll must be able to ask whether anything changed without paying for the answer. The
    happy path is exercised in-process because conftest's session client holds its own DB connection from before
    this module's fixture repointed the data dir; the route itself is checked over HTTP."""
    p = db.create_project("Tick", "brief")
    out = api.api_tick(p["id"])
    assert set(out["rev"]) == {"sources", "jobs", "notes", "research"} and out["active"] == 0

    db.create_job("reembed", {})
    assert api.api_tick(p["id"])["active"] == 1
    assert api.api_tick(p["id"])["rev"]["jobs"] != out["rev"]["jobs"]
    assert perf.stats("tick") is not None                               # the tick times itself like everything else

    assert client.get("/api/projects/does-not-exist/tick",
                      headers={"Authorization": "Bearer t0k"}).status_code == 404


def test_staleness_cache_is_invalidated_by_job_churn():
    """`assess` reports REBUILDING from live job state, so job churn MUST move its key — otherwise a source keeps
    claiming it is rebuilding after its job has finished, which is exactly the kind of stale-staleness bug that
    would make caching here indefensible."""
    p = db.create_project("Stale", "brief")
    s = db.upsert_source(platform="youtube", external_id="stale-1", url="https://www.youtube.com/watch?v=stale-1",
                         title="t", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    api.api_sources(project_id=p["id"], limit=50)
    misses = perf.snapshot()["caches"]["staleness"]["miss"]

    api.api_sources(project_id=p["id"], limit=50)
    assert perf.snapshot()["caches"]["staleness"]["miss"] == misses     # nothing moved → reused

    db.create_job("suggest_findings", {"project_id": p["id"], "source_ids": [s["id"]]})
    api.api_sources(project_id=p["id"], limit=50)
    assert perf.snapshot()["caches"]["staleness"]["miss"] == misses + 1  # a job appeared → recomputed


# ---------------------------------------------------------------- R2 part 3: payload

def test_list_clips_description_but_the_single_source_keeps_it_whole():
    """`description` measured 53% of the Sources payload for a field the list renders as one ellipsised line. The
    list copy is clipped; the drawer and the reader fetch /api/sources/{id} separately and must still get the full
    text, or clipping the list would quietly truncate what the user actually reads."""
    long_desc = "x" * (api.LIST_DESCRIPTION_CHARS * 3)
    p = db.create_project("Clip", "brief")
    s = db.upsert_source(platform="youtube", external_id="clip-1", url="https://www.youtube.com/watch?v=clip-1",
                         title="t", description=long_desc, status="ready")
    db.add_project_sources(p["id"], [s["id"]])

    row = next(r for r in api.api_sources(project_id=p["id"], limit=50) if r["id"] == s["id"])
    assert len(row["description"]) == api.LIST_DESCRIPTION_CHARS + 1 and row["description"].endswith("…")
    assert db.get_source(s["id"])["description"] == long_desc          # untouched at rest
    assert api.api_source(s["id"])["description"] == long_desc         # and whole on the single-source endpoint


def test_short_descriptions_are_left_exactly_alone():
    p = db.create_project("Clip2", "brief")
    s = db.upsert_source(platform="youtube", external_id="clip-2", url="https://www.youtube.com/watch?v=clip-2",
                         title="t", description="short one", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    row = next(r for r in api.api_sources(project_id=p["id"], limit=50) if r["id"] == s["id"])
    assert row["description"] == "short one"


# ---------------------------------------------------------------- account gates (0.46.4)

def test_a_successful_call_clears_the_spend_cap_gate_not_just_billing():
    """The bug Kyle caught: "I don't think that cap is real. I expanded the cap manually." `billing_until` always
    cleared itself on a successful call; `spend_cap_until` was set on SPEND_CAP and cleared NOWHERE, so a usage
    limit raised in the Console could never unblock the app — and because the same stored date parks every job,
    nothing would ever make the call that would prove it lifted."""
    future = db.now() + 30 * 24 * 3600
    db.kv_set("providers:spend_cap_until", str(future))
    db.kv_set("providers:billing_until", str(future))
    assert set(db.clear_account_gates()) == {"providers:spend_cap_until", "providers:billing_until"}
    assert float(db.kv_get("providers:spend_cap_until")) == 0
    assert float(db.kv_get("providers:billing_until")) == 0
    assert db.clear_account_gates() == []                              # idempotent, reports only what was set


def test_recheck_releases_budget_parked_jobs_but_leaves_other_waits_alone():
    """Clearing the belief has to release the jobs parked BY that belief, or the queue stays frozen on a
    `not_before` derived from the same stale date. Nothing else may be disturbed."""
    budget = db.create_job("suggest_findings", {})
    db.claim_job(("suggest_findings",))
    db.requeue_job(budget["id"], delay=30 * 24 * 3600, wait_reason="budget", message="paused: usage limit")

    rate = db.create_job("rank_proposed", {})
    db.claim_job(("rank_proposed",))
    db.requeue_job(rate["id"], delay=600, wait_reason="rate_limit", message="slow down")

    running = db.create_job("discover", {})
    db.claim_job(("discover",))

    assert db.release_budget_waits() == 1
    assert db.get_job(budget["id"])["not_before"] is None               # the budget-parked job is free to run
    assert db.get_job(rate["id"])["not_before"] is not None             # a rate-limit wait is a different thing
    assert db.get_job(running["id"])["status"] == "running"             # running work untouched
    assert db.release_budget_waits() == 0


def test_recheck_endpoint_reports_whether_it_actually_unblocked():
    """The button must never claim success it cannot support: it reports the live `blocked` reason after clearing,
    so a block that is still real (a daily budget, say) still shows."""
    db.kv_set("providers:spend_cap_until", str(db.now() + 86400))
    out = api.api_usage_recheck()
    assert "providers:spend_cap_until" in out["cleared"] and out["blocked"] is None

    db.kv_set("queue_paused", "1")                                      # a different, still-true block
    out2 = api.api_usage_recheck()
    assert out2["cleared"] == [] and out2["blocked"]
    db.kv_set("queue_paused", "0")


def test_recheck_forces_a_fresh_local_probe_not_a_cached_verdict(monkeypatch):
    """Kyle, live: "the probe from 5 minutes ago is not of any use to us now that I literally changed the cap 1
    minute ago." `claude_code.health` caches for HEALTH_TTL, so after the user fixes something the app kept
    reporting the stale answer with no way to ask again — the same cached-belief defect as the account gates, one
    layer up. Re-check must force a new probe, and must not block the request waiting for it."""
    from neurosearch import claude_code as CC
    calls = []
    monkeypatch.setattr(CC, "health", lambda force=False, wait=True: (calls.append((force, wait)) or
                                                                     {"state": "checking", "checking": True}))
    out = api.api_usage_recheck()
    assert calls == [(True, False)]                                     # forced, and non-blocking
    assert out["local_ai"] == {"state": "checking", "rechecking": True}


def test_research_overview_is_cached_on_the_research_revision():
    """Kyle: "I never feel clear on how its benefiting me ... it starts to feel like the old version of the app was
    faster or more useful." Measured on his live project: the Research overview did not return in 250 s and
    saturated the server while it ran, because the areas pass scales with the Claim pile that automatic extraction
    keeps growing. It is now computed once per research revision instead of once per request — the same answer,
    just not rebuilt for every look."""
    from neurosearch import research_view
    p = db.create_project("Research", "buying a business")
    first = research_view.overview(p["id"])
    misses = perf.snapshot()["caches"]["research_overview"]["miss"]

    second = research_view.overview(p["id"])
    assert second == first                                              # identical answer, not an approximation
    assert perf.snapshot()["caches"]["research_overview"]["miss"] == misses
    assert perf.snapshot()["caches"]["research_overview"]["hit"] >= 1

    db.connect().execute("INSERT INTO research_tensions (id, project_id, kind, description, status, impact, created_at, updated_at) "
                         "VALUES ('rt1',?,'CONTRADICTION','d','open','high',?,?)", (p["id"], db.now(), db.now()))
    db.connect().commit()
    research_view.overview(p["id"])
    assert perf.snapshot()["caches"]["research_overview"]["miss"] == misses + 1   # research moved → recomputed
