"""Rung G1 — global source identity: one underlying source → one global acquisition, N project relationships.
(Sorts after test_core, which builds the shared settings/DB at import.) No API client here: everything runs against
a private database per test, under fakes."""
from __future__ import annotations

import os
import tempfile
import threading

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_g1_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"
os.environ.pop("OPENAI_API_KEY", None)

import pytest  # noqa: E402

from neurosearch import db, identity, ingest, jobs  # noqa: E402
from neurosearch.config import settings  # noqa: E402
from tests import crashkit  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    monkeypatch.setattr(settings, "auto_suggest", True)
    monkeypatch.setattr(settings, "daily_budget", 1000)
    db._local.conn = None
    db.init_db()
    jobs.CRASH_AT.clear()
    with jobs._running_lock:
        jobs._running.clear()
    yield
    db._local.conn = None


def _projects(n=2):
    return [db.create_project(f"P{i}", "buying a small business with an SBA loan")["id"] for i in range(n)]


def _jobs_of(kind):
    return [j for j in db.list_jobs(200) if j["kind"] == kind]


def _links(sid):
    return {r["project_id"] for r in db.connect().execute("SELECT project_id FROM project_sources WHERE source_id=?", (sid,)).fetchall()}


# ------------------------------------------------------------------ the five states, by hand

def test_resolver_states_and_transactional_create():
    a, b = _projects()
    cand = identity.Candidate(platform="youtube", external_id="abcdefghijk", url="https://www.youtube.com/watch?v=abcdefghijk", title="v")
    r1 = identity.resolve_or_create_source(cand, a)
    assert r1.state == identity.NEW and r1.created and r1.attached and _links(r1.source["id"]) == {a}
    r2 = identity.resolve_or_create_source(cand, a)
    assert r2.state == identity.ALREADY_IN_PROJECT and not r2.created and not r2.attached and r2.source["id"] == r1.source["id"]
    r3 = identity.resolve_or_create_source(cand, b)
    assert r3.state == identity.EXISTING_PENDING and r3.attached and _links(r1.source["id"]) == {a, b}
    assert r3.source["status"] == "pending"                                                    # never reset by the second add
    db.set_source_status(r1.source["id"], "failed", "boom")
    c = db.create_project("P2", "x")["id"]
    r4 = identity.resolve_or_create_source(cand, c)
    assert r4.state == identity.EXISTING_FAILED and r4.source["status"] == "failed" and not r4.resumed   # attached, not retried
    r5 = identity.resolve_or_create_source(cand, c, retry=True)
    assert r5.resumed and r5.source["status"] == "pending"
    db.set_source_status(r1.source["id"], "ready")
    d = db.create_project("P3", "x")["id"]
    r6 = identity.resolve_or_create_source(cand, d)
    assert r6.state == identity.EXISTING_READY and r6.attached
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    ev = db.validation_events(kind="source_reused")
    assert len(ev) == 3 and int(db.kv_get("library:acquisitions_avoided")) == 2 and int(db.kv_get("library:failed_attached")) == 1


def test_concurrent_adds_of_the_same_source_make_one_row():
    pids = _projects(8)
    results, errors = [], []
    def add(pid):
        db._local.conn = None
        try:
            results.append(identity.resolve_or_create_source(
                identity.Candidate(platform="youtube", external_id="racecondition", url="https://www.youtube.com/watch?v=racecondition"), pid))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=add, args=(p,)) for p in pids]
    [t.start() for t in ts]; [t.join() for t in ts]
    db._local.conn = None
    assert not errors and len(results) == 8
    assert len({r.source["id"] for r in results}) == 1 and sum(r.created for r in results) == 1
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1 and len(_links(results[0].source["id"])) == 8


def test_identity_order_native_id_then_canonical_url_then_fingerprint_then_legacy_key(tmp_path):
    a, = _projects(1)
    # canonical URL identity for a source with no native id
    c1 = identity.Candidate(platform="media", external_id=None, url="https://example.com/ep/1?utm=x", canonical_url="https://example.com/ep/1")
    r1 = identity.resolve_or_create_source(c1, a)
    assert r1.created and r1.source["external_id"] == "https://example.com/ep/1"
    r1b = identity.resolve_or_create_source(identity.Candidate(platform="media", external_id=None, url="https://example.com/ep/1", canonical_url="https://example.com/ep/1"), a)
    assert not r1b.created and r1b.source["id"] == r1.source["id"]
    # a legacy upload row (name:size key, no fingerprint) is found by the legacy key and learns its fingerprint
    f = tmp_path / "doc.txt"; f.write_text("hello world " * 100)
    legacy = db.upsert_source(platform="document", external_id=f"doc:doc.txt:{f.stat().st_size}", url="file://doc.txt", title="doc", status="ready")
    cand = identity.upload_candidate("document", f, "doc.txt", "doc", [], "doc")
    r2 = identity.resolve_or_create_source(cand, a)
    assert not r2.created and r2.source["id"] == legacy["id"] and r2.source["content_fingerprint"] == cand.fingerprint
    # the same bytes under a different name are the same source (fingerprint beats name)
    g = tmp_path / "renamed.txt"; g.write_bytes(f.read_bytes())
    r3 = identity.resolve_or_create_source(identity.upload_candidate("document", g, "renamed.txt", None, [], "doc"), a)
    assert not r3.created and r3.source["id"] == legacy["id"]
    # different bytes with the same name and size are DIFFERENT sources (the old key collided)
    h = tmp_path / "doc2.txt"; h.write_text("HELLO WORLD " * 100)
    r4 = identity.resolve_or_create_source(identity.upload_candidate("document", h, "doc.txt", None, [], "doc"), a)
    assert r4.created and r4.source["id"] != legacy["id"]
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3


def test_upsert_without_identity_is_refused():
    with pytest.raises(ValueError):
        db.upsert_source(platform="media", external_id=None, url="https://x.example/y", status="pending")


# ------------------------------------------------------------------ the Feature Gate: many pathways, one acquisition

def test_same_video_by_three_url_forms_into_two_projects_is_one_acquisition(tmp_path, monkeypatch):
    """youtu.be/X, watch?v=X&si=…, shorts/X across two projects → 1 source row, 2 project links, 1 real ingestion."""
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    fx = urls[0]
    a, b = _projects()
    ingested = {"n": 0}
    real = ingest.ingest_source
    def counting(sid, **kw):
        ingested["n"] += 1
        return real(sid, **kw)
    monkeypatch.setattr(ingest, "ingest_source", counting)
    r_a = ingest.ingest_url(fx, project_id=a)
    assert r_a["identity"] == identity.NEW and db.get_source(r_a["source_id"])["status"] == "ready"
    r_b = ingest.ingest_url(fx, project_id=b)
    assert r_b["identity"] == identity.EXISTING_READY and r_b["already_ingested"] and r_b["source_id"] == r_a["source_id"]
    r_a2 = ingest.ingest_url(fx, project_id=a)
    assert r_a2["identity"] == identity.ALREADY_IN_PROJECT and r_a2["already_ingested"]
    assert ingested["n"] == 1 and db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    assert _links(r_a["source_id"]) == {a, b}
    # project-relative analysis was queued once per project, never twice for the same project
    sf = _jobs_of("suggest_findings")
    assert {j["payload"]["project_id"] for j in sf} == {a, b} and len(sf) == 2
    # the canonical forms of a real YouTube id resolve to the same external id
    from neurosearch.media import canonical_url
    forms = ["https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=abc", "https://www.youtube.com/shorts/dQw4w9WgXcQ"]
    assert len({ingest._external_id_from_url(canonical_url(u), "youtube") for u in forms}) == 1
    assert len({db.dedupe_key_for("ingest_url", {"url": canonical_url(u)}) for u in forms}) == 1        # one unit of work


def test_pending_acquisition_is_shared_not_repeated(tmp_path, monkeypatch):
    """Project B adds a video that project A's job is still ingesting: B attaches to the same work, no second ingest."""
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    a, b = _projects()
    job_a = db.create_job("ingest_url", {"url": urls[0], "project_id": a})
    # simulate A's job having resolved + claimed the source and being mid-flight
    res = identity.resolve_or_create_source(identity.Candidate(platform="fixture", external_id=urls[0], url=urls[0]), a)
    db.set_job_payload(job_a["id"], {**job_a["payload"], "source_id": res.source["id"]})
    db.connect().execute("UPDATE jobs SET status='running', lease_until=? WHERE id=?", (db.now() + 600, job_a["id"])); db.connect().commit()
    calls = {"n": 0}
    monkeypatch.setattr(ingest, "ingest_source", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})
    r_b = ingest.ingest_url(urls[0], project_id=b)
    assert r_b["identity"] == identity.EXISTING_PENDING and r_b["already_pending"] and calls["n"] == 0
    assert db.get_source(res.source["id"])["status"] == "pending" and _links(res.source["id"]) == {a, b}
    # …and a stale pending row with NO live job is resumed (the row is not stuck forever)
    db.connect().execute("UPDATE jobs SET status='failed' WHERE id=?", (job_a["id"],)); db.connect().commit()
    c = db.create_project("P2", "x")["id"]
    r_c = ingest.ingest_url(urls[0], project_id=c)
    assert calls["n"] == 1 and r_c["identity"] == identity.EXISTING_PENDING


def test_failed_source_is_attached_but_only_retried_by_the_project_that_has_it(tmp_path, monkeypatch):
    urls = crashkit.write_fixtures(tmp_path / "fx", 1, captions_every=1)
    a, b = _projects()
    res = identity.resolve_or_create_source(identity.Candidate(platform="fixture", external_id=urls[0], url=urls[0]), a)
    db.set_source_status(res.source["id"], "failed", "network down")
    calls = {"n": 0}
    monkeypatch.setattr(ingest, "ingest_source", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})
    r_b = ingest.ingest_url(urls[0], project_id=b)                                    # another project: attach + report, no spend
    assert r_b["identity"] == identity.EXISTING_FAILED and r_b["failed"] and calls["n"] == 0 and _links(res.source["id"]) == {a, b}
    r_a = ingest.ingest_url(urls[0], project_id=a)                                    # same project asks again: that IS a retry
    assert calls["n"] == 1 and r_a["identity"] == identity.ALREADY_IN_PROJECT
    r_f = ingest.ingest_url(urls[0], project_id=b, force=True)                        # explicit force retries from anywhere
    assert calls["n"] == 2


def test_uploads_reuse_by_content_not_name_and_never_reparse_a_ready_document(tmp_path, monkeypatch):
    a, b = _projects()
    f = tmp_path / "playbook.txt"; f.write_text("The hands-off playbook: hire a GM in month three. " * 40)
    r1 = ingest.ingest_local_file(f, None, [], a, original_name="playbook.txt")
    sid = r1["source_id"]
    assert db.get_source(sid)["status"] == "ready" and db.get_chunks(sid)
    from neurosearch import documents
    monkeypatch.setattr(documents, "extract_pages", lambda p: (_ for _ in ()).throw(AssertionError("must not re-extract")))
    g = tmp_path / "renamed copy.txt"; g.write_bytes(f.read_bytes())
    r2 = ingest.ingest_local_file(g, None, [], b, original_name="renamed copy.txt")
    assert r2["source_id"] == sid and r2["already_ingested"] and r2["identity"] == identity.EXISTING_READY
    assert _links(sid) == {a, b} and db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    assert len([j for j in _jobs_of("suggest_findings") if j["payload"]["project_id"] == b]) == 1            # B gets its own analysis
    # pasted text: the identity is stable (content hash), so the same paste twice is one source
    t1 = ingest.ingest_text("note", "seller note standby for two years " * 30, project_id=a)
    t2 = ingest.ingest_text("note", "seller note standby for two years " * 30, project_id=b)
    assert t1["source_id"] == t2["source_id"] and t2["already_ingested"]


def test_transcript_import_attaches_even_with_a_collection(tmp_path):
    a, = _projects(1)
    payload = {"platform": "youtube", "external_id": "importedvid1", "url": "https://www.youtube.com/watch?v=importedvid1", "title": "Imported",
               "duration": 60.0, "transcript_kind": "captions", "segments": [{"start": 0, "end": 6, "text": "equity injection matters"}] * 5, "chapters": []}
    r = ingest.store_transcript(payload, project_id=a, collection={"kind": "playlist", "external_id": "PL1", "url": "https://www.youtube.com/playlist?list=PL1", "title": "PL"})
    assert r["identity"] == identity.NEW and _links(r["source_id"]) == {a}                        # was: collection only, source never attached
    r2 = ingest.store_transcript(payload, project_id=a)
    assert r2["already_ingested"] and r2["identity"] == identity.ALREADY_IN_PROJECT


def test_channel_listing_never_resets_a_source_another_project_is_ingesting(tmp_path, monkeypatch):
    """A playlist review in project B lists a video that project A is ingesting: the row stays pending (A's work),
    B's review counts it as 'already in your library', and nothing is re-proposed or re-queued."""
    from neurosearch import media
    a, b = _projects()
    entries = [{"id": f"vid{i:08d}", "url": f"https://www.youtube.com/watch?v=vid{i:08d}", "title": f"Video {i}", "duration": 100.0} for i in range(5)]
    monkeypatch.setattr(media, "classify_url", lambda u: "playlist")
    monkeypatch.setattr(media, "enumerate_entries", lambda u: ({"id": "PLX", "url": u, "title": "List"}, entries))
    # A is ingesting vid0 (pending) and already has vid1 ready; B has vid2 already
    p0 = identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="vid00000000", url=entries[0]["url"]), a)
    p1 = identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="vid00000001", url=entries[1]["url"]), a)
    db.set_source_status(p1.source["id"], "ready")
    p2 = identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="vid00000002", url=entries[2]["url"]), b)
    db.set_source_status(p2.source["id"], "ready")
    r = ingest.ingest_url("https://www.youtube.com/playlist?list=PLX", project_id=b, review=True)
    assert r["counts"] == {"already_in_project": 1, "already_in_library": 2, "new": 2} and r["found"] == 5
    assert db.get_source(p0.source["id"])["status"] == "pending"                                   # NOT flipped to proposed
    assert db.get_source(p1.source["id"])["status"] == "ready"
    assert r["proposed"] == 2 and r["already_ingested"] == 3
    meta = db.review_meta(r["collection_id"])
    assert meta["counts"]["new"] == 2
    assert db.connect().execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 5


def test_attach_existing_from_library_queues_analysis_once_and_is_idempotent():
    a, b = _projects()
    res = identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="libvid00001", url="https://www.youtube.com/watch?v=libvid00001"), a)
    db.set_source_status(res.source["id"], "ready")
    r1 = identity.attach_existing(b, res.source["id"])
    r2 = identity.attach_existing(b, res.source["id"])
    assert r1.state == identity.EXISTING_READY and r2.state == identity.ALREADY_IN_PROJECT
    assert len([j for j in _jobs_of("suggest_findings") if j["payload"]["project_id"] == b]) == 1
    with pytest.raises(KeyError):
        identity.attach_existing(b, "nope")


def test_health_reports_the_library_and_migration_keeps_old_rows():
    a, b = _projects()
    res = identity.resolve_or_create_source(identity.Candidate(platform="youtube", external_id="hv1", url="u"), a)
    db.set_source_status(res.source["id"], "ready")
    identity.attach_existing(b, res.source["id"])
    h = db.health()["library"]
    assert h["sources"] == 1 and h["shared_by_projects"] == 1 and h["acquisitions_avoided"] == 1 and h["duplicate_fingerprints"] == 0
    cols = {r["name"] for r in db.connect().execute("PRAGMA table_info(sources)").fetchall()}
    assert {"canonical_url", "content_fingerprint"} <= cols
    assert db.connect().execute("SELECT COUNT(*) FROM source_relations").fetchone()[0] == 0          # the lineage seam exists, empty
