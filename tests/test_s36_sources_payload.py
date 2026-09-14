"""S36 — /api/sources ran the whole research pass twice to score 471 skipped rows (0.63.21). (Sorts after test_s35.)

The Sources tab asks for `?project_id=…&limit=2000`. Measured on Kyle's project, that is **1,348 rows and
3,276 KB in 13.2 s cold**, and the cost was not the payload:

```
sources:potential_setup   6.18 s   ← the gap-terms build
rv.load.planner           5.3  s   ← inside it, via research_view.questions/areas
sources:rows              0.98 s
everything else           ≤ 0.35 s each
```

Three faults, each a different kind:

**1. `_planner_dependent` scanned a list per Claim.** 16,191 Claims × 1,804 plan evidence entries = **87 million**
evaluations of `sid in srcs`. The test is anchored on the source id, so the labels belong in a dict keyed by it —
and an entry with **no** `source_id` can never satisfy the test, so it is dropped once rather than 16,191 times.
Every one of his 1,804 entries is unanchored (`kind: "user"` constraints have no source by definition, and his
pinned findings carried none), so the index is empty and the existing early return answers in microseconds what
took seconds to prove. Labels are also tokenised once instead of per Claim. Verified identical on all three of
his projects.

**2. The endpoint kept its own copy of an answer another cache already had**, and its lambda called `_gap_terms`
**twice** — once for the `*` unpack and once to build the index from it. So a cold request ran questions + areas
over 16,000 Claims twice. Same defect as 0.62.1's `claims.ensure` calling `assess_project` and then
`knowledge.refresh`, which calls it again. It now shares `candidates.gap_terms_cached`, so there is ONE entry and
the background warm-up that keeps the pool warm keeps this warm too.

**3. Then the payload, three keys and three different answers** (the 0.62.7 pattern):

| key | was | reader | verdict |
|---|---|---|---|
| `analysis` | 248 KB, 25% | none — the UI's hits are `p.analysis` and the separate `s.analysis_job` | dropped, `?analysis=1` |
| `summary` | 214 KB, 22% | one muted line per row | clipped at `LIST_SUMMARY_CHARS`, whole on `/api/sources/{id}` |
| `value.claims` / `.importance` | 40 KB | none | dropped |
| the rest of `value` | | **the client filters and sorts on it** | kept |

That last row is why you grep before dropping, and my first grep was **wrong**: `value.score` had zero hits
because `web/index.html` aliases the object — `const v = s => s.value || {}` — so `v(s).matters`,
`v(s).never_used`, `v(b).score` and `v(a).used.plan_evidence` are four real consumers a naive search cannot see.

**13.20 s → 5.76 s cold, 0.68 s → 0.53 s warm, 3,276 KB → 2,352 KB**, and the remaining cold cost is warmed in
the background. What is left is mostly repeated key names across 1,348 rows; going further means paging the list
server-side or a compact wire format, and both are Kyle's decision rather than an optimisation.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_srcp_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import claims, db, research_view  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _plain(project_id: str, cl: list[dict]) -> set[str]:
    """The pre-0.63.21 implementation, kept here as the definition the fast path must reproduce."""
    plan = db.latest_plan(project_id)
    if not plan:
        return set()
    emap = (plan.get("plan") or {}).get("_evidence") or {}
    labels = [(v.get("source_id"), v.get("label") or "") for v in emap.values()]
    if not labels:
        return set()
    by_claim = claims.evidence_source_ids(project_id)
    dep = set()
    for c in cl:
        srcs = c.get("evidence_source_ids") or by_claim.get(c["id"]) or set()
        if any(sid in srcs and claims.overlap(lbl, c["text"]) >= 0.5 for sid, lbl in labels):
            dep.add(c["id"])
    return dep


def _project_with_plan(evidence: dict) -> tuple[str, list[dict]]:
    p = db.create_project("deps", brief="buying accounting firms")["id"]
    s1 = db.upsert_source(platform="youtube", external_id="d1", url="https://youtu.be/d1", title="Seller notes")
    s2 = db.upsert_source(platform="youtube", external_id="d2", url="https://youtu.be/d2", title="Lender terms")
    db.add_project_sources(p, [s1["id"], s2["id"]])
    ids = {"s1": s1["id"], "s2": s2["id"]}
    emap = {k: {**v, **({"source_id": ids[v["source_id"]]} if v.get("source_id") in ids else {})}
            for k, v in evidence.items()}
    body = {"_evidence": emap, "goal": {"outcome": "buy a firm"}}
    db.save_plan(p, body, {"sources": [], "facts": []})
    return p, ids


def _claim(project_id: str, text: str, source_id: str | None) -> str:
    cid = claims.add_claim(project_id, text, claim_type="rule")["id"]
    if source_id:
        claims.add_evidence(cid, source_id, locator="00:00", excerpt=text, relation="SUPPORTS")
    return cid


# ------------------------------------------------------------------ _planner_dependent

def test_an_unanchored_plan_entry_can_never_match_so_it_is_not_work(fresh):
    """His whole plan is unanchored: 1,804 entries, none with a source id, and the old loop evaluated
    `None in srcs` 87 million times to reach the empty set it could have reached at the top."""
    p, _ = _project_with_plan({"U1": {"label": "constraint: household earns W2", "link": None, "kind": "user"},
                               "F1": {"label": "pinned finding", "link": None, "kind": "research"}})
    cl = [c for c in claims.list_for_project(p, with_evidence=False) if c["status"] != "superseded"]
    assert research_view._planner_dependent(p, cl) == set() == _plain(p, cl)


def test_an_anchored_entry_still_finds_the_claim_it_matches(fresh):
    """The property the function exists for: a plan label that matches a Claim's text, on a source the Claim
    actually rests on. Dropping the unanchored entries must not drop this."""
    text = "the seller keeps working through two full tax seasons after closing"
    p, ids = _project_with_plan({"U1": {"label": "constraint: user earns W2", "link": None, "kind": "user"},
                                 "S1": {"label": text, "link": None, "kind": "research", "source_id": "s1"}})
    cid = _claim(p, text, ids["s1"])
    cl = [c for c in claims.list_for_project(p, with_evidence=False) if c["status"] != "superseded"]
    dep = research_view._planner_dependent(p, cl)
    assert cid in dep and dep == _plain(p, cl)


def test_a_matching_label_on_the_wrong_source_does_not_count(fresh):
    """The source anchor is the point: the same words on a source the Claim does not rest on is not dependence."""
    text = "the seller keeps working through two full tax seasons after closing"
    p, ids = _project_with_plan({"S2": {"label": text, "link": None, "kind": "research", "source_id": "s2"}})
    cid = _claim(p, text, ids["s1"])
    cl = [c for c in claims.list_for_project(p, with_evidence=False) if c["status"] != "superseded"]
    assert cid not in research_view._planner_dependent(p, cl)
    assert research_view._planner_dependent(p, cl) == _plain(p, cl)


def test_a_source_match_with_unrelated_words_does_not_count(fresh):
    """Both halves of the `and` still hold: the right source is not enough without the overlap."""
    p, ids = _project_with_plan({"S1": {"label": "guarantee fee rates above three hundred thousand dollars",
                                        "link": None, "kind": "research", "source_id": "s1"}})
    cid = _claim(p, "the seller keeps working through two full tax seasons after closing", ids["s1"])
    cl = [c for c in claims.list_for_project(p, with_evidence=False) if c["status"] != "superseded"]
    assert cid not in research_view._planner_dependent(p, cl)
    assert research_view._planner_dependent(p, cl) == _plain(p, cl)


def test_no_plan_at_all_is_not_an_error(fresh):
    p = db.create_project("noplan", brief="b")["id"]
    assert research_view._planner_dependent(p, []) == set()


def test_the_overlap_helper_matches_the_definition_it_replaced():
    """`_token_overlap` is `claims.overlap` on sets computed once — same number, or the fast path is a new rule."""
    for a, b in [("the seller keeps working two tax seasons", "seller keeps working through two full tax seasons"),
                 ("guarantee fee rates", "the seller note standby rule"),
                 ("", "anything at all"), ("one two three", "one two three")]:
        assert research_view._token_overlap(claims._tokens(a), claims._tokens(b)) == claims.overlap(a, b)


# ------------------------------------------------------------------ the payload

def _row(project_id: str, **kw):
    from neurosearch import api
    rows = api.api_sources(project_id=project_id, **kw)
    assert rows
    return rows[0]


def test_the_provenance_blob_is_absent_by_default_and_available_on_request(fresh):
    p = db.create_project("pay", brief="b")["id"]
    s = db.upsert_source(platform="youtube", external_id="p1", url="https://youtu.be/p1", title="t", status="ready")
    db.add_project_sources(p, [s["id"]])
    assert "analysis" not in _row(p)
    assert "analysis" in _row(p, analysis=True)


def test_the_derived_facts_a_screen_uses_are_still_columns(fresh):
    """Dropping the blob must not drop what the row renders from it."""
    p = db.create_project("pay", brief="b")["id"]
    s = db.upsert_source(platform="youtube", external_id="p2", url="https://youtu.be/p2", title="t", status="ready")
    db.add_project_sources(p, [s["id"]])
    r = _row(p)
    for k in ("summary", "substance", "depth", "legacy_analysis", "relevance", "relevance_why"):
        assert k in r, k


def test_the_summary_is_one_line_in_the_list_and_whole_on_the_source(fresh):
    from neurosearch import api
    p = db.create_project("pay", brief="b")["id"]
    s = db.upsert_source(platform="youtube", external_id="p3", url="https://youtu.be/p3", title="t", status="ready")
    db.add_project_sources(p, [s["id"]])
    long = "x" * (api.LIST_SUMMARY_CHARS * 3)
    db.upsert_analysis(p, s["id"], "summary", summary=long, prompt_version="findings-test", input_hash="h1")
    row = _row(p)
    assert len(row["summary"]) == api.LIST_SUMMARY_CHARS + 1 and row["summary"].endswith("…")
    whole = [a for a in api.api_source(s["id"])["analyses"] if a["analysis_kind"] == "summary"][0]
    assert whole["summary"] == long


def test_the_value_fields_the_client_filters_and_sorts_on_are_all_present(fresh):
    """`const v = s => s.value || {}` hides these from a naive grep, so they are asserted by name: the Sources
    filters (`matters`, `stale`, `never_used`) and sorts (`score`, `used.plan_evidence`) read every one."""
    p = db.create_project("pay", brief="b")["id"]
    s = db.upsert_source(platform="youtube", external_id="p4", url="https://youtu.be/p4", title="t", status="ready")
    db.add_project_sources(p, [s["id"]])
    v = _row(p)["value"]
    for k in ("score", "label", "matters", "never_used", "used", "stale", "stale_status", "stale_reasons"):
        assert k in v, k
    for k in ("plan_evidence", "chat_citations"):
        assert k in v["used"], k
    for k in ("claims", "importance"):                  # nested, and nothing anywhere reads them
        assert k not in v, k
