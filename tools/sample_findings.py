"""L-05 (EXECUTION-LADDER.md): the smallest review that could CONTRADICT the SHIPPED-PROVISIONAL Haiku default
(rulings §5). Draws a stratified, model-blind sample of ~40 findings from the 8 real E5 sources (4 run on
claude-sonnet-5, 4 on claude-haiku-4-5 -- docs/T4-ADMISSION-2026-09-14.md "E5 prep") and writes a rubric Kyle
can fill in by hand in under 20 minutes.

Run ON THE MAC, app stopped or not -- this only READS project_notes, never writes:

    .venv/bin/python tools/sample_findings.py --out evals/p53-sample-<date>.json

Then Kyle opens the JSON, and for each item under "review_these" fills in review.accurate (true/false),
review.keep (true/false), and review.why_not (one line, only when keep is false). The model and source that
produced each finding are stored separately under "_scoring_key" at the bottom of the file -- reviewing is
blind to model ONLY if you don't scroll down there before finishing. L-07 reads review + _scoring_key back to
compute kept-rate and cost-per-kept per model.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

PROJECT_ID = "c752ed152ec942dd97b9a94c3f1b3b96"  # Kyle's business-acquisition project (E3-E5 throughout)
PER_SOURCE = 5


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--per-source", type=int, default=PER_SOURCE)
    ap.add_argument("--seed", type=int, default=53, help="shuffle seed, fixed by default so the file is reproducible")
    args = ap.parse_args()

    from neurosearch import db
    conn = db.connect()

    sources = [r["source_id"] for r in conn.execute(
        "SELECT DISTINCT source_id FROM project_notes WHERE project_id=? AND source_id IS NOT NULL "
        "AND model IS NOT NULL ORDER BY source_id", (PROJECT_ID,)
    ).fetchall()]
    if len(sources) < 2:
        sys.exit(f"REFUSING: found {len(sources)} distinct modeled source_id(s) for {PROJECT_ID} -- "
                  "expected the 8 E5 sources (4 Sonnet, 4 Haiku). Has the project changed?")

    picked: list[dict] = []
    for sid in sources:
        rows = conn.execute(
            "SELECT id, content, citations, importance, model, title FROM project_notes "
            "WHERE project_id=? AND source_id=? ORDER BY importance DESC NULLS LAST, id "
            "LIMIT ?", (PROJECT_ID, sid, args.per_source)
        ).fetchall()
        for r in rows:
            picked.append({
                "note_id": r["id"], "source_id": sid, "model": r["model"],
                "importance": r["importance"], "title": r["title"], "content": r["content"],
                "citations": json.loads(r["citations"]) if r["citations"] else None,
            })

    if not picked:
        sys.exit(f"REFUSING: zero findings matched for {PROJECT_ID} across {len(sources)} sources -- nothing to sample.")

    rng = random.Random(args.seed)
    rng.shuffle(picked)

    review_these = []
    scoring_key = {}
    for i, item in enumerate(picked, start=1):
        review_these.append({
            "sample_id": i,
            "title": item["title"],
            "content": item["content"],
            "citations": item["citations"],
            "review": {"accurate": None, "keep": None, "why_not": None},
        })
        scoring_key[str(i)] = {"note_id": item["note_id"], "source_id": item["source_id"], "model": item["model"]}

    models = sorted({v["model"] for v in scoring_key.values()})
    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_id": PROJECT_ID,
        "instructions": (
            "For each item in review_these: read the finding, then set review.accurate (true if it faithfully "
            "represents its source), review.keep (true if you would actually keep it -- the real kept-rate "
            "signal), and review.why_not (one short line, only when keep is false). Do not look at "
            "_scoring_key until you are done with every item -- it names the model and would un-blind the "
            f"review. {len(review_these)} items across {len(sources)} sources, ~{args.per_source} per source."
        ),
        "n_items": len(review_these),
        "n_sources": len(sources),
        "models_present": models,
        "review_these": review_these,
        "_scoring_key": scoring_key,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    print(f"wrote {len(review_these)} items across {len(sources)} sources ({', '.join(models)}) -> {args.out}")
    print("next: open the file, fill in every review block, save, then hand it to L-07.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
