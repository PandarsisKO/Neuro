"""P11 EA-9 — a collaborator's explicit commit that restricted state prevents applying (Kyle, 2026-09-22).

Status is where a fact stands in the project; explicitness is what the person did. When Gio explicitly decides
something but current state of that kind exists that her grant cannot see, the decision is HELD for the owner:
status=proposed, explicitness and her words unchanged, an owner-only reason recorded — and nothing in any external
response hints that hidden state exists. Accepting it changes only its status."""
from __future__ import annotations

import json
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, db, facts, jobs, ledger
from neurosearch.config import settings

HIDDEN = "Walk-away price is 2.1M"
LEAKS = ("can't see", "cannot see", "does not include", "hidden", "held for owner review", "may conflict", HIDDEN, "2.1M", "review_reason")
LOCAL = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir(); (d / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    monkeypatch.setattr(jobs, "enqueue_suggestions", lambda *a, **k: None)
    yield
    db._local.conn = None


@pytest.fixture
def w(client):
    p = client.post("/api/projects", json={"name": "Business Acquisition"}, headers=LOCAL).json()["id"]
    client.post(f"/api/projects/{p}/facts", json={"kind": "decision", "content": HIDDEN}, headers=LOCAL)   # Kyle's, private by default
    access.create_actor("Gio", actor_id="gio")
    c = access.create_client("Gio's ChatGPT")["id"]
    _, s = access.issue_credential("gio", c)
    access.grant(p, "gio", "contribute")
    return {"p": p, "s": s, "client": c}


def ext(client, w, op, **a):
    r = client.post(f"/api/ext/v1/{op}", json={"project_id": w["p"], **a}, headers={"Authorization": f"Bearer {w['s']}"})
    return r.status_code, r.json()


def _decide_both_ways(client, w):
    _, a = ext(client, w, "sync_project_state", changes=[
        {"op": "record", "kind": "decision", "content": "Offer 1.9M", "explicitness": "explicit", "user_text": "Let's offer 1.9M.",
         "client_request_id": "gio-dec-0001"}])
    _, b = ext(client, w, "sync_conversation_to_project", client_request_id="gio-save-0001",
               project_selection={"basis": "user_named", "user_text": "Save this to Business Acquisition."},
               state=[{"op": "record", "kind": "decision", "content": "Ask for a 12-month transition", "user_text": "We want 12 months of transition."},
                      {"op": "propose", "kind": "concern", "content": "Seller may walk over the transition length"}])
    return a, b


def test_1_held_decision_is_proposed_and_still_explicit(client, w):
    _decide_both_ways(client, w)
    rows = {f["content"]: f for f in db.list_facts(w["p"], include_history=True)}
    for content, words in (("Offer 1.9M", "Let's offer 1.9M."), ("Ask for a 12-month transition", "We want 12 months of transition.")):
        f = rows[content]
        assert (f["status"], f["explicitness"], f["actor_id"], f["external_client_id"], f["user_text"]) == \
               ("proposed", "explicit", "gio", w["client"], words)
        assert f["review_reason"] and "collaborator" in f["review_reason"]
    assert [f["content"] for f in facts.current_position(w["p"])] == [HIDDEN]          # nothing became a second current truth


def test_2_no_external_response_hints_that_hidden_state_exists(client, w):
    a, b = _decide_both_ways(client, w)
    applied = a["data"]["applied"][0]
    assert applied["status"] == "proposed" and applied["fact"]["explicitness"] == "explicit" and applied["note"] == "held for review"
    assert b["data"]["summary"] == "Saved to Business Acquisition: 1 project change for review, 1 suggestion to review"
    assert b["data"]["needs_attention"] == []
    reads = [ext(client, w, "open_project")[1], ext(client, w, "get_project_changes", since_cursor=0)[1],
             ext(client, w, "consult_project", question="What price are we offering?")[1],
             ext(client, w, "search_project", query="price offer walk-away")[1]]
    for payload in (a, b, *reads):
        text = json.dumps(payload)
        for leak in LEAKS:
            assert leak not in text, leak


def test_3_owner_sees_the_reconciliation_reason(client, w):
    _decide_both_ways(client, w)
    review = client.get(f"/api/projects/{w['p']}/facts/review", headers=LOCAL).json()["facts"]
    held = {f["content"]: f for f in review}
    assert held["Offer 1.9M"]["review_reason"].startswith("held for owner review") and held["Offer 1.9M"]["actor_name"] == "Gio"
    assert held["Offer 1.9M"]["client_label"] == "Gio's ChatGPT" and held["Offer 1.9M"]["user_text"] == "Let's offer 1.9M."
    assert client.get(f"/api/projects/{w['p']}/facts/review").status_code == 401                    # owner only
    assert client.get(f"/api/projects/{w['p']}/facts/review", headers={"Authorization": f"Bearer {w['s']}"}).status_code == 401


def test_4_accepting_keeps_gio_as_author_and_explicit_provenance(client, w):
    _decide_both_ways(client, w)
    fid = next(f["id"] for f in db.list_facts(w["p"], include_history=True) if f["content"] == "Offer 1.9M")
    r = client.post(f"/api/projects/{w['p']}/facts/{fid}/review", json={"accept": True}, headers=LOCAL).json()
    assert (r["status"], r["explicitness"], r["actor_id"], r["external_client_id"], r["user_text"]) == \
           ("active", "explicit", "gio", w["client"], "Let's offer 1.9M.")
    ev = [e for e in ledger.events(w["p"], object_type="fact", object_id=str(fid))["events"] if e["event_type"] == "fact_proposal_accepted"][0]
    assert ev["actor_id"] == "kyle" and ev["after"]["author"] == "gio" and ev["after"]["explicitness"] == "explicit"
    assert ev["materiality"] == "material"
    assert "Offer 1.9M" in [f["content"] for f in facts.current_position(w["p"])]


def test_5_an_inferred_proposal_stays_distinguishable(client, w):
    _decide_both_ways(client, w)
    rows = {f["content"]: f for f in db.list_facts(w["p"], include_history=True)}
    inferred = rows["Seller may walk over the transition length"]
    assert (inferred["status"], inferred["explicitness"], inferred["review_reason"]) == ("proposed", "inferred", None)
    review = {f["content"]: f for f in client.get(f"/api/projects/{w['p']}/facts/review", headers=LOCAL).json()["facts"]}
    assert review["Seller may walk over the transition length"]["explicitness"] == "inferred"
    assert review["Ask for a 12-month transition"]["explicitness"] == "explicit"
    client.post(f"/api/projects/{w['p']}/facts/{inferred['id']}/review", json={"accept": True}, headers=LOCAL)
    assert facts.get(inferred["id"])["explicitness"] == "inferred"          # acceptance does not rewrite provenance either way


def test_without_hidden_state_the_same_commit_applies_directly(client, w):
    access.set_grant_classes(w["p"], "gio", ["standard", "restricted"])      # now Gio can see Kyle's decision
    _, a = ext(client, w, "sync_project_state", base_revision=ext(client, w, "open_project")[1]["ledger_cursor"], changes=[
        {"op": "record", "kind": "decision", "content": "Offer 1.9M", "user_text": "Let's offer 1.9M.", "client_request_id": "gio-dec-0002"}])
    assert a["data"]["applied"][0]["status"] == "active" and "note" not in a["data"]["applied"][0]
