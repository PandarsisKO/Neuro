"""Rung H1 — the findings window pre-filter: a conservative REJECTION filter in front of findings.extract.

The cheap model answers exactly one question about one transcript window:

    Does this window have ANY plausible value to this project's research brief?   → keep | uncertain | drop

and nothing else — not "is this source good", never "what are the findings". Routing:

    keep      → findings.extract (Sonnet 5), unchanged
    uncertain → findings.extract, unchanged
    drop      → the window is not analysed (the only outcome that saves money)

Everything that is not a confident model decision fails OPEN: provider error, timeout, refusal, truncation, malformed or
schema-invalid output, exhausted budget, an unexpected exception → `uncertain` with `fail_open` naming why. The filter
is off unless NEUROSEARCH_FINDINGS_PREFILTER=1 (settings.findings_prefilter); the unfiltered path stays the rollback.

Optimisation target (not classifier accuracy): maximise safely avoided findings.extract work subject to essentially zero
relevant-window false negatives. `neurosearch eval --prefilter` measures recall, nugget reachability, drop rate,
tokens avoided, filter cost, net savings and filter leverage on the labeled window fixture.

Provenance: every decision is a `window_decisions` row keyed by an input hash (window text, brief revision, prompt
version, schema version, configured model) — changing the filter's prompt/schema/model re-evaluates; the analysis
row's `prefilter` column summarises keep/uncertain/drop/fail-open for the source.

Anomaly signal: a source with ≥ ANOMALY_MIN_WINDOWS windows whose drop share reaches ANOMALY_DROP_SHARE is NOT
overridden (no hidden quota) but is flagged: validation event `prefilter_aggressive` + kv `evidence:prefilter_aggressive`
→ Health. Suspicious aggressiveness is visible, never silently trusted.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

TASK = "findings.prefilter"
DECISIONS = ("keep", "uncertain", "drop")
ANOMALY_DROP_SHARE = 0.8              # a source losing ≥ 80% of its windows to 'drop' …
ANOMALY_MIN_WINDOWS = 3               # … when it has at least this many windows is flagged (signal, not a quota)
SAMPLE_CHARS = int(os.environ.get("NEUROSEARCH_PREFILTER_SAMPLE_CHARS", "0") or 0)   # 0 = the filter reads the WHOLE window (recall first)

SYSTEM = """You are a triage assistant in front of an expensive research analyst. You will see a research project's brief and ONE
window of a transcript (or document). Decide only whether this window has ANY plausible value to the brief.

Rules:
- "drop" ONLY when you are confident the window contains nothing of plausible value to the brief: a different subject
  throughout, with no passage — not even a brief aside — that touches the brief's topics, numbers, rules, methods, warnings or examples.
- "keep" when the window clearly addresses the brief's topics.
- "uncertain" whenever you cannot rule value out: mixed content, tangents that might contain one useful passage, an
  unfamiliar angle, low-quality transcription, or anything you did not read closely enough to be sure.
- A single relevant passage buried in unrelated talk makes the window valuable. When in doubt, do not drop.
- You are not extracting findings and not judging the source's overall quality; you are only deciding whether the
  analyst should read this window.
Answer with the decision and one short reason."""


def prompt_version() -> str:
    return "prefilter-" + hashlib.sha1(SYSTEM.encode()).hexdigest()[:8]


def schema_version() -> str | None:
    from .contracts import contract
    return contract(TASK).schema


def enabled() -> bool:
    return bool(settings.findings_prefilter)


def sample(window: str, sample_chars: int | None = None) -> str:
    """What the filter reads. Default (0): the whole window. With a budget: head, three evenly spaced slices and the
    tail, each marked, so the model knows it is looking at excerpts of a longer window."""
    n = SAMPLE_CHARS if sample_chars is None else sample_chars
    if n <= 0 or len(window) <= n:
        return window
    head = int(n * 0.35); tail = int(n * 0.2); mid = n - head - tail
    piece = mid // 3
    parts = [window[:head]]
    for k in (0.3, 0.5, 0.7):
        at = int(len(window) * k)
        parts.append(window[at:at + piece])
    parts.append(window[-tail:])
    return "\n[…]\n".join(parts) + f"\n\n(You are seeing {n:,} of {len(window):,} characters of this window: the beginning, three slices from the middle, and the end.)"


def _head(project: dict[str, Any], src: dict[str, Any]) -> str:
    brief = project.get("brief") or "(no brief — anything substantive and reusable counts as value)"
    return f"PROJECT: {project['name']}\nBRIEF: {brief}\n{db.project_steering(project)}\n\nSOURCE: {src['title']} ({src.get('channel') or src['platform']})"


def input_hash(project: dict[str, Any], window: str, sample_chars: int | None = None) -> str:
    from .contracts import contract
    c = contract(TASK)
    n = SAMPLE_CHARS if sample_chars is None else sample_chars
    return db._sha("prefilter", hashlib.sha1(window.encode()).hexdigest(), db.brief_revision(project), prompt_version(), c.schema or "text", c.model, str(n))


def request(project: dict[str, Any], src: dict[str, Any], window_index: int, windows: int, window: str, sample_chars: int | None = None) -> dict[str, Any]:
    """The exact request content (for the eval's token counting and for batch transport later)."""
    from . import usage
    part = f" (part {window_index + 1}/{windows})" if windows > 1 else ""
    text = sample(window, sample_chars)
    return {"system": [{"type": "text", "text": SYSTEM}, usage.cached_block(_head(project, src), min_chars=len(SYSTEM))],
            "messages": [{"role": "user", "content": f"WINDOW{part}:\n{text}\n\nDecide: keep, uncertain or drop."}], "sample_chars": len(text)}


def decide(project: dict[str, Any], src: dict[str, Any], window_index: int, windows: int, window: str, *, sample_chars: int | None = None) -> dict[str, Any]:
    """One decision, durable and idempotent (same inputs → the stored row, no second call). Never raises: any failure
    is a fail-open 'uncertain' with the reason recorded."""
    from . import providers, usage
    from .contracts import contract
    pid, sid = project["id"], src["id"]
    ih = input_hash(project, window, sample_chars)
    cached = db.window_decision_get(pid, sid, window_index, ih)
    if cached:
        return {**cached, "cached": True}
    c = contract(TASK)
    req = request(project, src, window_index, windows, window, sample_chars)
    row: dict[str, Any] = {"project_id": pid, "source_id": sid, "window_index": window_index, "windows": windows, "input_hash": ih, "decision": "uncertain",
                           "reason": None, "fail_open": None, "model": None, "configured_model": c.model, "prompt_version": prompt_version(),
                           "schema_version": c.schema, "window_chars": len(window), "sample_chars": req["sample_chars"], "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
    try:
        out = providers.invoke_structured(TASK, system=req["system"], messages=req["messages"], usage_kind="prefilter", project_id=pid, source_id=sid)
        resp = providers.last_response()
        u = getattr(resp, "usage", None)
        d = str(out.get("decision") or "").lower()
        if d not in DECISIONS:
            raise ValueError(f"decision {d!r} outside {DECISIONS}")
        row.update({"decision": d, "reason": str(out.get("reason") or "")[:200], "model": getattr(resp, "model", None) or c.model,
                    "input_tokens": int(getattr(u, "input_tokens", 0) or 0) + int(getattr(u, "cache_read_input_tokens", 0) or 0) + int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                    "output_tokens": int(getattr(u, "output_tokens", 0) or 0), "cost": usage.cost_of(resp)})
    except usage.BudgetPaused:
        raise                                                            # the budget valve is not a filter failure: the job parks as usual
    except Exception as e:  # noqa: BLE001 — fail OPEN, by contract
        detail = getattr(e, "error_type", None) or getattr(e, "kind", None)
        row.update({"decision": "uncertain", "fail_open": f"{type(e).__name__}{f'({detail})' if detail else ''}: {str(e)[:160]}"})
        db.validation_event("prefilter_fail_open", {"error": row["fail_open"], "window_index": window_index}, project_id=pid, source_id=sid, model=c.model, prompt_version=prompt_version())
        db.kv_bump("evidence:prefilter_fail_open")
        log.warning("prefilter failed open for %s window %d: %s", sid[:8], window_index, row["fail_open"])
    db.window_decision_put(row)
    db.kv_bump(f"evidence:prefilter_{row['decision']}")
    return {**row, "cached": False}


def decide_windows(project: dict[str, Any], src: dict[str, Any], windows: list[str], *, sample_chars: int | None = None) -> list[dict[str, Any]]:
    """Decisions for every window of a source + the anomaly check. Returns one row per window (same order)."""
    rows = [decide(project, src, i, len(windows), w, sample_chars=sample_chars) for i, w in enumerate(windows)]
    dropped = sum(1 for r in rows if r["decision"] == "drop")
    if len(rows) >= ANOMALY_MIN_WINDOWS and dropped / len(rows) >= ANOMALY_DROP_SHARE:
        db.validation_event("prefilter_aggressive", {"windows": len(rows), "dropped": dropped, "share": round(dropped / len(rows), 3)},
                            project_id=project["id"], source_id=src["id"], model=rows[0].get("configured_model"), prompt_version=prompt_version())
        db.kv_bump("evidence:prefilter_aggressive")
        log.warning("prefilter dropped %d/%d windows of %s — flagged as suspiciously aggressive (not overridden)", dropped, len(rows), src["id"][:8])
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the analysis row records about the filter for this source."""
    if not rows:
        return {}
    return {"windows": len(rows), "keep": sum(1 for r in rows if r["decision"] == "keep"), "uncertain": sum(1 for r in rows if r["decision"] == "uncertain" and not r.get("fail_open")),
            "drop": sum(1 for r in rows if r["decision"] == "drop"), "fail_open": sum(1 for r in rows if r.get("fail_open")),
            "dropped_chars": sum(int(r.get("window_chars") or 0) for r in rows if r["decision"] == "drop"),
            "model": rows[0].get("model") or rows[0].get("configured_model"), "configured_model": rows[0].get("configured_model"),
            "prompt_version": rows[0].get("prompt_version"), "schema_version": rows[0].get("schema_version"),
            "cost": round(sum(float(r.get("cost") or 0) for r in rows), 6)}
