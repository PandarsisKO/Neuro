"""Rung J2 — durable provider circuit breakers, proven with injected outages on the fakes (no live provider).
This module is named to sort AFTER test_core.py: test_core builds the shared settings/database at import time."""
from __future__ import annotations

import os
import tempfile
import time

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_brk_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import breakers, db, fake_ai, jobs, providers  # noqa: E402
from neurosearch.breakers import CLOSED, HALF_OPEN, OPEN, ProviderUnavailable  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests import crashkit  # noqa: E402


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    monkeypatch.setattr(providers, "RETRY_POLICY", {**providers.RETRY_POLICY, "default": {"max_attempts": 1, "backoff": []}, "answer.chat": {"max_attempts": 1, "backoff": []}, "embed": {"max_attempts": 1, "backoff": []}})
    yield
    fake_ai.OUTAGES.clear()
    db._local.conn = None


def overloaded(n: int = 1, status: int = 529):
    return [fake_ai.FakeAPIError(status, "overloaded", name="OverloadedError") for _ in range(n)]


def chat_once(text: str = "hello") -> str:
    from neurosearch import providers as P
    return P.text_of(P.invoke("answer.chat", system="be brief", messages=[{"role": "user", "content": text}]))


def embed_once() -> None:
    from neurosearch.embeddings import embed_query
    embed_query("hello")


def drain(op: str, call) -> int:
    """Call until the injected outage is consumed (a call may make several transport attempts — the breaker counts each). Returns calls made."""
    n = 0
    while fake_ai.OUTAGES.get(op):
        n += 1
        with pytest.raises(Exception):
            call()
    return n


def invocations(task: str | None = None) -> int:
    q = "SELECT COUNT(*) FROM invocations" + (" WHERE task=?" if task else "")
    return int(db.connect().execute(q, (task,) if task else ()).fetchone()[0])


# 1 / 2 / 3 — threshold opens ONLY the affected operation
def test_three_transient_failures_open_only_the_affected_operation():
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(2)
    with pytest.raises(providers.ProviderError):
        chat_once()                                                     # answer.chat makes 2 transport attempts: both fail, both counted
    assert breakers.get("anthropic:messages")["state"] == CLOSED and breakers.get("anthropic:messages")["failures"] == 2
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(1)
    with pytest.raises(providers.ProviderError):
        chat_once()                                                     # the third consecutive transient failure opens it (no further attempt is made)
    b = breakers.get("anthropic:messages")
    assert b["state"] == OPEN and b["failures"] == 3 and b["generation"] == 1 and b["next_probe_at"] > time.time() and b["last_error_type"] == "OVERLOADED"
    # 2: batches and 3: the other provider's operations are untouched
    for op in ("anthropic:batches", "openai:embeddings", "openai:transcription"):
        assert breakers.get(op)["state"] == CLOSED
    embed_once()                                                        # embeddings keep working while messages is open
    with pytest.raises(ProviderUnavailable) as ei:
        chat_once()
    assert ei.value.operation == "anthropic:messages" and invocations("answer.chat") == 3     # the blocked call wrote NO invocation row


def test_transcription_outage_does_not_block_embeddings():
    fake_ai.OUTAGES["openai:transcription"] = overloaded(3, status=503)
    client = providers.openai_client()
    drain("openai:transcription", lambda: client.audio.transcriptions.create(model="whisper-1", file=open(__file__, "rb")))
    assert breakers.get("openai:transcription")["state"] == OPEN and breakers.get("openai:embeddings")["state"] == CLOSED
    embed_once()
    assert breakers.get("openai:embeddings")["state"] == CLOSED


# 4 — account/request conditions never open a breaker
@pytest.mark.parametrize("err", [
    fake_ai.FakeAPIError(401, "invalid api key", name="AuthenticationError"),
    fake_ai.FakeAPIError(403, "permission denied", name="PermissionDeniedError"),
    fake_ai.FakeAPIError(400, "invalid request: messages[0]", name="BadRequestError"),
    fake_ai.FakeAPIError(400, "Your credit balance is too low", name="BadRequestError"),
    fake_ai.FakeAPIError(429, "enforced_spend_limit_reached: monthly limit", body={"error": {"type": "rate_limit_error", "message": "enforced_spend_limit_reached"}}, name="RateLimitError"),
])
def test_non_transient_conditions_do_not_open_a_breaker(err):
    fake_ai.OUTAGES["anthropic:messages"] = [err] * 5
    while fake_ai.OUTAGES["anthropic:messages"]:
        with pytest.raises(providers.ProviderError) as ei:
            chat_once()
        assert ei.value.error_type in ("AUTH", "INVALID_REQUEST", "BILLING", "SPEND_CAP")
    assert breakers.get("anthropic:messages")["state"] == CLOSED and breakers.get("anthropic:messages")["failures"] == 0


def test_schema_mismatch_and_refusal_do_not_touch_the_breaker(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_FAKE_AI_BAD_JSON", "1")
    with pytest.raises(Exception):
        providers.invoke_structured("findings.extract", system="s", messages=[{"role": "user", "content": "TRANSCRIPT:\n[0:00] x\n\nExtract the findings now."}], usage_kind="findings")
    monkeypatch.delenv("NEUROSEARCH_FAKE_AI_BAD_JSON")
    assert breakers.get("anthropic:messages") ["state"] == CLOSED and breakers.get("anthropic:messages")["failures"] == 0


# 5 — ordinary 429 honours retry-after; 6 — spend cap never enters a retry cycle
def test_rate_limit_honours_retry_after_and_spend_cap_is_typed():
    fake_ai.OUTAGES["anthropic:messages"] = [fake_ai.FakeAPIError(429, "rate limited", retry_after="90", name="RateLimitError") for _ in range(3)]
    t0 = time.time()
    drain("anthropic:messages", chat_once)
    assert breakers.get("anthropic:messages")["last_error_type"] == "RATE_LIMIT"
    b = breakers.get("anthropic:messages")
    assert b["state"] == OPEN and 85 <= b["next_probe_at"] - t0 <= 95                 # the provider's window, not our own cooldown
    e = fake_ai.FakeAPIError(429, "spend cap", body={"error": {"message": "enforced_spend_limit_reached"}}, name="RateLimitError")
    assert providers.classify_error(e) == "SPEND_CAP" and "SPEND_CAP" not in providers.TRANSIENT_TYPES
    e2 = fake_ai.FakeAPIError(429, "slow down", retry_after="5", name="RateLimitError")
    assert providers.classify_error(e2) == "RATE_LIMIT" and providers.retry_after_of(e2) == 5.0


# 7 / 8 / 9 — exactly one probe; success closes + wakes; transient probe failure reopens
def test_half_open_allows_exactly_one_probe_and_closes_on_success():
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(3)
    drain("anthropic:messages", chat_once)
    db.connect().execute("UPDATE circuit_breakers SET next_probe_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()
    g1 = breakers.gate("anthropic:messages", "worker-A")
    assert g1["probe"] is True and breakers.get("anthropic:messages")["state"] == HALF_OPEN and breakers.get("anthropic:messages")["probe_owner"] == "worker-A"
    with pytest.raises(ProviderUnavailable) as ei:
        breakers.gate("anthropic:messages", "worker-B")                                 # only one prober across all workers
    assert ei.value.state == HALF_OPEN
    # park two jobs on the operation, then the probe succeeds
    j1 = db.create_job("suggest_findings", {"project_id": "p", "source_ids": ["s1"]}); j2 = db.create_job("suggest_findings", {"project_id": "p", "source_ids": ["s2"]})
    for j in (j1, j2):
        db.park_provider_wait(j["id"], "anthropic:messages", time.time() + 600, "waiting")
    assert all(db.derived_status(db.get_job(j["id"])) == "provider_wait" for j in (j1, j2))
    assert breakers.record_success("anthropic:messages", "worker-B") is False            # a stray success from a non-prober does not close it
    assert breakers.record_success("anthropic:messages", "worker-A") is True
    b = breakers.get("anthropic:messages")
    assert b["state"] == CLOSED and b["failures"] == 0 and b["probe_owner"] is None
    assert all(db.get_job(j["id"])["not_before"] is None and db.derived_status(db.get_job(j["id"])) == "queued" for j in (j1, j2))   # released
    # 9: a transient probe failure reopens with a longer cooldown and a new generation
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(3)
    drain("anthropic:messages", chat_once)
    db.connect().execute("UPDATE circuit_breakers SET next_probe_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(1)
    with pytest.raises(providers.ProviderError):
        chat_once()                                                                      # this call IS the leased probe, and it fails
    b = breakers.get("anthropic:messages")
    assert b["state"] == OPEN and b["generation"] == 3 and b["next_probe_at"] - time.time() > breakers.COOLDOWN_S * 1.5 and b["probe_owner"] is None


# 10 — a prober that dies releases the lease after expiry
def test_crashed_probe_lease_expires_and_another_worker_can_probe(monkeypatch):
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(3)
    drain("anthropic:messages", chat_once)
    db.connect().execute("UPDATE circuit_breakers SET next_probe_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()
    assert breakers.gate("anthropic:messages", "worker-crashed")["probe"] is True
    with pytest.raises(ProviderUnavailable):
        breakers.gate("anthropic:messages", "worker-B")
    db.connect().execute("UPDATE circuit_breakers SET probe_expires_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()   # the prober never reported
    g = breakers.gate("anthropic:messages", "worker-B")
    assert g["probe"] is True and breakers.get("anthropic:messages")["probe_owner"] == "worker-B"


# 11 — a stale worker cannot close a newer generation
def test_stale_worker_cannot_close_a_newer_generation():
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(3)
    drain("anthropic:messages", chat_once)
    db.connect().execute("UPDATE circuit_breakers SET next_probe_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()
    g = breakers.gate("anthropic:messages", "old-worker")                                # generation 1 probe
    breakers.record_failure("anthropic:messages", "OVERLOADED", "old-worker", generation=g["generation"])   # its probe fails: generation 2, OPEN
    assert breakers.get("anthropic:messages")["generation"] == 2
    assert breakers.record_success("anthropic:messages", "old-worker", generation=1) is False   # a late success from generation 1 is ignored
    assert breakers.get("anthropic:messages")["state"] == OPEN


# 12 — provider_wait costs nothing
def test_provider_wait_consumes_zero_attempts_invocations_and_dollars(monkeypatch):
    from neurosearch import evals
    g = evals.load_golden(only={"yt01"}); pid = g["project_id"]
    fake_ai.OUTAGES["anthropic:messages"] = overloaded(3)
    drain("anthropic:messages", chat_once)
    inv0, usage0 = invocations(), db.connect().execute("SELECT COALESCE(SUM(cost),0) FROM usage").fetchone()[0]
    j = db.create_job("suggest_findings", {"project_id": pid, "source_ids": [g["sources"]["yt01"]]})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings",)) == "queued"
    jj = db.get_job(j["id"])
    assert db.derived_status(jj) == "provider_wait" and jj["wait_operation"] == "anthropic:messages" and int(jj["attempts"] or 0) == 0
    assert "Waiting for Anthropic Messages" in jj["message"] and "Next check after" in jj["message"] and "529" not in jj["message"]
    assert invocations() == inv0 and db.connect().execute("SELECT COALESCE(SUM(cost),0) FROM usage").fetchone()[0] == usage0
    assert any(e["event_type"] == "provider_wait" for e in db.job_events(j["id"]))
    # 13: the state survives a "restart" (a fresh connection; lease recovery leaves the wait intact)
    db._local.conn = None
    db.recover_expired_leases(all_running=True)
    assert breakers.get("anthropic:messages")["state"] == OPEN and db.derived_status(db.get_job(j["id"])) == "provider_wait"
    # the circuit closes → the job is released and completes with real invocations
    db.connect().execute("UPDATE circuit_breakers SET next_probe_at=? WHERE operation='anthropic:messages'", (time.time() - 1,)); db.connect().commit()
    db.connect().execute("UPDATE jobs SET not_before=NULL WHERE id=?", (j["id"],)); db.connect().commit()
    assert sim.step(("suggest_findings",)) == "done"                                     # this job's call was the probe; it succeeded
    assert breakers.get("anthropic:messages")["state"] == CLOSED and int(db.get_job(j["id"])["attempts"] or 0) == 0


def test_batch_submission_parks_on_an_open_batches_breaker(monkeypatch):
    from neurosearch import evals
    g = evals.load_golden(only={"yt01"}); pid = g["project_id"]
    fake_ai.OUTAGES["anthropic:batches"] = overloaded(3)
    client = providers.anthropic_client()
    drain("anthropic:batches", lambda: client.messages.batches.create(requests=[]))
    assert breakers.get("anthropic:batches")["state"] == OPEN and breakers.get("anthropic:messages")["state"] == CLOSED
    j = db.create_job("suggest_findings_batch", {"project_id": pid, "source_ids": [g["sources"]["yt01"]]})
    sim = crashkit.Sim()
    assert sim.step(("suggest_findings_batch",)) == "queued" and db.derived_status(db.get_job(j["id"])) == "provider_wait"
    assert db.get_job(j["id"])["wait_operation"] == "anthropic:batches"
    chat_once()                                                                          # interactive messages still flow


# 14 — Health and job diagnostics
def test_health_and_job_diagnostics(monkeypatch):
    h = db.health()["providers"]
    assert [p["label"] for p in h] == ["Anthropic Messages", "Anthropic Batches", "OpenAI Embeddings", "OpenAI Transcription"] and all(p["status"] == "Healthy" for p in h)
    fake_ai.OUTAGES["openai:embeddings"] = overloaded(3, status=500)
    drain("openai:embeddings", embed_once)
    j = db.create_job("ingest_url", {"url": "https://example.com", "project_id": "p"})
    db.park_provider_wait(j["id"], "openai:embeddings", breakers.get("openai:embeddings")["next_probe_at"], breakers.wait_message("openai:embeddings", breakers.get("openai:embeddings")["next_probe_at"]))
    h = {p["operation"]: p for p in db.health()["providers"]}
    e = h["openai:embeddings"]
    assert e["status"] == "Waiting" and "next check after" in e["detail"] and e["waiting_jobs"] == 1 and h["openai:transcription"]["status"] == "Healthy"
    assert "500" not in e["detail"] and "OVERLOADED" not in e["detail"]                 # plain language, no provider internals
    from neurosearch import api
    jd = api.api_job(j["id"])
    assert jd["state"] == "provider_wait" and jd["provider_wait"]["label"] == "OpenAI Embeddings" and jd["provider_wait"]["until"] and "Next check after" in jd["provider_wait"]["message"]
