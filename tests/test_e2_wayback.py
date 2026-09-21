"""E2 -- the Wayback Machine, for the two questions works.py asks and then gives up on.

FIRST: `version_freshness` can already tell you a source's evidence is out of date -- the SOP 50 10 7 page it
cites now serves 50 10 8. What it cannot tell you is what the page SAID. The finding quoting it is not wrong,
it is dated, and until now there was no way to see the text it was true of.

SECOND, duller and far more common: a citation 404s. The claim may be perfectly sound and the evidence simply
moved, and the choice has been between deleting a good finding and keeping an unverifiable one.

The design point these tests pin is `before()` rather than `nearest()`. The archive's "closest" capture to a
version's effective date is very often the capture just AFTER it -- which is the NEW text, confidently returned
as if it were the old. That would be worse than returning nothing, because it reads like an answer. Every
lookup here is therefore strictly-before, and every failure mode returns None rather than raising, because an
archive outage is not a reason to call a finding unsupported.
"""
from __future__ import annotations

import json

import pytest

from neurosearch import wayback


class _Res:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body, self.status, self.content_type, self.headers = body, status, "application/json", {}


def _cdx(rows: list[tuple[str, str]]) -> bytes:
    """The CDX endpoint's own shape: a header row, then one row per capture."""
    return json.dumps([["timestamp", "statuscode", "digest"]] + [[t, s, f"D{t}"] for t, s in rows]).encode()


@pytest.fixture()
def fetched(monkeypatch):
    """Capture the URLs the module builds, and answer them."""
    seen: list[str] = []
    answers: dict = {"body": b"", "status": 200}

    def fake(url, **kw):
        seen.append(url)
        b = answers["body"]
        return _Res(b(url) if callable(b) else b, answers["status"])

    from neurosearch import safe_fetch as SF
    monkeypatch.setattr(SF, "safe_fetch", fake)
    return seen, answers


# ---------------------------------------------------------------- pure (no network at all)

@pytest.mark.parametrize("given,expected", [
    ("2026-09-21", "20260921"),
    ("2026-09-21T14:03:00Z", "20260921"),
    ("2026-09", "202609"),
    ("20260921140300", "20260921140300"),
    ("", None),
    (None, None),
    ("not a date", None),
])
def test_to_timestamp(given, expected):
    assert wayback.to_timestamp(given) == expected


def test_from_timestamp_round_trips_the_date_the_schema_stores():
    assert wayback.from_timestamp("20260921140300") == "2026-09-21"
    assert wayback.from_timestamp("2026") is None


def test_archived_url_asks_for_the_page_as_captured():
    u = wayback.archived_url("https://www.sba.gov/x", "20240101000000")
    assert u.endswith("id_/https://www.sba.gov/x"), "id_ returns the capture, not the archive's rewritten copy"
    assert "id_" not in wayback.viewer_url("https://www.sba.gov/x", "20240101000000")


def test_available_is_shape_compatible_with_the_youtube_client():
    a = wayback.available()
    assert a["ready"] is True and "why" in a, "callers treat the two clients the same way"


# ---------------------------------------------------------------- before(): the whole point of the module

def test_before_returns_the_last_capture_strictly_before_the_cut(fetched):
    seen, answers = fetched
    answers["body"] = _cdx([("20230301000000", "200"), ("20240115000000", "200"), ("20240501000000", "200")])
    cap = wayback.before("https://www.sba.gov/sop", "2024-02-01")
    assert cap["timestamp"] == "20240115000000"
    assert cap["date"] == "2024-01-15"
    assert "to=20240201" in seen[0].replace("%", "") or "to=20240201" in seen[0]


def test_before_never_returns_the_successors_text(fetched):
    """The capture nearest an effective date is frequently the one just AFTER it. Returning that would be
    worse than returning nothing: it reads like the old text and is the new text."""
    seen, answers = fetched
    answers["body"] = _cdx([("20240202000000", "200"), ("20240210000000", "200")])
    assert wayback.before("https://www.sba.gov/sop", "2024-02-01") is None


def test_before_without_a_usable_date_makes_no_request(fetched):
    seen, _ = fetched
    assert wayback.before("https://www.sba.gov/sop", "sometime in 2024") is None
    assert seen == []


def test_captures_drops_error_pages_by_default(fetched):
    seen, answers = fetched
    answers["body"] = _cdx([("20240101000000", "200")])
    wayback.captures("https://x.test/a")
    assert "statuscode:200" in seen[0].replace("%3A", ":")


def test_captures_handles_the_empty_body_the_cdx_api_uses_for_nothing_archived(fetched):
    _, answers = fetched
    answers["body"] = b"   "
    assert wayback.captures("https://x.test/never") == []


def test_captures_is_bounded(fetched):
    seen, answers = fetched
    answers["body"] = _cdx([])
    wayback.captures("https://x.test/a", limit=99999)
    assert f"limit={wayback.MAX_ROWS}" in seen[0]


# ---------------------------------------------------------------- nearest / rescue

def test_nearest_returns_none_when_never_archived(fetched):
    _, answers = fetched
    answers["body"] = json.dumps({"archived_snapshots": {}}).encode()
    assert wayback.nearest("https://x.test/never") is None


def test_nearest_builds_a_citable_capture(fetched):
    _, answers = fetched
    answers["body"] = json.dumps({"archived_snapshots": {"closest": {
        "timestamp": "20240115000000", "status": "200", "available": True}}}).encode()
    cap = wayback.nearest("https://www.sba.gov/sop", at="2024-02-01")
    assert cap["date"] == "2024-01-15" and cap["archived_url"].startswith("https://web.archive.org/web/")


def test_rate_limiting_is_named_rather_than_reported_as_missing(fetched):
    _, answers = fetched
    answers["status"] = 429
    with pytest.raises(wayback.WaybackUnavailable) as ei:
        wayback.nearest("https://x.test/a")
    assert ei.value.reason == "rate_limited", "'slow down' must never be mistaken for 'never archived'"


def test_a_blocked_fetch_is_typed(monkeypatch):
    from neurosearch import safe_fetch as SF

    def blocked(url, **kw):
        raise SF.FetchBlocked("private_address", "nope")

    monkeypatch.setattr(SF, "safe_fetch", blocked)
    with pytest.raises(wayback.WaybackUnavailable) as ei:
        wayback.nearest("https://x.test/a")
    assert ei.value.reason == "fetch_blocked"


# ---------------------------------------------------------------- works.py wiring

def test_superseded_text_is_none_for_fresh_lineage(monkeypatch):
    from neurosearch import works
    monkeypatch.setattr(works, "version_freshness", lambda sid: {"relation": "none", "work_id": "w", "version_id": "v"})
    assert works.superseded_text("s1") is None


def test_superseded_text_cuts_on_the_first_successors_date(monkeypatch):
    from neurosearch import works
    monkeypatch.setattr(works, "version_freshness",
                        lambda sid: {"relation": "material", "work_id": "w", "version_id": "v7"})
    monkeypatch.setattr(works, "newer_versions", lambda vid: [
        {"id": "v8", "label": "SOP 50 10 8", "effective_date": "2023-08-01"},
        {"id": "v9", "label": "SOP 50 10 9", "effective_date": "2025-06-01"}])
    monkeypatch.setattr(works, "manifestations_of", lambda wid: [
        {"url": "https://www.sba.gov/sop", "form": "official", "version_id": "v7", "source_id": "s1"}])
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(wayback, "before", lambda url, date: asked.append((url, date)) or
                        {"timestamp": "20230715000000", "date": "2023-07-15"})
    out = works.superseded_text("s1")
    assert asked == [("https://www.sba.gov/sop", "2023-08-01")], "cut on v8, not on the later v9"
    assert out["superseded_by"] == "SOP 50 10 8" and out["capture"]["date"] == "2023-07-15"


def test_superseded_text_skips_a_local_uploaded_copy(monkeypatch):
    """A `document` source's URL has never been on the public web; looking it up would always miss."""
    from neurosearch import works
    monkeypatch.setattr(works, "version_freshness",
                        lambda sid: {"relation": "material", "work_id": "w", "version_id": "v7"})
    monkeypatch.setattr(works, "newer_versions", lambda vid: [{"id": "v8", "label": "L", "effective_date": "2023-08-01"}])
    monkeypatch.setattr(works, "manifestations_of", lambda wid: [{"url": "file:///Users/k/sop.pdf", "form": "mirror"}])
    monkeypatch.setattr(wayback, "before", lambda *a, **k: pytest.fail("must not look up a local path"))
    assert works.superseded_text("s1") is None


def test_an_archive_outage_never_fails_the_caller(monkeypatch):
    from neurosearch import works
    monkeypatch.setattr(works, "version_freshness",
                        lambda sid: {"relation": "material", "work_id": "w", "version_id": "v7"})
    monkeypatch.setattr(works, "newer_versions", lambda vid: [{"id": "v8", "label": "L", "effective_date": "2023-08-01"}])
    monkeypatch.setattr(works, "manifestations_of", lambda wid: [{"url": "https://www.sba.gov/sop", "form": "official"}])

    def down(url, date):
        raise wayback.WaybackUnavailable("unreachable", "archive.org is down")

    monkeypatch.setattr(wayback, "before", down)
    assert works.superseded_text("s1") is None


def test_rescue_link_ignores_anything_that_is_not_a_web_url(monkeypatch):
    from neurosearch import works
    monkeypatch.setattr(wayback, "rescue", lambda *a, **k: pytest.fail("must not look this up"))
    assert works.rescue_link("file:///tmp/x.pdf") is None
    assert works.rescue_link("") is None
