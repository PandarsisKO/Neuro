"""S41 — every press is acknowledged within one frame (0.63.32). (Sorts after test_s40/s39.)

Kyle: *"every single button needs instant feedback to the user that SOMETHING has happened even if it takes many
seconds for that action to truly do something. right now I click a button and the button doesnt respond for 1-5
seconds and I think something is broken."*

Measured in `web/index.html` before building anything: **228 controls carry a click handler and TWELVE of them
acknowledge the click.** The other 216 look identical whether the app heard the press or not — the same defect
this codebase has paid for at six other rungs (a failure indistinguishable from its answer: the OCR ladder in
0.63.2, the course importer in 0.63.15, the pool header in 0.63.20, the dropped citation in 0.63.22, the app's own
front door in 0.63.31, a held port in 0.63.32) arriving at the one surface a person actually touches.

So it is ONE mechanism, not 216 patched call sites: patching them by hand would miss the next button anyone adds
and could not be gated. Four properties, each asserted below because each was a decision:

* **capture:true** on the delegated listener. Without it the listener runs *after* the onclick attribute has
  already blocked the thread for its 1–5 seconds, which is precisely the interval being complained about. This is
  the single line the whole feature rests on.
* **`api()` is the clock.** Every request in the file goes through it (post/put/del all delegate), so it is the one
  place that knows when the work actually ended. A request beginning within `CLAIM_MS` of a press belongs to that
  press, and the control stays busy until every request that press started has settled.
* **no textContent is ever written.** The twelve handlers that already say "⏳ queueing…" or "Pinned ✓" own their
  labels; a class and a pseudo-element compose with them, a label write fights them. This is the property that
  lets the global mechanism and the hand-written ones coexist, so it is asserted directly.
* **a watchdog.** A spinner that never stops is the same lie as no spinner, so nothing stays busy past `STUCK_MS`.

A click that starts no request clears immediately, and that is correct rather than a miss: a tab switch really is
finished, and it still flashed. Background polling opts out (`ack: false`) because the 3-second `/tick` loop is not
something a person started — a window that pulses on its own teaches people to ignore it.

This is a text gate for the same reason `test_s5_ui_syntax.py` shells out to `node --check` and
`test_s38_verdict_labels.py` reads the shipped markup: there is no build step and no DOM here.
"""
from __future__ import annotations

import pathlib
import re

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return UI.read_text()


@pytest.fixture(scope="module")
def js(html: str) -> str:
    return "\n".join(m.group(1) for m in re.finditer(r"<script>(.*?)</script>", html, re.S))


# ------------------------------------------------------------------ the instant frame

def test_the_listener_is_capture_phase(js: str):
    """The one line the feature rests on. A bubble-phase listener runs after the onclick has already
    blocked the thread, which is the 1-5 seconds Kyle is describing."""
    m = re.search(r"document\.addEventListener\('click',(.*?)\}, true\);", js, re.S)
    assert m, "the delegated click listener must be registered with capture:true"
    body = m.group(1)
    assert "NSACK.press" in body, "the capture listener must mark the press"


def test_the_press_marks_the_control_immediately_and_not_via_a_request(js: str):
    """The class has to land without waiting for anything — that is the whole point."""
    press = re.search(r"press\(el\) \{(.*?)\n  \},", js, re.S)
    assert press, "NSACK.press not found"
    body = press.group(1)
    assert "classList.add('ns-press')" in body
    assert "await" not in body, "nothing in the press path may await"
    assert "fetch(" not in body, "the press must not depend on a request"


def test_the_press_state_is_styled(html: str):
    assert ".ns-press{" in html.replace(" ", ""), "the press class must have a visible rule"
    assert 'button[aria-busy="true"]::after{' in html.replace(" ", ""), "busy needs a visible indicator"


def test_the_busy_indicator_cannot_reflow_the_page(html: str):
    """A spinner that changes a button's size moves everything beside it, which reads as a glitch rather
    than as progress. The indicator is absolutely positioned inside the button for that reason."""
    rule = re.search(r'button\[aria-busy="true"\]::after\{(.*?)\}', html.replace("\n", " ").replace(" ", ""), re.S)
    assert rule, "no ::after rule for the busy state"
    assert "position:absolute" in rule.group(1)


# ------------------------------------------------------------------ it must not fight the twelve

def test_the_mechanism_never_writes_a_controls_label(js: str):
    """Twelve handlers already manage their own text ("⏳ queueing…", "Pinned ✓", "Added ✓"). If the global
    mechanism also wrote textContent it would overwrite them, so it is visual only. This assertion is what
    keeps the two layers compatible."""
    block = re.search(r"const NSACK = \{(.*?)\n\};", js, re.S)
    assert block, "NSACK not found"
    # Scoped to the methods that handle a CONTROL. `_bar` builds the window's own progress element and
    # legitimately sets its innerHTML — that is not a button and has no label to overwrite. The first
    # version of this assertion read the whole object and failed on exactly that, which is the difference
    # between the property I care about and the string it happens to contain.
    control_paths = "".join(
        m.group(0) for m in re.finditer(r"\n  (?:press|claim|release|done)\([^)]*\) \{.*?\n  \},", block.group(1), re.S))
    assert control_paths, "could not isolate the control-handling methods"
    for forbidden in ("textContent", "innerText", "innerHTML", "disabled ="):
        assert forbidden not in control_paths, f"the control path must not touch {forbidden}"
    # and the bar must never be handed a control
    assert "this.bar" not in control_paths, "the window bar is separate from the pressed control"


def test_the_hand_written_acknowledgements_still_exist(js: str):
    """A regression here would be invisible: the global flash would mask the loss of the specific label.
    0.60.1 built these deliberately ("every add acknowledges the click") so they are pinned."""
    for label in ("⏳ collecting…", "⏳ queueing…", "Pinned ✓"):
        assert label in js, f"the per-button acknowledgement {label!r} has gone"


# ------------------------------------------------------------------ api() is the clock

def test_api_claims_the_press_and_always_releases_it(js: str):
    m = re.search(r"async function api\(path, opts = \{\}\) \{(.*?)\n\}", js, re.S)
    assert m, "api() not found"
    body = m.group(1)
    assert "NSACK.claim()" in body, "api must attach the request to the press that started it"
    assert "finally" in body, "a failed request must clear the busy state, or it sticks for ever"
    rel = body.index("NSACK.release(owner)")
    assert rel > body.index("finally"), "release must be in the finally block"


def test_every_request_helper_goes_through_api(js: str):
    """post/put/del must delegate, or three quarters of the app's writes would never acknowledge."""
    for helper in ("const post = (p, b) => api(", "const put = (p, b) => api(", "const del = (p, b) => api("):
        assert helper in js, f"{helper!r} must delegate to api()"


def test_background_polling_is_silent(js: str):
    """A window that pulses every three seconds on its own teaches people to ignore it, which would undo
    the feature. Every /tick call opts out."""
    for m in re.finditer(r"api\(`/api/projects/\$\{state\.project\.id\}/tick`([^)]*)\)", js):
        assert "ack: false" in m.group(1), "a /tick poll must not acknowledge"
    assert js.count("ack: false") >= 3, "all three tick call sites must be silenced"
    assert "opts.ack === false" in js, "api() must honour the opt-out"


# ------------------------------------------------------------------ nothing may stay stuck

def test_a_watchdog_clears_a_stuck_control(js: str):
    """A spinner that never stops is the same lie as no spinner at all."""
    assert re.search(r"STUCK_MS:\s*(\d+)", js), "no watchdog timeout declared"
    stuck = int(re.search(r"STUCK_MS:\s*(\d+)", js).group(1))
    assert stuck >= 30000, "the watchdog must not fire during real work (measured slowest endpoint ~19 s p90)"
    assert "setTimeout(() => this.done(), this.STUCK_MS)" in js


def test_the_claim_window_is_long_enough_for_an_async_handler(js: str):
    """An async handler may await something before its first request. A window shorter than that silently
    produces no busy state — which is how the first version of this broke itself with a double-rAF."""
    m = re.search(r"CLAIM_MS:\s*(\d+)", js)
    assert m and int(m.group(1)) >= 1000


def test_a_busy_control_cannot_be_clicked_twice(html: str, js: str):
    """0.62.7 had to make a second Settle-all click impossible server-side. Doing it in the UI too is free."""
    assert "pointer-events:none" in re.search(r'button\[aria-busy="true"\]\{(.*?)\}', html, re.S).group(1)
    assert "el.getAttribute('aria-busy') === 'true'" in js, "the listener must ignore an already-busy control"


def test_opted_out_controls_are_possible(js: str):
    """Escape hatch for any control this turns out to be wrong for — without it the only fix would be to
    rip the mechanism out."""
    assert "dataset.noack" in js


def test_reduced_motion_is_honoured(html: str):
    assert "prefers-reduced-motion" in html


# ------------------------------------------------------------------ the measurement that motivated it

def test_most_controls_still_rely_on_the_global_mechanism(html: str):
    """Recorded as a number rather than a claim: this is why it is one mechanism and not N patches. If a
    future change makes most buttons hand-rolled, this gate should be revisited rather than kept."""
    with_onclick = len(re.findall(r"<button[^>]*onclick=", html))
    hand_rolled = html.count("disabled = true")
    assert with_onclick > 150, f"expected the measured population (228), found {with_onclick}"
    assert hand_rolled < 30, f"{hand_rolled} hand-rolled acknowledgements — is the global one still the right shape?"
