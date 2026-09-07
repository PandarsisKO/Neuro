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
        # economics (contract list prices; the fake's tokens are chars/4 on both sides)
        filter_cost = filter_in / 1e6 * pf_in + filter_out / 1e6 * pf_out
        avoided_cost = avoided_in / 1e6 * fx_in + avoided_out / 1e6 * fx_out
        total_extract_in = sum(extract_tokens.values())
        m.update({"recall": round(1 - len(m["false_negatives"]) / max(1, n_relevant), 4), "windows_dropped_share": round(m["windows_dropped"] / n_windows, 4),
                  "tokens_dropped_share": round(avoided_in / max(1, total_extract_in), 4),
                  "extract_input_tokens_total": total_extract_in, "extract_input_tokens_avoided": avoided_in, "extract_output_tokens_avoided": avoided_out,
                  "filter_input_tokens": filter_in, "filter_output_tokens": filter_out, "filter_cost": round(filter_cost, 6), "avoided_cost": round(avoided_cost, 6),
                  "net_saved": round(avoided_cost - filter_cost, 6), "leverage": round(avoided_cost / filter_cost, 2) if filter_cost else None,
                  "unfiltered_extract_cost": round(total_extract_in / 1e6 * fx_in + n_windows * EXTRACT_OUT_TOKENS / 1e6 * fx_out, 6),
                  "returned_models": sorted(returned_models)})
        m["net_saved_share"] = round(m["net_saved"] / m["unfiltered_extract_cost"], 4) if m["unfiltered_extract_cost"] else 0.0
        m["gates"] = {"recall_100": m["recall"] == 1.0, "zero_false_negatives": not m["false_negatives"], "nuggets_reachable": not m["unreachable_nuggets"],
                      "no_relevant_source_emptied": not m["lost_relevant_sources"], "evidence_recall_preserved": m["filtered_evidence_recall"] >= base_recall}
        m["pass"] = all(m["gates"].values())
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
                  f"    filter spent {m['filter_input_tokens']:,} in / {m['filter_output_tokens']:,} out = ${m['filter_cost']:.4f} · avoided ${m['avoided_cost']:.4f} · NET ${m['net_saved']:+.4f} ({m['net_saved_share']:+.1%} of the unfiltered ${m['unfiltered_extract_cost']:.4f}) · leverage {m['leverage']}×",
                  f"    evidence recall with the filter {m['filtered_evidence_recall']:.0%} · gates {', '.join(k for k, v in m['gates'].items() if not v) or 'all pass'} → {'PASS' if m['pass'] else 'FAIL'}"]
        if m["false_negatives"] or m["unreachable_nuggets"]:
            lines.append(f"    FN {m['false_negatives']} · unreachable {[(n['source'], n['window']) for n in m['unreachable_nuggets']]}")
    lines.append(f"Pre-filter eval {'PASS' if rep['pass'] else 'FAIL'} (verdict = production mode: {rep.get('production_mode')}; other modes are experiments)")
    return "\n".join(lines)
