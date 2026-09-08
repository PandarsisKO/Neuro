"""D1 — deep content (0.39.0): the suggested-findings cap is LENGTH-AWARE (12 + 8 per extra window, max 120), every window
contributes at least its top 3 (coverage floor), and validated findings beyond the cap are kept as `reserve` notes —
promotable, never exported, never planned on, never harvested into Claims. A one-window source is byte-identical to the
old top-12 by importance. (Sorts after test_n2.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_deep_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, findings, ingest, jobs, planner  # noqa: E402
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
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _f(imp, tag):
    return {"title": f"{tag} {imp}", "finding": f"finding {tag} {imp}", "ts": "0:10", "quote": "q", "importance": imp}


# ---------------------------------------------------------------- the selection rule (pure)

def test_cap_grows_with_length_and_is_bounded():
    assert findings.cap_for(1) == 12 and findings.cap_for(2) == 20 and findings.cap_for(4) == 36
    assert findings.cap_for(50) == findings.CAP_MAX == 120


def test_one_window_source_is_exactly_the_old_top_twelve():
    ws = [[_f(i % 5 + 1, f"a{i}") for i in range(20)]]
    sug, res = findings.select_findings(ws)
    assert len(sug) == 12 and len(res) == 8
    assert [f["importance"] for f in sug] == sorted((f["importance"] for f in sug), reverse=True)
    assert min(f["importance"] for f in sug) >= max(f["importance"] for f in res)     # nothing in reserve outranks a suggestion


def test_every_window_contributes_and_the_rest_is_reserve(monkeypatch):
    monkeypatch.setattr(findings, "CAP_BASE", 4)
    monkeypatch.setattr(findings, "CAP_PER_WINDOW", 1)
    monkeypatch.setattr(findings, "COVERAGE_FLOOR", 1)
    # window 0 is loud (all importance 5), window 3 is quiet (all importance 1): the floor still keeps one from the quiet window
    ws = [[_f(5, "w0") for _ in range(5)], [_f(4, "w1") for _ in range(5)], [_f(3, "w2") for _ in range(5)], [_f(1, "w3") for _ in range(5)]]
    sug, res = findings.select_findings(ws)
    assert len(sug) == 7 and len(res) == 13                       # cap 4 + 1×3 = 7
    assert any(f["title"].startswith("w3") for f in sug), "the coverage floor guarantees the quiet window a seat"
    assert [f["importance"] for f in sug][:4] == [5, 5, 5, 5]
    assert findings.select_findings(ws) == (sug, res), "deterministic"


# ---------------------------------------------------------------- through the real pipeline (fake model, multi-window transcript)

def _long_transcript(n_windows: int) -> str:
    # each window ≈ WINDOW_CHARS; lines carry the brief's words so the fake rates them and quotes them verbatim
    lines = []
    t = 0
    per = max(1, findings.WINDOW_CHARS // 100)
    for w in range(n_windows):
        for i in range(per):
            m, s = divmod(t, 60)
            lines.append(f"{m}:{s:02d} hosting note {w}-{i}: cloudflare pages is free hosting for static sites with no bandwidth bill and a generous edge cache for part {w}")
            t += 7
    return "\n".join(lines)


def test_multi_window_source_keeps_the_overflow_as_reserve(monkeypatch):
    p = db.create_project("Deep", "hosting")
    r = ingest.ingest_text("Long hosting course", _long_transcript(4), project_id=p["id"])
    wins = findings._windows(db.get_segments(r["source_id"]), "text")
    assert len(wins) >= 3
    monkeypatch.setattr(findings, "CAP_BASE", 3)
    monkeypatch.setattr(findings, "CAP_PER_WINDOW", 1)
    monkeypatch.setattr(findings, "COVERAGE_FLOOR", 1)
    out = findings.suggest_for_source(p["id"], r["source_id"], force=True)
    assert out["windows"] == len(wins) and out["cap"] == findings.cap_for(len(wins))
    sug = db.list_project_notes(p["id"], status="suggested")
    res = db.list_project_notes(p["id"], status="reserve")
    assert len(sug) == out["cap"] and len(res) == out["reserve"] >= 1
    assert all(n["source_id"] == r["source_id"] and n["citations"] for n in res)
    # reserve never reaches what exports / the planner / Claims read
    assert db.list_project_notes(p["id"]) == [] and db.list_project_notes(p["id"], status="approved") == []
    claims.ensure(p["id"])
    assert not any(any(e.get("note_id") == n["id"] for e in c.get("evidence") or []) for c in claims.list_for_project(p["id"]) for n in res)
    pj = api.api_project(p["id"])
    assert len(pj["suggested"]) == len(sug) and all(n["status"] != "reserve" for n in pj["suggested"])
    # the sources listing counts it; the notes endpoint lists it; promotion moves it into the normal flow
    row = next(s for s in api.api_sources(project_id=p["id"]) if s["id"] == r["source_id"])
    assert row["reserve"] == len(res) and row["suggested"] == len(sug)
    listed = api.api_list_notes(p["id"], status="reserve", source_id=r["source_id"])
    assert listed["total"] == len(res)
    api.api_note_status(res[0]["id"], api.NoteStatusIn(status="approved"))
    assert len(db.list_project_notes(p["id"], status="approved")) == 1
    # a re-analysis replaces suggested AND reserve rows (never the approved one)
    findings.suggest_for_source(p["id"], r["source_id"], force=True)
    assert len(db.list_project_notes(p["id"], status="approved")) == 1
    assert len(db.list_project_notes(p["id"], status="reserve")) == out["reserve"]


def test_short_source_has_no_reserve_and_unchanged_count():
    p = db.create_project("Short", "hosting")
    r = ingest.ingest_text("Hosting talk", "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks", project_id=p["id"])
    out = findings.suggest_for_source(p["id"], r["source_id"], force=True)
    assert out["windows"] == 1 and out["cap"] == 12 and out["reserve"] == 0 and out["suggested"] == 2


# ---------------------------------------------------------------- D2 Read deeper

def test_read_deeper_uses_smaller_windows_and_is_current_on_its_own_terms(monkeypatch):
    from neurosearch import staleness
    p = db.create_project("Deep2", "hosting")
    r = ingest.ingest_text("Long hosting course", _long_transcript(3), project_id=p["id"])
    calls = []
    real_call = findings._call

    def spy(system, user, *a, **k):
        calls.append(user)
        return real_call(system, user, *a, **k)
    monkeypatch.setattr(findings, "_call", spy)
    ordinary = findings.suggest_for_source(p["id"], r["source_id"], force=True)
    n_ord = len(calls); calls.clear()
    assert ordinary["depth"] is None and not any(findings.DEPTH_INSTRUCTION in u for u in calls)
    assert findings.is_current(db.get_project(p["id"]), r["source_id"]) and not findings.is_current(db.get_project(p["id"]), r["source_id"], depth="deep")
    deep = findings.suggest_for_source(p["id"], r["source_id"], depth="deep")       # no force needed: a deep request is not satisfied by an ordinary analysis
    assert deep["depth"] == "deep" and deep["windows"] > ordinary["windows"] and len(calls) > n_ord
    assert all(findings.DEPTH_INSTRUCTION in u for u in calls), "the depth instruction rides in the USER message"
    assert findings.prompt_version() == db.get_analysis(p["id"], r["source_id"], "summary")["prompt_version"]   # the frozen system prompt is untouched
    a = db.get_analysis(p["id"], r["source_id"], "summary")
    assert a["depth"] == "deep" and a["input_hash"] == findings.input_hash(p, r["source_id"], depth="deep")
    # current: for an ordinary request AND a deep one; staleness agrees (it hashes with the stored depth)
    assert findings.is_current(db.get_project(p["id"]), r["source_id"]) and findings.is_current(db.get_project(p["id"]), r["source_id"], depth="deep")
    st = staleness.assess(p["id"])
    assert next(x for x in st["sources"] if x["source_id"] == r["source_id"])["status"] == "current"
    row = next(s for s in api.api_sources(project_id=p["id"]) if s["id"] == r["source_id"])
    assert row["depth"] == "deep" and row["analysis"]["summary"]["depth"] == "deep"
    # a brief edit stales the deep analysis like any other
    db.update_project(p["id"], brief="hosting and email deliverability")
    assert not findings.is_current(db.get_project(p["id"]), r["source_id"], depth="deep")


def test_read_deeper_api_is_interactive_only_and_long_is_flagged():
    p = db.create_project("Deep3", "hosting")
    r = ingest.ingest_text("Short", "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill", project_id=p["id"])
    with pytest.raises(Exception) as ei:
        api.api_suggest(p["id"], api.SuggestIn(source_ids=[r["source_id"]], depth="deep", transport="batch"))
    assert "interactively" in str(ei.value)
    out = api.api_suggest(p["id"], api.SuggestIn(source_ids=[r["source_id"]], depth="deep"))
    job = db.get_job(out["job"])
    assert job["kind"] == "suggest_findings" and job["payload"]["depth"] == "deep" and job["payload"]["force"] is True
    assert findings.is_long({"platform": "book"}) and findings.is_long({"platform": "youtube", "duration": 3000}) and not findings.is_long({"platform": "youtube", "duration": 600})


def test_under_read_flag_marks_long_sources_at_the_old_cap(monkeypatch):
    p = db.create_project("Deep4", "hosting")
    r = ingest.ingest_text("Long hosting course", _long_transcript(3), project_id=p["id"])
    src = db.get_source(r["source_id"])
    db.upsert_source(platform=src["platform"], external_id=src["external_id"], url=src["url"], duration=4000)
    findings.suggest_for_source(p["id"], r["source_id"], force=True)
    row = next(s for s in api.api_sources(project_id=p["id"]) if s["id"] == r["source_id"])
    assert row["long"] and row["analysed"]
    assert row["under_read"] == ((row["approved"] + row["suggested"]) <= findings.CAP_BASE)
    findings.suggest_for_source(p["id"], r["source_id"], depth="deep")
    row = next(s for s in api.api_sources(project_id=p["id"]) if s["id"] == r["source_id"])
    assert row["depth"] == "deep" and row["under_read"] is False
