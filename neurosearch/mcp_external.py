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

from pydantic import BaseModel, ConfigDict

from . import external
from .external_schemas import CAPABILITIES, FILE_TRANSPORTS


class FileParam(BaseModel):
    """A file the user attached in this conversation, as ChatGPT delivers it.

    OpenAI's file-parameter contract (developers.openai.com/plugins/reference, "openai/fileParams"): the parameter must
    be an object declaring exactly download_url, file_id, mime_type and file_name, with only the first two required.
    ChatGPT only turns an attachment into {download_url, file_id} for a parameter published in that exact shape.
    Observed live 2026-09-22: while `file`/`files` were generic objects, ChatGPT showed its model a plain string and
    sent Neuro a bare "file_…" id with no download_url, so the original could never be kept.
    """
    model_config = ConfigDict(extra="ignore")
    download_url: str
    file_id: str
    mime_type: str = ""
    file_name: str = ""


def _file_dict(f: Any) -> dict[str, Any]:
    return f.model_dump() if isinstance(f, BaseModel) else dict(f or {})


def _caps(c: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept the capability shapes real clients send. Observed live 2026-09-22: ChatGPT's first open_project sent
    `file_transport: true`, which the strict v1 schema refused as "not of type 'array'". A yes/no is read as "can pass
    files by signed URL" (true) or "cannot pass files" (false); unknown keys are dropped rather than failing the read."""
    if not isinstance(c, dict):
        return None
    out: dict[str, Any] = {}
    for k, v in c.items():
        if k == "file_transport":
            if isinstance(v, bool):
                out[k] = ["signed_url"] if v else ["none"]
            elif isinstance(v, str):
                out[k] = [v] if v in FILE_TRANSPORTS else []
            elif isinstance(v, list):
                out[k] = [x for x in v if x in FILE_TRANSPORTS][:4]
        elif k in CAPABILITIES:
            out[k] = v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")
    return out

INSTRUCTIONS = (
    # Descriptive, not directive (2026-09-22): ChatGPT flagged the earlier imperative wording ("READ ... only when",
    # "Do NOT", "Never guess") as "Suspicious Instruction" on every write. The rules below are enforced by Neuro's
    # server regardless of wording; this text only explains the interface.
    "Neuro is the user's project memory: sources, evidence, Claims, decisions, constraints, open questions, watch-outs and plan state, with their history. The conversation happens in the client; Neuro keeps what it means for a project.\n"
    'Reading is useful for orientation, past decisions, research and evidence, comparing new material with a project, risks, open questions and plan implications. Drafting, rewriting, formatting or translating do not involve Neuro.\n'
    "Writing records what the user made durable: a decision or a change to one, a constraint, requirement, rejected option, commitment, deadline or fact, and material the project should keep. The client's own reading is stored as analysis or interpretation, separate from evidence.\n"
    "Neuro can join late. When the user says 'save this to Neuro' or 'check this against Neuro', sync_conversation_to_project takes the durable, project-relevant parts of the conversation (not the transcript or drafts); consult_project then answers questions against the updated project.\n"
    "Project choice: project_selection.basis is user_named (with the user's words) or previously_confirmed (same conversation_ref). An inferred project is not saved to: Neuro replies confirm_project or needs_project with candidates for the user to pick from.\n"
    "The user's own words: user_text holds the quoted words behind a decision or constraint. A change without them is stored as a suggestion for the owner to review. reaffirm is for a deliberate re-commitment to a fact Neuro already holds.\n"
    'Changing an existing decision: if the project already holds decisions of that kind and none was read in this conversation, Neuro replies needs_current_state with them and a base_revision; the resend says whether the new one supersedes one (fact_id) or stands beside them. Neuro does not overwrite without that.\n'
    'Each save returns a one-line receipt; needs_attention lists anything held.\n'
    'open_project orients on a project in one call; get_evidence drills down to the exact source when the user asks why.'
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
    """Links this sign-in to the user's Neuro access using a one-time connection code (starts with nsi_), for
    clients that can pass one. Relevant only after another tool returned account_unlinked; in ChatGPT the owner
    approves the sign-in in Neuro instead."""
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
                                       project_hint: str | None = None, project_selection: dict[str, Any] | None = None,
                                       state: list[dict[str, Any]] | None = None,
                                       materials: list[dict[str, Any]] | None = None, analysis: list[dict[str, Any]] | None = None,
                                       files: list[FileParam] | None = None, file_links: list[dict[str, Any]] | None = None,
                                       conversation_ref: str | None = None, base_revision: int | None = None,
                                       archive_transcript: dict[str, Any] | None = None) -> dict[str, Any]:
    """Saves the durable, project-relevant state of this conversation to a Neuro project — for "save this to
    Neuro", "send our decision to Neuro", or before consult_project when checking the conversation against a project.
    Works even when Neuro was not used earlier in the conversation.
    project_id when known, otherwise project_hint (a project name or topic); needs_project returns candidates.
    project_selection: {basis: user_named (user_text = the user's words naming or accepting the project) |
    previously_confirmed (a project confirmed earlier in this conversation, same conversation_ref) | inferred}.
    Only user_named and previously_confirmed save; inferred returns confirm_project.
    client_request_id: one id per save, reused on retry.
    state: [{op: record|reaffirm|supersede|propose|withdraw, kind: decision|constraint|requirement|rejected|commitment|
    deadline|counterpart_position|concern|open_question|context|preference, content, user_text (the user's own words,
    quoted; a record without them is stored as a suggestion), rationale?, fact_id?, scope? (personal|project),
    explicitness?, referent?}]. propose = something inferred rather than stated.
    If the project already holds decisions or constraints of that kind, base_revision from a read is required;
    otherwise the reply is needs_current_state with what Neuro holds.
    materials: what the user shared, as already read (same shape as add_processed_material; original_available=false
    when the file can no longer be passed). files: files attached earlier in this conversation. file_links: [{index
    into files, original_of_material: index into materials}] marks a file as the original of material already read, so
    Neuro keeps it without reading it again. analysis: [{text}] the client's own reasoning, stored as analysis.
    archive_transcript: {text, explicit_user_request: true}, only when the user asked to archive the conversation."""
    links = {int(x.get("index", -1)): x.get("original_of_material") for x in (file_links or [])}
    refs = []
    for i, f in enumerate(files or []):
        f = _file_dict(f)
        ref = {k: v for k, v in {"kind": "signed_url", "url": str(f.get("download_url") or ""), "handle": f.get("file_id"), "filename": f.get("file_name"),
                                 "content_type": f.get("mime_type")}.items() if v}
        refs.append({"artifact_ref": ref, **({"original_of_material": links[i]} if links.get(i) is not None else {})})
    args = {"client_request_id": client_request_id, "project_id": project_id, "project_hint": project_hint,
            "project_selection": project_selection, "state": state,
            "materials": materials, "analysis": analysis, "files": refs or None, "conversation_ref": conversation_ref,
            "base_revision": base_revision, "archive_transcript": archive_transcript}
    return await _call(ctx, "sync_conversation_to_project", args)


@server.tool(annotations=READ)
async def open_project(project_id: str, ctx: Context, client_capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    """Orient on one project in a single call: current decisions and constraints, open questions, watch-outs, the stored
    plan, counts, and the ledger cursor to pass back later. Call once at the start of a project conversation.
    client_capabilities: what the client can do (vision, ocr, pdf_text, table_extraction, web_access, transcription,
    diarization, read_tools, write_tools, file_transport) so Neuro can suggest the intake path."""
    return await _call(ctx, "open_project", {"project_id": project_id, "client_capabilities": _caps(client_capabilities)})


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
    """The exact support behind a Claim or source, for when the user asks why or wants proof.
    depth: summary → excerpt → exact (locator, page, timestamp, link)."""
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
    """Records durable changes the user made in this turn. Each change: {op, kind, content, fact_id, rationale,
    explicitness, scope, referent, disclosure_class, client_request_id, user_text}.
    op: record (an explicit statement: "We're staying at 10%") · reaffirm (fact_id; "we're still at 10%") · supersede
    (fact_id + new content; "change it to 7.5%") · propose (inferred; stays reviewable) · withdraw.
    kind: decision · constraint · requirement · rejected · commitment · preference · context.
    scope: personal (one person's preference) or project (the shared position).
    explicitness: explicit, or accepted_recommendation with referent = the one proposal the user accepted.
    user_text: the user's own words, quoted — required for reaffirm/supersede/withdraw; a record without them is stored
    as a suggestion. Tone, format and drafting requests are not project state.
    base_revision: the ledger_cursor last seen; a conflicting change comes back instead of overwriting a collaborator.
    client_request_id: one id per change, reused on retry."""
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
    """Material the client already read, so Neuro does not read it again: material = {material_type
    (image|pdf|url|correspondence|spreadsheet|transcript|text), title, producer (the client's name), extraction_method
    (vision|ocr|pdf_text|html|asr|table|manual|other), units: [{locator ("p. 3", "00:12:34", "sheet!A1", "msg:<id>"),
    text, speaker?, start?, end?, confidence?}], correspondence?, table?, canonical_url?, confidence?, language?,
    client_declared_class? (standard|correspondence|financial|tax|identity|restricted — how sensitive it is)}.
    Holds what the material says; the client's interpretation goes to finalize_intake as an interpretation."""
    return await _call(ctx, "add_processed_material", {"project_id": project_id, "intake_id": intake_id, "material": material,
                                                       "item_request_id": item_request_id})


@server.tool(annotations=WRITE)
async def attach_artifact(project_id: str, intake_id: str, artifact_ref: dict[str, Any], ctx: Context, item_id: str | None = None,
                          client_declared_class: str | None = None, item_request_id: str | None = None) -> dict[str, Any]:
    """Attaches an original file by reference ({kind: signed_url, url, filename?, sha256?}). With item_id it is
    kept as the original of material already processed (not read again); without it Neuro reads it."""
    return await _call(ctx, "attach_artifact", {"project_id": project_id, "intake_id": intake_id, "artifact_ref": artifact_ref,
                                                "item_id": item_id, "client_declared_class": client_declared_class,
                                                "item_request_id": item_request_id})


@server.tool(annotations=WRITE, meta={"openai/fileParams": ["file"]})
async def attach_file(project_id: str, intake_id: str, file: FileParam, ctx: Context, item_id: str | None = None,
                      client_declared_class: str | None = None, item_request_id: str | None = None) -> dict[str, Any]:
    """Attaches a file the user uploaded in this conversation. With item_id (from add_processed_material) Neuro
    keeps it as the original and does not read it again; without item_id Neuro reads it."""
    file = _file_dict(file)
    ref = {k: v for k, v in {"kind": "signed_url", "url": str(file.get("download_url") or ""), "handle": file.get("file_id"),
                              "filename": file.get("file_name") or "attachment", "content_type": file.get("mime_type")}.items() if v}
    return await _call(ctx, "attach_artifact", {"project_id": project_id, "intake_id": intake_id, "artifact_ref": ref,
                                                "item_id": item_id, "client_declared_class": client_declared_class,
                                                "item_request_id": item_request_id})


@server.tool(annotations=WRITE)
async def finalize_intake(project_id: str, intake_id: str, ctx: Context, user_state: list[dict[str, Any]] | None = None,
                          interpretations: list[dict[str, Any]] | None = None, base_revision: int | None = None) -> dict[str, Any]:
    """Closes the intake. user_state: the same change objects as sync_project_state, for durable things the user
    said about this material. interpretations: [{text, about_item_id?}] — the client's reading, stored as
    interpretation, separate from evidence."""
    return await _call(ctx, "finalize_intake", {"project_id": project_id, "intake_id": intake_id, "user_state": user_state,
                                                "interpretations": interpretations, "base_revision": base_revision})


@server.tool(annotations=READ)
async def get_intake_status(project_id: str, intake_id: str, ctx: Context) -> dict[str, Any]:
    """Where an intake is: received → queued → processing → ready, or needs_review with the reason."""
    return await _call(ctx, "get_intake_status", {"project_id": project_id, "intake_id": intake_id})


# The exact file-object shape OpenAI's "openai/fileParams" contract requires, published INLINE (no $ref, no
# "array or null" wrapper). Pydantic would emit `{"$ref": "#/$defs/FileParam"}` and `anyOf[array, null]`; this only
# replaces what is advertised — the FileParam type still validates every call.
FILE_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "download_url": {"type": "string"},
        "file_id": {"type": "string"},
        "mime_type": {"type": "string"},
        "file_name": {"type": "string"},
    },
    "required": ["download_url", "file_id"],
    "additionalProperties": False,
}


def _publish_file_params() -> None:
    tm = server._tool_manager
    for name, key, many in (("attach_file", "file", False), ("sync_conversation_to_project", "files", True)):
        t = tm.get_tool(name)
        params = dict(t.parameters)
        props = dict(params.get("properties") or {})
        desc = (props.get(key) or {}).get("description")
        props[key] = ({"type": "array", "items": FILE_OBJECT_SCHEMA} if many else dict(FILE_OBJECT_SCHEMA))
        if desc:
            props[key]["description"] = desc
        params["properties"] = props
        params.pop("$defs", None)
        t.parameters = params


_publish_file_params()


def app():
    from mcp.server.transport_security import TransportSecuritySettings
    return server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                      transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
