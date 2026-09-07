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

REGISTRY: dict[str, dict[str, Any]] = {
    "findings-v2": FINDINGS_V2,
    "rank-v2": RANK_V2,
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


_missing_warned = False


def validate(name: str, obj: Any) -> list[str]:
    """Client-side validation against the FULL schema (jsonschema). Returns a list of error strings (empty = valid).
    The provider-enforced schema is the production guarantee; this is defence in depth, so a missing jsonschema
    package (an un-reinstalled checkout) is logged loudly once and treated as 'not validated' rather than taking
    every findings job down."""
    global _missing_warned
    try:
        import jsonschema
    except ImportError:
        if not _missing_warned:
            import logging
            logging.getLogger(__name__).error("jsonschema is not installed — run `pip install -e .`; structured outputs are provider-enforced but not re-validated locally")
            _missing_warned = True
        return []
    v = jsonschema.Draft202012Validator(get(name))
    out = []
    for e in sorted(v.iter_errors(obj), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in e.path) or "<root>"
        out.append(f"{where}: {e.message}"[:200])
    return out


def is_valid(name: str, obj: Any) -> bool:
    return not validate(name, obj)
