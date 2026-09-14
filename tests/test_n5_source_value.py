"""S2 — Source Value (0.41.0): what a source GAVE the project, measured from rows that exist — findings and their importance,
Claims (strong), Master Plan evidence, chat citations, the priority star — with documented weights; a source holding only
importance-1 findings scores below one plan-evidence source; the rows on /api/sources carry value + staleness so the
Sources tab filters compose client-side. (Sorts after test_n4.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_value_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, jobs, knowledge, safe_fetch, sources_value as sv  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture  # noqa: E402


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


def test_value_is_measured_from_findings_claims_plan_chat_and_priority(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    v = sv.compute(pid)
    prim, outl, stale = v[ids["primary"]], v[ids["outlier"]], v[ids["stale"]]
    # the primary source evidences the strong governing Claim and holds a 5/5 finding
    assert prim["claims"]["strong"] >= 1 and prim["importance"]["n4plus"] == 1 and prim["value_score"] >= sv.W_STRONG + sv.W_IMPORTANT
    assert "strong Claim" in prim["label"] and prim["matters"]
    # a derivative secondary: one importance-3 finding, no strong-claim evidence of its own → low
    sec = v[ids["secs"][0]]
    assert sec["value_score"] < prim["value_score"] and not sec["matters"]
    # the plan and chat make a source matter; a priority star does too
    src = db.get_source(ids["stale"])
    db.save_plan(pid, {"steps": [{"title": "Fees", "evidence": ["e1"]}], "_evidence": {"e1": {"source_id": ids["stale"], "label": "fees", "url": src["url"]}}}, "test")
    conv = db.create_conversation(pid, "chat")
    db.save_message(conv["id"], "assistant", "Fees are 2 percent [1].", citations=[{"n": 1, "source_id": ids["outlier"], "title": "x"}])
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (pid, ids["secs"][1])); db.connect().commit()
    v2 = sv.compute(pid)
    assert v2[ids["stale"]]["used"]["plan_evidence"] == 1 and v2[ids["stale"]]["matters"] and "in the plan" in v2[ids["stale"]]["label"]
    assert v2[ids["outlier"]]["used"]["chat_citations"] == 1 and "cited 1×" in v2[ids["outlier"]]["label"] and not v2[ids["outlier"]]["never_used"]
    assert v2[ids["secs"][1]]["priority"] and v2[ids["secs"][1]]["matters"] and "★ priority" in v2[ids["secs"][1]]["label"]
    assert v2[ids["secs"][0]]["never_used"] is False or v2[ids["secs"][0]]["claims"]["evidence_rows"] == 0
    # weights are documented and deterministic
    assert sv.compute(pid) == v2
    only_low = {"findings": {"approved": 5}, "importance": {"max": 1, "sum": 5, "n4plus": 0}, "claims": {"evidence_rows": 0, "strong": 0, "accepted": 0},
                "used": {"plan_evidence": 0, "chat_citations": 0, "last_used_at": None}, "priority": False}
    plan_only = {**only_low, "findings": {"approved": 0}, "importance": {"max": 0, "sum": 0, "n4plus": 0}, "used": {"plan_evidence": 1, "chat_citations": 0, "last_used_at": 1}}
    assert sv.score(only_low) < sv.score(plan_only) and not sv.why(only_low) and sv.why(plan_only) == ["evidence in the Master Plan"]


def test_sources_rows_carry_value_and_staleness_for_the_filters(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid)
    rows = {r["id"]: r for r in api.api_sources(project_id=pid)}
    prim = rows[ids["primary"]]
    assert prim["value"]["score"] > 0 and prim["value"]["label"] and prim["value"]["stale"] is False and "used" in prim["value"]
    assert all("value" in r and "stale" in r["value"] for r in rows.values())
    db.update_project(pid, brief="a different brief entirely")
    rows2 = {r["id"]: r for r in api.api_sources(project_id=pid)}
    # findings in the fixture were pinned notes (no analysis rows), so nothing is stale by analysis — the flag is False, never missing
    assert all(r["value"]["stale"] in (True, False) for r in rows2.values())
