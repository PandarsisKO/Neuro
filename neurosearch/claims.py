"""G5 — Claims and evidence sufficiency (0.29.0).

A Claim is a proposition the project currently believes or questions; it is project research STATE, never library state.
Sources are how knowledge enters; Claims are what the user compares, verifies, rejects and plans around.

The cost policy is the G4 one: everything here that runs automatically costs $0 — candidate Claims are harvested from
findings that already exist, evidence rows point at chunks that already exist, strength/readiness are deterministic
functions of the evidence, and derivative detection is token overlap. The one model contract (`claims.extract`,
schema `claim-set-v1`) NORMALIZES candidates (qualifiers, type, topic, freshness class, merges) and proposes Evidence
Targets; it runs lazily, debounced and in bounded groups (`maybe_extract`), never once per new finding, and is
idempotent by `extraction_hash` (same revision + contract + text → no second spend).

Two sufficiency concepts (Kyle's G5 lock): GOVERNING — does the evidence directly establish what the controlling source
says (one current, authentic, directly applicable primary source can be Strong)? CORROBORATIVE — do enough INDEPENDENT
sources establish that a pattern / interpretation / experience / market condition is reliable (source count without
independence proves nothing)? Strong is not Decision Ready: application to this project is a separate field.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from . import db
from .config import settings

log = logging.getLogger("neurosearch.claims")

PROMPT_VERSION = "claims-1"
TYPES = ("governing", "historical", "expert_interpretation", "practice", "experiential", "market", "causal", "novel_tactic", "other")
GOVERNING_TYPES = {"governing", "historical"}
RELATIONS = ("SUPPORTS", "CONTRADICTS", "QUALIFIES", "INTERPRETS", "EXPERIENTIAL")
# G5.1 (0.30.0) — freshness belongs to the CLAIM, not to the age of the video it came from. A 2021 interview can carry a
# stale rate, a still-current transition insight, a timeless anecdote and a rule that needs re-verification at once.
# Each class = (days until NEEDS_REFRESH, days until STALE or None = never stale by age alone, note). Uncertain
# classification never produces a stale verdict — it produces `uncertain`.
FRESHNESS = ("regulatory", "rates_pricing", "promotional", "underwriting_practice", "tactics", "operational", "experiential", "historical", "static", "uncertain")
FRESHNESS_RULES: dict[str, tuple[int | None, int | None, str]] = {
    "regulatory":           (365, None, "verify the current version, amendment or effective date"),
    "rates_pricing":        (180, 540, "rates, fees, terms, multiples and prices move within months"),
    "promotional":          (60, 120, "offers and deadlines expire"),
    "underwriting_practice": (365, 730, "lender practice drifts over 12–24 months"),
    "tactics":              (6 * 365, None, "acquisition structures and tactics hold for years; newer corroboration preferred"),
    "operational":          (7 * 365, None, "operational practice holds unless technology or regulation changed"),
    "experiential":         (None, None, "human behaviour and transition lessons rarely stale by age; check applicability"),
    "historical":           (None, None, "a firsthand account never stales; flag applicability instead"),
    "static":               (None, None, "timeless framework, strategy or negotiation insight; stales only when contradicted"),
    "uncertain":            (3 * 365, None, "the $0 heuristic could not classify this — treat freshness as uncertain, not stale"),
}
_LEGACY_FRESHNESS = {"slow_changing": "tactics", "periodic": "regulatory", "fast_changing": "rates_pricing"}   # 0.29.x values
FRESHNESS_STATUS = ("current", "needs_refresh", "stale", "uncertain", "age_insensitive")
# corroborative sufficiency: independent supporting sources needed for each strength band
CORROBORATION = {"strong": 3, "developing": 2, "weak": 1}
STRENGTHS = ("strong", "developing", "weak", "unsupported")

CLAIMS_BATCH_MIN = 6          # unnormalized candidates that justify an extraction call on their own
CLAIMS_DEBOUNCE_S = 1800      # otherwise wait this long since the last extraction before spending again
EXTRACT_GROUP = 8             # candidates per model call (20 truncated a 4k output on the real library, 0.30.1)
EXTRACT_MAX_INLINE = 60       # more than this → job only

_STOP = {"the", "and", "that", "with", "this", "from", "your", "have", "will", "they", "their", "there", "which", "when", "what",
         "about", "into", "than", "then", "them", "been", "were", "also", "more", "most", "some", "such", "only", "over", "under",
         "should", "would", "could", "because", "before", "after", "these", "those", "other", "each", "very", "much", "many"}


# ---------------------------------------------------------------- deterministic helpers ($0)

from functools import lru_cache


@lru_cache(maxsize=50000)
def _tokens_cached(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z][a-z0-9\-']{3,}", text.lower()) if w not in _STOP)


def _tokens(text: str) -> frozenset[str]:
    return _tokens_cached((text or "")[:2000])


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / max(1, len(ta | tb))


def overlap(a: str, b: str) -> float:
    """Share of the shorter passage's distinctive tokens present in the other: 1.0 = one repeats the other."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(short & long_) / len(short)


DERIVATIVE_OVERLAP = 0.6
INDEPENDENCE_WINDOW = 24      # evidence rows compared for independence (sufficiency saturates long before)
SAME_CLAIM_OVERLAP = 0.6      # a harvested finding this close to an existing Claim is evidence for it, not a new Claim


def guess_type(text: str, evidence_class: str | None) -> str:
    """Pre-normalization guess from cue words + the evidence class of the first supporting source. The extraction
    contract refines it; this only exists so G5 is useful with zero model calls."""
    t = (text or "").lower()
    if re.search(r"\b(sop|statute|regulation|rule|code|section|§|requires?|must|shall|prohibit|eligib|permit(s|ted)?)\b", t) and evidence_class in ("authoritative", "historical"):
        return "governing"
    if re.search(r"\b(costs?|price|priced|fee|fees|rate|rates|\$\d|multiple|multiples|valuation)\b", t):
        return "market"
    if re.search(r"\b(because|causes?|leads? to|results? in|drives|due to)\b", t):
        return "causal"
    if re.search(r"\b(owners?|buyers?|sellers?|operators?|people|clients) (often|commonly|usually|typically|report|experience|find)\b", t) or evidence_class == "experiential":
        return "experiential"
    if re.search(r"\b(most|many|typically|usually|commonly|standard practice|in practice|lenders|brokers|industry)\b", t):
        return "practice"
    if re.search(r"\b(trick|tactic|hack|unconventional|contrarian|nobody|rarely|instead of)\b", t):
        return "novel_tactic"
    if evidence_class == "authoritative":
        return "governing"
    if evidence_class == "expert":
        return "expert_interpretation"
    return "other"


def guess_freshness(text: str, claim_type: str, evidence_class: str | None = None) -> str:
    """$0 Claim-relative freshness class from Claim semantics + temporal language + evidence class + governing domain.
    Errs toward `uncertain` (never a false stale) when the cues do not agree."""
    t = (text or "").lower()
    if re.search(r"\b(promotion|promo|offer|deadline|expires?|expiration|limited time)\b", t):
        return "promotional"
    if re.search(r"\b(interest rates?|prime rate|guarantee fees?|fee schedule|pricing|price list|listing price|asking price|cap rate)\b", t) \
            or (re.search(r"\b(multiples?|valuation)\b", t) and re.search(r"\d", t)) \
            or (re.search(r"\b(per cent|percent)\b|%|\$[\d,]+", t) and re.search(r"\b(rates?|fees?|prices?|costs?|multiples?|interest|premiums?|salary|salaries)\b", t)):
        return "rates_pricing"                                  # a figure about money over time — not every "10% down" structure point
    if re.search(r"\b(sop|statute|regulation|regulations|regulatory|tax code|irs|irc|§|section \d|eligib|prohibit|shall|federal|state law|licens)\b", t) or claim_type == "governing":
        return "regulatory"
    if re.search(r"\b(lenders?|banks?|underwrit\w*|credit box|loan officer)\b", t) and re.search(r"\b(require|requires|want|wants|prefer|look for|expect|typically|usually|will|won't|approve)\b", t):
        return "underwriting_practice"
    if claim_type == "historical" or re.search(r"\b(in (19|20)\d\d|back then|at the time|when (i|we) (bought|sold|started))\b", t):
        return "historical"
    if re.search(r"\b(framework|principle|mindset|negotiat\w*|strategy|strategic|philosophy|rule of thumb|always|never)\b", t):
        return "static"
    if claim_type == "experiential" or evidence_class == "experiential" and re.search(r"\b(seller|owner|client|employee|customer|staff|transition|retention|relationship|trust|culture|people)\b", t):
        return "experiential"
    if re.search(r"\b(software|technology|tool|tools|process|checklist|system|systems|workflow|automation)\b", t):
        return "operational"
    if claim_type in ("practice", "novel_tactic", "causal") or re.search(r"\b(structure|structuring|earnout|seller note|standby|loi|deal|acquisition|acquire|buyout|due diligence|diligence)\b", t):
        return "tactics"
    return "uncertain"


def freshness_status(freshness_class: str, newest_evidence_age_days: float | None) -> tuple[str, str]:
    """(status, why) for a Claim given its class and the age of its newest supporting evidence."""
    cls = _LEGACY_FRESHNESS.get(freshness_class, freshness_class)
    refresh, stale, note = FRESHNESS_RULES.get(cls, FRESHNESS_RULES["uncertain"])
    if newest_evidence_age_days is None:
        return ("uncertain", "no dated evidence; freshness cannot be judged") if cls not in ("static", "historical", "experiential") else ("age_insensitive", note)
    age = int(newest_evidence_age_days)
    if refresh is None and stale is None:
        return "age_insensitive", note
    if stale is not None and age > stale:
        return "stale", f"newest supporting evidence is {age} days old; {note} (stale after {stale} days)"
    if refresh is not None and age > refresh:
        if cls == "uncertain":
            return "uncertain", f"newest supporting evidence is {age} days old and the Claim's freshness class is uncertain — re-verify rather than assume"
        return "needs_refresh", f"newest supporting evidence is {age} days old; {note} (re-verify after {refresh} days)"
    return "current", f"newest supporting evidence is {age} days old, within the {cls.replace('_', ' ')} horizon"


def evidence_class_for(src: dict[str, Any]) -> str:
    """Project-neutral class of a source, from its enriched profile when one exists, else from deterministic signals."""
    try:
        from . import library
        prof = library.profile(src["id"]) if src else None
        enr = (prof or {}).get("enriched") or {}
        if enr.get("evidence_class") in ("authoritative", "expert", "experiential", "market", "historical"):
            return str(enr["evidence_class"])
        sig = {s["signal"]: s["value"] for s in library.authority_signals(src)}
    except Exception:  # noqa: BLE001
        sig = {}
    if sig.get("domain") == "government" or sig.get("document_kind") == "official-style document":
        return "authoritative"
    if sig.get("domain") == "education":
        return "expert"
    if (src.get("platform") or "") in ("youtube", "instagram", "podcast", "media", "community") or sig.get("text_origin") in ("captions", "transcribed", "community"):
        return "experiential"
    if (src.get("platform") or "") in ("document", "web"):
        return "expert"
    return "expert"


def _published_ts(src: dict[str, Any]) -> float | None:
    p = src.get("published_at")
    if not p:
        return None
    try:
        return datetime.fromisoformat(str(p)[:10]).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _topic_of(text: str, vocab: dict[str, int] | None = None) -> str:
    """$0 node key until the contract names the topic. With a project vocabulary (token → number of findings using it)
    the topic is the claim's most SHARED content word, so nodes aggregate around the project's own vocabulary instead
    of one node per finding; without one, the first two content words."""
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower()) if w not in _STOP]
    if vocab:
        ranked = sorted({w for w in words if vocab.get(w, 0) >= 2}, key=lambda w: (-vocab[w], w))
        if ranked:
            return ranked[0]
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
        if len(seen) == 2:
            break
    return " ".join(seen) or "general"


def project_vocab(project_id: str) -> dict[str, int]:
    """Document frequency of content words over the project's findings (cheap; recomputed per harvest)."""
    df: dict[str, int] = {}
    for n in db.list_project_notes(project_id, status=None):
        for w in _tokens(_strip_cites(n.get("content") or "")):
            df[w] = df.get(w, 0) + 1
    return df


# ---------------------------------------------------------------- rows

def _claim(row: Any) -> dict[str, Any]:
    d = dict(row)
    if d.get("freshness_class") in _LEGACY_FRESHNESS:
        d["freshness_class"] = _LEGACY_FRESHNESS[d["freshness_class"]]
    for k in ("qualifiers", "routing"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def get(claim_id: str) -> dict[str, Any] | None:
    row = db.connect().execute("SELECT * FROM project_claims WHERE id=?", (claim_id,)).fetchone()
    if not row:
        return None
    c = _claim(row)
    c["evidence"] = evidence_for(claim_id)
    return c


_EV_SQL = "SELECT e.*, s.title, s.platform, s.published_at, s.channel FROM claim_evidence e JOIN sources s ON s.id=e.source_id "


def evidence_for(claim_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    rows = db.connect().execute(_EV_SQL + "WHERE e.claim_id=? ORDER BY e.created_at" + (f" LIMIT {int(limit)}" if limit else ""), (claim_id,)).fetchall()
    return [dict(r) for r in rows]


def evidence_map(project_id: str) -> dict[str, list[dict[str, Any]]]:
    """All evidence of a project's Claims in ONE query (the map/state paths must not do N+1 over thousands of Claims)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for r in db.connect().execute(_EV_SQL + "JOIN project_claims c ON c.id=e.claim_id WHERE c.project_id=? ORDER BY e.created_at", (project_id,)).fetchall():
        out.setdefault(r["claim_id"], []).append(dict(r))
    return out


def list_for_project(project_id: str, status: str | None = None, with_evidence: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM project_claims WHERE project_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at"
    rows = db.connect().execute(q, (project_id, status) if status else (project_id,)).fetchall()
    out = [_claim(r) for r in rows]
    if with_evidence:
        em = evidence_map(project_id)
        for c in out:
            c["evidence"] = em.get(c["id"], [])
    return out


def add_claim(project_id: str, text: str, *, claim_type: str = "other", qualifiers: dict[str, Any] | None = None, topic: str | None = None,
              freshness_class: str | None = None, origin: str = "user", origin_note_id: int | None = None, status: str = "proposed",
              normalized: bool = False, provenance: dict[str, Any] | None = None, vocab: dict[str, int] | None = None) -> dict[str, Any]:
    if claim_type not in TYPES:
        claim_type = "other"
    t = time.time()
    cid = db.new_id()
    prov = provenance or {}
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, claim_type, qualifiers, topic, freshness_class, status, normalized, origin, origin_note_id, "
                     "extraction_hash, model, prompt_version, schema_version, routing, transport, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, project_id, text.strip(), claim_type, json.dumps(qualifiers or {}), topic or _topic_of(text, vocab),
                      freshness_class or guess_freshness(text, claim_type), status, 1 if normalized else 0, origin, origin_note_id,
                      prov.get("extraction_hash"), prov.get("model"), prov.get("prompt_version"), prov.get("schema_version"),
                      prov.get("routing"), prov.get("transport"), t, t))
    return get(cid)  # type: ignore[return-value]


def _creator_of(src: dict[str, Any], locator: str | None) -> str | None:
    if (src.get("platform") or "") == "community":
        m = re.search(r"(\d+)", locator or "")
        if m:
            r = db.connect().execute("SELECT author FROM community_posts WHERE source_id=? AND ordinal=?", (src.get("id"), int(m.group(1)))).fetchone()
            return (r["author"] or "").lower() or None if r else None
        return None
    return (src.get("channel") or "").lower() or None


def _firsthand(src: dict[str, Any], locator: str | None) -> bool:
    if (src.get("platform") or "") != "community":
        return False
    m = re.search(r"(\d+)", locator or "")
    if not m:
        return False
    r = db.connect().execute("SELECT firsthand FROM community_posts WHERE source_id=? AND ordinal=?", (src.get("id"), int(m.group(1)))).fetchone()
    return bool(r and r["firsthand"])


def add_evidence(claim_id: str, source_id: str, *, locator: str | None = None, start: float | None = None, link: str | None = None,
                 relation: str = "SUPPORTS", excerpt: str | None = None, task: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Freeze the exact revision + locator. Independence against the Claim's existing evidence is decided here ($0)."""
    if relation not in RELATIONS:
        relation = "SUPPORTS"
    from . import works
    src = db.get_source(source_id) or {"id": source_id}
    rev = src.get("revision") or db.source_revision(source_id)
    cls = evidence_class_for(src)
    lin = works.lineage_of(source_id)
    lineage_id = (lin or {}).get("work_id")
    if (src.get("platform") or "") == "community":
        m0 = re.search(r"(\d+)", locator or "")
        pr = db.connect().execute("SELECT permalink FROM community_posts WHERE source_id=? AND ordinal=?", (source_id, int(m0.group(1)))).fetchone() if m0 else None
        if pr and pr["permalink"]:
            link = pr["permalink"]                                        # the comment's own permalink, not the thread
    if not lineage_id and (src.get("platform") or "") == "community":
        # G7: posts that lean on the same external reference are REPEATED INFORMATION, not independent experience
        m = re.search(r"(\d+)", locator or "")
        row = db.connect().execute("SELECT evidence_links, firsthand FROM community_posts WHERE source_id=? AND ordinal=?", (source_id, int(m.group(1)))).fetchone() if m else None
        if row and row["evidence_links"] and not row["firsthand"]:
            try:
                links = json.loads(row["evidence_links"])
            except ValueError:
                links = []
            if links:
                lineage_id = "url:" + re.sub(r"^https?://(www\.)?", "", links[0]).rstrip("/").lower()
    independent, derivative_of = 1, None
    # beyond this window nothing changes sufficiency; two posts of one community thread are two pieces of evidence, so only
    # the identical locator is excluded (for other platforms a second row from the same source is the same source)
    existing = [e for e in evidence_for(claim_id, limit=INDEPENDENCE_WINDOW)
                if e["source_id"] != source_id or ((src.get("platform") or "") == "community" and (e.get("locator") or "") != (locator or ""))]
    # pass 1 — G6 lineage: one Work = one evidentiary lineage (official PDF + mirror + excerpt + quote = 1), whatever the source count
    promote_over: list[int] = []
    if lineage_id:
        same = [e for e in existing if e.get("lineage_id") == lineage_id]
        if same:
            rep = next((e for e in same if e.get("independent")), same[0])
            rep_lin = works.lineage_of(rep["source_id"]) or {}
            rep_primary = rep_lin.get("relation") in works.PRIMARY_RELATIONS
            new_primary = (lin or {}).get("relation") in works.PRIMARY_RELATIONS
            # the lineage's representative is its best primary manifestation: primary beats derivative/quote, official beats mirror
            if new_primary and (not rep_primary or ((lin or {}).get("form") == "official" and rep_lin.get("form") != "official")):
                promote_over = [e["id"] for e in same]
            else:
                independent, derivative_of = 0, rep["source_id"]
    # pass 2 — wording/creator heuristics, only where lineage says nothing: a source that belongs to a Work's lineage is
    # judged by that lineage alone (the first arrival of a Work is a new line of evidence, whatever its wording).
    # G7: for community threads the creator is the POST's author, never the community (two owners in one subreddit are two people)
    my_creator = _creator_of(src, locator)
    my_firsthand = _firsthand(src, locator)
    if independent and not lineage_id:
        for e in existing:
            same_creator = bool(my_creator) and my_creator == _creator_of({"platform": e.get("platform"), "channel": e.get("channel"), "id": e["source_id"]}, e.get("locator"))
            if my_firsthand and not same_creator:
                continue                                                   # another person's own experience is another line, however similar the words
            if excerpt and e.get("excerpt") and overlap(excerpt, e["excerpt"]) >= DERIVATIVE_OVERLAP:
                independent, derivative_of = 0, e["source_id"]
                break
            if same_creator:
                independent, derivative_of = 0, e["source_id"]
    if derivative_of and cls != "authoritative":
        cls = "derivative"
    t = time.time()
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO claim_evidence (claim_id, source_id, source_revision, locator, start, link, relation, excerpt, evidence_class, independent, "
                           "derivative_of, task, model, created_at, lineage_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (claim_id, source_id, rev, locator, start, link, relation, (excerpt or "")[:600], cls, independent, derivative_of, task, model, t, lineage_id))
        conn.execute("UPDATE project_claims SET updated_at=? WHERE id=?", (t, claim_id))
        eid = cur.lastrowid
        for old_id in promote_over:
            conn.execute("UPDATE claim_evidence SET independent=0, derivative_of=?, evidence_class=CASE WHEN evidence_class='authoritative' THEN evidence_class ELSE 'derivative' END WHERE id=?", (source_id, old_id))
    return dict(db.connect().execute("SELECT * FROM claim_evidence WHERE id=?", (eid,)).fetchone())


def set_status(claim_id: str, status: str, *, application: str | None = None) -> dict[str, Any] | None:
    """User/system state. Accepting is the user's act; the model never calls this."""
    if status not in ("proposed", "accepted", "rejected", "superseded"):
        raise ValueError("bad status")
    with db.tx() as conn:
        conn.execute("UPDATE project_claims SET status=?, application=COALESCE(?, application), updated_at=? WHERE id=?", (status, application, time.time(), claim_id))
    assess(claim_id)
    return get(claim_id)


# ---------------------------------------------------------------- harvest ($0 candidates)

class TwinIndex:
    """Inverted token index over Claim texts so the twin search is O(shared tokens), not O(claims) per finding."""

    def __init__(self, claims_: list[dict[str, Any]]):
        self.items: list[tuple[str, frozenset[str], dict[str, Any]]] = []
        self.post: dict[str, list[int]] = {}
        for c in claims_:
            self.add(c)

    def add(self, c: dict[str, Any]) -> None:
        toks = _tokens(c["text"])
        i = len(self.items)
        self.items.append((c["id"], toks, c))
        for t in toks:
            self.post.setdefault(t, []).append(i)

    def twin(self, text: str, threshold: float = SAME_CLAIM_OVERLAP, exclude_id: str | None = None, symmetric: bool = False) -> dict[str, Any] | None:
        toks = _tokens(text)
        if not toks:
            return None
        counts: dict[int, int] = {}
        for t in toks:
            for i in self.post.get(t, ()):
                counts[i] = counts.get(i, 0) + 1
        best, best_score = None, 0.0
        for i, shared in counts.items():
            cid, other, c = self.items[i]
            if cid == exclude_id:
                continue
            score = shared / max(1, len(toks | other)) if symmetric else shared / max(1, min(len(toks), len(other)))
            if score >= threshold and score > best_score:
                best, best_score = c, score
        return best

def _strip_cites(text: str) -> str:
    return re.sub(r"\s*\[\d{1,2}\]", "", text or "").strip()


def harvest(project_id: str) -> dict[str, Any]:
    """Zero-cost candidate Claims from findings that already exist (approved → proposed candidate; suggested → candidate
    for investigation, origin 'finding_suggested'). Idempotent per note. Never touches the model."""
    created, merged = 0, 0
    have = {r["origin_note_id"] for r in db.connect().execute("SELECT origin_note_id FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL", (project_id,))}
    have |= {r["note_id"] for r in db.connect().execute("SELECT note_id FROM claim_evidence_notes")}
    existing = [c for c in list_for_project(project_id, with_evidence=False) if c["status"] != "rejected"]
    index = TwinIndex(existing)
    touched: set[str] = set()
    vocab = project_vocab(project_id)
    with db.batch():                                   # one write transaction for the whole harvest
      for status in ("approved", "suggested"):
        for n in db.list_project_notes(project_id, status=status):
            if n["id"] in have:
                continue
            body = _strip_cites(n.get("content") or "")
            title = (n.get("title") or "").strip()
            text = f"{title} — {body}" if title and title.lower() not in body.lower() else body
            if len(text) < 20 or text.lower().startswith("gap:"):
                continue
            cites = n.get("citations") or []
            if isinstance(cites, str):
                try:
                    cites = json.loads(cites)
                except ValueError:
                    cites = []
            first = cites[0] if cites else None
            src = db.get_source(first["source_id"]) if first and first.get("source_id") else None
            cls = evidence_class_for(src) if src else None
            # the same proposition from another source is EVIDENCE for the existing Claim, not a second Claim —
            # independence is decided in add_evidence (a repeated passage counts as derivative)
            twin = index.twin(text)
            if twin:
                for cite in cites[:4]:
                    if cite.get("source_id") and db.get_source(cite["source_id"]):
                        add_evidence(twin["id"], cite["source_id"], locator=cite.get("timestamp"), start=cite.get("start"), link=cite.get("link"),
                                     relation="SUPPORTS", excerpt=cite.get("snippet"), task="findings.extract", model=n.get("model"))
                with db.tx() as conn:
                    conn.execute("INSERT OR IGNORE INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (twin["id"], n["id"]))
                touched.add(twin["id"])
                merged += 1
                continue
            ctype = guess_type(body, cls)
            c = add_claim(project_id, text, claim_type=ctype, freshness_class=guess_freshness(body, ctype, cls), origin="finding" if status == "approved" else "finding_suggested",
                          origin_note_id=n["id"], status="proposed", normalized=False, vocab=vocab)
            existing.append(c)
            for cite in cites[:4]:
                if cite.get("source_id") and db.get_source(cite["source_id"]):
                    add_evidence(c["id"], cite["source_id"], locator=cite.get("timestamp"), start=cite.get("start"), link=cite.get("link"),
                                 relation="SUPPORTS", excerpt=cite.get("snippet"), task="findings.extract", model=n.get("model"))
            touched.add(c["id"])
            index.add(c)
            created += 1
            try:                                                           # G6: a finding that names a Work → stub → candidate → target ($0)
                from . import works as _works
                _works.cite(project_id, body, source_id=(first or {}).get("source_id"), claim_id=c["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("work citation skipped: %s", e)
    # $0 topics and freshness follow the project's vocabulary / the Claim's own semantics (normalized Claims keep what the contract named)
    _first_class = {r["claim_id"]: r["evidence_class"] for r in db.connect().execute(
        "SELECT claim_id, evidence_class FROM claim_evidence WHERE claim_id IN (SELECT id FROM project_claims WHERE project_id=? AND normalized=0) GROUP BY claim_id", (project_id,))}
    with db.batch():
        for c in existing:
            if not c.get("normalized"):
                t = _topic_of(c["text"], vocab)
                f = guess_freshness(c["text"].split(" — ", 1)[-1], c["claim_type"], _first_class.get(c["id"]))
                if t != c.get("topic") or f != c.get("freshness_class"):
                    db.connect().execute("UPDATE project_claims SET topic=?, freshness_class=? WHERE id=? AND normalized=0", (t, f, c["id"]))
                    touched.add(c["id"])
    for cid in touched:                                    # assess once per touched Claim, not once per finding
        assess(cid)
    return {"created": created, "merged": merged}


# ---------------------------------------------------------------- assessment ($0, deterministic, explained)

def _primary_gap(evidence: list[dict[str, Any]], works_mod: Any) -> str | None:
    """G6 stricter governing sufficiency: if the evidence only reaches the governing Work through excerpts / quotes /
    summaries / derivatives while a primary manifestation is obtainable (owned elsewhere, a candidate, or a resolved
    identity), say so — Chat can then say 'supported by secondary sources, but the primary source is not yet resolved'."""
    for e in evidence:
        lin = works_mod.lineage_of(e["source_id"])
        if not lin:
            continue
        if lin["relation"] in works_mod.PRIMARY_RELATIONS:
            return None                                                    # a primary manifestation is in the evidence
    # no primary in the evidence: is one obtainable for any cited Work?
    for e in evidence:
        for m in db.connect().execute("SELECT work_id, relation FROM work_manifestations WHERE source_id=?", (e["source_id"],)).fetchall():
            w = works_mod.get(m["work_id"])
            if not w:
                continue
            prim = works_mod.primary_manifestations(w["id"])
            owned = [x for x in prim if x.get("access") == "owned"]
            if owned:
                return f"the governing primary source ({w['title']}) is owned but not the evidence here — resolve it into the project rather than relying on a {m['relation'].replace('_', ' ')}"
            if prim or w.get("resolution") == "resolved":
                return f"the governing primary source ({w['title']}) has not yet been resolved into the project — this Claim rests on a {m['relation'].replace('_', ' ')}"
    return None


def assess(claim_id: str) -> dict[str, Any] | None:
    """Strength from the evidence REQUIREMENT of the Claim type, not the source count; freshness from the domain class;
    readiness separate from strength. Writes strength/strength_why/readiness/readiness_why; returns the claim."""
    c = get(claim_id)
    if not c:
        return None
    ev = c["evidence"]
    now = time.time()
    srcs: dict[str, dict[str, Any]] = {}
    for e in ev:
        if e["source_id"] not in srcs:
            srcs[e["source_id"]] = db.get_source(e["source_id"]) or {}
    # refresh stale flags against the live revision (one lookup per source)
    live_rev = {sid: (srcs[sid].get("revision") or db.source_revision(sid)) for sid in srcs}
    for e in ev:
        live = live_rev.get(e["source_id"])
        stale = 1 if (e.get("source_revision") and live and live != e["source_revision"]) else 0
        if stale != e.get("stale", 0):
            with db.tx() as conn:
                conn.execute("UPDATE claim_evidence SET stale=? WHERE id=?", (stale, e["id"]))
            e["stale"] = stale
    live_ev = [e for e in ev if not e.get("stale")]
    sup = [e for e in live_ev if e["relation"] in ("SUPPORTS", "EXPERIENTIAL")]
    con = [e for e in live_ev if e["relation"] == "CONTRADICTS"]
    auth = [e for e in sup if e.get("evidence_class") in ("authoritative", "historical")]
    indep_sources = {e["source_id"] for e in sup if e.get("independent")}
    derivative = [e for e in sup if not e.get("independent")]
    why: list[str] = []
    ctype = c["claim_type"]
    # $0 re-typing for unnormalized Claims: once an authoritative PRIMARY manifestation supports it, a rule-shaped Claim is governing
    if not c.get("normalized") and auth and ctype not in GOVERNING_TYPES:
        from . import works as _w
        if any((_w.lineage_of(a["source_id"]) or {}).get("relation") in _w.PRIMARY_RELATIONS for a in auth):
            better = guess_type(c["text"].split(" — ", 1)[-1], "authoritative")
            if better in GOVERNING_TYPES:
                ctype = better
                with db.tx() as conn:
                    conn.execute("UPDATE project_claims SET claim_type=?, freshness_class=? WHERE id=? AND normalized=0", (ctype, guess_freshness(c["text"].split(" — ", 1)[-1], ctype, "authoritative"), claim_id))
    if not sup:
        strength = "unsupported"
        why.append("no supporting evidence" + (f"; {len(ev) - len(live_ev)} evidence row(s) stale after a source revision" if len(ev) != len(live_ev) else ""))
    elif ctype in GOVERNING_TYPES:
        if auth:
            a = auth[0]
            strength = "strong"
            why.append(f"governing sufficiency: 1 {a['evidence_class']} source directly states it ({a.get('title')}, {a.get('locator') or 'n/a'})")
            if len(sup) > 1:
                why.append(f"{len(sup) - 1} further source(s) repeat or interpret it — not needed to establish the rule")
            # G6: a derivative that accurately quotes the rule does not fully verify it while an obtainable primary manifestation exists
            from . import works as _works
            prim = _primary_gap(auth, _works)
            if prim:
                strength = "developing"
                why.append(prim)
        else:
            strength = "developing" if len(indep_sources) >= 2 else "weak"
            if all(e.get("evidence_class") in ("experiential", "derivative") for e in sup):
                strength = "weak"
                why.append(f"insufficient authority: {len(sup)} community/experiential source(s) cannot establish what a rule says, however many agree — find the governing primary source")
            else:
                why.append(f"governing Claim without a primary source: {len(sup)} secondary source(s), {len(indep_sources)} independent — the controlling text itself is missing")
            from . import works as _works
            prim = _primary_gap(sup, _works)
            if prim:
                why.append(prim)
    else:
        n = len(indep_sources)
        if ctype == "market" and (c.get("qualifiers") or {}).get("specific_instance"):
            strength = "strong" if n >= 1 else "unsupported"
            why.append("narrow market Claim about one specific quote/listing: the listing itself is sufficient")
        else:
            strength = "strong" if n >= CORROBORATION["strong"] else "developing" if n >= CORROBORATION["developing"] else "weak"
            why.append(f"corroborative sufficiency: {n} independent supporting source(s) of {len(sup)} (needs {CORROBORATION['strong']} for strong)")
            if derivative:
                names = sorted({e.get("title") or e["source_id"] for e in derivative})
                why.append(f"{len(derivative)} source(s) repeat another source's passage and do not count as corroboration: " + "; ".join(str(x)[:40] for x in names[:3]))
            if ctype in ("novel_tactic", "causal") and strength == "strong" and n < CORROBORATION["strong"] + 1:
                strength = "developing"
                why.append(f"{ctype.replace('_', ' ')} Claims need stronger corroboration")
        from . import works as _works
        prim = _primary_gap(sup, _works)
        if prim:
            why.append(prim)                                              # G6: the Work behind a quote/summary is obtainable — say so
    if sup and len(ev) != len(live_ev):
        why.append(f"{len(ev) - len(live_ev)} evidence row(s) stale: the source was revised since they were frozen — re-verify against the new revision")
    if con:
        indep_con = {e["source_id"] for e in con if e.get("independent")}
        why.append(f"{len(con)} contradicting source(s) ({len(indep_con)} independent) — unresolved")
        if strength == "strong" and (ctype not in GOVERNING_TYPES or any(e.get("evidence_class") == "authoritative" for e in con)):
            strength = "developing"
    # Claim-relative freshness (G5.1): a separate verdict, never folded into evidence strength
    ages = []
    for e in sup:
        src = srcs.get(e["source_id"]) or {}
        ts = _published_ts(src)
        if ts:
            ages.append((now - float(ts)) / 86400)
    fstatus, fwhy = freshness_status(c.get("freshness_class") or "uncertain", min(ages) if ages else None) if sup else ("uncertain", "no supporting evidence")
    # G6: version relationship, never "a newer copy exists": unknown/supersedes → needs_refresh; material change → stale;
    # rehost/formatting → nothing; a historical Claim about the old version → untouched
    if sup and (c.get("freshness_class") or "") != "historical":
        from . import works as _works
        for e in sup:
            vf = _works.version_freshness(e["source_id"])
            if not vf or vf["relation"] in ("none", "rehost"):
                continue
            if vf["relation"] == "material" and fstatus != "stale":
                fstatus, fwhy = "stale", f"{vf['newest']} changed the relevant provisions of the version this evidence cites ({vf.get('change_note') or 'see version notes'})"
            elif vf["relation"] in ("unknown", "supersedes") and fstatus != "stale":
                fstatus, fwhy = "needs_refresh", f"a newer version ({vf['newest']}) {'supersedes' if vf['relation'] == 'supersedes' else 'exists; differences unknown for'} the version this evidence cites — re-verify against it"
    if fstatus in ("stale", "needs_refresh", "uncertain") and sup:
        why.append(fwhy)
    # readiness is NOT strength
    app = c.get("application") or "unknown"
    if strength == "strong" and app == "established":
        readiness, rwhy = "ready", "evidence is strong and its application to this project is established"
    elif strength == "strong":
        readiness, rwhy = "not_ready", "evidence is strong but whether it applies to this project's situation is " + ("still developing" if app == "developing" else "not established")
    else:
        readiness, rwhy = "not_ready", f"evidence is {strength}"
    if fstatus == "stale" and readiness == "ready":
        readiness, rwhy = "not_ready", "evidence is strong but stale for this Claim's freshness class — re-verify first"
    with db.tx() as conn:
        conn.execute("UPDATE project_claims SET strength=?, strength_why=?, readiness=?, readiness_why=?, freshness_status=?, freshness_why=?, updated_at=? WHERE id=?",
                     (strength, "; ".join(why), readiness, rwhy, fstatus, fwhy, now, claim_id))
    return get(claim_id)


def assess_project(project_id: str) -> int:
    n = 0
    for r in db.connect().execute("SELECT id FROM project_claims WHERE project_id=? AND status!='rejected'", (project_id,)).fetchall():
        assess(r["id"])
        n += 1
    return n


def stale_by_source(source_id: str) -> int:
    """Called when a source's revision changes: re-assess every Claim whose evidence points at it (exact rows go stale)."""
    ids = {r["claim_id"] for r in db.connect().execute("SELECT claim_id FROM claim_evidence WHERE source_id=?", (source_id,))}
    for cid in ids:
        assess(cid)
    return len(ids)


# ---------------------------------------------------------------- contradiction with scope check

SCOPE_KEYS = ("jurisdiction", "product", "population", "conditions", "timeframe")


def scope_conflict(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """Before CONTRADICTS: if the two Claims differ in any scope qualifier, it is a QUALIFIES relationship, not a conflict."""
    qa_, qb = a.get("qualifiers") or {}, b.get("qualifiers") or {}
    for k in SCOPE_KEYS:
        if qa_.get(k) and qb.get(k) and str(qa_[k]).strip().lower() != str(qb[k]).strip().lower():
            return k
    ca = {e.get("evidence_class") for e in a.get("evidence", [])}
    cb = {e.get("evidence_class") for e in b.get("evidence", [])}
    if ("authoritative" in ca) != ("authoritative" in cb) and ({"experiential"} & (ca | cb)):
        return "primary rule vs practical experience"
    return None


def relate(claim_id: str, related_id: str, relation: str) -> dict[str, Any]:
    """Link two Claims through evidence: the related Claim's supporting passages become CONTRADICTS / QUALIFIES evidence
    of the first. A CONTRADICTS request is downgraded to QUALIFIES when scope differs."""
    a, b = get(claim_id), get(related_id)
    if not a or not b:
        raise ValueError("unknown claim")
    downgraded = None
    if relation == "CONTRADICTS":
        downgraded = scope_conflict(a, b)
        if downgraded:
            relation = "QUALIFIES"
    added = 0
    for e in b["evidence"]:
        if e["relation"] in ("SUPPORTS", "EXPERIENTIAL"):
            add_evidence(claim_id, e["source_id"], locator=e.get("locator"), start=e.get("start"), link=e.get("link"), relation=relation,
                         excerpt=e.get("excerpt"), task="claims.relate")
            added += 1
    assess(claim_id)
    from . import knowledge
    knowledge.detect(a["project_id"])
    return {"relation": relation, "scope_difference": downgraded, "evidence_added": added}


# ---------------------------------------------------------------- normalization (the one model contract; lazy, debounced, batched)

SYSTEM = """You are normalising research claims for a project. You receive candidate claims (harvested from findings) with the passages
that support them. For each candidate return ONE normalised claim that keeps every qualifier the evidence carries — jurisdiction,
product or model, population, conditions, timeframe, and the source's own hedging language. Never turn "some lenders may allow X when Y"
into "lenders allow X". Two similar candidates stay separate unless they assert the same proposition with the same scope (then set
merge_into to the id of the one you keep). Classify each claim by the KIND of evidence needed to establish it, not by how many sources
mention it: governing (what a controlling statute/regulation/SOP/contract/manual says), historical (what a person/document said, primary record),
expert_interpretation, practice (what an industry usually does), experiential (what people commonly experience), market (a price/cost/multiple),
causal, novel_tactic (an unconventional tactic), other. Give a freshness_class for the CLAIM (not the source): regulatory (law, SBA SOP, tax — verify
the current version), rates_pricing (rates, fees, terms, multiples, prices), promotional (offers, deadlines), underwriting_practice (what lenders
currently do), tactics (acquisition structures and tactics — years), operational (best practices), experiential (human behaviour, transitions,
retention — age alone rarely matters), historical (a firsthand account — never stale), static (timeless framework or strategy), uncertain.
When a claim states a REQUIREMENT, keep who imposes it in qualifiers.imposed_by — seller/listing preference, legal ownership rule, professional
licensing rule, a rule for performing specific services (e.g. attest/compilation), lender policy, or a state-specific rule — and never collapse
"the seller wants a CPA buyer" into "only CPAs can buy CPA firms". Where the evidence leaves that ambiguous, say so in conditions and propose an
evidence target that decomposes the underlying question by those requirement sources.
Topics are Knowledge Map nodes, not labels: use one of the EXISTING TOPICS you are given whenever the claim belongs there; introduce a new
topic only when none fits, and keep it broad (2–3 words a researcher would use as a chapter heading) — never one topic per claim.
Then, from the project brief and the claims, propose AT MOST three evidence targets the user has not named and that are not already
covered by the EXISTING TARGETS you are given: what a competent researcher would need to establish before deciding, each with a sufficiency
kind (governing = one current directly applicable primary source can close it; corroborative = several independent sources needed),
preferred evidence classes in order, and a one-sentence closure criterion. Return an empty targets list when the existing targets already
cover the ground. You are proposing research state, not deciding it."""


def _candidate_payload(c: dict[str, Any]) -> dict[str, Any]:
    return {"id": c["id"], "text": c["text"], "guessed_type": c["claim_type"],
            "evidence": [{"source": e.get("title"), "class": e.get("evidence_class"), "locator": e.get("locator"), "passage": (e.get("excerpt") or "")[:300]}
                         for e in c.get("evidence", [])[:3]]}


def extraction_hash(project: dict[str, Any], cands: list[dict[str, Any]]) -> str:
    revs = sorted({e.get("source_revision") or "" for c in cands for e in c.get("evidence", [])})
    return hashlib.sha256(json.dumps({"p": PROMPT_VERSION, "s": "claim-set-v1", "brief": (project.get("brief") or "")[:500],
                                      "ids": sorted(c["id"] for c in cands), "texts": [c["text"] for c in cands], "revs": revs}, sort_keys=True).encode()).hexdigest()[:16]


def unnormalized(project_id: str) -> list[dict[str, Any]]:
    return [c for c in list_for_project(project_id) if not c.get("normalized") and c["status"] != "rejected"]


def extract(project_id: str, cands: list[dict[str, Any]] | None = None, transport: str = "interactive") -> dict[str, Any]:
    """Normalize a bounded group of candidates with ONE structured call per EXTRACT_GROUP. Idempotent: a group whose
    extraction_hash is already stamped on its claims is skipped without spend."""
    from . import providers
    project = db.get_project(project_id)
    if not project:
        return {"normalized": 0, "targets": 0, "calls": 0}
    cands = cands if cands is not None else unnormalized(project_id)
    calls, normalized, targets = 0, 0, 0
    for i in range(0, len(cands), EXTRACT_GROUP):
        if transport == "job":
            from .jobs import check_cancel
            check_cancel()                                  # safe boundary: no group's model call is in flight yet
        group = cands[i:i + EXTRACT_GROUP]
        ih = extraction_hash(project, group)
        if all(c.get("extraction_hash") == ih for c in group):
            continue
        from . import knowledge as _kn
        existing_topics = [r["topic"] for r in db.connect().execute(
            "SELECT topic, COUNT(*) n FROM project_claims WHERE project_id=? AND status NOT IN ('rejected','superseded') GROUP BY topic ORDER BY n DESC LIMIT 40", (project_id,))]
        existing_targets = [t["question"][:160] for t in _kn.list_targets(project_id, status="open")[:40]]
        user = json.dumps({"brief": project.get("brief"), "goal": project.get("goal"), "questions": project.get("questions"),
                           "existing_topics": existing_topics, "existing_targets": existing_targets,
                           "candidates": [_candidate_payload(c) for c in group]}, ensure_ascii=False)
        parsed = providers.invoke_structured("claims.extract", system=SYSTEM, messages=[{"role": "user", "content": user}], usage_kind="claims", project_id=project_id)
        calls += 1
        model = getattr(providers.last_response(), "model", None)
        prov = {"extraction_hash": ih, "model": str(model or ""), "prompt_version": PROMPT_VERSION, "schema_version": "claim-set-v1",
                "routing": providers.routing_json("claims.extract", model), "transport": transport}
        by_id = {c["id"]: c for c in group}
        t = time.time()
        with db.tx() as conn:
            for item in parsed.get("claims", []):
                cid = item.get("id")
                if cid not in by_id:
                    continue
                merge = item.get("merge_into")
                if merge and merge in by_id and merge != cid:
                    conn.execute("UPDATE project_claims SET status='superseded', superseded_by=?, normalized=1, extraction_hash=?, updated_at=? WHERE id=? AND status='proposed'", (merge, ih, t, cid))
                    conn.execute("UPDATE claim_evidence SET claim_id=? WHERE claim_id=?", (merge, cid))
                    continue
                ctype = item.get("claim_type") if item.get("claim_type") in TYPES else by_id[cid]["claim_type"]
                fresh = item.get("freshness_class") if item.get("freshness_class") in FRESHNESS else by_id[cid]["freshness_class"]
                conn.execute("UPDATE project_claims SET text=?, claim_type=?, qualifiers=?, topic=?, freshness_class=?, normalized=1, extraction_hash=?, model=?, prompt_version=?, "
                             "schema_version=?, routing=?, transport=?, updated_at=? WHERE id=?",
                             ((item.get("text") or by_id[cid]["text"]).strip(), ctype, json.dumps(item.get("qualifiers") or {}), (item.get("topic") or by_id[cid]["topic"] or "")[:80].lower(),
                              fresh, ih, prov["model"], PROMPT_VERSION, "claim-set-v1", prov["routing"], transport, t, cid))
                normalized += 1
        from . import knowledge
        # requirement provenance → the decomposition target ($0): a requirement the evidence attributes to a seller/listing
        # (or cannot attribute) is not yet known to be a legal, licensing or service-performance rule — open the governing
        # question rather than corroborating the listing
        for item in parsed.get("claims", []):
            q = item.get("qualifiers") or {}
            cid = item.get("id")
            if cid in by_id and q.get("imposed_by") in ("seller_or_listing", "unclear") and re.search(r"\b(must|required?|requires|needs? to|only)\b", (item.get("text") or "").lower()):
                where = q.get("jurisdiction") or "the relevant jurisdiction"
                knowledge.add_target(project_id, f"Is this a legal ownership, professional licensing or service-performance requirement in {where}, or only the seller's/listing's preference: {(item.get('text') or by_id[cid]['text'])[:140]}",
                                     topic=(item.get("topic") or by_id[cid]["topic"]), claim_id=cid, sufficiency="governing",
                                     preferred_classes=["authoritative", "expert"], closure="one current primary source (statute, board rule or licensing regulation) that either imposes the requirement or shows it is not imposed", origin="model", provenance=prov)
        for tgt in parsed.get("targets", [])[:3]:
            if knowledge.add_target(project_id, tgt.get("question") or "", topic=tgt.get("topic"), sufficiency=tgt.get("sufficiency") or "corroborative",
                                    preferred_classes=tgt.get("preferred_classes") or [], closure=tgt.get("closure"), origin="model", provenance=prov):
                targets += 1
    for c in cands:
        assess(c["id"])
    db.kv_set(f"claims:last_extract:{project_id}", str(time.time()))
    return {"normalized": normalized, "targets": targets, "calls": calls}


FAST_GROUPS = 2                   # "a few per batch" (Kyle): at EXTRACT_GROUP=8 that is <=16 claims, cents per pass


def triage(project_id: str) -> dict[str, Any]:
    """$0, deterministic, no model call — which unnormalized candidates deserve to jump the queue.

    Kyle: "I want to surface important claims quickly, but want to offload bulky claim work to background and cheap
    processing", and he chose the two signals: a candidate that ANSWERS AN OPEN QUESTION he is already waiting on,
    or one that comes from a source he marked PRIORITY. Both are his own judgements already recorded in the data,
    which is the point — triage must never be a model guessing what matters before the cheap work can start
    (SPEED-MISSION.md §D: "triage must be free and instant, or it becomes the latency it was meant to remove").

    Everything not picked is returned as `bulk`, never dropped: the fast lane reorders, it does not filter."""
    from . import knowledge
    cands = unnormalized(project_id)
    if not cands:
        return {"fast": [], "bulk": [], "why": {}}
    prio_sources = set(db.priority_source_ids(project_id))
    note_source = {r["id"]: r["source_id"] for r in db.connect().execute(
        "SELECT id, source_id FROM project_notes WHERE project_id=?", (project_id,)).fetchall()}
    open_targets = [t for t in knowledge.list_targets(project_id) if t.get("status") not in ("dropped", "satisfied")]
    target_text = [(t.get("question") or t.get("label") or "") for t in open_targets]

    scored, why = [], {}
    for c in cands:
        reasons, score = [], 0.0
        if note_source.get(c.get("origin_note_id")) in prio_sources:
            score += 1.0; reasons.append("from a source you marked priority")
        best = max((overlap(c["text"], q) for q in target_text), default=0.0)
        if best >= 0.34:
            score += best; reasons.append("answers an open question you are waiting on")
        if reasons:
            scored.append((score, c)); why[c["id"]] = reasons
    scored.sort(key=lambda x: -x[0])
    fast = [c for _, c in scored[:FAST_GROUPS * EXTRACT_GROUP]]
    fast_ids = {c["id"] for c in fast}
    return {"fast": fast, "bulk": [c for c in cands if c["id"] not in fast_ids], "why": why}


def maybe_extract(project_id: str, reason: str, force: bool = False) -> dict[str, Any] | None:
    """Event-driven, debounced, lazy: queue ONE extract_claims job when enough candidates accumulated or the debounce
    window passed — never a call per finding. Returns the job or None."""
    from . import providers
    if not providers.anthropic_available():
        return None
    n = len(unnormalized(project_id))
    if n == 0:
        return None
    last = float(db.kv_get(f"claims:last_extract:{project_id}") or 0)
    if not force and n < CLAIMS_BATCH_MIN and (time.time() - last) < CLAIMS_DEBOUNCE_S:
        return None
    tri = triage(project_id)
    if tri["fast"]:
        # surface what he is waiting on immediately: small, api_requested (paid, ~3x faster than local), priority
        # lane so it is claimed ahead of the bulk pass. Bounded by FAST_GROUPS, so a burst cannot become the cost.
        db.create_job("extract_claims", {"project_id": project_id, "reason": f"{reason} (important)",
                                         "claim_ids": [c["id"] for c in tri["fast"]],
                                         "why": {k: v for k, v in tri["why"].items() if k in {c["id"] for c in tri["fast"]}}},
                      lane="priority", execution_policy="api_requested")
    job = db.create_job("extract_claims", {"project_id": project_id, "reason": reason}, lane="slow")
    return job


def run_job(payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    pid = payload["project_id"]
    if payload.get("evaluation"):
        return run_evaluation(pid, budget=int(payload.get("budget") or EVAL_BUDGET), progress=progress)
    harvest(pid)
    ids = set(payload.get("claim_ids") or [])
    cands = [c for c in unnormalized(pid) if c["id"] in ids] if ids else None
    if ids and not cands:
        return {"normalized": 0, "targets": 0, "calls": 0, "note": "already normalized by an earlier pass"}
    res = extract(pid, cands=cands, transport="job")
    from . import knowledge
    knowledge.refresh(pid)
    return res


# ---------------------------------------------------------------- bounded normalization evaluation (G5.1)
# Normalization must EARN adoption: one durable, bounded pass over decision-relevant Claims + a stratified sample, with
# before/after measurement — never the whole inherited corpus. Long-term policy is lazy and importance-driven.

EVAL_BUDGET = 150
_HEDGE = re.compile(r"\b(may|might|some|sometimes|can|could|often|usually|typically|generally|unless|depends|in some cases|not always)\b")


def select_cohort(project_id: str, budget: int = EVAL_BUDGET) -> dict[str, Any]:
    """Decision-relevant first: strong + developing, NOVEL/CONTRADICTION/WEAK_CONSENSUS tension Claims, Claims behind open or
    pursued targets, important stale/needs-refresh Claims, Claims the current plan's evidence points at; then a stratified
    sample of weak Claims (by topic) up to the budget. Only unnormalized Claims."""
    from . import knowledge
    cands = {c["id"]: c for c in unnormalized(project_id)}
    chosen: dict[str, str] = {}

    def take(ids: list[str], why: str) -> None:
        for i in ids:
            if i in cands and i not in chosen and len(chosen) < budget:
                chosen[i] = why
    take([c["id"] for c in cands.values() if c["strength"] in ("strong", "developing")], "strong/developing")
    take([t["claim_id"] for t in knowledge.list_tensions(project_id, status="open") if t.get("claim_id") and t["kind"] in ("NOVEL", "CONTRADICTION", "WEAK_CONSENSUS")], "tension")
    take([t["claim_id"] for t in knowledge.list_targets(project_id) if t.get("claim_id") and (t["status"] == "open" or t.get("last_escalation"))], "evidence target")
    imp = {r["id"]: int(r["importance"] or 3) for r in db.connect().execute("SELECT id, importance FROM project_notes WHERE project_id=?", (project_id,))}
    take([c["id"] for c in cands.values() if (c.get("freshness_status") in ("stale", "needs_refresh")) and imp.get(c.get("origin_note_id") or -1, 3) >= 4], "important stale")
    plan = db.latest_plan(project_id)
    if plan:
        emap = (plan.get("plan") or {}).get("_evidence") or {}
        labels = [(v.get("source_id"), v.get("label") or "") for v in emap.values()]
        dep = []
        for c in cands.values():
            srcs = {e["source_id"] for e in c["evidence"]}
            if any(sid in srcs and overlap(lbl, c["text"]) >= 0.5 for sid, lbl in labels):
                dep.append(c["id"])
        take(dep, "planner dependency")
    # stratified sample of the rest by topic (round-robin), highest importance first inside a topic
    rest = [c for c in cands.values() if c["id"] not in chosen]
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for c in sorted(rest, key=lambda c: -imp.get(c.get("origin_note_id") or -1, 3)):
        by_topic.setdefault(c.get("topic") or "general", []).append(c)
    while len(chosen) < budget and any(by_topic.values()):
        for t in sorted(by_topic):
            if by_topic[t] and len(chosen) < budget:
                chosen[by_topic[t].pop(0)["id"]] = "stratified sample"
    return {"claim_ids": list(chosen), "reasons": chosen, "candidates": len(cands),
            "by_reason": {r: sum(1 for x in chosen.values() if x == r) for r in set(chosen.values())}}


def _snapshot(project_id: str, ids: list[str]) -> dict[str, Any]:
    from . import knowledge
    cs = {c["id"]: c for c in list_for_project(project_id) if c["id"] in set(ids)}
    tens = knowledge.list_tensions(project_id, status="open")
    return {"claims": {i: {"text": c["text"], "type": c["claim_type"], "topic": c["topic"], "freshness": c["freshness_class"], "qualifiers": c.get("qualifiers") or {},
                           "hedged": bool(_HEDGE.search(c["text"].lower())), "status": c["status"], "evidence": len(c["evidence"])} for i, c in cs.items()},
            "topics": len({c["topic"] for c in cs.values()}), "tensions": {k: sum(1 for t in tens if t["kind"] == k) for k in ("NOVEL", "CONTRADICTION", "WEAK_CONSENSUS", "STALE", "MISSING_PERSPECTIVE")},
            "targets": len(knowledge.list_targets(project_id, status="open")), "ts": time.time()}


def run_evaluation(project_id: str, budget: int = EVAL_BUDGET, progress: Any = None) -> dict[str, Any]:
    """Durable, bounded: select → snapshot → extract (groups of EXTRACT_GROUP, idempotent) → refresh → measure. The
    report is stored at kv claims:eval:{project} and returned. Rerunning re-measures without re-spending."""
    from . import knowledge
    harvest(project_id)
    # resumable: a pending evaluation (cohort + before-snapshot + cost mark) survives a failed/interrupted run, so a
    # retry measures the SAME cohort and only spends on what is still unnormalized
    pending_raw = db.kv_get(f"claims:eval:{project_id}:pending")
    pending = json.loads(pending_raw) if pending_raw else None
    if pending and pending.get("budget") == budget:
        cohort, ids, before, cost0 = pending["cohort"], pending["cohort"]["claim_ids"], pending["before"], pending["cost0"]
    else:
        cohort = select_cohort(project_id, budget)
        ids = cohort["claim_ids"]
        before = _snapshot(project_id, ids)
        row = db.connect().execute("SELECT COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage WHERE project_id=? AND kind='claims'", (project_id,)).fetchone()
        cost0 = {"c": float(row["c"]), "n": int(row["n"])}
        db.kv_set(f"claims:eval:{project_id}:pending", json.dumps({"budget": budget, "cohort": cohort, "before": before, "cost0": cost0}))
    if progress:
        progress(0.05, f"evaluating normalisation on {len(ids)} claims")
    cands = [c for c in list_for_project(project_id) if c["id"] in set(ids)]
    res = extract(project_id, [c for c in cands if not c.get("normalized")], transport="job")
    knowledge.refresh(project_id)
    row1 = db.connect().execute("SELECT COALESCE(SUM(cost),0) c, COUNT(*) n FROM usage WHERE project_id=? AND kind='claims'", (project_id,)).fetchone()
    cost1 = {"c": float(row1["c"]), "n": int(row1["n"])}
    after_all = {c["id"]: c for c in list_for_project(project_id)}
    after = _snapshot(project_id, ids)
    rows, merged, hedges_kept, hedged_n, qual_n, imposed, type_changes, over_general = [], 0, 0, 0, 0, {}, 0, []
    for i in ids:
        b, a = before["claims"].get(i), after_all.get(i)
        if a is None and b is not None:
            continue
        if not b or not a:
            continue
        if a["status"] == "superseded":
            merged += 1
        q = a.get("qualifiers") or {}
        has_q = any(str(v).strip() for k, v in q.items() if k != "specific_instance")
        qual_n += int(has_q)
        if q.get("imposed_by"):
            imposed[q["imposed_by"]] = imposed.get(q["imposed_by"], 0) + 1
        if b["hedged"]:
            hedged_n += 1
            kept = bool(_HEDGE.search(a["text"].lower())) or bool(str(q.get("conditions") or "").strip())
            hedges_kept += int(kept)
            if not kept and len(a["text"]) < 0.6 * len(b["text"]):
                over_general.append({"id": i, "before": b["text"][:200], "after": a["text"][:200]})
        type_changes += int(a["claim_type"] != b["type"])
        rows.append({"id": i, "reason": cohort["reasons"].get(i), "before": b["text"][:240], "after": a["text"][:240], "type": [b["type"], a["claim_type"]],
                     "topic": [b["topic"], a["topic"]], "freshness": [b["freshness"], a["freshness_class"]], "qualifiers": q, "status": a["status"],
                     "strength": a["strength"], "merged_into": a.get("superseded_by")})
    report = {"project_id": project_id, "budget": budget, "cohort": {"size": len(ids), "candidates": cohort["candidates"], "by_reason": cohort["by_reason"]},
              "calls": res.get("calls", 0), "cost_usd": round(float(cost1["c"]) - float(cost0["c"]), 4), "usage_rows": int(cost1["n"]) - int(cost0["n"]),
              "normalized": res.get("normalized", 0), "targets_proposed": res.get("targets", 0), "merged": merged,
              "qualifiers_present": qual_n, "hedged_before": hedged_n, "hedges_kept": hedges_kept, "over_generalized": over_general,
              "imposed_by": imposed, "type_changes": type_changes,
              "topics": {"before": before["topics"], "after": after["topics"]}, "tensions": {"before": before["tensions"], "after": after["tensions"]},
              "open_targets": {"before": before["targets"], "after": after["targets"]}, "rows": rows[:200], "ts": time.time()}
    db.kv_set(f"claims:eval:{project_id}", json.dumps(report))
    db.kv_set(f"claims:eval:{project_id}:pending", None)
    return {k: v for k, v in report.items() if k != "rows"} | {"rows": len(rows)}


def evaluation_report(project_id: str) -> dict[str, Any] | None:
    raw = db.kv_get(f"claims:eval:{project_id}")
    return json.loads(raw) if raw else None


def ensure(project_id: str, allow_model: bool = False) -> dict[str, Any]:
    """What Chat/Discover call before they need Claims: harvest ($0) + assess ($0) + refresh the map ($0); optionally an
    inline extraction when the caller may spend (bounded by EXTRACT_MAX_INLINE)."""
    from . import knowledge, works as _works
    try:
        _works.index_project_sources(project_id)                          # G6: sources that ARE manifestations of a Work ($0, idempotent)
    except Exception as e:  # noqa: BLE001
        log.warning("work indexing skipped: %s", e)
    h = harvest(project_id)
    out: dict[str, Any] = {"harvested": h["created"], "extracted": None}
    if allow_model:
        cands = unnormalized(project_id)
        if cands and len(cands) <= EXTRACT_MAX_INLINE:
            try:
                out["extracted"] = extract(project_id, cands)
            except Exception as e:  # noqa: BLE001
                log.warning("claims extraction skipped: %s", e)
                out["extracted"] = {"error": str(e)[:200]}
        elif cands:
            out["extracted"] = {"job": maybe_extract(project_id, "ensure", force=True)}
    assess_project(project_id)
    out["map"] = knowledge.refresh(project_id)
    return out


def stats(project_id: str) -> dict[str, Any]:
    conn = db.connect()
    by = {r["strength"]: r["n"] for r in conn.execute("SELECT strength, COUNT(*) n FROM project_claims WHERE project_id=? AND status!='rejected' GROUP BY strength", (project_id,))}
    st = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM project_claims WHERE project_id=? GROUP BY status", (project_id,))}
    un = conn.execute("SELECT COUNT(*) n FROM project_claims WHERE project_id=? AND normalized=0 AND status!='rejected'", (project_id,)).fetchone()["n"]
    return {"by_strength": by, "by_status": st, "unnormalized": un, "last_extract": float(db.kv_get(f"claims:last_extract:{project_id}") or 0) or None}
