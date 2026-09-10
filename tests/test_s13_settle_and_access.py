"""S13 — collecting an abandoned batch, and every legal copy of a paper (0.60.3). (Sorts after test_s12.)

Two audits, both of open items Kyle named.

**The 432 unknown outcomes.** He asked whether they were another pocket of billed-but-unrecorded work. Measured on
his database: **one** job accounts for 426 of them — a `suggest_findings_batch` submitted on 2026-09-08, cancelled
locally 11.7 hours later, whose 426 `batch_items` were still at status `submitted` two days on. `cancel_job` does
the right things in the right order, but it waits one second for the batch to end and then swallows the failure —
and an eleven-hour-old batch does not end within a second of a cancel. So the harvest failed silently and there was
no way back. The provider bills the requests that completed before the cancellation landed, which makes it both a
money leak and a lost-work leak: findings paid for and never written. The rule restored here is the one the account
gates already state — **never leave a state with no path back**.

**Paywalled papers.** *"many of these require a subscription. how do we handle that?"* The app read only OpenAlex's
single `best_oa_location` and did not even request `locations`, so a closed publisher record hid a legally free
repository copy. Reading the whole list is free and changes nothing about access control.
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_settle_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import batches, db, scholar  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    db.create_project("p", brief="b")
    with db.tx() as conn:                       # a project row the fixtures can point at by a stable id
        conn.execute("UPDATE projects SET id='p1'")
    yield
    db._local.conn = None


# ------------------------------------------------------------------ the abandoned batch

HANDLE = "msgbatch_01F8ZLA39ZzrVV4Vxycu55qm"


def _abandoned(project_id="p1", n=3, status="cancelled"):
    job = db.create_job("suggest_findings_batch", {"project_id": project_id, "source_ids": ["s1"]})
    jid = job["id"] if isinstance(job, dict) else job
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status=?, external_provider='anthropic_batch', external_handle=?, "
                     "finished_at=? WHERE id=?", (status, HANDLE, 1788890398.0, jid))
        for i in range(n):
            conn.execute("INSERT INTO batch_items (job_id, batch_id, custom_id, task, project_id, source_id, "
                         "window_index, params, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (jid, HANDLE, f"w{i}", "findings.extract", project_id, "s1", i, "{}", "submitted", 1.0, 1.0))
    return jid


def test_an_abandoned_batch_is_found_durably(fresh):
    """Derived from the rows themselves, so it cannot go stale and cannot be forgotten by a restart."""
    jid = _abandoned()
    rows = batches.unsettled()
    assert len(rows) == 1
    assert rows[0]["job_id"] == jid and rows[0]["items"] == 3 and rows[0]["handle"] == HANDLE
    assert rows[0]["project_id"] == "p1"


def test_a_failed_batch_counts_too_not_only_a_cancelled_one(fresh):
    """6 of the 432 came from a job that failed on low credit, not from the cancel."""
    _abandoned(status="failed")
    assert len(batches.unsettled()) == 1


def test_a_batch_whose_items_all_landed_is_not_listed(fresh):
    jid = _abandoned()
    with db.tx() as conn:
        conn.execute("UPDATE batch_items SET status='materialized' WHERE job_id=?", (jid,))
    assert batches.unsettled() == []


def test_a_tentative_handle_is_never_touched(fresh):
    """Identity unproven: those candidates may belong to another run, and mutating them is the one thing worse
    than leaving them."""
    jid = _abandoned()
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET external_handle=? WHERE id=?", (batches.TENTATIVE + "guess", jid))
    assert batches.unsettled() == []
    assert batches.settle(jid)["settled"] is False


def test_settling_collects_what_completed_and_writes_it(fresh, monkeypatch):
    jid = _abandoned()
    calls = {"persist": 0, "materialize": 0}

    class Counts:
        processing, succeeded, errored, canceled, expired = 0, 2, 0, 1, 0

    class B:
        processing_status = "ended"
        request_counts = Counts()

    monkeypatch.setattr(batches.AnthropicBatch, "_client", classmethod(lambda cls: type("C", (), {
        "messages": type("M", (), {"batches": type("BB", (), {"retrieve": staticmethod(lambda h: B())})()})()})()))
    monkeypatch.setattr(batches.AnthropicBatch, "persist_results",
                        classmethod(lambda cls, h, results=None: calls.__setitem__("persist", calls["persist"] + 1)
                                    or {"succeeded": 2, "errored": 0, "expired": 0, "canceled": 1}))
    monkeypatch.setattr(batches, "materialize_ready",
                        lambda job_id, project_id: calls.__setitem__("materialize", calls["materialize"] + 1)
                        or {"materialized": 1})
    out = batches.settle(jid)
    assert out["settled"] is True and out["counts"]["succeeded"] == 2 and out["materialized"] == 1
    assert calls == {"persist": 1, "materialize": 1}
    assert "were collected" in out["note"]


def test_a_batch_still_processing_is_left_alone_and_says_so(fresh, monkeypatch):
    """Nothing is lost by waiting — but the user has to be told to come back, or this is the same silent gap."""
    jid = _abandoned()

    class Counts:
        processing, succeeded, errored, canceled, expired = 40, 2, 0, 0, 0

    class B:
        processing_status = "in_progress"
        request_counts = Counts()

    monkeypatch.setattr(batches.AnthropicBatch, "_client", classmethod(lambda cls: type("C", (), {
        "messages": type("M", (), {"batches": type("BB", (), {"retrieve": staticmethod(lambda h: B())})()})()})()))
    out = batches.settle(jid)
    assert out["settled"] is False and out["still_processing"] is True
    assert out["counts"]["processing"] == 40
    assert "later" in out["note"]
    assert json.loads(db.kv_get(f"batch:progress:{HANDLE}"))["succeeded"] == 2
    assert len(batches.unsettled()) == 1        # still listed, so it cannot be forgotten


def test_a_batch_the_provider_no_longer_has_stops_pretending(fresh, monkeypatch):
    """Batches expire. An item that will never be collected must not sit at "submitted" for ever — that is the
    state this whole fix exists to end."""
    jid = _abandoned()

    def gone(h):
        raise RuntimeError("404 not_found_error: batch not found")

    monkeypatch.setattr(batches.AnthropicBatch, "_client", classmethod(lambda cls: type("C", (), {
        "messages": type("M", (), {"batches": type("BB", (), {"retrieve": staticmethod(gone)})()})()})()))
    out = batches.settle(jid)
    assert out["settled"] is True and out["gone"] is True and out["items"] == 3
    assert batches.unsettled() == []
    errs = [r["error"] for r in db.batch_items_for_batch(HANDLE)]
    assert all("no longer has this batch" in (e or "") for e in errs)


def test_health_reports_the_gap_and_clears_itself(fresh, monkeypatch):
    jid = _abandoned()
    h = db.health()["batches"]
    assert h["unsettled"] == 1 and h["items"] == 3
    assert h["awaiting_collection"] == 3 and "nobody has collected" in h["note"]
    with db.tx() as conn:
        conn.execute("UPDATE batch_items SET status='materialized' WHERE job_id=?", (jid,))
    assert db.health()["batches"]["unsettled"] == 0


# ------------------------------------------------------------------ every legal copy of a paper

def _openalex(best=None, locations=()):
    return {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "display_name": "A paper",
            "publication_year": 2024, "cited_by_count": 3, "authorships": [],
            "primary_location": {"source": {"display_name": "Journal of Things", "type": "journal"}},
            "best_oa_location": best or {}, "open_access": {"oa_status": "closed"},
            "locations": list(locations), "abstract_inverted_index": None}


def test_a_repository_copy_is_found_when_the_publisher_is_closed():
    """The whole complaint in one test: the paper is paywalled, and a legal free copy exists in a repository the
    app was not looking at."""
    rec = scholar._from_openalex(_openalex(locations=[
        {"is_oa": False, "source": {"display_name": "Journal of Things", "type": "journal"}, "is_published": True},
        {"is_oa": True, "pdf_url": "https://arxiv.org/pdf/1234", "is_accepted": True,
         "source": {"display_name": "arXiv", "type": "repository"}, "version": "acceptedVersion"},
    ]))
    assert rec["oa_pdf_url"] is None                     # the publisher's own copy really is closed
    a = scholar.access(rec)
    assert a["state"] == "elsewhere" and a["url"] == "https://arxiv.org/pdf/1234"
    assert "arXiv" in a["why"] and a["caution"] == "repository copy"
    assert "version of record" in a["why"]               # said out loud, not glossed over


def test_the_publishers_own_open_copy_still_wins():
    rec = scholar._from_openalex(_openalex(best={"pdf_url": "https://publisher/paper.pdf"}, locations=[
        {"is_oa": True, "pdf_url": "https://arxiv.org/pdf/1234", "is_accepted": True,
         "source": {"display_name": "arXiv", "type": "repository"}}]))
    a = scholar.access(rec)
    assert a["state"] == "open" and a["url"] == "https://publisher/paper.pdf"


def test_a_genuinely_closed_paper_says_what_to_do_instead():
    """Not "here is a button that will fetch a paywall stub" — the honest next step is the user's own access."""
    rec = scholar._from_openalex(_openalex())
    a = scholar.access(rec)
    assert a["state"] == "closed"
    assert "publisher" in a["next"] and "extension" in a["next"]
    assert scholar.acquire(rec, "p1")["queued"] is False


def test_a_free_copy_elsewhere_can_be_acquired(fresh):
    rec = scholar._from_openalex(_openalex(locations=[
        {"is_oa": True, "pdf_url": "https://pmc/article.pdf", "source": {"display_name": "PubMed Central",
                                                                         "type": "repository"}}]))
    out = scholar.acquire(rec, "p1")
    assert out["queued"] is True and out["url"] == "https://pmc/article.pdf"
    assert out["access"] == "elsewhere" and out["caution"] == "repository copy"


def test_a_landing_page_counts_when_there_is_no_pdf():
    rec = scholar._from_openalex(_openalex(locations=[
        {"is_oa": True, "landing_page_url": "https://repo/record/1",
         "source": {"display_name": "Institutional repo", "type": "repository"}}]))
    c = scholar.best_copy(rec)
    assert c["url"] == "https://repo/record/1" and c["pdf"] is False


def test_the_catalogue_is_asked_for_the_locations_at_all():
    """The data was never requested, which is why "not openly available" was sometimes just not having looked."""
    assert "locations" in scholar.OPENALEX_FIELDS


def test_discover_rows_carry_the_access_state():
    rec = scholar._from_openalex(_openalex(locations=[
        {"is_oa": True, "pdf_url": "https://arxiv.org/pdf/9", "is_accepted": True,
         "source": {"display_name": "arXiv", "type": "repository"}}]))
    d = scholar.to_discoveries([rec])[0]
    assert d["access"] == "elsewhere" and d["fit"] == 4 and d["url"] == "https://arxiv.org/pdf/9"
    closed = scholar.to_discoveries([scholar._from_openalex(_openalex())])[0]
    assert closed["access"] == "closed" and closed["fit"] == 3
    assert "no free copy" in closed["angle"]


def test_a_closed_record_still_becomes_a_candidate_with_the_reason(fresh):
    """A record is metadata, and metadata is worth keeping — it just must not pretend to be readable."""
    scholar.to_candidates([scholar._from_openalex(_openalex())], "p1", origin={"kind": "test"})
    rows = db.connect().execute("SELECT description FROM candidates").fetchall()
    assert rows and "metadata only" in rows[0]["description"]
    assert "browser extension" in rows[0]["description"]


# ------------------------------------------------------------------ the UI must not be cached (0.60.4)

def test_the_ui_is_served_no_store():
    """Found by looking at Kyle's real browser: it reported v0.53.1 while the server ran 0.60.3, and a hard reload
    fixed it. The single-file UI was served with no Cache-Control, no ETag and no Last-Modified, so the browser
    kept its own copy for days — which means complaints kept arriving about faults that had already been fixed
    (the identical accelerate buttons, 0.59.2; the wall of queued jobs, 0.60.0). `uvicorn --reload` restarts the
    server; nothing was telling the browser."""
    from neurosearch import api
    assert "no-store" in api.NO_STORE["Cache-Control"]
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "neurosearch", "api.py"), encoding="utf-8").read()
    body = src[src.index("def index(request: Request)"):src.index("@app.post(\"/login\")")]
    assert body.count("headers=NO_STORE") == 2          # the app and the login page both


# ------------------------------------------------------------------ collected but never written (0.61.1)

def _mixed(project_id="p1"):
    """The shape Kyle's abandoned batch actually settled into: one source fully collected, one half-collected
    because the provider cancelled its other window, one already written."""
    job = db.create_job("suggest_findings_batch", {"project_id": project_id, "source_ids": ["whole", "half"]})
    jid = job["id"] if isinstance(job, dict) else job
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status='cancelled', external_provider='anthropic_batch', external_handle=?, "
                     "finished_at=? WHERE id=?", (HANDLE, 1.0, jid))
        rows = [("whole", 0, "succeeded"), ("whole", 1, "succeeded"),
                ("half", 0, "succeeded"), ("half", 1, "canceled"),
                ("done", 0, "materialized")]
        for i, (sid, w, st) in enumerate(rows):
            conn.execute("INSERT INTO batch_items (job_id, batch_id, custom_id, task, project_id, source_id, "
                         "window_index, params, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (jid, HANDLE, f"c{i}", "findings.extract", project_id, sid, w, "{}", st, 1.0, 1.0))
    return jid


def test_a_collected_result_nobody_wrote_still_counts_as_unsettled(fresh):
    """Counting only `submitted` declared the batch finished while 79 paid-for results had gone nowhere."""
    _mixed()
    rows = batches.unsettled()
    assert len(rows) == 1
    assert rows[0]["awaiting_collection"] == 0
    assert rows[0]["collected_not_written"] == 3
    h = db.health()["batches"]
    assert h["collected_not_written"] == 3 and "never written" in h["note"]


def test_the_sources_that_cannot_be_assembled_are_named(fresh):
    """`materialize_ready` is right to refuse half a source — but the refusal was silent, so the paid-for half
    vanished from view. Naming them is what lets someone decide to re-read."""
    jid = _mixed()
    stuck = batches.stuck_sources(jid)
    assert [s["source_id"] for s in stuck] == ["half"]
    assert stuck[0]["collected"] == 1 and stuck[0]["lost"] == 1
    assert "cannot be assembled" in stuck[0]["why"]


def test_a_fully_collected_source_is_not_called_stuck(fresh):
    jid = _mixed()
    assert "whole" not in [s["source_id"] for s in batches.stuck_sources(jid)]


def test_collecting_is_logged_before_writing(fresh, monkeypatch):
    """The first live settle collected 410 results and wrote 331 sources, then materialisation raised — and the
    whole outcome disappeared into an exception handler with nothing in job_events. Collecting is the irreversible
    half, so it is recorded whatever happens next."""
    jid = _abandoned()

    class Counts:
        processing, succeeded, errored, canceled, expired = 0, 2, 0, 0, 0

    class B:
        processing_status = "ended"
        request_counts = Counts()

    monkeypatch.setattr(batches.AnthropicBatch, "_client", classmethod(lambda cls: type("C", (), {
        "messages": type("M", (), {"batches": type("BB", (), {"retrieve": staticmethod(lambda h: B())})()})()})()))
    monkeypatch.setattr(batches.AnthropicBatch, "persist_results",
                        classmethod(lambda cls, h, results=None: {"succeeded": 2, "errored": 0, "expired": 0, "canceled": 0}))

    def boom(job_id, project_id):
        raise RuntimeError("materialisation exploded")

    monkeypatch.setattr(batches, "materialize_ready", boom)
    out = batches.settle(jid)
    assert out["settled"] is True and out["counts"]["succeeded"] == 2
    assert out["error"] and "exploded" in out["error"] and "raised" in out["note"]
    kinds = [e["event_type"] for e in db.job_events(jid)]
    assert "batch_settled" in kinds and "batch_materialised" in kinds
