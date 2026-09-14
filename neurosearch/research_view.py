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

import hashlib
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
WATCHOUT_ATTENTION_IMPACTS = ("high",)          # the sidebar counts issues, not rows: high-impact issues + planner-dependent questions + Claims awaiting a decision

GENERIC_TOPICS = {"general", "both", "year", "years", "also", "thing", "things", "make", "made", "take", "time", "first", "good", "well", "just", "like",
                  "really", "need", "want", "know", "think", "much", "many", "way", "lot", "one", "two", "three", "said", "says", "going", "get", "got",
                  "use", "used", "using", "case", "cases", "part", "point", "kind", "sort", "example", "people", "person", "someone", "something", "anything",
                  "account", "annual", "asset", "buyer", "build", "capital", "build", "business", "company", "firm", "practice", "owner", "seller", "deal"}
# ↑ the last row: words that name the project's WHOLE subject (an accounting-practice acquisition) and therefore split nothing;
#   they are still fine inside an area's name when they are distinctive for that area relative to the others.

AREA_MIN_CLAIMS = 3
AREA_MERGE = 0.22              # Jaccard over topic-node term bags at/above which two nodes are one area
AREA_TERMS = 40                # term bag size per node
BULK_MIN_OVERLAP = 0.15        # a bulk Claim joins an area when at least this share of its words are the area's words; else "Everything else"


# ---------------------------------------------------------------- inputs

def _importance(project_id: str) -> dict[str, int]:
    imp = {r["id"]: int(r["importance"] or 3) for r in db.connect().execute("SELECT id, importance FROM project_notes WHERE project_id=?", (project_id,)).fetchall()}
    out = {}
    for r in db.connect().execute("SELECT id, origin_note_id, origin FROM project_claims WHERE project_id=?", (project_id,)).fetchall():
        out[r["id"]] = 5 if r["origin"] == "user" else imp.get(r["origin_note_id"] or -1, 3)
    return out


PLANNER_DEPENDENT_OVERLAP = 0.5    # a plan label this close to a Claim's text, on a source the Claim rests on


def _planner_dependent(project_id: str, cl: list[dict[str, Any]]) -> set[str]:
    """Which Claims the current plan leans on — a plan evidence label that matches the Claim's text AND sits on a
    source the Claim actually rests on.

    **The test is anchored on the source id, so the labels are indexed by it (0.63.21).** This was a list scanned
    per Claim: 16,191 Claims × 1,804 plan evidence entries = **87 million** evaluations of `sid in srcs`, measured
    at **23.2 s of a 34.5 s `/api/sources` call** on Kyle's project — and `/api/sources` only wanted the open
    questions, so it was paying for the whole research pass to score 471 skipped rows (0.62.2's lesson, one
    surface along).

    **And an entry with no `source_id` can never satisfy the test**, so it is dropped when the index is built
    rather than 16,191 times. `planner._evidence` attaches one only when it has one, and his plan is user
    constraints (`kind: "user"`, which by definition have no source) and pinned findings whose note carried none —
    so all 1,804 of his entries are unanchored, the index is empty, and the existing early return now answers in
    microseconds what used to take 23 seconds to prove. That is not a bug in his data: a plan built from what he
    told it has nothing for this test to match, and the function's answer was always the empty set.

    Labels are tokenised ONCE. `claims.overlap` tokenises both sides on every call, so the old loop re-tokenised
    the same 1,804 labels for every Claim that reached the second half of the `and`."""
    plan = db.latest_plan(project_id)
    if not plan:
        return set()                       # no plan: the evidence query is not run at all
    emap = (plan.get("plan") or {}).get("_evidence") or {}
    by_source: dict[str, list[set[str]]] = {}
    for v in emap.values():
        sid = v.get("source_id")
        if not sid:                        # unanchored: `sid in srcs` cannot hold, so it is not work to be done
            continue
        by_source.setdefault(sid, []).append(claims._tokens(v.get("label") or ""))
    if not by_source:
        return set()
    by_claim = claims.evidence_source_ids(project_id)
    dep = set()
    for c in cl:
        srcs = c.get("evidence_source_ids") or by_claim.get(c["id"]) or set()
        ct = None
        for sid in srcs:
            labels = by_source.get(sid)
            if not labels:
                continue
            if ct is None:
                ct = claims._tokens(c["text"])
            if any(_token_overlap(lbl, ct) >= PLANNER_DEPENDENT_OVERLAP for lbl in labels):
                dep.add(c["id"])
                break
    return dep


def _token_overlap(ta: set[str], tb: set[str]) -> float:
    """`claims.overlap` on token sets that were computed once. Same definition: the share of the SHORTER side's
    distinctive tokens present in the other."""
    if not ta or not tb:
        return 0.0
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(short & long_) / len(short)


def _load(project_id: str) -> dict[str, Any]:
    """Everything the five panes derive from, in one pass — with stage timings, because the last time this pass was
    slow the stage I would have optimised on inspection was not the stage that cost anything (0.62.1)."""
    from . import perf
    with perf.timed("rv.load.claims"):
        # NO evidence rows: `_planner_dependent` wanted a set of source ids and was being handed every excerpt of
        # every piece of evidence in the project to get them (0.63.10).
        cl = [c for c in claims.list_for_project(project_id, with_evidence=False) if c["status"] != "superseded"]
    by_id = {c["id"]: c for c in cl}
    with perf.timed("rv.load.targets"):
        targets = [t for t in knowledge.list_targets(project_id) if t["status"] != "dropped"]
        tensions = knowledge.list_tensions(project_id, status="open")
        nodes = [dict(r) for r in db.connect().execute("SELECT * FROM project_knowledge_nodes WHERE project_id=?", (project_id,)).fetchall()]
        from . import candidates
        known = candidates.link_counts(project_id, "evidence_target")
    with perf.timed("rv.load.titles"):
        titles = {r["id"]: (r["title"] or "").strip() for r in db.connect().execute("SELECT id, title FROM project_notes WHERE project_id=?", (project_id,)).fetchall()}
        labels = {c["id"]: _label(c, titles) for c in cl}
    with perf.timed("rv.load.importance"):
        importance = _importance(project_id)
    with perf.timed("rv.load.planner"):
        planner = _planner_dependent(project_id, cl)
    return {"claims": cl, "by_id": by_id, "targets": targets, "tensions": tensions, "nodes": nodes, "importance": importance,
            "planner": planner, "known": known, "titles": titles, "labels": labels}


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
# RD-5 (declutter audit): titles used to repeat the subject the area chip beside them already names
# ("Deal financing · Seller financing evidence may be outdated" over a chip reading "Deal financing ·
# Seller financing") whenever a watch-out spans several Claims and subject falls back to the area string
# itself. Titles now say only what is wrong; areaChip() is where.
KIND_TITLE = {"STALE": "Evidence may be outdated", "WEAK_CONSENSUS": "Not enough independent evidence", "CONTRADICTION": "Sources disagree",
              "MISSING_PERSPECTIVE": "We are hearing from one side only", "NOVEL": "A lone viewpoint has little corroboration"}
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

# 2026-09-14 - one fixed sentence per kind read fine alone but, stacked in a Watch-outs list where one kind (most
# often MISSING_PERSPECTIVE) can account for dozens of cards, it reads as a single paragraph copy-pasted with the
# topic swapped (flagged in the Research/Chat design audit). Same information, several ways to say it - picked
# deterministically per watch-out (stable across reloads: the same card always reads the same way) rather than
# randomly, via a hash of its own id, so this never turns into visible re-shuffling on every page load.
KIND_IF_IGNORED_ALTS = {
    "STALE": ["Chat and the Master Plan keep treating these as needing re-verification.",
              "Nothing here has been checked against anything newer - Chat and the Master Plan will keep flagging it as unverified.",
              "The evidence behind this stays on the clock: Chat and the Master Plan continue to treat it as due for a recheck."],
    "WEAK_CONSENSUS": ["Chat will keep hedging: several sources, none independent.",
                       "This looks better-supported than it is - Chat will keep qualifying it because the sources all trace back to the same original claim.",
                       "The source count stays misleading: Chat will continue to hedge since none of them independently confirm it."],
    "CONTRADICTION": ["Chat will present both sides as unsettled.",
                      "The disagreement stays open - Chat will keep surfacing both readings rather than picking one.",
                      "Nobody has decided which source to trust here, so Chat keeps presenting the conflict instead of an answer."],
    "MISSING_PERSPECTIVE": ["Advice stays one-sided; the Master Plan cannot weigh the other side.",
                            "The Master Plan keeps recommending from one vantage point only - it has nothing from the other side to weigh against it.",
                            "This stays a one-sided read: whoever the missing voice would represent never gets a say in the advice."],
    "NOVEL": ["The point stays a single-source observation, never a finding you can lean on.",
             "Nobody else has said this yet - it stays a one-source observation rather than something you can build on.",
             "This claim keeps resting on its lone source; without corroboration it can't graduate to something you can lean on."],
}


def _if_ignored_for(kind: str, watchout_id: str) -> str:
    """Deterministic pick from KIND_IF_IGNORED_ALTS so the same watch-out always reads the same way across
    reloads, while different watch-outs of the same kind don't all read identically."""
    alts = KIND_IF_IGNORED_ALTS.get(kind) or [KIND_IF_IGNORED.get(kind, "")]
    idx = int(hashlib.md5(watchout_id.encode()).hexdigest(), 16) % len(alts)
    return alts[idx]


def _title_case(s: str) -> str:
    """Sentence case for a finding title used as an area name: first letter up, the rest as written (keeps SBA, SOP…)."""
    s = s.strip().rstrip(".")
    return (s[:1].upper() + s[1:]) if s else s


def _missing_of(t: dict[str, Any]) -> list[str]:
    """The perspectives a MISSING_PERSPECTIVE tension names as absent ("… missing expert, market perspective(s)")."""
    m = re.search(r"missing ([a-z, ]+?) perspective", t.get("description") or "")
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def _area_for(claim_id: str | None, topic: str | None, area_of_claim: dict[str, str], area_of: dict[str, str]) -> str:
    """The area a Claim belongs to (bulk Claims are placed one by one), else the area its topic maps to."""
    if claim_id and claim_id in area_of_claim:
        return area_of_claim[claim_id]
    return _area_name_for(topic, area_of)


def _area_name_for(topic: str | None, area_of: dict[str, str]) -> str:
    return area_of.get(topic or "general", (topic or "general").replace("_", " ").title())


# ---------------------------------------------------------------- Research Areas ($0 clustering over the topic nodes)

def areas(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cached on the project's research revision (SPEED R3). At 8,557 Claims the uncached derivation below did not
    return in 250 s on Kyle's live project and saturated the server while it ran — the bulk-topic pass assigns EVERY
    Claim of a lone-word topic ("business" x1,243) against EVERY cluster, so its cost grows with the Claim pile that
    automatic extraction keeps enlarging. That is why the Research tab felt slower than the old version: it was.
    Caching does not make it cheap, it makes it paid ONCE per actual change instead of once per request; making it
    cheap is a separate rung, and reducing how fast Claims accumulate is Kyle's call."""
    if data is None:
        return _stale_ok(f"research_areas:{project_id}", db.project_research_revision(project_id),
                         lambda: _areas_uncached(project_id, None), label="research_areas")
    return _areas_uncached(project_id, data)


def _areas_uncached(project_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Stable, human-readable clusters over the knowledge nodes. Nodes whose topic is a generic word or that hold too few
    Claims are folded into the nearest cluster rather than shown; names come from each cluster's most distinctive terms."""
    d = data or _load(project_id)
    cl, nodes = d["claims"], d["nodes"]
    if not cl:
        return {"areas": [], "area_of_topic": {}, "area_of_claim": {}}
    from . import perf
    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cl:
        by_topic[c.get("topic") or "general"].append(c)
    # One tokenisation per Claim, reused by the bags and by the bulk placement below — it was being redone there
    # for every lone-word bulk Claim, and on this project that is thousands of them (0.63.10).
    with perf.timed("rv.areas.tokens"):
        toks_of = {c["id"]: set(claims._tokens(c["text"])) for c in cl}
    bags: dict[str, Counter] = {}
    with perf.timed("rv.areas.bags"):
        for t, cs in by_topic.items():
            bag: Counter = Counter()
            for c in cs:
                bag.update(toks_of[c["id"]])
            bags[t] = Counter(dict(bag.most_common(AREA_TERMS)))
    big = [t for t in by_topic if t not in GENERIC_TOPICS and len(by_topic[t]) >= AREA_MIN_CLAIMS]
    # a normalized topic reads like a domain ("acquisition due diligence framework"); a lone word ("cash", "deal", "buyer") never does —
    # single-word topics only stand on their own when the project has no multi-word topic at all
    multi = [t for t in big if len(t.split()) >= 2]
    real = multi or big
    minor = [t for t in by_topic if t not in real]
    # greedy agglomeration over the real nodes, largest first, deterministic order
    real.sort(key=lambda t: (-len(by_topic[t]), t))
    clusters: list[dict[str, Any]] = []
    _t_merge = time.perf_counter()

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
            best["bag"] = Counter(dict((best["bag"] + bags[t]).most_common(AREA_TERMS)))   # re-trim: a big cluster must not become a magnet
        else:
            clusters.append({"topics": [t], "bag": Counter(bags[t])})
    perf.record("rv.areas.agglomerate", time.perf_counter() - _t_merge)
    if not clusters:
        clusters.append({"topics": [], "bag": Counter()})
    core = [dict(topics=list(c["topics"]), bag=Counter(c["bag"])) for c in clusters]   # the real topics only, for naming
    for cl_ in clusters:
        cl_["members"] = [c for t in cl_["topics"] for c in by_topic[t]]
        cl_["sets"] = set(cl_["bag"])
    catch_all: dict[str, Any] | None = None
    _t_bulk = time.perf_counter()
    for t in minor:
        bulk = (len(t.split()) < 2 or t in GENERIC_TOPICS) and len(by_topic[t]) >= AREA_MIN_CLAIMS
        if not bulk:                                            # a small coherent topic folds whole into the nearest cluster (never a card of its own)
            best = max(range(len(clusters)), key=lambda i: jac(bags[t], clusters[i]["bag"]) if clusters[i]["bag"] else 0.0)
            clusters[best]["topics"].append(t)
            clusters[best]["members"].extend(by_topic[t])
            continue
        # a lone-word topic with many Claims ("business" ×1,243) is not a subject, it is unlabelled bulk: each Claim goes to the area its
        # own words belong to; a Claim that matches nothing goes to an explicit "Everything else" rather than inflating the largest area
        for c in by_topic[t]:
            toks = toks_of[c["id"]]
            best_i, best_s = -1, 0.0
            for i, cl_ in enumerate(clusters):
                sc = len(toks & cl_["sets"]) / max(1, len(toks)) if cl_["sets"] else 0.0
                if sc > best_s:
                    best_i, best_s = i, sc
            if best_i >= 0 and best_s >= BULK_MIN_OVERLAP:
                clusters[best_i]["members"].append(c)
                clusters[best_i].setdefault("bulk_topics", set()).add(t)
            else:
                if catch_all is None:
                    catch_all = {"topics": [], "bag": Counter(), "members": [], "sets": set(), "fixed_name": "Everything else"}
                catch_all["members"].append(c)
                catch_all.setdefault("bulk_topics", set()).add(t)
    perf.record("rv.areas.place_bulk", time.perf_counter() - _t_bulk)
    if catch_all is not None:
        clusters.append(catch_all); core.append(dict(topics=[], bag=Counter()))
    # names: the cluster's own normalized topics (multi-word labels a model or Kyle wrote) — the largest one, plus a second when it
    # is nearly as large; else the short finding titles Kyle already reads; else the terms most distinctive against the other clusters
    titles = d["titles"]
    df: Counter = Counter()
    for cl_ in clusters:
        df.update(set(cl_["bag"]))
    used_names: set[str] = set()
    out = []
    for i, cl_ in enumerate(clusters):
        labels = sorted(((len(by_topic[t]), t) for t in core[i]["topics"] if len(t.split()) >= 2), key=lambda x: (-x[0], x[1]))
        name = cl_.get("fixed_name") or ""
        if not name and labels:
            name = _title_case(labels[0][1])
            if len(labels) > 1 and labels[1][0] >= 0.6 * labels[0][0]:
                name += " · " + _title_case(labels[1][1])
        if not name:
            tc: Counter = Counter()
            for t in cl_["topics"]:
                for c in by_topic[t]:
                    title = titles.get(c.get("origin_note_id") or -1) or ""
                    if 2 <= len(title.split()) <= 6:
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
    area_of_claim: dict[str, str] = {c["id"]: cl_["name"] for cl_ in out for c in cl_["members"]}
    for cl_ in out:                                             # a bulk topic maps (for topic-level filters) to the area holding most of its Claims
        for t in cl_.get("bulk_topics") or ():
            if t not in area_of:
                counts = Counter(area_of_claim[c["id"]] for c in by_topic[t])
                area_of[t] = counts.most_common(1)[0][0]
    # per-area state and summary
    tg_by_area: dict[str, list] = defaultdict(list)
    for t in d["targets"]:
        if t["status"] == "open":
            tg_by_area[_area_for(t.get("claim_id"), (d["by_id"].get(t.get("claim_id") or "") or {}).get("topic") or t.get("topic"), area_of_claim, area_of)].append(t)
    ts_by_area: dict[str, list] = defaultdict(list)
    for t in d["tensions"]:
        if t.get("claim_id") in d["by_id"]:
            ts_by_area[area_of_claim.get(t["claim_id"], "General")].append(t)
    cards = []
    for cl_ in out:
        cs = cl_["members"]
        strong = sum(1 for c in cs if c["strength"] == "strong")
        weak = sum(1 for c in cs if c["strength"] in ("weak", "unsupported"))
        stale = sum(1 for c in cs if c.get("freshness_status") in ("stale", "needs_refresh"))
        accepted = sum(1 for c in cs if c["status"] == "accepted")
        qs = tg_by_area.get(cl_["name"], [])
        ws = ts_by_area.get(cl_["name"], [])
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
    return {"areas": cards, "area_of_topic": area_of, "area_of_claim": area_of_claim}


# ---------------------------------------------------------------- watch-outs (issues, not rows)

def watchouts(project_id: str, data: dict[str, Any] | None = None, area_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    d = data or _load(project_id)
    if area_map is None:
        area_map = areas(project_id, d)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for t in d["tensions"]:
        c = d["by_id"].get(t.get("claim_id") or "")
        if t.get("claim_id") and not c:
            continue                                            # a tension on a superseded/removed Claim is not an issue anyone can act on
        groups[(t["kind"], _area_for(t.get("claim_id"), (c or {}).get("topic"), area_map["area_of_claim"], area_map["area_of_topic"]))].append(t)
    out = []
    for (kind, area), ts in groups.items():
        imp_rank = {"high": 0, "medium": 1, "low": 2}
        impact = min((t["impact"] for t in ts), key=lambda x: imp_rank.get(x, 1))
        cids = [t["claim_id"] for t in ts if t.get("claim_id")]
        importance = max((d["importance"].get(c, 3) for c in cids), default=3)
        planner = any(c in d["planner"] for c in cids)
        subject = d["labels"].get(cids[0], area) if len(set(cids)) == 1 else area   # one Claim → its own label; several → the area
        title = KIND_TITLE[kind] if kind in KIND_TITLE else f"{kind.replace('_', ' ').title()}"
        if kind == "MISSING_PERSPECTIVE":
            missing = sorted({m for t in ts for m in _missing_of(t)})
            if missing:
                title = f"No {' or '.join(missing[:2])} voice yet"
        n = len(ts)
        detail = {"STALE": f"{n} Claim{'s' if n != 1 else ''} rel{'y' if n != 1 else 'ies'} on evidence that may no longer be current.",
                  "WEAK_CONSENSUS": f"{n} Claim{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} supported by several sources that repeat one another.",
                  "CONTRADICTION": f"{n} pair{'s' if n != 1 else ''} of Claims disagree.",
                  "MISSING_PERSPECTIVE": f"{n} Claim{'s' if n != 1 else ''} {'come' if n != 1 else 'comes'} from one perspective only.",
                  "NOVEL": f"{n} Claim{'s' if n != 1 else ''} {'rest' if n != 1 else 'rests'} on a single source nobody else corroborates."}[kind]
        score = BASE[f"watchout:{kind}"] + IMPORTANCE_WEIGHT * importance + IMPACT.get(impact, 0) + (PLANNER_BONUS if planner else 0) + min(BREADTH_CAP, BREADTH_PER_CLAIM * (n - 1))
        action, action_help = KIND_ACTION[kind]
        out.append({"id": f"wo:{kind}:{area}", "kind": kind, "area": area, "title": title, "impact": impact, "importance": importance, "planner_dependent": planner,
                    "claims": n, "detail": detail, "if_ignored": _if_ignored_for(kind, f"wo:{kind}:{area}"), "action": {"label": action, "help": action_help, "cost": "$0"},
                    "underlying": [{"tension_id": t["id"], "claim_id": t.get("claim_id"), "claim": (t.get("claim_text") or "")[:160], "description": t["description"][:200]} for t in ts],
                    "score": score})
    out.sort(key=lambda w: (-w["score"], w["title"]))
    return out


# ---------------------------------------------------------------- open questions (evidence targets, in plain language)

def questions(project_id: str, data: dict[str, Any] | None = None, area_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    d = data or _load(project_id)
    if area_map is None:
        area_map = areas(project_id, d)
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
        # A step that was RECORDED but did not run must never be reported as checked — the escalation record keeps
        # skipped steps (with the reason) for diagnostics, and this list is what the user reads. 0.57.0 generalised
        # the rule from `external` alone to every optional step, because the new `catalogue` step is skipped for any
        # question that does not ask for expert or authoritative evidence.
        OPTIONAL = ("external", "catalogue")
        ran = {x.get("step") for x in esc if x.get("run")}
        already = [{"project_evidence": "This project", "global_library": "Your library",
                    "candidate_index": "Previously seen sources", "external": "The web",
                    "catalogue": "Research catalogues"}.get(s, s)
                   for s in looked if not (s in OPTIONAL and s not in ran)]
        actions = [{"label": "Search my existing research", "endpoint": f"/api/targets/{t['id']}/pursue", "body": {"external": False}, "cost": "$0",
                    "help": "Checks this project, your global library, and previously seen sources. No web search."}]
        if known:
            actions.append({"label": f"Check {min(known, 3)} promising source{'s' if min(known, 3) != 1 else ''}", "endpoint": f"/api/targets/{t['id']}/capture-best", "body": {"n": min(known, 3)}, "cost": "$0 (browser capture when needed)",
                            "help": "Attaches copies you already own; otherwise captures the source through the normal path — your browser when the server cannot read it."})
        actions.append({"label": "Find new sources online", "endpoint": f"/api/targets/{t['id']}/pursue", "body": {"external": True}, "cost": "uses discovery budget",
                        "help": "Looks outside your library and proposes sources for review before anything is ingested."})
        label = d["labels"].get(c.get("id") or "") or (t["question"].split(":", 1)[-1].strip()[:70] if ":" in t["question"] else t["question"][:70])
        headline = (f"Does anyone else confirm this: {label}?" if t["sufficiency"] == "corroborative" else f"What does the authoritative source say: {label}?")
        out.append({"id": t["id"], "question": t["question"], "headline": headline, "label": label, "area": _area_for(c.get("id"), topic, area_map["area_of_claim"], area_map["area_of_topic"]), "status": t["status"], "importance": importance, "important": score >= IMPORTANT_QUESTION or importance >= 4 or planner,
                    "planner_dependent": planner, "what_settles_it": SUFFICIENCY_TEXT.get(t["sufficiency"], t.get("closure") or ""), "closure": t.get("closure"), "current": current, "gap": gap,
                    "why_asking": ("the Master Plan depends on it" if planner else f"a finding you rated {importance}/5" if importance >= 4 else "it came up while building the research state"),
                    "already_checked": already, "known_uncaptured": known, "if_ignored": "Chat and the Master Plan keep treating this as uncertain.", "actions": actions,
                    "claim_id": c.get("id"), "score": score, "updated_at": t.get("updated_at")})
    out.sort(key=lambda q: (0 if q["status"] == "open" else 1, -q["score"], q["question"]))
    return out


# ---------------------------------------------------------------- the overview

QUESTIONS_INLINE_MAX = 200      # how many open questions the shell carries; the rest are paged (0.62.7)


def user_changed(project_id: str) -> int:
    """A user's own decision must be visible on their next read (0.62.8).

    `_stale_ok` lets a read ride on the previous answer while background work churns the research revision — which
    is right for churn and WRONG for a person who just dismissed a watch-out or accepted a Claim and is looking at
    the screen. Two frozen gates caught exactly that
    (`test_attention_is_what_needs_the_user_not_the_claim_count`,
    `test_one_verdict_clears_a_whole_watch_out_and_dismissal_is_durable`) and they were right to.

    So the rule is by AUTHOR, not by age: harvest and assessment may be served stale, a human's verdict may not.
    Every path that records a person's decision drops these entries, so the next read recomputes."""
    from . import cache
    return (cache.invalidate(f"research_overview:{project_id}")
            + cache.invalidate(f"research_areas:{project_id}"))


def _stale_ok(key: str, revision: str, compute, *, label: str):
    """Serve the previous answer at once and refresh behind the screen (0.62.8).

    **Measured on Kyle's project with the queue otherwise idle**, right after 3,314 findings were approved at his
    request: `research/overview?full=1` took **38.7 s cold and 33.4 s WARM**, `/research` 75.5 s / 63.1 s, the
    Claims workbench 14.8 s / 47.9 s. Sampling `db.project_research_revision` every 2.5 s explained all of it at
    once — the claim count was moving **15,792 → 15,800 → 15,811**, about four a second, because `harvest` was
    turning those newly approved findings into Claims. Legitimate $0 work; but a strict revision key means every
    read recomputes while it runs, and the pass costs tens of seconds.

    So this is the third surface to learn the 0.61.2 lesson: **a cache whose key changes faster than its value can
    be computed is not a cache.** A research overview computed a minute ago is a true statement about a minute ago;
    a 33-second wait is not a better answer, it is the same answer late. `as_of_current` says which the caller has.

    Nothing is fabricated and nothing goes permanently stale: the value returned was computed by this app, one
    background thread brings it forward, and a caller that must have the current state can still call the
    uncached pass directly."""
    from . import cache
    got = cache.get_stale_ok(key, revision, compute, label=label, warm=True)
    val = got["value"]
    if isinstance(val, dict):
        val = {**val, "as_of_current": got["current"], "recomputing": got["pending"]}
    return val


def overview(project_id: str, limit: int = 5, full: bool = False, area_map: bool = False) -> dict[str, Any]:
    from . import cache
    return _stale_ok(f"research_overview:{project_id}:{limit}:{int(full)}:{int(area_map)}",
                     db.project_research_revision(project_id),
                     lambda: _overview_uncached(project_id, limit, full, area_map), label="research_overview")


def _overview_uncached(project_id: str, limit: int = 5, full: bool = False, area_map: bool = False) -> dict[str, Any]:
    """R3. `full=True` also returns the complete `questions` and `watchouts` lists computed in the SAME pass — the shell
    (R2) renders every pane from one request instead of paying for `_load()` four times."""
    d = _load(project_id)
    ar = areas(project_id, d)
    qs = questions(project_id, d, ar)
    ws = watchouts(project_id, d, ar)
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
    # the sidebar number: on a 4,000-Claim project "important open questions" is a crowd of hundreds, so the count is of things that
    # are few by construction — issues (already aggregated), questions the Master Plan rests on, and Claims waiting for a yes/no
    attention = len([q for q in open_q if q["planner_dependent"]]) + len([w for w in ws if w["impact"] in WATCHOUT_ATTENTION_IMPACTS]) + len(awaiting)
    summary = {"important_questions": len(important), "important_settled": len(settled), "open_questions": len(open_q),
               "issues": len([w for w in ws if w["impact"] in WATCHOUT_ATTENTION_IMPACTS]), "issues_total": len(ws),
               "areas_to_refresh": len(refresh_areas), "areas_weak": len(weak_areas), "areas_total": len(ar["areas"]), "claims_awaiting_decision": len(awaiting),
               "claims_total": len(d["claims"])}
    out = {"summary": summary, "next": nxt, "recently_improved": improved[:6], "attention": min(attention, 99), "attention_capped": attention > 99,
           "areas": ar["areas"][:12], "empty": not d["claims"]}
    if full:
        # 0.62.7 — MEASURED ON KYLE'S PROJECT: `overview?full=1` shipped **5,858 KB in 23.7 s**, and the shape says
        # exactly where it went — `questions` 4,802 KB over **2,703 targets** (2,667 of them open, so filtering by
        # status saves nothing), and `area_of_claim` 854 KB over 15,499 claims. Inside a question, `actions` alone is
        # 1,311 KB. The third instance of the same defect: a list nobody re-measured after the corpus grew (the
        # findings payload was 8 MB before 0.60.1, the sources list 4.6 MB before 0.46.3).
        #
        # `area_of_claim` is dropped outright because **the UI never reads it** — zero references in index.html; it
        # is an internal index `areas()` builds for its own use, and `claims_view.query` already carries a per-row
        # `area` for the rows on screen. It stays available behind `area_map=True` for any caller that wants it.
        #
        # `questions` is BOUNDED, never filtered: the order is the same score the Overview's "next" uses, so the
        # first page is the part a human would read first, and `questions_total` / `questions_truncated` say plainly
        # that there is more. The full list stays at `GET …/research/questions`, which the Questions pane pages
        # through — truncation is never silent, and no question becomes unreachable.
        head = sorted(qs, key=lambda q: (0 if q["status"] == "open" else 1, -q["score"]))[:QUESTIONS_INLINE_MAX]
        out.update({"questions": head, "questions_total": len(qs), "questions_open": len(open_q),
                    "questions_truncated": len(qs) > len(head),
                    "watchouts": ws, "areas": ar["areas"], "area_of_topic": ar["area_of_topic"]})
        if area_map:
            out["area_of_claim"] = ar["area_of_claim"]
    return out


def attention(project_id: str) -> int:
    """The sidebar number: high-impact watch-outs + planner-dependent open questions + Claims awaiting an explicit decision. Never the Claim count."""
    try:
        return overview(project_id, limit=1)["attention"]
    except Exception:  # noqa: BLE001
        return 0
