"""S94 (2026-09-24) — Kyle: "chats, sources, progress seem to be leaking between projects". Reproduced in his
Chrome: open the wealth project, then the business project — the sources pane still showed r/HENRYfinance rows,
the source count stayed 285, the review cards lingered. Two causes: a slow answer for the project just LEFT landed
after the switch (a race), and per-project state lived in module globals that survived the switch (SRCG.all /
loaded, POOL.total, FB, RES, STALE, BOOTSTATE, rvSig, CAPTURE_SEEN, lastRev …) so "keep the list already on screen"
kept the other project's list."""
from __future__ import annotations

import pathlib

WEB = pathlib.Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js"
API = (WEB / "api.js").read_text()
HOME = (WEB / "home.js").read_text()
SRC = (WEB / "sources.js").read_text()
RES = (WEB / "research.js").read_text()


def test_a_project_scoped_answer_for_a_project_no_longer_open_is_dropped():
    assert "globalThis.projectOfPath = function projectOfPath(path)" in API
    assert "if (pid && state.project && state.project.id !== pid) throw staleProjectError(pid);" in API
    assert "e.name = 'AbortError'; e.stale = true;" in API, "loaders already treat AbortError as an abandoned poll, never an outage"


def test_the_switch_resets_every_per_project_cache_and_pane():
    assert "globalThis.resetProjectState = function resetProjectState()" in HOME
    for must in ("Object.assign(SRCG, { rows: [], html: new Map(), keys: [], byKey: {}, loaded: false, all: [] })", "POOL.total = null",
                 "Object.assign(FB, { offset: 0, source: null, loaded: false, rows: [], statusCounts: {} })", "STALE.data = null", "globalThis.BOOTSTATE = null",
                 "globalThis.rvSig = null", "globalThis.CAPTURE_SEEN = null; globalThis.lastRev = null", "JOBSHIST.clear()", "['#srcList', '']", "['#chatList', '']", "['#srcCount', '']"):
        assert must in HOME, must
    assert "if (fresh) { state.project = { id, name: '…', _loading: true }; resetProjectState(); }" in HOME, "the new id is current BEFORE the first fetch, so old answers are stale from that instant"
    assert HOME.count("if (seq !== globalThis.openSeq) return;") == 2, "a superseded open never finishes"


def test_loaders_that_paint_errors_ignore_a_dropped_stale_answer():
    assert "if (e && e.stale) return;                                            // S94" in SRC
    assert "catch (e) { if (e && e.stale) return; $('#notes').innerHTML = listState('failed'" in RES
