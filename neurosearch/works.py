"""G6 — Canonical Works & Source Resolver (0.31.0).

Work = intellectual/legal identity (global) · Version = first-class edition/revision whenever it changes what is
authoritative (global) · Manifestation = a particular obtainable representation of a version — possessed (a source),
seen (a candidate) or merely known (unavailable) (global) · project_works = relevance/use, never ownership.

Everything here is $0 and conservative. Identity signals, ranked and frozen (Kyle's G6 lock): (1) DOI / ISBN / ISSN /
official document number / statute citation / SOP number; (2) exact normalized title + creator + edition/year;
(3) publisher + title + date; (4) model-assisted match (not built — deferred until a real need); (5) NEVER auto-merge on
title similarity alone for legal/regulatory material. Ambiguity → a `possible_manifestation_of` relation, never a merge.
False negatives are cheaper than false canonicalization.

Independence by lineage: sources that are manifestations / reprints / translations / excerpts / summaries / quotations /
derivatives of one Work share ONE evidentiary lineage (`lineage_of`); `implements` / `interprets` / `cites` carry their
own analysis and keep their own lineage. Claims use this instead of raw source count.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from . import db

log = logging.getLogger("neurosearch.works")

KINDS = ("book", "paper", "statute", "regulation", "sop", "publication", "form", "standard", "report", "course", "series", "dataset", "other")
REGULATORY_KINDS = {"statute", "regulation", "sop", "publication", "form", "standard"}
RELATIONS = ("manifestation_of", "reprint_of", "translation_of", "revision_of", "excerpt_of", "summary_of", "quotes", "derivative_of",
             "cites", "implements", "interprets", "possible_manifestation_of")
# relations that put a source in the Work's lineage (one evidentiary line); the rest carry their own analysis
LINEAGE_RELATIONS = {"manifestation_of", "reprint_of", "translation_of", "revision_of", "excerpt_of", "summary_of", "quotes", "derivative_of"}
PRIMARY_RELATIONS = {"manifestation_of", "reprint_of", "translation_of", "revision_of"}
FORMS = ("official", "mirror", "html", "excerpt", "ocr", "scan", "reprint", "translation", "summary", "derivative")
CHANGE_KINDS = ("unknown", "supersedes", "material", "rehost", "formatting")

# ---------------------------------------------------------------- identifiers ($0)

_ISBN = re.compile(r"\b(?:isbn[:\s-]*)?((?:97[89][- ]?)?(?:\d[- ]?){9}[\dXx])\b", re.I)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>)\],;]+)", re.I)
_SOP = re.compile(r"\bSOP\s*(\d{2})[\s-]*(\d{2})(?:[\s-]*(\d{1,2}))?\b", re.I)
_PUB = re.compile(r"\b(?:IRS\s+)?(?:Publication|Pub\.?)\s*(\d{2,4})\b", re.I)
_USC = re.compile(r"\b(\d{1,2})\s*U\.?\s*S\.?\s*C\.?\s*(?:§+|section)?\s*(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)", re.I)
_IRC = re.compile(r"\bIRC\s*(?:§+|section)?\s*(\d+[A-Za-z]?(?:\([a-z0-9]+\))*)", re.I)
_CFR = re.compile(r"\b(\d{1,2})\s*C\.?\s*F\.?\s*R\.?\s*(?:§+|part|section)?\s*([\d.]+)", re.I)
_FORM = re.compile(r"\b(?:IRS|SBA)?\s*Form\s+(\d{3,4}[A-Z]?(?:-[A-Z0-9]+)?)\b", re.I)
_TAX_YEAR = re.compile(r"\b(?:tax year|TY|for)\s+(20\d\d)\b", re.I)


def _isbn_ok(d: str) -> bool:
    if len(d) == 10:
        s = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(d))
        return s % 11 == 0
    if len(d) == 13 and d.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0
    return False


def extract_identifiers(text: str) -> list[dict[str, Any]]:
    """Every canonical identifier a text names, with the Work it implies. Deterministic; no lookups."""
    out: list[dict[str, Any]] = []
    t = text or ""
    for m in _SOP.finditer(t):
        fam = f"SOP {m.group(1)} {m.group(2)}"
        out.append({"scheme": "sop", "value": fam.lower().replace(" ", ""), "kind": "sop", "title": f"SBA {fam}", "family": fam,
                    "version": (f"{fam} {m.group(3)}" if m.group(3) else None), "publisher": "U.S. Small Business Administration",
                    "url": "https://www.sba.gov/document/sop-" + f"{m.group(1)}-{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else "")})
    for m in _PUB.finditer(t):
        n = m.group(1)
        ty = _TAX_YEAR.search(t)
        out.append({"scheme": "pub", "value": f"irs-pub-{n}", "kind": "publication", "title": f"IRS Publication {n}", "family": f"IRS Publication {n}",
                    "version": (f"tax year {ty.group(1)}" if ty else None), "publisher": "Internal Revenue Service", "url": f"https://www.irs.gov/pub/irs-pdf/p{n}.pdf"})
    for m in _USC.finditer(t):
        title_no, sec = m.group(1), m.group(2)
        out.append({"scheme": "citation", "value": f"{title_no}usc{sec.lower()}", "kind": "statute", "title": f"{title_no} U.S.C. § {sec}", "family": f"{title_no} U.S.C. § {sec}",
                    "version": None, "publisher": "United States Code", "url": f"https://www.law.cornell.edu/uscode/text/{title_no}/{sec.split('(')[0]}"})
    for m in _IRC.finditer(t):
        sec = m.group(1)
        out.append({"scheme": "citation", "value": f"26usc{sec.lower()}", "kind": "statute", "title": f"26 U.S.C. § {sec} (IRC § {sec})", "family": f"26 U.S.C. § {sec}",
                    "version": None, "publisher": "United States Code", "url": f"https://www.law.cornell.edu/uscode/text/26/{sec.split('(')[0]}"})
    for m in _CFR.finditer(t):
        out.append({"scheme": "citation", "value": f"{m.group(1)}cfr{m.group(2)}", "kind": "regulation", "title": f"{m.group(1)} C.F.R. § {m.group(2)}", "family": f"{m.group(1)} C.F.R. § {m.group(2)}",
                    "version": None, "publisher": "Code of Federal Regulations", "url": f"https://www.ecfr.gov/current/title-{m.group(1)}/section-{m.group(2)}"})
    for m in _FORM.finditer(t):
        num = m.group(1).upper().replace("-", "")                            # 1120-S and 1120S are the same form
        out.append({"scheme": "docnum", "value": f"form-{num.lower()}", "kind": "form", "title": f"Form {num}", "family": f"Form {num}", "version": None, "publisher": None, "url": None})
    for m in _DOI.finditer(t):
        doi = m.group(1).rstrip(".,;")
        out.append({"scheme": "doi", "value": doi.lower(), "kind": "paper", "title": f"DOI {doi}", "family": f"DOI {doi}", "version": None, "publisher": None, "url": f"https://doi.org/{doi}"})
    for m in _ISBN.finditer(t):
        digits = re.sub(r"[- ]", "", m.group(1))
        if _isbn_ok(digits):
            out.append({"scheme": "isbn", "value": digits.upper(), "kind": "book", "title": f"ISBN {digits}", "family": f"ISBN {digits}", "version": None, "publisher": None,
                        "url": f"https://openlibrary.org/isbn/{digits}"})
    seen: set[tuple[str, str]] = set()
    uniq = []
    for i in out:
        k = (i["scheme"], i["value"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return uniq


def identifiers_of_source(src: dict[str, Any]) -> list[dict[str, Any]]:
    """Identifiers a SOURCE carries in its own metadata/URL (title, description, url) — what makes it a manifestation."""
    url = src.get("url") or ""
    text = " ".join(str(src.get(k) or "") for k in ("title", "description"))
    ids = extract_identifiers(text)
    u = url.lower()
    m = re.search(r"sop-(\d{2})-(\d{2})(?:-(\d{1,2}))?", u)
    if m:
        ids += extract_identifiers(f"SOP {m.group(1)} {m.group(2)}" + (f" {m.group(3)}" if m.group(3) else ""))
    m = re.search(r"irs\.gov/pub/irs-pdf/p(\d{2,4})\.pdf", u)
    if m:
        ids += extract_identifiers(f"IRS Publication {m.group(1)}")
    m = re.search(r"doi\.org/(10\.\d{4,9}/[^\s?#]+)", url, re.I)
    if m:
        ids += extract_identifiers(m.group(1))
    seen: set[tuple[str, str]] = set()
    out = []
    for i in ids:
        if (i["scheme"], i["value"]) not in seen:
            seen.add((i["scheme"], i["value"]))
            out.append(i)
    return out


def normalize_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())
    t = re.sub(r"\b(the|a|an|of|and|for|to|in|on)\b", " ", t)
    return " ".join(t.split())


# ---------------------------------------------------------------- rows

def _row(table: str, wid: str) -> dict[str, Any] | None:
    r = db.connect().execute(f"SELECT * FROM {table} WHERE id=?", (wid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("creators", "identifiers", "basis"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def get(work_id: str) -> dict[str, Any] | None:
    w = _row("works", work_id)
    if not w:
        return None
    w["versions"] = versions_of(work_id)
    w["manifestations"] = manifestations_of(work_id)
    return w


def versions_of(work_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in db.connect().execute("SELECT * FROM work_versions WHERE work_id=? ORDER BY created_at", (work_id,)).fetchall()]


def manifestations_of(work_id: str) -> list[dict[str, Any]]:
    rows = db.connect().execute("SELECT m.*, s.title AS source_title, s.status AS source_status, s.platform, c.title AS candidate_title FROM work_manifestations m "
                                "LEFT JOIN sources s ON s.id=m.source_id LEFT JOIN candidates c ON c.id=m.candidate_id WHERE m.work_id=? ORDER BY m.created_at", (work_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("basis"):
            try:
                d["basis"] = json.loads(d["basis"])
            except ValueError:
                pass
        out.append(d)
    return out


def by_identifier(scheme: str, value: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT work_id, version_id FROM work_identifiers WHERE scheme=? AND value=?", (scheme, value)).fetchone()
    return {"work_id": r["work_id"], "version_id": r["version_id"]} if r else None


def get_any(work_id: str) -> dict[str, Any] | None:
    """get() that follows merge aliases (an old id keeps resolving after merge_work)."""
    w = get(work_id)
    if w:
        return w
    a = by_identifier("alias", work_id)
    return get(a["work_id"]) if a else None


def ensure_work(kind: str, title: str, *, identifiers: list[dict[str, str]] | None = None, creators: list[str] | None = None,
                publisher: str | None = None, year: str | None = None) -> tuple[dict[str, Any], bool]:
    """Find-or-create by the frozen signal order. (1) an identifier hit is identity; (2) exact normalized title + creator
    (+ year when given) is identity for non-regulatory kinds; regulatory kinds without an identifier get a NEW stub —
    title similarity never merges legal material. Returns (work, created)."""
    ids = identifiers or []
    for i in ids:
        hit = by_identifier(i["scheme"], i["value"])
        if hit:
            return get(hit["work_id"]), False  # type: ignore[return-value]
    tn = normalize_title(title)
    if kind not in REGULATORY_KINDS and tn:
        for r in db.connect().execute("SELECT * FROM works WHERE title_norm=? AND kind=?", (tn, kind)).fetchall():
            w_cre = json.loads(r["creators"] or "[]")
            same_creator = (not creators and not w_cre) or bool({c.lower() for c in (creators or [])} & {c.lower() for c in w_cre})
            if same_creator:
                return get(r["id"]), False  # type: ignore[return-value]
    t = time.time()
    wid = db.new_id()
    with db.tx() as conn:
        conn.execute("INSERT INTO works (id, kind, title, title_norm, creators, publisher, identifiers, resolution, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (wid, kind if kind in KINDS else "other", title.strip(), tn, json.dumps(creators or []), publisher, json.dumps(ids), "resolved" if ids else "stub", t, t))
        for i in ids:
            conn.execute("INSERT OR IGNORE INTO work_identifiers (scheme, value, work_id) VALUES (?,?,?)", (i["scheme"], i["value"], wid))
    return get(wid), True  # type: ignore[return-value]


def ensure_version(work_id: str, label: str, *, edition: str | None = None, year: str | None = None, effective_date: str | None = None,
                   supersedes_id: str | None = None, change_kind: str = "unknown", change_note: str | None = None, status: str = "unknown") -> dict[str, Any]:
    conn = db.connect()
    r = conn.execute("SELECT * FROM work_versions WHERE work_id=? AND lower(label)=lower(?)", (work_id, label)).fetchone()
    t = time.time()
    if r:
        if supersedes_id or change_kind != "unknown" or effective_date or status != "unknown":
            with db.tx() as c:
                c.execute("UPDATE work_versions SET supersedes_id=COALESCE(?, supersedes_id), change_kind=CASE WHEN ?='unknown' THEN change_kind ELSE ? END, "
                          "change_note=COALESCE(?, change_note), effective_date=COALESCE(?, effective_date), status=CASE WHEN ?='unknown' THEN status ELSE ? END, updated_at=? WHERE id=?",
                          (supersedes_id, change_kind, change_kind, change_note, effective_date, status, status, t, r["id"]))
                if supersedes_id:
                    c.execute("UPDATE work_versions SET status='superseded', updated_at=? WHERE id=?", (t, supersedes_id))
        return dict(conn.execute("SELECT * FROM work_versions WHERE id=?", (r["id"],)).fetchone())
    vid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO work_versions (id, work_id, label, edition, year, effective_date, supersedes_id, change_kind, change_note, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (vid, work_id, label, edition, year, effective_date, supersedes_id, change_kind if change_kind in CHANGE_KINDS else "unknown", change_note, status, t, t))
        if supersedes_id:
            c.execute("UPDATE work_versions SET status='superseded', updated_at=? WHERE id=?", (t, supersedes_id))
    return dict(conn.execute("SELECT * FROM work_versions WHERE id=?", (vid,)).fetchone())


def link_source(source_id: str, work_id: str, *, version_id: str | None = None, relation: str = "manifestation_of", form: str | None = None,
                confidence: str = "identifier", basis: dict[str, Any] | None = None) -> dict[str, Any]:
    """A possessed source ↔ a Work (version). Idempotent per (source, work, relation). Access = owned when the source is ready."""
    if relation not in RELATIONS:
        raise ValueError(f"bad relation {relation}")
    conn = db.connect()
    src = db.get_source(source_id) or {}
    access = "owned" if src.get("status") == "ready" else "unknown"
    r = conn.execute("SELECT id FROM work_manifestations WHERE source_id=? AND work_id=? AND relation=?", (source_id, work_id, relation)).fetchone()
    t = time.time()
    if r:
        with db.tx() as c:
            c.execute("UPDATE work_manifestations SET version_id=COALESCE(?, version_id), access=?, form=COALESCE(?, form) WHERE id=?", (version_id, access, form, r["id"]))
        return dict(conn.execute("SELECT * FROM work_manifestations WHERE id=?", (r["id"],)).fetchone())
    mid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO work_manifestations (id, work_id, version_id, source_id, relation, form, access, url, confidence, basis, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, work_id, version_id, source_id, relation, form, access, src.get("url"), confidence, json.dumps(basis or {}), t))
        c.execute("UPDATE works SET updated_at=? WHERE id=?", (t, work_id))
    return dict(conn.execute("SELECT * FROM work_manifestations WHERE id=?", (mid,)).fetchone())


def link_candidate(candidate_id: str, work_id: str, *, version_id: str | None = None, url: str | None = None, basis: dict[str, Any] | None = None) -> dict[str, Any]:
    conn = db.connect()
    r = conn.execute("SELECT id FROM work_manifestations WHERE candidate_id=? AND work_id=?", (candidate_id, work_id)).fetchone()
    if r:
        return dict(conn.execute("SELECT * FROM work_manifestations WHERE id=?", (r["id"],)).fetchone())
    mid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO work_manifestations (id, work_id, version_id, candidate_id, relation, form, access, url, confidence, basis, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, work_id, version_id, candidate_id, "manifestation_of", "official", "candidate", url, "identifier", json.dumps(basis or {}), time.time()))
    return dict(conn.execute("SELECT * FROM work_manifestations WHERE id=?", (mid,)).fetchone())


def set_project_relevance(project_id: str, work_id: str, relevance: str, reason: str | None = None, target_id: str | None = None) -> None:
    """Project-relative only. Never touches the Work row."""
    if relevance not in ("attached", "relevant", "targeted", "dismissed"):
        raise ValueError("bad relevance")
    with db.tx() as c:
        c.execute("INSERT INTO project_works (project_id, work_id, relevance, reason, target_id, updated_at) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(project_id, work_id) DO UPDATE SET relevance=excluded.relevance, reason=COALESCE(excluded.reason, project_works.reason), "
                  "target_id=COALESCE(excluded.target_id, project_works.target_id), updated_at=excluded.updated_at", (project_id, work_id, relevance, reason, target_id, time.time()))


def project_relevance(project_id: str, work_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM project_works WHERE project_id=? AND work_id=?", (project_id, work_id)).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- lineage

def lineage_of(source_id: str) -> dict[str, Any] | None:
    """The Work (and version) whose lineage this source belongs to, or None. Only LINEAGE_RELATIONS count; a source that
    merely cites / interprets / implements a Work keeps its own lineage."""
    r = db.connect().execute("SELECT m.work_id, m.version_id, m.relation, m.form FROM work_manifestations m WHERE m.source_id=? AND m.relation IN (%s) "
                             "ORDER BY CASE m.relation WHEN 'manifestation_of' THEN 0 WHEN 'reprint_of' THEN 1 ELSE 2 END LIMIT 1"
                             % ",".join("?" * len(LINEAGE_RELATIONS)), (source_id, *sorted(LINEAGE_RELATIONS))).fetchone()
    return dict(r) if r else None


def relation_of(source_id: str, work_id: str) -> str | None:
    r = db.connect().execute("SELECT relation FROM work_manifestations WHERE source_id=? AND work_id=? ORDER BY created_at LIMIT 1", (source_id, work_id)).fetchone()
    return r["relation"] if r else None


def primary_manifestations(work_id: str) -> list[dict[str, Any]]:
    """Obtainable primary representations: owned sources with a primary relation, candidates, or known-unavailable copies."""
    return [m for m in manifestations_of(work_id) if m["relation"] in PRIMARY_RELATIONS or m.get("candidate_id")]


def owned_primary(work_id: str, version_id: str | None = None) -> list[dict[str, Any]]:
    out = [m for m in manifestations_of(work_id) if m.get("source_id") and m["relation"] in PRIMARY_RELATIONS and m.get("access") == "owned"]
    if version_id:
        exact = [m for m in out if m.get("version_id") == version_id]
        return exact or out
    return out


# ---------------------------------------------------------------- versions and freshness

def _version_rank(v: dict[str, Any]) -> tuple[float, str]:
    """Order versions: effective date, then year, then the trailing number in the label ('SOP 50 10 8' → 8)."""
    m = re.search(r"(\d+)\s*$", v.get("label") or "")
    n = float(m.group(1)) if m else 0.0
    return (float((v.get("effective_date") or v.get("year") or "0")[:4] or 0) * 1000 + n, v["id"])


def newer_versions(version_id: str) -> list[dict[str, Any]]:
    v = db.connect().execute("SELECT * FROM work_versions WHERE id=?", (version_id,)).fetchone()
    if not v:
        return []
    vs = versions_of(v["work_id"])
    me = dict(v)
    out = [x for x in vs if x["id"] != version_id and (x.get("supersedes_id") == version_id or _version_rank(x) > _version_rank(me))]
    return sorted(out, key=_version_rank)


def version_freshness(source_id: str) -> dict[str, Any] | None:
    """How evidence from this source's manifestation relates to newer versions of its Work:
    none | unknown | supersedes | material | rehost — the input to the G6 freshness rule."""
    lin = lineage_of(source_id)
    if not lin or not lin.get("version_id"):
        return None
    newer = newer_versions(lin["version_id"])
    if not newer:
        return {"work_id": lin["work_id"], "version_id": lin["version_id"], "relation": "none"}
    kinds = [n.get("change_kind") or "unknown" for n in newer]
    rel = "material" if "material" in kinds else "supersedes" if "supersedes" in kinds else "unknown" if "unknown" in kinds else "rehost"
    return {"work_id": lin["work_id"], "version_id": lin["version_id"], "relation": rel, "newest": newer[-1]["label"], "newer": [n["label"] for n in newer],
            "change_note": next((n.get("change_note") for n in newer if n.get("change_note")), None)}


# ---------------------------------------------------------------- indexing sources and citations ($0)

def _form_for(src: dict[str, Any], ident: dict[str, Any] | None = None) -> str:
    """official (government host) · mirror (a copy: the identifier is in the URL path or it is an uploaded document) ·
    quotes (a page that talks about the Work) · derivative (media that explains it). Conservative: a non-official page
    whose only link to the Work is its title is a quotation, not a manifestation."""
    url = src.get("url") or ""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if host.endswith((".gov", ".mil")) or host.endswith(".gov.uk"):
        return "official"
    if (src.get("platform") or "") in ("youtube", "instagram", "podcast", "media"):
        return "derivative"
    if (src.get("platform") or "") == "document":
        return "mirror"                                                    # an uploaded copy of the document
    if ident:
        key = re.sub(r"[^a-z0-9]", "", (ident.get("family") or "").lower().replace("sba", "").replace("irs", "") + (ident.get("version") or "").split()[-1] if ident.get("version") else (ident.get("family") or "").lower())
        p = re.sub(r"[^a-z0-9]", "", path)
        if key and key in p:
            return "mirror"
        if ident.get("scheme") == "pub" and re.search(r"p\d{2,4}\.pdf$", path):
            return "mirror"
    return "quotes"


def index_source(source_id: str) -> list[dict[str, Any]]:
    """A source whose own metadata/URL carries an identifier becomes a manifestation of that Work (version). Official
    hosts are `official`, other copies `mirror`, media that talks about it `derivative_of` (its own analysis stays
    separate: not a primary). Idempotent; $0."""
    src = db.get_source(source_id)
    if not src:
        return []
    out = []
    for i in identifiers_of_source(src):
        w, _ = ensure_work(i["kind"], i["family"], identifiers=[{"scheme": i["scheme"], "value": i["value"]}], publisher=i.get("publisher"))
        vid = None
        if i.get("version"):
            vid = ensure_version(w["id"], i["version"])["id"]
            with db.tx() as c:
                c.execute("UPDATE work_identifiers SET version_id=COALESCE(version_id, ?) WHERE scheme=? AND value=?", (vid, i["scheme"], i["value"]))
        form = _form_for(src, i)
        relation = {"derivative": "derivative_of", "quotes": "quotes"}.get(form, "manifestation_of")
        m = link_source(source_id, w["id"], version_id=vid, relation=relation, form=form, confidence="identifier",
                        basis={"identifier": f"{i['scheme']}:{i['value']}", "from": "source metadata/url"})
        # a primary copy names the Work better than its bare identifier (ISBN/DOI stubs get the book's/paper's title)
        if relation == "manifestation_of" and (w["title"] or "").startswith(("ISBN ", "DOI ")) and src.get("title"):
            with db.tx() as c:
                c.execute("UPDATE works SET title=?, title_norm=?, creators=CASE WHEN creators='[]' AND ? IS NOT NULL THEN json_array(?) ELSE creators END, updated_at=? WHERE id=?",
                          (src["title"][:200], normalize_title(src["title"]), src.get("channel"), src.get("channel"), time.time(), w["id"]))
        out.append({"work": w["title"], "version": i.get("version"), "relation": relation, "form": form, "manifestation_id": m["id"]})
    return out


def index_project_sources(project_id: str) -> int:
    n = 0
    for sid in db.project_source_ids(project_id, ready_only=False):
        if db.connect().execute("SELECT 1 FROM work_manifestations WHERE source_id=? LIMIT 1", (sid,)).fetchone():
            continue
        n += len(index_source(sid))
    return n


def cite(project_id: str, text: str, *, source_id: str | None = None, claim_id: str | None = None) -> list[dict[str, Any]]:
    """A finding/Claim that names a Work: ensure the Work (stub if new) → the citing source `cites` it → project relevance;
    when no owned primary manifestation exists: a Candidate (platform 'work') and an Evidence Target naming the
    MANIFESTATION needed ("Obtain the authoritative/current manifestation of IRS Publication 946 for tax year 2026").
    Resolved identity, unresolved access — represented, never conflated with unknown identity."""
    from . import candidates, knowledge
    results = []
    for i in extract_identifiers(text):
        w, created = ensure_work(i["kind"], i["family"], identifiers=[{"scheme": i["scheme"], "value": i["value"]}], publisher=i.get("publisher"))
        vid = ensure_version(w["id"], i["version"])["id"] if i.get("version") else None
        if source_id and source_id not in {m.get("source_id") for m in manifestations_of(w["id"])}:
            link_source(source_id, w["id"], version_id=vid, relation="cites", form=None, confidence="identifier", basis={"identifier": f"{i['scheme']}:{i['value']}", "from": "finding text"})
        owned = owned_primary(w["id"], vid)
        outcome: dict[str, Any] = {"work_id": w["id"], "title": w["title"], "version": i.get("version"), "identity": "resolved", "created": created}
        if owned:
            outcome["access"] = "owned"
            outcome["source_ids"] = [m["source_id"] for m in owned]
            set_project_relevance(project_id, w["id"], "relevant", reason="cited by project evidence")
        else:
            outcome["access"] = "unavailable"
            cid = None
            if i.get("url"):
                cid = candidates.remember([{"external_id": f"{i['scheme']}:{i['value']}", "url": i["url"], "title": w["title"] + (f" — {i['version']}" if i.get("version") else ""),
                                            "description": f"cited by project evidence; canonical Work {w['title']}", "creator": i.get("publisher"), "content_type": "document"}],
                                          "work", project_id, {"kind": "citation", "title": w["title"], "claim_id": claim_id})[0]
                link_candidate(cid, w["id"], version_id=vid, url=i["url"], basis={"identifier": f"{i['scheme']}:{i['value']}"})
                outcome["candidate_id"] = cid
            want = f"the authoritative/current manifestation of {w['title']}" + (f" ({i['version']})" if i.get("version") else "")
            tg = knowledge.add_target(project_id, f"Obtain {want}", topic=None, claim_id=claim_id, sufficiency="governing",
                                      preferred_classes=["authoritative"], closure="the primary manifestation itself is in the project (an official or equivalent copy of the right version)",
                                      origin="system", gap="resolved identity, unresolved access")
            set_project_relevance(project_id, w["id"], "targeted", reason="cited but no primary manifestation owned", target_id=(tg or {}).get("id"))
            outcome["target_id"] = (tg or {}).get("id")
        results.append(outcome)
    return results


# ---------------------------------------------------------------- the resolver (find a copy)

def find_copy(text: str, project_id: str | None = None, *, external: bool = False) -> dict[str, Any]:
    """Identity first, then access in the mandated order: project → global library (owned manifestations) → candidates →
    external (a Discover job, only when asked). Outcomes: resolved+owned · resolved+candidate · resolved identity with
    unresolved access · unresolved identity. $0."""
    from . import candidates as _cand
    ids = extract_identifiers(text)
    if not ids:
        return {"identity": "unresolved", "input": text, "note": "no canonical identifier (ISBN, DOI, SOP number, IRS publication, statute or CFR citation) recognised — title-only matching never resolves identity",
                "next": "discover"}
    i = ids[0]
    w, created = ensure_work(i["kind"], i["family"], identifiers=[{"scheme": i["scheme"], "value": i["value"]}], publisher=i.get("publisher"))
    vid = ensure_version(w["id"], i["version"])["id"] if i.get("version") else None
    owned = owned_primary(w["id"], vid)
    in_project = [m for m in owned if project_id and m["source_id"] in set(db.project_source_ids(project_id, ready_only=False))]
    out: dict[str, Any] = {"identity": "resolved", "work": {k: w[k] for k in ("id", "kind", "title", "resolution")}, "version": i.get("version"), "created": created,
                           "steps": []}
    out["steps"].append({"step": "project", "found": len(in_project)})
    out["steps"].append({"step": "global_library", "found": len(owned) - len(in_project)})
    if in_project:
        out.update(access="owned", where="project", source_ids=[m["source_id"] for m in in_project], next="none")
        return out
    if owned:
        out.update(access="owned", where="library", source_ids=[m["source_id"] for m in owned], next="attach",
                   attach={"endpoint": f"/api/projects/{project_id}/members" if project_id else None, "source_ids": [m["source_id"] for m in owned]})
        return out
    cands = [m for m in manifestations_of(w["id"]) if m.get("candidate_id")]
    out["steps"].append({"step": "candidate_index", "found": len(cands)})
    if cands:
        out.update(access="candidate", candidate_ids=[m["candidate_id"] for m in cands], next="acquire")
        return out
    out.update(access="unavailable", next="acquire" if i.get("url") else "discover", url=i.get("url"))
    if external and project_id:
        job = db.create_job("discover", {"project_id": project_id, "refine": f"obtain {w['title']}" + (f" {i['version']}" if i.get("version") else ""), "mode": "web_first"})
        out["job_id"] = job["id"]
    return out


# ---------------------------------------------------------------- canonical merge (the only way two Works become one)

def merge_work(source_work_id: str, canonical_work_id: str, *, reason: str = "same canonical identifier") -> dict[str, Any]:
    """Fold `source_work` into `canonical_work`: identifiers, versions (by label), manifestations (dedupe per source/relation),
    project relevance (keep the stronger state), targets/claims text untouched (they reference sources, not works), plus an
    audit alias so the old id still resolves. Never called automatically on title similarity — only on identical
    normalized identifiers or by explicit request."""
    if source_work_id == canonical_work_id:
        raise ValueError("same work")
    src, dst = get(source_work_id), get(canonical_work_id)
    if not src or not dst:
        raise ValueError("unknown work")
    t = time.time()
    moved = {"identifiers": 0, "versions": 0, "manifestations": 0, "project_works": 0}
    rank = {"dismissed": 0, "relevant": 1, "targeted": 2, "attached": 3}
    with db.tx() as c:
        moved["identifiers"] = c.execute("UPDATE work_identifiers SET work_id=? WHERE work_id=?", (canonical_work_id, source_work_id)).rowcount
        vmap: dict[str, str] = {}
        for v in c.execute("SELECT * FROM work_versions WHERE work_id=?", (source_work_id,)).fetchall():
            hit = c.execute("SELECT id FROM work_versions WHERE work_id=? AND lower(label)=lower(?)", (canonical_work_id, v["label"])).fetchone()
            if hit:
                vmap[v["id"]] = hit["id"]
                c.execute("DELETE FROM work_versions WHERE id=?", (v["id"],))
            else:
                c.execute("UPDATE work_versions SET work_id=?, updated_at=? WHERE id=?", (canonical_work_id, t, v["id"]))
                vmap[v["id"]] = v["id"]
            moved["versions"] += 1
        for old_v, new_v in vmap.items():
            c.execute("UPDATE work_versions SET supersedes_id=? WHERE supersedes_id=?", (new_v, old_v))
            c.execute("UPDATE work_identifiers SET version_id=? WHERE version_id=?", (new_v, old_v))
            c.execute("UPDATE work_manifestations SET version_id=? WHERE version_id=?", (new_v, old_v))
        for m in c.execute("SELECT * FROM work_manifestations WHERE work_id=?", (source_work_id,)).fetchall():
            dup = c.execute("SELECT id FROM work_manifestations WHERE work_id=? AND relation=? AND COALESCE(source_id,'')=COALESCE(?,'') AND COALESCE(candidate_id,'')=COALESCE(?,'')",
                            (canonical_work_id, m["relation"], m["source_id"], m["candidate_id"])).fetchone()
            if dup:
                c.execute("DELETE FROM work_manifestations WHERE id=?", (m["id"],))
            else:
                c.execute("UPDATE work_manifestations SET work_id=? WHERE id=?", (canonical_work_id, m["id"]))
            moved["manifestations"] += 1
        for pw in c.execute("SELECT * FROM project_works WHERE work_id=?", (source_work_id,)).fetchall():
            cur = c.execute("SELECT relevance FROM project_works WHERE project_id=? AND work_id=?", (pw["project_id"], canonical_work_id)).fetchone()
            if not cur or rank.get(pw["relevance"], 0) > rank.get(cur["relevance"], 0):
                c.execute("INSERT INTO project_works (project_id, work_id, relevance, reason, target_id, updated_at) VALUES (?,?,?,?,?,?) "
                          "ON CONFLICT(project_id, work_id) DO UPDATE SET relevance=excluded.relevance, reason=excluded.reason, target_id=COALESCE(excluded.target_id, project_works.target_id), updated_at=excluded.updated_at",
                          (pw["project_id"], canonical_work_id, pw["relevance"], pw["reason"], pw["target_id"], t))
            c.execute("DELETE FROM project_works WHERE project_id=? AND work_id=?", (pw["project_id"], source_work_id))
            moved["project_works"] += 1
        c.execute("UPDATE claim_evidence SET lineage_id=? WHERE lineage_id=?", (canonical_work_id, source_work_id))
        # audit alias: the old id and title stay resolvable
        c.execute("INSERT OR IGNORE INTO work_identifiers (scheme, value, work_id) VALUES ('alias', ?, ?)", (source_work_id, canonical_work_id))
        c.execute("INSERT OR IGNORE INTO work_identifiers (scheme, value, work_id) VALUES ('alias-title', ?, ?)", (src["title_norm"], canonical_work_id))
        c.execute("DELETE FROM works WHERE id=?", (source_work_id,))
        c.execute("UPDATE works SET updated_at=? WHERE id=?", (t, canonical_work_id))
    db.kv_bump("works:merged")
    log.info("work %s merged into %s (%s): %s", source_work_id, canonical_work_id, reason, moved)
    return {"canonical_work_id": canonical_work_id, "merged_work_id": source_work_id, "moved": moved, "reason": reason}


def reconcile_identifiers() -> list[dict[str, Any]]:
    """Identifiers whose normalized form collides (Form 1120-S / 1120S) mark the same Work: normalize in place and
    merge the collisions through merge_work. Safe by construction — only identical canonical identifiers ever merge."""
    conn = db.connect()
    merges = []
    rows = [dict(r) for r in conn.execute("SELECT scheme, value, work_id, version_id FROM work_identifiers WHERE scheme='docnum'").fetchall()]
    by_norm: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        norm = "form-" + r["value"][5:].replace("-", "") if r["value"].startswith("form-") else r["value"]
        by_norm.setdefault(norm, []).append(r)
    for norm, group in by_norm.items():
        works_ = sorted({g["work_id"] for g in group}, key=lambda wid: (dict(conn.execute("SELECT created_at FROM works WHERE id=?", (wid,)).fetchone() or {"created_at": 0})["created_at"]))
        canonical = works_[0]
        for wid in works_[1:]:
            if get(wid) and get(canonical):
                merges.append(merge_work(wid, canonical, reason=f"identical canonical identifier docnum:{norm}"))
        for g in group:
            if g["value"] != norm:
                with db.tx() as c:
                    c.execute("DELETE FROM work_identifiers WHERE scheme='docnum' AND value=?", (g["value"],))
                    c.execute("INSERT OR IGNORE INTO work_identifiers (scheme, value, work_id, version_id) VALUES ('docnum', ?, ?, ?)", (norm, canonical, g["version_id"]))
        # titles keep their official punctuation (Form 1099-DIV); only the identifier is normalized
    return merges


def stats() -> dict[str, Any]:
    conn = db.connect()
    return {"works": conn.execute("SELECT COUNT(*) FROM works").fetchone()[0],
            "resolved": conn.execute("SELECT COUNT(*) FROM works WHERE resolution='resolved'").fetchone()[0],
            "versions": conn.execute("SELECT COUNT(*) FROM work_versions").fetchone()[0],
            "manifestations": conn.execute("SELECT COUNT(*) FROM work_manifestations").fetchone()[0],
            "owned": conn.execute("SELECT COUNT(*) FROM work_manifestations WHERE access='owned' AND relation IN ('manifestation_of','reprint_of','translation_of','revision_of')").fetchone()[0],
            "discussing": conn.execute("SELECT COUNT(*) FROM work_manifestations WHERE source_id IS NOT NULL AND relation NOT IN ('manifestation_of','reprint_of','translation_of','revision_of')").fetchone()[0],
            "possible": conn.execute("SELECT COUNT(*) FROM work_manifestations WHERE relation='possible_manifestation_of'").fetchone()[0]}


def list_works(project_id: str | None = None, q: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    conn = db.connect()
    if project_id:
        rows = conn.execute("SELECT w.*, pw.relevance, pw.reason FROM works w JOIN project_works pw ON pw.work_id=w.id WHERE pw.project_id=? ORDER BY pw.updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
    else:
        rows = conn.execute("SELECT w.*, NULL AS relevance, NULL AS reason FROM works w ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if q and q.lower() not in (d["title"] or "").lower():
            continue
        d["versions"] = versions_of(d["id"])
        ms = manifestations_of(d["id"])
        d["owned"] = sum(1 for m in ms if m["access"] == "owned" and m["relation"] in PRIMARY_RELATIONS)     # copies of the Work itself
        d["discussing"] = sum(1 for m in ms if m.get("source_id") and m["relation"] not in PRIMARY_RELATIONS)  # sources that quote / explain / cite it
        d["candidates"] = sum(1 for m in ms if m.get("candidate_id"))
        d["manifestations"] = len(ms)
        out.append(d)
    return out
