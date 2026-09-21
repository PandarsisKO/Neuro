"""L-51 (EXECUTION-LADDER.md Stage 7, P4 Review at Scale): the exception queue. Gate: a project with thousands of
proposals yields a short, defensible queue that still shows consequential disagreement. The "thousands" test
below is literal (2,000 proposed Claims); the "defensible" part is that every shown item names its reason and
its inspectable members; "still shows disagreement" is pinned by making the cap smaller than the number of
disagreeing Claims and asserting none of them are hidden. Also pinned: this module can never approve anything."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from neurosearch import db, review_queue


@pytest.fixture
def rq_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _claim(pid: str, cid: str, strength: str = "developing", status: str = "proposed", created_at: float | None = None) -> None:
    t = created_at if created_at is not None else db.now()
    db.connect().execute(
        "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, freshness_class, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, pid, f"claim {cid}", "other", "topic", status, strength, "slow_changing", t, t))


def _tension(pid: str, tid: str, claim_id: str, kind: str = "CONTRADICTION", impact: str = "medium", status: str = "open") -> None:
    db.connect().execute(
        "INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, impact, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (tid, pid, kind, claim_id, "two sources disagree", status, impact, db.now(), db.now()))


def test_empty_project_yields_an_empty_honest_queue(rq_db):
    p = db.create_project("empty", "brief")
    q = review_queue.build(p["id"])
    assert q["queue"] == []
    assert q["counts"]["proposed_total"] == 0
    assert q["basis"]["auto_approve"] == "never"
    assert "novelty" in q["basis"]["signals_not_used"]


def test_a_well_supported_undisputed_unplanned_claim_is_not_in_the_queue(rq_db):
    p = db.create_project("quiet", "brief")
    _claim(p["id"], "c_strong", strength="strong")
    db.connect().commit()
    q = review_queue.build(p["id"])
    assert q["queue"] == []
    assert q["counts"]["proposed_total"] == 1 and q["counts"]["candidates"] == 0


def test_each_reason_is_real_and_named(rq_db):
    p = db.create_project("reasons", "brief")
    pid = p["id"]
    _claim(pid, "c_disagree", strength="strong")
    _tension(pid, "t1", "c_disagree")
    _claim(pid, "c_weak", strength="unsupported")
    _claim(pid, "c_dismissed_tension", strength="strong")
    _tension(pid, "t2", "c_dismissed_tension", status="dismissed")     # a closed tension is not disagreement
    _claim(pid, "c_stale_kind", strength="strong")
    _tension(pid, "t3", "c_stale_kind", kind="STALE")                   # STALE is not the disagreement kind L-50 uses
    db.connect().commit()

    q = review_queue.build(pid)
    by = {x["claim_id"]: x for x in q["queue"]}
    assert set(by) == {"c_disagree", "c_weak"}
    assert by["c_disagree"]["reasons"] == ["disagreement"]
    assert by["c_disagree"]["tensions"][0]["kind"] == "CONTRADICTION"
    assert by["c_weak"]["reasons"] == ["evidence_weak"]
    assert by["c_weak"]["strength"] == "unsupported"


def test_plan_impact_is_a_reason_when_a_folded_finding_is_cited(rq_db):
    p = db.create_project("planned", "brief")
    pid = p["id"]
    n_cited = db.add_project_note(pid, "the cited finding")
    n_other = db.add_project_note(pid, "an uncited finding")
    _claim(pid, "c_planned", strength="strong")
    _claim(pid, "c_unplanned", strength="strong")
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c_planned", n_cited["id"]))
    db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c_unplanned", n_other["id"]))
    db.connect().commit()
    # same F<n> numbering reasoning as tests/test_decision_impact.py: n_cited -> F1
    db.save_plan(pid, {"first_steps": [{"action": "do the thing", "evidence": ["F1"]}]}, db.project_snapshot(pid))

    q = review_queue.build(pid)
    assert [x["claim_id"] for x in q["queue"]] == ["c_planned"]
    assert q["queue"][0]["reasons"] == ["plan_impact"]
    assert q["queue"][0]["members"]["note_ids"] == [n_cited["id"]]      # inspectable: the finding behind it
    assert q["basis"]["plan_impact_known"] is True


def test_members_include_findings_folded_in_and_claims_merged_in(rq_db):
    p = db.create_project("members", "brief")
    pid = p["id"]
    n1 = db.add_project_note(pid, "finding one")
    n2 = db.add_project_note(pid, "finding two, says the same")
    _claim(pid, "c_rep", strength="weak")
    _claim(pid, "c_dup", strength="weak", status="superseded")
    db.connect().execute("UPDATE project_claims SET superseded_by='c_rep' WHERE id='c_dup'")
    for n in (n1, n2):
        db.connect().execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", ("c_rep", n["id"]))
    db.connect().commit()

    q = review_queue.build(pid)
    assert len(q["queue"]) == 1                                          # the superseded duplicate is not its own item
    m = q["queue"][0]["members"]
    assert m["note_ids"] == sorted([n1["id"], n2["id"]])
    assert m["merged_claim_ids"] == ["c_dup"]


def test_thousands_of_proposals_yield_a_short_queue_that_never_hides_disagreement(rq_db):
    """The gate, literally. 2,000 proposed Claims: 1,900 evidence-weak, 60 disagreeing, 40 quiet. With limit=25
    (smaller than the 60 disagreements) every disagreement is still shown, the cap applies only to the weak
    ones, and the counts say exactly what was hidden."""
    p = db.create_project("thousands", "brief")
    pid = p["id"]
    t0 = db.now()
    for i in range(1900):
        _claim(pid, f"w{i}", strength="weak", created_at=t0 + i)
    for i in range(60):
        _claim(pid, f"d{i}", strength="strong", created_at=t0 + 5000 + i)
        _tension(pid, f"t{i}", f"d{i}", impact="high" if i < 5 else "medium")
    for i in range(40):
        _claim(pid, f"q{i}", strength="strong", created_at=t0 + 9000 + i)
    db.connect().commit()

    q = review_queue.build(pid, limit=25)
    ids = [x["claim_id"] for x in q["queue"]]
    assert q["counts"]["proposed_total"] == 2000
    assert q["counts"]["candidates"] == 1960
    assert len(ids) == 60, "disagreement is never capped: all 60 shown, and the cap left no room for weak ones"
    assert all(i.startswith("d") for i in ids)
    assert ids[:5] == [f"d{i}" for i in range(5)], "high-impact tensions come first"
    # 2026-09-21: `evidence_dismissed` joined REASON_ORDER (a proposed Claim every one of whose supporting
    # findings has been dismissed). None of this fixture's notes are dismissed, so it is correctly 0 on both
    # sides — the counts are asserted whole on purpose, so a new reason has to be acknowledged here rather
    # than appearing silently.
    assert q["counts"]["by_reason"] == {"evidence_dismissed": 0, "disagreement": 60, "plan_impact": 0, "evidence_weak": 0}
    assert q["counts"]["not_shown"] == {"evidence_dismissed": 0, "disagreement": 0, "plan_impact": 0, "evidence_weak": 1900}
    assert q["counts"]["hidden_total"] == 1900

    q2 = review_queue.build(pid, limit=100)
    ids2 = [x["claim_id"] for x in q2["queue"]]
    assert len(ids2) == 100 and ids2[:60] == ids and all(i.startswith("w") for i in ids2[60:])
    assert q2["counts"]["not_shown"]["evidence_weak"] == 1860


def test_this_module_can_never_approve_anything(rq_db):
    """P4's rule: never auto-approve on confidence. Structural proof, same shape as L-15's promotion-boundary
    test: the module has no write of any kind and no reference to the one promotion door."""
    import ast
    import neurosearch.review_queue as rq
    src = Path(rq.__file__).read_text()
    tree = ast.parse(src)
    # strip every docstring/comment: the check is on CODE, and the module's own docstring is allowed to name
    # the door it never touches
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    assert "set_status" not in code
    assert "tx(" not in code and ".commit(" not in code
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b", code)


def test_api_route_serves_the_queue_read_only(rq_db, monkeypatch):
    from fastapi.testclient import TestClient
    from neurosearch import api
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "app_token", "")        # a developer .env token must not decide this test
    p = db.create_project("api", "brief")
    _claim(p["id"], "c_weak", strength="weak")
    db.connect().commit()
    client = TestClient(api.app)
    r = client.get(f"/api/projects/{p['id']}/claims/review-queue?limit=5")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["claim_id"] for x in body["queue"]] == ["c_weak"] and body["limit"] == 5
    assert db.connect().execute("SELECT status FROM project_claims WHERE id='c_weak'").fetchone()["status"] == "proposed"
    assert client.get("/api/projects/nope/claims/review-queue").status_code == 404


def test_cli_lists_the_queue_with_reasons(rq_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("cliq", "brief")
    _claim(p["id"], "c_d", strength="strong")
    _tension(p["id"], "t", "c_d", impact="high")
    _claim(p["id"], "c_w", strength="weak")
    db.connect().commit()
    r = CliRunner().invoke(app, ["project", "review-queue", p["id"]])
    assert r.exit_code == 0, r.output
    assert "2 to review out of 2 proposed" in r.output
    assert "[disagreement] claim c_d" in r.output and "tension: CONTRADICTION (high)" in r.output
    assert "[evidence_weak] claim c_w" in r.output
    assert r.output.index("c_d") < r.output.index("c_w")
