"""S87 (2026-09-23) — the findings tab, two things Kyle said in one breath.

"there should be an 'approve all' for a single source (per video, article, etc) and not just an 'approve all' for
EVERYTHING": every source group's header now carries Approve all N / Dismiss all over exactly its suggested rows.

"its hiding the full list by default ... when I first clicked on findings I got scared because the entire window was
blank until I expanded all": groups are open unless this person closed them in THIS project — a collapse never carries
over from another project, and "Collapse all" is a choice for one visit, not a default."""
from __future__ import annotations

import pathlib

JS = (pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "research.js").read_text()


def test_each_source_group_has_its_own_approve_all():
    assert "const sugg = list.filter(n => n.status === 'suggested' || n.status === 'reserve').map(n => n.id);" in JS
    assert ">Approve all ${sugg.length}</button>" in JS
    assert "bulkNotes(${JSON.stringify(sugg).replace(/\"/g, '&quot;')},'approved')" in JS, "same door as every other status change"
    assert "event.preventDefault();bulkNotes(" in JS, "pressing it must not toggle the group shut"


def test_groups_open_by_default_and_a_collapse_never_leaks_between_projects():
    assert "if (FGRP.project !== state.project.id) { FGRP.project = state.project.id; FGRP.collapsed = new Set(); }" in JS
    assert "const open = grpSearching || bySrc.length <= 4 || !FGRP.collapsed.has(title);" in JS, "open unless closed by hand"
