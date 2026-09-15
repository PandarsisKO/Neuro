"""Full SQLite integrity check of the live database, with an opt-in index repair.

Run this ON THE MAC that hosts the database (never from a sandbox or another machine -- SQLite's WAL mode is only
coherent between processes on one host):

    .venv/bin/python tools/db_check.py            # diagnose only: full PRAGMA integrity_check (quick_check skips indexes)
    .venv/bin/python tools/db_check.py --repair   # if EVERY reported problem is an index inconsistency: REINDEX, then re-check

Stop `neurosearch serve` and `neurosearch worker` before --repair. Never modifies anything unless --repair is given,
and even then refuses if any problem is not a plain index inconsistency (those need a restore, not a reindex).
"""
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "neurosearch.db"
INDEX_ONLY = ("missing from index", "wrong # of entries in index", "row .* missing from index", "index .* has")


def check(conn: sqlite3.Connection) -> list[str]:
    t = time.time()
    rows = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    print(f"integrity_check: {len(rows)} line(s) in {time.time() - t:.0f}s")
    for r in rows[:40]:
        print("  ", r)
    if len(rows) > 40:
        print(f"   ... {len(rows) - 40} more")
    return rows


def _refuse_bridge_mount() -> None:
    real = str(DB.resolve())
    if "/sessions/" in real and "/mnt/" in real:
        sys.exit(f"REFUSING: {real} is the live database seen through a sandbox bridge mount. Run this on the Mac "
                 "(CLAUDE.md standing rule #1: opening the live WAL database from another VM crashes the app and corrupts the file).")


def main() -> int:
    _refuse_bridge_mount()
    if not DB.exists():
        print(f"no database at {DB}")
        return 2
    repair = "--repair" in sys.argv
    conn = sqlite3.connect(str(DB), timeout=60)
    print(f"database: {DB} ({DB.stat().st_size / 1e6:.0f} MB)")
    print("quick_check:", conn.execute("PRAGMA quick_check").fetchone()[0])
    rows = check(conn)
    if rows == ["ok"]:
        print("RESULT: clean")
        return 0
    index_only = all(("index" in r) for r in rows)
    print("RESULT:", "index inconsistencies only (REINDEX repairs these, no data is lost)" if index_only
          else "NOT only index problems -- do not reindex; restore from the newest verified backup in data/backups/")
    if not repair:
        print("(diagnose only; add --repair to fix index-only problems)")
        return 1
    if not index_only:
        return 3
    t = time.time()
    conn.execute("REINDEX")
    conn.commit()
    print(f"REINDEX done in {time.time() - t:.0f}s; re-checking")
    rows = check(conn)
    print("RESULT after repair:", "clean" if rows == ["ok"] else "STILL NOT CLEAN -- restore from backup")
    return 0 if rows == ["ok"] else 4


if __name__ == "__main__":
    sys.exit(main())
