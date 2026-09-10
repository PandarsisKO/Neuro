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


def _inline_js(html: str) -> str:
    return "\n".join(re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.S))


def test_the_ui_file_is_where_we_think_it_is():
    assert INDEX.is_file() and INDEX.stat().st_size > 100_000


def test_the_inline_javascript_parses():
    js = _inline_js(INDEX.read_text())
    assert len(js) > 100_000, "the UI's inline script went missing"
    node = shutil.which("node") or shutil.which("nodejs")
    if not node:
        pytest.skip("no JavaScript engine on this machine")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
        path = f.name
    r = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"web/index.html has a JavaScript syntax error:\n{r.stderr[:2000]}"


def test_the_version_marker_is_present_and_matches_the_package():
    from neurosearch import __version__
    m = re.search(r"const UI_VERSION = '([^']+)'", INDEX.read_text())
    assert m, "UI_VERSION is gone — the delivery ritual bumps it in three places"
    assert m.group(1) == __version__, f"UI_VERSION {m.group(1)} != package {__version__}"


@pytest.mark.parametrize("fn", ["whereToLook", "poolFilter", "loadQuality", "openQuality", "sweepQuality"])
def test_tonights_handlers_exist(fn):
    """Every onclick added tonight must resolve to a defined function — an inline handler naming a missing function
    fails only when a human clicks it."""
    html = INDEX.read_text()
    assert re.search(rf"(async )?function {fn}\b", html), f"{fn} is referenced but not defined"


@pytest.mark.parametrize("fn", ["accelerateOption", "loadBacklog"])
def test_the_accelerate_handlers_exist(fn):
    html = INDEX.read_text()
    assert re.search(rf"(async )?function {fn}\b", html), f"{fn} is referenced but not defined"


def test_the_backlog_banner_no_longer_offers_a_count_plus_sort():
    """0.59.2: the dialog renders server-computed OPTIONS, each a distinct set with its own price. The old
    `btn(n, order, ...)` pairing is what allowed "next N" and "all N, most valuable first" to buy the same thing."""
    html = INDEX.read_text()
    assert "accelerateOption(" in html
    assert "most valuable first`" not in html, "the old count+sort button is still being rendered"
