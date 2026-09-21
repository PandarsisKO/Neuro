"""S77 — the two surfaces that were missing, and the cutoff that moved.

Two features shipped with working backends and no way to reach them. The Discovery exclude list (S75) had a
table, a filter and three endpoints, and the only way to add an exclusion was a raw API call. The claims review
queue (L-51) had an endpoint and no web surface at all — and then S76 wrote topic summaries into that response,
so a second feature became invisible behind the first. Both are reachable now.

What these tests pin is the honesty of each surface rather than its markup:

- The synthesis is a READING AID, not a merge. It sits above the claims it summarises and every one of them is
  still listed individually below. A UI that showed the summary INSTEAD of its members would be claim merging
  by accident, which `claims.merge_into` exists to do deliberately and narrowly.
- The queue's cap hides things, and the pane says what it hid and that disagreement is never capped.
- The queue is fetched when its tab is opened, not with the rest of the Research view, and a decision drops
  the cached copy rather than patching it.
- The cutoff constant is read, never duplicated — which is what made moving it a one-line change.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from neurosearch import candidates

WEB = Path(__file__).resolve().parents[1] / "neurosearch" / "web"
JS = (WEB / "js" / "research.js").read_text()
HOME = (WEB / "js" / "home.js").read_text()
HTML = (WEB / "index.html").read_text()
QUEUE_FN = JS.split("globalThis.renderQueuePane")[1].split("globalThis.queueDecide")[0]


# ---------------------------------------------------------------- the cutoff (C1)

def test_the_cutoff_moved_to_45():
    """C1's blind review returned 10/10 kept in the 45-49 band — the ranker was right and the line was wrong."""
    assert candidates.LOW_RELEVANCE == 45


def test_the_cutoff_is_read_everywhere_and_duplicated_nowhere():
    """The reason moving it is one line. A second hard-coded 50 would silently disagree with the first."""
    import re
    src = Path(__file__).resolve().parents[1]
    hits = []
    for f in list((src / "neurosearch").glob("*.py")) + list((src / "tools").glob("*.py")):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"relevance\s*[<>]=?\s*50\b|LOW_RELEVANCE\s*=\s*(?!45)\d+", line) and "#" not in line.split("50")[0]:
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert not hits, "a hard-coded cutoff that will not move with the constant: " + "; ".join(hits)


def test_the_creator_trust_net_moves_with_it():
    """`reconsider_creator` resurfaces within DISPOSITION_MAX_ADJUST of the cutoff. Pinned so the relationship
    stays visible: lowering the cutoff lowers that floor too (38 -> 33), which is a consequence, not a bug."""
    assert candidates.LOW_RELEVANCE - candidates.DISPOSITION_MAX_ADJUST == 33


# ---------------------------------------------------------------- exclude list (S75)

def test_the_exclude_card_exists_and_can_add_both_kinds():
    assert 'id="excludes"' in HTML and 'id="exTerm"' in HTML
    assert '<option value="keyword">' in HTML and '<option value="creator">' in HTML


def test_the_exclude_list_loads_when_settings_opens():
    assert "loadExcludes()" in HOME, "the card would render empty forever without this"


def test_a_blank_term_is_refused_in_the_browser():
    """The server rejects it too; catching it here avoids a pointless round trip and says why."""
    fn = JS.split("globalThis.addExclude")[1].split("globalThis.delExclude")[0]
    assert "if (!term)" in fn


def test_the_empty_state_says_what_is_actually_happening():
    fn = JS.split("globalThis.renderExcludes")[1].split("globalThis.loadExcludes")[0]
    assert "judging everything against your brief" in fn, \
        "'none yet' would not tell the user that Discovery is currently unfiltered"


def test_the_card_says_excludes_do_not_touch_existing_sources():
    assert "Existing sources are untouched" in HTML, \
        "without this the control reads as though it might retire sources already in the project"


# ---------------------------------------------------------------- review queue (L-51) + synthesis (S76)

def test_the_queue_has_a_tab_and_a_pane():
    assert 'id="paneQueue"' in HTML
    assert "'queue', 'Review queue'" in JS


def test_the_summary_never_replaces_the_claims_it_summarises():
    """S76 is a reading aid. A UI that showed the summary INSTEAD of its members would be claim merging by
    accident — which claims.merge_into exists to do deliberately, narrowly, and somewhere else."""
    assert "topic_summaries" in QUEUE_FN and "reading aid" in QUEUE_FN
    summary_half, rows_half = QUEUE_FN.split("const REASON_WORDS", 1)
    assert "topic_summaries" in summary_half and "q.queue" in QUEUE_FN
    assert "unchanged and still listed individually" in summary_half


def test_the_queue_is_fetched_only_when_its_tab_is_opened():
    """It recomputes impact over every proposed Claim. Loading it with the rest of the Research view would make
    every visit pay for a pane most visits do not open."""
    load = JS.split("globalThis.loadResearch")[1].split("globalThis.resLoadState")[0]
    assert "review-queue" not in load
    assert "review-queue" in QUEUE_FN


def test_a_decision_drops_the_cached_queue_rather_than_patching_it():
    fn = JS.split("globalThis.queueDecide")[1][:400]
    assert "RES.queue = null" in fn


def test_switching_projects_cannot_show_the_previous_queue():
    load = JS.split("globalThis.loadResearch")[1].split("globalThis.resLoadState")[0]
    assert "RES.queue = null" in load


def test_the_cap_declares_what_it_hid_and_that_disagreement_is_never_capped():
    assert "not_shown" in QUEUE_FN and "hidden_total" in QUEUE_FN
    # 2026-09-21: `evidence_dismissed` joined disagreement as never-capped, and the sentence says both
    assert "Disagreement and rejected evidence are never capped" in QUEUE_FN


def test_the_reasons_are_shown_in_words_not_field_names():
    assert "sources disagree" in QUEUE_FN and "the Master Plan depends on it" in QUEUE_FN and "thin evidence" in QUEUE_FN
    assert "REASON_WORDS" in QUEUE_FN


def test_the_empty_state_distinguishes_nothing_proposed_from_nothing_flagged():
    assert "proposed_total" in QUEUE_FN and "none show disagreement" in QUEUE_FN


def test_a_failed_queue_build_does_not_render_as_an_empty_queue():
    assert "could not build the review queue" in QUEUE_FN


# ---------------------------------------------------------------- provenance that had no surface (2026-09-21)

def test_the_queue_carries_the_claims_origin():
    from pathlib import Path as _P
    rq = (_P(__file__).resolve().parents[1] / "neurosearch" / "review_queue.py").read_text()
    assert '"origin": c.get("origin")' in rq


def test_a_claim_built_on_an_unreviewed_finding_says_so():
    """claims.py has tagged these `finding_suggested` all along and nothing ever showed it. A Claim resting on
    evidence its owner has never looked at is precisely what this queue exists to surface."""
    assert "finding_suggested" in QUEUE_FN
    assert "from an unreviewed finding" in QUEUE_FN
    assert "status-warn" in QUEUE_FN, "it is a caution, not a neutral label"
