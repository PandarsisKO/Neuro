"""Fast/bulk routing for claim extraction (Kyle, live 2026-09-09).

"I want to surface important claims quickly, but want to offload bulky claim work to background and cheap
processing." He chose the two signals himself: a candidate that answers an OPEN QUESTION he is waiting on, or one
from a source he marked PRIORITY — both already recorded in his own data, so triage stays $0 and instant rather
than a model guessing what matters before the cheap work can start.

The rule that must never break: the fast lane REORDERS, it never filters. Kyle's stated workflow is to "feed it
everything I find as I find it not knowing if it will benefit me later", so nothing may be dropped for being
unimportant — it just waits its turn on the cheap lane. (Sorts after test_p2.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_tri_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claims, db, knowledge  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _setup(monkeypatch):
    p = db.create_project("Triage", "buying a business with seller financing")
    s_prio = db.upsert_source(platform="youtube", external_id="prio-1", url="u1", title="Priority", status="ready")
    s_norm = db.upsert_source(platform="youtube", external_id="norm-1", url="u2", title="Normal", status="ready")
    db.add_project_sources(p["id"], [s_prio["id"], s_norm["id"]])
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?",
                         (p["id"], s_prio["id"]))
    db.connect().commit()
    return p, s_prio, s_norm


def _claim(pid: str, text: str, source_id: str | None = None) -> dict:
    note_id = None
    if source_id:
        note_id = db.add_project_note(pid, text, citations=[], status="approved", source_id=source_id)["id"]
    return claims.add_claim(pid, text=text, origin="finding", origin_note_id=note_id, normalized=False)


def test_a_claim_answering_an_open_question_is_fast_tracked(monkeypatch):
    p, _, s_norm = _setup(monkeypatch)
    knowledge.add_target(p["id"], question="How does seller financing work when buying a business?")
    hit = _claim(p["id"], "Seller financing typically covers 60 to 80 percent when buying a small business.", s_norm["id"])
    miss = _claim(p["id"], "Laundromat equipment depreciates over seven years.", s_norm["id"])

    tri = claims.triage(p["id"])
    fast_ids = {c["id"] for c in tri["fast"]}
    assert hit["id"] in fast_ids
    assert "answers an open question" in " ".join(tri["why"][hit["id"]])
    assert miss["id"] not in fast_ids


def test_nothing_is_ever_dropped_only_reordered(monkeypatch):
    """Kyle feeds the app everything on purpose. Unimportant is a scheduling verdict, never an exclusion."""
    p, _, s_norm = _setup(monkeypatch)
    made = [_claim(p["id"], f"Some unremarkable observation number {i} about business.", s_norm["id"]) for i in range(5)]
    tri = claims.triage(p["id"])
    seen = {c["id"] for c in tri["fast"]} | {c["id"] for c in tri["bulk"]}
    assert seen == {c["id"] for c in made}                       # every candidate is still accounted for


def test_the_fast_lane_is_bounded(monkeypatch):
    """'A few per batch' (Kyle): a burst of important-looking claims must not become the cost."""
    p, s_prio, _ = _setup(monkeypatch)
    for i in range(claims.FAST_GROUPS * claims.EXTRACT_GROUP + 25):
        _claim(p["id"], f"Priority claim {i} about acquisition financing.", s_prio["id"])
    tri = claims.triage(p["id"])
    assert len(tri["fast"]) == claims.FAST_GROUPS * claims.EXTRACT_GROUP
    assert len(tri["bulk"]) >= 25                                 # the remainder waits, it does not vanish


def test_routing_creates_a_paid_priority_job_and_a_cheap_bulk_job(monkeypatch):
    p, s_prio, _ = _setup(monkeypatch)
    for i in range(3):
        _claim(p["id"], f"Priority claim {i} about seller financing terms.", s_prio["id"])
    monkeypatch.setattr(claims, "CLAIMS_BATCH_MIN", 1)
    claims.maybe_extract(p["id"], "test", force=True)

    jobs_ = [j for j in db.list_jobs(limit=50) if j["kind"] == "extract_claims"]
    fast = [j for j in jobs_ if (j.get("payload") or {}).get("claim_ids")]
    bulk = [j for j in jobs_ if not (j.get("payload") or {}).get("claim_ids")]
    assert len(fast) == 1 and fast[0]["lane"] == "priority" and fast[0]["execution_policy"] == "api_requested"
    assert len(bulk) == 1 and bulk[0]["lane"] == "slow"           # cheap, non-blocking, local when available
    assert fast[0]["payload"]["why"]                              # it can say WHY it jumped the queue
