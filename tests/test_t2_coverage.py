"""T2 derived coverage view: typed locators, fail-open signals, and read-only behavior."""

import json

import numpy as np
import pytest

from neurosearch import db, t1


@pytest.fixture
def t2_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str, *, excluded: int = 0) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id,
                           url=f"manual://{external_id}", title=external_id)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,?)",
                         (project_id, sid, excluded))
    return sid


def test_t2_locator_boundaries_and_unknowns_are_typed_and_read_only(t2_db):
    project_id = db.create_project("T2 boundaries", "test")['id']
    sid = _source(project_id, "boundary")
    excluded_sid = _source(project_id, "excluded", excluded=1)
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text,embedding) VALUES (?,?,?,?,?,?)",
                         (sid, 0, 0, 10, "first", np.array([1., 0.], dtype=np.float32).tobytes()))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text,embedding) VALUES (?,?,?,?,?,?)",
                         (sid, 1, 10, 20, "second", np.array([0., 1.], dtype=np.float32).tobytes()))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text,embedding) VALUES (?,?,?,?,?,?)",
                         (excluded_sid, 0, 0, 10, "excluded", np.array([1., 0.], dtype=np.float32).tobytes()))
    claim_id = "claim-boundary"
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (claim_id, project_id, "claim", "accepted", db.now(), db.now()))
    db.connect().execute("INSERT INTO claim_evidence (claim_id,source_id,start,created_at) VALUES (?,?,?,?)",
                         (claim_id, sid, 10, db.now()))
    db.connect().execute("INSERT INTO claim_evidence (claim_id,source_id,start,created_at) VALUES (?,?,?,?)",
                         (claim_id, sid, 20, db.now()))
    db.connect().execute("INSERT INTO project_notes (project_id,content,citations,status,created_at) VALUES (?,?,?,?,?)",
                         (project_id, "finding", json.dumps([{"source_id": sid, "start": 0, "end": 5}]), "approved", db.now()))
    db.connect().commit()
    before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    report = t1.coverage_view(project_id, limit=10)

    assert report["denominator"] == 2
    assert report["reconciliation"]["claim_locator_reasons"] == {"at_chunk_end": 1}
    assert report["signals"]["claim_covered"] == 1
    assert report["signals"]["finding_covered"] == 1
    assert report["semantic"]["status"] == "unavailable"
    assert all({"extracted", "redundant", "irrelevant", "represented"} <= set(row["unknown_signals"])
               for row in report["chunks"])
    assert {row["primary_state"] for row in report["chunks"]} == {"claim_covered", "finding_covered"}
    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == before


def test_t2_representation_uses_attested_project_relative_cut_points(t2_db):
    project_id = db.create_project("T2 semantic", "test")['id']
    sid = _source(project_id, "semantic")
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text,embedding) VALUES (?,?,?,?,?,?)",
                         (sid, 0, 0, 10, "chunk", np.array([1., 0.], dtype=np.float32).tobytes()))
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         ("claim-sem", project_id, "claim", "accepted", db.now(), db.now()))
    db.connect().execute("INSERT INTO project_notes (project_id,content,status,created_at) VALUES (?,?,?,?)",
                         (project_id, "finding", "approved", db.now()))
    db.connect().commit()
    note_id = db.connect().execute("SELECT id FROM project_notes WHERE project_id=?", (project_id,)).fetchone()[0]
    db.set_derived_embedding("project_claims", "claim-sem", np.array([1., 0.], dtype=np.float32),
                             provider="openai", model="t2-model", version=t1.VECTOR_VERSION, input_hash="claim")
    db.set_derived_embedding("project_notes", note_id, np.array([0., 1.], dtype=np.float32),
                             provider="openai", model="t2-model", version=t1.VECTOR_VERSION, input_hash="finding")
    t1.attest_chunk_space(provider="openai", model="t2-model", dimensions=2, preparation_tag="t2-test")

    report = t1.coverage_view(project_id, limit=1)

    assert report["semantic"]["status"] == "measured"
    assert report["semantic"]["thresholds"] == {"claims": 1.0, "findings": 0.0}
    assert report["signals"]["represented"] == 1
    assert report["chunks"][0]["signals"] == ["represented"]
    assert report["chunks"][0]["primary_state"] == "represented"


def test_t2_invalid_window_fails_open_without_becoming_covered(t2_db):
    project_id = db.create_project("T2 invalid", "test")['id']
    sid = _source(project_id, "invalid")
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)",
                         (sid, 0, 0, 10, "chunk"))
    db.connect().execute("INSERT INTO project_notes (project_id,content,citations,status,created_at) VALUES (?,?,?,?,?)",
                         (project_id, "finding", json.dumps([{"source_id": sid, "start": 8, "end": 2}]), "approved", db.now()))
    db.connect().commit()

    report = t1.coverage_view(project_id, limit=1)

    assert report["reconciliation"]["finding_citation_reasons"] == {"invalid_window": 1}
    assert report["signals"]["finding_covered"] == 0
    assert report["chunks"][0]["primary_state"] == "unknown"


def test_t2_authenticated_endpoint_pages_the_derived_view(client):
    project_id = client.post("/api/projects", headers={"Authorization": "Bearer t0k"},
                             json={"name": "T2 endpoint", "brief": "test"}).json()["id"]
    response = client.get(f"/api/projects/{project_id}/transcript/coverage?detail=chunks&limit=2",
                          headers={"Authorization": "Bearer t0k"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id and payload["denominator"] == 0
    assert payload["chunks"] == [] and payload["limit"] == 2
    assert client.get(f"/api/projects/{project_id}/transcript/coverage?detail=invalid",
                      headers={"Authorization": "Bearer t0k"}).status_code == 400
