"""Hand-labeled cases from distinct domains for Claim review and candidate search."""
from datetime import datetime

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
