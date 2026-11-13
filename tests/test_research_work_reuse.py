"""Exercise reuse at the normal entry points with two independent projects."""
from __future__ import annotations

import numpy as np
import pytest

from neurosearch import claim_challenge, claims, db, embeddings, jobs, knowledge, planner, providers, search, sources_value
from neurosearch.config import settings


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db.close_thread_connection()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db.init_db()
    yield
    db.close_thread_connection()


def source(label, text, pid=None):
    src = db.upsert_source(platform="web", external_id=label, url=f"https://example.test/{label}",
                           title=label, status="ready")
    rows = [{"start": 0, "end": 20, "text": text}]
    db.replace_transcript(src["id"], rows, rows)
    if pid:
        db.add_project_sources(pid, [src["id"]])
    return src["id"]


def test_claims_coalesce_and_final_pass_covers_pending_refresh(isolated_db, monkeypatch):
    pid = db.create_project("Coalesce")["id"]
    refreshes = []
    monkeypatch.setattr(knowledge, "refresh", lambda p, progress=None: refreshes.append(p))
    monkeypatch.setattr(claims, "extract", lambda *a, **kw: {"normalized": 5, "more": True})
    for _ in range(2):
        with pytest.raises(jobs.Yield):
            claims.run_job({"project_id": pid})
    job, = [j for j in db.list_jobs() if j["kind"] == "refresh_research"]
    assert job["wait_reason"] == "coalescing"
    assert db.claim_job(kinds=("refresh_research",)) is None
    assert refreshes == []
    monkeypatch.setattr(claims, "extract", lambda *a, **kw: {"normalized": 1})
    claims.run_job({"project_id": pid})
    assert not claims.run_refresh_job(job["payload"])["refreshed"]
    assert refreshes == [pid]


def test_challenge_resumes_and_searches_only_new_sources(isolated_db, monkeypatch):
    pid = db.create_project("Challenge reuse")["id"]
    other = db.create_project("Other challenge")["id"]
    text = "Roof ventilation lowers storage temperatures."
    claim = claims.add_claim(pid, text)
    old = source("old-ventilation", text, pid)
    source("outside-ventilation", text, other)
    first = claim_challenge.find(pid, claim["id"], "roof ventilation", "")
    first["scopes"]["project"]["passages"][0]["assessment"] = "equivalent"
    first["remaining_gaps"] = "Compare a wet climate"
    claim_challenge.save_review(pid, claim["id"], first)
    real_search = search.search_fts
    calls = []

    def traced(q, **kw):
        calls.append(kw["source_ids"])
        return real_search(q, **kw)

    monkeypatch.setattr(search, "search_fts", traced)
    resumed = claim_challenge.find(pid, claim["id"], "roof ventilation", "")
    assert resumed["scopes"]["project"]["search_mode"] == "resumed" and calls == []
    assert resumed["searched_at"] == first["searched_at"]
    added = source("new-ventilation", "Roof ventilation in wet weather causes condensation.", pid)
    resumed = claim_challenge.find(pid, claim["id"], "roof ventilation", "")
    group = resumed["scopes"]["project"]
    assert calls == [[added]] and group["search_mode"] == "added"
    assert group["previous_searched_at"] == first["scopes"]["project"]["searched_at"]
    assert [(p["source_id"], p["assessment"]) for p in group["passages"]] == [(added, ""), (old, "equivalent")]
    assert resumed["remaining_gaps"] == "Compare a wet climate"
    full = claim_challenge.find(pid, claim["id"], "roof ventilation", "", full=True)
    assert full["scopes"]["project"]["search_mode"] == "full" and set(calls[-1]) == {old, added}


def test_plan_check_reuses_empty_and_requires_new_evidence_for_rejection(isolated_db, monkeypatch):
    pid = db.create_project("Plan check reuse")["id"]
    old = db.save_plan(pid, {"first_steps": [{"detail": "Use the small pump"}]}, {})
    calls = []
    proposed = {"section": "first_steps.0.detail", "previous": "Use the small pump",
                "proposed": "Use the large pump", "reason": ""}
    output = []

    def review(*args, **kwargs):
        calls.append(kwargs["messages"])
        return {"updates": output}

    monkeypatch.setattr(providers, "invoke_structured", review)
    db.add_project_note(pid, "Baseline tests are complete.", [])
    assert planner.suggest_updates(pid) == planner.suggest_updates(pid) == []
    assert len(calls) == 1
    evidence = "The small pump overheated after an hour."
    db.add_project_note(pid, evidence, [])
    output[:] = [{**proposed, "reason": f'"{evidence}"'}]
    update, = planner.suggest_updates(pid)
    db.set_update_status(update["id"], "rejected", decision_reason="Test the new seal first")
    db.add_project_note(pid, "The storage cabinet was repainted.", [])
    assert planner.suggest_updates(pid) == []
    assert db.get_plan(old["id"])["updates"][0]["decision_reason"] == "Test the new seal first"
    changed = "The new seal failed at the rated pump pressure."
    db.add_project_note(pid, changed, [])
    output[:] = [{**proposed, "reason": f'"{changed}"'}]
    reopened, = planner.suggest_updates(pid)
    assert reopened["id"] != update["id"]
    assert len(calls) == 4


def test_exact_plan_edit_preserves_execution_state_and_history(isolated_db, monkeypatch):
    pid = db.create_project("Edit plan")["id"]
    old = db.save_plan(pid, {"first_steps": [{"action": "Inspect", "detail": "Use the small pump"}]}, {"sources": 1})
    db.set_plan_status(old["id"], "started")
    db.set_item_status(old["id"], "first_steps.0", "complete", "Checked yesterday")
    db.add_plan_updates(old["id"], [{"section": "first_steps.0.detail", "previous": "Use the small pump",
                                     "proposed": "Use the large pump", "reason": "Pressure"}])
    update, = db.get_plan(old["id"])["updates"]
    db.set_update_status(update["id"], "accepted")
    monkeypatch.setattr(planner, "build_plan", lambda *a: pytest.fail("used a model rebuild"))
    new = planner.apply_exact_edits(pid, old["id"])
    assert new["plan"]["first_steps"] == [{"action": "Inspect", "detail": "Use the large pump"}]
    assert new["status"] == "started" and new["version"] == 2 and new["snapshot"] == old["snapshot"]
    assert new["items"]["first_steps.0"] == {"status": "complete", "note": "Checked yesterday"}
    assert db.get_plan(old["id"])["updates"][0]["applied_plan_id"] == new["id"]
    with pytest.raises(ValueError, match="current plan changed"):
        planner.apply_exact_edits(pid, old["id"])


def test_query_vector_cache_returns_copies_and_separates_contexts(isolated_db, monkeypatch, tmp_path):
    calls = []

    def embed(texts, *, model):
        calls.append((texts[0], model))
        return [np.array([1.0, 2.0])]

    monkeypatch.setattr(embeddings, "embed_texts", embed)
    embeddings.embed_query("exact query")[0] = 10
    assert embeddings.embed_query("exact query").tolist() == [1, 2]
    assert len(calls) == 1
    monkeypatch.setattr(settings, "embedding_model", "different")
    embeddings.embed_query("exact query")
    monkeypatch.setattr(settings, "fake_ai", not settings.fake_ai)
    embeddings.embed_query("exact query")
    monkeypatch.setattr(settings, "data_dir", tmp_path / "elsewhere")
    embeddings.embed_query("exact query")
    assert len(calls) == 4


def test_target_reuses_per_stage_and_keeps_external_opt_in(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    pid = db.create_project("Pursue locally")["id"]
    other = db.create_project("Library owner")["id"]
    old = source("old-pump", "Pump pressure storage tank.", pid)
    source("library-pump", "Pump pressure and storage tank.", other)
    target = knowledge.add_target(pid, "Pump pressure storage tank", origin="user")
    first = knowledge.pursue(target["id"])["escalation"]["steps"]
    again = knowledge.pursue(target["id"])["escalation"]["steps"]
    assert [s["search_mode"] for s in again[:3]] == ["reused", "reused", "reused"]
    assert [s["checked_at"] for s in first[:3]] == [s["checked_at"] for s in again[:3]]
    new = source("new-pump", "Pump pressure is limited by the storage tank.", pid)
    again = knowledge.pursue(target["id"])["escalation"]["steps"]
    assert again[0]["search_mode"] == "added" and again[0]["searched_sources"] == 1
    assert {hit["source_id"] for hit in again[0]["top"]} == {old, new}
    assert again[1]["search_mode"] == "reused" and again[-1]["run"] is False
    full = knowledge.pursue(target["id"], full=True)["escalation"]["steps"]
    assert [s["search_mode"] for s in full[:3]] == ["full", "full", "full"]


def test_drawer_distinguishes_queued_zero_failed_and_project_membership(isolated_db):
    pid = db.create_project("Drawer read status")["id"]
    other = db.create_project("Outside drawer")["id"]
    sid = source("drawer-status", "A ready source with indexed text.", pid)
    read_status = lambda p: sources_value.digest(p, sid)["read_status"]["state"]
    assert read_status(pid) == "unread" and read_status(other) == "outside_project"
    job = db.create_job("suggest_findings", {"project_id": pid, "source_ids": [sid]})
    assert read_status(pid) == "queued"
    claimed = db.claim_job(kinds=("suggest_findings",))
    db.finish_job(job["id"], claimed["run_id"], "failed", message="provider failed")
    assert read_status(pid) == "read_failed"
    db.upsert_analysis(pid, sid, "summary", summary="Read complete")
    digest = sources_value.digest(pid, sid)
    assert digest["read_status"]["state"] == "read" and digest["findings_total"] == 0
