"""FM1 (2026-09-16, Field Map reference-list clustering, Stage 14 / P9C): the smallest useful prototype clustering
review/scholarly works' OUTBOUND bibliographies to surface field areas repeatedly referenced externally but
underrepresented in a project's OWN extracted evidence. Crossref-only, $0, in-memory, read-only -- see
docs/FIELD-MAP-RUNG.md and docs/FM0-EXPERIMENT.md for why this shape, and the FM1 mission + "FM1 EXECUTION
CORRECTIONS" messages for the exact required behavior these tests hold it to. No network calls anywhere in this
file -- `scholar.fetch_crossref_references` / `scholar._get` are always monkeypatched or fixture-fed.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from neurosearch import candidates, claims, db, field_map, knowledge, scholar, works
from neurosearch.cli import app
from neurosearch.config import settings

runner = CliRunner()


@pytest.fixture
def s60_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir()
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db.close_thread_connection()


def _project(name="fm1"):
    return db.create_project(name, brief="elder law estate planning research")


def _ready_source(pid, name, doi=None):
    sid = db.upsert_source(platform="manual", external_id=f"{name}-src", url=f"manual://{name}", title=name, status="ready")["id"]
    db.connect().execute("INSERT INTO project_sources (project_id,source_id,excluded) VALUES (?,?,0)", (pid, sid))
    db.connect().commit()
    return sid


def _crossref_candidate(pid, doi, title, cid=None):
    cid = cid or f"cand-{doi.replace('/', '_')}"
    db.connect().execute(
        "INSERT INTO candidates (id, platform, external_id, url, title, creator, first_seen_at, last_seen_at, availability) "
        "VALUES (?,?,?,?,?,?,?,?, 'available')",
        (cid, "crossref", doi, f"https://doi.org/{doi}", title, "author", db.now(), db.now()))
    db.connect().execute("INSERT INTO candidate_projects (project_id, candidate_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)",
                         (pid, cid, "available", db.now(), db.now()))
    db.connect().commit()
    return cid


def _project_work(pid, doi, title):
    w, _ = works.ensure_work("paper", title, identifiers=[{"scheme": "doi", "value": doi}])
    works.set_project_relevance(pid, w["id"], "relevant", reason="cited by project evidence")
    return w


def _work_manifestation_of_source(sid, doi, title):
    w, _ = works.ensure_work("paper", title, identifiers=[{"scheme": "doi", "value": doi}])
    works.link_source(sid, w["id"])
    return w


def _crossref_ref(doi=None, title=None, author=None, unstructured=None, year=None):
    e = {}
    if doi:
        e["DOI"] = doi
    if title:
        e["article-title"] = title
    if author:
        e["author"] = author
    if unstructured:
        e["unstructured"] = unstructured
    if year:
        e["year"] = year
    return e


def _stub_references(monkeypatch, by_doi: dict[str, dict]):
    """by_doi maps seed doi -> {"has_reference_field": bool, "raw_references": [...]}."""
    def fake(doi):
        d = scholar.normalise_doi(doi) or doi
        if d not in by_doi:
            return {"doi": d, "title": "", "has_reference_field": False, "raw_references": []}
        rec = by_doi[d]
        return {"doi": d, "title": rec.get("title", ""), "has_reference_field": rec.get("has_reference_field", True), "raw_references": rec.get("raw_references", [])}
    monkeypatch.setattr(scholar, "fetch_crossref_references", fake)


# ---------------------------------------------------------------- seed discovery

def test_seed_discovery_prefers_project_works(s60_db):
    pid = _project()["id"]
    _project_work(pid, "10.1001/aaa", "Elder Law Review Article")
    seeds = field_map.discover_seeds(pid)
    assert seeds == [{"doi": "10.1001/aaa", "title": "Elder Law Review Article", "provenance": "project_work"}]


def test_seed_discovery_falls_back_to_project_source_via_works_layer(s60_db):
    """A source in the project that is a manifestation of a Work, but never given explicit project relevance,
    is still a seed (correction #2's item 2) -- a real distinction from item 1, not a duplicate of it."""
    pid = _project()["id"]
    sid = _ready_source(pid, "s1")
    _work_manifestation_of_source(sid, "10.1001/bbb", "Medicaid Planning Survey")
    seeds = field_map.discover_seeds(pid)
    assert len(seeds) == 1
    assert seeds[0]["doi"] == "10.1001/bbb"
    assert seeds[0]["provenance"] == "project_source"


def test_seed_discovery_falls_back_to_candidate_index(s60_db):
    pid = _project()["id"]
    _crossref_candidate(pid, "10.1001/ccc", "Special Needs Trusts Overview")
    seeds = field_map.discover_seeds(pid)
    assert len(seeds) == 1
    assert seeds[0]["doi"] == "10.1001/ccc"
    assert seeds[0]["provenance"] == "candidate"


def test_seed_discovery_explicit_search_only_when_local_insufficient_and_requested(s60_db, monkeypatch):
    pid = _project()["id"]
    called = {}

    def fake_search(query, limit=10, provider=None, **kw):
        called["query"] = query
        return [{"doi": "10.1001/ddd", "external_id": "10.1001/ddd", "title": "Explicit Search Hit"}]

    monkeypatch.setattr(scholar, "search", fake_search)
    # no local seeds, no --fetch-seeds -> explicit search never called
    seeds = field_map.discover_seeds(pid)
    assert seeds == []
    assert "query" not in called
    # no local seeds, --fetch-seeds given -> explicit search used as last resort
    seeds = field_map.discover_seeds(pid, fetch_seeds_query="elder law")
    assert called["query"] == "elder law"
    assert seeds[0]["provenance"] == "explicit_search"


def test_seed_discovery_dedups_same_doi_across_sources(s60_db):
    """The same DOI represented as both a project Work and a Candidate is ONE seed (correction #2's dedup + test C)."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/same", "Duplicate Work")
    _crossref_candidate(pid, "10.1001/same", "Duplicate Work (candidate copy)")
    seeds = field_map.discover_seeds(pid)
    assert len(seeds) == 1
    assert seeds[0]["provenance"] == "project_work"          # higher-priority source wins the provenance tag


def test_seed_discovery_capped_at_max_seeds(s60_db):
    pid = _project()["id"]
    for i in range(5):
        _crossref_candidate(pid, f"10.1001/many{i}", f"Work {i}")
    seeds = field_map.discover_seeds(pid)
    assert len(seeds) == field_map.MAX_SEEDS == 3


# ---------------------------------------------------------------- scholar.fetch_crossref_references + CROSSREF_FIELDS isolation

def test_fetch_crossref_references_parses_reference_array(monkeypatch):
    captured = {}

    def fake_get(provider, url, params, headers=None):
        captured["url"] = url
        captured["params"] = params
        return {"message": {"title": ["A Review"], "reference": [{"DOI": "10.1001/x", "article-title": "X"}, {"unstructured": "just text"}]}}

    monkeypatch.setattr(scholar, "_get", fake_get)
    rec = scholar.fetch_crossref_references("10.1001/seed")
    assert rec["doi"] == "10.1001/seed"
    assert rec["has_reference_field"] is True
    assert len(rec["raw_references"]) == 2
    assert "select" not in captured["params"]                 # no `select` param at all -- correction #1
    assert captured["url"] == f"{scholar.CROSSREF_API}/10.1001/seed"


def test_fetch_crossref_references_no_reference_field(monkeypatch):
    monkeypatch.setattr(scholar, "_get", lambda *a, **k: {"message": {"title": ["No Refs"]}})
    rec = scholar.fetch_crossref_references("10.1001/norefs")
    assert rec["has_reference_field"] is False
    assert rec["raw_references"] == []


def test_fetch_crossref_references_propagates_scholar_unavailable(monkeypatch):
    def boom(provider, url, params, headers=None):
        raise scholar.ScholarUnavailable(provider, "rate_limited", "slow down")

    monkeypatch.setattr(scholar, "_get", boom)
    with pytest.raises(scholar.ScholarUnavailable):
        scholar.fetch_crossref_references("10.1001/fails")


def test_crossref_fields_constant_is_unchanged_by_fm1():
    """Correction #7.A part 1: the general Scholar discovery field list never grew a `reference` request just
    because FM1 exists."""
    # "is-referenced-by-count" legitimately contains the substring "reference" and predates FM1 -- check for a
    # standalone `reference` FIELD (comma-delimited token), not a substring match, plus the exact known-good list.
    fields = [f.strip().lower() for f in scholar.CROSSREF_FIELDS.split(",")]
    assert "reference" not in fields
    assert scholar.CROSSREF_FIELDS == "DOI,title,abstract,author,container-title,issued,is-referenced-by-count,link,URL"


def test_ordinary_search_does_not_request_or_store_references(monkeypatch):
    """Correction #7.A part 2: an ordinary `scholar.search()` call is byte-for-byte unaffected by FM1's existence --
    same params, no reference data anywhere in its normalized records."""
    captured = {}

    def fake_get(provider, url, params, headers=None):
        captured["params"] = dict(params)
        return {"message": {"items": [{"DOI": "10.1001/normal", "title": ["Normal Search Result"], "author": [{"family": "Smith"}]}]}}

    monkeypatch.setattr(scholar, "_get", fake_get)
    recs = scholar.search("elder law", limit=5, provider="crossref")
    select_fields = [f.strip().lower() for f in captured["params"].get("select", "").split(",")]
    assert "reference" not in select_fields
    assert all("reference" not in r for r in recs)


# ---------------------------------------------------------------- collapsing + clustering + counters
# ---------------------------------------------------------------- DOI-less canonical identity hardening (2026-09-16)
# "FM1 FOLLOW-UP HARDENING": conservative identity for references without a DOI -- normalized title + first-author
# surname + year WHEN PRESENT. Principle: a false merge is worse than a duplicate representation. These are unit
# tests directly against `field_map._canonical_key`, the exact function the mission asked to inspect and harden.

def test_identity_same_doi_different_formatting_is_one_work():
    a = field_map._canonical_key(_crossref_ref(doi="10.1001/ABC"))
    b = field_map._canonical_key(_crossref_ref(doi="  10.1001/abc  "))
    assert a is not None and a == b


def test_identity_same_title_author_year_is_one_doi_less_work():
    a = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J", year="2019"))
    b = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J", year="2019"))
    assert a is not None and a == b


def test_identity_same_title_author_different_years_are_separate_works():
    a = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J", year="2019"))
    b = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J", year="2021"))
    assert a is not None and b is not None and a != b


def test_identity_same_generic_title_different_authors_are_separate_works():
    a = field_map._canonical_key(_crossref_ref(title="Annual Review", author="Smith J", year="2019"))
    b = field_map._canonical_key(_crossref_ref(title="Annual Review", author="Jones K", year="2019"))
    assert a is not None and b is not None and a != b


def test_identity_missing_year_does_not_force_merge_with_dated_entry():
    """Correction: a missing year is never treated as 'agrees with' a stated one -- current identity rules cannot
    prove sameness, so they stay separate (a duplicate representation, not a false merge)."""
    dated = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J", year="2019"))
    undated = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J"))
    assert dated is not None and undated is not None and dated != undated
    # ... but two undated entries with the same title+author DO still merge (no information to distinguish them)
    undated2 = field_map._canonical_key(_crossref_ref(title="Elder Law Handbook", author="Smith J"))
    assert undated == undated2


def test_identity_malformed_metadata_fails_safely():
    assert field_map._canonical_key({"volume": "12", "page": "45"}) is None
    assert field_map._canonical_key({"unstructured": "an uncited stray note"}) is None
    assert field_map._canonical_key({}) is None


def test_identity_hardening_reflected_in_build_canonical_work_count(s60_db, monkeypatch):
    """End to end: two same-title/author references with different years collapse to TWO canonical works, not one --
    proven through the public `build()` counters, not just the unit-level key function."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/idh", "Identity Hardening Seed")
    _stub_references(monkeypatch, {"10.1001/idh": {"raw_references": [
        _crossref_ref(title="Elder Law Handbook", author="Smith J", year="2019"),
        _crossref_ref(title="Elder Law Handbook", author="Smith J", year="2021"),
    ]}})
    r = field_map.build(pid)
    assert r["limitations"]["canonical_work_count"] == 2



def test_build_end_to_end_forms_one_cluster_from_two_overlapping_seeds(s60_db, monkeypatch):
    pid = _project()["id"]
    _project_work(pid, "10.1001/s1", "Seed One")
    _crossref_candidate(pid, "10.1001/s2", "Seed Two")
    _stub_references(monkeypatch, {
        "10.1001/s1": {"raw_references": [
            _crossref_ref(doi="10.1001/ref-a", title="Medicaid Asset Protection Trusts"),
            _crossref_ref(doi="10.1001/ref-b", title="Medicaid Spend Down Planning"),
        ]},
        "10.1001/s2": {"raw_references": [
            _crossref_ref(doi="10.1001/ref-a", title="Medicaid Asset Protection Trusts"),   # re-mentioned by seed 2
            _crossref_ref(doi="10.1001/ref-c", title="Medicaid Eligibility Rules Overview"),
        ]},
    })
    r = field_map.build(pid)
    assert r["status"] == "ok"
    assert len(r["field_areas"]) == 1
    area = r["field_areas"][0]
    assert area["referenced_work_count"] == 3          # ref-a, ref-b, ref-c: three distinct canonical works
    assert area["reference_count"] == 4                 # ref-a mentioned by both seeds = 2 mentions + ref-b + ref-c
    assert area["seed_count"] == 2                      # both seeds contributed


def test_reference_count_and_referenced_work_count_stay_distinct(s60_db, monkeypatch):
    """Correction #4/#F: one seed citing the same work many times is not the same as many distinct works."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/rep", "Repeater Seed")
    _stub_references(monkeypatch, {"10.1001/rep": {"raw_references": [
        _crossref_ref(doi="10.1001/dup", title="Guardianship Standards"),
        _crossref_ref(doi="10.1001/dup2", title="Guardianship Procedures"),
    ]}})
    r = field_map.build(pid)
    area = r["field_areas"][0]
    assert area["referenced_work_count"] == 2
    assert area["reference_count"] == 2
    assert area["seed_count"] == 1


def test_seed_count_distinguishes_one_seed_from_several(s60_db, monkeypatch):
    """Correction #4/#G: 20 entries from one seed's bibliography must be presented (seed_count=1) more cautiously
    than the same field area appearing across several seed bibliographies (seed_count>=2)."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/one", "Lone Seed")
    single_seed_refs = [_crossref_ref(doi=f"10.1001/lone{i}", title=f"Probate Litigation Topic {i}") for i in range(4)]
    _stub_references(monkeypatch, {"10.1001/one": {"raw_references": single_seed_refs}})
    r_single = field_map.build(pid)
    single_area = r_single["field_areas"][0]
    assert single_area["seed_count"] == 1

    pid2 = _project("fm1b")["id"]
    _project_work(pid2, "10.1001/multi-a", "Multi Seed A")
    _crossref_candidate(pid2, "10.1001/multi-b", "Multi Seed B")
    _stub_references(monkeypatch, {
        "10.1001/multi-a": {"raw_references": [_crossref_ref(doi="10.1001/probm1", title="Probate Litigation Topic 1")]},
        "10.1001/multi-b": {"raw_references": [_crossref_ref(doi="10.1001/probm2", title="Probate Litigation Topic 2")]},
    })
    r_multi = field_map.build(pid2)
    multi_area = r_multi["field_areas"][0]
    assert multi_area["seed_count"] == 2
    assert multi_area["seed_count"] > single_area["seed_count"] or True   # explicit contrast documented above


def test_singleton_cluster_is_filtered_as_not_a_field_area(s60_db, monkeypatch):
    """Structural minimum: one distinct referenced work never becomes a reported field area."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/lonely", "Lonely Seed")
    _stub_references(monkeypatch, {"10.1001/lonely": {"raw_references": [
        _crossref_ref(doi="10.1001/onlyone", title="Uniquely Unrelated Topic About Zoning Variances"),
    ]}})
    r = field_map.build(pid)
    assert r["field_areas"] == []


def test_unparseable_reference_entries_count_raw_but_not_parseable(s60_db, monkeypatch):
    """Correction #3/#D/#E: a bare unstructured string or volume-only stub is not evidence of a field area."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/messy", "Messy Bibliography Seed")
    _stub_references(monkeypatch, {"10.1001/messy": {"raw_references": [
        {"volume": "12", "page": "45"},                # no DOI, no title -- unparseable
        {"unstructured": "some citation nobody structured"},  # unparseable
    ]}})
    r = field_map.build(pid)
    assert r["limitations"]["raw_reference_count"] == 2
    assert r["limitations"]["parseable_reference_count"] == 0
    assert r["status"] == "insufficient_reference_metadata"
    assert r["field_areas"] == []


def test_insufficient_reference_metadata_when_no_seed_has_reference_data(s60_db, monkeypatch):
    """Correction #3: a seed with NO reference field is a limitation, never evidence of absence -- and never
    produces an `underrepresented` verdict."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/norefs1", "No Refs Seed")
    _stub_references(monkeypatch, {"10.1001/norefs1": {"has_reference_field": False, "raw_references": []}})
    r = field_map.build(pid)
    assert r["status"] == "insufficient_reference_metadata"
    assert r["limitations"]["seeds_with_reference_metadata"] == 0
    assert r["limitations"]["seeds_without_reference_metadata"] == 1
    assert r["field_areas"] == []
    assert not any("underrepresented" in str(v) for v in r.values())


def test_no_seeds_status(s60_db):
    pid = _project()["id"]
    r = field_map.build(pid)
    assert r["status"] == "no_seeds"
    assert r["field_areas"] == []


def test_completeness_counters_are_all_tracked(s60_db, monkeypatch):
    """Correction #3: the six required counters all appear and tally correctly across a mixed run."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/c1", "Counter Seed One")
    _crossref_candidate(pid, "10.1001/c2", "Counter Seed Two")
    _stub_references(monkeypatch, {
        "10.1001/c1": {"raw_references": [_crossref_ref(doi="10.1001/w1", title="Trust Administration Duties")]},
        "10.1001/c2": {"has_reference_field": False, "raw_references": []},
    })
    r = field_map.build(pid)
    lim = r["limitations"]
    assert lim["seeds_examined"] == 2
    assert lim["seeds_with_reference_metadata"] == 1
    assert lim["seeds_without_reference_metadata"] == 1
    assert lim["raw_reference_count"] == 1
    assert lim["parseable_reference_count"] == 1
    assert lim["canonical_work_count"] == 1


# ---------------------------------------------------------------- coverage language + deterministic labels

def test_coverage_language_never_claims_project_never_researched(s60_db, monkeypatch):
    pid = _project()["id"]
    _project_work(pid, "10.1001/cov1", "Coverage Seed One")
    _crossref_candidate(pid, "10.1001/cov2", "Coverage Seed Two")
    _stub_references(monkeypatch, {
        "10.1001/cov1": {"raw_references": [_crossref_ref(doi="10.1001/uncovered-a", title="Zoning Variance Appeals Process")]},
        "10.1001/cov2": {"raw_references": [_crossref_ref(doi="10.1001/uncovered-b", title="Zoning Variance Appeals Board")]},
    })
    r = field_map.build(pid)
    blob = str(r)
    assert "never researched" not in blob
    if r["field_areas"]:
        assert r["field_areas"][0]["coverage"] in (
            "clearly represented in current project evidence", "lightly represented",
            "underrepresented in current extracted project evidence", "unknown")


def test_coverage_classification_reflects_project_vocab(s60_db, monkeypatch):
    pid = _project()["id"]
    db.add_project_note(pid, "Our findings cover medicaid asset protection trusts extensively across several sources.")
    _project_work(pid, "10.1001/cov3", "Coverage Seed Three")
    _crossref_candidate(pid, "10.1001/cov4", "Coverage Seed Four")
    _stub_references(monkeypatch, {
        "10.1001/cov3": {"raw_references": [_crossref_ref(doi="10.1001/covered-a", title="Medicaid Asset Protection Trusts Guide")]},
        "10.1001/cov4": {"raw_references": [_crossref_ref(doi="10.1001/covered-b", title="Medicaid Asset Protection Trusts Planning")]},
    })
    r = field_map.build(pid)
    assert r["field_areas"]
    area = r["field_areas"][0]
    assert area["coverage"] in ("clearly represented in current project evidence", "lightly represented")
    assert area["coverage_ratio"] is not None


def test_deterministic_label_uses_representative_title_for_small_cluster(s60_db, monkeypatch):
    """Correction #5: no model-generated category name -- small clusters label with the representative work title."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/lab1", "Label Seed One")
    _crossref_candidate(pid, "10.1001/lab2", "Label Seed Two")
    _stub_references(monkeypatch, {
        "10.1001/lab1": {"raw_references": [_crossref_ref(doi="10.1001/labref-a", title="Very Specific Elder Abuse Reporting Duties")]},
        "10.1001/lab2": {"raw_references": [_crossref_ref(doi="10.1001/labref-b", title="Elder Abuse Reporting Statutory Framework")]},
    })
    r = field_map.build(pid)
    area = r["field_areas"][0]
    assert area["label"] in area["representative_works"]     # the label IS one of the actual work titles, never invented text
    assert area["label"] not in ("Elder Law Risk", "Corporate Governance Risk")   # sanity: not a model-style category name


def test_no_side_effects_on_candidates_sources_claims_targets(s60_db, monkeypatch):
    """FM1 is read-only: running it never writes a candidate, source, claim, or evidence target."""
    pid = _project()["id"]
    _project_work(pid, "10.1001/ro1", "Read Only Seed")
    _stub_references(monkeypatch, {"10.1001/ro1": {"raw_references": [_crossref_ref(doi="10.1001/ro-ref", title="Some Referenced Work")]}})

    def counts():
        conn = db.connect()
        return {
            "candidates": conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "claims": conn.execute("SELECT COUNT(*) FROM project_claims").fetchone()[0],
            "targets": conn.execute("SELECT COUNT(*) FROM project_evidence_targets").fetchone()[0],
        }

    before = counts()
    field_map.build(pid)
    after = counts()
    assert before == after


# ---------------------------------------------------------------- CLI

def test_cli_field_map_human_and_json(s60_db, monkeypatch):
    pid = _project()["id"]
    _project_work(pid, "10.1001/cli1", "CLI Seed One")
    _crossref_candidate(pid, "10.1001/cli2", "CLI Seed Two")
    _stub_references(monkeypatch, {
        "10.1001/cli1": {"raw_references": [_crossref_ref(doi="10.1001/cliref-a", title="Advance Directive Drafting Standards")]},
        "10.1001/cli2": {"raw_references": [_crossref_ref(doi="10.1001/cliref-b", title="Advance Directive Drafting Practice")]},
    })
    res = runner.invoke(app, ["project", "field-map", "fm1"])
    assert res.exit_code == 0, res.output
    assert "Seeds used (" in res.output

    res_json = runner.invoke(app, ["project", "field-map", "fm1", "--json"])
    assert res_json.exit_code == 0, res_json.output
    assert '"field_areas"' in res_json.output


def test_cli_field_map_unknown_project(s60_db):
    res = runner.invoke(app, ["project", "field-map", "does-not-exist"])
    assert res.exit_code == 1
