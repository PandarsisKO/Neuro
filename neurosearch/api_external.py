"""P11 HTTP surfaces (docs/P11-EXECUTION-PLAN-2026-09-22.md §3).

Two routers, two auth regimes, never mixed:
  * `/api/access/*`  — LOCAL OWNER administration (credentials, grants, classification). Behind the legacy app token
                       (api.py `require_auth`), i.e. Kyle on his own machine. External credentials are refused here.
  * `/api/ext/v1/*`  — the EXTERNAL client contract (EA-3+). Behind an external credential only (`access.authenticate`).
                       The legacy app token is refused there.
"""
from __future__ import annotations

from typing import Any, Callable

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import access, external


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

    invite_routes(r)

    @r.get("/client-health")
    def external_health() -> dict[str, Any]:
        return {"clients": access.health()}

    @r.get("/backfill")
    def backfill_preview() -> dict[str, Any]:
        return access.backfill_classes(apply=False)

    @r.post("/backfill")
    def backfill_apply() -> dict[str, Any]:
        return access.backfill_classes(apply=True)

    return r


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def ext_router() -> APIRouter:
    """`/api/ext/v1/<op>` — one POST per operation, JSON in, the §39 envelope out. External credential only."""
    r = APIRouter(prefix="/api/ext/v1")

    @r.post("/intakes/{intake_id}/artifacts")
    async def ext_upload(intake_id: str, request: Request) -> JSONResponse:
        """§55 multipart transport: the original file's bytes. Form fields: project_id, file, item_id?,
        client_declared_class?, item_request_id?."""
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            return JSONResponse({"schema_version": "1", "error": {"code": "invalid", "message": "multipart field 'file' is required"}}, status_code=422)
        data = await f.read()
        args = {"project_id": form.get("project_id"), "intake_id": intake_id, "item_id": form.get("item_id") or None,
                "client_declared_class": form.get("client_declared_class") or None, "item_request_id": form.get("item_request_id") or None,
                "artifact_ref": {"kind": "multipart", "filename": getattr(f, "filename", None) or "artifact"},
                "_upload": (getattr(f, "filename", None) or "artifact", data, getattr(f, "content_type", None))}
        secret = _bearer(request)
        try:
            out = await anyio.to_thread.run_sync(lambda: external.call(secret, "attach_artifact", args))
        except external.ExternalError as e:
            return JSONResponse(e.body(), status_code=e.status, headers={"WWW-Authenticate": "Bearer"} if e.status == 401 else None)
        return JSONResponse(out)

    @r.post("/{op}")
    async def ext_call(op: str, request: Request) -> JSONResponse:
        try:
            body = await request.json() if (await request.body()) else {}
        except ValueError:
            return JSONResponse({"schema_version": "1", "error": {"code": "invalid", "message": "body is not JSON"}}, status_code=422)
        if not isinstance(body, dict):
            return JSONResponse({"schema_version": "1", "error": {"code": "invalid", "message": "body must be a JSON object"}}, status_code=422)
        secret = _bearer(request)
        try:
            out = await anyio.to_thread.run_sync(lambda: external.call(secret, op, body))
        except external.ExternalError as e:
            headers = {"WWW-Authenticate": "Bearer"} if e.status == 401 else None
            return JSONResponse(e.body(), status_code=e.status, headers=headers)
        return JSONResponse(out)

    return r


def inbox_router(require_auth: Callable[..., None]) -> APIRouter:
    """The local owner's Project Inbox (§8): a view over external intakes, needs_review first."""
    r = APIRouter(prefix="/api/projects", dependencies=[Depends(require_auth)])

    @r.get("/{project_id}/inbox")
    def project_inbox(project_id: str, limit: int = 50) -> dict[str, Any]:
        from . import intake
        return {"intakes": intake.inbox(project_id, limit=max(1, min(limit, 200)))}

    return r


class InviteIn(BaseModel):
    actor_id: str
    label: str | None = None


def invite_routes(r: APIRouter) -> None:
    from . import oauth

    @r.post("/invites")
    def create_invite(body: InviteIn) -> dict[str, Any]:
        try:
            row, code = oauth.create_invite(body.actor_id, label=body.label)
        except access.AccessError as e:
            raise _http(e)
        return {"invite": row, "code": code, "note": "shown once; single use; expires in 7 days"}

    @r.get("/invites")
    def invites() -> list[dict[str, Any]]:
        return oauth.list_invites()

    @r.post("/invites/{invite_id}/revoke")
    def revoke_invite(invite_id: str) -> dict[str, Any]:
        oauth.revoke_invite(invite_id)
        return {"ok": True}


def oauth_router() -> APIRouter:
    """OAuth 2.1 for external AI clients (oauth.py). Public by design: every step is protected by PKCE plus the
    owner-issued invite the person types at consent; nothing here reads project data."""
    from fastapi.responses import HTMLResponse, RedirectResponse
    from . import oauth
    r = APIRouter()

    def base(request: Request) -> str:
        return oauth.base_url(str(request.base_url))

    def builtin_only() -> None:
        """With an external identity provider configured, Neuro serves NO authorization endpoints of its own."""
        from . import idp
        if idp.enabled():
            raise HTTPException(404, "authorization is handled by the configured identity provider")

    @r.get("/.well-known/oauth-protected-resource")
    @r.get("/.well-known/oauth-protected-resource/ext/mcp")
    def prm(request: Request) -> JSONResponse:
        from . import idp
        if idp.enabled():                                    # resource-server mode: point at the hosted provider
            return JSONResponse(idp.protected_resource_metadata())
        return JSONResponse(oauth.protected_resource_metadata(base(request)))

    @r.get("/.well-known/oauth-authorization-server")
    @r.get("/.well-known/openid-configuration")
    def asm(request: Request) -> JSONResponse:
        builtin_only()
        return JSONResponse(oauth.authorization_server_metadata(base(request)))

    @r.post("/oauth/register")
    async def register(request: Request) -> JSONResponse:
        builtin_only()
        try:
            meta = await request.json()
            return JSONResponse(oauth.register(meta if isinstance(meta, dict) else {}), status_code=201)
        except (ValueError, access.AccessError) as e:
            return JSONResponse({"error": "invalid_client_metadata", "error_description": getattr(e, "message", str(e))}, status_code=400)

    @r.get("/oauth/authorize")
    def authorize_page(request: Request) -> HTMLResponse:
        builtin_only()
        q = dict(request.query_params)
        try:
            c = oauth.check_authorize(q)
        except access.AccessError as e:
            return HTMLResponse(f"<p>Cannot connect: {e.message}</p>", status_code=400)
        return HTMLResponse(oauth.consent_page(q, c), headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    @r.post("/oauth/authorize")
    async def authorize_submit(request: Request) -> Any:
        builtin_only()
        form = {k: str(v) for k, v in (await request.form()).items()}
        q = {k: v for k, v in form.items() if k != "invite_code"}
        try:
            return RedirectResponse(oauth.approve(q, form.get("invite_code", "")), status_code=303)
        except access.AccessError as e:
            try:
                c = oauth.check_authorize(q)
            except access.AccessError:
                return HTMLResponse(f"<p>Cannot connect: {e.message}</p>", status_code=400)
            return HTMLResponse(oauth.consent_page(q, c, error=e.message), status_code=400,
                                headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})

    @r.post("/oauth/token")
    async def token(request: Request) -> JSONResponse:
        builtin_only()
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            return JSONResponse(oauth.token(form), headers={"Cache-Control": "no-store"})
        except access.AccessError as e:
            code = "invalid_grant" if e.code in ("auth_invalid", "auth_revoked") else ("slow_down" if e.code == "rate_limited" else "invalid_request")
            return JSONResponse({"error": code, "error_description": e.message}, status_code=400, headers={"Cache-Control": "no-store"})

    @r.post("/oauth/revoke")
    async def revoke(request: Request) -> JSONResponse:
        builtin_only()
        form = {k: str(v) for k, v in (await request.form()).items()}
        oauth.revoke_token(form.get("token", ""))
        return JSONResponse({})

    return r
