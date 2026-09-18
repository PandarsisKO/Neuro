"""CHR1 (docs/CHAT-REFRESH-PLAN.md §3, §5-§7, §11, §14): Conversation Delta — the deterministic, $0 diff of a
project's evidence state against a conversation's PER-QUESTION baselines (Kyle's correction: never against only
conversation_baseline(), which would hide an early question going stale behind a later, unrelated turn)."""
from __future__ import annotations

import json
import os
import time

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurosearch import cache, claims, conversation_delta as cd, db, evals, fake_ai, ingest, qa  # noqa: E402
from neurosearch.api import app  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    cache.invalidate()
    yield
    db._local.conn = None


def _golden():
    return evals.load_golden()["project_id"]


def _new_source(pid, title, text, *, tag="seller-financing-new-2026"):
    """A ready source with FTS-matchable text, added directly (no queue), mirroring how evals.load_golden works."""
    payload = {"platform": "youtube", "external_id": f"vid-{tag}-{time.time_ns()}", "url": f"https://youtu.be/{tag}",
              "title": title, "channel": "Test Channel", "published_at": "2026-09-18",
              "segments": [{"start": 0.0, "end": 30.0, "text": text}]}
    return ingest.store_transcript(payload, project_id=pid)["source_id"]


def test_whole_chat_scans_beyond_12_messages_and_excludes_refresh_turns():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    for i in range(14):
        qa.ask(f"Question number {i}: what kills deals in diligence?", project_id=pid, conversation_id=conv)
    # a synthetic refresh turn, inserted the way CHR3 will
    db.save_message(conv, "user", "Refresh: what's new since Sep 1 in this chat?", project_id=pid, meta={"kind": "refresh"})
    qs = cd._questions(conv)
    assert len(qs) == 14                               # every real question, not just the last 12
    assert all(q["question"].startswith("Question number") for q in qs)   # the refresh turn contributed nothing


def test_early_question_source_surfaces_through_a_later_unrelated_answer():
    """The semantic fix: an early question's staleness must not be hidden by a later, unrelated question that
    happens to postdate the new evidence and therefore wouldn't detect it on its own."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    q1_baseline_ts = cd._questions(conv)[0]["answered_at"]
    time.sleep(0.01)
    sid = _new_source(pid, "New seller financing terms video",
                      "Seller financing terms typically include a five year standby note with no payments in year one.")
    time.sleep(0.01)
    qa.ask("What accounting software should I use day to day?", project_id=pid, conversation_id=conv)   # unrelated, postdates the new source
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "exact"
    hit = next((u for u in delta["supporting_changes"] + delta["material_changes"] if u.get("source_id") == sid), None)
    assert hit is not None, "the new seller-financing source must surface even though only the LATER, unrelated question postdates it"
    touched_qids = {t["question_message_id"] for t in hit["touches_questions"]}
    q1_qid = cd._questions(conv)[0]["question_message_id"]
    assert q1_qid in touched_qids                        # attributed to the question it actually affects, not the newest one


def test_conversation_seen_chunks_are_never_flagged_as_new_excerpt():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    res = qa.ask("What are seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    shown = {h["chunk_id"] for h in res["hits"]}
    assert shown <= cd.conversation_seen_chunk_ids(conv)
    # nothing changed since — a delta run must not propose any of those chunks as "new"
    delta = cd.for_conversation(conv, pid)
    proposed_chunks = {cid for u in delta["supporting_changes"] for cid in (u.get("chunk_ids") or [])}
    assert not (proposed_chunks & shown)


def test_new_claim_evidence_on_old_source_reports_transition_from_last_known_state():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    baseline_ts = cd._questions(conv)[0]["answered_at"]
    c = claims.add_claim(pid, "Standby seller notes typically run five years with no payments in year one.", claim_type="market")
    time.sleep(0.01)
    claims.add_evidence(c["id"], sid, locator="1:00", excerpt="five year standby note")   # OLD source, new evidence, after baseline
    db.connect().execute("UPDATE project_claims SET strength='developing', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    delta = cd.for_conversation(conv, pid)
    unit = next((u for u in delta["material_changes"] + delta["supporting_changes"] if u.get("claim_id") == c["id"]), None)
    assert unit is not None
    assert unit["category"] in ("claim_transition", "plan_impact")
    assert unit["current_state"][0] == "developing"


def test_contradiction_ranks_above_corroboration():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    # both claims exist and carry evidence on the shown source BEFORE the baseline, so the baseline's claim_state
    # snapshot actually knows their prior state (a corroboration needs a KNOWN prior state to be distinguishable
    # from "new information" — plan §3: transitions are judged against what the conversation was told).
    corroborated = claims.add_claim(pid, "Seller notes are typically subordinated to the bank loan.", claim_type="market")
    claims.add_evidence(corroborated["id"], sid, locator="2:00", excerpt="subordinated note")
    contested = claims.add_claim(pid, "Seller notes are never subordinated.", claim_type="market")
    claims.add_evidence(contested["id"], sid, locator="3:00", excerpt="never subordinated")
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are seller financing subordination terms typically offered?", project_id=pid, conversation_id=conv)
    baseline_claim_state = cd._questions(conv)[0]["claim_state"]
    assert corroborated["id"] in baseline_claim_state and contested["id"] in baseline_claim_state
    time.sleep(0.01)
    claims.add_evidence(corroborated["id"], sid, locator="2:30", excerpt="subordination confirmed again")   # state unchanged: corroboration
    with db.tx() as conn:
        conn.execute("INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)", (db.new_id(), pid, "CONTRADICTION", contested["id"], "subordination disagreement", "open", db.now(), db.now()))
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    cats_by_claim = {u.get("claim_id"): u["category"] for u in all_units if u.get("claim_id")}
    assert cats_by_claim.get(contested["id"]) == "contradicts"
    assert cats_by_claim.get(corroborated["id"]) == "corroborates"
    order = [u["category"] for u in delta["material_changes"] + delta["supporting_changes"]]
    assert order.index("contradicts") < order.index("corroborates")


def test_known_false_plan_impact_stays_unknown_never_a_guess():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    c = claims.add_claim(pid, "Seller notes typically run five years.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="1:30", excerpt="five years")
    db.connect().execute("UPDATE project_claims SET strength='developing', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    delta = cd.for_conversation(conv, pid)   # no plan exists for this project at all
    unit = next(u for u in delta["material_changes"] + delta["supporting_changes"] if u.get("claim_id") == c["id"])
    assert unit["category"] != "plan_impact"
    if "plan_impact" in unit:
        assert unit["plan_impact"]["known"] is False and "reason" in unit["plan_impact"]


def test_irrelevant_new_source_is_counted_not_material():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    delta = cd.for_conversation(conv, pid)
    assert delta["irrelevant_new_source_count"] >= 1
    assert not any("lasagna" in json.dumps(u) for u in delta["material_changes"] + delta["supporting_changes"])


def test_nothing_new_makes_zero_provider_and_embedding_calls(monkeypatch):
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    from neurosearch import embeddings, providers
    monkeypatch.setattr(providers, "invoke", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("provider called")))
    monkeypatch.setattr(embeddings, "embed_query", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("embed called")))
    delta = cd.for_conversation(conv, pid)
    assert delta["nothing_new"] is True


def test_search_fts_never_calls_embeddings_even_when_enabled(monkeypatch):
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    assert settings.embeddings_enabled is True    # the fixture's fake_ai=True already turns this on
    from neurosearch import embeddings
    monkeypatch.setattr(embeddings, "embed_query", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("embed called")))
    from neurosearch.search import search_fts
    hits = search_fts("seller financing standby note", source_ids=[sid])
    assert isinstance(hits, list)   # ran to completion without ever calling embed_query


def test_second_identical_delta_request_is_a_cache_hit():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    from neurosearch import perf
    perf.reset()
    cd.get_delta(conv, pid)
    cd.get_delta(conv, pid)
    caches = perf.snapshot()["caches"]
    assert caches.get("conversation_delta", {}).get("hit", 0) >= 1


def test_unrelated_job_churn_does_not_move_the_revision():
    pid = _golden()
    rev1 = db.conversation_delta_revision(pid)
    with db.tx() as conn:
        conn.execute("INSERT INTO jobs (id, kind, status, payload, created_at, updated_at, lane) VALUES (?,?,?,?,?,?,?)",
                    (db.new_id(), "harvest_claims", "queued", "{}", db.now(), db.now(), "normal"))
    rev2 = db.conversation_delta_revision(pid)
    assert rev1 == rev2


def test_another_projects_changes_cannot_appear():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    other_pid = db.create_project("Other project", "unrelated")["id"]
    db.add_project_note(other_pid, "Seller financing terms typically include a five year standby note.", [])
    c = claims.add_claim(other_pid, "Seller notes are typically five years.", claim_type="market")
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("claim_id") == c["id"] for u in delta["material_changes"] + delta["supporting_changes"])
    assert not any("standby note" in json.dumps(u) for u in delta["material_changes"] + delta["supporting_changes"])


def test_legacy_conversation_with_no_snapshots_is_approximate():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[], project_id=pid, meta={"generation": {}})
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "approximate"


def test_mixed_old_and_new_conversation_reports_mixed_mode():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[], project_id=pid, meta={"generation": {}})
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "mixed"


def test_delta_endpoint_smoke():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    client = TestClient(app)
    r = client.get(f"/api/conversations/{conv}/delta", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"mode", "nothing_new", "questions_checked", "material_changes", "supporting_changes",
                        "irrelevant_new_source_count", "plan_impacts"}
    assert client.get("/api/conversations/does-not-exist/delta", headers=H).status_code == 404
