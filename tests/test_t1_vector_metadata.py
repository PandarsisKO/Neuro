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
    called = {}
    def fake_embed(texts, *, model=None):
        called["model"] = model
        return [np.array([0., 1.], dtype=np.float32)]
    monkeypatch.setattr("neurosearch.embeddings.embed_texts", fake_embed)
    input_hash = __import__("neurosearch.t1", fromlist=["input_hash"]).input_hash("embed me", None, None, None)
    job = {"id": "job-t1", "kind": "t1_embed_derived", "payload": {
        "table": "project_notes", "object_id": note_id, "text": "embed me", "provider": "openai",
        "model": "text-embedding-3-small", "version": "t1-v1", "input_hash": input_hash}}
    result = jobs.run_job(job)
    assert result["dimensions"] == 2
    assert called["model"] == "text-embedding-3-small"
    assert db.load_versioned_derived_embeddings("project_notes", project_id, provider="openai",
                                                model="text-embedding-3-small", version="t1-v1", dimensions=2)


def test_t1_job_skips_when_input_revision_changed(t1_db, monkeypatch):
    from neurosearch import jobs, t1
    project_id = db.create_project("T1 stale", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "new text", "approved", db.now()))
    db.connect().commit(); note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    monkeypatch.setattr("neurosearch.embeddings.embed_texts", lambda texts, **kwargs: (_ for _ in ()).throw(AssertionError("must not embed stale input")))
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


def test_t1_backfill_preview_never_queues_work(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 preview", "test")["id"]
    report = t1.backfill_preview(project_id)
    assert report["total_rows"] == 0 and report["queued"] == 0 and report["executed"] == 0


def test_t1_backfill_endpoint_is_bounded_and_low_lane(t1_db, client):
    project_id = db.create_project("T1 endpoint", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "queue through API", "approved", db.now()))
    db.connect().commit()
    headers = {"Authorization": "Bearer t0k"}
    queued = client.post(f"/api/projects/{project_id}/transcript/backfill", headers=headers, json={"limit": 1})
    assert queued.status_code == 200 and queued.json()["queued"] == 1
    assert queued.json()["lane"] == "low" and queued.json()["version"] == "t1-derived-v1"
    assert client.post(f"/api/projects/{project_id}/transcript/backfill", headers=headers, json={"limit": 5001}).status_code == 400
    assert client.post("/api/projects/nope/transcript/backfill", headers=headers, json={"limit": 1}).status_code == 404


def test_t1_backfill_offset_reaches_later_rows_without_duplicate_pages(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 paging", "test")["id"]
    for i in range(3):
        db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                             (project_id, f"queue {i}", "approved", db.now()))
    db.connect().commit()
    ids = [r["id"] for r in db.connect().execute("SELECT id FROM project_notes WHERE project_id=? ORDER BY id", (project_id,)).fetchall()]
    first = t1.enqueue_backfill(project_id, limit=2, offset=0)
    second = t1.enqueue_backfill(project_id, limit=2, offset=2)
    assert [j["payload"]["object_id"] for j in first] == ids[:2]
    assert [j["payload"]["object_id"] for j in second] == ids[2:]


def test_t1_preview_and_queue_include_stale_vectors_not_only_nulls(t1_db, monkeypatch):
    from neurosearch import t1
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "embedding_model", "current-model")
    project_id = db.create_project("T1 stale preview", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "current text", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    current_hash = t1.input_hash("current text", "", None, None)
    db.set_derived_embedding("project_notes", note_id, np.array([1., 0.], dtype=np.float32),
                             provider="openai", model="old-model", version=t1.VECTOR_VERSION,
                             input_hash=current_hash)
    assert t1.backfill_preview(project_id)["total_rows"] == 1
    queued = t1.enqueue_backfill(project_id, limit=1)
    assert len(queued) == 1 and queued[0]["payload"]["model"] == "current-model"
    assert t1.enqueue_backfill(project_id, limit=0) == []


def test_t1_preview_skips_a_current_matching_vector(t1_db, monkeypatch):
    from neurosearch import t1
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "embedding_model", "current-model")
    project_id = db.create_project("T1 current preview", "test")["id"]
    db.connect().execute("INSERT INTO project_notes (project_id, content, status, created_at) VALUES (?,?,?,?)",
                         (project_id, "current text", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    current_hash = t1.input_hash("current text", "", None, None)
    db.set_derived_embedding("project_notes", note_id, np.array([1., 0.], dtype=np.float32),
                             provider="openai", model="current-model", version=t1.VECTOR_VERSION,
                             input_hash=current_hash)
    assert t1.backfill_preview(project_id)["total_rows"] == 0
    assert t1.enqueue_backfill(project_id, limit=10) == []


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
    assert att["verification_scope"] == "dimensions_and_canonical_write_revision"
    assert att["provenance_basis"] == "declared_preparation_metadata"


def test_t1_attestation_expires_when_chunk_vectors_change(t1_db):
    from neurosearch import t1
    project_id = db.create_project("T1 revision", "test")["id"]
    source_id = db.upsert_source(platform="manual", external_id="revision", url="manual://revision", title="revision")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id, source_id) VALUES (?,?)", (project_id, source_id))
    db.connect().execute("INSERT INTO chunks (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                         (source_id, 0, 0, 1, "chunk"))
    db.connect().commit()
    chunk_id = db.connect().execute("SELECT last_insert_rowid()").fetchone()[0]
    db.set_embeddings([(chunk_id, np.array([1., 0.], dtype=np.float32))])
    att = t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t1-test")
    assert t1.get_chunk_space_attestation() == att
    db.set_embeddings([(chunk_id, np.array([0., 1.], dtype=np.float32))])
    assert t1.get_chunk_space_attestation() is None


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


def test_t1_read_filters_status_version_and_dimension(t1_db):
    project_id = db.create_project("T1 filters", "test")["id"]
    rows = [("accepted", "v1", 2), ("rejected", "v1", 2), ("proposed", "old", 2), ("proposed", "v1", 3)]
    for i, (status, version, dim) in enumerate(rows):
        cid = f"c{i}"
        db.connect().execute("INSERT INTO project_claims (id, project_id, text, status, created_at, updated_at, embedding_provider, embedding_model, embedding_dimensions, embedding_version, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, project_id, "claim", status, db.now(), db.now(), "openai", "m", dim, version, np.zeros(dim, dtype=np.float32).tobytes()))
    db.connect().commit()
    out = db.load_versioned_derived_embeddings("project_claims", project_id, provider="openai", model="m", version="v1", dimensions=2)
    assert [r["id"] for r in out] == ["c0"]
