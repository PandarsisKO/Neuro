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
import os
import time
from typing import Any

from . import db
from .config import int_env

# 2026-09-18 (Kyle): "if something ranks high 90+ and is members only, the app should remember it for the future.
# Maybe the user would want to become a member for that content. But we obviously cannot ingest it." A gated video
# is remembered as `needs_membership` with its relevance — never ingested, never resurfaced as available, never a
# preference signal (it says nothing about what the person WANTS, only what YouTube allows), shown in the pool
# with what it would take to get it. Any relevance is kept; the 90+ ones are the point.
STATES = ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost", "user_dismissed", "duplicate", "acquired", "needs_membership")
GATE_LABEL = {"members_only": "members-only — join the channel to make it ingestible", "premium": "YouTube Premium only",
              "needs_auth": "needs a signed-in account"}
LOW_RELEVANCE = 50            # a ranked score below this is a "skipped for low relevance", not a "skipped by the limit"
CONTENT_TYPE = {"youtube": "video", "instagram": "post", "podcast": "podcast", "web": "page", "media": "video", "document": "document", "book": "book"}


def _source_for_candidate_identity(platform: str, external_id: str) -> dict[str, Any] | None:
    """Find the Source identity that represents this candidate, if it already exists.

    Reddit listings were introduced before Community Sources and use the global candidate key
    ``reddit:<post-id>`` under platform ``reddit``. A captured Reddit thread is deliberately a
    ``community`` Source with the same external id. This is the one explicit bridge between
    those two canonical owners. Other platforms already use the same candidate and Source identity, and
    retain their existing explicit resolution behavior.
    """
    if platform == "reddit" and external_id.startswith("reddit:"):
        return db.find_source("community", external_id)
    return None


def _candidate_identity_for_source(platform: str, external_id: str) -> tuple[str, str]:
    """Map the Community Source representation back to the existing Reddit candidate key."""
    if platform == "community" and external_id.startswith("reddit:"):
        return "reddit", external_id
    return platform, external_id


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
            # Discovery can happen after an individual thread was captured through the browser or a direct URL.
            # Store that existing global Source now rather than forcing the next Capture click to rediscover it.
            source = _source_for_candidate_identity(platform, ext)
            source_id = e.get("source_id") or (source or {}).get("id")
            r = conn.execute("SELECT * FROM candidates WHERE platform=? AND external_id=?", (platform, ext)).fetchone()
            if r:
                cid = r["id"]
                patch: dict[str, Any] = {"last_seen_at": t}
                for k in ("title", "description", "creator", "published_at", "duration", "view_count", "canonical_url"):
                    if e.get(k) is not None and not r[k]:              # fill what is empty; never overwrite what we knew
                        patch[k] = e[k] if k != "description" else str(e[k])[:2000]
                if source_id and not r["source_id"]:
                    patch["source_id"] = source_id
                conn.execute("UPDATE candidates SET " + ", ".join(f"{k}=?" for k in patch) + " WHERE id=?", (*patch.values(), cid))
            else:
                cid = db.new_id()
                conn.execute("INSERT INTO candidates (id, platform, external_id, canonical_url, url, title, description, creator, published_at, duration, view_count, "
                             "content_type, language, first_seen_at, last_seen_at, source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, platform, ext, e.get("canonical_url"), e.get("url") or "", e.get("title"), (e.get("description") or "")[:2000] or None, e.get("creator"),
                              e.get("published_at"), e.get("duration"), e.get("view_count"), e.get("content_type") or CONTENT_TYPE.get(platform, "page"),
                              e.get("language"), t, t, source_id))
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
    candidate_platform, candidate_external_id = _candidate_identity_for_source(platform, external_id)
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=?, last_verified_at=? WHERE platform=? AND external_id=? AND source_id IS NULL", (source_id, time.time(), candidate_platform, candidate_external_id))
        conn.execute("UPDATE candidate_links SET state='satisfied', updated_at=? WHERE state='open' AND candidate_id IN (SELECT id FROM candidates WHERE platform=? AND external_id=?)",
                     (time.time(), candidate_platform, candidate_external_id))          # B3: the need this source served is met


def dismiss(project_id: str, candidate_id: str, reason: str | None) -> int:
    return mark(project_id, [candidate_id], "user_dismissed", reason or "dismissed by the user")


def restore(project_id: str, candidate_id: str) -> int:
    return mark(project_id, [candidate_id], "available", "restored by the user")


def capture(candidate_id: str, project_id: str, *, reason: str | None = None) -> dict[str, Any]:
    """AD1: the one CAPTURE path, through the NORMAL lifecycle (ingest_url -> G1 identity) -- never a parallel one.
    Attach-if-already-owned, else enqueue the real acquisition job; either way `mark(..., "acquired", ...)` records
    the durable disposition AD0 named as AD2's primary rerank signal. Extracted from `api.api_candidate_acquire`
    (0.63.9x had this same three-line sequence duplicated in `api_pool_capture_many`'s bulk path too -- both now
    call this one function). Raises `LookupError` for an unknown candidate; callers map that to their own "not
    found" (the API layer's 404)."""
    c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone())
    if not c:
        raise LookupError(candidate_id)
    source = db.get_source(c["source_id"]) if c.get("source_id") else _source_for_candidate_identity(c["platform"], c["external_id"])
    if source and source.get("status") == "ready":
        from . import identity
        if not c.get("source_id"):
            resolve_acquired(source["platform"], source["external_id"], source["id"])
        r = identity.attach_existing(project_id, source["id"])          # already owned: attach, no acquisition
        mark(project_id, [candidate_id], "acquired", "attached from the library")
        return {"ok": True, "job_id": None, "source_id": source["id"], "identity": r.state, "url": c["url"]}
    from . import jobs
    job = jobs.enqueue("ingest_url", {"url": c["url"], "tags": [], "project_id": project_id, "force": False, "review": False,
                                      "candidate_id": candidate_id, "reason": reason})
    mark(project_id, [candidate_id], "acquired", reason or "acquired from the Candidate Index")
    return {"ok": True, "job_id": job["id"], "url": c["url"]}


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


# ---------------------------------------------------------------- B3: durable links — why a known source matters (gap / claim / tension / mission)

LINK_KINDS = ("evidence_target", "claim", "tension", "mission", "discovery")


def link(candidate_id: str, project_id: str, kind: str, ref_id: str, *, relevance: int | None = None, why: str | None = None) -> None:
    """Record that this known-but-not-captured source may serve a research need. Idempotent; relevance/why refresh; a
    dismissed link stays dismissed (the user's word outranks a re-ranking); a link on an already-acquired candidate is born satisfied."""
    if kind not in LINK_KINDS:
        raise ValueError(f"unknown link kind {kind}")
    t = time.time()
    with db.tx() as conn:
        acquired = conn.execute("SELECT source_id FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        state = "satisfied" if acquired and acquired["source_id"] else "open"
        conn.execute("INSERT INTO candidate_links (candidate_id, project_id, kind, ref_id, relevance, why, state, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                     "ON CONFLICT(candidate_id, project_id, kind, ref_id) DO UPDATE SET relevance=excluded.relevance, why=COALESCE(excluded.why, candidate_links.why), "
                     "state=CASE WHEN candidate_links.state='dismissed' THEN 'dismissed' ELSE excluded.state END, updated_at=excluded.updated_at",
                     (candidate_id, project_id, kind, ref_id, relevance, why, state, t, t))


def links_for(project_id: str, kind: str, ref_id: str, *, state: str = "open", limit: int = 10) -> list[dict[str, Any]]:
    """The known sources linked to one research need, best first, with the candidate's metadata and an acquisition hint."""
    rows = db.connect().execute(
        "SELECT l.relevance, l.why, l.state, l.updated_at, c.* FROM candidate_links l JOIN candidates c ON c.id=l.candidate_id "
        "WHERE l.project_id=? AND l.kind=? AND l.ref_id=? AND l.state=? ORDER BY l.relevance DESC, l.updated_at DESC LIMIT ?", (project_id, kind, ref_id, state, limit)).fetchall()
    out = []
    for r in rows:
        d = db.row_to_dict(r)
        d["candidate_id"] = d["id"]
        d["acquisition_hint"] = "browser_likely" if d.get("platform") in ("reddit", "community") or "reddit.com" in (d.get("url") or "") else "server"
        out.append(d)
    return out


def link_counts(project_id: str, kind: str) -> dict[str, int]:
    """ref_id → number of open links (one query for a whole page of targets/claims)."""
    return {r["ref_id"]: r["n"] for r in db.connect().execute(
        "SELECT ref_id, COUNT(*) AS n FROM candidate_links WHERE project_id=? AND kind=? AND state='open' GROUP BY ref_id", (project_id, kind)).fetchall()}


def dismiss_link(project_id: str, candidate_id: str, kind: str, ref_id: str) -> int:
    with db.tx() as conn:
        return conn.execute("UPDATE candidate_links SET state='dismissed', updated_at=? WHERE project_id=? AND candidate_id=? AND kind=? AND ref_id=?",
                            (time.time(), project_id, candidate_id, kind, ref_id)).rowcount


def satisfy_links(candidate_id: str) -> int:
    """The candidate was acquired (any path, any project): every open link to it is satisfied."""
    with db.tx() as conn:
        return conn.execute("UPDATE candidate_links SET state='satisfied', updated_at=? WHERE candidate_id=? AND state='open'", (time.time(), candidate_id)).rowcount


# ---------------------------------------------------------------- S5: the known-but-uncaptured pool + the pre-cutoff quick scan ($0)

EVERGREEN = {"how", "framework", "principle", "principles", "checklist", "playbook", "guide", "mistakes", "lessons", "rules", "process", "steps", "strategy",
             "structure", "negotiat", "diligence", "valuation", "financing", "story", "case", "study", "explained", "beginner", "basics", "fundamentals"}
_EVERGREEN_T = tuple(sorted(EVERGREEN))        # for str.startswith, which accepts a tuple and tests it in C
DATED = {"news", "update", "breaking", "rates", "rate", "today", "week", "month", "2019", "2020", "2021", "2022", "2023", "2024", "election", "market", "stocks", "crypto", "price", "prices"}


def _toks(s: str) -> set[str]:
    import re
    return {w for w in re.findall(r"[a-z0-9][a-z0-9'-]+", (s or "").lower()) if len(w) > 2}


def _gap_terms(project_id: str) -> tuple[list[tuple[str, str, set[str]]], set[str]]:
    """(open questions as (id, label, tokens), the project's own vocabulary) — what an uncaptured item can FIT."""
    from . import research_view
    qs: list[tuple[str, str, set[str]]] = []
    try:
        for q in research_view.questions(project_id):
            if q["status"] == "open":
                qs.append((q["id"], q["label"], _toks(q["question"] + " " + (q.get("label") or ""))))
        for a in research_view.areas(project_id)["areas"]:
            if a["state"] in ("weak", "missing") and a["name"] != "Everything else":
                qs.append(("area:" + a["name"], a["name"], _toks(a["name"])))
    except Exception:  # noqa: BLE001
        pass
    p = db.get_project(project_id) or {}
    vocab = _toks(" ".join(str(p.get(k) or "") for k in ("brief", "goal", "context")))
    return qs, vocab


# ------------------------------------------------------------------ C1: what a master source has actually given us

# 0.58.2. `_potential` scored a known-but-uncaptured source out of 100 from the words in its own title and 600
# characters of description — and nothing else. So a video from a channel whose sixty siblings already produced
# hundreds of findings, closed evidence targets and supplied this project's only experiential evidence scored
# exactly the same as a video from a channel that has never yielded anything. The measurement existed in the
# database and nothing consulted it. With Kyle's partial-ingest pattern (60 of 598, plus 107, 93 and 398 unstarted)
# those remainders are reservoirs of KNOWN character being treated as a flat list of strangers.
#
# Scope, per SOURCE-CAPABILITY-RUNG.md and the G4 rule it has to respect: this is **project-scoped yield**, not a
# global source profile. G4 forbids building a global profile from project findings, and a yield profile is by
# construction built from project findings — so it stays inside the project that produced it, exactly as
# `project_reuse` does for Bootstrap. Nothing here is written anywhere; it is derived on read.
#
# Absence is never evidence: a creator with no yield gets NO penalty, because a channel that has never supplied
# authoritative evidence may simply never have been asked for any. Only positive, measured yield adds.

CREATOR_MAX_BONUS = 25
# CALIBRATED 2026-09-10 against Kyle's live corpus. The first version used an absolute bar (8.0 findings per
# ingested source) and it does not survive contact with real projects, because findings-per-source is a property of
# the DOMAIN and of source length, not of a creator's merit:
#
#   "buying businesses"  112 creators, per-source median 12.0, p75 19.0, max 48.2  → 8.0 marks nearly everyone
#   "web app design"      17 creators, per-source median  6.1, p75  9.8, max 13.7  → 8.0 marks only a handful
#   "real estate"          9 creators, per-source median  9.4, p75 11.0, max 11.4
#
# So "proven" is now relative to the PROJECT'S OWN distribution: the top quartile of its creators' per-source rates.
# That is self-calibrating, always identifies someone (a bar nobody clears is not a useful bar), and says something
# true in one sentence — "this source gives you more per video than three quarters of your sources do".
CREATOR_PROVEN_QUANTILE = 0.75       # top quartile of this project's own per-source rates
CREATOR_MIN_SOURCES = 3              # ...over at least this many read sources, so one lucky video proves nothing
CREATOR_MIN_FINDINGS = 10


def creator_yield(project_id: str) -> dict[str, dict[str, Any]]:
    """channel → what it has given THIS project: ingested sources, findings, findings that became Claims, evidence
    rows, and the evidence classes it has actually supplied. $0, derived on read, no model, no schema change.

    SC0b additions (read-only, project-scoped, never collapsed into a single score): claim_types/topics actually
    yielded (what KIND of claim this creator tends to produce for this project, not just how many), targets this
    creator has previously helped close (`candidate_links` rows this project marked `satisfied`, joined through
    `candidates.creator` — the same field a source's own `channel` is set from on acquisition), and cadence as the
    plain spread of this creator's own `published_at` dates for sources already in this project (min/max/count of
    dated sources) — a fact, not a schedule prediction."""
    conn = db.connect()
    ids = set(db.project_source_ids(project_id, ready_only=False))
    if not ids:
        return {}
    chan: dict[str, str] = {}
    published: dict[str, str] = {}
    for sid in ids:
        s = db.get_source(sid)
        if s and (s.get("channel") or "").strip():
            chan[sid] = s["channel"].strip()
            if s.get("published_at"):
                published[sid] = s["published_at"]
    if not chan:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for c in set(chan.values()):
        out[c] = {"sources": 0, "findings": 0, "claims": 0, "evidence": 0, "classes": {}, "claim_types": {}, "topics": {}, "targets_helped": 0, "cadence": None}
    for sid, c in chan.items():
        out[c]["sources"] += 1
    ph = ",".join("?" * len(chan))
    args = list(chan)
    for r in conn.execute(f"SELECT source_id, COUNT(*) n FROM project_notes WHERE project_id=? AND source_id IN ({ph}) GROUP BY source_id",
                          (project_id, *args)).fetchall():
        out[chan[r["source_id"]]]["findings"] += r["n"]
    for r in conn.execute(f"""SELECT n.source_id sid, c.claim_type ct, c.topic tp, COUNT(*) n FROM project_claims c JOIN project_notes n ON n.id=c.origin_note_id
                              WHERE c.project_id=? AND n.source_id IN ({ph}) GROUP BY n.source_id, c.claim_type, c.topic""",
                          (project_id, *args)).fetchall():
        row = out[chan[r["sid"]]]
        row["claims"] += r["n"]
        if r["ct"]:
            row["claim_types"][r["ct"]] = row["claim_types"].get(r["ct"], 0) + r["n"]
        if r["tp"]:
            row["topics"][r["tp"]] = row["topics"].get(r["tp"], 0) + r["n"]
    for r in conn.execute(f"""SELECT e.source_id sid, e.evidence_class cls, COUNT(*) n FROM claim_evidence e
                              JOIN project_claims c ON c.id=e.claim_id
                              WHERE c.project_id=? AND e.source_id IN ({ph}) GROUP BY e.source_id, e.evidence_class""",
                          (project_id, *args)).fetchall():
        row = out[chan[r["sid"]]]
        row["evidence"] += r["n"]
        if r["cls"]:
            row["classes"][r["cls"]] = row["classes"].get(r["cls"], 0) + r["n"]
    for r in conn.execute("""SELECT ca.creator cr, COUNT(DISTINCT cl.ref_id) n FROM candidate_links cl
                             JOIN candidates ca ON ca.id=cl.candidate_id
                             WHERE cl.project_id=? AND cl.kind='evidence_target' AND cl.state='satisfied' AND ca.creator IS NOT NULL
                             GROUP BY ca.creator""",
                          (project_id,)).fetchall():
        c = (r["cr"] or "").strip()
        if c in out:
            out[c]["targets_helped"] = r["n"]
    by_creator_dates: dict[str, list[str]] = {}
    for sid, c in chan.items():
        d = published.get(sid)
        if d:
            by_creator_dates.setdefault(c, []).append(d)
    for c, dates in by_creator_dates.items():
        dates.sort()
        out[c]["cadence"] = {"count": len(dates), "earliest": dates[0], "latest": dates[-1]}
    for c, row in out.items():
        row["per_source"] = round(row["findings"] / row["sources"], 1) if row["sources"] else 0.0
    # the bar is this project's own top quartile, computed over creators with enough read sources to mean anything
    rates = sorted(r["per_source"] for r in out.values()
                   if r["sources"] >= CREATOR_MIN_SOURCES and r["findings"] >= CREATOR_MIN_FINDINGS)
    bar = rates[min(len(rates) - 1, int(CREATOR_PROVEN_QUANTILE * len(rates)))] if rates else None
    for row in out.values():
        row["proven"] = bool(bar is not None and row["sources"] >= CREATOR_MIN_SOURCES
                             and row["findings"] >= CREATOR_MIN_FINDINGS and row["per_source"] >= bar)
        row["project_bar"] = bar
    return out


def _creator_term(creator: str | None, stats: dict[str, dict[str, Any]] | None,
                  want_classes: set[str] | None = None) -> tuple[int, list[str]]:
    """The bonus this item earns from what its master source has already given the project, and the measured reason.
    Never negative — see the note above on absence."""
    if not creator or not stats:
        return 0, []
    y = stats.get(creator.strip())
    if not y or not y.get("findings"):
        return 0, []
    score, why = 0, []
    if y["proven"]:
        score += 15
        why.append(f"{creator} has given this project {y['findings']} findings from {y['sources']} source(s) "
                   f"({y['per_source']} each) — top quartile for this project"
                   + (f", where the bar is {y['project_bar']}" if y.get("project_bar") else ""))
    elif y["findings"] >= 3:
        score += 6
        why.append(f"{creator} has given this project {y['findings']} findings so far")
    if y.get("claims"):
        score += 5
        why.append(f"{y['claims']} of them became tracked Claims")
    if want_classes and y.get("classes"):
        hit = sorted(set(want_classes) & set(y["classes"]))
        if hit:
            score += 8
            why.append(f"it has supplied {', '.join(hit)} evidence before, which is what this question needs")
    return min(CREATOR_MAX_BONUS, score), why


def gap_terms_cached(project_id: str) -> tuple[list[tuple[str, str, set[str]]], set[str], dict[str, Any]]:
    """`(questions, vocabulary, question index)` for this project, computed once per research revision.

    `_gap_terms` walks every open question and builds a token set for each — 2,689 of them on Kyle's project — and
    `pool` and `seen_for_query` were both calling it fresh on every request. `api_sources` had already cached it
    since 0.46.1; caching it HERE means one place serves every caller, and the index (0.63.19) is cached with the
    terms it belongs to rather than rebuilt beside them."""
    from . import cache
    return cache.get_or_compute(
        f"gap_terms_core:{project_id}", db.project_research_revision(project_id),
        lambda: (lambda qv: (qv[0], qv[1], question_index(qv[0])))(_gap_terms(project_id)),
        label="gap_terms_core")


# A "fit" is a claim on screen, so it needs the same bar the SCORE uses (0.63.20). `_potential` has awarded points
# only at or above 0.34 since S5, but `_best_fit` returned the argmax whatever it was, and `fits` is rendered
# unconditionally on every pool row and counted in the header chip. Measured on Kyle's project: 8,917 of 8,970
# items carried a `fits:` label and the chip read "8,917 fit an open question" — while **196** cleared 0.34, and
# 49.6% of items scored under 0.10, which is one function word in common. Revert with NEUROSEARCH_FIT_MIN_SHARE.
FIT_MIN_SHARE = max(0.0, min(1.0, float(os.environ.get("NEUROSEARCH_FIT_MIN_SHARE") or 0.34)))


def _need_for(den: int) -> int:
    """The fewest shared tokens that clear `FIT_MIN_SHARE` for a question of this denominator.

    Derived with the SAME comparison the verification uses rather than by `ceil(share * den)`: 0.34 is not
    representable in binary, so `0.34 * 50` is 17.000000000000004 and a ceiling would demand 18 shared tokens for a
    question that 17 genuinely clear. A wrong `need` here would prune a reachable question, which is a silent
    wrong answer rather than a slow one. `den` is at most a few dozen, so the loop costs nothing."""
    n = 1
    while n <= den and n / den < FIT_MIN_SHARE:
        n += 1
    return n


def question_index(qs: list[tuple[str, str, set[str]]]) -> dict[str, Any]:
    """A token → questions index, so scoring an item touches only the questions that could possibly fit it.

    **Exact, not an approximation**, in two steps. A question of `den` tokens needs `_need_for(den)` of them in
    common to clear `FIT_MIN_SHARE`, so each question's `need - 1` MOST COMMON tokens are left out of the postings:
    if an item shares `need` or more tokens, at most `need - 1` of them can be among the ones left out, so at least
    one remains and the question is still reached. Everything the reduced postings reach is then verified with the
    full token set, so the answer is the plain scan's answer and the postings only decide who is asked.

    That is where the time goes. Kyle's 2,726 open questions carry 7,513 distinct tokens and 83,380 postings, and
    the top ten tokens — `and`, `what`, `the`, `for`, `are`, `business`, `acquisition`, `sba`, `does`, `current` —
    hold 16% of them on their own, each sitting in 800–2,300 questions. They can never *decide* a fit (a question
    needs ~11 of its ~31 tokens matched), and walking them was most of the bill.

    Measured because the first benchmark lied. A synthetic corpus at his scale (10,319 candidates, 2,689 questions)
    said an index was barely worth having — because the synthetic questions shared only **67** distinct tokens, so
    every item overlapped nearly every question. His real questions carry **7,513**. The shape of the data was the
    whole variable, and inventing it produced the wrong answer; his own rows produced the right one (0.63.19)."""
    df: dict[str, int] = {}
    for _qid, _label, qt in qs:
        for w in qt:
            df[w] = df.get(w, 0) + 1
    post: dict[str, list[int]] = {}
    qlen: list[int] = []
    labels: list[str] = []
    toks: list[frozenset[str]] = []
    for i, (_qid, label, qt) in enumerate(qs):
        den = max(3, len(qt))
        qlen.append(den)
        labels.append(label)
        toks.append(frozenset(qt))
        drop = _need_for(den) - 1
        # Highest df first, ties by the word itself so the index is deterministic across runs.
        for w in sorted(qt, key=lambda x: (-df[x], x))[drop:]:
            post.setdefault(w, []).append(i)
    return {"post": {w: tuple(v) for w, v in post.items()}, "qlen": qlen, "labels": labels, "toks": toks,
            "postings": sum(len(v) for v in post.values())}


def _best_fit(t: set[str], qs: list[tuple[str, str, set[str]]], qindex: dict[str, Any] | None) -> tuple[str | None, float]:
    """(the open question this item fits, its share) — or `(None, 0.0)` when nothing clears `FIT_MIN_SHARE`.

    Below the bar there is no fit to report: `_potential` awards no points for one and the row has nothing true to
    say, so naming the argmax anyway was how 99.3% of the pool came to claim a question (0.63.20)."""
    if qindex:
        post, qlen, labels, toks = qindex["post"], qindex["qlen"], qindex["labels"], qindex["toks"]
        reached: set[int] = set()
        for w in t:
            reached.update(post.get(w, ()))
        best_i, best_s = -1, 0.0
        for i in reached:
            den = qlen[i]
            s = len(t & toks[i]) / den
            # `>` alone is not enough: the plain scan keeps the FIRST question at a tied score, and `reached` has no
            # order. Equal scores must resolve to the same question either way, or the same item would name a
            # different open question depending on the path (caught by S34's equivalence test, not by a screen).
            if s > best_s or (s == best_s and best_i >= 0 and i < best_i):
                best_i, best_s = i, s
        if best_s < FIT_MIN_SHARE:
            return None, 0.0
        return labels[best_i], best_s
    best, best_s = None, 0.0
    for _qid, label, qt in qs:
        if not qt:
            continue
        s = len(t & qt) / max(3, len(qt))
        if s > best_s:
            best, best_s = label, s
    if best_s < FIT_MIN_SHARE:
        return None, 0.0
    return best, best_s


LINKED_BOOST = 45            # AD2 reuses this exact figure to undo the boost when the link it rewarded has since closed
WORTH_A_LOOK = 40            # the pool's own "worth a look" boundary -- AD3 reuses it as its exploration floor


def _potential(title: str, desc: str, qs: list[tuple[str, str, set[str]]], vocab: set[str], relevance: int | None, linked: list[str],
               creator: str | None = None, creator_stats: dict[str, dict[str, Any]] | None = None,
               want_classes: set[str] | None = None, qindex: dict[str, Any] | None = None) -> tuple[int, str | None, list[str]]:
    """A quick $0 scan: 0–100 potential, the best fit (an open question / weak area), and the reasons. Words, plus
    (0.58.2) what this item's MASTER SOURCE has already given the project — see `creator_yield`.

    `qindex` is `question_index(qs)`, built once by a caller that scores many items: the pool scores 8,499 of them
    against 2,689 open questions, which is 23 million set intersections done one item at a time (0.63.19)."""
    t = _toks(title + " " + (desc or "")[:600])
    best, best_s = _best_fit(t, qs, qindex)
    why = []
    score = 0
    if linked:
        score += LINKED_BOOST; why.append(f"already found for: {linked[0][:60]}")
    if best_s >= FIT_MIN_SHARE:
        score += int(35 * min(1.0, best_s)); why.append(f"fits an open question: {best}")
    cov = len(t & vocab) / max(4, len(vocab)) if vocab else 0
    if cov > 0:
        score += int(20 * min(1.0, cov * 4)); why.append("uses the project's own vocabulary")
    if relevance is not None:
        score += int(relevance * 0.25); why.append(f"ranked {relevance}/100 at review")
    # `str.startswith` takes a tuple and does the whole test in C. The generator-per-word form cost 2.19M
    # Python-level calls and 29% of the pool pass once _best_fit stopped dominating it (0.63.20) —
    # identical answer, since a tuple of prefixes is exactly what the `any(...)` was spelling out.
    ever = sum(1 for w in t if w.startswith(_EVERGREEN_T))
    dated = len(t & DATED)
    if ever and not dated:
        score += 10; why.append("reads as timeless (how-to / principles)")
    elif dated and not ever:
        score -= 10; why.append("reads as dated (news / rates / a year)")
    cscore, cwhy = _creator_term(creator, creator_stats, want_classes)
    score += cscore
    why += cwhy
    return max(0, min(100, score)), best, why


def untapped_by_creator(project_id: str) -> dict[str, dict[str, Any]]:
    """channel → how much of that master source this project knows about but has NOT read: sources skipped at the
    ingest cutoff, plus Candidate Index rows. $0, counts only."""
    conn = db.connect()
    out: dict[str, dict[str, Any]] = {}

    def bump(name: str | None, key: str) -> None:
        n = (name or "").strip()
        if not n:
            return
        row = out.setdefault(n, {"skipped": 0, "candidates": 0})
        row[key] += 1

    ids = set(db.project_source_ids(project_id, ready_only=False))
    for srow in db.list_sources(status="skipped", limit=100000):
        if srow["id"] in ids:
            bump(srow.get("channel"), "skipped")
    for c in list_for_project(project_id, limit=100000):
        if c.get("state") in ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost", "needs_membership"):
            bump(c.get("creator"), "candidates")
    for row in out.values():
        row["untapped"] = row["skipped"] + row["candidates"]
    return out


def where_to_look(project_id: str, target: dict[str, Any] | None = None, limit: int = 5) -> dict[str, Any]:
    """C2 (0.58.3). Gap analysis used to start every search from nothing. This answers the question Kyle actually
    asked for — *where* should I look to close this gap — from what the project has already measured about each
    master source, and it is $0 with no model call and no network.

    A row is only offered when the creator has BOTH a yield history in this project and something left unread: a
    proven channel with nothing untapped is not a place to look, and an untapped channel with no history is just a
    list. Every reason cites a number. Absence stays not-evidence: nothing is ranked DOWN for having no history, it
    simply is not offered as a recommendation."""
    y = creator_yield(project_id)
    un = untapped_by_creator(project_id)
    want: set[str] = set()
    if target:
        pc = target.get("preferred_classes")
        if isinstance(pc, str):
            try:
                pc = json.loads(pc)
            except ValueError:
                pc = [pc]
        want = {c for c in (pc or []) if isinstance(c, str)}
    rows: list[dict[str, Any]] = []
    for creator, stats in y.items():
        left = (un.get(creator) or {}).get("untapped", 0)
        if not stats.get("findings") or not left:
            continue
        score, why = _creator_term(creator, y, want)
        if not score:
            continue
        why = list(why) + [f"{left} known but unread ({(un[creator]['skipped'])} skipped at review, "
                           f"{(un[creator]['candidates'])} seen but never captured)"]
        # Extrapolating from one or two read sources is how "Acquiring Minds: 1 video read, 24 findings" became a
        # promise of ~240 findings from the next ten. Below CREATOR_MIN_SOURCES there is no rate to extrapolate
        # from, so none is offered and the row says why instead.
        enough = stats["sources"] >= CREATOR_MIN_SOURCES
        expected = int(round(stats["per_source"] * min(left, 10))) if enough else None
        if not enough:
            why.append(f"only {stats['sources']} source(s) of theirs have been read, so there is no reliable rate "
                       f"to project from yet")
        # The untapped count is a tie-break, not a reason: a large remainder is not evidence that it is worth
        # reading, and capping it at +8 keeps measured yield in charge of the order.
        rows.append({"creator": creator, "score": score + min(8, left // 25), "untapped": left,
                     "read": stats["sources"], "findings": stats["findings"], "claims": stats["claims"],
                     "per_source": stats["per_source"], "proven": stats["proven"],
                     "classes": stats["classes"], "why": why,
                     "expected_findings": expected, "rate_is_reliable": enough,
                     "action": {"label": f"See what is left from {creator}", "method": "GET",
                                "endpoint": f"/api/projects/{project_id}/pool", "query": {"q": creator, "rank_by": "fit"}}})
    rows.sort(key=lambda r: (-r["score"], -r["untapped"], r["creator"]))
    return {"rows": rows[:max(1, limit)], "considered": len(y), "with_untapped": len(rows),
            "question": (target or {}).get("question"),
            "wanted_classes": sorted(want),
            "note": ("Ranked by what each master source has already given THIS project and how much of it is still "
                     "unread. A creator with no history is not ranked down — it is simply not recommended, because "
                     "never having supplied something is not evidence that it cannot."),
            "expected_findings_note": ("per_source × the next 10 unread — an extrapolation from this project's own "
                                       f"history with that source, not a promise. Null when fewer than "
                                       f"{CREATOR_MIN_SOURCES} of that source's items have been read, because there "
                                       f"is no rate to project from.")}


# 0.63.14: 24, was 12. $0 and no network — this rung is a DB search over 10,319 candidates plus 574 skipped
# sources, and twelve rows of a pool that size is a keyhole. Revert with NEUROSEARCH_SEEN_LIMIT=12.
SEEN_LIMIT = int_env("NEUROSEARCH_SEEN_LIMIT", 24)      # what a Discover rung shows before the web is worth trying (0.62.5)


def seen_for_query(project_id: str, query: str, limit: int = SEEN_LIMIT) -> dict[str, Any]:
    """The rung Discover never had: sources this app has ALREADY SEEN and chose not to read.

    Kyle: *"what I wanted was to search for content we chose not to ingest but that the app has seen at some point,
    like videos that were ranked but not chosen for transcription. if we do not find things there, then web,
    youtube, social media, academic papers etc."* `knowledge.pursue` has climbed exactly that ladder since G5
    (project → library → candidates → external); **Discover went library → catalogues → web and skipped the
    candidates rung entirely.**

    Measured on his live database, 2026-09-10 — the reservoir is an order of magnitude larger than the library
    scope it was searching instead (10,319 seen-and-never-ingested candidates plus 558 sources skipped at the
    cutoff, against 387 library sources outside the project):

        query                  seen, never ingested   what is in there
        quality of earnings     1                     an Acquisition Lab Quality-of-Earnings advisor
        due diligence          19                     all business-acquisition interviews
        sba                    43                     Ben Kelly, Acquiring Minds
        cpa                    13 + 8 skipped         Hector Garcia CPA, LYFE Accounting, Matt Bontrager

    Against which the library pass offered six short-term-rental tax videos. The material he wanted was in the
    database the whole time, one table away from the one being searched.

    Two existing mechanisms, no new data model (G3's rule: extend, never duplicate). `search` is the metadata FTS
    over candidates; `_potential` is the $0 scan that ranks an uncaptured item against THIS project's open
    questions, vocabulary and creator yield — which is also where project grounding legitimately enters, since it
    ranks rather than filters. Skipped sources are searched in the same pass because to a user they are the same
    thing: something the app saw and did not read."""
    from . import library
    q = (query or "").strip()
    if not q:
        return {"query": q, "items": [], "counts": {"candidates": 0, "skipped": 0}, "searched": None}
    # The anchor is the word that names the subject (0.62.0). A two-word search whose terms are ANDed finds almost
    # nothing in metadata as short as a title, so the subject word is what is searched, and the rest ranks.
    terms = library._tokens(q)
    anchor = library.query_anchor(terms)
    searched = anchor.get("term") or (sorted(terms)[0] if terms else q)
    qs, vocab, qidx = gap_terms_cached(project_id)       # the Discover rung scores up to 10x limit items (0.63.19)
    cy = creator_yield(project_id)
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for c in search(project_id, searched, limit=limit * 6):
        if c.get("source_id") or c.get("state") in ("dismissed", "acquired"):
            continue
        if c["id"] in seen_ids:
            continue
        seen_ids.add(c["id"])
        score, fit, why = _potential(c.get("title") or "", c.get("description") or "", qs, vocab, c.get("relevance"),
                                     [], creator=c.get("creator"), creator_stats=cy, qindex=qidx)
        items.append({"kind": "candidate", "id": c["id"], "title": c.get("title") or c["url"], "url": c["url"],
                      "creator": c.get("creator"), "published_at": c.get("published_at"), "platform": c["platform"],
                      "duration": c.get("duration"), "potential": score, "fits": fit, "why": why,
                      "why_known": "seen but never read",
                      "actions": {"capture": {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/acquire",
                                              "body": {"project_id": project_id}, "label": "Read this"},
                                  "dismiss": {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/dismiss",
                                              "body": {"project_id": project_id}, "label": "Not for this project"}}})
    like = f"%{searched.lower()}%"
    for s_ in db.connect().execute(
            "SELECT id, url, title, description, channel, platform, published_at, duration FROM sources "
            "WHERE status='skipped' AND (lower(title) LIKE ? OR lower(COALESCE(description,'')) LIKE ?) LIMIT ?",
            (like, like, limit * 4)):
        score, fit, why = _potential(s_["title"] or "", s_["description"] or "", qs, vocab, None, [],
                                     creator=s_["channel"], creator_stats=cy, qindex=qidx)
        items.append({"kind": "skipped", "id": s_["id"], "title": s_["title"] or s_["url"], "url": s_["url"],
                      "creator": s_["channel"], "published_at": s_["published_at"], "platform": s_["platform"],
                      "duration": s_["duration"], "potential": score, "fits": fit, "why": why,
                      "why_known": "skipped at the ingest cutoff",
                      "actions": {"capture": {"method": "POST", "endpoint": f"/api/sources/{s_['id']}/retry",
                                              "label": "Read it anyway"}}})
    items.sort(key=lambda i: (-i["potential"], i["title"]))
    counts = {"candidates": sum(1 for i in items if i["kind"] == "candidate"),
              "skipped": sum(1 for i in items if i["kind"] == "skipped")}
    return {"query": q, "searched": searched, "items": items[:limit], "total": len(items), "counts": counts,
            "note": (f"{len(items)} sources this app has already seen and never read mention \"{searched}\" "
                     f"({counts['candidates']} from exploration, {counts['skipped']} skipped at the cutoff)")
                    if items else f"nothing the app has seen but not read mentions \"{searched}\""}


def _pool_items(project_id: str) -> list[dict[str, Any]]:
    """Every known-but-uncaptured item scored, unfiltered and unsorted — the part of the pool that costs anything.

    Cached on `db.project_pool_revision` because it is a pass, not a lookup: 8,970 items on Kyle's project, each
    scored against his open questions, his vocabulary and what its creator has already given him. Filtering,
    sorting and paging that list costs milliseconds; assembling it was the whole bill — the same split
    `findings_view` needed at 17,000 findings (0.61.4), and the fifth time the answer has been that **a pass worth
    having is not worth having in a request**.

    Both kinds are always assembled, so one cached list serves `kind=all`, `kind=skipped` and `kind=candidates`
    rather than three. The returned dicts are SHARED with every later caller and must never be mutated — `pool`
    only filters, sorts and slices, all of which copy."""
    from . import perf
    conn = db.connect()
    with perf.timed("pool.gap_terms"):
        qs, vocab, qidx = gap_terms_cached(project_id)
    with perf.timed("pool.priority"):
        prio_creators = {(db.get_source(sid) or {}).get("channel") for sid in db.priority_source_ids(project_id)} - {None, ""}
    with perf.timed("pool.creator_yield"):
        cy = creator_yield(project_id)                   # 0.58.2: what each master source has already given us
    want_classes: set[str] = set()                       # the evidence classes this project's open questions ask for
    try:
        from . import knowledge
        for t in knowledge.list_targets(project_id, status="open"):
            pc = t.get("preferred_classes")
            if isinstance(pc, str):
                try:
                    pc = json.loads(pc)
                except ValueError:
                    pc = [pc]
            want_classes |= {c for c in (pc or []) if isinstance(c, str)}
    except Exception:  # noqa: BLE001 — the creator term is a bonus, never a prerequisite
        pass
    items: list[dict[str, Any]] = []
    with perf.timed("pool.score_skipped"):               # both kinds, always: one cached list serves every `kind`
        rel = db.project_analysis(project_id, "relevance")
        ids = set(db.project_source_ids(project_id, ready_only=False))
        for s in db.list_sources(status="skipped", limit=100000):
            if s["id"] not in ids:
                continue
            r = rel.get(s["id"]) or {}
            score, fit, why = _potential(s.get("title") or "", s.get("description") or "", qs, vocab, r.get("relevance"), [],
                                         creator=s.get("channel"), creator_stats=cy, want_classes=want_classes, qindex=qidx)
            items.append({"kind": "skipped", "id": s["id"], "title": s.get("title") or s["url"], "url": s["url"], "creator": s.get("channel"), "published_at": s.get("published_at"),
                          "duration": s.get("duration"), "platform": s["platform"], "why_known": s.get("error") or "skipped at review", "relevance": r.get("relevance"),
                          "relevance_why": r.get("relevance_why"), "potential": score, "fits": fit, "why": why, "same_creator_as_priority": (s.get("channel") in prio_creators),
                          "actions": {"capture": {"method": "POST", "endpoint": f"/api/sources/{s['id']}/retry", "label": "Ingest anyway"},
                                      "dismiss": {"method": "DELETE", "endpoint": f"/api/projects/{project_id}/members", "body": {"source_ids": [s["id"]]}, "label": "Not for this project"}}})
    with perf.timed("pool.score_candidates"):
        links: dict[str, list[str]] = {}
        for r in conn.execute("""SELECT l.candidate_id, t.question FROM candidate_links l LEFT JOIN project_evidence_targets t ON t.id=l.ref_id
                                 WHERE l.project_id=? AND l.state='open' AND l.kind='evidence_target'""", (project_id,)).fetchall():
            links.setdefault(r["candidate_id"], []).append(r["question"] or "an open question")
        for c in list_for_project(project_id, limit=100000):
            if c.get("state") not in ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost", "needs_membership"):
                continue
            score, fit, why = _potential(c.get("title") or "", c.get("description") or "", qs, vocab, c.get("relevance"), links.get(c["id"], []),
                                         creator=c.get("creator"), creator_stats=cy, want_classes=want_classes, qindex=qidx)
            origin = c.get("origin") or {}
            known = ("found for an open question" if links.get(c["id"]) else f"seen in {origin.get('kind', 'exploration')}{(' of ' + str(origin.get('title'))) if origin.get('title') else ''}")
            if c.get("reason"):
                known += f" · {c['reason']}"
            gated = c.get("state") == "needs_membership"
            actions = {"dismiss": {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/dismiss", "body": {"project_id": project_id}, "label": "Not for this project"}}
            if not gated:
                actions["capture"] = {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/acquire", "body": {"project_id": project_id}, "label": "Capture"}
            items.append({"kind": "candidate", "id": c["id"], "title": c.get("title") or c["url"], "url": c["url"], "creator": c.get("creator"), "published_at": c.get("published_at"),
                          "duration": c.get("duration"), "platform": c["platform"], "why_known": known, "relevance": c.get("relevance"), "relevance_why": c.get("relevance_why"),
                          "potential": score, "fits": fit, "why": why, "same_creator_as_priority": (c.get("creator") in prio_creators), "state": c.get("state"),
                          "actions": actions})
    return items


def pool(project_id: str, q: str | None = None, rank_by: str = "fit", limit: int = 100, kind: str = "all") -> dict[str, Any]:
    """Skipped sources (the ingest cutoff) and Candidate Index rows (available + skipped-low-relevance) as ONE ranked list:
    why known · potential · what it fits · one-click capture or dismissal. Never evidence until ingested; never the web.

    The scoring is `_pool_items`, cached per revision; everything here is a filter, a sort and a slice."""
    from . import cache, perf
    with perf.timed("pool.items"):
        all_items = cache.get_or_compute(f"pool_items:{project_id}", db.project_pool_revision(project_id),
                                         lambda: _pool_items(project_id), label="pool_items")
    items = all_items if kind == "all" else [i for i in all_items if i["kind"] == ("skipped" if kind == "skipped" else "candidate")]
    if q:
        qt = _toks(q)
        items = [i for i in items if qt <= _toks(i["title"] + " " + (i.get("creator") or "") + " " + " ".join(i["why"]))]
    keyf = {"fit": lambda i: (-i["potential"], -(i.get("relevance") or 0), i["title"]),
            "relevance": lambda i: (-(i.get("relevance") or 0), -i["potential"]),
            "newest": lambda i: ((i.get("published_at") or ""), ),
            "creator": lambda i: (0 if i["same_creator_as_priority"] else 1, -i["potential"])}.get(rank_by, lambda i: (-i["potential"],))
    items = sorted(items, key=keyf, reverse=(rank_by == "newest"))   # never sort the cached list in place
    counts = {"skipped": sum(1 for i in items if i["kind"] == "skipped"), "candidates": sum(1 for i in items if i["kind"] == "candidate"),
              "worth_a_look": sum(1 for i in items if i["potential"] >= WORTH_A_LOOK), "fits_a_question": sum(1 for i in items if i["fits"] and not str(i["fits"]).startswith("area:"))}
    return {"total": len(items), "items": items[:limit], "counts": counts, "rank_by": rank_by,
            "explain": "Known but never captured: sources the review skipped (older than the cutoff) and sources seen while exploring. Potential is a $0 scan of the title and description against your open questions, weak areas and the project's own words — a hint for review, never a verdict. Nothing here is evidence until you capture it."}


# ---------------------------------------------------------------- AD1: small-batch discovery
#
# "5 best next" over the SAME ranked pool `pool()` already assembles -- not a parallel surface. Deliberately no new
# `shown`/`seen`/cursor/session state: a resolved item (captured -> state='acquired', rejected -> state=
# 'user_dismissed') already drops out of `_pool_items()` on the very next call, because `project_pool_revision`
# already changes when `mark()` writes a new `candidate_projects.state` (see its own docstring on what it tracks).
# So "5 more" is just calling this again after resolving what's in front of you -- an unresolved item is correctly
# allowed to come back, because Neuro has not received a decision on it yet. Scoped to kind="candidates" only:
# "skipped" sources are the ingest-review cutoff's own list, a different, already-served flow (the full pool
# table's retry path) -- AD1 is about genuinely new discovery, not that backlog.

def next_batch(project_id: str, *, n: int = 5, rank_by: str = "fit", q: str | None = None) -> dict[str, Any]:
    n = max(1, min(n, 50))
    lookahead = max(n, min(n * BATCH_LOOKAHEAD_MULT, 50))    # AD2: bounded, cheap (`_pool_items` is cached; this
    r = pool(project_id, q=q, rank_by=rank_by, limit=lookahead, kind="candidates")   # only slices/reranks metadata)
    items = r["items"]
    if rank_by == "fit":                       # AD2/AD3 are a FIT adaptive path; every other explicit mode keeps
        items = rerank(project_id, items, max_per_creator=BATCH_MAX_PER_CREATOR)     # its own documented ordering
        items = apply_exploration(project_id, items, n)
    batch = items[:n]
    if rank_by == "fit":
        batch = [dict(i, exploratory=bool(i.get("exploratory"))) for i in batch]     # explicit false, never absent
    return {"items": batch, "remaining": max(0, r["counts"]["candidates"] - len(batch)),
            "explain": "Up to N candidates never yet captured or rejected, best first. Resolve each with capture "
                       "or reject; call again for the next best unresolved ones -- there is no separate queue or "
                       "session, just what has not been decided yet."}


# ---------------------------------------------------------------- AD3: exploration quota
#
# The purpose is narrow and specific: prevent Adaptive Discovery from becoming increasingly confident inside the
# preferences it has already learned. It is NOT randomness, not a low-relevance pick, not a second recommendation
# model, and not "different for the sake of different" -- `rerank`'s diversity cap already solves "don't show five
# of one creator"; this solves a different problem: "don't let a learned preference signal crowd out a promising
# candidate from a creator/source pattern this project has barely evaluated." EXPLORE = neutral/insufficient
# disposition history (`creator_disposition`'s own `adjust == 0`), never a negatively-learned creator, never a
# dismissed or acquired one (both already excluded from `items` by `_pool_items` itself), and never below the
# same "worth a look" floor the rest of the pool uses. No randomness, no persistent exploration state, no new
# schema, no second model call -- one deterministic pick per call, at most, reusing signals AD2 already computes.

EXPLORATION_MIN_BATCH = 2     # below this, "4 exploit + up to 1 explore" doesn't mean anything -- no-op


def apply_exploration(project_id: str, items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Tags at most one item among `items[:n]` as `exploratory` -- either one that already naturally qualifies, or
    the single best eligible candidate found beyond the top-n, swapped in for the current lowest-potential slot.
    Only runs when the project has SOME learned disposition signal at all (`adjust != 0` for at least one creator
    in this lookahead); with nothing learned yet, ordinary ranking is already exploratory, so this is a no-op."""
    if n < EXPLORATION_MIN_BATCH or len(items) <= n:
        return items
    disp = creator_disposition(project_id)
    if not any(d["adjust"] != 0 for d in disp.values()):
        return items
    stale = _stale_linked_targets(project_id, [i["id"] for i in items])

    def is_eligible(item: dict[str, Any]) -> bool:
        d = disp.get((item.get("creator") or "").strip())
        neutral = d is None or d["adjust"] == 0
        negative = bool(d and d["adjust"] < 0)
        return neutral and not negative and item["id"] not in stale and item["potential"] >= WORTH_A_LOOK

    top, rest = items[:n], items[n:]
    in_top = [i for i in top if is_eligible(i)]
    why = "Promising fit from a source pattern this project has not evaluated much yet."
    if in_top:
        chosen_id = max(in_top, key=lambda i: i["potential"])["id"]
        return [dict(i, exploratory=True, exploration_why=why) if i["id"] == chosen_id else i for i in top] + rest
    beyond = [i for i in rest if is_eligible(i)]
    if not beyond:
        return items
    top_creators = {(i.get("creator") or "").strip() for i in top}
    fresh = [i for i in beyond if (i.get("creator") or "").strip() not in top_creators]
    best = max(fresh or beyond, key=lambda i: i["potential"])
    new_top = top[:-1] + [dict(best, exploratory=True, exploration_why=why)]
    new_top.sort(key=lambda i: (-i["potential"], i["title"]))
    new_rest = [i for i in rest if i["id"] != best["id"]]
    return new_top + new_rest


# ---------------------------------------------------------------- AD2: deterministic rerank
#
# Adjusts the SAME `potential` score `pool()` already computed -- never a replacement, never touching `_potential()`
# or the full pool table. Two signals AD0 (`docs/AD0-FEEDBACK-INVENTORY.md`) named for AD2, both reused from
# existing state, no new schema, no model call:
#   PRIMARY   candidate disposition (`candidate_projects.state`) -- a creator this project keeps ACQUIRING should
#             rank higher; one it keeps REJECTING should rank lower. A rate, not a raw count (an 8-dismissal
#             creator with 80 decisions is mostly accepted; a 3-dismissal creator with 3 decisions is not), gated
#             on a minimum decided count so one early rejection never becomes a verdict, and capped well below
#             `_potential`'s own target-fit terms so history adjusts the ranking, never overrides it.
#   SECONDARY link outcome (`candidate_links.state`) -- `_potential` already rewards a candidate linked to a
#             still-open evidence target (`LINKED_BOOST`); what it cannot see is a target that closed through a
#             DIFFERENT candidate after this link was recorded, since only the acquired candidate's own links get
#             marked `satisfied` (`satisfy_links`). This corrects exactly that stale case, nothing else.
# Only `candidate_projects.state='acquired' | 'user_dismissed' | 'skipped_low_relevance'` count as a preference
# signal: `skipped_limit` / `skipped_cost` / `duplicate` are operational (a review cap, a budget, an identity
# collision) and are never read as "this project dislikes this creator."
#
# Diversity is a small-BATCH composition rule, not a source-quality judgment: it caps how many of one creator's
# items can fill the batch RETURNED right now, over a bounded lookahead window so a real alternative can actually
# surface (`next_batch` asks `pool()` for more than `n` before reranking) -- it never drops anything; a deferred
# item is simply pushed past the cap and stays eligible for a later `next_batch` call, same as any undecided item.

BATCH_LOOKAHEAD_MULT = 4     # next_batch looks this many times past `n` before reranking -- bounded, not paginated
BATCH_MAX_PER_CREATOR = 2    # at most this many of one creator in a single returned batch
DISPOSITION_MIN_DECISIONS = 3       # fewer decided outcomes than this and a creator's rate is not a signal yet --
DISPOSITION_MAX_ADJUST = 12         # mirrors CREATOR_MIN_SOURCES's own "one data point proves nothing" discipline
DISPOSITION_STATES = ("acquired", "user_dismissed", "skipped_low_relevance")   # the only preference-bearing states


def creator_disposition(project_id: str) -> dict[str, dict[str, Any]]:
    """creator -> how this project has actually decided on that creator's OTHER items, as a bounded rate-based
    adjustment, never a raw count. `skipped_low_relevance` counts as a soft negative (its own reason string is a
    genuine relevance judgment made in review, not an operational constraint); `skipped_limit`/`skipped_cost`/
    `duplicate`/`available` never do -- a review cap or a budget ceiling is not "Kyle dislikes this creator"."""
    conn = db.connect()
    rows = conn.execute(f"""SELECT c.creator cr, cp.state st, COUNT(*) n FROM candidate_projects cp
                            JOIN candidates c ON c.id=cp.candidate_id
                            WHERE cp.project_id=? AND cp.state IN ({",".join("?" * len(DISPOSITION_STATES))}) AND c.creator IS NOT NULL
                            GROUP BY c.creator, cp.state""", (project_id, *DISPOSITION_STATES)).fetchall()
    by_creator: dict[str, dict[str, int]] = {}
    for r in rows:
        by_creator.setdefault(r["cr"].strip(), {})[r["st"]] = r["n"]
    out: dict[str, dict[str, Any]] = {}
    for creator, counts in by_creator.items():
        pos = counts.get("acquired", 0)
        neg = counts.get("user_dismissed", 0) + 0.5 * counts.get("skipped_low_relevance", 0)
        decided = counts.get("acquired", 0) + counts.get("user_dismissed", 0) + counts.get("skipped_low_relevance", 0)
        if decided < DISPOSITION_MIN_DECISIONS:
            out[creator] = {"adjust": 0, "decided": decided, "pos": pos, "neg": neg, "why": None}
            continue
        rate = max(-1.0, min(1.0, (pos - neg) / decided))
        adjust = int(round(DISPOSITION_MAX_ADJUST * rate))
        why = None
        if adjust:
            why = (f"this project has mostly acquired {creator}'s items before ({pos} of {decided} decided)" if adjust > 0
                  else f"this project has mostly rejected {creator}'s items before ({int(counts.get('user_dismissed', 0))} of {decided} decided)")
        out[creator] = {"adjust": adjust, "decided": decided, "pos": pos, "neg": neg, "why": why}
    return out


def _stale_linked_targets(project_id: str, candidate_ids: list[str]) -> set[str]:
    """Candidate ids whose ONLY open evidence-target link(s) point to a target that is no longer actually open --
    `_potential` rewarded them for a need that has since closed through some OTHER candidate (only the candidate
    that closes it gets its own links marked `satisfied`; this reads the target's real, current status instead of
    trusting a link row that was never told). One read-only query, no new gap-routing system."""
    if not candidate_ids:
        return set()
    conn = db.connect()
    ph = ",".join("?" * len(candidate_ids))
    fresh: set[str] = set()
    any_link: set[str] = set()
    for r in conn.execute(f"""SELECT l.candidate_id cid, t.status st FROM candidate_links l
                              LEFT JOIN project_evidence_targets t ON t.id=l.ref_id
                              WHERE l.project_id=? AND l.kind='evidence_target' AND l.state='open'
                              AND l.candidate_id IN ({ph})""", (project_id, *candidate_ids)).fetchall():
        any_link.add(r["cid"])
        if (r["st"] or "open") == "open":
            fresh.add(r["cid"])
    return any_link - fresh


def rerank(project_id: str, items: list[dict[str, Any]], *, max_per_creator: int = BATCH_MAX_PER_CREATOR) -> list[dict[str, Any]]:
    """AD2. Adjusts a copy of `items` (as `pool()` already scored and sorted them) with disposition + stale-link
    corrections, re-sorts, then applies the batch-local diversity cap. Nothing is dropped: over-cap items are
    deferred to the tail, not discarded, so a later `next_batch` call still sees them."""
    if not items:
        return items
    disp = creator_disposition(project_id)
    stale = _stale_linked_targets(project_id, [i["id"] for i in items])
    adjusted = []
    for i in items:
        item = dict(i)
        item["why"] = list(item.get("why") or [])
        item["base_potential"] = item["potential"]      # AD4 prep: the pre-adjustment score, kept alongside the
        d = disp.get((i.get("creator") or "").strip())   # adaptive one -- no telemetry, just one derived field
        if d and d["adjust"]:
            item["potential"] = max(0, min(100, item["potential"] + d["adjust"]))
            item["why"].append(d["why"])
        if i["id"] in stale:
            item["potential"] = max(0, item["potential"] - LINKED_BOOST)
            item["why"] = [w for w in item["why"] if not w.startswith("already found for")]
            item["why"].append("the question it was linked to is no longer open")
        adjusted.append(item)
    adjusted.sort(key=lambda i: (-i["potential"], i["title"]))
    capped: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for i in adjusted:
        c = (i.get("creator") or "").strip()
        if seen.get(c, 0) >= max_per_creator:
            deferred.append(i)
        else:
            seen[c] = seen.get(c, 0) + 1
            capped.append(i)
    return capped + deferred
