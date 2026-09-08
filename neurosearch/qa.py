"""Question answering over the knowledge base with Claude, returning timestamped citations.

Flow: retrieve hits -> build numbered context -> Claude answers citing [n] -> map [n] back to
source + timestamp deep links. Optional web supplement uses Claude's built-in web search tool and
is reported separately so you always know what is grounded in your own sources.

Conversational project features:
- URLs pasted into a message are queued for ingestion into the current project.
- Claude has tools to update the project brief, pin findings, and flag gaps in the sources.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from . import db
from .config import settings
from .search import search

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

SYSTEM = """You are Neuro Search, a research assistant answering questions from a personal knowledge base of
video, podcast and audio transcripts, documents, spreadsheets and web pages the user has collected.

Rules:
- Ground every claim in the provided excerpts. Cite with bracketed numbers like [3] immediately after the
  sentence or clause the excerpt supports. Cite as many excerpts as are relevant; one claim can cite several.
- If the excerpts do not answer the question, say so plainly and say what they DO cover. Never invent.
- Quote short, verbatim phrases from the excerpts where the exact wording matters.
- When different sources disagree, point that out and cite both sides.
- Excerpts are auto-generated transcripts: forgive small transcription errors and interpret them sensibly.
- Be concise and useful. Use prose; short bullet lists only when comparing several items.
- Gap detection: when the excerpts only partly cover the question, end with one short line starting with
  "Gap:" naming what is missing and the most useful next step (e.g. a kind of source to add, a speaker or
  channel to look for, or that a web search would help). Call note_gap with the same text. Skip this when the
  excerpts cover the question well.
- The excerpts under the question are only what ONE automatic search found. They are not the whole library. When
  the question has several parts, asks about a particular source, author, channel or document, or the excerpts
  do not answer it, call search_library — one focused query per part or per named source — BEFORE answering, and
  cite what it returns with its [n] numbers. Use list_sources when you need to know what the project actually
  contains; never describe the library from the excerpts alone.
{web_rule}
{project_block}"""

WEB_RULE_ON = """- You may also use the web_search tool for facts that are recent, outside the transcripts, or to verify claims.
  Anything that comes from the web must be clearly marked as such (e.g. "According to the web…") and kept
  separate from what the transcripts say. Prefer the transcripts for what the speakers think or said."""
WEB_RULE_OFF = "- Answer ONLY from the excerpts. Do not use outside knowledge for factual claims."

# The project block is split by volatility (Rung G cache layout): everything that stays the same for the life of a
# project — identity, brief, tool guidance, steering — ends the cached prefix; the project STATE (pinned findings,
# recorded facts) changes as the user works and is sent after the breakpoint, as its own system block, so a pinned
# finding or a recorded fact never invalidates the cached rules + project prefix. Same lines, same meaning.
PROJECT_BLOCK = """
Project: {name}
Project brief (what the user is trying to find out — let this shape what you emphasise):
{brief}

You can shape the project as you talk:
- update_brief: when the user asks to change, widen, narrow or refocus what the project is about. Rewrite the
  whole brief (keep what still applies, fold in the change) and confirm the change in one sentence.
- save_finding: when the user says to pin, save, remember or note something, or asks you to record a
  conclusion. Save a self-contained finding in plain prose with the same [n] citations you used.
- note_gap: record a coverage gap you identified (see Gap detection).
- record_fact: when the user states a decision ("we're going with X"), a constraint (budget, deadline, must/must-not),
  a requirement, or rejects an option, record it so the Master Planner can use it. Kinds: decision | constraint |
  requirement | rejected. Do not record things you merely inferred.
- set_source_priority: when the user says a source, author, channel or document is authoritative, top tier, the
  one to follow, or must be preferred, flag the matching sources so retrieval favours them from now on (tell the
  user which sources were flagged). Use it to unflag when they change their mind.
What the user told us when setting up the project (treat as requirements, not suggestions):
{steering}
"""

PROJECT_STATE_BLOCK = """Pinned findings so far (do not repeat them unless asked; build on them):
{findings}
Known project facts (decisions, constraints, requirements):
{facts}
{research}
{inventory}"""

INVENTORY_MAX = 40
RESEARCH_MAX = 4


def research_block(project_id: str) -> str:
    """G5: the research state the chat must respect — open tensions (an outlier is not consensus; a stale Claim is not
    current) and open evidence targets. $0: reads the map; never triggers extraction."""
    try:
        from . import knowledge
        st = knowledge.state(project_id)
    except Exception:  # noqa: BLE001
        return ""
    m = st["map"]["counts"]
    if not st["claims"] and not st["targets"]:
        return ""
    lines = [f"Research state (Claims: {m.get('strong', 0)} strong / {m.get('developing', 0)} developing / {m.get('weak', 0)} weak topics; say when an answer rests on a weak or single-source Claim):"]
    for t in st["tensions"][:RESEARCH_MAX]:
        lines.append(f"- ⚠ {t['kind']}: {t['description'][:200]}")
    for tg in [x for x in st["targets"] if x["status"] == "open"][:RESEARCH_MAX]:
        lines.append(f"- open evidence target: {tg['question'][:140]}")
    return "\n".join(lines)


def inventory_block(project_id: str) -> str:
    """What the project contains, compactly: counts by kind plus the uploaded documents / files / spreadsheets / web
    pages by title (videos are not listed — there can be hundreds; list_sources covers them). Sits in the volatile
    state block (after the cached prefix) because it changes whenever something is added."""
    rows = db.project_source_inventory(project_id)
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[_kind_label(r)] = kinds.get(_kind_label(r), 0) + 1
    counts = ", ".join(f"{n} {k}{'s' if n != 1 and not k.endswith('s') else ''}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])) or "nothing yet"
    docs = [r for r in rows if r["platform"] not in ("youtube", "instagram", "podcast", "media")]
    lines = [f"Project library: {counts}. Priority sources are marked ★."]
    if docs:
        lines.append("Uploaded documents, files and pages (search them with search_library; they are NOT all in the excerpts):")
        for r in docs[:INVENTORY_MAX]:
            extra = f" · {r['description']}" if r.get("description") else ""
            st = "" if r.get("status") == "ready" else f" ({r.get('status')})"
            lines.append(f"- {'★ ' if r.get('priority') else ''}{r['title']} [{_kind_label(r)}]{extra}{st}")
        if len(docs) > INVENTORY_MAX:
            lines.append(f"- … and {len(docs) - INVENTORY_MAX} more (list_sources)")
    return "\n".join(lines)


def _kind_label(r: dict[str, Any]) -> str:
    return {"youtube": "video", "instagram": "video", "podcast": "podcast episode", "media": "video", "file": "uploaded media file",
            "document": "document", "spreadsheet": "spreadsheet", "web": "web page", "manual": "pasted text"}.get(r.get("platform") or "", r.get("platform") or "source")


def build_context(hits: list[dict[str, Any]], start: int = 0) -> str:
    """Numbered excerpts; `start` offsets the numbering (search_library results continue the answer's numbering)."""
    lines = []
    for n, h in enumerate(hits, start + 1):
        meta = f"{h['title']}"
        if h.get("channel"):
            meta += f" — {h['channel']}"
        if h.get("published_at"):
            meta += f" ({h['published_at']})"
        if h.get("attached"):
            meta += " [attached by the user in this message]"
        elif h.get("priority"):
            meta += " [priority source]"
        lines.append(f"[{n}] {meta} @ {h['timestamp']}\n{h['text']}")
    return "\n\n".join(lines)


def _calc_tool(calcs: list[dict[str, Any]]) -> dict[str, Any]:
    desc = ["Run one of the project's spreadsheet calculators with new inputs and read the recomputed outputs. "
            "The spreadsheet's own formulas do the maths. Refer to inputs/outputs by their labels (or cell addresses). "
            "Always show the user which inputs you set and the resulting outputs, and cite the spreadsheet by name."]
    for c in calcs:
        ins = ", ".join(f"{i['label']} (now {i['value']})" for i in c["inputs"][:25])
        outs = ", ".join(o["label"] for o in c["outputs"][:25])
        desc.append(f"CALCULATOR source_id={c['source_id']} '{c['title']}': INPUTS: {ins or '(none detected)'} → OUTPUTS: {outs or '(none detected)'}")
    return {"name": "calculate", "description": "\n".join(desc)[:4000],
            "input_schema": {"type": "object", "properties": {
                "source_id": {"type": "string"},
                "inputs": {"type": "object", "description": "label or cell → new value", "additionalProperties": True},
                "outputs": {"type": "array", "items": {"type": "string"}, "description": "labels or cells to read; omit for all"}},
                "required": ["source_id"]}}


def _project_tools() -> list[dict[str, Any]]:
    return [
        {"name": "update_brief", "description": "Replace the project's brief with a rewritten version that reflects the user's new focus.",
         "input_schema": {"type": "object", "properties": {"brief": {"type": "string"}}, "required": ["brief"]}},
        {"name": "save_finding", "description": "Pin a finding to the project's notes. Include [n] citations from the excerpts.",
         "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
        {"name": "note_gap", "description": "Record a coverage gap in the project's sources and the suggested next step.",
         "input_schema": {"type": "object", "properties": {"gap": {"type": "string"}}, "required": ["gap"]}},
        {"name": "record_fact", "description": "Record a user-stated decision, constraint, requirement or rejected option for the planner.",
         "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["decision", "constraint", "requirement", "rejected"]},
                                                           "content": {"type": "string"}}, "required": ["kind", "content"]}},
    ]


def _library_tools() -> list[dict[str, Any]]:
    """0.24.1: the chat can search and see the library instead of guessing from one automatic retrieval."""
    flt = {"type": "string", "description": "optional: restrict to sources whose title, author/channel or kind (video, document, spreadsheet, web page, file) contains this text, case-insensitive; or 'priority' for the priority sources"}
    return [
        {"name": "search_library", "description": "Search the project's sources for a focused query and get more numbered excerpts to cite. Call it once per sub-question or per named source; results continue the [n] numbering.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "source_filter": flt,
                                                           "limit": {"type": "integer", "minimum": 1, "maximum": 12}}, "required": ["query"]}},
        {"name": "list_sources", "description": "List what the project contains (title, kind, author/channel, date, status, priority) — the real inventory, optionally filtered.",
         "input_schema": {"type": "object", "properties": {"filter": flt}, "required": []}},
        {"name": "set_source_priority", "description": "Flag (or unflag) sources matching a filter as priority sources for this project: retrieval will favour them. Use when the user says a source/author/channel/document is authoritative or top tier.",
         "input_schema": {"type": "object", "properties": {"filter": {"type": "string"}, "priority": {"type": "boolean", "default": True}}, "required": ["filter"]}},
        {"name": "search_global_library", "description": "Search the user's GLOBAL library — sources they already own in OTHER projects, not attached here. Use when this project's excerpts lack evidence, BEFORE suggesting new acquisition or the web. Results are suggestions with passages you may quote to explain why they look useful, but they are NOT project evidence: do not cite them with [n]; tell the user which to attach (Sources → Library → Add).",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}},
        {"name": "research_state", "description": "The project's Knowledge Map: topics with Strong/Developing/Weak/Missing state and WHY, open Research Tensions (novel outliers, contradictions, weak consensus, stale, missing perspectives) and open Evidence Targets with their closure criteria. $0. Use when the user asks what is established, what is weak, what to research next, or 'what am I missing'.",
         "input_schema": {"type": "object", "properties": {"topic": {"type": "string", "description": "optional: restrict to topics containing this text"}}, "required": []}},
        {"name": "propose_claim", "description": "Record an EXTERNAL factual proposition the user asserts or asks about that needs evidence (e.g. 'SBA lets me borrow $2M'), as a proposed Claim with an Evidence Target. NOT for the user's own constraints/decisions ('my budget is $2M' → record_fact). Keep every qualifier (jurisdiction, product, conditions, timeframe).",
         "input_schema": {"type": "object", "properties": {"text": {"type": "string"}, "claim_type": {"type": "string", "enum": ["governing", "historical", "expert_interpretation", "practice", "experiential", "market", "causal", "novel_tactic", "other"]},
                                                           "topic": {"type": "string"}}, "required": ["text", "claim_type"]}},
        {"name": "search_seen_sources", "description": "Search the Candidate Index: sources Neuro Search has SEEN (listed from channels, feeds, sites) but NOT acquired. Use when the library lacks evidence for a gap, BEFORE suggesting a web search. Results are metadata only — they cannot be cited; tell the user which ones look worth acquiring (Sources → Library → Seen, not added).",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["query"]}},
    ]


def _matches(r: dict[str, Any], flt: str | None) -> bool:
    if not flt:
        return True
    f = flt.strip().lower()
    if f == "priority":
        return bool(r.get("priority"))
    hay = " ".join(str(x) for x in (r.get("title"), r.get("channel"), r.get("platform"), _kind_label(r), r.get("url")) if x).lower()
    return all(tok in hay for tok in f.split())


def _retrieval_query(question: str, history: list[dict[str, Any]]) -> str:
    """Follow-up grounding without a model call: a short or back-referring message ("what about the PDFs?",
    "and those two?") retrieves badly on its own words, so the previous substantive user message is prepended to the
    retrieval query. The question the model answers is unchanged."""
    words = question.split()
    prev = next((m["content"] for m in reversed(history) if m.get("role") == "user" and m.get("content")), None)
    if not prev:
        return question
    referential = re.search(r"\b(those|these|that|this|it|them|above|earlier|previous|again|the (pdf|pdfs|document|documents|file|files|source|sources|book|books))\b", question.lower())
    if len(words) <= 12 or (referential and len(words) < 40):
        return f"{prev[:600]}\n{question}"
    return question


def queue_urls(urls: list[str], project_id: str | None) -> list[dict[str, Any]]:
    """Queue pasted URLs for ingestion (into the project if any). Returns job summaries. G2: each link is classified
    first; items and reviewable collections go to the standard lifecycle, containers (a whole website, repository,
    community, feed, sitemap) are NOT fetched as a page — they come back as `detected` with the available choices."""
    from . import resources

    out = []
    for u in urls:
        c = resources.classify(u.rstrip(".,;:!?)"))
        if c.kind in resources.CONTAINER_KINDS or c.kind in ("feed", "sitemap", "image"):
            out.append({"job_id": None, "url": c.url or u, "detected": c.as_dict()})
            continue
        r = resources.route(c, project_id, tags=[])
        out.append({"job_id": r.get("job_id"), "url": c.url or u, "kind": c.kind, "review": r.get("review", False)} if r.get("job_id")
                   else {"job_id": None, "url": c.url or u, "detected": c.as_dict()})
    return out


def chat_system_blocks(project: dict[str, Any] | None, use_web: bool, tools: list[dict[str, Any]], full_context: str | None) -> tuple[list[dict[str, Any]], bool]:
    """The chat system prompt in cache order (Rung G layout):
         [1] rules + web rule + project identity/brief/tool guidance/steering   — stable for the life of the project  → breakpoint
         [2] the whole scoped material when it fits (≤ MAX_FULL_CONTEXT_SOURCES) — stable per source set             → breakpoint
         [3] project state: pinned findings + recorded facts                       — changes as the user works       (after the prefix)
       Tools precede the system prompt in the provider's cache order, so their size counts toward the ≥1024-token
       minimum a cached prefix needs. Returns (system_blocks, excerpts_in_system)."""
    from . import usage
    if project:
        notes = db.list_project_notes(project["id"])[:15]
        findings = "\n".join(f"- {n['content'][:400]}" for n in notes) or "(none yet)"
        facts = "\n".join(f"- [{f['kind']}] {f['content']}" for f in db.list_facts(project["id"])) or "(none yet)"
        project_block = PROJECT_BLOCK.format(name=project["name"], brief=project.get("brief") or "(none)", steering=db.project_steering(project))
        state_block: str | None = PROJECT_STATE_BLOCK.format(findings=findings, facts=facts, research=research_block(project["id"]), inventory=inventory_block(project["id"]))
    else:
        project_block, state_block = "", None
    system = SYSTEM.format(web_rule=WEB_RULE_ON if use_web else WEB_RULE_OFF, project_block=project_block)
    tool_chars = len(json.dumps(tools, default=str)) if tools else 0
    blocks: list[dict[str, Any]] = [usage.cached_block(system, min_chars=tool_chars)]
    if full_context is not None:
        blocks.append(usage.cached_block(f"The user's material (cite it as [n]):\n<excerpts>\n{full_context}\n</excerpts>", min_chars=tool_chars + len(system)))
    if state_block:
        blocks.append({"type": "text", "text": state_block})
    return blocks, full_context is not None


def _tail_breakpoint(messages: list[dict[str, Any]]) -> None:
    """The conversation-tail breakpoint (usage.mark_last) is OFF by default (0.20.0+g5, Rung G decision): it writes the
    volatile per-turn material at 1.25× and can never produce a cross-turn hit (history is stored without the excerpts
    that were sent), so it only pays back when the SAME turn makes another call (tool round, citation repair) — break-even
    ≈ one extra round per four turns; the default is optimised for the common single-call turn (new-conversation input
    cost index 0.843 → 0.682, `neurosearch eval --cache-layout`). NEUROSEARCH_CHAT_TAIL_BREAKPOINT=1 enables it for
    experimentation or tool-heavy workloads. No adaptive/predictive logic by decision."""
    from . import usage
    if os.environ.get("NEUROSEARCH_CHAT_TAIL_BREAKPOINT", "0") == "1":
        usage.mark_last(messages)


OBSERVER: Any = None      # evals hook: one dict per provider call (task, round, stop_reason, tools, model); never changes behaviour


def ask(
    question: str,
    project_id: str | None = None,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    use_web: bool = False,
    limit: int = 14,
    attached_source_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Answer a question. Returns {answer, citations, hits, web_used, project, ingest_jobs, actions}.
    attached_source_ids: sources the user uploaded with this message (0.24.1) — included in the excerpts on this turn."""
    project = db.get_project(project_id) if project_id else None
    actions: list[dict[str, Any]] = []

    # 1. URLs in the message -> ingest into this project
    urls = URL_RE.findall(question)
    ingest_jobs = queue_urls(urls, project_id) if urls else []
    if urls:
        question_wo = URL_RE.sub("", question).strip(" \n,;:-—")
        detected = [j["detected"] for j in ingest_jobs if j.get("detected")]
        queued = [j for j in ingest_jobs if j.get("job_id")]
        if len(question_wo.split()) < 4:  # nothing left to answer: just confirm
            where = f" into project **{project['name']}**" if project else ""
            bulk = [j for j in queued if j.get("review")]
            parts = []
            if queued:
                parts.append(f"Queued {len(queued)} link{'s' if len(queued) > 1 else ''}{where}. "
                             + ("Channels, playlists and searches are listed first and wait for your approval in **Sources → Review** before anything is transcribed. " if bulk else "")
                             + "I'll use new sources as soon as they're ready — ask again in a minute.")
            for d in detected:
                choices = ", ".join(a["label"] + ("" if a["available"] else " (not yet)") for a in d["actions"]) or "no action yet"
                parts.append(f"**{d['label']}** — {d['detail']} Options in **Sources → Add**: {choices}.")
            answer = "\n\n".join(parts) or "I couldn't tell what to do with that link."
            if conversation_id:
                db.save_message(conversation_id, "user", question, project_id=project_id, title=question[:80])
                db.save_message(conversation_id, "assistant", answer, citations=[], project_id=project_id)
            return {"answer": answer, "citations": [], "hits": [], "web_used": False, "web_sources": [],
                    "project": _pj(project), "conversation_id": conversation_id, "ingest_jobs": ingest_jobs,
                    "actions": actions}
        question = question_wo

    from . import providers

    providers.require_anthropic()
    if project and not source_ids:
        source_ids = project["source_ids"] or ["__none__"]

    history = db.get_messages(conversation_id, limit=12) if conversation_id else []
    priority_ids = db.priority_source_ids(project["id"]) if project else set()
    rq = _retrieval_query(question, history)
    hits, full_context = _hits_for(rq, limit, source_ids, priority_ids=priority_ids, attached_ids=attached_source_ids)
    ctx = {"hits": hits, "source_ids": source_ids, "priority_ids": priority_ids, "seen": {h["chunk_id"] for h in hits}}

    tools: list[dict[str, Any]] = []
    if use_web:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 4})
    if project:
        tools += _project_tools() + _library_tools()
        from .sheets import calculators_for_project
        calcs = calculators_for_project(project["id"])
        if calcs:
            tools.append(_calc_tool(calcs))

    context = build_context(hits) if hits else "(no relevant excerpts were found in the knowledge base)"
    system_blocks, in_system = chat_system_blocks(project, use_web, tools, context if (full_context and hits) else None)
    excerpt_part = "(The excerpts are in your instructions above.)" if in_system else f"<excerpts>\n{context}\n</excerpts>"
    messages: list[dict[str, Any]] = []
    for m in history:
        if m["role"] in ("user", "assistant") and m["content"]:
            messages.append({"role": m["role"], "content": m["content"]})
    note = ""
    if ingest_jobs:
        n_q = sum(1 for j in ingest_jobs if j.get("job_id"))
        note = (f"\n(Note: the user also pasted {n_q} link(s) which are now being ingested; mention they'll be available shortly.)" if n_q else "")
        for j in ingest_jobs:
            if j.get("detected"):
                d = j["detected"]
                note += f"\n(Note: {d['url'] or d['input']} was recognised as a {d['kind'].replace('_', ' ')} — NOT added: {d['detail']} Tell the user the choices are in Sources → Add.)"
    if attached_source_ids:
        titles = [(db.get_source(sid) or {}).get("title") or sid for sid in attached_source_ids]
        note += f"\n(Note: the user attached {', '.join(titles)} to this message; it has been added to the project and its content is in the excerpts marked [attached].)"
    messages.append({"role": "user", "content": f"{excerpt_part}\n\nQuestion: {question}{note}"})
    from . import usage

    answer_parts: list[str] = []
    web_sources: list[dict[str, str]] = []
    web_used = False
    pending_findings: list[str] = []

    for _round in range(6):
        _tail_breakpoint(messages)
        resp = providers.invoke("answer.chat", system=system_blocks, messages=messages, tools=tools or None)
        try:
            usage.record_anthropic(resp, "answer", project_id=project_id)
        except Exception:  # noqa: BLE001
            pass
        if OBSERVER:
            OBSERVER({"task": "answer.chat", "round": _round + 1, "stop_reason": getattr(resp, "stop_reason", None),
                      "tools": [b.name for b in resp.content if getattr(b, "type", None) == "tool_use"], "model": getattr(resp, "model", None)})
        tool_results: list[dict[str, Any]] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                answer_parts.append(block.text)
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", None)
                    if url and url not in {w["url"] for w in web_sources}:
                        web_sources.append({"url": url, "title": getattr(c, "title", None) or url})
            elif btype in ("server_tool_use", "web_search_tool_result"):
                web_used = True
            elif btype == "tool_use":
                result = _run_tool(block.name, block.input, project, pending_findings, actions, ctx)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        if resp.stop_reason == "tool_use" and tool_results:
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})
            continue
        break

    answer = "\n".join(p for p in answer_parts if p.strip()).strip()

    # Citations must point at excerpts we actually supplied. A bad one is NOT silently removed (that would turn a
    # falsely-cited claim into a confident uncited one): the model gets one repair round; if it still cites
    # nothing, the answer is rendered as-is with a validation warning the user can see.
    from .evidence import check_citations
    _valid, invalid = check_citations(answer + " " + " ".join(pending_findings), len(hits))
    validation: dict[str, Any] = {}
    if invalid:
        log.warning("answer cited excerpts that do not exist: %s — asking for a repair", invalid)
        db.validation_event("citation_validation_failed", {"invalid": invalid, "excerpts": len(hits), "answer": answer[:600]}, project_id=project_id)
        try:
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": f"Your answer cites {', '.join(f'[{n}]' for n in invalid)} but only excerpts [1]–[{len(hits)}] were provided"
                             + (" (no excerpts were provided)" if not hits else "") + ". Rewrite the whole answer using only citations that exist; "
                             "if a claim is not supported by any excerpt, say so plainly instead of citing. Keep everything else the same."})
            _tail_breakpoint(messages)
            resp2 = providers.invoke("answer.repair", system=system_blocks, messages=messages)
            usage.record_anthropic(resp2, "answer", project_id=project_id)
            repaired = providers.text_of(resp2).strip()
            v2, inv2 = check_citations(repaired + " " + " ".join(pending_findings), len(hits))
            if OBSERVER:
                OBSERVER({"task": "answer.repair", "stop_reason": getattr(resp2, "stop_reason", None), "model": getattr(resp2, "model", None),
                          "originally_invalid": invalid, "still_invalid": inv2, "success": bool(repaired and not inv2)})
            if repaired and not inv2:
                validation = {"repaired": True, "originally_invalid": invalid}
                db.validation_event("citation_repaired", {"invalid": invalid}, project_id=project_id)
                answer, _valid, invalid = repaired, v2, []
            else:
                invalid = inv2 or invalid
        except Exception as e:  # noqa: BLE001
            log.warning("citation repair failed: %s", e)
        if invalid:
            validation = {"invalid_citations": invalid,
                          "warning": f"This answer cites {', '.join(f'[{n}]' for n in invalid)}, which do not correspond to any excerpt from your sources. "
                                     "Treat those claims as unverified."}
            db.kv_bump("evidence:citations_invalid", len(invalid))
    db.kv_bump("evidence:citations_checked", len(_valid) + len(invalid))

    cited_nums = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", answer + " " + " ".join(pending_findings))})
    citations = []
    for n in cited_nums:
        if 1 <= n <= len(hits):
            h = hits[n - 1]
            citations.append({"n": n, **{k: h[k] for k in ("source_id", "title", "channel", "url", "link", "timestamp", "start", "end", "platform")},
                              "snippet": h["text"][:300]})

    # findings are saved after citations are resolved so they carry real links
    if project and pending_findings:
        for content in pending_findings:
            nums = {int(n) for n in re.findall(r"\[(\d{1,2})\]", content)}
            db.add_project_note(project["id"], content, [c for c in citations if c["n"] in nums])

    if conversation_id:
        db.save_message(conversation_id, "user", question, project_id=project_id, title=question[:80])
        db.save_message(conversation_id, "assistant", answer, citations=citations, project_id=project_id, meta=validation or None)

    return {
        "answer": answer,
        "citations": citations,
        "hits": hits,
        "web_used": web_used,
        "web_sources": web_sources,
        "project": _pj(db.get_project(project["id"]) if project else None),
        "conversation_id": conversation_id,
        "ingest_jobs": ingest_jobs,
        "actions": actions,
        "invalid_citations": invalid,
        "validation": validation,
    }


FULL_CONTEXT_CHARS = 90000  # if everything in scope fits in this, skip retrieval and hand Claude the whole thing


ATTACHED_FULL_CHARS = 30000   # an attached document up to this size goes into the excerpts whole; larger ones contribute their best chunks
ATTACHED_TOP = 6


def _attached_hits(query: str, attached_ids: list[str]) -> list[dict[str, Any]]:
    from .search import hit_from_chunk, search as _search
    out: list[dict[str, Any]] = []
    for sid in attached_ids:
        src = db.get_source(sid) or {}
        if src.get("status") != "ready":
            continue
        chunks = db.get_chunks(sid)
        if chunks and sum(len(c["text"]) for c in chunks) <= ATTACHED_FULL_CHARS:
            for c in chunks:
                c.update(title=src.get("title"), url=src.get("url"), platform=src.get("platform"), channel=src.get("channel"), published_at=src.get("published_at"))
                out.append({**hit_from_chunk(c, 1.0), "attached": True})
        else:
            for h in _search(query, limit=ATTACHED_TOP, source_ids=[sid], per_source_cap=ATTACHED_TOP):
                out.append({**h, "attached": True})
    return out


def _hits_for(question: str, limit: int, source_ids: list[str] | None, priority_ids: set[str] | None = None,
              attached_ids: list[str] | None = None) -> tuple[list[dict[str, Any]], bool]:
    """Retrieval, except when the scoped material is small enough to include in full (better for
    'summarise this' / 'main points' questions, which retrieval handles badly). Returns (hits, is_full_context).
    Attached sources (uploaded with this message) come first; priority sources get reserved slots (search.PRIORITY_RESERVE)."""
    from .search import hit_from_chunk

    if attached_ids:
        first = _attached_hits(question, attached_ids)
        seen = {h["chunk_id"] for h in first}
        rest = [h for h in search(question, limit=limit, source_ids=source_ids, priority_ids=priority_ids or None) if h["chunk_id"] not in seen]
        return first + rest[: max(limit - min(len(first), limit // 2), 4)], False
    if source_ids and "__none__" not in source_ids and len(source_ids) <= 6:
        chunks: list[dict[str, Any]] = []
        total = 0
        for sid in source_ids:
            src = db.get_source(sid) or {}
            for c in db.get_chunks(sid):
                c.update(title=src.get("title"), url=src.get("url"), platform=src.get("platform"),
                         channel=src.get("channel"), published_at=src.get("published_at"))
                chunks.append(c)
                total += len(c["text"])
        if chunks and total <= FULL_CONTEXT_CHARS:
            # de-overlap: chunks overlap by design; keep every other chunk's overlap out by trimming nothing —
            # cheap and fine for the model. Order by source then time.
            return [hit_from_chunk(c, 1.0) for c in chunks], True
    return search(question, limit=limit, source_ids=source_ids, priority_ids=priority_ids or None), False


def _pj(project: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"id": project["id"], "name": project["name"], "brief": project.get("brief")} if project else None


MAX_EXCERPTS = 60   # hard ceiling on excerpts per answer (initial retrieval + search_library calls)


def _run_tool(name: str, inp: dict[str, Any], project: dict[str, Any] | None,
              pending_findings: list[str], actions: list[dict[str, Any]], ctx: dict[str, Any] | None = None) -> str:
    if not project:
        return "no project in scope"
    ctx = ctx if ctx is not None else {"hits": [], "source_ids": None, "priority_ids": set(), "seen": set()}
    if name == "search_library":
        query = (inp.get("query") or "").strip()
        if not query:
            return "query was empty"
        flt = inp.get("source_filter")
        scope = ctx.get("source_ids")
        if flt:
            rows = [r for r in db.project_source_inventory(project["id"]) if r.get("status") == "ready" and _matches(r, flt)]
            if not rows:
                return f"no sources match '{flt}' — call list_sources to see the inventory"
            scope = [r["id"] for r in rows]
        room = MAX_EXCERPTS - len(ctx["hits"])
        if room <= 0:
            return "excerpt limit reached for this answer; answer from the excerpts you already have"
        n = min(int(inp.get("limit") or 8), 12, room)
        found = [h for h in search(query, limit=n + len(ctx["seen"]), source_ids=scope, priority_ids=ctx.get("priority_ids") or None, reserve=0)
                 if h["chunk_id"] not in ctx["seen"]][:n]
        if not found:
            return "nothing relevant found for that query" + (f" within '{flt}'" if flt else "")
        start = len(ctx["hits"])
        ctx["hits"].extend(found)
        ctx["seen"].update(h["chunk_id"] for h in found)
        new_part = build_context(found, start=start)
        actions.append({"type": "searched", "query": query, "filter": flt, "added": len(found)})
        return f"<excerpts>\n{new_part}\n</excerpts>\n(cite these as [{start + 1}]–[{len(ctx['hits'])}])"
    if name == "search_global_library":
        from . import library as _lib
        query = (inp.get("query") or "").strip()
        res = _lib.recall(project["id"], query, limit=min(int(inp.get("limit") or 5), 10), reason=f"chat: {query[:120]}") if query else {"suggestions": []}
        actions.append({"type": "library_searched", "query": query, "found": len(res["suggestions"]), "suggestions": [{"source_id": s["source_id"], "title": s["title"]} for s in res["suggestions"][:8]]})
        if not res["suggestions"]:
            return "nothing in the global library (outside this project) matches; the Candidate Index or external discovery would be next"
        lines = [f"{len(res['suggestions'])} source(s) the user already OWNS but has not attached to this project — NOT project evidence, do not cite as [n]:"]
        for s in res["suggestions"]:
            sig = ", ".join(f"{a['value']}" for a in s.get("authority_signals", [])[:3])
            lines.append(f"- {s['title']} ({s.get('channel') or s.get('platform')}{'; ' + s['published_at'] if s.get('published_at') else ''}; {sig}) — {'; '.join(s['why'])}"
                         + (f"\n  best passage @ {s['chunks'][0]['timestamp']}: “{s['chunks'][0]['text'][:200]}”" if s.get("chunks") else "")
                         + (f"\n  profile: {s['profile_summary']}" if s.get("profile_summary") else ""))
        lines.append("Suggest attaching the useful ones (Sources → Library → Add); once attached, search_library will return them as citable excerpts.")
        return "\n".join(lines)
    if name == "research_state":
        from . import knowledge
        st = knowledge.state(project["id"])
        flt = (inp.get("topic") or "").strip().lower()
        nodes = [n for n in st["map"]["nodes"] if not flt or flt in n["topic"]]
        actions.append({"type": "research_state", "counts": st["map"]["counts"], "tensions": len(st["tensions"]), "targets_open": sum(1 for x in st["targets"] if x["status"] == "open")})
        if not nodes and not st["tensions"] and not st["targets"]:
            return "no research state yet: no Claims have been harvested (approve findings, or refresh the Research view)"
        lines = ["Knowledge Map (state — why):"]
        for n in nodes[:20]:
            lines.append(f"- {n['topic']}: {n['state'].upper()} — {n['why'][:220]}")
        if st["tensions"]:
            lines.append("Open research tensions:")
            for t in st["tensions"][:10]:
                lines.append(f"- {t['kind']} ({t['impact']}): {t['description'][:220]}")
        open_t = [x for x in st["targets"] if x["status"] == "open"]
        if open_t:
            lines.append("Open evidence targets (closure = what counts as enough):")
            for tg in open_t[:10]:
                lines.append(f"- [{tg['sufficiency']}] {tg['question'][:160]} — closure: {(tg.get('closure') or '')[:120]}" + (f" — gap: {tg['gap'][:120]}" if tg.get("gap") else ""))
        return "\n".join(lines)
    if name == "propose_claim":
        from . import claims as _claims, knowledge
        text = (inp.get("text") or "").strip()
        ctype = inp.get("claim_type") if inp.get("claim_type") in _claims.TYPES else "other"
        c = _claims.add_claim(project["id"], text, claim_type=ctype, topic=inp.get("topic"), origin="chat", status="proposed", normalized=True)
        suff = "governing" if ctype in _claims.GOVERNING_TYPES else "corroborative"
        tg = knowledge.add_target(project["id"], f"Establish: {text[:160]}", topic=c["topic"], claim_id=c["id"], sufficiency=suff, origin="chat")
        knowledge.refresh(project["id"])
        actions.append({"type": "claim_proposed", "claim_id": c["id"], "text": text, "claim_type": ctype, "target_id": (tg or {}).get("id")})
        return f"recorded as a PROPOSED {ctype} Claim (unsupported until evidence is linked) with an evidence target ({suff} sufficiency: {(tg or {}).get('closure')}). It is not accepted project truth."
    if name == "search_seen_sources":
        from . import candidates as _cand
        query = (inp.get("query") or "").strip()
        rows = _cand.search(project["id"], query, limit=min(int(inp.get("limit") or 8), 20)) if query else []
        actions.append({"type": "candidates_searched", "query": query, "found": len(rows)})
        if not rows:
            return "nothing in the Candidate Index matches (nothing seen-but-unacquired covers this); external discovery would be the next step"
        lines = [f"{len(rows)} seen-but-not-acquired candidate(s) — METADATA ONLY, not evidence, do not cite:"]
        for r in rows:
            o = (r.get("project") or {}).get("origin") or {}
            where = f" · seen in {o.get('title') or o.get('kind') or 'a listing'}" if o else ""
            lines.append(f"- {r.get('title') or r['url']} ({r.get('content_type')}{', ' + r['creator'] if r.get('creator') else ''}{', ' + r['published_at'] if r.get('published_at') else ''}; state {r['state']}{where}{'; already in the library' if r.get('in_library') else ''})"
                         + (f" — {r['description'][:160]}" if r.get("description") else ""))
        return "\n".join(lines)
    if name == "list_sources":
        flt = inp.get("filter")
        rows = [r for r in db.project_source_inventory(project["id"]) if _matches(r, flt)]
        if not rows:
            return "no sources match" if flt else "the project has no sources"
        lines = [f"{len(rows)} source(s){' matching ' + repr(flt) if flt else ''}:"]
        for r in rows[:80]:
            bits = [_kind_label(r)]
            if r.get("channel"):
                bits.append(r["channel"])
            if r.get("published_at"):
                bits.append(str(r["published_at"]))
            if r.get("description") and r.get("platform") in ("document", "spreadsheet"):
                bits.append(r["description"])
            if r.get("status") != "ready":
                bits.append(f"status: {r.get('status')}")
            lines.append(f"- {'★ ' if r.get('priority') else ''}{r['title']} ({'; '.join(bits)})")
        if len(rows) > 80:
            lines.append(f"… and {len(rows) - 80} more — narrow the filter")
        return "\n".join(lines)
    if name == "set_source_priority":
        flt = (inp.get("filter") or "").strip()
        flag = bool(inp.get("priority", True))
        rows = [r for r in db.project_source_inventory(project["id"]) if flt and _matches(r, flt)]
        if not rows:
            return f"no sources match '{flt}' — call list_sources and try a title, author or channel"
        db.set_source_priority(project["id"], [r["id"] for r in rows], flag)
        ctx["priority_ids"] = db.priority_source_ids(project["id"])
        actions.append({"type": "priority_set", "filter": flt, "priority": flag, "titles": [r["title"] for r in rows][:20], "count": len(rows)})
        return ("flagged" if flag else "unflagged") + f" {len(rows)} source(s) as priority: " + "; ".join(r["title"] for r in rows[:20])
    if name == "calculate":
        from .sheets import calculate
        import json as _json
        try:
            res = calculate(inp.get("source_id") or "", inp.get("inputs") or {}, inp.get("outputs") or None)
            actions.append({"type": "calculated", "source_id": inp.get("source_id"), "inputs": res["inputs_applied"], "outputs": res["outputs"]})
            return _json.dumps(res, default=str)
        except Exception as e:  # noqa: BLE001
            return f"calculation failed: {e}"
    if name == "update_brief":
        brief = (inp.get("brief") or "").strip()
        if not brief:
            return "brief was empty; not changed"
        db.update_project(project["id"], brief=brief)
        actions.append({"type": "brief_updated", "brief": brief})
        return "brief updated"
    if name == "save_finding":
        content = (inp.get("content") or "").strip()
        if content:
            pending_findings.append(content)
            actions.append({"type": "finding_saved", "content": content})
        return "finding pinned"
    if name == "record_fact":
        content = (inp.get("content") or "").strip()
        kind = inp.get("kind") or "decision"
        if content:
            db.add_fact(project["id"], kind, content, origin="user")
            actions.append({"type": "fact_recorded", "kind": kind, "content": content})
        return "recorded"
    if name == "note_gap":
        gap = (inp.get("gap") or "").strip()
        if gap:
            db.add_project_note(project["id"], "Gap: " + gap, [])
            actions.append({"type": "gap_noted", "gap": gap})
        return "gap noted"
    return f"unknown tool {name}"


def render_markdown(result: dict[str, Any]) -> str:
    """Answer + a numbered source list with timestamp links (for CLI / MCP)."""
    out = [result["answer"], ""]
    if result["citations"]:
        out.append("Sources:")
        for c in result["citations"]:
            out.append(f"[{c['n']}] {c['title']} @ {c['timestamp']} — {c['link']}")
    if result.get("web_sources"):
        out.append("")
        out.append("Web:")
        for w in result["web_sources"]:
            out.append(f"- {w['title']} — {w['url']}")
    if result.get("ingest_jobs"):
        out.append("")
        out.append("Ingesting: " + ", ".join(j["url"] for j in result["ingest_jobs"]))
    for a in result.get("actions") or []:
        if a["type"] == "brief_updated":
            out.append("\nProject brief updated.")
        elif a["type"] == "finding_saved":
            out.append("\nPinned a finding to the project.")
        elif a["type"] == "fact_recorded":
            out.append(f"\nRecorded {a['kind']}: {a['content']}")
        elif a["type"] == "priority_set":
            out.append(f"\n{'Flagged' if a['priority'] else 'Unflagged'} {a['count']} priority source(s).")
        elif a["type"] == "library_searched":
            out.append(f"\nChecked the global library for “{a['query']}”: {a['found']} owned-but-unattached source(s).")
        elif a["type"] == "candidates_searched":
            out.append(f"\nChecked the Candidate Index for “{a['query']}”: {a['found']} seen-but-not-acquired.")
    return "\n".join(out)
