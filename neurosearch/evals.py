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
                           "thinking_policy": "n/a (model has no adaptive thinking; nothing requested)", "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
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
    rep["gates"]["fixture_evidence_present"] = {"value": rep["quality"]["fixture_evidence_present"], "floor": 1.0, "pass": rep["quality"]["fixture_evidence_present"] == 1.0}
    rep["pass"] = all(g["pass"] for g in rep["gates"].values())
    rep["project_id"] = pid
    return rep


# ------------------------------------------------------------------ reporting

def format_report(rep: dict[str, Any]) -> str:
    q, v, e, p = rep["quality"], rep["volume"], rep["economics"], rep["performance"]
    pct = lambda x: "—" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    fake = rep["tier"] != "live"
    lines = [f"Neuro Search eval · {rep['tier']} · model {rep['model']} · app {rep.get('app_version')} @ {rep.get('git_sha')}", "",
             "PIPELINE QUALITY  (does Neuro Search process AI-shaped output correctly?)",
             f"  Retrieval recall@5 / @10   {pct(q.get('retrieval_recall_at_5'))} / {pct(q.get('retrieval_recall_at_10'))}   MRR {q.get('retrieval_mrr')}   locator {pct(q.get('locator_accuracy'))}   ({q.get('questions')} questions)",
             f"  Citation integrity         {pct(q.get('citation_validity'))}   (invalid [n] caught, repaired or flagged)",
             f"  Evidence integrity         {pct(q.get('finding_quote_validity'))}   ({q.get('findings_suggested')} findings kept, {q.get('findings_rejected')} rejected; stored re-verified {pct(q.get('stored_findings_verified'))})",
             f"  Plan evidence integrity    {pct(q.get('plan_evidence_validity'))}   ({q.get('plan_evidence_refs')} references)" + (f"   ERROR {q['plan_error']}" if q.get("plan_error") else ""),
             f"  Calculator                 {'ok' if q.get('calculator_ok') else 'FAILED'}   DSCR {q.get('calculator_dscr')}",
             f"  Validation events          " + (", ".join(f"{k} {n}" for k, n in (rep.get("validation_events") or {}).items()) or "none"),
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
