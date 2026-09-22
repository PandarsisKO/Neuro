"""P11 EA-0 — the versioned JSON contracts of the external AI interface (EXTERNAL-AI-ACCESS-MISSION.md §39, §54).

These are wire contracts between Neuro and an external LLM client (ChatGPT first, Claude second — Kyle, 2026-09-22),
not model structured-output schemas, so they live here rather than in `schemas.REGISTRY`: every entry there is a
provider output schema that `check_provider_compat` holds to the Anthropic subset, and these deliberately use the
full JSON Schema vocabulary (`oneOf`, `pattern`, bounds) because `jsonschema` enforces them at the boundary.

Nothing here names a vendor. A client's abilities are described by `CAPABILITIES` (§63), never by who made it.
"""
from __future__ import annotations

from typing import Any

import jsonschema

SCHEMA_VERSION = "1"

DISCLOSURE_CLASSES = ("standard", "correspondence", "financial", "tax", "identity", "restricted")
MATERIAL_TYPES = ("image", "pdf", "url", "correspondence", "spreadsheet", "transcript", "text")
EXTRACTION_METHODS = ("vision", "ocr", "pdf_text", "html", "asr", "table", "manual", "other")
CAPABILITIES = ("vision", "ocr", "pdf_text", "table_extraction", "web_access", "transcription", "diarization",
                "read_tools", "write_tools")
FILE_TRANSPORTS = ("multipart", "mcp_resource", "signed_url", "none")
ARTIFACT_REF_KINDS = ("multipart", "mcp_resource", "signed_url", "client_handle")
FACT_KINDS = ("decision", "constraint", "requirement", "rejected", "context", "preference", "commitment",
              "deadline", "counterpart_position", "concern", "open_question")
SYNC_OPS = ("record", "reaffirm", "supersede", "propose", "withdraw")
EXPLICITNESS = ("explicit", "accepted_recommendation", "inferred")
SCOPES = ("project", "personal")

_S = {"type": "string"}
_ID = {"type": "string", "minLength": 1, "maxLength": 200}
_REQ = {"type": "string", "minLength": 8, "maxLength": 200, "description": "client-chosen idempotency key, resent verbatim on retry"}

ENVELOPE_V1: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "as_of", "truncated", "data"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "project_id": {"type": ["string", "null"]},
        "project_revision": {"type": ["string", "null"]},
        "ledger_cursor": {"type": ["integer", "null"]},
        "as_of": {"type": "number"},
        "truncated": {"type": "boolean"},
        "next_cursor": {"type": ["string", "integer", "null"]},
        "data": {},
    },
    "additionalProperties": False,
}

CLIENT_CAPABILITIES_V1: dict[str, Any] = {
    "type": "object",
    "properties": {**{c: {"type": "boolean"} for c in CAPABILITIES},
                   "file_transport": {"type": "array", "items": {"enum": list(FILE_TRANSPORTS)}, "maxItems": 4}},
    "additionalProperties": False,
}

UNIT: dict[str, Any] = {
    "type": "object",
    "required": ["text"],
    "properties": {
        "locator": {"type": "string", "maxLength": 120,
                    "description": "p. 4 | 00:12:34 | sheet!A1 | region:x,y,w,h | msg:<id> | § 3"},
        "text": {"type": "string", "minLength": 1, "maxLength": 200_000},
        "speaker": {"type": "string", "maxLength": 200},
        "start": {"type": "number", "minimum": 0},
        "end": {"type": "number", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "additionalProperties": False,
}

MATERIAL_V1: dict[str, Any] = {
    "type": "object",
    "required": ["material_type", "title", "producer", "extraction_method", "units"],
    "properties": {
        "material_type": {"enum": list(MATERIAL_TYPES)},
        "title": {"type": "string", "minLength": 1, "maxLength": 500},
        "canonical_url": {"type": "string", "maxLength": 4000},
        "producer": {"type": "string", "minLength": 1, "maxLength": 200},
        "extraction_method": {"enum": list(EXTRACTION_METHODS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "language": {"type": "string", "maxLength": 20},
        "client_declared_class": {"enum": list(DISCLOSURE_CLASSES)},
        "units": {"type": "array", "items": UNIT, "minItems": 1, "maxItems": 20_000},
        "correspondence": {
            "type": "object",
            "properties": {"from": _S, "to": {"type": "array", "items": _S, "maxItems": 100}, "cc": {"type": "array", "items": _S, "maxItems": 100},
                           "date": _S, "thread_id": _S, "message_id": _S, "subject": _S},
            "additionalProperties": False,
        },
        "table": {
            "type": "object",
            "properties": {"sheet": _S, "columns": {"type": "array", "items": _S, "maxItems": 500},
                           "rows": {"type": "array", "items": {"type": "array", "maxItems": 500}, "maxItems": 20_000}},
            "additionalProperties": False,
        },
        "original_ref": {"$ref": "#/$defs/artifact_ref"},
        "original_available": {"type": "boolean", "description": "false when the client read the original but can no longer "
                                                                 "hand it over: Neuro keeps the extraction and never claims to hold the file"},
    },
    "additionalProperties": False,
    "$defs": {},
}

ARTIFACT_REF_V1: dict[str, Any] = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"enum": list(ARTIFACT_REF_KINDS)},
        "url": {"type": "string", "maxLength": 4000},
        "uri": {"type": "string", "maxLength": 4000},
        "handle": {"type": "string", "maxLength": 500},
        "filename": {"type": "string", "maxLength": 500},
        "content_type": {"type": "string", "maxLength": 200},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "bytes": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}
MATERIAL_V1["$defs"]["artifact_ref"] = ARTIFACT_REF_V1

STATE_CHANGE: dict[str, Any] = {
    "type": "object",
    "required": ["op", "client_request_id"],
    "properties": {
        "op": {"enum": list(SYNC_OPS)},
        "kind": {"enum": list(FACT_KINDS)},
        "content": {"type": "string", "minLength": 1, "maxLength": 4000},
        "fact_id": {"type": "integer"},
        "rationale": {"type": "string", "maxLength": 4000},
        "explicitness": {"enum": list(EXPLICITNESS)},
        "scope": {"enum": list(SCOPES)},
        "referent": {"type": "string", "maxLength": 4000,
                     "description": "for accepted_recommendation: the ONE assistant proposal the user accepted, verbatim"},
        "user_text": {"type": "string", "maxLength": 4000,
                      "description": "the user's own words that state this (quoted from the conversation). Required for anything "
                                     "committed as the project's position; without it the item is saved as a suggestion"},
        "disclosure_class": {"enum": list(DISCLOSURE_CLASSES)},
        "client_request_id": _REQ,
    },
    "additionalProperties": False,
}

SYNC_V1: dict[str, Any] = {
    "type": "object",
    "required": ["project_id", "changes"],
    "properties": {
        "project_id": _ID,
        "base_revision": {"type": ["integer", "null"], "description": "the ledger_cursor the client reasoned against (§51)"},
        "intake_id": _ID,
        "changes": {"type": "array", "items": STATE_CHANGE, "minItems": 1, "maxItems": 50},
    },
    "additionalProperties": False,
}

INTERPRETATION: dict[str, Any] = {
    "type": "object",
    "required": ["text"],
    "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 20_000},
                   "about_item_id": _ID, "producer": {"type": "string", "maxLength": 200}},
    "additionalProperties": False,
}

# P11 EA-9: catch-up sync of what mattered in an external conversation that did not start "inside" Neuro. Per-change
# request ids are optional here — they are derived from the sync's own id, so a retried sync is idempotent.
SYNC_CHANGE: dict[str, Any] = {**STATE_CHANGE, "required": ["op"]}
CONVERSATION_SYNC_V1: dict[str, Any] = {
    "type": "object",
    "required": ["client_request_id"],
    "properties": {
        "project_id": _ID,
        "project_hint": {"type": "string", "maxLength": 200},
        "project_named_by_user": {"type": "boolean", "description": "true only if the USER named the project in their own words; "
                                                                    "an inferred project is suggested and confirmed first"},
        "conversation_ref": {"type": "string", "maxLength": 200},
        "client_request_id": _REQ,
        "base_revision": {"type": ["integer", "null"]},
        "state": {"type": "array", "items": SYNC_CHANGE, "maxItems": 100},
        "materials": {"type": "array", "items": MATERIAL_V1, "maxItems": 20},
        "files": {"type": "array", "maxItems": 20, "items": {
            "type": "object", "required": ["artifact_ref"], "additionalProperties": False,
            "properties": {"artifact_ref": ARTIFACT_REF_V1, "original_of_material": {"type": "integer", "minimum": 0},
                           "client_declared_class": {"enum": list(DISCLOSURE_CLASSES)}}}},
        "analysis": {"type": "array", "items": INTERPRETATION, "maxItems": 20},
        "archive_transcript": {"type": "object", "required": ["text", "explicit_user_request"], "additionalProperties": False,
                               "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 400_000},
                                              "explicit_user_request": {"const": True}}},
    },
    "additionalProperties": False,
}

REGISTRY: dict[str, dict[str, Any]] = {
    "external.conversation_sync.v1": CONVERSATION_SYNC_V1,
    "external.envelope.v1": ENVELOPE_V1,
    "external.capabilities.v1": CLIENT_CAPABILITIES_V1,
    "external.material.v1": MATERIAL_V1,
    "external.artifact_ref.v1": ARTIFACT_REF_V1,
    "external.sync.v1": SYNC_V1,
    "external.state_change.v1": STATE_CHANGE,
    "external.interpretation.v1": INTERPRETATION,
}


class ContractError(ValueError):
    """A request that does not match its versioned contract. Carries every violation, not only the first."""

    def __init__(self, name: str, errors: list[str]):
        super().__init__(f"{name}: " + "; ".join(errors[:5]))
        self.name, self.errors = name, errors


def errors(name: str, obj: Any) -> list[str]:
    v = jsonschema.Draft202012Validator(REGISTRY[name])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}" for e in v.iter_errors(obj)]


def check(name: str, obj: Any) -> Any:
    errs = errors(name, obj)
    if errs:
        raise ContractError(name, errs)
    return obj


def check_installation() -> None:
    for name, schema in REGISTRY.items():
        jsonschema.Draft202012Validator.check_schema(schema)
