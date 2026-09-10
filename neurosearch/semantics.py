"""T1 — what the corpus has never explained (0.61.0).

Every chunk in Kyle's library has had an embedding since the first release; the objects DERIVED from those chunks —
findings and Claims — never did. That single gap is why none of these questions could be answered without paying a
model to re-read transcripts:

  * which passages support a Claim that nobody has attached as evidence?
  * which passages does no Claim come near — the material we own and have never explained?
  * is a dense cluster of passages sitting there with no Claim representing it (a blind spot)?
  * are two Claims the same Claim in different words?

Measured on his corpus before building this (2026-09-10): 35,029 chunks, **100% embedded**; 13,371 Claims and
12,301 findings, **none embedded**; and only **25.5% of chunks contain a piece of claim evidence**, with 300
sources having produced nothing traceable at all. So the corpus is three-quarters unexplained, and the instrument
for finding the interesting quarter of THAT costs about three cents once (~1.3 M tokens at the embedding price).

Two rules this module holds to.

**No absolute similarity constants.** A cosine threshold that separates "covered" from "unexplained" is exactly the
kind of number this project has been wrong about four times in two days (`CLUSTER_MAX`, `NEAR_JACCARD`,
`CREATOR_STRONG_PER_SOURCE`, and in 0.60.2 both the three-character token rule and IDF weighting). So the cut is a
PERCENTILE of the project's own distribution — the same self-calibrating shape that fixed
`candidates.CREATOR_PROVEN_QUANTILE` — and every answer publishes the distribution it was cut from, so the choice
can be checked against real data later instead of trusted now.

**Nothing here changes state.** These are read-only views over vectors. A Claim's status still moves only through
`claims.set_status`, evidence is still attached by the existing paths, and a finding's status still changes only
through `POST /api/notes/bulk-status`. This module proposes; it never decides.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from . import db
from .config import settings

log = logging.getLogger(__name__)

BATCH = 96                     # matches embeddings.BATCH: one request per batch, committed as it lands
UNCOVERED_QUANTILE = 0.25      # "unexplained" = the bottom quarter of THIS project's own best-Claim similarity
BLIND_SPOT_MIN = 4             # passages that must agree with each other before a cluster is worth reporting
BLIND_SPOT_QUANTILE = 0.90     # how close two passages must be to count as the same topic (this project's own p90)
DUPLICATE_QUANTILE = 0.99      # a Claim pair this close, by the project's own distribution, is worth a look
TOP_PASSAGES = 5               # candidate passages offered per Claim
SAMPLE_PAIRS = 200_000         # cap on the pair sample used to derive a percentile (bounded, deterministic order)


# ------------------------------------------------------------------ embedding the derived objects

def embed_pending(kind: str, limit: int = 2000, project_id: str | None = None) -> dict[str, Any]:
    """Embed findings ("note") or Claims ("claim") that have no vector yet. Idempotent and resumable in the same
    way `embeddings.embed_pending` is for chunks: each batch is committed as it lands, so a crash costs only the
    batch in flight."""
    if not settings.embeddings_enabled:
        return {"kind": kind, "embedded": 0, "skipped": "no embedding key configured"}
    from .embeddings import embed_texts
    done = 0
    while done < limit:
        rows = db.derived_missing_embeddings(kind, limit=min(BATCH, limit - done), project_id=project_id)
        if not rows:
            break
        vecs = embed_texts([r["text"] for r in rows])
        db.set_derived_embeddings(kind, list(zip([r["id"] for r in rows], vecs)))
        done += len(rows)
    counts = db.derived_embedding_counts(project_id)
    return {"kind": kind, "embedded": done, "counts": counts}


def embed_all(limit_per_kind: int = 2000, project_id: str | None = None) -> dict[str, Any]:
    return {k: embed_pending(k, limit_per_kind, project_id) for k in db.DERIVED_KINDS}


def status(project_id: str | None = None) -> dict[str, Any]:
    c = db.derived_embedding_counts(project_id)
    pending = sum(v["pending"] for v in c.values())
    return {"counts": c, "pending": pending, "ready": pending == 0,
            "note": ("Findings and Claims carry their own vectors from 0.61.0. Until the backfill finishes, the "
                     "views below cover only what has been embedded, and they say how much that is.")}


# ------------------------------------------------------------------ distribution helpers (no absolute thresholds)

def _pct(values: np.ndarray, q: float) -> float:
    if values.size == 0:
        return 0.0
    return float(np.quantile(values, q))


def _describe(values: np.ndarray) -> dict[str, Any]:
    """The distribution a cut was taken from, so the cut can be argued with."""
    if values.size == 0:
        return {"n": 0}
    return {"n": int(values.size), "min": round(float(values.min()), 4), "p25": round(_pct(values, 0.25), 4),
            "median": round(_pct(values, 0.5), 4), "p75": round(_pct(values, 0.75), 4),
            "p90": round(_pct(values, 0.9), 4), "max": round(float(values.max()), 4)}


def _project_chunk_matrix(project_id: str) -> tuple[np.ndarray, list[int]]:
    ids = db.project_source_ids(project_id, ready_only=True)
    if not ids:
        return np.zeros((0, 0), dtype=np.float32), []
    return db.load_embedding_matrix(ids)


def _best_similarity(chunks: np.ndarray, claims: np.ndarray) -> np.ndarray:
    """For each chunk, its similarity to the nearest Claim. Vectors are already unit-normalised on write, so a dot
    product is the cosine and the whole thing is one matrix multiply."""
    if chunks.size == 0 or claims.size == 0:
        return np.zeros((chunks.shape[0] if chunks.size else 0,), dtype=np.float32)
    return (chunks @ claims.T).max(axis=1)


# ------------------------------------------------------------------ the four views

def claim_coverage(project_id: str, limit: int = 40) -> dict[str, Any]:
    """For each Claim, the passages this project owns that look like evidence for it and are NOT attached.

    This is the cheap half of an Evidence Target: the project may already own the answer. It proposes candidates
    with their locators; attaching one stays the existing path."""
    cm, cids = db.load_derived_matrix("claim", project_id)
    chunks, chunk_ids = _project_chunk_matrix(project_id)
    out: dict[str, Any] = {"project_id": project_id, "claims": len(cids), "passages": len(chunk_ids), "rows": [],
                           "distribution": {}}
    if not len(cids) or not len(chunk_ids):
        out["note"] = "nothing to compare yet — embed the Claims first (or the project has no ready sources)"
        return out
    sims = cm @ chunks.T                                   # [claims, chunks]
    out["distribution"] = _describe(sims.max(axis=1))
    attached: dict[str, set[int]] = {}
    for r in db.connect().execute(
            "SELECT e.claim_id cid, c.id chid FROM claim_evidence e JOIN chunks c "
            "ON c.source_id = e.source_id AND e.start >= c.start AND e.start < c.end "
            "WHERE e.claim_id IN (SELECT id FROM project_claims WHERE project_id=?)", (project_id,)).fetchall():
        attached.setdefault(r["cid"], set()).add(int(r["chid"]))
    claim_rows = {r["id"]: dict(r) for r in db.connect().execute(
        "SELECT id, text, strength, readiness, importance FROM project_claims WHERE project_id=?"
        if _has_column("project_claims", "importance") else
        "SELECT id, text, strength, readiness FROM project_claims WHERE project_id=?", (project_id,)).fetchall()}
    order = np.argsort(-sims.max(axis=1))
    for i in order:
        cid = cids[int(i)]
        have = attached.get(cid, set())
        best = np.argsort(-sims[int(i)])[:TOP_PASSAGES * 3]
        cands = []
        for j in best:
            chid = chunk_ids[int(j)]
            if chid in have:
                continue
            cands.append({"chunk_id": chid, "similarity": round(float(sims[int(i), int(j)]), 4)})
            if len(cands) >= TOP_PASSAGES:
                break
        if not cands:
            continue
        row = claim_rows.get(cid) or {"id": cid, "text": ""}
        out["rows"].append({"claim_id": cid, "claim": (row.get("text") or "")[:200],
                            "strength": row.get("strength"), "attached_passages": len(have),
                            "candidates": _hydrate(cands)})
        if len(out["rows"]) >= limit:
            break
    out["note"] = ("Passages this project already owns that look like evidence for a Claim and are not attached to "
                   "it. Nothing is attached by this view; similarity is a reason to look, never a verdict.")
    return out


def uncovered_passages(project_id: str, limit: int = 60) -> dict[str, Any]:
    """The material this project owns and has never explained: passages furthest from every Claim it holds.

    The cut is this project's own bottom quartile (`UNCOVERED_QUANTILE`), never an absolute cosine, and the
    distribution it came from is returned alongside."""
    cm, cids = db.load_derived_matrix("claim", project_id)
    chunks, chunk_ids = _project_chunk_matrix(project_id)
    out: dict[str, Any] = {"project_id": project_id, "claims": len(cids), "passages": len(chunk_ids), "rows": []}
    if not len(chunk_ids):
        out["note"] = "this project has no ready sources yet"
        return out
    if not len(cids):
        out["note"] = ("no Claims carry vectors yet, so nothing can be called explained — run the embedding "
                       "backfill, or approve some findings so Claims exist")
        return out
    best = _best_similarity(chunks, cm)
    cut = _pct(best, UNCOVERED_QUANTILE)
    out["distribution"] = _describe(best)
    out["cut"] = round(cut, 4)
    out["quantile"] = UNCOVERED_QUANTILE
    idx = [int(i) for i in np.argsort(best)[: max(limit, 0)]]
    out["rows"] = _hydrate([{"chunk_id": chunk_ids[i], "similarity": round(float(best[i]), 4)} for i in idx])
    out["uncovered"] = int((best <= cut).sum())
    out["share"] = round(float((best <= cut).mean()), 4)
    out["note"] = ("Ranked by distance from every Claim this project holds. The cut is this project's own bottom "
                   f"{int(UNCOVERED_QUANTILE * 100)}% — a relative measure, because a cosine that means "
                   "'unexplained' in one corpus means nothing in another. `distribution` is what it was cut from.")
    return out


def blind_spots(project_id: str, limit: int = 12) -> dict[str, Any]:
    """Groups of passages that agree with each other and with no Claim: a topic the corpus covers and the research
    state does not. Greedy single-pass clustering over the uncovered set — cheap, deterministic, and no new index."""
    cm, cids = db.load_derived_matrix("claim", project_id)
    chunks, chunk_ids = _project_chunk_matrix(project_id)
    out: dict[str, Any] = {"project_id": project_id, "clusters": [], "claims": len(cids)}
    if not len(chunk_ids) or not len(cids):
        out["note"] = "not enough embedded material yet to look for blind spots"
        return out
    best = _best_similarity(chunks, cm)
    cut = _pct(best, UNCOVERED_QUANTILE)
    pool = [int(i) for i in np.where(best <= cut)[0]]
    if len(pool) < BLIND_SPOT_MIN:
        out["note"] = "nothing in this project is far enough from its Claims to look like a blind spot"
        return out
    sub = chunks[pool]
    # the "same topic" threshold is also this project's own: a sample of pair similarities, taken in a fixed order
    step = max(1, (len(pool) * len(pool)) // SAMPLE_PAIRS)
    sample = (sub[::step] @ sub[::step].T)
    tri = sample[np.triu_indices(sample.shape[0], k=1)] if sample.shape[0] > 1 else np.zeros((0,), dtype=np.float32)
    near = _pct(tri, BLIND_SPOT_QUANTILE) if tri.size else 1.0
    out["distribution"] = {"best_claim_similarity": _describe(best), "pair_similarity": _describe(tri)}
    out["thresholds"] = {"uncovered_at_or_below": round(cut, 4), "same_topic_at_or_above": round(near, 4),
                         "quantiles": {"uncovered": UNCOVERED_QUANTILE, "same_topic": BLIND_SPOT_QUANTILE}}
    taken: set[int] = set()
    clusters: list[list[int]] = []
    sims = sub @ sub.T
    for a in range(len(pool)):
        if a in taken:
            continue
        members = [a] + [b for b in range(len(pool)) if b != a and b not in taken and sims[a, b] >= near]
        if len(members) >= BLIND_SPOT_MIN:
            taken.update(members)
            clusters.append(members)
    clusters.sort(key=lambda m: -len(m))
    for m in clusters[:limit]:
        rows = _hydrate([{"chunk_id": chunk_ids[pool[i]], "similarity": round(float(best[pool[i]]), 4)} for i in m[:6]])
        srcs = sorted({r.get("source_id") for r in rows if r.get("source_id")})
        out["clusters"].append({"size": len(m), "sources": len(srcs), "passages": rows,
                                "why": (f"{len(m)} passages across {len(srcs)} source(s) agree with each other and "
                                        "with none of this project's Claims")})
    out["note"] = ("A cluster here is a question the corpus can answer and the research state has never asked. It "
                   "is a prompt to look, not a Claim — nothing is created by this view.")
    return out


def duplicate_claims(project_id: str, limit: int = 40) -> dict[str, Any]:
    """Claim pairs close enough to be the same proposition in different words. Reported, never merged: merging is a
    judgement about meaning and `claims.set_status` is the only door."""
    cm, cids = db.load_derived_matrix("claim", project_id)
    out: dict[str, Any] = {"project_id": project_id, "claims": len(cids), "pairs": []}
    if len(cids) < 2:
        out["note"] = "not enough embedded Claims to compare"
        return out
    sims = cm @ cm.T
    np.fill_diagonal(sims, -1.0)
    tri = sims[np.triu_indices(len(cids), k=1)]
    cut = _pct(tri, DUPLICATE_QUANTILE)
    out["distribution"] = _describe(tri)
    out["cut"] = round(cut, 4)
    out["quantile"] = DUPLICATE_QUANTILE
    texts = {r["id"]: r["text"] for r in db.connect().execute(
        "SELECT id, text FROM project_claims WHERE project_id=?", (project_id,)).fetchall()}
    seen: set[tuple[Any, Any]] = set()
    for a, b in zip(*np.where(sims >= cut)):
        i, j = cids[int(a)], cids[int(b)]
        key = tuple(sorted((str(i), str(j))))
        if i == j or key in seen:
            continue
        seen.add(key)
        out["pairs"].append({"a": i, "b": j, "similarity": round(float(sims[int(a), int(b)]), 4),
                             "a_text": (texts.get(i) or "")[:180], "b_text": (texts.get(j) or "")[:180]})
        if len(out["pairs"]) >= limit:
            break
    out["pairs"].sort(key=lambda p: -p["similarity"])
    out["note"] = ("The cut is this project's own top 1% of pair similarity, so it adapts to how varied the Claim "
                   "set is. Two Claims can be this close and still differ in a qualifier that matters — which is "
                   "why nothing is merged here.")
    return out


def overview(project_id: str) -> dict[str, Any]:
    """One request for the panel: how much is embedded, how much is unexplained, and the biggest blind spots."""
    st = status(project_id)
    unc = uncovered_passages(project_id, limit=8)
    bs = blind_spots(project_id, limit=4)
    return {"project_id": project_id, "embedding": st,
            "unexplained": {"passages": unc.get("uncovered", 0), "of": unc.get("passages", 0),
                            "share": unc.get("share", 0.0), "cut": unc.get("cut"),
                            "distribution": unc.get("distribution", {}), "examples": unc.get("rows", [])[:5]},
            "blind_spots": bs.get("clusters", []),
            "note": ("Unexplained means far from every Claim this project holds, cut at this project's own bottom "
                     f"{int(UNCOVERED_QUANTILE * 100)}%. It is a place to look, not a failure.")}


# ------------------------------------------------------------------ hydration

def _has_column(table: str, column: str) -> bool:
    try:
        return any(r[1] == column for r in db.connect().execute(f"PRAGMA table_info({table})").fetchall())
    except Exception:  # noqa: BLE001
        return False


def _hydrate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn chunk ids into something a person can read: the passage, its source and its locator."""
    ids = [r["chunk_id"] for r in rows]
    if not ids:
        return []
    qs = ",".join("?" for _ in ids)
    got = {r["id"]: dict(r) for r in db.connect().execute(
        f"SELECT c.id, c.source_id, c.start, c.end, c.text, s.title, s.channel, s.platform "
        f"FROM chunks c JOIN sources s ON s.id=c.source_id WHERE c.id IN ({qs})", ids).fetchall()}
    out = []
    for r in rows:
        g = got.get(r["chunk_id"])
        if not g:
            continue
        try:
            from .search import locator_for
            loc = locator_for(g["source_id"], float(g["start"] or 0))
        except Exception:  # noqa: BLE001
            loc = None
        out.append({**r, "source_id": g["source_id"], "title": g.get("title"), "channel": g.get("channel"),
                    "start": g.get("start"), "locator": loc, "text": (g.get("text") or "")[:300]})
    return out
