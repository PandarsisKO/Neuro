"""Rung H1 — the findings pre-filter eval (`neurosearch eval --prefilter`).

Labeled window fixture = the Golden Project's own windows (labels.json "golden") + tests/fixtures/golden/prefilter/*
(two long irrelevant sources, one mixed source with a relevant second window, one 95%-filler window with a buried
nugget). For each filter mode (whole window; sampled) it measures what Kyle asked for:

  relevant-window recall · false negatives · every planted nugget still reachable (its window kept) · no relevant source
  loses all its windows · keep/uncertain/drop counts · % windows and % tokens safely skipped · findings.extract input
  tokens avoided · filter tokens/cost spent · net model cost saved · filter leverage (avoided cost / filter cost) ·
  fail-open count · configured/returned model + contract provenance

then runs the real findings path with the filter ON and checks golden evidence recall against the unfiltered run.
Hard gates (initial fixture): recall 100%, 0 false negatives, 100% nuggets reachable, no relevant source emptied.
The objective is NOT classifier accuracy: maximise safely avoided extractor work at zero relevant-window loss.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import db
from .config import settings

HERE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden"
PREFILTER_DIR = HERE / "prefilter"
EXTRACT_OUT_TOKENS = 600                 # findings.extract output per window (same assumption as usage.estimate_findings)


def load_labeled(project_id: str, golden_ids: dict[str, str]) -> dict[str, Any]:
    """Add the pre-filter fixture sources to the golden project; return the labeled windows for every source."""
    from . import findings, ingest
    labels = json.loads((PREFILTER_DIR / "labels.json").read_text())
    ids: dict[str, str] = dict(golden_ids)
    was = settings.auto_suggest
    settings.auto_suggest = False
    try:
        for s in labels["sources"]:
            payload = json.loads((PREFILTER_DIR / s["file"]).read_text())
            payload.update({k: s.get(k) for k in ("platform", "external_id", "url", "title", "channel")})
            payload["transcript_kind"] = "captions"
            ids[s["id"]] = ingest.store_transcript(payload, project_id=project_id)["source_id"]
    finally:
        settings.auto_suggest = was
    relevant: dict[str, list[bool]] = {**labels["golden"], **{s["id"]: s["relevant"] for s in labels["sources"]}}
    nuggets = [{"source": s["id"], "window": n["window"], "quote": n["quote"], "why": n["why"]} for s in labels["sources"] for n in s["nuggets"]]
    man = json.loads((HERE / "manifest.json").read_text())
    windows: dict[str, list[str]] = {}
    for gid, sid in ids.items():
        src = db.get_source(sid)
        windows[gid] = findings._windows(db.get_segments(sid), src["platform"])
        assert len(windows[gid]) == len(relevant[gid]), f"{gid}: fixture has {len(windows[gid])} windows, labels {len(relevant[gid])} — regenerate labels"
    for e in man["evidence"]:                                  # golden nuggets: locate their window
        w = next((i for i, t in enumerate(windows[e["source"]]) if e["quote"].lower() in t.lower()), None)
        assert w is not None, f"golden nugget not found in any window: {e['quote'][:50]}"
        nuggets.append({"source": e["source"], "window": w, "quote": e["quote"], "why": e["why"]})
    for n in nuggets:
        assert n["quote"].lower() in windows[n["source"]][n["window"]].lower(), f"nugget not in its labeled window: {n}"
    return {"ids": ids, "relevant": relevant, "nuggets": nuggets, "windows": windows}


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def run(progress: Any = print, modes: tuple[int, ...] = (0, 8000)) -> dict[str, Any]:
    from . import evals, findings, prefilter, usage
    from .contracts import contract
    t0 = time.time()
    g = evals.load_golden()
    pid = g["project_id"]
    lab = load_labeled(pid, g["sources"])
    ids, relevant, nuggets, windows = lab["ids"], lab["relevant"], lab["nuggets"], lab["windows"]
    project = db.get_project(pid)
    c_pf, c_fx = contract(prefilter.TASK), contract("findings.extract")
    pf_in, pf_out = usage._price(c_pf.model)
    fx_in, fx_out = usage._price(c_fx.model)
    n_windows = sum(len(w) for w in windows.values())
    n_relevant = sum(sum(1 for r in v if r) for v in relevant.values())
    rep: dict[str, Any] = {"eval": "prefilter", "tier": "fake" if settings.fake_ai else "live", "fixture": {"sources": len(ids), "windows": n_windows, "relevant_windows": n_relevant,
                           "irrelevant_windows": n_windows - n_relevant, "nuggets": len(nuggets), "chars": sum(len(t) for w in windows.values() for t in w)},
                           "contracts": {"prefilter": {"task": c_pf.task, "model": c_pf.model, "schema": c_pf.schema, "prompt_version": prefilter.prompt_version(), "price_in": pf_in, "price_out": pf_out},
                                         "extract": {"task": c_fx.task, "model": c_fx.model, "schema": c_fx.schema, "price_in": fx_in, "price_out": fx_out}},
                           "modes": {}}
    progress(f"fixture: {len(ids)} sources, {n_windows} windows ({n_relevant} relevant, {n_windows - n_relevant} irrelevant), {len(nuggets)} nuggets, "
             f"{rep['fixture']['chars']:,} chars · filter {c_pf.model} @ ${pf_in}/${pf_out} vs extractor {c_fx.model} @ ${fx_in}/${fx_out} per Mtok")
    # extractor input tokens per window as the fake bills them (request text / 4): what a drop avoids
    extract_tokens: dict[tuple[str, int], int] = {}
    for gid, sid in ids.items():
        for i, r in enumerate(findings.canonical_requests(pid, sid)):
            sys_text = "\n".join(b["text"] for b in r["system"])
            extract_tokens[(gid, i)] = _tokens(sys_text + r["messages"][0]["content"])
    # unfiltered reference run: golden evidence recall without the filter
    was_flag = settings.findings_prefilter
    settings.findings_prefilter = False
    for sid in ids.values():
        findings.suggest_for_source(pid, sid, force=True)
    base_recall = _evidence_recall(pid, ids, nuggets)
    rep["unfiltered_evidence_recall"] = base_recall
    for mode in modes:
        label = "whole window" if mode == 0 else f"sampled {mode:,} chars"
        m: dict[str, Any] = {"sample_chars": mode, "label": label, "decisions": {"keep": 0, "uncertain": 0, "drop": 0}, "fail_open": 0, "false_negatives": [],
                             "lost_relevant_sources": [], "unreachable_nuggets": [], "windows_dropped": 0, "chars_dropped": 0, "per_source": {}}
        filter_in = filter_out = 0
        avoided_in = avoided_out = 0
        returned_models: set[str] = set()
        for gid, sid in ids.items():
            src = db.get_source(sid)
            rows = prefilter.decide_windows(project, src, windows[gid], sample_chars=mode)
            per = {"windows": len(rows), "decisions": [r["decision"] for r in rows], "relevant": relevant[gid], "fail_open": [r.get("fail_open") for r in rows]}
            m["per_source"][gid] = per
            dropped_here = 0
            for r in rows:
                m["decisions"][r["decision"]] += 1
                if r.get("fail_open"):
                    m["fail_open"] += 1
                if r.get("model"):
                    returned_models.add(str(r["model"]))
                filter_in += int(r.get("input_tokens") or 0); filter_out += int(r.get("output_tokens") or 0)
                i = r["window_index"]
                if r["decision"] == "drop":
                    dropped_here += 1
                    m["windows_dropped"] += 1
                    m["chars_dropped"] += len(windows[gid][i])
                    avoided_in += extract_tokens[(gid, i)]; avoided_out += EXTRACT_OUT_TOKENS
                    if relevant[gid][i]:
                        m["false_negatives"].append({"source": gid, "window": i})
            if any(relevant[gid]) and dropped_here == len(rows):
                m["lost_relevant_sources"].append(gid)
        for n in nuggets:
            if m["per_source"][n["source"]]["decisions"][n["window"]] == "drop":
                m["unreachable_nuggets"].append(n)
        # the real findings path with the filter ON: evidence recall must equal the unfiltered run
        settings.findings_prefilter = True
        prefilter.SAMPLE_CHARS, keep_sc = mode, prefilter.SAMPLE_CHARS
        try:
            for sid in ids.values():
                findings.suggest_for_source(pid, sid, force=True)
        finally:
            prefilter.SAMPLE_CHARS = keep_sc
            settings.findings_prefilter = False
        m["filtered_evidence_recall"] = _evidence_recall(pid, ids, nuggets)
        an = db.get_analysis(pid, ids["beekeeping"], "summary") or {}
        m["provenance_example"] = json.loads(an["prefilter"]) if an.get("prefilter") else None
        # economics against the transport Neuro Search would actually have used (list prices; the fake's tokens are chars/4 on both
        # sides): interactive = Sonnet 5 standard; background = Sonnet 5 Message Batch (BATCH_MULT); the filter itself standard or batched
        total_extract_in = sum(extract_tokens.values())
        total_extract_out = n_windows * EXTRACT_OUT_TOKENS
        m["scenarios"] = economics(filter_in, filter_out, total_extract_in, total_extract_out, avoided_in, avoided_out, (pf_in, pf_out), (fx_in, fx_out), usage.BATCH_MULT)
        inter, bg = m["scenarios"]["interactive"], m["scenarios"]["background"]
        m.update({"recall": round(1 - len(m["false_negatives"]) / max(1, n_relevant), 4), "windows_dropped_share": round(m["windows_dropped"] / n_windows, 4),
                  "tokens_dropped_share": round(avoided_in / max(1, total_extract_in), 4),
                  "extract_input_tokens_total": total_extract_in, "extract_input_tokens_avoided": avoided_in, "extract_output_tokens_avoided": avoided_out,
                  "filter_input_tokens": filter_in, "filter_output_tokens": filter_out,
                  # headline figures = the interactive comparison (kept for continuity); the background comparison is the one that gates
                  "filter_cost": inter["filter_cost"], "avoided_cost": inter["avoided_cost"], "net_saved": inter["net_saved"], "leverage": inter["leverage"],
                  "unfiltered_extract_cost": inter["baseline_cost"], "net_saved_share": inter["net_saved_share"], "returned_models": sorted(returned_models)})
        m["gates"] = {"recall_100": m["recall"] == 1.0, "zero_false_negatives": not m["false_negatives"], "nuggets_reachable": not m["unreachable_nuggets"],
                      "no_relevant_source_emptied": not m["lost_relevant_sources"], "evidence_recall_preserved": m["filtered_evidence_recall"] >= base_recall,
                      # the economic gate (Kyle, H1 pause): on the BACKGROUND bulk path the filter must save ≥10% net against plain Sonnet 5
                      # batching with leverage ≥1.25× — with the filter run the way the product would run it there (standard, single stage)
                      "background_net_saving_10pct": bg["net_saved_share"] >= BACKGROUND_MIN_NET_SHARE, "background_leverage_1_25": (bg["leverage"] or 0) >= BACKGROUND_MIN_LEVERAGE}
        m["quality_pass"] = all(v for k, v in m["gates"].items() if not k.startswith("background_"))
        m["economics_pass"] = m["gates"]["background_net_saving_10pct"] and m["gates"]["background_leverage_1_25"]
        m["pass"] = m["quality_pass"] and m["economics_pass"]
        rep["modes"][label] = m
        progress(f"  {label:22s} keep {m['decisions']['keep']:2d} · uncertain {m['decisions']['uncertain']:2d} · drop {m['decisions']['drop']:2d} · fail-open {m['fail_open']} · "
                 f"recall {m['recall']:.0%} · FN {len(m['false_negatives'])} · windows skipped {m['windows_dropped_share']:.0%} · tokens skipped {m['tokens_dropped_share']:.0%} · "
                 f"net ${m['net_saved']:+.4f} ({m['net_saved_share']:+.0%}) · leverage {m['leverage']}× · {'PASS' if m['pass'] else 'FAIL'}")
    settings.findings_prefilter = was_flag
    rep["seconds"] = round(time.time() - t0, 1)
    # the verdict is the PRODUCTION mode's (prefilter.SAMPLE_CHARS); other modes are experiments reported beside it
    prod = next((m for m in rep["modes"].values() if m["sample_chars"] == prefilter.SAMPLE_CHARS), None)
    rep["production_mode"] = prod["label"] if prod else None
    rep["pass"] = bool(prod and prod["pass"])
    rep["text"] = format_report(rep)
    return rep


BACKGROUND_MIN_NET_SHARE = 0.10          # kill threshold (Kyle): ≥10% net model-cost saving vs plain Sonnet 5 Message Batch on the bulk path
BACKGROUND_MIN_LEVERAGE = 1.25           # and avoided cost ≥ 1.25× the filter's own cost


def economics(filter_in: int, filter_out: int, extract_in: int, extract_out: int, avoided_in: int, avoided_out: int,
              pf_price: tuple[float, float], fx_price: tuple[float, float], batch_mult: float) -> dict[str, dict[str, Any]]:
    """Net dollars per transport the product would actually use. Each scenario: baseline (no filter, that transport), filter cost,
    extractor cost on the kept windows, total, net saved, share of the baseline, leverage (avoided / filter cost) and the
    BREAK-EVEN irrelevant-token share — the fraction of extractor tokens a corpus must waste before this scenario saves anything."""
    pf_in, pf_out = pf_price
    fx_in, fx_out = fx_price

    def cost(tin: int, tout: int, price: tuple[float, float], mult: float = 1.0) -> float:
        return (tin / 1e6 * price[0] + tout / 1e6 * price[1]) * mult

    out: dict[str, dict[str, Any]] = {}
    for key, label, fmult, xmult, stages, latency in (
        ("interactive", "interactive: Haiku filter (standard) + Sonnet 5 standard on kept windows  vs  Sonnet 5 standard", 1.0, 1.0, 1, "adds one short model call per window before extraction"),
        ("background", "background: Haiku filter (standard) + Sonnet 5 BATCH on kept windows  vs  Sonnet 5 batch", 1.0, batch_mult, 1, "filter runs interactively while the batch is planned; no added batch stage"),
        ("background_batched_filter", "background: Haiku filter BATCHED + Sonnet 5 batch on kept windows  vs  Sonnet 5 batch", batch_mult, batch_mult, 2, "TWO sequential batches: the findings batch can only be formed after the filter batch ends — each stage may take up to 24 h"),
    ):
        baseline = cost(extract_in, extract_out, fx_price, xmult)
        f_cost = cost(filter_in, filter_out, pf_price, fmult)
        kept = cost(extract_in - avoided_in, extract_out - avoided_out, fx_price, xmult)
        avoided = cost(avoided_in, avoided_out, fx_price, xmult)
        total = f_cost + kept
        out[key] = {"label": label, "baseline_cost": round(baseline, 6), "filter_cost": round(f_cost, 6), "kept_extract_cost": round(kept, 6), "total_cost": round(total, 6),
                    "avoided_cost": round(avoided, 6), "net_saved": round(baseline - total, 6), "net_saved_share": round((baseline - total) / baseline, 4) if baseline else 0.0,
                    "leverage": round(avoided / f_cost, 2) if f_cost else None, "break_even_irrelevant_token_share": round(f_cost / baseline, 4) if baseline else None,
                    "batch_stages": stages, "latency": latency}
    return out


def _evidence_recall(pid: str, ids: dict[str, str], nuggets: list[dict[str, Any]]) -> float:
    """Share of planted nuggets represented by a suggested finding within 120 s / the same page (Tier 1's rule)."""
    from .evidence import quote_in_text
    notes = db.list_project_notes(pid, status="suggested")
    hit = 0
    for e in nuggets:
        sid = ids[e["source"]]
        segs = db.get_segments(sid)
        where = next((s["start"] for s in segs if quote_in_text(e["quote"], s["text"])), None)
        if where is None:
            continue
        for n in notes:
            c = (n.get("citations") or [{}])[0]
            if c.get("source_id") == sid and abs(float(c.get("start") or 0) - where) <= 120:
                hit += 1
                break
    return round(hit / max(1, len(nuggets)), 4)


def format_report(rep: dict[str, Any]) -> str:
    f, cp, cx = rep["fixture"], rep["contracts"]["prefilter"], rep["contracts"]["extract"]
    lines = [f"Findings pre-filter eval ({rep['tier']}) · {rep['seconds']}s",
             f"  fixture: {f['sources']} sources · {f['windows']} windows ({f['relevant_windows']} relevant / {f['irrelevant_windows']} irrelevant) · {f['nuggets']} planted nuggets · {f['chars']:,} chars",
             f"  filter {cp['model']} ({cp['schema']}, {cp['prompt_version']}) @ ${cp['price_in']}/${cp['price_out']} per Mtok · extractor {cx['model']} ({cx['schema']}) @ ${cx['price_in']}/${cx['price_out']}",
             f"  unfiltered golden evidence recall {rep['unfiltered_evidence_recall']:.0%}"]
    for label, m in rep["modes"].items():
        d = m["decisions"]
        lines += [f"  [{label}]",
                  f"    keep {d['keep']} · uncertain {d['uncertain']} · drop {d['drop']} · fail-open {m['fail_open']} · returned model {', '.join(m['returned_models']) or '—'}",
                  f"    relevant-window recall {m['recall']:.0%} · false negatives {len(m['false_negatives'])} · nuggets unreachable {len(m['unreachable_nuggets'])} · relevant sources emptied {len(m['lost_relevant_sources'])}",
                  f"    windows skipped {m['windows_dropped']}/{f['windows']} ({m['windows_dropped_share']:.0%}) · extractor input tokens avoided {m['extract_input_tokens_avoided']:,}/{m['extract_input_tokens_total']:,} ({m['tokens_dropped_share']:.0%})",
                  f"    filter spent {m['filter_input_tokens']:,} in / {m['filter_output_tokens']:,} out · evidence recall with the filter {m['filtered_evidence_recall']:.0%}"]
        for sc in m["scenarios"].values():
            lines.append(f"    {sc['label']}")
            lines.append(f"      baseline ${sc['baseline_cost']:.4f} · filter ${sc['filter_cost']:.4f} + kept extraction ${sc['kept_extract_cost']:.4f} = ${sc['total_cost']:.4f} · NET ${sc['net_saved']:+.4f} ({sc['net_saved_share']:+.1%}) · leverage {sc['leverage']}× · break-even irrelevant share {sc['break_even_irrelevant_token_share']:.0%} · {sc['latency']}")
        lines.append(f"    quality gates {', '.join(k for k, v in m['gates'].items() if not v and not k.startswith('background_')) or 'all pass'} · economic gate (background ≥{BACKGROUND_MIN_NET_SHARE:.0%} net, ≥{BACKGROUND_MIN_LEVERAGE}× leverage) {'PASS' if m['economics_pass'] else 'FAIL'} → {'PASS' if m['pass'] else 'FAIL'}")
        if m["false_negatives"] or m["unreachable_nuggets"]:
            lines.append(f"    FN {m['false_negatives']} · unreachable {[(n['source'], n['window']) for n in m['unreachable_nuggets']]}")
    lines.append(f"Pre-filter eval {'PASS' if rep['pass'] else 'FAIL'} (verdict = production mode: {rep.get('production_mode')}; other modes are experiments)")
    return "\n".join(lines)
