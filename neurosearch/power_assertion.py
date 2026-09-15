"""L-21 (EXECUTION-LADDER.md P1A/Stage 3, PRODUCT-INTELLIGENCE-MISSION.md's idle-sleep section): hold a macOS
power assertion (via the `caffeinate` CLI, a thin wrapper over IOPMAssertionCreateWithName) for exactly as long
as there is active or near-future scheduled autonomous work -- not for the whole worker process's lifetime, so
the product's keep-awake claim is tied to real queue state rather than a blanket assumption.

Measured vs. assumed -- what this rung's gate actually asks for. Apple's own System Preferences behavior and
widely reproduced developer reports (this code does not invent a new claim here) establish that a `caffeinate
-s` system-sleep assertion does NOT keep a MacBook awake once the LID IS CLOSED, unless an external display is
attached and macOS's clamshell-mode conditions are met -- that boundary sits below IOPMAssertion, at the
lid-switch/SMC level, and no user-space assertion can override it. This module makes no claim to defeat
lid-closed sleep, and neither should any product message derived from it.

What genuinely still needs a real MacBook's measured answer, not documentation, is narrower: with the assertion
held, lid OPEN, and the DISPLAY allowed to sleep (a display sleep is a different, shallower state than system
sleep) -- does the worker keep running? That is the one open question this rung's gate needs measured, not
assumed; see docs/L21-POWER-ASSERTION.md for the exact two-line test Kyle can run and where to record the
answer."""
from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from . import db

log = logging.getLogger("neurosearch.power_assertion")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_watch_stop = threading.Event()
_watch_thread: threading.Thread | None = None

# A job scheduled more than this far out doesn't justify holding the assertion yet -- holding it for days ahead
# of a single 2am job would defeat the "exactly as long as there is real reason to" premise above.
SCHEDULED_LOOKAHEAD = 24 * 3600


def available() -> bool:
    """False off macOS, or without `caffeinate` on PATH -- callers must never claim a held assertion they can't
    actually take."""
    return sys.platform == "darwin" and shutil.which("caffeinate") is not None


def _work_exists() -> bool:
    row = db.connect().execute(
        "SELECT COUNT(*) n FROM jobs WHERE status='running' OR (status='queued' AND (not_before IS NULL OR not_before <= ?))",
        (time.time() + SCHEDULED_LOOKAHEAD,),
    ).fetchone()
    return (row["n"] or 0) > 0


def _ensure_started() -> None:
    global _proc
    with _lock:
        if _proc is None or _proc.poll() is not None:
            _proc = subprocess.Popen(["caffeinate", "-s"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("power assertion started (pid %s) — active/scheduled work exists", _proc.pid)


def _ensure_stopped() -> None:
    global _proc
    with _lock:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _proc.kill()
            log.info("power assertion released — no active or near-future scheduled work")
        _proc = None


def _loop(poll: float) -> None:
    while not _watch_stop.is_set():
        try:
            (_ensure_started if _work_exists() else _ensure_stopped)()
        except Exception as e:  # noqa: BLE001
            log.warning("power assertion watch skipped a tick: %s", e)
        _watch_stop.wait(poll)
    _ensure_stopped()


def start(poll: float = 30.0) -> bool:
    """Start the watcher thread. Returns whether it actually started (False off macOS / without `caffeinate`) --
    callers (jobs.start_workers) treat False as "nothing to report," never as an error, since most of this
    product's development and CI runs off macOS."""
    global _watch_thread
    if not available():
        return False
    with _lock:
        if _watch_thread is not None and _watch_thread.is_alive():
            return True
        _watch_stop.clear()
        _watch_thread = threading.Thread(target=_loop, args=(poll,), daemon=True, name="ns-power-assertion")
        _watch_thread.start()
    atexit.register(_ensure_stopped)
    return True


def stop() -> None:
    _watch_stop.set()
    if _watch_thread is not None:
        _watch_thread.join(timeout=5)
    _ensure_stopped()


def status() -> dict[str, Any]:
    with _lock:
        held = _proc is not None and _proc.poll() is None
        watching = _watch_thread is not None and _watch_thread.is_alive()
    return {"available": available(), "watching": watching, "held": held}
