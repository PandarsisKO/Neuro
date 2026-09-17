"""R0 (SPEED-MISSION.md) — the timing ledger every later speed rung reports against.

Deliberately NOT a table. A row per HTTP request would add writes to the exact path the mission is
trying to unblock (§A: ~2,000 queries per `/api/sources` on a 3 s poll, with background workers already
holding SQLite's single write lock), and an instrument that slows the thing it measures is worse than
no instrument. The durable history we actually need already exists: `jobs` carries queue wait and work
duration, `invocations` carries per-call model latency, `usage` carries spend. So this module keeps only
what those tables cannot: bounded in-memory samples of in-process work — endpoint duration, cache hit
rates, time-to-first-token — cleared on restart, free to write, impossible to leak.

`api_perf` joins the two halves, which is what makes SPEED-MISSION.md §A reproducible: the baseline
tables in that document regenerate themselves from live data instead of being a one-off measurement.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Any, Iterator

SAMPLES = 200                      # per key; a few hundred keys of 200 floats stays well under a megabyte

_lock = threading.Lock()
_samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=SAMPLES))
_counters: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "miss": 0})


_peak: dict[str, tuple[float, float]] = {}     # key -> (seconds, time.time()) — the worst sample since start, never rolled out


def record(key: str, seconds: float) -> None:
    """One timing sample. Cheap enough to call on every request (a lock and a deque append)."""
    with _lock:
        _samples[key].append(float(seconds))
        # P0 validation (2026-09-17): the 200-sample window rolled a 12.1 s `db:write_hold` out within a minute of
        # commits, so a rare worst case was gone before anyone read it. The peak is kept separately.
        if seconds > _peak.get(key, (0.0, 0.0))[0]:
            _peak[key] = (float(seconds), time.time())


@contextmanager
def timed(key: str) -> Iterator[None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record(key, time.perf_counter() - t0)


def mark(key: str, hit: bool) -> None:
    """Cache instrumentation. R3 has to prove itself with a hit rate, and this is where that comes from."""
    with _lock:
        _counters[key]["hit" if hit else "miss"] += 1


def _pct(vals: list[float], p: float) -> float:
    return vals[min(len(vals) - 1, int(len(vals) * p))] if vals else 0.0


def stats(key: str) -> dict[str, Any] | None:
    with _lock:
        vals = sorted(_samples.get(key) or ())
        peak = _peak.get(key)
    if not vals:
        return None
    out = {"n": len(vals), "p50": round(_pct(vals, 0.5), 4), "p90": round(_pct(vals, 0.9), 4), "max": round(vals[-1], 4)}
    if peak:
        out["peak"], out["peak_at"] = round(peak[0], 4), round(peak[1])
    return out


def snapshot() -> dict[str, Any]:
    """Everything measured in this process since it started. Slowest-first, so the answer to 'what is slow
    right now' is the top of the list rather than something to sort by hand."""
    with _lock:
        keys = list(_samples)
        counters = {k: dict(v) for k, v in _counters.items()}
    timings = {}
    for k in keys:
        s = stats(k)
        if s:
            timings[k] = s
    timings = dict(sorted(timings.items(), key=lambda kv: -kv[1]["p50"]))
    for c in counters.values():
        total = c["hit"] + c["miss"]
        c["rate"] = round(c["hit"] / total, 4) if total else None
    return {"timings": timings, "caches": counters, "samples_kept": SAMPLES}


def slowest(n: int = 5) -> list[dict[str, Any]]:
    """The n slowest keys by p50 — what the Health console shows without making the user read a table."""
    return [{"key": k, **s} for k, s in list(snapshot()["timings"].items())[:n]]


def reset() -> None:
    with _lock:
        _samples.clear()
        _counters.clear()
