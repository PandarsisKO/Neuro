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

import json
import logging
import re
import time
from typing import Any

from . import db, library

log = logging.getLogger(__name__)

MAX_QUERIES = 6          # each is one library.recall; the goal itself is always the first
PER_QUERY = 14
MIN_QUERY_TOKENS = 3     # a fragment shorter than this retrieves noise
STRONG_QUERIES = 2       # matched by two independent queries = strong
STRONG_COVERAGE = 0.6    # or one query whose terms are mostly covered by real passages
KEEP = 60                # the most sources a scan will suggest; the rest are honestly reported as "not shown"

_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "that", "this", "my", "me", "i",
         "is", "are", "be", "can", "so", "it", "as", "at", "by", "from", "how", "what", "want", "would", "should",
         "help", "helps", "get", "make", "build", "better", "more", "new", "use", "using", "about"}


def _clauses(text: str) -> list[str]:
    """A goal, broken into the facets worth searching separately. A long sentence is REPLACED by its parts, not
    accompanied by them: the whole goal as one query is a poor retrieval query (every extra term raises the
    coverage denominator and pushes good passages under the floor), and keeping both would also make every hit
    look like it "matched 2 parts of your goal" when it matched one idea twice."""
    out: list[str] = []
    for sent in re.split(r"[.!?\n]+", text or ""):
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


def queries_for(project: dict[str, Any]) -> list[str]:
    """The searches a goal implies, at $0: the goal's own facets, then the project's starting questions.
    Deduplicated by content tokens — two phrasings of one idea must not spend two recalls."""
    goal = (project.get("goal") or "").strip()
    brief = (project.get("brief") or "").strip()
    cands = _clauses(goal) or _clauses(brief)
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
        if len(picked) >= MAX_QUERIES:
            break
    return picked


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
    return "strong" if (len(hit["queries"]) >= STRONG_QUERIES or hit["coverage"] >= STRONG_COVERAGE) else "possible"


def scan(project_id: str, progress: Any = None) -> dict[str, Any]:
    """Run the bootstrap scan and persist its suggestions. Pure recall + bookkeeping: no generation call, no
    writes to `project_sources`, no writes to any other project."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError("no such project")
    qs = queries_for(project)
    brev = db.brief_revision(project_id)
    if not qs:
        db.record_bootstrap_run(project_id, {"queries": [], "scanned": 0, "found": 0, "reason": "the goal is too short to search from"}, brev)
        return {"queries": [], "sources": [], "projects": [], "found": 0, "scope": 0,
                "note": "Tell Neuro Search a little more about the goal and it can search your library for it."}

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
        for s in r["suggestions"]:
            m = merged.setdefault(s["source_id"], {
                "source_id": s["source_id"], "title": s.get("title"), "channel": s.get("channel"),
                "platform": s.get("platform"), "url": s.get("url"), "published_at": s.get("published_at"),
                "score": 0.0, "coverage": 0.0, "passage_coverage": 0.0, "queries": [], "passages": [], "terms": [],
            })
            m["score"] = round(max(m["score"], s["score"]), 4)
            m["coverage"] = max(m["coverage"], s.get("coverage") or 0.0)
            m["passage_coverage"] = max(m["passage_coverage"], s.get("passage_coverage") or 0.0)
            m["queries"].append(q)
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
        h["why"] = _why(h)
        rows.append({"object_kind": "source", "object_id": h["source_id"], "band": h["band"], "score": h["score"],
                     "why": json.dumps({"passages": h["passages"], "terms": h["terms"], "coverage": h["coverage"]}),
                     "origin": json.dumps({"queries": h["queries"]})})
    db.upsert_project_reuse(project_id, rows, brev)

    projects = related_projects(project_id, hits)
    if progress:
        progress(0.98, "done")
    summary = {"queries": qs, "scope": scope, "found": total_found, "shown": len(hits),
               "strong": sum(1 for h in hits if h["band"] == "strong"),
               "possible": sum(1 for h in hits if h["band"] == "possible"),
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
             "terms": why.get("terms") or [], "queries": origin.get("queries") or []}
        h["why"] = _why(h)
        hits.append(h)
    run = db.last_bootstrap_run(project_id)
    live = [h for h in hits if h["state"] == "suggested"]
    return {"run": run, "sources": hits, "projects": related_projects(project_id, live),
            "counts": {"suggested": len(live), "attached": sum(1 for h in hits if h["state"] == "attached"),
                       "dismissed": sum(1 for h in hits if h["state"] == "dismissed"),
                       "strong": sum(1 for h in live if h["band"] == "strong"),
                       "possible": sum(1 for h in live if h["band"] == "possible")},
            "stale": bool(run and run.get("brief_revision") and run["brief_revision"] != db.brief_revision(project_id))}


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
