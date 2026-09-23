#!/usr/bin/env python3
"""Run the Neuro Search server under a LaunchAgent, so it survives reboots, logouts and a closed Terminal window.

Why (P11, 2026-09-22): once Gio uses Neuro from her own ChatGPT, Neuro has to be up whenever her ChatGPT reaches the
tunnel, not only while a Terminal window Kyle opened is still around. The tunnel already runs this way
(com.neurosearch.tunnel); this is the matching server half.

Same shape as tools/tunnel_agent.py, for the same macOS reason: the repo lives under ~/Desktop (TCC-protected), and a
launchd job whose program is a shell script there dies at getcwd. The venv's interpreter has access, so this runs
under it and execs the server in place.

It keeps start.command's behaviour: output goes to data/server.log (rotated at ~5 MB, one generation kept), and
`neurosearch start` is the same auto-reloading server Kyle runs by hand. It does NOT free a busy port itself — a
server started by hand would otherwise be killed silently by a background job; install_server_agent.sh stops that
copy once, deliberately, at install time.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_LIMIT = 5_000_000


def main() -> int:
    os.chdir(REPO)
    exe = REPO / ".venv" / "bin" / "neurosearch"
    py = REPO / ".venv" / "bin" / "python"
    if not exe.exists() or not py.exists():
        print(f"no .venv at {REPO} — run ./start once to create it", file=sys.stderr)
        return 78
    (REPO / "data").mkdir(exist_ok=True)
    log = REPO / "data" / "server.log"
    try:
        if log.exists() and log.stat().st_size > LOG_LIMIT:
            log.replace(log.with_name("server.log.1"))
    except OSError:
        pass
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.write(fd, f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  starting Neuro Search (LaunchAgent) =====\n".encode())
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    port = os.environ.get("NEUROSEARCH_PORT", "8000")
    os.execv(str(py), [str(py), str(exe), "start", "--port", port])   # launchd supervises the server from here


if __name__ == "__main__":
    sys.exit(main())
