"""AD8 -- enumeration carries descriptions.

THE BUG THIS CLOSES. `media.enumerate_entries` lists with `extract_flat="in_playlist"` and then reads
`e.get("description")`, a field flat extraction never populates. Every candidate the app has ever created from a
channel or a search therefore arrived with a NULL description, and `relevance.rank_collection` scored it from a
title and a runtime. The AD4B blind review measured what that costs: 77% of auto-rejected candidates were ones
Kyle would have kept. Backfilling fixed the 9,286 already in the database; this fixes the intake, so the backlog
does not simply rebuild itself on the next channel scan.

WHY ENRICHMENT AND NOT AN API-FIRST LISTING. A channel's uploads playlist omits members-only videos and has no
equivalent of the Shorts tab, so listing through `playlistItems` would silently drop content the flat scan sees.
These tests pin that: the flat listing stays the source of truth for WHICH videos exist, and the API only ever
ADDS fields to it. The last two tests are the ones that matter for safety -- with no key, and with the API
throwing, enumeration must return exactly what it returns today.
"""
from __future__ import annotations

import pytest

from neurosearch import media, youtube_api


# ---------------------------------------------------------------- pure URL parsing (no key, no network)

@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv", ("id", "UCabcdefghijklmnopqrstuv")),
    ("https://www.youtube.com/@AcquiringMinds", ("forHandle", "@AcquiringMinds")),
    ("https://www.youtube.com/@AcquiringMinds/videos", ("forHandle", "@AcquiringMinds")),
    ("https://www.youtube.com/c/SomeVanityName", ("forUsername", "SomeVanityName")),
    ("https://www.youtube.com/user/oldstyle", ("forUsername", "oldstyle")),
    ("https://www.youtube.com/watch?v=abc", None),
])
def test_channel_ref_picks_the_right_selector(url, expected):
    assert youtube_api.channel_ref(url) == expected


def test_playlist_id_of():
    assert youtube_api.playlist_id_of("https://www.youtube.com/playlist?list=PLxyz") == "PLxyz"
    assert youtube_api.playlist_id_of("https://www.youtube.com/@someone") is None


# ---------------------------------------------------------------- enrichment behaviour

def _entries():
    return [
        {"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Buying a laundromat",
         "duration": None, "description": None, "view_count": None, "access_gate": None},
        {"id": "v2", "url": "https://www.youtube.com/watch?v=v2", "title": "Members only deep dive",
         "duration": 60.0, "description": None, "view_count": 10, "access_gate": "members_only"},
    ]


def test_enrichment_fills_descriptions_and_leaves_identity_alone(monkeypatch):
    monkeypatch.setattr(youtube_api, "available", lambda: {"ready": True, "why": "test"})
    monkeypatch.setattr(youtube_api, "videos", lambda ids, **kw: {
        "v1": {"external_id": "v1", "title": "Buying a laundromat", "description": "How to evaluate route density.",
               "duration": 1800.0, "view_count": 999, "published_at": "2026-01-02", "has_captions": True,
               "creator": "Acquiring Minds"},
        "v2": {"external_id": "v2", "title": "Members only deep dive", "description": "Paid subscriber walkthrough.",
               "duration": 120.0, "view_count": 11, "published_at": "2026-02-02", "has_captions": False,
               "creator": "Acquiring Minds"},
    })
    out = media._enrich_youtube(_entries())

    assert [e["id"] for e in out] == ["v1", "v2"], "enrichment must never add, drop or reorder entries"
    assert out[0]["description"] == "How to evaluate route density."
    assert out[0]["duration"] == 1800.0 and out[0]["published_at"] == "2026-01-02"
    # the listing already knew these -- the API must not overwrite what flat extraction got right
    assert out[1]["duration"] == 60.0 and out[1]["view_count"] == 10
    # and the gate the API cannot see survives
    assert out[1]["access_gate"] == "members_only"


def test_enrichment_never_overwrites_an_existing_description(monkeypatch):
    monkeypatch.setattr(youtube_api, "available", lambda: {"ready": True, "why": "test"})
    monkeypatch.setattr(youtube_api, "videos", lambda ids, **kw: {
        "v1": {"external_id": "v1", "description": "api text", "duration": None, "view_count": None,
               "published_at": None, "has_captions": None, "creator": None}})
    rows = [{"id": "v1", "description": "listing text"}]
    assert media._enrich_youtube(rows)[0]["description"] == "listing text"


def test_enrichment_is_capped(monkeypatch):
    """A 5,000-video channel must not quietly spend 200 quota units."""
    monkeypatch.setattr(youtube_api, "available", lambda: {"ready": True, "why": "test"})
    asked: list[int] = []

    def fake_videos(ids, **kw):
        asked.append(len(ids))
        return {}

    monkeypatch.setattr(youtube_api, "videos", fake_videos)
    media._enrich_youtube([{"id": f"v{i}"} for i in range(media.ENRICH_MAX + 250)])
    assert asked == [media.ENRICH_MAX]


# ---------------------------------------------------------------- the no-key / failure guarantees

def test_no_key_changes_nothing(monkeypatch):
    monkeypatch.setattr(youtube_api, "available", lambda: {"ready": False, "why": "no key"})
    monkeypatch.setattr(youtube_api, "videos", lambda *a, **k: pytest.fail("must not call the API without a key"))
    before = _entries()
    assert media._enrich_youtube([dict(e) for e in before]) == before


def test_api_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(youtube_api, "available", lambda: {"ready": True, "why": "test"})

    def boom(ids, **kw):
        raise youtube_api.YouTubeApiUnavailable("quota_exceeded", "gone until midnight Pacific")

    monkeypatch.setattr(youtube_api, "videos", boom)
    before = _entries()
    assert media._enrich_youtube([dict(e) for e in before]) == before, "enumeration must survive an API outage intact"


def test_empty_listing_short_circuits(monkeypatch):
    monkeypatch.setattr(youtube_api, "videos", lambda *a, **k: pytest.fail("no ids, no call"))
    assert media._enrich_youtube([]) == []


# ---------------------------------------------------------------- enumerate_url (the API-first path, unused by ingest)

def test_enumerate_url_returns_empty_for_an_unaddressable_url(monkeypatch):
    """A `/c/` vanity name the API will not resolve must read as 'cannot address', not 'empty channel'."""
    monkeypatch.setattr(youtube_api, "_get", lambda ep, params: {"items": []})
    info, entries = youtube_api.enumerate_url("https://www.youtube.com/c/Unresolvable")
    assert entries == [] and info == {}


def test_enumerate_url_walks_a_channel_through_its_uploads_playlist(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_get(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "channels":
            return {"items": [{"id": "UC1", "snippet": {"title": "Acquiring Minds"},
                               "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]}
        return {"items": [{"snippet": {"resourceId": {"videoId": "v1"}, "title": "T", "description": "D",
                                       "publishedAt": "2026-03-04T00:00:00Z", "videoOwnerChannelTitle": "Acquiring Minds"}}]}

    monkeypatch.setattr(youtube_api, "_get", fake_get)
    info, entries = youtube_api.enumerate_url("https://www.youtube.com/@AcquiringMinds", with_details=False)
    assert info["channel_id" if "channel_id" in info else "id"] == "UC1"
    assert [e["external_id"] for e in entries] == ["v1"]
    assert entries[0]["description"] == "D" and entries[0]["published_at"] == "2026-03-04"
    assert [c[0] for c in calls] == ["channels", "playlistItems"]


def test_playlist_item_fields_drops_private_and_deleted():
    assert youtube_api.playlist_item_fields({"snippet": {"resourceId": {"videoId": "v"}, "title": "Private video"}}) is None
    assert youtube_api.playlist_item_fields({"snippet": {"title": "No id at all"}}) is None
