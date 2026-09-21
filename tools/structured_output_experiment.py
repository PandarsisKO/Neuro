"""Item 15 (Kyle's decision session, 2026-09-20) -- "a possible future experiment testing a different way of
extracting findings from sources." Turns out both ways already exist in the codebase, so nothing needed
building: this just runs a real, real-money, side-by-side test between them.

    structured (current default): providers.invoke_structured() -- provider-enforced JSON schema (findings-v2),
        full local schema validation, no free-text parsing at all.
    legacy (pre-Mission-F, currently only reachable via NEUROSEARCH_SCHEMA_COMPAT_FALLBACK, marked "emergency
        fallback only" in findings.py's own docstring): providers.invoke() -- the model free-generates, then
        findings._legacy_parse() regex-extracts the first {...} block and json.loads()s it.

Same model, same system+user prompt, same source, only the output contract differs. Question: does the strict
format actually produce better findings, or is "emergency fallback only" leaving something on the table?

Deliberately narrow and NON-DESTRUCTIVE:
  - each selected source's FIRST transcript window ONLY (bounds cost to what was estimated to Kyle -- this is a
    method comparison, not a full re-extraction of anyone's library)
  - never calls findings.materialize() -- nothing is written to findings/claims/evidence_targets/notes, only
    this script's own --out report file and the real usage ledger (so Kyle's cost dashboard is accurate)
  - usage is recorded under "findings_experiment_structured" / "findings_experiment_legacy", never bare
    "findings", so this run can never be mistaken for production extraction by decide_kept_rate.py or any other
    E5-style cohort tool
  - a running-total budget guard aborts BEFORE the next call if it would push projected spend past --budget

Run ON THE MAC (this calls the real model provider, real money):

    .venv/bin/python tools/structured_output_experiment.py --project <id> [--n 20] [--budget 10] [--out evals/...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def _select_sources(project_id: str, n: int) -> list[dict]:
    """Varied long sources: round-robin across whatever platforms are present (longest-first within each), so
    a 20-source sample isn't just 20 videos from one channel."""
    from neurosearch import db, findings
    by_platform: dict[str, list[dict]] = defaultdict(list)
    for sid in db.project_source_ids(project_id, ready_only=True):
        src = db.get_source(sid)
        if not src:
            continue
        segs = db.get_segments(sid)
        if not segs:
            continue
        if findings.is_long(src, len(segs)):
            by_platform[src.get("platform") or "unknown"].append(src)
    for bucket in by_platform.values():
        bucket.sort(key=lambda s: s.get("duration") or 0, reverse=True)
    platforms = list(by_platform.keys())
    selected: list[dict] = []
    i = 0
    while len(selected) < n and any(by_platform[p] for p in platforms):
        p = platforms[i % len(platforms)]
        if by_platform[p]:
            selected.append(by_platform[p].pop(0))
        i += 1
    return selected[:n]


def _first_window(project_id: str, source_id: str) -> dict | None:
    from neurosearch import findings
    reqs = findings.canonical_requests(project_id, source_id)
    if not reqs:
        return None
    r = reqs[0]
    return {"system": r["system"], "messages": r["messages"], "window_text": r["messages"][0]["content"]}


def _verified_rate(items: list[dict], window_text: str) -> tuple[int, int]:
    from neurosearch.evidence import evidence_for
    ok = 0
    for f in items:
        v = evidence_for(f, window_text, None)
        if v.get("ok"):
            ok += 1
    return ok, len(items)


def _run_structured(system, messages, project_id, source_id, window_text) -> dict:
    from neurosearch import providers, usage
    from neurosearch import findings as findings_mod
    user_chars = len(messages[0]["content"])
    est = usage.estimate_findings(user_chars)
    t0 = time.time()
    try:
        out = providers.invoke_structured("findings.extract", system=system, messages=messages,
                                          usage_kind="findings_experiment_structured", project_id=project_id,
                                          source_id=source_id, guard_estimate=est, legacy=findings_mod._legacy_parse)
        findings_list = out.get("findings") or []
        ok_quotes, n = _verified_rate(findings_list, window_text)
        return {"ok": True, "error": None, "n_findings": len(findings_list), "substance": out.get("substance"),
                "verified_quotes": ok_quotes, "elapsed_s": round(time.time() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "n_findings": 0, "substance": None,
                "verified_quotes": 0, "elapsed_s": round(time.time() - t0, 2)}


def _run_legacy(system, messages, project_id, source_id, window_text) -> dict:
    from neurosearch import providers, usage
    from neurosearch import findings as findings_mod
    user_chars = len(messages[0]["content"])
    est = usage.estimate_findings(user_chars)
    usage.guard(est)
    t0 = time.time()
    resp = providers.invoke("findings.extract", system=system, messages=messages)
    usage.record_anthropic(resp, "findings_experiment_legacy", project_id=project_id, source_id=source_id)
    raw = providers.text_of(resp).strip()
    parsed = findings_mod._legacy_parse(raw)
    findings_list = parsed.get("findings") or []
    ok_quotes, n = _verified_rate(findings_list, window_text) if findings_list else (0, 0)
    parse_ok = bool(parsed) and "findings" in parsed
    return {"ok": parse_ok, "error": None if parse_ok else "unparseable or missing 'findings' key",
            "n_findings": len(findings_list), "substance": parsed.get("substance"),
            "verified_quotes": ok_quotes, "elapsed_s": round(time.time() - t0, 2), "raw_len": len(raw)}


def main() -> None:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--budget", type=float, default=10.0, help="hard USD ceiling for this run -- aborts before the next call if projected spend would exceed it")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from neurosearch import db, usage
    from neurosearch.config import settings  # noqa: F401  (ensures .env is loaded before any provider call)

    sources = _select_sources(args.project, args.n)
    if not sources:
        sys.exit(f"REFUSING: no long, ready sources found in project {args.project}.")

    print(f"selected {len(sources)} sources across platforms: "
          f"{sorted(set(s.get('platform') for s in sources))}")

    spent = 0.0
    results = []
    for i, src in enumerate(sources):
        win = _first_window(args.project, src["id"])
        if not win:
            results.append({"source_id": src["id"], "title": src.get("title"), "skipped": "no transcript window"})
            continue
        est_per_call = usage.estimate_findings(len(win["messages"][0]["content"]))
        if spent + est_per_call * 2 > args.budget:
            print(f"stopping at {i}/{len(sources)} sources -- next pair (~${est_per_call*2:.3f}) would exceed --budget ${args.budget:.2f} (spent so far ${spent:.3f})")
            break

        structured = _run_structured(win["system"], win["messages"], args.project, src["id"], win["window_text"])
        legacy = _run_legacy(win["system"], win["messages"], args.project, src["id"], win["window_text"])

        row = {"source_id": src["id"], "title": src.get("title"), "platform": src.get("platform"),
               "duration_s": src.get("duration"), "structured": structured, "legacy": legacy}
        results.append(row)
        spent = float(db.connect().execute(
            "SELECT COALESCE(SUM(cost),0) FROM usage WHERE kind IN ('findings_experiment_structured','findings_experiment_legacy')").fetchone()[0])
        print(f"[{i+1}/{len(sources)}] {src.get('title','')[:60]!r}: "
              f"structured findings={structured['n_findings']} verified={structured['verified_quotes']} ok={structured['ok']} | "
              f"legacy findings={legacy['n_findings']} verified={legacy['verified_quotes']} ok={legacy['ok']} "
              f"-- running spend ${spent:.3f}")

    done = [r for r in results if "structured" in r]
    n = len(done)
    summary = {
        "n_sources_compared": n,
        "total_spend_usd": round(spent, 4),
        "structured": {
            "parse_success_rate": round(sum(1 for r in done if r["structured"]["ok"]) / n, 3) if n else None,
            "mean_findings_per_window": round(sum(r["structured"]["n_findings"] for r in done) / n, 2) if n else None,
            "mean_verified_quotes": round(sum(r["structured"]["verified_quotes"] for r in done) / n, 2) if n else None,
        },
        "legacy": {
            "parse_success_rate": round(sum(1 for r in done if r["legacy"]["ok"]) / n, 3) if n else None,
            "mean_findings_per_window": round(sum(r["legacy"]["n_findings"] for r in done) / n, 2) if n else None,
            "mean_verified_quotes": round(sum(r["legacy"]["verified_quotes"] for r in done) / n, 2) if n else None,
        },
    }
    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "project_id": args.project, "summary": summary, "rows": results}
    out_path = Path(args.out) if args.out else Path(f"evals/structured-vs-legacy-{time.strftime('%Y-%m-%d')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"full report -> {out_path}")


if __name__ == "__main__":
    main()
