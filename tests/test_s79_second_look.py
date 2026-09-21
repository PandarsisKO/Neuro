"""S79 backend — the reviewed_at column, the `reviewed` scope and the `weakest` sort, against a real database."""
from __future__ import annotations
import os, time
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest
from neurosearch import db, findings_view
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _note(pid, sid, imp, status="approved"):
    return db.add_project_note(pid, f"finding at importance {imp}", [], status=status,
                               source_id=sid, importance=imp)["id"]


def test_existing_rows_start_unreviewed_which_is_the_truthful_answer():
    p = db.create_project("p", "b")
    nid = _note(p["id"], None, 2)
    row = db.connect().execute("SELECT reviewed_at FROM project_notes WHERE id=?", (nid,)).fetchone()
    assert row["reviewed_at"] is None, "a row nobody ruled on must not claim to have been reviewed"


def test_setting_a_status_stamps_it_even_when_the_status_does_not_change():
    """A second-look Keep files an already-approved finding as approved. If that did not stamp, the finding
    would come back on the next pass forever."""
    p = db.create_project("p", "b")
    nid = _note(p["id"], None, 2, "approved")
    db.set_note_status(nid, "approved")
    row = db.connect().execute("SELECT status, reviewed_at FROM project_notes WHERE id=?", (nid,)).fetchone()
    assert row["status"] == "approved" and row["reviewed_at"] is not None


def test_the_reviewed_scope_splits_the_two_populations():
    p = db.create_project("p", "b")
    untouched = _note(p["id"], None, 1)
    ruled = _note(p["id"], None, 1)
    db.set_note_status(ruled, "approved")
    no = findings_view.query(p["id"], status="approved", reviewed="no", limit=50)
    yes = findings_view.query(p["id"], status="approved", reviewed="yes", limit=50)
    assert [f["id"] for f in no["findings"]] == [untouched]
    assert [f["id"] for f in yes["findings"]] == [ruled]
    assert findings_view.query(p["id"], status="approved", limit=50)["total"] == 2, "no scope = both"


def test_weakest_sorts_the_opposite_way_from_importance():
    p = db.create_project("p", "b")
    for imp in (5, 1, 3):
        _note(p["id"], None, imp)
    weak = [f["importance"] for f in findings_view.query(p["id"], sort="weakest", limit=50)["findings"]]
    strong = [f["importance"] for f in findings_view.query(p["id"], sort="importance", limit=50)["findings"]]
    assert weak == [1, 3, 5] and strong == [5, 3, 1]
