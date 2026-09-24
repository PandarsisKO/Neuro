"""S88 (2026-09-23) — the sweep Kyle asked for after S85–S87: "my findings seem to be pretty low hanging fruit for
usability issues ... examine the app and see if you can find similar issues". Same five classes, applied everywhere:
state wiped by a background re-render; a bulk action with no per-thing twin (or the reverse); content cut or hidden
without saying so; verbs mimed as glyphs where the tab next door uses words; blocking alert() boxes."""
from __future__ import annotations

import pathlib

WEB = pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web"
R = (WEB / "js" / "research.js").read_text()
S = (WEB / "js" / "sources.js").read_text()
P = (WEB / "js" / "plan.js").read_text()


def test_an_open_job_history_survives_the_three_second_poll():
    assert "globalThis.JOBSHIST = new Map();" in R
    assert 'data-job="${j.id || \'\'}"' in R, "rows are addressable so the history can be put back"
    assert "restoreJobHistories();" in R and "globalThis.restoreJobHistories = function" in R


def test_the_source_drawer_has_per_source_approve_all_and_says_the_verbs():
    assert ">Approve all ${list.length}</button>" in R and "globalThis.drawerBulk = async function" in R
    assert "drawerBulk(${ids},'approved','${sid}')" in R
    assert '<use href="#ic-approve">' not in R.split("globalThis.sourceDrawer")[1].split("globalThis.drawerBulk")[0], "no more mimed ✓ in the drawer"


def test_nothing_is_silently_cut_off():
    assert "Show the other ${list.length - DRAWER_FIRST}" in R, "drawer findings beyond 60"
    assert "Show the other ${d.claims.length - 12}" in R, "claims resting on a source beyond 12"
    assert "Show the other ${rest.length - 30} settled" in R, "settled questions beyond 30"


def test_no_blocking_alert_boxes_for_ordinary_feedback():
    for name, src in (("research.js", R), ("sources.js", S), ("plan.js", P)):
        live = [l for l in src.splitlines() if "alert(" in l and not l.strip().startswith("//") and "insertAdjacentHTML" not in l]
        assert not live, f"{name}: {live[:2]}"
