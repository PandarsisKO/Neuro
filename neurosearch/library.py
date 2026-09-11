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
from .config import int_env, settings

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
# 0.60.2 — WHY THIS WAS RETURNING AN AIRBNB VIDEO AS A STRONG MATCH FOR "enterprise UX complex workflows".
#
# Kyle, testing a new AI-UI/UX project against a library built mostly from business and real-estate research:
# *"it clearly is pulling bad data."* Three separate faults, measured on his own library (1,219 sources with
# chunks, the query he actually typed):
#
#   * `_tokens` required THREE characters, so "ux" was never a query term at all — the query was silently
#     "enterprise complex workflows", and the UI's own line said "2 of 3 query terms". Two-letter terms are exactly
#     the domain anchors in his field: ux, ui, ai, qa, 3d.
#   * coverage counted the UNION of the best three passages, so a source could "cover" a query by mentioning
#     different words in three unrelated places. 44 of the 63 sources that passed did so only by scattering.
#   * every term counted the same, so matching the two most generic words was enough.
#
# The obvious fix — IDF-weight the terms — was measured first and rejects **none** of the 63: his query's words
# have similar rarity (idf: enterprise 2.62, ux 2.95, complex 1.80, workflows 2.79), so weighting changes nothing.
# What works is requiring the query's RAREST term to actually appear (25 of 63 survive: Pencil & Paper, UI
# Collective, Figma — and out go "The Mathematics of Business", "How AI is breaking the SaaS business model",
# "If I Wanted to Become a Millionaire in 2026"), and reserving `strong` for a source where ONE passage clears the
# bar. Both are one explainable sentence to a user; a weighting scheme is not.
ANCHOR_MIN_TERMS = 2                # a one-word query has no distinctive term to anchor on; the rule is skipped
ANCHOR_MAX_DF_SHARE = 0.5           # if even the rarest term is in half the library, anchoring says nothing
# Two guards, both of which turn the rule OFF rather than on, so neither can invent a false negative. They are
# STRUCTURAL judgements, not calibrations — the measured evidence above covers a deliberate four-word query:
#   * a long block of prose is not a deliberate phrase. `bootstrap._clauses` already splits a goal for this same
#     reason; a whole brief's rarest word is more likely incidental than definitive, so above ANCHOR_MAX_TERMS the
#     query has no anchor.
#   * a word only one source in the library uses cannot separate topics — requiring it is retrieval, not
#     relevance. (This is what made the rule reject every hit in the nine-source test fixture.)
ANCHOR_MAX_TERMS = 8
ANCHOR_MIN_SOURCES = 2
ANCHOR_MIN_MENTIONS = 2             # one mention in a whole transcript is a passing remark, not a topic (0.62.0)
ANCHOR_MENTION_MIN_CHUNKS = 3       # ...but one mention in a SHORT source is its whole content, so the rule waits
ANCHOR_SHARE_MIN_LIBRARY = 40       # a proportion of a handful of sources is not a proportion

# Measured on Kyle's 1,229-source library, 2026-09-10, after "Modern CPA" returned eight house-flipping and
# web-design videos. Two defects, and the second is not a statistics problem at all.
#
# ANCHOR_MAX_DF_SHARE was 0.5, which would have anchored happily on "accountant" — a word in 49.6% of his
# library. The measured distribution: accountant 49.6%, designing 40.8%, improving 26.6%, seller 25.6%,
# complex 20.9%, workflows 14.3%, auditing 11.6%, cpa 10.6%, modern 10.4%, ui 10.2%, franchise 8.5%,
# enterprise 8.0%, bookkeeping 6.7%, ux 5.9%, laundromat 5.3%, reusable 2.4%, cognitive 1.7%. Everything that
# names a topic sits at or below a quarter of the library; everything above it is vocabulary the whole corpus
# shares. 0.25 is where that line falls, and it is a judgement about what a corpus-wide word can tell you, not a
# figure tuned until one query behaved.
#
# GENERIC_MODIFIERS is the harder half, and honesty demands it be a list rather than a threshold. "modern" is in
# 128 of his sources and "cpa" in 130, so RARITY CHOSE THE USELESS WORD BY A MARGIN OF TWO SOURCES. Nothing
# countable separates them: they are equally often in titles (2 each), and mentions-per-source prefers "cpa"
# (2.35 vs 1.66) but prefers "designing" (6.54) over both, so that measure is a coincidence here, not a rule.
# What actually distinguishes them is that "modern" is a modifier — it attaches to any topic in any field and
# denotes none. That is a linguistic fact a frequency count cannot discover, so it is written down where a human
# can read and correct it. These words are excluded from ANCHOR CHOICE ONLY: they still match, still score, still
# count towards coverage. And they are only skipped when the query has another content word left — if a search is
# nothing but modifiers, the honest answer is that it is too vague, not that it has no anchor.
ANCHOR_TOO_COMMON_SHARE = 0.5       # "in MOST of the library" — absolute, true of 9 sources in 11, never guarded
ANCHOR_MAX_DF_SHARE = 0.25          # "too common to be distinctive" — a calibration, so it waits for a real library
GENERIC_MODIFIERS = frozenset({
    "modern", "best", "new", "newest", "latest", "top", "good", "great", "better", "simple", "easy", "quick",
    "fast", "advanced", "basic", "ultimate", "complete", "full", "professional", "proper", "real", "true",
    "smart", "powerful", "effective", "efficient", "useful", "helpful", "popular", "common", "typical",
    "current", "recent", "old", "traditional", "classic", "big", "small", "large", "huge", "cheap", "free",
    "expensive", "important", "essential", "key", "main", "major", "minor", "general", "overall", "successful",
    # 0.63.25 — MEASURED on Kyle's live library: searching his business-acquisition project for
    # **"quality of earnings"** — a term of art in that field, a QoE report — anchored on **`quality`** and
    # returned "Sam Crawford | Web Design Expert", "UI Collective" and "Laundromat Millionaire". Exactly 0.62.0's
    # defect, surviving for a multi-word term of art because the list was written from the single-word case:
    # `quality` attaches to any topic in any field ("quality software", "quality of life", "quality control") and
    # denotes none, and there is no search in which it alone names the subject. Skipping it makes the anchor
    # `earnings`, which does.
    "quality",
    # The rest of this group is REASONED from the same rule, not measured — they are the words that were missing
    # from the families already here ("best/good/great" without "bad/worst", "big/small" without "high/low").
    # This is the assumption half of an assumption list, and the ledger says so.
    "high", "low", "strong", "weak", "bad", "worst", "right", "wrong", "different", "various", "multiple",
    "average", "normal", "standard", "comprehensive", "detailed", "beautiful", "nice",
})
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
            "web": "web page", "file": "uploaded media", "manual": "pasted text", "media": "media", "book": "book (EPUB)"}.get(p or "", p or "unknown")
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
    """Content terms. TWO characters is the minimum, not three (0.60.2): "ux", "ui", "ai", "qa" and "3d" are the
    most distinctive words in whole fields, and dropping them turned "enterprise UX complex workflows" into
    "enterprise complex workflows" before anything was compared. A token must contain a letter, so a year or a
    figure does not become a topic."""
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9\-']*", q.lower()):
        if len(w) < 2 or w in _STOP or not any(c.isalpha() for c in w):
            continue
        out.add(w)
    return out


def term_df(term: str) -> int:
    """How many CHUNKS in the whole library contain `term`, asked of the FTS index itself so the stemming and
    tokenisation match what `search` did. Cached on the library revision, because rarity only moves when the
    library does. `query_anchor` counts sources rather than chunks (see there); this is the passage-level view,
    kept for diagnostics."""
    from . import cache
    rev = str(db.library_revision())
    def compute() -> int:
        try:
            q = term.replace('"', " ").strip()
            if not q:
                return 0
            row = db.connect().execute("SELECT COUNT(*) n FROM chunks_fts WHERE chunks_fts MATCH ?",
                                       (f'"{q}"',)).fetchone()
            return int(row["n"] or 0)
        except Exception:  # noqa: BLE001 — an odd token must never take a recall down
            return 0
    return cache.get_or_compute(f"library:df:{term}", rev, compute, label="library_df")


def sources_with_term(term: str, source_ids: list[str] | None = None) -> set[str]:
    """Which sources contain `term` ANYWHERE, straight from the FTS index.

    The anchor is checked against the whole source, not against the three passages retrieval happened to return
    (0.60.2). A source can be entirely about your distinctive term and not use it in the three chunks that scored
    highest — that is a property of retrieval, not of the source, and letting it veto a match made the rule reject
    everything in a nine-source fixture."""
    from . import cache
    rev = str(db.library_revision())

    def compute() -> set[str]:
        try:
            q = term.replace('"', " ").strip()
            if not q:
                return set()
            rows = db.connect().execute(
                "SELECT DISTINCT c.source_id sid FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                "WHERE chunks_fts MATCH ?", (f'"{q}"',)).fetchall()
            return {r["sid"] for r in rows}
        except Exception:  # noqa: BLE001
            return set()

    hit = cache.get_or_compute(f"library:srcterm:{term}", rev, compute, label="library_df")
    return set(hit) if source_ids is None else {s for s in hit if s in set(source_ids)}


def _chunks_per_source(source_ids: list[str]) -> dict[str, int]:
    """How long each source is, in chunks. The mention floor is a statement about a long transcript: a source with
    two chunks that says the anchor once has said it in half of everything it contains."""
    if not source_ids:
        return {}
    out: dict[str, int] = {}
    try:
        for i in range(0, len(source_ids), 400):
            part = source_ids[i:i + 400]
            q = "SELECT source_id sid, COUNT(*) n FROM chunks WHERE source_id IN (%s) GROUP BY sid" % ",".join("?" * len(part))
            for r in db.connect().execute(q, part):
                out[r["sid"]] = int(r["n"] or 0)
    except Exception:  # noqa: BLE001
        return {}
    return out


def source_mentions(term: str) -> dict[str, int]:
    """source id → how many CHUNKS of it contain `term`. The aboutness measure `sources_with_term` cannot give.

    Measured (0.62.0): 66% of the sources containing "modern" contain it in exactly ONE chunk of an entire
    transcript, against 44% for "cpa". Requiring the anchor twice took precision on Kyle's "Modern CPA" search
    from 35% to 62% **with no loss of recall at all** — every on-target source mentions its own subject more than
    once. A word said once in three hours is a passing remark."""
    from . import cache
    rev = str(db.library_revision())

    def compute() -> dict[str, int]:
        out: dict[str, int] = {}
        try:
            q = term.replace('"', " ").strip()
            if not q:
                return out
            for r in db.connect().execute(
                    "SELECT c.source_id sid FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                    "WHERE chunks_fts MATCH ?", (f'"{q}"',)):
                out[r["sid"]] = out.get(r["sid"], 0) + 1
        except Exception:  # noqa: BLE001
            return {}
        return out

    return dict(cache.get_or_compute(f"library:mentions:{term}", rev, compute, label="library_df"))


def query_anchor(terms: set[str]) -> dict[str, Any]:
    """The query's most distinctive term — the one whose absence means the match is about something else.

    Returns the anchor and why, or no anchor with the reason. No anchor means the rule does not apply: a
    one-word query has nothing to anchor on, a term the library has never seen would reject everything, and a
    rarest term that still appears in half the library says nothing about topic."""
    if len(terms) < ANCHOR_MIN_TERMS:
        return {"term": None, "reason": "too few terms to have a distinctive one"}
    if len(terms) > ANCHOR_MAX_TERMS:
        return {"term": None, "reason": f"a {len(terms)}-word search is prose, not a phrase — its rarest word is "
                                        "probably incidental"}
    # Rarity is counted in SOURCES, not chunks: one three-hour video repeating a word forty times must not make
    # that word common, and "in 64 of 1,219 sources" is also the sentence a user can check.
    present = {t: len(sources_with_term(t)) for t in terms}
    known = {t: n for t, n in present.items() if n > 0}
    if not known:
        return {"term": None, "reason": "none of these words appear anywhere in the library", "df": present}
    total = max(1, db.sources_with_chunks())
    # Modifiers are set aside before the rarest word is chosen, but only while a content word survives: a search
    # made entirely of modifiers gets the vague-query answer below, not an anchor picked from among them.
    content = {t: n for t, n in known.items() if t not in GENERIC_MODIFIERS}
    skipped = sorted(set(known) - set(content))
    if not content:
        return {"term": None, "all_generic": True, "skipped": skipped, "df": known,
                "reason": "every word in this search is a generic modifier ("
                          + ", ".join(skipped[:4]) + "), so none of them names a subject"}
    term = min(content, key=lambda t: (content[t], t))
    known_for_report, known = known, content
    # `too_common` is the no-anchor case that says something about the QUERY rather than about the library: every
    # word in it is everywhere, so it cannot separate topics at all (bootstrap.query_strength reads this). There are
    # two bars, and the distinction matters. "In MOST of the library" is an absolute judgement — 9 sources out of 11
    # really is most — so it holds at any size. The tighter quarter-of-the-library bar is a CALIBRATION against a
    # measured distribution, so it waits for a library large enough for a proportion to mean anything; guarding it
    # is what stops a rule from firing on a handful of sources, and 0.62.0's first attempt guarded BOTH bars and so
    # silently switched off the generic-query judgement in small libraries.
    share = known[term] / total
    if share > ANCHOR_TOO_COMMON_SHARE:
        return {"term": None, "too_common": True, "rarest": term, "sources": known[term], "share": round(share, 4),
                "reason": f"even the rarest word ('{term}') is in most of the library", "df": known}
    if total >= ANCHOR_SHARE_MIN_LIBRARY and share > ANCHOR_MAX_DF_SHARE:
        return {"term": None, "too_common": True, "rarest": term, "sources": known[term], "share": round(share, 4),
                "reason": f"even the rarest word ('{term}') is in more than a quarter of your library "
                          f"({known[term]} of {total} sources), which cannot tell one subject from another",
                "df": known}
    if known[term] < ANCHOR_MIN_SOURCES:
        return {"term": None, "reason": f"'{term}' appears in too few sources to separate one topic from another",
                "df": known}
    return {"term": term, "sources": known[term], "of_sources": total, "share": round(known[term] / total, 4),
            "skipped_generic": skipped, "min_mentions": ANCHOR_MIN_MENTIONS,
            "reason": f"'{term}' is the rarest word in this search that names a subject, so a match that never says "
                      f"it is about something else"
                      + (f" (ignored as generic: {', '.join(skipped[:3])})" if skipped else ""),
            "df": known_for_report}


OWNED_SATURATED_SHARE = 0.6         # the project already holds this much of the library's coverage → say so (0.62.4)


def coverage_of(project_id: str | None, term: str | None) -> dict[str, Any]:
    """How much of the library's coverage of `term` this project ALREADY HOLDS.

    **Measured on Kyle's project, 2026-09-10, after he said the fixed search was still useless.** The six results
    were all real-estate tax videos in a business-acquisition project, and the reason was not ranking:

        term                 in library   already in this project   outside
        cpa                        130          115  (88%)              15
        sba                        212          191  (90%)              21
        quality of earnings         27           25  (93%)               2
        addbacks                     7            7 (100%)               0

    Library-first recall can only offer what the project does NOT have, so for its own subject matter this project
    has a pool of leftovers — 8 sources with two or more mentions of "cpa", 7 of them about short-term rentals.
    The list was not a bad ranking of a good pool; it was nearly the whole pool. Meanwhile the card said **"In your
    library — no new acquisition needed"**, which is a false statement about the dregs and is what made it useless
    rather than merely thin.

    Saturation is a real answer, and the cheapest one in the app: it says the subject is already absorbed, that the
    web is where anything new will come from, and that the useful move is to search inside the project rather than
    acquire more. It needs no model and no new data — `sources_with_term` is already cached on the library
    revision."""
    if not term:
        return {"term": None}
    have = sources_with_term(term)
    if not have:
        return {"term": term, "in_library": 0, "in_project": 0, "outside": 0, "saturated": False,
                "note": f"nothing in your library mentions \"{term}\""}
    mine = set(db.project_source_ids(project_id, ready_only=False)) if project_id else set()
    inside = len(have & mine)
    outside = len(have) - inside
    share = inside / len(have)
    out = {"term": term, "in_library": len(have), "in_project": inside, "outside": outside,
           "share_owned": round(share, 3), "saturated": share >= OWNED_SATURATED_SHARE and project_id is not None}
    if out["saturated"]:
        out["note"] = (f"{len(have)} sources in your library discuss \"{term}\" and this project already has "
                       f"{inside} of them — {share:.0%}. Only {outside} are left outside it, so a web search is "
                       f"where anything new will come from; to use what you already own, search inside the project.")
    else:
        out["note"] = (f"{len(have)} sources in your library discuss \"{term}\"; this project has {inside}, "
                       f"leaving {outside} it does not.")
    return out


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
    from . import perf
    from .search import search
    q = (query or "").strip()
    with perf.timed("recall.scope"):
        scope = library_scope(project_id)
    if not q or not scope:
        return {"query": q, "suggestions": [], "scope": len(scope), "enrichment": {"wanted": 0}}
    # 0.62.1: the whole pass is staged in the timing ledger. Kyle measured a library-only Discover at **195 s**
    # with no model call, no web request and no dollars, against a UI that advertises about ten seconds — and the
    # only honest way to find that is to time the stages rather than reason about which one looks expensive.
    with perf.timed("recall.search"):
        hits = search(q, limit=RECALL_CHUNKS, source_ids=scope, per_source_cap=PER_SOURCE_CHUNKS, reserve=0)
    qt = _tokens(q)
    with perf.timed("recall.anchor"):
        anchor = query_anchor(qt)
    # 0.62.0: aboutness, not presence. `anchored` is the set of sources that mention the anchor at least
    # ANCHOR_MIN_MENTIONS times; a single mention is reported separately so the reason can say which it was.
    with perf.timed("recall.mentions"):
        mention_counts = source_mentions(anchor["term"]) if anchor.get("term") else {}
        chunks_per = _chunks_per_source(list(mention_counts)) if mention_counts else {}
    anchored = {sid for sid, n in mention_counts.items()
                if n >= ANCHOR_MIN_MENTIONS or chunks_per.get(sid, 0) < ANCHOR_MENTION_MIN_CHUNKS}
    rejected = {"no_anchor_term": 0, "anchor_mentioned_once": 0, "low_coverage": 0, "low_score": 0}
    by_src: dict[str, dict[str, Any]] = {}
    for h in hits:
        d = by_src.setdefault(h["source_id"], {"source_id": h["source_id"], "chunk_score": 0.0, "chunks": [], "title": h["title"], "channel": h.get("channel"),
                                                "platform": h.get("platform"), "url": h.get("url"), "published_at": h.get("published_at")})
        d["chunk_score"] += h["score"]
        d["chunks"].append({"chunk_id": h["chunk_id"], "timestamp": h["timestamp"], "link": h["link"], "text": h["text"][:280], "score": h["score"]})
    out = []
    profile_s = 0.0
    for sid, d in by_src.items():
        if d["chunk_score"] < MIN_SCORE:
            rejected["low_score"] += 1
            continue
        _t0 = time.perf_counter()
        p = profile(sid) or {}
        profile_s += time.perf_counter() - _t0
        b = p.get("baseline") or {}
        e = p.get("enriched")
        term_hits = sorted(qt & set(b.get("terms") or []))
        title_hits = sorted(qt & _tokens(str(b.get("title") or "") + " " + str(b.get("creator") or "")))
        passage_terms = _tokens(" ".join(c["text"] for c in d["chunks"]))
        covered = sorted((qt & passage_terms) | set(title_hits))
        coverage = round(len(covered) / len(qt), 2) if qt else 0.0
        # 0.60.2: the same coverage, per PASSAGE. A source that mentions three of the query's words in three
        # unrelated places is not covering the query, and on Kyle's library 44 of the 63 sources that passed did
        # so only that way. The union still decides pass/fail (it is the recall-friendly measure); the best single
        # passage is what `strong` now needs.
        best_passage = 0.0
        for c_ in d["chunks"]:
            ct = _tokens(c_["text"]) | set(title_hits)
            best_passage = max(best_passage, len(qt & ct) / len(qt) if qt else 0.0)
        d["coverage"], d["covered_terms"], d["query_terms"] = coverage, covered, sorted(qt)
        d["passage_coverage"] = round(best_passage, 2)
        if coverage < MIN_COVERAGE:
            rejected["low_coverage"] += 1
            continue                                                # the nearest thing we own is not the same as coverage
        # The anchor: the query's rarest word has to be in there. Without this, matching the two most generic
        # words of a four-word query is enough, which is how a video about Airbnb income became a "strong" match
        # for enterprise UX work. IDF weighting was measured first and rejected none of them.
        d["anchor_term"] = anchor.get("term")
        d["anchor_mentions"] = mention_counts.get(sid, 0)
        if anchor.get("term") and sid not in anchored:
            rejected["anchor_mentioned_once" if mention_counts.get(sid) else "no_anchor_term"] += 1
            continue
        why: list[str] = [f"{len(d['chunks'])} matching passage(s); best at {d['chunks'][0]['timestamp']}",
                          f"passages cover {len(covered)} of {len(qt)} query terms ({', '.join(covered[:6])})"]
        if anchor.get("term"):
            why.append(f"says \"{anchor['term']}\" {d['anchor_mentions']}× — the most distinctive word in this "
                       f"search that names a subject")
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
    perf.record("recall.profiles", profile_s)
    out.sort(key=lambda x: -x["score"])
    out = out[:limit]
    wanted = 0
    if want_enrichment:
        with perf.timed("recall.want_enrichment"):
            wanted = want([s["source_id"] for s in out if not s["enriched"]], reason or f"library recall: {q[:120]}", project_id)
    try:
        db.kv_bump("library:recalls")
        if out:
            db.kv_bump("library:recall_hits", len(out))
    except Exception:  # noqa: BLE001
        pass
    return {"query": q, "suggestions": out, "scope": len(scope), "anchor": anchor, "rejected": rejected,
            "owned": coverage_of(project_id, anchor.get("term") or (sorted(qt)[0] if qt else None)),
            "note": (f"{rejected['no_anchor_term']} near-miss source(s) were left out because they never say "
                     f"\"{anchor['term']}\"" if anchor.get("term") and rejected["no_anchor_term"] else None),
            "enrichment": {"wanted": wanted, "pending": pending_count()}}


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
