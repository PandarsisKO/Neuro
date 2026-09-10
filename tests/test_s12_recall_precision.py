"""S12 — library recall precision, and links that actually resolve (0.60.2). (Sorts after test_s11.)

Kyle, testing a new AI-UI/UX project against a library built mostly from business and real-estate research:
*"it clearly is pulling bad data ... furthermore, is this searching against the global library? global library is
useful but only if its utilizing the projects criteria/brief/tags/chat etc."* The card offered **"How To Make
$3,000/mo From Airbnb With $0"** as the single **strong** match, pre-ticked.

Measured on his own library (1,219 sources with chunks, the query he actually typed — "enterprise UX complex
workflows"), three faults, and the obvious fix was wrong:

* `_tokens` required THREE characters, so **"ux" was never a query term** — the UI's own line read "2 of 3 query
  terms". Two-letter words are the domain anchors of whole fields: ux, ui, ai, qa, 3d.
* coverage counted the **union of three passages**, so a source could cover a query by mentioning different words
  in three unrelated places. 44 of the 63 passing sources did so only that way.
* every term counted the same, so the two most generic words were enough.
* **IDF weighting — the obvious fix — was measured first and rejects NONE of the 63.** His query's words have
  similar rarity (enterprise 2.62, ux 2.95, complex 1.80, workflows 2.79). What works is requiring the query's
  rarest word to appear in the source at all: 66 → 25, and `strong` 8 → 1 (Pencil & Paper, a UX design studio),
  with Hormozi ×4, a laundromat podcast and "If I Wanted to Become a Millionaire in 2026" all rejected.

And separately: *"discover is routinely suggesting content that has 404 issues"* — a URL from the model's memory is
a remembered address, and blogs move.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_recall_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import bootstrap, db, discover, library, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _source(sid, title, text, channel="ch"):
    with db.tx() as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id, url, title, channel, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?)", (sid, "youtube", sid, f"https://x/{sid}", title, channel, "ready", 1.0, 1.0))
        for i, chunk in enumerate(text):
            conn.execute("INSERT INTO chunks (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
                         (sid, i, i * 60.0, i * 60.0 + 60.0, chunk))


# ------------------------------------------------------------------ the tokenizer

def test_two_letter_terms_are_query_terms():
    """The one-character bug behind the whole complaint: "ux" was dropped before anything was compared."""
    assert library._tokens("enterprise UX complex workflows") == {"enterprise", "ux", "complex", "workflows"}
    assert "ai" in library._tokens("ai agents for qa")
    assert "qa" in library._tokens("ai agents for qa")


def test_a_bare_number_is_not_a_topic():
    t = library._tokens("millionaire in 2026 with 10x growth")
    assert "2026" not in t and "10x" in t


def test_bootstrap_uses_the_same_tokenizer():
    assert bootstrap._content_tokens("enterprise UX") == {"enterprise", "ux"}


# ------------------------------------------------------------------ the anchor

def test_the_anchor_is_the_rarest_word_and_says_why(lib):
    # two sources must know the word for it to separate topics at all (ANCHOR_MIN_SOURCES) — on Kyle's library
    # "ux" is in 64 of 1,219, which is exactly the shape this fixture is standing in for
    _source("a", "UX for complex enterprise workflows", ["progressive disclosure in ux for complex enterprise workflows"])
    _source("a2", "UX patterns", ["ux patterns for data tables"])
    _source("b", "Business growth", ["complex enterprise workflows for business growth"] * 3)
    _source("c", "More business", ["complex enterprise workflows again"])
    a = library.query_anchor({"enterprise", "ux", "complex", "workflows"})
    assert a["term"] == "ux"
    assert a["sources"] == 2 and a["of_sources"] == 4
    assert "rarest word" in a["reason"]


def test_a_source_that_never_says_the_anchor_is_not_suggested(lib):
    """The Airbnb case, in miniature: matching the generic words is not a match."""
    _source("ux1", "UX for complex enterprise workflows",
            ["progressive disclosure in ux for complex enterprise workflows", "ux patterns for dashboards"])
    _source("ux2", "Another UX source", ["ux writing for enterprise tools"])
    _source("biz", "The Mathematics of Business",
            ["complex enterprise workflows and margins", "workflows that scale", "enterprise buyers"])
    # the library this stands in for is mostly about other subjects: that is what makes "ux" the rare word
    for i in range(6):
        _source(f"biz{i}", f"Business {i}", [f"complex enterprise workflows and margins {i}", "workflows that scale"])
    r = library.recall(None, "enterprise UX complex workflows")
    ids = [s["source_id"] for s in r["suggestions"]]
    assert "ux1" in ids and "biz" not in ids
    assert r["anchor"]["term"] == "ux"
    assert r["rejected"]["no_anchor_term"] >= 1
    assert "never say" in (r["note"] or "")


def test_the_anchor_is_checked_against_the_whole_source_not_the_passage(lib):
    """A source can be about your distinctive term and not use it in the three chunks that scored highest. That is
    a property of retrieval, not of the source — and checking only the passages made the rule reject everything in
    a nine-source fixture."""
    _source("s1", "Design systems", ["complex enterprise workflows in practice"] * 2 + ["a chapter about ux research"])
    _source("s2", "Ux studio", ["ux ux ux"] * 3)
    _source("s3", "Ux writing", ["ux writing basics"])
    ids = [s["source_id"] for s in library.recall(None, "enterprise UX complex workflows")["suggestions"]]
    assert "s1" in ids


def test_a_long_prose_query_has_no_anchor(lib):
    """`bootstrap._clauses` splits a goal for this same reason: the rarest word of a whole brief is incidental.
    Both guards turn the rule OFF, so neither can invent a false negative."""
    _source("s1", "SBA loans", ["what documents the lender asks for with an sba loan"])
    long_q = ("what documents will the lender ask for with an sba loan when buying a laundromat business "
              "including the seller note and the equity injection and the standby terms")
    a = library.query_anchor(library._tokens(long_q))
    assert a["term"] is None and "prose" in a["reason"]


def test_a_word_only_one_source_uses_cannot_anchor(lib):
    _source("s1", "One offy", ["a unicorn hapax term nobody else uses"])
    _source("s2", "Business", ["business and workflows"])
    a = library.query_anchor({"hapax", "workflows"})
    assert a["term"] is None and "too few sources" in a["reason"]


def test_a_one_word_query_is_not_anchored(lib):
    _source("s1", "x", ["workflows"])
    assert library.query_anchor({"workflows"})["term"] is None


def test_term_rarity_comes_from_the_search_index(lib):
    _source("a", "t", ["ux and dashboards"])
    _source("b", "t", ["business and margins"])
    _source("c", "t", ["business and workflows"])
    assert library.term_df("ux") == 1                     # chunk-level view
    assert library.term_df("business") == 2
    assert library.sources_with_term("ux") == {"a"}       # what the anchor actually counts


# ------------------------------------------------------------------ strong means one passage, not three

def test_strong_needs_one_passage_that_clears_the_bar(lib):
    """`strong` is the band the bootstrap card PRE-TICKS, so it is the one that misleads. Kyle's screenshot called
    an Airbnb income video the project's one strong match."""
    scattered = {"queries": ["q1", "q2"], "coverage": 0.75, "passage_coverage": 0.25}
    focused = {"queries": ["q1", "q2"], "coverage": 0.75, "passage_coverage": 0.75}
    assert bootstrap._band(scattered) == "possible"
    assert bootstrap._band(focused) == "strong"


def test_an_older_row_without_the_measure_still_bands(lib):
    assert bootstrap._band({"queries": ["q1", "q2"], "coverage": 0.75}) == "strong"


def test_recall_reports_the_best_single_passage(lib):
    _source("s1", "Ux", ["ux for complex enterprise workflows all in one passage"])
    r = library.recall(None, "enterprise UX complex workflows")
    assert r["suggestions"][0]["passage_coverage"] == 1.0


# ------------------------------------------------------------------ the project's own words

def test_tags_are_part_of_what_the_scan_searches(lib):
    """Kyle: "global library is useful but only if its utilizing the projects criteria/brief/tags". Tags were the
    cheapest of those and were simply never read."""
    qs = bootstrap.queries_for({"goal": "design better software for people", "tags": ["ux", "design systems"]})
    assert any("ux" in q for q in qs)


def test_no_tags_changes_nothing(lib):
    a = bootstrap.queries_for({"goal": "buy a laundromat business with an sba loan and a seller note"})
    b = bootstrap.queries_for({"goal": "buy a laundromat business with an sba loan and a seller note", "tags": []})
    assert a == b


# ------------------------------------------------------------------ links that resolve

def test_a_404_is_recorded_and_the_site_root_is_offered(lib, monkeypatch):
    """Kyle's screenshot: https://37signals.com/blog, added from Discover, failed 404 in the queue. The check is
    free, so the user should never have had to find that out by clicking."""
    seen = []

    class R:
        def __init__(self, status, url):
            self.status, self.url, self.body, self.content_type, self.headers = status, url, b"", "text/html", {}

    def fake(url, **kw):
        seen.append(url)
        return R(404 if url.rstrip("/").endswith("/blog") else 200, url)

    monkeypatch.setattr(safe_fetch, "safe_fetch", fake)
    out = discover.check_link("https://37signals.com/blog")
    assert out["status"] == "not_found" and out["http"] == 404
    assert out["suggested_url"] == "https://37signals.com/"
    assert seen == ["https://37signals.com/blog", "https://37signals.com/"]


def test_a_403_is_not_called_missing(lib, monkeypatch):
    """A server refusing us usually means the page is there. Hiding it would lose a real source."""
    class R:
        status, url, body, content_type, headers = 403, "https://x/y", b"", "text/html", {}
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda url, **kw: R())
    out = discover.check_link("https://x/y")
    assert out["status"] == "blocked" and "suggested_url" not in out


def test_a_refusal_by_the_boundary_is_its_own_answer(lib, monkeypatch):
    def boom(url, **kw):
        raise safe_fetch.FetchBlocked("private_address", "that address is on a private network")
    monkeypatch.setattr(safe_fetch, "safe_fetch", boom)
    assert discover.check_link("https://x/y")["status"] == "refused"


def test_a_check_that_explodes_never_fails_the_run(lib, monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(safe_fetch, "safe_fetch", boom)
    assert discover.check_link("https://x/y")["status"] == "unreachable"


def test_the_results_land_on_the_discovery_rows(lib, monkeypatch):
    p = db.create_project("disc", brief="b")
    rows = db.add_discoveries(p["id"], [{"name": "37signals blog", "kind": "website", "url": "https://37signals.com/blog", "fit": 4},
                                        {"name": "Live one", "kind": "website", "url": "https://good.example/ok", "fit": 4}])

    class R:
        def __init__(self, status, url):
            self.status, self.url, self.body, self.content_type, self.headers = status, url, b"", "text/html", {}
    monkeypatch.setattr(safe_fetch, "safe_fetch",
                        lambda url, **kw: R(404 if "37signals.com/blog" in url else 200, url))
    out = discover.check_links(rows)
    assert out["checked"] == 2 and out["dead"] == 1 and out["by_status"]["not_found"] == 1
    assert "did not resolve" in out["note"]
    stored = {d["name"]: d["link_check"] for d in db.list_discoveries(p["id"])}
    assert stored["37signals blog"]["status"] == "not_found"
    assert stored["Live one"]["status"] == "ok"
    # never rewritten by a machine: the URL on the row is untouched
    assert [d for d in db.list_discoveries(p["id"]) if d["name"] == "37signals blog"][0]["url"] == "https://37signals.com/blog"


def test_a_dead_link_is_not_offered_as_something_to_add():
    ui = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "neurosearch", "web", "index.html"), encoding="utf-8").read()
    assert "const dead = lc && (lc.status === 'not_found' || lc.status === 'unreachable')" in ui
    assert "&& !dead ?" in ui
    assert "Add the site instead" in ui
    assert "that address is gone" in ui
    assert "the page is probably there" in ui       # a 403 keeps its link


# ------------------------------------------------------------------ a stored judgement knows what made it (0.60.5)

def test_a_suggestion_records_which_matcher_made_it(lib):
    """Seen on Kyle's actual screen an hour after 0.60.2 shipped: the Airbnb video was still offered as the
    project's one STRONG match, still pre-ticked. The recall fix changed how judgements are made; it could not
    change judgements already stored. So a stored opinion now carries its provenance, exactly as every AI artifact
    in this codebase already does."""
    p = db.create_project("matcher", brief="b")
    db.upsert_project_reuse(p["id"], [{"object_kind": "source", "object_id": "s1", "band": "strong", "score": 1.0,
                                       "why": "{}", "origin": "{}"}], "rev1", scan_version="recall-1")
    st = bootstrap.state(p["id"])
    assert st["scan_version"] == bootstrap.SCAN_VERSION
    assert st["matcher_stale"] is True
    assert st["sources"][0]["from_old_matcher"] is True
    assert "two-letter" in st["matcher_note"] and "free" in st["matcher_note"]


def test_a_row_with_no_version_at_all_counts_as_the_old_one(lib):
    """Every row written before 0.60.5 has a NULL there, and every one of them was made by the old matcher."""
    p = db.create_project("matcher2", brief="b")
    db.upsert_project_reuse(p["id"], [{"object_kind": "source", "object_id": "s1", "band": "possible",
                                       "score": 0.1, "why": "{}", "origin": "{}"}], "rev1")
    assert bootstrap.state(p["id"])["sources"][0]["from_old_matcher"] is True


def test_a_fresh_row_is_not_stale(lib):
    p = db.create_project("matcher3", brief="b")
    db.upsert_project_reuse(p["id"], [{"object_kind": "source", "object_id": "s1", "band": "strong", "score": 1.0,
                                       "why": "{}", "origin": "{}"}], "rev1",
                            scan_version=bootstrap.SCAN_VERSION)
    st = bootstrap.state(p["id"])
    assert st["matcher_stale"] is False and st["matcher_note"] is None


def test_an_old_suggestion_is_never_pre_ticked():
    ui = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "neurosearch", "web", "index.html"), encoding="utf-8").read()
    assert "h.band === 'strong' && !h.from_old_matcher ? 'checked' : ''" in ui
    assert "older matcher" in ui
    assert "Scan again — free" in ui


def test_the_scan_stamps_the_current_version(lib, monkeypatch):
    """And a scan re-judges: the row is replaced, not appended to."""
    p = db.create_project("matcher4", brief="b")
    db.upsert_project_reuse(p["id"], [{"object_kind": "source", "object_id": "s1", "band": "strong", "score": 1.0,
                                       "why": "{}", "origin": "{}"}], "rev1", scan_version="recall-1")
    db.upsert_project_reuse(p["id"], [{"object_kind": "source", "object_id": "s1", "band": "possible", "score": 0.2,
                                       "why": "{}", "origin": "{}"}], "rev1",
                            scan_version=bootstrap.SCAN_VERSION)
    rows = db.list_project_reuse(p["id"])
    assert len(rows) == 1 and rows[0]["scan_version"] == bootstrap.SCAN_VERSION and rows[0]["band"] == "possible"


def test_the_link_check_never_touches_the_network_in_tests(lib, monkeypatch):
    """It made a Tier 1 test flaky by timing. A deterministic suite must not depend on DNS."""
    from neurosearch.config import settings as _s
    monkeypatch.setattr(_s, "fake_ai", True)
    called = {"n": 0}
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    out = discover.check_links([{"id": 1, "url": "https://example.com/x"}])
    assert out["checked"] == 0 and called["n"] == 0 and "fake provider" in out["skipped"]
