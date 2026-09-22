#!/usr/bin/env python3
"""The Mac-native side of the publish path: drain publish requests, write receipts.

Invoked by a macOS LaunchAgent (com.neurosearch.git-publisher) running as Kyle's normal user whenever a
request file appears. It holds no credential of its own -- it runs `tools/github_publish.py`, which uses the
Mac's existing `osxkeychain` helper. A Linux/VM session can drop a request; only this side can publish.

QUEUE LOCATIONS (a request is a SHA, never a secret)
    <repo>/.git-publisher/requests/                      <- gitignored; what a VM with the repo mounted can reach
    ~/Library/Application Support/NeuroSearch/git-publisher/requests/

Both are watched because they solve different halves of the problem: the second is the tidy user-private
location, the first is the only one a session that mounts just the repo can actually write to. Receipts are
written next to the request that produced them, so the requesting session can read its own result.

SAFETY. This never modifies the working tree, index or any ref. It does not commit, stage, stash, reset,
merge or rebase, and it never forces. Another session's uncommitted work is irrelevant: publishing an
existing commit touches nothing. A flock makes concurrent/duplicate requests resolve to one safe result.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUPPORT = Path.home() / "Library/Application Support/NeuroSearch/git-publisher"
QUEUES = [REPO / ".git-publisher", SUPPORT]
LOCK = SUPPORT / "publisher.lock"
LOG = SUPPORT / "agent.log"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n"
    with LOG.open("a") as fh:
        fh.write(line)
    print(line, end="")


def process(req_path: Path, queue: Path) -> None:
    try:
        body = json.loads(req_path.read_text())
        sha = str(body.get("sha", "")).strip()
        session = str(body.get("session", "") or "")
    except Exception as e:                                        # noqa: BLE001
        log(f"malformed request {req_path.name}: {e}")
        sha, session, body = "", "", {}

    receipts = queue / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    stamp = f"{req_path.stem}-{int(time.time())}"

    if not sha:
        rec = {"status": "REFUSED_BAD_REQUEST", "reason": "request has no 'sha'",
               "requested": None, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session}
    else:
        # The publisher owns every check. The agent only decides WHEN to run it.
        r = subprocess.run([sys.executable, str(REPO / "tools/github_publish.py"), sha, "--json"],
                           capture_output=True, text=True, cwd=str(REPO))
        try:
            rec = json.loads(r.stdout)
        except Exception:                                         # noqa: BLE001
            rec = {"status": "BLOCKED_ERROR", "requested": sha,
                   "reason": (r.stderr or r.stdout or "publisher produced no output")[:300]}
        rec["session"] = session

    (receipts / f"{stamp}.json").write_text(json.dumps(rec, indent=2))
    done = queue / "done"
    done.mkdir(parents=True, exist_ok=True)
    try:
        req_path.rename(done / f"{stamp}.json")
    except OSError:
        req_path.unlink(missing_ok=True)
    log(f"{rec.get('status')} {str(rec.get('requested'))[:12]} (from {queue.name}/{req_path.name})")


def main() -> int:
    SUPPORT.mkdir(parents=True, exist_ok=True)
    # One publisher at a time. Duplicate/concurrent requests then resolve to one safe result:
    # the first publishes, the rest observe an already-published remote and return PASS.
    with LOCK.open("w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another publisher run holds the lock; exiting (its result covers this trigger)")
            return 0
        n = 0
        for queue in QUEUES:
            reqs = queue / "requests"
            if not reqs.is_dir():
                continue
            for req in sorted(reqs.glob("*.json")):
                process(req, queue)
                n += 1
        if n == 0:
            log("no pending requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
