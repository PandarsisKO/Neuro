"""One long-running tool at a time, per name.

WHY THIS EXISTS. On 2026-09-20 three `rescore_candidates.py` runs were started against the same project in
separate Terminal tabs. Each enforced its own `--budget` correctly and each was therefore wrong about the total:
the ceiling the user thought they had set was multiplied by the number of tabs, and the three runs interleaved
writes to the same `candidate_projects` rows. `backfill_descriptions.py` had the same shape -- concurrent runs
spend the same 10,000-unit daily YouTube quota against overlapping work.

The fix is deliberately the crudest one that cannot itself fail open in a dangerous direction: an exclusive
`flock` held for the life of the process. The lock is released by the kernel when the process dies for ANY
reason -- Ctrl-C, a crash, a closed Terminal window -- so there is no stale-lock class of bug and no cleanup
step a user has to know about. It is advisory and process-local by design: it does NOT protect the database
(SQLite does that) and it makes no claim about anything started outside these tools.

The file lives beside the database so that two checkouts pointed at the same data still see each other, which
is the case that actually bit. It is opened and flock'd, never read as data by anything that matters, and never
touches the database file itself -- consistent with the standing rule that only the app, the CLI, or a verified
backup may open `neurosearch.db`.
"""
from __future__ import annotations

import fcntl
import os
import sys
import time
from pathlib import Path


class Busy(RuntimeError):
    """Another run of the same tool holds the lock. Carries the holder's own description of itself."""

    def __init__(self, name: str, holder: str) -> None:
        super().__init__(f"another {name} run is already going")
        self.name, self.holder = name, holder


def acquire(name: str, *, note: str = "") -> object:
    """Take the named lock, or raise Busy. Returns the open file object, which the CALLER must keep alive --
    letting it be garbage-collected closes the descriptor and drops the lock."""
    from neurosearch.config import settings
    d = Path(settings.data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f".{name}.lock"
    fh = open(path, "a+")                      # a+ never truncates, so a failed attempt cannot erase the holder
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.seek(0)
        holder = (fh.read() or "").strip() or "(the other run did not record who it is)"
        fh.close()
        raise Busy(name, holder) from None
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
             f"  {' '.join(sys.argv)}\n" + (f"  {note}\n" if note else ""))
    fh.flush()
    return fh


def guard(name: str, *, note: str = "", ignore: bool = False) -> object | None:
    """`acquire`, but it prints the holder and exits 2 rather than raising -- the shape a CLI main() wants.
    `ignore` is the escape hatch for someone who knows the other run is wedged; it is never the default, and it
    says out loud that the budget ceiling no longer means what it says."""
    if ignore:
        print("--ignore-lock: not checking for other runs. Any --budget or quota ceiling now applies PER RUN,\n"
              "               not in total, and concurrent runs will interleave writes to the same rows.\n")
        return None
    try:
        return acquire(name, note=note)
    except Busy as e:
        print(f"REFUSING: {e}\n\nthe run that holds the lock:\n  {e.holder}\n\n"
              "Wait for it to finish, or stop it with Ctrl-C in its own window (the lock frees itself the moment\n"
              "that process exits -- there is nothing to clean up). Every budget and quota ceiling these tools\n"
              "take is per-run, so two at once spends twice what you asked for.", file=sys.stderr)
        raise SystemExit(2)
