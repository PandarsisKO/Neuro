"""P11 HTTP surfaces (docs/P11-EXECUTION-PLAN-2026-09-22.md §3).

Two routers, two auth regimes, never mixed:
  * `/api/access/*`  — LOCAL OWNER administration (credentials, grants, classification). Behind the legacy app token
                       (api.py `require_auth`), i.e. Kyle on his own machine. External credentials are refused here.
  * `/api/ext/v1/*`  — the EXTERNAL client contract (EA-3+). Behind an external credential only (`access.authenticate`).
                       The legacy app token is refused there.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import access


def _http(e: access.AccessError) -> HTTPException:
    return HTTPException(e.status, {"code": e.code, "message": e.message})


class ActorIn(BaseModel):
    name: str


class DisableIn(BaseModel):
    disabled: bool = True


class ClientIn(BaseModel):
    label: str
    transport: str = "local"


class CredentialIn(BaseModel):
    actor_id: str
    client_id: str
    expires_at: float | None = None


class RevokeIn(BaseModel):
    reason: str | None = None


class RotateIn(BaseModel):
    overlap_s: float = 0.0


class GrantIn(BaseModel):
    project_id: str
    actor_id: str
    role: str
    classes: list[str] | None = None      # omitted → standard only (Kyle, 2026-09-22)


class GrantClassesIn(BaseModel):
    project_id: str
    actor_id: str
    classes: list[str]


class ClassIn(BaseModel):
    disclosure_class: str
    reason: str | None = None


def admin_router(require_auth: Callable[..., None]) -> APIRouter:
    r = APIRouter(prefix="/api/access", dependencies=[Depends(require_auth)])

    def guard(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except access.AccessError as e:
            raise _http(e)

    @r.get("")
    def overview() -> dict[str, Any]:
        return {"actors": access.list_actors(), "clients": access.list_clients(), "credentials": access.list_credentials(),
                "grants": access.list_grants(), "default_grant_classes": list(access.DEFAULT_GRANT_CLASSES)}

    @r.post("/actors")
    def create_actor(body: ActorIn) -> dict[str, Any]:
        return guard(lambda: access.create_actor(body.name))

    @r.post("/actors/{actor_id}/disable")
    def disable_actor(actor_id: str, body: DisableIn) -> dict[str, Any] | None:
        return guard(lambda: access.set_actor_disabled(actor_id, body.disabled))

    @r.post("/clients")
    def create_client(body: ClientIn) -> dict[str, Any]:
        return guard(lambda: access.create_client(body.label, transport=body.transport))

    @r.post("/credentials")
    def issue(body: CredentialIn) -> dict[str, Any]:
        row, secret = guard(lambda: access.issue_credential(body.actor_id, body.client_id, expires_at=body.expires_at))
        return {"credential": row, "secret": secret, "note": "shown once — Neuro keeps only a hash"}

    @r.post("/credentials/{credential_id}/revoke")
    def revoke(credential_id: str, body: RevokeIn) -> dict[str, Any] | None:
        out = access.revoke_credential(credential_id, reason=body.reason)
        if not out:
            raise HTTPException(404, "no such credential")
        return out

    @r.post("/credentials/{credential_id}/rotate")
    def rotate(credential_id: str, body: RotateIn) -> dict[str, Any]:
        row, secret = guard(lambda: access.rotate_credential(credential_id, overlap_s=body.overlap_s))
        return {"credential": row, "secret": secret, "note": "shown once — Neuro keeps only a hash"}

    @r.put("/grants")
    def put_grant(body: GrantIn) -> dict[str, Any]:
        return guard(lambda: access.grant(body.project_id, body.actor_id, body.role, classes=body.classes))

    @r.put("/grants/classes")
    def put_grant_classes(body: GrantClassesIn) -> dict[str, Any]:
        return guard(lambda: access.set_grant_classes(body.project_id, body.actor_id, body.classes))

    @r.delete("/grants")
    def delete_grant(project_id: str, actor_id: str) -> dict[str, Any] | None:
        return access.revoke_grant(project_id, actor_id)

    @r.post("/sources/{source_id}/class")
    def source_class(source_id: str, body: ClassIn) -> dict[str, Any]:
        return guard(lambda: access.set_source_class(source_id, body.disclosure_class, reason=body.reason))

    @r.post("/facts/{fact_id}/class")
    def fact_class(fact_id: int, body: ClassIn) -> dict[str, Any]:
        return guard(lambda: access.set_fact_class(fact_id, body.disclosure_class, reason=body.reason))

    @r.get("/backfill")
    def backfill_preview() -> dict[str, Any]:
        return access.backfill_classes(apply=False)

    @r.post("/backfill")
    def backfill_apply() -> dict[str, Any]:
        return access.backfill_classes(apply=True)

    return r
