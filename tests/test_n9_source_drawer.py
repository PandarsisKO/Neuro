"""S3 — the source drawer (0.45.0): one request per source returns everything it gave the project — measured value, its
findings by status with what used each, the Claims resting on it, where it shows up (Master Plan steps, chat answers) and
its staleness tier with the one-source actions. $0, no model call, and it never invents a use. (Sorts after test_n8.)"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_drawer_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, findings, ingest, jobs, knowledge, safe_fetch, sources_value as sv  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture  # noqa: E402

UI = Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "index.html"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _calls():
    return db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]


def test_the_drawer_shows_what_one_source_gave_and_where_it_shows_up(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    sid = ids["primary"]
    src = db.get_source(sid)
    db.save_plan(pid, {"phases": [{"title": "Financing", "tasks": [{"title": "Seller note standby", "evidence": ["F1"], "text": "Put the note on full standby."}]}],
                       "_evidence": {"F1": {"source_id": sid, "label": "SOP @ § 1", "timestamp": "§ 1", "url": src["url"]},
                                     "F2": {"source_id": ids["stale"], "label": "fees", "timestamp": "§ 1"}}}, "test")
    conv = db.create_conversation(pid, "Standby rules")
    db.save_message(conv["id"], "assistant", "The note must be on full standby [1].", citations=[{"n": 1, "source_id": sid, "title": src["title"], "timestamp": "§ 1"}])
    before = _calls()
    d = sv.digest(pid, sid)
    assert _calls() == before, "the drawer is a $0 surface"
    # identity + measured value + why it matters
    assert d["source"]["id"] == sid and d["source"]["title"] == src["title"]
    assert d["value"]["score"] > 0 and "strong Claim" in d["value"]["label"] and d["value"]["matters"] and not d["value"]["never_used"]
    # its findings, with what used each
    approved = d["findings"]["approved"]
    assert approved and d["findings_total"] == len(approved)
    assert any(f["used"]["plan"] and f["used"]["claim"] == "strong" and f["used"]["chat"] == 1 for f in approved)
    assert all(f["locator"] for f in approved)
    # the Claims resting on it
    assert d["claims"] and d["claims"][0]["strength"] == "strong" and d["claims"][0]["independent"] in (0, 1)
    # where it shows up — the plan step by its own title, and the chat answer by its conversation
    assert d["used_in"]["plan"]["uses"] and d["used_in"]["plan"]["uses"][0]["where"] == "Seller note standby"
    assert d["used_in"]["chat"] and d["used_in"]["chat"][0]["conversation"] == "Standby rules" and d["used_in"]["chat"][0]["locators"] == ["§ 1"]
    # a source the plan cites but never references in its body is NOT reported as used by the plan
    assert not sv.digest(pid, ids["stale"])["used_in"]["plan"]["uses"]
    # a source that gave nothing says so plainly rather than inventing a use
    quiet = sv.digest(pid, ids["secs"][0])
    assert quiet["value"]["label"] and not quiet["used_in"]["plan"]["uses"] and not quiet["used_in"]["chat"]
    assert api.api_source_digest(pid, sid)["value"]["score"] == d["value"]["score"]
    with pytest.raises(Exception):
        api.api_source_digest(pid, "no-such-source")


def test_the_drawer_carries_the_staleness_tier_and_the_reserve_findings(monkeypatch):
    p = db.create_project("Drawer", "hosting")
    r = ingest.ingest_text("Hosting talk", "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks", project_id=p["id"])
    sid = r["source_id"]
    findings.suggest_for_source(p["id"], sid, force=True)
    d = sv.digest(p["id"], sid)
    assert d["staleness"]["status"] == "current" and d["staleness"]["tier"] is None
    assert d["findings"]["suggested"] and "approved" not in d["findings"]
    # a brief change makes it stale, and the drawer names the tier the triage card would put it in
    db.update_project(p["id"], brief="hosting and email deliverability")
    d2 = sv.digest(p["id"], sid)
    assert d2["staleness"]["status"] == "stale" and d2["staleness"]["tier"] == "accept" and d2["staleness"]["reasons"] == ["brief changed"]
    # accepting from the drawer is the same durable acceptance the triage card writes
    api.api_staleness_accept(p["id"], api.AcceptIn(source_ids=[sid]))
    assert sv.digest(p["id"], sid)["staleness"]["status"] == "current_accepted"
    # reserve findings (D1) are shown in their own group, never mixed into approved
    db.replace_suggestions(p["id"], sid, [{"title": "Extra", "content": "an overflow finding", "citations": [], "importance": 1, "status": "reserve"}],
                           provenance={"input_hash": "x"})
    d3 = sv.digest(p["id"], sid)
    assert [f["title"] for f in d3["findings"]["reserve"]] == ["Extra"] and "approved" not in d3["findings"]


def test_the_drawer_is_reachable_and_its_actions_exist():
    html = UI.read_text()
    assert html.count("sourceDrawer(") >= 4          # defined + source card button + value line + findings group
    assert "askAboutSource(" in html and "state.attached.push(" in html
    routes = {r.path for r in api.app.routes if hasattr(r, "path")}
    for path in ("/api/projects/{project_id}/sources/{source_id}/digest", "/api/projects/{project_id}/rebuild-stale",
                 "/api/projects/{project_id}/staleness/accept", "/api/notes/{note_id}/status", "/api/projects/{project_id}/suggest"):
        assert path in routes, path
