"""S28 — a quote is evidence if it is in the SOURCE (0.63.9). (Sorts after test_s27.)

Measured on Kyle's live database: `validation_events` held **321** `finding_validation_failed` rows, 198 of them on
one day, against 20,289 findings. 319 of the 321 were *"quote not found in transcript"*, median quote length 11
words, none over the 40-word limit. So I checked the 200 most recent against his actual transcripts:

```
105  (53%)  the quote IS in the transcript — just not in the window being validated
 30  (15%)  an elided quote whose every fragment is verbatim ("A... B")
 63  (32%)  genuinely not there — a paraphrase, a video title, a figure nobody said
```

**Two thirds of the rejected findings were valid evidence, already paid for, thrown away.** Two causes:

* `findings._windows` cuts the transcript at `WINDOW_CHARS` on a line boundary. A quote that straddles a boundary
  can never verify, and the model is not told where the seams are. The material on either side is the same source.
* An ellipsis is ordinary quotation, and the validator required one contiguous run.

Neither fix weakens the invariant — no quote, no finding. The same words still have to be found, in the same order,
in the same source, and the 63 that were not there are still rejected. What changes is the demand that they be
*inside one arbitrary slice* and *consecutive*. And an out-of-window quote gets its LOCATOR corrected from where
the quote actually is, so the citation becomes more accurate than the model's own claim about it.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_ev_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, evidence, findings  # noqa: E402
from neurosearch.config import settings  # noqa: E402

# His own rejected quotes, verbatim from validation_events.
ELIDED = "average customer size currently is $1,600 per job... we're doing like a consistent like $30,000 a month"
SPOKEN = ("so the average customer size currently is 1600 per job and with repeat work we are doing like a "
          "consistent like 30000 a month which is why the model holds up")


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


# ------------------------------------------------------------------ an elided quote

def test_an_elided_quote_is_a_quote():
    assert evidence.evidence_for({"quote": ELIDED}, SPOKEN)["ok"] is True
    assert evidence.evidence_for({"quote": ELIDED}, SPOKEN)["elided"] is True


def test_the_pieces_must_be_in_the_order_they_were_written():
    """Reversing them is a different claim about what was said, so it is not evidence."""
    backwards = "we're doing like a consistent like $30,000 a month... average customer size currently is $1,600"
    assert evidence.evidence_for({"quote": backwards}, SPOKEN)["ok"] is False


def test_a_missing_piece_fails_the_whole_quote():
    assert evidence.evidence_for({"quote": ELIDED + "... and margins of ninety percent"}, SPOKEN)["ok"] is False


def test_a_two_word_piece_is_not_evidence():
    """"consistency... documentation... proactive planning" was rejected and should stay rejected: pieces this
    short match almost any transcript, so they prove nothing. It is in his data as a real example."""
    q = "consistency... documentation... proactive planning"
    assert evidence.quote_fragments(q) == []
    assert evidence.evidence_for({"quote": q}, "we talked about consistency and documentation today")["ok"] is False


# ------------------------------------------------------------------ scope: window vs source

def test_a_quote_from_elsewhere_in_the_same_source_is_evidence():
    ev = evidence.evidence_for({"quote": "a consistent like 30000 a month"}, "an unrelated window", SPOKEN)
    assert ev["ok"] is True and ev["scope"] == "source"


def test_the_window_is_still_preferred_so_the_common_case_is_unchanged():
    ev = evidence.evidence_for({"quote": "a consistent like 30000 a month"}, SPOKEN, SPOKEN)
    assert ev["scope"] == "window"


def test_a_quote_in_neither_is_still_rejected():
    """The 63 of 200 that were genuinely not there. This is the invariant the release must not weaken."""
    for q in ["buying just one laundromat can change your life",
              "a dollar is worth about $20 or more sometimes",
              "From Family Business to a $400M+ Exit: Tony Safoian's Incredible Journey"]:
        assert evidence.evidence_for({"quote": q}, "an unrelated window", SPOKEN)["ok"] is False


def test_no_quote_at_all_is_still_no_finding():
    assert evidence.evidence_for({"quote": ""}, SPOKEN)["reason"] == "no quote"
    assert evidence.evidence_for({"quote": " ".join(["word"] * 41)}, SPOKEN)["reason"].startswith("quote too long")


# ------------------------------------------------------------------ the locator gets corrected, not inherited

def test_an_out_of_window_quote_has_its_locator_recovered():
    segs = [{"start": 0.0, "text": "opening remarks about nothing in particular"},
            {"start": 1800.0, "text": SPOKEN}]
    assert evidence.locate_quote("a consistent like 30000 a month", segs) == 1800.0


def test_a_quote_nobody_said_gets_no_locator():
    segs = [{"start": 0.0, "text": "opening remarks about nothing in particular"}]
    assert evidence.locate_quote("the mitochondria is the powerhouse of the cell", segs) is None


def test_materialize_relocates_the_citation_rather_than_trusting_the_model(fresh):
    """End to end: the model quotes something real from 30 minutes in while claiming it was at 0:05."""
    p = db.create_project("ev", brief="b")
    s = db.upsert_source(platform="youtube", external_id="ev1", url="https://youtu.be/ev1",
                         title="a long interview", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    db.replace_transcript(s["id"], [{"start": 0.0, "end": 10.0, "text": "opening remarks"},
                                    {"start": 1800.0, "end": 1860.0, "text": SPOKEN}], [])
    out = findings.materialize(
        p["id"], s["id"],
        [("[0:00] opening remarks", {"summary": "s", "substance": 50, "findings": [
            {"title": "unit economics", "finding": "The operator reports a repeatable monthly figure.",
             "ts": "0:05", "quote": "a consistent like 30000 a month", "importance": 4}]})],
        model="m", transport="interactive")
    assert out["suggested"] == 1
    note = db.list_project_notes(p["id"], status="suggested")[0]
    assert note["citations"] and note["citations"][0]["start"] == 1800.0, "the locator must come from the transcript"


def test_a_finding_with_no_real_quote_is_still_dropped_by_materialize(fresh):
    p = db.create_project("ev", brief="b")
    s = db.upsert_source(platform="youtube", external_id="ev2", url="https://youtu.be/ev2",
                         title="another", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    db.replace_transcript(s["id"], [{"start": 0.0, "end": 10.0, "text": "opening remarks"}], [])
    out = findings.materialize(
        p["id"], s["id"],
        [("[0:00] opening remarks", {"summary": "s", "substance": 50, "findings": [
            {"title": "invented", "finding": "Something nobody said.", "ts": "0:05",
             "quote": "buying just one laundromat can change your life", "importance": 4}]})],
        model="m", transport="interactive")
    assert out["suggested"] == 0 and out["rejected_quotes"] == 1
