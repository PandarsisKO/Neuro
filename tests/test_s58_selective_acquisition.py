"""CR8b (mission section 12, HANDOFF.md 2026-09-16 "Execution -- CR8b shipped with Kyle's 9 corrections"):
selective automatic acquisition from an open Evidence Target with no Claim yet -- the exact case CR5's
request_refresh() declines. This does NOT duplicate CR5's candidate-selection logic: both CR5
(research_refresh.request_refresh) and CR8b (research_refresh.request_acquisition) go through the SAME shared
mechanism, knowledge.capture_best(), which is where the eligibility fixes (dismissed-candidate protection,
$0-vs-spend budget sequencing, bounded consideration pool) actually live. Nothing here spends real money:
fake_ai and a poisoned safe_fetch keep this file at $0, same discipline as test_m3_links.py /
test_cr1_lp0_lp1_research_needs.py."""
from __future__ import annotations

import pytest

from neurosearch import candidates, claims as claims_mod, db, knowledge, research_refresh
from neurosearch.config import settings


@pytest.fixture
def s58_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "cr8b_enabled", True)
    from neurosearch import safe_fetch
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
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


def _candidate_row(cid, creator, title, duration=600, project_id=None, state="available", description=None):
    db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, title, description, creator, duration, first_seen_at, last_seen_at, availability) "
        "VALUES (?,?,?,?,?,?,?,?,?,?, 'available')",
        (cid, "youtube", cid, f"u/{cid}", title, description, creator, duration, db.now(), db.now()))
    if project_id:
        db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                             (project_id, cid, state, db.now(), db.now()))
    db.connect().commit()


def _open_target(pid, question="acme pricing rollout issues explained for Q1 customers", claim_id=None):
    tg = knowledge.add_target(pid, question, claim_id=claim_id)
    return tg


def _linked(pid, tg, cid, creator="acme channel", title=None):
    """A real open target with a real candidate linked to it via the actual $0 deterministic linking machinery
    (knowledge.pursue -> candidates.link), not a hand-inserted candidate_links row."""
    _candidate_row(cid, creator, title or tg["question"], project_id=pid)
    knowledge.pursue(tg["id"], external=False)
    return cid


# ------------------------------------------------------------- 1: happy path, real pursue()-driven link


def test_open_target_with_one_strong_linked_candidate_is_acquired(s58_db):
    p = db.create_project("CR8b happy", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand1")
    links = candidates.links_for(pid, "evidence_target", tg["id"])
    assert links and links[0]["candidate_id"] == "cand1"

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is True
    assert len(r["capture"]) == 1 and r["capture"][0]["candidate_id"] == "cand1"


# ------------------------------------------------------------- 2: no link at all -> nothing to acquire


def test_no_linked_candidate_means_nothing_started(s58_db):
    p = db.create_project("CR8b nolink", "brief")
    pid = p["id"]
    tg = _open_target(pid, question="a completely unrelated open question about zebras")
    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is False


# ------------------------------------------------------------- 3: dismissed candidate (Gap A) is never captured


def test_dismissed_candidate_is_skipped_not_captured(s58_db):
    p = db.create_project("CR8b dismissed", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand2")
    candidates.mark(pid, ["cand2"], "user_dismissed", "not useful")
    assert candidates.links_for(pid, "evidence_target", tg["id"])[0]["state"] == "open"

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is False
    state_after = db.row_to_dict(db.connect().execute(
        "SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?", ("cand2", pid)).fetchone())
    assert state_after["state"] == "user_dismissed"
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='ingest_url'").fetchone()["n"] == 0


# ------------------------------------------------------------- 4: already-acquired candidate is never re-captured


def test_already_acquired_candidate_is_not_recaptured(s58_db):
    p = db.create_project("CR8b already", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand3")
    candidates.mark(pid, ["cand3"], "acquired", "acquired earlier by another path")

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is False
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='ingest_url'").fetchone()["n"] == 0


# ------------------------------------------------------------- 5: closed target -> nothing happens, capture_best never called


def test_closed_target_never_reaches_capture_best(s58_db, monkeypatch):
    p = db.create_project("CR8b closed", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand4")
    knowledge.set_target_status(tg["id"], "closed_by_user")

    def _fail(*a, **k):
        raise AssertionError("capture_best must not be called for a closed target")
    monkeypatch.setattr(knowledge, "capture_best", _fail)

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is False and "no longer open" in r["reason"]


# ------------------------------------------------------------- 6/7: capture_best's own per-candidate loop reads live state


def test_capture_best_reads_live_state_not_a_snapshot_taken_before_the_loop(s58_db):
    """Correction #5: capture_best() must re-read candidate_projects.state fresh inside its loop, not trust
    whatever links_for() (or an earlier read) returned. Dismiss the candidate strictly AFTER the target/links
    already exist, then call capture_best directly -- it must still skip it."""
    p = db.create_project("CR8b live-read", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand5")
    links_before = candidates.links_for(pid, "evidence_target", tg["id"])
    assert links_before
    candidates.mark(pid, ["cand5"], "user_dismissed", "changed my mind")

    out = knowledge.capture_best(pid, tg["id"], n=1)
    assert out["started"] == []
    assert out["skipped"] and out["skipped"][0]["candidate_id"] == "cand5" and out["skipped"][0]["why"] == "user_dismissed"


# ------------------------------------------------------------- 8: two qualifying candidates, n=1 -> exactly one


def test_two_qualifying_candidates_yields_exactly_one_acquisition(s58_db):
    p = db.create_project("CR8b two", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _candidate_row("cand6", "acme channel", tg["question"], project_id=pid)
    _candidate_row("cand7", "acme channel", tg["question"] + " part two", project_id=pid)
    knowledge.pursue(tg["id"], external=False)
    links = candidates.links_for(pid, "evidence_target", tg["id"], limit=50)
    assert len({l["candidate_id"] for l in links} & {"cand6", "cand7"}) == 2

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is True and len(r["capture"]) == 1
    picked = r["capture"][0]["candidate_id"]
    other = "cand7" if picked == "cand6" else "cand6"
    other_state = db.row_to_dict(db.connect().execute(
        "SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?", (other, pid)).fetchone())
    assert other_state["state"] == "available"
    assert db.connect().execute("SELECT state FROM candidate_links WHERE candidate_id=? AND ref_id=?", (other, tg["id"])).fetchone()["state"] == "open"


# ------------------------------------------------------------- 9: cross-project isolation


def test_cross_project_isolation_dismissal_in_one_project_does_not_block_another(s58_db):
    pA = db.create_project("CR8b projA", "brief")["id"]
    pB = db.create_project("CR8b projB", "brief")["id"]
    db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, title, creator, duration, first_seen_at, last_seen_at, availability) "
        "VALUES (?,?,?,?,?,?,?,?,?, 'available')",
        ("cand8", "youtube", "cand8", "u/cand8", "acme pricing rollout issues explained for Q1 customers", "acme channel", 600, db.now(), db.now()))
    db.connect().commit()
    for pid in (pA, pB):
        db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                             (pid, "cand8", "available", db.now(), db.now()))
    db.connect().commit()
    tgA = _open_target(pA)
    tgB = _open_target(pB)
    knowledge.pursue(tgA["id"], external=False)
    knowledge.pursue(tgB["id"], external=False)
    candidates.mark(pA, ["cand8"], "user_dismissed", "not for project A")

    rA = research_refresh.request_acquisition(pA, need={"kind": "open_target", "target_id": tgA["id"]})
    rB = research_refresh.request_acquisition(pB, need={"kind": "open_target", "target_id": tgB["id"]})
    assert rA["started"] is False
    assert rB["started"] is True and rB["capture"][0]["candidate_id"] == "cand8"


# ------------------------------------------------------------- 11: no automatic Claim acceptance


def test_no_automatic_claim_promotion(s58_db, monkeypatch):
    p = db.create_project("CR8b noclaim-touch", "brief")
    pid = p["id"]
    _claim(pid, "c1", status="proposed")
    tg = _open_target(pid)
    _linked(pid, tg, "cand9")

    def _fail(*a, **k):
        raise AssertionError("request_acquisition must never call claims.set_status")
    monkeypatch.setattr(claims_mod, "set_status", _fail)

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is True
    row = db.row_to_dict(db.connect().execute("SELECT status FROM project_claims WHERE id=?", ("c1",)).fetchone())
    assert row["status"] == "proposed"


# ------------------------------------------------------------- 12: same job kind as every other acquisition path


def test_enqueued_job_is_the_normal_ingest_url_kind(s58_db):
    p = db.create_project("CR8b jobkind", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand10")
    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is True
    item = r["capture"][0]
    if item["how"] == "job":
        job = db.get_job(item["job_id"])
        assert job["kind"] == "ingest_url"
        assert job["payload"]["candidate_id"] == "cand10"


# ------------------------------------------------------------- 13: idempotent repeat


def test_repeated_call_on_unchanged_state_does_not_double_acquire(s58_db):
    p = db.create_project("CR8b idempotent", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand11")

    r1 = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r1["started"] is True
    n_jobs_after_first = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='ingest_url'").fetchone()["n"]

    r2 = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r2["started"] is False
    n_jobs_after_second = db.connect().execute("SELECT COUNT(*) n FROM jobs WHERE kind='ingest_url'").fetchone()["n"]
    assert n_jobs_after_second == n_jobs_after_first


# ------------------------------------------------------------- 15: provenance reconstructs end to end


def test_provenance_reconstructs_from_candidate_to_job(s58_db):
    p = db.create_project("CR8b provenance", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand12")

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is True
    item = r["capture"][0]
    link_row = db.row_to_dict(db.connect().execute(
        "SELECT * FROM candidate_links WHERE candidate_id=? AND kind='evidence_target' AND ref_id=?", ("cand12", tg["id"])).fetchone())
    assert link_row is not None and link_row["relevance"] is not None
    tg_row = knowledge.get_target(tg["id"])
    assert tg_row["question"]
    if item["how"] == "job":
        job = db.get_job(item["job_id"])
        assert job["payload"]["candidate_id"] == "cand12"
        assert "evidence for an open question" in job["payload"]["reason"]


# ------------------------------------------------------------- CLI


def test_cli_acquire_evaluate(s58_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("CR8b cli", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "cand13")

    r = CliRunner().invoke(app, ["project", "acquire-evaluate", pid, "--target", tg["id"]])
    assert r.exit_code == 0, r.output
    assert "acquisition started for target" in r.output


def test_cli_acquire_evaluate_reports_nothing_started(s58_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    p = db.create_project("CR8b cli-nothing", "brief")
    pid = p["id"]
    r = CliRunner().invoke(app, ["project", "acquire-evaluate", pid])
    assert r.exit_code == 1
    assert "nothing due" in r.output


# ------------------------------------------------------------- nightly integration


def test_cr8b_off_by_default_in_nightly(s58_db, monkeypatch):
    from neurosearch import nightly, t4
    monkeypatch.setattr(settings, "cr8b_enabled", False)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p = db.create_project("CR8b nightly-off", "brief")
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    db.connect().commit()
    r = nightly.run()
    assert r["cr8b_acquisition"] is None


def test_cr8b_nightly_pass_starts_due_open_target_needs(s58_db, monkeypatch):
    from neurosearch import nightly, t4
    monkeypatch.setattr(settings, "cr8b_enabled", True)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p = db.create_project("CR8b nightly-on", "brief")
    pid = p["id"]
    sid = db.upsert_source(platform="manual", external_id="s1", url="manual://s1", title="s1", status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    db.connect().commit()
    tg = _open_target(pid)
    _linked(pid, tg, "cand14")

    r = nightly.run()
    cr8b = r["cr8b_acquisition"]
    assert cr8b["ran"] is True and len(cr8b["requested"]) == 1 and cr8b["requested"][0]["project_id"] == pid


def test_cr8b_nightly_one_projects_failure_does_not_abort_the_rest(s58_db, monkeypatch):
    from neurosearch import nightly, research_needs as rn_mod, t4
    monkeypatch.setattr(settings, "cr8b_enabled", True)
    monkeypatch.setattr(settings, "t4_nightly_budget", 2.0)
    monkeypatch.setattr(settings, "t4_nightly_hour", 0)
    monkeypatch.setattr(t4, "_source_estimate", lambda pid, sid, **k: 0.01)
    p_bad = db.create_project("CR8b nightly-bad", "brief")
    p_good = db.create_project("CR8b nightly-good", "brief")
    for p in (p_bad, p_good):
        sid = db.upsert_source(platform="manual", external_id=f"s-{p['id']}", url=f"manual://{p['id']}", title="s", status="ready")["id"]
        db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (p["id"], sid))
    db.connect().commit()
    tg = _open_target(p_good["id"])
    _linked(p_good["id"], tg, "cand15")

    real_due_tonight = rn_mod.due_tonight

    def _flaky(project_id, needs=None):
        if project_id == p_bad["id"]:
            raise RuntimeError("boom")
        return real_due_tonight(project_id, needs)
    monkeypatch.setattr(rn_mod, "due_tonight", _flaky)

    r = nightly.run()
    cr8b = r["cr8b_acquisition"]
    assert cr8b["ran"] is True
    assert any(x["project_id"] == p_good["id"] for x in cr8b["requested"])


# ------------------------------------------------------------- correction #9: A-F


def test_A_library_reuse_attaches_despite_exhausted_budget(s58_db, monkeypatch):
    """An already-ready Library source reuse must succeed even when the configured budget is fully exhausted --
    that specific operation is genuinely $0 and must never be blocked by a depleted spend ledger."""
    from neurosearch import usage
    p = db.create_project("CR8b A", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _candidate_row("candA", "acme channel", tg["question"], project_id=pid)
    knowledge.pursue(tg["id"], external=False)
    src = db.upsert_source(platform="youtube", external_id="candA", url="u/candA", title=tg["question"], status="ready")
    db.connect().execute("UPDATE candidates SET source_id=? WHERE id=?", (src["id"], "candA"))
    db.connect().commit()
    usage.record("findings", "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    monkeypatch.setattr(settings, "daily_budget", 0.01)
    ok, reason, _ = usage.check()
    assert ok is False

    out = knowledge.capture_best(pid, tg["id"], n=1)
    assert out["started"] and out["started"][0]["candidate_id"] == "candA" and out["started"][0]["how"] == "attached"


def test_B_spend_bearing_candidate_refused_when_budget_does_not_authorize(s58_db, monkeypatch):
    """A candidate requiring a real ingest_url enqueue (no ready source) is refused, not started, when the
    existing budget does not currently authorize it."""
    from neurosearch import usage
    p = db.create_project("CR8b B", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "candB")
    usage.record("findings", "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    monkeypatch.setattr(settings, "daily_budget", 0.01)
    ok, _, _ = usage.check()
    assert ok is False

    out = knowledge.capture_best(pid, tg["id"], n=1)
    assert out["started"] == []
    assert out["skipped"] and out["skipped"][0]["candidate_id"] == "candB" and out["skipped"][0]["why"] == "budget"


def test_C_budget_refusal_leaves_candidate_completely_untouched(s58_db, monkeypatch):
    from neurosearch import usage
    p = db.create_project("CR8b C", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "candC")
    usage.record("findings", "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0)
    monkeypatch.setattr(settings, "daily_budget", 0.01)

    before = db.row_to_dict(db.connect().execute(
        "SELECT state, reason, updated_at FROM candidate_projects WHERE candidate_id=? AND project_id=?", ("candC", pid)).fetchone())
    n_jobs_before = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]

    out = knowledge.capture_best(pid, tg["id"], n=1)
    assert out["started"] == [] and out["skipped"][0]["why"] == "budget"

    after = db.row_to_dict(db.connect().execute(
        "SELECT state, reason, updated_at FROM candidate_projects WHERE candidate_id=? AND project_id=?", ("candC", pid)).fetchone())
    n_jobs_after = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    assert before == after
    assert n_jobs_after == n_jobs_before
    assert db.connect().execute("SELECT state FROM candidate_links WHERE candidate_id=?", ("candC",)).fetchone()["state"] == "open"


def test_D_cr5_and_cr8b_both_go_through_the_same_capture_best(s58_db, monkeypatch):
    """CR5's request_refresh() and CR8b's request_acquisition() must both call the ONE shared
    knowledge.capture_best() -- never a second, independently-drifting implementation."""
    p = db.create_project("CR8b D", "brief")
    pid = p["id"]
    calls = []
    real_capture_best = knowledge.capture_best

    def _spy(project_id, target_id, n=3):
        calls.append((project_id, target_id, n))
        return real_capture_best(project_id, target_id, n=n)
    monkeypatch.setattr(knowledge, "capture_best", _spy)

    tg1 = _open_target(pid, question="acme pricing rollout issues explained for Q1 customers")
    _linked(pid, tg1, "candD1")
    research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg1["id"]})

    _claim(pid, "cD", text="acme pricing changed recently for enterprise customers")
    _candidate_row("candD2", "acme channel", "acme pricing changed recently for enterprise customers", project_id=pid)
    need = {"kind": "disagreement", "claim_id": "cD", "question": "acme pricing changed recently for enterprise customers"}
    research_refresh.request_refresh(pid, need=need)

    assert len(calls) == 2


def test_E_autonomous_request_acquisition_never_captures_a_dismissed_candidate(s58_db):
    """End-to-end: dismiss a candidate linked to an open target, run request_acquisition, assert nothing was
    acquired and the dismissed state is unchanged."""
    p = db.create_project("CR8b E", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "candE")
    candidates.dismiss(pid, "candE", "not relevant to this project")

    r = research_refresh.request_acquisition(pid, need={"kind": "open_target", "target_id": tg["id"]})
    assert r["started"] is False
    state = db.row_to_dict(db.connect().execute(
        "SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?", ("candE", pid)).fetchone())
    assert state["state"] == "user_dismissed"


def test_F_explicit_manual_recapture_still_works_on_a_previously_dismissed_candidate(s58_db):
    """The deliberate single-candidate user override (candidates.capture(), simulating POST
    /api/candidates/{id}/acquire) must still succeed on a previously-user_dismissed candidate -- proving
    candidates.capture() itself was NOT modified to add a dismissed-check (only capture_best() was)."""
    p = db.create_project("CR8b F", "brief")
    pid = p["id"]
    tg = _open_target(pid)
    _linked(pid, tg, "candF")
    candidates.dismiss(pid, "candF", "changed my mind, dismissing")

    result = candidates.capture("candF", pid, reason="user explicitly recaptured this")
    assert result["ok"] is True
    state = db.row_to_dict(db.connect().execute(
        "SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?", ("candF", pid)).fetchone())
    assert state["state"] == "acquired"
