"""P11 EA-4/EA-5/EA-6 — External Intake Events, processed-material ingestion and bidirectional state sync
(EXTERNAL-AI-ACCESS-MISSION.md §21–§25, §29–§31, §47–§55, §61; plan §6, §7 and §10 rows 3–4, 6–9).

The gate: several objects from one turn stay separate but linked; processed screenshots/PDFs/transcripts become
normal Neuro sources with NO OCR, transcription, model call or refetch; interpretation never becomes evidence;
retries duplicate nothing; orphans and failures surface as needs_review; revocation stops new access but keeps
accepted material; the worked negotiation flow (seller email → decision → reaffirm → change → collaborator
conflict) passes end to end, attributed to the person and client who said it."""
from __future__ import annotations

import json
import os
import time

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, db, external_schemas, facts, intake, jobs, ledger, safe_fetch
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir(); (d / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    yield
    db._local.conn = None


@pytest.fixture
def world(client):
    p = db.create_project("Business acquisition", "buy an HVAC business")["id"]
    access.create_actor("Gio", actor_id="gio")
    c_gio, c_kyle = access.create_client("Gio's ChatGPT", transport="tunnel")["id"], access.create_client("Kyle's ChatGPT")["id"]
    _, s_gio = access.issue_credential("gio", c_gio)
    _, s_kyle = access.issue_credential("kyle", c_kyle)
    access.grant(p, "gio", "contribute", classes=["standard", "correspondence", "financial"])
    access.grant(p, "kyle", "owner", classes=list(external_schemas.DISCLOSURE_CLASSES))
    return {"p": p, "gio": s_gio, "kyle": s_kyle, "c_gio": c_gio, "c_kyle": c_kyle}


def ext(client, secret, op, **args):
    return client.post(f"/api/ext/v1/{op}", json=args, headers={"Authorization": f"Bearer {secret}"})


def run_items(intake_id):
    """Claim and execute the intake's queued jobs exactly as a worker would (conftest's run_queued_job, inlined)."""
    for r in db.connect().execute("SELECT ingest_job_id FROM intake_items WHERE intake_id=? AND ingest_job_id IS NOT NULL", (intake_id,)).fetchall():
        j = db.get_job(r["ingest_job_id"])
        if j and j["status"] == "queued":
            db.bump_job(j["id"])
            claimed = db.claim_job((j["kind"],), worker_id="test-driver")
            assert claimed and claimed["id"] == j["id"]
            jobs.execute(claimed, "test-driver")


@pytest.fixture
def no_cognition(monkeypatch):
    """Anything that would re-read what the client already read is a failure here."""
    from neurosearch import embeddings, images, providers, transcribe, webpage
    def boom(*a, **k):
        raise AssertionError("Neuro repeated cognition the client already performed")
    for mod, name in ((providers, "invoke"), (providers, "invoke_structured"), (images, "ocr"), (images, "_ocr_model"),
                      (transcribe, "transcribe_file"), (webpage, "fetch"), (safe_fetch, "safe_fetch"), (embeddings, "embed_query")):
        monkeypatch.setattr(mod, name, boom)
    monkeypatch.setattr(jobs, "enqueue_suggestions", lambda *a, **k: None)   # Neuro's OWN later findings pass is not duplicate cognition


SCREENSHOT = {"material_type": "image", "title": "Seller email screenshot", "producer": "Gio's ChatGPT", "extraction_method": "vision",
              "units": [{"locator": "region:0,0,800,300", "text": "We have another interested buyer and need an answer by Friday."}],
              "client_declared_class": "standard"}
PDF = {"material_type": "pdf", "title": "Updated financials FY2025", "producer": "Gio's ChatGPT", "extraction_method": "pdf_text",
       "client_declared_class": "financial",
       "units": [{"locator": "p. 1", "text": "Revenue 2025: $1.2M. SDE: $310k."}, {"locator": "p. 3", "text": "Add-backs: owner vehicle $18k."}]}
EMAIL = {"material_type": "correspondence", "title": "Re: seller note", "producer": "Gio's ChatGPT", "extraction_method": "manual",
         "correspondence": {"from": "seller@example.com", "to": ["gio@example.com"], "date": "2026-09-20", "subject": "Re: seller note"},
         "units": [{"locator": "msg:1", "text": "We would prefer a 5% seller note and a 6 month transition."}]}
TRANSCRIPT = {"material_type": "transcript", "title": "Call with the broker", "producer": "Gio's ChatGPT", "extraction_method": "asr",
              "client_declared_class": "standard",
              "units": [{"text": "The seller is flexible on the note.", "speaker": "Broker", "start": 12.0, "end": 18.0},
                        {"text": "Transition matters more to them.", "speaker": "Broker", "start": 75.0, "end": 80.0}]}


def test_one_turn_many_objects_separate_but_linked(client, world, no_cognition):
    r = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0001", conversation_ref="chat-abc")
    assert r.status_code == 200, r.text
    iid = r.json()["data"]["intake_id"]
    again = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0001").json()["data"]
    assert again["intake_id"] == iid and again["idempotent_replay"]
    ids = {}
    for name, m in (("shot", SCREENSHOT), ("pdf", PDF), ("email", EMAIL), ("call", TRANSCRIPT)):
        d = ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=m, item_request_id=f"item-{name}").json()["data"]
        ids[name] = d["item"]["item_id"]
        assert d["item"]["status"] == "queued"
    dup = ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=PDF, item_request_id="item-pdf").json()["data"]
    assert dup["item"]["item_id"] == ids["pdf"] and dup["idempotent_replay"]
    run_items(iid)
    fin = ext(client, world["gio"], "finalize_intake", project_id=world["p"], intake_id=iid,
              interpretations=[{"text": "This may be negotiation pressure.", "about_item_id": ids["shot"]}]).json()["data"]
    assert fin["status"] == "ready" and fin["finalized"]
    kinds = sorted(i["kind"] for i in fin["items"])
    assert kinds == ["interpretation"] + ["processed_material"] * 4
    srcs = {i["item_id"]: i["source_id"] for i in fin["items"] if i["kind"] == "processed_material"}
    assert len(set(srcs.values())) == 4
    rows = {r["id"]: dict(r) for r in db.connect().execute("SELECT * FROM sources").fetchall()}
    assert rows[srcs[ids["pdf"]]]["platform"] == "document" and rows[srcs[ids["pdf"]]]["disclosure_class"] == "financial"
    assert rows[srcs[ids["email"]]]["disclosure_class"] == "correspondence"             # the type implies it (raise-only)
    assert rows[srcs[ids["shot"]]]["disclosure_class"] == "standard"
    assert all(rows[s]["acquisition_provenance"] == "external_processed" for s in srcs.values())
    assert set(srcs.values()) <= set(db.project_source_ids(world["p"]))
    # page locators survive: evidence drill-down reaches "p. 3"
    ev = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref={"source_id": srcs[ids["pdf"]], "start": 2}, depth="exact").json()["data"]
    assert ev["passage"][0]["locator"] == "p. 3" and "Add-backs" in ev["passage"][0]["text"]
    call = ext(client, world["gio"], "get_evidence", project_id=world["p"], ref={"source_id": srcs[ids["call"]], "start": 70}, depth="exact").json()["data"]
    assert call["passage"][0]["locator"] == "1:15" and call["passage"][0]["text"].startswith("Broker: Transition")
    # the interpretation is not a source and not evidence anywhere
    assert not any("negotiation pressure" in (r.get("title") or "") for r in rows.values())
    hits = ext(client, world["gio"], "search_project", project_id=world["p"], query="negotiation pressure").json()["data"]["hits"]
    assert not any("negotiation pressure" in json.dumps(h) for h in hits)
    # finalize is idempotent
    assert ext(client, world["gio"], "finalize_intake", project_id=world["p"], intake_id=iid).json()["data"]["idempotent_replay"]
    assert [e["event_type"] for e in ledger.events(world["p"])["events"]].count("intake_finalized") == 1


def test_processed_material_that_already_exists_is_not_stored_twice(client, world, no_cognition):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0002").json()["data"]["intake_id"]
    ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=PDF)
    run_items(iid)
    iid2 = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0003").json()["data"]["intake_id"]
    ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid2, material=PDF)
    run_items(iid2)
    a = intake.status(intake._row(iid))["items"][0]["source_id"]
    b = intake.status(intake._row(iid2))["items"][0]["source_id"]
    assert a == b and db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1


def test_attribution_is_the_contributor_through_their_client(client, world, no_cognition):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0004").json()["data"]["intake_id"]
    ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=SCREENSHOT)
    run_items(iid)
    att = [e for e in ledger.events(world["p"])["events"] if e["event_type"] == "source_attached"][0]
    assert (att["actor_id"], att["external_client_id"], att["intake_id"]) == ("gio", world["c_gio"], iid)


def test_raw_artifacts_path_a_and_retained_originals(client, world, monkeypatch):
    from neurosearch import ingest
    calls = []
    def fake_ingest(path, title=None, tags=None, project_id=None, progress=None, original_name=None, **k):
        calls.append(original_name)
        s = db.upsert_source(platform="file", external_id=f"f:{original_name}", url=f"file://{original_name}", title=original_name, status="ready")
        db.add_project_sources(project_id, [s["id"]])
        return {"source_id": s["id"]}
    monkeypatch.setattr(ingest, "ingest_local_file", fake_ingest)
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0005").json()["data"]["intake_id"]
    shot = ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=SCREENSHOT).json()["data"]["item"]
    H = {"Authorization": f"Bearer {world['gio']}"}
    kept = client.post(f"/api/ext/v1/intakes/{iid}/artifacts", headers=H, data={"project_id": world["p"], "item_id": shot["item_id"]},
                       files={"file": ("seller.png", b"\x89PNG\r\n\x1a\n fake bytes", "image/png")}).json()["data"]
    assert kept["retained_as_original_of"] == shot["item_id"] and kept["item"]["sha256"]
    raw = client.post(f"/api/ext/v1/intakes/{iid}/artifacts", headers=H, data={"project_id": world["p"], "client_declared_class": "financial"},
                      files={"file": ("ledger.xlsx", b"PK fake workbook", "application/vnd.ms-excel")}).json()["data"]
    run_items(iid)
    assert calls == ["ledger.xlsx"]                                      # only the artifact nobody had read was read
    st = intake.status(intake._row(iid))
    raw_item = next(i for i in st["items"] if i["item_id"] == raw["item"]["item_id"])
    assert raw_item["status"] == "ready" and raw_item["source_id"]
    row = db.connect().execute("SELECT disclosure_class, acquisition_provenance FROM sources WHERE id=?", (raw_item["source_id"],)).fetchone()
    assert (row["disclosure_class"], row["acquisition_provenance"]) == ("financial", "user_private")
    retained = next(i for i in st["items"] if i["item_id"] == kept["item"]["item_id"])
    shot_src = next(i for i in st["items"] if i["item_id"] == shot["item_id"])["source_id"]
    assert retained["status"] == "ready" and retained["source_id"] == shot_src      # the original belongs to the source it was read into


def test_signed_url_goes_through_safe_fetch_and_a_blocked_fetch_needs_review(client, world, monkeypatch):
    monkeypatch.setattr(safe_fetch, "RESOLVER", lambda host, port: ["127.0.0.1"])
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0006").json()["data"]["intake_id"]
    r = ext(client, world["gio"], "attach_artifact", project_id=world["p"], intake_id=iid,
            artifact_ref={"kind": "signed_url", "url": "https://files.example.com/a.pdf?sig=x"})
    assert r.status_code == 200, r.text
    run_items(iid)
    st = ext(client, world["gio"], "get_intake_status", project_id=world["p"], intake_id=iid).json()["data"]
    assert st["status"] == "needs_review" and st["items"][0]["status"] == "failed"
    assert "private" in (st["items"][0]["error"] or "").lower() or "blocked" in (st["items"][0]["error"] or "").lower() or st["items"][0]["error"]
    unsupported = ext(client, world["gio"], "attach_artifact", project_id=world["p"], intake_id=iid, artifact_ref={"kind": "client_handle", "handle": "x"})
    assert unsupported.status_code == 422 and unsupported.json()["error"]["code"] == "capability_missing"


def test_orphaned_intake_surfaces_as_needs_review(client, world):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0007").json()["data"]["intake_id"]
    with db.tx() as conn:
        conn.execute("UPDATE external_intakes SET created_at=? WHERE id=?", (time.time() - intake.ORPHAN_S - 5, iid))
    st = ext(client, world["gio"], "get_intake_status", project_id=world["p"], intake_id=iid).json()["data"]
    assert st["status"] == "needs_review" and st["needs_review_reason"] == "never finalized by the client"
    inbox = client.get(f"/api/projects/{world['p']}/inbox", headers={"Authorization": "Bearer t0k"}).json()["intakes"]
    assert inbox[0]["intake_id"] == iid and inbox[0]["status"] == "needs_review" and inbox[0]["by"] == "Gio" and inbox[0]["via"] == "Gio's ChatGPT"


def test_intakes_belong_to_their_creator_and_read_only_cannot_write(client, world):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0008").json()["data"]["intake_id"]
    r = ext(client, world["kyle"], "get_intake_status", project_id=world["p"], intake_id=iid)
    assert r.status_code == 404
    access.grant(world["p"], "gio", "read")
    for op, a in (("create_intake", {"client_request_id": "turn-0009"}), ("sync_project_state", {"changes": [
            {"op": "record", "kind": "decision", "content": "x", "client_request_id": "chg-00001"}]})):
        r = ext(client, world["gio"], op, project_id=world["p"], **a)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


def test_invalid_material_is_rejected_with_every_reason(client, world):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="turn-0010").json()["data"]["intake_id"]
    r = ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid,
            material={"material_type": "hologram", "title": "", "units": []})
    assert r.status_code == 422 and len(r.json()["error"]["detail"]) >= 3


# ------------------------------------------------------------------ EA-6: the worked negotiation flow

def test_worked_negotiation_flow_end_to_end(client, world, no_cognition):
    p = world["p"]
    # turn 1 — "The seller sent these. Does this change how we handle the 10% seller note?"  → READ + WRITE
    orient = ext(client, world["gio"], "open_project", project_id=p).json()
    cur = orient["ledger_cursor"]
    ext(client, world["gio"], "consult_project", project_id=p, question="Does this change how we handle the 10% seller note?")
    iid = ext(client, world["gio"], "create_intake", project_id=p, client_request_id="neg-turn-1", base_revision=cur).json()["data"]["intake_id"]
    ext(client, world["gio"], "add_processed_material", project_id=p, intake_id=iid, material=EMAIL, item_request_id="neg-email")
    ext(client, world["gio"], "add_processed_material", project_id=p, intake_id=iid, material=PDF, item_request_id="neg-pdf")
    run_items(iid)
    ext(client, world["gio"], "finalize_intake", project_id=p, intake_id=iid,
        interpretations=[{"text": "The 5% ask may be an opening position."}])
    # turn 2 — "That makes sense. Let's stay at 10%, but frame it around transition."  → WRITE ONLY
    r = ext(client, world["gio"], "sync_project_state", project_id=p, base_revision=cur, changes=[
        {"op": "record", "kind": "decision", "content": "Seller note stays at 10%", "rationale": "frame it around the transition",
         "explicitness": "explicit", "user_text": "That makes sense. Let's stay at 10%, but frame it around transition.",
         "client_request_id": "neg-dec-1"}])
    applied = r.json()["data"]["applied"]
    assert r.status_code == 200 and applied[0]["status"] == "active"
    fid = applied[0]["fact_id"]
    replay = ext(client, world["gio"], "sync_project_state", project_id=p, changes=[
        {"op": "record", "kind": "decision", "content": "Seller note stays at 10%", "client_request_id": "neg-dec-1"}]).json()["data"]
    assert replay["applied"][0]["fact_id"] == fid and replay["applied"][0]["replay"] is True
    # turn 3 — "Turn that into a polite email."  → NEITHER: nothing to call; nothing changes
    before = ledger.cursor(p)
    # turn 4 — new pressure; "We're still staying at 10%."  → reaffirmation is chronology, state unchanged
    seen = ext(client, world["gio"], "open_project", project_id=p).json()["ledger_cursor"]
    ext(client, world["gio"], "sync_project_state", project_id=p, base_revision=seen, changes=[
        {"op": "reaffirm", "fact_id": fid, "rationale": "seller claims another buyer", "user_text": "We're still staying at 10%.",
         "client_request_id": "neg-reaff-1"}])
    assert facts.get(fid)["status"] == "active" and ledger.cursor(p) == before + 1
    # a personal preference is not the shared position; an ambiguous acceptance is refused
    r = ext(client, world["gio"], "sync_project_state", project_id=p, changes=[
        {"op": "record", "kind": "preference", "content": "I personally prefer 8%", "scope": "personal", "client_request_id": "neg-pref-1"},
        {"op": "record", "kind": "decision", "content": "all three recommendations", "explicitness": "accepted_recommendation",
         "client_request_id": "neg-acc-1"}])
    assert r.status_code == 422
    # Kyle, concurrently, from his own client changes it to 8%; Gio's stale change to 7.5% conflicts instead of winning
    k = ext(client, world["kyle"], "sync_project_state", project_id=p, base_revision=seen + 1, changes=[
        {"op": "supersede", "fact_id": fid, "content": "Seller note 8%", "user_text": "Change it to 8%.", "client_request_id": "kyle-sup-1"}]).json()["data"]
    assert k["conflicts"] == [] and k["applied"][0]["status"] == "active"
    g = ext(client, world["gio"], "sync_project_state", project_id=p, base_revision=seen + 1, changes=[
        {"op": "supersede", "fact_id": fid, "content": "Seller note 7.5%", "user_text": "Let's do 7.5%.", "client_request_id": "gio-sup-1"}]).json()["data"]
    assert g["applied"] == [] and g["conflicts"][0]["fact_id"] == fid and g["conflicts"][0]["current"]["status"] == "superseded"
    # the shared position and its chronology, as Gio's client sees them
    pos = ext(client, world["gio"], "open_project", project_id=p).json()["data"]["orientation"]["current_position"]
    assert [(f["content"], f["by"]) for f in pos if f["kind"] == "decision"] == [("Seller note 8%", "kyle")]
    hist = ext(client, world["gio"], "get_evidence", project_id=p, ref={"fact_id": fid}).json()["data"]["history"]
    assert [h["content"] for h in hist] == ["Seller note stays at 10%", "Seller note 8%"]
    chrono = [(e["event_type"], e["actor_id"], e["external_client_id"]) for e in
              sorted(ledger.events(p, object_type="fact", object_id=str(fid))["events"], key=lambda e: e["id"])]
    assert chrono == [("decision_recorded", "gio", world["c_gio"]), ("decision_reaffirmed", "gio", world["c_gio"]),
                      ("decision_changed", "kyle", world["c_kyle"])]


def test_ambiguous_acceptance_needs_a_single_referent(client, world):
    ok = ext(client, world["gio"], "sync_project_state", project_id=world["p"], changes=[
        {"op": "record", "kind": "decision", "content": "Remain at 10%", "explicitness": "accepted_recommendation",
         "referent": "Do you want to remain at 10%?", "user_text": "Yes.", "client_request_id": "acc-ok-01"}])
    assert ok.status_code == 200 and ok.json()["data"]["applied"][0]["status"] == "active"
    inferred = ext(client, world["gio"], "sync_project_state", project_id=world["p"], changes=[
        {"op": "propose", "kind": "decision", "content": "Maybe be more flexible", "client_request_id": "prop-0001"}]).json()["data"]
    assert inferred["applied"][0]["status"] == "proposed"
    pos = [f["content"] for f in facts.current_position(world["p"])]
    assert "Maybe be more flexible" not in pos


def test_cannot_change_a_fact_you_cannot_see(client, world):
    secret_fact = facts.record(world["p"], "decision", "tax position", disclosure_class="tax")
    r = ext(client, world["gio"], "sync_project_state", project_id=world["p"], changes=[
        {"op": "supersede", "fact_id": secret_fact["id"], "content": "changed", "user_text": "change it", "client_request_id": "sneaky-001"}], base_revision=0)
    assert r.status_code == 404
    assert facts.get(secret_fact["id"])["status"] == "active"


def test_revocation_keeps_accepted_material_and_stops_new_access(client, world, no_cognition):
    iid = ext(client, world["gio"], "create_intake", project_id=world["p"], client_request_id="rev-turn-1").json()["data"]["intake_id"]
    ext(client, world["gio"], "add_processed_material", project_id=world["p"], intake_id=iid, material=SCREENSHOT)
    ext(client, world["gio"], "sync_project_state", project_id=world["p"], changes=[
        {"op": "record", "kind": "decision", "content": "Stay at 10%", "user_text": "Stay at 10%.", "client_request_id": "rev-dec-01"}])
    access.revoke_credential(access.authenticate(world["gio"]).credential_id, reason="Gio left the deal")
    assert ext(client, world["gio"], "open_project", project_id=world["p"]).status_code == 401
    run_items(iid)                                                   # already-accepted material still finishes, with its attribution
    k = ext(client, world["kyle"], "open_project", project_id=world["p"]).json()["data"]
    assert k["orientation"]["counts"]["sources"] == 1
    assert [f["by"] for f in k["orientation"]["current_position"]] == ["gio"]
