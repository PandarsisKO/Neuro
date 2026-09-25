"""S11 — the Findings tab at real scale, and feedback on a click (0.60.1). (Sorts after test_s10.)

Kyle: *"in the sources tab, when I see 'XYZ suggested findings waiting for review' in yellow and click on it, it
takes me to findings tab, but nothing loads, no obvious action to take or to approve etc."*

Two separate faults behind one symptom, and both are the same shape as the Sources view before R2: a payload nobody
re-measured after the corpus grew.

1. `/api/projects/{id}` returned every finding in full. Measured on his own database: **10,384 approved plus 1,383
   suggested, about 8 MB**, fetched by the Findings, Chats, Settings and Plan views before any of them drew
   anything. The counts a screen actually needs are a `GROUP BY`, and the workbench already pages the list.
2. The link only called `showView('findings')`, so it dropped him into whatever filter the workbench was holding —
   normally `approved` — with no sign that 104 suggestions for that source existed anywhere.

And separately: *"clicking on a button does not give immediate user feedback that something happened"*, plus the
Discover list's arbitrary blue-versus-white buttons.
"""
from __future__ import annotations

import os
import re
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_ftab_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import api, db  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests.frontend_helpers import ui_source  # noqa: E402

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "neurosearch", "web", "index.html")


@pytest.fixture()
def project(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    db._local.conn = None
    db.init_db()
    p = db.create_project("scale", brief="a project with more findings than a screen can hold")
    yield p["id"]
    db._local.conn = None


def _notes(project_id, n, status="approved"):
    rows = [{"title": f"Finding {i}", "content": f"A specific point number {i} about the equity injection.",
             "citations": [], "importance": 3} for i in range(n)]
    with db.tx() as conn:
        for i, r in enumerate(rows):
            conn.execute("INSERT INTO project_notes (project_id, content, citations, created_at, status, model, "
                         "importance, title, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
                         (project_id, r["content"], "[]", 1000.0 + i, status, "claude-sonnet-5", 3, r["title"], "s1"))


# ------------------------------------------------------------------ the payload

def test_the_project_endpoint_no_longer_ships_every_finding(project):
    _notes(project, api.NOTES_INLINE_MAX + 50)
    _notes(project, 30, status="suggested")
    # 0.63.12 — it ships NO finding rows now. 0.60.1 bounded them to 200 because they were unbounded; measured on
    # the right project, the two bounded lists were still 407 KB of a 457 KB response that every tab fetches
    # first, and the only line in the UI reading them used `notes.length` as a COUNT — which the cap made wrong.
    p = api.api_project(project)
    assert p["notes"] == [] and p["suggested"] == [] and p["notes_omitted"] is True
    assert p["counts"]["approved"] == api.NOTES_INLINE_MAX + 50 and p["counts"]["suggested"] == 30
    inline = api.api_project(project, notes="inline")
    assert len(inline["notes"]) == api.NOTES_INLINE_MAX and inline["notes_truncated"] is True


def test_the_counts_are_exact_even_when_the_list_is_not(project):
    """The number on the tab has to be right whether or not the rows came with it — that is the whole trade."""
    _notes(project, api.NOTES_INLINE_MAX + 50)
    _notes(project, 30, status="suggested")
    c = api.api_project(project)["counts"]
    assert c["approved"] == api.NOTES_INLINE_MAX + 50 and c["suggested"] == 30
    assert c["total"] == api.NOTES_INLINE_MAX + 80


def test_omission_is_never_silent(project):
    """Absent rows are a stated choice, not an empty project: `notes_omitted` says so and `counts` is the number."""
    _notes(project, 5)
    p = api.api_project(project)
    assert p["notes"] == [] and p["notes_omitted"] is True and p["counts"]["approved"] == 5
    assert api.api_project(project, notes="inline")["notes_omitted"] is False


def test_a_caller_that_wants_everything_can_still_ask(project):
    """A bound that cannot be lifted is a data loss waiting to happen — exports and the planner read whole notes."""
    _notes(project, api.NOTES_INLINE_MAX + 7)
    p = api.api_project(project, notes="all")
    assert len(p["notes"]) == api.NOTES_INLINE_MAX + 7
    assert p["notes_truncated"] is False and p["notes_inline_max"] is None


def test_db_list_project_notes_limit_is_opt_in(project):
    _notes(project, 12)
    assert len(db.list_project_notes(project)) == 12
    assert len(db.list_project_notes(project, limit=5)) == 5


def test_note_counts_is_one_query_and_counts_every_status(project):
    _notes(project, 4)
    _notes(project, 3, status="suggested")
    _notes(project, 2, status="reserve")
    c = db.note_counts(project)
    assert c == {"approved": 4, "suggested": 3, "reserve": 2, "total": 9}


# ------------------------------------------------------------------ what the browser no longer has to derive

def test_the_analysing_counts_come_from_the_server(project):
    """The browser used to download every source in the project (limit=2000) to count how many were being read."""
    p = api.api_project(project)
    assert p["analysing"] == {"sources": 0, "queued": 0}
    db.create_job("suggest_findings", {"project_id": project, "source_ids": ["s1", "s2"]})
    p = api.api_project(project)
    assert p["analysing"]["sources"] == 2 and p["analysing"]["queued"] == 1


def test_another_projects_findings_job_is_not_counted(project):
    db.create_job("suggest_findings", {"project_id": "someone-else", "source_ids": ["x"]})
    assert api.api_project(project)["analysing"] == {"sources": 0, "queued": 0}


# ------------------------------------------------------------------ the link now lands somewhere

def test_the_sources_link_filters_the_workbench_to_that_source():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    assert "openSourceSuggestions(" in ui
    # the yellow link must call it, not merely switch tabs
    m = re.search(r"suggested finding\$\{s\.suggested === 1 \? '' : 's'\} waiting for review", ui)
    assert m
    link = ui[max(0, m.start() - 400):m.start()]
    assert "openSourceSuggestions(" in link and "showView('findings');return false\" style=\"color:var(--warn)\"" not in link


def test_the_workbench_can_be_filtered_to_one_source_and_cleared():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    assert "if (FB.source) p.set('source_id', FB.source);" in ui
    assert "clearFindingSource" in ui and 'id="fbSrcChip"' in ui


def test_the_findings_view_no_longer_downloads_every_source():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    body = ui[ui.index("async function loadNotes()"):ui.index("// The Sources tab's")]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
    assert "limit=2000" not in code
    assert "/findings?" in code and "status: 'suggested'" in code


def test_the_suggested_block_links_to_the_paged_workbench(project):
    # CL-2 (declutter rung 4): the 100-card block loadNotes() used to render here is gone — it duplicated the
    # workbench's own 'suggested' filter. loadNotes() now sends the user there instead of paging its own copy.
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    body = ui[ui.index("async function loadNotes()"):ui.index("// The Sources tab's")]
    assert "reviewSuggested" in body
    assert "suggested finding" in body and "waiting" in body
    # the bulk approve/dismiss wording (and its "never implies it approved everything" honesty) now lives on the
    # workbench itself, scoped to whichever page is actually on screen. (S99 moved the bar into renderFbBulk(),
    # which loadWorkbench calls with the same page of rows; the wording and its honesty are unchanged.)
    wb = ui[ui.index("globalThis.renderFbBulk = function renderFbBulk"):ui.index("globalThis.loadWorkbenchSource")]
    assert "Approve ${total > rows.length ? rows.length + ' shown' : 'all'}" in wb
    assert "renderFbBulk();" in ui[ui.index("globalThis.loadWorkbench = async function loadWorkbench"):ui.index("globalThis.loadWorkbenchSource")]


# ------------------------------------------------------------------ feedback on a click

def test_every_discover_add_button_looks_the_same():
    """The colour used to depend on the row's KIND, which encoded nothing a reader could see."""
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    acts = ui[ui.index('<div class="dacts">'):ui.index('${d.status !== \'added\' ?')]
    assert "d.kind === 'website'" not in acts
    # five since 0.60.2: the fifth is the "add the site instead" offer on a row whose address 404s
    assert acts.count('class="small primary"') == 5


def test_adding_from_discover_acknowledges_the_click():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    fn = ui[ui.index("async function discAdd("):ui.index("async function addFromLibrary(")]
    assert "btn.disabled = true" in fn and "adding…" in fn and "added ✓" in fn
    assert "toast(" in fn
    # and a failure puts the button back rather than leaving a dead control
    assert "btn.disabled = false" in fn and "btn.textContent = label" in fn


def test_adding_from_the_library_acknowledges_the_click_too():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    fn = ui[ui.index("async function addFromLibrary("):ui.index("// ================= BOOTSTRAP R3")]
    assert "adding…" in fn and "added ✓" in fn and "btn.disabled = false" in fn


def test_the_progress_box_collapses_to_what_is_running():
    ui = ui_source(__import__("pathlib").Path(UI).parent)
    assert "toggleJobsBox" in ui and "JOBSBOX" in ui
    assert "Show only what is running" in ui and "ns_jobsbox" in ui
    # collapsed still shows anything failed or bumped — those need the user
    assert "j.status === 'failed' || j.status === 'cancelling'" in ui
