"""S57 — CR8's now-resolved product decision (Kyle, 2026-09-16): "primary for this project" lives on the
project<->collection relationship (project_collections.source_role/monitor_policy), never the global collection.
These gates prove the pure derivation (reservoir.effective_monitor_active), that policy is genuinely per-project
(not per-collection), that changing policy never ingests anything, and that pre-existing rows migrate to
conservative (inactive) defaults. See reservoir.py's module docstring and rescan_project() for how CR3/CR4 now
respect this."""
from __future__ import annotations

import pytest

from neurosearch import db, reservoir


@pytest.fixture
def s57_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


# ------------------------------------------------------------- pure derivation truth table (1-5)

@pytest.mark.parametrize("source_role,monitor_policy,expected", [
    ("primary", "auto", True),       # 1
    ("secondary", "auto", False),    # 2
    ("unspecified", "auto", False),  # 3
    ("secondary", "on", True),       # 4
    ("primary", "off", False),       # 5
])
def test_effective_monitor_active_truth_table(source_role, monitor_policy, expected):
    assert reservoir.effective_monitor_active(source_role, monitor_policy) is expected


def test_monitor_policy_on_wins_over_any_role():
    for role in ("primary", "secondary", "unspecified"):
        assert reservoir.effective_monitor_active(role, "on") is True


def test_monitor_policy_off_wins_over_any_role():
    for role in ("primary", "secondary", "unspecified"):
        assert reservoir.effective_monitor_active(role, "off") is False


# ------------------------------------------------------------- per-relationship, not per-collection (6-7)

def test_same_collection_can_be_primary_in_one_project_and_secondary_in_another(s57_db):
    pid_a = db.create_project("S57 A", brief="a")["id"]
    pid_b = db.create_project("S57 B", brief="b")["id"]
    col = db.upsert_collection("channel", "UCshared", "https://www.youtube.com/channel/UCshared", "Shared")
    db.add_project_collections(pid_a, [col["id"]])
    db.add_project_collections(pid_b, [col["id"]])

    db.set_collection_policy(pid_a, col["id"], source_role="primary")
    db.set_collection_policy(pid_b, col["id"], source_role="secondary")

    assert reservoir.is_monitored(pid_a, col["id"]) is True
    assert reservoir.is_monitored(pid_b, col["id"]) is False


def test_project_as_policy_never_leaks_into_project_b(s57_db):
    pid_a = db.create_project("S57 leak A", brief="a")["id"]
    pid_b = db.create_project("S57 leak B", brief="b")["id"]
    col = db.upsert_collection("channel", "UCleak", "https://www.youtube.com/channel/UCleak", "Leak Test")
    db.add_project_collections(pid_a, [col["id"]])
    db.add_project_collections(pid_b, [col["id"]])

    db.set_collection_policy(pid_a, col["id"], source_role="primary", monitor_policy="on")
    # B never touched -- must still show the untouched, conservative default
    policy_b = db.get_collection_policy(pid_b, col["id"])
    assert policy_b["source_role"] == "unspecified" and policy_b["monitor_policy"] == "auto"
    assert reservoir.is_monitored(pid_b, col["id"]) is False

    policy_a = db.get_collection_policy(pid_a, col["id"])
    assert policy_a["source_role"] == "primary" and policy_a["monitor_policy"] == "on"


# ------------------------------------------------------------- policy changes never ingest anything (8-9)

def test_changing_monitor_policy_never_ingests_anything(s57_db):
    pid = db.create_project("S57 no-ingest monitor", brief="m")["id"]
    col = db.upsert_collection("channel", "UCni", "https://www.youtube.com/channel/UCni", "No Ingest")
    db.add_project_collections(pid, [col["id"]])
    before_candidates = db.connect().execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"]
    before_sources = db.connect().execute("SELECT COUNT(*) n FROM sources").fetchone()["n"]
    before_jobs = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]

    db.set_collection_policy(pid, col["id"], monitor_policy="on")
    db.set_collection_policy(pid, col["id"], monitor_policy="off")
    db.set_collection_policy(pid, col["id"], monitor_policy="auto")

    assert db.connect().execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"] == before_candidates
    assert db.connect().execute("SELECT COUNT(*) n FROM sources").fetchone()["n"] == before_sources
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == before_jobs


def test_changing_source_role_never_ingests_anything(s57_db):
    pid = db.create_project("S57 no-ingest role", brief="r")["id"]
    col = db.upsert_collection("channel", "UCnr", "https://www.youtube.com/channel/UCnr", "No Ingest Role")
    db.add_project_collections(pid, [col["id"]])
    before_candidates = db.connect().execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"]
    before_sources = db.connect().execute("SELECT COUNT(*) n FROM sources").fetchone()["n"]
    before_jobs = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]

    db.set_collection_policy(pid, col["id"], source_role="primary")
    db.set_collection_policy(pid, col["id"], source_role="secondary")
    db.set_collection_policy(pid, col["id"], source_role="unspecified")

    assert db.connect().execute("SELECT COUNT(*) n FROM candidates").fetchone()["n"] == before_candidates
    assert db.connect().execute("SELECT COUNT(*) n FROM sources").fetchone()["n"] == before_sources
    assert db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"] == before_jobs


# ------------------------------------------------------------- migration safety (10)

def test_existing_project_collections_rows_migrate_to_conservative_inactive_defaults(s57_db):
    """A row inserted the OLD way (add_project_collections, which never touches the new columns) must come back
    with the additive migration's defaults and read as NOT monitored -- no pre-existing attachment silently
    starts being watched just because this migration ran."""
    pid = db.create_project("S57 legacy row", brief="legacy")["id"]
    col = db.upsert_collection("channel", "UClegacy", "https://www.youtube.com/channel/UClegacy", "Legacy")
    db.add_project_collections(pid, [col["id"]])   # the pre-CR8 write path -- no source_role/monitor_policy args

    policy = db.get_collection_policy(pid, col["id"])
    assert policy is not None
    assert policy["source_role"] == "unspecified"
    assert policy["monitor_policy"] == "auto"
    assert reservoir.is_monitored(pid, col["id"]) is False


def test_is_monitored_false_for_a_relationship_that_was_never_attached(s57_db):
    pid = db.create_project("S57 unattached", brief="u")["id"]
    col = db.upsert_collection("channel", "UCunattached", "https://www.youtube.com/channel/UCunattached", "Unattached")
    # never db.add_project_collections -- no relationship row exists at all
    assert db.get_collection_policy(pid, col["id"]) is None
    assert reservoir.is_monitored(pid, col["id"]) is False


def test_set_collection_policy_rejects_invalid_values(s57_db):
    pid = db.create_project("S57 invalid", brief="i")["id"]
    col = db.upsert_collection("channel", "UCinvalid", "https://www.youtube.com/channel/UCinvalid", "Invalid")
    db.add_project_collections(pid, [col["id"]])
    with pytest.raises(ValueError):
        db.set_collection_policy(pid, col["id"], source_role="nope")
    with pytest.raises(ValueError):
        db.set_collection_policy(pid, col["id"], monitor_policy="nope")


def test_set_collection_policy_returns_none_for_a_relationship_that_does_not_exist(s57_db):
    pid = db.create_project("S57 no-relationship", brief="n")["id"]
    col = db.upsert_collection("channel", "UCnorel", "https://www.youtube.com/channel/UCnorel", "No Relationship")
    assert db.set_collection_policy(pid, col["id"], source_role="primary") is None


def _entries(n: int, *, start: int = 1, prefix: str = "vid") -> list[dict]:
    return [{"id": f"{prefix}{i}", "url": f"https://www.youtube.com/watch?v={prefix}{i}", "title": f"Video {i}",
             "duration": 100 + i, "view_count": 10 * i} for i in range(start, start + n)]


def test_explicit_single_collection_rescan_is_a_one_time_check_not_a_policy_change(s57_db):
    """Kyle's CR8a follow-up: the explicit single-collection rescan (`reservoir.rescan(pid, cid)`, the CLI's
    --collection flag) is deliberately ungated -- it runs even when this project's effective monitoring state
    for that collection is inactive, per CR8a's own design (a one-time "check this now", not "start watching
    this forever"). This proves the "check this now" half doesn't quietly become the "forever" half: running it
    must not touch source_role or monitor_policy at all, and a later bulk rescan_project() must still skip the
    collection exactly as before -- the explicit check has zero durable side effect on monitoring intent."""
    from neurosearch import candidates

    pid = db.create_project("S57 one-time check", brief="one-time")["id"]
    col = db.upsert_collection("channel", "UConetime", "https://www.youtube.com/channel/UConetime", "One-Time Check")
    db.add_project_collections(pid, [col["id"]])
    db.set_collection_policy(pid, col["id"], source_role="secondary", monitor_policy="auto")   # 2

    policy_before = db.get_collection_policy(pid, col["id"])
    assert reservoir.is_monitored(pid, col["id"]) is False   # 3/4: secondary + auto -> inactive

    calls = []
    def counting_enumerate(url: str):
        calls.append(url)
        return {"id": "UConetime", "title": "One-Time Check", "url": url}, _entries(3, prefix="onetime")

    result = reservoir.rescan(pid, col["id"], enumerate=counting_enumerate)   # 5

    assert len(calls) == 1   # 6: the collection was actually checked, exactly once
    assert result["changed"] is True and result["new"] == 3 and len(result["candidate_ids"]) == 3   # 7
    cand = db.connect().execute(
        "SELECT id FROM candidates WHERE id=?", (result["candidate_ids"][0],)).fetchone()
    assert cand is not None   # 7: reconciliation behaved normally -- a real Candidate Index row exists

    policy_after = db.get_collection_policy(pid, col["id"])
    assert policy_after["source_role"] == "secondary" == policy_before["source_role"]   # 8
    assert policy_after["monitor_policy"] == "auto" == policy_before["monitor_policy"]   # 9

    bulk_calls = []
    def counting_enumerate_bulk(url: str):
        bulk_calls.append(url)
        return {"id": "UConetime"}, _entries(3, prefix="onetime")
    later = reservoir.rescan_project(pid, enumerate=counting_enumerate_bulk)
    assert later == [] and bulk_calls == []   # 10: still skipped, zero enumerate() calls


def test_cli_collection_policy_show_and_set(s57_db):
    from typer.testing import CliRunner
    from neurosearch.cli import app
    pid = db.create_project("S57 cli", brief="cli")["id"]
    col = db.upsert_collection("channel", "UCcli", "https://www.youtube.com/channel/UCcli", "CLI Test")
    db.add_project_collections(pid, [col["id"]])
    runner = CliRunner()

    r0 = runner.invoke(app, ["project", "collection-policy", pid, col["id"], "--json"])
    assert r0.exit_code == 0, r0.output
    import json
    body0 = json.loads(r0.output)
    assert body0["source_role"] == "unspecified" and body0["effective_monitor_active"] is False

    r1 = runner.invoke(app, ["project", "collection-policy", pid, col["id"], "--role", "primary", "--json"])
    assert r1.exit_code == 0, r1.output
    body1 = json.loads(r1.output)
    assert body1["source_role"] == "primary" and body1["effective_monitor_active"] is True

    r2 = runner.invoke(app, ["project", "collection-policy", pid, "nope-not-attached"])
    assert r2.exit_code != 0
