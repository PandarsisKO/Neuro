"""The one place that hands out API clients.

Every module that talks to Anthropic or OpenAI asks here instead of constructing a client itself, so one switch —
`NEUROSEARCH_FAKE_AI=1` — runs the whole application (server, workers, CLI, evals, browser tests) against
deterministic fakes that cost nothing and need no network. This is the seam the task router (hardening ladder,
Rung 4) will later plug into; for now it only knows two providers and one switch.
"""
from __future__ import annotations

from typing import Any

from .config import settings


def fake() -> bool:
    return settings.fake_ai


def anthropic_available() -> bool:
    return fake() or bool(settings.anthropic_api_key)


def openai_available() -> bool:
    return fake() or bool(settings.openai_api_key)


def require_anthropic() -> None:
    if not anthropic_available():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")


def require_openai(what: str = "OPENAI_API_KEY is not set") -> None:
    if not openai_available():
        raise RuntimeError(what)


# ------------------------------------------------------------------ typed provider errors + retry policy (E0/E1)

RATE_LIMIT, TIMEOUT, OVERLOADED, AUTH, INVALID_REQUEST, CONNECTION, REFUSAL, UNKNOWN = (
    "RATE_LIMIT", "TIMEOUT", "OVERLOADED", "AUTH", "INVALID_REQUEST", "CONNECTION", "REFUSAL", "UNKNOWN")
TRANSIENT_TYPES = {RATE_LIMIT, TIMEOUT, OVERLOADED, CONNECTION}


def classify_error(e: BaseException) -> str:
    """Map an SDK exception to a Neuro Search error type by its class (never by message text)."""
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    if name in ("RateLimitError",) or status == 429:
        return RATE_LIMIT
    if name in ("APITimeoutError", "DeadlineExceededError") or status == 408:
        return TIMEOUT
    if name in ("OverloadedError", "ServiceUnavailableError", "InternalServerError") or (status is not None and status >= 500) or status == 529:
        return OVERLOADED
    if name in ("AuthenticationError", "PermissionDeniedError") or status in (401, 403):
        return AUTH
    if name in ("BadRequestError", "UnprocessableEntityError", "NotFoundError", "RequestTooLargeError", "ConflictError") or status in (400, 404, 413, 422, 409):
        return INVALID_REQUEST
    if name in ("APIConnectionError",):
        return CONNECTION
    if name in ("ContentFilterFinishReasonError",) or "refus" in str(e).lower():
        return REFUSAL
    return UNKNOWN


# transport attempts per logical invocation (E1 moves these into the per-task inference contract)
RETRY_POLICY: dict[str, dict[str, Any]] = {
    "default": {"max_attempts": 3, "backoff": [1.0, 4.0]},
    "answer.chat": {"max_attempts": 2, "backoff": [1.0]},
    "answer.repair": {"max_attempts": 2, "backoff": [1.0]},
    "transcribe": {"max_attempts": 2, "backoff": [2.0]},
    "embed": {"max_attempts": 3, "backoff": [1.0, 3.0]},
}


def retry_policy(task: str | None) -> dict[str, Any]:
    return RETRY_POLICY.get(task or "", RETRY_POLICY["default"])


class ProviderError(RuntimeError):
    """A provider call failed after Neuro Search's own attempts. `error_type` is one of the typed categories."""

    def __init__(self, error_type: str, cause: BaseException, attempts: int) -> None:
        super().__init__(f"{error_type} after {attempts} attempt{'s' if attempts != 1 else ''}: {cause}")
        self.error_type, self.cause, self.attempts = error_type, cause, attempts


# ------------------------------------------------------------------ invocation ledger (every paid call is accounted for)

def _request_hash(kw: dict[str, Any]) -> str:
    import hashlib
    import json
    try:
        body = json.dumps({k: v for k, v in kw.items() if k in ("model", "system", "messages", "tools", "input", "max_tokens")}, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        body = repr(kw)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


class _Ledgered:
    """Wraps a provider method: INTENT → IN_FLIGHT before the network call, COMPLETED/FAILED after. If the process dies
    in between, recovery marks the row OUTCOME_UNKNOWN (the provider may have done and charged the work)."""

    def __init__(self, fn: Any, provider: str, default_task: str, policy: dict[str, Any] | None = None) -> None:
        self._fn, self._provider, self._task, self._policy = fn, provider, default_task, policy

    def __call__(self, **kw: Any) -> Any:
        import time as _time

        from . import db, jobs
        task = (kw.get("extra_headers") or {}).get("x-neurosearch-task") or self._task
        jid, run_id = jobs.current_job()
        policy = self._policy or retry_policy(task)
        logical = None
        ihash = _request_hash(kw)
        attempt = 0
        while True:
            attempt += 1
            iid = db.invocation_start(self._provider, task, str(kw.get("model") or ""), ihash, jid, run_id, logical_id=logical, attempt_no=attempt)
            logical = logical or iid
            try:
                res = self._fn(**kw)
            except Exception as e:
                et = classify_error(e)
                db.invocation_finish(iid, "failed", error=str(e), error_type=et, provider_request_id=str(getattr(e, "request_id", "") or "") or None)
                if et in TRANSIENT_TYPES and attempt < policy["max_attempts"]:
                    _time.sleep(policy["backoff"][min(attempt - 1, len(policy["backoff"]) - 1)])
                    continue
                raise ProviderError(et, e, attempt) from e
            jobs.crash_point("provider_response_lost")          # the provider has done (and charged) the work; we die before recording it
            rid = getattr(res, "_request_id", None) or getattr(res, "id", None)
            db.invocation_finish(iid, "completed", provider_request_id=str(rid) if rid else None,
                                 returned_model=str(getattr(res, "model", "") or "") or None)   # configured vs returned
            return res


class _LedgeredStream:
    def __init__(self, fn: Any, provider: str, default_task: str) -> None:
        self._fn, self._provider, self._task = fn, provider, default_task

    def __call__(self, **kw: Any) -> Any:
        from . import db, jobs
        task = (kw.get("extra_headers") or {}).get("x-neurosearch-task") or self._task
        jid, run_id = jobs.current_job()
        iid = db.invocation_start(self._provider, task, str(kw.get("model") or ""), _request_hash(kw), jid, run_id)
        cm = self._fn(**kw)

        class _Wrap:
            def __enter__(self_inner):
                self_inner._s = cm.__enter__()
                return self_inner

            def __getattr__(self_inner, name):
                return getattr(self_inner._s, name)

            def __exit__(self_inner, et, ev, tb):
                r = cm.__exit__(et, ev, tb)
                if et is None:
                    rid = rm = None
                    try:
                        final = self_inner._s.get_final_message()
                        rid = getattr(final, "_request_id", None) or getattr(final, "id", None)
                        rm = getattr(final, "model", None)
                    except Exception:  # noqa: BLE001
                        pass
                    db.invocation_finish(iid, "completed", provider_request_id=str(rid) if rid else None, returned_model=str(rm) if rm else None)
                else:
                    db.invocation_finish(iid, "failed", error=str(ev), error_type=classify_error(ev) if isinstance(ev, BaseException) else None)
                return r
        return _Wrap()


class _Attr:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


def _wrap_anthropic(client: Any) -> Any:
    msgs = client.messages
    stream = getattr(msgs, "stream", None)
    return _Attr(messages=_Attr(create=_Ledgered(msgs.create, "anthropic", "answer.chat"),
                                stream=_LedgeredStream(stream, "anthropic", "planner.build") if stream else None,
                                count_tokens=getattr(msgs, "count_tokens", None)), _raw=client)


def _wrap_openai(client: Any) -> Any:
    return _Attr(embeddings=_Attr(create=_Ledgered(client.embeddings.create, "openai", "embed")),
                 audio=_Attr(transcriptions=_Attr(create=_Ledgered(client.audio.transcriptions.create, "openai", "transcribe"))), _raw=client)


def text_of(resp: Any) -> str:
    """The text of a response, selected by block TYPE. Claude 5 with adaptive thinking returns thinking blocks before
    the text; never assume content[0] is text and never read a thinking block as output."""
    return "".join(getattr(b, "text", "") or "" for b in (getattr(resp, "content", None) or []) if getattr(b, "type", None) == "text")


# ------------------------------------------------------------------ typed output failures (Mission F)

class OutputError(RuntimeError):
    """The provider answered, but the output cannot be used: `kind` is TRUNCATED (stop_reason max_tokens — the JSON
    is incomplete by construction) or REFUSED (stop_reason refusal — the output ignores the schema). Neither is a
    parse problem, and neither is retried blindly: TRUNCATED gets one budget escalation at the call site."""

    TRUNCATED, REFUSED, SCHEMA = "TRUNCATED", "REFUSED", "SCHEMA"

    def __init__(self, kind: str, task: str, detail: str = "") -> None:
        super().__init__(f"{task}: output {kind}" + (f" — {detail}" if detail else ""))
        self.kind, self.task, self.detail = kind, task, detail


class SchemaMismatch(OutputError):
    """Structured output was requested, generation finished normally, yet the JSON does not parse or does not
    validate. With provider-enforced schemas this should never happen; when it does, the call site may fall back
    to its legacy tolerant parser, and that fallback is recorded as a DEGRADED event (Health: structured-output
    fallbacks, steady state 0)."""

    def __init__(self, task: str, detail: str, text: str) -> None:
        super().__init__(OutputError.SCHEMA, task, detail)
        self.text = text


def structured(task: str, resp: Any) -> dict[str, Any]:
    """Parse + validate a structured-output response for `task` against the contract's registry schema.
    Raises OutputError(TRUNCATED|REFUSED) on the explicit stop reasons and SchemaMismatch when the JSON is not the
    schema. Malformed model-generated JSON is no longer a normal failure mode: it is an exception with a name."""
    import json

    from . import contracts as C
    from . import schemas
    c = C.contract(task)
    stop = getattr(resp, "stop_reason", None)
    if stop == "max_tokens":
        raise OutputError(OutputError.TRUNCATED, task, f"max_tokens={c.max_output_tokens}")
    if stop == "refusal":
        raise OutputError(OutputError.REFUSED, task)
    text = text_of(resp).strip()
    if not c.schema:
        raise C.ContractError(f"{task}: structured() needs a contract with a schema")
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise SchemaMismatch(task, f"not JSON: {e}", text) from e
    errors = schemas.validate(c.schema, obj)
    if errors:
        raise SchemaMismatch(task, "; ".join(errors[:3]), text)
    return obj


def schema_fallback(task: str, exc: SchemaMismatch, *, project_id: str | None = None, source_id: str | None = None, recovered: bool = True) -> None:
    """Record that a call site had to use its legacy tolerant parser (or failed outright). This is a degraded event,
    never normal success: it counts into kv evidence:schema_fallbacks → /api/health → Settings → Health."""
    from . import db
    db.validation_event("schema_fallback", {"task": task, "reason": exc.detail[:300], "recovered": recovered, "sample": exc.text[:400]},
                        project_id=project_id, source_id=source_id)
    db.kv_bump("evidence:schema_fallbacks")
    if not recovered:
        db.kv_bump("evidence:schema_failures")


def output_event(task: str, exc: OutputError, *, project_id: str | None = None, source_id: str | None = None, retried: bool = False) -> None:
    from . import db
    db.validation_event("output_" + exc.kind.lower(), {"task": task, "detail": exc.detail, "retried_with_larger_budget": retried}, project_id=project_id, source_id=source_id)
    db.kv_bump("evidence:output_" + exc.kind.lower())


# ------------------------------------------------------------------ the router: product code calls invoke(task, ...)

def invoke(task: str, *, system: Any = None, messages: list[dict[str, Any]] | None = None, tools: list[dict[str, Any]] | None = None,
           stream: bool = False, max_output_tokens: int | None = None, **extra: Any) -> Any:
    """Run one logical inference for `task` under its InferenceContract: the contract chooses provider, model,
    output budget, thinking policy, timeout, transport retries and (Mission F) the enforced output schema; the call
    site supplies only content. `max_output_tokens` is the one explicit override: a single budget escalation after
    a TRUNCATED structured output (recorded by the call site), never a general knob.
    Returns the response (or, with stream=True, the stream context manager)."""
    from . import contracts as C
    c = C.contract(task)
    C.forbid_sampling_knobs(extra, c)
    if c.provider != "anthropic":
        raise C.ContractError(f"{task}: invoke() serves message tasks; {c.provider} tasks use their own client methods")
    client = anthropic_client(**({"timeout": c.timeout} if c.timeout else {}))
    kw: dict[str, Any] = {"model": c.model, **C.request_params(c), "extra_headers": {"x-neurosearch-task": task}, **extra}
    if max_output_tokens:
        kw["max_tokens"] = int(max_output_tokens)
    if system is not None:
        kw["system"] = system
    if messages is not None:
        kw["messages"] = messages
    if tools:
        kw["tools"] = tools
    policy = {"max_attempts": c.max_attempts, "backoff": list(c.backoff)}
    if stream:
        return _LedgeredStream(client.messages.stream._fn if isinstance(client.messages.stream, _LedgeredStream) else client.messages.stream, "anthropic", task)(**kw)
    return _Ledgered(client.messages.create._fn, "anthropic", task, policy=policy)(**kw)


def anthropic_client(**kw: Any) -> Any:
    """anthropic.Anthropic(...) or the fake, wrapped so every call lands in the invocation ledger. kw: timeout, max_retries."""
    from . import logctx
    logctx.set_fields(provider="anthropic", model="fake" if fake() else settings.answer_model)
    if fake():
        from .fake_ai import Anthropic
        return _wrap_anthropic(Anthropic(**kw))
    require_anthropic()
    import anthropic
    kw["max_retries"] = 0                      # Neuro Search owns retries: every network execution is a ledger row
    return _wrap_anthropic(anthropic.Anthropic(api_key=settings.anthropic_api_key, **kw))


def openai_client(**kw: Any) -> Any:
    if fake():
        from .fake_ai import OpenAI
        return _wrap_openai(OpenAI(**kw))
    require_openai()
    from openai import OpenAI
    kw["max_retries"] = 0
    return _wrap_openai(OpenAI(api_key=settings.openai_api_key, **kw))
