"""Derived-state cache keyed on a REVISION, never on a clock (SPEED-MISSION.md R2/R3).

Mission Principle 12: a cache is keyed on an existing revision or content hash, never on elapsed time, so
staleness is impossible by construction rather than by luck. Nothing here has a TTL; an entry is used only
when the caller's revision string still matches the one it was stored under, and any write that changes the
underlying state changes the revision, which retires the entry automatically.

In process, deliberately. The measured targets are per-process derived state (SPEED-MISSION.md §D: "a dict
beats a server"), and there is exactly one process. The cache is bounded, cleared on restart, and carries no
durable meaning — anything that must survive a restart belongs in SQLite.

`compute()` runs OUTSIDE the lock: a cold entry can take over a second, and holding a global lock across it
would turn a cache into the contention it exists to remove. Two threads racing the same cold key both compute
and the last write wins, which is harmless for pure derived state and much cheaper than serialising.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from . import perf

MAX_ENTRIES = 512                  # per-project derived state; far more than a local install will ever hold

_lock = threading.Lock()
_store: dict[str, tuple[str, Any]] = {}          # key -> (revision, value)


def get_or_compute(key: str, revision: str, compute: Callable[[], Any], *, label: str | None = None) -> Any:
    """Return the cached value for `key` if it was stored under this exact `revision`, else compute and store it.
    Every call records a hit or a miss under `label`, because a cache that cannot show its hit rate cannot be
    shown to have earned its place (the Health console reads these)."""
    with _lock:
        hit = _store.get(key)
    if hit is not None and hit[0] == revision:
        perf.mark(label or key.split(":", 1)[0], True)
        return hit[1]
    perf.mark(label or key.split(":", 1)[0], False)
    value = compute()
    with _lock:
        if len(_store) >= MAX_ENTRIES and key not in _store:
            _store.pop(next(iter(_store)), None)          # crude FIFO trim; entries are cheap and self-retiring
        _store[key] = (revision, value)
    return value


def invalidate(prefix: str = "") -> int:
    """Drop entries whose key starts with `prefix` (everything when empty). Correctness never depends on this —
    revisions already retire stale entries — but tests and manual recovery want an explicit lever."""
    with _lock:
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            _store.pop(k, None)
        return len(keys)


def size() -> int:
    with _lock:
        return len(_store)
