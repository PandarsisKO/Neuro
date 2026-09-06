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


def normalize(text: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", (text or "").translate(_QUOTES).lower())).strip()


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


def check_finding(finding: dict[str, Any], window_text: str) -> str | None:
    """None when the finding is evidenced by the window, else the reason it is rejected."""
    quote = (finding.get("quote") or "").strip()
    if not quote:
        return "no quote"
    if len(quote.split()) > 40:
        return "quote too long to be verbatim"
    if not quote_in_text(quote, window_text):
        return "quote not found in transcript"
    return None


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


def check_plan_evidence(plan: dict[str, Any], known: set[str]) -> tuple[int, list[str]]:
    """(number of references, the ones that point at nothing)."""
    refs = plan_evidence_ids({k: v for k, v in plan.items() if not k.startswith("_")})
    return len(refs), sorted({r for r in refs if r not in known})
