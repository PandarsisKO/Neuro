"""B3 — Candidate links / gap recall (0.36.0): an open question REMEMBERS the known-but-not-captured sources that could
fill it (a durable relation, not a JSON trail); acquisition satisfies the link; the user can capture the best few through
the normal path; the chat's research state says what is known but uncaptured; dismissal is the user's word. (Sorts after test_m2.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_links_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import candidates, db, fake_ai, jobs, knowledge, qa, safe_fetch  # noqa: E402
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


def _open_corroborative(pid):
    from neurosearch import claims
    claims.ensure(pid)
    knowledge.refresh(pid)
    return [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]


def test_pursue_links_candidates_to_the_open_question_durably(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    tg = _open_corroborative(pid)
    knowledge.pursue(tg["id"], external=False)
    links = candidates.links_for(pid, "evidence_target", tg["id"])
    assert links and any(l["candidate_id"] == ids["candidate"] for l in links) and all(l["state"] == "open" and l["relevance"] is not None for l in links)
    assert links[0]["acquisition_hint"] == "server"
    # visible on the research state and in the chat's research_state tool
    st = knowledge.state(pid)
    tgs = {t["id"]: t for t in st["targets"]}
    assert tgs[tg["id"]]["known_uncaptured"] >= 1
    txt = qa._run_tool("research_state", {}, db.get_project(pid), [], [])
    assert "known but not yet captured" in txt
    # pursuing again refreshes, never duplicates
    knowledge.pursue(tg["id"], external=False)
    assert len(candidates.links_for(pid, "evidence_target", tg["id"], limit=50)) == len(links)


def test_acquisition_satisfies_the_link_and_dismissal_is_the_users_word(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    tg = _open_corroborative(pid)
    knowledge.pursue(tg["id"], external=False)
    # the user says one is not useful for this question: it stays known, but out of this question's list, even after re-ranking
    other = [l for l in candidates.links_for(pid, "evidence_target", tg["id"], limit=50) if l["candidate_id"] != ids["candidate"]]
    if other:
        assert candidates.dismiss_link(pid, other[0]["candidate_id"], "evidence_target", tg["id"]) == 1
        knowledge.pursue(tg["id"], external=False)
        assert other[0]["candidate_id"] not in {l["candidate_id"] for l in candidates.links_for(pid, "evidence_target", tg["id"], limit=50)}
        assert db.connect().execute("SELECT state FROM candidate_links WHERE candidate_id=? AND ref_id=?", (other[0]["candidate_id"], tg["id"])).fetchone()["state"] == "dismissed"
    # the candidate is acquired by ANY path → the link is satisfied, the count drops
    c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (ids["candidate"],)).fetchone())
    src = db.upsert_source(platform="youtube", external_id=c["external_id"], url=c["url"], title=c["title"], status="ready")
    candidates.resolve_acquired("youtube", c["external_id"], src["id"])
    assert db.connect().execute("SELECT state FROM candidate_links WHERE candidate_id=? AND ref_id=?", (ids["candidate"], tg["id"])).fetchone()["state"] == "satisfied"
    assert ids["candidate"] not in {l["candidate_id"] for l in candidates.links_for(pid, "evidence_target", tg["id"], limit=50)}


def test_capture_best_goes_through_the_normal_path(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    tg = _open_corroborative(pid)
    knowledge.pursue(tg["id"], external=False)
    # one linked candidate is already owned by another project → attached, not re-acquired; the rest become ingest jobs
    c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (ids["candidate"],)).fetchone())
    other = db.create_project("other", "y")["id"]
    src = db.upsert_source(platform="youtube", external_id=c["external_id"], url=c["url"], title=c["title"], status="ready")
    db.add_project_sources(other, [src["id"]])
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=? WHERE id=?", (src["id"], c["id"]))
    r = knowledge.capture_best(pid, tg["id"], n=3)
    hows = {x["candidate_id"]: x["how"] for x in r["started"]}
    assert hows.get(ids["candidate"]) == "attached" and src["id"] in db.project_source_ids(pid, ready_only=False)
    for x in r["started"]:
        if x["how"] == "job":
            j = db.get_job(x["job_id"])
            assert j["kind"] == "ingest_url" and j["payload"]["project_id"] == pid and j["payload"]["candidate_id"] == x["candidate_id"]
    # nothing web: no discover job was created
    assert not [j for j in db.list_jobs(limit=50) if j["kind"] == "discover"]
    from neurosearch import api
    k = api.api_target_known(tg["id"])
    assert set(k) >= {"known_uncaptured", "browser_likely", "best"}


def test_reddit_candidates_are_flagged_browser_likely():
    pid = db.create_project("r", "x")["id"]
    cid = candidates.remember([{"external_id": "reddit:zz1", "url": "https://www.reddit.com/r/accounting/comments/zz1/x/", "title": "Bought a CPA practice last year — client attrition", "content_type": "post"}],
                              "reddit", pid, {"kind": "community_search", "title": "r/accounting"})[0]
    tg = knowledge.add_target(pid, "How do acquired CPA firms prevent client attrition after the seller leaves?", sufficiency="corroborative")
    candidates.link(cid, pid, "evidence_target", tg["id"], relevance=92, why="matches")
    k = knowledge.known_evidence(pid, tg["id"])
    assert k["known_uncaptured"] == 1 and k["browser_likely"] == 1 and k["best"][0]["acquisition_hint"] == "browser_likely"
