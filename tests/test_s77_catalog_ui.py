"""Catalog UI ownership and rendering: execute the shipped sources.js, not a copy.

These DOM/async regressions are not a substitute for R8b's real-browser visual gate.
Uses the scanner gate's existing pinned jsdom setup, never an optional silent skip.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_s32_course_scanner import _jsdom_installed  # noqa: F401


@pytest.mark.parametrize("scenario", [
    "escape", "project-switch", "query-race", "stale-action",
    "stale-row-actions", "stale-card-actions", "stale-error", "late-action",
    "pending-action", "project-reset", "selected-capture", "draft-focus",
    "reset-source-project", "filtered-count", "late-library",
])
def test_catalog_dom_and_async_ownership(scenario):
    node = shutil.which("node")
    assert node, "Catalog UI gate requires Node; it must not silently skip."
    harness = Path(__file__).parent / "js" / "run-catalog-ui.mjs"
    result = subprocess.run([node, str(harness), scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("PASS " + scenario)
