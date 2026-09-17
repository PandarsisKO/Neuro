"""S70 — the write-lock hold is measured (P0 instrumentation, docs/SPEED-AUDIT-2026-09-17.md).

The audit saw the consequences of long write transactions (`database is locked`, failed heartbeats, a hanging
"New chat") but had no number for the hold itself. `db.tx()` / `db.batch()` now record every write transaction's
hold on the R0 ledger as `db:write_hold` and warn, naming the caller, past WRITE_HOLD_WARN_S. A read-only
transaction records nothing (it never took the writer).
"""
from __future__ import annotations

import logging

from neurosearch import db, perf


def _samples():
    return perf.stats("db:write_hold")


def test_a_write_transaction_is_recorded_and_a_read_is_not(monkeypatch):
    perf._samples["db:write_hold"].clear()                      # the ledger keeps a bounded window; count from empty
    before = 0
    with db.tx() as conn:
        conn.execute("SELECT 1").fetchall()
    assert (_samples() or {"n": 0})["n"] == before, "a read-only tx must not count as a writer hold"
    db.kv_set("s70:probe", "1")
    assert (_samples() or {"n": 0})["n"] == before + 1
    with db.batch():
        db.kv_set("s70:probe", "2")
        db.kv_set("s70:probe", "3")               # nested tx() inside a batch: one hold, not three
    assert (_samples() or {"n": 0})["n"] == before + 2


def test_a_long_hold_names_its_caller(monkeypatch, caplog):
    monkeypatch.setattr(db, "WRITE_HOLD_WARN_S", 0.0)
    with caplog.at_level(logging.WARNING, logger="neurosearch.db"):
        db.kv_set("s70:probe", "4")
    msgs = [r.getMessage() for r in caplog.records if "write lock held" in r.getMessage()]
    assert msgs and "test_s70" in msgs[-1], msgs                  # the nearest frame outside db.py: this test


def test_the_worst_hold_survives_the_sample_window(monkeypatch):
    perf._samples["s70:peak"].clear(); perf._peak.pop("s70:peak", None)
    perf.record("s70:peak", 12.1)
    for _ in range(perf.SAMPLES + 5):
        perf.record("s70:peak", 0.001)
    st = perf.stats("s70:peak")
    assert st["max"] < 1 and st["peak"] == 12.1 and st["peak_at"] > 0
