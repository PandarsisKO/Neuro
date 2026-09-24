"""S92 (2026-09-24) — Kyle: "reddit posts are getting blocked, but the chrome extension would work. from the sources
progress window we need a button to launch it in a new tab and trigger the chrome extension. it should be obvious,
especially because I frequently copy paste URLs without actually opening them in a new browser window and then
forget about them once I hit ADD."

The machinery existed (B1: the job parks as external_pending/browser, the extension badge lights on the tab, the
Browser-capture card's "Open & Capture" opened the tab) but the person still had to find the card, and then press
the extension's button. Now: the job's own row in the In-progress box carries "Open & capture in Chrome" (and the
job is hot, so it is visible collapsed); the app opens the URL with `#neuro-capture`; the extension's background
worker sees that fragment on a page it has a pending request for and runs the capture itself, no popup click."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
R = (ROOT / "neurosearch" / "web" / "js" / "research.js").read_text()
S = (ROOT / "neurosearch" / "web" / "js" / "sources.js").read_text()
BG = (ROOT / "extension" / "background.js").read_text()
POP = (ROOT / "extension" / "popup.js").read_text()
LIB = (ROOT / "extension" / "thread-capture.js").read_text()
HTML = (ROOT / "extension" / "popup.html").read_text()


def test_the_progress_row_offers_open_and_capture_and_stays_visible():
    assert "Open & capture in Chrome</button>" in R          # no emoji prefix: CL-6, gated by test_s50
    assert "j.status === 'external_pending' && j.external_provider === 'browser' && j.external_handle" in R
    assert "(j.status === 'external_pending' && j.external_provider === 'browser')" in R.split("const isHot")[1].split("\n")[0], "hot: shown even when the box is collapsed"
    assert "'needs your browser'" in R


def test_the_app_marks_the_tab_it_opens():
    assert "u.hash = 'neuro-capture'" in S


def test_the_extension_captures_a_marked_tab_on_its_own():
    assert "const AUTO_MARK = 'neuro-capture';" in BG and "async function autoCapture(tab)" in BG
    assert "hit.adapter === 'reddit_thread' ? await redditCapture(tab) : await pageCapture(tab)" in BG
    assert "autoCapture(tab)" in BG.split("chrome.tabs.onUpdated.addListener")[1]
    assert "if (!hash.includes(AUTO_MARK)) return;" in BG, "a tab the person opened by hand is never captured without the popup button"
    assert "importScripts('thread-capture.js');" in BG


def test_the_producers_are_shared_not_duplicated():
    assert "async function redditCapture(tab)" in LIB and "async function pageCapture(tab)" in LIB
    assert "self.NSThreadCapture = { redditCapture, pageCapture };" in LIB
    # scoped: as globals, these two would collide with the `const { redditCapture, pageCapture }` in popup.js and
    # background.js ("Identifier has already been declared") and take the popup AND the worker down — 1.9.7's first
    # load did exactly that
    assert LIB.strip().startswith("//") and "(() => {" in LIB and LIB.rstrip().endswith("})();")
    assert "async function redditCapture" not in POP and "const { redditCapture, pageCapture } = self.NSThreadCapture;" in POP
    assert '<script src="thread-capture.js"></script>' in HTML and HTML.index("thread-capture.js") < HTML.index('src="popup.js"')
    assert "// ---- B1:" in POP and "async function load()" in POP, "markers the extension-auth harness slices on"


def test_extension_version_bumped():
    assert json.loads((ROOT / "extension" / "manifest.json").read_text())["version"] == "1.9.7"
