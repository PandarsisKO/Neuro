"""L-60 (EXECUTION-LADDER.md Stage 8, P6 T5 operationalization): decision-aware escalation triggers + a budgeted
nightly adjudication pass. Gate (P6): T5 output appears because it changes what the user should know or do --
here that means: only tensions the trigger selects, never twice, never past the budget, always as a SUGGESTED
finding, never a status change."""
from __future__ import annotations

import pytest

from neurosearch import db, nightly, t4, t5


@pytest.fixture
def t5n_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 0.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "t5_nightly_budget", 0.0)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(pid: str, cid: str, status: str = "accepted") -> None:
    db.connect().execute("INSERT INTO project_claims (id,project_id,text,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                         (cid, pid, "Businesses sell for 3-5x profit.", status, db.now(), db.now()))


def _tension(pid: str, tid: str, kind: str, *, impact: str = "high", claim_id: str | None = None) -> None:
    t = db.now()
    db.connect().execute("INSERT INTO research_tensions (id,project_id,kind,claim_id,description,impact,status,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", (tid, pid, kind, claim_id, f"{kind} description", impact, "open", t, t))


def _plan_citing(pid: str, cid: str) -> None:
    n = db.add_project_note(pid, "the cited finding")
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (cid, n["id"]))
    db.connect().commit()
    db.save_plan(pid, {"first_steps": [{"action": "x", "evidence": ["F1"]}]}, db.project_snapshot(pid))


def test_decision_aware_adds_plan_cited_low_impact_tensions_and_nothing_else(t5n_db):
    pid = db.create_project("T5 decision", "b")["id"]
    _claim(pid, "c_planned"); _claim(pid, "c_other")
    _tension(pid, "t_weak_on_plan", "WEAK_CONSENSUS", impact="medium", claim_id="c_planned")
    _tension(pid, "t_contra_on_plan", "CONTRADICTION", impact="low", claim_id="c_planned")
    _tension(pid, "t_weak_elsewhere", "WEAK_CONSENSUS", impact="medium", claim_id="c_other")
    _tension(pid, "t_stale_on_plan", "STALE", impact="high", claim_id="c_planned")
    db.connect().commit()
    _plan_citing(pid, "c_planned")

    plain = t5.escalation_candidates(pid)
    assert plain["count"] == 0, "without decision_aware the medium/low tensions never trigger (existing behavior)"
    aware = t5.escalation_candidates(pid, decision_aware=True)
    by = {c["tension_id"]: c["trigger"] for c in aware["candidates"]}
    assert by == {"t_weak_on_plan": "weak_consensus_on_decision", "t_contra_on_plan": "plan_critical_uncertainty"}


def test_decision_aware_adds_nothing_when_plan_impact_is_unknown(t5n_db):
    pid = db.create_project("T5 noplan", "b")["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "WEAK_CONSENSUS", impact="medium", claim_id="c1")
    db.connect().commit()
    assert t5.escalation_candidates(pid, decision_aware=True)["count"] == 0, "unknown never escalates"


def test_run_nightly_off_calls_nothing(t5n_db):
    pid = db.create_project("T5 off", "b")["id"]
    _claim(pid, "c1"); _tension(pid, "t1", "CONTRADICTION", claim_id="c1"); db.connect().commit()
    r = t5.run_nightly([pid], budget_usd=0, envelope_id="nightly-test")
    assert r["ran"] is False and r["adjudicated"] == []
    assert db.connect().execute("SELECT COUNT(*) n FROM usage").fetchone()["n"] == 0


def test_run_nightly_adjudicates_within_budget_never_twice_and_only_as_suggested_findings(t5n_db):
    pid = db.create_project("T5 night", "b")["id"]
    _claim(pid, "c1"); _claim(pid, "c2"); _claim(pid, "c3")
    _tension(pid, "t_high_a", "CONTRADICTION", claim_id="c1")
    _tension(pid, "t_high_b", "NOVEL", claim_id="c2")
    _tension(pid, "t_high_c", "WEAK_CONSENSUS", claim_id="c3")
    db.connect().commit()
    per_call = t5.estimate_adjudication(pid, "c1")
    assert per_call > 0

    r = t5.run_nightly([pid], budget_usd=per_call * 2.5, envelope_id="nightly-2026-09-15")
    assert r["ran"] is True
    assert [a["tension_id"] for a in r["adjudicated"]] == ["t_high_a", "t_high_b"], "two fit, the third would exceed the cap"
    assert r["stopped_by_budget"]["tension_id"] == "t_high_c"
    assert r["spent_estimate"] <= per_call * 2.5 + 1e-9
    notes = db.connect().execute("SELECT status, content FROM project_notes WHERE project_id=?", (pid,)).fetchall()
    assert len(notes) == 2 and all(n["status"] == "suggested" for n in notes)
    assert all(row["status"] == "accepted" for row in db.connect().execute("SELECT status FROM project_claims WHERE project_id=?", (pid,)))
    assert all(row["status"] == "open" for row in db.connect().execute("SELECT status FROM research_tensions WHERE project_id=?", (pid,)))

    # the next night: the two already adjudicated are skipped, only the third is paid for
    r2 = t5.run_nightly([pid], budget_usd=per_call * 10, envelope_id="nightly-2026-09-16")
    assert r2["skipped_already"] == 2
    assert [a["tension_id"] for a in r2["adjudicated"]] == ["t_high_c"]
    r3 = t5.run_nightly([pid], budget_usd=per_call * 10, envelope_id="nightly-2026-09-17")
    assert r3["adjudicated"] == [] and r3["skipped_already"] == 3, "never paid for twice"


def test_high_impact_before_decision_triggered(t5n_db):
    pid = db.create_project("T5 order", "b")["id"]
    _claim(pid, "c_planned"); _claim(pid, "c_high")
    _tension(pid, "t_a_decision", "WEAK_CONSENSUS", impact="medium", claim_id="c_planned")   # sorts first by id...
    _tension(pid, "t_z_high", "CONTRADICTION", impact="high", claim_id="c_high")             # ...but high impact wins
    db.connect().commit()
    _plan_citing(pid, "c_planned")
    per_call = t5.estimate_adjudication(pid, "c_high")
    r = t5.run_nightly([pid], budget_usd=per_call * 1.5, envelope_id="e")
    assert [a["tension_id"] for a in r["adjudicated"]] == ["t_z_high"]


def test_one_projects_failure_does_not_abort_the_pass(t5n_db, monkeypatch):
    bad = db.create_project("bad", "b")["id"]; good = db.create_project("good", "b")["id"]
    _claim(good, "c1"); _tension(good, "t1", "CONTRADICTION", claim_id="c1"); db.connect().commit()
    real = t5.escalation_candidates

    def flaky(pid, **kw):
        if pid == bad:
            raise RuntimeError("boom")
        return real(pid, **kw)

    monkeypatch.setattr(t5, "escalation_candidates", flaky)
    r = t5.run_nightly([bad, good], budget_usd=5.0, envelope_id="e")
    assert r["errors"][0]["project_id"] == bad and [a["tension_id"] for a in r["adjudicated"]] == ["t1"]


def test_nightly_envelope_runs_t5_under_its_own_budget_and_the_report_says_so(t5n_db, monkeypatch):
    from neurosearch import delta, report
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t5_nightly_budget", 1.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    pid = db.create_project("T5 envelope", "b")["id"]
    sid = db.upsert_source(platform="manual", external_id="s", url="manual://s", title="s", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    db.connect().execute("INSERT INTO chunks (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0, 10, "some text."))
    db.connect().execute("INSERT INTO segments (source_id,idx,start,end,text) VALUES (?,?,?,?,?)", (sid, 0, 0.0, 30.0, "some text."))
    _claim(pid, "c1"); _tension(pid, "t1", "CONTRADICTION", claim_id="c1"); db.connect().commit()

    r = nightly.run()
    assert r["ran"] is True
    assert r["adjudication"]["ran"] is True and [a["tension_id"] for a in r["adjudication"]["adjudicated"]] == ["t1"]
    assert r["adjudication"]["budget"] == 1.0 and r["budget"] == 2.0, "two separate authorizations, never merged"

    d = delta.for_envelope(r["envelope_id"])
    assert d["adjudication"]["count"] == 1
    text = report.render_text(report.for_envelope(r["envelope_id"]))
    assert "Adjudicated 1 disagreement(s)" in text and "nothing was decided for you" in text


def test_nightly_envelope_with_t5_off_records_none(t5n_db, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    r = nightly.run()
    assert r["ran"] is True and r["adjudication"] is None
