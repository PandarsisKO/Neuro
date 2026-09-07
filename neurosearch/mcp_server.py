"""MCP server exposing the knowledge base to Claude (desktop, mobile, Claude Code).

Mounted by api.py at /mcp. Tools return markdown-ish text that Claude can relay with citations.
"""
from __future__ import annotations

import json
from typing import Any

import anyio
from mcp.server import MCPServer

from . import db, jobs, qa
from .chunking import fmt_ts
from .search import search, source_transcript

mcp = MCPServer(
    "Neuro Search",
    instructions=(
        "Neuro Search is the user's personal knowledge base of video/podcast transcripts. "
        "Use search_knowledge for raw excerpts with timestamps, or ask for a synthesized answer with citations. "
        "Always keep the [Title @ timestamp](link) citations so the user can jump to the exact moment. "
        "Scope questions to a project when the user names one (list_projects shows them)."
    ),
)


def _resolve_project(project: str | None) -> dict[str, Any] | None:
    if not project:
        return None
    p = db.find_project(project)
    if not p:
        raise ValueError(f"no project named or with id '{project}'. Use list_projects.")
    return p


def _fmt_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "No matching excerpts."
    out = []
    for i, h in enumerate(hits, 1):
        out.append(f"[{i}] {h['title']} @ {h['timestamp']} ({h['link']})\n{h['text']}")
    return "\n\n".join(out)


@mcp.tool()
async def search_knowledge(query: str, project: str | None = None, limit: int = 10) -> str:
    """Search transcript excerpts (keyword + semantic). Returns numbered excerpts with title, timestamp and deep link.
    `project` may be a project name or id to restrict the search."""
    p = _resolve_project(project)
    sids = (p["source_ids"] or ["__none__"]) if p else None
    hits = await anyio.to_thread.run_sync(lambda: search(query, limit=limit, source_ids=sids))
    return _fmt_hits(hits)


@mcp.tool()
async def ask(question: str, project: str | None = None, use_web: bool = False, conversation_id: str | None = None) -> str:
    """Ask a question and get a synthesized answer with [n] citations resolved to source titles, timestamps and links.
    Set use_web=true to let the answer also draw on live web search (clearly labelled). Pass the same conversation_id
    across turns to keep context."""
    p = _resolve_project(project)
    res = await anyio.to_thread.run_sync(
        lambda: qa.ask(question, project_id=p["id"] if p else None, use_web=use_web, conversation_id=conversation_id)
    )
    return qa.render_markdown(res)


@mcp.tool()
def list_projects() -> str:
    """List research projects (topic groupings of sources) with their briefs and source counts."""
    ps = db.list_projects()
    if not ps:
        return "No projects yet. Create one with create_project."
    return "\n".join(f"- {p['name']} (id {p['id']}, {p['n_sources']} sources): {p.get('brief') or ''}" for p in ps)


@mcp.tool()
def create_project(name: str, brief: str | None = None, tags: list[str] | None = None) -> str:
    """Create a project. `brief` describes what you're trying to find out and guides answers.
    `tags`: any source carrying one of these tags is automatically part of the project."""
    p = db.create_project(name, brief, tags)
    return f"Created project '{p['name']}' (id {p['id']})."


@mcp.tool()
def add_to_project(project: str, source_ids: list[str] | None = None, collection_ids: list[str] | None = None) -> str:
    """Add sources and/or collections (playlists/channels) to a project by id."""
    p = _resolve_project(project)
    assert p
    if source_ids:
        from . import identity
        for sid in source_ids:
            identity.attach_existing(p["id"], sid)          # G1: attach + reuse + project-relative analysis, never a re-acquire
    if collection_ids:
        db.add_project_collections(p["id"], collection_ids)
    p = db.get_project(p["id"])
    return f"Project '{p['name']}' now has {p['n_sources']} sources."  # type: ignore[index]


@mcp.tool()
def list_sources(project: str | None = None, query: str | None = None, limit: int = 100) -> str:
    """List ingested sources (videos/podcasts), optionally filtered to a project or by title/channel text."""
    p = _resolve_project(project)
    if p:
        ids = set(p["source_ids"])
        rows = [s for s in db.list_sources(query=query, limit=5000) if s["id"] in ids][:limit]
    else:
        rows = db.list_sources(query=query, limit=limit)
    if not rows:
        return "No sources."
    return "\n".join(
        f"- {s['title']} — {s.get('channel') or s['platform']} ({s.get('published_at') or 'n/a'}, "
        f"{fmt_ts(s['duration'] or 0)}) [{s['status']}] id={s['id']} {s['url']}" for s in rows
    )


@mcp.tool()
def list_collections() -> str:
    """List playlists/channels that have been ingested, with ids (use with add_to_project)."""
    cs = db.list_collections()
    return "\n".join(f"- {c['title']} ({c['kind']}, {c['n_sources']} sources) id={c['id']}" for c in cs) or "No collections."


@mcp.tool()
def get_transcript(source_id: str, start: float | None = None, end: float | None = None) -> str:
    """Read a source's transcript with [m:ss] timestamps. Optionally limit to a time window in seconds."""
    src = db.get_source(source_id)
    if not src:
        return "Unknown source id."
    segs = db.get_segments(source_id)
    if start is not None or end is not None:
        s0, e0 = start or 0, end or float("inf")
        segs = [s for s in segs if s["end"] >= s0 and s["start"] <= e0]
    body = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs)
    return f"{src['title']} — {src['url']}\n\n{body[:60000]}"


@mcp.tool()
def ingest(url: str, project: str | None = None, tags: list[str] | None = None) -> str:
    """Queue a video, playlist, channel, podcast episode, Instagram reel or audio URL for ingestion.
    Playlists/channels fan out into one job per video. Returns the job id; check with job_status."""
    p = _resolve_project(project)
    job = jobs.enqueue("ingest_url", {"url": url, "tags": tags or [], "project_id": p["id"] if p else None})
    return f"Queued job {job['id']} for {url}."


@mcp.tool()
def job_status(job_id: str | None = None) -> str:
    """Status of one job, or the latest jobs plus overall knowledge-base stats."""
    if job_id:
        j = db.get_job(job_id)
        return json.dumps(j, indent=1, default=str) if j else "Unknown job."
    stats = db.source_stats()
    recent = db.list_jobs(limit=10)
    lines = [f"Stats: {json.dumps(stats)}", "Recent jobs:"]
    for j in recent:
        lines.append(f"- {j['id'][:8]} {j['kind']} {j['status']} {int(j['progress'] * 100)}% {j.get('message') or ''}")
    return "\n".join(lines)


@mcp.tool()
def findings(project: str) -> str:
    """The project's findings document: brief, every pinned finding and gap with timestamp links, source list."""
    from .export import findings_markdown

    p = _resolve_project(project)
    assert p
    return findings_markdown(p["id"])


@mcp.tool()
async def masterplan(project: str) -> str:
    """Write the project's masterplan (Claude-synthesized: purpose, summary, insights with citations, actions,
    open questions). The web app can download the full portable package (zip with transcripts) at
    /api/projects/<id>/masterplan.zip."""
    from .export import synthesize_masterplan

    p = _resolve_project(project)
    assert p
    return await anyio.to_thread.run_sync(lambda: synthesize_masterplan(p["id"]))


@mcp.tool()
async def build_master_plan(project: str, instructions: str | None = None) -> str:
    """Build (or rebuild) the project's Master Plan — an actionable, evidence-grounded plan: goal, recommended
    approach, first steps, phases, dependencies, decisions, tools, costs, risks, gotchas, what to defer, open
    questions, confidence, ready-to-start. Returns it as markdown."""
    from . import planner

    p = _resolve_project(project)
    assert p
    row = await anyio.to_thread.run_sync(lambda: planner.build_plan(p["id"], instructions))
    return planner.plan_markdown(row, db.get_project(p["id"]) or p)


@mcp.tool()
def get_master_plan(project: str) -> str:
    """The project's current Master Plan as markdown (with item statuses), or a note that none exists yet."""
    from . import planner

    p = _resolve_project(project)
    assert p
    row = db.latest_plan(p["id"])
    if not row:
        return "No Master Plan yet — call build_master_plan."
    return planner.plan_markdown(row, p)


@mcp.tool()
def record_fact(project: str, kind: str, content: str) -> str:
    """Record a decision, constraint, requirement or rejected option on the project (used by the Master Planner)."""
    p = _resolve_project(project)
    assert p
    db.add_fact(p["id"], kind, content)
    return "Recorded."


@mcp.tool()
def update_brief(project: str, brief: str) -> str:
    """Replace a project's brief (what it is trying to find out)."""
    p = _resolve_project(project)
    assert p
    db.update_project(p["id"], brief=brief)
    return "Brief updated."


@mcp.tool()
def save_note(project: str, content: str) -> str:
    """Pin a finding to a project's notes so it shows up in the project view."""
    p = _resolve_project(project)
    assert p
    db.add_project_note(p["id"], content)
    return "Saved."
