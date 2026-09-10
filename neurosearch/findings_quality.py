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
# CALIBRATED 2026-09-10 against Kyle's live corpus (10,380 approved findings in one project, read-only from the
# app's own hourly backup). The first version shipped two guesses and both were wrong:
#
#  · NEAR_JACCARD 0.62 caught 18 pairs in 10,380 notes. Sampling the bands showed 0.45-0.62 and 0.35-0.45 are ALL
#    genuine duplicates (the same proposition reworded), while 0.25-0.35 is mixed — "high-risk industries get worse
#    credit access" and "the six-digit industry code affects loan approval" share vocabulary and say different
#    things. So the boundary sits at 0.35, measured, not at 0.62, assumed.
#  · CLUSTER_MAX 400 compared only the first 400 findings of a project, which found ZERO duplicates on a corpus that
#    demonstrably contains hundreds — including two byte-identical pairs. A cap that silently makes the feature
#    useless at the only scale that matters is worse than no feature. Replaced by blocking.
#
# Blocking: pairs are only considered when they share a RARE content word (document frequency at or below
# BLOCK_DF_SHARE of the project's findings), which is how the whole corpus can be compared instead of a prefix of it.
SHINGLE = 3                  # content-word 3-grams: short enough for a 189-character median finding
NEAR_JACCARD = 0.35          # measured boundary between "the same proposition reworded" and "the same topic"
CONTAIN_RATIO = 0.85         # ...or one finding's content words are almost wholly inside another's. Kept: it catches
                             # real duplicates Jaccard misses (a shorter restatement of a longer finding, J as low
                             # as 0.12) and sampled at high precision.
MIN_SHINGLE_TOKENS = 6       # below this a finding has too few content words for shingles to mean anything
# Shingles catch near-VERBATIM repeats and miss PARAPHRASES, because a 3-gram of content words rarely survives a
# reordering. Measured on the live corpus: "Total project cost includes not just the purchase price but working
# capital and SBA/due diligence fees…" and "Total project cost includes the purchase price plus working capital plus
# SBA/due-diligence fees, not just the sticker price…" share a word SET and almost no 3-grams. So a set (bag of
# words) measure runs alongside. Sampled bands: 0.55-0.65 and 0.45-0.55 are true duplicates, 0.35-0.45 mostly true,
# 0.30-0.35 clearly mixed (two DIFFERENT off-topic videos, each described as off-topic, score 0.33). 0.50 is the
# conservative pick, because a false duplicate costs a real finding.
SET_JACCARD = 0.50
SET_MIN_SHARED = 4           # ...over at least this many shared content words
# THE MEASURED FLOOR OF THIS APPROACH. Three genuine duplicates found by hand across statuses score 0.33, 0.20 and
# 0.18 on set-Jaccard — e.g. "Posting regular progress updates on LinkedIn/Facebook/Instagram/Twitter attracts
# investors organically" vs "Posting real-time updates on LinkedIn, Facebook, or Instagram about the buying process
# draws in investors organically". No lexical threshold separates those from findings that merely share vocabulary.
# Catching them needs embeddings (one call per finding, ~$0.013 for 13k), which is a measured decision for Kyle and
# not something to assume. Until then: this filter reports a FLOOR on the duplicates present, never a ceiling.
BLOCK_MIN_NOTES = 600        # below this, compare every pair (600^2/2 is ~180k comparisons, trivial) — blocking on
                             # a small set excludes everything, because with five findings every word is "common"
BLOCK_DF_SHARE = 0.02        # a word in more than 2% of a project's findings is too common to block on
BLOCK_MAX = 400              # ignore a blocking word that would pair more than this many findings
PAIR_BUDGET = 8_000_000      # measured: Kyle's 10,380-finding project needs ~4M comparisons and converges at 192
                             # duplicates in 169 groups. At 400k it found 78 and logged that it was partial, which
                             # is the kind of quiet half-answer this codebase is supposed to refuse. 8M costs 3.8 s,
                             # which is why `review` is cached on the project's view revision rather than recomputed
                             # per request.

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


# Spelled-out quantities are just as specific as digits, and findings are prose: "Sellers finance ten percent of
# the purchase price via a seller note" was being flagged `no_specifics` for want of a numeral (0.59.0).
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand",
                "million", "billion", "half", "third", "quarter", "double", "triple", "percent", "percentage"}


def _has_specific(text: str) -> bool:
    """A number (digits OR words), a quoted phrase, a percentage or price, or a capitalised word that is not merely
    sentence-initial. The strongest vacuity signal: a finding that names nothing cannot be checked against its
    source."""
    t = text or ""
    if re.search(r"\d", t) or '"' in t or "“" in t or "'" in t:
        return True
    if set(_words(t)) & NUMBER_WORDS:
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
    for n in notes:
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

    by_tok: dict[int, tuple[set[str], set[tuple[str, ...]]]] = {n["id"]: (si, gi) for n, si, gi in eligible}
    all_ids = sorted(by_tok)
    if len(eligible) < BLOCK_MIN_NOTES:
        # small project: compare everything. One block containing every finding does exactly that, and keeps a
        # single code path below rather than two that can drift apart.
        blocks: dict[str, list[int]] = {"*": all_ids}
    else:
        # --- blocking: only compare findings that share a RARE word, so the whole project is covered rather than a
        # prefix of it. This is what replaced CLUSTER_MAX.
        df: dict[str, int] = {}
        for _, si, _ in eligible:
            for w in si:
                df[w] = df.get(w, 0) + 1
        cap = max(3, int(BLOCK_DF_SHARE * len(eligible)))
        blocks = defaultdict(list)
        for n, si, _ in eligible:
            for w in si:
                if df[w] <= cap:
                    blocks[w].append(n["id"])
    seen: set[tuple[int, int]] = set()
    compared = 0
    for w, ids in blocks.items():
        if len(ids) < 2 or (w != "*" and len(ids) > BLOCK_MAX):
            continue
        ids = sorted(ids)
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                key = (ids[x], ids[y])
                if key in seen:
                    continue
                seen.add(key)
                compared += 1
                if compared > PAIR_BUDGET:
                    log.warning("findings_quality: pair budget reached (%d) — duplicate detection is partial", PAIR_BUDGET)
                    break
                si, gi = by_tok[ids[x]]
                sj, gj = by_tok[ids[y]]
                inter = len(gi & gj)
                if inter and inter / len(gi | gj) >= NEAR_JACCARD:
                    union(ids[x], ids[y]); continue
                small, big = (si, sj) if len(si) <= len(sj) else (sj, si)
                if small and len(small & big) / len(small) >= CONTAIN_RATIO:   # a restatement inside a longer one
                    union(ids[x], ids[y]); continue
                tset = len(si & sj)
                if tset >= SET_MIN_SHARED and tset / len(si | sj) >= SET_JACCARD:   # a paraphrase
                    union(ids[x], ids[y])
            if compared > PAIR_BUDGET:
                break
        if compared > PAIR_BUDGET:
            break

    by_root: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[int, dict[str, Any]] = {n["id"]: n for n, _, _ in eligible}
    for nid in parent:
        by_root[find(nid)].append(by_id[nid])
    out = []
    for root, members in by_root.items():
        if len(members) < 2:
            continue
        keep = _keeper(members, usage)
        srcs = sorted({str(m.get("source_id")) for m in members if m.get("source_id")})
        # 0.59.0, Kyle: "even duplicate data is useful somehow". He is right, and this app already says so —
        # `claims.assess` treats independent sources agreeing as its STRONGEST evidence signal (corroborative
        # sufficiency), and `claim_evidence` tracks independence by creator and lineage precisely to count it.
        #
        # So a cluster means two opposite things depending on where its members came from:
        #   · one source, said twice  -> REDUNDANT. The same video repeating itself adds nothing.
        #   · several sources agreeing -> CORROBORATED. That is evidence, and the largest cluster in Kyle's corpus
        #     is one SBA pre-screening fact stated by FOUR different creators. Sweeping it would delete the
        #     strongest thing the project knows about that fact.
        # Before this, both were flagged `duplicate` and offered for dismissal, which inverted the value of the
        # second case. Only redundancy is ever proposed for a sweep.
        kind = "redundant" if len(srcs) <= 1 else "corroborated"
        out.append({"keeper_id": keep,
                    "keeper": next(m["content"] for m in members if m["id"] == keep),
                    "duplicate_ids": sorted(m["id"] for m in members if m["id"] != keep),
                    "size": len(members), "sources": srcs, "kind": kind,
                    "n_sources": len(srcs)})
    out.sort(key=lambda c: (0 if c["kind"] == "redundant" else 1, -c["size"], c["keeper_id"]))
    return out


# ------------------------------------------------------------------ the review surface

def review(project_id: str, *, status: str | None = "approved", limit: int = 300,
           include_used: bool = False, stale_ok: bool = False, warm: bool = True) -> dict[str, Any]:
    """Cached on the project's view revision (never a clock, per `cache.py`).

    `stale_ok` is how the workbench should ask (0.61.2). Measured on Kyle's live project while the app was locked
    up for him: this pass takes **11.5 s over 12,805 findings** — it was 3.8 s at 10,000, so it grows faster than
    the corpus — and the revision it caches on moves every time a finding lands, which during a findings run is
    constantly. A cache whose key changes faster than its value can be computed is not a cache, and the Findings
    tab was asking for eleven seconds of CPU in a single-process server on every visit.
    With `stale_ok` the previous answer comes back immediately, one background thread refreshes it, and the result
    says `as_of_current: False` so the screen can admit it is a moment behind rather than implying it is current.
    A duplicate count that is thirty seconds old is worth having; a locked application is not."""
    from . import cache, db as _db
    rev = json.dumps(_db.project_view_revision(project_id), sort_keys=True)
    key = f"findings_quality:{project_id}:{status}:{limit}:{int(include_used)}"

    def compute() -> dict[str, Any]:
        return _review(project_id, status=status, limit=limit, include_used=include_used)

    if not stale_ok:
        return cache.get_or_compute(key, rev, compute, label="findings_quality")
    got = cache.get_stale_ok(key, rev, compute, label="findings_quality", warm=warm)
    if got["value"] is None:
        return {}                        # nothing computed yet and we were told not to compute it in a request
    out = dict(got["value"] or {})
    out["as_of_current"] = bool(got["current"])
    out["recomputing"] = bool(got["pending"])
    return out


def _review(project_id: str, *, status: str | None = "approved", limit: int = 300,
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
    corroborated: dict[int, dict[str, Any]] = {}
    for c in cl:
        if c["kind"] == "redundant":
            for d in c["duplicate_ids"]:
                dup_of[d] = c["keeper_id"]
        else:
            for m in [c["keeper_id"], *c["duplicate_ids"]]:
                corroborated[m] = {"n_sources": c["n_sources"], "size": c["size"], "keeper_id": c["keeper_id"]}

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
        # protection 0: a finding several independent sources agree on is evidence, not filler. It is never
        # pre-selected, whatever else it trips, because a batch sweep must not be able to delete corroboration.
        corr = corroborated.get(n["id"])
        for f in fl:
            counts[f] = counts.get(f, 0) + 1
        # protection 1: anything the project has leaned on is not trash, whatever it reads like
        protected = None
        if corr:
            protected = (f"{corr['n_sources']} independent sources say this — that is corroboration, which is the "
                         f"strongest evidence signal this app has")
        elif used:
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
        "clusters": [c for c in cl if c["kind"] == "redundant"][:60],
        "cluster_count": sum(1 for c in cl if c["kind"] == "redundant"),
        "duplicates": len(dup_of), "protected": protected_n,
        # reported as a POSITIVE, in its own right: what several independent sources agree on
        "corroborated": {"findings": len(corroborated),
                         "groups": [{"n_sources": c["n_sources"], "size": c["size"], "keeper": c["keeper"],
                                     "ids": [c["keeper_id"], *c["duplicate_ids"]]}
                                    for c in cl if c["kind"] == "corroborated"][:40],
                         "note": ("Several independent sources saying the same thing is corroboration, not "
                                  "duplication — `claims.assess` counts exactly this as corroborative sufficiency. "
                                  "None of these is ever offered for dismissal.")},
        "counts": counts,
        "share": round(len(flagged) / total, 4) if total else 0.0,
        "note": ("Nothing here has been changed. A finding already used in a plan, a chat answer or a Claim is never "
                 "listed as trash; one you rated 4+ or already judged is listed but never pre-selected. Within a "
                 "duplicate group one finding is always kept."),
        "rules": {f: FLAG_TEXT[f] for f in FLAGS},
        "thresholds": {"near_jaccard": NEAR_JACCARD, "contain_ratio": CONTAIN_RATIO, "set_jaccard": SET_JACCARD,
                       "shingle": SHINGLE, "short_content_tokens": SHORT_CONTENT_TOKENS, "title_echo": TITLE_ECHO},
        "limits": ("Catches repeats, not paraphrases. Two findings stating the same fact in different words score "
                   "around 0.2 on every lexical measure used here and cannot be separated from findings that merely "
                   "share vocabulary; detecting those would need embeddings. So this list is a floor on the "
                   "duplicates you have, never a ceiling."),
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
    corroborates: dict[int, dict[str, Any]] = {}
    for c in cl:
        members = set(c["duplicate_ids"]) | {c["keeper_id"]}
        anchor_id = next((m for m in members if m in approved_ids), None)
        if anchor_id is None:
            continue
        for m in members:
            if m in approved_ids:
                continue
            if c["kind"] == "redundant":
                covered[m] = anchor_id          # the same source said it twice — nothing gained by promoting it
            else:
                # 0.59.0: a withheld finding that says what an approved finding says, from a DIFFERENT source, is
                # corroboration. Promoting it is the point, not the mistake — it is how a Claim gets from one
                # source to independently supported.
                corroborates[m] = {"of": anchor_id, "n_sources": c["n_sources"]}
    rows: list[dict[str, Any]] = []
    skipped = {"already_covered": 0, **{f: 0 for f in FLAGS if f != "duplicate"}}
    for n in reserve:
        if n["id"] in covered:
            skipped["already_covered"] += 1
            continue
        corr = corroborates.get(n["id"])
        fl = vacuity(n, titles.get(str(n.get("source_id"))))
        if fl == ["too_short"] and _has_specific(n.get("content") or ""):
            fl = []                                   # brevity is not vacuity (same rule as `review`)
        if fl and corr:
            # Corroboration outranks a vacuity flag here for the same reason it outranks a duplicate flag: if
            # another source independently says this, the sentence is carrying a real proposition whatever its
            # wording scores. `review` already protects these; the promote path must not quietly drop them.
            fl = []
        if fl:
            for f in fl:
                skipped[f] = skipped.get(f, 0) + 1
            continue
        rows.append({"id": n["id"], "content": n.get("content"), "title": n.get("title"),
                     "source_id": n.get("source_id"), "importance": n.get("importance"),
                     "corroborates": corr["of"] if corr else None,
                     "why": (f"a different source saying what an approved finding says — that is corroboration, "
                             f"and promoting it is how a Claim becomes independently supported"
                             if corr else
                             "not a repeat of anything you have approved, and it names something specific")})
    # corroborating findings first: they are the ones that change what the project can claim
    rows.sort(key=lambda r: (0 if r.get("corroborates") else 1, -int(r["importance"] or 0), r["id"]))
    return {"reserve": len(reserve), "promotable": len(rows), "rows": rows[:max(1, min(limit, 1000))],
            "corroborating": sum(1 for r in rows if r.get("corroborates")),
            "skipped": {k: v for k, v in skipped.items() if v},
            "note": ("These were withheld by the cap, not judged — you already paid for them. Listed here are the "
                     "ones that are not repeats of findings you have already approved and that name something "
                     "specific. Nothing is promoted until you press the button. The repeat check catches rewordings, "
                     "not paraphrases: a withheld finding that states an approved fact in entirely different words "
                     "will still be listed, so skim before approving in bulk."),
            "action": {"method": "POST", "endpoint": "/api/notes/bulk-status", "body": {"status": "approved"}}}


def summary(project_id: str, stale_ok: bool = True, warm: bool = False) -> dict[str, Any]:
    """The counts only — a chip in the Findings header, and the one place that must never block a screen, so it
    takes the previous answer by default (0.61.2)."""
    r = review(project_id, limit=1, stale_ok=stale_ok, warm=warm)
    if not r:
        return {"findings": 0, "pending": True,
                "note": "the duplicate check has not run for this project yet — it will appear shortly"}
    out = {k: r[k] for k in ("findings", "flagged", "duplicates", "cluster_count", "protected", "counts", "share")}
    out["corroborated"] = {"findings": (r.get("corroborated") or {}).get("findings", 0)}
    out["as_of_current"] = r.get("as_of_current", True)
    out["recomputing"] = r.get("recomputing", False)
    return out


def corroborated_ids(project_id: str, status: str | None = None) -> set[int]:
    """Every finding id that another SOURCE independently agrees with, across all statuses by default.

    `review()` reports corroboration as a count and a sample of groups because that is what a workbench banner
    needs. `cost_value` needs the ids, to ask how many of the findings written in a window turned out to be
    corroborated — so this is the same pass exposed as an index rather than a list rendered into a payload. Cached
    on the project's view revision like `review`, so asking both costs one pass."""
    from . import cache, db as _db, findings_view
    rev = json.dumps(_db.project_view_revision(project_id), sort_keys=True)

    def compute() -> set[int]:
        notes = _db.list_project_notes(project_id, status=status)
        cl = clusters(notes, findings_view.usage_map(project_id))
        out: set[int] = set()
        for c in cl:
            if c["kind"] == "corroborated":
                out.add(int(c["keeper_id"]))
                out.update(int(i) for i in c["duplicate_ids"])
        return out

    return cache.get_or_compute(f"findings_quality:corroborated:{project_id}:{status}", rev, compute,
                                label="findings_quality")
