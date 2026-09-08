"""Research rebuild R1/R3/R5/R6 (0.37.0) — the decision-first Research view engine (`research_view.py`): a deterministic,
$0 priority order over open questions and watch-outs; watch-outs are ISSUES (grouped by kind and area, never one row per
tension); Research Areas are named from finding titles, never from generic tokens; the sidebar number is what needs the
user, never the Claim count. Zero model calls anywhere. (Sorts after test_m3.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_rview_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, jobs, knowledge, research_view as rv, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture, _note, _page  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(safe_fetch, "safe_fetch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used")))
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _invocations() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]


def _ready(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    claims.ensure(pid)
    knowledge.refresh(pid)
    return pid, ids


# ---------------------------------------------------------------- R3 priority engine

def test_overview_is_deterministic_ranked_and_costs_nothing(monkeypatch):
    pid, _ = _ready(monkeypatch)
    before = _invocations()
    a = rv.overview(pid)
    b = rv.overview(pid)
    assert a == b, "the same state must produce the same view, byte for byte"
    assert _invocations() == before, "the Research view is a $0 surface"
    nxt = a["next"]
    assert nxt and all(x["type"] in ("question", "watchout") for x in nxt)
    assert [x["score"] for x in nxt] == sorted((x["score"] for x in nxt), reverse=True)
    # the stale rates Claim (importance 4, high impact) outranks the lone-viewpoint watch-out and the corroboration question
    assert nxt[0]["type"] == "watchout" and nxt[0]["kind"] == "STALE"
    assert nxt[0]["claims"] == 1 and nxt[0]["title"] == "Guarantee fee rates evidence may be outdated"   # one Claim → titled by ITS label, not the area
    # every item says what to do, what it costs and what happens if ignored — never a raw tension row
    for x in nxt:
        assert x["if_ignored"]
        acts = x["actions"] if x["type"] == "question" else [x["action"]]
        assert acts and all(a_["label"] and a_["cost"] for a_ in acts)
    assert a["summary"]["claims_total"] == 3 and a["summary"]["open_questions"] == 2 and a["summary"]["issues"] >= 1
    assert a["empty"] is False


def test_importance_and_planner_dependence_raise_priority(monkeypatch):
    pid, ids = _ready(monkeypatch)
    qs = rv.questions(pid)
    out = next(q for q in qs if "transition" in q["question"])
    rates = next(q for q in qs if "guarantee" in q["question"].lower())
    assert out["importance"] == 5 and rates["importance"] == 4 and out["score"] > rates["score"]
    assert out["important"] and out["why_asking"].startswith("a finding you rated")
    # a Master Plan step that rests on the outlier's evidence makes its question planner-dependent (+bonus, "why": the plan depends on it)
    src = db.get_source(ids["outlier"])
    db.save_plan(pid, {"steps": [{"title": "Seller transition", "evidence": ["e1"]}], "_evidence": {"e1": {"source_id": ids["outlier"], "label": "Keep the accounting-firm seller through two full tax seasons", "url": src["url"]}}}, "test")
    q2 = next(q for q in rv.questions(pid) if q["id"] == out["id"])
    assert q2["planner_dependent"] and q2["score"] == out["score"] + rv.PLANNER_BONUS and "Master Plan" in q2["why_asking"]


def test_questions_speak_plainly_and_carry_the_escalation_history(monkeypatch):
    pid, ids = _ready(monkeypatch)
    q = next(q for q in rv.questions(pid) if "transition" in q["question"])
    assert q["headline"].startswith("Does anyone else confirm this:") and q["label"] == "Seller transition length"
    assert q["what_settles_it"] == rv.SUFFICIENCY_TEXT["corroborative"] and q["current"].startswith("Evidence so far: weak")
    assert q["already_checked"] == [] and q["known_uncaptured"] == 0
    assert [a["label"] for a in q["actions"]] == ["Search my existing research", "Find new sources online"]
    knowledge.pursue(q["id"], external=False)                    # project → library → candidates; the web was NOT run
    q2 = next(x for x in rv.questions(pid) if x["id"] == q["id"])
    assert q2["already_checked"] == ["This project", "Your library", "Previously seen sources"]
    assert q2["known_uncaptured"] >= 1 and any(a["endpoint"].endswith("/capture-best") for a in q2["actions"])
    assert q2["score"] == q["score"] + rv.KNOWN_SOURCES_BONUS


# ---------------------------------------------------------------- R5 watch-out aggregation

def test_watchouts_are_issues_not_rows(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    # six more stale rate pages, each its own Claim → six more STALE tensions in one area
    texts = ["Lender packaging fees for SBA loans run about 1 percent of the loan amount and lenders reprice those fees every year.",
             "The maximum SBA 7a interest rate cap sits at prime plus 2.75 percent for larger loans and the cap moves with the prime rate.",
             "Business appraisal prices for small accounting practices average 2 percent of the practice value and appraisers raise prices annually.",
             "Closing costs for a practice acquisition typically add 1.5 percent of the purchase price and vary with lender pricing.",
             "Broker commission rates for accounting practice sales run near 10 percent and brokers adjust that percentage every year.",
             "Working-capital line interest rates offered to acquirers sit near 8 percent and reprice quarterly."]
    for i, text in enumerate(texts):
        sid = _page(f"https://www.lenderblog.example.com/pricing-{i}", f"Acquisition pricing note {i}",
                    text + " This note was written for buyers comparing lender quotes and it records the figures the author saw at the time.", published=f"{2019 + i % 3}-01-15")
        db.add_project_sources(pid, [sid])
        _note(pid, sid, text, text, importance=4, locator="§ 1", start=1, title="Guarantee fee rates")
    claims.ensure(pid); knowledge.refresh(pid)
    stale_rows = [t for t in knowledge.list_tensions(pid, status="open") if t["kind"] == "STALE"]
    assert len(stale_rows) >= 7
    ws = rv.watchouts(pid)
    stale_issues = [w for w in ws if w["kind"] == "STALE"]
    assert len(stale_issues) == 1, [w["title"] for w in stale_issues]
    w = stale_issues[0]
    assert w["claims"] == len(stale_rows) and len(w["underlying"]) == len(stale_rows)
    assert "may be outdated" in w["title"] and w["action"]["label"] == "Find current evidence" and w["action"]["cost"] == "$0"
    assert w["detail"].startswith(f"{len(stale_rows)} Claims rel")
    # breadth raises the score but is capped; a single-Claim issue is titled by that Claim's own label, a many-Claim one by its area
    assert w["score"] == rv.BASE["watchout:STALE"] + rv.IMPORTANCE_WEIGHT * 4 + rv.IMPACT["high"] + min(rv.BREADTH_CAP, rv.BREADTH_PER_CLAIM * (len(stale_rows) - 1))
    assert w["area"] in w["title"]


def test_missing_perspective_names_what_is_absent(monkeypatch):
    pid, _ = _ready(monkeypatch)
    mp = [w for w in rv.watchouts(pid) if w["kind"] == "MISSING_PERSPECTIVE"]
    assert mp and "no " in mp[0]["title"] and "voice yet" in mp[0]["title"]
    assert mp[0]["action"]["label"] == "Find the missing perspective"


# ---------------------------------------------------------------- R6 research areas

def test_areas_are_named_from_finding_titles_never_generic_tokens(monkeypatch):
    pid, _ = _ready(monkeypatch)
    ar = rv.areas(pid)
    assert ar["areas"], "a project with Claims has at least one area"
    for a in ar["areas"]:
        low = a["name"].lower()
        assert not any(low == g or low.startswith(g + " ") for g in ("full", "usual", "general", "current")), a["name"]
        assert a["name"].split(" · ")[0] in ("Guarantee fee rates", "Seller note standby rule", "Seller transition length")
        assert a["understand"] and isinstance(a["attention"], list) and a["state"] in ("strong", "developing", "weak", "missing")
    # every topic node maps to exactly one area, small/generic topics are folded rather than shown as their own card
    topics = {n["topic"] for n in db.connect().execute("SELECT topic FROM project_knowledge_nodes WHERE project_id=?", (pid,)).fetchall()}
    assert set(ar["area_of_topic"]) >= topics
    assert len(ar["areas"]) <= len(topics)


def test_area_cards_summarise_state_without_source_counts(monkeypatch):
    pid, _ = _ready(monkeypatch)
    a = rv.areas(pid)["areas"][0]
    assert a["claims"] == 3 and a["strong"] == 1 and a["stale"] == 1 and a["open_questions"] == 2
    assert "well-evidenced conclusion" in a["understand"] and "sources" not in a["understand"]
    assert "2 open questions" in a["attention"] and "1 Claim may be outdated" in a["attention"]


# ---------------------------------------------------------------- attention + API

def test_attention_is_what_needs_the_user_not_the_claim_count(monkeypatch):
    pid, _ = _ready(monkeypatch)
    o = rv.overview(pid)
    imp_q = [q for q in rv.questions(pid) if q["status"] == "open" and q["important"]]
    hi_w = [w for w in rv.watchouts(pid) if w["impact"] in rv.WATCHOUT_ATTENTION_IMPACTS]
    assert o["attention"] == len(imp_q) + len(hi_w) + o["summary"]["claims_awaiting_decision"]
    assert rv.attention(pid) == o["attention"]
    # settling questions and accepting the strong Claim lowers the number; the Claim count does not move
    n_claims = len(claims.list_for_project(pid))
    for q in imp_q:
        knowledge.set_target_status(q["id"], "closed_by_user")
    for c in claims.list_for_project(pid):
        if c["strength"] == "strong" and c["status"] == "proposed":
            claims.set_status(c["id"], "accepted")
    knowledge.refresh(pid)
    o2 = rv.overview(pid)
    assert o2["attention"] < o["attention"] and o2["summary"]["claims_awaiting_decision"] == 0
    assert len(claims.list_for_project(pid)) == n_claims
    # an empty project: zero attention, an explicit empty flag, no crash
    empty = db.create_project("Empty", "nothing yet")["id"]
    e = rv.overview(empty)
    assert e["empty"] is True and e["attention"] == 0 and e["next"] == [] and e["areas"] == []


def test_api_surfaces_the_view_and_the_state_carries_attention(monkeypatch):
    pid, _ = _ready(monkeypatch)
    o = api.api_research_overview(pid)
    assert o["next"] and o["summary"]["claims_total"] == 3
    st = api.api_research(pid)
    assert st["attention"] == o["attention"] and st["attention"] != len(st["claims"]) or st["attention"] == o["attention"]
    qs = api.api_research_questions(pid, status="open")
    assert qs["total"] == 2 and all(q["status"] == "open" for q in qs["questions"])
    ws = api.api_research_watchouts(pid)
    assert ws["total"] == len(ws["watchouts"]) >= 1
    ar = api.api_research_areas(pid)
    assert ar["areas"] and ar["area_of_topic"]
