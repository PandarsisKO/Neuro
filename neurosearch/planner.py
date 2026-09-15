"""Master Planner: turn a project's accumulated research into an actionable, evidence-grounded plan.

Research mode answers "what do we need to know?"; Plan mode answers "given everything we know, how should we
accomplish this?". The plan is a structured JSON document (rendered to Markdown/HTML for sharing) whose items
carry statuses, evidence references, a basis (research / user / planner / estimate) and confidence.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from . import db
from .config import settings
from .search import search

log = logging.getLogger(__name__)

ANALYSIS_SCHEMA = """{
 "situation": str,                       // 3-5 sentences: where this person stands today, in plain words
 "swot": {"strengths": [{"point": str, "so_what": str}], "weaknesses": [{"point": str, "so_what": str}],
          "opportunities": [{"point": str, "so_what": str, "evidence": [id]}], "threats": [{"point": str, "so_what": str, "evidence": [id]}]},
 "readiness": [{"area": str, "level": "ready|partly|gap", "note": str}],      // money, time, skills, network, mindset, legal/admin…
 "options": [{"path": str, "summary": str, "cost": str, "time_to_result": str, "risk": "low|medium|high",
              "fit": 1-5, "why_fit": str, "evidence": [id]}],                     // 2-4 realistic paths, honestly compared
 "assumptions": [{"assumption": str, "if_wrong": str, "how_to_check": str}],   // the beliefs the plan rests on
 "failure_patterns": [{"pattern": str, "seen_in": str, "avoid": str, "evidence": [id]}],   // why people fail at this, per the sources
 "verdict": str                          // 2-3 sentences: the honest take on whether/how to proceed
}"""

PLAN_SCHEMA = """{
 "goal": {"outcome": str, "constraints": [str], "success": [str], "evidence": [id]},
 "approach": {"recommended": str, "why": str, "alternatives": [{"option": str, "why_not": str}],
              "basis": "research|user|planner|estimate", "confidence": "high|medium|needs_research", "evidence": [id]},
 "first_steps": [{"action": str, "detail": str, "today": bool, "evidence": [id]}],
 "phases": [{"name": str, "objective": str, "tasks": [{"task": str, "detail": str}], "dependencies": [str],
             "decisions": [str], "outcome": str}],
 "dependencies": [{"item": str, "blocking": bool, "note": str}],
 "decisions": [{"decision": str, "options": [str], "recommended": str, "why": str, "when": "now|later",
                "by_phase": str, "basis": "research|user|planner|estimate", "evidence": [id]}],
 "tools": [{"need": str, "tool": str, "free_option": str, "premium_option": str, "cost": str, "why": str,
            "tier": "required|recommended|optional", "basis": "research|user|planner|estimate", "evidence": [id]}],
 "costs": {"upfront": [{"item": str, "amount": str}], "recurring": [{"item": str, "amount": str}],
           "optional": [{"item": str, "amount": str}], "services": [{"item": str, "amount": str}],
           "contingency": str, "minimum": str, "recommended": str, "premium": str, "note": str, "evidence": [id]},
 "risks": [{"risk": str, "mitigation": str, "priority": "high|medium|low"}],
 "gotchas": [{"gotcha": str, "avoid": str}],
 "defer": [{"item": str, "until": str}],
 "open_questions": [{"question": str, "category": "blocking|soon|nice", "why": str, "research_prompt": str}],
 "confidence": [{"area": str, "level": "high|medium|needs_research", "note": str}],
 "ready": {"first_three": [str], "initial_cost": str, "need_before": [str], "blockers": [str]},
 "this_week": [{"action": str, "why": str, "time": str}],          // 3-5 concrete things to do in the next 7 days, each doable in a sitting
 "refine_questions": [{"question": str, "why": str, "kind": "fact|decision|preference",
                       "options": [str]}]                           // 4-7 questions whose ANSWERS would most change/improve this plan; options optional
}"""

SYSTEM = """You are Master Planner, an experienced project lead. You turn a project's research into a realistic plan for
actually accomplishing it. The reader should finish the plan thinking: "I understand the path, I know what matters,
I know what I can ignore for now, I know my first steps, I can start."

You reason ACROSS the research and turn it into a sequence of decisions and actions. You do not summarise it.

Behaviour:
- Make recommendations, prioritise, sequence work, identify dependencies, simplify, explain trade-offs, expose
  uncertainty honestly, flag risks that matter (likelihood x impact, and only ones the user can act on), remember
  decisions already made, recognise what can wait, and make the first actions obvious and doable today.
- Do NOT: produce generic checklists, list every conceivable risk, re-ask questions the research already answers,
  force irrelevant decisions before starting, treat every uncertainty as a blocker, recommend unnecessary software,
  or bury the first steps under analysis. Prefer tools the user already has.
- Be concrete. "Export the existing Squarespace site and save a complete local backup before changing DNS" beats
  "Start planning the migration."
- Beginner gotchas: things a first-timer would not realise (hidden costs, irreversible actions, sequencing traps,
  account ownership, lock-in, underestimated timelines) — a few that matter, each with how to avoid it.
- Grounding: attach evidence ids from the EVIDENCE list to items they rely on, and set "basis":
  research (from the sources/findings), user (a stated requirement/decision/constraint), planner (your judgement),
  estimate (a number or assumption). Never invent sources, prices or facts; when a price is unknown give a range and
  call it an estimate.
- Confidence: high = supported by several sources or confirmed project facts; medium = reasonable but depends on an
  unresolved variable; needs_research = important information is missing.
- Open questions: only ones that could materially change the plan. Categorise blocking / soon / nice and write a
  research_prompt the user can run as-is.
- Phases must fit THIS project; do not force a template. Keep the whole plan tight — clarity over volume.
- this_week: the plan must end in motion — 3-5 concrete actions for the next seven days, each finishable in one
  sitting, phrased as an instruction ("Call two SBA lenders and ask X"), with why it matters and a time estimate.
- refine_questions: the plan is a draft that improves with answers. Ask the 4-7 questions whose answers would most
  change it — facts only the user knows (cash available, hours per week, location, skills), decisions they must make,
  preferences that steer the approach. Say why each matters. Offer 2-4 options when the answer is a choice. Never ask
  what the research or the user's brief already answers.

Output ONLY a JSON object matching this schema (omit fields you have nothing for; evidence ids come from the list):
""" + PLAN_SCHEMA


ANALYSIS_SYSTEM = """You are Master Planner's analyst. Before any plan is written, give someone who is unsure how to start an
honest, grounded read of their situation — the kind a seasoned operator would give a friend over coffee.

Do a real SWOT: strengths/weaknesses are about THIS person's situation (what they told us: money, time, skills,
assets, constraints); opportunities/threats come from the research (market, what practitioners say works, what
burns people). Every point carries a "so_what" — what it means for how they should act. Then rate readiness by
area, compare 2-4 realistic paths on cost / time-to-result / risk / fit, list the assumptions everything rests on
and how to check each cheaply, and pull out the failure patterns the sources describe. Finish with a verdict.

Be specific and cite evidence ids. Never invent facts; if the research is thin on something, say so.
Output ONLY a JSON object matching this schema:
""" + ANALYSIS_SCHEMA

MATERIAL_CHARS = 170_000        # keep the prompt comfortably inside the model's window


def research_context(project_id: str, strict: bool = False) -> dict[str, Any]:
    """The planner's complete research input, prepared ONCE: evidence list, id map, material text and a hash of the
    material. Both planners accept it (`research=`) so a comparison can freeze it before either arm runs; strict=True
    makes a retrieval failure an error instead of a silently different evidence list."""
    import hashlib
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    ev, emap = _evidence(project_id, project, strict=strict)
    material = _material(project_id, project, ev)
    return {"project_id": project_id, "evidence": ev, "emap": emap, "material": material,
            "material_hash": hashlib.sha256(material.encode()).hexdigest()[:16], "evidence_count": len(ev), "strict": strict}


def _evidence(project_id: str, project: dict[str, Any], strict: bool = False) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build the numbered evidence list handed to Claude, and a map id -> display info."""
    ev: list[dict[str, Any]] = []
    emap: dict[str, dict[str, Any]] = {}

    def add(prefix: str, label: str, text: str, link: str | None = None, kind: str = "research", source_id: str | None = None,
            note_id: int | None = None) -> str:
        eid = f"{prefix}{sum(1 for e in ev if e['id'].startswith(prefix)) + 1}"
        ev.append({"id": eid, "text": text})
        # LP0 (mission §12): record the note's real id alongside the display label, so a later reader (decision_impact,
        # plan_impact) can resolve F<n> -> note_id from the plan's own frozen emap instead of re-deriving it from the
        # CURRENT note ordering, which breaks the moment a note is added, approved, or removed after the plan is built.
        emap[eid] = {"label": label, "link": link, "kind": kind, **({"source_id": source_id} if source_id else {}),
                     **({"note_id": note_id} if note_id is not None else {})}
        return eid

    for f in db.list_facts(project_id):
        add("U", f"{f['kind']}: {f['content'][:80]}", f"[{f['kind']}] {f['content']}", kind="user")
    for n in reversed(db.list_project_notes(project_id)):
        cites = n.get("citations") or []
        first = cites[0] if cites else None
        # 2026-09-14 - the "pinned finding" fallback was a fixed string, so every uncited note rendered as an
        # identical, indistinguishable chip in the Master Plan's Evidence tab (Kyle found 16 of them on one plan,
        # all reading "F22 - pinned finding research" / "F23 - pinned finding research" / ...). Fall back to the
        # note's own content instead, same as the fact branch above (f['content'][:80]) - always distinguishing,
        # never a placeholder.
        label = (first["title"] + " @ " + first["timestamp"]) if first else n["content"][:80]
        add("F", label, n["content"][:1200], first["link"] if first else None, source_id=(first or {}).get("source_id") or n.get("source_id"),
            note_id=n["id"])
    sids = db.project_source_ids(project_id)
    analysis = db.project_analysis(project_id, "summary")         # summaries/substance are project-relative
    srcs = [s for s in db.list_sources(limit=100000) if s["id"] in set(sids)]
    srcs.sort(key=lambda s: -((analysis.get(s["id"]) or {}).get("substance") or 0))   # most substantive first; big projects get capped
    for s in srcs[:80]:
        text = (analysis.get(s["id"]) or {}).get("summary")
        if not text:
            segs = db.get_segments(s["id"])
            text = " ".join(x["text"] for x in segs[:40])[:400]
        add("S", s["title"] or s["url"], f"{s['title']} ({s.get('channel') or s['platform']}): {text}", s["url"], source_id=s["id"])
    # retrieval: chunks most relevant to the brief/context and to open questions in chats
    queries = [q for q in [project.get("brief"), project.get("goal"), project.get("context")] if q] + list(project.get("questions") or [])
    for c in db.list_conversations(project_id, limit=20):
        for m in db.get_messages(c["id"], limit=50):
            if m["role"] == "user" and len(m["content"]) < 300:
                queries.append(m["content"])
    seen: set[int] = set()
    for q in queries[:25]:
        for h in search(q, limit=6, source_ids=sids or ["__none__"], strict=strict):
            if h["chunk_id"] in seen:
                continue
            seen.add(h["chunk_id"])
            add("C", f"{h['title']} @ {h['timestamp']}", f"{h['title']} @ {h['timestamp']}: {h['text'][:900]}", h["link"], source_id=h.get("source_id"))
            if len(seen) >= 60:
                break
        if len(seen) >= 60:
            break
    return ev, emap


def _material(project_id: str, project: dict[str, Any], ev: list[dict[str, Any]]) -> str:
    parts = [f"PROJECT: {project['name']}",
             "WHAT THE USER TOLD US (goal, brief, situation, audience, desired output — treat as requirements):",
             db.project_steering(project), "", "EVIDENCE (cite these ids):"]
    parts += [f"[{e['id']}] {e['text']}" for e in ev]
    parts.append("\nRESEARCH CONVERSATIONS (Q/A, most recent last):")
    budget = max(10000, MATERIAL_CHARS - sum(len(x) for x in parts))
    for c in db.list_conversations(project_id, limit=30)[::-1]:
        for m in db.get_messages(c["id"], limit=100):
            line = f"{'Q' if m['role'] == 'user' else 'A'}: {m['content'][:1500]}"
            if budget - len(line) < 0:
                break
            parts.append(line)
            budget -= len(line)
    return "\n".join(parts)


def _repair_json(text: str) -> str:
    """Best effort for output that was cut off mid-way: drop the dangling tail and close what is open."""
    for cut in range(len(text), max(0, len(text) - 20000), -1):
        chunk = text[:cut].rstrip().rstrip(",")
        if not chunk.endswith(("}", "]", '"', "e", "l")):   # true/false/null or a closed value
            continue
        opens = []
        in_str = esc = False
        for ch in chunk:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                opens.append(ch)
            elif ch in "}]":
                if opens:
                    opens.pop()
        if in_str:
            continue
        candidate = chunk + "".join("}" if o == "{" else "]" for o in reversed(opens))
        try:
            json.loads(candidate)
            return candidate
        except ValueError:
            continue
    raise RuntimeError("planner returned JSON that could not be repaired")


_last_model: dict[str, Any] = {}          # returned model of the most recent planner pass (provenance)
OBSERVER: Any = None                 # evals hook: one dict per model call + one per JSON parse; never changes behaviour
_last_call: dict[str, Any] = {}


def _observe(**ev: Any) -> None:
    if OBSERVER:
        OBSERVER(ev)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        _observe(event="parse", task=_last_call.get("task"), ok=False, repaired=False)
        raise RuntimeError("planner returned no JSON")
    body = text[start:end + 1] if end > start else text[start:]
    try:
        out = json.loads(body)
        _observe(event="parse", task=_last_call.get("task"), ok=True, repaired=False)
        return out
    except ValueError:
        log.warning("planner: repairing malformed/truncated JSON (%d chars)", len(body))
        try:
            out = json.loads(_repair_json(text[start:]))
        except Exception:
            _observe(event="parse", task=_last_call.get("task"), ok=False, repaired=True)
            raise
        _observe(event="parse", task=_last_call.get("task"), ok=True, repaired=True)
        return out


def _call_claude(system: str, user: str, max_tokens: int = 16000, progress: Any = None, label: str = "writing",
                 shared: str | None = None) -> str:
    """Streamed so long plans are never cut off by request timeouts; reports progress as the text grows.
    `shared` (the research material) goes first as a cached system block: the analysis pass writes it to the
    prompt cache, the plan pass and any rebuild within a few minutes read it back at a tenth of the price."""
    from . import providers, usage

    usage.guard(0.5)
    sys_blocks: Any = system
    if shared:
        sys_blocks = [usage.cached_block("RESEARCH MATERIAL for the project (your instructions follow it):\n\n" + shared),
                      {"type": "text", "text": system}]
    parts: list[str] = []
    n = 0
    task = "planner.analysis" if system is ANALYSIS_SYSTEM else "planner.update" if system is UPDATE_SYSTEM else "planner.build"
    from .contracts import contract
    max_tokens = contract(task).max_output_tokens                 # the contract owns the output budget
    _last_call.clear(); _last_call["task"] = task
    import time as _time
    t0 = _time.time()
    with providers.invoke(task, system=sys_blocks, messages=[{"role": "user", "content": user}], stream=True) as stream:
        for text in stream.text_stream:
            parts.append(text)
            n += len(text)
            if progress and n % 2000 < len(text):
                progress(None, f"{label}… {n // 4:,} tokens so far")
        final = stream.get_final_message()
        _last_model["model"] = getattr(final, "model", None)
    cost = None
    try:
        cost = usage.record_anthropic(final, "plan")
    except Exception:  # noqa: BLE001
        pass
    if getattr(final, "stop_reason", None) == "max_tokens":
        log.warning("planner: output hit max_tokens (%d) — will repair", max_tokens)
    u = getattr(final, "usage", None)
    _observe(event="call", task=task, stop_reason=getattr(final, "stop_reason", None), truncated=getattr(final, "stop_reason", None) == "max_tokens",
             model=getattr(final, "model", None), chars=n, seconds=round(_time.time() - t0, 2), cost=cost,
             input_tokens=int(getattr(u, "input_tokens", 0) or 0), output_tokens=int(getattr(u, "output_tokens", 0) or 0),
             cache_read=int(getattr(u, "cache_read_input_tokens", 0) or 0), cache_write=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
             thinking_blocks=sum(1 for b in (getattr(final, "content", None) or []) if getattr(b, "type", None) == "thinking"))
    return "".join(parts)


def build_plan(project_id: str, instructions: str | None = None, progress: Any = None, research: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate (or regenerate) the Master Plan for a project in two passes — situation analysis (SWOT,
    readiness, options, assumptions, failure patterns) and then the plan itself. Returns the stored plan row.
    With NEUROSEARCH_PLANNER_V3=1 the decomposed planner (planner_v3) runs instead; this single-call path is the
    rollback for one release."""
    if settings.planner_v3:
        from .planner_v3 import build_plan_v3
        return build_plan_v3(project_id, instructions, progress, research=research)
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    if progress:
        progress(0.05, "gathering the research…")
    research = research or research_context(project_id)            # a frozen payload, or prepared now
    ev, emap, material = research["evidence"], research["emap"], research["material"]
    prev = db.latest_plan(project_id)

    # ---- pass 1: situation analysis ----
    if progress:
        progress(0.15, "analysing the situation (SWOT, readiness, options)…")
    analysis: dict[str, Any] = {}
    try:
        a_user = ("INSTRUCTIONS FROM THE USER:\n" + instructions + "\n\n" if instructions else "") + "Using the research material above, write the situation analysis JSON now."
        analysis = _parse_json(_call_claude(ANALYSIS_SYSTEM, a_user, max_tokens=7000, progress=progress, label="analysing", shared=material))
    except Exception as e:  # noqa: BLE001
        log.warning("planner: analysis pass failed, continuing without it: %s", e)

    # ---- pass 2: the plan, informed by the analysis ----
    if progress:
        progress(0.5, "writing the plan…")
    user = "Build the plan from the research material above."
    if analysis:
        user += "\n\nSITUATION ANALYSIS (yours, from a first pass — build the plan on it, especially the recommended option, assumptions and failure patterns):\n" + json.dumps(analysis)[:20000]
    if prev:
        user += "\n\nPREVIOUS PLAN (keep what still holds; change only what the research or instructions justify):\n" + json.dumps({k: v for k, v in prev["plan"].items() if not k.startswith("_") and k != "analysis"})[:20000]
    if instructions:
        user += "\n\nINSTRUCTIONS FOR THIS REVISION:\n" + instructions
    user += "\n\nWrite the Master Plan JSON now. Keep it tight: the whole document under ~5000 words."
    plan = _parse_json(_call_claude(SYSTEM, user, progress=progress, label="writing the plan", shared=material))
    if analysis:
        plan["analysis"] = analysis
    if progress:
        progress(0.95, "saving…")
    plan["_evidence"] = emap
    plan["_generated"] = date.today().isoformat()
    plan["_research_hash"] = research["material_hash"]
    from .evidence import check_plan_evidence, drop_evidence_ids
    n_refs, dangling = check_plan_evidence(plan, set(emap))
    if dangling:
        # evidence references are optional decoration on a plan item; an unknown id is removed rather than stored,
        # so a plan never becomes current while pointing at evidence that does not exist
        log.warning("plan references evidence ids that do not exist — removed: %s", dangling[:10])
        drop_evidence_ids(plan, set(dangling))
        db.validation_event("plan_evidence_removed", {"removed": dangling, "references": n_refs}, project_id=project_id)
    plan["_evidence_check"] = {"references": n_refs, "dangling": dangling, "removed": bool(dangling)}
    db.kv_bump("evidence:plan_refs_checked", n_refs)
    db.kv_bump("evidence:plan_refs_dangling", len(dangling))
    snapshot = db.project_snapshot(project_id)
    import hashlib
    from . import providers
    row = db.save_plan(project_id, plan, snapshot, carry_statuses_from=prev["id"] if prev else None,
                       provenance={"model": _last_model.get("model") or settings.answer_model, "prompt_version": "plan-" + hashlib.sha1((ANALYSIS_SYSTEM + SYSTEM).encode()).hexdigest()[:8],
                                   "routing": providers.routing_json("planner.build", _last_model.get("model"))})
    db.update_project(project_id, mode="plan")
    return row


UPDATE_SYSTEM = """You are Master Planner reviewing whether NEW research changes an existing plan. Compare the new material
against the plan and list only changes that matter (a changed recommendation, a resolved open question, a new
blocking dependency, a materially different cost or risk). Do not rewrite for style. Output ONLY JSON:
{"updates": [{"section": str, "previous": str, "proposed": str, "reason": str}]}
Return {"updates": []} if nothing material changed."""


def suggest_updates(project_id: str) -> list[dict[str, Any]]:
    plan = db.latest_plan(project_id)
    if not plan:
        return []
    since = plan["created_at"]
    conn = db.connect()
    new_notes = [dict(r) for r in conn.execute("SELECT content FROM project_notes WHERE project_id=? AND created_at>? AND status<>'reserve'", (project_id, since)).fetchall()]
    new_facts = [dict(r) for r in conn.execute("SELECT kind, content FROM project_facts WHERE project_id=? AND created_at>?", (project_id, since)).fetchall()]
    new_msgs = [dict(r) for r in conn.execute(
        """SELECT m.role, m.content FROM messages m JOIN conversations c ON c.id=m.conversation_id
           WHERE c.project_id=? AND m.created_at>? ORDER BY m.id""", (project_id, since)).fetchall()]
    sids = set(db.project_source_ids(project_id))
    new_srcs = [s for s in db.list_sources(limit=100000) if s["id"] in sids and s["created_at"] > since]
    if not (new_notes or new_facts or new_msgs or new_srcs):
        db.add_plan_updates(plan["id"], [])
        return []
    material = ["NEW FINDINGS:"] + [f"- {n['content'][:1000]}" for n in new_notes]
    material += ["NEW USER FACTS:"] + [f"- [{f['kind']}] {f['content']}" for f in new_facts]
    material += ["NEW SOURCES:"] + [f"- {s['title']}: " + " ".join(x['text'] for x in db.get_segments(s['id'])[:30])[:600] for s in new_srcs]
    material += ["NEW CONVERSATION:"] + [f"{'Q' if m['role'] == 'user' else 'A'}: {m['content'][:1200]}" for m in new_msgs[-40:]]
    plan_json = {k: v for k, v in plan["plan"].items() if not k.startswith("_")}
    user = "CURRENT PLAN:\n" + json.dumps(plan_json)[:30000] + "\n\n" + "\n".join(material)[:40000] + "\n\nList the suggested updates now."
    from . import providers, usage
    from .contracts import contract
    if contract("planner.update").schema:
        # Mission F (F3): schema-enforced, fully validated. A model output we cannot understand is a typed failure that
        # propagates to the caller — it is never turned into an innocent "no updates".
        import time as _time
        t0 = _time.time()
        _last_call.clear(); _last_call["task"] = "planner.update"
        data = providers.invoke_structured("planner.update", system=UPDATE_SYSTEM, messages=[{"role": "user", "content": user}], usage_kind="plan",
                                           project_id=project_id, guard_estimate=0.1, legacy=_legacy_update_parse)
        resp = providers.last_response()
        u = getattr(resp, "usage", None)
        _observe(event="call", task="planner.update", stop_reason=getattr(resp, "stop_reason", None), truncated=False, model=getattr(resp, "model", None),
                 chars=len(json.dumps(data)), seconds=round(_time.time() - t0, 2), cost=None, input_tokens=int(getattr(u, "input_tokens", 0) or 0),
                 output_tokens=int(getattr(u, "output_tokens", 0) or 0), cache_read=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                 cache_write=int(getattr(u, "cache_creation_input_tokens", 0) or 0), thinking_blocks=0)
        updates = data["updates"]
        _observe(event="parse", task="planner.update", ok=True, repaired=False, raw_updates=len(updates))
    else:
        # legacy/unstructured contract (NEUROSEARCH_TASK_SCHEMA_PLANNER_UPDATE=none): a parse failure is STILL an error now
        raw = _call_claude(UPDATE_SYSTEM, user, max_tokens=4000)
        try:
            updates = _legacy_update_parse(raw)["updates"]
            _observe(event="parse", task="planner.update", ok=True, repaired=True, raw_updates=len(updates))
        except Exception as exc:
            _observe(event="parse", task="planner.update", ok=False, repaired=False, error=str(exc)[:200])
            raise RuntimeError(f"planner.update: could not understand the model's output ({exc}); no updates were recorded") from exc
    updates = [u for u in updates if isinstance(u, dict) and u.get("proposed")]
    db.add_plan_updates(plan["id"], updates)
    return updates


def _legacy_update_parse(raw: str) -> dict[str, Any]:
    """Pre-F tolerant parser (fences, list or {"updates": [...]}) — only for unstructured contracts or the compat hatch."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    s_obj, s_list = text.find("{"), text.find("[")
    if s_obj >= 0 and (s_list < 0 or s_obj < s_list):
        obj = json.loads(text[s_obj:text.rfind("}") + 1])
        if isinstance(obj, dict) and isinstance(obj.get("updates"), list):
            return obj
        raise ValueError("no updates list")
    if s_list >= 0:
        return {"updates": json.loads(text[s_list:text.rfind("]") + 1])}
    raise ValueError("no JSON in output")


def apply_accepted_updates(project_id: str) -> dict[str, Any]:
    """Regenerate the plan folding in every accepted (and rejecting pending-but-rejected) update."""
    plan = db.latest_plan(project_id)
    if not plan:
        raise RuntimeError("no plan yet")
    accepted = [u for u in plan["updates"] if u["status"] == "accepted"]
    rejected = [u for u in plan["updates"] if u["status"] == "rejected"]
    instr = []
    if accepted:
        instr.append("APPLY these changes:\n" + "\n".join(f"- {u['section']}: {u['proposed']} (reason: {u.get('reason') or ''})" for u in accepted))
    if rejected:
        instr.append("The user chose to KEEP the current plan for these (do not change them):\n" + "\n".join(f"- {u['section']}: keep '{u.get('previous') or ''}'" for u in rejected))
    instr.append("Keep everything else the same unless the applied changes require adjustments.")
    return build_plan(project_id, "\n\n".join(instr))


def research_changed(project_id: str) -> bool:
    plan = db.latest_plan(project_id)
    if not plan:
        return False
    return db.project_snapshot(project_id) != plan.get("snapshot")


# ------------------------------------------------------------- rendering

def _ev_links(ids: list[str] | None, emap: dict[str, Any]) -> str:
    if not ids:
        return ""
    out = []
    for i in ids:
        e = emap.get(i)
        if not e:
            continue
        link = e.get("link") or ""
        out.append(f"[{e['label']}]({link})" if link.startswith("http") else e["label"])
    return (" _(based on: " + "; ".join(out) + ")_") if out else ""


def plan_markdown(plan_row: dict[str, Any], project: dict[str, Any]) -> str:
    p = plan_row["plan"]
    emap = p.get("_evidence", {})
    items = plan_row.get("items", {})
    L = _ev_links

    def st(key: str) -> str:
        s = items.get(key, {}).get("status")
        return f" `{s.replace('_', ' ')}`" if s and s != "not_started" else ""

    out = [f"# {project['name']} — Master Plan", f"_Version {plan_row['version']} · generated {p.get('_generated', '')} · status: {plan_row['status']}_", ""]
    an = p.get("analysis") or {}
    if an:
        out += ["## 0. Where you stand — situation analysis", an.get("situation", ""), ""]
        sw = an.get("swot") or {}
        if sw:
            out += ["| Strengths | Weaknesses |", "|---|---|"]
            S, W = sw.get("strengths") or [], sw.get("weaknesses") or []
            for i in range(max(len(S), len(W))):
                a_ = S[i] if i < len(S) else {}; b_ = W[i] if i < len(W) else {}
                out.append(f"| {a_.get('point', '')}{(' — _' + a_['so_what'] + '_') if a_.get('so_what') else ''} | {b_.get('point', '')}{(' — _' + b_['so_what'] + '_') if b_.get('so_what') else ''} |")
            out += ["", "| Opportunities | Threats |", "|---|---|"]
            O, T = sw.get("opportunities") or [], sw.get("threats") or []
            for i in range(max(len(O), len(T))):
                a_ = O[i] if i < len(O) else {}; b_ = T[i] if i < len(T) else {}
                out.append(f"| {a_.get('point', '')}{(' — _' + a_['so_what'] + '_') if a_.get('so_what') else ''}{L(a_.get('evidence'), emap)} | {b_.get('point', '')}{(' — _' + b_['so_what'] + '_') if b_.get('so_what') else ''}{L(b_.get('evidence'), emap)} |")
            out.append("")
        if an.get("readiness"):
            out += ["**Readiness:**"] + [f"- {r.get('area')}: `{r.get('level', '')}` — {r.get('note', '')}" for r in an["readiness"]] + [""]
        if an.get("options"):
            out += ["**Paths compared:**", "| Path | Cost | Time to result | Risk | Fit | Why |", "|---|---|---|---|---|---|"]
            out += [f"| **{o.get('path')}** — {o.get('summary', '')} | {o.get('cost', '')} | {o.get('time_to_result', '')} | {o.get('risk', '')} | {'★' * int(o.get('fit') or 0)} | {o.get('why_fit', '')}{L(o.get('evidence'), emap)} |" for o in an["options"]]
            out.append("")
        if an.get("assumptions"):
            out += ["**Assumptions this plan rests on:**"] + [f"- **{x.get('assumption')}** — if wrong: {x.get('if_wrong', '')} · check: {x.get('how_to_check', '')}" for x in an["assumptions"]] + [""]
        if an.get("failure_patterns"):
            out += ["**Why people fail at this (per the sources):**"] + [f"- **{x.get('pattern')}** — {x.get('avoid', '')}{(' _(' + x['seen_in'] + ')_') if x.get('seen_in') else ''}{L(x.get('evidence'), emap)}" for x in an["failure_patterns"]] + [""]
        if an.get("verdict"):
            out += [f"**Verdict:** {an['verdict']}", ""]
    g = p.get("goal") or {}
    out += ["## 1. Goal", g.get("outcome", ""), ""]
    if g.get("constraints"):
        out += ["**Constraints:** " + "; ".join(g["constraints"]), ""]
    if g.get("success"):
        out += ["**Success looks like:** " + "; ".join(g["success"]), ""]
    a = p.get("approach") or {}
    out += ["## 2. Recommended approach", f"**{a.get('recommended', '')}**" + L(a.get("evidence"), emap), "",
            a.get("why", ""), ""]
    if a.get("alternatives"):
        out.append("Alternatives considered:")
        out += [f"- **{x.get('option')}** — {x.get('why_not')}" for x in a["alternatives"]]
        out.append("")
    out.append(f"_Basis: {a.get('basis', 'planner')} · confidence: {a.get('confidence', 'medium')}_\n")
    out.append("## 3. First steps")
    for i, s in enumerate(p.get("first_steps") or []):
        out.append(f"{i + 1}. **{s.get('action')}**{' _(today)_' if s.get('today') else ''}{st(f'first_steps.{i}')} — {s.get('detail', '')}{L(s.get('evidence'), emap)}")
    out.append("")
    if p.get("phases"):
        out.append("## 4. Phases")
        for i, ph in enumerate(p["phases"]):
            out += [f"### Phase {i + 1} — {ph.get('name')}", f"_Objective:_ {ph.get('objective', '')}"]
            for j, t in enumerate(ph.get("tasks") or []):
                out.append(f"- [{'x' if items.get(f'phases.{i}.tasks.{j}', {}).get('status') == 'complete' else ' '}] {t.get('task')}{st(f'phases.{i}.tasks.{j}')}" + (f" — {t.get('detail')}" if t.get("detail") else ""))
            if ph.get("dependencies"):
                out.append("_Depends on:_ " + "; ".join(ph["dependencies"]))
            if ph.get("decisions"):
                out.append("_Decisions needed:_ " + "; ".join(ph["decisions"]))
            if ph.get("outcome"):
                out.append(f"_Outcome:_ {ph['outcome']}")
            out.append("")
    if p.get("dependencies"):
        out.append("## 5. Dependencies")
        for d in p["dependencies"]:
            out.append(f"- {'**Blocking:** ' if d.get('blocking') else 'Non-blocking: '}{d.get('item')}" + (f" — {d.get('note')}" if d.get("note") else ""))
        out.append("")
    if p.get("decisions"):
        out.append("## 6. Decisions to make")
        for i, d in enumerate(p["decisions"]):
            out += [f"### {'Decide now' if d.get('when') == 'now' else 'Decide later'} — {d.get('decision')}{st(f'decisions.{i}')}",
                    "Options: " + "; ".join(d.get("options") or []),
                    f"**Recommended:** {d.get('recommended', '')} — {d.get('why', '')}{L(d.get('evidence'), emap)}"]
            if d.get("by_phase"):
                out.append(f"_Needed by:_ {d['by_phase']}")
            out.append("")
    if p.get("tools"):
        out += ["## 7. Tools & services", "| Need | Tool | Free option | Premium option | Approx. cost | Tier | Why |", "|---|---|---|---|---|---|---|"]
        for t in p["tools"]:
            out.append("| " + " | ".join(str(t.get(k) or "—").replace("|", "/") for k in ("need", "tool", "free_option", "premium_option", "cost", "tier", "why")) + " |")
        out.append("")
    c = p.get("costs") or {}
    if c:
        out.append("## 8. Costs")
        for k, label in (("upfront", "Upfront"), ("recurring", "Recurring"), ("optional", "Optional upgrades"), ("services", "Professional services")):
            if c.get(k):
                out.append(f"**{label}:** " + "; ".join(f"{x.get('item')} ({x.get('amount')})" for x in c[k]))
        if c.get("contingency"):
            out.append(f"**Contingency:** {c['contingency']}")
        out.append("")
        out += [f"- Minimum viable budget: **{c.get('minimum', '?')}**", f"- Recommended budget: **{c.get('recommended', '?')}**",
                f"- Premium implementation: **{c.get('premium', '?')}**"]
        if c.get("note"):
            out.append(f"\n_{c['note']}_")
        out.append(L(c.get("evidence"), emap) + "\n")
    if p.get("risks"):
        out.append("## 9. Risks")
        for r in sorted(p["risks"], key=lambda r: {"high": 0, "medium": 1, "low": 2}.get(r.get("priority", "medium"), 1)):
            out += [f"- **{r.get('risk')}** _({r.get('priority', 'medium')})_", f"  Mitigation: {r.get('mitigation')}"]
        out.append("")
    if p.get("gotchas"):
        out.append("## 10. Beginner gotchas")
        out += [f"- **{g.get('gotcha')}** — {g.get('avoid')}" for g in p["gotchas"]]
        out.append("")
    if p.get("defer"):
        out.append("## 11. What we don't need to worry about yet")
        out += [f"- {d.get('item')} — _{d.get('until')}_" for d in p["defer"]]
        out.append("")
    if p.get("open_questions"):
        out.append("## 12. Open questions")
        for cat, label in (("blocking", "Blocking"), ("soon", "Important soon"), ("nice", "Nice to know")):
            qs = [(i, q) for i, q in enumerate(p["open_questions"]) if q.get("category") == cat]
            if qs:
                out.append(f"**{label}**")
                out += [f"- {q.get('question')}{st(f'open_questions.{i}')} — {q.get('why', '')}" for i, q in qs]
        out.append("")
    if p.get("this_week"):
        out.append("## This week")
        out += [f"{i + 1}. **{t.get('action')}** — {t.get('why', '')}{(' _(' + t['time'] + ')_') if t.get('time') else ''}" for i, t in enumerate(p["this_week"])]
        out.append("")
    if p.get("refine_questions"):
        out.append("## Questions that would sharpen this plan")
        out += [f"- **{q.get('question')}** — {q.get('why', '')}{(' Options: ' + ' / '.join(q['options'])) if q.get('options') else ''}" for q in p["refine_questions"]]
        out.append("")
    if p.get("confidence"):
        out.append("## Plan confidence")
        out += [f"- **{x.get('area')}**: {x.get('level', '').replace('_', ' ')} — {x.get('note', '')}" for x in p["confidence"]]
        out.append("")
    r = p.get("ready") or {}
    if r:
        out += ["## Ready to start", "**Your first three actions:**"]
        out += [f"{i + 1}. {x}" for i, x in enumerate(r.get("first_three") or [])]
        out += ["", f"**Estimated initial cost:** {r.get('initial_cost', '?')}",
                "**What you need before beginning:** " + ("; ".join(r.get("need_before") or []) or "nothing special"),
                "**Current blockers:** " + ("; ".join(r.get("blockers") or []) or "none"), ""]
    if emap:
        out.append("## Evidence")
        for eid, e in emap.items():
            kind = {"user": "user-provided", "research": "research"}.get(e.get("kind"), e.get("kind"))
            link = e.get("link") or ""
            out.append(f"- [{eid}] {e['label']}" + (f" — {link}" if link.startswith("http") else "") + f" _({kind})_")
    return "\n".join(out)


def plan_html(plan_row: dict[str, Any], project: dict[str, Any]) -> str:
    """Self-contained, printable page for sharing with the team."""
    md = plan_markdown(plan_row, project)
    body = _md_to_html(md)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h(project['name'])} — Master Plan</title>
<style>
body{{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;max-width:860px;margin:40px auto;padding:0 22px;color:#1c1e26;line-height:1.55}}
h1{{font-size:28px;margin-bottom:2px}} h2{{font-size:20px;margin-top:34px;border-bottom:1px solid #e3e5ea;padding-bottom:4px}} h3{{font-size:16px;margin-top:20px}}
code{{background:#eef0f4;padding:1px 6px;border-radius:4px;font-size:12px}} em{{color:#5b6270}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{border:1px solid #e3e5ea;padding:6px 8px;text-align:left;vertical-align:top}} th{{background:#f4f5f8}}
li{{margin:4px 0}} a{{color:#2f5bea}} .meta{{color:#5b6270;font-size:13px}}
@media print{{body{{margin:0}} a{{color:inherit;text-decoration:none}}}}
</style></head><body>{body}
<p class="meta">Exported from Neuro Search on {date.today().isoformat()}.</p></body></html>"""


def _h(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s: str) -> str:
    s = _h(s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])_([^_]+)_(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _md_to_html(md: str) -> str:
    """Small Markdown subset renderer (headings, lists, tables, paragraphs) — enough for the plan."""
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    in_ul = in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-| ]+\|$", lines[i + 1].strip()):
            close_lists()
            head = [c.strip() for c in ln.strip("|").split("|")]
            out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</table>")
            continue
        m = re.match(r"^(#{1,3}) (.*)", ln)
        if m:
            close_lists()
            out.append(f"<h{len(m.group(1))}>{_inline(m.group(2))}</h{len(m.group(1))}>")
        elif re.match(r"^\d+\. ", ln):
            if not in_ol:
                close_lists(); out.append("<ol>"); in_ol = True
            txt = re.sub(r"^\d+\. ", "", ln)
            out.append(f"<li>{_inline(txt)}</li>")
        elif ln.startswith("- "):
            if not in_ul:
                close_lists(); out.append("<ul>"); in_ul = True
            txt = ln[2:]
            txt = txt.replace("[x] ", "☑ ").replace("[ ] ", "☐ ")
            out.append(f"<li>{_inline(txt)}</li>")
        elif ln.startswith("  ") and (in_ul or in_ol):
            out[-1] = out[-1][:-5] + "<br>" + _inline(ln.strip()) + "</li>"
        elif ln.strip() == "":
            close_lists()
        else:
            close_lists()
            out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    close_lists()
    return "\n".join(out)
