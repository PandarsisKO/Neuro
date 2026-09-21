"""The YouTube Data API client (2026-09-20) — parsing and batching, verified without a key.

Why the client exists: `media.enumerate_entries` lists with `extract_flat="in_playlist"` and then reads
`e.get("description")`, which flat extraction never fills. Measured on Kyle's project, ~48 of 11,774 candidates
had a description and none had a publish date, so every relevance score was computed from a title and a runtime.
`videos.list` answers 50 ids per quota unit against 10,000/day; yt-dlp answers one per ~4.4 s.

Everything here is the pure half — duration parsing, field mapping, batch chunking, the no-key gate. The live
half needs a real key and is Kyle's to run.
"""
from __future__ import annotations

import pytest

from neurosearch import youtube_api as yt
from neurosearch.config import settings


@pytest.mark.parametrize("iso, secs", [
    ("PT1H2M3S", 3723), ("PT45S", 45), ("PT12M", 720), ("P1DT2H", 93600),
    ("PT1H", 3600), ("P2DT3H4M5S", 183845),
])
def test_iso_durations_parse(iso, secs):
    assert yt.parse_duration(iso) == secs


@pytest.mark.parametrize("bad", [None, "", "garbage", "1H2M"])
def test_unparseable_durations_are_none_not_zero(bad):
    """None means unknown. Zero would read as a real zero-length video and poison a cost estimate."""
    assert yt.parse_duration(bad) is None


def test_video_fields_maps_onto_the_names_the_index_already_uses():
    item = {
        "id": "abc123",
        "snippet": {"title": "Buying a $4m Manufacturer", "description": "Full teardown of the deal.\nNumbers inside.",
                    "channelTitle": "Acquiring Minds", "channelId": "UC123", "publishedAt": "2026-03-04T17:02:11Z",
                    "tags": ["acquisition", "sba"], "categoryId": "22", "liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT57M3S", "caption": "true"},
        "statistics": {"viewCount": "41233"},
    }
    f = yt.video_fields(item)
    assert f["external_id"] == "abc123"
    assert f["title"] == "Buying a $4m Manufacturer"
    assert f["description"].startswith("Full teardown")
    assert f["creator"] == "Acquiring Minds"
    assert f["published_at"] == "2026-03-04"          # the schema stores a date, not a timestamp
    assert f["duration"] == 3423.0
    assert f["view_count"] == 41233
    assert f["has_captions"] is True                  # what usage.estimate_video could never determine
    assert f["live"] is False


def test_caption_availability_is_tri_state():
    """True/False are answers; None means the API did not say — and a missing answer must not read as 'no
    captions', which would inflate every Whisper estimate."""
    assert yt.video_fields({"contentDetails": {"caption": "true"}})["has_captions"] is True
    assert yt.video_fields({"contentDetails": {"caption": "false"}})["has_captions"] is False
    assert yt.video_fields({"contentDetails": {}})["has_captions"] is None


def test_missing_statistics_do_not_crash_or_invent():
    f = yt.video_fields({"id": "x", "snippet": {"title": "t"}, "statistics": {}})
    assert f["view_count"] is None and f["duration"] is None and f["published_at"] is None


def test_playlist_items_drop_what_cannot_be_fetched():
    """A private or deleted entry has no usable video, and storing it would create a candidate that can never
    be acquired."""
    def it(vid, title):
        return {"snippet": {"resourceId": {"videoId": vid} if vid else {}, "title": title,
                            "description": "d", "videoOwnerChannelTitle": "C", "publishedAt": "2026-01-02T00:00:00Z"}}
    assert yt.playlist_item_fields(it("v1", "Real one"))["external_id"] == "v1"
    assert yt.playlist_item_fields(it("v2", "Private video")) is None
    assert yt.playlist_item_fields(it("v3", "Deleted video")) is None
    assert yt.playlist_item_fields(it(None, "No id")) is None


def test_playlist_item_builds_a_usable_url():
    f = yt.playlist_item_fields({"snippet": {"resourceId": {"videoId": "zz"}, "title": "t", "description": "",
                                             "publishedAt": "2026-02-03T00:00:00Z"}})
    assert f["url"] == "https://www.youtube.com/watch?v=zz"
    assert f["published_at"] == "2026-02-03"
    assert f["description"] is None            # empty string becomes None, not ""


def test_videos_batches_by_fifty_and_merges(monkeypatch):
    """The whole economic argument: 50 ids per quota unit. One call per video would cost 50x."""
    calls = []

    def fake_get(endpoint, params):
        ids = params["id"].split(",")
        calls.append(ids)
        return {"items": [{"id": i, "snippet": {"title": i}} for i in ids]}

    monkeypatch.setattr(yt, "_get", fake_get)
    got = yt.videos([f"v{i}" for i in range(120)])
    assert [len(c) for c in calls] == [50, 50, 20]      # three calls, three quota units, not 120
    assert len(got) == 120 and got["v119"]["title"] == "v119"


def test_videos_deduplicates_and_ignores_blanks(monkeypatch):
    seen = []
    monkeypatch.setattr(yt, "_get", lambda e, p: seen.append(p["id"].split(",")) or {"items": []})
    yt.videos(["a", "a", "b", "", None, "b"])
    assert seen == [["a", "b"]]


def test_ids_the_api_omits_are_absent_not_errors(monkeypatch):
    """Deleted, private and region-blocked videos just do not come back. The caller needs to see which."""
    monkeypatch.setattr(yt, "_get", lambda e, p: {"items": [{"id": "a", "snippet": {"title": "A"}}]})
    got = yt.videos(["a", "gone"])
    assert set(got) == {"a"}


def test_without_a_key_it_reports_off_and_refuses_rather_than_failing_oddly(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", None)
    assert yt.available()["ready"] is False
    assert "yt-dlp" in yt.available()["why"]            # the message names the fallback, not just the lack
    with pytest.raises(yt.YouTubeApiUnavailable) as e:
        yt._get("videos", {"id": "x"})
    assert e.value.reason == "no_key"


def test_with_a_key_it_reports_ready(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "AIza-test")
    assert yt.available()["ready"] is True


def test_quota_is_tallied_per_endpoint_cost():
    assert yt.COST["videos"] == 1 and yt.COST["playlistItems"] == 1
    assert yt.COST["search"] == 100        # why search.list is deliberately not implemented here
