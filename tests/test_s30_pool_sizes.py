"""S30 — a thread count is not a spend control (0.63.13). (Sorts after test_s29.)

Kyle: *"what other artificial limits have we been imposing on ourselves? for example is 2 claude code at a time a
real limit?"*

Measured before answering. His `.env` carries `NEUROSEARCH_LOCAL_AI_WORKERS=2`, and over the two days to
2026-09-11 the local transport recorded **1,065 calls, $3.86 billed and $313.58 booked as avoided** — his CLI is on
the subscription, so local concurrency is free in dollars. Peak concurrency actually reached across the last 500
completed findings jobs: **3** (2 local + 1 API).

That 1 is the interesting number. `start_workers` created the API analysis pool as a single hard-coded thread with
no reason recorded, and `_pool_shape` then reported `api_workers: 1` — truthfully reporting a limit nobody had
chosen. **385 of his findings jobs ran `api_requested`**, which is what pressing Accelerate does: the work he paid
to speed up ran one job at a time.

Concurrency is not the instrument for cost. `usage.SPEND_RATE_CEILING` ($/rolling hour), the daily and weekly
budgets and the account gates all bound spend, they all still hold, and each says what it means.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pool_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, jobs  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_the_api_pool_size_is_a_setting_not_a_constant(monkeypatch):
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "api_ai_workers", 4)
    assert jobs._pool_shape(0, 0)["api_workers"] == 4
    monkeypatch.setattr(settings, "api_ai_workers", 1)
    assert jobs._pool_shape(0, 0)["api_workers"] == 1


def test_it_defaults_above_one(monkeypatch):
    """The default is the decision: one thread made purchased speed serial."""
    assert settings.api_ai_workers >= 2


def test_start_workers_actually_starts_that_many(fresh, monkeypatch):
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "workers", 1)
    monkeypatch.setattr(settings, "local_ai_workers", 2)
    monkeypatch.setattr(settings, "api_ai_workers", 3)
    try:
        jobs.start_workers()
        names = [t.name for t in jobs._threads]
        assert len([n for n in names if n.startswith("ns-worker-api-ai")]) == 3
        assert len([n for n in names if n.startswith("ns-worker-local-ai")]) == 2
    finally:
        jobs.stop_workers()


def test_a_zero_or_negative_setting_still_leaves_one_worker(fresh, monkeypatch):
    """A config typo must not silently switch off the pool that spends money on purpose."""
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "workers", 1)
    monkeypatch.setattr(settings, "api_ai_workers", 0)
    try:
        jobs.start_workers()
        assert len([t for t in jobs._threads if t.name.startswith("ns-worker-api-ai")]) == 1
    finally:
        jobs.stop_workers()


def test_the_cloud_profile_has_no_split_pools(monkeypatch):
    """Without the local profile there is no local/API partition to report."""
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    shape = jobs._pool_shape(5, 0)
    assert shape["local_workers"] == 0 and shape["api_workers"] == 0


def test_spend_is_still_bounded_by_the_instruments_that_mean_spend(fresh):
    """The point of the change: raising concurrency must not raise any ceiling. These are the ceilings."""
    from neurosearch import usage
    assert usage.rate_ceiling() > 0                      # $/rolling hour, settable
    assert set(db.RATE_HELD_POLICIES) == {"api_requested", "api_only"}     # exactly the paid pool is held
    limits = usage.totals()
    for k in ("daily_budget", "weekly_budget", "monthly_budget"):
        assert k in limits, k                                               # each a number the user can set
