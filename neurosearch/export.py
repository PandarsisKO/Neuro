"""Project exports: findings document and the portable "masterplan" package.

The masterplan zip is designed to be dropped into another AI tool (ChatGPT, Claude, NotebookLM, …):
  README.md            how to use the package + a ready-made prompt
  masterplan.md        Claude-written synthesis: purpose, summary, insights w/ citations, actions, open questions
  findings.md          brief + every pinned finding and gap, with timestamp links
  sources.csv          one row per source (title, channel, date, url, duration)
  conversations.md     the Q&A history for the project
  transcripts/*.md     full timestamped transcripts, one file per source
  context.json         everything above, machine-readable
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from datetime import date
from typing import Any

from . import db
from .chunking import fmt_locator, fmt_ts
from .config import settings
from .search import deep_link

log = logging.getLogger(__name__)


def _safe(name: str, n: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9 _.-]+", "", name or "untitled").strip()[:n] or "untitled"


def _sources(project_id: str) -> list[dict[str, Any]]:
    ids = set(db.project_source_ids(project_id))
    return [s for s in db.list_sources(limit=100000) if s["id"] in ids]


def _cite_line(c: dict[str, Any]) -> str:
    return f"[{c['title']} @ {c['timestamp']}]({c['link']})"


def findings_markdown(project_id: str) -> str:
    p = db.get_project(project_id)
    if not p:
        raise RuntimeError("project not found")
    notes = db.list_project_notes(project_id)
    findings = [n for n in notes if not n["content"].startswith("Gap:")]
    gaps = [n for n in notes if n["content"].startswith("Gap:")]
    srcs = _sources(project_id)
    out = [f"# {p['name']} — findings", f"_Exported {date.today().isoformat()} · {len(srcs)} sources · {len(findings)} findings_", ""]
    out += ["## Brief", p.get("brief") or "(none)", ""]
    out.append("## Findings")
    if not findings:
        out.append("(no findings pinned yet — pin answers from the Ask tab or ask the assistant to save a finding)")
    for i, n in enumerate(reversed(findings), 1):
        out.append(f"### {i}. {n['content'].splitlines()[0][:90]}")
        out.append(n["content"])
        cites = n.get("citations") or []
        if cites:
            out.append("")
            out.append("Sources: " + " · ".join(_cite_line(c) for c in cites))
        out.append("")
    if gaps:
        out.append("## Open gaps")
        out += [f"- {g['content'][4:].strip()}" for g in reversed(gaps)]
        out.append("")
    out.append("## Sources")
    for s in srcs:
        out.append(f"- [{s['title']}]({s['url']}) — {s.get('channel') or s['platform']}, {s.get('published_at') or 'n/a'}, {fmt_ts(s['duration'] or 0)}")
    return "\n".join(out)


def conversations_markdown(project_id: str) -> str:
    out = []
    for c in db.list_conversations(project_id, limit=200):
        msgs = db.get_messages(c["id"], limit=500)
        if not msgs:
            continue
        out.append(f"## {c.get('title') or c['id'][:8]}")
        for m in msgs:
            if m["role"] == "user":
                out.append(f"**Q:** {m['content']}")
            else:
                out.append(f"**A:** {m['content']}")
                if m.get("citations"):
                    out.append("Sources: " + " · ".join(_cite_line(x) for x in m["citations"]))
            out.append("")
    return "\n".join(out) or "(no conversations yet)"


def transcript_markdown(source: dict[str, Any]) -> str:
    segs = db.get_segments(source["id"])
    head = [f"# {source['title']}", f"- Channel: {source.get('channel') or ''}", f"- Published: {source.get('published_at') or ''}",
            f"- URL: {source['url']}", f"- Duration: {fmt_ts(source['duration'] or 0)}", ""]
    body = [f"[{fmt_locator(source['platform'], s['start'])}]({deep_link(source['url'], source['platform'], s['start'])}) {s['text']}" for s in segs]
    return "\n".join(head + body)


def sources_csv(srcs: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["title", "channel", "platform", "published", "duration", "url", "tags", "transcript_file"])
    for i, s in enumerate(srcs, 1):
        w.writerow([s["title"], s.get("channel"), s["platform"], s.get("published_at"), fmt_ts(s["duration"] or 0), s["url"],
                    ",".join(s.get("tags") or []), f"transcripts/{i:03d} - {_safe(s['title'])}.md"])
    return buf.getvalue()


MASTERPLAN_SYSTEM = """You write a research "masterplan": a self-contained document that lets another person or AI tool pick
up this project with full context. Write in clear prose with headings. Preserve every markdown citation link you are
given verbatim, e.g. [Title @ 12:34](https://...). Never invent facts not present in the material. Structure:

# <Project name> — Masterplan
## Purpose  (what the project is trying to find out, from the brief)
## Executive summary  (5-10 sentences)
## Key insights  (grouped by theme; each insight with its citations)
## Recommended actions / how to use these insights
## Open questions and gaps
## How to continue  (what sources to add next, questions worth asking)
"""


def synthesize_masterplan(project_id: str) -> str:
    """Ask Claude to write the masterplan narrative from the brief, findings and Q&A history."""
    p = db.get_project(project_id)
    if not p:
        raise RuntimeError("project not found")
    if not settings.anthropic_api_key:
        return _fallback_masterplan(p)
    import anthropic

    material = ["<brief>", p.get("brief") or "(none)", "</brief>", "<findings>"]
    for n in reversed(db.list_project_notes(project_id)):
        cites = " ".join(_cite_line(c) for c in (n.get("citations") or []))
        material.append(f"- {n['content']}\n  {cites}".strip())
    material.append("</findings>\n<qa_history>")
    budget = 60000
    for c in db.list_conversations(project_id, limit=50):
        for m in db.get_messages(c["id"], limit=200):
            if budget <= 0:
                break
            line = f"{'Q' if m['role'] == 'user' else 'A'}: {m['content'][:2500]}"
            if m["role"] == "assistant" and m.get("citations"):
                line += "\n   " + " ".join(_cite_line(x) for x in m["citations"])
            material.append(line)
            budget -= len(line)
    material.append("</qa_history>\n<sources>")
    material += [f"- {s['title']} — {s.get('channel') or ''} ({s.get('published_at') or ''}) {s['url']}" for s in _sources(project_id)]
    material.append("</sources>")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.answer_model, max_tokens=6000, system=MASTERPLAN_SYSTEM,
        messages=[{"role": "user", "content": f"Project name: {p['name']}\n\n" + "\n".join(material) + "\n\nWrite the masterplan now."}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    return text or _fallback_masterplan(p)


def _fallback_masterplan(p: dict[str, Any]) -> str:
    return f"# {p['name']} — Masterplan\n\n(Set ANTHROPIC_API_KEY to generate the synthesized narrative. See findings.md.)\n"


README = """# {name} — research package

Exported from Neuro Search on {today}. This folder contains everything another AI tool or collaborator needs to
continue the research: the synthesized masterplan, every pinned finding with timestamped video links, the full
transcripts, and the question/answer history.

## Files
- masterplan.md — start here. Purpose, summary, key insights with citations, actions, open questions.
- findings.md — the brief plus every pinned finding and gap, each with [Title @ mm:ss](link) citations.
- conversations.md — the Q&A history.
- sources.csv — one row per source with URL and the transcript file name.
- transcripts/ — full timestamped transcripts, one markdown file per source.
- context.json — the same content, machine-readable.

## Using it with ChatGPT / Claude / NotebookLM
Upload masterplan.md and findings.md (add transcripts/ if the tool accepts many files), then start with:

> You are continuing a research project. masterplan.md is the current state of the work and findings.md
> holds the evidence with links to the exact moments in the source videos. Treat these as the ground truth and
> cite them with the same [Title @ mm:ss](link) format whenever you use them. The brief describes what I am
> trying to find out. First, summarise what you understand the project to be and list the open questions;
> then wait for my next instruction.
"""


def build_masterplan_zip(project_id: str, synthesize: bool = True) -> bytes:
    p = db.get_project(project_id)
    if not p:
        raise RuntimeError("project not found")
    srcs = _sources(project_id)
    findings = findings_markdown(project_id)
    convs = conversations_markdown(project_id)
    plan = synthesize_masterplan(project_id) if synthesize else _fallback_masterplan(p)
    notes = db.list_project_notes(project_id)
    ctx = {
        "project": {"name": p["name"], "brief": p.get("brief"), "exported": date.today().isoformat()},
        "findings": [{"content": n["content"], "citations": n.get("citations") or [], "created_at": n["created_at"]} for n in notes],
        "sources": [{k: s.get(k) for k in ("id", "title", "channel", "platform", "published_at", "duration", "url", "tags")} for s in srcs],
        "conversations": [{"title": c.get("title"), "messages": db.get_messages(c["id"], limit=500)} for c in db.list_conversations(project_id, limit=200)],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", README.format(name=p["name"], today=date.today().isoformat()))
        z.writestr("masterplan.md", plan)
        z.writestr("findings.md", findings)
        z.writestr("conversations.md", f"# {p['name']} — conversations\n\n" + convs)
        z.writestr("sources.csv", sources_csv(srcs))
        z.writestr("context.json", json.dumps(ctx, indent=1, default=str))
        for i, s in enumerate(srcs, 1):
            z.writestr(f"transcripts/{i:03d} - {_safe(s['title'])}.md", transcript_markdown(s))
    return buf.getvalue()
