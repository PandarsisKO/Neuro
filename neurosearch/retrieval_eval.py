"""Rung I1 — the hard retrieval eval (`neurosearch eval --retrieval`).

The Golden Project + tests/fixtures/golden/retrieval/ (four distractor sources; 30 queries graded per source AND per chunk
locator, with hard negatives). Retrieval is exactly production's `search.search` (FTS5 + vectors, reciprocal-rank fusion,
per-source cap): nothing here changes behaviour. For every query it records the top-10 hits (metrics) and the top-40
candidate set (the reranker experiment of I2 may only reorder these — never invent candidates).

Metrics: Recall@1/3/5/10 (first expected source), MRR, NDCG@10 (binary source relevance per hit), expected-source
mean/median first rank, locator accuracy (±120 s media / exact page; any hit in the top 10), exact-locator@first-hit
(the FIRST hit of an expected source is at the graded locator), hard-negative false positives (a hard-negative source
ranks above the first expected hit), candidate Recall@40, per-category breakdown, per-query detail.

Under NEUROSEARCH_FAKE_AI=1 the vectors are the fake's hashed lexical embeddings, so the fake baseline measures FTS +
lexical vectors; a live run costs only embeddings (no Anthropic calls).
"""
from __future__ import annotations

import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

from . import db
from .config import settings

HERE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"
RETRIEVAL_DIR = HERE / "retrieval"
CANDIDATES = 40
TOP_K = 10
TOLERANCE_S = 120


def load_fixture(project_id: str, golden_ids: dict[str, str]) -> dict[str, Any]:
    from . import ingest
    fx = json.loads((RETRIEVAL_DIR / "retrieval.json").read_text())
    ids = dict(golden_ids)
    was = settings.auto_suggest
    settings.auto_suggest = False
    try:
        for s in fx["sources"]:
            payload = json.loads((RETRIEVAL_DIR / s["file"]).read_text())
            payload.update({k: s.get(k) for k in ("platform", "external_id", "url", "title", "channel", "published_at")})
            payload["transcript_kind"] = "captions"
            ids[s["id"]] = ingest.store_transcript(payload, project_id=project_id)["source_id"]
    finally:
        settings.auto_suggest = was
    return {"ids": ids, "queries": fx["queries"], "version": fx["version"]}


def locator_ok(hit: dict[str, Any], want: Any) -> bool:
    try:
        if hit.get("platform") in ("document", "web", "spreadsheet"):
            return int(hit["start"]) == int(want)
        return abs(float(hit["start"]) - float(want)) <= TOLERANCE_S
    except (TypeError, ValueError):
        return False


def grade(hits: list[dict[str, Any]], expected: list[dict[str, Any]], hard_negatives: list[str], ids: dict[str, str], top_k: int = TOP_K) -> dict[str, Any]:
    """Grade one ranked list. `hits` may be longer than top_k (candidates); metrics use the first top_k."""
    want = {ids[e["source"]]: e for e in expected}
    neg = {ids[s] for s in hard_negatives}
    top = hits[:top_k]
    first = next((i for i, h in enumerate(top) if h["source_id"] in want), None)
    cand_rank = next((i for i, h in enumerate(hits) if h["source_id"] in want), None)
    rel = [1 if h["source_id"] in want else 0 for h in top]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rel))
    ideal = sorted(rel, reverse=True)
    n_ideal = min(len(top), max(1, sum(1 for h in hits if h["source_id"] in want)))
    idcg = sum(1 / math.log2(i + 2) for i in range(n_ideal))
    loc_total = loc_hits = exact_total = exact_hits = 0
    for e in expected:
        if "at" not in e:
            continue
        sid = ids[e["source"]]
        loc_total += 1
        loc_hits += any(h["source_id"] == sid and locator_ok(h, e["at"]) for h in top)
        first_of = next((h for h in top if h["source_id"] == sid), None)
        exact_total += 1
        exact_hits += bool(first_of and locator_ok(first_of, e["at"]))
    neg_above = [h["source_id"] for i, h in enumerate(top) if h["source_id"] in neg and (first is None or i < first)]
    return {"first_rank": first, "candidate_rank": cand_rank, "rr": 1 / (first + 1) if first is not None else 0.0, "ndcg": round(dcg / idcg, 4) if idcg else 0.0,
            "loc_total": loc_total, "loc_hits": loc_hits, "exact_total": exact_total, "exact_hits": exact_hits,
            "hard_negative_fp": len(set(neg_above)), "top": [(h["source_id"], h.get("start")) for h in top]}


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(rows))
    firsts = [r["first_rank"] for r in rows if r["first_rank"] is not None]
    out = {"queries": len(rows)}
    for k in (1, 3, 5, 10):
        out[f"recall_at_{k}"] = round(sum(1 for r in rows if r["first_rank"] is not None and r["first_rank"] < k) / n, 4)
    out["candidate_recall_at_40"] = round(sum(1 for r in rows if r["candidate_rank"] is not None) / n, 4)
    out["mrr"] = round(sum(r["rr"] for r in rows) / n, 4)
    out["ndcg_at_10"] = round(sum(r["ndcg"] for r in rows) / n, 4)
    out["mean_first_rank"] = round(sum(f + 1 for f in firsts) / len(firsts), 2) if firsts else None
    out["median_first_rank"] = statistics.median(f + 1 for f in firsts) if firsts else None
    lt, lh = sum(r["loc_total"] for r in rows), sum(r["loc_hits"] for r in rows)
    et, eh = sum(r["exact_total"] for r in rows), sum(r["exact_hits"] for r in rows)
    out["locator_accuracy"] = round(lh / lt, 4) if lt else None
    out["locator_exact_at_first_hit"] = round(eh / et, 4) if et else None
    out["locators"] = lt
    out["hard_negative_false_positives"] = sum(r["hard_negative_fp"] for r in rows)
    out["queries_with_hard_negative_above"] = sum(1 for r in rows if r["hard_negative_fp"])
    out["not_first"] = sum(1 for r in rows if r["first_rank"] not in (None, 0))
    return out


def run(progress: Any = print, search_fn: Any = None, label: str = "hybrid (FTS + vectors, RRF)") -> dict[str, Any]:
    """Run the fixture through `search_fn(query, limit, source_ids) -> hits` (default: production search). Returns the
    report; `rep["per_query"]` carries the top-40 candidates so I2 can rerank exactly these offline."""
    from . import evals
    from .search import search
    fn = search_fn or (lambda q, limit, sids: search(q, limit=limit, source_ids=sids))
    t0 = time.time()
    g = evals.load_golden()
    pid = g["project_id"]
    fx = load_fixture(pid, g["sources"])
    ids = fx["ids"]
    by_sid = {v: k for k, v in ids.items()}
    rows, per_query = [], []
    t_search = 0.0
    for qq in fx["queries"]:
        t1 = time.time()
        hits = fn(qq["q"], CANDIDATES, list(ids.values()))
        t_search += time.time() - t1
        gr = grade(hits, qq["expected"], qq["hard_negatives"], ids)
        gr["category"] = qq["category"]
        rows.append(gr)
        per_query.append({"q": qq["q"], "category": qq["category"], "expected": [(e["source"], e.get("at")) for e in qq["expected"]], "hard_negatives": qq["hard_negatives"],
                          "first_rank": gr["first_rank"], "candidate_rank": gr["candidate_rank"], "ndcg": gr["ndcg"], "locator": f"{gr['loc_hits']}/{gr['loc_total']}",
                          "exact": f"{gr['exact_hits']}/{gr['exact_total']}", "hard_negative_fp": gr["hard_negative_fp"], "note": qq.get("note", ""),
                          "top10": [(by_sid.get(s, s[:8]), at) for s, at in gr["top"]],
                          "candidates": [{"chunk_id": h.get("chunk_id") or h.get("id"), "source": by_sid.get(h["source_id"], h["source_id"][:8]), "start": h.get("start"), "score": h.get("score")} for h in hits]})
    rep: dict[str, Any] = {"eval": "retrieval", "tier": "fake" if settings.fake_ai else "live", "retrieval": label, "fixture_version": fx["version"],
                           "fixture": {"sources": len(ids), "queries": len(rows), "locators": sum(r["loc_total"] for r in rows), "hard_negatives": sum(len(q["hard_negatives"]) for q in fx["queries"])},
                           "metrics": summarise(rows), "by_category": {}, "per_query": per_query,
                           "performance": {"search_s_per_query": round(t_search / max(1, len(rows)), 4), "seconds": round(time.time() - t0, 1)}}
    cands = [len(q["candidates"]) for q in per_query]
    rep["metrics"]["candidates_mean"] = round(sum(cands) / max(1, len(cands)), 1)
    rep["metrics"]["candidates_min_max"] = [min(cands), max(cands)] if cands else None
    for cat in sorted({r["category"] for r in rows}):
        rep["by_category"][cat] = summarise([r for r in rows if r["category"] == cat])
    rep["text"] = format_report(rep)
    return rep


def compare(base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    """Per-query rank changes between two runs of the same fixture (I2's adoption evidence)."""
    bq = {q["q"]: q for q in base["per_query"]}
    improved = worsened = same = 0
    changes = []
    overlap = []
    for q in cand["per_query"]:
        b = bq.get(q["q"])
        if not b:
            continue
        rb, rc = b["first_rank"], q["first_rank"]
        kb = 999 if rb is None else rb
        kc = 999 if rc is None else rc
        if kc < kb:
            improved += 1
        elif kc > kb:
            worsened += 1
        else:
            same += 1
        tb, tc = [x[0] for x in b["top10"]], [x[0] for x in q["top10"]]
        overlap.append(len(set(tb) & set(tc)) / max(1, len(set(tb) | set(tc))))
        if kb != kc or b["exact"] != q["exact"] or b["hard_negative_fp"] != q["hard_negative_fp"]:
            changes.append({"q": q["q"], "first_rank": [rb, rc], "exact": [b["exact"], q["exact"]], "hard_negative_fp": [b["hard_negative_fp"], q["hard_negative_fp"]]})
    return {"improved": improved, "worsened": worsened, "same": same, "top10_source_overlap_mean": round(sum(overlap) / max(1, len(overlap)), 4), "changes": changes}


def format_report(rep: dict[str, Any]) -> str:
    m, f = rep["metrics"], rep["fixture"]
    pct = lambda v: "—" if v is None else f"{v:.1%}"  # noqa: E731
    lines = [f"Retrieval eval ({rep['tier']}) · {rep['retrieval']} · fixture v{rep['fixture_version']} · {f['sources']} sources · {f['queries']} queries · {f['locators']} locators · {f['hard_negatives']} hard negatives · {rep['performance']['search_s_per_query']*1000:.1f} ms/query",
             f"  Recall@1 {pct(m['recall_at_1'])}   @3 {pct(m['recall_at_3'])}   @5 {pct(m['recall_at_5'])}   @10 {pct(m['recall_at_10'])}   candidates@40 {pct(m['candidate_recall_at_40'])} (fused candidates per query: mean {m['candidates_mean']}, range {m['candidates_min_max']})",
             f"  MRR {m['mrr']:.4f}   NDCG@10 {m['ndcg_at_10']:.4f}   expected-source first rank mean {m['mean_first_rank']} / median {m['median_first_rank']}   not-first {m['not_first']}/{m['queries']}",
             f"  locator accuracy {pct(m['locator_accuracy'])} (any top-10 hit within tolerance)   exact locator at the source's first hit {pct(m['locator_exact_at_first_hit'])}",
             f"  hard-negative false positives {m['hard_negative_false_positives']} (in {m['queries_with_hard_negative_above']} queries a distractor ranks above the first expected hit)",
             "  by category:"]
    for cat, c in rep["by_category"].items():
        lines.append(f"    {cat:14s} n={c['queries']:2d}  R@1 {pct(c['recall_at_1']):>6s}  R@3 {pct(c['recall_at_3']):>6s}  MRR {c['mrr']:.3f}  NDCG {c['ndcg_at_10']:.3f}  locator {pct(c['locator_accuracy']):>6s}  exact {pct(c['locator_exact_at_first_hit']):>6s}  HN-FP {c['hard_negative_false_positives']}")
    misses = [q for q in rep["per_query"] if q["first_rank"] != 0 or q["hard_negative_fp"] or q["exact"].split("/")[0] != q["exact"].split("/")[1]]
    if misses:
        lines.append("  mistakes available to fix:")
        for q in misses:
            lines.append(f"    [{q['category']}] {q['q'][:70]:70s} first rank {q['first_rank']}  exact {q['exact']}  HN-FP {q['hard_negative_fp']}  top3 {q['top10'][:3]}")
    return "\n".join(lines)
