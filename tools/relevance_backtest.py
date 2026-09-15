"""L-08 (EXECUTION-LADDER.md): does a brief-text embedding rank sources better than the T4 selector's current
Claim-centroid basis (`t4.source_relevance`, docstring's own note: "A brief-text embedding is the better
long-term basis... once the embedding provider is reachable from the executing process")?

Deliberately kept OUT of neurosearch/t4.py: that module documents itself as "no provider call" (its own module
docstring, first paragraph) and every one of its callers relies on that being true. This script makes exactly
one provider call per project (the brief, embedded once, cached in kv by brief_revision so a re-run is free)
and never touches t4.py, production ranking, or any write path except that one cache row.

Run ON THE MAC (needs OPENAI_API_KEY / a reachable embedding provider -- not available from the sandbox bridge):

    .venv/bin/python tools/relevance_backtest.py --project <id> [--project <id> ...]
    .venv/bin/python tools/relevance_backtest.py --project c752ed152ec942dd97b9a94c3f1b3b96

Cost: one embedding call per NEW (project, brief-revision) pair, cached after that -- a few cents at most across
the whole backtest set (OpenAI text-embedding pricing, one short brief per project). Reports, per project and
overall: Spearman correlation between the current centroid basis and the candidate max(centroid-sim, brief-sim)
basis, and how many of the top-5-by-centroid sources the candidate would have reordered. Writes nothing back to
the database except the brief-embedding cache row; makes NO decision and flips NO switch -- L-08's own gate says
"switch the ranking basis ONLY if the backtest improves... without regressing", which is Kyle's or my call to
make by reading this script's report, not this script's to decide.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _brief_vector(project: dict, provider: str, model: str, dims: int) -> np.ndarray | None:
    from neurosearch import db
    brief = (project.get("brief") or "").strip()
    if not brief or provider != "openai":
        return None
    rev = db.brief_revision(project)
    key = f"t4_brief_embedding_v1:{project['id']}:{rev}:{model}:{dims}"
    cached = db.kv_get(key)
    if cached is not None:
        try:
            arr = np.array(json.loads(cached), dtype=np.float32)
            if arr.size == dims:
                return arr
        except (ValueError, TypeError):
            pass
    from neurosearch import embeddings
    vec = embeddings.embed_query(brief)
    if vec.size != dims:
        return None
    db.kv_set(key, json.dumps(vec.tolist()))
    return vec


def backtest_one(project_id: str) -> dict:
    from neurosearch import db, t1, t4

    project = db.get_project(project_id)
    if not project:
        return {"project_id": project_id, "status": "no_such_project"}

    centroid_rel = t4.source_relevance(project_id)
    if centroid_rel["status"] != "measured" or not centroid_rel["scores"]:
        return {"project_id": project_id, "status": "centroid_unavailable", "reason": centroid_rel.get("reason")}

    att = t1.get_chunk_space_attestation()
    provider, model, dims = att.get("provider"), att.get("model"), int(att.get("dimensions") or 0)
    brief_vec = _brief_vector(project, provider, model, dims)
    if brief_vec is None:
        return {"project_id": project_id, "status": "no_brief_or_unsupported_provider", "provider": provider}
    bnorm = float(np.linalg.norm(brief_vec))
    if not np.isfinite(bnorm) or bnorm == 0.0:
        return {"project_id": project_id, "status": "brief_vector_degenerate"}
    brief_vec = brief_vec / bnorm

    conn = db.connect()
    rows = conn.execute("""SELECT c.source_id, c.embedding FROM chunks c
                           JOIN project_sources ps ON ps.source_id = c.source_id
                           WHERE ps.project_id=? AND c.embedding IS NOT NULL""", (project_id,)).fetchall()
    vecsum: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    for r in rows:
        sid = r["source_id"]
        try:
            vec = db._unpack(r["embedding"])
            if vec.size != dims or not np.isfinite(vec).all():
                continue
        except (TypeError, ValueError):
            continue
        vecsum[sid] = vecsum.get(sid, np.zeros(dims, dtype=np.float32)) + vec
        counts[sid] = counts.get(sid, 0) + 1
    mean_vecs = {sid: vecsum[sid] / counts[sid] for sid in counts}

    centroid_scores = centroid_rel["scores"]
    brief_scores = {sid: float(v @ brief_vec) for sid, v in mean_vecs.items() if sid in centroid_scores}
    candidate_scores = {sid: max(centroid_scores[sid], brief_scores.get(sid, centroid_scores[sid])) for sid in centroid_scores}

    ranked_ids = sorted(centroid_scores, key=lambda s: -centroid_scores[s])
    top5_current = set(ranked_ids[:5])
    ranked_candidate = sorted(candidate_scores, key=lambda s: -candidate_scores[s])
    top5_candidate = set(ranked_candidate[:5])

    common = [sid for sid in centroid_scores if sid in brief_scores]
    rho = _spearman([centroid_scores[s] for s in common], [candidate_scores[s] for s in common])

    return {
        "project_id": project_id, "status": "ok", "n_sources": len(centroid_scores),
        "spearman_centroid_vs_candidate": rho,
        "top5_unchanged": sorted(top5_current & top5_candidate),
        "top5_reordered_in": sorted(top5_candidate - top5_current),
        "top5_reordered_out": sorted(top5_current - top5_candidate),
    }


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", action="append", required=True, dest="projects")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    results = [backtest_one(pid) for pid in args.projects]
    ok = [r for r in results if r["status"] == "ok"]
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "n_projects": len(results), "n_ok": len(ok),
        "results": results,
        "verdict": (
            "NO DATA -- nothing measured" if not ok else
            "candidate basis looks like an improvement (reorders the top-5, positive correlation with current "
            "ranking, no red flags) -- worth a closer read before switching" if all(
                (r["spearman_centroid_vs_candidate"] or 0) > 0.3 for r in ok
            ) and any(r["top5_reordered_in"] for r in ok) else
            "no clear case to switch from the current basis on this data -- see per-project detail"
        ),
    }
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
        print(f"wrote {args.out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
