"""FM1 -- Field Map: reference-list clustering (Stage 14, P9C).

Prototype only. Clusters the OUTBOUND bibliographies of a small number of review/scholarly seed works already
connected to a project, to surface field areas that are repeatedly referenced externally but underrepresented in the
project's OWN extracted evidence (Findings/Claims/Evidence Targets) -- not a claim about the whole Library, and not
another discovery/search/acquisition system. See docs/FIELD-MAP-RUNG.md and docs/FM0-EXPERIMENT.md for why this
shape (reference-list clustering, not heading clustering) and why $0-only.

What this deliberately does NOT do (see FIELD-MAP-RUNG.md's "what would be wrong to build" + the FM1 mission):
  - never writes to candidates / sources / claims / evidence targets / the Planner -- CLI-only, read + report
  - never fetches for more than MAX_SEEDS seeds or makes more than MAX_SEEDS reference-fetch calls per run
  - never adds a second HTTP fetch boundary -- reuses scholar._get / scholar.fetch_crossref_references
  - never invents a polished model-generated category name for a cluster
  - never claims "the project has never researched this" -- only what the project's own extracted evidence shows
"""
from __future__ import annotations

import re
from typing import Any

from . import candidates as candidates_mod
from . import claims as claims_mod
from . import db
from . import knowledge
from . import scholar
from . import works

MAX_SEEDS = 3
MAX_REFERENCE_FETCHES = 3
MIN_CLUSTER_SIZE = 2                  # structural minimum: one distinct referenced work is not a field area
CLUSTER_OVERLAP_THRESHOLD = 0.2       # deterministic token-overlap threshold for joining a canonical work to a cluster
                                       # (share of the NEW work's own tokens already in the cluster -- titles are short,
                                       # so a strict two-sided Jaccard would never let two 4-token titles sharing one
                                       # topic word join at all; this is the same "overlap" shape as claims.overlap(),
                                       # just computed against a growing cluster token set instead of a second text)
LABEL_MIN_CLUSTER_FOR_TOKENS = 3      # below this, always label with the representative title (too few members for a
                                       # shared-token label to mean anything)
LABEL_TOKEN_SHARE = 0.6               # a token must appear in >=60% of cluster members' titles to be "shared"
COVERAGE_CLEAR = 0.5
COVERAGE_LIGHT = 0.15


# ---------------------------------------------------------------- seed discovery (local-first, per FM1 correction #2)

def _doi_of_work(w: dict[str, Any]) -> str | None:
    ids = w.get("identifiers") or []
    if isinstance(ids, str):                    # works.list_works() returns the raw works row -- identifiers is
        import json                              # still JSON text there (only works.get()/works._row() decode it)
        try:
            ids = json.loads(ids)
        except ValueError:
            ids = []
    for i in ids:
        if isinstance(i, dict) and i.get("scheme") == "doi" and i.get("value"):
            return scholar.normalise_doi(i["value"])
    return None


def _works_of_sources(source_ids: list[str]) -> list[str]:
    """Work ids that at least one of these sources is a manifestation of, via the existing work_manifestations
    relationship (G6) -- not a new identity scan, just reading the relationship that already exists."""
    if not source_ids:
        return []
    conn = db.connect()
    qmarks = ",".join("?" * len(source_ids))
    rows = conn.execute(f"SELECT DISTINCT work_id FROM work_manifestations WHERE source_id IN ({qmarks}) AND work_id IS NOT NULL", source_ids).fetchall()
    return [r["work_id"] for r in rows]


def discover_seeds(project_id: str, fetch_seeds_query: str | None = None, limit: int = MAX_SEEDS) -> list[dict[str, Any]]:
    """Preferred order (FM1 correction #2): (1) DOI-bearing project Works (explicit project relevance) (2) DOI-bearing
    project sources reached through the Works layer's existing manifestation relationship (3) project-local Crossref
    Candidate Index rows (4) only if none are sufficient, an explicit network search. Deduplicated by normalized DOI
    across all four sources before capping at `limit`; each seed carries where it came from. Nothing is persisted."""
    seeds: list[dict[str, Any]] = []
    seen_dois: set[str] = set()

    def _add(doi: str | None, title: str, provenance: str) -> None:
        if not doi or doi in seen_dois or len(seeds) >= limit:
            return
        seen_dois.add(doi)
        seeds.append({"doi": doi, "title": title or doi, "provenance": provenance})

    # (1) project Works with an explicit project-relevance row and a DOI identity
    for w in works.list_works(project_id, limit=200):
        if len(seeds) >= limit:
            break
        _add(_doi_of_work(w), w.get("title") or "", "project_work")

    # (2) project sources reached through the Works layer's manifestation relationship, not yet covered by (1)
    if len(seeds) < limit:
        source_ids = db.project_source_ids(project_id, ready_only=True)
        for wid in _works_of_sources(source_ids):
            if len(seeds) >= limit:
                break
            w = works.get(wid)
            if w:
                _add(_doi_of_work(w), w.get("title") or "", "project_source")

    # (3) project-local Crossref Candidate Index rows
    if len(seeds) < limit:
        for c in candidates_mod.list_for_project(project_id, limit=200):
            if len(seeds) >= limit:
                break
            if c.get("platform") == "crossref" and c.get("external_id"):
                _add(scholar.normalise_doi(c["external_id"]), c.get("title") or "", "candidate")

    # (4) explicit network search, opt-in only, and only if the local-first sources were not enough
    if len(seeds) < limit and fetch_seeds_query:
        try:
            for r in scholar.search(fetch_seeds_query, limit=limit - len(seeds), provider="crossref"):
                if len(seeds) >= limit:
                    break
                _add(scholar.normalise_doi(r.get("doi") or r.get("external_id") or ""), r.get("title") or "", "explicit_search")
        except scholar.ScholarUnavailable:
            pass

    return seeds


# ---------------------------------------------------------------- reference collapsing to canonical works ($0, in-memory only)

def _clean_title(t: Any) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip()[:300]


def _first_author(entry: dict[str, Any]) -> str:
    a = entry.get("author")
    return _clean_title(a).split(",")[0].split(" ")[0] if a else ""


def _canonical_key(entry: dict[str, Any]) -> tuple[str, str] | None:
    """(scheme, key) identity for one raw Crossref reference entry, or None when it carries nothing usable.
    DOI first (G6 identity order); normalized title + first author next; a bare 'unstructured' string or a
    volume/page-only stub is NOT parseable -- it counts toward raw_reference_count, never parseable_reference_count."""
    doi = scholar.normalise_doi(entry.get("DOI"))
    if doi:
        return ("doi", doi)
    title = _clean_title(entry.get("article-title") or entry.get("volume-title") or entry.get("series-title") or "")
    if title:
        tn = works.normalize_title(title)
        if tn:
            return ("title", f"{tn}|{_first_author(entry).lower()}")
    return None


def _collapse_references(seed_id: str, raw_refs: list[dict[str, Any]], canon: dict[tuple[str, str], dict[str, Any]]) -> tuple[int, int]:
    """Fold one seed's raw reference list into the shared canonical-work map. Returns (raw_count, parseable_count)
    for THIS seed. `canon[key]` accumulates: title, mention_count (raw_reference_count contribution), seed_ids."""
    raw = 0
    parseable = 0
    for entry in raw_refs:
        if not isinstance(entry, dict):
            continue
        raw += 1
        key = _canonical_key(entry)
        if key is None:
            continue
        parseable += 1
        title = _clean_title(entry.get("article-title") or entry.get("volume-title") or entry.get("series-title") or entry.get("unstructured") or key[1])
        c = canon.setdefault(key, {"key": key, "title": title, "mention_count": 0, "seed_ids": set()})
        c["mention_count"] += 1
        c["seed_ids"].add(seed_id)
        if not c["title"] and title:
            c["title"] = title
    return raw, parseable


# ---------------------------------------------------------------- deterministic clustering (existing token/Jaccard machinery)

def _cluster_canonical_works(canon_works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy deterministic clustering by title-token overlap (claims._tokens; the same overlap shape as
    claims.overlap(), computed against each cluster's accumulated token set). Stable-sorted input so ties resolve
    the same way every run; joins a work to the highest-overlap existing cluster at or above
    CLUSTER_OVERLAP_THRESHOLD, else starts a new one. No embeddings, no model call.

    Known v1 limitation: because a cluster's token set only grows, a long chain of works that each share just one
    topic word with the cluster (but not necessarily with each other) can merge into it -- acceptable for a small,
    Crossref-only, $0 prototype scoped to <=3 seeds' bibliographies; a future rung can tighten this if it proves
    to matter on real data."""
    ordered = sorted(canon_works, key=lambda w: w["key"])
    clusters: list[dict[str, Any]] = []
    for w in ordered:
        wt = claims_mod._tokens(w["title"])
        best_i, best_score = -1, 0.0
        for i, cl in enumerate(clusters):
            score = len(wt & cl["_tokens"]) / max(1, min(len(wt), len(cl["_tokens"])))
            if score >= CLUSTER_OVERLAP_THRESHOLD and score > best_score:
                best_i, best_score = i, score
        if best_i >= 0:
            cl = clusters[best_i]
            cl["members"].append(w)
            cl["_tokens"] = cl["_tokens"] | wt
        else:
            clusters.append({"members": [w], "_tokens": wt})
    return clusters


def _label_cluster(members: list[dict[str, Any]]) -> str:
    """Deterministic only (FM1 correction #5): the representative work's own title (highest mention_count, ties
    broken by canonical key), or -- only for clusters with enough members to make it meaningful -- a small set of
    tokens shared across most members' titles. Never a model-invented category name."""
    rep = sorted(members, key=lambda m: (-m["mention_count"], m["key"]))[0]
    if len(members) < LABEL_MIN_CLUSTER_FOR_TOKENS:
        return rep["title"]
    df: dict[str, int] = {}
    for m in members:
        for t in claims_mod._tokens(m["title"]):
            df[t] = df.get(t, 0) + 1
    need = max(2, int(len(members) * LABEL_TOKEN_SHARE))
    shared = sorted([t for t, n in df.items() if n >= need])
    return ", ".join(shared[:5]) if shared else rep["title"]


def _coverage_tokens(project_id: str) -> set[str]:
    """The vocabulary of the project's OWN extracted evidence state (correction #6): Findings (claims.project_vocab),
    plus Claim text and open Evidence Target questions -- never a statement about the whole Library."""
    toks: set[str] = set(claims_mod.project_vocab(project_id).keys())
    for c in claims_mod.list_for_project(project_id, status=None, with_evidence=False):
        toks |= claims_mod._tokens(c.get("text") or "")
    for t in knowledge.list_targets(project_id, status=None):
        toks |= claims_mod._tokens(t.get("question") or "")
    return toks


def _classify_coverage(cluster_tokens: set[str], project_tokens: set[str]) -> tuple[str, float | None]:
    if not project_tokens or not cluster_tokens:
        return "unknown", None
    ratio = len(cluster_tokens & project_tokens) / len(cluster_tokens)
    if ratio >= COVERAGE_CLEAR:
        state = "clearly represented in current project evidence"
    elif ratio >= COVERAGE_LIGHT:
        state = "lightly represented"
    else:
        state = "underrepresented in current extracted project evidence"
    return state, round(ratio, 3)


# ---------------------------------------------------------------- the FM1 pipeline

def build(project_id: str, fetch_seeds_query: str | None = None) -> dict[str, Any]:
    """The whole FM1 v1 pipeline. Read-only, $0, in-memory: no candidate/source/claim/target/plan write anywhere."""
    seeds = discover_seeds(project_id, fetch_seeds_query=fetch_seeds_query, limit=MAX_SEEDS)

    canon: dict[tuple[str, str], dict[str, Any]] = {}
    seeds_examined = 0
    seeds_with_reference_metadata = 0
    seeds_without_reference_metadata = 0
    raw_reference_count = 0
    parseable_reference_count = 0
    seed_fetch_notes: list[dict[str, Any]] = []

    for seed in seeds[:MAX_REFERENCE_FETCHES]:
        seeds_examined += 1
        try:
            rec = scholar.fetch_crossref_references(seed["doi"])
        except scholar.ScholarUnavailable as e:
            seeds_without_reference_metadata += 1
            seed_fetch_notes.append({"doi": seed["doi"], "provenance": seed["provenance"], "ok": False, "reason": f"{e.provider}:{e.reason}"})
            continue
        if not rec["has_reference_field"] or not rec["raw_references"]:
            seeds_without_reference_metadata += 1
            seed_fetch_notes.append({"doi": seed["doi"], "provenance": seed["provenance"], "ok": True, "has_reference_field": rec["has_reference_field"], "raw_references": 0})
            continue
        seeds_with_reference_metadata += 1
        raw, parseable = _collapse_references(seed["doi"], rec["raw_references"], canon)
        raw_reference_count += raw
        parseable_reference_count += parseable
        seed_fetch_notes.append({"doi": seed["doi"], "provenance": seed["provenance"], "ok": True, "has_reference_field": True, "raw_references": raw, "parseable_references": parseable})

    canonical_work_count = len(canon)
    insufficient = seeds_with_reference_metadata == 0 or parseable_reference_count == 0

    limitations: dict[str, Any] = {
        "seeds_examined": seeds_examined,
        "seeds_with_reference_metadata": seeds_with_reference_metadata,
        "seeds_without_reference_metadata": seeds_without_reference_metadata,
        "raw_reference_count": raw_reference_count,
        "parseable_reference_count": parseable_reference_count,
        "canonical_work_count": canonical_work_count,
        "note": ("A missing/empty Crossref `reference` array does not prove the underlying work has no bibliography "
                 "-- Crossref metadata is depositor-supplied. This limitation is recorded, not treated as evidence of absence."),
    }

    result: dict[str, Any] = {
        "project_id": project_id,
        "seeds": seeds,
        "seed_fetch_notes": seed_fetch_notes,
        "limitations": limitations,
        "status": "insufficient_reference_metadata" if insufficient else "ok",
        "field_areas": [],
    }
    if not seeds:
        result["status"] = "no_seeds"
        return result
    if insufficient:
        return result

    project_tokens = _coverage_tokens(project_id)
    canon_list = [dict(v, key_str=f"{k[0]}:{k[1]}") for k, v in canon.items()]
    clusters = _cluster_canonical_works(canon_list)

    areas = []
    for cl in clusters:
        members = cl["members"]
        if len(members) < MIN_CLUSTER_SIZE:
            continue                                    # structural minimum: one work is not a field area
        reference_count = sum(m["mention_count"] for m in members)
        referenced_work_count = len(members)
        seed_ids: set[str] = set()
        for m in members:
            seed_ids |= m["seed_ids"]
        seed_count = len(seed_ids)
        label = _label_cluster(members)
        cluster_tokens = cl["_tokens"]
        coverage_state, coverage_ratio = _classify_coverage(cluster_tokens, project_tokens)
        areas.append({
            "label": label,
            "reference_count": reference_count,           # raw mentions -- may repeat one work from one seed's bibliography
            "referenced_work_count": referenced_work_count,  # distinct canonical works in this cluster
            "seed_count": seed_count,                      # distinct SEED bibliographies contributing -- inspectability only, not an authority score
            "coverage": coverage_state,
            "coverage_ratio": coverage_ratio,
            "representative_works": sorted([m["title"] for m in members], key=str)[:5],
        })

    # deterministic order: most externally referenced first, tie-broken by label
    areas.sort(key=lambda a: (-a["referenced_work_count"], a["label"]))
    result["field_areas"] = areas
    return result
