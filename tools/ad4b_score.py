"""AD4B, second half: read back the blind rubric from tools/ad4b_blind_sample.py and produce the number.

The number: of what the relevance filter rejected, what fraction would Kyle actually have kept? Everything else
here is that number cut by score band and by creator, plus a plain verdict on whether AD4B closes.

Reads the rubric file only (and the project, to name creators). Writes nothing anywhere. No model calls.

Run ON THE MAC:

    .venv/bin/python tools/ad4b_score.py --in evals/ad4b-sample-<date>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# Below this, the filter is doing its job and AD4B closes; above it, the filter is costing real material.
# Set here rather than argued after the fact, so the reading of the result is not retrofitted to the result.
CLOSE_BELOW = 0.10
ACT_ABOVE = 0.25


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, type=Path)
    args = ap.parse_args()

    report = json.loads(args.inp.read_text())
    review = {r["item"]: r for r in report["review_these"]}
    key = {k["item"]: k for k in report["_scoring_key"]}

    judged = {i: r for i, r in review.items() if isinstance(r.get("review", {}).get("keep"), bool)}
    missing = sorted(set(review) - set(judged))
    if not judged:
        sys.exit(f"nothing judged yet — set review.keep true/false on the items in {args.inp}")
    if missing:
        print(f"WARNING: {len(missing)} of {len(review)} items have no review.keep yet "
              f"(items {missing[:10]}{'…' if len(missing) > 10 else ''}) — reporting on the {len(judged)} judged.\n")

    kept = [i for i, r in judged.items() if r["review"]["keep"]]
    rate = len(kept) / len(judged)

    by_band: dict[str, list[bool]] = defaultdict(list)
    by_creator: dict[str, list[bool]] = defaultdict(list)
    for i, r in judged.items():
        k = key[i]
        by_band[k["band"]].append(bool(r["review"]["keep"]))
        by_creator[k.get("creator") or "(no creator)"].append(bool(r["review"]["keep"]))

    print(f"AD4B — blind review of what the relevance filter rejected ({report['project_id']})")
    print(f"population: {report['population']['total_rejected_and_scored']} rejected+scored candidates")
    print(f"judged:     {len(judged)} of {len(review)} sampled\n")
    print(f"HEADLINE: you would have kept {len(kept)} of {len(judged)} — {rate:.0%} of what the filter rejected\n")

    print("by score band (the band nearest the cutoff is the one that matters most):")
    for band in sorted(by_band, key=lambda b: -int(b.split("-")[0])):
        v = by_band[band]
        print(f"  {band:>6}: kept {sum(v)}/{len(v)} ({sum(v)/len(v):.0%})")

    multi = {c: v for c, v in by_creator.items() if len(v) >= 2}
    if multi:
        print("\nby creator (2+ items judged):")
        for c, v in sorted(multi.items(), key=lambda kv: (-sum(kv[1])/len(kv[1]), -len(kv[1]))):
            print(f"  {c}: kept {sum(v)}/{len(v)} ({sum(v)/len(v):.0%})")

    wanted = [(key[i].get("creator"), review[i]["title"], key[i]["score"], key[i].get("model_said"))
              for i in sorted(kept)]
    if wanted:
        print("\nwhat you would have kept, and what the model said about it:")
        for creator, title, score, said in wanted[:25]:
            print(f"  [{score:>2}] {(title or '')[:70]!r} — {creator or '?'} — model: {said or '(no reason)'}")
        if len(wanted) > 25:
            print(f"  … and {len(wanted) - 25} more")

    print("\nVERDICT")
    if rate < CLOSE_BELOW:
        print(f"  {rate:.0%} is below the {CLOSE_BELOW:.0%} bar set before this ran. The filter is not costing you")
        print("  meaningful material. AD4B closes: no experiment to build, no cutoff change warranted.")
    elif rate < ACT_ABOVE:
        print(f"  {rate:.0%} sits between the {CLOSE_BELOW:.0%} and {ACT_ABOVE:.0%} bars set before this ran — real")
        print("  but not alarming. Worth re-checking the band table: if the loss is concentrated in 45-49, widening")
        print("  the creator-trust nudge is the cheap fix; if it is spread evenly, the score itself is the problem.")
    else:
        print(f"  {rate:.0%} is above the {ACT_ABOVE:.0%} bar set before this ran. The filter is costing you real")
        print("  material and the cutoff or the scoring prompt should change — the band and creator tables say where.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
