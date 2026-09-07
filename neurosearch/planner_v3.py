"""Master Planner V3 (Mission F4): one frozen situation analysis, four semantic component calls, deterministic assembly.

    research material
          ↓
    planner.situation  → SituationAnalysisV3   (schema-enforced, validated, then FROZEN: analysis_hash)
          ↓
    planner.core       → goal / approach / decisions / confidence          ┐ every component receives the SAME
    planner.execution  → phases / tasks / dependencies / defer             │ frozen analysis (immutable input) and
    planner.economics  → costs / tools / risks / gotchas                   │ the id catalogue of the components
    planner.actions    → first steps / this week / open + refine questions ┘ before it (so references resolve)
          ↓
    assemble()         → the EXISTING plan document shape (same keys the UI, exports and plan_markdown read),
                         plus stable semantic ids, `_ids` (positional key → id) for state reconciliation,
                         `_build` telemetry (material tokens, cache writes/reads per component, cost) and
                         cross-component consistency checks. A plan that fails assembly is never saved:
                         the previous CURRENT plan stays, the build fails visibly (plan_assembly_failed).

All five calls share the research material as the first, cached system block; the component prompts are short so
the cached prefix does the work. Enabled by NEUROSEARCH_PLANNER_V3=1 (settings.planner_v3); the single-call planner
in planner.py is the rollback path for one release.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

PLANNER_VERSION = "v3"
STATEFUL = ("first_steps", "dependencies", "decisions", "open_questions")      # positional keys the UI uses (+ phases.i.tasks.j)
ID_SIMILARITY = 0.5                                                           # token Jaccard for id reconciliation across rebuilds

# ------------------------------------------------------------------ prompts (behaviour text shared with the V1 planner)

from .planner import ANALYSIS_SYSTEM as _V1_ANALYSIS  # noqa: E402
from .planner import SYSTEM as _V1_PLAN  # noqa: E402

_BEHAVIOUR = _V1_PLAN.split("Output ONLY a JSON object")[0].strip()
_ID_RULES = """
Ids: every object with an "id" field gets a stable semantic id of the form <kind>:<kebab-case-slug> that names the
concept, not its position — e.g. phase:financing, task:get-lender-prequalification, risk:customer-concentration,
question:working-capital-peg, decision:target-industry, dependency:equity-injection. Ids must be unique. When you
reference another object (depends_on, task, phase, option, decisions, related) use its id exactly."""

SITUATION_SYSTEM = _V1_ANALYSIS.split("Output ONLY a JSON object")[0].strip() + """
Give every option, assumption and failure pattern a stable semantic id (option:sba-7a-acquisition, assumption:dscr-floor,
failure:overpaying-on-inflated-addbacks) and name the recommended option's id in "recommended_option".
Output ONLY the JSON object the response format requires."""

CORE_SYSTEM = _BEHAVIOUR + _ID_RULES + """

THIS CALL writes only: goal, approach (which analysis option it follows, alternatives and why not), the decisions the
user must make (now vs later) and confidence by area. The SITUATION ANALYSIS you are given is fixed: build on its
recommended option, assumptions and failure patterns; do not re-analyse. Output ONLY the JSON object the response
format requires."""

EXECUTION_SYSTEM = _BEHAVIOUR + _ID_RULES + """

THIS CALL writes only the execution structure: phases that fit THIS project (2-5), each with concrete tasks (each
task with an id, optional depends_on task ids, evidence), the phase's dependencies and the decision ids it needs,
plus the top-level dependencies (blocking or not, which phase they gate) and what to defer. Sequence for the
recommended option in the fixed SITUATION ANALYSIS; the decisions you may reference are listed in the ID CATALOGUE.
Output ONLY the JSON object the response format requires."""

ECONOMICS_SYSTEM = _BEHAVIOUR + _ID_RULES + """

THIS CALL writes only money, tools and what goes wrong: costs (upfront / recurring / optional / services, each tied
to a phase id where it belongs, with minimum / recommended / premium totals and a contingency), tools (required /
recommended / optional, free vs premium, tied to a phase), risks that matter (likelihood × impact, each with a
mitigation and the task/phase ids where the mitigation lives) and beginner gotchas. Never invent prices: ranges are
estimates. Use the phase and task ids from the ID CATALOGUE; the SITUATION ANALYSIS (threats, failure patterns,
assumptions) is fixed input. Output ONLY the JSON object the response format requires."""

ACTIONS_SYSTEM = _BEHAVIOUR + _ID_RULES + """

THIS CALL writes only what happens next: first_steps (3-6, the first of which are doable today; each names the plan
task id it starts), this_week (3-5 concrete actions for the next seven days, each finishable in one sitting, phrased
as an instruction, with why and a time estimate, each naming the task id it advances), open_questions that could
materially change the plan (blocking / soon / nice, with a research_prompt the user can run as-is), refine_questions
(4-7 questions only the user can answer, with options when it is a choice) and the ready checklist (first_three as
task ids). Use the ID CATALOGUE; the SITUATION ANALYSIS is fixed input. Output ONLY the JSON object the response format requires."""

COMPONENTS: tuple[tuple[str, str, str], ...] = (
    ("planner.core", "core", CORE_SYSTEM),
    ("planner.execution", "execution", EXECUTION_SYSTEM),
    ("planner.economics", "economics", ECONOMICS_SYSTEM),
    ("planner.actions", "actions", ACTIONS_SYSTEM),
)


def prompt_version() -> str:
    return "plan3-" + hashlib.sha1((SITUATION_SYSTEM + CORE_SYSTEM + EXECUTION_SYSTEM + ECONOMICS_SYSTEM + ACTIONS_SYSTEM).encode()).hexdigest()[:8]


class PlanAssemblyError(RuntimeError):
    """Schema-valid components that do not form a coherent plan. The previous plan stays current."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("plan assembly failed: " + "; ".join(problems[:8]) + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""))
        self.problems = problems


# ------------------------------------------------------------------ ids

def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:60].rstrip("-") or "item"


def norm_id(kind: str, raw: Any, fallback_text: str = "") -> str:
    """<kind>:<slug>. Accepts 'kind:slug', 'slug', or garbage (then slugs the item text)."""
    raw = str(raw or "").strip()
    body = raw.split(":", 1)[1] if ":" in raw else raw
    body = slug(body) if body else ""
    if not body or body == "item":
        body = slug(fallback_text) or "item"
    return f"{kind}:{body}"


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 2}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


# ------------------------------------------------------------------ assembly

def _uniq(items: list[dict[str, Any]], kind: str, text_key: str, problems: list[str]) -> None:
    seen: set[str] = set()
    for it in items:
        it["id"] = norm_id(kind, it.get("id"), it.get(text_key, ""))
        base = it["id"]
        n = 2
        while it["id"] in seen:
            if n == 2:
                problems.append(f"duplicate id {base}")
            it["id"] = f"{base}-{n}"; n += 1
        seen.add(it["id"])


def assemble(analysis: dict[str, Any], core: dict[str, Any], execution: dict[str, Any], economics: dict[str, Any], actions: dict[str, Any],
             known_evidence: set[str]) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """Deterministic assembly into the existing plan shape. Returns (plan, ids_by_positional_key, problems).
    Problems are cross-component inconsistencies; the caller decides (build fails visibly when any exist)."""
    problems: list[str] = []
    core, execution, economics, actions = json.loads(json.dumps(core)), json.loads(json.dumps(execution)), json.loads(json.dumps(economics)), json.loads(json.dumps(actions))
    # ids: normalise + unique per kind
    _uniq(core.get("decisions", []), "decision", "decision", problems)
    _uniq(execution.get("phases", []), "phase", "name", problems)
    tasks_all: list[dict[str, Any]] = []
    for ph in execution.get("phases", []):
        _uniq(ph.get("tasks", []), "task", "task", problems)
        tasks_all += ph.get("tasks", [])
    seen: set[str] = set()
    for t in tasks_all:                                                     # task ids unique across phases too
        base, n = t["id"], 2
        while t["id"] in seen:
            t["id"] = f"{base}-{n}"; n += 1
        seen.add(t["id"])
    _uniq(execution.get("dependencies", []), "dependency", "item", problems)
    _uniq(economics.get("tools", []), "tool", "tool", problems)
    _uniq(economics.get("risks", []), "risk", "risk", problems)
    _uniq(economics.get("gotchas", []), "gotcha", "gotcha", problems)
    _uniq(actions.get("first_steps", []), "step", "action", problems)
    _uniq(actions.get("this_week", []), "week", "action", problems)
    _uniq(actions.get("open_questions", []), "question", "question", problems)
    _uniq(actions.get("refine_questions", []), "refine", "question", problems)
    phase_ids = {p["id"] for p in execution.get("phases", [])}
    task_ids = {t["id"] for t in tasks_all}
    decision_ids = {d["id"] for d in core.get("decisions", [])}
    option_ids = {norm_id("option", o.get("id"), o.get("path", "")) for o in analysis.get("options", [])}
    all_ids = phase_ids | task_ids | decision_ids | {d["id"] for d in execution.get("dependencies", [])} | {r["id"] for r in economics.get("risks", [])} \
        | {t["id"] for t in economics.get("tools", [])} | {g["id"] for g in economics.get("gotchas", [])} | {s["id"] for s in actions.get("first_steps", [])} \
        | {w["id"] for w in actions.get("this_week", [])} | {q["id"] for q in actions.get("open_questions", [])} | {q["id"] for q in actions.get("refine_questions", [])}
    # every id unique across kinds as well
    counts: dict[str, int] = {}
    for lst in (core.get("decisions", []), execution.get("phases", []), tasks_all, execution.get("dependencies", []), economics.get("risks", []), economics.get("tools", []),
                economics.get("gotchas", []), actions.get("first_steps", []), actions.get("this_week", []), actions.get("open_questions", []), actions.get("refine_questions", [])):
        for it in lst:
            counts[it["id"]] = counts.get(it["id"], 0) + 1
    for k, n in counts.items():
        if n > 1:
            problems.append(f"duplicate id {k}")

    # ---- cross-component references
    def ref(kind: str, value: Any, where: str, allowed: set[str], optional: bool = True) -> str:
        if not value:
            if optional:
                return ""
            problems.append(f"{where}: missing {kind} reference")
            return ""
        v = norm_id(kind, value)
        if v not in allowed:
            # tolerate a bare slug that matches an id of the right kind
            problems.append(f"{where}: {kind} {value!r} does not exist")
        return v
    opt = core.get("approach", {}).get("option")
    if opt:
        core["approach"]["option"] = ref("option", opt, "approach", option_ids)
    rec = analysis.get("recommended_option")
    if rec and norm_id("option", rec) not in option_ids:
        problems.append(f"analysis.recommended_option {rec!r} is not one of its options")
    for ph in execution.get("phases", []):
        ph["decisions"] = [ref("decision", d, f"{ph['id']}.decisions", decision_ids) for d in ph.get("decisions", []) if d]
        for t in ph.get("tasks", []):
            t["depends_on"] = [ref("task", d, f"{t['id']}.depends_on", task_ids) for d in t.get("depends_on", []) if d]
            if t["id"] in t["depends_on"]:
                problems.append(f"{t['id']} depends on itself")
    for d in execution.get("dependencies", []):
        d["phase"] = ref("phase", d.get("phase"), f"{d['id']}.phase", phase_ids)
    for c in ("upfront", "recurring", "optional", "services"):
        for cost in economics.get("costs", {}).get(c, []):
            cost["phase"] = ref("phase", cost.get("phase"), f"costs.{c}[{cost.get('item')!r}].phase", phase_ids)
    for t in economics.get("tools", []):
        t["phase"] = ref("phase", t.get("phase"), f"{t['id']}.phase", phase_ids)
    for r in economics.get("risks", []):
        rel = []
        for x in r.get("related", []):
            if not x:
                continue
            v = norm_id("task", x) if str(x).startswith("task") or norm_id("task", x) in task_ids else norm_id("phase", x)
            if v not in task_ids and v not in phase_ids:
                problems.append(f"{r['id']}.related: {x!r} is not a task or phase")
            rel.append(v)
        r["related"] = rel
    for s in actions.get("first_steps", []):
        s["task"] = ref("task", s.get("task"), f"{s['id']}.task", task_ids)
    for w in actions.get("this_week", []):
        w["task"] = ref("task", w.get("task"), f"{w['id']}.task", task_ids)
    ready = actions.get("ready", {})
    ready["first_three"] = [ref("task", x, "ready.first_three", task_ids) if norm_id("task", x) in task_ids or str(x).startswith("task:") else str(x)
                            for x in ready.get("first_three", [])]
    # this_week / first_steps must map to real plan tasks when they claim to
    if tasks_all and actions.get("this_week") and not any(w.get("task") for w in actions["this_week"]):
        problems.append("this_week: no action maps to a plan task")
    # dependency cycles among tasks
    graph = {t["id"]: set(t.get("depends_on", [])) for t in tasks_all}
    cyc = _find_cycle(graph)
    if cyc:
        problems.append("dependency cycle: " + " → ".join(cyc))
    # evidence
    from .evidence import plan_evidence_ids
    refs = plan_evidence_ids({"a": analysis, "b": core, "c": execution, "d": economics, "e": actions})
    dangling = sorted({r for r in refs if r not in known_evidence})
    if dangling:
        problems.append(f"{len(dangling)} evidence ids do not exist: {', '.join(dangling[:5])}")

    # ---- the plan document (existing shape; ids are additive fields)
    plan: dict[str, Any] = {
        "goal": core.get("goal", {}),
        "approach": core.get("approach", {}),
        "first_steps": actions.get("first_steps", []),
        "phases": execution.get("phases", []),
        "dependencies": execution.get("dependencies", []),
        "decisions": core.get("decisions", []),
        "tools": economics.get("tools", []),
        "costs": economics.get("costs", {}),
        "risks": economics.get("risks", []),
        "gotchas": economics.get("gotchas", []),
        "defer": execution.get("defer", []),
        "open_questions": actions.get("open_questions", []),
        "confidence": core.get("confidence", []),
        "ready": ready,
        "this_week": actions.get("this_week", []),
        "refine_questions": actions.get("refine_questions", []),
        "analysis": _analysis_for_ui(analysis),
    }
    for d in plan["decisions"]:
        d.setdefault("by_phase", next((ph["name"] for ph in plan["phases"] if d["id"] in ph.get("decisions", [])), ""))
    ids: dict[str, str] = {}
    for i, s in enumerate(plan["first_steps"]):
        ids[f"first_steps.{i}"] = s["id"]
    for i, ph in enumerate(plan["phases"]):
        for j, t in enumerate(ph.get("tasks", [])):
            ids[f"phases.{i}.tasks.{j}"] = t["id"]
    for i, d in enumerate(plan["dependencies"]):
        ids[f"dependencies.{i}"] = d["id"]
    for i, d in enumerate(plan["decisions"]):
        ids[f"decisions.{i}"] = d["id"]
    for i, q in enumerate(plan["open_questions"]):
        ids[f"open_questions.{i}"] = q["id"]
    return plan, ids, problems


def _analysis_for_ui(a: dict[str, Any]) -> dict[str, Any]:
    """The V3 analysis already has the keys the UI reads (situation, swot, readiness, options, assumptions, failure_patterns, verdict)."""
    out = dict(a)
    for o in out.get("options", []):
        o["id"] = norm_id("option", o.get("id"), o.get("path", ""))
    return out


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(n: str) -> list[str]:
        color[n] = GREY; stack.append(n)
        for m in graph.get(n, ()):
            if m not in graph:
                continue
            if color[m] == GREY:
                return stack[stack.index(m):] + [m]
            if color[m] == WHITE:
                r = visit(m)
                if r:
                    return r
        stack.pop(); color[n] = BLACK
        return []
    for n in graph:
        if color[n] == WHITE:
            r = visit(n)
            if r:
                return r
    return []


# ------------------------------------------------------------------ id reconciliation across rebuilds

def _stateful_items(plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out = {"step": plan.get("first_steps", []), "task": [t for ph in plan.get("phases", []) for t in ph.get("tasks", [])],
           "dependency": plan.get("dependencies", []), "decision": plan.get("decisions", []), "question": plan.get("open_questions", [])}
    return out


_TEXT_KEY = {"step": "action", "task": "task", "dependency": "item", "decision": "decision", "question": "question"}


def reconcile_ids(prev_plan: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, str]:
    """Keep ids stable across rebuilds: a new item whose id is not in the previous plan but whose text is substantively
    the same as a previous item of the same kind adopts the previous id (references are rewritten). Returns {new id → old id}."""
    if not prev_plan or not prev_plan.get("_ids"):
        return {}
    prev, cur = _stateful_items(prev_plan), _stateful_items(plan)
    renames: dict[str, str] = {}
    for kind, items in cur.items():
        old_items = prev.get(kind, [])
        old_ids = {o.get("id") for o in old_items if o.get("id")}
        taken = {it.get("id") for it in items}
        for it in items:
            if it.get("id") in old_ids:
                continue
            key = _TEXT_KEY[kind]
            best, score = None, 0.0
            for o in old_items:
                if not o.get("id") or o["id"] in taken:
                    continue
                s = similarity(f"{it.get(key, '')} {it.get('detail', '')}", f"{o.get(key, '')} {o.get('detail', '')}")
                if s > score:
                    best, score = o, s
            if best and score >= ID_SIMILARITY:
                renames[it["id"]] = best["id"]
                taken.discard(it["id"]); taken.add(best["id"])
                it["id"] = best["id"]
    if renames:
        _rewrite_refs(plan, renames)
    return renames


def _rewrite_refs(obj: Any, renames: dict[str, str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("depends_on", "related", "decisions", "first_three") and isinstance(v, list) and all(isinstance(x, str) for x in v):
                obj[k] = [renames.get(x, x) for x in v]        # id lists (plan["decisions"] is a list of dicts and is walked instead)
            elif k in ("task", "phase") and isinstance(v, str):
                obj[k] = renames.get(v, v)
            else:
                _rewrite_refs(v, renames)
    elif isinstance(obj, list):
        for x in obj:
            _rewrite_refs(x, renames)


def positional_ids(plan: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for i, s in enumerate(plan.get("first_steps", [])):
        if s.get("id"):
            ids[f"first_steps.{i}"] = s["id"]
    for i, ph in enumerate(plan.get("phases", [])):
        for j, t in enumerate(ph.get("tasks", [])):
            if t.get("id"):
                ids[f"phases.{i}.tasks.{j}"] = t["id"]
    for key in ("dependencies", "decisions", "open_questions"):
        for i, d in enumerate(plan.get(key, [])):
            if d.get("id"):
                ids[f"{key}.{i}"] = d["id"]
    return ids


# ------------------------------------------------------------------ the build

def _catalogue(core: dict[str, Any] | None, execution: dict[str, Any] | None) -> str:
    lines = []
    if core:
        lines.append("DECISIONS: " + "; ".join(f"{d['id']} — {d['decision'][:70]}" for d in core.get("decisions", [])))
    if execution:
        for ph in execution.get("phases", []):
            lines.append(f"PHASE {ph['id']} — {ph['name'][:60]}: " + "; ".join(f"{t['id']} — {t['task'][:60]}" for t in ph.get("tasks", [])))
        lines.append("DEPENDENCIES: " + "; ".join(f"{d['id']} — {d['item'][:60]}" for d in execution.get("dependencies", [])))
    return "\n".join(lines)


def _usage_of(resp: Any) -> dict[str, int]:
    u = getattr(resp, "usage", None)
    return {"input_tokens": int(getattr(u, "input_tokens", 0) or 0), "output_tokens": int(getattr(u, "output_tokens", 0) or 0),
            "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0), "cache_write": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}


def build_plan_v3(project_id: str, instructions: str | None = None, progress: Any = None, research: dict[str, Any] | None = None) -> dict[str, Any]:
    from . import planner, providers, usage
    from .contracts import contract
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    if progress:
        progress(0.05, "gathering the research…")
    research = research or planner.research_context(project_id)     # a frozen payload, or prepared now — never re-retrieved per component
    emap, material = research["emap"], research["material"]
    shared = [usage.cached_block("RESEARCH MATERIAL for the project (your instructions follow it):\n\n" + material)]
    prev = db.latest_plan(project_id)
    t_all = time.time()
    telemetry: dict[str, Any] = {"planner_version": PLANNER_VERSION, "material_chars": len(material), "material_tokens_est": len(material) // 4,
                                 "research_hash": research["material_hash"], "components": []}
    instr = ("INSTRUCTIONS FROM THE USER:\n" + instructions + "\n\n") if instructions else ""

    def call(task: str, system: str, user: str, label: str) -> dict[str, Any]:
        t0 = time.time()
        if progress:
            progress(None, f"{label}…")
        planner._last_call.clear(); planner._last_call["task"] = task
        out = providers.invoke_structured(task, system=shared + [{"type": "text", "text": system}], messages=[{"role": "user", "content": user}],
                                          usage_kind="plan", project_id=project_id, guard_estimate=0.15)
        resp = providers.last_response()
        u = _usage_of(resp)
        cost = usage.cost_of(resp)
        rec = {"task": task, "seconds": round(time.time() - t0, 2), "model": getattr(resp, "model", None), "schema": contract(task).schema, **u, "cost": cost,
               "output_chars": len(json.dumps(out)), "thinking_blocks": sum(1 for b in (getattr(resp, "content", None) or []) if getattr(b, "type", None) == "thinking")}
        telemetry["components"].append(rec)
        planner._observe(event="call", task=task, stop_reason=getattr(resp, "stop_reason", None), truncated=False, model=rec["model"], chars=rec["output_chars"],
                         seconds=rec["seconds"], cost=cost, input_tokens=u["input_tokens"], output_tokens=u["output_tokens"], cache_read=u["cache_read"],
                         cache_write=u["cache_write"], thinking_blocks=rec["thinking_blocks"])
        planner._observe(event="parse", task=task, ok=True, repaired=False)
        return out

    # ---- 1. situation analysis, then frozen
    if progress:
        progress(0.15, "analysing the situation (SWOT, readiness, options)…")
    analysis = call("planner.situation", SITUATION_SYSTEM, instr + "Using the research material above, write the situation analysis JSON now.", "analysing")
    analysis_json = json.dumps(analysis, sort_keys=True, separators=(",", ":"))
    analysis_hash = hashlib.sha256(analysis_json.encode()).hexdigest()[:16]
    frozen = "SITUATION ANALYSIS (fixed input — build on it, do not re-analyse; analysis_hash " + analysis_hash + "):\n" + analysis_json

    # ---- 2-5. components, each with the same frozen analysis + the id catalogue so far
    prev_note = ""
    if prev:
        prev_note = "\n\nPREVIOUS PLAN (keep what still holds; reuse its ids for the same concepts; change only what the research or instructions justify):\n" + \
            json.dumps({k: v for k, v in prev["plan"].items() if not k.startswith("_") and k != "analysis"})[:16000]
    core = call("planner.core", CORE_SYSTEM, instr + frozen + prev_note + "\n\nWrite the goal, approach, decisions and confidence JSON now.", "goal and approach")
    execution = call("planner.execution", EXECUTION_SYSTEM, instr + frozen + "\n\nID CATALOGUE:\n" + _catalogue(core, None) + prev_note + "\n\nWrite the phases, tasks, dependencies and defer JSON now.", "phases and dependencies")
    economics = call("planner.economics", ECONOMICS_SYSTEM, instr + frozen + "\n\nID CATALOGUE:\n" + _catalogue(core, execution) + "\n\nWrite the costs, tools, risks and gotchas JSON now.", "costs, tools and risks")
    actions = call("planner.actions", ACTIONS_SYSTEM, instr + frozen + "\n\nID CATALOGUE:\n" + _catalogue(core, execution) + "\n\nWrite the first steps, this week, open questions, refine questions and ready JSON now.", "first steps and questions")
    for rec in telemetry["components"]:
        rec["analysis_hash"] = analysis_hash if rec["task"] != "planner.situation" else None

    # ---- assembly + consistency (deterministic Python; no merge call)
    if progress:
        progress(0.9, "assembling and checking the plan…")
    plan, ids, problems = assemble(analysis, core, execution, economics, actions, set(emap))
    if problems:
        db.validation_event("plan_assembly_failed", {"problems": problems[:40], "analysis_hash": analysis_hash, "planner_version": PLANNER_VERSION}, project_id=project_id)
        db.kv_bump("evidence:plan_assembly_failed")
        log.error("planner v3: assembly failed (%d problems) — previous plan kept: %s", len(problems), problems[:5])
        raise PlanAssemblyError(problems)
    renames = reconcile_ids(prev["plan"] if prev else None, plan)
    ids = positional_ids(plan)
    n_refs, dangling = __import__("neurosearch.evidence", fromlist=["check_plan_evidence"]).check_plan_evidence(plan, set(emap))
    assert not dangling, dangling                                          # assembly already refused dangling evidence
    telemetry.update({"seconds": round(time.time() - t_all, 2), "cost_total": round(sum(c["cost"] for c in telemetry["components"]), 6), "cache_write_total": sum(c["cache_write"] for c in telemetry["components"]),
                      "cache_read_total": sum(c["cache_read"] for c in telemetry["components"]), "input_tokens_total": sum(c["input_tokens"] for c in telemetry["components"]),
                      "output_tokens_total": sum(c["output_tokens"] for c in telemetry["components"]), "analysis_hash": analysis_hash,
                      "cache_read_share": round(sum(c["cache_read"] for c in telemetry["components"]) / max(1, sum(c["cache_read"] + c["cache_write"] + c["input_tokens"] for c in telemetry["components"])), 4),
                      "id_renames_on_rebuild": renames})
    plan["_evidence"] = emap
    plan["_generated"] = date.today().isoformat()
    plan["_evidence_check"] = {"references": n_refs, "dangling": [], "removed": False}
    plan["_ids"] = ids
    plan["_build"] = telemetry
    plan["_components"] = {"situation": analysis, "core": core, "execution": execution, "economics": economics, "actions": actions}   # as generated, before assembly
    plan["_analysis_hash"] = analysis_hash
    plan["_research_hash"] = research["material_hash"]
    db.kv_bump("evidence:plan_refs_checked", n_refs)
    snapshot = db.project_snapshot(project_id)
    row = db.save_plan(project_id, plan, snapshot, carry_statuses_from=prev["id"] if prev else None,
                       provenance={"model": ", ".join(sorted({str(c["model"]) for c in telemetry["components"] if c.get("model")})), "prompt_version": prompt_version(),
                                   "analysis_hash": analysis_hash, "planner_version": PLANNER_VERSION})
    db.update_project(project_id, mode="plan")
    return row
