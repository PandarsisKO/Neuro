"""S4 — the Findings workbench (0.42.0): server-side composable filters (text, status, importance, source, used-by, source
staleness, Research Area), facets that show what choosing them would give, sorts, paging, use badges (plan · chat · Claim)
and the low-value sweep (approved, importance ≤ 2, never used — reviewed, never automatic). $0. (Sorts after test_n5.)"""
from __future__ import annotations

import json
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


def _five_star_fixture():
    pid = db.create_project("Buying a small business")["id"]
    quote = "Ask the owner what they track in the weekly operations meeting."
    src = db.upsert_source(platform="web", external_id="weekly-ops", url="https://example.com/ops",
                           title="Operating handover", status="ready")
    sid = src["id"]
    db.add_project_sources(pid, [sid])
    db.replace_transcript(sid, [
        {"start": 1, "end": 1, "text": quote},
        {"start": 2, "end": 2, "text": "Other advice is on the following page."},
    ], [])
    citation = {"source_id": sid, "link": src["url"], "start": 1, "snippet": quote, "title": src["title"]}

    def add(**kwargs):
        note = {"title": "Operations handover", "content": quote, "citations": [citation],
                "status": "suggested", "importance": 5, **kwargs}
        with db.tx() as conn:
            return conn.execute(
                "INSERT INTO project_notes (project_id, source_id, source_revision, created_at, "
                "title, content, citations, status, importance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, sid, note.get("revision", db.source_revision(sid)), db.now(), note["title"], note["content"],
                 json.dumps(note["citations"]), note["status"], note["importance"]),
            ).lastrowid

    return pid, sid, add, citation


def test_five_star_preview_and_bulk_hold_leave_the_manual_review_pile_intact():
    pid, sid, add, cite = _five_star_fixture()
    safe = add()
    sensitive = add(content="All buyers must pay a 20 percent equity injection for an SBA loan.")
    hard_threshold = add(content="The financing plan faces a hard 1.25x DSCR threshold.")
    altered_quote = add(citations=[dict(cite, snippet="Ask the broker what they track in the weekly operations meeting.")])
    absent = add(citations=[])
    wrong_location = add(citations=[dict(cite, start=2)], status="reserve")
    wrong_source = add(citations=[dict(cite, source_id="some-other-deal")])
    legacy = add(revision=None)
    ordinary = add(importance=4, citations=[])
    dismissed = add(status="dismissed")
    held = {sensitive, hard_threshold, altered_quote, absent, wrong_location, wrong_source, legacy}
    before = db.list_project_notes(pid, status=None)
    preview = api.api_five_star_review(pid)
    assert preview["eligible_ids"] == [safe]
    assert {n["id"] for n in preview["held"]} == held - {wrong_location}
    assert all(n["hold_reason"] for n in preview["held"])
    assert db.list_project_notes(pid, status=None) == before

    result = api.api_notes_bulk(api.BulkNotesIn(note_ids=[safe, *held, ordinary, dismissed], status="approved"))
    assert result["n"] == 2 and result["skipped"] == 1
    assert {n["id"] for n in result["held"]} == held
    assert {n["id"] for n in db.list_project_notes(pid)} == {safe, ordinary}
    unchanged = {n["id"]: n for n in db.list_project_notes(pid, status=None) if n["id"] in held}
    assert unchanged == {n["id"]: n for n in before if n["id"] in held}
    assert api.api_notes_bulk(api.BulkNotesIn(note_ids=[absent], status="approved", individually_reviewed=True))["n"] == 1
    assert api.api_notes_bulk(api.BulkNotesIn(note_ids=[wrong_location], status="dismissed"))["n"] == 1
    assert {n["id"] for n in db.list_project_notes(pid, status="dismissed")} == {dismissed, wrong_location}


def test_five_star_confirmation_rechecks_source_revision_and_project_scope():
    pid, sid, add, _ = _five_star_fixture()
    safe = add()
    other_id = db.create_project("Another deal")["id"]
    other = db.add_project_note(other_id, "Another project's note.", status="suggested", importance=4)
    assert api.api_five_star_review(pid)["eligible_ids"] == [safe]
    db.replace_transcript(sid, [{"start": 1, "end": 1, "text": "The source changed after preview."}], [])
    r = api.api_notes_bulk(api.BulkNotesIn(note_ids=[safe, other["id"]], status="approved", five_star_project_id=pid))
    assert r["n"] == 0 and r["skipped"] == 1 and [n["id"] for n in r["held"]] == [safe]
    assert db.list_project_notes(pid, status="suggested")[0]["id"] == safe
    assert db.list_project_notes(other_id, status="suggested")[0]["id"] == other["id"]


def test_five_star_gate_does_not_overwrite_a_concurrent_human_verdict(monkeypatch):
    from neurosearch import findings_quality

    pid, _, add, _ = _five_star_fixture()
    note_id = add()
    hold = findings_quality.five_star_hold

    def dismiss_after_check(note, members):
        assert hold(note, members) is None
        db.set_note_status(note_id, "dismissed")
        return None

    monkeypatch.setattr(findings_quality, "five_star_hold", dismiss_after_check)
    r = api.api_notes_bulk(api.BulkNotesIn(note_ids=[note_id], status="approved"))
    assert r["n"] == 0 and r["skipped"] == 1
    assert db.list_project_notes(pid, status="dismissed")[0]["id"] == note_id



def test_returning_an_approval_to_suggested_requires_another_individual_verdict():
    pid, _, add, _ = _five_star_fixture()
    note_id = add()
    assert api.api_notes_bulk(api.BulkNotesIn(note_ids=[note_id], status="approved"))["n"] == 1
    assert api.api_notes_bulk(api.BulkNotesIn(note_ids=[note_id], status="suggested"))["n"] == 1
    preview = api.api_five_star_review(pid)
    assert preview["eligible_ids"] == []
    assert preview["held"][0]["hold_reason"] == "This finding was sent back for individual review."
    result = api.api_notes_bulk(api.BulkNotesIn(note_ids=[note_id], status="approved"))
    assert result["n"] == 0 and [n["id"] for n in result["held"]] == [note_id]
    assert api.api_notes_bulk(api.BulkNotesIn(
        note_ids=[note_id], status="approved", individually_reviewed=True))["n"] == 1



@pytest.mark.parametrize(("quote", "passage", "eligible"), [
    ("The posted usage reached 15", "The posted usage reached 15% on Friday.", False),
    ("The agreed ratio was 1.25x", "The agreed ratio was 1.25 on Friday.", False),
    ("The account adjustment was 300 dollars", "The account adjustment was −300 dollars.", False),
    ("The recording shows > 500 trips", "The recording shows ≥ 500 trips.", False),
    ("The recorded cost was £1500", "The recorded cost was $1,500.", False),
    ("The recorded cost was $1500", "The recorded cost was $1,500.", True),
    ("The report shows 15 gallons", "The report shows 1.5 gallons.", False),
    ("THE OWNER’S logs were available", "The owner's logs were available.", True),
    ("The owner approved the transfer", "The owner did not approve the transfer.", False),
])
def test_five_star_bulk_validation_preserves_quote_meaning(quote, passage, eligible):
    pid, sid, add, cite = _five_star_fixture()
    db.replace_transcript(sid, [{"start": 1, "end": 1, "text": passage}], [])
    note_id = add(citations=[dict(cite, snippet=quote)])
    preview = api.api_five_star_review(pid)
    assert (note_id in preview["eligible_ids"]) is eligible
    result = api.api_notes_bulk(api.BulkNotesIn(note_ids=[note_id], status="approved"))
    assert result["n"] == int(eligible)
    assert len(result["held"]) == int(not eligible)


def test_findings_review_context_is_read_only_and_checks_source_scope():
    pid, sid, add, cite = _five_star_fixture()
    quote = cite["snippet"]
    db.replace_transcript(sid, [{"start": 1, "end": 1,
                                 "text": f"The seller described the handover. {quote} Ask to see their agenda."}], [])
    good = add(importance=3)
    mismatch = add(citations=[dict(cite, snippet="The seller runs every meeting with an agenda.")])
    old = add(revision="older")
    legacy = add(revision=None)
    absent = add(citations=[])
    before = db.list_project_notes(pid, status=None)
    result = api.api_finding_source_context(pid, good)
    assert result["matched"] and quote in result["text"] and "Ask to see their agenda." in result["text"]
    result = api.api_finding_source_context(pid, mismatch)
    assert not result["matched"] and "could not be verified" in result["message"] and quote in result["text"]
    assert "changed" in api.api_finding_source_context(pid, old)["message"]
    result = api.api_finding_source_context(pid, legacy)
    assert not result["matched"] and "no recorded source revision" in result["message"]
    assert "No indexed passage" in api.api_finding_source_context(pid, absent)["message"]
    with pytest.raises(api.HTTPException) as error:
        api.api_finding_source_context("different-project", good)
    assert error.value.status_code == 404
    assert db.list_project_notes(pid, status=None) == before
    db.remove_project_sources(pid, [sid])
    assert "unavailable" in api.api_finding_source_context(pid, good)["message"]
