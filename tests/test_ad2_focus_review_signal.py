"""Focus review (2026-09-20) — a deliberate skip is the PERSON's verdict, not the ranker's.

Kyle: "I have been BULK approving everything so I don't think I have been providing good data back to the app."
That is the defect this closes. Bulk-approving a review card says nothing about the rows left unticked — the
person never looked at them — yet they were filed as `skipped_low_relevance`, which `creator_disposition` reads
as a half-weight rejection. The app was attributing opinions to Kyle that he never formed, and then ranking on
them.

`approve_proposed(..., dismissed_ids=[...])` is how focus review says "I looked at this one and said no":
recorded as `user_dismissed`, at full weight, and kept out of the automatic buckets entirely.
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


def _review(rows):
    """rows: (external_id, title, creator, relevance). Returns (collection_id, project_id, {ext: source_id})."""
    coll = db.upsert_collection("channel", "chan", "https://www.youtube.com/@chan", "chan")
    pid = db.create_project("focus", brief="how to buy a small business")["id"]
    db.kv_set(f"review:{coll['id']}", json.dumps({"project_id": pid}))
    db.connect().execute("INSERT OR IGNORE INTO project_collections (project_id, collection_id) VALUES (?,?)",
                         (pid, coll["id"]))
    ids = {}
    for ext, title, creator, rel in rows:
        s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://youtu.be/{ext}",
                             title=title, status="proposed")
        db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)",
                             (s["id"], coll["id"]))
        db.upsert_analysis(pid, s["id"], "relevance", relevance=rel, relevance_why="w",
                           prompt_version="t", input_hash=f"h-{ext}")
        cand.remember([{"external_id": ext, "url": f"https://youtu.be/{ext}", "title": title, "creator": creator}],
                      "youtube", pid, {"kind": "channel", "title": creator})
        ids[ext] = s["id"]
    db.connect().commit()
    return coll["id"], pid, ids


def _state(pid, ext):
    return db.connect().execute(
        "SELECT cp.state FROM candidate_projects cp JOIN candidates c ON c.id=cp.candidate_id "
        "WHERE cp.project_id=? AND c.external_id=?", (pid, ext)).fetchone()["state"]


def test_a_deliberate_skip_is_recorded_as_the_persons_own_no(fresh):
    coll, pid, ids = _review([
        ("a", "kept one", "Acquiring Minds", 80),
        ("b", "skipped on purpose", "Acquiring Minds", 75),   # high score, but the person said no
        ("c", "never looked at", "Acquiring Minds", 20),
    ])
    res = ingest.approve_proposed(coll, source_ids=[ids["a"]], dismissed_ids=[ids["b"]])
    assert res["started"] == 1
    assert res["dismissed"] == 1
    assert _state(pid, "a") == "acquired"
    assert _state(pid, "b") == "user_dismissed"          # the person's verdict, at full weight
    assert _state(pid, "c") == "skipped_low_relevance"   # untouched rows keep the old automatic classification


def test_a_high_scoring_deliberate_skip_does_not_become_skipped_limit(fresh):
    """The bug this guards: b scores 75, well above the cutoff, so without the dismissed_ids path it would be
    filed `skipped_limit` — 'outside the number selected' — which carries NO preference signal at all."""
    coll, pid, ids = _review([("a", "kept", "X", 80), ("b", "rejected", "X", 75)])
    ingest.approve_proposed(coll, source_ids=[ids["a"]], dismissed_ids=[ids["b"]])
    assert _state(pid, "b") == "user_dismissed"


def test_dismissing_everything_records_every_one_of_them(fresh):
    coll, pid, ids = _review([("a", "no", "X", 70), ("b", "no", "X", 60), ("c", "no", "X", 50)])
    res = ingest.approve_proposed(coll, source_ids=[], dismissed_ids=list(ids.values()))
    assert res["started"] == 0 and res["dismissed"] == 3
    assert all(_state(pid, e) == "user_dismissed" for e in ("a", "b", "c"))


def test_a_contradictory_id_in_both_lists_is_kept_not_dismissed(fresh):
    """Keeping is the explicit, irreversible-ish action (it queues a download); if the two lists disagree the
    safe reading is the one the person can undo by dismissing later."""
    coll, pid, ids = _review([("a", "both", "X", 70)])
    res = ingest.approve_proposed(coll, source_ids=[ids["a"]], dismissed_ids=[ids["a"]])
    assert res["started"] == 1 and res["dismissed"] == 0
    assert _state(pid, "a") == "acquired"


def test_the_old_bulk_path_is_completely_unchanged(fresh):
    """Focus review is alongside the list, not instead of it — approving with no dismissed_ids must behave
    exactly as it did before this existed."""
    coll, pid, ids = _review([("a", "picked", "X", 80), ("b", "under cutoff", "Y", 20), ("c", "over cutoff", "Z", 70)])
    res = ingest.approve_proposed(coll, source_ids=[ids["a"]])
    assert res["started"] == 1 and res["dismissed"] == 0
    assert _state(pid, "a") == "acquired"
    assert _state(pid, "b") == "skipped_low_relevance"
    assert _state(pid, "c") == "skipped_limit"


def test_deliberate_skips_reach_creator_disposition_at_full_weight(fresh):
    """The point of the whole change. A creator the person rejected item by item must read as rejected —
    not at the half weight `skipped_low_relevance` carries, which exists precisely because an auto-skip is
    NOT a judgement."""
    coll, pid, ids = _review([
        ("k", "kept", "Mixed Creator", 80),
        ("d1", "no", "Mixed Creator", 70), ("d2", "no", "Mixed Creator", 65), ("d3", "no", "Mixed Creator", 60),
    ])
    ingest.approve_proposed(coll, source_ids=[ids["k"]],
                            dismissed_ids=[ids["d1"], ids["d2"], ids["d3"]])
    disp = cand.creator_disposition(pid)["Mixed Creator"]
    assert disp["pos"] == 1
    assert disp["neg"] == 3            # full weight, not 1.5
    assert disp["decided"] == 4
    assert disp["adjust"] < 0          # and it actually moves the ranking against that creator
    assert "rejected" in (disp["why"] or "")


def test_gated_items_are_never_turned_into_a_judgement(fresh):
    """A members-only video cannot be ingested at all, so neither keeping nor skipping it means anything about
    the person's taste. The UI leaves them out; the backend must not record one either if an id slips through."""
    coll, pid, ids = _review([("a", "kept", "X", 80)])
    g = db.upsert_source(platform="youtube", external_id="g", url="https://youtu.be/g", title="gated",
                         status="proposed", access_gate="members_only")
    db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)",
                         (g["id"], coll))
    cand.remember([{"external_id": "g", "url": "https://youtu.be/g", "title": "gated", "creator": "X"}],
                  "youtube", pid, {"kind": "channel", "title": "X"})
    db.connect().commit()
    ingest.approve_proposed(coll, source_ids=[ids["a"]], dismissed_ids=[g["id"]])
    assert _state(pid, "g") == "needs_membership"     # not user_dismissed


def test_the_api_accepts_and_forwards_dismissed_ids(fresh, monkeypatch):
    from neurosearch import api
    seen = {}
    monkeypatch.setattr(api.ingest, "approve_proposed",
                        lambda c, s=None, d=None: seen.update(collection=c, source_ids=s, dismissed_ids=d) or {"ok": 1})
    api.api_approve("coll-1", api.ApproveIn(source_ids=["a"], dismissed_ids=["b", "c"]))
    assert seen == {"collection": "coll-1", "source_ids": ["a"], "dismissed_ids": ["b", "c"]}
    seen.clear()
    api.api_approve("coll-2", api.ApproveIn(source_ids=["a"]))      # the old callers still work
    assert seen["dismissed_ids"] is None
