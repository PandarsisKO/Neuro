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


def anthropic_client(**kw: Any) -> Any:
    """anthropic.Anthropic(...) or the fake. kw: timeout, max_retries."""
    from . import logctx
    logctx.set_fields(provider="anthropic", model="fake" if fake() else settings.answer_model)
    if fake():
        from .fake_ai import Anthropic
        return Anthropic(**kw)
    require_anthropic()
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, **kw)


def openai_client(**kw: Any) -> Any:
    if fake():
        from .fake_ai import OpenAI
        return OpenAI(**kw)
    require_openai()
    from openai import OpenAI
    return OpenAI(api_key=settings.openai_api_key, **kw)
