from __future__ import annotations

import pytest

from neurosearch import claims, db, export


AUTH = {"Authorization": "Bearer t0k"}


def test_masterplan_download_uses_latest_saved_plan_without_synthesis(client, monkeypatch):
    pid = db.create_project("Download fixture", "Project brief")["id"]
    path = f"/api/projects/{pid}"
    calls = []

    def synthesize(project_id):
        calls.append(project_id)
        return "Generated synthesis"

    monkeypatch.setattr(export, "synthesize_masterplan", synthesize)
    assert client.get(path + "/masterplan.md", headers=AUTH).text == "Generated synthesis"
    db.save_plan(pid, {"goal": {"outcome": "First saved plan"}}, {})
    db.save_plan(pid, {"goal": {"outcome": "Latest saved plan"}}, {})
    response = client.get(path + "/masterplan.md", headers=AUTH)
    assert response.status_code == 200
    assert response.text == client.get(path + "/plan.md", headers=AUTH).text
    assert "Latest saved plan" in response.text
    assert "First saved plan" not in response.text
    assert calls == [pid]
    assert client.get(path + "/masterplan.md?synthesize=true", headers=AUTH).text == "Generated synthesis"


def test_claim_preview_includes_counterevidence_and_is_project_scoped(client):
    pid = db.create_project("Claim preview", "Project brief")["id"]
    other = db.create_project("Other claim project", "Project brief")["id"]
    claim = claims.add_claim(pid, "The chosen approach works")
    path = f"/api/projects/{pid}/claims/{claim['id']}/evidence"
    response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["supporting"] == response.json()["counter"] == []

    for i in range(8):
        source = db.upsert_source(platform="manual", external_id=f"claim-preview-support-{i}",
                                  url=f"manual://claim-preview-support-{i}", title=f"Support {i}")
        claims.add_evidence(claim["id"], source["id"], excerpt=f"Supporting passage {i}", locator=f"p. {i + 1}")
    counter = db.upsert_source(platform="web", external_id="claim-preview-counter",
                               url="https://example.test/evidence", title="Counterexample")
    claims.add_evidence(claim["id"], counter["id"], relation="CONTRADICTS", locator="§ 2",
                        excerpt="The approach failed here.", link="https://example.test/evidence#counter")
    response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["supporting_total"] == 8 and len(data["supporting"]) == 6
    assert data["counter_total"] == 1
    passage = data["counter"][0]
    assert passage["relation"] == "CONTRADICTS"
    assert passage["excerpt"] == "The approach failed here."
    assert passage["link"] == "https://example.test/evidence#counter"
    assert client.get(path.replace(pid, other), headers=AUTH).status_code == 404


def test_rank_controls_and_claim_preview_in_shipped_javascript():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node required for shipped UI behavior")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "tests/js/run-quick-wins.mjs"], cwd=root,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
