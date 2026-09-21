"""A deliberate rejection is worth as much as a deliberate keep (2026-09-20).

Kyle, part-way through reviewing the never-judged pool one item at a time: "are we helping train the app in any
meaningful way by doing this?" Traced honestly, the answer was lopsided. A Keep fed three consumers (the review
cutoff via `pos`, `creator_yield`'s pool ordering, and the actual ingested material). A Lose fed essentially
none of the surfaces he uses: the negative half of `creator_disposition` is read only by `candidates.rerank`,
which runs only inside `next_batch`, which only the CLI and the raw API reach — never the web UI.

`creator_verdict` closes that. It reads ONLY explicit decisions — `acquired` and `user_dismissed` — and is
blind to `skipped_low_relevance`, which is the conflation that caused the original sign error: an auto-skip
records that nobody looked, not that anyone objected.
"""
from __future__ import annotations

import json

import pytest

from neurosearch import candidates as cand
from neurosearch import db, ingest
from neurosearch.config import settings


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _seed(pid, creator, rows):
    for ext, state in rows:
        cid = cand.remember([{"external_id": ext, "url": f"https://youtu.be/{ext}", "title": ext,
                              "creator": creator}], "youtube", pid, {"kind": "channel", "title": creator})[0]
        cand.mark(pid, [cid], state, reason="seeded", relevance=40)


def _project():
    return db.create_project("verdict", brief="how to buy a small business")["id"]


def test_a_creator_you_keep_rejecting_goes_negative(fresh):
    pid = _project()
    _seed(pid, "Noise Channel", [("a", "user_dismissed"), ("b", "user_dismissed"), ("c", "user_dismissed")])
    v = cand.creator_verdict(pid)["Noise Channel"]
    assert v["dismissed"] == 3 and v["kept"] == 0
    assert v["adjust"] == -cand.DISPOSITION_MAX_ADJUST
    assert "rejected" in v["why"]


def test_a_creator_you_keep_is_positive_by_the_same_amount(fresh):
    """Symmetry is the point: a rejection must be worth what a keep is worth."""
    pid = _project()
    _seed(pid, "Good Channel", [("a", "acquired"), ("b", "acquired"), ("c", "acquired")])
    v = cand.creator_verdict(pid)["Good Channel"]
    assert v["adjust"] == cand.DISPOSITION_MAX_ADJUST
    assert abs(cand.creator_verdict(pid)["Good Channel"]["adjust"]) == cand.DISPOSITION_MAX_ADJUST


def test_a_mixed_creator_lands_in_between(fresh):
    pid = _project()
    _seed(pid, "Mixed", [("a", "acquired"), ("b", "acquired"), ("c", "acquired"), ("d", "user_dismissed")])
    v = cand.creator_verdict(pid)["Mixed"]
    assert v["kept"] == 3 and v["dismissed"] == 1 and v["decided"] == 4
    assert 0 < v["adjust"] < cand.DISPOSITION_MAX_ADJUST      # (3-1)/4 = 0.5 -> +6


def test_auto_skips_are_invisible_to_it(fresh):
    """The sign error that started all of this: 360 bulk-approve auto-skips made a creator look rejected."""
    pid = _project()
    _seed(pid, "Acquisitions Anonymous", [("k1", "acquired")]
          + [(f"s{i}", "skipped_low_relevance") for i in range(40)])
    v = cand.creator_verdict(pid)["Acquisitions Anonymous"]
    assert v["kept"] == 1 and v["dismissed"] == 0 and v["decided"] == 1   # the 40 auto-skips do not count
    assert v["adjust"] == cand.DISPOSITION_MAX_ADJUST                     # still rescued, as the cliff fix intended


def test_one_stray_decision_is_not_a_verdict(fresh):
    """Below the minimum the older, generous rule stands, so the cliff fix does not regress."""
    pid = _project()
    _seed(pid, "Barely Known", [("a", "acquired")])
    assert cand.creator_verdict(pid)["Barely Known"]["adjust"] == cand.DISPOSITION_MAX_ADJUST
    _seed(pid, "One Reject", [("z", "user_dismissed")])
    assert cand.creator_verdict(pid)["One Reject"]["adjust"] == 0         # one Lose does not bury a creator


def _review(rows):
    coll = db.upsert_collection("channel", "chan", "https://www.youtube.com/@chan", "chan")
    pid = _project()
    db.kv_set(f"review:{coll['id']}", json.dumps({"project_id": pid}))
    db.connect().execute("INSERT OR IGNORE INTO project_collections (project_id, collection_id) VALUES (?,?)",
                         (pid, coll["id"]))
    ids = {}
    for ext, creator, rel in rows:
        s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://youtu.be/{ext}", title=ext,
                             status="proposed")
        db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)",
                             (s["id"], coll["id"]))
        db.upsert_analysis(pid, s["id"], "relevance", relevance=rel, relevance_why="w", prompt_version="t",
                           input_hash=f"h-{ext}")
        cand.remember([{"external_id": ext, "url": f"https://youtu.be/{ext}", "title": ext, "creator": creator}],
                      "youtube", pid, {"kind": "channel", "title": creator})
        ids[ext] = s["id"]
    db.connect().commit()
    return coll["id"], pid, ids


def _state(pid, ext):
    return db.connect().execute(
        "SELECT cp.state FROM candidate_projects cp JOIN candidates c ON c.id=cp.candidate_id "
        "WHERE cp.project_id=? AND c.external_id=?", (pid, ext)).fetchone()["state"]


def test_review_time_now_demotes_a_creator_you_rejected(fresh):
    """End to end, and the whole point: an item that WOULD have cleared the cutoff no longer does, because the
    person rejected that creator by hand three times."""
    coll, pid, ids = _review([("keep", "Other", 90), ("borderline", "Rejected Co", 55)])
    _seed(pid, "Rejected Co", [("x1", "user_dismissed"), ("x2", "user_dismissed"), ("x3", "user_dismissed")])
    ingest.approve_proposed(coll, source_ids=[ids["keep"]])
    # 55 - 12 = 43, under the 50 cutoff: filed as a relevance judgement, not as "outside the number picked"
    assert _state(pid, "borderline") == "skipped_low_relevance"


def test_review_time_still_rescues_a_creator_you_keep(fresh):
    coll, pid, ids = _review([("keep", "Other", 90), ("borderline", "Trusted Co", 45)])
    _seed(pid, "Trusted Co", [("y1", "acquired"), ("y2", "acquired"), ("y3", "acquired")])
    ingest.approve_proposed(coll, source_ids=[ids["keep"]])
    # 45 + 12 = 57, clears the cutoff, so it is only "outside the number you picked" — recoverable, not buried
    assert _state(pid, "borderline") == "skipped_limit"


def test_an_unknown_creator_is_unaffected(fresh):
    coll, pid, ids = _review([("keep", "Other", 90), ("borderline", "Never Seen", 55)])
    ingest.approve_proposed(coll, source_ids=[ids["keep"]])
    assert _state(pid, "borderline") == "skipped_limit"      # +0, exactly as before any of this existed
