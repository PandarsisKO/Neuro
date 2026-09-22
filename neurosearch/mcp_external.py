"""P11 EA-3/EA-7 — the external MCP adapter (EXTERNAL-AI-ACCESS-MISSION.md §39, §55–§59; plan §3).

A thin adapter over `external.call`: every tool authenticates the caller's own credential from THIS message's
headers (`Authorization: Bearer nsx_…`), so one server instance serves Kyle's and Gio's clients without either
ever acting as the other. It is a separate server from `mcp_server.py` (the legacy local tools, which stay as they
are); it is mounted at `/ext/mcp`, deliberately outside `/mcp*`, whose middleware accepts only the local token.

Tool descriptions carry the read/write rules (§29, §59) because the client model decides per turn whether to call.
Nothing here names a vendor.
"""
from __future__ import annotations

import json
from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import external

INSTRUCTIONS = (
    "Neuro is this person's durable project memory: sources, evidence, Claims, decisions, constraints, open questions, "
    "watch-outs, plan state and their history. You handle the live conversation; Neuro remembers what it means to the project.\n"
    "READ from Neuro only when this turn needs durable project knowledge that is not already in this conversation "
    "(orientation, past decisions, research/evidence, comparing new material to the project, risks, open questions, "
    "plan implications, or when Neuro has changed). Do NOT call Neuro to draft, rewrite, shorten, change tone, format, "
    "translate or turn content into an email — continue locally.\n"
    "WRITE to Neuro when the user states something durable: an explicit decision, a changed decision, a constraint, a "
    "requirement, a rejected option, a commitment, or a fact; or shares material the project should keep. Record your "
    "own interpretation separately as an interpretation, never as evidence. Never infer someone else's agreement. "
    "If the user answers 'yes/agreed' to a list of several proposals, ask which one before recording anything.\n"
    "Start with open_project once per conversation. Cite evidence only when asked why; use get_evidence to drill down."
)

server = MCPServer("Neuro (external)", instructions=INSTRUCTIONS)
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _secret(ctx: Context) -> str | None:
    h = (ctx.headers or {}).get("authorization") or (ctx.headers or {}).get("Authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else None


async def _call(ctx: Context, op: str, args: dict[str, Any]) -> dict[str, Any]:
    secret = _secret(ctx)
    try:
        return await anyio.to_thread.run_sync(lambda: external.call(secret, op, {k: v for k, v in args.items() if v is not None}))
    except external.ExternalError as e:
        raise ToolError(json.dumps(e.body())) from None     # deliberate: the model sees the code and message


@server.tool(annotations=READ)
async def list_projects(ctx: Context) -> dict[str, Any]:
    """The Neuro projects this person has been given, with their role and what they may see."""
    return await _call(ctx, "list_projects", {})


@server.tool(annotations=READ)
async def open_project(project_id: str, ctx: Context, client_capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    """Orient on one project in a single call: current decisions and constraints, open questions, watch-outs, the stored
    plan, counts, and the ledger cursor to pass back later. Call once at the start of a project conversation.
    client_capabilities: what YOU can do (vision, ocr, pdf_text, table_extraction, web_access, transcription,
    diarization, read_tools, write_tools, file_transport) so Neuro tells you which intake path to use."""
    return await _call(ctx, "open_project", {"project_id": project_id, "client_capabilities": client_capabilities})


@server.tool(annotations=READ)
async def get_project_changes(project_id: str, ctx: Context, since_cursor: int = 0, limit: int = 50,
                              min_materiality: str | None = None) -> dict[str, Any]:
    """What Neuro learned differently since `since_cursor` (the ledger_cursor from an earlier response): changed Claims,
    decisions, questions, watch-outs — impact-ordered, with who changed them. Maintenance that changed nothing is only counted."""
    return await _call(ctx, "get_project_changes", {"project_id": project_id, "since_cursor": since_cursor, "limit": limit,
                                                    "min_materiality": min_materiality})


@server.tool(annotations=READ)
async def search_project(project_id: str, query: str, ctx: Context, limit: int = 10, kinds: list[str] | None = None) -> dict[str, Any]:
    """Search this project's sources, Claims and recorded decisions/facts. kinds: any of chunk, claim, fact."""
    return await _call(ctx, "search_project", {"project_id": project_id, "query": query, "limit": limit, "kinds": kinds})


@server.tool(annotations=READ)
async def get_evidence(project_id: str, ctx: Context, claim_id: str | None = None, source_id: str | None = None,
                       fact_id: int | None = None, start: float | None = None, depth: str = "summary") -> dict[str, Any]:
    """Drill down only when the user asks why or wants proof. depth: summary → excerpt → exact (locator, page, timestamp, link)."""
    ref = {k: v for k, v in {"claim_id": claim_id, "source_id": source_id, "fact_id": fact_id, "start": start}.items() if v is not None}
    return await _call(ctx, "get_evidence", {"project_id": project_id, "ref": ref, "depth": depth})


@server.tool(annotations=READ)
async def consult_project(project_id: str, question: str, ctx: Context, since_cursor: int | None = None,
                          claim_ids: list[str] | None = None) -> dict[str, Any]:
    """The project's stored intelligence for ONE substantive question: current position, constraints, relevant Claims and
    watch-outs, plan implications, unresolved questions, available evidence. Neuro does not answer; you reason over it.
    Pass since_cursor to also get what changed since you last looked."""
    return await _call(ctx, "consult_project", {"project_id": project_id, "question": question, "since_cursor": since_cursor,
                                                "focus": {"claim_ids": claim_ids} if claim_ids else None})


def app():
    from mcp.server.transport_security import TransportSecuritySettings
    return server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
