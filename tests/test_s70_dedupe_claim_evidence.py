"""S70: cleanup for the pre-2026-09-14 duplicate-citation guard gap in claims.add_evidence. integrity_check()
has been reporting duplicate_claim_evidence > 0 for hours on Kyle's live database with nothing in the codebase
ever actually clearing it -- the guard (already fixed at the source) stops NEW duplicates, but never touches
whatever duplicate rows already existed. db._dedupe_claim_evidence(conn), wired into init_db() right after the
other startup backfills, is the actual cleanup: keeps the oldest (lowest id) row per (claim_id, source_id,
source_revision, locator, relation) group and deletes the rest, once per app start, idempotent.

Run: pytest -q tests/test_s70_dedupe_claim_evidence.py
"""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402

from neurosearch import db  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Same pattern as test_core.py's isolated_db -- a private database, never Kyle's live one."""
    from neurosearch.config import settings
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield data
    try:
        db.connect().close()
    except Exception:  # noqa: BLE001
        pass
    db._local.conn = None


def _seed(conn, n):
    """One project, one claim, one source -- everything claim_evidence's foreign keys require."""
    conn.execute("INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'p', 0, 0)", ("proj1",))
    conn.execute(
        "INSERT INTO project_claims (id, project_id, text, created_at, updated_at) VALUES (?, 'proj1', 'a claim', 0, 0)",
        ("claim1",))
    conn.execute(
        "INSERT INTO sources (id, platform, url, status, created_at, updated_at) VALUES (?, 'web', 'https://x', 'ready', 0, 0)",
        ("src1",))
    conn.commit()


def test_exact_duplicates_are_reduced_to_one_kept_row(isolated_db):
    conn = db.connect()
    _seed(conn, 1)
    # three exact duplicates on (claim_id, source_id, source_revision, locator, relation) -- the same group
    # integrity_check()'s own query groups by. Different excerpt/created_at so we can tell which one survives.
    for i, created in enumerate([100.0, 200.0, 300.0]):
        conn.execute(
            "INSERT INTO claim_evidence (claim_id, source_id, source_revision, locator, relation, excerpt, created_at) "
            "VALUES ('claim1', 'src1', 'rev1', '§1', 'SUPPORTS', ?, ?)", (f"copy {i}", created))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 3

    db._dedupe_claim_evidence(conn)

    rows = conn.execute("SELECT id, excerpt FROM claim_evidence ORDER BY id").fetchall()
    assert len(rows) == 1, "exactly one row should survive a 3-way duplicate group"
    assert rows[0]["excerpt"] == "copy 0", "the OLDEST (lowest id) row must be the one kept, not an arbitrary one"


def test_rows_that_differ_in_any_dedupe_key_field_are_left_alone(isolated_db):
    conn = db.connect()
    _seed(conn, 1)
    rows_in = [
        ("claim1", "src1", "rev1", "§1", "SUPPORTS"),
        ("claim1", "src1", "rev1", "§2", "SUPPORTS"),      # different locator
        ("claim1", "src1", "rev1", "§1", "CONTRADICTS"),   # different relation
        ("claim1", "src1", "rev2", "§1", "SUPPORTS"),      # different source_revision
    ]
    for claim_id, source_id, rev, locator, relation in rows_in:
        conn.execute(
            "INSERT INTO claim_evidence (claim_id, source_id, source_revision, locator, relation, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0)", (claim_id, source_id, rev, locator, relation))
    conn.commit()

    db._dedupe_claim_evidence(conn)

    assert conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == len(rows_in), \
        "four genuinely distinct rows must all survive -- this is not a blunt dedupe on claim_id/source_id alone"


def test_running_it_twice_is_a_no_op_the_second_time(isolated_db):
    conn = db.connect()
    _seed(conn, 1)
    for created in (1.0, 2.0):
        conn.execute(
            "INSERT INTO claim_evidence (claim_id, source_id, source_revision, locator, relation, created_at) "
            "VALUES ('claim1', 'src1', 'rev1', '§1', 'SUPPORTS', ?)", (created,))
    conn.commit()

    db._dedupe_claim_evidence(conn)
    after_first = conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0]
    assert after_first == 1

    db._dedupe_claim_evidence(conn)   # idempotent: nothing left to delete
    after_second = conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0]
    assert after_second == 1


def test_integrity_check_reports_zero_duplicates_after_the_cleanup_runs_via_init_db(isolated_db):
    """The real-world path: init_db() itself (called on every app start) must leave the database clean, not just
    the private helper function in isolation."""
    conn = db.connect()
    _seed(conn, 1)
    for created in (1.0, 2.0, 3.0):
        conn.execute(
            "INSERT INTO claim_evidence (claim_id, source_id, source_revision, locator, relation, created_at) "
            "VALUES ('claim1', 'src1', 'rev1', '§1', 'SUPPORTS', ?)", (created,))
    conn.commit()
    assert db.integrity_check()["duplicate_claim_evidence"] == 1   # one GROUP has duplicates (3 rows in it), not 3

    db.init_db()   # the actual startup path -- must include the dedupe, not just have the helper exist unwired

    chk = db.integrity_check()
    assert chk["duplicate_claim_evidence"] == 0
    assert conn.execute("SELECT COUNT(*) FROM claim_evidence").fetchone()[0] == 1
