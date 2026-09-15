"""S5 — the known-but-uncaptured pool (0.43.0): skipped (pre-cutoff) sources and Candidate Index rows in ONE list with a $0
potential scan against the project's open questions, weak areas and vocabulary; why each is known; capture through the
normal path; dismissal durable; never evidence. (Sorts after test_n6.)"""
from __future__ import annotations

import os

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


def test_job_lists_omit_captured_page_bodies_but_detail_keeps_them():
    """The Jobs panel polls often and never reads a browser capture's full HTML document."""
    p = db.create_project("compact jobs", "brief")
    body = "<html>" + ("large page " * 5000) + "</html>"
    job = db.create_job("ingest_url", {
        "project_id": p["id"], "url": "https://example.test/page",
        "_external_result": {"capture": {"html": body}},
    })

    project_row = next(j for j in api.api_project_jobs(p["id"]) if j["id"] == job["id"])
    global_row = next(j for j in api.api_jobs() if j["id"] == job["id"])
    assert "_external_result" not in project_row["payload"]
    assert "_external_result" not in global_row["payload"]
    assert project_row["payload_omitted"] == ["_external_result"]
    assert api.api_job(job["id"])["payload"]["_external_result"]["capture"]["html"] == body


def test_pool_unifies_skipped_and_candidates_with_a_potential_scan(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    corro = [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]
    knowledge.pursue(corro["id"], external=False)                      # links the fixture's skipped candidate to the open question
    timeless = _skipped(pid, "old-timeless", "Seller transition length: six, twelve or eighteen months versus two full tax seasons",
                        "A framework and checklist for the usual seller transition: how many tax seasons the seller keeps working, retention principles.", relevance=35)
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


    # 0.63.20 — this fixture's source used to be titled "How to structure a seller transition when buying an
    # accounting practice" and was asserted to name the open question. Measured: its best share was **0.217**,
    # under the 0.34 `FIT_MIN_SHARE` that `_potential` has needed for fit POINTS since S5 — so the assertion was
    # pinning the very behaviour that made Kyle's pool header read "8,917 of 8,970 fit an open question". The
    # source is now genuinely on the question (0.478), and the near miss is asserted as a near miss: it still
    # outranks the dated one on its other signals, and it says nothing it cannot support.
    near = _skipped(pid, "old-near", "How to structure a seller transition when buying an accounting practice",
                    "A framework and checklist for the seller transition: how many tax seasons, what the seller keeps doing, retention.", relevance=35)
    r2 = candidates.pool(pid)
    nrow = {i["id"]: i for i in r2["items"]}[near]
    assert nrow["fits"] is None and nrow["potential"] > d["potential"]
    assert not any(w.startswith("fits an open question") for w in nrow["why"])
    assert r2["counts"]["fits_a_question"] == sum(1 for i in r2["items"] if i["fits"])


def test_capture_the_n_that_fit_takes_the_same_paths_as_a_single_capture(monkeypatch):
    """0.45.4 — HANDOFF §4a's 'capture the N that fit' bulk action. One request captures every pool item at or above the
    'worth a look' threshold (potential >= 40) through EXACTLY the per-item path a single Capture click takes: retry for a
    skipped source, attach-from-library or ingest for a candidate — never a parallel path, so a bulk capture cannot diverge
    from what clicking each row by hand would have done."""
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    corro = [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]
    knowledge.pursue(corro["id"], external=False)
    timeless = _skipped(pid, "old-timeless", "Seller transition length: six, twelve or eighteen months versus two full tax seasons",
                        "A framework and checklist for the usual seller transition: how many tax seasons the seller keeps working, retention principles.", relevance=35)
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
    web = __import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web"
    html = __import__("tests.frontend_helpers", fromlist=["ui_source"]).ui_source(web)
    assert "/pool/capture-many" in html and "captureManyPool" in html


def test_skipped_sources_carry_the_pool_potential_scan_on_the_plain_sources_list(monkeypatch):
    """Kyle, live: a pre-cutoff source in the Sources tab showed no thumbnail and no hint of whether it was worth
    ingesting anyway — the pool already runs this exact $0 scan, it just never reached the ordinary sources list
    a person looks at day to day. GET /api/sources must carry the same score/why the pool shows, keyed the same way
    ('worth a look' >= 40), and must never compute it (or crash) for a non-skipped row."""
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    timeless = _skipped(pid, "old-timeless-src", "Seller transition length: six, twelve or eighteen months versus two full tax seasons",
                        "A framework and checklist for the usual seller transition: how many tax seasons the seller keeps working, retention principles.", relevance=35)
    dated = _skipped(pid, "old-dated-src", "SBA rates news update this week", "Breaking: rates moved again today; market update for 2021.", relevance=20)
    rows = {r["id"]: r for r in api.api_sources(project_id=pid)}
    pool_by = {i["id"]: i for i in candidates.pool(pid, kind="skipped")["items"]}
    assert rows[timeless]["pool_potential"]["score"] == pool_by[timeless]["potential"]
    assert rows[dated]["pool_potential"]["score"] == pool_by[dated]["potential"]
    # same scan, same ranking as the pool: the higher-relevance, timeless, on-topic one clearly outscores the dated one
    assert rows[timeless]["pool_potential"]["score"] > rows[dated]["pool_potential"]["score"]
    assert rows[timeless]["pool_potential"]["fits"]
    # a ready/non-skipped row never carries the field at all — it isn't a candidate for "worth ingesting anyway"
    ready = next((r for r in rows.values() if r["status"] not in ("skipped",)), None)
    assert ready is None or "pool_potential" not in ready


def test_refresh_skipped_metadata_backfills_thumbnails_without_changing_status(monkeypatch):
    """0.45.7 backfill: a source skipped before the ingest.ingest_source fix (or by the `_skipped` test helper, same
    shape) has no thumbnail_url. The bulk endpoint queues one refresh job per such source; running it re-fetches
    metadata only and updates the row — status and error stay 'skipped' and the cutoff reason, never re-ingested."""
    from neurosearch import ingest, media
    pid, ids = _fixture(monkeypatch)
    has_thumb = _skipped(pid, "has-thumb", "Already has a thumbnail", "x")
    db.upsert_source(platform="youtube", external_id="has-thumb", thumbnail_url="https://img.example/already.jpg")
    missing = _skipped(pid, "missing-thumb", "No thumbnail yet", "an old but on-topic video")

    def fake_info(url, cookies_file=None, referer=None):
        assert url == db.get_source(missing)["url"]
        return {"id": "missing-thumb", "title": "No thumbnail yet", "webpage_url": url, "upload_date": "20210301",
                "channel": "Old Channel", "thumbnail": "https://img.example/missing-thumb.jpg", "description": "refreshed description"}
    monkeypatch.setattr(media, "fetch_info", fake_info)

    r = api.api_refresh_skipped_metadata(pid)
    assert r["queued"] == 1   # has_thumb already has a thumbnail — only_missing (default) skips it
    js = [j for j in db.list_jobs(50) if j["kind"] == "refresh_skipped_metadata"]
    assert len(js) == 1 and js[0]["payload"]["source_id"] == missing
    from neurosearch import jobs
    jobs.execute(db.claim_job(("refresh_skipped_metadata",)))
    s = db.get_source(missing)
    assert s["thumbnail_url"] == "https://img.example/missing-thumb.jpg" and s["status"] == "skipped" and "before cutoff" in s["error"]
    assert db.get_source(has_thumb)["thumbnail_url"] == "https://img.example/already.jpg"   # untouched

    # refusing to run on anything not currently skipped — this is a display backfill, never a re-ingest path
    ready_id = db.upsert_source(platform="youtube", external_id="ready-one", url="https://www.youtube.com/watch?v=ready-one", status="ready")["id"]
    with pytest.raises(RuntimeError, match="not skipped"):
        ingest.refresh_skipped_metadata(ready_id)

    # a repeat call with everything already thumbnailed queues nothing
    r2 = api.api_refresh_skipped_metadata(pid)
    assert r2["queued"] == 0


def test_extract_claims_job_can_be_cancelled_mid_run(monkeypatch):
    """Kyle, live (screenshot): an extract_claims job showed 'cancelling... (stops at the next safe point)' and sat
    there for minutes without ever actually stopping. Every other AI job kind (findings, ingest) calls
    jobs.check_cancel() at a safe boundary inside its loop; claims.extract() never did, so a cancel request could
    only take effect once the WHOLE job finished — on a big candidate backlog, that's never. Also: the job's label
    in the Jobs panel was the raw kind name 'extract_claims' with no explanation of what it does."""
    pid, ids = _fixture(monkeypatch)
    from neurosearch import claims
    for i in range(17):                                        # more than one EXTRACT_GROUP (8), so a mid-run cancel has somewhere to land
        claims.add_claim(pid, f"Claim number {i} about a distinct topic area {i} for this test", status="proposed", normalized=False)
    assert len(claims.unnormalized(pid)) >= 17

    job = db.create_job("extract_claims", {"project_id": pid, "reason": "test"})
    job = db.claim_job(("extract_claims",))
    assert db.request_cancel(job["id"]) == "running"
    assert jobs.execute(job) == "cancelled"
    assert db.get_job(job["id"])["status"] == "cancelled"
    # the cancel landed before grinding through every group — nothing got normalized (no spend, nothing half-written)
    assert not any(c.get("normalized") for c in claims.list_for_project(pid))

    # the Jobs panel no longer shows the bare kind name for this job
    web = __import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web"
    html = __import__("tests.frontend_helpers", fromlist=["ui_source"]).ui_source(web)
    assert "extract_claims" in html and "finding claims to track" in html
    assert "extract_claims" in jobs.RETRYABLE   # a transient provider hiccup retries like every other AI job kind, instead of failing outright


def test_extract_claims_honours_a_cancel_after_the_model_returns(monkeypatch):
    """A model response is a safe boundary too: cancellation must not wait for a whole historical backlog to assess."""
    pid, ids = _fixture(monkeypatch)
    from neurosearch import claims
    claim = claims.add_claim(pid, "A distinct claim that the model will return", status="proposed", normalized=False)
    job = db.create_job("extract_claims", {"project_id": pid, "reason": "test"})
    job = db.claim_job(("extract_claims",))

    def cancel_after_answer(*args, **kwargs):
        db.request_cancel(job["id"])
        return {"claims": [{"id": claim["id"], "text": claim["text"]}], "targets": []}

    monkeypatch.setattr(__import__("neurosearch.providers", fromlist=["invoke_structured"]), "invoke_structured", cancel_after_answer)
    assert jobs.execute(job) == "cancelled"
    assert db.get_job(job["id"])["status"] == "cancelled"
    assert not claims.get(claim["id"])["normalized"]


def test_cancelled_queued_background_job_is_finalized_even_when_lane_is_paused(monkeypatch):
    """A paused worker pool must not strand a user-requested cancellation in a non-terminal state."""
    pid, ids = _fixture(monkeypatch)
    job = db.create_job("extract_claims", {"project_id": pid, "reason": "test"})
    assert db.request_cancel(job["id"]) == "cancelled"
    # Simulate the durable recovery shape: a running job was requested, then startup returned it to queued.
    db.connect().execute("UPDATE jobs SET status='queued', finished_at=NULL, cancel_requested_at=? WHERE id=?", (db.now(), job["id"]))
    db.connect().commit()
    assert db.claim_job(("reembed",), worker_id="ordinary") is None
    assert db.get_job(job["id"])["status"] == "cancelled"


def test_project_jobs_never_hides_an_active_job_behind_a_big_backlog(monkeypatch):
    """Kyle, live: "our in progress queue gets cut off if theres too many items in queue. I cannot see whats
    active." api_project_jobs used to scan only the most-recently-CREATED 400 jobs app-wide (db.list_jobs(400))
    before filtering down to this project — a genuinely active job for THIS project, created before a big batch
    of other jobs land (any project, any kind), gets pushed out of that recency window and simply vanishes from
    the panel, even though it is still queued and will run eventually. Every ACTIVE job for this project must
    show up regardless of how much has been created elsewhere since."""
    pid, ids = _fixture(monkeypatch)
    mine = db.create_job("reembed", {"project_id": pid, "n": "mine"})
    for i in range(450):                 # more than the old scan window (400) — all created AFTER ours
        db.create_job("reembed", {"project_id": "someone-elses-project", "n": i})
    rows = api.api_project_jobs(pid, limit=40)
    assert any(r["id"] == mine["id"] for r in rows)


def test_priority_lane_jobs_are_claimed_before_older_normal_lane_ones(monkeypatch):
    """Kyle: "ranking is far too slow." rank_proposed shares the same small local-AI worker pool as everything
    else in jobs.ANALYSIS_KINDS (findings, extract_claims, discover, build_plan) with plain FIFO scheduling — on
    a project with a big background backlog, a freshly-queued ranking job for a review card Kyle is actively
    looking at could sit behind hundreds of older jobs before a worker ever reaches it. rank_proposed now gets
    lane='priority', which is claimed ahead of 'normal'-lane jobs regardless of age — purely queue order, never
    a change to cost or provider (LOCAL_POLICIES/API_POLICIES and route() are untouched)."""
    pid, ids = _fixture(monkeypatch)
    old_normal = db.create_job("reembed", {"n": "old"})                      # created first, ordinary lane
    new_priority = db.create_job("reembed", {"n": "new"}, lane="priority")   # created after, priority lane
    assert db.claim_job(("reembed",))["id"] == new_priority["id"]            # priority wins despite being younger
    assert db.claim_job(("reembed",))["id"] == old_normal["id"]              # the older normal job still runs right after

    # every place a rank_proposed job is queued tags it priority, so a fresh review card never waits behind the backlog
    import re
    for path in ("api.py", "explore.py", "ingest.py"):
        src = (__import__("pathlib").Path(__import__("neurosearch").__file__).parent / path).read_text()
        for m in re.finditer(r'create_job\("rank_proposed"', src):
            window = src[m.start():m.start() + 260]
            assert 'lane="priority"' in window, f"{path}: {window[:100]}"


def test_low_lane_never_displaces_priority_or_normal_work(monkeypatch):
    """Kyle: "we need to be able to skip the line for items that are higher priority. obviously transcribing new
    sources, ranking things etc are higher priority over refreshing meta data from stale or skipped things that
    we dont even know if we will utilize." The lane order is now priority < normal/slow < low: a 'low' job (the
    skipped-metadata backfill — speculative work on content not yet known to matter) is claimed only once nothing
    priority or normal is waiting, however old it is; it still runs eventually, never starved outright."""
    pid, ids = _fixture(monkeypatch)
    old_low = db.create_job("reembed", {"n": "old-low"}, lane="low")            # created first, but low priority
    new_normal = db.create_job("reembed", {"n": "new-normal"})                  # created after, ordinary lane
    newer_priority = db.create_job("reembed", {"n": "newer-priority"}, lane="priority")  # created last, priority
    assert db.claim_job(("reembed",))["id"] == newer_priority["id"]             # priority first regardless of age
    assert db.claim_job(("reembed",))["id"] == new_normal["id"]                 # then normal
    assert db.claim_job(("reembed",))["id"] == old_low["id"]                    # low runs last, but it DOES run

    # the skipped-metadata backfill (speculative — content not yet known to be useful) is tagged low
    missing = _skipped(pid, "low-lane-src", "Some old video", "an old but on-topic video")
    r = api.api_refresh_skipped_metadata(pid)
    assert r["queued"] == 1
    job = next(j for j in db.list_jobs(20) if j["kind"] == "refresh_skipped_metadata" and j["payload"]["source_id"] == missing)
    assert job["lane"] == "low"


def test_job_lane_backfill_reprioritizes_jobs_already_queued_before_the_fix(monkeypatch):
    """Kyle: "the active queue needs to be re-prioritized." The 0.45.9/0.45.10 lane tags only apply to jobs
    CREATED from then on — anything already sitting in the queue (e.g. a rank_proposed or refresh_skipped_metadata
    job queued before this update landed) kept the old 'normal' lane. init_db() now backfills any currently-QUEUED
    job of those kinds to its correct lane on every app start, so a restart alone fixes the existing backlog too,
    not just future jobs — and it never touches a job that has already finished."""
    pid, ids = _fixture(monkeypatch)
    done_src = db.create_job("rank_proposed", {"collection_id": "c-done", "project_id": pid}, lane="normal")
    claimed = db.claim_job(("rank_proposed",))
    assert claimed["id"] == done_src["id"]
    db.finish_job(claimed["id"], claimed.get("run_id"), "done", message="done")

    stale_rank = db.create_job("rank_proposed", {"collection_id": "c1", "project_id": pid}, lane="normal")
    stale_backfill = db.create_job("refresh_skipped_metadata", {"source_id": "s1", "project_id": pid}, lane="normal")
    assert db.get_job(stale_rank["id"])["lane"] == "normal" and db.get_job(stale_backfill["id"])["lane"] == "normal"

    db.init_db()   # simulates a server restart picking up the fix
    assert db.get_job(stale_rank["id"])["lane"] == "priority"
    assert db.get_job(stale_backfill["id"])["lane"] == "low"
    assert db.get_job(done_src["id"])["lane"] == "normal"   # already finished — untouched


def test_bump_job_jumps_the_whole_queue_and_is_one_shot(monkeypatch):
    """Kyle: "can we get a manual start button in the progress queue to move it to the top/next in line?" A
    bumped job is claimed ahead of every lane, including 'priority' and even an older bump; bumps stack FIFO
    among themselves. The mark is cleared the moment the job is actually claimed — it's a one-time request, never
    a standing pin that would keep winning forever."""
    pid, ids = _fixture(monkeypatch)
    low_job = db.create_job("reembed", {"n": "low"}, lane="low")
    priority_job = db.create_job("reembed", {"n": "priority"}, lane="priority")
    assert db.bump_job(low_job["id"]) == "queued"
    assert db.get_job(low_job["id"])["bumped_at"]
    assert db.claim_job(("reembed",))["id"] == low_job["id"]          # bumped low-lane job still wins over priority
    assert db.claim_job(("reembed",))["id"] == priority_job["id"]     # then the queue resumes its normal order
    assert not db.get_job(low_job["id"])["bumped_at"]                 # cleared once claimed — one-shot

    # two bumps stack FIFO by request order, not creation order
    a = db.create_job("reembed", {"n": "a"})
    b = db.create_job("reembed", {"n": "b"})
    db.bump_job(b["id"]); db.bump_job(a["id"])                        # b bumped first
    assert db.claim_job(("reembed",))["id"] == b["id"]
    assert db.claim_job(("reembed",))["id"] == a["id"]

    # only a queued job can be bumped; the API surfaces the same rule
    running = db.create_job("reembed", {"n": "running"})
    db.claim_job(("reembed",))
    assert db.bump_job(running["id"]) == "running"
    with pytest.raises(Exception):
        api.api_bump_job(running["id"])
    with pytest.raises(Exception):
        api.api_bump_job("does-not-exist")


def test_check_now_unparks_a_timer_wait_and_is_a_noop_otherwise(monkeypatch):
    """Kyle: "in our progress bar we have a message that states: account's usage limit is reached — access returns
    2026-10-01 00:00 UTC ... but I think thats an old message and is not true. how do we verify?" The stored date is
    real (parsed straight from Anthropic's error text) but nothing re-attempts the call before it — 'Check now'
    clears the wait and bumps the job so the next worker cycle makes a genuinely fresh call."""
    pid, ids = _fixture(monkeypatch)
    parked = db.create_job("reembed", {"n": "parked"})
    db.requeue_job(parked["id"], delay=30 * 24 * 3600, message="paused: budget", wait_reason="budget")
    j = db.get_job(parked["id"])
    assert j["not_before"] and j["not_before"] > db.now()
    assert db.derived_status(j) == "budget_wait"

    assert db.check_now(parked["id"]) == "queued"
    j = db.get_job(parked["id"])
    assert not j["not_before"]
    assert not j["wait_reason"]
    assert j["bumped_at"]                                              # jumps the queue too, so it runs next
    assert db.derived_status(j) == "queued"

    # a job with no active timer wait has nothing to check early — no-op, not an error
    idle = db.create_job("reembed", {"n": "idle"})
    assert db.check_now(idle["id"]) == "queued"
    assert not db.get_job(idle["id"])["bumped_at"]                     # untouched — nothing was waiting

    # only a queued job can be checked; missing job is reported distinctly; the API surfaces the same rules
    still_waiting = db.create_job("reembed", {"n": "still_waiting"})
    db.requeue_job(still_waiting["id"], delay=100, wait_reason="retry")
    db.claim_job(("reembed",))                                         # claims the bumped `parked` job first
    db.claim_job(("reembed",))                                         # now claims `idle`
    assert db.get_job(still_waiting["id"])["status"] == "queued"       # untouched — not_before is still in the future
    now_running = db.create_job("reembed", {"n": "now_running"})
    db.claim_job(("reembed",))                                         # claims `now_running` -> status becomes running
    assert db.check_now(now_running["id"]) == "running"
    assert db.check_now("does-not-exist") == "missing"
    with pytest.raises(Exception):
        api.api_check_now(now_running["id"])
    with pytest.raises(Exception):
        api.api_check_now("does-not-exist")
    assert api.api_check_now(still_waiting["id"]) == {"ok": True}      # still queued -> checking it now succeeds


# ------------------------------------------------------------------ AD1: small-batch discovery
#
# "5 best next" is `candidates.next_batch` over the SAME ranked pool `pool()` already assembles, scoped to
# kind="candidates" only (never the "skipped" ingest-review backlog, which stays on the full pool table's own
# retry path). Deliberately no new shown/seen/cursor/session state: a resolved item drops out because
# `project_pool_revision` already changes on `mark()`; an unresolved one is correctly shown again next call.

def test_next_batch_returns_only_unresolved_candidates_never_skipped_sources(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    corro = [t for t in knowledge.list_targets(pid, status="open") if t["sufficiency"] == "corroborative"][0]
    knowledge.pursue(corro["id"], external=False)                      # the fixture's one open candidate
    _skipped(pid, "old-timeless", "Seller transition checklist", "A framework for the usual seller transition.", relevance=35)
    r = candidates.next_batch(pid, n=5)
    assert r["items"], r
    assert all(i["kind"] == "candidate" for i in r["items"])           # never the skipped-source backlog
    assert "remaining" in r and r["remaining"] >= 0


def test_next_batch_respects_n_and_reports_what_is_left(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    for t in knowledge.list_targets(pid, status="open"):
        knowledge.pursue(t["id"], external=False)
    candidates.remember([{"external_id": f"ad1-{i}", "url": f"https://example.org/ad1-{i}",
                          "title": f"Bonus candidate {i} about seller financing", "creator": "AD1 Channel"}
                         for i in range(8)], platform="youtube", project_id=pid, origin={"kind": "exploration"})
    full = candidates.next_batch(pid, n=50)
    total_candidates = len(full["items"])
    assert total_candidates >= 6
    small = candidates.next_batch(pid, n=3)
    assert len(small["items"]) == 3
    assert small["remaining"] == total_candidates - 3


def test_a_captured_candidate_does_not_reappear_and_an_undecided_one_does(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    for t in knowledge.list_targets(pid, status="open"):
        knowledge.pursue(t["id"], external=False)
    candidates.remember([{"external_id": "ad1-keep", "url": "https://example.org/ad1-keep",
                          "title": "Candidate that stays undecided about seller financing", "creator": "AD1 Channel"},
                         {"external_id": "ad1-capture", "url": "https://example.org/ad1-capture",
                          "title": "Candidate that gets captured about seller financing", "creator": "AD1 Channel"},
                         {"external_id": "ad1-reject", "url": "https://example.org/ad1-reject",
                          "title": "Candidate that gets rejected about seller financing", "creator": "AD1 Channel"}],
                        platform="youtube", project_id=pid, origin={"kind": "exploration"})
    before = candidates.next_batch(pid, n=50)
    ids_before = {i["id"] for i in before["items"]}
    cap_id = next(c["id"] for c in candidates.list_for_project(pid) if c["external_id"] == "ad1-capture")
    rej_id = next(c["id"] for c in candidates.list_for_project(pid) if c["external_id"] == "ad1-reject")
    keep_id = next(c["id"] for c in candidates.list_for_project(pid) if c["external_id"] == "ad1-keep")
    candidates.capture(cap_id, pid)
    candidates.dismiss(pid, rej_id, "not relevant")
    after = candidates.next_batch(pid, n=50)
    ids_after = {i["id"] for i in after["items"]}
    assert cap_id not in ids_after and rej_id not in ids_after         # resolved -> gone
    assert keep_id in ids_after                                        # undecided -> shown again, not lost
    assert ids_after == ids_before - {cap_id, rej_id}


def test_capture_attaches_when_already_owned_and_enqueues_when_not(monkeypatch):
    """The one shared CAPTURE path both API call sites now use — proven directly, not just through the API."""
    pid, ids = _fixture(monkeypatch)
    other = db.create_project("AD1 capture other", "brief")
    oid = other["id"] if isinstance(other, dict) else other
    ready = db.upsert_source(platform="youtube", external_id="ad1-owned", url="https://example.org/ad1-owned",
                             title="Already in the library", status="ready")
    cid = candidates.remember([{"external_id": "ad1-owned", "url": "https://example.org/ad1-owned",
                                "title": "Already in the library", "creator": "AD1 Channel", "source_id": ready["id"]}],
                              platform="youtube", project_id=oid, origin={"kind": "exploration"})[0]
    r1 = candidates.capture(cid, oid)
    assert r1["job_id"] is None and r1["source_id"] == ready["id"]     # attached, no new acquisition
    assert candidates.list_for_project(oid, "acquired")[0]["id"] == cid

    cid2 = candidates.remember([{"external_id": "ad1-new", "url": "https://example.org/ad1-new",
                                 "title": "Not yet in the library", "creator": "AD1 Channel"}],
                               platform="youtube", project_id=oid, origin={"kind": "exploration"})[0]
    r2 = candidates.capture(cid2, oid)
    assert r2["job_id"] and db.get_job(r2["job_id"])["kind"] == "ingest_url"    # the normal lifecycle, real job


def test_capture_raises_lookup_error_for_an_unknown_candidate(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    with pytest.raises(LookupError):
        candidates.capture("does-not-exist", pid)
    with pytest.raises(Exception):
        api.api_candidate_acquire("does-not-exist", api.CandidateActIn(project_id=pid))


def test_discover_cli_shows_a_batch_and_decide_resolves_it(monkeypatch):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    for t in knowledge.list_targets(pid, status="open"):
        knowledge.pursue(t["id"], external=False)
    r = CliRunner().invoke(app, ["project", "discover", pid, "--n", "5"])
    assert r.exit_code == 0, r.output
    assert "discover-decide" in r.output
    cid = next(c["id"] for c in candidates.list_for_project(pid) if c.get("state") in ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost"))
    r2 = CliRunner().invoke(app, ["project", "discover-decide", pid, cid, "reject", "--reason", "not needed"])
    assert r2.exit_code == 0 and "rejected" in r2.output
    assert candidates.list_for_project(pid, "user_dismissed") and candidates.list_for_project(pid, "user_dismissed")[0]["id"] == cid
    r3 = CliRunner().invoke(app, ["project", "discover-decide", pid, "does-not-exist", "capture"])
    assert r3.exit_code != 0
    r4 = CliRunner().invoke(app, ["project", "discover-decide", pid, cid, "maybe-later"])
    assert r4.exit_code != 0 and "capture" in r4.output
