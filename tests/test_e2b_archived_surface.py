"""E2b -- the surface for "what it said then".

`works.superseded_text` and `works.rescue_link` shipped with nothing calling them. This is the endpoint and the
drawer control that make them reachable, and the tests below pin the three things that would quietly make the
feature dishonest rather than merely broken:

1. **The two answers are not the same answer.** A capture from before the successor took effect IS the text a
   dated finding was drawn from. The newest capture of a URL is not evidence of what any version said -- it is
   just a copy of the page. The endpoint labels them `superseded` and `nearest`, and the drawer says different
   things about each. Collapsing them would silently upgrade the weaker one.
2. **An outage is not an absence.** "The archive is busy" must never render as "this source has no history".
3. **It costs a network call, so nothing fetches it on drawer load.** The button is the consent.
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, works  # noqa: E402
from neurosearch import db as _db  # noqa: E402

from tests.frontend_helpers import ui_source  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "neurosearch" / "web"
JS = (WEB / "js" / "research.js").read_text()


@pytest.fixture()
def a_source(monkeypatch):
    monkeypatch.setattr(_db, "get_source", lambda sid: {"id": sid, "url": "https://www.sba.gov/sop", "title": "SOP"})


# ---------------------------------------------------------------- the endpoint

def test_a_superseded_capture_is_labelled_as_such(monkeypatch, a_source):
    monkeypatch.setattr(works, "superseded_text", lambda sid: {
        "work_id": "w", "version_id": "v7", "relation": "material", "superseded_by": "SOP 50 10 8",
        "effective_date": "2023-08-01", "url": "https://www.sba.gov/sop",
        "capture": {"date": "2023-07-15", "viewer_url": "V", "archived_url": "A"}})
    monkeypatch.setattr(works, "rescue_link", lambda *a, **k: pytest.fail("must not fall back when there is a real answer"))
    r = api.api_source_archived("s1")
    assert r["available"] is True and r["kind"] == "superseded"
    assert r["superseded_by"] == "SOP 50 10 8" and r["capture"]["date"] == "2023-07-15"


def test_no_lineage_falls_back_to_the_nearest_capture_but_says_so(monkeypatch, a_source):
    monkeypatch.setattr(works, "superseded_text", lambda sid: None)
    monkeypatch.setattr(works, "rescue_link", lambda url, **k: {"date": "2026-01-02", "viewer_url": "V", "archived_url": "A"})
    r = api.api_source_archived("s1")
    assert r["kind"] == "nearest", "a plain copy of the page must never be returned as the superseded text"


def test_nothing_archived_is_a_plain_answer_not_an_error(monkeypatch, a_source):
    monkeypatch.setattr(works, "superseded_text", lambda sid: None)
    monkeypatch.setattr(works, "rescue_link", lambda url, **k: None)
    r = api.api_source_archived("s1")
    assert r["available"] is False and "no capture" in r["reason"]


def test_a_source_with_no_web_address_is_not_looked_up(monkeypatch):
    monkeypatch.setattr(_db, "get_source", lambda sid: {"id": sid, "url": "", "title": "an upload"})
    monkeypatch.setattr(works, "superseded_text", lambda sid: None)
    monkeypatch.setattr(works, "rescue_link", lambda *a, **k: pytest.fail("nothing to look up"))
    r = api.api_source_archived("s1")
    assert r["available"] is False and "no public web address" in r["reason"]


def test_an_unknown_source_is_404(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(_db, "get_source", lambda sid: None)
    with pytest.raises(HTTPException) as ei:
        api.api_source_archived("nope")
    assert ei.value.status_code == 404


def test_an_archive_outage_does_not_become_a_5xx(monkeypatch, a_source):
    """works.* swallow WaybackUnavailable and return None, so the endpoint answers 'nothing found' rather than
    failing the drawer. Pinned here because the swallowing lives in works.py and could be removed there."""
    monkeypatch.setattr(works, "superseded_text", lambda sid: None)
    monkeypatch.setattr(works, "rescue_link", lambda url, **k: None)
    assert api.api_source_archived("s1")["available"] is False


# ---------------------------------------------------------------- the drawer control

def test_the_drawer_does_not_fetch_the_archive_until_asked():
    """The only thing in the drawer that reaches the public internet. If sourceDrawer() called it directly,
    every source anyone opened would hit archive.org."""
    drawer = JS.split("globalThis.sourceDrawer")[1].split("globalThis.sourceArchived")[0]
    assert "/archived" not in drawer, "the archive lookup must hang off the button, not off opening the drawer"
    assert "sourceArchived(" in drawer, "…and the button must be there to press"


def test_the_two_answers_read_differently_in_the_ui():
    fn = JS.split("globalThis.sourceArchived")[1].split("globalThis.drawerNote")[0]
    assert "superseded" in fn and "nearest" not in fn.split("r.kind === 'superseded'")[0]
    assert "not evidence of what any particular version" in fn, \
        "the weaker answer must say what it is not, or it reads as the stronger one"


def test_a_failed_lookup_says_nothing_changed():
    fn = JS.split("globalThis.sourceArchived")[1].split("globalThis.drawerNote")[0]
    assert "Could not reach the archive" in fn and "nothing about this source has changed" in fn


def test_the_button_is_only_offered_for_a_web_url():
    assert "(s.url || '').startsWith('http') ?" in JS, \
        "an uploaded document has no public page to look up; offering the button would promise a lookup that cannot work"


def test_the_control_is_reachable_from_the_shipped_frontend():
    assert "sourceArchived" in ui_source(WEB)
