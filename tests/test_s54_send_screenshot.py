"""S54 — send screenshot: capture-lib primitives, as a contract (extension 1.9.3, mission "send screenshot").

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


def test_hide_scrollbars_injects_a_style_element() -> None:
    # Case 2 regression (2026-09-16 live-Chrome acceptance, Finviz Stock Screener at 900x557 against a
    # 1020x1447 page): the browser's own page-level scrollbar is rendered as a viewport overlay and gets baked
    # into every captureVisibleTab screenshot. When tile rows land back-to-back with no vertical overlap
    # (nsPlanTileGrid only overlaps where it clamps the last row), nothing is ever drawn over that band, and a
    # real content row was permanently replaced by a scrollbar graphic in the stitched image -- confirmed by
    # comparing the stitched PNG against the live, unmodified page at the same scroll position. Unlike sticky
    # elements, there is no "natural" tile where a baked-in scrollbar is correct, so this must be hidden even
    # for the first tile.
    r = _run("hide-scrollbars", [20000])
    assert r["styleElPresent"] is True, r


def test_restore_scrollbars_undoes_the_hide_completely() -> None:
    r = _run("hide-scrollbars-then-restore", [20000])
    assert r["before"] is True, r
    assert r["after"] is False, "nsRestoreScrollbars must remove the injected style element"


def test_scrollbars_watchdog_self_heals_if_nothing_calls_restore() -> None:
    # Same resilience contract as the sticky/fixed watchdog: if the background operation is interrupted, the
    # live page must not end up with its scrollbar permanently, invisibly hidden.
    r = _run("scrollbars-watchdog-selfheal", [150, 600])
    assert r["before"] is True, r
    assert r["afterWait"] is False, "the scrollbar watchdog must self-restore once its timer fires, unassisted"


def test_background_js_loads_capture_lib_by_reference_not_duplication() -> None:
    # Phase 2c originally defined these functions inline in background.js; they were extracted to capture-lib.js
    # specifically so this test file could exercise the SHIPPED source. Guard against the extraction silently
    # reverting to an inline duplicate (which would make this file test dead code). The repair round added
    # capture-blob-store.js as a second importScripts() argument (service-worker-only, never page-injected) --
    # both must load by reference, and neither's functions may be duplicated inline.
    bg = (EXT / "background.js").read_text()
    assert "importScripts('capture-lib.js', 'capture-blob-store.js')" in bg
    assert "function nsHideAndArm(" not in bg, "nsHideAndArm must live only in capture-lib.js, not be duplicated inline"
    assert "function nsMeasure(" not in bg, "nsMeasure must live only in capture-lib.js, not be duplicated inline"


def test_run_capture_hides_scrollbars_before_the_first_tile_not_just_later_ones() -> None:
    # background.js must arm nsHideScrollbars ONCE before the tile loop begins -- covering the very first tile,
    # where sticky-element hiding (nsHideAndArm, gated by `firstTileCaptured`) is deliberately skipped. Guards
    # against the fix being wired in only for tile 2+ (which would leave the exact case this regression covers
    # -- the first tile row's un-overlapped bottom band -- still corrupted).
    bg = (EXT / "background.js").read_text()
    assert "nsHideScrollbars" in bg and "nsRestoreScrollbars" in bg
    before_loop = bg.split("let grid = nsPlanTileGrid(dims, viewportWidth, viewportHeight).tiles;")[0]
    assert "nsHideScrollbars" in before_loop.split("const viewportWidth = m0.viewportWidth")[-1], (
        "nsHideScrollbars must be armed before the tile loop starts, not gated behind firstTileCaptured")
    assert "function nsPlanTileGrid(" not in bg, "nsPlanTileGrid must live only in capture-lib.js, not be duplicated inline"
    assert (EXT / "capture-blob-store.js").exists(), "extension/capture-blob-store.js must exist — background.js importScripts() it"
    blob_store = (EXT / "capture-blob-store.js").read_text()
    assert "function nsBlobRetentionPlan(" in blob_store
    assert "indexedDB" in blob_store


def test_init_db_migrates_a_source_captures_table_that_predates_repair_round(tmp_path, monkeypatch) -> None:
    """Regression for a real bug found 2026-09-16 opening a same-day backup snapshot for the Kyle-gate readiness
    pass: `capture_partial_reason`, `client_capture_id` and `ingest_job_id` were added straight into
    `source_captures`'s CREATE TABLE statement (the repair round added them to an ALREADY-EXISTING table) instead
    of through db.MIGRATIONS. `CREATE TABLE IF NOT EXISTS` is a no-op against a pre-existing table, so any
    `source_captures` table that predates the repair round -- any backup taken between the original ship and the
    repair round, or a live process never restarted since -- made `init_db()` crash outright: the very next
    `executescript(SCHEMA)` statement, the unique index on `client_capture_id`, referenced a column that did not
    exist yet, and that happens before the MIGRATIONS loop even runs. Reproduces the exact pre-repair-round table
    shape and proves init_db() now migrates it cleanly instead of crashing the app on the next restart."""
    import sqlite3
    from neurosearch import db
    from neurosearch.config import settings

    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "neurosearch.db")
    conn.executescript("""
        CREATE TABLE source_captures (
            id TEXT PRIMARY KEY, source_id TEXT, project_id TEXT, capture_url TEXT NOT NULL,
            capture_page_title TEXT, captured_at REAL NOT NULL, capture_mode TEXT NOT NULL,
            capture_page_width INTEGER, capture_page_height INTEGER, capture_viewport_width INTEGER,
            capture_viewport_height INTEGER, capture_dpr REAL, capture_note TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE INDEX ix_source_captures_source ON source_captures(source_id);
    """)
    conn.commit()
    conn.close()

    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(db._local, "conn", None, raising=False)
    try:
        db.init_db()  # must not raise
        conn = db.connect()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(source_captures)").fetchall()}
        assert {"capture_partial_reason", "client_capture_id", "ingest_job_id"} <= cols
        idx = {r[1] for r in conn.execute("PRAGMA index_list(source_captures)").fetchall()}
        assert "ix_source_captures_client_capture_id" in idx
        # the migrated table is actually usable through the real write path, not just structurally present
        conn.execute(
            "INSERT INTO source_captures (id, source_id, project_id, capture_url, captured_at, capture_mode, "
            "client_capture_id, ingest_job_id, created_at, updated_at) VALUES "
            "('c1', NULL, 'p1', 'https://example.com', 0, 'full_page', 'cap-1', 'job-1', 0, 0)")
        conn.commit()
        assert conn.execute("SELECT client_capture_id FROM source_captures WHERE id='c1'").fetchone()[0] == "cap-1"
    finally:
        try:
            db.connect().close()
        except Exception:
            pass
        db._local.conn = None



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


# ------------------------------------------------------------------------------------------- capture_id idempotency
# Server-side gates for db.create_or_get_capture_ingest_request / the capture_id-aware branch of api_ingest_file
# (repair round 4's atomicity fix). See db.py's function docstring for the full design rationale.

def test_retry_with_same_capture_id_reuses_the_same_job_and_deletes_the_orphan_temp_file(client, run_queued_job):
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Idem1", "brief": None}).json()
    png = _png_bytes((11, 22, 33))
    common = dict(project_id=p["id"], capture_url="https://idem.example/retry", capture_page_title="Retry Page",
                  capture_mode="full_page", capture_id="cap-retry-1")

    r1 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    assert r1["status"] == "queued"
    assert "source_id" not in r1

    # retry: same capture_id, same bytes, as the extension would resend after a lost response
    r2 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    assert r2["job"] == r1["job"], "a retry with the same capture_id must return the SAME job, never a new one"

    row = db.connect().execute("SELECT * FROM source_captures WHERE client_capture_id=?", ("cap-retry-1",)).fetchone()
    assert row is not None
    assert row["ingest_job_id"] == r1["job"]

    # exactly one source_captures row for this capture_id, not two
    n = db.connect().execute("SELECT COUNT(*) c FROM source_captures WHERE client_capture_id=?", ("cap-retry-1",)).fetchone()["c"]
    assert n == 1

    run_queued_job(r1["job"])
    row = db.connect().execute("SELECT * FROM source_captures WHERE client_capture_id=?", ("cap-retry-1",)).fetchone()
    assert row["source_id"] is not None


def test_retry_after_job_finished_reports_current_status_not_hardcoded_queued(client, run_queued_job):
    p = client.post("/api/projects", headers=H, json={"name": "Idem2", "brief": None}).json()
    png = _png_bytes((44, 55, 66))
    common = dict(project_id=p["id"], capture_url="https://idem.example/late-retry", capture_page_title="Late Retry",
                  capture_mode="full_page", capture_id="cap-retry-late")

    r1 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    run_queued_job(r1["job"])

    # a retry landing AFTER the job already completed must not lie and say "queued"
    r2 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    assert r2["job"] == r1["job"]
    assert r2["status"] == "done", r2


def test_concurrent_duplicate_capture_id_requests_create_exactly_one_job(client):
    """Real threads hitting the endpoint concurrently with the same capture_id — the gate for the
    create_or_get_capture_ingest_request atomicity fix (repair round 4)."""
    import threading
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Idem3", "brief": None}).json()
    png = _png_bytes((77, 88, 99))
    common = dict(project_id=p["id"], capture_url="https://idem.example/race", capture_page_title="Race Page",
                  capture_mode="full_page", capture_id="cap-http-race")

    results = []
    lock = threading.Lock()

    def fire():
        r = client.post("/api/ingest/file", headers=H, data=common,
                         files={"file": ("screenshot.png", png, "image/png")}).json()
        with lock:
            results.append(r)

    threads = [threading.Thread(target=fire) for _ in range(6)]
    for t in threads: t.start()
    for t in threads: t.join()

    job_ids = {r["job"] for r in results}
    assert len(job_ids) == 1, f"expected exactly one job across all concurrent retries, got {job_ids}"

    n = db.connect().execute("SELECT COUNT(*) c FROM source_captures WHERE client_capture_id=?", ("cap-http-race",)).fetchone()["c"]
    assert n == 1, "exactly one source_captures row, no matter how many concurrent requests raced for it"


def test_losing_retry_deletes_its_own_orphan_temp_upload(client, tmp_path, monkeypatch):
    """The loser of a capture_id race must clean up its own just-written temp file — the winner's job already
    references the winner's own upload, so a losing request's file would otherwise leak forever."""
    from neurosearch.config import settings as _settings

    p = client.post("/api/projects", headers=H, json={"name": "Idem4", "brief": None}).json()
    png = _png_bytes((123, 45, 67))
    common = dict(project_id=p["id"], capture_url="https://idem.example/cleanup", capture_page_title="Cleanup Page",
                  capture_mode="full_page", capture_id="cap-cleanup-1")

    before = {f.name for f in _settings.media_dir.glob("upload_*")}
    r1 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    r2 = client.post("/api/ingest/file", headers=H, data=common,
                      files={"file": ("screenshot.png", png, "image/png")}).json()
    after = {f.name for f in _settings.media_dir.glob("upload_*")}

    new_files = after - before
    # both requests wrote a temp file; only ONE should survive (the winner's) since the loser deletes its own
    assert len(new_files) == 1, f"expected exactly one surviving temp upload, found {new_files}"
    assert r1["job"] == r2["job"]


# --------------------------------------------------------------------------------------- project-scoped provenance
# sources_value.digest() surfaces the capture provenance in the source drawer (repair round, item 9: "stored but
# not surfaced") -- project-scoped only, never cross-project or global-most-recent, since the same (dedup-shared)
# source can be captured from more than one project.

def test_digest_surfaces_the_newest_capture_for_this_project_only(client, run_queued_job):
    from neurosearch import db
    from neurosearch.sources_value import digest

    p1 = client.post("/api/projects", headers=H, json={"name": "Prov1", "brief": None}).json()
    p2 = client.post("/api/projects", headers=H, json={"name": "Prov2", "brief": None}).json()
    png = _png_bytes((5, 15, 25))   # identical bytes -> one shared global source

    r1 = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p1["id"], "capture_url": "https://prov.example/p1", "capture_page_title": "P1 Snapshot",
              "capture_mode": "full_page", "capture_note": "note for project 1", "capture_id": "cap-prov-1"},
        files={"file": ("screenshot.png", png, "image/png")},
    ).json()
    run_queued_job(r1["job"])

    r2 = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p2["id"], "capture_url": "https://prov.example/p2", "capture_page_title": "P2 Snapshot",
              "capture_mode": "visible_only", "capture_note": "note for project 2", "capture_id": "cap-prov-2"},
        files={"file": ("screenshot.png", png, "image/png")},
    ).json()
    run_queued_job(r2["job"])

    row1 = db.connect().execute("SELECT * FROM source_captures WHERE client_capture_id=?", ("cap-prov-1",)).fetchone()
    row2 = db.connect().execute("SELECT * FROM source_captures WHERE client_capture_id=?", ("cap-prov-2",)).fetchone()
    assert row1["source_id"] == row2["source_id"], "identical bytes must still dedupe to one global source"
    sid = row1["source_id"]

    d1 = digest(p1["id"], sid)
    assert d1["capture"] is not None
    assert d1["capture"]["url"] == "https://prov.example/p1"
    assert d1["capture"]["page_title"] == "P1 Snapshot"
    assert d1["capture"]["note"] == "note for project 1"

    d2 = digest(p2["id"], sid)
    assert d2["capture"] is not None
    assert d2["capture"]["url"] == "https://prov.example/p2"
    assert d2["capture"]["note"] == "note for project 2"

    # the HTTP endpoint too, end to end
    via_api1 = client.get(f"/api/projects/{p1['id']}/sources/{sid}/digest", headers=H).json()
    assert via_api1["capture"]["url"] == "https://prov.example/p1"


def test_digest_capture_is_none_when_this_project_never_captured_the_source(client, run_queued_job):
    from neurosearch import db
    from neurosearch.sources_value import digest

    p = client.post("/api/projects", headers=H, json={"name": "Prov3", "brief": None}).json()
    png = _png_bytes((99, 88, 77))   # an ordinary image upload -- no capture_url, so no source_captures row at all
    r = client.post(
        "/api/ingest/file", headers=H,
        data={"project_id": p["id"], "title": "Uploaded, not captured"},
        files={"file": ("plain.png", png, "image/png")},
    ).json()
    run_queued_job(r["job"])
    row = db.connect().execute("SELECT id FROM sources ORDER BY created_at DESC LIMIT 1").fetchone()
    d = digest(p["id"], row["id"])
    assert d["capture"] is None


# --------------------------------------------------------------------------------- pure capture-engine helper gates
# capture-lib.js's pure (non-DOM) functions, repair round #127 — exercised the same way the DOM helpers above are
# (tests/js/run-capture.mjs, under jsdom), proving the tiling/ceiling/rate-limit/reconciliation math independent
# of any real chrome.* API or real captureVisibleTab call.

def test_tile_grid_is_1x1_for_a_page_that_fits_in_one_viewport() -> None:
    g = _run("plan-tile-grid", [{"scrollWidth": 1200, "scrollHeight": 700}, 1280, 800])
    assert g["rows"] == 1 and g["cols"] == 1
    assert g["tiles"] == [{"row": 0, "col": 0, "x": 0, "y": 0}]


def test_tile_grid_covers_a_page_taller_and_wider_than_the_viewport() -> None:
    g = _run("plan-tile-grid", [{"scrollWidth": 2600, "scrollHeight": 1700}, 1280, 800])
    assert g["rows"] == 3 and g["cols"] == 3   # ceil(1700/800)=3 rows, ceil(2600/1280)=3 cols
    # last row/col are clamped to (scrollDim - viewportDim), not overshooting past the true edge
    xs = sorted({t["x"] for t in g["tiles"]})
    ys = sorted({t["y"] for t in g["tiles"]})
    assert xs[-1] == 2600 - 1280
    assert ys[-1] == 1700 - 800


def test_whole_capture_tile_identity_catches_a_non_adjacent_repeat() -> None:
    # A -> B -> A: the repeat is not adjacent to the first A, so an adjacent-only comparison would miss it.
    dupes = _run("dedupe-tiles", [[[0, 0], [0, 800], [0, 0]]])
    assert dupes == [False, False, True]


def test_ceilings_check_actual_progress_not_planned_grid_size() -> None:
    under = _run("check-ceilings", [{"elapsedMs": 100, "tilesCaptured": 2, "totalPixels": 1000},
                                     {"maxElapsedMs": 60000, "maxTiles": 30, "maxTotalPixels": 40_000_000}])
    assert under["reason"] is None
    over_time = _run("check-ceilings", [{"elapsedMs": 70000, "tilesCaptured": 2, "totalPixels": 1000},
                                         {"maxElapsedMs": 60000, "maxTiles": 30, "maxTotalPixels": 40_000_000}])
    assert over_time["reason"] == "ceiling_time"
    over_tiles = _run("check-ceilings", [{"elapsedMs": 100, "tilesCaptured": 31, "totalPixels": 1000},
                                          {"maxElapsedMs": 60000, "maxTiles": 30, "maxTotalPixels": 40_000_000}])
    assert over_tiles["reason"] == "ceiling_folds"
    over_pixels = _run("check-ceilings", [{"elapsedMs": 100, "tilesCaptured": 2, "totalPixels": 50_000_000},
                                           {"maxElapsedMs": 60000, "maxTiles": 30, "maxTotalPixels": 40_000_000}])
    assert over_pixels["reason"] == "ceiling_pixels"


def test_stitch_scale_uses_real_bitmap_width_not_dpr_alone() -> None:
    # a 2x DPR screen would normally suggest scale=2, but the REAL bitmap can differ (zoom, rounding) -- the scale
    # must come from the actual captured bitmap width vs the CSS viewport width, not devicePixelRatio.
    r = _run("stitch-scale", [2560, 1280])
    assert r["scale"] == 2
    r2 = _run("stitch-scale", [1900, 1280])   # a real, non-round scale
    assert abs(r2["scale"] - 1900 / 1280) < 1e-9


def test_rate_limit_wait_ms_enforces_the_global_throttle() -> None:
    r = _run("rate-limit-wait", [1000, 1300, 600])   # only 300ms elapsed of a required 600ms
    assert r["waitMs"] == 300
    r2 = _run("rate-limit-wait", [1000, 1700, 600])  # 700ms elapsed -- already clear
    assert r2["waitMs"] == 0
    r3 = _run("rate-limit-wait", [None, 1700, 600])  # never called yet -- no wait
    assert r3["waitMs"] == 0


def test_fallback_eligibility_is_mechanism_only_never_identity() -> None:
    assert _run("fallback-eligible", ["CaptureMechanismError"])["eligible"] is True
    assert _run("fallback-eligible", ["TabIdentityError"])["eligible"] is False
    assert _run("fallback-eligible", ["SomethingElse"])["eligible"] is False   # fails closed on an unrecognized tag


def test_worker_restart_reconciliation_decisions() -> None:
    # 'capturing' -> hard failed (nothing will ever resume the loop that owned it; never reached the durable-blob
    # step either, so blobExists is irrelevant here)
    d1 = _run("reconcile-decision", [{"status": "capturing"}, 1000, False])
    assert d1["status"] == "failed"
    # 'uploading' WITH its blob still present -> recoverable upload_failed (capture_id idempotency makes a retry
    # safe, and there is something for capture-retry to actually resubmit)
    d2 = _run("reconcile-decision", [{"status": "uploading"}, 1000, True])
    assert d2["status"] == "upload_failed"
    # 'uploading' but the blob is GONE (repair round 2's fix) -> hard failed, never an upload_failed the popup
    # would offer a "Retry send" for with nothing behind it
    d3 = _run("reconcile-decision", [{"status": "uploading"}, 1000, False])
    assert d3["status"] == "failed"
    assert "not saved" in d3["error"] or "capture again" in d3["error"]
    # terminal states are left alone regardless of blobExists
    for terminal in ("done", "failed", "upload_failed"):
        assert _run("reconcile-decision", [{"status": terminal}, 1000, True]) is None
        assert _run("reconcile-decision", [{"status": terminal}, 1000, False]) is None


# --------------------------------------------------------------------------------------------- structural gates
# A few properties of the shipped orchestration (background.js) that a jsdom harness cannot exercise without a
# full chrome.* mock (worker-respawn timing, the captureVisibleTab rate limiter, durability ordering) are gated
# here as source-shape assertions instead — the same approach test_background_js_loads_capture_lib_by_reference_
# not_duplication above already uses for "loaded by reference, not inlined".

def test_captureinit_is_awaited_at_the_four_gated_call_sites() -> None:
    bg = (EXT / "background.js").read_text()
    # the four call sites the approved repair plan names explicitly
    assert bg.count("await captureInit;") >= 4, "capture-start, capture-retry, capture-get and startScan's capture check must each await captureInit"
    # placed AFTER listener registration in the source (unawaited top-level kickoff), not before
    assert bg.index("chrome.runtime.onMessage.addListener") < bg.index("const captureInit = reconcileCapturesOnWorkerInit();")


def test_durability_ordering_captured_before_blob_before_uploading() -> None:
    # repair round 3 (gap #C): metadata persists as 'captured' BEFORE the blob write, so a crash between them
    # leaves an honest 'captured'-with-no-blob (hard failure) rather than the old 'capturing' (which
    # nsReconcileDecision always failed outright, discarding a blob that might have actually made it to disk).
    # The blob write must still land before status flips to 'uploading', before the POST.
    bg = (EXT / "background.js").read_text()
    captured_idx = bg.index("rec.status = 'captured'; rec.updated_at = now();")
    put_idx = bg.index("await NSBlobStore.put(capture_id, out.blob);")
    uploading_idx = bg.index("rec.status = 'uploading'; rec.updated_at = now();\n      await putCapture(rec);\n\n      const uploadRes")
    upload_call_idx = bg.index("const uploadRes = await uploadCapture(rec);")
    assert captured_idx < put_idx < uploading_idx < upload_call_idx, \
        "metadata must persist as 'captured' before the blob write, which must land before status flips to 'uploading', before the POST"


def test_capture_id_travels_on_every_upload_and_retry() -> None:
    bg = (EXT / "background.js").read_text()
    assert "fd.append('capture_id', rec.capture_id);" in bg
    # uploadCapture is the SINGLE shared function both the first attempt and capture-retry call
    assert bg.count("await uploadCapture(rec);") == 2


def test_sticky_hide_uses_firsttilecaptured_not_a_fold_index() -> None:
    bg = (EXT / "background.js").read_text()
    assert "if (firstTileCaptured) {" in bg
    assert "fold > 0" not in bg, "the old 1D fold-index rule must not survive the 2D tiling rewrite"


def test_per_tile_identity_reverification_before_every_capturevisibletab_call() -> None:
    bg = (EXT / "background.js").read_text()
    # every call to throttledCaptureVisibleTab is preceded by a fresh verifyTabIdentity in the same try block
    assert bg.count("await verifyTabIdentity(") >= 3   # runCapture's start, per-tile, and the fallback
    assert bg.count("await throttledCaptureVisibleTab(") == 2   # the tile loop and the fallback
    # the literal chrome API call appears exactly once in the whole file — inside throttledCaptureVisibleTab
    # itself — so nothing can reach captureVisibleTab without going through the rate limiter + its windowId arg
    assert bg.count("chrome.tabs.captureVisibleTab(") == 1


# ------------------------------------------------------------------------------- atomicity under injected failure
def test_create_or_get_capture_ingest_request_leaves_no_orphan_row_if_job_creation_fails(client) -> None:
    """A crash between the source_captures INSERT and the create_job() call, inside the SAME db.batch(), must
    roll back the whole batch -- never a capture_events row committed with no job attached."""
    from neurosearch import db

    p = client.post("/api/projects", headers=H, json={"name": "Atomic1", "brief": None}).json()

    real_create_job = db.create_job
    def boom(*a, **kw):
        raise RuntimeError("injected failure between the two writes")
    db.create_job = boom
    try:
        with pytest.raises(RuntimeError):
            db.create_or_get_capture_ingest_request(
                client_capture_id="cap-atomic-1", capture_url="https://atomic.example/x", capture_mode="full_page",
                job_kind="ingest_file", job_payload={"path": "/dev/null", "name": "x", "project_id": p["id"]},
                project_id=p["id"],
            )
    finally:
        db.create_job = real_create_job

    row = db.connect().execute("SELECT * FROM source_captures WHERE client_capture_id=?", ("cap-atomic-1",)).fetchone()
    assert row is None, "the failed batch must leave NO source_captures row behind, not an orphan with no job"

    # a subsequent, real request with the SAME client_capture_id must succeed cleanly (nothing left over to collide with)
    r2 = db.create_or_get_capture_ingest_request(
        client_capture_id="cap-atomic-1", capture_url="https://atomic.example/x", capture_mode="full_page",
        job_kind="ingest_file", job_payload={"path": "/dev/null", "name": "x", "project_id": p["id"]},
        project_id=p["id"],
    )
    assert r2["created"] is True


# ------------------------------------------------------------------------------- grid-regrowth traversal (gap 1)
# Second review round: nsPlanTileGrid is row-major, so a page growing WIDER mid-capture (a new column) inserts
# tiles EARLIER in the new grid than a walk that kept its old index would ever revisit — those tiles would be
# silently skipped while the result is still labeled full_page. simulate-growth-traversal in run-capture.mjs
# mirrors runCapture's exact walk (including the idx=0-reset-on-regrowth fix) using only the real pure helpers.

def test_grid_growth_restarts_traversal_and_covers_every_new_tile() -> None:
    # starts 1 column tall (2 rows); after the 2nd tile is captured the page becomes 2 columns wide too
    r = _run("simulate-growth-traversal", [
        {"scrollWidth": 1200, "scrollHeight": 1600}, 1280, 800,
        [{"afterTiles": 2, "dims": {"scrollWidth": 2600, "scrollHeight": 1600}}],
    ])
    assert r["coveredAll"] is True, r
    assert r["finalGridSize"] == 6   # 3 rows x 2 cols after growth
    assert not r["guardTripped"]


def test_grid_growth_in_height_alone_still_covers_every_tile() -> None:
    # height-only growth never reshuffles column indices, but must still be covered end to end
    r = _run("simulate-growth-traversal", [
        {"scrollWidth": 1200, "scrollHeight": 800}, 1280, 800,
        [{"afterTiles": 1, "dims": {"scrollWidth": 1200, "scrollHeight": 2400}}],
    ])
    assert r["coveredAll"] is True, r


def test_repeated_growth_events_still_converge_and_cover_everything() -> None:
    r = _run("simulate-growth-traversal", [
        {"scrollWidth": 1280, "scrollHeight": 800}, 1280, 800,
        [{"afterTiles": 1, "dims": {"scrollWidth": 2600, "scrollHeight": 800}},
         {"afterTiles": 3, "dims": {"scrollWidth": 2600, "scrollHeight": 2000}}],
    ])
    assert r["coveredAll"] is True, r
    assert not r["guardTripped"]


def test_runcapture_resets_idx_on_any_grid_regrowth() -> None:
    # structural gate: the ONE place background.js recomputes the grid after growth must also reset idx to 0 —
    # this is what simulate-growth-traversal's algorithm mirrors and what the tests above depend on staying true.
    bg = (EXT / "background.js").read_text()
    start = bg.index("if (m.scrollWidth > dims.scrollWidth || m.scrollHeight > dims.scrollHeight) {")
    # brace-balance to find the matching close of this if-block, not just the first '}' (which closes the
    # nested `dims = {...}` object literal one line in)
    depth = 0
    end = start
    for i in range(start, len(bg)):
        if bg[i] == '{':
            depth += 1
        elif bg[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    regrow_block = bg[start:end]
    assert "idx = 0;" in regrow_block, "grid regrowth must restart the tile walk from 0, or newly-inserted earlier tiles can be silently skipped"


def test_reconciliation_checks_blob_existence_before_offering_a_retry() -> None:
    # structural gate: reconcileCapturesOnWorkerInit must consult NSBlobStore before calling nsReconcileDecision,
    # not assume every 'uploading' record's blob survived (repair round 2's fix for gap #2).
    bg = (EXT / "background.js").read_text()
    fn = bg[bg.index("async function reconcileCapturesOnWorkerInit()"):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "NSBlobStore.get(v.capture_id)" in fn
    assert "nsReconcileDecision(v, nowMs, blobExists)" in fn


def test_heartbeat_alarm_prunes_blobs_so_the_ttl_is_actually_enforced() -> None:
    # structural gate (repair round 2, gap #3): the periodic heartbeat alarm (every 5 min) must invoke
    # pruneCaptures() (which calls NSBlobStore.pruneExpired()), not just onInstalled/onStartup and a successful
    # upload's own cleanup — otherwise a failed screenshot's blob can outlive its promised 2h TTL for the rest of
    # a long-running Chrome session.
    bg = (EXT / "background.js").read_text()
    handler = bg[bg.index("chrome.alarms.onAlarm.addListener"):]
    handler = handler[:handler.index("\n});") + 4]
    assert "pruneCaptures();" in handler
    assert "a.name === ALARM" in handler


def test_pixel_ceiling_uses_captured_scale_not_dpr() -> None:
    # structural gate (repair round 2, gap #4): the running totalPixels total used for the 40M-pixel safety
    # ceiling must be derived from the actual captured bitmap's scale (same technique stitchShots uses via
    # nsStitchScale), not from devicePixelRatio alone -- Chrome's real captureVisibleTab output can differ from
    # cssPixels * dpr under zoom/rounding, so a dpr-based ceiling can disagree with what actually gets stitched.
    bg = (EXT / "background.js").read_text()
    start = bg.index("const totalPixels = viewportWidth")
    line_start = bg.rindex("\n", 0, start) + 1
    line_end = bg.index("\n", start)
    totals_line = bg[line_start:line_end]
    assert "dpr" not in totals_line, "the totalPixels ceiling calculation must not read dpr directly any more"
    assert "effScale" in totals_line or "capturedScale" in totals_line

    # capturedScale must actually be derived from a real captured bitmap via nsStitchScale, with a dpr fallback
    # only on decode failure (never letting ceiling accounting block or fail the capture itself).
    derive_start = bg.index("if (capturedScale == null) {")
    derive_end = bg.index("\n      }\n", derive_start)
    derive_block = bg[derive_start:derive_end]
    assert "createImageBitmap" in derive_block
    assert "nsStitchScale(bmp.width, viewportWidth)" in derive_block
    assert "capturedScale = dpr;" in derive_block, "a bitmap-decode failure must fall back to dpr for accounting only, never block capture"


def test_dpr_still_used_as_provenance_only() -> None:
    # gap #4 explicitly keeps dpr as pure provenance metadata everywhere else (e.g. the returned dimensions
    # object) -- this just guards that the provenance usage wasn't accidentally deleted alongside the ceiling fix.
    bg = (EXT / "background.js").read_text()
    dims_literals = [line for line in bg.splitlines() if "dimensions: {" in line]
    assert dims_literals, "expected at least one returned dimensions object"
    assert all("dpr" in line for line in dims_literals), "dpr must remain in every returned dimensions object as provenance"


# ------------------------------------------------------------------------------- tile-key precision (hardening a)
def test_tile_key_uses_actual_landed_coordinates_not_rounded() -> None:
    # nsTileKey/nsIsDuplicateTile must key on the exact landed (x, y) -- the design settled on deduping by real
    # landed position, and rounding could collapse two genuinely distinct fractional scroll positions (subpixel
    # offsets are real under some zoom/DPR combinations) into the same key.
    lib = (EXT / "capture-lib.js").read_text()
    assert "Math.round(x)" not in lib and "Math.round(y)" not in lib, \
        "nsTileKey must not round landed coordinates before keying on them"
    assert "function nsTileKey(x, y) { return x + ',' + y; }" in lib


def test_duplicate_tile_detection_still_distinguishes_and_still_dedupes() -> None:
    # dedupe-tiles feeds each (x, y) pair through the same seen-Set in sequence, exactly as the capture loop does
    out = _run("dedupe-tiles", [[[100.3, 200.7], [100.3, 200.7], [100, 200]]])
    assert out == [False, True, False], out
    # first sighting of a fractional position is never a duplicate; the exact same fractional position repeated
    # IS a duplicate; a distinct (unrounded) nearby position must NOT collide with it


# ------------------------------------------------------------------------------- stitch dimension mismatch (hardening b)
def test_stitch_shots_rejects_mismatched_bitmap_dimensions() -> None:
    # hardening item: stitchShots derived scale from only the first bitmap and implicitly assumed every later
    # tile shares its dimensions. It must now fail loudly (not silently misplace tiles) on a mismatch.
    bg = (EXT / "background.js").read_text()
    fn = bg[bg.index("async function stitchShots("):]
    fn = fn[:fn.index("\nasync function ", 10)]
    assert "b.bmp.width !== firstW || b.bmp.height !== firstH" in fn
    assert "inconsistent bitmap dimensions" in fn


# ------------------------------------------------------------------------------- orphan temp-file cleanup (hardening c)
def test_ingest_file_cleans_up_temp_upload_if_atomic_call_throws(client, tmp_path) -> None:
    """If db.create_or_get_capture_ingest_request raises AFTER api_ingest_file has already written the uploaded
    file to settings.media_dir, that temp file must not be leaked -- it should be deleted and the exception
    re-raised unchanged (repair round 2 hardening item)."""
    from neurosearch import db
    from neurosearch.config import settings

    p = client.post("/api/projects", headers=H, json={"name": "OrphanCleanup", "brief": None}).json()

    real = db.create_or_get_capture_ingest_request
    def boom(*a, **kw):
        raise RuntimeError("injected failure inside the atomic capture-ingest call")
    db.create_or_get_capture_ingest_request = boom

    before = {f.name for f in settings.media_dir.glob("upload_*")} if settings.media_dir.exists() else set()
    try:
        # the app's own global RuntimeError handler converts this to a 400 JSON response rather than letting
        # TestClient re-raise it -- the point of this test is the temp-file cleanup, not the error transport.
        r = client.post(
            "/api/ingest/file", headers=H,
            data={"project_id": p["id"], "immediate": "false", "capture_url": "https://orphan.example/x",
                  "capture_mode": "full_page", "capture_id": "cap-orphan-1"},
            files={"file": ("screenshot.png", _png_bytes((5, 5, 5)), "image/png")},
        )
        assert r.status_code == 400
        assert "injected failure inside the atomic capture-ingest call" in r.json()["error"]
    finally:
        db.create_or_get_capture_ingest_request = real

    after = {f.name for f in settings.media_dir.glob("upload_*")} if settings.media_dir.exists() else set()
    leaked = after - before
    assert not leaked, f"temp upload file(s) leaked after an atomic-call exception: {leaked}"


# ==================================================================================== repair round 3 (2026-09-16)
# Kyle's second independent re-review of the shipped 1.9.1 code found 3 more gaps before the live-Chrome pass:
#   A. the final stitched canvas used the full MEASURED page size even on a partial capture, so a partial capture
#      of an enormous/infinite-scroll page could still attempt to allocate an OffscreenCanvas hundreds of
#      millions of pixels large -- the 40M ceiling never actually bounded the FINAL image.
#   B. verifyTabIdentity only compared tab ORIGIN, so a same-origin navigation (example.com/a -> example.com/b)
#      passed unnoticed mid-capture while the uploaded provenance URL kept naming the page the capture started on.
#   C. a durability hole between saving the Blob and persisting 'uploading': a worker death in between left the
#      record at 'capturing', which reconciliation always fails outright -- discarding a blob that might have
#      safely reached IndexedDB. Fixed with a durable 'captured' intermediate state, checked for blob existence
#      exactly like 'uploading' already was (repair round 2, gap #2).

# ------------------------------------------------------------------------------- gap A: bounded partial-capture stitch
def test_partial_capture_stitches_only_the_captured_bounding_box_not_the_full_page() -> None:
    bg = (EXT / "background.js").read_text()
    block = bg[bg.index("const complete = idx >= grid.length && !partialReason;"):bg.index("const { blob } = await stitchShots(shots, stitchW, stitchH);") + 60]
    assert "const stitchW = complete ? Math.max(pageW, shotsMaxX) : shotsMaxX;" in block
    assert "const stitchH = complete ? Math.max(pageH, shotsMaxY) : shotsMaxY;" in block
    assert "await stitchShots(shots, stitchW, stitchH)" in block, \
        "a partial capture must stitch only the bounding box of what was actually captured, not the full measured page"
    # the reported page_width/page_height provenance is a SEPARATE concern from the stitch canvas size -- an
    # honest partial_page label should still report the page's true measured size, not shrink it down to match
    # what got captured (that would make an incomplete capture look like a smaller, complete one)
    assert "const finalPageW = Math.max(pageW, shotsMaxX);" in block
    assert "const finalPageH = Math.max(pageH, shotsMaxY);" in block


def test_stitch_shots_preflights_canvas_size_against_the_pixel_ceiling() -> None:
    # stitchShots must refuse to allocate an OffscreenCanvas beyond the safety ceiling no matter what its caller
    # asks it to stitch -- a backstop independent of whatever runCapture computed for stitchW/stitchH.
    bg = (EXT / "background.js").read_text()
    fn = bg[bg.index("async function stitchShots("):]
    fn = fn[:fn.index("\nasync function ", 10)]
    assert "if (w * h > CAPTURE_MAX_TOTAL_PIXELS)" in fn
    assert "new OffscreenCanvas(w, h)" in fn
    # the preflight check must appear BEFORE the actual allocation
    assert fn.index("if (w * h > CAPTURE_MAX_TOTAL_PIXELS)") < fn.index("new OffscreenCanvas(w, h)")


# ------------------------------------------------------------------------------- gap B: same-document identity pinning
def test_page_identity_pins_path_and_query_not_just_origin() -> None:
    same_page = _run("page-identity", ["https://example.com/calculator?x=1"])
    other_path_same_origin = _run("page-identity", ["https://example.com/dashboard?x=1"])
    same_page_different_hash = _run("page-identity", ["https://example.com/calculator?x=1#results"])
    different_origin = _run("page-identity", ["https://other.example/calculator?x=1"])

    assert same_page["identity"] == same_page_different_hash["identity"], \
        "a hash-only change (in-page anchor jump) is still the same document and must not look like a navigation"
    assert same_page["identity"] != other_path_same_origin["identity"], \
        "a same-origin navigation to a different path must be detected — origin alone is not a strong enough identity for evidence"
    assert same_page["identity"] != different_origin["identity"]


def test_verify_tab_identity_pins_full_page_identity_not_origin_alone() -> None:
    # structural gate: verifyTabIdentity must compare nsPageIdentity(tab.url), not new URL(tab.url).origin, so a
    # same-origin path change is caught (gap #B) rather than silently passing as before.
    bg = (EXT / "background.js").read_text()
    fn = bg[bg.index("async function verifyTabIdentity("):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "nsPageIdentity(tab.url)" in fn
    assert "new URL(tab.url).origin" not in fn, "verifyTabIdentity must no longer compare origin alone"
    assert "expectedIdentity && identity !== expectedIdentity" in fn


def test_capture_start_pins_identity_from_the_actual_starting_url() -> None:
    bg = (EXT / "background.js").read_text()
    assert "const expectedIdentity = nsPageIdentity(tab0.url);" in bg


# ------------------------------------------------------------------------------- gap C: durable 'captured' state
def test_captured_state_persists_before_the_blob_write_not_after() -> None:
    bg = (EXT / "background.js").read_text()
    captured_idx = bg.index("rec.status = 'captured'; rec.updated_at = now();")
    put_idx = bg.index("await NSBlobStore.put(capture_id, out.blob);")
    uploading_idx = bg.index("rec.status = 'uploading'; rec.updated_at = now();\n      await putCapture(rec);\n\n      const uploadRes")
    assert captured_idx < put_idx < uploading_idx, \
        "metadata must be durable as 'captured' BEFORE the blob write, so a crash in between is an honest no-blob failure, not the old always-failed 'capturing'"


def test_captured_status_is_active_for_mutual_exclusion() -> None:
    bg = (EXT / "background.js").read_text()
    assert "const CAPTURE_ACTIVE = new Set(['capturing', 'captured', 'uploading']);" in bg
    js = (EXT / "popup.js").read_text()
    assert "const CAPTURE_ACTIVE_UI = new Set(['capturing', 'captured', 'uploading']);" in js


def test_reconcile_decision_treats_captured_same_as_uploading() -> None:
    nowMs = 1_700_000_000_000
    for status in ("captured", "uploading"):
        with_blob = _run("reconcile-decision", [{"status": status}, nowMs, True])
        assert with_blob == {"status": "upload_failed", "error": with_blob["error"]}
        assert "Retry send" in with_blob["error"]

        without_blob = _run("reconcile-decision", [{"status": status}, nowMs, False])
        assert without_blob["status"] == "failed"
        assert "not saved" in without_blob["error"]


def test_worker_init_checks_blob_existence_for_captured_too() -> None:
    bg = (EXT / "background.js").read_text()
    fn = bg[bg.index("async function reconcileCapturesOnWorkerInit()"):]
    fn = fn[:fn.index("\n}\n") + 3]
    assert "v.status === 'uploading' || v.status === 'captured'" in fn


def test_in_process_upload_failure_checks_blob_existence_for_captured_not_just_status_string() -> None:
    # if NSBlobStore.put() itself throws, the record is left at 'captured' with NO blob actually written --
    # the in-process catch block must not naively treat 'captured' as automatically recoverable (that would
    # reintroduce gap #2's bug via a different code path), it must check IndexedDB the same way the worker-init
    # reconciliation path does.
    bg = (EXT / "background.js").read_text()
    catch_block = bg[bg.index("} catch (e) {\n      // an upload failure"):]
    catch_block = catch_block[:catch_block.index("\n    }\n") + 6]
    assert "rec.status === 'captured'" in catch_block
    assert "NSBlobStore.get(capture_id)" in catch_block
    assert "recoverable = true" in catch_block  # unconditional only for 'uploading'


# ==================================================================================== repair round 4 (2026-09-16)
# Kyle's third independent re-review of the shipped 1.9.2 code confirmed all 3 gaps from repair round 3 (and its
# hardening) landed correctly, but found 3 more things before he would close the mission:
#   1. the live-Chrome acceptance pass is still completely outstanding (unchanged status — still needs Kyle).
#   2. test_the_extension_version_moved_again's hard-pinned "1.7.0" literal was a false-unrelated dismissal — it
#      breaks on EVERY version bump, including this mission's, so its failure IS connected to this mission.
#   3. the prior release-check artifact's git_sha was "nogit" (ran in a plain rsync copy, not a git checkout),
#      so it wasn't actually commit-bound despite the filename/doc claiming a specific SHA.
#   4. two small evidence-integrity gaps: nsPageIdentity ignored the URL hash entirely (a hash-routed SPA could
#      switch screens via #/route without tripping the identity check), and the pixel ceiling was checked only
#      AFTER a tile was already captured and pushed to shots, relying on stitchShots' allocation backstop rather
#      than stopping cleanly beforehand.

# ------------------------------------------------------------------------------- route-like hash identity
def test_route_like_hash_heuristic() -> None:
    assert _run("is-route-like-hash", ["#/dashboard"])["routeLike"] is True
    assert _run("is-route-like-hash", ["#!/settings"])["routeLike"] is True
    assert _run("is-route-like-hash", ["#/users/42?tab=info"])["routeLike"] is True
    assert _run("is-route-like-hash", ["#results"])["routeLike"] is False
    assert _run("is-route-like-hash", ["#section-2"])["routeLike"] is False
    assert _run("is-route-like-hash", [""])["routeLike"] is False


def test_page_identity_pins_route_like_hashes_but_not_plain_anchors() -> None:
    anchor_a = _run("page-identity", ["https://app.example/dashboard#results"])
    anchor_b = _run("page-identity", ["https://app.example/dashboard#other-section"])
    assert anchor_a["identity"] == anchor_b["identity"], \
        "a plain anchor-name hash change (table of contents, in-page jump) must stay allowed"

    route_a = _run("page-identity", ["https://app.example/#/dashboard"])
    route_b = _run("page-identity", ["https://app.example/#/settings"])
    assert route_a["identity"] != route_b["identity"], \
        "a hash-routed SPA switching screens via the hash alone must be caught — same origin+pathname+search, different rendered screen"

    hashbang_a = _run("page-identity", ["https://app.example/#!/users/1"])
    hashbang_b = _run("page-identity", ["https://app.example/#!/users/2"])
    assert hashbang_a["identity"] != hashbang_b["identity"]


# ------------------------------------------------------------------------------- pixel-ceiling preflight
def test_pixel_ceiling_is_preflighted_before_capturing_the_next_tile() -> None:
    bg = (EXT / "background.js").read_text()
    loop_start = bg.index("while (idx < grid.length) {")
    # the SAME line also appears earlier, inside fallbackVisibleCapture -- search from loop_start onward so we
    # find the tile loop's own capture call, not the fallback's.
    first_capture_call = bg.index("dataUrl = await throttledCaptureVisibleTab(tab.windowId);", loop_start)
    preflight_block = bg[loop_start:first_capture_call]
    assert "if (capturedScale != null) {" in preflight_block
    assert "const projectedPixels = viewportWidth * capturedScale * viewportHeight * capturedScale * (shots.length + 1);" in preflight_block
    assert "partialReason = 'ceiling_pixels'; break;" in preflight_block
    # the preflight must appear BEFORE the tile is actually captured, not after
    assert preflight_block.index("projectedPixels") < len(preflight_block)


def test_post_capture_pixel_check_remains_as_a_first_tile_backstop() -> None:
    # the very first tile can't be preflighted (capturedScale isn't known until a real bitmap has been decoded),
    # so the post-capture nsCheckCeilings call must still exist as a defensive backstop.
    bg = (EXT / "background.js").read_text()
    assert "const ceilingHit = nsCheckCeilings(" in bg
    assert "maxTotalPixels: CAPTURE_MAX_TOTAL_PIXELS" in bg


# ------------------------------------------------------------------------------- non-brittle version floor
def test_manifest_version_floor_matches_the_established_pattern() -> None:
    # structural gate: the fix for gap #2 must follow the SAME non-brittle floor-comparison pattern
    # tests/test_s32_course_scanner.py::test_the_extension_version_moved already established, not reintroduce
    # a new hard-pinned literal under a different name.
    src = (ROOT / "tests" / "test_s33_page_videos.py").read_text()
    fn = src[src.index("def test_the_extension_version_moved_again():"):]
    fn = fn[:fn.index("\n\n")]
    assert 'mf["version"] == "1.7.0"' not in fn, "must not still hard-pin an exact version literal"
    assert ">= (1, 7, 0)" in fn
