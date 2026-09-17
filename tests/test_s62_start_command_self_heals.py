"""S62 — `start.command` clears a stuck port itself instead of requiring `restart.command` (2026-09-17).

Kyle: *"I ran the restart command, but its pretty shitty that a python crash can cause this to keep
happening to us."* A crash leaves uvicorn's parent alive and still holding the port, so the next launch
used to refuse to start ("something is already listening") and tell Kyle to close the window and
double-click `restart.command` separately -- a manual recovery step after every crash. `start.command`
now performs exactly the same recovery (`restart.command`'s own kill -> wait -> SIGKILL sequence) itself,
automatically, before it would otherwise refuse to start.

This is an end-to-end test of the real script (not a text gate): it binds a real process to a throwaway
port, points `start.command` at that port via `NEUROSEARCH_PORT`, and checks the stuck process actually
gets cleared and the app actually gets launched afterward -- not just that the right words appear in the
script.
"""
from __future__ import annotations

import pathlib
import shutil
import socket
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def sandbox(tmp_path: pathlib.Path) -> pathlib.Path:
    """A throwaway copy of just what start.command needs, so this never touches the real venv/app."""
    d = tmp_path / "app"
    d.mkdir()
    shutil.copy(REPO / "start.command", d / "start.command")
    (d / "start.command").chmod(0o755)
    venv_bin = d / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    # a stub `neurosearch` standing in for the real one: it just proves it was reached
    stub = venv_bin / "neurosearch"
    stub.write_text("#!/bin/bash\necho STUB_NEUROSEARCH_REACHED \"$@\"\ntouch \"$(dirname \"$0\")/../../reached.marker\"\n")
    stub.chmod(0o755)
    return d


def test_a_stuck_port_is_freed_and_the_app_still_launches(sandbox: pathlib.Path):
    port = _free_port()
    # hold the port the way a crashed-but-still-listening uvicorn parent would
    holder = subprocess.Popen(
        [sys.executable, "-c",
         f"import socket,time\n"
         f"s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
         f"s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
         f"s.bind(('127.0.0.1', {port}))\n"
         f"s.listen(1)\n"
         f"time.sleep(60)\n"],
    )
    try:
        # give it a moment to actually bind before start.command checks for it
        deadline = time.time() + 5
        bound = False
        while time.time() < deadline:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.connect(("127.0.0.1", port))
                bound = True
                probe.close()
                break
            except OSError:
                probe.close()
                time.sleep(0.1)
        assert bound, "the dummy port-holder never actually started listening"

        result = subprocess.run(
            ["./start.command"],
            cwd=sandbox,
            env={**__import__("os").environ, "NEUROSEARCH_PORT": str(port)},
            capture_output=True, text=True, timeout=30,
        )

        assert holder.poll() is not None, "start.command must have killed the process holding the port"
        assert (sandbox / "reached.marker").exists(), \
            "start.command must proceed to launch the app after freeing the port, not just free it and stop"
        assert "freeing it automatically" in result.stdout.lower() or "freeing it automatically" in result.stderr.lower(), \
            "start.command must say plainly that it recovered the port on its own"
        log = (sandbox / "data" / "server.log")
        assert log.exists()
        assert "freed automatically" in log.read_text()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_a_genuinely_unfreeable_port_still_refuses_to_start_with_a_clear_message():
    """SIGKILL cannot be simulated as "un-freeable" from an unprivileged test process, so this is a text
    check on the real script rather than an end-to-end run: if automatic recovery still leaves the port
    held (something other than a stale copy of this app owns it), start.command must say so plainly and
    exit non-zero rather than spin forever or silently proceed."""
    body = (REPO / "start.command").read_text()
    assert "if ! free_stuck_port; then" in body
    assert "still held after automatic recovery" in body
    assert "exit 1" in body
    assert "NOT starting" in body
