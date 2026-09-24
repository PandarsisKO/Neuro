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

import glob
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_LIMIT = 5_000_000
# Where the Claude Code CLI (and node/brew tools) usually live on a Mac. launchd starts us with PATH=/usr/bin:/bin:
# /usr/sbin:/sbin -- none of these -- and the first casualty (2026-09-23) was every local-capable job: `claude` is
# not on PATH, so rank_proposed failed on every batch and Kyle saw the ranking "start and stop" in a loop.
USER_BINS = ("~/.local/bin", "~/bin", "~/.claude/local/bin", "~/.claude/local", "~/.npm-global/bin", "~/.volta/bin",
             "~/.bun/bin", "/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin")


def login_path() -> str:
    """The PATH Kyle's own Terminal would have: ask his login shell (sources .zprofile/.zshrc, nvm, brew shellenv...),
    then append the usual user bin dirs as a floor in case the shell printed nothing. Never removes what launchd gave."""
    parts: list[str] = []
    shell = os.environ.get("SHELL") or "/bin/zsh"
    try:
        out = subprocess.run([shell, "-lic", 'printf %s "$PATH"'], capture_output=True, text=True, timeout=15,
                             cwd=str(Path.home()), env={**os.environ, "TERM": "dumb"})
        if out.returncode == 0:
            parts += [x for x in out.stdout.strip().split(":") if x]
    except (OSError, subprocess.SubprocessError):
        pass
    parts += [os.path.expanduser(x) for x in USER_BINS]
    for g in ("~/.nvm/versions/node/*/bin", "~/.local/share/fnm/node-versions/*/installation/bin"):
        parts += sorted(glob.glob(os.path.expanduser(g)), reverse=True)
    parts += [x for x in os.environ.get("PATH", "").split(":") if x]
    seen: set[str] = set()
    return ":".join(x for x in parts if not (x in seen or seen.add(x)))


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
    os.environ["PATH"] = login_path()
    os.write(fd, f"PATH={os.environ['PATH']}\n".encode())
    os.execv(str(py), [str(py), str(exe), "start", "--port", port])   # launchd supervises the server from here


if __name__ == "__main__":
    sys.exit(main())
