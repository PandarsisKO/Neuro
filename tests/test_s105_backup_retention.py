"""S105 — backup retention is configurable (Kyle, 2026-10-22: data/backups was large).

An hourly FULL copy of the database, newest `keep` retained, was hardcoded keep=48 / every=3600 with no way to
turn it down: deleting the files just let it refill to 48 within two days. `backup()` now defaults to
settings.backup_keep (NEUROSEARCH_BACKUP_KEEP) and the loop to settings.backup_interval_s. Defaults are unchanged,
so nobody who doesn't set them sees a difference; setting a smaller keep self-prunes on the next snapshot. Floors
(keep>=2, interval>=300s) stop a typo from erasing the recovery window.

Note: Settings() reads the environment live through its field factories, so these build a fresh Settings() under
patched env rather than reloading the config module (a reload would swap the shared singleton and break the suite).
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_s105_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import config, db  # noqa: E402


def _settings(monkeypatch, **env):
    for k in ("NEUROSEARCH_BACKUP_KEEP", "NEUROSEARCH_BACKUP_INTERVAL_S"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config.Settings()


def test_defaults_unchanged(monkeypatch):
    s = _settings(monkeypatch)
    assert s.backup_keep == 48 and s.backup_interval_s == 3600.0


def test_env_lowers_retention(monkeypatch):
    s = _settings(monkeypatch, NEUROSEARCH_BACKUP_KEEP="6", NEUROSEARCH_BACKUP_INTERVAL_S="7200")
    assert s.backup_keep == 6 and s.backup_interval_s == 7200.0


def test_floors_protect_the_recovery_window(monkeypatch):
    # a too-small positive value is floored to 2; a 0/invalid value falls back to the default (int_env's rule) --
    # either way you are never left with zero backups
    s = _settings(monkeypatch, NEUROSEARCH_BACKUP_KEEP="1", NEUROSEARCH_BACKUP_INTERVAL_S="5")
    assert s.backup_keep == 2, "keep=1 is floored at 2 -- always at least one spare"
    assert s.backup_interval_s == 300.0, "interval is floored at 5 min"
    s0 = _settings(monkeypatch, NEUROSEARCH_BACKUP_KEEP="0")
    assert s0.backup_keep == 48, "0/invalid is ignored, default stands -- never zero backups"


def test_backup_prunes_to_the_configured_keep(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    monkeypatch.setattr(config.settings, "backup_keep", 3)
    (tmp_path / "media").mkdir()
    db._local.conn = None
    db.init_db()
    bdir = tmp_path / "backups"; bdir.mkdir(exist_ok=True)
    for i in range(10):
        (bdir / f"neurosearch-202601{i:02d}-0000.db").write_bytes(b"old")
    db.backup()  # keep defaults to settings.backup_keep (3)
    assert len(sorted(bdir.glob("neurosearch-*.db"))) == 3
    db._local.conn = None


def test_backup_keep_can_still_be_passed_explicitly(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    (tmp_path / "media").mkdir()
    db._local.conn = None
    db.init_db()
    bdir = tmp_path / "backups"; bdir.mkdir(exist_ok=True)
    for i in range(5):
        (bdir / f"neurosearch-202602{i:02d}-0000.db").write_bytes(b"old")
    db.backup(keep=2)
    assert len(sorted(bdir.glob("neurosearch-*.db"))) == 2
    db._local.conn = None
