"""On-demand candidate retrieval for a Claim review. Search results are leads for the reviewer."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from . import claims, db, library, search, works
from .config import settings

PASSAGES_PER_SCOPE = 8


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()



def find(project_id: str, claim_id: str, query: str, alternate: str, *, semantic: bool = False,
         include_library: bool = False) -> dict[str, Any] | None:
    claim = claims.get(claim_id)
    if not claim or claim["project_id"] != project_id:
        return None

    queries = list(dict.fromkeys(q for q in (query.strip() or claim["text"][:500], alternate.strip()) if q))
    modes = []
    project_sources = db.project_source_ids(project_id)
    scopes = {"project": project_sources}
    if include_library:
        scopes["library"] = library.library_scope(project_id)
    lineage: dict[str, str | None] = {}

    def origin(row: dict[str, Any]) -> tuple[str, str]:
        sid = row["source_id"]
        if sid not in lineage:
            lineage[sid] = (works.lineage_of(sid) or {}).get("work_id")
        return claims.evidence_origin(row, lineage[sid])

    cited = {origin(row) for row in claims.cited_evidence(claim["evidence"])["support"]}
    shown_origins: set[tuple[str, str]] = set()
    results: dict[str, Any] = {}
    for scope, source_ids in scopes.items():
        candidates = {}
        if source_ids:
            for q in queries:
                if semantic and settings.embeddings_enabled:
                    from . import usage
                    try:
                        usage.guard()
                        hits = search.search(q, limit=24, source_ids=source_ids, per_source_cap=2,
                                             strict=True, rerank=False)
                        modes.append("hybrid")
                    except (usage.BudgetPaused, search.RetrievalUnavailable):
                        modes.append("keyword_fallback")
                        hits = search.search_fts(q, limit=24, source_ids=source_ids, per_source_cap=2)
                else:
                    modes.append("keyword")
                    hits = search.search_fts(q, limit=24, source_ids=source_ids, per_source_cap=2)
                for rank, hit in enumerate(hits):
                    previous = candidates.get(hit["chunk_id"])
                    if previous is None or rank < previous[0]:
                        candidates[hit["chunk_id"]] = (rank, hit)
        passages = []
        # One Work representative per search. Prefer an attached passage over a library copy.
        for _, hit in sorted(candidates.values(), key=lambda row: row[0]):
            key = origin(hit)
            if key in shown_origins:
                continue
            shown_origins.add(key)
            passages.append({**hit, "text": hit["text"][:1800],
                             "excerpt_truncated": len(hit["text"]) > 1800,
                             "fingerprint": _fingerprint(hit["text"]),
                             "source_revision": db.source_revision(hit["source_id"], persist=False),
                             "origin": key[1], "same_origin_as_support": key in cited})
            if len(passages) == PASSAGES_PER_SCOPE:
                break
        results[scope] = {"sources_in_scope": len(source_ids), "passages": passages}

    method = "keyword"
    if modes and all(mode == "hybrid" for mode in modes):
        method = "hybrid"
    elif "hybrid" in modes:
        method = "mixed"
    return {"claim_id": claim_id, "text": claim["text"], "qualifiers": claim.get("qualifiers") or {},
            "searched_at": datetime.now(timezone.utc).isoformat(), "queries": queries, "method": method,
            "semantic_requested": semantic, "scopes": results, "passage_limit_per_scope": PASSAGES_PER_SCOPE}


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
    selected = [p for group in review["scopes"].values() for p in group["passages"]]
    if not any(p["assessment"] for p in selected):
        raise ValueError("Assess at least one passage before saving.")
    if len({p["chunk_id"] for p in selected}) != len(selected):
        raise ValueError("Passages must be unique.")
    chunks = db.get_chunks_by_ids([p["chunk_id"] for p in selected])
    revisions = {sid: db.source_revision(sid, persist=False) for sid in {p["source_id"] for p in selected}}
    cited_origins = {claims.evidence_origin(e, (works.lineage_of(e["source_id"]) or {}).get("work_id"))
                     for e in claims.cited_evidence(claim["evidence"])["support"]}
    for scope, group in review["scopes"].items():
        allowed = project_sources if scope == "project" else library_sources
        saved = []
        for p in group["passages"]:
            row = chunks.get(p["chunk_id"])
            if (not row or row["source_id"] != p["source_id"] or row["source_id"] not in allowed
                    or _fingerprint(row["text"]) != p["fingerprint"] or revisions[p["source_id"]] != p["source_revision"]):
                raise ValueError("A reviewed passage changed. Search again before saving.")
            hit = search.hit_from_chunk(row, 0)
            sid = hit["source_id"]
            origin = claims.evidence_origin(hit, (works.lineage_of(sid) or {}).get("work_id"))
            saved.append({**hit, **p, "text": hit["text"][:1800], "excerpt_truncated": len(hit["text"]) > 1800,
                          "origin": origin[1], "same_origin_as_support": origin in cited_origins})
        group["passages"] = saved
    review["claim_id"] = claim_id
    review["passage_limit_per_scope"] = PASSAGES_PER_SCOPE
    with db.tx() as conn:
        current = conn.execute("SELECT text, qualifiers FROM project_claims WHERE id=? AND project_id=?",
                               (claim_id, project_id)).fetchone()
        if not current or current["text"] != claim["text"] or json.loads(current["qualifiers"] or "{}") != review["qualifiers"]:
            raise ValueError("The Claim changed. Search again before saving.")
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
    project_sources = set(db.project_source_ids(project_id))
    library_sources = set(library.library_scope(project_id)) if "library" in review["scopes"] else set()
    selected = [p for group in review["scopes"].values() for p in group["passages"]]
    chunks = db.get_chunks_by_ids([p["chunk_id"] for p in selected])
    revisions = {sid: db.source_revision(sid, persist=False) for sid in {p["source_id"] for p in selected}}
    for scope, group in review["scopes"].items():
        allowed = project_sources if scope == "project" else library_sources
        for p in group["passages"]:
            chunk = chunks.get(p["chunk_id"])
            p["changed"] = (p["source_id"] not in allowed or not chunk or chunk["source_id"] != p["source_id"]
                            or _fingerprint(chunk["text"]) != p["fingerprint"]
                            or revisions[p["source_id"]] != p["source_revision"])
    return review
