"""Decision Impact v1 (PRODUCT-INTELLIGENCE-MISSION.md, CTO rulings §6): exactly two deterministic signals --
disagreement (open CONTRADICTION/NOVEL tension) and plan_impact (cited via a folded Finding in the current
plan's evidence). Everything else must report "unknown", never a guess. $0, read-only, no provider call."""
from __future__ import annotations

import json

import pytest

from neurosearch import db, decision_impact as di


@pytest.fixture
def di_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(project_id: str, cid: str, status: str = "accepted") -> None:
    db.connect().execute(
        "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, freshness_class, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, project_id, f"claim {cid}", "factual", "topic", status, "moderate", "age_insensitive", db.now(), db.now()))


def _tension(project_id: str, tid: str, claim_id: str, kind: str = "CONTRADICTION", status: str = "open") -> None:
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, impact, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, project_id, kind, claim_id, "d", status, "medium", db.now(), db.now()))


def test_no_claims_returns_empty(di_db):
    p = db.create_project("DI empty", "brief")
    assert di.decision_impact(p["id"]) == {}


def test_disagreement_true_only_for_open_contradiction_or_novel(di_db):
    p = db.create_project("DI disagreement", "brief")
    pid = p["id"]
    _claim(pid, "c1"); _claim(pid, "c2"); _claim(pid, "c3"); _claim(pid, "c4")
    _tension(pid, "t1", "c1", kind="CONTRADICTION", status="open")
    _tension(pid, "t2", "c2", kind="NOVEL", status="open")
    _tension(pid, "t3", "c3", kind="CONTRADICTION", status="resolved")   # closed -- doesn't count
    _tension(pid, "t4", "c4", kind="WEAK_CONSENSUS", status="open")     # wrong kind -- doesn't count
    db.connect().commit()

    out = di.decision_impact(pid)
    assert out["c1"]["disagreement"] is True
    assert out["c2"]["disagreement"] is True
    assert out["c3"]["disagreement"] is False
    assert out["c4"]["disagreement"] is False


def test_rejected_claims_excluded_by_default(di_db):
    p = db.create_project("DI rejected", "brief")
    pid = p["id"]
    _claim(pid, "keep", status="accepted")
    _claim(pid, "gone", status="rejected")
    db.connect().commit()
    assert set(di.decision_impact(pid)) == {"keep"}


def test_plan_impact_unknown_without_a_plan(di_db):
    p = db.create_project("DI noplan", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    db.connect().commit()
    assert di.decision_impact(pid)["c1"]["plan_impact"] == "unknown"


def test_plan_impact_true_when_a_folded_finding_is_cited(di_db):
    p = db.create_project("DI cited", "brief")
    pid = p["id"]
    n_cited = db.add_project_note(pid, "the cited finding")
    n_other = db.add_project_note(pid, "an uncited finding")
    _claim(pid, "c1")
    _claim(pid, "c2")
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c1", n_cited["id"]))
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c2", n_other["id"]))
    db.connect().commit()

    # planner._evidence()'s F<n> numbering is sequential over reversed(list_project_notes()). With no
    # importance set, list_project_notes orders (importance DESC, created_at DESC) -- ties break newest-first, so
    # unordered = [n_other, n_cited] (n_other added second = newest). reversed() = [n_cited, n_other], so
    # n_cited -> F1, n_other -> F2.
    plan = {"first_steps": [{"action": "do the thing", "evidence": ["F1"]}]}
    snapshot = db.project_snapshot(pid)   # {"notes": 2, ...} -- matches current note count, so plan_impact trusts it
    db.save_plan(pid, plan, snapshot)

    out = di.decision_impact(pid)
    assert out["c1"]["plan_impact"] is True    # c1's finding (n_cited) is F1, which the plan cites
    assert out["c2"]["plan_impact"] is False   # c2's finding (n_other) is F2, not cited


def test_plan_impact_unknown_when_notes_changed_since_the_plan(di_db):
    p = db.create_project("DI stale plan", "brief")
    pid = p["id"]
    n1 = db.add_project_note(pid, "finding one")
    _claim(pid, "c1")
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c1", n1["id"]))
    db.connect().commit()

    db.save_plan(pid, {"first_steps": [{"action": "x", "evidence": ["F1"]}]}, db.project_snapshot(pid))
    db.add_project_note(pid, "a NEW finding added after the plan was built")   # note count now disagrees with the plan's snapshot
    db.connect().commit()

    assert di.decision_impact(pid)["c1"]["plan_impact"] == "unknown"


def test_specific_claim_ids_filters_the_result(di_db):
    p = db.create_project("DI filter", "brief")
    pid = p["id"]
    _claim(pid, "c1"); _claim(pid, "c2")
    db.connect().commit()
    assert set(di.decision_impact(pid, claim_ids=["c1"])) == {"c1"}
