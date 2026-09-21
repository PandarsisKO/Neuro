"""S78 — one-at-a-time review for findings (Kyle: "right now it's just a huge wall of information").

WHAT THIS IS, AND WHAT IT IS CAREFULLY NOT. On sources, focus review exists because a deliberate Lose is a real
signal at full weight: it feeds `creator_verdict` and changes what gets surfaced next. On findings it does not
— Kyle decided (D1) that a dismissed finding counts zero, and `creator_yield` filters
`COALESCE(status,'') <> 'dismissed'` accordingly. So this is ergonomics and is not sold as anything else. D2 was
closed on the grounds that a findings reviewer would not TEACH anything; that remains true, and this was built
anyway because being pleasant to use is a sufficient reason on its own.

The tests below pin the three ways this could quietly mislead:

1. Findings are scored 1-5 (importance). `scClass`'s 60/30 thresholds are for the 0-100 relevance scale and
   would paint every finding red — the same class of bug as the pool showing `potential` under a label that
   said relevance.
2. A finding's source rendered under the label "creator" would be wrong in the literal sense, so the facts row
   is the caller's, not the source-shaped default.
3. It reviews the page ON SCREEN, filters included. Silently widening to all 17,193 would be a promise the
   interface cannot keep.

Plus the regression Kyle asked for explicitly: the list, the filters and the bulk buttons all still work.
"""
from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "neurosearch" / "web"
JS = (WEB / "js" / "research.js").read_text()
FOCUS = (WEB / "js" / "focus.js").read_text()
HTML = (WEB / "index.html").read_text()
CSS = (WEB / "styles.css").read_text()
FN = JS.split("globalThis.fbFocus")[1].split("globalThis.findingCard")[0]


# ---------------------------------------------------------------- it exists and is reachable

def test_the_button_is_in_the_findings_bar():
    assert 'onclick="fbFocus()"' in HTML
    bar = HTML.split('id="fbBar"')[1].split("</div>")[0]
    assert "fbFocus()" in bar, "it belongs beside the filters it inherits, not somewhere else on the page"


def test_it_reviews_the_page_on_screen_not_a_fresh_query():
    assert "FB.rows" in FN
    assert "/findings?" not in FN, \
        "re-querying would review items the filters currently exclude — a set the user never asked for"
    assert "FB.rows = r.findings" in JS, "loadWorkbench must keep what it rendered"


def test_an_empty_page_says_so_instead_of_opening_an_empty_reviewer():
    assert "Nothing to review here" in FN


# ---------------------------------------------------------------- the three ways it could mislead

def test_importance_is_not_coloured_on_the_relevance_scale():
    """1-5, not 0-100. scClass would call every finding low."""
    assert "impClass" in FN and "v >= 4 ? 'hi'" in FN
    assert "scoreClass: impClass" in FN
    assert "scoreTitle: 'importance, 1-5'" in FN, "the badge must say which number it is showing"


def test_the_component_still_defaults_to_the_relevance_scale_for_sources():
    assert "scoreClass: opts.scoreClass || scClass" in FOCUS, \
        "adding an override must not change what the source surfaces already do"


def test_the_facts_row_uses_the_findings_own_words():
    assert "['source', n.source_title]" in FN and "['area', n.area]" in FN
    assert "'creator'" not in FN, "a finding's source under the label 'creator' is wrong in the literal sense"
    assert "it.facts ||" in FOCUS, "…and the component has to allow the override for that to be possible"


# ---------------------------------------------------------------- what it does on submit

def test_keep_approves_and_lose_dismisses_through_the_one_existing_door():
    assert "'/api/notes/bulk-status'" in FN
    assert "status: 'approved'" in FN and "status: 'dismissed'" in FN
    # count the CALLS, not the string -- the comment above the function names the endpoint too
    assert FN.count("post('/api/notes/bulk-status'") == 2, "one call per verdict, and no second path for status changes"


def test_it_says_that_an_unjudged_finding_is_left_alone():
    assert "anything you do not judge is left exactly as it is" in FN
    assert "Nothing is deleted either way" in FN


def test_it_says_which_verdict_maps_to_which_status():
    """Keep/Lose and Approve/Dismiss are the same two actions in two vocabularies. The panel reconciles them
    rather than leaving the user to guess that Lose is the Dismiss they already know."""
    assert "Keep files it as approved, Lose as dismissed" in FN


def test_the_list_refreshes_without_resetting_the_users_place():
    assert "loadWorkbench(false)" in FN, "reset=True would throw the user back to page one after every batch"


# ---------------------------------------------------------------- the quote is the evidence

def test_the_supporting_quote_is_shown_as_a_quote():
    assert "quote: c.snippet" in FN
    assert "it.quote" in FOCUS and 'class="fx-quote"' in FOCUS      # the dotted form is the CSS selector
    assert "#focusLayer .fx-quote" in CSS


def test_the_quote_is_styled_from_tokens_not_literals():
    rule = CSS.split("#focusLayer .fx-quote")[1].split("}")[0]
    assert "var(--" in rule and "#" not in rule, "the design ratchet counts colour literals in CSS rules"


# ---------------------------------------------------------------- Kyle asked for the old controls to survive

def test_bulk_and_list_controls_are_untouched():
    assert "bulkNotes" in JS, "bulk approve/dismiss"
    assert 'id="fbStatus"' in HTML and 'id="fbQ"' in HTML and 'id="fbSort"' in HTML, "filters and sorting"
    assert "sweepLow" in JS, "the low-value sweep"
    assert "findingCard" in JS, "the list rows themselves"
