"""Rung I2 — candidate-only listwise reranker (EXPERIMENT, off by default: NEUROSEARCH_RETRIEVAL_RERANK=1).

    existing FTS + vectors + RRF  →  top RERANK_DEPTH chunks  →  Haiku `retrieval.rerank`  →  the SAME chunks, reordered
                                     positions after the depth keep their RRF order; downstream retrieval is unchanged

One clean question: can a cheap model reorder the exact candidates we already retrieve substantially better than RRF
alone? So the stage may only permute the supplied candidates — never add, drop or duplicate one — and everything that is
not a valid permutation (provider error, timeout, refusal, truncation, schema mismatch, duplicate / missing / unknown
number, any unexpected exception) fails CLOSED to the current RRF ordering, exactly. Retrieval never becomes unavailable
because reranking failed. Chunks are reranked, not sources: exact-locator improvement is one of the opportunities.

Provenance: each reordered hit carries `rerank` = {from: original position, version, model}; `last()` exposes the
call's details (applied, fallback reason, tokens, cost, latency, order) for the eval and Health; usage kind "rerank".
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

TASK = "retrieval.rerank"
RERANK_DEPTH = 11                       # I1.5 live baseline: deepest expected target at position 9, +2 frozen safety margin
TEXT_CHARS = 700                        # per candidate: enough to judge relevance and exact location, small enough to stay cheap

SYSTEM = """You are a retrieval reranker for a personal research knowledge base of transcripts and documents. You will see a
question and a numbered list of candidate passages that were already retrieved for it. Order ALL the candidates from the
passage that answers the question most directly and precisely to the least useful one.

Rules:
- Prefer the passage that actually states the answer (the exact number, rule, name or recommendation asked about) over
  passages that merely share vocabulary with the question or discuss the topic in general.
- Prefer authoritative, specific statements over vague, promotional or contradictory ones — but a passage that directly
  answers the question is relevant even if you suspect it is wrong.
- The same words in a different sense (a 'standby generator' for a 'standby seller note') are not relevant.
- Output every candidate number exactly once."""

_last = threading.local()


def prompt_version() -> str:
    return "rerank-" + hashlib.sha1((SYSTEM + str(TEXT_CHARS)).encode()).hexdigest()[:8]


def enabled() -> bool:
    return bool(settings.retrieval_rerank)


def last() -> dict[str, Any] | None:
    return getattr(_last, "info", None)


def _candidate_line(i: int, h: dict[str, Any]) -> str:
    text = (h.get("text") or "").strip().replace("\n", " ")
    if len(text) > TEXT_CHARS:
        text = text[:TEXT_CHARS].rsplit(" ", 1)[0] + " …"
    where = h.get("timestamp") or ""
    src = h.get("title") or h.get("url") or "source"
    ch = h.get("channel")
    return f"[{i}] {src}{f' ({ch})' if ch else ''} @ {where}\n{text}"


def request(query: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    body = "\n\n".join(_candidate_line(i + 1, h) for i, h in enumerate(hits))
    return {"system": SYSTEM,
            "messages": [{"role": "user", "content": f"QUESTION: {query}\n\nCANDIDATES ({len(hits)}):\n\n{body}\n\nReturn the order: every number from 1 to {len(hits)} exactly once, best first."}]}


def validate_order(order: Any, n: int) -> str | None:
    """None when `order` is a permutation of 1..n; else the reason (the fail-closed trigger)."""
    if not isinstance(order, list):
        return "order is not a list"
    try:
        nums = [int(x) for x in order]
    except (TypeError, ValueError):
        return "non-integer candidate number"
    if len(nums) != n:
        return f"{'missing' if len(nums) < n else 'extra'} candidates ({len(nums)} of {n})"
    if len(set(nums)) != n:
        return "duplicate candidate numbers"
    if set(nums) != set(range(1, n + 1)):
        return "unknown candidate numbers"
    return None


def rerank(query: str, hits: list[dict[str, Any]], depth: int | None = None) -> list[dict[str, Any]]:
    """Reorder the first `depth` hits with the model; the rest keep their order. Returns the new list (same objects,
    same candidate set). On ANY failure returns `hits` unchanged and records why."""
    from . import providers, usage
    from .contracts import contract
    d = min(depth or RERANK_DEPTH, len(hits))
    info: dict[str, Any] = {"applied": False, "fallback": None, "depth": d, "candidates": len(hits), "version": prompt_version(), "schema": None,
                            "configured_model": None, "model": None, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "latency_s": 0.0, "order": None}
    _last.info = info
    if d < 2:
        info["fallback"] = "nothing to rerank"
        return hits
    c = contract(TASK)
    info["configured_model"], info["schema"] = c.model, c.schema
    head = hits[:d]
    req = request(query, head)
    t0 = time.time()
    try:
        out = providers.invoke_structured(TASK, system=req["system"], messages=req["messages"], usage_kind="rerank")
        resp = providers.last_response()
        u = getattr(resp, "usage", None)
        info.update({"model": getattr(resp, "model", None) or c.model,
                     "input_tokens": int(getattr(u, "input_tokens", 0) or 0) + int(getattr(u, "cache_read_input_tokens", 0) or 0) + int(getattr(u, "cache_creation_input_tokens", 0) or 0),
                     "output_tokens": int(getattr(u, "output_tokens", 0) or 0), "cost": usage.cost_of(resp)})
        why = validate_order(out.get("order"), d)
        if why:
            raise ValueError(why)
        order = [int(x) for x in out["order"]]
    except usage.BudgetPaused:
        info["fallback"] = "budget paused"
        info["latency_s"] = round(time.time() - t0, 3)
        return hits
    except Exception as e:  # noqa: BLE001 — fail CLOSED to the RRF ordering, whatever happened
        detail = getattr(e, "error_type", None) or getattr(e, "kind", None)
        info["fallback"] = f"{type(e).__name__}{f'({detail})' if detail else ''}: {str(e)[:160]}"
        info["latency_s"] = round(time.time() - t0, 3)
        log.warning("rerank fell back to the retrieval ordering: %s", info["fallback"])
        try:
            from . import db
            db.validation_event("rerank_fallback", {"reason": info["fallback"], "candidates": d}, model=c.model, prompt_version=prompt_version())
            db.kv_bump("evidence:rerank_fallback")
        except Exception:  # noqa: BLE001
            pass
        return hits
    info["latency_s"] = round(time.time() - t0, 3)
    info["applied"] = True
    info["order"] = order
    reordered = []
    for new_pos, num in enumerate(order):
        h = dict(head[num - 1])
        h["rerank"] = {"from": num - 1, "to": new_pos, "version": prompt_version(), "model": info["model"]}
        reordered.append(h)
    try:
        from . import db
        db.kv_bump("evidence:rerank_applied")
    except Exception:  # noqa: BLE001
        pass
    return reordered + hits[d:]
