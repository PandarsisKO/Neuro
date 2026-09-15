"""Spend tracking and the budget valve.

Every paid API call records an estimated cost. Background jobs check the budget before doing paid work and, when
the daily or monthly budget is reached, re-queue themselves (in order, nothing lost) until the budget window rolls
over or the user raises the limit. A manual pause switch uses the same mechanism.
"""
from __future__ import annotations

import json
import logging
import time
import contextlib
import threading
from datetime import date, datetime, timedelta
from typing import Any

from . import db
from .config import settings

log = logging.getLogger(__name__)

# USD per million tokens (input, output) — override with NEUROSEARCH_PRICES='{"model": [in, out]}'
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-6": (3.0, 15.0), "claude-sonnet-4-5": (3.0, 15.0), "claude-opus": (15.0, 75.0), "claude-haiku": (1.0, 5.0),
    "text-embedding-3-small": (0.02, 0.0), "text-embedding-3-large": (0.13, 0.0),
}
WHISPER_PER_MINUTE = 0.006
WEB_SEARCH_PER_CALL = 0.01
CACHE_WRITE_MULT = 1.25      # 5-minute cache writes cost 1.25x the normal input price
CACHE_READ_MULT = 0.10       # cache reads cost 0.1x
CACHE_MIN_CHARS = 4500       # ~1024 tokens: prefixes shorter than this are never cached by the API, so don't mark them

# findings.extract estimate, calibrated 2026-09-14 (T4 E5) against 8 real metered windows -- 4 Sonnet, 4 Haiku,
# every one a single window, every one cache_read=0 (docs/T4-ADMISSION-2026-09-14.md). The old formula
# (chars/4 in, 600 out, no system prompt) ran 2.0-2.7x UNDER actual spend on both models; these three constants
# are what the data says. tests/test_t4_execute.py::test_estimate_reproduces_measured_spend freezes the points.
FINDINGS_CHARS_PER_TOKEN = 2.5   # measured 2.4-2.6 on Sonnet, 2.9-3.4 on Haiku; 2.5 over-estimates Haiku ~15%, the safe side for a budget gate
FINDINGS_OUT_TOKENS = 1300       # measured mean 1271 (Sonnet) / 1295 (Haiku), range 957-1556, over all 8 windows
FINDINGS_SYSTEM_CHARS = 6200     # fallback when the caller has no request in hand: ~2,000 chars of fixed instructions + the project brief
                                 # (measured 6,222 on the real project; a one-line-brief fixture is ~2,100). Over on small projects = safe side.
                                 # t4._source_estimate passes the exact value; test_estimate_tracks_real_system_prompt guards the fixed part.
BATCH_MULT = 0.5             # Message Batches: 50% off MODEL tokens (input, cache, output) — not off web search, transcription or embeddings


def cache_control() -> dict[str, str]:
    return {"type": "ephemeral"}


def cached_block(text: str, min_chars: int = 0, ttl: str | None = None) -> dict[str, Any]:
    """A system/content text block that ends a cacheable prefix. The API ignores breakpoints on prefixes under
    ~1024 tokens, so callers pass the size of everything before the block in min_chars to skip pointless marks.
    ttl="1h": the longer cache duration (batched requests execute asynchronously; cache hits are best-effort)."""
    b: dict[str, Any] = {"type": "text", "text": text}
    if len(text) + min_chars >= CACHE_MIN_CHARS:
        b["cache_control"] = {**cache_control(), **({"ttl": ttl} if ttl else {})}
    return b


def mark_last(messages: list[dict[str, Any]]) -> None:
    """Move the conversation breakpoint to the last block of the last message (in place). Earlier breakpoints are
    removed — the API still finds the previously cached prefixes, so each tool round / chat turn reads the whole
    earlier conversation from cache and only pays full price for what is new."""
    for m in messages:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict):
                    b.pop("cache_control", None)
    if not messages:
        return
    last = messages[-1]
    if isinstance(last.get("content"), str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    if isinstance(last.get("content"), list) and last["content"] and isinstance(last["content"][-1], dict):
        last["content"][-1]["cache_control"] = cache_control()


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
           searches: int = 0, project_id: str | None = None, source_id: str | None = None, cost: float | None = None,
           cache_read: int = 0, cache_write: int = 0, transport: str = "interactive", saved: float = 0.0,
           price_model: str | None = None, ts: float | None = None) -> float:
    """input_tokens are the UNcached input tokens (as the API reports them); cached ones come separately.
    transport="batch" prices model tokens at BATCH_MULT (the discount stacks with cache pricing); transport="local" is
    the Claude Code provider (cost 0, `saved` = the avoided API spend, passed by the caller).

    **`ts` is when the spend was INCURRED, not when we learned about it (0.62.3).** Everything defaults to now,
    which is right for an interactive call and wrong for a batch: a Message Batch is billed when Anthropic runs it
    and only reaches this ledger when `batches.materialize_ready` collects the results, which can be a day later.

    Measured on Kyle's own data, 2026-09-10. His Console billed **$149.25 on Sep 9** and the app recorded $19.75
    for that day; the next day the app recorded $30.23 against a Console figure of $17.93. Both anomalies are one
    defect: **1,284 batch rows worth $23.18 were written between 15:49 and 16:12 — 647 of them inside a single
    minute — for results Anthropic had computed and charged for the previous day.** So the ledger under-reported the
    day the money was spent and over-reported the day it was collected, and `usage:rate_blocked_until` duly fired
    (`rate_at_block` $17.43, peak rolling hour $23.30 against a $6 ceiling) holding paid background work because of
    money spent a day earlier. A ceiling on spend RATE has to be computed from when spending happened."""
    if cost is None:
        if kind == "whisper":
            cost = seconds / 60 * WHISPER_PER_MINUTE
        else:
            pin, pout = _price(model)
            mult = BATCH_MULT if transport == "batch" else 1.0
            model_cost = ((input_tokens + cache_write * CACHE_WRITE_MULT + cache_read * CACHE_READ_MULT) / 1e6 * pin + output_tokens / 1e6 * pout)
            cost = model_cost * mult + searches * WEB_SEARCH_PER_CALL
            # what the same call would have cost with every token at full, interactive price, minus what it did cost
            full = (input_tokens + cache_write + cache_read) / 1e6 * pin + output_tokens / 1e6 * pout
            saved = full - model_cost * mult
    try:
        with db.tx() as conn:
            conn.execute("INSERT INTO usage (ts, kind, model, input_tokens, output_tokens, seconds, cost, project_id, source_id, cache_read, cache_write, saved, transport, price_model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (float(ts) if ts else time.time(), kind, model, input_tokens, output_tokens, seconds, cost,
                          project_id, source_id, cache_read, cache_write, saved, transport, price_model or model))
    except Exception as e:  # noqa: BLE001
        log.warning("usage record failed: %s", e)
    # A backdated row is spend we are only now LEARNING about, so it can never trip a rate ceiling: the rate it
    # implies already happened, the money is already gone, and holding work now cannot unspend it. The row still
    # counts towards the daily, weekly and monthly TOTALS, which is where late news belongs.
    if cost and not late_booking(ts):
        _update_rate_gate()
    return cost


def late_booking(ts: float | None, *, window: float = 3600.0) -> bool:
    """True when `ts` is older than the rate window — i.e. this row is news about the past, not spending now."""
    return ts is not None and (time.time() - float(ts)) > window


# ------------------------------------------------------------------ the spend-RATE ceiling (0.51.0)
#
# The daily and monthly budgets are ceilings on a TOTAL. They say nothing about how fast that total is reached,
# and on 2026-09-09 that gap cost Kyle $5 in ten minutes: work parked while his credits were empty all resumed the
# instant they were topped up, on top of a background pass that was re-queuing itself every five minutes. Both
# were well inside a $50/day budget the whole time. A rate is the thing a human actually notices, so it is the
# thing the machine should watch.
#
# What it stops is narrow on purpose: paid BACKGROUND work — jobs whose execution policy forces the API, and claim
# extraction. Chat, ingestion, transcription and every local job keep running, because a spending spike must never
# take away the thing the user is sitting in front of.

SPEND_RATE_CEILING = 6.0      # dollars per rolling hour (Kyle's choice: catches a runaway, not a heavy session)
RATE_COOLOFF_S = 600          # how long paid background stays held once the ceiling is hit; re-armed while it holds


def rate_last_hour() -> float:
    try:
        row = db.connect().execute("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE ts >= ?", (time.time() - 3600,)).fetchone()
        return round(float(row["c"]), 4)
    except Exception:  # noqa: BLE001
        return 0.0


def _update_rate_gate() -> None:
    """Maintained by `record` so the gate costs one aggregate per paid call and nothing at claim time."""
    try:
        rate = rate_last_hour()
        if rate > rate_ceiling():
            db.kv_set("usage:rate_blocked_until", str(time.time() + RATE_COOLOFF_S))
            db.kv_set("usage:rate_at_block", str(rate))
    except Exception:  # noqa: BLE001
        pass


def rate_gate() -> dict[str, Any]:
    """Is paid background work held right now, and why — in the user's terms."""
    until = float(db.kv_get("usage:rate_blocked_until") or 0)
    blocked = until > time.time()
    return {"ceiling": rate_ceiling(), "default_ceiling": SPEND_RATE_CEILING, "rate": rate_last_hour(), "blocked": blocked,
            "until": until if blocked else None, "at_block": float(db.kv_get("usage:rate_at_block") or 0) if blocked else None}


def clear_rate_gate() -> None:
    """The user's explicit "carry on" — same shape as the account-gate Re-check: a belief, not a fact."""
    db.kv_set("usage:rate_blocked_until", "0")


def cost_of(resp: Any) -> float:
    """What a response cost at list price (input + cache write 1.25x + cache read 0.1x + output) — computed, not recorded."""
    u = getattr(resp, "usage", None)
    pin, pout = _price(str(getattr(resp, "model", "") or settings.answer_model))
    i, o = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
    cr, cw = int(getattr(u, "cache_read_input_tokens", 0) or 0), int(getattr(u, "cache_creation_input_tokens", 0) or 0)
    return round((i + cw * CACHE_WRITE_MULT + cr * CACHE_READ_MULT) / 1e6 * pin + o / 1e6 * pout, 6)


def record_anthropic(resp: Any, kind: str, project_id: str | None = None, source_id: str | None = None,
                     transport: str = "interactive", ts: float | None = None) -> float:
    u = getattr(resp, "usage", None)
    searches = 0
    try:
        searches = int(getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0)
    except Exception:  # noqa: BLE001
        pass
    if getattr(resp, "provider", None) == "claude_code":
        # L1: the local provider costs $0 here; `saved` records what the SAME tokens would have cost on the task's API model
        # (the "avoided spend" number), priced at the contract's model, never the CLI's
        from . import contracts as C
        from .providers import _tl
        task = str(getattr(_tl, "task", "") or "")
        try:
            api_model = C.contract(task).model if task else settings.answer_model
        except Exception:  # noqa: BLE001
            api_model = settings.answer_model
        pin, pout = _price(api_model)
        i, o = int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)
        cr, cw = int(getattr(u, "cache_read_input_tokens", 0) or 0), int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        priced = (i + cr + cw) / 1e6 * pin + o / 1e6 * pout
        # 0.59.0 — A LOCAL CALL IS FREE ONLY WHEN WE CAN SHOW IT IS.
        #
        # L1 recorded every Claude Code call as cost 0 with `saved` = what the API would have charged, on the
        # assumption that the CLI runs on the user's subscription. Nothing checked. Measured on Kyle's account:
        # app ledger $111.96 for the month, local `saved` $210.55, his Anthropic Console $312.40 — the first two sum
        # to within 3% of the third. Those calls were real charges, and because they were booked at cost 0 they were
        # invisible to the daily budget, the monthly budget, the spend-rate ceiling and Health. He topped up credit
        # for a week wondering where it went, and the app kept telling him he had spent a third of what he had.
        #
        # So: subscription -> free, as before. API key or UNKNOWN -> priced as spend. Unknown counts as billed
        # because assuming free is the error that hid $200, and a wrong bill is recoverable where a hidden one is not.
        from . import claude_code as _cc
        free = _cc.local_is_free()
        return record(kind, str(getattr(resp, "model", "claude-code")), input_tokens=i, output_tokens=o,
                      project_id=project_id, source_id=source_id, cache_read=cr, cache_write=cw,
                      cost=0.0 if free else priced, saved=priced if free else 0.0, transport="local",
                      price_model=api_model, ts=ts)
    return record(kind, getattr(resp, "model", settings.answer_model), input_tokens=int(getattr(u, "input_tokens", 0) or 0),
                  output_tokens=int(getattr(u, "output_tokens", 0) or 0), searches=searches, project_id=project_id, source_id=source_id,
                  cache_read=int(getattr(u, "cache_read_input_tokens", 0) or 0),
                  cache_write=int(getattr(u, "cache_creation_input_tokens", 0) or 0), transport=transport, ts=ts)


def _sum_since(ts: float) -> float:
    row = db.connect().execute("SELECT COALESCE(SUM(cost),0) c FROM usage WHERE ts>=?", (ts,)).fetchone()
    return float(row["c"] or 0)


def totals() -> dict[str, Any]:
    now = datetime.now()
    day0 = datetime(now.year, now.month, now.day).timestamp()
    month0 = datetime(now.year, now.month, 1).timestamp()
    by_kind = {r["kind"]: float(r["c"]) for r in db.connect().execute(
        "SELECT kind, SUM(cost) c FROM usage WHERE ts>=? GROUP BY kind", (month0,)).fetchall()}
    saved = db.connect().execute("SELECT COALESCE(SUM(saved),0) s, COALESCE(SUM(cache_read),0) r FROM usage WHERE ts>=?", (month0,)).fetchone()
    return {"today": round(_sum_since(day0), 4), "month": round(_sum_since(month0), 4), "month_by_kind": by_kind,
            "month_saved": round(float(saved["s"] or 0), 4), "month_cached_tokens": int(saved["r"] or 0),
            "daily_budget": budget("daily"), "monthly_budget": budget("monthly"), "weekly_budget": budget("weekly"),
            "week": round(_sum_since((now - timedelta(days=7)).timestamp()), 4),
            "paused": db.kv_get("queue_paused") == "1"}


def _batch_dating() -> dict[str, Any]:
    """How much batch spend is still dated by collection rather than by when it was incurred.

    Rows written before 0.62.3 are stamped with the moment `materialize_ready` ran, so a day's figure can be wrong
    in both directions and no amount of arithmetic recovers it. This says how much of the ledger is affected instead
    of quietly presenting it as clean: `undated` is batch spend with no `result_at` behind it."""
    try:
        r = db.connect().execute("""SELECT COUNT(*) n, COALESCE(SUM(cost),0) c FROM usage WHERE transport='batch'""").fetchone()
        items = db.connect().execute("""SELECT SUM(CASE WHEN result_at IS NULL THEN 1 ELSE 0 END) undated,
                                               COUNT(*) n FROM batch_items WHERE raw IS NOT NULL""").fetchone()
        return {"batch_rows": int(r["n"] or 0), "batch_dollars": round(float(r["c"] or 0), 2),
                "results_without_a_date": int(items["undated"] or 0), "results": int(items["n"] or 0),
                "note": "batch spend recorded before 0.62.3 is dated when it was collected, not when the provider "
                        "produced it — those days read low and the collection day reads high"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


def reconcile(days: int = 14) -> dict[str, Any]:
    """What the app has recorded, versus what the account was most likely charged (0.59.0).

    The two differ by the local path. Rows written before this release booked Claude Code calls at cost 0 with the
    avoided spend in `saved`; if the CLI was billing an API key, that `saved` figure was really spend. This does not
    rewrite history — it reports both numbers side by side so a month that looked like $112 can be recognised as
    $312 without anyone having to reconstruct it by hand."""
    from . import claude_code as _cc
    conn = db.connect()
    now = datetime.now()
    month0 = datetime(now.year, now.month, 1).timestamp()
    week0 = (now - timedelta(days=7)).timestamp()
    mode = _cc.billing_mode()
    billed = not _cc.local_is_free()

    def window(ts: float) -> dict[str, Any]:
        r = conn.execute("""SELECT COALESCE(SUM(cost),0) c,
                                   COALESCE(SUM(CASE WHEN transport='local' THEN saved ELSE 0 END),0) local_saved,
                                   COUNT(*) n,
                                   SUM(CASE WHEN transport='local' THEN 1 ELSE 0 END) n_local
                            FROM usage WHERE ts>=?""", (ts,)).fetchone()
        rec, loc = float(r["c"] or 0), float(r["local_saved"] or 0)
        # 0.62.3: two things a single figure was hiding, both found while reconciling Kyle's month against his
        # Console. (1) `local_is_free()` can flip inside a window, so the same day can hold local rows priced as
        # charged AND local rows booked free — on 2026-09-10 that was $3.48 charged beside $96.16 booked as avoided,
        # presented as one number. (2) Batch spend is dated when it was incurred now, so a window can contain rows
        # BOOKED later than the day they belong to; naming that is the difference between a reconciliation and a
        # coincidence.
        mixed = conn.execute("""SELECT SUM(CASE WHEN transport='local' AND cost>0 THEN 1 ELSE 0 END) charged,
                                       SUM(CASE WHEN transport='local' AND cost=0 AND saved>0 THEN 1 ELSE 0 END) free,
                                       COALESCE(SUM(CASE WHEN transport='local' AND cost>0 THEN cost ELSE 0 END),0) charged_$
                                FROM usage WHERE ts>=?""", (ts,)).fetchone()
        n_charged, n_free = int(mixed["charged"] or 0), int(mixed["free"] or 0)
        out = {"recorded": round(rec, 2), "local_if_billed": round(loc, 2),
               "likely_total": round(rec + (loc if billed else 0.0), 2),
               "calls": int(r["n"] or 0), "local_calls": int(r["n_local"] or 0)}
        if n_charged and n_free:
            out["mixed_basis"] = {
                "local_charged": n_charged, "local_free": n_free,
                "charged_dollars": round(float(mixed["charged_$"] or 0), 2),
                "note": f"{n_charged} local calls in this window are priced as charged and {n_free} as free — the "
                        "billing mode changed part-way through it, so this total rests on two different bases"}
        return out

    per_day = []
    for row in conn.execute("""SELECT date(ts,'unixepoch','localtime') d, COALESCE(SUM(cost),0) c,
                                      COALESCE(SUM(CASE WHEN transport='local' THEN saved ELSE 0 END),0) ls
                               FROM usage WHERE ts>=? GROUP BY d ORDER BY d DESC""",
                            ((now - timedelta(days=days)).timestamp(),)):
        rec, loc = float(row["c"] or 0), float(row["ls"] or 0)
        per_day.append({"day": row["d"], "recorded": round(rec, 2), "local_if_billed": round(loc, 2),
                        "likely_total": round(rec + (loc if billed else 0.0), 2)})
    return {"billing_mode": mode, "local_is_free": not billed, "note": _cc.billing_note(),
            "month": window(month0), "week": window(week0), "today": window(datetime(now.year, now.month, now.day).timestamp()),
            "per_day": per_day, "batch_dating": _batch_dating(),
            "how_to_read": ("`recorded` is what the app booked, dated when the spend was INCURRED — batch rows carry "
                            "the day the provider produced them, not the day we collected them (0.62.3). "
                            "`local_if_billed` is what the Claude Code path would "
                            "cost on the API — money kept if the CLI runs on your subscription, money spent if it "
                            "runs on your API key. `likely_total` is the one to compare against the Anthropic "
                            "Console. Rows written before 0.59.0 always booked local at zero, whichever it was."),
            "budgets": {"daily": budget("daily"), "monthly": budget("monthly"), "weekly": budget("weekly"),
                        "rate_per_hour": rate_ceiling()}}


def budget(which: str) -> float:
    v = db.kv_get(f"{which}_budget")
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    if which == "weekly":
        return 0.0        # off unless set: Kyle thinks in weeks ("$300 in one week"), so the app can too
    return settings.daily_budget if which == "daily" else settings.monthly_budget


def rate_ceiling() -> float:
    """Dollars per rolling hour. Settable (0.59.0) because the shipped default was chosen against a runaway, not
    against a budget: $6/hour is about $1,000 a week, and Kyle's tolerance is nearer $100-300."""
    v = db.kv_get("spend_rate_ceiling")
    if v is not None:
        try:
            f = float(v)
            if f > 0:
                return f
        except ValueError:
            pass
    return SPEND_RATE_CEILING


def check(estimate: float = 0.0) -> tuple[bool, str, float]:
    """(ok, reason, wait_seconds). ok=False means paid work should wait."""
    if db.kv_get("queue_paused") == "1":
        return False, "queue paused by you — press Resume in Sources", 60
    t = totals()
    now = datetime.now()
    if t["daily_budget"] > 0 and t["today"] + estimate >= t["daily_budget"]:
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        return False, f"daily budget reached (${t['today']:.2f} of ${t['daily_budget']:.2f}) — resumes at midnight or raise it in Settings", max(60, (tomorrow - now).total_seconds())
    wb = budget("weekly")
    if wb > 0:
        w = _sum_since((now - timedelta(days=7)).timestamp())
        if w + estimate >= wb:
            return False, (f"weekly budget reached (${w:.2f} of ${wb:.2f} in the last 7 days) — raise it in Settings "
                           f"or wait for the rolling window to clear"), 3600
    if t["monthly_budget"] > 0 and t["month"] + estimate >= t["monthly_budget"]:
        nm = (datetime(now.year, now.month, 1) + timedelta(days=32)).replace(day=1)
        return False, f"monthly budget reached (${t['month']:.2f} of ${t['monthly_budget']:.2f}) — raise it in Settings to continue", max(60, (nm - now).total_seconds())
    return True, "", 0


class BudgetPaused(RuntimeError):
    def __init__(self, reason: str, wait: float) -> None:
        super().__init__(reason)
        self.wait = wait


_reservation_lock = threading.Lock()
_reservation_local = threading.local()
_reserved_estimate = 0.0


def guard(estimate: float = 0.0) -> None:
    with _reservation_lock:
        own = float(getattr(_reservation_local, "estimate", 0.0) or 0.0)
        ok, reason, wait = check(estimate + max(0.0, _reserved_estimate - own))
    if not ok:
        raise BudgetPaused(reason, wait)


@contextlib.contextmanager
def reserve(estimate: float):
    """Reserve estimated spend so concurrent guards cannot all pass against the same ledger total."""
    global _reserved_estimate
    amount = max(0.0, float(estimate or 0.0))
    with _reservation_lock:
        ok, reason, wait = check(amount + _reserved_estimate)
        if not ok:
            raise BudgetPaused(reason, wait)
        _reserved_estimate += amount
        _reservation_local.estimate = amount
    try:
        yield
    finally:
        with _reservation_lock:
            _reserved_estimate = max(0.0, _reserved_estimate - amount)
            _reservation_local.estimate = 0.0


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


def estimate_findings(n_chars: int, batch: bool = False, system_chars: int | None = None) -> float:
    """Per-window findings.extract estimate at list price: the user content, PLUS the system prompt (billed as a
    cache WRITE at CACHE_WRITE_MULT -- all 8 measured calls were cold-cache, cache_read=0), PLUS the measured
    output allowance. Calibrated 2026-09-14 against real metered spend (constants above); before that it ran
    2-2.7x low, which is what made E5's dry-run say $0.042 for a batch that cost $0.105. `system_chars` defaults
    to the measured prompt size; a caller holding the real request (t4._source_estimate) passes the exact one.
    batch=True applies the Message Batches discount to the MODEL cost only (this is not a claim that all of
    Neuro Search's processing is halved)."""
    from .contracts import contract
    pin, pout = _price(contract("findings.extract").model)
    sys_chars = FINDINGS_SYSTEM_CHARS if system_chars is None else system_chars
    in_tokens = n_chars / FINDINGS_CHARS_PER_TOKEN
    sys_tokens = sys_chars / FINDINGS_CHARS_PER_TOKEN * CACHE_WRITE_MULT
    return ((in_tokens + sys_tokens) / 1e6 * pin + FINDINGS_OUT_TOKENS / 1e6 * pout) * (BATCH_MULT if batch else 1.0)


def estimate_model_call(task: str, n_chars: int) -> float:
    """Conservative admission estimate for a structured call, including its full output allowance."""
    from .contracts import contract
    c = contract(task)
    pin, pout = _price(c.model)
    return n_chars / 4 / 1e6 * pin + c.max_output_tokens / 1e6 * pout


def avoided_this_month() -> float:
    """L1: what the local provider's calls would have cost on the API this month (the `saved` column of
    transport='local' rows). 0.59.0: this is ZERO unless Claude Code is billing a subscription — when the CLI runs on
    an API key those same calls are booked as real cost instead, so `saved` and `cost` can never double-count."""
    now = datetime.now()
    month0 = datetime(now.year, now.month, 1).timestamp()
    row = db.connect().execute("SELECT COALESCE(SUM(saved),0) s FROM usage WHERE ts>=? AND transport='local'", (month0,)).fetchone()
    return round(float(row["s"] or 0), 4)


def local_split(days: int | None = None) -> dict[str, Any]:
    """L4: the AI task split for this month (or the last `days`): how many model calls, what share ran locally, actual API spend
    on those calls, and the API spend the local ones avoided. Counts usage rows of model tasks (whisper excluded)."""
    now = datetime.now()
    since = (now.timestamp() - days * 86400) if days else datetime(now.year, now.month, 1).timestamp()
    row = db.connect().execute(
        "SELECT COUNT(*) n, SUM(CASE WHEN transport='local' THEN 1 ELSE 0 END) n_local, COALESCE(SUM(cost),0) actual, "
        "COALESCE(SUM(CASE WHEN transport='local' THEN saved ELSE 0 END),0) avoided FROM usage WHERE ts>=? AND kind<>'whisper'", (since,)).fetchone()
    n, nl = int(row["n"] or 0), int(row["n_local"] or 0)
    return {"calls": n, "local_calls": nl, "local_share": round(nl / n, 3) if n else 0.0, "actual": round(float(row["actual"] or 0), 4),
            "avoided": round(float(row["avoided"] or 0), 4), "since": since,
            "line": (f"{n:,} AI calls · {round(100 * nl / n)}% local · ${float(row['actual'] or 0):.2f} actual · ${float(row['avoided'] or 0):.2f} avoided" if n else "no AI calls yet")}


def estimate_source_findings(source_id: str, rate_per_min: float | None = None) -> float:
    """What a findings pass over ONE source is expected to cost on the API — the same figure `staleness.assess` quotes,
    in one place so the stale triage (S1) and the acceleration dialog (L3) can never disagree."""
    s = db.get_source(source_id) or {}
    if s.get("duration"):
        return estimate_video(s["duration"], rate_per_min)["analyse"]
    chars = db.connect().execute("SELECT COALESCE(SUM(LENGTH(text)),0) FROM segments WHERE source_id=?", (source_id,)).fetchone()[0]
    return estimate_findings(int(chars or 0))
