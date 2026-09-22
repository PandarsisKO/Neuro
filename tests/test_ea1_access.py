"""P11 EA-1 — external principals, project ACL, disclosure-at-assembly (EXTERNAL-AI-ACCESS-MISSION.md §40–§43, §61;
docs/P11-EXECUTION-PLAN-2026-09-22.md §4 and §10 rows 1–3).

The gate: project isolation, read-only enforcement, IDOR, revocation, legacy auth preserved, disclosure leakage
through derived objects, and the §43 backfill."""
from __future__ import annotations

import logging
import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
import pytest

from neurosearch import access, claims, db, logctx
from neurosearch.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    d = tmp_path / "data"; d.mkdir()
    monkeypatch.setattr(settings, "data_dir", d)
    db._local.conn = None
    db.init_db()
    access._rate.clear()
    yield
    db._local.conn = None


def _src(platform, ext, **kw):
    return db.upsert_source(platform=platform, external_id=ext, url=kw.pop("url", f"https://example.com/{ext}"),
                            title=ext, status="ready", **kw)["id"]


def _people():
    """Kyle and Gio, each with their own ChatGPT credential; a shared project and a private one."""
    shared = db.create_project("Business acquisition", "buy a business")["id"]
    private = db.create_project("Kyle private", "mine")["id"]
    gio = access.create_actor("Gio", actor_id="gio")
    c_gio = access.create_client("Gio's ChatGPT", transport="tunnel")
    c_kyle = access.create_client("Kyle's ChatGPT", transport="tunnel")
    _, s_gio = access.issue_credential(gio["id"], c_gio["id"])
    _, s_kyle = access.issue_credential("kyle", c_kyle["id"])
    access.grant(shared, "gio", "contribute")
    access.grant(shared, "kyle", "owner", classes=["standard", "correspondence", "financial"])
    access.grant(private, "kyle", "owner")
    return shared, private, s_gio, s_kyle


# ------------------------------------------------------------------ identity & ACL

def test_seeded_actors_exist_and_system_cannot_be_granted():
    ids = {a["id"]: a["kind"] for a in access.list_actors()}
    assert ids == {"kyle": "person", "system": "system"}
    p = db.create_project("p")["id"]
    with pytest.raises(access.AccessError):
        access.grant(p, "system", "read")


def test_two_people_two_credentials_distinct_principals():
    shared, private, s_gio, s_kyle = _people()
    g, k = access.authenticate(s_gio), access.authenticate(s_kyle)
    assert (g.actor_id, k.actor_id) == ("gio", "kyle")
    assert g.client_id != k.client_id and g.credential_id != k.credential_id
    assert [p["id"] for p in access.granted_projects(g)] == [shared]
    assert {p["id"] for p in access.granted_projects(k)} == {shared, private}


def test_ungranted_and_nonexistent_projects_are_the_same_answer():
    shared, private, s_gio, _ = _people()
    g = access.authenticate(s_gio)
    for pid in (private, "no-such-project", "", None):
        with pytest.raises(access.AccessError) as e:
            access.authorize(g, pid, "open_project")
        assert e.value.code == "project_unauthorized" and e.value.status == 404


def test_read_only_grant_cannot_write():
    shared, _, s_gio, _ = _people()
    access.grant(shared, "gio", "read")
    g = access.authenticate(s_gio)
    assert access.authorize(g, shared, "consult_project").role == "read"
    for op in ("create_intake", "finalize_intake", "sync_project_state", "add_processed_material"):
        with pytest.raises(access.AccessError) as e:
            access.authorize(g, shared, op)
        assert e.value.code == "forbidden" and e.value.status == 403


def test_unknown_operation_is_refused_for_every_role():
    shared, _, s_gio, _ = _people()
    with pytest.raises(access.AccessError):
        access.authorize(access.authenticate(s_gio), shared, "delete_project")


def test_revoked_grant_stops_access_immediately():
    shared, _, s_gio, _ = _people()
    g = access.authenticate(s_gio)
    access.revoke_grant(shared, "gio")
    with pytest.raises(access.AccessError) as e:
        access.authorize(g, shared, "open_project")
    assert e.value.code == "project_unauthorized"


def test_revocation_rotation_expiry_and_disabled_person():
    shared, _, s_gio, _ = _people()
    cred = access.authenticate(s_gio).credential_id
    new, s_new = access.rotate_credential(cred)
    assert new["rotated_from"] == cred
    with pytest.raises(access.AccessError) as e:
        access.authenticate(s_gio)
    assert e.value.code == "auth_revoked"
    assert access.authenticate(s_new).actor_id == "gio"
    # expiry
    row, s_exp = access.issue_credential("gio", new["client_id"], expires_at=1.0)
    with pytest.raises(access.AccessError) as e:
        access.authenticate(s_exp)
    assert e.value.code == "auth_invalid"
    # disabling the person revokes every credential they hold
    access.set_actor_disabled("gio", True)
    with pytest.raises(access.AccessError) as e:
        access.authenticate(s_new)
    assert e.value.code == "auth_revoked"
    with pytest.raises(access.AccessError):
        access.set_actor_disabled("kyle", True)


def test_rotation_overlap_keeps_old_secret_until_the_overlap_ends():
    _, _, s_gio, _ = _people()
    cred = access.authenticate(s_gio).credential_id
    access.rotate_credential(cred, overlap_s=3600)
    assert access.authenticate(s_gio).actor_id == "gio"


def test_malformed_unknown_and_legacy_tokens_are_invalid_here():
    _, _, s_gio, _ = _people()
    for bad in (None, "", "t0k", "nsx_short", s_gio[:-1] + ("A" if s_gio[-1] != "A" else "B"), "nsx_" + "x" * 40):
        with pytest.raises(access.AccessError) as e:
            access.authenticate(bad)
        assert e.value.code == "auth_invalid"


def test_secret_is_never_stored_and_listings_carry_only_the_prefix():
    _, _, s_gio, _ = _people()
    rows = db.connect().execute("SELECT * FROM external_credentials").fetchall()
    for r in rows:
        assert s_gio not in " ".join(str(v) for v in dict(r).values())
    listed = access.list_credentials()
    assert all("token_hash" not in c for c in listed)
    assert s_gio[:access.PREFIX_LEN] in {c["token_prefix"] for c in listed}


def test_rate_limit_per_credential():
    _, _, s_gio, s_kyle = _people()
    for _ in range(access.RATE_PER_MIN):
        access.authenticate(s_gio)
    with pytest.raises(access.AccessError) as e:
        access.authenticate(s_gio)
    assert e.value.code == "rate_limited"
    assert access.authenticate(s_kyle).actor_id == "kyle"      # another credential is unaffected


def test_log_redaction_keeps_only_the_prefix():
    secret = "nsx_" + "Q" * 43
    out = logctx.redact(f"calling with {secret} now")
    assert secret not in out and "nsx_QQQQQQQQ…" in out


# ------------------------------------------------------------------ HTTP: the two auth regimes never mix

def test_admin_routes_need_the_local_token_and_refuse_external_credentials(client):
    H = {"Authorization": "Bearer t0k"}
    assert client.get("/api/access").status_code == 401
    r = client.post("/api/access/actors", json={"name": "Gio"}, headers=H)
    assert r.status_code == 200
    aid = r.json()["id"]
    cid = client.post("/api/access/clients", json={"label": "Gio's ChatGPT"}, headers=H).json()["id"]
    issued = client.post("/api/access/credentials", json={"actor_id": aid, "client_id": cid}, headers=H).json()
    secret = issued["secret"]
    assert secret.startswith("nsx_") and "token_hash" not in issued["credential"]
    ext = {"Authorization": f"Bearer {secret}"}
    assert client.get("/api/access", headers=ext).status_code == 401          # an external credential is not the owner
    assert client.get("/api/projects", headers=ext).status_code == 401        # nor a key to the legacy API
    pid = client.post("/api/projects", json={"name": "Shared"}, headers=H).json()["id"]
    g = client.put("/api/access/grants", json={"project_id": pid, "actor_id": aid, "role": "read"}, headers=H).json()
    assert g["disclosure_classes"] == ["standard"]                             # Kyle's ruling: standard-only by default
    bad = client.put("/api/access/grants/classes", json={"project_id": pid, "actor_id": aid, "classes": ["secret"]}, headers=H)
    assert bad.status_code == 422
    listing = client.get("/api/access", headers=H).json()
    assert secret not in str(listing)


# ------------------------------------------------------------------ disclosure classes (§41–§43)

def test_effective_class_rules():
    ids = {
        "yt_public": _src("youtube", "yt1"),
        "yt_members": _src("youtube", "yt2", access_gate="members_only"),
        "podcast": _src("podcast", "pc1"),
        "instagram": _src("instagram", "ig1"),
        "upload": _src("document", "doc1"),
        "manual": _src("manual", "m1"),
        "web_unknown": _src("web", "w1"),
        "web_anon": _src("web", "w2"),
        "web_browser": _src("web", "w3"),
    }
    db.set_acquisition_provenance(ids["web_anon"], "anonymous")
    db.set_acquisition_provenance(ids["web_browser"], "anonymous")
    db.set_acquisition_provenance(ids["web_browser"], "browser_private")     # more private wins
    db.set_acquisition_provenance(ids["web_browser"], "anonymous")           # and never goes back
    cap = _src("youtube", "yt3")
    with db.tx() as conn:
        conn.execute("INSERT INTO source_captures (id, source_id, capture_url, captured_at, capture_mode, created_at, updated_at) "
                     "VALUES ('c1', ?, 'https://x', 0, 'full_page', 0, 0)", (cap,))
    cls = access.source_classes([*ids.values(), cap, "gone"])
    assert cls[ids["yt_public"]] == cls[ids["podcast"]] == cls[ids["web_anon"]] == "standard"
    for k in ("yt_members", "instagram", "upload", "manual", "web_unknown", "web_browser"):
        assert cls[ids[k]] == "restricted", k
    assert cls[cap] == "restricted" and cls["gone"] == "restricted"


def test_allowed_source_ids_is_decided_before_retrieval():
    p = db.create_project("p")["id"]
    pub, corr, fin = _src("youtube", "a"), _src("manual", "b"), _src("manual", "c")
    db.add_project_sources(p, [pub, corr, fin])
    access.set_source_class(corr, "correspondence")
    access.set_source_class(fin, "financial")
    assert access.allowed_source_ids(p, ["standard"]) == [pub]
    assert set(access.allowed_source_ids(p, ["standard", "correspondence"])) == {pub, corr}
    assert access.allowed_source_ids(p, []) == []


def test_derived_floor_is_the_union_of_everything_it_rests_on():
    """Granting financial does not unlock a Claim that also rests on tax or restricted material (Kyle's ruling 3)."""
    p = db.create_project("p")["id"]
    fin, tax, pub = _src("manual", "f"), _src("manual", "t"), _src("youtube", "y")
    access.set_source_class(fin, "financial"); access.set_source_class(tax, "tax")
    c_mixed = claims.add_claim(p, "seller note is 10%", origin="user")["id"]
    claims.add_evidence(c_mixed, fin); claims.add_evidence(c_mixed, tax)
    c_pub = claims.add_claim(p, "multiples cluster near 3x", origin="user")["id"]
    claims.add_evidence(c_pub, pub)
    c_bare = claims.add_claim(p, "no provenance at all", origin="user")["id"]
    note = db.add_project_note(p, "finding from the tax return", [], source_id=tax)["id"]
    c_note = claims.add_claim(p, "from a finding", origin="finding", origin_note_id=note)["id"]
    f = access.claim_floors([c_mixed, c_pub, c_bare, c_note])
    assert f[c_mixed] == {"financial", "tax"} and f[c_pub] == {"standard"}
    assert f[c_bare] == {"restricted"} and f[c_note] == {"tax"}
    grant = access.Authorization(access.Principal("x", "gio", "c"), p, "read", frozenset({"standard", "financial"}))
    assert grant.may_see(f[c_pub]) and not grant.may_see(f[c_mixed]) and not grant.may_see(f[c_note])
    t = access.tension_floors([{"id": "t1", "claim_id": c_pub, "related_claim_id": c_mixed}, {"id": "t2"}])
    assert t["t1"] == {"standard", "financial", "tax"} and t["t2"] == {"restricted"}


def test_claim_floor_includes_folded_in_findings():
    p = db.create_project("p")["id"]
    pub, restricted = _src("youtube", "y"), _src("instagram", "i")
    n_pub = db.add_project_note(p, "public finding", [], source_id=pub)["id"]
    n_ig = db.add_project_note(p, "instagram finding", [], source_id=restricted)["id"]
    c = claims.add_claim(p, "claim", origin="finding", origin_note_id=n_pub)["id"]
    with db.tx() as conn:
        conn.execute("INSERT INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (c, n_ig))
    assert access.claim_floors([c])[c] == {"standard", "restricted"}


def test_raise_only_rule():
    m = access.merge_declared
    assert m(None, "financial") == "financial"
    assert m("standard", "correspondence") == "correspondence"
    assert m("financial", "standard") == "financial"            # a client never lowers
    assert m("financial", "tax") == "restricted"                # incomparable → closed
    assert m("restricted", "standard") == "restricted"
    assert m("tax", None) == "tax"
    s = _src("manual", "x")
    assert access.raise_source_class(s, "standard") == "standard"
    assert access.raise_source_class(s, "financial") == "financial"
    assert access.raise_source_class(s, "standard") == "financial"


def test_owner_lowering_is_audited_and_legacy_facts_are_closed():
    s = _src("instagram", "i")
    access.set_source_class(s, "standard", reason="public post, checked")
    a = db.connect().execute("SELECT * FROM disclosure_audit WHERE object_id=?", (s,)).fetchone()
    assert a["to_class"] == "standard" and a["from_class"] == "unclassified:restricted" and a["actor_id"] == "kyle"
    p = db.create_project("p")["id"]
    f = db.add_fact(p, "decision", "stay at 10%")
    assert access.fact_class(f) == "restricted"
    access.set_fact_class(f["id"], "standard")
    assert access.fact_class(dict(db.connect().execute("SELECT * FROM project_facts WHERE id=?", (f["id"],)).fetchone())) == "standard"


def test_backfill_dry_run_writes_nothing_apply_is_idempotent_and_uncertainty_stays_closed():
    yt, ig, doc, web = _src("youtube", "y"), _src("instagram", "i"), _src("document", "d"), _src("web", "w")
    dry = access.backfill_classes()
    assert (dry["public"], dry["private"], dry["undecided"]) == (1, 2, 1)
    assert db.connect().execute("SELECT COUNT(*) FROM sources WHERE disclosure_class IS NOT NULL").fetchone()[0] == 0
    access.backfill_classes(apply=True)
    rows = {r["id"]: (r["disclosure_class"], r["disclosure_origin"]) for r in db.connect().execute("SELECT * FROM sources").fetchall()}
    assert rows[yt] == ("standard", "backfill_public")
    assert rows[ig] == rows[doc] == ("restricted", "backfill_private")
    assert rows[web] == (None, None)                                  # undecidable: left unclassified = restricted
    again = access.backfill_classes(apply=True)
    assert (again["public"], again["private"], again["undecided"]) == (0, 0, 1)
    assert access.source_classes([web])[web] == "restricted"


def test_webpage_ingest_records_provenance(monkeypatch):
    from neurosearch import ingest, webpage
    monkeypatch.setattr(ingest, "_embed_ready", lambda sid: 0)
    html = "<html><head><title>T</title></head><body><p>" + "Some article text. " * 40 + "</p></body></html>"
    sent = ingest.ingest_webpage("https://example.com/private-page", html=html)
    assert access.source_classes([sent["source_id"]])[sent["source_id"]] == "restricted"
    monkeypatch.setattr(webpage, "fetch", lambda url, timeout=60.0: (url, "text/html", html.encode()))
    fetched = ingest.ingest_webpage("https://example.com/public-page")
    row = db.connect().execute("SELECT acquisition_provenance FROM sources WHERE id=?", (fetched["source_id"],)).fetchone()
    assert row["acquisition_provenance"] == "anonymous"
    assert access.source_classes([fetched["source_id"]])[fetched["source_id"]] == "standard"


def test_contracts_are_valid_json_schema():
    from neurosearch import external_schemas as xs
    xs.check_installation()
    ok = {"material_type": "pdf", "title": "Updated financials", "producer": "Gio's ChatGPT", "extraction_method": "pdf_text",
          "units": [{"locator": "p. 1", "text": "Revenue 2025: $1.2M"}], "client_declared_class": "financial"}
    xs.check("external.material.v1", ok)
    with pytest.raises(xs.ContractError) as e:
        xs.check("external.material.v1", {**ok, "client_declared_class": "public", "units": []})
    assert len(e.value.errors) >= 2
    xs.check("external.sync.v1", {"project_id": "p", "base_revision": 3, "changes": [
        {"op": "record", "kind": "decision", "content": "Stay at 10%", "explicitness": "explicit", "client_request_id": "req-00000001"}]})
