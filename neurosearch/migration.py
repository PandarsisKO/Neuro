"""`neurosearch eval --migration-compare` — the rest of the Sonnet 4.6 → Sonnet 5 migration in one command (Mission E, E2.3).

Every arm sees identical frozen inputs: the Golden Project is ingested once, its findings are extracted once (under the
production findings contract, already Sonnet 5) and approved, and project state is restored between arms so nothing
one arm wrote (notes from chat tools, plans, plan updates) leaks into the next.

Arms (thinking is explicit everywhere; only model/thinking/effort differ between arms of a task):
  planner.analysis + planner.build   4.6 disabled · 5 disabled · 5 adaptive/medium   (same build_plan run serves both tasks)
  planner.update                     4.6 disabled · 5 disabled                       (frozen current plan = the 4.6 arm's plan + one new finding)
  export.synthesis                   4.6 disabled · 5 disabled
  answer.chat (+ answer.repair)      4.6 disabled · 5 disabled                       (the 33 non-calculator golden questions)
discover.quick / discover.verify are not part of this migration (no frozen exit test exists for them).

Quality and validity decide; cost and latency only add caveats. Adaptive thinking is recommended over disabled ONLY
when it measurably improves the frozen planner rubric, removes a failure mode, or materially improves completeness —
equal quality → disabled (simpler, faster, cheaper). Nothing here changes a production default.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from . import db
from .evals import (BASELINE_MODEL, CANDIDATE_MODEL, COST_TOLERANCE, GOLDEN, LATENCY_TOLERANCE, _model_slug, git_sha, load_golden,
                    model_matches, prompt_versions)

log = logging.getLogger(__name__)

RUBRIC = GOLDEN / "planner_rubric.json"
# 0.56.1: the arms are BUILT from the two models rather than hardcoded, because `--candidate-model` reached
# `--ranking-compare` and `--findings-compare` but silently did nothing here — pointing this command at Haiku
# would have spent real money re-answering the 4.6-vs-Sonnet-5 question instead.
ARM_BASE = ("baseline", BASELINE_MODEL, "disabled", None)
ARM_DIS = ("candidate", CANDIDATE_MODEL, "disabled", None)
ARM_ADAPT = ("candidate-adaptive", CANDIDATE_MODEL, "adaptive", "medium")


# The slots are arm POSITIONS, not model names: which model filled one is recorded in that arm's meta. They used
# to be literally "4.6" and "5-disabled", which is why nobody noticed the candidate model could not be changed.
SLOT_BASE, SLOT_CAND, SLOT_ADAPT = "baseline", "candidate", "candidate-adaptive"


def supports_adaptive(model: str) -> bool:
    """Only Claude 5 models take adaptive thinking (`contracts.validate` refuses the pairing outright)."""
    from . import contracts
    return contracts.model_family(model) == "claude-5"


def task_arms(baseline: str = BASELINE_MODEL, candidate: str = CANDIDATE_MODEL, skip_adaptive: bool = False) -> dict[str, list[tuple[str, str, str, str | None]]]:
    """The arms each task runs. 0.56.2: the adaptive planner arm is dropped when the CANDIDATE cannot run adaptive
    thinking, instead of being built and then blowing up inside the loop. `--candidate-model claude-haiku-4-5` built
    a `candidate-adaptive` arm that `contracts.validate` rejects on sight; the ContractError landed after the two
    real planner arms had already been paid for, so $0.39 of completed measurement went in the bin with it. An arm
    that cannot possibly run is a fact about the models, knowable for free before the first call."""
    base = (SLOT_BASE, baseline, "disabled", None)
    cand = (SLOT_CAND, candidate, "disabled", None)
    arms: dict[str, list[tuple[str, str, str, str | None]]] = {t: [base, cand] for t in TASK_ARMS}
    if not skip_adaptive and "planner" in arms and supports_adaptive(candidate):
        arms["planner"] = [base, cand, (SLOT_ADAPT, candidate, "adaptive", "medium")]
    return arms


def validate_arms(arms_for: dict[str, list[tuple[str, str, str, str | None]]]) -> list[str]:
    """Build every arm's contract before anything is spent and return the ones that will not validate. This is the
    arm-level twin of `preflight`: an unknown model id fails there, an impossible model/thinking pairing fails here,
    and both fail free."""
    from . import contracts
    bad: list[str] = []
    for task, arms in arms_for.items():
        tasks = TASK_CONTRACTS.get(task, [task])
        for label, model, thinking, effort in arms:
            saved = _set_arm(tasks, model, thinking, effort)
            try:
                for t in tasks:
                    try:
                        contracts.contract(t)
                    except Exception as e:  # noqa: BLE001
                        bad.append(f"{t} · arm {label} ({model}, thinking={thinking}{'/' + effort if effort else ''}): {e}")
            finally:
                _restore_env(saved)
    return bad
TASK_ARMS: dict[str, list[tuple[str, str, str, str | None]]] = {
    "planner": [ARM_BASE, ARM_DIS, ARM_ADAPT],
    "planner.update": [ARM_BASE, ARM_DIS],
    "export.synthesis": [ARM_BASE, ARM_DIS],
    "answer.chat": [ARM_BASE, ARM_DIS],
    "claims.extract": [ARM_BASE, ARM_DIS],
}
TASK_CONTRACTS: dict[str, list[str]] = {      # which contracts an arm of this task actually re-points (mirrors the _set_arm calls below)
    "planner": ["planner.analysis", "planner.build"],
    "planner.update": ["planner.update"],
    "export.synthesis": ["export.synthesis"],
    "answer.chat": ["answer.chat", "answer.repair"],
    "claims.extract": ["claims.extract"],
}
# tolerances (n=1 runs): a candidate may not fall further than this below the baseline on the decision metrics
RUBRIC_TOLERANCE = 0.10          # ~2 rubric checks of ~24
RUBRIC_WIN = 0.10                # adaptive must beat disabled by at least this (or remove a failure mode) to be recommended
GROUNDING_TOLERANCE = 0.10
EXPORT_COVERAGE_TOLERANCE = 0.20
CHAT_SOURCE_TOLERANCE = 0.10
CLAIMS_QUALIFIER_TOLERANCE = 0.10   # normalization exists to KEEP qualifiers; losing them is the failure mode
CLAIMS_EVAL_BUDGET = 40             # claims in the comparison cohort (claims.EVAL_BUDGET is 150 — too dear for an arm)
EVAL_BUDGET_FLOOR = 20.0         # eval-only daily budget written into the temporary database (never the real one)

# spend model per arm, from the frozen 0.17.3 live baseline (Sonnet 4.6 list price) — used only to print the expected maximum
_BASE_COST = {"answer.chat": 0.84, "planner": 0.27, "planner.update": 0.06, "export.synthesis": 0.06, "findings.extract": 0.20, "embed": 0.02,
              "claims.extract": 0.18}   # CLAIMS_EVAL_BUDGET candidates in groups of EXTRACT_GROUP, one structured call each
_SONNET5_FACTOR = 1.3 * (2.0 / 3.0)    # +30% tokens at two thirds of the price
_MODEL_FACTOR = {"claude-sonnet-4-6": 1.0, "claude-sonnet-5": _SONNET5_FACTOR, "claude-haiku-4-5": 1.3 / 3.0}   # vs 4.6 at $3/$15
_ADAPTIVE_EXTRA = 0.20                 # thinking tokens on the two planner passes, generous
_SAFETY = 1.5


def expected_spend(arms_for: dict[str, list[tuple[str, str, str, str | None]]] | None = None) -> dict[str, Any]:
    items = {"findings.extract (once, production Sonnet 5)": _BASE_COST["findings.extract"] * _SONNET5_FACTOR, "embeddings (once)": _BASE_COST["embed"]}
    for task, arms in (arms_for or TASK_ARMS).items():
        for label, model, thinking, effort in arms:
            c = _BASE_COST[task] * _MODEL_FACTOR.get(model, _SONNET5_FACTOR) + (_ADAPTIVE_EXTRA if thinking == "adaptive" else 0.0)
            items[f"{task} · {label}"] = c
    est = sum(items.values())
    return {"items": {k: round(v, 3) for k, v in items.items()}, "estimate": round(est, 2), "maximum": round(est * _SAFETY, 2),
            "budget": round(max(EVAL_BUDGET_FLOOR, est * _SAFETY * 2), 2)}


# ------------------------------------------------------------------ frozen planner rubric (deterministic; no model judges)

def load_rubric() -> dict[str, Any]:
    return json.loads(RUBRIC.read_text())


def _resolve(doc: Any, path: str) -> list[Any]:
    if path == "*":
        return [doc]
    cur = [doc]
    for seg in path.split("."):
        nxt: list[Any] = []
        for node in cur:
            if seg == "*":
                if isinstance(node, list):
                    nxt.extend(node)
                elif isinstance(node, dict):
                    nxt.extend(node.values())
            elif isinstance(node, dict) and seg in node:
                nxt.append(node[seg])
        cur = nxt
    return cur


def _text(nodes: list[Any]) -> str:
    return json.dumps(nodes, ensure_ascii=False).lower()


def _hit(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def score_rubric(doc: dict[str, Any] | None, spec: dict[str, Any]) -> dict[str, Any]:
    """{score, passed, total, failed: [ids], by_kind, structure: {score, failed}} for one document against one rubric section."""
    doc = doc or {}
    results: dict[str, bool] = {}
    by_kind: dict[str, list[int]] = {}
    for chk in spec["checks"]:
        text = _text([n for p in chk["sections"] for n in _resolve(doc, p)])
        ok = all(_hit(text, p) for p in chk.get("all", [])) and (not chk.get("any") or any(_hit(text, p) for p in chk["any"]))
        results[chk["id"]] = ok
        k = by_kind.setdefault(chk["kind"], [0, 0]); k[1] += 1; k[0] += int(ok)
    struct_failed: list[str] = []
    for path, rule in spec.get("structure", {}).items():
        nodes = _resolve(doc, path)
        items = nodes[0] if nodes and isinstance(nodes[0], list) else []
        n = len(items)
        if n < rule.get("min", 0):
            struct_failed.append(f"{path}: {n} < {rule['min']}")
        elif rule.get("max") and n > rule["max"]:
            struct_failed.append(f"{path}: {n} > {rule['max']}")
        else:
            missing = sum(1 for it in items if not isinstance(it, dict) or any(not str(it.get(f) or "").strip() for f in rule.get("fields", [])))
            if missing:
                struct_failed.append(f"{path}: {missing} item(s) missing {rule.get('fields')}")
    n_struct = len(spec.get("structure", {}))
    return {"score": round(sum(results.values()) / max(1, len(results)), 4), "passed": sum(results.values()), "total": len(results),
            "failed": [k for k, v in results.items() if not v], "by_kind": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_kind.items())},
            "structure": {"score": round(1 - len(struct_failed) / max(1, n_struct), 4), "failed": struct_failed}}


def grounding(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Recommendations grounded in evidence: items whose basis is 'research' must carry evidence ids."""
    research = grounded = refs = 0

    def walk(x: Any) -> None:
        nonlocal research, grounded, refs
        if isinstance(x, dict):
            ev = x.get("evidence")
            if isinstance(ev, list):
                refs += len(ev)
            if x.get("basis") == "research":
                research += 1
                grounded += bool(ev)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(doc or {})
    return {"research_items": research, "grounded": grounded, "fraction": round(grounded / research, 4) if research else None, "evidence_refs": refs}


# ------------------------------------------------------------------ arm plumbing

_ENV = ("MODEL", "THINKING", "EFFORT")


def _set_arm(tasks: list[str], model: str, thinking: str, effort: str | None) -> dict[str, str | None]:
    saved: dict[str, str | None] = {}
    for t in tasks:
        key = t.upper().replace(".", "_")
        for what in _ENV:
            k = f"NEUROSEARCH_TASK_{what}_{key}"
            saved[k] = os.environ.get(k)
            os.environ.pop(k, None)
        os.environ[f"NEUROSEARCH_TASK_MODEL_{key}"] = model
        os.environ[f"NEUROSEARCH_TASK_THINKING_{key}"] = thinking
        if effort:
            os.environ[f"NEUROSEARCH_TASK_EFFORT_{key}"] = effort
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _state_mark() -> float:
    time.sleep(0.01)
    return time.time()


def _restore_state(pid: str, mark: float) -> None:
    """Delete everything an arm wrote to the project after `mark` (eval database only): plans (+items/updates by cascade),
    notes, facts, conversations, and — since 0.56.0 — the research state (claims, their evidence, evidence targets,
    tensions, knowledge nodes). Sources, segments, analyses and the invocation ledger are left alone.

    The research state was added because the claims arm exposed the gap the hard way: `claims.run_evaluation`
    harvests claims and refreshes the Knowledge Map, and the chat prompt carries that state, so the chat arm's
    frozen input total moved from 210,014 to 220,887 the moment a claims arm ran before it. That is precisely the
    leak this function exists to prevent — 'every arm sees identical frozen inputs' has to hold whatever order the
    arms run in, not only in the order they happened to be written."""
    with db.tx() as conn:
        conn.execute("DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM project_claims WHERE project_id=? AND created_at>?)", (pid, mark))
        conn.execute("DELETE FROM claim_evidence_notes WHERE claim_id IN (SELECT id FROM project_claims WHERE project_id=? AND created_at>?)", (pid, mark))
        conn.execute("DELETE FROM project_evidence_targets WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM research_tensions WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM project_knowledge_nodes WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM project_claims WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM plan_items WHERE plan_id IN (SELECT id FROM plans WHERE project_id=? AND created_at>?)", (pid, mark))
        conn.execute("DELETE FROM plan_updates WHERE plan_id IN (SELECT id FROM plans WHERE project_id=? AND created_at>?)", (pid, mark))
        conn.execute("DELETE FROM plans WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM project_notes WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM project_facts WHERE project_id=? AND created_at>?", (pid, mark))
        conn.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE project_id=? AND created_at>?)", (pid, mark))
        conn.execute("DELETE FROM conversations WHERE project_id=? AND created_at>?", (pid, mark))


def _usage_since(ts: float, kinds: tuple[str, ...]) -> dict[str, Any]:
    q = ",".join("?" * len(kinds))
    r = db.connect().execute(f"SELECT SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read) cr, SUM(cache_write) cw, SUM(cost) c, COUNT(*) n "
                             f"FROM usage WHERE ts>=? AND kind IN ({q})", (ts, *kinds)).fetchone()
    return {"calls": int(r["n"] or 0), "input_tokens": int(r["i"] or 0), "output_tokens": int(r["o"] or 0), "cache_read_tokens": int(r["cr"] or 0),
            "cache_write_tokens": int(r["cw"] or 0), "cost": round(float(r["c"] or 0), 4)}


def _invocations_since(ts: float, task: str) -> dict[str, Any]:
    rows = db.connect().execute("SELECT state, COUNT(*) n, COUNT(DISTINCT logical_id) logical, GROUP_CONCAT(DISTINCT returned_model) rm "
                                "FROM invocations WHERE requested_at>=? AND task=? GROUP BY state", (ts, task)).fetchall()
    inv: dict[str, Any] = {"logical": 0, "attempts": 0, "by_state": {}, "outcome_unknown": 0}
    returned: set[str] = set()
    for r in rows:
        inv["attempts"] += r["n"]; inv["by_state"][r["state"]] = r["n"]
        if r["state"] == "completed":
            inv["logical"] += r["logical"]
        returned |= {m for m in (r["rm"] or "").split(",") if m}
    inv["outcome_unknown"] = inv["by_state"].get("outcome_unknown", 0)
    inv["returned_model"] = ", ".join(sorted(returned)) or None
    return inv


def _count_tokens(model: str, reqs: list[dict[str, Any]], live: bool, task: str | None = None) -> int | None:
    """Canonical input tokens over exact requests via the provider's token-counting endpoint (free). Also the preflight."""
    from . import contracts, providers
    strip = lambda sysb: [{k: v for k, v in b.items() if k != "cache_control"} for b in sysb] if isinstance(sysb, list) else sysb  # noqa: E731
    fmt: dict[str, Any] = {}
    if task and contracts.contract(task).schema:
        fmt = {"output_config": contracts.request_params(contracts.contract(task))["output_config"]}
    try:
        client = providers.anthropic_client()
        return sum(int(client.messages.count_tokens(model=model, system=strip(r["system"]), messages=r["messages"], **fmt).input_tokens) for r in reqs)
    except Exception as e:  # noqa: BLE001
        if live:
            raise RuntimeError(f"token counting failed for model {model!r} (preflight, nothing was spent): {e}") from e
        return None


def preflight(models: list[str], live: bool) -> dict[str, int | None]:
    """One tiny count_tokens per distinct model before any paid call: an unknown id fails here."""
    req = [{"system": "preflight", "messages": [{"role": "user", "content": "ping"}]}]
    return {m: _count_tokens(m, req, live) for m in models}


def _arm_meta(label: str, model: str, thinking: str, effort: str | None, tasks: list[str]) -> dict[str, Any]:
    from . import contracts
    return {"arm": label, "model": model, "thinking": thinking, "effort": effort, "contracts": {t: contracts.contract(t).describe() for t in tasks}}


# ------------------------------------------------------------------ planner arms (analysis + build from one build_plan)

def run_planner_arm(pid: str, live: bool, rubric: dict[str, Any], research: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import planner
    from .evidence import check_plan_evidence
    events: list[dict[str, Any]] = []
    planner.OBSERVER = events.append
    t0 = time.time()
    usage_from = time.time()
    err = None
    err_type = None
    row: dict[str, Any] | None = None
    try:
        row = planner.build_plan(pid, research=research)
    except Exception as e:  # noqa: BLE001
        err = str(e)[:300]
        err_type = type(e).__name__
    finally:
        planner.OBSERVER = None
    seconds = round(time.time() - t0, 2)
    plan = dict((row or {}).get("plan") or {})
    analysis = plan.pop("analysis", None) if plan else None
    if plan.get("_build"):
        # Planner V3: map the five structured calls onto the two reporting tasks (analysis ← situation; build ← the four components)
        for ev in events:
            if ev.get("task") == "planner.situation":
                ev["task"] = "planner.analysis"
            elif ev.get("task") in ("planner.core", "planner.execution", "planner.economics", "planner.actions"):
                ev["task"] = "planner.build"
        comp = [e for e in events if e.get("event") == "call" and e.get("task") == "planner.build"]
        if comp:
            merged = {"event": "call", "task": "planner.build", "truncated": any(e.get("truncated") for e in comp), "chars": sum(e.get("chars", 0) for e in comp),
                      "seconds": round(sum(e.get("seconds", 0) for e in comp), 2), "cost": round(sum(e.get("cost") or 0 for e in comp), 6),
                      "input_tokens": sum(e.get("input_tokens", 0) for e in comp), "output_tokens": sum(e.get("output_tokens", 0) for e in comp),
                      "cache_read": sum(e.get("cache_read", 0) for e in comp), "cache_write": sum(e.get("cache_write", 0) for e in comp),
                      "thinking_blocks": sum(e.get("thinking_blocks", 0) for e in comp), "model": comp[-1].get("model")}
            events = [e for e in events if not (e.get("event") == "call" and e.get("task") == "planner.build")] + [merged]
    emap = set((plan or {}).get("_evidence") or {})
    chk = (plan or {}).get("_evidence_check") or {}
    out: dict[str, Any] = {"error": err, "error_type": err_type if err else None, "seconds": seconds, "tasks": {},
                           "research_hash": (row or {}).get("plan", {}).get("_research_hash") if row else (research or {}).get("material_hash")}
    for task, doc, key in (("planner.analysis", analysis, "analysis"), ("planner.build", {k: v for k, v in plan.items() if not k.startswith("_")} if plan else None, "plan")):
        calls = [e for e in events if e.get("event") == "call" and e.get("task") == task]
        parses = [e for e in events if e.get("event") == "parse" and e.get("task") == task]
        r = score_rubric(doc, rubric[key])
        refs, dangling = check_plan_evidence(doc, emap) if doc else (0, [])
        c = calls[-1] if calls else {}
        out["tasks"][task] = {
            "present": doc is not None and bool(doc), "rubric": r, "grounding": grounding(doc),
            "evidence_refs": refs, "dangling_after_removal": len(dangling),
            "truncated": int(bool(c.get("truncated"))), "parse_failed": int(any(not p.get("ok") for p in parses)) if parses else int(doc is None),
            "json_repaired": int(any(p.get("repaired") for p in parses)),
            "output_chars": c.get("chars", 0), "output_tokens": c.get("output_tokens", 0), "input_tokens": c.get("input_tokens", 0),
            "cache_read": c.get("cache_read", 0), "cache_write": c.get("cache_write", 0), "cost": round(float(c.get("cost") or 0), 4),
            "thinking_tokens_est": max(0, int(c.get("output_tokens", 0)) - int(c.get("chars", 0)) // 4) if c.get("thinking_blocks") else 0,
            "thinking_blocks": c.get("thinking_blocks", 0), "seconds": c.get("seconds"), "invocations": _invocations_since(usage_from, task)}
    out["plan_evidence_dangling_raw"] = len(chk.get("dangling") or [])     # analysis + plan together, before removal
    out["planner_version"] = (plan.get("_build") or {}).get("planner_version", "v1")
    out["build_telemetry"] = plan.get("_build")
    out["plan_evidence_refs_raw"] = chk.get("references")
    out["plan"] = plan
    out["analysis"] = analysis
    out["plan_row_id"] = (row or {}).get("id")
    out["usage"] = _usage_since(usage_from, ("plan",))
    return out


# ------------------------------------------------------------------ planner.update arm

UPDATE_FINDING = ("New lender guidance: for acquisitions over $500k this lender now wants a fifteen percent equity injection and will "
                  "not count any seller note toward it — full standby or not.")
UPDATE_FACT = ("constraint", "I can bring $120k cash; my partner will not sign a personal guarantee.")


def run_update_arm(pid: str, live: bool) -> dict[str, Any]:
    from . import planner
    events: list[dict[str, Any]] = []
    planner.OBSERVER = events.append
    usage_from = time.time()
    t0 = time.time()
    try:
        updates = planner.suggest_updates(pid)
    finally:
        planner.OBSERVER = None
    seconds = round(time.time() - t0, 2)
    calls = [e for e in events if e.get("event") == "call"]
    parses = [e for e in events if e.get("event") == "parse"]
    c = calls[-1] if calls else {}
    p = parses[-1] if parses else {}
    text = json.dumps(updates).lower()
    return {"updates": updates, "n_updates": len(updates), "raw_updates": p.get("raw_updates"),
            "addresses_new_finding": int(any(k in text for k in ("15%", "fifteen percent", "equity injection", "seller note", "standby"))),
            "addresses_new_fact": int(any(k in text for k in ("personal guarantee", "120k", "$120", "partner", "cash"))),
            "well_formed": int(all(isinstance(u, dict) and u.get("section") and u.get("proposed") and u.get("reason") for u in updates)) if updates else 0,
            "truncated": int(bool(c.get("truncated"))), "parse_failed": int(not p.get("ok", True)), "json_repaired": int(bool(p.get("repaired"))),
            "output_chars": c.get("chars", 0), "output_tokens": c.get("output_tokens", 0), "input_tokens": c.get("input_tokens", 0),
            "cache_read": c.get("cache_read", 0), "cost": round(float(c.get("cost") or 0), 4), "seconds": seconds,
            "invocations": _invocations_since(usage_from, "planner.update"), "usage": _usage_since(usage_from, ("plan",))}


# ------------------------------------------------------------------ export arm

EXPORT_SECTIONS = ("Purpose", "Executive summary", "Key insights", "Recommended actions", "Open questions", "How to continue")


def run_export_arm(pid: str, live: bool) -> dict[str, Any]:
    from . import export
    notes = db.list_project_notes(pid)
    given_links = {m for n in notes for c in (n.get("citations") or []) for m in [c.get("link") or c.get("url")] if m}
    usage_from = time.time()
    t0 = time.time()
    text = export.synthesize_masterplan(pid)
    seconds = round(time.time() - t0, 2)
    c = dict(export._last_call)
    links = sorted(set(re.findall(r"\]\((https?://[^)\s]+|file://[^)\s]+)\)", text)))
    invented = sorted({u for u in links if u not in given_links})
    heads = [h.strip() for h in re.findall(r"^#{1,3}\s+(.+)$", text, re.M)]
    missing = [s for s in EXPORT_SECTIONS if not any(s.lower() in h.lower() for h in heads)]
    return {"chars": len(text), "words": len(text.split()), "citation_links": len(links), "invented_links": invented, "n_invented_links": len(invented),
            "link_coverage": round(len({u for u in links if u in given_links}) / max(1, len(given_links)), 4), "given_links": len(given_links),
            "sections_missing": missing, "sections_present": len(EXPORT_SECTIONS) - len(missing),
            "truncated": int(bool(c.get("truncated"))), "empty": int(bool(c.get("empty"))), "fallback_used": int("Set ANTHROPIC_API_KEY" in text),
            "seconds": seconds, "invocations": _invocations_since(usage_from, "export.synthesis"), "usage": _usage_since(usage_from, ("synthesis",)),
            "text": text}


# ------------------------------------------------------------------ claims arm (claims.extract)
#
# 0.56.0. `claims.extract` is the most expensive HELD task under the model decision engine ($33.03 of a $103.51
# month) and its justification is `irreversible` — a debt, meaning "we have not compared it". This is the arm that
# pays the debt.
#
# It invents no rubric. `claims.run_evaluation` already measures exactly what normalization is FOR — qualifiers
# preserved, hedges kept, over-generalizations, merges, type changes — because that is the bounded evaluation the
# rung had to pass to earn adoption in the first place. Reusing it means the comparison is judged by the product's
# own definition of good rather than by one written to make a model look right.

def _reset_normalization(pid: str, ids: list[str], before: dict[str, Any]) -> None:
    """Put the cohort back to candidates so the next arm actually spends on the SAME claims. Text and type are
    restored from the snapshot the evaluation took, so arm two starts from arm one's input, not its output."""
    with db.tx() as conn:
        for cid in ids:
            b = (before.get("claims") or {}).get(cid)
            if not b:
                continue
            conn.execute("UPDATE project_claims SET normalized=0, extraction_hash=NULL, text=?, claim_type=?, topic=?, "
                         "freshness_class=?, status=CASE WHEN status='superseded' THEN 'proposed' ELSE status END, superseded_by=NULL WHERE id=?",
                         (b["text"], b["type"], b["topic"], b["freshness"], cid))
    db.kv_set(f"claims:eval:{pid}", None)
    db.kv_set(f"claims:eval:{pid}:pending", None)


def run_claims_arm(pid: str, live: bool) -> dict[str, Any]:
    from . import claims
    usage_from = time.time()
    t0 = time.time()
    rep = claims.run_evaluation(pid, budget=CLAIMS_EVAL_BUDGET)
    seconds = round(time.time() - t0, 2)
    full = claims.evaluation_report(pid) or {}
    hedged, kept = int(rep.get("hedged_before") or 0), int(rep.get("hedges_kept") or 0)
    cohort = int((rep.get("cohort") or {}).get("size") or 0)
    return {"cohort": cohort, "normalized": rep.get("normalized", 0), "calls": rep.get("calls", 0),
            "qualifiers_present": rep.get("qualifiers_present", 0),
            "qualifier_rate": round(int(rep.get("qualifiers_present") or 0) / max(1, cohort), 4),
            "hedged_before": hedged, "hedges_kept": kept,
            "hedge_rate": round(kept / hedged, 4) if hedged else 1.0,
            "over_generalized": [o["id"] for o in (rep.get("over_generalized") or [])],
            "n_over_generalized": len(rep.get("over_generalized") or []),
            "merged": rep.get("merged", 0), "type_changes": rep.get("type_changes", 0),
            "targets_proposed": rep.get("targets_proposed", 0), "seconds": seconds,
            "invocations": _invocations_since(usage_from, "claims.extract"), "usage": _usage_since(usage_from, ("claims",)),
            "_before": (full or {}).get("_before") or {}, "rows": (full or {}).get("rows") or []}


def claims_verdict(arms: dict[str, dict[str, Any]], metas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b, d = arms[SLOT_BASE], arms[SLOT_CAND]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    if d["qualifier_rate"] < b["qualifier_rate"] - CLAIMS_QUALIFIER_TOLERANCE:
        fails.append(f"qualifiers preserved on {d['qualifier_rate']:.0%} of the cohort vs {b['qualifier_rate']:.0%} — "
                     "normalization exists to keep them; dropping them is how a claim quietly becomes wrong")
    if d["n_over_generalized"] > b["n_over_generalized"]:
        fails.append(f"{d['n_over_generalized']} over-generalized claims vs {b['n_over_generalized']} "
                     f"({', '.join(d['over_generalized'][:3])})")
    if d["hedge_rate"] < b["hedge_rate"] - CLAIMS_QUALIFIER_TOLERANCE:
        fails.append(f"hedges kept on {d['hedge_rate']:.0%} of hedged claims vs {b['hedge_rate']:.0%} — a dropped hedge is a stronger claim than the evidence supports")
    if d["normalized"] < b["normalized"]:
        caveats.append(f"normalized {d['normalized']} of {d['cohort']} vs {b['normalized']} — fewer claims processed for the same cohort")
    if d["merged"] != b["merged"]:
        notes.append(f"merges: {b['merged']} → {d['merged']} (a different merge count is not by itself better or worse)")
    if d["targets_proposed"] != b["targets_proposed"]:
        notes.append(f"evidence targets proposed: {b['targets_proposed']} → {d['targets_proposed']}")
    _cost_latency(b, d, caveats, cost_key="cost", secs_key="seconds")
    _model_gate("claims.extract", metas[SLOT_CAND], d["invocations"], fails, SLOT_CAND)
    _model_gate("claims.extract", metas[SLOT_BASE], b["invocations"], fails, SLOT_BASE)
    return _finish("claims.extract", metas[SLOT_BASE]["model"], metas[SLOT_CAND]["model"], fails, caveats, notes,
                   {"qualifier_rate": [b["qualifier_rate"], d["qualifier_rate"]],
                    "hedge_rate": [b["hedge_rate"], d["hedge_rate"]],
                    "over_generalized": [b["n_over_generalized"], d["n_over_generalized"]],
                    "normalized": [b["normalized"], d["normalized"]], "cohort": b["cohort"]})


# ------------------------------------------------------------------ chat arm (answer.chat + answer.repair)

def run_chat_arm(pid: str, ids: dict[str, str], man: dict[str, Any], live: bool, progress: Any) -> dict[str, Any]:
    from . import qa
    events: list[dict[str, Any]] = []
    qa.OBSERVER = events.append
    usage_from = time.time()
    t0 = time.time()
    qs = [q for q in man["questions"] if not q.get("calculator")]
    per_q: list[dict[str, Any]] = []
    cited_expected = expected_n = 0
    invalid_total = valid_total = 0
    gap_ok = gap_n = contra_ok = contra_n = 0
    offtopic_ok = offtopic_n = 0
    failed = repaired = unrepaired = 0
    try:
        for i, q in enumerate(qs):
            n_before = len(events)
            try:
                res = qa.ask(q["q"], project_id=pid)
            except Exception as e:  # noqa: BLE001
                failed += 1
                per_q.append({"q": q["q"], "error": str(e)[:200]})
                continue
            mine = events[n_before:]
            cited = {c["source_id"] for c in res["citations"]}
            rec: dict[str, Any] = {"q": q["q"], "cited": sorted({gid for gid, sid in ids.items() if sid in cited}), "chars": len(res["answer"]),
                                   "rounds": sum(1 for e in mine if e.get("task") == "answer.chat"), "tools": [t for e in mine for t in e.get("tools", [])],
                                   "truncated": int(any(e.get("stop_reason") == "max_tokens" for e in mine)),
                                   "invalid_citations": len(res.get("invalid_citations") or []), "repaired": int(bool((res.get("validation") or {}).get("repaired")))}
            invalid_total += rec["invalid_citations"]; valid_total += len(res["citations"])
            repaired += rec["repaired"]; unrepaired += int(bool(res.get("invalid_citations")))
            if q.get("gap"):
                gap_n += 1; ok = ("gap:" in res["answer"].lower()) or not res["citations"]; gap_ok += ok; rec["gap_ok"] = ok
            elif q.get("offtopic"):
                offtopic_n += 1; ok = bool(cited & {ids[s] for s in q["sources"]}) or not cited; offtopic_ok += ok; rec["offtopic_ok"] = ok
            elif q.get("sources"):
                expected_n += 1; ok = bool(cited & {ids[s] for s in q["sources"]}); cited_expected += ok; rec["expected_ok"] = ok
            if q.get("contradicts"):
                contra_n += 1
                ok = bool(cited & {ids[s] for s in q["sources"]}) and bool(cited & {ids[s] for s in q["contradicts"]})
                contra_ok += ok; rec["contradiction_ok"] = ok
            per_q.append(rec)
            if progress and (i + 1) % 10 == 0:
                progress(f"   {i + 1}/{len(qs)} questions")
    finally:
        qa.OBSERVER = None
    repairs = [e for e in events if e.get("task") == "answer.repair"]
    inv_chat, inv_rep = _invocations_since(usage_from, "answer.chat"), _invocations_since(usage_from, "answer.repair")
    return {"answers": len(qs) - failed, "failed_answers": failed, "questions": len(qs),
            "citation_validity": round(1 - invalid_total / (valid_total + invalid_total), 4) if (valid_total + invalid_total) else 1.0,
            "answers_cite_expected_source": round(cited_expected / max(1, expected_n), 4), "expected_questions": expected_n,
            "gap_detection": round(gap_ok / gap_n, 4) if gap_n else None, "gap_questions": gap_n,
            "contradiction_surfaced": round(contra_ok / contra_n, 4) if contra_n else None, "contradiction_questions": contra_n,
            "offtopic_handled": round(offtopic_ok / offtopic_n, 4) if offtopic_n else None,
            "repair_rounds": len(repairs), "repairs_succeeded": sum(1 for e in repairs if e.get("success")), "answers_repaired": repaired,
            "answers_with_unrepaired_invalid_citations": unrepaired, "truncated_answers": sum(r.get("truncated", 0) for r in per_q),
            "tool_rounds": sum(max(0, r.get("rounds", 1) - 1) for r in per_q), "tool_calls": sum(len(r.get("tools", [])) for r in per_q),
            "mean_answer_chars": round(sum(r.get("chars", 0) for r in per_q) / max(1, len(per_q))),
            "seconds": round(time.time() - t0, 2), "s_per_answer": round((time.time() - t0) / max(1, len(qs) - failed), 2),
            "invocations": inv_chat, "repair_invocations": inv_rep, "usage": _usage_since(usage_from, ("answer",)), "per_question": per_q}


# ------------------------------------------------------------------ verdicts (quality + validity gate; cost/latency caveat)

def _cost_latency(base: dict[str, Any], cand: dict[str, Any], caveats: list[str], cost_key: str = "cost", secs_key: str = "seconds") -> None:
    bc, cc = base["usage"][cost_key], cand["usage"][cost_key]
    if bc and cc > bc * (1 + COST_TOLERANCE):
        caveats.append(f"cost up {(cc / bc - 1):+.0%}: ${bc:.4f} → ${cc:.4f}")
    bl, cl = base[secs_key], cand[secs_key]
    if bl and bl >= 1.0 and cl > bl * (1 + LATENCY_TOLERANCE):       # sub-second timings are noise, never a caveat
        caveats.append(f"latency up {(cl / bl - 1):+.0%}: {bl}s → {cl}s")


def _model_gate(task: str, arm: dict[str, Any], inv: dict[str, Any], fails: list[str], label: str) -> None:
    if inv.get("outcome_unknown"):
        fails.append(f"[{label}] {inv['outcome_unknown']} {task} invocation(s) with unknown outcome")
    if inv.get("attempts") and not model_matches(arm["model"], inv.get("returned_model")):
        fails.append(f"[{label}] {task} returned model {inv.get('returned_model')!r} is not the configured {arm['model']!r}")


def _finish(task: str, base_model: str, cand_model: str, fails: list[str], caveats: list[str], notes: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if fails:
        v, h = "FAIL", f"FAIL — keep {base_model} for {task}"
    elif caveats:
        v, h = "PASS_WITH_CAVEAT", f"PASS WITH CAVEAT — {cand_model} holds quality on {task}; review the caveats before migrating"
    else:
        v, h = "PASS", f"PASS — migrate {task} to {cand_model}"
    rs = {"model": cand_model, "thinking": "disabled", "effort": None} if not fails else {"model": base_model, "thinking": "disabled", "effort": None}
    return {"task": task, "verdict": v, "headline": h, "fails": fails, "caveats": caveats, "notes": notes, "production_default_changed": False,
            "recommended_setting": rs, **(extra or {})}


def planner_verdict(task: str, arms: dict[str, dict[str, Any]], metas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Per planner task (analysis or build). Gates on the disabled arm vs 4.6; then decides whether adaptive earns its keep."""
    b, d, a = arms[SLOT_BASE], arms[SLOT_CAND], arms.get(SLOT_ADAPT)
    bt, dt = b["tasks"][task], d["tasks"][task]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    if d.get("error"):
        fails.append(f"build_plan failed on the candidate: {d['error']}")
    if b.get("error"):
        fails.append(f"build_plan failed on the BASELINE: {b['error']} — comparison is not like-for-like")
    if not dt["present"]:
        fails.append(f"{task} produced no usable JSON")
    if dt["truncated"]:
        fails.append("output hit max_tokens (truncated)")
    if dt["parse_failed"]:
        fails.append("JSON could not be parsed or repaired")
    if dt["json_repaired"] and not bt["json_repaired"]:
        fails.append("JSON needed repair (baseline did not)")
    if dt["dangling_after_removal"]:
        fails.append(f"{dt['dangling_after_removal']} evidence references still dangling after validation")
    if task == "planner.build" and d["plan_evidence_dangling_raw"] > b["plan_evidence_dangling_raw"] + 2:
        fails.append(f"invented evidence ids rose {b['plan_evidence_dangling_raw']} → {d['plan_evidence_dangling_raw']} (analysis+plan, before removal)")
    elif task == "planner.build" and d["plan_evidence_dangling_raw"] > b["plan_evidence_dangling_raw"]:
        caveats.append(f"invented evidence ids rose {b['plan_evidence_dangling_raw']} → {d['plan_evidence_dangling_raw']} (removed by the validator)")
    _model_gate(task, metas[SLOT_CAND], dt["invocations"], fails, SLOT_CAND)
    _model_gate(task, metas[SLOT_BASE], bt["invocations"], fails, SLOT_BASE)
    br, dr = bt["rubric"]["score"], dt["rubric"]["score"]
    if dr < br - RUBRIC_TOLERANCE - 1e-9:
        fails.append(f"rubric fell beyond tolerance: {br} → {dr} (lost: {', '.join(sorted(set(dt['rubric']['failed']) - set(bt['rubric']['failed'])))})")
    elif dr < br:
        caveats.append(f"rubric slightly lower: {br} → {dr} (lost: {', '.join(sorted(set(dt['rubric']['failed']) - set(bt['rubric']['failed'])))})")
    bs, ds = bt["rubric"]["structure"]["score"], dt["rubric"]["structure"]["score"]
    if ds < bs - 1e-9:
        caveats.append(f"structure checks lower: {bs} → {ds} ({'; '.join(dt['rubric']['structure']['failed'])})")
    bg, dg = bt["grounding"]["fraction"], dt["grounding"]["fraction"]
    if bg is not None and dg is not None and dg < bg - GROUNDING_TOLERANCE - 1e-9:
        fails.append(f"research-based items without evidence rose: grounded {bg} → {dg}")
    elif bg is not None and dg is not None and dg < bg:
        caveats.append(f"grounding slightly lower: {bg} → {dg}")
    if dt["evidence_refs"] < 0.5 * bt["evidence_refs"]:
        caveats.append(f"far fewer evidence references: {bt['evidence_refs']} → {dt['evidence_refs']}")
    _cost_latency(b, d, caveats)
    # adaptive: only recommended when it measurably beats disabled
    adaptive: dict[str, Any] = {"recommended": False, "reason": "no adaptive arm"}
    if a is not None:
        at = a["tasks"][task]
        a_fails: list[str] = []
        if a.get("error") or not at["present"] or at["truncated"] or at["parse_failed"] or at["dangling_after_removal"]:
            a_fails.append("adaptive arm failed a validity gate (" + ", ".join(k for k in ("error", "truncated", "parse_failed") if a.get(k) or at.get(k)) + ")")
        _model_gate(task, metas[SLOT_ADAPT], at["invocations"], a_fails, SLOT_ADAPT)
        gain = round(at["rubric"]["score"] - dr, 4)
        struct_gain = round(at["rubric"]["structure"]["score"] - ds, 4)
        removed = [k for k in ("json_repaired", "truncated") if dt[k] and not at[k]]
        wins = []
        if gain >= RUBRIC_WIN - 1e-9:
            wins.append(f"rubric +{gain} ({dr} → {at['rubric']['score']})")
        if removed:
            wins.append("removed failure mode: " + ", ".join(removed))
        if struct_gain >= 0.25 - 1e-9:
            wins.append(f"completeness +{struct_gain}")
        if a_fails:
            adaptive = {"recommended": False, "reason": "; ".join(a_fails), "rubric_gain": gain}
        elif wins and at["rubric"]["score"] >= dr:
            adaptive = {"recommended": True, "reason": "; ".join(wins), "rubric_gain": gain}
        else:
            adaptive = {"recommended": False, "reason": f"quality effectively equal (rubric {dr} vs {at['rubric']['score']}, structure {ds} vs {at['rubric']['structure']['score']}) — disabled is simpler, faster and cheaper", "rubric_gain": gain}
        adaptive.update({"thinking_tokens_est": at["thinking_tokens_est"], "cost": at["cost"], "seconds": at["seconds"], "rubric": at["rubric"]["score"], "failed_checks": at["rubric"]["failed"]})
        notes.append(f"adaptive/medium: rubric {at['rubric']['score']} vs disabled {dr}; ~{at['thinking_tokens_est']:,} thinking tokens; ${at['cost']:.4f} vs ${dt['cost']:.4f}; {at['seconds']}s vs {dt['seconds']}s")
    notes.append("single run per arm (n=1): differences inside the tolerances are not distinguishable from run-to-run noise")
    cand = metas[SLOT_CAND]["model"]
    out = _finish(task, metas[SLOT_BASE]["model"], cand, fails, caveats, notes, {"adaptive": adaptive})
    if out["verdict"] != "FAIL" and adaptive.get("recommended"):
        out["headline"] = out["headline"].replace(f"migrate {task} to {cand}", f"migrate {task} to {cand} with ADAPTIVE thinking (medium)") if out["verdict"] == "PASS" else out["headline"] + " (adaptive/medium recommended over disabled)"
        out["recommended_setting"] = {"model": cand, "thinking": "adaptive", "effort": "medium"}
    elif out["verdict"] != "FAIL":
        out["recommended_setting"] = {"model": cand, "thinking": "disabled", "effort": None}
    else:
        out["recommended_setting"] = {"model": metas[SLOT_BASE]["model"], "thinking": "disabled", "effort": None}
    return out


def update_verdict(arms: dict[str, dict[str, Any]], metas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b, d = arms[SLOT_BASE], arms[SLOT_CAND]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    if d["parse_failed"] or d["truncated"]:
        fails.append("update output truncated or unparsable")
    if d["json_repaired"] and not b["json_repaired"]:
        fails.append("update JSON needed fence/prose stripping (baseline did not)")
    _model_gate("planner.update", metas[SLOT_CAND], d["invocations"], fails, SLOT_CAND)
    _model_gate("planner.update", metas[SLOT_BASE], b["invocations"], fails, SLOT_BASE)
    if b["addresses_new_finding"] and not d["addresses_new_finding"]:
        fails.append("the candidate did not propose an update for the new lender finding (15% injection / seller note) that the baseline caught")
    if b["addresses_new_fact"] and not d["addresses_new_fact"]:
        caveats.append("the candidate did not react to the new user constraint (partner will not sign a guarantee) that the baseline did")
    if not d["addresses_new_finding"] and not b["addresses_new_finding"]:
        caveats.append("neither arm proposed an update for the new lender finding")
    if d["n_updates"] and not d["well_formed"]:
        fails.append("updates missing section/proposed/reason")
    if d["n_updates"] > 3 * max(1, b["n_updates"]):
        caveats.append(f"many more updates proposed: {b['n_updates']} → {d['n_updates']} (style rewrites are not wanted)")
    notes.append(f"updates proposed: {b['n_updates']} → {d['n_updates']}")
    _cost_latency(b, d, caveats)
    notes.append("single run per arm (n=1)")
    return _finish("planner.update", metas[SLOT_BASE]["model"], metas[SLOT_CAND]["model"], fails, caveats, notes)


def export_verdict(arms: dict[str, dict[str, Any]], metas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    b, d = arms[SLOT_BASE], arms[SLOT_CAND]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    if d["n_invented_links"]:
        fails.append(f"{d['n_invented_links']} citation link(s) not in the material (invented evidence): {', '.join(d['invented_links'][:3])}")
    if d["sections_missing"]:
        fails.append("required sections missing: " + ", ".join(d["sections_missing"]))
    if d["truncated"] or d["empty"] or d["fallback_used"]:
        fails.append("synthesis truncated, empty or fell back to the placeholder")
    _model_gate("export.synthesis", metas[SLOT_CAND], d["invocations"], fails, SLOT_CAND)
    _model_gate("export.synthesis", metas[SLOT_BASE], b["invocations"], fails, SLOT_BASE)
    if d["link_coverage"] < b["link_coverage"] - EXPORT_COVERAGE_TOLERANCE - 1e-9:
        fails.append(f"far fewer of the given citations preserved: {b['link_coverage']} → {d['link_coverage']}")
    elif d["link_coverage"] < b["link_coverage"]:
        caveats.append(f"fewer of the given citations preserved: {b['link_coverage']} → {d['link_coverage']}")
    if d["words"] < 0.5 * b["words"]:
        caveats.append(f"much shorter: {b['words']} → {d['words']} words")
    _cost_latency(b, d, caveats)
    notes.append(f"words {b['words']} → {d['words']}; citation links {b['citation_links']} → {d['citation_links']} of {d['given_links']} given")
    notes.append("single run per arm (n=1)")
    return _finish("export.synthesis", metas[SLOT_BASE]["model"], metas[SLOT_CAND]["model"], fails, caveats, notes)


def chat_verdict(arms: dict[str, dict[str, Any]], metas: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    b, d = arms[SLOT_BASE], arms[SLOT_CAND]
    fails: list[str] = []
    caveats: list[str] = []
    notes: list[str] = []
    if d["failed_answers"]:
        fails.append(f"{d['failed_answers']} question(s) raised an error")
    if d["citation_validity"] < 1.0 or d["answers_with_unrepaired_invalid_citations"]:
        fails.append(f"citation validity {d['citation_validity']} — {d['answers_with_unrepaired_invalid_citations']} answer(s) kept an invalid citation after repair")
    if d["truncated_answers"]:
        fails.append(f"{d['truncated_answers']} incomplete answer(s) (max_tokens)")
    _model_gate("answer.chat", metas[SLOT_CAND], d["invocations"], fails, SLOT_CAND)
    _model_gate("answer.chat", metas[SLOT_BASE], b["invocations"], fails, SLOT_BASE)
    if d["answers_cite_expected_source"] < b["answers_cite_expected_source"] - CHAT_SOURCE_TOLERANCE - 1e-9:
        fails.append(f"cites-expected-source fell beyond tolerance: {b['answers_cite_expected_source']} → {d['answers_cite_expected_source']}")
    elif d["answers_cite_expected_source"] < b["answers_cite_expected_source"]:
        caveats.append(f"cites-expected-source lower: {b['answers_cite_expected_source']} → {d['answers_cite_expected_source']}")
    for k, n_key, label in (("contradiction_surfaced", "contradiction_questions", "contradiction handling"), ("gap_detection", "gap_questions", "gap detection")):
        bv, dv, n = b.get(k), d.get(k), d.get(n_key) or 0
        if bv is None or dv is None or not n:
            continue
        lost = round((bv - dv) * n)
        if lost >= 2:
            fails.append(f"{label} lost {lost} of {n} questions: {bv} → {dv}")
        elif lost == 1:
            caveats.append(f"{label} lost 1 of {n} questions: {bv} → {dv}")
    if d["repair_rounds"] > b["repair_rounds"] + 2:
        fails.append(f"repair rounds rose {b['repair_rounds']} → {d['repair_rounds']} (first answers cite excerpts that do not exist)")
    elif d["repair_rounds"] > b["repair_rounds"]:
        caveats.append(f"repair rounds rose {b['repair_rounds']} → {d['repair_rounds']}")
    if d.get("offtopic_handled") is not None and b.get("offtopic_handled") is not None and d["offtopic_handled"] < b["offtopic_handled"]:
        caveats.append(f"off-topic questions handled: {b['offtopic_handled']} → {d['offtopic_handled']}")
    if d["tool_calls"] > 2 * max(1, b["tool_calls"]) + 2:
        caveats.append(f"many more tool calls: {b['tool_calls']} → {d['tool_calls']}")
    _cost_latency(b, d, caveats, secs_key="s_per_answer")
    notes.append(f"answers {b['answers']} → {d['answers']}; mean length {b['mean_answer_chars']} → {d['mean_answer_chars']} chars (wording differences are not failures)")
    notes.append("single run per arm (n=1): differences inside the tolerances are not distinguishable from run-to-run noise")
    chat = _finish("answer.chat", metas[SLOT_BASE]["model"], metas[SLOT_CAND]["model"], fails, caveats, notes)
    # answer.repair: judged on repair behaviour, migrates alongside chat
    r_fails: list[str] = []
    r_caveats: list[str] = []
    r_notes: list[str] = []
    if chat["verdict"] == "FAIL":
        r_fails.append("answer.chat failed; repair migrates only alongside chat")
    if d["repair_rounds"] and d["repairs_succeeded"] < d["repair_rounds"]:
        r_fails.append(f"{d['repair_rounds'] - d['repairs_succeeded']} of {d['repair_rounds']} repair round(s) still cited nonexistent excerpts")
    _model_gate("answer.repair", metas[SLOT_CAND], d["repair_invocations"], r_fails, SLOT_CAND)
    if not d["repair_rounds"] and not b["repair_rounds"]:
        r_caveats.append("no repair round was triggered on either arm — repair behaviour is unexercised; it shares chat's prompt family and contract, so it migrates with chat")
    elif not d["repair_rounds"]:
        r_notes.append(f"candidate needed no repair rounds (baseline {b['repair_rounds']})")
    r_notes.append(f"repair rounds {b['repair_rounds']} → {d['repair_rounds']}, succeeded {b['repairs_succeeded']} → {d['repairs_succeeded']}")
    repair = _finish("answer.repair", metas[SLOT_BASE]["model"], metas[SLOT_CAND]["model"], r_fails, r_caveats, r_notes)
    if chat["verdict"] == "PASS_WITH_CAVEAT" and repair["verdict"] == "PASS":
        repair["verdict"], repair["headline"] = "PASS_WITH_CAVEAT", "PASS WITH CAVEAT — migrate answer.repair alongside answer.chat (see chat's caveats)"
    return chat, repair


# ------------------------------------------------------------------ the run

def run_migration_compare(root: Path = GOLDEN, live: bool = False, out_dir: Path = Path("evals"), progress: Any = print,
                          skip_adaptive: bool = False, baseline_model: str = BASELINE_MODEL,
                          candidate_model: str = CANDIDATE_MODEL) -> dict[str, Any]:
    from . import __version__, findings, planner
    from . import usage as _usage
    rubric = load_rubric()
    arms_for = task_arms(baseline_model, candidate_model, skip_adaptive)
    bad_arms = validate_arms(arms_for)
    if bad_arms:
        raise RuntimeError("these arms cannot run (checked before any spending, nothing was charged):\n  - " + "\n  - ".join(bad_arms))
    if not skip_adaptive and not supports_adaptive(candidate_model):
        progress(f"adaptive planner arm skipped: {candidate_model} does not support adaptive thinking")
    spend = expected_spend(arms_for)
    progress(f"expected spend ≈ ${spend['estimate']:.2f}, maximum ≈ ${spend['maximum']:.2f} (eval-only budget ${spend['budget']:.2f} in the temporary database; your real budget is untouched)")
    db.kv_set("daily_budget", str(spend["budget"]))
    db.kv_set("monthly_budget", str(spend["budget"]))
    models = sorted({m for arms in arms_for.values() for _, m, _, _ in arms})
    pf = preflight(models, live)
    progress("preflight ok: " + ", ".join(f"{m} ({n} tokens)" for m, n in pf.items()))
    t_all = time.time()
    sha = git_sha()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = out_dir / "migration-compare" / f"{stamp}-{sha}"
    d.mkdir(parents=True, exist_ok=True)
    rep: dict[str, Any] = {"eval": "migration-compare", "tier": "live" if live else "fake", "app_version": __version__, "git_sha": sha, "started": stamp,
                           "spend_estimate": spend, "preflight": pf, "prompt_versions": prompt_versions(), "rubric_version": rubric.get("version"),
                           "arms": {}, "verdicts": {}, "files": [], "excluded": {"discover.quick": "no frozen exit test (judgement-based shortlist)",
                                                                                   "discover.verify": "uses the live web_search tool; not freezable"}}

    # ---- shared frozen inputs
    t0 = time.time()
    g = load_golden(root)
    pid, ids, man = g["project_id"], g["sources"], g["manifest"]
    for gid, sid in ids.items():
        if gid != "calc":
            findings.suggest_for_source(pid, sid)
    for n in db.list_project_notes(pid, status="suggested"):
        db.set_note_status(n["id"], "approved")
    n_notes = len(db.list_project_notes(pid))
    rep["shared_inputs"] = {"sources": len(ids), "approved_findings": n_notes, "findings_contract": __import__("neurosearch.contracts", fromlist=["contract"]).contract("findings.extract").describe(),
                            "prepared_s": round(time.time() - t0, 2), "shared_cost": _usage_since(t_all, ("findings", "embed"))["cost"]}
    progress(f"shared inputs ready: {len(ids)} sources, {n_notes} approved findings ({rep['shared_inputs']['prepared_s']}s)")
    mark = _state_mark()

    def save(name: str, obj: Any) -> None:
        f = d / name
        f.write_text(json.dumps(obj, indent=1, default=str)); rep["files"].append(str(f))

    # 0.56.2: a stage that dies must not take the completed stages with it. The Haiku run lost two paid planner
    # arms to a ContractError raised while setting up a third — the per-arm JSON files survived on disk but the
    # comparison report was never written, so nothing said what the $0.39 had already measured.
    stage_error: dict[str, Any] | None = None
    try:
        # ---- planner: analysis + build (3 arms)
        arms_p: dict[str, dict[str, Any]] = {}
        metas_p: dict[str, dict[str, Any]] = {}
        base_plan: dict[str, Any] | None = None
        for label, model, thinking, effort in arms_for["planner"]:
            if skip_adaptive and thinking == "adaptive":
                continue
            saved = _set_arm(["planner.analysis", "planner.build"], model, thinking, effort)
            try:
                metas_p[label] = _arm_meta(label, model, thinking, effort, ["planner.analysis", "planner.build"])
                progress(f"[planner · {label}] {model} thinking={thinking}{'/' + effort if effort else ''}")
                arms_p[label] = run_planner_arm(pid, live, rubric)
            finally:
                _restore_env(saved)
            a = arms_p[label]
            for t in ("planner.analysis", "planner.build"):
                tt = a["tasks"][t]
                progress(f"[{t} · {label}] rubric {tt['rubric']['score']} ({tt['rubric']['passed']}/{tt['rubric']['total']}) · structure {tt['rubric']['structure']['score']} · refs {tt['evidence_refs']} · "
                         f"repaired {tt['json_repaired']} · truncated {tt['truncated']} · ${tt['cost']:.4f} · {tt['seconds']}s · returned {tt['invocations'].get('returned_model')}")
            if label == SLOT_BASE:
                base_plan = {"plan": a["plan"], "analysis": a["analysis"]}
            save(f"planner-{label}.json", {k: v for k, v in a.items()})
            _restore_state(pid, mark)
        rep["arms"]["planner"] = {k: {"meta": metas_p[k], **{kk: vv for kk, vv in v.items() if kk not in ("plan", "analysis")}} for k, v in arms_p.items()}
        for t in ("planner.analysis", "planner.build"):
            rep["verdicts"][t] = planner_verdict(t, arms_p, metas_p)

        # ---- planner.update (2 arms): the 4.6 plan is the frozen current plan; one new finding + one new fact arrive after it
        arms_u: dict[str, dict[str, Any]] = {}
        metas_u: dict[str, dict[str, Any]] = {}
        if base_plan and base_plan["plan"]:
            frozen = dict(base_plan["plan"])
            if base_plan["analysis"]:
                frozen["analysis"] = base_plan["analysis"]
            yt = ids.get("yt01")
            src = db.get_source(yt) if yt else None
            for label, model, thinking, effort in arms_for["planner.update"]:
                db.save_plan(pid, json.loads(json.dumps(frozen)), db.project_snapshot(pid))
                time.sleep(0.02)
                cite = [{"n": 1, "source_id": yt, "title": src["title"], "channel": src.get("channel"), "url": src["url"], "link": src["url"],
                         "timestamp": "0:12", "start": 12, "end": 12, "platform": src["platform"], "snippet": "ten percent equity injection"}] if src else []
                db.add_project_note(pid, UPDATE_FINDING + " [1]", cite)
                db.add_fact(pid, UPDATE_FACT[0], UPDATE_FACT[1])
                saved = _set_arm(["planner.update"], model, thinking, effort)
                try:
                    metas_u[label] = _arm_meta(label, model, thinking, effort, ["planner.update"])
                    progress(f"[planner.update · {label}] {model} thinking={thinking}")
                    arms_u[label] = run_update_arm(pid, live)
                finally:
                    _restore_env(saved)
                u = arms_u[label]
                progress(f"[planner.update · {label}] {u['n_updates']} updates · new finding addressed {u['addresses_new_finding']} · new fact {u['addresses_new_fact']} · "
                         f"repaired {u['json_repaired']} · ${u['cost']:.4f} · {u['seconds']}s · returned {u['invocations'].get('returned_model')}")
                save(f"planner.update-{label}.json", u)
                _restore_state(pid, mark)
            rep["arms"]["planner.update"] = {k: {"meta": metas_u[k], **v} for k, v in arms_u.items()}
            rep["verdicts"]["planner.update"] = update_verdict(arms_u, metas_u)
        else:
            rep["verdicts"]["planner.update"] = {"task": "planner.update", "verdict": "FAIL", "headline": "FAIL — no baseline plan to update (4.6 build failed)", "fails": ["no baseline plan"], "caveats": [], "notes": []}

        # ---- export.synthesis (2 arms)
        arms_e: dict[str, dict[str, Any]] = {}
        metas_e: dict[str, dict[str, Any]] = {}
        for label, model, thinking, effort in arms_for["export.synthesis"]:
            saved = _set_arm(["export.synthesis"], model, thinking, effort)
            try:
                metas_e[label] = _arm_meta(label, model, thinking, effort, ["export.synthesis"])
                progress(f"[export.synthesis · {label}] {model} thinking={thinking}")
                arms_e[label] = run_export_arm(pid, live)
            finally:
                _restore_env(saved)
            e = arms_e[label]
            progress(f"[export.synthesis · {label}] {e['words']} words · sections {e['sections_present']}/{len(EXPORT_SECTIONS)} · links {e['citation_links']} (invented {e['n_invented_links']}, coverage {e['link_coverage']}) · "
                     f"truncated {e['truncated']} · ${e['usage']['cost']:.4f} · {e['seconds']}s · returned {e['invocations'].get('returned_model')}")
            save(f"export.synthesis-{label}.json", e)
            (d / f"export.synthesis-{label}.md").write_text(e["text"])
            _restore_state(pid, mark)
        rep["arms"]["export.synthesis"] = {k: {"meta": metas_e[k], **{kk: vv for kk, vv in v.items() if kk != "text"}} for k, v in arms_e.items()}
        rep["verdicts"]["export.synthesis"] = export_verdict(arms_e, metas_e)

        # ---- claims.extract (2 arms) — the most expensive HELD task; this is the arm that pays its `irreversible` debt
        arms_cl: dict[str, dict[str, Any]] = {}
        metas_cl: dict[str, dict[str, Any]] = {}
        cl_before: dict[str, Any] = {}
        cl_ids: list[str] = []
        for label, model, thinking, effort in arms_for["claims.extract"]:
            saved = _set_arm(["claims.extract"], model, thinking, effort)
            try:
                metas_cl[label] = _arm_meta(label, model, thinking, effort, ["claims.extract"])
                progress(f"[claims.extract · {label}] {model} thinking={thinking}")
                arms_cl[label] = run_claims_arm(pid, live)
            finally:
                _restore_env(saved)
            cl = arms_cl[label]
            if not cl_ids:                                        # remember arm one's INPUT so arm two starts from it
                cl_ids = [r["id"] for r in cl.get("rows") or []]
                cl_before = {"claims": {r["id"]: {"text": r["before"], "type": (r.get("type") or ["other", "other"])[0],
                                                  "topic": (r.get("topic") or [None, None])[0],
                                                  "freshness": (r.get("freshness") or ["slow_changing", "slow_changing"])[0]}
                                        for r in cl.get("rows") or []}}
            progress(f"[claims.extract · {label}] cohort {cl['cohort']} · normalized {cl['normalized']} · qualifiers {cl['qualifier_rate']:.0%} · "
                     f"hedges kept {cl['hedge_rate']:.0%} · over-generalized {cl['n_over_generalized']} · merges {cl['merged']} · "
                     f"${cl['usage']['cost']:.4f} · {cl['seconds']}s · returned {cl['invocations'].get('returned_model')}")
            save(f"claims.extract-{label}.json", {k: v for k, v in cl.items() if not k.startswith("_")})
            _reset_normalization(pid, cl_ids, cl_before)
            _restore_state(pid, mark)
        rep["arms"]["claims.extract"] = {k: {"meta": metas_cl[k], **{kk: vv for kk, vv in v.items() if kk not in ("rows", "_before")}}
                                         for k, v in arms_cl.items()}
        rep["verdicts"]["claims.extract"] = claims_verdict(arms_cl, metas_cl)

        # ---- answer.chat + answer.repair (2 arms)
        arms_c: dict[str, dict[str, Any]] = {}
        metas_c: dict[str, dict[str, Any]] = {}
        for label, model, thinking, effort in arms_for["answer.chat"]:
            saved = _set_arm(["answer.chat", "answer.repair"], model, thinking, effort)
            try:
                metas_c[label] = _arm_meta(label, model, thinking, effort, ["answer.chat", "answer.repair"])
                progress(f"[answer.chat · {label}] {model} thinking={thinking}")
                arms_c[label] = run_chat_arm(pid, ids, man, live, progress)
            finally:
                _restore_env(saved)
            c = arms_c[label]
            progress(f"[answer.chat · {label}] citation validity {c['citation_validity']} · expected source {c['answers_cite_expected_source']} · contradictions {c['contradiction_surfaced']} · gaps {c['gap_detection']} · "
                     f"repairs {c['repair_rounds']} · truncated {c['truncated_answers']} · ${c['usage']['cost']:.4f} · {c['s_per_answer']}s/answer · returned {c['invocations'].get('returned_model')}")
            save(f"answer.chat-{label}.json", c)
            _restore_state(pid, mark)
        rep["arms"]["answer.chat"] = {k: {"meta": metas_c[k], **{kk: vv for kk, vv in v.items() if kk != "per_question"}} for k, v in arms_c.items()}
        rep["verdicts"]["answer.chat"], rep["verdicts"]["answer.repair"] = chat_verdict(arms_c, metas_c)

    except Exception as e:  # noqa: BLE001
        stage_error = {"error": str(e)[:600], "type": type(e).__name__}
        rep["stage_error"] = stage_error
        log.exception("migration-compare stage failed; writing the partial report")
    rep["total_cost"] = _usage_since(t_all, ("answer", "plan", "synthesis", "findings", "embed"))["cost"]
    rep["total_s"] = round(time.time() - t_all, 2)
    rep["summary"] = {t: v["verdict"] for t, v in rep["verdicts"].items()}
    rep["rows"] = comparison_rows(rep)
    rep["files"] += [str(d / "comparison.json"), str(d / "comparison.txt")]
    text = format_migration(rep)
    (d / "comparison.json").write_text(json.dumps(rep, indent=1, default=str))
    (d / "comparison.txt").write_text(text)
    rep["text"] = text
    rep["project_id"] = pid
    if stage_error:
        raise RuntimeError(f"{stage_error['type']}: {stage_error['error']}\n"
                           f"The arms that finished before this are measured and saved: {d / 'comparison.txt'}")
    return rep


# ------------------------------------------------------------------ side-by-side + report

def comparison_rows(rep: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}

    def row(rows: list, metric: str, vals: dict[str, Any]) -> None:
        rows.append({"metric": metric, **vals})
    p = rep["arms"].get("planner", {})
    for t in ("planner.analysis", "planner.build"):
        rows: list[dict[str, Any]] = []
        arms = {k: v["tasks"][t] for k, v in p.items()}
        for m in ("rubric.score", "rubric.structure.score", "grounding.fraction", "evidence_refs", "dangling_after_removal", "json_repaired", "truncated", "parse_failed",
                  "thinking_tokens_est", "output_chars", "input_tokens", "cache_read", "output_tokens", "cost", "seconds"):
            vals = {}
            for k, v in arms.items():
                x: Any = v
                for seg in m.split("."):
                    x = x.get(seg) if isinstance(x, dict) else None
                vals[k] = x
            row(rows, m, vals)
        row(rows, "rubric.by_kind", {k: v["rubric"]["by_kind"] for k, v in arms.items()})
        row(rows, "rubric.failed", {k: ", ".join(v["rubric"]["failed"]) or "—" for k, v in arms.items()})
        row(rows, "structure.failed", {k: "; ".join(v["rubric"]["structure"]["failed"]) or "—" for k, v in arms.items()})
        row(rows, "returned_model", {k: v["invocations"].get("returned_model") for k, v in arms.items()})
        row(rows, "outcome_unknown", {k: v["invocations"].get("outcome_unknown") for k, v in arms.items()})
        if t == "planner.build":
            row(rows, "plan_evidence_dangling_raw (both passes)", {k: v["plan_evidence_dangling_raw"] for k, v in p.items()})
        out[t] = rows
    for t, keys in (("planner.update", ("n_updates", "addresses_new_finding", "addresses_new_fact", "well_formed", "json_repaired", "truncated", "parse_failed", "input_tokens", "output_tokens", "cost", "seconds")),
                    ("export.synthesis", ("words", "sections_present", "sections_missing", "citation_links", "given_links", "link_coverage", "n_invented_links", "truncated", "empty", "seconds")),
                    ("answer.chat", ("answers", "failed_answers", "citation_validity", "answers_cite_expected_source", "contradiction_surfaced", "gap_detection", "offtopic_handled",
                                     "repair_rounds", "repairs_succeeded", "answers_with_unrepaired_invalid_citations", "truncated_answers", "tool_rounds", "tool_calls", "mean_answer_chars", "s_per_answer", "seconds"))):
        arms = rep["arms"].get(t, {})
        rows = []
        for m in keys:
            row(rows, m, {k: ((", ".join(v[m]) or "—") if isinstance(v.get(m), list) else v.get(m)) for k, v in arms.items()})
        for m in ("calls", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost"):
            row(rows, "billed_" + m, {k: v["usage"][m] for k, v in arms.items()})
        row(rows, "returned_model", {k: v["invocations"].get("returned_model") for k, v in arms.items()})
        row(rows, "outcome_unknown", {k: v["invocations"].get("outcome_unknown") for k, v in arms.items()})
        if t == "answer.chat":
            row(rows, "repair.returned_model", {k: v["repair_invocations"].get("returned_model") for k, v in arms.items()})
        out[t] = rows
    return out


def format_migration(rep: dict[str, Any]) -> str:
    f = lambda v: "—" if v is None else (v if isinstance(v, str) else f"{v:,}" if isinstance(v, int) else f"{v:.4f}".rstrip("0").rstrip("."))  # noqa: E731
    lines = [f"Neuro Search Sonnet 4.6 → Sonnet 5 migration comparison · {rep['tier']} · app {rep['app_version']} @ {rep['git_sha']} · rubric v{rep.get('rubric_version')}",
             f"  shared inputs: {rep['shared_inputs']['sources']} golden sources, {rep['shared_inputs']['approved_findings']} approved findings (findings on {rep['shared_inputs']['findings_contract']['model']}); identical for every arm",
             f"  expected spend ≈ ${rep['spend_estimate']['estimate']:.2f} (max ≈ ${rep['spend_estimate']['maximum']:.2f}) · actual ${rep.get('total_cost', 0):.4f} · {rep.get('total_s')}s",
             f"  excluded: " + "; ".join(f"{k} ({v})" for k, v in rep["excluded"].items()), ""]
    for t, rows in rep["rows"].items():
        arms = list(rows[0].keys())[1:] if rows else []
        lines.append(f"== {t}")
        lines.append("  " + f"{'metric':44s}" + "".join(f"{a:>22s}" for a in arms))
        for r in rows:
            vals = [r[a] for a in arms]
            if any(isinstance(v, dict) for v in vals):
                for a in arms:
                    lines.append(f"  {r['metric'] + ' [' + a + ']':44s} " + ", ".join(f"{k} {v}" for k, v in (r[a] or {}).items()))
                continue
            if any(isinstance(v, str) and len(v) > 20 for v in vals):
                for a in arms:
                    lines.append(f"  {r['metric'] + ' [' + a + ']':44s} {str(r[a])[:140]}")
                continue
            lines.append("  " + f"{r['metric']:44s}" + "".join(f"{f(r[a]):>22s}" for a in arms))
        v = rep["verdicts"].get(t)
        if v:
            lines.append("  VERDICT: " + v["headline"])
            for x in v["fails"]:
                lines.append("    FAIL    " + x)
            for x in v["caveats"]:
                lines.append("    caveat  " + x)
            for x in v["notes"]:
                lines.append("    note    " + x)
            if v.get("adaptive") and v["adaptive"].get("reason") != "no adaptive arm":
                lines.append(f"    adaptive/medium {'RECOMMENDED' if v['adaptive']['recommended'] else 'not recommended'}: {v['adaptive']['reason']}")
        lines.append("")
    rv = rep["verdicts"].get("answer.repair")
    if rv:
        lines.append("== answer.repair")
        lines.append("  VERDICT: " + rv["headline"])
        for x in rv["fails"]:
            lines.append("    FAIL    " + x)
        for x in rv["caveats"]:
            lines.append("    caveat  " + x)
        for x in rv["notes"]:
            lines.append("    note    " + x)
        lines.append("")
    lines.append("RECOMMENDATIONS (nothing was changed; production contracts stay as they are until you migrate them)")
    for t, v in rep["verdicts"].items():
        rs = v.get("recommended_setting")
        setting = f" → {rs['model']} thinking={rs['thinking']}{'/' + rs['effort'] if rs.get('effort') else ''}" if rs else ""
        lines.append(f"  {v['verdict']:17s} {t:18s}{setting}")
    lines.append("  stay on 4.6       discover.quick, discover.verify (excluded from this migration)")
    lines.append("  (billing categories differ between arms by design: each model has its own prompt cache, so cache read/write splits are not comparable; canonical token deltas were measured in E2.1/E2.2)")
    lines.append("")
    lines.append("  files: " + ", ".join(rep["files"]))
    return "\n".join(lines)
