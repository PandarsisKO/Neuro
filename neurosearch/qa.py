"""Question answering over the knowledge base with Claude, returning timestamped citations.

Flow: retrieve hits -> build numbered context -> Claude answers citing [n] -> map [n] back to
source + timestamp deep links. Optional web supplement uses Claude's built-in web search tool and
is reported separately so you always know what is grounded in your own sources.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import db
from .config import settings
from .search import search

log = logging.getLogger(__name__)

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


def ask(
    question: str,
    project_id: str | None = None,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    use_web: bool = False,
    limit: int = 14,
) -> dict[str, Any]:
    """Answer a question. Returns {answer, citations, hits, web_used, project}."""
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    import anthropic

    project = db.get_project(project_id) if project_id else None
    if project and not source_ids:
        source_ids = project["source_ids"] or ["__none__"]

    hits = search(question, limit=limit, source_ids=source_ids)
    history = db.get_messages(conversation_id, limit=12) if conversation_id else []

    project_block = PROJECT_BLOCK.format(name=project["name"], brief=project.get("brief") or "(none)") if project else ""
    system = SYSTEM.format(web_rule=WEB_RULE_ON if use_web else WEB_RULE_OFF, project_block=project_block)

    context = build_context(hits) if hits else "(no relevant excerpts were found in the knowledge base)"
    messages: list[dict[str, Any]] = []
    for m in history:
        if m["role"] in ("user", "assistant") and m["content"]:
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({
        "role": "user",
        "content": f"<excerpts>\n{context}\n</excerpts>\n\nQuestion: {question}",
    })

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    kwargs: dict[str, Any] = dict(model=settings.answer_model, max_tokens=2000, system=system, messages=messages)
    if use_web:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]

    resp = client.messages.create(**kwargs)
    answer_parts: list[str] = []
    web_sources: list[dict[str, str]] = []
    web_used = False
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
    answer = "".join(answer_parts).strip()

    cited_nums = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", answer)})
    citations = []
    for n in cited_nums:
        if 1 <= n <= len(hits):
            h = hits[n - 1]
            citations.append({"n": n, **{k: h[k] for k in ("source_id", "title", "channel", "url", "link", "timestamp", "start", "end", "platform")},
                              "snippet": h["text"][:300]})

    if conversation_id:
        db.save_message(conversation_id, "user", question, project_id=project_id, title=question[:80])
        db.save_message(conversation_id, "assistant", answer, citations=citations, project_id=project_id)

    return {
        "answer": answer,
        "citations": citations,
        "hits": hits,
        "web_used": web_used,
        "web_sources": web_sources,
        "project": {"id": project["id"], "name": project["name"]} if project else None,
        "conversation_id": conversation_id,
    }


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
    return "\n".join(out)
