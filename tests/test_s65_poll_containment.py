"""S65 — the browser cannot build an unbounded backlog of UI refreshes (P0.1, docs/SPEED-AUDIT-2026-09-17.md).

Measured 2026-09-17 on Kyle's live server: `/api/sources` p50 92 s and `caption-recovery` p50 186 s while
findings/Claims work ran. `pollTick` fired `loadSources()` without awaiting it, `api()` had no timeout and
nothing de-duplicated a refresh already in flight, so copies of minute-long requests stacked up until Chrome's
six-connections-per-host limit was full and every click in the tab — "New chat" included — queued behind them.

Three behaviours are proven against the SHIPPED api.js in a node vm (tests/js/run-poll-containment.mjs):
bounded quiet concurrency with user actions never queued behind polls; an abort budget on quiet requests that
releases its slot; and coalescing (single flight + exactly one rerun, loud wins, watchdog). The text gates
below pin the wiring: every poll-path loader enters/leaves its key, and a hidden tab does not poll.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "neurosearch" / "web" / "js"
HARNESS = ROOT / "tests" / "js" / "run-poll-containment.mjs"


def _node() -> str:
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        pytest.skip("no JavaScript engine on this machine")
    return node


@pytest.mark.parametrize("scenario", ["limit", "timeout", "coalesce"])
def test_shipped_api_js_contains_polls(scenario: str):
    r = subprocess.run([_node(), str(HARNESS), scenario], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"{scenario}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert r.stdout.startswith("PASS " + scenario)


@pytest.fixture(scope="module")
def sources_js() -> str:
    return (UI / "sources.js").read_text()


@pytest.fixture(scope="module")
def research_js() -> str:
    return (UI / "research.js").read_text()


def _body(js: str, name: str) -> str:
    m = re.search(rf"globalThis\.{name} = async function {name}\(([\w, ]*)\) \{{(.*?)\n\}}", js, re.S)
    assert m, f"{name} not found"
    return m.group(2)


@pytest.mark.parametrize("name,key", [("loadSources", "sources"), ("loadReviews", "reviews"),
                                      ("loadCaptionRecovery", "caption-recovery"), ("loadBacklog", "backlog")])
def test_every_sources_poll_loader_is_single_flight(sources_js: str, name: str, key: str):
    body = _body(sources_js, name)
    assert f"if (!POLL.enter('{key}', quiet)) return;" in body, f"{name} must enter its POLL key before fetching"
    assert body.count(f"POLL.leave('{key}', {name})") >= 1, f"{name} must leave its POLL key on every exit path"


@pytest.mark.parametrize("name,key", [("loadJobs", "jobs"), ("loadBoot", "bootstrap")])
def test_every_research_poll_loader_is_single_flight(research_js: str, name: str, key: str):
    body = _body(research_js, name)
    assert f"if (!POLL.enter('{key}', quiet)) return;" in body
    assert f"POLL.leave('{key}', {name})" in body


def test_load_sources_leaves_on_the_failure_path_and_keeps_the_screen(sources_js: str):
    body = _body(sources_js, "loadSources")
    # the catch block must release the key BEFORE any early return, and a quiet failure must not blank the list
    catch = body[body.index("catch (e) {"):]
    assert catch.index("POLL.leave('sources', loadSources)") < catch.index("return")
    assert "if (quiet && SRCG.loaded) return;" in catch


def test_hidden_tab_does_not_poll(research_js: str):
    body = _body(research_js, "pollTick")
    assert "if (document.hidden)" in body, "pollTick must stop while the document is hidden"
    hidden = body[body.index("if (document.hidden)"):].split("\n", 1)[0]
    assert "api(" not in hidden and "loadJobs" not in hidden and "loadSources" not in hidden
    assert "setTimeout(pollTick" in hidden, "a hidden tab keeps a slow heartbeat so it resumes on its own"
    assert "document.addEventListener('visibilitychange'" in research_js and "pollTick();" in research_js, \
        "a tab that becomes visible must poll immediately, not wait for the heartbeat"


def test_capture_queue_loop_is_quiet_and_not_while_hidden(sources_js: str):
    body = _body(sources_js, "loadCaptureQueue")
    assert "if (state.view === 'sources' && !document.hidden) loadSources(true)" in body
    assert "loadSources();" not in body


def test_abandoned_poll_is_not_reported_as_an_outage(research_js: str):
    body = _body(research_js, "loadJobs")
    assert "e.name !== 'AbortError'" in body, "a timed-out poll is a slow server, not a disconnected one"
