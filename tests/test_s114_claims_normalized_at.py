"""S114 — Claims are counted when the paid step normalized them, not when they were harvested.

Found in the 2026-11-10 cost audit: `claims.extract` rewrites a Claim IN PLACE, so `created_at` stays the harvest
date. cost_value counted Claims by `created_at`, putting the October sweep's spend ($228, 673 calls) in one window and
its Claims in an earlier one: 0 normalized Claims in the window, and $0.259 per Claim tracked against a true ~$0.04.
`normalized_at` is stamped by both normalization paths; legacy rows fall back to `updated_at` and are reported as
approximate."""
from __future__ import annotations

import time

import pytest

from neurosearch import cost_value, db


@pytest.fixture()
def project(monkeypatch):
    db.init_db()
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "subscription")
    p = db.create_project("s114", brief="claims dating")
    with db.tx() as conn:
        conn.execute("DELETE FROM usage")
        conn.execute("DELETE FROM project_claims WHERE project_id=?", (p["id"],))
    yield p["id"]


def _claim(pid, *, normalized, created_ago, norm_ago=None, stamp=True, model="claude-sonnet-5", cid=None):
    now = time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, normalized, model, created_at, updated_at, normalized_at) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (cid or f"c{time.time_ns()}", pid, "a claim with its qualifiers", normalized,
                      model if normalized else None, now - created_ago, now - (norm_ago if norm_ago is not None else created_ago),
                      (now - norm_ago) if (normalized and stamp and norm_ago is not None) else None))


DAY = 86400.0


def test_the_column_exists_and_a_fresh_database_stamps_it():
    db.init_db()
    cols = {r["name"] for r in db.connect().execute("PRAGMA table_info(project_claims)").fetchall()}
    assert "normalized_at" in cols


def test_a_claim_harvested_long_ago_and_normalized_today_counts_today(project):
    for _ in range(3):
        _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=60.0)        # the October pattern
    _claim(project, normalized=0, created_ago=60.0)                                # a fresh $0 candidate
    c = cost_value._claims_counts(time.time() - DAY, project)
    assert c["normalized"] == 3, "counted when the paid step ran, not when the candidate was harvested"
    assert c["tracked"] == 1 and c["harvested"] == 1, "tracked/harvested still follow creation"
    assert c["normalized_approximate"] == 0


def test_cost_per_normalized_claim_uses_the_normalization_window(project):
    with db.tx() as conn:
        conn.execute("INSERT INTO usage (ts, kind, model, cost, project_id, transport, price_model) VALUES (?,?,?,?,?,?,?)",
                     (time.time() - 60, "claims", "claude-sonnet-5", 1.20, project, "interactive", "claude-sonnet-5"))
    for _ in range(30):
        _claim(project, normalized=1, created_ago=15 * DAY, norm_ago=120.0)
    rep = cost_value.unit_costs("today", project)
    row = next(r for r in rep["rows"] if r["unit"] == "normalized_claim")
    assert row["count"] == 30 and row["per_unit"] == pytest.approx(0.04), "not 0 Claims / unavailable"


def test_legacy_rows_fall_back_to_updated_at_and_are_flagged(project):
    _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=60.0, stamp=False)   # normalized_at NULL, updated_at recent
    c = cost_value._claims_counts(time.time() - DAY, project)
    assert c["normalized"] == 1 and c["normalized_approximate"] == 1
    assert any("approximate" in x for x in cost_value.CAVEATS), "the report says the historical window is approximate"


def test_by_model_and_trend_follow_the_normalization_time(project):
    for _ in range(4):
        _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=60.0, model="claude-sonnet-5")
    for _ in range(5):
        _claim(project, normalized=0, created_ago=60.0)
    bm = cost_value.by_model("claim", "today", project)
    counts = {r["model"]: r["count"] for r in bm["rows"]}
    assert counts.get("claude-sonnet-5") == 4 and counts.get("?") == 5
    tr = cost_value.trend("normalized_claim", 3, project)
    assert sum(r.get("count", 0) for r in tr["rows"]) == 4


@pytest.mark.parametrize("unit", ["claim", "normalized_claim"])
def test_legacy_claims_cannot_publish_model_or_daily_cost_verdicts(project, unit):
    _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=60, stamp=False)
    _claim(project, normalized=1, created_ago=10 * DAY, norm_ago=60, model="claude-haiku-4-5")
    with db.tx() as conn:
        for model in ("claude-sonnet-5", "claude-haiku-4-5"):
            conn.execute("INSERT INTO usage (ts, kind, model, cost, project_id, transport, price_model) "
                         "VALUES (?,?,?,?,?,?,?)", (time.time() - DAY, "claims", model, 1.0, project,
                                                    "interactive", model))
    rep = cost_value.by_model(unit, "week", project)
    sonnet = next(r for r in rep["rows"] if r["model"] == "claude-sonnet-5")
    assert sonnet["count"] == 1 and sonnet["cost"] == 1.0
    assert sonnet["normalized_approximate"] == 1
    assert sonnet["per_unit"] is None and sonnet["comparable"] is False
    assert "normalization dates" in sonnet["per_unit_unavailable"]
    assert rep["verdict"] is None and rep["comparable_models"] == 1
    assert all(r["per_unit"] is None for r in cost_value.trend(unit, 7, project)["rows"])
    row = next(r for r in cost_value.unit_costs("week", project)["rows"] if r["unit"] == "normalized_claim")
    assert row["count"] == 2 and row["cost"] == 2.0 and row["per_unit"] is None


def test_legacy_dates_are_scoped_to_project_and_window(project):
    other = db.create_project("legacy elsewhere")["id"]
    _claim(other, normalized=1, created_ago=20 * DAY, norm_ago=60, stamp=False)
    _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=10 * DAY, stamp=False)
    _claim(project, normalized=1, created_ago=20 * DAY, norm_ago=60)
    row = next(r for r in cost_value.unit_costs("today", project)["rows"] if r["unit"] == "normalized_claim")
    assert row["count"] == 1 and row["per_unit"] == 0.0
    assert cost_value.by_model("normalized_claim", "today", project)["rows"][0]["comparable"] is True
    assert cost_value.trend("normalized_claim", 1, project)["rows"][0]["per_unit"] == 0.0
