"""A finding you threw away must not count as what a creator gave you (2026-09-20).

Kyle asked whether Keep/Lose covers findings. It does not — and checking why found the same class of bug one
layer down. `creator_yield` shapes pool ranking from "what has this creator actually produced for this project",
but its findings count had NO status filter: a dismissed finding counted exactly as much as an approved one, so
a creator producing volumes of noise scored like one producing keepers. Measured on his project that day:
17,193 approved, 2,352 suggested (not yet reviewed), 17 reserve, 1,438 dismissed — 1,438 explicit rejections
being counted as wins.

The filter is `<> 'dismissed'`, not `= 'approved'`, and that distinction is the point: counting approved-only
would zero out the 2,352 he simply has not reviewed, punishing sources for his backlog rather than their
quality — the same error as treating an auto-skip as a rejection, which is what began this whole thread.
"""
from __future__ import annotations

import pytest

from neurosearch import candidates as cand
from neurosearch import db
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


def _seed(pid: str, channel: str, statuses: list[str | None]) -> str:
    """A ready source on `channel`, in the project, with one finding per entry. None = omit the column, which
    exercises the NOT NULL DEFAULT 'approved' that older rows were written under."""
    s = db.upsert_source(platform="youtube", external_id=f"ext-{channel}", url=f"https://youtu.be/{channel}",
                         title=channel, channel=channel, status="ready")
    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", (pid, s["id"]))
        for i, st in enumerate(statuses):
            if st is None:
                conn.execute("INSERT INTO project_notes (project_id, source_id, content, created_at) VALUES (?,?,?,?)",
                             (pid, s["id"], f"finding {i}", 0.0))
            else:
                conn.execute("INSERT INTO project_notes (project_id, source_id, content, status, created_at) "
                             "VALUES (?,?,?,?,?)", (pid, s["id"], f"finding {i}", st, 0.0))
    return s["id"]


def test_dismissed_findings_do_not_count_as_yield(fresh):
    pid = db.create_project("y", brief="b")["id"]
    _seed(pid, "Noisy", ["dismissed"] * 8 + ["approved"])
    assert cand.creator_yield(pid)["Noisy"]["findings"] == 1, "rejections were still counted as yield"


def test_unreviewed_findings_still_count(fresh):
    """Otherwise a source is penalised for sitting in the review backlog rather than for being poor."""
    pid = db.create_project("y", brief="b")["id"]
    _seed(pid, "Fresh", ["suggested"] * 5)
    assert cand.creator_yield(pid)["Fresh"]["findings"] == 5


def test_reserve_counts_too(fresh):
    pid = db.create_project("y", brief="b")["id"]
    _seed(pid, "Held", ["reserve"] * 3)
    assert cand.creator_yield(pid)["Held"]["findings"] == 3


def test_rows_written_before_the_status_column_existed_still_count(fresh):
    """`status` is NOT NULL DEFAULT 'approved', so an omitted status means approved — never dismissed."""
    pid = db.create_project("y", brief="b")["id"]
    _seed(pid, "Legacy", [None, None, "approved"])
    assert cand.creator_yield(pid)["Legacy"]["findings"] == 3


def test_two_creators_with_the_same_raw_count_are_now_distinguishable(fresh):
    """The behaviour the fix exists for: identical finding counts, opposite quality."""
    pid = db.create_project("y", brief="b")["id"]
    _seed(pid, "Good", ["approved"] * 10)
    _seed(pid, "Noise", ["dismissed"] * 9 + ["approved"])
    y = cand.creator_yield(pid)
    assert y["Good"]["findings"] == 10
    assert y["Noise"]["findings"] == 1
