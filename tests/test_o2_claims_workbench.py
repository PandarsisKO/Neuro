"""R7 — the Claims workbench (0.45.5): RESEARCH-TAB.md §5 asked for filters (needs decision · accepted · weak · stale ·
by topic), batch accept/reject and one plain-language line per Claim when the R2 shell was designed; R2 (0.44.0) moved
the old flat, capped, jargon-carrying list under its own tab without rebuilding it. This gate covers `claims_view.query`
(over the FULL claim set, never `knowledge.state`'s 300-cap), `bulk_status` (one refresh, project-scoped), `for_source`
(chat's "Why this answer"), and the "Settle this" chat-gap-to-target path. (Sorts after test_core, after test_k6.)"""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, claims_view, db, fake_ai, jobs, knowledge, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture, _by_text  # noqa: E402
from tests.frontend_helpers import ui_source  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


SOP_TEXT = None  # filled from the k6 fixture module for readability below


def _setup(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid)      # $0 harvest + assess + map, per test_k6
    return pid, ids


def test_query_filters_over_the_full_set_never_the_300_cap(monkeypatch):
    pid, ids = _setup(monkeypatch)
    from tests.test_k6_claims import SOP, OUTLIER, STALE_TEXT
    gov, out, stale = _by_text(pid, SOP), _by_text(pid, OUTLIER), _by_text(pid, STALE_TEXT)

    all_ = claims_view.query(pid)
    assert all_["total"] >= 3 and {gov["id"], out["id"], stale["id"]} <= {c["id"] for c in all_["claims"]}

    strong_only = claims_view.query(pid, strength="strong")
    assert {c["id"] for c in strong_only["claims"]} == {gov["id"]}
    assert out["id"] not in {c["id"] for c in strong_only["claims"]}

    stale_only = claims_view.query(pid, freshness="stale")
    assert stale["id"] in {c["id"] for c in stale_only["claims"]} and gov["id"] not in {c["id"] for c in stale_only["claims"]}

    # needs_decision = proposed AND (strong or developing) — the weak outlier and the weak stale Claim are NOT "needs a decision"
    # (there is nothing decision-worthy about a Claim with almost no evidence yet)
    nd = claims_view.query(pid, needs_decision=True)
    ids_nd = {c["id"] for c in nd["claims"]}
    assert gov["id"] in ids_nd and out["id"] not in ids_nd and stale["id"] not in ids_nd

    # a search that matches nothing returns 0, not an error
    assert claims_view.query(pid, q="zzz_no_such_token_zzz")["total"] == 0

    # facets are counts over the filtered set MINUS that filter's own dimension (so choosing a facet shows what it would give)
    f = claims_view.query(pid, strength="strong")["facets"]
    assert f["strength"].get("strong", 0) >= 1 and "weak" in f["strength"]   # the weak Claims still show up in the strength facet
    assert isinstance(f["needs_decision"], int) and f["needs_decision"] >= 1


def test_plain_language_replaces_the_internal_vocabulary(monkeypatch):
    pid, ids = _setup(monkeypatch)
    from tests.test_k6_claims import SOP, STALE_TEXT
    gov, stale = _by_text(pid, SOP), _by_text(pid, STALE_TEXT)
    gov_line = claims_view.plain(gov)
    stale_line = claims_view.plain(stale)
    # no raw internal tokens leak into the sentence a first-time reader sees
    for jargon in ("strong", "weak", "developing", "unsupported", "needs_refresh", "age_insensitive", "proposed"):
        assert jargon not in gov_line and jargon not in stale_line
    assert "well evidenced" in gov_line and "not yet decided" in gov_line
    assert "likely outdated" in stale_line


def test_bulk_status_is_project_scoped_and_refreshes_once(monkeypatch):
    pid, ids = _setup(monkeypatch)
    from tests.test_k6_claims import SOP, OUTLIER
    gov, out = _by_text(pid, SOP), _by_text(pid, OUTLIER)
    other_pid = db.create_project("Other project", "unrelated")["id"]
    foreign = claims.add_claim(other_pid, "A claim in a different project", origin="user")

    calls = []
    monkeypatch.setattr(knowledge, "refresh", lambda p: (calls.append(p), {})[1])
    r = claims_view.bulk_status(pid, [gov["id"], out["id"], foreign["id"], "not-a-real-id"], "accepted")
    assert r["changed"] == 2 and r["skipped"] == 2
    assert calls == [pid]                                                   # exactly one refresh, for THIS project only
    assert claims.get(foreign["id"])["status"] == "proposed"                # the other project's Claim was never touched
    assert claims.get(gov["id"])["status"] == "accepted" and claims.get(out["id"])["status"] == "accepted"

    # an empty selection changes nothing and never calls refresh
    calls.clear()
    r2 = claims_view.bulk_status(pid, [], "rejected")
    assert r2["changed"] == 0 and calls == []

    with pytest.raises(ValueError):
        claims_view.bulk_status(pid, [gov["id"]], "not_a_status")


def test_for_source_is_why_this_answer(monkeypatch):
    pid, ids = _setup(monkeypatch)
    from tests.test_k6_claims import SOP
    gov = _by_text(pid, SOP)
    primary_sid = ids["primary"]

    exact = claims_view.for_source(pid, primary_sid, locator="§ 1")
    assert exact["total"] >= 1
    top = exact["claims"][0]
    assert top["id"] == gov["id"] and top["matched_here"] is True and "well evidenced" in top["plain"]

    wrong_locator = claims_view.for_source(pid, primary_sid, locator="9:99")
    assert wrong_locator["claims"][0]["id"] == gov["id"] and wrong_locator["claims"][0]["matched_here"] is False

    # a source nothing rests on returns an empty, honest list — never a fabricated Claim
    never_used = db.upsert_source(platform="youtube", external_id="never-cited", url="https://www.youtube.com/watch?v=never-cited", title="Untouched", status="ready")
    assert claims_view.for_source(pid, never_used["id"])["claims"] == []


def test_api_wiring_and_settle_this_reuses_the_normal_target_path(monkeypatch):
    pid, ids = _setup(monkeypatch)
    from tests.test_k6_claims import SOP
    gov = _by_text(pid, SOP)

    r = api.api_claims_query(pid, strength="strong")
    assert r["total"] >= 1 and any(c["id"] == gov["id"] for c in r["claims"])

    with pytest.raises(Exception):
        api.api_claims_bulk(pid, api.ClaimsBulkIn(claim_ids=[gov["id"]], status="bogus"))

    r2 = api.api_claims_for_source(pid, source_id=ids["primary"], locator="§ 1")
    assert r2["claims"] and r2["claims"][0]["id"] == gov["id"]

    # "Settle this" is not a new code path — it is the EXISTING /targets endpoint, so a chat gap becomes a real,
    # normally-escalatable Open question with no separate machinery to keep in sync
    before = len(knowledge.list_targets(pid))
    tg = api.api_target_add(pid, api.TargetIn(question="Does the seller's non-compete radius vary by state?", sufficiency="corroborative"))
    assert tg and len(knowledge.list_targets(pid)) == before + 1

    # the UI wires exactly these endpoints and functions
    web = __import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web"
    html = ui_source(web)
    assert "loadClaimsWorkbench" in html and "/claims?" in html
    assert "claimsBulk" in html and "/claims/bulk-status" in html
    assert "whyThisAnswer" in html and "/claims/for-source" in html
    assert "settleGap" in html and "Settle this" in html
    assert any(getattr(rt, "path", "") == "/api/projects/{project_id}/claims" for rt in api.app.routes)
    assert any(getattr(rt, "path", "") == "/api/projects/{project_id}/claims/bulk-status" for rt in api.app.routes)
    assert any(getattr(rt, "path", "") == "/api/projects/{project_id}/claims/for-source" for rt in api.app.routes)
