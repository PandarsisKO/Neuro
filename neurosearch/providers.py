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

    def __init__(self, fn: Any, provider: str, default_task: str) -> None:
        self._fn, self._provider, self._task = fn, provider, default_task

    def __call__(self, **kw: Any) -> Any:
        from . import db, jobs
        task = (kw.get("extra_headers") or {}).get("x-neurosearch-task") or self._task
        jid, run_id = jobs.current_job()
        iid = db.invocation_start(self._provider, task, str(kw.get("model") or ""), _request_hash(kw), jid, run_id)
        try:
            res = self._fn(**kw)
        except Exception as e:
            db.invocation_finish(iid, "failed", error=str(e))
            raise
        jobs.crash_point("provider_response_lost")          # the provider has done (and charged) the work; we die before recording it
        rid = getattr(res, "_request_id", None) or getattr(res, "id", None)
        db.invocation_finish(iid, "completed", provider_request_id=str(rid) if rid else None)
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
                    try:
                        final = self_inner._s.get_final_message()
                        rid = getattr(final, "_request_id", None) or getattr(final, "id", None)
                    except Exception:  # noqa: BLE001
                        rid = None
                    db.invocation_finish(iid, "completed", provider_request_id=str(rid) if rid else None)
                else:
                    db.invocation_finish(iid, "failed", error=str(ev))
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


def anthropic_client(**kw: Any) -> Any:
    """anthropic.Anthropic(...) or the fake, wrapped so every call lands in the invocation ledger. kw: timeout, max_retries."""
    from . import logctx
    logctx.set_fields(provider="anthropic", model="fake" if fake() else settings.answer_model)
    if fake():
        from .fake_ai import Anthropic
        return _wrap_anthropic(Anthropic(**kw))
    require_anthropic()
    import anthropic
    return _wrap_anthropic(anthropic.Anthropic(api_key=settings.anthropic_api_key, **kw))


def openai_client(**kw: Any) -> Any:
    if fake():
        from .fake_ai import OpenAI
        return _wrap_openai(OpenAI(**kw))
    require_openai()
    from openai import OpenAI
    return _wrap_openai(OpenAI(api_key=settings.openai_api_key, **kw))
