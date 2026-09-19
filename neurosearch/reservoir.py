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


# ---------------------------------------------------------------- subreddit catalog scans (SUB3)

SUBREDDIT_PAGE_SIZE = 100
SUBREDDIT_MAX_PAGES = 50
SUBREDDIT_MAX_OBSERVATIONS = 5_000


class _StaleSubredditScan(RuntimeError):
    """A newer manual run replaced this worker while it was fetching a page."""


def _subreddit_catalog(project_id: str, collection_id: str) -> dict[str, Any]:
    collection = db.get_collection(collection_id)
    if (not db.get_project(project_id) or not collection or collection.get("kind") != "subreddit"
            or not db.project_has_collection(project_id, collection_id)):
        raise ValueError("subreddit refresh needs a subreddit catalog")
    return collection


def _scan_state(raw: str | None) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def _new_subreddit_run(prior: dict[str, Any], collection_id: str) -> dict[str, Any]:
    """Construct one head-first run.  The caller atomically stores it with its job."""
    t = time.time()
    known_posts = len(db.collection_candidate_ids(collection_id))
    previous_completed = None
    if prior.get("status") == "complete":
        previous_completed = {k: prior.get(k) for k in (
            "run_id", "generation", "mode", "known_posts", "new", "pages", "observed",
            "started_at", "finished_at", "reason", "observed_oldest", "observed_newest",
        )}
    elif prior.get("previous_completed"):
        previous_completed = prior["previous_completed"]
    return {"run_id": db.new_id(), "generation": int(prior.get("generation") or 0) + 1,
            "mode": "refresh" if prior or known_posts else "initial", "status": "queued", "cursor": None,
            "pages": 0, "observed": 0, "new": 0, "initial_known": 0, "known_posts": known_posts,
            "baseline_known": known_posts, "started_at": t, "updated_at": t, "finished_at": None,
            "reason": None, "access": "reddit_api", "endpoint": "new",
            "page_limit": SUBREDDIT_MAX_PAGES, "observation_limit": SUBREDDIT_MAX_OBSERVATIONS,
            "previous_completed": previous_completed}


def _catalog_job_is_active(state: dict[str, Any]) -> bool:
    job_id = state.get("job_id")
    job = db.get_job(job_id) if job_id else None
    return bool(job and job.get("status") in db.JOB_ACTIVE)


def begin_subreddit_refresh(project_id: str, collection_id: str) -> dict[str, Any]:
    """Begin a new head-first, manual catalog run without touching the provider.

    This is intentionally a state transition, not another queue or scheduler. A later page worker owns the
    provider call. Keeping the prior completed summary lets the UI describe a failed refresh honestly.
    """
    _subreddit_catalog(project_id, collection_id)
    key = _scan_key(project_id, collection_id)
    raw = db.kv_get(key)
    prior = _scan_state(raw)
    if prior.get("status") in ("queued", "partial"):
        # Repeated refresh clicks must share the existing durable run and cursor. In particular, do not turn a
        # queued initial scan into a refresh before it has made its first page commit.
        return prior
    state = _new_subreddit_run(prior, collection_id)
    if not db.kv_compare_set(key, raw, json.dumps(state, sort_keys=True)):
        raise RuntimeError("subreddit scan changed; retry refresh")
    return state


def admit_subreddit_scan(project_id: str, collection_id: str, *, refresh: bool = False) -> dict[str, Any]:
    """Atomically admit a catalog run and its existing explore job.

    ``refresh=False`` is the paste/attach path: it starts a missing initial run,
    reuses an active run, resumes a terminal run from its checkpoint, and leaves
    a completed catalog alone.  ``refresh=True`` is the explicit head refresh:
    it reuses a presently active run but otherwise creates a new generation.
    State and job are committed together so neither can be stranded by a crash.
    """
    collection = _subreddit_catalog(project_id, collection_id)
    key = _scan_key(project_id, collection_id)
    with db.batch():
        raw = db.kv_get(key)
        prior = _scan_state(raw)
        active_state = prior.get("status") in ("queued", "partial")
        if active_state and _catalog_job_is_active(prior):
            return {"state": prior, "job": db.get_job(prior["job_id"]), "reused": True}

        if refresh:
            # A non-active explicit refresh is a new head run.  Its run-bound
            # dedupe key prevents an old retry from being returned here.
            state = _new_subreddit_run(prior, collection_id)
        elif not prior:
            state = _new_subreddit_run({}, collection_id)
        elif active_state:
            # Legacy state may predate job_id, or its job may have disappeared.
            # Preserve this run/cursor and repair the missing admission.
            state = {**prior, "status": "queued", "updated_at": time.time(), "error": None}
        elif prior.get("status") == "complete":
            return {"state": prior, "job": None, "reused": True}
        elif _catalog_job_is_active(prior):
            # A retrying job can temporarily have a blocked scan state.  The
            # paste path resumes it; explicit refresh took the new-run branch.
            return {"state": prior, "job": db.get_job(prior["job_id"]), "reused": True}
        else:
            # Retry a terminal/blocked run from its persisted cursor.  This is
            # resume, not a silent refresh from the listing head.
            state = {**prior, "status": "queued", "updated_at": time.time(), "finished_at": None,
                     "reason": None, "error": None}

        from . import jobs
        job = jobs.enqueue("explore", {
            "url": collection.get("url"), "kind": "subreddit", "project_id": project_id,
            "collection_id": collection_id, "catalog_run_id": state["run_id"],
            "catalog_generation": state["generation"],
        }, lane="low")
        state = {**state, "job_id": job["id"]}
        if not db.kv_compare_set(key, raw, json.dumps(state, sort_keys=True)):
            raise RuntimeError("subreddit scan changed; retry admission")
    return {"state": state, "job": job, "reused": False}


def subreddit_catalogs(project_id: str) -> list[dict[str, Any]]:
    """The project-attached catalog cards, with their latest durable scan state."""
    rows = db.connect().execute("""SELECT c.* FROM collections c JOIN project_collections pc ON pc.collection_id=c.id
                                 WHERE pc.project_id=? AND c.kind='subreddit' ORDER BY c.created_at DESC""", (project_id,)).fetchall()
    out = []
    for row in rows:
        catalog = dict(row)
        try:
            scan = json.loads(db.kv_get(_scan_key(project_id, catalog["id"])) or "{}")
        except ValueError:
            scan = {}
        catalog["scan"] = scan
        out.append(catalog)
    return out


def scan_subreddit_page(project_id: str, collection_id: str, *, expected_run_id: str | None = None,
                         expected_generation: int | None = None,
                         fetch_page: Callable[[str, str | None], tuple[list[dict[str, Any]], str | None]] | None = None) -> dict[str, Any]:
    """Fetch and atomically commit one subreddit listing page.

    Fetching happens before the write transaction. The page's Candidate Index rows, catalog memberships,
    project reconciliation and cursor checkpoint commit together through ``db.batch``; a crash therefore
    replays an entire page or none of it. Callers schedule another turn while ``status == 'partial'``.
    """
    collection = db.get_collection(collection_id)
    if not db.get_project(project_id) or not collection or collection.get("kind") != "subreddit" or not db.project_has_collection(project_id, collection_id):
        raise ValueError("subreddit scan needs a subreddit catalog")
    name = collection.get("external_id")
    if not name:
        raise ValueError("subreddit catalog is missing its identity")
    key = _scan_key(project_id, collection_id)
    prior_raw = db.kv_get(key)
    try:
        prior = json.loads(prior_raw or "{}")
    except ValueError:
        prior = {}
    if expected_run_id and (prior.get("run_id") != expected_run_id or
                            (expected_generation is not None and prior.get("generation") != expected_generation)):
        return {"collection_id": collection_id, "status": "stale", "new": 0, "candidate_ids": []}
    if prior.get("status") == "complete":
        return {"collection_id": collection_id, "status": "complete", "new": 0, "total": int(prior.get("known_posts") or 0),
                "reason": prior.get("reason"), "candidate_ids": []}
    if not prior:
        t = time.time()
        prior = {"run_id": db.new_id(), "generation": 1, "mode": "initial", "status": "queued", "cursor": None,
                 "pages": 0, "observed": 0, "new": 0, "initial_known": 0,
                 "baseline_known": len(db.collection_candidate_ids(collection_id)), "started_at": t, "updated_at": t,
                 "access": "reddit_api", "endpoint": "new", "page_limit": SUBREDDIT_MAX_PAGES,
                 "observation_limit": SUBREDDIT_MAX_OBSERVATIONS}
    cursor = prior.get("cursor")
    fetch = fetch_page
    if fetch is None:
        from . import community
        fetch = lambda sub, after: community.enumerate_subreddit_page(sub, after, limit=SUBREDDIT_PAGE_SIZE)
    try:
        rows, next_cursor = fetch(name, cursor)
    except Exception as e:  # preserve any committed pages and make the block visible/retryable
        state = {**prior, "status": "blocked", "error": str(e), "updated_at": time.time(), "cursor": cursor,
                 "known_posts": len(db.collection_candidate_ids(collection_id)), "pages": int(prior.get("pages") or 0)}
        if not db.kv_compare_set(key, prior_raw, json.dumps(state, sort_keys=True)):
            return {"collection_id": collection_id, "status": "stale", "new": 0, "candidate_ids": []}
        return {"collection_id": collection_id, "status": "blocked", "new": 0, "total": state["known_posts"], "error": state["error"], "candidate_ids": []}
    if next_cursor and next_cursor == cursor:
        next_cursor = None
        terminal_reason = "cursor did not advance"
    else:
        terminal_reason = "listing ended" if not next_cursor else None

    # Compute before remember() mutates either global rows or this project's relationship rows.
    known = {r["external_id"] for r in db.connect().execute(
        "SELECT c.external_id FROM collection_candidates cc JOIN candidates c ON c.id=cc.candidate_id WHERE cc.collection_id=?",
        (collection_id,),
    ).fetchall()}
    # A listing can repeat a post within one page.  Observations retain that fact, while membership and
    # unique-post counts use each external id exactly once.
    entries_by_id = {str(r["external_id"]): r for r in rows if r.get("external_id")}
    entries = list(entries_by_id.values())
    new_count = sum(1 for r in entries if r["external_id"] not in known)
    now = time.time()
    pages = int(prior.get("pages") or 0) + 1
    observed = int(prior.get("observed") or 0) + len(rows)
    capped = pages >= SUBREDDIT_MAX_PAGES or observed >= SUBREDDIT_MAX_OBSERVATIONS
    status = "complete" if not next_cursor or capped else "partial"
    terminal_reason = "application limit reached" if capped and next_cursor else terminal_reason
    known_posts = len(known) + new_count
    mode = prior.get("mode") or "initial"
    dates = [str(r.get("published_at")) for r in entries if r.get("published_at")]
    oldest = min([d for d in [prior.get("observed_oldest"), *dates] if d], default=None)
    newest = max([d for d in [prior.get("observed_newest"), *dates] if d], default=None)
    state = {**prior, "status": status, "cursor": None if status == "complete" else next_cursor, "pages": pages,
             "observed": observed, "known_posts": known_posts,
             "new": int(prior.get("new") or 0) + (new_count if mode == "refresh" else 0),
             "initial_known": int(prior.get("initial_known") or 0) + (new_count if mode == "initial" else 0),
             "started_at": prior.get("started_at") or now, "updated_at": now, "finished_at": now if status == "complete" else None,
             "reason": terminal_reason, "access": "reddit_api", "endpoint": "new",
             "observed_oldest": oldest, "observed_newest": newest,
             "page_limit": SUBREDDIT_MAX_PAGES, "observation_limit": SUBREDDIT_MAX_OBSERVATIONS}
    state_raw = json.dumps(state, sort_keys=True)
    try:
        with db.batch():
            ids = candidates.remember(entries, "reddit", project_id,
                                      {"kind": "subreddit_catalog", "collection_id": collection_id, "subreddit": name})
            db.link_collection_candidates(collection_id, ids)
            if not db.kv_compare_set(key, prior_raw, state_raw):
                raise _StaleSubredditScan()
    except _StaleSubredditScan:
        return {"collection_id": collection_id, "status": "stale", "new": 0, "candidate_ids": []}
    return {"collection_id": collection_id, "status": status, "new": new_count if mode == "refresh" else 0,
            "initial_known": new_count if mode == "initial" else 0, "total": state["known_posts"],
            "observed": state["observed"], "pages": state["pages"], "cursor": state["cursor"],
            "reason": terminal_reason, "candidate_ids": ids}


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
