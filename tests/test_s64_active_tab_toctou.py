"""S64 -- captureVisibleTab's active-tab TOCTOU gap closed before it was ever reproduced live (2026-09-17).

During Send Screenshot case-5 planning, Kyle amended the plan before any live testing: the proposed case
5.3 ("switch to another tab as a forced-failure mechanism") was flagged as unsafe to use casually, because
`chrome.tabs.captureVisibleTab(windowId)` captures whatever tab is CURRENTLY active in that window -- it
takes no tabId at all. `verifyTabIdentity`'s existing `tab.active` check (a prior "BLOCKER fix") proves the
target tab is active at the moment it runs, but every caller then awaits the rate-limit wait (up to
CAPTURE_MIN_CALL_INTERVAL_MS, ~600ms) and the `preCapture` re-hide round trip BEFORE the actual
captureVisibleTab call -- both real async gaps a fast tab switch fits inside. Kyle's instruction: inspect
the code and Chrome API semantics first, and if there is no guarantee that the active tab at capture time
is still the intended tab, treat it as a real safety gap -- more important than the scroll-restoration
check, because it could attribute the WRONG tab's pixels to the original tab's evidence/provenance.

Inspection confirmed the gap was real. Fix: `throttledCaptureVisibleTab` now takes `tabId` and re-checks
`chrome.tabs.get(tabId)`'s `.active`/`.windowId` immediately before the `captureVisibleTab` call itself,
with no further await in between -- the tightest margin JS allows. A tab switch (or window move, or the
tab closing) in that window now fails closed with `TabIdentityError` and `captureVisibleTab` is never
called, instead of silently capturing the wrong tab.

`tests/js/run-toctou-guard.mjs` extracts this exact function (by string boundary, not a reimplementation)
out of the SHIPPED `extension/background.js` and runs it against a mock `chrome.tabs`/`chrome.storage`,
empirically proving the behavior -- not just checking the code's text shape. It refuses to pass (exit 3)
if the recheck it depends on has been removed or moved, so a future refactor that quietly drops this
protection fails loudly rather than passing a stale assertion.

`node` missing is a fact about the machine (skip), matching test_s54's convention.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "tests" / "js" / "run-toctou-guard.mjs"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("no JavaScript engine on this machine — the active-tab TOCTOU gate needs node")
    return exe


def _run(command: str) -> dict:
    proc = subprocess.run([_node(), str(RUN), command], capture_output=True, text=True, timeout=30)
    if proc.returncode not in (0, 1):
        pytest.fail(f"run-toctou-guard.mjs {command!r} exited {proc.returncode} unexpectedly:\n{proc.stderr}")
    if not proc.stdout.strip():
        pytest.fail(f"run-toctou-guard.mjs {command!r} produced no output:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_normal_case_still_captures_once():
    r = _run("stays-active")
    assert r["threw"] is False
    assert r["captureCount"] == 1
    assert r["dataUrl"]


def test_a_tab_switch_during_the_precapture_window_fails_closed_not_silently():
    """The exact scenario the correction described: the user switches to a different tab in the SAME window
    during the hide-and-settle wait. This must never reach captureVisibleTab."""
    r = _run("switches-during-precapture")
    assert r["threw"] is True
    assert r["nsErrorKind"] == "TabIdentityError", "a tab-identity failure must never fall back silently"
    assert r["captureCount"] == 0, "captureVisibleTab must not be called once the recheck fails"


def test_the_tab_moving_to_a_different_window_also_fails_closed():
    r = _run("switches-window-during-precapture")
    assert r["threw"] is True
    assert r["nsErrorKind"] == "TabIdentityError"
    assert r["captureCount"] == 0


def test_the_tab_closing_during_the_precapture_window_also_fails_closed():
    r = _run("tab-closed-during-precapture")
    assert r["threw"] is True
    assert r["nsErrorKind"] == "TabIdentityError"
    assert r["captureCount"] == 0


def test_both_real_call_sites_pass_tabid_to_the_recheck():
    """The fix is only load-bearing if every caller actually supplies a tabId -- confirms both the tiled
    loop's per-tile call and the visible-area fallback's call were updated, not just the function signature."""
    bg = (ROOT / "extension" / "background.js").read_text()
    assert "async function throttledCaptureVisibleTab(tabId, windowId, preCapture)" in bg
    calls = [ln for ln in bg.split("\n") if "throttledCaptureVisibleTab(" in ln and "async function" not in ln]
    assert len(calls) == 2, f"expected exactly 2 call sites, found {len(calls)}: {calls}"
    for ln in calls:
        assert "throttledCaptureVisibleTab(tab.id," in ln or "throttledCaptureVisibleTab(tabId," in ln, \
            f"call site does not pass a tabId as the first argument: {ln}"
