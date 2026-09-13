# fts5 corruption report, 2026-09-12 — evidence, hypotheses, and what was changed

Written by Claude for Codex. Nothing here is a conclusion you have to accept; it is the evidence I could gather
without opening the live database, the reasoning I applied, and the bounded mitigation. The mmap reversal and the
recovery seam are tracked in `neurosearch/db.py`, `neurosearch/api.py`, and `HARDENING.md`; the observational R8
hypotheses remain open.

## 1. What happened, as fact

The live database reported the same fts5 error three times, from the hourly `_backup_loop` integrity check:

```
2026-09-12 13:43:17,980 ERROR neurosearch.jobs: DATABASE INTEGRITY CHECK FAILED:
  {'ok': False, 'result': 'fts5: corruption found reading blob 824633720836 from table "chunks_fts"',
   'foreign_key_violations': 0, 'seconds': 0.36}
2026-09-12 14:44:48,656  — identical, same blob id, 0.4 s
2026-09-12 15:44:50,679  — identical, same blob id, 0.4 s
```

Facts, all from `data/server.log`:

- **Same blob id every time** (824633720836) and **zero foreign-key violations** on all three.
- **The app logged nothing at all between 09:32 and 13:43.** Four hourly backups were missed. The snapshot
  cadence is continuous before and after: `08:25:49, 08:41:37, 08:48:35, [gap], 13:44:48, 14:44:50, 15:44:52`.
  The machine was asleep or otherwise suspended for about 4h11m.
- **The first integrity check after that gap is the one that failed.** The check at 08:48:35 passed — it logs only
  on failure, and its backup line is present with no preceding ERROR.
- **The night before was continuous**: hourly snapshots from 00:32 through 08:25, no gaps, no failures.
- **Every backup verified clean throughout**, including those taken immediately after each failed check.
  `db.verify_database` opens its own `mode=ro` connection and runs `quick_check`; that connection never sets
  `mmap_size`.
- **The server stopped at about 15:45** with no shutdown record, no traceback and no signal in the log. I could not
  determine whether that was a crash, a closed Terminal window, or sleep — macOS crash reports are outside the
  connected folder. `restart.command` at 16:17 reported "nothing was holding port 8000", so the process was
  genuinely gone rather than hung.
- **After the restart the integrity check passes.** No repair ran; nothing rebuilt the index.
- Unrelated but in the same window: local Claude Code was timing out at 300 s repeatedly before the stop
  (`LOCAL_UNAVAILABLE after 1 attempt: claude code timeout`) and answers in about 6 s after it.

## 2. What the error means

`fts5: corruption found reading blob %lld from table "%s"` comes from SQLite's fts5 module, not the pager. It
fires when fts5 reads a segment or leaf blob whose content does not match what its index says should be there.

Since SQLite 3.44 the integrity pragmas call `xIntegrity` on virtual tables, so this check really does walk the
fts5 index rather than only the b-trees underneath it. **Open question I could not answer: which SQLite version
the Mac's Python 3.14 links against.** Worth confirming — it changes how much the check actually covers.

Note that `quick_check` is the weaker pragma. I ran a full `PRAGMA integrity_check` against a copied, non-live backup
(`data_backup_2026-09-03/neurosearch.db` copied to `/tmp/neuro-fts-integrity-copy.db`) on 2026-09-12: **`ok` in
0.381 s**. This proves that backup is consistent on disk; it does not prove the live file or transient read path was
healthy during the incident.

The Mac Python 3.14 build links SQLite **3.53.4**, with `ENABLE_FTS5` and `DEFAULT_MMAP_SIZE=0`. That is new enough
for integrity pragmas to invoke virtual-table integrity checks, so the copied-backup result includes FTS5's own
consistency walk.

## 3. Hypotheses

The constraint that matters: **the failure appeared and disappeared without any write to `chunks_fts` in
between.** Nothing ingested, re-embedded or rebuilt. Between 09:32 and 13:43 the app did nothing at all; between
13:43 and the restart it ran findings jobs, which write `project_notes`, not `chunks`. So whatever changed was in
how pages were *read*, not what was on disk — or the restart changed which bytes a read resolves to.

**H1 — a stale memory-mapped page across sleep/wake.** R8 (0.63.36, commit `99849d1`) set
`PRAGMA mmap_size=1024*1024*1024`. The database is 689 MB, so effectively all of it is mapped. If a mapped page is
served stale after a wake, fts5 reads a blob that does not match its index and reports exactly this. Fits: one
specific page, structure intact, a fresh process clean, and the backup path — a separate connection with no mmap —
never affected.

Against H1: a correctly behaving mmap should re-fault clean pages from the file after they are discarded. For this
to be the mechanism the mapping has to survive sleep in a state that is neither valid nor re-faulted. I cannot
demonstrate that from logs.

**H2 — a stale or inconsistent `-shm` (WAL index).** In WAL mode the `-shm` file is *always* memory-mapped,
regardless of `mmap_size`. It tells a reader which WAL frame holds the current version of a page. If it goes
stale, a reader resolves a page to the wrong frame and reads an older or unrelated version — again exactly this
error, with the files themselves fine. The WAL was 27 MB and uncheckpointed at the time. A restart rebuilds the
`-shm` from the WAL, which explains the clean result afterwards without anything being repaired.

**H2 is at least as plausible as H1, and `mmap_size=0` does not address it.** CLAUDE.md already documents this
family of problem from another angle: a session reaching the folder through a bridge mount does not see the
server's POSIX locks and can truncate `-shm` underneath it, which killed the server twice on 2026-09-11. I did not
open the database from my side in this session — I only read `data/server.log` and `stat`-ed the db files — but
`-shm` is the component I would look at next if this recurs.

**H3 — the unclean worker drains.** At 08:41 and 08:48 uvicorn reloaded (your saves to `resources.py`,
`bootstrap.py`, `index.html`) and both shutdowns logged `worker drain exceeded shutdown timeout … Worker shutdown
incomplete: ns-worker-local-ai-0` — a worker thread still running as the process was replaced. **Ruled out as the
immediate cause**, because the integrity check at 08:48:35 passed after both. Still a standing hazard: a reload
can kill a worker mid-transaction.

**H4 — real on-disk damage.** Weakest. Nothing rebuilt the index, yet it reads clean now.

## 4. What I changed, and why

`neurosearch/db.py`: `SQLITE_MMAP_BYTES = 1024 * 1024 * 1024` to `0`, with the reasoning in a comment above it.
A matching entry appended to `HARDENING.md`. The server auto-reloaded at 16:31:59 and its startup integrity check
passed.

Rationale: it removes H1's mechanism entirely, it is one line, and R8's *measured* win was the composite index
(7.87 ms to 0.43 ms on a copied backup). mmap was bundled into that rung and never isolated, so no recorded
benefit is given up. This is a deliberate partial reversal of R8, not an accident.

**This is not a proof and I want to be explicit about that.** The evidence is correlational: the first long sleep
since mmap was enabled produced the first corruption report. The observational test is whether it recurs across
sleeps with mmap at 0. If it does, H1 is wrong, the line costs nothing to restore, and H2 becomes the live
suspect.

## 5. Why it is worth attention at all

The instinct is to treat this as a noisy integrity check. It is not, for one reason: **a page that can be served to
`quick_check` can be served to a query.** `search.py` is FTS5 plus embeddings plus RRF, and search feeds findings
and chat citations. Under either H1 or H2 the same stale read that produced the error could have produced a wrong
or missing keyword result with nothing logged. For two hours on 2026-09-12 retrieval may have been degraded and
there is no way to tell after the fact.

## 6. Suggested follow-ups, in order of value

1. **Run a full `PRAGMA integrity_check` on a copied verified backup** (never in place). It is the only way to know
   whether the fts5 index is actually consistent on disk; `quick_check` cannot answer it.
2. **Confirm the SQLite version** the Mac's Python links against, so we know what the integrity pragmas cover.
3. **Recovery path — closed 2026-09-13.** `db.rebuild_fts5()` now runs the remedy statement,
   `INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')`, inside the app's serialized `BEGIN IMMEDIATE` writer
   transaction, follows it with a full `PRAGMA integrity_check`, and records the result in `db:last_fts_rebuild`.
   The authenticated `POST /api/maintenance/fts5/rebuild` route requires `{"confirm": true}` so a passive health read
   can never rewrite the index. `tests/test_s52_fts5_recovery.py` holds this contract.
4. **Surface it properly.** Health shows a red "Database integrity" line with the result, which is correct but
   passive — nobody looked for two hours. A failed integrity check is arguably an interrupt, not a status field.
5. **The reload hazard (H3)** deserves its own look: a worker surviving the shutdown timeout while the process is
   replaced is a real window for a half-finished transaction, and it happened twice in seven minutes.
