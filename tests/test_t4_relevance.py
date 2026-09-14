"""T4 selector v2: source relevance (Claim-centroid proximity) ranks unexplained chunks within a priority --
read-only, $0, and honest about unavailability exactly like T1/T2."""

import numpy as np
import pytest

from neurosearch import db, t1, t4


@pytest.fixture
def t4r_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id, url=f"manual://{external_id}", title=external_id)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    return sid


def _chunk(sid: str, idx: int, text: str, vec) -> None:
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text,embedding) VALUES (?,?,?,?,?,?)",
                         (sid, idx, idx * 40, idx * 40 + 40, text, np.array(vec, dtype=np.float32).tobytes()))


def _claim_vector(project_id: str, cid: str, vec) -> None:
    db.connect().execute("INSERT INTO project_claims (id, project_id, text, status, created_at, updated_at, embedding_provider, "
                         "embedding_model, embedding_dimensions, embedding_version, embedding_input_hash, embedding) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cid, project_id, "claim", "accepted", db.now(), db.now(), "openai", "m", 2, t1.VECTOR_VERSION, "h",
                          np.array(vec, dtype=np.float32).tobytes()))


CUE = "The warranty lasts 90 days from purchase."   # a Tier-0 cue (duration): priority 1 either way


def test_relevance_unavailable_without_attestation_and_ranking_still_deterministic(t4r_db):
    project_id = db.create_project("T4 rel none", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, CUE, [1.0, 0.0])
    db.connect().commit()

    rel = t4.source_relevance(project_id)
    assert rel["status"] == "unavailable" and rel["reason"] == "chunk_space_unattested" and rel["scores"] == {}
    sel = t4.select(project_id)
    assert sel["items"][0]["relevance"] is None                   # unavailable is None, never a low number
    assert sel["relevance"]["status"] == "unavailable"
    assert sel == t4.select(project_id)


def test_relevance_unavailable_without_claim_vectors(t4r_db):
    project_id = db.create_project("T4 rel noclaims", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, CUE, [1.0, 0.0])
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t")

    rel = t4.source_relevance(project_id)
    assert rel["status"] == "unavailable" and rel["reason"] == "claim_vectors_unavailable"


def test_more_relevant_source_ranks_first_within_the_same_priority(t4r_db):
    project_id = db.create_project("T4 rel rank", "test")["id"]
    near = _source(project_id, "near")     # chunk vectors point where the project's Claims point
    far = _source(project_id, "far")       # orthogonal to them
    _chunk(near, 0, CUE, [1.0, 0.0])
    _chunk(far, 0, CUE, [0.0, 1.0])
    _claim_vector(project_id, "c1", [1.0, 0.0])
    _claim_vector(project_id, "c2", [0.9, 0.1])
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t")

    rel = t4.source_relevance(project_id)
    assert rel["status"] == "measured" and rel["claim_vectors"] == 2
    assert rel["scores"][near] > rel["scores"][far]

    sel = t4.select(project_id)
    chunks = [i for i in sel["items"] if i["kind"] == "unexplained_chunk"]
    assert [i["source_id"] for i in chunks] == [near, far]
    assert chunks[0]["priority"] == chunks[1]["priority"] == 1   # relevance only reorders within a priority
    assert [s["source_id"] for s in sel["by_source"]] == [near, far]
    assert sel["by_source"][0]["priority1_chunks"] == 1


def test_priority_still_outranks_relevance(t4r_db):
    project_id = db.create_project("T4 rel prio", "test")["id"]
    near_dull = _source(project_id, "near-dull")   # relevant but no Tier-0 cue: priority 2
    far_cue = _source(project_id, "far-cue")       # irrelevant but cue-bearing: priority 1
    _chunk(near_dull, 0, "Some unrelated filler passage without any numbers here.", [1.0, 0.0])
    _chunk(far_cue, 0, CUE, [0.0, 1.0])
    _claim_vector(project_id, "c1", [1.0, 0.0])
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t")

    chunks = [i for i in t4.select(project_id)["items"] if i["kind"] == "unexplained_chunk"]
    assert [i["source_id"] for i in chunks] == [far_cue, near_dull]


def test_source_without_chunk_vectors_is_unscored_not_zero(t4r_db):
    project_id = db.create_project("T4 rel novec", "test")["id"]
    scored = _source(project_id, "scored")
    unscored = _source(project_id, "unscored")
    _chunk(scored, 0, CUE, [1.0, 0.0])
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (unscored, 0, 0, 40, CUE))
    _claim_vector(project_id, "c1", [1.0, 0.0])
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t")

    rel = t4.source_relevance(project_id)
    assert rel["status"] == "measured"
    assert rel["scores"][scored] == pytest.approx(1.0)
    assert unscored not in rel["scores"]                         # absent, never 0.0
    items = {i["source_id"]: i for i in t4.select(project_id)["items"] if i["kind"] == "unexplained_chunk"}
    assert items[unscored]["relevance"] is None


def test_selector_still_writes_nothing(t4r_db):
    project_id = db.create_project("T4 rel nowrite", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, CUE, [1.0, 0.0])
    _claim_vector(project_id, "c1", [1.0, 0.0])
    db.connect().commit()
    t1.attest_chunk_space(provider="openai", model="m", dimensions=2, preparation_tag="t")
    conn = db.connect()
    before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("chunks", "project_claims", "project_notes", "jobs", "work_units")}

    t4.select(project_id)
    t4.plan(project_id)

    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert after == before
