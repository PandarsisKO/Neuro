"""Rank a channel's/playlist's proposed videos by relevance to the project — from titles and
descriptions only, before anything is downloaded — so the review card can pre-select the best N.

One Claude call per batch of ~80 titles (a few cents for a whole channel).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from . import db
from .config import settings

log = logging.getLogger(__name__)

POOL = 400          # never rank more than this many (newest first); keeps the cost bounded
BATCH = 80
BATCHES_PER_RUN = 2    # 0.55.1 — then the job hands its worker back (jobs.Yield). A 398-video channel is five
                       # batches at 59-92 s each: 5-8 minutes holding one of three AI workers while every findings
                       # job waits. Each batch's scores are persisted as it completes and `_pool` already re-ranks
                       # only what is still unscored, so stopping between batches costs nothing and resuming
                       # re-does nothing.

SYSTEM = """You are a research triage assistant scoring a list of videos for relevance BEFORE they are downloaded.
You only see each video's title, a snippet of its description, its length and view count — judge from that.
The description is often missing entirely; then the title is all there is, and a thin title is a reason to score
in the middle, not a reason to reject.

Score every video 0-100 for how likely it is to TEACH THIS PERSON SOMETHING THEY CAN USE.

CRITICAL — what you are judging. The project brief describes the OUTCOME this person wants: the kind of business
they intend to buy, their budget, their constraints, what they rule out. That is their buy-box. It is NOT a filter
on which content is useful to them. A video about a business they would never buy can be the most useful thing
they watch all week, because what transfers is the METHOD: how a deal was found, valued, financed, structured,
negotiated, diligenced or operated.

So never score a video low because the business IN it fails the brief's criteria. "Wrong industry", "not remote",
"too big", "physical rather than online", "they built it instead of buying it", "size mismatch" are NOT reasons to
reject, as long as the video still carries usable method, real numbers or first-hand experience.

Score on what it teaches:
- 85-100: concrete method, real numbers or first-hand experience on exactly what this person is doing
- 60-84: solid transferable method or experience, even when the business, industry or deal size differs
- 30-59: some usable substance mixed with filler, or a real topic covered thinly
- 0-29: genuinely nothing to learn — pure promotion, reaction/vlog filler, a near-duplicate of a better item, or a
  subject with no bearing on this project at all

The brief's constraints are a TIEBREAK, never a veto: between two videos of equal instructional value, prefer the
one closer to this person's own situation. A constraint mismatch alone never pushes an instructive video below 60.
Prefer depth over breadth: a 40-minute deep dive on the exact question beats a 3-minute clip.
Penalise obvious clickbait/sales pitches and near-duplicate titles (score the best one, mark the rest lower).

Return ONLY JSON: {"scores":[{"i":<index>,"score":<0-100>,"why":"<max 8 words>"}]} with one entry per index given.
Never use double quotes or backslashes inside "why" (write Boring not "Boring")."""


def _system_blocks(system: str, head: str) -> Any:
    from . import usage
    return [{"type": "text", "text": system}, usage.cached_block(head, min_chars=len(system))] if head else system


def _call(system: str, user: str, project_id: str | None, collection_id: str, head: str = "") -> dict[str, Any]:
    from . import providers, usage

    from .contracts import contract
    sys_blocks = _system_blocks(system, head)
    c = contract("rank.relevance")
    messages = [{"role": "user", "content": user}]
    if c.schema:
        # Mission F path: schema-enforced result, fully validated locally; typed failures propagate (a failed batch is
        # visible as failed_batches, never a silently "repaired" one)
        return providers.invoke_structured("rank.relevance", system=sys_blocks, messages=messages, usage_kind="rank", project_id=project_id,
                                           guard_estimate=0.02, legacy=parse_scores)
    usage.guard(0.02)
    resp = providers.invoke("rank.relevance", system=sys_blocks, messages=messages)
    usage.record_anthropic(resp, "rank", project_id=project_id)
    return parse_scores(providers.text_of(resp).strip())


ITEM_RE = re.compile(r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(\d+)\s*,\s*"why"\s*:\s*"(.*?)"\s*\}', re.S)


def parse_scores(text: str) -> dict[str, Any]:
    """Tolerant parse: strict JSON first, otherwise pull out every {"i":..,"score":..,"why":".."} object we can
    (the model occasionally puts a stray quote inside a reason or gets cut off, and one bad item should not
    sink a batch of 120)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    if s >= 0:
        try:
            data = json.loads(text[s:e + 1])
            if isinstance(data, dict) and isinstance(data.get("scores"), list):
                return data
        except ValueError:
            pass
    items = [{"i": int(i), "score": int(sc), "why": why.replace('\\"', '"').strip()} for i, sc, why in ITEM_RE.findall(text)]
    if not items:   # last resort: objects without a why
        items = [{"i": int(i), "score": int(sc)} for i, sc in re.findall(r'"i"\s*:\s*(\d+)\s*,\s*"score"\s*:\s*(\d+)', text)]
    return {"scores": items, "repaired": True}


def prompt_version() -> str:
    import hashlib
    return "rank-" + hashlib.sha1(SYSTEM.encode()).hexdigest()[:8]


def schema_version() -> str | None:
    from .contracts import contract
    return contract("rank.relevance").schema


def input_hash(project: dict[str, Any] | str, s: dict[str, Any]) -> str:
    """What the ranking actually judged: title, description snippet, length (to the minute), the brief, the prompt and
    the output schema. View count is deliberately left out — it changes on every metadata refresh and should not
    make a ranking stale."""
    return db._sha("relevance", s.get("title"), clean_description(s.get("description"))[:DESC_CHARS],
                   int((s.get("duration") or 0) // 60), db.brief_revision(project), prompt_version(),
                   schema_version() or "text")


DESC_CHARS = 400          # was 220, raised once descriptions actually existed to read (2026-09-20)

_URL_RE = re.compile(r"https?://\S+")
_CTA_RE = re.compile(r"\b(subscribe|newsletter|free training|join my|book a call|link (below|in bio)|"
                     r"follow me|my course|coupon|promo code|sponsored|affiliate|patreon|merch|"
                     r"dm me|apply (now|here)|sign up)\b", re.I)


def clean_description(d: str | None) -> str:
    """Strip a YouTube description's funnel so the snippet carries the video's actual subject.

    Measured on Kyle's project the day descriptions first existed: median description 1,883 chars, but the first
    220 -- all the ranker ever saw -- were promo for 25% of them. A real example, verbatim, and all of it inside
    the old window: "Learn How to Acquire Your First Boring Business: https://bit.ly/... Join My FREE Daily
    Newsletter: https://bit.ly/... In this video,". Two calls to action and two shortlinks before the first word
    about the content. Backfilling descriptions and then feeding the model THAT would have bought very little.

    Conservative on purpose: a line is dropped only when it is essentially a bare link, or a SHORT call to action
    (a long sentence that happens to contain the word "subscribe" is kept). URLs are stripped from lines that
    survive, because the ranker has no use for an address and every character of the window is contested."""
    out: list[str] = []
    for line in (d or "").splitlines():
        line = line.strip()
        if not line:
            continue
        bare = _URL_RE.sub("", line).strip()
        if _URL_RE.search(line) and len(bare) < 25:      # the line was a link with a short label
            continue
        # "Learn How to Acquire Your First Boring Business: <url>" survives every rule above -- it is long, and
        # it is a call to action phrased as a benefit, which no keyword list catches. But a line that carried a
        # URL and whose remaining text ends in a colon or dash IS a label for that link, whatever it says.
        if _URL_RE.search(line) and bare.rstrip().endswith((":", "-", "\u2014", "\u2013", "|", "\u27a1\ufe0f")):
            continue
        if _CTA_RE.search(line) and len(bare) < 120:     # a short plug, not a sentence about the video
            continue
        if bare:
            out.append(bare)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def _line(i: int, s: dict[str, Any]) -> str:
    bits = [f"[{i}] {s.get('title') or s.get('url')}"]
    if s.get("duration"):
        m = int(s["duration"] // 60)
        bits.append(f"({m} min)" if m else "(<1 min)")
    if s.get("view_count"):
        bits.append(f"{int(s['view_count']):,} views")
    d = clean_description(s.get("description"))
    if d:
        bits.append("— " + d[:DESC_CHARS])
    return " ".join(bits)


def _prov(project: dict[str, Any]) -> dict[str, Any]:
    from . import contracts, providers
    return {"model": "fake" if providers.fake() else contracts.contract("rank.relevance").model,
            "provider": "fake" if providers.fake() else "anthropic",
            "prompt_version": prompt_version(), "schema_version": schema_version() or "rank-v1",
            "brief_revision": db.brief_revision(project),
            "routing": providers.routing_json("rank.relevance", getattr(providers.last_response(), "model", None))}


def _job_started() -> float | None:
    """When the job now ranking was CREATED (a re-rank request, a fresh listing) — None outside a job."""
    try:
        from .jobs import current_job
        jid = current_job()[0]
        row = db.get_job(jid) if jid else None
        return float(row["created_at"]) if row and row.get("created_at") else None
    except Exception:  # noqa: BLE001 — never let bookkeeping stop a ranking
        return None


def _pool(rows: list[dict[str, Any]], since: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # 2026-09-18 (Kyle): a gated (members-only / premium / sign-in) video IS ranked — its relevance is what the
    # Candidate Index remembers, so a 90+ can be worth a membership — but it sorts last in the review and is never
    # auto-ticked (db.proposed_sources, the review card). Ranking is what makes the memory worth keeping.
    rows.sort(key=lambda r: r.get("created_at") or 0)      # listing order (newest first for channels)
    pool, rest = rows[:POOL], rows[POOL:]
    # Resume only what is still unscored BY THIS JOB. A score written before the job was created is the previous
    # ranking, not progress. 2026-09-23 (Kyle: "the new rankings seem to be looping again"): he pressed re-rank on two
    # fully-scored channels; each run ranked two batches, yielded, and the next run found nothing "unscored" — every
    # row already carried its OLD score — so it started from batch 0 again, forever (13 batches for a 5-batch list).
    def fresh(r: dict[str, Any]) -> bool:
        if r.get("relevance") is None:
            return False
        return since is None or (r.get("relevance_at") or 0) >= since
    unscored = [r for r in pool if not fresh(r)]
    if unscored and len(unscored) < len(pool):
        pool = unscored
    return pool, rest


def _head(project: dict[str, Any], want: int | None) -> str:
    # 2026-09-20: the steering block is shared with every other prompt and is written as the person's OWN
    # requirements ("must be operable remotely", "SDE at least $350k", "laundromats are rejected"). Handed to a
    # ranker unlabelled, that reads as a checklist each video's subject must satisfy — and it was being applied
    # that way: a blind review of 30 rejected candidates found Kyle would have kept 23 of them, with the model's
    # own reasons being "not remote", "size mismatch", "physical not online". Those are facts about a business,
    # not about whether a video teaches anything. The line below says which one it is, at the point of injection.
    return (f"PROJECT: {project['name']}\n{db.project_steering(project)}\n"
            "The block above is this person's SITUATION and BUY-BOX — what they are trying to end up with. Judge each\n"
            "video on what it would TEACH them, not on whether the business it features fits those criteria.\n"
            + (f"We only need about the best {want} videos.\n" if want else ""))


def _user(batch: list[dict[str, Any]]) -> str:
    return "VIDEOS:\n" + "\n".join(_line(i, s) for i, s in enumerate(batch)) + "\n\nScore them now."


def canonical_requests(collection_id: str, project_id: str, want: int | None = None) -> list[dict[str, Any]]:
    """The exact request content rank_collection would send right now — one {system, messages} per batch — built from
    the same helpers, so a token count over these is a token count over the real requests (E2 tokenizer deltas)."""
    project = db.get_project(project_id)
    rows = db.proposed_sources(collection_id, project_id)
    if not rows or not project:
        return []
    pool, _ = _pool(rows)
    head = _head(project, want)
    return [{"system": _system_blocks(SYSTEM, head), "messages": [{"role": "user", "content": _user(pool[b:b + BATCH])}]}
            for b in range(0, len(pool), BATCH)]


def rank_collection(collection_id: str, project_id: str | None, want: int | None = None,
                    progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """Score every proposed source in the collection and store relevance/relevance_why on each.
    Sources beyond POOL (oldest) get score 0 so they stay unticked."""
    project = db.get_project(project_id) if project_id else None
    rows = db.proposed_sources(collection_id, project_id)
    if not rows:
        return {"ranked": 0}
    if not project or not (project.get("brief") or project.get("goal") or project.get("questions")):
        # nothing to rank against: keep newest-first, mark as ranked so the UI stops waiting
        db.mark_review_ranked(collection_id, note="no brief to rank against — newest first")
        return {"ranked": 0, "skipped": "no brief"}
    pool, rest = _pool(rows, since=_job_started())
    head = _head(project, want)
    scored: dict[str, tuple[int, str]] = {}
    persisted: set[str] = set()
    failed_batches = repaired_batches = batches = 0
    yielding = False
    for b in range(0, len(pool), BATCH):
        if batches >= BATCHES_PER_RUN and b < len(pool):
            yielding = True                                 # durable progress is already written: leave
            break
        from .jobs import check_cancel
        check_cancel()                                      # safe boundary: the previous batch is persisted, this one not started
        batches += 1
        batch = pool[b:b + BATCH]
        done_now = min(b + BATCH, len(pool))
        if progress:
            progress(max(0.02, b / len(pool)), f"ranking {b + 1}-{done_now} of {len(pool)}")
        user = _user(batch)
        try:
            res = _call(SYSTEM, user, project_id, collection_id, head=head)
        except Exception as e:  # noqa: BLE001
            from .breakers import ProviderUnavailable
            from .providers import LOCAL_TYPES, ProviderError
            from .usage import BudgetPaused
            if isinstance(e, (BudgetPaused, ProviderUnavailable)):
                raise
            if isinstance(e, ProviderError) and e.error_type in LOCAL_TYPES:
                # 2026-09-23 (Kyle: "stuck in a loop of starting and stopping the ranking"). The local CLI was not
                # reachable at all (`claude` not on the LaunchAgent's PATH), so every batch failed in milliseconds,
                # nothing was persisted, and the run reached the yield below with zero progress -- requeued at once,
                # started from batch 0 again, 1,800+ times in ten minutes. A transport that is DOWN is not a batch
                # that failed: hand it to jobs.execute, which parks the job for 60 s with the honest local-AI-
                # unavailable message instead of counting it as a scored-nothing pass.
                raise
            log.warning("rank batch %d failed: %s", b // BATCH, e)
            failed_batches += 1
            continue
        repaired_batches += 1 if res.get("repaired") else 0
        for it in res.get("scores") or []:
            try:
                i = int(it.get("i")); sc = max(0, min(100, int(it.get("score", 0))))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(batch):
                scored[batch[i]["id"]] = (sc, str(it.get("why") or "")[:80])
        # persist THIS batch before going round again, so yielding (or dying) never loses a paid call
        bprov = _prov(project)
        with db.batch():
            for s_ in batch:
                if s_["id"] in scored:
                    sc, why = scored[s_["id"]]
                    db.set_relevance(s_["id"], sc, why, project_id=project_id, input_hash=input_hash(project, s_), **bprov)
                    persisted.add(s_["id"])
        if progress:                                       # the bar moves when a batch is actually scored, not when one starts
            progress(min(0.99, done_now / len(pool)), f"ranked {len(scored)} of {len(pool)}")
    if yielding and persisted:
        # Yield's contract: durable progress is written and the next run skips it (_pool re-ranks only what is still
        # unscored). A run that persisted NOTHING has no such progress, so yielding would restart it identically and
        # forever; it falls through instead and finishes with the "could not be scored — press re-rank" note.
        from .jobs import Yield
        raise Yield(f"ranked {len(persisted)} of {len(pool)} — paused so other work can run, continues automatically")
    from . import contracts, providers
    prov = _prov(project)
    with db.batch():
        for s in pool:
            if s["id"] in persisted:
                continue                                    # already written by its own batch
            if s["id"] in scored:
                sc, why = scored[s["id"]]
                db.set_relevance(s["id"], sc, why, project_id=project_id, input_hash=input_hash(project, s), **prov)
            elif failed_batches:
                db.set_relevance(s["id"], None, None, project_id=project_id)      # leave unscored rather than pretend it's a 0
            else:
                db.set_relevance(s["id"], 0, "not scored", project_id=project_id, input_hash=input_hash(project, s), **prov)
        for s in rest:
            db.set_relevance(s["id"], 0, "beyond ranking pool (older)", project_id=project_id, input_hash=input_hash(project, s), **prov)
    note = None
    if failed_batches or len(scored) < len(pool):
        note = f"{len(pool) - len(scored)} of {len(pool)} videos could not be scored — press re-rank to try those again."
    # 0.63.0: how many sources disappeared while this was ranking. Before the guard in `db.upsert_analysis`, one of
    # them raised FOREIGN KEY and took the whole batch with it; now the ranking survives and the count is stated.
    vanished = sum(1 for s in rows if not db.analysis_writable(project_id, s["id"])) if project_id else 0
    if vanished:
        note = (note + " · " if note else "") + f"{vanished} source(s) were removed while this was ranking"
    db.mark_review_ranked(collection_id, note=note)
    return {"ranked": len(scored), "pool": len(pool), "unranked": len(rest), "batches": batches,
            "failed_batches": failed_batches, "repaired_batches": repaired_batches}
