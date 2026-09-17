"""S67 — caption recovery is derived state, never a transcript walk on the poll path (P0.3,
docs/SPEED-AUDIT-2026-09-17.md).

`ingest.caption_recovery_candidates` used to load every segment of every ready project source that had a caption
to sum their lengths — 601,423 rows / 21.7 MB on Kyle's project — on every Sources poll, from every open tab;
the endpoint measured p50 186 s under background load. The sum is now `sources.spoken_chars`, written by the one
place segments are written (`db.replace_transcript`) and backfilled once at startup. Proven here: the column is
maintained and backfilled; the poll-path query reads NO segments; eligibility is identical to the old
definition on every branch; a NULL count is computed on the spot and stored rather than skipped.
"""
from __future__ import annotations

import pytest

from neurosearch import db, ingest
from neurosearch.config import settings

CAPTION = ("1) Go to smbmarket.com & find businesses that cash flow $100k/year. 2) Make a list of 10-20 businesses "
           "and call every owner. 3) Ask for seller financing on 80% of the purchase price before you approach any bank. "
           "4) Close within 90 days and keep the staff.")


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _src(ext: str, spoken: str | None, desc: str, kind: str = "transcribed", project_id: str | None = None, status: str = "ready") -> dict:
    s = db.upsert_source(platform="youtube", external_id=ext, url=f"https://www.youtube.com/shorts/{ext}", title=ext,
                         description=desc, duration=30, transcript_kind=kind, status=status)
    if spoken is not None:
        db.replace_transcript(s["id"], [{"start": 0.0, "end": 5.0, "text": spoken}], [])
    if project_id:
        db.add_project_sources(project_id, [s["id"]])
    return db.get_source(s["id"])


def _old_definition(project_id: str | None) -> list[dict]:
    """The pre-P0.3 semantics, verbatim, as the reference oracle."""
    ids = set(db.project_source_ids(project_id, ready_only=False)) if project_id else None
    out = []
    for s in db.list_sources(status="ready", limit=100000):
        if ids is not None and s["id"] not in ids:
            continue
        if (s.get("transcript_kind") or "").endswith("+caption"):
            continue
        if len(s.get("description") or "") < ingest.CAPTION_MIN_CHARS:
            continue
        spoken = sum(len(x["text"]) for x in db.get_segments(s["id"]))
        if spoken >= ingest.SILENT_TRANSCRIPT_CHARS:
            continue
        out.append({"id": s["id"], "title": s.get("title"), "spoken_chars": spoken, "caption_chars": len(s.get("description") or "")})
    return out


def test_replace_transcript_maintains_spoken_chars():
    s = _src("a", "hello world", CAPTION)
    assert db.get_source(s["id"])["spoken_chars"] == len("hello world")
    db.replace_transcript(s["id"], [{"start": 0, "end": 1, "text": "héllo"}, {"start": 1, "end": 2, "text": "wörld!"}], [])
    assert db.get_source(s["id"])["spoken_chars"] == len("héllo") + len("wörld!")    # characters, like len()


def test_startup_backfills_rows_written_before_the_column_existed():
    s = _src("b", "x" * 50, CAPTION)
    db.connect().execute("UPDATE sources SET spoken_chars=NULL WHERE id=?", (s["id"],)); db.connect().commit()
    db.init_db()
    assert db.get_source(s["id"])["spoken_chars"] == 50


def test_poll_path_reads_no_segments(monkeypatch):
    pid = db.create_project("p", brief="b")["id"]
    for i in range(6):
        _src(f"c{i}", "🔥" * (i * 100), CAPTION, project_id=pid)          # 0..500 spoken chars: 4 eligible, 2 not
    def boom(_sid):
        raise AssertionError("caption_recovery_candidates must not read segments on the poll path")
    monkeypatch.setattr(db, "get_segments", boom)
    out = ingest.caption_recovery_candidates(pid)
    assert sorted(o["spoken_chars"] for o in out) == [0, 100, 200, 300]


def test_eligibility_is_identical_to_the_old_definition_on_every_branch():
    pid = db.create_project("p", brief="b")["id"]
    other = db.create_project("q", brief="b")["id"]
    _src("eligible", "🔥🔥", CAPTION, project_id=pid)
    _src("no-transcript", None, CAPTION, project_id=pid)                              # zero spoken: eligible
    _src("boundary-399", "x" * 399, CAPTION, project_id=pid)                          # just under: eligible
    _src("boundary-400", "x" * 400, CAPTION, project_id=pid)                          # at the floor: it spoke
    _src("spoke", "x" * 2000, CAPTION, project_id=pid)
    _src("short-caption", "🔥", "just a title", project_id=pid)
    _src("caption-199", "🔥", "y" * 199, project_id=pid)                              # just under the caption floor
    _src("caption-200", "🔥", "y" * 200, project_id=pid)                              # at the floor: eligible
    _src("already", "🔥", CAPTION, kind="transcribed+caption", project_id=pid)
    _src("not-ready", "🔥", CAPTION, project_id=pid, status="pending")
    _src("elsewhere", "🔥", CAPTION, project_id=other)
    _src("nowhere", "🔥", CAPTION)
    new = sorted(ingest.caption_recovery_candidates(pid), key=lambda r: r["id"])
    old = sorted(_old_definition(pid), key=lambda r: r["id"])
    assert new == old
    assert {r["title"] for r in new} == {"eligible", "no-transcript", "boundary-399", "caption-200"}
    # and the global (no project) form agrees too
    assert sorted(ingest.caption_recovery_candidates(None), key=lambda r: r["id"]) == sorted(_old_definition(None), key=lambda r: r["id"])


def test_a_null_count_is_computed_and_stored_not_skipped():
    pid = db.create_project("p", brief="b")["id"]
    s = _src("late", "🔥🔥", CAPTION, project_id=pid)
    db.connect().execute("UPDATE sources SET spoken_chars=NULL WHERE id=?", (s["id"],)); db.connect().commit()
    out = ingest.caption_recovery_candidates(pid)
    assert [o["id"] for o in out] == [s["id"]] and out[0]["spoken_chars"] == 2
    assert db.get_source(s["id"])["spoken_chars"] == 2
