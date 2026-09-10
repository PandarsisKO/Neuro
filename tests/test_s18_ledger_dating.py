"""S18 — a usage row is dated when the money was spent (0.62.3). (Sorts after test_s17.)

Reconciling Kyle's month against his Anthropic Console, 2026-09-10, produced two anomalies that looked like
different bugs and were one:

* his Console billed **$149.25 on Sep 9** and the app recorded **$19.75** for that day;
* the next day the app recorded **$30.23** against a Console figure of **$17.93** — the app claiming MORE than he
  was charged, which no amount of hidden spend can explain.

The cause: **1,284 batch rows worth $23.18 were written between 15:49 and 16:12 on Sep 10 — 647 of them inside a
single minute** — for results Anthropic had computed, and charged for, the day before. `usage.record` stamps
`time.time()`, so a Message Batch is dated when the app *collects* it, which can be a day after it was billed. The
day the money was spent read low; the day it was collected read high.

And it had teeth. `usage:rate_blocked_until` was set that afternoon with `rate_at_block` $17.43 against a $6/hour
ceiling (peak rolling hour $23.30), holding paid background work because of money that was already gone. **A
ceiling on spend RATE has to be computed from when spending happened**, or recovering old results looks exactly
like a runaway.

So `record`/`record_anthropic` take an explicit `ts`, `batch_items.result_at` records when a provider result
actually arrived, and a row dated outside the rate window never touches the rate gate — it still counts towards
every TOTAL, which is where late news belongs.
"""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_ledger_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, usage  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _rows():
    return [dict(r) for r in db.connect().execute("SELECT ts, cost, transport FROM usage ORDER BY ts")]


# ------------------------------------------------------------------ the date on the row

def test_a_row_defaults_to_now(fresh):
    usage.record("findings", "claude-sonnet-5", input_tokens=1000, output_tokens=100)
    assert abs(_rows()[0]["ts"] - time.time()) < 5


def test_a_row_can_be_dated_when_it_was_incurred(fresh):
    yesterday = time.time() - 26 * 3600
    usage.record("findings", "claude-sonnet-5", input_tokens=1000, output_tokens=100, transport="batch", ts=yesterday)
    assert abs(_rows()[0]["ts"] - yesterday) < 1


def test_late_news_still_counts_towards_the_totals(fresh):
    """The money was spent; the month must show it. Only the RATE window is protected."""
    yesterday = time.time() - 26 * 3600
    c = usage.record("findings", "claude-sonnet-5", input_tokens=500_000, output_tokens=10_000,
                     transport="batch", ts=yesterday)
    assert c > 0
    total = db.connect().execute("SELECT SUM(cost) c FROM usage").fetchone()["c"]
    assert abs(total - c) < 1e-9


# ------------------------------------------------------------------ the rate ceiling

def test_a_backdated_row_cannot_trip_the_rate_ceiling(fresh, monkeypatch):
    """Recovering 410 stranded batches booked $23.18 in 23 minutes and held Kyle's queue over money already gone."""
    monkeypatch.setattr(usage, "SPEND_RATE_CEILING", 1.0)
    yesterday = time.time() - 26 * 3600
    for _ in range(6):
        usage.record("findings", "claude-sonnet-5", input_tokens=500_000, output_tokens=20_000,
                     transport="batch", ts=yesterday)
    assert db.kv_get("usage:rate_blocked_until") in (None, "0", 0)


def test_spending_now_still_trips_it(fresh, monkeypatch):
    """The guard must not disarm the ceiling — a real runaway is exactly what it is for."""
    monkeypatch.setattr(usage, "SPEND_RATE_CEILING", 1.0)
    for _ in range(6):
        usage.record("findings", "claude-sonnet-5", input_tokens=500_000, output_tokens=20_000)
    until = db.kv_get("usage:rate_blocked_until")
    assert until and float(until) > time.time()


def test_the_window_is_what_decides_late(fresh):
    assert usage.late_booking(None) is False
    assert usage.late_booking(time.time() - 60) is False          # inside the rolling hour: this is spending now
    assert usage.late_booking(time.time() - 7200) is True


# ------------------------------------------------------------------ what the report admits

def test_a_provider_result_records_when_it_arrived(fresh):
    p = db.create_project("b", brief="x")
    db.create_job("suggest_findings_batch", {"project_id": p["id"]})
    jid = db.list_jobs(limit=1)[0]["id"]
    with db.tx() as conn:
        conn.execute("INSERT INTO batch_items (job_id, cohort_no, custom_id, task, project_id, source_id, "
                     "window_index, windows, params, batch_id, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (jid, 1, "c1", "findings.extract", p["id"], "s1", 0, 1, "{}", "bx", "submitted", 1.0, 1.0))
    t0 = time.time()
    db.batch_item_result("bx", "c1", "succeeded", raw={"model": "claude-sonnet-5"})
    row = db.connect().execute("SELECT result_at, updated_at FROM batch_items WHERE custom_id='c1'").fetchone()
    assert row["result_at"] and abs(row["result_at"] - t0) < 5
    # the collection moment survives a later status change — updated_at does not
    db.batch_item_result("bx", "c1", "materialized", raw={"model": "claude-sonnet-5"})
    row2 = db.connect().execute("SELECT result_at FROM batch_items WHERE custom_id='c1'").fetchone()
    assert abs(row2["result_at"] - row["result_at"]) < 1e-6


def test_reconcile_says_how_much_of_the_ledger_is_undated(fresh):
    r = usage.reconcile(days=3)
    bd = r["batch_dating"]
    assert "results_without_a_date" in bd and "batch_dollars" in bd
    assert "collected" in bd["note"]


def test_reconcile_names_a_window_that_rests_on_two_bases(fresh):
    """On 2026-09-10 the same day held $3.48 of local calls priced as charged and $96.16 booked as avoided, because
    `local_is_free` flipped part-way through it — and the report showed one number."""
    usage.record("findings", "claude-sonnet-5", cost=3.48, transport="local", saved=0.0)
    usage.record("findings", "claude-sonnet-5", cost=0.0, transport="local", saved=96.16)
    mb = usage.reconcile(days=3)["today"].get("mixed_basis")
    assert mb and mb["local_charged"] == 1 and mb["local_free"] == 1
    assert mb["charged_dollars"] == 3.48 and "two different bases" in mb["note"]
