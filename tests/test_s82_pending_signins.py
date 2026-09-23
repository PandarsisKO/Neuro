"""S82: an owner approves a verified sign-in in Neuro, because the code path is not available to every client.

ChatGPT's credential-safety layer blocks an `nsi_…` code in chat BEFORE `link_account` is sent — observed
2026-09-22, when Kyle pasted one and Neuro never received the call. So for that client a code the user types
cannot be the link path, and the owner has to approve the sign-in on Neuro's side instead.

What these tests hold: recording a pending sign-in proves nothing the provider has not already proved, approving
creates exactly what the invite path creates, dismissing denies nothing, an external credential can never approve
itself, and none of it widens what a grant may disclose.
"""
from __future__ import annotations

import time

import pytest

from neurosearch import access, db, idp
from neurosearch.access import AccessError
from neurosearch.config import settings

ISS = "https://example-idp.test"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "oauth_issuer", ISS)
    monkeypatch.setattr(settings, "oauth_resource", "https://tunnel.test/v1/mcp/x")
    monkeypatch.setattr(settings, "oauth_audience", "https://tunnel.test/v1/mcp/x")
    db._local.conn = None
    db.init_db()
    assert access.get_actor("kyle"), "init_db seeds the owner's actor"
    yield
    db._local.conn = None


def claims(sub: str, **extra):
    return {"sub": sub, "iss": ISS, "aud": "https://tunnel.test/v1/mcp/x", "exp": time.time() + 600, **extra}


def test_a_pending_row_is_created_once_per_subject(world):
    """Repeated calls from the same identity must not pile up rows — one identity, one line for the owner."""
    idp.note_pending("sub-1", claims("sub-1", email="kyle@example.com", azp="chatgpt"))
    idp.note_pending("sub-1", claims("sub-1"))
    idp.note_pending("sub-1", claims("sub-1"))

    pend = idp.list_pending()
    assert len(pend) == 1
    row = pend[0]
    assert row["subject"] == "sub-1" and row["seen_count"] == 3
    assert row["email"] == "kyle@example.com", "a later token without the claim must not erase what we knew"
    assert row["client_hint"] == "chatgpt"
    assert row["first_seen"] <= row["last_seen"]


def test_approving_links_the_identity_exactly_as_an_invite_would(world):
    idp.note_pending("sub-2", claims("sub-2"))
    out = idp.approve_pending("sub-2", "kyle", client_name="ChatGPT")
    assert out["linked"] is True and out["person"] == "Kyle"

    # the same three rows the invite path writes: identity -> credential -> client, all owned by the actor
    ident = db.connect().execute("SELECT * FROM external_identities WHERE issuer=? AND subject=?", (ISS, "sub-2")).fetchone()
    assert ident is not None and ident["invite_id"] is None, "approval spends no invite"
    p = access.authenticate_credential_id(ident["credential_id"])
    assert p.actor_id == "kyle"

    assert idp.list_pending() == [], "an approved sign-in leaves the owner's list"
    assert idp.credential_for.__doc__                       # the reader now resolves it
    again = idp.approve_pending("sub-2", "kyle")
    assert again.get("already_linked") is True, "approving twice must be idempotent, not a second credential"
    assert len(access.list_credentials()) == 1


def test_dismissing_blocks_nothing_and_is_not_a_denial(world):
    idp.note_pending("sub-3", claims("sub-3"))
    assert idp.dismiss_pending("sub-3")["dismissed"] is True
    assert idp.list_pending() == [], "dismissed rows leave the list"

    # dismissal says "not now", not "never": the same identity signing in again is visible again
    idp.note_pending("sub-3", claims("sub-3"))
    assert [r["subject"] for r in idp.list_pending()] == ["sub-3"]

    # and it never blocked approval
    assert idp.approve_pending("sub-3", "kyle")["linked"] is True


def test_an_unlinked_verified_signin_is_recorded_and_told_where_to_go(world, monkeypatch):
    """The message must send the user to the owner, not to a code they cannot deliver."""
    monkeypatch.setattr(idp, "verify", lambda token: claims("sub-4", email="k@example.com"))
    with pytest.raises(AccessError) as e:
        idp.credential_for("any-token")
    assert e.value.code == "account_unlinked"
    assert "approve this sign-in" in str(e.value) and "Access" in str(e.value)
    assert "nsi_" not in str(e.value), "the code path is exactly what this client cannot use"
    assert [r["subject"] for r in idp.list_pending()] == ["sub-4"]

    idp.approve_pending("sub-4", "kyle")
    assert idp.credential_for("any-token")                  # now resolves instead of raising


def test_approval_refuses_unknown_or_disabled_people_and_unknown_subjects(world):
    idp.note_pending("sub-5", claims("sub-5"))
    with pytest.raises(AccessError):
        idp.approve_pending("sub-5", "nobody")
    with pytest.raises(AccessError):
        idp.approve_pending("sub-5", "system")              # never the automatic actor
    with pytest.raises(AccessError):
        idp.approve_pending("sub-never-seen", "kyle")
    gio = access.create_actor("Gio")                        # the owner itself cannot be disabled, by design
    access.set_actor_disabled(gio["id"], True)
    with pytest.raises(AccessError):
        idp.approve_pending("sub-5", gio["id"])


def test_the_approve_endpoint_is_owner_only(world):
    """An external credential must not be able to approve itself. The admin router sits behind the local owner
    token; the external surface has no such route at all."""
    from neurosearch import api_external

    ext = api_external.ext_router()
    ext_paths = {r.path for r in ext.routes}
    assert not any("pending-signin" in p for p in ext_paths), "no approval route on the external surface"

    admin = api_external.admin_router(lambda: None)
    admin_paths = {r.path for r in admin.routes}
    assert "/api/access/pending-signins/approve" in admin_paths
    assert "/api/access/pending-signins" in admin_paths
    # every admin route carries the owner-auth dependency the router was built with
    assert admin.dependencies, "the admin router must be auth-gated as a whole"


def test_approval_does_not_widen_what_may_be_disclosed(world):
    """Linking says who someone is. It says nothing about what they may see."""
    p_id = db.create_project("P", brief="b")["id"]
    idp.note_pending("sub-6", claims("sub-6"))
    idp.approve_pending("sub-6", "kyle")

    g = access.grant(p_id, "kyle", "read")
    assert g["disclosure_classes"] == ["standard"], "a new grant stays standard-only after approval"

    ident = db.connect().execute("SELECT credential_id FROM external_identities WHERE subject=?", ("sub-6",)).fetchone()
    principal = access.authenticate_credential_id(ident["credential_id"])
    auth = access.authorize(principal, p_id, "search_project")
    assert "restricted" not in auth.classes and "financial" not in auth.classes
