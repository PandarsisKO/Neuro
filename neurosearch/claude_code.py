"""L1 — Claude Code as a LOCAL inference provider (LOCAL-AI-PROVIDER.md; policy in EXPANSION.md "Local-First AI").

Claude Code is driven headless (`claude -p … --output-format json`) as an inference engine, never as a developer: no repo,
no tools, no file access, a scratch cwd under data/local_ai/, one turn, a hard timeout from the contract. What comes back
is text (or a structured result) that goes through the SAME ledger, schema validation and provenance as an API response
(`providers._Ledgered` wraps `create`, `providers.structured` parses it) — provider choice never changes behaviour.

Two states the policy distinguishes: UNAVAILABLE (not installed / not signed in / error / timeout / malformed output →
automatic API fallback, recorded) and LOCAL_LIMIT (the subscription's usage limit → fallback, reset time shown). "Busy"
(the local pool is full) is NOT an error: the job waits in the queue; nothing spends.

Tests use NEUROSEARCH_FAKE_CLAUDE_CODE=<ready|not_installed|not_signed_in|limit|error|timeout>: `ready` answers through the
fake Anthropic provider (fixture-exact outputs, so Tier 1 totals are untouched); the others reproduce each failure class
without a binary. `tests/fake_claude_cli.py` is a stub CLI that exercises the real subprocess path (flags, JSON, exit codes).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from .config import settings

log = logging.getLogger("neurosearch.claude_code")

PROVIDER = "claude_code"
FAKE_ENV = "NEUROSEARCH_FAKE_CLAUDE_CODE"
HEALTH_TTL = 600.0            # seconds a health verdict is trusted before re-probing
PROBE_TIMEOUT = 90.0
VERSION_TIMEOUT = 15.0
DEFAULT_TIMEOUT = 300.0
MAX_OUTPUT_CHARS = 400_000    # the CLI's result text is capped before parsing (never unbounded)

# The CLI flag table — the ONE place the command line is spelled. Verified against `claude --help` at runtime by
# `capabilities()` (flags have changed across releases): a flag that the installed CLI does not list is not sent.
CLI = {
    "print": "-p",
    "output_json": ("--output-format", "json"),
    "max_turns": ("--max-turns", "1"),
    "system_prompt": "--system-prompt",
    "model": "--model",
    "tools_none": ("--tools", ""),                 # newer CLIs: no tools at all
    "allowed_none": ("--allowedTools", ""),        # older CLIs: nothing auto-approved (and -p never prompts → tools are denied)
    "json_schema": "--json-schema",                # native structured output when the CLI has it
}

# text patterns in a failed result that mean the SUBSCRIPTION limit, not a broken install
LIMIT_RE = re.compile(r"(usage limit|rate limit|limit (?:has been )?reached|out of (?:credits|quota)|too many requests)", re.I)
RESET_RE = re.compile(r"(?:reset|resets|try again|available)\s*(?:at|in|after)?\s*([^.\n]{3,60})", re.I)
AUTH_RE = re.compile(r"(not (?:logged|signed) in|please (?:log|sign) in|run /login|authenticat|invalid api key|api key)", re.I)


class LocalUnavailable(RuntimeError):
    """The local provider cannot do the work now (missing, not signed in, errored, timed out, malformed output)."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"claude code {kind}: {detail}" if detail else f"claude code {kind}")
        self.kind, self.detail = kind, detail


class LocalLimit(LocalUnavailable):
    """The subscription's usage limit — the policy's own state, with the reset time when the CLI says it."""

    def __init__(self, detail: str = "", reset_hint: str | None = None) -> None:
        super().__init__("usage_limit", detail)
        self.reset_hint = reset_hint


# ------------------------------------------------------------------ the response shape downstream already understands

class _Block:
    def __init__(self, text: str) -> None:
        self.type, self.text = "text", text


class _Usage:
    def __init__(self, u: dict[str, Any]) -> None:
        self.input_tokens = int(u.get("input_tokens") or 0)
        self.output_tokens = int(u.get("output_tokens") or 0)
        self.cache_read_input_tokens = int(u.get("cache_read_input_tokens") or 0)
        self.cache_creation_input_tokens = int(u.get("cache_creation_input_tokens") or 0)


class LocalResponse:
    """Duck-types the Anthropic Message the rest of Neuro Search reads: content[].type/text, stop_reason, usage, model, id."""

    def __init__(self, text: str, usage: dict[str, Any], model: str, session_id: str | None, cost_reported: float | None) -> None:
        self.content = [_Block(text)]
        self.stop_reason = "end_turn"
        self.usage = _Usage(usage)
        self.model = model
        self.id = session_id or ""
        self.provider = PROVIDER
        self.cost_reported = cost_reported       # what the CLI says the call would cost — informational; actual spend is $0


# ------------------------------------------------------------------ fake mode (tests)

def fake_mode() -> str | None:
    return os.environ.get(FAKE_ENV) or None


# ------------------------------------------------------------------ capabilities + health

_lock = threading.Lock()
_state: dict[str, Any] = {"health": None, "caps": None}


def binary() -> str:
    return settings.claude_code_bin or "claude"


def capabilities(force: bool = False) -> dict[str, Any]:
    """Which flags the installed CLI lists (from `claude --help`). Cached per process."""
    with _lock:
        if _state["caps"] is not None and not force:
            return _state["caps"]
    caps: dict[str, Any] = {"help": False, "flags": set()}
    if fake_mode():
        caps = {"help": True, "flags": {"--output-format", "--max-turns", "--system-prompt", "--model", "--allowedTools", "--json-schema", "--tools"}}
    else:
        try:
            out = subprocess.run([binary(), "--help"], capture_output=True, text=True, timeout=VERSION_TIMEOUT)
            text = (out.stdout or "") + (out.stderr or "")
            caps = {"help": True, "flags": {f for f in re.findall(r"(--[a-zA-Z][\w-]*)", text)}}
        except Exception as e:  # noqa: BLE001
            caps = {"help": False, "flags": set(), "error": str(e)[:200]}
    with _lock:
        _state["caps"] = caps
    return caps


def _has(flag: str) -> bool:
    caps = capabilities()
    return (flag in caps["flags"]) if caps.get("help") else True     # no help text → send the documented flags and let the CLI complain


def health(force: bool = False, wait: bool = True) -> dict[str, Any]:
    """ready · not_installed · not_signed_in · usage_limit · error · disabled (cloud profile) · checking. Cached HEALTH_TTL seconds.
    The probe is one tiny prompt (it does spend a few subscription tokens), run only when the profile is local. wait=False
    (the API surfaces) never blocks: a cold or expired verdict starts the probe in the background and returns the last
    known state (or "checking"); the router (wait=True, worker threads) waits for the verdict."""
    if settings.ai_profile != "local":
        return {"state": "disabled", "detail": "AI profile is cloud (NEUROSEARCH_AI_PROFILE=local enables Claude Code)", "checked_at": time.time()}
    with _lock:
        h = _state["health"]
        fresh = bool(h) and not force and time.time() - h["checked_at"] < HEALTH_TTL
        if fresh:
            return h
        if not wait:
            if not _state.get("probing"):
                _state["probing"] = True
                threading.Thread(target=_probe_bg, daemon=True, name="ns-claude-code-probe").start()
            return dict(h or {"state": "checking", "detail": "checking Claude Code…"}, checking=True)
        _state["probing"] = True
    try:
        h = _probe()
        h["checked_at"] = time.time()
        with _lock:
            _state["health"] = h
    finally:
        with _lock:
            _state["probing"] = False
    return h


def _probe_bg() -> None:
    try:
        h = _probe()
        h["checked_at"] = time.time()
        with _lock:
            _state["health"] = h
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state["health"] = {"state": "error", "detail": str(e)[:300], "checked_at": time.time()}
    finally:
        with _lock:
            _state["probing"] = False


def note_failure(e: LocalUnavailable) -> None:
    """A failure seen by a real call updates the cached verdict at once (the next router decision must not wait for the TTL)."""
    with _lock:
        h = dict(_state["health"] or {})
        h.update({"state": "usage_limit" if isinstance(e, LocalLimit) else ("not_signed_in" if e.kind == "not_signed_in" else "not_installed" if e.kind == "not_installed" else "error"),
                  "detail": (e.detail or str(e))[:300], "reset_hint": getattr(e, "reset_hint", None), "checked_at": time.time()})
        _state["health"] = h


def note_success() -> None:
    with _lock:
        h = dict(_state["health"] or {})
        if h.get("state") != "ready":
            h.update({"state": "ready", "detail": "answered", "checked_at": time.time()})
            _state["health"] = h


def _probe() -> dict[str, Any]:
    fm = fake_mode()
    if fm:
        table = {"ready": ("ready", "fake claude code"), "not_installed": ("not_installed", "no `claude` on PATH"), "not_signed_in": ("not_signed_in", "run `claude` once and sign in"),
                 "limit": ("usage_limit", "usage limit reached"), "error": ("error", "exit 1"), "timeout": ("error", "timed out")}
        st, detail = table.get(fm, ("error", f"unknown fake mode {fm}"))
        return {"state": st, "detail": detail, "version": "fake", "reset_hint": "in 2 hours" if st == "usage_limit" else None}
    if not shutil.which(binary()):
        return {"state": "not_installed", "detail": f"`{binary()}` is not on PATH — install Claude Code, or set NEUROSEARCH_CLAUDE_CODE_BIN", "version": None}
    try:
        v = subprocess.run([binary(), "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT)
        version = (v.stdout or v.stderr or "").strip().splitlines()[0][:60] if (v.stdout or v.stderr) else None
    except Exception as e:  # noqa: BLE001
        return {"state": "error", "detail": f"`{binary()} --version` failed: {e}"[:300], "version": None}
    try:
        # Kyle: "our Claude Code subscription is not saturated. Only [the CLI's bare default model] is." The probe used
        # to hardcode model=None here — the CLI's OWN default (its cheapest-available model, whatever that is today),
        # which is a DIFFERENT model than settings.claude_code_model actually pins real calls to (create() below already
        # respects the pin). A probe on the unpinned default can report the whole local path dead over one model's own
        # limit while the pinned model — the one every real call actually uses — is completely fine. Probe with the same
        # pin real work uses, so health reflects what's actually about to be asked to run.
        resp = _run("Reply with exactly the word OK and nothing else.", system=None, model=settings.claude_code_model or None, timeout=PROBE_TIMEOUT, schema=None)
    except LocalLimit as e:
        return {"state": "usage_limit", "detail": e.detail[:300], "version": version, "reset_hint": e.reset_hint}
    except LocalUnavailable as e:
        return {"state": e.kind if e.kind in ("not_signed_in", "not_installed") else "error", "detail": e.detail[:300], "version": version}
    return {"state": "ready", "detail": f"answered in probe ({resp.model})", "version": version, "model": resp.model}


# ------------------------------------------------------------------ the call

def _scratch_cwd() -> str:
    p = settings.data_dir / "local_ai" / "scratch"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _prompt_of(messages: list[dict[str, Any]] | None) -> str:
    """Flatten the message list to one prompt: role labels + text blocks (images/tool blocks are not local-capable in L1)."""
    parts = []
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join((b.get("text") or "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text")
        if m.get("role") == "assistant":
            parts.append(f"[Assistant]\n{text}")
        else:
            parts.append(text)
    return "\n\n".join(p for p in parts if p)


def _system_of(system: Any) -> str | None:
    if system is None:
        return None
    if isinstance(system, str):
        return system
    return "\n\n".join((b.get("text") or "") for b in system if isinstance(b, dict) and b.get("type") == "text") or None


def _classify_failure(text: str, returncode: int) -> LocalUnavailable:
    if LIMIT_RE.search(text):
        m = RESET_RE.search(text)
        return LocalLimit(text[:300], reset_hint=m.group(1).strip() if m else None)
    if AUTH_RE.search(text):
        return LocalUnavailable("not_signed_in", text[:300])
    return LocalUnavailable("error", f"exit {returncode}: {text[:300]}")


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _run(prompt: str, *, system: str | None, model: str | None, timeout: float, schema: dict[str, Any] | None) -> LocalResponse:
    """One headless CLI invocation → LocalResponse. Raises LocalUnavailable / LocalLimit."""
    if not shutil.which(binary()):
        raise LocalUnavailable("not_installed", f"`{binary()}` is not on PATH")
    cmd = [binary(), CLI["print"], prompt, *CLI["output_json"]]
    if _has("--max-turns"):
        cmd += list(CLI["max_turns"])
    sys_text = system
    native_schema = bool(schema) and _has(CLI["json_schema"])
    if schema and not native_schema:
        sys_text = (sys_text + "\n\n" if sys_text else "") + "Respond with ONLY a single JSON object that conforms to this JSON schema — no prose, no code fences:\n" + json.dumps(schema)
    if sys_text and _has(CLI["system_prompt"]):
        cmd += [CLI["system_prompt"], sys_text]
    if model and _has(CLI["model"]):
        cmd += [CLI["model"], model]
    if _has("--tools"):
        cmd += list(CLI["tools_none"])
    elif _has("--allowedTools"):
        cmd += list(CLI["allowed_none"])
    if native_schema:
        cmd += [CLI["json_schema"], json.dumps(schema)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEUROSEARCH_")}
    env["CLAUDE_CODE_NO_TELEMETRY"] = env.get("CLAUDE_CODE_NO_TELEMETRY", "1")
    t0 = time.time()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=_scratch_cwd(), env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise LocalUnavailable("timeout", f"no answer within {timeout:.0f}s") from e
    except FileNotFoundError as e:
        raise LocalUnavailable("not_installed", str(e)) from e
    raw = (out.stdout or "")[:MAX_OUTPUT_CHARS]
    if out.returncode != 0 and not raw.strip():
        raise _classify_failure(out.stderr or "", out.returncode)
    try:
        data = json.loads(raw)
        if isinstance(data, list):                                  # stream-json style arrays: the result event is last
            data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), data[-1] if data else {})
    except ValueError as e:
        raise LocalUnavailable("malformed_output", f"not JSON ({e}): {raw[:200]}") from e
    if not isinstance(data, dict):
        raise LocalUnavailable("malformed_output", f"unexpected shape: {raw[:200]}")
    if data.get("is_error") or str(data.get("subtype") or "").startswith("error"):
        raise _classify_failure(str(data.get("result") or data.get("error") or data.get("subtype") or out.stderr or ""), out.returncode)
    text = data.get("structured_output") if native_schema and data.get("structured_output") is not None else data.get("result")
    if isinstance(text, (dict, list)):
        text = json.dumps(text)
    if text is None:
        raise LocalUnavailable("malformed_output", f"no result field: {raw[:200]}")
    text = _strip_fences(str(text)) if schema else str(text)
    usage = data.get("usage") or {}
    mu = data.get("modelUsage") or {}
    if isinstance(mu, dict) and mu:
        busiest = max(mu.items(), key=lambda kv: int((kv[1] or {}).get("outputTokens") or 0) + int((kv[1] or {}).get("inputTokens") or 0))[0]
    else:
        busiest = None
    model_name = busiest or model or "claude-code"      # what actually answered (the CLI may route a trivial prompt to Haiku)
    cost = data.get("total_cost_usd")
    log.info("claude code %s answered in %.1fs (%s in / %s out)", model_name, time.time() - t0, usage.get("input_tokens"), usage.get("output_tokens"))
    return LocalResponse(text, usage, str(model_name), data.get("session_id"), float(cost) if isinstance(cost, (int, float)) else None)


def create(**kw: Any) -> LocalResponse:
    """The `messages.create`-shaped entry point `providers.invoke` routes to. kw is the API request Neuro Search would
    have sent: system, messages, max_tokens, output_config (schema), extra_headers (task)."""
    task = (kw.get("extra_headers") or {}).get("x-neurosearch-task") or ""
    fm = fake_mode()
    if fm and fm != "ready":
        errors = {"not_installed": LocalUnavailable("not_installed", "no `claude` on PATH"), "not_signed_in": LocalUnavailable("not_signed_in", "please log in"),
                  "limit": LocalLimit("You've hit your usage limit. Resets at 6pm.", reset_hint="6pm"), "error": LocalUnavailable("error", "exit 1: boom"),
                  "timeout": LocalUnavailable("timeout", "no answer within 1s")}
        raise errors.get(fm, LocalUnavailable("error", f"fake mode {fm}"))
    if fm == "ready":
        from .fake_ai import Anthropic
        resp = Anthropic().messages.create(**{k: v for k, v in kw.items() if k != "extra_headers"}, extra_headers=kw.get("extra_headers") or {})
        u = getattr(resp, "usage", None)
        usage = {"input_tokens": getattr(u, "input_tokens", 0), "output_tokens": getattr(u, "output_tokens", 0),
                 "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0), "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0)}
        from .providers import text_of
        out = LocalResponse(text_of(resp), usage, f"fake-claude-code:{kw.get('model')}", "fake-session", None)
        out.stop_reason = getattr(resp, "stop_reason", "end_turn")
        return out
    from . import contracts as C
    c = C.contract(task) if task else None
    schema = None
    if c and c.schema:
        from . import schemas
        schema = schemas.provider_schema(c.schema)
    timeout = float(c.timeout) if c and c.timeout else DEFAULT_TIMEOUT
    return _run(_prompt_of(kw.get("messages")), system=_system_of(kw.get("system")), model=settings.claude_code_model or None, timeout=timeout, schema=schema)


def status_line(wait: bool = False) -> str:
    """One line for doctor / the Jobs header (never blocks unless asked)."""
    h = health(wait=wait)
    st = h.get("state")
    if st == "disabled":
        return "Claude Code: off (cloud profile)"
    if st == "checking":
        return "Claude Code: checking…"
    if st == "ready":
        return f"Claude Code: ready{(' ' + h['version']) if h.get('version') else ''}"
    if st == "usage_limit":
        return f"Claude Code: usage limit{(' — resets ' + h['reset_hint']) if h.get('reset_hint') else ''} · API fallback active"
    return f"Claude Code: {str(st).replace('_', ' ')} — {h.get('detail') or ''} · API fallback active"
