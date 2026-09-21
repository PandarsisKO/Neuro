"""Re-score an existing candidate backlog under the corrected ranking prompt (HANDOFF.md, 2026-09-20).

WHY. A blind review of 30 candidates the relevance filter had rejected found Kyle would have kept 23 of them --
77%, against a 25% bar set before the run. The band table showed the loss was not near the cutoff but spread
across the whole range (100% at 35-44, 90% at 20-34, still 40% at 0-19), which is the signature of a score that
is measuring the wrong thing rather than a threshold in the wrong place. The model's own reasons said what:
"not remote", "size mismatch", "physical not online", "built it instead of buying it" -- it was checking each
video's SUBJECT BUSINESS against Kyle's buy-box, because `db.project_steering` hands the ranker a brief written
as acquisition requirements. `relevance.SYSTEM` now separates the outcome he wants from the content that teaches
him to get there.

That fix only changes FUTURE scoring. This re-scores what is already on record.

Every score written here comes from a real model call, so this costs real money -- roughly one call per 80
candidates. `--budget` is a hard ceiling checked BEFORE each call, and `--dry-run` shows the cost and the sample
without spending anything.

Nothing moves state by default. Scoring and deciding are deliberately separate: `--resurface` is what promotes
anything that now clears the cutoff back to `available`, and it is opt-in so the new numbers can be read first.

Run ON THE MAC:
    .venv/bin/python tools/rescore_candidates.py --project <id> --dry-run
    .venv/bin/python tools/rescore_candidates.py --project <id> --budget 5
    .venv/bin/python tools/rescore_candidates.py --project <id> --budget 5 --resurface
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

PER_CALL_USD = 0.02          # relevance._call's own guard_estimate, one call per BATCH candidates


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--state", default="skipped_low_relevance",
                    help="which candidates to re-score (default: the ones the old prompt rejected)")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many candidates (0 = all)")
    ap.add_argument("--order", choices=("best", "worst", "spread"), default="best",
                    help="which candidates a --limit slice takes. best: the highest old scores (the most likely "
                         "false rejections). worst: the lowest (does real noise STAY down?). spread: evenly "
                         "across the whole range, which is the only slice that answers both at once")
    ap.add_argument("--min-old-score", type=int, default=None, metavar="N",
                    help="only re-score candidates whose OLD score was at least N. The spread sample showed the "
                         "yield is wildly uneven: 46%% of the 20+ band clears the cutoff on a re-score against 6%% "
                         "of the 0-19 band, so `--min-old-score 20` buys most of the recovery for an eighth of "
                         "the cost and time")
    ap.add_argument("--budget", type=float, default=5.0, help="hard USD ceiling; checked before each call")
    ap.add_argument("--resurface", action="store_true",
                    help="after re-scoring, move anything that now clears the cutoff back to 'available'")
    ap.add_argument("--resurface-only", action="store_true",
                    help="make NO model calls: just promote candidates whose CURRENT score already clears the "
                         "cutoff. This is how you finish an interrupted run without paying to re-score")
    ap.add_argument("--dry-run", action="store_true", help="show cost and a sample, call nothing, write nothing")
    ap.add_argument("--ignore-lock", action="store_true",
                    help="start even if another re-score is already running. Only if you know the other one is "
                         "wedged: --budget is enforced per run, so two at once spend twice what you asked for")
    args = ap.parse_args()

    # B2: three of these were once running at once against the same project, each correctly enforcing its own
    # --budget and so collectively spending three times the stated ceiling. A --dry-run reads and prints only,
    # so it is not worth blocking; anything that can call the model or write takes the lock for its whole life.
    _lock = None
    if not args.dry_run:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _runlock import guard
        _lock = guard(  # noqa: F841 -- must stay referenced; closing it drops the lock
            "rescore", note=f"project {args.project}, budget ${args.budget:.2f}", ignore=args.ignore_lock)

    from neurosearch import candidates as cand
    from neurosearch import db, relevance
    from neurosearch.config import settings  # noqa: F401  (loads .env before any provider call)

    project = db.get_project(args.project)
    if not project:
        sys.exit(f"no project {args.project}")
    if not (project.get("brief") or project.get("goal") or project.get("questions")):
        sys.exit("this project has no brief/goal to rank against")

    if args.resurface_only:
        ready = db.connect().execute(
            "SELECT cp.candidate_id cid FROM candidate_projects cp "
            "WHERE cp.project_id=? AND cp.state=? AND cp.relevance >= ?",
            (args.project, args.state, cand.LOW_RELEVANCE)).fetchall()
        if not ready:
            print(f"nothing in {args.state!r} currently scores >= {cand.LOW_RELEVANCE}; nothing to promote")
            return 0
        if args.dry_run:
            print(f"--dry-run: {len(ready)} candidate(s) already clear the cutoff and would be promoted")
            return 0
        n = cand.mark(args.project, [r["cid"] for r in ready], "available",
                      reason=f"re-scored under the corrected ranking prompt ({relevance.prompt_version()}): "
                             f"now clears the relevance cutoff")
        print(f"moved {n} candidate(s) back to 'available' — no model calls were made")
        return 0

    rows = db.connect().execute(
        "SELECT cp.candidate_id cid, cp.relevance old_rel, cp.relevance_why old_why, c.title, c.description, "
        "       c.creator, c.duration, c.view_count "
        "FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state=? AND cp.relevance >= ? ORDER BY cp.relevance DESC",
        (args.project, args.state, args.min_old_score if args.min_old_score is not None else -1)).fetchall()
    rows_all = rows
    if args.limit and args.limit < len(rows):
        # A slice taken only off the top cannot tell a working fix from an overcorrection: the highest-scoring
        # rejects are the ones most likely to be genuine, so they SHOULD climb. Whether real noise stays down is
        # a question about the other end, and `spread` is the only slice that asks both.
        if args.order == "worst":
            rows = rows[-args.limit:]
        elif args.order == "spread":
            step = (len(rows) - 1) / (args.limit - 1) if args.limit > 1 else 1
            rows = [rows[min(len(rows) - 1, round(i * step))] for i in range(args.limit)]
        else:
            rows = rows[:args.limit]
    if not rows:
        sys.exit(f"no candidates in state {args.state!r} for this project")

    items = [{"id": r["cid"], "title": r["title"], "description": r["description"], "duration": r["duration"],
              "view_count": r["view_count"], "creator": r["creator"], "_old": r["old_rel"], "_oldwhy": r["old_why"]}
             for r in rows]
    n_calls = (len(items) + relevance.BATCH - 1) // relevance.BATCH
    est = n_calls * PER_CALL_USD

    print(f"{len(items)} candidate(s) in state {args.state!r}"
          + (f", old score >= {args.min_old_score}" if args.min_old_score is not None else "")
          + (f" — {args.order} slice of {len(rows_all)}" if args.limit and args.limit < len(rows_all) else ""))
    print(f"{n_calls} model call(s) at {relevance.BATCH} per call — estimated ${est:.2f}")
    print(f"prompt version now: {relevance.prompt_version()}", flush=True)
    if est > args.budget:
        print(f"\nthat is over --budget ${args.budget:.2f}. Raise it, or use --limit to do a slice first.")
        if not args.dry_run:
            return 1
    if args.dry_run:
        print("\n--dry-run: nothing called, nothing written. A sample of what would be re-scored:")
        for it in items[:8]:
            print(f"  [{it['_old']:>3}] {(it['title'] or '')[:64]!r} — was: {it['_oldwhy'] or '(no reason)'}")
        return 0

    mins = max(1, n_calls)
    eta = f"{mins} minute(s)" if mins < 90 else f"about {mins / 60:.1f} hours"
    print(f"\nabout a minute per call, so roughly {eta} — progress prints as each lands. Safe to stop with "
          f"Ctrl-C: every batch is written as it completes.\n", flush=True)
    head = relevance._head(project, None)
    updates: list[tuple[str, int, str]] = []
    spent = 0.0
    for b in range(0, len(items), relevance.BATCH):
        if spent + PER_CALL_USD > args.budget:
            print(f"stopping before call {b // relevance.BATCH + 1}: would exceed --budget ${args.budget:.2f}")
            break
        batch = items[b:b + relevance.BATCH]
        # Say the call has STARTED, before waiting on it. A batch of 80 titles takes about a minute, and a tool
        # that prints nothing for that minute is indistinguishable from one that has hung -- the same defect
        # this codebase already fixed once on the buttons ("I click a button and the button doesnt respond for
        # 1-5 seconds and I think something is broken"). flush because stdout is block-buffered off a terminal.
        t0 = time.time()
        print(f"  call {b // relevance.BATCH + 1}/{n_calls}: scoring {len(batch)} candidates…", end="", flush=True)
        try:
            res = relevance._call(relevance.SYSTEM, relevance._user(batch), args.project, "rescore", head=head)
        except Exception as e:  # noqa: BLE001
            print(f"\n  call {b // relevance.BATCH + 1} failed: {type(e).__name__}: {e}", flush=True)
            break
        spent += PER_CALL_USD
        got: list[tuple[str, int, str]] = []
        for it in res.get("scores") or []:
            try:
                i, sc = int(it.get("i")), max(0, min(100, int(it.get("score", 0))))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(batch):
                got.append((batch[i]["id"], sc, str(it.get("why") or "")))
                batch[i]["_new"] = sc
        # Persist THIS batch before going round again. `relevance.rank_collection` already learned this the hard
        # way ("so yielding (or dying) never loses a paid call") and a 117-call run is exactly where it matters:
        # buffering to the end means one Ctrl-C two hours in throws away every dollar already spent.
        cand.rescore(args.project, got)
        updates.extend(got)
        print(f"  scored {len(got)}/{len(batch)} in {time.time() - t0:.0f}s — spent ~${spent:.2f} "
              f"(saved)", flush=True)

    if not updates:
        print("nothing was scored; nothing written")
        return 1

    print(f"\nwrote {len(updates)} new score(s) (saved batch by batch as the run went)")

    scored = [it for it in items if "_new" in it]
    # `... >= LOW_RELEVANCE > (it["_old"] or 0)` was wrong: it also required the OLD score to be under the
    # cutoff, so anything already scoring >=50 from an EARLIER re-score that was never resurfaced stayed stuck
    # in skipped_low_relevance forever — 632 cleared the cutoff on the 2026-09-20 full run and only 310 were
    # promoted, because 322 had already been lifted by a previous slice. What matters is where an item stands
    # NOW and that it is still sitting in a skipped state, which is the condition `--resurface-only` already used.
    moved_up = [it for it in scored if it["_new"] >= cand.LOW_RELEVANCE]
    band = Counter("clears the cutoff now" if it["_new"] >= cand.LOW_RELEVANCE else "still under" for it in scored)
    print(f"  {band['clears the cutoff now']} of {len(scored)} now score >= {cand.LOW_RELEVANCE} "
          f"({band['still under']} still under)")
    # split by where each item started: a fix should lift what was wrongly rejected and leave real noise alone
    lo = [it for it in scored if (it["_old"] or 0) < 20]
    hi = [it for it in scored if (it["_old"] or 0) >= 20]
    if lo and hi:
        lo_up = sum(1 for it in lo if it["_new"] >= cand.LOW_RELEVANCE)
        hi_up = sum(1 for it in hi if it["_new"] >= cand.LOW_RELEVANCE)
        print(f"  of those the old prompt scored 0-19:  {lo_up}/{len(lo)} now clear the cutoff "
              f"({lo_up / len(lo):.0%}) — high here would mean OVERCORRECTION")
        print(f"  of those it scored 20+:               {hi_up}/{len(hi)} now clear ({hi_up / len(hi):.0%})")
    if lo:
        print("\n  lowest-scored items, to eyeball whether real noise stayed down:")
        for it in sorted(lo, key=lambda x: -(x["_new"]))[:6]:
            print(f"    {it['_old'] or 0:>3} -> {it['_new']:>3}  {(it['title'] or '')[:54]!r}")
    if scored:
        avg_old = sum((it["_old"] or 0) for it in scored) / len(scored)
        avg_new = sum(it["_new"] for it in scored) / len(scored)
        print(f"  average score {avg_old:.1f} -> {avg_new:.1f}")
    print("\nbiggest changes:")
    for it in sorted(scored, key=lambda x: -(x["_new"] - (x["_old"] or 0)))[:12]:
        print(f"  {it['_old'] or 0:>3} -> {it['_new']:>3}  {(it['title'] or '')[:58]!r} — {it.get('creator') or ''}")

    if not args.resurface:
        print(f"\n{len(moved_up)} candidate(s) would come back into review. Nothing was moved — re-run with "
              f"--resurface to promote them to 'available'.")
        return 0

    if moved_up:
        n = cand.mark(args.project, [it["id"] for it in moved_up], "available",
                      reason=f"re-scored {time.strftime('%Y-%m-%d')} under the corrected ranking prompt "
                             f"({relevance.prompt_version()}): now clears the relevance cutoff")
        print(f"\nmoved {n} candidate(s) back to 'available' — visible again in Sources > Seen, not added")
    else:
        print("\nnothing cleared the cutoff; nothing moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
