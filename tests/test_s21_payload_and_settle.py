"""S21 — two passes that ran inside a request, and a list nobody re-measured (0.62.7). (Sorts after test_s20.)

**Measured through Kyle's browser on his 17,119-finding project, 2026-09-10.** The Research tab loads from one
request, and that request had grown to **5,858 KB served in 23.7 s**. Decomposed by key:

    questions        4,802 KB   2,703 targets (2,667 of them OPEN, so filtering by status saves nothing)
    area_of_claim      854 KB   15,499 claims
    watchouts          146 KB
    everything else    ~60 KB

and inside a single question, `actions` alone accounted for 1,311 KB across the list. This is the third instance of
one defect: **a list nobody re-measured after the corpus grew** — the findings payload was 8 MB before 0.60.1, the
sources list 4.6 MB before 0.46.3.

Two different fixes, because the two keys fail differently:

* `area_of_claim` is **dropped outright** — grepping the UI for it returns nothing. It is an index `areas()` builds
  for its own use, and `claims_view.query` already carries a per-row `area` for the rows on screen. Available
  behind `area_map=True` for any caller that wants it.
* `questions` is **bounded, never filtered**, in the same order the Overview's "next" list uses, with
  `questions_total` and `questions_truncated` beside it, and the full list paged from
  `GET …/research/questions?offset=&limit=&area=`. Nothing becomes unreachable and truncation is never silent.
  Focusing an area re-fetches for that area, because an area whose questions all sit past the page boundary must
  not read as empty.

And separately: `settle_all` materialised every unsettled cohort **inside the HTTP request**. Materialising one is a
full findings write per source — validation, quote checking, note insertion — and recovering Kyle's 410 stranded
cohorts took minutes on a single-process server. It queues now. The same sentence as three other fixes this week:
a pass worth having is not worth having in a request.
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_pay_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, batches, db, research_view as rv  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


@pytest.fixture(autouse=True)
def _no_jobs_left_behind():
    yield
    try:
        with db.tx() as conn:
            conn.execute("UPDATE jobs SET status='cancelled' WHERE status IN ('queued','running')")
    except Exception:  # noqa: BLE001
        pass


def _project_with_questions(n):
    p = db.create_project("many", brief="buying businesses")
    with db.tx() as conn:
        for i in range(n):
            conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                         "VALUES (?,?,?,?,?,?)", (f"t{i}", p["id"], f"open question number {i}", "open", 1.0, 1.0))
    return p



def _project_with_claims(n: int = 4) -> str:
    """A project with claims, an open target and a tension — the three things `/research` actually renders,
    plus the rows it stopped shipping."""
    p = db.create_project("with claims", brief="buying businesses")
    pid = p["id"]
    with db.tx() as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO project_claims (id, project_id, text, claim_type, topic, status, strength, "
                "freshness_class, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"c{i}", pid, f"a claim about seller financing number {i}", "factual", "seller financing",
                 "accepted" if i == 0 else "proposed", "strong" if i == 0 else "weak", "age_insensitive", 1.0, 1.0))
        conn.execute("INSERT INTO project_evidence_targets (id, project_id, question, status, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?)", ("tc1", pid, "what do lenders require?", "open", 1.0, 1.0))
        conn.execute("INSERT INTO research_tensions (id, project_id, kind, description, impact, status, "
                     "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     ("x1", pid, "NOVEL", "only one source says this", "medium", "open", 1.0, 1.0))
    return pid


# ------------------------------------------------------------------ the bounded list

def test_the_shell_carries_a_page_not_the_whole_list(fresh):
    p = _project_with_questions(rv.QUESTIONS_INLINE_MAX + 60)
    full = rv.overview(p["id"], full=True)
    assert len(full["questions"]) == rv.QUESTIONS_INLINE_MAX
    assert full["questions_total"] == rv.QUESTIONS_INLINE_MAX + 60
    assert full["questions_truncated"] is True


def test_a_small_project_is_not_truncated_and_says_so(fresh):
    p = _project_with_questions(5)
    full = rv.overview(p["id"], full=True)
    assert len(full["questions"]) == 5 and full["questions_truncated"] is False


def test_the_unused_area_map_is_no_longer_shipped(fresh):
    """854 KB on Kyle's project, and the UI never reads it — grep index.html for area_of_claim: zero hits."""
    p = _project_with_questions(3)
    full = rv.overview(p["id"], full=True)
    assert "area_of_claim" not in full
    assert "area_of_claim" in rv.overview(p["id"], full=True, area_map=True)


def test_nothing_is_unreachable_the_rest_is_paged(fresh):
    p = _project_with_questions(rv.QUESTIONS_INLINE_MAX + 40)
    first = api.api_research_questions(p["id"], limit=rv.QUESTIONS_INLINE_MAX)
    second = api.api_research_questions(p["id"], limit=rv.QUESTIONS_INLINE_MAX, offset=rv.QUESTIONS_INLINE_MAX)
    assert first["truncated"] is True and second["truncated"] is False
    assert second["returned"] == 40
    ids = {q["id"] for q in first["questions"]} | {q["id"] for q in second["questions"]}
    assert len(ids) == rv.QUESTIONS_INLINE_MAX + 40                    # every question is reachable


def test_the_page_order_matches_the_shell_so_a_boundary_is_not_a_change_of_subject(fresh):
    p = _project_with_questions(rv.QUESTIONS_INLINE_MAX + 10)
    shell = rv.overview(p["id"], full=True)["questions"]
    paged = api.api_research_questions(p["id"], limit=rv.QUESTIONS_INLINE_MAX)["questions"]
    assert [q["id"] for q in shell] == [q["id"] for q in paged]


def test_the_light_request_is_still_light(fresh):
    p = _project_with_questions(10)
    light = rv.overview(p["id"])
    assert "questions" not in light and "area_of_claim" not in light


# ------------------------------------------------------------------ settlement is a job

def test_settle_all_queues_instead_of_blocking(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [{"job_id": "j1"}, {"job_id": "j2"}])
    monkeypatch.setattr(batches, "settle", lambda jid: pytest.fail("settled inside the request"))
    out = api.api_settle_all()
    assert out["queued"] is True and out["status"] == "queued"
    rows = [j for j in db.list_jobs(limit=20) if j["kind"] == "settle_batches"]
    assert len(rows) == 1 and rows[0]["lane"] == "priority" and rows[0]["execution_policy"] == "local_only"


def test_a_second_click_does_not_queue_a_second_settlement(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [{"job_id": "j1"}])
    a, b = api.api_settle_all(), api.api_settle_all()
    assert a["job_id"] == b["job_id"]


def test_nothing_waiting_means_nothing_queued(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [])
    out = api.api_settle_all()
    assert out["queued"] is False and out["attempted"] == 0 and "nothing" in out["note"]


def test_the_job_does_the_work_and_reports_progress(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [{"job_id": "j1"}, {"job_id": "j2"}])
    monkeypatch.setattr(batches, "settle", lambda jid: {"settled": True, "materialized": 3})
    said = []
    out = batches.run_settle_job({"limit": 25}, progress=lambda f, m: said.append((round(f, 2), m)))
    assert out["attempted"] == 2 and out["materialized"] == 6
    assert said[0][1].startswith("collecting 2") and said[-1][0] == 1.0


def test_a_failing_cohort_does_not_stop_the_others(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [{"job_id": "bad"}, {"job_id": "good"}])
    def settle(jid):
        if jid == "bad":
            raise RuntimeError("provider said no")
        return {"settled": True, "materialized": 2}
    monkeypatch.setattr(batches, "settle", settle)
    out = batches.run_settle_job({})
    assert out["materialized"] == 2
    assert any(r.get("why", "").startswith("provider said no") for r in out["results"])


def test_the_synchronous_path_is_still_there_for_the_cli(fresh, monkeypatch):
    monkeypatch.setattr(batches, "unsettled", lambda: [{"job_id": "j1"}])
    monkeypatch.setattr(batches, "settle", lambda jid: {"settled": True, "materialized": 1})
    out = api.api_settle_all(background=False)
    assert out["attempted"] == 1 and out["materialized"] == 1 and "queued" not in out


# ── 0.63.8 — the same fault, one layer along ────────────────────────────────────────────────────────────────────
# 0.62.7 trimmed `research/overview`. Re-measured through his browser after it, `/research` — the full state, which
# the shell loads lazily behind the Claims and Research-tools panes — was **773,926 bytes**, by key:
#
#     claims   546,350      targets  112,730      tensions  80,620      map  33,741      everything else  327
#
# 300 claim rows at 1.8 KB each, 206 KB of that their attached evidence. And `renderResearch` reads `map`,
# `targets`, `tensions` and `attention` — grep the UI for the claims key and there are no hits. `claims_view.query`
# replaced this list in the 0.45.5 workbench rebuild; the list stayed in the response for eighteen releases.

def test_the_research_state_no_longer_ships_claim_rows(fresh):
    from neurosearch import api, knowledge
    pid = _project_with_claims()
    st = api.api_research(pid)
    assert st["claims"] == []
    assert st["claims_total"] >= 1 and st["claims_truncated"] is True


def test_every_number_is_still_computed_over_the_whole_set(fresh):
    """The rows go; the counts must not change, because they are what the screen actually renders."""
    from neurosearch import api, knowledge
    pid = _project_with_claims()
    lean, full = api.api_research(pid), api.api_research(pid, claims=True)
    for k in ("claims_total", "targets_total", "tensions_total", "tension_counts", "freshness_counts", "claim_stats"):
        assert lean[k] == full[k], k
    assert full["claims"] and len(json.dumps(lean)) < len(json.dumps(full))


def test_the_rows_are_one_parameter_away(fresh):
    """Dropping a key that a CLI or an MCP caller might want is a different decision from removing the ability."""
    from neurosearch import api
    pid = _project_with_claims()
    assert api.api_research(pid, claims=True)["claims"]


def test_the_chat_block_does_not_depend_on_the_dropped_page(fresh):
    """`qa.research_block` tested emptiness with `st["claims"]`, which is now always empty — it would have gone
    silent on every project the moment the rows were dropped. It reads the count instead."""
    from neurosearch import qa
    pid = _project_with_claims()
    assert qa.research_block(pid).startswith("Research state")
