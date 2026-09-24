"""S89 (2026-09-23) — Kyle's screenshot: two review cards, one ranked, one "Newest first" with 380 of 380 ticked
although its rank_proposed job had scored every video for this project. `pending_reviews` called
`proposed_sources(collection_id)` with no project, which falls back to the FIRST project ever linked to the channel —
so a channel he had used in an earlier project read its relevance from that project and found none. Relevance is
project-relative; the card must ask for the project it is drawn in.

Same screenshot: "I had no idea that the Sharran card was folded... I was honestly perplexed." A folded card no
longer shows list controls with no list; it says it is folded and offers one button that names what it will show."""
from __future__ import annotations

import pathlib

import pytest

from neurosearch import db
from neurosearch.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _link(pid: str, cid: str) -> None:
    db.connect().execute("INSERT OR IGNORE INTO project_collections (project_id, collection_id) VALUES (?,?)", (pid, cid))
    db.connect().commit()


def test_a_channel_used_in_an_earlier_project_shows_this_projects_scores():
    older = db.create_project("Business acquisition", "buy a business")
    wealth = db.create_project("Personal wealth", "build generational wealth")
    coll = db.upsert_collection("channel", "UCmyron0001", "https://www.youtube.com/@myron", "Myron Golden")
    _link(older["id"], coll["id"]); _link(wealth["id"], coll["id"])       # older project linked it FIRST
    for i in range(3):
        src = db.upsert_source(platform="youtube", external_id=f"mg{i:08d}", url=f"https://www.youtube.com/watch?v=mg{i:08d}",
                               status="proposed", title=f"Video {i}", duration=600)
        db.link_source_collection(src["id"], coll["id"])
        db.set_relevance(src["id"], 90 - i, "teaches pricing", project_id=wealth["id"])   # what rank_proposed wrote for THIS project
    assert db.collection_project(coll["id"]) == older["id"], "the fallback really does point at the other project"
    cards = {c["id"]: c for c in db.pending_reviews(wealth["id"])}
    assert coll["id"] in cards
    scores = [s["relevance"] for s in cards[coll["id"]]["proposed"]]
    assert scores == [90, 89, 88], scores        # before: [None, None, None] — the card said "Newest first"
    # and the older project, which never ranked it, is not lent the newer project's opinion
    assert all(s["relevance"] is None for s in db.pending_reviews(older["id"])[0]["proposed"])


def test_a_folded_review_card_says_so_and_hides_its_list_controls():
    js = (ROOT / "neurosearch" / "web" / "js" / "sources.js").read_text()
    css = (ROOT / "neurosearch" / "web" / "styles.css").read_text()
    assert ">list folded</span>" in js
    assert "▾ Show the ${n} videos to review</button>" in js
    assert '<div class="row rvctl"' in js and ".rv.folded .rvctl{display:none}" in css, "no select-all/none/filter row on a card whose list is hidden"
