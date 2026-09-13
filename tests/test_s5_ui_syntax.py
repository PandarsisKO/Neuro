"""S5 — the single-file UI must at least parse.

`web/index.html` is 295 KB with ~247 KB of inline JavaScript and no build step, so a stray brace or an unbalanced
template literal ships silently: `release-check` never looked at it, and the first symptom is a blank panel in
Kyle's browser. Every rung tonight touched this file. A syntax gate is the cheapest possible protection and it
belongs in the suite rather than in a habit.

It is skipped, not failed, where no JavaScript engine exists — a missing `node` is a fact about the machine, and a
gate that fails for that reason teaches people to ignore gates.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "index.html"


def _module_paths() -> list[Path]:
    root = INDEX.parent / "js"
    return sorted(root.glob("*.js"))


def test_the_ui_file_is_where_we_think_it_is():
    assert INDEX.is_file() and INDEX.stat().st_size > 20_000


def test_the_module_javascript_parses():
    paths = _module_paths()
    assert len(paths) >= 8, "the UI module split is incomplete"
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        pytest.skip("no JavaScript engine on this machine")
    for path in paths:
        r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{path.name} has a JavaScript syntax error:\n{r.stderr[:2000]}"


def test_module_state_assignments_do_not_create_implicit_globals():
    """ES modules are strict: assigning a second bare name crashes startup even when `node --check` passes."""
    js = "\n".join(p.read_text() for p in _module_paths())
    implicit_second_assignment = re.compile(
        r"globalThis\.[A-Za-z_$][\w$]*\s*=\s*(?:null|undefined|\d+)\s*,\s*"
        r"(?!globalThis\.)[A-Za-z_$][\w$]*\s*=(?!=|>)"
    )
    assert not implicit_second_assignment.search(js), "comma assignment creates a bare strict-mode global"
    sources = (INDEX.parent / "js" / "sources.js").read_text()
    assert "globalThis.lastClassified = null" in sources


def test_the_version_marker_is_present_and_matches_the_package():
    from neurosearch import __version__
    m = re.search(r"globalThis\.UI_VERSION = '([^']+)'", (INDEX.parent / "js/state.js").read_text())
    assert m, "UI_VERSION is gone — the delivery ritual bumps it in three places"
    assert m.group(1) == __version__, f"UI_VERSION {m.group(1)} != package {__version__}"
    meta = re.search(r'name="neurosearch-ui-version" content="([^"]+)"', INDEX.read_text())
    assert meta and meta.group(1) == __version__, "index.html UI version marker is missing or stale"


@pytest.mark.parametrize("fn", ["whereToLook", "poolFilter", "loadQuality", "openQuality", "sweepQuality"])
def test_high_value_workbench_handlers_exist(fn):
    """Every onclick added tonight must resolve to a defined function — an inline handler naming a missing function
    fails only when a human clicks it."""
    js = "\n".join(p.read_text() for p in _module_paths())
    assert re.search(rf"globalThis\.{fn}\s*=\s*(async )?function\b", js), f"{fn} is referenced but not defined"


@pytest.mark.parametrize("fn", ["accelerateOption", "loadBacklog"])
def test_acceleration_handlers_exist(fn):
    js = "\n".join(p.read_text() for p in _module_paths())
    assert re.search(rf"globalThis\.{fn}\s*=\s*(async )?function\b", js), f"{fn} is referenced but not defined"


def test_the_backlog_banner_no_longer_offers_a_count_plus_sort():
    """0.59.2: the dialog renders server-computed OPTIONS, each a distinct set with its own price. The old
    `btn(n, order, ...)` pairing is what allowed "next N" and "all N, most valuable first" to buy the same thing."""
    js = "\n".join(p.read_text() for p in _module_paths())
    assert "accelerateOption(" in js
    assert "most valuable first`" not in js, "the old count+sort button is still being rendered"
