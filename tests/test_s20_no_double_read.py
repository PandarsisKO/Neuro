"""S20 — work in flight is still work (0.62.6). (Sorts after test_s19.)

Measured on Kyle's live database, 2026-09-10: **166 sources were analysed twice that day, costing $22.67**, and
every pair had the same shape —

    Copy of Acquisition Ace Deal Calculator
       pass: 13:28 → 13:30   4 windows   $1.768   [local]
       pass: 15:50 → 16:12  12 windows   $1.510   [batch]
       brief_rev d4da9549…  facts_rev 5fb2f4bc…  (identical across both)

15:50–16:12 is the window in which 410 stranded batch cohorts were recovered and settled. Those batches had been
submitted, and charged, on Sep 8–9; their results sat uncollected; and in the meantime the ordinary queue read the
same sources again, because `findings.is_current` only ever consulted the analysis ROW. **Work that had been bought
but not yet collected was invisible to the check whose whole job is to stop paying twice.**

`db.batch_coverage(source_id, input_hash)` answers it from the item table with no new state, because
`findings.batch_requests` already builds a `custom_id` of `fw-<source12>-<window>-<inputhash12>` — the same inputs
always produce the same ids.

The hash is what makes the guard safe rather than blunt: a stale rebuild, a brief edit and a deep read all change
`input_hash`, so none of them match and none of them are blocked. It fires only when the answer to *exactly* this
question has already been paid for.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_dbl_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, findings  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _source(sid="s1"):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (sid, "youtube", sid, f"https://y/{sid}", "A source", "ready", 1.0, 1.0))
        conn.execute("INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                     (sid, 0, 0.0, 60.0, "the seller financed ten percent of the purchase price over three years"))
    return sid


def _batch_item(sid, ih, status="submitted", window=0):
    p = db.create_project("b", brief="x")
    db.create_job("suggest_findings_batch", {"project_id": p["id"]})
    jid = db.list_jobs(limit=1)[0]["id"]
    with db.tx() as conn:
        conn.execute("INSERT INTO batch_items (job_id, cohort_no, custom_id, task, project_id, source_id, "
                     "window_index, windows, params, batch_id, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (jid, 1, f"fw-{sid[:12]}-{window}-{ih[:12]}", "findings.extract", p["id"], sid,
                      window, 1, "{}", "batch_abc", status, 1.0, 1.0))


# ------------------------------------------------------------------ the question the item table can answer

def test_coverage_is_found_from_the_custom_id_alone(fresh):
    sid = _source()
    p = db.create_project("proj", brief="buying businesses")
    ih = findings.input_hash(p, sid)
    assert db.batch_coverage(sid, ih)["covered"] is False
    _batch_item(sid, ih)
    cov = db.batch_coverage(sid, ih)
    assert cov["covered"] is True and cov["items"] == 1 and cov["waiting"] == 1 and cov["collected"] == 0
    assert cov["batch_ids"] == ["batch_abc"]


def test_a_collected_but_unwritten_result_also_counts(fresh):
    """`succeeded` means the provider's answer is already persisted here — the money is spent either way."""
    sid = _source()
    p = db.create_project("proj", brief="b")
    ih = findings.input_hash(p, sid)
    _batch_item(sid, ih, status="succeeded")
    cov = db.batch_coverage(sid, ih)
    assert cov["collected"] == 1 and cov["waiting"] == 0 and cov["covered"] is True


def test_a_finished_item_does_not_count(fresh):
    sid = _source()
    p = db.create_project("proj", brief="b")
    ih = findings.input_hash(p, sid)
    for st in ("materialized", "errored", "expired", "canceled"):
        with db.tx() as conn:
            conn.execute("DELETE FROM batch_items")
        _batch_item(sid, ih, status=st)
        assert db.batch_coverage(sid, ih)["covered"] is False, st


# ------------------------------------------------------------------ the guard, and what it refuses to block

def test_the_local_pass_is_skipped_when_a_batch_already_covers_it(fresh, monkeypatch):
    sid = _source()
    p = db.create_project("proj", brief="buying businesses")
    ih = findings.input_hash(p, sid)
    _batch_item(sid, ih)
    called = []
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: called.append(1) or [])
    out = findings.suggest_for_source(p["id"], sid)
    assert out["skipped_reason"] == "batch_in_flight"
    assert "pay twice" in out["note"] and out["batch"]["items"] == 1
    assert not called                                    # no windows built, so nothing could be sent


def test_it_holds_even_under_force_because_the_hash_is_the_same_question(fresh, monkeypatch):
    sid = _source()
    p = db.create_project("proj", brief="b")
    _batch_item(sid, findings.input_hash(p, sid))
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: pytest.fail("re-read a question already paid for"))
    out = findings.suggest_for_source(p["id"], sid, force=True)
    assert out["skipped_reason"] == "batch_in_flight"


def test_a_deep_read_is_a_different_question_and_is_never_blocked(fresh, monkeypatch):
    """The guard must not become a way to lose work the user asked for. `depth` changes the hash, so it does not
    match — and the same is true of a brief edit or a changed transcript."""
    sid = _source()
    p = db.create_project("proj", brief="b")
    _batch_item(sid, findings.input_hash(p, sid))                 # shallow batch in flight
    ran = []
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: ran.append(1) or [])
    out = findings.suggest_for_source(p["id"], sid, depth="deep", force=True)
    assert out.get("skipped_reason") != "batch_in_flight"
    assert ran                                                     # the deep read proceeded


def test_a_batch_for_older_inputs_does_not_block_a_rebuild(fresh, monkeypatch):
    sid = _source()
    p = db.create_project("proj", brief="the original brief")
    _batch_item(sid, findings.input_hash(p, sid))
    db.update_project(p["id"], brief="a completely rewritten brief")    # brief_revision moves, so the hash does
    p2 = db.get_project(p["id"])
    assert db.batch_coverage(sid, findings.input_hash(p2, sid))["covered"] is False
    ran = []
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: ran.append(1) or [])
    findings.suggest_for_source(p["id"], sid, force=True)
    assert ran


def test_the_custom_id_shape_the_guard_depends_on_is_the_one_batches_build(fresh):
    """A guard that matches on an id format must fail loudly if that format ever changes."""
    sid = _source()
    p = db.create_project("proj", brief="b")
    reqs = findings.batch_requests(p["id"], sid)
    assert reqs, "expected at least one window"
    ih = findings.input_hash(p, sid)
    assert reqs[0]["custom_id"] == f"fw-{sid[:12]}-0-{ih[:12]}"
