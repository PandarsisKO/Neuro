"""SQLite storage: sources, segments, chunks (+FTS5), collections, jobs.

One database file, WAL mode, safe for a single app process with a few worker threads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,
    platform        TEXT NOT NULL,            -- youtube | instagram | podcast | file | web
    external_id     TEXT,
    url             TEXT NOT NULL,
    title           TEXT,
    channel         TEXT,
    channel_url     TEXT,
    published_at    TEXT,                     -- ISO date
    duration        REAL,                     -- seconds
    description     TEXT,
    thumbnail_url   TEXT,
    language        TEXT,
    transcript_kind TEXT,                     -- captions | transcribed | manual
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed | skipped
    error           TEXT,
    tags            TEXT,                     -- JSON list
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_sources_platform_ext ON sources(platform, external_id);
CREATE INDEX IF NOT EXISTS ix_sources_status ON sources(status);

CREATE TABLE IF NOT EXISTS segments (
    id        INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    idx       INTEGER NOT NULL,
    start     REAL NOT NULL,
    end       REAL NOT NULL,
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segments_source ON segments(source_id, idx);

CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    idx       INTEGER NOT NULL,
    start     REAL NOT NULL,
    end       REAL NOT NULL,
    text      TEXT NOT NULL,
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS ix_chunks_source ON chunks(source_id, idx);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS collections (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,   -- playlist | channel | manual
    url         TEXT,
    title       TEXT,
    external_id TEXT,
    created_at  REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_collections_ext ON collections(kind, external_id);

CREATE TABLE IF NOT EXISTS source_collections (
    source_id     TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, collection_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,          -- ingest_url | ingest_source | reembed
    payload     TEXT NOT NULL,          -- JSON
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued | running | done | failed
    progress    REAL NOT NULL DEFAULT 0,
    message     TEXT,
    result      TEXT,                   -- JSON
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    brief       TEXT,                 -- what this project is trying to find out; guides answers
    tags        TEXT,                 -- JSON list: sources carrying any of these tags are included
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS project_sources (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id  TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, source_id)
);
CREATE TABLE IF NOT EXISTS project_collections (
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, collection_id)
);
CREATE TABLE IF NOT EXISTS project_notes (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,         -- saved findings / pinned answers
    citations  TEXT,                  -- JSON
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS project_facts (
    id         INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,         -- decision | constraint | requirement | rejected | context
    content    TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'user',   -- user | assistant
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version    INTEGER NOT NULL,
    plan       TEXT NOT NULL,         -- JSON (structured plan)
    snapshot   TEXT,                  -- JSON: counts of sources/notes/messages/facts at generation time
    status     TEXT NOT NULL DEFAULT 'planning',   -- planning | started
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plans_project ON plans(project_id, version);

CREATE TABLE IF NOT EXISTS plan_items (
    id         INTEGER PRIMARY KEY,
    plan_id    TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,         -- stable key e.g. first_steps.0, phases.1.tasks.2, decisions.0, questions.3
    status     TEXT NOT NULL DEFAULT 'not_started',
    note       TEXT,
    updated_at REAL NOT NULL,
    UNIQUE(plan_id, key)
);

CREATE TABLE IF NOT EXISTS plan_updates (
    id         INTEGER PRIMARY KEY,
    plan_id    TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    section    TEXT NOT NULL,
    previous   TEXT,
    proposed   TEXT NOT NULL,
    reason     TEXT,
    status     TEXT NOT NULL DEFAULT 'pending',   -- pending | accepted | rejected
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    title      TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    citations       TEXT,   -- JSON
    created_at      REAL NOT NULL
);
"""

_local = threading.local()


def connect() -> sqlite3.Connection:
    """Thread-local connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(settings.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


MIGRATIONS = [
    ("projects", "context", "ALTER TABLE projects ADD COLUMN context TEXT"),
    ("projects", "mode", "ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT 'research'"),
]


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    for table, col, sql in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            conn.execute(sql)
    conn.commit()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("tags", "payload", "result", "citations"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    d.pop("embedding", None)
    return d


# ---------------------------------------------------------------- sources

def upsert_source(**fields: Any) -> dict[str, Any]:
    """Insert or update a source keyed on (platform, external_id). Returns the row."""
    platform, external_id = fields["platform"], fields.get("external_id")
    if "tags" in fields and not isinstance(fields["tags"], str):
        fields["tags"] = json.dumps(fields["tags"] or [])
    with tx() as conn:
        existing = None
        if external_id:
            existing = conn.execute(
                "SELECT * FROM sources WHERE platform=? AND external_id=?", (platform, external_id)
            ).fetchone()
        t = now()
        if existing:
            fields = {k: v for k, v in fields.items() if v is not None}
            fields["updated_at"] = t
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE sources SET {sets} WHERE id=?", (*fields.values(), existing["id"]))
            sid = existing["id"]
        else:
            sid = fields.get("id") or new_id()
            fields.update(id=sid, created_at=t, updated_at=t)
            cols = ", ".join(fields)
            qs = ", ".join("?" for _ in fields)
            conn.execute(f"INSERT INTO sources ({cols}) VALUES ({qs})", tuple(fields.values()))
        return row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone())  # type: ignore[return-value]


def get_source(source_id: str) -> dict[str, Any] | None:
    return row_to_dict(connect().execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())


def find_source(platform: str, external_id: str) -> dict[str, Any] | None:
    return row_to_dict(
        connect().execute("SELECT * FROM sources WHERE platform=? AND external_id=?", (platform, external_id)).fetchone()
    )


def list_sources(
    *, status: str | None = None, collection_id: str | None = None, query: str | None = None,
    limit: int = 500, offset: int = 0,
) -> list[dict[str, Any]]:
    sql = "SELECT s.* FROM sources s"
    where, args = [], []
    if collection_id:
        sql += " JOIN source_collections sc ON sc.source_id = s.id"
        where.append("sc.collection_id=?"); args.append(collection_id)
    if status:
        where.append("s.status=?"); args.append(status)
    if query:
        where.append("(s.title LIKE ? OR s.channel LIKE ?)"); args += [f"%{query}%", f"%{query}%"]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(s.published_at, '') DESC, s.created_at DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [row_to_dict(r) for r in connect().execute(sql, args).fetchall()]  # type: ignore[misc]


def set_source_status(source_id: str, status: str, error: str | None = None) -> None:
    with tx() as conn:
        conn.execute("UPDATE sources SET status=?, error=?, updated_at=? WHERE id=?", (status, error, now(), source_id))


def delete_source(source_id: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


def source_stats() -> dict[str, Any]:
    conn = connect()
    r = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(duration),0) dur, SUM(status='ready') ready, SUM(status='failed') failed, "
        "SUM(status='pending') pending FROM sources"
    ).fetchone()
    c = conn.execute("SELECT COUNT(*) n, SUM(embedding IS NOT NULL) emb FROM chunks").fetchone()
    return {
        "sources": r["n"], "ready": r["ready"] or 0, "failed": r["failed"] or 0, "pending": r["pending"] or 0,
        "total_hours": round((r["dur"] or 0) / 3600, 1), "chunks": c["n"], "chunks_embedded": c["emb"] or 0,
    }


# ------------------------------------------------------- segments / chunks

def replace_transcript(source_id: str, segments: list[dict], chunks: list[dict]) -> None:
    """Replace all segments and chunks for a source. Embeddings may be None (filled later)."""
    with tx() as conn:
        conn.execute("DELETE FROM segments WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        conn.executemany(
            "INSERT INTO segments (source_id, idx, start, end, text) VALUES (?,?,?,?,?)",
            [(source_id, i, s["start"], s["end"], s["text"]) for i, s in enumerate(segments)],
        )
        conn.executemany(
            "INSERT INTO chunks (source_id, idx, start, end, text, embedding) VALUES (?,?,?,?,?,?)",
            [
                (source_id, i, c["start"], c["end"], c["text"], _pack(c.get("embedding")))
                for i, c in enumerate(chunks)
            ],
        )


def get_segments(source_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT idx, start, end, text FROM segments WHERE source_id=? ORDER BY idx", (source_id,)
    ).fetchall()]


def get_chunks(source_id: str) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute(  # type: ignore[misc]
        "SELECT id, source_id, idx, start, end, text FROM chunks WHERE source_id=? ORDER BY idx", (source_id,)
    ).fetchall()]


def chunks_missing_embeddings(limit: int = 500) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT id, text FROM chunks WHERE embedding IS NULL LIMIT ?", (limit,)
    ).fetchall()]


def set_embeddings(pairs: list[tuple[int, np.ndarray]]) -> None:
    with tx() as conn:
        conn.executemany("UPDATE chunks SET embedding=? WHERE id=?", [(_pack(e), cid) for cid, e in pairs])


def _pack(vec: Any) -> bytes | None:
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def _unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def load_embedding_matrix(source_ids: list[str] | None = None) -> tuple[np.ndarray, list[int]]:
    """Return (matrix [n, d], chunk_ids). Fine for tens of thousands of chunks."""
    conn = connect()
    if source_ids:
        qs = ",".join("?" for _ in source_ids)
        rows = conn.execute(
            f"SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL AND source_id IN ({qs})", source_ids
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return np.zeros((0, 0), dtype=np.float32), []
    ids = [r["id"] for r in rows]
    mat = np.vstack([_unpack(r["embedding"]) for r in rows])
    return mat, ids


def get_chunks_by_ids(ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    qs = ",".join("?" for _ in ids)
    rows = connect().execute(
        f"""SELECT c.id, c.source_id, c.idx, c.start, c.end, c.text,
                   s.title, s.url, s.platform, s.channel, s.published_at, s.external_id
            FROM chunks c JOIN sources s ON s.id = c.source_id WHERE c.id IN ({qs})""", ids
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def fts_search(query: str, limit: int = 40, source_ids: list[str] | None = None) -> list[tuple[int, float]]:
    """Full-text search. Returns [(chunk_id, bm25_score)] with lower = better (SQLite convention), converted to positive."""
    conn = connect()
    q = _fts_query(query)
    if not q:
        return []
    sql = "SELECT c.id, bm25(chunks_fts) AS score FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid WHERE chunks_fts MATCH ?"
    args: list[Any] = [q]
    if source_ids:
        sql += " AND c.source_id IN (" + ",".join("?" for _ in source_ids) + ")"
        args += source_ids
    sql += " ORDER BY score LIMIT ?"
    args.append(limit)
    try:
        rows = conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r["id"], -float(r["score"])) for r in rows]


def _fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 query: quoted terms OR'd together (each term prefix-matched)."""
    import re
    terms = [t for t in re.findall(r"[\w']+", query.lower()) if len(t) > 1]
    if not terms:
        return ""
    stop = {"the", "and", "or", "of", "to", "in", "is", "it", "a", "an", "what", "how", "does", "do", "did",
            "about", "for", "on", "with", "that", "this", "are", "was", "were", "be", "they", "he", "she", "say",
            "said", "talk", "mention", "anyone", "who", "when", "where", "why", "which", "there", "any", "can"}
    terms = [t for t in terms if t not in stop] or terms
    return " OR ".join(f'"{t}"' for t in terms[:12])


# ----------------------------------------------------------- collections

def upsert_collection(kind: str, external_id: str | None, url: str | None, title: str | None) -> dict[str, Any]:
    with tx() as conn:
        row = None
        if external_id:
            row = conn.execute("SELECT * FROM collections WHERE kind=? AND external_id=?", (kind, external_id)).fetchone()
        if row:
            if title:
                conn.execute("UPDATE collections SET title=?, url=COALESCE(?, url) WHERE id=?", (title, url, row["id"]))
            cid = row["id"]
        else:
            cid = new_id()
            conn.execute(
                "INSERT INTO collections (id, kind, url, title, external_id, created_at) VALUES (?,?,?,?,?,?)",
                (cid, kind, url, title, external_id, now()),
            )
        return dict(conn.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone())


def link_source_collection(source_id: str, collection_id: str) -> None:
    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO source_collections VALUES (?,?)", (source_id, collection_id))


def list_collections() -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        """SELECT c.*, COUNT(sc.source_id) AS n_sources FROM collections c
           LEFT JOIN source_collections sc ON sc.collection_id = c.id
           GROUP BY c.id ORDER BY c.created_at DESC"""
    ).fetchall()]


# ------------------------------------------------------------------ jobs

def create_job(kind: str, payload: dict) -> dict[str, Any]:
    jid = new_id()
    with tx() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, payload, created_at) VALUES (?,?,?,?)",
            (jid, kind, json.dumps(payload), now()),
        )
    return get_job(jid)  # type: ignore[return-value]


def get_job(job_id: str) -> dict[str, Any] | None:
    return row_to_dict(connect().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute(  # type: ignore[misc]
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()]


def claim_job() -> dict[str, Any] | None:
    """Atomically claim the oldest queued job."""
    with tx() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        cur = conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'", (now(), row["id"])
        )
        if cur.rowcount != 1:
            return None
        return row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())


def update_job(job_id: str, *, progress: float | None = None, message: str | None = None,
               status: str | None = None, result: dict | None = None) -> None:
    sets, args = [], []
    if progress is not None:
        sets.append("progress=?"); args.append(progress)
    if message is not None:
        sets.append("message=?"); args.append(message[:2000])
    if status is not None:
        sets.append("status=?"); args.append(status)
        if status in ("done", "failed"):
            sets.append("finished_at=?"); args.append(now())
    if result is not None:
        sets.append("result=?"); args.append(json.dumps(result))
    if not sets:
        return
    with tx() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", (*args, job_id))


def requeue_stale_running_jobs() -> int:
    """On startup: jobs left 'running' by a crashed process go back to queued."""
    with tx() as conn:
        cur = conn.execute("UPDATE jobs SET status='queued', started_at=NULL WHERE status='running'")
        return cur.rowcount


# -------------------------------------------------------------- projects

def create_project(name: str, brief: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    pid = new_id()
    with tx() as conn:
        t = now()
        conn.execute(
            "INSERT INTO projects (id, name, brief, tags, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, name, brief, json.dumps(tags or []), t, t),
        )
    return get_project(pid)  # type: ignore[return-value]


def update_project(project_id: str, **fields: Any) -> dict[str, Any] | None:
    fields = {k: v for k, v in fields.items() if k in ("name", "brief", "tags", "context", "mode") and v is not None}
    if "tags" in fields:
        fields["tags"] = json.dumps(fields["tags"])
    if fields:
        fields["updated_at"] = now()
        sets = ", ".join(f"{k}=?" for k in fields)
        with tx() as conn:
            conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), project_id))
    return get_project(project_id)


def get_project(project_id: str) -> dict[str, Any] | None:
    row = row_to_dict(connect().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())
    if row:
        row["source_ids"] = project_source_ids(project_id)
        row["n_sources"] = len(row["source_ids"])
        row["collections"] = [dict(r) for r in connect().execute(
            "SELECT c.* FROM collections c JOIN project_collections pc ON pc.collection_id=c.id WHERE pc.project_id=?",
            (project_id,)).fetchall()]
    return row


def find_project(name_or_id: str) -> dict[str, Any] | None:
    p = get_project(name_or_id)
    if p:
        return p
    row = connect().execute("SELECT id FROM projects WHERE lower(name)=lower(?)", (name_or_id,)).fetchone()
    return get_project(row["id"]) if row else None


def list_projects() -> list[dict[str, Any]]:
    rows = [row_to_dict(r) for r in connect().execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()]
    for r in rows:
        r["n_sources"] = len(project_source_ids(r["id"]))  # type: ignore[index]
    return rows  # type: ignore[return-value]


def delete_project(project_id: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


def project_source_ids(project_id: str, ready_only: bool = True) -> list[str]:
    """Sources in a project: direct members + members of linked collections + tag matches.
    ready_only=True (default) is what search uses; False also returns pending/failed ones for listing."""
    conn = connect()
    st = "s.status='ready'" if ready_only else "1=1"
    p = conn.execute("SELECT tags FROM projects WHERE id=?", (project_id,)).fetchone()
    if not p:
        return []
    ids: set[str] = set()
    ids.update(r["source_id"] for r in conn.execute(
        f"SELECT ps.source_id FROM project_sources ps JOIN sources s ON s.id=ps.source_id WHERE ps.project_id=? AND {st}",
        (project_id,)).fetchall())
    ids.update(r["source_id"] for r in conn.execute(
        f"""SELECT sc.source_id FROM project_collections pc
           JOIN source_collections sc ON sc.collection_id = pc.collection_id
           JOIN sources s ON s.id = sc.source_id
           WHERE pc.project_id=? AND {st}""", (project_id,)).fetchall())
    try:
        tags = json.loads(p["tags"] or "[]")
    except ValueError:
        tags = []
    if tags:
        st2 = st.replace("s.status", "status")
        for r in conn.execute(f"SELECT id, tags FROM sources WHERE {st2} AND tags IS NOT NULL").fetchall():
            try:
                stags = json.loads(r["tags"] or "[]")
            except ValueError:
                continue
            if any(t in stags for t in tags):
                ids.add(r["id"])
    return sorted(ids)


def add_project_sources(project_id: str, source_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("INSERT OR IGNORE INTO project_sources VALUES (?,?)", [(project_id, s) for s in source_ids])
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


def remove_project_sources(project_id: str, source_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("DELETE FROM project_sources WHERE project_id=? AND source_id=?", [(project_id, s) for s in source_ids])


def add_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("INSERT OR IGNORE INTO project_collections VALUES (?,?)", [(project_id, c) for c in collection_ids])
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), project_id))


def remove_project_collections(project_id: str, collection_ids: list[str]) -> None:
    with tx() as conn:
        conn.executemany("DELETE FROM project_collections WHERE project_id=? AND collection_id=?",
                         [(project_id, c) for c in collection_ids])


def add_project_note(project_id: str, content: str, citations: list | None = None) -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO project_notes (project_id, content, citations, created_at) VALUES (?,?,?,?)",
            (project_id, content, json.dumps(citations or []), now()),
        )
        return row_to_dict(conn.execute("SELECT * FROM project_notes WHERE id=?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_project_notes(project_id: str) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in connect().execute(  # type: ignore[misc]
        "SELECT * FROM project_notes WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()]


def delete_project_note(note_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM project_notes WHERE id=?", (note_id,))


# ------------------------------------------------------ facts & plans

def add_fact(project_id: str, kind: str, content: str, origin: str = "user") -> dict[str, Any]:
    with tx() as conn:
        cur = conn.execute("INSERT INTO project_facts (project_id, kind, content, origin, created_at) VALUES (?,?,?,?,?)",
                           (project_id, kind, content, origin, now()))
        return dict(conn.execute("SELECT * FROM project_facts WHERE id=?", (cur.lastrowid,)).fetchone())


def list_facts(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM project_facts WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()]


def delete_fact(fact_id: int) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM project_facts WHERE id=?", (fact_id,))


def project_snapshot(project_id: str) -> dict[str, int]:
    """Counts used to detect 'research changed since the plan was built'."""
    conn = connect()
    n_msgs = conn.execute("SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.project_id=?",
                          (project_id,)).fetchone()["n"]
    return {
        "sources": len(project_source_ids(project_id)),
        "notes": conn.execute("SELECT COUNT(*) n FROM project_notes WHERE project_id=?", (project_id,)).fetchone()["n"],
        "facts": conn.execute("SELECT COUNT(*) n FROM project_facts WHERE project_id=?", (project_id,)).fetchone()["n"],
        "messages": n_msgs,
    }


def save_plan(project_id: str, plan: dict[str, Any], snapshot: dict[str, Any], carry_statuses_from: str | None = None) -> dict[str, Any]:
    pid = new_id()
    with tx() as conn:
        v = conn.execute("SELECT COALESCE(MAX(version),0)+1 v FROM plans WHERE project_id=?", (project_id,)).fetchone()["v"]
        t = now()
        conn.execute("INSERT INTO plans (id, project_id, version, plan, snapshot, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                     (pid, project_id, v, json.dumps(plan), json.dumps(snapshot), t, t))
        if carry_statuses_from:
            rows = conn.execute("SELECT key, status, note FROM plan_items WHERE plan_id=?", (carry_statuses_from,)).fetchall()
            conn.executemany("INSERT OR IGNORE INTO plan_items (plan_id, key, status, note, updated_at) VALUES (?,?,?,?,?)",
                             [(pid, r["key"], r["status"], r["note"], t) for r in rows])
    return get_plan(pid)  # type: ignore[return-value]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d["plan"] or "{}")
    d["snapshot"] = json.loads(d["snapshot"] or "{}")
    d["items"] = {r["key"]: {"status": r["status"], "note": r["note"]} for r in
                  connect().execute("SELECT key, status, note FROM plan_items WHERE plan_id=?", (plan_id,)).fetchall()}
    d["updates"] = [dict(r) for r in connect().execute(
        "SELECT * FROM plan_updates WHERE plan_id=? ORDER BY created_at", (plan_id,)).fetchall()]
    return d


def latest_plan(project_id: str) -> dict[str, Any] | None:
    row = connect().execute("SELECT id FROM plans WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
    return get_plan(row["id"]) if row else None


def list_plans(project_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in connect().execute(
        "SELECT id, version, status, created_at FROM plans WHERE project_id=? ORDER BY version DESC", (project_id,)).fetchall()]


def set_plan_status(plan_id: str, status: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE plans SET status=?, updated_at=? WHERE id=?", (status, now(), plan_id))


def set_item_status(plan_id: str, key: str, status: str, note: str | None = None) -> None:
    with tx() as conn:
        conn.execute("""INSERT INTO plan_items (plan_id, key, status, note, updated_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(plan_id, key) DO UPDATE SET status=excluded.status,
                        note=COALESCE(excluded.note, plan_items.note), updated_at=excluded.updated_at""",
                     (plan_id, key, status, note, now()))


def add_plan_updates(plan_id: str, updates: list[dict[str, Any]]) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM plan_updates WHERE plan_id=? AND status='pending'", (plan_id,))
        conn.executemany("INSERT INTO plan_updates (plan_id, section, previous, proposed, reason, created_at) VALUES (?,?,?,?,?,?)",
                         [(plan_id, u.get("section", ""), u.get("previous"), u.get("proposed", ""), u.get("reason"), now()) for u in updates])


def set_update_status(update_id: int, status: str) -> dict[str, Any] | None:
    with tx() as conn:
        conn.execute("UPDATE plan_updates SET status=? WHERE id=?", (status, update_id))
        row = conn.execute("SELECT * FROM plan_updates WHERE id=?", (update_id,)).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------- conversations

def save_message(conversation_id: str, role: str, content: str, citations: list | None = None,
                 title: str | None = None, project_id: str | None = None) -> None:
    with tx() as conn:
        t = now()
        conn.execute(
            "INSERT OR IGNORE INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conversation_id, project_id, title, t, t),
        )
        conn.execute("UPDATE conversations SET updated_at=?, title=COALESCE(title, ?) WHERE id=?", (t, title, conversation_id))
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, citations, created_at) VALUES (?,?,?,?,?)",
            (conversation_id, role, content, json.dumps(citations) if citations is not None else None, t),
        )


def get_messages(conversation_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = connect().execute(
        "SELECT role, content, citations, created_at FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return [row_to_dict(r) for r in reversed(rows)]  # type: ignore[misc]


def list_conversations(project_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if project_id:
        rows = connect().execute(
            "SELECT * FROM conversations WHERE project_id=? ORDER BY updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
    else:
        rows = connect().execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def create_conversation(project_id: str | None, title: str | None = None) -> dict[str, Any]:
    cid = new_id()
    with tx() as conn:
        t = now()
        conn.execute("INSERT INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (cid, project_id, title, t, t))
        return dict(conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone())


def rename_conversation(conversation_id: str, title: str) -> None:
    with tx() as conn:
        conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now(), conversation_id))


def delete_conversation(conversation_id: str) -> None:
    with tx() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
