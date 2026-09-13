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
def js() -> str:
    return "\n".join(p.read_text() for p in sorted(UI.parent.joinpath("js").glob("*.js")))


@pytest.fixture(scope="module")
def css() -> str:
    return (UI.parent / "styles.css").read_text()


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


def test_the_press_state_is_styled(css: str):
    assert ".ns-press{" in css.replace(" ", ""), "the press class must have a visible rule"
    assert 'button[aria-busy="true"]::after{' in css.replace(" ", ""), "busy needs a visible indicator"


def test_the_busy_indicator_cannot_reflow_the_page(css: str):
    """A spinner that changes a button's size moves everything beside it, which reads as a glitch rather
    than as progress. The indicator is absolutely positioned inside the button for that reason."""
    rule = re.search(r'button\[aria-busy="true"\]::after\{(.*?)\}', css.replace("\n", " ").replace(" ", ""), re.S)
    assert rule, "no ::after rule for the busy state"
    assert "position:absolute" in rule.group(1)


# ------------------------------------------------------------------ it must not fight the twelve

def test_the_mechanism_never_writes_a_controls_label(js: str):
    """Twelve handlers already manage their own text ("⏳ queueing…", "Pinned ✓", "Added ✓"). If the global
    mechanism also wrote textContent it would overwrite them, so it is visual only. This assertion is what
    keeps the two layers compatible."""
    block = re.search(r"globalThis\.NSACK = \{(.*?)\n\};", js, re.S)
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
    for helper in ("globalThis.post = (p, b) => api(", "globalThis.put = (p, b) => api(", "globalThis.del = (p, b) => api("):
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


def test_the_busy_state_is_unmistakable_not_subtle(css: str):
    """Kyle, on the first version: "the delay was so bad I thought the app was frozen ... I need it to be
    visually obvious that the button was clicked, maybe turned grey or something while it waits."

    The animated hairline was too quiet on its own. A busy control now greys out — the strongest visual
    vocabulary a button has and the one people already read as "not right now" — with the hairline kept
    vivid on top so it says *working* rather than *broken*. The !important flags are load-bearing: a
    button here may carry .primary (accent background), .ghost (transparent) or .small, and with no build
    step a busy state that loses the cascade on SOME buttons is worse than none, because it is
    inconsistent."""
    rule = re.search(r'button\[aria-busy="true"\]\{(.*?)\}', css, re.S).group(1).replace(" ", "").replace("\n", "")
    for prop in ("background:var(--panel2)!important", "color:var(--muted)!important"):
        assert prop in rule, f"the busy state must {prop.split(':')[0]} the control unmistakably"
    assert "cursor:progress" in rule
    # and the progress indicator must NOT be greyed with it, or busy reads as merely disabled
    after = re.search(r'button\[aria-busy="true"\]::after\{(.*?)\}', css.replace("\n", " "), re.S).group(1)
    assert "var(--accent" in after, "the hairline must stay vivid so busy reads as working, not broken"


def test_a_busy_control_cannot_be_clicked_twice(css: str, js: str):
    """0.62.7 had to make a second Settle-all click impossible server-side. Doing it in the UI too is free."""
    assert "pointer-events:none" in re.search(r'button\[aria-busy="true"\]\{(.*?)\}', css, re.S).group(1)
    assert "el.getAttribute('aria-busy') === 'true'" in js, "the listener must ignore an already-busy control"


def test_opted_out_controls_are_possible(js: str):
    """Escape hatch for any control this turns out to be wrong for — without it the only fix would be to
    rip the mechanism out."""
    assert "dataset.noack" in js


def test_reduced_motion_is_honoured(css: str):
    assert "prefers-reduced-motion" in css


# ------------------------------------------------------------------ the measurement that motivated it

def test_most_controls_still_rely_on_the_global_mechanism(html: str, js: str):
    """Recorded as a number rather than a claim: this is why it is one mechanism and not N patches. If a
    future change makes most buttons hand-rolled, this gate should be revisited rather than kept."""
    with_onclick = len(re.findall(r"<button[^>]*onclick=", html)) + len(re.findall(r"<button[^>]*onclick=", js))
    hand_rolled = html.count("disabled = true") + js.count("disabled = true")
    assert with_onclick > 150, f"expected the measured population (228), found {with_onclick}"
    assert hand_rolled < 30, f"{hand_rolled} hand-rolled acknowledgements — is the global one still the right shape?"


# ------------------------------------------------------------------ what his report actually found

def test_a_press_owns_its_whole_request_chain_not_just_its_first_request(js: str):
    """Kyle, after 0.63.32 shipped: "its still a big problem on the findings page 'approve all' doesnt
    appear to have clicked when i click it."

    His click had worked — `approved` went 16,378 → 16,437 and `suggested` went to zero, all 59 of them.
    The defect was entirely in the telling, and half of it was mine from an hour earlier: `bulkNotes`
    posts 59 ids in ~200 ms and then calls `loadNotes()`, which re-fetches the project, the staleness map
    and a page of findings — seconds of work. Releasing the busy state when the FIRST request settled
    left that whole tail silent, which is the exact complaint the feature exists to answer.

    So a press keeps claiming while its chain is alive, and the gap between two requests in one handler
    is bridged rather than flickering."""
    assert re.search(r"SETTLE_MS:\s*(\d+)", js), "no settle window — the state will flicker between requests"
    settle = int(re.search(r"SETTLE_MS:\s*(\d+)", js).group(1))
    assert 150 <= settle <= 1500, f"SETTLE_MS={settle} is outside the useful range"
    claim = re.search(r"claim\(\) \{(.*?)\n  \},", js, re.S).group(1)
    assert "this.n > 0 ||" in claim, "an in-flight chain must keep claiming past CLAIM_MS"
    rel = re.search(r"release\(el\) \{(.*?)\n  \},", js, re.S).group(1)
    assert "this._settle = setTimeout" in rel, "release must debounce, not clear instantly"
    done = re.search(r"done\(\) \{(.*?)\n  \},", js, re.S).group(1)
    assert "clearTimeout(this._settle)" in done, "a stale settle timer must not clear a newer press"


def test_a_bulk_verdict_says_what_it_did(js: str):
    """The pressed button is destroyed by the re-render that follows — there is nothing left to approve,
    so the block redraws without it. A transient control state therefore cannot be the confirmation for
    this class of action; it needs a durable message. 0.60.1 set that rule and this call site never got
    it, which is why 59 successful approvals read as a broken button."""
    m = re.search(r"async function bulkNotes\(ids, status\) \{(.*?)\n\}", js, re.S)
    assert m, "bulkNotes not found"
    body = m.group(1)
    assert "toast(" in body, "a bulk verdict must report what it did"
    # Compare CODE, not prose: the first version of this assertion matched `loadNotes()` inside the
    # explanatory comment above the call and reported a false failure — the same mistake test_s38's
    # first scanner made when its regex walked into a `${...}` template hole.
    code = "\n".join(ln for ln in body.split("\n") if not ln.strip().startswith("//"))
    assert code.index("toast(`✓") < code.index("loadNotes()"), "report before the reload that destroys the button"
    assert "ids.length" in body, "the message must name how many, not just that something happened"
    for sibling in ("async function bulkReserve", "async function reserveVerdict"):
        assert sibling in js, f"{sibling} is the same shape and must keep its own confirmation"


def test_no_two_top_level_functions_share_a_name(js: str):
    """Found while fixing the above: `promoteReserve` was declared TWICE at top level. The later
    declaration wins, so the per-item verdict buttons on the Sources reserve box — the ✓ Approve /
    📌 To review / ✕ Dismiss that 0.63.27 went to the trouble of labelling — were calling the BULK
    function with a bare note id. `!ids.length` on a number is true, so every click returned
    toast('nothing ticked') and the `status` argument was discarded. Three labelled verdict buttons that
    could not record a verdict, and nothing anywhere said so.

    This file is ~300 KB with no build step and no linter, so a shadowed name is invisible — `node
    --check` (test_s5) parses it happily, because it is valid JavaScript. It is only wrong. Hence a
    gate: the same reason test_s38 reads the shipped markup for verdict labels."""
    names: dict[str, int] = {}
    for m in re.finditer(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", js, re.M):
        names[m.group(1)] = names.get(m.group(1), 0) + 1
    dupes = {n: c for n, c in names.items() if c > 1}
    assert not dupes, f"top-level functions declared more than once (the later silently wins): {dupes}"


def test_the_reserve_verdict_buttons_pass_a_status_that_is_actually_used(js: str):
    """The collision above discarded `status` entirely, so approve/dismiss/to-review were the same
    no-op. Each call site must name its own verdict and the function must consume it."""
    m = re.search(r"async function reserveVerdict\(id, status, sid\) \{(.*?)\n", js, re.S)
    assert m, "reserveVerdict not found"
    assert "{ status }" in m.group(1), "the status argument must reach the request"
    for verdict in ("'approved'", "'suggested'", "'dismissed'"):
        assert f"reserveVerdict(${{n.id}}, {verdict}" in js, f"no reserve call site for {verdict}"


# ------------------------------------------------------------------ it has to fit on the screen

def test_no_group_of_buttons_is_trapped_in_white_space_nowrap(js: str):
    """Kyle, with a screenshot of the Findings page: "elements not fitting in their window."

    The staleness triage row put four buttons carrying both currencies — "Rebuild · $0 · about 4 h 17 min
    on Claude Code", "Rebuild in the background · $9.50", "Rebuild now · $30.55 on the API" — inside a
    `white-space:nowrap` box. Buttons in a nowrap box can never wrap, so on his 2000 px window the last
    one was cut off at the right edge: the most expensive button in the app, half visible and unreadable.

    What makes it an oversight rather than a decision is that the sibling row one function away already
    carried `flex-wrap:wrap`. Four groups had the defect. A nowrap box around TEXT is correct and stays —
    it stops a label breaking mid-phrase — and one tight inline group ("pick top [n]") is a deliberate
    exception, so the rule is about GROUPS of buttons, which is the shape that can only overflow."""
    offenders = []
    for i, line in enumerate(js.split("\n"), 1):
        if 'white-space:nowrap">' not in line:
            continue
        # count buttons after the nowrap opener on this line
        tail = line.split('white-space:nowrap">', 1)[1]
        n = tail.count("<button")
        if n > 1:
            offenders.append((i, n))
    assert not offenders, ("button groups that cannot wrap and will clip off the right edge "
                           f"(line, count): {offenders}")


def test_the_triage_row_itself_wraps(js: str):
    """The row has to be allowed to drop its buttons below the text, not just wrap them internally —
    otherwise a long explanation squeezes them to nothing instead of clipping them."""
    row = re.search(r'return `<div class="row" style="margin-top:6px;gap:8px;align-items:flex-start([^"]*)"', js)
    assert row, "the staleness triage row was not found — has it been rewritten?"
    assert "flex-wrap:wrap" in row.group(1), "the triage row must wrap"
