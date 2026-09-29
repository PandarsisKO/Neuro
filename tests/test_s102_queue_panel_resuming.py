"""S102 — the queue panel says what it is doing (Kyle's screenshot, 2026-09-29).

After ~4,700 findings were bulk-approved the panel read "3 jobs running" over five bars: two `extract_claims`
rows with the same label, both "quiet for 22–26m" inside the research-map refresh, and two `harvest_claims`
rows marked *queued* with 60% progress bars. Three things were wrong, none of them the queue itself:

1. A job that yielded (`jobs.Yield`) came back as a plain `queued` row that kept its progress — a queued job
   with a half-full bar. It now carries `wait_reason="yield"` while it waits, `derived_status` reports
   `resuming`, and the panel says "waiting to resume · progress kept". `claim_job` clears the marker.
2. `knowledge.refresh` — the long tail of an extract job on a big project — emitted no heartbeat, so a healthy
   job tripped the "quiet for a while" warning. It now reports every phase through an optional `progress`.
3. The paid fast pass and the bulk pass are deliberately two jobs; the panel labels them differently now.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_s102_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, jobs, knowledge  # noqa: E402
from neurosearch.config import settings  # noqa: E402

JS = (pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "research.js").read_text()


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_yielded_job_is_resuming_not_queued_until_claimed_again(monkeypatch):
    jid = db.create_job("harvest_claims", {"project_id": "p"})["id"]
    claimed = db.claim_job(kinds=("harvest_claims",), worker_id="w")
    db.update_job(jid, progress=0.6, message="collecting Claims from new findings ($0)")
    monkeypatch.setattr(jobs, "run_job", lambda job: (_ for _ in ()).throw(
        jobs.Yield("harvested 0 new Claims — more findings landed meanwhile, continuing")))
    assert jobs.execute(claimed, worker_id="w") == "queued"
    row = db.get_job(jid)
    assert row["status"] == "queued" and row["wait_reason"] == "yield" and row["attempts"] == 0
    assert db.derived_status(row) == "resuming", "the panel can tell a resumable job from a fresh queued one"
    assert row["progress"] == pytest.approx(0.6), "it kept its progress"
    events = [e["event_type"] for e in db.job_events(jid)]
    assert events.count("yielded") == 1 and "yield_wait" not in events, "one honest event, not a made-up wait"
    again = db.claim_job(kinds=("harvest_claims",), worker_id="w2")
    assert again["id"] == jid
    assert db.get_job(jid)["wait_reason"] is None, "the marker lives exactly as long as the wait"


def test_refresh_reports_every_phase_as_a_heartbeat():
    p = db.create_project("Acq", "buying a business")
    seen: list[str] = []
    knowledge.refresh(p["id"], progress=seen.append)
    assert seen[0].startswith("re-checking ") and "claims" in seen[0]
    assert "looking for tensions between claims" in seen
    assert seen[-1] == "rebuilding the research map"
    # every other caller is unchanged
    knowledge.refresh(p["id"])


def test_panel_wording():
    assert "resuming: 'waiting to resume · progress kept'" in JS
    assert "finding claims to track · the important few first" in JS
    assert "finding claims to track · the rest" in JS
    assert "waiting" in JS and "resum" in JS, "the header names what is waiting, not just what is running"
