"""S22 — a research read may be a moment old; a person's own verdict may not (0.62.8). (Sorts after test_s21.)

**Measured on Kyle's project with the job queue otherwise IDLE**, right after 3,314 findings were approved at his
request:

    research/overview?full=1     38.7 s cold   33.4 s WARM
    /research (full state)       75.5 s cold   63.1 s warm
    claims workbench (100)       14.8 s cold   47.9 s warm
    findings (100)               55.1 s cold    1.7 s warm

Sampling `db.project_research_revision` every 2.5 s explained all of it at once — the claim count was moving
**15,792 → 15,800 → 15,811**, about four a second, because `harvest` was turning the newly approved findings into
Claims. Legitimate $0 work with no model call; but a strict revision key means every read recomputes for as long as
it runs, and the areas/overview pass costs tens of seconds on 15,800 Claims. The third surface to learn the 0.61.2
lesson: **a cache whose key changes faster than its value can be computed is not a cache.**

And then the correction that matters. Making the read stale-tolerant broke two frozen gates —
`test_attention_is_what_needs_the_user_not_the_claim_count` and
`test_one_verdict_clears_a_whole_watch_out_and_dismissal_is_durable` — and they were right to break: a person who
has just dismissed a watch-out is looking at the screen, and serving them the answer from before their own click is
not "a moment old", it is wrong.

So the rule is by AUTHOR, not by age. Background churn is served stale with `as_of_current: False`; a recorded human
decision drops the entry so the next read recomputes. `research_view.user_changed` is that lever, called from every
path where a person's verdict lands.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_stale_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import cache, claims, db, knowledge, research_view as rv  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    cache.invalidate()
    yield
    db._local.conn = None


def _claim(pid, text, cid):
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, topic, status, strength, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (cid, pid, text, "financing", "proposed", "weak", 1.0, 1.0))


# ------------------------------------------------------------------ churn is served stale

def test_a_read_during_background_churn_does_not_wait(fresh, monkeypatch):
    p = db.create_project("churn", brief="b")
    _claim(p["id"], "sellers finance ten percent", "c1")
    first = rv.overview(p["id"], full=True)
    assert first["as_of_current"] is True
    _claim(p["id"], "a second claim arrives from harvest", "c2")        # the revision moves
    calls = []
    real = rv._overview_uncached
    monkeypatch.setattr(rv, "_overview_uncached", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    again = rv.overview(p["id"], full=True)
    assert again["as_of_current"] is False and again["recomputing"] is True
    assert again["questions_total"] == first["questions_total"]         # the previous answer, returned at once


def test_the_stale_value_is_one_this_app_computed(fresh):
    """Nothing is fabricated: what comes back is a real earlier answer, and it says how current it is."""
    p = db.create_project("real", brief="b")
    _claim(p["id"], "a claim", "c1")
    a = rv.overview(p["id"])
    _claim(p["id"], "another", "c2")
    b = rv.overview(p["id"])
    assert b["summary"] == a["summary"] and b["as_of_current"] is False


def test_it_catches_up_on_its_own(fresh):
    import time as _t
    p = db.create_project("catchup", brief="b")
    _claim(p["id"], "a claim", "c1")
    rv.overview(p["id"])
    _claim(p["id"], "another", "c2")
    rv.overview(p["id"])                                   # stale + a background refresh
    for _ in range(50):
        if rv.overview(p["id"])["as_of_current"]:
            break
        _t.sleep(0.1)
    assert rv.overview(p["id"])["as_of_current"] is True


# ------------------------------------------------------------------ a person's verdict is not churn

def test_accepting_a_claim_is_visible_on_the_next_read(fresh):
    p = db.create_project("verdict", brief="b")
    _claim(p["id"], "sellers finance ten percent", "c1")
    rv.overview(p["id"])                                   # warm the entry
    claims.set_status("c1", "accepted")
    assert rv.overview(p["id"])["as_of_current"] is True   # recomputed, not served from before the click


def test_dismissing_a_watch_out_is_visible_on_the_next_read(fresh):
    p = db.create_project("tension", brief="b")
    _claim(p["id"], "a claim", "c1")
    with db.tx() as conn:
        conn.execute("INSERT INTO research_tensions (id, project_id, kind, claim_id, description, impact, status, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     ("t1", p["id"], "NOVEL", "c1", "one source says otherwise", "high", "open", 1.0, 1.0))
    before = rv.overview(p["id"])["summary"]["issues_total"]
    knowledge.set_tension_status("t1", "dismissed")
    after = rv.overview(p["id"])
    assert after["as_of_current"] is True and after["summary"]["issues_total"] == before - 1


def test_settling_a_question_is_visible_on_the_next_read(fresh):
    p = db.create_project("target", brief="b")
    _claim(p["id"], "a claim", "c1")
    with db.tx() as conn:
        conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", ("tg1", p["id"], "does it hold?", "open", 1.0, 1.0))
    assert rv.overview(p["id"], full=True)["questions_open"] == 1
    knowledge.set_target_status("tg1", "closed_by_user")
    out = rv.overview(p["id"], full=True)
    assert out["as_of_current"] is True and out["questions_open"] == 0


def test_the_lever_reports_what_it_dropped(fresh):
    p = db.create_project("lever", brief="b")
    _claim(p["id"], "a claim", "c1")
    rv.overview(p["id"]); rv.areas(p["id"])
    assert rv.user_changed(p["id"]) >= 2
    assert rv.user_changed(p["id"]) == 0                   # idempotent: nothing left to drop


def test_a_cache_drop_never_fails_a_recorded_decision(fresh, monkeypatch):
    """The decision is the durable thing; the cache is not. If dropping it raises, the status still stands."""
    p = db.create_project("safe", brief="b")
    _claim(p["id"], "a claim", "c1")
    monkeypatch.setattr(rv, "user_changed", lambda pid: (_ for _ in ()).throw(RuntimeError("cache exploded")))
    claims.set_status("c1", "accepted")
    assert claims.get("c1")["status"] == "accepted"
