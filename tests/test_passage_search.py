"""Project passage lookup reuses the FTS index and source locators."""
from neurosearch import db, embeddings, providers
from tests.test_core import H


def test_passage_search_exact_terms_and_project_scope(client, monkeypatch):
    project = db.create_project("Passage lookup")
    empty = db.create_project("Empty passage lookup")

    def source(external_id, start, text):
        row = db.upsert_source(platform="youtube", external_id=external_id,
                               url=f"https://www.youtube.com/watch?v={external_id}", status="ready")
        segments = [{"start": start, "end": start + 10, "text": text}]
        db.replace_transcript(row["id"], segments, segments)
        return row["id"]

    match = source("passage-test-a", 65, "They discussed quality of earnings in detail.")
    distractor = source("passage-test-b", 5, "They discussed earnings quality in detail.")
    foreign = source("passage-test-c", 35, "They discussed quality of earnings in detail.")
    db.add_project_sources(project["id"], [match, distractor])
    path = f"/api/projects/{project['id']}/passages"

    def model_call(*args, **kwargs):
        raise AssertionError("Passage search must never invoke a model")

    monkeypatch.setattr(embeddings, "embed_query", model_call)
    monkeypatch.setattr(providers, "invoke", model_call)

    response = client.get(path, params={"q": '"quality of earnings"'}, headers=H)
    assert response.status_code == 200
    hit, = response.json()
    assert hit["source_id"] == match
    assert hit["timestamp"] == "1:05" and hit["link"].endswith("&t=65s")
    assert hit["text"] == "They discussed quality of earnings in detail."

    response = client.get(path, params={"q": "quality earnings", "phrase": False}, headers=H)
    assert {row["source_id"] for row in response.json()} == {match, distractor}
    for source_id in (match, distractor):
        response = client.get(path, params={"q": "quality of earnings", "source_id": source_id}, headers=H)
        assert [row["source_id"] for row in response.json()] == ([match] if source_id == match else [])

    assert client.get(path, params={"q": "earnings", "source_id": foreign}, headers=H).status_code == 404
    assert client.get(path, params={"q": "earnings", "source_id": match}).status_code == 401
    assert client.get(path, params={"q": '" OR *'}, headers=H).json() == []
    assert client.get(f"/api/projects/{empty['id']}/passages", params={"q": "earnings"}, headers=H).json() == []
    db.remove_project_sources(project["id"], [match])
    assert client.get(path, params={"q": "quality of earnings"}, headers=H).json() == []
