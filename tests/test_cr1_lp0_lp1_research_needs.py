"""CR1 + LP0/LP1 (mission §12, EXECUTION-LADDER.md Stages 10-11): the plan-evidence note_id seam (LP0), plan
impact (LP1) and Research Needs (CR1). All $0, read-only, no provider call, no new table -- projections over
Claims/targets/plans that already exist."""
from __future__ import annotations

import time

import pytest

from neurosearch import db, decision_impact as di, plan_impact, research_needs


@pytest.fixture
def rn_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(project_id, cid, *, status="accepted", strength="developing", freshness_status="current",
          freshness_class="age_insensitive", topic="topic", text=None):
    db.connect().execute(
        "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, freshness_status, "
        "freshness_class, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (cid, project_id, text or f"claim {cid}", "factual", topic, status, strength, freshness_status,
         freshness_class, db.now(), db.now()))
    db.connect().commit()


def _tension(project_id, tid, claim_id, kind="CONTRADICTION", status="open"):
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, impact, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, project_id, kind, claim_id, "d", status, "medium", db.now(), db.now()))
    db.connect().commit()


def _fold(claim_id, note_id):
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (claim_id, note_id))
    db.connect().commit()


# ------------------------------------------------------------- LP0: plan-evidence note_id seam


def test_planner_evidence_records_note_id_alongside_the_label(rn_db):
    from neurosearch import planner
    p = db.create_project("LP0", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "a finding")
    ev, emap = planner._evidence(pid, p)
    fids = [e["id"] for e in ev if e["id"].startswith("F")]
    assert fids == ["F1"]
    assert emap["F1"]["note_id"] == n["id"]


def test_plan_impact_stays_known_after_notes_change_when_plan_used_the_lp0_seam(rn_db):
    """The exact bug the acceleration directive flagged: a plan built with the LP0 seam must not degrade to
    'unknown' just because the project's notes changed afterwards -- that is the whole point of recording the
    real note_id at build time instead of re-deriving it from the current ordering."""
    p = db.create_project("LP0 stable", "brief")
    pid = p["id"]
    n_cited = db.add_project_note(pid, "the cited finding")
    _claim(pid, "c1")
    _fold("c1", n_cited["id"])
    plan = {"first_steps": [{"action": "do the thing", "evidence": ["F1"]}],
           "_evidence": {"F1": {"label": "x", "link": None, "kind": "research", "note_id": n_cited["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    db.add_project_note(pid, "a NEW finding added after the plan was built")   # note count now disagrees

    out = di.decision_impact(pid)
    assert out["c1"]["plan_impact"] is True   # known and correct, not "unknown" -- LP0's whole point


def test_old_plan_without_note_ids_still_falls_back_when_notes_unchanged(rn_db):
    p = db.create_project("LP0 legacy", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "the only finding")
    _claim(pid, "c1")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "x", "evidence": ["F1"]}]}   # no _evidence map at all -- an older plan
    db.save_plan(pid, plan, db.project_snapshot(pid))
    assert di.decision_impact(pid)["c1"]["plan_impact"] is True


# ------------------------------------------------------------- LP1: plan_impact.affected_items


def test_affected_items_unknown_without_a_plan(rn_db):
    p = db.create_project("LP1 noplan", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    r = plan_impact.affected_items(pid, claim_id="c1")
    assert r == {"known": False, "items": [], "reason": "no plan yet"}


def test_affected_items_indicated_for_a_direct_citation(rn_db):
    p = db.create_project("LP1 direct", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", text="the claim")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}],
           "decisions": [{"decision": "unrelated", "evidence": []}],
           "_evidence": {"F1": {"label": "x", "note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    r = plan_impact.affected_items(pid, claim_id="c1")
    assert r["known"] is True
    assert r["items"] == [{"path": "first_steps.0", "label": "step one", "strength": "indicated"}]


def test_affected_items_possible_via_a_superseded_claim(rn_db):
    p = db.create_project("LP1 merged", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "old")
    _claim(pid, "survivor")
    db.connect().execute("UPDATE project_claims SET superseded_by=? WHERE id=?", ("survivor", "old"))
    db.connect().commit()
    _fold("old", n["id"])   # the finding is folded into the OLD claim, which merged into "survivor"
    plan = {"tools": [{"need": "a tool", "tool": "x", "evidence": ["F1"]}],
           "_evidence": {"F1": {"label": "x", "note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    r = plan_impact.affected_items(pid, claim_id="survivor")
    assert r["known"] is True
    assert r["items"] == [{"path": "tools.0", "label": "a tool", "strength": "possible"}]


def test_affected_items_via_tension_id_resolves_the_claim(rn_db):
    p = db.create_project("LP1 tension", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1")
    _fold("c1", n["id"])
    _tension(pid, "t1", "c1")
    plan = {"costs": {"evidence": ["F1"]}, "_evidence": {"F1": {"label": "x", "note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    r = plan_impact.affected_items(pid, tension_id="t1")
    assert r["known"] is True and r["items"] == [{"path": "costs", "label": "costs", "strength": "indicated"}]


def test_affected_items_unknown_when_seam_missing_and_notes_moved(rn_db):
    p = db.create_project("LP1 stale", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "x", "evidence": ["F1"]}]}   # no _evidence -- an older plan
    db.save_plan(pid, plan, db.project_snapshot(pid))
    db.add_project_note(pid, "a new finding, moving the count")

    r = plan_impact.affected_items(pid, claim_id="c1")
    assert r["known"] is False and "cannot be safely mapped" in r["reason"]


# ------------------------------------------------------------- CR1: research_needs.for_project


def test_plan_impact_stale_is_first_and_needs_a_stale_or_needs_refresh_claim(rn_db):
    p = db.create_project("CR1 stale", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", freshness_class="rates_pricing", text="rate claim")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "x", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    needs = research_needs.for_project(pid)
    assert needs[0]["kind"] == "plan_impact_stale" and needs[0]["claim_id"] == "c1"


def test_age_insensitive_claim_never_becomes_a_need_by_freshness_alone(rn_db):
    p = db.create_project("CR1 ageins", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="age_insensitive", freshness_class="experiential")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "x", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    assert research_needs.for_project(pid) == []


def test_disagreement_is_a_need_even_without_a_plan(rn_db):
    p = db.create_project("CR1 disagree", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1", kind="NOVEL")
    needs = research_needs.for_project(pid)
    assert len(needs) == 1 and needs[0]["kind"] == "disagreement" and needs[0]["claim_id"] == "c1"


def test_open_target_is_a_need(rn_db):
    from neurosearch import knowledge
    p = db.create_project("CR1 target", "brief")
    pid = p["id"]
    tg = knowledge.add_target(pid, "what does the rule say?")
    needs = research_needs.for_project(pid)
    kinds = [n["kind"] for n in needs]
    assert "open_target" in kinds
    match = [n for n in needs if n["kind"] == "open_target"][0]
    assert match["target_id"] == tg["id"]


def test_weak_plan_cited_only_when_not_already_flagged_stale(rn_db):
    p = db.create_project("CR1 weak", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="weak", freshness_status="current")
    _fold("c1", n["id"])
    plan = {"decisions": [{"decision": "x", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    needs = research_needs.for_project(pid)
    assert len(needs) == 1 and needs[0]["kind"] == "weak_plan_cited" and needs[0]["claim_id"] == "c1"


def test_rejected_and_superseded_claims_never_produce_a_need(rn_db):
    p = db.create_project("CR1 rejected", "brief")
    pid = p["id"]
    _claim(pid, "c1", status="rejected", freshness_status="stale", freshness_class="rates_pricing")
    _claim(pid, "c2", status="superseded", strength="weak")
    _tension(pid, "t1", "c1")
    assert research_needs.for_project(pid) == []


def test_needs_are_capped_by_limit_after_priority_sort(rn_db):
    p = db.create_project("CR1 limit", "brief")
    pid = p["id"]
    for i in range(5):
        cid = f"c{i}"
        _claim(pid, cid)
        _tension(pid, f"t{i}", cid)
    needs = research_needs.for_project(pid, limit=2)
    assert len(needs) == 2


# ------------------------------------------------------------- API + CLI surfaces


def test_api_research_needs_and_plan_impact_routes(rn_db, monkeypatch):
    from fastapi.testclient import TestClient
    from neurosearch import api
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "app_token", "")
    p = db.create_project("api needs", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    client = TestClient(api.app)

    r = client.get(f"/api/projects/{pid}/research-needs")
    assert r.status_code == 200, r.text
    assert [n["claim_id"] for n in r.json()["needs"]] == ["c1"]
    assert client.get("/api/projects/nope/research-needs").status_code == 404

    r2 = client.get(f"/api/projects/{pid}/plan/impact", params={"claim_id": "c1"})
    assert r2.status_code == 200 and r2.json()["known"] is False   # no plan yet
    assert client.get(f"/api/projects/{pid}/plan/impact").status_code == 400   # neither claim_id nor tension_id


def test_cli_needs_and_plan_impact(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli needs", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().commit()

    r = CliRunner().invoke(app, ["project", "needs", pid])
    assert r.exit_code == 0, r.output
    assert "[disagreement]" in r.output

    r2 = CliRunner().invoke(app, ["project", "plan-impact", pid, "--claim", "c1"])
    assert r2.exit_code == 0, r2.output
    assert "unknown: no plan yet" in r2.output


# ------------------------------------------------------------- Morning Report line


def test_morning_report_shows_research_needs_count_only_when_nonzero(rn_db, monkeypatch):
    from neurosearch import nightly, report, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p = db.create_project("morning needs", "brief")
    pid = p["id"]
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    r = nightly.run()
    window_ts = (r["ts"] + time.time()) / 2
    db.connect().execute(
        "INSERT INTO project_notes (project_id, content, citations, created_at, status) VALUES (?,?,?,?,?)",
        (pid, "a suggested finding", "[]", window_ts, "suggested"))
    db.connect().commit()

    rep = report.for_envelope(r["envelope_id"])
    assert rep["projects"][0]["research_needs_count"] == 1
    text = report.render_text(rep)
    assert "1 thing(s) may need fresh evidence" in text


# ------------------------------------------------------------- CR2: due policy


def _target(project_id, tid, question, sufficiency="corroborative", status="open"):
    db.connect().execute(
        "INSERT INTO project_evidence_targets (id, project_id, question, sufficiency, status, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?)", (tid, project_id, question, sufficiency, status, db.now(), db.now()))
    db.connect().commit()


def test_due_categories_read_the_needs_own_recorded_fields(rn_db):
    p = db.create_project("CR2 category", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c_stale", freshness_status="stale", freshness_class="rates_pricing")
    _fold("c_stale", n["id"])
    plan = {"first_steps": [{"action": "x", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    _claim(pid, "c_hi")
    _tension(pid, "t_hi", "c_hi", kind="CONTRADICTION")
    db.connect().execute("UPDATE research_tensions SET impact='high' WHERE id='t_hi'")
    _claim(pid, "c_lo")
    _tension(pid, "t_lo", "c_lo", kind="NOVEL")
    db.connect().execute("UPDATE research_tensions SET impact='low' WHERE id='t_lo'")
    _target(pid, "tg_gov", "governing q?", sufficiency="governing")
    _target(pid, "tg_cor", "corroborative q?", sufficiency="corroborative")
    db.connect().commit()

    due = research_needs.due_tonight(pid)
    by_key = {(d["kind"], d.get("claim_id") or d.get("target_id")): d["due_category"] for d in due}
    assert by_key[("plan_impact_stale", "c_stale")] == "critical"
    assert by_key[("disagreement", "c_hi")] == "critical"
    assert by_key[("disagreement", "c_lo")] == "worth_checking"
    assert by_key[("open_target", "tg_gov")] == "worth_checking"
    assert by_key[("open_target", "tg_cor")] == "low"
    # ranked: every critical before every worth_checking before every low
    cats = [d["due_category"] for d in due]
    assert cats == sorted(cats, key=lambda c: {"critical": 0, "worth_checking": 1, "low": 2}[c])


def test_due_estimates_cost_from_a_real_untapped_candidate_when_one_exists(rn_db):
    from neurosearch import candidates as cand_mod
    p = db.create_project("CR2 cost", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    # a candidate this need's routing can point at: same creator/class the claim's topic would route through --
    # simplest reliable path is to monkeypatch where_to_look's rows directly rather than fabricate a full yield history.
    import neurosearch.research_needs as rn
    orig_route = rn._route
    rn._route = lambda *a, **k: [{"creator": "acme channel", "untapped": 3, "why": ["x"]}]
    cid = db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, creator, duration, first_seen_at, last_seen_at, availability) "
        "VALUES ('cand1','youtube','e1','u1','acme channel',1200,?,?, 'available')", (db.now(), db.now())).lastrowid
    db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                         (pid, "cand1", "available", db.now(), db.now()))
    db.connect().commit()
    try:
        due = research_needs.due_tonight(pid)
    finally:
        rn._route = orig_route
    assert due and "acme channel" in due[0]["cost_basis"] and due[0]["estimated_cost_usd"] > 0


def test_due_skips_a_need_checked_recently_but_resurfaces_after_the_ttl(rn_db):
    p = db.create_project("CR2 ttl", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    first = research_needs.due_tonight(pid)
    assert len(first) == 1
    again = research_needs.due_tonight(pid)
    assert again == []   # recorded in kv, within the TTL

    key = f"disagreement:c1"
    db.kv_set(f"research:checked:{key}", __import__("json").dumps({"ts": 0.0, "category": "critical"}))   # simulate an expired check
    later = research_needs.due_tonight(pid)
    assert len(later) == 1


# ------------------------------------------------------------- LP2: plan_narrative.explain


def test_explain_passes_through_unknown_from_lp1(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP2 unknown", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    r = plan_narrative.explain(pid, claim_id="c1")
    assert r == {"known": False, "items": [], "reason": "no plan yet"}


def test_explain_names_the_step_and_the_freshness_condition(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP2 stale", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim under review")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "buy the thing", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    r = plan_narrative.explain(pid, claim_id="c1")
    assert r["known"] is True
    why = r["items"][0]["why"]
    assert "buy the thing" in why and "the claim under review" in why and "stale" in why and "directly relies" in why


def test_explain_says_possible_relation_for_a_superseded_claim(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP2 merged", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "old", strength="weak")
    _claim(pid, "survivor")
    db.connect().execute("UPDATE project_claims SET superseded_by=? WHERE id=?", ("survivor", "old"))
    db.connect().commit()
    _fold("old", n["id"])
    plan = {"tools": [{"need": "a tool", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    r = plan_narrative.explain(pid, claim_id="survivor")
    assert "absorbed via merge" in r["items"][0]["why"]


# ------------------------------------------------------------- CLI: due, plan-impact --explain


def test_cli_due(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli due", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    _tension(pid, "t1", "c1")
    db.connect().execute("UPDATE research_tensions SET impact='high' WHERE id='t1'")
    db.connect().commit()
    r = CliRunner().invoke(app, ["project", "due", pid])
    assert r.exit_code == 0, r.output
    assert "[critical]" in r.output


def test_cli_plan_impact_explain_flag(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli explain", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))

    plain = CliRunner().invoke(app, ["project", "plan-impact", pid, "--claim", "c1"])
    assert "step one" in plain.output and "cites" not in plain.output

    explained = CliRunner().invoke(app, ["project", "plan-impact", pid, "--claim", "c1", "--explain"])
    assert explained.exit_code == 0, explained.output
    assert "cites the claim" in explained.output and "stale" in explained.output
