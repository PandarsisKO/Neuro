"""The one place that hands out API clients.

Every module that talks to Anthropic or OpenAI asks here instead of constructing a client itself, so one switch —
`NEUROSEARCH_FAKE_AI=1` — runs the whole application (server, workers, CLI, evals, browser tests) against
deterministic fakes that cost nothing and need no network. This is the seam the task router (hardening ladder,
Rung 4) will later plug into; for now it only knows two providers and one switch.
"""
from __future__ import annotations

import re

import json
import logging
import time
from typing import Any

from .config import settings

log = logging.getLogger(__name__)


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

RATE_LIMIT, TIMEOUT, OVERLOADED, AUTH, INVALID_REQUEST, CONNECTION, REFUSAL, UNKNOWN, SPEND_CAP, BILLING = (
    "RATE_LIMIT", "TIMEOUT", "OVERLOADED", "AUTH", "INVALID_REQUEST", "CONNECTION", "REFUSAL", "UNKNOWN", "SPEND_CAP", "BILLING")
TRANSIENT_TYPES = {RATE_LIMIT, TIMEOUT, OVERLOADED, CONNECTION}          # transport retries AND circuit breakers (J2) act on these only
# J2: account/request conditions that will NOT recover by retrying — typed failures, never breaker input
NON_TRANSIENT_TYPES = {AUTH, INVALID_REQUEST, REFUSAL, SPEND_CAP, BILLING}


def retry_after_of(e: BaseException) -> float | None:
    """The provider's own retry window in seconds (Retry-After header, seconds or HTTP-date), when it gave one."""
    resp = getattr(e, "response", None)
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    v = headers.get("retry-after") if hasattr(headers, "get") else None
    if not v:
        return None
    try:
        return max(1.0, float(v))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            return max(1.0, parsedate_to_datetime(v).timestamp() - time.time())
        except Exception:  # noqa: BLE001
            return None


def _error_text(e: BaseException) -> str:
    body = getattr(e, "body", None)
    return (json.dumps(body, default=str) if body else "") + " " + str(e)


LOCAL_TYPES = ("LOCAL_UNAVAILABLE", "LOCAL_LIMIT")     # L1: never retried by the ledger, never trip a breaker; the router falls back


def classify_error(e: BaseException) -> str:
    from . import claude_code as CC
    if isinstance(e, CC.LocalLimit):
        return "LOCAL_LIMIT"
    if isinstance(e, CC.LocalUnavailable):
        return "LOCAL_UNAVAILABLE"
    return _classify_error(e)


def _classify_error(e: BaseException) -> str:
    """Map an SDK exception to a Neuro Search error type by its class and status. The one place message text is
    consulted: a 429 with NO retry window that names a spend/usage limit is an account condition (SPEND_CAP), not a
    rate limit, and a 400 that names billing/credit balance is BILLING — neither will recover by retrying."""
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    if name in ("RateLimitError",) or status == 429:
        txt = _error_text(e).lower()
        if retry_after_of(e) is None and ("spend" in txt or "usage limit" in txt or "enforced_spend_limit" in txt or "monthly limit" in txt):
            return SPEND_CAP
        return RATE_LIMIT
    txt_all = _error_text(e).lower()
    if "usage limit" in txt_all and "regain access" in txt_all:
        return SPEND_CAP                      # 2026: the Console's monthly usage limit arrives as a 400 invalid_request_error
    if status == 402 or "credit balance" in txt_all or "billing" in txt_all:
        return BILLING
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


_REGAIN = re.compile(r"regain access on (\d{4}-\d{2}-\d{2})(?: at (\d{2}:\d{2}))?", re.I)


def spend_cap_until(e: BaseException) -> float | None:
    """When an account-level usage limit names the date access returns, the epoch of that moment (UTC); else None."""
    import calendar
    m = _REGAIN.search(_error_text(e))
    if not m:
        return None
    try:
        y, mo, d = (int(x) for x in m.group(1).split("-"))
        hh, mm = (int(x) for x in (m.group(2) or "00:00").split(":"))
        return float(calendar.timegm((y, mo, d, hh, mm, 0)))
    except ValueError:
        return None


class ProviderError(RuntimeError):
    """A provider call failed after Neuro Search's own attempts. `error_type` is one of the typed categories."""

    def __init__(self, error_type: str, cause: BaseException, attempts: int, operation: str | None = None) -> None:
        super().__init__(f"{error_type} after {attempts} attempt{'s' if attempts != 1 else ''}: {cause}")
        self.error_type, self.cause, self.attempts, self.operation = error_type, cause, attempts, operation


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

    def __init__(self, fn: Any, provider: str, default_task: str, policy: dict[str, Any] | None = None, operation: str | None = None) -> None:
        self._fn, self._provider, self._task, self._policy = fn, provider, default_task, policy
        # every Anthropic message task shares ONE breaker (anthropic:messages); OpenAI operations are keyed by method
        self._operation = operation or OPERATION_OF.get((provider, default_task), "anthropic:messages" if provider == "anthropic" else f"{provider}:{default_task}")

    def __call__(self, **kw: Any) -> Any:
        import time as _time

        from . import breakers, db, jobs
        task = (kw.get("extra_headers") or {}).get("x-neurosearch-task") or self._task
        jid, run_id = jobs.current_job()
        policy = self._policy or retry_policy(task)
        worker = f"{jid or 'nojob'}:{run_id or ''}"
        gate = breakers.gate(self._operation, worker)               # J2: an open circuit raises BEFORE any ledger row or attempt
        generation = int(gate.get("generation") or 0)
        probing = bool(gate.get("probe"))
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
                if et in TRANSIENT_TYPES:                            # the breaker sees EVERY transport attempt; non-transient errors never touch it
                    breakers.record_failure(self._operation, et, worker, retry_after_s=retry_after_of(e), generation=generation)
                    if probing:                                      # a failed probe reopened the circuit: stop here
                        raise ProviderError(et, e, attempt) from e
                    if attempt < policy["max_attempts"] and breakers.get(self._operation)["state"] == breakers.CLOSED:
                        _time.sleep(policy["backoff"][min(attempt - 1, len(policy["backoff"]) - 1)])
                        continue
                raise ProviderError(et, e, attempt) from e
            jobs.crash_point("provider_response_lost")          # the provider has done (and charged) the work; we die before recording it
            rid = getattr(res, "_request_id", None) or getattr(res, "id", None)
            db.invocation_finish(iid, "completed", provider_request_id=str(rid) if rid else None,
                                 returned_model=str(getattr(res, "model", "") or "") or None)   # configured vs returned
            breakers.record_success(self._operation, worker, generation=generation)
            db.clear_account_gates()   # a call went through: whatever the account was blocked on is provably over
            return res


# J2 breaker keys: provider:operation — never per model (fragmented keys hide the outage signal)
OPERATION_OF = {("anthropic", "answer.chat"): "anthropic:messages", ("anthropic", "planner.build"): "anthropic:messages",
                ("openai", "embed"): "openai:embeddings", ("openai", "transcribe"): "openai:transcription"}


class _GatedBatches:
    """Message Batches methods behind the anthropic:batches breaker (batches.py keeps its own per-item ledger)."""

    def __init__(self, batches: Any) -> None:
        self._b = batches

    def __getattr__(self, name: str) -> Any:
        fn = getattr(self._b, name)
        if not callable(fn):
            return fn

        def call(*a: Any, **kw: Any) -> Any:
            from . import breakers, db, jobs
            jid, run_id = jobs.current_job()
            worker = f"{jid or 'poller'}:{run_id or ''}"
            gate = breakers.gate("anthropic:batches", worker)
            try:
                out = fn(*a, **kw)
            except Exception as e:
                et = classify_error(e)
                if et in TRANSIENT_TYPES:
                    breakers.record_failure("anthropic:batches", et, worker, retry_after_s=retry_after_of(e), generation=int(gate.get("generation") or 0))
                raise
            breakers.record_success("anthropic:batches", worker, generation=int(gate.get("generation") or 0))
            db.clear_account_gates()
            return out
        return call


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
                                count_tokens=getattr(msgs, "count_tokens", None),
                                batches=_GatedBatches(msgs.batches) if getattr(msgs, "batches", None) is not None else None), _raw=client)     # Message Batches (Rung G): ledgered per item by batches.py; gated by the anthropic:batches breaker (J2)


def _wrap_openai(client: Any) -> Any:
    return _Attr(embeddings=_Attr(create=_Ledgered(client.embeddings.create, "openai", "embed")),
                 audio=_Attr(transcriptions=_Attr(create=_Ledgered(client.audio.transcriptions.create, "openai", "transcribe"))), _raw=client)


# ------------------------------------------------------------------ Rung J3: routing provenance (no automatic fallback exists)

def routing_for(task: str, actual_model: Any) -> dict[str, Any]:
    """The routing decision to persist with an AI artifact. requested_model = the model Neuro Search intentionally
    selected for the task (contract + explicit overrides); actual_model = what the provider reported (a versioned
    snapshot of a requested alias is NOT a fallback); fallback_used reflects the router's decision — and the router has
    exactly one decision available today: no fallback."""
    from . import contracts as C
    c = C.contract(task)
    r = getattr(_tl, "route", None) or {}
    return {"requested_model": c.model, "actual_model": (str(actual_model) if actual_model else None) or c.model, "fallback_used": False,
            "fallback_reason": r.get("fallback_reason"), "fallback_policy": c.fallback, "fallback_policy_version": C.FALLBACK_POLICY_VERSION,
            "executed_by": r.get("executed_by", "api"), "route_reason": r.get("reason")}    # L1: WHICH PROVIDER ran (model substitution is still not a thing)


def routing_json(task: str, actual_model: Any) -> str:
    return json.dumps(routing_for(task, actual_model))


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
    obj = schemas.normalize_enums(c.schema, obj)          # enum casing is not guaranteed by the provider; compare case-insensitively
    obj = schemas.clamp(c.schema, obj)                    # provider-invisible bounds (maxItems/maxLength) clamp, never reject (0.30.3)
    errors = schemas.validate(c.schema, obj)
    if errors:
        raise SchemaMismatch(task, "; ".join(errors[:3]), text)
    return obj


def _bump_event(kind: str, detail: dict[str, Any], *, project_id: str | None, source_id: str | None, counter: str) -> None:
    from . import db
    db.validation_event(kind, detail, project_id=project_id, source_id=source_id)
    db.kv_bump("evidence:" + counter)


def output_event(task: str, exc: OutputError, *, project_id: str | None = None, source_id: str | None = None, **detail: Any) -> None:
    _bump_event("output_" + exc.kind.lower(), {"task": task, "detail": exc.detail, **detail}, project_id=project_id, source_id=source_id, counter="output_" + exc.kind.lower())


COMPAT_FALLBACK_ENV = "NEUROSEARCH_SCHEMA_COMPAT_FALLBACK"      # =1: the explicitly degraded escape hatch (legacy parser + full local validation)

import threading as _threading  # noqa: E402

_tl = _threading.local()


def last_response() -> Any:
    """The provider response behind the most recent invoke_structured() on this thread (model id, usage) — for provenance."""
    return getattr(_tl, "resp", None)


def invoke_structured(task: str, *, system: Any, messages: list[dict[str, Any]], usage_kind: str, project_id: str | None = None,
                      source_id: str | None = None, guard_estimate: float = 0.0, legacy: Any = None) -> dict[str, Any]:
    """The Mission F execution path for a schema'd task:

        provider structured result → json.loads → FULL local schema validation → PASS: return · FAIL: SchemaMismatch

    Legacy parsing is NOT part of this path. What happens on the two explicit failures and the one bug signal:
      * stop_reason max_tokens  → OutputError(TRUNCATED) → exactly one escalation, through usage.guard, capped by the
                                  contract's max_output_ceiling, original/escalated budgets recorded → then a typed error;
      * stop_reason refusal     → OutputError(REFUSED), never parsed;
      * SchemaMismatch on a normal completion → a BUG SIGNAL (schema_mismatch event + counter): retried once with a fresh
                                  completion; if that mismatches too, the typed error propagates and the job fails visibly.
                                  Only with NEUROSEARCH_SCHEMA_COMPAT_FALLBACK=1 does the `legacy` parser run, and its
                                  result must still pass the FULL local schema to be returned (schema_fallback event).
    Health: structured_outputs {mismatches, fallbacks, unrecovered, truncated, refused}; steady state all zero."""
    import os

    from . import contracts as C
    from . import usage
    c = C.contract(task)
    if not c.schema:
        raise C.ContractError(f"{task}: invoke_structured() needs a contract with a schema")
    usage.guard(guard_estimate)
    resp = invoke(task, system=system, messages=messages)
    _tl.resp = resp
    usage.record_anthropic(resp, usage_kind, project_id=project_id, source_id=source_id)
    if getattr(resp, "stop_reason", None) == "max_tokens":
        exc = OutputError(OutputError.TRUNCATED, task, f"max_tokens={c.max_output_tokens}")
        if not c.max_output_ceiling or c.max_output_ceiling <= c.max_output_tokens:
            output_event(task, exc, project_id=project_id, source_id=source_id, budget=c.max_output_tokens, escalated_to=None, ceiling=c.max_output_ceiling)
            raise exc
        bigger = min(int(c.max_output_tokens * 1.5), c.max_output_ceiling)
        output_event(task, exc, project_id=project_id, source_id=source_id, budget=c.max_output_tokens, escalated_to=bigger, ceiling=c.max_output_ceiling, retried_with_larger_budget=True)
        log.warning("%s: output truncated at %d tokens — one escalation to %d (ceiling %d)", task, c.max_output_tokens, bigger, c.max_output_ceiling)
        usage.guard(guard_estimate * 1.5)
        resp = invoke(task, system=system, messages=messages, max_output_tokens=bigger)
        _tl.resp = resp
        usage.record_anthropic(resp, usage_kind, project_id=project_id, source_id=source_id)
        if getattr(resp, "stop_reason", None) == "max_tokens":
            exc = OutputError(OutputError.TRUNCATED, task, f"still truncated at the ceiling {bigger}")
            output_event(task, exc, project_id=project_id, source_id=source_id, budget=bigger, escalated_to=None, ceiling=c.max_output_ceiling, final=True)
            raise exc
    try:
        return structured(task, resp)
    except SchemaMismatch as first:
        _bump_event("schema_mismatch", {"task": task, "reason": first.detail[:300], "sample": first.text[:400], "schema": c.schema, "model": str(getattr(resp, "model", "") or ""), "retried": True},
                    project_id=project_id, source_id=source_id, counter="schema_mismatches")
        log.error("%s: provider-enforced structured output did not match schema %s (%s) — retrying once; this is a bug signal, not a normal failure",
                  task, c.schema, first.detail[:200])
    except OutputError as e:
        output_event(task, e, project_id=project_id, source_id=source_id)
        raise
    usage.guard(guard_estimate)
    resp = invoke(task, system=system, messages=messages)
    _tl.resp = resp
    usage.record_anthropic(resp, usage_kind, project_id=project_id, source_id=source_id)
    try:
        out = structured(task, resp)
        _bump_event("schema_mismatch_recovered", {"task": task, "how": "retry"}, project_id=project_id, source_id=source_id, counter="schema_mismatch_recovered")
        return out
    except SchemaMismatch as second:
        if os.environ.get(COMPAT_FALLBACK_ENV) == "1" and legacy is not None:
            from . import schemas
            try:
                obj = legacy(second.text)
            except Exception as e:  # noqa: BLE001
                obj, err = None, str(e)
            else:
                err = "; ".join(schemas.validate(c.schema, obj)[:3]) if obj is not None else "legacy parser returned nothing"
            if obj is not None and not err:
                _bump_event("schema_fallback", {"task": task, "reason": second.detail[:300], "recovered": True, "validated_against": c.schema},
                            project_id=project_id, source_id=source_id, counter="schema_fallbacks")
                log.error("%s: DEGRADED — legacy compatibility parser produced a schema-valid result (%s=1)", task, COMPAT_FALLBACK_ENV)
                return obj
            _bump_event("schema_fallback", {"task": task, "reason": second.detail[:300], "recovered": False, "legacy_error": err[:300]},
                        project_id=project_id, source_id=source_id, counter="schema_fallbacks")
        _bump_event("schema_failure", {"task": task, "reason": second.detail[:300], "sample": second.text[:400], "schema": c.schema},
                    project_id=project_id, source_id=source_id, counter="schema_failures")
        raise
    except OutputError as e:
        output_event(task, e, project_id=project_id, source_id=source_id)
        raise


# ------------------------------------------------------------------ the router: product code calls invoke(task, ...)

def _stream_collect(client: Any, task: str, kw: dict[str, Any], on_text: Any) -> Any:
    """One API call over the streaming transport, under the same breaker as every other message call.
    Text deltas go to `on_text` as they arrive; the complete Message is returned."""
    from . import breakers, jobs
    jid, run_id = jobs.current_job()
    worker = f"{jid or 'nojob'}:{run_id or ''}"
    gate = breakers.gate("anthropic:messages", worker)
    generation = int(gate.get("generation") or 0)
    fn = client.messages.stream
    fn = fn._fn if isinstance(fn, _LedgeredStream) else fn
    try:
        with _LedgeredStream(fn, "anthropic", task)(**kw) as s:
            for delta in s.text_stream:
                if delta:
                    on_text(delta)
            final = s.get_final_message()
    except Exception as e:
        if classify_error(e) in TRANSIENT_TYPES:
            breakers.record_failure("anthropic:messages", classify_error(e), worker, retry_after_s=retry_after_of(e), generation=generation)
        raise
    breakers.record_success("anthropic:messages", worker, generation=generation)
    from . import db
    db.clear_account_gates()
    return final


def invoke(task: str, *, system: Any = None, messages: list[dict[str, Any]] | None = None, tools: list[dict[str, Any]] | None = None,
           stream: bool = False, max_output_tokens: int | None = None, on_text: Any = None, **extra: Any) -> Any:
    """Run one logical inference for `task` under its InferenceContract: the contract chooses provider, model,
    output budget, thinking policy, timeout, transport retries and (Mission F) the enforced output schema; the call
    site supplies only content. `max_output_tokens` is the one explicit override: a single budget escalation after
    a TRUNCATED structured output (recorded by the call site), never a general knob.
    `on_text` (R1) is a transport detail, not a second entry point: when it is given and the call runs on the API,
    the same request is made over the streaming transport and each text delta is handed to the callback as it
    arrives; the returned value is still the complete final Message, so every caller downstream is unchanged.
    A local (claude_code) route has no token stream, so it silently runs unstreamed — the answer is identical,
    only the typing effect is missing.
    Returns the response (or, with stream=True, the stream context manager)."""
    from . import contracts as C
    c = C.contract(task)
    _tl.task = task
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
    if on_text is not None and not stream:
        target, reason = route(task)
        if target != "local":
            _tl.route = {"executed_by": "api", "reason": reason, "fallback_reason": None}
            _accumulate_route()
            try:
                return _stream_collect(client, task, kw, on_text)
            except Exception as e:  # noqa: BLE001 — a broken stream must never cost the user their answer
                log.warning("%s: streaming transport failed (%s) — answering without token streaming", task, e)
        on_text = None      # fall through to the ordinary path below (local route, or the stream failed)
    if stream:
        _tl.route = {"executed_by": "api", "reason": "stream", "fallback_reason": None}
        return _LedgeredStream(client.messages.stream._fn if isinstance(client.messages.stream, _LedgeredStream) else client.messages.stream, "anthropic", task)(**kw)
    target, reason = route(task)
    if target == "local":
        from . import claude_code as CC
        try:
            resp = _Ledgered(CC.create, CC.PROVIDER, task, policy={"max_attempts": 1, "backoff": []}, operation="claude_code:print")(**kw)
        except ProviderError as e:
            if e.error_type not in LOCAL_TYPES:
                raise
            CC.note_failure(e.cause if isinstance(e.cause, CC.LocalUnavailable) else CC.LocalUnavailable("error", str(e.cause)))
            if current_policy() == "local_only":
                _tl.route = {"executed_by": "none", "reason": reason, "fallback_reason": f"{e.error_type.lower()}: {str(e.cause)[:160]}"}
                _accumulate_route()
                raise
            fb = f"{e.error_type.lower()}: {str(e.cause)[:160]}"
            log.warning("%s: local provider unavailable (%s) — running on the API", task, fb)
            _tl.route = {"executed_by": "api", "reason": reason, "fallback_reason": fb}
            _accumulate_route()
            return _Ledgered(client.messages.create._fn, "anthropic", task, policy=policy)(**kw)
        CC.note_success()
        _tl.route = {"executed_by": "local", "reason": reason, "fallback_reason": None}
        _accumulate_route()
        return resp
    _tl.route = {"executed_by": "api", "reason": reason, "fallback_reason": None}
    _accumulate_route()
    return _Ledgered(client.messages.create._fn, "anthropic", task, policy=policy)(**kw)


# ------------------------------------------------------------------ L1: the provider router (local ⇄ API; never a model substitution)

_policy_tl = _threading.local()


def set_policy(policy: str | None) -> None:
    """The execution policy of the job running on this thread (jobs.execute sets it; interactive calls have none = local_preferred)."""
    _policy_tl.policy = policy


def current_policy() -> str:
    return getattr(_policy_tl, "policy", None) or "local_preferred"


def last_route() -> dict[str, Any]:
    return dict(getattr(_tl, "route", None) or {})


def reset_job_route() -> None:
    """jobs.execute calls this first: the job's outcome accumulates over every invoke on this thread (a fallback is sticky)."""
    _tl.job_route = {"by": set(), "fb": None}


def _accumulate_route() -> None:
    jr = getattr(_tl, "job_route", None)
    r = getattr(_tl, "route", None) or {}
    if jr is not None and r:
        jr["by"].add(r.get("executed_by") or "api")
        if r.get("fallback_reason") and not jr["fb"]:
            jr["fb"] = r["fallback_reason"]


def job_route() -> tuple[str | None, str | None]:
    """(executed_by, fallback_reason) for the job on this thread: local · api · mixed; None when no model call happened."""
    jr = getattr(_tl, "job_route", None)
    if not jr or not jr["by"]:
        return None, None
    by = jr["by"] - {"none"}
    return ("mixed" if len(by) > 1 else (next(iter(by)) if by else "none")), jr["fb"]


def route(task: str) -> tuple[str, str]:
    """("local" | "api", reason). local only when: the task is local-capable, the profile is local, the policy allows it,
    and Claude Code's cached health is ready (a usage limit or a broken install → API, with the reason). local_only with an
    unavailable provider still returns "local" so the failure is typed and visible, never silently spent."""
    from . import claude_code as CC
    from . import contracts as C
    c = C.contract(task)
    pol = current_policy()
    if pol in ("api_only", "api_requested"):
        return "api", f"policy:{pol}"
    if not c.local_capable:
        return "api", "task_not_local_capable"
    if settings.ai_profile != "local":
        return "api", "cloud_profile"
    h = CC.health()
    if h.get("state") == "ready" or pol == "local_only":
        return "local", "local_preferred" if pol != "local_only" else "policy:local_only"
    return "api", f"local_{h.get('state')}"


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


def batch_params(task: str, *, system: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The `params` of one Message Batches request for `task`: exactly the interactive request under the contract
    (model, output budget, thinking, enforced schema) minus the per-request header the batch API does not carry."""
    from . import contracts as C
    c = C.contract(task)
    if c.provider != "anthropic":
        raise C.ContractError(f"{task}: batches serve anthropic message tasks")
    if not c.batch_allowed:
        raise C.ContractError(f"{task}: the contract does not allow batch execution")
    return {"model": c.model, **C.request_params(c), "system": system, "messages": messages}


def message_from_batch_result(msg: Any) -> Any:
    """A batch result's message is the same shape as an interactive response (content blocks, usage, stop_reason, model)."""
    return msg
