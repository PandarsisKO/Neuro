"""S38 — a verdict button has to say what it does (0.63.27). (Sorts after test_s37.)

Kyle: *"it's unclear in the app how to approve or reject sometimes."* Audited every place the app asks for a
verdict, and the inconsistency is the whole answer:

```
Claims workbench     Accept · Applies to us · Reject          words
Findings workbench   ✓  ✕                                     two glyphs, no label, NO title either
Findings (reserve)   ✓  📌  ✕                                  glyphs, partial titles
Findings (dismissed) ↩                                        glyph
bulk actions         "Approve the ticked ones" · "Dismiss all" words
```

The most-used verdict surface in the app was the least labelled — and on the `suggested` filter, where the
approving actually happens, the two buttons carried neither text nor a tooltip. Worse, `✓` already means *"this
happened"* elsewhere in the same file (`✓ already in your library`, `✓ added`, `✓ attached`), so one glyph was
both a status and a command.

`📌` for "send it back to the review queue" is the clearest case that an icon cannot carry a verb: nothing about a
pin says that, and it was reachable only by hovering and waiting for a tooltip.

This gate reads the shipped `web/index.html` and requires every button that changes a verdict — `noteStatus`,
`promoteReserve`, `claimStatus`, `bulkNotes` — to carry a word, not just a symbol. It is a text check on purpose:
there is no build step and no DOM here (`test_s5_ui_syntax.py` runs `node --check` for the same reason), and the
property worth protecting is small enough to state as one rule.
"""
from __future__ import annotations

import pathlib
import re
from tests.frontend_helpers import ui_source

UI = pathlib.Path(__file__).resolve().parent.parent / "neurosearch" / "web" / "index.html"
VERDICT_CALLS = ("noteStatus(", "promoteReserve(", "claimStatus(", "bulkNotes(")
# every glyph this file uses on an action control, so "has a word" means "has something other than these"
GLYPHS = "✓✕✗×📌↩⏫🔄👁🎬🧽📥🧹⚠▶📖💬🔎💵📊⏳●‹›→↗…"


def _buttons(src: str) -> list[tuple[str, str]]:
    """(attributes, inner text) for every <button> whose onclick changes a verdict.

    Hand-scanned rather than regexed: these tags contain `${...}` template holes with their own quotes and `>`
    characters, and a regex for the closing bracket of the open tag walks straight into one (my first version of
    this gate mis-parsed the bulk buttons and reported a false failure)."""
    out: list[tuple[str, str]] = []
    i = 0
    while True:
        i = src.find("<button", i)
        if i < 0:
            return out
        j, depth = i + 7, 0
        while j < len(src):
            if src.startswith("${", j):
                depth += 1; j += 2; continue
            if src[j] == "}" and depth:
                depth -= 1; j += 1; continue
            if src[j] == ">" and not depth:
                break
            j += 1
        attrs, k = src[i:j], src.find("</button>", j)
        label = src[j + 1:k] if k > 0 else ""
        if any(c in attrs for c in VERDICT_CALLS):
            out.append((attrs, label))
        i = j + 1


def _row_buttons(src: str) -> list[tuple[str, str]]:
    """The per-item verdicts — one finding, one Claim. Bulk buttons are a separate contract: their text is already
    a whole sentence ("Approve the ticked ones"), so they need a word but not a hover explanation."""
    return [(a, l) for a, l in _buttons(src) if "${n.id}" in a or "${c.id}" in a]


def _words(label: str) -> str:
    """The label with markup, template holes and decoration stripped — what a person actually reads."""
    txt = re.sub(r"<[^>]+>", "", label)          # nested spans
    txt = re.sub(r"\$\{[^}]*\}", "", txt)        # ${...} interpolation
    txt = txt.translate({ord(c): None for c in GLYPHS})
    return re.sub(r"\s+", " ", txt).strip()


def test_there_are_verdict_buttons_to_check():
    """A gate that silently matches nothing is not a gate."""
    src = ui_source(UI.parent)
    assert len(_buttons(src)) >= 8 and len(_row_buttons(src)) >= 6


def test_every_verdict_button_says_what_it_does():
    bare = []
    for tag, label in _buttons(ui_source(UI.parent)):
        if not _words(label):
            bare.append(tag[:150])
    assert not bare, ("a verdict button with no word in it — a person should not have to hover a glyph to learn "
                      "whether it approves or rejects:\n" + "\n".join(bare))


def test_every_verdict_button_also_carries_a_title():
    """The word says WHAT; the title says what it means for the project — 'approved findings feed exports, the
    plan and Claims', 'nothing is deleted'. A verdict that cannot be explained on hover is a verdict a person
    makes without knowing the consequence."""
    missing = []
    for tag, _label in _row_buttons(ui_source(UI.parent)):
        if not re.search(r'title="[^"]{8,}"', tag):
            missing.append(tag[:150])
    assert not missing, "verdict button with no explanatory title:\n" + "\n".join(missing)


def test_the_approve_and_dismiss_verbs_are_the_same_words_everywhere():
    """Three separate call sites render a findings verdict (workbench row, per-source block, reserve drawer). The
    same action must read identically in all of them, or the app teaches three vocabularies for one decision."""
    src = ui_source(UI.parent)
    approve = [_words(l) for t, l in _row_buttons(src) if "'approved'" in t]
    dismiss = [_words(l) for t, l in _row_buttons(src) if "'dismissed'" in t]
    assert approve and len(set(approve)) == 1, f"approve reads as {sorted(set(approve))}"
    assert dismiss and len(set(dismiss)) == 1, f"dismiss reads as {sorted(set(dismiss))}"


def test_the_status_glyphs_are_not_reused_as_commands_without_a_word():
    """`✓` means 'this happened' in several status lines in this file (✓ added, ✓ attached, ✓ already in your
    library). That is fine — what is not fine is the same glyph standing alone as a command, which is how it read
    on the findings row."""
    src = ui_source(UI.parent)
    for tag, label in _buttons(src):
        w = _words(label)
        if "✓" in label:
            assert w, f"bare ✓ as a command: {tag[:120]}"
