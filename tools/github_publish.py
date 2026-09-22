#!/usr/bin/env python3
"""Publish ONE exact commit to GitHub `main`, from the Mac, safely.

WHY THIS EXISTS
---------------
A Cowork/Linux/VM session can create durable commits in this checkout but has no GitHub credential:
publishing here is HTTPS + the macOS `osxkeychain` helper, and a Linux VM has no macOS Keychain. Until now
that meant an uncredentialed session finished its work and left the commits sitting on the Mac, waiting for
a later Claude Code session to notice and push. That is the failure the Git repair was meant to end, so the
fix is a trusted publisher on the credentialed side -- not credentials handed to every session.

    uncredentialed session -> request exact SHA -> Mac-native publisher -> GitHub -> verified receipt

This tool NEVER runs a bare `git push main`. It publishes exactly the SHA it was given, only as a
fast-forward, and then proves the result with `git ls-remote` rather than trusting a local ref.

WHAT IT REFUSES
---------------
Divergence, non-fast-forward, an unreachable or non-commit object, a wrong remote, forbidden paths
(`.env`, `data/`, `VIDEOS/`, key material) and oversized blobs. It never forces, merges, rebases, commits,
stages or stashes, and it never touches the working tree or index -- another session's uncommitted work is
irrelevant to publishing an already-existing commit.

IDEMPOTENCE
-----------
Requested SHA already is GitHub main            -> PASS (no push)
Requested SHA is an ancestor of GitHub main     -> ALREADY_PUBLISHED_BY_LATER_COMMIT (success)
Local main is ahead of the request              -> fine; only the requested SHA is published, never newer
                                                   commits the caller did not ask for.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

EXPECTED_REMOTE = "PandarsisKO/Neuro"
MAX_BLOB_BYTES = 100 * 1024 * 1024          # GitHub's hard per-file limit
FORBIDDEN_PREFIXES = ("data/", "VIDEOS/", "_to_delete/")
FORBIDDEN_NAMES = (".env",)
FORBIDDEN_SUFFIXES = (".pem", ".p12", ".pfx", ".key", "id_rsa", "id_ed25519")
# Credential-shaped strings. Deliberately narrow: this is a tripwire for an obvious mistake,
# never a claim that the range has been proven secret-free.
SECRET_RE = re.compile(rb"(gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}"
                       rb"|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
# Auth failures look different per transport/helper; treat any of these as a credential problem
# rather than as "nothing to push".
CRED_MARKERS = ("could not read Username", "Authentication failed", "terminal prompts disabled",
                "Permission denied", "fatal: Authentication", "invalid credentials", "403 Forbidden",
                "remote: Support for password authentication", "Repository not found")


class Refuse(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def out(*args: str) -> str:
    return git(*args).stdout.strip()


def remote_main() -> str | None:
    """GitHub's real main SHA. Raises Refuse on an auth/network failure so a dead remote can never be
    mistaken for 'the branch does not exist' -- the two have completely different consequences."""
    r = git("ls-remote", "--heads", "origin", "main", check=False)
    if r.returncode != 0:
        blob = (r.stderr or "") + (r.stdout or "")
        status = "BLOCKED_CREDENTIALS" if any(m in blob for m in CRED_MARKERS) else "BLOCKED_REMOTE"
        raise Refuse(status, f"ls-remote failed: {(r.stderr or '').strip()[:300]}")
    line = r.stdout.strip()
    return line.split("\t")[0] if line else None       # None == branch genuinely absent


def check_range(base: str | None, sha: str) -> None:
    """Refuse forbidden paths and oversized blobs in what is about to become public."""
    rng = f"{base}..{sha}" if base else sha
    names = out("diff", "--name-only", rng) if base else out("ls-tree", "-r", "--name-only", sha)
    for p in [n for n in names.splitlines() if n]:
        base_name = os.path.basename(p)
        if p.startswith(FORBIDDEN_PREFIXES) or base_name in FORBIDDEN_NAMES \
                or any(base_name.endswith(s) or base_name == s for s in FORBIDDEN_SUFFIXES):
            raise Refuse("REFUSED_FORBIDDEN_PATH", f"range touches a forbidden path: {p}")

    objs = git("rev-list", "--objects", *( [f"{base}..{sha}"] if base else [sha] ), check=False).stdout
    shas = [ln.split(" ", 1)[0] for ln in objs.splitlines() if ln.strip()]
    if shas:
        cat = subprocess.run(["git", "cat-file", "--batch-check=%(objecttype) %(objectsize) %(objectname)"],
                             input="\n".join(shas), capture_output=True, text=True)
        for ln in cat.stdout.splitlines():
            parts = ln.split()
            if len(parts) == 3 and parts[0] == "blob" and int(parts[1]) > MAX_BLOB_BYTES:
                raise Refuse("REFUSED_OVERSIZED_BLOB",
                             f"blob {parts[2][:12]} is {int(parts[1]):,} bytes (> {MAX_BLOB_BYTES:,})")

    if base:
        diff = git("diff", "-U0", rng, check=False).stdout.encode("utf-8", "replace")
        added = b"\n".join(l for l in diff.splitlines() if l.startswith(b"+") and not l.startswith(b"+++"))
        if SECRET_RE.search(added):
            raise Refuse("REFUSED_POSSIBLE_SECRET", "a credential-shaped string appears in the added lines")


def publish(sha_arg: str, dry_run: bool, receipt_dir: Path | None) -> tuple[str, str, dict]:
    # 1. the remote is the one we think it is
    url = out("remote", "get-url", "origin")
    if EXPECTED_REMOTE not in url:
        raise Refuse("REFUSED_WRONG_REMOTE", f"origin is {url}, expected {EXPECTED_REMOTE}")

    # 2. the request names a real commit
    r = git("rev-parse", "--verify", f"{sha_arg}^{{commit}}", check=False)
    if r.returncode != 0:
        raise Refuse("REFUSED_NOT_A_COMMIT", f"{sha_arg} is not a commit in this repository")
    sha = r.stdout.strip()

    # 3. fetch/prune safely -- a failure here is reported, never ignored
    f = git("fetch", "origin", "--prune", check=False)
    if f.returncode != 0:
        blob = (f.stderr or "") + (f.stdout or "")
        status = "BLOCKED_CREDENTIALS" if any(m in blob for m in CRED_MARKERS) else "BLOCKED_REMOTE"
        raise Refuse(status, f"fetch failed: {(f.stderr or '').strip()[:300]}")

    # 4. the commit must be durable local history, not a stray object
    if git("merge-base", "--is-ancestor", sha, "main", check=False).returncode != 0:
        raise Refuse("REFUSED_NOT_ON_MAIN", f"{sha[:12]} is not reachable from local main")

    # 5. GitHub's real main, via ls-remote (not origin/main)
    rmain = remote_main()

    # 6. idempotence
    if rmain == sha:
        return "PASS", sha, {"remote_before": rmain, "remote_after": rmain, "pushed": False,
                             "note": "requested SHA is already GitHub main"}
    if rmain and git("merge-base", "--is-ancestor", sha, rmain, check=False).returncode == 0:
        return "ALREADY_PUBLISHED_BY_LATER_COMMIT", sha, {
            "remote_before": rmain, "remote_after": rmain, "pushed": False,
            "note": "GitHub is beyond the request and contains it"}

    # 7/8. fast-forward only -- GitHub main must be an ancestor of the request
    if rmain and git("merge-base", "--is-ancestor", rmain, sha, check=False).returncode != 0:
        raise Refuse("REFUSED_DIVERGED",
                     f"GitHub main {rmain[:12]} is not an ancestor of {sha[:12]}; reconcile manually")

    # 9. nothing forbidden becomes public
    check_range(rmain, sha)

    if dry_run:
        return "DRY_RUN", sha, {"remote_before": rmain, "remote_after": rmain, "pushed": False,
                                "note": "would fast-forward GitHub main to the requested SHA"}

    # 10. publish exactly the requested SHA. No --force, ever.
    p = git("push", "origin", f"{sha}:refs/heads/main", check=False)
    if p.returncode != 0:
        blob = (p.stderr or "") + (p.stdout or "")
        if any(m in blob for m in CRED_MARKERS):
            raise Refuse("BLOCKED_CREDENTIALS", f"push failed: {(p.stderr or '').strip()[:300]}")
        # Losing a race is not an error. Between our ls-remote and our push another publisher may have
        # moved main -- possibly to this very SHA. Re-read the remote before calling it a failure, so two
        # sessions asked to publish the same commit both end up correct instead of one reporting BLOCKED.
        now = remote_main()
        if now == sha:
            return "PASS", sha, {"remote_before": rmain, "remote_after": now, "pushed": False,
                                 "note": "another publisher put this exact SHA on main first"}
        if now and git("merge-base", "--is-ancestor", sha, now, check=False).returncode == 0:
            return "ALREADY_PUBLISHED_BY_LATER_COMMIT", sha, {
                "remote_before": rmain, "remote_after": now, "pushed": False,
                "note": "another publisher moved main beyond this SHA while it contained it"}
        raise Refuse("BLOCKED_PUSH", f"push failed: {(p.stderr or '').strip()[:300]}")

    # 11. prove it from the remote, not from a local ref
    after = remote_main()
    if after != sha:
        raise Refuse("BLOCKED_VERIFY", f"after push GitHub main is {str(after)[:12]}, expected {sha[:12]}")
    return "PASS", sha, {"remote_before": rmain, "remote_after": after, "pushed": True}


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish one exact commit to GitHub main from the Mac.")
    ap.add_argument("sha", help="the exact commit to publish")
    ap.add_argument("--dry-run", action="store_true", help="run every check, publish nothing")
    ap.add_argument("--receipt-dir", default=None, help="write a JSON receipt here")
    ap.add_argument("--json", action="store_true", help="print the receipt as JSON only")
    a = ap.parse_args()

    rec: dict = {"requested": a.sha, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        status, sha, extra = publish(a.sha, a.dry_run, None)
        rec.update(status=status, requested_resolved=sha, force_used=False, **extra)
        code = 0
    except Refuse as e:
        rec.update(status=e.status, reason=e.reason, force_used=False)
        code = 2
    except Exception as e:                                        # noqa: BLE001
        rec.update(status="BLOCKED_ERROR", reason=str(e)[:300], force_used=False)
        code = 2

    if a.receipt_dir:
        d = Path(os.path.expanduser(a.receipt_dir)); d.mkdir(parents=True, exist_ok=True)
        (d / f"receipt-{rec['requested'][:12]}-{int(time.time())}.json").write_text(json.dumps(rec, indent=2))

    if a.json:
        print(json.dumps(rec, indent=2))
    else:
        print(f"GitHub publish: {rec['status']}")
        print(f"  requested: {rec.get('requested_resolved', a.sha)}")
        print(f"  remote main: {rec.get('remote_after') or rec.get('remote_before') or '(unknown)'}")
        print(f"  verified via ls-remote: {'yes' if rec['status'] in ('PASS', 'ALREADY_PUBLISHED_BY_LATER_COMMIT') else 'no'}")
        print(f"  force used: no")
        if rec.get("note"):
            print(f"  note: {rec['note']}")
        if rec.get("reason"):
            print(f"  reason: {rec['reason']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
