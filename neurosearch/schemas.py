"""Versioned output schemas (Mission F — deterministic AI).

One registry, three uses:
  * production: the provider enforces the schema at generation time (`output_config.format`, structured outputs);
  * tests + fakes: `jsonschema` validates that every fake output and every parsed response conforms;
  * provenance: the registry key (e.g. "findings-v2") is the artifact's schema_version and part of its input_hash,
    so a schema change makes artifacts stale exactly like a prompt change does.

Provider compatibility is checked here, before any paid request: internal `$ref`/`$defs` are fine, external refs,
`allOf`/`oneOf`/`not` and unsupported string formats are not; numeric/length/pattern constraints are kept for the
client-side validator and stripped from the copy sent to the provider (`provider_schema`).
"""
from __future__ import annotations

import copy
import json
from typing import Any

_STR = {"type": "string"}
_INT = {"type": "integer"}

FINDINGS_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FindingsV2",
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two sentences on what the transcript actually covers"},
        "substance": {"type": "integer", "minimum": 0, "maximum": 100, "description": "0 = pure fluff, 100 = dense, specific, on-topic"},
        "findings": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
    },
    "required": ["summary", "substance", "findings"],
    "additionalProperties": False,
    "$defs": {
        "finding": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "≤ 8 words, the claim itself"},
                "finding": {"type": "string", "description": "one sentence of what the title leaves out; may be empty"},
                "ts": {"type": "string", "description": "the [m:ss] / h:mm:ss / p. N / § N marker just before the quote"},
                "quote": {"type": "string", "description": "≤ 20 verbatim words from the transcript"},
                "importance": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["title", "finding", "ts", "quote", "importance"],
            "additionalProperties": False,
        }
    },
}

RANK_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RankingV2",
    "type": "object",
    "properties": {
        "scores": {"type": "array", "items": {"$ref": "#/$defs/score"}},
    },
    "required": ["scores"],
    "additionalProperties": False,
    "$defs": {
        "score": {
            "type": "object",
            "properties": {
                "i": {"type": "integer", "minimum": 0, "description": "the [index] of the video"},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "why": {"type": "string", "description": "max 8 words"},
            },
            "required": ["i", "score", "why"],
            "additionalProperties": False,
        }
    },
}

PLAN_UPDATE_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "PlanUpdateV2",
    "type": "object",
    "properties": {"updates": {"type": "array", "items": {"$ref": "#/$defs/update"}, "description": "empty when nothing material changed"}},
    "required": ["updates"],
    "additionalProperties": False,
    "$defs": {
        "update": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "minLength": 1, "description": "which part of the plan changes"},
                "previous": {"type": "string", "description": "what the plan says now"},
                "proposed": {"type": "string", "minLength": 1, "description": "what it should say"},
                "reason": {"type": "string", "minLength": 1, "description": "the new material that justifies it"},
            },
            "required": ["section", "previous", "proposed", "reason"],
            "additionalProperties": False,
        }
    },
}

DISCOVERY_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DiscoveryV2",
    "type": "object",
    "properties": {
        "sources": {"type": "array", "items": {"$ref": "#/$defs/source"}},
        "note": {"type": "string", "description": "one or two sentences on sequencing or caveats"},
    },
    "required": ["sources", "note"],
    "additionalProperties": False,
    "$defs": {
        "start": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}}, "required": ["title", "url"], "additionalProperties": False},
        "source": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["youtube_channel", "podcast", "newsletter", "website", "person"]},
                "url": {"type": "string", "description": "canonical page, or empty when unsure"},
                "gist": {"type": "string", "description": "at most 5 words"},
                "why": {"type": "string", "description": "one sentence, max 20 words"},
                "angle": {"type": "string", "description": "bias/lens, max 12 words"},
                "start_with": {"type": "array", "items": {"$ref": "#/$defs/start"}},
                "fit": {"type": "integer", "minimum": 1, "maximum": 5},
                "depth": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
            },
            "required": ["name", "kind", "url", "gist", "why", "angle", "start_with", "fit", "depth"],
            "additionalProperties": False,
        },
    },
}

REGISTRY: dict[str, dict[str, Any]] = {
    "findings-v2": FINDINGS_V2,
    "rank-v2": RANK_V2,
    "plan-update-v2": PLAN_UPDATE_V2,
    "discovery-v2": DISCOVERY_V2,
}

# keywords the provider accepts (per the structured-outputs docs) — everything else is stripped or rejected
_PROVIDER_KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const", "anyOf", "$ref", "$defs", "definitions",
                      "description", "title", "$schema", "default"}
_STRIPPED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "format", "examples"}
_REJECTED = {"allOf", "oneOf", "not", "if", "then", "else", "dependentSchemas", "patternProperties", "$id", "$anchor", "$dynamicRef"}


class SchemaError(ValueError):
    pass


def get(name: str) -> dict[str, Any]:
    try:
        return REGISTRY[name]
    except KeyError:
        raise SchemaError(f"unknown output schema {name!r}; registered: {sorted(REGISTRY)}") from None


def check_provider_compat(schema: dict[str, Any], name: str = "") -> None:
    """Raise SchemaError if the provider would reject this schema. Runs in tests for every registry entry and from
    contracts.validate for every structured contract — never discovered by a paid request."""
    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in _REJECTED:
                    raise SchemaError(f"{name}{path}: {k!r} is not supported by structured outputs")
                if k == "$ref":
                    if not isinstance(v, str) or not v.startswith("#/"):
                        raise SchemaError(f"{name}{path}: only internal $ref (#/…) is supported, got {v!r}")
                    continue
                if k in ("properties", "$defs", "definitions"):
                    for pk, pv in v.items():
                        walk(pv, f"{path}/{k}/{pk}")
                    continue
                if k in ("items",):
                    walk(v, f"{path}/{k}")
                    continue
                if k == "anyOf":
                    for i, alt in enumerate(v):
                        walk(alt, f"{path}/anyOf[{i}]")
                    continue
                if k not in _PROVIDER_KEYWORDS and k not in _STRIPPED:
                    raise SchemaError(f"{name}{path}: unknown keyword {k!r}")
            if node.get("type") == "object" and node.get("additionalProperties") is not False:
                raise SchemaError(f"{name}{path}: objects must set additionalProperties: false")
    walk(schema, "")
    _resolve_refs(schema, name)


def _resolve_refs(schema: dict[str, Any], name: str) -> None:
    defs = {**schema.get("$defs", {}), **schema.get("definitions", {})}
    text = json.dumps(schema)
    import re
    for ref in set(re.findall(r'"\$ref": "([^"]+)"', text)):
        key = ref.split("/")[-1]
        if not ref.startswith(("#/$defs/", "#/definitions/")) or key not in defs:
            raise SchemaError(f"{name}: unresolved $ref {ref!r}")


def provider_schema(name: str) -> dict[str, Any]:
    """The copy sent in output_config.format: client-only constraints (min/max/length/pattern/format) stripped."""
    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in _STRIPPED and k != "$schema"}
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node
    return strip(copy.deepcopy(get(name)))


def output_config(name: str) -> dict[str, Any]:
    return {"format": {"type": "json_schema", "schema": provider_schema(name)}}


def check_installation() -> None:
    """jsonschema is a required dependency (Mission F): the local validator is part of the contract, not an
    enhancement. An incomplete checkout fails at startup with instructions rather than validating less on one machine."""
    try:
        import jsonschema  # noqa: F401
    except ImportError as e:
        raise SystemExit("Neuro Search installation is incomplete:\njsonschema is required by structured outputs.\n\nRun ./start to update dependencies (it runs pip install -e .).") from e


def validate(name: str, obj: Any) -> list[str]:
    """Client-side validation against the FULL schema (jsonschema). Returns a list of error strings (empty = valid)."""
    import jsonschema
    v = jsonschema.Draft202012Validator(get(name))
    out = []
    for e in sorted(v.iter_errors(obj), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in e.path) or "<root>"
        out.append(f"{where}: {e.message}"[:200])
    return out


def is_valid(name: str, obj: Any) -> bool:
    return not validate(name, obj)
