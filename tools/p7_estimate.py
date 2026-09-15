"""L-70 prep (EXECUTION-LADDER.md Stage 9, P7 Structured Delta experiment): the ladder says `kyle-decides` on the
dollar estimate and "state it first". This states it -- $0, read-only, no provider call -- so the decision Kyle
owes is a number he can look at, not one he has to go and produce.

    .venv/bin/python tools/p7_estimate.py --project "<name or id>" [--n 20] [--out evals/p7-estimate-<date>.json]

Selection: the ~N longest sources in the project (duration, else transcript characters), at most --per-platform
from any one platform so the set is varied, never one already excluded. Arm A is priced exactly the way the app
prices any findings pass (`usage.estimate_source_findings`, the same figure the stale triage quotes). Arm B has no
contract yet -- there is nothing real to price -- so it is stated as an explicit ASSUMPTION: the same input as Arm
A with twice the output allowance (a structured analysis writes more than a findings list), labelled as such in
the output. Nothing here is a measurement of Arm B; it is the number the experiment asks Kyle to authorise
before Arm B exists. L-70 itself still needs L-07 first (the ladder's own dependency) and Kyle's yes on this $."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ARM_B_OUTPUT_FACTOR = 2.0   # ASSUMPTION, stated in the output -- not measured, there is no Arm B contract to measure


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def select_sources(project_id: str, n: int, per_platform: int) -> list[dict[str, Any]]:
    from neurosearch import db
    conn = db.connect()
    rows = conn.execute(
        """SELECT s.id, s.title, s.platform, s.duration,
                  (SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id=s.id) AS chars
           FROM sources s JOIN project_sources ps ON ps.source_id=s.id
           WHERE ps.project_id=? AND ps.excluded=0 AND s.status='ready'
           ORDER BY COALESCE(s.duration, 0) DESC, chars DESC""", (project_id,)).fetchall()
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for r in rows:
        if seen.get(r["platform"], 0) >= per_platform:
            continue
        seen[r["platform"]] = seen.get(r["platform"], 0) + 1
        out.append({"source_id": r["id"], "title": r["title"], "platform": r["platform"], "duration": r["duration"], "chars": int(r["chars"] or 0)})
        if len(out) >= n:
            break
    return out


def estimate(project_id: str, n: int = 20, per_platform: int = 8) -> dict[str, Any]:
    from neurosearch import usage
    from neurosearch.contracts import contract
    sources = select_sources(project_id, n, per_platform)
    c = contract("findings.extract")
    _, pout = usage._price(c.model)
    extra_out_per_source = (ARM_B_OUTPUT_FACTOR - 1.0) * c.max_output_tokens / 1e6 * pout
    arm_a = 0.0
    for s in sources:
        est = usage.estimate_source_findings(s["source_id"])
        s["arm_a_usd"] = round(est, 4)
        s["arm_b_usd_assumed"] = round(est + extra_out_per_source, 4)
        arm_a += est
    arm_b = arm_a + extra_out_per_source * len(sources)
    return {
        "project_id": project_id, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_sources": len(sources), "sources": sources,
        "arm_a_usd": round(arm_a, 2), "arm_b_usd_assumed": round(arm_b, 2), "total_usd_assumed": round(arm_a + arm_b, 2),
        "arm_a_basis": f"usage.estimate_source_findings per source ({c.model}, the figure the stale triage quotes)",
        "arm_b_basis": f"ASSUMPTION: Arm A input with {ARM_B_OUTPUT_FACTOR:.0f}x the output allowance ({c.max_output_tokens} -> "
                       f"{int(c.max_output_tokens * ARM_B_OUTPUT_FACTOR)} tokens at ${pout}/M). No Arm B contract exists to measure.",
        "note": "Arm A sources that are already current would be re-read for the experiment (both arms must see the same input); "
                "the batch transport would roughly halve both numbers.",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--per-platform", type=int, default=8)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    _refuse_bridge_mount()
    from neurosearch import db
    db.init_db()
    p = db.get_project(args.project) or next((x for x in db.list_projects() if x["name"] == args.project), None)
    if not p:
        print(f"no project matches {args.project!r}", file=sys.stderr)
        return 1
    r = estimate(p["id"], args.n, args.per_platform)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(r, indent=1))
    print(f"P7 estimate for {p['name']!r}: {r['n_sources']} sources · Arm A ${r['arm_a_usd']:.2f} (priced) · "
          f"Arm B ${r['arm_b_usd_assumed']:.2f} (ASSUMED, see arm_b_basis) · total ${r['total_usd_assumed']:.2f}"
          + (f" -> {args.out}" if args.out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
