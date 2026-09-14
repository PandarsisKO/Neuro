"""Foundation R8: measured SQLite indexes, bounded connection pragmas and scheduled statistics."""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest

from neurosearch import db
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def test_every_connection_gets_bounded_storage_pragmas(fresh):
    conn = db.connect()
    assert conn.execute("PRAGMA cache_size").fetchone()[0] == -db.SQLITE_CACHE_KIB
    assert conn.execute("PRAGMA temp_store").fetchone()[0] == 2
    # The value is an explicit policy: 0 after the 2026-09-12 FTS5 sleep/wake investigation, rather than an
    # accidental platform default. Keep the test coupled to the configured value so a future change is deliberate.
    assert conn.execute("PRAGMA mmap_size").fetchone()[0] == db.SQLITE_MMAP_BYTES


def test_measured_indexes_exist_and_cover_their_leading_predicates(fresh):
    conn = db.connect()
    expected = {
        "ix_project_notes_project_status_source": "project_notes",
        "ix_messages_conversation": "messages",
        "ix_usage_kind_source": "usage",
        "ix_jobs_kind_status": "jobs",
    }
    rows = conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name IN (?,?,?,?)",
        tuple(expected),
    ).fetchall()
    assert {row["name"]: row["tbl_name"] for row in rows} == expected

    plans = {
        "ix_project_notes_project_status_source": conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM project_notes WHERE project_id=? AND status=? AND source_id=?",
            ("p", "approved", "s"),
        ).fetchall(),
        "ix_messages_conversation": conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE conversation_id=?", ("c",)
        ).fetchall(),
        "ix_usage_kind_source": conn.execute(
            "EXPLAIN QUERY PLAN SELECT source_id, SUM(cost) FROM usage WHERE kind=? AND source_id IS NOT NULL GROUP BY source_id",
            ("findings",),
        ).fetchall(),
        "ix_jobs_kind_status": conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM jobs WHERE kind=? AND status=?", ("suggest_findings", "queued")
        ).fetchall(),
    }
    for index, plan in plans.items():
        assert index in " ".join(str(row["detail"]) for row in plan)


def test_analyze_is_durable_and_rate_limited(fresh, monkeypatch):
    clock = iter((1_000_000.0, 1_000_001.0, 1_000_002.0))
    monkeypatch.setattr(db, "now", lambda: next(clock))
    first = db.analyze_if_due()
    assert first["analyzed"] is True and first["stat_rows"] > 0
    assert db.connect().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
    ).fetchone()
    second = db.analyze_if_due()
    assert second["analyzed"] is False and second["why"] == "not due"
