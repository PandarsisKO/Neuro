"""S19 — the rung Discover never had: seen, and never read (0.62.5). (Sorts after test_s18.)

Kyle, after four releases of me fixing the matcher: *"when we are searching library I suppose what I wanted was to
search for content we chose not to ingest but that the app has seen at some point, like videos that were ranked but
not chosen for transcription. if we do not find things there, then web, youtube, social media, academic papers
etc."*

That ladder already existed in `knowledge.pursue` (project → library → candidates → external, G5) and **Discover
did not climb it** — it went library → catalogues → web, skipping the candidates rung entirely. Measured on his
live database, 2026-09-10, the rung it skipped is an order of magnitude larger than the one it searched:

    seen and never ingested   10,319 candidates + 558 sources skipped at the cutoff
    library scope (searched)     387 sources outside the project

    query                  in the seen pool   what is actually in there
    quality of earnings     1                 an Acquisition Lab Quality-of-Earnings advisor
    due diligence          19                 business-acquisition interviews, all of them
    sba                    43                 Ben Kelly, Acquiring Minds
    cpa                    13 + 8 skipped     Hector Garcia CPA, LYFE Accounting, Matt Bontrager

Against which the library pass offered six short-term-rental tax videos. **The material he wanted was in the
database the whole time, one table away from the one being searched.**

Reuses two existing mechanisms and adds no data model (G3: extend, never duplicate) — `candidates.search` for the
metadata FTS, `_potential` for the $0 ranking against this project's open questions, vocabulary and creator yield.
Project grounding enters as RANKING, never as a filter, which is the distinction the failed 0.62.4 experiment
missed.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_seen_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import candidates, db  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


@pytest.fixture(autouse=True)
def _no_jobs_left_behind():
    yield
    try:
        with db.tx() as conn:
            conn.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('queued','running')")
    except Exception:  # noqa: BLE001
        pass


def _candidate(cid, title, desc="", creator="Some Channel", project_id=None):
    candidates.remember([{"external_id": cid, "url": f"https://y/{cid}", "title": title,
                          "description": desc, "creator": creator}], "youtube", project_id,
                        {"kind": "exploration"})


def _skipped(sid, title, desc=""):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, description, channel, status, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (sid, "youtube", sid, f"https://y/{sid}", title, desc, "Cutoff Channel", "skipped", 1.0, 1.0))


def test_it_finds_what_the_app_saw_and_never_read(fresh):
    p = db.create_project("acq", brief="buying businesses, SBA loans, quality of earnings")
    _candidate("c1", "An Acquisition Lab Quality of Earnings Advisor", "how a QoE is run", project_id=p["id"])
    _candidate("c2", "Laundromat loyalty programs", "nothing to do with it", project_id=p["id"])
    out = candidates.seen_for_query(p["id"], "quality of earnings")
    titles = [i["title"] for i in out["items"]]
    assert any("Quality of Earnings" in t for t in titles)
    assert not any("Laundromat" in t for t in titles)


def test_a_source_skipped_at_the_cutoff_is_the_same_thing_to_a_user(fresh):
    """13 candidates AND 8 skipped sources mentioned "cpa" on Kyle's machine. Both are things the app saw and did
    not read, so both belong in one answer."""
    p = db.create_project("acq", brief="b")
    _skipped("s1", "CPA EXPLAINS: Tax Loopholes for Entrepreneurs")
    _candidate("c1", "7 Money Moves Your CPA Never Mentioned", project_id=p["id"])
    out = candidates.seen_for_query(p["id"], "cpa")
    assert out["counts"] == {"candidates": 1, "skipped": 1}
    assert {i["why_known"] for i in out["items"]} == {"seen but never read", "skipped at the ingest cutoff"}


def test_the_subject_word_is_what_gets_searched(fresh):
    """A title is a few words long, so ANDing every query term finds nothing. The anchor from 0.62.0 — the word
    that names the subject — is what the metadata is searched for, and "modern" is not it."""
    p = db.create_project("acq", brief="b")
    _candidate("c1", "Hector Garcia CPA on bookkeeping", "a cpa explains", project_id=p["id"])
    _candidate("c2", "A modern kitchen remodel", "modern design ideas", project_id=p["id"])
    out = candidates.seen_for_query(p["id"], "modern CPA")
    assert out["searched"] == "cpa"
    assert [i["id"] for i in out["items"]] and all("kitchen" not in i["title"] for i in out["items"])


def test_something_already_read_is_never_offered_again(fresh):
    p = db.create_project("acq", brief="b")
    _candidate("c1", "A CPA interview", project_id=p["id"])
    rows = db.connect().execute("SELECT id FROM candidates").fetchall()
    with db.tx() as conn:                                    # a real source row: source_id is a foreign key
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) "
                     "VALUES ('already','youtube','already','https://y/already','A CPA interview','ready',1.0,1.0)")
        conn.execute("UPDATE candidates SET source_id='already' WHERE id=?", (rows[0]["id"],))
    out = candidates.seen_for_query(p["id"], "cpa")
    assert out["items"] == []
    assert "nothing the app has seen but not read" in out["note"]


def test_the_project_ranks_the_pool_it_does_not_filter_it(fresh):
    """0.62.4 tried to FILTER library hits by a project-vocabulary model and it separated nothing. Ranking is the
    honest use of the same signal: everything found stays findable, the project decides the order."""
    p = db.create_project("acq", brief="SBA loans for buying a business, seller financing")
    _candidate("c1", "SBA loan basics for buying a business", "seller financing and SBA", project_id=p["id"])
    _candidate("c2", "SBA disaster relief for hurricane damage", "unrelated", project_id=p["id"])
    out = candidates.seen_for_query(p["id"], "sba")
    assert len(out["items"]) == 2                            # nothing filtered out
    assert "buying a business" in out["items"][0]["title"]   # the project decided which came first


def test_discover_climbs_the_rung_before_the_web(fresh):
    from neurosearch import discover
    p = db.create_project("acq", brief="b")
    _candidate("c1", "A CPA explains addbacks", project_id=p["id"])
    out = discover.discover(p["id"], refine="cpa addbacks", count=1, verify=False, mode="library_only")
    assert out["seen"]["counts"]["candidates"] == 1
    assert "seen" in out and out["seen"]["items"][0]["actions"]["capture"]["label"] == "Read this"


def test_a_failure_in_the_rung_cannot_take_the_ladder_down(fresh, monkeypatch):
    from neurosearch import candidates as c, discover
    p = db.create_project("acq", brief="b")
    monkeypatch.setattr(c, "seen_for_query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = discover.discover(p["id"], refine="cpa", count=1, verify=False, mode="library_only")
    assert out["seen"]["items"] == []                        # empty, not an exception


def test_the_note_says_where_the_answer_came_from(fresh):
    p = db.create_project("acq", brief="b")
    _candidate("c1", "Due diligence on an ecommerce business", project_id=p["id"])
    _skipped("s1", "Due diligence mistakes to avoid")
    out = candidates.seen_for_query(p["id"], "diligence")
    assert "already seen and never read" in out["note"] and "skipped at the cutoff" in out["note"]
