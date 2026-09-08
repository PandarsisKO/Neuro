#!/usr/bin/env python3
"""A stub `claude` CLI for tests (L1): reproduces the headless JSON contract without Claude Code installed.
FAKE_CLAUDE_MODE: ok (default) | limit | auth | crash | garbage | hang. FAKE_CLAUDE_RESULT: the result text (default "OK").
FAKE_CLAUDE_ARGS: a file path — the argv is appended there so tests can assert the flag table."""
import json
import os
import sys
import time

args = sys.argv[1:]
if os.environ.get("FAKE_CLAUDE_ARGS"):
    with open(os.environ["FAKE_CLAUDE_ARGS"], "a") as f:
        f.write(json.dumps(args) + "\n")
if "--version" in args:
    print("2.1.0 (Claude Code)"); sys.exit(0)
if "--help" in args:
    print("Usage: claude [options] [command] [prompt]\n  -p, --print\n  --output-format <format>\n  --max-turns <n>\n  --system-prompt <prompt>\n  --model <model>\n  --allowedTools <tools...>\n  --tools <tools>\n  --json-schema <schema>\n  --permission-mode <mode>")
    sys.exit(0)
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "hang":
    time.sleep(30); sys.exit(0)
if mode == "auth":
    print("Not logged in. Please run /login", file=sys.stderr); sys.exit(1)
if mode == "crash":
    print("Error: something broke", file=sys.stderr); sys.exit(2)
if mode == "garbage":
    print("this is not json"); sys.exit(0)
if mode == "limit":
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "You've hit your usage limit. Resets at 3pm (America/New_York).", "session_id": "s1"})); sys.exit(1)
result = os.environ.get("FAKE_CLAUDE_RESULT", "OK")
prompt = args[args.index("-p") + 1] if "-p" in args else ""
out = {"type": "result", "subtype": "success", "is_error": False, "result": result, "session_id": "s-fake", "num_turns": 1, "duration_ms": 120,
       "total_cost_usd": 0.0042, "usage": {"input_tokens": max(1, len(prompt) // 4), "output_tokens": max(1, len(result) // 4), "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
       "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 10, "outputTokens": 5}}}
if "--json-schema" in args:
    out["structured_output"] = json.loads(result) if result.strip().startswith("{") else result
print(json.dumps(out))
