"""Structured log correlation (Mission A9).

Every log line carries the job/run/project/source/task/model it belongs to, from a thread-local context that the
worker sets when it claims a job and that AI calls extend with their task. Lines render as
    2026-09-06 21:40:01 INFO neurosearch.findings [job=8c1f run=2 project=4a9e source=77b1 task=findings.extract] finding rejected…
and `NEUROSEARCH_LOG_JSON=1` switches to one JSON object per line for log shippers.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
from typing import Any, Iterator

_local = threading.local()
FIELDS = ("job_id", "run_id", "project_id", "source_id", "task", "provider", "model")


def get() -> dict[str, Any]:
    return dict(getattr(_local, "ctx", {}) or {})


def set_fields(**fields: Any) -> None:
    ctx = get()
    for k, v in fields.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v
    _local.ctx = ctx


def clear() -> None:
    _local.ctx = {}


@contextlib.contextmanager
def context(**fields: Any) -> Iterator[None]:
    before = get()
    set_fields(**fields)
    try:
        yield
    finally:
        _local.ctx = before


_SECRETS = [
    (re.compile(r"(sk-ant-[A-Za-z0-9_-]{6})[A-Za-z0-9_-]+"), r"\1…"),                 # Anthropic keys
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{4})[A-Za-z0-9_-]{12,}"), r"\1…"),                # OpenAI keys
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s'\"]+"), r"\1[redacted]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[redacted]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|passwd|secret|cookie|session[_-]?id|x-api-key)\s*[=:]\s*)[^\s,;'\"&]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(/mcp/)[A-Za-z0-9._~-]{8,}"), r"\1[redacted]"),                   # MCP url token
    (re.compile(r"(?i)([?&](?:sig|signature|x-amz-signature|x-goog-signature|token|key|auth|access_token|expires)=)[^&\s]+"), r"\1[redacted]"),
]


def redact(text: str) -> str:
    for pat, rep in _SECRETS:
        text = pat.sub(rep, text)
    return text


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            if redact(msg) != msg:
                record.msg, record.args = redact(msg), ()
        except Exception:  # noqa: BLE001
            pass
        ctx = get()
        for k in FIELDS:
            setattr(record, k, ctx.get(k))
        short = " ".join(f"{k.replace('_id', '')}={str(v)[:8] if k.endswith('_id') else v}" for k, v in ctx.items() if k in FIELDS)
        record.ctx = f"[{short}] " if short else ""
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k in FIELDS:
            v = getattr(record, k, None)
            if v is not None:
                d[k] = v
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)
        return json.dumps(d, default=str)


def configure(level: int = logging.INFO) -> None:
    """Install once per process (server, CLI, tests)."""
    root = logging.getLogger()
    if getattr(root, "_ns_configured", False):
        return
    handler = logging.StreamHandler()
    if os.environ.get("NEUROSEARCH_LOG_JSON") == "1":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(ctx)s%(message)s"))
    handler.addFilter(ContextFilter())
    root.handlers[:] = [handler]
    root.setLevel(level)
    root._ns_configured = True  # type: ignore[attr-defined]
