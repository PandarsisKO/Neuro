"""L-05 (EXECUTION-LADDER.md): the smallest review that could CONTRADICT the SHIPPED-PROVISIONAL Haiku default
(rulings §5). Draws a stratified, model-blind sample of exactly 40 findings from the 8 real E5 sources (4 run on
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
E5_COHORT = (
    ("21274fb9125848cfa58e06517adc3ce1", "claude-sonnet-5"),
    ("1c309a3c978846ef8e9d2c14f53716c4", "claude-sonnet-5"),
    ("77311b566b8342018a61153036597475", "claude-sonnet-5"),
    ("8899039e74304275bffecc2396e150d1", "claude-sonnet-5"),
    ("6d5f072cf3ca46d899b4b0f9e851444e", "claude-haiku-4-5"),
    ("b76454d32f0441ac9d0901c8bb2687db", "claude-haiku-4-5"),
    ("3b6b9cc84b334248b6d0fb34e01a0555", "claude-haiku-4-5"),
    ("1bba2517c73a46308749bcdf3263ea4d", "claude-haiku-4-5"),
)


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def _importance_stratified(rows: list[dict], count: int) -> list[dict]:
    """Pick evenly across a source's importance-ranked findings, deterministically."""
    if len(rows) < count:
        raise ValueError(f"has only {len(rows)} modeled findings; need {count}")
    if count == 1:
        return rows[:1]
    return [rows[i * (len(rows) - 1) // (count - 1)] for i in range(count)]


def build_sample(conn, *, per_source: int = PER_SOURCE, seed: int = 53) -> dict:
    """Build the fixed E5 cohort without writing to the database or filesystem."""
    if per_source < 1:
        raise ValueError("--per-source must be at least 1")

    picked: list[dict] = []
    for source_id, model in E5_COHORT:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, content, citations, importance, model, title FROM project_notes "
            "WHERE project_id=? AND source_id=? AND model=? "
            "ORDER BY importance DESC NULLS LAST, id", (PROJECT_ID, source_id, model)
        ).fetchall()]
        try:
            selected = _importance_stratified(rows, per_source)
        except ValueError as exc:
            raise ValueError(f"E5 source {source_id} ({model}) {exc}") from exc
        for r in selected:
            picked.append({
                "note_id": r["id"], "source_id": source_id, "model": model,
                "importance": r["importance"], "title": r["title"], "content": r["content"],
                "citations": json.loads(r["citations"]) if r["citations"] else None,
            })

    rng = random.Random(seed)
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

    models = sorted({model for _, model in E5_COHORT})
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project_id": PROJECT_ID,
        "cohort": {"sources": [{"source_id": source_id, "model": model} for source_id, model in E5_COHORT]},
        "instructions": (
            "For each item in review_these: read the finding, then set review.accurate (true if it faithfully "
            "represents its source), review.keep (true if you would actually keep it -- the real kept-rate "
            "signal), and review.why_not (one short line, only when keep is false). Do not look at "
            "_scoring_key until you are done with every item -- it names the model and would un-blind the "
            f"review. {len(review_these)} items from the fixed {len(E5_COHORT)}-source E5 cohort, "
            f"{per_source} importance-stratified findings per source."
        ),
        "n_items": len(review_these),
        "n_sources": len(E5_COHORT),
        "models_present": models,
        "review_these": review_these,
        "_scoring_key": scoring_key,
    }


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--per-source", type=int, default=PER_SOURCE)
    ap.add_argument("--seed", type=int, default=53, help="shuffle seed, fixed by default so the file is reproducible")
    args = ap.parse_args()

    from neurosearch import db
    conn = db.connect()

    try:
        out = build_sample(conn, per_source=args.per_source, seed=args.seed)
    except ValueError as exc:
        sys.exit(f"REFUSING: {exc}. Has the E5 cohort changed?")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1))
    print(f"wrote {out['n_items']} items across {out['n_sources']} E5 sources ({', '.join(out['models_present'])}) -> {args.out}")
    print("next: open the file, fill in every review block, save, then hand it to L-07.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
