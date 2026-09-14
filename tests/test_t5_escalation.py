"""T5 escalation trigger: pure, read-only, proposes adjudication candidates from real tension signals only —
makes no provider call and writes nothing anywhere."""

import pytest

from neurosearch import contracts, db, t5


@pytest.fixture
def t5_db(tmp_path, monkeypatch):
    from neurosearch.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(project_id: str, claim_id: str, *, model: str | None = None) -> None:
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at,model) VALUES (?,?,?,?,?,?,?)",
                         (claim_id, project_id, "claim text", "accepted", db.now(), db.now(), model))


def _tension(project_id: str, tension_id: str, kind: str, *, impact: str = "high", claim_id: str | None = None,
            status: str = "open") -> None:
    t = db.now()
    db.connect().execute("""INSERT INTO research_tensions
        (id,project_id,kind,claim_id,description,impact,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
                         (tension_id, project_id, kind, claim_id, f"{kind} description", impact, status, t, t))


def test_high_impact_contradiction_triggers_source_disagreement(t5_db):
    project_id = db.create_project("T5 contradiction", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    assert result["count"] == 1
    c = result["candidates"][0]
    assert c["trigger"] == "source_disagreement"
    assert c["tension_id"] == "tsn-1"
    assert c["tier_reason"].startswith("evidence:")
    assert c["proposed_model"] == contracts.TIERS[1]
    assert c["decision_verdict"] == "evidence"  # never UNJUSTIFIED -- the reason is properly formed


def test_high_impact_novel_and_weak_consensus_trigger_ambiguous_evidence(t5_db):
    project_id = db.create_project("T5 ambiguous", "test")["id"]
    _claim(project_id, "claim-1")
    _claim(project_id, "claim-2")
    _tension(project_id, "tsn-novel", "NOVEL", impact="high", claim_id="claim-1")
    _tension(project_id, "tsn-weak", "WEAK_CONSENSUS", impact="high", claim_id="claim-2")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    triggers = {c["tension_id"]: c["trigger"] for c in result["candidates"]}
    assert triggers == {"tsn-novel": "ambiguous_evidence", "tsn-weak": "ambiguous_evidence"}


def test_medium_and_low_impact_tensions_never_trigger(t5_db):
    project_id = db.create_project("T5 low impact", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-med", "CONTRADICTION", impact="medium", claim_id="claim-1")
    _tension(project_id, "tsn-low", "NOVEL", impact="low", claim_id="claim-1")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    assert result["count"] == 0


def test_stale_and_missing_perspective_never_trigger_even_at_high_impact(t5_db):
    project_id = db.create_project("T5 not adjudication", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-stale", "STALE", impact="high", claim_id="claim-1")
    _tension(project_id, "tsn-missing", "MISSING_PERSPECTIVE", impact="high", claim_id="claim-1")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    assert result["count"] == 0


def test_resolved_tension_is_excluded(t5_db):
    project_id = db.create_project("T5 resolved", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1", status="resolved")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    assert result["count"] == 0


def test_comparison_detail_reflects_live_recorded_data_not_a_stated_opinion(t5_db):
    project_id = db.create_project("T5 comparison", "test")["id"]
    _claim(project_id, "claim-1", model="claude-haiku-4-5")
    _claim(project_id, "claim-2", model="claude-haiku-4-5")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()

    result = t5.escalation_candidates(project_id, unit="claim")

    assert result["comparison_supported"] is True
    assert "claude-haiku-4-5" in result["comparison_basis"]
    assert result["candidates"][0]["tier_reason"] == f"evidence:{result['comparison_basis']}"


def test_no_open_tensions_returns_empty_candidates(t5_db):
    project_id = db.create_project("T5 empty", "test")["id"]
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    assert result["count"] == 0 and result["candidates"] == []


def test_escalation_candidates_is_read_only(t5_db):
    project_id = db.create_project("T5 readonly", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()
    jobs_before = db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    tensions_before = db.connect().execute("SELECT COUNT(*) FROM research_tensions").fetchone()[0]
    claims_before = db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0]

    t5.escalation_candidates(project_id)

    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before
    assert db.connect().execute("SELECT COUNT(*) FROM research_tensions").fetchone()[0] == tensions_before
    assert db.connect().execute("SELECT COUNT(*) FROM project_claims").fetchone()[0] == claims_before


def test_every_proposed_reason_is_admissible_to_the_real_ladder(t5_db):
    # The gate, verbatim from the mission doc: "the model decision table still refuses any tier above the
    # cheapest without a stated reason." T5 must never produce a candidate contracts.decision would reject.
    project_id = db.create_project("T5 gate", "test")["id"]
    _claim(project_id, "claim-1")
    _tension(project_id, "tsn-1", "CONTRADICTION", impact="high", claim_id="claim-1")
    db.connect().commit()

    result = t5.escalation_candidates(project_id)

    for c in result["candidates"]:
        assert contracts.policy_reason_ok(c["tier_reason"])
        assert c["decision_verdict"] != "UNJUSTIFIED"


def test_result_is_deterministic_across_repeated_calls(t5_db):
    project_id = db.create_project("T5 repro", "test")["id"]
    _claim(project_id, "claim-1")
    _claim(project_id, "claim-2")
    _tension(project_id, "tsn-a", "CONTRADICTION", impact="high", claim_id="claim-1")
    _tension(project_id, "tsn-b", "NOVEL", impact="high", claim_id="claim-2")
    db.connect().commit()

    first = t5.escalation_candidates(project_id)
    second = t5.escalation_candidates(project_id)

    assert first == second
    assert [c["tension_id"] for c in first["candidates"]] == ["tsn-a", "tsn-b"]  # sorted, stable order
