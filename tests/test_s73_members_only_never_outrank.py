"""S73 — a members-only YouTube video is never ranked above a video that can be downloaded (Kyle, 2026-09-18).

The app never holds the person's channel-membership cookie for bulk downloads (CLAUDE.md), so a members-only video
in a channel listing cannot be ingested: if it ranked into the top N it took a slot from a watchable video, was
auto-ticked, spent a ranking call, failed at download with "Join this channel …", and — classified `login_wall`,
retryable — was retried. Now: the listing carries `access_gate` from yt-dlp's `availability`; a gated video sorts
LAST in the review whatever its relevance, is never sent to the ranker, is never auto-ticked, is labelled, and a
download refusal back-fills the gate and is a permanent failure class.
"""
from __future__ import annotations

import pytest

from neurosearch import db, media, relevance
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


def test_listing_availability_becomes_the_gate():
    assert media.access_gate_of({"availability": "subscriber_only"}) == "members_only"
    assert media.access_gate_of({"availability": "premium_only"}) == "premium"
    assert media.access_gate_of({"availability": "needs_auth"}) == "needs_auth"
    assert media.access_gate_of({"availability": "public"}) is None
    assert media.access_gate_of({"availability": "unlisted"}) is None
    assert media.access_gate_of({}) is None
    assert media.access_gate_of({"title": "Q&A (Members Only)"}) == "members_only"


def _collection_with(fresh_rows):
    coll = db.upsert_collection("channel", "chan", "https://www.youtube.com/@chan", "chan")
    pid = db.create_project("s73", brief="how to buy a small business")["id"]
    ids = []
    for ext, title, gate, rel in fresh_rows:
        s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://youtu.be/{ext}", title=title, status="proposed", access_gate=gate)
        db.connect().execute("INSERT OR IGNORE INTO source_collections (source_id, collection_id) VALUES (?,?)", (s["id"], coll["id"]))
        if rel is not None:
            db.upsert_analysis(pid, s["id"], "relevance", relevance=rel, relevance_why="w", prompt_version="t", input_hash=f"h-{ext}")
        ids.append(s["id"])
    db.connect().commit()
    return coll["id"], pid, ids


def test_gated_videos_sort_last_whatever_their_relevance(fresh):
    coll, pid, (public_low, gated_high, public_high, gated_unranked) = _collection_with([
        ("a", "public, low relevance", None, 20),
        ("b", "members only, high relevance", "members_only", 95),
        ("c", "public, high relevance", None, 80),
        ("d", "members only, unranked", "members_only", None),
    ])
    order = [r["id"] for r in db.proposed_sources(coll, pid)]
    assert order == [public_high, public_low, gated_high, gated_unranked], \
        "every watchable video precedes every gated one; within each group relevance still orders"


def test_gated_videos_are_never_sent_to_the_ranker(fresh):
    coll, pid, ids = _collection_with([("a", "public", None, None), ("b", "members", "members_only", None), ("c", "public 2", None, None)])
    rows = db.proposed_sources(coll, pid)
    pool, rest = relevance._pool(rows)
    assert {r["external_id"] for r in pool} == {"a", "c"}
    assert [r["external_id"] for r in rest] == ["b"]


def test_a_download_refusal_backfills_the_gate_and_is_permanent(fresh):
    s = db.upsert_source(platform="youtube", external_id="m", url="https://youtu.be/m", title="t", status="pending")
    assert db.get_source(s["id"])["access_gate"] is None
    db.set_source_status(s["id"], "failed", error="[youtube] m: Join this channel to get access to members-only content like this video, and other exclusive perks.")
    row = db.get_source(s["id"])
    assert row["access_gate"] == "members_only"
    assert row["error_class"] == "members_only" and db.failure_is_permanent(row["error_class"])
    assert db.failure_class("Sign in to confirm you're not a bot") == "login_wall" and not db.failure_is_permanent("login_wall")


def test_review_card_never_auto_ticks_a_gated_video_and_labels_it():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web" / "js" / "sources.js").read_text()
    assert "|| s.access_gate) off.add(s.id)" in js, "a gated video must start unticked"
    assert "members only" in js and "s.access_gate ===" in js, "the review row must say why it is last"
