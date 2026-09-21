"""Fetch the descriptions the Candidate Index never had (HANDOFF.md, 2026-09-20).

THE FINDING. Of 11,774 candidates in Kyle's acquisition project, about 48 carry a description and none carry a
publish date; only duration is reliably present. `relevance.SYSTEM` opens by telling the model it will see "each
video's title, a snippet of its description, its length and view count" — in practice it sees a title and a
runtime. Every relevance score this project has ever computed was made on that, which is how a six-word title
became "Roofing, physical labor not remote".

THE CAUSE is not a mistake. `media.enumerate_entries` lists with `extract_flat="in_playlist"` and then reads
`e.get("description")`, which flat extraction never populates — the field is plumbed but never filled. Flat mode
is why adding a 400-video channel takes seconds instead of half an hour, so removing it is not a free fix: at
`settings.yt_delay` (4 s, randomised, one request at a time) a full metadata fetch costs ~4.4 s per video
whenever you pay it. Backfilling all 11,774 would take ~14 hours AND hold the same YouTube lock the real
ingestion jobs need.

So this hydrates the candidates about to be JUDGED rather than everything. A description helps twice over: the
ranker stops guessing from a title, and focus review stops showing "no description was stored for this item"
at the moment a human is trying to decide.

Polite by construction: it goes through `media.fetch_info`, so it shares `polite()`'s lock and spacing with
ingestion rather than racing it, and a bot-check pause stops this cleanly instead of hammering. Every result is
written as it lands, so Ctrl-C costs nothing and re-running resumes.

Run ON THE MAC:
    .venv/bin/python tools/backfill_descriptions.py --project <id> --dry-run
    .venv/bin/python tools/backfill_descriptions.py --project <id> --limit 200
"""
from __future__ import annotations

import argparse
import sys
import time


def _refuse_bridge_mount() -> None:
    import os
    cwd = os.path.realpath(os.getcwd())
    if "/sessions/" in cwd and "/mnt/" in cwd:
        sys.exit("REFUSING: run this on the Mac, not through a sandbox bridge mount (CLAUDE.md standing rule #1).")


def main() -> int:
    _refuse_bridge_mount()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--state", default="available",
                    help="which candidates to hydrate (default: available — the ones you are about to review)")
    ap.add_argument("--limit", type=int, default=200,
                    help="how many to fetch this run (default 200; seconds via the API, ~15 min via yt-dlp)")
    ap.add_argument("--no-api", action="store_true",
                    help="force the slow yt-dlp path even when a YouTube API key is configured")
    ap.add_argument("--dry-run", action="store_true", help="report coverage and what would be fetched; fetch nothing")
    ap.add_argument("--ignore-lock", action="store_true",
                    help="start even if another backfill is already running. Concurrent runs spend the same "
                         "10,000-unit daily YouTube quota on overlapping work")
    args = ap.parse_args()

    _lock = None
    if not args.dry_run:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _runlock import guard
        _lock = guard(  # noqa: F841 -- must stay referenced; closing it drops the lock
            "backfill", ignore=args.ignore_lock)

    from neurosearch import candidates as cand
    from neurosearch import db, media
    from neurosearch import youtube_api as yta
    from neurosearch.config import settings
    from neurosearch.media import RateLimited

    if not db.get_project(args.project):
        sys.exit(f"no project {args.project}")

    conn = db.connect()
    total, have = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN TRIM(COALESCE(c.description,'')) <> '' THEN 1 ELSE 0 END) "
        "FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state=?", (args.project, args.state)).fetchone()
    have = have or 0
    print(f"{args.state}: {total} candidate(s), {have} with a description ({have / max(1, total):.0%})")

    rows = conn.execute(
        "SELECT c.id, c.platform, c.external_id, c.url, c.title, cp.relevance "
        "FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state=? AND TRIM(COALESCE(c.description,'')) = '' "
        "  AND c.url LIKE 'http%' "
        "ORDER BY cp.relevance DESC",                    # best first: the ones most likely to be judged soon
        (args.project, args.state)).fetchall()
    n_missing_total = len(rows)                 # before --limit trims it, so the closing line can tell
    rows = rows[:args.limit] if args.limit else rows
    if not rows:
        print("nothing to fetch — every candidate in that state already has a description")
        return 0

    yt_rows = [r for r in rows if r["platform"] == "youtube" and r["external_id"]]
    api_on = bool(yta.available()["ready"] and not args.no_api and yt_rows)
    per = settings.yt_delay * 1.1
    # partition by candidate id: sqlite3.Row has no cheap membership test, and `in` over a list would be O(n^2)
    api_ids = {r["id"] for r in yt_rows} if api_on else set()
    slow_rows = [r for r in rows if r["id"] not in api_ids]

    if api_on:
        units = (len(yt_rows) + yta.BATCH - 1) // yta.BATCH
        print(f"YouTube Data API: {len(yt_rows)} video(s) in {units} call(s) — {units} of 10,000 daily quota units, seconds")
    else:
        print(f"YouTube Data API: off — {yta.available()['why']}")
    if slow_rows:
        print(f"yt-dlp fallback : {len(slow_rows)} at ~{per:.1f}s each — roughly {len(slow_rows) * per / 60:.0f} minute(s)")
    print("Safe to stop with Ctrl-C: results are written as they land, and re-running picks up where it left off.\n")
    if args.dry_run:
        for r in rows[:10]:
            print(f"  [{r['relevance'] if r['relevance'] is not None else '  '}] {(r['title'] or '')[:66]}")
        print("\n--dry-run: nothing fetched, nothing written.")
        return 0

    got = failed = 0
    if api_on:
        # 50 ids per quota unit. Written per batch, so a Ctrl-C or a quota wall keeps everything already fetched.
        by_id = {r["external_id"]: r for r in yt_rows}
        ids = list(by_id)
        for b in range(0, len(ids), yta.BATCH):
            chunk = ids[b:b + yta.BATCH]
            try:
                found = yta.videos(chunk)
            except yta.YouTubeApiUnavailable as e:
                print(f"  API stopped ({e.reason}): {e.detail}")
                print(f"  {got} saved so far. The rest can be fetched with --no-api, or tomorrow when quota resets.")
                slow_rows = []          # do not silently fall through to a 14-hour job the user did not ask for
                break
            for vid, f in found.items():
                r = by_id[vid]
                cand.remember([{"external_id": vid, "url": r["url"], "title": f.get("title") or r["title"],
                                "description": f.get("description"), "published_at": f.get("published_at"),
                                "duration": f.get("duration"), "view_count": f.get("view_count"),
                                "creator": f.get("creator")}],
                              "youtube", None, {"kind": "backfill", "title": "description backfill (api)"})
                got += 1 if f.get("description") else 0
            missing = len(chunk) - len(found)
            failed += missing
            print(f"  api call {b // yta.BATCH + 1}/{(len(ids) + yta.BATCH - 1) // yta.BATCH}: "
                  f"{len(found)}/{len(chunk)} returned, {got} descriptions saved"
                  + (f", {missing} unavailable (deleted/private)" if missing else ""), flush=True)
        print(f"  quota used this run: {yta.quota_spent()['units']} unit(s)\n")

    t0 = time.time()
    for i, r in enumerate(slow_rows, start=1):
        try:
            info = media.fetch_info(r["url"])
        except Exception as e:  # noqa: BLE001
            if isinstance(e, RateLimited):
                print(f"\n{e}\nStopping here — {got} saved. Re-run later to continue.")
                break
            failed += 1
            print(f"  [{i}/{len(slow_rows)}] failed: {(r['title'] or '')[:44]} — {type(e).__name__}", flush=True)
            continue
        if not info:
            failed += 1
            continue
        f = media.info_to_source_fields(info, r["platform"])
        desc = (f.get("description") or "").strip()
        # remember() fills EMPTY fields only and is the Candidate Index's one idempotent write path, so this
        # cannot clobber anything already known; project_id=None keeps it to the global row, where a description
        # benefits every project that has ever seen this video.
        cand.remember([{"external_id": r["external_id"], "url": r["url"], "title": f.get("title") or r["title"],
                      "description": desc or None, "published_at": f.get("published_at"),
                      "duration": f.get("duration"), "view_count": info.get("view_count"),
                      "creator": f.get("channel")}],
                    r["platform"], None, {"kind": "backfill", "title": "description backfill"})
        got += 1 if desc else 0
        if i % 10 == 0 or i == len(slow_rows):
            rate = (time.time() - t0) / i
            print(f"  [{i}/{len(slow_rows)}] {got} descriptions saved, {failed} failed "
                  f"— {rate:.1f}s each, ~{(len(slow_rows) - i) * rate / 60:.0f} min left", flush=True)

    total2, have2 = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN TRIM(COALESCE(c.description,'')) <> '' THEN 1 ELSE 0 END) "
        "FROM candidate_projects cp JOIN candidates c ON c.id = cp.candidate_id "
        "WHERE cp.project_id=? AND cp.state=?", (args.project, args.state)).fetchone()
    print(f"\n{args.state}: {have2 or 0} of {total2} now have a description "
          f"(was {have}) — {failed} fetch(es) failed")
    unattempted = max(0, n_missing_total - len(rows))
    still_empty = total2 - (have2 or 0)
    if unattempted:
        print(f"{unattempted} were not reached by --limit {args.limit}. Run it again for the next batch.")
    elif still_empty:
        # Everything selected WAS attempted, so whatever is still blank has none at the source. Saying "run it
        # again" here would re-fetch those every time for nothing — a completion message that makes a finished
        # job look unfinished is the same defect as a silent truncation, pointing the other way.
        print(f"{still_empty} still have none — all of them were fetched, so those videos simply have no "
              f"description on YouTube (common for Shorts). Re-running will not change that.")
    else:
        print("Every candidate in that state now has a description.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
