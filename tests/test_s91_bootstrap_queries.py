"""S91 (2026-09-24) — Kyle: the wealth project never surfaced the Alex Hormozi videos his business project had
ingested, "which feels suspicious". The last scan's queries explained it: the brief's markdown heading
("# Generational Wealth Project Brief"), a mangled first sentence, one real facet at the generic cut, and three
"Corroborate or refute" card-points targets from the first source that landed. Six queries, taken in document order,
half reserved for gaps. The ten concrete areas further down the goal were never searched.

Now: markdown is stripped (headings are labels, not facets), gaps take at most MAX_GAP_QUERIES, and the clauses are
chosen by distinctiveness — the same rarest-known-word measure `query_strength` already reports — not by position."""
from __future__ import annotations

import pathlib

from neurosearch import bootstrap, library

GOAL = """Gio and I are starting a long-term family wealth project focused on building, protecting, and transferring wealth across generations.

The areas we want to focus on include:

Budgeting, cash flow, and net worth tracking

Eliminating harmful debt and using productive debt intelligently

Investing and tax-advantaged accounts

Estate planning, trusts, and generational wealth transfer

Teaching our children financial literacy and responsible stewardship
"""
BRIEF = """# Generational Wealth Project Brief

## Purpose

Gio and I want to build a long-term family wealth strategy focused on financial education, disciplined wealth creation, preservation, and generational transfer.

### Debt and Leverage
- Consumer debt reduction
- Mortgage strategy
- **Productive versus destructive debt**
"""


def test_markdown_headings_and_bullets_are_not_queries():
    plain = bootstrap._plain(BRIEF)
    assert "Project Brief" not in plain and "Purpose" not in plain and "Debt and Leverage" not in plain
    assert "Productive versus destructive debt" in plain and "**" not in plain and "- " not in plain
    assert not any("Brief" in c for c in bootstrap._clauses(BRIEF))


def test_the_most_distinctive_clauses_win_not_the_first_ones(monkeypatch):
    # a fake library: rarity of each clause's anchor word, None = every word is everywhere
    rarity = {"estate": 12, "trusts": 12, "literacy": 9, "stewardship": 9, "tax-advantaged": 15, "advantaged": 15, "investing": 40,
              "budgeting": 30, "mortgage": 25, "consumer": 60, "productive": 70, "generations": 222, "transferring": 222,
              "building": 300, "long-term": 309, "starting": 309}
    def anchor(tokens):
        known = {t: rarity[t] for t in tokens if t in rarity}
        if not known:
            return {"term": None, "too_common": True}
        t = min(known, key=known.get)
        return {"term": t, "sources": known[t]}
    monkeypatch.setattr(library, "query_anchor", anchor)
    from neurosearch import db
    monkeypatch.setattr(db, "sources_with_chunks", lambda: 1590)      # floor = 31.8 sources
    project = {"goal": GOAL, "brief": BRIEF, "questions": [], "tags": []}
    perks = ["lounge access", "airline credits", "hotel status", "rental insurance", "purchase protection", "concierge service"]
    gaps = [{"status": "open", "question": f"Corroborate or refute: the {p} perk trades an annual fee for {p.split()[0]} value"} for p in perks]
    qs = bootstrap.queries_for(project, gaps)
    assert len(qs) <= bootstrap.MAX_QUERIES
    assert sum(q.startswith("Corroborate") for q in qs) == bootstrap.MAX_GAP_QUERIES, "gaps no longer take half the budget"
    joined = " | ".join(qs).lower()
    for must in ("estate planning", "financial literacy", "tax-advantaged", "consumer debt reduction"):
        assert must in joined, (must, qs)
    assert "project brief" not in joined


def test_a_short_goal_is_untouched_and_document_order_is_kept(monkeypatch):
    monkeypatch.setattr(library, "query_anchor", lambda toks: {"term": "x", "sources": 5})
    qs = bootstrap.queries_for({"goal": "Compare index funds against rental property for a family portfolio", "brief": "", "questions": [], "tags": []}, [])
    assert qs == ["Compare index funds against rental property for a family portfolio"]


def test_a_word_in_under_two_percent_of_the_library_is_never_called_generic(monkeypatch):
    """The live run: median rarity 8 → "IRAs and Roth strategies" (26 of 1,590) marked weak. The floor keeps it."""
    from neurosearch import db
    monkeypatch.setattr(db, "sources_with_chunks", lambda: 1590)
    rarity = {"roth": 26, "casualty": 2, "erosion": 2, "stewardship": 3, "destructive": 20, "multi-year": 17, "two-person": 8}
    monkeypatch.setattr(library, "query_anchor", lambda toks: (lambda k: {"term": k, "sources": rarity[k]} if k else {"term": None, "too_common": True})(min((t for t in toks if t in rarity), key=lambda t: rarity[t], default=None)))
    qs = ["IRAs and Roth strategies", "Property and casualty insurance", "Preventing wealth erosion across generations",
          "Teaching our children financial literacy and responsible stewardship", "Productive versus destructive debt",
          "Multi-year tax planning", "Two-person credit card strategies"]
    st = bootstrap.query_strength(qs)
    assert st["cut"] >= 31.8 and st["weak"] == [], st


def test_an_empty_distinctive_query_is_retried_without_its_incidental_anchor(monkeypatch):
    """"Multi-year tax planning" anchors on "multi-year" and finds nothing; searched again as "tax planning"."""
    calls = []
    def recall(pid, q, **k):
        calls.append(q)
        if q == "Multi-year tax planning":
            return {"suggestions": [], "anchor": {"term": "multi-year", "sources": 17}, "scope": 100}
        return {"suggestions": [{"source_id": "s1", "title": "Tax planning for families", "score": 0.5, "coverage": 0.8, "passage_coverage": 0.8,
                                 "chunks": [], "covered_terms": ["tax", "planning"]}], "anchor": {"term": "planning", "sources": 40}, "scope": 100}
    monkeypatch.setattr(library, "recall", recall)
    r = bootstrap._recall_without_anchor("p", "Multi-year tax planning", recall("p", "Multi-year tax planning"), {"goal": "g"})
    assert calls == ["Multi-year tax planning", "tax planning"]
    assert r and r["retried_without"] == "multi-year" and r["suggestions"][0]["source_id"] == "s1"
    # a query whose remainder is a single word is not retried
    assert bootstrap._recall_without_anchor("p", "Roth strategies", {"anchor": {"term": "roth"}, "suggestions": []}, {"goal": "g"}) is None


def test_a_hit_found_only_by_a_shortened_retry_is_possible_never_strong():
    hit = {"passage_coverage": 0.9, "coverage": 0.9, "queries": ["Property and casualty insurance"], "distinctive_queries": [],
           "retried_queries": ["Property and casualty insurance"]}
    assert bootstrap._band(hit) == "possible"
    hit["distinctive_queries"] = ["IRAs and Roth strategies"]; hit["queries"].append("IRAs and Roth strategies")
    assert bootstrap._band(hit) == "strong"


def test_distinctive_but_present_beats_ultra_rare(monkeypatch):
    from neurosearch import db
    monkeypatch.setattr(db, "sources_with_chunks", lambda: 1590)
    rarity = {"roth": 26, "stewardship": 3, "beneficiary": 2, "trusts": 12, "destructive": 20, "generations": 222}
    monkeypatch.setattr(library, "query_anchor", lambda toks: (lambda k: {"term": k, "sources": rarity[k]} if k else {"term": None, "too_common": True})(min((t for t in toks if t in rarity), key=lambda t: rarity[t], default=None)))
    monkeypatch.setattr(bootstrap, "MAX_QUERIES", 4)
    monkeypatch.setattr(bootstrap, "MAX_BROAD_QUERIES", 1)
    cands = ["responsible stewardship", "IRAs and Roth strategies", "Beneficiary planning", "Multi-generational trusts",
             "Productive versus destructive debt", "transferring wealth across generations"]
    qs = bootstrap._most_distinctive(cands)
    # three sharp ones (present-but-distinctive first), and one slot for the broadest facet of the goal
    assert qs == ["IRAs and Roth strategies", "Multi-generational trusts", "Productive versus destructive debt", "transferring wealth across generations"], qs


def test_generic_only_matches_are_one_click_away_not_silently_excluded():
    js = (pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "research.js").read_text()
    assert "const live = BOOT.showWeak ? pending : pending.filter(h => !h.weak_query_only);" in js
    assert "show them too</a>" in js and "BOOT.showWeak=true" in js
    assert "showWeak: false" in js
