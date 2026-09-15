"""L-40 (EXECUTION-LADDER.md Stage 5, P1B "Tonight" UI, rulings section 3/4): Now / Tonight / Overnight batch on
the stale-rebuild action, on top of L-20's not_before backend. What these pin: the server owns the definition of
"tonight"; a scheduled job is its own visible state (never "retry wait"); the words the UI shows are host-honest
("eligible from", never "runs at"); cancel and run-now only ever touch the user's own schedule; and the frontend
routes each choice at a route that exists, exposing no scheduler internals."""
from __future__ import annotations

import re
import time

import pytest

from neurosearch import db, findings, ingest, jobs, staleness


@pytest.fixture
def p1b_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    monkeypatch.setattr(settings, "app_token", "")
    monkeypatch.setattr(settings, "t4_nightly_hour", 2)
    db._local.conn = None
    db.init_db()
    jobs.CRASH_AT.clear()
    yield
    db.close_thread_connection()


def _stale_project():
    p = db.create_project("P1B", "hosting")
    text = "0:05 provider0 pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks"
    r = ingest.ingest_text("Hosting talk", text, project_id=p["id"])
    findings.suggest_for_source(p["id"], r["source_id"], force=True)
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (p["id"], r["source_id"]))
    db.connect().commit()
    db.update_project(p["id"], brief="hosting and email deliverability")
    return p, r["source_id"]


def _client():
    from fastapi.testclient import TestClient
    from neurosearch import api
    return TestClient(api.app)


def test_next_tonight_is_the_next_occurrence_of_the_nightly_hour_on_the_host_clock(p1b_db):
    # 01:00 local today -> tonight is 02:00 today; 03:00 local -> 02:00 tomorrow
    lt = time.localtime()
    one_am = time.mktime(time.struct_time((lt.tm_year, lt.tm_mon, lt.tm_mday, 1, 0, 0, 0, 0, -1)))
    three_am = one_am + 2 * 3600
    assert staleness.next_tonight(one_am) == one_am + 3600
    assert staleness.next_tonight(three_am) == one_am + 3600 + 86400
    assert staleness.next_tonight() > time.time()


def test_when_tonight_schedules_and_answers_in_host_honest_words(p1b_db):
    p, sid = _stale_project()
    c = _client()
    r = c.post(f"/api/projects/{p['id']}/rebuild-stale", json={"what": ["findings"], "source_ids": [sid], "transport": "interactive", "when": "tonight"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queued"] == 1
    row = db.get_job(body["job_ids"][0])
    assert row["wait_reason"] == "scheduled" and row["not_before"] == pytest.approx(staleness.next_tonight(), abs=2)
    assert db.derived_status(row) == "scheduled", "a caller's schedule is its own state, not a retry wait"
    sch = body["schedule"]
    assert re.fullmatch(r"\d\d:\d\d", sch["eligible_from"]) and sch["day"] == "tonight"
    assert "must be awake" in sch["host_note"] and "not at the exact minute" in sch["host_note"]
    for word in ("not_before", "lease", "dedupe"):
        assert word not in sch["host_note"]

    r = c.post(f"/api/projects/{p['id']}/rebuild-stale", json={"what": ["findings"], "source_ids": [sid], "when": "someday"})
    assert r.status_code == 400


def test_scheduled_read_reports_pending_and_what_happened(p1b_db):
    p, sid = _stale_project()
    c = _client()
    c.post(f"/api/projects/{p['id']}/rebuild-stale", json={"what": ["findings"], "source_ids": [sid], "transport": "batch", "when": "tonight"})
    sc = c.get(f"/api/projects/{p['id']}/scheduled").json()
    assert sc["pending"]["jobs"] == 1 and sc["pending"]["sources"] == 1 and sc["pending"]["waiting"] == 1
    assert sc["pending"]["transport"] == "batch" and sc["pending"]["schedule"]["day"] == "tonight"
    assert sc["recent"] == {"done": 0, "done_sources": 0, "failed": 0, "missed_window": 0, "cancelled": 0, "spend_usd": 0.0, "needs_attention": False}

    # a scheduled job whose deadline already passed is cancelled by jobs.execute() (L-20) and shows as a missed window
    j = db.create_job("reembed", {"project_id": p["id"], "_deadline": db.now() - 10}, not_before=db.now() - 100)
    claimed = db.claim_job(("reembed",), worker_id="w")
    assert jobs.execute(claimed, "w") == "cancelled"
    sc = c.get(f"/api/projects/{p['id']}/scheduled").json()
    assert sc["recent"]["missed_window"] == 1 and sc["recent"]["needs_attention"] is True


def test_cancel_scheduled_touches_only_the_users_own_schedule(p1b_db):
    p, sid = _stale_project()
    c = _client()
    c.post(f"/api/projects/{p['id']}/rebuild-stale", json={"what": ["findings"], "source_ids": [sid], "when": "tonight"})
    budget_job = db.create_job("reembed", {"project_id": p["id"]})
    db.requeue_job(budget_job["id"], delay=3600, message="paused: daily budget reached", wait_reason="budget")
    r = c.post(f"/api/projects/{p['id']}/scheduled/cancel").json()
    assert r["cancelled"] == 1
    assert db.get_job(budget_job["id"])["status"] == "queued", "a budget park is not the user's schedule and must survive"
    assert c.get(f"/api/projects/{p['id']}/scheduled").json()["pending"]["jobs"] == 0


def test_run_now_clears_only_a_scheduled_wait_and_makes_it_claimable(p1b_db):
    p, sid = _stale_project()
    c = _client()
    jid = c.post(f"/api/projects/{p['id']}/rebuild-stale", json={"what": ["findings"], "source_ids": [sid], "when": "tonight"}).json()["job_ids"][0]
    assert db.claim_job(("suggest_findings",), worker_id="w") is None
    r = c.post(f"/api/jobs/{jid}/run-now")
    assert r.status_code == 200, r.text
    row = db.get_job(jid)
    assert row["not_before"] is None and row["wait_reason"] is None and row["bumped_at"]
    assert any(e["event_type"] == "scheduled_run_now" for e in db.job_events(jid))
    assert db.claim_job(("suggest_findings",), worker_id="w")["id"] == jid

    budget_job = db.create_job("reembed", {"project_id": p["id"]})
    db.requeue_job(budget_job["id"], delay=3600, message="paused: daily budget reached", wait_reason="budget")
    assert c.post(f"/api/jobs/{budget_job['id']}/run-now").status_code == 409, "never pulls a budget/provider park forward"
    assert c.post("/api/jobs/nope/run-now").status_code == 404


def test_the_ui_offers_now_tonight_and_overnight_and_hides_scheduler_internals(p1b_db):
    from neurosearch import api
    web = __import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web"
    html = __import__("tests.frontend_helpers", fromlist=["ui_source"]).ui_source(web)
    js = (web / "js" / "research.js").read_text()
    # the three choices, each routed at the one rebuild route with the server-owned "when"
    for mode in ("'tonight'", "'overnight'", "'api'", "'batch'"):
        assert f"rebuildTier('${{key}}', {mode})" in js
    assert "when: scheduled ? 'tonight' : 'now'" in js
    # progressive disclosure: one primary per tier, the rest behind "When…"
    assert 'class="small primary"' in js and ">When…</button>" in js and 'class="when-menu"' in js
    # the scheduled facts + the two safe controls, routed at routes that exist
    for path in ("/api/projects/{project_id}/scheduled", "/api/projects/{project_id}/scheduled/cancel", "/api/jobs/{job_id}/run-now"):
        assert any(getattr(r, "path", "") == path for r in api.app.routes), path
    assert "/scheduled/cancel" in js and "/run-now" in js and "scheduledBlock" in js
    # host honesty in the user-facing copy; no internals in the words the user reads
    assert "must be awake" in js and "not at the exact minute" in js
    # the L-40 copy specifically: everything from the When… menu through the scheduled block
    l40 = js[js.index("const whenMenu"):js.index("globalThis.acceptTier")]
    for internal in ("not_before", "dedupe", "lease ", "queue lease", "wait_reason"):
        assert internal not in re.sub(r"/\*.*?\*/|//[^\n]*", "", l40), internal
    # a scheduled job is labelled as such in the console, with its own action
    assert "scheduled: 'scheduled'" in js and "runNowJob(" in js
    assert 'name="neurosearch-ui-version" content="0.63.91"' in html
