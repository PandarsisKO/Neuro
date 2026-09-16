"""S54 — send screenshot: capture-lib primitives, as a contract (extension 1.8.0, mission "send screenshot").

Full plan and revisions: see the Kyle-approved plan referenced from docs/SEND-SCREENSHOT-2026-09-16.md and from
neurosearch/api.py's api_ingest_file docstring. This file gates the extraction Phase 2c made necessary: the
in-page capture primitives (nsMeasure, nsHideAndArm, nsRestore) live in extension/capture-lib.js so they can be
loaded BOTH by background.js (importScripts, then passed by reference to chrome.scripting.executeScript) and by
this test harness (tests/js/run-capture.mjs, window.eval — the same technique tests/js/run.mjs uses for
scan-lib.js). jsdom does no real layout, so tests/fixtures/capture/sticky-fixed.html stubs getBoundingClientRect
for the elements under test; see that fixture's own comment. This proves the DOM traversal, the hide/restore
mechanics and the in-page watchdog's self-heal. It does NOT prove chrome.tabs.captureVisibleTab pixel output, DPR
crop correctness against a real screen, or OffscreenCanvas stitching — those stay live-browser gates, same as the
course scanner's live-browser boundary in docs/COURSE-SCANNER-2026-09-15.md.

`node` missing is a fact about the machine (skip). jsdom missing is a broken verify environment and FAILS.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FIX = ROOT / "tests" / "fixtures" / "capture" / "sticky-fixed.html"
RUN = ROOT / "tests" / "js" / "run-capture.mjs"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("no JavaScript engine on this machine — the send-screenshot gate needs node")
    return exe


def _run(command: str, args: list | None = None) -> dict:
    argv = [_node(), str(RUN), str(FIX), command]
    if args is not None:
        argv.append(json.dumps(args))
    out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert out.returncode != 3, "jsdom is not installed in tests/js — run `npm ci --prefix tests/js`; this gate cannot be skipped"
    assert out.returncode == 0, out.stderr[:800]
    return json.loads(out.stdout)


def test_shipped_capture_lib_exists_and_is_valid_js() -> None:
    lib = EXT / "capture-lib.js"
    assert lib.exists(), "extension/capture-lib.js must exist — background.js importScripts() it"
    out = subprocess.run([_node(), "--check", str(lib)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:400]


def test_measure_reports_viewport_and_dpr() -> None:
    m = _run("measure")
    assert m["viewportWidth"] > 0 and m["viewportHeight"] > 0
    assert m["dpr"] >= 1
    assert "Capture fixture" in m["title"]


def test_hide_hides_only_nonzero_sticky_and_fixed_elements() -> None:
    # the fixture has a sticky header, a fixed sidebar, a zero-size sticky element, and ordinary static content:
    # exactly the two non-zero sticky/fixed elements should be hidden, never the zero-size one and never the
    # ordinary section.
    r = _run("hide", [20000])
    assert r["hidden"] == 2, r
    assert r["stillHiddenCount"] == 2, r


def test_restore_undoes_the_hide_completely() -> None:
    r = _run("hide-then-restore", [20000])
    assert r["hidden"] == 2, r
    assert r["afterRestoreCount"] == 0, "nsRestore must leave no element still hidden"


def test_watchdog_self_heals_if_nothing_calls_restore() -> None:
    # this is the content-script watchdog the plan requires: an interrupted background operation (worker killed,
    # message channel severed, try/finally on the OTHER side never running) must not leave the page visually
    # altered forever. Arm with a short watchdog and wait past it WITHOUT calling nsRestore.
    r = _run("watchdog-selfheal", [150, 600])
    assert r["hidden"] == 2, r
    assert r["afterWaitCount"] == 0, "the in-page watchdog must self-restore once its timer fires, unassisted"


def test_background_js_loads_capture_lib_by_reference_not_duplication() -> None:
    # Phase 2c originally defined these functions inline in background.js; they were extracted to capture-lib.js
    # specifically so this test file could exercise the SHIPPED source. Guard against the extraction silently
    # reverting to an inline duplicate (which would make this file test dead code).
    bg = (EXT / "background.js").read_text()
    assert "importScripts('capture-lib.js')" in bg
    assert "function nsHideAndArm(" not in bg, "nsHideAndArm must live only in capture-lib.js, not be duplicated inline"
    assert "function nsMeasure(" not in bg, "nsMeasure must live only in capture-lib.js, not be duplicated inline"


# ---------------------------------------------------------------------------------------------------- server side
# Everything below exercises the /api/ingest/file provenance contract end to end: pending capture_events row
# written BEFORE the job is enqueued, materialized once the job resolves a source, and the queued response never
# implying a source exists yet. See neurosearch/db.py's source_captures table comment for why a separate table
# (not columns on sources) is required — global image dedupe means identical screenshot bytes can resolve to one
# sources row while representing a genuinely distinct capture event.
import io

H = {"Authorization": "Bearer t0k"}


def _png_bytes(color: tuple[int, int, int] = (30, 90, 200)) -> bytes:
    # a real, distinct 4x4 PNG per call (content-identity dedupe is global by byte hash, so tests that must NOT
    # collide with each other need genuinely different pixels, not just a different filename/title).
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def test_screenshot_upload_is_accepted_and_queued_not_immediate(client):
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Screenshots", "brief": None}).json()
    r = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "immediate": "false", "capture_url": "https://calc.example/loan",
              "capture_page_title": "Loan Calculator", "capture_mode": "full_page",
              "captured_at": "1700000000", "capture_page_width": "1280", "capture_page_height": "3400",
              "capture_viewport_width": "1280", "capture_viewport_height": "800", "capture_dpr": "2"},
        files={"file": ("screenshot.png", _png_bytes((10, 20, 30)), "image/png")},
    ).json()
    # the honest async contract: accepted + queued, never a source_id, never "ready"
    assert r["status"] == "queued"
    assert "source_id" not in r
    assert r["immediate"] is False
    assert r["job"]

    # a pending source_captures row exists, source_id still NULL
    row = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://calc.example/loan",)).fetchone()
    assert row is not None
    assert row["source_id"] is None
    assert row["capture_page_title"] == "Loan Calculator"
    assert row["capture_mode"] == "full_page"
    assert row["capture_dpr"] == 2.0


def test_screenshot_job_materializes_capture_event_and_uses_page_title(client, run_queued_job):
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Screenshots2", "brief": None}).json()
    r = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "capture_url": "https://config.example/build", "capture_page_title": "Build Configurator",
              "capture_mode": "visible_only"},
        files={"file": ("screenshot.png", _png_bytes((40, 50, 60)), "image/png")},
    ).json()
    run_queued_job(r["job"])

    row = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://config.example/build",)).fetchone()
    assert row["source_id"] is not None, "materialize_capture_event must fill in source_id once the job resolves one"
    src = db.get_source(row["source_id"])
    # the page's title, not the uploaded filename ("screenshot.png"), becomes the source title
    assert src["title"] == "Build Configurator"


def test_screenshot_note_never_becomes_title_or_is_lost(client, run_queued_job):
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Screenshots3", "brief": None}).json()
    r = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "capture_url": "https://dash.example/q3", "capture_page_title": "Q3 Dashboard",
              "capture_mode": "full_page", "capture_note": "this is the state right before the renewal call"},
        files={"file": ("screenshot.png", _png_bytes((70, 80, 90)), "image/png")},
    ).json()
    run_queued_job(r["job"])

    row = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://dash.example/q3",)).fetchone()
    assert row["capture_note"] == "this is the state right before the renewal call"
    src = db.get_source(row["source_id"])
    assert src["title"] == "Q3 Dashboard"
    assert "renewal call" not in (src["title"] or "")


def test_partial_capture_reason_recorded_on_ceiling(client, run_queued_job):
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Screenshots4", "brief": None}).json()
    r = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "capture_url": "https://feed.example/infinite", "capture_page_title": "Infinite Feed",
              "capture_mode": "full_page", "capture_partial_reason": "ceiling_pixels"},
        files={"file": ("screenshot.png", _png_bytes((100, 110, 120)), "image/png")},
    ).json()
    run_queued_job(r["job"])
    row = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://feed.example/infinite",)).fetchone()
    assert row["capture_partial_reason"] == "ceiling_pixels"


def test_two_captures_of_identical_bytes_both_get_their_own_capture_event(client, run_queued_job):
    """Global image dedupe means identical screenshot bytes resolve to ONE sources row — but two presses of
    "Send screenshot" (different times, possibly different projects/notes) must still be two distinct
    source_captures rows pointing at that same source. This is the core reason source_captures is its own table
    rather than columns on sources."""
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Screenshots5", "brief": None}).json()
    png = _png_bytes((200, 60, 15))

    r1 = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "capture_url": "https://site.example/a", "capture_page_title": "Page A",
              "capture_mode": "visible_only"},
        files={"file": ("screenshot.png", png, "image/png")},
    ).json()
    run_queued_job(r1["job"])

    r2 = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "capture_url": "https://site.example/b-later", "capture_page_title": "Page B Later",
              "capture_mode": "visible_only", "capture_note": "second capture, same pixels"},
        files={"file": ("screenshot.png", png, "image/png")},
    ).json()
    run_queued_job(r2["job"])

    row1 = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://site.example/a",)).fetchone()
    row2 = db.connect().execute("SELECT * FROM source_captures WHERE capture_url=?", ("https://site.example/b-later",)).fetchone()
    assert row1["source_id"] == row2["source_id"], "identical bytes must dedupe to the same global source"
    assert row1["id"] != row2["id"], "but each press is still its own capture event"

    events = db.get_capture_events_for_source(row1["source_id"])
    assert len(events) == 2
    assert {e["capture_url"] for e in events} == {"https://site.example/a", "https://site.example/b-later"}
