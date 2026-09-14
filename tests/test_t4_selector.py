"""T4 selector: pure, deterministic, read-only work-list ranking from T1/T2 signals and open Evidence Targets."""

import numpy as np
import pytest

from neurosearch import db, t4


@pytest.fixture
def t4_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, external_id: str) -> str:
    sid = db.upsert_source(platform="manual", external_id=external_id,
                           url=f"manual://{external_id}", title=external_id)["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (project_id, sid))
    return sid


def _chunk(sid: str, idx: int, start: int, end: int, text: str) -> None:
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)",
                         (sid, idx, start, end, text))


def _target(project_id: str, target_id: str, question: str, *, sufficiency: str, status: str = "open",
           claim_id: str | None = None) -> None:
    t = db.now()
    db.connect().execute("""INSERT INTO project_evidence_targets
        (id,project_id,question,sufficiency,status,origin,created_at,updated_at,claim_id)
        VALUES (?,?,?,?,?,?,?,?,?)""",
                         (target_id, project_id, question, sufficiency, status, "user", t, t, claim_id))


def test_unexplained_chunk_with_t3_cue_outranks_one_with_none(t4_db):
    project_id = db.create_project("T4 cues", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "We paid $500 for the service last quarter.")
    _chunk(sid, 1, 40, 80, "It was a pleasant conversation about nothing in particular here today.")
    db.connect().commit()

    result = t4.select(project_id)

    kinds_by_reason = {item["chunk_idx"]: item for item in result["items"] if item["kind"] == "unexplained_chunk"}
    assert kinds_by_reason[0]["priority"] == 1 and kinds_by_reason[0]["cue_kinds"]
    assert kinds_by_reason[1]["priority"] == 2 and kinds_by_reason[1]["cue_kinds"] == []
    assert result["items"][0]["chunk_idx"] == 0  # priority 1 sorts first


def test_claim_covered_chunk_is_not_selected(t4_db):
    project_id = db.create_project("T4 covered", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "We paid $500 for the service last quarter.")
    claim_id = "claim-1"
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (claim_id, project_id, "claim", "accepted", db.now(), db.now()))
    db.connect().execute("INSERT INTO claim_evidence (claim_id,source_id,start,created_at) VALUES (?,?,?,?)",
                         (claim_id, sid, 0, db.now()))
    db.connect().commit()

    result = t4.select(project_id)

    assert result["by_kind"]["unexplained_chunk"] == 0
    assert all(item["kind"] != "unexplained_chunk" for item in result["items"])


def test_governing_target_with_no_claim_outranks_governing_with_claim_and_corroborative(t4_db):
    project_id = db.create_project("T4 targets", "test")["id"]
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         ("claim-x", project_id, "claim", "accepted", db.now(), db.now()))
    _target(project_id, "t-open-governing", "What is the true failure rate for this category?", sufficiency="governing")
    _target(project_id, "t-governing-claimed", "What loan terms are typical?", sufficiency="governing", claim_id="claim-x")
    _target(project_id, "t-corroborative", "Is this a common approach?", sufficiency="corroborative")
    _target(project_id, "t-closed", "A closed question that should not appear", sufficiency="governing", status="closed_by_user")
    db.connect().commit()

    result = t4.select(project_id)

    targets = [i for i in result["items"] if i["kind"] == "open_evidence_target"]
    assert result["by_kind"]["open_evidence_target"] == 3
    assert {t["target_id"] for t in targets} == {"t-open-governing", "t-governing-claimed", "t-corroborative"}
    order = [t["target_id"] for t in targets]
    assert order.index("t-open-governing") < order.index("t-governing-claimed") < order.index("t-corroborative")


def test_selection_is_deterministic_and_reproducible(t4_db):
    project_id = db.create_project("T4 repro", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "The warranty lasts 90 days from purchase.")
    _chunk(sid, 1, 40, 80, "Some unrelated filler passage without any numbers here.")
    _target(project_id, "t-1", "What does the contract actually require?", sufficiency="governing")
    db.connect().commit()

    first = t4.select(project_id)
    second = t4.select(project_id)

    assert first == second
    hashes = [item["input_hash"] for item in first["items"]]
    assert len(hashes) == len(set(hashes))  # every item's provenance hash is unique


def test_limit_truncates_the_ranked_list(t4_db):
    project_id = db.create_project("T4 limit", "test")["id"]
    sid = _source(project_id, "s1")
    for i in range(5):
        _chunk(sid, i, i * 10, i * 10 + 5, f"Passage number {i} with no covered claim here.")
    db.connect().commit()

    result = t4.select(project_id, limit=2)

    assert result["count"] == 5  # count reflects the full ranked list
    assert len(result["items"]) == 2  # items is truncated to the limit


def test_selector_never_writes_or_queues_anything(t4_db):
    project_id = db.create_project("T4 readonly", "test")["id"]
    sid = _source(project_id, "s1")
    _chunk(sid, 0, 0, 40, "We paid $500 for the service last quarter.")
    _target(project_id, "t-1", "What does the contract actually require?", sufficiency="governing")
    db.connect().commit()
    jobs_before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    claims_before = db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0]
    notes_before = db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0]

    t4.select(project_id)

    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before
    assert db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0] == claims_before
    assert db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0] == notes_before


def test_empty_project_returns_empty_ranked_list(t4_db):
    project_id = db.create_project("T4 empty", "test")["id"]
    db.connect().commit()

    result = t4.select(project_id)

    assert result == {"selector_version": t4.SELECTOR_VERSION, "project_id": project_id, "count": 0,
                      "by_kind": {"unexplained_chunk": 0, "open_evidence_target": 0},
                      "relevance": {"status": "unavailable", "reason": "chunk_space_unattested", "claim_vectors": 0},
                      "by_source": [], "items": []}
