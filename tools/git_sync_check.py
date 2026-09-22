#!/usr/bin/env python3
"""Does GitHub contain everything this repo considers durable?

Run this after every delivery. It answers one question and exits nonzero when the answer is no, so
"done" can include a machine-checked GitHub sync rather than a human's memory of having pushed.

The gate exists because of a real failure mode found on 2026-09-22: a local audit used
`git rev-parse --abbrev-ref <branch>@{u}` to decide whether a branch existed on GitHub. That reports the
branch's CONFIGURED UPSTREAM, not remote truth, so five branches that were present on GitHub were reported
as local-only. Remote truth is `git ls-remote`; a `refs/remotes/origin/*` ref is only a cache of it. This
script always refreshes that cache before judging anything.

What it checks
  1. `origin` points at the expected repository.
  2. `main` equals `origin/main` (hard failure in --delivery mode; a warning otherwise).
  3. No commit is reachable from a local ref but from no `origin` ref -- except refs named in the baseline.
  4. No local tag is missing from GitHub -- except tags matched by the baseline.
  5. No tag name exists in both places pointing at different objects.
  6. The active branch's upstream and ahead/behind state are reported.

The baseline (tools/git_sync_baseline.txt) records refs that are KNOWN to be unpublishable and says why.
Without it this gate would fail permanently on pre-existing history and would therefore be ignored, which is
worse than no gate. Anything NOT in the baseline is drift and fails the run. Adding a line to the baseline is
a deliberate, reviewable act -- it is not a way to silence a real sync failure.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

EXPECTED_REMOTE_SUBSTRINGS = ("PandarsisKO/Neuro",)
BASELINE = Path(__file__).with_name("git_sync_baseline.txt")
# Shared with tools/github_publish.py: auth failures look different per transport and helper, and every
# one of them must read as "credentials", never as "nothing to push" or "branch absent".
CRED_MARKERS = ("could not read Username", "Authentication failed", "terminal prompts disabled",
                "Permission denied", "fatal: Authentication", "invalid credentials", "403 Forbidden",
                "remote: Support for password authentication", "Repository not found")


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def load_baseline() -> list[str]:
    if not BASELINE.exists():
        return []
    out = []
    for line in BASELINE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def is_baselined(ref: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(ref, p) for p in patterns)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delivery", action="store_true",
                    help="final/delivery mode: main must equal origin/main, no exceptions")
    ap.add_argument("--no-fetch", action="store_true", help="skip the fetch (use the cache as-is; for tests)")
    args = ap.parse_args()

    patterns = load_baseline()
    failures: list[str] = []
    notes: list[str] = []

    # --- 1. the remote is the one we think it is -------------------------------------------------
    try:
        url = git("remote", "get-url", "origin")
    except RuntimeError:
        print("GitHub sync: FAIL\n  no 'origin' remote is configured")
        return 1
    if not any(s in url for s in EXPECTED_REMOTE_SUBSTRINGS):
        failures.append(f"origin is {url}, expected one of {EXPECTED_REMOTE_SUBSTRINGS}")

    # --- 2. refresh the cache from remote truth before judging anything --------------------------
    # A failed fetch must never be silently ignored: judging the cache after a failed refresh is exactly
    # how a gate prints PASS on stale information. Auth failure is reported as auth failure, not as
    # "nothing to do".
    if not args.no_fetch:
        f = subprocess.run(["git", "fetch", "origin", "--prune", "--tags"], capture_output=True, text=True)
        if f.returncode != 0:
            blob = (f.stderr or "") + (f.stdout or "")
            kind = "credentials" if any(m in blob for m in CRED_MARKERS) else "remote/network"
            print("GitHub sync: FAIL")
            print(f"  fetch failed ({kind}): {(f.stderr or '').strip()[:300]}")
            print("\n  Refusing to judge sync state from a stale cache after a failed refresh.")
            return 1

    # --- 3. main vs origin/main ------------------------------------------------------------------
    # ls-remote FAILING and the branch NOT EXISTING are different facts with different consequences,
    # so they are never collapsed into one empty string.
    local_main = git("rev-parse", "--verify", "main", check=False)
    remote_main = ""
    ls_proc = subprocess.run(["git", "ls-remote", "--heads", "origin", "main"],
                             capture_output=True, text=True)
    if ls_proc.returncode != 0:
        blob = (ls_proc.stderr or "") + (ls_proc.stdout or "")
        kind = "credentials" if any(m in blob for m in CRED_MARKERS) else "remote/network"
        print("GitHub sync: FAIL")
        print(f"  ls-remote failed ({kind}): {(ls_proc.stderr or '').strip()[:300]}")
        print("\n  Remote truth is unavailable; this is NOT the same as 'main does not exist'.")
        return 1
    ls = ls_proc.stdout.strip()
    if ls:
        remote_main = ls.split("\t")[0]
    else:
        failures.append("origin has no 'main' branch (ls-remote succeeded and returned nothing)")
    if local_main and remote_main:
        if local_main == remote_main:
            main_state = "exact"
        else:
            ahead = git("rev-list", "--count", f"{remote_main}..{local_main}", check=False) or "?"
            behind = git("rev-list", "--count", f"{local_main}..{remote_main}", check=False) or "?"
            main_state = f"DIVERGED (local ahead {ahead}, behind {behind})"
            msg = f"main {local_main[:8]} != origin/main {remote_main[:8]} ({main_state})"
            (failures if args.delivery else notes).append(msg)
    else:
        main_state = "UNKNOWN"
        failures.append("could not resolve main and/or origin/main")

    # --- 4. commits reachable locally but from no origin ref -------------------------------------
    local_refs = [r for r in git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags").splitlines() if r]
    audited = [r for r in local_refs if not is_baselined(r, patterns)]
    skipped = [r for r in local_refs if is_baselined(r, patterns)]
    local_only = 0
    if audited:
        out = git("rev-list", *audited, "--not", "--remotes=origin", check=False)
        local_only = len([c for c in out.splitlines() if c])
    if local_only:
        failures.append(f"{local_only} commit(s) reachable from a local ref but from no origin ref")

    # --- 5. tags: missing remotely, and same-name mismatches -------------------------------------
    remote_tags: dict[str, str] = {}
    for line in git("ls-remote", "--tags", "--refs", "origin", check=False).splitlines():
        if "\t" in line:
            sha, ref = line.split("\t", 1)
            remote_tags[ref.removeprefix("refs/tags/")] = sha
    local_tags = [t for t in git("tag").splitlines() if t]
    missing, mismatched = [], []
    for t in local_tags:
        if is_baselined(f"refs/tags/{t}", patterns):
            continue
        if t not in remote_tags:
            missing.append(t)
        else:
            # compare the COMMIT each side resolves to, so annotated vs lightweight is not a false alarm
            lhs = git("rev-parse", f"{t}^{{commit}}", check=False)
            rhs = git("rev-parse", f"{remote_tags[t]}^{{commit}}", check=False)
            if lhs and rhs and lhs != rhs:
                mismatched.append(t)
    if missing:
        failures.append(f"{len(missing)} durable tag(s) absent from GitHub: {', '.join(missing[:8])}"
                        + (" …" if len(missing) > 8 else ""))
    if mismatched:
        failures.append(f"{len(mismatched)} tag(s) point at a different object on GitHub: {', '.join(mismatched[:8])}")

    # --- 6. active branch upstream / ahead-behind -------------------------------------------------
    branch = git("rev-parse", "--abbrev-ref", "HEAD", check=False)
    upstream = git("rev-parse", "--abbrev-ref", f"{branch}@{{u}}", check=False) or "(none)"
    ab = ""
    if upstream != "(none)":
        counts = git("rev-list", "--left-right", "--count", f"{upstream}...{branch}", check=False)
        if counts:
            behind_n, ahead_n = (counts.split() + ["?", "?"])[:2]
            ab = f" (ahead {ahead_n}, behind {behind_n})"
        if upstream == "(none)":
            notes.append(f"branch '{branch}' has no upstream configured")

    # --- report -----------------------------------------------------------------------------------
    ok = not failures
    print(f"GitHub sync: {'PASS' if ok else 'FAIL'}")
    print(f"  origin: {url}")
    print(f"  main: {main_state}")
    print(f"  local-only commits: {local_only}")
    print(f"  local-only durable tags: {len(missing)}")
    print(f"  tag SHA mismatches: {len(mismatched)}")
    print(f"  branch: {branch} -> {upstream}{ab}")
    if skipped:
        print(f"  baselined refs skipped: {len(skipped)} (see {BASELINE.name})")
    for n in notes:
        print(f"  note: {n}")
    for f in failures:
        print(f"  FAIL: {f}")
    if not ok:
        print("\n  'Done' requires a passing sync. Locally complete but unpushed work is NOT DELIVERED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
