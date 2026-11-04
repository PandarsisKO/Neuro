"""Subscription login never proves zero incremental cost; billing is fixed per call, not per current plan."""
import json
from datetime import datetime
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from neurosearch import claude_code as cc, cost_value, db, providers, usage
from neurosearch.config import settings

H = {"Authorization": "Bearer t0k"}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.delenv("NEUROSEARCH_LOCAL_BILLING", raising=False)
    db.close_thread_connection()
    db.init_db()
    providers.set_policy(None)
    yield
    db.close_thread_connection()
    providers.set_policy(None)


def declaration(mode="unknown", plan="pro", fee=20):
    return {"claude_billing": {"period": cc.billing_settings()["period"], "plan": plan, "mode": mode,
                              "subscription_usd": fee, "credits_disabled_confirmed": mode == "subscription"}}


def response(estimate=None):
    return cc.LocalResponse("result", {"input_tokens": 1000, "output_tokens": 100,
                            "cache_read_input_tokens": 2000000, "cache_creation_input_tokens": 10000},
                            "claude-haiku-4-5", "test-session", estimate)


def record(resp=None):
    usage.record_anthropic(resp or response(), "findings")
    return dict(db.connect().execute("SELECT * FROM usage ORDER BY id DESC LIMIT 1").fetchone())


def test_subscription_auth_and_legacy_override_are_not_proof_of_free_calls(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_LOCAL_BILLING", "subscription")
    assert cc.billing_mode() == "unknown"
    row = record()
    assert row["billing_basis"] == "unknown" and row["cost"] > 0 and row["saved"] == 0
    assert usage.totals()["billing"]["unverified_calls"] == 1
    assert usage.avoided_this_month() == 0


def test_credits_estimate_uses_cache_prices_and_returned_model(client):
    assert client.post("/api/usage/spend-settings", headers=H, json=declaration("usage_credits")).status_code == 200
    row = record()
    assert row["cost"] == pytest.approx((1000 + 2000000 * .1 + 10000 * 1.25 + 100 * 5) / 1e6)
    assert row["billing_basis"] == "usage_credits" and row["billing_plan"] == "pro"
    assert row["price_model"] == "claude-haiku-4-5"
    assert usage.totals()["billing"]["metered_local_estimate"] > 0


def test_cli_session_estimate_includes_helper_model_overhead():
    row = record(response(0.73))
    assert row["cost"] == row["api_equivalent"] == pytest.approx(.73)
    assert row["price_model"] == "claude-code-session"
    assert cost_value.price_basis(0, ("findings",))[row["model"]]["comparable"] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_invalid_cli_estimates_cannot_hide_spend(value):
    row = record(response(value))
    assert row["cost"] == pytest.approx(usage.cost_of(response()))
    assert row["cost"] > 0


def test_plan_and_billing_changes_do_not_reprice_existing_calls(client):
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription", "max_20x", 200))
    included = record(response(.5))
    assert included["cost"] == 0 and included["saved"] == .5
    client.post("/api/usage/spend-settings", headers=H, json=declaration("usage_credits", "pro", 20))
    metered = record(response(.8))
    assert metered["cost"] == .8
    before = usage.totals()["month"]
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription", "max_5x", 100))
    assert usage.totals()["month"] == before == pytest.approx(.8)
    assert cost_value.unit_costs("month")["total_charged"] == pytest.approx(.8)
    assert dict(db.connect().execute("SELECT * FROM usage WHERE id=?", (included["id"],)).fetchone()) == included
    assert usage.totals()["claude_billing"]["subscription_usd"] == 100  # fee is not duplicated into calls/budgets


def test_new_month_requires_new_declaration_without_repricing_last_month(client, monkeypatch):
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription"))
    record(response(.4))
    class Later(datetime):
        @classmethod
        def now(cls):
            return cls(2027, 2, 1)
    monkeypatch.setattr(cc, "datetime", Later)
    assert cc.billing_settings()["period"] == "2027-02"
    assert cc.billing_mode() == "unknown" and not cc.local_is_free()
    assert usage.totals()["month"] == 0


def test_stale_form_and_unconfirmed_included_selection_cannot_zero_costs(client):
    payload = declaration("subscription")
    payload["claude_billing"]["credits_disabled_confirmed"] = False
    assert client.post("/api/usage/spend-settings", headers=H, json=payload).status_code == 422
    payload = declaration()
    payload["claude_billing"]["period"] = "2026-01"
    assert client.post("/api/usage/spend-settings", headers=H, json=payload).status_code == 409
    assert cc.billing_mode() == "unknown"


def test_legacy_zero_cost_rows_are_unverified_in_all_cost_surfaces(client):
    usage.record("findings", "claude-haiku", cost=0, saved=4, transport="local")
    u = client.get("/api/usage", headers=H).json()
    assert u["today"] == u["month"] == u["week"] == 4
    assert u["billing"]["unverified_estimate"] == 4
    assert u["month_saved"] == u["local_ai"]["avoided_month"] == 0
    assert usage.rate_last_hour() == 4
    assert cost_value.unit_costs("today")["total_charged"] == 4
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription"))
    assert usage.totals()["month"] == 4
    assert usage.reconcile()["month"]["likely_total"] == 4


def test_unknown_cost_holds_before_local_or_paid_fallback_invocation(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "local_api_fallback", True)
    monkeypatch.setattr(providers, "route", lambda task: ("local", "test"))
    monkeypatch.setattr(cc, "create", lambda **kw: pytest.fail("A held call must not start"))
    record(response(1))
    db.kv_set("daily_budget", ".50")
    with pytest.raises(usage.BudgetPaused):
        providers.invoke("findings.extract", messages=[{"role":"user", "content":"facts"}])
    assert db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == 0


def test_observed_forecast_never_learns_zero_from_included_or_legacy_calls(client):
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription"))
    for n in range(5):
        sid = db.upsert_source(platform="manual", external_id=str(n), url=f"manual://{n}", title=str(n), duration=60)["id"]
        usage.record_anthropic(response(.2), "findings", source_id=sid)
    assert usage.observed_rate_per_minute() == pytest.approx(.2)


def test_billing_ui_workflow():
    root = Path(__file__).resolve().parents[1]
    js_dir = root / "tests/js"
    if not (js_dir / "node_modules/jsdom").exists():
        setup = subprocess.run(["npm", "ci", "--prefix", str(js_dir)], capture_output=True, text=True, timeout=180)
        assert setup.returncode == 0, setup.stderr
    result = subprocess.run(["node", str(root / "tests/js/run-claude-billing.mjs")], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_inflight_call_keeps_the_plan_declared_when_it_started(client, monkeypatch):
    client.post("/api/usage/spend-settings", headers=H, json=declaration("subscription", "max_20x", 200))
    monkeypatch.setattr(cc, "binary", lambda: "/usr/bin/true")
    monkeypatch.setattr(cc, "_has", lambda flag: False)
    def finished(cmd, **kw):
        client.post("/api/usage/spend-settings", headers=H, json=declaration("usage_credits", "pro", 20))
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"result":"ok", "total_cost_usd":.7}))
    monkeypatch.setattr(cc.subprocess, "run", finished)
    out = cc._run("hello", system=None, model="claude-haiku-4-5", timeout=5, schema=None)
    row = record(out)
    assert row["billing_basis"] == "subscription" and row["billing_plan"] == "max_20x" and row["cost"] == 0


def test_health_probe_is_metered_and_cannot_run_past_the_budget(monkeypatch):
    monkeypatch.delenv(cc.FAKE_ENV, raising=False)
    monkeypatch.setattr(cc.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="version", stderr=""))
    calls=[]
    monkeypatch.setattr(cc, "_run", lambda *a, **k: (calls.append(1), response(.12))[1])
    assert cc._probe("claude-haiku-4-5")["state"] == "ready"
    assert usage.totals()["today"] == pytest.approx(.12)
    assert db.connect().execute("SELECT kind FROM usage").fetchone()[0] == "local_probe"
    db.kv_set("daily_budget", ".10")
    assert cc._probe("claude-haiku-4-5")["state"] == "budget_wait"
    assert len(calls) == 1


@pytest.mark.parametrize("message,hint", [("You're out of extra usage. Resets at 6pm.", "6pm"),
                                     ("You've hit your session limit · resets 5:40pm (America/Los_Angeles)", "5:40pm")])
def test_usage_credit_exhaustion_is_a_limit_not_a_retryable_provider_failure(message, hint):
    error = cc._classify_failure(message, 1)
    assert isinstance(error, cc.LocalLimit)
    assert error.reset_hint.startswith(hint)


def test_a_cached_neuro_budget_hold_never_selects_paid_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "local_api_fallback", True)
    monkeypatch.setattr(cc, "health", lambda **kw: {"state":"budget_wait", "detail":"Neuro budget reached"})
    assert providers.route("findings.extract")[0] == "local"
