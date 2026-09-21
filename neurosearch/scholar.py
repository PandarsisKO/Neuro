"""Scholarly catalogues as a $0 discovery and resolution backend — Crossref and OpenAlex.

Why this exists. `discover` asks a model to propose sources from its own memory and then pays `discover.verify`
(with the web-search tool) to check whether the proposals are real. A catalogue query has nothing to hallucinate:
every record returned exists, has a DOI, and carries its own metadata. So this module makes Discover CHEAPER, not
dearer — it replaces a guess-then-verify round trip with one free HTTP request. It also closes the gap
`works.find_copy` has always reported as *"resolved identity, unresolved access"*: a citation the app could name but
not obtain now has a real chance of an open-access PDF, which goes into the corpus through the ordinary document
ingestion path.

What it is NOT. It is not evidence. A catalogue record is metadata, so records land in the Discovery Candidate Index
(`candidates`, explicitly never evidence) or as `discoveries`; only an open-access PDF the user chooses to acquire
becomes a source with retrievable text and locators. Nothing here attaches anything to a project on its own.

Boundaries. Every request goes through `safe_fetch` (the one fetch path) — no client library, no second boundary.
No model call is made anywhere in this module. `resources.classify` is extended rather than duplicated.

Providers, as measured 2026-09:
  · Crossref  — no account. `mailto=` earns the polite pool: 10 req/s single, 3 req/s list, 3 concurrent
                (limits tightened 2025-12-01). Authoritative DOI metadata and reference lists.
  · OpenAlex  — a free API key has been REQUIRED since 2026-02-13; the `mailto` parameter and the polite pool were
                retired for credit-based limits (100k credits/day free, a list query costs 10). Without a key you
                get 100 credits and then HTTP 409, so `available()` reports it off unless the key is present.
                Carries `best_oa_location.pdf_url` and `open_access.oa_url`, which is why it is worth a key.
Semantic Scholar is deliberately not implemented: it overlaps OpenAlex almost entirely, its unauthenticated search
endpoints fail in practice, and a key buys a guaranteed 1 req/s — the least new coverage for the most pacing.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from typing import Any, Callable

from .config import settings

log = logging.getLogger(__name__)

PROVIDERS = ("crossref", "openalex")
EVIDENCE_CLASS = "expert"          # peer-reviewed literature; knowledge.CLASSES member
SCHOLAR_CLASSES = ("expert", "authoritative")   # an evidence target asking for these is what makes a catalogue query worth running

# 2026-09-20 (Kyle): an "in-office vs. remote" workplace-policy target, tagged expert/authoritative like most
# ordinary business questions are, sent Crossref/OpenAlex a query with nothing academic about it and got back
# real, term-matched, useless records -- furniture-standards specs, a 1914 Scientific American piece on the
# patent office, a fisheries remote-sensing survey. All three share ordinary words ("office", "work", "needs",
# "remote") with the question and nothing else; measured against the actual observed junk, neither raising a
# token-overlap bar (claims.overlap) nor diluting it with the record's abstract moved the needle -- most
# Crossref records carry no abstract at all (confirmed against this exact case), and a short title has too
# little vocabulary for any lexical filter to tell "shares words" from "is about this". A model call could
# judge that, but this module's whole reason to exist is running the catalogue pass at $0 with no model call
# (see the module docstring; test_the_catalogue_pass_makes_no_model_call freezes it) -- so the fix has to be
# in WHETHER the query runs, not in grading what comes back. `preferred_classes` says the target wants EXPERT
# evidence in general -- a lawyer's opinion or an HR consultant's post both qualify. Only the question's own
# wording says whether that's the PEER-REVIEWED kind a scholarly catalogue actually carries, which is exactly
# what SCHOLAR_HINT already tests for the free-text `refine` path below -- so target_wants_literature() now
# requires it too, on the target's own question text.
SCHOLAR_HINT = re.compile(r"\b(paper|papers|study|studies|research|literature|journal|peer[- ]review(?:ed)?|"
                          r"meta[- ]analys[ei]s|trial|preprint|doi|academic|scholar(?:ly)?|citation|evidence base)\b", re.I)

CROSSREF_API = "https://api.crossref.org/works"
OPENALEX_API = "https://api.openalex.org/works"

MAX_ROWS = 25                      # never ask a catalogue for more than this in one query
ABSTRACT_CHARS = 1200
DEADLINE_S = 20.0

# Conservative floors, well inside each provider's published ceiling: one request at a time, paced. A catalogue is a
# free service and this app is a guest on it.
MIN_INTERVAL_S = {"crossref": 0.4, "openalex": 0.2}
_last_call: dict[str, float] = {}


class ScholarUnavailable(Exception):
    """A provider cannot be used right now — missing credential, blocked fetch, or a bad response. Callers degrade
    (Discover falls back to its model pass, `pursue` skips the catalogue step); nothing is ever silently empty."""

    def __init__(self, provider: str, reason: str, detail: str = "") -> None:
        super().__init__(f"{provider}: {reason}")
        self.provider, self.reason, self.detail = provider, reason, detail


# ------------------------------------------------------------------ availability (no network)

def contact_email() -> str | None:
    return (settings.scholar_email or "").strip() or None


def available() -> dict[str, dict[str, Any]]:
    """Which catalogues are usable, and the plain reason when one is not. Cheap: reads config, touches no network."""
    email = contact_email()
    out = {
        "crossref": {"ready": True, "why": f"polite pool as {email}" if email else
                     "public pool — set NEUROSEARCH_SCHOLAR_EMAIL to get the higher polite-pool limits"},
        "openalex": {"ready": bool(settings.openalex_api_key),
                     "why": "api key present" if settings.openalex_api_key else
                            "needs a free key in OPENALEX_API_KEY — since 2026-02-13 OpenAlex answers unkeyed callers "
                            "with 100 credits and then HTTP 409"},
    }
    return out


def ready_providers() -> list[str]:
    a = available()
    return [p for p in PROVIDERS if a[p]["ready"]]


# ------------------------------------------------------------------ the one fetch

def _pace(provider: str) -> None:
    gap = MIN_INTERVAL_S.get(provider, 0.5)
    last = _last_call.get(provider)
    if last is not None:
        wait = gap - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_call[provider] = time.monotonic()


def _get(provider: str, url: str, params: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    """One paced GET through safe_fetch, decoded as JSON. Raises ScholarUnavailable for every failure mode so a
    caller never has to tell 'nothing matched' apart from 'the catalogue is down'."""
    from . import safe_fetch as SF
    ua = f"NeuroSearch/1.0 (+https://github.com/; mailto:{contact_email()})" if contact_email() else "NeuroSearch/1.0"
    hdrs = {"Accept": "application/json", "User-Agent": ua, **(headers or {})}
    full = url + "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    _pace(provider)
    try:
        res = SF.safe_fetch(full, content_class="html", headers=hdrs, deadline_s=DEADLINE_S)
    except SF.FetchBlocked as e:
        raise ScholarUnavailable(provider, "fetch_blocked", getattr(e, "reason", "") or str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise ScholarUnavailable(provider, "unreachable", str(e)[:200]) from e
    status = res.status
    if status == 409 and provider == "openalex":
        raise ScholarUnavailable(provider, "credits_exhausted", "OpenAlex returned 409 — an unkeyed caller gets 100 credits, then this")
    if status == 429:
        raise ScholarUnavailable(provider, "rate_limited", "the catalogue asked us to slow down")
    if status >= 400:
        raise ScholarUnavailable(provider, "http_error", f"HTTP {status}")
    body = (res.body or b"").decode("utf-8", "replace")
    try:
        return json.loads(body)
    except ValueError as e:
        raise ScholarUnavailable(provider, "bad_json", body[:200]) from e


# ------------------------------------------------------------------ normalisation to ONE record shape

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")


def normalise_doi(text: str | None) -> str | None:
    if not text:
        return None
    m = DOI_RE.search(str(text).strip())
    return m.group(0).rstrip(".,;)").lower() if m else None


def _clean(s: Any, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()[:limit]


def _authors(names: list[str]) -> str:
    names = [n for n in names if n]
    if not names:
        return ""
    return names[0] if len(names) == 1 else f"{names[0]} et al."


def _record(*, provider: str, doi: str | None, title: str, abstract: str = "", authors: str = "", venue: str = "",
            year: Any = None, cited_by: Any = None, oa_pdf_url: str | None = None, landing: str | None = None,
            oa_status: str | None = None, copies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    url = (f"https://doi.org/{doi}" if doi else landing) or ""
    return {"provider": provider, "doi": doi, "external_id": doi or url, "url": url, "landing_url": landing,
            "title": _clean(title, 300) or "(untitled)", "abstract": _clean(abstract, ABSTRACT_CHARS),
            "creator": authors, "venue": _clean(venue, 160),
            "year": int(year) if isinstance(year, (int, float)) or (isinstance(year, str) and year.isdigit()) else None,
            "cited_by": int(cited_by) if isinstance(cited_by, (int, float)) else None,
            "oa_pdf_url": oa_pdf_url, "is_oa": bool(oa_pdf_url), "oa_status": oa_status,
            "copies": copies or [], "evidence_class": EVIDENCE_CLASS}


# ------------------------------------------------------------------ every legal copy, not just the "best" one (0.60.3)
#
# Kyle: *"many of these require a subscription. how do we handle that?"* The app already refuses to turn a closed
# paper into a source, which is right — but it was asking OpenAlex only for `best_oa_location`, and not even
# REQUESTING the `locations` array. For a paywalled journal article the publisher's own record is closed while a
# legally free accepted manuscript sits in a repository (arXiv, PubMed Central, an institutional repository), and
# that copy is in `locations`. So "the full text is not openly available" was sometimes the app not having looked.
#
# Nothing here circumvents anything: it reads the catalogue's own list of copies the publisher or author put in the
# open, prefers a direct PDF, and ranks a repository copy below the published version because an accepted
# manuscript can differ from the version of record — a difference `works.py` already models as a version
# relationship. A subscription copy is never fetched, and the user's own institutional access is theirs to use in
# their own browser (the extension's "Send this page"), never something this app drives.
COPY_KIND_ORDER = {"publisher": 0, "repository": 1, "other": 2}


def _copies(it: dict[str, Any]) -> list[dict[str, Any]]:
    """Every open copy OpenAlex lists, best first. `pdf_url` when there is one, else the landing page."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for loc in (it.get("locations") or []):
        if not isinstance(loc, dict) or not loc.get("is_oa"):
            continue
        src = loc.get("source") or {}
        kind = "publisher" if loc.get("is_published") or (src.get("type") == "journal" and not loc.get("is_accepted")) else \
               ("repository" if src.get("type") in ("repository", "ebook platform") or loc.get("is_accepted") else "other")
        url = loc.get("pdf_url") or loc.get("landing_page_url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "pdf": bool(loc.get("pdf_url")), "kind": kind,
                    "host": src.get("display_name") or "", "version": loc.get("version"),
                    "license": loc.get("license")})
    out.sort(key=lambda c: (COPY_KIND_ORDER.get(c["kind"], 3), 0 if c["pdf"] else 1))
    return out


def best_copy(rec: dict[str, Any]) -> dict[str, Any] | None:
    """The copy to ingest: a direct PDF first, whatever its host, then a landing page. `oa_pdf_url` stays the
    primary answer when the catalogue gave one — this only fills in what it left out."""
    if rec.get("oa_pdf_url"):
        return {"url": rec["oa_pdf_url"], "pdf": True, "kind": "publisher", "host": "", "version": None}
    for c in rec.get("copies") or []:
        if c.get("pdf"):
            return c
    return (rec.get("copies") or [None])[0]


def access(rec: dict[str, Any]) -> dict[str, Any]:
    """How this paper can be read, in plain words. `open` = we can ingest it now; `elsewhere` = a free copy exists
    away from the publisher; `closed` = metadata only, and the honest next step is the user's own access."""
    if rec.get("oa_pdf_url"):
        return {"state": "open", "why": "the publisher's own copy is open", "url": rec["oa_pdf_url"]}
    c = best_copy(rec)
    if c:
        where = c.get("host") or "a repository"
        return {"state": "elsewhere", "url": c["url"], "kind": c.get("kind"),
                "why": (f"the published version is closed, but a free copy is on {where}"
                        + ("" if c.get("kind") != "repository" else " — an accepted manuscript can differ from the "
                           "version of record")),
                "caution": "repository copy" if c.get("kind") == "repository" else None}
    return {"state": "closed", "url": rec.get("url") or rec.get("landing_url"),
            "why": "no free copy is listed anywhere the catalogue can see",
            "next": ("open it at the publisher — if you have access through a subscription or a library, the "
                     "browser extension can send the page into the project once you are reading it")}


def _from_crossref(it: dict[str, Any]) -> dict[str, Any]:
    names = [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in (it.get("author") or [])]
    parts = ((it.get("issued") or {}).get("date-parts") or [[None]])[0] or [None]
    # Crossref carries a PDF link only when the publisher registered one as full-text; application/pdf is the signal
    pdf = next((l.get("URL") for l in (it.get("link") or [])
                if str(l.get("content-type") or "").lower() == "application/pdf" and l.get("URL")), None)
    return _record(provider="crossref", doi=normalise_doi(it.get("DOI")), title=(it.get("title") or [""])[0],
                   abstract=it.get("abstract") or "", authors=_authors(names),
                   venue=(it.get("container-title") or [""])[0], year=parts[0],
                   cited_by=it.get("is-referenced-by-count"), oa_pdf_url=pdf, landing=it.get("URL"))


def _inverted_abstract(inv: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as an inverted index (word → positions) for licensing reasons; rebuild the text."""
    if not isinstance(inv, dict) or not inv:
        return ""
    at: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions or []:
            if isinstance(p, int):
                at[p] = word
    return " ".join(at[i] for i in sorted(at))


def _from_openalex(it: dict[str, Any]) -> dict[str, Any]:
    names = [((a.get("author") or {}).get("display_name")) for a in (it.get("authorships") or [])]
    best = it.get("best_oa_location") or {}
    oa = it.get("open_access") or {}
    pdf = best.get("pdf_url") or oa.get("oa_url")
    src = (it.get("primary_location") or {}).get("source") or {}
    return _record(provider="openalex", doi=normalise_doi(it.get("doi")), title=it.get("display_name") or it.get("title") or "",
                   abstract=_inverted_abstract(it.get("abstract_inverted_index")), authors=_authors(names),
                   venue=src.get("display_name") or "", year=it.get("publication_year"),
                   cited_by=it.get("cited_by_count"), oa_pdf_url=pdf, landing=it.get("id"),
                   oa_status=oa.get("oa_status"), copies=_copies(it))


# ------------------------------------------------------------------ search

OPENALEX_FIELDS = ("id,doi,display_name,publication_year,cited_by_count,authorships,primary_location,best_oa_location,"
                   "locations,open_access,abstract_inverted_index")     # `locations` added 0.60.3: every open copy
CROSSREF_FIELDS = "DOI,title,abstract,author,container-title,issued,is-referenced-by-count,link,URL"


def search(query: str, limit: int = 10, provider: str | None = None, *, open_access_only: bool = False) -> list[dict[str, Any]]:
    """Records matching `query`, newest-relevance first as the catalogue ranks them. Tries each ready provider in
    order and returns the first that answers; a provider that fails raises only if NONE could answer."""
    q = _clean(query, 300)
    if not q:
        return []
    rows = max(1, min(int(limit or 10), MAX_ROWS))
    chosen = [provider] if provider else ready_providers()
    if not chosen:
        raise ScholarUnavailable("scholar", "no_provider", "; ".join(f"{p}: {v['why']}" for p, v in available().items()))
    problems: list[str] = []
    only = len(chosen) == 1        # a caller who named one provider wants THAT provider's reason, not a summary
    for p in chosen:
        try:
            if p == "crossref":
                data = _get(p, CROSSREF_API, {"query.bibliographic": q, "rows": rows, "select": CROSSREF_FIELDS,
                                              "sort": "relevance", "mailto": contact_email()})
                items = ((data or {}).get("message") or {}).get("items") or []
                recs = [_from_crossref(it) for it in items]
            else:
                params: dict[str, Any] = {"search": q, "per-page": rows, "select": OPENALEX_FIELDS,
                                          "api_key": settings.openalex_api_key}
                if open_access_only:
                    params["filter"] = "is_oa:true"
                data = _get(p, OPENALEX_API, params)
                recs = [_from_openalex(it) for it in ((data or {}).get("results") or [])]
            recs = [r for r in recs if r["title"] != "(untitled)" and r["url"]]
            if open_access_only:
                recs = [r for r in recs if r["oa_pdf_url"]]
            return recs
        except ScholarUnavailable as e:
            log.warning("scholar search via %s failed: %s", p, e)
            if only:
                raise
            problems.append(f"{p}: {e.reason}")
    raise ScholarUnavailable("scholar", "all_providers_failed", "; ".join(problems))


def resolve_doi(doi: str) -> dict[str, Any] | None:
    """One DOI → one record, merging what each catalogue is best at: Crossref for authoritative metadata, OpenAlex
    for whether a free copy exists. This is what turns `works.find_copy`'s 'resolved identity, unresolved access'
    into an obtainable PDF."""
    d = normalise_doi(doi)
    if not d:
        return None
    rec: dict[str, Any] | None = None
    try:
        data = _get("crossref", f"{CROSSREF_API}/{urllib.parse.quote(d)}", {"mailto": contact_email()})
        msg = (data or {}).get("message")
        if isinstance(msg, dict):
            rec = _from_crossref(msg)
    except ScholarUnavailable as e:
        log.info("crossref could not resolve %s: %s", d, e.reason)
    if settings.openalex_api_key:
        try:
            data = _get("openalex", f"{OPENALEX_API}/doi:{urllib.parse.quote(d)}",
                        {"select": OPENALEX_FIELDS, "api_key": settings.openalex_api_key})
            if isinstance(data, dict) and (data.get("id") or data.get("doi")):
                oa = _from_openalex(data)
                if rec is None:
                    rec = oa
                else:                                   # keep Crossref's metadata, take OpenAlex's access answer
                    for k in ("oa_pdf_url", "is_oa", "oa_status"):
                        if oa.get(k):
                            rec[k] = oa[k]
                    rec["abstract"] = rec["abstract"] or oa["abstract"]
        except ScholarUnavailable as e:
            log.info("openalex could not resolve %s: %s", d, e.reason)
    return rec


# ------------------------------------------------------------------ FM1: one work's own bibliography ($0)

def fetch_crossref_references(doi: str) -> dict[str, Any]:
    """FM1 (Field Map) only -- not part of ordinary Scholar discovery. One paced, UNFILTERED singleton retrieval of
    a Crossref work record through the same `_get`/ScholarUnavailable boundary `resolve_doi` uses, returning its raw
    `reference` list (a paper's own outbound bibliography) alongside the doi/title asked for.

    Deliberately does NOT pass a `select` parameter: Crossref's public docs describe `reference` as a selectable
    field, but this environment has no network route to verify that against the live API, so this asks for the full
    record instead of depending on an unverified `select=reference`. Deliberately does NOT touch `CROSSREF_FIELDS` --
    that constant is the general Scholar discovery path (`search`, `resolve_doi`'s field list) and stays lean; every
    ordinary discovery request is unaffected by this function's existence.

    Raises ScholarUnavailable exactly like `_get` does (fetch blocked, rate limited, bad response, ...) -- callers
    that want to keep going after a single seed fails should catch it themselves; this never returns an empty
    result to paper over a fetch failure.
    """
    d = normalise_doi(doi)
    if not d:
        return {"doi": None, "title": "", "has_reference_field": False, "raw_references": []}
    data = _get("crossref", f"{CROSSREF_API}/{urllib.parse.quote(d)}", {"mailto": contact_email()})
    msg = (data or {}).get("message")
    if not isinstance(msg, dict):
        return {"doi": d, "title": "", "has_reference_field": False, "raw_references": []}
    title = _clean(" ".join(msg.get("title") or []))
    has_field = "reference" in msg
    refs = msg.get("reference")
    return {"doi": d, "title": title, "has_reference_field": has_field, "raw_references": refs if isinstance(refs, list) else []}


# ------------------------------------------------------------------ where records go (never evidence)

def why(rec: dict[str, Any]) -> str:
    bits = [b for b in (rec["creator"], rec["venue"], str(rec["year"]) if rec["year"] else "") if b]
    tail = f" · cited {rec['cited_by']}×" if rec.get("cited_by") else ""
    return (" · ".join(bits) + tail).strip(" ·") or rec["provider"]


def to_candidates(records: list[dict[str, Any]], project_id: str | None, origin: dict[str, Any]) -> list[str]:
    """Remember records in the Discovery Candidate Index — seen, not acquired. One platform per catalogue so the
    provenance of a candidate is never guessed."""
    from . import candidates
    ids: list[str] = []
    for prov in PROVIDERS:
        batch = [r for r in records if r["provider"] == prov and r["external_id"]]
        if not batch:
            continue
        ids += candidates.remember(
            # `url` is what an Acquire click ingests, so it is the free PDF when one exists and the DOI landing page
            # otherwise; `canonical_url` is always the DOI, which is the record's identity whatever its access.
            [{"external_id": r["external_id"], "url": (access(r).get("url") if access(r)["state"] != "closed"
                                                       else r["url"]), "title": r["title"],
              "description": ((r["abstract"] or why(r)) + _access_note(r))[:2000],
              "creator": r["creator"], "canonical_url": r["url"]} for r in batch],
            platform=prov, project_id=project_id, origin=origin)
    return ids


def _access_note(rec: dict[str, Any]) -> str:
    a = access(rec)
    if a["state"] == "open":
        return ""
    if a["state"] == "elsewhere":
        return f"  [{a['why']}]"
    return ("  [metadata only — no open copy is listed, so acquiring this would fetch a paywalled landing page "
            "rather than the paper; open it at the publisher and use the browser extension if you have access]")


def to_discoveries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Discover's item shape. `fit` is deliberately conservative (3, or 4 when a free full text exists): the
    catalogue ranked these for term relevance, which is not the same as fit to the project, and inventing a
    confident score from a relevance rank would be exactly the kind of made-up number this app refuses."""
    out = []
    for r in records:
        a = access(r)
        # a free copy away from the publisher is still a copy we can read: fit 4, with the caution said out loud
        angle = {"open": "open access — the full text can be read now",
                 "elsewhere": a["why"],
                 "closed": "metadata only — no free copy is listed anywhere"}[a["state"]]
        out.append({"name": r["title"][:120], "kind": "paper",
                    "url": a["url"] if a["state"] != "closed" else r["url"],
                    "known_for": (r["venue"] or r["provider"])[:80], "why": why(r)[:300],
                    "angle": angle[:160], "start_with": [],
                    "fit": 4 if a["state"] in ("open", "elsewhere") else 3, "depth": "",
                    "access": a["state"], "verified_by": r["provider"], "doi": r["doi"]})
    return out


def acquire(record: dict[str, Any], project_id: str, *, lane: str = "low") -> dict[str, Any]:
    """Queue the open-access PDF for ordinary ingestion. No new ingestion path: the PDF goes through `ingest_url`
    exactly like any other document, so chunking, embeddings, page locators and findings all behave as usual."""
    from . import db
    a = access(record)
    if a["state"] == "closed":
        return {"queued": False, "why": a["why"], "next": a.get("next"), "access": "closed"}
    job = db.create_job("ingest_url", {"project_id": project_id, "url": a["url"],
                                       "title": record["title"], "origin": f"scholar:{record['provider']}",
                                       "doi": record.get("doi")}, lane=lane)
    return {"queued": True, "job_id": job["id"] if isinstance(job, dict) else job, "url": a["url"],
            "access": a["state"], "caution": a.get("caution"), "why": a["why"]}


# ------------------------------------------------------------------ gap-first: does this target want literature?

def target_wants_literature(target: dict[str, Any]) -> bool:
    """An evidence target already declares the classes it needs (`knowledge.CLASSES`); that used to be the whole
    test. It is necessary but not sufficient: the class says the target wants EXPERT (or AUTHORITATIVE) evidence
    in general, and most "expert" business questions want a practitioner's opinion, not a peer-reviewed paper --
    Crossref/OpenAlex can only ever supply the latter. So a catalogue query is worth a request only when BOTH the
    class fits AND the target's own question reads like something a scholarly catalogue could plausibly answer
    (SCHOLAR_HINT) — which is what keeps this from bolting an academic search onto an ordinary workplace-policy
    or editing-workflow question that only happens to be tagged "expert"."""
    want = target.get("preferred_classes")
    if isinstance(want, str):
        try:
            want = json.loads(want)
        except ValueError:
            want = [want]
    if not (set(w for w in (want or []) if isinstance(w, str)) & set(SCHOLAR_CLASSES)):
        return False
    return bool(SCHOLAR_HINT.search(str(target.get("question") or "")))


def _wants_literature_why(target: dict[str, Any]) -> str:
    """Same two-part test as target_wants_literature(), but says which half failed -- 'not asking for expert
    evidence' and 'asking for expert evidence, but not about literature' are different situations and the UI
    ('already checked') should be able to say which one this was."""
    want = target.get("preferred_classes")
    if isinstance(want, str):
        try:
            want = json.loads(want)
        except ValueError:
            want = [want]
    classes = [w for w in (want or []) if isinstance(w, str)]
    if not (set(classes) & set(SCHOLAR_CLASSES)):
        return (f"this target asks for {', '.join(classes) or 'no particular class'} evidence — scholarly "
                f"catalogues are only queried for expert or authoritative targets")
    return ("this target asks for expert/authoritative evidence, but its question doesn't read like a literature "
            "question (no paper/study/research-type wording) — scholarly catalogues only carry peer-reviewed "
            "literature, not practitioner opinion, so they wouldn't have anything for it")


def for_target(target: dict[str, Any], project_id: str, limit: int = 8,
               progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """The gap-first step: query the catalogues with the open question itself, remember what comes back as
    candidates, and link each one to the target it might close. $0, no model call, and it runs before the paid
    external Discover job rather than instead of the user's judgement."""
    from . import candidates
    q = _clean(target.get("question") or "", 300)
    if not q:
        return {"run": False, "why": "the target has no question text"}
    if not target_wants_literature(target):
        return {"run": False, "why": _wants_literature_why(target)}
    try:
        recs = search(q, limit=limit)
    except ScholarUnavailable as e:
        return {"run": False, "why": f"catalogue unavailable ({e.reason})", "detail": e.detail}
    if progress:
        progress(f"{len(recs)} catalogue records for “{q[:60]}”")
    ids = to_candidates(recs, project_id, origin={"kind": "evidence_target", "ref": target.get("id"), "query": q})
    for cid, rec in zip(ids, recs):
        candidates.link(cid, project_id, "evidence_target", str(target.get("id")),
                        relevance=70 if rec["oa_pdf_url"] else 50,
                        why=f"catalogue match for the open question: {q[:120]}")
    return {"run": True, "found": len(recs), "candidates": len(ids),
            "open_access": sum(1 for r in recs if r["oa_pdf_url"]),
            "records": [{"title": r["title"], "doi": r["doi"], "url": r["url"], "why": why(r),
                         "oa_pdf_url": r["oa_pdf_url"]} for r in recs]}
