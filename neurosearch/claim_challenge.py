"""On-demand candidate retrieval for a Claim review. Search results are leads for the reviewer."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from functools import cache
from itertools import zip_longest
from datetime import datetime, timezone
from typing import Any, Callable

from . import claims, db, library, search, works
from .config import settings

PASSAGES_PER_SCOPE = 8
PASSAGES_PER_ORIGIN = 2
EARLIER_ASSESSMENT_LIMIT = 32


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()



def _scope_revision(snapshot: dict[str, list], *, legacy: bool = False) -> str:
    if legacy:
        return _fingerprint(json.dumps([(sid, row[0], int(row[1] is not None)) for sid, row in snapshot.items()]))
    return _fingerprint(json.dumps(snapshot))


def _additive_scope(before: dict | None, after: dict) -> bool:
    return before is not None and all(sid in after and (after[sid] == row or row[1] is None)
                                      for sid, row in before.items())


def _saved_passages(group: dict[str, Any]) -> list[dict[str, Any]]:
    return group["passages"] + group.get("earlier_assessments", [])


def _retained_assessments(group: dict[str, Any], shown: set[int]) -> list[dict[str, Any]]:
    if not group:
        return []
    return [{k: v for k, v in passage.items() if k != "changed"}
            for passage in _saved_passages(group)
            if not passage["changed"] and passage["assessment"] and passage["chunk_id"] not in shown
            ][:EARLIER_ASSESSMENT_LIMIT]


def _same_search(review: dict[str, Any], queries: list[str], semantic: bool, scopes: dict) -> bool:
    return (not review.get("claim_changed") and review["queries"] == queries
            and bool(review.get("semantic_requested")) == semantic and set(review["scopes"]) == set(scopes))


def _passage_origin(claim: dict[str, Any]) -> Callable[[dict[str, Any]], tuple[tuple[str, str], str]]:
    """Compare with current cited support. Separate source records alone carry no lineage proof."""
    @cache
    def lineage(source_id: str) -> str | None:
        return (works.lineage_of(source_id) or {}).get("work_id")

    def origin(row: dict[str, Any]) -> tuple[str, str]:
        return claims.evidence_origin(row, lineage(row["source_id"]))

    support = claims.cited_evidence(claim["evidence"])["support"]
    cited_sources = {row["source_id"] for row in support}
    cited_origins = {origin(row) for row in support}
    all_support_has_work = bool(cited_origins) and all(kind == "lineage" for kind, _ in cited_origins)

    def compare(passage: dict[str, Any]) -> tuple[tuple[str, str], str]:
        key = origin(passage)
        if passage["source_id"] in cited_sources or key in cited_origins:
            return key, "already_cited"
        if key[0] == "lineage" and all_support_has_work:
            return key, "different_recorded_work"
        return key, "unverified"

    return compare


def _origin_fields(key: tuple[str, str], status: str) -> dict[str, Any]:
    return {"origin": key[1], "same_origin_as_support": status == "already_cited", "origin_status": status}


def find(project_id: str, claim_id: str, query: str, alternate: str, *, semantic: bool = False,
         include_library: bool = False, precedent: str = "", counter: str = "", full: bool = False) -> dict[str, Any] | None:
    claim = claims.get(claim_id)
    if not claim or claim["project_id"] != project_id:
        return None

    queries = list(dict.fromkeys(q for q in (query.strip() or claim["text"][:500], alternate.strip(),
                                            precedent.strip(), counter.strip()) if q))
    modes = []
    project_sources = db.project_source_ids(project_id)
    scopes = {"project": project_sources}
    if include_library:
        scopes["library"] = library.library_scope(project_id)
    prior = load_review(project_id, claim)
    if prior and prior["claim_changed"]:
        prior = None
    same_search = bool(prior and _same_search(prior, queries, semantic, scopes))
    now = datetime.now(timezone.utc).isoformat()
    hybrid = bool(semantic and settings.embeddings_enabled)
    retrieval = {"embeddings": hybrid, "model": settings.embedding_model if hybrid else None,
                 "vectors": str(db.chunk_embedding_revision()) if hybrid else None}
    compare_origin = _passage_origin(claim)
    shown_passages: set[tuple[tuple[str, str], str]] = set()
    shown_chunks: set[int] = set()
    results: dict[str, Any] = {}
    for scope, source_ids in scopes.items():
        snapshot = db.searchable_source_snapshot(source_ids)
        previous = prior["scopes"].get(scope, {}) if prior else {}
        old_snapshot = previous.get("source_snapshot")
        same_collection = _additive_scope(old_snapshot, snapshot)
        incremental = (not full and same_search and same_collection and prior.get("retrieval") == retrieval
                       and (not retrieval["embeddings"] or previous.get("method") == "hybrid"))
        if incremental:
            to_search = [sid for sid, row in snapshot.items() if row[1] is not None and (sid not in old_snapshot or old_snapshot[sid][1] is None)]
        else:
            to_search = [sid for sid, row in snapshot.items() if row[1] is not None]
        kept = {p["chunk_id"]: p for p in _saved_passages(previous) if not p["changed"]} if previous else {}
        query_hits = []
        scope_modes = []
        if to_search:
            for q in queries:
                if retrieval["embeddings"]:
                    from . import usage
                    try:
                        usage.guard()
                        hits = search.search(q, limit=24, source_ids=to_search, per_source_cap=2,
                                             strict=True, rerank=False)
                        scope_modes.append("hybrid")
                    except (usage.BudgetPaused, search.RetrievalUnavailable):
                        scope_modes.append("keyword")
                        hits = search.search_fts(q, limit=24, source_ids=to_search, per_source_cap=2)
                else:
                    scope_modes.append("keyword")
                    hits = search.search_fts(q, limit=24, source_ids=to_search, per_source_cap=2)
                query_hits.append(hits)
        if incremental:
            query_hits = list(zip_longest(*query_hits))
            query_hits.extend((p,) for p in previous["passages"] if p["chunk_id"] in kept)
        else:
            query_hits = zip_longest(*query_hits)
        passages = []
        origins: Counter[tuple[str, str]] = Counter()
        # Give each query a turn before reading further down another query's results.
        # Distinct passages can share a Work; repeated text from that Work cannot.
        for hit in (hit for row in query_hits for hit in row if hit is not None):
            key, status = compare_origin(hit)
            passage_key = (key, _fingerprint(" ".join(hit["text"][:1800].casefold().split())))
            if hit["chunk_id"] in shown_chunks or passage_key in shown_passages or origins[key] >= PASSAGES_PER_ORIGIN:
                continue
            shown_chunks.add(hit["chunk_id"])
            shown_passages.add(passage_key)
            origins[key] += 1
            saved_hit = kept.get(hit["chunk_id"])
            passages.append({**hit, "text": hit["text"][:1800],
                             "excerpt_truncated": hit.get("excerpt_truncated", len(hit["text"]) > 1800),
                             "fingerprint": hit.get("fingerprint") or _fingerprint(hit["text"]),
                             "source_revision": db.source_revision(hit["source_id"], persist=False),
                             **_origin_fields(key, status),
                             "assessment": saved_hit["assessment"] if saved_hit else ""})
            if len(passages) == PASSAGES_PER_SCOPE:
                break
        if incremental:
            scope_modes.append(previous["method"])
        method = _method(scope_modes)
        modes.append(method)
        results[scope] = {"sources_in_scope": len(source_ids),
                          "searchable_sources": sum(row[1] is not None for row in snapshot.values()),
                          "scope_revision": _scope_revision(snapshot), "passages": passages,
                          "method": method, "searched_sources": len(to_search),
                          "search_mode": ("added" if to_search else "resumed") if incremental else "full",
                          "searched_at": now if to_search or not incremental else previous["searched_at"],
                          "previous_searched_at": previous.get("searched_at") if incremental else None}
    for scope, group in results.items():
        previous = prior["scopes"].get(scope, {}) if prior else {}
        group["earlier_assessments"] = _retained_assessments(previous, shown_chunks)

    return {"claim_id": claim_id, "text": claim["text"], "qualifiers": claim.get("qualifiers") or {},
            "searched_at": max(group["searched_at"] for group in results.values()), "queries": queries,
            "method": _method(modes), "retrieval": retrieval, "semantic_requested": semantic,
            "scopes": results, "passage_limit_per_scope": PASSAGES_PER_SCOPE,
            "remaining_gaps": prior.get("remaining_gaps", "") if prior else ""}


def _method(modes: list[str]) -> str:
    if modes and all(mode == "hybrid" for mode in modes):
        return "hybrid"
    return "mixed" if any(mode in ("hybrid", "mixed") for mode in modes) else "keyword"


def save_review(project_id: str, claim_id: str, review: dict[str, Any]) -> dict[str, Any]:
    """Save the latest manual review using canonical source excerpts and locators."""
    claim = claims.get(claim_id)
    if not claim or claim["project_id"] != project_id:
        raise LookupError("Claim not found in project")
    if (review["text"], review["qualifiers"]) != (claim["text"], claim.get("qualifiers") or {}):
        raise ValueError("The Claim changed. Search again before saving.")
    project_sources = set(db.project_source_ids(project_id))
    library_sources = set(library.library_scope(project_id)) if "library" in review["scopes"] else set()
    if "project" not in review["scopes"]:
        raise ValueError("Project search scope is required.")
    prior = load_review(project_id, claim)
    if prior and prior["claim_changed"]:
        prior = None
    if any(not group.get("scope_revision") for group in review["scopes"].values()):
        review["retrieval"] = None  # older clients can save assessments, but cannot assert a resumable search
    selected = [p for group in review["scopes"].values() for p in group["passages"]]
    selected_ids = {p["chunk_id"] for p in selected}
    earlier = {scope: _retained_assessments(prior["scopes"].get(scope, {}) if prior else {}, selected_ids)
               for scope in review["scopes"]}
    if not (any(p["assessment"] for p in selected) or any(earlier.values())):
        raise ValueError("Assess at least one passage before saving.")
    if len(selected_ids) != len(selected):
        raise ValueError("Passages must be unique.")
    chunks = db.get_chunks_by_ids([p["chunk_id"] for p in selected])
    revisions = {sid: db.source_revision(sid, persist=False) for sid in {p["source_id"] for p in selected}}
    compare_origin = _passage_origin(claim)
    for scope, group in review["scopes"].items():
        allowed = project_sources if scope == "project" else library_sources
        snapshot = db.searchable_source_snapshot(list(allowed))
        revision = _scope_revision(snapshot)
        group["source_snapshot"] = snapshot
        group["searched_at"] = group.get("searched_at") or review["searched_at"]
        group["method"] = group.get("method") or review["method"]
        if group.get("scope_revision") and group["scope_revision"] != revision:
            raise ValueError("The searched sources changed. Run the search again before saving.")
        saved = []
        for p in group["passages"]:
            row = chunks.get(p["chunk_id"])
            if (not row or row["source_id"] != p["source_id"] or row["source_id"] not in allowed
                    or _fingerprint(row["text"]) != p["fingerprint"] or revisions[p["source_id"]] != p["source_revision"]):
                raise ValueError("A reviewed passage changed. Search again before saving.")
            hit = search.hit_from_chunk(row, 0)
            saved.append({**hit, **p, "text": hit["text"][:1800], "excerpt_truncated": len(hit["text"]) > 1800,
                          **_origin_fields(*compare_origin(hit))})
        group["passages"] = saved
        group["earlier_assessments"] = earlier[scope]
    review["claim_id"] = claim_id
    review["passage_limit_per_scope"] = PASSAGES_PER_SCOPE
    with db.tx() as conn:
        conn.execute("UPDATE project_claims SET id=id WHERE id=? AND project_id=?", (claim_id, project_id))
        current = conn.execute("SELECT text, qualifiers FROM project_claims WHERE id=? AND project_id=?",
                               (claim_id, project_id)).fetchone()
        if not current or current["text"] != claim["text"] or json.loads(current["qualifiers"] or "{}") != review["qualifiers"]:
            raise ValueError("The Claim changed. Search again before saving.")
        for scope, group in review["scopes"].items():
            ids = db.project_source_ids(project_id) if scope == "project" else library.library_scope(project_id)
            if db.searchable_source_snapshot(ids) != group["source_snapshot"]:
                raise ValueError("The searched sources changed. Run the search again before saving.")
        conn.execute("""INSERT INTO claim_challenge_reviews (claim_id, review, saved_at) VALUES (?,?,?)
                     ON CONFLICT(claim_id) DO UPDATE SET review=excluded.review, saved_at=excluded.saved_at""",
                     (claim_id, json.dumps(review, ensure_ascii=False), time.time()))
    return load_review(project_id, claim)


def load_review(project_id: str, claim: dict[str, Any]) -> dict[str, Any] | None:
    row = db.connect().execute("SELECT review, saved_at FROM claim_challenge_reviews WHERE claim_id=?", (claim["id"],)).fetchone()
    if not row:
        return None
    review = json.loads(row["review"])
    review["saved_at"] = row["saved_at"]
    review["claim_changed"] = (review["text"], review["qualifiers"]) != (claim["text"], claim.get("qualifiers") or {})
    compare_origin = _passage_origin(claim)
    project_sources = set(db.project_source_ids(project_id))
    library_sources = set(library.library_scope(project_id)) if "library" in review["scopes"] else set()
    selected = [p for group in review["scopes"].values() for p in _saved_passages(group)]
    chunks = db.get_chunks_by_ids([p["chunk_id"] for p in selected])
    revisions = {sid: db.source_revision(sid, persist=False) for sid in {p["source_id"] for p in selected}}
    for scope, group in review["scopes"].items():
        allowed = project_sources if scope == "project" else library_sources
        snapshot = db.searchable_source_snapshot(list(allowed))
        revision = _scope_revision(snapshot, legacy=group.get("source_snapshot") is None)
        group["scope_changed"] = bool(group.get("scope_revision") and group["scope_revision"] != revision)
        for p in _saved_passages(group):
            chunk = chunks.get(p["chunk_id"])
            p["changed"] = (p["source_id"] not in allowed or not chunk or chunk["source_id"] != p["source_id"]
                            or _fingerprint(chunk["text"]) != p["fingerprint"]
                            or revisions[p["source_id"]] != p["source_revision"])
            p.update(_origin_fields(*compare_origin(p)))
    return review
