#!/usr/bin/env python3
"""Ask the Mac-native publisher to put an exact commit on GitHub. Safe to run from ANY session.

This is what an uncredentialed session (Cowork, a Linux VM, a sandbox) calls instead of telling Kyle
"Claude Code needs to push this". It writes a request file containing a SHA and nothing else -- no
credential ever crosses the boundary -- and then waits for the receipt the Mac-native agent writes back.

    .venv/bin/python tools/publish_request.py <sha> [--session cowork] [--wait 120]

Exit codes: 0 published (or already published), 1 still pending when the wait elapsed, 2 refused/blocked.
A pending exit is NOT success: the durable commit's state is PUBLISH_REQUESTED, not PUBLISHED.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUPPORT = Path.home() / "Library/Application Support/NeuroSearch/git-publisher"
OK = ("PASS", "ALREADY_PUBLISHED_BY_LATER_COMMIT")


def pick_queue() -> Path:
    """Prefer the user-private location; fall back to the repo-local one a mounted VM can reach."""
    try:
        (SUPPORT / "requests").mkdir(parents=True, exist_ok=True)
        probe = SUPPORT / "requests" / ".probe"
        probe.write_text("")
        probe.unlink()
        return SUPPORT
    except OSError:
        d = REPO / ".git-publisher"
        (d / "requests").mkdir(parents=True, exist_ok=True)
        return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sha", help="exact commit to publish to GitHub main")
    ap.add_argument("--session", default=os.environ.get("NEUROSEARCH_SESSION", ""),
                    help="optional label recorded in the receipt")
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait for the receipt (0 = don't wait)")
    a = ap.parse_args()

    queue = pick_queue()
    rid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    (queue / "requests" / f"{rid}.json").write_text(json.dumps(
        {"sha": a.sha, "session": a.session, "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=2))
    print(f"publish requested: {a.sha} (queue {queue}, id {rid})")

    # On the Mac we can run the agent directly, which makes this synchronous and testable. From a VM the
    # LaunchAgent's WatchPaths fires instead and we simply wait for the receipt to appear.
    if sys.platform == "darwin":
        subprocess.run([sys.executable, str(REPO / "tools/git_publish_agent.py")],
                       capture_output=True, text=True, cwd=str(REPO))

    deadline = time.time() + max(0, a.wait)
    while True:
        hits = sorted((queue / "receipts").glob(f"{rid}-*.json")) if (queue / "receipts").is_dir() else []
        if hits:
            rec = json.loads(hits[-1].read_text())
            print(f"receipt: {rec.get('status')}")
            print(f"  requested  : {rec.get('requested_resolved') or rec.get('requested')}")
            print(f"  remote main: {rec.get('remote_after') or rec.get('remote_before') or '(unknown)'}")
            if rec.get("note"):
                print(f"  note: {rec['note']}")
            if rec.get("reason"):
                print(f"  reason: {rec['reason']}")
            return 0 if rec.get("status") in OK else 2
        if time.time() >= deadline:
            print("receipt: PENDING — state is PUBLISH_REQUESTED, not PUBLISHED")
            return 1
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
