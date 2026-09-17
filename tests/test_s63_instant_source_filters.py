"""S63 — filtering/sorting the Sources list is instant, no network round trip (2026-09-17).

Kyle: *"the 'show only whats running' button on the sources page lags like crazy. shouldnt it be able
to hide things pretty quick?"* It should have been instant all along: the server never even looks at
`srcFilter`, the value-filter toggles (`state.srcFilters`), the length band or the sort order --
`/api/sources` always returns everything (up to 2000 rows) and every one of those is filtered/sorted in
the browser from the already-fetched list. But every status chip, every ★/⚠ value-filter toggle, and the
length/sort <select>s called `loadSources()` -- which refetches all 2000 sources PLUS reviews,
caption-recovery, the browser-capture queue and (on first load) the pool count -- on every single click,
for a change that never needed any of that data to be re-fetched.

`renderSourcesView()` is the pure, synchronous, no-network re-render of `SRCG.all`; `filterSources()` is
the thin wrapper every filter/sort control now calls instead of `loadSources()`. Only the search box
(the server *does* apply `q`) and anything that actually changed the underlying sources still goes
through a real `loadSources()` fetch.

Text gates, same reasoning as test_s41/test_s61: no build step, no DOM here.
"""
from __future__ import annotations

import pathlib
import re

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web"


@pytest.fixture(scope="module")
def sources_js() -> str:
    return (UI / "js" / "sources.js").read_text()


@pytest.fixture(scope="module")
def html() -> str:
    return (UI / "index.html").read_text()


def test_render_sources_view_is_synchronous_and_touches_no_network(sources_js: str):
    m = re.search(r"globalThis\.renderSourcesView = function renderSourcesView\(\) \{(.*?)\n\}\n", sources_js, re.S)
    assert m, "renderSourcesView not found"
    body = m.group(1)
    assert "await" not in body, "the pure re-render must not await anything -- that's what made it slow"
    assert "api(" not in body, "renderSourcesView must not call api() -- it only reads SRCG.all"
    assert "loadCaptureQueue(" not in body, "loadCaptureQueue is a network call and belongs to the real fetch, not every re-render"
    assert body.count("all = SRCG.all") == 1, "it must read the already-fetched list, not refetch it"


def test_filter_sources_is_the_instant_path(sources_js: str):
    m = re.search(r"globalThis\.filterSources = function filterSources\(\) \{ (.*?) \}", sources_js)
    assert m, "filterSources not found"
    assert m.group(1).strip() == "renderSourcesView();", "filterSources must do nothing but re-render"


def test_status_chips_and_value_filters_call_filter_sources_not_load_sources(sources_js: str):
    chip_html = re.search(r"const chipHtml = list => (.*?)\.join\(''\);", sources_js).group(1)
    assert "filterSources()" in chip_html
    assert "loadSources()" not in chip_html

    toggle = re.search(r"globalThis\.toggleSrcFilter = function toggleSrcFilter\(k\) \{.*\}\n", sources_js).group(0)
    assert "filterSources()" in toggle
    assert "loadSources()" not in toggle

    pool_badge = re.search(r"globalThis\.renderPoolChipBadge = function renderPoolChipBadge\(n\) \{(.*?)\n\}", sources_js, re.S).group(1)
    assert "filterSources()" in pool_badge


def test_length_and_sort_selects_call_filter_sources(html: str):
    assert '<select id="srcLen" onchange="filterSources()"' in html
    assert '<select id="srcSort" onchange="filterSources()"' in html


def test_the_search_box_still_does_a_real_fetch(html: str):
    """The one control that genuinely needs the server: `q` is applied server-side, not client-side."""
    assert 'id="srcQ"' in html
    assert 'oninput="debounce(loadSources)"' in html


def test_load_sources_still_caches_all_for_the_instant_path_to_read(sources_js: str):
    m = re.search(r"globalThis\.loadSources = async function loadSources\(quiet\) \{(.*?)\n\}\n", sources_js, re.S)
    assert m, "loadSources not found"
    body = m.group(1)
    assert "SRCG.all = all" in body, "loadSources must populate the cache filterSources reads from"
    assert body.rstrip().endswith("renderSourcesView();"), "loadSources must still render via the shared function"


def test_pool_filter_still_gets_its_own_real_fetch(sources_js: str):
    """Pool ('Known, not captured') is a different dataset entirely, not part of SRCG.all -- selecting it
    must still call the real loadPool(), even though it's reached via the instant filterSources() path."""
    view = re.search(r"globalThis\.renderSourcesView = function renderSourcesView\(\) \{(.*?)\n\}\n", sources_js, re.S).group(1)
    assert "return loadPool();" in view
