"""A capped Findings job can run for $0 through the existing queue."""
import json
from types import SimpleNamespace

from neurosearch import db, findings, ingest, jobs, ollama, providers, usage
from neurosearch.config import override, settings
from tests.test_core import isolated_db  # noqa: F401


def enable(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(settings, "mac_findings", True)


def test_mac_slots_only_take_eligible_findings_and_respect_pause(isolated_db, monkeypatch):
    enable(monkeypatch)
    candidates = [db.create_job("suggest_findings", {"project_id": f"p{i}"}) for i in range(4)]
    for job, wait in zip(candidates, ("budget", "chatgpt_slot", "budget", "scheduled")):
        db.requeue_job(job["id"], delay=3600, wait_reason=wait)
    api = db.create_job("suggest_findings", {"project_id": "api"}, execution_policy="api_only")
    db.requeue_job(api["id"], delay=3600, wait_reason="budget")
    db.kv_set("usage:rate_blocked_until", str(db.now() + 3600))

    def claim(busy=True):
        return db.claim_mac_findings("test", lanes=None, chatgpt_busy=busy)

    first = claim(False)
    assert first["id"] == candidates[0]["id"]
    second = claim()
    assert second["id"] == candidates[1]["id"]
    assert claim() is None
    db.kv_set("mac_work:paused", "1")
    assert db.mac_work_status()["running"]
    for job in (first, second):
        db.finish_job(job["id"], job["run_id"], "done")
    assert not db.mac_work_status()["running"]
    assert claim() is None
    db.kv_set("mac_work:paused", None)
    third = claim()
    assert third["id"] == candidates[2]["id"]
    assert claim() is None


def test_pause_resumes_saved_window_without_paid_fallback(isolated_db, monkeypatch):
    enable(monkeypatch)
    project = db.create_project("Workshop")
    passage = "Replace the K2 filter every ninety days under normal conditions."
    with override(fake_ai=True, auto_suggest=False):
        sid = ingest.store_transcript(
            {"platform": "web", "title": "K2 manual", "url": "https://example.com/mac-findings-test",
             "segments": [{"start": 0, "end": 10, "text": passage}]}, project_id=project["id"],
        )["source_id"]
    monkeypatch.setattr(findings, "_windows", lambda *a, **k: [f"[p. 1] {passage}", f"[p. 2] {passage}"])
    seen = []

    def create(**kw):
        seen.append(kw["model"])
        if len(seen) == 1:
            db.kv_set("mac_work:paused", "1")
        out = {"summary": "K2 instructions", "substance": 85, "findings": [
            {"title": "Replace the K2 filter regularly", "finding": "Follow the maintenance schedule.",
             "quote": passage, "ts": "p. 1", "importance": 4},
        ]}
        return SimpleNamespace(provider="ollama", model=kw["model"], stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(out))],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=50), seconds=1)

    def no_spend(*args, **kwargs):
        raise AssertionError("Mac work attempted paid admission")

    monkeypatch.setattr(ollama, "create", create)
    monkeypatch.setattr(usage, "guard", no_spend)
    monkeypatch.setattr(providers, "_invoke_anthropic", no_spend)
    job = db.create_job("suggest_findings", {"project_id": project["id"], "source_ids": [sid]})
    db.requeue_job(job["id"], delay=3600, wait_reason="budget")
    claimed = db.claim_mac_findings("test", lanes=None, chatgpt_busy=True)
    assert jobs.execute(claimed) == "queued"
    assert db.derived_status(db.get_job(job["id"])) == "mac_paused"
    assert not db.list_project_notes(project["id"], status="suggested")
    assert db.claim_job(("suggest_findings",)) is None
    db.kv_set("mac_work:paused", None)
    assert jobs.execute(db.claim_mac_findings("test", lanes=None, chatgpt_busy=False)) == "done"
    assert seen == ["gemma4:26b", "gemma4:26b"]
    assert db.list_project_notes(project["id"], status="suggested")
    assert db.get_job(job["id"])["executed_by"] == "ollama"
    rows = db.connect().execute("SELECT cost,transport FROM usage WHERE kind='findings'").fetchall()
    assert [tuple(row) for row in rows] == [(0, "ollama"), (0, "ollama")]
