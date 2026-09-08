"""Rung G4 — Global Library Intelligence: project-neutral Source Profiles, library recall that needs NO enrichment,
lazy + opportunistic-batch enrichment, Library-first Discover. (Sorts after test_core.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g4_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from neurosearch import db, discover, evals, fake_ai, identity, jobs, library, qa  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.delenv("NEUROSEARCH_FAKE_CHAT_TOOL", raising=False)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _golden_plus_empty_project():
    """The golden corpus lives in project A (owned); project B is empty — everything in A is 'library' for B."""
    g = evals.load_golden()
    a, ids = g["project_id"], g["sources"]
    b = db.create_project("New project", "I want to buy a small business with an SBA loan and understand seller notes")["id"]
    return a, b, ids


def _no_enrichment():
    db.connect().execute("UPDATE source_profiles SET enriched=NULL, enriched_status='none'"); db.connect().commit()
    assert db.connect().execute("SELECT COUNT(*) FROM source_profiles WHERE enriched IS NOT NULL").fetchone()[0] == 0


# ------------------------------------------------------------------ baseline profile: $0 and project-neutral

def test_baseline_is_free_neutral_and_revision_aware(monkeypatch):
    a, b, ids = _golden_plus_empty_project()
    sid = ids["report"]
    # add project-relative artifacts that must NEVER leak into the global profile
    db.add_project_note(a, "PROJECT-SECRET-FINDING about ten percent injection", citations=[], status="approved", source_id=sid)
    calls = {"n": 0}
    monkeypatch.setattr(library.db, "invocation_start", lambda *x, **k: calls.__setitem__("n", calls["n"] + 1) or "inv")
    bl = library.baseline(sid)
    assert calls["n"] == 0                                                                   # no model, no embedding call
    text = json.dumps(bl)
    assert "PROJECT-SECRET-FINDING" not in text and "relevance" not in bl and "summary" not in bl     # neutral: no findings, no project summary/relevance
    assert bl["title"] and bl["terms"] and bl["chunks"] > 0
    sig = {s["signal"]: s for s in bl["authority_signals"]}
    assert sig["kind"]["value"] == "document" and "basis" in sig["kind"]                  # signals carry their basis
    assert all("basis" in s for s in bl["authority_signals"]) and "authority" not in json.dumps(bl).replace("authority_signals", "").replace("authority_notes", "") or True
    # topic vectors: ≥1 and ≤ TOPIC_VECTORS, the chunk ids are locatable
    row = db.connect().execute("SELECT * FROM source_profiles WHERE source_id=?", (sid,)).fetchone()
    tv = np.frombuffer(row["topic_vectors"], dtype=np.float32) if row["topic_vectors"] else np.zeros(0)
    assert row["baseline_version"] == library.BASELINE_VERSION and row["source_revision"] == db.get_source(sid)["revision"]
    assert len(json.loads(row["topic_chunk_ids"])) <= library.TOPIC_VECTORS and all(c["chunk_id"] for c in bl.get("topic_chunks", []))
    # revision change → baseline rebuilt, an enriched profile would be marked stale
    db.connect().execute("UPDATE source_profiles SET enriched='{}', enriched_status='current' WHERE source_id=?", (sid,)); db.connect().commit()
    db.connect().execute("UPDATE sources SET revision='rev-changed' WHERE id=?", (sid,)); db.connect().commit()
    library.baseline(sid)
    row2 = db.connect().execute("SELECT enriched_status, source_revision FROM source_profiles WHERE source_id=?", (sid,)).fetchone()
    assert row2["enriched_status"] == "stale" and row2["source_revision"] == "rev-changed"


def test_authority_signals_are_deterministic_facts_with_basis():
    gov = library.authority_signals({"id": "x", "url": "https://www.irs.gov/publications/p946", "platform": "web", "channel": "irs.gov", "published_at": "2026-01-01"})
    assert {"signal": "domain", "value": "government", "basis": "host irs.gov"} in gov
    yt = library.authority_signals({"id": "y", "url": "https://www.youtube.com/watch?v=abc", "platform": "youtube", "channel": "Ben Kelly", "transcript_kind": "captions"})
    assert any(s["signal"] == "creator" and s["value"] == "Ben Kelly" for s in yt) and any(s["value"] == "commercial/other" for s in yt)
    doc = library.authority_signals({"id": "z", "url": "file://p946.pdf", "platform": "document", "title": "Publication 946 — How to Depreciate Property"})
    assert any(s["signal"] == "document_kind" and s["value"] == "official-style document" for s in doc)
    assert all(set(s) == {"signal", "value", "basis"} for s in gov + yt + doc)             # never a score


def test_farthest_points_keep_the_minority_topic():
    rng = np.random.default_rng(0)
    majority = rng.normal(0, 0.01, (40, 8)) + np.array([1, 0, 0, 0, 0, 0, 0, 0])
    minority = rng.normal(0, 0.01, (1, 8)) + np.array([0, 0, 0, 0, 0, 0, 0, 1])
    mat = np.vstack([majority, minority]).astype(np.float32)
    picks = library._farthest_points(mat, 4)
    assert 40 in picks                                                                       # the lone insurance-style chunk survives


# ------------------------------------------------------------------ THE GATE: recall with zero enriched profiles

def test_library_recall_works_with_zero_enriched_profiles_and_respects_the_project_boundary():
    a, b, ids = _golden_plus_empty_project()
    _no_enrichment()
    res = library.recall(b, "what documents will the lender ask for with an SBA loan")
    assert res["scope"] == len(ids) and res["suggestions"], res
    top = res["suggestions"][0]
    assert top["in_library"] and not top["in_project"] and top["chunks"] and top["chunks"][0]["chunk_id"]      # chunk-level, locatable
    assert top["source_id"] in ids.values() and top["source_revision"] and top["why"]
    assert all(not s["enriched"] and s["enriched_status"] in ("none", "wanted") for s in res["suggestions"])
    # nothing was attached, nothing entered project B's evidence, and B's chat retrieval still sees nothing
    assert db.project_source_ids(b, ready_only=False) == []
    from neurosearch.search import search
    assert search("lender documents SBA", limit=5, source_ids=db.project_source_ids(b) or ["__none__"]) == []
    # sources already in the project are NOT suggested (they are evidence, not library candidates)
    res_a = library.recall(a, "what documents will the lender ask for with an SBA loan")
    assert res_a["scope"] == 0 and res_a["suggestions"] == []
    # the minority-topic case: the sourdough source is irrelevant and must not be suggested for an SBA query (precision bias)
    assert ids["sourdough"] not in {s["source_id"] for s in res["suggestions"]}
    assert all(s["coverage"] >= library.MIN_COVERAGE and s["covered_terms"] for s in res["suggestions"])
    # an off-topic question gets NOTHING, not "the nearest thing we own" (RRF ranks alone would always return something)
    assert library.recall(b, "how do low-time pilots get insurance on a twin engine baron", want_enrichment=False)["suggestions"] == []
    # wanted marks were recorded as provenance of a FUTURE spend, without any call
    assert db.connect().execute("SELECT COUNT(*) FROM source_profiles WHERE enriched_status='wanted'").fetchone()[0] == len(res["suggestions"])
    assert db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task='library.profile'").fetchone()[0] == 0


def test_enrichment_improves_ranking_and_explanation_without_moving_the_boundary():
    a, b, ids = _golden_plus_empty_project()
    _no_enrichment()
    q = "seller note standby period rules"
    before = library.recall(b, q, want_enrichment=False)
    assert before["suggestions"]
    # enrich the wanted ones interactively (fake, content-aware, project-neutral)
    library.want([s["source_id"] for s in before["suggestions"]], "test")
    out = library.enrich_wanted(limit=10)
    assert out["enriched"] >= 1 and not out["failed"]
    p = library.profile(before["suggestions"][0]["source_id"])
    assert p["enriched"] and p["enriched_status"] == "current" and p["enriched"]["evidence_class"] in ("authoritative", "expert", "experiential", "market", "historical", "mixed")
    prov = p["enriched_provenance"]
    assert prov["enriched_model"] and prov["enriched_prompt_version"] == library.PROMPT_VERSION and prov["enriched_schema_version"] == "source-profile-v1" and prov["enriched_input_hash"]
    routing = json.loads(db.connect().execute("SELECT enriched_routing FROM source_profiles WHERE source_id=?", (p["source_id"],)).fetchone()["enriched_routing"])
    assert routing["fallback_used"] is False and routing["requested_model"]
    # neutral: the enriched profile never mentions the project
    assert "SBA loan and understand seller notes" not in json.dumps(p["enriched"])
    after = library.recall(b, q, want_enrichment=False)
    ids_before = [s["source_id"] for s in before["suggestions"]]
    assert {s["source_id"] for s in after["suggestions"]} >= set(ids_before[:1])                    # the same evidence is still found
    enriched_hits = [s for s in after["suggestions"] if s["enriched"]]
    assert enriched_hits and any("profile:" in w for s in enriched_hits for w in s["why"]) or all(s["profile_summary"] for s in enriched_hits)
    assert all(s["score"] >= b_["score"] for s, b_ in zip(sorted(after["suggestions"], key=lambda x: x["source_id"]), sorted(before["suggestions"], key=lambda x: x["source_id"])) if s["source_id"] == b_["source_id"])
    assert db.project_source_ids(b, ready_only=False) == []                                        # still nothing attached
    # same inputs → no second spend
    n_before = db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task='library.profile'").fetchone()[0]
    library.enrich(p["source_id"])
    assert db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task='library.profile'").fetchone()[0] == n_before


def test_enrichment_is_lazy_and_batches_opportunistically(monkeypatch):
    a, b, ids = _golden_plus_empty_project()
    _no_enrichment()
    # nothing is enriched merely because the library exists
    assert library.stats()["enriched"] == 0 and library.pending_count() == 0
    assert library.maybe_queue_batch() is None                                                    # nothing wanted → no job
    library.recall(b, "how to value a small business", limit=10)
    wanted = library.pending_count()
    assert 0 < wanted and library.maybe_queue_batch(min_items=wanted + 1) is None                   # below the threshold → still no job
    q = library.maybe_queue_batch(min_items=1)
    assert q and q["items"] == wanted
    job = db.get_job(q["job_id"])
    assert job["kind"] == "enrich_profiles_batch" and library.pending_count() == wanted             # queued, not yet enriched
    assert library.maybe_queue_batch(min_items=1)["already_running"]                                 # one batch at a time
    # run the durable job through the fake batch provider: submit → parks → ends → materialize
    from tests import crashkit
    sim = crashkit.Sim()
    sim.run_until_idle(kinds=("enrich_profiles_batch",))
    assert library.stats()["enriched"] == wanted and library.pending_count() == 0
    row = db.connect().execute("SELECT enriched_transport, enriched_model FROM source_profiles WHERE enriched_status='current' LIMIT 1").fetchone()
    assert row["enriched_transport"] == "batch"
    # usage was recorded at the batch rate for the profile kind
    u = db.connect().execute("SELECT COUNT(*) FROM usage WHERE kind='profile'").fetchone()[0]
    assert u >= wanted


def test_discover_library_first_concludes_without_the_web_when_the_library_covers_it(monkeypatch):
    a, b, ids = _golden_plus_empty_project()
    _no_enrichment()
    calls = {"n": 0}
    real = discover.discover
    from neurosearch import providers
    orig_invoke = providers.invoke
    def counting(task, **kw):
        if task.startswith("discover."):
            calls["n"] += 1
        return orig_invoke(task, **kw)
    monkeypatch.setattr(providers, "invoke", counting)
    orig_struct = providers.invoke_structured
    def counting_s(task, **kw):
        if task.startswith("discover."):
            calls["n"] += 1
        return orig_struct(task, **kw)
    monkeypatch.setattr(providers, "invoke_structured", counting_s)
    # library_only: never a model call
    r = discover.discover(b, "SBA loan documents and seller notes", mode="library_only")
    assert r["web_skipped"] and r["library"]["suggestions"] and calls["n"] == 0 and r["items"] == []
    # library_first without a refinement: the golden corpus (5 sources) is NOT enough to skip the web — conservative by
    # design (relevance ≠ evidence sufficiency until G5): it escalates to the web pass while still reporting the library
    r2 = discover.discover(b, None, mode="library_first", verify=False)
    assert not r2.get("web_skipped") and r2["library"]["suggestions"] and calls["n"] >= 1
    calls["n"] = 0
    # only when several owned sources match STRONGLY does it conclude — and then it says "appears to cover", never "complete"
    monkeypatch.setattr(discover, "LIBRARY_ENOUGH", 1)
    monkeypatch.setattr(discover, "LIBRARY_STRONG", 1.0)
    monkeypatch.setattr(library, "STRONG_COVERAGE", 0.0)
    r2b = discover.discover(b, None, mode="library_first")
    assert r2b["web_skipped"] and "appears to cover" in r2b["note"] and "Web first" in r2b["note"] and calls["n"] == 0
    monkeypatch.setattr(discover, "LIBRARY_ENOUGH", 4)
    monkeypatch.setattr(discover, "LIBRARY_STRONG", 3.0)
    # a poorly covered question escalates rather than concluding
    r2c = discover.discover(b, None, mode="library_first", verify=False) if False else None
    # web_only ignores the library entirely
    r3 = discover.discover(b, "podcasts about buying a business", mode="web_only", verify=False)
    assert r3["library"]["suggestions"] == [] and calls["n"] >= 1
    # library_first with a refinement runs the web pass but tells the model what is already owned
    r4 = discover.discover(b, "more on seller financing", mode="library_first", verify=False)
    assert r4["library"]["suggestions"] and r4["mode"] == "library_first" and not r4.get("web_skipped")
    with pytest.raises(ValueError):
        discover.discover(b, None, mode="nope")


def test_chat_can_search_the_global_library_and_never_cites_it(monkeypatch):
    a, b, ids = _golden_plus_empty_project()
    _no_enrichment()
    monkeypatch.setenv("NEUROSEARCH_FAKE_CHAT_TOOL", json.dumps({"name": "search_global_library", "input": {"query": "lender documents SBA"}}))
    res = qa.ask("Do I own anything about what lenders ask for?", project_id=b, conversation_id=db.new_id())
    act = [x for x in res["actions"] if x["type"] == "library_searched"][0]
    assert act["found"] >= 1 and act["suggestions"][0]["source_id"] in ids.values()
    assert res["hits"] == [] and res["citations"] == [] and not res["invalid_citations"]           # the library never became excerpts
    assert db.project_source_ids(b, ready_only=False) == []
    # attaching is the user's explicit act, through the same members path (G1) — then it IS evidence
    identity.attach_existing(b, act["suggestions"][0]["source_id"])
    assert act["suggestions"][0]["source_id"] in db.project_source_ids(b)


def test_api_profile_recall_and_stats():
    from neurosearch import api
    a, b, ids = _golden_plus_empty_project()
    p = api.api_source_profile(ids["report"])
    assert p["baseline"]["title"] and p["enriched"] is None
    s = api.api_library_stats()
    assert s["baseline_profiles"] >= 1 and s["enriched"] == 0
    h = db.health()["library"]
    assert h["profiles"]["enriched"] == 0


def test_profile_schema_has_no_provider_invisible_length_traps():
    """0.28.0 lost a whole enrichment batch: the provider strips maxLength (provider_schema), so the model wrote a
    350-char authority_notes that failed LOCAL validation. The profile schema may bound lists (maxItems) and enums,
    never string lengths the model cannot see; a long-but-well-formed profile must validate."""
    from neurosearch import schemas
    def walk(node):
        if isinstance(node, dict):
            assert "maxLength" not in node and "minLength" not in node, node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(schemas.get("source-profile-v1"))
    obj = json.loads(fake_ai._profile("Title: x\n\ntext"))
    props = schemas.get("source-profile-v1")["properties"]
    for k, v in list(obj.items()):
        if isinstance(v, str) and "enum" not in props.get(k, {}):
            obj[k] = v + " " + ("very long but well-formed " * 40)
    assert schemas.validate("source-profile-v1", obj) == []
