"""The Mac pause is a durable admission hold; only the current profile can finish."""
import json
from types import SimpleNamespace

import httpx

from neurosearch import api, db, ingest, jobs, library, ollama, providers
from neurosearch.config import override, settings
from tests.test_core import isolated_db  # noqa: F401


PROFILE = {"summary": "A manufacturer's manual for the K2 filter.", "topics": ["filter replacement"],
           "entities": ["K2"], "document_type": "other", "evidence_class": "authoritative",
           "temporal_character": "static", "useful_for": ["How to replace the K2 filter"],
           "authority_notes": "The manufacturer describes its own equipment."}


def _enable(monkeypatch):
    monkeypatch.setattr(settings, "mac_profiles", True)
    monkeypatch.setattr(settings, "fake_ai", False)


def _wanted(name):
    # Build the stored transcript and its derived baseline before any model call.
    with override(fake_ai=True):
        sid = ingest.store_transcript({"platform": "web", "title": name, "url": f"https://example.com/{name}",
                                       "segments": [{"start": 0, "end": 40, "text": "Replace K2 filters every 90 days under normal conditions."}]})["source_id"]
    assert library.baseline(sid)
    assert library.want([sid], "test request") == 1
    return sid


def _response(model):
    return SimpleNamespace(provider="ollama", model=model, stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=json.dumps(PROFILE))],
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50), seconds=1)


def test_pause_preserves_progress_and_does_not_hold_claims(isolated_db, monkeypatch):
    _enable(monkeypatch)
    one, two = _wanted("manual-one"), _wanted("manual-two")
    j = library.maybe_queue_batch()
    seen = []
    def create(**kw):
        seen.append(kw["model"])
        if len(seen) == 1:
            assert api.api_mac_work(api.MacWorkIn(paused=True)) == {"enabled": True, "paused": True, "running": True}
        return _response(kw["model"])
    monkeypatch.setattr(ollama, "create", create)
    monkeypatch.setattr(providers, "_invoke_anthropic", lambda *a, **k: (_ for _ in ()).throw(AssertionError("paid route")))
    from neurosearch import usage
    monkeypatch.setattr(usage, "guard", lambda *_: (_ for _ in ()).throw(AssertionError("paid guard")))
    first = db.claim_job((db.MAC_PROFILE_JOB,))
    assert jobs.execute(first, "test") == "queued"
    assert db.derived_status(db.get_job(j["job_id"])) == "mac_paused"
    assert db.mac_work_status() == {"enabled": True, "paused": True, "running": False}
    assert db.claim_job((db.MAC_PROFILE_JOB,)) is None
    assert library.profile(one)["enriched_status"] == "current"
    assert library.profile(two)["enriched_status"] == "wanted"
    other = db.create_job("extract_claims", {"project_id": "other"})
    assert db.claim_job(("extract_claims",))["id"] == other["id"]

    api.api_mac_work(api.MacWorkIn(paused=False))
    assert jobs.execute(db.claim_job((db.MAC_PROFILE_JOB,)), "test") == "done"
    assert seen == ["qwen3.5:9b", "qwen3.5:9b"]
    row = db.connect().execute("SELECT enriched_routing FROM source_profiles WHERE source_id=?", (two,)).fetchone()
    assert json.loads(row[0])["executed_by"] == "ollama"
    assert db.get_job(j["job_id"])["executed_by"] == "ollama"
    rows = db.connect().execute("SELECT cost,transport,billing_basis FROM usage WHERE kind='profile'").fetchall()
    assert [tuple(r) for r in rows] == [(0.0, "ollama", "on_device")] * 2


def test_missing_local_model_waits_without_spending_or_releasing_account_hold(isolated_db, monkeypatch):
    _enable(monkeypatch)
    sid = _wanted("manual-unavailable")
    j = library.maybe_queue_batch()
    db.kv_set("providers:billing_until", str(db.now() + 3600))
    def missing(**kw):
        raise ollama.ModelUnavailable("model missing")
    monkeypatch.setattr(ollama, "create", missing)
    assert jobs.execute(db.claim_job((db.MAC_PROFILE_JOB,)), "test") == "queued"
    parked = db.get_job(j["job_id"])
    assert parked["attempts"] == 0 and parked["wait_reason"] == "provider"
    assert library.profile(sid)["enriched_status"] == "wanted"
    assert db.account_gate_active()
    assert db.connect().execute("SELECT count(*) FROM usage WHERE kind='profile'").fetchone()[0] == 0


def test_ollama_only_posts_schema_to_loopback_and_requests_unload(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert body["keep_alive"] == 0 and body["think"] is False
        assert "summary" in body["format"]["required"]
        return httpx.Response(200, json={"model": body["model"], "message": {"content": json.dumps(PROFILE)}})
    real_client = httpx.Client
    def client(**kw):
        assert kw["trust_env"] is False
        return real_client(**kw, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ollama.httpx, "Client", client)
    result = ollama.create(model="qwen3.5:9b", system="catalogue this source", messages=[{"role": "user", "content": "passage"}],
                           schema="source-profile-v1", max_tokens=1200, timeout=10)
    assert result.model == "qwen3.5:9b"



def test_legacy_cloud_batch_can_run_while_mac_is_paused_and_mac_jobs_serialize(isolated_db, monkeypatch):
    _enable(monkeypatch)
    mac = db.create_job(db.MAC_PROFILE_JOB, {"on_device": True}, dedupe_key="first")
    extra = db.create_job(db.MAC_PROFILE_JOB, {"on_device": True}, dedupe_key="second")
    cloud = db.create_job(db.MAC_PROFILE_JOB, {}, dedupe_key="legacy")
    db.kv_set("mac_work:paused", "1")
    assert db.claim_job((db.MAC_PROFILE_JOB,))["id"] == cloud["id"]
    assert db.claim_job((db.MAC_PROFILE_JOB,)) is None
    db.kv_set("mac_work:paused", None)
    first = db.claim_job((db.MAC_PROFILE_JOB,))
    assert first["id"] == mac["id"]
    assert db.claim_job((db.MAC_PROFILE_JOB,)) is None
    db.finish_job(first["id"], first["run_id"], "done")
    assert db.claim_job((db.MAC_PROFILE_JOB,))["id"] == extra["id"]
