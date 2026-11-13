"""Hand-labeled cases from distinct domains for Claim review and candidate search."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from neurosearch import claims, db, knowledge, works
from tests.test_core import H


def _source(pid, name, text):
    source = db.upsert_source(platform="youtube", external_id=name, title=name, status="ready",
                              url=f"https://www.youtube.com/watch?v={name}")
    segments = [{"start": 40, "end": 55, "text": text}]
    db.replace_transcript(source["id"], segments, segments)
    db.add_project_sources(pid, [source["id"]])
    return source["id"]


def test_challenge_retrieves_alternate_wording_and_isolates_library(client, monkeypatch):
    from neurosearch import search

    def forbid_paid_search(*args, **kwargs):
        pytest.fail("Keyword search should never use embeddings")

    monkeypatch.setattr(search, "search", forbid_paid_search)
    pid = db.create_project("Turnover research")["id"]
    library = db.create_project("Independent source library")["id"]
    claim = claims.add_claim(pid, "Removing incentives lowered employee attrition.",
                             qualifiers={"population": "warehouse employees"}, normalized=True)
    initial = _source(pid, "challenge-original", "Removing incentives lowered employee attrition.")
    paraphrase = _source(pid, "challenge-paraphrase", "Staff retention improved after bonus payments ended.")
    reprint = _source(library, "challenge-reprint", "Removing incentives lowered employee attrition.")
    library_lead = _source(library, "challenge-library", "Staff retention declined after bonus payments ended.")
    work, _ = works.ensure_work("other", "Warehouse compensation report")
    works.link_source(initial, work["id"])
    works.link_source(reprint, work["id"], relation="reprint_of")
    claims.add_evidence(claim["id"], initial, excerpt="Removing incentives lowered employee attrition.", locator="0:40")

    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    body = {"alternate": "staff retention bonus payments"}
    reply = client.post(path, json=body, headers=H)
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["queries"] == [claim["text"], body["alternate"]]
    assert result["method"] == "keyword" and datetime.fromisoformat(result["searched_at"]).tzinfo
    assert set(result["scopes"]) == {"project"}
    hits = {p["source_id"]: p for p in result["scopes"]["project"]["passages"]}
    assert hits.keys() == {initial, paraphrase}
    assert hits[initial]["same_origin_as_support"]
    assert hits[initial]["origin_status"] == "already_cited"
    assert hits[paraphrase]["origin_status"] == "unverified"
    assert hits[paraphrase]["link"].endswith("&t=40s")

    result = client.post(path, json={**body, "library": True}, headers=H).json()
    hits = {p["source_id"] for p in result["scopes"]["library"]["passages"]}
    assert library_lead in hits and reprint not in hits
    assert client.post(path.replace(pid, library), json=body, headers=H).status_code == 404
    assert client.post(path, json=body).status_code == 401
    assert len(claims.get(claim["id"])["evidence"]) == 1


@pytest.mark.parametrize("counter_text,counter_scope,relation,reason", [
    ("Solar ventilation increased storage temperatures", "dry climate", "CONTRADICTS", "disagreement"),
    ("Solar ventilation did not lower storage temperatures", "humid climate", "QUALIFIES", "qualification"),
])
def test_review_queue_pairs_actual_passages_and_respects_scope(client, counter_text, counter_scope, relation, reason):
    pid = db.create_project(f"Storage engineering · {counter_scope}")["id"]
    statement = "Solar ventilation lowered storage temperatures"
    claim = claims.add_claim(pid, statement, claim_type="causal", qualifiers={"conditions": "dry climate"}, normalized=True)
    counter = claims.add_claim(pid, counter_text, qualifiers={"conditions": counter_scope}, normalized=True)
    for label, row, text in (("pro", claim, statement), ("counter", counter, counter_text)):
        sid = _source(pid, f"challenge-{pid}-{label}", text)
        claims.add_evidence(row["id"], sid, excerpt=text, locator="0:40")
    result = claims.relate(claim["id"], counter["id"], "CONTRADICTS")
    assert result["relation"] == relation
    base = f"/api/projects/{pid}/claims"
    queue = client.get(base + "/review-queue", headers=H).json()["queue"]
    row = next(row for row in queue if row["claim_id"] == claim["id"])
    assert reason in row["reasons"]
    assert row["disagreement"] == (relation == "CONTRADICTS")
    preview = client.get(f"{base}/{claim['id']}/evidence", headers=H).json()
    if relation == "CONTRADICTS":
        assert [row["excerpt"] for row in preview["comparison"]] == [statement, counter_text]
    else:
        assert preview["comparison"] == []


def test_outlier_prompt_only_suppressed_by_current_equivalent_independent_support(client):
    pid = db.create_project("Reading intervention research")["id"]
    text = "Small group tutoring improved comprehension"
    claim = claims.add_claim(pid, text, claim_type="causal", qualifiers={"population": "grade 3"}, normalized=True)
    source = _source(pid, "challenge-tutoring-first", text)
    copy = _source(pid, "challenge-tutoring-copy", text)
    work, _ = works.ensure_work("other", "Original tutoring report")
    works.link_source(source, work["id"])
    works.link_source(copy, work["id"], relation="reprint_of")
    claims.add_evidence(claim["id"], source, excerpt=text, locator="0:40")
    equivalent = claims.add_claim(pid, text, claim_type="causal", qualifiers={"population": "grade 3"}, normalized=True)
    claims.add_evidence(equivalent["id"], copy, excerpt=text, locator="0:40")
    opposite = claims.add_claim(pid, "Small group tutoring reduced comprehension", claim_type="causal",
                                qualifiers={"population": "grade 3"}, normalized=True)
    sid = _source(pid, "challenge-tutoring-opposite", opposite["text"])
    claims.add_evidence(opposite["id"], sid, excerpt=opposite["text"], locator="0:40")

    def outlier():
        knowledge.detect(pid)
        return any(t["kind"] == "NOVEL" and t["claim_id"] == claim["id"] for t in knowledge.list_tensions(pid))

    assert outlier()
    queue = client.get(f"/api/projects/{pid}/claims/review-queue", headers=H).json()["queue"]
    row = next(row for row in queue if row["claim_id"] == claim["id"])
    assert "corroboration" in row["reasons"] and not row["disagreement"]

    independent = _source(pid, "challenge-tutoring-independent", text)
    other_work, _ = works.ensure_work("other", "Second tutoring report")
    works.link_source(independent, other_work["id"])
    evidence = claims.add_evidence(equivalent["id"], independent, excerpt=text + " in a second school.", locator="0:40")
    assert not outlier()
    with db.tx() as conn:
        conn.execute("UPDATE claim_evidence SET stale=1 WHERE id=?", (evidence["id"],))
    assert outlier()


def test_saved_challenge_reopens_and_flags_revised_evidence(client):
    pid = db.create_project("Saved research challenge")["id"]
    other = db.create_project("Other project")["id"]
    claim = claims.add_claim(pid, "Roof vents lower storage temperatures.")
    sid = _source(pid, "challenge-saved-vent", "Roof vents lower storage temperatures.")
    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    found = client.post(path, json={}, headers=H).json()
    passage, = found["scopes"]["project"]["passages"]
    passage.update(assessment="equivalent", text="Untrusted replacement")
    found["remaining_gaps"] = "Check other climates"
    saved = client.put(path + "/review", json=found, headers=H)
    assert saved.status_code == 200, saved.text
    result = client.get(path + "/review", headers=H).json()["review"]
    stored, = result["scopes"]["project"]["passages"]
    assert stored["assessment"] == "equivalent"
    assert stored["text"] == "Roof vents lower storage temperatures."
    assert result["remaining_gaps"] == "Check other climates"
    assert not result["claim_changed"] and not stored["changed"]
    assert not claims.get(claim["id"])["evidence"]
    assert client.put(path.replace(pid, other) + "/review", json=found, headers=H).status_code == 404

    revised = [{"start": 40, "end": 55, "text": "Roof vents increased storage temperatures."}]
    db.replace_transcript(sid, revised, revised)
    result = client.get(path + "/review", headers=H).json()["review"]
    assert result["scopes"]["project"]["passages"][0]["changed"]
    assert client.put(path + "/review", json=found, headers=H).status_code == 409


def test_challenge_origin_tracks_current_works_without_rewriting_judgments(client):
    pid = db.create_project("Provenance review")["id"]
    claim = claims.add_claim(pid, "Roof vents lower storage temperatures.")
    cited = _source(pid, "challenge-provenance-cited", claim["text"])
    match = _source(pid, "challenge-provenance-match", claim["text"])
    cited_work, _ = works.ensure_work("other", "Ventilation report A")
    match_work, _ = works.ensure_work("other", "Ventilation report B")
    works.link_source(cited, cited_work["id"])
    works.link_source(match, match_work["id"])
    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    result = client.post(path, headers=H, json={}).json()
    passage = next(p for p in result["scopes"]["project"]["passages"] if p["source_id"] == match)
    assert passage["origin_status"] == "unverified"
    passage["assessment"] = "equivalent"
    passage["origin_status"] = "already_cited"  # client metadata is never accepted as provenance
    saved = client.put(path + "/review", headers=H, json=result)
    assert saved.status_code == 200, saved.text

    def stored_match():
        review = client.get(path + "/review", headers=H).json()["review"]
        return next(p for p in review["scopes"]["project"]["passages"] if p["source_id"] == match)

    assert stored_match()["origin_status"] == "unverified"
    claims.add_evidence(claim["id"], cited, excerpt=claim["text"], locator="0:40")
    assert stored_match()["origin_status"] == "different_recorded_work"
    claims.add_evidence(claim["id"], match, excerpt=claim["text"], locator="0:40")
    stored = stored_match()
    assert stored["origin_status"] == "already_cited"
    assert stored["assessment"] == "equivalent" and not stored["changed"]


def test_pending_plan_proposal_shows_recorded_claim_and_passage(client):
    pid = db.create_project("Plan with evidence")["id"]
    claim = claims.add_claim(pid, "Roof vents lower storage temperatures.")
    sid = _source(pid, "plan-evidence-vent", claim["text"])
    claims.add_evidence(claim["id"], sid, excerpt=claim["text"], locator="0:40")
    plan = db.save_plan(pid, {}, {})
    db.add_plan_updates(plan["id"], [
        {"section": "ventilation", "proposed": "Add rooftop vents", "claim_id": claim["id"]},
        {"section": "monitoring", "proposed": "Log daytime temperatures"},
    ])
    data = client.get(f"/api/projects/{pid}/plan", headers=H).json()
    linked, unlinked = data["plan"]["updates"]
    assert linked["claim_evidence"]["text"] == claim["text"]
    assert linked["claim_evidence"]["supporting"][0]["locator"] == "0:40"
    assert "claim_evidence" not in unlinked


@pytest.mark.parametrize("subject,claim_text,first,precedent,exception,wording", [
    ("Ventilation", "Nighttime rooftop vents reduce warehouse heat in dry climates",
     "Rooftop vents in warehouses can be opened at night for maintenance.",
     "The dry-climate warehouse trial reduced daytime heat by opening rooftop vents overnight.",
     "Nighttime rooftop vents increased warehouse heat in humid climates.",
     "warehouse trial overnight daytime heat"),
    ("Tutoring", "Small group tutoring improves comprehension for third graders",
     "Small group tutoring has been used to schedule third grade reading sessions.",
     "Third grade reading groups improved comprehension in a controlled tutoring trial.",
     "Small group tutoring reduced comprehension for third graders in the trial.",
     "controlled reading groups trial comprehension"),
    ("Scheduling", "Evening dispatch reduces missed deliveries on rural routes",
     "Evening dispatch is listed in the rural route calendar.",
     "A rural route trial found fewer missed deliveries after switching dispatch to evenings.",
     "Evening dispatch increased missed deliveries on rural routes in winter.",
     "rural route trial switching dispatch evenings"),
])
def test_challenge_benchmark_recovers_prior_example_and_keeps_scope_evidence(
    client, subject, claim_text, first, precedent, exception, wording,
):
    pid = db.create_project(f"Challenge benchmark {subject}")["id"]
    lib = db.create_project(f"Challenge benchmark library {subject}")["id"]
    claim = claims.add_claim(pid, claim_text)
    original = _source(pid, f"prior-{subject}-original", first)
    copy = _source(lib, f"prior-{subject}-copy", precedent)
    source = _source(pid, f"prior-{subject}-counter", exception)
    work, _ = works.ensure_work("other", f"Challenge benchmark report {subject}")
    works.link_source(original, work["id"])
    works.link_source(copy, work["id"], relation="reprint_of")
    works.link_source(source, work["id"])
    passages = [{"start": i * 40, "end": (i + 1) * 40, "text": text}
                for i, text in enumerate([first, precedent])]
    db.replace_transcript(original, passages, passages)
    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    response = client.post(path, headers=H, json={"precedent": wording, "counter": exception, "library": True})
    assert response.status_code == 200, response.text
    data = response.json()
    found = data["scopes"]["project"]["passages"]
    assert {precedent, exception} <= {p["text"] for p in found}
    assert len(found) == 2
    assert len({p["origin"] for p in found}) == 1
    assert [p["source_id"] for p in found].count(original) == 1
    assert any(p["source_id"] == source for p in found)
    assert not any(p["source_id"] == copy for p in data["scopes"]["library"]["passages"])
    assert data["scopes"]["project"]["searchable_sources"] == 2


def test_saved_challenge_detects_new_and_revised_unreviewed_sources(client):
    pid = db.create_project("Challenge coverage")["id"]
    claim = claims.add_claim(pid, "Warehouse skylights reduce lighting costs.")
    _source(pid, "challenge-covered-lighting", claim["text"])
    unreviewed = _source(pid, "challenge-covered-extra", "Truck loading ramps")
    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    result = client.post(path, headers=H, json={}).json()
    assert result["scopes"]["project"]["searchable_sources"] == 2
    assert len(result["scopes"]["project"]["passages"]) == 1
    result["scopes"]["project"]["passages"][0]["assessment"] = "equivalent"
    assert client.put(path + "/review", headers=H, json=result).status_code == 200
    _source(pid, "challenge-covered-new", "More information about warehouse skylights")
    saved = client.get(path + "/review", headers=H).json()["review"]
    assert saved["scopes"]["project"]["scope_changed"]
    assert not saved["scopes"]["project"]["passages"][0]["changed"]
    assert client.put(path + "/review", headers=H, json=result).status_code == 409

    result = client.post(path, headers=H, json={}).json()
    for passage in result["scopes"]["project"]["passages"]:
        passage["assessment"] = "equivalent"
    assert client.put(path + "/review", headers=H, json=result).status_code == 200
    segments = [{"start": 40, "end": 55, "text": "Ramp permits expire annually."}]
    db.replace_transcript(unreviewed, segments, segments)
    saved = client.get(path + "/review", headers=H).json()["review"]
    assert saved["scopes"]["project"]["scope_changed"]
    assert all(not p["changed"] for p in saved["scopes"]["project"]["passages"])


@pytest.mark.parametrize("case", json.loads(
    (Path(__file__).parent / "fixtures" / "novelty_challenge.json").read_text()
), ids=lambda case: case["id"])
def test_challenge_recovers_independent_precedents_and_preserves_scope_labels(client, case):
    pid = db.create_project(f"Novelty benchmark {case['id']}")["id"]
    library = db.create_project(f"Novelty benchmark library {case['id']}")["id"]
    claim = claims.add_claim(pid, case["claim"], qualifiers=case["qualifiers"])
    labels = {}
    for label, excerpt in case["passages"]:
        sid = _source(pid, f"novelty-benchmark-{case['id']}-{label}", excerpt)
        labels[sid] = label
        if label == "cited":
            claims.add_evidence(claim["id"], sid, excerpt=excerpt, locator="0:40")
            work, _ = works.ensure_work("other", f"Original report {case['id']}")
            works.link_source(sid, work["id"])
            copy = _source(library, f"novelty-benchmark-{case['id']}-reprint", excerpt)
            works.link_source(copy, work["id"], relation="reprint_of")

    path = f"/api/projects/{pid}/claims/{claim['id']}/challenge"
    alternate, precedent, counter = case["queries"]
    response = client.post(path, headers=H, json={"alternate": alternate, "precedent": precedent, "counter": counter,
                                                 "library": True})
    assert response.status_code == 200, response.text
    scopes = response.json()["scopes"]
    passages = {labels[p["source_id"]]: p for p in scopes["project"]["passages"]}
    assert set(passages) == {label for label, _ in case["passages"]}
    assert passages["cited"]["same_origin_as_support"]
    if "precedent" in passages:
        assert not passages["precedent"]["same_origin_as_support"]
    assert all(not p["assessment"] for p in passages.values())
    assert all(p["source_id"] != copy for p in scopes["library"]["passages"])
