"""F1/F2 — is this finding worth keeping? A $0, deterministic, model-free pass over a project's findings.

Why this exists. Kyle's objective is *"as many findings as possible provided they aren't trash"*, and on 2026-09-10
his live database held 13,480 findings of which 12,614 were auto-approved and **twelve** had ever been dismissed.
Nothing in the app checked whether a finding was vacuous or a near-duplicate of one already held, so the only
mechanism standing between him and noise was the length-aware cap in `findings.py` — which withholds findings he
already paid for (`reserve`) on the basis of source length, a proxy for quality that knows nothing about quality.
This module is the real check the cap was standing in for. Once it exists, the cap can be relaxed (F4), and that is
the whole point: the way to get MORE findings that are not trash is to be able to tell which ones are.

What it does NOT do. It never deletes, dismisses, hides or reorders anything. `review()` returns a list for a human
to sweep, and the only thing that changes a finding's status is the existing bulk accept/reject path — Kyle's
judgement, through one door, as everywhere else in this app. There is no quality *score*: every flag is a named,
explainable rule, because a single number would start silently overruling him.

Three protections, in priority order over any flag:
  1. a finding already used in a plan step, a chat answer, or a Claim is **never** flagged, however it reads —
     something the project has actually leaned on is not trash by definition (`findings_view.usage_map`);
  2. a finding the user has touched (importance set above the default, or status already decided by hand) is
     reported but never pre-selected;
  3. within a duplicate cluster the app proposes a KEEPER and flags the rest — it never proposes emptying a cluster.

Why lexical and not semantic. Findings have no embeddings (only chunks do), so a semantic pass would mean an
embedding call per finding — real money, on a corpus of 13,480, for a filter whose job is to save money. Shingle
overlap catches the case that actually occurs: the same proposition restated across sources in largely the same
words. A semantic pass is a separate, measured decision, and `NEAR_JACCARD` is where it would be compared.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from . import db

log = logging.getLogger(__name__)

# ---- duplicate detection ------------------------------------------------------------------------
SHINGLE = 3                  # content-word 3-grams: short enough for a 184-character median finding
NEAR_JACCARD = 0.62          # shingle overlap at which two findings say the same thing in the same words
CONTAIN_RATIO = 0.85         # ...or one finding's content words are almost wholly inside another's
MIN_SHINGLE_TOKENS = 6       # below this a finding has too few content words for shingles to mean anything
CLUSTER_MAX = 400            # never compare more than this many findings pairwise in one group

# ---- vacuity ------------------------------------------------------------------------------------
SHORT_CONTENT_TOKENS = 5     # content words, after stop words: fewer than this says almost nothing
TITLE_ECHO = 0.7             # share of a finding's content words that are already in its source's title
GENERIC_VERBS = {"discuss", "discusses", "discussed", "talk", "talks", "mention", "mentions", "mentioned",
                 "explain", "explains", "explained", "cover", "covers", "covered", "describe", "describes",
                 "note", "notes", "noted", "say", "says", "said", "share", "shares", "shared", "highlight",
                 "highlights", "emphasise", "emphasises", "emphasize", "emphasizes", "suggest", "suggests"}
VAGUE_OBJECTS = {"thing", "things", "stuff", "topic", "topics", "idea", "ideas", "point", "points", "aspect",
                 "aspects", "importance", "value", "benefit", "benefits", "way", "ways", "approach", "approaches",
                 "strategy", "strategies", "process", "concept", "concepts", "content", "video", "episode"}
STOP = {"the", "and", "for", "that", "this", "with", "から", "you", "your", "are", "was", "were", "his", "her",
        "its", "their", "they", "them", "have", "has", "had", "not", "but", "can", "could", "would", "should",
        "will", "when", "what", "which", "who", "how", "why", "than", "then", "there", "here", "more", "most",
        "some", "any", "all", "one", "two", "into", "from", "about", "over", "out", "off", "own", "very", "also",
        "just", "only", "because", "while", "after", "before", "between", "during", "such", "each", "other",
        "been", "being", "does", "did", "doing", "get", "gets", "got", "make", "makes", "made", "like", "even"}

FLAGS = ("duplicate", "no_specifics", "too_short", "echoes_title", "generic_only")
FLAG_TEXT = {
    "duplicate": "says the same thing as another finding you already have",
    "no_specifics": "names nothing specific — no number, name, or quoted phrase",
    "too_short": "too few words to carry a finding",
    "echoes_title": "mostly repeats the source's own title",
    "generic_only": "describes that the source talks about something, without saying what",
}


# ------------------------------------------------------------------ normalisation

def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'’\-]*", (text or "").lower())


def content_words(text: str) -> list[str]:
    return [w for w in _words(text) if len(w) > 2 and w not in STOP]


def _shingles(toks: list[str]) -> set[tuple[str, ...]]:
    if len(toks) < SHINGLE:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i:i + SHINGLE]) for i in range(len(toks) - SHINGLE + 1)}


def _has_specific(text: str) -> bool:
    """A number, a quoted phrase, a percentage or price, or a capitalised word that is not merely sentence-initial.
    This is the single strongest vacuity signal: a finding that names nothing cannot be checked against its source."""
    t = text or ""
    if re.search(r"\d", t) or '"' in t or "“" in t or "'" in t:
        return True
    # capitalised tokens after the first word (proper nouns, product names, acronyms)
    tokens = re.findall(r"\b[\w’'-]+\b", t)
    return any(re.match(r"^[A-Z][\w’'-]*$", w) and not w.isupper() or (w.isupper() and len(w) > 2)
               for w in tokens[1:])


# ------------------------------------------------------------------ per-finding rules

def vacuity(note: dict[str, Any], source_title: str | None = None) -> list[str]:
    """The named reasons this finding may say nothing. Deterministic, order-stable, no model, no network."""
    text = note.get("content") or ""
    cw = content_words(text)
    out: list[str] = []
    if len(cw) < SHORT_CONTENT_TOKENS:
        out.append("too_short")
    if not _has_specific(text):
        out.append("no_specifics")
    if source_title:
        tw = set(content_words(source_title))
        if tw and cw and len(set(cw) & tw) / len(set(cw)) >= TITLE_ECHO:
            out.append("echoes_title")
    # "the video discusses the importance of consistency" — a generic verb, a vague object, nothing else concrete
    if cw and any(w in GENERIC_VERBS for w in cw):
        concrete = [w for w in cw if w not in GENERIC_VERBS and w not in VAGUE_OBJECTS]
        if len(concrete) <= 2 and not _has_specific(text):
            out.append("generic_only")
    return out


# ------------------------------------------------------------------ duplicate clusters

def _keeper(notes: list[dict[str, Any]], usage: dict[int, dict[str, Any]]) -> int:
    """Which member of a duplicate cluster to keep: one the project already uses, else the most important, else the
    most specific, else the longest, else the oldest. Deterministic — the same cluster always keeps the same row."""
    def rank(n: dict[str, Any]) -> tuple:
        u = usage.get(n["id"]) or {}
        used = (u.get("plan") or 0) + (u.get("chat") or 0) + (1 if u.get("claim") else 0)
        return (-used, -int(n.get("importance") or 0), -int(_has_specific(n.get("content") or "")),
                -len(n.get("content") or ""), n["id"])
    return sorted(notes, key=rank)[0]["id"]


def clusters(notes: list[dict[str, Any]], usage: dict[int, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Groups of findings that say the same thing. Union-find over shingle overlap and near-containment; each group
    names a keeper and the duplicates of it. A finding with too few content words is never clustered — it is short,
    which `vacuity` reports separately, and shingle overlap on three words means nothing."""
    usage = usage or {}
    eligible = []
    for n in notes[:CLUSTER_MAX]:
        toks = content_words(n.get("content") or "")
        if len(toks) >= MIN_SHINGLE_TOKENS:
            eligible.append((n, set(toks), _shingles(toks)))
    parent: dict[int, int] = {n["id"]: n["id"] for n, _, _ in eligible}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(len(eligible)):
        ni, si, gi = eligible[i]
        for j in range(i + 1, len(eligible)):
            nj, sj, gj = eligible[j]
            inter = len(gi & gj)
            if inter:
                jac = inter / len(gi | gj)
                if jac >= NEAR_JACCARD:
                    union(ni["id"], nj["id"]); continue
            small, big = (si, sj) if len(si) <= len(sj) else (sj, si)
            if small and len(small & big) / len(small) >= CONTAIN_RATIO:
                union(ni["id"], nj["id"])

    by_root: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_id = {n["id"]: n for n, _, _ in eligible}
    for nid in parent:
        by_root[find(nid)].append(by_id[nid])
    out = []
    for root, members in by_root.items():
        if len(members) < 2:
            continue
        keep = _keeper(members, usage)
        out.append({"keeper_id": keep,
                    "keeper": next(m["content"] for m in members if m["id"] == keep),
                    "duplicate_ids": sorted(m["id"] for m in members if m["id"] != keep),
                    "size": len(members),
                    "sources": sorted({str(m.get("source_id")) for m in members if m.get("source_id")})})
    out.sort(key=lambda c: (-c["size"], c["keeper_id"]))
    return out


# ------------------------------------------------------------------ the review surface

def review(project_id: str, *, status: str | None = "approved", limit: int = 300,
           include_used: bool = False) -> dict[str, Any]:
    """One $0 pass: what looks like trash, why, and what to keep instead. Nothing is changed.

    `flagged` rows carry `flags` (rule names), `why` (the same in plain language), `pre_select` (safe to sweep in a
    batch) and `protected` (why it will never be pre-selected). `keep_instead` points a duplicate at its cluster's
    keeper so the user can see what survives before deciding."""
    from . import findings_view
    notes = db.list_project_notes(project_id, status=status)
    usage = findings_view.usage_map(project_id)
    titles: dict[str, str] = {}
    for sid in {str(n.get("source_id")) for n in notes if n.get("source_id")}:
        s = db.get_source(sid)
        if s:
            titles[sid] = s.get("title") or ""

    cl = clusters(notes, usage)
    dup_of: dict[int, int] = {}
    for c in cl:
        for d in c["duplicate_ids"]:
            dup_of[d] = c["keeper_id"]

    flagged: list[dict[str, Any]] = []
    counts: dict[str, int] = {f: 0 for f in FLAGS}
    protected_n = 0
    for n in notes:
        u = usage.get(n["id"]) or {}
        used = (u.get("plan") or 0) + (u.get("chat") or 0) + (1 if u.get("claim") else 0)
        fl = list(vacuity(n, titles.get(str(n.get("source_id")))))
        if n["id"] in dup_of:
            fl.insert(0, "duplicate")
        if not fl:
            continue
        for f in fl:
            counts[f] = counts.get(f, 0) + 1
        # protection 1: anything the project has leaned on is not trash, whatever it reads like
        protected = None
        if used:
            bits = [f"used in {u['plan']} plan step(s)" if u.get("plan") else "",
                    f"cited in {u['chat']} chat answer(s)" if u.get("chat") else "",
                    f"backs a {u['claim']} Claim" if u.get("claim") else ""]
            protected = "; ".join(b for b in bits if b)
        elif (n.get("status") or "approved") not in ("approved", "suggested"):
            protected = "you have already decided this one"
        elif int(n.get("importance") or 0) >= 4:
            protected = f"you rated it {n['importance']}/5"
        # protection 4: "Gross margin: 42%" is terse, not empty. A finding whose ONLY complaint is its length,
        # while it still names something checkable, is reported but never pre-selected — brevity is not vacuity.
        if protected is None and fl == ["too_short"] and _has_specific(n.get("content") or ""):
            protected = "short, but it does name something specific"
        if protected:
            protected_n += 1
            if not include_used:
                continue
        flagged.append({
            "id": n["id"], "content": n.get("content"), "title": n.get("title"),
            "source_id": n.get("source_id"), "importance": n.get("importance"), "status": n.get("status"),
            "flags": fl, "why": [FLAG_TEXT[f] for f in fl if f in FLAG_TEXT],
            "keep_instead": dup_of.get(n["id"]),
            "protected": protected, "pre_select": protected is None,
        })
    flagged.sort(key=lambda r: (0 if "duplicate" in r["flags"] else 1, -len(r["flags"]), r["id"]))
    total = len(notes)
    shown = flagged[:max(1, min(limit, 1000))]
    return {
        "project_id": project_id, "findings": total,
        "flagged": len(flagged), "shown": len(shown), "rows": shown,
        "clusters": cl[:60], "cluster_count": len(cl),
        "duplicates": len(dup_of), "protected": protected_n,
        "counts": counts,
        "share": round(len(flagged) / total, 4) if total else 0.0,
        "note": ("Nothing here has been changed. A finding already used in a plan, a chat answer or a Claim is never "
                 "listed as trash; one you rated 4+ or already judged is listed but never pre-selected. Within a "
                 "duplicate group one finding is always kept."),
        "rules": {f: FLAG_TEXT[f] for f in FLAGS},
        "thresholds": {"near_jaccard": NEAR_JACCARD, "contain_ratio": CONTAIN_RATIO, "shingle": SHINGLE,
                       "short_content_tokens": SHORT_CONTENT_TOKENS, "title_echo": TITLE_ECHO},
    }


def promotable(project_id: str, limit: int = 400) -> dict[str, Any]:
    """F5 — which withheld `reserve` findings are worth having after all.

    `reserve` is the overflow the length-aware cap declined to suggest: findings the user ALREADY PAID FOR that are
    never exported, planned on or harvested until promoted. Kyle's objective is more findings that are not trash, so
    the interesting question is not "raise the cap" (0.58.1 did that, for future sources) but "of what was already
    withheld, which would I actually want?" — and now there is a check that can answer it.

    A reserve finding is promotable when it is not vacuous AND not a near-duplicate of something already approved.
    That second test is the one that matters and is why this cannot just be "promote all": clustering runs across
    BOTH statuses, so a reserve note restating an approved one is skipped rather than promoted into a duplicate.
    Nothing is promoted here — the caller sweeps through `POST /api/notes/bulk-status`, as everywhere else."""
    from . import findings_view
    approved = db.list_project_notes(project_id, status="approved")
    reserve = db.list_project_notes(project_id, status="reserve")
    if not reserve:
        return {"reserve": 0, "promotable": 0, "rows": [], "skipped": {},
                "note": "no withheld findings — nothing was over the cap on this project"}
    usage = findings_view.usage_map(project_id)
    titles: dict[str, str] = {}
    for sid in {str(n.get("source_id")) for n in (approved + reserve) if n.get("source_id")}:
        srow = db.get_source(sid)
        if srow:
            titles[sid] = srow.get("title") or ""
    approved_ids = {n["id"] for n in approved}
    # cluster ACROSS statuses: a reserve finding that repeats an approved one is not a gain
    cl = clusters(approved + reserve, usage)
    covered: dict[int, int] = {}
    for c in cl:
        members = set(c["duplicate_ids"]) | {c["keeper_id"]}
        anchor_id = next((m for m in members if m in approved_ids), None)
        if anchor_id is None:
            continue
        for m in members:
            if m not in approved_ids:
                covered[m] = anchor_id
    rows: list[dict[str, Any]] = []
    skipped = {"already_covered": 0, **{f: 0 for f in FLAGS if f != "duplicate"}}
    for n in reserve:
        if n["id"] in covered:
            skipped["already_covered"] += 1
            continue
        fl = vacuity(n, titles.get(str(n.get("source_id"))))
        if fl == ["too_short"] and _has_specific(n.get("content") or ""):
            fl = []                                   # brevity is not vacuity (same rule as `review`)
        if fl:
            for f in fl:
                skipped[f] = skipped.get(f, 0) + 1
            continue
        rows.append({"id": n["id"], "content": n.get("content"), "title": n.get("title"),
                     "source_id": n.get("source_id"), "importance": n.get("importance"),
                     "why": "not a repeat of anything you have approved, and it names something specific"})
    rows.sort(key=lambda r: (-int(r["importance"] or 0), r["id"]))
    return {"reserve": len(reserve), "promotable": len(rows), "rows": rows[:max(1, min(limit, 1000))],
            "skipped": {k: v for k, v in skipped.items() if v},
            "note": ("These were withheld by the cap, not judged — you already paid for them. Listed here are the "
                     "ones that are not repeats of findings you have already approved and that name something "
                     "specific. Nothing is promoted until you press the button."),
            "action": {"method": "POST", "endpoint": "/api/notes/bulk-status", "body": {"status": "approved"}}}


def summary(project_id: str) -> dict[str, Any]:
    """The counts only — cheap enough for a chip in the Findings header."""
    r = review(project_id, limit=1)
    return {k: r[k] for k in ("findings", "flagged", "duplicates", "cluster_count", "protected", "counts", "share")}
