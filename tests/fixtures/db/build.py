"""Builds databases exactly as older Neuro Search versions created them (Mission A7), so the migration test can prove
`current init_db()` upgrades them without losing a row.

Usage: python tests/fixtures/db/build.py <dir-with-<version>/db.py copies>
Each old db.py is loaded as a module in isolation (its SCHEMA and MIGRATIONS are executed the way its own init_db
did), then every table is populated with representative rows using that version's column list, so anything the old
version could store is present. Output: tests/fixtures/db/neurosearch-<version>.db (committed; small).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent

SAMPLE = {   # meaningful values by column name; anything else gets a type default
    "id": None, "platform": "youtube", "external_id": "abc123def45", "url": "https://www.youtube.com/watch?v=abc123def45",
    "title": "Old video kept through migrations", "channel": "Chan", "duration": 120.0, "status": "ready", "kind": "youtube",
    "name": "Legacy project", "brief": "brief carried across versions", "text": "we talk about churn and retention tactics",
    "start": 0.0, "end": 4.0, "role": "user", "content": "what about retention? [1]", "cost": 0.0123, "ts": time.time(),
    "created_at": time.time(), "updated_at": time.time(), "tags": "[]", "citations": "[]", "payload": "{}", "result": "{}",
    "plan": "{}", "snapshot": "{}", "progress": 0.0, "message": None, "key": "k", "value": "v", "model": "claude", "chunk_index": 0,
    "source_id": "SRC1", "project_id": "PRJ1", "conversation_id": "CONV1", "collection_id": "COL1", "plan_id": "PLAN1", "note_id": "N1",
    "input_tokens": 100, "output_tokens": 10, "seconds": 0.0, "n": 0, "position": 0, "importance": 3, "transcript_kind": "captions",
    "chapters": "[]", "segments": "[]", "language": "en", "description": "d", "thumbnail_url": None, "published_at": "2025-01-01",
    "channel_url": None, "error": None, "embedding": None, "item_key": "first_steps.0", "status_note": None, "section": "s",
    "previous": "p", "proposed": "q", "reason": "r", "gist": "g", "why": "w", "angle": "a", "fit": 4, "depth": "beginner",
    "context": None, "mode": "research", "goal": None, "audience": None, "output_pref": None, "source_prefs": None, "questions": "[]",
    "summary": None, "substance": None, "suggested_at": None, "not_before": None, "relevance": None, "relevance_why": None, "view_count": None,
    "origin": "user", "verified": 0, "note": "", "refine": None, "start_with": "[]", "version": 1, "cache_read": 0, "cache_write": 0, "saved": 0.0,
}
IDS = {"sources": "SRC1", "projects": "PRJ1", "conversations": "CONV1", "collections": "COL1", "plans": "PLAN1", "project_notes": "N1",
       "jobs": "JOB1", "messages": "MSG1", "discoveries": "D1", "project_facts": "FACT1", "plan_updates": "PU1"}


def load_old(path: Path) -> tuple[str, list[str]]:
    src = path.read_text()
    m = re.search(r'^SCHEMA\s*=\s*"""(.*?)"""', src, re.S | re.M)
    if not m:
        raise SystemExit(f"no SCHEMA in {path}")
    migs = re.findall(r'\(\s*"[a-z_]+",\s*"[a-z_]+",\s*"(ALTER TABLE [^"]+)"\s*\)', src)
    return m.group(1), migs


def build(version: str, dbpy: Path) -> Path:
    out = HERE / f"neurosearch-{version}.db"
    out.unlink(missing_ok=True)
    schema, migs = load_old(dbpy)
    conn = sqlite3.connect(str(out))
    conn.executescript(schema)
    for sql in migs:
        table = sql.split()[2]
        col = sql.split("ADD COLUMN")[1].split()[0]
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(sql)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%' AND name NOT LIKE '%_config' AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' AND name NOT LIKE '%_docsize' AND name NOT LIKE '%_content'")]
    for t in tables:
        info = conn.execute(f"PRAGMA table_info({t})").fetchall()
        row = {}
        for _cid, name, ctype, notnull, default, pk in info:
            if name == "id":
                row[name] = IDS.get(t, 1) if "INT" not in (ctype or "").upper() else None
                if row[name] is None:
                    del row[name]
                continue
            v = SAMPLE.get(name, ...)
            if v is ...:
                v = 0 if "INT" in (ctype or "").upper() or "REAL" in (ctype or "").upper() else "x"
            if v is None and notnull and default is None:
                v = 0 if "INT" in (ctype or "").upper() or "REAL" in (ctype or "").upper() else "x"
            if v is not None:
                row[name] = v
        try:
            conn.execute(f"INSERT OR IGNORE INTO {t} ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
        except sqlite3.Error as e:
            print(f"  {version}: could not populate {t}: {e}")
    conn.commit()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    conn.execute("VACUUM")
    conn.close()
    (HERE / f"neurosearch-{version}.json").write_text(json.dumps({"version": version, "tables": counts}, indent=1))
    print(version, "→", out.name, counts)
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for d in sorted(root.iterdir()):
        if (d / "db.py").exists():
            build(d.name, d / "db.py")
