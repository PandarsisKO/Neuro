"""S104 — the research-map rebuild never runs inside a request or a chat turn.

Kyle, 2026-09-30: a chat sat on "recording that claim for evidence…" for 1,700 s. The `propose_claim` chat tool
called `knowledge.refresh()` — the full map rebuild: re-assess every Claim, detect tensions, assess every target —
synchronously inside the turn. On his project that is 25+ minutes (S102 measured it in the extract job). Seven
click endpoints in api.py and the Claims review queue's bulk verdict did the same. All of them now queue the
refresh through `claims.maybe_refresh` (low lane, deduped per project), which is what `ensure_cheap` has done
since 0.62.2 for exactly this reason. The rows the user asked for are written before the queue call, so nothing
the click meant is deferred — only the derived map."""
from __future__ import annotations

import os
import pathlib
import re
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_s104_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claims, db, knowledge, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1] / "neurosearch"


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_request_paths_never_call_the_full_refresh():
    """api.py and the chat tool loop queue the refresh; the job runners (claims.py) are the only synchronous callers."""
    for name in ("api.py", "qa.py", "claims_view.py"):
        src = (ROOT / name).read_text()
        live = [l for l in src.splitlines() if "knowledge.refresh(" in l and not l.lstrip().startswith("#")]
        assert not live, f"{name} still rebuilds the research map inside a request: {live}"
    assert (ROOT / "api.py").read_text().count("claims.maybe_refresh(") == 7


def test_propose_claim_writes_the_claim_and_queues_the_map(monkeypatch):
    p = db.create_project("Acq", "buying a business")
    called = []
    monkeypatch.setattr(knowledge, "refresh", lambda *a, **k: called.append("sync") or {})
    actions: list = []
    out = qa._run_tool("propose_claim", {"text": "SBA 7(a) loans allow up to $5M", "claim_type": "governing"}, p, [], actions)
    assert "PROPOSED" in out
    assert called == [], "the map is not rebuilt inside the chat turn"
    assert any(j["kind"] == "refresh_research" for j in db.list_jobs(limit=20)), "…it is queued instead"
    assert any(c["text"].startswith("SBA 7(a)") for c in claims.list_for_project(p["id"])), "the Claim itself is written immediately"


def test_bulk_verdict_queues_one_refresh_not_one_per_click():
    from neurosearch import claims_view
    p = db.create_project("Acq", "buying a business")
    ids = [claims.add_claim(p["id"], f"claim {i} about seller notes", claim_type="practice", origin="user", status="proposed", normalized=True)["id"] for i in range(3)]
    r1 = claims_view.bulk_status(p["id"], ids, "accepted")
    r2 = claims_view.bulk_status(p["id"], ids, "rejected")
    assert r1["changed"] == 3 and r2["changed"] == 3
    q = [j for j in db.list_jobs(limit=50) if j["kind"] == "refresh_research" and j["status"] == "queued"]
    assert len(q) == 1, "deduped per project: a second verdict does not queue a second rebuild"
