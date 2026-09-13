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
    again = t1.enqueue_backfill(project_id, limit=10)
    assert again[0]["id"] == queued[0]["id"]


def test_t1_job_writes_provider_versioned_vector(t1_db, monkeypatch):
    from neurosearch import jobs
    project_id = db.create_project("T1 job", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "embed me", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    monkeypatch.setattr("neurosearch.embeddings.embed_texts", lambda texts: [np.array([0., 1.], dtype=np.float32)])
    input_hash = __import__("neurosearch.t1", fromlist=["input_hash"]).input_hash("embed me", None, None, None)
    job = {"id": "job-t1", "kind": "t1_embed_derived", "payload": {
        "table": "project_notes", "object_id": note_id, "text": "embed me", "provider": "openai",
        "model": "text-embedding-3-small", "version": "t1-v1", "input_hash": input_hash}}
    result = jobs.run_job(job)
    assert result["dimensions"] == 2
    assert db.load_versioned_derived_embeddings("project_notes", project_id, provider="openai",
                                                model="text-embedding-3-small", version="t1-v1", dimensions=2)


def test_t1_job_skips_when_input_revision_changed(t1_db, monkeypatch):
    from neurosearch import jobs, t1
    project_id = db.create_project("T1 stale", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "new text", "approved", db.now()))
    db.connect().commit(); note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    monkeypatch.setattr("neurosearch.embeddings.embed_texts", lambda texts: (_ for _ in ()).throw(AssertionError("must not embed stale input")))
    old_hash = t1.input_hash("old text", None, None, None)
    result = jobs.run_job({"id": "job-stale", "kind": "t1_embed_derived", "payload": {
        "table": "project_notes", "object_id": note_id, "text": "old text", "provider": "openai",
        "model": "m", "version": "t1-v1", "input_hash": old_hash}})
    assert result == {"skipped": "stale_input"}


def test_t1_coverage_is_read_only_and_explicitly_pending(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 coverage", "test")["id"]
    report = t1.coverage_report(project_id)
    assert report["status"] == "measurement_pending"
    assert report["semantic_distributions"] is None
    assert report["corpus_space"] is None
    assert report["claim_locator_rows"] == 0 and report["finding_locator_rows"] == 0


def test_t1_chunk_space_attestation_measures_and_fails_mixed_space(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 attest", "test")["id"]
    source_id = db.upsert_source(platform="manual", external_id="attest", url="manual://attest", title="attest")['id']
    db.connect().execute("INSERT INTO project_sources (project_id, source_id) VALUES (?,?)", (project_id, source_id))
    db.connect().execute("INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
                         (source_id, 0, 0, 1, "ok", np.array([1., 0.], dtype=np.float32).tobytes()))
    db.connect().execute("INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
                         (source_id, 1, 1, 2, "bad", np.array([1., 0., 0.], dtype=np.float32).tobytes()))
    db.connect().commit()
    att = t1.attest_chunk_space(provider="openai", model="text-embedding-3-small", dimensions=2, preparation_tag="t1-test")
    assert att["count"] == 2 and att["bad_dimensions"] == 1 and not att["verified"]
    assert t1.get_chunk_space_attestation() is None
    db.connect().execute("DELETE FROM chunks WHERE idx=1 AND source_id=?", (source_id,))
    db.connect().commit()
    att = t1.attest_chunk_space(provider="openai", model="text-embedding-3-small", dimensions=2, preparation_tag="t1-test")
    assert att["verified"] and t1.get_chunk_space_attestation()["dimensions"] == 2


def test_t1_measurement_publishes_project_relative_distribution(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 measure", "test")["id"]
    source_id = db.upsert_source(platform="manual", external_id="measure", url="manual://measure", title="measure")['id']
    db.connect().execute("INSERT INTO project_sources (project_id, source_id) VALUES (?,?)", (project_id, source_id))
    db.connect().execute("INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
                         (source_id, 0, 0, 1, "chunk", np.array([1., 0.], dtype=np.float32).tobytes()))
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t1-test")
    db.connect().execute("INSERT INTO project_claims (id, project_id, text, status, created_at, updated_at, embedding_provider, embedding_model, embedding_dimensions, embedding_version, embedding_input_hash, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("c1", project_id, "claim", "accepted", db.now(), db.now(), "openai", "m", 2, t1.VECTOR_VERSION, "h", np.array([1., 0.], dtype=np.float32).tobytes()))
    db.connect().commit()
    report = t1.measure_project(project_id, provider="openai", model="m", dimensions=2)
    assert report["status"] == "measured" and report["claims"]["vector_count"] == 1 and report["claims"]["distribution"]["p50"] == 1.0
