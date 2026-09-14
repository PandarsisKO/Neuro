"""0.53.0 — a new project's first findings must not queue behind another project's backlog.

Kyle, live 2026-09-09, on a brand-new project with ~70 sources: *"the app is useless if I need to wait 24 hours
for sources to populate. we NEED some sources FAST. but not all of them right away to be able to use this app
while other processes are going."*

Findings were not slow — the queue was FIFO. His other project had ~1,000 jobs ahead, so a project created a
minute ago had its first finding hours away while the machine looked busy and produced nothing he could use.

The fix is queue ORDER only: same provider, same model, same $0. It is bounded (`FIRST_WAVE`), it is once per
project by construction (the condition is "this project has no findings", which stops being true as soon as the
wave lands), and 0.48.0's lesson is respected — this lane cannot re-trigger itself. (Sorts after test_r4.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_fw_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, ingest, jobs  # noqa: E402
from neurosearch.config import settings  # noqa: E402

TEXT = "0:05 a first line worth extracting\n1:00 a second line worth extracting"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _backlog(n: int = 20) -> str:
    """Another project, already deep in the queue — the thing a new project used to wait behind."""
    p = db.create_project("Old", "brief")
    for i in range(n):
        db.create_job("suggest_findings", {"project_id": p["id"], "source_ids": [f"s{i}"]})
    return p["id"]


def _channel(pid: str, n: int, scores: list[int]) -> tuple[str, list[str]]:
    """A reviewed channel: proposed sources carrying the relevance ranking rank_proposed produced."""
    coll = db.upsert_collection("channel", f"UC{pid[:8]}", f"https://www.youtube.com/@c{pid[:6]}", "A channel")
    ids = []
    for i in range(n):
        src = db.upsert_source(platform="youtube", external_id=f"chan{pid[:4]}{i:04d}",
                               url=f"https://www.youtube.com/watch?v=chan{pid[:4]}{i:04d}", status="ready", title=f"Video {i}")
        db.link_source_collection(src["id"], coll["id"])
        db.upsert_analysis(pid, src["id"], "relevance", relevance=scores[i], relevance_why="x")
        ids.append(src["id"])
    return coll["id"], ids


def test_a_channels_first_wave_is_the_top_ranked_videos_not_the_first_to_arrive():
    """Kyle's rule: "top 3 videos by ranking when ingesting a whole channel". The ranking already exists from the
    review, so it is decidable per source as each becomes ready — arrival order is irrelevant."""
    _backlog(20)
    new = db.create_project("New", "brief")
    _coll, ids = _channel(new["id"], 6, [10, 95, 30, 88, 5, 70])       # best: #1 (95), #3 (88), #5 (70)
    for sid in ids:                                                     # they become ready in ARRIVAL order
        jobs.enqueue_suggestions(sid, new["id"])
    lane = {(j["payload"] or {}).get("source_ids", [None])[0]: j["lane"]
            for j in db.list_jobs(limit=200) if (j["payload"] or {}).get("project_id") == new["id"]}
    assert [lane[ids[i]] for i in (1, 3, 5)] == ["priority"] * 3, "the three best-ranked jump the queue"
    assert [lane[ids[i]] for i in (0, 2, 4)] == ["normal"] * 3, "the rest wait their turn"
    # and a promoted one really is claimed before the older project's backlog
    first = db.claim_job(kinds=("suggest_findings",), worker_id="w")
    assert (first["payload"] or {}).get("project_id") == new["id"]


def test_a_source_added_on_its_own_always_starts_right_away():
    """The other half: "start findings right away when videos are added individually" — you added one video, you
    are waiting on that video. No collection means no ranking to be 4th in."""
    _backlog(20)
    new = db.create_project("New", "brief")
    solo = db.upsert_source(platform="youtube", external_id="solo0000001",
                            url="https://www.youtube.com/watch?v=solo0000001", status="ready", title="Just this one")
    jobs.enqueue_suggestions(solo["id"], new["id"])
    j = next(j for j in db.list_jobs(limit=200) if (j["payload"] or {}).get("project_id") == new["id"])
    assert j["lane"] == "priority"


def test_the_wave_is_free_it_only_changes_order():
    new = db.create_project("New", "brief")
    src = db.upsert_source(platform="youtube", external_id="free0000001",
                           url="https://www.youtube.com/watch?v=free0000001", status="ready", title="V")
    jobs.enqueue_suggestions(src["id"], new["id"])
    j = next(j for j in db.list_jobs(limit=50) if (j["payload"] or {}).get("project_id") == new["id"])
    assert j["lane"] == "priority"
    assert j["execution_policy"] == "local_preferred", "promotion must never route work onto the paid API"


def test_it_cannot_re_trigger_itself():
    """0.48.0's lesson: a lane that can re-queue itself needs a rate limit. This one must not be able to —
    a hundred individually-added sources still cannot promote more than the cap."""
    new = db.create_project("New", "brief")
    for i in range(50):
        src = db.upsert_source(platform="youtube", external_id=f"many{i:07d}",
                               url=f"https://www.youtube.com/watch?v=many{i:07d}", status="ready", title=f"V{i}")
        jobs.enqueue_suggestions(src["id"], new["id"])
    mine = [j for j in db.list_jobs(limit=200) if (j["payload"] or {}).get("project_id") == new["id"]]
    assert sum(1 for j in mine if j["lane"] == "priority") == jobs.FIRST_WAVE_CAP
    # once the project HAS findings, nothing is promoted at all
    db.kv_set(f"firstwave:{new['id']}", "0")
    db.add_project_note(new["id"], "a finding", status="suggested")
    assert jobs.first_wave_lane(new["id"]) == "normal"


def test_a_project_queued_before_this_existed_can_still_be_promoted(client):
    """The retroactive half: 75 sources already queued should not need "Start next" pressed 75 times."""
    p = db.create_project("Stuck", "brief")
    for i in range(12):
        db.create_job("suggest_findings", {"project_id": p["id"], "source_ids": [f"s{i}"]})
    r = db.promote_first_findings(p["id"], limit=6)
    assert r["promoted"] == 6 and r["waiting"] == 12
    bumped = [j for j in db.list_jobs(limit=50) if j["bumped_at"]]
    assert len(bumped) == 6
    first = db.claim_job(kinds=("suggest_findings",), worker_id="w")
    assert first["bumped_at"] is None, "a bump is one-shot: cleared the moment the job is claimed"
    # promoting again moves the NEXT ones and never the same ones twice
    still = {j["id"] for j in db.list_jobs(limit=50) if j["bumped_at"]}
    r2 = db.promote_first_findings(p["id"], limit=6)
    now = {j["id"] for j in db.list_jobs(limit=50) if j["bumped_at"]}
    assert r2["promoted"] == len(now - still), "every promotion this call made is a job that was not already bumped"
    assert still <= now


def test_the_endpoint_mirrors_it(client):
    H = {"Authorization": "Bearer t0k"}
    p = client.post("/api/projects", headers=H, json={"name": "FW", "goal": "a goal worth searching for"}).json()
    r = client.post(f"/api/projects/{p['id']}/findings/first-wave", headers=H)
    assert r.status_code == 200 and set(r.json()) == {"promoted", "waiting"}
    assert client.post("/api/projects/nope/findings/first-wave", headers=H).status_code == 404
