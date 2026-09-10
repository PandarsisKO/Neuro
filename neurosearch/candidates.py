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
import time
from typing import Any

from . import db

STATES = ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost", "user_dismissed", "duplicate", "acquired")
LOW_RELEVANCE = 50            # a ranked score below this is a "skipped for low relevance", not a "skipped by the limit"
CONTENT_TYPE = {"youtube": "video", "instagram": "post", "podcast": "podcast", "web": "page", "media": "video", "document": "document", "book": "book"}


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
            r = conn.execute("SELECT * FROM candidates WHERE platform=? AND external_id=?", (platform, ext)).fetchone()
            if r:
                cid = r["id"]
                patch: dict[str, Any] = {"last_seen_at": t}
                for k in ("title", "description", "creator", "published_at", "duration", "view_count", "canonical_url", "source_id"):
                    if e.get(k) is not None and not r[k]:              # fill what is empty; never overwrite what we knew
                        patch[k] = e[k] if k != "description" else str(e[k])[:2000]
                conn.execute("UPDATE candidates SET " + ", ".join(f"{k}=?" for k in patch) + " WHERE id=?", (*patch.values(), cid))
            else:
                cid = db.new_id()
                conn.execute("INSERT INTO candidates (id, platform, external_id, canonical_url, url, title, description, creator, published_at, duration, view_count, "
                             "content_type, language, first_seen_at, last_seen_at, source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, platform, ext, e.get("canonical_url"), e.get("url") or "", e.get("title"), (e.get("description") or "")[:2000] or None, e.get("creator"),
                              e.get("published_at"), e.get("duration"), e.get("view_count"), e.get("content_type") or CONTENT_TYPE.get(platform, "page"),
                              e.get("language"), t, t, e.get("source_id")))
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
    with db.tx() as conn:
        conn.execute("UPDATE candidates SET source_id=?, last_verified_at=? WHERE platform=? AND external_id=? AND source_id IS NULL", (source_id, time.time(), platform, external_id))
        conn.execute("UPDATE candidate_links SET state='satisfied', updated_at=? WHERE state='open' AND candidate_id IN (SELECT id FROM candidates WHERE platform=? AND external_id=?)",
                     (time.time(), platform, external_id))          # B3: the need this source served is met


def dismiss(project_id: str, candidate_id: str, reason: str | None) -> int:
    return mark(project_id, [candidate_id], "user_dismissed", reason or "dismissed by the user")


def restore(project_id: str, candidate_id: str) -> int:
    return mark(project_id, [candidate_id], "available", "restored by the user")


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
    rows, and the evidence classes it has actually supplied. $0, derived on read, no model, no schema change."""
    conn = db.connect()
    ids = set(db.project_source_ids(project_id, ready_only=False))
    if not ids:
        return {}
    chan: dict[str, str] = {}
    for sid in ids:
        s = db.get_source(sid)
        if s and (s.get("channel") or "").strip():
            chan[sid] = s["channel"].strip()
    if not chan:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for c in set(chan.values()):
        out[c] = {"sources": 0, "findings": 0, "claims": 0, "evidence": 0, "classes": {}}
    for sid, c in chan.items():
        out[c]["sources"] += 1
    ph = ",".join("?" * len(chan))
    args = list(chan)
    for r in conn.execute(f"SELECT source_id, COUNT(*) n FROM project_notes WHERE project_id=? AND source_id IN ({ph}) GROUP BY source_id",
                          (project_id, *args)).fetchall():
        out[chan[r["source_id"]]]["findings"] += r["n"]
    for r in conn.execute(f"""SELECT n.source_id sid, COUNT(*) n FROM project_claims c JOIN project_notes n ON n.id=c.origin_note_id
                              WHERE c.project_id=? AND n.source_id IN ({ph}) GROUP BY n.source_id""",
                          (project_id, *args)).fetchall():
        out[chan[r["sid"]]]["claims"] += r["n"]
    for r in conn.execute(f"""SELECT e.source_id sid, e.evidence_class cls, COUNT(*) n FROM claim_evidence e
                              JOIN project_claims c ON c.id=e.claim_id
                              WHERE c.project_id=? AND e.source_id IN ({ph}) GROUP BY e.source_id, e.evidence_class""",
                          (project_id, *args)).fetchall():
        row = out[chan[r["sid"]]]
        row["evidence"] += r["n"]
        if r["cls"]:
            row["classes"][r["cls"]] = row["classes"].get(r["cls"], 0) + r["n"]
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


def _potential(title: str, desc: str, qs: list[tuple[str, str, set[str]]], vocab: set[str], relevance: int | None, linked: list[str],
               creator: str | None = None, creator_stats: dict[str, dict[str, Any]] | None = None,
               want_classes: set[str] | None = None) -> tuple[int, str | None, list[str]]:
    """A quick $0 scan: 0–100 potential, the best fit (an open question / weak area), and the reasons. Words, plus
    (0.58.2) what this item's MASTER SOURCE has already given the project — see `creator_yield`."""
    t = _toks(title + " " + (desc or "")[:600])
    best, best_s = None, 0.0
    for qid, label, qt in qs:
        if not qt:
            continue
        s = len(t & qt) / max(3, len(qt))
        if s > best_s:
            best, best_s = label, s
    why = []
    score = 0
    if linked:
        score += 45; why.append(f"already found for: {linked[0][:60]}")
    if best_s >= 0.34:
        score += int(35 * min(1.0, best_s)); why.append(f"fits an open question: {best}")
    cov = len(t & vocab) / max(4, len(vocab)) if vocab else 0
    if cov > 0:
        score += int(20 * min(1.0, cov * 4)); why.append("uses the project's own vocabulary")
    if relevance is not None:
        score += int(relevance * 0.25); why.append(f"ranked {relevance}/100 at review")
    ever = len({w for w in t if any(w.startswith(e) for e in EVERGREEN)})
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
        if c.get("state") in ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost"):
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


def pool(project_id: str, q: str | None = None, rank_by: str = "fit", limit: int = 100, kind: str = "all") -> dict[str, Any]:
    """Skipped sources (the ingest cutoff) and Candidate Index rows (available + skipped-low-relevance) as ONE ranked list:
    why known · potential · what it fits · one-click capture or dismissal. Never evidence until ingested; never the web."""
    conn = db.connect()
    qs, vocab = _gap_terms(project_id)
    prio_creators = {(db.get_source(sid) or {}).get("channel") for sid in db.priority_source_ids(project_id)} - {None, ""}
    cy = creator_yield(project_id)                       # 0.58.2: what each master source has already given us
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
    if kind in ("all", "skipped"):
        rel = db.project_analysis(project_id, "relevance")
        ids = set(db.project_source_ids(project_id, ready_only=False))
        for s in db.list_sources(status="skipped", limit=100000):
            if s["id"] not in ids:
                continue
            r = rel.get(s["id"]) or {}
            score, fit, why = _potential(s.get("title") or "", s.get("description") or "", qs, vocab, r.get("relevance"), [],
                                         creator=s.get("channel"), creator_stats=cy, want_classes=want_classes)
            items.append({"kind": "skipped", "id": s["id"], "title": s.get("title") or s["url"], "url": s["url"], "creator": s.get("channel"), "published_at": s.get("published_at"),
                          "duration": s.get("duration"), "platform": s["platform"], "why_known": s.get("error") or "skipped at review", "relevance": r.get("relevance"),
                          "relevance_why": r.get("relevance_why"), "potential": score, "fits": fit, "why": why, "same_creator_as_priority": (s.get("channel") in prio_creators),
                          "actions": {"capture": {"method": "POST", "endpoint": f"/api/sources/{s['id']}/retry", "label": "Ingest anyway"},
                                      "dismiss": {"method": "DELETE", "endpoint": f"/api/projects/{project_id}/members", "body": {"source_ids": [s["id"]]}, "label": "Not for this project"}}})
    if kind in ("all", "candidates"):
        links: dict[str, list[str]] = {}
        for r in conn.execute("""SELECT l.candidate_id, t.question FROM candidate_links l LEFT JOIN project_evidence_targets t ON t.id=l.ref_id
                                 WHERE l.project_id=? AND l.state='open' AND l.kind='evidence_target'""", (project_id,)).fetchall():
            links.setdefault(r["candidate_id"], []).append(r["question"] or "an open question")
        for c in list_for_project(project_id, limit=100000):
            if c.get("state") not in ("available", "skipped_low_relevance", "skipped_limit", "skipped_cost"):
                continue
            score, fit, why = _potential(c.get("title") or "", c.get("description") or "", qs, vocab, c.get("relevance"), links.get(c["id"], []),
                                         creator=c.get("creator"), creator_stats=cy, want_classes=want_classes)
            origin = c.get("origin") or {}
            known = ("found for an open question" if links.get(c["id"]) else f"seen in {origin.get('kind', 'exploration')}{(' of ' + str(origin.get('title'))) if origin.get('title') else ''}")
            if c.get("reason"):
                known += f" · {c['reason']}"
            items.append({"kind": "candidate", "id": c["id"], "title": c.get("title") or c["url"], "url": c["url"], "creator": c.get("creator"), "published_at": c.get("published_at"),
                          "duration": c.get("duration"), "platform": c["platform"], "why_known": known, "relevance": c.get("relevance"), "relevance_why": c.get("relevance_why"),
                          "potential": score, "fits": fit, "why": why, "same_creator_as_priority": (c.get("creator") in prio_creators), "state": c.get("state"),
                          "actions": {"capture": {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/acquire", "body": {"project_id": project_id}, "label": "Capture"},
                                      "dismiss": {"method": "POST", "endpoint": f"/api/candidates/{c['id']}/dismiss", "body": {"project_id": project_id}, "label": "Not for this project"}}})
    if q:
        qt = _toks(q)
        items = [i for i in items if qt <= _toks(i["title"] + " " + (i.get("creator") or "") + " " + " ".join(i["why"]))]
    keyf = {"fit": lambda i: (-i["potential"], -(i.get("relevance") or 0), i["title"]),
            "relevance": lambda i: (-(i.get("relevance") or 0), -i["potential"]),
            "newest": lambda i: ((i.get("published_at") or ""), ),
            "creator": lambda i: (0 if i["same_creator_as_priority"] else 1, -i["potential"])}.get(rank_by, lambda i: (-i["potential"],))
    items.sort(key=keyf, reverse=(rank_by == "newest"))
    counts = {"skipped": sum(1 for i in items if i["kind"] == "skipped"), "candidates": sum(1 for i in items if i["kind"] == "candidate"),
              "worth_a_look": sum(1 for i in items if i["potential"] >= 40), "fits_a_question": sum(1 for i in items if i["fits"] and not str(i["fits"]).startswith("area:"))}
    return {"total": len(items), "items": items[:limit], "counts": counts, "rank_by": rank_by,
            "explain": "Known but never captured: sources the review skipped (older than the cutoff) and sources seen while exploring. Potential is a $0 scan of the title and description against your open questions, weak areas and the project's own words — a hint for review, never a verdict. Nothing here is evidence until you capture it."}
