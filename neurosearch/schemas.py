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

# Rung H1 — the findings window pre-filter answers ONE question: does this transcript window have ANY plausible value to
# the project's research brief? Three outcomes; only DROP has a cost (the window is not analysed). It never extracts.
PREFILTER_V1: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["keep", "uncertain", "drop"],
                     "description": "keep = clearly has plausible value for the brief; uncertain = cannot rule value out (analyse it); drop = confidently no plausible value at all"},
        "reason": {"type": "string", "maxLength": 200, "description": "one short sentence"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}

# G4 — the enriched, project-neutral Source Profile. Describes the SOURCE (what it is, what it can answer); never a
# project judgement. `authority_notes` explains the source's characteristics with their basis; the deterministic
# `authority_signals` in the baseline stay the primary evidence.
SOURCE_PROFILE_V1: dict[str, Any] = {
    # No maxLength anywhere: the provider strips client-only constraints (provider_schema), so a maxLength is a local-only
    # trap that the model cannot see — 0.28.0 lost a whole batch of profiles to authority_notes > 300 chars. Lengths are
    # guidance in descriptions; the contract's max_output_tokens bounds the whole.
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "two or three neutral sentences: what this source is and what it covers"},
        "topics": {"type": "array", "items": {"type": "string"}, "maxItems": 15, "description": "short subject phrases the source actually discusses, most substantial first"},
        "entities": {"type": "array", "items": {"type": "string"}, "maxItems": 20, "description": "named organisations, laws, products, places, people, standards mentioned substantively"},
        "document_type": {"type": "string", "description": "a few words, e.g. interview, tutorial, official publication, forum thread, product page, lecture, case study, rate schedule"},
        "evidence_class": {"type": "string", "enum": ["authoritative", "expert", "experiential", "market", "historical", "mixed"],
                           "description": "the KIND of evidence it offers (not how good it is): authoritative = governing/official text; expert = practitioner analysis; experiential = firsthand experience; market = current prices/offers/conditions; historical = past events"},
        "temporal_character": {"type": "string", "enum": ["static", "slow_changing", "periodic", "fast_changing"],
                               "description": "how quickly the factual claims in it go stale"},
        "useful_for": {"type": "array", "items": {"type": "string"}, "maxItems": 12, "description": "concrete questions this source can help answer, one short line each"},
        "not_useful_for": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "description": "things a title might suggest but the source does not actually cover"},
        "authority_notes": {"type": "string", "description": "one or two sentences: who speaks and on what basis (role, organisation, firsthand vs secondhand) — descriptive, with the basis stated; never a score"},
        "minority_topics": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "description": "briefly-covered but substantive topics a summary would miss"},
    },
    "required": ["summary", "topics", "entities", "document_type", "evidence_class", "temporal_character", "useful_for", "authority_notes"],
    "additionalProperties": False,
}

# Rung I2 — listwise rerank of the retrieved candidates: a permutation of the candidate numbers, nothing else.
RETRIEVAL_RERANK_V1: dict[str, Any] = {
    "type": "object",
    "properties": {
        "order": {"type": "array", "items": {"type": "integer"}, "description": "every candidate number exactly once, best first"},
    },
    "required": ["order"],
    "additionalProperties": False,
}

# G5 (0.29.0) — claim normalization + proposed evidence targets. Same rule as source-profile-v1: NO string-length constraints
# (the provider strips them; a local-only bound fails after paying). Lists bounded with maxItems, categories with enums.
CLAIM_SET_V1: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "maxItems": 40, "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "the candidate id you were given"},
                "text": {"type": "string", "description": "the normalised proposition WITH its qualifiers and the source's hedging"},
                "claim_type": {"type": "string", "enum": ["governing", "historical", "expert_interpretation", "practice", "experiential", "market", "causal", "novel_tactic", "other"]},
                "qualifiers": {"type": "object", "properties": {
                    "jurisdiction": {"type": "string"}, "product": {"type": "string"}, "population": {"type": "string"},
                    "conditions": {"type": "string"}, "timeframe": {"type": "string"}, "source_language": {"type": "string"},
                    "imposed_by": {"type": "string", "enum": ["", "seller_or_listing", "legal_ownership", "professional_licensing", "service_performance", "lender_policy", "state_specific", "unclear"],
                                   "description": "for a requirement: who imposes it; empty when the claim is not a requirement"},
                    "specific_instance": {"type": "boolean", "description": "true when a market claim describes one specific quote/listing"}},
                    "required": ["jurisdiction", "product", "population", "conditions", "timeframe", "source_language", "imposed_by", "specific_instance"], "additionalProperties": False},
                "topic": {"type": "string", "description": "2-4 word knowledge-map topic"},
                "freshness_class": {"type": "string", "enum": ["regulatory", "rates_pricing", "promotional", "underwriting_practice", "tactics", "operational", "experiential", "historical", "static", "uncertain"]},
                "merge_into": {"type": ["string", "null"], "description": "id of the candidate this one duplicates (same proposition, same scope), else null"},
            },
            "required": ["id", "text", "claim_type", "qualifiers", "topic", "freshness_class", "merge_into"],
            "additionalProperties": False}},
        "targets": {"type": "array", "maxItems": 8, "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "topic": {"type": "string"},
                "sufficiency": {"type": "string", "enum": ["governing", "corroborative"]},
                "preferred_classes": {"type": "array", "maxItems": 4, "items": {"type": "string", "enum": ["authoritative", "expert", "experiential", "market", "historical"]}},
                "closure": {"type": "string", "description": "one sentence: what counts as enough"},
            },
            "required": ["question", "topic", "sufficiency", "preferred_classes", "closure"],
            "additionalProperties": False}},
        "missing_areas": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
    },
    "required": ["claims", "targets", "missing_areas"],
    "additionalProperties": False,
}

REGISTRY: dict[str, dict[str, Any]] = {
    "claim-set-v1": CLAIM_SET_V1,
    "findings-v2": FINDINGS_V2,
    "prefilter-v1": PREFILTER_V1,
    "source-profile-v1": SOURCE_PROFILE_V1,
    "retrieval-rerank-v1": RETRIEVAL_RERANK_V1,
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
    def strip(node: Any, is_map: bool = False) -> Any:
        """is_map: this dict maps NAMES to schemas (properties/$defs/definitions) — its keys are never keywords."""
        if isinstance(node, dict):
            if is_map:
                return {k: strip(v) for k, v in node.items()}
            return {k: strip(v, is_map=k in ("properties", "$defs", "definitions")) for k, v in node.items() if k not in _STRIPPED and k != "$schema"}
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


# ------------------------------------------------------------------ Planner V3 (Mission F4): one frozen analysis, four semantic components

_ID = {"type": "string", "minLength": 3, "description": "stable semantic id: <kind>:<kebab-case-slug>, e.g. task:get-lender-prequalification"}
_EVIDENCE = {"type": "array", "items": {"type": "string"}, "description": "evidence ids from the EVIDENCE list (U1, F3, S2, C1…); empty if none"}
_BASIS = {"type": "string", "enum": ["research", "user", "planner", "estimate"]}
_CONF = {"type": "string", "enum": ["high", "medium", "needs_research"]}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props), "additionalProperties": False}


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


SITUATION_V3: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "SituationAnalysisV3",
    **_obj({
        "situation": {"type": "string", "description": "3-5 sentences: where this person stands today"},
        "swot": _obj({"strengths": _arr({"$ref": "#/$defs/point"}), "weaknesses": _arr({"$ref": "#/$defs/point"}),
                      "opportunities": _arr({"$ref": "#/$defs/point"}), "threats": _arr({"$ref": "#/$defs/point"})}),
        "readiness": _arr(_obj({"area": {"type": "string"}, "level": {"type": "string", "enum": ["ready", "partly", "gap"]}, "note": {"type": "string"}})),
        "options": _arr(_obj({"id": _ID, "path": {"type": "string"}, "summary": {"type": "string"}, "cost": {"type": "string"}, "time_to_result": {"type": "string"},
                              "risk": {"type": "string", "enum": ["low", "medium", "high"]}, "fit": {"type": "integer", "minimum": 1, "maximum": 5},
                              "why_fit": {"type": "string"}, "evidence": _EVIDENCE})),
        "recommended_option": {"type": "string", "description": "the id of the option to build the plan on"},
        "assumptions": _arr(_obj({"id": _ID, "assumption": {"type": "string"}, "if_wrong": {"type": "string"}, "how_to_check": {"type": "string"}})),
        "failure_patterns": _arr(_obj({"id": _ID, "pattern": {"type": "string"}, "seen_in": {"type": "string"}, "avoid": {"type": "string"}, "evidence": _EVIDENCE})),
        "verdict": {"type": "string", "description": "2-3 sentences: the honest take"},
    }),
    "$defs": {"point": _obj({"point": {"type": "string"}, "so_what": {"type": "string"}, "evidence": _EVIDENCE})},
}

PLAN_CORE_V3: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "PlanCoreV3",
    **_obj({
        "goal": _obj({"outcome": {"type": "string"}, "constraints": _arr({"type": "string"}), "success": _arr({"type": "string"}), "evidence": _EVIDENCE}),
        "approach": _obj({"recommended": {"type": "string"}, "why": {"type": "string"}, "option": {"type": "string", "description": "the analysis option id this follows"},
                          "alternatives": _arr(_obj({"option": {"type": "string"}, "why_not": {"type": "string"}})), "basis": _BASIS, "confidence": _CONF, "evidence": _EVIDENCE}),
        "decisions": _arr(_obj({"id": _ID, "decision": {"type": "string"}, "options": _arr({"type": "string"}), "recommended": {"type": "string"}, "why": {"type": "string"},
                                "when": {"type": "string", "enum": ["now", "later"]}, "basis": _BASIS, "evidence": _EVIDENCE})),
        "confidence": _arr(_obj({"area": {"type": "string"}, "level": _CONF, "note": {"type": "string"}})),
    }),
}

PLAN_EXECUTION_V3: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "PlanExecutionV3",
    **_obj({
        "phases": _arr(_obj({"id": _ID, "name": {"type": "string"}, "objective": {"type": "string"},
                             "tasks": _arr(_obj({"id": _ID, "task": {"type": "string"}, "detail": {"type": "string"},
                                                 "depends_on": {"type": "array", "items": {"type": "string"}, "description": "task ids that must finish first"}, "evidence": _EVIDENCE})),
                             "dependencies": _arr({"type": "string"}), "decisions": {"type": "array", "items": {"type": "string"}, "description": "decision ids needed before this phase"},
                             "outcome": {"type": "string"}})),
        "dependencies": _arr(_obj({"id": _ID, "item": {"type": "string"}, "blocking": {"type": "boolean"}, "note": {"type": "string"},
                                   "phase": {"type": "string", "description": "phase id this gates, or empty"}})),
        "defer": _arr(_obj({"item": {"type": "string"}, "until": {"type": "string"}})),
    }),
}

PLAN_ECONOMICS_V3: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "PlanEconomicsV3",
    **_obj({
        "costs": _obj({"upfront": _arr({"$ref": "#/$defs/cost"}), "recurring": _arr({"$ref": "#/$defs/cost"}), "optional": _arr({"$ref": "#/$defs/cost"}),
                       "services": _arr({"$ref": "#/$defs/cost"}), "contingency": {"type": "string"}, "minimum": {"type": "string"}, "recommended": {"type": "string"},
                       "premium": {"type": "string"}, "note": {"type": "string"}, "evidence": _EVIDENCE}),
        "tools": _arr(_obj({"id": _ID, "need": {"type": "string"}, "tool": {"type": "string"}, "free_option": {"type": "string"}, "premium_option": {"type": "string"},
                            "cost": {"type": "string"}, "why": {"type": "string"}, "tier": {"type": "string", "enum": ["required", "recommended", "optional"]},
                            "basis": _BASIS, "evidence": _EVIDENCE, "phase": {"type": "string", "description": "phase id, or empty"}})),
        "risks": _arr(_obj({"id": _ID, "risk": {"type": "string"}, "mitigation": {"type": "string"}, "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                            "related": {"type": "array", "items": {"type": "string"}, "description": "task/phase ids the mitigation lives in, or empty"}, "evidence": _EVIDENCE})),
        "gotchas": _arr(_obj({"id": _ID, "gotcha": {"type": "string"}, "avoid": {"type": "string"}})),
    }),
    "$defs": {"cost": _obj({"item": {"type": "string"}, "amount": {"type": "string"}, "phase": {"type": "string", "description": "phase id, or empty"}})},
}

PLAN_ACTIONS_V3: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "PlanActionsV3",
    **_obj({
        "first_steps": _arr(_obj({"id": _ID, "action": {"type": "string"}, "detail": {"type": "string"}, "today": {"type": "boolean"},
                                  "task": {"type": "string", "description": "the plan task id this starts, or empty"}, "evidence": _EVIDENCE})),
        "this_week": _arr(_obj({"id": _ID, "action": {"type": "string"}, "why": {"type": "string"}, "time": {"type": "string"},
                                "task": {"type": "string", "description": "the plan task id this advances, or empty"}})),
        "open_questions": _arr(_obj({"id": _ID, "question": {"type": "string"}, "category": {"type": "string", "enum": ["blocking", "soon", "nice"]},
                                     "why": {"type": "string"}, "research_prompt": {"type": "string"}})),
        "refine_questions": _arr(_obj({"id": _ID, "question": {"type": "string"}, "why": {"type": "string"}, "kind": {"type": "string", "enum": ["fact", "decision", "preference"]},
                                       "options": _arr({"type": "string"})})),
        "ready": _obj({"first_three": _arr({"type": "string"}), "initial_cost": {"type": "string"}, "need_before": _arr({"type": "string"}), "blockers": _arr({"type": "string"})}),
    }),
}

REGISTRY.update({
    "situation-v3": SITUATION_V3,
    "plan-core-v3": PLAN_CORE_V3,
    "plan-execution-v3": PLAN_EXECUTION_V3,
    "plan-economics-v3": PLAN_ECONOMICS_V3,
    "plan-actions-v3": PLAN_ACTIONS_V3,
})


def normalize_enums(name: str, obj: Any) -> Any:
    """Structured outputs do not guarantee the capitalisation of enum/const values (provider docs: compare
    case-insensitively). Before local validation, map any string whose lowercase form matches an enum member to that
    member, in place. Anything else is left alone and will fail validation as it should."""
    def walk(node: Any, schema: dict[str, Any], root: dict[str, Any]) -> Any:
        if "$ref" in schema:
            ref = schema["$ref"].split("/")
            target: Any = root
            for seg in ref[1:]:
                target = target.get(seg, {})
            return walk(node, target, root)
        if "enum" in schema and isinstance(node, str):
            for member in schema["enum"]:
                if isinstance(member, str) and member.lower() == node.lower():
                    return member
            return node
        if isinstance(node, dict) and schema.get("type") == "object":
            props = schema.get("properties", {})
            for k in list(node):
                if k in props:
                    node[k] = walk(node[k], props[k], root)
            return node
        if isinstance(node, list) and schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            return [walk(x, schema["items"], root) for x in node]
        return node
    sch = get(name)
    return walk(obj, sch, sch)


def clamp(name: str, obj: Any) -> Any:
    """Constraints the provider strips (`_STRIPPED`: maxItems, maxLength, …) are invisible to the model, so locally they
    are CLAMPS, never rejections: arrays are truncated to maxItems and strings to maxLength before validation. 0.28.0
    (profiles, maxLength) and 0.30.2 (claims, maxItems on missing_areas) both paid for a batch and then failed it on a
    constraint the model could not see; this makes that class of failure impossible by construction."""
    def walk(node: Any, schema: dict[str, Any], root: dict[str, Any]) -> Any:
        if "$ref" in schema:
            target: Any = root
            for seg in schema["$ref"].split("/")[1:]:
                target = target.get(seg, {})
            return walk(node, target, root)
        if isinstance(node, str) and isinstance(schema.get("maxLength"), int) and len(node) > schema["maxLength"]:
            node = node[: schema["maxLength"]]
        if isinstance(node, list) and schema.get("type") == "array":
            if isinstance(schema.get("maxItems"), int) and len(node) > schema["maxItems"]:
                node = node[: schema["maxItems"]]
            if isinstance(schema.get("items"), dict):
                node = [walk(x, schema["items"], root) for x in node]
            return node
        if isinstance(node, dict) and schema.get("type") == "object":
            props = schema.get("properties", {})
            for k in list(node):
                if k in props:
                    node[k] = walk(node[k], props[k], root)
            return node
        return node
    sch = get(name)
    return walk(obj, sch, sch)
