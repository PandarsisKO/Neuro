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
FRESHNESS = ("static", "slow_changing", "periodic", "fast_changing")
# domain-sensitive freshness: how old may the NEWEST supporting evidence be before the Claim is flagged STALE
FRESHNESS_DAYS = {"static": None, "slow_changing": 3 * 365, "periodic": 400, "fast_changing": 120}
# corroborative sufficiency: independent supporting sources needed for each strength band
CORROBORATION = {"strong": 3, "developing": 2, "weak": 1}
STRENGTHS = ("strong", "developing", "weak", "unsupported", "stale")

CLAIMS_BATCH_MIN = 6          # unnormalized candidates that justify an extraction call on their own
CLAIMS_DEBOUNCE_S = 1800      # otherwise wait this long since the last extraction before spending again
EXTRACT_GROUP = 20            # candidates per model call
EXTRACT_MAX_INLINE = 60       # more than this → job only

_STOP = {"the", "and", "that", "with", "this", "from", "your", "have", "will", "they", "their", "there", "which", "when", "what",
         "about", "into", "than", "then", "them", "been", "were", "also", "more", "most", "some", "such", "only", "over", "under",
         "should", "would", "could", "because", "before", "after", "these", "those", "other", "each", "very", "much", "many"}


# ---------------------------------------------------------------- deterministic helpers ($0)

def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9\-']{3,}", (text or "").lower()) if w not in _STOP}


def overlap(a: str, b: str) -> float:
    """Share of the shorter passage's distinctive tokens present in the other: 1.0 = one repeats the other."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(short & long_) / len(short)


DERIVATIVE_OVERLAP = 0.6
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


def guess_freshness(text: str, claim_type: str) -> str:
    t = (text or "").lower()
    if re.search(r"\b(promotion|offer|deadline|expires?|rate|rates|pricing|price|listing|market|current)\b", t):
        return "fast_changing" if re.search(r"\b(promotion|offer|expires?|deadline)\b", t) else "periodic"
    if claim_type in ("governing",):
        return "periodic"          # rules change on a cadence (SOP revisions, tax years)
    if claim_type in ("historical",):
        return "static"
    return "slow_changing"


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
    if (src.get("platform") or "") in ("youtube", "instagram", "podcast", "media") or sig.get("text_origin") in ("captions", "transcribed"):
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


def _topic_of(text: str) -> str:
    """Two most distinctive content words: a stable, explainable node key until the contract names the topic."""
    words = [w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower()) if w not in _STOP]
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
        if len(seen) == 2:
            break
    return " ".join(seen) or "general"


# ---------------------------------------------------------------- rows

def _claim(row: Any) -> dict[str, Any]:
    d = dict(row)
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


def evidence_for(claim_id: str) -> list[dict[str, Any]]:
    rows = db.connect().execute("SELECT e.*, s.title, s.platform, s.published_at, s.channel FROM claim_evidence e JOIN sources s ON s.id=e.source_id "
                                "WHERE e.claim_id=? ORDER BY e.created_at", (claim_id,)).fetchall()
    return [dict(r) for r in rows]


def list_for_project(project_id: str, status: str | None = None, with_evidence: bool = True) -> list[dict[str, Any]]:
    q = "SELECT * FROM project_claims WHERE project_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at"
    rows = db.connect().execute(q, (project_id, status) if status else (project_id,)).fetchall()
    out = [_claim(r) for r in rows]
    if with_evidence:
        for c in out:
            c["evidence"] = evidence_for(c["id"])
    return out


def add_claim(project_id: str, text: str, *, claim_type: str = "other", qualifiers: dict[str, Any] | None = None, topic: str | None = None,
              freshness_class: str | None = None, origin: str = "user", origin_note_id: int | None = None, status: str = "proposed",
              normalized: bool = False, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
    if claim_type not in TYPES:
        claim_type = "other"
    t = time.time()
    cid = db.new_id()
    prov = provenance or {}
    with db.tx() as conn:
        conn.execute("INSERT INTO project_claims (id, project_id, text, claim_type, qualifiers, topic, freshness_class, status, normalized, origin, origin_note_id, "
                     "extraction_hash, model, prompt_version, schema_version, routing, transport, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (cid, project_id, text.strip(), claim_type, json.dumps(qualifiers or {}), topic or _topic_of(text),
                      freshness_class or guess_freshness(text, claim_type), status, 1 if normalized else 0, origin, origin_note_id,
                      prov.get("extraction_hash"), prov.get("model"), prov.get("prompt_version"), prov.get("schema_version"),
                      prov.get("routing"), prov.get("transport"), t, t))
    return get(cid)  # type: ignore[return-value]


def add_evidence(claim_id: str, source_id: str, *, locator: str | None = None, start: float | None = None, link: str | None = None,
                 relation: str = "SUPPORTS", excerpt: str | None = None, task: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Freeze the exact revision + locator. Independence against the Claim's existing evidence is decided here ($0)."""
    if relation not in RELATIONS:
        relation = "SUPPORTS"
    src = db.get_source(source_id) or {"id": source_id}
    rev = src.get("revision") or db.source_revision(source_id)
    cls = evidence_class_for(src)
    independent, derivative_of = 1, None
    for e in evidence_for(claim_id):
        if e["source_id"] == source_id:
            continue
        same_creator = bool(src.get("channel")) and src.get("channel") == e.get("channel")
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
                           "derivative_of, task, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (claim_id, source_id, rev, locator, start, link, relation, (excerpt or "")[:600], cls, independent, derivative_of, task, model, t))
        conn.execute("UPDATE project_claims SET updated_at=? WHERE id=?", (t, claim_id))
        eid = cur.lastrowid
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

def _strip_cites(text: str) -> str:
    return re.sub(r"\s*\[\d{1,2}\]", "", text or "").strip()


def harvest(project_id: str) -> dict[str, Any]:
    """Zero-cost candidate Claims from findings that already exist (approved → proposed candidate; suggested → candidate
    for investigation, origin 'finding_suggested'). Idempotent per note. Never touches the model."""
    created, merged = 0, 0
    have = {r["origin_note_id"] for r in db.connect().execute("SELECT origin_note_id FROM project_claims WHERE project_id=? AND origin_note_id IS NOT NULL", (project_id,))}
    have |= {r["note_id"] for r in db.connect().execute("SELECT note_id FROM claim_evidence_notes")}
    existing = [c for c in list_for_project(project_id, with_evidence=False) if c["status"] != "rejected"]
    for status in ("approved", "suggested"):
        for n in db.list_project_notes(project_id, status=status):
            if n["id"] in have:
                continue
            text = _strip_cites(n.get("content") or "")
            title = (n.get("title") or "").strip()
            if title and title.lower() not in text.lower():
                text = f"{title} — {text}"
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
            twin = next((x for x in existing if overlap(text, x["text"]) >= SAME_CLAIM_OVERLAP), None)
            if twin:
                for cite in cites[:4]:
                    if cite.get("source_id") and db.get_source(cite["source_id"]):
                        add_evidence(twin["id"], cite["source_id"], locator=cite.get("timestamp"), start=cite.get("start"), link=cite.get("link"),
                                     relation="SUPPORTS", excerpt=cite.get("snippet"), task="findings.extract", model=n.get("model"))
                with db.tx() as conn:
                    conn.execute("INSERT OR IGNORE INTO claim_evidence_notes (claim_id, note_id) VALUES (?,?)", (twin["id"], n["id"]))
                assess(twin["id"])
                merged += 1
                continue
            ctype = guess_type(text, cls)
            c = add_claim(project_id, text, claim_type=ctype, origin="finding" if status == "approved" else "finding_suggested", origin_note_id=n["id"],
                          status="proposed", normalized=False)
            for cite in cites[:4]:
                if cite.get("source_id") and db.get_source(cite["source_id"]):
                    add_evidence(c["id"], cite["source_id"], locator=cite.get("timestamp"), start=cite.get("start"), link=cite.get("link"),
                                 relation="SUPPORTS", excerpt=cite.get("snippet"), task="findings.extract", model=n.get("model"))
            assess(c["id"])
            existing.append(c)
            created += 1
    return {"created": created, "merged": merged}


# ---------------------------------------------------------------- assessment ($0, deterministic, explained)

def assess(claim_id: str) -> dict[str, Any] | None:
    """Strength from the evidence REQUIREMENT of the Claim type, not the source count; freshness from the domain class;
    readiness separate from strength. Writes strength/strength_why/readiness/readiness_why; returns the claim."""
    c = get(claim_id)
    if not c:
        return None
    ev = c["evidence"]
    now = time.time()
    # refresh stale flags against the live revision
    for e in ev:
        live = db.source_revision(e["source_id"])
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
        else:
            strength = "developing" if len(indep_sources) >= 2 else "weak"
            why.append(f"governing Claim without a primary source: {len(sup)} secondary source(s), {len(indep_sources)} independent — the controlling text itself is missing")
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
    if sup and len(ev) != len(live_ev):
        why.append(f"{len(ev) - len(live_ev)} evidence row(s) stale: the source was revised since they were frozen — re-verify against the new revision")
    if con:
        indep_con = {e["source_id"] for e in con if e.get("independent")}
        why.append(f"{len(con)} contradicting source(s) ({len(indep_con)} independent) — unresolved")
        if strength == "strong" and (ctype not in GOVERNING_TYPES or any(e.get("evidence_class") == "authoritative" for e in con)):
            strength = "developing"
    # domain-sensitive freshness on the newest supporting evidence
    limit = FRESHNESS_DAYS.get(c.get("freshness_class") or "slow_changing")
    if sup and limit:
        ages = []
        for e in sup:
            src = db.get_source(e["source_id"]) or {}
            ts = _published_ts(src) or src.get("created_at")
            if ts:
                ages.append((now - float(ts)) / 86400)
        if ages and min(ages) > limit:
            strength = "stale"
            why.append(f"newest supporting evidence is {int(min(ages))} days old; a {c['freshness_class'].replace('_', '-')} Claim should be re-verified after {limit} days")
    # readiness is NOT strength
    app = c.get("application") or "unknown"
    if strength == "strong" and app == "established":
        readiness, rwhy = "ready", "evidence is strong and its application to this project is established"
    elif strength == "strong":
        readiness, rwhy = "not_ready", "evidence is strong but whether it applies to this project's situation is " + ("still developing" if app == "developing" else "not established")
    else:
        readiness, rwhy = "not_ready", f"evidence is {strength}"
    with db.tx() as conn:
        conn.execute("UPDATE project_claims SET strength=?, strength_why=?, readiness=?, readiness_why=?, updated_at=? WHERE id=?",
                     (strength, "; ".join(why), readiness, rwhy, now, claim_id))
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
causal, novel_tactic (an unconventional tactic), other. Give a freshness_class by how fast the truth changes in that domain.
Then, from the project brief and the claims, propose evidence targets the user has not named: what a competent researcher would need to
establish before deciding, each with a sufficiency kind (governing = one current directly applicable primary source can close it;
corroborative = several independent sources needed), preferred evidence classes in order, and a one-sentence closure criterion.
You are proposing research state, not deciding it."""


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
        group = cands[i:i + EXTRACT_GROUP]
        ih = extraction_hash(project, group)
        if all(c.get("extraction_hash") == ih for c in group):
            continue
        user = json.dumps({"brief": project.get("brief"), "goal": project.get("goal"), "questions": project.get("questions"),
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
        for tgt in parsed.get("targets", [])[:8]:
            if knowledge.add_target(project_id, tgt.get("question") or "", topic=tgt.get("topic"), sufficiency=tgt.get("sufficiency") or "corroborative",
                                    preferred_classes=tgt.get("preferred_classes") or [], closure=tgt.get("closure"), origin="model", provenance=prov):
                targets += 1
    for c in cands:
        assess(c["id"])
    db.kv_set(f"claims:last_extract:{project_id}", str(time.time()))
    return {"normalized": normalized, "targets": targets, "calls": calls}


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
    job = db.create_job("extract_claims", {"project_id": project_id, "reason": reason})
    return job


def run_job(payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    pid = payload["project_id"]
    harvest(pid)
    res = extract(pid, transport="job")
    from . import knowledge
    knowledge.refresh(pid)
    return res


def ensure(project_id: str, allow_model: bool = False) -> dict[str, Any]:
    """What Chat/Discover call before they need Claims: harvest ($0) + assess ($0) + refresh the map ($0); optionally an
    inline extraction when the caller may spend (bounded by EXTRACT_MAX_INLINE)."""
    from . import knowledge
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
