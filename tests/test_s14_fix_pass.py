"""S14 — the fix pass of 2026-09-10 (0.61.0). (Sorts after test_s13.)

Nine faults, all found by measuring Kyle's live data or by looking at his actual screen. The ones with tests here:

* **A clause made only of generic words produced a "strong" match.** 0.60.2 fixed the matcher and the Airbnb
  income video came back anyway. Measured on his corpus (1,229 sources with chunks), his goal splits into six
  clauses whose most distinctive words are `auditing` (15 sources), `cognitive` (16), `reusable` (28),
  `architecture` (38) — and then `improving` (85) and `designing` (125). Every bad match comes from the last two,
  and no matcher can help: a video about Airbnb income genuinely does discuss improving and designing things. Nor
  can rarity separate them — `improving` is in 6.9% of the library and `ux` in 5.2%. So the fault is in the QUERY.
* **A re-scan could not take a suggestion away.** `upsert` only inserted or updated, so rows the fixed matcher no
  longer produces stayed on the card for ever.
* **A progress callback overwrote a terminal failure message.** Four failed jobs read
  `[download] Finished downloading playlist: Mark J Kohler`; the real reason ("metadata fetch timed out after
  4 min") was in `job_events` all along. yt-dlp went on downloading after the job had failed and reported over it.
* **The Master Plan could not build.** `build_plan` waited on ALL_SUCCESS across 199 ingest jobs; 11 succeeded, so
  it refused to run. On a project that size something always fails.
* **14 failed sources, all unclassified** — a deleted video, a carousel with no video, a 403 and a timeout were
  indistinguishable, so the hopeless ones could not be told from the retryable ones.
* **A warning banner that said zero**: "⚠ 0 sources analysed against older inputs · 15 re-analysing".
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_fixpass_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import bootstrap, db, staleness  # noqa: E402
from neurosearch.config import settings  # noqa: E402

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "neurosearch", "web", "index.html")


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _source(sid, texts, title="t"):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, channel, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (sid, "youtube", sid, f"https://x/{sid}", title, "ch", "ready", 1.0, 1.0))
        for i, t in enumerate(texts):
            conn.execute("INSERT INTO chunks (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                         (sid, i, i * 60.0, i * 60.0 + 60.0, t))


# ------------------------------------------------------------------ 1. a generic clause cannot make a strong match

def test_a_query_of_generic_words_is_marked_weak(fresh):
    """The shape of Kyle's real goal: four clauses with a distinctive word, two made of words the library uses
    everywhere. The cut is the median of the queries' own rarities, so it adapts to the goal and the library."""
    _source("ux1", ["progressive disclosure and cognitive load in ux"], "UX")
    _source("ux2", ["auditing an existing information architecture"], "IA")
    for i in range(9):                       # a library that talks about improving and designing all day
        _source(f"biz{i}", [f"improving the business and designing offers {i}", "improving margins"], f"biz{i}")
    st = bootstrap.query_strength(["reducing cognitive load", "when auditing an existing one",
                                   "improving complex web applications",
                                   "useful when designing a new application"])
    assert "improving complex web applications" in st["weak"]
    assert "useful when designing a new application" in st["weak"]
    assert "reducing cognitive load" not in st["weak"]
    assert "when auditing an existing one" not in st["weak"]
    # both are weak for the ABSOLUTE reason — every word in them is everywhere in this library — which needs no
    # distribution. A word that is too RARE to anchor on is the opposite of generic and must never be caught here.
    assert set(st["too_common"]) == set(st["weak"])
    assert "cannot tell one subject from another" in st["note"]


def test_two_queries_are_not_enough_to_rank(fresh):
    """With one or two queries there is no distribution to compare against, so the rule stays off — a guard that
    can only turn the feature OFF cannot invent a false negative."""
    _source("s1", ["anything at all"])
    st = bootstrap.query_strength(["reducing cognitive load", "auditing an existing one"])
    assert st["weak"] == [] and st["cut"] is None
    assert "too few searches" in st["note"]


def test_a_hit_that_only_matched_weak_queries_cannot_be_strong():
    weak_only = {"queries": ["q1", "q2"], "coverage": 0.9, "passage_coverage": 0.9, "distinctive_queries": []}
    real = {"queries": ["q1", "q2"], "coverage": 0.9, "passage_coverage": 0.9, "distinctive_queries": ["q1"]}
    assert bootstrap._band(weak_only) == "possible"
    assert bootstrap._band(real) == "strong"


def test_an_older_row_without_the_measure_is_unaffected():
    assert bootstrap._band({"queries": ["q1", "q2"], "coverage": 0.9}) == "strong"


def test_the_card_holds_back_a_generic_only_match():
    ui = open(UI, encoding="utf-8").read()
    assert "const weakOnly = live.filter(h => h.weak_query_only)" in ui
    assert "matched only the generic parts of your goal" in ui
    assert "show them anyway" in ui                     # held back, never deleted
    assert "generic match" in ui


# ------------------------------------------------------------------ 2. a re-scan can take a suggestion away

def test_a_rescan_retires_what_it_no_longer_suggests(fresh):
    p = db.create_project("retire", brief="b")
    db.upsert_project_reuse(p["id"], [
        {"object_kind": "source", "object_id": "keep", "band": "strong", "score": 1.0, "why": "{}", "origin": "{}"},
        {"object_kind": "source", "object_id": "gone", "band": "strong", "score": 1.0, "why": "{}", "origin": "{}"},
    ], "rev1", scan_version=bootstrap.SCAN_VERSION)
    assert db.retire_project_reuse(p["id"], ["keep"]) == 1
    states = {r["object_id"]: r["state"] for r in db.list_project_reuse(p["id"])}
    assert states == {"keep": "suggested", "gone": "retired"}
    live = [h for h in bootstrap.state(p["id"])["sources"] if h["state"] == "suggested"]
    assert [h["source_id"] for h in live] == ["keep"]
    assert bootstrap.state(p["id"])["counts"]["retired"] == 1


def test_a_decision_the_user_made_is_never_retired(fresh):
    """The scan authored the suggestion, so it may withdraw it. It did not author the user's answer."""
    p = db.create_project("retire2", brief="b")
    db.upsert_project_reuse(p["id"], [
        {"object_kind": "source", "object_id": "a", "band": "strong", "score": 1.0, "why": "{}", "origin": "{}"},
        {"object_kind": "source", "object_id": "b", "band": "strong", "score": 1.0, "why": "{}", "origin": "{}"},
    ], "rev1")
    db.set_project_reuse_state(p["id"], ["a"], "attached")
    db.set_project_reuse_state(p["id"], ["b"], "dismissed")
    assert db.retire_project_reuse(p["id"], []) == 0
    assert {r["object_id"]: r["state"] for r in db.list_project_reuse(p["id"])} == {"a": "attached", "b": "dismissed"}


def test_retiring_nothing_is_free(fresh):
    p = db.create_project("retire3", brief="b")
    assert db.retire_project_reuse(p["id"], []) == 0


# ------------------------------------------------------------------ 3. a finished job's diagnosis cannot be erased

def test_progress_never_overwrites_a_finished_jobs_message(fresh):
    job = db.create_job("ingest_url", {"url": "https://x/y"})
    jid = job["id"] if isinstance(job, dict) else job
    db.claim_job(worker_id="w1")
    db.finish_job(jid, db.get_job(jid)["run_id"], "failed", message="error: metadata fetch timed out after 4 min")
    # yt-dlp goes on downloading and reports afterwards, exactly as it did on Kyle's machine
    db.update_job(jid, progress=1.0, message="[download] Finished downloading playlist: Mark J Kohler")
    j = db.get_job(jid)
    assert j["status"] == "failed"
    assert j["message"] == "error: metadata fetch timed out after 4 min"


def test_a_deliberate_status_change_still_works(fresh):
    """The guard is on PROGRESS, not on status transitions — `update_job(status=…)` must still be able to act."""
    job = db.create_job("ingest_url", {"url": "https://x/z"})
    jid = job["id"] if isinstance(job, dict) else job
    db.update_job(jid, status="failed", message="error: real reason")
    assert db.get_job(jid)["message"] == "error: real reason"


def test_progress_on_a_live_job_is_unaffected(fresh):
    job = db.create_job("ingest_url", {"url": "https://x/w"})
    jid = job["id"] if isinstance(job, dict) else job
    db.update_job(jid, progress=0.5, message="downloading…")
    assert db.get_job(jid)["message"] == "downloading…"


def test_the_progress_hook_is_cleared_when_a_job_ends():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "jobs.py"), encoding="utf-8").read()
    assert "media.set_progress_hook(None)" in src


# ------------------------------------------------------------------ 4. the plan builds from what landed

def test_the_plan_waits_for_the_work_to_settle_not_to_be_perfect():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "staleness.py"), encoding="utf-8").read()
    block = src[src.index('if "plan" in what'):src.index('return {"queued": len(jobs)')]
    assert 'dependency_policy="ALL_TERMINAL"' in block
    assert "ALL_SUCCESS" in block                        # the decision is recorded, not silently swapped


def test_all_terminal_lets_a_dependent_job_run_after_a_failure(fresh):
    a = db.create_job("ingest_url", {"url": "https://a"})
    aid = a["id"] if isinstance(a, dict) else a
    b = db.create_job("build_plan", {"project_id": "p"}, blocked_by=[aid], dependency_policy="ALL_TERMINAL")
    bid = b["id"] if isinstance(b, dict) else b
    db.claim_job(worker_id="w1")
    db.finish_job(aid, db.get_job(aid)["run_id"], "failed", message="error: gone")
    claimed = db.claim_job(worker_id="w2")
    assert claimed and claimed["id"] == bid              # under ALL_SUCCESS this job would have been failed instead
    assert db.get_job(bid)["status"] == "running"


# ------------------------------------------------------------------ 5. a failure says whether a retry could help

@pytest.mark.parametrize("error,expected", [
    ("This Instagram post has no video (images/carousel) — nothing to transcribe.", "no_media"),
    ("[youtube] 69d-NPc5yEo: This video is not available", "unavailable"),
    ("[generic] id1572445829: Unable to download webpage: HTTP Error 404: Not Found", "not_found"),
    ("Reddit refused the listing — www.reddit.com: HTTP 403", "blocked"),
    ("error: transcript came back empty", "empty_transcript"),
    ("metadata fetch timed out after 4 min — the connection stalled", "timed_out"),
    ("[instagram:user] sbaloanguy1: Unable to extract data", "extractor"),
    ("something nobody has seen before", "other"),
    (None, None),
])
def test_every_real_failure_from_his_project_classifies(error, expected):
    assert db.failure_class(error) == expected


def test_permanence_is_the_distinction_that_matters():
    """"Retry all" is useless if half the list can never work. `permanent` is what lets the UI offer the right
    action for each."""
    assert db.failure_is_permanent("no_media") is True
    assert db.failure_is_permanent("unavailable") is True
    assert db.failure_is_permanent("timed_out") is False
    assert db.failure_is_permanent("blocked") is False


def test_a_failure_is_classified_as_it_is_recorded(fresh):
    _source("s1", ["x"])
    db.set_source_status("s1", "failed", "This video is not available")
    r = db.get_source("s1")
    assert r["status"] == "failed" and r["error_class"] == "unavailable"


def test_a_browser_solvable_class_is_never_overwritten(fresh):
    """`acquire` sets that one deliberately and the extension queue reads it — a text classifier must not clobber
    a state another subsystem owns."""
    _source("s2", ["x"])
    with db.tx() as conn:
        conn.execute("UPDATE sources SET error_class='browser_solvable:login_wall' WHERE id='s2'")
    db.set_source_status("s2", "failed", "HTTP 403 blocked")
    assert db.get_source("s2")["error_class"] == "browser_solvable:login_wall"


def test_a_success_clears_nothing_it_should_not(fresh):
    _source("s3", ["x"])
    db.set_source_status("s3", "ready", None)
    assert db.get_source("s3")["error_class"] is None


def test_old_failures_are_backfilled_once_and_idempotently(fresh):
    _source("old1", ["x"]); _source("old2", ["x"])
    with db.tx() as conn:
        conn.execute("UPDATE sources SET status='failed', error='This video is not available', error_class=NULL WHERE id='old1'")
        conn.execute("UPDATE sources SET status='failed', error='HTTP 403', error_class=NULL WHERE id='old2'")
    assert db.backfill_failure_classes() == 2
    assert db.backfill_failure_classes() == 0
    assert db.get_source("old1")["error_class"] == "unavailable"
    assert db.get_source("old2")["error_class"] == "blocked"


def test_health_separates_hopeless_from_retryable(fresh):
    _source("f1", ["x"]); _source("f2", ["x"])
    db.set_source_status("f1", "failed", "This video is not available")
    db.set_source_status("f2", "failed", "metadata fetch timed out")
    h = db.health()["failures"]
    assert h["failed"] == 2 and h["permanent"] == 1
    assert {c["class"] for c in h["classes"]} == {"unavailable", "timed_out"}
    assert "worth retiring" in h["note"]


def test_the_row_says_which_it_is():
    ui = open(UI, encoding="utf-8").read()
    assert "PERMANENT_FAILURES" in ui and "will not work" in ui and "retryable" in ui


# ------------------------------------------------------------------ 6. a warning that says zero, and a poll storm

def test_a_banner_with_nothing_stale_does_not_warn():
    ui = open(UI, encoding="utf-8").read()
    assert "const head = t.stale_total" in ui
    assert "⟳ Re-analysing ${reb.length}" in ui
    assert "Three answers, not one bill" not in ui       # the garbled line is gone
    assert "Every option below shows both prices" in ui


def test_the_findings_tab_asks_whether_anything_changed_first():
    """Five whole-project passes every four seconds, seen in his own browser. The Sources view has had the 13 ms
    revision check since 0.46.2; Findings never got it."""
    ui = open(UI, encoding="utf-8").read()
    assert "async function notesTick()" in ui and "/tick`" in ui
    body = ui[ui.index("async function notesTick()"):ui.index("async function loadNotes()")]
    assert "notesTicks >= RECONCILE_EVERY" in body       # and it still reconciles on a slow interval
