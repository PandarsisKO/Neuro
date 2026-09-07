"""`neurosearch eval` — the proving ground (hardening ladder, Mission A3).

Loads the frozen Golden Project (tests/fixtures/golden), runs the real pipeline over it — ingestion, retrieval,
findings, answers, the planner, the calculator — and reports quality, volume, economics and performance as numbers.

Tier 1 (default) runs against the deterministic fakes (NEUROSEARCH_FAKE_AI): free, repeatable, gates every commit.
Tier 2 (`--live`) runs the same corpus against the real models: it costs money, it is how a model or prompt change is
judged, and `--baseline` freezes its numbers so the next run can be compared token for token.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

GOLDEN = Path(__file__).parent.parent / "tests" / "fixtures" / "golden"
GATES = {"retrieval_recall_at_10": 0.90, "citation_validity": 1.0, "finding_quote_validity": 0.98, "plan_evidence_validity": 1.0}
ZERO_GATES = ("schema_fallbacks", "output_truncated", "output_refused")          # Mission F: structured output is the guarantee; fallbacks are degraded events
# What Tier 1 can prove (the pipeline handles AI-shaped output correctly) vs what only a real model can show
PIPELINE_METRICS = ("retrieval_recall_at_5", "retrieval_recall_at_10", "retrieval_mrr", "locator_accuracy", "citation_validity",
                    "finding_quote_validity", "stored_findings_verified", "plan_evidence_validity", "calculator_ok", "fixture_evidence_present")
MODEL_METRICS = ("golden_evidence_recall", "answers_cite_expected_source", "gap_detection", "contradiction_surfaced")
# request parameters per task as the call sites set them today (recorded so a migration can compare like with like)
REQUEST_PARAMS = {"answer.chat": {"max_tokens": 2000}, "answer.repair": {"max_tokens": 2000}, "findings.extract": {"max_tokens": 4000},
                  "rank.relevance": {"max_tokens": 6000}, "discover.quick": {"max_tokens": 3500}, "discover.verify": {"max_tokens": 2500},
                  "planner.analysis": {"max_tokens": 7000}, "planner.build": {"max_tokens": 16000}, "planner.update": {"max_tokens": 4000}}


def prompt_versions() -> dict[str, str]:
    """A short hash per system prompt — changes when the prompt changes, so baselines say what they measured."""
    import hashlib
    from . import discover, findings, planner, qa, relevance
    h = lambda t: hashlib.sha1(t.encode()).hexdigest()[:8]  # noqa: E731
    return {"findings.extract": h(findings.SYSTEM), "answer.chat": h(qa.SYSTEM + qa.PROJECT_BLOCK), "rank.relevance": h(relevance.SYSTEM),
            "planner.analysis": h(planner.ANALYSIS_SYSTEM), "planner.build": h(planner.SYSTEM), "planner.update": h(planner.UPDATE_SYSTEM),
            "discover.quick": h(discover.QUICK_SYSTEM), "discover.verify": h(discover.VERIFY_SYSTEM)}


def git_sha() -> str:
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=str(Path(__file__).parent.parent)).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


# ------------------------------------------------------------------ loading the corpus

def load_golden(root: Path = GOLDEN) -> dict[str, Any]:
    """Ingest the golden project into the current database. Returns {project_id, sources: {golden id: source id}}."""
    from . import ingest
    man = json.loads((root / "manifest.json").read_text())
    pj = man["project"]
    project = db.create_project(pj["name"], pj.get("brief"))
    db.update_project(project["id"], goal=pj.get("goal"), questions=pj.get("questions"))
    was_auto = settings.auto_suggest
    settings.auto_suggest = False          # the eval runs findings itself, synchronously
    ids: dict[str, str] = {}
    try:
        for s in man["sources"]:
            path = root / s["file"]
            if s["kind"] == "transcript":
                payload = json.loads(path.read_text())
                payload.update({k: s.get(k) for k in ("platform", "external_id", "url", "title", "channel", "published_at")})
                payload["transcript_kind"] = "captions"
                r = ingest.store_transcript(payload, project_id=project["id"])
            elif s["kind"] == "html":
                r = ingest.ingest_webpage(s["url"], project_id=project["id"], title=s.get("title"), html=path.read_text())
            else:
                r = ingest.ingest_local_file(path, title=s.get("title"), project_id=project["id"], original_name=path.name)
            ids[s["id"]] = r["source_id"]
    finally:
        settings.auto_suggest = was_auto
    return {"project_id": project["id"], "sources": ids, "manifest": man}


# ------------------------------------------------------------------ the run

def _locator_ok(hit: dict[str, Any], want: Any) -> bool:
    try:
        if hit.get("platform") in ("document", "web", "spreadsheet"):
            return int(hit["start"]) == int(want)
        return abs(float(hit["start"]) - float(want)) <= 120
    except (TypeError, ValueError):
        return False


def run(root: Path = GOLDEN, live: bool = False, progress: Any = print) -> dict[str, Any]:
    from . import findings, planner, qa
    from .evidence import quote_in_text
    from .search import search

    t_all = time.time()
    usage_from = time.time()
    from . import __version__
    rep: dict[str, Any] = {"tier": "live" if live else "fake", "model": settings.answer_model if live else "fake",
                           "app_version": __version__, "git_sha": git_sha(), "provider": "anthropic" if live else "fake",
                           "requested_model": settings.answer_model if live else "fake", "embedding_model": settings.embedding_model if live else "fake",
                           "prompt_versions": prompt_versions(), "request_params": REQUEST_PARAMS,
                           "contracts": {c.task: c.describe() for c in __import__("neurosearch.contracts", fromlist=["all_contracts"]).all_contracts()},
                           "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "gates": {}, "quality": {}, "volume": {}, "economics": {}, "performance": {}}

    t0 = time.time()
    g = load_golden(root)
    pid, ids = g["project_id"], g["sources"]
    by_source = {v: k for k, v in ids.items()}
    man = g["manifest"]
    rep["performance"]["ingest_s"] = round(time.time() - t0, 2)
    progress(f"ingested {len(ids)} golden sources")

    # fixture sanity: every golden evidence quote really is in its source
    missing = [e for e in man["evidence"] if not quote_in_text(e["quote"], " ".join(x["text"] for x in db.get_segments(ids[e["source"]])))]
    rep["quality"]["fixture_evidence_present"] = 1 - len(missing) / max(1, len(man["evidence"]))

    # ---- retrieval
    t0 = time.time()
    qs = [q for q in man["questions"] if q.get("sources") and not q.get("calculator")]
    r5 = r10 = 0
    rr = 0.0
    loc_hits = loc_total = 0
    per_q = []
    for q in qs:
        hits = search(q["q"], limit=10, source_ids=list(ids.values()))
        want = {ids[s] for s in q["sources"]}
        ranks = [i for i, h in enumerate(hits) if h["source_id"] in want]
        first = ranks[0] if ranks else None
        r5 += first is not None and first < 5
        r10 += first is not None
        rr += 1 / (first + 1) if first is not None else 0
        for gid, at in (q.get("at") or {}).items():
            loc_total += 1
            loc_hits += any(h["source_id"] == ids[gid] and _locator_ok(h, at) for h in hits)
        per_q.append({"q": q["q"], "first_rank": first, "top": [by_source.get(h["source_id"]) for h in hits[:3]]})
    n = max(1, len(qs))
    rep["quality"].update({"retrieval_recall_at_5": round(r5 / n, 4), "retrieval_recall_at_10": round(r10 / n, 4), "retrieval_mrr": round(rr / n, 4),
                           "locator_accuracy": round(loc_hits / loc_total, 4) if loc_total else None, "questions": len(qs)})
    rep["performance"]["retrieval_s_per_q"] = round((time.time() - t0) / n, 4)
    rep["retrieval_detail"] = per_q
    progress(f"retrieval: recall@5 {r5}/{n}, recall@10 {r10}/{n}")

    # ---- findings + quote validity
    t0 = time.time()
    checked = rejected = suggested = 0
    windows = 0
    for gid, sid in ids.items():
        if gid in ("calc",):
            continue
        try:
            res = findings.suggest_for_source(pid, sid)
        except Exception as e:  # noqa: BLE001
            progress(f"findings failed for {gid}: {e}")
            continue
        suggested += res["suggested"]
        rejected += res.get("rejected_quotes", 0)
        checked += res["suggested"] + res.get("rejected_quotes", 0)
        windows += len(findings._windows(db.get_segments(sid), db.get_source(sid)["platform"]))
    # independent re-check of what was stored (the runtime validator could have a bug of its own)
    stored_bad = 0
    stored = 0
    notes = db.list_project_notes(pid, status="suggested")
    for note in notes:
        c = (note.get("citations") or [{}])[0]
        if not c.get("source_id"):
            continue
        stored += 1
        full = " ".join(x["text"] for x in db.get_segments(c["source_id"]))
        if c.get("snippet") and not quote_in_text(c["snippet"], full):
            stored_bad += 1
    # golden evidence recall: is each planted nugget represented by a suggested finding nearby?
    ev_hit = 0
    for e in man["evidence"]:
        sid = ids[e["source"]]
        segs = db.get_segments(sid)
        where = next((s["start"] for s in segs if quote_in_text(e["quote"], s["text"])), None)
        if where is None:
            continue
        for nnote in notes:
            c = (nnote.get("citations") or [{}])[0]
            if c.get("source_id") == sid and abs(float(c.get("start") or 0) - where) <= 120:
                ev_hit += 1
                break
    rep["quality"].update({"finding_quote_validity": round(1 - rejected / checked, 4) if checked else 1.0,
                           "stored_findings_verified": round(1 - stored_bad / stored, 4) if stored else 1.0,
                           "golden_evidence_recall": round(ev_hit / max(1, len(man["evidence"])), 4),
                           "findings_suggested": suggested, "findings_rejected": rejected, "transcript_windows": windows})
    rep["performance"]["findings_s"] = round(time.time() - t0, 2)
    progress(f"findings: {suggested} suggested, {rejected} rejected by the quote validator, evidence recall {ev_hit}/{len(man['evidence'])}")

    # ---- answers + citation validity
    t0 = time.time()
    cited_expected = 0
    invalid_total = valid_total = 0
    gap_ok = gap_n = 0
    contra_ok = contra_n = 0
    calc_ok = None
    answers = 0
    for q in man["questions"]:
        if q.get("calculator"):
            continue
        try:
            res = qa.ask(q["q"], project_id=pid)
        except Exception as e:  # noqa: BLE001
            progress(f"answer failed: {e}")
            continue
        answers += 1
        invalid_total += len(res.get("invalid_citations") or [])
        valid_total += len(res["citations"])
        cited = {c["source_id"] for c in res["citations"]}
        if q.get("gap"):
            gap_n += 1
            gap_ok += ("gap:" in res["answer"].lower()) or not res["citations"]
        elif q.get("sources"):
            cited_expected += bool(cited & {ids[s] for s in q["sources"]})
        if q.get("contradicts"):
            contra_n += 1
            contra_ok += bool(cited & {ids[s] for s in q["sources"]}) and bool(cited & {ids[s] for s in q["contradicts"]})
    rep["quality"].update({"citation_validity": round(1 - invalid_total / (valid_total + invalid_total), 4) if (valid_total + invalid_total) else 1.0,
                           "answers_cite_expected_source": round(cited_expected / max(1, sum(1 for q in man["questions"] if q.get("sources") and not q.get("gap") and not q.get("calculator"))), 4),
                           "gap_detection": round(gap_ok / gap_n, 4) if gap_n else None,
                           "contradiction_surfaced": round(contra_ok / contra_n, 4) if contra_n else None, "answers": answers})
    rep["performance"]["answer_s_per_q"] = round((time.time() - t0) / max(1, answers), 3)
    progress(f"answers: {answers}, invalid citations {invalid_total}")

    # ---- calculator
    try:
        from .sheets import calculate
        r = calculate(ids["calc"], {"Down payment %": 0.10}, ["DSCR"])
        dscr = float(list(r["outputs"].values())[0])
        calc_ok = 1.7 <= dscr <= 1.85
        rep["quality"]["calculator_dscr"] = round(dscr, 3)
    except Exception as e:  # noqa: BLE001
        calc_ok = False
        rep["quality"]["calculator_error"] = str(e)[:200]
    rep["quality"]["calculator_ok"] = calc_ok

    # ---- planner + evidence validity
    t0 = time.time()
    try:
        row = planner.build_plan(pid)
        chk = row["plan"].get("_evidence_check") or {}
        rep["quality"]["plan_evidence_validity"] = round(1 - len(chk.get("dangling") or []) / max(1, chk.get("references") or 1), 4)
        rep["quality"]["plan_evidence_refs"] = chk.get("references")
    except Exception as e:  # noqa: BLE001
        rep["quality"]["plan_error"] = str(e)[:300]
        rep["quality"]["plan_evidence_validity"] = 0.0
    rep["performance"]["plan_s"] = round(time.time() - t0, 2)

    # ---- volume + economics from the usage table (everything this run recorded)
    rows = db.connect().execute("SELECT kind, model, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read) cr, SUM(cache_write) cw, SUM(cost) c, COUNT(*) n "
                                "FROM usage WHERE ts>=? GROUP BY kind, model", (usage_from,)).fetchall()
    by_task = {r["kind"]: {"calls": r["n"], "input_tokens": int(r["i"] or 0), "output_tokens": int(r["o"] or 0), "cache_read": int(r["cr"] or 0),
                           "cache_write": int(r["cw"] or 0), "cost": round(float(r["c"] or 0), 4), "model": r["model"]} for r in rows}
    tot = {k: sum(v[k] for v in by_task.values()) for k in ("input_tokens", "output_tokens", "cache_read", "cache_write", "cost")}
    hours = sum((db.get_source(s) or {}).get("duration") or 0 for s in ids.values()) / 3600
    rep["volume"] = {"by_task": by_task, "input_tokens": tot["input_tokens"], "output_tokens": tot["output_tokens"], "cache_read_tokens": tot["cache_read"],
                     "cache_write_tokens": tot["cache_write"],
                     "cache_read_rate": round(tot["cache_read"] / max(1, tot["input_tokens"] + tot["cache_read"] + tot["cache_write"]), 4)}
    rep["economics"] = {"cost": round(tot["cost"], 4), "cost_per_source_hour": round(tot["cost"] / hours, 4) if hours else None, "media_hours": round(hours, 2)}
    rep["returned_models"] = sorted({t["model"] for t in by_task.values() if t.get("model")})
    rep["validators"] = {k: v for k, v in rep["quality"].items() if k in ("citation_validity", "finding_quote_validity", "stored_findings_verified", "plan_evidence_validity")}
    rep["validation_events"] = {r["kind"]: r["n"] for r in db.connect().execute("SELECT kind, COUNT(*) n FROM validation_events WHERE ts>=? GROUP BY kind", (usage_from,)).fetchall()}
    ve = rep["validation_events"]
    rep["structured_outputs"] = {"schema_fallbacks": ve.get("schema_fallback", 0), "output_truncated": ve.get("output_truncated", 0), "output_refused": ve.get("output_refused", 0),
                                 "structured_tasks": sorted(t for t, c in rep["contracts"].items() if c.get("schema"))}
    for k in ZERO_GATES:
        rep["quality"][k] = rep["structured_outputs"][k]
    # logical invocations vs transport attempts (a retry must never look like a second research task)
    inv_rows = db.connect().execute("SELECT task, state, COUNT(*) n, COUNT(DISTINCT logical_id) logical FROM invocations WHERE requested_at>=? GROUP BY task, state", (usage_from,)).fetchall()
    inv: dict[str, Any] = {"logical": 0, "attempts": 0, "by_state": {}, "by_task": {}}
    for r in inv_rows:
        inv["attempts"] += r["n"]
        inv["by_state"][r["state"]] = inv["by_state"].get(r["state"], 0) + r["n"]
        t = inv["by_task"].setdefault(r["task"] or "?", {"attempts": 0, "logical": 0, "failed_attempts": 0})
        t["attempts"] += r["n"]
        if r["state"] == "completed":
            t["logical"] += r["logical"]
        elif r["state"] == "failed":
            t["failed_attempts"] += r["n"]
    inv["logical"] = db.connect().execute("SELECT COUNT(DISTINCT logical_id) FROM invocations WHERE requested_at>=?", (usage_from,)).fetchone()[0]
    inv["outcome_unknown"] = inv["by_state"].get("outcome_unknown", 0)
    inv["sdk_retries"] = "disabled (max_retries=0); every attempt is a ledger row"
    rep["invocations"] = inv
    rep["performance"]["total_s"] = round(time.time() - t_all, 2)

    # ---- gates
    for k, floor in GATES.items():
        v = rep["quality"].get(k)
        rep["gates"][k] = {"value": v, "floor": floor, "pass": v is not None and v >= floor}
    rep["gates"]["calculator_ok"] = {"value": calc_ok, "floor": True, "pass": bool(calc_ok)}
    for k in ZERO_GATES:
        rep["gates"][k] = {"value": rep["quality"][k], "floor": 0, "pass": rep["quality"][k] == 0}
    rep["gates"]["fixture_evidence_present"] = {"value": rep["quality"]["fixture_evidence_present"], "floor": 1.0, "pass": rep["quality"]["fixture_evidence_present"] == 1.0}
    rep["pass"] = all(g["pass"] for g in rep["gates"].values())
    rep["project_id"] = pid
    return rep


# ------------------------------------------------------------------ reporting

def format_report(rep: dict[str, Any]) -> str:
    q, v, e, p = rep["quality"], rep["volume"], rep["economics"], rep["performance"]
    pct = lambda x: "—" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    fake = rep["tier"] != "live"
    lines = [f"Neuro Search eval · {rep['tier']} · model {rep['model']} · app {rep.get('app_version')} @ {rep.get('git_sha')}", ""]
    cs = rep.get("contracts") or {}
    if cs:
        lines += ["CONTRACTS  (task · model · thinking/effort · max_out · attempts)"]
        for t, c in cs.items():
            if c.get("provider") == "anthropic":
                lines.append(f"  {t:18s} {c['model']:28s} {c['thinking']}{'/' + c['effort'] if c.get('effort') else '':10s} {c['max_output_tokens']:>6}  {c['max_attempts']}")
        lines.append("")
    lines += [
             "PIPELINE QUALITY  (does Neuro Search process AI-shaped output correctly?)",
             f"  Retrieval recall@5 / @10   {pct(q.get('retrieval_recall_at_5'))} / {pct(q.get('retrieval_recall_at_10'))}   MRR {q.get('retrieval_mrr')}   locator {pct(q.get('locator_accuracy'))}   ({q.get('questions')} questions)",
             f"  Citation integrity         {pct(q.get('citation_validity'))}   (invalid [n] caught, repaired or flagged)",
             f"  Evidence integrity         {pct(q.get('finding_quote_validity'))}   ({q.get('findings_suggested')} findings kept, {q.get('findings_rejected')} rejected; stored re-verified {pct(q.get('stored_findings_verified'))})",
             f"  Plan evidence integrity    {pct(q.get('plan_evidence_validity'))}   ({q.get('plan_evidence_refs')} references)" + (f"   ERROR {q['plan_error']}" if q.get("plan_error") else ""),
             f"  Calculator                 {'ok' if q.get('calculator_ok') else 'FAILED'}   DSCR {q.get('calculator_dscr')}",
             f"  Validation events          " + (", ".join(f"{k} {n}" for k, n in (rep.get("validation_events") or {}).items()) or "none"),
             f"  Structured outputs         fallbacks {rep.get('structured_outputs', {}).get('schema_fallbacks', '—')} · truncated {rep.get('structured_outputs', {}).get('output_truncated', '—')} · refused {rep.get('structured_outputs', {}).get('output_refused', '—')}   (schema'd tasks: {', '.join(rep.get('structured_outputs', {}).get('structured_tasks') or []) or 'none'})",
             f"  Provider calls             {rep.get('invocations', {}).get('logical', 0)} logical · {rep.get('invocations', {}).get('attempts', 0)} transport attempts · outcome unknown {rep.get('invocations', {}).get('outcome_unknown', 0)} · returned models {', '.join(rep.get('returned_models') or []) or '—'}",
             ""]
    if fake:
        lines += ["MODEL QUALITY", "  Not evaluated (fake provider). The numbers below only show the pipeline can carry them; run `neurosearch eval --live`.", ""]
    else:
        lines += ["MODEL QUALITY", ""]
    lines += [f"  Golden evidence recall     {pct(q.get('golden_evidence_recall'))}   (planted nuggets that became findings)",
              f"  Cites expected source      {pct(q.get('answers_cite_expected_source'))}   gap detection {pct(q.get('gap_detection'))}   contradictions surfaced {pct(q.get('contradiction_surfaced'))}",
              "", "VOLUME",
              f"  Input tokens {v['input_tokens']:,}   output {v['output_tokens']:,}   cache read {v['cache_read_tokens']:,}   cache write {v['cache_write_tokens']:,}   cache read rate {pct(v['cache_read_rate'])}"]
    for k, t in sorted(v["by_task"].items()):
        lines.append(f"    {k:10s} {t['calls']:3d} calls   in {t['input_tokens']:>8,}   out {t['output_tokens']:>7,}   cached {t['cache_read']:>8,}   ${t['cost']:.4f}   {t.get('model')}")
    lines += ["", "ECONOMICS", f"  Cost ${e['cost']:.4f}   per source-hour ${e['cost_per_source_hour']}   ({e['media_hours']} h of media)" + ("   [fake token estimates at list price]" if fake else ""),
              "", "PERFORMANCE", f"  ingest {p['ingest_s']}s   retrieval {p['retrieval_s_per_q']}s/q   findings {p['findings_s']}s   answer {p['answer_s_per_q']}s/q   plan {p['plan_s']}s   total {p['total_s']}s",
              "", "GATES"]
    for k, g in rep["gates"].items():
        lines.append(f"  {'PASS' if g['pass'] else 'FAIL'}  {k:28s} {g['value']}  (floor {g['floor']})")
    lines += ["", f"Tier 1: {'PASS' if rep['pass'] else 'FAIL'}"]
    return "\n".join(lines)


def compare(cur: dict[str, Any], base: dict[str, Any], cost_tolerance: float = 0.10) -> list[str]:
    """Human-readable deltas against a frozen baseline; cost/token regressions beyond the tolerance are flagged."""
    out = []
    for k, v in cur["quality"].items():
        b = base.get("quality", {}).get(k)
        if isinstance(v, (int, float)) and isinstance(b, (int, float)) and v != b:
            out.append(f"{'▲' if v > b else '▼'} {k}: {b} → {v}")
    for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
        b = base.get("volume", {}).get(k)
        if b:
            d = (cur["volume"][k] - b) / b
            out.append(f"{'▲' if d > 0 else '▼'} {k}: {b:,} → {cur['volume'][k]:,} ({d:+.0%})")
    bc = base.get("economics", {}).get("cost")
    if bc:
        d = (cur["economics"]["cost"] - bc) / bc
        flag = "  ⚠ REGRESSION" if d > cost_tolerance else ""
        out.append(f"{'▲' if d > 0 else '▼'} cost: ${bc:.4f} → ${cur['economics']['cost']:.4f} ({d:+.0%}){flag}")
    return out


# ------------------------------------------------------------------ rank.relevance fixture (E2 ranking eval)

RANKING = GOLDEN / "ranking.json"
RANKING_GATES = {"schema_validity": 1.0, "unscored_candidates": 0}      # quality metrics are reported, baselines judge them


def load_ranking(root: Path = GOLDEN) -> dict[str, Any]:
    return json.loads((root / "ranking.json").read_text())


def ndcg(gains_in_rank_order: list[float], k: int) -> float:
    """Normalised DCG@k: gains are the graded relevance of the items as ranked; the ideal ordering is the same gains sorted."""
    import math
    dcg = lambda g: sum(x / math.log2(i + 2) for i, x in enumerate(g[:k]))  # noqa: E731
    ideal = dcg(sorted(gains_in_rank_order, reverse=True))
    return round(dcg(gains_in_rank_order) / ideal, 4) if ideal else 0.0


def run_ranking(root: Path = GOLDEN, live: bool = False, progress: Any = print) -> dict[str, Any]:
    """Invoke the real `rank.relevance` task (through relevance.rank_collection → providers.invoke, under its contract)
    on the frozen candidate set and score the ordering against the fixture's predetermined grades.
    Independent of the ingest/findings eval: nothing is downloaded, embedded or transcribed."""
    from . import __version__, contracts, providers, relevance
    man = json.loads((root / "manifest.json").read_text())
    fx = load_ranking(root)
    items = fx["items"]
    want = int(fx.get("want") or 20)
    c = contracts.contract("rank.relevance")
    configured_model = c.model
    t_all = time.time()
    usage_from = time.time()
    rep: dict[str, Any] = {"eval": "ranking", "tier": "live" if live else "fake", "model": "fake" if not live else c.model, "configured_model": configured_model,
                           "app_version": __version__, "git_sha": git_sha(), "provider": "fake" if not live else c.provider,
                           "fixture_version": fx.get("version"), "candidates": len(items), "want": want,
                           "prompt_version": prompt_versions()["rank.relevance"], "contract": c.describe(),
                           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "gates": {}, "quality": {}, "volume": {}, "economics": {}, "performance": {}}

    # the same brief the ingest eval uses, so the two evals judge the same project
    pj = man["project"]
    project = db.create_project(pj["name"], pj.get("brief"))
    db.update_project(project["id"], goal=pj.get("goal"), questions=pj.get("questions"))
    pid = project["id"]
    coll = db.upsert_collection("channel", "UCgoldenranking", "https://www.youtube.com/@goldenranking", "Golden ranking fixture")
    db.add_project_collections(pid, [coll["id"]])
    by_sid: dict[str, dict[str, Any]] = {}
    with db.batch():
        for it in items:
            s = db.upsert_source(platform="youtube", external_id=it["external_id"], url=f"https://www.youtube.com/watch?v={it['external_id']}",
                                 title=it["title"], description=it.get("description"), duration=it.get("duration"), view_count=it.get("view_count"),
                                 published_at=it.get("published_at"), status="proposed", channel="Golden ranking fixture")
            db.link_source_collection(s["id"], coll["id"])
            by_sid[s["id"]] = it
    progress(f"{len(items)} candidates staged as proposed sources; ranking with {configured_model}")

    # canonical input tokens: the provider's token-counting endpoint over the exact requests about to be sent (free,
    # not a ledger row). Doubles as the preflight — an unknown model id fails here, before any paid call.
    reqs = relevance.canonical_requests(coll["id"], pid, want=want)
    try:
        client = providers.anthropic_client()
        strip = lambda sysb: [{k: v for k, v in b.items() if k != "cache_control"} for b in sysb] if isinstance(sysb, list) else sysb  # noqa: E731
        fmt = {"output_config": contracts.request_params(c)["output_config"]} if c.schema else {}     # the injected format instructions count too
        rep["canonical_input_tokens"] = sum(int(client.messages.count_tokens(model=c.model, system=strip(r["system"]), messages=r["messages"], **fmt).input_tokens) for r in reqs)
    except Exception as e:  # noqa: BLE001
        if live:
            raise RuntimeError(f"token counting failed for model {c.model!r} (preflight, nothing was spent): {e}") from e
        rep["canonical_input_tokens"] = None
    rep["canonical_requests"] = len(reqs)

    t0 = time.time()
    res = relevance.rank_collection(coll["id"], pid, want=want)
    rank_s = time.time() - t0
    rows = db.proposed_sources(coll["id"], pid)        # ordered by score desc, unscored last
    ordered = [by_sid[r["id"]] | {"score": r.get("relevance"), "why": r.get("relevance_why")} for r in rows]
    unscored = [o for o in ordered if o["score"] is None or o["why"] == "not scored"]
    relevant = {o["id"] for o in ordered if o["grade"] >= 2}
    top10, top20 = ordered[:10], ordered[:20]
    q = rep["quality"]
    q["precision_at_10"] = round(sum(o["id"] in relevant for o in top10) / 10, 4)
    q["recall_at_10"] = round(sum(o["id"] in relevant for o in top10) / max(1, len(relevant)), 4)
    q["recall_at_20"] = round(sum(o["id"] in relevant for o in top20) / max(1, len(relevant)), 4)
    q["ndcg_at_20"] = ndcg([float(o["grade"]) for o in ordered], 20)
    strict = {o["id"] for o in ordered if o["grade"] >= 3}         # clearly relevant only: what the top-20 selection should be made of
    q["precision_at_20"] = round(sum(o["id"] in relevant for o in top20) / 20, 4)
    q["precision_at_10_strict"] = round(sum(o["id"] in strict for o in top10) / 10, 4)
    q["recall_at_10_strict"] = round(sum(o["id"] in strict for o in top10) / max(1, len(strict)), 4)
    q["recall_at_20_strict"] = round(sum(o["id"] in strict for o in top20) / max(1, len(strict)), 4)
    q["strict_candidates"] = len(strict)
    q["irrelevant_in_top_10"] = sum(o["grade"] == 0 for o in top10)
    q["clickbait_in_top_10"] = sum(o["category"] == "clickbait" for o in top10)
    q["authoritative_low_view_in_top_20"] = sum(o["category"] == "authoritative_low_view" for o in top20)
    q["popular_irrelevant_in_top_20"] = sum(o["category"] == "popular_irrelevant" for o in top20)
    q["relevant_candidates"] = len(relevant)
    batches = res.get("batches") or 0
    q["schema_validity"] = round((batches - res.get("failed_batches", 0) - res.get("repaired_batches", 0)) / batches, 4) if batches else 0.0
    q["batches"] = batches
    q["failed_batches"] = res.get("failed_batches", 0)
    q["repaired_batches"] = res.get("repaired_batches", 0)
    q["unscored_candidates"] = len(unscored)
    # per category: where do the items land, and what score do they get
    cats: dict[str, dict[str, Any]] = {}
    for pos, o in enumerate(ordered, 1):
        d = cats.setdefault(o["category"], {"n": 0, "rank_sum": 0, "score_sum": 0, "scored": 0})
        d["n"] += 1; d["rank_sum"] += pos
        if o["score"] is not None:
            d["score_sum"] += o["score"]; d["scored"] += 1
    rep["by_category"] = {k: {"n": d["n"], "mean_rank": round(d["rank_sum"] / d["n"], 1), "mean_score": round(d["score_sum"] / d["scored"], 1) if d["scored"] else None}
                          for k, d in sorted(cats.items())}
    rep["ordering"] = [{"pos": i + 1, "id": o["id"], "category": o["category"], "grade": o["grade"], "score": o["score"], "why": o["why"], "title": o["title"][:70]}
                       for i, o in enumerate(ordered)]

    # volume + economics: only what this run recorded for the ranking task
    rows_u = db.connect().execute("SELECT model, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read) cr, SUM(cache_write) cw, SUM(cost) c, COUNT(*) n "
                                  "FROM usage WHERE ts>=? AND kind='rank' GROUP BY model", (usage_from,)).fetchall()
    tot = {k: 0 for k in ("i", "o", "cr", "cw", "c", "n")}
    for r in rows_u:
        for k in tot:
            tot[k] += (r[k] or 0)
    rep["volume"] = {"calls": int(tot["n"]), "input_tokens": int(tot["i"]), "output_tokens": int(tot["o"]), "cache_read_tokens": int(tot["cr"]),
                     "cache_write_tokens": int(tot["cw"]), "tokens_per_candidate": round((tot["i"] + tot["cr"] + tot["cw"]) / len(items), 1),
                     "canonical_input_tokens": rep.get("canonical_input_tokens")}
    rep["economics"] = {"cost": round(float(tot["c"]), 4), "cost_per_100_candidates": round(100 * float(tot["c"]) / len(items), 4)}
    rep["performance"] = {"rank_s": round(rank_s, 2), "s_per_batch": round(rank_s / batches, 2) if batches else None,
                          "s_per_100_candidates": round(100 * rank_s / len(items), 2), "total_s": round(time.time() - t_all, 2)}
    inv_rows = db.connect().execute("SELECT state, COUNT(*) n, COUNT(DISTINCT logical_id) logical, GROUP_CONCAT(DISTINCT returned_model) rm "
                                    "FROM invocations WHERE requested_at>=? AND task='rank.relevance' GROUP BY state", (usage_from,)).fetchall()
    inv: dict[str, Any] = {"logical": 0, "attempts": 0, "by_state": {}}
    returned: set[str] = set()
    for r in inv_rows:
        inv["attempts"] += r["n"]; inv["by_state"][r["state"]] = r["n"]
        if r["state"] == "completed":
            inv["logical"] += r["logical"]
        returned |= {m for m in (r["rm"] or "").split(",") if m}
    inv["outcome_unknown"] = inv["by_state"].get("outcome_unknown", 0)
    rep["invocations"] = inv
    rep["returned_models"] = sorted(returned)
    rep["returned_model"] = ", ".join(sorted(returned)) or None
    rep["gates"]["schema_validity"] = {"value": q["schema_validity"], "floor": 1.0, "pass": q["schema_validity"] >= 1.0}
    rep["gates"]["unscored_candidates"] = {"value": q["unscored_candidates"], "floor": 0, "pass": q["unscored_candidates"] == 0}
    rep["gates"]["all_invocations_resolved"] = {"value": inv["outcome_unknown"], "floor": 0, "pass": inv["outcome_unknown"] == 0}
    rep["pass"] = all(g["pass"] for g in rep["gates"].values())
    rep["project_id"] = pid
    return rep


def format_ranking_report(rep: dict[str, Any]) -> str:
    q, v, e, p, inv = rep["quality"], rep["volume"], rep["economics"], rep["performance"], rep.get("invocations", {})
    pct = lambda x: "—" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    c = rep.get("contract") or {}
    lines = [f"Neuro Search ranking eval · {rep['tier']} · app {rep.get('app_version')} @ {rep.get('git_sha')} · fixture v{rep.get('fixture_version')} ({rep['candidates']} candidates, want {rep['want']})",
             "",
             "MODEL",
             f"  configured {rep.get('configured_model')}   returned {rep.get('returned_model') or '—'}   prompt {rep.get('prompt_version')}   canonical input tokens {rep.get('canonical_input_tokens') if rep.get('canonical_input_tokens') is not None else '—'} ({rep.get('canonical_requests')} request{'s' if rep.get('canonical_requests') != 1 else ''})",
             f"  contract   thinking={c.get('thinking')}{'/' + c['effort'] if c.get('effort') else ''}  max_out={c.get('max_output_tokens')}  attempts={c.get('max_attempts')}  timeout={c.get('timeout') or 'default'}",
             "",
             "RANKING QUALITY" + ("  (fake provider: lexical stand-in — proves the fixture, not the model)" if rep["tier"] != "live" else ""),
             f"  relevant = grade ≥ 2 ({q['relevant_candidates']} of {rep['candidates']}):   Precision@10 {pct(q['precision_at_10'])}   Recall@10 {pct(q['recall_at_10'])}   Recall@20 {pct(q['recall_at_20'])}   Precision@20 {pct(q['precision_at_20'])}",
             f"  strict   = grade 3   ({q['strict_candidates']} of {rep['candidates']}):   Precision@10 {pct(q['precision_at_10_strict'])}   Recall@10 {pct(q['recall_at_10_strict'])}   Recall@20 {pct(q['recall_at_20_strict'])}",
             f"  NDCG@20 {q['ndcg_at_20']}   (graded gains 0-3, ideal ordering = 1.0)",
             f"  Top 10 contains {q['irrelevant_in_top_10']} irrelevant · {q['clickbait_in_top_10']} clickbait;  top 20 contains {q['authoritative_low_view_in_top_20']}/{rep['by_category'].get('authoritative_low_view', {}).get('n', 0)} authoritative-low-view · {q['popular_irrelevant_in_top_20']} popular-irrelevant",
             "  by category            n   mean rank   mean score"]
    for k, d in rep["by_category"].items():
        lines.append(f"    {k:22s} {d['n']:2d}   {d['mean_rank']:9}   {d['mean_score']}")
    lines += ["",
              "SCHEMA",
              f"  validity {pct(q['schema_validity'])}   batches {q['batches']} · failed {q['failed_batches']} · repaired {q['repaired_batches']}   unscored candidates {q['unscored_candidates']}",
              f"  Provider calls  {inv.get('logical', 0)} logical · {inv.get('attempts', 0)} transport attempts · outcome unknown {inv.get('outcome_unknown', 0)}",
              "",
              "VOLUME",
              f"  {v['calls']} calls   input {v['input_tokens']:,}   output {v['output_tokens']:,}   cache read {v['cache_read_tokens']:,}   cache write {v['cache_write_tokens']:,}   ({v['tokens_per_candidate']} input tokens/candidate)",
              "",
              "ECONOMICS",
              f"  cost ${e['cost']:.4f}   per 100 candidates ${e['cost_per_100_candidates']:.4f}" + ("   [fake token estimates at list price]" if rep["tier"] != "live" else ""),
              "",
              "PERFORMANCE",
              f"  ranking {p['rank_s']}s   {p['s_per_batch']}s/batch   {p['s_per_100_candidates']}s per 100 candidates   total {p['total_s']}s",
              "",
              "GATES"]
    for k, g in rep["gates"].items():
        lines.append(f"  {'PASS' if g['pass'] else 'FAIL'}  {k:28s} {g['value']}  (floor {g['floor']})")
    lines += ["", f"Ranking eval: {'PASS' if rep['pass'] else 'FAIL'}"]
    return "\n".join(lines)


def compare_ranking(cur: dict[str, Any], base: dict[str, Any], cost_tolerance: float = 0.10) -> list[str]:
    out = []
    for k in ("precision_at_10", "recall_at_10", "recall_at_20", "precision_at_20", "precision_at_10_strict", "recall_at_10_strict", "recall_at_20_strict", "ndcg_at_20", "schema_validity", "unscored_candidates", "irrelevant_in_top_10", "clickbait_in_top_10"):
        v, b = cur["quality"].get(k), base.get("quality", {}).get(k)
        if isinstance(v, (int, float)) and isinstance(b, (int, float)) and v != b:
            out.append(f"{'▲' if v > b else '▼'} {k}: {b} → {v}")
    for k in ("input_tokens", "output_tokens", "cache_read_tokens"):
        b = base.get("volume", {}).get(k)
        if b and cur["volume"][k] != b:
            d = (cur["volume"][k] - b) / b
            out.append(f"{'▲' if d > 0 else '▼'} {k}: {b:,} → {cur['volume'][k]:,} ({d:+.0%})")
    bc = base.get("economics", {}).get("cost_per_100_candidates")
    if bc and cur["economics"]["cost_per_100_candidates"] != bc:
        d = (cur["economics"]["cost_per_100_candidates"] - bc) / bc
        out.append(f"{'▲' if d > 0 else '▼'} cost per 100 candidates: ${bc:.4f} → ${cur['economics']['cost_per_100_candidates']:.4f} ({d:+.0%}){'  ⚠ REGRESSION' if d > cost_tolerance else ''}")
    bl = base.get("performance", {}).get("rank_s")
    if bl and cur["performance"]["rank_s"] != bl:
        out.append(f"latency: {bl}s → {cur['performance']['rank_s']}s")
    if (cur.get("returned_model") or "") != (base.get("returned_model") or ""):
        out.append(f"returned model: {base.get('returned_model')} → {cur.get('returned_model')}")
    return out


# ------------------------------------------------------------------ ranking model comparison (E2.1/E2.2 in one command)

BASELINE_MODEL = "claude-sonnet-4-6"
CANDIDATE_MODEL = "claude-sonnet-5"
# quality tolerances: a candidate may not fall further than this below the baseline on the decision metrics (n=1 runs)
QUALITY_TOLERANCE = {"ndcg_at_20": 0.03, "precision_at_10": 0.10, "precision_at_20": 0.10, "recall_at_20_strict": 0.08, "recall_at_10_strict": 0.08}
COST_TOLERANCE, LATENCY_TOLERANCE = 0.10, 0.50


def _model_slug(m: str) -> str:
    return m.replace("/", "_").replace("claude-", "")


def model_matches(configured: str, returned: str | None) -> bool:
    """A returned id is the configured alias or a dated snapshot of it (claude-sonnet-5 → claude-sonnet-5-2026xxxx)."""
    if not returned:
        return False
    if configured == "fake" or returned.startswith("fake"):
        return True
    return any(r.strip().startswith(configured) for r in returned.split(","))


def ranking_verdict(base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    """Quality and validity decide; cost and latency only add caveats. Never changes a default."""
    bq, cq = base["quality"], cand["quality"]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    # validity gates on the candidate itself
    if cq["failed_batches"]:
        fails.append(f"{cq['failed_batches']} batch(es) failed outright")
    if cq["unscored_candidates"]:
        fails.append(f"{cq['unscored_candidates']} candidates left unscored")
    if cand["invocations"].get("outcome_unknown"):
        fails.append(f"{cand['invocations']['outcome_unknown']} invocation(s) with unknown outcome")
    if cq["repaired_batches"] > bq["repaired_batches"]:
        fails.append(f"schema validity regressed: {cq['repaired_batches']} batch(es) needed tolerant parsing vs {bq['repaired_batches']} on the baseline")
    if not model_matches(cand["configured_model"], cand.get("returned_model")):
        fails.append(f"returned model {cand.get('returned_model')!r} is not the configured {cand['configured_model']!r}")
    if not model_matches(base["configured_model"], base.get("returned_model")):
        fails.append(f"BASELINE returned model {base.get('returned_model')!r} is not the configured {base['configured_model']!r} — comparison is not like-for-like")
    # quality: decision metrics with tolerance
    for k, tol in QUALITY_TOLERANCE.items():
        b, c = bq.get(k), cq.get(k)
        if b is None or c is None:
            continue
        if c < b - tol - 1e-9:
            fails.append(f"{k} fell beyond tolerance: {b} → {c} (tolerance −{tol})")
        elif c < b:
            caveats.append(f"{k} slightly lower: {b} → {c} (within tolerance −{tol})")
    for k in ("recall_at_10", "recall_at_20"):
        if cq.get(k, 0) < bq.get(k, 0):
            caveats.append(f"{k} lower: {bq[k]} → {cq[k]}")
    if cq["irrelevant_in_top_10"] > bq["irrelevant_in_top_10"] + 1:
        fails.append(f"irrelevant candidates in top 10 rose {bq['irrelevant_in_top_10']} → {cq['irrelevant_in_top_10']}")
    elif cq["irrelevant_in_top_10"] > bq["irrelevant_in_top_10"]:
        caveats.append(f"irrelevant in top 10 rose {bq['irrelevant_in_top_10']} → {cq['irrelevant_in_top_10']}")
    if cq["clickbait_in_top_10"] > bq["clickbait_in_top_10"]:
        caveats.append(f"clickbait in top 10 rose {bq['clickbait_in_top_10']} → {cq['clickbait_in_top_10']}")
    if cq["popular_irrelevant_in_top_20"] > bq["popular_irrelevant_in_top_20"]:
        caveats.append(f"popular-but-irrelevant in top 20 rose {bq['popular_irrelevant_in_top_20']} → {cq['popular_irrelevant_in_top_20']}")
    if cq["authoritative_low_view_in_top_20"] < bq["authoritative_low_view_in_top_20"]:
        caveats.append(f"authoritative-low-view in top 20 fell {bq['authoritative_low_view_in_top_20']} → {cq['authoritative_low_view_in_top_20']}")
    if cq["repaired_batches"] and cq["repaired_batches"] <= bq["repaired_batches"]:
        caveats.append(f"{cq['repaired_batches']} batch(es) needed tolerant parsing (no worse than baseline)")
    # supporting metrics
    bc, cc = base["economics"]["cost_per_100_candidates"], cand["economics"]["cost_per_100_candidates"]
    if bc and cc > bc * (1 + COST_TOLERANCE):
        caveats.append(f"cost per 100 candidates up {(cc / bc - 1):+.0%}: ${bc:.4f} → ${cc:.4f}")
    bl, cl = base["performance"]["rank_s"], cand["performance"]["rank_s"]
    if bl and cl > bl * (1 + LATENCY_TOLERANCE):
        caveats.append(f"latency up {(cl / bl - 1):+.0%}: {bl}s → {cl}s")
    bt, ct = base.get("canonical_input_tokens"), cand.get("canonical_input_tokens")
    if bt and ct:
        notes.append(f"tokenizer delta on the canonical requests: {bt:,} → {ct:,} ({(ct / bt - 1):+.1%})")
    notes.append("single run per model (n=1): differences inside the tolerances are not distinguishable from run-to-run noise")
    if fails:
        verdict, headline = "FAIL", f"FAIL — keep {base['configured_model']} for rank.relevance"
    elif caveats:
        verdict, headline = "PASS_WITH_CAVEAT", f"PASS WITH CAVEAT — {cand['configured_model']} holds quality on rank.relevance; review the caveats before migrating"
    else:
        verdict, headline = "PASS", f"PASS — migrate rank.relevance to {cand['configured_model']}"
    return {"verdict": verdict, "headline": headline, "fails": fails, "caveats": caveats, "notes": notes,
            "production_default_changed": False,
            "how_to_migrate": "set NEUROSEARCH_TASK_MODEL_RANK_RELEVANCE=" + cand["configured_model"] + " (and THINKING=disabled) or change the rank.relevance contract; nothing was changed by this run"}


def _side_by_side(base: dict[str, Any], cand: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    def add(label: str, b: Any, c: Any, kind: str = "num") -> None:
        rows.append({"metric": label, "baseline": b, "candidate": c, "delta": (round(c - b, 4) if isinstance(b, (int, float)) and isinstance(c, (int, float)) and not isinstance(b, bool) else None), "kind": kind})
    bq, cq = base["quality"], cand["quality"]
    for k in ("precision_at_10", "precision_at_20", "recall_at_10", "recall_at_20", "precision_at_10_strict", "recall_at_10_strict", "recall_at_20_strict", "ndcg_at_20"):
        add(k, bq[k], cq[k])
    for k in ("irrelevant_in_top_10", "clickbait_in_top_10", "authoritative_low_view_in_top_20", "popular_irrelevant_in_top_20"):
        add(k, bq[k], cq[k])
    for cat in sorted(set(base["by_category"]) | set(cand["by_category"])):
        add(f"mean_rank[{cat}]", base["by_category"].get(cat, {}).get("mean_rank"), cand["by_category"].get(cat, {}).get("mean_rank"))
    for cat in sorted(set(base["by_category"]) | set(cand["by_category"])):
        add(f"mean_score[{cat}]", base["by_category"].get(cat, {}).get("mean_score"), cand["by_category"].get(cat, {}).get("mean_score"))
    for k in ("schema_validity", "batches", "failed_batches", "repaired_batches", "unscored_candidates"):
        add(k, bq[k], cq[k])
    add("outcome_unknown", base["invocations"].get("outcome_unknown", 0), cand["invocations"].get("outcome_unknown", 0))
    add("transport_attempts", base["invocations"].get("attempts", 0), cand["invocations"].get("attempts", 0))
    add("configured_model", base["configured_model"], cand["configured_model"], "text")
    add("returned_model", base.get("returned_model"), cand.get("returned_model"), "text")
    add("thinking", base["contract"]["thinking"], cand["contract"]["thinking"], "text")
    add("canonical_input_tokens", base.get("canonical_input_tokens"), cand.get("canonical_input_tokens"))
    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
        add("billed_" + k, base["volume"][k], cand["volume"][k])
    add("cost", base["economics"]["cost"], cand["economics"]["cost"])
    add("cost_per_100_candidates", base["economics"]["cost_per_100_candidates"], cand["economics"]["cost_per_100_candidates"])
    add("latency_rank_s", base["performance"]["rank_s"], cand["performance"]["rank_s"])
    add("latency_s_per_100_candidates", base["performance"]["s_per_100_candidates"], cand["performance"]["s_per_100_candidates"])
    return rows


def format_comparison(cmp: dict[str, Any]) -> str:
    b, c = cmp["baseline"], cmp["candidate"]
    bt, ct = b.get("canonical_input_tokens"), c.get("canonical_input_tokens")
    lines = [f"Neuro Search rank.relevance model comparison · {cmp['tier']} · app {cmp['app_version']} @ {cmp['git_sha']} · fixture v{b.get('fixture_version')} ({b['candidates']} candidates)",
             f"  baseline  {b['configured_model']} (returned {b.get('returned_model') or '—'}, thinking {b['contract']['thinking']})",
             f"  candidate {c['configured_model']} (returned {c.get('returned_model') or '—'}, thinking {c['contract']['thinking']})",
             f"  same prompt {b['prompt_version']} · same fixture · same contract except the model", "",
             f"  {'metric':40s} {'baseline':>14s} {'candidate':>14s} {'delta':>10s}"]
    section = None
    for r in cmp["rows"]:
        sec = ("quality" if r["metric"].split("[")[0] in ("precision_at_10", "precision_at_20", "recall_at_10", "recall_at_20", "precision_at_10_strict", "recall_at_10_strict", "recall_at_20_strict", "ndcg_at_20", "irrelevant_in_top_10", "clickbait_in_top_10", "authoritative_low_view_in_top_20", "popular_irrelevant_in_top_20")
               else "category" if r["metric"].startswith("mean_")
               else "validity" if r["metric"] in ("schema_validity", "batches", "failed_batches", "repaired_batches", "unscored_candidates", "outcome_unknown", "transport_attempts", "configured_model", "returned_model", "thinking")
               else "tokens" if "tokens" in r["metric"] else "economics")
        if sec != section:
            lines.append(f"  -- {sec.upper()}" + ("  (decision gate)" if sec in ("quality", "validity") else "  (supporting)" if sec in ("tokens", "economics") else ""))
            section = sec
        f = lambda v: "—" if v is None else (v if isinstance(v, str) else f"{v:,}" if isinstance(v, int) else f"{v:.4f}".rstrip("0").rstrip("."))  # noqa: E731
        d = "" if r["delta"] is None else f"{r['delta']:+.4f}".rstrip("0").rstrip(".")
        lines.append(f"  {r['metric']:40s} {f(r['baseline']):>14s} {f(r['candidate']):>14s} {d:>10s}")
    if bt and ct:
        lines.append(f"\n  tokenizer delta (canonical requests, provider token count): {bt:,} → {ct:,} = {(ct / bt - 1):+.1%}")
    v = cmp["verdict"]
    lines += ["", "VERDICT: " + v["headline"]]
    for x in v["fails"]:
        lines.append("  FAIL    " + x)
    for x in v["caveats"]:
        lines.append("  caveat  " + x)
    for x in v["notes"]:
        lines.append("  note    " + x)
    lines += ["", "  Production default unchanged. " + v["how_to_migrate"], "", "  files: " + ", ".join(cmp.get("files", []))]
    return "\n".join(lines)


def run_ranking_compare(root: Path = GOLDEN, live: bool = False, baseline_model: str = BASELINE_MODEL, candidate_model: str = CANDIDATE_MODEL,
                        out_dir: Path = Path("evals"), progress: Any = print) -> dict[str, Any]:
    """One command for E2.1 + E2.2: rank the frozen fixture with the baseline model and with the candidate (both
    thinking=disabled, nothing else different), save both raw results, freeze the baseline model's result as the ranking
    baseline if none exists, save the side-by-side comparison and return it with a verdict."""
    import os
    from . import __version__
    keys = {"NEUROSEARCH_TASK_MODEL_RANK_RELEVANCE": None, "NEUROSEARCH_TASK_THINKING_RANK_RELEVANCE": None, "NEUROSEARCH_TASK_EFFORT_RANK_RELEVANCE": None}
    saved = {k: os.environ.get(k) for k in keys}
    reps: dict[str, dict[str, Any]] = {}
    try:
        for label, model in (("baseline", baseline_model), ("candidate", candidate_model)):
            os.environ["NEUROSEARCH_TASK_MODEL_RANK_RELEVANCE"] = model
            os.environ["NEUROSEARCH_TASK_THINKING_RANK_RELEVANCE"] = "disabled"
            os.environ.pop("NEUROSEARCH_TASK_EFFORT_RANK_RELEVANCE", None)
            progress(f"[{label}] {model} · thinking disabled")
            reps[label] = run_ranking(root, live=live, progress=lambda m: progress("   " + m))
            progress(f"[{label}] NDCG@20 {reps[label]['quality']['ndcg_at_20']} · P@10 {reps[label]['quality']['precision_at_10']} · ${reps[label]['economics']['cost']:.4f} · {reps[label]['performance']['rank_s']}s · returned {reps[label].get('returned_model')}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    base, cand = reps["baseline"], reps["candidate"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sha = git_sha()
    d = out_dir / "ranking-compare" / f"{stamp}-{sha}"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for label, rep in reps.items():
        f = d / f"{label}-{_model_slug(rep['configured_model'])}.json"
        f.write_text(json.dumps(rep, indent=1)); files.append(str(f))
    # the frozen ranking baseline for the baseline model: written once, never overwritten here
    existing = sorted(out_dir.glob(f"baseline-rank-*-{_model_slug(base['model'])}.json"))
    if existing:
        baseline_file, baseline_written = existing[-1], False
    else:
        baseline_file = out_dir / f"baseline-rank-{__version__}-{sha}-{_model_slug(base['model'])}.json"
        baseline_file.write_text(json.dumps(base, indent=1)); baseline_written = True
        files.append(str(baseline_file))
    files += [str(d / "comparison.json"), str(d / "comparison.txt")]
    cmp: dict[str, Any] = {"eval": "ranking-compare", "tier": "live" if live else "fake", "app_version": __version__, "git_sha": sha, "started": stamp,
                           "baseline": base, "candidate": cand, "rows": _side_by_side(base, cand), "verdict": ranking_verdict(base, cand),
                           "ranking_baseline_file": str(baseline_file), "ranking_baseline_written": baseline_written, "files": files}
    text = format_comparison(cmp)
    (d / "comparison.json").write_text(json.dumps(cmp, indent=1))
    (d / "comparison.txt").write_text(text)
    cmp["text"] = text
    return cmp


# ------------------------------------------------------------------ findings.extract workload (E2.2 in one command)

FINDINGS_GATES = {"finding_quote_validity": 0.98, "stored_findings_verified": 1.0}
EVIDENCE_TOLERANCE = 0.10          # one nugget of ten: the 4.6 live runs vary by about that much
LOST_NUGGETS_FAIL = 2              # losing two nuggets the baseline found is a real regression, not noise


def _nugget_key(e: dict[str, Any]) -> str:
    return f"{e['source']}: {e['quote'][:60]}"


def run_findings(pid: str, ids: dict[str, str], man: dict[str, Any], live: bool = False, progress: Any = print, force: bool = False) -> dict[str, Any]:
    """Run the Golden Project findings workload (every ingested source, every transcript window) through the real
    findings.extract task under its contract and measure it. Sources must already be ingested (load_golden)."""
    from . import __version__, contracts, findings, providers
    from .evidence import quote_in_text
    c = contracts.contract("findings.extract")
    t_all = time.time()
    usage_from = time.time()
    rep: dict[str, Any] = {"eval": "findings", "tier": "live" if live else "fake", "model": "fake" if not live else c.model, "configured_model": c.model,
                           "app_version": __version__, "git_sha": git_sha(), "provider": "fake" if not live else c.provider,
                           "prompt_version": prompt_versions()["findings.extract"], "contract": c.describe(), "validators": "evidence.check_finding (quote must be in the window) + stored re-check",
                           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "gates": {}, "quality": {}, "volume": {}, "economics": {}, "performance": {}}
    work = {gid: sid for gid, sid in ids.items() if gid != "calc"}
    # canonical input tokens over the exact requests (free; also the preflight for the model id)
    reqs = [(gid, r) for gid, sid in work.items() for r in findings.canonical_requests(pid, sid)]
    try:
        client = providers.anthropic_client()
        strip = lambda sysb: [{k: v for k, v in b.items() if k != "cache_control"} for b in sysb] if isinstance(sysb, list) else sysb  # noqa: E731
        fmt = {"output_config": contracts.request_params(c)["output_config"]} if c.schema else {}
        rep["canonical_input_tokens"] = sum(int(client.messages.count_tokens(model=c.model, system=strip(r["system"]), messages=r["messages"], **fmt).input_tokens) for _, r in reqs)
    except Exception as e:  # noqa: BLE001
        if live:
            raise RuntimeError(f"token counting failed for model {c.model!r} (preflight, nothing was spent): {e}") from e
        rep["canonical_input_tokens"] = None
    rep["canonical_requests"] = len(reqs)

    events: list[dict[str, Any]] = []
    findings.OBSERVER = events.append
    t0 = time.time()
    per_source: dict[str, dict[str, Any]] = {}
    failed_sources: list[str] = []
    try:
        for gid, sid in work.items():
            try:
                res = findings.suggest_for_source(pid, sid, force=force)
            except Exception as e:  # noqa: BLE001
                progress(f"findings failed for {gid}: {e}")
                failed_sources.append(gid)
                per_source[gid] = {"suggested": 0, "rejected": 0, "windows": len(findings._windows(db.get_segments(sid), db.get_source(sid)["platform"])), "error": str(e)[:200]}
                continue
            per_source[gid] = {"suggested": res["suggested"], "rejected": res.get("rejected_quotes", 0), "substance": res.get("substance"),
                               "summary_chars": len(res.get("summary") or ""), "windows": len(findings._windows(db.get_segments(sid), db.get_source(sid)["platform"]))}
    finally:
        findings.OBSERVER = None
    rep["performance"]["findings_s"] = round(time.time() - t0, 2)
    suggested = sum(p["suggested"] for p in per_source.values())
    rejected = sum(p["rejected"] for p in per_source.values())
    windows = sum(p["windows"] for p in per_source.values())
    checked = suggested + rejected

    # independent re-check of what was stored
    notes = db.list_project_notes(pid, status="suggested")
    stored = stored_bad = 0
    for note in notes:
        cit = (note.get("citations") or [{}])[0]
        if not cit.get("source_id"):
            continue
        stored += 1
        full = " ".join(x["text"] for x in db.get_segments(cit["source_id"]))
        if cit.get("snippet") and not quote_in_text(cit["snippet"], full):
            stored_bad += 1
    # planted nuggets, individually
    nuggets: dict[str, bool] = {}
    for e in man["evidence"]:
        sid = ids[e["source"]]
        segs = db.get_segments(sid)
        where = next((s["start"] for s in segs if quote_in_text(e["quote"], s["text"])), None)
        hit = False
        if where is not None:
            for nnote in notes:
                cit = (nnote.get("citations") or [{}])[0]
                if cit.get("source_id") == sid and abs(float(cit.get("start") or 0) - where) <= 120:
                    hit = True
                    break
        nuggets[_nugget_key(e)] = hit
    q = rep["quality"]
    q["golden_evidence_recall"] = round(sum(nuggets.values()) / max(1, len(nuggets)), 4)
    q["nuggets"] = nuggets
    q["finding_quote_validity"] = round(1 - rejected / checked, 4) if checked else 1.0
    q["stored_findings_verified"] = round(1 - stored_bad / stored, 4) if stored else 1.0
    q["findings_suggested"] = suggested
    q["findings_rejected"] = rejected
    q["findings_candidates"] = checked
    q["sources"] = len(work)
    q["failed_sources"] = failed_sources
    q["transcript_windows"] = windows
    q["findings_per_source"] = round(suggested / max(1, len(work)), 2)
    q["findings_per_window"] = round(suggested / max(1, windows), 2)
    q["per_source"] = per_source
    ok_sum = sum(1 for p in per_source.values() if p.get("summary_chars"))
    ok_sub = sum(1 for p in per_source.values() if isinstance(p.get("substance"), int) and 0 <= p["substance"] <= 100)
    q["summary_validity"] = round(ok_sum / max(1, len(work)), 4)
    q["substance_validity"] = round(ok_sub / max(1, len(work)), 4)
    q["window_calls"] = len(events)
    q["truncated_windows"] = sum(1 for ev in events if ev.get("truncated"))
    q["parse_failed_windows"] = sum(1 for ev in events if ev.get("parse") == "failed" or ev.get("error"))
    q["no_json_windows"] = sum(1 for ev in events if ev.get("parse") == "no_json")
    q["repaired_windows"] = sum(1 for ev in events if ev.get("parse") == "repaired")
    q["empty_windows"] = sum(1 for ev in events if ev.get("raw_findings", 0) == 0 and not ev.get("error"))
    q["windows_missing_summary"] = sum(1 for ev in events if not ev.get("summary_ok"))
    q["windows_missing_substance"] = sum(1 for ev in events if not ev.get("substance_ok"))
    q["incomplete_outputs"] = q["truncated_windows"] + q["parse_failed_windows"] + q["no_json_windows"]
    q["raw_findings"] = sum(ev.get("raw_findings", 0) for ev in events)

    rows_u = db.connect().execute("SELECT model, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read) cr, SUM(cache_write) cw, SUM(cost) c, COUNT(*) n "
                                  "FROM usage WHERE ts>=? AND kind='findings' GROUP BY model", (usage_from,)).fetchall()
    tot = {k: 0 for k in ("i", "o", "cr", "cw", "c", "n")}
    for r in rows_u:
        for k in tot:
            tot[k] += (r[k] or 0)
    hours = sum((db.get_source(s) or {}).get("duration") or 0 for s in work.values()) / 3600
    rep["volume"] = {"calls": int(tot["n"]), "input_tokens": int(tot["i"]), "output_tokens": int(tot["o"]), "cache_read_tokens": int(tot["cr"]),
                     "cache_write_tokens": int(tot["cw"]), "canonical_input_tokens": rep.get("canonical_input_tokens"),
                     "output_tokens_per_window": round(tot["o"] / max(1, len(events)), 1)}
    rep["economics"] = {"cost": round(float(tot["c"]), 4), "cost_per_source_hour": round(float(tot["c"]) / hours, 4) if hours else None, "media_hours": round(hours, 2),
                        "cost_per_source": round(float(tot["c"]) / max(1, len(work)), 4)}
    rep["performance"].update({"s_per_window": round(rep["performance"]["findings_s"] / max(1, len(events)), 2), "s_per_source": round(rep["performance"]["findings_s"] / max(1, len(work)), 2),
                               "total_s": round(time.time() - t_all, 2)})
    inv_rows = db.connect().execute("SELECT state, COUNT(*) n, COUNT(DISTINCT logical_id) logical, GROUP_CONCAT(DISTINCT returned_model) rm "
                                    "FROM invocations WHERE requested_at>=? AND task='findings.extract' GROUP BY state", (usage_from,)).fetchall()
    inv: dict[str, Any] = {"logical": 0, "attempts": 0, "by_state": {}}
    returned: set[str] = set()
    for r in inv_rows:
        inv["attempts"] += r["n"]; inv["by_state"][r["state"]] = r["n"]
        if r["state"] == "completed":
            inv["logical"] += r["logical"]
        returned |= {m for m in (r["rm"] or "").split(",") if m}
    inv["outcome_unknown"] = inv["by_state"].get("outcome_unknown", 0)
    rep["invocations"] = inv
    rep["returned_models"] = sorted(returned)
    rep["returned_model"] = ", ".join(sorted(returned)) or None
    for k, floor in FINDINGS_GATES.items():
        rep["gates"][k] = {"value": q[k], "floor": floor, "pass": q[k] >= floor}
    rep["gates"]["incomplete_outputs"] = {"value": q["incomplete_outputs"], "floor": 0, "pass": q["incomplete_outputs"] == 0}
    rep["gates"]["all_invocations_resolved"] = {"value": inv["outcome_unknown"], "floor": 0, "pass": inv["outcome_unknown"] == 0}
    rep["gates"]["all_sources_analysed"] = {"value": len(failed_sources), "floor": 0, "pass": not failed_sources}
    rep["pass"] = all(g["pass"] for g in rep["gates"].values())
    return rep


def findings_verdict(base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    """Evidence recall and quote/validation integrity are the hard gates; the raw number of findings is not."""
    bq, cq = base["quality"], cand["quality"]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    # validity gates on the candidate itself
    for k, floor in FINDINGS_GATES.items():
        if cq[k] < floor:
            fails.append(f"{k} {cq[k]} is under the floor {floor}")
        elif cq[k] < bq[k]:
            caveats.append(f"{k} lower than baseline: {bq[k]} → {cq[k]} (above the floor {floor})")
    if cq["findings_rejected"] > bq["findings_rejected"]:
        caveats.append(f"more findings rejected by the quote validator: {bq['findings_rejected']} → {cq['findings_rejected']}")
    if cq["incomplete_outputs"]:
        fails.append(f"{cq['incomplete_outputs']} incomplete output(s): {cq['truncated_windows']} truncated, {cq['parse_failed_windows']} unparsable, {cq['no_json_windows']} without JSON")
    if cq["failed_sources"]:
        fails.append(f"sources not analysed: {', '.join(cq['failed_sources'])}")
    if cand["invocations"].get("outcome_unknown"):
        fails.append(f"{cand['invocations']['outcome_unknown']} invocation(s) with unknown outcome")
    if not model_matches(cand["configured_model"], cand.get("returned_model")):
        fails.append(f"returned model {cand.get('returned_model')!r} is not the configured {cand['configured_model']!r}")
    if not model_matches(base["configured_model"], base.get("returned_model")):
        fails.append(f"BASELINE returned model {base.get('returned_model')!r} is not the configured {base['configured_model']!r} — comparison is not like-for-like")
    # evidence recall, individually
    lost = [k for k, hit in bq["nuggets"].items() if hit and not cq["nuggets"].get(k)]
    gained = [k for k, hit in cq["nuggets"].items() if hit and not bq["nuggets"].get(k)]
    if cq["golden_evidence_recall"] < bq["golden_evidence_recall"] - EVIDENCE_TOLERANCE - 1e-9:
        fails.append(f"golden evidence recall fell beyond tolerance: {bq['golden_evidence_recall']} → {cq['golden_evidence_recall']} (tolerance −{EVIDENCE_TOLERANCE})")
    if len(lost) >= LOST_NUGGETS_FAIL:
        fails.append(f"{len(lost)} planted nuggets the baseline found were lost: " + "; ".join(lost))
    elif lost:
        caveats.append(f"{len(lost)} planted nugget the baseline found was lost: " + "; ".join(lost) + (f" (gained {len(gained)})" if gained else ""))
    elif cq["golden_evidence_recall"] < bq["golden_evidence_recall"]:
        caveats.append(f"golden evidence recall lower: {bq['golden_evidence_recall']} → {cq['golden_evidence_recall']}")
    if gained and not lost:
        notes.append(f"gained {len(gained)} nugget(s) the baseline missed: " + "; ".join(gained))
    # output shape (not gates)
    if cq["repaired_windows"] > bq["repaired_windows"]:
        caveats.append(f"more windows needed fence/prose stripping before JSON parsed: {bq['repaired_windows']} → {cq['repaired_windows']}")
    for k in ("summary_validity", "substance_validity"):
        if cq[k] < bq[k]:
            caveats.append(f"{k} lower: {bq[k]} → {cq[k]}")
    if cq["windows_missing_summary"] > bq["windows_missing_summary"] or cq["windows_missing_substance"] > bq["windows_missing_substance"]:
        caveats.append(f"windows missing summary/substance: {bq['windows_missing_summary']}/{bq['windows_missing_substance']} → {cq['windows_missing_summary']}/{cq['windows_missing_substance']}")
    if bq["findings_suggested"] and cq["findings_suggested"] < 0.7 * bq["findings_suggested"]:
        caveats.append(f"far fewer findings kept: {bq['findings_suggested']} → {cq['findings_suggested']} (count is not a gate; 4.6 runs vary too)")
    elif cq["findings_suggested"] != bq["findings_suggested"]:
        notes.append(f"findings kept: {bq['findings_suggested']} → {cq['findings_suggested']} (not a gate)")
    if cq["empty_windows"] > bq["empty_windows"]:
        caveats.append(f"windows with no findings at all: {bq['empty_windows']} → {cq['empty_windows']}")
    # supporting
    bc, cc = base["economics"]["cost"], cand["economics"]["cost"]
    if bc and cc > bc * (1 + COST_TOLERANCE):
        caveats.append(f"cost up {(cc / bc - 1):+.0%}: ${bc:.4f} → ${cc:.4f} (per source-hour ${base['economics']['cost_per_source_hour']} → ${cand['economics']['cost_per_source_hour']})")
    bl, cl = base["performance"]["findings_s"], cand["performance"]["findings_s"]
    if bl and cl > bl * (1 + LATENCY_TOLERANCE):
        caveats.append(f"latency up {(cl / bl - 1):+.0%}: {bl}s → {cl}s")
    bt, ct = base.get("canonical_input_tokens"), cand.get("canonical_input_tokens")
    if bt and ct:
        notes.append(f"tokenizer delta on the canonical requests: {bt:,} → {ct:,} ({(ct / bt - 1):+.1%})")
    notes.append("single run per model (n=1): differences inside the tolerances are not distinguishable from run-to-run noise")
    if fails:
        verdict, headline = "FAIL", f"FAIL — keep {base['configured_model']} for findings.extract"
    elif caveats:
        verdict, headline = "PASS_WITH_CAVEAT", f"PASS WITH CAVEAT — {cand['configured_model']} holds evidence recall and quote integrity on findings.extract; review the caveats before migrating"
    else:
        verdict, headline = "PASS", f"PASS — migrate findings.extract to {cand['configured_model']}"
    return {"verdict": verdict, "headline": headline, "fails": fails, "caveats": caveats, "notes": notes, "lost_nuggets": lost, "gained_nuggets": gained,
            "production_default_changed": False,
            "how_to_migrate": "set NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT=" + cand["configured_model"] + " (and THINKING=disabled) or change the findings.extract contract; nothing was changed by this run"}


def _findings_rows(base: dict[str, Any], cand: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []

    def add(label: str, b: Any, c: Any, kind: str = "num") -> None:
        rows.append({"metric": label, "baseline": b, "candidate": c, "delta": (round(c - b, 4) if isinstance(b, (int, float)) and isinstance(c, (int, float)) and not isinstance(b, bool) else None), "kind": kind})
    bq, cq = base["quality"], cand["quality"]
    for k in ("golden_evidence_recall", "finding_quote_validity", "stored_findings_verified", "findings_rejected"):
        add(k, bq[k], cq[k])
    for key in bq["nuggets"]:
        add(f"nugget[{key}]", "found" if bq["nuggets"][key] else "missed", "found" if cq["nuggets"].get(key) else "missed", "text")
    for k in ("findings_suggested", "raw_findings", "findings_per_source", "findings_per_window", "transcript_windows", "window_calls", "empty_windows"):
        add(k, bq[k], cq[k])
    for gid in bq["per_source"]:
        add(f"findings[{gid}]", bq["per_source"][gid]["suggested"], cq["per_source"].get(gid, {}).get("suggested"))
    for k in ("summary_validity", "substance_validity", "windows_missing_summary", "windows_missing_substance"):
        add(k, bq[k], cq[k])
    for gid in bq["per_source"]:
        add(f"substance[{gid}]", bq["per_source"][gid].get("substance"), cq["per_source"].get(gid, {}).get("substance"))
    for k in ("truncated_windows", "parse_failed_windows", "no_json_windows", "repaired_windows", "incomplete_outputs"):
        add(k, bq[k], cq[k])
    add("failed_sources", len(bq["failed_sources"]), len(cq["failed_sources"]))
    add("outcome_unknown", base["invocations"].get("outcome_unknown", 0), cand["invocations"].get("outcome_unknown", 0))
    add("transport_attempts", base["invocations"].get("attempts", 0), cand["invocations"].get("attempts", 0))
    add("configured_model", base["configured_model"], cand["configured_model"], "text")
    add("returned_model", base.get("returned_model"), cand.get("returned_model"), "text")
    add("thinking", base["contract"]["thinking"], cand["contract"]["thinking"], "text")
    add("canonical_input_tokens", base.get("canonical_input_tokens"), cand.get("canonical_input_tokens"))
    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens_per_window"):
        add("billed_" + k if "per" not in k else k, base["volume"][k], cand["volume"][k])
    add("cost", base["economics"]["cost"], cand["economics"]["cost"])
    add("cost_per_source_hour", base["economics"]["cost_per_source_hour"], cand["economics"]["cost_per_source_hour"])
    add("cost_per_source", base["economics"]["cost_per_source"], cand["economics"]["cost_per_source"])
    add("latency_findings_s", base["performance"]["findings_s"], cand["performance"]["findings_s"])
    add("latency_s_per_window", base["performance"]["s_per_window"], cand["performance"]["s_per_window"])
    return rows


_FINDINGS_SECTIONS = {"evidence": ("golden_evidence_recall", "finding_quote_validity", "stored_findings_verified", "findings_rejected", "nugget"),
                      "findings (not a gate)": ("findings_suggested", "raw_findings", "findings_per_source", "findings_per_window", "transcript_windows", "window_calls", "empty_windows", "findings"),
                      "summary/substance": ("summary_validity", "substance_validity", "windows_missing_summary", "windows_missing_substance", "substance"),
                      "output integrity (decision gate)": ("truncated_windows", "parse_failed_windows", "no_json_windows", "repaired_windows", "incomplete_outputs", "failed_sources", "outcome_unknown", "transport_attempts", "configured_model", "returned_model", "thinking"),
                      "tokens (supporting)": ("canonical_input_tokens", "billed_input_tokens", "billed_output_tokens", "billed_cache_read_tokens", "billed_cache_write_tokens", "output_tokens_per_window"),
                      "economics / latency (supporting)": ("cost", "cost_per_source_hour", "cost_per_source", "latency_findings_s", "latency_s_per_window")}


def format_findings_comparison(cmp: dict[str, Any]) -> str:
    b, c = cmp["baseline"], cmp["candidate"]
    bt, ct = b.get("canonical_input_tokens"), c.get("canonical_input_tokens")
    lines = [f"Neuro Search findings.extract model comparison · {cmp['tier']} · app {cmp['app_version']} @ {cmp['git_sha']} · Golden Project ({b['quality']['sources']} sources, {b['quality']['transcript_windows']} windows, {b['economics']['media_hours']} h)",
             f"  baseline  {b['configured_model']} (returned {b.get('returned_model') or '—'}, thinking {b['contract']['thinking']})",
             f"  candidate {c['configured_model']} (returned {c.get('returned_model') or '—'}, thinking {c['contract']['thinking']})",
             f"  same sources, windows ({__import__('neurosearch.findings', fromlist=['WINDOW_CHARS']).WINDOW_CHARS} chars), brief, prompt {b['prompt_version']}, validators, contract except the model",
             "", f"  {'metric':52s} {'baseline':>14s} {'candidate':>14s} {'delta':>10s}"]
    section = None
    for r in cmp["rows"]:
        stem = r["metric"].split("[")[0]
        sec = next((name for name, keys in _FINDINGS_SECTIONS.items() if stem in keys), "other")
        if sec == "evidence":
            sec = "evidence (decision gate)"
        if sec != section:
            lines.append(f"  -- {sec.upper()}")
            section = sec
        f = lambda v: "—" if v is None else (v if isinstance(v, str) else f"{v:,}" if isinstance(v, int) else f"{v:.4f}".rstrip("0").rstrip("."))  # noqa: E731
        d = "" if r["delta"] is None else f"{r['delta']:+.4f}".rstrip("0").rstrip(".")
        lines.append(f"  {r['metric'][:52]:52s} {f(r['baseline']):>14s} {f(r['candidate']):>14s} {d:>10s}")
    if bt and ct:
        lines.append(f"\n  tokenizer delta (canonical requests, provider token count): {bt:,} → {ct:,} = {(ct / bt - 1):+.1%}")
    v = cmp["verdict"]
    lines += ["", "VERDICT: " + v["headline"]]
    for x in v["fails"]:
        lines.append("  FAIL    " + x)
    for x in v["caveats"]:
        lines.append("  caveat  " + x)
    for x in v["notes"]:
        lines.append("  note    " + x)
    lines += ["", "  Production default unchanged. " + v["how_to_migrate"], "", "  files: " + ", ".join(cmp.get("files", []))]
    return "\n".join(lines)


def run_findings_compare(root: Path = GOLDEN, live: bool = False, baseline_model: str = BASELINE_MODEL, candidate_model: str = CANDIDATE_MODEL,
                         out_dir: Path = Path("evals"), progress: Any = print) -> dict[str, Any]:
    """One command for E2.2: ingest the Golden Project once, run the findings workload with the baseline model and then
    with the candidate (both thinking=disabled, nothing else different; the second pass is forced past the input_hash
    idempotency so the same inputs are analysed again), save both raw results, freeze the baseline model's result as
    the findings baseline if none exists, save the side-by-side and the verdict. Never changes a default."""
    import os
    from . import __version__
    keys = ("NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT", "NEUROSEARCH_TASK_THINKING_FINDINGS_EXTRACT", "NEUROSEARCH_TASK_EFFORT_FINDINGS_EXTRACT")
    saved = {k: os.environ.get(k) for k in keys}
    t0 = time.time()
    g = load_golden(root)
    pid, ids, man = g["project_id"], g["sources"], g["manifest"]
    progress(f"ingested {len(ids)} golden sources in {time.time() - t0:.1f}s (embeddings are not part of the findings accounting)")
    reps: dict[str, dict[str, Any]] = {}
    try:
        for label, model in (("baseline", baseline_model), ("candidate", candidate_model)):
            os.environ["NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT"] = model
            os.environ["NEUROSEARCH_TASK_THINKING_FINDINGS_EXTRACT"] = "disabled"
            os.environ.pop("NEUROSEARCH_TASK_EFFORT_FINDINGS_EXTRACT", None)
            progress(f"[{label}] {model} · thinking disabled")
            reps[label] = run_findings(pid, ids, man, live=live, progress=lambda m: progress("   " + m), force=True)
            q = reps[label]["quality"]
            progress(f"[{label}] evidence recall {q['golden_evidence_recall']} · quote validity {q['finding_quote_validity']} · {q['findings_suggested']} findings ({q['findings_rejected']} rejected) · "
                     f"incomplete {q['incomplete_outputs']} · ${reps[label]['economics']['cost']:.4f} · {reps[label]['performance']['findings_s']}s · returned {reps[label].get('returned_model')}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    base, cand = reps["baseline"], reps["candidate"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    sha = git_sha()
    d = out_dir / "findings-compare" / f"{stamp}-{sha}"
    d.mkdir(parents=True, exist_ok=True)
    files = []
    for label, rep in reps.items():
        f = d / f"{label}-{_model_slug(rep['configured_model'])}.json"
        f.write_text(json.dumps(rep, indent=1)); files.append(str(f))
    existing = sorted(out_dir.glob(f"baseline-findings-*-{_model_slug(base['model'])}.json"))
    if existing:
        baseline_file, baseline_written = existing[-1], False
    else:
        baseline_file = out_dir / f"baseline-findings-{__version__}-{sha}-{_model_slug(base['model'])}.json"
        baseline_file.write_text(json.dumps(base, indent=1)); baseline_written = True
        files.append(str(baseline_file))
    files += [str(d / "comparison.json"), str(d / "comparison.txt")]
    cmp: dict[str, Any] = {"eval": "findings-compare", "tier": "live" if live else "fake", "app_version": __version__, "git_sha": sha, "started": stamp,
                           "baseline": base, "candidate": cand, "rows": _findings_rows(base, cand), "verdict": findings_verdict(base, cand),
                           "findings_baseline_file": str(baseline_file), "findings_baseline_written": baseline_written, "files": files, "project_id": pid}
    text = format_findings_comparison(cmp)
    (d / "comparison.json").write_text(json.dumps(cmp, indent=1))
    (d / "comparison.txt").write_text(text)
    cmp["text"] = text
    return cmp
