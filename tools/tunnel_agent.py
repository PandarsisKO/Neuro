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
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILE = os.environ.get("TUNNEL_PROFILE", "local-http")
PROFILE_DIR = Path(os.environ.get("TUNNEL_CLIENT_PROFILE_DIR") or (Path.home() / ".config/tunnel-client"))
TUNNEL_HEADER = "X-Neuro-Tunnel"          # must match neurosearch.idp.TUNNEL_HEADER
WAIT_FOR_NEURO_S = int(os.environ.get("TUNNEL_WAIT_FOR_NEURO_S") or 180)


def wait_for_neuro(url: str, deadline_s: int) -> bool:
    """Block until Neuro answers, because tunnel-client caches a failed OAuth discovery for its whole life.

    At startup tunnel-client fetches Neuro's protected-resource metadata once. If Neuro is not up yet the fetch
    fails, `/readyz` stays 503, and the daemon never retries -- it sat that way for two and a half hours on
    2026-09-23 (client started 08:22:22, discovery failed 08:23:49, Neuro first answered 08:24:53) and only a
    manual restart cleared it. Every agent here is RunAtLoad, so at login this is a race the tunnel can lose.

    Waiting is the fix rather than retrying discovery, because the retry is not ours to implement. Returning
    False lets the caller exit EX_TEMPFAIL so launchd's KeepAlive tries again, instead of starting a daemon that
    is permanently half-dead.
    """
    started = time.monotonic()
    while True:
        try:
            urllib.request.urlopen(url, timeout=5).read(1)
            waited = time.monotonic() - started
            if waited >= 1:
                print(f"Neuro answered after {waited:.0f}s — starting tunnel-client", file=sys.stderr)
            return True
        except urllib.error.HTTPError:
            return True                   # 401/404 is still Neuro answering; only a dead socket is "not up"
        except Exception:                 # noqa: BLE001 — connection refused, DNS, timeout: all mean "not yet"
            pass
        if time.monotonic() - started >= deadline_s:
            print(f"Neuro did not answer {url} within {deadline_s}s — exiting so launchd retries", file=sys.stderr)
            return False
        time.sleep(2)


def ensure_tunnel_header(profile: str) -> str | None:
    """Make the profile tell Neuro which tunnel a request came through. Idempotent; returns the tunnel id.

    Neuro serves one resource per tunnel and has nothing else to key on -- tunnel-client's requests are
    byte-identical between profiles, `Host: localhost:8000` included (measured 2026-09-23). The header is set
    here, not only by hand, so that `tunnel-client init` (which knows nothing about Neuro) cannot quietly drop
    it: without it Neuro falls back to the FIRST configured resource, which for Gio's tunnel is Kyle's -- the
    exact bug this closes, and a silent one.
    """
    path = PROFILE_DIR / f"{profile}.yaml"
    if not path.is_file():
        print(f"no tunnel-client profile at {path}", file=sys.stderr)
        return None
    text = path.read_text()
    m = re.search(r'^\s*tunnel_id:\s*"?(tunnel_[A-Za-z0-9]+)"?', text, re.M)
    if not m:
        print(f"{path} has no tunnel_id — cannot set {TUNNEL_HEADER}", file=sys.stderr)
        return None
    tid = m.group(1)

    present = re.findall(rf'^\s*{re.escape(TUNNEL_HEADER)}:\s*"?([^"\s]+)"?\s*$', text, re.M | re.I)
    if present and all(v == tid for v in present):
        return tid                                                   # already correct: touch nothing
    if present:                                                      # points at the wrong tunnel: correct it
        text = re.sub(rf'^(\s*{re.escape(TUNNEL_HEADER)}:\s*)"?[^"\s]+"?\s*$', rf'\g<1>"{tid}"', text,
                      flags=re.M | re.I)
        path.write_text(text)
        print(f"{path}: {TUNNEL_HEADER} corrected to {tid}", file=sys.stderr)
        return tid

    anchor = re.search(r'^mcp:\n', text, re.M)
    if not anchor:
        print(f"{path} has no mcp: block — cannot set {TUNNEL_HEADER}", file=sys.stderr)
        return None
    block = (f"  # Which tunnel a request arrived through, so Neuro can advertise THIS tunnel's resource rather\n"
             f"  # than the first one configured. Written by tools/install_tunnel_agent.sh; do not drop it.\n"
             f"  extra_headers:\n    {TUNNEL_HEADER}: \"{tid}\"\n"
             f"  discovery_extra_headers:\n    {TUNNEL_HEADER}: \"{tid}\"\n")
    text = text[:anchor.end()] + block + text[anchor.end():]
    path.write_text(text)
    print(f"{path}: {TUNNEL_HEADER} set to {tid}", file=sys.stderr)
    return tid


def main() -> int:
    if "--ensure-profile" in sys.argv:                               # install-time use; does not run the daemon
        i = sys.argv.index("--ensure-profile")
        return 0 if ensure_tunnel_header(sys.argv[i + 1] if i + 1 < len(sys.argv) else PROFILE) else 1

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
        prefix = PROFILE.upper().replace("-", "_")
        own = env.get(prefix + "_CONTROL_PLANE_API_KEY")
        if not own:
            print(f"{prefix}_CONTROL_PLANE_API_KEY is not set in .env", file=sys.stderr)
            return 78
        env["CONTROL_PLANE_API_KEY"] = own
        # The tunnel id needs the same treatment, and for a sharper reason: CONTROL_PLANE_TUNNEL_ID in the
        # environment BEATS the profile's own tunnel_id (measured 2026-09-23 -- `doctor --profile gio` reports
        # Kyle's id with the variable set and Gio's without it). Because this wrapper loads all of .env, Kyle's
        # CONTROL_PLANE_TUNNEL_ID would otherwise run every profile against Kyle's tunnel, silently.
        # Same precedence rule applies to the tunnel's organization and the control-plane base URL, so every
        # per-profile value travels as <PROFILE>_<NAME> in .env and nothing of Kyle's leaks into another profile.
        for name in ("CONTROL_PLANE_TUNNEL_ID", "CONTROL_PLANE_ORGANIZATION_ID", "CONTROL_PLANE_BASE_URL"):
            own_value = env.get(f"{prefix}_{name}")
            if own_value:
                env[name] = own_value
            else:
                env.pop(name, None)
    if not env.get("CONTROL_PLANE_API_KEY"):
        print("CONTROL_PLANE_API_KEY is not set in .env", file=sys.stderr)
        return 78

    tc = env.get("TUNNEL_CLIENT_BIN") or shutil.which("tunnel-client") or "/opt/homebrew/bin/tunnel-client"
    if not os.access(tc, os.X_OK):
        print("tunnel-client not found (brew install openai/tools/tunnel-client)", file=sys.stderr)
        return 127

    ensure_tunnel_header(PROFILE)

    health = env.get("NEUROSEARCH_HEALTH_URL") or f"http://127.0.0.1:{env.get('NEUROSEARCH_PORT', '8000')}/"
    if not wait_for_neuro(health, WAIT_FOR_NEURO_S):
        return 75                                           # EX_TEMPFAIL — KeepAlive restarts us

    os.chdir(REPO)
    os.execve(tc, [tc, "run", "--profile", PROFILE], env)   # replaces this process; launchd supervises it


if __name__ == "__main__":
    sys.exit(main())
