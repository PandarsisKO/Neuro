"""L3 — the acceleration dialog (0.45.0): the local provider is slow on purpose, so buying speed is an EXPLICIT purchase.
`jobs.backlog` reports what waits on Claude Code, the time it needs there and what the same work costs on the API (the same
per-source estimate the stale triage quotes); `jobs.accelerate` moves exactly the chosen jobs onto the API pool by marking
them `api_requested` — slowness alone never spends. (Sorts after test_n9.)"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_accel_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, db, fake_ai, ingest, jobs, staleness, usage  # noqa: E402
from neurosearch import claude_code as CC  # noqa: E402
from neurosearch.config import settings  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "index.html"
TEXT = "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setenv(CC.FAKE_ENV, "ready")
    CC._state["health"] = {"state": "ready", "checked_at": 1e12}
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    CC._state["health"] = None
    db._local.conn = None


def _queued(pid, n=4):
    ids = []
    for i in range(n):
        r = ingest.ingest_text(f"Talk {i}", TEXT.replace("cloudflare", f"provider{i}"), project_id=pid)
        ids.append(r["source_id"])
        db.create_job("suggest_findings", {"project_id": pid, "source_ids": [r["source_id"]]})
    return ids


def test_backlog_reports_time_locally_and_dollars_on_the_api():
    p = db.create_project("Accel", "hosting")
    assert jobs.backlog(p["id"])["local_queued"] == 0 and jobs.backlog(p["id"])["line"] == "nothing waiting"
    ids = _queued(p["id"], 4)
    b = jobs.backlog(p["id"])
    assert b["local_queued"] == 4 and b["api_queued"] == 0 and b["local_ready"] is True
    assert b["local_minutes"] == round(b["windows"] * staleness.LOCAL_MINUTES_PER_WINDOW) and b["local_eta"]
    # the dollar figure is the SAME per-source estimate the stale triage quotes — the two surfaces can never disagree
    assert b["api_cost"] == round(sum(usage.estimate_source_findings(s, usage.observed_rate_per_minute()) for s in ids), 2)
    assert "waiting on Claude Code" in b["line"] and "on the API ≈ $" in b["line"]
    assert b["choices"] == [4] and all(j["policy"] == "local_preferred" for j in b["jobs"])
    # a deep read counts as more work locally (it re-windows), and jobs of another project are not in this backlog
    other = db.create_project("Other", "x"); _queued(other["id"], 2)
    assert jobs.backlog(p["id"])["local_queued"] == 4 and jobs.backlog()["local_queued"] == 6
    db.create_job("suggest_findings", {"project_id": p["id"], "source_ids": [ids[0]], "depth": "deep"}, lane="slow")
    deep = next(j for j in jobs.backlog(p["id"])["jobs"] if j["depth"] == "deep")
    assert deep["windows"] >= 3 * next(j["windows"] for j in jobs.backlog(p["id"])["jobs"] if j["depth"] is None)


def test_acceleration_is_an_explicit_purchase_of_exactly_what_was_chosen():
    p = db.create_project("Accel2", "hosting")
    ids = _queued(p["id"], 4)
    # value order: the source that matters most goes first
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (p["id"], ids[3])); db.connect().commit()
    r = jobs.accelerate(p["id"], n=1, order="value")
    assert r["moved"] == 1 and r["remaining"] == 3
    moved = db.get_job(r["job_ids"][0])
    assert moved["execution_policy"] == "api_requested" and moved["payload"]["source_ids"] == [ids[3]]
    # only the API pool claims it now; the local pool sees the three that were not bought
    assert db.claim_job(jobs.ANALYSIS_KINDS, worker_id="api", policies=jobs.API_POLICIES)["id"] == moved["id"]
    b = jobs.backlog(p["id"])
    assert b["local_queued"] == 3 and b["api_queued"] == 0            # the bought one is running on the API worker now
    # nothing else moved, and the estimate returned is for what was actually moved
    assert all(db.get_job(j["id"])["execution_policy"] == "local_preferred" for j in b["jobs"])
    assert r["api_cost"] == round(usage.estimate_source_findings(ids[3], usage.observed_rate_per_minute()), 2)
    # asking for more than there is moves what there is; a bad order is refused; the API surfaces mirror the engine
    r2 = api.api_accelerate(p["id"], api.AccelerateIn(n=99))
    assert r2["moved"] == 3 and jobs.backlog(p["id"])["local_queued"] == 0
    with pytest.raises(Exception):
        api.api_accelerate(p["id"], api.AccelerateIn(n=1, order="cheapest"))
    with pytest.raises(Exception):
        api.api_ai_backlog("no-such-project")


def test_a_cloud_profile_never_offers_the_dialog(monkeypatch):
    p = db.create_project("Accel3", "hosting")
    _queued(p["id"], 2)
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    b = jobs.backlog(p["id"])
    assert b["local_ready"] is False and b["local_minutes"] is None and "waiting on Claude Code" not in b["line"]
    html = UI.read_text()
    assert 'id="backlog"' in html and "loadBacklog()" in html and "accelerate(" in html
    assert "b.local_ready" in html, "the banner must hide itself when the local provider is not the one doing the work"


def test_a_button_that_spends_money_says_so_on_its_face():
    """Kyle, live 2026-09-09: "I am not sure what the buttons on this progress bar do or what the risks/costs are."

    The buttons were labelled "next 10" beside a banner reading $0, with the price hidden in a hover title. The
    per-button estimate is computed in the browser from the SAME per-job numbers `accelerate` charges against, so
    this test gates the two things that make that possible: every job carries what the estimate needs, and the
    totals it divides by are present. If a field here is dropped, the buttons silently lose their price."""
    p = db.create_project("Accel4", "hosting")
    _queued(p["id"], 4)
    b = jobs.backlog(p["id"])
    for j in b["jobs"]:
        assert j["api_cost"] >= 0 and j["windows"] >= 1 and "value" in j     # cost, time share, and the ⭐ ordering
    assert b["windows"] >= 4 and b["local_minutes"] is not None               # the denominators of "saves ~N min"
    # the per-button sum can never exceed the whole-set figure the banner quotes
    assert round(sum(j["api_cost"] for j in b["jobs"]), 2) == b["api_cost"]

    html = UI.read_text()
    assert "function accelEstimate" in html and "accelMins(" in html
    for must in ("saves ~", "buying time, not a different answer", "cannot be undone", "at $0"):
        assert must in html, f"the purchase must state {must!r} before it is made"
    assert "state.usage" in html, "the confirm must be able to quote the real budget, not a guess"
