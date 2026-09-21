"""S80 — a Claim whose every supporting finding was dismissed comes back for a decision.

THE DEFECT THIS CLOSES, which predates all of today's review UI. `claim_evidence` is keyed by SOURCE, and
`claims.assess` filters only on whether a source revision moved. Nothing anywhere consults a NOTE's status. So
dismissing a finding removed it from chat, from exports and from future harvesting -- and left every Claim
built on it standing at unchanged strength with no sign its evidence had been rejected. `retire.py` models
exactly this loss, but only for sources LEAVING a project; the ordinary Dismiss button never had an equivalent.

That is the worst shape this can take: the user acts, believes they have acted, and the conclusion drawn from
the thing they rejected quietly survives. Warning them in a subtitle was not a fix.
"""
from __future__ import annotations
import os
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest
from neurosearch import claims, db, review_queue
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _setup(statuses):
    """One proposed Claim harvested from the first note, with the rest folded in as supporting evidence."""
    p = db.create_project("p", "brief")
    nids = [db.add_project_note(p["id"], f"finding {i}", [], status=st, importance=3)["id"]
            for i, st in enumerate(statuses)]
    c = claims.add_claim(p["id"], "multiples cluster around 3x SDE", claim_type="empirical",
                         origin="finding", origin_note_id=nids[0], status="proposed")
    with db.tx() as conn:
        for nid in nids[1:]:
            conn.execute("INSERT OR IGNORE INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (c["id"], nid))
    return p["id"], c["id"], nids


def _reasons(pid, cid):
    q = review_queue.build(pid, limit=25)
    row = next((x for x in q["queue"] if x["claim_id"] == cid), None)
    return row["reasons"] if row else []


def test_a_claim_whose_every_finding_was_dismissed_is_flagged():
    pid, cid, _ = _setup(["dismissed", "dismissed"])
    assert "evidence_dismissed" in _reasons(pid, cid)


def test_one_surviving_finding_is_enough_to_keep_it_supported():
    """The defensible line, and retire.py's own: all of them dismissed, not any of them."""
    pid, cid, _ = _setup(["dismissed", "approved"])
    assert "evidence_dismissed" not in _reasons(pid, cid)


def test_it_counts_the_origin_finding_not_only_folded_in_evidence():
    pid, cid, _ = _setup(["dismissed"])
    assert "evidence_dismissed" in _reasons(pid, cid), "origin_note_id alone must be enough to catch it"


def test_a_suggested_finding_still_counts_as_support():
    """Suggested is undecided, not rejected. Only an explicit dismissal removes support."""
    pid, cid, _ = _setup(["suggested", "suggested"])
    assert "evidence_dismissed" not in _reasons(pid, cid)


def test_dismissing_through_the_normal_door_is_what_triggers_it():
    """The whole point: the ordinary Dismiss button, not a special path."""
    pid, cid, nids = _setup(["approved", "approved"])
    assert "evidence_dismissed" not in _reasons(pid, cid)
    for nid in nids:
        db.set_note_status(nid, "dismissed")
    assert "evidence_dismissed" in _reasons(pid, cid)


def test_it_leads_the_reason_order_and_is_never_capped():
    assert review_queue.REASON_ORDER[0] == "evidence_dismissed"
    pid, cid, _ = _setup(["dismissed"])
    q = review_queue.build(pid, limit=1)
    assert any(x["claim_id"] == cid for x in q["queue"]), "a limit of 1 must not be able to hide it"


# ---------------------------------------------------------------- accepted Claims (the case I first deferred)

def test_an_accepted_claim_on_dismissed_evidence_surfaces_too():
    """The clearest possible 'needs a human': the user stood behind this, then rejected everything under it.
    assess() will never notice -- it reads source revisions, not note status -- so this queue is the only
    place the contradiction can become visible."""
    pid, cid, nids = _setup(["approved", "approved"])
    claims.set_status(cid, "accepted") if hasattr(claims, "set_status") else \
        db.connect().execute("UPDATE project_claims SET status='accepted' WHERE id=?", (cid,)) or db.connect().commit()
    assert _reasons(pid, cid) == [], "an accepted Claim with live evidence has no business in the queue"
    for nid in nids:
        db.set_note_status(nid, "dismissed")
    q = review_queue.build(pid, limit=25)
    row = next((x for x in q["queue"] if x["claim_id"] == cid), None)
    assert row and "evidence_dismissed" in row["reasons"] and row["status"] == "accepted"
    assert q["counts"]["accepted_on_dismissed_evidence"] == 1


def test_an_accepted_claim_with_support_stays_out():
    """Accepted Claims enter for this ONE reason and no other -- the queue's contract for them is narrow."""
    pid, cid, nids = _setup(["approved", "approved"])
    db.connect().execute("UPDATE project_claims SET status='accepted' WHERE id=?", (cid,)); db.connect().commit()
    db.set_note_status(nids[0], "dismissed")            # one of two -- still supported
    assert _reasons(pid, cid) == []
