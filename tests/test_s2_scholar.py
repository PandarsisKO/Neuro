"""S2 — Crossref and OpenAlex as a $0 discovery / resolution backend (`scholar.py`).

Nothing here touches the real network: `safe_fetch.safe_fetch` is replaced with a recorder that returns canned
catalogue payloads, which is also how the tests prove the boundary rules — that every request goes through
`safe_fetch` at all, that Crossref carries the `mailto` and OpenAlex the `api_key`, and that a catalogue outage
degrades instead of failing the caller.

The invariants that matter:
  · a catalogue record is metadata — it becomes a candidate or a discovery, never evidence, and only an
    open-access PDF is ever queued for ingestion, through the ordinary `ingest_url` path;
  · no model call is made anywhere in this module (Discover's catalogue pass is cheaper than the pass it
    supplements precisely because a real record needs no verification);
  · a scholarly query only runs where literature is actually the evidence class asked for.
"""
from __future__ import annotations

import json

import pytest

from neurosearch import db, discover, safe_fetch, scholar
from neurosearch.config import settings

# ------------------------------------------------------------------ canned payloads

CROSSREF_ITEM = {
    "DOI": "10.1038/S41586-021-03819-3",
    "title": ["Highly accurate protein structure prediction"],
    "abstract": "<jats:p>We  present\nAlphaFold, a  computational method.</jats:p>",
    "author": [{"given": "John", "family": "Jumper"}, {"given": "Richard", "family": "Evans"}],
    "container-title": ["Nature"],
    "issued": {"date-parts": [[2021, 7, 15]]},
    "is-referenced-by-count": 12345,
    "link": [{"content-type": "text/html", "URL": "https://example.org/landing"},
             {"content-type": "application/pdf", "URL": "https://example.org/paper.pdf"}],
    "URL": "https://doi.org/10.1038/s41586-021-03819-3",
}

OPENALEX_ITEM = {
    "id": "https://openalex.org/W3177828909",
    "doi": "https://doi.org/10.1038/s41586-021-03819-3",
    "display_name": "Highly accurate protein structure prediction",
    "publication_year": 2021,
    "cited_by_count": 12000,
    "authorships": [{"author": {"display_name": "John Jumper"}}, {"author": {"display_name": "Richard Evans"}}],
    "primary_location": {"source": {"display_name": "Nature"}},
    "best_oa_location": {"pdf_url": "https://europepmc.org/oa.pdf", "is_oa": True},
    "open_access": {"oa_status": "hybrid", "oa_url": "https://europepmc.org/oa.pdf"},
    "abstract_inverted_index": {"We": [0], "present": [1], "AlphaFold": [2]},
}


class Recorder:
    """Stands in for safe_fetch: records every URL asked for and replays a payload per host."""

    def __init__(self, crossref=None, openalex=None, status=200, raise_blocked=False):
        self.urls: list[str] = []
        self.headers: list[dict] = []
        self.crossref = crossref if crossref is not None else {"message": {"items": [CROSSREF_ITEM]}}
        self.openalex = openalex if openalex is not None else {"results": [OPENALEX_ITEM]}
        self.status = status
        self.raise_blocked = raise_blocked

    def __call__(self, url, *, content_class=None, headers=None, deadline_s=None, **kw):
        self.urls.append(url)
        self.headers.append(dict(headers or {}))
        if self.raise_blocked:
            raise safe_fetch.FetchBlocked("private_address", "refused")
        # a single-record URL ("/works/10.x" or "/works/doi:10.x") returns the injected payload too, so a test that
        # injects a closed-access record sees it on BOTH the search and the resolve path
        single = "/works/" in url
        if "crossref.org" in url:
            body = self.crossref
            if single and isinstance(body, dict) and isinstance((body.get("message") or {}), dict) and "items" in (body.get("message") or {}):
                items = body["message"]["items"]
                body = {"message": items[0] if items else {}}
        else:
            body = self.openalex
            if single and isinstance(body, dict) and "results" in body:
                res = body["results"]
                body = res[0] if res else {}
        return safe_fetch.FetchResult(url=url, status=self.status, content_type="application/json",
                                      body=json.dumps(body).encode())


@pytest.fixture()
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(safe_fetch, "safe_fetch", r)
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})          # no sleeping in tests
    scholar._last_call.clear()
    return r


@pytest.fixture()
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "scholar_email", "kyle@example.com", raising=False)
    monkeypatch.setattr(settings, "openalex_api_key", "oa-test-key", raising=False)


# ------------------------------------------------------------------ availability is config, never a probe

def test_availability_needs_no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("available() must not fetch anything")
    monkeypatch.setattr(safe_fetch, "safe_fetch", boom)
    monkeypatch.setattr(settings, "openalex_api_key", None, raising=False)
    a = scholar.available()
    assert a["crossref"]["ready"] is True                        # no account needed, ever
    assert a["openalex"]["ready"] is False and "OPENALEX_API_KEY" in a["openalex"]["why"]
    assert scholar.ready_providers() == ["crossref"]


def test_openalex_becomes_ready_with_a_key(keyed):
    assert scholar.ready_providers() == ["crossref", "openalex"]


# ------------------------------------------------------------------ the boundary and the credentials

def test_every_request_goes_through_safe_fetch_with_the_right_credential(rec, keyed):
    scholar.search("protein folding", limit=3, provider="crossref")
    assert len(rec.urls) == 1 and rec.urls[0].startswith("https://api.crossref.org/works?")
    assert "mailto=kyle%40example.com" in rec.urls[0]           # polite pool
    assert "mailto:kyle@example.com" in rec.headers[0]["User-Agent"]
    scholar.search("protein folding", limit=3, provider="openalex")
    assert "api_key=oa-test-key" in rec.urls[1]                 # required since 2026-02-13
    assert "mailto" not in rec.urls[1]                          # the parameter OpenAlex retired is not sent


def test_a_blocked_fetch_degrades_and_never_leaks_the_boundary_error(monkeypatch, keyed):
    monkeypatch.setattr(safe_fetch, "safe_fetch", Recorder(raise_blocked=True))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    with pytest.raises(scholar.ScholarUnavailable) as e:
        scholar.search("anything")
    assert e.value.reason == "all_providers_failed"


def test_openalex_409_is_named_as_the_credit_wall(monkeypatch, keyed):
    monkeypatch.setattr(safe_fetch, "safe_fetch", Recorder(status=409))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    with pytest.raises(scholar.ScholarUnavailable) as e:
        scholar.search("anything", provider="openalex")
    assert e.value.reason == "credits_exhausted"


def test_one_provider_failing_falls_through_to_the_next(monkeypatch, keyed):
    class HalfBroken(Recorder):
        def __call__(self, url, **kw):
            if "crossref" in url:
                raise safe_fetch.FetchBlocked("timeout", "slow")
            return super().__call__(url, **kw)
    monkeypatch.setattr(safe_fetch, "safe_fetch", HalfBroken())
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    recs = scholar.search("protein folding")
    assert recs and recs[0]["provider"] == "openalex"


# ------------------------------------------------------------------ normalisation

def test_crossref_normalisation(rec):
    r = scholar.search("protein folding", provider="crossref")[0]
    assert r["doi"] == "10.1038/s41586-021-03819-3"              # lower-cased
    assert r["url"] == "https://doi.org/10.1038/s41586-021-03819-3"
    assert r["title"] == "Highly accurate protein structure prediction"
    assert "<jats:p>" not in r["abstract"] and "  " not in r["abstract"]     # tags stripped, whitespace collapsed
    assert r["creator"] == "John Jumper et al."
    assert r["venue"] == "Nature" and r["year"] == 2021 and r["cited_by"] == 12345
    assert r["oa_pdf_url"] == "https://example.org/paper.pdf"    # only the application/pdf link, not the landing page
    assert r["evidence_class"] == "expert"


def test_openalex_normalisation_rebuilds_the_inverted_abstract(rec, keyed):
    r = scholar.search("protein folding", provider="openalex")[0]
    assert r["abstract"] == "We present AlphaFold"
    assert r["oa_pdf_url"] == "https://europepmc.org/oa.pdf" and r["is_oa"] is True
    assert r["oa_status"] == "hybrid"


def test_a_single_author_is_not_given_et_al():
    assert scholar._authors(["Ada Lovelace"]) == "Ada Lovelace"
    assert scholar._authors(["Ada Lovelace", "Charles Babbage"]) == "Ada Lovelace et al."
    assert scholar._authors([]) == ""


def test_doi_is_recognised_in_prose_and_normalised():
    assert scholar.normalise_doi("see https://doi.org/10.1038/S41586-021-03819-3.") == "10.1038/s41586-021-03819-3"
    assert scholar.normalise_doi("doi:10.1234/abc-def_1") == "10.1234/abc-def_1"
    assert scholar.normalise_doi("no identifier here") is None
    assert scholar.normalise_doi(None) is None


def test_open_access_only_filters_records_without_a_free_copy(monkeypatch, keyed):
    closed = dict(OPENALEX_ITEM, best_oa_location=None, open_access={"oa_status": "closed"})
    monkeypatch.setattr(safe_fetch, "safe_fetch", Recorder(openalex={"results": [closed]}))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    assert scholar.search("x", provider="openalex", open_access_only=True) == []


# ------------------------------------------------------------------ resolve_doi: Crossref metadata + OpenAlex access

def test_resolve_doi_merges_metadata_with_the_access_answer(rec, keyed):
    r = scholar.resolve_doi("10.1038/s41586-021-03819-3")
    assert r is not None
    assert r["provider"] == "crossref" and r["cited_by"] == 12345          # Crossref's metadata is kept
    assert r["oa_pdf_url"] == "https://europepmc.org/oa.pdf"               # OpenAlex's access answer wins
    assert r["oa_status"] == "hybrid"


def test_resolve_doi_rejects_a_non_doi_without_fetching(rec):
    assert scholar.resolve_doi("not a doi") is None
    assert rec.urls == []


# ------------------------------------------------------------------ records are candidates, never evidence

def test_records_become_candidates_with_the_doi_as_identity(rec, keyed, tmp_path):
    db.init_db()
    p = db.create_project("Scholar test", brief="protein structure prediction accuracy")
    pid = p["id"] if isinstance(p, dict) else p
    recs = scholar.search("protein folding", provider="crossref")
    ids = scholar.to_candidates(recs, pid, origin={"kind": "user_query", "query": "protein folding"})
    assert len(ids) == 1
    row = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (ids[0],)).fetchone())
    assert row["platform"] == "crossref"
    assert row["url"] == "https://example.org/paper.pdf"          # what an Acquire click can actually ingest
    assert row["canonical_url"] == "https://doi.org/10.1038/s41586-021-03819-3"    # identity stays the DOI
    # nothing became a source, a chunk or evidence
    assert row["source_id"] is None


def test_a_record_without_free_full_text_says_so_in_the_candidate(monkeypatch, keyed):
    db.init_db()
    p = db.create_project("Scholar closed", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    # a DOI of its own: `candidates.remember` is deliberately fill-only (it never overwrites what it already knew),
    # so reusing the open-access record's DOI here would assert against the earlier test's description
    closed = dict(CROSSREF_ITEM, DOI="10.9999/closed-access-1", link=[{"content-type": "text/html", "URL": "https://example.org/landing"}])
    monkeypatch.setattr(safe_fetch, "safe_fetch", Recorder(crossref={"message": {"items": [closed]}}))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    recs = scholar.search("x", provider="crossref")
    assert recs[0]["oa_pdf_url"] is None
    ids = scholar.to_candidates(recs, pid, origin={"kind": "user_query"})
    row = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (ids[0],)).fetchone())
    assert "metadata only" in row["description"]
    assert row["url"] == row["canonical_url"] == "https://doi.org/10.9999/closed-access-1"


def test_only_an_open_access_pdf_is_ever_queued_for_ingestion(rec, keyed):
    db.init_db()
    p = db.create_project("Scholar acquire", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    r = scholar.search("protein folding", provider="crossref")[0]
    q = scholar.acquire(r, pid)
    assert q["queued"] is True and q["url"].endswith(".pdf")
    job = db.get_job(q["job_id"])
    assert job["kind"] == "ingest_url"                            # the ordinary path, not a parallel one
    closed = dict(r, oa_pdf_url=None)
    assert scholar.acquire(closed, pid)["queued"] is False


def test_discovery_items_never_invent_a_confident_fit(rec, keyed):
    items = scholar.to_discoveries(scholar.search("protein folding", provider="crossref"))
    assert items[0]["kind"] == "paper"
    assert items[0]["fit"] == 4                                   # open access
    assert items[0]["verified_by"] == "crossref"
    closed = scholar.to_discoveries([dict(scholar.search("x", provider="crossref")[0], oa_pdf_url=None)])
    assert closed[0]["fit"] == 3 and "metadata only" in closed[0]["angle"]


# ------------------------------------------------------------------ gap-first: only where literature is the evidence class

def test_a_target_is_only_queried_when_it_asks_for_expert_evidence():
    assert scholar.target_wants_literature({"preferred_classes": ["expert"]}) is True
    assert scholar.target_wants_literature({"preferred_classes": ["authoritative", "market"]}) is True
    assert scholar.target_wants_literature({"preferred_classes": '["expert"]'}) is True      # stored as JSON
    assert scholar.target_wants_literature({"preferred_classes": ["experiential"]}) is False
    assert scholar.target_wants_literature({"preferred_classes": []}) is False
    assert scholar.target_wants_literature({}) is False


def test_for_target_skips_an_experiential_question_without_fetching(rec, keyed):
    out = scholar.for_target({"id": "t1", "question": "How do editors feel about client revisions?",
                              "preferred_classes": ["experiential"]}, "p1")
    assert out["run"] is False and "experiential" in out["why"]
    assert rec.urls == []                                         # a free request is still a request


def test_for_target_links_every_candidate_to_the_question(rec, keyed):
    db.init_db()
    p = db.create_project("Gap test", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    from neurosearch import knowledge
    tg = knowledge.add_target(pid, "Does peer review improve accuracy?", preferred_classes=["expert"], origin="user")
    out = scholar.for_target(tg, pid)
    assert out["run"] is True and out["found"] == 1 and out["candidates"] == 1
    links = __import__("neurosearch.candidates", fromlist=["links_for"]).links_for(pid, "evidence_target", str(tg["id"]))
    assert links and "open question" in (links[0].get("why") or "")


# ------------------------------------------------------------------ Discover: the catalogue pass supplements, never takes over

def test_discover_asks_the_catalogue_only_when_literature_is_wanted():
    assert discover.scholar_wanted("find me peer-reviewed studies", {})[0] is True
    assert discover.scholar_wanted("more channels like this", {})[0] is False
    assert discover.scholar_wanted(None, {"targets": [{"question": "q", "preferred_classes": ["expert"]}]})[0] is True
    # a YouTube-only project with experiential questions gets no academic search bolted on
    assert discover.scholar_wanted(None, {"targets": [{"question": "q", "preferred_classes": ["experiential"]}]})[0] is False


def test_the_catalogue_pass_makes_no_model_call(rec, keyed, monkeypatch):
    from neurosearch import providers
    def boom(*a, **k):
        raise AssertionError("the catalogue pass must not call a model")
    monkeypatch.setattr(providers, "invoke", boom)
    monkeypatch.setattr(providers, "invoke_structured", boom)
    db.init_db()
    p = db.create_project("Catalogue pass", brief="protein structure prediction")
    out = discover.scholar_pass(db.get_project(p["id"] if isinstance(p, dict) else p),
                                "papers on protein folding", {"targets": []})
    assert out["run"] is True and out["found"] == 1
    assert out["items"][0]["kind"] == "paper"


def test_the_query_sent_to_a_catalogue_is_short():
    long_goal = "word " * 200
    assert len(discover._clean_query(long_goal)) <= 240


def test_scholar_only_mode_exists_and_needs_no_anthropic_key(rec, keyed, monkeypatch):
    from neurosearch import providers
    def boom(*a, **k):
        raise AssertionError("scholar_only must not require the Anthropic client")
    monkeypatch.setattr(providers, "require_anthropic", boom)
    monkeypatch.setattr(providers, "invoke", boom)
    db.init_db()
    p = db.create_project("Scholar only", brief="protein structure prediction accuracy")
    pid = p["id"] if isinstance(p, dict) else p
    out = discover.discover(pid, refine="papers on protein folding", mode="scholar_only")
    assert out["mode"] == "scholar_only"
    assert out["added"] == out["verified"] == 1                   # real by construction: verified without a verify pass
    assert "scholar_only" in discover.MODES


# ------------------------------------------------------------------ works.find_copy: identity resolved AND access resolved

def test_find_copy_turns_a_doi_into_an_obtainable_copy(rec, keyed):
    db.init_db()
    p = db.create_project("Find copy", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    from neurosearch import works
    out = works.find_copy("as reported in doi:10.1038/s41586-021-03819-3", project_id=pid)
    assert out["access"] == "open_access"
    assert out["url"] == "https://europepmc.org/oa.pdf"
    assert out["catalogue"]["venue"] == "Nature"
    assert out["queued"]["queued"] is True


def test_find_copy_still_reports_unresolved_access_when_there_is_no_free_copy(monkeypatch, keyed):
    db.init_db()
    p = db.create_project("Find copy closed", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    closed_cr = dict(CROSSREF_ITEM, link=[])
    closed_oa = dict(OPENALEX_ITEM, best_oa_location=None, open_access={"oa_status": "closed"})
    monkeypatch.setattr(safe_fetch, "safe_fetch",
                        Recorder(crossref={"message": closed_cr}, openalex=closed_oa))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    from neurosearch import works
    out = works.find_copy("doi:10.1038/s41586-021-03819-3", project_id=pid)
    assert out["access"] != "open_access"
    assert "no open-access copy" in (out.get("note") or "")


def test_a_catalogue_outage_never_changes_the_resolution_outcome(monkeypatch):
    db.init_db()
    p = db.create_project("Find copy outage", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    monkeypatch.setattr(safe_fetch, "safe_fetch", Recorder(raise_blocked=True))
    monkeypatch.setattr(scholar, "MIN_INTERVAL_S", {})
    from neurosearch import works
    out = works.find_copy("doi:10.1038/s41586-021-03819-3", project_id=pid)
    assert out["identity"] != "unresolved"          # the DOI still identifies the work
    assert out["access"] == "unavailable"


# ------------------------------------------------------------------ Health reports it without probing

def test_health_reports_the_catalogues_without_a_network_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("Health must not spend someone else's free service")
    monkeypatch.setattr(safe_fetch, "safe_fetch", boom)
    db.init_db()
    h = db.health()
    assert "crossref" in h["scholar"]["providers"] and "openalex" in h["scholar"]["providers"]
    assert "never evidence" in h["scholar"]["note"]


def test_the_catalogue_step_stays_off_the_no_web_search_path(rec, keyed):
    """`pursue(external=False)` is what the UI calls "Search my existing research … No web search", and the G5
    acceptance gate freezes it as network-free. A catalogue request is free but it is still a request to an outside
    service, so it belongs on the external path only — and the first version of this feature got that wrong."""
    db.init_db()
    from neurosearch import knowledge
    p = db.create_project("No web promise", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    tg = knowledge.add_target(pid, "Does peer review improve accuracy?", preferred_classes=["expert"], origin="user")
    r = knowledge.pursue(tg["id"], external=False)
    assert "catalogue" not in [s["step"] for s in r["escalation"]["steps"]]
    assert rec.urls == []                                   # nothing left the machine


def test_the_catalogue_runs_before_the_paid_external_job(rec, keyed):
    db.init_db()
    from neurosearch import knowledge
    p = db.create_project("Catalogue first", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    tg = knowledge.add_target(pid, "Does peer review improve accuracy?", preferred_classes=["expert"], origin="user")
    r = knowledge.pursue(tg["id"], external=True)
    steps = [s["step"] for s in r["escalation"]["steps"]]
    assert steps.index("catalogue") < steps.index("external")
    cat = next(s for s in r["escalation"]["steps"] if s["step"] == "catalogue")
    assert cat["run"] is True and cat["found"] == 1


def test_a_skipped_step_is_never_reported_to_the_user_as_checked(rec, keyed):
    """The escalation record keeps skipped steps with their reason, for diagnostics. `research_view.questions`
    reports what was actually CHECKED, so a recorded-but-not-run step must not appear there."""
    db.init_db()
    from neurosearch import knowledge, research_view
    p = db.create_project("Checked honestly", brief="x")
    pid = p["id"] if isinstance(p, dict) else p
    tg = knowledge.add_target(pid, "How do editors feel about revisions?", preferred_classes=["experiential"], origin="user")
    knowledge.pursue(tg["id"], external=True)               # the catalogue step is recorded but skipped
    q = next(x for x in research_view.questions(pid) if x["id"] == tg["id"])
    assert "Research catalogues" not in q["already_checked"]
    assert all("catalogue" != a for a in q["already_checked"])       # and never the raw internal word
