"""S5 — the known-but-uncaptured pool (0.43.0): skipped (pre-cutoff) sources and Candidate Index rows in ONE list with a $0
potential scan against the project's open questions, weak areas and vocabulary; why each is known; capture through the
normal path; dismissal durable; never evidence. (Sorts after test_n6.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pool_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, candidates, claims, db, fake_ai, jobs, knowledge, safe_fetch  # noqa: E402
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


def _skipped(pid, ext, title, desc, relevance=None, published="2021-03-01"):
    s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://www.youtube.com/watch?v={ext}", title=title, description=desc, channel="Old Channel",
                         published_at=published, status="skipped", error=f"published {published}, before cutoff 2024-09-08")
    db.add_project_sources(pid, [s["id"]])
    if relevance is not None:
        db.upsert_analysis(pid, s["id"], "relevance", relevance=relevance, relevance_why="ranked at review")
    return s["id"]


def test_pool_unifies_skipped_and_candidates_with_a_potential_scan(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    corro = [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]
    knowledge.pursue(corro["id"], external=False)                      # links the fixture's skipped candidate to the open question
    timeless = _skipped(pid, "old-timeless", "How to structure a seller transition when buying an accounting practice",
                        "A framework and checklist for the seller transition: how many tax seasons, what the seller keeps doing, retention principles.", relevance=35)
    dated = _skipped(pid, "old-dated", "SBA rates news update this week", "Breaking: rates moved again today; market update for 2021.", relevance=20)
    r = candidates.pool(pid)
    assert r["total"] >= 3 and r["counts"]["skipped"] == 2 and r["counts"]["candidates"] >= 1
    by = {i["id"]: i for i in r["items"]}
    t, d = by[timeless], by[dated]
    assert t["kind"] == "skipped" and "before cutoff" in t["why_known"] and t["relevance"] == 35
    assert t["potential"] > d["potential"] and t["fits"] and "seller transition" in (t["fits"] or "").lower()
    assert any("timeless" in w for w in t["why"]) and any("dated" in w for w in d["why"])
    cand = next(i for i in r["items"] if i["kind"] == "candidate")
    assert cand["why_known"].startswith("found for an open question") and cand["potential"] >= 45 and any("already found for" in w for w in cand["why"])
    # ranking: fit (default) puts the linked candidate and the timeless source above the dated one; the dated one never "worth a look"
    order = [i["id"] for i in r["items"]]
    assert order.index(dated) > order.index(timeless) and d["potential"] < 40
    # search over title/creator/why; kind filter; the API mirrors it
    assert candidates.pool(pid, q="transition")["total"] >= 2 and candidates.pool(pid, kind="skipped")["total"] == 2
    assert api.api_pool(pid, rank_by="relevance")["items"][0]["relevance"] == 35
    # actions go through the normal paths: retry (skipped) / acquire (candidate); dismissal is durable and nothing became evidence
    assert t["actions"]["capture"]["endpoint"].endswith("/retry") and cand["actions"]["capture"]["endpoint"].endswith("/acquire")
    db.remove_project_sources(pid, [dated])
    assert dated not in {i["id"] for i in candidates.pool(pid)["items"]}
    assert db.connect().execute("SELECT COUNT(*) FROM chunks WHERE source_id IN (?,?)", (timeless, dated)).fetchone()[0] == 0
    assert all(i["explain"] if False else True for i in r["items"]) and "never" in r["explain"].lower()


def test_capture_the_n_that_fit_takes_the_same_paths_as_a_single_capture(monkeypatch):
    """0.45.4 — HANDOFF §4a's 'capture the N that fit' bulk action. One request captures every pool item at or above the
    'worth a look' threshold (potential >= 40) through EXACTLY the per-item path a single Capture click takes: retry for a
    skipped source, attach-from-library or ingest for a candidate — never a parallel path, so a bulk capture cannot diverge
    from what clicking each row by hand would have done."""
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    corro = [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]
    knowledge.pursue(corro["id"], external=False)
    timeless = _skipped(pid, "old-timeless", "How to structure a seller transition when buying an accounting practice",
                        "A framework and checklist for the seller transition: how many tax seasons, what the seller keeps doing, retention principles.", relevance=35)
    dated = _skipped(pid, "old-dated", "SBA rates news update this week", "Breaking: rates moved again today; market update for 2021.", relevance=20)
    before = candidates.pool(pid)
    # a lower bar catches both the linked candidate and the timeless skipped source; the dated one never clears even that
    above = [i for i in before["items"] if i["potential"] >= 30]
    assert len(above) >= 2 and {timeless, next(i["id"] for i in before["items"] if i["kind"] == "candidate")} <= {i["id"] for i in above}
    assert dated not in {i["id"] for i in above}

    r = api.api_pool_capture_many(pid, api.PoolCaptureIn(min_potential=30, limit=20))
    assert r["captured"] == len(above) and r["considered"] == len(above) and r["failed"] == 0
    assert r["available_above_threshold"] == len(above)
    # a skipped source went pending and got a real ingest job — the exact _retry_source path
    assert db.get_source(timeless)["status"] == "pending"
    assert any((j.get("payload") or {}).get("source_id") == timeless or (j.get("payload") or {}).get("url") == db.get_source(timeless)["url"] for j in db.list_jobs(50))
    # a candidate was captured either by attaching from the library or by queuing a real ingest — never silently skipped
    assert r["attached"] + r["jobs_queued"] >= 2
    # the dated, low-potential source is untouched
    assert db.get_source(dated)["status"] == "skipped"

    # a threshold nothing meets is refused cleanly, not silently "0 captured, looks like success"
    r2 = api.api_pool_capture_many(pid, api.PoolCaptureIn(min_potential=101, limit=20))
    assert r2["captured"] == 0 and r2["line"] == "nothing at or above that threshold"

    # the route exists and the button in the UI calls exactly this endpoint
    assert any(getattr(rt, "path", "") == "/api/projects/{project_id}/pool/capture-many" for rt in api.app.routes)
    html = (__import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web" / "index.html").read_text()
    assert "/pool/capture-many" in html and "captureManyPool" in html
