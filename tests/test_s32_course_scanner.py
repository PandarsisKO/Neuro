"""S32 — the course importer blamed the login (0.63.15 / extension 1.6.0). (Sorts after test_s31.)

Kyle: *"the course importer doesnt seem to be working properly ... errors include: no videos found - are you sure
you are logged in?"* He was logged in, and on the course page. Measured in his own browser against
`smbmarket.com/dashboard/educational-hub/classroom/`, three separate faults:

1. **The lesson pattern matched the site's own navigation.** `/partners/` matched because the pattern contained the
   bare substring `part`; the two calendar links matched because it contained `classroom` and they sit UNDER the
   course path — "this link is inside the course" was being read as "this link is a lesson". All three candidates
   it found were navigation.
2. **Those false positives silenced the real result.** The on-page fallback was `if (!lessons.length &&
   here.length)`, so videos on the page the user is looking at were used only when nothing else was found at all.
   Two junk rows were enough to discard them.
3. **That course cannot be crawled at all.** Measured: the six course paths are
   `<button class="group block w-full text-left">`, not links; every lesson renders at the same URL; the served
   HTML has zero `<video>` tags, zero iframes and no player URL. So the right answer is not a login hint, it is
   *"open a lesson and use Send this page"*.

These assertions run the real `extension/scanner.js` predicates under `node`, and skip where no JS engine exists —
the same policy as the UI syntax gate, because a missing `node` is a fact about the machine (0.58.4).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "extension"
SCANNER = EXT / "scanner.js"


def _node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("no JavaScript engine on this machine — the scanner gate needs node")
    return exe


def _literal(name: str) -> str:
    """The regex literal as it is written in scanner.js — the test must read the shipped source, never a copy."""
    src = SCANNER.read_text()
    m = re.search(rf"const {name} = (/.+/i);", src)
    assert m, f"{name} not found in scanner.js — the gate must follow the source"
    return m.group(1)


def _run(js: str) -> str:
    out = subprocess.run([_node(), "-e", js], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[:400]
    return out.stdout.strip()


def test_the_scanner_and_popup_parse():
    for f in ("scanner.js", "popup.js", "background.js"):
        out = subprocess.run([_node(), "--check", str(EXT / f)], capture_output=True, text=True)
        assert out.returncode == 0, f"{f}: {out.stderr[:300]}"


def test_navigation_is_never_a_lesson():
    """His three real candidates, by their real paths."""
    js = f"""
    const good = {_literal('good')}, bad = {_literal('bad')};
    const hit = p => !bad.test(p) && good.test(p);
    console.log(JSON.stringify(['/partners/', '/dashboard/educational-hub/classroom/calendar/',
                                '/pricing', '/community/posts/99'].map(hit)));
    """
    assert json.loads(_run(js)) == [False, False, False, False]


def test_a_link_under_the_course_path_is_not_a_lesson_by_location():
    js = f"""
    const good = {_literal('good')}, bad = {_literal('bad')};
    console.log(JSON.stringify(!bad.test('/dashboard/educational-hub/classroom/')
                               && good.test('/dashboard/educational-hub/classroom/')));
    """
    assert json.loads(_run(js)) is False


def test_real_lesson_addresses_still_match():
    """The tightening must not cost recall on the courses the importer is FOR (Kajabi, Teachable, Skool shapes)."""
    js = f"""
    const good = {_literal('good')}, bad = {_literal('bad')};
    const hit = p => !bad.test(p) && good.test(p);
    console.log(JSON.stringify(['/courses/acquisition-101/lesson-3', '/lessons/12', '/p/module-2-part-1',
                                '/watch/abc123', '/day-4-outreach', '/chapter-7', '/units/3/steps/2'].map(hit)));
    """
    assert json.loads(_run(js)) == [True] * 7


def test_the_page_you_are_looking_at_always_counts():
    """Fault 2, as a property of the source: the fallback must not be conditional on finding nothing else."""
    # Comment lines are excluded on purpose: the header of scanner.js QUOTES the old condition to record what was
    # wrong with it, and a gate that cannot tell prose from code would forbid explaining the bug.
    code = "\n".join(ln for ln in SCANNER.read_text().splitlines() if not ln.lstrip().startswith("//"))
    assert "if (!lessons.length && here.length)" not in code
    assert "if (here.length) {" in code and "lessons.unshift(" in code


def test_navigation_landmarks_are_excluded_structurally():
    src = SCANNER.read_text()
    assert "[role=navigation]" in src and "a.closest(CHROME)" in src


def test_the_scanner_reports_what_it_saw():
    """A diagnosis the popup can render instead of one guessed cause."""
    src = SCANNER.read_text()
    for key in ("candidates:", "on_page_videos:", "clickable_lessonish:", "app_rendered"):
        assert key in src, key


def test_the_popup_no_longer_blames_the_login_for_every_empty_result():
    src = (EXT / "popup.js").read_text()
    assert "are you on the course home page, and logged in?" not in src
    assert "keeps one address for every lesson" in src          # the app-rendered case, named
    assert "No lesson links on this page" in src                 # nothing found, named
    assert "no video in any of them" in src                      # found pages, no players, named


def test_the_extension_version_moved():
    """The scanner fix shipped in 1.6.0; a later release may raise this again, so the floor is what is asserted."""
    mf = json.loads((EXT / "manifest.json").read_text())
    assert tuple(int(x) for x in mf["version"].split(".")) >= (1, 6, 0)
