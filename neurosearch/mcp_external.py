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
    "Neuro does NOT need to be involved from the start. The user may talk with you normally and only later say things like "
    "'save this to Neuro', 'check this against Neuro', 'send our decision to Neuro'. Then:\n"
    "- SAVE: call sync_conversation_to_project with only the durable, project-relevant state from this conversation "
    "(decisions, reaffirmations, changes, constraints, requirements, rejected options, rationale, commitments, deadlines, "
    "counterpart positions, concerns, open questions, material the user shared and what you extracted from it, and your own "
    "analysis marked as analysis). Never send the transcript, drafts, or requests about wording/tone/format. On later saves "
    "in the same conversation send only what is new since the last one.\n"
    "- CHECK: first sync the new durable material the same way, then call consult_project, then answer using both.\n"
    "- PROJECT: if the user named a project, pass their words as project_hint with project_named_by_user=true. If you only "
    "infer it, pass project_hint alone: Neuro answers confirm_project and you ask the user. If Neuro answers needs_project, "
    "ask the user to choose. Never guess. Once confirmed, pass that project_id for the rest of this conversation.\n"
    "- EVIDENCE OF WHAT THE USER SAID: for every decision/constraint/commitment etc. you save as the user's, put the user's "
    "own words from the conversation in user_text (quote them). Without them Neuro saves it only as a suggestion. If the "
    "user says the same thing again later (e.g. 'we're STILL at 10%'), send it with their new words: Neuro records a "
    "reaffirmation. To change or withdraw something Neuro already holds, read it first (consult_project/open_project) and "
    "pass that ledger_cursor as base_revision; Neuro returns a conflict instead of overwriting blind.\n"
    "- Report the receipt's summary in one line; mention needs_attention only if it is not empty.\n"
    "When working inside a project from the start, open_project once, then read only when needed. Cite evidence only when "
    "asked why; use get_evidence to drill down."
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


@server.tool(annotations=WRITE)
async def link_account(code: str, ctx: Context, client_name: str | None = None) -> dict[str, Any]:
    """Use this ONLY when another Neuro tool answered `account_unlinked`: ask the user for the Neuro connection code
    they were given (it starts with nsi_) and pass it here once. It links their sign-in to their Neuro access."""
    secret = _secret(ctx)
    try:
        return await anyio.to_thread.run_sync(lambda: external.link_account(secret, code, client_name))
    except external.ExternalError as e:
        raise ToolError(json.dumps(e.body())) from None


@server.tool(annotations=READ)
async def list_projects(ctx: Context, query: str | None = None) -> dict[str, Any]:
    """The Neuro projects this person has been given, with their role and what they may see. Pass query (a project
    name or what the conversation is about) to get the best matches first."""
    return await _call(ctx, "list_projects", {"query": query})


@server.tool(annotations=WRITE, meta={"openai/fileParams": ["files"]})
async def sync_conversation_to_project(client_request_id: str, ctx: Context, project_id: str | None = None,
                                       project_hint: str | None = None, project_named_by_user: bool = False,
                                       state: list[dict[str, Any]] | None = None,
                                       materials: list[dict[str, Any]] | None = None, analysis: list[dict[str, Any]] | None = None,
                                       files: list[dict[str, Any]] | None = None, file_links: list[dict[str, Any]] | None = None,
                                       conversation_ref: str | None = None, base_revision: int | None = None,
                                       archive_transcript: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use this when the user asks to save/send/add what mattered in this conversation to Neuro, or before
    consult_project when they ask to check the conversation against Neuro. Works even if Neuro was never used earlier.
    project_id if known; otherwise project_hint (the project they named or the topic) — if the answer is needs_project,
    ask the user to pick from candidates and call again. client_request_id: one fresh id per save, reused on retry.
    state: [{op: record|reaffirm|supersede|propose|withdraw, kind: decision|constraint|requirement|rejected|commitment|
    deadline|counterpart_position|concern|open_question|context|preference, content, user_text (the user's own words,
    quoted — required for anything saved as the user's position), rationale?, fact_id?, scope?, explicitness?,
    referent?}] — 'propose' for anything you inferred rather than the user stated; 'personal' scope for one person's
    preference. project_named_by_user=true only when the user named the project themselves. Changing or withdrawing
    something Neuro already holds needs base_revision from a read; a conflict comes back otherwise — show it to the user. materials: what the user shared, as you read it (same shape as add_processed_material;
    set original_available=false if you can no longer pass the file). files: files uploaded earlier in this conversation
    (they are passed by reference); file_links: [{index into files, original_of_material: index into materials}] when a
    file is the original of something you already read — Neuro keeps it and does not read it again. analysis:
    [{text}] your own reasoning, stored as analysis, never as evidence. archive_transcript only if the user explicitly
    asked to archive the whole conversation ({text, explicit_user_request: true})."""
    links = {int(x.get("index", -1)): x.get("original_of_material") for x in (file_links or [])}
    refs = []
    for i, f in enumerate(files or []):
        ref = {k: v for k, v in {"kind": "signed_url", "url": str(f.get("download_url") or ""), "handle": f.get("file_id"), "filename": f.get("file_name"),
                                 "content_type": f.get("mime_type")}.items() if v}
        refs.append({"artifact_ref": ref, **({"original_of_material": links[i]} if links.get(i) is not None else {})})
    args = {"client_request_id": client_request_id, "project_id": project_id, "project_hint": project_hint,
            "project_named_by_user": project_named_by_user or None, "state": state,
            "materials": materials, "analysis": analysis, "files": refs or None, "conversation_ref": conversation_ref,
            "base_revision": base_revision, "archive_transcript": archive_transcript}
    return await _call(ctx, "sync_conversation_to_project", args)


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


# ------------------------------------------------------------------ writes (the contributor's own words and material)

@server.tool(annotations=WRITE)
async def sync_project_state(project_id: str, changes: list[dict[str, Any]], ctx: Context, base_revision: int | None = None) -> dict[str, Any]:
    """Record what the user made DURABLE in this turn. Each change: {op, kind, content, fact_id, rationale, explicitness,
    scope, referent, disclosure_class, client_request_id}.
    op: record (an explicit statement: "We're staying at 10%") · reaffirm (fact_id; "we're STILL at 10%") · supersede
    (fact_id + new content; "change it to 7.5%") · propose (something you inferred; stays reviewable) · withdraw.
    kind: decision · constraint · requirement · rejected · commitment · preference · context.
    scope: personal for one person's preference ("I personally prefer…"), project for the shared position.
    explicitness: explicit, or accepted_recommendation WITH referent = the ONE proposal the user said yes to.
    Never record tone/format/drafting requests. user_text: the user's own words for this change, quoted — required for
    reaffirm/supersede/withdraw, and without it a record is saved only as a suggestion. Pass base_revision = the
    ledger_cursor you last saw; a conflict comes back instead of overwriting a collaborator. client_request_id: a fresh
    unique id per change, reused on retry."""
    return await _call(ctx, "sync_project_state", {"project_id": project_id, "changes": changes, "base_revision": base_revision})


@server.tool(annotations=WRITE)
async def create_intake(project_id: str, client_request_id: str, ctx: Context, base_revision: int | None = None,
                        conversation_ref: str | None = None) -> dict[str, Any]:
    """Start one intake for material the user shared in this turn (a screenshot, PDF, email, spreadsheet, recording…).
    Reuse the same client_request_id on retry. Then add each item, then finalize."""
    return await _call(ctx, "create_intake", {"project_id": project_id, "client_request_id": client_request_id,
                                              "base_revision": base_revision, "conversation_ref": conversation_ref})


@server.tool(annotations=WRITE)
async def add_processed_material(project_id: str, intake_id: str, material: dict[str, Any], ctx: Context,
                                 item_request_id: str | None = None) -> dict[str, Any]:
    """Give Neuro what YOU already read, so Neuro never reads it again: material = {material_type (image|pdf|url|
    correspondence|spreadsheet|transcript|text), title, producer (your client's name), extraction_method (vision|ocr|
    pdf_text|html|asr|table|manual|other), units: [{locator ("p. 3", "00:12:34", "sheet!A1", "msg:<id>"), text,
    speaker?, start?, end?, confidence?}], correspondence?, table?, canonical_url?, confidence?, language?,
    client_declared_class? (standard|correspondence|financial|tax|identity|restricted — say how sensitive it is)}.
    Put only what the material SAYS here; your interpretation goes to finalize_intake as an interpretation."""
    return await _call(ctx, "add_processed_material", {"project_id": project_id, "intake_id": intake_id, "material": material,
                                                       "item_request_id": item_request_id})


@server.tool(annotations=WRITE)
async def attach_artifact(project_id: str, intake_id: str, artifact_ref: dict[str, Any], ctx: Context, item_id: str | None = None,
                          client_declared_class: str | None = None, item_request_id: str | None = None) -> dict[str, Any]:
    """Attach the ORIGINAL file by reference ({kind: signed_url, url, filename?, sha256?}). With item_id it is kept as
    the original of material you already processed (Neuro does not read it again); without it Neuro reads it itself."""
    return await _call(ctx, "attach_artifact", {"project_id": project_id, "intake_id": intake_id, "artifact_ref": artifact_ref,
                                                "item_id": item_id, "client_declared_class": client_declared_class,
                                                "item_request_id": item_request_id})


@server.tool(annotations=WRITE, meta={"openai/fileParams": ["file"]})
async def attach_file(project_id: str, intake_id: str, file: dict[str, Any], ctx: Context, item_id: str | None = None,
                      client_declared_class: str | None = None, item_request_id: str | None = None) -> dict[str, Any]:
    """Attach a file the user uploaded in this conversation (file = {download_url, file_id, mime_type?, file_name?}).
    Use item_id when you already processed the file with add_processed_material: Neuro then keeps it as the original
    and does NOT read it again. Without item_id, Neuro reads it itself."""
    ref = {k: v for k, v in {"kind": "signed_url", "url": str(file.get("download_url") or ""), "handle": file.get("file_id"),
                              "filename": file.get("file_name") or "attachment", "content_type": file.get("mime_type")}.items() if v}
    return await _call(ctx, "attach_artifact", {"project_id": project_id, "intake_id": intake_id, "artifact_ref": ref,
                                                "item_id": item_id, "client_declared_class": client_declared_class,
                                                "item_request_id": item_request_id})


@server.tool(annotations=WRITE)
async def finalize_intake(project_id: str, intake_id: str, ctx: Context, user_state: list[dict[str, Any]] | None = None,
                          interpretations: list[dict[str, Any]] | None = None, base_revision: int | None = None) -> dict[str, Any]:
    """Close the intake. user_state: the same change objects as sync_project_state, for durable things the user said
    about this material. interpretations: [{text, about_item_id?}] — YOUR reading, stored as interpretation, never as evidence."""
    return await _call(ctx, "finalize_intake", {"project_id": project_id, "intake_id": intake_id, "user_state": user_state,
                                                "interpretations": interpretations, "base_revision": base_revision})


@server.tool(annotations=READ)
async def get_intake_status(project_id: str, intake_id: str, ctx: Context) -> dict[str, Any]:
    """Where an intake is: received → queued → processing → ready, or needs_review with the reason."""
    return await _call(ctx, "get_intake_status", {"project_id": project_id, "intake_id": intake_id})


def app():
    from mcp.server.transport_security import TransportSecuritySettings
    return server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
