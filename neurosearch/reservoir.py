"""CR3/CR4 (EXECUTION-LADDER.md, PRODUCT-INTELLIGENCE-MISSION.md §13): known-reservoir rescan and change
detection. This is the MONITOR layer only -- see §13's Monitor != Acquire != Retain framing. A rescan produces,
at most, Candidate Index rows (cheap metadata via `candidates.remember`); it never creates a `sources` row,
never ingests, never makes a provider/model call. Acquisition (turning a candidate into real evidence) stays a
separate, explicit decision through the existing review/acquire paths -- the seam between the two is CR8
(documented, not built here; see HANDOFF.md).

Ownership: this module orchestrates existing owners rather than duplicating them -- `media.enumerate_entries`
(collection identity/listing), `db`'s `collections`/`project_collections` tables (collection identity, project
attachment -- both already owned by db.py, extended here only with the two read-only accessors a rescan needs),
and `candidates.remember` (the Candidate Index's one idempotent write path). Nothing here re-implements any of
those.

Reservoir-scan state is PROJECT-SCOPED (`reservoir:scan:<project_id>:<collection_id>`), not merely per-collection.
Candidate relevance, disposition, and acquisition are project-relative (candidate_projects is a per-project
relationship table); a global, collection-only scan-state key would let one project's scan silently starve a
LATER project attaching to the same shared reservoir -- if the remote listing had not changed since the first
project's scan, a collection-only fingerprint would report "unchanged" and skip reconciling already-known
candidates into the second project's own candidate_projects rows, and that project would never receive items
the first project already discovered. Scoping the stored fingerprint per (project_id, collection_id) makes the
cheap no-op gate mean "same remote revision AND this project is already reconciled to it" -- not "the remote
happens to be unchanged" alone -- without needing a second, separate reconciliation-proof mechanism.

CR8 product decision (Kyle, 2026-09-16): "primary for this project" (§13's previously-open question) is stored
on the project<->collection relationship (`project_collections.source_role`/`monitor_policy`), never the global
collection -- the same reservoir can be primary for one project and secondary for another. `effective_monitor_
active` is the pure derivation; `rescan_project` (the "cover everything this project is attached to" bulk path)
now filters to collections whose effective state is active, and skips the rest with ZERO enumerate() calls --
not "rescan and discard", genuinely untouched. `rescan` itself (a single, explicitly-named collection -- the
CLI's `--collection` flag) stays UNGATED by design: an explicit, one-collection ask is a deliberate action, the
same override principle §13 already established for user-explicit watch overriding a tier default. Changing
source_role/monitor_policy never ingests anything -- db.set_collection_policy touches only project_collections.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from . import candidates, db, media

PLATFORM = "youtube"   # media.enumerate_entries is yt-dlp/YouTube-only today; CR3/CR4 do not widen that scope


def _scan_key(project_id: str, collection_id: str) -> str:
    return f"reservoir:scan:{project_id}:{collection_id}"


def fingerprint(entries: list[dict[str, Any]]) -> str:
    """Stable, order-insensitive hash of a reservoir listing's canonical identity.

    Built from (external id, title, duration) per entry, sorted by external id before hashing -- a provider
    returning the same videos in a different order must not register as a change (S51/S50-style ratchet
    discipline: ordering has no semantic meaning here). A genuinely new or removed id, or a changed title/
    duration for an existing id, does change the fingerprint -- but see `rescan`: a video's DISAPPEARANCE from
    the current listing never causes anything already remembered about it to be removed or invalidated; the
    fingerprint changing only ever triggers a fresh `candidates.remember` pass, which is itself a pure add/
    fill-only upsert.
    """
    rows = sorted(
        (str(e.get("id") or ""), str(e.get("title") or ""), str(e.get("duration") or ""))
        for e in entries if e.get("id")
    )
    h = hashlib.sha256()
    for row in rows:
        h.update("\x1f".join(row).encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def _to_candidate_entry(e: dict[str, Any]) -> dict[str, Any] | None:
    ext = e.get("id")
    if not ext:
        return None
    entry: dict[str, Any] = {
        "external_id": ext,
        "url": e.get("url") or "",
        "title": e.get("title"),
        "description": e.get("description"),
        "duration": e.get("duration"),
        "view_count": e.get("view_count"),
    }
    existing_source = db.find_source(PLATFORM, ext)
    if existing_source:
        entry["source_id"] = existing_source["id"]   # candidates.remember only fills empty fields -- safe, idempotent
    return entry


def rescan(project_id: str, collection_id: str, *, enumerate: Callable[[str], tuple[dict, list]] | None = None,
           now: Callable[[], float] | None = None) -> dict[str, Any]:
    """Rescan one reservoir for one project. Detection only -- see module docstring.

    Returns {"changed": bool, "new": int, "total": int, "candidate_ids": [...], "collection_id": ...}.
    `new` counts entries this PROJECT has not previously seen (no existing candidate_projects row for it),
    which is what CR3's gate cares about -- a candidate already known globally (another project found it first)
    still counts as new to a project seeing it for the first time.
    """
    enumerate_fn = enumerate or media.enumerate_entries
    now_fn = now or time.time
    collection = db.get_collection(collection_id)
    if not collection:
        raise ValueError(f"no such collection: {collection_id}")

    _info, raw_entries = enumerate_fn(collection["url"])
    fp = fingerprint(raw_entries)
    key = _scan_key(project_id, collection_id)
    stored_raw = db.kv_get(key)
    stored = json.loads(stored_raw) if stored_raw else None

    if stored and stored.get("fingerprint") == fp:
        return {"changed": False, "new": 0, "total": len(raw_entries), "candidate_ids": [], "collection_id": collection_id}

    # "new to this project" is computed BEFORE remember() mutates candidate_projects, so a candidate another
    # project already discovered (global row exists) still counts as new here if THIS project has never seen it.
    seen_ext_ids = {r["external_id"] for r in db.connect().execute(
        "SELECT c.external_id FROM candidates c JOIN candidate_projects cp ON cp.candidate_id = c.id "
        "WHERE cp.project_id=? AND c.platform=?", (project_id, PLATFORM)).fetchall()}
    entries = [ce for e in raw_entries if (ce := _to_candidate_entry(e)) is not None]
    new_count = sum(1 for e in entries if e["external_id"] not in seen_ext_ids)

    ids = candidates.remember(
        entries, PLATFORM, project_id,
        origin={"kind": "reservoir_rescan", "collection_id": collection_id, "collection_kind": collection.get("kind")},
    )
    db.kv_set(key, json.dumps({"fingerprint": fp, "scanned_at": now_fn(), "total": len(raw_entries)}))
    return {"changed": True, "new": new_count, "total": len(raw_entries), "candidate_ids": ids, "collection_id": collection_id}


def effective_monitor_active(source_role: str, monitor_policy: str) -> bool:
    """Pure derivation over the stored (source_role, monitor_policy) pair -- CR8 product decision (2026-09-16).
    monitor_policy='on'/'off' always wins outright, regardless of role. 'auto' defers to source_role, and only
    'primary' defaults active -- 'secondary' and 'unspecified' both default OFF, because merely being attached
    to a project (`project_collections` existing at all) says nothing on its own about whether this project
    treats that reservoir as a primary source worth watching."""
    if monitor_policy == "on":
        return True
    if monitor_policy == "off":
        return False
    return source_role == "primary"   # monitor_policy == "auto"


def is_monitored(project_id: str, collection_id: str) -> bool:
    """False for a relationship that doesn't exist (never attached) as well as one that exists but is
    effectively inactive -- both mean "don't rescan this automatically"."""
    policy = db.get_collection_policy(project_id, collection_id)
    if not policy:
        return False
    return effective_monitor_active(policy["source_role"], policy["monitor_policy"])


def rescan_project(project_id: str, *, enumerate: Callable[[str], tuple[dict, list]] | None = None,
                    now: Callable[[], float] | None = None) -> list[dict[str, Any]]:
    """Rescan every collection this project is attached to AND whose effective monitoring state is active
    (see module docstring's CR8 note) -- a collection that is attached but not monitored is skipped entirely,
    not rescanned-and-discarded: `enumerate` is never called for it. On-demand only -- never called from a
    schedule or nightly hook tonight; CLI-driven (`neurosearch project rescan`)."""
    return [rescan(project_id, cid, enumerate=enumerate, now=now) for cid in db.project_collection_ids(project_id)
            if is_monitored(project_id, cid)]
