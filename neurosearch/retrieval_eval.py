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


# I1.5 decision gate (frozen BEFORE the live-embeddings result was seen — Kyle): build the reranker (I2) only if the
# production-embedding baseline leaves at least one of these opportunities; else close Rung I and keep the fixture as a
# regression test. Candidate recall must stay 100% regardless.
GATE = {"mrr_headroom": 0.03, "recall_at_3_headroom_pp": 5.0, "exact_locator_headroom_pp": 10.0, "fixable_mistakes": 2}
DEPTH_MARGIN = 2


def headroom(rep: dict[str, Any]) -> dict[str, Any]:
    """Ceilings if ordering were perfect within the retrieved candidates, the fixable-mistake count (hard-negative or
    authority/ordering mistakes a candidate-only reranker could plausibly fix: the target IS in the candidates), the
    candidate positions of every expected target and the smallest rerank depth that keeps candidate recall at 100%."""
    m = rep["metrics"]
    per = rep["per_query"]
    # ordering / hard-negative mistakes whose target is in the candidates (exact-locator misses are the separate locator headroom)
    fixable = [q for q in per if q["candidate_rank"] is not None and (q["hard_negative_fp"] or q["first_rank"] not in (None, 0))]
    positions = [q["candidate_rank"] for q in per if q["candidate_rank"] is not None]
    deepest = max(positions) + 1 if positions else 0
    hist: dict[str, int] = {}
    for p_ in positions:
        b = "1" if p_ == 0 else "2-3" if p_ < 3 else "4-5" if p_ < 5 else "6-10" if p_ < 10 else "11+"
        hist[b] = hist.get(b, 0) + 1
    h = {"mrr_ceiling": round(1.0 - m["mrr"], 4), "recall_at_3_ceiling_pp": round((1.0 - m["recall_at_3"]) * 100, 1),
         "exact_locator_ceiling_pp": round((1.0 - (m["locator_exact_at_first_hit"] or 1.0)) * 100, 1),
         "fixable_mistakes": len(fixable), "fixable": [{"q": q["q"], "category": q["category"], "first_rank": q["first_rank"], "candidate_rank": q["candidate_rank"], "exact": q["exact"], "hard_negative_fp": q["hard_negative_fp"]} for q in fixable],
         "candidate_positions_of_first_target": hist, "deepest_target_position": deepest,
         "min_rerank_depth_for_100pct_candidate_recall": deepest, "recommended_rerank_depth": deepest + DEPTH_MARGIN if deepest else 0,
         "candidate_recall_100": m["candidate_recall_at_40"] == 1.0 and m["recall_at_10"] == 1.0}
    h["gate"] = {"mrr": h["mrr_ceiling"] >= GATE["mrr_headroom"], "recall_at_3": h["recall_at_3_ceiling_pp"] >= GATE["recall_at_3_headroom_pp"],
                 "exact_locator": h["exact_locator_ceiling_pp"] >= GATE["exact_locator_headroom_pp"], "fixable_mistakes": h["fixable_mistakes"] >= GATE["fixable_mistakes"]}
    h["build_i2"] = h["candidate_recall_100"] and any(h["gate"].values())
    h["decision"] = ("BUILD I2 (experiment, off by default; must still beat the baseline by MRR +0.02 / R@3 +5 pp / locator +10 pp)" if h["build_i2"]
                     else "CLOSE RUNG I — production retrieval leaves no meaningful headroom; keep the hard fixture as the regression test")
    return h


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
    rep["embeddings"] = {"model": settings.embedding_model if not settings.fake_ai else "fake hashed lexical vectors", "fake": bool(settings.fake_ai)}
    rep["anthropic_calls"] = int(db.connect().execute("SELECT COUNT(*) FROM invocations WHERE provider LIKE 'anthropic%'").fetchone()[0])
    rep["embedding_usage"] = {k: (v or 0) for k, v in dict(db.connect().execute("SELECT SUM(input_tokens) input_tokens, SUM(cost) cost, COUNT(*) calls FROM usage WHERE kind='embed'").fetchone()).items()}
    rep["headroom"] = headroom(rep)
    rep["text"] = format_report(rep)
    return rep


# I2 adoption rule, FROZEN against the live baseline b5768c0 (0.22.0+i15-live) before the comparison is run (Kyle).
LIVE_BASELINE = {"recall_at_1": 0.8667, "recall_at_3": 0.9333, "recall_at_5": 0.9333, "recall_at_10": 1.0, "candidate_recall_at_40": 1.0, "mrr": 0.9093,
                 "ndcg_at_10": 0.8501, "locator_exact_at_first_hit": 0.8718, "hard_negative_false_positives": 1, "deepest_target_position": 9}
HARD_GATES = {"recall_at_10_min": 1.0, "candidate_recall_min": 1.0, "exact_locator_min": 0.8718, "hard_negative_fp_max": 1}
MEANINGFUL = {"mrr_min": 0.9293, "recall_at_3_min": 0.983, "exact_locator_min": 0.972}      # +0.02 / +5 pp / +10 pp — at least ONE
FIXABLE_IMPROVED_MIN = 2                                                                   # of the 4 fixable ordering mistakes in the live baseline


def run_rerank_compare(progress: Any = print, depth: int | None = None) -> dict[str, Any]:
    """I2: the same fixture, the same database, the same candidates — RRF ordering vs RRF + reranker — and the frozen
    verdict. The baseline is re-run in this database (per-query comparisons need identical candidates); the gate
    thresholds are the FROZEN live baseline numbers, not the re-run's."""
    from . import rerank as R
    from .search import search
    d = depth or R.RERANK_DEPTH
    calls: list[dict[str, Any]] = []

    def reranked(q: str, limit: int, sids: list[str]) -> list[dict[str, Any]]:
        hits = search(q, limit=limit, source_ids=sids, rerank=False)
        out = R.rerank(q, hits, depth=d)
        info = dict(R.last() or {})
        info["q"] = q
        info["contained"] = sorted(h["chunk_id"] for h in out) == sorted(h["chunk_id"] for h in hits)
        info["tail_unchanged"] = [h["chunk_id"] for h in out[d:]] == [h["chunk_id"] for h in hits[d:]]
        info["order_before"] = [h["chunk_id"] for h in hits[:d]]
        info["order_after"] = [h["chunk_id"] for h in out[:d]]
        calls.append(info)
        return out

    progress("baseline: production retrieval (RRF ordering)")
    base = run(progress=lambda m: None, search_fn=lambda q, limit, sids: search(q, limit=limit, source_ids=sids, rerank=False), label="hybrid (FTS + vectors, RRF)")
    progress(f"candidate: the same retrieval + retrieval.rerank over the top {d}")
    cand = run(progress=lambda m: None, search_fn=reranked, label=f"hybrid + retrieval.rerank (depth {d})")
    cmp = compare(base, cand)
    m = cand["metrics"]
    applied = [c for c in calls if c["applied"]]
    fallbacks = [c for c in calls if not c["applied"]]
    fixable_base = {q["q"] for q in base["headroom"]["fixable"]}
    by_q_cand = {q["q"]: q for q in cand["per_query"]}
    by_q_base = {q["q"]: q for q in base["per_query"]}
    fixable_improved = [q for q in fixable_base if (999 if by_q_cand[q]["first_rank"] is None else by_q_cand[q]["first_rank"]) < (999 if by_q_base[q]["first_rank"] is None else by_q_base[q]["first_rank"])
                        or by_q_cand[q]["hard_negative_fp"] < by_q_base[q]["hard_negative_fp"]]
    exact_pairs = [(by_q_base[q]["exact"], by_q_cand[q]["exact"]) for q in by_q_cand]
    hard = {"recall_at_10_100": m["recall_at_10"] >= HARD_GATES["recall_at_10_min"], "candidate_recall_100": m["candidate_recall_at_40"] >= HARD_GATES["candidate_recall_min"],
            "exact_locator_not_below_baseline": (m["locator_exact_at_first_hit"] or 0) >= HARD_GATES["exact_locator_min"],
            "hard_negative_fp_not_above_1": m["hard_negative_false_positives"] <= HARD_GATES["hard_negative_fp_max"],
            "candidate_set_unchanged_every_query": all(c["contained"] and c["tail_unchanged"] for c in calls),
            "fallback_restores_original_ordering": all(c["order_after"] == c["order_before"] for c in fallbacks)}
    meaningful = {"mrr": m["mrr"] >= MEANINGFUL["mrr_min"], "recall_at_3": m["recall_at_3"] >= MEANINGFUL["recall_at_3_min"], "exact_locator": (m["locator_exact_at_first_hit"] or 0) >= MEANINGFUL["exact_locator_min"]}
    econ = {"queries": len(calls), "applied": len(applied), "fallbacks": len(fallbacks), "fallback_reasons": [c["fallback"] for c in fallbacks][:10],
            "latency_s_mean": round(sum(c["latency_s"] for c in calls) / max(1, len(calls)), 3), "latency_s_max": round(max((c["latency_s"] for c in calls), default=0.0), 3),
            "input_tokens_mean": round(sum(c["input_tokens"] for c in calls) / max(1, len(calls))), "output_tokens_mean": round(sum(c["output_tokens"] for c in calls) / max(1, len(calls))),
            "cost_per_query": round(sum(c["cost"] for c in calls) / max(1, len(calls)), 6), "cost_total": round(sum(c["cost"] for c in calls), 6),
            "configured_model": next((c["configured_model"] for c in calls), None), "returned_models": sorted({str(c["model"]) for c in calls if c.get("model")}),
            "cost_per_query_at_contract_price": _contract_price_per_query(calls),
            "version": next((c["version"] for c in calls), None), "schema": next((c["schema"] for c in calls), None), "depth": d}
    verdict = "ADOPT" if all(hard.values()) and any(meaningful.values()) and len(fixable_improved) >= FIXABLE_IMPROVED_MIN else "KILL"
    if verdict == "KILL" and all(hard.values()) and any(meaningful.values()):
        verdict_note = f"aggregate improved but only {len(fixable_improved)} of the {len(fixable_base)} fixable ordering mistakes did (need {FIXABLE_IMPROVED_MIN})"
    elif verdict == "KILL" and all(hard.values()):
        verdict_note = "no meaningful improvement (MRR +0.02 / R@3 +5 pp / exact locator +10 pp)"
    elif verdict == "KILL":
        verdict_note = "hard gate failed: " + ", ".join(k for k, v in hard.items() if not v)
    else:
        verdict_note = "every hard gate holds and the improvement is meaningful"
    rep = {"eval": "retrieval-rerank", "tier": cand["tier"], "depth": d, "baseline": {k: base["metrics"].get(k) for k in LIVE_BASELINE}, "frozen_live_baseline": LIVE_BASELINE,
           "candidate": {k: m.get(k) for k in LIVE_BASELINE}, "compare": cmp, "fixable_in_baseline": sorted(fixable_base), "fixable_improved": sorted(fixable_improved),
           "hard_gates": hard, "meaningful": meaningful, "economics": econ, "verdict": verdict, "verdict_note": verdict_note,
           "per_query": [{"q": b["q"], "category": b["category"], "first_rank": [b["first_rank"], by_q_cand[b["q"]]["first_rank"]], "exact": [b["exact"], by_q_cand[b["q"]]["exact"]],
                          "hard_negative_fp": [b["hard_negative_fp"], by_q_cand[b["q"]]["hard_negative_fp"]], "top_before": b["top10"][:d], "top_after": by_q_cand[b["q"]]["top10"][:d]} for b in base["per_query"]],
           "calls": calls, "exact_pairs": exact_pairs, "anthropic_calls": cand["anthropic_calls"] - base["anthropic_calls"], "base_report": base, "cand_report": cand}
    rep["text"] = format_compare(rep)
    return rep


def _contract_price_per_query(calls: list[dict[str, Any]]) -> float:
    """What the configured reranker model costs per query at list price (the fake returns 'fake-claude', priced as a default)."""
    from . import rerank as R, usage
    from .contracts import contract
    pin, pout = usage._price(contract(R.TASK).model)
    n = max(1, len(calls))
    return round(sum(c["input_tokens"] / 1e6 * pin + c["output_tokens"] / 1e6 * pout for c in calls) / n, 6)


def format_compare(rep: dict[str, Any]) -> str:
    b, c, e, cmp = rep["baseline"], rep["candidate"], rep["economics"], rep["compare"]
    pct = lambda v: "—" if v is None else f"{v:.1%}"  # noqa: E731
    lines = [f"Retrieval rerank comparison ({rep['tier']}) · depth {rep['depth']} · {e['configured_model']} ({e['version']}, {e['schema']}) · returned {', '.join(e['returned_models']) or '—'}",
             f"  {'metric':28s} {'baseline (this run)':>20s} {'frozen live b5768c0':>20s} {'+ reranker':>12s}"]
    for k, label in (("recall_at_1", "Recall@1"), ("recall_at_3", "Recall@3"), ("recall_at_5", "Recall@5"), ("recall_at_10", "Recall@10"), ("candidate_recall_at_40", "candidate recall"),
                     ("mrr", "MRR"), ("ndcg_at_10", "NDCG@10"), ("locator_exact_at_first_hit", "exact first-hit locator"), ("hard_negative_false_positives", "hard-negative FPs")):
        f = (lambda v: f"{v:.4f}") if k in ("mrr", "ndcg_at_10") else (lambda v: str(v)) if k == "hard_negative_false_positives" else pct
        lines.append(f"  {label:28s} {f(b[k]):>20s} {f(rep['frozen_live_baseline'][k]):>20s} {f(c[k]):>12s}")
    lines += [f"  per query: improved {cmp['improved']} · worsened {cmp['worsened']} · unchanged {cmp['same']} · top-{rep['depth']} source overlap {cmp['top10_source_overlap_mean']:.2f}",
              f"  fixable ordering mistakes in the baseline: {len(rep['fixable_in_baseline'])} · improved by the reranker: {len(rep['fixable_improved'])} (need ≥ {FIXABLE_IMPROVED_MIN})",
              f"  economics: {e['applied']}/{e['queries']} reranked · fallbacks {e['fallbacks']} · latency mean {e['latency_s_mean']:.2f}s max {e['latency_s_max']:.2f}s · tokens in {e['input_tokens_mean']} / out {e['output_tokens_mean']} per query · ${e['cost_per_query']:.5f}/query as billed (${e['cost_total']:.4f} total; ${e['cost_per_query_at_contract_price']:.5f}/query at {e['configured_model']} list price) · anthropic calls {rep['anthropic_calls']}",
              "  hard gates: " + " · ".join(f"{k} {'✓' if v else '✗'}" for k, v in rep["hard_gates"].items()),
              "  meaningful: " + " · ".join(f"{k} {'✓' if v else '✗'}" for k, v in rep["meaningful"].items())]
    changed = [q for q in rep["per_query"] if q["first_rank"][0] != q["first_rank"][1] or q["exact"][0] != q["exact"][1] or q["hard_negative_fp"][0] != q["hard_negative_fp"][1]]
    if changed:
        lines.append("  queries whose grade changed (first rank / exact / HN-FP before → after):")
        for q in changed:
            lines.append(f"    [{q['category']}] {q['q'][:66]:66s} rank {q['first_rank'][0]}→{q['first_rank'][1]}  exact {q['exact'][0]}→{q['exact'][1]}  HN-FP {q['hard_negative_fp'][0]}→{q['hard_negative_fp'][1]}")
    if e["fallback_reasons"]:
        lines.append(f"  fallback reasons: {e['fallback_reasons']}")
    lines.append(f"VERDICT: {rep['verdict']} — {rep['verdict_note']}")
    return "\n".join(lines)


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
        lines.append("  mistakes available to fix (candidate position = where the first expected target sits in the fused candidate list, 1-based):")
        for q in misses:
            cp = None if q["candidate_rank"] is None else q["candidate_rank"] + 1
            lines.append(f"    [{q['category']}] {q['q'][:70]:70s} first rank {q['first_rank']}  candidate pos {cp}  exact {q['exact']}  HN-FP {q['hard_negative_fp']}  top3 {q['top10'][:3]}")
    h = rep.get("headroom")
    if h:
        lines += [f"  embeddings: {rep['embeddings']['model']} · anthropic calls {rep['anthropic_calls']} · embedding tokens {rep['embedding_usage'].get('input_tokens', 0):,} (${rep['embedding_usage'].get('cost', 0):.4f})",
                  f"  candidate positions of the first expected target: {h['candidate_positions_of_first_target']} · deepest {h['deepest_target_position']} → minimum rerank depth for 100% candidate recall {h['min_rerank_depth_for_100pct_candidate_recall']}, recommended {h['recommended_rerank_depth']} (+{DEPTH_MARGIN} margin)",
                  f"  headroom vs the frozen gate: MRR {h['mrr_ceiling']:+.4f} (gate ≥ {GATE['mrr_headroom']}) {'✓' if h['gate']['mrr'] else '✗'} · R@3 {h['recall_at_3_ceiling_pp']:+.1f} pp (≥ {GATE['recall_at_3_headroom_pp']}) {'✓' if h['gate']['recall_at_3'] else '✗'} · exact locator {h['exact_locator_ceiling_pp']:+.1f} pp (≥ {GATE['exact_locator_headroom_pp']}) {'✓' if h['gate']['exact_locator'] else '✗'} · fixable mistakes {h['fixable_mistakes']} (≥ {GATE['fixable_mistakes']}) {'✓' if h['gate']['fixable_mistakes'] else '✗'} · candidate recall 100% {'✓' if h['candidate_recall_100'] else '✗'}",
                  f"  decision: {h['decision']}"]
    return "\n".join(lines)
