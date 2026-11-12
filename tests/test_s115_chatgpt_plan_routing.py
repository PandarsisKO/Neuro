"""Opt-in ChatGPT plan routing on the ordinary queue, with no external requests."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace as NS

import pytest

from neurosearch import chatgpt_plan as plan, claude_code as claude, db, jobs, providers, usage
from neurosearch.config import settings

TASK = "findings.extract"
MESSAGES = [{"role": "user", "content": "Summarize this fixture transcript."}]
RESULT = {"summary": "Fixture summary", "substance": 50, "findings": []}


def response(model):
    return NS(model=model, provider="chatgpt_plan" if model == plan.MODEL else "anthropic",
              content=[NS(type="text", text=json.dumps(RESULT))], stop_reason="end_turn",
              usage=NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=100))


@pytest.fixture
def calls(tmp_path, monkeypatch):
    db.close_thread_connection()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "local_api_fallback", False)
    monkeypatch.setattr(settings, "chatgpt_plan_tasks", (TASK,))
    monkeypatch.setattr(settings, "chatgpt_plan_parallel", False)
    monkeypatch.setattr(settings, "daily_budget", 10)
    monkeypatch.setattr(settings, "monthly_budget", 50)
    db.init_db()
    monkeypatch.setattr(plan, "ready", lambda: True)
    monkeypatch.setattr(claude, "health", lambda **kw: {"state": "ready"})
    monkeypatch.setattr(claude, "health_snapshot", lambda **kw: {"state": "ready"})
    monkeypatch.setattr(claude, "note_success", lambda *args, **kw: None)
    monkeypatch.setattr(claude, "note_failure", lambda *args, **kw: None)
    monkeypatch.setattr(claude, "local_is_free", lambda: True)
    order = []
    monkeypatch.setattr(plan, "create", lambda **kw: order.append("chatgpt") or response(plan.MODEL))
    monkeypatch.setattr(claude, "create", lambda **kw: order.append("claude") or response(kw["model"]))

    def never_api(**kw):
        pytest.fail("unexpected Anthropic API inference")

    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: NS(messages=NS(create=NS(_fn=never_api))))
    providers.set_policy(None)
    providers.reset_job_route()
    yield order
    providers.set_policy(None)
    providers.reset_job_route()
    db.close_thread_connection()


def run():
    return providers.invoke_structured(TASK, system="Test instructions", messages=MESSAGES, usage_kind="findings")


def test_healthy_claude_stays_primary(calls):
    assert run() == RESULT
    assert calls == ["claude"]


def test_claude_code_limit_falls_back_and_books_estimated_usage(calls, monkeypatch):
    def limited(**kwargs):
        calls.append("claude")
        raise claude.LocalLimit("Usage limit")

    monkeypatch.setattr(claude, "create", limited)
    assert run() == RESULT
    assert calls == ["claude", "chatgpt"]
    route = providers.routing_for(TASK, providers.last_response().model)
    assert route["fallback_reason"] == "local_limit" and route["fallback_used"]
    assert route["requested_model"] == plan.MODEL and "model_mismatch" not in route
    from neurosearch.contracts import contract
    assert "model_mismatch" not in providers.routing_for("claims.extract", contract("claims.extract").model)
    rows = db.connect().execute("SELECT provider, state FROM invocations ORDER BY rowid").fetchall()
    assert [tuple(r) for r in rows] == [("claude_code", "failed"), ("chatgpt_plan", "completed")]
    row = db.connect().execute("SELECT transport, billing_basis, cost FROM usage").fetchone()
    assert tuple(row) == ("chatgpt_plan", "unknown", pytest.approx(.000141))


@pytest.mark.parametrize("status, message", [(429, "rate limit"), (400, "credit balance too low")])
def test_anthropic_api_limit_uses_plan(calls, monkeypatch, status, message):
    class ApiError(RuntimeError):
        status_code = status

    def limited(**kw):
        calls.append("api")
        raise ApiError(message)

    monkeypatch.setattr(providers, "anthropic_client", lambda **kw: NS(messages=NS(create=NS(_fn=limited))))
    with providers.policy_context("api_requested"):
        assert run() == RESULT
    assert calls[-1] == "chatgpt"
    if status == 400:
        assert db.account_gate_active()[0] == "providers:billing_until"
        calls.clear()
        with providers.policy_context("api_requested"):
            run()
        assert calls == ["chatgpt"]


def test_opt_in_cannot_bypass_local_only_or_budget(calls, monkeypatch):
    def limited(**kwargs):
        raise claude.LocalLimit("Usage limit")

    monkeypatch.setattr(claude, "create", limited)
    with providers.policy_context("local_only"), pytest.raises(providers.ProviderError, match="LOCAL_LIMIT"):
        run()
    db.kv_set("queue_paused", "1")
    with providers.parallel_chatgpt(), pytest.raises(usage.BudgetPaused):
        run()
    assert calls == []


def test_paid_account_wall_admits_only_eligible_jobs(calls):
    findings = db.create_job("suggest_findings", {"project_id": "p"}, execution_policy="api_requested")
    db.create_job("rank_proposed", {"collection_id": "c"}, execution_policy="api_requested")
    db.kv_set("providers:billing_until", str(time.time() + 1800))
    assert db.claim_job(policies=jobs.API_POLICIES) is None
    job = db.claim_job(policies=jobs.API_POLICIES, anthropic_alternates=("suggest_findings",))
    assert job["id"] == findings["id"]
    assert db.claim_job(policies=jobs.API_POLICIES, anthropic_alternates=("suggest_findings",)) is None


def test_two_existing_workers_overlap_distinct_jobs(calls, monkeypatch):
    monkeypatch.setattr(settings, "chatgpt_plan_parallel", True)
    monkeypatch.setattr(jobs, "_stop", threading.Event())
    barrier = threading.Barrier(2, timeout=5)
    seen = []
    errs = []
    for pid in ("p-one", "p-two"):
        db.create_job("suggest_findings", {"project_id": pid}, execution_policy="local_preferred")

    def execute(job, wid):
        try:
            barrier.wait()
            run()
            seen.append((job["id"], providers.last_route()["executed_by"]))
            db.finish_job(job["id"], job["run_id"], "done")
        except Exception as e:
            errs.append(e)
        finally:
            jobs._stop.set()
        return "done"

    monkeypatch.setattr(jobs, "execute", execute)
    workers = [threading.Thread(target=jobs._thread_main, args=(jobs._worker, settings.db_path, (name, jobs.ANALYSIS_KINDS),
               opts)) for name, opts in (("local-test", {"policies": jobs.LOCAL_POLICIES}),
                                        ("api-test", {"policies": jobs.API_POLICIES, "chatgpt_overflow": True}))]
    for t in workers:
        t.start()
    for t in workers:
        t.join(timeout=8)
    assert not any(t.is_alive() for t in workers)
    assert errs == []
    assert len({row[0] for row in seen}) == 2
    assert {row[1] for row in seen} == {"local", "chatgpt_plan"}


def test_chatgpt_limit_parks_same_job_without_changing_anthropic_gate(calls, monkeypatch):
    job = db.create_job("suggest_findings", {"project_id": "p"})
    claimed = db.claim_job(("suggest_findings",))
    monkeypatch.setattr(jobs, "run_job", lambda job: run())

    def limited(**kw):
        raise plan.PlanWait("ChatGPT plan usage limit reached.", 300)

    monkeypatch.setattr(plan, "create", limited)
    with providers.parallel_chatgpt():
        assert jobs.execute(claimed) == "queued"
    row = db.get_job(job["id"])
    assert row["wait_reason"] == "provider" and row["attempts"] == 0
    assert "ChatGPT plan usage limit" in row["message"]
    assert db.account_gate_active() is None


def test_plan_request_uses_public_preview_shape():
    body = plan.request(task=TASK, system=[{"type": "text", "text": "Test", "cache_control": {"type": "ephemeral"}}],
                        messages=MESSAGES)
    assert body["instructions"] == "Test"
    assert body["input"] == MESSAGES
    assert body["stream"] and body["store"] is False
    assert "max_output_tokens" not in body
    assert body["text"]["format"]["name"] == "findings-v2"


def test_connect_uses_loopback_pkce_and_keeps_credentials_private(tmp_path, monkeypatch):
    import base64
    import hashlib
    import webbrowser
    from urllib.parse import parse_qs, urlencode, urlsplit
    from urllib.request import urlopen

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    opened = {}
    pending = []

    def browser(url):
        opened.update({k: v[0] for k, v in parse_qs(urlsplit(url).query).items()})
        callback = opened["redirect_uri"] + "?" + urlencode({
            "state": opened["state"], "code": "fixture-code", "client_id": "fixture-client",
        })

        def request_callback():
            with urlopen(callback, timeout=5) as result:
                assert result.status == 200

        thread = threading.Thread(target=request_callback)
        pending.append(thread)
        thread.start()
        return True

    def exchange(fields):
        assert fields["code"] == "fixture-code"
        assert fields["client_id"] == "fixture-client"
        assert fields["redirect_uri"] == opened["redirect_uri"]
        digest = hashlib.sha256(fields["code_verifier"].encode()).digest()
        assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == opened["code_challenge"]
        return {"scope": plan.SCOPES, "access_token": "fixture-access", "refresh_token": "fixture-refresh",
                "expires_in": 1800, "token_type": "Bearer", "id_token": "fixture-id"}

    def verify(token, client, nonce):
        assert (token, client, nonce) == ("fixture-id", "fixture-client", opened["nonce"])
        return {"sub": "fixture-subject"}

    monkeypatch.setattr(webbrowser, "open", browser)
    monkeypatch.setattr(plan, "_exchange", exchange)
    monkeypatch.setattr(plan, "_identity", verify)
    plan.connect(timeout=5)
    for thread in pending:
        thread.join(timeout=5)
    assert opened["redirect_uri"].startswith("http://127.0.0.1:")
    assert opened["client_id"] == "dynamic_agent_client"
    path = tmp_path / "chatgpt-plan" / "session.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert plan._access() == "fixture-access"


def test_stream_uses_plan_token_and_requires_terminal_event(monkeypatch):
    from contextlib import nullcontext
    import openai

    monkeypatch.setattr(plan, "_access", lambda: "fixture-plan-token")
    response = NS(id="fixture-response", model=plan.MODEL,
                  output=[NS(type="message", content=[NS(type="output_text")])],
                  output_text=json.dumps(RESULT),
                  usage=NS(input_tokens=20, output_tokens=10, input_tokens_details=NS(cached_tokens=5)))
    events = [NS(type="response.output_text.delta", delta="part")]
    request = plan.request(task=TASK, system="Fixture instructions", messages=MESSAGES)

    def client(**opts):
        assert opts["api_key"] == "fixture-plan-token"
        assert opts["base_url"] == "https://api.openai.com/v1"
        assert opts["max_retries"] == 0

        def create(**body):
            assert body == request
            return nullcontext(iter(events))

        return nullcontext(NS(responses=NS(create=create)))

    monkeypatch.setattr(openai, "OpenAI", client)
    with pytest.raises(RuntimeError, match="before completion"):
        plan.create(body=request, model=plan.MODEL, max_tokens=100, timeout=5)
    events.append(NS(type="response.completed", response=response))
    actual = plan.create(body=request, model=plan.MODEL, max_tokens=100, timeout=5)
    assert actual.model == plan.MODEL and actual.usage.cache_read_input_tokens == 5
    assert providers.structured(TASK, actual) == RESULT
