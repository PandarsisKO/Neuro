"""S68 — `/api/sources` carries what the Sources list renders, and nothing it does not (P0.4,
docs/SPEED-AUDIT-2026-09-17.md).

Measured on Kyle's project: 1,515 rows, 2,539 KB, 47 keys per row — of which fifteen keys (~640 KB with their
repeated names) were never read by the list, `description` was sent for rows whose row template never shows it
(a duration wins), and the query listed the whole global library (`limit=10000`) to keep the project's rows in
Python. This gate is the inventory contract: every `s.<field>` the shipped row templates read is present on a
list row, every field in `LIST_OMIT_FIELDS` is absent from the list and present on `/api/sources/{id}`, and the
project-scoped query is the database's, not Python's.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from neurosearch import api, db
from neurosearch.config import settings

JS = pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web" / "js" / "sources.js"


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _rendered_fields() -> set[str]:
    """Every `s.<field>` the list's row templates and their helpers read, from the shipped JS."""
    js = JS.read_text()
    out: set[str] = set()
    for name in ("srcRowHtml", "sourceRowActions", "browserBlock", "completenessLine", "renderSourcesView", "renderSourceList"):
        m = re.search(rf"globalThis\.{name} = (?:async )?function {name}\(([^)]*)\) \{{(.*?)\n\}}", js, re.S)
        assert m, name
        first = (m.group(1).split(",")[0].strip() or "s")
        out |= set(re.findall(rf"\b{re.escape(first)}\.([a-zA-Z_]\w*)", m.group(2)))
        out |= set(re.findall(r"\bs\.([a-zA-Z_]\w*)", m.group(2)))        # arrow callbacks `s => s.<field>`
    return out


# fields that exist on a row only in a particular state; their presence is proven by their own feature gates
SITUATIONAL = {"job", "analysis_job", "acquisition", "pool_potential", "video_embeds", "video_embeds_added", "completeness", "error", "error_class"}


def _project_with_source(**src):
    p = db.create_project("diet", brief="b")["id"]
    s = db.upsert_source(platform="youtube", external_id="d1", url="https://youtu.be/d1", title="t", status="ready",
                         channel="c", channel_url="https://youtube.com/@c", description="d" * 900, **src)
    db.add_project_sources(p, [s["id"]])
    return p, s["id"]


def test_omitted_fields_are_never_ones_the_list_renders():
    clash = set(api.LIST_OMIT_FIELDS) & _rendered_fields()
    assert not clash, f"LIST_OMIT_FIELDS drops fields the row templates read: {sorted(clash)}"


def test_every_rendered_field_is_on_a_list_row(fresh):
    p, _ = _project_with_source(duration=120)
    row = api.api_sources(project_id=p)[0]
    missing = _rendered_fields() - set(row) - SITUATIONAL
    assert not missing, f"the row template reads fields the list no longer sends: {sorted(missing)}"


def test_omitted_fields_are_absent_from_the_list_and_present_on_the_source(fresh):
    p, sid = _project_with_source(duration=120)
    row = api.api_sources(project_id=p)[0]
    for k in api.LIST_OMIT_FIELDS:
        assert k not in row, k
    full = api.api_source(sid)
    for k in ("channel_url", "created_at", "updated_at", "external_id", "revision", "canonical_url", "spoken_chars"):
        assert k in full, k
    assert full["description"] == "d" * 900


def test_description_is_omitted_when_a_duration_is_shown_and_clipped_otherwise(fresh):
    p, sid = _project_with_source(duration=120)
    assert api.api_sources(project_id=p)[0]["description"] is None
    db.connect().execute("UPDATE sources SET duration=NULL WHERE id=?", (sid,)); db.connect().commit()
    d = api.api_sources(project_id=p)[0]["description"]
    assert len(d) == api.LIST_DESCRIPTION_CHARS + 1 and d.endswith("…")


def test_the_project_query_is_scoped_in_the_database_not_python(fresh, monkeypatch):
    p, sid = _project_with_source(duration=120)
    other = db.upsert_source(platform="youtube", external_id="d2", url="https://youtu.be/d2", title="elsewhere", status="ready")
    calls = []
    real = db.list_sources

    def spy(**kw):
        calls.append(kw)
        return real(**kw)
    monkeypatch.setattr(db, "list_sources", spy)
    rows = api.api_sources(project_id=p, limit=2000)
    assert [r["id"] for r in rows] == [sid]
    seen = calls[0]                                              # the list's own query; later helpers make their own
    assert seen.get("ids") is not None and seen.get("limit") == 2000, "the project's ids must be the query's predicate, not a 10000-row scan"
    assert other["id"] not in {r["id"] for r in rows}


def test_list_sources_ids_predicate(fresh):
    a = db.upsert_source(platform="youtube", external_id="a", url="https://youtu.be/a", title="alpha", status="ready")
    b = db.upsert_source(platform="youtube", external_id="b", url="https://youtu.be/b", title="beta", status="failed")
    db.upsert_source(platform="youtube", external_id="c", url="https://youtu.be/c", title="gamma", status="ready")
    assert {r["id"] for r in db.list_sources(ids=[a["id"], b["id"]])} == {a["id"], b["id"]}
    assert db.list_sources(ids=[]) == []
    assert [r["id"] for r in db.list_sources(ids=[a["id"], b["id"]], status="ready")] == [a["id"]]
    assert [r["id"] for r in db.list_sources(ids=[a["id"], b["id"]], query="bet")] == [b["id"]]
    assert {r["id"] for r in db.list_sources(ids=[a["id"], a["id"], "nope"])} == {a["id"]}


def test_review_cards_still_carry_relevance_from_their_own_endpoint(fresh):
    """`relevance`/`relevance_why` left the list; the review card is their reader and has its own source."""
    import inspect
    src = inspect.getsource(db.proposed_sources)
    assert "relevance" in src
