"""Research rebuild R3/R5/R6 (0.37.0) — the human-facing reading of the G5 research state, deterministic and $0.

The evidence engine (claims.py / knowledge.py) keeps score; this module answers the five-second questions the Research
tab must answer: what does the project understand, what is unresolved, what could change the decision, what to work on
next, what Neuro Search can do about it. Nothing here writes research state or calls a model; everything is derived from
Claims, Evidence Targets ("open questions"), tensions ("watch-outs") and knowledge nodes, and every ranking rule is a
number in this file so it can be inspected and tested.

    PRIORITY  — one deterministic score per actionable item (open question | watch-out); the Overview shows the top few
    WATCH-OUTS — Claim-level tensions aggregated into issues (one issue may stand for 17 stale Claims)
    AREAS      — stable, human-readable Research Areas clustered over the token-like topic nodes ($0; a model may name them
                 better later, nothing depends on it)
    ATTENTION  — the sidebar number: what genuinely asks for the user, never the Claim count
"""
from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from typing import Any

from . import claims, db, knowledge

# ---------------------------------------------------------------- the score (documented; change = a decision)

BASE = {"question:governing": 40, "question:corroborative": 30,
        "watchout:CONTRADICTION": 45, "watchout:MISSING_PERSPECTIVE": 35, "watchout:STALE": 30, "watchout:WEAK_CONSENSUS": 25, "watchout:NOVEL": 15}
IMPORTANCE_WEIGHT = 5          # × the linked finding's importance (1–5)
PLANNER_BONUS = 15             # a Claim the Master Plan's evidence leans on
IMPACT = {"high": 15, "medium": 0, "low": -10}
APPLICABILITY_BONUS = 8        # strong evidence whose applicability to the user is still undecided
BREADTH_PER_CLAIM, BREADTH_CAP = 3, 12
KNOWN_SOURCES_BONUS = 8        # promising candidates already known: the action is cheap
RECENT_BONUS, RECENT_DAYS = 5, 7
IMPORTANT_QUESTION = 60        # score at/above which a question counts as "important" for the summary and the badge
WATCHOUT_ATTENTION_IMPACTS = ("high", "medium")

GENERIC_TOPICS = {"general", "both", "year", "years", "also", "thing", "things", "make", "made", "take", "time", "first", "good", "well", "just", "like",
                  "really", "need", "want", "know", "think", "much", "many", "way", "lot", "one", "two", "three", "said", "says", "going", "get", "got",
                  "use", "used", "using", "case", "cases", "part", "point", "kind", "sort", "example", "people", "person", "someone", "something", "anything",
                  "account", "annual", "asset", "buyer", "build", "capital", "build", "business", "company", "firm", "practice", "owner", "seller", "deal"}
# ↑ the last row: words that name the project's WHOLE subject (an accounting-practice acquisition) and therefore split nothing;
#   they are still fine inside an area's name when they are distinctive for that area relative to the others.

AREA_MIN_CLAIMS = 3
AREA_MERGE = 0.22              # Jaccard over topic-node term bags at/above which two nodes are one area
AREA_TERMS = 40                # term bag size per node


# ---------------------------------------------------------------- inputs

def _importance(project_id: str) -> dict[str, int]:
    imp = {r["id"]: int(r["importance"] or 3) for r in db.connect().execute("SELECT id, importance FROM project_notes WHERE project_id=?", (project_id,)).fetchall()}
    out = {}
    for r in db.connect().execute("SELECT id, origin_note_id, origin FROM project_claims WHERE project_id=?", (project_id,)).fetchall():
        out[r["id"]] = 5 if r["origin"] == "user" else imp.get(r["origin_note_id"] or -1, 3)
    return out


def _planner_dependent(project_id: str, cl: list[dict[str, Any]]) -> set[str]:
    plan = db.latest_plan(project_id)
    if not plan:
        return set()
    emap = (plan.get("plan") or {}).get("_evidence") or {}
    labels = [(v.get("source_id"), v.get("label") or "") for v in emap.values()]
    dep = set()
    for c in cl:
        srcs = {e["source_id"] for e in c.get("evidence") or []}
        if any(sid in srcs and claims.overlap(lbl, c["text"]) >= 0.5 for sid, lbl in labels):
            dep.add(c["id"])
    return dep


def _load(project_id: str) -> dict[str, Any]:
    cl = [c for c in claims.list_for_project(project_id) if c["status"] != "superseded"]
    by_id = {c["id"]: c for c in cl}
    targets = [t for t in knowledge.list_targets(project_id) if t["status"] != "dropped"]
    tensions = knowledge.list_tensions(project_id, status="open")
    nodes = [dict(r) for r in db.connect().execute("SELECT * FROM project_knowledge_nodes WHERE project_id=?", (project_id,)).fetchall()]
    from . import candidates
    known = candidates.link_counts(project_id, "evidence_target")
    titles = {r["id"]: (r["title"] or "").strip() for r in db.connect().execute("SELECT id, title FROM project_notes WHERE project_id=?", (project_id,)).fetchall()}
    labels = {c["id"]: _label(c, titles) for c in cl}
    return {"claims": cl, "by_id": by_id, "targets": targets, "tensions": tensions, "nodes": nodes, "importance": _importance(project_id),
            "planner": _planner_dependent(project_id, cl), "known": known, "titles": titles, "labels": labels}


def _label(c: dict[str, Any], titles: dict[int, str]) -> str:
    """A short human label for a Claim: the finding title Kyle already reads when there is one, else the Claim's opening words."""
    t = titles.get(c.get("origin_note_id") or -1) or ""
    if 2 <= len(t.split()) <= 8:
        return _title_case(t)
    text = c.get("text") or ""
    head = text.split(" — ", 1)[0]
    if head != text and 2 <= len(head.split()) <= 8:           # "Finding title — proposition" (how harvest writes titled findings)
        return _title_case(head)
    if len(text) <= 70:
        return _title_case(text)
    cut = text[:70].rsplit(" ", 1)[0]
    return _title_case(cut) + "…"


# ---------------------------------------------------------------- plain language

SUFFICIENCY_TEXT = {"governing": "One current authoritative source can settle this.", "corroborative": "This needs independent confirmation."}
KIND_TITLE = {"STALE": "{area} evidence may be outdated", "WEAK_CONSENSUS": "Not enough independent evidence on {area}", "CONTRADICTION": "Sources disagree about {area}",
              "MISSING_PERSPECTIVE": "{area}: we are hearing from one side only", "NOVEL": "A lone viewpoint on {area} has little corroboration"}
KIND_ACTION = {"STALE": ("Find current evidence", "Searches this project, your library and previously seen sources for newer evidence on these Claims. No web search."),
               "WEAK_CONSENSUS": ("Find independent confirmation", "Looks for sources that do not repeat the ones you already have. No web search."),
               "CONTRADICTION": ("Review the disagreement", "Opens the Claims that disagree so you can decide which to rely on."),
               "MISSING_PERSPECTIVE": ("Find the missing perspective", "Looks for sources from the perspective that is absent (owners, sellers, professionals…). No web search."),
               "NOVEL": ("Look for corroboration", "Checks whether anyone else reports this. No web search.")}
KIND_IF_IGNORED = {"STALE": "Chat and the Master Plan keep treating these as needing re-verification.",
                   "WEAK_CONSENSUS": "Chat will keep hedging: several sources, none independent.",
                   "CONTRADICTION": "Chat will present both sides as unsettled.",
                   "MISSING_PERSPECTIVE": "Advice stays one-sided; the Master Plan cannot weigh the other side.",
                   "NOVEL": "The point stays a single-source observation, never a finding you can lean on."}


def _title_case(s: str) -> str:
    """Sentence case for a finding title used as an area name: first letter up, the rest as written (keeps SBA, SOP…)."""
    s = s.strip().rstrip(".")
    return (s[:1].upper() + s[1:]) if s else s


def _missing_of(t: dict[str, Any]) -> list[str]:
    """The perspectives a MISSING_PERSPECTIVE tension names as absent ("… missing expert, market perspective(s)")."""
    m = re.search(r"missing ([a-z, ]+?) perspective", t.get("description") or "")
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def _area_name_for(topic: str | None, area_of: dict[str, str]) -> str:
    return area_of.get(topic or "", (topic or "general").replace("_", " ").title())


# ---------------------------------------------------------------- Research Areas ($0 clustering over the topic nodes)

def areas(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stable, human-readable clusters over the knowledge nodes. Nodes whose topic is a generic word or that hold too few
    Claims are folded into the nearest cluster rather than shown; names come from each cluster's most distinctive terms."""
    d = data or _load(project_id)
    cl, nodes = d["claims"], d["nodes"]
    if not cl:
        return {"areas": [], "area_of_topic": {}}
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cl:
        by_topic[c.get("topic") or "general"].append(c)
    bags: dict[str, Counter] = {}
    for t, cs in by_topic.items():
        bag: Counter = Counter()
        for c in cs:
            bag.update(claims._tokens(c["text"]))
        bags[t] = Counter(dict(bag.most_common(AREA_TERMS)))
    real = [t for t in by_topic if t not in GENERIC_TOPICS and len(by_topic[t]) >= AREA_MIN_CLAIMS]
    minor = [t for t in by_topic if t not in real]
    # greedy agglomeration over the real nodes, largest first, deterministic order
    real.sort(key=lambda t: (-len(by_topic[t]), t))
    clusters: list[dict[str, Any]] = []

    def jac(a: Counter, b: Counter) -> float:
        sa, sb = set(a), set(b)
        return len(sa & sb) / max(1, len(sa | sb))
    for t in real:
        best, best_j = None, 0.0
        for cl_ in clusters:
            j = jac(bags[t], cl_["bag"])
            if j > best_j:
                best, best_j = cl_, j
        if best is not None and best_j >= AREA_MERGE:
            best["topics"].append(t)
            best["bag"] = best["bag"] + bags[t]
        else:
            clusters.append({"topics": [t], "bag": Counter(bags[t])})
    if not clusters:
        clusters.append({"topics": [], "bag": Counter()})
    for t in minor:                                             # fold generic/small topics into the nearest cluster (never a card of their own)
        best = max(clusters, key=lambda cl_: jac(bags[t], cl_["bag"]) if cl_["bag"] else 0.0)
        best["topics"].append(t)
        best["bag"] = best["bag"] + bags[t]
    # names: the finding titles Kyle already reads (most common in the cluster, up to two) — a title is a human label, a
    # token is not; fall back to the terms most distinctive for the cluster against the others (tf × 1/df)
    titles = d["titles"]
    df: Counter = Counter()
    for cl_ in clusters:
        df.update(set(cl_["bag"]))
    used_names: set[str] = set()
    out = []
    for cl_ in clusters:
        tc: Counter = Counter()
        for t in cl_["topics"]:
            for c in by_topic[t]:
                title = titles.get(c.get("origin_note_id") or -1) or ""
                if 2 <= len(title.split()) <= 8:
                    tc[title] += 1
        ranked = sorted(tc.items(), key=lambda kv: (-kv[1], kv[0]))
        name = " · ".join(_title_case(t) for t, _ in ranked[:2])
        if not name:
            scored = sorted(((cnt / (1 + df[w] - 1) * (1.0 if w not in GENERIC_TOPICS else 0.4), w) for w, cnt in cl_["bag"].items()), reverse=True)
            words = []
            for _, w in scored:
                if w in words or any(w.startswith(x) or x.startswith(w) for x in words):
                    continue
                words.append(w)
                if len(words) == 3:
                    break
            name = " & ".join(x.replace("-", " ").title() for x in words[:2]) or "General"
            if name in used_names:
                name = " & ".join(x.replace("-", " ").title() for x in words[:3]) or name
        n, base = 2, name
        while name in used_names:
            name, n = f"{base} ({n})", n + 1
        used_names.add(name)
        cl_["name"] = name
        out.append(cl_)
    area_of: dict[str, str] = {t: cl_["name"] for cl_ in out for t in cl_["topics"]}
    # per-area state and summary
    tg_by_topic: dict[str, list] = defaultdict(list)
    for t in d["targets"]:
        if t["status"] == "open":
            key = (d["by_id"].get(t.get("claim_id") or "") or {}).get("topic") or t.get("topic") or "general"
            tg_by_topic[key].append(t)
    ts_by_topic: dict[str, list] = defaultdict(list)
    for t in d["tensions"]:
        key = (d["by_id"].get(t.get("claim_id") or "") or {}).get("topic") or "general"
        ts_by_topic[key].append(t)
    cards = []
    for cl_ in out:
        cs = [c for t in cl_["topics"] for c in by_topic[t]]
        strong = sum(1 for c in cs if c["strength"] == "strong")
        weak = sum(1 for c in cs if c["strength"] in ("weak", "unsupported"))
        stale = sum(1 for c in cs if c.get("freshness_status") in ("stale", "needs_refresh"))
        accepted = sum(1 for c in cs if c["status"] == "accepted")
        qs = [t for tp in cl_["topics"] for t in tg_by_topic.get(tp, [])]
        ws = [t for tp in cl_["topics"] for t in ts_by_topic.get(tp, [])]
        n = max(1, len(cs))
        if strong / n >= 0.5 and not any(w["kind"] == "CONTRADICTION" for w in ws):
            state = "strong"
        elif strong + sum(1 for c in cs if c["strength"] == "developing") >= n / 2:
            state = "developing"
        elif cs:
            state = "weak"
        else:
            state = "missing"
        understand = (f"{strong} well-evidenced conclusion{'s' if strong != 1 else ''}" if strong else "no well-evidenced conclusions yet") + (f", {accepted} adopted" if accepted else "")
        attention = []
        if qs:
            attention.append(f"{len(qs)} open question{'s' if len(qs) != 1 else ''}")
        if stale:
            attention.append(f"{stale} Claim{'s' if stale != 1 else ''} may be outdated")
        if any(w["kind"] == "CONTRADICTION" for w in ws):
            attention.append("sources disagree")
        if any(w["kind"] == "MISSING_PERSPECTIVE" for w in ws):
            attention.append("one perspective only")
        if weak and not qs:
            attention.append(f"{weak} thinly evidenced")
        cards.append({"name": cl_["name"], "topics": sorted(cl_["topics"]), "state": state, "claims": len(cs), "strong": strong, "weak": weak, "stale": stale, "accepted": accepted,
                      "open_questions": len(qs), "watchouts": len(ws), "understand": understand, "attention": attention})
    order = {"weak": 0, "missing": 1, "developing": 2, "strong": 3}
    cards.sort(key=lambda a: (order[a["state"]], -a["claims"], a["name"]))
    return {"areas": cards, "area_of_topic": area_of}


# ---------------------------------------------------------------- watch-outs (issues, not rows)

def watchouts(project_id: str, data: dict[str, Any] | None = None, area_of: dict[str, str] | None = None) -> list[dict[str, Any]]:
    d = data or _load(project_id)
    if area_of is None:
        area_of = areas(project_id, d)["area_of_topic"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in d["tensions"]:
        topic = (d["by_id"].get(t.get("claim_id") or "") or {}).get("topic") or "general"
        groups[(t["kind"], _area_name_for(topic, area_of))].append(t)
    out = []
    for (kind, area), ts in groups.items():
        imp_rank = {"high": 0, "medium": 1, "low": 2}
        impact = min((t["impact"] for t in ts), key=lambda x: imp_rank.get(x, 1))
        cids = [t["claim_id"] for t in ts if t.get("claim_id")]
        importance = max((d["importance"].get(c, 3) for c in cids), default=3)
        planner = any(c in d["planner"] for c in cids)
        subject = d["labels"].get(cids[0], area) if len(set(cids)) == 1 else area   # one Claim → its own label; several → the area
        title = KIND_TITLE[kind].format(area=subject) if kind in KIND_TITLE else f"{kind.replace('_', ' ').title()}: {subject}"
        if kind == "MISSING_PERSPECTIVE":
            missing = sorted({m for t in ts for m in _missing_of(t)})
            if missing:
                title = f"{subject}: no {' or '.join(missing[:2])} voice yet"
        n = len(ts)
        detail = {"STALE": f"{n} Claim{'s' if n != 1 else ''} rel{'y' if n != 1 else 'ies'} on evidence that may no longer be current.",
                  "WEAK_CONSENSUS": f"{n} Claim{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} supported by several sources that repeat one another.",
                  "CONTRADICTION": f"{n} pair{'s' if n != 1 else ''} of Claims disagree.",
                  "MISSING_PERSPECTIVE": f"{n} Claim{'s' if n != 1 else ''} {'come' if n != 1 else 'comes'} from one perspective only.",
                  "NOVEL": f"{n} Claim{'s' if n != 1 else ''} {'rest' if n != 1 else 'rests'} on a single source nobody else corroborates."}[kind]
        score = BASE[f"watchout:{kind}"] + IMPORTANCE_WEIGHT * importance + IMPACT.get(impact, 0) + (PLANNER_BONUS if planner else 0) + min(BREADTH_CAP, BREADTH_PER_CLAIM * (n - 1))
        action, action_help = KIND_ACTION[kind]
        out.append({"id": f"wo:{kind}:{area}", "kind": kind, "area": area, "title": title, "impact": impact, "importance": importance, "planner_dependent": planner,
                    "claims": n, "detail": detail, "if_ignored": KIND_IF_IGNORED[kind], "action": {"label": action, "help": action_help, "cost": "$0"},
                    "underlying": [{"tension_id": t["id"], "claim_id": t.get("claim_id"), "claim": (t.get("claim_text") or "")[:160], "description": t["description"][:200]} for t in ts],
                    "score": score})
    out.sort(key=lambda w: (-w["score"], w["title"]))
    return out


# ---------------------------------------------------------------- open questions (evidence targets, in plain language)

def questions(project_id: str, data: dict[str, Any] | None = None, area_of: dict[str, str] | None = None) -> list[dict[str, Any]]:
    d = data or _load(project_id)
    if area_of is None:
        area_of = areas(project_id, d)["area_of_topic"]
    out = []
    now = time.time()
    for t in d["targets"]:
        c = d["by_id"].get(t.get("claim_id") or "") or {}
        topic = c.get("topic") or t.get("topic") or "general"
        importance = d["importance"].get(c.get("id") or "", 3) if c else (5 if t.get("origin") == "user" else 3)
        planner = bool(c) and c["id"] in d["planner"]
        known = d["known"].get(t["id"], 0)
        esc = (t.get("last_escalation") or {}).get("steps") or []
        looked = [s["step"] for s in esc]
        score = 0
        if t["status"] == "open":
            score = BASE[f"question:{t['sufficiency']}"] + IMPORTANCE_WEIGHT * importance + (PLANNER_BONUS if planner else 0) \
                + (APPLICABILITY_BONUS if c and c.get("strength") == "strong" and c.get("application") == "unknown" else 0) \
                + (KNOWN_SOURCES_BONUS if known else 0) + (RECENT_BONUS if now - (t.get("updated_at") or 0) < RECENT_DAYS * 86400 else 0)
        current = (f"Evidence so far: {c['strength']} — {c.get('strength_why') or ''}".strip(" —") if c else "No Claim yet holds this; the question is open from the brief or a tension.")
        gap = t.get("gap") or ("satisfied" if t["status"] == "satisfied" else "not yet looked at")
        already = [{"project_evidence": "This project", "global_library": "Your library", "candidate_index": "Previously seen sources", "external": "The web"}.get(s, s) for s in looked
                   if not (s == "external" and not any(x.get("run") for x in esc if x.get("step") == "external"))]
        actions = [{"label": "Search my existing research", "endpoint": f"/api/targets/{t['id']}/pursue", "body": {"external": False}, "cost": "$0",
                    "help": "Checks this project, your global library, and previously seen sources. No web search."}]
        if known:
            actions.append({"label": f"Check {min(known, 3)} promising source{'s' if min(known, 3) != 1 else ''}", "endpoint": f"/api/targets/{t['id']}/capture-best", "body": {"n": min(known, 3)}, "cost": "$0 (browser capture when needed)",
                            "help": "Attaches copies you already own; otherwise captures the source through the normal path — your browser when the server cannot read it."})
        actions.append({"label": "Find new sources online", "endpoint": f"/api/targets/{t['id']}/pursue", "body": {"external": True}, "cost": "uses discovery budget",
                        "help": "Looks outside your library and proposes sources for review before anything is ingested."})
        label = d["labels"].get(c.get("id") or "") or (t["question"].split(":", 1)[-1].strip()[:70] if ":" in t["question"] else t["question"][:70])
        headline = (f"Does anyone else confirm this: {label}?" if t["sufficiency"] == "corroborative" else f"What does the authoritative source say: {label}?")
        out.append({"id": t["id"], "question": t["question"], "headline": headline, "label": label, "area": _area_name_for(topic, area_of), "status": t["status"], "importance": importance, "important": score >= IMPORTANT_QUESTION or importance >= 4 or planner,
                    "planner_dependent": planner, "what_settles_it": SUFFICIENCY_TEXT.get(t["sufficiency"], t.get("closure") or ""), "closure": t.get("closure"), "current": current, "gap": gap,
                    "why_asking": ("the Master Plan depends on it" if planner else f"a finding you rated {importance}/5" if importance >= 4 else "it came up while building the research state"),
                    "already_checked": already, "known_uncaptured": known, "if_ignored": "Chat and the Master Plan keep treating this as uncertain.", "actions": actions,
                    "claim_id": c.get("id"), "score": score, "updated_at": t.get("updated_at")})
    out.sort(key=lambda q: (0 if q["status"] == "open" else 1, -q["score"], q["question"]))
    return out


# ---------------------------------------------------------------- the overview

def overview(project_id: str, limit: int = 5) -> dict[str, Any]:
    d = _load(project_id)
    ar = areas(project_id, d)
    qs = questions(project_id, d, ar["area_of_topic"])
    ws = watchouts(project_id, d, ar["area_of_topic"])
    open_q = [q for q in qs if q["status"] == "open"]
    important = [q for q in qs if q["important"]]
    settled = [q for q in important if q["status"] == "satisfied"]
    nxt = sorted([{"type": "question", **q} for q in open_q] + [{"type": "watchout", **w} for w in ws], key=lambda x: (-x["score"], x.get("question") or x.get("title")))[:limit]
    refresh_areas = [a for a in ar["areas"] if a["stale"] and a["stale"] >= max(2, a["claims"] // 4)]
    weak_areas = [a for a in ar["areas"] if a["state"] in ("weak", "missing")]
    now = time.time()
    improved = []
    for q in qs:
        if q["status"] == "satisfied" and now - (q.get("updated_at") or 0) < 14 * 86400:
            improved.append({"kind": "question_settled", "text": q["question"], "detail": q.get("closure")})
    for c in d["claims"]:
        if c["strength"] == "strong" and now - (c.get("updated_at") or 0) < 14 * 86400 and c["status"] == "accepted":
            improved.append({"kind": "claim_strong", "text": c["text"][:160], "detail": c.get("strength_why")})
    awaiting = [c for c in d["claims"] if c["status"] == "proposed" and c["strength"] == "strong" and d["importance"].get(c["id"], 3) >= 4]
    attention = len([q for q in open_q if q["important"]]) + len([w for w in ws if w["impact"] in WATCHOUT_ATTENTION_IMPACTS]) + len(awaiting)
    summary = {"important_questions": len(important), "important_settled": len(settled), "open_questions": len(open_q),
               "issues": len([w for w in ws if w["impact"] in WATCHOUT_ATTENTION_IMPACTS]), "issues_total": len(ws),
               "areas_to_refresh": len(refresh_areas), "areas_weak": len(weak_areas), "areas_total": len(ar["areas"]), "claims_awaiting_decision": len(awaiting),
               "claims_total": len(d["claims"])}
    return {"summary": summary, "next": nxt, "recently_improved": improved[:6], "attention": min(attention, 99), "attention_capped": attention > 99,
            "areas": ar["areas"][:12], "empty": not d["claims"]}


def attention(project_id: str) -> int:
    """The sidebar number: important open questions + high/medium watch-outs + Claims awaiting an explicit decision. Never the Claim count."""
    try:
        return overview(project_id, limit=1)["attention"]
    except Exception:  # noqa: BLE001
        return 0
