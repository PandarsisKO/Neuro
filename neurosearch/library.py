"""Rung G4 — Global Library Intelligence: use evidence the user already owns before spending on new evidence.

    PROJECT EVIDENCE → GLOBAL LIBRARY (this module) → CANDIDATE INDEX → EXTERNAL DISCOVERY

Two layers of Source Profile, both strictly PROJECT-NEUTRAL (never built from project findings, project summaries,
relevance or steering — those live in (project, source) context and stay out of global recall):

  baseline  $0. From what is already stored: source metadata (title, creator, platform, dates, duration, kind, tags,
            host), top terms of the source's own chunks, deterministic AUTHORITY SIGNALS with their basis (government /
            education / organisation domain, document kind, creator identity), a centroid of the chunk vectors as a
            COARSE signal and a small set of representative "topic vectors" (farthest-point sampled) so a five-minute
            insurance passage in a three-hour interview keeps its own vector and is still recoverable.
  enriched  one lazy `library.profile` model call — only when the source has become a plausible candidate for a
            Discover query, a gap, or a new project — cached globally, versioned by source revision + prompt/schema
            version, batched opportunistically (50%) when enough wanted profiles accumulate.

Library recall (`recall`) works with ZERO enriched profiles: chunk-level FTS + vector retrieval over the library's
sources outside the project (never averaged away), plus baseline term hits. Enrichment only adds ranking signal and
explanation. Results are SUGGESTIONS with provenance to the global source/revision; nothing is attached until the
user says so, so the project evidence boundary is intact. Authority is reported as signals + basis, never as a
permanent verdict — the project decides what counts as authoritative for its question.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from typing import Any
from urllib.parse import urlparse

import numpy as np

from . import db
from .config import settings

log = logging.getLogger(__name__)

BASELINE_VERSION = "baseline-v1"
PROMPT_VERSION = "profile-v1"
TOPIC_VECTORS = 6                   # representative chunk vectors per source
TOP_TERMS = 30
RECALL_CHUNKS = 60                  # chunk-level candidates before grouping by source
PER_SOURCE_CHUNKS = 3
MIN_SCORE = 0.012                   # ≈ one RRF rank ≤ 25 in either channel: below this a source is not suggested (precision bias)
# RRF scores are RANK-based: the top hit of ANY query looks the same, so rank alone cannot tell "covered" from "nearest
# thing we own". Precision therefore also needs an ABSOLUTE signal: the share of the query's content terms that actually
# appear in the matched passages (+ title/creator). Below MIN_COVERAGE a source is not suggested at all.
MIN_COVERAGE = 0.4
STRONG_COVERAGE = 0.6               # what Discover may treat as "strong" (together with ≥2 passages) — still relevance, not sufficiency
BATCH_MIN = 8                       # wanted profiles that trigger an opportunistic batch
INTERACTIVE_MAX = 3                 # profiles enriched inline when a query needs them right now
PROFILE_CHARS = 14000               # text sample sent for enrichment (head + topic chunks)

_STOP = set("""a an the and or of to in on for with by from at as is are was were be been being this that these those it its into over under
about after before between during than then there their them they you your we our us he she his her him not no nor so if but can could would should
will may might must do does did done have has had having more most some such only also very just like what when where which who whom why how all any
each other into out up down off again further once here because while both few own same too than s t don ve ll re m d""".split())


# ------------------------------------------------------------------ baseline ($0)

def _terms(texts: list[str], n: int = TOP_TERMS) -> list[str]:
    c: Counter[str] = Counter()
    for t in texts:
        for w in re.findall(r"[a-z][a-z0-9\-']{2,}", t.lower()):
            if w not in _STOP and not w.isdigit():
                c[w] += 1
    return [w for w, _ in c.most_common(n)]


def _domain_class(host: str) -> str | None:
    h = host.lower()
    if h.endswith((".gov", ".gov.uk", ".gc.ca", ".gov.au", ".mil")) or ".gov." in h:
        return "government"
    if h.endswith((".edu", ".ac.uk", ".edu.au")):
        return "education"
    if h.endswith((".org", ".int")):
        return "organisation"
    return None


def authority_signals(src: dict[str, Any]) -> list[dict[str, str]]:
    """Deterministic, provenance-backed source characteristics. Facts with a basis — never a verdict."""
    out: list[dict[str, str]] = []
    url = src.get("url") or ""
    host = urlparse(url).netloc.lower().replace("www.", "") if url.startswith("http") else ""
    dc = _domain_class(host) if host else None
    if dc:
        out.append({"signal": "domain", "value": dc, "basis": f"host {host}"})
    elif host:
        out.append({"signal": "domain", "value": "commercial/other", "basis": f"host {host}"})
    p = src.get("platform")
    kind = {"youtube": "video", "instagram": "social post", "podcast": "podcast episode", "document": "document", "spreadsheet": "spreadsheet",
            "web": "web page", "file": "uploaded media", "manual": "pasted text", "media": "media"}.get(p or "", p or "unknown")
    out.append({"signal": "kind", "value": kind, "basis": f"platform {p}"})
    title = (src.get("title") or "").lower()
    if p == "document" and re.search(r"\b(publication|pub\.? ?\d+|form \d+|instructions|regulation|statute|code of|manual|handbook|advisory circular|\bad\b|notice|bulletin)\b", title):
        out.append({"signal": "document_kind", "value": "official-style document", "basis": f"title pattern: {src.get('title')!r}"})
    if src.get("channel"):
        out.append({"signal": "creator", "value": str(src["channel"]), "basis": "channel/author metadata"})
    if src.get("published_at"):
        out.append({"signal": "published", "value": str(src["published_at"]), "basis": "source metadata"})
    if src.get("transcript_kind"):
        out.append({"signal": "text_origin", "value": str(src["transcript_kind"]), "basis": "how the text was obtained (captions / transcribed / document / manual)"})
    return out


def _farthest_points(mat: np.ndarray, k: int) -> list[int]:
    """Greedy farthest-point sampling: k indexes covering the spread of the chunk vectors (minority topics survive)."""
    n = mat.shape[0]
    if n <= k:
        return list(range(n))
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    m = mat / norms
    centroid = m.mean(axis=0)
    chosen = [int(np.argmin(m @ centroid))]                     # start with the chunk least like the average: the outlier first
    dist = 1.0 - m @ m[chosen[0]]
    while len(chosen) < k:
        nxt = int(np.argmax(dist))
        chosen.append(nxt)
        dist = np.minimum(dist, 1.0 - m @ m[nxt])
    return chosen


def build_baseline(src: dict[str, Any]) -> tuple[dict[str, Any], bytes | None, bytes | None, list[int]]:
    chunks = db.get_chunks(src["id"])
    texts = [c["text"] for c in chunks]
    total = sum(len(t) for t in texts)
    tags = src.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    baseline = {
        "version": BASELINE_VERSION, "title": src.get("title"), "creator": src.get("channel"), "platform": src.get("platform"),
        "url": src.get("url"), "published_at": src.get("published_at"), "duration": src.get("duration"), "transcript_kind": src.get("transcript_kind"),
        "description": (src.get("description") or "")[:600] or None, "tags": tags, "chunks": len(chunks), "chars": total,
        "terms": _terms(texts), "authority_signals": authority_signals(src),
    }
    mat, ids = db.load_embedding_matrix([src["id"]])
    centroid = topic = None
    topic_ids: list[int] = []
    if len(ids):
        centroid = db._pack(mat.mean(axis=0))
        pick = _farthest_points(mat, TOPIC_VECTORS)
        topic = db._pack(mat[pick])
        topic_ids = [ids[i] for i in pick]
        by_id = {c["id"]: c for c in chunks}
        baseline["topic_chunks"] = [{"chunk_id": ids[i], "preview": " ".join((by_id.get(ids[i]) or {}).get("text", "").split()[:18])} for i in pick]
    return baseline, centroid, topic, topic_ids


def baseline(source_id: str, force: bool = False) -> dict[str, Any] | None:
    """The cached $0 profile, rebuilt when the source revision moved (staleness) or on demand."""
    src = db.get_source(source_id)
    if not src or src.get("status") != "ready":
        return None
    rev = src.get("revision") or db.source_revision(source_id)
    conn = db.connect()
    row = conn.execute("SELECT * FROM source_profiles WHERE source_id=?", (source_id,)).fetchone()
    if row and not force and row["baseline"] and row["source_revision"] == rev and row["baseline_version"] == BASELINE_VERSION:
        return json.loads(row["baseline"])
    b, centroid, topic, topic_ids = build_baseline(src)
    t = time.time()
    with db.tx() as tx:
        if row:
            stale_enriched = row["enriched_status"] == "current" and row["source_revision"] != rev
            tx.execute("UPDATE source_profiles SET source_revision=?, baseline=?, baseline_version=?, baseline_at=?, centroid=?, topic_vectors=?, topic_chunk_ids=?, "
                       "enriched_status=CASE WHEN ? THEN 'stale' ELSE enriched_status END, updated_at=? WHERE source_id=?",
                       (rev, json.dumps(b), BASELINE_VERSION, t, centroid, topic, json.dumps(topic_ids), 1 if stale_enriched else 0, t, source_id))
        else:
            tx.execute("INSERT INTO source_profiles (source_id, source_revision, baseline, baseline_version, baseline_at, centroid, topic_vectors, topic_chunk_ids, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (source_id, rev, json.dumps(b), BASELINE_VERSION, t, centroid, topic, json.dumps(topic_ids), t))
    return b


def profile(source_id: str) -> dict[str, Any] | None:
    """baseline + enriched (if current) + status, for display and ranking."""
    b = baseline(source_id)
    if b is None:
        return None
    row = db.connect().execute("SELECT * FROM source_profiles WHERE source_id=?", (source_id,)).fetchone()
    enriched = json.loads(row["enriched"]) if row and row["enriched"] and row["enriched_status"] == "current" else None
    return {"source_id": source_id, "baseline": b, "enriched": enriched, "enriched_status": row["enriched_status"] if row else "none",
            "enriched_provenance": {k: row[k] for k in ("enriched_model", "enriched_prompt_version", "enriched_schema_version", "enriched_input_hash", "enriched_at", "enriched_transport")} if row and enriched else None,
            "source_revision": row["source_revision"] if row else None}


# ------------------------------------------------------------------ recall (works with zero enriched profiles)

def _tokens(q: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9\-']{2,}", q.lower()) if w not in _STOP}


def library_scope(project_id: str | None) -> list[str]:
    """Library Candidates (Invariant D): ready sources NOT in the project. They can be suggested, never used, until attached."""
    conn = db.connect()
    ready = [r["id"] for r in conn.execute("SELECT id FROM sources WHERE status='ready'").fetchall()]
    if not project_id:
        return ready
    mine = set(db.project_source_ids(project_id, ready_only=False))
    return [s for s in ready if s not in mine]


def recall(project_id: str | None, query: str, limit: int = 8, *, want_enrichment: bool = True, reason: str | None = None) -> dict[str, Any]:
    """Which sources the user ALREADY OWNS could answer `query`? Chunk-level retrieval first (nothing averaged away),
    then baseline/enriched profile term hits as ranking signal + explanation. Returns suggestions with provenance;
    marks the top unenriched hits as `wanted` (lazy enrichment) without ever waiting for it."""
    from .search import search
    q = (query or "").strip()
    scope = library_scope(project_id)
    if not q or not scope:
        return {"query": q, "suggestions": [], "scope": len(scope), "enrichment": {"wanted": 0}}
    hits = search(q, limit=RECALL_CHUNKS, source_ids=scope, per_source_cap=PER_SOURCE_CHUNKS, reserve=0)
    qt = _tokens(q)
    by_src: dict[str, dict[str, Any]] = {}
    for h in hits:
        d = by_src.setdefault(h["source_id"], {"source_id": h["source_id"], "chunk_score": 0.0, "chunks": [], "title": h["title"], "channel": h.get("channel"),
                                                "platform": h.get("platform"), "url": h.get("url"), "published_at": h.get("published_at")})
        d["chunk_score"] += h["score"]
        d["chunks"].append({"chunk_id": h["chunk_id"], "timestamp": h["timestamp"], "link": h["link"], "text": h["text"][:280], "score": h["score"]})
    out = []
    for sid, d in by_src.items():
        if d["chunk_score"] < MIN_SCORE:
            continue
        p = profile(sid) or {}
        b = p.get("baseline") or {}
        e = p.get("enriched")
        term_hits = sorted(qt & set(b.get("terms") or []))
        title_hits = sorted(qt & _tokens(str(b.get("title") or "") + " " + str(b.get("creator") or "")))
        passage_terms = _tokens(" ".join(c["text"] for c in d["chunks"]))
        covered = sorted((qt & passage_terms) | set(title_hits))
        coverage = round(len(covered) / len(qt), 2) if qt else 0.0
        d["coverage"], d["covered_terms"], d["query_terms"] = coverage, covered, sorted(qt)
        if coverage < MIN_COVERAGE:
            continue                                                # the nearest thing we own is not the same as coverage
        why: list[str] = [f"{len(d['chunks'])} matching passage(s); best at {d['chunks'][0]['timestamp']}",
                          f"passages cover {len(covered)} of {len(qt)} query terms ({', '.join(covered[:6])})"]
        bonus = 0.0
        if title_hits:
            bonus += 0.004 * len(title_hits); why.append("title/creator mentions " + ", ".join(title_hits[:4]))
        if term_hits:
            bonus += 0.001 * min(len(term_hits), 5); why.append("frequent terms: " + ", ".join(term_hits[:5]))
        if e:
            ehits = sorted(qt & _tokens(" ".join((e.get("topics") or []) + (e.get("entities") or []) + (e.get("useful_for") or []) + (e.get("minority_topics") or []))))
            if ehits:
                bonus += 0.003 * min(len(ehits), 5); why.append("profile: " + ", ".join(ehits[:5]))
        out.append({**d, "score": round(d["chunk_score"] + bonus, 4), "why": why, "authority_signals": b.get("authority_signals") or [],
                    "evidence_class": (e or {}).get("evidence_class"), "temporal_character": (e or {}).get("temporal_character"),
                    "profile_summary": (e or {}).get("summary"), "enriched": bool(e), "enriched_status": p.get("enriched_status", "none"),
                    "source_revision": p.get("source_revision"), "in_library": True, "in_project": False, "attach": {"endpoint": f"/api/projects/{project_id}/members", "source_ids": [sid]} if project_id else None})
    out.sort(key=lambda x: -x["score"])
    out = out[:limit]
    wanted = 0
    if want_enrichment:
        wanted = want([s["source_id"] for s in out if not s["enriched"]], reason or f"library recall: {q[:120]}", project_id)
    try:
        db.kv_bump("library:recalls")
        if out:
            db.kv_bump("library:recall_hits", len(out))
    except Exception:  # noqa: BLE001
        pass
    return {"query": q, "suggestions": out, "scope": len(scope), "enrichment": {"wanted": wanted, "pending": pending_count()}}


# ------------------------------------------------------------------ enrichment (lazy · opportunistic batch · never required)

SYSTEM = """You are cataloguing a source for a research library. Describe the SOURCE itself — what it is, who speaks, what it
covers, what questions it can help answer — neutrally and independently of any particular research project.
Do not judge relevance to anything; do not rate quality; report who speaks and on what basis so a reader can judge
authority for their own question. Prefer the source's own words for topics and entities. Output only the JSON the
schema requires."""


def _sample(src: dict[str, Any], b: dict[str, Any]) -> str:
    chunks = db.get_chunks(src["id"])
    if not chunks:
        return ""
    picked: list[str] = []
    seen: set[int] = set()
    head = chunks[: max(1, min(4, len(chunks)))]
    for c in head:
        picked.append(c["text"]); seen.add(c["id"])
    for tc in b.get("topic_chunks") or []:                    # the representative (incl. minority) passages
        cid = tc.get("chunk_id")
        if cid in seen:
            continue
        c = next((x for x in chunks if x["id"] == cid), None)
        if c:
            picked.append(c["text"]); seen.add(cid)
    text = "\n---\n".join(picked)
    return text[:PROFILE_CHARS]


def input_hash(src: dict[str, Any], sample: str) -> str:
    from .contracts import contract
    c = contract("library.profile")
    return hashlib.sha256("\x1f".join([src.get("revision") or "", PROMPT_VERSION, c.schema or "", c.model, sample]).encode()).hexdigest()[:16]


def _user(src: dict[str, Any], b: dict[str, Any], sample: str) -> str:
    meta = {k: b.get(k) for k in ("title", "creator", "platform", "published_at", "duration", "transcript_kind", "description")}
    sig = "; ".join(f"{s['signal']}={s['value']} ({s['basis']})" for s in b.get("authority_signals") or [])
    return f"SOURCE METADATA: {json.dumps(meta)}\nDETERMINISTIC SIGNALS: {sig}\n\nTEXT SAMPLE (head, then representative passages):\n{sample}"


def want(source_ids: list[str], reason: str, project_id: str | None = None) -> int:
    """Mark sources as plausible candidates worth enriching. Idempotent; never blocks; provenance of the future spend."""
    n = 0
    t = time.time()
    with db.tx() as conn:
        for sid in source_ids:
            r = conn.execute("SELECT enriched_status FROM source_profiles WHERE source_id=?", (sid,)).fetchone()
            if not r:
                continue                                        # baseline() creates the row; recall() always built it first
            if r["enriched_status"] in ("none", "stale", "failed"):
                conn.execute("UPDATE source_profiles SET enriched_status='wanted', wanted_at=?, wanted_by=?, updated_at=? WHERE source_id=?",
                             (t, json.dumps({"reason": reason, "project_id": project_id}), t, sid))
                n += 1
    return n


def pending_count() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM source_profiles WHERE enriched_status IN ('wanted','queued')").fetchone()[0]


def wanted_ids(limit: int = 500) -> list[str]:
    return [r["source_id"] for r in db.connect().execute("SELECT source_id FROM source_profiles WHERE enriched_status='wanted' ORDER BY wanted_at LIMIT ?", (limit,)).fetchall()]


def _store_enriched(source_id: str, parsed: dict[str, Any], *, model: Any, ih: str, transport: str, rev: str | None) -> None:
    from . import providers
    from .contracts import contract
    c = contract("library.profile")
    t = time.time()
    with db.tx() as conn:
        conn.execute("UPDATE source_profiles SET enriched=?, enriched_status='current', enriched_at=?, enriched_model=?, enriched_prompt_version=?, enriched_schema_version=?, "
                     "enriched_input_hash=?, enriched_routing=?, enriched_transport=?, enriched_error=NULL, source_revision=COALESCE(?, source_revision), updated_at=? WHERE source_id=?",
                     (json.dumps(parsed), t, str(model or c.model), PROMPT_VERSION, c.schema, ih, providers.routing_json("library.profile", model), transport, rev, t, source_id))
    try:
        db.kv_bump("library:profiles_enriched")
    except Exception:  # noqa: BLE001
        pass


def enrich(source_id: str, transport: str = "interactive") -> dict[str, Any] | None:
    """One model call, project-neutral, cached. Returns the enriched profile or None when the source is not ready."""
    from . import providers
    src = db.get_source(source_id)
    b = baseline(source_id)
    if not src or b is None:
        return None
    sample = _sample(src, b)
    if not sample:
        with db.tx() as conn:
            conn.execute("UPDATE source_profiles SET enriched_status='failed', enriched_error='no text', updated_at=? WHERE source_id=?", (time.time(), source_id))
        return None
    ih = input_hash(src, sample)
    row = db.connect().execute("SELECT enriched, enriched_input_hash, enriched_status FROM source_profiles WHERE source_id=?", (source_id,)).fetchone()
    if row and row["enriched"] and row["enriched_input_hash"] == ih and row["enriched_status"] == "current":
        return json.loads(row["enriched"])                     # same inputs → same profile, no spend
    with db.tx() as conn:
        conn.execute("UPDATE source_profiles SET enriched_status='queued', updated_at=? WHERE source_id=?", (time.time(), source_id))
    try:
        parsed = providers.invoke_structured("library.profile", system=SYSTEM, messages=[{"role": "user", "content": _user(src, b, sample)}],
                                             usage_kind="profile", source_id=source_id)
    except Exception as e:  # noqa: BLE001
        with db.tx() as conn:
            conn.execute("UPDATE source_profiles SET enriched_status='failed', enriched_error=?, updated_at=? WHERE source_id=?", (str(e)[:300], time.time(), source_id))
        raise
    model = getattr(providers.last_response(), "model", None)
    _store_enriched(source_id, parsed, model=model, ih=ih, transport=transport, rev=src.get("revision"))
    return parsed


def enrich_wanted(limit: int = INTERACTIVE_MAX, source_ids: list[str] | None = None) -> dict[str, Any]:
    """Interactive enrichment for a handful of wanted profiles a query needs right now. Failures never propagate to recall."""
    ids = (source_ids or wanted_ids())[:limit]
    done, failed = 0, []
    for sid in ids:
        try:
            if enrich(sid) is not None:
                done += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"source_id": sid, "error": str(e)[:200]})
            from .breakers import ProviderUnavailable
            from .usage import BudgetPaused
            if isinstance(e, (BudgetPaused, ProviderUnavailable)):
                break
    return {"enriched": done, "failed": failed, "remaining": pending_count()}


# ---- opportunistic batch (reuses the Rung G batch machinery: batch_items + AnthropicBatch + jobs.submit_external)

def batch_requests(source_ids: list[str]) -> list[dict[str, Any]]:
    from . import providers
    out = []
    for sid in source_ids:
        src = db.get_source(sid)
        b = baseline(sid)
        if not src or b is None:
            continue
        sample = _sample(src, b)
        if not sample:
            continue
        ih = input_hash(src, sample)
        params = providers.batch_params("library.profile", system=SYSTEM, messages=[{"role": "user", "content": _user(src, b, sample)}])
        out.append({"custom_id": f"lp-{sid[:12]}-{ih[:12]}", "task": "library.profile", "project_id": None, "source_id": sid, "window_index": 0, "windows": 1, "params": params})
    return out


def maybe_queue_batch(min_items: int = BATCH_MIN, force: bool = False) -> dict[str, Any] | None:
    """When enough wanted profiles have accumulated, ONE durable `enrich_profiles_batch` job takes them (50% economics).
    Called opportunistically (after a recall, by Discover); never on a timer, never for sources nobody asked about."""
    active = [j for j in db.list_jobs(50) if j["kind"] == "enrich_profiles_batch" and j["status"] in ("queued", "running", "external_pending")]
    if active:
        return {"job_id": active[0]["id"], "already_running": True}
    ids = wanted_ids()
    if not ids or (len(ids) < min_items and not force):
        return None
    job = db.create_job("enrich_profiles_batch", {"source_ids": ids})
    with db.tx() as conn:
        conn.execute(f"UPDATE source_profiles SET enriched_status='queued', updated_at=? WHERE source_id IN ({','.join('?' for _ in ids)})", (time.time(), *ids))
    return {"job_id": job["id"], "items": len(ids)}


def run_batch_job(job_id: str, payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    """Job body for enrich_profiles_batch: plan + submit (parks as external_pending), then materialize when the batch ends.
    Mirrors batches.run for findings; failed items are retried once in a second cohort, then marked failed (visible)."""
    from . import batches, jobs, providers, usage
    result = payload.get("_external_result")
    cohort_no = int(payload.get("_cohort_no") or 1)
    if not result:
        if not db.batch_items(job_id, cohort_no):
            items = batch_requests(payload.get("source_ids") or [])
            if not items:
                return {"items": 0, "note": "nothing to profile"}
            db.batch_items_add(job_id, 1, items)
            db.job_event(job_id, "batch_planned", cohort_no=1, items=len(items))
        client_ref = f"{job_id}#{cohort_no}"
        if not db.kv_get(f"batch:intent:{client_ref}"):
            db.kv_set(f"batch:intent:{client_ref}", json.dumps({"job_id": job_id, "cohort_no": cohort_no, "n": len(db.batch_items(job_id, cohort_no)), "ts": time.time()}))
        usage.guard(0.05)
        jobs.submit_external(batches.PROVIDER, "profiles", {"job_id": job_id, "cohort_no": cohort_no}, deadline=time.time() + batches.DEADLINE_S, client_ref=client_ref)
    done, failed = 0, []
    for it in db.batch_items(job_id):
        if it["status"] == "succeeded":
            msg = batches._Msg(it["raw"])
            try:
                usage.record_anthropic(msg, "profile", source_id=it["source_id"], transport="batch")
                parsed = providers.structured("library.profile", msg)
                src = db.get_source(it["source_id"]) or {}
                _store_enriched(it["source_id"], parsed, model=getattr(msg, "model", None), ih=it["custom_id"].rsplit("-", 1)[-1], transport="batch", rev=src.get("revision"))
                db.batch_items_materialized(job_id, it["source_id"])
                done += 1
            except Exception as e:  # noqa: BLE001
                failed.append({"source_id": it["source_id"], "error": str(e)[:200]})
        elif it["status"] in ("errored", "expired", "canceled"):
            failed.append({"source_id": it["source_id"], "error": it.get("error") or it["status"]})
    if failed:
        with db.tx() as conn:
            for f in failed:
                conn.execute("UPDATE source_profiles SET enriched_status='failed', enriched_error=?, updated_at=? WHERE source_id=? AND enriched_status='queued'",
                             (f["error"], time.time(), f["source_id"]))
    db.job_event(job_id, "batch_ended", cohort_no=cohort_no, enriched=done, failed=len(failed))
    return {"enriched": done, "failed": failed, "items": len(db.batch_items(job_id))}


def stats() -> dict[str, Any]:
    conn = db.connect()
    by = {r["enriched_status"]: r["n"] for r in conn.execute("SELECT enriched_status, COUNT(*) n FROM source_profiles GROUP BY enriched_status").fetchall()}
    return {"baseline_profiles": conn.execute("SELECT COUNT(*) FROM source_profiles WHERE baseline IS NOT NULL").fetchone()[0],
            "enriched": by.get("current", 0), "wanted": by.get("wanted", 0), "queued": by.get("queued", 0), "stale": by.get("stale", 0), "failed": by.get("failed", 0),
            "recalls": int(db.kv_get("library:recalls") or 0), "recall_hits": int(db.kv_get("library:recall_hits") or 0),
            "profiles_enriched_total": int(db.kv_get("library:profiles_enriched") or 0)}
