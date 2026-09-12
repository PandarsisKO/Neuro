"""Rung G5 — Knowledge Map, Claim graph, Evidence Targets, Research Tensions. Includes the FROZEN end-to-end acceptance
gate from the G5 lock (EXPANSION.md): a vague project with one current primary source, derivative secondaries, one
credible outlier, one stale source and one previously skipped Candidate. (Sorts after test_core.)"""
from __future__ import annotations

import json
import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g5_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import candidates, claims, db, discover, fake_ai, ingest, jobs, knowledge, qa, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402


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
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


SOP = ("When a seller note counts toward the required equity injection, the SBA SOP requires the seller note to be on full standby "
       "for the life of the SBA loan; no payments of principal or interest may be made during that period.")
STALE_TEXT = "Current SBA guarantee fee rates for fiscal year 2023 are 2 percent on loans under 150,000 dollars and 3 percent above that; these rates change every fiscal year."
OUTLIER = ("Keep the accounting-firm seller through two full tax seasons, about eighteen months, rather than the usual six to twelve month "
           "transition, because client retention in tax practices is decided in the first two filing seasons.")


def _transcript(ext: str, title: str, channel: str, text: str, published: str = "2026-05-01", platform: str = "youtube") -> str:
    words = text.split()
    segs, t = [], 0.0
    for i in range(0, len(words), 12):
        segs.append({"start": t, "end": t + 6.0, "text": " ".join(words[i:i + 12])}); t += 6.0
    r = ingest.store_transcript({"platform": platform, "external_id": ext, "url": f"https://www.youtube.com/watch?v={ext}" if platform == "youtube" else f"https://example.com/{ext}.mp3",
                                 "title": title, "channel": channel, "published_at": published, "segments": segs, "transcript_kind": "captions"})
    return r["source_id"]


def _page(url: str, title: str, body: str, published: str | None = None) -> str:
    html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p><p>Filler paragraph so the page has substance and a second section.</p></body></html>"
    r = ingest.ingest_webpage(url, html=html, title=title)
    if published:
        db.upsert_source(platform="web", external_id=db.get_source(r["source_id"])["external_id"], published_at=published)
    return r["source_id"]


def _note(pid: str, sid: str, text: str, snippet: str, importance: int = 3, locator: str = "0:00", start: float = 0.0, title: str | None = None):
    src = db.get_source(sid)
    n = db.add_project_note(pid, text + " [1]", citations=[{"n": 1, "source_id": sid, "title": src["title"], "url": src["url"], "link": src["url"], "timestamp": locator,
                                                          "start": start, "platform": src["platform"], "snippet": snippet}], status="approved", source_id=sid, importance=importance)
    if title:
        db.connect().execute("UPDATE project_notes SET title=? WHERE id=?", (title, n["id"])); db.connect().commit()
    return n


def _acceptance_fixture(monkeypatch):
    """The frozen G5 gate project. No network: safe_fetch is poisoned for the whole fixture."""
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    pid = db.create_project("Vague: buy an accounting practice", "I think I want to buy a small accounting practice with an SBA loan. Not sure what matters.")["id"]
    db.connect().execute("UPDATE projects SET questions=? WHERE id=?", (json.dumps(["What are the SBA rules on seller notes?", "How long should the seller stay on?"]), pid)); db.connect().commit()
    # 1 current primary source (government domain → authoritative)
    primary = _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8 — Lender and Development Company Loan Programs", SOP, published="2026-02-01")
    # 3 derivative secondaries: different creators, each repeating the SOP passage
    secs = [_transcript(f"deriv{i}", f"SBA seller note standby explained ({i})", f"Channel {i}", "Let me read you the rule. " + SOP + " That is what the SOP says.") for i in range(3)]
    # 1 credible outlier (single experiential source, high importance)
    outlier = _transcript("outlier1", "Buying a CPA practice: what I learned", "Practice Buyer Pod", OUTLIER, platform="media")
    # 1 stale source (fast-moving facts, three years old)
    stale = _page("https://www.lenderblog.example.com/sba-fees-2023", "SBA guarantee fees 2023", STALE_TEXT, published="2023-01-15")
    db.add_project_sources(pid, [primary, *secs, outlier, stale])
    # findings as the pipeline would have written them (approved)
    _note(pid, primary, SOP, SOP, importance=5, locator="§ 1", start=1, title="Seller note standby rule")
    for sid in secs:
        _note(pid, sid, SOP, "Let me read you the rule. " + SOP, importance=3, locator="0:06", start=6, title="Seller note standby rule")
    _note(pid, outlier, OUTLIER, OUTLIER, importance=5, locator="0:00", start=0, title="Seller transition length")
    _note(pid, stale, STALE_TEXT, STALE_TEXT, importance=4, locator="§ 1", start=1, title="Guarantee fee rates")
    # 1 previously skipped candidate that the new gap makes relevant
    cid = candidates.remember([{"external_id": "cand-transition", "url": "https://www.youtube.com/watch?v=cand-transition",
                                "title": "Seller transition after buying an accounting practice: how many tax seasons?",
                                "description": "Three buyers compare six-month, twelve-month and two-tax-season seller transitions", "creator": "CPA Deals",
                                "content_type": "video"}], "youtube", pid, {"kind": "channel", "title": "CPA Deals"})[0]
    candidates.mark(pid, [cid], "skipped_low_relevance", reason="ranked below the cut during exploration", relevance=35)
    return pid, {"primary": primary, "secs": secs, "outlier": outlier, "stale": stale, "candidate": cid}


def _by_text(pid: str, text: str) -> dict:
    return next(c for c in claims.list_for_project(pid) if text in c["text"])


def _calls(task: str) -> int:
    return db.connect().execute("SELECT COUNT(*) FROM invocations WHERE task=?", (task,)).fetchone()[0]


# ---------------------------------------------------------------- the frozen acceptance gate (10 points)

def test_g5_acceptance_gate_end_to_end(monkeypatch):
    pid, ids = _acceptance_fixture(monkeypatch)
    before = _calls("claims.extract")
    res = claims.ensure(pid)                       # $0 path: harvest + assess + map
    assert _calls("claims.extract") == before, "the $0 path must not call the extraction contract"
    gov = _by_text(pid, SOP)
    # (1) governing Claim Strong from ONE primary source
    assert gov["claim_type"] == "governing" and gov["strength"] == "strong", (gov["claim_type"], gov["strength"], gov["strength_why"])
    assert "governing sufficiency" in gov["strength_why"] and "1 authoritative source" in gov["strength_why"]
    # (2) the three repeats are folded in as DERIVATIVE evidence, not independent corroboration
    ev = gov["evidence"]
    assert len(ev) == 4 and sum(1 for e in ev if e["independent"]) == 1
    assert all(e["evidence_class"] == "derivative" for e in ev if e["source_id"] in ids["secs"])
    # (3) the outlier is a Research Tension / corroboration gap, not consensus
    out = _by_text(pid, OUTLIER)
    assert out["strength"] == "weak" and out["status"] == "proposed"
    tens = knowledge.list_tensions(pid)
    novel = [t for t in tens if t["kind"] == "NOVEL" and t["claim_id"] == out["id"]]
    assert novel and "additional corroboration recommended" in novel[0]["description"]
    corro = [t for t in knowledge.list_targets(pid) if t["claim_id"] == out["id"] and t["origin"] == "tension"]
    assert corro and corro[0]["sufficiency"] == "corroborative" and corro[0]["status"] == "open"
    # (4) the stale Claim is flagged by its CLAIM-relative freshness class — separately from evidence strength (G5.1)
    st = _by_text(pid, STALE_TEXT)
    assert st["freshness_class"] == "rates_pricing" and st["freshness_status"] == "stale", (st["freshness_class"], st["freshness_status"])
    assert st["strength"] == "weak" and "540 days" in st["freshness_why"]
    assert any(t["kind"] == "STALE" and t["claim_id"] == st["id"] for t in tens)
    # …while the experiential outlier from the same era would never stale by age, and the governing rule needs re-verification, not a stale verdict
    assert out["freshness_class"] == "experiential" and out["freshness_status"] == "age_insensitive"
    assert gov["freshness_class"] == "regulatory" and gov["freshness_status"] in ("current", "needs_refresh")
    # (5)+(6) pursuing the corroboration target: project → library → candidates (reranked, skipped one resurfaced) → external only on request; no network
    n_sources_before = len(db.project_source_ids(pid, ready_only=False))
    r = knowledge.pursue(corro[0]["id"], external=False)
    steps = [s["step"] for s in r["escalation"]["steps"]]
    assert steps == ["project_evidence", "global_library", "candidate_index", "external"]
    ci = r["escalation"]["steps"][2]
    assert ci["resurfaced"] >= 1 and any(c["id"] == ids["candidate"] and c["resurfaced"] for c in ci["candidates"])
    assert candidates.search(pid, "seller transition tax seasons")[0]["state"] == "available"
    assert r["escalation"]["steps"][3]["run"] is False
    # (7) nothing crossed the project boundary: no source attached, evidence only from project sources, candidates never evidence
    assert len(db.project_source_ids(pid, ready_only=False)) == n_sources_before
    proj = set(db.project_source_ids(pid, ready_only=False))
    for c in claims.list_for_project(pid):
        for e in c["evidence"]:
            assert e["source_id"] in proj
    assert db.connect().execute("SELECT COUNT(*) FROM claim_evidence e JOIN candidates c ON c.source_id=e.source_id").fetchone()[0] == 0
    # (8) every Claim traces to exact revision + locator
    for c in claims.list_for_project(pid):
        for e in c["evidence"]:
            assert e["source_revision"] and e["locator"], e
            assert e["source_revision"] == db.source_revision(e["source_id"])
    # (9) the map explains WHY — never a source count
    m = knowledge.refresh(pid)
    node = next(n for n in m["nodes"] if n["claims_strong"] >= 1)
    assert node["state"] in ("strong", "developing") and "governing sufficiency" in node["why"]
    assert not any(w in node["why"].lower() for w in ("4 sources", "four sources"))
    # (10) the hardened gates: nothing model-side ran, provenance rows carry task/created_at, health still opens
    assert _calls("claims.extract") == before
    assert all(e["task"] and e["created_at"] for c in claims.list_for_project(pid) for e in c["evidence"])
    assert db.health()["integrity"]["ok"] if isinstance(db.health().get("integrity"), dict) else True


# ---------------------------------------------------------------- policy tests

def test_claim_intelligence_is_lazy_debounced_and_idempotent(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    claims.harvest(pid)
    n = len(claims.unnormalized(pid))
    assert 0 < n < claims.CLAIMS_BATCH_MIN
    db.kv_set(f"claims:last_extract:{pid}", str(time.time()))
    assert claims.maybe_extract(pid, "test") is None                       # few candidates + recent extraction → no job
    db.kv_set(f"claims:last_extract:{pid}", "0")
    job = claims.maybe_extract(pid, "test")
    assert job and job["kind"] == "extract_claims" and db.dedupe_key_for("extract_claims", job["payload"]) == f"claims:{pid}"
    assert claims.maybe_extract(pid, "again")["id"] == job["id"]            # deduped while active
    before = _calls("claims.extract")
    res = claims.extract(pid)
    assert res["calls"] == 1 and res["normalized"] >= 1 and _calls("claims.extract") == before + 1
    assert claims.extract(pid)["calls"] == 0                                # same revision + contract + text → no second spend
    assert all(c["normalized"] for c in claims.list_for_project(pid) if c["status"] != "rejected")
    # proposed targets the user never named exist and are marked as proposed (origin model)
    assert any(t["origin"] == "model" for t in knowledge.list_targets(pid))
    # harvest is idempotent
    assert claims.harvest(pid) == {"created": 0, "merged": 0}


def test_harvest_after_findings_job_is_event_driven_not_per_finding(monkeypatch):
    pid, ids = _acceptance_fixture(monkeypatch)
    db.connect().execute("DELETE FROM project_claims"); db.connect().commit()
    jobs._after_done({"kind": "suggest_findings", "payload": {"project_id": pid}})
    assert len(claims.list_for_project(pid)) >= 3                            # harvested for $0
    assert _calls("claims.extract") == 0                                     # and no paid call was made for it
    active = db.connect().execute("SELECT COUNT(*) FROM jobs WHERE kind='extract_claims' AND status IN ('queued','running')").fetchone()[0]
    assert active <= 1


def test_strong_is_not_decision_ready_and_user_state_is_never_rewritten(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)
    gov = _by_text(pid, SOP)
    assert gov["strength"] == "strong" and gov["readiness"] == "not_ready" and "not established" in gov["readiness_why"]
    claims.set_status(gov["id"], "accepted", application="established")
    c = claims.get(gov["id"])
    assert c["status"] == "accepted" and c["readiness"] == "ready"
    claims.extract(pid)                                                      # the model pass must not touch user state
    c = claims.get(gov["id"])
    assert c["status"] == "accepted" and c["application"] == "established"
    claims.set_status(gov["id"], "rejected")
    knowledge.refresh(pid)
    assert claims.get(gov["id"])["status"] == "rejected"


def test_user_facts_are_not_claims_but_external_assertions_are(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    db.add_fact(pid, "constraint", "My maximum budget is $2 million")
    claims.ensure(pid)
    assert not any("budget" in c["text"].lower() for c in claims.list_for_project(pid))
    project = db.get_project(pid)
    actions: list = []
    out = qa._run_tool("propose_claim", {"text": "SBA 7(a) lets a buyer borrow up to $5 million for an acquisition", "claim_type": "governing"}, project, [], actions)
    assert "PROPOSED" in out and actions[-1]["type"] == "claim_proposed"
    c = claims.get(actions[-1]["claim_id"])
    assert c["status"] == "proposed" and c["strength"] == "unsupported" and c["origin"] == "chat"
    tg = knowledge.get_target(actions[-1]["target_id"])
    assert tg["sufficiency"] == "governing" and tg["closure_rule"]["primary_required"] is True
    # research_state tool is $0 and reports the map
    before = db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
    txt = qa._run_tool("research_state", {}, project, [], actions)
    assert "Knowledge Map" in txt and db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == before


def test_contradiction_checks_scope_before_conflict(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)
    a = claims.add_claim(pid, "Seller notes must be on full standby for the life of the loan", claim_type="governing", qualifiers={"jurisdiction": "US", "timeframe": "SOP 50 10 8"}, normalized=True)
    b = claims.add_claim(pid, "Seller notes only needed two years of standby", claim_type="governing", qualifiers={"jurisdiction": "US", "timeframe": "SOP 50 10 5"}, normalized=True)
    src = db.get_source(db.project_source_ids(pid)[0])
    claims.add_evidence(b["id"], src["id"], locator="§ 1", excerpt="two years of standby was the old rule")
    r = claims.relate(a["id"], b["id"], "CONTRADICTS")
    assert r["relation"] == "QUALIFIES" and r["scope_difference"] == "timeframe"
    c = claims.add_claim(pid, "Seller notes never need standby", claim_type="governing", qualifiers={"jurisdiction": "US", "timeframe": "SOP 50 10 8"}, normalized=True)
    claims.add_evidence(c["id"], src["id"], locator="§ 2", excerpt="standby is never required")
    r2 = claims.relate(a["id"], c["id"], "CONTRADICTS")
    assert r2["relation"] == "CONTRADICTS"
    assert any(t["kind"] == "CONTRADICTION" and t["claim_id"] == a["id"] for t in knowledge.list_tensions(pid))


def test_revision_change_stales_exactly_the_touched_evidence(monkeypatch):
    pid, ids = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)
    gov = _by_text(pid, SOP)
    assert gov["strength"] == "strong"
    # the primary page is re-read with different words → new revision → the primary evidence row goes stale
    _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8 — Lender and Development Company Loan Programs",
          "The standby requirement was revised: seller notes may now be on partial standby for twenty-four months when the lender approves.", published="2026-08-01")
    gov = claims.get(gov["id"])
    stale_rows = [e for e in gov["evidence"] if e["stale"]]
    assert [e["source_id"] for e in stale_rows] == [ids["primary"]]
    assert gov["strength"] != "strong" and "stale" in gov["strength_why"]
    others = [c for c in claims.list_for_project(pid) if c["id"] != gov["id"]]
    assert all(not e["stale"] for c in others for e in c["evidence"])


def test_discover_leads_with_research_state_and_api_surfaces(monkeypatch):
    import anyio
    from neurosearch import api
    pid, _ = _acceptance_fixture(monkeypatch)
    r = anyio.run(api.api_research_refresh, pid, api.ResearchRefreshIn(extract=False))
    assert r["harvested"] >= 3 and r["state"]["claim_stats"]["by_strength"].get("strong", 0) >= 1
    st = api.api_research(pid)
    # 0.63.8 — the endpoint no longer ships the claim ROWS by default: 300 of them were 546 KB of a 774 KB
    # response and no screen read the key (the workbench pages `…/claims` instead). What this gate is about — the
    # API surfaces the research state — is unchanged, and the rows are still one parameter away. Recorded in
    # HARDENING.md with the measurement.
    assert st["tensions"] and st["targets"] and st["claims_total"] >= 1 and st["claims"] == []
    assert api.api_research(pid, claims=True)["claims"]
    tg = api.api_target_add(pid, api.TargetIn(question="What do lenders require for the seller transition period?", sufficiency="corroborative"))
    p = anyio.run(api.api_target_pursue, tg["id"], api.PursueIn(external=False))
    assert [s["step"] for s in p["escalation"]["steps"]][:3] == ["project_evidence", "global_library", "candidate_index"]
    d = discover.discover(pid, mode="library_only")
    assert d["web_skipped"] and sum(d["research"]["counts"].values()) >= 1 and d["research"]["targets"]
    assert "Research coverage" in d["research"]["summary"]
    block = qa.research_block(pid)
    assert block.startswith("Research state") and "⚠" in block


def test_freshness_is_claim_relative_not_source_age(monkeypatch):
    """G5.1: one 2021 interview carries a stale rate, a still-current transition insight, a timeless anecdote and a rule that
    needs re-verification. The $0 heuristic errs toward `uncertain`, never a false stale."""
    pid, _ = _acceptance_fixture(monkeypatch)
    old = _transcript("old2021", "Buying a practice in 2021: full interview", "Old Pod", "An interview recorded in 2021 about buying a practice.", published="2021-03-01", platform="media")
    db.add_project_sources(pid, [old])
    rate = "SBA 7a interest rates were prime plus 2.75 percent, about 6 percent, in 2021 for acquisition loans."
    trans = "Keep the seller involved with clients through the first busy season; client retention depends on that relationship."
    anec = "When I bought my first firm in 2019 the seller stayed for eighteen months and every client stayed."
    rule = "The SBA SOP prohibits using the seller note for the equity injection unless it is on full standby."
    frame = "Always negotiate the transition terms before the price; the structure matters more than the multiple."
    vague = "The team was very good and the office was in a nice location."
    for i, tx in enumerate([rate, trans, anec, rule, frame, vague]):
        _note(pid, old, tx, tx, importance=4, locator=f"{i}:00", start=i * 60, title=f"Old interview point {i}")
    claims.ensure(pid)
    got = {tx: _by_text(pid, tx) for tx in [rate, trans, anec, rule, frame, vague]}
    assert got[rate]["freshness_class"] == "rates_pricing" and got[rate]["freshness_status"] == "stale"
    assert got[trans]["freshness_class"] == "experiential" and got[trans]["freshness_status"] == "age_insensitive"
    assert got[anec]["freshness_class"] == "historical" and got[anec]["freshness_status"] == "age_insensitive"
    assert got[rule]["freshness_class"] == "regulatory" and got[rule]["freshness_status"] == "needs_refresh" and "current version" in got[rule]["freshness_why"]
    assert got[frame]["freshness_class"] == "static" and got[frame]["freshness_status"] == "age_insensitive"
    assert got[vague]["freshness_status"] in ("uncertain", "age_insensitive")            # a lone observation from a 2021 talk is never "stale"
    assert claims.guess_freshness(vague, "other", "expert") == "uncertain"
    assert claims.freshness_status("uncertain", 4 * 365)[0] == "uncertain"                 # old + unclassifiable → uncertain, not stale
    assert all(c["strength"] != "stale" for c in got.values())            # strength never carries a temporal verdict any more
    stale_t = [t for t in knowledge.list_tensions(pid) if t["kind"] == "STALE"]
    assert any(t["claim_id"] == got[rate]["id"] for t in stale_t) and not any(t["claim_id"] == got[vague]["id"] for t in stale_t)
    # legacy 0.29.x classes read as the new ones
    db.connect().execute("UPDATE project_claims SET freshness_class='slow_changing' WHERE id=?", (got[trans]["id"],)); db.connect().commit()
    assert claims.get(got[trans]["id"])["freshness_class"] == "tactics"


def test_bounded_normalization_evaluation_is_durable_and_measured(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)
    cohort = claims.select_cohort(pid, budget=2)
    assert len(cohort["claim_ids"]) == 2 and cohort["candidates"] == 3
    assert "strong/developing" in cohort["by_reason"] and "tension" in cohort["by_reason"]
    before = _calls("claims.extract")
    rep = jobs.run_job({"id": "j", "kind": "extract_claims", "payload": {"project_id": pid, "evaluation": True, "budget": 2}})
    assert rep["cohort"]["size"] == 2 and rep["calls"] == 1 and _calls("claims.extract") == before + 1
    assert rep["normalized"] >= 1 and rep["hedges_kept"] == rep["hedged_before"] and rep["over_generalized"] == []
    full = claims.evaluation_report(pid)
    assert full and len(full["rows"]) == 2 and all(r["after"] for r in full["rows"])
    # the rest of the corpus stayed unnormalized: the evaluation never becomes corpus-wide normalization
    assert len(claims.unnormalized(pid)) == 1
    # a rerun picks up only what is still unnormalized; with nothing left it spends nothing
    assert claims.run_evaluation(pid, budget=2)["cohort"]["size"] == 1
    assert claims.run_evaluation(pid, budget=2)["calls"] == 0


def test_normalization_evaluation_resumes_the_same_cohort_after_a_failure(monkeypatch):
    """A truncated call mid-way (0.30.1, real library) must not lose the before-snapshot or re-spend on normalized claims."""
    pid, _ = _acceptance_fixture(monkeypatch)
    claims.ensure(pid)
    calls = {"n": 0}
    real = claims.extract

    def flaky(project_id, cands=None, transport="interactive"):
        calls["n"] += 1
        if calls["n"] == 1:
            real(project_id, cands[:1], transport)              # one group lands…
            raise RuntimeError("simulated truncation")            # …then the run dies
        return real(project_id, cands, transport)
    monkeypatch.setattr(claims, "extract", flaky)
    with pytest.raises(RuntimeError):
        claims.run_evaluation(pid, budget=3)
    assert db.kv_get(f"claims:eval:{pid}:pending")
    rep = claims.run_evaluation(pid, budget=3)
    assert rep["cohort"]["size"] == 3 and rep["normalized"] >= 1 and db.kv_get(f"claims:eval:{pid}:pending") is None
    full = claims.evaluation_report(pid)
    assert len(full["rows"]) == 3 and all(r["before"] and r["after"] for r in full["rows"])


def test_targets_dedupe_by_meaning_and_proposals_are_capped(monkeypatch):
    pid, _ = _acceptance_fixture(monkeypatch)
    a = knowledge.add_target(pid, "What are the current SBA rules on seller notes and standby?", sufficiency="governing", origin="model")
    b = knowledge.add_target(pid, "What are the SBA rules on seller notes and standby currently?", sufficiency="governing", origin="model")
    assert b["id"] == a["id"]                                                # same gap phrased twice → one target
    mine = knowledge.add_target(pid, "SBA seller note standby rules — what applies to us?", sufficiency="governing", origin="user")
    knowledge.refresh(pid)
    assert knowledge.get_target(mine["id"])["status"] != "dropped"           # user targets are never folded away
    # normalization proposes at most three targets per call and none that duplicate existing ones
    claims.ensure(pid)
    before = len(knowledge.list_targets(pid, status="open"))
    claims.extract(pid)
    after = len(knowledge.list_targets(pid, status="open"))
    assert after - before <= 3


def test_requirement_attributed_to_the_seller_opens_the_governing_question(monkeypatch):
    """The CPA-buyer case: normalization keeps 'the listing requires a CPA buyer' as a seller/listing requirement AND opens
    the governing target (is it a legal/licensing/service rule?) instead of a target to corroborate the listing."""
    pid, ids = _acceptance_fixture(monkeypatch)
    lst = _transcript("listing1", "Central Valley CPA practice listing", "Practice Sales", "Specific requirements: the seller requires the buyer to be a CPA who can prepare compilations.", platform="media")
    db.add_project_sources(pid, [lst])
    _note(pid, lst, "Seller requires the buyer to be a CPA who can prepare compilations", "the seller requires the buyer to be a CPA who can prepare compilations", importance=5, title="Buyer must be a CPA")
    claims.ensure(pid)
    c = _by_text(pid, "CPA who can prepare compilations")
    claims.extract(pid, [c])
    c = claims.get(c["id"])
    assert c["qualifiers"]["imposed_by"] == "seller_or_listing"
    assert "seller" in c["text"].lower()                                            # the requirement's source survives normalization
    tg = [t for t in knowledge.list_targets(pid) if t["claim_id"] == c["id"] and t["sufficiency"] == "governing"]
    assert tg and "professional licensing" in tg[0]["question"] and tg[0]["closure_rule"]["primary_required"] is True

