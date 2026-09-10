"""S6 — a walled account stops the queue instead of being rediscovered job by job (0.59.0).

Measured on Kyle's live database: **624 `BILLING` attempts on 2026-09-09** and **48 `SPEND_CAP` attempts inside 13
minutes on 2026-09-10**. Every one was refused by Anthropic in about 0.4 seconds and cost nothing — but
`db.claim_job` never consulted the account gates, so a capped account did not stop the queue, it walked the queue
THROUGH the wall: claim a paid job, get refused, park it for 30 days, claim the next.

The cost was never money. It was worker slots that free work could have used, a Jobs panel that reads as a
catastrophe when the truth is "the account is capped", and hundreds of ledger rows that make real spend impossible
to see — those rows are exactly why the first read of that ledger looked like it was undercounting.

This is the smallest useful slice of SCHEDULER-ADMISSION.md: a decision taken BEFORE a job is claimed about whether
the work can succeed at all.
"""
from __future__ import annotations

import time

import pytest

from neurosearch import db


@pytest.fixture(autouse=True)
def _clean_gates():
    db.init_db()
    for g in db.ACCOUNT_GATES:
        db.kv_set(g, "0")
    db.kv_set("usage:rate_blocked_until", "0")
    db.kv_set("background_paused", "0")
    # the suite shares one database, and claiming is FIFO — retire anything another module left queued so these
    # tests are asserting about their OWN job rather than whichever one happens to be oldest
    with db.tx() as conn:
        conn.execute("UPDATE jobs SET status='done' WHERE status='queued'")
    yield
    for g in db.ACCOUNT_GATES:
        db.kv_set(g, "0")


def _job(policy="api_requested", kind="suggest_findings"):
    j = db.create_job(kind, {"project_id": "p", "n": time.time()}, execution_policy=policy,
                      dedupe_key=f"{kind}:{time.time_ns()}")
    return j["id"] if isinstance(j, dict) else j


# ------------------------------------------------------------------ the gate itself

def test_no_gate_when_nothing_is_walled():
    assert db.account_gate_active() is None


@pytest.mark.parametrize("gate", db.ACCOUNT_GATES)
def test_each_account_gate_is_recognised(gate):
    db.kv_set(gate, str(time.time() + 3600))
    active = db.account_gate_active()
    assert active is not None and active[0] == gate


@pytest.mark.parametrize("gate", db.ACCOUNT_GATES)
def test_an_expired_gate_does_not_hold(gate):
    db.kv_set(gate, str(time.time() - 5))
    assert db.account_gate_active() is None


@pytest.mark.parametrize("gate", db.ACCOUNT_GATES)
def test_a_corrupt_gate_value_never_blocks_the_queue(gate):
    """A gate is a cached belief. An unparseable one must fail OPEN — refusing to claim any work because a kv value
    is malformed would be a self-inflicted outage."""
    for bad in ("", "soon", "null"):
        db.kv_set(gate, bad)
        assert db.account_gate_active() is None


# ------------------------------------------------------------------ what it does to claiming

@pytest.mark.parametrize("policy", db.ACCOUNT_HELD_POLICIES)
def test_api_only_work_is_not_claimed_while_the_account_is_walled(policy):
    jid = _job(policy)
    db.kv_set("providers:spend_cap_until", str(time.time() + 3600))
    assert db.claim_job(worker_id="w1") is None
    db.kv_set("providers:spend_cap_until", "0")
    got = db.claim_job(worker_id="w1")
    assert got and got["id"] == jid          # and it is still there, untouched, when the wall lifts


def test_work_that_can_run_locally_is_still_claimed():
    """The point of holding only `ACCOUNT_HELD_POLICIES`: with NEUROSEARCH_AI_PROFILE=local most findings work has
    somewhere else to go, and a capped API account must not stop it."""
    jid = _job("local_preferred")
    db.kv_set("providers:billing_until", str(time.time() + 3600))
    got = db.claim_job(worker_id="w1")
    assert got and got["id"] == jid


def test_free_work_is_still_claimed_while_walled():
    jid = _job("local_only", kind="bootstrap_scan")
    db.kv_set("providers:billing_until", str(time.time() + 3600))
    got = db.claim_job(worker_id="w1")
    assert got and got["id"] == jid


def test_the_wall_holds_api_only_which_the_rate_ceiling_deliberately_does_not():
    """The rate ceiling is about pace, so it holds only work that CHOSE the API (`api_requested`) plus the known
    background spender. An account wall is different in kind: nothing on the API can succeed, so `api_only` is held
    too, because there is no cheaper way for it to run and claiming it only earns another refusal."""
    assert "api_only" in db.ACCOUNT_HELD_POLICIES
    jid = _job("api_only")
    db.kv_set("providers:spend_cap_until", str(time.time() + 3600))
    assert db.claim_job(worker_id="w1") is None
    db.kv_set("providers:spend_cap_until", "0")
    assert (db.claim_job(worker_id="w1") or {}).get("id") == jid


def test_clearing_the_gate_after_a_successful_call_releases_the_queue():
    """`db.clear_account_gates()` is the documented path back — only a successful call or the user's explicit
    Re-check may retire a gate. Whichever fires, the held work must become claimable again."""
    jid = _job("api_requested")
    db.kv_set("providers:billing_until", str(time.time() + 3600))
    assert db.claim_job(worker_id="w1") is None
    db.clear_account_gates()
    assert (db.claim_job(worker_id="w1") or {}).get("id") == jid
