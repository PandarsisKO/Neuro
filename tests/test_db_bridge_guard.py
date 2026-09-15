"""CLAUDE.md standing rule #1, enforced: db.connect() refuses the live database when it is reached through a sandbox
bridge mount (/sessions/<id>/mnt/...). Opening it from there -- even read-only -- crashed the live server on
2026-09-11 (x2) and 2026-09-14 (x3) and then corrupted the file. The rule existed in prose the whole time."""
import pytest

from neurosearch import db


def test_refuses_a_bridge_mount_path(monkeypatch):
    monkeypatch.delenv("NEUROSEARCH_ALLOW_BRIDGE_DB", raising=False)
    with pytest.raises(RuntimeError, match="standing rule #1"):
        db.refuse_bridge_mount("/sessions/rcw-abc123/mnt/2026 - KO Neuro Search REPO/data/neurosearch.db")


def test_allows_ordinary_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROSEARCH_ALLOW_BRIDGE_DB", raising=False)
    db.refuse_bridge_mount("/Users/kyleowen/Desktop/2026 - KO Neuro Search REPO/data/neurosearch.db")
    db.refuse_bridge_mount(tmp_path / "neurosearch.db")          # pytest tmp dirs, wherever the runner lives
    db.refuse_bridge_mount("/sessions/rcw-abc123/scratchpad/copy.db")   # a COPY in the session's own workspace, not the mount


def test_escape_hatch_is_explicit(monkeypatch):
    monkeypatch.setenv("NEUROSEARCH_ALLOW_BRIDGE_DB", "1")
    db.refuse_bridge_mount("/sessions/rcw-abc123/mnt/proj/data/neurosearch.db")


def test_connect_goes_through_the_guard(monkeypatch):
    monkeypatch.delenv("NEUROSEARCH_ALLOW_BRIDGE_DB", raising=False)
    db.close_thread_connection()
    monkeypatch.setattr(db._local, "db_path", "/sessions/rcw-abc123/mnt/proj/data/neurosearch.db", raising=False)
    try:
        with pytest.raises(RuntimeError, match="bridge mount"):
            db.connect()
    finally:
        db.close_thread_connection()      # monkeypatch undoes db_path itself
