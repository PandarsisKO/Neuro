"""Spend tracking and the budget valve.

Every paid API call records an estimated cost. Background jobs check the budget before doing paid work and, when
the daily or monthly budget is reached, re-queue themselves (in order, nothing lost) until the budget window rolls
over or the user raises the limit. A manual pause switch uses the same mechanism.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

# USD per million tokens (input, output) — override with NEUROSEARCH_PRICES='{"model": [in, out]}'
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0), "claude-sonnet-4-5": (3.0, 15.0), "claude-opus": (15.0, 75.0), "claude-haiku": (0.8, 4.0),
    "text-embedding-3-small": (0.02, 0.0), "text-embedding-3-large": (0.13, 0.0),
}
WHISPER_PER_MINUTE = 0.006
WEB_SEARCH_PER_CALL = 0.01


def _price(model: str) -> tuple[float, float]:
    try:
        override = json.loads(settings.prices_json or "{}")
        for k, v in override.items():
            if k in model:
                return float(v[0]), float(v[1])
    except (ValueError, TypeError):
        pass
    for k, v in PRICES.items():
        if k in model:
            return v
    return (3.0, 15.0)


def record(kind: str, model: str, *, input_tokens: int = 0, output_tokens: int = 0, seconds: float = 0,
           searches: int = 0, project_id: str | None = None, source_id: str | None = None, cost: float | None = None) -> float:
    if cost is None:
        if kind == "whisper":
            cost = seconds / 60 * WHISPER_PER_MINUTE
        else:
            pin, pout = _price(model)
            cost = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout + searches * WEB_SEARCH_PER_CALL
    try:
        with db.tx() as conn:
            conn.execute("INSERT INTO usage (ts, kind, model, input_tokens, output_tokens, seconds, cost, project_id, source_id) VALUES (?,?,?,?,?,?,?,?,?)",
                         (time.time(), kind, model, input_tokens, output_tokens, seconds, cost, project_id, source_id))
    except Exception as e:  # noqa: BLE001
        log.warning("usage record failed: %s", e)
    return cost


def record_anthropic(resp: Any, kind: str, project_id: str | None = None, source_id: str | None = None) -> float:
    u = getattr(resp, "usage", None)
    searches = 0
    try:
        searches = int(getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    return record(kind, getattr(resp, "model", settings.answer_model), input_tokens=int(getattr(u, "input_tokens", 0) or 0),
                  output_tokens=int(getattr(u, "output_tokens", 0) or 0), searches=searches, project_id=project_id, source_id=source_id)


def _sum_since(ts: float) -> float:
    row = db.connect().execute("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE ts>=?", (ts,)).fetchone()
    return float(row["c"] or 0)


def totals() -> dict[str, Any]:
    now = datetime.now()
    day0 = datetime(now.year, now.month, now.day).timestamp()
    month0 = datetime(now.year, now.month, 1).timestamp()
    by_kind = {r["kind"]: float(r["c"]) for r in db.connect().execute(
        "SELECT kind, SUM(cost) c FROM usage WHERE ts>=? GROUP BY kind", (month0,)).fetchall()}
    return {"today": round(_sum_since(day0), 4), "month": round(_sum_since(month0), 4), "month_by_kind": by_kind,
            "daily_budget": budget("daily"), "monthly_budget": budget("monthly"), "paused": db.kv_get("queue_paused") == "1"}


def budget(which: str) -> float:
    v = db.kv_get(f"{which}_budget")
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    return settings.daily_budget if which == "daily" else settings.monthly_budget


def check(estimate: float = 0.0) -> tuple[bool, str, float]:
    """(ok, reason, wait_seconds). ok=False means paid work should wait."""
    if db.kv_get("queue_paused") == "1":
        return False, "queue paused by you — press Resume in Sources", 60
    t = totals()
    now = datetime.now()
    if t["daily_budget"] > 0 and t["today"] + estimate >= t["daily_budget"]:
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        return False, f"daily budget reached (${t['today']:.2f} of ${t['daily_budget']:.2f}) — resumes at midnight or raise it in Settings", max(60, (tomorrow - now).total_seconds())
    if t["monthly_budget"] > 0 and t["month"] + estimate >= t["monthly_budget"]:
        nm = (datetime(now.year, now.month, 1) + timedelta(days=32)).replace(day=1)
        return False, f"monthly budget reached (${t['month']:.2f} of ${t['monthly_budget']:.2f}) — raise it in Settings to continue", max(60, (nm - now).total_seconds())
    return True, "", 0


class BudgetPaused(RuntimeError):
    def __init__(self, reason: str, wait: float) -> None:
        super().__init__(reason)
        self.wait = wait


def guard(estimate: float = 0.0) -> None:
    ok, reason, wait = check(estimate)
    if not ok:
        raise BudgetPaused(reason, wait)


def estimate_transcription(duration_s: float | None) -> float:
    return (duration_s or 0) / 60 * WHISPER_PER_MINUTE


CHARS_PER_MINUTE = 1000      # ~150 wpm of speech plus timestamp prefixes


def estimate_video(duration_s: float | None, rate_per_min: float | None = None) -> dict[str, float]:
    """Expected cost of one video that arrives with captions: findings analysis + embeddings (transcription is
    free when captions exist). Returns {"analyse": $, "whisper": $ if captions turn out to be missing}."""
    mins = max((duration_s or 0) / 60, 1.0)
    if rate_per_min is not None:
        analyse = mins * rate_per_min
    else:
        from .findings import WINDOW_CHARS
        chars = mins * CHARS_PER_MINUTE
        windows = max(1, int(-(-chars // WINDOW_CHARS)))
        pin, pout = _price(settings.answer_model)
        analyse = (chars / 4 + windows * 1500) / 1e6 * pin + windows * 800 / 1e6 * pout
        analyse += chars / 4 / 1e6 * _price(settings.embedding_model)[0]
    return {"analyse": round(analyse, 4), "whisper": round(mins * WHISPER_PER_MINUTE, 4)}


def observed_rate_per_minute(min_sources: int = 5) -> float | None:
    """What findings analysis has actually cost per minute of video so far (None until enough history)."""
    try:
        row = db.connect().execute(
            """SELECT COUNT(DISTINCT u.source_id) n, SUM(u.cost) c, SUM(s.duration) d
               FROM (SELECT source_id, SUM(cost) cost FROM usage WHERE kind='findings' AND source_id IS NOT NULL GROUP BY source_id) u
               JOIN sources s ON s.id=u.source_id WHERE s.duration>0""").fetchone()
        if row and row["n"] and row["n"] >= min_sources and row["d"]:
            return float(row["c"]) / (float(row["d"]) / 60)
    except Exception:  # noqa: BLE001
        pass
    return None


def estimate_findings(n_chars: int) -> float:
    # ~4 chars per token in, ~600 tokens out per window
    pin, pout = _price(settings.answer_model)
    return n_chars / 4 / 1e6 * pin + 0.0006 * pout
