"""CHR1 (docs/CHAT-REFRESH-PLAN.md §3, §5-§7, §11, §14): Conversation Delta — the deterministic, $0 diff of a
project's evidence state against a conversation's PER-QUESTION baselines (Kyle's correction: never against only
conversation_baseline(), which would hide an early question going stale behind a later, unrelated turn)."""
from __future__ import annotations

import json
import os
import threading
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
    # Long and non-referential (>12 words, no "that/this/it/..." backreference) on purpose: qa.ask's own
    # short-follow-up grounding (Kyle's 2026-09-18 qa.py fix) would otherwise legitimately pull Q1's seller-
    # financing context into Q2's retrieval and mark the new source's chunk as already shown — which is correct
    # behavior, just not what this fixture is testing. This wording keeps Q2 genuinely unrelated and ungrounded.
    qa.ask("For a totally different topic, what accounting software packages are recommended for day to day "
          "small business bookkeeping and expense tracking?", project_id=pid, conversation_id=conv)   # unrelated, postdates the new source
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


def test_new_claim_created_after_baseline_reports_new_claim_not_a_fabricated_transition():
    """Kyle's correction (2026-09-18, part B): a Claim with no entry in THIS question's own claim_state has no
    known prior state to compare against — it is new to this answer, never a fabricated "changed from None"
    claim_transition. This Claim's evidence touches the OLD/shown source, so it is still relevant and still
    surfaces — just under the honest category."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    c = claims.add_claim(pid, "Standby seller notes typically run five years with no payments in year one.", claim_type="market")
    time.sleep(0.01)
    claims.add_evidence(c["id"], sid, locator="1:00", excerpt="five year standby note")   # OLD source, new evidence, after baseline
    db.connect().execute("UPDATE project_claims SET strength='developing', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    delta = cd.for_conversation(conv, pid)
    unit = next((u for u in delta["material_changes"] + delta["supporting_changes"] if u.get("claim_id") == c["id"]), None)
    assert unit is not None
    assert unit["category"] in ("new_claim", "plan_impact")
    assert unit["current_state"][0] == "developing"
    assert unit["previous_state"] is None


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


def test_cache_invalidates_when_the_conversation_gains_a_new_turn_not_just_project_state():
    """Kyle's fix #1: conversation_delta_revision() tracks the PROJECT, not this conversation. A new successful
    question/answer with no project-level change must still invalidate the cached delta."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    d1 = cd.get_delta(conv, pid)
    d2 = cd.get_delta(conv, pid)
    assert d1 == d2 and d1["questions_checked"] == 1                # identical second read: cache hit, same answer
    qa.ask("What multiple is fair for a service business?", project_id=pid, conversation_id=conv)   # no project-state change
    d3 = cd.get_delta(conv, pid)
    assert d3["questions_checked"] == 2                              # must reflect the new turn, not the stale cached value
    d4 = cd.get_delta(conv, pid)
    assert d4 == d3                                                  # settles back into a cache hit


def test_exact_mode_routes_on_the_stored_retrieval_query_not_the_raw_followup():
    """Kyle's fix #2: a bare follow-up like 'What about taxes?' retrieves badly on its own words. CHR0 already
    grounds it via qa._retrieval_query (prepending the prior question); CHR1 must use that stored string, not
    q['question'], or a contextual follow-up silently loses its topic."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("How does SBA seller financing work for a service business acquisition?", project_id=pid, conversation_id=conv)
    q2 = "What about taxes?"     # unanswerable on its own words against seller-financing-tax content
    qa.ask(q2, project_id=pid, conversation_id=conv)
    stored_rq = cd._questions(conv)[1]["retrieval_query"]
    assert stored_rq != q2 and "seller financing" in stored_rq.lower()   # grounded by the prior question, as qa.ask built it
    # Deliberately avoids the literal word "tax"/"taxes" so the raw follow-up ("What about taxes?") cannot FTS-match
    # it at all — only the grounded query (carrying "seller financing" / "service business acquisition") can.
    sid = _new_source(pid, "Structuring seller financing payouts",
                      "Structuring seller financing for a service business acquisition changes how the deferred "
                      "payments are treated: installment sale rules let the seller defer capital gains recognition, "
                      "and the buyer can deduct interest on the seller note against acquisition income.")
    from neurosearch.search import search_fts
    raw_hits = search_fts(q2, source_ids=[sid])
    grounded_hits = search_fts(stored_rq, source_ids=[sid])
    assert not raw_hits and grounded_hits, "the raw follow-up must miss this source while the grounded query finds it"
    delta = cd.for_conversation(conv, pid)
    hit = next((u for u in delta["supporting_changes"] + delta["material_changes"] if u.get("source_id") == sid), None)
    assert hit is not None, "CHR1 must have used the stored retrieval_query, not the raw 'What about taxes?'"


def test_legacy_question_reconstructs_the_retrieval_query_from_history():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "How does SBA seller financing work for a service business acquisition?", project_id=pid)
    db.save_message(conv, "assistant", "an old legacy answer with no evidence snapshot", citations=[], project_id=pid, meta={"generation": {}})
    db.save_message(conv, "user", "What about taxes?", project_id=pid)
    db.save_message(conv, "assistant", "another legacy answer", citations=[], project_id=pid, meta={"generation": {}})
    qs = cd._questions(conv)
    assert qs[1]["mode"] == "approximate"
    assert qs[1]["retrieval_query"] != "What about taxes?" and "seller financing" in qs[1]["retrieval_query"].lower()


def test_metadata_only_update_does_not_surface_as_a_revised_source():
    """Kyle's fix #3: exact-mode 'revised source' detection must compare sources.revision, not updated_at — a
    title fix or status back-fill moves updated_at without touching the transcript."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    baseline = cd._questions(conv)[0]
    assert sid in baseline["scope_source_revisions"]                 # v3 snapshot recorded a real baseline revision
    time.sleep(0.01)
    db.upsert_source(platform="youtube", external_id=db.get_source(sid)["external_id"], title="A renamed title, metadata only")
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("source_id") == sid for u in delta["material_changes"] + delta["supporting_changes"]),         "a metadata-only write must not be mistaken for a re-transcription"


def test_real_retranscription_does_surface():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    ingest.store_transcript({
        "platform": "youtube", "external_id": db.get_source(sid)["external_id"], "url": db.get_source(sid)["url"],
        "title": db.get_source(sid)["title"], "replace": True,
        "segments": [{"start": 0.0, "end": 30.0, "text": "Newly re-transcribed: seller financing terms extend to seven years now."}],
    }, project_id=pid)
    delta = cd.for_conversation(conv, pid)
    assert any(u.get("source_id") == sid for u in delta["material_changes"] + delta["supporting_changes"]),         "a real re-transcription (a new sources.revision) must surface"


def test_pending_to_ready_source_surfaces():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    sid = _new_source(pid, "Just-ingested seller financing video",
                      "Seller financing standby terms: five years, no payments in year one, subordinated to the bank loan.")
    db.upsert_source(platform="youtube", external_id=db.get_source(sid)["external_id"], status="pending")   # simulate mid-ingest
    delta_while_pending = cd.for_conversation(conv, pid)
    assert not any(u.get("source_id") == sid for u in delta_while_pending["material_changes"] + delta_while_pending["supporting_changes"])
    db.upsert_source(platform="youtube", external_id=db.get_source(sid)["external_id"], status="ready")
    delta = cd.for_conversation(conv, pid)
    assert any(u.get("source_id") == sid for u in delta["material_changes"] + delta["supporting_changes"])


def test_old_globally_existing_source_attached_later_surfaces():
    """A source that existed in the user's library (another project, or unattached) BEFORE the baseline, with an
    old created_at, attached to THIS project only afterward — the case project_source_ids' set difference exists
    to catch, since the source's own timestamps predate the baseline and would never trip an updated_at check."""
    pid = _golden()
    other_pid = db.create_project("Another project", "unrelated")["id"]
    sid = _new_source(other_pid, "Pre-existing seller financing video",
                      "Seller financing standby structure: interest-only for eighteen months, then fully amortizing.")
    time.sleep(0.01)
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # source not yet attached here
    time.sleep(0.01)
    db.add_project_sources(pid, [sid])   # attached to THIS project after the baseline; the source's own created_at is old
    delta = cd.for_conversation(conv, pid)
    assert any(u.get("source_id") == sid for u in delta["material_changes"] + delta["supporting_changes"]),         "an old, globally-existing source attached to this project after the baseline must surface"


def test_approximate_mode_rolls_up_unproven_claim_churn_instead_of_flooding_material_changes():
    """Kyle's fix (2026-09-18): prev=None in Approximate mode means UNKNOWN, not "this is a transition." A legacy
    chat's ordinary post-baseline Claim activity — no tension, no plan citation — must not turn into an explicit
    claim_transition unit per Claim; it belongs in `rollups`, counted, never individually enumerated."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    ordinary_ids = []
    for i in range(12):
        c = claims.add_claim(pid, f"Ordinary post-baseline claim {i} about seller financing.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"ordinary evidence {i}")
        ordinary_ids.append(c["id"])
    tense = claims.add_claim(pid, "Seller notes are never subordinated.", claim_type="market")
    claims.add_evidence(tense["id"], sid, locator="9:00", excerpt="never subordinated")
    with db.tx() as conn:
        conn.execute("INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)", (db.new_id(), pid, "CONTRADICTION", tense["id"], "subordination disagreement", "open", db.now(), db.now()))
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "approximate"
    all_units = delta["material_changes"] + delta["supporting_changes"]
    surfaced_claim_ids = {u.get("claim_id") for u in all_units if u.get("claim_id")}
    assert tense["id"] in surfaced_claim_ids                          # the provable signal (contradiction) still surfaces
    assert not (set(ordinary_ids) & surfaced_claim_ids)                # the unproven churn does NOT flood material/supporting
    assert delta["rollups"] is not None
    assert delta["rollups"]["claims_added_or_updated"] >= len(ordinary_ids)
    assert delta["nothing_new"] is False
    assert delta["approximate_limitations"]


def test_approximate_mode_plan_impacting_claim_still_surfaces_explicitly():
    """A legacy chat's Claim that decision_impact() can PROVE affects the current plan is not rolled up — it's the
    one Claim-level signal Approximate mode can make explicitly without a historical claim_state snapshot."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    from neurosearch import decision_impact as _di
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    c = claims.add_claim(pid, "Post-baseline claim that the plan cites.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="4:00", excerpt="plan-relevant evidence")
    real_di = _di.decision_impact
    import neurosearch.conversation_delta as cd_mod
    def fake_di(project_id, claim_ids=None):
        out = real_di(project_id, claim_ids)
        for cid in out:
            if cid == c["id"]:
                out[cid]["plan_impact"] = True
        return out
    import unittest.mock
    with unittest.mock.patch("neurosearch.decision_impact.decision_impact", side_effect=fake_di):
        delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] for u in all_units)


def _insert_target(pid, question, *, claim_id=None, status="satisfied", created_at=None, updated_at=None):
    t = updated_at if updated_at is not None else db.now()
    c = created_at if created_at is not None else t   # default: created now too (created-after-baseline pattern)
    tid = db.new_id()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO project_evidence_targets (id, project_id, question, topic, claim_id, sufficiency, "
            "preferred_classes, closure, closure_rule, status, origin, gap, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tid, pid, question, "topic", claim_id, "corroborative", "[]", "closure", "{}", status, "system",
             None, c, t))
    return tid


def _insert_tension(pid, claim_id, created_at=None):
    t = created_at if created_at is not None else db.now()
    tid = db.new_id()
    with db.tx() as conn:
        conn.execute("INSERT INTO research_tensions (id, project_id, kind, claim_id, description, status, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)", (tid, pid, "CONTRADICTION", claim_id, "disagreement", "open", t, t))
    return tid


# --- Kyle's second correction (2026-09-18): topical relevance gate for contradicts/resolves_gap in Approximate mode ---
# "important to the project is not automatically important to this conversation." Approximate mode must connect a
# contradiction or resolved gap to THIS chat via a demonstrable signal (cited source, or topical overlap on the
# grounded retrieval_query) before it becomes an explicit material_changes unit; otherwise it is real project
# activity but not something this legacy conversation can honestly be told changed its understanding.

def test_gate1_unrelated_contradiction_is_not_material_in_approximate_mode():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    other_sid = _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    c = claims.add_claim(pid, "The recipe calls for fresh basil and ricotta cheese.", claim_type="market")
    claims.add_evidence(c["id"], other_sid, locator="0:05", excerpt="basil and ricotta")
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert not any(u.get("claim_id") == c["id"] for u in all_units)


def test_gate2_contradiction_on_claim_matching_retrieval_query_is_material():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    other_sid = _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "What are typical seller financing standby note terms?", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    c = claims.add_claim(pid, "Seller financing notes typically carry a five year standby term.", claim_type="market")
    claims.add_evidence(c["id"], other_sid, locator="0:05", excerpt="unrelated evidence source")   # NOT the cited source
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "approximate"
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] and u["category"] == "contradicts" for u in all_units)


def test_gate3_contradiction_on_cited_source_is_material_despite_weak_text_overlap():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    c = claims.add_claim(pid, "The video creator prefers oat milk in their morning coffee.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="0:05", excerpt="oat milk aside")   # evidence on the CITED source
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "approximate"
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] and u["category"] == "contradicts" for u in all_units)


def test_gate4_unrelated_resolved_target_is_not_material_in_approximate_mode():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    tid = _insert_target(pid, "What is the best pasta shape for lasagna?")
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert not any(u.get("target_id") == tid for u in all_units)


def test_gate5_resolved_target_matching_retrieval_query_is_material():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "What are typical seller financing standby note terms?", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    tid = _insert_target(pid, "What are typical seller financing standby note terms?")
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("target_id") == tid for u in all_units)


def test_gate6_resolved_target_linked_to_relevant_claim_is_material_despite_weak_target_text_overlap():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    c = claims.add_claim(pid, "Seller financing notes typically carry a five year standby term.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="0:05", excerpt="five year standby")
    tid = _insert_target(pid, "unrelated wording that shares nothing with the question", claim_id=c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("target_id") == tid for u in all_units)


def test_gate7_plan_impacting_claim_unrelated_to_chat_is_not_material():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    other_sid = _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    from neurosearch import decision_impact as _di
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "an old question with no evidence snapshot", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[{"source_id": sid}], project_id=pid, meta={"generation": {}})
    time.sleep(0.01)
    c = claims.add_claim(pid, "The recipe calls for fresh basil and ricotta cheese.", claim_type="market")
    claims.add_evidence(c["id"], other_sid, locator="0:05", excerpt="basil and ricotta")
    real_di = _di.decision_impact
    def fake_di(project_id, claim_ids=None):
        out = real_di(project_id, claim_ids)
        for cid in out:
            if cid == c["id"]:
                out[cid]["plan_impact"] = True
        return out
    import unittest.mock
    with unittest.mock.patch("neurosearch.decision_impact.decision_impact", side_effect=fake_di):
        delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert not any(u.get("claim_id") == c["id"] for u in all_units)


def test_gate8_exact_mode_contradiction_and_resolved_gap_behavior_stays_unfiltered():
    """Do not weaken Exact mode: it has a real historical claim_state/scope snapshot, so `touched` there is already
    only what the answer could know — the new Approximate-only relevance gate must not narrow it further."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    c = claims.add_claim(pid, "The video creator prefers oat milk in their morning coffee.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="0:05", excerpt="oat milk aside")
    _insert_tension(pid, c["id"])
    tid = _insert_target(pid, "unrelated wording that shares nothing with the question", claim_id=c["id"])
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "exact"
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] and u["category"] == "contradicts" for u in all_units)
    assert any(u.get("target_id") == tid for u in all_units)


# --- Kyle's THIRD correction (2026-09-18): resolves_gap target-status honesty, per-question Claim baselines,
# Exact-mode relevance narrowing, and "seen elsewhere" annotation instead of silent drop. ---

def test_gateA1_dropped_target_after_baseline_is_not_resolves_gap():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are typical seller financing standby note terms?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="dropped")
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateA2_closed_by_user_target_is_not_resolves_gap():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are typical seller financing standby note terms?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="closed_by_user")
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateA3_target_open_in_v4_baseline_and_satisfied_afterward_surfaces():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="open")
    qa.ask("What are typical seller financing standby note terms?", project_id=pid, conversation_id=conv)
    ev = cd._questions(conv)[0]
    assert ev["open_evidence_target_ids"] is not None and tid in ev["open_evidence_target_ids"]
    time.sleep(0.01)
    with db.tx() as conn:
        conn.execute("UPDATE project_evidence_targets SET status='satisfied', updated_at=? WHERE id=?", (db.now(), tid))
    delta = cd.for_conversation(conv, pid)
    assert any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateA4_already_satisfied_before_baseline_does_not_surface_as_newly_resolved():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are typical seller financing standby note terms?", project_id=pid, conversation_id=conv)
    since = cd._questions(conv)[0]["answered_at"]
    # inserted AFTER the baseline read but BACKDATED to before it, and only after qa.ask() has already run its own
    # target assessment for this question -- avoids qa.ask's own evidence-target reassessment machinery touching
    # a target that already existed at ask time (an unrelated side effect, not part of what this gate tests).
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="satisfied",
                         created_at=since - 1000, updated_at=since - 1000)
    ev = cd._questions(conv)[0]
    assert tid not in (ev["open_evidence_target_ids"] or set())   # was already satisfied, never "open" at baseline
    time.sleep(0.01)
    with db.tx() as conn:   # touched later (e.g. gap notes re-assessed) without ever re-opening
        conn.execute("UPDATE project_evidence_targets SET updated_at=? WHERE id=?", (db.now(), tid))
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateA5_target_created_and_satisfied_after_exact_baseline_surfaces():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are typical seller financing standby note terms?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="satisfied")
    delta = cd.for_conversation(conv, pid)
    assert any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateA6_approximate_baseline_never_fabricates_resolution_from_updated_at_alone():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    db.save_message(conv, "user", "What are typical seller financing standby note terms?", project_id=pid)
    db.save_message(conv, "assistant", "an old answer", citations=[], project_id=pid, meta={"generation": {}})
    before = db.now()
    tid = _insert_target(pid, "What are typical seller financing standby note terms?", status="satisfied",
                         created_at=before - 1000, updated_at=before - 1000)   # already satisfied BEFORE the baseline
    time.sleep(0.01)
    with db.tx() as conn:   # touched again after the baseline, but never re-opened -- updated_at alone must not fabricate a resolution
        conn.execute("UPDATE project_evidence_targets SET updated_at=? WHERE id=?", (db.now(), tid))
    delta = cd.for_conversation(conv, pid)
    assert not any(u.get("target_id") == tid for u in delta["material_changes"] + delta["supporting_changes"])


def test_gateB_earlier_questions_claim_transition_is_not_erased_by_a_later_questions_snapshot():
    """Kyle's correction (2026-09-18, part B): prev must come from THIS question's own claim_state, never from
    conversation_last_known_claim_state() (the latest state seen anywhere), or an earlier question's real A->B
    transition disappears once a later question's snapshot happens to record the post-change state B."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    c = claims.add_claim(pid, "Seller notes typically run five years.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="1:00", excerpt="five years")
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # Q1
    q1 = cd._questions(conv)[0]
    q1_id, state_a = q1["question_message_id"], q1["claim_state"][c["id"]]
    time.sleep(0.01)
    db.connect().execute("UPDATE project_claims SET strength='strong', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    time.sleep(0.01)
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # Q2, same topic -> re-cites sid, its own snapshot now records state B
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    unit = next((u for u in all_units if u.get("claim_id") == c["id"]), None)
    assert unit is not None, "Q1's A->B transition must not disappear"
    assert unit["category"] in ("claim_transition", "plan_impact")
    assert unit["previous_state"] == state_a          # compared against Q1's OWN baseline, not Q2's later state
    assert unit["current_state"][0] == "strong"
    assert any(t["question_message_id"] == q1_id for t in unit["touches_questions"])


def test_gateE1_single_question_transition_is_not_flagged_seen_elsewhere():
    """Kyle's fifth correction (2026-09-18): already_seen_elsewhere_in_chat must mean ANOTHER successful answer in
    this conversation recorded the resulting state -- not "some snapshot, including this very answer's own." A
    single-question conversation has no "elsewhere" at all."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    c = claims.add_claim(pid, "Seller notes typically run five years.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="1:00", excerpt="five years")
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # only question
    time.sleep(0.01)
    db.connect().execute("UPDATE project_claims SET strength='strong', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    unit = next((u for u in all_units if u.get("claim_id") == c["id"]), None)
    assert unit is not None
    assert unit["already_seen_elsewhere_in_chat"] is False


def test_gateE2_transition_seen_by_a_later_question_is_flagged_seen_elsewhere():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    c = claims.add_claim(pid, "Seller notes typically run five years.", claim_type="market")
    claims.add_evidence(c["id"], sid, locator="1:00", excerpt="five years")
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # Q1
    time.sleep(0.01)
    db.connect().execute("UPDATE project_claims SET strength='strong', updated_at=? WHERE id=?", (db.now(), c["id"]))
    db.connect().commit()
    time.sleep(0.01)
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # Q2, independently re-records the new state
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    unit = next((u for u in all_units if u.get("claim_id") == c["id"]), None)
    assert unit is not None
    assert unit["already_seen_elsewhere_in_chat"] is True


def test_gateF1_large_new_claim_population_is_capped_and_totaled():
    """Kyle's final correction (2026-09-18, item 2): new_claim is real but low-priority -- an automatically-opened
    Exact chat must not receive thousands of nearly-identical objects for it. A large population of newly-relevant
    Claims collapses to a small explicit sample plus an exact total, never silently dropped."""
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    for i in range(20):
        c = claims.add_claim(pid, f"Newly relevant seller financing detail number {i}.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"detail {i}")
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    new_claim_units = [u for u in all_units if u["category"] == "new_claim"]
    assert len(new_claim_units) <= 5
    assert delta["new_claims"] == {"total": 20, "shown": len(new_claim_units)}
    assert delta["new_claims"]["shown"] == 5


def test_gateF4_new_claim_ranking_is_deterministic_across_identical_runs():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    for i in range(20):
        c = claims.add_claim(pid, f"Newly relevant seller financing detail number {i}.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"detail {i}")
    d1 = cd.for_conversation(conv, pid)
    d2 = cd.for_conversation(conv, pid)
    ids1 = [u["claim_id"] for u in d1["material_changes"] + d1["supporting_changes"] if u["category"] == "new_claim"]
    ids2 = [u["claim_id"] for u in d2["material_changes"] + d2["supporting_changes"] if u["category"] == "new_claim"]
    assert ids1 == ids2 and ids1   # same explicit sample, same order, both runs


def test_gateF5_nothing_new_is_false_when_only_rolled_up_new_claims_exist():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    for i in range(3):   # below the cap -- none of this is about capping, just that it counts as "something new"
        c = claims.add_claim(pid, f"Newly relevant seller financing detail number {i}.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"detail {i}")
    delta = cd.for_conversation(conv, pid)
    assert delta["new_claims"]["total"] == 3
    assert delta["nothing_new"] is False


def test_gateF6_strong_categories_are_not_capped_by_the_new_claim_mechanism():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    tension_claim_ids = []
    for i in range(8):   # well above NEW_CLAIM_EXPLICIT_CAP
        c = claims.add_claim(pid, f"Seller financing disputed detail number {i}.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"disputed detail {i}")
        _insert_tension(pid, c["id"])
        tension_claim_ids.append(c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    contradicts_ids = {u["claim_id"] for u in all_units if u["category"] == "contradicts"}
    assert set(tension_claim_ids) <= contradicts_ids   # every one surfaces -- contradicts is never rolled up/capped


def test_gateF7_new_claims_total_exceeds_shown_when_population_is_large():
    pid = _golden()
    sid = evals.load_golden()["sources"]["yt01"]
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    time.sleep(0.01)
    for i in range(20):
        c = claims.add_claim(pid, f"Newly relevant seller financing detail number {i}.", claim_type="market")
        claims.add_evidence(c["id"], sid, locator=f"{i}:00", excerpt=f"detail {i}")
    delta = cd.for_conversation(conv, pid)
    assert delta["new_claims"]["total"] == 20
    assert delta["new_claims"]["shown"] < delta["new_claims"]["total"]


def test_gateC1_exact_mode_contradiction_on_unrelated_newly_attached_source_does_not_surface():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    other_sid = _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    time.sleep(0.01)
    c = claims.add_claim(pid, "The recipe calls for fresh basil and ricotta cheese.", claim_type="market")
    claims.add_evidence(c["id"], other_sid, locator="0:05", excerpt="basil and ricotta")
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    assert delta["mode"] == "exact"
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert not any(u.get("claim_id") == c["id"] for u in all_units)


def test_gateC2a_fts_relevant_source_does_not_grant_relevance_to_an_unrelated_claims_evidence():
    """Kyle's fourth correction (2026-09-18): source-level topical relevance must not leak to a Claim whose OWN
    evidence excerpt on that source has nothing to do with the question -- a source can cover many topics. The
    Claim's evidence excerpt itself ("microphone brand mention") does not overlap the seller-financing query, even
    though the source it lives on does (via a different passage), so this contradiction must NOT surface."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    fts_sid = _new_source(pid, "Another seller financing video",
                          "This video covers seller financing standby note terms and typical structures in detail.")
    time.sleep(0.01)
    from neurosearch.search import search_fts
    assert search_fts("What are the seller financing terms typically offered?", source_ids=[fts_sid]), \
        "fixture sanity: the new source must be FTS-findable for this test to mean anything"
    c = claims.add_claim(pid, "The presenter recommends a specific microphone brand for recording.", claim_type="market")
    claims.add_evidence(c["id"], fts_sid, locator="0:05", excerpt="microphone brand mention")
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert not any(u.get("claim_id") == c["id"] for u in all_units)


def test_gateC2b_fts_relevant_source_grants_relevance_when_the_claims_own_evidence_excerpt_matches():
    """Same source-discovery shape as C2a, but this Claim's own evidence EXCERPT on the hit source is itself
    on-topic (even though the Claim's own text wording is weak/generic) -- evidence-level relevance, not mere
    source co-location, is what should let it surface."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    fts_sid = _new_source(pid, "Another seller financing video",
                          "This video covers seller financing standby note terms and typical structures in detail.")
    time.sleep(0.01)
    from neurosearch.search import search_fts
    assert search_fts("What are the seller financing terms typically offered?", source_ids=[fts_sid]), \
        "fixture sanity: the new source must be FTS-findable for this test to mean anything"
    c = claims.add_claim(pid, "Some structuring detail worth noting.", claim_type="market")   # weak/generic wording
    claims.add_evidence(c["id"], fts_sid, locator="0:10",
                        excerpt="seller financing standby note terms are typically five years")   # on-topic excerpt
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] and u["category"] == "contradicts" for u in all_units)


def test_gateC3_exact_mode_contradiction_on_claim_matching_retrieval_query_surfaces():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    other_sid = _new_source(pid, "Unrelated cooking video", "Today we are making a lasagna with fresh basil and ricotta.")
    time.sleep(0.01)
    c = claims.add_claim(pid, "Seller financing notes typically carry a five year standby term.", claim_type="market")
    claims.add_evidence(c["id"], other_sid, locator="0:05", excerpt="unrelated evidence source")
    _insert_tension(pid, c["id"])
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    assert any(u.get("claim_id") == c["id"] and u["category"] == "contradicts" for u in all_units)


def test_gateD_new_excerpt_seen_later_in_chat_still_associates_with_earlier_question():
    """Kyle's correction (2026-09-18, part D): dropping a chunk from new_excerpt just because a LATER question in
    the same chat also happened to show it repeats the whole-chat-baseline mistake -- it is still a genuine
    post-baseline change relevant to the EARLIER question. Annotate, never discard."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)   # Q1
    q1_id = cd._questions(conv)[0]["question_message_id"]
    new_sid = _new_source(pid, "New seller financing standby video",
                          "This new source discusses seller financing standby note structures extensively.")
    time.sleep(0.01)
    from neurosearch.search import search_fts
    hits = search_fts("What are the seller financing terms typically offered?", source_ids=[new_sid])
    assert hits, "fixture sanity: the new source must be FTS-findable for this test to mean anything"
    chunk_id = hits[0]["chunk_id"]
    # fabricate a later turn in the SAME conversation whose snapshot already shows this chunk (Q2)
    q2_id = db.save_message(conv, "user", "A second, later question in this same chat.", project_id=pid)
    db.save_message(conv, "assistant", "a later answer", citations=[{"source_id": new_sid}], project_id=pid, meta={
        "generation": {}, "evidence": {
            "v": cd.SNAPSHOT_VERSION, "complete": True, "answered_at": db.now(), "retrieval_query": "irrelevant to this test",
            "scope_source_ids": [], "scope_source_revisions": {}, "shown_chunk_ids": [chunk_id], "shown_source_ids": [new_sid],
            "full_context": False, "question_message_id": q2_id, "research_revision": None, "max_claim_evidence_id": None,
            "claim_state": {}, "open_evidence_target_ids": [],
        }})
    delta = cd.for_conversation(conv, pid)
    all_units = delta["material_changes"] + delta["supporting_changes"]
    hits_for_q1 = [u for u in all_units if u["kind"] == "new_excerpt" and u.get("source_id") == new_sid
                  and any(t["question_message_id"] == q1_id for t in u["touches_questions"])]
    assert hits_for_q1, "the excerpt from the new source must still be associated with Q1, not silently dropped"
    assert any(u.get("already_seen_elsewhere_in_chat") for u in hits_for_q1)


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


def test_refresh_is_explicit_delta_evidence_only_and_establishes_a_fresh_baseline(monkeypatch):
    """CHR3: the paid call gets the delta's selected new passage, not a second broad retrieval, and its synthetic
    user turn can never become another topic in the next delta."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    sid = _new_source(pid, "New seller financing terms video",
                      "Seller financing terms can include a five year standby note with no payments in year one.")
    expected = cd.refresh_evidence(conv, pid)
    assert expected["new_chunk_ids"], "fixture sanity: the delta must select a concrete new passage"
    monkeypatch.setattr(qa, "_hits_for", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("refresh re-searched the corpus")))
    before_claims = db.connect().execute("SELECT COUNT(*) n FROM project_claims WHERE project_id=?", (pid,)).fetchone()["n"]

    res = qa.refresh_conversation(conv, pid)
    assert res["answer"]
    rows = cd._rows(conv)
    refresh_user = next(r for r in rows if r["role"] == "user" and r["meta"].get("kind") == "refresh")
    refresh_answer = rows[-1]
    assert refresh_answer["role"] == "assistant"
    assert refresh_answer["meta"]["refresh"]["baseline_message_id"] is not None
    first_refresh_key = refresh_answer["meta"]["refresh"]["refresh_key"]
    assert refresh_answer["meta"]["evidence"]["complete"] is True
    shown_sources = set(refresh_answer["meta"]["evidence"]["shown_source_ids"])
    assert sid in shown_sources
    assert cd._questions(conv)[0]["question_message_id"] != refresh_user["id"]
    assert len(cd._questions(conv)) == 1
    after_claims = db.connect().execute("SELECT COUNT(*) n FROM project_claims WHERE project_id=?", (pid,)).fetchone()["n"]
    assert after_claims == before_claims, "a refresh response is not silently made into Claim evidence"
    # The original question's delta remains visible by design (it is the conversation's durable comparison
    # baseline), so admission needs an evidence identity rather than a timestamp/base-message heuristic.
    with pytest.raises(ValueError, match="no concrete new evidence"):
        qa.refresh_conversation(conv, pid)
    assert first_refresh_key


def test_refresh_key_changes_when_the_bounded_evidence_contract_changes():
    """The admission identity must be content-addressed: unchanged evidence blocks a repeat spend, while a
    distinct selected passage is eligible.  Supplying the deterministic delta directly isolates that contract
    from FTS ranking, which is intentionally allowed to select a bounded subset of many new sources."""
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    sid_a = _new_source(pid, "Seller financing one", "Seller financing terms include a five year standby note.", tag="refresh-key-a")
    sid_b = _new_source(pid, "Seller financing two", "Seller financing terms include a seven year standby note.", tag="refresh-key-b")
    cid_a = db.get_chunks(sid_a)[0]["id"]
    cid_b = db.get_chunks(sid_b)[0]["id"]
    first = {"material_changes": [{"kind": "new_excerpt", "category": "new_excerpt", "source_id": sid_a, "chunk_ids": [cid_a]}], "supporting_changes": []}
    second = {"material_changes": first["material_changes"] + [{"kind": "new_excerpt", "category": "new_excerpt", "source_id": sid_b, "chunk_ids": [cid_b]}], "supporting_changes": []}
    assert cd.refresh_evidence(conv, pid, first)["refresh_key"] != cd.refresh_evidence(conv, pid, second)["refresh_key"]


def test_refresh_evidence_drops_cross_project_chunks_even_if_a_bad_unit_names_them():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    other = db.create_project("Other project", "isolated")["id"]
    other_sid = _new_source(other, "Other seller source", "seller financing terms are unrelated to this project", tag="other-project")
    other_chunk = db.get_chunks(other_sid)[0]["id"]
    evidence = cd.refresh_evidence(conv, pid, {
        "material_changes": [{"source_id": other_sid, "chunk_ids": [other_chunk]}],
        "supporting_changes": [], "latest_activity_at": None,
    })
    assert evidence["new_chunk_ids"] == []


def test_refresh_endpoint_refuses_without_concrete_new_evidence():
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    client = TestClient(app)
    response = client.post(f"/api/conversations/{conv}/refresh", headers=H, json={})
    assert response.status_code == 409
    assert "no concrete new evidence" in response.json()["detail"].lower()


def test_refresh_admission_rejects_a_concurrent_second_click(monkeypatch):
    pid = _golden()
    conv = db.create_conversation(pid)["id"]
    qa.ask("What are the seller financing terms typically offered?", project_id=pid, conversation_id=conv)
    _new_source(pid, "New seller financing terms video",
                "Seller financing terms can include a five year standby note with no payments in year one.")
    entered, release = threading.Event(), threading.Event()

    def blocked_ask(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return {"answer": "done"}

    monkeypatch.setattr(qa, "ask", blocked_ask)
    first = threading.Thread(target=lambda: qa.refresh_conversation(conv, pid))
    first.start()
    assert entered.wait(2)
    with pytest.raises(ValueError, match="already refreshing"):
        qa.refresh_conversation(conv, pid)
    release.set()
    first.join(2)
    assert not first.is_alive()
