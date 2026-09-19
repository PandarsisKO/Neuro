"""Rung G1 — global source identity: a source is acquired ONCE globally and attached to N projects.

Every ingestion entrance (URL, pasted HTML, session ingest, file upload, pasted text, transcript import, course
import, channel/playlist listing, library attach, CLI, MCP) resolves identity through ONE function before it does
anything else:

    resolve_or_create_source(candidate, project_id) -> Resolution(state, source, created, attached, resumed)

        ALREADY_IN_PROJECT   the project already has it: no-op (no job, no analysis)
        EXISTING_READY       attach; queue THIS project's project-relative analysis; nothing is re-downloaded
        EXISTING_PENDING     attach to the same global work; the status is never reset; whoever is ingesting it
                             finishes it for every project (a stale pending row with no live job is resumed once)
        EXISTING_FAILED      attach and report the failure; the acquisition is retried only when retry=True
        NEW                  create the global row exactly once (the unique index + IntegrityError re-select make two
                             concurrent adds resolve to one row) and attach; the caller runs the durable lifecycle

Identity order (Invariant C): platform-native id → canonical URL → content fingerprint → the legacy `name:size`
upload key. Legacy rows found by the legacy key are stamped with their fingerprint so the next add is a direct hit.
A URL with no extractable native id resolves by canonical URL instead of inserting blind.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import db

log = logging.getLogger(__name__)

ALREADY_IN_PROJECT, EXISTING_READY, EXISTING_PENDING, EXISTING_FAILED, NEW = (
    "ALREADY_IN_PROJECT", "EXISTING_READY", "EXISTING_PENDING", "EXISTING_FAILED", "NEW")
STATES = (ALREADY_IN_PROJECT, EXISTING_READY, EXISTING_PENDING, EXISTING_FAILED, NEW)
REUSED = (ALREADY_IN_PROJECT, EXISTING_READY, EXISTING_PENDING)      # states in which no acquisition happens


@dataclass
class Candidate:
    platform: str
    external_id: str | None
    url: str
    title: str | None = None
    canonical_url: str | None = None
    fingerprint: str | None = None
    legacy_external_id: str | None = None          # the pre-G1 upload key (doc:name:size …) for rows created before 0.25.0
    tags: list[str] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)   # extra source columns to set on create / fill when empty


@dataclass
class Resolution:
    state: str
    source: dict[str, Any]
    created: bool = False
    attached: bool = False
    resumed: bool = False

    @property
    def reused(self) -> bool:
        return self.state in REUSED


def fingerprint_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def fingerprint_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def fingerprint_text(*parts: str) -> str:
    return "sha256:" + hashlib.sha256("\x1f".join(parts).encode("utf-8", "replace")).hexdigest()


def upload_candidate(platform: str, path: Path, name: str, title: str | None, tags: list[str] | None, legacy_prefix: str) -> Candidate:
    """Identity for an uploaded file: content fingerprint first (the same bytes under another name are the same
    source), the pre-G1 `prefix:name:size` key as the legacy fallback."""
    fp = fingerprint_file(path)
    return Candidate(platform=platform, external_id=f"file:{fp[7:23]}", url=f"file://{name}", title=title, fingerprint=fp,
                     legacy_external_id=f"{legacy_prefix}:{name}:{path.stat().st_size}", tags=list(tags or []))


def find_existing(conn: sqlite3.Connection, cand: Candidate) -> sqlite3.Row | None:
    if cand.external_id:
        r = conn.execute("SELECT * FROM sources WHERE platform=? AND external_id=?", (cand.platform, cand.external_id)).fetchone()
        if r:
            return r
    if cand.fingerprint:
        r = conn.execute("SELECT * FROM sources WHERE platform=? AND content_fingerprint=?", (cand.platform, cand.fingerprint)).fetchone()
        if r:
            return r
    if cand.canonical_url:
        r = conn.execute("SELECT * FROM sources WHERE platform=? AND canonical_url=?", (cand.platform, cand.canonical_url)).fetchone()
        if r:
            return r
    if cand.legacy_external_id:
        # a pre-G1 upload row keyed name:size — trusted only while its content is unknown (no fingerprint yet) or matches;
        # once stamped, a different fingerprint under the same name and size is a different file (the old key collided)
        r = conn.execute("SELECT * FROM sources WHERE platform=? AND external_id=?", (cand.platform, cand.legacy_external_id)).fetchone()
        if r and (not r["content_fingerprint"] or not cand.fingerprint or r["content_fingerprint"] == cand.fingerprint):
            return r
    return None


def classify(source: dict[str, Any] | None, project_id: str | None, conn: sqlite3.Connection | None = None) -> str:
    """The five states, without writing anything (used for review counts and dry runs)."""
    if not source:
        return NEW
    conn = conn or db.connect()
    if project_id and conn.execute("SELECT 1 FROM project_sources WHERE project_id=? AND source_id=? AND excluded=0", (project_id, source["id"])).fetchone():
        return ALREADY_IN_PROJECT
    st = source.get("status")
    if st == "ready":
        return EXISTING_READY
    if st == "failed":
        return EXISTING_FAILED
    return EXISTING_PENDING            # pending | proposed | skipped: exists, not acquired yet


def resolve(cand: Candidate, project_id: str | None) -> tuple[str, dict[str, Any] | None]:
    """Dry run: (state, existing source or None). No writes."""
    conn = db.connect()
    r = find_existing(conn, cand)
    src = db.row_to_dict(r) if r else None
    return classify(src, project_id, conn), src


def resolve_or_create_source(cand: Candidate, project_id: str | None, *, initial_status: str = "pending",
                             retry: bool = False, attach: bool = True, resume_skipped: bool = True) -> Resolution:
    """See the module docstring. Atomic per call; safe under concurrent adds of the same source."""
    if not cand.external_id:
        cand.external_id = cand.canonical_url or cand.fingerprint or cand.url
    with db.tx() as conn:
        r = find_existing(conn, cand)
        created = False
        if r is None:
            t = db.now()
            row = {"id": db.new_id(), "platform": cand.platform, "external_id": cand.external_id, "url": cand.url, "title": cand.title,
                   "status": initial_status, "tags": db.json.dumps(cand.tags or []), "created_at": t, "updated_at": t,
                   "canonical_url": cand.canonical_url, "content_fingerprint": cand.fingerprint}
            for k, v in (cand.fields or {}).items():
                if v is not None and k not in row:
                    row[k] = db.json.dumps(v) if isinstance(v, (list, dict)) else v
            try:
                conn.execute(f"INSERT INTO sources ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})", tuple(row.values()))
                created = True
            except sqlite3.IntegrityError:
                pass                                                  # lost the race: the other add created it — use theirs
            r = find_existing(conn, cand)
            if r is None:                                             # cannot happen unless the unique key differs from ours
                raise RuntimeError(f"source identity conflict for {cand.platform}:{cand.external_id}")
        src = db.row_to_dict(r)
        resumed = False
        if not created:
            # a legacy row (found by name:size or canonical URL) learns its stronger identity; empty metadata is filled, never overwritten
            patch: dict[str, Any] = {}
            if cand.fingerprint and not src.get("content_fingerprint"):
                patch["content_fingerprint"] = cand.fingerprint
            if cand.canonical_url and not src.get("canonical_url"):
                patch["canonical_url"] = cand.canonical_url
            if cand.title and not src.get("title"):
                patch["title"] = cand.title
            for k, v in (cand.fields or {}).items():
                if v is not None and k in src and src.get(k) in (None, "", "[]"):
                    patch[k] = db.json.dumps(v) if isinstance(v, (list, dict)) else v
            if cand.tags:
                cur = list(src.get("tags") or [])
                new = cur + [t for t in cand.tags if t not in cur]
                if new != cur:
                    patch["tags"] = db.json.dumps(new)
            if src.get("status") == "failed" and retry:
                patch["status"], patch["error"], resumed = "pending", None, True
            elif src.get("status") == "skipped" and resume_skipped:
                patch["status"], patch["error"], resumed = "pending", None, True   # an explicit add overrides a bulk cutoff
            if patch:
                patch["updated_at"] = db.now()
                conn.execute("UPDATE sources SET " + ", ".join(f"{k}=?" for k in patch) + " WHERE id=?", (*patch.values(), src["id"]))
                src = db.row_to_dict(conn.execute("SELECT * FROM sources WHERE id=?", (src["id"],)).fetchone())
        state = NEW if created else classify(src, project_id, conn)
        attached = False
        if attach and project_id and state != ALREADY_IN_PROJECT:
            conn.execute("INSERT OR IGNORE INTO project_sources (project_id, source_id) VALUES (?,?)", (project_id, src["id"]))
            # An explicit add/capture reverses the project's own prior removal.
            # `INSERT OR IGNORE` alone leaves an excluded durable relationship
            # in place, which made a ready library Source appear captured but
            # remain absent from the selecting project.
            conn.execute("UPDATE project_sources SET excluded=0 WHERE project_id=? AND source_id=? AND excluded=1",
                         (project_id, src["id"]))
            conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (db.now(), project_id))
            attached = True
    res = Resolution(state=state, source=src, created=created, attached=attached, resumed=resumed)
    if created and initial_status != "proposed":
        try:
            from . import candidates
            candidates.resolve_acquired(src["platform"], src["external_id"], src["id"])    # a seen candidate now points at its source
        except Exception:  # noqa: BLE001
            pass
    if attached and state in (EXISTING_READY, EXISTING_PENDING, EXISTING_FAILED):
        _record_reuse(res, project_id)
    if attached and state == EXISTING_READY:
        after_ready(src["id"], project_id)
    return res


def attach_existing(project_id: str, source_id: str) -> Resolution:
    """Library → project (members endpoint, CLI, MCP): the same rules as any other entrance, by id."""
    src = db.get_source(source_id)
    if not src:
        raise KeyError(source_id)
    cand = Candidate(platform=src["platform"], external_id=src["external_id"], url=src["url"])
    return resolve_or_create_source(cand, project_id, resume_skipped=False)


def after_ready(source_id: str, project_id: str | None) -> None:
    """Project-relative analysis for a source that is (already) ready — the same hook every ingest path uses."""
    try:
        from .jobs import enqueue_suggestions
        enqueue_suggestions(source_id, project_id)
    except Exception as e:  # noqa: BLE001
        log.warning("could not queue suggestions: %s", e)


def _record_reuse(res: Resolution, project_id: str | None) -> None:
    """Provenance of the reuse: the project got the source without a new acquisition. Health counts these."""
    try:
        db.validation_event("source_reused", {"state": res.state, "resumed": res.resumed, "platform": res.source.get("platform")},
                            project_id=project_id, source_id=res.source["id"])
        db.kv_bump("library:acquisitions_avoided" if res.state in (EXISTING_READY, EXISTING_PENDING) else "library:failed_attached")
    except Exception:  # noqa: BLE001
        pass


def current_job_id() -> str | None:
    try:
        from . import jobs
        return getattr(jobs._current, "job_id", None)
    except Exception:  # noqa: BLE001
        return None


def claim_job_for(source_id: str) -> None:
    """Stamp the running job (an ingest_url / ingest_file job carries a URL or a path, not a source id) with the source
    it resolved to, so `live_job_by_source` — and therefore EXISTING_PENDING handling in other projects — can see it."""
    jid = current_job_id()
    if not jid:
        return
    try:
        job = db.get_job(jid)
        if job and not (job.get("payload") or {}).get("source_id"):
            db.set_job_payload(jid, {**(job.get("payload") or {}), "source_id": source_id})
    except Exception:  # noqa: BLE001
        pass


def has_live_ingest_job(source_id: str) -> bool:
    """True when ANOTHER queued/running ingest job already owns this source (so this add waits instead of re-ingesting)."""
    live = db.live_job_by_source().get(source_id)
    return bool(live) and live.get("id") != current_job_id()


def review_counts(items: list[tuple[str, dict[str, Any] | None]]) -> dict[str, int]:
    """found / already_in_library / already_in_project / new from a list of (state, source) dry-run results."""
    c = {"found": len(items), "already_in_project": 0, "already_in_library": 0, "new": 0}
    for state, _ in items:
        if state == ALREADY_IN_PROJECT:
            c["already_in_project"] += 1
        elif state == NEW:
            c["new"] += 1
        else:
            c["already_in_library"] += 1
    return c
