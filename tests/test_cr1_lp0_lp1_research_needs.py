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


# ------------------------------------------------------------- LP3: plan_narrative.propose_updates


def test_propose_updates_writes_pending_lp3_rows_and_never_collides_with_the_planner_queue(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP3 propose", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    saved = db.save_plan(pid, plan, db.project_snapshot(pid))
    # a pending row from the OTHER (LLM) path, on the same plan, must survive an LP3 write and vice versa
    db.add_plan_updates(saved["id"], [{"section": "goal", "proposed": "planner says X", "reason": "llm"}])   # origin=None

    updates = plan_narrative.propose_updates(pid, claim_id="c1")
    assert len(updates) == 1 and updates[0]["origin"] == "lp3" and updates[0]["section"] == "first_steps.0"
    assert updates[0]["status"] == "pending"

    all_pending = [u for u in db.get_plan(saved["id"])["updates"] if u["status"] == "pending"]
    assert {u.get("origin") for u in all_pending} == {None, "lp3"}   # both queues intact

    # a SECOND lp3 propose call must clear only its own prior pending rows, never the planner's
    updates2 = plan_narrative.propose_updates(pid, claim_id="c1")
    assert len(updates2) == 1
    all_pending2 = [u for u in db.get_plan(saved["id"])["updates"] if u["status"] == "pending"]
    assert len([u for u in all_pending2 if u.get("origin") is None]) == 1
    assert len([u for u in all_pending2 if u.get("origin") == "lp3"]) == 1


def test_propose_updates_accepted_via_the_existing_route(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP3 accept", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="weak", text="the claim")
    _fold("c1", n["id"])
    plan = {"decisions": [{"decision": "d1", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    updates = plan_narrative.propose_updates(pid, claim_id="c1")
    row = db.set_update_status(updates[0]["id"], "accepted")
    assert row["status"] == "accepted"


def test_propose_updates_returns_nothing_when_lp1_cannot_resolve(rn_db):
    from neurosearch import plan_narrative
    p = db.create_project("LP3 unknown", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    assert plan_narrative.propose_updates(pid, claim_id="c1") == []


def test_cli_propose_updates(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli propose", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", freshness_status="stale", text="the claim")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    r = CliRunner().invoke(app, ["project", "propose-updates", pid, "--claim", "c1"])
    assert r.exit_code == 0, r.output
    assert "wrote 1 pending plan update(s)" in r.output


# ------------------------------------------------------------- CR5: research_refresh


def _candidate_row(cid, creator, title, duration=600, project_id=None, state="available"):
    db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, title, creator, duration, first_seen_at, last_seen_at, availability) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'available')", (cid, "youtube", cid, f"u/{cid}", title, creator, duration, db.now(), db.now()))
    if project_id:
        db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                             (project_id, cid, state, db.now(), db.now()))
    db.connect().commit()


def test_resolve_target_reuses_an_existing_open_target_for_the_claim(rn_db):
    from neurosearch import knowledge, research_refresh
    p = db.create_project("CR5 reuse", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    tg = knowledge.add_target(pid, "existing question", claim_id="c1")
    got = research_refresh._resolve_target(pid, {"kind": "disagreement", "claim_id": "c1"})
    assert got == tg["id"]


def test_resolve_target_creates_one_when_none_exists(rn_db):
    from neurosearch import knowledge, research_refresh
    p = db.create_project("CR5 create", "brief")
    pid = p["id"]
    _claim(pid, "c1", text="the claim text")
    tid = research_refresh._resolve_target(pid, {"kind": "disagreement", "claim_id": "c1", "question": "the claim text"})
    tg = knowledge.get_target(tid)
    assert tg["claim_id"] == "c1" and tg["origin"] == "research_needs"


def test_request_refresh_reports_when_nothing_is_due_under_cap(rn_db):
    from neurosearch import research_refresh
    p = db.create_project("CR5 nodue", "brief")
    r = research_refresh.request_refresh(p["id"], cap_usd=0.0001)
    assert r["started"] is False and "nothing due" in r["reason"]


def test_request_refresh_refuses_an_open_target_need_with_no_claim(rn_db):
    from neurosearch import research_refresh
    p = db.create_project("CR5 noclaim", "brief")
    need = {"kind": "open_target", "target_id": "tg1", "claim_id": None}
    r = research_refresh.request_refresh(p["id"], need=need)
    assert r["started"] is False and "no claim" in r["reason"]


def test_request_refresh_end_to_end_enqueues_the_real_ingest_job(rn_db):
    from neurosearch import jobs, research_refresh
    p = db.create_project("CR5 e2e", "brief")
    pid = p["id"]
    _claim(pid, "c1", text="acme pricing changed recently")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand1", "acme channel", "acme pricing update video", project_id=pid)

    need = {"kind": "disagreement", "claim_id": "c1", "question": "acme pricing changed recently", "text": "acme pricing changed recently"}
    r = research_refresh.request_refresh(pid, need=need)
    assert r["started"] is True and r["claim_id"] == "c1" and len(r["capture"]) == 1
    assert r["capture"][0]["how"] == "job"
    job = db.get_job(r["capture"][0]["job_id"])
    assert job["kind"] == "ingest_url" and job["payload"]["project_id"] == pid


def test_check_reports_unknown_before_a_refresh_was_requested(rn_db):
    from neurosearch import research_refresh
    p = db.create_project("CR5 unknown", "brief")
    pid = p["id"]
    _claim(pid, "c1")
    r = research_refresh.check(pid, "c1")
    assert r["known"] is False


def test_check_unchanged_is_an_honest_normal_outcome(rn_db):
    from neurosearch import research_refresh
    p = db.create_project("CR5 unchanged", "brief")
    pid = p["id"]
    _claim(pid, "c1", text="acme pricing changed recently")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand2", "acme channel", "acme pricing update video", project_id=pid)
    need = {"kind": "disagreement", "claim_id": "c1", "question": "acme pricing changed recently"}
    research_refresh.request_refresh(pid, need=need)

    r = research_refresh.check(pid, "c1")
    assert r["known"] is True and r["changed"] is False


def test_check_reports_changed_once_new_evidence_lands(rn_db):
    """CR5's own responsibility is the before/after comparison -- the findings/claims harvest that actually
    produces new evidence is the existing pipeline, already covered by its own tests, so this exercises the
    boundary directly: request a refresh (snapshotting "before"), then simulate what the harvest pipeline does
    when it succeeds (adds evidence, which triggers claims.assess), then confirm check() sees it."""
    from neurosearch import claims as claims_mod, research_refresh
    p = db.create_project("CR5 changed", "brief")
    pid = p["id"]
    _claim(pid, "c1", text="acme pricing changed recently", strength="unsupported")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand3", "acme channel", "acme pricing update video", project_id=pid)
    need = {"kind": "disagreement", "claim_id": "c1", "question": "acme pricing changed recently"}
    research_refresh.request_refresh(pid, need=need)

    sid = db.upsert_source(platform="youtube", external_id="src1", url="u/src1", title="acme pricing update video", status="ready")["id"]
    claims_mod.add_evidence("c1", sid, locator="0:10", relation="SUPPORTS")
    claims_mod.assess("c1")   # the harvest pipeline's own step, already tested elsewhere -- exercised directly here

    r = research_refresh.check(pid, "c1")
    assert r["known"] is True and r["changed"] is True
    assert r["before"]["strength"] == "unsupported" and r["after"]["strength"] != "unsupported"


# ------------------------------------------------------------- CLI: refresh-need, refresh-check


def test_cli_refresh_need_and_check(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli refresh", "brief")
    pid = p["id"]
    _claim(pid, "c1", text="acme pricing changed recently")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand4", "acme channel", "acme pricing update video", project_id=pid)

    r = CliRunner().invoke(app, ["project", "refresh-need", pid, "--claim", "c1"])
    assert r.exit_code == 0, r.output
    assert "refresh requested for claim c1" in r.output

    r2 = CliRunner().invoke(app, ["project", "refresh-check", pid, "--claim", "c1"])
    assert r2.exit_code == 0, r2.output
    assert "unchanged:" in r2.output


# ------------------------------------------------------------- CR6: nightly integration


def test_research_refresh_off_by_default_in_nightly(rn_db, monkeypatch):
    from neurosearch import nightly, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    assert settings.research_refresh_nightly_budget == 0
    p = db.create_project("CR6 off", "brief")
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    db.connect().commit()
    r = nightly.run()
    assert r["research_refresh"] is None


def test_research_refresh_requests_due_needs_under_its_own_cap(rn_db, monkeypatch):
    from neurosearch import nightly, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "research_refresh_nightly_budget", 5.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p = db.create_project("CR6 on", "brief")
    pid = p["id"]
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    _claim(pid, "c1", text="acme pricing changed recently")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand5", "acme channel", "acme pricing update video", project_id=pid)

    r = nightly.run()
    rr = r["research_refresh"]
    assert rr["ran"] is True and len(rr["requested"]) == 1 and rr["requested"][0]["claim_id"] == "c1"
    assert rr["spent_estimate"] > 0


def test_research_refresh_one_projects_failure_does_not_abort_the_rest(rn_db, monkeypatch):
    from neurosearch import nightly, research_needs, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "research_refresh_nightly_budget", 5.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p_bad = db.create_project("CR6 bad", "brief")
    p_good = db.create_project("CR6 good", "brief")
    for p in (p_bad, p_good):
        sid = db.upsert_source(platform="manual", external_id=f"s-{p['id']}", url=f"manual://{p['id']}", title="s1", status="ready")["id"]
        db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    _claim(p_good["id"], "cg", text="acme pricing changed recently")
    _tension(p_good["id"], "tg", "cg")
    db.connect().commit()
    _candidate_row("cand6", "acme channel", "acme pricing update video", project_id=p_good["id"])

    orig = research_needs.due_tonight
    def flaky(pid, *a, **k):
        if pid == p_bad["id"]:
            raise RuntimeError("boom")
        return orig(pid, *a, **k)
    monkeypatch.setattr(research_needs, "due_tonight", flaky)

    r = nightly.run()
    assert r["research_refresh"]["ran"] is True
    assert any(x["project_id"] == p_good["id"] for x in r["research_refresh"]["requested"])


def test_morning_report_shows_research_refresh_line_only_when_nonzero(rn_db, monkeypatch):
    from neurosearch import nightly, report, t4
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(settings, "research_refresh_nightly_budget", 5.0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p = db.create_project("CR6 report", "brief")
    pid = p["id"]
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    _claim(pid, "c1", text="acme pricing changed recently")
    _tension(pid, "t1", "c1")
    db.connect().commit()
    _candidate_row("cand7", "acme channel", "acme pricing update video", project_id=pid)

    r = nightly.run()
    rep = report.for_envelope(r["envelope_id"])
    assert rep["material_change"] is True
    text = report.render_text(rep)
    assert "Requested 1 research refresh(es) (CR6" in text


def test_cli_nightly_run_discloses_research_refresh_budget(rn_db, monkeypatch):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    p = db.create_project("cli cr6", "brief")
    db.connect().commit()
    r = CliRunner().invoke(app, ["nightly", "run", "--budget", "1", "--research-refresh-budget", "2", "--yes"])
    assert r.exit_code == 0, r.output
    assert "$2.00 for CR6 research refreshes" in r.output


# ------------------------------------------------------------- LP4: plan_state.derive


def test_plan_state_known_for_a_strong_current_cited_claim(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 known", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="strong", freshness_status="current")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert states["first_steps.0"]["state"] == "known"


def test_plan_state_uncertain_for_a_stale_cited_claim(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 uncertain", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="strong", freshness_status="stale", freshness_class="rates_pricing")
    _fold("c1", n["id"])
    plan = {"decisions": [{"decision": "d1", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert states["decisions.0"]["state"] == "uncertain"


def test_plan_state_monitored_beats_uncertain_when_disagreement_is_open(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 monitored", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="weak", freshness_status="stale", freshness_class="rates_pricing")
    _fold("c1", n["id"])
    _tension(pid, "t1", "c1")
    plan = {"tools": [{"need": "x", "tool": "y", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert states["tools.0"]["state"] == "monitored"


def test_plan_state_blocked_takes_precedence_over_evidence_state(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 blocked", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="strong", freshness_status="current")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "obtain business license", "evidence": ["F1"]}],
           "dependencies": [{"item": "business license", "blocking": True, "note": "needed first"}],
           "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert states["first_steps.0"]["state"] == "blocked"


def test_plan_state_chosen_and_assumed_from_basis_with_no_evidence_link(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 basis", "brief")
    pid = p["id"]
    plan = {"decisions": [{"decision": "d1", "basis": "user"}, {"decision": "d2", "basis": "estimate"}]}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert states["decisions.0"]["state"] == "chosen" and states["decisions.1"]["state"] == "assumed"


def test_plan_state_leaves_an_unresolvable_item_unclassified(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 unclassified", "brief")
    pid = p["id"]
    plan = {"first_steps": [{"action": "just do it"}]}   # no evidence, no basis
    db.save_plan(pid, plan, db.project_snapshot(pid))
    states = plan_state.derive(pid)
    assert "first_steps.0" not in states


def test_plan_state_no_plan_returns_empty(rn_db):
    from neurosearch import plan_state
    p = db.create_project("LP4 noplan", "brief")
    assert plan_state.derive(p["id"]) == {}


def test_plan_state_never_writes_anything(rn_db):
    import ast
    import inspect
    from neurosearch import plan_state
    tree = ast.parse(inspect.getsource(plan_state))
    code = ast.unparse(tree)
    assert "tx(" not in code and ".commit(" not in code
    assert not __import__("re").search(r"\b(INSERT|UPDATE|DELETE)\b", code)


def test_cli_plan_state(rn_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cli plan-state", "brief")
    pid = p["id"]
    n = db.add_project_note(pid, "finding")
    _claim(pid, "c1", strength="strong", freshness_status="current")
    _fold("c1", n["id"])
    plan = {"first_steps": [{"action": "step one", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": n["id"]}}}
    db.save_plan(pid, plan, db.project_snapshot(pid))
    r = CliRunner().invoke(app, ["project", "plan-state", pid])
    assert r.exit_code == 0, r.output
    assert "first_steps.0: known" in r.output
