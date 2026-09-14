"""S4 — the Findings workbench (0.42.0): server-side composable filters (text, status, importance, source, used-by, source
staleness, Research Area), facets that show what choosing them would give, sorts, paging, use badges (plan · chat · Claim)
and the low-value sweep (approved, importance ≤ 2, never used — reviewed, never automatic). $0. (Sorts after test_n5.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_fw_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, findings_view as fv, jobs, knowledge, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture, _note  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def test_filters_compose_facets_explain_and_badges_come_from_real_rows(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid); knowledge.refresh(pid)
    # two low-importance approved findings nobody uses, on the outlier's source
    for k in range(2):
        _note(pid, ids["outlier"], f"minor aside {k} about office coffee", "coffee", importance=1, locator="0:30", start=30, title=f"Coffee {k}")
    # a plan step that cites the primary's finding, and a chat answer citing the stale one at its locator
    src = db.get_source(ids["primary"])
    db.save_plan(pid, {"steps": [{"title": "Standby", "evidence": ["F1"]}], "_evidence": {"F1": {"source_id": ids["primary"], "label": "standby", "url": src["url"], "timestamp": "§ 1"},
                                                                                       "F2": {"source_id": ids["stale"], "label": "unreferenced", "timestamp": "§ 1"}}}, "test")
    conv = db.create_conversation(pid, "chat")
    db.save_message(conv["id"], "assistant", "Fees [1].", citations=[{"n": 1, "source_id": ids["stale"], "title": "fees", "timestamp": "§ 1"}])
    r = fv.query(pid)
    assert r["total"] == 8 and len(r["findings"]) == 8                         # 6 fixture findings + 2 asides, all approved
    by_src = {f["source_id"]: f for f in r["findings"] if f["source_id"] in (ids["primary"], ids["stale"])}
    assert by_src[ids["primary"]]["used"]["plan"] == 1 and by_src[ids["primary"]]["used"]["claim"] == "strong" and by_src[ids["primary"]]["used"]["claim_counts"]
    assert by_src[ids["stale"]]["used"]["plan"] == 0, "evidence the plan body never references is not use"
    assert by_src[ids["stale"]]["used"]["chat"] == 1 and by_src[ids["stale"]]["used"]["never"] is False
    outl = next(f for f in r["findings"] if f["source_id"] == ids["outlier"] and f["importance"] == 5)
    assert outl["used"]["claim"] == "weak" and outl["used"]["claim_counts"] is False and outl["used"]["never"] is True   # a weak harvested Claim is not use
    # composable: importance ≥ 4 AND used=plan → the primary only
    r2 = fv.query(pid, min_importance=4, used="plan")
    assert [f["source_id"] for f in r2["findings"]] == [ids["primary"]]
    # facets describe the other dimensions of the filtered set (used facet ignores its own filter)
    assert r2["facets"]["used"]["plan"] == 1 and r2["facets"]["used"]["claim"] >= 1 and r["facets"]["used"]["never"] >= 3
    assert set(r2["facets"]["importance"]) <= {"5", "4", "3", "1"}
    # text search over title + content + source title
    assert fv.query(pid, q="coffee")["total"] == 2 and fv.query(pid, q="standby seller")["total"] >= 1 and fv.query(pid, q="zebra")["total"] == 0
    # never used + low importance = the sweep; it is a review list, nothing is dismissed by itself
    sw = r["low_value_sweep"]
    assert sw["count"] == 2 and "never used" in sw["line"]
    assert fv.query(pid, used="never", min_importance=None)["total"] >= 2
    assert len(db.list_project_notes(pid, status="approved")) == 8
    # sorts and paging
    imp = [f["importance"] for f in fv.query(pid, sort="importance")["findings"]]
    assert imp == sorted(imp, reverse=True)
    pg = fv.query(pid, limit=3, offset=3)
    assert pg["total"] == 8 and len(pg["findings"]) == 3 and pg["offset"] == 3
    used_first = fv.query(pid, sort="used")["findings"][0]
    assert used_first["used"]["plan"] or used_first["used"]["claim"]
    # area filter: findings inherit their Claim's Research Area; a bogus area matches nothing
    areas = fv.query(pid)["facets"]["area"]
    assert areas and fv.query(pid, area=next(iter(areas)))["total"] >= 1 and fv.query(pid, area="Nope")["total"] == 0
    # status and source filters; the API mirrors the engine
    assert fv.query(pid, status="suggested")["total"] == 0 and fv.query(pid, status="all")["total"] == 8
    assert fv.query(pid, source_id=ids["outlier"])["total"] == 3
    a = api.api_findings_query(pid, used="never")
    assert a["total"] == fv.query(pid, used="never")["total"] and "facets" in a and "low_value_sweep" in a


def test_source_staleness_filter_reads_the_analysis_state(monkeypatch):
    from neurosearch import findings, ingest
    p = db.create_project("FW", "hosting")
    r = ingest.ingest_text("Hosting talk", "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks", project_id=p["id"])
    findings.suggest_for_source(p["id"], r["source_id"], force=True)
    for n in db.list_project_notes(p["id"], status="suggested"):
        db.set_note_status(n["id"], "approved")
    assert fv.query(p["id"], stale="current")["total"] == 2 and fv.query(p["id"], stale="stale")["total"] == 0
    db.update_project(p["id"], brief="hosting and email deliverability")
    assert fv.query(p["id"], stale="stale")["total"] == 2 and all(f["source_stale"] for f in fv.query(p["id"])["findings"])
    assert fv.query(p["id"])["facets"]["stale"] == {"stale": 2}


def test_a_populated_embedding_blob_does_not_break_json_serialization(monkeypatch):
    """0.63.67: T1's backfill writes a real embedding BLOB onto project_notes.embedding once a note has been
    vectorised. findings_view._rows_only used to build its row dicts with a bare dict(row) (SELECT * includes
    that column), so once any note in a project had an embedding, GET /findings 500'd with
    PydanticSerializationError: invalid utf-8 sequence... — pydantic trying to treat the raw vector bytes as a
    JSON string. db.row_to_dict() already stripped this for every other reader of project_notes; this was the
    one path that still didn't. Same landmine existed in claims._claim() for project_claims.embedding.

    Exercises the uncached, private row-builders directly (`_rows_only`/`_claim`) rather than the cached public
    wrappers, so a stale cache entry from fixture setup can't hide the very bug this guards against."""
    import json
    pid, ids = _fixture(monkeypatch)
    note_id = next(iter(fv._rows_only(pid)))["id"]
    fake_vector = bytes(range(1, 256)) * 24  # deliberately invalid UTF-8 (no byte is 0, none of it decodes cleanly)
    db.connect().execute("UPDATE project_notes SET embedding=? WHERE id=?", (fake_vector, note_id))
    db.connect().commit()
    rows = fv._rows_only(pid)
    target = next(r for r in rows if r["id"] == note_id)
    assert "embedding" not in target
    json.dumps(rows)  # must not raise TypeError on a raw bytes value

    claims.ensure(pid)
    row = db.connect().execute("SELECT id FROM project_claims WHERE project_id=? LIMIT 1", (pid,)).fetchone()
    assert row, "fixture should have produced at least one claim"
    db.connect().execute("UPDATE project_claims SET embedding=? WHERE id=?", (fake_vector, row["id"]))
    db.connect().commit()
    claim_row = db.connect().execute("SELECT * FROM project_claims WHERE id=?", (row["id"],)).fetchone()
    claim = claims._claim(claim_row)
    assert "embedding" not in claim
    json.dumps(claim)  # must not raise TypeError on a raw bytes value
