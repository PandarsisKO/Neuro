"""S76 -- topic/basis claim synthesis (item 1, Kyle's decision session, 2026-09-20): a synthesized summary line
sitting above a group of related weak claims, e.g. "9 sources give ranges of 1x-7x depending on business type...
most cluster around 2-4x SDE." Individual claims stay untouched underneath -- this is NOT claim merging (see
`claims.py`'s `merge_into`, which is deliberately narrow: same proposition, same scope). These claims are kept
separate on purpose because they measure genuinely different things once you group by valuation *basis* (SDE vs.
EBITDA vs. cash flow vs. revenue vs. profit) -- averaging across bases would misrepresent the sources. So this
module groups by (topic, basis) first, and only synthesizes within a group that shares both.

Deterministic, $0 (no AI cost): regex extraction of "Nx" / "N-Mx" multiples from claim text already on hand,
grouped by the claim's existing `topic` field and a keyword-matched `basis`, summarized with plain min/max plus a
defensible "most commonly" cluster found by a sweep over the extracted ranges (the sub-range covered by the most
sources -- not a guess, an intersection of the ranges that actually overlap there).

`synthesize_topic_summaries()` is read-only and returns a list the caller (currently `review_queue.build()`) adds
to its response above the individual queue items; it changes nothing in the database and proposes no claim edits.
"""
from __future__ import annotations

import re
from typing import Any

_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX]?\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*[xX]\b"
)
_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\b")

# Checked in order -- first match wins, so more specific terms (SDE) are tested before terms they might also
# trigger a looser match on (profit/revenue language sometimes appears in the same sentence as SDE).
_BASIS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sde", re.compile(r"\bsde\b|seller.{0,3}discretionary earnings", re.I)),
    ("ebitda", re.compile(r"\bebitda\b", re.I)),
    ("cash_flow", re.compile(r"cash\s*flow", re.I)),
    ("revenue", re.compile(r"\brevenue\b|top.?line|gross sales", re.I)),
    ("profit", re.compile(r"net (profit|income)|\bprofit\b", re.I)),
]

BASIS_LABELS = {
    "sde": "SDE", "ebitda": "EBITDA", "cash_flow": "cash flow", "revenue": "revenue",
    "profit": "profit", "unspecified": "",
}

MIN_GROUP = 3  # matches knowledge.py's MIN_NODE_CLAIMS threshold for "enough to say something about"

# Business valuation multiples for small/mid-size businesses essentially never run this high. A claim's text
# containing a bare "Nx" far above this is almost certainly a different kind of "Nx" statement entirely (revenue
# growth, a return multiple, a subscriber-count multiple) caught by the same regex, not a valuation multiple --
# so it is dropped rather than dragged into a group's overall range as if it were comparable to the rest.
MAX_PLAUSIBLE_MULTIPLE = 30.0


def extract_range(text: str) -> tuple[float, float] | None:
    """Best-effort "Nx" / "N-Mx" multiple extraction. Returns (low, high), equal for a single value, or None.
    A value above MAX_PLAUSIBLE_MULTIPLE is treated as a different kind of "Nx" claim, not a valuation multiple,
    and yields None rather than a range that would misrepresent the rest of its group."""
    if not text:
        return None
    m = _RANGE_RE.search(text)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        lo, hi = (a, b) if a <= b else (b, a)
        return None if hi > MAX_PLAUSIBLE_MULTIPLE else (lo, hi)
    m = _SINGLE_RE.search(text)
    if m:
        v = float(m.group(1))
        return None if v > MAX_PLAUSIBLE_MULTIPLE else (v, v)
    return None


def detect_basis(text: str) -> str:
    text = text or ""
    for name, pattern in _BASIS_PATTERNS:
        if pattern.search(text):
            return name
    return "unspecified"


def _densest_interval(ranges: list[tuple[float, float]]) -> tuple[tuple[float, float], int]:
    """The sub-range covered by the most input ranges, and how many cover it. O(n^2) -- fine for review-queue
    group sizes (single digits to low tens)."""
    points = sorted({p for r in ranges for p in r})
    probe_points: list[float] = []
    for i, p in enumerate(points):
        probe_points.append(p)
        if i + 1 < len(points):
            probe_points.append((p + points[i + 1]) / 2)

    best_count = 0
    best_interval = ranges[0]
    for p in probe_points:
        containing = [r for r in ranges if r[0] <= p <= r[1]]
        if len(containing) > best_count:
            best_count = len(containing)
            best_interval = (max(r[0] for r in containing), min(r[1] for r in containing))
    return best_interval, best_count


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.1f}"


def _range_phrase(low: float, high: float) -> str:
    lo, hi = _fmt(low), _fmt(high)
    return f"{lo}x" if lo == hi else f"{lo}x–{hi}x"


def synthesize_topic_summaries(items: list[dict[str, Any]], min_group: int = MIN_GROUP) -> list[dict[str, Any]]:
    """Groups `items` (review-queue candidate dicts: needs `claim_id`, `text`, `topic`) by (topic, basis), and
    for every group with at least `min_group` members whose text yields a numeric multiple, returns a summary.
    Claims with no topic, or no extractable number, are left out of every summary -- they still appear in the
    queue itself, unsummarized, since this never removes or edits a claim."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for it in items:
        topic = it.get("topic")
        if not topic:
            continue
        rng = extract_range(it.get("text") or "")
        if rng is None:
            continue
        basis = detect_basis(it.get("text") or "")
        groups.setdefault((topic, basis), []).append({**it, "_range": rng})

    summaries: list[dict[str, Any]] = []
    for (topic, basis), members in groups.items():
        if len(members) < min_group:
            continue
        ranges = [m["_range"] for m in members]
        overall_low = min(r[0] for r in ranges)
        overall_high = max(r[1] for r in ranges)
        cluster, cluster_count = _densest_interval(ranges)
        n = len(members)
        basis_label = BASIS_LABELS.get(basis, "")
        basis_phrase = f" {basis_label}" if basis_label else ""
        summary_text = (
            f"{n} sources give ranges of {_range_phrase(overall_low, overall_high)}{basis_phrase} — "
            f"most cluster around {_range_phrase(*cluster)}{basis_phrase} ({cluster_count} of {n})."
        )
        summaries.append({
            "topic": topic, "basis": basis, "n": n,
            "overall_range": {"low": overall_low, "high": overall_high},
            "cluster_range": {"low": cluster[0], "high": cluster[1], "count": cluster_count},
            "summary_text": summary_text,
            "claim_ids": [m["claim_id"] for m in members],
        })

    summaries.sort(key=lambda s: (-s["n"], s["topic"], s["basis"]))
    return summaries
