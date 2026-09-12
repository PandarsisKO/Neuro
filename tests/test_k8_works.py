"""Rung G6 — Canonical Works & Source Resolver: the FROZEN 12-point gate from the G6 lock (EXPANSION.md), $0 and offline.
(Sorts after test_core.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g6_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import candidates, claims, db, fake_ai, ingest, jobs, knowledge, resources, safe_fetch, works  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


RULE = "When a seller note counts toward the equity injection the seller note must be on full standby for the life of the loan."


def _page(url, title, body, published=None):
    html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p><p>Filler paragraph so the page has enough readable substance for the document reader, and a second section to cite.</p></body></html>"
    r = ingest.ingest_webpage(url, html=html, title=title)
    if published:
        db.upsert_source(platform="web", external_id=db.get_source(r["source_id"])["external_id"], published_at=published)
    return r["source_id"]


def _transcript(ext, title, channel, text, platform="youtube"):
    words = text.split()
    segs = [{"start": i * 6.0, "end": i * 6.0 + 6, "text": " ".join(words[j:j + 12])} for i, j in enumerate(range(0, len(words), 12))]
    return ingest.store_transcript({"platform": platform, "external_id": ext, "url": f"https://www.youtube.com/watch?v={ext}" if platform == "youtube" else f"https://example.com/{ext}.mp3",
                                    "title": title, "channel": channel, "published_at": "2026-05-01", "segments": segs, "transcript_kind": "captions"})["source_id"]


def _note(pid, sid, text, importance=4, locator="§ 1"):
    src = db.get_source(sid)
    return db.add_project_note(pid, text + " [1]", citations=[{"n": 1, "source_id": sid, "title": src["title"], "url": src["url"], "link": src["url"], "timestamp": locator,
                                                            "start": 1, "platform": src["platform"], "snippet": text}], status="approved", source_id=sid, importance=importance)


def _project():
    return db.create_project("G6", "Buying an accounting practice with an SBA loan")["id"]


def test_gate_1_identifier_resolves_to_existing_work_and_reuses_owned_copy_at_zero_cost():
    pid = _project()
    official = _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8 Lender and Development Company Loan Programs", RULE, "2026-02-01")
    works.index_source(official)
    before = db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
    r = works.find_copy("SOP 50 10 8", pid)
    assert r["identity"] == "resolved" and r["access"] == "owned" and r["where"] == "library" and r["source_ids"] == [official]
    assert r["next"] == "attach" and r["attach"]["source_ids"] == [official]
    assert db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == before
    assert db.connect().execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1        # no second Work for the same SOP
    # G2's classifier routes the identifier to the resolver
    c = resources.classify("SOP 50 10 8")
    assert c.kind == "work_identity" and c.default_action == "resolve"
    out = resources.route(c, pid)
    assert out["resolver"]["access"] == "owned"


def test_gate_2_3_and_12_equivalent_copies_and_derivatives_are_one_lineage(monkeypatch):
    pid = _project()
    official = _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8", RULE, "2026-02-01")
    mirror = _page("https://lenderdocs.example.com/mirrors/sop-50-10-8.html", "SOP 50 10 8 (mirror copy)", RULE, "2026-03-01")
    video = _transcript("explainer1", "SBA SOP 50 10 8 seller note standby explained", "Acquisition Basics", "Let me read you SOP 50 10 8. " + RULE)
    manual = _page("https://www.bigbank.example.com/underwriting-manual", "Bank underwriting manual: acquisition loans", "Bank policy: any seller carry-back we treat as buyer equity is placed on standby until our loan is repaid in full.", "2026-01-15")
    db.add_project_sources(pid, [official, mirror, video, manual])
    for sid in (official, mirror, video, manual):
        works.index_source(sid)
    w = works.list_works()[0]
    assert w["manifestations"] == 3 and {m["relation"] for m in works.manifestations_of(w["id"])} == {"manifestation_of", "derivative_of"}
    assert works.relation_of(official, w["id"]) == "manifestation_of" and works.relation_of(video, w["id"]) == "derivative_of"
    for sid in (official, mirror, video):
        _note(pid, sid, RULE)
    _note(pid, manual, "Seller note counted as equity: on full standby for the life of the loan (bank policy).")
    claims.ensure(pid)
    c = next(c for c in claims.list_for_project(pid) if "full standby" in c["text"])
    ev = c["evidence"]
    assert len(ev) == 4
    # (2) official + mirror = one lineage; (3) the explainer does not corroborate the SOP it derives from; (12) independence by lineage
    lineages = {e["lineage_id"] for e in ev if e["independent"]}
    assert sum(1 for e in ev if e["independent"]) == 2 and w["id"] in {e["lineage_id"] for e in ev}
    assert all(e["independent"] == 0 for e in ev if e["source_id"] in (mirror, video))
    assert next(e for e in ev if e["source_id"] == manual)["independent"] == 1          # the bank's own policy is its own lineage
    assert c["claim_type"] == "governing" and c["strength"] == "strong"


def test_gate_4_citation_of_unavailable_work_creates_stub_candidate_and_specific_target():
    pid = _project()
    talk = _transcript("depr1", "Depreciating the practice's equipment", "Tax Talk", "For the recovery periods see IRS Publication 946 for tax year 2026; the tables are all in there.")
    db.add_project_sources(pid, [talk])
    _note(pid, talk, "For the recovery periods see IRS Publication 946 for tax year 2026; the tables are all in there.", locator="0:00")
    claims.ensure(pid)
    w = next(x for x in works.list_works() if "946" in x["title"])
    assert w["resolution"] == "resolved" and w["kind"] == "publication" and w["versions"][0]["label"] == "tax year 2026"
    assert works.relation_of(talk, w["id"]) == "cites"
    cands = candidates.search(pid, "Publication 946")
    assert cands and cands[0]["platform"] == "work" and cands[0]["url"].endswith("p946.pdf") and cands[0]["state"] == "available"
    tg = [t for t in knowledge.list_targets(pid) if "Publication 946" in t["question"]]
    assert tg and tg[0]["question"].startswith("Obtain the authoritative/current manifestation of IRS Publication 946 (tax year 2026)")
    assert tg[0]["sufficiency"] == "governing" and ("primary source" in tg[0]["gap"] or "unresolved access" in tg[0]["gap"])
    assert works.project_relevance(pid, w["id"])["relevance"] == "targeted"
    r = works.find_copy("IRS Publication 946", pid)
    assert r["identity"] == "resolved" and r["access"] == "candidate" and r["next"] == "acquire"


def test_gate_5_6_7_version_relationship_drives_freshness():
    pid = _project()
    old = _page("https://www.sba.gov/document/sop-50-10-7-lender-and-development-company-loan-programs", "SOP 50 10 7", RULE, "2023-08-01")
    db.add_project_sources(pid, [old])
    works.index_source(old)
    _note(pid, old, RULE)
    claims.ensure(pid)
    c = next(c for c in claims.list_for_project(pid) if "full standby" in c["text"])
    assert c["freshness_status"] in ("current", "needs_refresh")          # regulatory: by age only
    w = works.list_works()[0]
    v7 = next(v for v in w["versions"] if v["label"] == "SOP 50 10 7")
    # (7) a rehosted identical copy of the same version: nothing changes
    mirror = _page("https://mirror.example.com/sop-50-10-7.pdf", "SOP 50 10 7 (mirror)", RULE, "2026-06-01")
    works.index_source(mirror)
    claims.assess(c["id"])
    assert "newer version" not in (claims.get(c["id"])["freshness_why"] or "")
    # (5) a newer governing edition, differences unknown → needs_refresh, not stale
    v8 = works.ensure_version(w["id"], "SOP 50 10 8", effective_date="2026-06-01", supersedes_id=v7["id"], change_kind="supersedes")
    c = claims.assess(c["id"])
    assert c["freshness_status"] == "needs_refresh" and "SOP 50 10 8" in c["freshness_why"] and "supersedes" in c["freshness_why"]
    # (6) a materially changed provision → stale
    works.ensure_version(w["id"], "SOP 50 10 8", supersedes_id=v7["id"], change_kind="material", change_note="seller-note standby period shortened to 24 months")
    c = claims.assess(c["id"])
    assert c["freshness_status"] == "stale" and "24 months" in c["freshness_why"]
    # a historical Claim explicitly about the old version is untouched
    db.connect().execute("UPDATE project_claims SET freshness_class='historical' WHERE id=?", (c["id"],)); db.connect().commit()
    assert claims.assess(c["id"])["freshness_status"] == "age_insensitive"


def test_gate_8_ambiguous_title_matching_never_merges_two_works():
    a, created_a = works.ensure_work("sop", "SBA SOP 50 10", identifiers=[{"scheme": "sop", "value": "sop5010"}])
    b, created_b = works.ensure_work("sop", "SBA SOP 50 10")                          # same title, no identifier → NOT the same Work
    assert created_a and created_b and a["id"] != b["id"] and b["resolution"] == "stub"
    book1, _ = works.ensure_work("book", "Buy Then Build", creators=["Walker Deibel"])
    book2, created = works.ensure_work("book", "Buy then build", creators=["Walker Deibel"])
    assert not created and book2["id"] == book1["id"]                               # exact normalized title + creator IS identity for a book
    other, created = works.ensure_work("book", "Buy Then Build", creators=["Someone Else"])
    assert created and other["id"] != book1["id"]
    assert works.find_copy("Buy Then Build")["identity"] == "unresolved"            # title-only input never resolves identity


def test_gate_9_10_11_one_work_many_projects_and_project_state_never_mutates_the_work():
    p1, p2 = _project(), db.create_project("Other", "Real estate")["id"]
    official = _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8", RULE, "2026-02-01")
    works.index_source(official)
    w = works.list_works()[0]
    works.set_project_relevance(p1, w["id"], "attached", reason="in project")
    works.set_project_relevance(p2, w["id"], "dismissed", reason="not relevant here")
    assert db.connect().execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1
    row = dict(db.connect().execute("SELECT * FROM works WHERE id=?", (w["id"],)).fetchone())
    assert row["updated_at"] == w["updated_at"] and row["resolution"] == "resolved"     # (10) the global row is untouched
    assert works.project_relevance(p1, w["id"])["relevance"] == "attached" and works.project_relevance(p2, w["id"])["relevance"] == "dismissed"
    # (11) resolver prefers the owned manifestation before any acquisition, from either project
    r = works.find_copy("SOP 50 10 8", p2)
    assert r["access"] == "owned" and r["next"] == "attach" and "job_id" not in r
    r2 = works.find_copy("SOP 50 10 8", p2, external=True)
    assert "job_id" not in r2                                                            # external is never needed when a copy is owned


def test_governing_claim_through_a_quote_is_not_fully_verified_while_the_primary_is_obtainable():
    pid = _project()
    official = _page("https://www.sba.gov/document/sop-50-10-8-lender-and-development-company-loan-programs", "SOP 50 10 8", RULE, "2026-02-01")
    works.index_source(official)                                                        # owned globally, NOT in this project
    quote = _page("https://www.acquisition-blog.example.com/standby", "What SOP 50 10 8 says about seller notes", "Quoting SOP 50 10 8: " + RULE, "2026-04-01")
    db.add_project_sources(pid, [quote])
    works.index_source(quote)
    _note(pid, quote, RULE)
    claims.ensure(pid)
    c = next(c for c in claims.list_for_project(pid) if "full standby" in c["text"])
    assert c["strength"] != "strong" and "primary source" in c["strength_why"] and "owned" in c["strength_why"]


def test_merge_work_is_the_only_way_two_works_become_one_and_keeps_an_alias():
    pid = _project()
    a, _ = works.ensure_work("form", "Form 1120-S", identifiers=[{"scheme": "docnum", "value": "form-1120-s"}])
    b, _ = works.ensure_work("form", "Form 1120S", identifiers=[{"scheme": "docnum", "value": "form-1120s"}])
    s1 = _transcript("f1", "How to file Form 1120-S", "Tax Talk", "Form 1120-S walkthrough for S corps.")
    s2 = _transcript("f2", "Form 1120S deadlines", "Tax Talk", "Form 1120S is due in March.")
    works.link_source(s1, a["id"], relation="derivative_of", form="derivative")
    works.link_source(s2, b["id"], relation="derivative_of", form="derivative")
    va = works.ensure_version(a["id"], "2025")
    works.ensure_version(b["id"], "2025"); works.ensure_version(b["id"], "2026")
    works.set_project_relevance(pid, a["id"], "relevant"); works.set_project_relevance(pid, b["id"], "targeted")
    merges = works.reconcile_identifiers()
    assert len(merges) == 1 and merges[0]["moved"]["manifestations"] == 1
    canon = works.get(merges[0]["canonical_work_id"])
    assert canon and works.get(merges[0]["merged_work_id"]) is None
    assert works.get_any(merges[0]["merged_work_id"])["id"] == canon["id"]                    # alias survives
    assert {v["label"] for v in canon["versions"]} == {"2025", "2026"} and len(canon["manifestations"]) == 2
    assert works.project_relevance(pid, canon["id"])["relevance"] == "targeted"                 # the stronger state wins
    assert works.by_identifier("docnum", "form-1120s")["work_id"] == canon["id"] and canon["title"] in ("Form 1120-S", "Form 1120S")
    assert db.connect().execute("SELECT COUNT(*) FROM works").fetchone()[0] == 1
    with pytest.raises(ValueError):
        works.merge_work(canon["id"], canon["id"])

