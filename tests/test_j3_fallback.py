"""Rung J3 — fallback is an explicit contract invariant: NO_FALLBACK everywhere, audited in provenance. (Sorts after test_core.)"""
from __future__ import annotations

import json
import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_j3_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import breakers, contracts, db, fake_ai, jobs, providers  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests import crashkit  # noqa: E402

ANTHROPIC_TASKS = ("answer.chat", "answer.repair", "findings.extract", "rank.relevance", "discover.quick", "discover.verify", "planner.analysis", "planner.build",
                   "planner.update", "export.synthesis", "planner.situation", "planner.core", "planner.execution", "planner.economics", "planner.actions",
                   "findings.prefilter", "retrieval.rerank")


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    yield
    fake_ai.OUTAGES.clear()
    db._local.conn = None


def models_invoked(task: str) -> set[str]:
    return {r["model"] for r in db.connect().execute("SELECT DISTINCT model FROM invocations WHERE task=?", (task,)).fetchall()}


def err(status: int, name: str, msg: str = "simulated", **kw):
    return fake_ai.FakeAPIError(status, msg, name=name, **kw)


# ---------------------------------------------------------------- the invariant on every contract

def test_every_ai_contract_declares_no_fallback_explicitly():
    for task in ANTHROPIC_TASKS + ("embed", "transcribe"):
        c = contracts.contract(task)
        assert c.fallback == "NO_FALLBACK" and c.fallback_candidates == () and c.describe()["fallback_policy_version"] == "fallback-policy-v1", task
    with pytest.raises(contracts.ContractError):
        contracts.validate(contracts.InferenceContract("x", "anthropic", "claude-sonnet-5", fallback="NO_FALLBACK", fallback_candidates=("claude-sonnet-4-6",)))
    with pytest.raises(contracts.ContractError):
        contracts.validate(contracts.InferenceContract("x", "anthropic", "claude-sonnet-5", fallback="VALIDATED", fallback_candidates=("claude-sonnet-4-6",)))
    with pytest.raises(contracts.ContractError):
        contracts.validate(contracts.InferenceContract("x", "anthropic", "claude-sonnet-5", fallback="AUTO"))


# ---------------------------------------------------------------- the router never substitutes

def _golden_source():
    from neurosearch import evals
    g = evals.load_golden(only={"yt01"})
    return g["project_id"], g["sources"]["yt01"]


def test_findings_sonnet5_failure_never_substitutes_the_general_model():
    from neurosearch import findings
    pid, sid = _golden_source()
    assert contracts.contract("findings.extract").model == "claude-sonnet-5" and settings.answer_model != "claude-sonnet-5"
    fake_ai.OUTAGES["anthropic:messages"] = [err(529, "OverloadedError")] * 6
    with pytest.raises(Exception):
        findings.suggest_for_source(pid, sid)
    assert models_invoked("findings.extract") == {"claude-sonnet-5"}                 # only the requested model was ever asked
    assert not models_invoked("findings.extract") & {settings.answer_model, "claude-sonnet-4-6"}
    assert db.get_analysis(pid, sid, "summary") is None                             # and no artifact was produced by anything else


def test_ranking_sonnet5_failure_never_substitutes():
    from neurosearch import relevance
    pid, sid = _golden_source()
    fake_ai.OUTAGES["anthropic:messages"] = [err(401, "AuthenticationError", "bad key")] * 6
    coll = db.create_collection("c", "playlist", "https://www.youtube.com/playlist?list=x", project_id=pid) if hasattr(db, "create_collection") else None
    try:
        relevance.rank_collection(coll["id"], pid, want=5) if coll else providers.invoke("rank.relevance", system="s", messages=[{"role": "user", "content": "[1] x"}])
    except Exception:
        pass
    assert models_invoked("rank.relevance") <= {"claude-sonnet-5"} and "claude-sonnet-4-6" not in models_invoked("rank.relevance")


def test_general_task_failure_never_substitutes_sonnet5():
    fake_ai.OUTAGES["anthropic:messages"] = [err(500, "InternalServerError")] * 6
    with pytest.raises(providers.ProviderError):
        providers.invoke("answer.chat", system="s", messages=[{"role": "user", "content": "hi"}])
    assert models_invoked("answer.chat") == {settings.answer_model} and "claude-sonnet-5" not in models_invoked("answer.chat")


def test_circuit_open_parks_rather_than_substitutes():
    from neurosearch import findings
    pid, sid = _golden_source()
    fake_ai.OUTAGES["anthropic:messages"] = [err(529, "OverloadedError")] * 3
    for _ in range(3):
        try:
            providers.invoke("answer.chat", system="s", messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass
    assert breakers.get("anthropic:messages")["state"] == "open"
    n0 = db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
    j = db.create_job("suggest_findings", {"project_id": pid, "source_ids": [sid]})
    assert crashkit.Sim().step(("suggest_findings",)) == "queued"
    assert db.derived_status(db.get_job(j["id"])) == "provider_wait"
    assert db.connect().execute("SELECT COUNT(*) FROM invocations").fetchone()[0] == n0    # nothing asked of any model
    assert db.get_analysis(pid, sid, "summary") is None


@pytest.mark.parametrize("e", [
    err(401, "AuthenticationError", "invalid api key"), err(402, "BadRequestError", "billing: credit balance too low"),
    err(429, "RateLimitError", "spend cap", body={"error": {"message": "enforced_spend_limit_reached"}}), err(400, "BadRequestError", "invalid request"),
])
def test_account_and_request_failures_are_typed_not_substituted(e):
    fake_ai.OUTAGES["anthropic:messages"] = [e] * 3
    with pytest.raises(providers.ProviderError) as ei:
        providers.invoke("findings.extract", system="s", messages=[{"role": "user", "content": "TRANSCRIPT:\n[0:00] x\n\nExtract the findings now."}])
    assert ei.value.error_type in providers.NON_TRANSIENT_TYPES and models_invoked("findings.extract") == {"claude-sonnet-5"}


def test_refusal_and_schema_failures_do_not_substitute(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_AI_BAD_JSON", "1")
    with pytest.raises(Exception):
        providers.invoke_structured("findings.extract", system="s", messages=[{"role": "user", "content": "TRANSCRIPT:\n[0:00] x\n\nExtract the findings now."}], usage_kind="findings")
    monkeypatch.delenv("NEUROSEARCH_FAKE_AI_BAD_JSON")
    assert models_invoked("findings.extract") == {"claude-sonnet-5"}
    monkeypatch.setenv("NEUROSEARCH_FAKE_RERANK", "refuse")
    from neurosearch import rerank
    hits = [{"chunk_id": i, "source_id": "s", "title": "t", "text": "x", "start": 0, "timestamp": "0:00"} for i in range(3)]
    assert [h["chunk_id"] for h in rerank.rerank("q", hits)] == [0, 1, 2] and models_invoked("retrieval.rerank") == {"claude-haiku-4-5"}


def test_explicit_override_is_the_requested_model_not_a_fallback(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_TASK_MODEL_FINDINGS_EXTRACT", "claude-haiku-4-5")
    r = providers.routing_for("findings.extract", "fake-claude")
    assert r["requested_model"] == "claude-haiku-4-5" and r["fallback_used"] is False and r["fallback_reason"] is None and r["fallback_policy"] == "NO_FALLBACK"
    providers.invoke("findings.extract", system="s", messages=[{"role": "user", "content": "TRANSCRIPT:\n[0:00] x\n\nExtract the findings now."}])
    assert models_invoked("findings.extract") == {"claude-haiku-4-5"}


def test_versioned_alias_is_actual_model_not_fallback():
    r = providers.routing_for("findings.extract", "claude-sonnet-5-20260401")
    assert r == {"requested_model": "claude-sonnet-5", "actual_model": "claude-sonnet-5-20260401", "fallback_used": False, "fallback_reason": None,
                 "fallback_policy": "NO_FALLBACK", "fallback_policy_version": "fallback-policy-v1"}


# ---------------------------------------------------------------- provenance on every artifact + the ledger

def test_every_ai_artifact_and_invocation_carries_the_routing_audit():
    from neurosearch import discover, evals, findings, planner
    g = evals.load_golden(); pid = g["project_id"]
    for sid in g["sources"].values():
        findings.suggest_for_source(pid, sid)
    planner.build_plan(pid)
    discover.discover(pid, verify=False) if hasattr(discover, "discover") else None
    conn = db.connect()
    for table, task in (("project_source_analysis", "findings.extract"), ("project_notes", "findings.extract"), ("plans", "planner.build")):
        rows = conn.execute(f"SELECT routing FROM {table}").fetchall()
        assert rows and all(r["routing"] for r in rows), table
        for r in rows:
            rt = json.loads(r["routing"])
            assert rt["fallback_used"] is False and rt["fallback_reason"] is None and rt["fallback_policy_version"] == "fallback-policy-v1" and rt["requested_model"] == contracts.contract(task).model
    disc = conn.execute("SELECT routing FROM discoveries").fetchall()
    assert all(r["routing"] and json.loads(r["routing"])["fallback_used"] is False for r in disc)
    inv = conn.execute("SELECT fallback_used, fallback_policy_version, model, returned_model FROM invocations WHERE state='completed'").fetchall()
    assert inv and all(r["fallback_used"] == 0 and r["fallback_policy_version"] == "fallback-policy-v1" and r["model"] for r in inv)
    assert not any("fallback" in str(k).lower() and "auto" in str(k).lower() for k in dir(providers))    # no automatic fallback code path exists
