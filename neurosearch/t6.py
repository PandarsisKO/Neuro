"""L-61 (EXECUTION-LADDER.md Stage 8, PRODUCT-INTELLIGENCE-MISSION.md P6 "T6"): surface an assumption ONLY where
it changes what the user should know -- never a generic assumptions dashboard (`neurosearch assumptions` already
is the ledger; this is not a second one).

The mission doc names four occasions. This slice implements the three that are deterministic today, all read
off the night's own envelope record plus the ledger, $0:

  1. "a measured constant no longer matches reality" -- the narrowest provable case: the ledger can no longer
     resolve the constant at all (renamed/moved: `value` starts with "ERROR:"), so whatever the code now does is
     not what was measured. Always surfaced, exercised or not, because it is a broken fact, not a stale one.
  2. "a plan depends on an unmeasured assumption" -- generalised to "tonight's OUTPUT depended on an unmeasured
     assumption": the envelope record says which mechanisms actually fired (a probe stopped sources; findings
     were harvested into clusters; the budget walk ran across projects; T5 adjudicated; scheduled work held the
     keep-awake assertion), and the ledger says which never-measured numbers shaped each. Surfaced only when the
     mechanism fired tonight.
  3. "an assumption has expired" -- a MEASURED number whose measurement is older than STALE_DAYS and which fired
     tonight. Age alone is not drift, so this is a warning to re-check, never a claim that the number is wrong.

Not implemented: automatic re-measurement ("does the constant still match reality" beyond resolution failure).
Each ledger entry's `how_to_verify` is the manual check until that assumption's re-check earns its own rung --
the ledger's own docstring already says so; this module does not pretend otherwise.

Read-only. No write, no provider call.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import assumptions

STALE_DAYS = 60
# Only numbers that shape OUTPUT (what gets merged, stopped, or budgeted) can change what the user should know;
# kind="default" entries (concurrency, ETAs, lookahead) change how fast, and never surface here unless broken.
OUTPUT_KINDS = ("threshold", "weight", "budget")
MAX_LINES = 3   # collapsed operational detail, per the P3 hierarchy -- never the headline

# mechanism key -> how the envelope record proves it fired tonight (delta.for_envelope()'s shape).
MECHANISMS = ("substance_probe", "findings_clusters", "findings_extract", "nightly_budget_walk",
              "staleness_triage", "power_assertion", "adjudication")


def mechanisms_fired(d: dict[str, Any]) -> set[str]:
    """Which mechanisms a night's delta record proves ran. Conservative: a mechanism is "fired" only when the
    record carries a number that could not be non-zero otherwise."""
    fired: set[str] = set()
    projects = [p for p in d.get("projects") or [] if "error" not in p]
    for p in projects:
        wn = p.get("what_neuro_did") or {}
        if wn.get("sources_stopped_by_probe"):
            fired.add("substance_probe")
        if wn.get("findings_suggested"):
            fired.update(("findings_clusters", "findings_extract"))   # a suggested finding was extracted, then harvested
        if wn.get("sources_read"):
            fired.add("findings_extract")
    if sum(1 for p in projects if (p.get("what_neuro_did") or {}).get("sources_read")) > 1:
        fired.add("nightly_budget_walk")
    if (d.get("adjudication") or {}).get("count"):
        fired.add("adjudication")
    return fired


def _age_days(measured_on: str | None, today: date) -> int | None:
    if not measured_on:
        return None
    try:
        y, m, dd = (int(x) for x in measured_on.split("-"))
        return (today - date(y, m, dd)).days
    except ValueError:
        return None


def surface(d: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """The T6 items worth a line in tonight's report, or none. `d` is delta.for_envelope()'s dict."""
    today = today or date.today()
    fired = mechanisms_fired(d)
    items: list[dict[str, Any]] = []
    for a in assumptions.list_assumptions():
        exercised = sorted(set(a["exercised_by"]) & fired)
        broken = isinstance(a["value"], str) and a["value"].startswith("ERROR: ")
        if not broken and a.get("kind") not in OUTPUT_KINDS:
            continue   # an operational default (concurrency, ETA, lookahead) changes speed, not what the user knows
        age = _age_days(a.get("measured_on"), today)
        if broken:
            reason, kind = "the ledger can no longer resolve this constant -- the code moved; what was measured is not what runs", "unresolvable"
        elif exercised and not a["measured"]:
            reason, kind = f"tonight's {', '.join(exercised)} depended on it and it has never been measured against your data", "unmeasured_exercised"
        elif exercised and age is not None and age > STALE_DAYS:
            reason, kind = f"tonight's {', '.join(exercised)} depended on it and its measurement is {age} days old", "stale_exercised"
        else:
            continue
        items.append({"name": a["name"], "value": a["value"], "kind": kind, "why_now": reason,
                      "exercised_by": exercised, "why": a["why"], "how_to_verify": a["how_to_verify"],
                      "measured_on": a.get("measured_on")})
    order = {"unresolvable": 0, "unmeasured_exercised": 1, "stale_exercised": 2}
    items.sort(key=lambda x: (order[x["kind"]], x["name"]))
    return {"mechanisms_fired": sorted(fired), "items": items, "stale_days": STALE_DAYS}


def render_lines(t6: dict[str, Any]) -> list[str]:
    """Morning-Report lines. Empty when there is nothing to say -- that is the normal case and must stay short."""
    items = t6.get("items") or []
    if not items:
        return []
    shown, rest = items[:MAX_LINES], items[MAX_LINES:]
    out = [f"  Numbers tonight leaned on that nobody has checked against your data ({len(items)}):"]
    for x in shown:
        out.append(f"    - {x['name']} = {x['value']!r}: {x['why_now']}")
    if rest:
        out.append(f"    - and {len(rest)} more (`neurosearch nightly report --json`, then `assumptions.items`)")
    return out
