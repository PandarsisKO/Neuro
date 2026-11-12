"""On-demand candidate retrieval for a Claim review. Search results are leads for the reviewer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import claims, db, library, search, works
from .config import settings

PASSAGES_PER_SCOPE = 8


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
