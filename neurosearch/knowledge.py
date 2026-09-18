"""G5 — Knowledge Map, Evidence Targets and Research Tensions (0.29.0).

Everything in this module is $0 and deterministic: it reads Claims (claims.py) and explains research state. The map
never counts sources — a node is Strong because a governing Claim is established or a corroborative one has enough
independent support, and the `why` says which. Evidence Targets say what "enough" means (closure) before anyone looks
for URLs; pursuing one runs the mandated escalation PROJECT EVIDENCE → GLOBAL LIBRARY → CANDIDATE INDEX → EXTERNAL and
reranks skipped candidates against the TARGET (not the whole project) without re-enumerating anything. Tensions
(NOVEL · CONTRADICTION · WEAK_CONSENSUS · STALE · MISSING_PERSPECTIVE) keep the map from being consensus-only.
Model-generated targets are proposed state (origin 'model'); user decisions are never rewritten here.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import claims, db

log = logging.getLogger("neurosearch.knowledge")

TENSIONS = ("NOVEL", "CONTRADICTION", "WEAK_CONSENSUS", "STALE", "MISSING_PERSPECTIVE")
NODE_STATES = ("strong", "developing", "weak", "missing")
CLASSES = ("authoritative", "expert", "experiential", "market", "historical")
# a corroborative topic whose evidence is all of ONE class is missing the perspective the Claim type needs
NEEDS = {"practice": ("experiential", "expert"), "experiential": ("experiential",), "market": ("market", "experiential"),
         "expert_interpretation": ("expert", "authoritative"), "governing": ("authoritative",), "causal": ("expert", "experiential"),
         "novel_tactic": ("experiential", "expert")}
CANDIDATE_RERANK_LIMIT = 12
TARGET_DUP_JACCARD = 0.5     # two target questions this similar are one target
MIN_NODE_CLAIMS = 3          # a topic becomes its own map node once this many Claims share it
SKIPPED_STATES = ("skipped_low_relevance", "skipped_limit", "skipped_cost")


# ---------------------------------------------------------------- targets

def _target(row: Any) -> dict[str, Any]:
    d = dict(row)
    for k in ("preferred_classes", "closure_rule", "current_evidence", "last_escalation"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def get_target(target_id: str) -> dict[str, Any] | None:
    row = db.connect().execute("SELECT * FROM project_evidence_targets WHERE id=?", (target_id,)).fetchone()
    return _target(row) if row else None


def list_targets(project_id: str, status: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM project_evidence_targets WHERE project_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at"
    return [_target(r) for r in db.connect().execute(q, (project_id, status) if status else (project_id,)).fetchall()]


def default_closure(sufficiency: str) -> tuple[str, dict[str, Any]]:
    if sufficiency == "governing":
        return ("one current, directly applicable primary source, with any ambiguity resolved; secondary sources help implementation but are not required",
                {"min_independent": 1, "primary_required": True, "characterize_disagreement": False})
    return ("at least three independent sources; major disagreement characterized; important outliers captured",
            {"min_independent": claims.CORROBORATION["strong"], "primary_required": False, "characterize_disagreement": True})


def add_target(project_id: str, question: str, *, topic: str | None = None, claim_id: str | None = None, sufficiency: str = "corroborative",
               preferred_classes: list[str] | None = None, closure: str | None = None, closure_rule: dict[str, Any] | None = None,
               origin: str = "user", gap: str | None = None, provenance: dict[str, Any] | None = None) -> dict[str, Any] | None:
    question = (question or "").strip()
    if len(question) < 8:
        return None
    if sufficiency not in ("governing", "corroborative"):
        sufficiency = "corroborative"
    conn = db.connect()
    dup = conn.execute("SELECT id FROM project_evidence_targets WHERE project_id=? AND lower(question)=lower(?)", (project_id, question)).fetchone()
    if dup:
        return get_target(dup["id"])
    # near-duplicate questions (the same gap phrased twice by different passes) fold into the existing target
    for row in conn.execute("SELECT id, question FROM project_evidence_targets WHERE project_id=? AND status IN ('open','satisfied')", (project_id,)).fetchall():
        if claims.jaccard(question, row["question"]) >= TARGET_DUP_JACCARD:
            return get_target(row["id"])
    d_closure, d_rule = default_closure(sufficiency)
    t = time.time()
    tid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO project_evidence_targets (id, project_id, question, topic, claim_id, sufficiency, preferred_classes, closure, closure_rule, status, origin, gap, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, project_id, question, (topic or claims._topic_of(question))[:80].lower(), claim_id, sufficiency,
                   json.dumps([x for x in (preferred_classes or []) if x in CLASSES] or list(NEEDS.get("practice" if sufficiency == "corroborative" else "governing"))),
                   closure or d_closure, json.dumps(closure_rule or d_rule), "open", origin, gap, t, t))
    assess_target(tid)
    return get_target(tid)


def set_target_status(target_id: str, status: str) -> dict[str, Any] | None:
    if status not in ("open", "satisfied", "closed_by_user", "dropped"):
        raise ValueError("bad status")
    with db.tx() as c:
        c.execute("UPDATE project_evidence_targets SET status=?, updated_at=? WHERE id=?", (status, time.time(), target_id))
    tg = get_target(target_id)
    claims._user_changed(tg.get("project_id") if tg else None)          # 0.62.8: their own decision, not churn
    return tg


def _claim_for_target(tg: dict[str, Any]) -> dict[str, Any] | None:
    if tg.get("claim_id"):
        return claims.get(tg["claim_id"])
    # best matching claim by topic / token overlap
    best, score = None, 0.0
    for c in claims.list_for_project(tg["project_id"]):
        if c["status"] == "rejected":
            continue
        s = claims.overlap(tg["question"], c["text"]) + (0.3 if c.get("topic") == tg.get("topic") else 0)
        if s > score:
            best, score = c, s
    return best if score >= 0.5 else None


def assess_target(target_id: str) -> dict[str, Any] | None:
    """Closure is evaluated against the linked/matching Claim's evidence, with the target's own rule."""
    tg = get_target(target_id)
    if not tg:
        return None
    rule = tg.get("closure_rule") or {}
    c = _claim_for_target(tg)
    ev = c["evidence"] if c else []
    sup = [e for e in ev if e["relation"] in ("SUPPORTS", "EXPERIENTIAL") and not e.get("stale")]
    indep = {e["source_id"] for e in sup if e.get("independent")}
    primary = [e for e in sup if e.get("evidence_class") in ("authoritative", "historical")]
    classes = sorted({e.get("evidence_class") or "" for e in sup})
    summary = {"claim_id": c["id"] if c else None, "strength": c["strength"] if c else None, "supporting": len(sup), "independent": len(indep),
               "primary": len(primary), "classes": classes}
    satisfied = bool(c) and c["strength"] == "strong"
    if rule.get("primary_required") and not primary:
        satisfied = False
    if len(indep) < int(rule.get("min_independent") or 1):
        satisfied = False
    if rule.get("characterize_disagreement") and c:
        open_t = db.connect().execute("SELECT COUNT(*) n FROM research_tensions WHERE claim_id=? AND status='open' AND kind IN ('CONTRADICTION','NOVEL')", (c["id"],)).fetchone()["n"]
        if open_t:
            satisfied = False
    if not c:
        gap = "no Claim in the project addresses this yet"
    elif satisfied:
        gap = None
    elif rule.get("primary_required") and not primary:
        gap = "the controlling primary source itself is missing"
    elif len(indep) < int(rule.get("min_independent") or 1):
        gap = f"{len(indep)} independent source(s); needs {rule.get('min_independent')}"
    else:
        gap = c.get("strength_why")
    status = tg["status"]
    if status not in ("closed_by_user", "dropped"):
        status = "satisfied" if satisfied else "open"
    # S72: write only when the assessment actually changed — this ran for every target on every research pass
    # (6,774 on Kyle's project) and stamped `updated_at` each time, moving the research revision for nothing.
    new_claim = tg.get("claim_id") or (c["id"] if c else None)
    cur_ev = tg.get("current_evidence")
    if isinstance(cur_ev, str):
        try:
            cur_ev = json.loads(cur_ev)
        except ValueError:
            cur_ev = None
    if (tg.get("claim_id"), cur_ev, tg.get("gap"), tg["status"]) == (new_claim, summary, gap, status):
        return tg
    with db.tx() as conn:
        conn.execute("UPDATE project_evidence_targets SET claim_id=COALESCE(claim_id, ?), current_evidence=?, gap=?, status=?, updated_at=? WHERE id=?",
                     (c["id"] if c else None, json.dumps(summary), gap, status, time.time(), target_id))
    return get_target(target_id)


# ---------------------------------------------------------------- escalation: project → library → candidates → external

def _target_terms(tg: dict[str, Any]) -> set[str]:
    return claims._tokens(tg["question"]) | claims._tokens(tg.get("topic") or "")


def _class_of_candidate(cand: dict[str, Any]) -> str:
    ct = (cand.get("content_type") or "").lower()
    url = (cand.get("url") or "").lower()
    if ".gov" in url or ".mil" in url or ct == "document" and "publication" in (cand.get("title") or "").lower():
        return "authoritative"
    if ct in ("video", "podcast", "post"):
        return "experiential"
    if ".edu" in url:
        return "expert"
    return "expert" if ct in ("page", "document") else "experiential"


def rerank_candidates(tg: dict[str, Any], limit: int = CANDIDATE_RERANK_LIMIT) -> list[dict[str, Any]]:
    """Candidate Index recall scored against THIS target: metadata match × preferred-class fit. Skipped candidates are
    eligible — a new gap is exactly what makes a previously low-relevance candidate relevant. No network."""
    from . import candidates
    pref = list(tg.get("preferred_classes") or [])
    rows = candidates.search(tg["project_id"], tg["question"], limit=limit * 3)
    terms = _target_terms(tg)
    out = []
    for r in rows:
        meta = " ".join(str(r.get(k) or "") for k in ("title", "description", "creator"))
        cov = len(terms & claims._tokens(meta)) / max(1, len(terms))
        cls = _class_of_candidate(r)
        fit = (1.0 - pref.index(cls) / max(1, len(pref))) if cls in pref else 0.25
        score = round(0.6 * cov + 0.4 * fit + 0.05 * min(r.get("score") or 0, 5) / 5, 3)
        r.update(target_score=score, target_coverage=round(cov, 2), evidence_class=cls, class_fit=round(fit, 2),
                 resurfaced=r.get("state") in SKIPPED_STATES)
        out.append(r)
    out.sort(key=lambda x: x["target_score"], reverse=True)
    return out[:limit]


def pursue(target_id: str, *, external: bool = False, resurface: bool = True) -> dict[str, Any]:
    """The mandated order for a new Evidence Target. Steps 1–3 cost nothing but an embeddings micro-call in step 2; step 4
    (external Discover) only when asked. Nothing found here becomes project evidence: library suggestions are attach
    proposals and candidates are metadata — the project boundary is crossed only by an explicit Add."""
    from . import candidates, library, search
    tg = get_target(target_id)
    if not tg:
        raise ValueError("unknown target")
    pid, q = tg["project_id"], tg["question"]
    steps: list[dict[str, Any]] = []
    project = db.get_project(pid) or {}
    # 1 — current project evidence
    hits = search.search(q, limit=8, source_ids=project.get("source_ids") or []) if project.get("source_ids") else []
    steps.append({"step": "project_evidence", "found": len(hits), "top": [{"source_id": h["source_id"], "title": h.get("title"), "timestamp": h.get("timestamp")} for h in hits[:3]]})
    # 2 — global library (never attached)
    lib = library.recall(pid, q, limit=6, reason=f"evidence target: {q[:100]}")
    steps.append({"step": "global_library", "found": len(lib["suggestions"]),
                  "suggestions": [{"source_id": s["source_id"], "title": s["title"], "coverage": s.get("coverage"), "evidence_class": s.get("evidence_class")} for s in lib["suggestions"]]})
    # 3 — candidate index, reranked against the target
    ranked = rerank_candidates(tg)
    resurfaced = [r for r in ranked if r.get("resurfaced")]
    if resurface and resurfaced:
        candidates.mark(pid, [r["id"] for r in resurfaced], "available", reason=f"resurfaced for evidence target: {q[:80]}")
    steps.append({"step": "candidate_index", "found": len(ranked), "resurfaced": len(resurfaced),
                  "candidates": [{"id": r["id"], "title": r.get("title"), "state": r.get("state"), "target_score": r["target_score"], "evidence_class": r.get("evidence_class"), "resurfaced": r.get("resurfaced")} for r in ranked[:8]]})
    for r in ranked[:8]:                                                   # B3: the gap remembers what could fill it (durable, not a JSON trail)
        candidates.link(r["id"], pid, "evidence_target", target_id, relevance=int(round(100 * float(r["target_score"]))), why=f"matches the open question: {q[:120]}")
    # Where to look, from what this project has already measured about each master source (C2, 0.58.3). $0 and
    # database-only, so it is safe here where `pursue(external=False)` promises no WEB SEARCH.
    #
    # It is deliberately NOT a step. `steps` is the escalation LADDER — project evidence → global library →
    # candidate index → external — and every entry in it is somewhere the app actually looked; `already_checked` in
    # the Research tab is rendered straight from it. This searched nothing: it reads what the earlier steps and the
    # project's history already know and recommends a place for the USER to look next. Adding it to the ladder both
    # broke the frozen G5 acceptance gate and would have told Kyle a recommendation was a search. It rides alongside.
    look = candidates.where_to_look(pid, tg, limit=5)
    # 4 — research catalogues: $0 and no model call, but it IS a request to an outside service, so it belongs on the
    # external path only. `pursue(external=False)` is the escalation the UI labels "Search my existing research …
    # No web search", and the G5 acceptance gate freezes it as network-free; a free call is still a call. When the
    # user does ask to look outside, the catalogue runs FIRST, because a Crossref query either answers the
    # question's evidence need for nothing or proves this is not a literature question — either way before a paid
    # Discover job. Only targets declaring an expert/authoritative class are queried.
    closure_ok = assess_target(target_id)
    if external:
        from . import scholar
        sch = scholar.for_target(tg, pid, limit=8)
        steps.append({"step": "catalogue", **sch})
    # 5 — external discovery, only on request
    ext: dict[str, Any] = {"step": "external", "run": False}
    if external and (closure_ok or {}).get("status") == "open":
        job = db.create_job("discover", {"project_id": pid, "refine": q, "mode": "web_first"})
        ext.update(run=True, job_id=job["id"])
    steps.append(ext)
    rec = {"at": time.time(), "steps": steps,
           "where_to_look": [{k: r[k] for k in ("creator", "untapped", "read", "findings", "per_source", "why", "action")}
                             for r in look["rows"]]}
    with db.tx() as conn:
        conn.execute("UPDATE project_evidence_targets SET last_escalation=?, updated_at=? WHERE id=?", (json.dumps(rec), time.time(), target_id))
    db.kv_bump("research:targets_pursued")
    return {"target": get_target(target_id), "escalation": rec}


# ---------------------------------------------------------------- tensions

def _upsert_tension(project_id: str, kind: str, claim_id: str | None, description: str, evidence: dict[str, Any], impact: str = "medium",
                    related_claim_id: str | None = None) -> str:
    t = time.time()
    conn = db.connect()
    row = conn.execute("SELECT id, status, description, evidence, impact FROM research_tensions WHERE project_id=? AND kind=? AND claim_id IS ? AND COALESCE(related_claim_id,'')=?",
                       (project_id, kind, claim_id, related_claim_id or "")).fetchone()
    ev_json = json.dumps(evidence)
    if row and (row["description"], row["evidence"], row["impact"]) == (description, ev_json, impact):
        return row["id"]                                   # same tension, same words: no write, no revision movement (S72)
    with db.tx() as c:
        if row:
            c.execute("UPDATE research_tensions SET description=?, evidence=?, impact=?, updated_at=? WHERE id=?", (description, ev_json, impact, t, row["id"]))
            return row["id"]
        tid = db.new_id()
        c.execute("INSERT INTO research_tensions (id, project_id, kind, claim_id, related_claim_id, description, evidence, impact, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, project_id, kind, claim_id, related_claim_id, description, json.dumps(evidence), impact, "open", t, t))
    return tid


def list_tensions(project_id: str, status: str | None = "open") -> list[dict[str, Any]]:
    q = "SELECT t.*, c.text AS claim_text, c.strength AS claim_strength FROM research_tensions t LEFT JOIN project_claims c ON c.id=t.claim_id WHERE t.project_id=?" + (" AND t.status=?" if status else "") + " ORDER BY t.impact='high' DESC, t.created_at"
    out = []
    for r in db.connect().execute(q, (project_id, status) if status else (project_id,)).fetchall():
        d = dict(r)
        if d.get("evidence"):
            try:
                d["evidence"] = json.loads(d["evidence"])
            except ValueError:
                pass
        out.append(d)
    return out


def set_tension_status(tension_id: str, status: str) -> None:
    if status not in ("open", "resolved", "dismissed"):
        raise ValueError("bad status")
    pid = (db.connect().execute("SELECT project_id FROM research_tensions WHERE id=?", (tension_id,)).fetchone() or {})
    with db.tx() as c:
        c.execute("UPDATE research_tensions SET status=?, updated_at=? WHERE id=?", (status, time.time(), tension_id))
    claims._user_changed(pid["project_id"] if pid else None)            # 0.62.8: their own decision, not churn


ECHO_OVERLAP = 0.3       # Jaccard


NOVEL_MAX = 12          # the outliers worth a tension + corroboration target per pass: highest importance first, not every lone finding
WEAK_CONSENSUS_MAX = 40 # false-consensus cases per pass (highest importance first); the Claim itself still says "1 independent"
STALE_MIN_IMPORTANCE = 4  # a stale tension only for Claims that matter (importance ≥ 4 or accepted); every stale Claim still shows `stale`
STALE_MAX = 60          # per pass, stale before needs-refresh, highest importance first; the Research view filters by freshness for the rest


def _echoed(c: dict[str, Any], index: "claims.TwinIndex") -> bool:
    """Novelty is project-relative: an idea another source in the project also states (even loosely) is not an outlier.
    Symmetric (Jaccard) so a long normalized text cannot 'echo' every short claim that shares a few words."""
    mine = {e["source_id"] for e in c["evidence"]}
    o = index.twin(c["text"], threshold=ECHO_OVERLAP, exclude_id=c["id"], symmetric=True)
    return bool(o) and bool({e["source_id"] for e in o.get("evidence", [])} - mine)


def detect(project_id: str) -> dict[str, int]:
    """Deterministic tension detection over assessed Claims. Creates the corroboration Evidence Target for NOVEL and
    WEAK_CONSENSUS tensions so the gap is pursued, not just displayed."""
    counts = {k: 0 for k in TENSIONS}
    all_claims = [c for c in claims.list_for_project(project_id) if c["status"] not in ("rejected", "superseded")]
    index = claims.TwinIndex(all_claims)
    imp_of: dict[int, int] = {}
    if all_claims:
        for r in db.connect().execute("SELECT id, importance FROM project_notes WHERE project_id=?", (project_id,)).fetchall():
            imp_of[r["id"]] = int(r["importance"] or 3)
    novel_budget, weak_budget, stale_budget = NOVEL_MAX, WEAK_CONSENSUS_MAX, STALE_MAX
    selected: set[str] = set()
    all_claims.sort(key=lambda c: (-imp_of.get(c.get("origin_note_id") or -1, 3), 0 if c.get("freshness_status") == "stale" else 1))   # importance first, stale before needs-refresh (the budgets)
    for c in all_claims:
        ev = [e for e in c["evidence"] if not e.get("stale")]
        sup = [e for e in ev if e["relation"] in ("SUPPORTS", "EXPERIENTIAL")]
        con = [e for e in ev if e["relation"] == "CONTRADICTS"]
        indep = {e["source_id"] for e in sup if e.get("independent")}
        imp = imp_of.get(c.get("origin_note_id") or -1, 3)
        fs = c.get("freshness_status") or "uncertain"
        if fs in ("stale", "needs_refresh") and (imp >= STALE_MIN_IMPORTANCE or c["status"] == "accepted" or (fs == "stale" and c["strength"] in ("strong", "developing"))) and stale_budget > 0:
            stale_budget -= 1
            label = "Stale" if fs == "stale" else "Needs refresh"
            selected.add(_upsert_tension(project_id, "STALE", c["id"], f"{label}: {c['text'][:140]} — {c.get('freshness_why')}",
                                         {"freshness_class": c["freshness_class"], "freshness_status": fs}, "high" if fs == "stale" else "medium"))
            counts["STALE"] += 1
        if con:
            other = next((e for e in con), None)
            selected.add(_upsert_tension(project_id, "CONTRADICTION", c["id"], f"Contradiction: {c['text'][:140]} is disputed by {other.get('title') if other else 'another source'}",
                            {"supporting": len(sup), "contradicting": len(con)}, "high"))
            counts["CONTRADICTION"] += 1
        if c["claim_type"] not in claims.GOVERNING_TYPES and len(sup) >= 1:
            if len(indep) == 1 and len(sup) >= 2 and weak_budget > 0:
                weak_budget -= 1
                selected.add(_upsert_tension(project_id, "WEAK_CONSENSUS", c["id"], f"Looks corroborated but is not: {len(sup)} sources, 1 independent — the others repeat it. {c['text'][:120]}",
                                {"supporting": len(sup), "independent": 1}, "medium"))
                counts["WEAK_CONSENSUS"] += 1
                add_target(project_id, f"Independently corroborate: {c['text'][:160]}", topic=c.get("topic"), claim_id=c["id"], sufficiency="corroborative", origin="tension")
            elif len(indep) == 1 and len(sup) == 1 and (imp >= 4 or c["claim_type"] in ("novel_tactic", "causal")) and novel_budget > 0 and not _echoed(c, index):
                novel_budget -= 1
                e0 = sup[0]
                selected.add(_upsert_tension(project_id, "NOVEL", c["id"], f"Potential outlier: {c['text'][:160]} — currently supported by one {e0.get('evidence_class')} source ({e0.get('title')}); additional corroboration recommended",
                                {"source_id": e0["source_id"], "locator": e0.get("locator"), "importance": imp}, "high" if imp >= 4 else "medium"))
                counts["NOVEL"] += 1
                add_target(project_id, f"Corroborate or refute: {c['text'][:160]}", topic=c.get("topic"), claim_id=c["id"], sufficiency="corroborative", origin="tension")
    # missing perspective per topic
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for c in all_claims:
        by_topic.setdefault(c.get("topic") or "general", []).append(c)
    for topic, cs in by_topic.items():
        present = {e.get("evidence_class") for c in cs for e in c["evidence"] if e["relation"] in ("SUPPORTS", "EXPERIENTIAL")}
        present.discard("derivative")
        needed = set()
        for c in cs:
            needed |= set(NEEDS.get(c["claim_type"], ()))
        missing = sorted(needed - present)
        if missing and cs:
            lead = cs[0]
            selected.add(_upsert_tension(project_id, "MISSING_PERSPECTIVE", lead["id"], f"Topic '{topic}' has only {', '.join(sorted(x for x in present if x)) or 'no'} evidence; missing {', '.join(missing)} perspective(s)",
                            {"topic": topic, "present": sorted(x for x in present if x), "missing": missing}, "medium"))
            counts["MISSING_PERSPECTIVE"] += 1
    # reconcile: a deterministic pass owns NOVEL/WEAK_CONSENSUS/STALE/MISSING_PERSPECTIVE — anything it did not (re)select is
    # dismissed and the corroboration target it opened is dropped (user-made targets are never touched)
    with db.tx() as conn:
        for tsn in list_tensions(project_id, status="open"):
            if tsn["kind"] in ("NOVEL", "WEAK_CONSENSUS", "STALE", "MISSING_PERSPECTIVE") and tsn["id"] not in selected:
                conn.execute("UPDATE research_tensions SET status='dismissed', updated_at=? WHERE id=?", (time.time(), tsn["id"]))
                if tsn.get("claim_id"):
                    conn.execute("UPDATE project_evidence_targets SET status='dropped', updated_at=? WHERE project_id=? AND claim_id=? AND origin='tension' AND status='open'",
                                 (time.time(), project_id, tsn["claim_id"]))
        # a target re-opened by a re-selected tension — unless dedupe_targets folded it into a surviving duplicate,
        # which stays folded (the survivor is open and carries the question)
        for tsn in list_tensions(project_id, status="open"):
            if tsn["kind"] in ("NOVEL", "WEAK_CONSENSUS") and tsn.get("claim_id"):
                conn.execute("UPDATE project_evidence_targets SET status='open', updated_at=? WHERE project_id=? AND claim_id=? AND origin='tension' AND status='dropped' "
                             "AND (gap IS NULL OR gap NOT LIKE ?)",
                             (time.time(), project_id, tsn["claim_id"], f"{DUPLICATE_GAP_PREFIX}%"))
    # auto-resolve tensions whose condition no longer holds
    for tsn in list_tensions(project_id, status="open"):
        c = claims.get(tsn["claim_id"]) if tsn.get("claim_id") else None
        if not c or c["status"] in ("rejected", "superseded"):
            set_tension_status(tsn["id"], "resolved")
            continue
        if tsn["kind"] == "STALE" and (c.get("freshness_status") or "") not in ("stale", "needs_refresh"):
            set_tension_status(tsn["id"], "resolved")
        if tsn["kind"] in ("NOVEL", "WEAK_CONSENSUS") and c["strength"] == "strong":
            set_tension_status(tsn["id"], "resolved")
    return counts


# ---------------------------------------------------------------- the map

DUPLICATE_GAP_PREFIX = "duplicate of target "     # the drop reason dedupe_targets records; detect() honours it


def dedupe_targets(project_id: str) -> int:
    """Open targets whose questions are near-duplicates (Jaccard ≥ TARGET_DUP_JACCARD) fold into the earliest one; the
    later ones are `dropped`. User-made targets are never dropped. Cheap: open targets only."""
    rows = [t for t in list_targets(project_id, status="open")]
    # P0 (docs/SPEED-AUDIT-2026-09-17.md §7): the pairwise Jaccard pass is CPU — quadratic in open targets — and it
    # used to run INSIDE the write transaction, holding SQLite's single writer for 12 s on Kyle's project while
    # "New chat" (one INSERT) waited 10 s behind it. Decide first, then write the decisions in one short transaction.
    keep: list[dict[str, Any]] = []
    to_drop: list[tuple[str, str]] = []
    for t in rows:                                                 # list_targets is created_at ascending
        dup = next((k for k in keep if claims.jaccard(t["question"], k["question"]) >= TARGET_DUP_JACCARD), None)
        if dup and t.get("origin") != "user":
            to_drop.append((t["id"], dup["id"]))
        else:
            keep.append(t)
    if to_drop:
        # Sources cache-churn (docs/SPEED-AUDIT-2026-09-17.md §8): a target dropped HERE as a near-duplicate is
        # folded into its survivor, and the drop says so in `gap` — `detect()`'s reconcile re-opens dropped
        # tension targets whose tension is still selected, and without the reason it re-opened these every pass
        # for this function to fold them again: one write per pass, moving the research revision and retiring
        # every research-derived cache for nothing (three targets on Kyle's project, measured live).
        with db.tx() as conn:
            now = time.time()
            conn.executemany("UPDATE project_evidence_targets SET status='dropped', gap=?, updated_at=? WHERE id=? AND status='open'",
                             [(f"{DUPLICATE_GAP_PREFIX}{into}", now, tid) for tid, into in to_drop])
    return len(to_drop)


def refresh(project_id: str) -> dict[str, Any]:
    """Recompute nodes from Claims + targets + tensions. `why` is the explanation; counts are context, never the verdict."""
    claims.assess_project(project_id)
    detect(project_id)
    dedupe_targets(project_id)
    try:
        from . import community
        community.synthesize(project_id)                                  # G7: derived cross-thread states, never primary evidence
    except Exception as e:  # noqa: BLE001
        log.warning("community synthesis skipped: %s", e)
    for tg in list_targets(project_id):
        assess_target(tg["id"])
    all_claims = [c for c in claims.list_for_project(project_id) if c["status"] not in ("rejected", "superseded")]
    targets = list_targets(project_id)
    tensions = list_tensions(project_id, status="open")
    # node keys: a topic is a node when at least MIN_NODE_CLAIMS Claims share it; a finer topic (the contract names
    # specific ones) folds into the project-vocabulary topic for the MAP only — the Claim keeps its own label
    vocab = claims.project_vocab(project_id)
    tcount: dict[str, int] = {}
    for c in all_claims:
        tcount[c.get("topic") or "general"] = tcount.get(c.get("topic") or "general", 0) + 1

    def node_key(c: dict[str, Any]) -> str:
        t = c.get("topic") or "general"
        return t if tcount.get(t, 0) >= MIN_NODE_CLAIMS else claims._topic_of(c["text"].split(" — ", 1)[-1], vocab)
    topics: dict[str, dict[str, Any]] = {}
    for c in all_claims:
        topics.setdefault(node_key(c), {"claims": [], "targets": [], "tensions": []})["claims"].append(c)
    claim_topic = {c["id"]: node_key(c) for c in all_claims}
    for tg in targets:
        if tg["status"] == "dropped":
            continue
        key = claim_topic.get(tg.get("claim_id") or "")
        if not key:
            t = tg.get("topic") or "general"
            key = t if t in topics else claims._topic_of(tg["question"], vocab)
        topics.setdefault(key, {"claims": [], "targets": [], "tensions": []})["targets"].append(tg)
    for tsn in tensions:
        c = next((x for x in all_claims if x["id"] == tsn.get("claim_id")), None)
        topics.setdefault(claim_topic.get((c or {}).get("id") or "") or (tsn.get("evidence") or {}).get("topic") or "general", {"claims": [], "targets": [], "tensions": []})["tensions"].append(tsn)
    t = time.time()
    nodes = []
    rows: list[tuple] = []
    if True:                                                          # (indentation kept so the diff stays reviewable)
        for topic, g in topics.items():
            cs, tgs, tsns = g["claims"], [x for x in g["targets"] if x["status"] == "open"], g["tensions"]
            strong = [c for c in cs if c["strength"] == "strong"]
            classes = sorted({e.get("evidence_class") for c in cs for e in c["evidence"] if e.get("evidence_class") and e.get("evidence_class") != "derivative"})
            missing = sorted({m for x in tsns if x["kind"] == "MISSING_PERSPECTIVE" for m in (x.get("evidence") or {}).get("missing", [])})
            if not cs:
                state, why = "missing", ("an evidence target exists but no Claim addresses it yet" if tgs else "nothing established")
            elif strong and not tgs and not any(x["kind"] in ("CONTRADICTION", "STALE") for x in tsns) and not any(c.get("freshness_status") == "stale" for c in strong):
                lead = strong[0]
                state, why = "strong", f"{len(strong)} strong Claim(s) — e.g. {lead['strength_why']}"
            elif strong:
                state = "developing"
                why = f"{len(strong)} strong Claim(s) ({strong[0]['strength_why'].split(';')[0]}) but " + (f"{len(tgs)} open evidence target(s)" if tgs else "an open contradiction/staleness tension")
            elif any(c["strength"] == "developing" for c in cs):
                lead = next(c for c in cs if c["strength"] == "developing")
                state, why = "developing", lead["strength_why"] or "partial support"
            else:
                lead = cs[0]
                state, why = "weak", lead["strength_why"] or "single or no support"
            if missing:
                why += f"; missing {', '.join(missing)} perspective(s)"
            rows.append((project_id, topic, state, why, len(cs), len(strong), len(tgs), len(tsns), json.dumps(classes), json.dumps(missing)))
            nodes.append({"topic": topic, "state": state, "why": why, "claims_total": len(cs), "claims_strong": len(strong), "targets_open": len(tgs),
                          "tensions_open": len(tsns), "evidence_classes": classes, "missing_perspectives": missing})
    # Sources cache-churn (docs/SPEED-AUDIT-2026-09-17.md §8): the nodes used to be deleted and re-inserted with a
    # fresh `updated_at` on every refresh, so `project_knowledge_nodes.MAX(updated_at)` — part of
    # `db.project_research_revision` — moved on every pass even when every node came out identical, retiring every
    # research-derived cache for nothing. The table is rewritten only when the node set actually differs; an
    # identical rebuild leaves the rows, their timestamps and the revision alone. (Decided outside the transaction,
    # written in one short one — the P0 rule.)
    existing = {r["topic"]: (r["state"], r["why"], r["claims_total"], r["claims_strong"], r["targets_open"], r["tensions_open"],
                             r["evidence_classes"], r["missing_perspectives"])
                for r in db.connect().execute("SELECT topic, state, why, claims_total, claims_strong, targets_open, tensions_open, evidence_classes, "
                                              "missing_perspectives FROM project_knowledge_nodes WHERE project_id=?", (project_id,))}
    wanted = {r[1]: r[2:] for r in rows}
    if wanted != existing:
        with db.tx() as conn:
            conn.execute("DELETE FROM project_knowledge_nodes WHERE project_id=?", (project_id,))
            conn.executemany("INSERT INTO project_knowledge_nodes (project_id, topic, state, why, claims_total, claims_strong, targets_open, tensions_open, "
                             "evidence_classes, missing_perspectives, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [(*r, t) for r in rows])
    order = {"strong": 0, "developing": 1, "weak": 2, "missing": 3}
    nodes.sort(key=lambda n: (order[n["state"]], n["topic"]))
    return {"nodes": nodes, "counts": {s: sum(1 for n in nodes if n["state"] == s) for s in NODE_STATES},
            "targets_open": sum(1 for x in targets if x["status"] == "open"), "tensions_open": len(tensions)}


STATE_MAX_CLAIMS = 300
STATE_MAX_EVIDENCE = 12
STATE_MAX_LIST = 100
_STRENGTH_ORDER = {"strong": 0, "developing": 1, "weak": 2, "unsupported": 3}


def known_evidence(project_id: str, target_id: str, limit: int = 3) -> dict[str, Any]:
    """B3: for one open question — how many promising sources are known but not captured, and the best few."""
    from . import candidates
    rows = candidates.links_for(project_id, "evidence_target", target_id, limit=limit)
    total = candidates.link_counts(project_id, "evidence_target").get(target_id, 0)
    return {"known_uncaptured": total, "browser_likely": sum(1 for r in rows if r["acquisition_hint"] == "browser_likely"),
            "best": [{"candidate_id": r["candidate_id"], "title": r.get("title"), "url": r.get("url"), "relevance": r.get("relevance"), "platform": r.get("platform"),
                      "acquisition_hint": r["acquisition_hint"], "num_comments": r.get("comment_count") or r.get("view_count")} for r in rows]}


def capture_best(project_id: str, target_id: str, n: int = 3) -> dict[str, Any]:
    """Acquire the best known sources for an open question through the NORMAL path (attach if owned -> ingest job,
    which parks on the browser when the server cannot read it). Never a parallel acquisition.

    Shared boundary for CR5 (Claim-linked refresh, research_refresh.request_refresh) and CR8b (open-Evidence-Target
    selective acquisition, 2026-09-16): both callers need the same eligibility/acquisition mechanics, so this is the
    one place that lives -- not two independently drifting implementations (Kyle, CR8b corrections #2/#9.D).

    Considers a bounded pool of the strongest-linked candidates (fixed at up to 10, independent of `n`) so a
    candidate that turns out ineligible at execution time doesn't stall the target -- it's skipped and the next-best
    candidate in the SAME pass is tried, until `n` acquisitions have started or the pool is exhausted. Still at most
    `n` acquisitions per call -- never a cascade through the whole pool (CR8b correction #6).

    Re-reads live `candidate_projects.state` immediately before acting on each candidate (CR8b correction #4/#5): a
    candidate the user has since dismissed, or that another path already acquired/marked duplicate, is skipped here
    rather than re-captured -- this closes a real gap CR8b's inspection found (this function previously never
    looked at project-local state at all, which both CR5 and any future selective-acquisition caller inherited).
    This boundary is deliberately NOT inside `candidates.capture()`, which stays the explicit single-candidate
    "capture this anyway" path a user can still reach to reverse their own earlier dismissal (correction #4).

    $0-vs-spend sequencing (correction #3): an already-ready Library source attaches unconditionally -- a depleted
    budget must never block a genuinely free reuse. Only the enqueue-a-real-ingest branch is budget-gated, through
    the existing `usage.guard`/`usage.check` machinery (no new budget concept here or in any caller). A
    budget-refused candidate is left completely untouched -- no disposition change, no partial acquisition -- and
    reported in the returned `skipped` list; the next candidate in the pool is tried."""
    from . import candidates, identity, jobs as _jobs, usage
    rows = candidates.links_for(project_id, "evidence_target", target_id, limit=10)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    cap = max(1, n)
    for r in rows:
        if len(started) >= cap:
            break
        c = db.row_to_dict(db.connect().execute("SELECT * FROM candidates WHERE id=?", (r["candidate_id"],)).fetchone())
        if not c:
            continue
        cp = db.row_to_dict(db.connect().execute(
            "SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?", (c["id"], project_id)).fetchone())
        state = (cp or {}).get("state")
        if state in ("user_dismissed", "acquired", "duplicate"):
            skipped.append({"candidate_id": c["id"], "title": c.get("title"), "why": state})
            continue
        if c.get("source_id") and (db.get_source(c["source_id"]) or {}).get("status") == "ready":
            identity.attach_existing(project_id, c["source_id"])
            candidates.mark(project_id, [c["id"]], "acquired", "attached for an open question")
            candidates.satisfy_links(c["id"])
            started.append({"candidate_id": c["id"], "title": c.get("title"), "how": "attached"})
            continue
        try:
            usage.guard(0.0)
        except usage.BudgetPaused:
            skipped.append({"candidate_id": c["id"], "title": c.get("title"), "why": "budget"})
            continue
        job = _jobs.enqueue("ingest_url", {"url": c["url"], "tags": [], "project_id": project_id, "force": False, "review": False, "candidate_id": c["id"],
                                          "reason": f"evidence for an open question", "title": c.get("title")})
        candidates.mark(project_id, [c["id"]], "acquired", "capturing for an open question")
        started.append({"candidate_id": c["id"], "title": c.get("title"), "how": "job", "job_id": job["id"], "acquisition_hint": r["acquisition_hint"]})
    return {"target_id": target_id, "started": started, "skipped": skipped}


def state_map(project_id: str) -> dict[str, Any]:
    """Nodes and their counts as they stand, with NO recompute — the steering view (0.62.2). `state()` falls back to
    `refresh()` when a project has no nodes yet; a caller that only needs to steer must never trigger that, because
    on a large project it is a seven-minute pass (see `claims.ensure_cheap`)."""
    nodes = [dict(r) for r in db.connect().execute(
        "SELECT * FROM project_knowledge_nodes WHERE project_id=? ORDER BY updated_at", (project_id,)).fetchall()]
    for n in nodes:
        for key in ("evidence_classes", "missing_perspectives"):
            try:
                n[key] = json.loads(n[key] or "[]")
            except ValueError:
                pass
    order = {"strong": 0, "developing": 1, "weak": 2, "missing": 3}
    nodes.sort(key=lambda n: (order.get(n["state"], 9), n["topic"]))
    return {"nodes": nodes, "counts": {s: sum(1 for n in nodes if n["state"] == s) for s in NODE_STATES}}


def state(project_id: str, max_claims: int = STATE_MAX_CLAIMS) -> dict[str, Any]:
    """Everything the Research view / Chat / Discover need, $0. Claims are capped (accepted and strong first) so a
    thousand-finding project returns a page, not a dump; `claims_total` carries the real count.

    **`max_claims=0` returns no claim rows at all**, and that is what the API endpoint now asks for (0.63.8).
    Measured on Kyle's project: `/research` was 774 KB, of which `claims` was **546 KB** — 300 rows averaging 1.8 KB,
    206 KB of it their attached evidence — and **nothing in the UI reads the key.** `claims_view.query` replaced
    this list in the 0.45.5 workbench rebuild and the list was never removed from the response; `renderResearch`
    reads only `map`, `targets`, `tensions` and `attention`. Same fault as `area_of_claim` in 0.62.7, one layer
    along: a list nobody re-measured after the surface that consumed it was replaced.

    `claims_total`, `claim_stats` and `freshness_counts` are computed from the WHOLE set either way, so nothing
    that reports a number loses accuracy — only the rows go."""
    nodes = [dict(r) for r in db.connect().execute("SELECT * FROM project_knowledge_nodes WHERE project_id=? ORDER BY updated_at", (project_id,)).fetchall()]
    if not nodes:
        m = refresh(project_id)
    else:
        for n in nodes:
            for k in ("evidence_classes", "missing_perspectives"):
                try:
                    n[k] = json.loads(n[k] or "[]")
                except ValueError:
                    pass
        order = {"strong": 0, "developing": 1, "weak": 2, "missing": 3}
        nodes.sort(key=lambda n: (order.get(n["state"], 9), n["topic"]))
        m = {"nodes": nodes, "counts": {s: sum(1 for n in nodes if n["state"] == s) for s in NODE_STATES}}
    all_claims = [c for c in claims.list_for_project(project_id) if c["status"] != "superseded"]
    all_claims.sort(key=lambda c: (0 if c["status"] == "accepted" else 1 if c["status"] == "proposed" else 2, _STRENGTH_ORDER.get(c["strength"], 9), -(c.get("updated_at") or 0)))
    page = []
    for c in (all_claims[:max_claims] if max_claims else []):
        c = dict(c)
        c["evidence_total"] = len(c["evidence"])
        c["evidence"] = c["evidence"][:STATE_MAX_EVIDENCE]
        page.append(c)
    targets_all, tensions_all = list_targets(project_id), list_tensions(project_id, status="open")
    from . import candidates as _cands
    known = _cands.link_counts(project_id, "evidence_target")                      # B3: open questions remember what could fill them
    for tg in targets_all:
        tg["known_uncaptured"] = known.get(tg["id"], 0)
    tension_counts: dict[str, int] = {}
    for t in tensions_all:
        tension_counts[t["kind"]] = tension_counts.get(t["kind"], 0) + 1
    freshness_counts: dict[str, int] = {}
    for c in all_claims:
        k = c.get("freshness_status") or "uncertain"
        freshness_counts[k] = freshness_counts.get(k, 0) + 1
    return {"map": m, "claims": page, "claims_truncated": len(page) < len(all_claims), "claims_total": len(all_claims), "targets_total": len(targets_all), "tensions_total": len(tensions_all), "tension_counts": tension_counts, "freshness_counts": freshness_counts, "targets": targets_all[:STATE_MAX_LIST], "tensions": tensions_all[:STATE_MAX_LIST],
            "claim_stats": claims.stats(project_id)}


def summary_text(project_id: str, max_items: int = 6) -> str:
    """Compact research state for a system block / Discover header."""
    st = state(project_id)
    m = st["map"]
    lines = ["Research coverage: " + " · ".join(f"{k.capitalize()} {v}" for k, v in m["counts"].items())]
    for n in m["nodes"][:max_items]:
        lines.append(f"- {n['topic']}: {n['state'].upper()} — {n['why'][:160]}")
    for t in st["tensions"][:max_items]:
        lines.append(f"- ⚠ {t['kind']}: {t['description'][:160]}")
    for tg in [x for x in st["targets"] if x["status"] == "open"][:max_items]:
        lines.append(f"- target ({tg['sufficiency']}): {tg['question'][:120]} — closure: {(tg.get('closure') or '')[:100]}")
    return "\n".join(lines)
