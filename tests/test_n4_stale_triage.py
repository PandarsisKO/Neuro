"""S1 — stale triage (0.40.0): the stale set is three answers — rebuild (matters / transcript changed), accept as still
usable, retry failed — never one bill. Accepting is recorded against the exact inputs and survives assess until the inputs
change again; a transcript change is never acceptable; the cost line names the provider. (Sorts after test_n3.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_triage_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import api, claims, db, fake_ai, findings, ingest, jobs, staleness  # noqa: E402
from neurosearch import claude_code as CC  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    monkeypatch.setattr(settings, "auto_suggest", False)
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    db._local.conn = None
    db.init_db()
    fake_ai.OUTAGES.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


TEXT = "0:05 cloudflare pages is free hosting for static sites with no bandwidth bill\n3:40 never touch the MX records when you move hosting or email breaks"


def _project():
    p = db.create_project("Triage", "hosting")
    ids = []
    for i in range(4):
        r = ingest.ingest_text(f"Hosting talk {i}", TEXT.replace("cloudflare", f"provider{i}"), project_id=p["id"])
        findings.suggest_for_source(p["id"], r["source_id"], force=True)
        ids.append(r["source_id"])
    return p, ids


def _by(t, key):
    return {r["source_id"] for r in t["tiers"][key]["sources"]}


def test_tiers_partition_the_stale_set_by_why_and_weight(monkeypatch):
    p, ids = _project()
    assert staleness.triage(p["id"])["stale_total"] == 0
    # weight: source 0 is a priority source; source 1 has three approved findings rated 5; sources 2 and 3 carry nothing
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (p["id"], ids[0])); db.connect().commit()
    for k in range(3):
        n = db.add_project_note(p["id"], f"rule {k} [1]", citations=[{"n": 1, "source_id": ids[1], "title": "t"}], status="approved", source_id=ids[1], importance=5)
    # the brief changes: everything is stale by inputs
    db.update_project(p["id"], brief="hosting and email deliverability")
    t = staleness.triage(p["id"])
    assert t["stale_total"] == 4
    assert _by(t, "rebuild_matters") == {ids[0], ids[1]} and _by(t, "accept") == {ids[2], ids[3]}
    assert not _by(t, "rebuild_transcript") and not _by(t, "retry_failed")
    whys = {r["source_id"]: r["why"] for r in t["tiers"]["rebuild_matters"]["sources"]}
    assert whys[ids[0]] == ["priority source"] and whys[ids[1]] == ["3 approved findings rated 4–5"]
    # transcript change moves a source into its own, never-acceptable tier
    seg = [{"start": 0.0, "end": 5.0, "text": "a new transcript entirely about email"}]
    db.replace_transcript(ids[2], seg, seg)
    t2 = staleness.triage(p["id"])
    assert ids[2] in _by(t2, "rebuild_transcript") and ids[2] not in _by(t2, "accept")
    # cost lines name the provider: dollars on the API…
    assert t2["local"] is False and all(x["cost_line"].endswith("on the API") for x in t2["tiers"].values() if x["count"])
    # …time on Claude Code when the local profile is on and ready
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setenv(CC.FAKE_ENV, "ready")
    CC._state["health"] = {"state": "ready", "checked_at": 1e12}
    t3 = staleness.triage(p["id"])
    assert t3["local"] is True and all("Claude Code" in x["cost_line"] and x["cost_line"].startswith("$0") for x in t3["tiers"].values() if x["count"])
    assert all(x["local_minutes"] is not None for x in t3["tiers"].values() if x["count"])


def test_accept_survives_assess_until_the_inputs_change_again_and_refuses_transcript_changes():
    p, ids = _project()
    db.update_project(p["id"], brief="hosting and email deliverability")
    t = staleness.triage(p["id"])
    assert _by(t, "accept") == set(ids)
    r = staleness.accept(p["id"], tier="accept")
    assert r["accepted"] == 4 and r["refused"] == 0
    a = staleness.assess(p["id"])
    assert all(x["status"] == staleness.ACCEPTED and "accepted" in (x["note"] or "") for x in a["sources"])
    assert a["stale_sources"] == 0 and staleness.triage(p["id"])["stale_total"] == 0 and staleness.triage(p["id"])["accepted"] == 4
    # nothing was queued or spent by accepting
    assert not [j for j in db.list_jobs(50) if j["kind"].startswith("suggest")]
    # the findings are still there and still read as approved/suggested — accept never touches them
    assert len(db.list_project_notes(p["id"], status="suggested")) >= 4
    # a further brief change stales them again (the accepted hash no longer matches)
    db.update_project(p["id"], brief="hosting, email and DNS")
    assert staleness.triage(p["id"])["stale_total"] == 4
    # a transcript change is refused
    seg = [{"start": 0.0, "end": 5.0, "text": "brand new words"}]
    db.replace_transcript(ids[0], seg, seg)
    r2 = staleness.accept(p["id"], [ids[0], ids[1]])
    assert r2["accepted"] == 1 and r2["refused"] == 1
    # rebuilding an accepted source is still possible and clears the acceptance by producing a fresh analysis
    findings.suggest_for_source(p["id"], ids[1], force=True)
    st = next(x for x in staleness.assess(p["id"])["sources"] if x["source_id"] == ids[1])
    assert st["status"] == "current"


def test_rebuild_by_tier_and_retry_failed_only_queue_that_tier(monkeypatch):
    p, ids = _project()
    db.connect().execute("UPDATE project_sources SET priority=1 WHERE project_id=? AND source_id=?", (p["id"], ids[0])); db.connect().commit()
    db.update_project(p["id"], brief="hosting and email deliverability")
    out = api.api_rebuild_stale(p["id"], api.RebuildIn(what=["findings"], tier="rebuild_matters"))
    assert out["queued"] == 1 and out["tier"] == "rebuild_matters"
    j = db.get_job(out["job_ids"][0])
    assert j["kind"] == "suggest_findings" and j["payload"]["source_ids"] == [ids[0]] and j["payload"]["force"] is True
    # a failed rebuild lands the source in retry_failed, and retrying queues exactly it
    claimed = db.claim_job(("suggest_findings",), worker_id="t")
    assert claimed and claimed["id"] == j["id"]
    assert db.finish_job(j["id"], claimed["run_id"], "failed", message="error: provider exploded")
    t = staleness.triage(p["id"])
    assert _by(t, "retry_failed") == {ids[0]} and ids[0] not in _by(t, "rebuild_matters")
    assert any("provider exploded" in z for r in t["tiers"]["retry_failed"]["sources"] for z in r["reasons"])
    out2 = api.api_rebuild_stale(p["id"], api.RebuildIn(what=["findings"], tier="retry_failed"))
    assert out2["queued"] == 1 and db.get_job(out2["job_ids"][0])["payload"]["source_ids"] == [ids[0]]
    # an empty tier queues nothing
    assert api.api_rebuild_stale(p["id"], api.RebuildIn(what=["findings"], tier="rebuild_transcript"))["queued"] == 0
    # the API accept endpoint defaults to the accept tier and reports counts
    r = api.api_staleness_accept(p["id"], api.AcceptIn())
    assert r["accepted"] == 3
    assert api.api_staleness_triage(p["id"])["tiers"]["accept"]["count"] == 0


def _make_legacy(project_id: str, source_ids: list[str]) -> None:
    """A row migrated from Neuro Search 0.15: no input_hash, status legacy_unverified — exactly what db._migrate writes."""
    with db.tx() as conn:
        conn.execute("UPDATE project_source_analysis SET status='legacy_unverified', provider='migrated', input_hash=NULL "
                     "WHERE project_id=? AND source_id IN (%s)" % ",".join("?" * len(source_ids)), (project_id, *source_ids))


def test_a_legacy_source_can_be_accepted_and_the_tier_actually_empties():
    """0.45.1 regression. Every source in a migrated library is legacy_unverified, and assess returned from the legacy
    branch before reading accepted_hash — so accept() reported success, wrote the hash, and NOTHING changed: the accept
    tier could never empty and the stale pile looked permanent no matter what the user pressed."""
    p, ids = _project()
    _make_legacy(p["id"], ids)
    a = staleness.assess(p["id"])
    assert {x["status"] for x in a["sources"]} == {staleness.LEGACY}
    t = staleness.triage(p["id"])
    assert _by(t, "accept") == set(ids) and t["stale_total"] == 4 and t["accepted"] == 0

    r = staleness.accept(p["id"], tier="accept")
    assert r["accepted"] == 4 and r["refused"] == 0

    # the acceptance is now VISIBLE: this is the assertion that failed before the fix
    a2 = staleness.assess(p["id"])
    assert all(x["status"] == staleness.ACCEPTED and "accepted" in (x["note"] or "") for x in a2["sources"])
    assert a2["stale_sources"] == 0
    t2 = staleness.triage(p["id"])
    assert t2["stale_total"] == 0 and t2["accepted"] == 4 and t2["tiers"]["accept"]["count"] == 0
    # an accepted source is not quoted as work to buy any more, and nothing was queued or spent
    assert all(x["estimate"] == 0 for x in a2["sources"])
    assert t2["tiers"]["accept"]["api_cost"] == 0 and not [j for j in db.list_jobs(50) if j["kind"].startswith("suggest")]
    # the findings themselves are untouched
    assert len(db.list_project_notes(p["id"], status="suggested")) >= 4
    # and the findings workbench stops calling them stale
    from neurosearch import findings_view
    assert findings_view.query(p["id"], status="all")["facets"]["stale"].get("stale", 0) == 0


def test_a_legacy_acceptance_holds_for_exactly_the_inputs_it_was_given_for():
    """Accepting a legacy source is not a blanket 'never ask again'. The accepted hash covers the transcript, the brief and
    the prompt, so ANY of them changing puts the source back in the pile — the same deal the stale branch gives, and the
    reason the acceptance is safe to offer: it can never hide findings written for inputs that no longer exist."""
    p, ids = _project()
    _make_legacy(p["id"], ids)
    staleness.accept(p["id"], tier="accept")
    assert staleness.triage(p["id"])["stale_total"] == 0

    # the transcript changing brings that source back, still as a legacy row, and quoted as work again
    seg = [{"start": 0.0, "end": 5.0, "text": "brand new words"}]
    db.replace_transcript(ids[0], seg, seg)
    back = next(x for x in staleness.assess(p["id"])["sources"] if x["source_id"] == ids[0])
    assert back["status"] == staleness.LEGACY and back["estimate"] > 0
    assert staleness.triage(p["id"])["stale_total"] == 1

    # so does editing the brief, for all of them — accepted answers are answers about a question that just changed
    db.update_project(p["id"], brief="hosting, email and DNS")
    assert staleness.triage(p["id"])["stale_total"] == 4
    # and accepting again is one action that clears them for the new brief
    assert staleness.accept(p["id"], tier="accept")["accepted"] == 4
    assert staleness.triage(p["id"])["stale_total"] == 0


def test_every_tier_quotes_both_currencies_so_faster_is_visible(monkeypatch):
    """0.45.2. The card used to print ONE price — whichever provider was configured. On Kyle's local setup that made a
    4-hour tier look like the only thing on offer: the API price existed in the payload but nothing rendered it and no
    button could reach it, so 'is there a faster option?' had no answer in the UI. Every tier now carries local_line AND
    api_line, and the fast button only appears when there is a real choice to make."""
    p, ids = _project()
    db.update_project(p["id"], brief="hosting and email deliverability")

    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(CC, "health", lambda wait=False: {"state": "ready"})
    t = staleness.triage(p["id"])
    x = t["tiers"]["accept"]
    assert t["local"] and x["count"] == 4
    assert x["local_line"].startswith("$0 ") and "Claude Code" in x["local_line"]
    assert x["api_line"].startswith("$") and "on the API" in x["api_line"]
    assert x["cost_line"] == x["local_line"]                   # the default answer is still the free one
    assert x["api_cost"] > 0                                   # …and the paid one is a real, quotable number

    # an empty tier quotes nothing at all (no "$0.00 on the API" on a row that does not exist)
    empty = t["tiers"]["retry_failed"]
    assert empty["count"] == 0 and empty["local_line"] == "" and empty["api_line"] == "" and empty["cost_line"] == ""

    # on the cloud profile there is no second currency to offer: one price, and it is the API one
    monkeypatch.setattr(settings, "ai_profile", "cloud")
    t2 = staleness.triage(p["id"])
    y = t2["tiers"]["accept"]
    assert not t2["local"] and y["local_line"] == "" and y["cost_line"] == y["api_line"]

    # the UI renders the fast button from exactly these fields and routes it at a route that exists
    html = (__import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web" / "index.html").read_text()
    assert "x.local_line ?" in html and "rebuildTier('${key}', 'api')" in html
    assert "/accelerate" in html and any(getattr(r, "path", "") == "/api/projects/{project_id}/accelerate" for r in api.app.routes)


def test_the_local_eta_is_wall_clock_and_the_batch_price_is_offered(monkeypatch):
    """0.45.3. Kyle's card read '$0 · about 4 h 24 min on Claude Code' next to '$9.96 on the API' and the gap felt wrong —
    because both halves were misleading. The ETA multiplied windows by the per-window minute and never divided by the pool
    actually doing the work, so two workers were quoted as one; and the Message Batches price (half, in the background,
    findings.extract is batch_allowed) existed in the pricing model but was offered nowhere. Three real options now."""
    p, ids = _project()
    db.update_project(p["id"], brief="hosting and email deliverability")
    monkeypatch.setattr(settings, "ai_profile", "local")
    monkeypatch.setattr(CC, "health", lambda wait=False: {"state": "ready"})

    monkeypatch.setattr(settings, "local_ai_workers", 1)
    one = staleness.triage(p["id"])["tiers"]["accept"]
    monkeypatch.setattr(settings, "local_ai_workers", 2)
    two = staleness.triage(p["id"])["tiers"]["accept"]
    assert one["local_workers"] == 1 and two["local_workers"] == 2
    assert two["local_minutes"] == round(one["local_minutes"] / 2)      # wall clock, not work
    assert "2 at a time" in two["local_line"] and "at a time" not in one["local_line"]
    assert two["api_cost"] == one["api_cost"]                            # parallelism is free; it changes time, never money

    # the batch price is the API price at the documented multiplier, and it is named as a separate answer
    from neurosearch import usage
    assert two["batch_cost"] == round(two["api_cost"] * usage.BATCH_MULT, 4) < two["api_cost"]
    assert "background" in two["batch_line"]
    # findings.extract really is batchable and the rebuild route really takes that transport
    from neurosearch import contracts
    assert contracts.contract("findings.extract").batch_allowed
    r = api.api_rebuild_stale(p["id"], api.RebuildIn(what=["findings"], tier="accept", transport="batch"))
    assert r["queued"] == 1                                              # ONE batch job for the whole tier, not one per source
    assert db.list_jobs(5)[0]["kind"] == "suggest_findings_batch"

    # an empty tier still quotes nothing, and the UI reads exactly these fields
    assert staleness.triage(p["id"])["tiers"]["retry_failed"]["batch_line"] == ""
    html = (__import__("pathlib").Path(__import__("neurosearch").__file__).parent / "web" / "index.html").read_text()
    assert "x.batch_line" in html and "rebuildTier('${key}', 'batch')" in html and "rebuildTier('${key}', 'api')" in html
