"""S61 — the background poll's whole fan-out stays quiet, not just loadJobs (2026-09-17).

Kyle: *"on the sources page I hate that theres still a constant progress bar thats at the very top of
the screen ... its very distracting."* -- the exact symptom L-19 (2026-09-15) already diagnosed and
supposedly fixed, verbatim, in `loadJobs`'s own comment. It came back because L-19 only quieted
`loadJobs` (and its own two direct sub-calls, `loadSpend`/`loadBacklog`) -- but `pollTick` unconditionally
also calls `loadSources()` and `loadBoot()` on nearly every tick (`srcChanged` and `changed('jobs') ||
changed('sources')` are both true almost every cycle on an active project), and NEITHER of those took a
`quiet` argument at all: every `api()` call inside them (and inside `loadSources`'s own sub-calls --
`loadReviews`, `loadCaptionRecovery`, `loadCaptureQueue`) defaulted to `ack: true`, lighting `#nsbar`
right back up every ~3s regardless of the `loadJobs` fix.

This is a text gate for the same reason test_s41 is: no build step, no DOM here.
"""
from __future__ import annotations

import pathlib
import re

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web"


@pytest.fixture(scope="module")
def research_js() -> str:
    return (UI / "js" / "research.js").read_text()


@pytest.fixture(scope="module")
def sources_js() -> str:
    return (UI / "js" / "sources.js").read_text()


def test_poll_tick_calls_loadsources_and_loadboot_quietly(research_js: str):
    m = re.search(r"globalThis\.pollTick = async function pollTick\(\) \{(.*?)\n\}", research_js, re.S)
    assert m, "pollTick not found"
    body = m.group(1)
    assert "loadSources(true)" in body, "pollTick must call loadSources(true) so its own fan-out stays silent"
    assert "loadBoot(true)" in body, "pollTick must call loadBoot(true) so its own fan-out stays silent"
    assert "loadSources()" not in body, "a bare loadSources() inside pollTick would relight the bar every tick"
    assert "loadBoot()" not in body, "a bare loadBoot() inside pollTick would relight the bar every tick"


def test_loadsources_accepts_and_propagates_quiet(sources_js: str):
    m = re.search(r"globalThis\.loadSources = async function loadSources\((\w*)\) \{(.*?)\n\}", sources_js, re.S)
    assert m, "loadSources not found"
    assert m.group(1) == "quiet", "loadSources must take a quiet parameter"
    body = m.group(2)
    assert "loadReviews(quiet)" in body
    assert "loadCaptionRecovery(quiet)" in body
    assert "loadCaptureQueue(all.filter(needsBrowser), quiet)" in body
    assert "api('/api/sources?' + p, quiet ? { ack: false } : {})" in body, \
        "loadSources's own main fetch must respect quiet or the bar still lights on every poll tick"


def test_loadboot_accepts_and_propagates_quiet(research_js: str):
    m = re.search(r"globalThis\.loadBoot = async function loadBoot\((\w*)\) \{(.*?)\n\}", research_js, re.S)
    assert m, "loadBoot not found"
    assert m.group(1) == "quiet", "loadBoot must take a quiet parameter"
    assert "ack: false" in m.group(2), "loadBoot's own api() call must respect quiet"


def test_loadreviews_and_loadcaptionrecovery_and_loadcapturequeue_respect_quiet(sources_js: str):
    for fn, param in (("loadReviews", "quiet"), ("loadCaptionRecovery", "quiet")):
        m = re.search(rf"globalThis\.{fn} = async function {fn}\((\w*)\) \{{(.*?)\n\}}", sources_js, re.S)
        assert m, f"{fn} not found"
        assert m.group(1) == param, f"{fn} must take a quiet parameter"
        assert "ack: false" in m.group(2), f"{fn}'s api() call must respect quiet"
    m = re.search(r"globalThis\.loadCaptureQueue = async function loadCaptureQueue\(([^)]*)\) \{(.*?)\n\}",
                   sources_js, re.S)
    assert m, "loadCaptureQueue not found"
    assert [a.strip() for a in m.group(1).split(",")] == ["rows", "quiet"], \
        "loadCaptureQueue must take (rows, quiet)"
    assert m.group(2).count("ack: false") >= 2, \
        "both of loadCaptureQueue's own api() calls (pending list + landed-source lookup) must respect quiet"


def test_pollticks_error_fallback_also_stays_quiet(research_js: str):
    """The /tick-unreachable fallback path is still a background retry, not a click -- it must not relight
    the bar either."""
    assert "catch (e) { loadJobs(true); loadSources(true).catch(() => {}); return; }" in research_js, \
        "the pollTick catch branch must call loadSources(true) too"


def test_click_triggered_callers_still_default_to_acknowledged(sources_js: str, research_js: str):
    """The fix must not go too far the other way: a real click handler calling loadSources()/loadBoot()
    with no argument must still light the bar (that acknowledgement is the whole point of NSACK)."""
    js = sources_js + "\n" + research_js
    assert "loadSources().catch(() => {});" in js or re.search(r"\bloadSources\(\);", js), \
        "at least one click-triggered call site must still call loadSources() unquieted"
    assert re.search(r"\bloadBoot\(\);", js), \
        "bootDecide's loadBoot() call must still be unquieted (a user action, not a poll)"


# ------------------------------------------------------------------ the "Add sources" panel defaults open

def test_add_sources_panel_defaults_open():
    """Kyle, same message: *"the 'add sources' window is collapsed by default, but thats a dumb design
    because its the primary function of the page."* `#srcAddPanel` is a native <details> with no JS
    anywhere setting or remembering its open state (unlike `#jobsDetails`'s sibling JOBSBOX toggle) --
    it was simply missing the `open` attribute, so every page load collapsed the one panel whose entire
    job is to be used immediately."""
    html = (pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web" / "index.html").read_text()
    m = re.search(r'<details class="card" id="srcAddPanel"([^>]*)>', html)
    assert m, "the Add sources panel was not found"
    assert re.search(r"\bopen\b", m.group(1)), "the Add sources panel must default to expanded (open)"
