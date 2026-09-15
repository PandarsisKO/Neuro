"""L-10 (EXECUTION-LADDER.md P0.G, CTO rulings §1.G): db.preflight_autonomous() -- once per autonomous
execution envelope, before any job in it may run: a full PRAGMA integrity_check on the LIVE database (not
quick_check -- the check that actually caught 2026-09-14's real corruption), then a freshly verified backup.
Also covers the integrity_check().ok fix: dangling_origin_note_id must count toward ok, not just be reported."""
from __future__ import annotations

import json

import pytest

from neurosearch import db


@pytest.fixture
def p0_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    db.create_project("p0", "brief")   # so backup()'s table counts have something real to report
    db.connect().commit()
    yield
    db.close_thread_connection()


class _CorruptIntegrityCheck:
    """Wraps the real connection so PRAGMA integrity_check reports corruption while everything else (kv_get/
    kv_set, backup()'s own queries) behaves normally -- a faithful unit test of preflight_autonomous's REFUSAL
    logic without needing to hand-corrupt SQLite's on-disk page format."""
    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a, **kw):
        if "integrity_check" in sql:
            class _Row:
                def fetchone(self_):
                    return ("*** in database main *** Page 3 is never used",)
            return _Row()
        return self._real.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_integrity_check_ok_requires_zero_dangling_origin_notes(p0_db):
    pid = db.create_project("dangling", "brief")["id"]
    n = db.add_project_note(pid, "a finding")
    db.connect().execute("INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, "
                         "freshness_class, origin_note_id, created_at, updated_at) VALUES "
                         "('c1',?,'x','factual','t','accepted','moderate','age_insensitive',?,?,?)",
                         (pid, n["id"], db.now(), db.now()))
    db.connect().execute("DELETE FROM project_notes WHERE id=?", (n["id"],))   # a Claim survives its origin note's deletion by design
    db.connect().commit()

    chk = db.integrity_check()
    assert chk["dangling_origin_note_id"] == 1
    assert chk["ok"] is False, "a dangling origin_note_id must fail ok, not just be counted and ignored"


def test_preflight_refuses_when_the_live_database_is_not_clean(p0_db, monkeypatch):
    real = db.connect()
    monkeypatch.setattr(db, "connect", lambda: _CorruptIntegrityCheck(real))
    with pytest.raises(RuntimeError, match="preflight refused"):
        db.preflight_autonomous("env-bad")
    failure = json.loads(db.kv_get("db:last_preflight_failure"))
    assert failure["envelope_id"] == "env-bad" and failure["ok"] is False


def test_preflight_does_not_permanently_lock_out_a_repaired_database(p0_db, monkeypatch):
    real = db.connect()
    monkeypatch.setattr(db, "connect", lambda: _CorruptIntegrityCheck(real))
    with pytest.raises(RuntimeError):
        db.preflight_autonomous("env-retry")
    monkeypatch.undo()   # database is "repaired" -- back to the real connection
    info = db.preflight_autonomous("env-retry")
    assert info["ok"] is True and info["backup_path"]


def test_preflight_is_idempotent_per_envelope_one_backup_for_n_jobs(p0_db, monkeypatch):
    calls = []
    real_backup = db.backup

    def counted_backup(*a, **kw):
        calls.append(1)
        return real_backup(*a, **kw)

    monkeypatch.setattr(db, "backup", counted_backup)
    results = [db.preflight_autonomous("env-shared") for _ in range(5)]   # 5 "jobs" in one envelope
    assert len(calls) == 1, "backup() must run once per envelope, not once per job"
    assert all(r == results[0] for r in results)
    assert results[0]["ok"] is True
