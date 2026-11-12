"""Queue progress refreshes independent of worker and provider lifecycle changes."""
from pathlib import Path
import shutil
import subprocess

import pytest

from neurosearch import db


def test_tick_distinguishes_new_progress_from_a_worker_check_in(client, monkeypatch):
    project = db.create_project("Queue progress revisions")
    job = db.create_job("fixture_queue_activity", {"project_id": project["id"]})
    before = db.project_view_revision(project["id"])
    claimed = db.claim_job(kinds=("fixture_queue_activity",))
    assert claimed["id"] == job["id"]
    started = db.project_view_revision(project["id"])
    assert started["jobs"] != before["jobs"]
    with monkeypatch.context() as patch:
        patch.setattr(db, "now", lambda: claimed["heartbeat_at"] + 3)
        assert db.heartbeat(job["id"], claimed["run_id"])
    checked = db.project_view_revision(project["id"])
    assert checked["job_activity"] != started["job_activity"]
    assert checked["jobs"] == started["jobs"]
    db.update_job(job["id"], progress=0.8, message="old attempt", run_id="earlier-run")
    assert not db.get_job(job["id"])["progress"]
    db.update_job(job["id"], progress=0.25, message="5 of 20 checked", run_id=claimed["run_id"])
    assert db.get_job(job["id"])["progress"] == 0.25
    assert db.project_view_revision(project["id"])["jobs"] != checked["jobs"]
    db.update_job(job["id"], status="done")


def test_shipped_job_bars_follow_the_real_provider_count_and_wait_state():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required")
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([node, "tests/js/run-queue-progress.mjs"], cwd=root, text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
