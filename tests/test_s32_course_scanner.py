"""S32 — the course scanner, as a contract (extension 1.7.0, mission CS). (Sorts after test_s31.)

History this file carries: 0.63.15 / extension 1.6.0 fixed three faults Kyle hit on SMB Market — navigation
matched as lessons, false positives silencing the video on screen, and "are you logged in?" blamed for every
empty result — and concluded that an app-rendered course "cannot be crawled at all". The first three stay gated
here. The conclusion was reopened on 2026-09-15 (docs/COURSE-SCANNER-2026-09-15.md): measured in Kyle's own
browser, the course's lesson controls can be operated and every lesson renders a stable player identity. The
scanner is now a strategy pipeline — linked pages → interactive SPA traversal → rendered-content inspection —
and every lesson it discovers ends in an explicit outcome.

How this is tested: `tests/js/run.mjs` runs the SHIPPED `extension/scan-lib.js` inside jsdom against HTML
fixtures under `tests/fixtures/courses/` that implement real course behaviours (an SMB-shaped SPA, an accordion,
a lazy player, a broken lesson, danger buttons among the lessons). jsdom proves classification, traversal,
settling, outcomes, dedupe, partial failure and the safety rules. It does NOT prove React's event semantics,
Chrome's resource timing, the MV3 worker lifecycle or SMB Market itself — those are the live gates in the design
note. `node` missing is a fact about the machine (skip, the UI-syntax policy). jsdom missing is a broken verify
environment and FAILS: `npm ci --prefix tests/js` installs the pinned version.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FIX = ROOT / "tests" / "fixtures" / "courses"
RUN = ROOT / "tests" / "js" / "run.mjs"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("no JavaScript engine on this machine — the scanner gate needs node")
    return exe


def _run_js(js: str) -> str:
    out = subprocess.run([_node(), "-e", js], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:600]
    return out.stdout.strip()


def _lib_js(expr: str) -> str:
    """Evaluate `expr` with the shipped library loaded (no DOM needed for the regex-level gates)."""
    lib = json.dumps(str(EXT / "scan-lib.js"))
    return _run_js(f"globalThis.document=undefined; eval(require('fs').readFileSync({lib},'utf8')); console.log(JSON.stringify({expr}));")


def scan(fixture: str, *args: str) -> dict:
    """Run the shipped pipeline against a fixture; jsdom absent is a FAILURE (exit 3), not a skip."""
    out = subprocess.run([_node(), str(RUN), str(FIX / fixture), *args], capture_output=True, text=True, timeout=120)
    assert out.returncode != 3, "jsdom is not installed in tests/js — run `npm ci --prefix tests/js`; the scanner gate cannot be skipped"
    assert out.returncode == 0, out.stderr[:800]
    return json.loads(out.stdout)


def outcomes(r: dict) -> list[tuple[str, str]]:
    return [(l["title"], l["outcome"]) for l in r["summary"]["lessons"]]


# ------------------------------------------------------------------ the files parse, the version moved

def test_every_extension_script_parses():
    for f in ("scan-lib.js", "scanner.js", "popup.js", "background.js"):
        out = subprocess.run([_node(), "--check", str(EXT / f)], capture_output=True, text=True)
        assert out.returncode == 0, f"{f}: {out.stderr[:300]}"


def test_the_extension_version_moved():
    mf = json.loads((EXT / "manifest.json").read_text())
    assert tuple(int(x) for x in mf["version"].split(".")) >= (1, 7, 0)
    assert set(mf["permissions"]) == {"activeTab", "scripting", "cookies", "storage", "alarms", "tabs"}, "no new permissions were needed"


# ------------------------------------------------------------------ 1.6.0's three faults stay closed

def test_navigation_is_never_a_lesson():
    """His three real candidates, by their real paths."""
    hits = _lib_js("['/partners/', '/dashboard/educational-hub/classroom/calendar/', '/pricing', '/community/posts/99']"
                   ".map(p => !NSScan._re.BAD_LINK.test(p) && NSScan._re.GOOD_LINK.test(p))")
    assert json.loads(hits) == [False, False, False, False]


def test_a_link_under_the_course_path_is_not_a_lesson_by_location():
    assert json.loads(_lib_js("!NSScan._re.BAD_LINK.test('/dashboard/educational-hub/classroom/') && NSScan._re.GOOD_LINK.test('/dashboard/educational-hub/classroom/')")) is False


def test_real_lesson_addresses_still_match():
    """The tightening must not cost recall on the courses the importer is FOR (Kajabi, Teachable, Skool shapes)."""
    hits = _lib_js("['/courses/acquisition-101/lesson-3', '/lessons/12', '/p/module-2-part-1', '/watch/abc123', '/day-4-outreach', '/chapter-7', '/units/3/steps/2']"
                   ".map(p => !NSScan._re.BAD_LINK.test(p) && NSScan._re.GOOD_LINK.test(p))")
    assert json.loads(hits) == [True] * 7


def test_the_page_you_are_looking_at_always_counts():
    """Fixture 8: a lesson page with its Loom embed and the site's navigation around it. No lesson list, no links
    that look like lessons — the video on screen is the result, and the navigation is not."""
    r = scan("courses/thispage.html")
    assert r["summary"]["strategy"] == "none"
    assert outcomes(r) == [("Lesson 4 · Pricing", "video_found")]
    assert r["summary"]["lessons"][0]["media"][0]["provider"] == "loom"
    assert r["clicks"] == [], "nothing on a page with no course structure is ever clicked"


def test_the_popup_never_blames_the_login_for_an_empty_result():
    src = (EXT / "popup.js").read_text()
    assert "are you on the course home page, and logged in?" not in src
    scan_ui = "\n".join(ln for ln in src.split("mission CS")[1].splitlines() if not ln.lstrip().startswith("//"))
    strings = re.findall(r"[`'\"]([^`'\"]{6,})[`'\"]", scan_ui)         # what a person can be shown, not comments or code
    assert not any("logged in" in t.lower() for t in strings)           # the Reddit path keeps its own, true, login hint
    assert "No lessons found on this page" in src                       # nothing seen, named
    assert "no video in any of them" in src                              # pages seen, no players, named
    assert "could not open any of them" in src                           # controls seen, activation failed, named


# ------------------------------------------------------------------ Strategy A: linked multi-page course

def test_linked_course_fetches_each_lesson_page_and_classifies_every_one():
    r = scan("linked/index.html", "--url", "https://course.test/courses/demo/")
    s = r["summary"]
    assert s["strategy"] == "linked"
    assert outcomes(r) == [("Welcome", "video_found"), ("Setting up", "video_found"), ("Text only lesson", "no_video"), ("Members lesson", "blocked")]
    assert [l["module"] for l in s["lessons"]] == ["Module 1", "Module 1", "Module 2", "Module 2"]
    assert s["lessons"][1]["media"] == [{"provider": "vimeo", "id": "123456", "url": "https://vimeo.com/123456", "ephemeral": False, "via": "data"}], "one identity, whichever of data-attribute and inline JSON named it"
    assert "/lessons/99.html" not in " ".join(r["fetched"]), "a link inside a sidebar landmark is site chrome, not a lesson"
    assert s["lessons"][3]["detail"] == "http 403"


# ------------------------------------------------------------------ Strategy B: interactive SPA courses

def test_spa_course_at_one_url_is_traversed_module_by_module():
    """Fixture 2 is SMB Market's shape without SMB Market's classes: module cards → lesson view with breadcrumb,
    lesson rows as buttons, one address throughout, quiz and purchase buttons on the same view."""
    r = scan("courses/spa.html")
    s = r["summary"]
    assert s["strategy"] == "interactive" and s["status"] == "done" and s["expected"] == 5
    assert outcomes(r) == [("Welcome aboard", "video_found"), ("Your first deal", "video_found"),
                           ("SDE explained", "video_found"), ("Multiples", "video_found"), ("Working capital", "video_found")]
    assert [l["module"] for l in s["lessons"]] == ["Getting Started"] * 2 + ["Deal Economics"] * 3
    ids = [l["media"][0]["provider"] + ":" + l["media"][0]["id"] for l in s["lessons"]]
    assert len(set(ids)) == 5 and ids[-1] == "vimeo:987654"
    assert s["diagnosis"]["back_control"] is True and s["diagnosis"]["expanded_modules"] == 2
    # the lesson that opens with a module is inspected, not re-clicked; the breadcrumb is used to go back
    assert r["clicks"] == ["Getting Started2 lessons", "2. Your first deal7m", "Learning", "Deal Economics3 lessons", "2. Multiples", "3. Working capital12m", "Learning"]
    for danger in ("Submit quiz", "Purchase", "Complete", "Prev", "Start course", "A. First answer"):
        assert not any(c.startswith(danger) for c in r["clicks"]), danger


def test_collapsed_modules_are_expanded_in_place_and_rows_attributed_to_their_module():
    r = scan("courses/collapsed.html")
    s = r["summary"]
    assert s["status"] == "done" and s["expected"] == 5
    assert [(l["module"], l["title"], l["outcome"]) for l in s["lessons"]] == [
        ("Module A", "Intro", "video_found"), ("Module A", "Setup", "video_found"),
        ("Module B", "Deep dive", "video_found"), ("Module B", "Wrap up", "video_found"), ("Module B", "Bonus", "video_found")]
    assert s["diagnosis"]["back_control"] is False, "an accordion keeps its module cards: no way-back control is needed or used"


def test_a_player_that_arrives_late_is_still_found():
    r = scan("courses/delayed.html")
    assert outcomes(r) == [("Slow one", "video_found"), ("Slow two", "video_found")]


def test_a_lesson_without_a_video_and_a_locked_lesson_are_named_as_such():
    r = scan("courses/novideo.html")
    assert outcomes(r) == [("Video lesson", "video_found"), ("Reading", "no_video"), ("Locked bonus", "blocked")]
    # the page's own script lists lesson 1's Loom URL: a regex over the source would have credited it to every lesson
    assert all(len(l["media"]) == 0 for l in r["summary"]["lessons"][1:])


def test_the_same_video_behind_two_lessons_is_one_video_and_two_memberships():
    r = scan("courses/dup.html")
    s = r["summary"]
    assert outcomes(r) == [("Part one", "video_found"), ("Part two", "video_found"), ("Part one again", "video_found")]
    assert s["duplicates"] == {"loom:ffff1111ffff1111ffff1111ffff1111": [0, 2]}
    assert s["lessons"][0]["video_urls"] == s["lessons"][2]["video_urls"], "each lesson keeps its own reference; the import dedupes the acquisition"


def test_one_broken_lesson_does_not_cost_the_others():
    r = scan("courses/partial.html")
    s = r["summary"]
    assert outcomes(r) == [("Fine", "video_found"), ("Broken button", "scan_failed"), ("Also fine", "video_found"), ("Vanishes", "scan_failed")]
    assert "did not change" in s["lessons"][1]["detail"] and "vanished" in s["lessons"][3]["detail"]
    assert s["diagnosis"]["unchanged"] == 1
    assert r["clicks"].count("2. Broken button") == 2, "one plain click, one pointer-event retry, then an honest outcome — never a loop"


def test_cancellation_stops_at_a_lesson_boundary_and_keeps_what_was_read():
    r = scan("courses/spa.html", "--cancel-after", "2")
    s = r["summary"]
    assert s["status"] == "cancelled" and len(s["lessons"]) == 2 and s["diagnosis"]["cancelled"] is True


# ------------------------------------------------------------------ safety: positive identification first, denylist second

def test_dangerous_controls_among_the_lessons_are_never_activated():
    r = scan("courses/safety.html")
    assert r["clicks"] == ["1. Welcome 3m", "4. Closing thoughts 6m"]
    assert outcomes(r) == [("Welcome", "video_found"), ("Closing thoughts", "video_found")]
    danger = ["Complete lesson", "Purchase", "Take quiz", "Download certificate", "Save", "Next", "Logout", "Submit quiz", "Mark complete", "Start course", "Pay now", "Delete my account"]
    assert not any(any(c.startswith(d) or c.endswith(d) for d in danger) for c in r["clicks"])
    assert not any("DANGER" in (l.get("heading") or "") for l in r["summary"]["lessons"])


def test_control_identification_is_positive_not_a_denylist():
    """A lesson row is a lesson because of its shape among siblings; a lone numbered button is nothing."""
    lesson = _lib_js("['1. How to Use SMBMarket 6m', '12) Closing the deal', '3. Take quiz', 'Complete & next', 'A. First answer', 'Getting Started 6 lessons']"
                     ".map(t => NSScan._re.LESSON_TEXT.test(t))")
    assert json.loads(lesson) == [True, True, True, False, False, False]
    module = _lib_js("['Getting Started 6 lessons', 'Module B 3 lessons', '1. Intro', 'View all lessons']"
                     ".map(t => NSScan._re.MODULE_TEXT.test(t))")
    assert json.loads(module) == [True, True, False, False]


def test_no_platform_selectors_in_the_generic_scanner():
    """SMB Market is the acceptance case, not the design: nothing in the generic scanner names it or its CSS."""
    for f in ("scan-lib.js", "scanner.js"):
        src = (EXT / f).read_text()
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))
        for token in ("smbmarket", "w-full", "group/item", "text-left", "educational-hub"):
            assert token not in code, f"{f}: {token}"
    assert "adapters = []" in (EXT / "scan-lib.js").read_text(), "the adapter seam exists and is empty until a platform earns one"


# ------------------------------------------------------------------ media identity

def test_media_identity_is_stable_for_players_and_ephemeral_for_delivery_urls():
    rows = json.loads(_lib_js("[ 'https://www.loom.com/embed/c867b5414d1246c0aa948cce46bead6a?hide_owner=true&sid=1',"
                              " 'https://player.vimeo.com/video/12345?h=zz9&badge=0', 'https://youtube-nocookie.com/embed/abc123def45?rel=0',"
                              " 'https://fast.wistia.net/embed/iframe/abcde12345?videoFoam=true', 'https://cdn.example.com/hls/lesson.m3u8?token=SIGNED&exp=1',"
                              " 'https://cdn.example.com/app.js' ].map(u => NSScan.mediaIdentity(u))"))
    assert rows[0] == {"provider": "loom", "id": "c867b5414d1246c0aa948cce46bead6a", "url": "https://www.loom.com/share/c867b5414d1246c0aa948cce46bead6a", "ephemeral": False}
    assert rows[1]["url"] == "https://vimeo.com/12345/zz9" and rows[2]["url"] == "https://www.youtube.com/watch?v=abc123def45"
    assert rows[3] == {"provider": "wistia", "id": "abcde12345", "url": "https://fast.wistia.net/embed/iframe/abcde12345", "ephemeral": False}
    assert rows[4]["ephemeral"] is True and rows[4]["id"] == "cdn.example.com/hls/lesson.m3u8", "a signed delivery URL is evidence, never an identity"
    assert rows[5] is None


# ------------------------------------------------------------------ durable scan state (source-level gates; the lifecycle itself is a live gate)

def test_scan_state_is_per_tab_and_every_message_is_nonce_guarded():
    bg = (EXT / "background.js").read_text()
    assert "`scan:${tabId}`" in bg and "chrome.storage.local.scan" not in bg, "one record per tab, never a singleton"
    assert "rec.scan_id !== m.scan_id" in bg, "a superseded runner's messages are ignored"
    assert "A scan is already running in this tab" in bg, "a second start on a busy tab is refused"
    assert "globalThis.__nsScanActive" in bg and "__nsScanActive" in (EXT / "scanner.js").read_text(), "page-runner idempotency marker"
    assert "info.status === 'loading'" in bg and "scan-ping" in bg, "liveness is asked of the runner, not inferred from a URL change"
    assert "browser_restarted" in bg and "tab_closed" in bg and "origin_changed" in bg
    sc = (EXT / "scanner.js").read_text()
    assert "scan_id, ...payload" in sc, "every event from the page carries its scan_id"


def test_the_popup_speaks_in_lessons_and_videos_not_mechanics():
    html = (EXT / "popup.html").read_text()
    js = "\n".join(ln for ln in (EXT / "popup.js").read_text().split("mission CS")[1].splitlines() if not ln.lstrip().startswith("//"))
    # quote-type aware: a naive [`'"]...[`'"] scan pairs a backtick open with an unrelated
    # single-quote close and swallows real code (e.g. the `dom` loop variable) into the
    # "string" it thinks it found. Match same open/close quote char instead.
    str_pat = re.compile(r"([`'\"])((?:\\.|(?!\1)[^\\\n])*)\1")
    user_strings = [m.group(2) for m in str_pat.finditer(js) if len(m.group(2)) >= 12]
    user_strings = [t for t in user_strings if "api/" not in t and not t.strip().startswith("${")]
    for word in ("DOM", "selector", "strateg", "MutationObserver", "cookie jar", "scrape", "iframe"):
        assert not any(word.lower() in t.lower() for t in user_strings), (word, [t for t in user_strings if word.lower() in t.lower()])
    for phrase in ("Finding lessons", "found so far", "need", "could not be read", "Stopped early"):
        assert phrase in js, phrase
    assert "Scan this course" in html and 'id="cancelScan"' in html
