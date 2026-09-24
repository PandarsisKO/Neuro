"""S85 (2026-09-23) — two things Kyle hit on a new personal-finance project, both from the same evening.

**The ranking "loop".** Kyle: *"it seems to be stuck in a loop of starting and stopping the ranking."* Measured in
`data/server.log`: 1,868 `rank batch N failed: LOCAL_UNAVAILABLE ... `claude` is not on PATH` lines in ten minutes,
the same three jobs each getting a fresh run id every ~0.6 s and never a `job done`. The server had just moved
under the LaunchAgent (`tools/server_agent.py`), whose PATH is launchd's `/usr/bin:/bin:/usr/sbin:/sbin` — no
`claude`. `rank_collection` treated the transport being DOWN as two batches that failed, persisted nothing, then hit
its BATCHES_PER_RUN quota and raised `Yield` — whose contract is "progress is written, re-running skips it". With no
progress written, the immediate requeue restarted batch 0, forever. Two guards: a `ProviderError` in `LOCAL_TYPES`
propagates (jobs.execute parks it 60 s with the local-AI-unavailable message), and a run that persisted nothing
never yields. Plus the actual cause: the agent now takes the login shell's PATH.

**The library-suggestions checkboxes.** Kyle: *"when I try to click the checkbox ... the page refreshes and the
check box is unclicked again. I cannot select anything effectively."* `renderBoot` rebuilt the card's innerHTML on
every poll (`loadBoot(true)` fires whenever jobs or sources change, i.e. constantly while a channel is being
listed), and innerHTML forgets every tick. Picks now live in `BOOT.pick`, outside the DOM, and an unchanged answer
never rebuilds the card."""
from __future__ import annotations

import os
import pathlib

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, jobs, providers, relevance  # noqa: E402
from neurosearch.config import settings  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESEARCH_JS = (ROOT / "neurosearch" / "web" / "js" / "research.js").read_text()
AGENT = (ROOT / "tools" / "server_agent.py").read_text()


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _collection(pid: str, n: int) -> str:
    coll = db.upsert_collection("channel", "UCloop0001", "https://www.youtube.com/@loop", "A finance channel")
    for i in range(n):
        src = db.upsert_source(platform="youtube", external_id=f"lp{i:08d}", url=f"https://www.youtube.com/watch?v=lp{i:08d}",
                               status="proposed", title=f"Video {i} about budgeting, index funds and paying off debt",
                               description="A talk about personal finance.", duration=900)
        db.link_source_collection(src["id"], coll["id"])
    return coll["id"]


def _local_down(*a, **k):
    raise providers.ProviderError("LOCAL_UNAVAILABLE", RuntimeError("claude code not_installed: `claude` is not on PATH"), 1, "rank.relevance")


def test_a_down_local_transport_propagates_instead_of_yielding_forever(monkeypatch):
    p = db.create_project("Personal finance", "How to build a budget and invest the rest")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))   # long enough to hit the yield quota
    monkeypatch.setattr(relevance, "_call", _local_down)
    with pytest.raises(providers.ProviderError) as e:
        relevance.rank_collection(coll, p["id"], want=20)
    assert e.value.error_type == "LOCAL_UNAVAILABLE"
    assert all(r.get("relevance") is None for r in db.proposed_sources(coll, p["id"])), "nothing pretended to be scored"


def test_jobs_execute_parks_that_job_for_a_minute_not_zero_seconds(monkeypatch):
    p = db.create_project("Personal finance", "a brief")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))
    monkeypatch.setattr(relevance, "_call", _local_down)
    jid = db.create_job("rank_proposed", {"collection_id": coll, "project_id": p["id"], "want": 20})["id"]
    claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
    assert jobs.execute(claimed, worker_id="w") == "queued"
    row = db.get_job(jid)
    assert row["status"] == "queued"
    assert (row["not_before"] or 0) >= db.now() + 30, "parked with a real delay — this is the loop"
    assert "local AI unavailable" in (row["message"] or "")
    assert not any(e["event_type"] == "yielded" for e in db.job_events(jid))


def test_a_run_that_scored_nothing_never_yields(monkeypatch):
    """Any other failure shape that leaves zero progress (a parser that rejects every batch, say) must finish with
    the honest note rather than restart from batch 0 on an immediate requeue."""
    p = db.create_project("Personal finance", "a brief")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))
    monkeypatch.setattr(relevance, "_call", lambda *a, **k: (_ for _ in ()).throw(ValueError("garbage from the model")))
    res = relevance.rank_collection(coll, p["id"], want=20)          # must NOT raise Yield
    assert res["ranked"] == 0 and res["failed_batches"] == relevance.BATCHES_PER_RUN
    meta = db.review_meta(coll)
    assert meta.get("ranked") and "could not be scored" in (meta.get("rank_note") or "")


def test_yield_still_happens_once_something_was_persisted():
    p = db.create_project("Design", "How complex web apps stay simple")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))
    with pytest.raises(jobs.Yield):
        relevance.rank_collection(coll, p["id"], want=20)


def test_server_agent_gives_the_server_a_login_path():
    assert "login_path()" in AGENT and 'os.environ["PATH"] = login_path()' in AGENT
    assert "/opt/homebrew/bin" in AGENT and "~/.local/bin" in AGENT


def test_boot_card_keeps_the_persons_ticks_across_polls():
    assert "pick: new Map()" in RESEARCH_JS
    assert "bootPicked(h) ? 'checked' : ''" in RESEARCH_JS and 'onchange="bootPick(' in RESEARCH_JS
    assert "if (sig === BOOT.sig && !el.hidden) return;" in RESEARCH_JS, "an unchanged answer never rebuilds the card"
    assert "i.checked !== i.defaultChecked) BOOT.pick.set(i.value, i.checked)" in RESEARCH_JS, "ticks made between renders survive"
    assert "BOOT.pick.clear()" in RESEARCH_JS, "a rescan starts the picks over"


def test_claude_code_widens_a_bare_launchd_path_to_the_user_bins(monkeypatch, tmp_path):
    from neurosearch import claude_code as CC
    home = tmp_path / "home"; (home / ".local" / "bin").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setattr(CC, "_path_widened", False)
    monkeypatch.setattr(CC.settings, "claude_code_bin", None)
    monkeypatch.setattr(CC.shutil, "which", lambda name: None)
    assert CC.binary() == "claude"
    parts = os.environ["PATH"].split(":")
    assert parts[:4] == ["/usr/bin", "/bin", "/usr/sbin", "/sbin"], "launchd's own PATH stays in front"
    assert str(home / ".local" / "bin") in parts, "an existing user bin dir is appended"
    assert str(home / ".npm-global" / "bin") not in parts, "a dir that does not exist is not"


def test_an_explicit_claude_code_bin_is_never_second_guessed(monkeypatch):
    from neurosearch import claude_code as CC
    monkeypatch.setattr(CC.settings, "claude_code_bin", "/somewhere/claude")
    assert CC.binary() == "/somewhere/claude"


def test_review_one_at_a_time_is_never_offered_when_acquiring_sources():
    """Kyle, 2026-09-23: "it should not appear at all when ingesting a source. only for findings, research, claims
    etc". The review card and the pool are acquisition decisions (ranker + pick top N + Start / Capture); focus
    review lives with findings, research and claims."""
    js = (ROOT / "neurosearch" / "web" / "js" / "sources.js").read_text()
    assert "Review one at a time</button>" not in js
    assert "onclick=\"rvFocus(" not in js and "onclick=\"poolFocus()" not in js


def test_a_rerank_of_a_fully_scored_list_converges_instead_of_restarting_from_batch_0():
    """Kyle, 2026-09-23 21:04: "the new rankings seem to be looping again". He pressed re-rank on two scored channels.
    A score written BEFORE the job was created is the previous ranking, not this job's progress."""
    import time
    p = db.create_project("Personal finance", "How to build a budget and invest the rest")
    coll = _collection(p["id"], relevance.BATCH * (relevance.BATCHES_PER_RUN + 1))     # 3 batches: 2 runs + a finish
    # first ranking, run to completion the way the queue would
    jid = db.create_job("rank_proposed", {"collection_id": coll, "project_id": p["id"], "want": 20})["id"]
    for _ in range(3):
        claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
        if claimed is None: break
        jobs.execute(claimed, worker_id="w")
    assert db.get_job(jid)["status"] == "done"
    assert all(r.get("relevance") is not None for r in db.proposed_sources(coll, p["id"]))
    time.sleep(0.02)
    # re-rank: every row already carries a score; the job must still finish in exactly ceil(3/2) = 2 runs
    jid2 = db.create_job("rank_proposed", {"collection_id": coll, "project_id": p["id"], "want": 20})["id"]
    statuses = []
    for _ in range(6):
        claimed = db.claim_job(kinds=("rank_proposed",), worker_id="w")
        if claimed is None: break
        statuses.append(jobs.execute(claimed, worker_id="w"))
        if statuses[-1] == "done": break
    assert statuses == ["queued", "done"], statuses     # before: queued, queued, queued, queued, ... forever
