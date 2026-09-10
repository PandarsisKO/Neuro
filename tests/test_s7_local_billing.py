"""S7 — a local call is free only when the app can show it is (0.59.0).

The measurement that forced this, from Kyle's own account on 2026-09-10:

    app ledger, month to date        $111.96
    local path, booked as `saved`    $210.55
    Anthropic Console                $312.40

The first two sum to within 3% of the third. L1 recorded every Claude Code call as `cost=0` with the avoided spend
in `saved`, on the assumption that the CLI runs on the user's subscription — and nothing ever checked. Those calls
were real charges, and because they were booked at zero they were invisible to the daily budget, the monthly budget,
the spend-rate ceiling and Health. Kyle topped up credit for a week while the app told him he had spent a third of
what he actually had.

The rule these tests hold: subscription → free; API key → spend; **unknown → spend**. Assuming free is the specific
mistake that hid $200, and a bill that is too cautious is recoverable where a hidden one is not.
"""
from __future__ import annotations

import pytest

from neurosearch import claude_code as cc
from neurosearch import db, usage


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    db.init_db()
    monkeypatch.delenv("NEUROSEARCH_LOCAL_BILLING", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db.kv_set("spend_rate_ceiling", None)
    db.kv_set("weekly_budget", None)
    yield


class _Resp:
    """A Claude Code response as `usage.record_anthropic` sees one."""
    provider = "claude_code"
    model = "claude-haiku-4-5-20251001"

    class usage:                                     # noqa: N801
        input_tokens = 1_000
        output_tokens = 100_000
        cache_read_input_tokens = 2_000_000
        cache_creation_input_tokens = 0


# ------------------------------------------------------------------ detection

def test_no_api_key_means_the_subscription_pays():
    assert cc.billing_mode() == cc.BILLING_SUBSCRIPTION
    assert cc.local_is_free() is True


def test_a_key_in_our_environment_no_longer_decides_who_pays(monkeypatch):
    """0.59.1 CHANGED this. The first version of `billing_mode` read ANTHROPIC_API_KEY from our own environment,
    because the app was passing it to the CLI. Now `_run` strips it, so the CLI uses its own login and a key sitting
    in our process says nothing about who pays. The honest check became empirical: `usage.reconcile()` reports
    `recorded` beside `likely_total`, and the Console should track `recorded` from here on."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
    assert cc.billing_mode() == cc.BILLING_SUBSCRIPTION
    assert cc.local_is_free() is True
    assert "no longer passed" in cc.billing_note()


@pytest.mark.parametrize("mode", [cc.BILLING_SUBSCRIPTION, cc.BILLING_API_KEY, cc.BILLING_UNKNOWN])
def test_the_override_wins_for_a_setup_the_heuristic_reads_wrongly(monkeypatch, mode):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", mode)
    assert cc.billing_mode() == mode


def test_unknown_is_treated_as_billed(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_UNKNOWN)
    assert cc.local_is_free() is False               # the whole lesson, in one assertion


# ------------------------------------------------------------------ what gets recorded

def _record() -> dict:
    usage.record_anthropic(_Resp(), "findings", project_id=None)
    row = db.connect().execute("SELECT cost, saved, transport FROM usage ORDER BY id DESC LIMIT 1").fetchone()
    return {"cost": float(row["cost"] or 0), "saved": float(row["saved"] or 0), "transport": row["transport"]}


def test_a_subscription_call_is_free_and_records_what_it_avoided():
    r = _record()
    assert r["transport"] == "local"
    assert r["cost"] == 0.0 and r["saved"] > 0


def test_an_api_key_call_is_recorded_as_real_spend(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_API_KEY)
    r = _record()
    assert r["transport"] == "local"                 # provenance is kept: it still ran locally
    assert r["cost"] > 0 and r["saved"] == 0.0       # ...but it is money, not savings


def test_cost_and_saved_can_never_double_count(monkeypatch):
    """Exactly one of the two is ever non-zero, so `recorded + local_if_billed` is a sum and not an overcount."""
    for mode in (cc.BILLING_SUBSCRIPTION, cc.BILLING_API_KEY):
        monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", mode)
        r = _record()
        assert (r["cost"] > 0) != (r["saved"] > 0), r


def test_a_billed_local_call_reaches_the_budget_and_the_rate_ceiling(monkeypatch):
    """The reason this mattered: `totals()`, `check()` and the rate gate all read `cost`. Booking local at zero took
    it out of every one of them at once."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_API_KEY)
    before = usage.totals()["today"]
    _record()
    assert usage.totals()["today"] > before          # the budget can see it now
    assert usage.rate_last_hour() > 0                # and so can the rate ceiling


# ------------------------------------------------------------------ reconciliation

def test_reconcile_reports_both_numbers_and_says_how_to_read_them(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_API_KEY)
    _record()
    r = usage.reconcile()
    assert r["billing_mode"] == cc.BILLING_API_KEY and r["local_is_free"] is False
    assert r["month"]["likely_total"] >= r["month"]["recorded"] > 0
    assert "Anthropic Console" in r["how_to_read"]
    assert r["month"]["local_calls"] >= 1


def test_reconcile_adds_the_local_path_only_when_it_is_billed(monkeypatch):
    """Historic rows always booked local at zero with the avoided spend in `saved`. When the CLI is billing an API
    key, that `saved` figure was really spend — which is how a month that looked like $112 is recognised as $312
    without anyone reconstructing it by hand."""
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_SUBSCRIPTION)
    _record()                                        # a free call: saved > 0, cost 0
    free = usage.reconcile()
    assert free["month"]["likely_total"] == free["month"]["recorded"]
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_API_KEY)
    billed = usage.reconcile()
    assert billed["month"]["likely_total"] > billed["month"]["recorded"]
    assert billed["month"]["local_if_billed"] > 0


# ------------------------------------------------------------------ the budget levers he actually needs

def test_the_rate_ceiling_is_settable_because_the_default_is_not_a_budget():
    assert usage.rate_ceiling() == usage.SPEND_RATE_CEILING == 6.0     # ~$1,000/week: a runaway detector
    db.kv_set("spend_rate_ceiling", "1.25")
    assert usage.rate_ceiling() == 1.25
    for bad in ("", "lots", "-3", "0"):
        db.kv_set("spend_rate_ceiling", bad)
        assert usage.rate_ceiling() == usage.SPEND_RATE_CEILING        # nonsense falls back, never blocks


def test_a_weekly_budget_exists_because_that_is_how_he_thinks(monkeypatch):
    """Kyle measures this in weeks — "nearly $300 in one week" — and the app only had daily and monthly."""
    assert usage.budget("weekly") == 0.0                               # off unless set
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", cc.BILLING_API_KEY)
    _record()
    spent = usage.totals()["week"]
    assert spent > 0
    db.kv_set("weekly_budget", str(round(spent / 2, 4)))
    db.kv_set("daily_budget", "100000")      # isolate the weekly rule from the daily one
    db.kv_set("monthly_budget", "100000")
    ok, why, wait = usage.check(0.0)
    assert ok is False and "weekly budget" in why and wait > 0
    db.kv_set("weekly_budget", "0")
    assert usage.check(0.0)[0] is True
    db.kv_set("daily_budget", None); db.kv_set("monthly_budget", None)


def test_health_shows_the_gap():
    h = db.health()["spend"]
    assert "billing_mode" in h and "how_to_read" in h
    assert set(h["month"]) >= {"recorded", "local_if_billed", "likely_total"}


# ------------------------------------------------------------------ 0.59.1: the app must not hand the CLI a key

def test_the_cli_never_receives_an_api_key(monkeypatch, tmp_path):
    """The actual bug. `config.load_dotenv()` copies .env into os.environ, and `_run` passed the whole environment
    to the subprocess — so ANTHROPIC_API_KEY reached the Claude Code CLI on every call and the CLI billed the API
    account in preference to the user's subscription login. `claude login` could not fix it: the app overrode the
    login every time. This asserts on the environment the subprocess is actually given."""
    seen = {}

    class _Done:
        returncode = 0
        stdout = '{"result": "ok"}'
        stderr = ""

    def fake_run(cmd, **kw):
        seen.update(kw.get("env") or {})
        return _Done()

    for var in cc.CLI_CREDENTIAL_VARS:
        monkeypatch.setenv(var, f"secret-{var}")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")            # something innocuous that MUST survive
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "binary", lambda: "/usr/bin/true")
    try:
        cc._run("hello", system=None, model=None, timeout=5, schema=None)
    except Exception:
        pass                                               # the parse may fail; the environment is what is on trial
    assert seen, "the subprocess was never given an environment"
    for var in cc.CLI_CREDENTIAL_VARS:
        assert var not in seen, f"{var} was handed to the CLI"
    assert seen.get("PATH") == "/usr/bin:/bin"             # ...and nothing else was thrown away
    assert not any(k.startswith("NEUROSEARCH_") for k in seen)


def test_every_stripped_variable_is_a_credential():
    """A guard on the guard: this list is subtracted from the CLI's environment, so an accidental entry would break
    local inference rather than protect it."""
    for var in cc.CLI_CREDENTIAL_VARS:
        assert "KEY" in var or "TOKEN" in var, var


def test_a_missing_subscription_fails_visibly_rather_than_silently_billing(monkeypatch):
    """The failure mode after the fix: no CLI login means the CLI errors, `_run` raises LocalUnavailable and
    `providers.route` falls back to the API — where the call is recorded as real spend. Visible and paid beats
    hidden and paid."""
    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "Invalid API key · Please run /login"

    monkeypatch.setattr(cc.subprocess, "run", lambda cmd, **kw: _Fail())
    monkeypatch.setattr(cc, "binary", lambda: "/usr/bin/true")
    with pytest.raises((cc.LocalUnavailable, cc.LocalLimit)):
        cc._run("hello", system=None, model=None, timeout=5, schema=None)
