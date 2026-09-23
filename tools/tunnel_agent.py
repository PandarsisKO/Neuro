#!/usr/bin/env python3
"""Run the Secure MCP Tunnel under the LaunchAgent (P11 EA-9 step 3).

Two constraints shape this file.

The runtime key must never appear in a plist. The tunnel profile references it as
`api_key: "env:CONTROL_PLANE_API_KEY"`, so this wrapper reads it from `.env` -- the Mac's own local config,
owned by Kyle -- and puts it in the environment immediately before exec. launchd sees only this script's path.

It is Python, not a shell script, because of macOS TCC. The repo lives under `~/Desktop`, a protected location.
A launchd job whose program is a shell script there dies before it starts: `/bin/bash` has no access to that
path and fails at `getcwd` with "Operation not permitted" (observed 2026-09-22). The virtualenv's interpreter
does have access -- it is what `com.neurosearch.git-publisher` already uses successfully -- so running under it
is what makes the agent work at all.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILE = os.environ.get("TUNNEL_PROFILE", "local-http")


def main() -> int:
    env_path = REPO / ".env"
    if not env_path.is_file():
        print(f"no .env at {REPO} — cannot obtain CONTROL_PLANE_API_KEY", file=sys.stderr)
        return 78

    env = dict(os.environ)
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    # A second tunnel (profile "gio", 2026-09-23) uses its own org's runtime key: <PROFILE>_CONTROL_PLANE_API_KEY in
    # .env becomes CONTROL_PLANE_API_KEY for this process only, so every profile can reference env:CONTROL_PLANE_API_KEY.
    if PROFILE != "local-http":
        own = env.get(PROFILE.upper().replace("-", "_") + "_CONTROL_PLANE_API_KEY")
        if not own:
            print(f"{PROFILE.upper()}_CONTROL_PLANE_API_KEY is not set in .env", file=sys.stderr)
            return 78
        env["CONTROL_PLANE_API_KEY"] = own
    if not env.get("CONTROL_PLANE_API_KEY"):
        print("CONTROL_PLANE_API_KEY is not set in .env", file=sys.stderr)
        return 78

    tc = env.get("TUNNEL_CLIENT_BIN") or shutil.which("tunnel-client") or "/opt/homebrew/bin/tunnel-client"
    if not os.access(tc, os.X_OK):
        print("tunnel-client not found (brew install openai/tools/tunnel-client)", file=sys.stderr)
        return 127

    os.chdir(REPO)
    os.execve(tc, [tc, "run", "--profile", PROFILE], env)   # replaces this process; launchd supervises it


if __name__ == "__main__":
    sys.exit(main())
