"""T5 live adjudication call: only against the fake provider harness here (no real spend in CI) -- refuses any
tension the trigger didn't flag, writes its verdict as a suggested finding, never changes Claim/tension status."""

import pytest

from neurosearch import contracts, db, t5


@pytest.fixture
def t5_adj_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "fake_ai", True)
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(project_id: str, claim_id: str) -> None:
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (claim_id, project_id, "Businesses sell for 3-5x profit.", "accepted", db.now(), db.now()))


def _tension(project_id: str, tension_id: str, kind: str, *, impact: str = "high", claim_id: str | None = None,
            status: str = "open") -> None:
    t = db.now()
    db.connect().execute("""INSERT INTO research_tensions
        (id,project_id,kind,claim_id,description,impact,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
                         (tension_id, project_id, kind, claim_id, f"{kind} description", impact, status, t, t))


def test_t5_adjudicate_contract_is_registered_and_gate_clean(t5_adj_db):
    c = contracts.contract(t5.ADJUDICATE_TASK)
    assert c.model == contracts.TIERS[1]
    assert c.reversible is True
    decision = contracts.decision(c)
    assert decision["verdict"] == "evidence"  # above cheapest, admissible reason
    assert c.task not in [v.split(":")[0] for v in contracts.policy_violations()]


def test_adjudicate_refuses_a_tension_the_trigger_did_not_flag(t5_adj_db):
    project_id = db.create_project("T5 refuse", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-low", "CONTRADICTION", impact="medium", claim_id="claim-1")  # medium impact: not a candidate
    db.connect().commit()

    with pytest.raises(ValueError, match="not an open, high-impact tension"):
        t5.adjudicate(project_id, "tsn-low")


def test_adjudicate_refuses_an_unknown_tension_id(t5_adj_db):
    project_id = db.create_project("T5 unknown", "test")["id"]
    db.connect().commit()

    with pytest.raises(ValueError, match="not an open, high-impact tension"):
        t5.adjudicate(project_id, "does-not-exist")


def test_adjudicate_writes_a_suggested_finding_never_approved(t5_adj_db):
    project_id = db.create_project("T5 writes suggested", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()
    notes_before = db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0]

    result = t5.adjudicate(project_id, "tsn-1")

    assert result["written_note_id"] is not None
    assert db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0] == notes_before + 1
    note = db.connect().execute("SELECT * FROM project_notes WHERE id=?", (result["written_note_id"],)).fetchone()
    assert note["status"] == "suggested"  # never auto-approved
    assert result["verdict"] and result["verdict"] in note["content"]


def test_adjudicate_never_changes_claim_or_tension_status(t5_adj_db):
    project_id = db.create_project("T5 no side effects", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "NOVEL", impact="high", claim_id="claim-1")
    db.connect().commit()

    t5.adjudicate(project_id, "tsn-1")

    claim = db.connect().execute("SELECT status FROM project_claims WHERE id=?", ("claim-1",)).fetchone()
    tension = db.connect().execute("SELECT status FROM research_tensions WHERE id=?", ("tsn-1",)).fetchone()
    assert claim["status"] == "accepted"      # unchanged
    assert tension["status"] == "open"        # unchanged -- claims.set_status is still the only promotion door


def test_adjudicate_can_run_dry_without_writing(t5_adj_db):
    project_id = db.create_project("T5 dry run", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "WEAK_CONSENSUS", impact="high", claim_id="claim-1")
    db.connect().commit()
    notes_before = db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0]

    result = t5.adjudicate(project_id, "tsn-1", write=False)

    assert result["written_note_id"] is None
    assert db.connect().execute("SELECT COUNT(*) FROM project_notes").fetchone()[0] == notes_before


def test_adjudicate_records_a_cost(t5_adj_db):
    project_id = db.create_project("T5 records cost", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()

    result = t5.adjudicate(project_id, "tsn-1")

    assert isinstance(result["cost"], float)
    assert result["model"]
