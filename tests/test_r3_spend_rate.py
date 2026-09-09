"""0.51.0 — the four holes that cost Kyle $5 in ten minutes (live, 2026-09-09).

Not a hypothetical. His own ledger, read from the running app:

    created 20:28:36 → done 20:32:34   2 paid calls, 16 claims
    created 20:34:45 → done 20:39:02   2 paid calls, 16 claims
    created 20:39:11 → done 20:44:28   2 paid calls, 16 claims
    created 20:45:17 → running

A fresh PAID claim pass every five minutes, all day — 32% of a month's spend — from the fast lane added in
0.48.0. Four separate mistakes, one test each:

  1. `FAST_GROUPS` bounded the cost of one pass and nothing bounded passes per hour. The 30-minute debounce was
     skipped whenever six candidates were waiting, which findings made permanently true, so it never engaged.
  2. The fast lane runs on `priority`, and "Pause background" only skipped `slow`/`low` — the control built to
     stop background spend exempted the biggest background spender.
  3. The triage overlap floor of 0.34 qualified every candidate: sixteen rows, sixteen identical reasons.
  4. Budgets cap a TOTAL. Nothing watched the RATE, so parked work released all at once when credits landed and
     everything stayed comfortably inside a $50/day budget while it happened.

(Sorts after test_r2.)"""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_rate_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claims, db, usage  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _job(kind: str, lane: str = "normal", policy: str = "local_preferred") -> str:
    return db.create_job(kind, {"project_id": "p", "n": time.time()}, lane=lane, execution_policy=policy)["id"]


# ---------------------------------------------------------------- 1. the paid pass has a rate limit

def test_the_paid_fast_pass_cannot_run_again_within_its_interval(monkeypatch):
    p = db.create_project("Claims", "brief")
    monkeypatch.setattr(claims, "triage", lambda pid: {"fast": [{"id": "c1"}], "bulk": [], "why": {"c1": ["x"]},
                                                       "considered": 20, "qualified": 1, "share": 0.05})
    monkeypatch.setattr(claims, "unnormalized", lambda pid: [{"id": f"c{i}"} for i in range(30)])

    def fast_jobs():
        return [j for j in db.list_jobs(limit=200) if j["kind"] == "extract_claims" and (j["payload"] or {}).get("claim_ids")]

    claims.maybe_extract(p["id"], "after suggest_findings")
    assert len(fast_jobs()) == 1
    # the count test (n >= CLAIMS_BATCH_MIN) is exactly what used to bypass the debounce — it must not bypass this
    for _ in range(5):
        claims.maybe_extract(p["id"], "after suggest_findings")
    assert len(fast_jobs()) == 1, "a paid pass per findings job is the bug that cost 32% of a month"
    # the free bulk pass is unaffected: it still returns a job every time (deduped to one active pass, as before)
    assert claims.maybe_extract(p["id"], "after suggest_findings") is not None
    # once the first pass has finished AND the interval has passed, one more is allowed — both gates, not either
    first = fast_jobs()[0]["id"]
    db.update_job(first, status="done")
    claims.maybe_extract(p["id"], "after suggest_findings")
    assert len(fast_jobs()) == 1, "the dedupe key freeing is not on its own a licence to spend again"
    db.kv_set(f"claims:last_fast:{p['id']}", str(time.time() - claims.FAST_MIN_INTERVAL_S - 1))
    claims.maybe_extract(p["id"], "after suggest_findings")
    assert len(fast_jobs()) == 2


# ---------------------------------------------------------------- 2. pause covers claim work on any lane

def test_pausing_background_holds_claim_work_whatever_lane_it_runs_on():
    fast = _job("extract_claims", lane="priority", policy="api_requested")   # 0.48.0's paid fast lane
    bulk = _job("extract_claims", lane="slow")
    mine = _job("suggest_findings", lane="normal")
    db.set_background_paused(True)
    claimed = set()
    while True:
        j = db.claim_job(worker_id="w")
        if not j:
            break
        claimed.add(j["id"])
    assert mine in claimed, "the user's own work must keep running"
    assert fast not in claimed, "the paid claim pass is background spend and must be held"
    assert bulk not in claimed
    db.set_background_paused(False)
    assert db.claim_job(worker_id="w") is not None


def test_pausing_stops_a_running_claim_job_too():
    fast = _job("extract_claims", lane="priority", policy="api_requested")
    db.claim_job(worker_id="w")
    r = db.set_background_paused(True)
    assert r["stopped"] >= 1 and db.cancel_requested(fast)


# ---------------------------------------------------------------- 3. triage has to discriminate

def test_a_reason_printed_on_every_row_is_not_a_reason():
    """The floor was 0.34, which every candidate cleared. Raising it is the fix; reporting the share is what makes
    a future regression visible instead of silent."""
    assert claims.TARGET_OVERLAP_FAST > 0.34
    p = db.create_project("Triage", "brief")
    tri = claims.triage(p["id"])
    assert {"considered", "qualified", "share"} <= set(tri), "the share must be reported so 16-of-16 is visible"


# ---------------------------------------------------------------- 4. the spend-RATE ceiling

def test_the_ceiling_watches_the_rate_not_the_total():
    assert usage.rate_gate()["blocked"] is False
    usage.record("claims", "claude-sonnet-4-6", cost=usage.SPEND_RATE_CEILING + 0.01)
    g = usage.rate_gate()
    assert g["blocked"] and g["rate"] > g["ceiling"] and g["until"] > time.time()
    # ... and the daily budget was never the thing that noticed
    ok, _reason, _ = usage.check()
    assert ok, "this is exactly the case a daily total cannot see"


def test_the_ceiling_holds_paid_background_and_nothing_else():
    paid_bg = _job("extract_claims", lane="priority", policy="api_requested")
    bought = _job("suggest_findings", lane="normal", policy="api_requested")
    mine = _job("ingest_source", lane="normal")
    local = _job("suggest_findings", lane="normal", policy="local_preferred")
    usage.record("claims", "claude-sonnet-4-6", cost=usage.SPEND_RATE_CEILING + 1)
    claimed = set()
    while True:
        j = db.claim_job(worker_id="w")
        if not j:
            break
        claimed.add(j["id"])
    assert mine in claimed and local in claimed, "a spending spike must never take away what the user is using"
    assert paid_bg not in claimed and bought not in claimed


def test_the_user_can_say_carry_on_and_it_is_their_call():
    held = _job("extract_claims", lane="priority", policy="api_requested")
    usage.record("claims", "claude-sonnet-4-6", cost=usage.SPEND_RATE_CEILING + 1)
    assert db.claim_job(kinds=("extract_claims",), worker_id="w") is None
    usage.clear_rate_gate()
    assert usage.rate_gate()["blocked"] is False
    assert db.claim_job(kinds=("extract_claims",), worker_id="w")["id"] == held


def test_the_gate_expires_on_its_own():
    _job("extract_claims", lane="priority", policy="api_requested")
    usage.record("claims", "claude-sonnet-4-6", cost=usage.SPEND_RATE_CEILING + 1)
    assert db.claim_job(kinds=("extract_claims",), worker_id="w") is None
    db.kv_set("usage:rate_blocked_until", str(time.time() - 1))
    assert db.claim_job(kinds=("extract_claims",), worker_id="w") is not None


def test_the_endpoints_report_and_release(client):
    from neurosearch import api
    u = api.api_usage()
    assert "rate" in u and set(u["rate"]) >= {"ceiling", "rate", "blocked"}
    usage.record("claims", "claude-sonnet-4-6", cost=usage.SPEND_RATE_CEILING + 1)
    assert api.api_usage()["rate"]["blocked"] is True
    assert api.api_rate_resume()["blocked"] is False
