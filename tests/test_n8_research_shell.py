"""R2 — the Research shell (0.44.0): the tab renders from ONE $0 request (`overview(full=True)` returns the same questions,
watch-outs and areas the separate endpoints do, computed in one pass), and a watch-out carries ONE verdict for every tension
behind it — "Not important to my project" is durable, a later refresh never reopens it. (Sorts after test_n7.)"""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, jobs, knowledge, research_view as rv, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture  # noqa: E402
from tests.frontend_helpers import ui_source  # noqa: E402

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


def _ready(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid)
    knowledge.refresh(pid)
    return pid, ids


def _calls():
    return db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]


def test_one_request_carries_every_pane(monkeypatch):
    pid, _ = _ready(monkeypatch)
    before = _calls()
    full = rv.overview(pid, full=True)
    assert _calls() == before, "the shell's request is a $0 surface"
    # the same lists the separate endpoints return — one pass instead of four.
    #
    # CHANGED 0.62.7 (recorded in HARDENING.md): this asserted byte-equality with `rv.questions(pid)` and carried
    # `area_of_claim`. Measured on Kyle's project, that made the shell's one request **5,858 KB in 23.7 s** —
    # `questions` 4,802 KB over 2,703 targets, `area_of_claim` 854 KB over 15,499 claims. The RUNG's intent is one
    # pass instead of four, and that is intact; what is no longer promised is that the pass returns everything at
    # once. `questions` is bounded (in the same order, with the total and a truncation flag beside it) and the full
    # list is paged from the endpoint; `area_of_claim` is opt-in because nothing in the UI reads it.
    qs_all = rv.questions(pid)
    assert full["questions"] == sorted(qs_all, key=lambda q: (0 if q["status"] == "open" else 1, -q["score"]))[:rv.QUESTIONS_INLINE_MAX]
    assert full["questions_total"] == len(qs_all) and full["questions_truncated"] is (len(qs_all) > rv.QUESTIONS_INLINE_MAX)
    assert full["watchouts"] == rv.watchouts(pid)
    ar = rv.areas(pid)
    assert full["areas"] == ar["areas"] and full["area_of_topic"] == ar["area_of_topic"]
    assert "area_of_claim" not in full                                   # opt-in only
    assert rv.overview(pid, full=True, area_map=True)["area_of_claim"] == ar["area_of_claim"]
    # and everything the panes need is in it
    assert {"summary", "next", "recently_improved", "attention", "areas", "empty"} <= set(full)
    assert full["areas"] and full["questions"] and full["watchouts"]
    # the light request stays light: no questions/watchouts unless asked
    light = rv.overview(pid)
    assert "questions" not in light and "watchouts" not in light and light["next"] == full["next"]
    assert api.api_research_overview(pid, full=True)["questions"] == full["questions"]
    assert "questions" not in api.api_research_overview(pid)


def test_one_verdict_clears_a_whole_watch_out_and_dismissal_is_durable(monkeypatch):
    pid, _ = _ready(monkeypatch)
    before_issues = rv.overview(pid)["summary"]["issues_total"]
    w = next(x for x in rv.watchouts(pid) if x["claims"] >= 1)
    ids = [u["tension_id"] for u in w["underlying"]]
    r = api.api_tensions_bulk(pid, api.TensionsBulkIn(tension_ids=ids, status="dismissed"))
    assert r["changed"] == len(ids) and r["skipped"] == 0
    assert not any(x["id"] == w["id"] for x in rv.watchouts(pid)), "the issue is gone, not just one of its rows"
    # durable: the deterministic pass re-selects tensions on every refresh but never reopens a dismissed one
    knowledge.refresh(pid)
    claims.ensure(pid)
    assert not any(x["id"] == w["id"] for x in rv.watchouts(pid))
    assert all(t["status"] == "dismissed" for t in knowledge.list_tensions(pid, status=None) if t["id"] in ids)
    # scoped and validated: another project's tension ids are skipped, a bad status is refused
    other = db.create_project("Other", "x")
    assert api.api_tensions_bulk(other["id"], api.TensionsBulkIn(tension_ids=ids, status="resolved"))["changed"] == 0
    assert all(t["status"] == "dismissed" for t in knowledge.list_tensions(pid, status=None) if t["id"] in ids)
    with pytest.raises(Exception):
        api.api_tensions_bulk(pid, api.TensionsBulkIn(tension_ids=ids, status="deleted"))
    with pytest.raises(Exception):
        api.api_tensions_bulk("no-such-project", api.TensionsBulkIn(tension_ids=ids, status="resolved"))
    # the summary counts issues, not rows: clearing one removes exactly one from issues_total
    assert rv.overview(pid)["summary"]["issues_total"] == before_issues - 1


def test_the_shell_and_the_api_agree(monkeypatch):
    """A UI rung still gets a gate: every endpoint and pane id the shell uses must exist on this build."""
    html = ui_source(UI.parent)
    for pane in ("paneOverview", "paneQuestions", "paneWatchouts", "paneAreas", "paneClaims", "paneTools"):
        assert f'id="{pane}"' in html, pane
    for el in ("resNav", "resHead", "resAreaBar", "resMsg", "resClaims", "resMap", "resTensions", "resTargets"):
        assert f'id="{el}"' in html, el          # the old lists stay reachable under Research tools
    assert "research/overview?full=1" in html and "tensions/bulk-status" in html
    routes = {r.path for r in api.app.routes if hasattr(r, "path")}
    for path in ("/api/projects/{project_id}/research/overview", "/api/projects/{project_id}/research",
                 "/api/projects/{project_id}/tensions/bulk-status", "/api/targets/{target_id}/pursue",
                 "/api/targets/{target_id}/status", "/api/targets/{target_id}/capture-best", "/api/targets/{target_id}/known"):
        assert path in routes, path
    # every action the questions pane renders as a button points at a route that exists
    pid, _ = _ready(monkeypatch)
    for q in rv.questions(pid):
        for a in q["actions"]:
            tmpl = re.sub(r"/api/targets/[^/]+/", "/api/targets/{target_id}/", a["endpoint"])
            assert tmpl in routes, a["endpoint"]
            assert a["label"] and a["cost"] and a["help"]
