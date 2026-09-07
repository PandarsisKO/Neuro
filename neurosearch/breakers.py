"""Rung J2 — durable provider circuit breakers, keyed by provider:OPERATION (never by model).

    anthropic:messages · anthropic:batches · openai:embeddings · openai:transcription

State lives in SQLite (`circuit_breakers`) so every worker and every restart agrees:

    CLOSED  ──(FAILURE_THRESHOLD consecutive TRANSIENT failures)──▶  OPEN
    OPEN    ──(next_probe_at reached)──▶  HALF_OPEN: exactly ONE worker leases the probe; everyone else parks (provider_wait)
    HALF_OPEN probe success ──▶ CLOSED (+ wake every job parked on the operation) · probe transient failure ──▶ OPEN, new next_probe_at

Only transient capacity conditions count — connection failures, timeouts, provider 5xx/529 overload, ordinary rate limits
(429 WITH a retry window). Authentication, permission, billing, invalid request, schema mismatch, refusal, the user's own
budget pause and an account spend cap (429 without a retry window / `enforced_spend_limit_reached`) are typed failures
that never touch a breaker: retrying them is pointless and probing them would be noise. For ordinary rate limits the
provider's retry-after IS next_probe_at — never probe earlier. `generation` is bumped on every open so a worker holding
a stale view cannot close a newer circuit. Deterministic and small on purpose: no rolling scores, no adaptive thresholds.

A job that hits an open circuit raises ProviderUnavailable BEFORE any invocation row is written: it parks in the distinct
`provider_wait` state — 0 attempts, 0 provider invocations, $0 — and is woken automatically when the circuit closes.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from . import db

log = logging.getLogger(__name__)

OPERATIONS = ("anthropic:messages", "anthropic:batches", "openai:embeddings", "openai:transcription")
LABELS = {"anthropic:messages": "Anthropic Messages", "anthropic:batches": "Anthropic Batches", "openai:embeddings": "OpenAI Embeddings", "openai:transcription": "OpenAI Transcription"}
FAILURE_THRESHOLD = 3            # consecutive transient failures that open the circuit
COOLDOWN_S = 60.0                # default wait before the first probe when the provider gave no retry window
COOLDOWN_MAX_S = 15 * 60.0       # a reopened circuit waits longer each time, up to this
PROBE_LEASE_S = 120.0            # a probe that neither succeeded nor failed within this (crashed worker) is released
CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class ProviderUnavailable(RuntimeError):
    """The operation's circuit is open (or another worker holds the half-open probe). Raised BEFORE any provider call."""

    def __init__(self, operation: str, next_probe_at: float | None, state: str) -> None:
        super().__init__(f"{LABELS.get(operation, operation)} is temporarily unavailable")
        self.operation, self.next_probe_at, self.state = operation, next_probe_at, state


def get(operation: str) -> dict[str, Any]:
    r = db.connect().execute("SELECT * FROM circuit_breakers WHERE operation=?", (operation,)).fetchone()
    return db.row_to_dict(r) if r else {"operation": operation, "state": CLOSED, "failures": 0, "opened_at": None, "next_probe_at": None, "last_error_type": None,
                                        "last_error_at": None, "last_success_at": None, "probe_owner": None, "probe_expires_at": None, "generation": 0, "updated_at": None}


def all_states() -> list[dict[str, Any]]:
    return [get(op) for op in OPERATIONS]


def _cooldown(generation: int) -> float:
    return min(COOLDOWN_S * (2 ** max(0, generation - 1)), COOLDOWN_MAX_S)


def gate(operation: str, worker: str) -> dict[str, Any]:
    """Called before a provider call. Returns the breaker row (with `probe` True when THIS worker holds the half-open
    probe lease) or raises ProviderUnavailable. Atomic: one UPDATE claims the lease."""
    t = time.time()
    with db.tx() as conn:
        r = conn.execute("SELECT * FROM circuit_breakers WHERE operation=?", (operation,)).fetchone()
        if not r or r["state"] == CLOSED:
            return {**(db.row_to_dict(r) if r else get(operation)), "probe": False}
        row = db.row_to_dict(r)
        if row["state"] == OPEN and (row["next_probe_at"] or 0) > t:
            raise ProviderUnavailable(operation, row["next_probe_at"], OPEN)
        # OPEN past its probe time, or HALF_OPEN: exactly one worker may probe
        lease_free = row["state"] == OPEN or not row["probe_owner"] or (row["probe_expires_at"] or 0) < t
        if not lease_free:
            raise ProviderUnavailable(operation, row["probe_expires_at"], HALF_OPEN)
        n = conn.execute("UPDATE circuit_breakers SET state=?, probe_owner=?, probe_expires_at=?, updated_at=? WHERE operation=? AND generation=? "
                         "AND (state='open' OR probe_owner IS NULL OR probe_expires_at < ?)",
                         (HALF_OPEN, worker, t + PROBE_LEASE_S, t, operation, row["generation"], t)).rowcount
        if not n:
            raise ProviderUnavailable(operation, row["probe_expires_at"], HALF_OPEN)
        log.info("breaker %s: half-open, probe leased to %s (generation %d)", operation, worker, row["generation"])
        return {**row, "state": HALF_OPEN, "probe_owner": worker, "probe": True}


def record_success(operation: str, worker: str, generation: int | None = None) -> bool:
    """A real provider success. Closes a half-open circuit ONLY if the caller's generation is current (a stale worker
    that started before the circuit reopened cannot close the newer one). Returns True when a circuit was closed."""
    t = time.time()
    closed = False
    with db.tx() as conn:
        r = conn.execute("SELECT * FROM circuit_breakers WHERE operation=?", (operation,)).fetchone()
        if not r:
            conn.execute("INSERT INTO circuit_breakers (operation, state, failures, last_success_at, updated_at) VALUES (?,?,0,?,?)", (operation, CLOSED, t, t))
            return False
        if r["state"] == CLOSED:
            conn.execute("UPDATE circuit_breakers SET failures=0, last_success_at=?, updated_at=? WHERE operation=?", (t, t, operation))
            return False
        if generation is not None and generation != r["generation"]:
            log.warning("breaker %s: ignoring success from a stale worker (generation %s, current %s)", operation, generation, r["generation"])
            return False
        if r["state"] == HALF_OPEN and r["probe_owner"] not in (None, worker):
            return False                                             # not the prober: a stray success does not close it
        conn.execute("UPDATE circuit_breakers SET state=?, failures=0, opened_at=NULL, next_probe_at=NULL, probe_owner=NULL, probe_expires_at=NULL, "
                     "last_success_at=?, updated_at=? WHERE operation=? AND generation=?", (CLOSED, t, t, operation, r["generation"]))
        closed = True
    if closed:
        woken = db.wake_provider_wait(operation)
        log.info("breaker %s: CLOSED by %s after a successful probe; %d waiting job(s) released", operation, worker, woken)
        try:
            db.validation_event("breaker_closed", {"operation": operation, "worker": worker, "woken": woken})
        except Exception:  # noqa: BLE001
            pass
    return closed


def record_failure(operation: str, error_type: str, worker: str, retry_after_s: float | None = None, generation: int | None = None) -> dict[str, Any]:
    """A TRANSIENT provider failure (the caller has already classified it). Opens the circuit at the threshold; a failed
    half-open probe reopens it with a longer cooldown. Non-transient errors must not reach here."""
    t = time.time()
    with db.tx() as conn:
        r = conn.execute("SELECT * FROM circuit_breakers WHERE operation=?", (operation,)).fetchone()
        if not r:
            conn.execute("INSERT INTO circuit_breakers (operation, state, failures, last_error_type, last_error_at, updated_at) VALUES (?,?,1,?,?,?)", (operation, CLOSED, error_type, t, t))
            r = conn.execute("SELECT * FROM circuit_breakers WHERE operation=?", (operation,)).fetchone()
            failures, state, gen = 1, CLOSED, 0
        else:
            failures, state, gen = int(r["failures"]) + 1, r["state"], int(r["generation"])
            if generation is not None and generation != gen and state != CLOSED:
                return db.row_to_dict(r)                             # stale worker: the circuit already moved on
        opens = state == HALF_OPEN or (state == CLOSED and failures >= FAILURE_THRESHOLD) or state == OPEN
        if opens:
            new_gen = gen + 1
            wait = retry_after_s if retry_after_s else _cooldown(new_gen)
            conn.execute("UPDATE circuit_breakers SET state=?, failures=?, opened_at=COALESCE(opened_at, ?), next_probe_at=?, last_error_type=?, last_error_at=?, "
                         "probe_owner=NULL, probe_expires_at=NULL, generation=?, updated_at=? WHERE operation=?",
                         (OPEN, failures, t, t + wait, error_type, t, new_gen, t, operation))
            log.warning("breaker %s: OPEN (generation %d, %s after %d consecutive transient failures); next probe in %.0fs", operation, new_gen, error_type, failures, wait)
            try:
                db.validation_event("breaker_opened", {"operation": operation, "error_type": error_type, "failures": failures, "next_probe_in_s": round(wait), "generation": new_gen})
            except Exception:  # noqa: BLE001
                pass
        else:
            conn.execute("UPDATE circuit_breakers SET failures=?, last_error_type=?, last_error_at=?, updated_at=? WHERE operation=?", (failures, error_type, t, t, operation))
    return get(operation)


def release_probe(operation: str, worker: str) -> None:
    """The prober stopped without a verdict (e.g. cancelled): give the lease back so another worker can probe."""
    with db.tx() as conn:
        conn.execute("UPDATE circuit_breakers SET probe_owner=NULL, probe_expires_at=NULL, updated_at=? WHERE operation=? AND probe_owner=?", (time.time(), operation, worker))


def health() -> list[dict[str, Any]]:
    """Plain-language provider health for the console: label, state, and the next check time when waiting."""
    out = []
    t = time.time()
    for op in OPERATIONS:
        b = get(op)
        st = b["state"]
        if st == CLOSED:
            status, detail = "Healthy", None
        elif st == HALF_OPEN and b.get("probe_owner") and (b.get("probe_expires_at") or 0) > t:
            status, detail = "Checking", "one request is testing whether the provider is back"
        else:
            status, detail = "Waiting", f"provider temporarily unavailable · next check after {time.strftime('%I:%M %p', time.localtime(b['next_probe_at'] or t)).lstrip('0')}"
        out.append({"operation": op, "label": LABELS[op], "state": st, "status": status, "detail": detail, "failures": b["failures"], "next_probe_at": b.get("next_probe_at"),
                    "last_error_type": b.get("last_error_type"), "last_success_at": b.get("last_success_at"), "generation": b.get("generation"),
                    "waiting_jobs": len(db.provider_wait_jobs(op)) if st != CLOSED else 0})
    return out


def wait_message(operation: str, until: float | None) -> str:
    when = time.strftime("%I:%M %p", time.localtime(until or time.time())).lstrip("0")
    return f"Waiting for {LABELS.get(operation, operation)} — provider temporarily unavailable. Next check after {when}."
