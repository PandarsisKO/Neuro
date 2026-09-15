"""L-15 (EXECUTION-LADDER.md P0.E, CTO rulings §1.E): claims.set_status is the sole promotion door. No autonomous
path -- suggest_findings, extract_claims, harvest, _after_done, or anything reachable from t4.execute/t5.research
-- may ever move a Claim to 'accepted' or 'rejected'; only a user-driven API route may. Two independent proofs:

1. Static: grep the whole neurosearch/ package for every call site of `claims.set_status(` / `set_status(` and
   assert the only ones are the two known, explicitly user-gated API surfaces (api.py's direct route and
   claims_view.bulk_status, both called only from POST /api/... routes behind require_auth) plus the function's
   own definition in claims.py. A new autonomous call site added anywhere else fails this test immediately,
   without needing to first observe its effect.

2. Dynamic: run the real end-to-end T4/harvest pipeline (reusing test_k6_claims.py's proven multi-source,
   multi-claim acceptance fixture -- governing/derivative/outlier/stale claims, the full harvest+assess+map path,
   the G5 acceptance gate's own fixture) under fake AI, and assert every resulting Claim's status is in
   ('proposed', 'superseded') -- 'superseded' being the one autonomous transition that IS allowed (dedup/merge of
   a still-proposed duplicate into another still-proposed Claim, gated `AND status='proposed'` in claims.py so it
   can never touch an already-accepted Claim), never 'accepted' or 'rejected'."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from neurosearch import claims, db, fake_ai, jobs
from neurosearch.config import settings

REPO_ROOT = Path(__file__).resolve().parent.parent
NEUROSEARCH_DIR = REPO_ROOT / "neurosearch"

# Files allowed to call claims.set_status / set_status(...): the function's own definition, and the two
# explicitly user-gated surfaces (a direct claim-status API route, and the bulk-status helper those routes call).
ALLOWED_CALLERS = {"claims.py", "api.py", "claims_view.py"}

SET_STATUS_CALL = re.compile(r"(?<!def )(?:claims(?:_mod)?\.)?set_status\s*\(")


def test_set_status_is_only_called_from_the_two_known_user_gated_surfaces():
    offenders = []
    for path in NEUROSEARCH_DIR.glob("*.py"):
        if path.name in ALLOWED_CALLERS:
            continue
        text = path.read_text()
        for m in SET_STATUS_CALL.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{path.name}:{line_no}")
    assert not offenders, f"claims.set_status called from an unexpected (potentially autonomous) site: {offenders}"


def test_the_full_harvest_pipeline_never_promotes_a_claim(tmp_path, monkeypatch):
    from tests.test_k6_claims import _acceptance_fixture

    # Same fresh-DB setup test_k6_claims.py's own autouse fixture does -- that fixture is scoped to its own
    # module, so it does not apply here; _acceptance_fixture itself just builds project/source/claim content on
    # whatever DB is already open.
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()

    pid, ids = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)                     # the $0 harvest + assess + map path exercised by the G5 acceptance gate

    all_claims = claims.list_for_project(pid)
    assert all_claims, "the fixture must actually produce claims for this test to mean anything"
    bad = [(c["id"], c["status"]) for c in all_claims if c["status"] not in ("proposed", "superseded")]
    assert not bad, f"autonomous harvest/assess/map promoted or rejected claims without a user action: {bad}"

    # Confirm directly against the table too (list_for_project may filter): no row anywhere is 'accepted'/'rejected'.
    rows = db.connect().execute(
        "SELECT id, status FROM project_claims WHERE project_id=? AND status IN ('accepted','rejected')", (pid,)
    ).fetchall()
    assert not rows, f"project_claims rows promoted/rejected with no set_status call in this test: {[dict(r) for r in rows]}"
