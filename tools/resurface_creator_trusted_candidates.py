"""One-time backlog fix for the 2026-09-20 creator-trust cliff fix (see HANDOFF.md, neurosearch/ingest.py's
approve_proposed). The code fix only changes FUTURE review decisions; this recovers candidates that were
already filed as skipped_low_relevance before the fix existed, using the exact same rule: a creator this
project has already kept at least one source from gets DISPOSITION_MAX_ADJUST added to a borderline score
before the cutoff is re-applied.

Non-destructive and reversible: moves matching rows from skipped_low_relevance to available (candidates.mark),
the same state candidates.py already uses for resurfacing elsewhere (e.g. knowledge.pursue). Nothing is
auto-added to your real sources -- these just become visible again in Sources -> Seen, not added / the pool,
for you to judge yourself, same as any other candidate. Re-running is safe and idempotent: it only ever touches
rows still sitting in skipped_low_relevance, so a second run after the first just finds nothing left to do.

Run ON THE MAC:
    .venv/bin/python tools/resurface_creator_trusted_candidates.py --project <id> --dry-run
    .venv/bin/python tools/resurface_creator_trusted_candidates.py --project <id>
"""
from __future__ import annotations

import argparse
import sys


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def main() -> None:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="project id (see `neurosearch project list`)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    from neurosearch import candidates as cand
    from neurosearch import db

    pid = args.project
    proj = db.get_project(pid)
    if not proj:
        sys.exit(f"no project {pid}")

    disp = cand.creator_disposition(pid)
    trusted_creators = {c for c, d in disp.items() if int(d.get("pos", 0)) > 0}
    if not trusted_creators:
        print("no creators in this project have any acquired sources yet -- nothing to rescue")
        return

    conn = db.connect()
    rows = conn.execute(
        "SELECT cp.candidate_id, c.creator, c.title, cp.relevance FROM candidate_projects cp "
        "JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state='skipped_low_relevance' AND cp.relevance IS NOT NULL",
        (pid,)).fetchall()

    threshold = cand.LOW_RELEVANCE - cand.DISPOSITION_MAX_ADJUST
    rescued = [r for r in rows if r["creator"] and r["creator"].strip() in trusted_creators and r["relevance"] >= threshold]

    print(f"{len(rows)} skipped_low_relevance candidates total in this project")
    print(f"{len(rescued)} qualify for rescue (creator already has >=1 kept source in this project, AND "
          f"relevance >= {threshold} [{cand.LOW_RELEVANCE} cutoff - {cand.DISPOSITION_MAX_ADJUST} creator-trust nudge])")

    by_creator: dict[str, list] = {}
    for r in rescued:
        by_creator.setdefault(r["creator"].strip(), []).append(r)
    for creator, items in sorted(by_creator.items(), key=lambda kv: -len(kv[1])):
        scores = sorted(set(i["relevance"] for i in items))
        print(f"  {creator}: {len(items)} candidate(s), scores {scores}")

    if args.dry_run:
        print("--dry-run: nothing written. Re-run without --dry-run to actually move these to 'available'.")
        return

    if not rescued:
        print("nothing to write")
        return

    ids = [r["candidate_id"] for r in rescued]
    n = cand.mark(pid, ids, "available",
                  reason="resurfaced 2026-09-20: creator already has kept sources in this project; this "
                         "candidate's score would have cleared the cutoff with the same creator-trust "
                         "adjustment now applied at review time (see HANDOFF.md)")
    print(f"moved {n} candidate(s) from skipped_low_relevance to 'available' -- visible again in "
          f"Sources > Seen, not added, and the discovery pool")


if __name__ == "__main__":
    main()
