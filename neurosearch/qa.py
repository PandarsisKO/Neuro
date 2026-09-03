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
import re
from typing import Any

from . import db
from .config import settings
from .search import search

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

SYSTEM = """You are Neuro Search, a research assistant answering questions from a personal knowledge base of
video, podcast and audio transcripts the user has collected.

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
{web_rule}
{project_block}"""

WEB_RULE_ON = """- You may also use the web_search tool for facts that are recent, outside the transcripts, or to verify claims.
  Anything that comes from the web must be clearly marked as such (e.g. "According to the web…") and kept
  separate from what the transcripts say. Prefer the transcripts for what the speakers think or said."""
WEB_RULE_OFF = "- Answer ONLY from the excerpts. Do not use outside knowledge for factual claims."

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
Pinned findings so far (do not repeat them unless asked; build on them):
{findings}
Known project facts (decisions, constraints, requirements):
{facts}
What the user told us when setting up the project (treat as requirements, not suggestions):
{steering}
"""


def build_context(hits: list[dict[str, Any]]) -> str:
    lines = []
    for n, h in enumerate(hits, 1):
        meta = f"{h['title']}"
        if h.get("channel"):
            meta += f" — {h['channel']}"
        if h.get("published_at"):
            meta += f" ({h['published_at']})"
        lines.append(f"[{n}] {meta} @ {h['timestamp']}\n{h['text']}")
    return "\n\n".join(lines)


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


def queue_urls(urls: list[str], project_id: str | None) -> list[dict[str, Any]]:
    """Queue pasted URLs for ingestion (into the project if any). Returns job summaries."""
    from . import jobs

    out = []
    for u in urls:
        u = u.rstrip(".,;:!?")
        j = jobs.enqueue("ingest_url", {"url": u, "tags": [], "project_id": project_id})
        out.append({"job_id": j["id"], "url": u})
    return out


def ask(
    question: str,
    project_id: str | None = None,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    use_web: bool = False,
    limit: int = 14,
) -> dict[str, Any]:
    """Answer a question. Returns {answer, citations, hits, web_used, project, ingest_jobs, actions}."""
    project = db.get_project(project_id) if project_id else None
    actions: list[dict[str, Any]] = []

    # 1. URLs in the message -> ingest into this project
    urls = URL_RE.findall(question)
    ingest_jobs = queue_urls(urls, project_id) if urls else []
    if urls:
        question_wo = URL_RE.sub("", question).strip(" \n,;:-—")
        if len(question_wo.split()) < 4:  # nothing left to answer: just confirm
            where = f" into project **{project['name']}**" if project else ""
            answer = (f"Queued {len(urls)} link{'s' if len(urls) > 1 else ''} for ingestion{where}. "
                      "Playlists and channels expand into every video; I'll use the new sources as soon as "
                      "they're ready — ask again in a minute.")
            if conversation_id:
                db.save_message(conversation_id, "user", question, project_id=project_id, title=question[:80])
                db.save_message(conversation_id, "assistant", answer, citations=[], project_id=project_id)
            return {"answer": answer, "citations": [], "hits": [], "web_used": False, "web_sources": [],
                    "project": _pj(project), "conversation_id": conversation_id, "ingest_jobs": ingest_jobs,
                    "actions": actions}
        question = question_wo

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic

    if project and not source_ids:
        source_ids = project["source_ids"] or ["__none__"]

    hits = _hits_for(question, limit, source_ids)
    history = db.get_messages(conversation_id, limit=12) if conversation_id else []

    if project:
        notes = db.list_project_notes(project["id"])[:15]
        findings = "\n".join(f"- {n['content'][:400]}" for n in notes) or "(none yet)"
        facts = "\n".join(f"- [{f['kind']}] {f['content']}" for f in db.list_facts(project["id"])) or "(none yet)"
        project_block = PROJECT_BLOCK.format(name=project["name"], brief=project.get("brief") or "(none)", findings=findings,
                                             facts=facts, steering=db.project_steering(project))
    else:
        project_block = ""
    system = SYSTEM.format(web_rule=WEB_RULE_ON if use_web else WEB_RULE_OFF, project_block=project_block)

    context = build_context(hits) if hits else "(no relevant excerpts were found in the knowledge base)"
    messages: list[dict[str, Any]] = []
    for m in history:
        if m["role"] in ("user", "assistant") and m["content"]:
            messages.append({"role": m["role"], "content": m["content"]})
    note = ""
    if ingest_jobs:
        note = f"\n(Note: the user also pasted {len(ingest_jobs)} link(s) which are now being ingested; mention they'll be available shortly.)"
    messages.append({"role": "user", "content": f"<excerpts>\n{context}\n</excerpts>\n\nQuestion: {question}{note}"})

    tools: list[dict[str, Any]] = []
    if use_web:
        tools.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 4})
    if project:
        tools += _project_tools()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    answer_parts: list[str] = []
    web_sources: list[dict[str, str]] = []
    web_used = False
    pending_findings: list[str] = []

    for _round in range(6):
        kwargs: dict[str, Any] = dict(model=settings.answer_model, max_tokens=2000, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        try:
            from . import usage
            usage.record_anthropic(resp, "answer", project_id=project_id)
        except Exception:  # noqa: BLE001
            pass
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
                result = _run_tool(block.name, block.input, project, pending_findings, actions)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        if resp.stop_reason == "tool_use" and tool_results:
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})
            continue
        break

    answer = "\n".join(p for p in answer_parts if p.strip()).strip()

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
        db.save_message(conversation_id, "assistant", answer, citations=citations, project_id=project_id)

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
    }


FULL_CONTEXT_CHARS = 90000  # if everything in scope fits in this, skip retrieval and hand Claude the whole thing


def _hits_for(question: str, limit: int, source_ids: list[str] | None) -> list[dict[str, Any]]:
    """Retrieval, except when the scoped material is small enough to include in full (better for
    'summarise this' / 'main points' questions, which retrieval handles badly)."""
    from .search import hit_from_chunk

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
            return [hit_from_chunk(c, 1.0) for c in chunks]
    return search(question, limit=limit, source_ids=source_ids)


def _pj(project: dict[str, Any] | None) -> dict[str, Any] | None:
    return {"id": project["id"], "name": project["name"], "brief": project.get("brief")} if project else None


def _run_tool(name: str, inp: dict[str, Any], project: dict[str, Any] | None,
              pending_findings: list[str], actions: list[dict[str, Any]]) -> str:
    if not project:
        return "no project in scope"
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
    return "\n".join(out)
