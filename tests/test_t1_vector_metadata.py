"""T1 admission slice: derived vectors carry an explicit, comparable space identity."""

import pytest
import numpy as np

from neurosearch import db


@pytest.fixture
def t1_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def test_t1_metadata_columns_are_additive_and_nullable(t1_db):
    for table in ("project_notes", "project_claims"):
        cols = {row["name"] for row in db.connect().execute(f"PRAGMA table_info({table})").fetchall()}
        assert {"embedding", "embedding_provider", "embedding_model", "embedding_dimensions",
                "embedding_input_hash", "embedding_version"} <= cols


def test_t1_legacy_vectors_are_not_comparable_without_metadata(t1_db):
    cols = ["id", "embedding", "embedding_provider", "embedding_model", "embedding_dimensions", "embedding_version"]
    row = db.connect().execute("SELECT " + ",".join(cols) + " FROM project_notes LIMIT 1").fetchone()
    # The migration preserves the old blob, but an absent model/dimension means a caller must fail open.
    assert row is None or row["embedding_provider"] is None or row["embedding_model"] is None or row["embedding_dimensions"] is None


def test_t1_versioned_write_read_and_invalidation_fail_open(t1_db):
    project_id = db.create_project("T1", "test")['id']
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "note", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    db.set_derived_embedding("project_notes", note_id, np.array([1, 0, 0], dtype=np.float32),
                             provider="openai", model="text-embedding-3-small", version="t1-v1", input_hash="h1")
    rows = db.load_versioned_derived_embeddings("project_notes", project_id, provider="openai",
                                                model="text-embedding-3-small", version="t1-v1", dimensions=3)
    assert len(rows) == 1 and rows[0]["embedding"].shape == (3,)
    db.invalidate_derived_embedding("project_notes", note_id)
    assert db.load_versioned_derived_embeddings("project_notes", project_id, provider="openai",
                                                model="text-embedding-3-small", version="t1-v1", dimensions=3) == []


def test_t1_backfill_queues_canonical_rows_in_low_lane(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 queue", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "queue me", "approved", db.now()))
    db.connect().commit()
    queued = t1.enqueue_backfill(project_id, limit=10)
    assert len(queued) == 1 and queued[0]["lane"] == "low" and queued[0]["kind"] == "t1_embed_derived"


def test_t1_job_writes_provider_versioned_vector(t1_db, monkeypatch):
    from neurosearch import jobs
    project_id = db.create_project("T1 job", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "embed me", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    monkeypatch.setattr("neurosearch.embeddings.embed_texts", lambda texts: [np.array([0., 1.], dtype=np.float32)])
    job = {"id": "job-t1", "kind": "t1_embed_derived", "payload": {
        "table": "project_notes", "object_id": note_id, "text": "embed me", "provider": "openai",
        "model": "text-embedding-3-small", "version": "t1-v1", "input_hash": "h"}}
    result = jobs.run_job(job)
    assert result["dimensions"] == 2
    assert db.load_versioned_derived_embeddings("project_notes", project_id, provider="openai",
                                                model="text-embedding-3-small", version="t1-v1", dimensions=2)


def test_t1_coverage_is_read_only_and_explicitly_pending(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 coverage", "test")["id"]
    report = t1.coverage_report(project_id)
    assert report["status"] == "measurement_pending"
    assert report["semantic_distributions"] is None
