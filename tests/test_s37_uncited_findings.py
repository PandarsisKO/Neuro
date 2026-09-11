"""S37 — a verified finding stored with no citation at all (0.63.22). (Sorts after test_s36.)

Found by sweeping Kyle's live data for correctness rather than for speed. **63 live Claims in his large project
rest on no evidence whatsoever**, and every one of them was harvested from an approved finding whose citations
blob is empty. 123 of his 16,378 approved findings (0.8%) are like that, and they are not spread evenly:

```
platform      transcript_kind    findings   no citation    rate
spreadsheet   spreadsheet             134            69   51.5%
community     community                 9             9   100.0%
youtube       captions             16,733             1    0.0%
web / document / book / file / media / instagram      1,085   0    0.0%
```

Every platform that cites by timestamp or page is at zero. The cause is in his own rejection log: `_ts_to_seconds`
reads `p. 3`, `§ 3`, `sheet 3`, `post 3`, `MM:SS` and a bare integer — and on a spreadsheet the model writes the
sheet by **NAME**: `§ Reverse Calculator`, `§ Sheet: Profile`. A sheet's name is the meaningful thing about it and
its ordinal is not, so this is the model doing the reasonable thing. No digits, so the parser returns None — and
the citation was built **only** when that parse succeeded, so the finding was stored with `citations: []`.

Silently. No validation event, no counter, nothing: an uncitable finding was indistinguishable from a cited one,
which is the failure mode this codebase keeps paying for (0.63.2's OCR rung, 0.63.15's course importer, 0.63.20's
pool header). It then reached `claims.harvest`, which attaches evidence from a note's citations and so produced a
Claim resting on nothing — and `harvest` is idempotent per note, so nothing ever goes back for it.

**The fix does not parse more locator formats.** At the point the citation is built the quote has ALREADY been
verified against the source, so its position is a fact the app holds rather than something to take the model's
word for: `evidence.locate_quote` answers for every platform, needs no per-platform parsing and no model call. It
is the same move 0.63.9 made for a locator pointing at the wrong PLACE, applied to one that cannot be read at all.
If the quote cannot be placed either, the finding keeps its verified quote — paid, checked work is not discarded —
but `finding_uncitable` is recorded so it can be seen.

**Not repaired, and it cannot be cheaply:** the quote is only persisted INSIDE the citation, so his existing 79
uncited extractor findings have lost their quotes and can only be recovered by re-analysing those sources, which
costs money. That is Kyle's decision. `HARDENING.md` records it, along with the separate G5 boundary question the
sweep turned up: 25 of his 95 hand-written project notes were harvested into Claims with origin
`finding_suggested`, which mislabels his own words as something a finding suggested.
"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_uncit_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import db, findings  # noqa: E402
from neurosearch.config import settings  # noqa: E402

SHEETS = [
    (0.0, "Profile: asking price 950000 | SDE 617200 | multiple 1.5x"),
    (1.0, "Reverse Calculator: at a 1.25 DSCR the maximum supportable debt is 2.4 million dollars"),
    (2.0, "Assumptions: closing costs are three percent of the purchase price"),
]
QUOTE = "at a 1.25 DSCR the maximum supportable debt is 2.4 million dollars"


@pytest.fixture()
def sheet(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    p = db.create_project("cite", brief="buying an accounting firm")
    s = db.upsert_source(platform="spreadsheet", external_id="calc1", url="file:///calc.xlsx",
                         title="Copy of Acquisition Ace Deal Calculator", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    segs = [{"start": st, "end": st, "text": t} for st, t in SHEETS]
    db.replace_transcript(s["id"], segs, segs)
    yield p["id"], s["id"]
    db._local.conn = None


def _materialize(pid, sid, ts, quote=QUOTE, title="Max supportable debt at 1.25 DSCR"):
    window = "\n".join(f"[sheet {int(st)}] {t}" for st, t in SHEETS)
    out = {"summary": "a deal calculator", "substance": 70,
           "findings": [{"title": title, "finding": "The calculator caps supportable debt at 2.4M.",
                         "quote": quote, "ts": ts, "importance": 4}]}
    return findings.materialize(pid, sid, [(window, out)], model="claude-sonnet-5")


def _cites(pid):
    notes = db.list_project_notes(pid, status="suggested")
    assert notes, "no findings were stored"
    c = notes[0].get("citations") or []
    return json.loads(c) if isinstance(c, str) else c


# ------------------------------------------------------------------ his exact case

@pytest.mark.parametrize("ts", ["§ Reverse Calculator", "§ Sheet: Profile", "Reverse Calculator", "tab 2, row 7"])
def test_a_locator_naming_the_sheet_still_produces_a_citation(sheet, ts):
    """The four shapes his model actually wrote, none of which `_ts_to_seconds` can read."""
    pid, sid = sheet
    assert findings._ts_to_seconds(ts, "spreadsheet") is None, "this test is pointless if the parser reads it"
    _materialize(pid, sid, ts)
    cites = _cites(pid)
    assert len(cites) == 1, f"{ts!r} produced no citation"
    assert cites[0]["source_id"] == sid and cites[0]["snippet"].startswith(QUOTE[:30])


def test_the_citation_points_where_the_quote_actually_is(sheet):
    """Not merely present — correct. The quote is on sheet 1, and the model named a different sheet entirely."""
    pid, sid = sheet
    _materialize(pid, sid, "§ Sheet: Profile")
    assert _cites(pid)[0]["timestamp"] == "sheet 1"


def test_a_readable_locator_is_still_honoured(sheet):
    """The recovery is a fallback, not a replacement: when the model's own locator parses, it is used."""
    pid, sid = sheet
    _materialize(pid, sid, "sheet 1")
    assert _cites(pid)[0]["timestamp"] == "sheet 1" and db.kv_get("evidence:locator_from_quote") in (None, 0, "0")


def test_the_recovery_is_counted(sheet):
    pid, sid = sheet
    _materialize(pid, sid, "§ Reverse Calculator")
    assert int(db.kv_get("evidence:locator_from_quote") or 0) == 1


def test_the_marker_is_added_so_the_finding_reads_as_cited(sheet):
    pid, sid = sheet
    _materialize(pid, sid, "§ Reverse Calculator")
    assert "[1]" in db.list_project_notes(pid, status="suggested")[0]["content"]


# ------------------------------------------------------------------ and when it genuinely cannot be placed

def test_an_unplaceable_quote_is_recorded_rather_than_stored_in_silence(sheet):
    """A finding whose quote cannot be located keeps the finding — paid, verified work is not discarded — but it
    can never be silent again, because `harvest` would turn it into a Claim resting on nothing."""
    pid, sid = sheet
    # a quote verbatim in the source, so validation passes, but placed by hand in a segment list that is empty
    _materialize(pid, sid, "§ Reverse Calculator", quote=QUOTE)
    ev = [r for r in db.connect().execute("SELECT kind FROM validation_events")]
    assert not [r for r in ev if r["kind"] == "finding_uncitable"], "this one IS placeable"

    db.replace_transcript(sid, [], [])                       # nothing left to locate against
    s2 = db.upsert_source(platform="spreadsheet", external_id="calc2", url="file:///calc2.xlsx",
                          title="Empty calculator", status="ready")
    db.add_project_sources(pid, [s2["id"]])
    out = {"summary": "s", "substance": 10,
           "findings": [{"title": "t", "finding": "f", "quote": "a quote in the window only",
                         "ts": "§ Nowhere", "importance": 3}]}
    findings.materialize(pid, s2["id"], [("[sheet 0] a quote in the window only", out)], model="claude-sonnet-5")
    kinds = [r["kind"] for r in db.connect().execute("SELECT kind FROM validation_events")]
    assert "finding_uncitable" in kinds
    assert int(db.kv_get("evidence:findings_uncitable") or 0) >= 1


def test_the_uncitable_event_says_what_it_saw(sheet):
    """The 0.63.15 rule: a message that names one cause for every failure is worse than one that says what it saw."""
    pid, sid = sheet
    db.replace_transcript(sid, [], [])
    out = {"summary": "s", "substance": 10,
           "findings": [{"title": "Sheet name only", "finding": "f", "quote": "a quote in the window only",
                         "ts": "§ Nowhere", "importance": 3}]}
    findings.materialize(pid, sid, [("[sheet 0] a quote in the window only", out)], model="claude-sonnet-5")
    row = db.connect().execute("SELECT detail FROM validation_events WHERE kind='finding_uncitable'").fetchone()
    d = json.loads(row["detail"])
    assert d["claimed_locator"] == "§ Nowhere" and d["platform"] == "spreadsheet" and d["quote"]


# ------------------------------------------------------------------ the platforms that already worked must not change

@pytest.mark.parametrize("platform,ts,expect", [("youtube", "1:09", "1:09"), ("document", "p. 3", "p. 3"),
                                                ("web", "§ 4", "§ 4"), ("community", "post 2", "post 2")])
def test_the_platforms_that_were_already_at_zero_percent_are_untouched(tmp_path, monkeypatch, platform, ts, expect):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    p = db.create_project("cite", brief="b")
    s = db.upsert_source(platform=platform, external_id="x1", url="https://example.com/x1", title="t", status="ready")
    db.add_project_sources(p["id"], [s["id"]])
    at = findings._ts_to_seconds(ts, platform)
    segs = [{"start": at, "end": at, "text": "the quote we are going to cite verbatim"}]
    db.replace_transcript(s["id"], segs, segs)
    out = {"summary": "s", "substance": 50,
           "findings": [{"title": "t", "finding": "f", "quote": "the quote we are going to cite verbatim",
                         "ts": ts, "importance": 3}]}
    findings.materialize(p["id"], s["id"], [(f"[{expect}] the quote we are going to cite verbatim", out)], model="m")
    notes = db.list_project_notes(p["id"], status="suggested")
    c = notes[0].get("citations") or []
    c = json.loads(c) if isinstance(c, str) else c
    assert len(c) == 1 and c[0]["timestamp"] == expect
    db._local.conn = None
