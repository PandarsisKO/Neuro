"""Mechanical evidence validators — the machine-checkable hallucination detectors (hardening ladder, Mission A4/A5).

A finding's quote must literally occur in the transcript window it came from; an answer's [n] citations must point
at excerpts that were actually supplied; a plan's evidence ids must exist in the material. None of these need a
model, so they run on every call for free, and the eval reports them as hard numbers.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

_PUNCT = re.compile(r"[^a-z0-9\s]")
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


_THOUSANDS = re.compile(r"(?<=\d),(?=\d)")
_CONTRACTIONS = ((" re ", " are "), (" m ", " am "), (" ve ", " have "), (" ll ", " will "), (" nt ", " not "))


def normalize(text: str) -> str:
    """Lower-case, punctuation-stripped words — the form both a quote and a transcript are compared in.

    Two things it has to get right, both found by measuring Kyle's rejected findings (0.63.9):

    * **A digit group separator is not punctuation.** `$1,600` became `1 600` while the transcript said `1600`, so
      a nine-word quote had to match an eight-word run and the ratio fell under the floor. Every quote carrying a
      money figure was affected, which in a business-acquisition corpus is most of the interesting ones.
    * **A contraction is the same words.** `we're` became `we re` against a transcript that says `we are`. Whisper
      and YouTube captions disagree about contractions constantly, and that is not a difference in what was said.
    """
    t = _WS.sub(" ", _PUNCT.sub(" ", _THOUSANDS.sub("", (text or "").translate(_QUOTES).lower())))
    t = f" {t.strip()} "
    for a, b in _CONTRACTIONS:
        t = t.replace(a, b)
    return _WS.sub(" ", t).strip()


def quote_in_text(quote: str, text: str, min_ratio: float = 0.8) -> bool:
    """True when the quote occurs verbatim (after normalisation) or as a near-verbatim contiguous run — transcripts
    are auto-generated, so "gonna"/"going to" and a dropped filler word should not fail a real quote."""
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return False
    if q in t:
        return True
    qw = q.split()
    if len(qw) < 3:
        return False
    tw = t.split()
    m = difflib.SequenceMatcher(None, qw, tw, autojunk=False).find_longest_match(0, len(qw), 0, len(tw))
    if m.size / len(qw) >= min_ratio:
        return True
    # two shorter runs (a filler word in the middle) still count
    blocks = difflib.SequenceMatcher(None, qw, tw, autojunk=False).get_matching_blocks()
    covered = sum(b.size for b in blocks if b.size >= 2)
    return covered / len(qw) >= min_ratio


ELLIPSIS = re.compile(r"\.\s*\.\s*\.+|\u2026")
FRAGMENT_MIN_WORDS = 3        # below this a "fragment" matches almost anything and is not evidence


def _span(quote: str, text: str) -> tuple[int, int] | None:
    """Where the quote sits in the text, as (word index, length), or None. Same tolerance as `quote_in_text`."""
    q, t = normalize(quote), normalize(text)
    if not q or not t:
        return None
    qw, tw = q.split(), t.split()
    if len(qw) < FRAGMENT_MIN_WORDS:
        return None
    at = t.find(q)
    if at >= 0:
        return len(t[:at].split()), len(qw)
    m = difflib.SequenceMatcher(None, qw, tw, autojunk=False).find_longest_match(0, len(qw), 0, len(tw))
    if m.size and m.size / len(qw) >= 0.8:
        return m.b, m.size
    return None


def quote_fragments(quote: str) -> list[str]:
    """An elided quote's pieces. `"consistency... documentation... proactive planning"` is three."""
    return [f.strip() for f in ELLIPSIS.split(quote or "") if len(f.strip().split()) >= FRAGMENT_MIN_WORDS]


def elided_quote_in_text(quote: str, text: str) -> bool:
    """True when every piece of an ELIDED quote occurs in the text, in the order it was written.

    Measured on Kyle's 200 most recent rejections: 30 of them were quotes like *"average customer size currently
    is $1,600 per job... we're doing like a consistent like $30,000 a month"* — a perfectly ordinary elision, and
    every piece verbatim in the transcript. Checking each piece separately is not a weaker test than checking the
    whole string: the same words must be found, in the same order, and a piece shorter than
    `FRAGMENT_MIN_WORDS` is not counted at all. What is dropped is the demand that the speaker said them
    *consecutively*, which the ellipsis was announcing in the first place."""
    frags = quote_fragments(quote)
    if len(frags) < 2:
        return False
    at = -1
    for f in frags:
        sp = _span(f, text)
        if not sp or sp[0] <= at:
            return False                  # missing, or out of order
        at = sp[0]
    return True


def evidence_for(finding: dict[str, Any], window_text: str, source_text: str | None = None) -> dict[str, Any]:
    """Is this finding evidenced, and by what — `{ok, reason, scope, elided}`.

    `scope` is `"window"` when the quote is in the window the model was given and `"source"` when it is elsewhere
    in the same transcript. **Elsewhere in the same source is still evidence.** Measured on his 200 most recent
    rejections: **105 of them (53%) were quotes that are in the transcript**, rejected only because they were not
    in the window being validated — windows are cut at `WINDOW_CHARS` on a line boundary, so a quote that straddles
    one cannot ever be verified, and the material either side is the same source either way. 63 were genuinely not
    there (a paraphrase, a title, a figure nobody said) and are still rejected, which is the point of the check.

    A `source`-scope quote means the model's own `ts` cannot be trusted, so the caller re-derives the locator from
    where the quote actually is (`locate_quote`) — the citation gets more accurate, not less."""
    quote = (finding.get("quote") or "").strip()
    if not quote:
        return {"ok": False, "reason": "no quote", "scope": None, "elided": False}
    if len(quote.split()) > 40:
        return {"ok": False, "reason": "quote too long to be verbatim", "scope": None, "elided": False}
    elided = bool(ELLIPSIS.search(quote)) and len(quote_fragments(quote)) >= 2
    for scope, text in (("window", window_text), ("source", source_text)):
        if not text:
            continue
        if quote_in_text(quote, text) or (elided and elided_quote_in_text(quote, text)):
            return {"ok": True, "reason": None, "scope": scope, "elided": elided}
    return {"ok": False, "reason": "quote not found in transcript", "scope": None, "elided": elided}


def locate_quote(quote: str, segments: list[dict[str, Any]]) -> float | None:
    """The start time/page of the segment the quote begins in, or None.

    Used when a quote was found outside the window the model was reading: its claimed locator describes a place it
    was not looking at, and the true one is recoverable from the transcript."""
    if not segments:
        return None
    first = (quote_fragments(quote) or [quote])[0]
    best: tuple[float, Any] = (0.0, None)
    for seg in segments:
        sp = _span(first, seg.get("text") or "")
        if sp:
            return float(seg.get("start") or 0.0)
        nq, nt = normalize(first), normalize(seg.get("text") or "")
        if nq and nt:
            share = difflib.SequenceMatcher(None, nq.split(), nt.split(), autojunk=False).ratio()
            if share > best[0]:
                best = (share, seg)
    return float(best[1].get("start") or 0.0) if best[1] is not None and best[0] >= 0.5 else None


def check_finding(finding: dict[str, Any], window_text: str, source_text: str | None = None) -> str | None:
    """None when the finding is evidenced, else the reason it is rejected. Thin wrapper over `evidence_for`, kept
    because the evals and several tests read a reason string."""
    return evidence_for(finding, window_text, source_text)["reason"]


CITE_RE = re.compile(r"\[(\d{1,3})\]")


def check_citations(text: str, n_excerpts: int) -> tuple[list[int], list[int]]:
    """(valid numbers, invalid numbers) referenced in an answer."""
    nums = sorted({int(n) for n in CITE_RE.findall(text or "")})
    return [n for n in nums if 1 <= n <= n_excerpts], [n for n in nums if not 1 <= n <= n_excerpts]


def strip_citations(text: str, invalid: list[int]) -> str:
    if not invalid:
        return text
    bad = {str(n) for n in invalid}
    return re.sub(r"\s?\[(\d{1,3})\]", lambda m: "" if m.group(1) in bad else m.group(0), text)


def plan_evidence_ids(obj: Any) -> list[str]:
    """Every id referenced in an "evidence" list anywhere in a plan/analysis JSON."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "evidence" and isinstance(v, list):
                out += [str(x) for x in v]
            else:
                out += plan_evidence_ids(v)
    elif isinstance(obj, list):
        for x in obj:
            out += plan_evidence_ids(x)
    return out


def drop_evidence_ids(obj: Any, bad: set[str]) -> None:
    """Remove the given ids from every "evidence" list, in place."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "evidence" and isinstance(v, list):
                v[:] = [x for x in v if str(x) not in bad]
            else:
                drop_evidence_ids(v, bad)
    elif isinstance(obj, list):
        for x in obj:
            drop_evidence_ids(x, bad)


def check_plan_evidence(plan: dict[str, Any], known: set[str]) -> tuple[int, list[str]]:
    """(number of references, the ones that point at nothing)."""
    refs = plan_evidence_ids({k: v for k, v in plan.items() if not k.startswith("_")})
    return len(refs), sorted({r for r in refs if r not in known})
