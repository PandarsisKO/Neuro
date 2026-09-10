"""Derived-state cache keyed on a REVISION, never on a clock (SPEED-MISSION.md R2/R3).

Mission Principle 12: a cache is keyed on an existing revision or content hash, never on elapsed time, so
staleness is impossible by construction rather than by luck. Nothing here has a TTL; an entry is used only
when the caller's revision string still matches the one it was stored under, and any write that changes the
underlying state changes the revision, which retires the entry automatically.

In process, deliberately. The measured targets are per-process derived state (SPEED-MISSION.md §D: "a dict
beats a server"), and there is exactly one process. The cache is bounded, cleared on restart, and carries no
durable meaning — anything that must survive a restart belongs in SQLite.

`compute()` runs OUTSIDE the global lock: a cold entry can take over a second, and holding one lock across it
would turn a cache into the contention it exists to remove. But two threads racing the same cold key must not
both compute — that was harmless when a cold pass cost a second and is not harmless now (0.61.2).

**Measured on Kyle's live project, 2026-09-10, while the app was locked up for him:** the findings-quality pass
takes **11.5 s** over 12,805 findings and the workbench query 2.0 s, so opening the Findings tab asked for 13.5 s
of CPU in one process — and until 0.61.0 the tab re-asked every four seconds. Worse, every concurrent miss on the
same key ran its own copy of the 11.5 s pass. So this module gained two things a cache of an expensive pass needs:

* **single flight** — one computation per (key, revision); everyone else waits for it or takes the stale value;
* **stale while revalidating** — `get_stale_ok` returns the previous value at once and recomputes in a background
  thread, so a screen shows a slightly old duplicate count instead of blocking for eleven seconds. Correctness is
  unaffected: the value returned is always one the app itself computed, and the revision it was computed under is
  returned with it so a caller can say "as of a moment ago" rather than implying it is current.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from . import perf

MAX_ENTRIES = 512                  # per-project derived state; far more than a local install will ever hold

_lock = threading.Lock()
_store: dict[str, tuple[str, Any]] = {}          # key -> (revision, value)
_flight: dict[str, threading.Lock] = {}          # key -> the lock whoever is computing it holds
_running: set[str] = set()                       # keys with a background recompute in flight


def _put(key: str, revision: str, value: Any) -> None:
    with _lock:
        if len(_store) >= MAX_ENTRIES and key not in _store:
            _store.pop(next(iter(_store)), None)          # crude FIFO trim; entries are cheap and self-retiring
        _store[key] = (revision, value)


def _flight_lock(key: str) -> threading.Lock:
    with _lock:
        lk = _flight.get(key)
        if lk is None:
            lk = _flight[key] = threading.Lock()
        return lk


def peek(key: str) -> tuple[str, Any] | None:
    """(revision, value) as stored, whatever revision that is. For callers that can use a slightly old answer."""
    with _lock:
        return _store.get(key)


def get_or_compute(key: str, revision: str, compute: Callable[[], Any], *, label: str | None = None) -> Any:
    """Return the cached value for `key` if it was stored under this exact `revision`, else compute and store it.

    Single flight: one thread computes a cold key and the others wait for its result rather than each running the
    same expensive pass. Every call records a hit or a miss under `label`, because a cache that cannot show its hit
    rate cannot be shown to have earned its place (the Health console reads these)."""
    hit = peek(key)
    if hit is not None and hit[0] == revision:
        perf.mark(label or key.split(":", 1)[0], True)
        return hit[1]
    perf.mark(label or key.split(":", 1)[0], False)
    with _flight_lock(key):
        again = peek(key)                       # someone may have computed it while we waited for the lock
        if again is not None and again[0] == revision:
            return again[1]
        value = compute()
        _put(key, revision, value)
        return value


def get_stale_ok(key: str, revision: str, compute: Callable[[], Any], *, label: str | None = None,
                 warm: bool = True) -> dict[str, Any]:
    """The expensive-pass variant: never block on a cold recompute if there is anything to show.

    Returns `{"value", "revision", "current", "pending"}`. A stored value under a different revision is returned
    immediately with `current: False`, and one background thread refreshes it. Nothing is fabricated: the value is
    always one this app computed, and `current` says whether it still matches the state it was computed from."""
    hit = peek(key)
    if hit is not None and hit[0] == revision:
        perf.mark(label or key.split(":", 1)[0], True)
        return {"value": hit[1], "revision": hit[0], "current": True, "pending": False}
    perf.mark(label or key.split(":", 1)[0], False)
    if hit is None:
        if not warm:
            return {"value": None, "revision": None, "current": False, "pending": True}
        value = get_or_compute(key, revision, compute, label=label)      # nothing to show: compute it once
        return {"value": value, "revision": revision, "current": True, "pending": False}
    _refresh_later(key, revision, compute, label)
    return {"value": hit[1], "revision": hit[0], "current": False, "pending": True}


def _refresh_later(key: str, revision: str, compute: Callable[[], Any], label: str | None) -> None:
    with _lock:
        if key in _running:
            return
        _running.add(key)

    def run() -> None:
        try:
            get_or_compute(key, revision, compute, label=label)
        except Exception:  # noqa: BLE001 — a background refresh must never take the process down
            pass
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=run, name=f"cache-refresh:{key[:40]}", daemon=True).start()


def refreshing() -> list[str]:
    with _lock:
        return sorted(_running)


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
