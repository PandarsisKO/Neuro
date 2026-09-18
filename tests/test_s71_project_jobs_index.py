"""S71 — a project's job list comes from indexed generated columns, not a scan (R8, narrow, 2026-09-17).

`api_project_jobs` decoded every active job app-wide plus the 400 most recent to keep the project's rows in Python —
measured 233–586 ms from the browser and 236 ms on a copy of the 79k-row live table, on every poll tick that saw a
job change. `jobs.project_id` / `jobs.source_id` are VIRTUAL generated columns over the payload (they cannot drift;
`ALTER TABLE` can add them to an existing database) with indexes; `db.list_project_jobs` runs two index-ordered
queries and merges (26 ms on the same copy — one `OR` query measured 205 ms because SQLite re-sorts the union).
"""
from __future__ import annotations

import json

import pytest

from neurosearch import api, db
from neurosearch.config import settings


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_generated_columns_track_the_payload_and_survive_a_second_init(fresh):
    j = db.create_job("suggest_findings", {"project_id": "p1", "source_ids": ["s1"]})
    row = db.connect().execute("SELECT project_id, source_id FROM jobs WHERE id=?", (j["id"],)).fetchone()
    assert row["project_id"] == "p1" and row["source_id"] is None
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps({"project_id": "p2", "source_id": "s9"}), j["id"]))
    row = db.connect().execute("SELECT project_id, source_id FROM jobs WHERE id=?", (j["id"],)).fetchone()
    assert row["project_id"] == "p2" and row["source_id"] == "s9", "a generated column can never drift from its payload"
    db.init_db()                                                        # idempotent: table_xinfo sees the columns
    names = {r["name"] for r in db.connect().execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='jobs'")}
    assert {"ix_jobs_project_created", "ix_jobs_kind_source_created"} <= names


def test_an_existing_database_without_the_columns_gets_them_on_init(fresh, tmp_path):
    """The live database predates the columns: init_db must add them to a table that already has rows."""
    p = tmp_path / "old.db"
    old = __import__("sqlite3").connect(str(p))
    old.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, kind TEXT, payload TEXT, status TEXT, created_at REAL)")
    old.execute("INSERT INTO jobs VALUES ('a','suggest_findings','{\"project_id\":\"p1\"}','done',1.0)")
    old.commit(); old.close()
    c = __import__("sqlite3").connect(str(p))
    db._add_job_payload_columns(c)
    assert c.execute("SELECT project_id FROM jobs WHERE id='a'").fetchone()[0] == "p1"
    db._add_job_payload_columns(c)                                     # and again, harmlessly
    c.close()


def test_project_jobs_membership_and_order_are_unchanged(fresh):
    pid = db.create_project("s71", brief="b")["id"]
    other = db.create_project("other", brief="b")["id"]
    s = db.upsert_source(platform="manual", external_id="s71", url="manual://s71", title="t")
    db.add_project_sources(pid, [s["id"]])
    mine = db.create_job("suggest_findings", {"project_id": pid, "source_ids": [s["id"]]})
    ing = db.create_job("ingest_source", {"source_id": s["id"]})                      # no project_id in the payload
    theirs = db.create_job("suggest_findings", {"project_id": other, "source_ids": []})
    foreign_ing = db.create_job("ingest_source", {"source_id": "nobody"})
    db.finish_job(mine["id"], None, "done")
    rows = api.api_project_jobs(pid, limit=30)
    ids = [r["id"] for r in rows]
    assert set(ids) == {mine["id"], ing["id"]}, ids
    assert ids == [ing["id"], mine["id"]], "newest first, active and terminal alike"
    assert theirs["id"] not in ids and foreign_ing["id"] not in ids


def test_the_list_never_scans_the_whole_table(fresh, monkeypatch):
    pid = db.create_project("s71", brief="b")["id"]
    calls = []
    real = db.list_jobs
    monkeypatch.setattr(db, "list_jobs", lambda *a, **k: (calls.append(k), real(*a, **k))[1])
    api.api_project_jobs(pid, limit=30)
    assert not calls, "api_project_jobs must not fall back to list_jobs (the app-wide scan)"
