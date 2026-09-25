"""S99 — filter findings by strength, bulk-select them, and load a filtered or hand-picked set into Keep vs Lose.

Kyle, 2026-09-25: "in our findings tab, I want a way to filter by strength so I can review findings and bulk select
and remove if possible. furthermore, I would like to be able to select findings by strength and load them into the
Keep vs Lose feature so I can have an easier way to view and review, not just the random review we have already
built."

Strength is the 1-5 importance every finding already carries. Before this, the only handle on it was a FLOOR
("3 and up") in the collapsed filters panel — the wrong shape for the job, which is reaching the WEAK end exactly.
The server side gains an exact set filter (`importance="1,2"`); the workbench gains toggle chips with counts, a
checkbox on every row, a selection bar, and two new doors into the same reviewer the second look uses.

(Sorts after test_s98.)
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import db, fake_ai, findings_view as fv, jobs, safe_fetch  # noqa: E402
from neurosearch.config import settings  # noqa: E402

from tests.test_k6_claims import _acceptance_fixture as _fixture, _note  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "neurosearch" / "web"
JS = (WEB / "js" / "research.js").read_text()
HTML = (WEB / "index.html").read_text()
CSS = (WEB / "styles.css").read_text()
BAR = HTML.split('id="fbBar"')[1].split('id="fbSrcChip"')[0]
FILTERED = JS.split("globalThis.fbReviewFiltered =")[1].split("globalThis.fbFocus =")[0]
BULK = JS.split("globalThis.renderFbBulk =")[1].split("globalThis.loadWorkbench =")[0]


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


# ---------------------------------------------------------------- the server-side set filter

def test_parse_levels_is_a_set_and_never_an_error():
    assert fv.parse_levels(None) is None and fv.parse_levels("") is None and fv.parse_levels(" ") is None
    assert fv.parse_levels("1,2") == {1, 2} and fv.parse_levels("5") == {5} and fv.parse_levels("0") == {0}
    assert fv.parse_levels("2, 1, 1") == {1, 2}
    assert fv.parse_levels("9,abc") is None, "unknown tokens fall back to no filter, never a 4xx"
    assert fv.parse_levels("3,junk") == {3}


def test_importance_is_an_exact_set_where_min_importance_was_a_floor(monkeypatch):
    pid, ids = _fixture(monkeypatch)
    for k in range(2):
        _note(pid, ids["outlier"], f"minor aside {k} about office coffee", "coffee", importance=1, locator="0:30", start=30, title=f"Coffee {k}")
    _note(pid, ids["outlier"], "a middling remark about the coffee machine", "coffee", importance=2, locator="0:40", start=40, title="Coffee 2")
    everything = fv.query(pid)["findings"]
    by_level = {}
    for f in everything:
        by_level.setdefault(int(f["importance"] or 0), 0); by_level[int(f["importance"] or 0)] += 1
    weak = fv.query(pid, importance="1,2")
    assert weak["total"] == by_level.get(1, 0) + by_level.get(2, 0) == 3
    assert {f["importance"] for f in weak["findings"]} == {1, 2}
    only1 = fv.query(pid, importance="1")
    assert only1["total"] == 2 and all(f["importance"] == 1 for f in only1["findings"])
    # a floor still works exactly as before, and the two compose
    assert fv.query(pid, min_importance=4)["total"] == by_level.get(4, 0) + by_level.get(5, 0)
    assert fv.query(pid, importance="1,2,3,4,5", min_importance=4)["total"] == fv.query(pid, min_importance=4)["total"]
    # the importance facet ignores its own filter, so every chip keeps saying what choosing it would give
    assert weak["facets"]["importance"] == fv.query(pid)["facets"]["importance"]


def test_the_api_passes_importance_through(monkeypatch, client):
    pid, ids = _fixture(monkeypatch)
    _note(pid, ids["outlier"], "minor aside about office coffee", "coffee", importance=1, locator="0:30", start=30, title="Coffee")
    h = {"Authorization": "Bearer t0k"}
    r = client.get(f"/api/projects/{pid}/findings", params={"importance": "1"}, headers=h)
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["total"] == 1 and r["findings"][0]["importance"] == 1
    r = client.get(f"/api/projects/{pid}/findings", params={"importance": "1", "sort": "weakest", "reviewed": "no"}, headers=h).json()
    assert r["total"] == 1, "the filtered-review query (strength + weakest + unreviewed) composes"


# ---------------------------------------------------------------- the chips are out in the open

def test_strength_chips_sit_in_the_findings_bar_beside_status():
    assert 'id="fbImpChips"' in BAR and 'id="fbStatusChips"' in BAR
    assert 'id="fbImp" type="hidden"' in HTML, "the chosen levels ride in a hidden input, not a select with fixed options"
    assert "3 and up" not in HTML, "the floor-only select is gone; strength is an exact pick now"


def test_chips_are_toggles_over_exact_levels_and_send_importance_not_a_floor():
    assert "['importance', 'fbImp']" in JS and "['min_importance', 'fbImp']" not in JS
    assert "FB_IMP_LEVELS = [5, 4, 3, 2, 1, 0]" in JS, "every level, weak end included, plus unrated"
    tog = JS.split("globalThis.fbImpToggle =")[1].split("\n}")[0]
    assert "on.has(v) ? on.delete(v) : on.add(v)" in tog, "several levels may be on at once"
    assert "renderFbImpChips(r.facets && r.facets.importance)" in JS, "counts come from the facet, so each chip says what picking it gives"


# ---------------------------------------------------------------- bulk select and remove

def test_every_row_has_a_checkbox_and_the_bar_acts_on_the_selection():
    assert 'class="fsel"' in JS and "onchange=\"fbSel(${n.id},this.checked)\"" in JS
    assert "_sel: FB.sel.has(n.id)" in JS, "the workbench opts rows in; other renderers of findingCard get no box"
    assert ".f .fsel" in CSS
    assert "fbSelAll(this.checked)" in BULK and "select the ${rows.length} shown" in BULK
    assert "fbBulkSelected('dismissed')" in BULK and "fbBulkSelected('approved')" in BULK
    assert "fbReviewSelected()" in BULK, "a selection can go straight into Keep vs Lose"


def test_bulk_actions_go_through_the_one_existing_door():
    sel = JS.split("globalThis.fbBulkSelected =")[1].split("\n}")[0]
    assert "await bulkNotes(ids, status)" in sel and "/api/notes/" not in sel, "no second path for status changes"
    assert "for (const id of ids) FB.sel.delete(id)" in JS, "a pick that has been acted on is done"


def test_dismissing_approved_picks_asks_first_and_says_it_is_reversible():
    sel = JS.split("globalThis.fbBulkSelected =")[1].split("\n}")[0]
    assert "n.status === 'approved'" in sel and "confirm(" in sel
    assert "Nothing is deleted and it is reversible" in sel


def test_the_selection_never_crosses_projects():
    assert "if (FB.selFor !== state.project.id) { FB.selFor = state.project.id; FB.sel.clear(); }" in JS


def test_the_suggested_approve_all_pair_survives():
    assert "Approve ${total > rows.length ? rows.length + ' shown' : 'all'}" in BULK
    assert "bulkNotes(${JSON.stringify(bulkIds)},'dismissed')" in BULK


# ---------------------------------------------------------------- filtered review into Keep vs Lose

def test_the_filtered_review_button_is_in_the_bar_and_reads_the_same_filters():
    assert 'id="fbFilteredBtn" onclick="fbReviewFiltered()"' in BAR
    for k in ("['importance', 'fbImp']", "['used', 'fbUsed']", "['area', 'fbArea']", "['stale', 'fbStale']", "['q', 'fbQ']"):
        assert k in FILTERED, k
    assert "if (FB.source) p.set('source_id', FB.source)" in FILTERED


def test_it_serves_the_batch_size_weakest_first_and_can_page_itself():
    assert "limit: FOCUS_BATCH" in FILTERED and "sort: 'weakest'" in FILTERED
    assert "if (st === 'approved') p.set('reviewed', 'no')" in FILTERED, \
        "Keep on an approved finding changes only reviewed_at; skipping ruled-on rows is what makes 'again' mean 'the next 100'"
    assert "Press the button again for the next ${FOCUS_BATCH}" in FILTERED


def test_it_opens_the_same_reviewer_and_names_the_set():
    assert "fbFocusOpen(rows, {" in FILTERED
    assert "Keep files it as approved, Lose as dismissed" in FILTERED and "nothing is deleted either way" in FILTERED
    assert "strength ${" in FILTERED, "the title says which strengths are being reviewed"


def test_the_selected_review_walks_exactly_the_picks_and_clears_them_after():
    sel = JS.split("globalThis.fbReviewSelected =")[1].split("\n}")[0]
    assert "const rows = [...FB.sel.values()]" in sel and "fbFocusOpen(rows, {" in sel
    assert "onDone: fbSelClear" in sel
    opener = JS.split("globalThis.fbFocusOpen =")[1].split("globalThis.findingCard")[0]
    assert "if (opts.onDone) opts.onDone();" in opener


def test_s78_region_is_untouched_by_the_new_query():
    """S78 pins that fbFocus reviews the page ON SCREEN and never refetches; the new door lives outside that region."""
    fn = JS.split("globalThis.fbFocus =")[1].split("globalThis.findingCard")[0]
    assert "/findings?" not in fn
    assert JS.index("globalThis.fbReviewFiltered =") < JS.index("globalThis.fbFocus =")
