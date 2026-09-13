"""S52 — the explicit, in-app FTS5 recovery seam."""
from __future__ import annotations

import pytest

from neurosearch import db, ingest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    from neurosearch.config import settings
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield data
    db.close_thread_connection()


def test_fts5_rebuild_requires_confirmation_and_rechecks_integrity(client, isolated_db):
    ingest.ingest_text("FTS recovery", "A short transcript about durable search indexes.")

    headers = {"Authorization": "Bearer t0k"}
    refused = client.post("/api/maintenance/fts5/rebuild", headers=headers, json={})
    assert refused.status_code == 400
    assert "confirm=true" in refused.json()["detail"]

    response = client.post("/api/maintenance/fts5/rebuild", headers=headers, json={"confirm": True})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["before"] == "ok" and body["result"] == "ok"
    assert body["chunks"] == 1 and body["seconds"] >= 0
    assert db.fts_search("durable search")
    assert db.kv_get("db:last_fts_rebuild")
    health = client.get("/api/health", headers=headers).json()
    assert health["db"]["fts5_rebuild"]["result"] == "ok"
