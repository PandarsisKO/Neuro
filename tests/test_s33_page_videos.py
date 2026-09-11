"""S33 — a page's video is not in its text (0.63.16). (Sorts after test_s32.)

Kyle: *"I did send page, which worked for capturing the notes on the page, but I think its failing to grab the
content of the video, which is a video hosted on Loom."*

Measured on his database: the capture produced a `web` source with **4,926 characters over 4 chunks** — all of
Lesson 7's notes, correctly — and **not one URL of any kind**, no mention of Loom. The cause is structural rather
than a bug in the reader: `webpage.read_page` returns TEXT, an `<iframe src="…loom.com/embed/…">` contributes no
text, and the HTML is not kept anywhere afterwards. So the video was dropped *and the drop left no trace* — a page
whose video was discarded looked identical to a page that never had one.

Two halves, deliberately separate:

* **Free and automatic:** `webpage.video_embeds` runs at capture time, the list is stored on the source
  (`sources.video_embeds`) and the description says "1 video embedded (not added yet)".
* **Priced and explicit:** `courses.add_page_videos` queues them through the course importer's own machinery — the
  same cookie file (a private Loom needs the session), the same `normalise_embed`, the same `ingest_url` job, and
  the page URL as referer, which Loom checks. A video is a download plus a transcription, so it is offered, never
  taken.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pv_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, courses, db, ingest, webpage  # noqa: E402
from neurosearch.config import settings  # noqa: E402

NOTES = "<h1>Lesson 7 · Buying a Franchise</h1><p>" + ("A franchise is a licensing agreement. " * 30) + "</p>"
LOOM = '<iframe src="https://www.loom.com/embed/9f8a7b6c5d4e" allowfullscreen></iframe>'


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


# ------------------------------------------------------------------ detection

def test_a_loom_iframe_is_found():
    assert webpage.video_embeds(NOTES + LOOM) == ["https://loom.com/embed/9f8a7b6c5d4e"]


def test_a_player_hidden_in_escaped_json_is_found():
    """How a React course page carries its video: inside a script, with the slashes escaped."""
    h = '<script>window.d={"lesson":{"video":"https:\\/\\/www.loom.com\\/share\\/deadbeefcafe"}}</script>'
    assert webpage.video_embeds(h) == ["https://loom.com/share/deadbeefcafe"]


def test_the_other_hosts_a_course_uses():
    h = ('<iframe src="https://player.vimeo.com/video/123456"></iframe>'
         '<iframe src="https://fast.wistia.net/embed/iframe/abc123"></iframe>'
         '<video src="https://stream.mux.com/xyz.m3u8"></video>'
         '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>')
    got = webpage.video_embeds(h)
    assert len(got) == 4 and any("vimeo" in u for u in got) and any("wistia" in u for u in got)


def test_page_furniture_is_not_a_video():
    """Scripts, fonts and thumbnails share the URL shape and are not players."""
    h = ('<script src="https://cdn.x.com/player.js"></script><img src="https://cdn.x.com/thumb.png">'
         '<link href="https://fonts.x.com/inter.woff2">')
    assert webpage.video_embeds(h) == []


def test_a_page_with_no_video_reports_none():
    assert webpage.video_embeds(NOTES) == [] and webpage.video_embeds("") == []


def test_the_list_is_bounded():
    h = "".join(f'<iframe src="https://www.loom.com/embed/id{i:04d}"></iframe>' for i in range(40))
    assert len(webpage.video_embeds(h)) == webpage.EMBED_MAX


# ------------------------------------------------------------------ the capture records it, and says so

def test_capturing_a_lesson_keeps_the_notes_and_records_the_video(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/dashboard/educational-hub/classroom",
                              project_id=p["id"], title="Lesson 7", html=NOTES + LOOM)
    assert r["chunks"] >= 1                                            # the notes still arrive, as they did
    assert r["video_embeds"] == ["https://loom.com/embed/9f8a7b6c5d4e"]
    assert db.video_embeds_of(r["source_id"]) == r["video_embeds"]      # durable, so it can be offered later
    assert "1 video embedded (not added yet)" in db.get_source(r["source_id"])["description"]


def test_nothing_is_downloaded_by_the_capture(fresh):
    """The whole point of the split: capturing a page must never start a DOWNLOAD.

    It does queue the ordinary free `suggest_findings` pass over the notes, as every ingest does — the assertion is
    about `ingest_url`, which is the job that fetches and transcribes, and therefore the one that spends."""
    p = db.create_project("c", brief="b")
    ingest.ingest_webpage("https://x.test/lesson", project_id=p["id"], title="L", html=NOTES + LOOM)
    kinds = [j["kind"] for j in db.list_jobs(limit=100)]
    assert "ingest_url" not in kinds, kinds


def test_a_page_without_a_video_says_nothing_about_videos(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://x.test/plain", project_id=p["id"], title="L", html=NOTES)
    assert r["video_embeds"] == [] and "video" not in db.get_source(r["source_id"])["description"]


# ------------------------------------------------------------------ adding them is the explicit, priced half

def test_adding_the_video_queues_it_through_the_ordinary_path(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="Lesson 7",
                              html=NOTES + LOOM)
    out = courses.add_page_videos(p["id"], r["source_id"])
    assert out["queued"] == 1
    j = [x for x in db.list_jobs(limit=50) if x["kind"] == "ingest_url"][0]
    assert "loom.com" in j["payload"]["url"]
    assert j["payload"]["referer"] == "https://smbmarket.com/lesson-7"   # Loom checks the referer on an embed
    assert j["payload"]["project_id"] == p["id"]


def test_the_session_can_be_sent_for_a_private_video(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="L", html=NOTES + LOOM)
    out = courses.add_page_videos(p["id"], r["source_id"],
                                  cookies=[{"domain": ".loom.com", "name": "sid", "value": "x", "path": "/"}])
    assert out["cookies"] is True
    j = [x for x in db.list_jobs(limit=50) if x["kind"] == "ingest_url"][0]
    assert j["payload"]["cookies_file"]


def test_a_page_with_nothing_recorded_says_so_rather_than_failing(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://x.test/plain", project_id=p["id"], title="L", html=NOTES)
    out = courses.add_page_videos(p["id"], r["source_id"])
    assert out["queued"] == 0 and "no video embed" in out["why"]


def test_the_endpoint_is_reachable_and_project_scoped(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="L", html=NOTES + LOOM)
    out = api.api_page_videos(p["id"], api.PageVideosIn(source_id=r["source_id"]))
    assert out["queued"] == 1
    with pytest.raises(Exception):
        api.api_page_videos("no-such-project", api.PageVideosIn(source_id=r["source_id"]))


def test_the_row_carries_the_embeds_so_the_ui_can_offer_them(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="L", html=NOTES + LOOM)
    row = next(x for x in api.api_sources(project_id=p["id"]) if x["id"] == r["source_id"])
    assert row["video_embeds"] == ["https://loom.com/embed/9f8a7b6c5d4e"]


# ------------------------------------------------------------------ the extension has to carry the session

def test_the_page_capture_endpoint_returns_the_embeds_so_the_extension_can_offer_them(fresh):
    """`/ingest/html` is what "Send this page" calls, so the embeds have to come back through it."""
    p = db.create_project("c", brief="b")
    out = api.api_ingest_html(p["id"], api.HtmlIn(url="https://smbmarket.com/lesson-7", title="L",
                                                  html=NOTES + LOOM))
    assert out["video_embeds"] == ["https://loom.com/embed/9f8a7b6c5d4e"] and out["source_id"]


def test_the_extension_asks_before_adding_and_sends_every_embed_hosts_cookies():
    """A private Loom refuses an anonymous download, so the session must travel with the request — and the press
    has to be separate from the capture, because this half spends."""
    js = (EXT_POPUP := __import__("pathlib").Path(__file__).resolve().parent.parent / "extension" / "popup.js").read_text()
    assert "page-videos" in js                      # it calls the priced verb
    assert "addVid" in js                           # behind its own button, not automatic
    assert "vids.forEach(v => { try { hosts.add(new URL(v).hostname); } catch (e) {} });" in js
    assert "a video is downloaded and transcribed" in js.replace("\n", " ") or "downloaded and transcribed" in js


def test_the_extension_version_moved_again():
    import json as _json
    mf = _json.loads((__import__("pathlib").Path(__file__).resolve().parent.parent / "extension" / "manifest.json").read_text())
    assert mf["version"] == "1.6.1"


# ── 0.63.17 — and then it said "not added yet" about a video that was already transcribed ───────────────────────
# Kyle: *"it worked! I sent the video and its putting it through transcription now"* — and it had in fact already
# finished: a `media` source, 306 s, **69 segments, 7 chunks, 8 findings**, attached to the big project. But the
# page row still read *"1 video embedded (not added yet)"* and still offered the button. Queueing again would not
# double-spend (identity resolves to the ready source) — it would just be the screen saying something false.
#
# The state is DERIVED from `sources` rather than stored as a flag, because a stored "added" marker is a second
# copy of a truth the library already holds, and second copies drift.

def test_a_video_already_in_the_library_is_not_offered_again(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="L", html=NOTES + LOOM)
    row = next(x for x in api.api_sources(project_id=p["id"]) if x["id"] == r["source_id"])
    assert row["video_embeds_added"] == []                       # nothing added yet, so the offer stands

    # the video arrives, exactly as the ingest job would leave it
    db.upsert_source(platform="media", external_id="loom:9f8a7b6c5d4e",
                     url="https://www.loom.com/share/9f8a7b6c5d4e", title="the lesson video", status="ready")
    row = next(x for x in api.api_sources(project_id=p["id"]) if x["id"] == r["source_id"])
    assert row["video_embeds_added"] == ["https://loom.com/embed/9f8a7b6c5d4e"]


def test_adding_twice_says_so_instead_of_queueing_again(fresh):
    p = db.create_project("c", brief="b")
    r = ingest.ingest_webpage("https://smbmarket.com/lesson-7", project_id=p["id"], title="L", html=NOTES + LOOM)
    assert courses.add_page_videos(p["id"], r["source_id"])["queued"] == 1
    db.upsert_source(platform="media", external_id="loom:9f8a7b6c5d4e",
                     url="https://www.loom.com/share/9f8a7b6c5d4e", title="v", status="ready")
    again = courses.add_page_videos(p["id"], r["source_id"])
    assert again["queued"] == 0 and "already added" in again["why"]


def test_the_match_survives_the_embed_to_share_rewrite(fresh):
    """The page records `loom.com/embed/<id>` and the library holds `loom.com/share/<id>`: the same video under two
    addresses, which is exactly what `normalise_embed` exists to reconcile."""
    db.upsert_source(platform="media", external_id="loom:abc123", url="https://www.loom.com/share/abc123",
                     title="v", status="ready")
    from neurosearch.courses import normalise_embed
    assert db.sources_for_urls([normalise_embed("https://www.loom.com/embed/abc123")])


def test_a_video_that_is_not_in_the_library_is_not_claimed_as_added(fresh):
    assert db.sources_for_urls(["https://www.loom.com/share/nothinghere"]) == {}
    assert db.sources_for_urls([]) == {}
