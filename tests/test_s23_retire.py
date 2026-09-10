"""S23 — retiring a direction the project is no longer pursuing (0.62.9). (Sorts after test_s22.)

Kyle: *"I want to bulk remove some content that we are no longer pursuing in the large project but I dont know how.
we need to essentially get rid of ALL CPA and laundromat specific content."*

Measured on his 882-source project before any of this was written, and the measurement changed the design twice.

**A keyword sweep is not safe.** Matching "cpa"/"accounting firm" selects 43 sources, and among them are *How To
Acquire Your First Business With $0 (FREE COURSE)*, *Best Boring Businesses to Buy in 2026*, his own
*Gio Kyle and Zach first coaching call* and his own acquisition notes — because general acquisition training uses
accounting firms as an example industry. So retirement is by CHANNEL or explicit source id, never by keyword:

    Laundromat Resource       25 sources   22.6 h   1,059 findings
    Jason On Firms Podcast     7 sources    4.6 h      74 findings
    LYFE Accounting           13 sources    6.5 h     448 findings   <- KEPT: general small-business tax
    Sherman - My CPA Coach    16 sources    2.9 h     429 findings   <- KEPT: general small-business tax
    Ben Kelly                 38 sources    8.9 h     975 findings   <- KEPT: core training

**Removing sources does not remove what was derived from them.** `db.remove_project_sources` is a membership marker
by design (0.34.2), so on his two sets it would have left **1,775 findings** attached to sources no longer in the
project and **2,509 Claims with no evidence inside it at all**. Retiring is therefore three coordinated steps.

Nothing is deleted: sources keep their place in the global library, findings are dismissed, Claims are rejected
with the reason recorded, and `claim_evidence` rows are untouched so the decision can be explained and undone.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_ret_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, retire  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


@pytest.fixture(autouse=True)
def _no_jobs_left_behind():
    yield
    try:
        with db.tx() as conn:
            conn.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('queued','running')")
    except Exception:  # noqa: BLE001
        pass


def _src(sid, title, channel, dur=3600.0):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, channel, status, duration, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (sid, "youtube", sid, f"https://y/{sid}", title, channel, "ready", dur, 1.0, 1.0))
    return sid


def _note(pid, sid, content, status="approved"):
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO project_notes (project_id, source_id, content, citations, created_at, status) "
                           "VALUES (?,?,?,?,?,?)", (pid, sid, content, "[]", 1.0, status))
        return cur.lastrowid


def _claim(pid, cid, text, evidence_sources):
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, topic, status, strength, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?)", (cid, pid, text, "t", "proposed", "weak", 1.0, 1.0))
        for i, s in enumerate(evidence_sources):
            conn.execute("INSERT INTO claim_evidence (claim_id, source_id, locator, relation, excerpt, created_at) "
                         "VALUES (?,?,?,?,?,?)", (cid, s, "0:00", "SUPPORTS", "an excerpt", 1.0))


def _project():
    p = db.create_project("acq", brief="buying businesses")
    laundry = [_src(f"L{i}", f"Laundromat episode {i}", "Laundromat Resource") for i in range(3)]
    firms = [_src(f"F{i}", f"Accounting firm episode {i}", "Jason On Firms") for i in range(2)]
    keep = [_src("K0", "How To Acquire Your First Business", "Ben Kelly"),
            _src("K1", "15 Biggest Tax Write Offs", "Sherman - My CPA Coach")]
    db.add_project_sources(p["id"], laundry + firms + keep)
    for s in laundry + firms + keep:
        _note(p["id"], s, f"a finding from {s}")
    _claim(p["id"], "c_laundry", "laundromats are cash businesses", ["L0", "L1"])       # dies with the direction
    _claim(p["id"], "c_mixed", "cash businesses need controls", ["L0", "K0"])           # survives, partly affected
    _claim(p["id"], "c_keep", "SBA loans need a down payment", ["K0"])                  # untouched
    return p, laundry, firms, keep


# ------------------------------------------------------------------ the menu

def test_the_menu_says_what_each_channel_contributed(fresh):
    p, *_ = _project()
    chans = {c["channel"]: c for c in retire.channels(p["id"])}
    assert chans["Laundromat Resource"]["sources"] == 3 and chans["Laundromat Resource"]["findings"] == 3
    assert chans["Ben Kelly"]["sources"] == 1
    assert chans["Laundromat Resource"]["hours"] == 3.0


# ------------------------------------------------------------------ the preview

def test_the_preview_counts_the_claims_that_would_lose_everything(fresh):
    """The number that makes it an informed decision. On Kyle's laundromat set it is 1,664."""
    p, *_ = _project()
    pv = retire.preview(p["id"], channels=["Laundromat Resource"])
    assert pv["sources"] == 3 and pv["findings"] == 3
    assert pv["claims_losing_all_evidence"] == 1                 # c_laundry
    assert pv["claims_partly_affected"] == 1                     # c_mixed keeps K0
    assert "reversible" in pv and "1,664" not in pv["note"]


def test_the_preview_changes_nothing(fresh):
    p, laundry, *_ = _project()
    before = set(db.project_source_ids(p["id"], ready_only=False))
    retire.preview(p["id"], channels=["Laundromat Resource"])
    assert set(db.project_source_ids(p["id"], ready_only=False)) == before


def test_selecting_a_channel_never_selects_a_neighbour(fresh):
    """The measured reason this is channel-based: a keyword sweep on "accounting firm" would have taken Ben Kelly's
    core training and Kyle's own coaching notes with it."""
    p, *_ = _project()
    pv = retire.preview(p["id"], channels=["Jason On Firms"])
    assert set(pv["source_ids"]) == {"F0", "F1"}


def test_an_empty_selection_is_a_no_op_not_an_error(fresh):
    p, *_ = _project()
    assert retire.preview(p["id"])["sources"] == 0
    assert retire.apply(p["id"])["applied"] is False


def test_a_whole_project_selection_is_refused_rather_than_truncated(fresh, monkeypatch):
    p, *_ = _project()
    monkeypatch.setattr(retire, "MAX_SOURCES", 2)
    with pytest.raises(ValueError):
        retire.preview(p["id"], channels=["Laundromat Resource"])


# ------------------------------------------------------------------ applying it

def test_the_three_steps_happen_together(fresh):
    p, laundry, firms, keep = _project()
    out = retire.apply(p["id"], channels=["Laundromat Resource"], reason="laundromats are out")
    assert out["applied"] and out["sources_removed"] == 3 and out["findings_dismissed"] == 3
    assert out["claims_rejected"] == 1
    left = set(db.project_source_ids(p["id"], ready_only=False))
    assert not (set(laundry) & left) and set(keep) <= left
    rows = {r["id"]: r["status"] for r in db.connect().execute("SELECT id, status FROM project_claims")}
    assert rows["c_laundry"] == "rejected" and rows["c_mixed"] == "proposed" and rows["c_keep"] == "proposed"


def test_nothing_is_deleted_anywhere(fresh):
    p, laundry, *_ = _project()
    retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    # the sources still exist globally: another project can still use them
    assert db.get_source("L0") and db.get_source("L0")["status"] == "ready"
    # the findings are dismissed, not gone
    n = db.connect().execute("SELECT COUNT(*) n FROM project_notes WHERE source_id='L0'").fetchone()["n"]
    assert n == 1
    assert db.connect().execute("SELECT status FROM project_notes WHERE source_id='L0'").fetchone()["status"] == "dismissed"
    # and the evidence rows are untouched, so the rejection can be explained and undone
    assert db.connect().execute("SELECT COUNT(*) n FROM claim_evidence WHERE claim_id='c_laundry'").fetchone()["n"] == 2


def test_the_reason_is_recorded_on_the_claim_and_as_a_project_decision(fresh):
    p, *_ = _project()
    retire.apply(p["id"], channels=["Laundromat Resource"], reason="laundromats are out")
    app = db.connect().execute("SELECT application FROM project_claims WHERE id='c_laundry'").fetchone()["application"]
    assert "retired: laundromats are out" == app
    facts = [f for f in db.list_facts(p["id"]) if f["kind"] == "rejected"]
    assert facts and "laundromats are out" in facts[0]["content"] and "Laundromat Resource" in facts[0]["content"]


def test_a_retired_source_cannot_drift_back_in(fresh):
    """0.34.2's exclusion marker is the mechanism, so a tag match or a retried ingest cannot resurrect it."""
    p, laundry, *_ = _project()
    retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    row = db.connect().execute("SELECT excluded FROM project_sources WHERE project_id=? AND source_id='L0'",
                               (p["id"],)).fetchone()
    assert row["excluded"] == 1


def test_it_can_retire_by_explicit_source_too(fresh):
    p, *_ = _project()
    out = retire.apply(p["id"], source_ids=["F0"], reason="one specific deal")
    assert out["sources_removed"] == 1 and "F0" not in set(db.project_source_ids(p["id"], ready_only=False))


def test_findings_can_be_kept_if_the_user_wants_them(fresh):
    p, *_ = _project()
    out = retire.apply(p["id"], channels=["Laundromat Resource"], dismiss_findings=False, reject_claims=False)
    assert out["findings_dismissed"] == 0 and out["claims_rejected"] == 0
    assert db.connect().execute("SELECT status FROM project_notes WHERE source_id='L0'").fetchone()["status"] == "approved"


def test_a_second_run_is_idempotent(fresh):
    p, *_ = _project()
    retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    again = retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    assert again["sources_removed"] == 0 or again["findings_dismissed"] == 0
    assert again["claims_rejected"] == 0


def test_the_decision_shows_on_the_next_research_read(fresh):
    """It is a person's decision, not background churn, so 0.62.8's rule applies."""
    from neurosearch import research_view
    p, *_ = _project()
    research_view.overview(p["id"])
    out = retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    assert research_view.overview(p["id"])["as_of_current"] is True
    assert "refresh_job" in out


def test_another_project_keeps_its_own_claims(fresh):
    """`claim_evidence` is global; a Claim belonging to another project is not ours to reject."""
    p, *_ = _project()
    other = db.create_project("other", brief="b")
    db.add_project_sources(other["id"], ["L0"])
    _claim(other["id"], "o1", "laundromats are fine actually", ["L0"])
    retire.apply(p["id"], channels=["Laundromat Resource"], reason="out")
    assert db.connect().execute("SELECT status FROM project_claims WHERE id='o1'").fetchone()["status"] == "proposed"
    assert "L0" in set(db.project_source_ids(other["id"], ready_only=False))
