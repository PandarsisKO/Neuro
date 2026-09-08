"""Rung G3 — the Discovery Candidate Index: what Neuro Search has SEEN but not acquired.

    PROJECT EVIDENCE  →  GLOBAL LIBRARY (acquired)  →  CANDIDATE INDEX (seen, not acquired)  →  EXTERNAL WORLD

Principle: discover once, remember cheaply, acquire only when needed. Every enumeration (channel, playlist, YouTube
search, Instagram profile, feed, sitemap, website) records its entries here with cheap metadata (title, description,
creator, date, duration, origin); nothing is transcribed, fetched or embedded to populate the index. A candidate is
NOT evidence: it cannot be cited, cannot support a Claim and never reaches the chat's excerpts — `search()` exists
so a later gap can ask "have we already seen something that might cover this?" before searching the world again.

One global candidate per (platform, external_id); the project relationship carries state + relevance + reason:

    available · skipped_low_relevance · skipped_limit · skipped_cost · user_dismissed · duplicate · acquired

User intent outranks recall: `user_dismissed` is never resurfaced by default. Once acquired (by any path), the
candidate RESOLVES to the global source (`source_id`) — never a second evidence object.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import db

STATES = ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost", "user_dismissed", "duplicate", "acquired")
LOW_RELEVANCE = 50            # a ranked score below this is a "skipped for low relevance", not a "skipped by the limit"
CONTENT_TYPE = {"youtube": "video", "instagram": "post", "podcast": "podcast", "web": "page", "media": "video", "document": "document", "book": "book"}


def remember(entries: list[dict[str, Any]], platform: str, project_id: str | None, origin: dict[str, Any]) -> list[str]:
    """Record enumerated entries as global candidates (+ a project relationship when a project is in scope).
    entries: [{external_id, url, title?, description?, creator?, published_at?, duration?, view_count?, canonical_url?, source_id?}].
    Cheap and idempotent: an entry seen again only bumps last_seen_at / fills empty metadata. Returns candidate ids."""
    t = time.time()
    ids: list[str] = []
    with db.tx() as conn:
        for e in entries:
            ext = e.get("external_id")
            if not ext:
                continue
            r = conn.execute("SELECT * FROM candidates WHERE platform=? AND external_id=?", (platform, ext)).fetchone()
            if r:
                cid = r["id"]
                patch: dict[str, Any] = {"last_seen_at": t}
                for k in ("title", "description", "creator", "published_at", "duration", "view_count", "canonical_url", "source_id"):
                    if e.get(k) is not None and not r[k]:              # fill what is empty; never overwrite what we knew
                        patch[k] = e[k] if k != "description" else str(e[k])[:2000]
                conn.execute("UPDATE candidates SET " + ", ".join(f"{k}=?" for k in patch) + " WHERE id=?", (*patch.values(), cid))
            else:
                cid = db.new_id()
                conn.execute("INSERT INTO candidates (id, platform, external_id, canonical_url, url, title, description, creator, published_at, duration, view_count, "
                             "content_type, language, first_seen_at, last_seen_at, source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, platform, ext, e.get("canonical_url"), e.get("url") or "", e.get("title"), (e.get("description") or "")[:2000] or None, e.get("creator"),
                              e.get("published_at"), e.get("duration"), e.get("view_count"), e.get("content_type") or CONTENT_TYPE.get(platform, "page"),
                              e.get("language"), t, t, e.get("source_id")))
            if project_id:
                conn.execute("INSERT INTO candidate_projects (candidate_id, project_id, state, origin, first_seen_at, updated_at) VALUES (?,?,?,?,?,?) "
                             "ON CONFLICT(candidate_id, project_id) DO UPDATE SET updated_at=excluded.updated_at, origin=COALESCE(candidate_projects.origin, excluded.origin)",
                             (cid, project_id, "available", json.dumps(origin), t, t))
            ids.append(cid)
    return ids


def mark(project_id: str, candidate_ids: list[str], state: str, reason: str | None = None, relevance: int | None = None, why: str | None = None) -> int:
    assert state in STATES, state
    t = time.time()
    n = 0
    with db.tx() as conn:
        for cid in candidate_ids:
            conn.execute("INSERT OR IGNORE INTO candidate_projects (candidate_id, project_id, state, first_seen_at, updated_at) VALUES (?,?,?,?,?)", (cid, project_id, state, t, t))
            n += conn.execute("UPDATE candidate_projects SET state=?, reason=COALESCE(?, reason), relevance=COALESCE(?, relevance), relevance_why=COALESCE(?, relevance_why), updated_at=? "
                              "WHERE candidate_id=? AND project_id=?", (state, reason, relevance, why, t, cid, project_id)).rowcount
    return n


def mark_by_source(project_id: str, source_ids: list[str], state: str, reason: str | None = None, relevance_of: dict[str, tuple[int | None, str | None]] | None = None) -> int:
    """The review flow works in proposed SOURCE ids: map them to their candidates (same platform + external id)."""
    conn = db.connect()
    n = 0
    for sid in source_ids:
        s = conn.execute("SELECT platform, external_id FROM sources WHERE id=?", (sid,)).fetchone()
        if not s:
            continue
        c = conn.execute("SELECT id FROM candidates WHERE platform=? AND external_id=?", (s["platform"], s["external_id"])).fetchone()
        if not c:
            continue
        rel, why = (relevance_of or {}).get(sid, (None, None))
        n += mark(project_id, [c["id"]], state, reason, rel, why)
        if state == "acquired":
            with db.tx() as tx:
                tx.execute("UPDATE candidates SET source_id=? WHERE id=? AND source_id IS NULL", (sid, c["id"]))
    return n


def resolve_acquired(platform: str, external_id: str, source_id: str) -> None:
    """A source was created by ANY path: the matching candidate (if any) now points at it."""
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=?, last_verified_at=? WHERE platform=? AND external_id=? AND source_id IS NULL", (source_id, time.time(), platform, external_id))


def dismiss(project_id: str, candidate_id: str, reason: str | None) -> int:
    return mark(project_id, [candidate_id], "user_dismissed", reason or "dismissed by the user")


def restore(project_id: str, candidate_id: str) -> int:
    return mark(project_id, [candidate_id], "available", "restored by the user")


def _fts_query(q: str) -> str:
    import re
    terms = [t for t in re.findall(r"[\w']+", q.lower()) if len(t) > 1]
    return " OR ".join(f'"{t}"*' for t in terms[:24])


def search(project_id: str | None, query: str, limit: int = 20, include_dismissed: bool = False, include_acquired: bool = False) -> list[dict[str, Any]]:
    """Gap recall over cheap metadata (FTS on title/description/creator). Returns candidates with the project relationship
    and whether a global source already exists (in_library). Never returns evidence — only "we have seen this"."""
    q = _fts_query(query)
    if not q:
        return []
    conn = db.connect()
    rows = conn.execute("SELECT c.*, bm25(candidates_fts) AS score FROM candidates_fts JOIN candidates c ON c.rowid = candidates_fts.rowid "
                        "WHERE candidates_fts MATCH ? ORDER BY score LIMIT ?", (q, limit * 4)).fetchall()
    out = []
    for r in rows:
        d = db.row_to_dict(r)
        d["score"] = round(-float(d.pop("score")), 3)
        rel = None
        if project_id:
            pr = conn.execute("SELECT state, relevance, relevance_why, reason, origin, first_seen_at FROM candidate_projects WHERE candidate_id=? AND project_id=?", (d["id"], project_id)).fetchone()
            rel = db.row_to_dict(pr) if pr else None
            if rel and rel.get("origin"):
                try:
                    rel["origin"] = json.loads(rel["origin"])
                except ValueError:
                    pass
        state = (rel or {}).get("state") or "unseen_by_project"
        if state == "user_dismissed" and not include_dismissed:
            continue
        src = None
        if d.get("source_id"):
            src = conn.execute("SELECT id, status FROM sources WHERE id=?", (d["source_id"],)).fetchone()
        in_library = bool(src and src["status"] == "ready")
        in_project = bool(src and project_id and conn.execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=? AND excluded=0", (project_id, src["id"])).fetchone())
        if (state == "acquired" or in_project) and not include_acquired:
            continue
        d.update(project=rel, state=state, in_library=in_library, in_project=in_project)
        out.append(d)
        if len(out) >= limit:
            break
    return out


def counts(project_id: str) -> dict[str, int]:
    conn = db.connect()
    out = {r["state"]: r["n"] for r in conn.execute("SELECT state, COUNT(*) n FROM candidate_projects WHERE project_id=? GROUP BY state", (project_id,)).fetchall()}
    out["total"] = sum(out.values())
    out["global"] = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    return out


def list_for_project(project_id: str, state: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    conn = db.connect()
    sql = "SELECT c.*, cp.state, cp.relevance, cp.relevance_why, cp.reason, cp.origin, cp.updated_at AS state_at FROM candidate_projects cp JOIN candidates c ON c.id=cp.candidate_id WHERE cp.project_id=?"
    args: list[Any] = [project_id]
    if state:
        sql += " AND cp.state=?"; args.append(state)
    sql += " ORDER BY cp.updated_at DESC LIMIT ?"; args.append(limit)
    out = []
    for r in conn.execute(sql, args).fetchall():
        d = db.row_to_dict(r)
        try:
            d["origin"] = json.loads(d["origin"]) if d.get("origin") else None
        except ValueError:
            pass
        out.append(d)
    return out
