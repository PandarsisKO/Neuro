"""Local Sign in with ChatGPT session and the Responses transport for the provider router."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx

from .config import settings

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
TOKEN = f"{ISSUER}/api/accounts/oauth/token"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
MODEL = "gpt-6-luna"
SUPPORTED_TASKS = frozenset(("library.profile", "findings.extract", "rank.relevance"))
MAX_REQUEST_BYTES = 160_000
MAX_MODEL_OUTPUT = 128_000
OPERATION = "chatgpt_plan:responses"
_slots = threading.BoundedSemaphore(1)


class PlanWait(RuntimeError):
    """An actionable condition that parks the existing job without consuming a retry."""
    def __init__(self, message: str, wait: float = 60.0) -> None:
        super().__init__(message)
        self.wait = wait


def model_for(task: str) -> str | None:
    if not settings.fake_ai and task in SUPPORTED_TASKS and task in settings.chatgpt_plan_tasks:
        from .contracts import contract
        if contract(task).schema:
            return MODEL
    return None


def _folder() -> Path:
    return settings.data_dir / "chatgpt-plan"


def _private(path: Path, *, directory: bool = False) -> bool:
    st = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    return expected(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077


def _read() -> dict:
    path = _folder() / "session.json"
    try:
        if not _private(_folder(), directory=True) or not _private(path):
            return {}
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def _locked():
    import fcntl

    folder = _folder()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not _private(folder, directory=True):
        raise RuntimeError("ChatGPT connection directory must be private to the Neuro user.")
    fd = os.open(folder / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _save(profile: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=_folder(), delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(profile, f)
            f.flush()
            os.fsync(f.fileno())
            tmp.replace(_folder() / "session.json")
        finally:
            tmp.unlink(missing_ok=True)


def _granted(profile: dict) -> bool:
    return (all(isinstance(profile.get(k), str) and profile[k] for k in
                ("client_id", "subject", "access_token", "refresh_token"))
            and PLAN_SCOPE in str(profile.get("scope", "")).split()
            and type(profile.get("expires_at")) in (int, float)
            and type(profile.get("hold_until", 0)) in (int, float)
            and not profile.get("disconnected"))


def ready() -> bool:
    if settings.fake_ai or not settings.chatgpt_plan_tasks:
        return False
    profile = _read()
    return _granted(profile) and float(profile.get("hold_until") or 0) <= time.time()


def _exchange(fields: dict) -> dict:
    # Never include request/response bodies in errors or logs.
    try:
        response = httpx.post(TOKEN, data={**fields, "resource": RESOURCE}, timeout=20)
        data = response.json()
    except (ValueError, httpx.HTTPError):
        raise PlanWait("ChatGPT sign-in is temporarily unavailable.") from None
    if not isinstance(data, dict):
        raise PlanWait("ChatGPT sign-in returned an invalid response.")
    if not response.is_success:
        if data.get("error") in ("invalid_grant", "invalid_token", "invalid_client"):
            raise PlanWait("Reconnect ChatGPT in Neuro to resume plan use.", 1800)
        raise PlanWait("ChatGPT sign-in is temporarily unavailable.")
    return data


def _tokens(data: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    scope = data.get("scope", previous.get("scope", ""))
    access = data.get("access_token")
    refresh = data.get("refresh_token") or previous.get("refresh_token")
    expires = data.get("expires_in")
    if (not isinstance(scope, str) or PLAN_SCOPE not in scope.split()
            or not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh
            or type(expires) not in (int, float) or not 0 < expires <= 86400 * 30
            or str(data.get("token_type", "")).lower() != "bearer"):
        raise PlanWait("OpenAI did not grant a renewable ChatGPT plan session.", 1800)
    return {"access_token": access, "refresh_token": refresh, "scope": scope, "expires_at": time.time() + expires}


def _identity(id_token: str, client_id: str, nonce: str) -> dict:
    import jwt

    try:
        meta = httpx.get(f"{ISSUER}/.well-known/openid-configuration", timeout=10)
        meta.raise_for_status()
        doc = meta.json()
        key_url = doc["jwks_uri"]
        if doc["issuer"] != ISSUER or not key_url.startswith(f"{ISSUER}/"):
            raise ValueError("issuer")
        key = jwt.PyJWKClient(key_url, timeout=10).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(id_token, key.key, algorithms=["RS256"], audience=client_id,
                            issuer=ISSUER, options={"require": ["sub", "exp", "nonce", "iat"]})
        if not secrets.compare_digest(claims["nonce"], nonce) or not claims["sub"]:
            raise ValueError("nonce")
        return claims
    except (KeyError, ValueError, TypeError, jwt.PyJWTError, httpx.HTTPError):
        raise RuntimeError("Could not verify the ChatGPT account identity.") from None


def connect(*, timeout: float = 180.0) -> None:
    """Explicit owner action. Browser consent and loopback callback, with no inference."""
    import webbrowser

    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    with _locked():
        old = _read()
        host = old.get("host_id") or f"urn:uuid:{uuid4()}"
        client = old.get("client_id")
        # Preserve the host identity even if the owner declines consent.
        if not old:
            _save({"host_id": host})
        callback: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            timeout = 5

            def log_message(self, *_args):
                pass

            def do_GET(self):
                url = urlsplit(self.path)
                fields = parse_qs(url.query)
                valid = url.path == "/auth/callback" and fields.get("state") == [state]
                if valid and not callback:
                    callback.update({k: v[0] for k, v in fields.items() if len(v) == 1})
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"Return to Neuro Search to see the sign-in result." if valid else b"Invalid callback.")

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            server.timeout = 1
            redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
            params = {"client_id": client or "dynamic_agent_client", "ext_agent_host_id": host,
                      "response_type": "code", "redirect_uri": redirect, "scope": SCOPES,
                      "resource": RESOURCE, "state": state, "nonce": nonce,
                      "code_challenge": challenge, "code_challenge_method": "S256"}
            if not client:
                params["agent_name_hint"] = "Neuro Search"
            elif old.get("disconnected"):
                params["prompt"] = "consent"
            if not webbrowser.open(f"{ISSUER}/api/accounts/authorize?{urlencode(params)}"):
                raise RuntimeError("Could not open the browser for ChatGPT sign-in.")
            deadline = time.monotonic() + timeout
            while not callback and time.monotonic() < deadline:
                server.handle_request()
        if callback.get("error") or not callback.get("code"):
            raise RuntimeError("ChatGPT sign-in was cancelled or timed out.")
        issued = callback.get("client_id") or client
        if not issued or issued == "dynamic_agent_client" or (client and client != issued):
            raise RuntimeError("ChatGPT returned an unexpected client registration.")
        data = _exchange({"grant_type": "authorization_code", "client_id": issued, "code": callback["code"],
                          "redirect_uri": redirect, "code_verifier": verifier})
        identity = _identity(data.get("id_token", ""), issued, nonce)
        if old.get("subject") and identity["sub"] != old["subject"]:
            raise RuntimeError("Choose the ChatGPT account already connected to this Neuro installation.")
        _save({"host_id": host, "client_id": issued, "subject": identity["sub"], **_tokens(data)})


def _access() -> str:
    profile = _read()
    if not _granted(profile):
        raise PlanWait("Connect ChatGPT in Neuro to use the plan.", 1800)
    if float(profile.get("hold_until") or 0) > time.time():
        raise PlanWait("ChatGPT plan usage is paused. Check ChatGPT Settings → Usage.", 300)
    if profile["expires_at"] > time.time() + 90:
        return profile["access_token"]
    with _locked():
        profile = _read()
        if not _granted(profile):
            raise PlanWait("Reconnect ChatGPT in Neuro to resume plan use.", 1800)
        if profile["expires_at"] <= time.time() + 90:
            try:
                new = _exchange({"grant_type": "refresh_token", "client_id": profile["client_id"],
                                 "refresh_token": profile["refresh_token"]})
                profile.update(_tokens(new, profile))
            except PlanWait as e:
                if e.wait >= 1800:
                    profile["disconnected"] = True
                    _save(profile)
                raise
            _save(profile)
        return profile["access_token"]


def _hold(code: str, access_token: str, status: int | None = None) -> None:
    limit = code == "subscription_sharing_usage_limit_exceeded"
    disconnected = status in (401, 403) or code == "subscription_sharing_user_not_eligible"
    temporary = code == "subscription_sharing_usage_unavailable" or status in (429, 503)
    if limit or disconnected or temporary:
        wait = 300 if limit else (1800 if disconnected else 60)
        with _locked():
            profile = _read()
            if _granted(profile) and profile["access_token"] == access_token:
                profile.update(hold_until=time.time() + wait, disconnected=disconnected)
                _save(profile)
        message = ("ChatGPT plan usage limit reached. Check ChatGPT Settings → Usage." if limit else
                   "ChatGPT plan access needs attention. Check the connected account in ChatGPT settings." if disconnected else
                   "ChatGPT plan is temporarily unavailable.")
        raise PlanWait(message, wait)
    raise RuntimeError("ChatGPT plan inference did not complete successfully.")


def _as_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(b, dict) and b.get("type") == "text"
                                        and isinstance(b.get("text"), str) for b in content):
        return "\n\n".join(b["text"] for b in content)
    raise ValueError("ChatGPT plan pilot accepts text only.")


def request(*, task: str, system, messages: list[dict]) -> dict:
    from . import contracts, schemas

    contract = contracts.contract(task)
    if not contract.schema or any(m.get("role") != "user" for m in messages):
        raise ValueError("ChatGPT plan pilot requires a structured user request.")
    body = {"model": MODEL, "instructions": _as_text(system),
            "input": [{"role": "user", "content": _as_text(m["content"])} for m in messages],
            "store": False, "stream": True, "reasoning": {"effort": "none"},
            "text": {"format": {"type": "json_schema", "name": contract.schema,
                                "strict": False, "schema": schemas.provider_schema(contract.schema)}}}
    if len(json.dumps(body, ensure_ascii=False).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Request exceeds the ChatGPT plan pilot input limit.")
    return body


def create(*, body: dict, model: str, max_tokens: int, timeout: float) -> SimpleNamespace:
    from openai import APIStatusError, OpenAI

    access_token = _access()
    deadline = time.monotonic() + timeout
    try:
        with OpenAI(api_key=access_token, base_url=RESOURCE, max_retries=0, timeout=timeout) as client:
            with client.responses.create(**body) as events:
                for event in events:
                    if time.monotonic() > deadline:
                        raise RuntimeError("ChatGPT plan response exceeded the task deadline.")
                    if event.type in ("response.completed", "response.incomplete"):
                        response = event.response
                        break
                    if event.type == "response.failed":
                        _hold(getattr(event.response.error, "code", "") or "", access_token)
                    if event.type == "error":
                        _hold(getattr(event, "code", "") or "", access_token)
                else:
                    raise RuntimeError("ChatGPT plan response ended before completion.")
    except APIStatusError as e:
        _hold(str(e.code or ""), access_token, e.status_code)
    from .contracts import same_model
    if not response.model or not same_model(model, response.model):
        raise RuntimeError("ChatGPT returned a different model than the approved pilot model.")
    usage = response.usage
    if usage is None:
        raise RuntimeError("ChatGPT plan response did not report token usage.")
    refusal = any(c.type == "refusal" for item in response.output if item.type == "message" for c in item.content)
    stop = ("refusal" if refusal else "max_tokens" if event.type == "response.incomplete"
            or usage.output_tokens > max_tokens else "end_turn")
    return SimpleNamespace(id=response.id, model=response.model, provider="chatgpt_plan", stop_reason=stop,
                           content=[SimpleNamespace(type="text", text=response.output_text)],
                           usage=SimpleNamespace(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                                 cache_read_input_tokens=getattr(usage.input_tokens_details, "cached_tokens", 0)))
