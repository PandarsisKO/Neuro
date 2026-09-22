"""P11 EA-2 — project change ledger + durable user state (EXTERNAL-AI-ACCESS-MISSION.md §44–§51, §60;
docs/P11-EXECUTION-PLAN-2026-09-22.md §5, §7 and §10 row 4).

The gate: 10% → reaffirm 10% → 7.5%; the 56-reassessment case writes only what changed; exact no-op suppression;
idempotent retry; optimistic concurrency; attribution never invents a person (Kyle's ruling 2); the ledger is
written only from its declared writers; nothing is classified under the write lock."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, claims, db, facts, jobs, knowledge, ledger
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _ev(pid, since=0, **kw):
    return ledger.events(pid, since=since, **kw)


def _src(i, plat="youtube"):
    return db.upsert_source(platform=plat, external_id=f"s{i}", url=f"https://www.youtube.com/watch?v={i:011d}",
                            title=f"s{i}", channel=f"ch{i}", status="ready")["id"]


# ------------------------------------------------------------------ durable state: 10 → reaffirm → 7.5

def test_ten_reaffirm_seven_five():
    p = db.create_project("Business acquisition")["id"]
    access.create_actor("Gio", actor_id="gio")
    client = access.create_client("Gio's ChatGPT")["id"]
    with ledger.acting("gio", client_id=client, request_id="r1"):
        a = facts.record(p, "decision", "Seller note stays at 10%", disclosure_class="standard", client_request_id="req-000001")
    assert a["status"] == "active" and a["actor_id"] == "gio" and a["external_client_id"] == client
    with ledger.acting("gio", client_id=client, request_id="r2"):
        facts.reaffirm(a["id"], rationale="seller applied new pressure; we hold", client_request_id="req-000002")
    assert facts.get(a["id"])["status"] == "active"                                    # row untouched
    assert db.connect().execute("SELECT COUNT(*) FROM project_facts WHERE project_id=?", (p,)).fetchone()[0] == 1
    with ledger.acting("gio", client_id=client, request_id="r3"):
        b = facts.supersede(a["id"], "Seller note 7.5%", rationale="traded for a longer transition", client_request_id="req-000003")
    assert facts.get(a["id"])["status"] == "superseded" and b["supersedes_fact_id"] == a["id"]
    assert [f["content"] for f in facts.current_position(p)] == ["Seller note 7.5%"]
    assert [f["content"] for f in db.list_facts(p)] == ["Seller note 7.5%"]            # the planner sees the current position only
    assert [f["id"] for f in facts.history(b["id"])] == [a["id"], b["id"]]
    chrono = [(e["event_type"], e["actor_id"], e["external_client_id"]) for e in
              sorted(_ev(p, object_type="fact", object_id=str(a["id"]))["events"], key=lambda e: e["id"])]
    assert chrono == [("decision_recorded", "gio", client), ("decision_reaffirmed", "gio", client), ("decision_changed", "gio", client)]
    changed = [e for e in _ev(p)["events"] if e["event_type"] == "decision_changed"][0]
    assert changed["before"]["content"] == "Seller note stays at 10%" and changed["after"]["content"] == "Seller note 7.5%"
    assert changed["decision_impact"]["kind"] == "decision" and changed["materiality"] == "material"


def test_idempotent_retries_write_nothing_twice():
    p = db.create_project("p")["id"]
    with ledger.acting("kyle", client_id="c1"):
        a = facts.record(p, "decision", "stay at 10%", client_request_id="same-request-1")
        again = facts.record(p, "decision", "stay at 10%", client_request_id="same-request-1")
        facts.reaffirm(a["id"], client_request_id="reaff-request-1")
        facts.reaffirm(a["id"], client_request_id="reaff-request-1")
        b = facts.supersede(a["id"], "7.5%", client_request_id="sup-request-1")
        b2 = facts.supersede(a["id"], "7.5%", client_request_id="sup-request-1")
    assert again["id"] == a["id"] and again.get("idempotent_replay")
    assert b2["id"] == b["id"] and b2.get("idempotent_replay")
    types = [e["event_type"] for e in _ev(p)["events"]]
    assert types.count("decision_recorded") == 1 and types.count("decision_reaffirmed") == 1 and types.count("decision_changed") == 1


def test_concurrent_collaborators_conflict_instead_of_last_writer_wins():
    p = db.create_project("p")["id"]
    a = facts.record(p, "decision", "stay at 10%", disclosure_class="standard")
    other = facts.record(p, "constraint", "close by Q1")
    seen_by_both = ledger.cursor(p)
    with ledger.acting("kyle"):
        facts.supersede(a["id"], "8%", base_cursor=seen_by_both)
    with ledger.acting("gio"), pytest.raises(facts.Conflict) as e:
        facts.supersede(a["id"], "7.5%", base_cursor=seen_by_both)
    assert e.value.current["status"] == "superseded" and e.value.proposed["content"] == "7.5%"
    assert [f["content"] for f in facts.current_position(p) if f["kind"] == "decision"] == ["8%"]
    # a base that predates changes to OTHER state is not a conflict for this fact
    facts.reaffirm(other["id"], base_cursor=seen_by_both)
    # but a fact created after the client's base is one it never saw
    late = facts.record(p, "constraint", "added later")
    with pytest.raises(facts.Conflict):
        facts.reaffirm(late["id"], base_cursor=seen_by_both)


def test_explicit_inferred_personal_and_acceptance_rules():
    p = db.create_project("p")["id"]
    inferred = facts.record(p, "preference", "maybe be more flexible", explicitness="inferred")
    personal = facts.record(p, "preference", "I personally prefer 10%", scope="personal")
    with pytest.raises(ValueError):
        facts.record(p, "decision", "all three", explicitness="accepted_recommendation")   # no single referent
    ok = facts.record(p, "decision", "stay at 10%", explicitness="accepted_recommendation",
                      referent="Do you want to remain at 10%?")
    assert inferred["status"] == "proposed" and personal["scope"] == "personal" and ok["status"] == "active"
    assert [f["content"] for f in facts.current_position(p)] == ["stay at 10%"]
    facts.set_proposal(inferred["id"], accept=True)
    assert facts.get(inferred["id"])["status"] == "active"
    types = [e["event_type"] for e in sorted(_ev(p)["events"], key=lambda e: e["id"])]
    assert types[:3] == ["fact_proposed", "preference_recorded", "decision_recorded"]


def test_local_fact_writes_are_kyle_and_closed_until_classified(client):
    H = {"Authorization": "Bearer t0k"}
    pid = client.post("/api/projects", json={"name": "Shared"}, headers=H).json()["id"]
    client.post(f"/api/projects/{pid}/facts", json={"kind": "decision", "content": "stay at 10%"}, headers=H)
    e = [x for x in _ev(pid)["events"] if x["object_type"] == "fact"][0]
    assert (e["actor_id"], e["local_surface"], e["external_client_id"]) == ("kyle", "api", None)
    assert e["disclosure_floor"] == ["restricted"]
    assert _ev(pid, classes=["standard"])["summary"]["withheld"] >= 1


# ------------------------------------------------------------------ §46/§48: only what changed

def test_fifty_six_reassessed_two_changed_one_affects_the_plan():
    p = db.create_project("p")["id"]
    ids = []
    for i in range(56):
        c = claims.add_claim(p, f"claim number {i} about multiples", origin="user", status="accepted")["id"]
        claims.add_evidence(c, _src(1000 + i), excerpt=f"first account of claim {i}")
        ids.append(c)
    claims.assess_project(p)                                     # establishes every verdict
    # the plan cites the finding behind ids[0]
    note = db.add_project_note(p, "finding behind claim 0", [], source_id=_src(5000))["id"]
    with db.tx() as conn:
        conn.execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (ids[0], note))
    db.save_plan(p, {"summary": "x", "decisions": [{"text": "d", "evidence": ["F1"]}], "_evidence": {"F1": {"note_id": note}}},
                 {"notes": 1})
    for c in ids[:2]:
        for j in range(3):
            claims.add_evidence(c, _src(2000 + j + (10 if c == ids[1] else 0)), excerpt=f"independent account {j} with different words {c[:4]}")
    mark = ledger.cursor(p)
    t0 = __import__("time").perf_counter()
    with ledger.acting("system", originating_actor_id="kyle", originating_request_id="nightly-1"):
        assert claims.assess_project(p) == 56
    assert __import__("time").perf_counter() - t0 < db.WRITE_HOLD_WARN_S * 5
    page = _ev(p, since=mark)
    assert page["summary"]["reassessed"] == 56
    assert page["summary"]["changed"] == 2
    assert page["summary"]["decision_affecting"] == 1
    assert {e["object_id"] for e in page["events"]} == set(ids[:2])
    top = page["events"][0]
    assert top["object_id"] == ids[0] and top["decision_impact"]["kind"] == "plan"      # impact-ordered
    for e in page["events"]:
        assert e["actor_id"] == "system" and e["originating_actor_id"] == "kyle"
        assert e["originating_request_id"] == "nightly-1" and e["external_client_id"] is None
    # a second identical pass: nothing changed, no change rows
    mark2 = ledger.cursor(p)
    claims.assess_project(p)
    again = _ev(p, since=mark2)
    assert again["summary"]["changed"] == 0 and again["summary"]["reassessed"] == 56


def test_membership_and_status_no_ops_are_silent():
    p = db.create_project("p")["id"]
    a, b = _src(1), _src(2)
    db.add_project_sources(p, [a, b])
    db.add_project_sources(p, [a, b])                       # same membership: nothing
    db.remove_project_sources(p, [b])
    db.remove_project_sources(p, [b])                       # already removed: nothing
    db.add_project_sources(p, [b])                          # an explicit add lifts the removal
    types = [e["event_type"] for e in sorted(_ev(p)["events"], key=lambda e: e["id"])]
    assert types == ["source_attached", "source_attached", "source_removed", "source_attached"]
    c = claims.add_claim(p, "x", origin="user")["id"]
    claims.set_status(c, "accepted"); claims.set_status(c, "accepted")
    assert [e["event_type"] for e in _ev(p)["events"]].count("claim_status_changed") == 1


def test_source_becoming_ready_is_ledgered_for_every_project_that_holds_it():
    p1, p2 = db.create_project("a")["id"], db.create_project("b")["id"]
    s = db.upsert_source(platform="youtube", external_id="z", url="https://www.youtube.com/watch?v=zzzzzzzzzzz", title="z", status="pending")["id"]
    db.add_project_sources(p1, [s]); db.add_project_sources(p2, [s])
    db.upsert_source(platform="youtube", external_id="z", status="ready")
    db.upsert_source(platform="youtube", external_id="z", status="ready")
    for p in (p1, p2):
        assert [e["event_type"] for e in _ev(p)["events"]].count("source_ready") == 1


def test_rollback_leaves_no_event():
    p = db.create_project("p")["id"]
    with pytest.raises(RuntimeError):
        with db.tx() as conn:
            ledger.record(conn, p, event_type="fact_recorded", object_type="fact", object_id=1, before=None, after={"x": 1}, floor={"standard"})
            raise RuntimeError("boom")
    assert ledger.cursor(p) == 0


def test_classification_happens_after_commit_not_under_the_lock(monkeypatch):
    p = db.create_project("p")["id"]
    seen = []
    real = ledger.classify_pending

    def spy(limit=500):
        seen.append(db.connect().in_transaction)
        return real(limit)
    monkeypatch.setattr(ledger, "classify_pending", spy)
    facts.record(p, "decision", "x", disclosure_class="standard")
    assert seen and seen[0] is False
    e = _ev(p)["events"][0]
    assert e["materiality"] == "material"


def test_payloads_are_bounded():
    p = db.create_project("p")["id"]
    facts.record(p, "context", "y" * 50_000, disclosure_class="standard")
    row = db.connect().execute("SELECT after FROM project_change_events WHERE project_id=?", (p,)).fetchone()
    assert len(row["after"].encode()) <= ledger.MAX_PAYLOAD_BYTES


# ------------------------------------------------------------------ disclosure floor on the change stream

def test_floor_filter_is_in_the_query_and_cursor_passes_hidden_events():
    p = db.create_project("p")["id"]
    facts.record(p, "decision", "public decision", disclosure_class="standard")
    facts.record(p, "decision", "the tax position", disclosure_class="tax")
    facts.record(p, "decision", "another public one", disclosure_class="standard")
    page = _ev(p, classes=["standard"])
    assert [e["after"]["content"] for e in sorted(page["events"], key=lambda e: e["id"])] == ["public decision", "another public one"]
    assert page["summary"]["withheld"] == 1
    assert "tax position" not in str(page)
    nxt = _ev(p, since=page["next_cursor"], classes=["standard"])
    assert nxt["events"] == [] and nxt["summary"]["withheld"] == 0      # the cursor moved past what it may not see
    both = _ev(p, classes=["standard", "tax"])
    assert both["summary"]["changed"] == 3


def test_paging_never_skips_or_repeats():
    p = db.create_project("p")["id"]
    for i in range(7):
        facts.record(p, "context", f"fact {i}", disclosure_class="standard")
    seen, cur = [], 0
    while True:
        page = ledger.events(p, since=cur, classes=["standard"], limit=3)
        seen += [e["after"]["content"] for e in sorted(page["events"], key=lambda e: e["id"])]
        cur = page["next_cursor"]
        if not page["more"]:
            break
    assert seen == [f"fact {i}" for i in range(7)]


def test_derived_objects_carry_their_provenance_floor():
    p = db.create_project("p")["id"]
    ig = _src(1, "instagram")
    c = claims.add_claim(p, "from instagram", origin="user")["id"]
    claims.add_evidence(c, ig)
    knowledge._upsert_tension(p, "CONTRADICTION", c, "contradicts the public view", {}, "high")
    evs = _ev(p)["events"]
    assert {e["object_type"] for e in evs} >= {"claim", "claim_evidence", "tension"}
    for e in evs:
        assert "restricted" in e["disclosure_floor"], e["event_type"]
    std = _ev(p, classes=["standard"])
    assert std["events"] == [] and std["summary"]["withheld"] == len(evs)


# ------------------------------------------------------------------ attribution (Kyle's ruling 2)

def test_jobs_run_as_system_with_their_cause(monkeypatch):
    p = db.create_project("p")["id"]
    with ledger.acting("kyle", surface="ui", request_id="req:abc"):
        j = db.create_job("noop_p11", {"project_id": p})
    row = db.connect().execute("SELECT origin_actor_id, origin_request_id FROM jobs WHERE id=?", (j["id"],)).fetchone()
    assert (row["origin_actor_id"], row["origin_request_id"]) == ("kyle", "req:abc")
    monkeypatch.setattr(jobs, "run_job", lambda job: db.add_fact(p, "context", "written by a job") and {})
    jobs.execute({**db.get_job(j["id"]), "run_id": None})
    e = [x for x in _ev(p)["events"] if x["object_type"] == "fact"][0]
    assert (e["actor_id"], e["originating_actor_id"], e["originating_request_id"]) == ("system", "kyle", "req:abc")
    assert db.connect().execute("SELECT actor_id FROM project_facts WHERE project_id=?", (p,)).fetchone()[0] == "system"


def test_unbound_work_is_system_never_a_person():
    p = db.create_project("p")["id"]
    db.add_fact(p, "context", "nobody bound")
    assert _ev(p)["events"][0]["actor_id"] == "system"


def test_nightly_is_system_even_when_kyle_starts_it(monkeypatch):
    from neurosearch import nightly
    p = db.create_project("p")["id"]
    monkeypatch.setattr(nightly, "_run", lambda force=False: db.add_fact(p, "context", "night work") and {})
    with ledger.acting("kyle", surface="cli", request_id="cli:1"):
        nightly.run(force=True)
    e = _ev(p)["events"][0]
    assert (e["actor_id"], e["originating_actor_id"]) == ("system", "kyle")


def test_access_changes_are_chronology_but_never_disclosed():
    p = db.create_project("p")["id"]
    access.create_actor("Gio", actor_id="gio")
    access.grant(p, "gio", "read")
    access.set_grant_classes(p, "gio", ["standard", "correspondence"])
    access.revoke_grant(p, "gio")
    types = [e["event_type"] for e in sorted(_ev(p)["events"], key=lambda e: e["id"])]
    assert types == ["access_granted", "access_changed", "access_revoked"]
    assert _ev(p, classes=["standard", "correspondence", "financial", "tax", "identity"])["summary"]["changed"] == 0


# ------------------------------------------------------------------ the ledger is written only by its declared writers

def test_ledger_record_is_called_only_from_declared_writers():
    root = Path(__file__).resolve().parent.parent / "neurosearch"
    callers = set()
    for f in root.glob("*.py"):
        if re.search(r"\bledger\.record\(", f.read_text()):
            callers.add(f.name)
    assert callers <= set(ledger.WRITERS), callers - set(ledger.WRITERS)
    for f in ("jobs.py", "usage.py", "perf.py", "cache.py", "breakers.py", "batches.py", "providers.py"):
        assert f not in callers
