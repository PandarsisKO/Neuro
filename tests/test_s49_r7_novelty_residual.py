"""Foundation R7: project-relative novelty changes priority/order, never eligibility."""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_r7_novelty_"))

import numpy as np
import pytest

from neurosearch import db, jobs, novelty
from neurosearch.config import settings


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db.close_thread_connection()
    db.init_db()
    yield
    db.close_thread_connection()


def _source(project_id: str, key: str, chunks: list[tuple[str, list[float]]]) -> str:
    src = db.upsert_source(platform="document", external_id=f"r7-{key}", url=f"https://example.test/{key}", title=key, status="ready")
    db.add_project_sources(project_id, [src["id"]])
    segs = [{"idx": i, "start": float(i + 1), "end": float(i + 1), "text": text} for i, (text, _) in enumerate(chunks)]
    db.replace_transcript(src["id"], segs, [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segs])
    rows = db.get_chunks(src["id"])
    db.set_embeddings([(row["id"], np.asarray(vector, dtype=np.float32)) for row, (_, vector) in zip(rows, chunks)])
    return src["id"]


def test_residual_insight_survives_a_redundant_source_and_reads_first(fresh):
    project = db.create_project("R7")
    _source(project["id"], "represented", [("common thesis repeated everywhere", [1, 0]), ("common mechanism", [1, 0])])
    candidate = _source(project["id"], "repeat-with-exception", [("common thesis repeated everywhere", [1, 0]), ("critical exception changes the decision", [0, 1])])
    row = novelty.profile(project["id"], candidate)
    assert row["available"] and row["redundancy"] > 0.4
    assert row["residual_chunks"][0] == 1
    windows = ["[p. 1] common thesis repeated everywhere", "[p. 2] critical exception changes the decision"]
    assert novelty.order_windows(windows, {0, 1}, row) == [1, 0]


def test_no_embeddings_fails_open_and_never_removes_windows(fresh):
    project = db.create_project("R7")
    src = _source(project["id"], "unembedded", [("first", [1, 0])])
    db.connect().execute("UPDATE chunks SET embedding=NULL WHERE source_id=?", (src,))
    row = novelty.profile(project["id"], src)
    assert not row["available"]
    assert novelty.order_windows(["first", "second"], {0, 1}, row) == [0, 1]


def test_same_batch_comparison_is_not_arrival_order_relative(fresh):
    project = db.create_project("R7")
    one = _source(project["id"], "one", [("one", [1, 0])])
    two = _source(project["id"], "two", [("two", [1, 0])])
    forward = novelty.profile(project["id"], one, comparison_source_ids=[one, two])
    reverse = novelty.profile(project["id"], one, comparison_source_ids=[two, one])
    assert forward["redundancy"] == reverse["redundancy"]


def test_redundancy_changes_fast_priority_but_keeps_the_source_warm_eligible(fresh):
    project = db.create_project("R7")
    represented = _source(project["id"], "represented", [("represented", [1, 0, 0, 0])])
    repeated = _source(project["id"], "repeated", [("repeated", [1, 0, 0, 0])])
    novel = _source(project["id"], "novel", [("novel exception", [0, 1, 0, 0])])
    another = _source(project["id"], "another", [("another exception", [0, 0, 1, 0])])
    third = _source(project["id"], "third", [("third exception", [0, 0, 0, 1])])
    plan = jobs.fast_wave_plan(project["id"], [repeated, novel], limit=1)
    assert plan[0]["source_id"] == novel
    scheduled = jobs.enqueue_fast_warm(project["id"], [repeated, novel, another, third])
    assert scheduled["warm"] == [repeated]
    assert any(j["payload"]["source_ids"] == [repeated] for j in scheduled["jobs"])
