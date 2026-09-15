"""Restore the live database from the newest copy that passes a FULL integrity check.

Run ON THE MAC, with `neurosearch serve` and `neurosearch worker` both stopped:

    .venv/bin/python tools/db_restore.py          # dry run: says what it WOULD do, changes nothing
    .venv/bin/python tools/db_restore.py --yes    # do it

Candidates, newest first: (1) the live main file WITHOUT its -wal (if only the write-ahead log is damaged, the main
file is intact and newer than any backup), (2) data/backups/*.db newest-first. Each candidate is copied and full
integrity-checked BEFORE it is installed. The damaged files are moved to data/corrupt-<stamp>/, never deleted.
"""
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "neurosearch.db"
SIDE = [DB.with_name(DB.name + "-wal"), DB.with_name(DB.name + "-shm")]


def full_check(path: Path) -> list[str]:
    conn = sqlite3.connect(str(path), timeout=60)
    try:
        return [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    except sqlite3.DatabaseError as e:
        return [f"ERROR: {e}"]
    finally:
        conn.close()


def holders() -> str:
    try:
        return subprocess.run(["lsof", "-t", str(DB)], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        return ""


def _refuse_bridge_mount() -> None:
    real = str(DB.resolve())
    if "/sessions/" in real and "/mnt/" in real:
        sys.exit(f"REFUSING: {real} is the live database seen through a sandbox bridge mount. Run this on the Mac "
                 "(CLAUDE.md standing rule #1: opening the live WAL database from another VM crashes the app and corrupts the file).")


def main() -> int:
    _refuse_bridge_mount()
    do = "--yes" in sys.argv
    h = holders()
    if h and "--ignore-holders" not in sys.argv:
        print(f"REFUSING: something still has the database open (pids {h.replace(chr(10), ' ')}). Stop serve and worker first.")
        print("(if `ps -p <pid> -o command` shows only com.apple.Virtualization -- a sandbox's stale read handle, no writer -- add --ignore-holders)")
        return 2
    if h:
        print(f"note: ignoring holder pids {h.replace(chr(10), ' ')} at your request")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    quarantine = DATA / f"corrupt-{stamp}"
    scratch = DATA / f"restore-scratch-{stamp}"
    scratch.mkdir()
    try:
        # candidate 1: the live main file alone (no WAL applied)
        cands: list[tuple[str, Path]] = []
        main_only = scratch / "main-only.db"
        shutil.copyfile(DB, main_only)
        r = full_check(main_only)
        print(f"live main file WITHOUT its -wal: {'CLEAN' if r == ['ok'] else r[0][:120]}")
        if r == ["ok"]:
            cands.append(("live main file (WAL discarded)", main_only))
        else:
            for b in sorted((DATA / "backups").glob("neurosearch-*.db"), reverse=True):
                if "PRE-DEDUPE" in b.name:
                    continue
                r = full_check(b)
                print(f"backup {b.name}: {'CLEAN' if r == ['ok'] else r[0][:120]}")
                if r == ["ok"]:
                    cands.append((f"backup {b.name}", b))
                    break
        if not cands:
            print("NO clean candidate found. Stop here and ask for help.")
            return 3
        label, src = cands[0]
        print(f"\nWOULD restore from: {label}")
        print(f"WOULD move damaged files to: {quarantine}/")
        if not do:
            print("(dry run -- add --yes to do it)")
            return 0
        quarantine.mkdir()
        for f in [DB, *SIDE]:
            if f.exists():
                shutil.move(str(f), str(quarantine / f.name))
        shutil.copyfile(src, DB)
        r = full_check(DB)
        print(f"installed; final full check on the new live file: {'CLEAN' if r == ['ok'] else r[:3]}")
        return 0 if r == ["ok"] else 4
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
