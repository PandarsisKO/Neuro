"""Mission BOOTSTRAP R1–R3 — a new project starts with what Neuro Search already owns.

The mandatory scenario (BOOTSTRAP-MISSION.md §52, Kyle's own example): a 150-source Finance project is *mostly*
irrelevant to a portfolio-website project and contains a handful of AI/Claude/automation sources that are exactly
relevant. The system must find the subset and leave the rest — which is why the project can never be the unit of
inheritance.

What is gated here is not "did it run". It is the set of things that would make reuse dangerous:
nothing is re-acquired, nothing is attached without a decision, and no interpretation crosses a project boundary
— no chat, no fact, no plan, no finding text. Those are the invariants; the retrieval quality is the feature.
(Sorts after test_r1.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_boot_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import bootstrap, db, ingest, jobs  # noqa: E402
from neurosearch.config import settings  # noqa: E402

H = {"Authorization": "Bearer t0k"}

AI_SOURCES = [
    ("Claude Code architecture for local AI agents",
     "0:05 claude code runs coding agents locally on your own machine\n1:10 local ai hosting keeps automation cost down for a personal website"),
    ("ChatGPT agent workflows for automation",
     "0:20 chatgpt agent workflows automate the boring parts of a personal website\n2:00 local automation beats a monthly saas bill"),
    ("Cutting API cost with local models",
     "0:40 api cost optimization for automation: run the small models locally\n3:00 a personal website can generate custom pages per visitor"),
]
FINANCE_SOURCES = [
    ("SBA 7(a) overview", "0:05 the sba 7a loan program guarantees bank lending for acquisitions\n2:00 equity injection rules"),
    ("Seller financing interview", "0:10 seller financing and standby notes in a small acquisition\n4:00 how sellers think about earnouts"),
    ("Accounting practice acquisition", "0:15 buying an accounting firm: client retention and partner transition\n5:00 tax season cash flow"),
    ("Tax strategy for owners", "0:30 s corp election and reasonable salary for an owner operator\n6:00 depreciation schedules"),
]
GOAL = "Build a modern personal website with local AI automation, and use claude code to generate custom versions."


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def _finance() -> tuple[str, list[str], list[str]]:
    """A mostly-unrelated project holding a small, genuinely relevant subset."""
    p = db.create_project("Finance & Business Acquisition", "buying a business with SBA financing")
    ai = [ingest.ingest_text(t, body, project_id=p["id"])["source_id"] for t, body in AI_SOURCES]
    fin = [ingest.ingest_text(t, body, project_id=p["id"])["source_id"] for t, body in FINANCE_SOURCES]
    return p["id"], ai, fin


def _portfolio(goal: str = GOAL) -> str:
    p = db.create_project("Personal Portfolio Redesign", goal)
    db.update_project(p["id"], goal=goal)
    return p["id"]


# ---------------------------------------------------------------- R1: name + goal

def test_a_project_needs_only_a_name_and_a_goal(client):
    p = client.post("/api/projects", headers=H, json={"name": "Portfolio", "goal": GOAL}).json()
    assert p["goal"] == GOAL
    assert p["brief"] == GOAL, "the brief every model task reads is seeded from the goal, not left empty"
    assert p.get("bootstrap_job"), "a project that knows what it is for starts searching immediately"
    # everything else still round-trips when it IS given
    p2 = client.post("/api/projects", headers=H, json={"name": "Full", "goal": "g", "brief": "a longer brief",
                                                       "audience": "recruiters", "questions": ["what matters?"]}).json()
    assert p2["brief"] == "a longer brief" and p2["audience"] == "recruiters"


# ---------------------------------------------------------------- R2: the scan

def test_the_goal_becomes_several_cheap_searches_and_never_one_bad_one():
    qs = bootstrap.queries_for({"goal": GOAL})
    assert len(qs) >= 2, "a goal with two clauses is two searches"
    assert not any(q == GOAL for q in qs), "the whole goal as one query buries good passages under its own term count"
    # a goal too short to search says so rather than being padded by a model guessing at intent
    assert bootstrap.queries_for({"goal": "Buy a business."}) == []
    pid = _portfolio("Buy a business.")
    r = bootstrap.scan(pid)
    assert r["found"] == 0 and "note" in r


def test_it_finds_the_relevant_subset_of_a_mostly_unrelated_project():
    """§52. This is the whole reason projects cannot be the unit of inheritance."""
    fin_id, ai, fin = _finance()
    pid = _portfolio()
    r = bootstrap.scan(pid)
    got = {h["source_id"] for h in r["sources"]}
    assert got & set(ai), "the AI subset inside Finance was not found"
    assert not (got & set(fin)), f"SBA/tax/seller-financing content must not be surfaced: {got & set(fin)}"
    # the related project is explained by its useful subset, never offered as a bundle
    proj = next(p for p in r["projects"] if p["project_id"] == fin_id)
    assert 0 < proj["relevant"] < proj["total"]
    assert "of" in proj["line"] and proj["overlap"], "the overlap must be named from terms that actually matched"


def test_every_reason_is_a_passage_the_user_can_check():
    _finance()
    pid = _portfolio()
    r = bootstrap.scan(pid)
    assert r["sources"]
    for h in r["sources"]:
        assert h["passages"], "a suggestion with no matching passage has no reason"
        assert h["passages"][0].get("text") and h["passages"][0].get("timestamp")
        assert any("matching passage" in w for w in h["why"])
        assert not any(w.strip().lower().startswith("highly relevant") for w in h["why"])


def test_the_scan_makes_no_generation_call_and_attaches_nothing():
    """The scan's only spend is one query embedding per search — fractions of a cent, and the same call every
    search in the product already makes. It must never reach a generation model: a bootstrap that costs real money
    to *look* at your own library defeats the point of having the library."""
    _finance()
    pid = _portfolio()
    n = lambda k: db.connect().execute("SELECT COUNT(*) FROM usage WHERE kind != 'embed'").fetchone()[0]  # noqa: E731
    before = n("")
    r = bootstrap.scan(pid)
    assert n("") == before, "the scan must make no generation call"
    assert r["sources"] and db.project_source_ids(pid, ready_only=False) == [], "nothing is attached by a scan"
    assert all(row["state"] == "suggested" for row in db.list_project_reuse(pid))


def test_a_rescan_refreshes_why_but_never_un_decides_the_user():
    _finance()
    pid = _portfolio()
    r = bootstrap.scan(pid)
    picked = r["sources"][0]["source_id"]
    bootstrap.decide(pid, [picked], "attach")
    bootstrap.scan(pid)
    row = next(x for x in db.list_project_reuse(pid) if x["object_id"] == picked)
    assert row["state"] == "attached"


# ---------------------------------------------------------------- R3: deciding

def test_attaching_reuses_the_canonical_source_and_never_re_acquires_it():
    fin_id, ai, _ = _finance()
    pid = _portfolio()
    bootstrap.scan(pid)
    src = db.get_source(ai[0])
    chunks_before = len(db.get_chunks(ai[0]))
    n_sources = db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    bootstrap.decide(pid, [ai[0]], "attach")
    assert ai[0] in db.project_source_ids(pid, ready_only=False)
    assert ai[0] in db.project_source_ids(fin_id, ready_only=False), "it stays in the project it came from"
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == n_sources, "no duplicate source row"
    assert len(db.get_chunks(ai[0])) == chunks_before, "chunks and embeddings are reused, never rebuilt"
    assert db.get_source(ai[0])["revision"] == src["revision"]
    assert not [j for j in db.list_jobs(limit=50) if j["kind"] in ("ingest_url", "ingest_source")], "nothing was queued for re-ingestion"


def test_removing_an_inherited_source_never_deletes_it_from_the_library():
    """Remove-from-this-project and delete-from-library are different acts. Reuse makes the difference matter:
    the same row now backs several projects. (Run in-process: conftest's session client holds its own DB
    connection from before these fixtures, see test_p1_perf.)"""
    fin_id, ai, _ = _finance()
    pid = _portfolio()
    bootstrap.scan(pid)
    bootstrap.decide(pid, [ai[0]], "attach")
    db.remove_project_sources(pid, [ai[0]])
    assert ai[0] not in db.project_source_ids(pid, ready_only=False)
    assert db.get_source(ai[0]) is not None, "the canonical source survives"
    assert ai[0] in db.project_source_ids(fin_id, ready_only=False), "and so does every other project's access"
    assert len(db.get_chunks(ai[0])) > 0


def test_a_dismissed_suggestion_stays_dismissed_and_out_of_the_way():
    _finance()
    pid = _portfolio()
    r = bootstrap.scan(pid)
    sid = r["sources"][0]["source_id"]
    bootstrap.decide(pid, [sid], "dismiss")
    st = bootstrap.state(pid)
    assert sid not in {h["source_id"] for h in st["sources"] if h["state"] == "suggested"}
    assert st["counts"]["dismissed"] == 1
    assert sid not in db.project_source_ids(pid, ready_only=False)


# ---------------------------------------------------------------- the isolation invariants

def test_no_interpretation_ever_crosses_a_project_boundary():
    """Evidence is portable; interpretation is not. Chats, facts, plans and finding TEXT stay where they were
    written — including when the source they were written about is reused."""
    fin_id, ai, _ = _finance()
    db.add_fact(fin_id, "constraint", "Budget: $500,000 for the acquisition")
    db.add_project_note(fin_id, "SBA lending favours this deal structure [1]")
    conv = db.create_conversation(fin_id, "financing")["id"]
    db.save_message(conv, "user", "how much can I borrow?", project_id=fin_id)
    pid = _portfolio()
    bootstrap.scan(pid)
    bootstrap.decide(pid, [ai[0]], "attach")

    assert db.list_facts(pid) == []
    assert db.list_project_notes(pid) == []
    assert db.list_conversations(pid) == []
    assert db.get_plan(pid) is None
    # and the reuse row itself carries no text from the other project — only passages from the shared source
    for row in db.list_project_reuse(pid):
        assert "Budget" not in (row["why"] or "") and "SBA lending favours" not in (row["why"] or "")


def test_chat_in_the_new_project_sees_the_reused_source_and_nothing_else(client):
    fin_id, ai, _ = _finance()
    conv_old = db.create_conversation(fin_id, "old thinking")["id"]
    db.save_message(conv_old, "assistant", "you should buy the accounting firm", project_id=fin_id)
    pid = _portfolio()
    bootstrap.scan(pid)
    bootstrap.decide(pid, [ai[0]], "attach")
    from neurosearch import qa
    r = qa.ask("what does it say about local automation?", project_id=pid, conversation_id=db.new_id())
    assert "accounting firm" not in r["answer"]
    assert all(h["source_id"] in db.project_source_ids(pid, ready_only=False) for h in r["hits"])


# ---------------------------------------------------------------- failure and shape

def test_one_bad_query_never_costs_the_whole_scan(monkeypatch):
    _finance()
    pid = _portfolio()
    from neurosearch import library
    real, calls = library.recall, {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("index unavailable")
        return real(*a, **k)

    monkeypatch.setattr(bootstrap.library, "recall", flaky)
    r = bootstrap.scan(pid)
    assert calls["n"] > 1 and r["found"] >= 0, "a failed query is skipped, not fatal"


def test_the_endpoints_mirror_the_engine(client):
    p = client.post("/api/projects", headers=H, json={"name": "API boot", "goal": GOAL}).json()
    st = client.get(f"/api/projects/{p['id']}/bootstrap", headers=H)
    assert st.status_code == 200 and "counts" in st.json()
    assert client.post(f"/api/projects/{p['id']}/bootstrap", headers=H).json()["job_id"]
    bad = client.post(f"/api/projects/{p['id']}/bootstrap/decide", headers=H, json={"source_ids": [], "decision": "burn"})
    assert bad.status_code == 400
    assert client.get("/api/projects/nope/bootstrap", headers=H).status_code == 404


def test_the_job_is_registered_and_deduped():
    pid = _portfolio()
    a = jobs.enqueue("bootstrap_scan", {"project_id": pid}, lane="priority")
    b = jobs.enqueue("bootstrap_scan", {"project_id": pid}, lane="priority")
    assert a["id"] == b["id"], "one scan per project while it is active"
    out = jobs.run_job(dict(db.get_job(a["id"])))
    assert "found" in out and "queries" in out
