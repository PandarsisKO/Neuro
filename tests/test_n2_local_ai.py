"""L1 — Claude Code as the local AI provider (0.38.0): the router puts local-capable work on Claude Code when the profile is
local and the CLI is ready; UNAVAILABLE / LOCAL_LIMIT fall back to the API with the reason recorded and nothing else changed
(same schema, same artifact fields); local_only never touches the API; api_only / api_requested never touch local; the cloud
profile treats local as absent; the ledger carries provider + $0 actual + avoided spend; the stub CLI proves the subprocess
contract (flag table, JSON shape, error mapping, timeout). (Sorts after test_n1.)"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_local_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claude_code as CC  # noqa: E402
from neurosearch import api, contracts, db, fake_ai, jobs, providers, usage  # noqa: E402
from neurosearch.config import settings  # noqa: E402

STUB = str(pathlib.Path(__file__).with_name("fake_claude_cli.py"))
SYSTEM = "PROJECT: x\nBRIEF: getting out of debt"
USER = [{"role": "user", "content": "VIDEOS:\n[0] Debt payoff plan\n[1] Vlog\n\nScore them now."}]


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(settings, "claude_code_bin", "claude")
    monkeypatch.setattr(settings, "claude_code_model", None)
    monkeypatch.setenv(CC.FAKE_ENV, "ready")
    CC._state["health"] = None; CC._state["caps"] = None
    providers.set_policy(None)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    providers.set_policy(None)
    CC._state["health"] = None; CC._state["caps"] = None
    db._local.conn = None


def _rank():
    return providers.invoke_structured("rank.relevance", system=SYSTEM, messages=USER, usage_kind="rank")


def _ledger():
    return [dict(r) for r in db.connect().execute("SELECT provider, task, state AS status, error_type FROM invocations ORDER BY requested_at, rowid").fetchall()]


def _usage_rows():
    return [dict(r) for r in db.connect().execute("SELECT model, cost, saved, transport FROM usage ORDER BY ts").fetchall()]


# ---------------------------------------------------------------- routing

def test_local_runs_when_ready_and_output_is_identical(monkeypatch):
    out = _rank()
    assert [x["i"] for x in out["scores"]] == [0, 1]
    r = providers.routing_for("rank.relevance", providers.last_response().model)
    assert r["executed_by"] == "local" and r["fallback_reason"] is None and r["requested_model"] == contracts.contract("rank.relevance").model
    assert r["fallback_used"] is False, "provider choice is not a model substitution"
    led = _ledger()
    assert led and led[-1]["provider"] == CC.PROVIDER and led[-1]["status"] == "completed" and not any(x["provider"] == "anthropic" for x in led)
    u = _usage_rows()
    assert u and u[-1]["transport"] == "local" and u[-1]["cost"] == 0.0 and u[-1]["saved"] > 0, u[-1]
    # the same call on the cloud profile produces the same structured result
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    assert _rank() == out
    assert _ledger()[-1]["provider"] == "anthropic" and providers.last_route()["reason"] == "cloud_profile"


@pytest.mark.parametrize("mode,etype", [("not_installed", "LOCAL_UNAVAILABLE"), ("not_signed_in", "LOCAL_UNAVAILABLE"), ("error", "LOCAL_UNAVAILABLE"),
                                        ("timeout", "LOCAL_UNAVAILABLE"), ("limit", "LOCAL_LIMIT")])
def test_unavailable_or_limited_local_falls_back_to_the_api_with_the_reason(monkeypatch, mode, etype):
    monkeypatch.setenv(CC.FAKE_ENV, mode)
    CC._state["health"] = {"state": "ready", "checked_at": 1e12}          # a stale "ready" verdict: the CALL discovers the failure
    out = _rank()
    assert [x["i"] for x in out["scores"]] == [0, 1]
    r = providers.last_route()
    assert r["executed_by"] == "api" and r["fallback_reason"].startswith(etype.lower())
    led = _ledger()
    assert [x["provider"] for x in led[-2:]] == [CC.PROVIDER, "anthropic"] and led[-2]["status"] == "failed" and led[-2]["error_type"] == etype
    # the failure updated the cached health at once, so the NEXT call routes straight to the API without a local attempt
    assert CC.health()["state"] in ("usage_limit", "not_installed", "not_signed_in", "error")
    _rank()
    assert _ledger()[-1]["provider"] == "anthropic" and providers.last_route()["reason"].startswith("local_")
    if mode == "limit":
        assert CC.health()["reset_hint"] == "6pm" and "usage limit" in CC.status_line()


def test_local_errors_never_trip_a_breaker_and_are_never_retried(monkeypatch):
    from neurosearch import breakers
    monkeypatch.setenv(CC.FAKE_ENV, "error")
    CC._state["health"] = {"state": "ready", "checked_at": 1e12}
    _rank()
    assert breakers.get("claude_code:print")["state"] == breakers.CLOSED
    assert sum(1 for x in _ledger() if x["provider"] == CC.PROVIDER) == 1


def test_local_only_never_touches_the_api(monkeypatch):
    monkeypatch.setenv(CC.FAKE_ENV, "limit")
    providers.set_policy("local_only")
    with pytest.raises(providers.ProviderError) as ei:
        _rank()
    assert ei.value.error_type == "LOCAL_LIMIT"
    assert not any(x["provider"] == "anthropic" for x in _ledger()) and not _usage_rows()
    assert providers.last_route()["executed_by"] == "none"


@pytest.mark.parametrize("policy", ["api_only", "api_requested"])
def test_api_policies_never_touch_local(monkeypatch, policy):
    providers.set_policy(policy)
    _rank()
    led = _ledger()
    assert all(x["provider"] == "anthropic" for x in led) and providers.last_route()["reason"] == f"policy:{policy}"


def test_non_local_capable_tasks_stay_on_the_api(monkeypatch):
    assert contracts.contract("answer.chat").local_capable is False
    assert providers.route("answer.chat") == ("api", "task_not_local_capable")
    assert providers.route("rank.relevance")[0] == "local"


# ---------------------------------------------------------------- jobs: policy column, pools, outcome

def test_jobs_record_intent_and_outcome_separately(monkeypatch):
    j = db.create_job("rank_proposed", {"project_id": "p", "collection_id": "c"})
    assert j["execution_policy"] == "local_preferred" and j["executed_by"] is None
    db.set_job_policy(j["id"], "api_requested")
    assert db.get_job(j["id"])["execution_policy"] == "api_requested"
    with pytest.raises(AssertionError):
        db.set_job_policy(j["id"], "fast_please")
    # pools: the local pool sees only local policies, the API pool only API policies, general workers never the AI kinds
    assert db.claim_job(jobs.ANALYSIS_KINDS, worker_id="local", policies=jobs.LOCAL_POLICIES) is None
    got = db.claim_job(jobs.ANALYSIS_KINDS, worker_id="api", policies=jobs.API_POLICIES)
    assert got and got["id"] == j["id"]
    j2 = db.create_job("rank_proposed", {"project_id": "p", "collection_id": "c2"})
    assert db.claim_job(None, worker_id="general", exclude_kinds=jobs.ANALYSIS_KINDS) is None
    assert db.claim_job(jobs.ANALYSIS_KINDS, worker_id="local", policies=jobs.LOCAL_POLICIES)["id"] == j2["id"]


def test_job_outcome_is_recorded_from_the_calls_it_made(monkeypatch):
    """A job that meant local and ran on the API (fallback) says so; a job that ran local says local; the intent column is untouched."""
    calls = []

    def fake_run(job):
        calls.append(job["execution_policy"])
        _rank()
        return {"ok": True}
    monkeypatch.setattr(jobs, "run_job", fake_run)
    j = db.create_job("rank_proposed", {"project_id": "p", "collection_id": "c"})
    assert jobs.execute(dict(j, run_id="r1")) == "done"
    row = db.get_job(j["id"])
    assert row["executed_by"] == "local" and row["fallback_reason"] is None and row["execution_policy"] == "local_preferred"
    monkeypatch.setenv(CC.FAKE_ENV, "limit")
    CC._state["health"] = {"state": "ready", "checked_at": 1e12}
    j2 = db.create_job("rank_proposed", {"project_id": "p", "collection_id": "c2"})
    jobs.execute(dict(j2, run_id="r2"))
    row = db.get_job(j2["id"])
    assert row["executed_by"] == "api" and row["fallback_reason"].startswith("local_limit") and row["execution_policy"] == "local_preferred"
    assert calls == ["local_preferred", "local_preferred"]


# ---------------------------------------------------------------- the real subprocess path (stub CLI)

def _real(monkeypatch, tmp_path, mode="ok", result=None):
    monkeypatch.delenv(CC.FAKE_ENV, raising=False)
    monkeypatch.setattr(settings, "claude_code_bin", STUB)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    argf = tmp_path / "args.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_ARGS", str(argf))
    if result is not None:
        monkeypatch.setenv("FAKE_CLAUDE_RESULT", result)
    CC._state["health"] = None; CC._state["caps"] = None
    return argf


def test_stub_cli_proves_the_headless_contract(monkeypatch, tmp_path):
    argf = _real(monkeypatch, tmp_path, "ok", json.dumps({"scores": [{"i": 0, "score": 90, "why": "on topic"}, {"i": 1, "score": 5, "why": "vlog"}]}))
    h = CC.health(force=True)
    assert h["state"] == "ready" and h["version"].startswith("2.1.0")
    resp = CC.create(system=SYSTEM, messages=USER, extra_headers={"x-neurosearch-task": "rank.relevance"}, max_tokens=100)
    assert resp.provider == CC.PROVIDER and resp.stop_reason == "end_turn" and resp.usage.input_tokens > 0
    out = providers.structured("rank.relevance", resp)
    assert [x["i"] for x in out["scores"]] == [0, 1]
    argv = [json.loads(l) for l in argf.read_text().splitlines()]
    call = argv[-1]
    assert call[0] == "-p" and "--output-format" in call and call[call.index("--output-format") + 1] == "json"
    assert "--max-turns" in call and "--system-prompt" in call and "--tools" in call and call[call.index("--tools") + 1] == ""
    assert "--json-schema" in call and json.loads(call[call.index("--json-schema") + 1])["type"] == "object"
    assert SYSTEM in call[call.index("--system-prompt") + 1] and "Score them now." in call[1]
    assert "--model" not in call            # no model pin unless NEUROSEARCH_CLAUDE_CODE_MODEL is set


@pytest.mark.parametrize("mode,kind", [("limit", "usage_limit"), ("auth", "not_signed_in"), ("crash", "error"), ("garbage", "malformed_output")])
def test_stub_cli_failures_map_to_the_two_policy_states(monkeypatch, tmp_path, mode, kind):
    _real(monkeypatch, tmp_path, mode)
    with pytest.raises(CC.LocalUnavailable) as ei:
        CC.create(system="s", messages=[{"role": "user", "content": "u"}], extra_headers={"x-neurosearch-task": "rank.relevance"})
    assert ei.value.kind == kind
    if mode == "limit":
        assert isinstance(ei.value, CC.LocalLimit) and "3pm" in (ei.value.reset_hint or "")
        assert providers.classify_error(ei.value) == "LOCAL_LIMIT"
    else:
        assert providers.classify_error(ei.value) == "LOCAL_UNAVAILABLE"


def test_stub_cli_timeout_is_unavailable_not_a_hang(monkeypatch, tmp_path):
    _real(monkeypatch, tmp_path, "hang")
    monkeypatch.setattr(CC, "DEFAULT_TIMEOUT", 1.0)
    monkeypatch.setattr(CC, "PROBE_TIMEOUT", 1.0)
    with pytest.raises(CC.LocalUnavailable) as ei:
        CC._run("x", system=None, model=None, timeout=1.0, schema=None)
    assert ei.value.kind == "timeout"


def test_missing_binary_and_cloud_profile(monkeypatch, tmp_path):
    monkeypatch.delenv(CC.FAKE_ENV, raising=False)
    monkeypatch.setattr(settings, "claude_code_bin", str(tmp_path / "no-such-claude"))
    CC._state["health"] = None; CC._state["caps"] = None
    assert CC.health(force=True)["state"] == "not_installed"
    assert providers.route("rank.relevance") == ("api", "local_not_installed")
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    assert CC.health(force=True)["state"] == "disabled" and CC.status_line().startswith("Claude Code: off")
    assert usage.avoided_this_month() == 0.0


def test_api_surfaces_never_block_on_the_probe(monkeypatch, tmp_path):
    """/api/health and /api/usage return at once with 'checking' while the probe runs in the background; the router waits."""
    _real(monkeypatch, tmp_path, "hang")
    monkeypatch.setattr(CC, "PROBE_TIMEOUT", 2.0)
    import time as _t
    t0 = _t.time()
    h = CC.health(wait=False)
    assert _t.time() - t0 < 0.5 and h["state"] == "checking" and CC.status_line().startswith("Claude Code: checking")
    _t.sleep(3.0)                                            # the hung probe timed out in the background → a real verdict, no thread left probing
    h2 = CC.health(wait=False)
    assert h2["state"] == "error" and "timeout" in (h2.get("detail") or "") or h2["state"] in ("error",)
    assert CC._state["probing"] is False


def test_usage_split_counts_local_share_actual_and_avoided(monkeypatch):
    """L4: the split is what the Health line shows — calls, local share, actual API spend, avoided spend."""
    assert usage.local_split()["calls"] == 0 and usage.local_split()["line"] == "no AI calls yet"
    _rank()                                              # local
    providers.set_policy("api_only"); _rank()            # api
    providers.set_policy(None)
    sp = usage.local_split()
    assert sp["calls"] == 2 and sp["local_calls"] == 1 and sp["local_share"] == 0.5
    assert sp["avoided"] > 0 and sp["actual"] > 0 and "50% local" in sp["line"]
    h = api.api_health()
    assert h["local_ai"]["split"]["calls"] == 2
