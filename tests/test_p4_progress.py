"""Honest progress for long background work (Kyle, live 2026-09-09).

"we need much more reliable or insightful progress bars or progress updates, I get nervous that things look locked
up or frozen, the background processes says they will take several hours but I never know if something is actually
happening."

Two separate causes, both real. `claims.extract` accepted no progress callback at all, so a pass with a measured
p90 of 6,821 s sat at 0.0 and — because a progress report is also the job's heartbeat — additionally tripped the
UI's "quiet for a while" warning while working perfectly. And the batch path threw away the per-request counts the
provider returns on every poll, showing a static "up to 24 hours" line for hours.

Mission Principle 6 governs the fix: never fake progress. Everything asserted here is a real count. (Sorts after
test_p3.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_prog_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import batches, claims, db  # noqa: E402
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


def test_claim_extraction_reports_every_group_with_real_counts(monkeypatch):
    """The bar must move, and the message must say something a person can check against reality."""
    p = db.create_project("Prog", "brief")
    for i in range(claims.EXTRACT_GROUP * 3):
        claims.add_claim(p["id"], text=f"Candidate claim {i} about acquisition financing.", normalized=False)

    seen = []
    monkeypatch.setattr(claims, "extraction_hash", lambda *a, **k: "skip-the-model")
    # every group is already stamped, so no model call happens — we are testing the reporting, not the extraction
    for c in claims.unnormalized(p["id"]):
        db.connect().execute("UPDATE project_claims SET extraction_hash='skip-the-model' WHERE id=?", (c["id"],))
    db.connect().commit()

    claims.extract(p["id"], transport="job", progress=lambda frac, msg: seen.append((round(frac, 3), msg)))
    assert seen, "extraction reported nothing at all — the original defect"
    fracs = [f for f, _ in seen]
    assert fracs == sorted(fracs) and fracs[0] < fracs[-1]          # monotonic, and it actually advances
    assert all(0.0 <= f <= 1.0 for f in fracs)
    assert any("group 1 of 3" in m for _, m in seen)                # names where it is, not just "working…"
    assert any("group 3 of 3" in m for _, m in seen)


def test_a_parked_batch_shows_the_providers_own_counts_not_a_static_scare():
    """Before: "processing in background — up to 24 hours; 0/N ready", unchanged for hours. After: what the
    provider actually reports, and when we last asked."""
    j = db.create_job("suggest_findings_batch", {"project_id": "p1", "source_ids": ["s1", "s2"]})
    db.claim_job(("suggest_findings_batch",))
    db.park_external(j["id"], db.get_job(j["id"])["run_id"], "anthropic", "batch", "msgbatch_abc")
    db.kv_set("batch:progress:msgbatch_abc",
              json.dumps({"processing": 6, "succeeded": 14, "errored": 0, "canceled": 0, "expired": 0, "ts": db.now()}))

    ui = batches.ui_state(db.get_job(j["id"]))
    assert ui["phase"] == "processing"
    assert ui["provider_done"] == 14 and ui["provider_total"] == 20
    assert "14 of 20 requests done" in ui["label"]
    assert "checked just now" in ui["label"]                        # freshness of the evidence, not a promise
    assert "24 hours" not in ui["label"]


def test_a_parked_batch_with_no_counts_yet_still_says_something_true():
    """Before the first poll there are no counts. It must fall back, never invent."""
    j = db.create_job("suggest_findings_batch", {"project_id": "p1", "source_ids": ["s1"]})
    db.claim_job(("suggest_findings_batch",))
    db.park_external(j["id"], db.get_job(j["id"])["run_id"], "anthropic", "batch", "msgbatch_none")
    ui = batches.ui_state(db.get_job(j["id"]))
    assert ui["phase"] == "processing" and "provider_done" not in ui
