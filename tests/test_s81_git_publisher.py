"""S81: the Mac-native publish path — exact-SHA, fast-forward-only, verified from the remote.

These tests reproduce the failure this repo kept having: an uncredentialed session creates a durable commit
and it sits unpublished until someone notices. Everything here runs against a real local bare repository
standing in for GitHub. No network, no credentials, no paid calls.

The bare repo is deliberately created at a path containing "PandarsisKO/Neuro" so the publisher's
remote-identity check runs for real rather than being stubbed out.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PUBLISH = REPO / "tools/github_publish.py"
SYNC = REPO / "tools/git_sync_check.py"


def run(*args, cwd, env=None, check=False):
    e = dict(os.environ)
    e.setdefault("GIT_TERMINAL_PROMPT", "0")
    if env:
        e.update(env)
    r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, env=e)
    if check and r.returncode != 0:
        raise AssertionError(f"{' '.join(args)} failed: {r.stderr}")
    return r


def git(*args, cwd, **kw):
    return run("git", *args, cwd=cwd, **kw)


def publish(work, sha, *extra):
    r = run(sys.executable, str(PUBLISH), sha, "--json", *extra, cwd=work)
    try:
        return json.loads(r.stdout), r
    except json.JSONDecodeError:
        raise AssertionError(f"publisher produced no JSON. out={r.stdout!r} err={r.stderr!r}")


@pytest.fixture()
def world(tmp_path):
    """A bare 'GitHub' plus a working clone, with one commit already published as main."""
    bare = tmp_path / "PandarsisKO" / "Neuro.git"
    bare.parent.mkdir(parents=True)
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path, check=True)

    work = tmp_path / "work"
    git("clone", str(bare), str(work), cwd=tmp_path, check=True)
    git("config", "user.email", "t@example.com", cwd=work, check=True)
    git("config", "user.name", "T", cwd=work, check=True)
    (work / "a.txt").write_text("A\n")
    git("add", "a.txt", cwd=work, check=True)
    git("commit", "-m", "A", cwd=work, check=True)
    git("push", "origin", "main", cwd=work, check=True)
    return work, bare


def head(work, ref="main"):
    return git("rev-parse", ref, cwd=work).stdout.strip()


def remote_main(bare):
    out = git("ls-remote", "--heads", str(bare), "main", cwd=bare).stdout.strip()
    return out.split("\t")[0] if out else None


def commit(work, name, text="x"):
    """Returns the NEW commit via HEAD -- never `main`, which is wrong on any other branch."""
    (work / name).write_text(text)
    git("add", name, cwd=work, check=True)
    git("commit", "-m", name, cwd=work, check=True)
    return head(work, "HEAD")


def test_uncredentialed_commit_reaches_github_by_fast_forward(world):
    """The whole point: local commit B becomes GitHub main, verified from the remote, tree untouched."""
    work, bare = world
    a = remote_main(bare)
    b = commit(work, "b.txt")

    tree_before = git("write-tree", cwd=work).stdout.strip()
    status_before = git("status", "--porcelain", cwd=work).stdout

    rec, _ = publish(work, b)

    assert rec["status"] == "PASS", rec
    assert rec["remote_before"] == a and rec["remote_after"] == b
    assert rec["force_used"] is False
    assert remote_main(bare) == b                      # proven from the remote, not a local ref
    # publishing an existing commit must not disturb another session's work
    assert git("write-tree", cwd=work).stdout.strip() == tree_before
    assert git("status", "--porcelain", cwd=work).stdout == status_before


def test_requesting_the_same_sha_twice_is_idempotent(world):
    work, bare = world
    b = commit(work, "b.txt")
    first, _ = publish(work, b)
    second, _ = publish(work, b)
    assert first["status"] == "PASS" and first["pushed"] is True
    assert second["status"] == "PASS" and second["pushed"] is False
    assert remote_main(bare) == b


def test_local_advancing_does_not_publish_commits_nobody_requested(world):
    """B is requested, local moves to C first. B must publish alone; C only when asked."""
    work, bare = world
    b = commit(work, "b.txt")
    c = commit(work, "c.txt")            # local main is now C while the B request is pending

    rec_b, _ = publish(work, b)
    assert rec_b["status"] == "PASS"
    assert remote_main(bare) == b, "publishing B must not drag C along"

    rec_c, _ = publish(work, c)
    assert rec_c["status"] == "PASS"
    assert remote_main(bare) == c


def test_ancestor_of_remote_reports_already_published(world):
    work, bare = world
    b = commit(work, "b.txt")
    c = commit(work, "c.txt")
    publish(work, c)
    rec, _ = publish(work, b)            # B is now behind GitHub, but contained in it
    assert rec["status"] == "ALREADY_PUBLISHED_BY_LATER_COMMIT"
    assert rec["pushed"] is False and remote_main(bare) == c


def test_divergence_is_refused_never_forced(world):
    """Someone else moved GitHub. The publisher refuses instead of reconciling or forcing."""
    work, bare = world
    other = work.parent / "other"
    git("clone", str(bare), str(other), cwd=work.parent, check=True)
    git("config", "user.email", "o@example.com", cwd=other, check=True)
    git("config", "user.name", "O", cwd=other, check=True)
    (other / "o.txt").write_text("O\n")
    git("add", "o.txt", cwd=other, check=True)
    git("commit", "-m", "O", cwd=other, check=True)
    git("push", "origin", "main", cwd=other, check=True)
    moved = remote_main(bare)

    b = commit(work, "b.txt")            # built on the old base -> diverged
    rec, proc = publish(work, b)
    assert rec["status"] == "REFUSED_DIVERGED", rec
    assert proc.returncode == 2
    assert remote_main(bare) == moved, "a refusal must leave GitHub exactly as it was"


def test_forbidden_paths_are_refused(world):
    work, bare = world
    before = remote_main(bare)
    (work / "data").mkdir(exist_ok=True)
    (work / "data" / "neurosearch.db").write_text("not really a db")
    git("add", "-f", "data/neurosearch.db", cwd=work, check=True)
    git("commit", "-m", "oops", cwd=work, check=True)
    rec, _ = publish(work, head(work))
    assert rec["status"] == "REFUSED_FORBIDDEN_PATH"
    assert "data/" in rec["reason"]
    assert remote_main(bare) == before


def test_credential_shaped_string_is_refused(world):
    work, bare = world
    before = remote_main(bare)
    (work / "cfg.txt").write_text("token = ghp_" + "A" * 36 + "\n")
    git("add", "cfg.txt", cwd=work, check=True)
    git("commit", "-m", "leak", cwd=work, check=True)
    rec, _ = publish(work, head(work))
    assert rec["status"] == "REFUSED_POSSIBLE_SECRET"
    assert remote_main(bare) == before


def test_a_commit_not_on_main_is_refused(world):
    work, _ = world
    git("checkout", "-b", "side", cwd=work, check=True)
    side = commit(work, "s.txt")
    git("checkout", "main", cwd=work, check=True)
    rec, _ = publish(work, side)
    assert rec["status"] == "REFUSED_NOT_ON_MAIN"


def test_wrong_remote_is_refused(tmp_path):
    bare = tmp_path / "SomeoneElse" / "Other.git"
    bare.parent.mkdir(parents=True)
    git("init", "--bare", "-b", "main", str(bare), cwd=tmp_path, check=True)
    work = tmp_path / "w"
    git("clone", str(bare), str(work), cwd=tmp_path, check=True)
    git("config", "user.email", "t@example.com", cwd=work, check=True)
    git("config", "user.name", "T", cwd=work, check=True)
    (work / "a.txt").write_text("A\n")
    git("add", "a.txt", cwd=work, check=True)
    git("commit", "-m", "A", cwd=work, check=True)
    rec, _ = publish(work, head(work))
    assert rec["status"] == "REFUSED_WRONG_REMOTE"


def test_unreachable_remote_is_blocked_never_silently_ok(world):
    """An auth/network failure must never read as 'nothing to push'."""
    work, _ = world
    b = commit(work, "b.txt")
    git("remote", "set-url", "origin", "https://127.0.0.1:9/PandarsisKO/Neuro.git", cwd=work, check=True)
    rec, proc = publish(work, b)
    assert rec["status"].startswith("BLOCKED_"), rec
    assert proc.returncode == 2
    assert rec["force_used"] is False


def test_credential_markers_classify_as_blocked_credentials():
    """The exact strings git emits for auth failure must map to BLOCKED_CREDENTIALS, not a generic error."""
    sys.path.insert(0, str(REPO / "tools"))
    import github_publish as gp

    for msg in ("fatal: could not read Username for 'https://github.com': terminal prompts disabled",
                "remote: Support for password authentication was removed.",
                "fatal: Authentication failed for 'https://github.com/PandarsisKO/Neuro.git/'"):
        assert any(m in msg for m in gp.CRED_MARKERS), msg


def test_concurrent_duplicate_requests_resolve_to_one_safe_result(world):
    """Two publishers racing the same SHA: one pushes, both end correct, nothing is forced."""
    work, bare = world
    b = commit(work, "b.txt")
    procs = [subprocess.Popen([sys.executable, str(PUBLISH), b, "--json"], cwd=str(work),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outs = [json.loads(p.communicate()[0]) for p in procs]
    assert all(o["status"] in ("PASS", "ALREADY_PUBLISHED_BY_LATER_COMMIT") for o in outs), outs
    assert all(o["force_used"] is False for o in outs)
    assert sum(1 for o in outs if o.get("pushed")) <= 1, "at most one process may actually push"
    assert remote_main(bare) == b


def test_sync_gate_fails_loudly_when_the_remote_cannot_be_reached(world):
    """The gate must never print PASS from a stale cache after a failed refresh."""
    work, _ = world
    git("remote", "set-url", "origin", "https://127.0.0.1:9/PandarsisKO/Neuro.git", cwd=work, check=True)
    r = run(sys.executable, str(SYNC), cwd=work)
    assert r.returncode != 0
    assert "FAIL" in r.stdout
    assert "PASS" not in r.stdout.splitlines()[0]
    assert "failed" in r.stdout.lower()


def test_a_non_macos_session_queues_where_the_mac_agent_will_look(monkeypatch, tmp_path):
    """Found on the first real Cowork use: `~/Library/Application Support/...` is creatable inside a Linux VM,
    so the old writability probe succeeded there and the request landed somewhere the Mac agent never reads —
    PENDING forever, silently. Off macOS the repo queue is the only genuinely shared location."""
    sys.path.insert(0, str(REPO / "tools"))
    import publish_request as pr

    monkeypatch.setattr(pr, "SUPPORT", tmp_path / "vm-home" / "Library/Application Support/NeuroSearch/git-publisher")
    monkeypatch.setattr(pr, "REPO", tmp_path / "repo")

    monkeypatch.setattr(sys, "platform", "linux")
    assert pr.pick_queue() == tmp_path / "repo" / ".git-publisher", "a VM must queue in the shared repo dir"
    assert not (tmp_path / "vm-home").exists(), "a VM must not create a queue the Mac agent cannot see"

    monkeypatch.setattr(sys, "platform", "darwin")
    assert pr.pick_queue() == pr.SUPPORT, "on the Mac the user-private queue is still preferred"


def test_publish_request_stays_runnable_by_a_bare_python3():
    """Claude Desktop's Linux sandbox cannot use `.venv/bin/python` — this repo's virtualenv points at a macOS
    interpreter, and the path existing on the shared mount makes that failure confusing rather than obvious.
    The request side must therefore need nothing but the standard library, and must say so."""
    import ast

    text = (REPO / "tools/publish_request.py").read_text()
    mods = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods.add(n.module.split(".")[0])
    extra = sorted(m for m in mods if m not in sys.stdlib_module_names)
    assert not extra, f"publish_request.py must be stdlib-only so a bare python3 can run it; found {extra}"
    assert "python3 tools/publish_request.py" in text, "the usage line must not send other sessions to .venv"
