"""L-07 (EXECUTION-LADDER.md Stage 2, P5.3 decision): turn Kyle's filled-in kept-rate sample (L-06, produced by
tools/sample_findings.py) into the decision the T4 plan's E5 rule prescribes -- so the moment the review JSON is
saved, the decision is one command and one paragraph, not an afternoon.

    .venv/bin/python tools/decide_kept_rate.py --sample evals/p53-sample-<date>.json

Rule (T4 plan E5, unchanged): Haiku stays the default ONLY if its cost per KEPT finding is lower than Sonnet's AND
its kept rate is within 10 points of Sonnet's. Otherwise revert the `.env` line and say so.

Cost per finding by model comes from the app's own ledger (`usage` rows of kind 'findings' by model, divided by
the findings each model wrote for the fixed sources in this sample) when run on the Mac; pass `--cost-per-finding
claude-haiku-4-5=0.011,claude-sonnet-5=0.021` to run it anywhere from stated numbers (e.g. the ones in
docs/T4-ADMISSION-2026-09-14.md). The script never changes a finding, a status, or `.env`; it prints the
decision and the numbers behind it, and exits 3 when the review is incomplete rather than deciding on a partial
sample."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

WITHIN_POINTS = 10.0


def score(sample: dict[str, Any], cost_per_finding: dict[str, float]) -> dict[str, Any]:
    key = sample["_scoring_key"]
    per_model: dict[str, dict[str, Any]] = {}
    incomplete = 0
    for item in sample["review_these"]:
        k = key[str(item["sample_id"])]
        r = item.get("review") or {}
        if r.get("keep") is None or r.get("accurate") is None:
            incomplete += 1
            continue
        m = per_model.setdefault(k["model"], {"n": 0, "kept": 0, "accurate": 0, "why_not": []})
        m["n"] += 1
        m["kept"] += 1 if r["keep"] else 0
        m["accurate"] += 1 if r["accurate"] else 0
        if not r["keep"] and r.get("why_not"):
            m["why_not"].append(str(r["why_not"]))
    for model, m in per_model.items():
        m["kept_rate"] = round(100.0 * m["kept"] / m["n"], 1) if m["n"] else None
        m["accurate_rate"] = round(100.0 * m["accurate"] / m["n"], 1) if m["n"] else None
        cpf = cost_per_finding.get(model)
        m["cost_per_finding"] = cpf
        m["cost_per_kept"] = round(cpf / (m["kept"] / m["n"]), 4) if cpf is not None and m["kept"] else None
    return {"per_model": per_model, "incomplete": incomplete, "n_reviewed": sum(m["n"] for m in per_model.values())}


def _resolve_model_key(alias: str, pm: dict[str, Any]) -> str | None:
    """2026-09-20: `per_model` is keyed by whatever exact model string the provider actually stamped on the
    finding (e.g. "claude-haiku-4-5-20251001", a dated snapshot id) -- not necessarily the bare alias a caller
    passes in. An exact match wins; otherwise, if exactly one key starts with the alias, that's the same model
    under its dated name. Ambiguous (more than one match) or no match at all -> None, so the caller reports
    undecidable rather than silently picking the wrong one."""
    if alias in pm:
        return alias
    matches = [k for k in pm if k.startswith(alias)]
    return matches[0] if len(matches) == 1 else None


def decide(scored: dict[str, Any], haiku: str, sonnet: str) -> dict[str, Any]:
    pm = scored["per_model"]
    haiku_key, sonnet_key = _resolve_model_key(haiku, pm), _resolve_model_key(sonnet, pm)
    if haiku_key is None or sonnet_key is None:
        return {"decision": "undecidable", "reason": f"need both {haiku} and {sonnet} (or a dated variant of each) in the reviewed sample; have {sorted(pm)}"}
    h, s = pm[haiku_key], pm[sonnet_key]
    if h["cost_per_kept"] is None or s["cost_per_kept"] is None:
        return {"decision": "undecidable", "reason": "cost per kept finding unavailable for at least one model (no cost data, or zero kept)"}
    cheaper = h["cost_per_kept"] < s["cost_per_kept"]
    within = (s["kept_rate"] - h["kept_rate"]) <= WITHIN_POINTS
    keep_haiku = cheaper and within
    return {
        "decision": "keep Haiku as the findings default" if keep_haiku else "revert the .env line: Sonnet is the findings default",
        "haiku_cost_per_kept": h["cost_per_kept"], "sonnet_cost_per_kept": s["cost_per_kept"], "cheaper_per_kept": cheaper,
        "haiku_kept_rate": h["kept_rate"], "sonnet_kept_rate": s["kept_rate"], "gap_points": round(s["kept_rate"] - h["kept_rate"], 1),
        "within_10_points": within,
    }


def _cohort_by_model(sample: dict[str, Any]) -> dict[str, set[str]]:
    cohort = sample.get("cohort", {}).get("sources")
    if not isinstance(cohort, list):
        cohort = list(sample.get("_scoring_key", {}).values())
    out: dict[str, set[str]] = {}
    for item in cohort:
        model, source_id = item.get("model"), item.get("source_id")
        if not isinstance(model, str) or not isinstance(source_id, str):
            raise ValueError("sample cohort has a missing model or source_id")
        out.setdefault(model, set()).add(source_id)
    if not out:
        raise ValueError("sample has no source/model cohort")
    return out


def _costs_from_ledger(project_id: str, sample: dict[str, Any]) -> dict[str, float]:
    from neurosearch import db
    conn = db.connect()
    out: dict[str, float] = {}
    for model, source_ids in _cohort_by_model(sample).items():
        placeholders = ",".join("?" * len(source_ids))
        args = (project_id, model, *sorted(source_ids))
        cost = float(conn.execute(
            f"SELECT COALESCE(SUM(cost),0) c FROM usage WHERE project_id=? AND kind='findings' AND model=? "
            f"AND source_id IN ({placeholders})", args).fetchone()["c"])
        n = int(conn.execute(
            f"SELECT COUNT(*) n FROM project_notes WHERE project_id=? AND model=? AND source_id IN ({placeholders})", args
        ).fetchone()["n"])
        if n:
            out[model] = round(cost / n, 5)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True, type=Path)
    ap.add_argument("--cost-per-finding", default=None, help="model=usd,model=usd -- skip the ledger and use stated numbers")
    ap.add_argument("--haiku", default="claude-haiku-4-5")
    ap.add_argument("--sonnet", default="claude-sonnet-5")
    ap.add_argument("--allow-partial", action="store_true", help="decide on whatever is reviewed (default: refuse)")
    args = ap.parse_args(argv)
    sample = json.loads(args.sample.read_text())
    if args.cost_per_finding:
        costs = {k.strip(): float(v) for k, v in (kv.split("=") for kv in args.cost_per_finding.split(","))}
    else:
        try:
            costs = _costs_from_ledger(sample["project_id"], sample)
        except ValueError as exc:
            print(f"REFUSING: {exc}")
            return 3
    scored = score(sample, costs)
    if scored["incomplete"] and not args.allow_partial:
        print(f"REFUSING: {scored['incomplete']} of {sample['n_items']} items are not yet reviewed -- finish the review "
              f"(or pass --allow-partial to decide on {scored['n_reviewed']}).")
        return 3
    d = decide(scored, args.haiku, args.sonnet)
    print(json.dumps({"scored": scored, "decision": d}, indent=1))
    print()
    print(f"DECISION: {d['decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
