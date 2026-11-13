"""Loopback text transport for the task router. One profile request, no tools or cloud."""
from types import SimpleNamespace

import httpx

from . import schemas

ORIGIN = "http://127.0.0.1:11434"


class ModelUnavailable(RuntimeError):
    pass


def create(*, model, system, messages, schema, max_tokens, timeout):
    body = {"model": model, "messages": [{"role": "system", "content": system}, *messages],
            "format": schemas.get(schema), "think": False, "stream": False, "keep_alive": 0,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": max_tokens}}
    # Ignore system proxy variables; only the loopback runtime can receive source text.
    with httpx.Client(base_url=ORIGIN, trust_env=False, timeout=httpx.Timeout(timeout or 120, connect=2)) as client:
        response = client.post("/api/chat", json=body)
        if response.status_code == 404:
            raise ModelUnavailable(f"Install {model} in Ollama to resume Mac work")
        response.raise_for_status()
        data = response.json()
    return SimpleNamespace(
        provider="ollama", model=data["model"], stop_reason="max_tokens" if data.get("done_reason") == "length" else "end_turn",
        content=[SimpleNamespace(type="text", text=data["message"]["content"])],
        usage=SimpleNamespace(input_tokens=data.get("prompt_eval_count", 0), output_tokens=data.get("eval_count", 0)),
        seconds=data.get("total_duration", 0) / 1e9,
    )
