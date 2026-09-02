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
 "ready": {"first_three": [str], "initial_cost": str, "need_before": [str], "blockers": [str]}
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

Output ONLY a JSON object matching this schema (omit fields you have nothing for; evidence ids come from the list):
""" + PLAN_SCHEMA


def _evidence(project_id: str, project: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Build the numbered evidence list handed to Claude, and a map id -> display info."""
    ev: list[dict[str, Any]] = []
    emap: dict[str, dict[str, Any]] = {}

    def add(prefix: str, label: str, text: str, link: str | None = None, kind: str = "research") -> str:
        eid = f"{prefix}{sum(1 for e in ev if e['id'].startswith(prefix)) + 1}"
        ev.append({"id": eid, "text": text})
        emap[eid] = {"label": label, "link": link, "kind": kind}
        return eid

    for f in db.list_facts(project_id):
        add("U", f"{f['kind']}: {f['content'][:80]}", f"[{f['kind']}] {f['content']}", kind="user")
    for n in reversed(db.list_project_notes(project_id)):
        cites = n.get("citations") or []
        first = cites[0] if cites else None
        label = (first["title"] + " @ " + first["timestamp"]) if first else "pinned finding"
        add("F", label, n["content"][:1200], first["link"] if first else None)
    sids = db.project_source_ids(project_id)
    srcs = [s for s in db.list_sources(limit=100000) if s["id"] in set(sids)]
    for s in srcs:
        segs = db.get_segments(s["id"])
        preview = " ".join(x["text"] for x in segs[:40])[:500]
        add("S", s["title"] or s["url"], f"{s['title']} ({s.get('channel') or s['platform']}): {preview}", s["url"])
    # retrieval: chunks most relevant to the brief/context and to open questions in chats
    queries = [q for q in [project.get("brief"), project.get("goal"), project.get("context")] if q] + list(project.get("questions") or [])
    for c in db.list_conversations(project_id, limit=20):
        for m in db.get_messages(c["id"], limit=50):
            if m["role"] == "user" and len(m["content"]) < 300:
                queries.append(m["content"])
    seen: set[int] = set()
    for q in queries[:25]:
        for h in search(q, limit=6, source_ids=sids or ["__none__"]):
            if h["chunk_id"] in seen:
                continue
            seen.add(h["chunk_id"])
            add("C", f"{h['title']} @ {h['timestamp']}", f"{h['title']} @ {h['timestamp']}: {h['text'][:900]}", h["link"])
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
    budget = 40000
    for c in db.list_conversations(project_id, limit=30)[::-1]:
        for m in db.get_messages(c["id"], limit=100):
            line = f"{'Q' if m['role'] == 'user' else 'A'}: {m['content'][:1500]}"
            if budget - len(line) < 0:
                break
            parts.append(line)
            budget -= len(line)
    return "\n".join(parts)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError("planner returned no JSON")
    return json.loads(text[start:end + 1])


def _call_claude(system: str, user: str, max_tokens: int = 12000) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(model=settings.answer_model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user}])
    return "".join(getattr(b, "text", "") for b in resp.content)


def build_plan(project_id: str, instructions: str | None = None) -> dict[str, Any]:
    """Generate (or regenerate) the Master Plan for a project. Returns the stored plan row."""
    project = db.get_project(project_id)
    if not project:
        raise RuntimeError("project not found")
    ev, emap = _evidence(project_id, project)
    material = _material(project_id, project, ev)
    prev = db.latest_plan(project_id)
    user = material
    if prev:
        user += "\n\nPREVIOUS PLAN (keep what still holds; change only what the research or instructions justify):\n" + json.dumps(prev["plan"])[:30000]
    if instructions:
        user += "\n\nINSTRUCTIONS FOR THIS REVISION:\n" + instructions
    user += "\n\nWrite the Master Plan JSON now."
    plan = _parse_json(_call_claude(SYSTEM, user))
    plan["_evidence"] = emap
    plan["_generated"] = date.today().isoformat()
    snapshot = db.project_snapshot(project_id)
    row = db.save_plan(project_id, plan, snapshot, carry_statuses_from=prev["id"] if prev else None)
    db.update_project(project_id, mode="plan")
    return row


UPDATE_SYSTEM = """You are Master Planner reviewing whether NEW research changes an existing plan. Compare the new material
against the plan and list only changes that matter (a changed recommendation, a resolved open question, a new
blocking dependency, a materially different cost or risk). Do not rewrite for style. Output ONLY a JSON list:
[{"section": str, "previous": str, "proposed": str, "reason": str}]
Return [] if nothing material changed."""


def suggest_updates(project_id: str) -> list[dict[str, Any]]:
    plan = db.latest_plan(project_id)
    if not plan:
        return []
    since = plan["created_at"]
    conn = db.connect()
    new_notes = [dict(r) for r in conn.execute("SELECT content FROM project_notes WHERE project_id=? AND created_at>?", (project_id, since)).fetchall()]
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
    try:
        raw = _call_claude(UPDATE_SYSTEM, user, max_tokens=4000)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
        s, e = text.find("["), text.rfind("]")
        updates = json.loads(text[s:e + 1]) if s >= 0 else []
    except Exception as exc:  # noqa: BLE001
        log.warning("suggest_updates failed: %s", exc)
        updates = []
    updates = [u for u in updates if isinstance(u, dict) and u.get("proposed")]
    db.add_plan_updates(plan["id"], updates)
    return updates


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
