"""Mission BOOTSTRAP R2 — a new project starts with what Neuro Search already owns.

    NAME + GOAL → cheap query expansion ($0) → library.recall per query → merge → bands → project_reuse

This module is deliberately thin. The retrieval it needs already exists and is already correct: `library.recall`
does chunk-level FTS + vector recall over the sources a project does NOT have, keeps a five-minute passage inside
a three-hour interview recoverable (baseline topic vectors, never a source-averaged embedding), and returns the
matching passages with timestamps and deep links. What was missing was a caller.

Three properties are load-bearing and every change here must preserve them:

  * **No generation call, ever.** Query expansion is deterministic — the goal, its clauses, and the project's
    starting questions. The only spend is one query *embedding* per search (fractions of a cent, the same call
    every search in the product already makes); nothing here reaches a generation model, because a bootstrap that
    costs real money to look at your own library defeats the point of having the library. A goal too short to
    expand is reported as such rather than padded by a model guessing at the user's intent.
  * **The reason is a passage, not an adjective.** `why` is built from the chunks that actually matched, so the
    user can click it and check. "Highly relevant to your goal" is what you get when you ask a model to explain a
    retrieval it did not perform.
  * **Nothing is attached.** A scan writes `project_reuse` rows in state 'suggested' and nothing else. Attaching
    is `project_sources`, and it is the user's decision (or an explicit, visible, undoable high-confidence band).

Findings and Claims are NOT surfaced here. That is not an omission: a finding is an interpretation written
against another project's brief (`project_notes.brief_revision` proves the schema already knows it), and copying
it across a boundary imports the old framing with the fact. The portable layer is evidence, and evidence already
points at global sources. See BOOTSTRAP-MISSION.md §B2.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from . import db, library

log = logging.getLogger(__name__)

MAX_QUERIES = 14         # bounded $0 recalls, chosen by distinctiveness (S91); at most MAX_GAP_QUERIES from open gaps
MAX_GAP_QUERIES = 3      # S91: evidence targets used to take half the budget and, on a young project, they are all
                         # from whichever source landed first (three Points Guy card targets on a wealth project)
PER_QUERY = 14
MIN_GOAL_TOKENS = 3      # the whole goal must say at least this much before anything is searched
MIN_QUERY_TOKENS = 2     # S91: was 3, which threw away "Business ownership", "real estate", "Mortgage strategy",
                         # "Emergency reserves" — the two-word facets ARE the subjects. Distinctiveness ranking and
                         # the anchor rule (ANCHOR_MIN_TERMS = 2) now guard against the noise the 3 was for.
STRONG_QUERIES = 2       # matched by two independent queries = strong
STRONG_COVERAGE = 0.6    # or one query whose terms are mostly covered by real passages
KEEP = 60                # the most sources a scan will suggest; the rest are honestly reported as "not shown"

_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "that", "this", "my", "me", "i",
         "is", "are", "be", "can", "so", "it", "as", "at", "by", "from", "how", "what", "want", "would", "should",
         "help", "helps", "get", "make", "build", "better", "more", "new", "use", "using", "about"}


_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_MD_INLINE = re.compile(r"[*_`>]+")


def _plain(text: str) -> str:
    """S91: a brief is written in markdown. `# Generational Wealth Project Brief` is a label, not a facet of the
    goal, and it was the first thing the scan searched for (rarest word: "brief", 91 sources). Headings are dropped,
    bullets and emphasis are stripped, so what is left is what the person actually said."""
    out = []
    for line in (text or "").splitlines():
        if _MD_HEADING.match(line):
            continue
        line = _MD_BULLET.sub("", line)
        out.append(_MD_INLINE.sub(" ", line))
    return "\n".join(out)


def _clauses(text: str) -> list[str]:
    """A goal, broken into the facets worth searching separately. A long sentence is REPLACED by its parts, not
    accompanied by them: the whole goal as one query is a poor retrieval query (every extra term raises the
    coverage denominator and pushes good passages under the floor), and keeping both would also make every hit
    look like it "matched 2 parts of your goal" when it matched one idea twice."""
    out: list[str] = []
    for sent in re.split(r"[.!?\n]+", _plain(text)):
        sent = " ".join(sent.split())
        if not sent:
            continue
        parts = [p.strip() for p in re.split(r"[,;]| and (?=\w)| so (?:that |i |we )", sent)]
        parts = [p for p in parts if len(_content_tokens(p)) >= MIN_QUERY_TOKENS]
        out += parts if len(parts) >= 2 else ([sent] if len(_content_tokens(sent)) >= MIN_QUERY_TOKENS else [])
    return out


def _content_tokens(q: str) -> set[str]:
    """0.60.2: two characters, not three — same fix as `library._tokens`, and for the same reason: "ux", "ui",
    "ai" and "qa" are the words that identify a field, and dropping them made a goal about AI UI/UX design
    unrecognisable to the scan that was meant to search for it."""
    from .library import _tokens
    return _tokens(q or "")


def queries_for(project: dict[str, Any], targets: list[dict[str, Any]] | None = None) -> list[str]:
    """Bounded searches from open gaps, goal/brief facets, starting questions and tags.
    Deduplicated by content tokens — two phrasings of one idea must not spend two recalls."""
    goal = (project.get("goal") or "").strip()
    brief = (project.get("brief") or "").strip()
    # a goal that is only a couple of words ("Buy a business.") is too short to search from — say so rather than
    # guess; the 2-word floor below is for FACETS of a goal that says more, never for the whole of it
    if len(_content_tokens(" ".join([goal, brief, *(project.get("questions") or []), *map(str, project.get("tags") or [])]))) < MIN_GOAL_TOKENS:
        return []
    # Reserve half the bounded search budget for current gaps; keep the full question
    # so clause splitting cannot turn a domain-specific gap into a generic fragment.
    gaps = [t["question"] for t in (targets or []) if t.get("status") == "open" and t.get("question")]
    gaps = [q for q in gaps if len(_content_tokens(q)) >= MIN_QUERY_TOKENS][:MAX_GAP_QUERIES]
    goal_parts, brief_parts = _clauses(goal), _clauses(brief)
    cands = list(gaps)
    for i in range(max(len(goal_parts), len(brief_parts))):
        if i < len(goal_parts):
            cands.append(goal_parts[i])
        if i < len(brief_parts):
            cands.append(brief_parts[i])
    cands += [q for q in (project.get("questions") or []) if q]
    # 0.60.2 (Kyle: "global library is useful but only if its utilizing the projects criteria/brief/tags/chat").
    # Tags are the cheapest of those and were simply never read: a project tagged "ux, design systems" said so
    # explicitly and the scan searched only the goal sentence. Chat and the research state are a separate decision
    # (RECALL-RUNG.md) because they change what a $0 scan costs and when it can run.
    tags = [str(t).strip() for t in (project.get("tags") or []) if str(t).strip()]
    if tags:
        cands.append(" ".join(tags[:6]))
    picked: list[str] = []
    seen: list[set[str]] = []
    for c in cands:
        c = " ".join(str(c).split())
        toks = _content_tokens(c)
        if len(toks) < MIN_QUERY_TOKENS:
            continue
        if any(toks == s or toks < s for s in seen):     # identical, or wholly contained in one we already run
            continue
        picked.append(c)
        seen.append(toks)
    return _most_distinctive(picked, keep=set(gaps))


def _most_distinctive(cands: list[str], keep: set[str] | None = None) -> list[str]:
    """S91 (Kyle, 2026-09-24: Hormozi videos from his business project never surfaced for the wealth project). The
    scan took the first MAX_QUERIES clauses in DOCUMENT ORDER — the brief's heading, a mangled first sentence and
    one real facet — and never reached "investing and tax-advantaged accounts", "estate planning, trusts", "teaching
    our children financial literacy" further down. Every clause is now weighed the way `query_strength` weighs it
    (how many sources hold its rarest known word) and the most distinctive ones are searched; a clause made only of
    words the whole library uses is not searched at all. Gap questions keep their place ahead of the goal's own
    clauses, but only up to MAX_GAP_QUERIES of them."""
    if len(cands) <= MAX_QUERIES:
        return cands
    keep = keep or set()
    floor = DISTINCTIVE_SHARE * max(1, db.sources_with_chunks())
    scored: list[tuple[int, float, str]] = []
    for i, q in enumerate(cands):
        try:
            a = library.query_anchor(_content_tokens(q))
        except Exception:  # noqa: BLE001 — never let scoring stop a scan; fall back to document order
            return cands[:MAX_QUERIES]
        n = a.get("sources") if a.get("term") else None
        if n is None and (a.get("too_common") or a.get("all_generic")) and q not in keep:
            continue                                        # cannot discriminate: not worth one of the recalls (a gap question is kept as before)
        # Distinctive but PRESENT wins. Rarest-first picked "responsible stewardship" and "Multi-generational
        # trusts" (2-3 sources each, nothing to find) over "IRAs and Roth strategies" (26). Tiers: a gap question
        # first; then an anchor under the generic floor with at least MIN_USEFUL_SOURCES behind it, more sources
        # first; then the ultra-rare; then the generic-leaning (query_strength will mark those weak anyway).
        if q in keep:
            tier, key = 0, 0.0
        elif n is None:
            tier, key = 2, 0.0
        elif n >= MIN_USEFUL_SOURCES and n <= floor:
            tier, key = 1, -float(n)
        elif n < MIN_USEFUL_SOURCES:
            tier, key = 2, -float(n)
        else:
            tier, key = 3, float(n)
        scored.append((tier, key, q))
    scored.sort(key=lambda t: (t[0], t[1], cands.index(t[2])))
    # A few slots are held for the BROADEST facets of the goal ("net worth tracking", "passive income": common in a
    # finance library, but this project's actual subject). Their matches reach the card as "generic matches" behind
    # one click, which is how Kyle's 46 Hormozi videos can surface for a wealth project at all.
    sharp = [t for t in scored if t[0] < 3][:MAX_QUERIES - MAX_BROAD_QUERIES]
    broad = [t for t in scored if t[0] == 3]
    chosen = [q for _, _, q in (sharp + broad)[:MAX_QUERIES]]
    return sorted(chosen, key=cands.index)                # searched in the order the person wrote them


# 0.60.5 — a stored judgement has to know what made it.
#
# 0.60.2 changed how library recall decides relevance (two-letter terms count, the query's rarest word must appear,
# `strong` needs one passage rather than three), and it worked: on Kyle's corpus the same query went from 66
# matches to 25 and from 8 "strong" to 1. But the suggestions on his screen had been WRITTEN by the old matcher and
# were still there afterwards — the Airbnb video was still offered as the project's strong match, pre-ticked, an
# hour after the fix shipped. A recall change is a change to a stored opinion, and the opinion has to carry its
# provenance the same way every AI artifact in this codebase already does.
#
# Bump this string whenever the matcher's decisions change. Rows from an older version are reported as stale and
# never pre-ticked; they are not deleted, because the user may already have decided on them.
SCAN_VERSION = "recall-3"        # recall-1 = before 0.60.2 (3-char tokens, union coverage, no anchor)


# 0.61.0 — A CLAUSE MADE ONLY OF GENERIC WORDS CANNOT DISCRIMINATE, AND MUST NOT PRODUCE A "STRONG" MATCH.
#
# 0.60.2 fixed the matcher and the Airbnb video came back anyway. Measured on Kyle's live corpus (1,229 sources
# with chunks), his goal splits into six clauses, and their most distinctive words are:
#
#     "when auditing an existing one"                       auditing      15 sources
#     "reducing cognitive load"                             cognitive     16
#     "A reusable product-design framework for evaluating"  reusable      28
#     "It should include guidance for information architecture"  architecture  38
#     "improving complex web applications"                  improving     85
#     "…useful both when designing a new application"       designing    125
#
# The bad matches all come from the last two. Those clauses are made entirely of generic English — a video about
# Airbnb income really does talk about improving things and designing things — so no matcher working on those words
# can tell a UX source from a business source. And rarity alone cannot separate them from a real anchor: `improving`
# is in 6.9% of the library, `ux` in 5.2%. Nearly the same number, opposite usefulness.
#
# So the fault is in the QUERY, not in the matcher, and the fix belongs here: a query whose rarest word is in the
# upper half of THIS GOAL'S OWN rarity spread cannot separate topics, so it may contribute a `possible` match and
# never a `strong` one, and a source that matched nothing else is held back from the card with the reason stated.
# Relative to the goal, not an absolute cut — the same self-calibrating shape as `CREATOR_PROVEN_QUANTILE`, and for
# the same reason: 85 sources is generic in a 1,229-source library and distinctive in a 90-source one.
WEAK_QUERY_QUANTILE = 0.5        # a query is weak if its rarest term is rarer than fewer than half the others'
# S91: the median is a RELATIVE judgement, and it assumed a mix. Once the queries are chosen for distinctiveness
# (_most_distinctive) the median of seven rarities was 8 sources, and "IRAs and Roth strategies" — Roth in 26 of
# 1,590 sources — was declared generic and its matches hidden. A word in fewer than this share of the library is
# distinctive whatever its neighbours look like; the median can only raise the bar above it, never lower it.
DISTINCTIVE_SHARE = 0.02
MIN_USEFUL_SOURCES = 4           # an anchor in fewer sources than this has almost nothing to retrieve
MAX_BROAD_QUERIES = 3            # slots kept for the goal's broadest facets (above the generic line, closest to it first)
MIN_QUERIES_TO_RANK = 3          # with one or two queries there is no distribution to compare against


def _recall_without_anchor(project_id: str, q: str, first: dict[str, Any], project: dict[str, Any]) -> dict[str, Any] | None:
    term = (first.get("anchor") or {}).get("term")
    if not term:
        return None
    rest = [w for w in q.split() if _content_tokens(w) and term not in _content_tokens(w)]
    if len(_content_tokens(" ".join(rest))) < ANCHOR_RETRY_MIN_TOKENS:
        return None
    q2 = " ".join(rest)
    try:
        r2 = library.recall(project_id, q2, limit=PER_QUERY, want_enrichment=False,
                            reason=f"project bootstrap (without '{term}'): {(project.get('goal') or project.get('name') or '')[:100]}")
    except Exception as e:  # noqa: BLE001
        log.warning("bootstrap: retry recall failed for %r: %s", q2[:60], e)
        return None
    a2 = r2.get("anchor") or {}
    if a2.get("all_generic") or a2.get("too_common") or not r2.get("suggestions"):
        return None
    r2["retried_without"] = term
    return r2


ANCHOR_RETRY_MIN_TOKENS = 2      # "tax planning" is a phrase worth one recall; a single word is not


def query_strength(queries: list[str]) -> dict[str, Any]:
    """Which of these queries can actually separate one topic from another, judged against each other.

    Returns `rarity` (query -> how many sources hold its rarest known word), `weak` (the queries that cannot
    discriminate) and the cut, so the decision is inspectable rather than a hidden constant."""
    rarity: dict[str, int | None] = {}
    too_common: list[str] = []
    for q in queries:
        a = library.query_anchor(_content_tokens(q))
        if a.get("term"):
            rarity[q] = a.get("sources")
        else:
            rarity[q] = None
            # the one no-anchor case that condemns the QUERY: every word in it is everywhere. The other cases
            # ("appears in too few sources", "too few terms") mean the opposite — a very rare word — and must not
            # be treated as generic.
            # `all_generic` (0.62.0) is the same verdict by another route: every word in the search is a modifier,
            # so it names no subject. Both mean "this query cannot discriminate"; neither means "a rare word".
            if a.get("too_common") or a.get("all_generic"):
                too_common.append(q)
    known = [n for n in rarity.values() if n]
    weak = list(too_common)
    cut = None
    if len(known) >= MIN_QUERIES_TO_RANK:
        import statistics
        cut = statistics.median(known)
        floor = DISTINCTIVE_SHARE * max(1, db.sources_with_chunks())
        cut = max(cut, floor)
        weak += [q for q, n in rarity.items() if n is not None and n > cut]
    note = ""
    if too_common:
        note = (f"{len(too_common)} of these searches are made only of words most of your library uses, so they "
                "cannot tell one subject from another")
    if cut is not None:
        note = ((note + "; ") if note else "") + (
            f"a search whose rarest word appears in more than {int(cut)} of your sources is generic for this goal, "
            "so its matches are excluded from project suggestions")
    return {"rarity": rarity, "weak": sorted(set(weak)), "cut": cut, "too_common": too_common,
            "note": note or "too few searches to tell a distinctive one from a generic one"}


def _band(hit: dict[str, Any]) -> str:
    """0.60.2: `strong` now needs ONE passage that clears the bar, not a union across three.

    Kyle's first screenshot of this card offered "How To Make $3,000/mo From Airbnb With $0" as the single strong
    match for a project about AI-assisted UI/UX design. Two queries matching, or 0.6 of the terms appearing
    somewhere among three passages, is a low bar in a library of 1,219 sources about other subjects — and calling
    it "strong" is the part that misleads, because it is the row the card pre-ticks."""
    passage = hit.get("passage_coverage")
    strong_passage = passage is None or passage >= STRONG_COVERAGE     # None = an older row without the measure
    if not strong_passage:
        return "possible"
    # 0.61.0: and it has to have matched a query that could tell topics apart. S91: a query that only matched after
    # its anchor word was dropped ("property insurance" for "Property and casualty insurance") is not that query,
    # so on its own it makes a "possible", never a "strong" — the row the card pre-ticks.
    if hit.get("retried_queries") and not hit.get("distinctive_queries"):
        return "possible"
    if hit.get("distinctive_queries") is not None and not hit["distinctive_queries"]:
        return "possible"
    return "strong" if (len(hit["queries"]) >= STRONG_QUERIES or hit["coverage"] >= STRONG_COVERAGE) else "possible"


def _open_targets(project_id: str) -> list[dict[str, Any]]:
    from . import knowledge
    return sorted(knowledge.list_targets(project_id, status="open"),
                  key=lambda t: (t.get("origin") != "user", -float(t.get("updated_at") or 0), t["id"]))


def _target_revision(targets: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps([(t["id"], t["question"], t.get("updated_at")) for t in targets],
                                     sort_keys=True).encode()).hexdigest()


def scan(project_id: str, progress: Any = None) -> dict[str, Any]:
    """Run the bootstrap scan and persist its suggestions. Pure recall + bookkeeping: no generation call, no
    writes to `project_sources`, no writes to any other project."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError("no such project")
    targets = _open_targets(project_id)
    qs = queries_for(project, targets)
    brev = db.brief_revision(project_id)
    if not qs:
        db.retire_project_reuse(project_id, [])
        db.record_bootstrap_run(project_id, {"queries": [], "scanned": 0, "found": 0, "target_revision": _target_revision(targets),
                                              "reason": "the goal is too short to search from"}, brev)
        return {"queries": [], "sources": [], "projects": [], "found": 0, "scope": 0,
                "note": "Tell Neuro Search a little more about the goal and it can search your library for it."}

    strength = query_strength(qs)
    weak_qs = set(strength["weak"])
    merged: dict[str, dict[str, Any]] = {}
    scope = 0
    for i, q in enumerate(qs):
        if progress:
            progress(0.05 + 0.75 * (i / len(qs)), f"searching what you already own · {i + 1} of {len(qs)} · \"{q[:48]}\"")
        try:
            r = library.recall(project_id, q, limit=PER_QUERY, want_enrichment=False,
                               reason=f"project bootstrap: {(project.get('goal') or project.get('name') or '')[:100]}")
        except Exception as e:  # noqa: BLE001 — one bad query must never cost the whole scan
            log.warning("bootstrap: recall failed for %r: %s", q[:60], e)
            continue
        scope = max(scope, int(r.get("scope") or 0))
        # Generic-only recall is diagnostic, not a source recommendation. Never let
        # its scores or passage coverage promote a separate, weaker subject match.
        if q in weak_qs or (r.get("anchor") or {}).get("all_generic") or (r.get("anchor") or {}).get("too_common"):
            continue
        # S91: the anchor rule wants the query's RAREST word in the passage, and in a facet like "Multi-year tax
        # planning" or "Two-person credit card strategies" the rarest word is the incidental modifier, not the
        # subject — so 7 of Kyle's 10 well-chosen queries returned nothing. When a distinctive query finds nothing,
        # it is searched once more without that word ("tax planning", "credit card strategies"): the next-rarest
        # word anchors instead. One extra $0 recall, only on an empty result, never on a generic query.
        if not r.get("suggestions"):
            r = _recall_without_anchor(project_id, q, r, project) or r
        for s in r["suggestions"]:
            m = merged.setdefault(s["source_id"], {
                "source_id": s["source_id"], "title": s.get("title"), "channel": s.get("channel"),
                "platform": s.get("platform"), "url": s.get("url"), "published_at": s.get("published_at"),
                "score": 0.0, "coverage": 0.0, "passage_coverage": 0.0, "queries": [], "distinctive_queries": [],
                "passages": [], "terms": [],
            })
            m["score"] = round(max(m["score"], s["score"]), 4)
            m["coverage"] = max(m["coverage"], s.get("coverage") or 0.0)
            m["passage_coverage"] = max(m["passage_coverage"], s.get("passage_coverage") or 0.0)
            m["queries"].append(q)
            if q not in weak_qs and not r.get("retried_without"):
                m["distinctive_queries"].append(q)       # a shortened retry can suggest, never make a hit "strong" on its own
            if r.get("retried_without"):
                m.setdefault("retried_queries", []).append(q)
            m["terms"] = sorted(set(m["terms"]) | set(s.get("covered_terms") or []))
            for c in (s.get("chunks") or [])[:2]:
                if len(m["passages"]) < 4 and not any(p["chunk_id"] == c["chunk_id"] for p in m["passages"]):
                    m["passages"].append(c)

    hits = sorted(merged.values(), key=lambda h: (-len(h["queries"]), -h["score"]))
    total_found = len(hits)
    hits = hits[:KEEP]
    if progress:
        progress(0.85, f"grouping {total_found} match{'' if total_found == 1 else 'es'}")

    rows = []
    for h in hits:
        h["band"] = _band(h)
        h["weak_query_only"] = bool(h["queries"]) and not h["distinctive_queries"] and not h.get("retried_queries")
        h["why"] = _why(h)
        rows.append({"object_kind": "source", "object_id": h["source_id"], "band": h["band"], "score": h["score"],
                     "why": json.dumps({"passages": h["passages"], "terms": h["terms"], "coverage": h["coverage"],
                                        "weak_query_only": h["weak_query_only"],
                                        "distinctive_queries": h["distinctive_queries"],
                                        "retried_queries": h.get("retried_queries") or []}),
                     "origin": json.dumps({"queries": h["queries"]})})
    db.upsert_project_reuse(project_id, rows, brev, scan_version=SCAN_VERSION)
    # 0.61.0 — a re-scan has to be able to take a suggestion AWAY.
    #
    # `upsert` only ever inserted or updated, so a row the new matcher no longer produces stayed on the card for
    # ever: after 0.60.2 shipped, Kyle's screen still offered sources the fixed matcher would never have suggested,
    # and re-scanning could not remove them. A `suggested` row has exactly one author — the scan — so a scan that
    # does not reproduce it is entitled to retire it. Rows the USER decided on (attached or dismissed) are never
    # touched, and retiring keeps the row rather than deleting it, so the count stays explainable.
    retired = db.retire_project_reuse(project_id, [h["source_id"] for h in hits])

    projects = related_projects(project_id, hits)
    if progress:
        progress(0.98, "done")
    summary = {"queries": qs, "target_revision": _target_revision(targets), "scope": scope, "found": total_found, "shown": len(hits), "retired": retired,
               "strong": sum(1 for h in hits if h["band"] == "strong"),
               "possible": sum(1 for h in hits if h["band"] == "possible"),
               "weak_query_only": sum(1 for h in hits if h["weak_query_only"]),
               "query_strength": {"cut": strength["cut"], "weak": strength["weak"], "note": strength["note"],
                                  "rarity": strength["rarity"]},
               "projects": [{k: p[k] for k in ("project_id", "name", "relevant", "total")} for p in projects]}
    db.record_bootstrap_run(project_id, summary, brev)
    return {**summary, "sources": hits, "projects": projects}


def _why(h: dict[str, Any]) -> list[str]:
    """The reason, built from what actually matched. Never an adjective."""
    why = []
    if h["passages"]:
        why.append(f"{len(h['passages'])} matching passage{'' if len(h['passages']) == 1 else 's'}, first at {h['passages'][0]['timestamp']}")
    if h["terms"]:
        why.append("covers " + ", ".join(h["terms"][:6]))
    if len(h["queries"]) > 1:
        why.append(f"matched {len(h['queries'])} separate parts of your goal")
    if h.get("retried_queries") and not h.get("distinctive_queries"):
        why.append("matched only after the search was shortened — check the passage")
    return why


def related_projects(project_id: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Which existing projects the matching sources live in — explained by the useful subset, never as a bundle.
    A project here is a place relevant material happens to be, not a thing to import. The overlap is the union of
    terms the matched passages actually covered; the rest of that project is reported as a count, because saying
    what is NOT relevant would require scanning sources that did not match — a claim we have not earned."""
    if not hits:
        return []
    by_source = {h["source_id"]: h for h in hits}
    conn = db.connect()
    out: dict[str, dict[str, Any]] = {}
    qmarks = ",".join("?" for _ in by_source)
    for r in conn.execute(f"SELECT ps.project_id, ps.source_id, p.name FROM project_sources ps JOIN projects p ON p.id = ps.project_id "
                          f"WHERE ps.source_id IN ({qmarks}) AND ps.project_id != ?", (*by_source, project_id)).fetchall():
        e = out.setdefault(r["project_id"], {"project_id": r["project_id"], "name": r["name"], "relevant": 0,
                                             "total": 0, "source_ids": [], "overlap": []})
        e["relevant"] += 1
        e["source_ids"].append(r["source_id"])
        e["overlap"] = sorted(set(e["overlap"]) | set(by_source[r["source_id"]]["terms"]))
    for e in out.values():
        e["total"] = int(conn.execute("SELECT COUNT(*) FROM project_sources WHERE project_id=?", (e["project_id"],)).fetchone()[0])
        e["overlap"] = e["overlap"][:8]
        e["line"] = (f"{e['relevant']} of {e['total']} source{'' if e['total'] == 1 else 's'} match this project"
                     + (f" · the overlap is {', '.join(e['overlap'][:5])}" if e["overlap"] else ""))
    return sorted(out.values(), key=lambda e: -e["relevant"])


def state(project_id: str) -> dict[str, Any]:
    """What the Starting Research screen renders: the last run, the standing suggestions, and the related
    projects recomputed from them (cheap, and always consistent with what is actually stored)."""
    rows = db.list_project_reuse(project_id)
    hits = []
    for r in rows:
        why = json.loads(r["why"] or "{}")
        origin = json.loads(r["origin"] or "{}")
        src = db.get_source(r["object_id"]) or {}
        h = {"source_id": r["object_id"], "title": src.get("title"), "channel": src.get("channel"),
             "platform": src.get("platform"), "url": src.get("url"), "published_at": src.get("published_at"),
             "duration": src.get("duration"), "state": r["state"], "band": r["band"], "score": r["score"],
             "coverage": why.get("coverage") or 0.0, "passages": why.get("passages") or [],
             "weak_query_only": bool(why.get("weak_query_only")),
             "terms": why.get("terms") or [], "queries": origin.get("queries") or [],
             "scan_version": r.get("scan_version"),
             "from_old_matcher": (r.get("scan_version") or "recall-1") != SCAN_VERSION}
        h["why"] = _why(h)
        hits.append(h)
    run = db.last_bootstrap_run(project_id)
    pending = [h for h in hits if h["state"] == "suggested"]
    live = [h for h in pending if not h["weak_query_only"]]
    return {"run": run, "sources": hits, "projects": related_projects(project_id, live),
            "counts": {"suggested": len(live), "attached": sum(1 for h in hits if h["state"] == "attached"),
                       "dismissed": sum(1 for h in hits if h["state"] == "dismissed"),
                       "retired": sum(1 for h in hits if h["state"] == "retired"),
                       "weak_query_only": sum(1 for h in pending if h["weak_query_only"]),
                       "strong": sum(1 for h in live if h["band"] == "strong"),
                       "possible": sum(1 for h in live if h["band"] == "possible")},
            "stale": bool(run and ((run.get("brief_revision") and run["brief_revision"] != db.brief_revision(project_id))
                                   or run.get("target_revision") != _target_revision(_open_targets(project_id)))),
            "scan_version": SCAN_VERSION,
            "matcher_stale": any(h["from_old_matcher"] for h in pending),
            "matcher_note": ("These suggestions predate the current relevance check. Generic-only matches are excluded; "
                             "the scan now uses the brief and open research gaps. Scan again to re-judge them — free. "
                             "The earlier two-letter subject-token fix is retained."
                             if any(h["from_old_matcher"] for h in pending) else None)}


def decide(project_id: str, source_ids: list[str], decision: str) -> dict[str, Any]:
    """Attach or dismiss suggested sources. Attaching is a `project_sources` row — the source itself is untouched,
    stays in every other project it belongs to, and is never re-acquired."""
    if decision not in ("attach", "dismiss"):
        raise ValueError("decision must be attach or dismiss")
    ids = [s for s in source_ids if s]
    if decision == "attach" and ids:
        db.add_project_sources(project_id, ids)
    db.set_project_reuse_state(project_id, ids, "attached" if decision == "attach" else "dismissed")
    return {"decision": decision, "count": len(ids), **state(project_id)["counts"]}


def run_job(job_id: str, payload: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    t0 = time.time()
    r = scan(payload["project_id"], progress=progress)
    return {"queries": len(r["queries"]), "found": r["found"], "shown": r.get("shown", 0),
            "strong": r.get("strong", 0), "scope": r["scope"], "seconds": round(time.time() - t0, 2)}
