"""AD4B (docs/KYLE-GATES-2026-09-15.md): does the relevance filter actually cost Kyle anything?

The gate's own discover-report says plainly that its numbers are "NOT a comparison against static ranking, which
was never shown to the user and cannot be reconstructed from current state." Kyle's answer to it was conditional
-- "fine as long as I am not missing out on potentially novel or insightful findings" -- which is an open
question, not a close. This is the smallest thing that answers it.

WHAT THE REVIEW CARD ACTUALLY DOES (checked 2026-09-20 in web/js/sources.js and db.proposed_sources, because the
first version of this plan assumed otherwise): every proposed item is SHOWN, sorted by relevance. The score does
not hide anything -- it decides which rows arrive PRE-TICKED. Bulk-approving accepts the pre-tick. So the 9,691
`skipped_low_relevance` candidates in Kyle's acquisition project were on screen, unticked, and never scrolled to.

That makes the honest question: when Kyle actually looks, deliberately, at what the algorithm did not pre-tick,
how often does he want it? This draws a stratified sample of those rejected candidates, strips the score and the
model's verdict out of the reviewable part, and writes a rubric he fills in blind -- exactly the shape of
tools/sample_findings.py (L-05). tools/ad4b_score.py reads it back against the hidden key.

Blind matters here specifically because Kyle bulk-approves: shown the score, he would agree with the score.

Costs nothing (no model calls, reads only) and runs against the EXISTING backlog, so there is no waiting.

Run ON THE MAC:

    .venv/bin/python tools/ad4b_blind_sample.py --project <id> --out evals/ad4b-sample-<date>.json

Then open the JSON and, for each item under "review_these", set review.keep true or false -- would you want this
in the project? -- and review.why (one short line). Judge from the title, description, creator, duration and date
only: that is all the ranker saw. The scores and verdicts are under "_scoring_key" at the bottom; it is blind
only if you do not scroll there first.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

BANDS = ((0, 19), (20, 34), (35, 44), (45, 49))    # the four rejection bands; 45-49 is the "one point under" cliff


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def _band(score: int) -> str:
    for lo, hi in BANDS:
        if lo <= score <= hi:
            return f"{lo}-{hi}"
    return "other"


def build_sample(conn, project_id: str, per_band: int, seed: int) -> dict:
    rows = conn.execute(
        """SELECT cp.candidate_id cid, cp.relevance rel, cp.relevance_why why, cp.state st,
                  c.title, c.description, c.creator, c.duration, c.published_at, c.url, c.content_type
           FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id
           WHERE cp.project_id=? AND cp.state='skipped_low_relevance' AND cp.relevance IS NOT NULL""",
        (project_id,)).fetchall()
    if not rows:
        sys.exit(f"no scored skipped_low_relevance candidates in project {project_id} — nothing to sample")

    by_band: dict[str, list] = {}
    for r in rows:
        by_band.setdefault(_band(int(r["rel"])), []).append(r)

    rng = random.Random(seed)
    picked = []
    for band in sorted(by_band):
        pool = sorted(by_band[band], key=lambda r: r["cid"])      # deterministic order before the seeded shuffle
        rng.shuffle(pool)
        picked.extend((band, r) for r in pool[:per_band])
    rng.shuffle(picked)                                            # bands interleaved, so order leaks no score

    review, key = [], []
    for i, (band, r) in enumerate(picked, start=1):
        dur = int(r["duration"] or 0)
        review.append({
            "item": i,
            # exactly what the ranker saw, and nothing else
            "title": r["title"],
            "creator": r["creator"],
            "description": (r["description"] or "")[:600],
            "length": f"{dur // 60}m" if dur else None,
            "published": r["published_at"],
            "kind": r["content_type"],
            "review": {"keep": None, "why": ""},
        })
        key.append({"item": i, "candidate_id": r["cid"], "score": int(r["rel"]), "band": band,
                    "model_said": r["why"], "url": r["url"], "creator": r["creator"]})

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_id": project_id,
        "question": "For each item: would you want this in the project? Judge ONLY from what is shown — title, "
                    "creator, description, length, date. That is all the relevance ranker saw. Set review.keep to "
                    "true or false and add one line in review.why. Do not scroll to _scoring_key until you are done.",
        "population": {"total_rejected_and_scored": len(rows),
                       "by_band": {b: len(v) for b, v in sorted(by_band.items())}},
        "sampling": {"per_band": per_band, "seed": seed, "sampled": len(review)},
        "review_these": review,
        "_scoring_key": key,
    }


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="project id (see `neurosearch project list`)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--per-band", type=int, default=10, help="items per rejection band (4 bands; default 10 = 40 items)")
    ap.add_argument("--seed", type=int, default=44, help="fixed by default so the file is reproducible")
    ap.add_argument("--html", action="store_true",
                    help="also write a ready-to-open review page beside --out, with the rubric already inside it "
                         "(no file to load: just open it)")
    args = ap.parse_args()

    from neurosearch import db
    if not db.get_project(args.project):
        sys.exit(f"no project {args.project}")
    report = build_sample(db.connect(), args.project, args.per_band, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    pop = report["population"]
    print(f"{pop['total_rejected_and_scored']} rejected+scored candidates in this project")
    print("  by band: " + ", ".join(f"{b}: {n}" for b, n in pop["by_band"].items()))
    print(f"sampled {report['sampling']['sampled']} of them (blind) -> {args.out}")

    if args.html:
        page = Path(__file__).resolve().parent / "ad4b_review.html"
        if not page.exists():
            sys.exit(f"--html needs {page}, which is missing")
        shell = page.read_text()
        # "</script" inside the payload would close the tag early; "<" escaped is still valid JSON
        payload = json.dumps(report).replace("<", "\\u003c")
        tag = f'<script id="embedded" type="application/json">{payload}</script>\n'
        close = "</" + "body>"
        if close not in shell:
            sys.exit(f"ad4b_review.html has no {close} to inject before")
        # inject at the LAST occurrence: the page's own script text may mention the tag in a comment, and
        # splicing at the first match would drop the payload into the middle of the JavaScript (it did, once)
        head, _, rest = shell.rpartition(close)
        out_html = args.out.with_suffix(".html")
        out_html.write_text(head + tag + rest)
        print(f"ready-to-open review page   -> {out_html}")
        print(f"\n  open \"{out_html.resolve()}\"\n")
        print("Judge every item, and the page shows the result when you finish. To record it with the canonical")
        print("scorer, download the filled rubric from the page and run:")
        print("  .venv/bin/python tools/ad4b_score.py --in <the downloaded file>")
    else:
        print("\nOpen that file, fill in review.keep (true/false) and review.why for each item under 'review_these',")
        print("then run:  .venv/bin/python tools/ad4b_score.py --in " + str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
