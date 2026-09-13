"""Pure validation and scoring helpers for T3 hand-label manifests.

The helpers operate only on in-memory rows.  They never open the database, call a provider,
write an artifact, or promote extraction output to product state.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


RECORD_FIELDS = ("kind", "raw", "normalized", "start", "end", "attributes")


def record_key(record: dict[str, Any]) -> tuple[str, int, int, str]:
    return (str(record["kind"]), int(record["start"]), int(record["end"]), str(record["normalized"]))


def validate_records(text: str, records: Iterable[dict[str, Any]]) -> list[str]:
    """Return deterministic structural errors for predicted or gold records."""
    errors: list[str] = []
    seen: set[tuple[str, int, int, str]] = set()
    previous: tuple[int, int, str, str] | None = None
    for index, record in enumerate(records):
        missing = [field for field in RECORD_FIELDS if field not in record]
        if missing:
            errors.append(f"record[{index}] missing {','.join(missing)}")
            continue
        try:
            start, end = int(record["start"]), int(record["end"])
        except (TypeError, ValueError):
            errors.append(f"record[{index}] has non-integer offsets")
            continue
        if start < 0 or end <= start or end > len(text):
            errors.append(f"record[{index}] offsets outside half-open text bounds")
        elif text[start:end] != str(record["raw"]):
            errors.append(f"record[{index}] raw does not match text offsets")
        key = record_key(record)
        if key in seen:
            errors.append(f"record[{index}] duplicate key")
        seen.add(key)
        order = (start, end, str(record["kind"]), str(record["normalized"]))
        if previous is not None and order < previous:
            errors.append(f"record[{index}] output is not sorted")
        previous = order
    return errors


def score_records(predicted: Iterable[dict[str, Any]], gold: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Score exact record keys; matching requires kind, normalized value, and exact offsets."""
    predicted_keys = {record_key(record) for record in predicted}
    gold_keys = {record_key(record) for record in gold}
    by_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"predicted": 0, "gold": 0, "tp": 0, "fp": 0, "fn": 0})
    for kind, *_ in predicted_keys:
        by_kind[kind]["predicted"] += 1
    for kind, *_ in gold_keys:
        by_kind[kind]["gold"] += 1
    for kind, *_ in predicted_keys & gold_keys:
        by_kind[kind]["tp"] += 1
    for kind, *_ in predicted_keys - gold_keys:
        by_kind[kind]["fp"] += 1
    for kind, *_ in gold_keys - predicted_keys:
        by_kind[kind]["fn"] += 1
    metrics = {kind: _rates(values) for kind, values in sorted(by_kind.items())}
    totals = {key: sum(values[key] for values in by_kind.values()) for key in ("predicted", "gold", "tp", "fp", "fn")}
    return {"by_kind": metrics, "overall": _rates(totals)}


def score_manifest(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Score labeled rows and report pending rows separately."""
    rows = list(rows)
    pending = 0
    aggregate: dict[str, dict[str, int]] = {}
    for row in rows:
        if row.get("gold") is None:
            pending += 1
        else:
            scored = score_records(row.get("predicted", []), row.get("gold", []))
            for kind, values in scored["by_kind"].items():
                target = aggregate.setdefault(kind, {"predicted": 0, "gold": 0, "tp": 0, "fp": 0, "fn": 0})
                for key in target:
                    target[key] += int(values[key])
    by_kind = {kind: _rates(values) for kind, values in sorted(aggregate.items())}
    totals = {key: sum(values[key] for values in aggregate.values()) for key in ("predicted", "gold", "tp", "fp", "fn")}
    return {"labeled_rows": sum(1 for row in rows if row.get("gold") is not None), "pending_rows": pending,
            "by_kind": by_kind, "overall": _rates(totals)}


def _rates(values: dict[str, int]) -> dict[str, Any]:
    result = dict(values)
    result["precision"] = values["tp"] / (values["tp"] + values["fp"]) if values["tp"] + values["fp"] else None
    result["recall"] = values["tp"] / (values["tp"] + values["fn"]) if values["tp"] + values["fn"] else None
    p, r = result["precision"], result["recall"]
    result["f1"] = 2 * p * r / (p + r) if p is not None and r is not None and p + r else None
    return result
