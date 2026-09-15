"""Clean the two legacy consistency issues db.integrity_check() counts (both root-caused and fixed at the source on
2026-09-14; these are the leftover rows from before the fixes, dating from 2026-09-09/10):

  1. duplicate claim_evidence rows -- same (claim_id, source_id, source_revision, locator, relation) more than once.
     Fix: keep the OLDEST row of each group (lowest id), delete the rest. Nothing references the duplicates
     (claim_evidence.derivative_of was checked before this was written).
  2. project_claims.origin_note_id pointing at a note that no longer exists. A Claim must survive its origin
     note's deletion (that is why there is no FK); the honest value for a dead pointer is NULL. Every reader of
     origin_note_id already handles NULL (claims.py `.get(... or -1)`, JOINs, NOT IN).

Run ON THE MAC with serve and worker stopped:

    .venv/bin/python tools/db_cleanup_legacy.py          # dry run: counts only, changes nothing
    .venv/bin/python tools/db_cleanup_legacy.py --yes    # do it, inside one transaction, then re-count

Refuses to touch a database that does not pass a full PRAGMA integrity_check first.
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "neurosearch.db"

DUP_GROUPS = """SELECT claim_id, source_id, source_revision, locator, relation, MIN(id) keep, COUNT(*) n
                FROM claim_evidence GROUP BY claim_id, source_id, source_revision, locator, relation HAVING n > 1"""
DANGLING = """SELECT COUNT(*) FROM project_claims c WHERE c.origin_note_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM project_notes n WHERE n.id = c.origin_note_id)"""


def _refuse_bridge_mount() -> None:
    real = str(DB.resolve())
    if "/sessions/" in real and "/mnt/" in real:
        sys.exit(f"REFUSING: {real} is the live database seen through a sandbox bridge mount. Run this on the Mac "
                 "(CLAUDE.md standing rule #1).")


def main() -> int:
    _refuse_bridge_mount()
    do = "--yes" in sys.argv
    conn = sqlite3.connect(str(DB), timeout=60)
    ic = [r[0] for r in conn.execute("PRAGMA integrity_check").fetchall()]
    if ic != ["ok"]:
        print("REFUSING: database is not clean:", ic[:3])
        return 2
    groups = conn.execute(DUP_GROUPS).fetchall()
    extra_rows = sum(g[6] - 1 for g in groups)
    dangling = conn.execute(DANGLING).fetchone()[0]
    print(f"duplicate claim_evidence groups: {len(groups)} ({extra_rows} extra row(s) to delete)")
    print(f"dangling origin_note_id: {dangling} claim(s) to set NULL")
    if not do:
        print("(dry run -- add --yes to apply)")
        return 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        deleted = 0
        for claim_id, source_id, rev, locator, relation, keep, n in groups:
            cur = conn.execute("DELETE FROM claim_evidence WHERE claim_id=? AND source_id=? AND source_revision IS ? "
                               "AND locator IS ? AND relation IS ? AND id <> ?", (claim_id, source_id, rev, locator, relation, keep))
            deleted += cur.rowcount
        nulled = conn.execute("UPDATE project_claims SET origin_note_id = NULL WHERE origin_note_id IS NOT NULL "
                              "AND NOT EXISTS (SELECT 1 FROM project_notes n WHERE n.id = project_claims.origin_note_id)").rowcount
        conn.commit()
    except Exception as e:  # noqa: BLE001
        conn.rollback()
        print("ROLLED BACK:", e)
        return 3
    print(f"deleted {deleted} duplicate evidence row(s); nulled {nulled} dead origin pointer(s)")
    print("after: duplicate groups =", len(conn.execute(DUP_GROUPS).fetchall()), "| dangling =", conn.execute(DANGLING).fetchone()[0])
    print("integrity_check:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
