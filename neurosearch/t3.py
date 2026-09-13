"""Transcript Intelligence T3: deterministic Tier-0 extraction.

This module is deliberately pure.  It returns explainable spans and never reads or writes the
database, queues work, calls a provider, or promotes research state.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from . import qa, works

EXTRACTOR_VERSION = "t3-tier0-v1"

_MONEY = re.compile(r"(?<![\w])(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|b|million|billion))?|\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|dollars?|euros?|pounds?))(?!\w)", re.I)
_PERCENT = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?\s?%(?!\w)|(?<![\w])\d[\d,]*(?:\.\d+)?\s?percent(?:age)?(?!\w)", re.I)
_DURATION = re.compile(r"(?<![\w])\d+(?:\.\d+)?\s?(?:milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?)(?!\w)", re.I)
_DATE = re.compile(r"(?<![\w])(?:20\d{2}-\d{1,2}-\d{1,2}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*20\d{2})?|\d{1,2}[/-]\d{1,2}[/-]20\d{2})(?!\w)", re.I)
_NUMBER = re.compile(r"(?<![\w])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w)")
_UNIT = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?\s?(?:kg|g|lb|lbs|mile|miles|km|ft|sq\.?\s?ft|tokens?|pages?|people|employees?|customers?|sources?|chunks?|windows?)(?!\w)", re.I)
_SENTENCE = re.compile(r"(?m)(?<!\w)[^\n.!?]{2,}[.!?]")
_PROCEDURE = re.compile(r"(?i)^(?:first\s+off\b|(?:first|second|third)\s+step\b|step\s+\d+|then\b|next\b|make sure|ensure|use\b|do\b|avoid\b|never\b|always\b|check\b|calculate\b|contact\b|file\b|submit\b|review\b|keep\b|create\b|add\b|remove\b|set\b|start\b|stop\b)")
# Generic "don't"/"never" also occur in harmless narration ("I don't know").
# Admit only explicit warning words or a small imperative verb list after them.
_WARNING = re.compile(r"(?i)(?:\b(?:warning|warns?|caution|danger|beware|red\s+flag|watch\s+out)\b|\b(?:do\s+not|don't|never)\s+(?:skip|ignore|assume|use|share|send|put|forget|touch|buy|sign|delete|remove|enter|leave|call|rely|invest|miss|start|stop|worry)\b)")
_EXCEPTION = re.compile(r"(?i)\b(?:except|unless|only\s+if|provided\s+that|with\s+the\s+exception|however|although)\b")
_COMPARATIVE = re.compile(r"(?i)\b(?:more|less|higher|lower|better|worse|best|worst|versus|vs\.?|compared\s+(?:with|to)|than)\b")
_HEDGE = re.compile(r"(?i)\b(?:may|might|could|likely|possibly|generally|often|usually|tends?\s+to|appears?|seems?|can\s+be)\b")
_ENTITY = re.compile(r"(?i:\b(?:company|organization|organisation|firm|vendor|tool|product|platform)\s+called\s+)(?P<name>[A-Z][\w&-]*(?:\s+[A-Z][\w&-]*){0,3})")


def _normal(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _number_normal(text: str) -> str:
    return text.replace(",", "").strip().lower()


def _span_record(text: str, start: int, end: int, kind: str, *, normalized: str | None = None,
                 attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = text[start:end]
    return {"kind": kind, "raw": raw, "normalized": normalized if normalized is not None else _normal(raw),
            "start": start, "end": end, "attributes": attributes or {}}


def _add(records: list[dict[str, Any]], text: str, matches: Iterable[re.Match[str]], kind: str,
         *, normalizer: Any = _normal, attributes: dict[str, Any] | None = None) -> None:
    for match in matches:
        records.append(_span_record(text, match.start(), match.end(), kind,
                                    normalized=normalizer(match.group(0)), attributes=attributes))


def _identifier_spans(text: str) -> list[dict[str, Any]]:
    """Reuse works.extract_identifiers' canonical normalization while retaining exact source offsets."""
    records: list[dict[str, Any]] = []
    patterns = {
        "doi": re.compile(r"\b10\.\d{4,9}/[^\s\"'<>)\],;]+", re.I),
        # T3 only admits ISBNs with an explicit ISBN label or the unambiguous
        # 978/979 prefix.  works.extract_identifiers remains the canonical
        # normalizer, but its broad legacy matcher also accepts phone-shaped
        # ten-digit strings; those must not become transcript identifiers.
        "isbn": re.compile(r"\b(?:isbn[:\s-]*(?:97[89][- ]?)?(?:\d[- ]?){9}[\dXx]|97[89][- ]?(?:\d[- ]?){10})\b", re.I),
        "sop": re.compile(r"\bSOP\s*\d{2}[\s-]*\d{2}(?:[\s-]*\d{1,2})?\b", re.I),
        "pub": re.compile(r"\b(?:IRS\s+)?(?:Publication|Pub\.?)\s*\d{2,4}\b", re.I),
        "citation": re.compile(r"\b(?:\d{1,2}\s*U\.?\s*S\.?\s*C\.?|IRC|\d{1,2}\s*C\.?\s*F\.?\s*R\.?)\s*(?:§+|section|part)?\s*[\d.]+[A-Za-z]?(?:\([a-z0-9]+\))?", re.I),
        "docnum": re.compile(r"\b(?:(?:IRS|SBA)\s+)?Form\s+\d{3,4}[A-Z]?(?:-[A-Z0-9]+)?\b", re.I),
    }
    seen: set[tuple[int, int, str]] = set()
    for scheme, pattern in patterns.items():
        for match in pattern.finditer(text):
            # Normalize each span independently.  Mapping every match through the
            # whole-text list would assign the first DOI/SOP to later matches.
            item = next((i for i in works.extract_identifiers(match.group(0))
                         if str(i.get("scheme") or "") == scheme), None)
            if item is None:
                continue
            key = (match.start(), match.end(), scheme)
            if key in seen:
                continue
            seen.add(key)
            records.append(_span_record(text, match.start(), match.end(), "identifier",
                                        normalized=str(item.get("value") or _normal(match.group(0))).lower(),
                                        attributes={"scheme": scheme, "title": item.get("title"), "family": item.get("family")}))
    return records


def extract(text: str, *, extractor_version: str = EXTRACTOR_VERSION) -> dict[str, Any]:
    """Return deterministic Tier-0 spans for one chunk.  No external state is consulted."""
    text = text or ""
    records: list[dict[str, Any]] = []
    protected: list[tuple[int, int]] = []
    identifiers = _identifier_spans(text)
    records.extend(identifiers)
    protected.extend((int(r["start"]), int(r["end"])) for r in identifiers)

    def add_matches(pattern: re.Pattern[str], kind: str, *, normalizer: Any = _normal,
                    attributes: dict[str, Any] | None = None, protect: bool = False) -> None:
        for match in pattern.finditer(text):
            end = match.end()
            while end > match.start() and text[end - 1] in ".,;:!?":
                end -= 1
            if end <= match.start():
                continue
            records.append(_span_record(text, match.start(), end, kind,
                                        normalized=normalizer(text[match.start():end]), attributes=attributes))
            if protect:
                protected.append((match.start(), end))

    add_matches(_MONEY, "money", normalizer=_number_normal, protect=True)
    add_matches(_PERCENT, "percentage", normalizer=_number_normal, protect=True)
    add_matches(_DURATION, "duration", normalizer=_number_normal, protect=True)
    add_matches(_DATE, "date", normalizer=_normal, protect=True)
    add_matches(_UNIT, "unit", normalizer=_number_normal, protect=True)
    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in protected):
            continue
        records.append(_span_record(text, match.start(), match.end(), "number", normalized=_number_normal(match.group(0))))
    for match in qa.URL_RE.finditer(text):
        end = match.end()
        while end > match.start() and text[end - 1] in ".,;:!?":
            end -= 1
        if end > match.start():
            records.append(_span_record(text, match.start(), end, "url", normalized=_normal(text[match.start():end])))

    for sentence in _SENTENCE.finditer(text):
        segment = sentence.group(0)
        left = len(segment) - len(segment.lstrip(" \t[]()"))
        right = len(segment.rstrip(" \t[]()"))
        start = sentence.start() + left
        end = sentence.start() + right
        raw = text[start:end].strip()
        if not raw:
            continue
        # Transcript chunks frequently start with a markdown/topic label such
        # as ``[Intro]``.  That label is metadata, not part of a sentence cue;
        # suppress cue classification when a closing bracket appears in the
        # opening label region.
        if "]" in raw[:60] and raw.find("]") < 60:
            continue
        if raw.rstrip().endswith("?"):
            records.append(_span_record(text, start, end, "question"))
        if _PROCEDURE.search(raw): records.append(_span_record(text, start, end, "procedure"))
        for kind, cue in (("warning", _WARNING), ("exception", _EXCEPTION), ("comparative", _COMPARATIVE), ("hedge", _HEDGE)):
            if cue.search(raw): records.append(_span_record(text, start, end, kind))
    for match in _ENTITY.finditer(text):
        name = match.group("name").strip()
        if len(name) < 2 or name.lower() in {"i", "a"}:
            continue
        name_start = match.start("name") + len(match.group("name")) - len(match.group("name").lstrip())
        records.append(_span_record(text, name_start, name_start + len(name), "entity", normalized=_normal(name),
                                    attributes={"cue": match.group(0)[:match.group(0).find(name)].strip().lower()}))

    unique: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for record in records:
        key = (int(record["start"]), int(record["end"]), str(record["kind"]), str(record["normalized"]))
        unique[key] = record
    ordered = [unique[k] for k in sorted(unique)]
    return {"extractor_version": extractor_version, "records": ordered}
