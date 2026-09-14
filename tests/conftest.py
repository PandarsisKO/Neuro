"""Shared fixtures. The FastAPI app (with its MCP mount) can only be started ONCE per process, so the API client is
session-scoped here and every module that talks to the app through HTTP uses this one instance."""
from __future__ import annotations

import os

import pytest

# The developer machine's .env selects the local Claude Code profile. Tests
# that monkeypatch the Anthropic client must stay on the cloud-shaped adapter;
# otherwise collection order can launch the real CLI. Local-provider tests set
# `settings.ai_profile = "local"` explicitly.
os.environ["NEUROSEARCH_AI_PROFILE"] = "cloud"

# A developer .env may be experimenting with features that the release contract
# requires off.  Collection must begin from the production-safe defaults;
# individual tests opt into a flag explicitly when they exercise it.
os.environ["NEUROSEARCH_PLANNER_V3"] = "0"
os.environ["NEUROSEARCH_FINDINGS_PREFILTER"] = "0"
os.environ["NEUROSEARCH_RETRIEVAL_RERANK"] = "0"
os.environ["NEUROSEARCH_CHAT_TAIL_BREAKPOINT"] = "0"
os.environ["NEUROSEARCH_SCHEMA_COMPAT_FALLBACK"] = ""
os.environ["NEUROSEARCH_FAKE_AI"] = "0"
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

# 2026-09-13 — the data directory is HARD-SET here, unconditionally, before any test module is imported. Seventy-eight
# modules still say `os.environ.setdefault("NEUROSEARCH_DATA_DIR", tmp)`; Kyle's `.env` sets that variable, so on
# his Mac `setdefault` loses and a focused run (`pytest tests/test_k3_resources.py`) wrote ten projects and their jobs
# into the LIVE database on 2026-09-12 — jobs the live server then executed with real providers. The full suite was
# only ever safe because `test_core.py` hard-sets the variable and happens to import first. Conftest runs before every
# module, so this is the one place the guarantee belongs; `tests/test_s51_test_isolation.py` keeps it true.
import tempfile
os.environ["NEUROSEARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="ns_pytest_")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from neurosearch.api import app
    from neurosearch import jobs
    # Endpoint tests drive jobs explicitly. Worker lifecycle tests start real workers separately.
    with pytest.MonkeyPatch.context() as lifecycle:
        lifecycle.setattr(jobs, "start_workers", lambda: None)
        lifecycle.setattr(jobs, "stop_workers", lambda: None)
        with TestClient(app) as c:
            lifecycle.undo()
            yield c
            lifecycle.setattr(jobs, "stop_workers", lambda: None)


@pytest.fixture
def run_queued_job():
    """Claim and execute exactly the requested queued job, without a racing background consumer."""
    from neurosearch import db, jobs
    def run(job_id):
        row = db.get_job(job_id)
        db.bump_job(job_id)
        claimed = db.claim_job((row["kind"],), worker_id="test-driver")
        assert claimed and claimed["id"] == job_id
        assert jobs.execute(claimed, "test-driver") == "done", db.get_job(job_id)
        return db.get_job(job_id)
    return run
