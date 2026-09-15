"""L-41 (EXECUTION-LADDER.md Stage 6, PRODUCT-INTELLIGENCE-MISSION.md P3 "Morning Report", rulings section 7 --
"MORNING REPORT V1 MUST NOT PRETEND P4 EXISTS"). Make one night's autonomous work understandable in under a
minute, honestly, without promising a judgment queue Neuro cannot yet rank defensibly.

Ruling section 7, followed exactly: V1 MAY show what changed, coverage delta, what Neuro researched, important
existing tensions, stale/risky state via existing staleness.triage tiers marked EXPLICITLY PROVISIONAL,
spend/budget, operational details collapsed. V1 MUST NOT claim "these are the exact N things you need to
review" unless the ranking has a real defensible basis -- it does not yet (that basis is Stage 7's Decision
Impact work, L-50/L-51), so this module never produces that sentence, in any form. "Nothing important changed"
is a first-class outcome, not an edge case to special-case around.

Two functions: `for_envelope(envelope_id) -> dict` assembles delta.for_envelope()'s per-project data with each
project's staleness.triage() tiers (a $0, deterministic, read-only call -- see staleness.assess()'s own
docstring); `render_text(report) -> str` is the actual "Kyle reads this without opening Findings" surface, in
the mission doc's own primary hierarchy order: what changed (max emphasis) -> why it matters -> what needs me
-> what Neuro handled (secondary) -> operational details (collapsed, last).
"""
from __future__ import annotations

import time
from typing import Any

from . import delta

# staleness.triage()'s own tiers, in the order this report surfaces them -- rebuild_matters first (why-backed,
# the only tier the ruling's "provisional prioritization aid" language is really about), retry_failed next
# (operationally actionable), the other two collapsed into a single count (see render_text).
_TIER_ORDER = ("rebuild_matters", "retry_failed", "rebuild_transcript", "accept")


def for_envelope(envelope_id: str) -> dict[str, Any]:
    """$0, deterministic, read-only. Returns {"found": False, ...} for an unrecognised or not-yet-run envelope,
    same as delta.for_envelope() -- "nothing to report yet" is an ordinary answer, never an error."""
    from . import staleness

    d = delta.for_envelope(envelope_id)
    if not d.get("found"):
        return d

    projects: list[dict[str, Any]] = []
    for pd in d["projects"]:
        pid = pd["project_id"]
        if "error" in pd:
            projects.append({**pd, "staleness_tiers": None})
            continue
        try:
            t = staleness.triage(pid)
            # staleness.triage()'s own tiers are ALREADY per-tier summary dicts (each carrying its own "count",
            # not a bare list of rows) -- pull "count" straight through rather than re-deriving it.
            tiers = {k: {"count": int((t["tiers"].get(k) or {}).get("count") or 0)} for k in _TIER_ORDER}
        except Exception as e:  # noqa: BLE001 — a triage read failing must never blank out this project's delta
            tiers = {"error": str(e)}
        projects.append({**pd, "staleness_tiers": tiers})

    material_change = bool(d["new_tensions_total"]) or bool((d.get("adjudication") or {}).get("count")) or any(
        (pd.get("what_neuro_did") or {}).get("findings_suggested") for pd in d["projects"] if "error" not in pd)

    return {**d, "projects": projects, "material_change": material_change, "report_ts": time.time()}


def _fmt_usd(x: float) -> str:
    return f"${x:.2f}" if x >= 0.01 or x == 0 else f"${x:.4f}"


def render_text(report: dict[str, Any]) -> str:
    """The actual reading surface. Plain text/markdown-safe (no HTML): "Kyle explains the overnight change
    without opening Findings" is this rung's whole gate, and that means readable in a terminal or a plain email
    just as well as a UI panel."""
    if not report.get("found"):
        return f"No overnight report for {report.get('envelope_id')}: {report.get('reason', 'not found')}."

    lines: list[str] = []
    lines.append(f"Morning Report — {report['envelope_id']}" + ("" if report.get("ok") else "  [run did not complete cleanly]"))
    lines.append("")

    broken = [x for x in (report.get("assumptions") or {}).get("items") or [] if x["kind"] == "unresolvable"]
    if not report.get("material_change") and not any("error" in pd for pd in report["projects"]) and not broken:
        lines.append("Nothing important changed overnight.")
        lines.append(f"Spend: {_fmt_usd(report['budget']['actual_usd'])} of {_fmt_usd(report['budget']['authorized_usd'])} authorized.")
        return "\n".join(lines)
    if not report.get("material_change") and not any("error" in pd for pd in report["projects"]) and broken:
        lines.append("Nothing important changed overnight -- but one of the numbers the system runs on is broken:")
        from . import t6
        lines.extend(t6.render_lines({"items": broken}))
        return "\n".join(lines)

    for pd in report["projects"]:
        lines.append(f"## {pd['project_id']}")
        if "error" in pd:
            lines.append(f"  Did not run: {pd['error']}")
            lines.append("  Needs you: investigate why this project's nightly run failed.")
            lines.append("")
            continue

        wn = pd["what_neuro_did"]
        wc = pd["what_changed"]
        cov = wc.get("coverage") or {}
        tensions = wc.get("new_tensions") or {}

        # 1. What changed (max emphasis)
        changed_bits = []
        if wn["findings_suggested"]:
            changed_bits.append(f"{wn['findings_suggested']} new finding(s) suggested")
        if tensions:
            changed_bits.append(f"{sum(tensions.values())} new tension(s) ({', '.join(sorted(tensions))})")
        if cov.get("available") and cov.get("canonical_claims", {}).get("delta"):
            d_claims = cov["canonical_claims"]["delta"]
            changed_bits.append(f"{'+' if d_claims > 0 else ''}{d_claims} canonical claim(s)")
        lines.append("What changed: " + ("; ".join(changed_bits) if changed_bits else "nothing material"))

        # 2. Why it matters
        lines.append(f"Why it matters: {pd['why_it_matters']}")

        # 3. What needs me (never a false-precision claim -- see module docstring)
        if pd["what_needs_the_user"]:
            for item in pd["what_needs_the_user"]:
                lines.append(f"Needs you: {item.get('reason', item)}")
        else:
            lines.append("Needs you: nothing")

        # 4. What Neuro handled (secondary)
        lines.append(f"What Neuro did: read {wn['sources_read']} source(s)"
                     + (f", {wn['sources_stopped_by_probe']} stopped early by the substance probe" if wn["sources_stopped_by_probe"] else "")
                     + f", spent {_fmt_usd(wn['spend_usd'])}")

        # provisional staleness tiers, explicitly labeled per rulings section 7
        st = pd.get("staleness_tiers")
        if st and "error" not in st:
            worth_mentioning = {k: v for k, v in st.items() if k in ("rebuild_matters", "retry_failed") and v["count"]}
            if worth_mentioning:
                bits = ", ".join(f"{v['count']} {k.replace('_', ' ')}" for k, v in worth_mentioning.items())
                lines.append(f"Stale/risky (provisional triage, not a ranked judgment queue): {bits}")

        # 5. Operational details, collapsed
        lines.append(f"  (job(s): {', '.join(wn['job_ids']) if wn['job_ids'] else 'none'})")
        lines.append("")

    adj = report.get("adjudication")
    if adj and adj.get("ran") and adj.get("count"):
        lines.append(f"Adjudicated {adj['count']} disagreement(s) (T5, {_fmt_usd(float(adj.get('spent') or 0))} of "
                     f"{_fmt_usd(float(adj.get('budget') or 0))}); each verdict is a suggested finding, nothing was decided for you.")
        lines.append("")
    lines.append(f"Total spend: {_fmt_usd(report['budget']['actual_usd'])} of {_fmt_usd(report['budget']['authorized_usd'])} authorized"
                 f" ({_fmt_usd(report['budget']['estimated_usd'])} estimated).")
    from . import t6
    lines.extend(t6.render_lines(report.get("assumptions") or {}))     # L-61: last, collapsed, only when non-empty
    return "\n".join(lines).rstrip() + "\n"
