"""`neurosearch closeout` — Mission F closeout in one command (F5).

Deterministic phase (free, must all pass before a paid call):
  pytest (the whole suite incl. the F tests: schema registry, structured paths, planner V3 exit gate, status reconciliation),
  schema registry provider-compatibility, Tier 1 with Planner V1, Tier 1 with Planner V3 (both with the zero
  structured-output gates), the frozen planner rubric on both fake paths.

Live phase (--live; ONE paid run, narrowly scoped to what Mission F changed — nothing else is retested):
  1. findings.extract   production Sonnet 5 structured path — golden evidence recall, quote validity, stored re-check, zero events
  2. rank.relevance     production Sonnet 5 structured path — quality inside the saved Sonnet 5 envelope, zero unscored, zero events
  3. planner.update     valid structured update that addresses the new finding — never a silent empty list, zero events
  4. discover.quick     schema-valid result, zero events (no subjective judge)
  5. Planner V1 vs V3   identical frozen research: rubric, evidence, completeness, assembly, dangling/cycles, cost, latency,
                        tokens, cache write/read, cache read share, per-component telemetry
Ends with Mission F PASS / PASS WITH CAVEAT / FAIL and a separate Planner V3 PROMOTE / DO NOT PROMOTE. Changes nothing.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
EVENT_KINDS = ("schema_mismatch", "schema_fallback", "schema_failure", "output_truncated", "output_refused", "plan_assembly_failed")
FINDINGS_FLOORS = {"finding_quote_validity": 0.98, "stored_findings_verified": 1.0}
RECALL_TOLERANCE = 0.10
RANK_TOLERANCE = {"ndcg_at_20": 0.03, "precision_at_10": 0.10, "precision_at_20": 0.10, "recall_at_20_strict": 0.08, "recall_at_10_strict": 0.08}
COST_PATHOLOGICAL = 3.0          # V3 costing more than 3× V1 is "wildly wrong"; anything less is a caveat
LATENCY_PATHOLOGICAL = 3.0
# spend model (list price, from the frozen baselines): used only to print the expected maximum before anything is spent
_SPEND = {"embeddings": 0.02, "findings.extract (Sonnet 5, structured)": 0.20, "rank.relevance (Sonnet 5, structured)": 0.04,
          "planner V1 (4.6)": 0.30, "planner V3 (4.6, 5 calls, cached prefix)": 0.40, "planner.update": 0.06, "discover.quick": 0.03}
_SAFETY = 1.5


def expected_spend() -> dict[str, Any]:
    est = sum(_SPEND.values())
    return {"items": _SPEND, "estimate": round(est, 2), "maximum": round(est * _SAFETY, 2), "budget": round(max(10.0, est * _SAFETY * 2), 2)}


def _events_since(ts: float) -> dict[str, int]:
    rows = db.connect().execute("SELECT kind, COUNT(*) n FROM validation_events WHERE ts>=? GROUP BY kind", (ts,)).fetchall()
    got = {r["kind"]: r["n"] for r in rows}
    return {k: got.get(k, 0) for k in EVENT_KINDS}


def _zero(ev: dict[str, int], fails: list[str], label: str) -> None:
    bad = {k: v for k, v in ev.items() if v}
    if bad:
        fails.append(f"{label}: structured-output events {bad}")


def _latest(pattern: str) -> dict[str, Any] | None:
    files = sorted(glob.glob(pattern))
    return json.loads(Path(files[-1]).read_text()) if files else None


# ------------------------------------------------------------------ deterministic phase

def _fresh_db() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="ns_closeout_"))
    settings.data_dir = tmp
    db._local.conn = None
    db.init_db()
    return tmp


def deterministic_phase(progress: Any = print, run_pytest: bool = True) -> dict[str, Any]:
    from . import evals, migration, schemas
    out: dict[str, Any] = {"steps": [], "pass": True}

    def step(name: str, ok: bool, detail: Any = None) -> None:
        out["steps"].append({"step": name, "pass": bool(ok), "detail": detail})
        out["pass"] = out["pass"] and bool(ok)
        progress(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not ok else ""))

    if run_pytest:
        progress("deterministic: pytest (whole suite, incl. Mission F tests)…")
        env = {k: v for k, v in os.environ.items() if not k.startswith("NEUROSEARCH_")}      # the suite sets its own environment; ours must not leak in
        try:
            import pytest  # noqa: F401
        except ImportError:                                                            # the dev extra was not installed: fix it here, in this venv, once
            progress("  pytest is not installed in this environment — installing (pip install pytest)…")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pytest>=8"], capture_output=True, text=True, timeout=600)
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider"], cwd=str(ROOT), capture_output=True, text=True, timeout=1800, env=env)
        tail = (r.stdout.strip().splitlines() or [""])[-1]
        step("pytest", r.returncode == 0, tail if r.returncode == 0 else (r.stdout[-1500:] + r.stderr[-800:]))
        if r.returncode != 0:
            return out
    try:
        for name, sch in schemas.REGISTRY.items():
            schemas.check_provider_compat(sch, name)
        step("schema registry provider-compatible", True, sorted(schemas.REGISTRY))
    except schemas.SchemaError as e:
        step("schema registry provider-compatible", False, str(e))
        return out
    rubric = migration.load_rubric()
    was_fake, was_v3, was_dir = settings.fake_ai, settings.planner_v3, settings.data_dir
    settings.fake_ai = True
    try:
        for v3 in (False, True):
            settings.planner_v3 = v3
            tmp = _fresh_db()
            try:
                rep = evals.run(live=False, progress=lambda m: None)
                label = f"Tier 1 (Planner {'V3' if v3 else 'V1'})"
                gates = {k: g["pass"] for k, g in rep["gates"].items()}
                step(label, rep["pass"], {k: v for k, v in gates.items() if not v} or f"cost ${rep['economics']['cost']:.4f}")
                so = rep["structured_outputs"]
                step(label + " zero structured-output events", all(so[k] == 0 for k in ("schema_mismatches", "schema_fallbacks", "output_truncated", "output_refused")), so)
                plan = (db.latest_plan(rep["project_id"]) or {}).get("plan") or {}
                body = {k: v for k, v in plan.items() if not k.startswith("_")}
                r_plan = migration.score_rubric(body, rubric["plan"])["score"]
                r_an = migration.score_rubric(plan.get("analysis"), rubric["analysis"])["score"]
                out["rubric_v3" if v3 else "rubric_v1"] = {"plan": r_plan, "analysis": r_an}
                step(label + " frozen planner rubric", True, {"plan": r_plan, "analysis": r_an})
                if v3:
                    chk = plan.get("_evidence_check") or {}
                    step("Tier 1 V3 evidence / assembly", not chk.get("dangling") and bool(plan.get("_build")) and bool(plan.get("_ids")), chk)
            finally:
                db._local.conn = None
                shutil.rmtree(tmp, ignore_errors=True)
        step("rubric V3 ≥ V1 (fakes)", out["rubric_v3"]["plan"] >= out["rubric_v1"]["plan"] and out["rubric_v3"]["analysis"] >= out["rubric_v1"]["analysis"],
             {"v1": out["rubric_v1"], "v3": out["rubric_v3"]})
    finally:
        settings.fake_ai, settings.planner_v3, settings.data_dir = was_fake, was_v3, was_dir
        db._local.conn = None
    return out


# ------------------------------------------------------------------ live phase (one run)

class StageIncomplete(RuntimeError):
    """A required external dependency failed during a live stage: the stage is INCOMPLETE — never evaluated on a
    degraded fallback — and the run can be resumed once the dependency is back."""


def _dependency_failure(e: BaseException) -> str | None:
    from . import providers
    from .search import RetrievalUnavailable
    if isinstance(e, RetrievalUnavailable):
        return f"retrieval: {e}"
    if isinstance(e, providers.ProviderError) and e.error_type in providers.TRANSIENT_TYPES:
        return f"provider {e.error_type}: {e}"
    if isinstance(e, StageIncomplete):
        return str(e)
    return None


STAGE_ORDER = ("shared_inputs", "findings", "ranking", "research", "planner_v1", "planner_v3", "update", "discover")


def _state_path(d: Path) -> Path:
    return d / "stages.json"


def _save_state(d: Path, state: dict[str, Any]) -> None:
    _state_path(d).write_text(json.dumps(state, indent=1, default=str))


def _import_previous(prev: Path, d: Path, state: dict[str, Any], progress: Any) -> None:
    """Resume: carry over the previous run's completed stage artifacts (and its database, when it was persisted) and
    record what was invalidated and why. Nothing is overwritten: the previous directory stays as it was."""
    prev_state = json.loads(_state_path(prev).read_text()) if _state_path(prev).exists() else {"stages": {}, "history": [], "legacy": True}
    entry = {"resumed_from": str(prev), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "reused": [], "invalidated": {}, "rebuilt": []}
    if (prev / "data" / "neurosearch.db").exists():
        shutil.copytree(prev / "data", d / "data", dirs_exist_ok=True)
        entry["database"] = "copied from the previous run (shared inputs reused, nothing repaid)"
    else:
        entry["database"] = "the previous run did not persist its database — shared inputs (ingest + findings extraction) are rebuilt"
    for name in ("findings", "ranking", "planner_v1", "planner_v3", "update", "discover"):
        fname = {"findings": "findings.json", "ranking": "ranking.json", "planner_v1": "planner-v1.json", "planner_v3": "planner-v3.json", "update": "update.json", "discover": "discover.json"}[name]
        st = (prev_state.get("stages") or {}).get(name)
        src = prev / fname
        ok = (st or {}).get("status") == "done" if st else src.exists()          # legacy runs: a present artifact means the stage finished
        if not ok or not src.exists():
            if st or src.exists():
                entry["invalidated"][name] = (st or {}).get("error") or "stage did not complete"
            continue
        if name in ("planner_v1", "planner_v3"):
            # a planner arm is reusable only when it ran on THIS run's frozen research — decided after the research is frozen
            entry["invalidated"][name] = "pending: reusable only if its research_hash matches the frozen research of this run"
            state.setdefault("_candidate_arms", {})[name] = json.loads(src.read_text())
            continue
        obj = json.loads(src.read_text())
        if "events" not in obj:
            # legacy run (before stage files carried their events): take them from that run's closeout.json surfaces
            surf_name = {"findings": "findings.extract", "ranking": "rank.relevance", "update": "planner.update", "discover": "discover.quick"}[name]
            prev_close = json.loads((prev / "closeout.json").read_text()) if (prev / "closeout.json").exists() else {}
            surf = ((prev_close.get("live") or {}).get("surfaces") or {}).get(surf_name)
            if not surf:
                entry["invalidated"][name] = "legacy artifact without structured-output event counts and no closeout.json to recover them from"
                continue
            obj["events"] = surf.get("events") or {}
            if name == "discover":
                obj.setdefault("invocations", {"returned_model": surf.get("returned_model")}); obj.setdefault("cost", surf.get("cost")); obj.setdefault("seconds", surf.get("seconds"))
        (d / fname).write_text(json.dumps(obj, indent=1, default=str))
        state["stages"][name] = {**(st or {"status": "done", "legacy": True}), "reused_from": str(prev)}
        entry["reused"].append(name)
    if (prev_state.get("stages") or {}).get("shared_inputs") and (d / "data" / "neurosearch.db").exists():
        state["stages"]["shared_inputs"] = {**prev_state["stages"]["shared_inputs"], "reused_from": str(prev)}
        entry["reused"].append("shared_inputs")
        rs = (prev_state.get("stages") or {}).get("research")
        if rs and rs.get("status") == "done" and (prev / "research.json").exists():
            shutil.copy(prev / "research.json", d / "research.json")          # the frozen payload itself is reused, never re-retrieved
            state["stages"]["research"] = {**rs, "reused_from": str(prev)}
            entry["reused"].append("research")
    state["history"] = list(prev_state.get("history") or []) + [entry]
    progress(f"resuming from {prev.name}: reused {', '.join(entry['reused']) or 'nothing'}; " + entry["database"])


def live_phase(live: bool, d: Path, progress: Any = print, resume_from: Path | None = None) -> dict[str, Any]:
    from . import contracts, discover, evals, findings, migration, planner
    rubric = migration.load_rubric()
    state: dict[str, Any] = {"stages": {}, "history": [], "dir": str(d)}
    if resume_from:
        _import_previous(resume_from, d, state, progress)
    data = d / "data"
    data.mkdir(exist_ok=True)
    settings.data_dir = data                      # the run's database lives WITH its artifacts: a resume reopens it, nothing is repaid
    db._local.conn = None
    db.init_db()
    spend = expected_spend()
    todo = [s_ for s_ in STAGE_ORDER if (state["stages"].get(s_) or {}).get("status") != "done"]
    progress(f"stages to run: {', '.join(todo)}; expected paid spend ≈ ${spend['estimate']:.2f} for a full run (max ≈ ${spend['maximum']:.2f}); eval-only budget ${spend['budget']:.2f} in the run's own database")
    db.kv_set("daily_budget", str(spend["budget"])); db.kv_set("monthly_budget", str(spend["budget"]))
    models = sorted({contracts.contract(t).model for t in ("findings.extract", "rank.relevance", "planner.update", "discover.quick", "planner.build", "planner.situation")})
    pf = migration.preflight(models, live)
    progress("preflight ok: " + ", ".join(f"{m} ({n})" for m, n in pf.items()))
    res: dict[str, Any] = {"tier": "live" if live else "fake", "preflight": pf, "spend_estimate": spend, "surfaces": {}, "fails": [], "caveats": [], "notes": [],
                           "incomplete": {}, "state": state}
    fails, caveats, notes = res["fails"], res["caveats"], res["notes"]
    t_all = time.time()

    def save(name: str, obj: Any) -> None:
        (d / name).write_text(json.dumps(obj, indent=1, default=str))

    def done(stage: str, **info: Any) -> None:
        state["stages"][stage] = {"status": "done", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **info}
        _save_state(d, state)

    def incomplete(stage: str, why: str) -> None:
        state["stages"][stage] = {"status": "incomplete", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": why}
        res["incomplete"][stage] = why
        _save_state(d, state)
        progress(f"[{stage}] INCOMPLETE — {why}")

    def run_stage(stage: str, fn: Any, needs: tuple[str, ...] = ()) -> bool:
        if (state["stages"].get(stage) or {}).get("status") == "done":
            progress(f"[{stage}] reused from the previous run")
            return True
        missing = [n for n in needs if (state["stages"].get(n) or {}).get("status") != "done"]
        if missing:
            incomplete(stage, f"skipped: depends on {', '.join(missing)}")
            return False
        try:
            fn()
            return True
        except Exception as e:  # noqa: BLE001
            why = _dependency_failure(e)
            if why is None:
                raise
            incomplete(stage, why)
            return False

    # ---- shared inputs: ingest once, findings once (production contract), approve — persisted in the run's database
    shared: dict[str, Any] = {}

    def s_shared() -> None:
        g = evals.load_golden()
        pid, ids = g["project_id"], g["sources"]
        for n in db.list_project_notes(pid, status="suggested"):
            db.set_note_status(n["id"], "approved")
        done("shared_inputs", project_id=pid, source_ids=ids)
    run_stage("shared_inputs", s_shared)
    if (state["stages"].get("shared_inputs") or {}).get("status") != "done":
        res["total_cost"] = migration._usage_since(t_all, ("answer", "plan", "synthesis", "findings", "embed", "rank", "discover"))["cost"]
        return res
    pid, ids = state["stages"]["shared_inputs"]["project_id"], state["stages"]["shared_inputs"]["source_ids"]
    man = json.loads((evals.GOLDEN / "manifest.json").read_text())

    # ---- 1. findings.extract (production contract, structured) — the eval extracts (force) and is the paid stage
    def s_findings() -> None:
        t0 = time.time()
        fr = evals.run_findings(pid, ids, man, live=live, progress=lambda m: progress("   " + m), force=True)
        fr["events"] = _events_since(t0)
        fr["saved_sonnet5"] = _latest(str(d.parent.parent / "findings-compare" / "*" / "candidate-sonnet-5.json"))
        for n in db.list_project_notes(pid, status="suggested"):
            db.set_note_status(n["id"], "approved")
        save("findings.json", fr)
        q = fr["quality"]
        progress(f"[findings.extract] recall {q['golden_evidence_recall']} · quote validity {q['finding_quote_validity']} · stored {q['stored_findings_verified']} · events {sum(fr['events'].values())} · ${fr['economics']['cost']:.4f}")
        done("findings", cost=fr["economics"]["cost"])
    run_stage("findings", s_findings, needs=("shared_inputs",))
    if (d / "findings.json").exists():
        fr = json.loads((d / "findings.json").read_text())
        q, ev = fr["quality"], fr.get("events") or {}
        saved_f = fr.get("saved_sonnet5") or _latest(str(d.parent.parent / "findings-compare" / "*" / "candidate-sonnet-5.json"))
        f_fails: list[str] = []
        for k, floor in FINDINGS_FLOORS.items():
            if q[k] < floor:
                f_fails.append(f"{k} {q[k]} < {floor}")
        if q["incomplete_outputs"] or q["failed_sources"]:
            f_fails.append(f"incomplete outputs {q['incomplete_outputs']}, failed sources {q['failed_sources']}")
        if saved_f and q["golden_evidence_recall"] < saved_f["quality"]["golden_evidence_recall"] - RECALL_TOLERANCE - 1e-9:
            f_fails.append(f"golden evidence recall {q['golden_evidence_recall']} fell beyond tolerance vs the saved Sonnet 5 result {saved_f['quality']['golden_evidence_recall']}")
        elif saved_f and q["golden_evidence_recall"] < saved_f["quality"]["golden_evidence_recall"]:
            caveats.append(f"findings: evidence recall {saved_f['quality']['golden_evidence_recall']} → {q['golden_evidence_recall']} (within tolerance)")
        _zero(ev, f_fails, "findings.extract")
        if not migration.model_matches(fr["configured_model"], fr.get("returned_model")):
            f_fails.append(f"findings.extract returned {fr.get('returned_model')!r}, configured {fr['configured_model']!r}")
        fails += f_fails
        res["surfaces"]["findings.extract"] = {"pass": not f_fails, "fails": f_fails, "golden_evidence_recall": q["golden_evidence_recall"], "finding_quote_validity": q["finding_quote_validity"],
                                               "stored_findings_verified": q["stored_findings_verified"], "findings_suggested": q["findings_suggested"], "findings_rejected": q["findings_rejected"],
                                               "events": ev, "schema": fr["contract"]["schema"], "configured_model": fr["configured_model"], "returned_model": fr.get("returned_model"),
                                               "cost": fr["economics"]["cost"], "seconds": fr["performance"]["findings_s"], "reused": bool((state["stages"].get("findings") or {}).get("reused_from"))}

    # ---- 2. rank.relevance (production contract, structured) vs the saved Sonnet 5 envelope
    def s_ranking() -> None:
        t0 = time.time()
        rr = evals.run_ranking(live=live, progress=lambda m: progress("   " + m))
        rr["events"] = _events_since(t0)
        rr["saved_sonnet5"] = _latest(str(d.parent.parent / "ranking-compare" / "*" / "candidate-sonnet-5.json"))
        save("ranking.json", rr)
        rq = rr["quality"]
        progress(f"[rank.relevance] NDCG@20 {rq['ndcg_at_20']} · P@10 {rq['precision_at_10']} · unscored {rq['unscored_candidates']} · events {sum(rr['events'].values())} · ${rr['economics']['cost']:.4f}")
        done("ranking", cost=rr["economics"]["cost"])
    run_stage("ranking", s_ranking)
    if (d / "ranking.json").exists():
        rr = json.loads((d / "ranking.json").read_text())
        rq, ev, saved_r = rr["quality"], rr.get("events") or {}, rr.get("saved_sonnet5") or _latest(str(d.parent.parent / "ranking-compare" / "*" / "candidate-sonnet-5.json"))
        r_fails: list[str] = []
        if rq["unscored_candidates"] or rq["failed_batches"]:
            r_fails.append(f"unscored {rq['unscored_candidates']}, failed batches {rq['failed_batches']}")
        if saved_r:
            for k, tol in RANK_TOLERANCE.items():
                if rq[k] < saved_r["quality"][k] - tol - 1e-9:
                    r_fails.append(f"{k} {rq[k]} fell beyond tolerance vs the saved Sonnet 5 result {saved_r['quality'][k]}")
                elif rq[k] < saved_r["quality"][k]:
                    caveats.append(f"ranking: {k} {saved_r['quality'][k]} → {rq[k]} (within tolerance)")
        else:
            notes.append("ranking: no saved Sonnet 5 ranking result found under evals/ranking-compare — envelope check skipped")
        _zero(ev, r_fails, "rank.relevance")
        if not migration.model_matches(rr["configured_model"], rr.get("returned_model")):
            r_fails.append(f"rank.relevance returned {rr.get('returned_model')!r}, configured {rr['configured_model']!r}")
        fails += r_fails
        res["surfaces"]["rank.relevance"] = {"pass": not r_fails, "fails": r_fails, **{k: rq[k] for k in ("precision_at_10", "recall_at_20", "recall_at_20_strict", "ndcg_at_20", "unscored_candidates", "failed_batches", "repaired_batches")},
                                             "events": ev, "schema": rr["contract"]["schema"], "configured_model": rr["configured_model"], "returned_model": rr.get("returned_model"),
                                             "cost": rr["economics"]["cost"], "seconds": rr["performance"]["rank_s"], "reused": bool((state["stages"].get("ranking") or {}).get("reused_from"))}

    # ---- research: the planner's input, prepared ONCE (strict: a retrieval failure is an error, never a different evidence list), then frozen
    research: dict[str, Any] | None = None

    def s_research() -> None:
        nonlocal research
        r = planner.research_context(pid, strict=True)
        save("research.json", {k: v for k, v in r.items()})
        done("research", material_hash=r["material_hash"], evidence_count=r["evidence_count"], material_chars=len(r["material"]))
        progress(f"[research] frozen: {r['evidence_count']} evidence items, {len(r['material']):,} chars, hash {r['material_hash']}")
    run_stage("research", s_research, needs=("findings",))
    if (state["stages"].get("research") or {}).get("status") == "done":
        research = json.loads((d / "research.json").read_text())
        # decide the fate of carried-over planner arms now that the frozen research exists
        for name, arm in (state.pop("_candidate_arms", {}) or {}).items():
            hist = state["history"][-1] if state.get("history") else None
            if arm.get("research_hash") == research["material_hash"]:
                fname = "planner-v1.json" if name == "planner_v1" else "planner-v3.json"
                save(fname, arm); state["stages"][name] = {"status": "done", "reused_from": str(resume_from), "research_hash": arm["research_hash"]}
                if hist:
                    hist["reused"].append(name); hist["invalidated"].pop(name, None)
            elif hist:
                hist["invalidated"][name] = (f"built on different research (hash {arm.get('research_hash') or 'unknown — the original run retrieved per arm and did not freeze it'}"
                                             f" vs frozen {research['material_hash']}); rebuilt on the frozen payload")
                hist["rebuilt"].append(name)
        _save_state(d, state)

    # ---- planner V1 then V3 on the SAME frozen research; state restored between arms
    mark = migration._state_mark()

    def planner_stage(label: str, v3: bool) -> Any:
        def fn() -> None:
            was = settings.planner_v3
            settings.planner_v3 = v3
            t0 = time.time()
            try:
                progress(f"[planner {label.upper()}] building on the frozen research {research['material_hash']}…")
                arm = migration.run_planner_arm(pid, live, rubric, research=research)
            finally:
                settings.planner_v3 = was
            arm["events"] = _events_since(t0)
            arm["usage"] = migration._usage_since(t0, ("plan",))
            migration._restore_state(pid, mark)
            if arm.get("error"):
                if arm.get("error_type") in ("ProviderError", "RetrievalUnavailable") and any(k in arm["error"] for k in ("CONNECTION", "TIMEOUT", "OVERLOADED", "RATE_LIMIT", "vector search")):
                    raise StageIncomplete(f"planner {label.upper()} build failed on an external dependency: {arm['error']}")
            if arm.get("research_hash") != research["material_hash"]:
                raise StageIncomplete(f"planner {label.upper()} did not consume the frozen research ({arm.get('research_hash')} vs {research['material_hash']})")
            save(f"planner-{label}.json", arm)
            tb, ta = arm["tasks"]["planner.build"], arm["tasks"]["planner.analysis"]
            progress(f"[planner {label.upper()}] rubric plan {tb['rubric']['score']} / analysis {ta['rubric']['score']} · structure {tb['rubric']['structure']['score']} · refs {tb['evidence_refs']} · "
                     f"dangling {arm['plan_evidence_dangling_raw']} · error {arm['error']} · ${arm['usage']['cost']:.4f} · {arm['seconds']}s · calls {arm['usage']['calls']}")
            done(f"planner_{label}", cost=arm["usage"]["cost"], research_hash=arm["research_hash"])
        return fn
    run_stage("planner_v1", planner_stage("v1", False), needs=("research",))
    run_stage("planner_v3", planner_stage("v3", True), needs=("research",))
    arms = {k: json.loads((d / f"planner-{k}.json").read_text()) for k in ("v1", "v3") if (state["stages"].get(f"planner_{k}") or {}).get("status") == "done" and (d / f"planner-{k}.json").exists()}
    if set(arms) == {"v1", "v3"}:
        res["planner"] = planner_decision(arms)
        if arms["v1"].get("research_hash") != arms["v3"].get("research_hash"):
            res["planner"].update({"promote": False, "decision": "NOT DECIDED — the two arms did not consume identical frozen research", "hard_failures": res["planner"]["hard_failures"] + ["research hashes differ"]})
        fails += [f"planner V3: {x}" for x in res["planner"]["mission_fails"]]
        caveats += [f"planner V3: {x}" for x in res["planner"]["caveats"]]
    else:
        res["planner"] = {"promote": False, "decided": False, "decision": "NOT DECIDED — a planner arm is incomplete (see INCOMPLETE stages); resume the closeout", "hard_failures": [], "caveats": [], "notes": [], "mission_fails": [],
                          "v1": None, "v3": None}

    # ---- 3. planner.update on the frozen V1 plan + one new finding and one new fact
    def s_update() -> None:
        base = arms["v1"]
        frozen_plan = dict(base["plan"])
        if base.get("analysis"):
            frozen_plan["analysis"] = base["analysis"]
        db.save_plan(pid, json.loads(json.dumps(frozen_plan)), db.project_snapshot(pid))
        time.sleep(0.02)
        yt = ids.get("yt01"); src = db.get_source(yt) if yt else None
        cite = [{"n": 1, "source_id": yt, "title": src["title"], "channel": src.get("channel"), "url": src["url"], "link": src["url"], "timestamp": "0:12", "start": 12, "end": 12,
                 "platform": src["platform"], "snippet": "ten percent equity injection"}] if src else []
        db.add_project_note(pid, migration.UPDATE_FINDING + " [1]", cite)
        db.add_fact(pid, migration.UPDATE_FACT[0], migration.UPDATE_FACT[1])
        t0 = time.time()
        try:
            u = migration.run_update_arm(pid, live)
            u["error"] = None
        except Exception as e:  # noqa: BLE001
            if _dependency_failure(e):
                migration._restore_state(pid, mark)
                raise
            u = {"error": str(e)[:300], "n_updates": 0, "addresses_new_finding": 0, "addresses_new_fact": 0, "well_formed": 0, "json_repaired": 0, "truncated": 0, "parse_failed": 1,
                 "invocations": {}, "usage": migration._usage_since(t0, ("plan",)), "seconds": round(time.time() - t0, 2), "cost": 0}
        u["events"] = _events_since(t0)
        migration._restore_state(pid, mark)
        save("update.json", u)
        progress(f"[planner.update] {u['n_updates']} updates · new finding addressed {u['addresses_new_finding']} · events {sum(u['events'].values())} · ${u['usage']['cost']:.4f}")
        done("update", cost=u["usage"]["cost"])
    run_stage("update", s_update, needs=("planner_v1",))
    if (state["stages"].get("update") or {}).get("status") == "done" and (d / "update.json").exists():
        u = json.loads((d / "update.json").read_text())
        ev = u.get("events") or {}
        u_fails: list[str] = []
        if u.get("error"):
            u_fails.append(f"planner.update raised: {u['error']}")
        elif not u["n_updates"]:
            u_fails.append("planner.update returned no updates although a material new finding and a new constraint were added (silent-empty behaviour)")
        elif not u["well_formed"]:
            u_fails.append("planner.update: updates missing section/proposed/reason")
        elif not u["addresses_new_finding"]:
            u_fails.append("planner.update did not address the new lender finding (15% injection / seller note)")
        if not u.get("addresses_new_fact") and not u.get("error"):
            caveats.append("planner.update did not react to the new user constraint (partner will not sign a guarantee)")
        _zero(ev, u_fails, "planner.update")
        if u.get("invocations", {}).get("attempts") and not migration.model_matches(contracts.contract("planner.update").model, u["invocations"].get("returned_model")):
            u_fails.append(f"planner.update returned {u['invocations'].get('returned_model')!r}")
        fails += u_fails
        res["surfaces"]["planner.update"] = {"pass": not u_fails, "fails": u_fails, "n_updates": u["n_updates"], "addresses_new_finding": u["addresses_new_finding"], "addresses_new_fact": u["addresses_new_fact"],
                                             "well_formed": u["well_formed"], "events": ev, "schema": contracts.contract("planner.update").schema, "returned_model": u.get("invocations", {}).get("returned_model"),
                                             "cost": u["usage"]["cost"], "seconds": u["seconds"], "updates": u.get("updates"), "reused": bool((state["stages"].get("update") or {}).get("reused_from"))}

    # ---- 4. discover.quick (pass 1 only; discover.verify is out of scope by design)
    def s_discover() -> None:
        t0 = time.time()
        dres = discover.discover(pid, count=6, verify=False)
        inv = migration._invocations_since(t0, "discover.quick")
        out = {"items": dres["items"], "note": dres["note"], "events": _events_since(t0), "invocations": inv, "cost": migration._usage_since(t0, ("discover",))["cost"], "seconds": round(time.time() - t0, 2)}
        save("discover.json", out)
        progress(f"[discover.quick] {len(out['items'])} sources · events {sum(out['events'].values())} · ${out['cost']:.4f}")
        done("discover", cost=out["cost"])
    run_stage("discover", s_discover, needs=("shared_inputs",))
    if (state["stages"].get("discover") or {}).get("status") == "done" and (d / "discover.json").exists():
        dd = json.loads((d / "discover.json").read_text())
        d_fails: list[str] = []
        _zero(dd.get("events") or {}, d_fails, "discover.quick")
        if not dd["items"]:
            d_fails.append("discover.quick returned no sources")
        if not migration.model_matches(contracts.contract("discover.quick").model, (dd.get("invocations") or {}).get("returned_model")):
            d_fails.append(f"discover.quick returned {(dd.get('invocations') or {}).get('returned_model')!r}")
        fails += d_fails
        res["surfaces"]["discover.quick"] = {"pass": not d_fails, "fails": d_fails, "sources": len(dd["items"]), "with_url": sum(1 for x in dd["items"] if x.get("url")), "note": dd["note"][:200],
                                             "events": dd.get("events"), "schema": contracts.contract("discover.quick").schema, "returned_model": (dd.get("invocations") or {}).get("returned_model"),
                                             "cost": dd["cost"], "seconds": dd["seconds"], "reused": bool((state["stages"].get("discover") or {}).get("reused_from"))}

    res["total_cost"] = migration._usage_since(t_all, ("answer", "plan", "synthesis", "findings", "embed", "rank", "discover"))["cost"]
    res["total_s"] = round(time.time() - t_all, 2)
    res["project_id"] = pid
    res["research_hash"] = (research or {}).get("material_hash")
    _save_state(d, state)
    return res


def planner_decision(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """PROMOTE / DO NOT PROMOTE for Planner V3, plus which of its problems (if any) count against Mission F itself."""
    v1, v3 = arms["v1"], arms["v3"]
    hard: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    mission_fails: list[str] = []
    b1, b3 = v1["tasks"]["planner.build"], v3["tasks"]["planner.build"]
    a1, a3 = v1["tasks"]["planner.analysis"], v3["tasks"]["planner.analysis"]
    if v3.get("error"):
        hard.append(f"V3 build failed: {v3['error']}")
    if v1.get("error"):
        notes.append(f"V1 build failed: {v1['error']} — comparison is not like-for-like")
    r1, r3 = b1["rubric"]["score"], b3["rubric"]["score"]
    ra1, ra3 = a1["rubric"]["score"], a3["rubric"]["score"]
    if r3 < r1 - 1e-9:
        hard.append(f"plan rubric V3 {r3} < V1 {r1} (lost: {', '.join(sorted(set(b3['rubric']['failed']) - set(b1['rubric']['failed'])))})")
    if ra3 < ra1 - 1e-9:
        hard.append(f"analysis rubric V3 {ra3} < V1 {ra1}")
    if v3.get("plan_evidence_dangling_raw"):
        hard.append(f"V3 evidence validity < 1.0 ({v3['plan_evidence_dangling_raw']} dangling before validation)")
    if b3["dangling_after_removal"] or a3["dangling_after_removal"]:
        hard.append("V3 dangling evidence after validation")
    ev3 = v3.get("events") or {}
    if any(ev3.get(k) for k in EVENT_KINDS):
        hard.append(f"V3 structured-output/assembly events {dict((k, v) for k, v in ev3.items() if v)}")
        mission_fails.append(f"structured-output/assembly events during the V3 build: {dict((k, v) for k, v in ev3.items() if v)}")
    for t in (a3, b3):
        if t["truncated"] or t["parse_failed"] or t["json_repaired"]:
            hard.append("V3 truncation / parse failure / JSON repair")
    tb = v3.get("build_telemetry") or {}
    if not tb:
        hard.append("V3 produced no build telemetry (did the flag take effect?)")
    s1, s3 = b1["rubric"]["structure"]["score"], b3["rubric"]["structure"]["score"]
    if s3 < s1 - 1e-9:
        caveats.append(f"completeness (structure checks) V3 {s3} < V1 {s1}: {'; '.join(b3['rubric']['structure']['failed'])}")
    c1, c3 = v1["usage"]["cost"], v3["usage"]["cost"]
    if c1 and c3 > c1 * COST_PATHOLOGICAL:
        hard.append(f"cost pathological: V3 ${c3:.4f} vs V1 ${c1:.4f} (>{COST_PATHOLOGICAL}×)")
    elif c1 and c3 > c1 * 1.10:
        caveats.append(f"cost V1 ${c1:.4f} → V3 ${c3:.4f} ({(c3 / c1 - 1):+.0%})")
    l1, l3 = v1["seconds"], v3["seconds"]
    if l1 and l1 >= 1.0 and l3 > l1 * LATENCY_PATHOLOGICAL:
        hard.append(f"latency pathological: V3 {l3}s vs V1 {l1}s")
    elif l1 and l1 >= 1.0 and l3 > l1 * 1.5:
        caveats.append(f"latency V1 {l1}s → V3 {l3}s ({(l3 / l1 - 1):+.0%})")
    share = tb.get("cache_read_share")
    if share is not None and share < 0.5:
        caveats.append(f"cache read share {share} — the shared research prefix is not being reused as intended")
    from .usage import _price
    def cold(arm: dict[str, Any], model: str | None) -> float:
        pin, _ = _price(str(model or settings.answer_model))
        return round(arm["usage"]["cost"] + arm["usage"]["cache_read_tokens"] / 1e6 * pin * 0.9, 4)      # every cache read billed as a fresh read
    v1_cold, v3_cold = cold(v1, b1["invocations"].get("returned_model")), cold(v3, b3["invocations"].get("returned_model"))
    notes.append(f"V1 built first and wrote the shared research prefix to the prompt cache; V3 (same model, same prefix, within minutes) read it back. "
                 f"Cold-cache equivalent cost: V1 ${v1_cold:.4f} vs V3 ${v3_cold:.4f}")
    notes.append(f"calls V1 {v1['usage']['calls']} → V3 {v3['usage']['calls']}; input {v1['usage']['input_tokens']:,} → {v3['usage']['input_tokens']:,}; "
                 f"cache write {v1['usage']['cache_write_tokens']:,} → {v3['usage']['cache_write_tokens']:,}; cache read {v1['usage']['cache_read_tokens']:,} → {v3['usage']['cache_read_tokens']:,}; "
                 f"output {v1['usage']['output_tokens']:,} → {v3['usage']['output_tokens']:,}")
    if r3 > r1 + 1e-9 or ra3 > ra1 + 1e-9:
        notes.append(f"rubric improved: plan {r1} → {r3}, analysis {ra1} → {ra3}")
    promote = not hard
    return {"promote": promote, "decision": "PROMOTE — make NEUROSEARCH_PLANNER_V3 the default for the next release; keep V1 as the rollback path for one release cycle" if promote
            else "DO NOT PROMOTE — leave the default on V1; V3 recorded as not promoted (no further tuning loop)",
            "hard_failures": hard, "caveats": caveats, "notes": notes, "mission_fails": mission_fails,
            "v1": {"rubric_plan": r1, "rubric_analysis": ra1, "structure": s1, "evidence_refs": b1["evidence_refs"], "dangling_raw": v1.get("plan_evidence_dangling_raw"), "cost": c1, "cost_cold_equivalent": v1_cold, "seconds": l1, "usage": v1["usage"]},
            "v3": {"rubric_plan": r3, "rubric_analysis": ra3, "structure": s3, "evidence_refs": b3["evidence_refs"], "dangling_raw": v3.get("plan_evidence_dangling_raw"), "cost": c3, "cost_cold_equivalent": v3_cold, "seconds": l3, "usage": v3["usage"],
                   "telemetry": tb, "events": ev3}}


# ------------------------------------------------------------------ the command

def latest_run_dir(out_dir: Path = Path("evals")) -> Path | None:
    runs = sorted(p for p in (out_dir / "mission-f-closeout").glob("*") if p.is_dir())
    return runs[-1] if runs else None


def run_closeout(live: bool = False, out_dir: Path = Path("evals"), progress: Any = print, run_pytest: bool = True, resume: bool = False,
                 resume_from: Path | None = None) -> dict[str, Any]:
    from . import __version__
    from .evals import git_sha
    sha = git_sha()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    prev = resume_from or (latest_run_dir(out_dir) if resume else None)
    if resume and not prev:
        raise RuntimeError("nothing to resume: no previous run under " + str(out_dir / "mission-f-closeout"))
    d = out_dir / "mission-f-closeout" / (f"{stamp}-{sha}" + (f"-resume-of-{prev.name[:15]}" if prev else ""))
    d.mkdir(parents=True, exist_ok=True)
    rep: dict[str, Any] = {"eval": "mission-f-closeout", "tier": "live" if live else "fake", "app_version": __version__, "git_sha": sha, "started": stamp, "dir": str(d),
                           "resumed_from": str(prev) if prev else None}
    progress(f"Mission F closeout · app {__version__} @ {sha} · {'LIVE' if live else 'fake dry run'}" + (f" · resuming {prev.name}" if prev else ""))
    progress("== deterministic phase (free)")
    det = deterministic_phase(progress, run_pytest=run_pytest)
    rep["deterministic"] = det
    (d / "deterministic.json").write_text(json.dumps(det, indent=1, default=str))
    if not det["pass"]:
        rep["mission"] = {"verdict": "FAIL", "headline": "Mission F FAIL — the deterministic phase failed; nothing was spent", "fails": [s["step"] for s in det["steps"] if not s["pass"]], "caveats": [], "notes": []}
        rep["planner_v3"] = {"promote": False, "decision": "DO NOT PROMOTE — deterministic phase failed"}
        rep["text"] = format_closeout(rep)
        (d / "closeout.json").write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
        (d / "closeout.txt").write_text(rep["text"])
        return rep
    progress("== live phase" if live else "== live phase (fake dry run — no spend)")
    was_fake, was_dir = settings.fake_ai, settings.data_dir
    settings.fake_ai = not live
    try:
        lv = live_phase(live, d, progress, resume_from=prev)
    finally:
        db._local.conn = None
        settings.fake_ai, settings.data_dir = was_fake, was_dir
    rep["live"] = {k: v for k, v in lv.items() if k not in ("planner", "state")}
    rep["stages"] = lv["state"]["stages"]
    rep["history"] = lv["state"].get("history", [])
    rep["planner_v3"] = lv["planner"]
    fails, caveats, notes = lv["fails"], lv["caveats"], lv["notes"]
    if lv["incomplete"]:
        verdict, head = "INCOMPLETE", "Mission F INCOMPLETE — an external dependency failed during a live stage; completed stages are saved, resume with: neurosearch closeout --live --resume"
    elif fails:
        verdict, head = "FAIL", "Mission F FAIL — a changed surface did not hold its guarantees"
    elif caveats:
        verdict, head = "PASS_WITH_CAVEAT", "Mission F PASS WITH CAVEAT — every changed surface holds; review the caveats"
    else:
        verdict, head = "PASS", "Mission F PASS — structured outputs hold on every changed surface with zero fallbacks"
    if not lv["planner"].get("promote") and lv["planner"].get("decided", True) and verdict != "INCOMPLETE":
        notes.append("Planner V3 not promoted (see the separate decision); this does not fail Mission F unless its build raised structured-output/assembly events")
    rep["mission"] = {"verdict": verdict, "headline": head, "fails": fails, "caveats": caveats, "notes": notes, "incomplete": lv["incomplete"]}
    rep["text"] = format_closeout(rep)
    (d / "closeout.json").write_text(json.dumps({k: v for k, v in rep.items() if k != "text"}, indent=1, default=str))
    (d / "closeout.txt").write_text(rep["text"])
    return rep


def format_closeout(rep: dict[str, Any]) -> str:
    f = lambda v: "—" if v is None else (f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))  # noqa: E731
    lines = [f"MISSION F CLOSEOUT · {rep['tier']} · app {rep['app_version']} @ {rep['git_sha']} · {rep['dir']}", "", "DETERMINISTIC PHASE"]
    for s in rep["deterministic"]["steps"]:
        lines.append(f"  {'PASS' if s['pass'] else 'FAIL'}  {s['step']}" + (f"   {s['detail']}" if s.get("detail") and (not s["pass"] or isinstance(s["detail"], (dict, str))) else ""))
    for h in rep.get("history") or []:
        lines += ["", f"HISTORY  resumed from {h['resumed_from']} at {h['at']}: {h.get('database')}",
                  "  reused: " + (", ".join(h.get("reused") or []) or "nothing")]
        for k, why in (h.get("invalidated") or {}).items():
            lines.append(f"  invalidated {k}: {why}")
    lv = rep.get("live")
    if lv:
        lines += ["", f"LIVE PHASE  (expected ≈ ${lv['spend_estimate']['estimate']:.2f} for a full run, actual this run ${lv.get('total_cost', 0):.4f}, {lv.get('total_s')}s"
                  + (f", frozen research {lv.get('research_hash')}" if lv.get("research_hash") else "") + ")"]
        for stage, why in (lv.get("incomplete") or {}).items():
            lines.append(f"  INCOMPLETE  {stage:18s} {why}")
        for name, s in lv["surfaces"].items():
            lines.append(f"  {'PASS' if s.get('pass') else 'FAIL'}  {name:18s} " + ("(reused) " if s.get("reused") else "") + ", ".join(
                f"{k} {f(v)}" for k, v in s.items() if k in ("golden_evidence_recall", "finding_quote_validity", "stored_findings_verified", "ndcg_at_20", "precision_at_10", "recall_at_20_strict",
                                                              "unscored_candidates", "n_updates", "addresses_new_finding", "sources", "returned_model", "cost", "seconds"))
                         + f", events {sum((s.get('events') or {}).values())}")
            for x in s.get("fails", []):
                lines.append("        FAIL " + x)
        p = rep["planner_v3"]
        if not p.get("v1") or not p.get("v3"):
            lines += ["", "PLANNER V1 vs V3", "  DECISION: " + p["decision"]]
            m = rep["mission"]
            lines += ["", "VERDICT: " + m["headline"]]
            for x in m.get("fails", []):
                lines.append("  FAIL    " + x)
            for x in m.get("caveats", []):
                lines.append("  caveat  " + x)
            lines += ["", "PLANNER V3: NOT DECIDED", "", "Nothing was changed. Completed stages are saved in " + rep["dir"] + " and will be reused by: neurosearch closeout --live --resume"]
            return "\n".join(lines)
        lines += ["", "PLANNER V1 vs V3 (identical frozen research)", f"  {'metric':28s} {'V1':>14s} {'V3':>14s}"]
        for k in ("rubric_plan", "rubric_analysis", "structure", "evidence_refs", "dangling_raw", "cost", "cost_cold_equivalent", "seconds"):
            lines.append(f"  {k:28s} {f(p['v1'][k]):>14s} {f(p['v3'][k]):>14s}")
        for k in ("calls", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens"):
            lines.append(f"  {k:28s} {p['v1']['usage'][k]:>14,} {p['v3']['usage'][k]:>14,}")
        tb = p["v3"].get("telemetry") or {}
        if tb:
            lines.append(f"  {'cache_read_share (V3)':28s} {'':>14s} {f(tb.get('cache_read_share')):>14s}")
            for c in tb.get("components", []):
                lines.append(f"    {c['task']:20s} in {c['input_tokens']:>6,} cache_w {c['cache_write']:>6,} cache_r {c['cache_read']:>7,} out {c['output_tokens']:>6,} ${c['cost']:.4f} {c['seconds']}s")
        lines.append("  DECISION: " + p["decision"])
        for x in p.get("hard_failures", []):
            lines.append("    HARD    " + x)
        for x in p.get("caveats", []):
            lines.append("    caveat  " + x)
        for x in p.get("notes", []):
            lines.append("    note    " + x)
    m = rep["mission"]
    lines += ["", "VERDICT: " + m["headline"]]
    for x in m["fails"]:
        lines.append("  FAIL    " + x)
    for x in m["caveats"]:
        lines.append("  caveat  " + x)
    for x in m["notes"]:
        lines.append("  note    " + x)
    lines += ["", "PLANNER V3: " + ("PROMOTE" if rep["planner_v3"].get("promote") else "DO NOT PROMOTE"), "",
              "Nothing was changed: production contracts and NEUROSEARCH_PLANNER_V3 stay as they are until you decide. The run's database and every stage artifact are kept in " + rep["dir"] + "."]
    return "\n".join(lines)
