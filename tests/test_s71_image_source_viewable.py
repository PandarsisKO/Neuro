"""S71 (case 7 side-finding, 2026-09-18): /api/sources/{id}/image has existed server-side since 0.63.0, but
nothing in the frontend ever linked to it -- an image-platform source (including every Send Screenshot capture)
had no way to actually be VIEWED as a picture anywhere in the app; the drawer's "Transcript" button and the
source row's own button only ever showed the OCR'd text. Found live while testing case 7 (drawer provenance) --
Kyle could see a source's capture metadata but not the screenshot itself. Fixed in two places: sourceDrawer's
provenance card (research.js) gets a clickable thumbnail, and viewTranscript (sources.js) shows the actual image
for platform === 'image' sources instead of falling through to the plain-text transcript view.

This is a string-boundary test on the shipped frontend source, same style as test_s54/test_s64's background.js
checks -- it proves the markup exists and is wired to the real endpoint, not that a browser renders it correctly
(that stays a live-app gate, which is how this was actually found and verified this session).

Run: pytest -q tests/test_s71_image_source_viewable.py
"""
from __future__ import annotations

from pathlib import Path

RESEARCH_JS = Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "research.js"
SOURCES_JS = Path(__file__).resolve().parents[1] / "neurosearch" / "web" / "js" / "sources.js"
API_PY = Path(__file__).resolve().parents[1] / "neurosearch" / "api.py"


def test_the_image_serving_endpoint_still_exists_server_side():
    src = API_PY.read_text()
    assert '@app.get("/api/sources/{source_id}/image"' in src, \
        "the endpoint both frontend fixes depend on must still exist -- if this moved, both UI fixes are now broken silently"


def test_the_drawer_provenance_card_links_to_the_actual_image():
    src = RESEARCH_JS.read_text()
    assert "capturedThumb" in src, "the drawer's capture card lost its image thumbnail"
    assert "s.platform === 'image'" in src and "/api/sources/${sid}/image" in src, \
        "the thumbnail must be gated on platform === 'image' and point at the real per-source image endpoint"
    # the thumbnail must actually be included in what gets rendered, not just computed and discarded
    assert "${capturedThumb}" in src, "capturedThumb was computed but never actually inserted into capturedLine's markup"


def test_the_drawer_capture_timestamp_names_its_timezone():
    src = RESEARCH_JS.read_text()
    assert "const capturedAt = cap ? new Intl.DateTimeFormat" in src, \
        "capture provenance must format its stored timestamp through one explicit display seam"
    assert "timeZoneName: 'short'" in src, \
        "the drawer must name the timezone instead of showing an ambiguous browser-local date/time"
    assert "${esc(capturedAt)}" in src, \
        "the capture card must render the timezone-labelled timestamp, not a discarded formatter result"


def test_view_transcript_shows_the_picture_for_image_sources_not_just_ocr_text():
    src = SOURCES_JS.read_text()
    # the image branch must come BEFORE the generic transcript fallback, and must return, or an image source
    # would render the image and then immediately overwrite it with the plain-text view
    img_branch = src.find("s.platform === 'image'")
    generic_fallback = src.find("download .txt", img_branch if img_branch != -1 else 0)
    assert img_branch != -1, "viewTranscript lost its image-platform branch"
    assert generic_fallback != -1 and generic_fallback > img_branch, \
        "the image branch must run before the generic text-transcript fallback"
    # between the branch and the next function, there must be an actual <img> pointing at the real endpoint,
    # and a `return` so the generic fallback never also runs for an image source
    segment = src[img_branch:generic_fallback]
    assert "<img src=\"/api/sources/${id}/image\"" in segment, \
        "the image branch must render an <img> tag pointing at the real per-source image endpoint"
    assert "return;" in segment, \
        "the image branch must return early -- otherwise it falls through and the plain-text view overwrites it"
